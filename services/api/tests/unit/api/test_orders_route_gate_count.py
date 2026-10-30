"""`POST /orders` counts the order-entry gate's refusals (#4973, #964 AC1, 20 Sec.12.1): each
refused request is one `cv_order_entry_refusals_total{reason}` increment and one
`order_entry_refused` line (`reason` and `account_id`, never `detail`), at the route, whether
step 10 refused or the OMS intake's re-check did; an admitted order, and a refusal outside the
gate's closed `REFUSAL_REASONS` set (live trading off, the B18 kill switch), is neither. Driven
through the route on `test_orders_route`'s fakes, never through `order_entry_refusal` itself."""

from __future__ import annotations

from typing import Any

import pytest
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.domain.order_entry import REFUSAL_REASONS, OrderEntryRefusal, RefusalReason
from candleviewer.oms.errors import OrderEntryRefused, TradingDisabled
from tests.unit.api.test_order_acceptance import ACCOUNT
from tests.unit.api.test_orders_route import World, post

_DETAIL = "Order entry is refused for this account."


def _counts() -> dict[str, float]:
    sample = REGISTRY.get_sample_value
    return {
        reason: sample("cv_order_entry_refusals_total", {"reason": reason}) or 0.0
        for reason in REFUSAL_REASONS
    }


def _refused(logs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [log for log in logs if log["event"] == "order_entry_refused"]


def _delta(before: dict[str, float]) -> dict[str, float]:
    after = _counts()
    return {reason: after[reason] - before[reason] for reason in REFUSAL_REASONS}


def _only(reason: str) -> dict[str, float]:
    return {each: 1.0 if each == reason else 0.0 for each in REFUSAL_REASONS}


def _gate(reason: RefusalReason) -> OrderEntryRefused:
    return OrderEntryRefused(OrderEntryRefusal(reason, _DETAIL))


def _assert_one_line(logs: list[dict[str, Any]], reason: str) -> None:
    (line,) = _refused(logs)
    assert (line["reason"], line["account_id"], line["log_level"]) == (reason, str(ACCOUNT), "info")
    assert "detail" not in line and _DETAIL not in repr(logs)


@pytest.mark.parametrize("reason", sorted(REFUSAL_REASONS))
async def test_a_step_10_gate_refusal_is_counted_once_by_its_reason_and_logged_once(
    reason: RefusalReason,
) -> None:
    world = World()
    world.oms.route.switches.refuses = _gate(reason)
    before = _counts()
    with capture_logs() as logs:
        answer = await post(world)
    assert (answer.status_code, answer.json()["reason"]) == (403, reason)
    assert _delta(before) == _only(reason)
    _assert_one_line(logs, reason)
    assert world.oms.submission.submitted == []  # no pipeline: no second check to count


@pytest.mark.parametrize("reason", sorted(REFUSAL_REASONS))
async def test_the_intakes_recheck_refusal_is_counted_once_at_the_route(
    reason: RefusalReason,
) -> None:
    """Step 10 admitted, then the OMS intake's re-check refused (24 Sec.8.4.1): one count."""
    world = World()
    world.oms.submission.error = _gate(reason)
    before = _counts()
    with capture_logs() as logs:
        answer = await post(world)
    assert (answer.status_code, answer.json()["reason"]) == (403, reason)
    assert len(world.oms.submission.submitted) == 1 and world.oms.route.switches.asked == 1
    assert _delta(before) == _only(reason)
    _assert_one_line(logs, reason)


async def test_a_refusal_at_step_10_is_not_counted_again_by_the_intake() -> None:
    """Both checks would refuse: step 10 answers, the pipeline never runs, one count."""
    world = World()
    world.oms.route.switches.refuses = _gate("maintenance")
    world.oms.submission.error = _gate("maintenance")
    before = _counts()
    with capture_logs() as logs:
        await post(world)
    assert _delta(before) == _only("maintenance") and len(_refused(logs)) == 1


async def test_a_gate_refusal_whose_record_cannot_land_is_still_counted_once() -> None:
    """The 503 `audit_unavailable` answer refuses the order too (C-2.9): the gate refused it."""
    world = World()
    world.audit.fail = True
    world.oms.route.switches.refuses = _gate("account_unhealthy")
    before = _counts()
    with capture_logs() as logs:
        answer = await post(world)
    assert answer.status_code == 503
    assert _delta(before) == _only("account_unhealthy") and len(_refused(logs)) == 1


async def test_an_admitted_order_is_neither_counted_nor_logged() -> None:
    world = World()
    before = _counts()
    with capture_logs() as logs:
        answer = await post(world)
    assert answer.status_code == 202
    assert _delta(before) == _only("") and _refused(logs) == []


@pytest.mark.parametrize("at", ["step_10", "intake"])
async def test_a_refusal_outside_the_gates_reasons_is_not_counted(at: str) -> None:
    """Live trading off and the B18 kill switch are `TradingDisabled` with no `reason`: outside
    the closed set, so outside the gate's series (`oms_submit_rejected_total` counts them)."""
    world = World()
    if at == "step_10":
        world.oms.route.switches.refuses = TradingDisabled()
    else:
        world.oms.submission.error = TradingDisabled()
    before = _counts()
    with capture_logs() as logs:
        answer = await post(world)
    assert (answer.status_code, answer.json()["code"]) == (403, "trading_disabled")
    assert _delta(before) == _only("") and _refused(logs) == []
