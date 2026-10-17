"""#2196: the book module's WS `SnapshotSource` (`23-ws-protocol.md` §6.1, §7; B14), on real
engines, with a fake published phase where a test needs a state the engine never holds."""

from __future__ import annotations

import gc
import weakref
from decimal import Context, Decimal, localcontext

import pytest

from candleviewer.book.models import BookPhase
from candleviewer.book.resync import BookEngine
from candleviewer.book.snapshot_source import BookSnapshotSource
from candleviewer.exchange.base.models import BookLevel
from candleviewer.ws.binary import BOOK_SNAPSHOT
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.sequencing import MAX_OUTBOUND_FRAME_BYTES, SnapshotBody, SnapshotCache
from candleviewer.ws.topics import parse_topic
from candleviewer.ws_wiring import book_snapshot_body

from ._builders import delta, lvl, snap

STEPS = (Decimal("0.1"), Decimal("0.001"))
RS = "bb000000-0000-4000-8000-000000000001"
Levels = tuple[BookLevel, ...]
BOOK: tuple[Levels, Levels] = ((lvl(999, "1.5"), lvl(998, "2")), (lvl(1001, "0.25"),))


async def _noop(_: object = None) -> None:
    return None


async def _live(
    depth: int = 200, u: int = 10, xseq: int = 4_242, levels: tuple[Levels, Levels] = BOOK
) -> BookEngine:
    """A `live` engine whose snapshot's cross sequence (`xseq`) is not its `u`."""
    eng = BookEngine(symbol="BTCUSDT", depth=depth, publish=_noop, resubscribe=_noop,
                     now_us=lambda: 0)  # fmt: skip
    await eng.start()
    ev = snap(u, [*levels[0]], [*levels[1]], depth)
    await eng.on_event(ev.model_copy(update={"cross_seq": xseq}))
    return eng


def _sub(ch: str = "book.BTCUSDT.50", replay: str | None = None, **opts: int) -> Subscription:
    return Subscription("s1", parse_topic(ch), opts, {}, replay_session_id=replay)


class _World:
    def __init__(self, eng: BookEngine, steps: tuple[Decimal, Decimal] | None = STEPS) -> None:
        self.engines = {"BTCUSDT": eng}
        self.src: BookSnapshotSource[SnapshotBody] = BookSnapshotSource(
            self.engines.get, lambda _s: steps, book_snapshot_body
        )


@pytest.mark.parametrize(
    ("steps", "scales"),
    [(("0.1", "0.001"), (1, 3)), (("1", "1"), (1, 3)), (("0.01", "0.0001"), (2, 4))],
)
async def test_live_book_builds_a_fresh_exact_snapshot_in_both_forms(
    steps: tuple[str, str], scales: tuple[int, int]
) -> None:
    eng = await _live()
    await eng.on_event(delta(11, 10, [lvl(997, "0.001")]))
    w = _World(eng, (Decimal(steps[0]), Decimal(steps[1])))
    body = w.src.build(_sub())
    assert body is not None and body.stale is False
    assert (body.price_scale, body.qty_scale) == scales  # instrument step, raised to every level
    assert body.structured == {
        "symbol": "BTCUSDT", "depth": 50, "xu": 11, "xseq": 4242,
        "bids": [["99.9", "1.5"], ["99.8", "2"], ["99.7", "0.001"]], "asks": [["100.1", "0.25"]],
    }  # fmt: skip
    (part,) = body.parts
    ps, qs = (10**s for s in scales)
    assert part.body_kind == BOOK_SNAPSHOT and part.trailer == (11, 4242)  # `xu`, then `xseq`
    assert part.records == (
        (0, 999 * ps // 10, 1500 * qs // 1000), (0, 998 * ps // 10, 2 * qs),
        (0, 997 * ps // 10, qs // 1000), (1, 1001 * ps // 10, 250 * qs // 1000),
    )  # fmt: skip


async def test_only_a_live_book_is_served() -> None:
    """B14 tags only `live` consumable: a book held outside it is never served,
    so `stale` stays false (no freshness signal exists yet). Each phase is a state of its own."""
    eng = await _live()
    w = _World(eng)
    seen = [w.src.generation(_sub())]
    for phase in (BookPhase.INIT, BookPhase.SNAPSHOT_PENDING, BookPhase.DESYNCED):
        eng.phase = phase  # fake phase: the book is still held
        assert w.src.build(_sub()) is None, phase
        seen.append(w.src.generation(_sub()))
    eng.phase = BookPhase.LIVE
    body = w.src.build(_sub())
    assert body is not None and body.stale is False and seen == sorted(set(seen))
    held, eng.book = eng.book, None  # fake: `live` without a book, which the engine never is
    assert w.src.build(_sub()) is None
    eng.book = held
    await eng.on_event(delta(13, 12))  # a gap: the engine drops its book and resyncs (C-2.5)
    assert eng.phase is BookPhase.SNAPSHOT_PENDING and w.src.build(_sub()) is None


async def test_depth_is_the_topic_depth_capped_at_the_engine_tier() -> None:
    eng = await _live(depth=50)
    more = [lvl(900 - i, 1) for i in range(60)], [lvl(1100 + i, 1) for i in range(60)]
    await eng.on_event(delta(11, 10, *more))  # the engine holds up to twice its tier
    w = _World(eng)
    for ch, n in (("book.BTCUSDT.500", 50), ("book.BTCUSDT.200", 50), ("book.BTCUSDT.1", 1)):
        body = w.src.build(_sub(ch))
        assert body is not None and body.structured["depth"] == n
        assert len(body.structured["bids"]) == len(body.structured["asks"]) == n
        assert len(body.parts[0].records) == 2 * n
    top = w.src.build(_sub("book.BTCUSDT.1"))
    assert top is not None and top.structured["bids"] == [["99.9", "1.5"]]
    assert top.structured["asks"] == [["100.1", "0.25"]]


async def test_replay_unknown_symbol_or_instrument_gets_no_live_book() -> None:
    eng = await _live()
    w = _World(eng)
    assert w.src.build(_sub(replay=RS)) is None  # the live book is never a replay state
    assert w.src.generation(_sub(replay=RS)) == 0 and not w.src.continuity(_sub(replay=RS), 0)
    assert w.src.build(_sub("book.ETHUSDT.50")) is None
    assert _World(eng, None).src.build(_sub()) is None  # no instrument: no scales to announce


async def test_generation_moves_with_every_book_change_and_never_goes_back() -> None:
    eng = await _live(u=10)
    w = _World(eng)
    sub = _sub()
    seen = [w.src.generation(sub)]
    assert w.src.generation(sub) == seen[0]  # same state, same generation (a cache hit)
    await eng.on_event(delta(11, 10, [lvl(997, 1)]))
    seen.append(w.src.generation(sub))
    await eng.on_event(delta(13, 12))  # a gap and its rebuild at the same `u`, unseen between
    await eng.on_event(snap(11, [lvl(999, 1)], [lvl(1001, 1)]))
    seen.append(w.src.generation(sub))
    await eng.on_event(delta(13, 12))  # rebuilding
    seen.append(w.src.generation(sub))
    await eng.on_event(snap(5, [lvl(999, 1)], [lvl(1001, 1)]))  # a lower `u` (venue reset)
    seen.append(w.src.generation(sub))
    w.engines["BTCUSDT"] = await _live(u=5)  # a new tier engine at the same `u`
    seen.append(w.src.generation(sub))
    assert seen == sorted(set(seen)), seen
    assert w.src.generation(_sub("book.ETHUSDT.50")) == 0


async def test_an_engine_swap_at_the_same_u_and_resync_count_is_a_new_state() -> None:
    """A new tier engine replacing one that never desynced has the same `u`, resync count and
    phase: only its identity tells them apart, and the cache must not serve the old tier."""
    w, cache, sub = _World(await _live(depth=200)), SnapshotCache(), _sub("book.BTCUSDT.500")

    def served_depth() -> object:
        rendered = cache.get(sub, w.src, MAX_OUTBOUND_FRAME_BYTES)
        assert rendered is not None and rendered.payload is not None
        return rendered.payload["depth"]

    before = w.src.generation(sub), served_depth()
    w.engines["BTCUSDT"] = await _live(depth=50)
    after = w.src.generation(sub), served_depth()
    assert after[0] > before[0] and (before[1], after[1]) == (200, 50)


async def test_the_adapter_keeps_no_engine_alive() -> None:
    """One entry per engine, dropped with it: a replaced tier engine is freed."""
    w = _World(await _live())
    w.src.generation(_sub())  # the adapter now holds an entry for the engine
    gone = weakref.ref(w.engines.pop("BTCUSDT"))
    gc.collect()
    assert gone() is None


@pytest.mark.parametrize(
    ("price", "qty", "scales", "record"),
    [  # qty_scale 18; the largest i64 price; the largest u64 size
        ("99.7", "0.000000000000000001", (1, 18), (0, 997, 1)),
        ("92233720368.54775807", "1", (8, 3), (0, 2**63 - 1, 1000)),
        ("99.7", "184467440737.09551615", (1, 8), (0, 997, 2**64 - 1)),
    ],
    ids=["qty-scale-18", "price-at-i64-max", "size-at-u64-max"],
)
async def test_values_at_the_section_14_1_and_kind_1_limits_are_served_exactly(
    price: str, qty: str, scales: tuple[int, int], record: tuple[int, int, int]
) -> None:
    """Plain decimals in the payload (`str` would write "1E-18") and exact kind-1 records,
    whatever the caller's decimal context."""
    eng = await _live()
    level = BookLevel(price=Decimal(price), qty=Decimal(qty), price_ticks=997)
    await eng.on_event(delta(11, 10, [level]))
    with localcontext(Context(prec=6)):  # scaling must not round to the ambient precision
        body = _World(eng).src.build(_sub())
    assert body is not None and (body.price_scale, body.qty_scale) == scales
    assert body.structured["bids"][2] == [price, qty] and body.parts[0].records[2] == record


@pytest.mark.parametrize(
    ("price", "qty"), [("0.1", "1E-19"), ("0.1000000000000000000", "1")],
    ids=["qty-scale-19", "price-scale-19"],
)  # fmt: skip
async def test_a_scale_above_18_builds_none(price: str, qty: str) -> None:
    """§14.1 caps both scales at 18; every value here would still fit its kind-1 field."""
    bid = BookLevel(price=Decimal(price), qty=Decimal(qty), price_ticks=1)
    eng = await _live(levels=((bid,), (lvl(2, "0.5"),)))
    assert eng.phase is BookPhase.LIVE and _World(eng).src.build(_sub()) is None


@pytest.mark.parametrize(
    ("price", "qty", "xseq"),
    [  # at scale 8: a size over u64, a price over i64; and an `xseq` over the u64 trailer field
        ("99.7", "999999999999.99999999", 4_242),
        ("99999999999.99999999", "1", 4_242),
        ("99.7", "1", 2**64),
    ],
    ids=["size-over-u64", "price-over-i64", "xseq-over-u64"],
)
async def test_a_value_outside_its_kind_1_field_builds_none(
    price: str, qty: str, xseq: int
) -> None:
    """Fail closed: no snapshot (the subscription stays pending), never an encoder error."""
    eng = await _live(xseq=xseq)
    level = BookLevel(price=Decimal(price), qty=Decimal(qty), price_ticks=997)
    await eng.on_event(delta(11, 10, [level]))
    assert eng.phase is BookPhase.LIVE and _World(eng).src.build(_sub()) is None


async def test_an_update_id_over_u64_builds_none() -> None:
    """The trailer's `xu` is a u64 too, and a venue `u` has no upper bound: fail closed."""
    eng = await _live(u=2**64)
    assert eng.phase is BookPhase.LIVE and _World(eng).src.build(_sub()) is None


async def test_continuity_is_never_claimed_for_a_book() -> None:
    """§7.6, §7.7: the engine keeps no delta history and the book publisher (#604) starts at the
    attach point, so no `snapshot: false` attach is proven, even one naming the book's own `u`."""
    eng = await _live()
    w = _World(eng)
    sub = _sub(from_seq=eng.last_u, from_ts_ms=1_000)
    w.src.generation(sub)  # the book was seen `live` first, as another subscriber's `snap` does
    for from_ts_ms in (None, 0, 1_000, 10**15):  # none, the past, the attach and the future
        assert w.src.continuity(sub, from_ts_ms) is False, from_ts_ms
