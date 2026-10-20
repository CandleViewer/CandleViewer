"""`PUT /users/{userId}/roles` (E09-T03, QA #1648 defects 1-2).

Enforces `users:write`, SR-055 (never the acting user), the owner-floor guard at
API level, audits the change write-ahead inside the store's transaction (C-2.9),
and notifies the WS layer so a downgrade takes effect on live sockets. A refusal
whose record cannot be written is 503 `audit_unavailable`; a push that fails after
the commit is counted and logged (`roles_push`, R7), never a 500.
`principal_resolver=None` / `store=None` fail closed with 501 (the fake backend;
the real backend wires both, #2492); the audit emitter and notifier are
required (TypeError at wiring time).

`GET /users/{userId}/account-access` (E42-T08 S9b, #2648): the user's live grants, owner only
(`users:read`, no step-up: a read). RBAC runs before any lookup, so a refused caller gets one 403
for an existing and a missing id (threat U25), audited naming the target. Its problem codes are
the contract's `x-error-codes`. `account_access=None` fails closed with 501.

`PUT /users/{userId}/account-access` (S9c): `users:write` and SR-055 refused as the GET refuses;
then the step-up, `acknowledge_unknown_positions` (`true` or `false`, once, as the DELETE reads
it), the closed body (at most 64 KiB and 256 grants, SR-040) and `AccountAccessService.replace`,
whose store refusals map to the design's codes. It answers with the set the store read under its
locks; unwired, 501 (sessions wired without a step-up service, 503). A caller RBAC refuses is
refused, not challenged, inside the handler only: in the deployed app the path-gated
`DANGEROUS_ROUTES` guard (`make_read_only_guard`) challenges every un-elevated session first, a
forbidden Manager or Viewer included and with no `rbac.denied`, so this order is the second line:
it alone decides an elevated caller.

`DELETE /users/{userId}` (E42-T04 S6, #965; `deleteUser`, the disable) runs, nothing read or
written before the last: `users:write`, then a self-target (both refusals audited before any
lookup: U25, SR-055), the step-up `users` (SR-025), the query (an undeclared key is 422, S7),
then the change; with `purge=true` the purge's schedule follows it (E42-T10, `_schedule_purge`).
`user_disable=None` fails closed with 501; while no purge reaper runs (none wired, or stopped),
`purge=true` fails closed with 503 `purge_unavailable`, before anything changes. In the deployed
app the path-gated `DANGEROUS_ROUTES` guard
(`make_read_only_guard`) answers an un-elevated caller first, so this order is the second line: it
alone decides an elevated caller.

E42-T09 (#2649), `make_user_admin_router`: `GET /users/{userId}` answers the `User` and an
`ETag` over the whole representation, roles included (never `password_hash`). `PATCH` runs, nothing
read before the change but its own query and body: `users:write` (an audited 403 before any
lookup, U25), an undeclared query key (422, SR-026, as the DELETE), the body (O3 and R6 refusals
are 400), a self-target of `roles` or `status` (an audited 403, SR-055), the step-up `users`
(SR-025), then the user read and its `If-Match` (412), judged again under the change's own lock.
A disable is `UserDisableService`'s whole cascade with `acknowledge_unknown_positions` as the
DELETE reads it, and changes nothing else; every other change is one transaction of the user admin
store under the owner lock (R7), written ahead as `users.enable`, `users.update`, `roles.grant`
and `roles.revoke`, its role push counted after the commit. `GET /users/{userId}/sessions` lists
the user's live sessions as `listMySessions` does (no token material);
`DELETE /users/{userId}/sessions/{sessionId}` addresses only a live session of that user (404
otherwise, IDOR), writes the acting Owner's `users.session_revoked`, then records B16 REVOKE, whose
action writes the one `auth.session_revoked` (R5), both ahead of the change, then revokes the row,
which closes its sockets 4401; a session that ended in between is 404. No runtime flag gates the
lock, the step-up or the audit (C-4.14).
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from functools import partial
from typing import Annotated, Any, Final, Literal, Protocol

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from candleviewer.admin.account_access import AccountAccessService, GrantStore
from candleviewer.admin.errors import (
    LastOwnerError,
    LifecycleAuditUnavailableError,
    LifecycleForbiddenError,
    PositionsUnknownError,
    UserLifecycleError,
    UserNotFoundError,
    UserVersionConflictError,
)
from candleviewer.admin.lifecycle_metrics import user_lifecycle_steps_total
from candleviewer.admin.user_disable import DisableResult
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.csrf import source_ip
from candleviewer.api.query_allowlist import undeclared_query_refusal
from candleviewer.api.sessions import _view_json
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
from candleviewer.auth.session_chart import SessionChartError
from candleviewer.observability.context import current_request_id
from candleviewer.storage.errors import StorageQueryFailed, WriteAheadTimeout
from candleviewer.storage.repositories import account_access as aa
from candleviewer.storage.repositories.user_lifecycle import (
    UserPatch,
    UserPrecondition,
    UserUpdate,
    UserUpdateAudit,
)
from candleviewer.storage.repositories.user_purge import (
    PurgeAuditUnavailableError,
    PurgeSchedule,
    PurgeUnavailableError,
    PurgeUserNotDisabledError,
    PurgeUserNotFoundError,
)
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_SYSTEM_ROLES = frozenset({"owner", "manager", "viewer"})
_RETRY_AFTER_S = 5
#: SR-026 for an owner route (S7): `deleteUser`'s declared query parameters (22-api-openapi.yaml).
DELETE_USER_QUERY = frozenset({"acknowledge_unknown_positions", "purge"})
_Input = tuple[api.AccountAccessGrantInput, ...]
#: SR-040: the PUT's body bounds. Both answer 400 `validation_failed`: the operation declares no
#: 413, and the contract is not this slice's to change (C-6.1). 256 grants take about 20 KiB. The
#: contract has no `maxItems` yet; it is proposed in the #965 comment of 2026-10-17 10:40Z
#: (issuecomment-6232927455), which does not cover the 64 KiB cap: that one is this change's own.
_MAX_BODY_BYTES: Final = 64 * 1024
_MAX_GRANTS: Final = 256
_LENGTH: Final = re.compile(r"[0-9]{1,19}")  # a usable `Content-Length`, as `api/drawings.py`
#: The tail of every `positions_unknown` detail, the PUT's (`_REFUSED`) and the DELETE's
#: (`_lifecycle_problem`): how a client acknowledges that the open-position state is unknown.
_RESEND_ACKNOWLEDGED: Final = "resend with acknowledge_unknown_positions=true"
#: The detail of every write-ahead refusal (C-2.9): the change rolled back.
_NOT_AUDITED: Final = "the audit record could not be written; nothing changed"
_LAST_OWNER: Final = "the last active owner cannot be demoted"
#: The store's refusals, nothing changed (#2648 design (c).2); unknown and deleted alike.
_REFUSED: dict[type[Exception], tuple[ErrorCode, int, str]] = {
    aa.AccessSelfTargetError: (ErrorCode.FORBIDDEN, 403, "a caller's own grants cannot change"),
    aa.AccessUserNotFoundError: (ErrorCode.NOT_FOUND, 404, "user not found"),
    aa.AccessUnknownAccountError: (ErrorCode.NOT_FOUND, 404, "an exchange account was not found"),
    aa.AccessUserNotActiveError: (ErrorCode.CONFLICT, 409, "the user is not active"),
    aa.AccessBusyError: (ErrorCode.CONFLICT, 409, "the grants are being changed; retry"),
    aa.AccessPositionsUnknownError: (
        ErrorCode.POSITIONS_UNKNOWN,
        409,
        f"open-position state is unavailable; {_RESEND_ACKNOWLEDGED}",
    ),
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

    async def get_status(self, user_id: uuid.UUID) -> str | None: ...

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
    async def list_grants(self, user_id: uuid.UUID) -> list[aa.AccessGrant]:
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
        precondition: UserPrecondition | None = None,
    ) -> DisableResult: ...


class UserPurge(Protocol):
    """`UsersPurgeTask` (E42-T10 S14): `running` while its reaper runs; `schedule` puts a disabled
    user's purge 90 days out on the injected clock, `users.delete` written ahead, a repeat keeping
    the first date, and refuses with `PurgeUnavailableError` once the reaper has stopped."""

    @property
    def running(self) -> bool: ...

    async def schedule(
        self,
        user_id: uuid.UUID,
        *,
        actor_user_id: uuid.UUID,
        request_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
    ) -> PurgeSchedule: ...


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
        return _registered(ErrorCode.POSITIONS_UNKNOWN, 409, f"{unknown}; {_RESEND_ACKNOWLEDGED}")
    if isinstance(exc, LifecycleAuditUnavailableError):
        return _registered(ErrorCode.AUDIT_UNAVAILABLE, 503, _NOT_AUDITED)
    if isinstance(exc, UserVersionConflictError):  # only a PATCH passes a precondition
        return _registered(ErrorCode.VERSION_CONFLICT, 412, _STALE)
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


def _grant_json(grant: aa.AccessGrant) -> dict[str, Any]:
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


async def _session_of(auth: _AuthLike | None, request: Request) -> uuid.UUID | None:
    """The session behind the bearer token, as the audit record of a refusal names it. A
    read-only peek: it authorises nothing, and `None` when there is no session to name."""
    token = _bearer(request)
    if auth is None or token is None or not auth.sessions_is_active:
        return None
    found: SessionRecord | None = await auth.sessions.peek_access_token(token)
    return None if found is None else found.id


async def _elevated(auth: _AuthLike | None, request: Request) -> JSONResponse | uuid.UUID:
    """SR-025, for a handler that has already decided RBAC and the self-target: the id of the
    session holding a live `users` elevation, which the change's audit records name (C-2.9), else
    the answer. No session service is 501 (the fake backend: nothing authenticates); sessions
    without a step-up service are a wiring fault, 503 as `require_session_elevation` answers it."""
    if auth is None or not auth.sessions_is_active:
        return _registered(ErrorCode.NOT_IMPLEMENTED, 501, "no session service wired")
    try:  # no bearer is an unknown token: the same refusal
        record: SessionRecord = await auth.sessions.authenticate_access_token(
            _bearer(request) or ""
        )
    except AuthError:
        return _unauthenticated()
    gate = await require_session_elevation(auth, record.id, "users")  # 503: no step-up wired
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


#: R7: the `step` of `cv_user_lifecycle_steps_total` for the push of a committed role change.
ROLES_PUSH_STEP: Final = "roles_push"


def _roles_pushed(
    user_id: uuid.UUID, outcome: Literal["ok", "failed"], error: str | None = None
) -> None:
    """One count and one line per push of a committed role change (R7); `failed` raises the
    `UserLifecycleStepFailed` ticket."""
    user_lifecycle_steps_total.labels(step=ROLES_PUSH_STEP, outcome=outcome).inc()
    (_log().error if outcome == "failed" else _log().info)(
        "users.update.step",
        step=ROLES_PUSH_STEP,
        outcome=outcome,
        error=error,
        target_user_id=str(user_id),
        request_id=current_request_id(),
    )


async def _push_roles(notifier: PermissionChangeNotifier, user_id: uuid.UUID) -> None:
    """After the commit (R7): the user's live sockets are re-evaluated (23 section 9.5). A failure
    is counted and logged, never rolled back and never the answer to a committed change."""
    try:
        await notifier.roles_changed(user_id)
    except Exception as exc:  # isolated: the change is committed
        _roles_pushed(user_id, "failed", type(exc).__name__)
    else:
        _roles_pushed(user_id, "ok")


async def _schedule_purge(
    purge: UserPurge, user_id: uuid.UUID, actor: uuid.UUID, session: uuid.UUID
) -> Response:
    """E42-T10 S14, once the disable has committed: the purge, `users.delete` ahead (R5), naming
    the session that stepped up. The disable is its own audited change and stays if this step is
    refused, as the refusal says; a retry is the disable's no-op (AC5), then this step."""
    rid = current_request_id()  # bound by `CorrelationMiddleware`: a UUID if present
    unscheduled = "the user is disabled, but its purge was not scheduled: "
    try:
        scheduled = await purge.schedule(
            user_id,
            actor_user_id=actor,
            request_id=uuid.UUID(rid) if rid else None,
            session_id=session,
        )
    except PurgeUserNotFoundError:
        return _registered(ErrorCode.NOT_FOUND, 404, "user not found")
    except PurgeUserNotDisabledError:  # a re-enable won the race: nothing scheduled
        return _registered(ErrorCode.CONFLICT, 409, "the user is no longer disabled; no purge")
    except PurgeAuditUnavailableError:
        detail = unscheduled + "the audit record could not be written; retry"
        return _registered(ErrorCode.AUDIT_UNAVAILABLE, 503, detail)
    except PurgeUnavailableError:  # the reaper stopped after the check (a shutdown)
        detail = unscheduled + "no purge reaper is running; retry"
        return _registered(ErrorCode.PURGE_UNAVAILABLE, 503, detail)
    except Exception as exc:  # a store outage is a 503; anything else is a defect (a 500)
        if not is_storage_outage(exc):
            raise
        _log().error(
            "user purge store unavailable", error=type(exc).__name__, target_user_id=str(user_id)
        )
        return _registered(ErrorCode.STORE_UNAVAILABLE, 503, "the user store is unavailable")
    _log().info(
        "user purge scheduled",
        target_user_id=str(user_id),
        changed=scheduled.changed,
        request_id=rid,
    )
    return Response(status_code=204)


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
    user_purge: UserPurge | None = None,
) -> APIRouter:
    """`emitter` and `notifier` are mandatory: a role change without an
    audit record (C-2.9) or without a live-socket re-evaluation is refused
    at wiring time, not silently skipped."""
    if emitter is None or notifier is None:
        raise TypeError("make_users_router: audit emitter and notifier are required")
    router = APIRouter()
    session_of = partial(_session_of, auth)

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
            return _unauthenticated()  # the registry's 401 code (AD-F24)
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
            return _unauthenticated()
        try:
            record = await auth.sessions.authenticate_access_token(token)
        except AuthError:
            return _unauthenticated()
        gate = await require_elevation_for(auth, str(record.id), "users")
        if gate is not None:
            return gate
        try:
            body = await request.json()
        except ValueError:
            return _registered(ErrorCode.VALIDATION_FAILED, 400, "body must be JSON")
        roles_raw = body.get("roles") if isinstance(body, dict) else None
        if (
            not isinstance(roles_raw, list)
            or not roles_raw
            or not all(isinstance(r, str) and r in _SYSTEM_ROLES for r in roles_raw)
        ):
            detail = "roles must be a non-empty list of role names"
            return _registered(ErrorCode.VALIDATION_FAILED, 400, detail)
        new_roles = frozenset(roles_raw)
        current = await store.get_roles(user_id)
        if current is None:
            return _registered(ErrorCode.NOT_FOUND, 404, "user not found")

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
        # atomically under lock, so a concurrent demotion still cannot slip by). As the
        # store's `counted_roles`, a target that is not active holds no counted owner grant
        # (#2649): a disabled owner can be demoted while one other owner is active.
        try:
            counted = current if await store.get_status(user_id) == "active" else frozenset()
            assert_owner_floor(
                current_roles=counted,
                new_roles=new_roles,
                active_owner_count=await store.count_active_owners(),
            )
            found = await store.apply_roles(
                user_id, new_roles, actor=principal.user_id, audit=write_ahead
            )
        except OwnerFloorError:
            try:  # the refusal's record (UL-F13); unwritable, the answer is AC8's 503
                await _audit(
                    emitter,
                    "rbac.denied",
                    principal,
                    user_id,
                    "owner_floor",
                    before=current,
                    after=new_roles,
                )
            except (AuditError, RuntimeError):  # RuntimeError: audit not started
                return _registered(ErrorCode.AUDIT_UNAVAILABLE, 503, _NOT_AUDITED)
            return _registered(ErrorCode.CONFLICT, 409, _LAST_OWNER)
        except (_AuditRefused, WriteAheadTimeout):  # the store bounds the hook (#2510)
            return _registered(ErrorCode.AUDIT_UNAVAILABLE, 503, _NOT_AUDITED)
        if not found:
            return _registered(ErrorCode.NOT_FOUND, 404, "user not found")
        await _push_roles(notifier, user_id)  # committed: a failed push is no 500 (R7)
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
        except aa.AccessUserNotFoundError:  # a deleted user and a missing one answer alike
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
        if (acknowledged := _flag(request, "acknowledge_unknown_positions")) is None:
            detail = "acknowledge_unknown_positions is true or false, given once"
            return _registered(ErrorCode.VALIDATION_FAILED, 400, detail)
        if (raw := await _read_capped(request)) is None:  # never held whole, nor echoed
            return _registered(
                ErrorCode.VALIDATION_FAILED, 400, f"the body exceeds {_MAX_BODY_BYTES} bytes"
            )
        try:
            body = _ReplaceBody.model_validate_json(raw)
        except ValidationError:  # nothing of the input is echoed
            return _registered(
                ErrorCode.VALIDATION_FAILED, 400, "the request does not match its schema"
            )
        try:
            change = await access_service.replace(
                user_id,
                {g.exchange_account_id: g.level for g in body.grants},
                actor_user_id=principal.user_id,
                acknowledge_unknown_positions=acknowledged,
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
        if isinstance(gate := await _elevated(auth, request), JSONResponse):
            return gate
        refusal = undeclared_query_refusal(request, DELETE_USER_QUERY, self_service=False)
        if refusal is not None:  # the names, before any value is read
            return refusal
        acknowledged = _flag(request, "acknowledge_unknown_positions")
        purge = _flag(request, "purge")
        if acknowledged is None or purge is None:
            detail = "acknowledge_unknown_positions and purge are each true or false"
            return _registered(ErrorCode.VALIDATION_FAILED, 400, detail)
        if purge and (user_purge is None or not user_purge.running):  # E42-T10, UL4-D1
            detail = "no purge reaper is running; nothing was changed"
            return _registered(ErrorCode.PURGE_UNAVAILABLE, 503, detail)
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
        if purge and user_purge is not None:  # E42-T10 S14: then the purge, 90 days out
            return await _schedule_purge(user_purge, user_id, principal.user_id, gate)
        return Response(status_code=204)

    return router


# -- E42-T09 (#2649): the user read model, PATCH, and the admin view of a user's sessions --------

#: `sessions.revoked_reason` and the B16 `REVOKE` reason of an Owner's revoke: `set_revoke_admin`'s
#: own (INV-B16-b), and a reason the revocation counter knows.
ADMIN_REVOKE_REASON: Final = "admin"
#: `updateUser`'s query parameter (22-api-openapi.yaml): the disable's acknowledgement.
_ACKNOWLEDGE: Final = "acknowledge_unknown_positions"
#: SR-026, as for `deleteUser` (S7): `updateUser`'s declared query parameters, its only one.
UPDATE_USER_QUERY: Final = frozenset({_ACKNOWLEDGE})
_NO_SESSION: Final = "no such session of this user"
#: The `UpdateUserRequest` fields a 400 may name: the contract's own, never a client's key.
_PATCH_FIELDS: Final = frozenset({"display_name", "status", "roles", "mfa_required"})
#: Fields whose `null` the generated model accepts but the contract does not (no `null` type).
_NOT_NULL: Final = ("status", "roles", "mfa_required")
#: An `If-Match` that can match no representation: `*`, a list, two header lines.
_NEVER_MATCHES: Final = '"never-matches"'
_STALE: Final = "the user changed since it was read"


class UserAdminStore(Protocol):
    """`storage.repositories.users_sqlalchemy.SqlAlchemyUserAdminStore`."""

    async def get_user(self, user_id: uuid.UUID) -> dict[str, Any] | None: ...

    async def update_user(
        self,
        user_id: uuid.UUID,
        patch: UserPatch,
        *,
        actor: uuid.UUID,
        check: UserPrecondition,
        audit: UserUpdateAudit,
    ) -> UserUpdate | None:
        """One transaction under the user-row and owner locks: `check` on the representation read
        under them, the change, the owner floor, then `audit` ahead of the commit. Raises what
        `check`, the floor or `audit` raises, or `WriteAheadTimeout`, with nothing changed;
        `None` if no such user."""
        ...


class _Stale(Exception):
    """The `If-Match` names another version than the one read under the lock (412)."""


class _StatusRefused(Exception):
    """R6: the patch cannot move the user from the status read under the lock (400)."""


def representation(user: Mapping[str, Any]) -> dict[str, Any]:
    """The `User` as `getUser` answers it: the contract's fields only, so a column the read model
    grows (never `password_hash`, which it does not select) cannot leak through."""
    return api.User.model_validate(dict(user)).model_dump(mode="json")


def user_etag(shown: Mapping[str, Any]) -> str:
    """A strong `ETag` over the whole representation, roles included (R4, UL3-T1): any change to
    a returned field, a role change among them, makes an earlier tag stale."""
    canonical = {**shown, "roles": sorted(shown.get("roles") or ())}
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()
    return f'"{digest[:32]}"'


def _if_match(request: Request) -> str | None:
    """`If-Match`, one tag, quoted or `W/`-prefixed; absent is `None` (last write wins). Anything
    that is not one tag can match no version (412)."""
    lines = request.headers.getlist("if-match")
    if not lines:
        return None
    value = lines[0].strip().removeprefix("W/")
    if len(lines) > 1 or "," in value or value in ("*", '"*"'):
        return _NEVER_MATCHES
    return value if value.startswith('"') else f'"{value}"'


def _status_refusal(current: str, requested: str | None) -> str | None:
    """R6 (UL-F3): only a `disabled` user is enabled, so no PATCH activates an unredeemed invite
    or lifts a lock; a disable leaves any status (an invited user's invite is revoked)."""
    if requested == "active" and current not in ("active", "disabled"):
        return f"a user who is {current} cannot be enabled"
    return None


def _changes(shown: Mapping[str, Any], body: api.UpdateUserRequest) -> list[str]:
    """The fields other than `status` that `body` would change on `shown`."""
    sent, changed = body.model_fields_set, []
    if "display_name" in sent and body.display_name != shown["display_name"]:
        changed.append("display_name")
    if "roles" in sent and frozenset(body.roles or ()) != frozenset(shown["roles"]):
        changed.append("roles")
    if "mfa_required" in sent and not shown["mfa_required"]:
        changed.append("mfa_required")
    return changed


def _patch_of(body: api.UpdateUserRequest) -> UserPatch:
    sent = body.model_fields_set
    return UserPatch(
        display_name=body.display_name,
        set_display_name="display_name" in sent,
        roles=frozenset(body.roles) if body.roles is not None else None,
        require_mfa=body.mfa_required is True,
        enable=body.status == "active",
    )


async def _patch_body(request: Request) -> api.UpdateUserRequest | JSONResponse:
    """The closed `UpdateUserRequest` (at most 64 KiB, never echoed): `mfa_required: false` (O3),
    `status` `invited` or `locked` (R6), a `null` the contract does not allow and a name that
    Postgres `text` cannot hold (U+0000) are 400."""
    if (raw := await _read_capped(request)) is None:
        detail = f"the body exceeds {_MAX_BODY_BYTES} bytes"
        return _registered(ErrorCode.VALIDATION_FAILED, 400, detail)
    try:
        body = api.UpdateUserRequest.model_validate_json(raw)
    except ValidationError as exc:
        named = sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]} & _PATCH_FIELDS)
        listed = f": {', '.join(named)}" if named else ""
        detail = f"the request does not match its schema{listed}"
        return _registered(ErrorCode.VALIDATION_FAILED, 400, detail)
    sent = body.model_fields_set
    if nulls := [name for name in _NOT_NULL if name in sent and getattr(body, name) is None]:
        return _registered(ErrorCode.VALIDATION_FAILED, 400, f"not nullable: {', '.join(nulls)}")
    if body.display_name is not None and "\x00" in body.display_name:
        return _registered(ErrorCode.VALIDATION_FAILED, 400, "display_name holds a NUL character")
    return body


async def _read(store: UserAdminStore, user_id: uuid.UUID) -> dict[str, Any] | JSONResponse:
    """The user's representation, 404 for a missing or deleted one, 503 for an outage."""
    try:
        found = await store.get_user(user_id)
    except Exception as exc:  # a store outage is a 503; anything else is a defect (a 500)
        if not is_storage_outage(exc):
            raise
        _log().error("users.admin read failed", error=type(exc).__name__)
        return _registered(ErrorCode.STORE_UNAVAILABLE, 503, "the user store is unavailable")
    if found is None:
        return _registered(ErrorCode.NOT_FOUND, 404, "user not found")
    return representation(found)


def _answer(shown: dict[str, Any]) -> JSONResponse:
    return JSONResponse(shown, headers={"ETag": user_etag(shown)})


async def _audit_revoke_ahead(auth: _AuthLike, record: SessionRecord, now: datetime) -> None:
    """R5 (C-2.9): B16 `REVOKE` on the session's chart, as `reset_totp` records it; the chart's
    `revoked` entry writes the one `auth.session_revoked`, ahead of the change. A record the sink
    refuses raises `SessionChartError` with the chart rolled back and nothing revoked."""
    await auth.step_up.chart.revoke(record, now, ADMIN_REVOKE_REASON)


def _who(request: Request) -> dict[str, Any]:
    rid = current_request_id()  # bound by `CorrelationMiddleware`: a UUID if present
    return {"actor_ip": source_ip(request.scope), "request_id": uuid.UUID(rid) if rid else None}


async def _audit_owner_revoke(
    emitter: _Emitter,
    principal: PrincipalSnapshot,
    elevated: uuid.UUID,
    user_id: uuid.UUID,
    revoked: uuid.UUID,
    who: Mapping[str, Any],
) -> None:
    """C-2.9, SR-055: the acting Owner's own record of an admin revoke, ahead of B16 REVOKE,
    whose `auth.session_revoked` names the session's own user. It names the Owner (id, roles,
    the elevated session, the request) and the revoked session with its user."""
    await emitter.emit(
        "users.session_revoked",
        actor_label=str(principal.user_id),
        actor_user_id=principal.user_id,
        session_id=elevated,
        object_kind="session",
        object_id=str(revoked),
        severity=Severity.WARNING,
        reason=ADMIN_REVOKE_REASON,
        before_state={"user_id": str(user_id), "revoked_reason": None},
        after_state={
            "user_id": str(user_id),
            "revoked_reason": ADMIN_REVOKE_REASON,
            "actor_roles": sorted(principal.roles),
        },
        **who,
    )


async def audit_user_update(emitter: _Emitter, change: UserUpdate, base: Mapping[str, Any]) -> None:
    """The records of one PATCH, ahead of its commit: `users.enable` (R5: status and roles only,
    nothing restored, R6), `users.update` for the name and the MFA flag (the field names only, so
    no PII is copied, O6), and `roles.grant` / `roles.revoke` with the sets before and after."""
    before, after = change.before, change.after
    held, kept = sorted(before["roles"]), sorted(after["roles"])
    if before["status"] != after["status"]:
        await emitter.emit(
            "users.enable",
            **base,
            outcome=AuditOutcome.SUCCESS,
            severity=Severity.WARNING,
            before_state={"status": before["status"], "roles": held},
            after_state={"status": after["status"], "roles": kept},
        )
    if named := [f for f in ("display_name", "mfa_required") if before[f] != after[f]]:
        mfa = "mfa_required" in named
        await emitter.emit(
            "users.update",
            **base,
            reason=",".join(named),
            before_state={"mfa_required": before["mfa_required"]} if mfa else None,
            after_state={"changed": named, **({"mfa_required": True} if mfa else {})},
        )
    for action, moved in (
        ("roles.grant", sorted(set(kept) - set(held))),
        ("roles.revoke", sorted(set(held) - set(kept))),
    ):
        if moved:
            await emitter.emit(
                action,
                **base,
                reason=",".join(moved),
                before_state={"roles": held},
                after_state={"roles": kept},
            )


def make_user_admin_router(
    store: UserAdminStore | None,
    emitter: _Emitter,
    principal_resolver: SnapshotResolver | None,
    notifier: PermissionChangeNotifier,
    *,
    auth: _AuthLike | None = None,
    user_disable: UserDisable | None = None,
) -> APIRouter:
    """`getUser`, `updateUser`, `listUserSessions` and `revokeUserSession` (E42-T09). RBAC runs
    first, so a refused caller gets one audited 403 whatever the target (U25); an unwired
    store answers 501 after it. `emitter` and `notifier` are mandatory, as for the role route."""
    if emitter is None or notifier is None:
        raise TypeError("make_user_admin_router: audit emitter and notifier are required")
    router = APIRouter()

    async def caller(
        request: Request, user_id: uuid.UUID, permission: Permission
    ) -> PrincipalSnapshot | JSONResponse:
        """The authorised caller, or the answer: 501 unwired, 401, an audited 403 naming the
        target (before any lookup), or 503 when that refusal cannot be audited."""
        if principal_resolver is None:
            return _registered(ErrorCode.NOT_IMPLEMENTED, 501, "no principal resolver wired")
        got = principal_resolver.resolve(request)
        principal = await got if inspect.isawaitable(got) else got
        if principal is None:
            return _unauthenticated()
        denials = _NamesTarget(emitter, user_id, partial(_session_of, auth, request))
        try:
            await enforce(principal, permission, emitter=denials, **_who(request))
        except ForbiddenError as exc:
            return _forbidden(exc.deny.reason.value)
        except (AuditError, RuntimeError) as exc:  # RuntimeError: audit not started
            _log().warning("users.admin refusal not audited", error=type(exc).__name__)
            detail = "the refusal could not be audited"
            return _registered(ErrorCode.AUDIT_UNAVAILABLE, 503, detail)
        return principal

    @router.get("/users/{userId}")
    async def get_user(
        request: Request, user_id: Annotated[uuid.UUID, Path(alias="userId")]
    ) -> JSONResponse:
        principal = await caller(request, user_id, Permission.USERS_READ)
        if isinstance(principal, JSONResponse):
            return principal
        if store is None:
            return _registered(ErrorCode.NOT_IMPLEMENTED, 501, "no user store wired")
        shown = await _read(store, user_id)
        return shown if isinstance(shown, JSONResponse) else _answer(shown)

    async def disable(
        user_id: uuid.UUID,
        principal: PrincipalSnapshot,
        body: api.UpdateUserRequest,
        shown: dict[str, Any],
        *,
        acknowledged: bool,
        expected: str | None,
    ) -> JSONResponse:
        """SR-029: the whole cascade, exactly as `DELETE /users/{userId}` runs it (AC7 included),
        and nothing else: another field it would change is refused before anything is. UL3-T1:
        an `If-Match` is judged again in the cascade's own transaction, on the user read under
        its lock, so a change committed since `shown` was read is 412 with nothing done."""
        if changed := _changes(shown, body):
            detail = f"a disable changes nothing else; send {', '.join(changed)} on its own"
            return _registered(ErrorCode.VALIDATION_FAILED, 400, detail)
        if store is None or user_disable is None:
            return _registered(ErrorCode.NOT_IMPLEMENTED, 501, "no disable service wired")

        def unchanged(locked: Mapping[str, Any]) -> None:
            if user_etag(representation(locked)) != expected:
                raise UserVersionConflictError(str(user_id))

        try:
            await user_disable.disable(
                user_id,
                actor=principal,
                acknowledge_unknown_positions=acknowledged,
                precondition=None if expected is None else unchanged,
            )
        except UserLifecycleError as exc:
            return _lifecycle_problem(exc)
        except Exception as exc:  # a store outage is a 503; anything else is a defect (a 500)
            if not is_storage_outage(exc):
                raise
            _log().error("user disable store unavailable", error=type(exc).__name__)
            return _registered(ErrorCode.STORE_UNAVAILABLE, 503, "the user store is unavailable")
        after = await _read(store, user_id)
        return after if isinstance(after, JSONResponse) else _answer(after)

    @router.patch("/users/{userId}")
    async def update_user(
        request: Request, user_id: Annotated[uuid.UUID, Path(alias="userId")]
    ) -> JSONResponse:
        principal = await caller(request, user_id, Permission.USERS_WRITE)
        if isinstance(principal, JSONResponse):
            return principal
        undeclared = undeclared_query_refusal(request, UPDATE_USER_QUERY, self_service=False)
        if undeclared is not None:  # SR-026, as the DELETE: the names, before any value is read
            return undeclared
        if (acknowledged := _flag(request, _ACKNOWLEDGE)) is None:
            detail = f"{_ACKNOWLEDGE} is true or false, given once"
            return _registered(ErrorCode.VALIDATION_FAILED, 400, detail)
        if isinstance(body := await _patch_body(request), JSONResponse):
            return body
        who = _who(request)
        if user_id == principal.user_id and body.model_fields_set & {"roles", "status"}:
            denials = _NamesTarget(emitter, user_id, partial(_session_of, auth, request))
            try:  # SR-055: never the acting user's roles or status, step-up or not
                await denials.emit(
                    "rbac.denied",
                    actor_label=str(principal.user_id),
                    actor_user_id=principal.user_id,
                    outcome=AuditOutcome.DENIED,
                    severity=Severity.WARNING,
                    reason="self_target",
                    **who,
                )
            except (AuditError, RuntimeError):
                return _registered(ErrorCode.AUDIT_UNAVAILABLE, 503, _NOT_AUDITED)
            return _forbidden("self_target")
        if isinstance(session := await _elevated(auth, request), JSONResponse):
            return session
        if store is None:
            return _registered(ErrorCode.NOT_IMPLEMENTED, 501, "no user store wired")
        if isinstance(shown := await _read(store, user_id), JSONResponse):
            return shown
        expected = _if_match(request)
        if expected is not None and expected != user_etag(shown):
            return _registered(ErrorCode.VERSION_CONFLICT, 412, _STALE)
        if (refusal := _status_refusal(shown["status"], body.status)) is not None:
            return _registered(ErrorCode.VALIDATION_FAILED, 400, refusal)
        if body.status == "disabled":
            return await disable(
                user_id, principal, body, shown, acknowledged=acknowledged, expected=expected
            )
        if not body.model_fields_set:  # an empty patch changes nothing and takes no lock
            return _answer(shown)
        base = {
            "actor_label": str(principal.user_id),
            "actor_user_id": principal.user_id,
            "object_kind": "user",
            "object_id": str(user_id),
            "session_id": session,
            **who,
        }

        def check(locked: Mapping[str, Any]) -> None:
            """Under the locks (R7): the version and the status the change starts from."""
            current = representation(locked)
            if expected is not None and expected != user_etag(current):
                raise _Stale
            if (refused := _status_refusal(current["status"], body.status)) is not None:
                raise _StatusRefused(refused)

        async def write_ahead(change: UserUpdate) -> None:
            """C-2.9: every record of the change, read under the locks, before the commit."""
            try:
                await audit_user_update(emitter, change, base)
            except (AuditError, RuntimeError) as exc:  # RuntimeError: audit not started
                raise _AuditRefused from exc

        try:
            change = await store.update_user(
                user_id, _patch_of(body), actor=principal.user_id, check=check, audit=write_ahead
            )
        except OwnerFloorError:  # the role path's loser: one `rbac.denied` (UL-F13), no change
            try:
                await emitter.emit(
                    "rbac.denied",
                    **base,
                    outcome=AuditOutcome.DENIED,
                    severity=Severity.WARNING,
                    reason="owner_floor",
                    before_state={"roles": sorted(shown["roles"])},
                    after_state={"roles": sorted(body.roles or ())},
                )
            except (AuditError, RuntimeError):
                return _registered(ErrorCode.AUDIT_UNAVAILABLE, 503, _NOT_AUDITED)
            return _registered(ErrorCode.CONFLICT, 409, _LAST_OWNER)
        except _Stale:
            return _registered(ErrorCode.VERSION_CONFLICT, 412, _STALE)
        except _StatusRefused as exc:
            return _registered(ErrorCode.VALIDATION_FAILED, 400, str(exc))
        except (_AuditRefused, WriteAheadTimeout):  # the store bounds the hook (#2510)
            return _registered(ErrorCode.AUDIT_UNAVAILABLE, 503, _NOT_AUDITED)
        except Exception as exc:  # a store outage is a 503; anything else is a defect (a 500)
            if not is_storage_outage(exc):
                raise
            _log().error("users.update store unavailable", error=type(exc).__name__)
            return _registered(ErrorCode.STORE_UNAVAILABLE, 503, "the user store is unavailable")
        if change is None:
            return _registered(ErrorCode.NOT_FOUND, 404, "user not found")
        if frozenset(change.before["roles"]) != frozenset(change.after["roles"]):
            await _push_roles(notifier, user_id)  # after the commit: counted, never rolled back
        return _answer(representation(change.after))

    @router.get("/users/{userId}/sessions")
    async def list_user_sessions(
        request: Request, user_id: Annotated[uuid.UUID, Path(alias="userId")]
    ) -> JSONResponse:
        principal = await caller(request, user_id, Permission.USERS_READ)
        if isinstance(principal, JSONResponse):
            return principal
        if store is None or auth is None or not auth.sessions_is_active:
            return _registered(ErrorCode.NOT_IMPLEMENTED, 501, "no user or session store wired")
        if isinstance(found := await _read(store, user_id), JSONResponse):
            return found
        mine = await _session_of(auth, request)  # `current` marks the caller's own session
        views = await auth.sessions.list_sessions(
            str(user_id), current_session_id=None if mine is None else str(mine)
        )
        return JSONResponse({"items": [_view_json(view) for view in views]})

    @router.delete("/users/{userId}/sessions/{sessionId}")
    async def revoke_user_session(
        request: Request,
        user_id: Annotated[uuid.UUID, Path(alias="userId")],
        session_id: Annotated[uuid.UUID, Path(alias="sessionId")],
    ) -> Response:
        principal = await caller(request, user_id, Permission.USERS_WRITE)
        if isinstance(principal, JSONResponse):
            return principal
        if isinstance(elevated := await _elevated(auth, request), JSONResponse):
            return elevated
        if store is None or auth is None:
            return _registered(ErrorCode.NOT_IMPLEMENTED, 501, "no user store wired")
        if isinstance(found := await _read(store, user_id), JSONResponse):
            return found
        record = await auth.sessions.find_live_session(str(user_id), str(session_id))
        if record is None:  # unknown, ended or another user's (IDOR): one 404, nothing changed
            return _registered(ErrorCode.NOT_FOUND, 404, _NO_SESSION)
        who = _who(request)
        try:  # the acting Owner's record first: unwritable, nothing is recorded or revoked
            await _audit_owner_revoke(emitter, principal, elevated, user_id, record.id, who)
        except (AuditError, RuntimeError):  # RuntimeError: audit not started
            return _registered(ErrorCode.AUDIT_UNAVAILABLE, 503, _NOT_AUDITED)
        try:
            await _audit_revoke_ahead(auth, record, auth.sessions.now())
        except SessionChartError:
            return _registered(ErrorCode.AUDIT_UNAVAILABLE, 503, _NOT_AUDITED)
        try:  # the row, then its sockets (4401, 23 section 9.5) through the revocation sink
            revoked = await auth.sessions.revoke(str(session_id), reason=ADMIN_REVOKE_REASON)
        except Exception as exc:  # recorded, not revoked: the trail over-reports, never under
            if not is_storage_outage(exc):
                raise
            _log().error("users.session_revoke store unavailable", error=type(exc).__name__)
            detail = "the session store is unavailable"
            return _registered(ErrorCode.STORE_UNAVAILABLE, 503, detail)
        if revoked is None:  # it ended since it was found (a logout, a revoke, a rotation)
            _log().warning("users.session_revoke.not_live", target_user_id=str(user_id))
            return _registered(ErrorCode.NOT_FOUND, 404, _NO_SESSION)
        return Response(status_code=204)

    return router
