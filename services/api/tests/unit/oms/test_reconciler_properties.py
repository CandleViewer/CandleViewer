"""Properties of the reconciliation pass (E29-T06 #914 PR 2a; 24 Sec.8.5's phase table, BQ-12,
BQ-18, C-2.6): one row that fails never fails the pass, step 5 always runs whatever failed before
it, and a row of another account fails the fetch with nothing applied."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from unittest.mock import patch

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from candleviewer.exchange.base.models import Position
from candleviewer.oms import reconciler as rc
from candleviewer.oms.reconciler import FetchError
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow
from tests.unit.oms.reconcile_rig import OTHER, World, fill, position, record, remote, row

type Recorded = RecordedStopRow | None

_HYP = settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
#: The row states a pass meets (persisted), each a different branch of 3a or 3b.
_STATES = st.sampled_from(
    ["accepted", "triggered", "partially_filled", "unknown", "quarantined", "untracked", "held"]
)
#: Where one failure lands: a read of the diff, or an effect of the remediation.
_FAULTS = st.sampled_from(
    [
        "get_by_exchange_order_id", "get_by_link_id", "command:RECON_MISS",
        "command:RECON_FOUND_LIVE", "push:EXEC", "push:TRIGGERED", "discover", "adopted",
        "hand_over_execution", "open", "stored", "unfinished_for", "held", "plan_stops",
    ]
)  # fmt: skip


def _world(states: list[str], remote_open: list[int], fills: list[int]) -> World:
    w = World()
    for n, state in enumerate(states, start=1):
        w.oms.seed(row(n, state, lifecycle_state=state if state != "accepted" else "submitted"))
    for n in remote_open:
        w.venue.seed_order(remote(n), uid="1001")
    for i, n in enumerate(fills):
        w.venue.seed_execution(fill(f"e{i}", n=n, seq=i))
    w.oms.records = [record()]
    w.venue.seed_position(position(stop_loss=None))  # naked, with a record in force
    w.venue.seed_position(position(symbol="ETHUSDT"))  # protected: step 5 plans nothing for it
    return w


def _planning_fails(w: World) -> Callable[[Position, Sequence[RecordedStopRow]], Recorded]:
    """`_in_force` that raises the injected `plan_stops` fault, once, for the protected position:
    one position's planning fails, and the naked one is planned all the same (BQ-18)."""
    real = rc._in_force

    def in_force(p: Position, records: Sequence[RecordedStopRow]) -> Recorded:
        if p.symbol == "ETHUSDT":
            w.oms._maybe_fail("plan_stops")
        return real(p, records)

    return in_force


@_HYP
@given(
    states=st.lists(_STATES, max_size=5),
    remote_open=st.lists(st.integers(1, 8), max_size=4, unique=True),
    fills=st.lists(st.integers(1, 8), max_size=4),
    fault=_FAULTS,
)
@example(states=[], remote_open=[], fills=[], fault="plan_stops")  # run whatever ci draws
async def test_one_failure_never_fails_the_pass_and_step_5_always_runs(
    states: list[str], remote_open: list[int], fills: list[int], fault: str
) -> None:
    """BQ-18 and C-2.6: whatever one read or one effect raises, the diff and the remediation
    return, the failure is listed with its step, and the naked position's recorded stop is
    attached all the same."""
    w = _world(states, remote_open, fills)
    w.oms.fail[fault] = ConnectionError("down")
    with patch.object(rc, "_in_force", _planning_fails(w)):
        report = await w.run()
    assert w.oms.effects("attach_recorded"), (states, remote_open, fills, fault)
    assert report.sl_repaired == ("BTCUSDT",)
    if fault not in w.oms.fail:  # it fired: listed, never raised
        assert any(e.kind in ("ConnectionError", "freeze_failed") for e in report.errors)


@_HYP
@given(
    states=st.lists(_STATES, max_size=5),
    remote_open=st.lists(st.integers(1, 8), max_size=4, unique=True),
)
async def test_the_plan_lists_each_action_once_and_step_5_last(
    states: list[str], remote_open: list[int]
) -> None:
    """The plan keeps 24 Sec.8.5's order: every step-5 action after every other action."""
    w = _world(states, remote_open, [])
    plan = await w.plan()
    kinds = [type(a).__name__ for a in plan.actions]
    protective = {"AttachStop", "PageNaked", "RestoreStop", "PageTighter"}
    first = next((i for i, k in enumerate(kinds) if k in protective), len(kinds))
    assert all(k in protective for k in kinds[first:])
    assert plan.divergences == len(kinds) >= 1


_FOREIGN = st.sampled_from(["open_orders", "positions", "executions", "order_handover"])


@_HYP
@given(where=_FOREIGN, n=st.integers(1, 4))
async def test_any_row_of_another_account_fails_the_fetch_with_nothing_applied(
    where: str, n: int
) -> None:
    """BQ-12: whichever read a row of another account arrives in, the fetch fails and nothing is
    planned or written."""
    w = _world(["accepted"] * n, [1], [1])
    if where == "open_orders":
        w.venue.seed_order(remote(9, account_id=OTHER), uid="1001")
    elif where == "positions":
        w.venue._positions.append(position(account_id=OTHER, symbol="ETHUSDT"))
    elif where == "executions":
        w.venue._executions.append(fill("x", n=9, account_id=OTHER))
    else:
        from candleviewer.oms.handovers import WaitingOrder

        w.oms.handed_orders = [WaitingOrder(1, remote(9, account_id=OTHER))]
    if where in ("open_orders", "positions", "executions"):
        _expose(w, where)
    with pytest.raises(FetchError) as failed:
        await w.run()
    assert failed.value.kind == "other_account"
    assert w.oms.log == []


def _expose(w: World, where: str) -> None:
    """The fake venue filters by account as the adapter does (ruling R12): here it lets another
    account's row through, as a defect would, so the pass's own check is what refuses it."""
    original = getattr(w.venue, where)

    async def leaky(account: object, *args: object, **kwargs: object) -> list[object]:
        own = list(await original(account, *args, **kwargs))
        everyone = {"open_orders": list(w.venue._open.values()), "positions": w.venue._positions,
                    "executions": w.venue._executions}[where]  # fmt: skip
        return own + [r for r in everyone if r not in own]

    setattr(w.venue, where, leaky)


def test_the_strategies_cover_a_naked_position_and_a_record() -> None:
    w = _world([], [], [])
    assert (w.oms.records[0].trigger_price, w.venue._positions[0].stop_loss) == (
        Decimal(62000),
        None,
    )
