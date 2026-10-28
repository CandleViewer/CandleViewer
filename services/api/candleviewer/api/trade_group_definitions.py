"""The trade-group definition reads (E28-T05 #909, S2b), each member with its readiness (22).

The session (401), `accounts:read` alone (403, audited), then the store (503 on the fake backend) in
the caller's scope, in SQL (SR-E28-21): a definition with a member outside the grants is not listed
and is the get's one unaudited 404, as a missing or deleted one is, its readiness never read. Never
`created_by`; the `ETag` leaves readiness out; logs carry a class and a SQLSTATE alone (C-12.6).
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Final

import structlog
from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse, Response

from candleviewer.accounts import trade_group_definitions as domain
from candleviewer.accounts.errors import AccountScopeDeniedError, AccountsError
from candleviewer.accounts.trade_group_readiness import Readiness, ReadinessMember, readiness
from candleviewer.accounts.trade_group_readiness import ReadinessSource as Source
from candleviewer.api.csrf import source_ip
from candleviewer.api.profile_audit import Emitter
from candleviewer.api.profile_projection import rfc3339
from candleviewer.api.profiles import problem
from candleviewer.api.refusal_session import NamesSession, SessionsLike
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.api.trade_group_cursor import decode_cursor, encode_cursor
from candleviewer.api.users import SnapshotResolver
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.metrics import count_authz_denial
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, account_scope, enforce
from candleviewer.observability.context import current_request_uuid
from candleviewer.storage.errors import StorageError, StorageQueryFailed
from candleviewer.storage.repositories import trade_group_definitions as port

_READ: Final = Permission.ACCOUNTS_READ
_LIST: Final = "listTradeGroupDefinitions"


class _OnDefinition:
    """`enforce` names no object: a refused get's records name its definition (C-2.9)."""

    def __init__(self, audit: Emitter, definition_id: uuid.UUID) -> None:
        self._audit, self._id = audit, str(definition_id)

    async def emit(self, action: str, **kwargs: Any) -> None:
        named = {"object_kind": "trade_group_definition", "object_id": self._id}
        await self._audit.emit(action, **kwargs | named)


def _forbidden(principal: PrincipalSnapshot, unwritten: Exception | None = None) -> Response:
    """403; a refusal whose record could not be written is logged by its class, and stands."""
    if unwritten is not None:  # a module-level logger pins a stale processor chain (#2008)
        error, actor = type(unwritten).__name__, str(principal.user_id)
        log = structlog.get_logger(__name__)
        log.warning("trade_group_definition_denial_unaudited", principal_user_id=actor, error=error)
    return problem("forbidden", f"Requires {_READ.value}.", required_permissions=[_READ.value])


def definition_readiness(stored: domain.StoredDefinition, source: Source) -> Readiness:
    """From each member's switch and its account row's, both read with the definition."""
    pairs = zip(stored.definition.members, stored.member_accounts, strict=True)
    members = (ReadinessMember(m.account_id, m.enabled, a.account_enabled) for m, a in pairs)
    return readiness(members, source, stored.definition.environment)


def definition_document(stored: domain.StoredDefinition, ready: Readiness) -> dict[str, object]:
    """22's closed `TradeGroupDefinition`: no writer (SR-E28-21), readiness as of the read."""
    d, states = stored.definition, [(m.account_id, m.ready, m.reason) for m in ready.members]
    return {
        "id": str(stored.definition_id), "created_at": rfc3339(stored.created_at),
        "updated_at": rfc3339(stored.updated_at),
        "definition": {"name": d.name, "environment": d.environment, "members": [
            {"exchange_account_id": str(m.account_id), "enabled": m.enabled} for m in d.members
        ]},
        "readiness": {"ready": ready.ready, "total": ready.total, "members": [
            {"exchange_account_id": str(a), "ready": r, "reason": why} for a, r, why in states
        ]},
    }  # fmt: skip


def _after(position: bytes | None) -> tuple[str, uuid.UUID] | None:
    """A cursor's place in `ux_tgd_name`'s order: an id, then a name `text` can hold."""
    try:  # none, too short, or not UTF-8: a `ValueError`
        name, key = (position or b"")[16:].decode(), uuid.UUID(bytes=(position or b"")[:16])
    except ValueError:
        return None
    return (name, key) if name and "\x00" not in name else None


def make_trade_group_definitions_router(
    reads: port.DefinitionReads | None, readiness_source: Source | None, audit: Emitter,
    resolver: SnapshotResolver | None, *, auth: SessionsLike | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> APIRouter:  # fmt: skip
    router = APIRouter(tags=["trading"])  # with no store or readiness 503, no resolver 501

    async def admit(
        request: Request, named: Emitter
    ) -> tuple[PrincipalSnapshot, port.DefinitionReads, Source] | Response:
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
        if reads is None or readiness_source is None:
            detail = "Trade-group definitions are not available on this backend."
            return problem("store_unavailable", detail)
        return principal, reads, readiness_source

    async def refused(
        request: Request, principal: PrincipalSnapshot, named: Emitter, exc: Exception
    ) -> Response:
        """The owner gate (SR-051) 403, counted, audited; an outage or bad row 503; else raised."""
        if isinstance(exc, port.DefinitionStoreError):
            exc = domain.definition_error(exc)  # a fresh error holding no value (C-12.6)
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
        if not isinstance(exc, AccountsError | StorageError) and not is_storage_outage(exc):
            raise exc
        facts = exc if isinstance(exc, StorageQueryFailed) else getattr(exc, "orig", None)
        state, name = getattr(facts, "sqlstate", None), type(exc).__name__
        log = structlog.get_logger(__name__)  # per call (#2008)
        log.warning("trade_group_definition_read_unavailable", error=name, sqlstate=state)
        return problem("store_unavailable", "The trade-group definition store is unavailable.")

    @router.get("/trade-group-definitions")
    async def list_trade_group_definitions(
        request: Request, cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> Response:  # fmt: skip
        named = NamesSession(audit, auth, request)
        if isinstance(admitted := await admit(request, named), Response):
            return admitted
        principal, store, source = admitted
        now, after = int(clock().timestamp()), None
        if cursor is not None:
            after = _after(decode_cursor(cursor, _LIST, principal.user_id, (), now))
            if after is None:
                detail = "The cursor is malformed, expired or for another query."
                return problem("invalid_cursor", detail, status=400)
        try:
            found = await store.page(account_scope(principal), after=after, limit=limit + 1)
            shown = [domain.stored_definition(record) for record in found[:limit]]
        except Exception as exc:  # mapped, or raised as a defect
            return await refused(request, principal, named, exc)
        nxt, last = None, found[limit - 1].definition if len(found) > limit else None
        if last is not None:  # past the last one read: its id, then its stored name
            position, me = last.id.bytes + last.name.encode(), principal.user_id
            nxt = encode_cursor(_LIST, me, (), position, now)
        meta = {"next_cursor": nxt, "has_more": nxt is not None, "count": len(shown)}
        items = [definition_document(s, definition_readiness(s, source)) for s in shown]
        return JSONResponse({"items": items, "meta": meta})

    @router.get("/trade-group-definitions/{definitionId}")
    async def get_trade_group_definition(
        request: Request, definition_id: Annotated[uuid.UUID, Path(alias="definitionId")]
    ) -> Response:
        named = _OnDefinition(NamesSession(audit, auth, request), definition_id)
        if isinstance(admitted := await admit(request, named), Response):
            return admitted
        principal, store, source = admitted
        try:
            found = await store.get(account_scope(principal), definition_id)
            stored = None if found is None else domain.stored_definition(found)
        except Exception as exc:  # mapped, or raised as a defect
            return await refused(request, principal, named, exc)
        if stored is None:  # missing, deleted or with a member outside the grants: one 404
            return problem("not_found", "No such trade-group definition.")
        doc = definition_document(stored, definition_readiness(stored, source))
        return JSONResponse(doc, headers={"ETag": domain.definition_etag(stored)})

    return router
