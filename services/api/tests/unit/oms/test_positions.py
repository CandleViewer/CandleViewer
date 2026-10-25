"""The position projection and the protection readings (E29-T05 #848, S5b; 24-internal-schemas.md
Sec.8.12, 21-database-schema.md Sec.3.3.7 "Writes"), on `position_rig`: every bound runs on the
fake clock of `VirtualTimeLoop`. The last cases drive the real facade (`order_rig`)."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.oms import positions as projection
from candleviewer.oms.errors import (
    IllegalTransition,
    OrderStepRefused,
    OrderStepUnknown,
    ReconcileAnomaly,
)
from candleviewer.oms.ports import NoPositionProtection, PositionKey
from candleviewer.oms.positions import REAPPLY_BOUND_S, TAKE_BUDGET_S, PositionProjection
from candleviewer.oms.stream_consumer import POSITION_TAKE_TIMEOUT_S, PositionRows
from candleviewer.oms.stream_push import PORT_TIMEOUT_S, PUSH_TIMEOUT_S
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.positions import NewPositionSnapshot, PositionState
from tests.unit.audit.audit_waits import virtual
from tests.unit.oms import order_rig
from tests.unit.oms.order_rig import build_rig, fill_of, order_of
from tests.unit.oms.position_rig import ACCOUNT, NOW_US, OTHER, Rig, position, routed, stamp

O1, O2 = UUID(int=1), UUID(int=2)
LOST = {"updated_time": (NOW_US + 123_456) // 1_000, "stop_loss": None, "size": "0.4"}
ETH = {"symbol": "ETHUSDT"}


def key(**over: Any) -> PositionKey:
    p = position(**over)
    return PositionKey(p.account_id, p.symbol, p.position_idx)


@virtual
async def test_take_applied_push_upserts_the_mapped_state_then_one_ws_push_snapshot() -> None:
    rig = Rig()
    await rig.take(position(side="sell", trailing_stop_distance=Decimal("15"), take_profit=None))
    assert rig.states == [
        PositionState(
            exchange_account_id=ACCOUNT, symbol="BTCUSDT", size=Decimal("0.4"), position_idx=0,
            side="Sell", avg_price=Decimal("61000.5"), leverage=Decimal("10"),
            mark_price=Decimal("61010"), liq_price=Decimal("50000"),
            unrealised_pnl=Decimal("4.2"), cum_realised_pnl=Decimal("-1.25"),
            trailing_stop=Decimal("15"), exchange_updated_ts=stamp(NOW_US + 123_456),
        )
    ]  # fmt: skip
    assert rig.snaps == [
        NewPositionSnapshot(
            exchange_account_id=ACCOUNT, symbol="BTCUSDT", size=Decimal("0.4"), reason="ws_push",
            avg_price=Decimal("61000.5"), mark_price=Decimal("61010"),
            unrealised_pnl=Decimal("4.2"), cum_realised_pnl=Decimal("-1.25"),
            liq_price=Decimal("50000"),
        )
    ]  # fmt: skip
    assert rig.calls == ["upsert", "protecting", "take_reading", "append"]
    assert rig.counts == ["applied", "to_protection"]


@virtual
async def test_take_stale_push_still_gives_its_reading_and_appends_no_snapshot() -> None:
    rig = Rig(upserts=["stale"])
    await rig.take()
    assert rig.counts == ["stale", "to_protection"] and len(rig.handed) == 1 and rig.snaps == []


@virtual
async def test_take_future_dated_push_logs_counts_pages_once_and_gives_nothing() -> None:
    rig = Rig(upserts=["dated", "dated"])
    with capture_logs() as logs:
        await rig.take()
        await rig.take(position(updated_at=NOW_US + 999))
    assert rig.calls == ["upsert", "upsert"] and rig.handed == [] and rig.snaps == []
    assert rig.counts == ["future_dated", "future_dated"] and len(rig.pages) == 1
    dated = [e for e in logs if e["event"] == "position_future_dated"]
    assert dated[0] == {
        "event": "position_future_dated", "log_level": "error",
        "account_id": str(ACCOUNT), "symbol": "BTCUSDT", "position_idx": 0,
    }  # fmt: skip


@virtual
async def test_take_reapplies_a_held_row_first_and_only_then_gives_its_reading() -> None:
    rig = Rig(upserts=["dated"])
    await rig.take()
    await rig.take(position(**ETH))
    assert [s.symbol for s in rig.states] == ["BTCUSDT", "BTCUSDT", "ETHUSDT"]
    assert [k.symbol for k, _ in rig.handed] == ["BTCUSDT", "ETHUSDT"]
    assert rig.counts.count("reapplied") == 1 and len(rig.snaps) == 2
    await rig.take(position(**ETH))
    assert len(rig.states) == 4  # applied: no longer held


@virtual
async def test_take_newer_row_of_a_held_key_supersedes_the_held_one() -> None:
    rig = Rig(upserts=["dated"])
    await rig.take()
    await rig.take(position(updated_at=NOW_US + 999))
    assert [s.exchange_updated_ts for s in rig.states] == [
        stamp(NOW_US + 123_456),
        stamp(NOW_US + 999),
    ]
    assert len(rig.handed) == 1 and "reapplied" not in rig.counts


@virtual
async def test_reapply_applies_every_held_row_of_the_account_and_no_other() -> None:
    rig = Rig(upserts=["dated"] * 4)
    await rig.take()
    await rig.take(position(**ETH))  # BTCUSDT's re-apply is refused again: still held
    await rig.take(position(account_id=OTHER), account=OTHER)
    await rig.reapply()
    assert [(k.account_id, k.symbol) for k, _ in rig.handed] == [
        (ACCOUNT, "BTCUSDT"), (ACCOUNT, "ETHUSDT")
    ]  # fmt: skip
    assert rig.counts.count("reapplied") == 2


@virtual
async def test_take_hold_is_capped_and_evicts_the_oldest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(projection, "MAX_REFUSED", 2)
    rig = Rig(upserts=["dated"] * 6)  # each take re-applies the held rows: refused again
    for symbol in ("AUSDT", "BUSDT", "CUSDT"):
        await rig.take(position(symbol=symbol))
    assert rig.counts.count("refused_evicted") == 1 and rig.upserts == []
    await rig.reapply()
    assert [k.symbol for k, _ in rig.handed] == ["BUSDT", "CUSDT"]


@virtual
async def test_take_reapply_shares_one_deadline_across_its_held_rows() -> None:
    rig = Rig(upserts=["dated"] * 10)  # each take re-applies the held rows: refused again
    for symbol in ("AUSDT", "BUSDT", "CUSDT", "DUSDT"):
        await rig.take(position(symbol=symbol))
    rig.hang.add("upsert")
    spent = await rig.take(position(**ETH))
    assert spent == pytest.approx(REAPPLY_BOUND_S + PORT_TIMEOUT_S)
    assert [s.symbol for s in rig.states[10:]] == ["AUSDT", "ETHUSDT"]  # the rest stay held


@virtual
async def test_take_reapplied_row_whose_reading_was_not_handed_on_stays_held() -> None:
    rig = Rig(upserts=["dated"], raises={"take_reading": RuntimeError("x")})
    await rig.take()
    await rig.take(position(**ETH))
    del rig.raises["take_reading"]
    await rig.take(position(**ETH))
    assert [s.symbol for s in rig.states] == ["BTCUSDT", "BTCUSDT", "ETHUSDT", "ETHUSDT"]
    assert [k.symbol for k, _ in rig.handed][-2:] == ["BTCUSDT", "ETHUSDT"]  # store step kept


@virtual
async def test_take_protecting_orders_take_the_reading_and_nothing_goes_to_readings() -> None:
    rig = Rig(ids=(O1, O2))
    await rig.take()
    assert rig.pushed == [(O1, "SL_LOST", LOST), (O2, "SL_LOST", LOST)] and rig.handed == []


@virtual
async def test_take_with_no_protecting_order_hands_the_reading_to_protection_readings() -> None:
    rig = Rig()
    p = position()
    await rig.take(p)
    assert rig.handed == [(key(), routed(p).reading)] and rig.pushed == []


@virtual
async def test_take_every_protecting_push_answering_false_falls_back() -> None:
    rig = Rig(ids=(O1, O2), took=[False, False])
    await rig.take()
    assert len(rig.pushed) == 2 and len(rig.handed) == 1 and "to_protection" in rig.counts


@pytest.mark.parametrize(("unknowns", "handed"), [(1, 0), (2, 1)])
@virtual
async def test_take_unknown_push_is_delivered_once_more_and_never_a_third_time(
    unknowns: int, handed: int
) -> None:
    rig = Rig(ids=(O1,), push_errors=[OrderStepUnknown("SL_LOST", "x")] * unknowns)
    await rig.take()
    assert len(rig.pushed) == 2 and len(rig.handed) == handed
    assert rig.counts.count("push_unknown") == unknowns - 1


@pytest.mark.parametrize(
    "error",
    [
        OrderStepRefused("SL_LOST", "x", deterministic=True),
        IllegalTransition("partially_filled", "SL_LOST"),
        ReconcileAnomaly("filled", "SL_LOST"),
        RuntimeError("x"),
    ],
)
@virtual
async def test_take_failed_push_is_counted_and_the_reading_falls_back(error: Exception) -> None:
    rig = Rig(ids=(O1,), push_errors=[error])
    await rig.take()
    assert rig.counts.count("push_failed") == 1 and len(rig.handed) == 1 and len(rig.pushed) == 1


@virtual
async def test_take_hung_push_is_cut_at_the_deadline_and_the_fallback_keeps_its_own_bound() -> None:
    rig = Rig(ids=(O1, O2), hang={"push"}, cost={"take_reading": 1.0})
    spent = await rig.take()
    assert spent == pytest.approx(PUSH_TIMEOUT_S + 1.0)
    assert len(rig.pushed) == 2 and rig.counts.count("push_failed") == 2  # one deadline for both
    assert len(rig.handed) == 1 and "reading_failed" not in rig.counts


@virtual
async def test_take_lost_stop_pages_once_per_episode_and_sl_observed_ends_it() -> None:
    rig = Rig()
    await rig.take(readings=NoPositionProtection())
    await rig.take(position(updated_at=NOW_US + 999))
    assert len(rig.pages) == 1 and rig.counts.count("reading_unavailable") == 2
    await rig.take(position(stop_loss=Decimal("60000")))
    await rig.take(position(**ETH))  # another key's episode is its own
    await rig.take()
    assert len(rig.pages) == 3


@virtual
async def test_take_failed_fallback_on_a_lost_stop_pages_once_per_episode() -> None:
    rig = Rig(raises={"take_reading": RuntimeError("x")})
    await rig.take()
    await rig.take()
    await rig.take(position(qty=Decimal("0"), side=None))  # flat: SL_OBSERVED, never a page
    assert rig.counts.count("reading_failed") == 3 and len(rig.pages) == 1


@virtual
async def test_take_flat_row_reads_sl_observed_and_pages_nothing() -> None:
    rig = Rig()
    await rig.take(position(qty=Decimal("0"), side=None), readings=NoPositionProtection())
    assert rig.states[0].side == "None" and rig.pages == []
    assert "reading_unavailable" not in rig.counts


@virtual
async def test_take_foreign_account_row_writes_and_sends_nothing() -> None:
    rig = Rig(ids=(O1,))
    await rig.take(account=OTHER)
    assert rig.calls == [] and rig.counts == ["foreign_row"] and rig.pushed == []


@virtual
async def test_take_invalid_state_still_gives_its_reading() -> None:
    rig = Rig()
    await rig.take(position(leverage=Decimal("10.123")))  # numeric(10,2) refuses it
    assert rig.states == [] and rig.snaps == []
    assert len(rig.handed) == 1 and rig.counts[0] == "invalid"


@virtual
async def test_take_failed_upsert_still_gives_its_reading_and_no_snapshot() -> None:
    rig = Rig(raises={"upsert": RuntimeError("x")})
    await rig.take()
    assert rig.counts[0] == "store_failed" and len(rig.handed) == 1 and rig.snaps == []


@virtual
async def test_take_cancel_during_a_hung_push_propagates_with_one_delivery() -> None:
    rig = Rig(ids=(O1,), hang={"push"})
    task = asyncio.create_task(rig.take())
    await rig.stalled.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(rig.pushed) == 1 and rig.handed == []


@virtual
async def test_take_cancel_during_a_reapply_keeps_the_held_row() -> None:
    rig = Rig(upserts=["dated"])
    await rig.take()
    rig.hang.add("upsert")
    task = asyncio.create_task(rig.take(position(**ETH)))
    await rig.stalled.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    rig.hang.clear()
    await rig.reapply()
    assert [k.symbol for k, _ in rig.handed] == ["BTCUSDT"]


@virtual
async def test_take_logs_carry_ids_and_kinds_never_a_figure() -> None:
    rig = Rig(ids=(O1,), upserts=["dated"], push_errors=[RuntimeError("61000.5")])
    rig.raises["append"] = RuntimeError("4.2")
    with capture_logs() as logs:
        await rig.take(readings=NoPositionProtection())
        await rig.take(position(**ETH))
    allowed = {
        "event", "log_level", "account_id", "symbol", "position_idx", "kind", "order_id", "reading"
    }  # fmt: skip
    assert logs and all(set(e) <= allowed for e in logs)
    assert not any(s in str(logs) for s in ("61000.5", "0.4", "4.2", "1.25", "50000", "61010"))


@virtual
async def test_take_dated_applied_then_dated_again_pages_once_per_dated_run() -> None:
    rig = Rig(upserts=["dated", "applied", "dated"])
    for _ in range(3):
        await rig.take()
    assert len(rig.pages) == 2


@virtual
async def test_take_lost_stop_episodes_are_capped_and_the_oldest_pages_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(projection, "MAX_EPISODES", 1)
    rig = Rig()
    lost = NoPositionProtection()
    await rig.take(readings=lost)
    await rig.take(position(**ETH))
    await rig.take(position())  # the BTCUSDT episode was evicted by ETHUSDT's
    assert len(rig.pages) == 3


@virtual
async def test_take_reapplies_at_most_the_per_take_cap_of_held_rows() -> None:
    rig = Rig(upserts=["dated"] * 20)
    for symbol in ("AUSDT", "BUSDT", "CUSDT", "DUSDT", "EUSDT"):
        await rig.take(position(symbol=symbol))
    rig.upserts.clear()
    rig.counts.clear()
    await rig.take(position(symbol="FUSDT"))
    assert rig.counts.count("reapplied") == 4


@virtual
async def test_take_snapshot_carries_the_rows_position_idx() -> None:
    rig = Rig()
    await rig.take(position(position_idx=1))
    assert [s.position_idx for s in rig.snaps] == [1]


@virtual
async def test_take_row_of_another_account_under_this_accounts_key_writes_nothing() -> None:
    rig = Rig(ids=(O1,))
    await rig.projection().take(ACCOUNT, position(account_id=OTHER), routed(position()))
    assert rig.calls == [] and rig.counts == ["foreign_row"] and rig.pushed == []


@virtual
async def test_take_reapplied_row_after_a_spent_deadline_stays_held_and_pages_no_loss() -> None:
    """SEC-S5B-01: a spent re-apply deadline cuts every read at zero; the row is not handed on."""
    rig = Rig(upserts=["dated"])
    await rig.take(readings=NoPositionProtection())
    rig.ids, rig.hang, rig.yields = (O1,), {"upsert"}, {"push"}
    await rig.take(position(stop_loss=Decimal("60000"), **ETH))  # A's store step spends the 4 s
    assert len(rig.pages) == 1 and "reading_unavailable" not in rig.counts  # the clock page only
    rig.hang.clear()
    await rig.reapply()  # the store timed out, so the upsert is retried with the reading
    assert rig.pushed[-1] == (O1, "SL_LOST", LOST) and len(rig.pages) == 1


@virtual
async def test_take_reapplied_row_whose_push_the_shared_deadline_cuts_stays_held() -> None:
    """D-1: a few ms left after the store: the cut push leaves the reading owed to the live order,
    so no fallback, no lost-stop page, and the row is held for the next take."""
    rig = Rig(upserts=["dated"])
    await rig.take(readings=NoPositionProtection())
    rig.ids, rig.cost = (O1,), {"upsert": 3.995, "push": 0.01}
    await rig.take(position(stop_loss=Decimal("60000"), **ETH))
    assert len(rig.pages) == 1 and "to_protection" not in rig.counts  # the clock page only
    rig.cost.clear()
    await rig.reapply()
    assert rig.pushed[-1] == (O1, "SL_LOST", LOST) and len(rig.pages) == 1


def _binds_as_the_consumers_seam(projection: PositionProjection) -> PositionRows:
    return projection  # mypy --strict checks the projection against S4c's seam


def test_take_budget_fits_under_the_consumers_bound_on_take() -> None:
    assert TAKE_BUDGET_S < POSITION_TAKE_TIMEOUT_S


@pytest.mark.parametrize("slow", [False, True])
@virtual
async def test_take_fully_hung_or_slow_take_returns_within_its_budget(slow: bool) -> None:
    """Q1: every phase at its bound (a held row re-applied too) fits under the consumer's 50 s."""
    rig = Rig(upserts=["dated"])
    await rig.take()
    rig.ids, rig.hang = (O1,), {"push"}
    for name in ("upsert", "take_reading", "append"):
        if slow:
            rig.cost[name] = PORT_TIMEOUT_S - 0.5
        else:
            rig.hang.add(name)
    assert await rig.take(position(**ETH)) <= TAKE_BUDGET_S


@virtual
async def test_take_raises_nothing_when_every_port_raises() -> None:
    names = ("upsert", "push", "take_reading", "append", "protecting", "count", "page")
    rig = Rig(ids=(O1,), raises=dict.fromkeys(names, RuntimeError("x")))
    await rig.take()
    await rig.take(position(**ETH))
    assert rig.calls.count("upsert") == 2 and len(rig.handed) == 2


# The real facade (`order_rig`, S5a's surface).
@pytest.fixture
async def facade(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[order_rig.Rig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    out = build_rig()
    yield out
    await out.facade.stop()


async def _protected(rig: order_rig.Rig) -> UUID:
    order = order_of()
    await rig.submitted(order)
    await rig.facade.push(order_rig.ACCOUNT, order.id, "EXEC", fill_of(order, "f1", "0.4"))
    await rig.quiet()
    assert rig.facade.state(order.id) == ("partially_filled", "sl_present")
    return order.id


async def _real(rig: order_rig.Rig, p: Any) -> Rig:
    doubles = Rig()
    await doubles.take(p, account=p.account_id, orders=rig.facade)
    await rig.quiet()
    return doubles


async def test_take_lost_stop_reaches_the_live_order_and_the_facade_settles_it(
    facade: order_rig.Rig,
) -> None:
    """T17, C-2.6: the order in `sl_present` takes `SL_LOST` through the projection."""
    order_id = await _protected(facade)
    doubles = await _real(facade, position(account_id=order_rig.ACCOUNT))
    assert facade.facade.state(order_id) == ("partially_filled", "sl_missing")
    assert doubles.handed == [] and doubles.pages == []
    o = facade.facade._orders[order_id]
    assert not o.lock.locked() and not o.busy and len(o.notices) == 0  # `_settle` ran


async def test_take_fired_stops_flat_position_before_its_order_push_pages_nothing(
    facade: order_rig.Rig,
) -> None:
    """T16: 24 Sec.8.12 "tests apply the position push first": the flat reading is recorded."""
    order_id = await _protected(facade)
    flat = position(account_id=order_rig.ACCOUNT, qty=Decimal("0"), side=None)
    doubles = await _real(facade, flat)
    assert doubles.handed == [] and doubles.pages == [] and facade.pager.calls == []
    assert facade.facade.state(order_id) == ("partially_filled", "sl_present")
