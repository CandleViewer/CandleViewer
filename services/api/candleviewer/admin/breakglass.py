"""Offline break-glass Owner MFA reset: the CLI flow (E09-S11 #2119 slice 4, SR-023; threat
model U10 and Sec.3.6.1, KV-E08, ADR-0009 Amendment 1). Slice 5 composes the ports.

Fixed order: the host journal under the run lock; the write-ahead `auth.break_glass_attempt`;
`--live` against the configured environment; the KEK proof; the cv-api probe; the Owner; a TTY
and a retyped phrase; in `live` one Owner recovery code (echo off); the one-transaction reset;
`auth.break_glass_refused` or `auth.break_glass_reset`; a bounded close (what Postgres did not
take stays in the journal for cv-api's boot fold-in). Without a journal nothing else runs: the
attempt and the refusal go straight to `audit_log` if it is reachable (else: a pre-audit
refusal). No input skips a record (C-4.14); no secret is printed, logged or audited (C-12.6).
A cancel (Ctrl-C) before the reset is an `operator_cancelled` refusal; the reset and every
record run to their end, so the outcome is recorded; then the cancel is re-raised.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import re
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from enum import IntEnum
from typing import Any, Protocol

import structlog

from candleviewer.admin.errors import BreakGlassUnavailable
from candleviewer.audit.journal import ACTOR  # every record's `actor_label` (R3): no user acts
from candleviewer.audit.models import AuditOutcome, ExchangeEnv, Severity
from candleviewer.auth.break_glass import BreakGlassRefusal, BreakGlassResetService
from candleviewer.auth.errors import BreakGlassRefused
from candleviewer.observability import spawn
from candleviewer.secrets import KekCheckResult
from candleviewer.settings import Environment

#: The journal admits only these (`audit.journal.BREAK_GLASS_ACTIONS`; a test pins them).
ATTEMPT = "auth.break_glass_attempt"
REFUSED = "auth.break_glass_refused"
RESET = "auth.break_glass_reset"
#: Bound on each precondition port and each record; the run lock is held, so cv-api cannot boot.
STEP_TIMEOUT_S = 60.0
#: Bound on each operator prompt (the sealed recovery-code envelope may take a while to fetch).
PROMPT_TIMEOUT_S = 300.0
#: Flush grace when a trail closes; what is not in `audit_log` by then stays in the journal.
CLOSE_GRACE_S = 10.0
#: The close's margin beyond the grace (stop and unlock) before the CLI gives up on it.
CLOSE_SLACK_S = 5.0
#: A refusal code from `secrets` is recorded only if it looks like one (C-12.6).
_REASON_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_AUDITED = "Audit: every record reached audit_log."
_PRE_AUDIT = "Audit: no record could be written (pre-audit refusal); the log has the reason."
_UNRECORDED = "Audit: the outcome record could not be written; the attempt record is kept."
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
    RESET_FAILED = 3  # rolled back, or unknown if cut at COMMIT (2 is argparse's usage)
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
    OPERATOR_CANCELLED = 16  # recorded, then `run` re-raises the cancel; slice 5 exits with it

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


class Interrupted(Exception):
    """A record or the reset was cut short anyway (`asyncio.run` cancels every task on a second
    Ctrl-C): its outcome is unknown, so it is never reported as "nothing was changed"."""


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
    """One run's records on one trail: critical, `system:breakglass`, no user id. `cancelled`
    notes a cancel that came while a record or the reset ran to its end; `run` re-raises it."""

    def __init__(self, trail: AuditTrail, run_id: uuid.UUID, owner: str, env: Environment) -> None:
        self.trail, self.run_id, self.label = trail, run_id, _label(owner)
        self.env = ExchangeEnv(env.value)
        self.target: uuid.UUID | None = None
        self.cancelled = False

    async def to_the_end[T](self, call: Coroutine[Any, Any, T], name: str) -> T:
        """`call`'s result once it has ended, even if the run is cancelled meanwhile: a cancel
        that cut a record or the reset's COMMIT short would leave the outcome unknown."""
        task = spawn(call, name=f"breakglass.{name}")
        while not task.done():
            try:
                await asyncio.wait({task})
            except asyncio.CancelledError:  # noted here, re-raised by `run` (never swallowed)
                self.cancelled = True
        if task.cancelled():  # cut short itself: unknown, not "never happened"
            self.cancelled = True
            raise Interrupted(name)
        return task.result()

    async def write(
        self, action: str, outcome: AuditOutcome, reason: str | None, state: _State
    ) -> None:
        """Durable when it returns; raises if the trail refuses or takes too long."""
        await self.to_the_end(self._emit(action, outcome, reason, state), "record")

    async def _emit(
        self, action: str, outcome: AuditOutcome, reason: str | None, state: _State
    ) -> None:
        async with asyncio.timeout(STEP_TIMEOUT_S):
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
        async with asyncio.timeout(CLOSE_GRACE_S + CLOSE_SLACK_S):
            return await trail.close(CLOSE_GRACE_S)
    except Exception as exc:
        _log().critical("breakglass.trail_close_failed", error=type(exc).__name__)
        return None


def _audit_lines(verdict: _Verdict, pending: int | None) -> list[str]:
    """Where the records are, never more than was written (C-2.9): `pending` is what the
    journal's close left outside `audit_log` (None: it did not close cleanly)."""
    if verdict.status is _X.AUDIT_UNAVAILABLE:  # the attempt record itself was not written
        return [_PRE_AUDIT]
    lines = [_UNRECORDED] if verdict.unrecorded else []
    if pending is None:
        lines.append("Audit: the journal did not close cleanly.")
    elif pending:
        waiting = f"records waiting in the host journal: {pending}; cv-api folds them in."
        lines.append(f"Audit: {waiting}")
    elif not verdict.unrecorded:
        lines.append(_AUDITED)
    return lines


class BreakGlassFlow:
    """One break-glass run per `run()`. The environment is the reset service's, the configured
    one (arch P9): the one source of `live`, which `--live` only has to confirm."""

    def __init__(self, ports: BreakGlassPorts) -> None:
        self._ports, self._environment = ports, ports.reset.environment
        self._live = self._environment is Environment.LIVE

    async def run(self, owner: str, *, live_flag: bool) -> BreakGlassExit:
        """Reset the MFA of the Owner named `owner` (username or email); `live_flag` is
        `--live`. Returns the exit status; no secret reaches the terminal or the log. A cancel
        is recorded and summarised first, then re-raised."""
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
        self._summarise(verdict, owner, _audit_lines(verdict, pending), records.cancelled)
        if records.cancelled:
            raise asyncio.CancelledError  # honoured now that the trail is closed
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
        verdict = _Verdict(_X.OPERATOR_CANCELLED)  # cancelled during the attempt record
        if not records.cancelled:
            try:
                verdict = await self._decide(records, owner, live_flag)
            except asyncio.CancelledError:  # before the reset began: a recorded refusal
                records.cancelled = True
        if records.cancelled:
            _log().warning("breakglass.run_cancelled", run_id=run_id, reason=verdict.status.reason)
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
        try:  # probed again, last: a cv-api may have connected during the prompts (R2c)
            running = await self._step("api_probe", self._ports.api_running)
        except BaseException:
            del code  # no frame of a probe failure or a cancel keeps the plaintext code
            raise
        if running:
            return _Verdict(_X.API_RUNNING)
        call = self._ports.reset.reset(target, recovery_code=code, correlation_id=records.run_id)
        del code  # the service hashes it before its first await: no frame here keeps it
        # No timer and no cancel cuts it: either would leave the outcome unknown if it hit
        # COMMIT. Each statement is bounded by the relational repository's `statement_timeout`.
        try:
            done = await records.to_the_end(call, "reset")
        except BreakGlassRefused as exc:
            return _Verdict(_REFUSED_BY_RESET[exc.reason])
        except Exception as exc:  # rolled back (S10), or unknown if the link broke at COMMIT
            error = type(exc).__name__
            _log().error("breakglass.reset_failed", run_id=str(records.run_id), error=error)
            return _Verdict(_X.RESET_FAILED, {"error": error, "outcome": "rolled_back_or_unknown"})
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
        recorded, cancelled = False, False
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
                    pending, cancelled = await _close(trail), records.cancelled
                recorded = pending == 0
        except Exception as exc:
            error = type(exc).__name__
            _log().error("breakglass.direct_audit_failed", run_id=str(run_id), error=error)
        log = _log().warning if recorded else _log().critical
        log("breakglass.refused_unjournaled", run_id=str(run_id), reason=status.reason, ok=recorded)
        self._summarise(_Verdict(status), owner, [_AUDITED if recorded else _PRE_AUDIT], cancelled)
        if cancelled:
            raise asyncio.CancelledError  # honoured once both records ran to their end
        return status

    def _summarise(self, verdict: _Verdict, owner: str, audit: list[str], cancelled: bool) -> None:
        """The non-secret summary: the outcome, reason codes and where the records are."""
        write, details = self._ports.terminal.write, verdict.details or {}
        more = details.get("proof") or details.get("step") or details.get("error")
        why = f"{verdict.status.reason}: {more}" if more else verdict.status.reason
        if verdict.status is _X.RESET:
            write(
                f"Break-glass reset done for {owner} on {self._environment.value}: "
                f"{details['methods_revoked']} MFA methods and {details['sessions_revoked']} "
                f"sessions revoked, system event {details['system_event_id']} raised. The Owner "
                "enrols TOTP again at the next sign-in."
            )
        elif verdict.status is _X.RESET_FAILED:  # a link lost at COMMIT may still have applied it
            write(
                f"Break-glass reset failed ({why}); no change is confirmed. Before re-running, "
                "check for an unresolved break_glass_used system event: if there is one, the "
                "reset applied."
            )
        else:
            write(f"Break-glass ended without a reset ({why}); nothing was changed.")
        if cancelled and verdict.status is not _X.OPERATOR_CANCELLED:
            # A reset or record under way ended first, or was cut short: the line above says so.
            write("Cancelled: the line above says how the run ended.")
        for line in audit:
            write(line)
