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
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from candleviewer.auth.errors import (
    SessionReadOnly,
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
    auth_step_up_failures_total,
    auth_step_up_total,
    auth_stepup_failures_total,
)
from candleviewer.auth.mfa_repository import MfaRepository
from candleviewer.auth.models import SessionRecord, UserRecord
from candleviewer.auth.repository import UserRepository
from candleviewer.auth.session_chart import SessionChart, to_us
from candleviewer.auth.session_repository import SessionRepository
from candleviewer.auth.session_service import RevocationSink, publish_revoked
from candleviewer.auth.totp import verify_code
from candleviewer.auth.totp_skew import TotpSkewReporter

#: Ticket: "a 5-minute grace per action class".
GRACE_WINDOW = timedelta(minutes=5)
#: Ticket: three invalid codes abandon the action.
FAILURE_CAP = 3
#: Ticket: read-only downgrade lasts 5 minutes.
READONLY_WINDOW = timedelta(minutes=5)
ACTION_CLASSES = frozenset({"keys", "users", "live_enablement", "killswitch", "risk_caps"})
#: Ticket "No-grace list": always a fresh code.
NO_GRACE_ACTION_CLASSES = frozenset({"live_enablement", "killswitch"})
#: `PositionStateProvider.source` when no position store exists yet.
POSITION_SOURCE_NOT_DEPLOYED = "not_deployed"
#: Key prefix (in `step_up_elevations`) of the challenge issued by the last 403.
_PENDING = "pending:"


def grace_expires_at(elevations: dict[str, datetime], now: datetime) -> datetime | None:
    """Latest live grace-window expiry (excludes pending challenges and
    one-shot grants) - the `step_up_expires_at` the dialog counts down."""
    live = [v for k, v in elevations.items() if k in ACTION_CLASSES and v > now]
    return max(live) if live else None


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

    async def _save(
        self,
        session_id: str,
        *,
        elevations: dict[str, datetime],
        failures: int,
        readonly_until: datetime | None,
    ) -> None:
        saved = await self._sessions.save_step_up_state(
            session_id, elevations=elevations, failures=failures, readonly_until=readonly_until
        )
        if saved is None:  # revoked meanwhile: fail closed
            raise StepUpRequired("session")

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
        await self._save(
            session_id, elevations=dict(record.step_up_elevations), failures=0, readonly_until=None
        )
        await self._chart.record(record, now, "REQUEST", replay=True)
        if self._chart.in_state(str(record.id), "readonly_downgrade"):
            await self._chart.record(record, now, "READONLY_EXPIRED")

    # -- step-up -----------------------------------------------------------

    async def step_up(
        self, user_id: str, session_id: str, action_class: str, code: str, password: str
    ) -> StepUpGrant:
        """Re-authenticate with password **and** TOTP (owner decision #1778 AE).

        Every failure - wrong password, locked account, wrong/replayed code -
        raises the same `StepUpCodeInvalid` and is counted identically."""
        if action_class not in ACTION_CLASSES:
            raise UnknownActionClass(action_class)
        await self.assert_writable(session_id)
        record = await self._live(session_id)
        if record is None:
            raise StepUpRequired(action_class)
        now = self._clock()
        elevations = {k: v for k, v in record.step_up_elevations.items() if v > now}
        if not await self._verify_both(user_id, code, password, now):
            auth_step_up_failures_total.labels(action_class=action_class).inc()
            auth_stepup_failures_total.inc()  # SR-125 catalogue series (scraped, no label)
            failures = record.step_up_failures + 1
            if failures >= FAILURE_CAP:
                until = now + READONLY_WINDOW
                auth_readonly_downgrades_total.inc()
                await self._save(
                    session_id, elevations={}, failures=FAILURE_CAP, readonly_until=until
                )
                await self._record(
                    record, now, "STEP_UP_FAILED", action_class=action_class, now_us=to_us(now)
                )
                raise SessionReadOnly(until)
            await self._save(
                session_id, elevations=elevations, failures=failures, readonly_until=None
            )
            await self._record(
                record, now, "STEP_UP_FAILED", action_class=action_class, now_us=to_us(now)
            )
            raise StepUpCodeInvalid(FAILURE_CAP - failures)
        until = now + GRACE_WINDOW
        single_use = action_class in NO_GRACE_ACTION_CLASSES
        # No-grace classes store a one-shot grant under "once:<class>" that a
        # handler consumes via `consume_single_use`; grace classes a window.
        elevations = {k: v for k, v in elevations.items() if not k.startswith(_PENDING)}
        elevations[f"once:{action_class}" if single_use else action_class] = until
        await self._save(session_id, elevations=elevations, failures=0, readonly_until=None)
        await self._record(
            record,
            now,
            "STEP_UP_OK",
            action_class=action_class,
            elevated_until_us=to_us(until),
        )
        auth_step_up_total.labels(action_class=action_class).inc()
        return StepUpGrant(action_class, until, single_use=single_use)

    async def record_pending(self, session_id: str, action_class: str) -> None:
        """Remember which action class the last 403 step_up_required challenged,
        so `POST /auth/step-up` with only `{code}` (the merged M-020 modal)
        elevates the class the server itself demanded. Server-side only."""
        record = await self._live(session_id)
        if record is None or action_class not in ACTION_CLASSES:
            return
        now = self._clock()
        elevations = {
            k: v
            for k, v in record.step_up_elevations.items()
            if v > now and not k.startswith(_PENDING)
        }
        elevations[_PENDING + action_class] = now + GRACE_WINDOW
        await self._save(
            session_id,
            elevations=elevations,
            failures=record.step_up_failures,
            readonly_until=record.readonly_until,
        )
        # Challenge issued (the 403 is decided): B16 audits `step_up_required`.
        await self._record(
            record, now, "ACTION_REQUEST", action_class=action_class, now_us=to_us(now)
        )

    async def pending_action_class(self, session_id: str) -> str | None:
        record = await self._live(session_id)
        if record is None:
            return None
        now = self._clock()
        for key, until in record.step_up_elevations.items():
            if key.startswith(_PENDING) and until > now:
                return key[len(_PENDING) :]
        return None

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
        step-up code, then the one-shot grant is gone."""
        await self.assert_writable(session_id)
        record = await self._live(session_id)
        key = f"once:{action_class}"
        now = self._clock()
        until = record.step_up_elevations.get(key) if record else None
        if record is None or until is None or until <= now:
            raise StepUpRequired(action_class)
        remaining = {k: v for k, v in record.step_up_elevations.items() if k != key and v > now}
        await self._save(
            session_id,
            elevations=remaining,
            failures=record.step_up_failures,
            readonly_until=None,
        )

    async def require_elevation(self, session_id: str, action_class: str) -> None:
        """Server-side gate for `is_dangerous` routes (the E09-T03 decision
        point calls this). No-grace classes always raise: those actions must
        carry a fresh code (`step_up()` -> `StepUpGrant.single_use`)."""
        await self.assert_writable(session_id)
        if action_class not in ACTION_CLASSES:
            raise StepUpRequired(action_class)
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
        self, *, actor_session_id: str, actor_user_id: str, target_user_id: str
    ) -> ResetResult:
        """Owner reset: revoke the target's methods and all their sessions
        (which ends their elevations too), nothing else. Requires a live
        `users` elevation; touches no OMS surface and returns no secret.
        Self-reset is refused."""
        await self.require_elevation(actor_session_id, "users")
        if actor_user_id == target_user_id:
            raise StepUpRequired("users")
        now = self._clock()
        methods = await self._mfa.find_active_methods(target_user_id)
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
