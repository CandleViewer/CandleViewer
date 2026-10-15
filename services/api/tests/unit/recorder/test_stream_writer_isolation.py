"""E16-T03: per-lane sinks (real `IlpWriter`), and the no-loss/no-dup property including drops
and corruption."""

from __future__ import annotations

import asyncio
import itertools
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.recorder.writer import STREAMS, Stream, StreamWriter, WriterConfig
from candleviewer.storage.questdb.ilp_writer import IlpWriter
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS
from tests.unit.recorder._writer_helpers import (
    OPEN_GATE,
    T0,
    FakeClock,
    FakeEvents,
    FakeStore,
    FsyncCounter,
    delta,
    make_writer,
    trade,
)


class _StallableTransport:
    """In-memory `IlpTransport`; `gate` (when set) blocks `write` like a stalled socket."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.gate: asyncio.Event | None = None

    async def connect(self) -> None:
        return None

    async def write(self, data: bytes) -> None:
        if self.gate is not None:
            await self.gate.wait()
        self.lines.extend(data.decode().splitlines())

    async def close(self) -> None:
        return None


async def test_stalled_lane_on_real_ilp_writer_does_not_block_trades(tmp_path: Path) -> None:
    """Scenario: orderbook_deltas writes stall; trades keep their 200 ms cadence, because each
    lane owns its own `IlpWriter` (connection, lock and queue bound)."""
    transports: dict[Stream, _StallableTransport] = {s: _StallableTransport() for s in STREAMS}

    def factory(stream: Stream) -> IlpWriter:
        return IlpWriter(transports[stream], ALL_SCHEMAS)

    clock = FakeClock()
    w = StreamWriter(
        factory,
        FakeStore(),
        FakeEvents(),
        WriterConfig(wal_dir=tmp_path / "wal", write_timeout_s=60.0),
        clock=clock,
        wall_clock_us=lambda: T0,
        fsync=FsyncCounter(),
        disk_gate=OPEN_GATE,
    )
    await w.open()
    w.seed(["BTCUSDT"])
    transports["orderbook_deltas"].gate = asyncio.Event()
    await w.on_book_delta(delta(1))
    await w.on_trade(trade(1))
    clock.advance(0.2)
    stalled = asyncio.create_task(w.pump("orderbook_deltas"))
    await asyncio.sleep(0)
    for _ in range(3):  # three 200 ms cycles while deltas are stuck
        await w.pump("trades")
        await w.on_trade(trade(len(transports["trades"].lines) + 2))
        clock.advance(0.2)
    assert len(transports["trades"].lines) == 3
    assert all(line.startswith("trades,") for line in transports["trades"].lines)
    assert not stalled.done()
    transports["orderbook_deltas"].gate.set()
    await stalled
    assert len(transports["orderbook_deltas"].lines) == 2


async def test_remainder_after_full_batch_flushes_promptly(tmp_path: Path) -> None:
    w, sink, *_ = await make_writer(tmp_path, flush_rows=3)
    for i in range(5):
        await w.on_trade(trade(i))
    await w.pump("trades")  # full batch of 3 goes; the remainder is not yet due
    assert len(sink.rows("trades")) == 3
    w._clock.advance(0.2)  # type: ignore[attr-defined]
    await w.pump("trades")  # aged from its first row, not from the last flush
    assert len(sink.rows("trades")) == 5


# --- property: every event lands exactly once, or is covered by exactly one gap ------------

_OPS = st.lists(
    st.sampled_from(
        ["event", "event", "event", "event", "down", "up", "tick", "recover", "corrupt"]
    ),
    min_size=1,
    max_size=50,
)


@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(ops=_OPS, cap_frames=st.sampled_from([3, 8, 10_000]))
async def test_property_every_event_written_once_or_covered_by_a_gap(
    tmp_path_factory: pytest.TempPathFactory, ops: list[str], cap_frames: int
) -> None:
    tmp = tmp_path_factory.mktemp("prop")
    from candleviewer.recorder.wal import encode_frame
    from candleviewer.recorder.writer import trade_records

    frame = len(encode_frame(trade_records(trade(10))[0]))
    w, sink, store, _, clock = await make_writer(
        tmp, max_queue_rows=4, flush_rows=3, wal_max_bytes=frame * cap_frames, replay_chunk_rows=2
    )
    spill = tmp / "wal" / "trades" / "spill.wal"
    n = 0
    for op in ops:
        if op == "event":
            await w.on_trade(trade(n))
            n += 1
        elif op == "down":
            sink.down.add("*")
        elif op == "up":
            sink.down.clear()
        elif op == "tick":
            clock.advance(0.25)
            await w.pump("trades")
        elif op == "corrupt":
            await w.pump("trades")  # flush the spill buffer, then damage the last frame
            if spill.exists() and spill.stat().st_size > 8:
                data = bytearray(spill.read_bytes())
                data[-1] ^= 0xFF
                spill.write_bytes(bytes(data))
        else:
            await w.recover()
    sink.down.clear()
    await w.recover()
    await w.stop()
    got = [str(r["trade_id"]) for r in sink.rows("trades")]
    assert len(got) == len(set(got)), "duplicate row"
    written = {int(t[1:]) for t in got}
    windows = [(g["start"], g["end"]) for g in store.gaps]
    from datetime import timedelta

    from candleviewer.recorder.writer import _EPOCH

    def covered(i: int) -> int:
        ts = _EPOCH + timedelta(microseconds=T0 + i)
        return sum(1 for lo, hi in windows if lo <= ts <= hi)

    for i in range(n):
        if i in written:
            continue
        assert covered(i) >= 1, f"event {i} neither written nor covered by a gap"
    # Gap windows of one (symbol, stream) never overlap: each lost event is in exactly one row.
    spans = sorted(windows)
    for (_, hi), (lo, _) in itertools.pairwise(spans):
        assert lo >= hi
