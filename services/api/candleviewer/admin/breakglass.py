"""Offline break-glass Owner MFA reset: the CLI flow (E09-S11 #2119 slice 4, SR-023; threat
model U10 and Sec.3.6.1, KV-E08, ADR-0009 Amendment 1). `admin.breakglass_wiring` composes the
ports and `python -m candleviewer.breakglass` runs the flow (slice 5).

Fixed order: the host journal under the run lock; the write-ahead `auth.break_glass_attempt`;
`--live` against the configured environment; the KEK proof; the cv-api probe; the Owner; a TTY
and a retyped phrase; in `live` one Owner recovery code (echo off); the one-transaction reset;
`auth.break_glass_refused` or `auth.break_glass_reset`; a bounded close (what Postgres did not
take stays in the journal for cv-api's boot fold-in). Without a journal nothing else runs: the
attempt and the refusal go straight to `audit_log` if it is reachable (else: a pre-audit
refusal). No input skips a record (C-4.14); no secret is printed, logged or audited (C-12.6).
A cancel (Ctrl-C) before the reset is an `operator_cancelled` refusal; the reset and every
record run to their end, so the outcome is recorded; a cancel cuts only a trail's open or close.
The summary is shown, then `RunCancelled` re-raises the cancel with the run's exit status.

That order is the host gate, `HostGatedFlow`, which a second offline CLI reuses as it is (#4479):
its steps are final, so no flow reorders or drops one. `BreakGlassFlow` brings only its own steps:
the Owner (`_target`), the line above the phrase, the recovery code and the reset (`_act`, where
the gate's last cv-api probe follows the prompts, right before the reset), and the summary's
first line (`_outcome`). Its `GateSpec` names its actions, actor, log events, task names, phrase
verb and exit status; the statuses the gate itself ends a run with (`GATE_STATUSES`) keep one
number in every CLI.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import re
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from enum import IntEnum
from types import MappingProxyType
from typing import Any, Final, Generic, Protocol, TypeVar, final

import structlog

from candleviewer.admin.audited import audit_exempt, audited
from candleviewer.admin.errors import BreakGlassUnavailable
from candleviewer.audit.actions import validate_action
from candleviewer.audit.journal import (
    ACTOR,  # every record's `actor_label` (R3): no user acts
    BOOTSTRAP_OWNER_ACTIONS,  # `_Records.write` (DC-4479-18)
)
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
    OPERATOR_CANCELLED = 16  # cancelled before a reset began; carried by `RunCancelled`

    @property
    @audit_exempt("read")
    def reason(self) -> str:
        return self.name.lower()


class RunCancelled(asyncio.CancelledError):
    """The run was cancelled (Ctrl-C), raised once the summary is shown. `exit` is how the run
    ended: OPERATOR_CANCELLED if the cancel stopped it before a reset began, else the status
    already under way, so a reset that applied stays RESET. The CLI exits with it by catching
    this inside the coroutine it gives `asyncio.run`: one that escapes turns into KeyboardInterrupt
    there and its `exit` is lost. It is the gate's, so `exit` is a member of the flow's status."""

    def __init__(self, status: IntEnum) -> None:
        super().__init__(status)  # `args` alone rebuild it (copy, pickle)
        self.exit = status


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
    """The operator's TTY. Only a secret the flow asks for (break-glass: the recovery code) is
    read, by `ask_secret` with echo off; nothing secret is ever written."""

    def is_interactive(self) -> bool: ...
    def write(self, line: str) -> None: ...
    async def ask(self, prompt: str) -> str: ...
    async def ask_secret(self, prompt: str) -> str: ...


def new_phrase_nonce() -> str:
    """Six random hex digits, so the phrase cannot be typed ahead or piped in (not secret)."""
    return os.urandom(3).hex().upper()


def confirmation_phrase(
    owner: str, environment: Environment, nonce: str, verb: str = "reset"
) -> str:
    """What the operator retypes: the flow's verb, the Owner, the environment (`live` included),
    the nonce."""
    return f"{verb} {owner} on {environment.value} {nonce}"


class GatePorts(Protocol):
    """The ports the gate itself uses; a flow's own (`BreakGlassPorts`) add those of its steps."""

    @property
    def open_journal(self) -> Callable[[], Awaitable[AuditTrail]]: ...
    @property
    def open_direct(self) -> Callable[[], Awaitable[AuditTrail | None]]: ...
    @property
    def prove_kek(self) -> Callable[[], Awaitable[KekCheckResult]]: ...
    @property
    def api_running(self) -> Callable[[], Awaitable[bool]]: ...
    @property
    def terminal(self) -> Terminal: ...
    @property
    def new_run_id(self) -> Callable[[], uuid.UUID]: ...


@dataclasses.dataclass(frozen=True, slots=True)
class BreakGlassPorts:
    """Everything the flow touches, composed by slice 5; none of it is a switch (C-4.14)."""

    #: The host journal under the run lock; raises `BreakGlassUnavailable` if it cannot.
    open_journal: Callable[[], Awaitable[AuditTrail]]
    #: Straight to `audit_log` (scenario S3), or None while Postgres is unreachable.
    open_direct: Callable[[], Awaitable[AuditTrail | None]]
    #: `secrets.prove_kek_possession`: metadata only, never enrols (decision O1).
    prove_kek: Callable[[], Awaitable[KekCheckResult]]
    #: True while another session of the CLI's database role is connected (R2c): the
    #: `pg_stat_activity` probe of `SqlAlchemyBreakGlassDatabase.others_connected`.
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
    """A record or the act (break-glass: the reset) was cut short anyway (`asyncio.run` cancels
    every task on a second Ctrl-C): its outcome is unknown, so it is never reported as "nothing
    was changed"."""


@dataclasses.dataclass(frozen=True, slots=True)
class _Verdict:
    """How a run ends: the spec's done status (its counts in `details`) or the status that says
    why not."""

    status: IntEnum
    details: _State = None
    unrecorded: bool = False  # the closing record could not be written

    @property
    @audit_exempt("read")
    def exit(self) -> IntEnum:
        return type(self.status)["AUDIT_UNAVAILABLE"] if self.unrecorded else self.status


#: The statuses the gate itself ends a run with, by name and number. Every flow's exit status
#: defines them with these numbers (`GateSpec` refuses one that does not), so that each number
#: means one thing in every offline CLI.
GATE_STATUSES: Final[Mapping[str, int]] = MappingProxyType({
    "STEP_FAILED": 1, "HOST_FS_UNAVAILABLE": 4, "API_RUNNING": 5, "AUDIT_UNAVAILABLE": 6,
    "LIVE_FLAG_REQUIRED": 7, "LIVE_FLAG_MISMATCH": 8, "KEK_UNPROVEN": 9, "NO_TTY": 11,
    "CONFIRMATION_MISMATCH": 12, "CONFIRMATION_TIMEOUT": 13, "OPERATOR_CANCELLED": 16,
})  # fmt: skip


@final
@dataclasses.dataclass(frozen=True, slots=True)
class GateSpec:
    """What one offline CLI names on the gate: `name` prefixes its log events and task names;
    `actor`, a `system:` label, is every record's `actor_label`; `attempt`, `refused` and `done`
    are its actions, registered ones (its journal admits only these); `verb` opens the phrase.
    `exits` is its exit status, one number per status: it holds `GATE_STATUSES` with their
    numbers and two of its own, `done_status` (0: the act done and recorded) and `failed_status`
    (the act failed, or its outcome is unknown). All of it is checked when the spec is built."""

    name: str
    actor: str
    attempt: str
    refused: str
    done: str
    verb: str
    exits: type[IntEnum]
    done_status: str
    failed_status: str

    def __post_init__(self) -> None:
        for action in (self.attempt, self.refused, self.done):
            validate_action(action)  # at import, not at the first record under the run lock
        if not self.actor.startswith("system:"):  # no user acts on the host (R3)
            raise ValueError(f"the actor {self.actor!r} is not a system: label")
        exits, own = self.exits.__name__, {self.done_status, self.failed_status}
        if len(self.exits) != len(self.exits.__members__):  # an alias: two names, one status
            raise ValueError(f"{exits} gives two of its statuses one number")
        if len(own) < 2 or not own.isdisjoint(GATE_STATUSES):
            raise ValueError(f"{exits}: its done and failed statuses are two of its own")
        numbers = {status.name: int(status) for status in self.exits}
        wanted = {**GATE_STATUSES, self.done_status: 0}
        if self.failed_status not in numbers or any(numbers.get(k) != n for k, n in wanted.items()):
            raise ValueError(
                f"{exits} must number {wanted} as the gate does and define {self.failed_status}"
            )

    @audit_exempt("read")
    def record_of(self, verdict: _Verdict) -> tuple[str, AuditOutcome, str | None]:
        """The closing record's action, outcome and reason. A status of another exit status is
        refused, never recorded under this spec's actions (C-2.9)."""
        status, reason = verdict.status, verdict.status.name.lower()
        if type(status) is not self.exits:
            raise TypeError(f"a {type(status).__name__} status, not a {self.exits.__name__}")
        if status is self.exits[self.done_status]:
            return self.done, AuditOutcome.SUCCESS, None
        if status is self.exits[self.failed_status]:
            return self.done, AuditOutcome.FAILURE, reason
        broke = status is self.exits["STEP_FAILED"]
        return self.refused, AuditOutcome.FAILURE if broke else AuditOutcome.DENIED, reason


_BREAK_GLASS = GateSpec(
    "breakglass", ACTOR, ATTEMPT, REFUSED, RESET, "reset", BreakGlassExit, "RESET", "RESET_FAILED"
)


class _Records:
    """One run's records on one trail: critical, the spec's actor (`system:breakglass`), no user
    id. `landed` counts those the trail took; `cancelled` notes a cancel that came while a
    record, the act (the reset) or the close ran (`run` re-raises it after the summary)."""

    def __init__(
        self, spec: GateSpec, trail: AuditTrail, run_id: uuid.UUID, owner: str, env: Environment
    ) -> None:
        self.spec, self.trail, self.run_id, self.label = spec, trail, run_id, _label(owner)
        self.env = ExchangeEnv(env.value)
        self.target: uuid.UUID | None = None
        self.cancelled, self.landed = False, 0

    @audit_exempt("caller_audits")
    async def to_the_end[T](self, call: Coroutine[Any, Any, T], name: str) -> T:
        """`call`'s result once it has ended, even if the run is cancelled meanwhile: a cancel
        that cut a record or the act's COMMIT short would leave the outcome unknown."""
        task = spawn(call, name=f"{self.spec.name}.{name}")
        while not task.done():
            try:
                await asyncio.wait({task})
            except asyncio.CancelledError:  # noted here, re-raised by `run` (never swallowed)
                self.cancelled = True
        if task.cancelled():  # cut short itself: unknown, not "never happened"
            self.cancelled = True
            raise Interrupted(name)
        return task.result()

    @audited(ATTEMPT, REFUSED, RESET, *sorted(BOOTSTRAP_OWNER_ACTIONS))
    async def write(
        self, action: str, outcome: AuditOutcome, reason: str | None, state: _State
    ) -> None:
        """Durable when it returns; raises if the trail refuses or takes too long."""
        await self.to_the_end(self._emit(action, outcome, reason, state), "record")
        self.landed += 1

    @audit_exempt("lifecycle")
    async def close(self) -> int | None:
        """Close with the bounded grace: the count not in `audit_log` yet, or None if the close
        failed or was cancelled (the journal keeps what it has; the cancel is noted)."""
        try:
            async with asyncio.timeout(CLOSE_GRACE_S + CLOSE_SLACK_S):
                return await self.trail.close(CLOSE_GRACE_S)
        except asyncio.CancelledError:  # Ctrl-C in the flush grace: noted, re-raised by `run`
            self.cancelled = True
            _log().warning(f"{self.spec.name}.trail_close_cancelled", run_id=str(self.run_id))
        except Exception as exc:
            error = type(exc).__name__
            _log().critical(
                f"{self.spec.name}.trail_close_failed", run_id=str(self.run_id), error=error
            )
        return None

    async def _emit(
        self, action: str, outcome: AuditOutcome, reason: str | None, state: _State
    ) -> None:
        async with asyncio.timeout(STEP_TIMEOUT_S):
            await self.trail.emit(
                action,
                actor_label=self.spec.actor,
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


def _audit_lines(landed: int, pending: int | None, trail: str = "the journal") -> list[str]:
    """Where the run's two records are, never more than was written (C-2.9): `landed` of them
    reached `trail`; `pending` is what its close left outside `audit_log` (None: it did not
    close cleanly)."""
    if not landed:  # not even the attempt record
        return [_PRE_AUDIT]
    lines = [] if landed > 1 else [_UNRECORDED]
    if pending is None:
        lines.append(f"Audit: {trail} did not close cleanly.")
    elif pending:
        waiting = f"records waiting in the host journal: {pending}; cv-api folds them in."
        lines.append(f"Audit: {waiting}")
    elif landed > 1:
        lines.append(_AUDITED)
    return lines


#: What a flow acts on (break-glass: the Owner's id). A `TypeVar`, not a PEP 695 parameter:
#: Semgrep's `cv-admin-mutation-audited` must keep reading this module (X03-F4, DC-4479-18).
_Target = TypeVar("_Target")


class HostGatedFlow(ABC, Generic[_Target]):  # noqa: UP046 - Semgrep, X03-F4 (DC-4479-18)
    """The host gate of an offline CLI: one run per `_run()`, in the module's fixed order, with
    the flow's steps as hooks: `_target` after the probe, `_warning` above the phrase, `_act` once
    every check held, `_outcome` atop the summary. The gate's own methods are final (mypy rejects
    an override), so a flow cannot reorder or drop a check. `spec` names its records, actor, log
    events, task names, phrase verb and statuses; `environment` is the configured one (arch P9),
    the one source of `live`, which `--live` only has to confirm."""

    def __init__(self, ports: GatePorts, spec: GateSpec, environment: Environment) -> None:
        self._ports, self._environment, self._spec, self._x = ports, environment, spec, spec.exits
        self._live = self._environment is Environment.LIVE

    @final
    async def _run(self, owner: str, *, live_flag: bool) -> IntEnum:
        """One run on `owner` (as typed); `live_flag` is `--live`. Returns the exit status; no
        secret reaches the terminal or the log. A cancel is recorded and summarised first, then
        re-raised as `RunCancelled` with the status."""
        run_id = self._ports.new_run_id()
        try:
            async with asyncio.timeout(STEP_TIMEOUT_S):
                trail = await self._ports.open_journal()
        except asyncio.CancelledError:  # Ctrl-C while it opened: refused like any other run
            cancel = self._x["OPERATOR_CANCELLED"]
            return await self._refuse_unjournaled(run_id, owner, live_flag, cancel, cancelled=True)
        except Exception as exc:  # unusable, whatever the cause; a held run lock means cv-api
            held = isinstance(exc, BreakGlassUnavailable) and exc.reason == "api_running"
            error = type(exc).__name__
            _log().error(f"{self._spec.name}.journal_unavailable", run_id=str(run_id), error=error)
            status = self._x["API_RUNNING"] if held else self._x["HOST_FS_UNAVAILABLE"]
            return await self._refuse_unjournaled(run_id, owner, live_flag, status)
        records = _Records(self._spec, trail, run_id, owner, self._environment)
        try:
            verdict = await self._journaled(records, owner, live_flag)
        finally:
            pending = await records.close()
        self._summarise(verdict, owner, _audit_lines(records.landed, pending), records.cancelled)
        if records.cancelled:  # honoured now that the trail is closed and the summary shown
            raise RunCancelled(verdict.exit)
        return verdict.exit

    @final
    def _intent(self, live_flag: bool) -> dict[str, Any]:
        return {"environment": self._environment.value, "live_flag": live_flag}

    @final
    async def _journaled(self, records: _Records, owner: str, live_flag: bool) -> _Verdict:
        run_id, spec = str(records.run_id), self._spec
        try:
            await records.write(spec.attempt, AuditOutcome.SUCCESS, None, self._intent(live_flag))
        except Exception as exc:  # not durable: refuse before any check (C-2.9)
            error = type(exc).__name__
            _log().critical(f"{spec.name}.attempt_unrecorded", run_id=run_id, error=error)
            return _Verdict(self._x["AUDIT_UNAVAILABLE"])
        verdict = _Verdict(self._x["OPERATOR_CANCELLED"])  # cancelled during the attempt record
        if not records.cancelled:
            try:
                verdict = await self._decide(records, owner, live_flag)
            except asyncio.CancelledError:  # before the act began: a recorded refusal
                records.cancelled = True
        if records.cancelled:
            _log().warning(
                f"{spec.name}.run_cancelled", run_id=run_id, reason=verdict.status.name.lower()
            )
        action, outcome, reason = spec.record_of(verdict)
        try:
            await records.write(action, outcome, reason, verdict.details)
        except Exception as exc:
            error = type(exc).__name__
            _log().critical(
                f"{spec.name}.outcome_unrecorded", run_id=run_id, reason=reason, error=error
            )
            return dataclasses.replace(verdict, unrecorded=True)
        _log().warning(f"{spec.name}.run_ended", run_id=run_id, reason=reason)
        return verdict

    @final
    async def _decide(self, records: _Records, owner: str, live_flag: bool) -> _Verdict:
        try:
            checked = await self._check(records, owner, live_flag)
            if isinstance(checked, _Verdict):
                return self._own(checked, acted=False)
            return self._own(await self._act(records, checked), acted=True)
        except _StepFailed as exc:
            step, error = exc.step, exc.error
        except Exception as exc:  # a port or a hook broke its contract: still recorded (C-2.9)
            step, error = "flow", type(exc).__name__
        _log().error(
            f"{self._spec.name}.step_failed", run_id=str(records.run_id), step=step, error=error
        )
        return _Verdict(self._x["STEP_FAILED"], {"step": step, "error": error})

    @final
    def _own(self, verdict: _Verdict, *, acted: bool) -> _Verdict:
        """A hook's verdict if it keeps to the gate, else an error `_decide` records as
        STEP_FAILED: a status of the spec's own exit status, and its done or failed status only
        from the act (from a check, it would skip the TTY, the phrase and the act)."""
        if type(verdict.status) is not self._x:
            raise TypeError(f"a {type(verdict.status).__name__} status, not a {self._x.__name__}")
        if not acted and verdict.status.name in {self._spec.done_status, self._spec.failed_status}:
            raise RuntimeError(f"a check cannot end a run as {verdict.status.name}")
        return verdict

    @final
    async def _step[T](self, step: str, call: Callable[[], Awaitable[T]]) -> T:
        try:
            async with asyncio.timeout(STEP_TIMEOUT_S):
                return await call()
        except Exception as exc:
            raise _StepFailed(step, type(exc).__name__) from None

    @final
    async def _check(self, records: _Records, owner: str, live_flag: bool) -> _Verdict | _Target:
        """The preconditions after the attempt record, in order; the target if all hold."""
        if live_flag != self._live:  # --live confirms the configured environment, never sets it
            return _Verdict(self._x["LIVE_FLAG_REQUIRED" if self._live else "LIVE_FLAG_MISMATCH"])
        proof = await self._step("kek_proof", self._ports.prove_kek)
        if not proof.kcv_ok:
            code = proof.reason if _REASON_CODE.fullmatch(proof.reason or "") else None
            return _Verdict(self._x["KEK_UNPROVEN"], {"proof": code or "kek_unavailable"})
        if await self._step("api_probe", self._ports.api_running):
            return _Verdict(self._x["API_RUNNING"])
        target = await self._target(records, owner)
        if isinstance(target, _Verdict):
            return target
        refused = await self._confirm(owner)
        return target if refused is None else refused

    @final
    async def _confirm(self, owner: str) -> _Verdict | None:
        terminal = self._ports.terminal
        if not terminal.is_interactive():
            return _Verdict(self._x["NO_TTY"])
        phrase = confirmation_phrase(owner, self._environment, new_phrase_nonce(), self._spec.verb)
        terminal.write(self._warning(owner))
        terminal.write(f"To confirm, type: {phrase}")
        try:
            async with asyncio.timeout(PROMPT_TIMEOUT_S):
                typed = await terminal.ask("> ")
        except TimeoutError:
            return _Verdict(self._x["CONFIRMATION_TIMEOUT"])
        except EOFError:
            typed = ""
        return None if typed.strip() == phrase else _Verdict(self._x["CONFIRMATION_MISMATCH"])

    @final
    async def _probe_again(self) -> _Verdict | None:
        """cv-api probed again, last, right before the act: one may have connected during the
        prompts (R2c). Every `_act` calls it before it changes anything; API_RUNNING if one did."""
        if await self._step("api_probe", self._ports.api_running):
            return _Verdict(self._x["API_RUNNING"])
        return None

    @abstractmethod
    async def _target(self, records: _Records, ident: str) -> _Verdict | _Target:
        """The flow's target once the probe passed, or a refusal (of its exit status) that ends
        the run; it sets `records.target` once the target is known, and `ident`, the identifier
        as typed, is echoed only after that."""

    @abstractmethod
    def _warning(self, ident: str) -> str:
        """The line shown above the phrase: what the act will do, to whom, where."""

    @abstractmethod
    async def _act(self, records: _Records, target: _Target) -> _Verdict:
        """The act once every check held, and the closing verdict. After any prompt of its own,
        it calls `_probe_again` right before its change and returns its refusal if it gives one;
        it runs the change with `records.to_the_end` so that no cancel leaves the outcome
        unknown. The gate cannot see inside `_act`: the flow's own tests pin that probe by trace
        (cv-api up at the second probe, and that probe breaking, each end the run unacted)."""

    @abstractmethod
    def _outcome(self, verdict: _Verdict, ident: str, why: str) -> list[str]:
        """The summary's first lines for `verdict`; `why` is its reason with any detail. They
        echo `ident` only for the done status: on any refusal the identifier may not have named
        a real target, and it may be a pasted secret (C-12.6; `_label`)."""

    @final
    async def _refuse_unjournaled(
        self,
        run_id: uuid.UUID,
        owner: str,
        live_flag: bool,
        status: IntEnum,
        cancelled: bool = False,
    ) -> IntEnum:
        """No journal (scenario S3, cv-api holds the run lock, or a cancel while it opened):
        nothing else runs. The attempt and the refusal go straight to `audit_log` if it can be
        reached; the summary says which of them got there."""
        landed, pending = 0, None
        try:
            async with asyncio.timeout(STEP_TIMEOUT_S):
                trail = await self._ports.open_direct()
            if trail is not None:
                records = _Records(self._spec, trail, run_id, owner, self._environment)
                try:
                    await records.write(
                        self._spec.attempt, AuditOutcome.SUCCESS, None, self._intent(live_flag)
                    )
                    await records.write(
                        self._spec.refused, AuditOutcome.DENIED, status.name.lower(), None
                    )
                finally:
                    pending = await records.close()
                    landed, cancelled = records.landed, cancelled or records.cancelled
        except asyncio.CancelledError:  # while `audit_log` was being reached: nothing written
            cancelled = True
        except Exception as exc:
            error = type(exc).__name__
            _log().error(f"{self._spec.name}.direct_audit_failed", run_id=str(run_id), error=error)
        recorded = landed > 1 and pending == 0
        log = _log().warning if recorded else _log().critical
        log(
            f"{self._spec.name}.refused_unjournaled",
            run_id=str(run_id),
            reason=status.name.lower(),
            ok=recorded,
        )
        # Straight to `audit_log`: a count its close left outside it is not a journal's to fold.
        audit = _audit_lines(landed, 0 if pending == 0 else None, "the audit_log writer")
        self._summarise(_Verdict(status), owner, audit, cancelled)
        if cancelled:  # honoured once what reached `audit_log` is summarised
            raise RunCancelled(status)
        return status

    @final
    def _summarise(self, verdict: _Verdict, owner: str, audit: list[str], cancelled: bool) -> None:
        """The non-secret summary: the outcome, reason codes and where the records are."""
        write, details = self._ports.terminal.write, verdict.details or {}
        more = details.get("proof") or details.get("step") or details.get("error")
        why = f"{verdict.status.name.lower()}: {more}" if more else verdict.status.name.lower()
        for line in self._outcome(verdict, owner, why):
            write(line)
        if cancelled and verdict.status is not self._x["OPERATOR_CANCELLED"]:
            # An act or a record under way ended first, or was cut short: the line above says so.
            write("Cancelled: the line above says how the run ended.")
        for line in audit:
            write(line)


#: The gate's types, for the flows that build on it.
Verdict = _Verdict
GateRecords = _Records


class BreakGlassFlow(HostGatedFlow[uuid.UUID]):
    """One break-glass run per `run()`. The environment is the reset service's, the configured
    one (arch P9): the one source of `live`, which `--live` only has to confirm."""

    _ports: BreakGlassPorts  # the gate's ports and break-glass's own: the Owner lookup, the reset

    def __init__(self, ports: BreakGlassPorts) -> None:
        super().__init__(ports, _BREAK_GLASS, ports.reset.environment)

    @audited(ATTEMPT, REFUSED, RESET)
    async def run(self, owner: str, *, live_flag: bool) -> BreakGlassExit:
        """Reset the MFA of the Owner named `owner` (username or email); `live_flag` is
        `--live`. Returns the exit status; no secret reaches the terminal or the log. A cancel
        is recorded and summarised first, then re-raised as `RunCancelled` with the status."""
        return _X(await self._run(owner, live_flag=live_flag))

    async def _target(self, records: _Records, owner: str) -> _Verdict | uuid.UUID:
        target = await self._step("owner_lookup", lambda: self._ports.resolve_owner(owner))
        if target is None:  # the identifier is echoed (in the phrase) only once it names an Owner
            return _Verdict(_X.NOT_OWNER)
        records.target = target
        return target

    def _warning(self, owner: str) -> str:
        env = self._environment.value
        return f"Break-glass revokes every MFA method and session of {owner} on {env}."

    async def _act(self, records: _Records, target: uuid.UUID) -> _Verdict:
        return await self._reset(records, target)

    async def _reset(self, records: _Records, target: uuid.UUID) -> _Verdict:
        code = None
        if self._live:  # one Owner recovery code, echo off; none at all is refused by the service
            try:
                async with asyncio.timeout(PROMPT_TIMEOUT_S):
                    code = await self._ports.terminal.ask_secret("Owner recovery code (hidden): ")
            except (TimeoutError, EOFError):
                code = None
        try:  # probed again, last: a cv-api may have connected during the prompts (R2c)
            refused = await self._probe_again()
        except BaseException:
            del code  # no frame of a probe failure or a cancel keeps the plaintext code
            raise
        if refused is not None:
            return refused
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

    def _outcome(self, verdict: _Verdict, owner: str, why: str) -> list[str]:
        details = verdict.details or {}
        if verdict.status is _X.RESET:
            return [
                f"Break-glass reset done for {owner} on {self._environment.value}: "
                f"{details['methods_revoked']} MFA methods and {details['sessions_revoked']} "
                f"sessions revoked, system event {details['system_event_id']} raised. The Owner "
                "enrols TOTP again at the next sign-in."
            ]
        if verdict.status is _X.RESET_FAILED:  # a link lost at COMMIT may still have applied it
            return [
                f"Break-glass reset failed ({why}); no change is confirmed. Before re-running, "
                "check for an unresolved break_glass_used system event: if there is one, the "
                "reset applied."
            ]
        return [f"Break-glass ended without a reset ({why}); nothing was changed."]
