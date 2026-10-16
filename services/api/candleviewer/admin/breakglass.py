"""Offline break-glass Owner MFA reset: the CLI flow (E09-S11 #2119 slice 4, SR-023; threat
model U10 and Sec.3.6.1, KV-E08, ADR-0009 Amendment 1). Slice 5 composes the ports.

Fixed order: the host journal under the run lock; the write-ahead `auth.break_glass_attempt`;
`--live` against the configured environment; the KEK proof; the cv-api probe; the Owner; a TTY
and a retyped phrase; in `live` one Owner recovery code (echo off); the one-transaction reset;
`auth.break_glass_refused` or `auth.break_glass_reset`; a bounded close (what Postgres did not
take stays in the journal for cv-api's boot fold-in). Without a journal nothing else runs: the
attempt and the refusal go straight to `audit_log` if it is reachable (else: a pre-audit
refusal). No input skips a record (C-4.14); no secret is printed, logged or audited (C-12.6).
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import re
import uuid
from collections.abc import Awaitable, Callable
from enum import IntEnum
from typing import Any, Protocol

import structlog

from candleviewer.admin.errors import BreakGlassUnavailable
from candleviewer.audit.models import AuditOutcome, ExchangeEnv, Severity
from candleviewer.auth.break_glass import BreakGlassRefusal, BreakGlassResetService
from candleviewer.auth.errors import BreakGlassRefused
from candleviewer.secrets import KekCheckResult
from candleviewer.settings import Environment

#: `actor_label` of every break-glass record (decision R3): no user acts.
ACTOR = "system:breakglass"
ATTEMPT = "auth.break_glass_attempt"
REFUSED = "auth.break_glass_refused"
RESET = "auth.break_glass_reset"
#: Bound on each precondition port; the run lock is held meanwhile, so cv-api cannot boot.
STEP_TIMEOUT_S = 60.0
#: Bound on each operator prompt (the sealed recovery-code envelope may take a while to fetch).
PROMPT_TIMEOUT_S = 300.0
#: Flush grace when a trail closes; what is not in `audit_log` by then stays in the journal.
CLOSE_GRACE_S = 10.0
#: A refusal code from `secrets` is recorded only if it looks like one (C-12.6).
_REASON_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_AUDITED = "Audit: every record reached audit_log."
_State = dict[str, Any] | None


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class BreakGlassExit(IntEnum):
    """The CLI's exit status: 0 only after a reset whose records were all written. Any other
    status says why the run did not reset; its lower-case name is the `reason` of the closing
    record (the reset service's `BreakGlassRefusal` values keep their spelling)."""

    RESET = 0
    STEP_FAILED = 1  # a check broke (a port raised or timed out); nothing changed
    RESET_FAILED = 3  # the reset rolled back, nothing changed (2 is argparse's usage error)
    HOST_FS_UNAVAILABLE = 4
    API_RUNNING = 5
    AUDIT_UNAVAILABLE = 6
    LIVE_FLAG_REQUIRED = 7
    LIVE_FLAG_MISMATCH = 8
    KEK_UNPROVEN = 9
    NOT_OWNER = 10
    NO_TTY = 11
    CONFIRMATION_MISMATCH = 12
    CONFIRMATION_TIMEOUT = 13
    RECOVERY_CODE_REQUIRED = 14
    RECOVERY_CODE_INVALID = 15

    @property
    def reason(self) -> str:
        return self.name.lower()


_X = BreakGlassExit
#: The reset service's refusals; none of them can map onto `RESET`.
_REFUSED_BY_RESET = {refusal.value: BreakGlassExit[refusal.name] for refusal in BreakGlassRefusal}


class AuditTrail(Protocol):
    """The host journal (an `AuditWriter` on `journal.wal`) or `audit_log` itself. `emit` has
    `AuditWriter.emit`'s shape and is durable when it returns; it raises otherwise."""

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: str | None,
        object_kind: str | None,
        object_id: str | None,
        object_label: str | None,
        outcome: AuditOutcome,
        severity: Severity,
        reason: str | None,
        after_state: dict[str, Any] | None,
        request_id: uuid.UUID | None,
        env: ExchangeEnv | None,
    ) -> None: ...

    async def close(self, grace_s: float) -> int:
        """Flush up to `grace_s`, stop, unlock; return the count not in `audit_log` yet."""
        ...


class Terminal(Protocol):
    """The operator's TTY. Only the recovery code is read, by `ask_secret` with echo off;
    nothing secret is ever written."""

    def is_interactive(self) -> bool: ...
    def write(self, line: str) -> None: ...
    async def ask(self, prompt: str) -> str: ...
    async def ask_secret(self, prompt: str) -> str: ...


def new_phrase_nonce() -> str:
    """Six random hex digits, so the phrase cannot be typed ahead or piped in (not secret)."""
    return os.urandom(3).hex().upper()


def confirmation_phrase(owner: str, environment: Environment, nonce: str) -> str:
    """What the operator retypes: the Owner, the environment (`live` included), the nonce."""
    return f"reset {owner} on {environment.value} {nonce}"


@dataclasses.dataclass(frozen=True, slots=True)
class BreakGlassPorts:
    """Everything the flow touches, composed by slice 5; none of it is a switch (C-4.14)."""

    #: The host journal under the run lock; raises `BreakGlassUnavailable` if it cannot.
    open_journal: Callable[[], Awaitable[AuditTrail]]
    #: Straight to `audit_log` (scenario S3), or None while Postgres is unreachable.
    open_direct: Callable[[], Awaitable[AuditTrail | None]]
    #: `secrets.prove_kek_possession`: metadata only, never enrols (decision O1).
    prove_kek: Callable[[], Awaitable[KekCheckResult]]
    #: True while another session of the CLI's database role is connected (R2c).
    api_running: Callable[[], Awaitable[bool]]
    #: The id of the active Owner with this username or email, else None.
    resolve_owner: Callable[[str], Awaitable[uuid.UUID | None]]
    #: Built with the configured environment, which decides the live recovery-code rule.
    reset: BreakGlassResetService
    terminal: Terminal
    new_run_id: Callable[[], uuid.UUID] = uuid.uuid4


def _label(owner: str) -> str:
    """The typed identifier as an audit label: enough to correlate runs, never the whole
    value (the field may hold a pasted secret, as on failed logins)."""
    head = "".join(c if c.isprintable() else "?" for c in owner[:3])
    return f"{head}***(len={len(owner)})" if owner else "(empty)"


class _StepFailed(Exception):
    """A precondition port raised or timed out: only the step and the error type travel on."""

    def __init__(self, step: str, error: str) -> None:
        super().__init__(step)
        self.step, self.error = step, error


@dataclasses.dataclass(frozen=True, slots=True)
class _Verdict:
    """How a run ends: `RESET` (its counts in `details`) or the status that says why not."""

    status: BreakGlassExit
    details: _State = None
    unrecorded: bool = False  # the closing record could not be written

    @property
    def exit(self) -> BreakGlassExit:
        return _X.AUDIT_UNAVAILABLE if self.unrecorded else self.status

    @property
    def record(self) -> tuple[str, AuditOutcome, str | None]:
        """The closing record's action, outcome and reason."""
        if self.status is _X.RESET:
            return RESET, AuditOutcome.SUCCESS, None
        if self.status is _X.RESET_FAILED:
            return RESET, AuditOutcome.FAILURE, self.status.reason
        broke = self.status is _X.STEP_FAILED
        return REFUSED, AuditOutcome.FAILURE if broke else AuditOutcome.DENIED, self.status.reason


class _Records:
    """One run's records on one trail: critical, `system:breakglass`, no user id."""

    def __init__(self, trail: AuditTrail, run_id: uuid.UUID, owner: str, env: Environment) -> None:
        self.trail, self.run_id, self.label = trail, run_id, _label(owner)
        self.env = ExchangeEnv(env.value)
        self.target: uuid.UUID | None = None

    async def write(
        self, action: str, outcome: AuditOutcome, reason: str | None, state: _State
    ) -> None:
        await self.trail.emit(
            action,
            actor_label=ACTOR,
            actor_user_id=None,
            object_kind="user",
            object_id=None if self.target is None else str(self.target),
            object_label=self.label,
            outcome=outcome,
            severity=Severity.CRITICAL,
            reason=reason,
            after_state=state,
            request_id=self.run_id,
            env=self.env,
        )


async def _close(trail: AuditTrail) -> int | None:
    """Close with the bounded grace; None if that failed (the journal keeps what it has)."""
    try:
        async with asyncio.timeout(CLOSE_GRACE_S + 5.0):
            return await trail.close(CLOSE_GRACE_S)
    except Exception as exc:
        _log().critical("breakglass.trail_close_failed", error=type(exc).__name__)
        return None


class BreakGlassFlow:
    """One break-glass run per `run()`. `environment` is the configured one (arch P9): it
    decides `live`, as it does for the reset service, and `--live` only has to confirm it."""

    def __init__(self, ports: BreakGlassPorts, *, environment: Environment) -> None:
        self._ports, self._environment = ports, environment
        self._live = environment is Environment.LIVE

    async def run(self, owner: str, *, live_flag: bool) -> BreakGlassExit:
        """Reset the MFA of the Owner named `owner` (username or email); `live_flag` is
        `--live`. Returns the exit status; no secret reaches the terminal or the log."""
        run_id = self._ports.new_run_id()
        try:
            async with asyncio.timeout(STEP_TIMEOUT_S):
                trail = await self._ports.open_journal()
        except Exception as exc:  # unusable, whatever the cause; a held run lock means cv-api
            held = isinstance(exc, BreakGlassUnavailable) and exc.reason == "api_running"
            error = type(exc).__name__
            _log().error("breakglass.journal_unavailable", run_id=str(run_id), error=error)
            status = _X.API_RUNNING if held else _X.HOST_FS_UNAVAILABLE
            return await self._refuse_unjournaled(run_id, owner, live_flag, status)
        records = _Records(trail, run_id, owner, self._environment)
        try:
            verdict = await self._journaled(records, owner, live_flag)
        finally:
            pending = await _close(trail)
        audit = _AUDITED if pending == 0 else "Audit: the journal did not close cleanly."
        if pending:
            audit = f"Audit: records waiting in the host journal: {pending}; cv-api folds them in."
        self._summarise(verdict, owner, audit)
        return verdict.exit

    def _intent(self, live_flag: bool) -> dict[str, Any]:
        return {"environment": self._environment.value, "live_flag": live_flag}

    async def _journaled(self, records: _Records, owner: str, live_flag: bool) -> _Verdict:
        run_id = str(records.run_id)
        try:
            await records.write(ATTEMPT, AuditOutcome.SUCCESS, None, self._intent(live_flag))
        except Exception as exc:  # not durable: refuse before any check (C-2.9)
            error = type(exc).__name__
            _log().critical("breakglass.attempt_unrecorded", run_id=run_id, error=error)
            return _Verdict(_X.AUDIT_UNAVAILABLE)
        verdict = await self._decide(records, owner, live_flag)
        action, outcome, reason = verdict.record
        try:
            await records.write(action, outcome, reason, verdict.details)
        except Exception as exc:
            error = type(exc).__name__
            _log().critical(
                "breakglass.outcome_unrecorded", run_id=run_id, reason=reason, error=error
            )
            return dataclasses.replace(verdict, unrecorded=True)
        _log().warning("breakglass.run_ended", run_id=run_id, reason=reason)
        return verdict

    async def _decide(self, records: _Records, owner: str, live_flag: bool) -> _Verdict:
        try:
            checked = await self._check(records, owner, live_flag)
            if isinstance(checked, _Verdict):
                return checked
            return await self._reset(records, checked)
        except _StepFailed as exc:
            step, error = exc.step, exc.error
        except Exception as exc:  # a port broke its contract: still recorded (C-2.9)
            step, error = "flow", type(exc).__name__
        _log().error("breakglass.step_failed", run_id=str(records.run_id), step=step, error=error)
        return _Verdict(_X.STEP_FAILED, {"step": step, "error": error})

    async def _step[T](self, step: str, call: Callable[[], Awaitable[T]]) -> T:
        try:
            async with asyncio.timeout(STEP_TIMEOUT_S):
                return await call()
        except Exception as exc:
            raise _StepFailed(step, type(exc).__name__) from None

    async def _check(self, records: _Records, owner: str, live_flag: bool) -> _Verdict | uuid.UUID:
        """The preconditions after the attempt record, in order; the target id if all hold."""
        if live_flag != self._live:  # --live confirms the configured environment, never sets it
            return _Verdict(_X.LIVE_FLAG_REQUIRED if self._live else _X.LIVE_FLAG_MISMATCH)
        proof = await self._step("kek_proof", self._ports.prove_kek)
        if not proof.kcv_ok:
            code = proof.reason if _REASON_CODE.fullmatch(proof.reason or "") else None
            return _Verdict(_X.KEK_UNPROVEN, {"proof": code or "kek_unavailable"})
        if await self._step("api_probe", self._ports.api_running):
            return _Verdict(_X.API_RUNNING)
        target = await self._step("owner_lookup", lambda: self._ports.resolve_owner(owner))
        if target is None:  # the identifier is echoed below only once it names an Owner
            return _Verdict(_X.NOT_OWNER)
        records.target = target
        refused = await self._confirm(owner)
        return target if refused is None else refused

    async def _confirm(self, owner: str) -> _Verdict | None:
        terminal = self._ports.terminal
        if not terminal.is_interactive():
            return _Verdict(_X.NO_TTY)
        phrase = confirmation_phrase(owner, self._environment, new_phrase_nonce())
        env = self._environment.value
        terminal.write(f"Break-glass revokes every MFA method and session of {owner} on {env}.")
        terminal.write(f"To confirm, type: {phrase}")
        try:
            async with asyncio.timeout(PROMPT_TIMEOUT_S):
                typed = await terminal.ask("> ")
        except TimeoutError:
            return _Verdict(_X.CONFIRMATION_TIMEOUT)
        except EOFError:
            typed = ""
        return None if typed.strip() == phrase else _Verdict(_X.CONFIRMATION_MISMATCH)

    async def _reset(self, records: _Records, target: uuid.UUID) -> _Verdict:
        code = None
        if self._live:  # one Owner recovery code, echo off; none at all is refused by the service
            try:
                async with asyncio.timeout(PROMPT_TIMEOUT_S):
                    code = await self._ports.terminal.ask_secret("Owner recovery code (hidden): ")
            except (TimeoutError, EOFError):
                code = None
        call = self._ports.reset.reset(target, recovery_code=code, correlation_id=records.run_id)
        del code  # the service hashes it before its first await: no frame here keeps it
        # No timer here: a cancel during COMMIT would leave the outcome unknown. Each statement
        # is bounded by the relational repository's `statement_timeout`.
        try:
            done = await call
        except BreakGlassRefused as exc:
            return _Verdict(_REFUSED_BY_RESET[exc.reason])
        except Exception as exc:  # rolled back: zero rows changed (scenario S10)
            error = type(exc).__name__
            _log().error("breakglass.reset_failed", run_id=str(records.run_id), error=error)
            return _Verdict(_X.RESET_FAILED, {"error": error})
        counts = {
            "methods_revoked": done.methods_revoked,
            "sessions_revoked": done.sessions_revoked,
            "codes_consumed": int(done.recovery_code_consumed),
            "system_event_id": done.system_event_id,
        }
        return _Verdict(_X.RESET, counts)

    async def _refuse_unjournaled(
        self, run_id: uuid.UUID, owner: str, live_flag: bool, status: BreakGlassExit
    ) -> BreakGlassExit:
        """No journal (scenario S3, or cv-api holds the run lock): nothing else runs. The
        attempt and the refusal go straight to `audit_log` if it can be reached."""
        recorded = False
        try:
            async with asyncio.timeout(STEP_TIMEOUT_S):
                trail = await self._ports.open_direct()
            if trail is not None:
                records = _Records(trail, run_id, owner, self._environment)
                try:
                    await records.write(
                        ATTEMPT, AuditOutcome.SUCCESS, None, self._intent(live_flag)
                    )
                    await records.write(REFUSED, AuditOutcome.DENIED, status.reason, None)
                finally:
                    pending = await _close(trail)
                recorded = pending == 0
        except Exception as exc:
            error = type(exc).__name__
            _log().error("breakglass.direct_audit_failed", run_id=str(run_id), error=error)
        log = _log().warning if recorded else _log().critical
        log("breakglass.refused_unjournaled", run_id=str(run_id), reason=status.reason, ok=recorded)
        pre_audit = "Audit: no record could be written (pre-audit refusal); the log has the reason."
        self._summarise(_Verdict(status), owner, _AUDITED if recorded else pre_audit)
        return status

    def _summarise(self, verdict: _Verdict, owner: str, audit: str) -> None:
        """The non-secret summary: counts, reason codes and where the records are."""
        write, details = self._ports.terminal.write, verdict.details or {}
        if verdict.status is _X.RESET:
            write(
                f"Break-glass reset done for {owner} on {self._environment.value}: "
                f"{details['methods_revoked']} MFA methods and {details['sessions_revoked']} "
                f"sessions revoked, system event {details['system_event_id']} raised. The Owner "
                "enrols TOTP again at the next sign-in."
            )
        else:
            more = details.get("proof") or details.get("step")
            why = f"{verdict.status.reason}: {more}" if more else verdict.status.reason
            write(f"Break-glass ended without a reset ({why}); nothing was changed.")
        if verdict.unrecorded:
            write("Audit: the outcome record could not be written; the attempt record is kept.")
        write(audit)
