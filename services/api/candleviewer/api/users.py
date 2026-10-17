"""`PUT /users/{userId}/roles` (E09-T03, QA #1648 defects 1-2).

Enforces `users:write`, SR-055 (never the acting user), the owner-floor guard at
API level, audits the change write-ahead inside the store's transaction (C-2.9),
and notifies the WS layer so a downgrade takes effect on live sockets.
`principal_resolver=None` / `store=None` fail closed with 501 (the fake backend;
the real backend wires both, #2492); the audit emitter and notifier are
required (TypeError at wiring time).

`GET /users/{userId}/account-access` (E42-T08 S9b, #2648): the user's live grants, owner only
(`users:read`, no step-up: a read). RBAC runs before any lookup, so a refused caller gets one 403
for an existing and a missing id (threat U25), audited naming the target. Its problem codes are
the contract's `x-error-codes`. `account_access=None` fails closed with 501.

`PUT /users/{userId}/account-access` (S9c): `users:write` and SR-055 refused as the GET refuses;
then the step-up, the closed body (at most 64 KiB and 256 grants, SR-040) and
`AccountAccessService.replace`, whose store refusals map to the design's codes. It answers with
the set the store read under its locks; unwired, 501.

`DELETE /users/{userId}` (E42-T04 S6, #965; `deleteUser`, the disable) runs, nothing read or
written before the last: `users:write`, then a self-target (both refusals audited before any
lookup: U25, SR-055), the step-up `users` (SR-025), the query (`purge=true` is E42-T10's: 400
until it serves it), then the change. `user_disable=None` fails closed with 501. In the deployed
app the path-gated `DANGEROUS_ROUTES` guard (`make_read_only_guard`) answers an un-elevated caller
first, so this order is the second line: it alone decides an elevated caller.
"""

from __future__ import annotations

import inspect
import re
import uuid
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Annotated, Any, Final, Protocol

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

from candleviewer.admin.account_access import AccountAccessService, GrantStore
from candleviewer.admin.errors import (
    LastOwnerError,
    LifecycleAuditUnavailableError,
    LifecycleForbiddenError,
    PositionsUnknownError,
    UserLifecycleError,
    UserNotFoundError,
)
from candleviewer.admin.user_disable import DisableResult
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.csrf import source_ip
from candleviewer.api.step_up import (
    _AuthLike,
    _bearer,
    _unauthenticated,
    require_elevation_for,
    require_session_elevation,
)
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.errors import AuthError
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.owner_floor import OwnerFloorError, assert_owner_floor
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.observability.context import current_request_id
from candleviewer.storage.errors import StorageQueryFailed, WriteAheadTimeout
from candleviewer.storage.repositories import account_access as aa
from candleviewer.storage.repositories.account_access import AccessGrant, AccessUserNotFoundError
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_SYSTEM_ROLES = frozenset({"owner", "manager", "viewer"})
_RETRY_AFTER_S = 5
_ACK = TypeAdapter(bool)  # `acknowledge_unknown_positions`, a query parameter
_Input = tuple[api.AccountAccessGrantInput, ...]
#: SR-040: the PUT's body bounds. Both answer 400 `validation_failed`: the operation declares no
#: 413, and the contract is not this slice's to change (C-6.1). 256 grants take about 20 KiB. The
#: contract has no `maxItems` yet; it is proposed in the #965 comment of 2026-10-17 10:40Z
#: (issuecomment-6232927455), which does not cover the 64 KiB cap: that one is this change's own.
_MAX_BODY_BYTES: Final = 64 * 1024
_MAX_GRANTS: Final = 256
_LENGTH: Final = re.compile(r"[0-9]{1,19}")  # a usable `Content-Length`, as `api/drawings.py`
#: The store's refusals, nothing changed (#2648 design (c).2); unknown and deleted alike.
_REFUSED: dict[type[Exception], tuple[ErrorCode, int, str]] = {
    aa.AccessSelfTargetError: (ErrorCode.FORBIDDEN, 403, "a caller's own grants cannot change"),
    aa.AccessUserNotFoundError: (ErrorCode.NOT_FOUND, 404, "user not found"),
    aa.AccessUnknownAccountError: (ErrorCode.NOT_FOUND, 404, "an exchange account was not found"),
    aa.AccessUserNotActiveError: (ErrorCode.CONFLICT, 409, "the user is not active"),
    aa.AccessBusyError: (ErrorCode.CONFLICT, 409, "the grants are being changed; retry"),
    aa.AccessPositionsUnknownError: (ErrorCode.POSITIONS_UNKNOWN, 409, "positions are unknown"),
    aa.AccessAuditUnavailableError: (ErrorCode.AUDIT_UNAVAILABLE, 503, "change not audited"),
}
_REFUSALS = tuple(_REFUSED)


def _refusal(exc: Exception) -> JSONResponse:
    """The answer for a store refusal, or for the nearest mapped class above it: a subclass of a
    refusal is answered as its parent, never as a 500."""
    return _registered(*next(_REFUSED[kind] for kind in type(exc).__mro__ if kind in _REFUSED))


class _ReplaceBody(BaseModel):
    """`setUserAccountAccess`'s body, closed at both levels (#2658): a freeze field, the cap,
    `can_trade`, `granted_by` or `user_id` is refused, as is an account named twice (I5) or a
    grant past the 256th (SR-040)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    grants: Annotated[_Input, Field(max_length=_MAX_GRANTS)]

    @field_validator("grants")
    @classmethod
    def _distinct(cls, grants: _Input) -> _Input:
        if len({g.exchange_account_id for g in grants}) != len(grants):
            raise ValueError("an exchange account is named twice")
        return grants


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class SnapshotResolver(Protocol):
    """Sync (test seams) or async (`SessionSnapshotResolver`, the deployed app, #2492)."""

    def resolve(
        self, request: Request
    ) -> PrincipalSnapshot | Awaitable[PrincipalSnapshot | None] | None: ...


class UserRoleStore(Protocol):
    async def get_roles(self, user_id: uuid.UUID) -> frozenset[str] | None: ...

    async def count_active_owners(self) -> int: ...

    async def apply_roles(
        self,
        user_id: uuid.UUID,
        roles: frozenset[str],
        *,
        actor: uuid.UUID,
        audit: Callable[[frozenset[str]], Awaitable[None]],
    ) -> bool:
        """Atomically (one transaction, owner rows locked) enforce the owner
        floor via `assert_owner_floor`, write `roles` granted by `actor`, then
        await `audit(roles read under lock)` before committing (C-2.9
        write-ahead). Raises `OwnerFloorError` or what `audit` raises, with
        nothing changed (or `WriteAheadTimeout`, #2510); False if no such user."""
        ...


class AccountAccessStore(GrantStore, Protocol):  # its writes go through `AccountAccessService`
    async def list_grants(self, user_id: uuid.UUID) -> list[AccessGrant]:
        """The user's live grants of live accounts. Raises `AccessUserNotFoundError` (missing or
        deleted user), `StorageQueryFailed` or the driver's `OSError` (database down)."""
        ...


class UserDisable(Protocol):
    """`admin.user_disable.UserDisableService`: `authorize` is its guard alone."""

    async def authorize(self, user_id: uuid.UUID, *, actor: PrincipalSnapshot) -> None: ...

    async def disable(
        self,
        user_id: uuid.UUID,
        *,
        actor: PrincipalSnapshot,
        acknowledge_unknown_positions: bool = False,
    ) -> DisableResult: ...


class PermissionChangeNotifier(Protocol):
    async def roles_changed(self, user_id: uuid.UUID) -> None: ...


class _AuditRefused(Exception):
    """The write-ahead audit record could not be written; the change rolled back."""


def _forbidden(reason: str) -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "type": "about:blank",
            "title": "Forbidden",
            "status": 403,
            "code": "forbidden",
            "reason": reason,
        },
        media_type="application/problem+json",
    )


def _registered(code: ErrorCode, status: int, detail: str) -> JSONResponse:
    """A problem for a code of `x-error-codes`: title and retryability come from the generated
    registry, so no other code can be answered."""
    meta = ERROR_META[code]
    body: dict[str, Any] = {
        "type": f"https://candleviewer.local/errors/{code.value}",
        "title": meta.title,
        "status": status,
        "code": code.value,
        "detail": detail,
    }
    headers: dict[str, str] = {}
    if meta.retryable:
        body["retry_after_seconds"] = _RETRY_AFTER_S
        headers["Retry-After"] = str(_RETRY_AFTER_S)
    return JSONResponse(body, status, headers, "application/problem+json")


def _problem(status: int, code: str, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "type": f"https://candleviewer.local/errors/{code}",
            "title": title,
            "status": status,
            "code": code,
            "detail": detail,
        },
        media_type="application/problem+json",
    )


def _lifecycle_problem(exc: UserLifecycleError) -> JSONResponse:
    """A refused lifecycle call as its `x-error-codes` problem, with a detail that names no id."""
    if isinstance(exc, LifecycleForbiddenError):
        return _forbidden(exc.reason)
    if isinstance(exc, UserNotFoundError):
        return _registered(ErrorCode.NOT_FOUND, 404, "user not found")
    if isinstance(exc, LastOwnerError):
        return _registered(ErrorCode.CONFLICT, 409, "the last active owner cannot be disabled")
    if isinstance(exc, PositionsUnknownError):
        unknown = f"open-position state is unavailable (source: {exc.source})"
        resend = "resend with acknowledge_unknown_positions=true"
        return _registered(ErrorCode.POSITIONS_UNKNOWN, 409, f"{unknown}; {resend}")
    if isinstance(exc, LifecycleAuditUnavailableError):
        detail = "the audit record could not be written; nothing changed"
        return _registered(ErrorCode.AUDIT_UNAVAILABLE, 503, detail)
    raise exc  # a refusal this route does not know is a defect: a 500, never a guess


def _flag(request: Request, name: str) -> bool | None:
    """The contract's boolean flag: absent is false; only `true` or `false`, once, else None."""
    values = request.query_params.getlist(name) or ["false"]
    return {"true": True, "false": False}.get(values[0]) if len(values) == 1 else None


class _NamesTarget:
    """`enforce` audits a denial without its target or the caller's session; this names the user
    whose grants were asked for, so a probe of ids leaves a trail, and the session, which is read
    only now, for a refusal."""

    def __init__(
        self,
        emitter: _Emitter,
        target: uuid.UUID,
        session: Callable[[], Awaitable[uuid.UUID | None]],
    ) -> None:
        self._emitter, self._target, self._session = emitter, target, session

    async def emit(self, action: str, **kwargs: Any) -> None:
        named = {"object_kind": "user", "object_id": str(self._target)}
        try:
            session = await self._session()
        except Exception as exc:  # the session store may be down: name no session, drop no record
            _log().warning("account access refusal names no session", error=type(exc).__name__)
            session = None
        await self._emitter.emit(action, **kwargs | named | {"session_id": session})


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


async def _read_capped(request: Request) -> bytes | None:
    """The body, or `None` past `_MAX_BODY_BYTES` (SR-040): a larger declared `Content-Length` is
    refused before any read, and a stream is cut off as soon as it passes the cap."""
    declared = request.headers.get("content-length", "")
    if _LENGTH.fullmatch(declared) and int(declared) > _MAX_BODY_BYTES:
        return None
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > _MAX_BODY_BYTES:
            return None
    return bytes(raw)


def _grant_json(grant: AccessGrant) -> dict[str, Any]:
    """One `AccountAccessGrant` (`granted_by` left out once its user is gone; no `granted_at`)."""
    shown = api.AccountAccessGrant.model_validate(
        {
            "exchange_account_id": grant.exchange_account_id,
            "level": grant.level,
            "account_label": grant.account_label,
            "environment": grant.environment,
            "granted_by": grant.granted_by,
        }
    )
    return shown.model_dump(mode="json", exclude_none=True)


async def _elevated(auth: _AuthLike | None, request: Request) -> JSONResponse | uuid.UUID:
    """SR-025 after RBAC and SR-055, as `put_user_roles`: the elevated session's id, which the
    change's audit records name (C-2.9), else the problem."""
    if auth is None or not auth.step_up_is_active or not auth.sessions_is_active:
        return _registered(ErrorCode.NOT_IMPLEMENTED, 501, "step-up is not wired")
    try:
        record: SessionRecord = await auth.sessions.authenticate_access_token(
            _bearer(request) or ""
        )
    except AuthError:
        return _registered(ErrorCode.UNAUTHENTICATED, 401, "authentication required")
    gate = await require_elevation_for(auth, str(record.id), "users")
    return record.id if gate is None else gate


async def _audit(
    emitter: _Emitter,
    action: str,
    principal: PrincipalSnapshot,
    user_id: uuid.UUID,
    reason: str,
    *,
    before: frozenset[str],
    after: frozenset[str],
) -> None:
    """C-12.8: every record carries the role set before and after (for a
    denial, `after` is the *requested* set that was refused)."""
    await emitter.emit(
        action,
        actor_label=str(principal.user_id),
        actor_user_id=principal.user_id,
        object_kind="user",
        object_id=str(user_id),
        reason=reason,
        before_state={"roles": sorted(before)},
        after_state={"roles": sorted(after)},
    )


def make_users_router(
    store: UserRoleStore | None,
    emitter: _Emitter,
    principal_resolver: SnapshotResolver | None,
    notifier: PermissionChangeNotifier,
    *,
    auth: _AuthLike | None = None,
    account_access: AccountAccessStore | None = None,
    access_service: AccountAccessService | None = None,
    user_disable: UserDisable | None = None,
) -> APIRouter:
    """`emitter` and `notifier` are mandatory: a role change without an
    audit record (C-2.9) or without a live-socket re-evaluation is refused
    at wiring time, not silently skipped."""
    if emitter is None or notifier is None:
        raise TypeError("make_users_router: audit emitter and notifier are required")
    router = APIRouter()

    async def session_of(request: Request) -> uuid.UUID | None:
        """The session behind the bearer token, as the audit record of a refusal names it. A
        read-only peek: it authorises nothing, and `None` when there is no session to name."""
        token = _bearer(request)
        if auth is None or token is None or not auth.sessions_is_active:
            return None
        found: SessionRecord | None = await auth.sessions.peek_access_token(token)
        return None if found is None else found.id

    @router.put("/users/{userId}/roles")
    async def put_user_roles(
        request: Request, user_id: Annotated[uuid.UUID, Path(alias="userId")]
    ) -> JSONResponse:
        if principal_resolver is None or store is None:
            return _problem(
                501, "not_implemented", "Not implemented", "no principal resolver/store wired"
            )
        got = principal_resolver.resolve(request)
        principal = await got if inspect.isawaitable(got) else got
        if principal is None:
            return _problem(
                401, "unauthorized", "Unauthorized", "no verified session for this request"
            )
        try:
            await enforce(principal, Permission.USERS_WRITE, scope=Scope.NONE, emitter=emitter)
        except ForbiddenError as exc:
            return _forbidden(exc.deny.reason.value)
        if user_id == principal.user_id:  # SR-055: never the acting user, step-up or not
            await emitter.emit(
                "rbac.denied",
                actor_label=str(principal.user_id),
                actor_user_id=principal.user_id,
                object_kind="user",
                object_id=str(user_id),
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason="self_target",
            )
            return _forbidden("self_target")
        # SR-025: step-up after authn + RBAC, before any mutation. Fail closed
        # when the step-up service is not wired. Denial is audited by B16.
        if auth is None or not auth.step_up_is_active or not auth.sessions_is_active:
            return _problem(503, "service_unavailable", "Service unavailable", "step-up not wired")
        token = _bearer(request)
        if token is None:
            return _problem(401, "unauthorized", "Unauthorized", "authentication required")
        try:
            record = await auth.sessions.authenticate_access_token(token)
        except AuthError:
            return _problem(401, "unauthorized", "Unauthorized", "authentication required")
        gate = await require_elevation_for(auth, str(record.id), "users")
        if gate is not None:
            return gate
        try:
            body = await request.json()
        except ValueError:
            return _problem(400, "bad_request", "Bad request", "body must be JSON")
        roles_raw = body.get("roles") if isinstance(body, dict) else None
        if (
            not isinstance(roles_raw, list)
            or not roles_raw
            or not all(isinstance(r, str) and r in _SYSTEM_ROLES for r in roles_raw)
        ):
            return _problem(
                400, "bad_request", "Bad request", "roles must be a non-empty list of role names"
            )
        new_roles = frozenset(roles_raw)
        current = await store.get_roles(user_id)
        if current is None:
            return _problem(404, "not_found", "Not found", "user not found")

        async def write_ahead(before: frozenset[str]) -> None:
            """C-2.9: written inside the store's transaction, before commit, with the
            role set read under lock; a failed write rolls the change back."""
            try:
                for action, changed in (
                    ("roles.grant", sorted(new_roles - before)),
                    ("roles.revoke", sorted(before - new_roles)),
                ):
                    if changed:
                        await _audit(
                            emitter,
                            action,
                            principal,
                            user_id,
                            ",".join(changed),
                            before=before,
                            after=new_roles,
                        )
            except (AuditError, RuntimeError) as exc:  # RuntimeError: audit not started
                raise _AuditRefused from exc

        # Endpoint-level owner floor (defence in depth; `apply_roles` re-checks
        # atomically under lock, so a concurrent demotion still cannot slip by).
        try:
            assert_owner_floor(
                current_roles=current,
                new_roles=new_roles,
                active_owner_count=await store.count_active_owners(),
            )
            found = await store.apply_roles(
                user_id, new_roles, actor=principal.user_id, audit=write_ahead
            )
        except OwnerFloorError:
            await _audit(
                emitter,
                "rbac.denied",
                principal,
                user_id,
                "owner_floor",
                before=current,
                after=new_roles,
            )
            return _problem(409, "conflict", "Conflict", "the last active owner cannot be demoted")
        except (_AuditRefused, WriteAheadTimeout):  # the store bounds the hook (#2510)
            return _problem(503, "service_unavailable", "Service unavailable", "audit unavailable")
        if not found:
            return _problem(404, "not_found", "Not found", "user not found")
        await notifier.roles_changed(user_id)
        return JSONResponse(
            status_code=200, content={"id": str(user_id), "roles": sorted(new_roles)}
        )

    @router.get("/users/{userId}/account-access")
    async def list_user_account_access(
        request: Request, user_id: Annotated[uuid.UUID, Path(alias="userId")]
    ) -> JSONResponse:
        if principal_resolver is None or account_access is None:
            return _problem(
                501, "not_implemented", "Not implemented", "no principal resolver/store wired"
            )
        got = principal_resolver.resolve(request)
        principal = await got if inspect.isawaitable(got) else got
        if principal is None:
            return _registered(
                ErrorCode.UNAUTHENTICATED, 401, "no verified session for this request"
            )
        correlation = current_request_id()  # bound by `CorrelationMiddleware`: a UUID if present
        try:  # before any lookup: the same 403 for an id that exists and one that does not
            await enforce(
                principal,
                Permission.USERS_READ,
                scope=Scope.NONE,
                emitter=_NamesTarget(emitter, user_id, partial(session_of, request)),
                actor_ip=source_ip(request.scope),
                request_id=uuid.UUID(correlation) if correlation else None,
            )
        except ForbiddenError as exc:
            return _forbidden(exc.deny.reason.value)
        except (AuditError, RuntimeError) as exc:  # RuntimeError: audit not started
            _log().warning(
                "account access refusal not audited",
                error=type(exc).__name__,
                target_user_id=str(user_id),
            )
            return _registered(ErrorCode.AUDIT_UNAVAILABLE, 503, "the refusal could not be audited")
        try:
            grants = await account_access.list_grants(user_id)
        except AccessUserNotFoundError:  # a deleted user and a missing one answer alike
            return _registered(ErrorCode.NOT_FOUND, 404, "user not found")
        except (StorageQueryFailed, OSError) as exc:
            _log().error(
                "account access read failed",
                error=type(exc).__name__,
                sqlstate=exc.sqlstate if isinstance(exc, StorageQueryFailed) else None,
                target_user_id=str(user_id),
            )
            return _registered(
                ErrorCode.STORE_UNAVAILABLE, 503, "the account access store is unavailable"
            )
        return JSONResponse({"items": [_grant_json(grant) for grant in grants]})

    @router.put("/users/{userId}/account-access")
    async def set_user_account_access(
        request: Request, user_id: Annotated[uuid.UUID, Path(alias="userId")]
    ) -> JSONResponse:
        if principal_resolver is None or access_service is None:
            return _registered(ErrorCode.NOT_IMPLEMENTED, 501, "no resolver or service wired")
        got = principal_resolver.resolve(request)
        principal = await got if inspect.isawaitable(got) else got
        if principal is None:
            return _registered(ErrorCode.UNAUTHENTICATED, 401, "no verified session")
        ip, rid = source_ip(request.scope), current_request_id()  # a UUID4, as the GET reads it
        who: dict[str, Any] = {"actor_ip": ip, "request_id": uuid.UUID(rid) if rid else None}
        denials = _NamesTarget(emitter, user_id, partial(session_of, request))
        try:  # before any lookup, as the GET: one 403 for an existing and a missing id (U25)
            await enforce(principal, Permission.USERS_WRITE, emitter=denials, **who)
            if user_id == principal.user_id:  # SR-055: never the acting user, step-up or not
                await denials.emit(
                    "rbac.denied",
                    actor_label=str(principal.user_id),
                    actor_user_id=principal.user_id,
                    outcome=AuditOutcome.DENIED,
                    severity=Severity.WARNING,
                    reason="self_target",
                    **who,
                )
                return _forbidden("self_target")
        except ForbiddenError as exc:
            return _forbidden(exc.deny.reason.value)
        except (AuditError, RuntimeError) as exc:  # RuntimeError: audit not started (F6)
            _log().warning("account access refusal not audited", error=type(exc).__name__)
            return _registered(ErrorCode.AUDIT_UNAVAILABLE, 503, "the refusal could not be audited")
        if isinstance(session := await _elevated(auth, request), JSONResponse):
            return session
        if (raw := await _read_capped(request)) is None:  # never held whole, nor echoed
            return _registered(
                ErrorCode.VALIDATION_FAILED, 400, f"the body exceeds {_MAX_BODY_BYTES} bytes"
            )
        try:
            body = _ReplaceBody.model_validate_json(raw)
            ack = _ACK.validate_python(
                request.query_params.get("acknowledge_unknown_positions", "false")
            )
        except ValidationError:  # nothing of the input is echoed
            return _registered(
                ErrorCode.VALIDATION_FAILED, 400, "the request does not match its schema"
            )
        try:
            change = await access_service.replace(
                user_id,
                {g.exchange_account_id: g.level for g in body.grants},
                actor_user_id=principal.user_id,
                acknowledge_unknown_positions=ack,
                actor_ip=ip,
                session_id=session,
            )
        except _REFUSALS as exc:
            return _refusal(exc)
        except (StorageQueryFailed, OSError) as exc:
            _log().error(
                "account access write failed",
                error=type(exc).__name__,
                sqlstate=exc.sqlstate if isinstance(exc, StorageQueryFailed) else None,
                target_user_id=str(user_id),
            )
            return _registered(
                ErrorCode.STORE_UNAVAILABLE, 503, "the account access store is unavailable"
            )
        return JSONResponse({"items": [_grant_json(grant) for grant in change.granted]})

    async def users_elevation(request: Request) -> JSONResponse | None:
        """SR-025: `None` when the session holds a live `users` elevation, else the answer."""
        if auth is None or not auth.sessions_is_active:  # the fake backend: nothing authenticates
            return _registered(ErrorCode.NOT_IMPLEMENTED, 501, "no session service wired")
        try:  # no bearer is an unknown token: the same refusal
            record = await auth.sessions.authenticate_access_token(_bearer(request) or "")
        except AuthError:
            return _unauthenticated()
        return await require_session_elevation(auth, record.id, "users")  # 503: no step-up wired

    @router.delete("/users/{userId}")  # nosem: audit-write-required reason=audited-below-the-handler-in-UserDisableService-users.disable-ahead-and-rbac.denied-refusals-#965 owner=@CandleViewer/security review=2027-03-25  # noqa: E501 -- suppression metadata must stay on the matched line  # fmt: skip
    async def delete_user(
        request: Request, user_id: Annotated[uuid.UUID, Path(alias="userId")]
    ) -> Response:
        if principal_resolver is None or user_disable is None:
            return _problem(
                501, "not_implemented", "Not implemented", "no principal resolver/service wired"
            )
        got = principal_resolver.resolve(request)
        principal = await got if inspect.isawaitable(got) else got
        if principal is None:
            return _unauthenticated()
        try:  # before the step-up and any lookup: one 403 for an existing and a missing id (U25)
            await user_disable.authorize(user_id, actor=principal)
        except UserLifecycleError as exc:
            return _lifecycle_problem(exc)
        if (gate := await users_elevation(request)) is not None:
            return gate
        acknowledged = _flag(request, "acknowledge_unknown_positions")
        purge = _flag(request, "purge")
        if acknowledged is None or purge is None or purge:  # purge=true is E42-T10's (S14)
            detail = "purge is not available yet"
            if not purge:
                detail = "acknowledge_unknown_positions and purge are each true or false"
            return _registered(ErrorCode.VALIDATION_FAILED, 400, detail)
        try:
            await user_disable.disable(
                user_id, actor=principal, acknowledge_unknown_positions=acknowledged
            )
        except UserLifecycleError as exc:
            return _lifecycle_problem(exc)
        except Exception as exc:  # a store outage is a 503; anything else is a defect (a 500)
            if not is_storage_outage(exc):
                raise
            _log().error(
                "user disable store unavailable",
                error=type(exc).__name__,
                target_user_id=str(user_id),
            )
            return _registered(ErrorCode.STORE_UNAVAILABLE, 503, "the user store is unavailable")
        return Response(status_code=204)

    return router
