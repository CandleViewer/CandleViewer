"""The trade-group reads (E28-T05 #909, S2f): `listTradeGroups` and `getTradeGroup` (22).

The session (401), `orders:read` alone (403, audited), then `TradeGroupReader` (503 on the fake
backend) in the caller's scope, in SQL (SR-E28-21): a group with a leg outside the grants is not
listed and is the get's one 404, byte for byte a missing group's, with no record written and no
order read (SR-E29-13). A page is read as `limit + 1`, so a next page is known without a count:
`meta` has no `total`, which would count groups the caller cannot read (OL-02). The cursor is the
last group served's `(created_at, id)`, never the look-ahead row's; the served legs' orders are
read once. The documents of a page and their JSON are built on a worker thread, as a page of 500
groups with 20 legs takes about half a second (AGENTS.md 5.2). Logs carry a class and a SQLSTATE
alone (C-12.6).
"""

from __future__ import annotations

import asyncio
import inspect
import struct
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, Final

import structlog
from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse, Response

from candleviewer.accounts.errors import (
    AccountNotFoundError,
    AccountScopeDeniedError,
    AccountsError,
)
from candleviewer.accounts.profiles import to_us
from candleviewer.accounts.trade_group_repository import TradeGroupReader
from candleviewer.accounts.trade_groups import ScopedTradeGroup, from_us
from candleviewer.api.csrf import source_ip
from candleviewer.api.profile_audit import Emitter
from candleviewer.api.profiles import problem
from candleviewer.api.refusal_session import NamesSession, SessionsLike
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.api.trade_group_cursor import decode_cursor, encode_cursor
from candleviewer.api.trade_group_projection import group_document
from candleviewer.api.users import SnapshotResolver
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.metrics import count_authz_denial
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, account_scope, enforce
from candleviewer.domain.primitives import GroupId
from candleviewer.observability.context import current_request_uuid
from candleviewer.storage.errors import StorageError, StorageQueryFailed
from candleviewer.storage.repositories.trade_groups import TradeGroupStatus

_READ: Final = Permission.ORDERS_READ
_LIST: Final = "listTradeGroups"
_SYMBOL: Final = r"^[A-Z0-9]{2,20}USDT$"  # 22's `Symbol`
_PLACE: Final = struct.Struct(">q16s")  # a cursor's place: `created_at` (epoch us), then the id


class _OnGroup:
    """`enforce` names no object: a refused get's records name its group (C-2.9)."""

    def __init__(self, audit: Emitter, group_id: uuid.UUID) -> None:
        self._audit, self._id = audit, str(group_id)

    async def emit(self, action: str, **kwargs: Any) -> None:
        named = {"object_kind": "trade_group", "object_id": self._id}
        await self._audit.emit(action, **kwargs | named)


def _forbidden(principal: PrincipalSnapshot, unwritten: Exception | None = None) -> Response:
    """403; a refusal whose record could not be written is logged by its class, and stands."""
    if unwritten is not None:  # a module-level logger pins a stale processor chain (#2008)
        error, actor = type(unwritten).__name__, str(principal.user_id)
        log = structlog.get_logger(__name__)
        log.warning("trade_group_read_denial_unaudited", principal_user_id=actor, error=error)
    return problem("forbidden", f"Requires {_READ.value}.", required_permissions=[_READ.value])


def _after(place: bytes | None) -> tuple[datetime, uuid.UUID] | None:
    """A cursor's place in the list's order (`created_at`, then id), else `None`: not that many
    bytes (a `struct.error`), or a time no date holds (an `OverflowError`)."""
    try:
        at, key = _PLACE.unpack(place or b"")
        return from_us(at), uuid.UUID(bytes=key)
    except (struct.error, OverflowError):
        return None


type _Orders = Mapping[uuid.UUID, Sequence[uuid.UUID]]  # each leg's order ids, by leg id


def _page(
    shown: Sequence[ScopedTradeGroup], orders: _Orders, meta: Mapping[str, object]
) -> Response:
    """22's page: the documents of `shown` and their JSON, CPU work that grows with the page, so
    it is run on a worker thread, never on the serving loop (R1C-01)."""
    return JSONResponse({"items": [group_document(g, orders) for g in shown], "meta": meta})


def _one(scoped: ScopedTradeGroup, orders: _Orders) -> Response:
    """22's `TradeGroup` of one group, in its JSON: run on a worker thread, as `_page` is."""
    return JSONResponse(group_document(scoped, orders))


def make_trade_groups_router(
    reader: TradeGroupReader | None, audit: Emitter, resolver: SnapshotResolver | None, *,
    auth: SessionsLike | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> APIRouter:  # fmt: skip
    router = APIRouter(tags=["trading"])  # with no reader 503, no resolver 501

    async def admit(
        request: Request, named: Emitter
    ) -> tuple[PrincipalSnapshot, TradeGroupReader] | Response:
        if resolver is None:
            return problem("not_implemented", "No principal resolver is wired.")
        got = resolver.resolve(request)
        if (principal := await got if inspect.isawaitable(got) else got) is None:
            return problem("unauthenticated", "No verified session for this request.")
        try:  # the permission alone (`Scope.NONE`): the store applies the scope
            ip, request_id = source_ip(request.scope), current_request_uuid()
            await enforce(principal, _READ, emitter=named, actor_ip=ip, request_id=request_id)
        except ForbiddenError:
            return _forbidden(principal)
        except (AuditError, RuntimeError) as exc:  # RuntimeError: the audit writer not started
            return _forbidden(principal, exc)
        if reader is None:
            return problem("store_unavailable", "Trade groups are not available on this backend.")
        return principal, reader

    async def refused(
        request: Request, principal: PrincipalSnapshot, named: Emitter, exc: Exception
    ) -> Response:
        """The owner gate (SR-051) 403, counted, audited; the one 404; an outage or a row the
        models refuse 503; else raised."""
        if isinstance(exc, AccountScopeDeniedError):
            count_authz_denial(_READ, principal.roles)
            actor, ip = principal.user_id, source_ip(request.scope)
            try:
                await named.emit(
                    "rbac.denied", actor_label=str(actor), actor_user_id=actor, actor_ip=ip,
                    outcome="denied", severity="warning", request_id=current_request_uuid(),
                    reason=f"not_owner:{_READ.value}:{Scope.GRANTED_ACCOUNTS.value}",
                )  # fmt: skip
            except (AuditError, RuntimeError) as error:
                return _forbidden(principal, error)
            return _forbidden(principal)
        if isinstance(exc, AccountNotFoundError):  # missing, or any leg outside the grants
            return problem("not_found", "No such trade group.")
        if not isinstance(exc, AccountsError | StorageError) and not is_storage_outage(exc):
            raise exc
        facts = exc if isinstance(exc, StorageQueryFailed) else getattr(exc, "orig", None)
        state, name = getattr(facts, "sqlstate", None), type(exc).__name__
        log = structlog.get_logger(__name__)  # per call (#2008)
        log.warning("trade_group_read_unavailable", error=name, sqlstate=state)
        return problem("store_unavailable", "The trade-group store is unavailable.")

    @router.get("/trade-groups")
    async def list_trade_groups(
        request: Request, cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        symbol: Annotated[str | None, Query(pattern=_SYMBOL)] = None,
        status: Annotated[list[TradeGroupStatus] | None, Query()] = None,
        from_: Annotated[datetime | None, Query(alias="from")] = None, to: datetime | None = None,
    ) -> Response:  # fmt: skip
        named = NamesSession(audit, auth, request)
        if isinstance(admitted := await admit(request, named), Response):
            return admitted
        principal, groups = admitted
        if any(t.utcoffset() is None for t in (from_, to) if t is not None):
            return problem("invalid_time_range", "from and to need a UTC offset.", status=400)
        try:  # `0001-01-01T00:00:00+14:00` has no UTC date: the driver would refuse it, a 500
            start, end = (None if t is None else t.astimezone(UTC) for t in (from_, to))
        except OverflowError:
            return problem("invalid_time_range", "from and to must be dates in UTC.", status=400)
        if start is not None and end is not None and start > end:
            return problem("invalid_time_range", "from is after to.", status=400)
        statuses = sorted(set(status or ()))  # a cursor is bound to each filter as given
        times = [None if t is None else str(to_us(t)) for t in (start, end)]
        bound = (symbol, ",".join(statuses) or None, *times)
        now, after = int(clock().timestamp()), None
        if cursor is not None:
            after = _after(decode_cursor(cursor, _LIST, principal.user_id, bound, now))
            if after is None:
                detail = "The cursor is malformed, expired or for another query."
                return problem("invalid_cursor", detail, status=400)
        scope = account_scope(principal)
        try:
            found = await groups.list(
                scope, symbol=symbol, statuses=statuses, created_from=start, created_to=end,
                after=after, limit=limit + 1,
            )  # fmt: skip
            shown = found[:limit]
            orders = await groups.order_ids(scope, [x.leg_id for g in shown for x in g.record.legs])
        except Exception as exc:  # mapped, or raised as a defect
            return await refused(request, principal, named, exc)
        nxt = None
        if len(found) > limit:  # past the last group served, not the look-ahead row
            last = shown[-1].record.group
            place = _PLACE.pack(last.created_at, last.group_id.bytes)
            nxt = encode_cursor(_LIST, principal.user_id, bound, place, now)
        meta = {"next_cursor": nxt, "has_more": nxt is not None, "count": len(shown)}
        return await asyncio.to_thread(_page, shown, orders, meta)

    @router.get("/trade-groups/{tradeGroupId}")
    async def get_trade_group(
        request: Request, group_id: Annotated[uuid.UUID, Path(alias="tradeGroupId")]
    ) -> Response:
        named = _OnGroup(NamesSession(audit, auth, request), group_id)
        if isinstance(admitted := await admit(request, named), Response):
            return admitted
        principal, groups = admitted
        scope = account_scope(principal)
        try:
            scoped = await groups.get(scope, GroupId(group_id))
            orders = await groups.order_ids(scope, [x.leg_id for x in scoped.record.legs])
        except Exception as exc:  # mapped, or raised as a defect
            return await refused(request, principal, named, exc)
        return await asyncio.to_thread(_one, scoped, orders)

    return router
