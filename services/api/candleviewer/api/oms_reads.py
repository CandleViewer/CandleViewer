"""The OMS read routes (E29-T07 #915, PR 1): `GET /orders` (`listOrders`), `GET /orders/{orderId}`
(`getOrder`), `GET /positions` (`listPositions`), `GET /positions/{positionId}` (`getPosition`) and
`GET /executions` (`listExecutions`), `GET /executions/closed-pnl` (`listClosedPnl`, from the fills
that carry a closed PnL until the nightly backfill lands) and `GET /orders/{orderId}/diagnostics`
(`getOrderDiagnostics`, the Owner's alone: decision D7), as 22 declares them.

After the middleware (session state, the view-as guard, deny-by-default) each route checks, each
before the next:

1. the principal (`resolve_principal`): none composed is 501, none found 401, one whose store does
   not answer 503 `store_unavailable`;
2. its operation's permissions (22 `x-rbac`: `orders:read`, `positions:read`, `executions:read`;
   diagnostics `orders:read` and `admin:read`, which only the Owner holds), each `enforce`d with
   no account (the store holds the scope): 403 `forbidden` without one, audited `rbac.denied`, a
   403 even when that record cannot be written, so a Manager or Viewer is refused diagnostics
   whatever the id;
3. the query string or the path id (`api.oms_read_params`): 400 `validation_failed` naming each
   rule that failed, `invalid_time_range`, or `invalid_cursor` for a cursor that is malformed,
   expired, or another caller's or query's; unaudited, as nothing in scope is named yet;
4. the store: none composed (the fake backend) is 503 `store_unavailable`;
5. the read (`oms.reads.OmsReads`), the scope held in SQL (C-12.4): an account the query names
   outside the caller's grants, or one that does not exist, refuses the whole request 403
   `account_scope_denied`, counted and audited `rbac.denied` naming the ids (a 403 even when that
   record cannot be written), no row read (SR-E29-13); an order or a position on an account
   outside the grants is the same 404 `not_found` as a missing id, never telling them apart, and
   audited `rbac.denied` when an account holds the id; a store that does not answer is 503
   `store_unavailable`.

Bodies carry 22's members only: an order (`order_body`) with its remaining quantity and creation
time, and on `getOrder` its fills and, with `include_events`, its events without their payloads
(SR-E29-09), with the order's `ETag` when the OMS knows its version; a position with 22's
vocabulary (a member the row lacks is absent, never invented); a fill. No log line carries a value
of a row (C-12.6).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Final, get_args

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response
from starlette.datastructures import QueryParams

from candleviewer.api.csrf import source_ip
from candleviewer.api.oms_read_params import (
    CursorInvalid,
    Listing,
    ParamsInvalid,
    closed_pnl_query,
    execution_query,
    next_cursor,
    order_query,
    position_query,
    read_after,
)
from candleviewer.api.order_acceptance import order_body
from candleviewer.api.order_admission import (
    AuditEmitter,
    OrderPrincipals,
    problem,
    resolve_principal,
)
from candleviewer.api.order_diagnostics import RecordRefused, exchange_calls
from candleviewer.api.order_etag import order_etag
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.api.refusal_session import SessionsLike
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.metrics import count_authz_denial
from candleviewer.auth.scopes import ForbiddenError, account_scope, enforce
from candleviewer.domain.primitives import Environment
from candleviewer.observability.context import current_request_uuid
from candleviewer.oms.errors import AccountScopeDenied, FieldError, StoreUnavailable
from candleviewer.oms.reads import AggregatePosition, OmsReads, aggregate_positions
from candleviewer.storage.repositories.accounts import AccountScope
from candleviewer.storage.repositories.executions import ExecType
from candleviewer.storage.repositories.oms_reads import Keyset, ListedExecution, ListedOrder
from candleviewer.storage.repositories.orders import OrderEventRow, OutOfScope
from candleviewer.storage.repositories.positions import PositionRow

__all__ = ["flag_param", "make_oms_reads_router"]

_LIST_ORDERS: Final = "listOrders"
_LIST_EXECUTIONS: Final = "listExecutions"
_LIST_CLOSED_PNL: Final = "listClosedPnl"
_DIAGNOSTICS: Final = "getOrderDiagnostics"
#: Each operation's 22 `x-rbac.permissions`, every one required; the first names its scope.
_PERMISSIONS: Final[Mapping[str, tuple[Permission, ...]]] = {
    "listOrders": (Permission.ORDERS_READ,), "getOrder": (Permission.ORDERS_READ,),
    _DIAGNOSTICS: (Permission.ORDERS_READ, Permission.ADMIN_READ),
    "listPositions": (Permission.POSITIONS_READ,), "getPosition": (Permission.POSITIONS_READ,),
    "listExecutions": (Permission.EXECUTIONS_READ,),
    _LIST_CLOSED_PNL: (Permission.EXECUTIONS_READ,),
}  # fmt: skip
#: 22 `Execution.exec_type`: a stored type outside it (`SessionSettlePnl`) is served without one.
_EXEC_TYPES: Final = frozenset(get_args(ExecType)) - {"SessionSettlePnl"}
_POSITION_SIDES: Final = {"Buy": "long", "Sell": "short"}

type Body = dict[str, object]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _money(value: Decimal | None) -> str | None:
    """22 `Decimal`: plain notation, never an exponent."""
    return None if value is None else format(value, "f")


def _at(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _present(body: Mapping[str, object | None], *names: str) -> Body:
    """`body` without the `names` whose value is None: members 22 types as never null."""
    return {k: v for k, v in body.items() if v is not None or k not in names}


def order_document(listed: ListedOrder, env: Environment) -> Body:
    """22 `Order`, as the order routes render one, with its remaining quantity and creation time."""
    row = listed.order
    body = order_body(row, listed.trade_group_id, env, row.state, row.lifecycle_state)
    return body | {"remaining_qty": _money(row.leaves_qty), "created_at": _at(row.created_ts)}


def event_document(event: OrderEventRow) -> Body:
    """22 `OrderEvent`: never its stored payload or the exchange's text (SR-E29-09)."""
    return {"id": event.id, "kind": event.kind, "event_ts": _at(event.event_ts)}


def execution_document(listed: ListedExecution) -> Body:
    """22 `Execution`."""
    x = listed.execution
    body: dict[str, object | None] = {
        "id": str(x.id), "exec_id": x.exec_id,
        "order_id": None if x.order_id is None else str(x.order_id),
        "exchange_account_id": str(x.exchange_account_id),
        "trade_group_id": None if listed.trade_group_id is None else str(listed.trade_group_id),
        "symbol": x.symbol, "side": x.side.lower(), "exec_qty": _money(x.exec_qty),
        "exec_price": _money(x.exec_price), "exec_value": _money(x.exec_value),
        "fee": _money(x.exec_fee), "fee_rate": _money(x.fee_rate), "fee_coin": x.fee_currency,
        "is_maker": x.is_maker, "exec_type": x.exec_type if x.exec_type in _EXEC_TYPES else None,
        "exec_pnl": _money(x.closed_pnl), "ts": _at(x.exec_ts), "is_paper": x.is_paper,
    }  # fmt: skip
    return _present(body, "order_id", "fee_rate", "exec_type", "exec_pnl")


def closed_pnl_document(listed: ListedExecution) -> Body:
    """22 `ClosedPnl` from a fill that carries a closed PnL (22 `listClosedPnl`): what a fill
    holds, the closed position's side its opposite; nothing it does not hold is estimated."""
    x = listed.execution
    return {
        "id": str(x.id), "exchange_account_id": str(x.exchange_account_id), "symbol": x.symbol,
        "side": "short" if x.side == "Buy" else "long", "avg_exit_price": _money(x.exec_price),
        "closed_pnl": _money(x.closed_pnl), "closed_at": _at(x.exec_ts),
    }  # fmt: skip


def position_document(row: PositionRow) -> Body:
    """22 `Position`; a member the row holds no value for is absent. The exchange's 0 trailing stop
    is stored as NULL and served as `0`, none; `native_stop_present` is said of an open position
    only (C-2.6: no stop-loss is the alarm `ix_pos_no_sl` reads)."""
    side = _POSITION_SIDES.get(row.side or "") if row.size > 0 else None
    open_ = side is not None
    body: dict[str, object | None] = {
        "id": str(row.id), "exchange_account_id": str(row.exchange_account_id),
        "symbol": row.symbol, "side": side or "flat",
        "position_idx": row.position_idx, "size": _money(row.size),
        "avg_price": _money(row.avg_price), "mark_price": _money(row.mark_price),
        "position_value": _money(row.position_value), "leverage": _money(row.leverage),
        "unrealised_pnl": _money(row.unrealised_pnl), "liq_price": _money(row.liq_price),
        "bust_price": _money(row.bust_price), "take_profit": _money(row.take_profit),
        "stop_loss": _money(row.stop_loss), "trailing_stop": _money(row.trailing_stop) or "0",
        "tpsl_mode": row.tpsl_mode,
        "native_stop_present": (row.stop_loss is not None) if open_ else None,
        "updated_at": _at(row.updated_at), "is_paper": row.is_paper,
    }  # fmt: skip
    nullable = {"liq_price", "bust_price", "take_profit", "stop_loss"}
    return _present(body, *(name for name in body if name not in nullable))


def aggregate_document(found: AggregatePosition) -> Body:
    """22 `AggregatePosition`, its per-account breakdown in `accounts`."""
    legs = [
        _present({
            "exchange_account_id": str(leg.account_id), "size": _money(leg.size),
            "side": leg.side, "unrealised_pnl": _money(leg.unrealised_pnl),
        }, "unrealised_pnl")
        for leg in found.legs
    ]  # fmt: skip
    body: dict[str, object | None] = {
        "symbol": found.symbol, "net_size": _money(found.net_size),
        "gross_size": _money(found.gross_size),
        "weighted_avg_price": _money(found.weighted_avg_price),
        "unrealised_pnl": _money(found.unrealised_pnl), "accounts": legs,
    }  # fmt: skip
    return _present(body, "weighted_avg_price", "unrealised_pnl")


def _page(items: list[Body], nxt: str | None) -> JSONResponse:
    meta = {"next_cursor": nxt, "has_more": nxt is not None, "count": len(items)}
    return JSONResponse({"items": items, "meta": meta})


def make_oms_reads_router(
    principals: OrderPrincipals | None, reads: OmsReads | None, *, audit: AuditEmitter,
    auth: SessionsLike | None = None, versions: Callable[[uuid.UUID], int | None] | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> APIRouter:  # fmt: skip
    """The seven reads (module docstring). `reads` is None on the fake backend (503 after RBAC);
    `versions` gives an order's version for `getOrder`'s `ETag`, None when the OMS knows none."""
    router = APIRouter()

    async def denied(
        principal: TradingPrincipal, request: Request, operation: str, reason: str,
        named: Mapping[str, Any],
    ) -> None:  # fmt: skip
        """A scope refusal's `rbac.denied`, best effort: its answer stands (module docstring)."""
        actor = principal.snapshot.user_id
        try:
            await audit.emit(
                "rbac.denied", actor_label=str(actor), actor_user_id=actor,
                actor_ip=source_ip(request.scope), session_id=principal.session_id,
                outcome="denied", severity="warning", reason=reason,
                request_id=current_request_uuid(), **named,
            )  # fmt: skip
        except (AuditError, RuntimeError) as exc:  # RuntimeError: the writer is not started
            _log().warning(
                "oms_read_denial_unaudited", operation=operation, error=type(exc).__name__
            )

    def reason(operation: str) -> str:
        return (
            f"account_not_granted:{_PERMISSIONS[operation][0].value}:{Scope.GRANTED_ACCOUNTS.value}"
        )

    async def admit(
        request: Request, operation: str
    ) -> tuple[TradingPrincipal, OmsReads] | Response:
        """Steps 1, 2 and 4 (module docstring); step 3 is the route's, between them."""
        if principals is None:
            return problem(501, "not_implemented", "No principal source is composed.")
        try:
            principal = await resolve_principal(principals, request, auth)
        except StoreUnavailable:
            return problem(503, "store_unavailable", "The session could not be read.")
        if principal is None:
            return problem(401, "unauthenticated", "No verified session for this request.")
        needed = _PERMISSIONS[operation]
        try:
            for permission in needed:
                await enforce(
                    principal.snapshot, permission, emitter=audit,
                    actor_ip=source_ip(request.scope), session_id=principal.session_id,
                    request_id=current_request_uuid(),
                )  # fmt: skip
        except (ForbiddenError, AuditError, RuntimeError) as exc:
            if not isinstance(exc, ForbiddenError):  # counted by `enforce`; its 403 stands
                _log().warning(
                    "oms_read_denial_unaudited", operation=operation, error=type(exc).__name__
                )
            need = [p.value for p in needed]
            detail = f"Requires {' and '.join(need)}."
            return problem(403, "forbidden", detail, required_permissions=need)
        if reads is None:
            return problem(
                503, "store_unavailable", "The OMS reads are not available on this backend."
            )
        return principal, reads

    def invalid(exc: ParamsInvalid | CursorInvalid) -> Response:
        if isinstance(exc, CursorInvalid):
            detail = "The cursor is malformed, expired or for another query."
            return problem(400, "invalid_cursor", detail)
        errors = [{"field": e.field, "rule": e.rule, "message": e.message} for e in exc.errors]
        return problem(400, exc.code, f"{len(errors)} parameters failed validation.", errors=errors)

    async def scoped_failure(
        exc: Exception, principal: TradingPrincipal, request: Request, operation: str,
        accounts: tuple[uuid.UUID, ...],
    ) -> Response:  # fmt: skip
        if isinstance(exc, AccountScopeDenied):
            count_authz_denial(
                _PERMISSIONS[operation][0], principal.snapshot.roles, route=operation
            )
            listed = {"operation": operation, "exchange_account_ids": [str(a) for a in accounts]}
            await denied(principal, request, operation, reason(operation), {"after_state": listed})
            detail = "An exchange account named is outside your grants."
            return problem(403, "account_scope_denied", detail)
        if isinstance(exc, StoreUnavailable):
            return problem(503, "store_unavailable", "The OMS store is unavailable.")
        raise exc

    def bad_id(name: str) -> Response:
        error = FieldError(name, "uuid", "Name it by its id (a UUID).")
        return invalid(ParamsInvalid((error,)))

    async def missing(
        principal: TradingPrincipal, request: Request, operation: str, kind: str,
        object_id: uuid.UUID, holder: uuid.UUID | None,
    ) -> Response:  # fmt: skip
        """A foreign id and a missing one alike (SR-E29-13); the foreign one audited."""
        if holder is not None:
            count_authz_denial(
                _PERMISSIONS[operation][0], principal.snapshot.roles, route=operation
            )
            named = {"object_kind": kind, "object_id": str(object_id)}
            await denied(principal, request, operation, reason(operation), named)
        return problem(404, "not_found", f"No such {kind}.")

    async def listed[Q, T](
        request: Request, operation: str, parse: Callable[[QueryParams], Listing[Q]],
        fetch: Callable[[OmsReads, AccountScope, Q, Keyset | None, int], Awaitable[Sequence[T]]],
        render: Callable[[OmsReads, T], Body], position: Callable[[T], Keyset],
        accounts: Callable[[Q], tuple[uuid.UUID, ...]],
    ) -> Response:  # fmt: skip
        """A keyset list, `listOrders`, `listExecutions` or `listClosedPnl`: one row past the page
        says there is a next one, whose cursor names the page's last row."""
        if isinstance(admitted := await admit(request, operation), Response):
            return admitted
        principal, service = admitted
        me, now = principal.snapshot.user_id, int(clock().timestamp())
        try:
            listing = parse(request.query_params)
            after = read_after(listing, operation, me, now)
        except (ParamsInvalid, CursorInvalid) as exc:
            return invalid(exc)
        scope, query, limit = account_scope(principal.snapshot), listing.query, listing.limit
        try:
            rows = await fetch(service, scope, query, after, limit + 1)
        except (AccountScopeDenied, StoreUnavailable) as exc:
            return await scoped_failure(exc, principal, request, operation, accounts(query))
        shown = rows[:limit]
        last = position(shown[-1]) if len(rows) > limit else None
        nxt = None if last is None else next_cursor(listing, operation, me, last, now)
        return _page([render(service, row) for row in shown], nxt)

    @router.get("/orders", tags=["trading"])
    async def list_orders(request: Request) -> Response:
        return await listed(
            request, _LIST_ORDERS, order_query,
            lambda s, scope, q, after, n: s.orders(scope, q, after=after, limit=n),
            lambda s, row: order_document(row, s.environment),
            lambda row: Keyset(row.order.created_ts, row.order.id), lambda q: q.accounts,
        )  # fmt: skip

    @router.get("/executions", tags=["executions"])
    async def list_executions(request: Request) -> Response:
        return await listed(
            request, _LIST_EXECUTIONS, execution_query,
            lambda s, scope, q, after, n: s.executions(scope, q, after=after, limit=n),
            lambda _s, row: execution_document(row),
            lambda row: Keyset(row.execution.exec_ts, row.execution.id), lambda q: q.accounts,
        )  # fmt: skip

    @router.get("/executions/closed-pnl", tags=["executions"])
    async def list_closed_pnl(request: Request) -> Response:
        return await listed(
            request, _LIST_CLOSED_PNL, closed_pnl_query,
            lambda s, scope, q, after, n: s.closed_pnl(scope, q, after=after, limit=n),
            lambda _s, row: closed_pnl_document(row),
            lambda row: Keyset(row.execution.exec_ts, row.execution.id), lambda q: q.accounts,
        )  # fmt: skip

    @router.get("/orders/{orderId}/diagnostics", tags=["trading"])
    async def get_order_diagnostics(
        request: Request, order_ref: Annotated[str, Path(alias="orderId")]
    ) -> Response:
        """The Owner's (D7): the order, its events without payloads and its stored exchange
        records, checked on the way out (`api.order_diagnostics`); the read recorded before its
        body is sent (`order.diagnostics_viewed`), else `503 audit_unavailable` with no body."""
        if isinstance(admitted := await admit(request, _DIAGNOSTICS), Response):
            return admitted
        principal, service = admitted
        try:
            order_id = uuid.UUID(order_ref)
        except ValueError:
            return bad_id("orderId")
        scope = account_scope(principal.snapshot)
        try:
            found = await service.order(scope, order_id, events=True)
        except (AccountScopeDenied, StoreUnavailable) as exc:
            return await scoped_failure(exc, principal, request, _DIAGNOSTICS, ())
        if isinstance(found, OutOfScope):
            holder = found.account_id
            return await missing(principal, request, _DIAGNOSTICS, "order", order_id, holder)
        try:
            calls = exchange_calls(found.events)
        except RecordRefused:  # logged by the check; never a partial answer (OM-I05)
            return problem(
                503, "store_unavailable", "The order's exchange records cannot be served."
            )
        scoped = found.scoped
        account, actor = scoped.order.exchange_account_id, principal.snapshot.user_id
        try:  # written ahead of the body (C-2.9, SR-E29-09)
            await audit.emit(
                "order.diagnostics_viewed", actor_label=str(actor), actor_user_id=actor,
                actor_ip=source_ip(request.scope), session_id=principal.session_id,
                object_kind="order", object_id=str(order_id), outcome="success",
                severity="info", after_state={"account_id": str(account)},
                request_id=current_request_uuid(),
            )  # fmt: skip
        except (AuditError, RuntimeError) as exc:  # RuntimeError: the writer is not started
            _log().error("oms_diagnostics_unaudited", error=type(exc).__name__)
            return problem(
                503, "audit_unavailable", "The read cannot be recorded, so it is refused."
            )
        order = order_document(
            ListedOrder(scoped.order, scoped.trade_group_id), service.environment
        )
        events = [event_document(e) for e in found.events]
        return JSONResponse({"order": order, "events": events, "exchange_calls": calls})

    @router.get("/orders/{orderId}", tags=["trading"])
    async def get_order(
        request: Request, order_ref: Annotated[str, Path(alias="orderId")]
    ) -> Response:
        operation = "getOrder"
        if isinstance(admitted := await admit(request, operation), Response):
            return admitted
        principal, service = admitted
        try:
            order_id = uuid.UUID(order_ref)
        except ValueError:
            return bad_id("orderId")
        try:
            events = flag_param(request.query_params, "include_events")
        except ParamsInvalid as exc:
            return invalid(exc)
        try:
            found = await service.order(account_scope(principal.snapshot), order_id, events=events)
        except (AccountScopeDenied, StoreUnavailable) as exc:
            return await scoped_failure(exc, principal, request, operation, ())
        if isinstance(found, OutOfScope):
            return await missing(principal, request, operation, "order", order_id, found.account_id)
        scoped = found.scoped
        body = order_document(ListedOrder(scoped.order, scoped.trade_group_id), service.environment)
        body["executions"] = [execution_document(x) for x in found.executions]
        if events:
            body["events"] = [event_document(e) for e in found.events]
        seq = None if versions is None else versions(order_id)
        headers = {} if seq is None else {"ETag": order_etag(order_id, seq)}
        return JSONResponse(body, headers=headers)

    @router.get("/positions", tags=["positions"])
    async def list_positions(request: Request) -> Response:
        operation = "listPositions"
        if isinstance(admitted := await admit(request, operation), Response):
            return admitted
        principal, service = admitted
        try:
            query, aggregate = position_query(request.query_params)
        except ParamsInvalid as exc:
            return invalid(exc)
        try:
            rows = await service.positions(account_scope(principal.snapshot), query)
        except (AccountScopeDenied, StoreUnavailable) as exc:
            return await scoped_failure(exc, principal, request, operation, query.accounts)
        found = aggregate_positions(rows) if aggregate else ()
        items = [position_document(row) for row in rows]
        return JSONResponse({"items": items, "aggregates": [aggregate_document(a) for a in found]})

    @router.get("/positions/{positionId}", tags=["positions"])
    async def get_position(
        request: Request, position_ref: Annotated[str, Path(alias="positionId")]
    ) -> Response:
        operation = "getPosition"
        if isinstance(admitted := await admit(request, operation), Response):
            return admitted
        principal, service = admitted
        try:
            position_id = uuid.UUID(position_ref)
        except ValueError:
            return bad_id("positionId")
        try:
            found = await service.position(account_scope(principal.snapshot), position_id)
        except (AccountScopeDenied, StoreUnavailable) as exc:
            return await scoped_failure(exc, principal, request, operation, ())
        if not isinstance(found, PositionRow):
            holder = found.account_id
            return await missing(principal, request, operation, "position", position_id, holder)
        return JSONResponse(position_document(found))

    return router


def flag_param(params: QueryParams, name: str) -> bool:
    """A boolean query parameter, `false` when absent; else `ParamsInvalid`."""
    raw = params.getlist(name)
    if not raw:
        return False
    if len(raw) == 1 and raw[0] in ("true", "false"):
        return raw[0] == "true"
    raise ParamsInvalid((FieldError(name, "boolean", f"`{name}` is `true` or `false`."),))
