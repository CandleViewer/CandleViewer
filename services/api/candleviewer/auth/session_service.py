"""`SessionService` — the M18 core for E09-S03 (US-ONB-004/009): session
minting, refresh-token rotation with family-reuse revocation, idle lock,
absolute expiry, and sign-out-everywhere.

Every Gherkin scenario in the ticket maps to a method here:

- `mint()` — first-login session creation (called after `LoginService`/
  `MfaService` complete the two-legged login, per those modules' own
  `NotImplementedError`/`MfaVerifiedResult` "E09-S03 scope" notes).
- `refresh()` — "Refresh-token reuse kills the family". Not activity: the
  successor inherits `last_seen_at` (#2300).
- `touch()` — "Idle lock preserves the data feed" (re-stamps
  `last_seen_at`, i.e. the `REQUEST` event on B16). Activity is explicit
  (#2300): only `POST /auth/session/extend` calls it, and authenticating a
  request never does.
- `require_active()` — "Order entry is refused while locked": the
  per-request/per-WS-frame revocation + idle-lock check every caller in
  the OMS/WS path must run before honouring a session id.
- `unlock()` — "Unlock restores context": password-only re-auth while
  still within the absolute lifetime.
- `revoke()` / `revoke_all()` — single-session revoke and sign-out-
  everywhere (SCR-112).

Audit emission is the router's job, exactly like `LoginService`/
`MfaService` (`auth` may not import `audit` — `forbidden-M18`); this module
raises typed errors and returns typed results only.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from candleviewer.auth.errors import (
    RefreshReuseDetected,
    SessionIdleLocked,
    SessionNotFound,
    SessionRevoked,
    UnlockPasswordInvalid,
)
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.metrics import (
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
)
from candleviewer.auth.session_repository import SessionRepository

#: Ticket "Scope / Deliverables": "12 h absolute lifetime".
ABSOLUTE_LIFETIME = timedelta(hours=12)

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


def _utc_now() -> datetime:
    return datetime.now(UTC)


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
    """Read-only twin of `authenticate_access_token`'s acceptance rule: not revoked,
    not absolute-expired, not idle-locked, and the access handle within
    `ACCESS_TOKEN_TTL`. No state change; used to decide whether a CSRF refusal is
    bound to a session that could actually act (#2238 review)."""
    return (
        not session.is_revoked
        and not session.is_absolute_expired(now=now)
        and not session.is_idle_locked(now=now)
        and now < session.issued_at + ACCESS_TOKEN_TTL
    )


def is_idle_locked_session(session: SessionRecord, *, now: datetime) -> bool:
    """The idle-lock twin of `is_live_session` (#2300): a session that
    `authenticate_access_token` would accept but for the idle lock (not revoked,
    inside its absolute lifetime, access handle within `ACCESS_TOKEN_TTL`) and
    past its `idle_deadline`. Such a request answers `401 session_idle_locked`
    instead of `unauthenticated`. No state change."""
    return (
        session.is_idle_locked(now=now)
        and not session.is_absolute_expired(now=now)
        and now < session.issued_at + ACCESS_TOKEN_TTL
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


class SessionService:
    def __init__(
        self,
        repository: SessionRepository,
        hasher: Hasher,
        *,
        clock: Clock = _utc_now,
        refresh_token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(48),
    ) -> None:
        self._repository = repository
        self._hasher = hasher
        self._clock = clock
        self._refresh_token_factory = refresh_token_factory
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
        last_seen_at: datetime | None = None,
    ) -> MintedSession:
        """Issue a brand-new session — session fixation is prevented by
        always minting a fresh `session_id`/refresh token here, never
        reusing one from an earlier, unauthenticated request (Security
        notes: "new session id issued on every authentication").

        *expires_at* lets `refresh()` propagate the presented session's own
        absolute deadline to its successor (review finding, PR #1628,
        high: rotation must not reset the 12 h absolute lifetime). First-
        login callers never pass it, so a brand-new session still gets
        `now + ABSOLUTE_LIFETIME`. *last_seen_at* does the same for the idle
        deadline (#2300: a refresh is not activity).
        """
        now = self._clock()
        raw_token = self._refresh_token_factory()
        raw_access = secrets.token_urlsafe(32)
        session = SessionRecord(
            id=uuid.uuid4(),
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
        )
        created = await self._repository.create_session(session)
        auth_sessions_active.inc()
        return MintedSession(
            session_id=created.id,
            access_token_jti=created.access_token_jti or hash_access_token(raw_access),
            access_token=raw_access,
            refresh_token=raw_token,
            issued_at=created.issued_at,
            expires_at=created.expires_at,
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
        raising), or `SessionRevoked`/`SessionIdleLocked` for a
        non-reuse-but-dead presented session.
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
            auth_refresh_reuse_total.inc()
            auth_session_revocations_total.labels(reason="rotation_reuse").inc(len(family))
            raise RefreshReuseDetected(
                "refresh token reuse detected; entire session family revoked",
                revoked_session_ids=tuple(str(m) for m in family),
            )

        if presented.is_revoked:
            raise SessionRevoked(presented.revoked_reason or "revoked")

        if presented.is_absolute_expired(now=now):
            await self._repository.revoke(str(presented.id), reason="expired", now=now)
            raise SessionRevoked("expired")

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
            # #2300: a refresh is not activity. The successor keeps the presented
            # session's idle deadline, so a client refreshing on schedule still locks.
            last_seen_at=presented.last_seen_at,
        )
        await self._repository.link_rotation(
            prev_session_id=str(presented.id), next_session_id=str(minted.session_id)
        )
        auth_refresh_total.inc()
        return RefreshOutcome(minted=minted, previous_session_id=presented.id)

    # -- per-request enforcement ------------------------------------------

    async def require_active(self, session_id: str) -> SessionRecord:
        """The per-request/per-WS-frame-batch backstop (ticket "Revocation
        propagation" + "Order entry is refused while locked"): every caller
        on the OMS/WS path calls this before honouring *session_id*, and it
        is the server-side source of truth regardless of what the client's
        own (cosmetic) lock overlay believes.

        Raises `SessionNotFound`, `SessionRevoked`, or `SessionIdleLocked`.
        """
        session = await self._repository.find_by_id(session_id)
        if session is None:
            raise SessionNotFound("no such session")

        now = self._clock()
        if session.is_absolute_expired(now=now):
            # Fail closed: revoke() returns None when a concurrent caller won
            # the race, and the stale copy must never be accepted (#2273).
            if not session.is_revoked:
                await self._repository.revoke(session_id, reason="expired", now=now)
            raise SessionRevoked(session.revoked_reason or "expired")

        if session.is_revoked:
            raise SessionRevoked(session.revoked_reason or "revoked")

        if session.is_idle_locked(now=now):
            auth_idle_locks_total.inc()
            raise SessionIdleLocked(
                "session is idle-locked", idle_locked_at=session.idle_deadline()
            )

        return session

    async def peek_access_token(self, raw_access_token: str) -> SessionRecord | None:
        """Read-only: the session an access handle was issued for, ignoring the
        access TTL, idle lock and revocation. Used only to bind the SR-041 CSRF
        token to a session id (#2090) so an expired bearer still gets its MAC
        verified and then the route's own 401; it never authorises anything."""
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
        `SessionIdleLocked`. Never activity (#2300): it never re-stamps
        `last_seen_at`; `touch()` and `unlock()` are the only writers."""
        jti = hash_access_token(raw_access_token)
        found = await self._repository.find_by_access_token_jti(str(jti))
        if found is None or not hmac.compare_digest(
            found.access_token_jti.bytes if found.access_token_jti else b"", jti.bytes
        ):
            raise SessionNotFound("no session for this access token")
        if self._clock() >= found.issued_at + ACCESS_TOKEN_TTL:
            raise SessionNotFound("access token expired")
        if allow_locked:
            # Logout / revoke must work on an idle-locked session (the lock
            # is cosmetic on the client; the server still lets the owner end it).
            if found.is_revoked:
                raise SessionRevoked(found.revoked_reason or "revoked")
            return found
        return await self.require_active(str(found.id))

    async def touch(self, session_id: str) -> SessionRecord:
        """The `REQUEST` event on B16: re-stamp `last_seen_at`, extending
        the idle deadline. Raises the same errors as `require_active` —
        activity on a dead/locked session never resurrects it."""
        await self.require_active(session_id)
        now = self._clock()
        touched = await self._repository.touch_last_seen(session_id, now=now)
        if touched is None:
            raise SessionNotFound("session disappeared between check and touch")
        return touched

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
        low: unlock attempts must be throttled)."""
        session = await self._repository.find_by_id(session_id)
        if session is None:
            raise SessionNotFound("no such session")
        now = self._clock()
        if session.is_revoked or session.is_absolute_expired(now=now):
            raise SessionRevoked(session.revoked_reason or "expired")

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
                self._unlock_failures.pop(session_id, None)
                await self._repository.revoke(
                    session_id, reason="unlock_attempts_exceeded", now=now
                )
                raise SessionRevoked("unlock_attempts_exceeded")
            await _write_ahead(write_ahead, UnlockOutcome.FAILED)
            raise UnlockPasswordInvalid("invalid_password")

        await _write_ahead(write_ahead, UnlockOutcome.UNLOCKED)
        self._unlock_failures.pop(session_id, None)
        if session.is_idle_locked(now=now):
            # B16.7 (C-2.12, C-2.21; PR #2290 ruling rule 4d): lifting the lock
            # drops every step-up elevation in the same write that re-stamps
            # `last_seen_at`, so a password-only unlock never inherits a grace
            # window, a one-shot grant or a pending challenge taken before it.
            touched = await self._repository.lift_idle_lock(session_id, now=now)
        else:
            touched = await self._repository.touch_last_seen(session_id, now=now)
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
        return revoked

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
