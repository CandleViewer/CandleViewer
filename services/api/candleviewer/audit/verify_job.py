"""The start-up and nightly audit chain verify job, `cv-audit-verify` (#2111, E09-X04 R-5, with
#2466 folded in; `21-database-schema.md` section 3.10.1).

One supervised task. The ASGI lifespan starts it once the supervisor has started the audit
module, and stops it before the audit module stops: a run writes its records through the audit
writer.

- The start-up run is at least `STARTUP_DELAY_S` after start, so Prometheus has scraped
  `audit_chain_verification_failures_total` and `RUNS_COUNTER` at 0 before a run can move them
  (`increase()` misses a series whose first sample is already 1).
- Then one scheduled run a day at `audit_verify_nightly_hour_utc`:00 UTC. The loop is
  sequential: runs never overlap, and a run that overruns its slot queues no other (the next
  slot is the first one after the run). No wait is longer than `MAX_SLEEP_S`, so a wall-clock
  step or a host resume delays a run by at most that.
- A run waits for the verify slot (`VerifySlot.acquire`): it is never skipped, and an on-demand
  run is refused while it waits or runs. The slot goes back in a `finally`; a cancellation is
  re-raised, never swallowed.
- Each run walks the whole chain with the `audit_verify_nightly_deadline_s` deadline
  (`24-internal-schemas.md` section 15.4), which the runner enforces; one still going
  `RUN_GRACE_S` past it is cancelled (stopped, leaving only its `started` record).

The runner writes the run's records, the chain gauge and failure counter and the
`audit_chain_break` event (`verify_runner`). The job sets `LAST_OK_GAUGE` (its start, then the
end of each pass) and `RUNS_COUNTER` (each run end by result; a runner exception is `stopped`).
The page rule on no pass for 26 h is added by the next slice: it reads the gauge within one
process and the counter across restarts (`increase()` spans a reset). No runner wired: no job,
no run, and the lifespan logs `audit.verify_job_not_wired`. A loop that dies logs
`audit.verify_job_died`.

Detection only: what a break does to trading is the Owner's decision (#2904).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import structlog

from candleviewer.audit.verify_runner import (
    VerifyOutcome,
    VerifyOutcomeKind,
    VerifyRunner,
    VerifyRunRequest,
    VerifyTrigger,
)
from candleviewer.audit.verify_slot import VerifySlot
from candleviewer.observability.context import spawn
from candleviewer.observability.metrics import Metrics

#: Unix time of the last run that passed; the job's start until one does (no labels).
LAST_OK_GAUGE: Final = "cv_audit_verify_last_ok_timestamp_seconds"
#: Runs that ended, by `result` (a `VerifyOutcomeKind` value).
RUNS_COUNTER: Final = "cv_audit_verify_runs_total"
#: The start-up run waits at least this long after the job starts.
STARTUP_DELAY_S: Final = 300.0
#: The longest single wait before the wall clock is read again.
MAX_SLEEP_S: Final = 300.0
#: How long past its deadline a run may go on before the job cancels it.
RUN_GRACE_S: Final = 60.0


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def next_slot(after: datetime, hour_utc: int) -> datetime:
    """The first `hour_utc`:00 UTC strictly after `after`."""
    slot = after.astimezone(UTC).replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    return slot if slot > after else slot + timedelta(days=1)


class AuditVerifyJob:
    """Tracked, cancellable owner of the verify loop (C-2.18)."""

    def __init__(
        self,
        runner: VerifyRunner,
        slot: Callable[[], VerifySlot],
        metrics: Metrics,
        *,
        hour_utc: int,
        deadline_s: float,
        clock: Callable[[], datetime] = _utcnow,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        timeout: Callable[[float], AbstractAsyncContextManager[object]] = asyncio.timeout,
    ) -> None:
        if not 0 <= hour_utc <= 23:
            raise ValueError("hour_utc must be an hour of the day, 0 to 23")
        # Built once, so a bad deadline fails at wiring rather than at the first run.
        self._requests = {
            t: VerifyRunRequest(trigger=t, deadline_s=deadline_s) for t in VerifyTrigger
        }
        self._runner = runner
        self._slot = slot  # resolved per run: the audit module wires it in `start()`
        self._last_ok = metrics.get(LAST_OK_GAUGE).child()
        runs = metrics.get(RUNS_COUNTER)
        # Each result at 0 from the start, after a restart too, so `increase()` sees a first run.
        self._runs = {kind: runs.labels(kind.value) for kind in VerifyOutcomeKind}
        self._hour_utc = hour_utc
        self._backstop_s = deadline_s + RUN_GRACE_S
        self._clock = clock
        self._sleep = sleep
        self._timeout = timeout
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the loop (idempotent, so it never runs twice); the ASGI lifespan owns it."""
        if self._task is None:
            self._task = spawn(self.run_forever(), name="cv-audit-verify")

    async def stop(self) -> None:
        """Cancel the loop and wait for it; a run in flight gives the slot back."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()  # also on a loop that died: its error is not reported a second time
            await asyncio.wait({task})  # unlike `await task`, an outer cancellation still raises

    async def run_forever(self) -> None:
        """The start-up run, then one a day at the hour. Ends by cancellation or a logged error."""
        try:
            await self._loop()
        except Exception as exc:
            _log().error("audit.verify_job_died", error=type(exc).__name__)  # the class only
            raise

    async def _loop(self) -> None:
        self._last_ok.set(self._clock().timestamp())  # what the 26 h page counts from
        await self._sleep(STARTUP_DELAY_S)
        await self.run_once(VerifyTrigger.STARTUP)
        slot = next_slot(self._clock(), self._hour_utc)
        while True:
            while (left := (slot - self._clock()).total_seconds()) > 0:
                await self._sleep(min(left, MAX_SLEEP_S))
            await self.run_once(VerifyTrigger.SCHEDULED)
            # Never the slot just run, even if the wall clock stepped back during the run.
            slot = next_slot(max(self._clock(), slot), self._hour_utc)

    async def run_once(self, trigger: VerifyTrigger) -> VerifyOutcomeKind:
        """One run: wait for the slot, run, give the slot back. Returns how the run ended."""
        try:
            slot = self._slot()
        except Exception as exc:  # the audit module is not up: stopped, never a success
            return self._stopped(trigger, exc)
        await slot.acquire()
        try:
            async with self._timeout(self._backstop_s):  # past it: `TimeoutError`
                outcome = await self._runner.run(self._requests[trigger])
        except Exception as exc:  # a runner fault: stopped, never a success
            return self._stopped(trigger, exc)
        finally:
            slot.release()
        if outcome.outcome is VerifyOutcomeKind.OK:
            self._last_ok.set(outcome.ended_at.timestamp())
        self._runs[outcome.outcome].inc()
        self._report(trigger, outcome)
        return outcome.outcome

    def _stopped(self, trigger: VerifyTrigger, exc: Exception) -> VerifyOutcomeKind:
        self._runs[VerifyOutcomeKind.STOPPED].inc()
        fields = {"trigger": trigger.value, "outcome": "stopped", "error": type(exc).__name__}
        _log().error("audit.verify_job_run", **fields)  # the class only: no store details
        return VerifyOutcomeKind.STOPPED

    @staticmethod
    def _report(trigger: VerifyTrigger, outcome: VerifyOutcome) -> None:
        log = _log()
        emit = {VerifyOutcomeKind.OK: log.info, VerifyOutcomeKind.MISMATCH: log.error}.get(
            outcome.outcome, log.warning
        )
        emit(
            "audit.verify_job_run",
            trigger=trigger.value,
            outcome=outcome.outcome.value,
            entries_checked=outcome.entries_checked,
            first_bad_id=outcome.first_bad_id,
            stop_reason=None if outcome.stop_reason is None else outcome.stop_reason.value,
        )
