"""#2762: a print the builder refuses during catch-up never leaves the series unregistrable.

The series' last blob is older than a print its builder refuses (SR-E12-15) or raises on, and the
tape still holds that print. The restore replays it, so the set refuses the blob and cold-starts
the series with a fresh builder: counted and logged once as `replay_refused`, with the class of the
builder's error. The cold start's floor record replaces the blob, so a later register (after the
grace, or a restart) does not meet the print again. Renko refuses with its real cap; the volume cap
(#2770) is faked by trade id, and so is a builder raising a `ValueError` or a `RuntimeError`, which
the live path would quarantine. Only the builder's error discards the blob: a tape that fails
mid-replay raises, and the blob stays."""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from structlog.testing import capture_logs

from candleviewer.bars.builder_set import (
    BarBuilderSet,
    BuilderFactory,
    default_factory,
    renko_factory,
)
from candleviewer.bars.errors import BarsError
from candleviewer.bars.leases import GRACE_US
from candleviewer.bars.metrics import bar_builder_cold_starts_total
from candleviewer.bars.models import BarBuilder, BarSpec
from candleviewer.bars.rows import MAX_GENERATION
from candleviewer.bars.state_store import StateStore, StoredState, Watermark
from candleviewer.bus.bus import Bus
from candleviewer.exchange.base.models import TradeEvent

from ._set_harness import TOPIC, V5, Clock, FakeTape, RecordingSink, blob_discards, make_set, settle
from ._trades import SYM, trade, us

T0 = us("10:00:00")
GEN = 7  # the stale blob's generation
HIGH = 10**15  # a stale blob's generation above the clock's ms: the floor, not the clock, decides
REASON = "replay_refused"  # its `bars_blob_discarded_total` reason and its log line's
R2 = BarSpec(kind="renko", range_ticks=2)  # a 0.02 brick at a 0.01 tick
OUTLIER = trade(T0 + 4, "10100", seq=4)  # 500 000 renko bricks in one print: over the cap of 1 000
NEXT = trade(T0 + 5, "100.06", seq=5)  # the print after it, which arrives live after the restart
TAPE = [
    trade(T0 + 1, "100", seq=1),
    trade(T0 + 2, "100.02", seq=2),
    trade(T0 + 3, "100.04", seq=3),  # the stale blob's watermark
    OUTLIER,
    NEXT,
]


def _refusing(error: type[Exception]) -> BuilderFactory:
    """Volume builders that raise `error` on the outlier: a `BarsError` is the per-print cap of
    #2770, faked; any other error is a builder failing on the print."""

    def make(spec: BarSpec, symbol: str) -> BarBuilder:
        builder = default_factory(spec, symbol)
        real = builder.on_trade

        def on_trade(t: Any) -> Any:
            if t.trade_id == OUTLIER.trade_id:
                raise error("The builder refuses this print.")
            return real(t)

        builder.on_trade = on_trade  # type: ignore[method-assign]  # the refusal, faked
        return builder

    return make


#: Per case: the spec, its factory, and the class of the error the builder raises on the outlier.
CASES: dict[str, tuple[BarSpec, BuilderFactory, str]] = {
    "renko": (R2, renko_factory(lambda _s: Decimal("0.01")), "BarsError"),
    "volume": (V5, _refusing(BarsError), "BarsError"),
    "ValueError": (V5, _refusing(ValueError), "ValueError"),
    "RuntimeError": (V5, _refusing(RuntimeError), "RuntimeError"),  # not a restore error
}


async def _stale_blob(root: Path, spec: BarSpec, factory: BuilderFactory, gen: int = GEN) -> None:
    """What a stop after the first three prints leaves: a blob older than the outlier."""
    builder = factory(spec, SYM)
    for t in TAPE[:3]:
        builder.on_trade(t)
    mark = Watermark(TAPE[2].ts_event, frozenset({TAPE[2].trade_id}))
    await StateStore(root).save(StoredState(builder.snapshot(), mark, gen))


def _cold_starts() -> float:
    return float(bar_builder_cold_starts_total._value.get())


class _Restart(NamedTuple):
    """A set restarted over one case's stale blob, its series not registered yet."""

    s: BarBuilderSet
    bus: Bus
    sink: RecordingSink
    clock: Clock
    spec: BarSpec
    factory: BuilderFactory
    error: str  # the class of the error the builder raises on the outlier


@pytest.fixture(params=list(CASES))
async def restart(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[_Restart]:
    spec, factory, error = CASES[request.param]
    await _stale_blob(tmp_path, spec, factory)
    clock, bus, sink = Clock(T0 + 10), Bus(), RecordingSink()
    s = make_set(tmp_path, bus=bus, sinks=[sink], tape=FakeTape(TAPE), clock=clock)  # a restart
    s._factory = factory
    yield _Restart(s, bus, sink, clock, spec, factory, error)
    await s.stop()


async def test_a_refused_replay_is_counted_and_logged_once_with_the_builders_error(
    restart: _Restart,
) -> None:
    s, spec = restart.s, restart.spec
    refused, cold = blob_discards(REASON), _cold_starts()
    with capture_logs() as logs:
        await s.register(spec, SYM, "a")
    assert s.active(SYM) == (spec.spec_hash,)
    assert s._leases._series[(SYM, spec.spec_hash)].holders == {"a": None}
    assert (blob_discards(REASON), _cold_starts()) == (refused + 1, cold + 1)  # once
    discarded = [e for e in logs if e["event"] == "bars_state_blob_discarded"]
    assert [(e["spec_hash"], e["reason"], e.get("error_type")) for e in discarded] == [
        (spec.spec_hash, REASON, restart.error)
    ]


async def test_the_cold_start_after_a_refused_replay_writes_a_fresh_builders_floor_record(
    restart: _Restart, tmp_path: Path
) -> None:
    await restart.s.register(restart.spec, SYM, "a")
    stored, _ = await StateStore(tmp_path).load(SYM, restart.spec.spec_hash)
    assert stored is not None and stored.watermark is None  # the floor record replaced the blob
    assert stored.generation > GEN  # a new epoch
    assert stored.state == restart.factory(restart.spec, SYM).snapshot()  # nothing of the blob


async def test_the_next_live_print_after_a_refused_replay_opens_bar_0_with_only_its_volume(
    restart: _Restart,
) -> None:
    await restart.s.register(restart.spec, SYM, "a")
    await restart.bus.publish(TOPIC, NEXT)  # the next print, live
    await settle(restart.bus, restart.s)
    first = [(kind, bar.index, bar.volume, bar.turnover) for _, kind, bar in restart.sink.bars][:1]
    assert first == [("open", 0, NEXT.qty, NEXT.notional)]


async def test_a_register_after_the_grace_of_a_refused_replay_meets_the_print_no_more(
    restart: _Restart,
) -> None:
    s, spec = restart.s, restart.spec
    await s.register(spec, SYM, "a")
    s.release(spec.spec_hash, SYM, "a")
    restart.clock.t += GRACE_US
    await s.tick()  # the grace ends: the series is torn down
    assert s.active(SYM) == ()
    refused = blob_discards(REASON)
    await s.register(spec, SYM, "b")  # replays nothing: the refused print is not met again
    assert s.active(SYM) == (spec.spec_hash,) and blob_discards(REASON) == refused


async def test_the_cold_start_after_a_refused_replay_takes_a_generation_above_the_blobs(
    tmp_path: Path,
) -> None:
    """The aborted restore noted the blob's generation, so the new epoch is above it even where
    the clock is below it (a wall clock that stepped back, #2662)."""
    assert (T0 + 10) // 1000 < HIGH < MAX_GENERATION
    spec, factory, _ = CASES["renko"]
    await _stale_blob(tmp_path, spec, factory, gen=HIGH)
    s = make_set(tmp_path, tape=FakeTape(TAPE), clock=Clock(T0 + 10))
    s._factory = factory
    await s.register(spec, SYM, "a")
    stored, _ = await StateStore(tmp_path).load(SYM, spec.spec_hash)
    assert stored is not None and stored.watermark is None  # the cold start's floor record
    assert stored.generation == HIGH + 1
    await s.stop()


class _BrokenTape(FakeTape):
    """A tape whose read fails where the outlier is: an outage, not a refused print."""

    async def since(self, symbol: str, ts_us: int) -> AsyncIterator[TradeEvent]:
        async for t in super().since(symbol, ts_us):
            if t is OUTLIER:
                raise BarsError("The tape read failed.")
            yield t


async def test_a_tape_that_fails_mid_replay_raises_and_keeps_the_blob(tmp_path: Path) -> None:
    spec, factory, _ = CASES["renko"]
    await _stale_blob(tmp_path, spec, factory)
    s = make_set(tmp_path, tape=_BrokenTape(TAPE), clock=Clock(T0 + 10))
    s._factory = factory
    refused = blob_discards(REASON)
    with pytest.raises(BarsError, match="tape read failed"):
        await s.register(spec, SYM, "a")
    stored, _ = await StateStore(tmp_path).load(SYM, spec.spec_hash)
    assert stored is not None and stored.generation == GEN and stored.watermark is not None  # kept
    assert (blob_discards(REASON), s._leases.keys(), s._lanes) == (refused, (), {})
    await s.stop()
