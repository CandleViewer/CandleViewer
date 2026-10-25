"""`PATCH /orders/{orderId}`, `amendOrder` (E29-T04 #913 slice 4, S4-D2b; 24 Sec.8.4 "The exit
routes", 22 `amendOrder`, the slice-4 rulings Q5 to Q7, Q10 to Q12 and Q14, SEC-S4C2B-01). The
route runs in the exit routes' router (`make_order_exits_router`) over the real exit service: on
S4-C's scripted facade (`test_exits.scripted`) for each step's refusal and, made to take an
`AMEND` (`amending`), for each answer the service gives; and on the real B1 facade, command port
and fake venue (`submit_rig`, the rig's limit buy entry resting `submitted`: 0.010 at 60000, its
stop 58000 and its take-profit 64000) for the body's terms, the scope, the arm token, the flag
and the `ETag`. Each `202` is validated against 22 `Order`, each problem against
`OrderExchangeProblem`."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from structlog.testing import capture_logs

from candleviewer.api.idempotency import StoredResponse, request_fingerprint
from candleviewer.api.order_admission import MAX_ORDER_BODY_BYTES
from candleviewer.api.order_etag import order_etag
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.domain.primitives import Environment
from candleviewer.exchange.base.errors import OmsErrorCode
from candleviewer.oms import commands as oc
from candleviewer.oms import exits as ex
from candleviewer.oms.errors import OMS_NOT_READY_RETRY_AFTER_S, OmsNotReady, StoreUnavailable
from candleviewer.oms.ports import ArmToken, RequestRecord, StopOffset
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.gateway import (
    GatewayDegradedError,
    GatewayError,
    GatewayOverloadedError,
)
from candleviewer.storage.repositories.accounts import OwnerScope
from candleviewer.storage.repositories.orders import OrderRow, ScopedOrder
from tests.unit.api import test_order_exits_route as er
from tests.unit.api.test_orders_route import ArmChecks
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr
from tests.unit.oms import test_exits as tx
from tests.unit.oms.submit_rig import SubmitRig

OWNER, KEY, TRACE, PEER = er.OWNER, er.KEY, er.TRACE, er.PEER
D = Decimal
_DENIED = "orders.amend"
_REUSED = (_DENIED, "idempotency_key_reuse")
_CUT = {"qty": "0.005"}  # a smaller quantity: never gated (C-2.6)
_RAISE = {"qty": "0.011"}  # a larger one on an entry: risk-increasing (24 Sec.8.10)


def routed(world: er.World, env: Environment = "demo", versions: object = None) -> ArmChecks:
    """The route's reads of the runtime: `env`, the arm records (a live account passes with a
    token only) and B1's facade, whose `version()` names a `202`'s `ETag` (kept when not given)."""
    arms = ArmChecks()
    kept = getattr(world.oms.route, "versions", None) if versions is None else versions
    world.oms.route = SimpleNamespace(environment=env, arm_records=arms, versions=kept)
    return arms


def refused(world: er.World, code: str) -> float:
    labels = {"env": "demo", "operation": "amend", "code": code}
    return world.metrics.registry.get_sample_value("oms_exit_refused_total", labels) or 0.0


async def patch(
    world: er.World, order: object, body: object = _CUT, who: str = "owner", key: object = KEY,
    fields: tuple[tuple[str, str], ...] = (), **headers: str,
) -> httpx.Response:  # fmt: skip
    """The amend, from `PEER` as each record names it; `fields`, more header fields as sent."""
    sent = [("authorization", f"Bearer {who}"), ("x-correlation-id", str(TRACE))]
    if key is not None:
        sent.append(("idempotency-key", str(key)))
    sent += [(name.replace("_", "-"), value) for name, value in headers.items()]
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    transport = ASGITransport(app=world.app(), client=(PEER, 4321))
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        return await c.patch(f"/orders/{order}", content=raw, headers=[*sent, *fields])


_FINAL = frozenset({"filled", "cancelled"})


def amending(machines: tx.Scripted, monkeypatch: pytest.MonkeyPatch) -> None:
    """S4-C's scripted facade as an amend meets it: an `AMEND` taken leaves the order
    `amend_pending`, each settle answers the amend's watch, and a final order has no version, as
    B1's facade has none."""

    async def command(account_id: UUID, order_id: UUID, event: Any, *_a: Any, **_k: Any) -> str:
        if machines.refuse is not None:
            raise machines.refuse
        machines.sent.append(event)
        machines.held = "amend_pending"
        return machines.held

    async def settled(account_id: UUID, order_id: UUID, *, leaving: str, timeout_s: float) -> str:
        out = machines.settles.pop(0)
        if isinstance(out, BaseException):
            raise out
        if (watch := machines.watches.held.get((order_id, "amend"))) is not None:
            watch.resolve(machines.answer)
        machines.held = out
        return out

    def version(order_id: UUID) -> int | None:
        return None if machines.held in _FINAL else 7

    monkeypatch.setattr(machines, "command", command)
    monkeypatch.setattr(machines, "settled", settled)
    monkeypatch.setattr(machines, "version", version)


# --- each step's refusal (24 Sec.8.4, the exit routes), on the scripted facade ------------------


def _claimed(*keys: UUID) -> Any:
    def claim(world: er.World) -> None:
        for key in keys:
            claimed = world.oms.service.guard.claim(OWNER, "amend", key)
            assert not isinstance(claimed, ex.ExitOutcome)

    return claim


def _recorded_elsewhere(world: er.World) -> None:
    held = StoredResponse("another request", 202, b"{}", None)
    world.cache.put(str(OWNER), f"amendOrder:{KEY}", held)


def _live(world: er.World) -> None:
    routed(world, "live")


def _starting(world: er.World) -> None:
    world.oms.state = "starting"


_FULL = tuple(UUID(int=n) for n in range(1, ex.MAX_IN_FLIGHT_PER_PRINCIPAL + 1))
_LARGE = b'{"qty": "0.005", "pad": "' + b"x" * MAX_ORDER_BODY_BYTES + b'"}'
_BAD_OFFSET = {"stop_loss": {"unit": "price", "value": "abc"}}
_TEXT_PERIOD = {"stop_loss": {"unit": "atr", "value": "1", "atr_period": "14"}}  # JSON text
#: The step a route refusal's record names (`deny`'s `step`).
_STEP_OF = {
    "5_too_large": "body", "5_empty": "body", "5_not_an_object": "body",
    "5_extra_member": "body", "5_not_a_number": "body", "5_two_rules": "body",
    "5_bad_offset": "body", "5_text_integer": "body", "6_not_armed": "arm", "7_no_key": "key",
    "8_reuse": "replay", "9_in_flight": "guard", "9_full": "guard",
}  # fmt: skip
#: Each step's refusal alone: (name, change, who, order, body, key) -> (status, code, records).
#: Nothing is commanded or run, and the refusal is counted once.
_STEPS: list[tuple[str, Any, str, str, Any, UUID | None, int, str, list[tuple[str, str]]]] = [
    ("1_no_source", lambda w: setattr(w, "principals", None), "owner", "row", _CUT, KEY, 501,
     "not_implemented", []),
    ("1_no_session", None, "nobody", "row", _CUT, KEY, 401, "unauthenticated", []),
    ("1_unread", lambda w: setattr(w.principals, "fail", True), "owner", "row", _CUT, KEY, 503,
     "store_unavailable", []),
    ("1_not_an_id", None, "owner", "not-a-uuid", _CUT, KEY, 400, "validation_failed", []),
    ("2_permission", None, "viewer", "row", _CUT, KEY, 403, "forbidden",
     [("rbac.denied", "missing_permission:orders:write:none")]),
    ("3_no_runtime", lambda w: setattr(w, "composed", False), "owner", "row", _CUT, KEY, 501,
     "not_implemented", []),
    ("3_starting", _starting, "owner", "row", _CUT, KEY, 503, "oms_not_ready", []),
    ("3_stopping", lambda w: setattr(w.oms, "stopped", "exits"), "owner", "row", _CUT, KEY, 503,
     "oms_not_ready", []),
    ("4_lane_stopped", lambda w: setattr(w.oms.service, "scope", er.lane_stopped), "owner", "row",
     _CUT, KEY, 503, "oms_not_ready", []),
    ("4_missing", None, "owner", "missing", _CUT, KEY, 404, "not_found", []),
    ("5_too_large", None, "owner", "row", _LARGE, KEY, 400, "validation_failed",
     [(_DENIED, "validation_failed")]),
    ("5_empty", None, "owner", "row", b"", KEY, 400, "validation_failed",
     [(_DENIED, "validation_failed")]),
    ("5_not_an_object", None, "owner", "row", b"[1]", KEY, 400, "validation_failed",
     [(_DENIED, "validation_failed")]),
    ("5_extra_member", None, "owner", "row", {"qty": "0.005", "side": "sell"}, KEY, 400,
     "validation_failed", [(_DENIED, "validation_failed")]),
    ("5_not_a_number", None, "owner", "row", {"qty": "lots"}, KEY, 400, "validation_failed",
     [(_DENIED, "validation_failed")]),
    ("5_two_rules", None, "owner", "row", {"qty": "lots", "price": "x"}, KEY, 400,
     "validation_failed", [(_DENIED, "validation_failed")]),
    ("5_bad_offset", None, "owner", "row", _BAD_OFFSET, KEY, 400, "validation_failed",
     [(_DENIED, "validation_failed")]),
    ("5_text_integer", None, "owner", "row", _TEXT_PERIOD, KEY, 400, "validation_failed",
     [(_DENIED, "validation_failed")]),
    ("6_not_armed", _live, "owner", "row", _RAISE, KEY, 403, "session_not_armed",
     [(_DENIED, "session_not_armed")]),
    ("7_no_key", None, "owner", "row", _CUT, None, 400, "validation_failed",
     [(_DENIED, "validation_failed")]),
    ("8_reuse", _recorded_elsewhere, "owner", "row", _CUT, KEY, 409, "idempotency_key_reuse",
     [(_DENIED, "idempotency_key_reuse")]),
    ("9_in_flight", _claimed(KEY), "owner", "row", _CUT, KEY, 409, "idempotency_in_flight",
     [(_DENIED, "idempotency_in_flight")]),
    ("9_full", _claimed(*_FULL), "owner", "row", _CUT, KEY, 429, "rate_limited",
     [(_DENIED, "rate_limited")]),
    ("9_stopping", lambda w: setattr(w.oms, "stopped", "run"), "owner", "row", _CUT, KEY, 503,
     "oms_not_ready", []),
]  # fmt: skip
#: 22's members of a step's problem: its `retry_after_seconds`, `Retry-After` alike, where 22
#: gives one (`oms_not_ready`'s, the in-flight guard's), and each `errors[]` entry's field and rule.
_RETRY = {
    "3_starting": OMS_NOT_READY_RETRY_AFTER_S, "3_stopping": OMS_NOT_READY_RETRY_AFTER_S,
    "4_lane_stopped": OMS_NOT_READY_RETRY_AFTER_S,
    "9_in_flight": ex.IN_FLIGHT_RETRY_AFTER_S, "9_full": ex.IN_FLIGHT_RETRY_AFTER_S,
    "9_stopping": OMS_NOT_READY_RETRY_AFTER_S,
}  # fmt: skip
_ERRORS: dict[str, list[tuple[str, str]]] = {
    "1_not_an_id": [("orderId", "uuid")],
    "5_too_large": [("body", "body_too_large")],
    "5_empty": [("body", "object")],
    "5_not_an_object": [("body", "object")],
    "5_extra_member": [("side", "extra_forbidden")],
    "5_not_a_number": [("qty", "string_pattern_mismatch")],
    "5_two_rules": [("price", "string_pattern_mismatch"), ("qty", "string_pattern_mismatch")],
    "5_bad_offset": [("stop_loss.value", "string_pattern_mismatch")],
    "5_text_integer": [("stop_loss.atr_period", "int_type")],
    "7_no_key": [("Idempotency-Key", "uuid")],
}


@pytest.mark.parametrize("case", _STEPS, ids=[case[0] for case in _STEPS])
async def test_each_step_refuses_before_the_next_runs(case: Any) -> None:
    name, change, who, order, body, key, status, code, records = case
    world, machines, row, _ = await er.scripted_world("submitted")
    routed(world)
    if change is not None:
        change(world)
    target = {"row": row.id, "missing": uuid4()}.get(order, order)
    with capture_logs() as logs:
        answer = await patch(world, target, body, who, key)
    problem = answer.json()
    er._PROBLEM.validate(problem)
    assert (answer.status_code, problem["code"], world.actions()) == (status, code, records)
    escaped = [line for line in logs if line["event"] == "oms_exit_refusal_escaped"]
    assert escaped == []  # each a refusal the route answers, none one that escaped the service
    assert world.steps() == ([_STEP_OF[name]] if name in _STEP_OF else [])
    assert (machines.sent, world.oms.tasks, refused(world, code)) == ([], [], 1)
    retry = _RETRY.get(name)
    assert (problem.get("retry_after_seconds"), answer.headers.get("retry-after")) == (
        retry, None if retry is None else str(retry),
    )  # fmt: skip
    listed = [(error["field"], error["rule"]) for error in problem.get("errors", [])]
    assert listed == _ERRORS.get(name, [])
    if name == "9_stopping":  # the runtime refused the run: the claim is released
        assert callable(world.oms.service.guard.claim(OWNER, "amend", KEY))


#: Two steps refusing at once: the earlier answers and is the one counted, the later never runs
#: (24 Sec.8.4, each before the next). (change, who, order, body, key) -> (status, code, records,
#: the later step's code).
_PAIRS: list[tuple[str, Any, str, str, Any, UUID | None, int, str, list[Any], str]] = [
    ("1_before_2", None, "viewer", "not-a-uuid", _CUT, KEY, 400, "validation_failed", [],
     "forbidden"),
    ("2_before_3", _starting, "viewer", "row", _CUT, KEY, 403, "forbidden",
     [("rbac.denied", "missing_permission:orders:write:none")], "oms_not_ready"),
    ("3_before_4", _starting, "owner", "missing", _CUT, KEY, 503, "oms_not_ready", [],
     "not_found"),
    ("4_before_5", None, "owner", "missing", b"[1]", KEY, 404, "not_found", [],
     "validation_failed"),
    ("5_before_6", _live, "owner", "row", {"qty": "lots"}, KEY, 400, "validation_failed",
     [(_DENIED, "validation_failed")], "session_not_armed"),
    ("6_before_7", _live, "owner", "row", _RAISE, None, 403, "session_not_armed",
     [(_DENIED, "session_not_armed")], "validation_failed"),
]  # fmt: skip


@pytest.mark.parametrize("case", _PAIRS, ids=[case[0] for case in _PAIRS])
async def test_of_two_refusing_steps_the_earlier_answers(case: Any) -> None:
    _, change, who, order, body, key, status, code, records, later = case
    world, machines, row, _ = await er.scripted_world("submitted")
    routed(world)
    if change is not None:
        change(world)
    target = {"row": row.id, "missing": uuid4()}.get(order, order)
    answer = await patch(world, target, body, who, key)
    assert (answer.status_code, answer.json()["code"], world.actions()) == (status, code, records)
    assert (refused(world, code), refused(world, later), machines.sent) == (1, 0, [])


async def test_a_stored_202_is_not_replayed_to_a_live_raise_without_its_token() -> None:
    """Step 6 before step 8: the arm token is asked before the 24 h record is read, so a live
    raise without one is `403 session_not_armed`, never the `202` stored under its key."""
    world, machines, row, _ = await er.scripted_world("submitted")
    _live(world)
    digest = request_fingerprint("PATCH", f"/orders/{row.id}", json.dumps(_RAISE).encode())
    world.cache.put(str(OWNER), f"amendOrder:{KEY}", StoredResponse(digest, 202, b"{}", None))
    answer = await patch(world, row.id, _RAISE)
    assert (answer.status_code, answer.json()["code"]) == (403, "session_not_armed")
    assert "idempotency-replayed" not in answer.headers
    assert (world.steps(), machines.sent) == (["arm"], [])


@pytest.mark.parametrize("lands", [True, False], ids=["recorded", "unrecorded"])
async def test_a_viewer_is_403_its_record_naming_the_order_and_still_403_unrecorded(
    lands: bool,
) -> None:
    """Step 2: `orders:write`, audited `rbac.denied` naming the order asked for, the request, its
    session and its source address, a 403 even when that record cannot be written, and counted
    either way (24 Sec.8.4)."""
    world, _, row, _ = await er.scripted_world("submitted")
    routed(world)
    world.audit.fail = not lands
    answer = await patch(world, row.id, who="viewer")
    assert (answer.status_code, answer.json()["code"]) == (403, "forbidden")
    named = [
        (e["object_kind"], e["object_id"], e["request_id"], e["session_id"], e["actor_ip"])
        for e in world.audit.records
    ]
    assert named == ([("order", str(row.id), TRACE, sr.SESSION, PEER)] if lands else [])
    assert refused(world, "forbidden") == 1


# --- each answer of the exit service, on the scripted facade taking an `AMEND` ------------------


def _no(code: str, **more: Any) -> dict[str, Any]:
    return {"ok": False, "error_code": code, **more}


_OK: dict[str, Any] = {"ok": True}
_GONE = {"unknown": b01.ALREADY_TERMINAL, "exchange_ret_code": 110001}
_RATE, _VENUE = OmsErrorCode.RATE_BUDGET_EXCEEDED, OmsErrorCode.PRICE_OUT_OF_BOUNDS
_SETTLED = ["submitted"]
#: 22 `amendOrder`'s answers (24 Sec.8.4 steps 10 and 11), as B1's scripted step leaves the order
#: and the port answers: (held, its settles, the port's answer) -> (status, lifecycle state or
#: problem code, `Retry-After`, the `AMEND` sent, the `ETag` carried). The scripted facade's
#: version is 7, none once the order is final.
_ANSWERS: list[tuple[str, str, list[str], Any, int, str, str | None, bool, bool]] = [
    ("accepted", "submitted", _SETTLED, _OK, 202, "submitted", None, True, True),
    ("unknown_transport", "submitted", ["unknown"], None, 202, "unknown", None, True, True),
    ("unknown_110001", "submitted", ["unknown"], _GONE, 202, "unknown", None, True, True),
    ("final", "submitted", ["filled"], _OK, 202, "filled", None, True, False),
    ("not_amendable", "cancel_pending", [], _OK, 422, "order_not_amendable", None, False, False),
    ("no_account", "submitted", _SETTLED, _no(oc.ACCOUNT_UNAVAILABLE), 409,
     "account_unavailable", None, True, False),
    ("no_rate_token", "submitted", _SETTLED, _no(_RATE, retry_after_s=4), 429,
     "exchange_rate_limited", "4", True, False),
    ("venue_refusal", "submitted", _SETTLED, _no(_VENUE, exchange_ret_code=110003), 502,
     "exchange_error", None, True, False),
    ("unread", "submitted", _SETTLED, _no(oc.STORE_UNAVAILABLE), 503, "store_unavailable", "1",
     True, False),
    ("stop_in_flight", "submitted", _SETTLED, _no(oc.STOP_REQUEST_IN_FLIGHT, retry_after_s=5),
     409, "stop_request_in_flight", "5", True, False),
    ("port_not_amendable", "submitted", _SETTLED, _no(oc.ORDER_NOT_AMENDABLE), 422,
     "order_not_amendable", None, True, False),
    ("native_stop", "submitted", _SETTLED, _no(b01.NATIVE_STOP_REQUIRED), 400,
     "validation_failed", None, True, False),
    ("stop_loosening", "submitted", _SETTLED, _no(oc.STOP_LOOSENING_REFUSED), 403,
     "risk_limit_breached", None, True, False),
]  # fmt: skip


@pytest.mark.parametrize("case", _ANSWERS, ids=[case[0] for case in _ANSWERS])
async def test_each_answer_is_22s_from_the_exit_services_outcome(
    case: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The service's outcome rendered as it gives it (24 Sec.8.4 step 11): a refusal recorded by
    the service, naming no route step, and counted; a `202` with the order's `ETag` wherever B1's
    facade gives a version, an `unknown` amend's too (22 `OrderETag`: none for a final order)."""
    _, held, settles, port_answer, status, got, retry, sent, tagged = case
    world, machines, row, _ = await er.scripted_world(held, *settles, answer=port_answer)
    amending(machines, monkeypatch)
    routed(world, versions=machines)
    answer = await patch(world, row.id)
    body = answer.json()
    assert (answer.status_code, answer.headers.get("retry-after")) == (status, retry)
    assert machines.sent == (["AMEND"] if sent else [])
    assert answer.headers.get("etag") == (order_etag(row.id, 7) if tagged else None)
    if status == 202:
        er._ORDER.validate(body)
        assert (body["id"], body["lifecycle_state"]) == (str(row.id), got)
        return
    er._PROBLEM.validate(body)
    assert (body["code"], refused(world, got)) == (got, 1)
    assert body.get("retry_after_seconds") == (None if retry is None else int(retry))
    assert (world.actions()[-1], world.steps()[-1]) == ((_DENIED, got), None)
    assert body.get("exchange") == ({"ret_code": 110003} if status == 502 else None)


async def test_an_unknown_amends_202_carries_the_orders_etag_and_its_replay_the_stored_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An amend left `unknown` (never re-sent, 24 Sec.8.2 S1) is answered `202` with the order's
    `ETag` as B1's facade reads it, kept with the `202` for 24 h: its replay answers the stored
    tag, never the order's tag as it stands then."""
    world, machines, row, _ = await er.scripted_world("submitted", "unknown", answer=None)
    amending(machines, monkeypatch)
    routed(world, versions=machines)
    first = await patch(world, row.id)
    assert (first.status_code, first.json()["lifecycle_state"]) == (202, "unknown")
    assert first.headers["etag"] == order_etag(row.id, 7)
    monkeypatch.setattr(machines, "version", lambda _order_id: 8)  # the order moved on since
    again = await patch(world, row.id)
    assert (again.headers["idempotency-replayed"], again.headers["etag"]) == (
        "true", first.headers["etag"],
    )  # fmt: skip
    assert machines.sent == ["AMEND"]


@pytest.mark.parametrize("where", ["scope", "amend"], ids=["step-4", "step-11"])
@pytest.mark.parametrize(
    ("error", "page"), er._FAULTS, ids=["a-row-that-pages", "no-row", "no-oms-error"]
)
async def test_a_fault_the_exit_service_raises_is_a_500_paged_once_and_counted_as_the_amends(
    monkeypatch: pytest.MonkeyPatch, where: str, error: Exception, page: str
) -> None:
    """The orchestrator's ruling of 2026-10-25 02:50Z (2) on the amend route, as on the cancel's:
    a fault the exit service raises at step 4's scope read or in step 11's amend, which no outcome
    answers, is the redacted `500 internal_error` (`exit_fault`), paged once by its class alone,
    never its text, and counted once under the amend's own operation (its own `faulted`), never
    the cancel's; nothing is kept."""
    world, _, row, _ = await er.scripted_world("submitted")
    routed(world)

    async def faulty(*_args: Any, **_kwargs: Any) -> ex.ExitOutcome:
        raise error

    monkeypatch.setattr(world.oms.service, where, faulty)
    answer = await patch(world, row.id)
    body = answer.json()
    er._PROBLEM.validate(body)
    assert (answer.status_code, body["code"], set(body)) == (500, "internal_error", er._REDACTED)
    assert world.pages == [page] and str(error) not in answer.text
    assert (refused(world, "internal_error"), world.refused("internal_error")) == (1, 0)
    assert world.cache.get(str(OWNER), f"amendOrder:{KEY}") is None


async def test_a_key_is_the_principals_for_this_order_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 8: the key on another order is `409 idempotency_key_reuse`, recorded at step
    `replay`; another principal's same key and body is a key never seen, amended afresh (C-12.4,
    the cross-account case)."""
    world, machines, row, port = await er.scripted_world("submitted", *_SETTLED * 2)
    amending(machines, monkeypatch)
    routed(world, versions=machines)
    first = await patch(world, row.id)
    other = await port.stored(cr.new_order(seq=1), lifecycle="submitted")
    reused = await patch(world, other.id)
    assert (first.status_code, reused.status_code) == (202, 409)
    assert reused.json()["code"] == "idempotency_key_reuse"
    assert (world.actions()[-1], world.steps()[-1]) == (_REUSED, "replay")
    fresh = await patch(world, row.id, who="second")
    assert fresh.status_code == 202 and "idempotency-replayed" not in fresh.headers
    assert machines.sent == ["AMEND", "AMEND"]


# --- the body's terms, the scope, the arm token and the `ETag`, over the real B1 facade ----------


@pytest.fixture
async def rig() -> AsyncIterator[SubmitRig]:
    async with sr.rigged() as built:
        built.store.seed_owner(OWNER)
        yield built


async def amendable(rig: SubmitRig, who: str = "owner", **over: Any) -> tuple[er.World, OrderRow]:
    """The route over the rig's exit service (`over` replacing its dependencies), the rig's entry
    placed, its leg's profile held under its id (D1's check), `who`'s grant held by the store."""
    row = await tx.placed(rig)
    found = await tx.exits_of(rig).scope(ex.ExitCaller(OwnerScope(OWNER), tx.actor(OWNER)), row.id)
    assert isinstance(found, ScopedOrder)
    rig.profiles.held[(cr.ACCOUNT, found.profile_id)] = sr.profile()
    if who in ("creator", "other", "view_only", "frozen"):
        user = sr.USER if who == "creator" else tx.OTHER
        rig.store.seed_access(user, cr.ACCOUNT, trade=who != "view_only", frozen=who == "frozen")
    world = er.world_of(tx.exits_of(rig, **over), rig.port.audits)
    routed(world, versions=rig.machines)
    return world, row


def amends(rig: SubmitRig) -> list[Any]:
    return [call.request for call in rig.port.demo.calls if call.method == "amend_order"]


#: Each body as the exit service's terms (22 `AmendOrderRequest`): a TP/SL side named `null` is
#: asked cleared, one not named is not amended.
_EVERY = {
    "qty": "0.005", "price": "60100", "trigger_price": "61000",
    "take_profit": {"unit": "price", "value": "64500"},
    "stop_loss": {"unit": "ticks", "value": "10"},
}  # fmt: skip
_TERMS: list[tuple[str, dict[str, Any], ex.AmendTerms]] = [
    ("every_member", _EVERY, ex.AmendTerms(
        qty=D("0.005"), price=D("60100"), trigger_price=D("61000"),
        sides={"take_profit": StopOffset("price", D("64500")),
               "stop_loss": StopOffset("ticks", D("10"))},
    )),
    ("take_profit_null", {"take_profit": None}, ex.AmendTerms(sides={"take_profit": None})),
    ("stop_loss_null", {"stop_loss": None}, ex.AmendTerms(sides={"stop_loss": None})),
    ("price_alone", {"price": "60100"}, ex.AmendTerms(price=D("60100"))),
]  # fmt: skip


@pytest.mark.parametrize(
    ("body", "terms"), [case[1:] for case in _TERMS], ids=[case[0] for case in _TERMS]
)
async def test_the_body_reaches_the_exit_service_as_its_terms(
    body: dict[str, Any], terms: ex.AmendTerms, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 5: the body read once, strictly, into the terms the service judges."""
    world, _, row, _ = await er.scripted_world("submitted")
    routed(world)
    asked: list[ex.AmendTerms] = []

    async def spy(_scoped: ScopedOrder, got: ex.AmendTerms, **_kwargs: Any) -> ex.ExitOutcome:
        asked.append(got)
        return ex.ExitOutcome(kind="refused", status=409, code="conflict", detail="Held.")

    monkeypatch.setattr(world.oms.service, "amend", spy)
    await patch(world, row.id, body)
    assert asked == [terms]


@pytest.mark.parametrize(
    ("side", "rule", "kept"),
    [("stop_loss", "native_stop_required", D("58000")),
     ("take_profit", "tpsl_clear_unsupported", D("64000"))],
    ids=["native_sl", "take_profit"],
)  # fmt: skip
async def test_native_sl_a_side_named_null_is_refused_nothing_sent_and_the_side_kept(
    rig: SubmitRig, side: str, rule: str, kept: Decimal
) -> None:
    """C-2.6 over HTTP: a stop asked cleared is refused (`native_stop_required`), and a take-profit
    too (`tpsl_clear_unsupported`), each recorded by the service; nothing is sent and the order's
    side stays as it was."""
    world, row = await amendable(rig)
    answer = await patch(world, row.id, {side: None})
    assert (answer.status_code, answer.json()["code"]) == (400, "validation_failed")
    assert [(e["field"], e["rule"]) for e in answer.json()["errors"]] == [(side, rule)]
    assert (world.actions()[-1], world.steps()[-1]) == ((_DENIED, "validation_failed"), None)
    stored = await rig.port.orders.get(cr.ACCOUNT, row.id)
    assert amends(rig) == [] and stored is not None and getattr(stored, side) == kept


async def test_a_stop_tightened_beside_a_new_price_is_sent_with_both_sides(rig: SubmitRig) -> None:
    """Q2 over HTTP: a tighter stop named beside a price is sent with the take-profit re-paired at
    its current value."""
    world, row = await amendable(rig)
    body = {"price": "60100", "stop_loss": {"unit": "price", "value": "58500"}}
    answer = await patch(world, row.id, body)
    assert answer.status_code == 202
    [sent] = amends(rig)
    assert (sent.price, sent.stop_loss, sent.take_profit) == (D("60100"), D("58500"), D("64000"))


async def test_an_amend_answers_202_with_the_order_and_its_new_etag(rig: SubmitRig) -> None:
    """22 `amendOrder`: the order as B1's step left it, with its new `ETag` (ruling Q5), the
    amend written ahead and its outcome recorded."""
    world, row = await amendable(rig)
    before = rig.machines.version(row.id)
    answer = await patch(world, row.id, {"price": "60100"})
    assert answer.status_code == 202
    er._ORDER.validate(answer.json())
    after = rig.machines.version(row.id)
    assert before is not None and after is not None and after > before
    assert answer.headers["etag"] == order_etag(row.id, after)
    assert (Decimal(answer.json()["price"]), len(amends(rig))) == (Decimal("60100"), 1)
    assert world.actions() == [(_DENIED, "user"), (_DENIED, "submitted")]


async def test_the_202_is_kept_24h_and_its_replay_carries_the_stored_etag(rig: SubmitRig) -> None:
    """Step 8: the repeat is the first `202`, its `ETag` as stored, though the order moved on since
    (an amend under another key); nothing is sent again."""
    world, row = await amendable(rig)
    first = await patch(world, row.id, {"price": "60100"})
    moved = await patch(world, row.id, {"price": "60200"}, key=uuid4())
    again = await patch(world, row.id, {"price": "60100"})
    assert (first.status_code, moved.status_code, again.status_code) == (202, 202, 202)
    assert moved.headers["etag"] != first.headers["etag"]
    assert again.headers["idempotency-replayed"] == "true"
    assert again.headers["etag"] == first.headers["etag"] and again.content == first.content
    assert len(amends(rig)) == 2  # the repeat sent nothing


async def test_another_body_under_a_key_is_409_recorded_nothing_sent(rig: SubmitRig) -> None:
    world, row = await amendable(rig)
    first = await patch(world, row.id, {"price": "60100"})
    other = await patch(world, row.id, {"price": "60200"})
    assert (first.status_code, other.status_code) == (202, 409)
    assert other.json()["code"] == "idempotency_key_reuse" and len(amends(rig)) == 1
    assert (world.actions()[-1], world.steps()[-1]) == (_REUSED, "replay")


async def test_a_refusal_is_not_kept_and_its_key_is_free_once_its_amend_ended(
    rig: SubmitRig,
) -> None:
    """The 24 h record holds a `2xx` only: an amend refused `412` may be sent again under its
    key, which the guard frees once that amend's task ended (24 Sec.8.4 steps 8 and 9)."""
    world, row = await amendable(rig)
    seq = rig.machines.version(row.id)
    assert seq is not None
    stale = await patch(world, row.id, {"price": "60100"}, if_match=order_etag(row.id, seq + 1))
    named = await patch(world, row.id, {"price": "60100"}, if_match=order_etag(row.id, seq))
    assert (stale.status_code, named.status_code) == (412, 202)
    assert "idempotency-replayed" not in named.headers and len(amends(rig)) == 1


@pytest.mark.parametrize("tag", ["stale", "another_order", "star", "weak", "list", "empty"])
async def test_an_if_match_not_naming_the_version_read_is_412_nothing_sent(
    rig: SubmitRig, tag: str
) -> None:
    """Ruling Q5: `*`, a list, a weak or malformed tag, another order's and a stale one alike, and
    one empty field, a list naming no tag (22 `amendOrder`, RFC 9110 Sec.5.3), never read as no
    `If-Match`: each refused by the service, recorded once, naming no route step, and counted."""
    world, row = await amendable(rig)
    seq = rig.machines.version(row.id)
    assert seq is not None
    named = {
        "stale": order_etag(row.id, seq + 1), "another_order": order_etag(uuid4(), seq),
        "star": "*", "weak": f"W/{order_etag(row.id, seq)}",
        "list": f"{order_etag(row.id, seq)}, {order_etag(row.id, seq)}", "empty": "",
    }[tag]  # fmt: skip
    answer = await patch(world, row.id, {"price": "60100"}, if_match=named)
    assert (answer.status_code, answer.json().get("code")) == (412, "version_conflict")
    assert (amends(rig), refused(world, "version_conflict")) == ([], 1)
    assert (world.actions(), world.steps()) == ([(_DENIED, "version_conflict")], [None])


async def test_an_if_match_sent_as_two_fields_is_one_list_and_412(rig: SubmitRig) -> None:
    """22 `amendOrder` (RFC 9110 Sec.5.3): two `If-Match` fields are one list, which names no
    version: `412` with nothing sent, though the first names the version read."""
    world, row = await amendable(rig)
    seq = rig.machines.version(row.id)
    assert seq is not None
    tag = order_etag(row.id, seq)
    fields = (("if-match", tag), ("if-match", tag))
    answer = await patch(world, row.id, {"price": "60100"}, fields=fields)
    assert (answer.status_code, answer.json()["code"]) == (412, "version_conflict")
    assert amends(rig) == []


async def test_an_if_match_naming_the_version_read_sends_the_amend(rig: SubmitRig) -> None:
    world, row = await amendable(rig)
    seq = rig.machines.version(row.id)
    assert seq is not None
    answer = await patch(world, row.id, {"price": "60100"}, if_match=order_etag(row.id, seq))
    assert (answer.status_code, len(amends(rig))) == (202, 1)


@pytest.mark.parametrize(
    ("who", "status", "code", "denied"),
    [
        ("owner", 202, None, None),
        ("creator", 202, None, None),
        ("other", 403, "forbidden", ex.NOT_ORDER_CREATOR),
        ("view_only", 403, "account_scope_denied", ex.VIEW_ONLY),
        ("ungranted", 404, "not_found", ex.NOT_GRANTED),
        ("frozen", 404, "not_found", ex.NOT_GRANTED),
    ],
)
async def test_the_scope_is_the_exit_services_as_rulings_q6_q7_and_q12_say(
    rig: SubmitRig, who: str, status: int, code: str | None, denied: str | None
) -> None:
    """A Manager amends only the orders it created (04 Sec.7.2.2 rows 12, 13); a view-only grant
    is 403 (Q7); an ungranted or frozen account's order is 404 (SR-E29-13), recorded once by the
    service; nothing is sent."""
    world, row = await amendable(rig, who)
    answer = await patch(world, row.id, {"price": "60100"}, who)
    assert answer.status_code == status
    if code is None:
        assert len(amends(rig)) == 1
        return
    assert (answer.json()["code"], amends(rig), refused(world, code)) == (code, [], 1)
    assert world.actions() == [("rbac.denied", denied)]


async def test_a_stored_202_is_not_replayed_once_the_callers_grant_is_frozen(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """24 Sec.8.4: the lookup comes after authorisation, so a caller who has lost access reads no
    outcome back (SR-E29-13)."""
    world, row = await amendable(rig, "creator")
    first = await patch(world, row.id, {"price": "60100"}, "creator")
    assert first.status_code == 202
    rig.store.seed_access(sr.USER, cr.ACCOUNT, trade=True, frozen=True)
    frozen = TradingPrincipal(sr.SESSION, PrincipalSnapshot(
        sr.USER, frozenset({"manager"}), frozenset({Permission.ORDERS_WRITE}),
        (AccountGrant(cr.ACCOUNT, True, True, True),),
    ))  # fmt: skip
    monkeypatch.setattr(er, "principal", lambda who: frozen)
    again = await patch(world, row.id, {"price": "60100"}, "creator")
    assert (again.status_code, again.json()["code"]) == (404, "not_found")
    assert "idempotency-replayed" not in again.headers


async def test_every_record_the_route_causes_names_its_principal_and_its_request(
    rig: SubmitRig,
) -> None:
    """C-2.9, #3990: a guard refusal's record and an amend's own, each the Owner's (user, role,
    session and source address), under this request's id."""
    world, row = await amendable(rig)
    claimed = world.oms.service.guard.claim(OWNER, "amend", KEY)
    assert not isinstance(claimed, ex.ExitOutcome)
    refusal = await patch(world, row.id, {"price": "60100"})
    claimed()  # release
    answer = await patch(world, row.id, {"price": "60100"}, key=uuid4())
    assert (refusal.status_code, answer.status_code) == (409, 202)
    written = [r for r, _ in world.audits.written[world.since :] if isinstance(r, RequestRecord)]
    assert [(record.actor, record.request_id) for record in written] == [(er.ACTOR, TRACE)] * 3


@pytest.mark.parametrize(
    ("body", "env", "token", "status"),
    [
        (_RAISE, "live", None, 403),
        (_RAISE, "live", "the-token", 202),
        (_CUT, "live", None, 202),
        (_RAISE, "demo", None, 202),
        ({"price": "60100"}, "live", None, 403),  # a moved price on an entry raises exposure
    ],
    ids=["live-raise", "live-raise-armed", "live-cut", "demo-raise", "live-reprice"],
)
async def test_only_a_live_risk_increasing_amend_needs_the_arm_token(
    rig: SubmitRig, body: dict[str, str], env: Environment, token: str | None, status: int
) -> None:
    """Step 6 (24 Sec.8.4, 22 `amendOrder`), judged on step 4's read: a cut never needs it
    (C-2.6); a raise on a demo account neither."""
    world, row = await amendable(rig)
    arms = routed(world, env)
    if token is None:
        answer = await patch(world, row.id, body)
    else:
        answer = await patch(world, row.id, body, x_arm_token=token)
    assert answer.status_code == status
    if status == 403:
        assert answer.json()["code"] == "session_not_armed" and amends(rig) == []
        assert world.steps() == ["arm"]
        return
    gated = body is not _CUT
    assert len(arms.shown) == int(gated)  # asked only for a risk-increasing amend
    if token is not None:
        assert isinstance(arms.shown[0], ArmToken) and str(arms.shown[0]) != token


async def test_with_the_flag_off_a_raise_is_refused_and_a_cut_passes(rig: SubmitRig) -> None:
    """Step 10 (ruling Q10): `trading.oms_enabled` off refuses a risk-increasing amend only."""
    world, row = await amendable(rig, oms_enabled=lambda: False)
    up = await patch(world, row.id, _RAISE)
    assert (up.status_code, up.json()["code"]) == (403, "trading_disabled")
    down = await patch(world, row.id, _CUT, key=uuid4())
    assert (down.status_code, len(amends(rig))) == (202, 1)


@pytest.mark.parametrize(
    ("tagged", "status", "code", "retry"),
    [(False, 409, "conflict", "1"), (True, 412, "version_conflict", None)],
    ids=["unpinned", "if-match"],
)  # fmt: skip
async def test_a_step_11_refusal_is_answered_as_the_service_gives_it_and_counted(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch, tagged: bool, status: int, code: str,
    retry: str | None,
) -> None:  # fmt: skip
    """D2a's step-11 refusal is consumed, never re-decided (the orchestrator's rulings of
    2026-10-25 00:27Z (1) and 01:11Z): step 4 read the order before a cut settled, so it took a
    quantity of 0.009 for a cut, which the order as it stands, 0.001, makes a raise. The service
    refuses it before the send and records it once, at its step (`class`): `409 conflict` with
    `Retry-After: 1`, `412` with `If-Match`, each counted `{operation="amend", code}`."""
    world, row = await amendable(rig)
    first = await world.oms.service.scope(ex.ExitCaller(OwnerScope(OWNER), tx.actor(OWNER)), row.id)
    assert isinstance(first, ScopedOrder)
    assert (await patch(world, row.id, {"qty": "0.001"}, key=uuid4())).status_code == 202

    async def stale(*_args: Any) -> ScopedOrder:  # step 4's read, from before the cut
        return first

    monkeypatch.setattr(world.oms.service, "scope", stale)
    world.since = len(world.audits.written)
    seq = rig.machines.version(row.id)
    assert seq is not None
    if tagged:
        answer = await patch(world, row.id, {"qty": "0.009"}, if_match=order_etag(row.id, seq))
    else:
        answer = await patch(world, row.id, {"qty": "0.009"})
    assert (answer.status_code, answer.json()["code"]) == (status, code)
    assert answer.headers.get("retry-after") == retry
    assert (world.actions(), world.steps()) == ([(_DENIED, code)], ["class"])
    assert (refused(world, code), len(amends(rig))) == (1, 1)


async def test_the_services_body_refusal_is_answered_with_its_rules(rig: SubmitRig) -> None:
    """A body the model reads but the service refuses (22 `amendOrder`'s rules): its 400 as the
    service gave it, recorded by the service, counted."""
    world, row = await amendable(rig)
    answer = await patch(world, row.id, {})
    assert (answer.status_code, answer.json()["code"]) == (400, "validation_failed")
    assert [e["rule"] for e in answer.json()["errors"]] == ["nothing_to_amend"]
    assert refused(world, "validation_failed") == 1 and amends(rig) == []


@pytest.mark.parametrize("where", ["scope", "run", "amend"], ids=["step-4", "step-9", "step-11"])
async def test_an_amend_that_meets_a_stopped_lane_is_the_counted_503_unaudited_and_unpaged(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """24 Sec.8.4, binding on the amend over the order lane (L1b's handoff of 2026-10-25): an
    `OmsNotReady` out of `exits.scope` or `exits.amend`, an `OnLaneExits` hop finding the lane
    stopped, or the gate check not begun within 1 s, or out of `runtime.run`, its stop begun, is
    step 3's answer: `503 oms_not_ready` with its `Retry-After`, counted once under `{amend,
    oms_not_ready}`, its key free again, with no `ETag`, no 24 h record, no `deny` through the
    stalled lane, no page and nothing sent. It is never logged `oms_exit_refusal_escaped`, which
    `exit_fault` logs for a refusal that escaped the exit service: a stopped lane is no such
    refusal, so nothing is logged at warning or above."""
    world, row = await amendable(rig)
    before, denied = world.actions(), list[tuple[Any, ...]]()
    real = world.oms.service.deny

    async def deny(*args: Any, **kwargs: Any) -> ex.ExitOutcome:
        denied.append(args)
        return await real(*args, **kwargs)

    monkeypatch.setattr(world.oms.service, "deny", deny)
    if where == "run":
        world.oms.stopped = "run"
    else:
        monkeypatch.setattr(world.oms.service, where, er.lane_stopped)
    with capture_logs() as logs:
        answer = await patch(world, row.id, {"price": "60100"})
    assert (answer.status_code, answer.json()["code"]) == (503, "oms_not_ready")
    assert answer.headers.get("retry-after") == str(OMS_NOT_READY_RETRY_AFTER_S)
    assert "etag" not in answer.headers and world.pages == []
    assert (world.actions(), denied, amends(rig)) == (before, [], [])
    assert world.cache.get(str(OWNER), f"amendOrder:{KEY}") is None
    assert (refused(world, "oms_not_ready"), world.refused("oms_not_ready")) == (1, 0)
    assert callable(world.oms.service.guard.claim(OWNER, "amend", KEY))
    assert [line for line in logs if line["log_level"] in ("warning", "error", "critical")] == []


#: A refusal the route makes from step 5 on, each recorded through `deny` before it is answered
#: (24 Sec.8.4): (the step its record names, the change, the body and the key that refuse there,
#: the code it is answered with while its record lands).
_OWN: list[tuple[str, Any, Any, UUID | None, str]] = [
    ("body", None, {"qty": "lots"}, KEY, "validation_failed"),
    ("arm", _live, _RAISE, KEY, "session_not_armed"),
    ("key", None, _CUT, None, "validation_failed"),
    ("replay", _recorded_elsewhere, _CUT, KEY, "idempotency_key_reuse"),
    ("guard", None, _CUT, KEY, "idempotency_in_flight"),
]  # fmt: skip


@pytest.mark.parametrize("case", _OWN, ids=["step-5", "step-6", "step-7", "step-8", "step-9"])
async def test_a_refusal_whose_record_meets_a_stopped_lane_is_the_counted_503_unaudited(
    case: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """24 Sec.8.4's binding at the route's own refusals (the delta's F3 at e677aa89): a refusal from
    step 5 on is recorded through `deny`, a hop to the order lane, before it is answered, and a lane
    that stopped after step 4 makes that hop `OmsNotReady`. It is step 3's answer, as at steps 4, 9
    and 11: `503 oms_not_ready` with its `Retry-After` in the refusal's place, counted once under
    `{amend, oms_not_ready}`, never the cancel's nor under the refusal's own code, unaudited, with
    no `ETag`, no 24 h record, no page, nothing sent and nothing logged at warning or above; the
    key is free. Step 9's guard refusal gets it too, as it did through `run_claimed` before."""
    step, change, body, key, own = case
    world, machines, row, _ = await er.scripted_world("submitted")
    routed(world)
    if change is not None:
        change(world)
    guard = world.oms.service.guard
    held = guard.claim(OWNER, "amend", KEY) if step == "guard" else None  # in flight
    kept = world.cache.get(str(OWNER), f"amendOrder:{KEY}")
    met: list[object] = []

    async def stopped(*_args: Any, **kwargs: Any) -> ex.ExitOutcome:
        met.append(kwargs.get("step"))
        raise OmsNotReady

    monkeypatch.setattr(world.oms.service, "deny", stopped)
    with capture_logs() as logs:
        answer = await patch(world, row.id, body, key=key)
    problem = answer.json()
    er._PROBLEM.validate(problem)
    assert (answer.status_code, problem["code"], met) == (503, "oms_not_ready", [step])
    assert answer.headers.get("retry-after") == str(OMS_NOT_READY_RETRY_AFTER_S)
    assert "etag" not in answer.headers and world.pages == []
    assert (world.actions(), machines.sent, world.oms.tasks) == ([], [], [])
    assert world.cache.get(str(OWNER), f"amendOrder:{KEY}") == kept
    counted = (refused(world, "oms_not_ready"), world.refused("oms_not_ready"), refused(world, own))
    assert counted == (1, 0, 0)
    assert [line for line in logs if line["log_level"] in ("warning", "error", "critical")] == []
    if callable(held):  # the test's own claim
        held()
    assert callable(guard.claim(OWNER, "amend", KEY))


@pytest.mark.parametrize(
    "error",
    [StoreUnavailable(), RuntimeError("a defect in the record's hop")],
    ids=["oms-error", "no-oms-error"],
)
async def test_a_refusals_record_that_fails_otherwise_is_no_stopped_lane(
    error: Exception, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The binding takes `OmsNotReady` alone: any other error out of a refusal's record, another
    `OmsError` too, takes the route's path as before, out of the route to the app's own `500`,
    never answered or counted as `oms_not_ready`."""
    world, machines, row, _ = await er.scripted_world("submitted")
    routed(world)

    async def fails(*_args: Any, **_kwargs: Any) -> ex.ExitOutcome:
        raise error

    monkeypatch.setattr(world.oms.service, "deny", fails)
    with pytest.raises(type(error)):
        await patch(world, row.id, key=None)  # step 7's refusal, recorded through `deny`
    assert (refused(world, "oms_not_ready"), machines.sent, world.oms.tasks) == (0, [], [])


@pytest.mark.parametrize(
    "refusal",
    [GatewayOverloadedError("order:x", "order"), GatewayDegradedError("order:x", "order")],
    ids=["inbox-full", "degraded"],
)
async def test_an_amend_the_gateway_refuses_for_backpressure_is_the_services_recorded_503(
    refusal: GatewayError, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-S4D2A-01 on the amend route: the order's gateway refusing the `AMEND` for backpressure,
    its inbox full or its admission refused, is no stopped lane but the exit service's own refusal
    (`_refused(OmsNotReady())` through `_dispatch`), an outcome the route answers as given: `503
    oms_not_ready` with its `Retry-After`, recorded `denied` beside the intent and counted once,
    with no page, no `ETag`, nothing kept and nothing sent."""
    world, machines, row, _ = await er.scripted_world("submitted")
    amending(machines, monkeypatch)
    routed(world, versions=machines)
    machines.refuse = refusal
    answer = await patch(world, row.id)
    body, retry = answer.json(), OMS_NOT_READY_RETRY_AFTER_S
    er._PROBLEM.validate(body)
    assert (answer.status_code, body["code"], body.get("retry_after_seconds")) == (
        503, "oms_not_ready", retry,
    )  # fmt: skip
    assert answer.headers["retry-after"] == str(retry) and "etag" not in answer.headers
    assert (world.pages, machines.sent) == ([], [])
    assert world.actions() == [(_DENIED, "user"), (_DENIED, "oms_not_ready")]
    assert (refused(world, "oms_not_ready"), refused(world, "internal_error")) == (1, 0)
    assert world.cache.get(str(OWNER), f"amendOrder:{KEY}") is None


async def test_a_client_that_leaves_does_not_stop_the_amend_nor_free_its_key_early(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Step 11, shielded: the amend runs on as the runtime's task, its key held until it ends (a
    repeat meanwhile is in flight), and its `202` is kept for the repeat, `ETag` and all."""
    world, row = await amendable(rig)
    gate, entered = asyncio.Event(), asyncio.Event()
    real = world.oms.service.amend

    async def held(*args: Any, **kwargs: Any) -> ex.ExitOutcome:
        entered.set()
        await gate.wait()
        return await real(*args, **kwargs)

    monkeypatch.setattr(world.oms.service, "amend", held)
    sent = asyncio.ensure_future(patch(world, row.id, {"price": "60100"}))
    waiting = asyncio.ensure_future(entered.wait())
    done, _ = await asyncio.wait({sent, waiting}, return_when=asyncio.FIRST_COMPLETED)
    waiting.cancel()
    assert done == {waiting}  # handed to the service, the request still waiting
    sent.cancel()
    with pytest.raises(asyncio.CancelledError):
        await sent
    meanwhile = await patch(world, row.id, {"price": "60100"})
    assert (meanwhile.status_code, meanwhile.json()["code"]) == (409, "idempotency_in_flight")
    gate.set()
    (task,) = world.oms.tasks
    first = await task
    assert first.status_code == 202
    again = await patch(world, row.id, {"price": "60100"})
    assert (again.status_code, again.headers["idempotency-replayed"]) == (202, "true")
    assert again.headers["etag"] == first.headers["etag"] and len(amends(rig)) == 1
