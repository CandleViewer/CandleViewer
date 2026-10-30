"""`POST /positions/{positionId}/close` and `POST /positions/close-all` (E29-T07 #915 PR 2; 22
`closePosition`, `closeAllPositions` as amended by #5013), on the doubles of
`position_writes_world`. Each test names the Gherkin scenario or the ruling it proves. No network
(C-13.5)."""

from __future__ import annotations

import ast
import asyncio
import uuid
import warnings
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import candleviewer
from candleviewer.api.position_close import (
    CLOSE_ALL_PATH,
    CLOSE_PATH,
    CloseAllBody,
    close_all_body,
)
from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.oms.errors import (
    ExchangeRejected,
    OmsNotReady,
    OrderEntryRefused,
    RiskRefused,
    TradingDisabled,
)
from candleviewer.oms.idempotency import InFlight, KeyReuse, Replay
from candleviewer.oms.position_writes import CLOSE_ACTION, FLATTEN_ACTION
from candleviewer.oms.submit import SubmitContext, SubmitOutcome
from candleviewer.storage.repositories.idempotency_anchors import AnchorRow
from tests.unit.api import test_order_acceptance as acc
from tests.unit.api.oms_reads_world import MISSING
from tests.unit.api.position_writes_world import (
    ACCOUNT,
    FLAT,
    HEDGED,
    LIVE,
    ON_A,
    ON_B,
    ON_LIVE,
    World,
    first_close,
    on,
    post,
)
from tests.unit.oms.submit_rig import ACTOR

FULL: dict[str, Any] = {"order_type": "market", "pct": "100"}
HALF: dict[str, Any] = {"order_type": "market", "pct": "50"}
T0 = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def anchor(outcome: SubmitOutcome, status: int | None = 202, **over: Any) -> AnchorRow:
    values: dict[str, Any] = {
        "id": outcome.anchor_id, "created_by": acc.USER, "operation": "closePosition",
        "trade_group_id": outcome.trade_group_id, "order_id": outcome.order_id,
        "outcome_status": status, "outcome_code": None, "outcome_ret_code": None,
        "created_at": T0, "decided_at": T0, "body_matches": True,
    }  # fmt: skip
    return AnchorRow(**(values | over))


async def close(world: World, position: str = ON_A, body: Any = None, **kw: Any) -> Any:
    return await post(world, on(CLOSE_PATH, position), body=FULL if body is None else body, **kw)


def closes(world: World) -> list[tuple[str, str]]:
    return [(r.outcome, r.reason) for r, _ in world.records.written if r.action == CLOSE_ACTION]


# --- closePosition: the close and its native stop (C-2.6) ------------------------------------


async def test_close_position_full_is_a_reduce_only_flatten_of_the_whole_size_answered_202() -> (
    None
):
    world = World()
    answer = await close(world)
    assert answer.status_code == 202, answer.text
    body = answer.json()
    acc.validate(body)  # 22 OrderAcceptance
    assert body["trade_group"] is None and body["order"]["reduce_only"] is True
    [request] = world.submitted()
    assert (request.side, request.reduce_only, request.intent) == ("sell", True, "flatten")
    assert (request.sizing.mode, request.sizing.qty) == ("fixed_qty", Decimal("0.200"))
    assert request.stop_loss is None and request.take_profit is None


async def test_close_position_native_sl_full_close_sweeps_once_filled_partial_never() -> None:
    """C-2.6 (22 closePosition): at 100 % the sweep of the closed size's Partial-mode
    conditionals is started (it acts only once the venue reads the position flat); below 100 %
    the position's protection is left as it is, so the remaining position keeps its stop."""
    full, half = World(), World()
    assert (await close(full)).status_code == 202
    assert (await close(half, body=HALF)).status_code == 202
    assert [position for position, _ in full.positions.sweeps] == [uuid.UUID(ON_A)]
    assert half.positions.sweeps == []
    [request] = half.submitted()
    assert request.sizing.qty == Decimal("0.100") and request.reduce_only is True


async def test_close_position_by_qty_closes_that_quantity_and_a_full_qty_sweeps() -> None:
    world = World()
    answer = await close(world, body={"order_type": "market", "qty": "0.200"})
    assert answer.status_code == 202
    assert world.submitted()[0].sizing.qty == Decimal("0.200") and world.positions.sweeps


async def test_close_position_a_short_is_closed_by_a_buy_on_its_own_index() -> None:
    world = World()
    assert (await close(world, HEDGED)).status_code == 202
    [request] = world.submitted()
    assert (request.side, request.position_idx) == ("buy", 2)


async def test_close_position_a_limit_close_carries_its_price_and_time_in_force() -> None:
    world = World()
    body = {"order_type": "limit", "price": "63400.00", "pct": "50", "time_in_force": "PostOnly"}
    assert (await close(world, body=body)).status_code == 202
    [request] = world.submitted()
    assert (request.price, request.time_in_force) == (Decimal("63400.00"), "PostOnly")


async def test_close_position_audit_the_close_is_correlated_after_its_order_before_the_answer() -> (
    None
):
    """C-2.9: the order's own submit record is the pipeline's, written ahead of its send; the
    `position.closed` record names the order and is written before the answer returns."""
    world = World()
    answer = await close(world)
    [record] = world.positions.records
    assert (record.action, record.reason) == (CLOSE_ACTION, "requested")
    assert record.detail["order_id"] == answer.json()["order"]["id"]
    assert record.detail["full"] == "true" and record.object_id == uuid.UUID(ON_A)


# --- closePosition: the arm token, the flag and the switches ---------------------------------


async def test_close_position_arm_is_never_required_even_on_live() -> None:
    """22 `ArmToken`, C-2.6: a close is never refused for want of the arm; it is never asked."""
    world = World(environment="live")
    answer = await close(world, ON_LIVE)
    assert answer.status_code == 202, answer.text
    assert world.route.arm_records.shown == []


async def test_close_position_the_oms_flag_off_does_not_refuse_a_close() -> None:
    world = World(oms_enabled=False)
    assert (await close(world)).status_code == 202


_PAUSED = OrderEntryRefusal("maintenance", "Order entry is paused for maintenance.")


@pytest.mark.parametrize(
    "switched", [TradingDisabled(), OrderEntryRefused(_PAUSED)], ids=["freeze_or_live", "gate"]
)
async def test_close_position_c26_freeze_live_off_or_a_paused_gate_never_refuse_a_close(
    switched: TradingDisabled,
) -> None:
    """24 Sec.8.10, 22 `Forbidden` (Fable B1): FREEZE, live trading not enabled and the paused
    order-entry gate never refuse a close: it is sent, marked `protective` for the pipeline."""
    world = World(environment="live")
    world.route.switches.refusal_of = switched
    answer = await close(world, ON_LIVE)
    assert answer.status_code == 202, answer.text
    [(request, context)] = world.pipeline.submitted
    assert request.reduce_only and context.protective is True
    assert closes(world) == []


async def test_close_position_a_fenced_switch_is_503_not_ready_unrecorded() -> None:
    world = World()
    world.route.switches.refusal_of = OmsNotReady()
    answer = await close(world)
    assert (answer.status_code, answer.json()["code"]) == (503, "oms_not_ready")
    assert closes(world) == [] and world.submitted() == []


# --- closePosition: the body ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "rule"),
    [
        ({"order_type": "market"}, "pct_xor_qty"),
        ({"order_type": "market", "pct": "50", "qty": "0.1"}, "pct_xor_qty"),
        ({"order_type": "market", "pct": "0"}, "range"),
        ({"order_type": "market", "pct": "100.5"}, "range"),
        ({"order_type": "market", "qty": "0"}, "range"),
        ({"order_type": "limit", "pct": "50"}, "required"),
        ({"order_type": "market", "pct": 50}, "string_type"),
        ({"order_type": "market", "pct": "50", "extra": 1}, "extra_forbidden"),
        ([], "json_object"),
    ],
)
async def test_close_position_a_body_breaking_a_rule_is_422_unrecorded(
    body: Any, rule: str
) -> None:
    world = World()
    answer = await close(world, body=body)
    assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed")
    assert rule in [e["rule"] for e in answer.json()["errors"]]
    assert world.submitted() == [] and world.records.written == []


async def test_close_position_a_body_past_its_cap_is_422() -> None:
    world = World()
    answer = await close(world, body={"order_type": "market", "pct": "1" * 3_000})
    assert answer.json()["errors"][0]["rule"] == "body_too_large"


@pytest.mark.parametrize(
    ("position", "body", "rule"),
    [(FLAT, FULL, "position_flat"), (ON_A, {"order_type": "market", "qty": "0.3"},
                                     "exceeds_position")],
)  # fmt: skip
async def test_close_position_against_the_position_is_422_recorded_nothing_sent(
    position: str, body: Any, rule: str
) -> None:
    """A close never opens the other side: more than the size, or a flat position, is refused."""
    world = World()
    answer = await close(world, position, body=body)
    assert answer.status_code == 422 and answer.json()["errors"][0]["rule"] == rule
    assert closes(world) == [("denied", "validation_failed")] and world.submitted() == []


# --- closePosition: RBAC and scope (Gherkin "Scope is enforced server-side") --------------------


async def test_close_position_scope_a_viewer_is_forbidden_and_audited() -> None:
    world = World()
    answer = await close(world, who="viewer")
    assert (answer.status_code, answer.json()["code"]) == (403, "forbidden")
    assert world.audit.actions() == ["rbac.denied"] and world.submitted() == []


async def test_close_position_scope_a_foreign_position_is_404_as_a_missing_one_audited() -> None:
    """IDOR (SR-E29-13): B's position and an id nothing holds read alike; the foreign one is
    audited; nothing is sent."""
    world = World()
    foreign = await close(world, ON_B, who="manager")
    missing = await close(world, str(MISSING), who="manager")
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert world.audit.actions() == ["rbac.denied"] and world.submitted() == []


async def test_close_position_scope_a_view_only_grant_is_account_scope_denied() -> None:
    world = World()
    answer = await close(world, who="reader")
    assert (answer.status_code, answer.json()["code"]) == (403, "account_scope_denied")
    assert world.audit.actions() == ["rbac.denied"] and world.submitted() == []


async def test_close_position_scope_a_manager_closes_a_granted_position() -> None:
    world = World()
    assert (await close(world, who="manager")).status_code == 202


@pytest.mark.parametrize(
    ("change", "status", "code"),
    [
        (lambda w: setattr(w, "composed", False), 501, "not_implemented"),
        (lambda w: setattr(w, "readiness", "starting"), 503, "oms_not_ready"),
        (lambda w: setattr(w, "reads_composed", False), 503, "store_unavailable"),
        (lambda w: setattr(w, "refuse_run", True), 503, "oms_not_ready"),
        (lambda w: w.exhaust(), 429, "rate_limited"),
    ],
    ids=["no_oms", "not_ready", "no_reads", "run_refused", "rate"],
)
async def test_close_position_an_edge_before_the_pipeline_sends_nothing(
    change: Any, status: int, code: str
) -> None:
    world = World()
    change(world)
    answer = await close(world)
    assert (answer.status_code, answer.json()["code"]) == (status, code)
    assert world.submitted() == []


async def test_close_position_a_bad_id_and_a_missing_key_are_400() -> None:
    world = World()
    assert (await close(world, "x")).status_code == 400
    async with world.client() as client:
        answer = await client.post(on(CLOSE_PATH, ON_A), json=FULL,
                                   headers={"authorization": "Bearer owner"})  # fmt: skip
    assert (answer.status_code, answer.json()["code"]) == (400, "validation_failed")
    assert world.submitted() == []


# --- closePosition: idempotency (C-2.10, 22 Idempotency "Exception (#915)") ---------------------


async def test_close_position_replay_a_stored_202_is_replayed_and_never_sends_again() -> None:
    world, key = World(), uuid.uuid4()
    first = await close(world, key=key)
    again = await close(world, key=key)
    assert again.status_code == 202 and again.json() == first.json()
    assert again.headers["idempotency-replayed"] == "true" and len(world.submitted()) == 1


async def test_close_position_replay_another_body_under_the_key_is_409_key_reuse() -> None:
    world, key = World(), uuid.uuid4()
    await close(world, key=key)
    answer = await close(world, body=HALF, key=key)
    assert (answer.status_code, answer.json()["code"]) == (409, "idempotency_key_reuse")


async def test_close_position_replay_a_repeat_in_flight_is_409_with_retry_after() -> None:
    world, key, hold = World(), uuid.uuid4(), asyncio.Event()
    original, entered = world.pipeline.submit, asyncio.Event()

    async def held(request: Any, context: Any) -> SubmitOutcome:
        entered.set()
        await hold.wait()
        return await original(request, context)

    world.pipeline.submit = held  # type: ignore[method-assign]  # the first request still runs
    async with world.client() as client:
        path, sent = on(CLOSE_PATH, ON_A), {"authorization": "Bearer owner",
                                            "idempotency-key": str(key)}  # fmt: skip
        first = asyncio.create_task(client.post(path, json=FULL, headers=sent))
        await asyncio.wait_for(entered.wait(), timeout=5)  # never an unbounded wait
        repeat = await client.post(path, json=FULL, headers=sent)
        hold.set()
        assert (await first).status_code == 202
    assert (repeat.status_code, repeat.json()["code"]) == (409, "idempotency_in_flight")
    assert repeat.headers["retry-after"] == "1" and len(world.submitted()) == 1


async def test_close_position_replay_the_anchor_answers_its_rows_as_read_now_unsent() -> None:
    """21 Sec.3.3.10: past the 24 h record, the anchor's repeat reaches its order, nothing sent."""
    world, key, first = World(), uuid.uuid4(), first_close()
    assert first.written is not None
    row = acc.stored(first.written.order, lifecycle_state="filled", state="filled")
    world.route.orders.rows[row.id] = row
    world.anchors.answers[("closePosition", key)] = Replay(anchor(first))
    world.pipeline.replays[first.anchor_id] = acc.replay_of(first)
    answer = await close(world, key=key)
    assert answer.status_code == 202 and answer.headers["idempotency-replayed"] == "true"
    acc.validate(answer.json())
    assert answer.json()["order"]["state"] == "filled" and world.submitted() == []


async def test_close_position_replay_a_send_time_429_is_replayed_from_the_anchor() -> None:
    world, key, first = World(), uuid.uuid4(), first_close()
    refused = SubmitOutcome(429, first.anchor_id, first.order_id, code="exchange_rate_limited",
                            replayed=True)  # fmt: skip
    world.anchors.answers[("closePosition", key)] = Replay(anchor(first, 429))
    world.pipeline.replays[first.anchor_id] = refused
    answer = await close(world, key=key)
    assert (answer.status_code, answer.json()["code"]) == (429, "exchange_rate_limited")
    assert answer.headers["idempotency-replayed"] == "true" and "retry-after" not in answer.headers
    assert world.submitted() == []


@pytest.mark.parametrize(
    ("found", "code"),
    [(InFlight(1), "idempotency_in_flight"), (KeyReuse(), "idempotency_key_reuse")],
)
async def test_close_position_replay_an_undecided_or_reused_anchor_is_409_recorded(
    found: Any, code: str
) -> None:
    world, key = World(), uuid.uuid4()
    world.anchors.answers[("closePosition", key)] = found
    answer = await close(world, key=key)
    assert (answer.status_code, answer.json()["code"]) == (409, code)
    assert closes(world) == [("denied", code)] and world.submitted() == []


# --- closePosition: the pipeline's answers ----------------------------------------------------


async def test_close_position_a_rejected_close_is_502_with_its_return_code_only() -> None:
    world = World()
    world.pipeline.close = SubmitOutcome(502, uuid.uuid4(), uuid.uuid4(), code="exchange_error",
                                         ret_code=110017)  # fmt: skip
    answer = await close(world)
    assert (answer.status_code, answer.json()["code"]) == (502, "exchange_error")
    assert world.positions.sweeps == [] and len(world.cache) == 0


async def test_close_position_a_pipeline_refusal_is_its_problem_nothing_kept() -> None:
    world = World()
    world.pipeline.close = RiskRefused()
    answer = await close(world)
    assert (answer.status_code, answer.json()["code"]) == (403, "risk_limit_breached")
    assert len(world.cache) == 0 and world.positions.records == []


async def test_close_position_an_unrecorded_refusal_is_audit_unavailable_key_unbound() -> None:
    world, key = World(), uuid.uuid4()
    world.anchors.answers[("closePosition", key)] = KeyReuse()
    world.records.fail = True
    answer = await close(world, key=key)
    assert (answer.status_code, answer.json()["code"]) == (503, "audit_unavailable")
    assert len(world.cache) == 0 and world.submitted() == []


async def test_close_position_a_forged_protective_field_is_422_and_never_reaches_the_pipeline(
) -> None:  # fmt: skip
    """The carve-out's marker is route code's alone: a body naming it is refused whole."""
    world = World()
    answer = await close(world, body=FULL | {"protective": True})
    assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed")
    assert "extra_forbidden" in [e["rule"] for e in answer.json()["errors"]]
    assert world.submitted() == []


def test_close_position_only_the_close_routes_set_the_protective_marker() -> None:
    """The marker is unforgeable by request data: no module but the close routes' passes
    `protective=` to a `SubmitContext` (or a `replace` of one), and there only as `True`, a
    constant; it defaults off."""
    root = Path(candleviewer.__file__).resolve().parent
    found: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*.py")):
        with warnings.catch_warnings():  # a module's own escape warnings are not this test's
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "protective" and _names_context(node.func):
                        value = kw.value
                        shown = repr(value.value) if isinstance(value, ast.Constant) else "dynamic"
                        found.append((path.relative_to(root).as_posix(), shown))
    assert found == [("api/position_close.py", "True")] * 2
    assert SubmitContext(ACTOR, uuid.uuid4(), "0" * 64).protective is False


def _names_context(func: ast.expr) -> bool:
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    return name in ("SubmitContext", "replace")


# --- closeAllPositions ------------------------------------------------------------------------


async def flatten(world: World, body: Any = None, **kw: Any) -> Any:
    return await post(world, CLOSE_ALL_PATH, body={} if body is None else body, **kw)


async def test_close_all_flattens_each_open_position_of_the_granted_accounts() -> None:
    """22 closeAllPositions: each open position closed whole, reduce-only; flat ones skipped."""
    world = World()
    answer = await flatten(world)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["requested"], body["succeeded"]) == (1, 1)
    [result] = body["results"]
    assert (result["exchange_account_id"], result["affected"]) == (str(ACCOUNT), 2)
    assert all(r.reduce_only and r.intent == "flatten" for r in world.submitted())
    assert {r.symbol for r in world.submitted()} == {"BTCUSDT", "SOLUSDT"}  # the flat one left
    contexts = [c for _, c in world.pipeline.submitted]
    assert {c.operation for c in contexts} == {"closeAllPositions"}
    assert len({c.anchored_ref for c in contexts}) == 2  # one anchor per position
    assert [r.action for r in world.positions.records] == [FLATTEN_ACTION]
    assert len(world.positions.sweeps) == 2  # each close is whole


@pytest.mark.parametrize(
    "switched", [TradingDisabled(), OrderEntryRefused(_PAUSED)], ids=["freeze_or_live", "gate"]
)
async def test_close_all_c26_freeze_live_off_or_a_paused_gate_never_refuse_a_leg(
    switched: TradingDisabled,
) -> None:
    """24 Sec.8.10 (Fable B1): the panic flatten goes while FREEZE is engaged, live is not enabled
    or the gate pauses; every leg is reduce-only and marked `protective` for the pipeline."""
    world = World()
    world.route.switches.refusal_of = switched
    answer = await flatten(world)
    assert answer.status_code == 200 and answer.json()["succeeded"] == 1
    sent = world.pipeline.submitted
    assert len(sent) == 2 and all(r.reduce_only and c.protective for r, c in sent)


async def test_close_all_a_forged_protective_field_is_422_nothing_sent() -> None:
    world = World()
    answer = await flatten(world, {"protective": True})
    assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed")
    assert world.submitted() == []


async def test_close_all_arm_is_never_required_on_live() -> None:
    world = World(environment="live")
    answer = await flatten(world, {"exchange_account_ids": [str(LIVE)]})
    assert answer.status_code == 200 and world.route.arm_records.shown == []
    assert answer.json()["results"][0]["affected"] == 1


async def test_close_all_cancels_open_orders_first_unless_asked_not_to() -> None:
    world, kept = World(), World()
    await flatten(world, {"symbol": "BTCUSDT"})
    await flatten(kept, {"cancel_open_orders": False})
    [run] = world.cancel_all.runs
    assert run.symbol == "BTCUSDT" and run.exclude_reduce_only is True
    assert kept.cancel_all.runs == []
    assert {r.symbol for r in world.submitted()} == {"BTCUSDT"}


async def test_close_all_scope_an_account_outside_the_grants_refuses_the_whole_request() -> None:
    """SR-E29-13: one foreign id refuses all, audited, nothing sent."""
    world = World()
    answer = await flatten(world, {"exchange_account_ids": [str(ACCOUNT), str(MISSING)]},
                           who="manager")  # fmt: skip
    assert (answer.status_code, answer.json()["code"]) == (403, "account_scope_denied")
    assert world.audit.actions() == ["rbac.denied"] and world.submitted() == []


async def test_close_all_scope_a_viewer_is_forbidden() -> None:
    world = World()
    answer = await flatten(world, who="viewer")
    assert (answer.status_code, answer.json()["code"]) == (403, "forbidden")
    assert world.submitted() == []


async def test_close_all_an_account_whose_close_fails_is_reported_not_hidden() -> None:
    world = World()
    world.pipeline.close = ExchangeRejected(ret_code=110017)
    body = (await flatten(world)).json()
    assert body["succeeded"] == 0
    assert {r["error"]["code"] for r in body["results"]} == {"exchange_error"}
    assert [r.outcome for r in world.positions.records] == ["failure"]


async def test_close_all_a_rejected_close_is_an_account_error() -> None:
    world = World()
    world.pipeline.close = SubmitOutcome(429, uuid.uuid4(), uuid.uuid4(),
                                         code="exchange_rate_limited", retry_after_s=1)  # fmt: skip
    body = (await flatten(world)).json()
    assert {r["error"]["retryable"] for r in body["results"]} == {True}


async def test_close_all_replay_the_same_key_is_answered_from_the_24h_record() -> None:
    world, key = World(), uuid.uuid4()
    first = await flatten(world, key=key)
    again = await flatten(world, key=key)
    assert again.json() == first.json() and again.headers["idempotency-replayed"] == "true"
    assert len(world.submitted()) == 2


@pytest.mark.parametrize(
    "body",
    [[], {"exchange_account_ids": "x"}, {"exchange_account_ids": ["nope"]},
     {"exchange_account_ids": [1]}, {"symbol": "btc"}, {"cancel_open_orders": "yes"},
     {"other": 1}],
)  # fmt: skip
async def test_close_all_a_body_breaking_a_rule_is_422(body: Any) -> None:
    world = World()
    answer = await flatten(world, body)
    assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed")
    assert world.submitted() == []


@pytest.mark.parametrize(
    ("change", "status"),
    [(lambda w: setattr(w, "composed", False), 501),
     (lambda w: setattr(w, "readiness", "starting"), 503),
     (lambda w: setattr(w, "reads_composed", False), 503),
     (lambda w: setattr(w, "refuse_run", True), 503), (lambda w: w.exhaust(), 429)],
)  # fmt: skip
async def test_close_all_an_edge_before_any_send_sends_nothing(change: Any, status: int) -> None:
    world = World()
    change(world)
    assert (await flatten(world)).status_code == status and world.submitted() == []


async def test_close_all_without_a_key_is_400() -> None:
    world = World()
    async with world.client() as client:
        answer = await client.post(
            CLOSE_ALL_PATH, json={}, headers={"authorization": "Bearer owner"}
        )
    assert answer.status_code == 400


def test_close_all_body_dedupes_ids_and_defaults_cancel() -> None:
    a = str(ACCOUNT)
    read = close_all_body(f'{{"exchange_account_ids": ["{a}", "{a}"]}}'.encode())
    assert read == CloseAllBody((ACCOUNT,), None, True)
