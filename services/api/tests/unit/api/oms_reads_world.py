"""A world for the OMS read routes (E29-T07 #915, PR 1), on fakes: the real router and the real
`OmsReads` over an in-memory store that answers as the SQL does (`oms_reads_sqlalchemy`): the
scope settles the named accounts all or nothing (the store's own `settle_accounts`), an Owner
views every account of the process's environment, a grant only its own, and nothing of another
environment is ever read. Postgres proves the SQL itself (`tests/integration/storage/
test_oms_reads_pg.py`). A support module: pytest collects nothing from it."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Final

from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from candleviewer.api.oms_reads import make_oms_reads_router
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.app import _refuse_target_as_actor
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.auth.view_as import ViewAsPhase, ViewAsRequestContext, bound_view_as
from candleviewer.oms.errors import StoreUnavailable
from candleviewer.oms.reads import OmsReads
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.accounts import AccountScope, GrantScope
from candleviewer.storage.repositories.executions import ExecutionRow
from candleviewer.storage.repositories.oms_reads import (
    CLOSING_EXEC_TYPES,
    MAX_ORDER_EXECUTIONS,
    ExecutionQuery,
    Keyset,
    ListedExecution,
    ListedOrder,
    OrderDetail,
    OrderQuery,
    PositionOutOfScope,
    PositionQuery,
)
from candleviewer.storage.repositories.orders import (
    MAX_EVENT_PAGE,
    OrderEventRow,
    OrderRow,
    OutOfScope,
    ScopedOrder,
    settle_accounts,
)
from candleviewer.storage.repositories.positions import PositionRow

T0: Final = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
NOW: Final = T0 + timedelta(hours=1)
#: A (granted to the Manager and the Viewer), B (foreign), both demo; LIVE (another environment).
ACCOUNT_A: Final = uuid.UUID("a1000000-0000-4000-8000-00000000000a")
ACCOUNT_B: Final = uuid.UUID("a1000000-0000-4000-8000-00000000000b")
ACCOUNT_LIVE: Final = uuid.UUID("a1000000-0000-4000-8000-00000000000c")
MISSING: Final = uuid.UUID("0a000000-0000-4000-8000-0000000000ff")
ENVIRONMENT: Final = {ACCOUNT_A: "demo", ACCOUNT_B: "demo", ACCOUNT_LIVE: "live"}
GROUP_A: Final = uuid.UUID("0c000000-0000-4000-8000-00000000000a")
GROUP_B: Final = uuid.UUID("0c000000-0000-4000-8000-00000000000b")
SESSION: Final = uuid.UUID("5e551011-0000-4000-8000-000000000915")
USERS: Final = {
    who: uuid.uuid5(uuid.NAMESPACE_URL, f"cv-915/{who}")
    for who in ("owner", "manager", "viewer", "bare")
}
_MANAGER: Final = frozenset(
    {Permission.ORDERS_READ, Permission.POSITIONS_READ, Permission.EXECUTIONS_READ}
)


def snapshot(who: str) -> PrincipalSnapshot:
    """The Owner; a Manager and a Viewer granted A (22 `x-permissions`); `bare` holds nothing."""
    if who == "owner":
        return PrincipalSnapshot(USERS[who], frozenset({"owner"}), frozenset(Permission))
    if who == "bare":
        return PrincipalSnapshot(USERS[who], frozenset({"manager"}), frozenset())
    grant = AccountGrant(ACCOUNT_A, True, who == "manager", False)
    return PrincipalSnapshot(USERS[who], frozenset({who}), _MANAGER, (grant,))


class Principals:
    """`SessionTradingPrincipalResolver`: a principal per bearer token; `fail`: its store's 503."""

    def __init__(self) -> None:
        self.tokens = {who: TradingPrincipal(SESSION, snapshot(who)) for who in USERS}
        self.fail = False

    async def resolve(self, request: Any) -> TradingPrincipal | None:
        if self.fail:
            raise StoreUnavailable
        return self.tokens.get(request.headers.get("authorization", "").partition(" ")[2])


@dataclass
class Audit:
    """The audit writer behind the app's own tripwire (`_refuse_target_as_actor`, #3085 S8), as
    `_LazyAuditEmitter` puts it before every write: a record naming a view-as target as its
    actor is refused (`TargetNamedAsActor`), never recorded."""

    emitted: list[dict[str, Any]] = field(default_factory=list)
    fail: bool = False

    async def emit(self, action: str, **fields: Any) -> None:
        _refuse_target_as_actor(action, fields)
        if self.fail:
            raise RuntimeError("the audit writer is not started")
        self.emitted.append({"action": action, **fields})

    def actions(self) -> list[str]:
        return [record["action"] for record in self.emitted]


def order(n: int, account: uuid.UUID, **over: Any) -> OrderRow:
    values: dict[str, Any] = {f.name: None for f in fields(OrderRow)}
    values |= {
        "id": uuid.UUID(int=0x0A00 + n), "exchange_account_id": account, "symbol": "BTCUSDT",
        "side": "Buy", "intent": "entry", "order_type": "Limit", "qty": Decimal("0.500"),
        "price": Decimal("63100.00"), "time_in_force": "GTC", "reduce_only": False,
        "close_on_trigger": False, "position_idx": 0, "state": "accepted",
        "lifecycle_state": "submitted", "cum_exec_qty": Decimal("0.200"),
        "cum_exec_value": Decimal("12619.96"), "avg_price": Decimal("63099.80"),
        "leaves_qty": Decimal("0.300"), "fee_paid": Decimal(0), "tpsl_mode": "Full",
        "stop_loss": Decimal("62900.00"), "submit_attempts": 1, "idempotency_state": "acked",
        "created_ts": T0 + timedelta(minutes=n), "is_paper": False, "provenance": "placed",
        "order_link_id": f"cvl-0MduI3fiqJ6h0wkltsuR4T-Jel{n % 10}-00en",
    }  # fmt: skip
    return OrderRow(**(values | over))


def fill(n: int, account: uuid.UUID, order_id: uuid.UUID | None, **over: Any) -> ExecutionRow:
    values: dict[str, Any] = {
        "id": uuid.UUID(int=0x0E00 + n), "exchange_account_id": account, "exec_id": f"E{n}",
        "order_id": order_id, "symbol": "BTCUSDT", "side": "Buy",
        "exec_qty": Decimal("0.200"), "exec_price": Decimal("63099.80"),
        "exec_value": Decimal("12619.96"), "exec_type": "Trade", "is_maker": False,
        "exec_ts": T0 + timedelta(minutes=n), "exec_fee": Decimal("6.941"),
        "fee_rate": Decimal("0.00055"), "recv_ts": T0 + timedelta(minutes=n),
    }  # fmt: skip
    return ExecutionRow(**(values | over))


def position(n: int, account: uuid.UUID, **over: Any) -> PositionRow:
    values: dict[str, Any] = {
        "id": uuid.UUID(int=0x0D00 + n), "exchange_account_id": account, "symbol": "BTCUSDT",
        "side": "Buy", "size": Decimal("0.200"), "avg_price": Decimal("63000"),
        "mark_price": Decimal("63118.90"), "position_value": Decimal("12623.78"),
        "leverage": Decimal("10.00"), "unrealised_pnl": Decimal("3.82"),
        "stop_loss": Decimal("62900"), "tpsl_mode": "Full", "recv_ts": T0, "updated_at": T0,
    }  # fmt: skip
    return PositionRow(**(values | over))


def event(n: int, order_id: uuid.UUID, payload: dict[str, object], **over: Any) -> OrderEventRow:
    values: dict[str, Any] = {
        "id": n, "order_id": order_id, "order_link_id": "x", "seq": n, "kind": "ack",
        "from_state": None, "to_state": None, "source": "rest", "payload": payload,
        "ret_code": None, "ret_msg": None, "latency_ms": None,
        "event_ts": T0 + timedelta(seconds=n), "recv_ts": T0,
    }  # fmt: skip
    return OrderEventRow(**(values | over))


#: The exchange adapter's record of one create, as the store keeps it.
RECORD: Final[dict[str, object]] = {
    "transport": "rest", "method": "POST", "endpoint": "/v5/order/create", "ret_code": 0,
    "ret_msg": "OK", "latency_ms": 12,
    "request_redacted": {
        "category": "linear", "symbol": "BTCUSDT", "side": "buy", "order_type": "limit",
        "qty": "0.500", "price": "63100.00", "stop_loss": "62900.00",
        "order_link_id": "cvl-0MduI3fiqJ6h0wkltsuR4T-Jel1-00en",
    },
    "response_redacted": {"exchange_order_id": "8a1f0f9c-3d2e-4b11-9f77-1b2c3d4e5f60"},
}  # fmt: skip


@dataclass
class Store:
    """`OmsReadStore` in memory (module docstring); `fail` raises the store's own failure."""

    orders: list[tuple[OrderRow, uuid.UUID | None]] = field(default_factory=list)
    fills: list[tuple[ExecutionRow, uuid.UUID | None]] = field(default_factory=list)
    positions: list[PositionRow] = field(default_factory=list)
    events: dict[uuid.UUID, list[OrderEventRow]] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    fail: bool = False

    def _reach(
        self, scope: AccountScope, env: str, requested: Iterable[uuid.UUID]
    ) -> set[uuid.UUID]:
        self.calls.append("settle")
        if self.fail:
            raise StorageQueryFailed("57014")
        live = sorted(a for a, e in ENVIRONMENT.items() if e == env)
        if isinstance(scope, GrantScope):
            live = [a for a in live if a in scope.account_ids]
        return set(settle_accounts(live, tuple(requested)))

    def _viewable(self, scope: AccountScope, env: str, account: uuid.UUID) -> bool:
        if self.fail:
            raise StorageQueryFailed("57014")
        granted = not isinstance(scope, GrantScope) or account in scope.account_ids
        return ENVIRONMENT.get(account) == env and granted

    @staticmethod
    def _page[T](rows: list[tuple[Keyset, T]], after: Keyset | None, limit: int) -> tuple[T, ...]:
        rows.sort(key=lambda r: (r[0].at, r[0].id), reverse=True)
        kept = [r for k, r in rows if after is None or (k.at, k.id) < (after.at, after.id)]
        return tuple(kept[:limit])

    async def orders_(
        self, scope: AccountScope, query: OrderQuery, *, environment: str, after: Keyset | None,
        limit: int,
    ) -> tuple[ListedOrder, ...]:  # fmt: skip
        reach = self._reach(scope, environment, query.accounts)
        states = query.wanted_states()
        rows = [
            (Keyset(o.created_ts, o.id), ListedOrder(o, g)) for o, g in self.orders
            if o.exchange_account_id in reach
            and (states is None or o.state in states)
            and (not query.intents or o.intent in query.intents)
            and query.symbol in (None, o.symbol)
            and query.trade_group_id in (None, g)
            and (query.since is None or o.created_ts >= query.since)
            and (query.until is None or o.created_ts < query.until)
        ]  # fmt: skip
        return self._page(rows, after, limit)

    async def order(
        self, scope: AccountScope, order_id: uuid.UUID, *, environment: str, events: bool
    ) -> OrderDetail | OutOfScope:
        self.calls.append("order")
        if self.fail:
            raise StorageQueryFailed("57014")
        for row, group in self.orders:
            if row.id != order_id:
                continue
            if not self._viewable(scope, environment, row.exchange_account_id):
                return OutOfScope(row.exchange_account_id)
            found = ScopedOrder(row, group, None, None, True)
            chain = tuple(self.events.get(order_id, ())) if events else ()
            fills = tuple(ListedExecution(x, g) for x, g in self.fills if x.order_id == order_id)
            more = len(chain) > MAX_EVENT_PAGE
            more_fills = len(fills) > MAX_ORDER_EXECUTIONS
            return OrderDetail(
                found, chain[:MAX_EVENT_PAGE], fills[:MAX_ORDER_EXECUTIONS], more, more_fills
            )
        return OutOfScope(None)

    async def _fills(
        self, scope: AccountScope, query: ExecutionQuery, environment: str,
        after: Keyset | None, limit: int, closed: bool,
    ) -> tuple[ListedExecution, ...]:  # fmt: skip
        reach = self._reach(scope, environment, query.accounts)
        rows = [
            (Keyset(x.exec_ts, x.id), ListedExecution(x, g)) for x, g in self.fills
            if x.exchange_account_id in reach
            and (not closed or (x.closed_pnl is not None and x.exec_type in CLOSING_EXEC_TYPES))
            and query.symbol in (None, x.symbol)
            and query.order_id in (None, x.order_id)
            and query.trade_group_id in (None, g)
            and (query.since is None or x.exec_ts >= query.since)
            and (query.until is None or x.exec_ts < query.until)
        ]  # fmt: skip
        return self._page(rows, after, limit)

    async def executions(
        self, scope: AccountScope, query: ExecutionQuery, *, environment: str,
        after: Keyset | None, limit: int,
    ) -> tuple[ListedExecution, ...]:  # fmt: skip
        return await self._fills(scope, query, environment, after, limit, closed=False)

    async def closed_pnl(
        self, scope: AccountScope, query: ExecutionQuery, *, environment: str,
        after: Keyset | None, limit: int,
    ) -> tuple[ListedExecution, ...]:  # fmt: skip
        return await self._fills(scope, query, environment, after, limit, closed=True)

    async def positions_(
        self, scope: AccountScope, query: PositionQuery, *, environment: str
    ) -> tuple[PositionRow, ...]:
        reach = self._reach(scope, environment, query.accounts)
        return tuple(
            p for p in self.positions
            if p.exchange_account_id in reach and query.symbol in (None, p.symbol)
            and (not query.open_only or p.size > 0)
        )  # fmt: skip

    async def position(
        self, scope: AccountScope, position_id: uuid.UUID, *, environment: str
    ) -> PositionRow | PositionOutOfScope:
        self.calls.append("position")
        if self.fail:
            raise StorageQueryFailed("57014")
        for row in self.positions:
            if row.id == position_id:
                if self._viewable(scope, environment, row.exchange_account_id):
                    return row
                return PositionOutOfScope(row.exchange_account_id)
        return PositionOutOfScope(None)


class ReadStore:
    """`Store` under the port's method names (`orders` and `positions` are its row lists)."""

    def __init__(self, store: Store) -> None:
        self.s = store
        self.orders, self.order, self.positions = store.orders_, store.order, store.positions_
        self.position, self.executions, self.closed_pnl = (
            store.position, store.executions, store.closed_pnl,
        )  # fmt: skip


def seeded() -> Store:
    """Orders, fills and positions on A, B and LIVE (module docstring)."""
    a1 = order(1, ACCOUNT_A)
    a2 = order(2, ACCOUNT_A, state="filled", lifecycle_state="filled", intent="scale_in")
    a3 = order(3, ACCOUNT_A, symbol="ETHUSDT", state="held", lifecycle_state="held")
    b1, live = order(4, ACCOUNT_B), order(5, ACCOUNT_LIVE)
    closed = Decimal("-1.25")
    return Store(
        orders=[(a1, GROUP_A), (a2, GROUP_A), (a3, None), (b1, GROUP_B), (live, None)],
        fills=[
            (fill(1, ACCOUNT_A, a1.id), GROUP_A),
            (fill(2, ACCOUNT_A, a2.id, side="Sell", closed_pnl=closed), GROUP_A),
            (fill(3, ACCOUNT_B, b1.id, closed_pnl=Decimal("4.5")), GROUP_B),
            (fill(4, ACCOUNT_LIVE, live.id, closed_pnl=Decimal(1)), None),
        ],
        positions=[
            position(1, ACCOUNT_A),
            position(2, ACCOUNT_B, side="Sell", size=Decimal("0.100"), avg_price=Decimal("64000")),
            position(3, ACCOUNT_A, symbol="ETHUSDT", side="None", size=Decimal(0)),
            position(4, ACCOUNT_LIVE, size=Decimal(5), avg_price=Decimal("1")),
            position(5, ACCOUNT_A, symbol="SOLUSDT", stop_loss=None, trailing_stop=None),
        ],
        events={a1.id: [event(1, a1.id, {"ok": True, "record": RECORD}), event(2, a1.id, {})]},
    )


@dataclass
class World:
    store: Store = field(default_factory=seeded)
    principals: Principals | None = field(default_factory=Principals)
    audit: Audit = field(default_factory=Audit)
    composed: bool = True
    versions: dict[uuid.UUID, int] = field(default_factory=dict)
    now: datetime = NOW
    #: A live view-as context bound around each request, as the view-as guard binds one.
    viewing: ViewAsRequestContext | None = None

    def app(self) -> FastAPI:
        reads = OmsReads(ReadStore(self.store), "demo") if self.composed else None  # type: ignore[arg-type]  # the in-memory port
        app = FastAPI()
        app.include_router(
            make_oms_reads_router(
                self.principals, reads, audit=self.audit, versions=self.versions.get,
                clock=lambda: self.now,
            )
        )  # fmt: skip
        if self.viewing is not None:
            context = self.viewing

            @app.middleware("http")
            async def bound(request: Request, call_next: Any) -> Any:
                with bound_view_as(context):
                    return await call_next(request)

        return app

    @asynccontextmanager
    async def client(self) -> AsyncIterator[AsyncClient]:
        transport = ASGITransport(app=self.app())
        async with AsyncClient(transport=transport, base_url="http://t") as client:
            yield client


def viewing_as(target: str) -> ViewAsRequestContext:
    """The Owner viewing as `target` in a live context: the read answers as the target."""
    return ViewAsRequestContext(
        viewer_user_id=USERS["owner"], viewer_session_id=SESSION, viewer_label="owner",
        target_user_id=USERS[target], context_id=uuid.uuid5(SESSION, "view-as"),
        subject_user_id=USERS[target], phase=ViewAsPhase.LIVE,
    )  # fmt: skip


def bearer(who: str) -> dict[str, str]:
    return {"authorization": f"Bearer {who}"}


def ids(body: dict[str, Any]) -> list[str]:
    return [item["id"] for item in body["items"]]


def accounts_of(body: dict[str, Any]) -> set[str]:
    return {item["exchange_account_id"] for item in body["items"]}


__all__ = [
    "ACCOUNT_A",
    "ACCOUNT_B",
    "ACCOUNT_LIVE",
    "MISSING",
    "NOW",
    "RECORD",
    "T0",
    "Audit",
    "Principals",
    "Store",
    "World",
    "accounts_of",
    "bearer",
    "event",
    "fill",
    "ids",
    "order",
    "position",
    "replace",
    "seeded",
    "viewing_as",
]  # fmt: skip
