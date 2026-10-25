"""`PATCH /orders/{orderId}`, `amendOrder` (E29-T04 #913 slice 4, S4-D2b; 24 Sec.8.4 "The exit
routes", 22 `amendOrder`, the slice-4 rulings Q5 to Q7, Q10 to Q12 and Q14, SEC-S4C2B-01). The
route runs in the exit routes' router (`make_order_exits_router`) over the real exit service: on
S4-C's scripted facade (`test_exits.scripted`) for each step's refusal, and on the real B1 facade,
command port and fake venue (`submit_rig`, the rig's limit buy entry resting `submitted`: 0.010 at
60000, its stop 58000 and its take-profit 64000) for the answers, the scope, the arm token, the
flag and the `ETag`. Each `202` is validated against 22 `Order`, each problem against
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

from candleviewer.api.idempotency import StoredResponse
from candleviewer.api.order_admission import MAX_ORDER_BODY_BYTES
from candleviewer.api.order_etag import order_etag
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.domain.primitives import Environment
from candleviewer.oms import exits as ex
from candleviewer.oms.ports import ArmToken, RequestRecord
from candleviewer.storage.repositories.accounts import OwnerScope
from candleviewer.storage.repositories.orders import OrderRow, ScopedOrder
from tests.unit.api import test_order_exits_route as er
from tests.unit.api.test_orders_route import ArmChecks
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr
from tests.unit.oms import test_exits as tx
from tests.unit.oms.submit_rig import SubmitRig

OWNER, KEY, TRACE = er.OWNER, er.KEY, er.TRACE
_DENIED = "orders.amend"
_CUT = {"qty": "0.005"}  # a smaller quantity: never gated (C-2.6)
_RAISE = {"qty": "0.011"}  # a larger one on an entry: risk-increasing (24 Sec.8.10)


def routed(world: er.World, env: Environment = "demo") -> ArmChecks:
    """The route's reads of the runtime: `env`, and the arm records (a live account passes with a
    token only)."""
    arms = ArmChecks()
    world.oms.route = SimpleNamespace(environment=env, arm_records=arms)
    return arms


def refused(world: er.World, code: str) -> float:
    labels = {"env": "demo", "operation": "amend", "code": code}
    return world.metrics.registry.get_sample_value("oms_exit_refused_total", labels) or 0.0


async def patch(
    world: er.World, order: object, body: object = _CUT, who: str = "owner", key: object = KEY,
    **headers: str,
) -> httpx.Response:  # fmt: skip
    sent = {"authorization": f"Bearer {who}", "x-correlation-id": str(TRACE)}
    if key is not None:
        sent["idempotency-key"] = str(key)
    sent |= {name.replace("_", "-"): value for name, value in headers.items()}
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    async with AsyncClient(transport=ASGITransport(app=world.app()), base_url="http://t") as c:
        return await c.patch(f"/orders/{order}", content=raw, headers=sent)


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


_FULL = tuple(UUID(int=n) for n in range(1, ex.MAX_IN_FLIGHT_PER_PRINCIPAL + 1))
_LARGE = b'{"qty": "0.005", "pad": "' + b"x" * MAX_ORDER_BODY_BYTES + b'"}'
#: The step a route refusal's record names (`deny`'s `step`).
_STEP_OF = {
    "5_too_large": "body", "5_not_an_object": "body", "5_extra_member": "body",
    "5_not_a_number": "body", "6_not_armed": "arm", "7_no_key": "key", "8_reuse": "replay",
    "9_in_flight": "guard", "9_full": "guard",
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
    ("3_starting", lambda w: setattr(w.oms, "state", "starting"), "owner", "row", _CUT, KEY, 503,
     "oms_not_ready", []),
    ("3_stopping", lambda w: setattr(w.oms, "stopped", "exits"), "owner", "row", _CUT, KEY, 503,
     "oms_not_ready", []),
    ("4_missing", None, "owner", "missing", _CUT, KEY, 404, "not_found", []),
    ("5_too_large", None, "owner", "row", _LARGE, KEY, 400, "validation_failed",
     [(_DENIED, "validation_failed")]),
    ("5_not_an_object", None, "owner", "row", b"[1]", KEY, 400, "validation_failed",
     [(_DENIED, "validation_failed")]),
    ("5_extra_member", None, "owner", "row", {"qty": "0.005", "side": "sell"}, KEY, 400,
     "validation_failed", [(_DENIED, "validation_failed")]),
    ("5_not_a_number", None, "owner", "row", {"qty": "lots"}, KEY, 400, "validation_failed",
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


@pytest.mark.parametrize("case", _STEPS, ids=[case[0] for case in _STEPS])
async def test_each_step_refuses_before_the_next_runs(case: Any) -> None:
    name, change, who, order, body, key, status, code, records = case
    world, machines, row, _ = await er.scripted_world("submitted")
    routed(world)
    if change is not None:
        change(world)
    target = {"row": row.id, "missing": uuid4()}.get(order, order)
    answer = await patch(world, target, body, who, key)
    problem = answer.json()
    er._PROBLEM.validate(problem)
    assert (answer.status_code, problem["code"], world.actions()) == (status, code, records)
    assert world.steps() == ([_STEP_OF[name]] if name in _STEP_OF else [])
    assert (machines.sent, world.oms.tasks, refused(world, code)) == ([], [], 1)
    if "retry_after_seconds" in problem:  # oms_not_ready, and the guard's 1
        assert answer.headers["retry-after"] == str(problem["retry_after_seconds"])
    if name.startswith("5_"):  # each rule that failed, named
        assert problem["errors"] and all(e["rule"] for e in problem["errors"])
    if name == "9_stopping":  # the runtime refused the run: the claim is released
        assert callable(world.oms.service.guard.claim(OWNER, "amend", KEY))


async def test_the_runtime_is_asked_after_the_permission() -> None:
    """Step order: a viewer meets step 2's 403 even while the runtime is starting (step 3)."""
    world, _, row, _ = await er.scripted_world("submitted")
    routed(world)
    world.oms.state = "starting"
    answer = await patch(world, row.id, who="viewer")
    assert (answer.status_code, answer.json()["code"]) == (403, "forbidden")


async def test_the_step_2_refusal_is_counted_when_its_record_cannot_be_written() -> None:
    world, _, row, _ = await er.scripted_world("submitted")
    routed(world)
    world.audit.fail = True
    answer = await patch(world, row.id, who="viewer")
    assert (answer.status_code, refused(world, "forbidden")) == (403, 1)


# --- the answers, over the real B1 facade, command port and fake venue ----------------------------


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
    routed(world)
    return world, row


def amends(rig: SubmitRig) -> list[Any]:
    return [call.request for call in rig.port.demo.calls if call.method == "amend_order"]


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
    world, row = await amendable(rig)
    first = await patch(world, row.id, {"price": "60100"})
    again = await patch(world, row.id, {"price": "60100"})
    assert (first.status_code, again.status_code) == (202, 202)
    assert again.headers["idempotency-replayed"] == "true"
    assert again.headers["etag"] == first.headers["etag"] and again.content == first.content
    assert len(amends(rig)) == 1  # the repeat sent nothing
    other = await patch(world, row.id, {"price": "60200"})
    assert (other.status_code, other.json()["code"]) == (409, "idempotency_key_reuse")


@pytest.mark.parametrize("tag", ["stale", "another_order", "star", "weak", "list"])
async def test_an_if_match_not_naming_the_version_read_is_412_nothing_sent(
    rig: SubmitRig, tag: str
) -> None:
    """Ruling Q5: `*`, a list, a weak or malformed tag, another order's and a stale one alike."""
    world, row = await amendable(rig)
    seq = rig.machines.version(row.id)
    assert seq is not None
    named = {
        "stale": order_etag(row.id, seq + 1), "another_order": order_etag(uuid4(), seq),
        "star": "*", "weak": f"W/{order_etag(row.id, seq)}",
        "list": f"{order_etag(row.id, seq)}, {order_etag(row.id, seq)}",
    }[tag]  # fmt: skip
    answer = await patch(world, row.id, {"price": "60100"}, if_match=named)
    assert (answer.status_code, answer.json()["code"]) == (412, "version_conflict")
    assert (amends(rig), refused(world, "version_conflict")) == ([], 1)


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
    """C-2.9, #3990: a guard refusal's record and an amend's own, each the Owner's, from this
    session, under this request's id."""
    world, row = await amendable(rig)
    claimed = world.oms.service.guard.claim(OWNER, "amend", KEY)
    assert not isinstance(claimed, ex.ExitOutcome)
    refusal = await patch(world, row.id, {"price": "60100"})
    claimed()  # release
    answer = await patch(world, row.id, {"price": "60100"}, key=uuid4())
    assert (refusal.status_code, answer.status_code) == (409, 202)
    written = [r for r, _ in world.audits.written[world.since :] if isinstance(r, RequestRecord)]
    assert len(written) == 3
    for record in written:
        assert record.actor is not None
        assert (record.actor.user_id, record.actor.role) == (OWNER, "owner")
        assert (record.actor.session_id, record.request_id) == (sr.SESSION, TRACE)


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
    headers = {} if token is None else {"x_arm_token": token}
    answer = await patch(world, row.id, body, **headers)
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


async def test_a_step_11_refusal_is_answered_as_the_service_gives_it_and_counted(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D2a's step-11 refusal is consumed, not re-decided: an amend the order as it stands made
    risk-increasing since step 4 is `409 conflict` with `Retry-After: 1`, counted
    `{operation="amend", code="conflict"}` (the orchestrator's ruling of 2026-10-25 01:11Z)."""
    world, row = await amendable(rig)

    async def moved(*_args: Any, **_kwargs: Any) -> ex.ExitOutcome:
        return ex._MOVED

    monkeypatch.setattr(world.oms.service, "amend", moved)
    answer = await patch(world, row.id, {"price": "60100"})
    assert (answer.status_code, answer.json()["code"]) == (409, "conflict")
    assert answer.headers["retry-after"] == "1" and refused(world, "conflict") == 1


async def test_the_services_body_refusal_is_answered_with_its_rules(rig: SubmitRig) -> None:
    """A body the model reads but the service refuses (22 `amendOrder`'s rules): its 400 as the
    service gave it, recorded by the service, counted."""
    world, row = await amendable(rig)
    answer = await patch(world, row.id, {})
    assert (answer.status_code, answer.json()["code"]) == (400, "validation_failed")
    assert [e["rule"] for e in answer.json()["errors"]] == ["nothing_to_amend"]
    assert refused(world, "validation_failed") == 1 and amends(rig) == []


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
