"""The order path fails closed on the day's loss (E29-S06 #981 slice 4; 24 Sec.8.13, Sec.9.3.6; the
orchestrator's ruling of 2026-11-04 22:19Z, after #881's addendum 3).

`DayRiskFigures` reads the venue itself (24 Sec.8.13: "a read, the cap's included"), not the
closed-PnL sync's records, so the ways its figure is lost are its own: a read that fails, a kept
loss whose day has ended (stale), and a day the resolver cannot resolve. Each leaves the loss
unknown, and an entry is refused before anything is recorded or sent (`figure_unknown`, 503
`sizing_unavailable`), never sized on the last figure. A reduce-only close reads no figure and is
sent, and the exits hold no figures at all, so no cancel, close, amend or stop waits on it (C-2.6).
The figures are the real `DayRiskFigures` on the pipeline's figures slot, over a fake venue."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest

from candleviewer.exchange.base.models import PlaceOrderRequest
from candleviewer.exchange.base.ports import TradingPort
from candleviewer.oms.day_figures import FIGURES_TTL_S, DayRiskFigures
from candleviewer.oms.errors import OmsError, SizingUnavailable, problem_for
from candleviewer.oms.exits import ExitDeps
from candleviewer.oms.ports import SizingRequest
from candleviewer.oms.submit import OrderRequest
from candleviewer.risk.day_boundary import DayBoundary
from candleviewer.statechart.bindings import b01_order as b01
from tests.unit.oms import command_rig as cr
from tests.unit.oms.submit_rig import SubmitRig, build_rig, context, entry, flatten
from tests.unit.oms.test_day_figures import Clock, Venue, _tier, _wallet
from tests.unit.risk.test_day_boundary import Policy

NOW = datetime(2026, 10, 26, 9, 30, tzinfo=UTC)
NEXT_START = datetime(2026, 10, 27, tzinfo=UTC)  # NOW's day ends here at the default offset 0


@dataclass
class Day:
    """The real figures on the rig's slot, and what they read: the venue, the column, the
    monotonic clock and the wall clock (`wall[0]`)."""

    figures: DayRiskFigures
    venue: Venue
    policy: Policy
    clock: Clock
    wall: list[datetime]

    async def prime(self) -> None:
        """A reading kept, as an earlier entry's or preview's would be."""
        reading = await self.figures.read(cr.ref(), [cr.SYMBOL], fallback_sl_offset_pct=None)
        assert reading.account.realised_loss_today == Decimal(0)


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[SubmitRig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    built = build_rig()
    yield built
    await built.machines.stop()


@pytest.fixture
def day(rig: SubmitRig, monkeypatch: pytest.MonkeyPatch) -> Day:
    venue, policy, clock, wall = Venue(), Policy(), Clock(), [NOW]
    venue.wallet_value, venue.held, venue.open, venue.records = (
        _wallet("100000", "100000"),
        [],
        [],
        [],
    )
    tiers = [_tier(1, "2000000", "0.005")]
    figures = DayRiskFigures(
        "demo", port_for=lambda _e: cast(TradingPort, venue), tiers=lambda _s: tiers,
        days=DayBoundary(policy), now=lambda: wall[0], monotonic=clock,
    )  # fmt: skip
    for name in ("read", "peek", "invalidate"):
        monkeypatch.setattr(rig.figures, name, getattr(figures, name))
    return Day(figures, venue, policy, clock, wall)


def _entry() -> OrderRequest:
    """An entry sized by its profile: it reads the day's figures."""
    return entry(sizing=SizingRequest(mode="profile"), stop_loss=None, take_profit=None)


async def _refused_entry(rig: SubmitRig) -> None:
    with pytest.raises(OmsError) as refused:
        await rig.submit(_entry())
    assert isinstance(refused.value, SizingUnavailable)  # figure_unknown
    assert problem_for(refused.value).code == "sizing_unavailable"
    assert rig.calls() == [] and rig.written() == (0, 0, 0, 0)  # nothing recorded or sent


async def _close_passes(rig: SubmitRig, day: Day) -> None:
    """A reduce-only close is sized by its own quantity and reads no figure (C-2.6)."""
    rig.port.demo.seed_position(cr.position(qty="0.050"))
    read = list(day.venue.calls)
    close = flatten(sizing=SizingRequest(mode="fixed_qty", qty=Decimal("0.010")))
    assert (await rig.submit(close, context(client_ref=uuid4()))).status == 202
    assert day.venue.calls == read


async def test_with_the_days_loss_read_an_entry_is_sized_and_sent_with_its_native_stop(
    rig: SubmitRig, day: Day
) -> None:
    assert (await rig.submit(_entry())).status == 202
    [create] = [c.request for c in rig.port.demo.calls if c.method == "place_order"]
    assert isinstance(create, PlaceOrderRequest) and create.price is not None
    assert create.stop_loss is not None and create.stop_loss < create.price  # a buy's (C-2.6)
    assert day.venue.calls.count("closed_pnl") == 1  # the cap's own read


async def test_a_failed_loss_read_refuses_an_entry_never_on_the_last_figure(
    rig: SubmitRig, day: Day
) -> None:
    """Faulted: the read fails once the kept figure is past `FIGURES_TTL_S`."""
    await day.prime()
    day.clock.t += FIGURES_TTL_S
    day.venue.fail = {"closed_pnl"}
    await _refused_entry(rig)
    await _close_passes(rig, day)


async def test_a_kept_loss_past_its_days_next_start_refuses_an_entry_never_served(
    rig: SubmitRig, day: Day
) -> None:
    """Stale: kept at the day's last instant, the loss is not served at `next_start`, inside
    `FIGURES_TTL_S`, and its re-read fails."""
    day.wall[0] = NEXT_START - timedelta(microseconds=1)
    await day.prime()
    day.wall[0], day.clock.t = NEXT_START, day.clock.t + 1
    day.venue.fail = {"closed_pnl"}
    await _refused_entry(rig)
    await _close_passes(rig, day)


async def test_a_day_the_resolver_cannot_resolve_refuses_an_entry_never_the_last_day(
    rig: SubmitRig, day: Day
) -> None:
    """Unknown: past the day's `next_start` the column cannot be read, so the loss has no day:
    never the ended day's, never UTC midnight's."""
    await day.prime()
    day.policy.failure = OSError("postgres unreachable")
    day.wall[0], day.clock.t = NEXT_START, day.clock.t + FIGURES_TTL_S
    await _refused_entry(rig)
    assert day.venue.calls.count("closed_pnl") == 1  # the prime's: the loss read nothing
    await _close_passes(rig, day)


def test_the_exits_hold_no_figures_so_no_cancel_amend_or_stop_waits_on_the_days_loss() -> None:
    """C-2.6: cancels, quantity-reducing amends and stop tightening go through `OrderExits`,
    whose dependencies hold no `OrderFigures`, so the day's loss never refuses one."""
    held = [f.name for f in fields(ExitDeps) if "figure" in f.name or "Figures" in str(f.type)]
    assert held == []
