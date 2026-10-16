"""E08-X02 (c)+(d): decoding abuse and resource exhaustion. Register sections C, D.

Memory is measured with tracemalloc; time is a fake clock. No sleeps, no network.
"""

from __future__ import annotations

import asyncio
import gc
import statistics
import time
import tracemalloc
import zlib
from typing import Any
from urllib.parse import urlsplit

import pytest
from websockets.exceptions import PayloadTooBig
from websockets.extensions.permessage_deflate import PerMessageDeflate
from websockets.frames import Frame, Opcode

# nosemgrep: cv-adapter-isolation reason=X02 owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit import public_ws
from candleviewer.ingestion import metrics as im
from candleviewer.ingestion.connection import MAX_FRAME_BYTES
from candleviewer.ingestion.reconnect import ConnectionRateGuard
from candleviewer.ingestion.service import WS_FRAME_QUEUE_MAXSIZE, IngestionService
from candleviewer.observability.context import spawn
from tests.security.ingestion._harness import Rig
from tests.security.ingestion.corpus import TRADES, TS, book


class _Conn:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    async def recv(self, decode: bool = True) -> str:
        return self.payload


async def test_oversized_frame_refused_by_socket_adapter() -> None:
    sock = public_ws._WsSocket(_Conn("x" * (MAX_FRAME_BYTES + 1)))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="max_bytes"):
        await sock.recv(MAX_FRAME_BYTES)


async def test_ws_client_bounds_frames_before_buffering(monkeypatch: pytest.MonkeyPatch) -> None:
    # The library enforces `max_size` on the wire (and on the *decompressed* size
    # when permessage-deflate is negotiated) before the frame is buffered/parsed.
    seen: dict[str, Any] = {}

    async def fake_connect(url: str, **kw: Any) -> object:
        seen.update(kw, url=url)
        return object()

    import websockets.asyncio.client as client

    monkeypatch.setattr(client, "connect", fake_connect)
    await public_ws.public_socket_factory("live", max_frame_bytes=MAX_FRAME_BYTES)()
    assert seen["max_size"] == MAX_FRAME_BYTES
    parts = urlsplit(seen["url"])
    assert parts.scheme == "wss"
    assert parts.hostname == "stream.bybit.com"


def test_deflate_bomb_is_capped_at_max_size() -> None:
    # Default client offers permessage-deflate, so it may be negotiated: a 48 KB
    # frame inflating to 50 MB must abort at MAX_FRAME_BYTES, not materialise.
    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    body = (comp.compress(b"\0" * 50_000_000) + comp.flush(zlib.Z_SYNC_FLUSH))[:-4]
    ext = PerMessageDeflate(False, False, 15, 15)
    tracemalloc.start()
    try:
        with pytest.raises(PayloadTooBig):
            ext.decode(Frame(Opcode.TEXT, body, rsv1=True), max_size=MAX_FRAME_BYTES)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 8 * MAX_FRAME_BYTES


def test_frame_queue_is_bounded_and_overflow_is_signalled() -> None:
    svc, rig = IngestionService(), Rig()
    svc.attach_trades(rig.trades)
    rig.trades._last_ts["BTCUSDT"] = 1  # a print was published before the flood
    for _ in range(WS_FRAME_QUEUE_MAXSIZE + 500):
        svc.offer_frame(TRADES[0])
    assert svc.ws_frames.qsize() == WS_FRAME_QUEUE_MAXSIZE
    assert svc.ws_frames_dropped == 500
    assert "BTCUSDT" in rig.trades.open_gaps()  # loss is visible, never silent


async def test_many_symbols_in_one_frame_rejected() -> None:
    rig = Rig()
    rows = ",".join(
        f'{{"s":"S{i:05d}USDT","i":"t{i}","T":{TS},"p":"1","v":"1","S":"Buy"}}' for i in range(1500)
    )
    await rig.feed(f'{{"topic":"publicTrade.BTCUSDT","ts":{TS},"data":[{rows}]}}')
    assert rig.drain() == []


def test_symbol_label_cardinality_folds_to_other() -> None:
    im.reset_symbol_universe()
    try:
        labels = {im.symbol_label(f"X{i:06d}USDT") for i in range(10_000)}
        assert len(labels) <= im.MAX_SYMBOLS + 1 and im.OTHER_SYMBOL in labels
        assert im.symbol_label("<script>") == im.OTHER_SYMBOL
    finally:
        im.reset_symbol_universe()


def test_resubscribe_thrash_is_rate_guarded() -> None:
    now = [0.0]
    guard = ConnectionRateGuard(lambda: now[0], limit=480, window_s=300.0)
    delays = [guard.reserve() for _ in range(5_000)]
    assert delays[479] == 0.0 and delays[480] > 0.0  # paced past the per-IP budget
    assert len(guard._opens) <= 480


async def test_subscribe_unsubscribe_thrash_has_no_unbounded_growth() -> None:
    rig = Rig()

    async def cycle(n: int) -> None:
        for i in range(n):
            rig.now_s += 120.0  # past the grace window every cycle (fake clock)
            for s in (rig.trades, rig.tickers, rig.books):
                s.release("x02", "BTCUSDT")
                s.acquire(f"c{i}", "BTCUSDT")
            await rig.feed(TRADES[i % len(TRADES)])
            await rig.feed(book("snapshot", 1, [["100.0", "1"]], [["100.1", "1"]]))
            rig.drain()
            for s in (rig.trades, rig.tickers, rig.books):
                s.release(f"c{i}", "BTCUSDT")
                s.acquire("x02", "BTCUSDT")

    tracemalloc.start()
    try:
        await cycle(1_500)  # fills the bounded recent-tape deque / dedupe ring
        gc.collect()
        plateau, _ = tracemalloc.get_traced_memory()
        await cycle(1_500)
        gc.collect()
        after, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert after - plateau < 64 * 1024, f"grew {after - plateau} B after the plateau"


@pytest.mark.xfail(strict=True, reason="#1893 frame pump never yields while frames are queued")
async def test_never_idle_stream_does_not_starve_loop() -> None:
    svc, rig = IngestionService(), Rig()
    svc.attach_trades(rig.trades)
    for i in range(2_000):
        svc.offer_frame(TRADES[i % len(TRADES)])
    observed: list[int] = []

    async def other() -> None:
        while True:
            observed.append(svc.ws_frames.qsize())
            await asyncio.sleep(0)

    o = spawn(other(), name="x02-other")
    await asyncio.sleep(0)
    p = spawn(svc._pump_frames(), name="x02-pump")
    for _ in range(3):
        await asyncio.sleep(0)
    p.cancel()
    o.cancel()
    await asyncio.gather(p, o, return_exceptions=True)
    assert any(0 < q < 2_000 for q in observed), observed[:5]


#: Samples for the huge-exponent budget, each timed with the collector quiesced: the median
#: must fit, so one runner stall cannot fail it, while the >1 s regression it guards (#1893)
#: puts every sample over the budget (#2714). The 50 ms budget itself is unchanged.
_HUGE_EXPONENT_SAMPLES = 5


@pytest.mark.perf
# fixed by #1898 (#1893): huge-exponent prices cost >1 s of loop CPU
async def test_huge_exponent_levels_rejected_cheaply() -> None:
    frame = book("snapshot", 1, [["1e4200", "1"]] * 1000, [])
    timings = []
    for _ in range(_HUGE_EXPONENT_SAMPLES):
        rig = Rig()  # a fresh rig per sample: nothing from the last feed is cached
        gc.collect()
        gc.disable()
        try:
            t0 = time.perf_counter()
            await rig.feed(frame)
            timings.append(time.perf_counter() - t0)
        finally:
            gc.enable()
    median = statistics.median(timings)
    assert median < 0.05, f"median of {_HUGE_EXPONENT_SAMPLES}: {sorted(timings)}"
