"""`StepUpService` (E09-S04, US-ONB-005/010): step-up re-authentication and
owner-initiated TOTP reset.

Policy numbers mirror the B16 `session` chart's elevation sub-state
(`statechart/bindings/b16_session.py`; a parity test pins them). Per C-2.21
the statechart records and this synchronous code enforces: the check in
`require_elevation()` reads the step-up columns of the caller's own
`sessions` row (`step_up_elevations`, `step_up_failures`, `readonly_until`;
migration 0009) - the brief's "stored on the session row keyed by action
class with its own expiry". Never a token claim, so a client cannot forge or
replay it on another session; it survives a process restart and dies with
the session (revoked rows are never updated and carry no elevation).

After each enforcement decision is persisted, the matching B16 event is sent
to the session's chart (`SessionChart`); the chart's audit actions write the
step-up audit records (`auth` itself may not import `audit`).

Challenges (#2304; PR #2290 ruling, rule 4): every refusal issues one live
challenge per session (`record_pending`), stored on the row with its id,
class, 5-minute expiry and, when the route names it, the SHA-256 fingerprint
of the refused request; `step_up()` answers the live one.

Writes (#2304, #2798): a no-grace class's one-shot grant is used by one
conditional write (`consume_step_up_key`), and every other write of the
step-up columns is a change applied to the row as it is under its lock
(`update_step_up_state`), never to a copy read before it: of two requests
racing to use a grant one does, and a grant used while another request of
the session is in flight stays used. A change is a function of the columns it
is given and of the values it was built with, with no I/O and no await; the
strike also notes on itself whether it started a downgrade.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from candleviewer.auth.errors import (
    SelfResetRefused,
    SessionReadOnly,
    SessionRevoked,
    StepUpChallengeRefused,
    StepUpCodeInvalid,
    StepUpRequired,
    UnknownActionClass,
)
from candleviewer.auth.hashing import Hasher
from candleviewer.auth.login_service import LOCKOUT_DURATION, LOCKOUT_THRESHOLD
from candleviewer.auth.metrics import (
    auth_lockouts_total,
    auth_mfa_resets_total,
    auth_readonly_downgrades_total,
    auth_step_up_total,
    auth_stepup_failures_total,
)
from candleviewer.auth.mfa_repository import MfaRepository
from candleviewer.auth.models import SessionRecord, UserRecord
from candleviewer.auth.repository import UserRepository
from candleviewer.auth.session_chart import SessionChart, to_us
from candleviewer.auth.session_repository import SessionRepository, StepUpChange, StepUpState
from candleviewer.auth.session_service import RevocationSink, publish_revoked
from candleviewer.auth.totp import verify_code
from candleviewer.auth.totp_skew import TotpSkewReporter

#: Ticket: "a 5-minute grace per action class".
GRACE_WINDOW = timedelta(minutes=5)
#: Ticket: three invalid codes abandon the action.
FAILURE_CAP = 3
#: Ticket: read-only downgrade lasts 5 minutes.
READONLY_WINDOW = timedelta(minutes=5)
#: `recorder` (04 §7.2.2 rows 9 and 9a): retention and pin changes (#2738) and the
#: irreversible recorded-data purge (E16-T06); a grace class.
#: #2751 (SR-025): `audit` gates the audit-log export, `backups` a backup restore.
ACTION_CLASSES = frozenset(
    {"keys", "users", "live_enablement", "killswitch", "risk_caps", "recorder", "audit", "backups"}
)
#: Ticket "No-grace list": always a fresh code. `backups`: a restore is irreversible.
NO_GRACE_ACTION_CLASSES = frozenset({"live_enablement", "killswitch", "backups"})
#: `PositionStateProvider.source` when no position store exists yet.
POSITION_SOURCE_NOT_DEPLOYED = "not_deployed"
#: Key prefix (in `step_up_elevations`) of the challenge issued by the last 403.
_PENDING = "pending:"
#: Key prefix (in `step_up_elevations`) of a one-shot grant: a no-grace class is stored as
#: `once:<class>` by `step_up()` and removed by `consume_single_use`.
_ONCE = "once:"
#: #2304: a challenge expires 5 minutes after issue.
CHALLENGE_WINDOW = timedelta(minutes=5)
_FINGERPRINT = re.compile(r"[0-9a-f]{64}")


def grace_expires_at(elevations: dict[str, datetime], now: datetime) -> datetime | None:
    """Latest live grace-window expiry (excludes pending challenges and
    one-shot grants) - the `step_up_expires_at` the dialog counts down."""
    live = [v for k, v in elevations.items() if k in ACTION_CLASSES and v > now]
    return max(live) if live else None


def last_step_up_at(elevations: dict[str, datetime]) -> datetime | None:
    """When the session's most recent successful step-up happened, whatever its action class,
    or `None` when the row records none (#2754).

    `step_up()` stores `now + GRACE_WINDOW` under the class (`once:<class>` for a one-shot
    grant), so a grant's expiry less the window is the instant it was given. A `pending:`
    challenge carries the same expiry but is no step-up, and a key that is not an action class
    is ignored. A grant stays on the row after its window lapses, so the instant outlives the
    window; it is gone once something removes the grant: an idle-lock unlock (B16.7), the
    read-only downgrade, the spend of a one-shot grant, or a later write that prunes lapsed
    windows. A token refresh starts a successor row, which holds none. Observability only:
    elevation is still decided by `require_elevation`, never here."""
    given = [
        until - GRACE_WINDOW
        for key, until in elevations.items()
        if key.removeprefix(_ONCE) in ACTION_CLASSES
    ]
    return max(given) if given else None


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Decrypter(Protocol):
    def decrypt(self, blob: bytes) -> bytes: ...


class PositionStateProvider(Protocol):
    """Read-only view of a user's open-position state (OMS read model).

    `source` names the backing store; `"not_deployed"` means none exists yet
    and `open_position_count` returns `None` (unknown) - never a made-up 0."""

    @property
    def source(self) -> str: ...

    async def open_position_count(self, user_id: str) -> int | None: ...


@dataclass(frozen=True)
class StepUpGrant:
    action_class: str
    elevated_until: datetime
    #: True for no-grace classes: no window is opened; the grant authorises
    #: exactly the one action it was obtained for.
    single_use: bool
    #: #2304: the challenge the step-up answered, if any.
    challenge_id: uuid.UUID | None = None


@dataclass(frozen=True)
class StepUpChallenge:
    """A challenge a `403 step_up_required` issued (#2304), or the one-shot grant a
    no-grace step-up made of it. Stored on the session row as
    `<prefix><class>:<challenge_id>[:<fingerprint>]` -> expiry."""

    challenge_id: uuid.UUID
    action_class: str
    expires_at: datetime
    #: Hex SHA-256 of the refused request; always set for a no-grace class.
    fingerprint: str | None = None

    def key(self, prefix: str = _PENDING) -> str:
        tail = "" if self.fingerprint is None else f":{self.fingerprint}"
        return f"{prefix}{self.action_class}:{self.challenge_id}{tail}"

    @classmethod
    def parse(cls, key: str, expires_at: datetime, prefix: str) -> StepUpChallenge | None:
        """The entry stored under `key`, or None for any other key (including the
        class-only keys written before #2304, which therefore bind nothing). A
        one-shot grant is a no-grace class's and always names the request it binds,
        so a `once:` key without a fingerprint is no grant at all."""
        parts = key.removeprefix(prefix).split(":") if key.startswith(prefix) else []
        if len(parts) not in (2, 3) or parts[0] not in ACTION_CLASSES:
            return None
        fingerprint = parts[2] if len(parts) == 3 else None
        if prefix == _ONCE and (parts[0] not in NO_GRACE_ACTION_CLASSES or fingerprint is None):
            return None
        if fingerprint is not None and not _FINGERPRINT.fullmatch(fingerprint):
            return None
        try:
            return cls(uuid.UUID(parts[1]), parts[0], expires_at, fingerprint)
        except ValueError:
            return None


def _stored(record: SessionRecord, now: datetime, prefix: str) -> list[StepUpChallenge]:
    """The unexpired challenges (`pending:`) or one-shot grants (`once:`) on the row."""
    found = (
        StepUpChallenge.parse(key, until, prefix)
        for key, until in record.step_up_elevations.items()
        if until > now
    )
    return [entry for entry in found if entry is not None]


def _answered(
    record: SessionRecord, now: datetime, action_class: str | None, challenge_id: uuid.UUID | None
) -> tuple[str, StepUpChallenge | None]:
    """The class a step-up elevates and the live challenge it answers (#2304). Every
    refusal is decided here, before any factor is checked."""
    live = next(iter(_stored(record, now, _PENDING)), None)
    if challenge_id is not None and (live is None or live.challenge_id != challenge_id):
        raise StepUpChallengeRefused("challenge_id", "challenge_expired")
    if live is not None and action_class is not None and action_class != live.action_class:
        raise StepUpChallengeRefused("action_class", "challenge_mismatch")
    resolved = live.action_class if live is not None else action_class
    if resolved is None:
        raise StepUpChallengeRefused("action_class", "required")
    return resolved, live


# Every write of the step-up columns is one of these changes, applied by
# `SessionRepository.update_step_up_state` to the row as it is under its lock (#2304), never
# to the copy a request read before: a grant used meanwhile stays used, a downgrade stands.
# Each is a function of the columns it is given and of the values it was built with, with no I/O
# and no await; `_Strike` alone is an object, as it also notes whether it started a downgrade.


def _unexpired(elevations: dict[str, datetime], now: datetime) -> dict[str, datetime]:
    return {k: v for k, v in elevations.items() if v > now}


def _issue(key: str, until: datetime, now: datetime) -> StepUpChange:
    """The new challenge supersedes the live one; nothing else on the row changes."""

    def change(state: StepUpState) -> StepUpState:
        elevations, failures, readonly_until = state
        kept = {k: v for k, v in _unexpired(elevations, now).items() if not k.startswith(_PENDING)}
        return {**kept, key: until}, failures, readonly_until

    return change


def _elevate(action_class: str, grant_key: str, until: datetime, now: datetime) -> StepUpChange:
    """The challenge is used up. A no-grace class holds one grant (a newer step-up replaces
    it), a grace class a window. A downgrade that landed during the factor check stands, and
    nothing is elevated."""
    once = f"{_ONCE}{action_class}"

    def change(state: StepUpState) -> StepUpState:
        elevations, _failures, readonly_until = state
        if readonly_until is not None and now < readonly_until:
            return state
        kept = {
            k: v
            for k, v in _unexpired(elevations, now).items()
            if not (k.startswith(_PENDING) or k == once or k.startswith(once + ":"))
        }
        return {**kept, grant_key: until}, 0, None

    return change


class _Strike:
    """One more invalid step-up, counted on the row: the third downgrades the session to
    read-only for 5 minutes and ends every elevation. A downgrade that landed during the factor
    check stands as it was set: the row is left alone, so it is neither renewed nor counted
    twice. `downgraded` tells whether this write started the downgrade; the repository calls the
    change once, under the row lock, and each call sets it afresh."""

    def __init__(self, now: datetime) -> None:
        self._now = now
        self.downgraded = False

    def __call__(self, state: StepUpState) -> StepUpState:
        elevations, failures, readonly_until = state
        self.downgraded = False
        if readonly_until is not None and self._now < readonly_until:
            return state
        if failures + 1 >= FAILURE_CAP:
            self.downgraded = True
            return {}, FAILURE_CAP, self._now + READONLY_WINDOW
        return _unexpired(elevations, self._now), failures + 1, None


def _lift(now: datetime) -> StepUpChange:
    """End a downgrade that has run out; a downgrade lifted or renewed meanwhile is kept."""

    def change(state: StepUpState) -> StepUpState:
        elevations, _failures, readonly_until = state
        if readonly_until is None or now < readonly_until:
            return state
        return elevations, 0, None

    return change


@dataclass(frozen=True)
class ResetPreview:
    target_user_id: uuid.UUID
    #: `None` = unknown (no position store deployed); never a silent 0.
    open_position_count: int | None
    position_source: str
    message: str

    @property
    def positions_known(self) -> bool:
        return self.open_position_count is not None


@dataclass(frozen=True)
class ResetResult:
    """Deliberately no secret / recovery-code field (ticket "Reset reveals
    nothing")."""

    target_user_id: uuid.UUID
    methods_revoked: int
    sessions_revoked: int


class ResetAudit(Protocol):
    """Write-ahead audit of an owner TOTP reset (C-2.9, #2510), given the methods and live
    sessions about to be revoked, before the first revoke; a raise changes nothing."""

    async def __call__(self, methods: int, sessions: int, /) -> None: ...


class StepUpService:
    def __init__(
        self,
        mfa_repository: MfaRepository,
        session_repository: SessionRepository,
        encryptor: Decrypter,
        user_repository: UserRepository,
        hasher: Hasher,
        *,
        clock: Clock = _utc_now,
        publish_revocation: RevocationSink | None = None,
        chart: SessionChart | None = None,
        skew_reporter: TotpSkewReporter | None = None,
    ) -> None:
        self._chart = chart if chart is not None else SessionChart()
        #: #2272: the owner TOTP reset closes the target's sockets through it.
        self._publish_revocation = publish_revocation
        self._mfa = mfa_repository
        self._sessions = session_repository
        self._encryptor = encryptor
        self._users = user_repository
        self._hasher = hasher
        self._clock = clock
        self._skew_reporter = skew_reporter or TotpSkewReporter()

    @property
    def chart(self) -> SessionChart:
        return self._chart

    async def _record(
        self, record: SessionRecord, now: datetime, event: str, **payload: object
    ) -> None:
        """Record *event* on B16 after enforcement; first closes a grace
        window the row says has lapsed (`ELEVATION_DEADLINE`)."""
        sid = str(record.id)
        live = any(k in ACTION_CLASSES and v > now for k, v in record.step_up_elevations.items())
        await self._chart.record(record, now, "REQUEST", replay=True)  # ensure built
        if self._chart.in_state(sid, "elevated") and not live:
            await self._chart.record(record, now, "ELEVATION_DEADLINE")
        if event != "REQUEST":
            await self._chart.record(record, now, event, **payload)

    async def stop(self) -> None:
        await self._chart.stop()

    async def _live(self, session_id: str) -> SessionRecord | None:
        record = await self._sessions.find_by_id(session_id)
        return None if record is None or record.is_revoked else record

    async def _update(self, session_id: str, change: StepUpChange) -> SessionRecord:
        """Apply `change` to the step-up columns as the row holds them now (#2304)."""
        saved = await self._sessions.update_step_up_state(session_id, change)
        if saved is None:  # revoked meanwhile: fail closed (401, never a challenge)
            raise SessionRevoked("step_up")
        return saved

    # -- read-only downgrade ---------------------------------------------

    async def assert_writable(self, session_id: str) -> None:
        """Every write route calls this; raises `SessionReadOnly` during the
        downgrade window."""
        record = await self._live(session_id)
        if record is None or record.readonly_until is None:
            return
        now = self._clock()
        if now < record.readonly_until:
            raise SessionReadOnly(record.readonly_until)
        saved = await self._update(session_id, _lift(now))
        if saved.readonly_until is not None:  # three new strikes renewed it meanwhile
            raise SessionReadOnly(saved.readonly_until)
        await self._chart.record(record, now, "REQUEST", replay=True)
        if self._chart.in_state(str(record.id), "readonly_downgrade"):
            await self._chart.record(record, now, "READONLY_EXPIRED")

    # -- step-up -----------------------------------------------------------

    async def step_up(
        self,
        user_id: str,
        session_id: str,
        action_class: str | None,
        code: str,
        password: str,
        *,
        challenge_id: uuid.UUID | None = None,
    ) -> StepUpGrant:
        """Re-authenticate with password **and** TOTP (owner decision #1778 AE).

        Elevates the class of the session's live challenge; `action_class` is a
        cross-check, or names a grace class when no challenge is live (#2304).
        `StepUpChallengeRefused` is decided before any factor is checked. Every
        failure - wrong password, locked account, wrong/replayed code - raises
        the same `StepUpCodeInvalid` and is counted identically."""
        if action_class is not None and action_class not in ACTION_CLASSES:
            raise UnknownActionClass(action_class)
        await self.assert_writable(session_id)
        record = await self._live(session_id)
        if record is None:
            raise SessionRevoked("step_up")
        now = self._clock()
        action_class, challenge = _answered(record, now, action_class, challenge_id)
        if not await self._verify_both(user_id, code, password, now):
            auth_stepup_failures_total.inc()  # SR-125; the audit row names the action class
            strike = _Strike(now)
            struck = await self._update(session_id, strike)
            await self._record(
                record, now, "STEP_UP_FAILED", action_class=action_class, now_us=to_us(now)
            )
            if struck.readonly_until is not None:
                if strike.downgraded:  # one that landed meanwhile was counted when it began
                    auth_readonly_downgrades_total.inc()
                raise SessionReadOnly(struck.readonly_until)
            raise StepUpCodeInvalid(FAILURE_CAP - struck.step_up_failures)
        until = now + GRACE_WINDOW
        single_use = action_class in NO_GRACE_ACTION_CLASSES
        # No-grace classes store a one-shot grant under "once:<class>" that a
        # handler consumes via `consume_single_use`; grace classes a window.
        grant_key = f"{_ONCE}{action_class}" if single_use else action_class
        saved = await self._update(session_id, _elevate(action_class, grant_key, until, now))
        if saved.readonly_until is not None:  # downgraded during the factor check
            raise SessionReadOnly(saved.readonly_until)
        cid = None if challenge is None else challenge.challenge_id
        await self._record(
            record,
            now,
            "STEP_UP_OK",
            action_class=action_class,
            elevated_until_us=to_us(until),
            **({} if cid is None else {"challenge_id": str(cid)}),
        )
        auth_step_up_total.labels(action_class=action_class).inc()
        return StepUpGrant(action_class, until, single_use=single_use, challenge_id=cid)

    async def record_pending(
        self, session_id: str, action_class: str, *, fingerprint: str | None = None
    ) -> StepUpChallenge:
        """Issue the challenge for the request a `403 step_up_required` refuses (#2304): a
        random id scoped to this session, expiring in 5 minutes, recording the refused
        request's `fingerprint` when the route names it. It supersedes the session's live
        challenge, so `POST /auth/step-up` elevates the class the server itself demanded.
        Server-side only."""
        if action_class not in ACTION_CLASSES:
            raise UnknownActionClass(action_class)
        if fingerprint is not None and not _FINGERPRINT.fullmatch(fingerprint):
            raise ValueError("fingerprint must be a hex SHA-256")
        record = await self._live(session_id)
        if record is None:
            raise SessionRevoked("step_up")
        now = self._clock()
        challenge = StepUpChallenge(uuid.uuid4(), action_class, now + CHALLENGE_WINDOW, fingerprint)
        await self._update(session_id, _issue(challenge.key(), challenge.expires_at, now))
        # Challenge issued (the 403 is decided): B16 audits `step_up_required`.
        await self._record(
            record,
            now,
            "ACTION_REQUEST",
            action_class=action_class,
            now_us=to_us(now),
            challenge_id=str(challenge.challenge_id),
        )
        return challenge

    async def live_challenge(self, session_id: str) -> StepUpChallenge | None:
        """The session's one live challenge, if any (#2304)."""
        record = await self._live(session_id)
        if record is None:
            return None
        return next(iter(_stored(record, self._clock(), _PENDING)), None)

    async def pending_action_class(self, session_id: str) -> str | None:
        challenge = await self.live_challenge(session_id)
        return None if challenge is None else challenge.action_class

    async def _verify_both(self, user_id: str, code: str, password: str, now: datetime) -> bool:
        """Password first (login's hasher + lockout counters), then TOTP.

        The TOTP step (and its replay guard) is only reached with a correct
        password, so a wrong password never burns a valid time step."""
        user = await self._users.find_by_id(user_id)
        if not await self._password_ok(user, password, now):
            return False
        return await self._verify(user_id, code, now)

    async def _password_ok(self, user: UserRecord | None, password: str, now: datetime) -> bool:
        if user is None:
            await self._hasher.verify_dummy(password)  # same Argon2id work as a real user
            return False
        ok = await self._hasher.verify(user.password_hash, password)  # always, even if locked
        if user.locked_until is not None and user.locked_until > now:
            return False  # locked accounts are refused like any other failure
        if not ok:
            locked_until = await self._users.record_login_failure(
                str(user.id),
                lockout_threshold=LOCKOUT_THRESHOLD,
                lock_duration=LOCKOUT_DURATION,
                now=now,
            )
            if locked_until is not None:
                auth_lockouts_total.inc()  # SR-125: a wrong step-up password can lock the account
        return ok

    async def _verify(self, user_id: str, code: str, now: datetime) -> bool:
        refused: list[tuple[bytes, int | None]] = []
        for method in await self._mfa.find_active_totp_methods(user_id):
            if method.secret_enc is None:
                continue
            seed = self._encryptor.decrypt(method.secret_enc)
            step = verify_code(seed, code, unix_time=now.timestamp())
            if step is None:
                refused.append((seed, method.last_accepted_time_step))
                continue
            # Same replay protection as login codes (ticket Security notes).
            return await self._mfa.record_time_step(str(method.id), time_step=step)
        # #2146: reached only with a correct password; holds a report for a skewed clock.
        self._skew_reporter.report_rejection(refused, code, unix_time=now.timestamp())
        return False

    async def remaining_grace(self, session_id: str, action_class: str) -> timedelta | None:
        """Remaining window for the dialog text; None if none / no-grace."""
        if action_class in NO_GRACE_ACTION_CLASSES:
            return None
        record = await self._live(session_id)
        until = record.step_up_elevations.get(action_class) if record else None
        now = self._clock()
        if until is None or until <= now:
            return None
        return until - now

    async def consume_single_use(self, session_id: str, action_class: str) -> None:
        """Handler-side check for no-grace classes: succeeds once per fresh
        step-up code, then the one-shot grant is gone. The grant is removed by
        one conditional write (#2798), so of two requests racing to use it one
        does; the other is refused as if it had none."""
        await self.assert_writable(session_id)
        used = await self._sessions.consume_step_up_key(
            session_id, key=f"{_ONCE}{action_class}", now=self._clock()
        )
        if used is None:  # no live grant: never granted, expired, used or the session ended
            raise StepUpRequired(action_class)

    async def require_elevation(self, session_id: str, action_class: str) -> None:
        """Server-side gate for `is_dangerous` routes (the E09-T03 decision
        point calls this). No-grace classes always raise: those actions must
        carry a fresh code (`step_up()` -> `StepUpGrant.single_use`). An
        unregistered class is a server defect, never a challenge (#2304)."""
        await self.assert_writable(session_id)
        if action_class not in ACTION_CLASSES:
            raise UnknownActionClass(action_class)
        if await self.remaining_grace(session_id, action_class) is None:
            raise StepUpRequired(action_class)
        record = await self._live(session_id)
        if record is not None:  # allowed under grace: B16 audits `grace_used`
            now = self._clock()
            await self._record(
                record, now, "ACTION_REQUEST", action_class=action_class, now_us=to_us(now)
            )

    # -- owner TOTP reset ----------------------------------------------------

    async def preview_reset(
        self, target_user_id: str, positions: PositionStateProvider
    ) -> ResetPreview:
        """State shown to the owner *before* confirming. Unknown position
        state is reported as unknown, never as zero."""
        count = await positions.open_position_count(target_user_id)
        tail = "Resetting does NOT cancel orders or flatten positions."
        if count is None:
            msg = (
                "Open-position state is UNAVAILABLE: no position store is deployed "
                f"(source: {positions.source}). The target may hold open positions. {tail}"
            )
        else:
            msg = f"Target has {count} open position(s). {tail}"
        return ResetPreview(uuid.UUID(target_user_id), count, positions.source, msg)

    async def reset_totp(
        self, *, actor_session_id: str, actor_user_id: str, target_user_id: str, audit: ResetAudit
    ) -> ResetResult:
        """Owner reset: revoke the target's methods and all their sessions
        (which ends their elevations too), nothing else. Requires a live
        `users` elevation; touches no OMS surface and returns no secret.
        Self-reset is refused, before the elevation check: no step-up can cure it.
        It cannot be undone, so `audit` is written ahead of the first revoke
        (C-2.9): if it raises, nothing changes."""
        if actor_user_id == target_user_id:
            raise SelfResetRefused("the owner cannot reset their own TOTP")
        await self.require_elevation(actor_session_id, "users")
        now = self._clock()
        methods = await self._mfa.find_active_methods(target_user_id)
        live = await self._sessions.find_live_by_user(target_user_id)
        await audit(len(methods), len(live))
        for method in methods:
            await self._mfa.revoke_method(str(method.id), now=now)
        revoked = await self._sessions.revoke_all_for_user(
            target_user_id, reason="mfa_reset_by_owner", now=now
        )
        # #2272: close the target's sockets first, before the chart records.
        await publish_revoked(
            self._publish_revocation, (str(gone.id) for gone in revoked), "mfa_reset_by_owner"
        )
        for gone in revoked:  # revoked by the row update above; B16 records it
            await self._chart.revoke(gone, now, "mfa_reset_by_owner")
        auth_mfa_resets_total.inc()
        return ResetResult(uuid.UUID(target_user_id), len(methods), len(revoked))
