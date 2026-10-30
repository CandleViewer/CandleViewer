"""`POST /positions/{positionId}/reverse` (E29-T07 #915 PR 2; 22 `reversePosition` as amended by
#5013), on the doubles of `position_writes_world`. Each test names the ruling or the 22 sentence
it proves; the replay matrix is the brief's. No network (C-13.5)."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from candleviewer.api.position_reverse import REVERSE_PATH, decided_outcome
from candleviewer.oms.errors import (
    FieldError,
    OrderInvalid,
    RiskRefused,
    StoreUnavailable,
    TradingDisabled,
)
from candleviewer.oms.idempotency import InFlight, Replay
from candleviewer.oms.position_writes import REVERSE_ACTION, reversal_refs
from candleviewer.oms.submit import RECONCILING, SubmitOutcome
from candleviewer.storage.repositories.idempotency_anchors import AnchorRow
from tests.unit.api import test_order_acceptance as acc
from tests.unit.api.position_writes_world import (
    FLAT,
    HEDGED,
    ON_A,
    ON_LIVE,
    World,
    first_close,
    first_open,
    on,
    post,
)

T0 = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
_REVERSE = Draft202012Validator(acc.schema("ReverseAcceptance"), format_checker=acc._FORMATS)


async def reverse(world: World, position: str = ON_A, body: Any = None, **kw: Any) -> Any:
    return await post(world, on(REVERSE_PATH, position), body=body, **kw)


def reversals(world: World) -> list[tuple[str, str]]:
    return [(r.outcome, r.reason) for r, _ in world.records.written if r.action == REVERSE_ACTION]


def anchor(outcome: SubmitOutcome, status: int | None = 202, **over: Any) -> AnchorRow:
    values: dict[str, Any] = {
        "id": outcome.anchor_id, "created_by": acc.USER, "operation": "reversePosition",
        "trade_group_id": outcome.trade_group_id, "order_id": outcome.order_id,
        "outcome_status": status, "outcome_code": None, "outcome_ret_code": None,
        "created_at": T0, "decided_at": T0, "body_matches": True,
    }  # fmt: skip
    return AnchorRow(**(values | over))


# --- the reversal: close, the confirmed fill, then the entry -----------------------------------


async def test_reverse_position_closes_waits_for_the_fill_then_enters_answered_reversed() -> None:
    world, key = World(), uuid.uuid4()
    answer = await reverse(world, key=key)
    assert answer.status_code == 202, answer.text
    body = answer.json()
    _REVERSE.validate(body)  # 22 ReverseAcceptance
    assert (body["outcome"], body["reason"]) == ("reversed", None)
    assert body["close"]["order"]["reduce_only"] is True and body["open"]["trade_group"]
    close, entry = world.submitted()
    assert (close.reduce_only, close.side, close.intent) == (True, "sell", "flatten")
    assert (close.order_type, close.sizing.qty) == ("market", Decimal("0.200"))
    assert (entry.reduce_only, entry.side, entry.intent) == (False, "sell", "entry")
    close_ref, open_ref = reversal_refs(key)
    contexts = [c for _, c in world.pipeline.submitted]
    assert [(c.operation, c.anchored_ref, c.client_ref) for c in contexts] == [
        ("reversePosition", close_ref, key),
        ("reversePosition", open_ref, key),
    ]  # the entry's group keeps the raw key (21 Sec.3.3.10)


async def test_reverse_position_mutant_the_entry_is_never_sent_before_the_fill_is_confirmed() -> (
    None
):
    """22: the entry is submitted only after the close is confirmed filled."""
    world, log = World(), list[str]()
    world.pipeline.log = world.positions.log = log
    assert (await reverse(world)).status_code == 202
    assert log == ["close", "fill:filled", "entry"]


async def test_reverse_position_the_wait_is_measured_from_the_request_on_the_injected_clock() -> (
    None
):
    world = World()
    original = world.pipeline.submit

    async def slow(request: Any, context: Any) -> SubmitOutcome:
        world.clock[0] += 1.5  # the close took 1.5 s of the 2 s
        return await original(request, context)

    world.pipeline.submit = slow  # type: ignore[method-assign]  # a close that takes its time
    await reverse(world)
    assert world.positions.waits == [0.5]


async def test_reverse_position_native_sl_the_entry_is_sized_and_stopped_by_the_profile() -> None:
    """C-2.6, C-12.5: the entry names no client size or stop; the profile gives both (the
    pipeline's guard judges its stop: `test_position_writes` proves it on the real pipeline)."""
    world = World()
    await reverse(world, body={"size_mode": "profile", "order_type": "limit", "price": "63000"})
    entry = world.submitted()[1]
    assert (entry.sizing.mode, entry.stop_loss, entry.take_profit) == ("profile", None, None)
    assert (entry.order_type, entry.price) == ("limit", Decimal("63000"))


async def test_reverse_position_hedge_mode_enters_on_the_other_index() -> None:
    world = World()
    await reverse(world, HEDGED)
    close, entry = world.submitted()
    assert (close.position_idx, close.side, entry.position_idx, entry.side) == (2, "buy", 1, "buy")


@pytest.mark.parametrize(
    ("fill", "outcome"),
    [("unfilled", "close_unfilled"), ("partially_filled", "close_partially_filled")],
)
async def test_reverse_position_a_close_not_filled_at_the_deadline_sends_no_entry(
    fill: Any, outcome: str
) -> None:
    world = World()
    world.positions.fill = fill
    body = (await reverse(world)).json()
    _REVERSE.validate(body)
    assert (body["outcome"], body["open"], body["reason"]) == (outcome, None, None)
    assert [r.reduce_only for r in world.submitted()] == [True]
    assert world.positions.records[0].reason == outcome


@pytest.mark.parametrize(
    ("entry", "reason"),
    [(RiskRefused(), "risk_limit_breached"), (TradingDisabled(), "trading_disabled"),
     (SubmitOutcome(502, uuid.uuid4(), uuid.uuid4(), code="exchange_error", ret_code=110007),
      "exchange_error"),
     (SubmitOutcome(429, uuid.uuid4(), uuid.uuid4(), code="exchange_rate_limited",
                    retry_after_s=1), "exchange_rate_limited")],
)  # fmt: skip
async def test_reverse_position_an_entry_refused_by_a_check_or_the_exchange_is_entry_refused(
    entry: Any, reason: str
) -> None:
    world = World()
    world.pipeline.entry = entry
    answer = await reverse(world)
    assert answer.status_code == 202
    body = answer.json()
    _REVERSE.validate(body)
    assert (body["outcome"], body["reason"], body["open"]) == ("entry_refused", reason, None)


async def test_reverse_position_a_close_the_exchange_rejects_is_502_and_no_entry() -> None:
    world = World()
    world.pipeline.close = SubmitOutcome(502, uuid.uuid4(), uuid.uuid4(), code="exchange_error",
                                         ret_code=110017)  # fmt: skip
    answer = await reverse(world)
    assert (answer.status_code, answer.json()["code"]) == (502, "exchange_error")
    assert answer.json()["exchange"] == {"ret_code": 110017}
    assert len(world.submitted()) == 1 and world.positions.waits == []


async def test_reverse_position_a_close_the_pipeline_refuses_is_its_problem() -> None:
    world = World()
    world.pipeline.close = RiskRefused()
    answer = await reverse(world)
    assert (answer.status_code, answer.json()["code"]) == (403, "risk_limit_breached")
    assert len(world.submitted()) == 1


async def test_reverse_position_audit_one_reversed_record_after_both_orders() -> None:
    """C-2.9: each order's submit record is the pipeline's (ahead of its send); one
    `position.reversed` record correlates the pair and the outcome before the answer."""
    world = World()
    body = (await reverse(world)).json()
    [record] = world.positions.records
    assert (record.action, record.reason) == (REVERSE_ACTION, "reversed")
    assert record.detail["close_order_id"] == body["close"]["order"]["id"]
    leg = body["open"]["trade_group"]["legs"][0]
    assert record.detail["open_order_id"] == leg["order_details"][0]["id"]


# --- refused before anything is sent ---------------------------------------------------------


async def test_reverse_position_native_sl_no_stop_from_the_profile_refuses_with_nothing_sent() -> (
    None
):
    """22, C-2.6: a profile that cannot produce a stop refuses the reversal before any order."""
    world = World()
    stop = FieldError("stop_loss", "native_stop_required", "No stop.")
    world.positions.stop_refusal = OrderInvalid("No stop.", errors=(stop,))
    answer = await reverse(world)
    assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed")
    assert answer.json()["errors"][0]["rule"] == "native_stop_required"
    assert world.submitted() == [] and reversals(world) == [("denied", "validation_failed")]


async def test_reverse_position_an_unread_profile_is_503_nothing_sent() -> None:
    world = World()
    world.positions.stop_refusal = StoreUnavailable()
    answer = await reverse(world)
    assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")
    assert world.submitted() == []


async def test_reverse_position_arm_is_required_on_live() -> None:
    """22 `ArmToken`: a reversal opens exposure, so a live account needs the arm."""
    world = World(environment="live")
    refused = await reverse(world, ON_LIVE)
    assert (refused.status_code, refused.json()["code"]) == (403, "session_not_armed")
    assert world.submitted() == [] and reversals(world) == [("denied", "session_not_armed")]
    armed = await reverse(world, ON_LIVE, arm="armed")
    assert armed.status_code == 202 and len(world.submitted()) == 2


@pytest.mark.parametrize(
    ("change", "code"),
    [(lambda w: setattr(w, "oms_enabled", False), "trading_disabled"),
     (lambda w: setattr(w.route.switches, "refusal_of", TradingDisabled()), "trading_disabled")],
    ids=["flag", "switches"],
)  # fmt: skip
async def test_reverse_position_trading_disabled_is_checked_before_the_close(
    change: Any, code: str
) -> None:
    world = World()
    change(world)
    answer = await reverse(world)
    assert (answer.status_code, answer.json()["code"]) == (403, code)
    assert world.submitted() == [] and reversals(world) == [("denied", code)]


async def test_reverse_position_a_flat_position_is_422_nothing_sent() -> None:
    world = World()
    answer = await reverse(world, FLAT)
    assert answer.status_code == 422 and answer.json()["errors"][0]["rule"] == "position_flat"
    assert world.submitted() == []


@pytest.mark.parametrize(
    "body",
    [{"size_mode": "same"}, {"order_type": "limit"}, {"qty": "1"}, [], {"price": 1}],
)
async def test_reverse_position_a_body_breaking_a_rule_is_422_unrecorded(body: Any) -> None:
    world = World()
    answer = await reverse(world, body=body)
    assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed")
    assert world.submitted() == [] and world.records.written == []


async def test_reverse_position_scope_rbac_and_idor_are_the_shared_admissions() -> None:
    world = World()
    viewer = await reverse(world, who="viewer")
    foreign = await reverse(world, "00000000-0000-0000-0000-000000000d02", who="manager")
    reader = await reverse(world, who="reader")
    assert (viewer.status_code, foreign.status_code, reader.status_code) == (403, 404, 403)
    assert reader.json()["code"] == "account_scope_denied" and world.submitted() == []


# --- the replay matrix (22 Idempotency "Exception (#915)", 21 Sec.3.3.10) ---------------------


async def test_reverse_position_replay_a_stored_202_is_replayed_verbatim_nothing_sent() -> None:
    world, key = World(), uuid.uuid4()
    first = await reverse(world, key=key)
    again = await reverse(world, key=key)
    assert again.json() == first.json() and again.headers["idempotency-replayed"] == "true"
    assert len(world.submitted()) == 2


async def test_reverse_position_replay_an_outcome_other_than_reversed_is_stored_too() -> None:
    world, key = World(), uuid.uuid4()
    world.positions.fill = "unfilled"
    first = await reverse(world, key=key)
    again = await reverse(world, key=key)
    assert again.json() == first.json() and len(world.submitted()) == 1


async def test_reverse_position_replay_a_repeat_in_flight_is_409() -> None:
    world, key, hold = World(), uuid.uuid4(), asyncio.Event()
    original, entered = world.pipeline.submit, asyncio.Event()

    async def held(request: Any, context: Any) -> SubmitOutcome:
        entered.set()
        await hold.wait()
        return await original(request, context)

    world.pipeline.submit = held  # type: ignore[method-assign]  # the first request still runs
    async with world.client() as client:
        path = on(REVERSE_PATH, ON_A)
        sent = {"authorization": "Bearer owner", "idempotency-key": str(key)}
        first = asyncio.create_task(client.post(path, headers=sent))
        await asyncio.wait_for(entered.wait(), timeout=5)  # never an unbounded wait
        repeat = await client.post(path, headers=sent)
        hold.set()
        assert (await first).status_code == 202
    assert (repeat.status_code, repeat.json()["code"]) == (409, "idempotency_in_flight")
    assert len(world.submitted()) == 2


def _undecided(world: World, key: uuid.UUID, close_chart: str, **row: Any) -> SubmitOutcome:
    """The close's anchor decided by the repeat (the store's compare-and-set), its row as read."""
    close = first_close()
    assert close.written is not None
    world.route.orders.rows[close.order_id or uuid.uuid4()] = acc.stored(close.written.order, **row)
    world.anchors.answers[("reversePosition", reversal_refs(key)[0])] = Replay(anchor(close))
    world.pipeline.replays[close.anchor_id] = acc.replay_of(close, close_chart)
    return close


async def test_reverse_position_replay_undecided_with_its_open_anchor_answers_reversed() -> None:
    """22: with the entry's anchor present the answer is `reversed`, the entry as it ended."""
    world, key = World(), uuid.uuid4()
    _undecided(world, key, "filled", lifecycle_state="filled", state="filled")
    opened = first_open()
    open_row, group = acc.read_entry(opened, lifecycle_state="rejected", state="rejected")
    world.route.orders.rows[open_row.id] = open_row
    world.route.groups.found = group
    world.anchors.answers[("reversePosition", reversal_refs(key)[1])] = Replay(anchor(opened, 502))
    world.pipeline.replays[opened.anchor_id] = replace(
        acc.replay_of(opened, "rejected"), status=502, code="exchange_error"
    )
    answer = await reverse(world, key=key)
    assert answer.status_code == 202 and answer.headers["idempotency-replayed"] == "true"
    body = answer.json()
    _REVERSE.validate(body)
    assert body["outcome"] == "reversed"  # never entry_refused once the entry's anchor exists
    assert body["open"]["trade_group"]["legs"][0]["order_details"][0]["state"] == "rejected"
    assert world.submitted() == []


@pytest.mark.parametrize(
    ("chart", "row", "outcome", "reason"),
    [("filled", {"lifecycle_state": "filled"}, "entry_refused", "timeout"),
     ("cancelled", {"lifecycle_state": "cancelled", "cum_exec_qty": Decimal("0.1")},
      "close_partially_filled", None),
     ("cancelled", {"lifecycle_state": "cancelled", "cum_exec_qty": Decimal(0)},
      "close_unfilled", None),
     (RECONCILING, {"lifecycle_state": "submitting"}, "close_unfilled", None)],
)  # fmt: skip
async def test_reverse_position_replay_undecided_without_its_open_anchor_follows_the_close(
    chart: str, row: dict[str, Any], outcome: str, reason: str | None
) -> None:
    world, key = World(), uuid.uuid4()
    _undecided(world, key, chart, **row)
    answer = await reverse(world, key=key)
    body = answer.json()
    _REVERSE.validate(body)
    assert (body["outcome"], body["reason"], body["open"]) == (outcome, reason, None)
    assert body["close"]["reconciling"] is (chart == RECONCILING)
    assert world.submitted() == []


async def test_reverse_position_replay_a_send_time_429_on_the_close_is_replayed() -> None:
    world, key, close = World(), uuid.uuid4(), first_close()
    refused = SubmitOutcome(429, close.anchor_id, close.order_id, code="exchange_rate_limited",
                            replayed=True)  # fmt: skip
    world.anchors.answers[("reversePosition", reversal_refs(key)[0])] = Replay(anchor(close, 429))
    world.pipeline.replays[close.anchor_id] = refused
    answer = await reverse(world, key=key)
    assert (answer.status_code, answer.json()["code"]) == (429, "exchange_rate_limited")
    assert answer.headers["idempotency-replayed"] == "true" and world.submitted() == []


async def test_reverse_position_replay_an_entry_anchor_in_flight_is_409() -> None:
    world, key = World(), uuid.uuid4()
    _undecided(world, key, "filled", lifecycle_state="filled")
    world.anchors.answers[("reversePosition", reversal_refs(key)[1])] = InFlight(1)
    answer = await reverse(world, key=key)
    assert (answer.status_code, answer.json()["code"]) == (409, "idempotency_in_flight")
    assert world.submitted() == []


async def test_reverse_position_replay_still_passes_the_arm_check_first() -> None:
    world, key = World(environment="live"), uuid.uuid4()
    world.anchors.answers[("reversePosition", reversal_refs(key)[0])] = InFlight(1)
    answer = await reverse(world, ON_LIVE, key=key)
    assert answer.json()["code"] == "session_not_armed" and world.anchors.calls == []


def test_decided_outcome_reads_the_close() -> None:
    close = first_close()
    assert decided_outcome(close, "filled", Decimal(0)) == ("entry_refused", "timeout")
    assert decided_outcome(replace(close, lifecycle=RECONCILING), "filled", Decimal(1)) == (
        "close_unfilled",
        None,
    )
