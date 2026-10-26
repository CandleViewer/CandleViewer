"""`RecorderRuntime`: the recorder under the supervisor (#2188 S4a; 20-architecture.md §3, §6.2).

`start()` spawns the one tracked task and returns at once (`recorder` starts before `oms`, §6.2:
nothing here is awaited inside `start_all`). The task starts the writer (its WAL replay runs
inline), then `startup_reconcile`; a failure retries with capped, jittered backoff, and the
warm-up gate stays closed until a startup completes. Then the 1 s tick, `policy.tick()` and
`sessions.poll_writer()`: an error is logged and the loop goes on. `stop()` cancels the task, then
stops the writer (it needs the live sessions to attach its gaps), the sessions and the policy.
The bounds, the clock, `sleep` and `rng` are injected: no default hides a production choice.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

import structlog

from candleviewer.observability import spawn
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.recorder.control import HIDDEN_CAUSES
from candleviewer.recorder.policy import RecordingPolicy
from candleviewer.recorder.sessions import PositionSeed, SessionManager, startup_reconcile
from candleviewer.recorder.writer import RecorderWalVolumeError, StreamWriter

MODULE: Final = "recorder"
TICK_S: Final = 1.0  # the policy's evaluation tick (20 §3.8)
_Step = tuple[str, Callable[[], Awaitable[None]]]


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


@dataclass(frozen=True, slots=True)
class RuntimeBounds:
    """Every bound is required: the composition root chooses them. One that would make a loop hot,
    a timeout instant or unbounded, or the alert unreachable is refused, naming its field."""

    start_timeout_s: float  # the writer's start, its inline WAL replay included
    startup_timeout_s: float  # the whole of one `startup_reconcile`: a hung seed or restore
    tick_timeout_s: float  # one step of a tick
    retry_base_s: float  # the first wait between startups; it doubles up to `retry_cap_s`
    retry_cap_s: float
    max_attempts: int  # failed startups after which health is degraded (the retries go on)
    gate_closed_alert_s: float  # N: the gate closed longer than this is degraded health

    def __post_init__(self) -> None:
        for name in ("start_timeout_s", "startup_timeout_s", "tick_timeout_s", "retry_base_s",
                     "retry_cap_s", "gate_closed_alert_s"):  # fmt: skip
            if not 0 < getattr(self, name) < math.inf:
                raise ValueError(f"{name} must be positive and finite")
        if self.retry_cap_s < self.retry_base_s:
            raise ValueError("retry_cap_s must not be below retry_base_s")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")


class RecorderRuntime:
    def __init__(
        self,
        *,
        policy: RecordingPolicy,
        sessions: SessionManager,
        writer: StreamWriter,
        restore_b11: Callable[[], Awaitable[None]],
        seed: PositionSeed,
        process_start_us: int,
        env: str,
        clock: Callable[[], float],
        sleep: Callable[[float], Awaitable[None]],
        rng: Callable[[], float],
        bounds: RuntimeBounds,
        on_ready: Callable[[], Awaitable[None]] | None = None,
        heal: Callable[[], Awaitable[None]] | None = None,
        anchors: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """`clock` is monotonic seconds, `rng` a uniform draw in [0, 1) (the backoff's jitter).
        `on_ready` runs once, after the startup and before `startup_complete` turns true: it opens
        what a restored chart never published (S3a finding 1). It is isolated: a raise is logged and
        health degrades. `heal` is a tick step after the policy's: it reopens what a failed fan-out
        left without a session (SEC-B1), bounded like every step. `anchors` is the last step: the
        periodic book seek anchors (#2223), which keep their own cadence on `clock`."""
        self._on_ready, self._heal, self._anchors = on_ready, heal, anchors
        self._on_ready_error: type[Exception] | None = None
        self._policy, self._sessions, self._writer = policy, sessions, writer
        self._restore_b11, self._seed, self._env = restore_b11, seed, env
        self._start_us, self._bounds = process_start_us, bounds
        self._clock, self._sleep, self._rng = clock, sleep, rng
        self._task: asyncio.Task[None] | None = None
        self._t0 = 0.0
        self._writer_up = False  # started once: a retried startup never starts it again
        self._done = False
        self._attempts = 0  # failed startups
        self._last_error: type[Exception] | None = None
        self._source_deployed = True  # False: the seed answered `None` (no positions source)

    async def start(self) -> None:
        if self._task is None:
            self._t0 = self._clock()
            self._task = spawn(self._run(), name="recorder-runtime")

    async def stop(self, grace_s: float) -> None:
        """Cancel the task, then stop the writer, the sessions and the policy, each within a
        quarter of `grace_s` (so the four fit the bound the supervisor puts on `stop`), each run
        whatever the one before did. `wait`, not `await task`: the task's cancellation is not
        ours. The writer's own flush bound is half its share, so its spill path runs before the
        cut. A cancellation that reaches this stop is held until the last step has run, then
        re-raised, as `Supervisor._stop_each` does (#3361): the sessions still close."""
        share = grace_s / 4
        held: BaseException | None = None
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                _, pending = await asyncio.wait({task}, timeout=share)
            except BaseException as exc:  # this stop was cut while it waited
                held = exc
            else:
                if pending:  # it ignores its cancel: nothing else here would say so
                    logger().error("recorder_stop_failed", step="task", error="TimeoutError")
        steps: tuple[_Step, ...] = (
            ("writer", lambda: self._writer.stop(share / 2)),
            ("sessions", self._sessions.stop),
            ("policy", self._policy.stop),
        )
        for step, call in steps:
            try:
                async with asyncio.timeout(share):
                    await call()
            except BaseException as exc:  # a failing, hung or cut step never skips the next
                if held is None and not isinstance(exc, Exception):
                    held = exc
                logger().error("recorder_stop_failed", step=step, error=type(exc).__name__)
                if step == "writer":
                    self._log_unpersisted_gaps()
        if held is not None:
            raise held

    def _log_unpersisted_gaps(self) -> None:
        """The writer was cut before it could save its gap windows (a stalled store), the only
        evidence of a hole in the recording (C-2.14): log each as its own stop would. No I/O."""
        for (symbol, stream), windows in self._writer.pending_gaps().items():
            for first, last in windows:
                logger().critical(
                    "recorder_gap_unpersisted", symbol=symbol, stream=stream, start=first, end=last
                )

    @property
    def startup_complete(self) -> bool:
        """True once `startup_reconcile` has returned and the gate is open. Until then the policy
        holds none of the rows: a user remove or unpin would be a silent no-op and an add would
        rewrite its row, so the control surface refuses them (SEC-4, #2188; wired in S4b)."""
        return self._done

    def recorded_symbols(self) -> frozenset[str]:
        """The policy's effective set (a lingering symbol is still recorded), less a symbol
        recorded for a hidden cause alone (`control.HIDDEN_CAUSES`, R-I2): `/rules/vocabulary`
        would reveal an open position (SEC-A2). A lingering entry holds none: its last decides."""
        return frozenset(
            symbol
            for symbol, entry in self._policy.effective_set().items()
            if not frozenset(entry.reasons or (entry.reason,)) <= HIDDEN_CAUSES
        )

    def health(self) -> HealthReport:
        """`stopped` before `start()` and after `stop()`, else the startup's state in `detail`
        (error classes only, never a message: `/readyz` is anonymous). Degraded: past
        `max_attempts`, a WAL volume refusal (SR-096), the gate closed longer than N, or the task
        ended. A positions source that is not deployed is shown with its env, not degraded: it is
        the accepted risk until E29-T06 provides one."""
        task, b, err, failed = self._task, self._bounds, self._last_error, self._attempts
        ready_err = self._on_ready_error
        if task is None:
            return HealthReport(module=MODULE, status=HealthStatus.STOPPED)
        state = "pending" if not failed else "degraded" if failed >= b.max_attempts else "retrying"
        overdue = not self._done and self._clock() - self._t0 > b.gate_closed_alert_s
        no_source = self._done and not self._source_deployed
        facts = [
            "startup=done" if self._done else f"startup={state}",
            f"attempts={failed} last_error={err.__name__}" if err else "",
            f"positions_source=not_deployed env={self._env}" if no_source else "",
            f"gate_closed_over={b.gate_closed_alert_s:g}s" if overdue else "",
            f"on_ready_failed error={ready_err.__name__}" if ready_err else "",
            "task_ended" if task.done() else "",
        ]
        stuck = err is not None and (state == "degraded" or err is RecorderWalVolumeError)
        bad = stuck or overdue or task.done() or ready_err is not None
        status = HealthStatus.DEGRADED if bad else HealthStatus.OK
        return HealthReport(module=MODULE, status=status, detail=" ".join(f for f in facts if f))

    async def _run(self) -> None:
        delay = min(self._bounds.retry_base_s, self._bounds.retry_cap_s)
        while not await self._attempt():
            await self._sleep(delay * (0.5 + self._rng() / 2))  # equal jitter
            delay = min(delay * 2, self._bounds.retry_cap_s)
        while True:
            await self._tick()
            await self._sleep(TICK_S)

    async def _attempt(self) -> bool:
        """One startup: the writer (once), then `startup_reconcile`, which opens the gate last."""
        b = self._bounds
        try:
            if not self._writer_up:
                async with asyncio.timeout(b.start_timeout_s):
                    await self._writer.start()
                self._writer_up = True
            async with asyncio.timeout(b.startup_timeout_s):
                positions = await startup_reconcile(
                    self._sessions,
                    self._policy,
                    process_start_us=self._start_us,
                    restore_b11=self._restore_b11,
                    seed=self._seed,
                )
        except Exception as exc:  # the gate stays closed; a CancelledError is not one
            self._attempts, self._last_error = self._attempts + 1, type(exc)
            if isinstance(exc, RecorderWalVolumeError):  # nothing may record on this volume
                log = logger().critical
            elif self._attempts >= b.max_attempts:  # health is degraded now: say so
                log = logger().error
            else:
                log = logger().warning
            log(
                "recorder_startup_failed",
                attempt=self._attempts,
                error=type(exc).__name__,
                gate_closed_s=int(self._clock() - self._t0),
            )
            return False
        if self._on_ready is not None:
            try:
                async with asyncio.timeout(b.startup_timeout_s):
                    await self._on_ready()
            except Exception as exc:  # the startup is over (the gate is open): it is not retried
                self._on_ready_error = type(exc)
                logger().error("recorder_on_ready_failed", error=type(exc).__name__)
        self._done, self._last_error, self._source_deployed = True, None, positions is not None
        logger().info("recorder_startup_done", env=self._env, failed_attempts=self._attempts)
        return True

    async def _tick(self) -> None:
        steps: tuple[_Step, ...] = (
            ("policy", self._policy.tick),
            ("sessions", lambda: self._sessions.poll_writer(self._writer)),
        )
        if self._heal is not None:
            steps = (*steps, ("heal", self._heal))
        if self._anchors is not None:
            steps = (*steps, ("anchors", self._anchors))
        for step, call in steps:  # each isolated: a failing one never skips the other
            try:
                async with asyncio.timeout(self._bounds.tick_timeout_s):
                    await call()
            except Exception as exc:  # the loop outlives a failed step
                logger().error("recorder_tick_failed", step=step, error=type(exc).__name__)
