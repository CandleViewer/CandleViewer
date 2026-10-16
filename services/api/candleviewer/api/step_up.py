"""`POST /auth/step-up`, owner TOTP reset and the read-only write guard
(E09-S04, US-ONB-005/010).

Thin HTTP adapter over `auth.step_up.StepUpService`. `auth` may not import
`audit`, so every audit record (C-2.9) is emitted here: `auth.step_up_granted`,
`auth.step_up_failed`, `auth.step_up_required`, `auth.session_readonly_downgrade`
and `auth.mfa_reset_by_owner`. Elevation state is server-side, keyed by the
session id resolved from the bearer token - nothing the client sends can
forge it. `require_elevation_for` is the `is_dangerous` gate E09-T03 routes
call; `make_read_only_guard` is the middleware refusing every write during the
5-minute downgrade.
"""

from __future__ import annotations

import inspect
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Protocol

from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response

# The function `starlette.routing` itself matches routes with (it only re-imports
# it, so mypy --strict refuses that path): the guard classifies what the router
# dispatches on, by construction. A move upstream fails the import, never open.
from starlette._utils import get_route_path

from candleviewer.audit.models import Severity
from candleviewer.auth.errors import (
    AuthError,
    SessionReadOnly,
    StepUpCodeInvalid,
    StepUpRequired,
    UnknownActionClass,
)
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.auth.step_up import ACTION_CLASSES, PositionStateProvider, StepUpService

_PROBLEM = "application/problem+json"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
#: Writes that must keep working in the downgrade (ending the session).
_WRITE_EXEMPT_PATHS = frozenset({"/auth/logout", "/auth/step-up"})


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class _AuthLike(Protocol):
    @property
    def step_up_is_active(self) -> bool: ...

    @property
    def step_up(self) -> StepUpService: ...

    @property
    def sessions(self) -> Any: ...

    @property
    def sessions_is_active(self) -> bool: ...


class _UserLookup(Protocol):
    async def get_roles(self, user_id: uuid.UUID) -> frozenset[str] | None: ...


class _Resolver(Protocol):
    """Sync (test seams) or async (`SessionSnapshotResolver`, the deployed app, #2492)."""

    def resolve(
        self, request: Request
    ) -> PrincipalSnapshot | Awaitable[PrincipalSnapshot | None] | None: ...


def _problem(status: int, code: str, title: str, detail: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "type": f"https://candleviewer.local/errors/{code}",
            "title": title,
            "status": status,
            "code": code,
            "detail": detail,
            **extra,
        },
        media_type=_PROBLEM,
    )


def _bearer(request: Request) -> str | None:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    return value.strip() or None if scheme.lower() == "bearer" else None


def readonly_problem(exc: SessionReadOnly) -> JSONResponse:
    until = exc.until.isoformat() if hasattr(exc.until, "isoformat") else None
    return _problem(
        403,
        "session_read_only",
        "Session is read-only",
        "Too many invalid step-up codes; this session is read-only for 5 minutes.",
        readonly_until=until,
    )


def required_problem(exc: StepUpRequired) -> JSONResponse:
    return _problem(
        403,
        "step_up_required",
        "Step-up authentication required",
        "Re-enter your authenticator code (POST /auth/step-up) to continue.",
        action_class=exc.action_class,
    )


async def require_elevation_for(
    auth: _AuthLike, session_id: str, action_class: str
) -> JSONResponse | None:
    """The `is_dangerous` decision-point hook (E09-T03 routes call this):
    None when elevated, else the 403 problem to return."""
    try:
        await auth.step_up.require_elevation(session_id, action_class)
    except SessionReadOnly as exc:
        return readonly_problem(exc)
    except StepUpRequired as exc:
        # Remember the challenged class server-side so the modal may post `{code}` only.
        await auth.step_up.record_pending(session_id, action_class)
        return required_problem(exc)
    return None


#: `is_dangerous` routes (permissions seeded `is_dangerous=true`) -> the
#: step-up action class that must be elevated. Method + path regex. Paths are
#: the `22-api-openapi.yaml` contract; entries for routes that later epics
#: implement (E27 keys, E44/E39 risk) are pre-registered so they are gated the
#: moment they are mounted. `tests/unit/api/test_dangerous_route_registry.py`
#: fails if any mounted route matching `DANGEROUS_PATH_PATTERN` is missing here
#: or in `HANDLER_GATED_ROUTES`.
DANGEROUS_ROUTES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("POST", re.compile(r"^/users$"), "users"),  # invite
    ("POST", re.compile(r"^/users/[^/]+/invite$"), "users"),  # reissue mints a new token
    ("DELETE", re.compile(r"^/users/[^/]+/invite$"), "users"),  # revoke
    ("PUT", re.compile(r"^/users/[^/]+/roles$"), "users"),
    ("POST", re.compile(r"^/users/[^/]+/mfa/reset$"), "users"),
    ("POST", re.compile(r"^/exchange-accounts/[^/]+/keys$"), "keys"),
    ("POST", re.compile(r"^/exchange-accounts/[^/]+/keys/[^/]+/rotate$"), "keys"),
    ("DELETE", re.compile(r"^/exchange-accounts/[^/]+/keys/[^/]+$"), "keys"),
    # reveal-scope has no contract path yet (E27); pre-registered under the keys prefix.
    ("POST", re.compile(r"^/exchange-accounts/[^/]+/keys/[^/]+/reveal-scope$"), "keys"),
    ("GET", re.compile(r"^/exchange-accounts/[^/]+/keys/[^/]+/reveal-scope$"), "keys"),
    ("POST", re.compile(r"^/risk/lockouts/[^/]+/override$"), "risk_caps"),
)

#: No-grace classes cannot be gated by path alone: kill-switch *engage* must
#: never wait for a code (emergency stop) and switching *to demo* is not
#: dangerous, so only the handler (body-aware) knows. Each entry is a
#: declaration that the handler demands a fresh code for its dangerous
#: branch; the owning epic must add a test proving it.
HANDLER_GATED_ROUTES: tuple[tuple[str, str, str], ...] = (
    ("POST", "/trading/kill-switch", "killswitch"),  # E39: release only
    ("POST", "/session/environment", "live_enablement"),  # E44: to live only
    ("PUT", "/rules/{ruleId}/mode", "live_enablement"),  # E35-S01: arming a live-scoped rule
)

#: Mounted write routes whose path matches this must be in one of the two
#: registries above (deny-by-default for future tickets).
DANGEROUS_PATH_PATTERN = re.compile(
    r"^/(admin/)?(users|exchange-accounts/[^/]+/keys|keys|live|kill|trading/kill-switch"
    r"|session/environment|risk/lockouts)(/|$)"
)


def dangerous_action_class(method: str, path: str) -> str | None:
    for m, pattern, action_class in DANGEROUS_ROUTES:
        if method == m and pattern.match(path):
            return action_class
    return None


def make_read_only_guard(
    auth: _AuthLike,
    emitter: _Emitter | None = None,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """HTTP middleware body: refuse every write from a session in the
    read-only downgrade (enforced on all write routes, not just step-up) and
    demand a step-up on the path-gated `DANGEROUS_ROUTES`.

    #2752: requests are classified on the routed path - `get_route_path`, the
    ASGI `root_path` stripped exactly as the router does - never on
    `request.url.path`, which keeps a `uvicorn --root-path` prefix that no
    registry pattern matches. Sessions wired without step-up is a wiring
    fault, not "no step-up needed": the path-gated routes answer 503 rather
    than run unchecked (C-2.21). With no session store (the fake backend)
    nothing can authenticate and every route fails closed on its own."""

    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = get_route_path(request.scope)
        action_class = dangerous_action_class(request.method, path)
        if (
            (request.method in _SAFE_METHODS and action_class is None)
            or path in _WRITE_EXEMPT_PATHS
            or not auth.sessions_is_active
        ):
            return await call_next(request)
        if not auth.step_up_is_active:
            if action_class is not None:
                return _problem(
                    503, "service_unavailable", "Service unavailable", "step-up not wired"
                )
            return await call_next(request)  # no step-up, so no read-only downgrade
        token = _bearer(request)
        if token is not None:
            try:
                record = await auth.sessions.authenticate_access_token(token)
                await auth.step_up.assert_writable(str(record.id))
                if action_class is not None:
                    # E09-T03 decision point: dangerous route, no elevation -> 403.
                    # `auth.step_up_required` is written by B16 (`ACTION_REQUEST`).
                    denied = await require_elevation_for(auth, str(record.id), action_class)
                    if denied is not None:
                        return denied
            except SessionReadOnly as exc:
                return readonly_problem(exc)
            except AuthError:
                pass  # unauthenticated: the route answers 401 itself
        return await call_next(request)

    return guard


def make_step_up_router(
    auth: _AuthLike,
    emitter: _Emitter,
    *,
    principal_resolver: _Resolver | None = None,
    positions: PositionStateProvider | None = None,
    users: _UserLookup | None = None,
    audit_ready: Callable[[], bool],
) -> APIRouter:
    """`audit_ready()` false -> the owner TOTP reset answers 503 before changing
    anything: it cannot be undone, so its audit record must be writable (C-2.9)."""
    if emitter is None:
        raise TypeError("make_step_up_router: audit emitter is required")
    router = APIRouter(tags=["auth"])

    async def _session(request: Request) -> SessionRecord | JSONResponse:
        if not auth.step_up_is_active or not auth.sessions_is_active:
            return _problem(503, "service_unavailable", "Service unavailable", "step-up not wired")
        token = _bearer(request)
        if token is None:
            return _problem(401, "unauthorized", "Unauthorized", "authentication required")
        try:
            record: SessionRecord = await auth.sessions.authenticate_access_token(token)
        except AuthError:
            return _problem(401, "unauthorized", "Unauthorized", "authentication required")
        return record

    async def _audit(action: str, record: SessionRecord, **kw: Any) -> None:
        await emitter.emit(
            action,
            actor_label=str(record.user_id),
            actor_user_id=record.user_id,
            session_id=record.id,
            **kw,
        )

    @router.post("/auth/step-up")
    async def step_up(request: Request) -> JSONResponse:
        got = await _session(request)
        if isinstance(got, JSONResponse):
            return got
        record = got
        try:
            body = await request.json()
        except ValueError:
            body = None
        code = body.get("code") if isinstance(body, dict) else None
        action_class = body.get("action_class") if isinstance(body, dict) else None
        password = body.get("password") if isinstance(body, dict) else None
        if not isinstance(password, str) or not password:
            return _problem(
                422, "validation_failed", "Unprocessable entity", "password is required"
            )
        if not isinstance(code, str) or (
            action_class is not None and not isinstance(action_class, str)
        ):
            return _problem(400, "validation_failed", "Bad request", "code is required")
        # The server decides the class: the one its last 403 challenged. A
        # client-supplied value is only a cross-check (mismatch -> 400).
        pending = await auth.step_up.pending_action_class(str(record.id))
        if action_class is None:
            action_class = pending
        elif pending is not None and action_class != pending:
            return _problem(
                400, "validation_failed", "Bad request", "action_class does not match challenge"
            )
        if action_class is None:
            return _problem(400, "validation_failed", "Bad request", "no pending step-up challenge")
        try:
            grant = await auth.step_up.step_up(
                str(record.user_id), str(record.id), action_class, code, password
            )
        except UnknownActionClass:
            return _problem(
                400,
                "validation_failed",
                "Bad request",
                f"action_class must be one of {sorted(ACTION_CLASSES)}",
            )
        # Step-up granted / failed / read-only downgrade are audited by the B16
        # chart's actions (`StepUpService` records each decision on it).
        except StepUpCodeInvalid as exc:
            return _problem(
                401,
                "mfa_invalid",
                "Step-up rejected",
                "Invalid password or code.",
                failures_remaining=exc.failures_remaining,
            )
        except SessionReadOnly as exc:
            return readonly_problem(exc)
        return JSONResponse(
            status_code=200,
            content={
                "elevated_until": grant.elevated_until.isoformat(),
                "action_class": grant.action_class,
                "single_use": grant.single_use,
                "step_up_expires_at": (
                    None if grant.single_use else grant.elevated_until.isoformat()
                ),
            },
        )

    async def _unknown_user(user_id: uuid.UUID) -> JSONResponse | None:
        """404 for a target that does not exist (never a 200 no-op reset)."""
        if users is None:
            return _problem(501, "not_implemented", "Not implemented", "no user store")
        if await users.get_roles(user_id) is None:
            return _problem(404, "not_found", "Not found", "user not found")
        return None

    async def _owner(request: Request, record: SessionRecord) -> JSONResponse | None:
        if principal_resolver is None:
            return _problem(501, "not_implemented", "Not implemented", "no principal resolver")
        got = principal_resolver.resolve(request)
        principal = await got if inspect.isawaitable(got) else got
        if principal is None or principal.user_id != record.user_id:
            return _problem(401, "unauthorized", "Unauthorized", "authentication required")
        try:
            await enforce(
                principal,
                Permission.USERS_WRITE,
                scope=Scope.NONE,
                emitter=emitter,
                session_id=record.id,
            )
        except ForbiddenError:
            return _problem(403, "forbidden", "Forbidden", "owner only")
        if not principal.is_owner:
            return _problem(403, "forbidden", "Forbidden", "owner only")
        return None

    @router.get("/users/{userId}/mfa/reset-preview")
    async def reset_preview(
        request: Request, user_id: Annotated[uuid.UUID, Path(alias="userId")]
    ) -> JSONResponse:
        got = await _session(request)
        if isinstance(got, JSONResponse):
            return got
        denied = await _owner(request, got)
        if denied is not None:
            return denied
        missing = await _unknown_user(user_id)
        if missing is not None:
            return missing
        if positions is None:
            return _problem(501, "not_implemented", "Not implemented", "no position provider")
        preview = await auth.step_up.preview_reset(str(user_id), positions)
        return JSONResponse(
            {
                "target_user_id": str(preview.target_user_id),
                "open_position_count": preview.open_position_count,
                "positions": "known" if preview.positions_known else "unavailable",
                "position_source": preview.position_source,
                "requires_acknowledge_unknown_positions": not preview.positions_known,
                "message": preview.message,
            }
        )

    @router.post("/users/{userId}/mfa/reset")
    async def reset(
        request: Request, user_id: Annotated[uuid.UUID, Path(alias="userId")]
    ) -> JSONResponse:
        got = await _session(request)
        if isinstance(got, JSONResponse):
            return got
        record = got
        denied = await _owner(request, record)
        if denied is not None:
            return denied
        missing = await _unknown_user(user_id)
        if missing is not None:
            return missing
        gate = await require_elevation_for(auth, str(record.id), "users")
        if gate is not None:  # audited by B16 (`ACTION_REQUEST`)
            return gate
        if positions is None:
            return _problem(501, "not_implemented", "Not implemented", "no position provider")
        preview = await auth.step_up.preview_reset(str(user_id), positions)
        if not preview.positions_known:
            # Unknown position state is never shown as 0: the owner must
            # acknowledge it explicitly before the reset proceeds.
            try:
                body = await request.json()
            except ValueError:
                body = None
            ack = isinstance(body, dict) and body.get("acknowledge_unknown_positions") is True
            if not ack:
                return _problem(
                    409,
                    "positions_unknown",
                    "Open-position state unavailable",
                    preview.message,
                    position_source=preview.position_source,
                    requires_acknowledge_unknown_positions=True,
                )
        if not audit_ready():
            return _problem(503, "service_unavailable", "Service unavailable", "audit unavailable")
        try:
            result = await auth.step_up.reset_totp(
                actor_session_id=str(record.id),
                actor_user_id=str(record.user_id),
                target_user_id=str(user_id),
            )
        except StepUpRequired as exc:  # self-reset refused
            return required_problem(exc)
        await _audit(
            "auth.mfa_reset_by_owner",
            record,
            severity=Severity.CRITICAL,
            object_kind="user",
            object_id=str(user_id),
            after_state={
                "methods_revoked": result.methods_revoked,
                "sessions_revoked": result.sessions_revoked,
            },
        )
        # Reveals nothing: no secret, recovery code or position data.
        return JSONResponse(
            {
                "target_user_id": str(result.target_user_id),
                "methods_revoked": result.methods_revoked,
                "sessions_revoked": result.sessions_revoked,
            }
        )

    return router


__all__ = ["make_read_only_guard", "make_step_up_router", "require_elevation_for"]
