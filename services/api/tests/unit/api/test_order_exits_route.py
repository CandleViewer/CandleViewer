"""`DELETE /orders/{orderId}`, `cancelOrder` (E29-T04 #913 slice 4, S4-D1; 24 Sec.8.4 "The exit
routes", 22 `cancelOrder`, the slice-4 rulings Q6 to Q9, Q11, Q12 and Q14). The router runs on a
bare app over the real exit service, `OrderExits`: on S4-C's scripted facade (`test_exits.scripted`,
whose bounds the test reads, never the wall clock) for each step and each answer, and on the real
B1 facade, command port and fake venue (`submit_rig`) for the scope, the native stop and the gates.
Each `202` is validated against 22 `Order`, each problem against `OrderExchangeProblem`. The mount
order is `create_app()`'s."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass, field, replace
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import Response
from httpx import ASGITransport, AsyncClient
from jsonschema import Draft202012Validator
from structlog.testing import capture_logs

from candleviewer.api.idempotency import IdempotencyCache, StoredResponse
from candleviewer.api.order_exits import make_order_exits_router
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.app import create_app
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.domain.order_link import ext_key
from candleviewer.exchange.base.errors import OmsErrorCode
from candleviewer.observability.correlation import CorrelationMiddleware
from candleviewer.observability.metrics import Metrics
from candleviewer.oms import commands as oc
from candleviewer.oms import exits as ex
from candleviewer.oms.errors import (
    OMS_NOT_READY_RETRY_AFTER_S,
    OmsNotReady,
    OrderHistoryRefused,
    OrderMachinesFull,
    StoreUnavailable,
    TradingDisabled,
)
from candleviewer.oms.fakes import InMemorySubmissionStore
from candleviewer.oms.ports import RequestRecord, SubmitActor
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.gateway import (
    GatewayDegradedError,
    GatewayError,
    GatewayOverloadedError,
)
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.accounts import OwnerScope
from candleviewer.storage.repositories.orders import (
    ORDER_STATE_OF,
    NewOrder,
    OrderRow,
    ScopedOrder,
)
from tests.unit.api.test_order_acceptance import schema
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr
from tests.unit.oms import test_exits as tx
from tests.unit.oms.submit_rig import SubmitRig

OWNER, OTHER = tx.OWNER, tx.OTHER
SECOND = UUID("0e000000-0000-4000-8000-0000000000cc")  # another Owner
VIEWER = UUID("0e000000-0000-4000-8000-0000000000dd")
KEY = UUID("9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59")
TRACE = UUID("7d3c9a2e-1f4b-4c8d-9e0a-2b3c4d5e6f70")  # an `X-Correlation-Id`, a UUIDv4
PEER = "100.64.0.7"  # the address each request comes from, a tailnet peer's
#: The Owner's requests' actor, as each record names it (C-2.9): user, role, session, address.
ACTOR = SubmitActor(OWNER, "owner", sr.SESSION, PEER)
_TRADE = frozenset({Permission.ORDERS_WRITE, Permission.ORDERS_READ})
_FORMATS = Draft202012Validator.FORMAT_CHECKER
_ORDER = Draft202012Validator(schema("Order"), format_checker=_FORMATS)
_PROBLEM = Draft202012Validator(schema("OrderExchangeProblem"), format_checker=_FORMATS)
_OK: dict[str, Any] = {"ok": True}


def principal(who: str) -> TradingPrincipal:
    """An Owner (`owner`, `second`), a viewer, or a Manager of `cr.ACCOUNT`: the order's creator
    (`creator`, or `creator_frozen` once its grant is frozen), another user (`other`), on a
    view-only (`view_only`) or frozen grant, or none."""
    if who in ("owner", "second"):
        owner = OWNER if who == "owner" else SECOND
        snap = PrincipalSnapshot(owner, frozenset({"owner"}), frozenset(Permission))
    elif who == "viewer":
        snap = PrincipalSnapshot(VIEWER, frozenset({"viewer"}), frozenset({Permission.ORDERS_READ}))
    else:
        frozen = who in ("frozen", "creator_frozen")
        grant = AccountGrant(cr.ACCOUNT, True, who != "view_only", frozen)
        grants = () if who == "ungranted" else (grant,)
        user = sr.USER if who in ("creator", "creator_frozen") else OTHER
        snap = PrincipalSnapshot(user, frozenset({"manager"}), _TRADE, grants)
    return TradingPrincipal(sr.SESSION, snap)


@dataclass
class Principals:
    """`SessionTradingPrincipalResolver`: the bearer names the principal; `fail`, a 503."""

    fail: bool = False

    async def resolve(self, request: Any) -> TradingPrincipal | None:
        if self.fail:
            raise StoreUnavailable
        who = request.headers.get("authorization", "").partition(" ")[2]
        return None if who == "nobody" else principal(who)


@dataclass
class Emitted:
    """The route's audit writer, step 2's `rbac.denied`; `fail`: one not started."""

    records: list[dict[str, Any]] = field(default_factory=list)
    fail: bool = False

    async def emit(self, action: str, **fields: Any) -> None:
        if self.fail:
            raise RuntimeError("the audit writer is not started")
        self.records.append({"action": action, **fields})


@dataclass
class Runtime:
    """`OmsRuntime` as the route reads it. `stopped` is the stop race, a stop begun after step 3
    read `ok`, met at `exits` or at `run`, each answering `OmsNotReady` as the runtime's do."""

    service: ex.OrderExits
    state: str = "ok"
    stopped: str | None = None
    tasks: list[asyncio.Task[Response]] = field(default_factory=list)
    route: SimpleNamespace = field(default_factory=lambda: SimpleNamespace(environment="demo"))

    @property
    def exits(self) -> ex.OrderExits:
        if self.stopped == "exits":
            raise OmsNotReady
        return self.service

    def run(self, coro: Coroutine[Any, Any, Response]) -> asyncio.Task[Response]:
        if self.stopped == "run":
            coro.close()
            raise OmsNotReady
        self.tasks.append(asyncio.get_running_loop().create_task(coro))
        return self.tasks[-1]


@dataclass
class World:
    """The router over the exit service `oms.service`, whose records land in `audits`."""

    oms: Runtime
    audits: cr.Audits
    since: int = 0  # the records written before the world was built
    principals: Principals | None = field(default_factory=Principals)
    composed: bool = True
    audit: Emitted = field(default_factory=Emitted)
    metrics: Metrics = field(default_factory=lambda: Metrics("demo"))
    cache: IdempotencyCache = field(default_factory=IdempotencyCache)
    pages: list[str] = field(default_factory=list)

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        self.pages.append(summary)

    def app(self) -> FastAPI:
        app = FastAPI()
        app.include_router(make_order_exits_router(
            self.principals, lambda: self.oms if self.composed else None, audit=self.audit,
            metrics=self.metrics, replays=self.cache, pager=self,
        ))  # fmt: skip
        app.add_middleware(CorrelationMiddleware)  # binds `request_id`, as `create_app` does
        return app

    def actions(self) -> list[tuple[str, str]]:
        """The records, the route's then the service's: (action, reason)."""
        written = [(r.action, r.reason) for r, _ in self.audits.written[self.since :]]
        return [(e["action"], e["reason"]) for e in self.audit.records] + written

    def steps(self) -> list[str | None]:
        """The 24 Sec.8.4 step each of the service's records names (`deny`'s `step`), else None."""
        return [r.detail.get("step") for r, _ in self.audits.written[self.since :]]

    def named(self) -> list[object]:
        """Whom and which request each of the service's records names: (actor, request id)."""
        return [
            (r.actor, r.request_id) if isinstance(r, RequestRecord) else r
            for r, _ in self.audits.written[self.since :]
        ]

    def refused(self, code: str) -> float:
        labels = {"env": "demo", "operation": "cancel", "code": code}
        return self.metrics.registry.get_sample_value("oms_exit_refused_total", labels) or 0.0


def world_of(service: ex.OrderExits, audits: cr.Audits) -> World:
    return World(Runtime(service), audits, since=len(audits.written))


async def scripted_world(
    held: str | None = "submitted", *settles: str | BaseException,
    answer: dict[str, Any] | None = _OK, stored: Any = "submitted", **over: Any,
) -> tuple[World, tx.Scripted, OrderRow, cr.Rig]:  # fmt: skip
    """The route over the exit service on S4-C's scripted facade (`over` replacing any of its
    dependencies): its order on `cr.ACCOUNT`, of the demo environment, in the Owners' scope alone
    (no person created it, ruling Q6)."""
    exits, machines, row, port = await tx.scripted(
        held, *settles, answer=answer, stored=stored, **over
    )
    InMemorySubmissionStore(port.store).seed_account(cr.ref())
    port.store.seed_owner(OWNER)
    port.store.seed_owner(SECOND)
    return world_of(exits, port.audits), machines, row, port


async def delete(
    world: World, order: object, who: str = "owner", key: object = KEY
) -> httpx.Response:
    headers = {"authorization": f"Bearer {who}", "x-correlation-id": str(TRACE)}
    if key is not None:
        headers["idempotency-key"] = str(key)
    transport = ASGITransport(app=world.app(), client=(PEER, 4321))
    async with AsyncClient(transport=transport, base_url="http://t") as c:
        return await c.delete(f"/orders/{order}", headers=headers)


def admitted(world: World, monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """The orders the route hands `cancel_admitted`, which checks no scope itself: only one
    `scope` returned may reach it (SEC-S4C2A-02)."""
    seen: list[UUID] = []
    real = world.oms.service.cancel_admitted

    async def spy(row: OrderRow, **kw: Any) -> ex.ExitOutcome:
        seen.append(row.id)
        return await real(row, **kw)

    monkeypatch.setattr(world.oms.service, "cancel_admitted", spy)
    return seen


class _Unread:
    """An order store whose every read fails as an outage."""

    def __getattr__(self, _name: str) -> Any:
        async def unread(*_args: Any, **_kwargs: Any) -> Any:
            raise StorageTierUnavailable("postgres unreachable (OSError)")

        return unread


def _claimed(*keys: UUID) -> Callable[[World], None]:
    def claim(world: World) -> None:
        for key in keys:
            claimed = world.oms.service.guard.claim(OWNER, "cancel", key)
            assert not isinstance(claimed, ex.ExitOutcome)

    return claim


def _recorded_elsewhere(world: World) -> None:
    held = StoredResponse("another request", 202, b"{}", None)
    world.cache.put(str(OWNER), f"cancelOrder:{KEY}", held)


async def lane_stopped(*args: Any, **kwargs: Any) -> Any:
    """An `OnLaneExits` hop once the order lane has stopped, or has not answered within its bound
    (L1b, `20-architecture.md` Sec.6.2): `OmsNotReady`, the exit service never reached."""
    raise OmsNotReady


_FULL = tuple(UUID(int=n) for n in range(1, ex.MAX_IN_FLIGHT_PER_PRINCIPAL + 1))
_DENIED = "orders.cancel"
#: The step a route refusal's record names (`deny`'s `step`, as `placeOrder`'s records do).
_STEP_OF = {"7_no_key": "key", "8_reuse": "replay", "9_in_flight": "guard", "9_full": "guard"}
#: Each step's refusal alone (24 Sec.8.4, the exit routes): (change, who, order, key) -> (status,
#: code, records). Nothing is commanded or run, and the refusal is counted once.
_STEPS: list[tuple[str, Any, str, str, UUID | None, int, str, list[tuple[str, str]]]] = [
    ("1_no_source", lambda w: setattr(w, "principals", None), "owner", "row", KEY, 501,
     "not_implemented", []),
    ("1_no_session", None, "nobody", "row", KEY, 401, "unauthenticated", []),
    ("1_unread", lambda w: setattr(w.principals, "fail", True), "owner", "row", KEY, 503,
     "store_unavailable", []),
    ("1_not_an_id", None, "owner", "not-a-uuid", KEY, 400, "validation_failed", []),
    ("2_permission", None, "viewer", "row", KEY, 403, "forbidden",
     [("rbac.denied", "missing_permission:orders:write:none")]),
    ("3_no_runtime", lambda w: setattr(w, "composed", False), "owner", "row", KEY, 501,
     "not_implemented", []),
    ("3_starting", lambda w: setattr(w.oms, "state", "starting"), "owner", "row", KEY, 503,
     "oms_not_ready", []),
    ("3_stopping", lambda w: setattr(w.oms, "stopped", "exits"), "owner", "row", KEY, 503,
     "oms_not_ready", []),
    ("4_missing", None, "owner", "missing", KEY, 404, "not_found", []),
    ("4_lane_stopped", lambda w: setattr(w.oms.service, "scope", lane_stopped), "owner", "row",
     KEY, 503, "oms_not_ready", []),
    ("7_no_key", None, "owner", "row", None, 400, "validation_failed",
     [(_DENIED, "validation_failed")]),
    ("8_reuse", _recorded_elsewhere, "owner", "row", KEY, 409, "idempotency_key_reuse",
     [(_DENIED, "idempotency_key_reuse")]),
    ("9_in_flight", _claimed(KEY), "owner", "row", KEY, 409, "idempotency_in_flight",
     [(_DENIED, "idempotency_in_flight")]),
    ("9_full", _claimed(*_FULL), "owner", "row", KEY, 429, "rate_limited",
     [(_DENIED, "rate_limited")]),
    ("9_stopping", lambda w: setattr(w.oms, "stopped", "run"), "owner", "row", KEY, 503,
     "oms_not_ready", []),
]  # fmt: skip
#: 22's members of a step's problem: its `retry_after_seconds`, `Retry-After` alike, where 22
#: gives one (`oms_not_ready`'s, the in-flight guard's), and the field of each `errors[]` entry.
_RETRY = {
    "3_starting": OMS_NOT_READY_RETRY_AFTER_S, "3_stopping": OMS_NOT_READY_RETRY_AFTER_S,
    "4_lane_stopped": OMS_NOT_READY_RETRY_AFTER_S,
    "9_in_flight": ex.IN_FLIGHT_RETRY_AFTER_S, "9_full": ex.IN_FLIGHT_RETRY_AFTER_S,
    "9_stopping": OMS_NOT_READY_RETRY_AFTER_S,
}  # fmt: skip
_FIELDS = {"1_not_an_id": ["orderId"], "7_no_key": ["Idempotency-Key"]}


@pytest.mark.parametrize("case", _STEPS, ids=[case[0] for case in _STEPS])
async def test_each_step_refuses_before_the_next_runs(case: Any) -> None:
    name, change, who, order, key, status, code, records = case
    world, machines, row, _ = await scripted_world("submitted", "cancelled")
    if change is not None:
        change(world)
    target = {"row": row.id, "missing": uuid4()}.get(order, order)
    with capture_logs() as logs:
        answer = await delete(world, target, who, key)
    body = answer.json()
    _PROBLEM.validate(body)
    assert (answer.status_code, body["code"], world.actions()) == (status, code, records)
    escaped = [line for line in logs if line["event"] == "oms_exit_refusal_escaped"]
    assert escaped == []  # each a refusal the route answers, none one that escaped the service
    assert world.steps() == ([_STEP_OF[name]] if name in _STEP_OF else [])
    assert (machines.sent, world.oms.tasks, world.refused(code)) == ([], [], 1)
    retry = _RETRY.get(name)
    assert (body.get("retry_after_seconds"), answer.headers.get("retry-after")) == (
        retry, None if retry is None else str(retry),
    )  # fmt: skip
    assert [error["field"] for error in body.get("errors", [])] == _FIELDS.get(name, [])
    if name == "9_stopping":  # the runtime refused the run: the claim is released
        assert callable(world.oms.service.guard.claim(OWNER, "cancel", KEY))


#: Two steps refusing at once, the runtime not ready (step 3): the earlier answers and is the one
#: counted, the later never runs (24 Sec.8.4, each before the next). (who, order) -> (status,
#: code, records, the later step's code).
_PAIRS: list[tuple[str, str, str, int, str, list[tuple[str, str]], str]] = [
    ("2_before_3", "viewer", "row", 403, "forbidden",
     [("rbac.denied", "missing_permission:orders:write:none")], "oms_not_ready"),
    ("3_before_4", "owner", "missing", 503, "oms_not_ready", [], "not_found"),
]  # fmt: skip


@pytest.mark.parametrize("case", _PAIRS, ids=[case[0] for case in _PAIRS])
async def test_of_two_refusing_steps_the_earlier_answers(case: Any) -> None:
    _, who, order, status, code, records, later = case
    world, machines, row, _ = await scripted_world()
    world.oms.state = "starting"
    answer = await delete(world, {"row": row.id, "missing": uuid4()}[order], who)
    assert (answer.status_code, answer.json()["code"], world.actions()) == (status, code, records)
    assert (world.refused(code), world.refused(later), machines.sent) == (1, 0, [])


def _no(code: str, **more: Any) -> dict[str, Any]:
    return {"ok": False, "error_code": code, **more}


_RATE, _VENUE = OmsErrorCode.RATE_BUDGET_EXCEEDED, OmsErrorCode.PRICE_OUT_OF_BOUNDS
_GONE = {"unknown": b01.ALREADY_TERMINAL, "exchange_ret_code": 110001}
_Q8 = ("unknown", "quarantined", "held", "untracked")
#: 22 `cancelOrder`'s answers (rulings Q8, Q9, Q11), as B1's scripted step leaves the order:
#: (held, its settles, the port's answer, stored) -> (status, lifecycle state or problem code,
#: `Retry-After`, B1 commanded).
_ANSWERS: list[tuple[str, Any, list[str], Any, str, int, str, str | None, bool]] = [
    ("cancelled", "submitted", ["cancelled"], _OK, "submitted", 202, "cancelled", None, True),
    ("unknown_transport", "submitted", ["unknown"], None, "submitted", 202, "unknown", None, True),
    ("unknown_110001", "submitted", ["unknown"], _GONE, "submitted", 202, "unknown", None, True),
    ("final", None, [], _OK, "cancelled", 202, "cancelled", None, False),
    ("cancel_pending", "cancel_pending", ["cancelled"], _OK, "submitted", 202, "cancelled", None,
     False),
    ("transitional", "validated", ["submitting", "submitted", "cancelled"], _OK, "submitted", 202,
     "cancelled", None, True),
    ("no_account", "submitted", ["submitted"], _no(oc.ACCOUNT_UNAVAILABLE), "submitted", 409,
     "account_unavailable", None, True),
    ("no_rate_token", "submitted", ["submitted"], _no(_RATE, retry_after_s=4), "submitted", 429,
     "exchange_rate_limited", "4", True),
    ("venue_refusal", "submitted", ["submitted"], _no(_VENUE, exchange_ret_code=110003),
     "submitted", 502, "exchange_error", None, True),
    ("unread", "submitted", ["submitted"], _no(oc.STORE_UNAVAILABLE), "submitted", 503,
     "store_unavailable", "1", True),
    ("recorded_stop", "submitted", ["submitted"], _no(b01.NATIVE_STOP_REQUIRED), "submitted",
     403, "risk_limit_breached", None, True),
    *[(f"q8_{s}", s, [], _OK, "submitted", 409, "conflict", None, False) for s in _Q8],
]  # fmt: skip


@pytest.mark.parametrize("case", _ANSWERS, ids=[case[0] for case in _ANSWERS])
async def test_each_answer_is_22s_from_the_exit_services_outcome(case: Any) -> None:
    _, held, settles, port_answer, stored, status, got, retry, commanded = case
    world, machines, row, _ = await scripted_world(
        held, *settles, answer=port_answer, stored=stored
    )
    answer = await delete(world, row.id)
    body = answer.json()
    assert (answer.status_code, answer.headers.get("retry-after")) == (status, retry)
    assert machines.sent == (["CANCEL"] if commanded else [])
    if status == 202:
        _ORDER.validate(body)
        assert (body["id"], body["lifecycle_state"]) == (str(row.id), got)
        assert body["state"] == ORDER_STATE_OF[got] and body["environment"] == "demo"
        return
    _PROBLEM.validate(body)
    assert (body["code"], world.refused(got)) == (got, 1)
    assert body.get("retry_after_seconds") == (None if retry is None else int(retry))
    # recorded by the service before it is answered, its own refusal naming no route step
    assert (world.actions()[-1], world.steps()[-1]) == ((_DENIED, got), None)
    assert body.get("exchange") == ({"ret_code": 110003} if status == 502 else None)


async def test_a_202_is_the_order_read_again_never_the_scopes_earlier_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """22 `cancelOrder`'s `202` renders the row the exit service read again once B1's step
    settled (`ExitOutcome.row`), never the one the scope read before the cancel: a part filled
    meanwhile shows in it."""
    world, _, row, port = await scripted_world("submitted", "cancelled")
    filled = replace(row, cum_exec_qty=Decimal("0.004"), avg_price=Decimal("59990"))

    async def read_again(account_id: UUID, order_id: UUID) -> OrderRow | None:
        return filled if (account_id, order_id) == (cr.ACCOUNT, row.id) else None

    monkeypatch.setattr(port.orders, "get", read_again)
    answer = await delete(world, row.id)
    assert answer.status_code == 202
    _ORDER.validate(answer.json())
    assert (answer.json()["filled_qty"], answer.json()["avg_fill_price"]) == ("0.004", "59990")


async def test_a_scope_that_cannot_be_read_is_503_unrecorded_and_counted() -> None:
    """SEC-S4C2A-03: an outage, not an actor's act: `503 store_unavailable` with `Retry-After: 1`
    (the shared retry), no record, and counted (Q14); nothing sent."""
    world, machines, row, _ = await scripted_world(orders=_Unread())
    answer = await delete(world, row.id)
    assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")
    assert answer.headers["retry-after"] == "1"
    assert (world.actions(), machines.sent, world.refused("store_unavailable")) == ([], [], 1)


@pytest.mark.parametrize("lands", [True, False], ids=["recorded", "unrecorded"])
async def test_a_viewer_is_403_its_record_naming_the_order_and_still_403_unrecorded(
    lands: bool,
) -> None:
    """Step 2: `orders:write`, audited `rbac.denied` naming the order asked for, the request, its
    session and its source address, a 403 even when that record cannot be written, and counted
    either way (24 Sec.8.4)."""
    world, _, row, _ = await scripted_world()
    world.audit.fail = not lands
    answer = await delete(world, row.id, "viewer")
    assert (answer.status_code, answer.json()["code"]) == (403, "forbidden")
    assert answer.json()["required_permissions"] == ["orders:write"]
    named = [
        (e["object_kind"], e["object_id"], e["request_id"], e["session_id"], e["actor_ip"])
        for e in world.audit.records
    ]
    assert named == ([("order", str(row.id), TRACE, sr.SESSION, PEER)] if lands else [])
    assert world.refused("forbidden") == 1


@pytest.mark.parametrize(
    ("change", "status", "records"),
    [
        (_claimed(KEY), 409, [(_DENIED, "idempotency_in_flight")]),
        (None, 202, [(_DENIED, "user"), (_DENIED, "cancelled")]),
    ],
    ids=["refused_at_the_guard", "cancelled"],
)
async def test_each_record_a_cancel_causes_names_its_principal_and_its_request(
    change: Callable[[World], None] | None, status: int, records: list[tuple[str, str]]
) -> None:
    """C-2.9, #3990: the route's own refusal (`deny`) and the cancel it hands the exit service
    (`cancel_admitted`), its intent and its outcome, each name the principal (user, role, session,
    address) and the request's `X-Correlation-Id`, which `test_audit_request_id_carried` (its
    `emit` and `enforce` calls) cannot see here."""
    world, _, row, _ = await scripted_world("submitted", "cancelled")
    if change is not None:
        change(world)
    assert (await delete(world, row.id)).status_code == status
    assert world.actions() == records
    assert world.named() == [(ACTOR, TRACE)] * len(records)


async def test_a_route_refusal_whose_record_cannot_land_is_503_audit_unavailable() -> None:
    world, _, row, port = await scripted_world()
    port.audits.refuse = RuntimeError("the audit WAL refused the record")
    answer = await delete(world, row.id, key=None)
    assert (answer.status_code, answer.json()["code"]) == (503, "audit_unavailable")
    assert (world.refused("audit_unavailable"), world.refused("validation_failed")) == (1, 0)


async def test_a_202_is_kept_24h_and_a_key_is_the_principals_for_this_order_only() -> None:
    """Steps 8 and 11: the first `202` is the repeat's answer, nothing sent again; the key on
    another order is `409 idempotency_key_reuse`, recorded; another principal's same key is a key
    never seen, answered as the order now stands."""
    world, machines, row, port = await scripted_world("submitted", "cancelled")
    first, again = await delete(world, row.id), await delete(world, row.id)
    assert (first.status_code, again.status_code) == (202, 202)
    assert again.json() == first.json() and again.headers["idempotency-replayed"] == "true"
    second = await port.stored(cr.new_order(seq=1), lifecycle="submitted")
    reused = await delete(world, second.id)
    assert (reused.status_code, reused.json()["code"]) == (409, "idempotency_key_reuse")
    assert world.actions()[-1] == (_DENIED, "idempotency_key_reuse")
    assert world.steps()[-1] == "replay"
    fresh = await delete(world, row.id, "second")
    assert fresh.status_code == 202 and "idempotency-replayed" not in fresh.headers
    assert fresh.json()["lifecycle_state"] == "cancelled" and machines.sent == ["CANCEL"]


async def test_a_refusal_is_not_kept_and_its_key_is_free_once_its_cancel_ended() -> None:
    """The 24 h record holds a `2xx` only: a cancel the venue refused may be asked again under
    its key, which the guard frees once that cancel's task ended (24 Sec.8.4 steps 8 and 9)."""
    refusal = _no(_VENUE, exchange_ret_code=110003)
    world, machines, row, _ = await scripted_world(
        "submitted", "submitted", "submitted", answer=refusal
    )
    first, again = await delete(world, row.id), await delete(world, row.id)
    assert (first.status_code, again.status_code) == (502, 502)
    assert "idempotency-replayed" not in again.headers and machines.sent == ["CANCEL", "CANCEL"]


async def test_a_client_that_leaves_does_not_stop_the_cancel_nor_free_its_key_early() -> None:
    """Step 11, shielded: the cancel B1 was commanded runs on as the runtime's task, its key held
    until it ends (a repeat meanwhile is in flight), and its `202` is kept for the repeat."""
    world, machines, row, _ = await scripted_world("submitted", "cancelled")
    machines.gate = asyncio.Event()
    headers = {"authorization": "Bearer owner", "idempotency-key": str(KEY)}
    async with AsyncClient(transport=ASGITransport(app=world.app()), base_url="http://t") as c:
        sent = asyncio.create_task(c.delete(f"/orders/{row.id}", headers=headers))
        entered = asyncio.ensure_future(machines.entered.wait())
        done, _ = await asyncio.wait({sent, entered}, return_when=asyncio.FIRST_COMPLETED)
        entered.cancel()
        assert done == {entered}  # commanded, B1's settle held, the request still waiting
        sent.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sent
    meanwhile = await delete(world, row.id)
    assert (meanwhile.status_code, meanwhile.json()["code"]) == (409, "idempotency_in_flight")
    assert world.steps()[-1] == "guard"
    machines.gate.set()
    (task,) = world.oms.tasks
    assert (await task).status_code == 202
    again = await delete(world, row.id)
    assert (again.status_code, again.headers["idempotency-replayed"]) == (202, "true")
    assert machines.sent == ["CANCEL"]


#: The redacted `500`'s members (22 `InternalError`): its code and title only.
_REDACTED = {"type", "title", "status", "code"}
_UNEXPECTED = "oms_exit_unexpected_failure"
#: Faults the exit service raises and no outcome answers, and the one page each is: a row that
#: pages (`oms.errors.PROBLEMS`) its own, any other the exit routes' (`exit_fault`).
_FAULTS = [
    (OrderMachinesFull("1024 order machines are live"), "oms_order_fault:OrderMachinesFull"),
    (OrderHistoryRefused("the order's events do not rebuild its row (OM-T03)"),
     f"{_UNEXPECTED}:OrderHistoryRefused"),
    (RuntimeError("a defect at the facade"), f"{_UNEXPECTED}:RuntimeError"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("error", "page"), _FAULTS, ids=["a-row-that-pages", "no-row", "no-oms-error"]
)
async def test_every_fault_the_exit_service_raises_is_a_500_paged_once(
    error: Exception, page: str
) -> None:
    """The orchestrator's ruling of 2026-10-25 02:50Z (2): a fault the exit service raises, which
    no outcome answers, is the redacted `500 internal_error` (22 `InternalError`), paged once by
    its class alone, never its text: a row that pages with its own page and no other, any other
    fault through the shared renderer's (`exit_fault`); counted once (ruling Q14). Its failure is
    recorded beside the cancel's intent, by its class (SEC-S4D2A-03)."""
    world, machines, row, _ = await scripted_world()
    machines.refuse = error
    answer = await delete(world, row.id)
    body = answer.json()
    _PROBLEM.validate(body)
    assert (answer.status_code, body["code"], set(body)) == (500, "internal_error", _REDACTED)
    assert world.pages == [page] and world.refused("internal_error") == 1
    assert str(error) not in answer.text and machines.sent == []
    assert world.actions() == [(_DENIED, "user"), (_DENIED, type(error).__name__)]


@pytest.mark.parametrize(
    "refusal",
    [GatewayOverloadedError("order:x", "order"), GatewayDegradedError("order:x", "order")],
    ids=["inbox-full", "degraded"],
)
async def test_a_cancel_the_gateway_refuses_is_503_with_retry_after_recorded_and_unpaged(
    refusal: GatewayError,
) -> None:
    """SEC-S4D2A-01 (the Fable lens at 38bfb62e): backpressure at the order's gateway, its inbox
    full or its admission refused, is no fault: `503 oms_not_ready` with its `Retry-After`, the
    refusal recorded beside the intent (C-2.9) and counted once (ruling Q14), no exit page (the
    gateway pages its own, C-2.18) and nothing sent."""
    world, machines, row, _ = await scripted_world()
    machines.refuse = refusal
    answer = await delete(world, row.id)
    body, retry = answer.json(), OMS_NOT_READY_RETRY_AFTER_S
    _PROBLEM.validate(body)
    assert (answer.status_code, body["code"], body.get("retry_after_seconds")) == (
        503, "oms_not_ready", retry,
    )  # fmt: skip
    assert answer.headers["retry-after"] == str(retry)
    assert (world.pages, machines.sent) == ([], [])
    assert world.actions() == [(_DENIED, "user"), (_DENIED, "oms_not_ready")]
    assert (world.refused("oms_not_ready"), world.refused("internal_error")) == (1, 0)


@pytest.mark.parametrize("where", ["scope", "cancel_admitted"], ids=["step-4", "step-11"])
async def test_a_cancel_that_meets_a_stopped_lane_is_the_counted_503_never_an_escaped_refusal(
    monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """24 Sec.8.4 over the order lane (L1b's handoff of 2026-10-25): `OmsNotReady` out of step 4's
    scope read or step 11's cancel, an `OnLaneExits` hop finding the lane stopped, is step 3's
    answer, unlike the gateway's backpressure above: `503 oms_not_ready` with its `Retry-After`,
    counted once, unaudited and unpaged, its key free and nothing kept or sent. It is never
    logged `oms_exit_refusal_escaped`, as no refusal escaped the exit service: nothing is logged
    at warning or above."""
    world, machines, row, _ = await scripted_world()
    monkeypatch.setattr(world.oms.service, where, lane_stopped)
    with capture_logs() as logs:
        answer = await delete(world, row.id)
    body = answer.json()
    _PROBLEM.validate(body)
    assert (answer.status_code, body["code"]) == (503, "oms_not_ready")
    assert answer.headers["retry-after"] == str(OMS_NOT_READY_RETRY_AFTER_S)
    assert (world.actions(), world.pages, machines.sent) == ([], [], [])
    assert world.refused("oms_not_ready") == 1
    assert world.cache.get(str(OWNER), f"cancelOrder:{KEY}") is None
    assert callable(world.oms.service.guard.claim(OWNER, "cancel", KEY))
    assert [line for line in logs if line["log_level"] in ("warning", "error", "critical")] == []


@pytest.mark.parametrize("fault", tx.GATEWAY_FAULTS)
async def test_a_gateway_refusal_that_is_no_backpressure_is_a_paged_500_with_its_failure(
    fault: type[GatewayError],
) -> None:
    """SEC-S4D2AX-01 (the Fable delta at 896c1ebe): only the gateway's backpressure, above, is
    `503 oms_not_ready`. Any other `GatewayError` (an unknown machine, a send off its loop, a
    system event) is a programming fault: the redacted `500 internal_error`, paged once by its
    class (`exit_fault`) and counted once, its one `failure` recorded beside the intent by its
    class alone, never `denied`, and nothing sent."""
    world, machines, row, _ = await scripted_world()
    error = fault("a defect naming the machine 'order:x'")
    machines.refuse = error
    answer = await delete(world, row.id)
    body, name = answer.json(), fault.__name__
    _PROBLEM.validate(body)
    assert (answer.status_code, body["code"], set(body)) == (500, "internal_error", _REDACTED)
    assert (world.pages, machines.sent) == ([f"{_UNEXPECTED}:{name}"], [])
    assert (world.refused("internal_error"), world.refused("oms_not_ready")) == (1, 0)
    records = [r for r, _ in world.audits.written[world.since :] if isinstance(r, RequestRecord)]
    assert [(r.outcome, r.reason) for r in records] == [("success", "user"), ("failure", name)]
    assert str(error) not in answer.text + repr(records)


async def test_a_second_fault_of_a_class_pages_the_same_page_again() -> None:
    """One page for the class: a second fault of the class, whatever its text, pages the same page,
    which the pager's alerting folds into the one it holds (`LogPager` keeps none itself); each
    `500` is counted."""
    world, machines, row, _ = await scripted_world()
    machines.refuse = RuntimeError("one defect")
    first = await delete(world, row.id)
    machines.refuse = RuntimeError("another defect")
    again = await delete(world, row.id, key=uuid4())
    assert (first.status_code, again.status_code) == (500, 500)
    assert world.pages == [f"{_UNEXPECTED}:RuntimeError"] * 2
    assert world.refused("internal_error") == 2


async def test_a_fault_once_the_client_left_is_still_answered_and_paged_in_its_task() -> None:
    """Step 11 runs shielded, as the runtime's task: a fault B1's settle raises once the client
    left is answered and paged in that task, with no request awaiting it, and counted."""
    world, machines, row, _ = await scripted_world("submitted", RuntimeError("a defect"))
    machines.gate = asyncio.Event()
    headers = {"authorization": "Bearer owner", "idempotency-key": str(KEY)}
    async with AsyncClient(transport=ASGITransport(app=world.app()), base_url="http://t") as c:
        sent = asyncio.create_task(c.delete(f"/orders/{row.id}", headers=headers))
        entered = asyncio.ensure_future(machines.entered.wait())
        done, _ = await asyncio.wait({sent, entered}, return_when=asyncio.FIRST_COMPLETED)
        entered.cancel()
        assert done == {entered}  # commanded, B1's settle held, the request still waiting
        sent.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sent
    machines.gate.set()
    (task,) = world.oms.tasks
    answer = await task
    assert answer.status_code == 500 and machines.sent == ["CANCEL"]
    assert world.pages == [f"{_UNEXPECTED}:RuntimeError"]
    assert world.refused("internal_error") == 1


async def test_a_fault_of_step_4s_scoped_read_is_a_500_paged_nothing_recorded_or_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Step 4: a fault the exit service's scoped read raises, no outage (that is `503
    store_unavailable`, unrecorded), is the paged `500`, counted, nothing recorded or sent."""
    world, machines, row, port = await scripted_world()

    async def faulty(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("a defect in the scoped read")

    monkeypatch.setattr(port.orders, "get_in_scope", faulty)
    answer = await delete(world, row.id)
    assert (answer.status_code, answer.json()["code"]) == (500, "internal_error")
    assert world.pages == [f"{_UNEXPECTED}:RuntimeError"]
    assert (world.refused("internal_error"), world.actions(), machines.sent) == (1, [], [])


# --- over the real B1 facade, command port and fake venue -----------------------------------------


@pytest.fixture
async def rig() -> AsyncIterator[SubmitRig]:
    async with sr.rigged() as built:
        built.store.seed_owner(OWNER)
        yield built


def granted(rig: SubmitRig, who: str) -> World:
    """The route over the rig's exit service, `who`'s grant on `cr.ACCOUNT` held by the store."""
    if who in ("creator", "other", "view_only", "frozen"):
        user = sr.USER if who == "creator" else OTHER
        rig.store.seed_access(user, cr.ACCOUNT, trade=who != "view_only", frozen=who == "frozen")
    return world_of(tx.exits_of(rig), rig.port.audits)


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
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch, who: str, status: int, code: str | None,
    denied: str | None,
) -> None:  # fmt: skip
    """A Manager cancels only the orders it created (04 Sec.7.2.2 rows 12, 13); a view-only grant
    is 403 (Q7); an ungranted or frozen account's order is 404 (SR-E29-13), each refusal recorded
    `rbac.denied` once, by the service; a refused order never reaches `cancel_admitted`, and
    nothing is sent."""
    row = await tx.placed(rig)
    world = granted(rig, who)
    seen = admitted(world, monkeypatch)
    answer = await delete(world, row.id, who)
    sent = rig.calls().count("cancel_order")
    assert answer.status_code == status
    assert seen == ([row.id] if code is None else [])
    if code is None:
        _ORDER.validate(answer.json())
        assert (answer.json()["lifecycle_state"], sent) == ("cancelled", 1)
        assert world.actions() == [(_DENIED, "user"), (_DENIED, "cancelled")]
        return
    assert (answer.json()["code"], sent, world.refused(code)) == (code, 0, 1)
    assert world.actions() == [("rbac.denied", denied)]


async def test_a_foreign_order_is_answered_as_a_missing_id_only_the_real_one_recorded(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SR-E29-13 and Q12: a frozen or ungranted account's order and an id no order holds get one
    `404`, body and headers alike; only the real orders' are recorded `rbac.denied`, and none
    reaches `cancel_admitted` (SEC-S4C2A-02)."""
    row = await tx.placed(rig)
    world = granted(rig, "frozen")
    seen = admitted(world, monkeypatch)
    asked = [(uuid4(), "frozen"), (row.id, "frozen"), (row.id, "ungranted")]
    answers = [await delete(world, order, who) for order, who in asked]
    shapes = [(a.status_code, a.json(), dict(a.headers)) for a in answers]
    assert shapes[0][0] == 404 and shapes[0] == shapes[1] == shapes[2]
    assert world.actions() == [("rbac.denied", ex.NOT_GRANTED)] * 2
    assert (seen, rig.calls().count("cancel_order")) == ([], 0)


async def test_a_kept_202_is_withheld_from_its_principal_once_its_access_is_lost(
    rig: SubmitRig,
) -> None:
    """24 Sec.8.4, SR-E29-13: the 24 h record is read after the scope, so a Manager whose grant
    was frozen since its cancel reads no outcome back under its key, only the `404` any order
    outside its scope gets, recorded; the record still holds the `202`, the repeat's answer once
    the grant is live again, nothing sent twice."""
    row = await tx.placed(rig)
    world = granted(rig, "creator")
    first = await delete(world, row.id, "creator")
    assert first.status_code == 202
    rig.store.seed_access(sr.USER, cr.ACCOUNT, trade=True, frozen=True)  # the store's grant
    lost = await delete(world, row.id, "creator_frozen")  # and the session's snapshot
    assert (lost.status_code, lost.json()["code"]) == (404, "not_found")
    assert "idempotency-replayed" not in lost.headers
    rig.store.seed_access(sr.USER, cr.ACCOUNT, trade=True)  # live again
    again = await delete(world, row.id, "creator")
    assert (again.status_code, again.headers["idempotency-replayed"]) == (202, "true")
    assert again.content == first.content and rig.calls().count("cancel_order") == 1
    cancelled = [(_DENIED, "user"), (_DENIED, "cancelled")]
    assert world.actions() == [*cancelled, ("rbac.denied", ex.NOT_GRANTED)]


async def test_a_202_names_the_orders_trade_group_and_leg(rig: SubmitRig) -> None:
    """22 `Order`: the `202` carries the group the scope read the order in, and its leg."""
    row = await tx.placed(rig)
    scoped = await rig.port.orders.get_in_scope(OwnerScope(OWNER), row.id, environment="demo")
    assert isinstance(scoped, ScopedOrder)
    assert None not in (scoped.trade_group_id, row.trade_group_leg_id)
    answer = await delete(granted(rig, "owner"), row.id)
    assert answer.status_code == 202
    group, leg = answer.json()["trade_group_id"], answer.json()["trade_group_leg_id"]
    assert (group, leg) == (str(scoped.trade_group_id), str(row.trade_group_leg_id))


@pytest.mark.parametrize(
    ("who", "position", "status", "code"),
    [
        ("owner", True, 403, "risk_limit_breached"),
        ("owner", False, 202, None),
        ("other", False, 403, "forbidden"),
    ],
    ids=["position-open", "position-flat", "no-person-created-it"],
)
async def test_native_sl_a_recorded_stops_cancel_is_refused_while_its_position_is_open(
    rig: SubmitRig, who: str, position: bool, status: int, code: str | None
) -> None:
    """C-2.6, ruling Q9: the command port reads the position and refuses, nothing cancelled, the
    stop kept live; a flat position lets the orphaned row go. No person created it, so a Manager
    is refused (Q6): the Owner's alone."""
    stop = NewOrder(
        id=uuid4(), exchange_account_id=cr.ACCOUNT, order_link_id=ext_key(tx.STOP_ID),
        symbol=cr.SYMBOL, side="Sell", intent="stop_loss", order_type="Market",
        qty=Decimal("0.010"), trigger_price=Decimal("58000"), reduce_only=True,
        close_on_trigger=True, tpsl_mode="Partial", exchange_order_id=tx.STOP_ID,
        provenance="recorded_stop", state="accepted", lifecycle_state="submitted",
    )  # fmt: skip
    await rig.machines.materialise(stop, environment="demo")
    held = cr.exchange_order(stop, exchange_order_id=tx.STOP_ID)
    rig.port.demo.seed_order(held, uid=cr.UIDS["demo"])  # the venue holds the stop
    if position:
        rig.port.demo.seed_position(cr.position())
    answer = await delete(granted(rig, who), stop.id, who)
    sent = rig.calls().count("cancel_order")
    assert answer.status_code == status
    if code is None:
        assert (answer.json()["lifecycle_state"], sent) == ("cancelled", 1)
        return
    assert (answer.json()["code"], sent) == (code, 0)
    assert (rig.machines.state(stop.id) or ("",))[0] == "submitted"  # INV-B1-j: kept live


async def test_a_cancel_meets_no_switch_and_no_flag(rig: SubmitRig) -> None:
    """C-2.6, 22 `cancelOrder`: live trading, B18 and the order-entry gate refusing, and
    `trading.oms_enabled` off, the cancel still goes out; the route has no arm token step."""
    row = await tx.placed(rig)
    rig.port.switches.refusals[cr.ACCOUNT] = TradingDisabled()
    world = world_of(tx.exits_of(rig, oms_enabled=lambda: False), rig.port.audits)
    answer = await delete(world, row.id)
    assert (answer.status_code, answer.json()["lifecycle_state"]) == (202, "cancelled")
    assert rig.calls().count("cancel_order") == 1


# --- the app -------------------------------------------------------------------------------------


_CANCEL_ALL = "candleviewer.api.order_cancel_all"


def _order_routers(routes: Any, found: list[str]) -> list[str]:
    """The modules serving `/orders` routes, in the order `create_app()` mounted them."""
    for route in routes:
        inner = getattr(route, "original_router", None)  # FastAPI 0.141's include wrapper
        if inner is not None:
            _order_routers(inner.routes, found)
        elif str(getattr(route, "path", "")).startswith("/orders"):
            if route.endpoint.__module__ not in found:
                found.append(route.endpoint.__module__)
    return found


def test_the_order_routers_mount_in_their_ruled_order() -> None:
    """The orchestrator's ruling of 2026-10-24 19:43Z: `create_app()` mounts the exit routes'
    `DELETE /orders/{orderId}` after `placeOrder`'s router and after cancel-all's own router
    (S4-E's `api/order_cancel_all.py`, included between the two) wherever that is mounted."""
    mounted = _order_routers(create_app().routes, [])
    exits = mounted.index("candleviewer.api.order_exits")
    ahead = [m for m in mounted if m in ("candleviewer.api.orders", _CANCEL_ALL)]
    assert "candleviewer.api.orders" in ahead
    assert all(mounted.index(module) < exits for module in ahead)
