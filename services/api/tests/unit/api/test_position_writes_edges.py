"""The position write routes' edges (E29-T07 #915 PR 2): the shared admission's failures, the
replay reads that fail closed, the in-flight guards when full, and the races a held key or a
failed read meets after a send, on `position_writes_world`'s doubles. Each failure answers a
problem and never sends an order it should not (C-2.10, C-2.9). No network (C-13.5)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from candleviewer.accounts.trade_groups import TradeGroupWithLegs
from candleviewer.api.position_close import CLOSE_ALL_PATH, CLOSE_PATH
from candleviewer.api.position_reverse import REVERSE_PATH
from candleviewer.oms.errors import OmsNotReady, StoreUnavailable, TradingDisabled
from candleviewer.oms.idempotency import Replay
from candleviewer.oms.position_writes import reversal_refs
from candleviewer.oms.submit import SubmitOutcome
from candleviewer.storage.repositories.idempotency_anchors import AnchorRow
from tests.unit.api import test_order_acceptance as acc
from tests.unit.api.position_writes_world import (
    ON_A,
    ON_B,
    World,
    first_close,
    first_open,
    on,
    post,
)

FULL: dict[str, Any] = {"order_type": "market", "pct": "100"}
T0 = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
_PATHS = [(on(CLOSE_PATH, ON_A), FULL), (on(REVERSE_PATH, ON_A), None), (CLOSE_ALL_PATH, {})]


def _another(group: TradeGroupWithLegs) -> TradeGroupWithLegs:
    """A group other than the one the outcome names, with its own leg."""
    other = acc._group(group_id=uuid.uuid4(), status="open", created_by=acc.USER)
    [leg] = group.legs
    mine = acc._leg(leg_id=leg.leg_id, group_id=other.group_id, account_id=leg.account_id,
                    status="open")  # fmt: skip
    return TradeGroupWithLegs(group=other, legs=(mine,))


def anchor(outcome: SubmitOutcome, operation: Any, status: int | None = 202) -> AnchorRow:
    return AnchorRow(
        outcome.anchor_id,
        acc.USER,
        operation,
        outcome.trade_group_id,
        outcome.order_id,
        status,
        None,
        None,
        T0,
        T0,
        True,
    )


@pytest.mark.parametrize(("path", "body"), _PATHS, ids=["close", "reverse", "close_all"])
@pytest.mark.parametrize(
    ("principals", "who", "status", "code"),
    [("none", "owner", 501, "not_implemented"), ("fail", "owner", 503, "store_unavailable"),
     ("ok", "nobody", 401, "unauthenticated")],
)  # fmt: skip
async def test_position_writes_a_principal_that_is_not_had_sends_nothing(
    path: str, body: Any, principals: str, who: str, status: int, code: str
) -> None:
    world = World(principals=principals)
    answer = await post(world, path, who, body)
    assert (answer.status_code, answer.json()["code"]) == (status, code)
    assert world.submitted() == []


@pytest.mark.parametrize(("path", "body"), _PATHS, ids=["close", "reverse", "close_all"])
async def test_position_writes_a_forbidden_caller_is_403_even_when_unaudited(
    path: str, body: Any
) -> None:
    world = World()
    world.audit.fail = True
    answer = await post(world, path, "viewer", body)
    assert (answer.status_code, answer.json()["code"]) == (403, "forbidden")
    assert world.submitted() == []


@pytest.mark.parametrize(
    ("who", "position", "status", "code"),
    [("manager", ON_B, 404, "not_found"), ("reader", ON_A, 403, "account_scope_denied")],
)
async def test_position_writes_a_scope_refusal_stands_when_its_record_cannot_be_written(
    who: str, position: str, status: int, code: str
) -> None:
    world = World()
    world.audit.fail = True
    answer = await post(world, on(CLOSE_PATH, position), who, FULL)
    assert (answer.status_code, answer.json()["code"]) == (status, code)
    assert world.submitted() == []


async def test_position_writes_a_position_store_that_fails_is_503_nothing_sent() -> None:
    world = World()
    world.store.fail = True
    answer = await post(world, on(CLOSE_PATH, ON_A), "owner", FULL)
    assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")
    assert world.submitted() == []


@pytest.mark.parametrize(
    ("path", "body"), [(on(CLOSE_PATH, ON_A), FULL), (on(REVERSE_PATH, ON_A), None)],
    ids=["close", "reverse"],
)  # fmt: skip
async def test_position_writes_a_full_in_flight_guard_is_429(
    path: str, body: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import candleviewer.api.position_close as close_module
    import candleviewer.api.position_reverse as reverse_module

    monkeypatch.setattr(close_module, "MAX_IN_FLIGHT", 0)
    monkeypatch.setattr(reverse_module, "MAX_IN_FLIGHT", 0)
    world = World()
    answer = await post(world, path, "owner", body)
    assert (answer.status_code, answer.json()["code"]) == (429, "rate_limited")
    assert answer.headers["retry-after"] == "1" and world.submitted() == []


# --- closePosition: replays that fail closed ------------------------------------------------------


def _replay_close(world: World, key: uuid.UUID, outcome: SubmitOutcome) -> None:
    world.anchors.answers[("closePosition", key)] = Replay(anchor(outcome, "closePosition"))
    world.pipeline.replays[outcome.anchor_id] = acc.replay_of(outcome)


@pytest.mark.parametrize("error", [RuntimeError("down"), OmsNotReady()], ids=["store", "stopping"])
async def test_close_position_a_replay_whose_rows_cannot_be_read_sends_nothing(
    error: BaseException,
) -> None:
    world, key = World(), uuid.uuid4()
    _replay_close(world, key, first_close())
    world.route.orders.error = error
    answer = await post(world, on(CLOSE_PATH, ON_A), "owner", FULL, key=key)
    assert answer.status_code == 503 and world.submitted() == []


async def test_close_position_a_replay_of_a_row_gone_is_503() -> None:
    world, key = World(), uuid.uuid4()
    _replay_close(world, key, first_close())
    answer = await post(world, on(CLOSE_PATH, ON_A), "owner", FULL, key=key)
    assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")


async def test_close_position_a_replay_reading_another_group_fails_closed() -> None:
    """SEC-S3F2-03: rows other than the outcome's are never answered."""
    world, key, opened = World(), uuid.uuid4(), first_open()
    row, group = acc.read_entry(opened)
    world.route.orders.rows[row.id] = row
    world.route.groups.found = _another(group)
    world.anchors.answers[("closePosition", key)] = Replay(anchor(opened, "closePosition"))
    world.pipeline.replays[opened.anchor_id] = acc.replay_of(opened)
    answer = await post(world, on(CLOSE_PATH, ON_A), "owner", FULL, key=key)
    assert (answer.status_code, answer.json()["code"]) == (500, "internal_error")


async def test_close_position_a_held_key_met_at_the_persist_answers_the_earlier_rows() -> None:
    world, close = World(), first_close()
    assert close.written is not None
    row = acc.stored(close.written.order)
    world.route.orders.rows[row.id] = row
    world.pipeline.close = acc.replay_of(close, "submitted")
    answer = await post(world, on(CLOSE_PATH, ON_A), "owner", FULL)
    assert answer.status_code == 202 and answer.headers["idempotency-replayed"] == "true"
    assert world.positions.sweeps == [] and world.positions.records == []


async def test_close_position_a_held_key_whose_rows_are_gone_is_503() -> None:
    world = World()
    world.pipeline.close = acc.replay_of(first_close(), "submitted")
    answer = await post(world, on(CLOSE_PATH, ON_A), "owner", FULL)
    assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")


# --- closeAllPositions --------------------------------------------------------------------------


async def test_close_all_a_failed_cancel_never_holds_back_the_closes() -> None:
    world = World()
    world.cancel_all.error = StoreUnavailable()
    answer = await post(world, CLOSE_ALL_PATH, "owner", {})
    assert answer.status_code == 200 and len(world.submitted()) == 2


async def test_close_all_a_scope_refusal_stands_when_its_record_cannot_be_written() -> None:
    world = World()
    world.audit.fail = True
    answer = await post(world, CLOSE_ALL_PATH, "manager",
                        {"exchange_account_ids": [str(uuid.uuid4())]})  # fmt: skip
    assert (answer.status_code, answer.json()["code"]) == (403, "account_scope_denied")


async def test_close_all_a_body_past_its_cap_and_a_repeat_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import candleviewer.api.position_close as close_module

    world = World()
    big = {"exchange_account_ids": [str(uuid.uuid4())] * 600}
    answer = await post(world, CLOSE_ALL_PATH, "owner", big)
    assert answer.json()["errors"][0]["rule"] == "body_too_large"
    monkeypatch.setattr(close_module, "MAX_IN_FLIGHT", 0)
    full = await post(world, CLOSE_ALL_PATH, "owner", {})
    assert (full.status_code, full.json()["code"]) == (429, "rate_limited")


async def test_close_all_an_unreadable_scope_is_its_problem_and_a_stop_not_ready() -> None:
    world = World()
    world.store.fail = True
    assert (await post(world, CLOSE_ALL_PATH, "owner", {})).status_code == 503
    stopping = World()

    async def stopped(scope: Any, request: Any) -> Any:
        raise OmsNotReady

    stopping.cancel_all.scope = stopped  # type: ignore[method-assign]  # its stop began
    answer = await post(stopping, CLOSE_ALL_PATH, "owner", {})
    assert (answer.status_code, answer.json()["code"]) == (503, "oms_not_ready")


# --- reversePosition: races and failures after a send --------------------------------------------


async def test_reverse_position_a_fenced_switch_is_not_ready_and_an_unrecorded_refusal_503() -> (
    None
):
    fenced = World()
    fenced.route.switches.refusal_of = OmsNotReady()
    assert (await post(fenced, on(REVERSE_PATH, ON_A))).json()["code"] == "oms_not_ready"
    unrecorded = World()
    unrecorded.route.switches.refusal_of = TradingDisabled()
    unrecorded.records.fail = True
    answer = await post(unrecorded, on(REVERSE_PATH, ON_A))
    assert (answer.status_code, answer.json()["code"]) == (503, "audit_unavailable")
    assert unrecorded.submitted() == []


async def test_reverse_position_a_held_close_key_still_in_flight_is_409_no_entry() -> None:
    """The close's persist met the key held by a request still running: 409, no entry sent."""
    world, close = World(), first_close()
    world.pipeline.close = acc.replay_of(close, "filled")
    answer = await post(world, on(REVERSE_PATH, ON_A))
    assert (answer.status_code, answer.json()["code"]) == (409, "idempotency_in_flight")
    assert len(world.submitted()) == 1


async def test_reverse_position_a_held_close_key_with_its_anchor_answers_the_decision() -> None:
    world, key, close = World(), uuid.uuid4(), first_close()
    assert close.written is not None
    world.route.orders.rows[close.order_id or uuid.uuid4()] = acc.stored(
        close.written.order, lifecycle_state="filled"
    )
    world.pipeline.close = acc.replay_of(close, "filled")
    world.pipeline.replays[close.anchor_id] = acc.replay_of(close, "filled")
    original = world.anchors.lookup
    calls = 0

    async def second_finds(*args: Any, **kw: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:  # the route's own lookup found none; the race's finds the close's
            return Replay(anchor(close, "reversePosition"))
        return await original(*args, **kw)

    world.anchors.lookup = second_finds  # type: ignore[method-assign]  # the race's read
    answer = await post(world, on(REVERSE_PATH, ON_A), key=key)
    assert answer.status_code == 202, answer.text
    assert answer.json()["outcome"] == "entry_refused" and len(world.submitted()) == 1


async def test_reverse_position_a_held_entry_key_answers_its_rows_as_reversed() -> None:
    world, opened = World(), first_open()
    row, group = acc.read_entry(opened)
    world.route.orders.rows[row.id] = row
    world.route.groups.found = group
    world.pipeline.entry = acc.replay_of(opened, "submitted")
    body = (await post(world, on(REVERSE_PATH, ON_A))).json()
    assert body["outcome"] == "reversed" and body["open"]["trade_group"]["id"] == str(
        opened.trade_group_id
    )


async def test_reverse_position_a_read_failing_after_the_close_answers_its_problem() -> None:
    """The close is sent and B1 owns it; the wait's read failing answers 503, no entry sent."""
    world = World()
    world.positions.fill_error = StoreUnavailable()
    answer = await post(world, on(REVERSE_PATH, ON_A))
    assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")
    assert [r.reduce_only for r in world.submitted()] == [True]


async def test_reverse_position_a_held_entry_reading_another_group_fails_closed() -> None:
    world, opened = World(), first_open()
    row, group = acc.read_entry(opened)
    world.route.orders.rows[row.id] = row
    world.route.groups.found = _another(group)
    world.pipeline.entry = acc.replay_of(opened, "submitted")
    answer = await post(world, on(REVERSE_PATH, ON_A))
    assert (answer.status_code, answer.json()["code"]) == (500, "internal_error")


async def test_reverse_position_a_decided_repeat_reading_another_group_fails_closed() -> None:
    world, key, close, opened = World(), uuid.uuid4(), first_close(), first_open()
    assert close.written is not None
    world.route.orders.rows[close.order_id or uuid.uuid4()] = acc.stored(close.written.order)
    row, group = acc.read_entry(opened)
    world.route.orders.rows[row.id] = row
    world.route.groups.found = _another(group)
    close_ref, open_ref = reversal_refs(key)
    world.anchors.answers[("reversePosition", close_ref)] = Replay(anchor(close, "reversePosition"))
    world.anchors.answers[("reversePosition", open_ref)] = Replay(anchor(opened, "reversePosition"))
    world.pipeline.replays[close.anchor_id] = acc.replay_of(close)
    world.pipeline.replays[opened.anchor_id] = replace(acc.replay_of(opened), lifecycle="filled")
    answer = await post(world, on(REVERSE_PATH, ON_A), key=key)
    assert (answer.status_code, answer.json()["code"]) == (500, "internal_error")
    assert world.submitted() == []


async def test_reverse_position_a_run_refused_by_a_stopping_runtime_is_not_ready() -> None:
    world = World(refuse_run=True)
    answer = await post(world, on(REVERSE_PATH, ON_A))
    assert (answer.status_code, answer.json()["code"]) == (503, "oms_not_ready")
    assert world.submitted() == []
