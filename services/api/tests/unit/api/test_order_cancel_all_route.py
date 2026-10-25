"""`POST /orders/cancel-all` (E29-T04 #913 slice 4, S4-E; 24 Sec.8.4 "The exit routes", 22
`cancelAllOrders`; the orchestrator's rulings of 2026-10-24 19:43Z and 20:08Z), on fakes: the
router on a bare app, so each step is driven alone. The runtime's in-flight guard is the real
`InFlightGuard` and its cancel-all service the real `CancelAll`, over a recording exit service and
order store; the exit service settles the scope with the store's own `settle_accounts` over the
accounts each principal may trade, so the cross-account cases drive the scope into the call
(SEC-S4C2A-02). Answers are validated against 22. The include order runs the real app."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Collection, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, fields
from decimal import Decimal
from typing import Any, Final
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import Response
from httpx import ASGITransport, AsyncClient
from jsonschema import Draft202012Validator
from prometheus_client import generate_latest

from candleviewer.api import order_cancel_all
from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.idempotency import IdempotencyCache, StoredResponse
from candleviewer.api.order_cancel_all import CANCEL_ALL_PATH, make_cancel_all_router
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.app import create_app
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.observability.correlation import CorrelationMiddleware
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.cancel_all import (
    CancelAll,
    CancelAllOutcome,
    CancelAllRequest,
    ScopedAccounts,
)
from candleviewer.oms.errors import AccountScopeDenied, OmsNotReady, StoreUnavailable
from candleviewer.oms.exits import ExitOutcome, InFlightGuard
from candleviewer.oms.ports import RequestRecord, SubmitActor
from candleviewer.oms.submit import STORE_TIMEOUT_S
from candleviewer.storage.repositories.accounts import AccountScope, GrantScope, OwnerScope
from candleviewer.storage.repositories.orders import (
    AccountsOutOfScope,
    OrderRow,
    settle_accounts,
)
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode
from tests.unit.api.test_order_acceptance import ACCOUNT, USER, schema
from tests.unit.api.test_orders_route import (
    FOREIGN,
    KEY,
    MANAGER,
    SESSION,
    TRACE,
    Audit,
    Pager,
    Principals,
    authz_denied,
)

OTHER_KEY = UUID("6c1f0e2d-3b4a-4c5d-8e6f-7a8b9c0d1e2f")
MISSING = UUID("a1000000-0000-4000-8000-0000000000ee")  # no such account
NO_GRANT = UUID("4b000000-0000-4000-8000-000000000004")  # a Manager granted no account
VIEW_ONLY = UUID("4b000000-0000-4000-8000-000000000005")  # a Manager who may only view ACCOUNT
FROZEN = UUID("4b000000-0000-4000-8000-000000000006")  # a Manager whose ACCOUNT grant is frozen
_RESULT = Draft202012Validator(
    schema("BulkAccountResult"), format_checker=Draft202012Validator.FORMAT_CHECKER
)
#: A first `200` the 24 h record holds for the key under another body's fingerprint.
_OTHER_BODY = StoredResponse("0" * 64, 200, b"{}", None)


def _row(n: int, account: UUID = ACCOUNT, **over: Any) -> OrderRow:
    values: dict[str, Any] = {f.name: None for f in fields(OrderRow)}
    values |= {
        "id": UUID(int=n), "exchange_account_id": account, "symbol": "BTCUSDT",
        "intent": "entry", "reduce_only": False, "provenance": "placed", "state": "accepted",
        "lifecycle_state": "submitted", "qty": Decimal("0.010"), "order_link_id": f"cv-{n}",
    }  # fmt: skip
    return OrderRow(**(values | over))


def _refused(code: str, status: int = 409, ret_code: int | None = None) -> ExitOutcome:
    return ExitOutcome(kind="refused", status=status, code=code, exchange_ret_code=ret_code)


_CANCELLED = ExitOutcome(kind="accepted", status=202, lifecycle_state="cancelled")


@dataclass
class Store:
    """The order store's open-order read, each call recorded."""

    rows: list[OrderRow] = field(default_factory=lambda: [_row(1), _row(2, FOREIGN)])
    listed: list[UUID] = field(default_factory=list)

    async def list_open(
        self, account_id: UUID, *, symbol: str | None = None
    ) -> tuple[OrderRow, ...]:
        self.listed.append(account_id)
        return tuple(
            row for row in self.rows
            if row.exchange_account_id == account_id and symbol in (None, row.symbol)
        )  # fmt: skip


@dataclass
class Exits:
    """The exit service as cancel-all drives it: the real guard; the scope settled by the store's
    own `settle_accounts` over the accounts the principal may trade (an Owner's: every one, a
    Manager's: those of its scope its own rows in `grants` may trade, as the store's SQL reads
    them); each cancel recorded and answered `cancelled` unless `outcomes` says otherwise, after
    `hold` when one is set."""

    guard: InFlightGuard = field(default_factory=InFlightGuard)
    accounts: tuple[UUID, ...] = (ACCOUNT, FOREIGN)
    #: Each user's grant rows as the store holds them. Its predicate is `can_view`, `can_trade`,
    #: not `frozen` (S4-C's SQL, pinned on Postgres by `store_reads_contract.py`'s view-only and
    #: frozen cases). FROZEN's row here may trade, so only its own `account_scope`, which drops a
    #: frozen grant, refuses it; VIEW_ONLY's may not, so the store refuses it.
    grants: dict[UUID, tuple[AccountGrant, ...]] = field(
        default_factory=lambda: {
            MANAGER: (AccountGrant(ACCOUNT, True, True, False),),
            VIEW_ONLY: (AccountGrant(ACCOUNT, True, False, False),),
            FROZEN: (AccountGrant(ACCOUNT, True, True, False),),
        }
    )
    scope_down: bool = False
    outcomes: dict[UUID, ExitOutcome] = field(default_factory=dict)
    hold: asyncio.Event | None = None
    scoped: list[tuple[AccountScope, tuple[UUID, ...]]] = field(default_factory=list)
    cancelled: list[tuple[UUID, SubmitActor, str, UUID | None]] = field(default_factory=list)

    async def accounts_in_scope(
        self, scope: AccountScope, requested: Collection[UUID]
    ) -> tuple[UUID, ...]:
        self.scoped.append((scope, tuple(requested)))
        if self.scope_down:
            raise StoreUnavailable
        if isinstance(scope, OwnerScope):
            reach = list(self.accounts)
        else:  # the grants the principal may view, of them the ones its rows may trade
            rows = self.grants.get(scope.user_id, ())
            trades = {g.exchange_account_id for g in rows if g.can_view and g.can_trade}
            mine = (trades - {g.exchange_account_id for g in rows if g.frozen}) & scope.account_ids
            reach = [account for account in self.accounts if account in mine]
        try:
            return settle_accounts(reach, requested)
        except AccountsOutOfScope:
            raise AccountScopeDenied from None

    async def cancel_admitted(
        self, row: OrderRow, *, actor: SubmitActor, reason: str, request_id: UUID | None
    ) -> ExitOutcome:
        self.cancelled.append((row.id, actor, reason, request_id))
        if self.hold is not None:
            await self.hold.wait()
        return self.outcomes.get(row.id, _CANCELLED)


@dataclass
class Runtime:
    """`OmsRuntime` as the route reads it: no `route`, no switches, no flag (C-2.6). `stopped`
    makes `run` refuse, as the runtime does once its stop has begun; `broken` makes the service's
    run raise; `lane_lost` makes it refuse, as the lane's bridge does once the lane has stopped
    after the scope answered."""

    state: str = "ok"
    store: Store = field(default_factory=Store)
    exits: Exits = field(default_factory=Exits)
    tasks: list[asyncio.Task[Response]] = field(default_factory=list)
    stopped: bool = False
    broken: bool = False
    lane_lost: bool = False
    gone: bool = False

    @property
    def cancel_all(self) -> Any:
        if self.gone:  # its stop began after step 3 read `ok`
            raise OmsNotReady
        if self.broken:
            return _Broken(CancelAll(self.store, self.exits))
        if self.lane_lost:
            return _LaneLost(CancelAll(self.store, self.exits))
        return CancelAll(self.store, self.exits)

    def run(self, coro: Coroutine[Any, Any, Response]) -> asyncio.Task[Response]:
        if self.stopped:
            coro.close()
            raise OmsNotReady
        self.tasks.append(asyncio.get_running_loop().create_task(coro))
        return self.tasks[-1]


@dataclass
class _Broken:
    """A service whose scope answers and whose run raises: a defect, never an outcome."""

    real: CancelAll

    async def scope(self, scope: AccountScope, request: CancelAllRequest) -> ScopedAccounts:
        return await self.real.scope(scope, request)

    async def run(self, *args: Any, **kwargs: Any) -> CancelAllOutcome:
        raise ExceptionGroup("a worker broke", [ValueError("a defect")])  # as a TaskGroup fails


@dataclass
class _LaneLost:
    """A service whose scope answers and whose run finds the lane stopped: `OnLaneCancelAll`'s
    `run` once the lane has stopped between its scope's answer and the run's hop."""

    real: CancelAll

    async def scope(self, scope: AccountScope, request: CancelAllRequest) -> ScopedAccounts:
        return await self.real.scope(scope, request)

    async def run(self, *args: Any, **kwargs: Any) -> CancelAllOutcome:
        raise OmsNotReady


def _principals() -> Principals:
    """`test_orders_route`'s principals, and Managers who may write orders but hold no grant, a
    view-only grant or a frozen one on ACCOUNT, each its own user with its own rows in the store's
    `Exits.grants` (the security look's Low 3)."""
    principals = Principals()
    trade = frozenset({Permission.ORDERS_WRITE, Permission.ORDERS_READ})
    managers = {
        "no_grant": PrincipalSnapshot(NO_GRANT, frozenset({"manager"}), trade),
        "view_only_grant": PrincipalSnapshot(
            VIEW_ONLY, frozenset({"manager"}), trade, (AccountGrant(ACCOUNT, True, False, False),)
        ),
        "frozen_grant": PrincipalSnapshot(
            FROZEN, frozenset({"manager"}), trade, (AccountGrant(ACCOUNT, True, True, True),)
        ),
    }
    for token, snapshot in managers.items():
        principals.tokens[token] = TradingPrincipal(SESSION, snapshot)
    return principals


@dataclass
class World:
    principals: Principals | None = field(default_factory=_principals)
    runtime: Runtime | None = field(default_factory=Runtime)
    audit: Audit = field(default_factory=Audit)
    metrics: Metrics = field(default_factory=lambda: Metrics("demo"))
    cache: IdempotencyCache = field(default_factory=IdempotencyCache)
    pager: Pager = field(default_factory=Pager)

    @property
    def oms(self) -> Runtime:
        assert self.runtime is not None
        return self.runtime

    def app(self) -> FastAPI:
        app = FastAPI()
        router = make_cancel_all_router(
            self.principals, lambda: self.runtime, audit=self.audit, records=self.audit,
            metrics=self.metrics, replays=self.cache, pager=self.pager,
        )  # fmt: skip
        app.include_router(router)
        app.add_middleware(CorrelationMiddleware)
        return app

    def refused(self, code: str) -> float:
        line = f'oms_exit_refused_total{{code="{code}",env="demo",operation="cancel_all"}}'
        text = generate_latest(self.metrics.registry).decode()
        found = [float(r.rsplit(" ", 1)[1]) for r in text.splitlines() if r.startswith(line)]
        return found[0] if found else 0

    def records(self) -> list[RequestRecord]:
        return [r for r in self.audit.written if r.action == "orders.cancel"]


@asynccontextmanager
async def client(world: World) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=world.app()), base_url="http://t") as c:
        yield c


def _args(
    who: str, body: object, key: object, extra: dict[str, str] | None = None
) -> dict[str, Any]:
    headers = {"authorization": f"Bearer {who}"} | (extra or {})
    if key is not None:
        headers["idempotency-key"] = str(key)
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return {"content": raw, "headers": headers}


async def post(
    world: World, who: str = "owner", body: object = None, key: object = KEY,
    extra: dict[str, str] | None = None,
) -> httpx.Response:  # fmt: skip
    async with client(world) as c:
        args = _args(who, {} if body is None else body, key, extra)
        return await c.post(CANCEL_ALL_PATH, **args)


_TRACED: Final = {"x-correlation-id": str(TRACE)}


def _listed(*ids: UUID) -> dict[str, Any]:
    return {"exchange_account_ids": [str(i) for i in ids]}


#: Each refusal before the scope, alone: what it answers and what it records; nothing is read or
#: sent, and each is counted (ruling Q14).
_BEFORE_SCOPE: list[tuple[str, Any, str, object, int, str, str | None]] = [
    ("1_no_source", lambda w: setattr(w, "principals", None), "owner", None, 501,
     "not_implemented", None),
    ("1_no_session", None, "nobody", None, 401, "unauthenticated", None),
    ("1_unread", lambda w: setattr(w.principals, "fail", True), "owner", None, 503,
     "store_unavailable", None),
    ("2_permission", None, "viewer", None, 403, "forbidden", "rbac.denied"),
    ("3_no_runtime", lambda w: setattr(w, "runtime", None), "owner", None, 501,
     "not_implemented", None),
    ("3_starting", lambda w: setattr(w.oms, "state", "starting"), "owner", None, 503,
     "oms_not_ready", None),
    ("4_not_an_object", None, "owner", b"[1]", 400, "validation_failed", None),
    ("4_not_json", None, "owner", b"{", 400, "validation_failed", None),
    ("4_unknown_field", None, "owner", {"accounts": []}, 400, "validation_failed", None),
    ("4_bad_id", None, "owner", {"exchange_account_ids": ["nope"]}, 400, "validation_failed",
     None),
    ("4_unknown_intent", None, "owner", {"intents": ["hedge"]}, 400, "validation_failed", None),
    ("4_bad_symbol", None, "owner", {"symbol": "btc"}, 400, "validation_failed", None),
    ("4_constant", None, "owner", b'{"exclude_reduce_only": NaN}', 400, "validation_failed",
     None),
    ("4_over_cap", None, "owner", b"{" + b" " * 17_000 + b"}", 400, "validation_failed", None),
    ("4_scope_unread", lambda w: setattr(w.oms.exits, "scope_down", True), "owner", None, 503,
     "store_unavailable", None),
]  # fmt: skip


@pytest.mark.parametrize(
    ("change", "who", "body", "status", "code", "action"),
    [case[1:] for case in _BEFORE_SCOPE],
    ids=[case[0] for case in _BEFORE_SCOPE],
)
async def test_each_step_before_the_scope_refuses_before_the_next_runs(
    change: Any, who: str, body: object, status: int, code: str, action: str | None
) -> None:
    world = World()
    if change is not None:
        change(world)
    answer = await post(world, who, body)
    assert (answer.status_code, answer.json()["code"]) == (status, code)
    assert world.audit.actions() == ([] if action is None else [action])
    assert world.refused(code) == 1
    if world.runtime is not None:
        assert (world.oms.store.listed, world.oms.exits.cancelled, world.oms.tasks) == ([], [], [])


async def test_a_body_refused_before_the_scope_answers_whatever_ids_it_names() -> None:
    """A malformed body is a 400 even when it names an account the caller may not trade: the
    scope is never asked, so it is no oracle (24 Sec.8.4 step 4)."""
    world = World()
    body = _listed(FOREIGN) | {"intents": ["hedge"]}
    answer = await post(world, "manager", body)
    assert (answer.status_code, answer.json()["code"]) == (400, "validation_failed")
    assert world.oms.exits.scoped == [] and world.audit.actions() == []


@pytest.mark.parametrize(
    ("who", "ids"),
    [
        ("manager", (ACCOUNT, FOREIGN)),  # one foreign id refuses the whole request
        ("manager", (FOREIGN,)),
        ("owner", (ACCOUNT, MISSING)),  # one that does not exist, alike
        ("no_grant", (ACCOUNT,)),  # a Manager with no grant at all
        ("view_only_grant", (ACCOUNT,)),  # one who may view the account but not trade it
        ("frozen_grant", (ACCOUNT,)),  # one whose grant is frozen
    ],
    ids=["foreign_among_granted", "foreign_alone", "missing", "no_grant", "view_only", "frozen"],
)
async def test_a_listed_account_out_of_scope_refuses_the_whole_request(
    who: str, ids: tuple[UUID, ...]
) -> None:
    world, before = World(), authz_denied()
    answer = await post(world, who, _listed(*ids))
    assert (answer.status_code, answer.json()["code"]) == (403, "account_scope_denied")
    assert (world.oms.store.listed, world.oms.exits.cancelled, world.oms.tasks) == ([], [], [])
    [denied] = world.audit.emitted  # one record for the request, naming what it listed
    assert (denied["action"], denied["reason"]) == (
        "rbac.denied", "account_not_granted:orders:write:granted_accounts",
    )  # fmt: skip
    assert denied["after_state"] == {
        "operation": "cancel_all", "exchange_account_ids": [str(i) for i in ids],
    }  # fmt: skip
    who_id = {
        "manager": MANAGER, "owner": USER, "no_grant": NO_GRANT, "view_only_grant": VIEW_ONLY,
        "frozen_grant": FROZEN,
    }[who]  # fmt: skip
    assert (denied["actor_user_id"], denied["session_id"]) == (who_id, SESSION)
    assert world.records() == [] and authz_denied() == before + 1
    assert world.refused("account_scope_denied") == 1


async def test_a_view_only_grant_is_refused_by_the_stores_trade_predicate() -> None:
    """Its scope keeps the view-only grant (`account_scope` drops only a frozen one): the store's
    `can_trade` refuses it. The same request from a row that may trade is admitted."""
    world = World()
    answer = await post(world, "view_only_grant", _listed(ACCOUNT))
    assert answer.status_code == 403
    assert world.oms.exits.scoped[0][0] == GrantScope(VIEW_ONLY, frozenset({ACCOUNT}))
    world = World()
    world.oms.exits.grants[VIEW_ONLY] = (AccountGrant(ACCOUNT, True, True, False),)
    assert (await post(world, "view_only_grant", _listed(ACCOUNT))).status_code == 200


async def test_a_frozen_grant_is_refused_by_the_principals_own_scope() -> None:
    """The store's row here may trade: the refusal is `account_scope` dropping the frozen grant
    before the store is asked, so the scope it reads holds no account."""
    world = World()
    answer = await post(world, "frozen_grant", _listed(ACCOUNT))
    assert answer.status_code == 403
    assert world.oms.exits.scoped == [(GrantScope(FROZEN, frozenset()), (ACCOUNT,))]


async def test_the_scope_refusal_stands_when_its_record_cannot_be_written() -> None:
    world = World()
    world.audit.fail = True
    answer = await post(world, "manager", _listed(FOREIGN))
    assert (answer.status_code, answer.json()["code"]) == (403, "account_scope_denied")


async def test_the_permission_refusal_stands_when_its_record_cannot_be_written() -> None:
    world = World()
    world.audit.fail = True
    answer = await post(world, "viewer")
    assert (answer.status_code, answer.json()["code"]) == (403, "forbidden")
    assert world.refused("forbidden") == 1


def _held(world: World) -> None:
    """A first request of `KEY` still running: the guard holds the owner's key."""
    claim = world.oms.exits.guard.claim(USER, "cancel_all", KEY)
    assert not isinstance(claim, ExitOutcome)


def _full(world: World) -> None:
    world.oms.exits.guard = InFlightGuard(max_keys=1, max_per_principal=1)
    claim = world.oms.exits.guard.claim(USER, "cancel_all", OTHER_KEY)
    assert not isinstance(claim, ExitOutcome)


def _stored(world: World) -> None:
    """The key's first `200`, for another body: a reuse."""
    world.cache.put(str(USER), f"cancelAllOrders:{KEY}", _OTHER_BODY)


#: Each refusal after the scope, alone: its answer, its `Retry-After`, the step its records name.
_AFTER_SCOPE: list[tuple[str, Any, object, int, str, str | None, str]] = [
    ("7_no_key", None, None, 400, "validation_failed", None, "key"),
    ("7_bad_key", None, "not-a-uuid", 400, "validation_failed", None, "key"),
    ("8_reuse", _stored, KEY, 409, "idempotency_key_reuse", None, "replay"),
    ("9_in_flight", _held, KEY, 409, "idempotency_in_flight", "1", "guard"),
    ("9_full", _full, KEY, 429, "rate_limited", "1", "guard"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("change", "key", "status", "code", "retry", "step"),
    [case[1:] for case in _AFTER_SCOPE],
    ids=[case[0] for case in _AFTER_SCOPE],
)
async def test_each_refusal_after_the_scope_is_recorded_per_account_before_it_is_answered(
    change: Any, key: object, status: int, code: str, retry: str | None, step: str
) -> None:
    """The 19:43Z ruling: one `orders.cancel` denied per account in scope, object
    `exchange_account`, reason the code, detail `{operation, code, step}` (20:08Z's names)."""
    world = World()
    if change is not None:
        change(world)
    answer = await post(world, "owner", {}, key)
    assert (answer.status_code, answer.json()["code"]) == (status, code)
    assert answer.headers.get("retry-after") == retry
    assert answer.json().get("retry_after_seconds") == (None if retry is None else int(retry))
    records = world.records()
    assert [(r.account_id, r.object_kind, r.object_id) for r in records] == [
        (ACCOUNT, "exchange_account", ACCOUNT), (FOREIGN, "exchange_account", FOREIGN),
    ]  # fmt: skip
    for record in records:
        assert (record.outcome, record.severity, record.reason) == ("denied", "warning", code)
        assert record.detail == {"operation": "cancel_all", "code": code, "step": step}
        assert record.actor.user_id == USER and record.actor.session_id == SESSION
    assert (world.oms.store.listed, world.oms.exits.cancelled, world.oms.tasks) == ([], [], [])
    assert world.refused(code) == 1


async def test_the_scope_is_settled_before_the_key_is_read() -> None:
    """24 Sec.8.4: step 4 refuses a foreign id before step 7 looks at the key, so a request with
    neither is the scope's 403, recorded `rbac.denied`, never the key's 400."""
    world = World()
    answer = await post(world, "manager", _listed(FOREIGN), None)
    assert (answer.status_code, answer.json()["code"]) == (403, "account_scope_denied")
    assert world.audit.actions() == ["rbac.denied"]


async def test_a_refusal_after_the_scope_names_only_the_accounts_in_scope() -> None:
    """A Manager's empty list is its trade grants: the record names ACCOUNT, never FOREIGN."""
    world = World()
    answer = await post(world, "manager", {}, None)
    assert answer.status_code == 400
    assert [r.account_id for r in world.records()] == [ACCOUNT]


async def test_a_refusal_whose_record_does_not_land_is_503_and_sends_nothing() -> None:
    world = World()
    world.audit.fail = True
    answer = await post(world, "owner", {}, None)
    assert (answer.status_code, answer.json()["code"]) == (503, "audit_unavailable")
    assert (world.oms.exits.cancelled, world.oms.tasks) == ([], [])
    assert world.refused("audit_unavailable") == 1 and world.refused("validation_failed") == 0


async def test_a_scope_of_no_account_answers_its_refusal_with_no_record() -> None:
    world = World()
    answer = await post(world, "no_grant", {}, None)
    assert answer.status_code == 400 and world.audit.actions() == []


async def test_the_owners_empty_list_cancels_every_accounts_selected_orders() -> None:
    world = World()
    answer = await post(world, "owner", {})
    assert answer.status_code == 200
    body = answer.json()
    _RESULT.validate(body)
    assert body == {
        "results": [
            {"exchange_account_id": str(ACCOUNT), "ok": True, "affected": 1, "error": None},
            {"exchange_account_id": str(FOREIGN), "ok": True, "affected": 1, "error": None},
        ],
        "requested": 2, "succeeded": 2,
    }  # fmt: skip
    cancelled = world.oms.exits.cancelled
    assert [(c[0], c[2]) for c in cancelled] == [
        (UUID(int=1), "cancel_all"), (UUID(int=2), "cancel_all"),
    ]  # fmt: skip
    assert {c[1].user_id for c in cancelled} == {USER} and len(world.oms.tasks) == 1


async def test_a_managers_empty_list_never_reaches_an_account_outside_its_trade_grants() -> None:
    """SEC-S4C2A-02: the scope is driven into the call, so FOREIGN's order is never read or sent
    a cancel, though the store holds it."""
    world = World()
    answer = await post(world, "manager", {})
    assert answer.status_code == 200
    assert [r["exchange_account_id"] for r in answer.json()["results"]] == [str(ACCOUNT)]
    assert world.oms.store.listed == [ACCOUNT]
    assert [c[0] for c in world.oms.exits.cancelled] == [UUID(int=1)]


async def test_a_caller_with_no_trade_grant_naming_none_gets_200_with_no_results() -> None:
    world = World()
    answer = await post(world, "no_grant", {})
    assert (answer.status_code, answer.json()) == (
        200, {"results": [], "requested": 0, "succeeded": 0},
    )  # fmt: skip


@pytest.mark.parametrize(
    ("body", "cancelled"),
    [
        ({}, [1, 3]),  # every symbol and intent; reduce-only left out by default
        ({"symbol": "ETHUSDT"}, [3]),
        ({"intents": ["take_profit"]}, []),  # the TP is reduce-only, left out
        ({"intents": ["take_profit"], "exclude_reduce_only": False}, [5]),
        ({"exclude_reduce_only": False}, [1, 3, 4, 5]),
    ],
    ids=["defaults", "symbol", "intent", "intent_with_reduce_only", "reduce_only"],
)
async def test_the_body_reaches_the_selection_as_it_was_sent(
    body: dict[str, Any], cancelled: list[int]
) -> None:
    world = World()
    world.oms.store.rows = [
        _row(1), _row(3, symbol="ETHUSDT"), _row(4, reduce_only=True),
        _row(5, intent="take_profit", reduce_only=True),
    ]  # fmt: skip
    answer = await post(world, "owner", _listed(ACCOUNT) | body)
    assert answer.status_code == 200
    assert [c[0] for c in world.oms.exits.cancelled] == [UUID(int=n) for n in cancelled]
    assert world.oms.store.listed == [ACCOUNT]


async def test_an_accounts_error_carries_the_oms_text_for_its_code_never_the_exchanges() -> None:
    world = World()
    world.oms.exits.outcomes[UUID(int=2)] = _refused("exchange_error", 502, ret_code=110017)
    answer = await post(world, "owner", {})
    body = answer.json()
    _RESULT.validate(body)
    assert body["results"][1] == {
        "exchange_account_id": str(FOREIGN), "ok": False, "affected": 0,
        "error": {
            "code": "exchange_error", "message": ERROR_META[ErrorCode("exchange_error")].title,
            "exchange_ret_code": 110017, "retryable": False,
        },
    }  # fmt: skip
    assert (body["requested"], body["succeeded"]) == (2, 1)


@pytest.mark.parametrize(
    "code",
    [
        "store_unavailable", "exchange_unavailable", "timeout", "conflict", "account_unavailable",
        "exchange_error", "exchange_rate_limited", "risk_limit_breached", "audit_unavailable",
        "oms_not_ready",
    ],
)  # fmt: skip
def test_every_code_an_account_reports_has_the_oms_own_text(code: str) -> None:
    """The service's own codes and the exit service's cancel refusals (S4-C, the 17:42Z ruling)."""
    assert ERROR_META[ErrorCode(code)].title.strip()


async def test_the_200_is_kept_for_24_h_and_a_repeat_replays_it_sending_nothing() -> None:
    world = World()
    first = await post(world, "owner", {})
    again = await post(world, "owner", {})
    assert (again.status_code, again.content) == (200, first.content)
    assert again.headers["idempotency-replayed"] == "true"
    assert len(world.oms.exits.cancelled) == 2 and len(world.oms.tasks) == 1


async def test_a_new_key_runs_the_cancels_again() -> None:
    world = World()
    await post(world, "owner", {})
    await post(world, "owner", {}, OTHER_KEY)
    assert len(world.oms.exits.cancelled) == 4


async def test_a_client_that_leaves_midway_still_gets_its_cancels_and_their_record() -> None:
    """Step 11 is shielded: the task runs on, keeps its `200` for 24 h and only then releases
    the key."""
    world = World()
    world.oms.exits.hold = asyncio.Event()
    request = asyncio.create_task(post(world, "owner", {}))
    for _ in range(50):
        await asyncio.sleep(0)
        if world.oms.tasks:
            break
    request.cancel()
    with pytest.raises(asyncio.CancelledError):
        await request
    [task] = world.oms.tasks
    assert not task.done()
    assert isinstance(world.oms.exits.guard.claim(USER, "cancel_all", KEY), ExitOutcome)
    world.oms.exits.hold.set()
    assert (await task).status_code == 200
    assert world.cache.get(str(USER), f"cancelAllOrders:{KEY}") is not None
    claim = world.oms.exits.guard.claim(USER, "cancel_all", KEY)
    assert not isinstance(claim, ExitOutcome)  # released with the task's end


async def test_a_stop_begun_after_step_3_answers_not_ready_and_frees_the_key() -> None:
    world = World()
    world.oms.stopped = True
    answer = await post(world, "owner", {})
    assert (answer.status_code, answer.json()["code"]) == (503, "oms_not_ready")
    assert not isinstance(world.oms.exits.guard.claim(USER, "cancel_all", KEY), ExitOutcome)
    assert world.records() == [] and world.refused("oms_not_ready") == 1


async def test_a_run_that_raises_answers_500_pages_and_keeps_nothing() -> None:
    world = World()
    world.oms.broken = True
    answer = await post(world, "owner", {})
    assert (answer.status_code, answer.json()["code"]) == (500, "internal_error")
    assert world.pager.pages == ["orders_cancel_all_failed"]
    assert world.cache.get(str(USER), f"cancelAllOrders:{KEY}") is None
    assert world.refused("internal_error") == 1


async def test_a_lane_stopped_after_the_scope_answers_not_ready_unpaged_and_frees_the_key() -> None:
    """The run's hop finds the lane stopped after the scope answered: the counted `503` D1b's
    route answers for it, never the paged `500`, with nothing sent, recorded or kept."""
    world = World()
    world.oms.lane_lost = True
    answer = await post(world, "owner", {})
    assert (answer.status_code, answer.json()["code"]) == (503, "oms_not_ready")
    assert answer.headers.get("retry-after") == "5"
    assert (world.pager.pages, world.records(), world.oms.exits.cancelled) == ([], [], [])
    assert world.cache.get(str(USER), f"cancelAllOrders:{KEY}") is None
    assert (world.refused("oms_not_ready"), world.refused("internal_error")) == (1, 0)
    assert not isinstance(world.oms.exits.guard.claim(USER, "cancel_all", KEY), ExitOutcome)


async def test_cancel_all_reads_no_arm_token_switch_or_flag() -> None:
    """C-2.6: the runtime here has no `route` (arm records, switches) and the router takes no
    flag, so a cancel-all that read any of them would fail; a live-shaped request cancels."""
    world = World()
    assert not hasattr(world.oms, "route")
    answer = await post(world, "owner", {})
    assert answer.status_code == 200


def test_the_app_serves_cancel_all() -> None:
    """`create_app()` mounts the route; that it mounts ahead of the exit routes' router (the 19:43Z
    ruling) is `test_order_exits_route.py::test_the_order_routers_mount_in_their_ruled_order`."""
    assert ("POST", CANCEL_ALL_PATH) in served_operations(create_app())


# --- the code look's findings (M1, M2, m1, m4, m5): the records' correlation, the real -----------
# --- fingerprint, 22's limits, the audit writer's own failures and the answer's rendering --------


async def test_each_refusal_record_names_its_request_and_its_actor() -> None:
    """C-2.9: the actor, role, address, session and correlation id of every record (M1)."""
    world = World()
    await post(world, "owner", {}, None, _TRACED)
    for record in world.records():
        assert record.request_id == TRACE
        assert (record.actor.user_id, record.actor.role) == (USER, "owner")
        assert (record.actor.ip, record.actor.session_id) == ("127.0.0.1", SESSION)


async def test_the_scope_refusal_record_names_its_request_and_its_actor() -> None:
    world = World()
    await post(world, "manager", _listed(FOREIGN), KEY, _TRACED)
    [denied] = world.audit.emitted
    assert (denied["request_id"], denied["actor_ip"]) == (TRACE, "127.0.0.1")
    assert (denied["outcome"], denied["severity"]) == ("denied", "warning")


async def test_the_permission_refusal_record_names_its_request() -> None:
    world = World()
    await post(world, "viewer", {}, KEY, _TRACED)
    [denied] = world.audit.emitted
    assert (denied["request_id"], denied["actor_ip"]) == (TRACE, "127.0.0.1")
    assert denied["session_id"] == SESSION


async def test_each_cancel_carries_its_request_and_its_actor() -> None:
    world = World()
    await post(world, "owner", {}, KEY, _TRACED)
    assert [request_id for *_, request_id in world.oms.exits.cancelled] == [TRACE, TRACE]
    assert {
        (actor.role, actor.ip, actor.session_id) for _, actor, _, _ in world.oms.exits.cancelled
    } == {("owner", "127.0.0.1", SESSION)}


async def test_a_key_reused_for_another_body_is_409_and_sends_nothing_again() -> None:
    """24 Sec.8.4 step 8 on the real fingerprint: the stored `200` never answers another body
    (M2)."""
    world = World()
    first = await post(world, "owner", {}, KEY)
    again = await post(world, "owner", _listed(ACCOUNT), KEY)
    assert first.status_code == 200
    assert (again.status_code, again.json()["code"]) == (409, "idempotency_key_reuse")
    assert len(world.oms.exits.cancelled) == 2  # the first request's two, nothing more
    assert [r.detail["step"] for r in world.records()] == ["replay"]


@pytest.mark.parametrize(
    ("body", "rule"),
    [
        (_listed(ACCOUNT, ACCOUNT), "non_unique_items"),  # 22's `uniqueItems`
        ({"exchange_account_ids": [str(UUID(int=n)) for n in range(101)]}, "too_long"),
    ],
    ids=["repeated", "over_100"],
)
async def test_a_list_the_contract_refuses_is_400_before_the_scope(
    body: dict[str, Any], rule: str
) -> None:
    world = World()
    answer = await post(world, "owner", body)
    assert (answer.status_code, answer.json()["code"]) == (400, "validation_failed")
    assert [e["rule"] for e in answer.json()["errors"]] == [rule]
    assert world.oms.exits.scoped == [] and world.audit.actions() == []


class _BrokenAudit(Audit):
    """The audit writer refusing as the real one does (`AuditError`) while `refusing` is set;
    `after` lets that many writes land first."""

    def __init__(self, after: int = 0) -> None:
        super().__init__()
        self.after, self.refusing = after, True

    async def emit(self, action: str, **fields: Any) -> None:
        if self.refusing:
            raise AuditError("the audit writer refused")
        await super().emit(action, **fields)

    async def write(self, record: Any) -> None:
        if self.refusing and len(self.written) >= self.after:
            raise AuditError("the audit writer refused")
        await super().write(record)


@pytest.mark.parametrize(
    ("who", "body", "status", "code"),
    [
        ("viewer", {}, 403, "forbidden"),  # step 2's record
        ("manager", _listed(FOREIGN), 403, "account_scope_denied"),  # step 4's
    ],
    ids=["step_2", "step_4"],
)
async def test_a_403_stands_when_the_audit_writer_refuses_its_record(
    who: str, body: dict[str, Any], status: int, code: str
) -> None:
    world = World(audit=_BrokenAudit())
    answer = await post(world, who, body)
    assert (answer.status_code, answer.json()["code"]) == (status, code)


async def test_a_refusal_whose_later_record_does_not_land_is_503_and_sends_nothing() -> None:
    """The first account's record landed, the second's did not: the refusal is not answered as
    such, and nothing is sent (C-2.9)."""
    world = World(audit=_BrokenAudit(after=1))
    answer = await post(world, "owner", {}, None)
    assert (answer.status_code, answer.json()["code"]) == (503, "audit_unavailable")
    assert [r.account_id for r in world.records()] == [ACCOUNT]
    assert (world.oms.exits.cancelled, world.oms.tasks) == ([], [])


async def test_a_stop_begun_before_the_service_is_read_is_not_ready() -> None:
    world = World()
    world.oms.gone = True
    answer = await post(world, "owner", {})
    assert (answer.status_code, answer.json()["code"]) == (503, "oms_not_ready")
    assert world.refused("oms_not_ready") == 1


async def test_a_scope_that_cannot_be_read_answers_the_shared_retry() -> None:
    """The exits' one `Retry-After` for a store outage (the 11:34Z ruling), nothing recorded."""
    world = World()
    world.oms.exits.scope_down = True
    answer = await post(world, "owner", {})
    assert (answer.status_code, answer.headers.get("retry-after")) == (503, "1")
    assert answer.json()["retry_after_seconds"] == 1 and world.audit.actions() == []


async def test_a_retryable_account_error_says_so() -> None:
    world = World()
    world.oms.exits.outcomes[UUID(int=2)] = _refused("store_unavailable", 503)
    body = (await post(world, "owner", {})).json()
    assert body["results"][1]["error"]["retryable"] is True


async def test_a_code_the_registry_lacks_gets_the_oms_fixed_text() -> None:
    """Never the exchange's text, whatever code an account reports (SR-E29-09)."""
    world = World()
    world.oms.exits.outcomes[UUID(int=2)] = _refused("not_a_registered_code")
    body = (await post(world, "owner", {})).json()
    _RESULT.validate(body)
    error = body["results"][1]["error"]
    assert error == {
        "code": "not_a_registered_code",
        "message": "The account's selected orders were not all cancelled.",
        "exchange_ret_code": None, "retryable": False,
    }  # fmt: skip


class _Bounds:
    """`asyncio` as the route module sees it, counting the timeouts it opens."""

    def __init__(self) -> None:
        self.opened: list[float | None] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)

    def timeout(self, delay: float | None) -> asyncio.Timeout:
        self.opened.append(delay)
        return asyncio.timeout(delay)


class _HangingAudit(Audit):
    """An audit writer whose writes never land."""

    async def write(self, record: Any) -> None:
        await asyncio.Event().wait()


async def test_all_of_a_refusals_records_share_one_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """One `STORE_TIMEOUT_S` for every account's record, not one each (the code look's Nit 8)."""
    bounds = _Bounds()
    monkeypatch.setattr(order_cancel_all, "asyncio", bounds)
    world = World()
    answer = await post(world, "owner", {}, None)  # step 7: one record per account in scope
    assert answer.status_code == 400 and len(world.records()) == 2
    assert bounds.opened == [STORE_TIMEOUT_S]


async def test_a_refusal_whose_record_hangs_is_503_once_its_bound_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The security look's Low 4: a store that never answers holds no request past the bound."""
    monkeypatch.setattr(order_cancel_all, "STORE_TIMEOUT_S", 0.01)
    world = World(audit=_HangingAudit())
    async with asyncio.timeout(5):  # without a bound this fails here, never hangs the suite
        answer = await post(world, "owner", {}, None)
    assert (answer.status_code, answer.json()["code"]) == (503, "audit_unavailable")
    assert (world.oms.exits.cancelled, world.oms.tasks) == ([], [])


@pytest.mark.parametrize("fault", ["render", "keep"])
async def test_a_fault_answering_or_keeping_the_200_is_the_paged_500(
    fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The security look's Low 5: the guard covers the `200`'s rendering and its 24 h record, so a
    defect there is the paged 500; each cancel already sent stays with B1."""

    def broken(*args: Any) -> Any:
        raise ValueError("a defect")

    world = World()
    if fault == "render":
        monkeypatch.setattr(order_cancel_all, "_result", broken)
    else:
        monkeypatch.setattr(world.cache, "put", broken)
    answer = await post(world, "owner", {})
    assert (answer.status_code, answer.json()["code"]) == (500, "internal_error")
    assert world.pager.pages == ["orders_cancel_all_failed"]
    assert len(world.oms.exits.cancelled) == 2
