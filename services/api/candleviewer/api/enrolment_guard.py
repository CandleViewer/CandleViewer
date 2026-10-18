"""The enrolment-only session at the HTTP edge (#2295; `22-api-openapi.yaml` "Enrolment-only
session").

A session whose user has `mfa_required` and no confirmed MFA method may call exactly
`ENROLMENT_OPERATIONS` among the operations that need a session; every other such request it
makes answers `403 mfa_enrollment_required` here, before any handler or state change. The
operations the contract serves without a session (`sessionless_operations`, plus the
operational routes) are left alone whatever bearer they carry, so sign-in stays possible and
`POST /auth/mfa/verify` still audits a carried foreign session (E09-X02 AC2). The class is
`AuthService.classify`, read from the user's state on every request (no session flag). A
request without a bearer, or whose bearer has no live session, is left to the route (401, or
a pre-session operation), and so is one whose user is gone or disabled: the route revokes that
session (#2911, SR-029). A session lookup or a classification that fails answers
`503 store_unavailable`: deny by default (C-12.4). A session that was not minted enrolment-only
(its expiry lies beyond `ENROLMENT_ONLY_LIFETIME`, Q7, or it proved a second factor) gets 401
like an expired session, except on `POST /auth/logout`. One past its expiry never reaches the
class: the session lookup refuses it (#3183), so its route answers 401, uncounted here.

The guard is inert only while `AuthService.enrolment_gate_is_active` is false: no session store
is wired, so nothing authenticates. Wired without the user store, every classification fails and
the guard answers 503 (deny by default).

Every refusal is counted (`auth_enrolment_refused_total{transport, reason}`, SR-125) and logged
with the method and the contract route template, never the raw path. A 403 also writes an
`auth.mfa_enrollment_required` audit record (C-2.9; 04 section 7.3: a denied request is
audited) through `EnrolmentRefusals`, the CSRF guard's bounded writer path: a per-user
budget, the shared `RefusalAuditTracker` in-flight cap and a shielded write. Past either the
answer is the same and the metric counts `audit_throttled`. The WebSocket refuses such a session
at `auth` through the same recorder (`app._session_authenticator`, `23-ws-protocol.md` §4.3).

Requests are matched on the routed path (`get_route_path`, as `api/step_up.py`; #2752), and the
bearer is read with the route resolvers' own parse. `create_app` mounts this inside the CSRF
guard and outside the read-only/step-up guard, so a refused request never records a step-up
challenge.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any, Final, Literal, Protocol

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse, Response

# The router's own path function (see `api/step_up.py`, #2752): a move upstream fails the
# import, never open.
from starlette._utils import get_route_path

from candleviewer.api.csrf import (
    ANON_REFUSAL_WINDOW_S,
    AUDIT_TIMEOUT_S,
    SESSION_REFUSALS_PER_WINDOW,
    RefusalAuditTracker,
    _compile_operations,
    bounded_method,
    match_operation,
    source_ip,
)
from candleviewer.api.deny_by_default import PUBLIC_OPERATIONAL_ROUTES

# The parse `api/users.py` and the step-up routes use (the route resolvers inline the same
# one): the guard must see exactly the tokens the routes accept. A test pins the agreement.
from candleviewer.api.step_up import _bearer
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.errors import AuthError
from candleviewer.auth.metrics import auth_enrolment_refused_total
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.session_service import SessionClass
from candleviewer.auth.throttle import PerIpLoginThrottle

#: The only operations an enrolment-only session may call (decision on #2295, contract).
ENROLMENT_OPERATIONS: Final = frozenset(
    {
        ("POST", "/auth/mfa/enroll"),
        ("POST", "/auth/mfa/enroll/confirm"),
        ("GET", "/auth/session"),
        ("POST", "/auth/refresh"),
        ("POST", "/auth/logout"),
    }
)
#: The audit action of a refusal (`audit/actions.py`), named after the problem code.
REFUSAL_ACTION: Final = "auth.mfa_enrollment_required"
#: Ending the session stays possible even when the session itself is refused.
_SIGN_OUT: Final = ("POST", "/auth/logout")
_RETRY_AFTER_S = 5
_HTTP_METHODS: Final = frozenset({"get", "put", "post", "delete", "patch", "options", "head"})
#: (status, code, title from `x-error-codes`, detail) of each answer.
_REFUSED = (
    403,
    "mfa_enrollment_required",
    "Session is enrolment-only; enrol and confirm a TOTP method first",
    "Set up two-factor authentication to continue.",
)
_EXPIRED = (
    401,
    "unauthenticated",
    "Missing, malformed or expired access token",
    "The enrolment-only session has expired; sign in again.",
)
_UNCLASSIFIED = (
    503,
    "store_unavailable",
    "QuestDB / Postgres / Parquet tier unavailable",
    "The session could not be checked; try again shortly.",
)

#: `http` (this guard) or `ws` (the `auth` frame): logged as `channel`, counted as `transport`.
Channel = Literal["http", "ws"]
CallNext = Callable[[Request], Awaitable[Response]]


class _Sessions(Protocol):
    async def authenticate_access_token(
        self, raw_access_token: str, *, allow_locked: bool = ...
    ) -> SessionRecord: ...


class _Auth(Protocol):
    @property
    def enrolment_gate_is_active(self) -> bool: ...

    @property
    def sessions(self) -> _Sessions: ...

    async def classify(self, session: SessionRecord) -> SessionClass: ...


class _Emitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


def _log() -> Any:
    return structlog.get_logger(__name__)


def _problem(answer: tuple[int, str, str, str], **extra: Any) -> JSONResponse:
    status, code, title, detail = answer
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


def _unavailable() -> JSONResponse:
    response = _problem(_UNCLASSIFIED, retry_after_seconds=_RETRY_AFTER_S)
    response.headers["Retry-After"] = str(_RETRY_AFTER_S)
    return response


def sessionless_operations(spec: Mapping[str, Any]) -> frozenset[tuple[str, str]]:
    """(METHOD, path template) of each operation the contract serves without a session: its
    `security` admits an anonymous caller (`[]`, or a `{}` alternative), or its `x-rbac` names
    no permission with scope `none` (the pre-session invite operations; info "CSRF",
    "Exempt"). The RBAC matrix's `public: true` rows are exactly these, except the
    issue-linked rows the contract has opened ahead of the matrix (pinned by a test)."""
    out: set[tuple[str, str]] = set()
    for path, item in spec.get("paths", {}).items():
        if not isinstance(item, dict):
            continue
        for method, op in item.items():
            if method not in _HTTP_METHODS or not isinstance(op, dict):
                continue
            security, rbac = op.get("security"), op.get("x-rbac")
            anonymous = isinstance(security, list) and (security == [] or {} in security)
            pre_session = (
                isinstance(rbac, dict)
                and not rbac.get("permissions")
                and rbac.get("scope") == "none"
            )
            if anonymous or pre_session:
                out.add((method.upper(), path))
    return frozenset(out)


class EnrolmentRefusals:
    """Counts, logs and audits each refusal of an enrolment-only session (SR-125, C-2.9), for
    the HTTP guard and the WS authenticator alike.

    `auth_enrolment_refused_total{transport, reason}` counts every refusal once under its reason
    (`enrolment_only`: 403 or `bye mfa_enrollment_required`; `expired`: a session not minted as
    one, 401 or a failed `auth`; `unclassified`: the session could not be checked, 503 or a failed
    `auth`) and, for an `enrolment_only` refusal whose audit record was not written normally,
    again under `audit_throttled`, `audit_slow` or `audit_unavailable`. Only the
    `enrolment_only` refusal is an authorisation denial, so only it is audited: within a
    per-user budget (every session of a user shares it, so minting sessions buys no rows) and
    the shared tracker's in-flight cap, under `asyncio.shield`, so a timeout never cancels the
    writer mid-append. As the CSRF guard's `_emit_audit`: the write's own outcome decides
    between `audit_slow` and `audit_unavailable`, and a write that fails after the caller
    stopped waiting (timeout, or the request or socket was cancelled), or that is still running
    when the tracker drains at shutdown, counts `audit_unavailable` then. A slow or failed write
    never changes the answer."""

    def __init__(
        self,
        audit: _Emitter,
        *,
        tracker: RefusalAuditTracker,
        per_user: PerIpLoginThrottle | None = None,
        audit_timeout_s: float = AUDIT_TIMEOUT_S,
    ) -> None:
        self._audit = audit
        self._tracker = tracker
        self._per_user = per_user or PerIpLoginThrottle(
            max_attempts=SESSION_REFUSALS_PER_WINDOW, window_s=ANON_REFUSAL_WINDOW_S
        )
        self._audit_timeout_s = audit_timeout_s

    @staticmethod
    def _count(channel: Channel, reason: str) -> None:
        auth_enrolment_refused_total.labels(transport=channel, reason=reason).inc()

    def unclassified(self, exc: Exception, *, channel: Channel, method: str, path: str) -> None:
        """The session could not be looked up or classified: refused, and an error to page."""
        self._count(channel, "unclassified")
        _log().error(
            "auth.enrolment_only.unclassified",
            channel=channel,
            method=method,
            path=path,
            error=type(exc).__name__,
        )

    def expired(self, record: SessionRecord, *, channel: Channel, method: str, path: str) -> None:
        """A session that was not minted enrolment-only: overlong (Q7), or it proved a factor."""
        self._count(channel, "expired")
        _log().warning(
            "auth.enrolment_only.expired",
            channel=channel,
            method=method,
            path=path,
            session_id=str(record.id),
            user_id=str(record.user_id),
        )

    async def refused(
        self,
        record: SessionRecord,
        *,
        channel: Channel,
        method: str,
        path: str,
        ip: str | None,
    ) -> None:
        """A refusal of an operation outside the allow-list (or of the socket): counted,
        logged and audited within the budgets. *path* is a route template, never raw input."""
        self._count(channel, "enrolment_only")
        log = _log()
        fields = {"channel": channel, "method": method, "path": path}
        ids = {"session_id": str(record.id), "user_id": str(record.user_id)}
        key = f"uid:{record.user_id}"
        if self._tracker.full or self._per_user.is_blocked(key):
            self._count(channel, "audit_throttled")
            log.warning("auth.enrolment_only.refused_unaudited", **ids, **fields)
            return
        self._per_user.record_failure(key)
        log.warning("auth.enrolment_only.refused", **ids, **fields)
        task = self._tracker.track(
            self._audit.emit(
                REFUSAL_ACTION,
                actor_label=str(record.user_id),
                actor_user_id=record.user_id,
                actor_ip=ip,
                session_id=record.id,
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason="mfa_enrollment_required",
                after_state=fields,
            ),
            on_lost=lambda: self._count(channel, "audit_unavailable"),
            late_failure_event="auth.enrolment_only.audit_failed_late",
        )
        try:
            await asyncio.wait_for(asyncio.shield(task), self._audit_timeout_s)
        except TimeoutError:
            failure = task.exception() if task.done() and not task.cancelled() else None
            if failure is not None:  # the writer raised `TimeoutError` itself: it failed
                self._audit_failed(channel, failure, fields)
                return
            self._tracker.mark_timed_out(task)  # left to finish; never cancelled mid-append
            self._count(channel, "audit_slow")
            log.warning("auth.enrolment_only.audit_slow", **fields)
        except asyncio.CancelledError:
            self._tracker.mark_timed_out(task)  # a later failure is still counted
            raise
        except Exception as exc:
            self._audit_failed(channel, exc, fields)

    @staticmethod
    def _audit_failed(channel: Channel, exc: BaseException, fields: Mapping[str, str]) -> None:
        EnrolmentRefusals._count(channel, "audit_unavailable")
        _log().error("auth.enrolment_only.audit_unavailable", error=type(exc).__name__, **fields)


def make_enrolment_only_guard(
    auth: _Auth,
    *,
    refusals: EnrolmentRefusals,
    operations: Iterable[tuple[str, str]],
    sessionless: Iterable[tuple[str, str]],
) -> Callable[[Request, CallNext], Awaitable[Response]]:
    """HTTP middleware body; see the module docstring. *operations* are the contract's
    declared operations (the bounded route template of a log line or an audit record),
    *sessionless* the ones it serves without a session (`sessionless_operations`)."""
    templates = _compile_operations(frozenset(operations))
    free = frozenset(sessionless)
    free_patterns = _compile_operations(free)
    free_templates = frozenset(template for _method, template in free)

    def _needs_no_session(method: str, path: str) -> bool:
        return (
            path in PUBLIC_OPERATIONAL_ROUTES
            or match_operation(method, path, free_patterns) in free_templates
        )

    async def guard(request: Request, call_next: CallNext) -> Response:
        path = get_route_path(request.scope)
        token = _bearer(request)
        if (
            token is None
            or not auth.enrolment_gate_is_active
            or _needs_no_session(request.method, path)
        ):
            return await call_next(request)
        method = bounded_method(request.method)
        template = match_operation(method, path, templates)  # bounded: never the raw path
        try:
            # An idle-locked session is classified too: a route that accepts one
            # (`DELETE /me/sessions/{sessionId}`) must not serve an enrolment-only session.
            record = await auth.sessions.authenticate_access_token(token, allow_locked=True)
        except AuthError:
            return await call_next(request)  # no live session: the route answers itself
        except Exception as exc:  # fail closed: a session that cannot be read reaches nothing
            refusals.unclassified(exc, channel="http", method=method, path=template)
            return _unavailable()
        try:
            verdict = await auth.classify(record)
        except Exception as exc:  # fail closed: an unclassified session reaches no handler
            refusals.unclassified(exc, channel="http", method=method, path=template)
            return _unavailable()
        operation = (request.method, path)
        if verdict is SessionClass.FULL or verdict is SessionClass.USER_INACTIVE:  # inactive: #2911
            return await call_next(request)
        if verdict is SessionClass.ENROLMENT_ONLY_EXPIRED and operation != _SIGN_OUT:
            refusals.expired(record, channel="http", method=method, path=template)
            return _problem(_EXPIRED)
        if operation in ENROLMENT_OPERATIONS:
            return await call_next(request)
        ip = source_ip(request.scope)
        await refusals.refused(record, channel="http", method=method, path=template, ip=ip)
        return _problem(_REFUSED)

    return guard


__all__ = [
    "ENROLMENT_OPERATIONS",
    "REFUSAL_ACTION",
    "EnrolmentRefusals",
    "make_enrolment_only_guard",
    "sessionless_operations",
]
