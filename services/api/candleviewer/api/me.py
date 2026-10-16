"""`GET /me`, `GET /me/preferences` and `GET /me/keymap` (#2713, the server half of E10-T04).

The shell bootstrap (`apps/web/src/shell/bootstrap/bootstrap.ts`) calls all three before the
router renders, and a `/me` failure is fatal there. Contract: `getMe`, `getMyPreferences`,
`getMyKeymap` in `22-api-openapi.yaml`.

Scope `self` (SR-026). The caller is the session's own user and nothing the client sends selects
whom a route describes, so a query parameter is refused (`api.query_allowlist`) rather than
ignored. Authentication is the opaque bearer access token of ADR-0020. Every refusal of the
credential (missing, unknown, expired, revoked), a user who is no longer `active`
and a user holding a role outside the closed set (`RoleName`; the snapshot and rules-actor
resolvers refuse it as no principal) get one and the same 401, so the answer is no session oracle.
An idle-locked session gets `401 session_idle_locked` instead (contract "Idle lock", #2300): the
shell then shows the unlock screen (SCR-005), not sign-in, as `IdleLockMiddleware` answers it.
A session backend that is not active is a 503 `store_unavailable`, and so is a `RuntimeError` out
of the authentication call (defensive parity with the audit and snapshot resolvers, which answer no
principal for it). That catch also hides a defect that raises `RuntimeError`, so the 503 is logged
as `auth.me.session_backend_error`: the exception class name and a traceback, which the redaction
filter scans. The checks run in this order and the first refusal wins: session backend,
authentication, identity, permission (`settings:read` for preferences and keymap, none for `/me`),
undeclared query parameter. A read-only session (`403 session_read_only` after three bad step-up
codes) refuses writes only, so reads are served. The role is always re-read from the identity
store (C-12.4); the UI uses these answers to decide what to render and they authorise nothing
(04-security-program.md 7.3).

`GET /me` is assembled from the session row and the SQL identity read path (`user`,
`session_info`, `accounts`). The `user` object is projected onto the contract's `User` fields, so
a column the store later returns can never reach the client. The email address is served as
stored: `users.email` is only constrained to `position('@' in email) > 1` and the owner's address
is operator input, so `owner@candleviewer.local` is valid data. `User.email` carries that same
pattern and not `format: email`, so the generated model accepts it (a refusal would turn the call
the shell cannot start without into a 500), and no model here overrides the contract's.

Preferences and keymap serve the contract's empty answer: no store for per-user overrides and
no deployment default set exist yet (the `settings` table has no user-scope writer until
`PATCH /me/preferences`, and `hotkey_profiles` is not migrated, E10-S02), so the effective
settings are empty and there is no stored profile, and the client applies its built-in defaults.
Both handlers read their data here and nowhere else, so the stores slot in without a contract
change.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.idle_lock import idle_locked_problem
from candleviewer.api.query_allowlist import undeclared_query_refusal
from candleviewer.auth.errors import AuthError, SessionIdleLocked
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.step_up import grace_expires_at
from candleviewer.settings import Environment

SETTINGS_READ: Final = Permission.SETTINGS_READ.value

#: SR-026: the query parameters each contract operation declares (22-api-openapi.yaml). All
#: three declare none, so any query key, a target user under any spelling included, is refused.
GET_ME_QUERY: frozenset[str] = frozenset()
GET_MY_PREFERENCES_QUERY: frozenset[str] = frozenset()
GET_MY_KEYMAP_QUERY: frozenset[str] = frozenset()

#: `Me.role` is one name where a user may hold several: the highest of these.
_ROLE_PRECEDENCE: Final = ("owner", "manager", "viewer")
#: The closed role set (`RoleName`, the `role_name` enum): a user holding any other name is refused.
_KNOWN_ROLES: Final = frozenset(_ROLE_PRECEDENCE)
#: `Me.permissions` is drawn from the contract's closed vocabulary; anything else is dropped.
_VOCABULARY: Final = frozenset(permission.value for permission in Permission)
_NO_STORE: Final = {"Cache-Control": "no-store"}  # SR-178: the shell holds these in memory only


class _Sessions(Protocol):
    async def authenticate_access_token(
        self, raw_access_token: str, *, touch: bool = False, allow_locked: bool = False
    ) -> SessionRecord: ...


class AuthLike(Protocol):
    """The part of `AuthService` these routes use."""

    @property
    def sessions_is_active(self) -> bool: ...

    @property
    def sessions(self) -> _Sessions: ...


class MeIdentity(Protocol):
    """The SQL identity read path (`SqlAlchemyIdentityProvider`) as these routes read it."""

    async def user(self, user_id: str) -> dict[str, Any]: ...

    async def session_info(self, user_id: str) -> dict[str, Any]: ...

    async def accounts(self, user_id: str) -> Sequence[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class _Caller:
    record: SessionRecord
    user: dict[str, Any]
    permissions: frozenset[str]
    identity: MeIdentity


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
        media_type="application/problem+json",
    )


def _unauthenticated() -> JSONResponse:
    return _problem(
        401,
        "unauthenticated",
        "Missing, malformed or expired access token",
        "Authentication is required.",
    )


def _store_unavailable() -> JSONResponse:
    return _problem(503, "store_unavailable", "Session store unavailable", "No session backend.")


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _bearer(request: Request) -> str | None:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    return value.strip() or None if scheme.lower() == "bearer" else None


def _highest_role(roles: Sequence[object]) -> str | None:
    held = {str(role) for role in roles}
    return next((role for role in _ROLE_PRECEDENCE if role in held), None)


def _holds_only_known_roles(user: dict[str, Any]) -> bool:
    return {str(role) for role in user.get("roles") or ()} <= _KNOWN_ROLES


def make_me_router(
    auth: AuthLike,
    *,
    identity: MeIdentity | None,
    environment: Environment,
    clock: Callable[[], datetime] | None = None,
) -> APIRouter:
    """`identity=None` answers 501 after authenticating, so nothing is served unchecked. The app
    wires the identity provider and the session backend together or not at all (the fake storage
    backend has neither and answers 503 first), so only a router built by hand reaches the 501.
    `clock` defaults to UTC now; pass the auth clock where it is offset."""
    router = APIRouter()
    now = clock or (lambda: datetime.now(UTC))

    async def _gate(
        request: Request, *, permission: str | None, query: frozenset[str]
    ) -> _Caller | Response:
        if not auth.sessions_is_active:
            return _store_unavailable()
        token = _bearer(request)
        if token is None:
            return _unauthenticated()
        try:
            record = await auth.sessions.authenticate_access_token(token, touch=True)
        except SessionIdleLocked as exc:  # not sign-in: the unlock screen (contract "Idle lock")
            return idle_locked_problem(exc.idle_locked_at)
        except AuthError:  # unknown, expired or revoked: one answer
            return _unauthenticated()
        except RuntimeError as exc:
            # Defensive parity with the audit and snapshot resolvers, not a race: nothing awaits
            # between the `sessions_is_active` read and the `sessions` read, so this is a store
            # failing under the call. The catch is broad, so a defect that raises RuntimeError
            # would hide behind the 503: log it (class name and a traceback, which the redaction
            # filter scans; the message gets no field of its own).
            _log().error("auth.me.session_backend_error", error=type(exc).__name__, exc_info=exc)
            return _store_unavailable()
        if identity is None:
            return _problem(
                501, "not_implemented", "Not implemented", "No identity provider is wired."
            )
        try:
            user = await identity.user(str(record.user_id))
            info = await identity.session_info(str(record.user_id))
        except LookupError:  # the user is gone
            return _unauthenticated()
        if user.get("status") != "active" or not _holds_only_known_roles(user):
            return _unauthenticated()  # an unknown role is no principal, as in the snapshot gate
        permissions = frozenset(
            code for code in map(str, info.get("permissions", ())) if code in _VOCABULARY
        )
        if permission is not None and permission not in permissions:
            return _problem(
                403,
                "forbidden",
                "Authenticated but lacking the required permission",
                f"Requires permission '{permission}'.",
                required_permissions=[permission],
            )
        if (refusal := undeclared_query_refusal(request, query)) is not None:
            return refusal  # SR-026: before anything is read for the answer
        return _Caller(record, user, permissions, identity)

    @router.get("/me", tags=["auth"])
    async def get_me(request: Request) -> Response:
        caller = await _gate(request, permission=None, query=GET_ME_QUERY)
        if isinstance(caller, Response):
            return caller
        role = _highest_role(caller.user.get("roles") or ())
        if role is None:
            return _problem(
                403,
                "forbidden",
                "Authenticated but lacking the required permission",
                "The account holds no live role.",
            )
        accounts = await caller.identity.accounts(str(caller.record.user_id))
        body = {
            "user": caller.user,
            "role": role,
            "permissions": sorted(caller.permissions),
            "accounts": list(accounts),
            "session": {
                "session_id": str(caller.record.id),
                "environment": environment.value,
                "elevated_until": grace_expires_at(caller.record.step_up_elevations, now()),
                "one_click_armed_until": None,  # one-click arming is not served yet
            },
        }
        payload = api.Me.model_validate(body).model_dump(mode="json", exclude_unset=True)
        return JSONResponse(payload, headers=_NO_STORE)

    @router.get("/me/preferences", tags=["settings"])
    async def get_my_preferences(request: Request) -> Response:
        caller = await _gate(request, permission=SETTINGS_READ, query=GET_MY_PREFERENCES_QUERY)
        if isinstance(caller, Response):
            return caller
        settings = api.Settings.model_validate({"_meta": {"overridden": []}})
        payload = settings.model_dump(mode="json", by_alias=True, exclude_unset=True)
        return JSONResponse(payload, headers=_NO_STORE)

    @router.get("/me/keymap", tags=["settings"])
    async def get_my_keymap(request: Request) -> Response:
        caller = await _gate(request, permission=SETTINGS_READ, query=GET_MY_KEYMAP_QUERY)
        if isinstance(caller, Response):
            return caller
        return JSONResponse({"bindings": []}, headers=_NO_STORE)

    return router
