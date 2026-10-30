"""`SessionService` — the M18 core for E09-S03 (US-ONB-004/009): session
minting, refresh-token rotation with family-reuse revocation, idle lock,
absolute expiry, and sign-out-everywhere.

Every Gherkin scenario in the ticket maps to a method here:

- `mint()` — first-login session creation (called after `LoginService`/
  `MfaService` complete the two-legged login, per those modules' own
  `NotImplementedError`/`MfaVerifiedResult` "E09-S03 scope" notes).
- `refresh()` — "Refresh-token reuse kills the family".
- `touch()` — the one activity: re-stamps `last_seen_at`. Its production caller is
  `POST /auth/session/extend`; no other request is activity (#2300).
- `require_active()` — "Order entry is refused while locked": the
  per-request/per-WS-frame revocation + idle-lock check every caller in
  the OMS/WS path must run before honouring a session id.
- `unlock()` — "Unlock restores context": password-only re-auth while
  still within the absolute lifetime.
- `lock()` — CMP-098 "Lock now" (#4743): the session locks at once, its lock a fact
  on its row (`locked_at`) that every check above reads; only `unlock()` lifts it.
- `revoke()` / `revoke_all()` — single-session revoke and sign-out-
  everywhere (SCR-112).
- `classify_session()` — #2295: the enrolment-only class of a resolved
  session, derived from its user's state (`AuthService.classify` reads the
  user store; this service never reads `users`).

Audit emission is the router's job, exactly like `LoginService`/
`MfaService` (`auth` may not import `audit` — `forbidden-M18`); this module
raises typed errors and returns typed results only. The one exception is the backstop of
`require_active`, which no router wraps (any route and the WS `auth` reach it), and of a refused
`refresh()` (#3331): it hands each revocation to an injected `BackstopAuditSink` (C-2.9, #3120).
The backstop runs as one owned unit that a cancelled request cannot cut short (#3332).

Revocation propagation (#2272, `23-ws-protocol.md` §9.5) is this module's:
every path that revokes a session publishes its id to the injected
`RevocationSink` after the row update, so no caller can forget to. A
refresh-token rotation is not published: the client re-`auth`s its socket
in place (§4.1).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import secrets
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import structlog

from candleviewer.auth.errors import (
    RefreshReuseDetected,
    SessionIdleLocked,
    SessionNotFound,
    SessionNotLocked,
    SessionRevoked,
    UnlockPasswordInvalid,
    UserDisabled,
)
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.metrics import (
    auth_disabled_user_sessions_revoked_total,
    auth_idle_locks_total,
    auth_refresh_reuse_total,
    auth_refresh_total,
    auth_session_revocations_total,
    auth_sessions_active,
    normalise_reason,
)
from candleviewer.auth.models import (
    MintedSession,
    RefreshOutcome,
    SessionIntrospection,
    SessionRecord,
    SessionView,
    UserRecord,
    UserStatus,
)
from candleviewer.auth.session_repository import LockWriteAhead, SessionRepository
from candleviewer.auth.view_as import ViewAsState
from candleviewer.observability.context import spawn

#: Ticket "Scope / Deliverables": "12 h absolute lifetime".
ABSOLUTE_LIFETIME = timedelta(hours=12)

#: #2295 (Q7): an enrolment-only session lives at most this long from sign-in.
#: `refresh()` hands the absolute `expires_at` on, so rotation never extends it;
#: `classify_session` refuses an enrolment-only session that would outlive it.
ENROLMENT_ONLY_LIFETIME = timedelta(minutes=15)

#: ADR-0020 decision 3: opaque access-token TTL (12 min).
ACCESS_TOKEN_TTL = timedelta(minutes=12)

#: Ticket: "5-60 min idle lock" — default 15 (per-user configurable,
#: `sessions.idle_timeout_s` on the row, min/max enforced at the API edge
#: this ticket's router owns, not here).
DEFAULT_IDLE_TIMEOUT_S = 900
MIN_IDLE_TIMEOUT_S = 300
MAX_IDLE_TIMEOUT_S = 3600

#: Review finding (PR #1628, low): unlock() previously allowed unlimited
#: password guesses against a locked session with no penalty. Five
#: consecutive wrong-password unlock attempts against the *same* session
#: revoke it outright (ticket "becomes a full sign-in" is then the caller's
#: only path back in), mirroring `LoginService`'s own 5-try account lockout.
MAX_UNLOCK_ATTEMPTS = 5

Clock = Callable[[], datetime]

#: `(session_id, reason)`, awaited once per revoked session after its row
#: update. The composition root wires it to the WS `RevocationHub` (`auth`
#: never imports `ws`) and maps `reason`, the revoke reason, to the client's
#: closed `bye` set (#2272).
RevocationSink = Callable[[str, str], Awaitable[None]]

#: `unlock(check=...)`: verifies the account password. `POST /auth/unlock` (#2300)
#: passes login's Argon2id path and lockout counters (SR-015, SR-016).
PasswordCheck = Callable[[str], Awaitable[bool]]


class UnlockOutcome(StrEnum):
    """What a password check decided, handed to `unlock(write_ahead=...)` before any
    row changes (C-2.9): the lock lifts, a wrong password is refused, or a wrong
    password reached `MAX_UNLOCK_ATTEMPTS` and revokes the session."""

    UNLOCKED = "unlocked"
    FAILED = "failed"
    REVOKED = "revoked"


#: `unlock(write_ahead=...)`: awaited with the decided outcome before the row changes.
UnlockWriteAhead = Callable[[UnlockOutcome], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class BackstopRevocation:
    """A session `require_active` or a refused `refresh()` revoked as `user_disabled` (SR-029,
    #3120, #3331): what the audit record needs, and nothing that could be a credential."""

    session_id: uuid.UUID
    user_id: uuid.UUID
    user_status: UserStatus | None  # `None`: the user row is gone


#: Awaited once per session `require_active` or a refused `refresh()` revoked as `user_disabled`,
#: after the revoke, the count, the log and the publish. The composition root wires it to the
#: audit lane, the writer its fallback (ADR-0037; `auth` never imports `audit`, `forbidden-M18`;
#: C-2.9):
#: `AuthService.attach_backstop_audit`.
BackstopAuditSink = Callable[[BackstopRevocation], Awaitable[None]]

#: Longest the backstop waits for that port before `require_active` or `refresh()` answers, and
#: longest a cancelled one still waits for its backstop to finish (#3332). The record may still
#: land (the real port shields its write), and the revocation never depends on it.
BACKSTOP_AUDIT_TIMEOUT_S = 2.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


async def publish_revoked(
    sink: RevocationSink | None, session_ids: Iterable[str], reason: str
) -> None:
    """Publish each revoked session id to *sink*. Callers run this after the
    row update, so a closed socket cannot re-`auth` on the same session. A
    failed publish is logged and skips nothing else: the revocation stands,
    and that socket still ends at its access token's expiry at the latest."""
    if sink is None:
        return
    for session_id in session_ids:
        try:
            await sink(session_id, reason)
        except Exception:  # isolate the sink: the other sessions must still close
            _log().error(
                "auth.session_revocation_publish_failed",
                session_id=session_id,
                reason=reason,
                exc_info=True,
            )


def _hash_refresh_token(token: str) -> str:
    """`sessions.refresh_token_hash` is `sha256_hex` per the schema — the
    raw token is never persisted, mirroring `LoginService._hash_mfa_
    token`'s identical rationale."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_access_token(token: str) -> uuid.UUID:
    """Opaque access handle -> the `sessions.access_token_jti` lookup value
    (ADR-0020: hashed at rest, never plaintext). SHA-256 truncated to 128
    bits, carried in the existing uuid column."""
    return uuid.UUID(bytes=hashlib.sha256(token.encode("utf-8")).digest()[:16])


def is_live_session(session: SessionRecord, *, now: datetime) -> bool:
    """Read-only twin of the strict acceptance rule of `authenticate_access_token`
    (`allow_locked=False`, which ends in `require_active`): not revoked, not
    absolute-expired, not idle-locked, and the access handle within
    `ACCESS_TOKEN_TTL`. No state change; used to decide whether a CSRF refusal is
    bound to a session that could actually act (#2238 review). A property test pins
    the two together (#2264).

    The `allow_locked=True` path (logout, revoke) is laxer on purpose: an idle-locked session
    can still act there, which this predicate does not model, so a CSRF refusal on those
    routes for such a session draws on the per-IP audit budget (conservative). The user's
    status is not part of it either: `peek_access_token` reads none, and `require_active`
    refuses and revokes a disabled user's session itself (#2911)."""
    return (
        not session.is_revoked
        and not session.is_absolute_expired(now=now)
        and not session.is_idle_locked(now=now)
        and now < session.issued_at + ACCESS_TOKEN_TTL
    )


def refresh_refused_as_locked(session: SessionRecord, *, now: datetime) -> bool:
    """Read-only twin of `SessionService.refresh`'s idle-lock refusal: true exactly when
    `refresh()` would raise `SessionIdleLocked` for *session* as `peek_refresh` read it. The checks
    `refresh()` makes first come first here too: a revoked session (a rotated one included), one
    past its absolute lifetime and one of a disabled or deleted user are never refused as locked,
    so `POST /auth/refresh` can answer `session_idle_locked` before its write-ahead record without
    hiding a reuse, an expiry or the backstop (#3331). No state change; `refresh()` keeps its own
    checks, and a test pins the two together on every row (as #2264 pins `is_live_session`)."""
    return (
        not session.is_revoked
        and not session.is_absolute_expired(now=now)
        and session.user_status not in (UserStatus.DISABLED, None)
        and session.is_idle_locked(now=now)
    )


def clamp_idle_timeout_s(idle_timeout_s: int) -> int:
    """Ticket "5-60 min idle lock" — the API edge and this service both
    clamp so a stored/requested value outside the documented range can
    never silently take effect."""
    return max(MIN_IDLE_TIMEOUT_S, min(MAX_IDLE_TIMEOUT_S, idle_timeout_s))


def access_token_expires_at(session: SessionRecord) -> datetime:
    """The first instant `authenticate_access_token` refuses this session's
    access handle on time grounds: `issued_at + ACCESS_TOKEN_TTL`, capped by
    the absolute `expires_at` that `require_active` enforces. The WS gateway
    ends a socket's identity here (#2259). Revocation is not a deadline: it is
    pushed to sockets through the `RevocationHub`. The idle lock is a sliding
    deadline that can come first, but it intentionally does not end the
    socket: E09-S03 keeps the data feed alive while locked, and REST refuses
    the locked session through `require_active`."""
    return min(session.issued_at + ACCESS_TOKEN_TTL, session.expires_at)


async def _write_ahead(hook: UnlockWriteAhead | None, outcome: UnlockOutcome) -> None:
    if hook is not None:
        await hook(outcome)


class SessionClass(StrEnum):
    """What a live session may do (#2295; `22-api-openapi.yaml` "Enrolment-only session").

    Derived from the user's state on every request, never stored: the session row carries
    no flag, so a TOTP reset, a recovery sign-in or a confirmed enrolment takes effect on
    the next request of every session of that user."""

    #: The user has a confirmed MFA method and the session proved one (`mfa_satisfied_at`),
    #: or MFA is not required (which C-12.2 forbids).
    FULL = "full"
    #: A session minted on the password alone (`mfa_satisfied_at` unset) of a user who has
    #: `mfa_required`, inside its 15 minutes: only the five enrolment operations.
    ENROLMENT_ONLY = "enrolment_only"
    #: As `ENROLMENT_ONLY`, but its absolute expiry has passed (a refreshed access handle
    #: outlives it), or it was not minted as one: its expiry lies more than
    #: `ENROLMENT_ONLY_LIFETIME` ahead, or it proved a second factor (a full session whose user
    #: then lost every method). Refused like an expired session: the user signs in again (Q7).
    ENROLMENT_ONLY_EXPIRED = "enrolment_only_expired"
    #: The user is disabled or gone, whatever else holds: #2911 answers, not this class. The
    #: HTTP guard leaves the request to its route, whose `require_active` (or `refresh()`, #3331)
    #: revokes the session as `user_disabled` and counts the SR-029 breach signal; the WS `auth`
    #: is closed `bye user_disabled`, 4403, and counted in `cv_ws_revoked_total`, as #3413's
    #: close is.
    USER_INACTIVE = "user_inactive"


def classify_session(
    session: SessionRecord, user: UserRecord | None, *, now: datetime
) -> SessionClass:
    """The one classification every HTTP request and every WS `auth` runs (#2295).

    *user* is the session's user as the store reads it now, `None` when there is no such
    user. A user who is gone or `disabled` comes first (`USER_INACTIVE`), as in
    `SessionService.require_active` (#2911). `UserRecord.mfa_methods` lists the confirmed,
    unrevoked methods, the same rule `User.mfa_enabled` follows, so the server and the client
    always agree.

    A session that never proved a second factor (`mfa_satisfied_at` unset: minted with
    `mfa_satisfied=False`, on the password alone) stays restricted even once its user has a
    confirmed method. Revoke-all at confirm (ADR-0010 decision 2) ends such sessions; should
    one be missed, it still never turns full. `mint` sets `mfa_satisfied_at` by default (the
    MFA verify path) and `refresh` hands it on, so a full session keeps it.

    Conversely, a session that proved a second factor its user no longer has is never
    enrolment-only (deny by default, C-12.4): every enrolment-only session is minted on the
    password alone, so such a session (one a recovery sign-in or an owner reset left behind)
    was not minted as one, and could otherwise enrol another TOTP in its last 15 minutes."""
    if user is None or user.status is UserStatus.DISABLED:
        return SessionClass.USER_INACTIVE
    proved = session.mfa_satisfied_at is not None
    if not user.mfa_required or (user.mfa_methods and proved):
        return SessionClass.FULL
    remaining = session.expires_at - now
    if proved or remaining <= timedelta(0) or remaining > ENROLMENT_ONLY_LIFETIME:
        return SessionClass.ENROLMENT_ONLY_EXPIRED
    return SessionClass.ENROLMENT_ONLY


class SessionService:
    def __init__(
        self,
        repository: SessionRepository,
        hasher: Hasher,
        *,
        clock: Clock = _utc_now,
        refresh_token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(48),
        publish_revocation: RevocationSink | None = None,
        backstop_audit: BackstopAuditSink | None = None,
        backstop_audit_timeout_s: float = BACKSTOP_AUDIT_TIMEOUT_S,
    ) -> None:
        self._repository = repository
        self._hasher = hasher
        self._clock = clock
        self._refresh_token_factory = refresh_token_factory
        self._publish_revocation = publish_revocation
        self._backstop_audit = backstop_audit
        self._backstop_audit_timeout_s = backstop_audit_timeout_s
        #: The backstop units in flight (#3332): one per request that is revoking a stray session,
        #: each ended by the store's statement timeout, the hub's close bound and the audit bound,
        #: so the set needs no cap of its own (C-2.18). `drain` waits for them at shutdown.
        self._backstop_units: set[asyncio.Task[None]] = set()
        #: Review finding (PR #1628, low): bounded, in-process counter of
        #: consecutive failed `unlock()` attempts per session id. Not
        #: persisted (a restart resets it, same trade-off as
        #: `PerIpLoginThrottle`); capped at `_MAX_TRACKED_UNLOCK_SESSIONS`
        #: entries so an attacker cycling session ids cannot grow this
        #: dict without bound (C-2.18).
        self._unlock_failures: dict[str, int] = {}

    _MAX_TRACKED_UNLOCK_SESSIONS = 10_000

    def now(self) -> datetime:
        """The clock every session deadline is judged by: the HTTP edge reports lock
        state and `server_time` from it (#2300, server truth, never a client clock)."""
        return self._clock()

    # -- minting -------------------------------------------------------

    async def mint(
        self,
        user_id: str,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
        device_label: str | None = None,
        is_electron: bool = False,
        idle_timeout_s: int = DEFAULT_IDLE_TIMEOUT_S,
        mfa_satisfied: bool = True,
        expires_at: datetime | None = None,
        session_id: uuid.UUID | None = None,
        view_as: ViewAsState | None = None,
        last_seen_at: datetime | None = None,
        step_up_failures: int = 0,
        readonly_until: datetime | None = None,
        locked_at: datetime | None = None,
    ) -> MintedSession:
        """Issue a brand-new session — session fixation is prevented by
        always minting a fresh `session_id`/refresh token here, never
        reusing one from an earlier, unauthenticated request (Security
        notes: "new session id issued on every authentication").

        *expires_at* lets `refresh()` propagate the presented session's own
        absolute deadline to its successor (review finding, PR #1628,
        high: rotation must not reset the 12 h absolute lifetime). First-
        login callers never pass it, so a brand-new session still gets
        `now + ABSOLUTE_LIFETIME`.

        *view_as* is the view-as context `refresh()` carries to the successor
        as the claim returned it (#3085, SR-013), inserted with the row and
        unchanged: nothing extends its expiry. A sign-in never passes it.

        *last_seen_at* is the activity stamp `refresh()` carries to the
        successor (#4012): a token rotation is no user activity, so it never
        restarts the idle clock. A sign-in never passes it and starts the
        clock at `now`.

        *step_up_failures* and *readonly_until* are the step-up penalty `refresh()`
        carries to the successor (#4051, SR-025): a rotation never lifts the read-only
        downgrade or forgets a strike. Grants are never carried. A sign-in starts clean.

        *locked_at* is the lock by request `refresh()` carries to the successor (#4743): a
        rotation never lifts a lock. A sign-in never passes it.

        Raises `UserDisabled` when the user is `disabled` or gone (#2911):
        the repository reads `users.status` under the user-row lock in the
        insert's own transaction, so a disable that commits before the insert
        refuses it, and one that commits after it revokes it. `locked` and
        `invited` users are not refused (login refuses `disabled` only).

        *session_id* is an id the caller drew server-side (`uuid4`) to name the
        session in its write-ahead audit record before minting (C-2.9, #2295);
        it never comes from a request.
        """
        now = self._clock()
        raw_token = self._refresh_token_factory()
        raw_access = secrets.token_urlsafe(32)
        session = SessionRecord(
            id=session_id if session_id is not None else uuid.uuid4(),
            user_id=uuid.UUID(user_id),
            refresh_token_hash=_hash_refresh_token(raw_token),
            access_token_jti=hash_access_token(raw_access),
            issued_at=now,
            last_seen_at=last_seen_at if last_seen_at is not None else now,
            expires_at=expires_at if expires_at is not None else now + ABSOLUTE_LIFETIME,
            revoked_at=None,
            revoked_reason=None,
            ip=ip,
            user_agent=user_agent,
            device_label=device_label,
            is_electron=is_electron,
            mfa_satisfied_at=now if mfa_satisfied else None,
            idle_timeout_s=clamp_idle_timeout_s(idle_timeout_s),
            view_as=view_as,
            step_up_failures=step_up_failures,
            readonly_until=readonly_until,
            locked_at=locked_at,
        )
        created = await self._repository.create_session(session)
        if created is None:
            raise UserDisabled(None)  # nothing was inserted (#2911)
        auth_sessions_active.inc()
        return MintedSession(
            session_id=created.id,
            access_token_jti=created.access_token_jti or hash_access_token(raw_access),
            access_token=raw_access,
            refresh_token=raw_token,
            issued_at=created.issued_at,
            expires_at=created.expires_at,
        )

    async def mint_enrolment_only(
        self,
        user_id: str,
        *,
        session_id: uuid.UUID,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> MintedSession:
        """#2295 (Q6, Q7): a session minted on the password alone (`mfa_satisfied_at`
        unset) that lives at most `ENROLMENT_ONLY_LIFETIME`; `refresh()` hands both on,
        so it never turns full and never outlives that lifetime."""
        return await self.mint(
            user_id,
            ip=ip,
            user_agent=user_agent,
            mfa_satisfied=False,
            expires_at=self._clock() + ENROLMENT_ONLY_LIFETIME,
            session_id=session_id,
        )

    # -- refresh / rotation ----------------------------------------------

    async def peek_refresh(self, raw_refresh_token: str) -> SessionRecord | None:
        """Read-only lookup of the session a refresh token belongs to, so the
        HTTP edge can write its audit record *ahead* of `refresh()` mutating
        anything (C-2.9 write-ahead). Never changes state."""
        return await self._repository.find_by_refresh_hash(_hash_refresh_token(raw_refresh_token))

    async def refresh(
        self,
        raw_refresh_token: str,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
        device_label: str | None = None,
        is_electron: bool = False,
    ) -> RefreshOutcome:
        """`POST /auth/refresh`. Raises `SessionNotFound`,
        `RefreshReuseDetected` (family already revoked as a side effect of
        raising), `SessionRevoked`/`SessionIdleLocked` for a
        non-reuse-but-dead presented session, or `UserDisabled` (#2911): before
        the claim, once the presented session is revoked as `require_active` revokes
        it (#3331; nothing is claimed or minted), or from the successor's mint when a
        disable commits after the claim (the claim stands; no successor exists).
        """
        token_hash = _hash_refresh_token(raw_refresh_token)
        presented = await self._repository.find_by_refresh_hash(token_hash)
        if presented is None:
            raise SessionNotFound("no session for this refresh token")

        now = self._clock()

        if presented.revoked_reason == "rotated":
            # Ticket "Refresh-token reuse kills the family": this exact
            # token was already exchanged for a successor session. Revoke
            # every session in the family (both directions) before raising,
            # so the caller's audit write reflects a fully-contained
            # incident by the time it runs.
            family = await self._repository.walk_rotation_family(str(presented.id))
            for member_id in family:
                await self._repository.revoke(member_id, reason="rotation_reuse", now=now)
            # Every member, the already-rotated ones too: a socket that has not
            # re-`auth`ed since its rotation still runs on the older id.
            await self._publish(family, "rotation_reuse")
            auth_refresh_reuse_total.inc()
            auth_session_revocations_total.labels(reason="rotation_reuse").inc(len(family))
            raise RefreshReuseDetected(
                "refresh token reuse detected; entire session family revoked",
                revoked_session_ids=tuple(str(m) for m in family),
            )

        if presented.is_revoked:
            raise SessionRevoked(presented.revoked_reason or "revoked")

        if presented.is_absolute_expired(now=now):
            expired = await self._repository.revoke(str(presented.id), reason="expired", now=now)
            await self._publish_row(expired, "expired")
            raise SessionRevoked("expired")

        if presented.user_status in (UserStatus.DISABLED, None):
            await self._end_stray_session(presented)  # as `require_active` does (#3331)
            raise UserDisabled(presented.user_status)  # read with the row (#2911)

        if presented.is_idle_locked(now=now):
            # Ticket "The lock does not refresh tokens in the background":
            # a refresh attempt against an idle-locked session is refused
            # without revoking it — unlocking is `unlock()`'s job, not a
            # side effect of a stray refresh call.
            raise SessionIdleLocked(
                "session is idle-locked; unlock before refreshing",
                idle_locked_at=presented.idle_deadline(),
            )

        # Review finding (PR #1628, medium): claim the presented session by
        # revoking it *first* and checking the result, instead of minting
        # the successor first and revoking after. `repository.revoke()` is
        # documented idempotent — it only flips a row from live to revoked
        # once and returns `None` if the row was already revoked by a
        # concurrent caller (INV-B16-d). Whichever concurrent `refresh()`
        # call's revoke() wins the race gets a non-None row back and is the
        # only one that mints a successor; the loser observes `None` and
        # raises the same reuse/race error a legitimate replay would, so
        # two racing refreshes never both mint (they used to: the previous
        # ordering revoked the presented session *after* minting, so both
        # copies of a concurrently-presented token could mint a successor
        # and reuse detection never fired for either).
        claimed = await self._repository.revoke(str(presented.id), reason="rotated", now=now)
        if claimed is None:
            raise RefreshReuseDetected(
                "refresh token reuse detected (concurrent refresh); session family revoked"
            )

        minted = await self.mint(
            str(presented.user_id),
            ip=ip or presented.ip,
            user_agent=user_agent or presented.user_agent,
            device_label=device_label or presented.device_label,
            is_electron=is_electron or presented.is_electron,
            idle_timeout_s=presented.idle_timeout_s,
            mfa_satisfied=presented.mfa_satisfied_at is not None,
            # Review finding (PR #1628, high): propagate the presented
            # session's own absolute deadline instead of minting a fresh
            # `now + ABSOLUTE_LIFETIME` on every rotation. Refreshing must
            # never be able to extend a session past its original 12 h
            # absolute lifetime (ticket "Scope / Deliverables").
            expires_at=presented.expires_at,
            # #3085 SR-013: the view-as context as the claim's RETURNING row holds it, never as
            # `presented` was read before the claim (an end, clear or start may land in between),
            # live, held or cleared alike. The rotated row keeps its copy: it is revoked, and the
            # sweeper skips a copy another row carries (`ViewAsSessionStore.list_view_as_due`).
            # The claim and this insert are two transactions (`SessionRepository` has one per
            # call, and #2911's disable window sits between them), so until the insert commits
            # only the rotated row holds the context. The sweeper's grace runs from the claim's
            # `revoked_at`, the `now` read above, so the gap it must exceed includes the claim's
            # own waits. Each unit of work can wait for a pool connection (30 s) and open one
            # (asyncpg, 60 s), and each statement runs under the unit's `statement_timeout` (30 s):
            # one for the claim, two for the insert (the user-row lock wait, the insert), 270 s in
            # all. A pre-ping, a stalled connection, a commit and the event loop are outside that.
            # A request cancelled in the gap leaves an orphan the sweeper ends `session_ended`
            # after the grace, rightly: no live session holds the context. A shorter grace could
            # end, as `session_ended`, a context a slow successor then carries.
            view_as=claimed.view_as,
            # #4012: the idle clock runs from the last user activity, which a background token
            # refresh is not. Carried from the claim's row (as `view_as` is), so a re-stamp that
            # landed after `presented` was read still counts; a tab that only refreshes locks
            # after its idle timeout, and its next refresh is refused `SessionIdleLocked` above.
            last_seen_at=claimed.last_seen_at,
            # #4051 SR-025: the step-up brake survives a rotation, read from the claim's row
            # (as `last_seen_at` is), so a strike recorded after `presented` was read counts.
            step_up_failures=claimed.step_up_failures,
            readonly_until=claimed.readonly_until,
            # #4743: a lock by request that landed after `presented` was read, before the claim,
            # is on the claim's row: the successor is locked too, so a rotation never lifts it.
            locked_at=claimed.locked_at,
        )
        await self._repository.link_rotation(
            prev_session_id=str(presented.id), next_session_id=str(minted.session_id)
        )
        auth_refresh_total.inc()
        return RefreshOutcome(minted=minted, previous_session_id=presented.id)

    # -- per-request enforcement ------------------------------------------

    async def require_active(self, session_id: str, *, allow_locked: bool = False) -> SessionRecord:
        """The per-request/per-WS-frame-batch backstop (ticket "Revocation
        propagation" + "Order entry is refused while locked"): every caller
        on the OMS/WS path calls this before honouring *session_id*, and it
        is the server-side source of truth regardless of what the client's
        own (cosmetic) lock overlay believes.

        Raises `SessionNotFound`, `SessionRevoked`, or `SessionIdleLocked`.
        A live session of a disabled user, or of one whose row is gone (read
        with the session row, #2911), is revoked as `user_disabled` and refused:
        SR-029 fails closed on any session no disable revoked, and the publish
        ends its sockets with `bye user_disabled` + 4403.

        *allow_locked* (#2300): an idle-locked session is returned as it is, for an
        operation allowed while locked (`GET /auth/session` reads it); every other
        check above still refuses.
        """
        session = await self._repository.find_by_id(session_id)
        if session is None:
            raise SessionNotFound("no such session")

        now = self._clock()
        if session.is_absolute_expired(now=now):
            # Fail closed: revoke() returns None when a concurrent caller won
            # the race, and the stale copy must never be accepted (#2273).
            # Publish only the row this call revoked (#2272).
            if not session.is_revoked:
                expired = await self._repository.revoke(session_id, reason="expired", now=now)
                await self._publish_row(expired, "expired")
            raise SessionRevoked(session.revoked_reason or "expired")

        if session.is_revoked:
            raise SessionRevoked(session.revoked_reason or "revoked")

        if session.user_status in (UserStatus.DISABLED, None):
            await self._end_stray_session(session)
            raise SessionRevoked("user_disabled")

        if session.is_idle_locked(now=now) and not allow_locked:
            auth_idle_locks_total.inc()
            raise SessionIdleLocked(
                "session is idle-locked", idle_locked_at=session.idle_deadline()
            )

        return session

    async def _end_stray_session(self, session: SessionRecord) -> None:
        """Run `_revoke_stray_session` as one unit that a cancel of the request cannot cut short
        (#3332): an owned task under `asyncio.shield`, started before the row update. A request
        cancelled anywhere in it (the commit, the publish, the record) still leaves the row
        revoked, counted, logged, published and recorded once, as an uncancelled one does; a
        retry would find the row revoked and add nothing, so a step lost there is lost for good.
        The cancelled request still waits for the unit up to the audit bound, then lets the
        cancel through; a unit that runs on is drained at shutdown (`drain`). Finishing the
        revocation after the request left is the safe direction: the row update is conditional.
        An error of the unit reaches a request that still waits, unchanged, and is logged either
        way (`_backstop_unit_done`)."""
        unit = spawn(self._revoke_stray_session(session), name="session-backstop-revoke")
        self._backstop_units.add(unit)
        ids = {"session_id": str(session.id), "user_id": str(session.user_id)}
        unit.add_done_callback(lambda done: self._backstop_unit_done(done, ids))
        try:
            await asyncio.shield(unit)
        except asyncio.CancelledError:
            if not unit.done():
                await asyncio.wait({unit}, timeout=self._backstop_audit_timeout_s)
            raise

    def _backstop_unit_done(self, unit: asyncio.Task[None], ids: dict[str, str]) -> None:
        """Untrack a finished unit. A failed one is logged here, by class name only, whether or not
        its request still waits (a waiting request also gets the error and is refused 503 or
        500): once the request has left, nobody awaits the unit, and the shield has marked the
        error retrieved, so this line is the only trace."""
        self._backstop_units.discard(unit)
        if not unit.cancelled() and (exc := unit.exception()) is not None:
            with contextlib.suppress(Exception):  # a log sink must not raise out of a callback
                _log().error(
                    "auth.disabled_user_session_revoke_failed", error=type(exc).__name__, **ids
                )

    async def drain(self, timeout_s: float) -> int:
        """Shutdown: wait up to *timeout_s* for the backstop units in flight (#3332). Each ends by
        its own bounds, but a hung one must not hold the shutdown (C-2.18). Returns how many are
        still running, logged: they are never cancelled here."""
        if not self._backstop_units:
            return 0
        _, pending = await asyncio.wait(set(self._backstop_units), timeout=timeout_s)
        if pending:
            _log().warning("auth.backstop_units_in_flight_at_shutdown", units=len(pending))
        return len(pending)

    async def _revoke_stray_session(self, session: SessionRecord) -> None:
        """Revoke *session*, a live session of a disabled or deleted user that no disable revoked
        (SR-029 breach signal), as `user_disabled`. `require_active` and a refused `refresh()` run
        it (#3331), as one unit (`_end_stray_session`, #3332), so both revoke, count, log, publish
        and record the same way; each then raises its own refusal. Counted, logged and audited
        only when this call revoked the row (#3029): a request that read it live while another
        revoked it is refused all the same, but adds nothing, so the counter and the log line move
        once per row, as the revocation counted under `user_disabled` does, and the record is
        written once. The record goes last, bounded and isolated (C-2.9, #3120): a port that fails
        or hangs can hide neither the revocation nor the signal."""
        session_id = str(session.id)
        revoked = await self._revoke_row(session_id, reason="user_disabled")
        if revoked is not None:
            auth_disabled_user_sessions_revoked_total.inc()
            _log().warning(
                "auth.disabled_user_session_revoked",
                session_id=session_id,
                user_id=str(session.user_id),
                user_status=session.user_status,
            )
        await self._publish_row(revoked, "user_disabled")
        if revoked is not None:
            await self._audit_backstop(session)

    async def _audit_backstop(self, session: SessionRecord) -> None:
        """Hand the revocation just made to the audit port. The revocation stands whatever the
        port does: a failure is logged and dropped here (never queued, C-2.18), a wait past the
        bound is logged as slow (the record may still land), and neither changes the refusal. The
        composition root's port journals the record through the audit lane first, with the writer
        as its fallback, so it is lost only when both refuse it, the port drops it (its in-flight
        cap, the shutdown drain) or its write fails after the caller stopped waiting (the 2 s bound
        or a cancel), and the port then counts it (`auth_audit_outcome_lost_total`,
        04-security-program.md section 8.3). A cancel is no failure: it propagates (only the loop's
        teardown cancels the unit this runs in, #3332)."""
        if self._backstop_audit is None:
            return
        revocation = BackstopRevocation(session.id, session.user_id, session.user_status)
        try:
            async with asyncio.timeout(self._backstop_audit_timeout_s) as bound:
                await self._backstop_audit(revocation)
        except Exception as exc:  # isolate the port, as `publish_revoked` isolates the sink
            ids = {"session_id": str(session.id), "user_id": str(session.user_id)}
            if isinstance(exc, TimeoutError) and bound.expired():
                _log().warning("auth.disabled_user_session_audit_slow", **ids)
            else:
                _log().error(
                    "auth.disabled_user_session_audit_failed", error=type(exc).__name__, **ids
                )

    async def peek_access_token(self, raw_access_token: str) -> SessionRecord | None:
        """Read-only: the session an access handle was issued for, ignoring the
        access TTL, idle lock and revocation. Used, among others, to bind the
        SR-041 CSRF token to a session id (#2090) so an expired bearer still gets
        its MAC verified and then the route's own 401, and to name the session a
        refusal's record names; it never authorises anything."""
        jti = hash_access_token(raw_access_token)
        found = await self._repository.find_by_access_token_jti(str(jti))
        if found is None or not hmac.compare_digest(
            found.access_token_jti.bytes if found.access_token_jti else b"", jti.bytes
        ):
            return None
        return found

    async def authenticate_access_token(
        self, raw_access_token: str, *, allow_locked: bool = False
    ) -> SessionRecord:
        """Per-request authentication (ADR-0020): resolve the opaque bearer
        handle to its session, refusing unknown, expired-token, revoked and
        idle-locked sessions. Raises `SessionNotFound`, `SessionRevoked`,
        `SessionIdleLocked`. Never activity: a request leaves `last_seen_at` as
        it is; only extend (`touch()`) and unlock move it (#2300)."""
        jti = hash_access_token(raw_access_token)
        found = await self._repository.find_by_access_token_jti(str(jti))
        if found is None or not hmac.compare_digest(
            found.access_token_jti.bytes if found.access_token_jti else b"", jti.bytes
        ):
            raise SessionNotFound("no session for this access token")
        if self._clock() >= found.issued_at + ACCESS_TOKEN_TTL:
            raise SessionNotFound("access token expired")
        if allow_locked:
            # For a caller that serves an idle-locked session. A revoked or
            # expired session is refused like any other (#2389 gap J).
            if found.is_revoked:
                raise SessionRevoked(found.revoked_reason or "revoked")
            if found.is_absolute_expired(now=self._clock()):
                raise SessionRevoked("expired")
            return found
        return await self.require_active(str(found.id))

    async def touch(self, session_id: str) -> SessionRecord:
        """Extend's activity (`POST /auth/session/extend`, its sole route):
        re-stamp `last_seen_at`, extending the idle deadline. Raises the same
        errors as `require_active` — activity on a dead/locked session never
        resurrects it. The write is conditional on the row being neither
        revoked nor idle-locked at `now`, so a lock that engages between the
        check and the write is not lifted (B16.7: activity never lifts a lock);
        the row is then refused as it is."""
        await self.require_active(session_id)
        now = self._clock()
        touched = await self._repository.touch_last_seen(session_id, now=now)
        if touched is None:
            await self.require_active(session_id)  # locked or revoked since the check
            raise SessionNotFound("session disappeared between check and touch")
        return touched

    # -- lock (#4743) ----------------------------------------------------------

    async def lock(
        self, session_id: str, *, write_ahead: LockWriteAhead, audit_timeout_s: float
    ) -> tuple[SessionRecord, bool]:
        """`POST /auth/lock` (22 `authLock`, CMP-098 "Lock now"): lock the session at once, as if
        its idle deadline fell due, without moving it (`last_seen_at` stays: BQ-5). One unit of
        work under the row's lock (`SessionRepository.lock_session`). A session that is already
        idle-locked, by its deadline or by request, comes back as it is with `False`, and
        *write_ahead* is never awaited: one record per lock. Otherwise *write_ahead* (C-2.9) is
        awaited with the row, `locked_at` is set, and the locked row comes back with `True`.

        A session revoked, past its absolute lifetime or gone raises what `require_active`
        raises for it (an expired one is revoked as `expired` and published), else
        `SessionNotFound` (fail closed). A failing hook raises its error, and one past
        *audit_timeout_s* `WriteAheadTimeout`, with nothing changed."""
        now = self._clock()
        outcome = await self._repository.lock_session(
            session_id,
            now=now,
            unlocked=lambda row: not row.is_idle_locked(now=now),
            write_ahead=write_ahead,
            audit_timeout_s=audit_timeout_s,
        )
        if outcome is None:
            await self.require_active(session_id, allow_locked=True)
            raise SessionNotFound("session ended before its lock")
        return outcome

    # -- unlock -------------------------------------------------------------

    async def unlock(
        self,
        session_id: str,
        *,
        password: str,
        password_hash: str | None = None,
        check: PasswordCheck | None = None,
        write_ahead: UnlockWriteAhead | None = None,
    ) -> SessionRecord:
        """Ticket "Unlock restores context": password only, no TOTP, while
        still inside the absolute lifetime. `password_hash` is the caller's
        already-looked-up `users.password_hash` — this service never reads
        the `users` table itself (M18 boundary: `session_service` composes
        with a `Hasher`, not a second repository). *check* replaces that
        comparison: `POST /auth/unlock` (#2300) passes login's Argon2id path
        and lockout counters (SR-015, SR-016).

        *write_ahead* (C-2.9) is awaited with the decided `UnlockOutcome`
        after the password check and before the row changes. If it raises, the
        lock stays and nothing is revoked, but a wrong password stays counted
        (#2300: a failure counts even if its audit record cannot be written).

        Raises `SessionNotFound`/`SessionRevoked` if the session died while
        locked (ticket "if the absolute lifetime elapses while locked,
        unlocking fails and becomes a full sign-in" — the caller maps this
        error to that fallback, `unlock()` itself never re-mints), or
        `UnlockPasswordInvalid` for a wrong password that has not yet hit
        `MAX_UNLOCK_ATTEMPTS` (at which point the session is revoked and
        `SessionRevoked` is raised instead — review finding, PR #1628,
        low: unlock attempts must be throttled). A session that is not
        idle-locked raises `SessionNotLocked` before any password check
        (#2300: unlock is never a password check on an unlocked session)."""
        session = await self._repository.find_by_id(session_id)
        if session is None:
            raise SessionNotFound("no such session")
        now = self._clock()
        if session.is_revoked or session.is_absolute_expired(now=now):
            raise SessionRevoked(session.revoked_reason or "expired")
        if not session.is_idle_locked(now=now):
            raise SessionNotLocked("session is not idle-locked")

        if check is not None:
            password_ok = await check(password)
        elif password_hash is not None:
            password_ok = await self._hasher.verify(password_hash, password)
        else:
            raise TypeError("unlock() needs password_hash or check")
        if not password_ok:
            failures = self._count_unlock_failure(session_id)
            if failures >= MAX_UNLOCK_ATTEMPTS:
                await _write_ahead(write_ahead, UnlockOutcome.REVOKED)
                revoked = await self._repository.revoke(
                    session_id, reason="unlock_attempts_exceeded", now=now
                )
                # Only once the revoke committed: a failed or cancelled revoke keeps the
                # count, so the next wrong password revokes (#2389 gap I).
                self._unlock_failures.pop(session_id, None)
                if revoked is not None:  # as `revoke()`; None: already revoked, and counted then
                    auth_sessions_active.dec()
                    auth_session_revocations_total.labels(reason="unlock_attempts_exceeded").inc()
                await self._publish_row(revoked, "unlock_attempts_exceeded")
                raise SessionRevoked("unlock_attempts_exceeded")
            await _write_ahead(write_ahead, UnlockOutcome.FAILED)
            raise UnlockPasswordInvalid("invalid_password")

        await _write_ahead(write_ahead, UnlockOutcome.UNLOCKED)
        self._unlock_failures.pop(session_id, None)
        # B16.7 (C-2.12, C-2.21; PR #2290 ruling rule 4d): lifting the lock drops every
        # step-up elevation in the same write that re-stamps `last_seen_at`, so a
        # password-only unlock never inherits a grace window, a one-shot grant or a
        # pending challenge taken before it. The write also clears a lock by request and
        # stamps `unlocked_at` (#4743).
        touched = await self._repository.lift_idle_lock(session_id, now=now)
        if touched is None:
            raise SessionNotFound("session disappeared during unlock")
        return touched

    def _count_unlock_failure(self, session_id: str) -> int:
        """Count one wrong unlock password; returns the consecutive count."""
        failures = self._unlock_failures.get(session_id, 0) + 1
        if session_id not in self._unlock_failures and (
            len(self._unlock_failures) >= self._MAX_TRACKED_UNLOCK_SESSIONS
        ):
            # Bounded map (C-2.18), same rationale as PerIpLoginThrottle.
            oldest = next(iter(self._unlock_failures))
            del self._unlock_failures[oldest]
        self._unlock_failures[session_id] = failures
        return failures

    # -- revocation ----------------------------------------------------------

    async def revoke(self, session_id: str, *, reason: str) -> SessionRecord | None:
        """Single-session revoke (SCR-112 per-row "revoke", or `LOGOUT`)."""
        revoked = await self._revoke_row(session_id, reason=reason)
        await self._publish_row(revoked, reason)
        return revoked

    async def _revoke_row(self, session_id: str, *, reason: str) -> SessionRecord | None:
        """The conditional row update and its counters, without the publish. The publish suspends,
        so a caller with more to count (the backstop's breach signal) counts it first. `None`
        means the row was already revoked, and whoever revoked it counted it then."""
        revoked = await self._repository.revoke(session_id, reason=reason, now=self._clock())
        if revoked is not None:
            auth_sessions_active.dec()
            auth_session_revocations_total.labels(reason=normalise_reason(reason)).inc()
        return revoked

    async def revoke_all(
        self, user_id: str, *, reason: str, except_session_id: str | None = None
    ) -> tuple[SessionRecord, ...]:
        """Sign-out-everywhere. `except_session_id` lets a caller keep its
        own current session alive (ticket "my own session is unaffected"
        only applies to the *other-session* revoke path, but `/auth/
        password`'s "revokes all other sessions on success" reuses this
        same exclusion)."""
        revoked = await self._repository.revoke_all_for_user(
            user_id, reason=reason, now=self._clock(), except_session_id=except_session_id
        )
        auth_sessions_active.dec(len(revoked))
        auth_session_revocations_total.labels(reason=normalise_reason(reason)).inc(len(revoked))
        await self._publish((str(r.id) for r in revoked), reason)
        return revoked

    async def _publish(self, session_ids: Iterable[str], reason: str) -> None:
        await publish_revoked(self._publish_revocation, session_ids, reason)

    async def _publish_row(self, revoked: SessionRecord | None, reason: str) -> None:
        """Publish a row this call revoked. `None` means it was already
        revoked, and whoever revoked it published it then."""
        if revoked is not None:
            await self._publish((str(revoked.id),), reason)

    # -- read views ------------------------------------------------------

    async def introspect(self, session_id: str) -> SessionIntrospection:
        session = await self.require_active(session_id)
        return SessionIntrospection(
            session_id=session.id,
            user_id=session.user_id,
            issued_at=session.issued_at,
            expires_at=session.expires_at,
            idle_deadline=session.idle_deadline(),
            mfa_satisfied_at=session.mfa_satisfied_at,
        )

    async def find_live_session(self, user_id: str, session_id: str) -> SessionRecord | None:
        """Read-only (E42-T09, #2649): `session_id` if it is a live session of `user_id`, one that
        `list_sessions(user_id)` lists; `None` for an unknown, ended or another user's session
        alike, so the admin revoke answers each with one 404 (IDOR). Revokes nothing."""
        session = await self._repository.find_by_id(session_id)
        if session is None or session.is_revoked or str(session.user_id) != user_id:
            return None
        return session

    async def list_sessions(
        self, user_id: str, *, current_session_id: str | None = None
    ) -> tuple[SessionView, ...]:
        sessions = await self._repository.find_live_by_user(user_id)
        return tuple(
            SessionView(
                id=s.id,
                device_name=s.device_label,
                ip=s.ip,
                user_agent=s.user_agent,
                created_at=s.issued_at,
                last_seen_at=s.last_seen_at,
                expires_at=s.expires_at,
                current=(str(s.id) == current_session_id),
            )
            for s in sessions
        )
