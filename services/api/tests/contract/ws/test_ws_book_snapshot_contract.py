"""#2196: the book module's `SnapshotSource` against `23-ws-protocol.md` §14.1 (`ws-schema.json`):
through the real `/ws` router, where the client validates every frame (`_harness`), and over the
recorded BTCUSDT corpus replayed through the production `BookStream` and wiring."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.book.models import BookPhase
from candleviewer.bus.bus import Bus
from candleviewer.exchange.bybit.orderbook import book_topic, parse_book_frame
from candleviewer.orderbook_wiring import BookStream
from candleviewer.ws.binary import decode_b64
from candleviewer.ws.cvwb_vectors import structured
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.sequencing import MAX_OUTBOUND_FRAME_BYTES, render
from candleviewer.ws.topics import parse_topic
from candleviewer.ws_wiring import SnapshotRouter, book_snapshot_source
from tests._corpus import TICKS, frames
from tests.contract.ws import _harness as h
from tests.unit.ws._seq_support import Book

BOOK = "cv://ws/v1/book.schema.json"
#: The instrument the corpus was recorded under (`rest/instruments_before.json`).
INSTRUMENT = SimpleNamespace(tick_size=TICKS[h.SYM], qty_step=Decimal("0.001"))
RAW = frames("ws/orderbook_BTCUSDT.jsonl")
#: The first frame, a venue snapshot: its cross sequence `seq` is not its `u`.
FIRST = json.loads(RAW[0])["data"]
CH = f"book.{h.SYM}.50"


async def _noop(_: object = None) -> None:
    return None


def _stream() -> tuple[BookStream, Any]:
    """A production `BookStream` holding the symbol's demand, and an app context exposing it."""
    stream = BookStream(
        bus=Bus(), env="live", set_desired=lambda _t: None, topic_for=book_topic,
        parse_frame=lambda f: parse_book_frame(f, TICKS.get), resubscribe=_noop,
        is_listed=lambda _s: True, touch=lambda _t: None, clock=lambda: 0.0,
        now_us=lambda: 0, rand=lambda: 0.0,
    )  # fmt: skip
    stream.acquire("contract", h.SYM)
    catalogue = SimpleNamespace(snapshot=lambda: {h.SYM: INSTRUMENT})
    return stream, SimpleNamespace(ingestion=SimpleNamespace(books=stream, instruments=catalogue))


def _live_world() -> h.World:
    """The conformance world with the corpus's first book live and `book` served by the real
    adapter and wiring."""
    stream, ctx = _stream()
    asyncio.run(stream.handle_frame(RAW[0]))
    w = h.World()
    w.registry.services.snapshots = SnapshotRouter({"book": book_snapshot_source(ctx)})
    return w


def _decimals(levels: Any) -> list[tuple[Decimal, Decimal]]:
    return [(Decimal(p), Decimal(q)) for p, q in levels]


@pytest.mark.parametrize("mode", h.MODES)
@pytest.mark.parametrize("offer", h.OFFERS.values(), ids=h.OFFERS.keys())
def test_contract_live_book_snap_validates_on_the_wire(offer: list[str], mode: str) -> None:
    ref = Book(h.SYM)
    ref.apply(FIRST["b"], FIRST["a"])
    with h.connect(_live_world(), offer) as c:
        assert c.sub(h.entry("book", ("symbol", "depth"), mode))["p"]["results"][0]["ok"]
        body = h.structured_of(c.next_of("snap"))  # the envelope and §14.1 payload validated
    bids, asks = ref.top(50)
    assert _decimals(body["bids"]) == _decimals(bids.items())
    assert _decimals(body["asks"]) == _decimals(asks.items())
    assert body.get("stale", False) is False
    assert (body["price_scale"], body["qty_scale"]) == (1, 3)  # tick 0.1 and qty step 0.001
    assert (body["xu"], body["xseq"]) == (FIRST["u"], FIRST["seq"])


def test_contract_snapshot_false_on_a_live_book_is_forced_to_a_snap() -> None:
    """§7.6, §7.7: book continuity is never claimed, so a delta-only attach to a live book is
    answered `snapshot_forced` and gets a `snap`, even naming the book's `u` and the time now."""
    w = _live_world()
    attach = {"ch": CH, "opts": {"from_seq": FIRST["u"], "from_ts_ms": w.clock.wall_ms()}}
    with h.connect(w) as c:
        res = c.sub(attach, snapshot=False)["p"]["results"][0]
        assert res["ok"] and res.get("snapshot_forced") is True and res["snapshot_pending"]
        assert h.structured_of(c.next_of("snap"))["xu"] == FIRST["u"]


def test_contract_book_without_marketdata_read_is_forbidden_and_never_snapped() -> None:
    w = _live_world()
    w.perms = h.ALL_PERMS - {Permission.MARKETDATA_READ}
    with h.connect(w) as c:
        res = c.sub(CH)["p"]["results"][0]
        assert res["ok"] is False and res["error"]["code"] == "forbidden"
        c.send({"t": "ping", "id": "p"})
        assert c.recv()["t"] == "pong"  # nothing came before it: no `snap`


@pytest.mark.parametrize(
    "instruments",
    [None, SimpleNamespace(snapshot=lambda: None), SimpleNamespace(snapshot=dict)],
    ids=["no-scheduler", "no-catalogue-yet", "not-listed"],
)
async def test_contract_no_instrument_means_no_book_snapshot(instruments: Any) -> None:
    stream, ctx = _stream()
    await stream.handle_frame(RAW[0])
    ctx.ingestion.instruments = instruments  # no scales to announce
    assert book_snapshot_source(ctx).build(Subscription("s", parse_topic(CH), {}, {})) is None


async def test_contract_replayed_corpus_snapshots_validate_and_never_span_the_hole() -> None:
    """Frames 0-2700 (a `u` gap at 2700), then the venue's re-snapshot (frame 4000, `u` back to
    1) and its deltas: every LIVE snapshot equals an independent top-50, validates in both forms
    with the frame's `u` and its venue snapshot's `seq`, none is built across the hole, and the
    generation moves on every frame."""
    stream, ctx = _stream()
    src = book_snapshot_source(ctx)
    subs = {m: Subscription(m, parse_topic(CH), {}, {"encoding": m}) for m in h.MODES}
    ref, generations, built, held, xseq = Book(h.SYM), [0], 0, 0, None
    for i, line in enumerate(RAW[:2701] + RAW[4000:]):
        await stream.handle_frame(line)
        msg = json.loads(line)
        data = msg["data"]
        xseq = data["seq"] if msg["type"] == "snapshot" else xseq
        ref.apply(data["b"], data["a"], reset=i in (0, 2701))
        generations.append(src.generation(subs["structured"]))
        assert generations[-1] > generations[-2]
        if stream.phase(h.SYM) is not BookPhase.LIVE:
            assert src.build(subs["structured"]) is None
            held += 1
            continue
        if i % 100 and i not in (2699, 2701):
            continue
        body = src.build(subs["structured"])
        assert body is not None
        bids, asks = ref.top(50)
        assert _decimals(body.structured["bids"]) == _decimals(bids.items())
        assert _decimals(body.structured["asks"]) == _decimals(asks.items())
        for mode, sub in subs.items():
            out = render(sub, body, MAX_OUTBOUND_FRAME_BYTES)
            wire = out.payload or {"symbol": h.SYM, **structured(decode_b64(out.parts[0]))}
            h.check_schema(BOOK, wire, f"frame {i} ({mode})")
            assert (wire["xu"], wire["xseq"]) == (data["u"], xseq), (i, mode)
        built += 1
    assert held == 1 and built > 30
