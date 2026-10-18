"""`POST /auth/step-up`, owner TOTP reset and the read-only write guard
(E09-S04, US-ONB-005/010).

Thin HTTP adapter over `auth.step_up.StepUpService`. `auth` may not import
`audit`: the B16 chart writes `auth.step_up_granted`, `auth.step_up_failed`
(a wrong factor), `auth.step_up_required` and `auth.session_readonly_downgrade`;
this module writes `auth.mfa_reset_by_owner`, `auth.step_up_mismatch` and the
`auth.step_up_failed` of a refused challenge (see below). Elevation state is
server-side, keyed by the session id resolved from the bearer token - nothing the client sends can
forge it. `require_elevation_for` is the `is_dangerous` gate E09-T03 routes
call: every refusal is a challenge for the one request it refused, and a no-grace
class passes only with the one-shot grant bound to that request (#2304).
`make_read_only_guard` is the middleware refusing every write during the
5-minute downgrade. A step-up that cannot answer its challenge is audited
`auth.step_up_failed` (DENIED, the refusal rule as reason) within a
per-session budget; no factor is checked or counted. That record, the reset's and
`auth.step_up_mismatch` are written ahead of their answer, within `AUDIT_TIMEOUT_S`:
a writer that is down or slow makes the answer `503 audit_unavailable`, never the 400, 403 or 200.
"""

from __future__ import annotations

import asyncio
import inspect
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any, Protocol

import structlog
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

# The function `starlette.routing` itself matches routes with (it only re-imports
# it, so mypy --strict refuses that path): the guard classifies what the router
# dispatches on, by construction. A move upstream fails the import, never open.
from starlette._utils import get_route_path

from candleviewer.admin.flags.store import FlagWrite, StoreUnavailableError
from candleviewer.api.csrf import (
    ANON_REFUSAL_WINDOW_S,
    AUDIT_TIMEOUT_S,
    SESSION_REFUSALS_PER_WINDOW,
)
from candleviewer.api.step_up_challenge import ChallengeText
from candleviewer.api.storage_outage import is_storage_outage
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.actions import UnknownAuditAction
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.errors import (
    AuthError,
    SelfResetRefused,
    SessionReadOnly,
    SessionRevoked,
    StepUpChallengeRefused,
    StepUpCodeInvalid,
    StepUpMismatch,
    StepUpRequired,
    UnknownActionClass,
)
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.auth.step_up import (
    ACTION_CLASSES,
    NO_GRACE_ACTION_CLASSES,
    PositionStateProvider,
    StepUpChallenge,
    StepUpService,
)
from candleviewer.auth.throttle import PerIpLoginThrottle
from candleviewer.observability.redaction import redact_text
from candleviewer.ws._generated.error_codes import ERROR_META, ErrorCode

_PROBLEM = "application/problem+json"
#: `403 step_up_required`'s title and detail on every route that issues a challenge (#2304): the
#: contract's title, and what the step-up asks for - the password and the code (#1778) - in
#: words the dialog shows verbatim.
STEP_UP_REQUIRED_TITLE = "A dangerous action needs a live step-up elevation for its action class"
STEP_UP_REQUIRED_DETAIL = (
    "Re-enter your password and authenticator code (POST /auth/step-up) to continue."
)
#: `403 session_read_only`'s title and detail wherever a read-only session is refused (#2304): the
#: write guard (`readonly_problem`) and `api.rules_actor`, which refuses a session that turned
#: read-only inside its own request.
SESSION_READ_ONLY_TITLE = "Session is read-only"
SESSION_READ_ONLY_DETAIL = (
    "Too many invalid step-up codes; this session is read-only for 5 minutes."
)
#: `503 audit_unavailable` where the record an answer is written ahead of cannot be written
#: (C-2.9): the catalogued code and title (`x-error-codes`), also for `api.rules_actor`.
AUDIT_UNAVAILABLE_CODE = ErrorCode.AUDIT_UNAVAILABLE.value
AUDIT_UNAVAILABLE_TITLE = ERROR_META[ErrorCode.AUDIT_UNAVAILABLE].title
AUDIT_UNAVAILABLE_DETAIL = "audit unavailable"
#: What `AuditService.writer` raises before `start()`; any other `RuntimeError` is a defect.
_AUDIT_NOT_STARTED = "AuditService.start() has not wired"
#: `400 validation_failed` details for a step-up that cannot answer its challenge (#2304).
_CHALLENGE_REFUSED = {
    "challenge_required": "A step-up for this action class must send the challenge_id.",
    "challenge_expired": "The step-up challenge cannot be answered.",
    "challenge_mismatch": "action_class does not match the step-up challenge.",
    "required": "There is no step-up challenge to answer; send action_class.",
    "format": "challenge_id must be a UUID.",
}
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
#: Writes that must keep working in the downgrade (ending the session).
_WRITE_EXEMPT_PATHS = frozenset({"/auth/logout", "/auth/step-up"})


class AuditRefused(Exception):
    """A write-ahead audit record could not be written in time; nothing was changed."""


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _StepUpBody(BaseModel):
    """`authStepUp`'s request body, validated whole (C-12.4): unknown members are refused."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(pattern=r"^[0-9]{6}$")
    password: str = Field(min_length=1, max_length=512)  # as `LoginRequest.password`
    challenge_id: uuid.UUID | None = None
    #: Checked against the closed class set by `StepUpService` (`UnknownActionClass`).
    action_class: str | None = None


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


def _audit_unavailable() -> JSONResponse:
    return _problem(503, AUDIT_UNAVAILABLE_CODE, AUDIT_UNAVAILABLE_TITLE, AUDIT_UNAVAILABLE_DETAIL)


async def _ahead(record: Awaitable[None]) -> None:
    """Await the audit record an answer depends on, ahead of the answer (C-2.9): `AuditRefused`
    when the writer is down or not started, or takes longer than `AUDIT_TIMEOUT_S`, so the
    request fails closed and a stalled WAL cannot hold it. `AuditWriter.emit` is safe to cancel
    at the bound (#2250). A defect is not an outage and propagates (a 500, never a retryable
    503): an `UnknownAuditAction` (a call site names an action the registry lacks) and a
    `RuntimeError` other than "audit not started"."""
    try:
        async with asyncio.timeout(AUDIT_TIMEOUT_S):
            await record
    except (AuditError, RuntimeError, TimeoutError) as exc:
        if isinstance(exc, UnknownAuditAction) or (
            isinstance(exc, RuntimeError) and not str(exc).startswith(_AUDIT_NOT_STARTED)
        ):
            raise
        _log().error("auth.step_up_audit_refused", error=type(exc).__name__)
        raise AuditRefused from exc


def _bearer(request: Request) -> str | None:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    return value.strip() or None if scheme.lower() == "bearer" else None


def readonly_problem(exc: SessionReadOnly) -> JSONResponse:
    until = exc.until.isoformat() if hasattr(exc.until, "isoformat") else None
    return _problem(
        403,
        "session_read_only",
        SESSION_READ_ONLY_TITLE,
        SESSION_READ_ONLY_DETAIL,
        readonly_until=until,
    )


def _unauthenticated() -> JSONResponse:
    """`401 unauthenticated`, as the contract catalogues it (`x-error-codes`)."""
    title = "Missing, malformed or expired access token"
    return _problem(401, "unauthenticated", title, "authentication required")


def _challenge_refused(field: str, rule: str) -> JSONResponse:
    detail = _CHALLENGE_REFUSED[rule]
    return _problem(
        400,
        "validation_failed",
        "Request body or parameters failed schema validation",
        detail,
        errors=[{"field": field, "rule": rule, "message": detail}],
    )


def _invalid_body(exc: ValidationError) -> JSONResponse:
    """The body is not `authStepUp`'s schema: a missing, empty or over-long `password` is 422
    (contract), a malformed `challenge_id` the `format` refusal (its fixed message: the UUID
    parser's quotes a character of the input), anything else 400. Decided before any factor is
    checked. Nothing the client sent is echoed: a member the schema does not declare is
    reported as `body`, never by name."""
    errors = exc.errors(include_url=False, include_context=False, include_input=False)
    declared = _StepUpBody.model_fields
    fields = [
        str(err["loc"][0]) if err["loc"] and err["loc"][0] in declared else "body" for err in errors
    ]
    if "password" in fields:
        long = any(
            field == "password" and err["type"] == "string_too_long"
            for field, err in zip(fields, errors, strict=True)
        )
        detail = "password is too long" if long else "password is required"
        return _problem(422, "validation_failed", "Unprocessable entity", detail)
    if "challenge_id" in fields:
        return _challenge_refused("challenge_id", "format")
    return _problem(
        400,
        "validation_failed",
        "Request body or parameters failed schema validation",
        "The step-up body does not match its schema.",
        errors=[
            {"field": field, "rule": err["type"], "message": redact_text(err["msg"])}
            for field, err in zip(fields, errors, strict=True)
        ],
    )


def required_problem(challenge: StepUpChallenge, text: ChallengeText | None = None) -> JSONResponse:
    """`403 step_up_required`: the challenge issued for the one request it refused (#2304),
    restating it in the server-composed `text` of a route that validated its request."""
    restated = (
        {} if text is None else {"action_summary": text.action_summary, "target": text.target}
    )
    return _problem(
        403,
        "step_up_required",
        STEP_UP_REQUIRED_TITLE,
        STEP_UP_REQUIRED_DETAIL,
        action_class=challenge.action_class,
        challenge_id=str(challenge.challenge_id),
        challenge_expires_at=challenge.expires_at.isoformat(),
        **restated,
    )


@dataclass(frozen=True)
class SpentGrant:
    """The one-shot grant a request used (#2799): the entry `StepUpService.consume_single_use`
    removed from the session row by its conditional write, kept as it returned it and never read
    back, so the handler's audit record names `challenge_id`. Read only on access, so
    `consume_bound_grant`, which discards it, never reads it."""

    grant: StepUpChallenge

    @property
    def challenge_id(self) -> uuid.UUID:
        return self.grant.challenge_id

    @property
    def action_class(self) -> str:
        return self.grant.action_class


async def spend_bound_grant(
    step_up: StepUpService,
    emitter: _Emitter | None,
    session_id: str,
    action_class: str,
    fingerprint: str,
) -> SpentGrant | StepUpChallenge:
    """No-grace gate (#2304): the `SpentGrant` this request used when the grant was bound to
    `fingerprint`, else the challenge issued for this request. A grant bound to another request
    is left in place and the mismatch is audited first (write-ahead, C-2.9, `AuditRefused` when
    it cannot be): no emitter means no answer."""
    try:
        grant = await step_up.consume_single_use(session_id, action_class, fingerprint=fingerprint)
    except StepUpMismatch as exc:
        if emitter is None:
            raise RuntimeError("auth.step_up_mismatch: no audit emitter wired") from exc
        await _ahead(
            emitter.emit(
                "auth.step_up_mismatch",
                actor_label=exc.user_id,
                actor_user_id=exc.user_id,
                session_id=session_id,
                object_kind="step_up_challenge",
                object_id=exc.challenge_id,
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason=action_class,
                after_state={
                    "bound_request_sha256": exc.bound,
                    "refused_request_sha256": fingerprint,
                },
            )
        )
    except StepUpRequired:
        pass
    else:
        return SpentGrant(grant)
    return await step_up.record_pending(session_id, action_class, fingerprint=fingerprint)


async def consume_bound_grant(
    step_up: StepUpService,
    emitter: _Emitter | None,
    session_id: str,
    action_class: str,
    fingerprint: str,
) -> StepUpChallenge | None:
    """`spend_bound_grant` for a caller that records no spend: None when the grant bound to
    `fingerprint` was used, else the challenge issued for this request. It raises as
    `spend_bound_grant` does, which `api.rules_actor` relies on: the mismatch is audited first,
    `AuditRefused` when it cannot be, and no emitter means no answer."""
    spent = await spend_bound_grant(step_up, emitter, session_id, action_class, fingerprint)
    return None if isinstance(spent, SpentGrant) else spent


async def require_elevation_for(
    auth: _AuthLike,
    session_id: str,
    action_class: str,
    *,
    text: ChallengeText | None = None,
    fingerprint: str | None = None,
    emitter: _Emitter | None = None,
) -> JSONResponse | None:
    """The `is_dangerous` decision-point hook (E09-T03 routes call this):
    None when elevated, else the problem to return. A no-grace class has no
    window to check: the request spends the one-shot grant of a fresh code,
    so each gated request needs its own (#2751). A refusal issues the
    challenge for this request, restated by `text` when the route validated
    it. An unregistered class is a server defect, never a challenge (500); a
    revoked session is a 401. A no-grace class passes only with the grant bound to
    `fingerprint`, the SHA-256 of the request the route validated
    (`api.step_up_challenge.request_fingerprint`); a route that cannot bind its
    request fails closed."""
    step_up = auth.step_up
    try:
        if action_class in NO_GRACE_ACTION_CLASSES:
            if fingerprint is None:
                raise TypeError(f"{action_class} gate needs the request fingerprint")
            challenge = await consume_bound_grant(
                step_up, emitter, session_id, action_class, fingerprint
            )
            return None if challenge is None else required_problem(challenge, text)
        try:
            await step_up.require_elevation(session_id, action_class)
        except StepUpRequired:
            return required_problem(await step_up.record_pending(session_id, action_class), text)
    except SessionReadOnly as exc:
        return readonly_problem(exc)
    except SessionRevoked:
        return _unauthenticated()
    except AuditRefused:  # the mismatch record could not be written ahead: no answer, no challenge
        return _audit_unavailable()
    except UnknownActionClass:
        # The route demanded a class the service does not register: a defect to fix, not a user
        # error. One line for the operator; the class is a server-side constant, never a secret.
        _log().error("auth.step_up_unregistered_class", action_class=action_class)
        return _problem(500, "internal_error", "Internal error", "unregistered step-up class")
    return None


async def require_session_elevation(
    auth: _AuthLike,
    session_id: object | None,
    action_class: str,
    text: ChallengeText | None = None,
    *,
    fingerprint: str | None = None,
    emitter: _Emitter | None = None,
) -> JSONResponse | None:
    """`require_elevation_for` for a handler that resolved its caller itself (#2304): with no
    session there is nothing to elevate and no challenge to issue (401), and sessions wired
    without step-up are a wiring fault (503, as on the path-gated routes), never a refusal no
    client could answer. A challenge restates `text`, and a no-grace class needs the
    `fingerprint` of the request, as there."""
    if session_id is None:
        return _unauthenticated()
    if not auth.step_up_is_active:
        return _problem(503, "service_unavailable", "Service unavailable", "step-up not wired")
    return await require_elevation_for(
        auth, str(session_id), action_class, text=text, fingerprint=fingerprint, emitter=emitter
    )


class StepUpRefused(Exception):
    def __init__(self, response: JSONResponse) -> None:
        super().__init__("step-up refused")
        self.response = response  # the problem the route answers with


def step_up_port(
    auth: _AuthLike, restate: Callable[[FlagWrite], ChallengeText], emitter: _Emitter | None
) -> Callable[[AuditPrincipal, str, FlagWrite, str | None], Awaitable[None]]:
    """`require_session_elevation` raising `StepUpRefused`, for a writer that picks the action
    class itself under its lock (the feature-flag writer); a challenge restates the validated
    change the writer gives, by the route's template `restate` (#2304). A no-grace class
    passes only with the grant bound to `fingerprint`, which the route computed from the
    request it validated; `emitter` writes the `auth.step_up_mismatch` of another request's."""

    async def demand(
        who: AuditPrincipal, action_class: str, change: FlagWrite, fingerprint: str | None
    ) -> None:
        text = restate(change)
        try:
            refused = await require_session_elevation(
                auth, who.session_id, action_class, text, fingerprint=fingerprint, emitter=emitter
            )
        except Exception as exc:  # an outage is the writer's: counted, logged and recorded
            if not is_storage_outage(exc):
                raise
            raise StoreUnavailableError(type(exc).__name__) from None
        if refused is not None:
            raise StepUpRefused(refused)

    return demand


async def require_bound_elevation(
    auth: _AuthLike,
    session_id: object | None,
    action_class: str,
    *,
    fingerprint: str,
    emitter: _Emitter,
    text: ChallengeText | None = None,
) -> JSONResponse | SpentGrant:
    """The no-grace gate of a handler that names the grant it spends (#2799): the `SpentGrant`
    this request used, else the problem to return, mapped as `require_elevation_for` maps it,
    a refusal being the challenge for this request restated by `text`. No session is a 401 and
    sessions wired without step-up a 503, as in `require_session_elevation`. A grace class
    binds no request (its step-up opens a window, never a grant): naming one fails closed."""
    if action_class in ACTION_CLASSES - NO_GRACE_ACTION_CLASSES:
        raise TypeError(f"{action_class} has a grace window: it binds no request")
    if session_id is None:
        return _unauthenticated()
    if not auth.step_up_is_active:
        return _problem(503, "service_unavailable", "Service unavailable", "step-up not wired")
    try:
        spent = await spend_bound_grant(
            auth.step_up, emitter, str(session_id), action_class, fingerprint
        )
    except SessionReadOnly as exc:
        return readonly_problem(exc)
    except SessionRevoked:
        return _unauthenticated()
    except AuditRefused:  # the mismatch record could not be written ahead: no answer, no challenge
        return _audit_unavailable()
    except UnknownActionClass:  # a defect, as in `require_elevation_for`
        _log().error("auth.step_up_unregistered_class", action_class=action_class)
        return _problem(500, "internal_error", "Internal error", "unregistered step-up class")
    return spent if isinstance(spent, SpentGrant) else required_problem(spent, text)


#: `is_dangerous` routes (permissions seeded `is_dangerous=true`) -> the
#: step-up action class that must be elevated. Method + path regex. Paths are
#: the `22-api-openapi.yaml` contract; entries for routes that later epics
#: implement (E27 keys, E44/E39 risk, E16-T08 retention) are pre-registered so
#: they are gated the moment they are mounted.
#: `tests/unit/api/test_dangerous_route_registry.py` fails if any mounted route
#: matching `DANGEROUS_PATH_PATTERN` is missing here or in `HANDLER_GATED_ROUTES`,
#: and (#3083) if any mounted operation of any method that the contract or the RBAC
#: seed marks for step-up is in neither registry nor its reasoned allow-list.
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
    # #2751 (SR-025, 04 §7.2.2 rows 38, 40, 50, 52). Mounted today: the export and deleteUser.
    ("PATCH", re.compile(r"^/users/[^/]+$"), "users"),  # updateUser
    ("DELETE", re.compile(r"^/users/[^/]+$"), "users"),  # deleteUser
    ("PUT", re.compile(r"^/users/[^/]+/account-access$"), "users"),  # setUserAccountAccess
    ("POST", re.compile(r"^/admin/audit/export$"), "audit"),  # exportAuditLog
    # #2738 (SR-025, 04 §7.2.2 row 9, Owner and Manager): every request changes retention.
    ("PUT", re.compile(r"^/recording/retention-policies$"), "recorder"),  # setRetentionPolicies
    ("PUT", re.compile(r"^/recording/symbols/[^/]+/pin$"), "recorder"),  # pinRecordedSymbol
)

#: These routes cannot be gated by path alone: kill-switch *engage* must
#: never wait for a code (emergency stop) and switching *to demo* is not
#: dangerous, so only the handler (body- or query-aware) knows. Each entry is a
#: declaration that the handler demands elevation of that class for its
#: dangerous branch (a route with several such branches has a row per class);
#: the owning epic must add a test proving it.
HANDLER_GATED_ROUTES: tuple[tuple[str, str, str], ...] = (
    ("POST", "/trading/kill-switch", "killswitch"),  # E39: release only
    ("POST", "/session/environment", "live_enablement"),  # E44: to live only
    ("PUT", "/rules/{ruleId}/mode", "live_enablement"),  # E35-S01: arming a live-scoped rule
    # E16-T06: irreversible purge. The handler checks RBAC, then owner-only (capability 9a),
    # THEN step-up, so a non-owner gets the audited `purge_owner_only`, not a step-up prompt.
    ("POST", "/admin/recorder/purge", "recorder"),
    # restoreBackup (04 §7.2.2 row 52, #2751), no-grace and irreversible. A no-grace grant is
    # bound to the request its handler validated (#2304), which a path alone cannot name, so a
    # path-gated no-grace class fails closed: the handler gates it after RBAC and validation, with
    # `require_bound_elevation(..., fingerprint=request_fingerprint(...), emitter=...)`. Not
    # mounted yet: its ticket drops it from the registry test's `_PENDING_HANDLER_GATES` and adds
    # the handler test. The restore's write-ahead audit record must name the `challenge_id` of
    # the `SpentGrant` that gate returns (B16 records no spend: #2799).
    ("POST", "/admin/backups/{backupId}/restore", "backups"),
    # #2738 (SR-025, 04 §7.2.2 rows 8, 9 and 9a). Not mounted yet: the E16-T08 (#492) PR that
    # mounts them must drop them from the registry test's `_PENDING_HANDLER_GATES` (it fails
    # while a listed route is mounted), add the handler test, and demand `recorder` elevation
    # on every branch that changes retention or deletes recorded data; the rest is row 8.
    # - addRecordedSymbol: `pinned: true` or a non-default `retention_days`; a re-add must not
    #   change the retention of data kept from an earlier recording either. A plain add (the
    #   rules vocabulary's `{symbol}` hint) passes.
    # - updateRecordedSymbol: `pinned` or `retention_days` in the body (streams, depth: row 8).
    # - removeRecordedSymbol: `purge_data=true`, after the owner-only check, as the purge route
    #   orders them. Open for E16-T08 and security: stopping a pinned symbol drops its pin for
    #   the reaper (pins are read only from rows not removed), so either refuse that until it
    #   is unpinned through the gated pin route, or gate that branch as well.
    ("POST", "/recording/symbols", "recorder"),
    ("PATCH", "/recording/symbols/{recordedSymbolId}", "recorder"),
    ("DELETE", "/recording/symbols/{recordedSymbolId}", "recorder"),
    # #3083 (AD-F01). Not mounted yet either: the PR that mounts one drops it from
    # `_PENDING_HANDLER_GATES` and adds the handler test.
    # - setFeatureFlag (E42-T03, #964): the class is chosen after request validation, under the
    #   row lock, from the key and the stored value (an unreadable row counts as its fail-closed
    #   value): releasing a kill-switch-class flag needs `killswitch`, writing `true` to
    #   `trading.live_enabled` needs `live_enablement` (both no-grace), any other write `flags`.
    ("PUT", "/admin/feature-flags/{flagKey}", "flags"),
    ("PUT", "/admin/feature-flags/{flagKey}", "killswitch"),
    ("PUT", "/admin/feature-flags/{flagKey}", "live_enablement"),
    # - downloadAuditExport (E42-T02, #889): `audit` within its grace window, checked by the
    #   operation after the requester check, so anyone but the requester gets `404`, never a
    #   challenge. A GET with no path row: the guard passes it straight to the handler.
    ("GET", "/admin/audit/exports/{jobId}", "audit"),
    # #3085 startViewAs (SR-025, 04 §7.2.2 row 40b): RBAC and the five view-as refusals come
    # before the gate, so only the handler can gate it. Not mounted yet: pending in the test.
    ("POST", "/admin/view-as", "users"),
)

#: Mounted write routes whose path matches this must be in one of the two
#: registries above (deny-by-default for future tickets). The recording and
#: recorder prefixes are swept whole (SR-025: recorded data can be deleted from
#: under any of them, #2738); their writes without step-up are allow-listed,
#: each with its 04 §7.2.2 row, in the registry test. `feature-flags` (#3083):
#: a flag write is owner-equivalent configuration (live gate, kill switches). `view-as`
#: (#3085): an impersonation start, handler-gated.
DANGEROUS_PATH_PATTERN = re.compile(
    r"^/(admin/)?(users|exchange-accounts/[^/]+/keys|keys|live|kill|trading/kill-switch"
    r"|session/environment|risk/lockouts|recording[^/]*|recorder[^/]*|audit|backups"
    r"|feature-flags|view-as)(/|$)"
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
    refusal_budget: PerIpLoginThrottle | None = None,
) -> APIRouter:
    """`audit_ready()` false -> the owner TOTP reset answers 503 before changing
    anything: it cannot be undone, so its audit record must be writable (C-2.9)."""
    if emitter is None:
        raise TypeError("make_step_up_router: audit emitter is required")
    router = APIRouter(tags=["auth"])
    # Challenge refusals are audited up to a per-session budget, as `auth.csrf_refused` is,
    # so an in-session flood cannot grow the audit log without bound.
    refusals = refusal_budget or PerIpLoginThrottle(
        max_attempts=SESSION_REFUSALS_PER_WINDOW, window_s=ANON_REFUSAL_WINDOW_S
    )

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

    async def _refused(record: SessionRecord, rule: str, challenge_id: uuid.UUID | None) -> None:
        """Audit a step-up that cannot answer its challenge (C-12.8), before its 400: the rule
        and the presented `challenge_id`, never a factor or a body. A record that cannot be
        written ahead of the answer is `AuditRefused`: the answer is 503, never the 400."""
        key = f"sid:{record.id}"
        if refusals.is_blocked(key):  # over budget: still refused, not audited
            _log().warning("auth.step_up_refused.unaudited", rule=rule)
            return
        refusals.record_failure(key)
        await _ahead(
            _audit(
                "auth.step_up_failed",
                record,
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason=rule,
                object_kind="step_up_challenge",
                object_id=None if challenge_id is None else str(challenge_id),
            )
        )

    @router.post("/auth/step-up")
    async def step_up(request: Request) -> JSONResponse:
        got = await _session(request)
        if isinstance(got, JSONResponse):
            return got
        record = got
        try:
            raw = await request.json()
        except ValueError:
            raw = None
        try:  # a body that is not an object has none of the members
            body = _StepUpBody.model_validate(raw if isinstance(raw, dict) else {})
        except ValidationError as exc:
            return _invalid_body(exc)
        # The server decides the class: the one its live challenge names. A
        # client-supplied value is only a cross-check (mismatch -> 400, #2304).
        try:
            grant = await auth.step_up.step_up(
                str(record.user_id),
                str(record.id),
                body.action_class,
                body.code,
                body.password,
                challenge_id=body.challenge_id,
            )
        except StepUpChallengeRefused as exc:  # decided before any factor is checked
            try:
                await _refused(record, exc.rule, body.challenge_id)
            except AuditRefused:
                return _audit_unavailable()
            return _challenge_refused(exc.field, exc.rule)
        except SessionRevoked:
            return _unauthenticated()
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
        if user_id == record.user_id:  # no step-up can cure it: a refusal, never a challenge
            return _problem(403, "forbidden", "Forbidden", "owners cannot reset their own TOTP")
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
            return _audit_unavailable()

        async def write_ahead(methods: int, sessions: int, /) -> None:
            """C-2.9 (#2510): awaited by `reset_totp` before its first revoke, with the
            counts it is about to revoke (the reset cannot be undone)."""
            await _ahead(
                _audit(
                    "auth.mfa_reset_by_owner",
                    record,
                    severity=Severity.CRITICAL,
                    object_kind="user",
                    object_id=str(user_id),
                    after_state={"methods_revoked": methods, "sessions_revoked": sessions},
                )
            )

        try:
            result = await auth.step_up.reset_totp(
                actor_session_id=str(record.id),
                actor_user_id=str(record.user_id),
                target_user_id=str(user_id),
                audit=write_ahead,
            )
        except SelfResetRefused:
            return _problem(403, "forbidden", "Forbidden", "owners cannot reset their own TOTP")
        except SessionReadOnly as exc:  # downgraded after the gate, as `require_elevation_for`
            return readonly_problem(exc)
        except StepUpRequired:  # the grace window lapsed after the gate: a new challenge
            try:
                challenge = await auth.step_up.record_pending(str(record.id), "users")
            except SessionRevoked:  # the session ended in that window: nothing to challenge
                return _unauthenticated()
            return required_problem(challenge)
        except AuditRefused:
            return _audit_unavailable()
        # Reveals nothing: no secret, recovery code or position data.
        return JSONResponse(
            {
                "target_user_id": str(result.target_user_id),
                "methods_revoked": result.methods_revoked,
                "sessions_revoked": result.sessions_revoked,
            }
        )

    return router


__all__ = [
    "SpentGrant",
    "StepUpRefused",
    "make_read_only_guard",
    "make_step_up_router",
    "require_bound_elevation",
    "require_elevation_for",
    "require_session_elevation",
    "step_up_port",
]
