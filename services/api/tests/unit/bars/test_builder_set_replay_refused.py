"""#2762: a print the per-print cap refuses during catch-up never leaves the series unregistrable.

The series' last blob is older than a print its builder refuses (SR-E12-15) and the tape still holds
that print. The restore replays it, so the set refuses the blob and cold-starts the series: counted
and logged once as `replay_refused`. The cold start's floor record replaces the blob, so a later
register (after the grace, or a restart) replays nothing and succeeds. Renko refuses with its real
cap; the volume cap (#2770) is faked by trade id, so the test does not depend on it. Only the
builder's refusal discards the blob: a tape that fails mid-replay raises, and the blob stays."""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.bars.builder_set import BuilderFactory, default_factory, renko_factory
from candleviewer.bars.errors import BarsError
from candleviewer.bars.leases import GRACE_US
from candleviewer.bars.metrics import bar_builder_cold_starts_total
from candleviewer.bars.models import BarBuilder, BarSpec
from candleviewer.bars.state_store import StateStore, StoredState, Watermark
from candleviewer.bus.bus import Bus
from candleviewer.exchange.base.models import TradeEvent

from ._set_harness import V5, Clock, FakeTape, blob_discards, make_set
from ._trades import SYM, trade, us

T0 = us("10:00:00")
GEN = 7  # the stale blob's generation
REASON = "replay_refused"  # its `bars_blob_discarded_total` reason and its log line's
R2 = BarSpec(kind="renko", range_ticks=2)  # a 0.02 brick at a 0.01 tick
OUTLIER = trade(T0 + 4, "10100", seq=4)  # 500 000 renko bricks in one print: over the cap of 1 000
TAPE = [
    trade(T0 + 1, "100", seq=1),
    trade(T0 + 2, "100.02", seq=2),
    trade(T0 + 3, "100.04", seq=3),  # the stale blob's watermark
    OUTLIER,
    trade(T0 + 5, "100.06", seq=5),
]


def _volume_capped(spec: BarSpec, symbol: str) -> BarBuilder:
    """A volume builder whose per-print cap (#2770) refuses the outlier."""
    builder = default_factory(spec, symbol)
    real = builder.on_trade

    def on_trade(t: Any) -> Any:
        if t.trade_id == OUTLIER.trade_id:
            raise BarsError("One trade would complete too many volume bars.")
        return real(t)

    builder.on_trade = on_trade  # type: ignore[method-assign]  # the cap, faked
    return builder


CASES: dict[str, tuple[BarSpec, BuilderFactory]] = {
    "renko": (R2, renko_factory(lambda _s: Decimal("0.01"))),
    "volume": (V5, _volume_capped),
}


async def _stale_blob(root: Path, spec: BarSpec, factory: BuilderFactory) -> None:
    """What a stop after the first three prints leaves: a blob older than the outlier."""
    builder = factory(spec, SYM)
    for t in TAPE[:3]:
        builder.on_trade(t)
    mark = Watermark(TAPE[2].ts_event, frozenset({TAPE[2].trade_id}))
    await StateStore(root).save(StoredState(builder.snapshot(), mark, GEN))


def _cold_starts() -> float:
    return float(bar_builder_cold_starts_total._value.get())


@pytest.mark.parametrize("case", list(CASES))
async def test_a_restore_that_replays_a_refused_print_cold_starts_the_series(
    tmp_path: Path, case: str
) -> None:
    spec, factory = CASES[case]
    await _stale_blob(tmp_path, spec, factory)
    clock, bus = Clock(T0 + 10), Bus()
    s = make_set(tmp_path, bus=bus, tape=FakeTape(TAPE), clock=clock)  # a restart
    s._factory = factory
    refused, cold = blob_discards(REASON), _cold_starts()
    with capture_logs() as logs:
        await s.register(spec, SYM, "a")
    assert s.active(SYM) == (spec.spec_hash,)
    assert s._leases._series[(SYM, spec.spec_hash)].holders == {"a": None}
    assert (blob_discards(REASON), _cold_starts()) == (refused + 1, cold + 1)  # once
    discarded = [e for e in logs if e["event"] == "bars_state_blob_discarded"]
    assert [(e["spec_hash"], e["reason"]) for e in discarded] == [(spec.spec_hash, REASON)]
    stored, _ = await StateStore(tmp_path).load(SYM, spec.spec_hash)
    assert stored is not None and stored.watermark is None  # the floor record replaced the blob
    assert stored.generation > GEN  # a new epoch
    s.release(spec.spec_hash, SYM, "a")
    clock.t += GRACE_US
    await s.tick()  # the grace ends: the series is torn down
    assert s.active(SYM) == ()
    await s.register(spec, SYM, "b")  # replays nothing: the refused print is not met again
    assert s.active(SYM) == (spec.spec_hash,) and blob_discards(REASON) == refused + 1
    await s.stop()


class _BrokenTape(FakeTape):
    """A tape whose read fails where the outlier is: an outage, not a refused print."""

    async def since(self, symbol: str, ts_us: int) -> AsyncIterator[TradeEvent]:
        async for t in super().since(symbol, ts_us):
            if t is OUTLIER:
                raise BarsError("The tape read failed.")
            yield t


async def test_a_tape_that_fails_mid_replay_raises_and_keeps_the_blob(tmp_path: Path) -> None:
    spec, factory = CASES["renko"]
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
