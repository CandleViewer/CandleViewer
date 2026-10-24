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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final

import structlog

from candleviewer.observability import spawn
from candleviewer.observability.health import HealthReport, HealthStatus
from candleviewer.recorder.policy import RecordingPolicy
from candleviewer.recorder.sessions import PositionSeed, SessionManager, startup_reconcile
from candleviewer.recorder.writer import StreamWriter

MODULE: Final = "recorder"
TICK_S: Final = 1.0  # the policy's evaluation tick (20 §3.8)
_Step = tuple[str, Callable[[], Awaitable[None]]]


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


@dataclass(frozen=True, slots=True)
class RuntimeBounds:
    """Every bound is required: the composition root chooses them."""

    start_timeout_s: float  # the writer's start, its inline WAL replay included
    startup_timeout_s: float  # the whole of one `startup_reconcile`: a hung seed or restore
    tick_timeout_s: float  # one step of a tick
    retry_base_s: float  # the first wait between startups; it doubles up to `retry_cap_s`
    retry_cap_s: float
    max_attempts: int  # failed startups after which health is degraded (the retries go on)


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
        clock: Callable[[], float],
        sleep: Callable[[float], Awaitable[None]],
        rng: Callable[[], float],
        bounds: RuntimeBounds,
    ) -> None:
        """`clock` is monotonic seconds, `rng` a uniform draw in [0, 1) (the backoff's jitter)."""
        self._policy, self._sessions, self._writer = policy, sessions, writer
        self._restore_b11, self._seed = restore_b11, seed
        self._start_us, self._bounds = process_start_us, bounds
        self._clock, self._sleep, self._rng = clock, sleep, rng
        self._task: asyncio.Task[None] | None = None
        self._t0 = 0.0
        self._writer_up = False  # started once: a retried startup never starts it again
        self._done = False
        self._attempts = 0  # failed startups
        self._last_error: type[Exception] | None = None

    async def start(self) -> None:
        if self._task is None:
            self._t0 = self._clock()
            self._task = spawn(self._run(), name="recorder-runtime")

    async def stop(self, grace_s: float) -> None:
        """Cancel the task, then stop the writer, the sessions and the policy, each within a
        quarter of `grace_s` (so the four fit the bound the supervisor puts on `stop`), each run
        whatever the one before did. `wait`, not `await task`: the task's cancellation is not
        ours. The writer's own flush bound is half its share, so its spill path runs before the
        cut."""
        share = grace_s / 4
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task}, timeout=share)
        steps: tuple[_Step, ...] = (
            ("writer", lambda: self._writer.stop(share / 2)),
            ("sessions", self._sessions.stop),
            ("policy", self._policy.stop),
        )
        for step, call in steps:
            try:
                async with asyncio.timeout(share):
                    await call()
            except Exception as exc:  # a failing or hung step never skips the next
                logger().error("recorder_stop_failed", step=step, error=type(exc).__name__)

    @property
    def startup_complete(self) -> bool:
        """True once `startup_reconcile` has returned and the gate is open. Until then the policy
        holds none of the rows: a user remove or unpin would be a silent no-op and an add would
        rewrite its row, so the control surface refuses them (SEC-4, #2188; wired in S4b)."""
        return self._done

    def health(self) -> HealthReport:
        """`stopped` before `start()` and after `stop()`, else the startup's state in `detail`
        (error classes only, never a message: `/readyz` is anonymous). Degraded: past
        `max_attempts`."""
        task, b, err, failed = self._task, self._bounds, self._last_error, self._attempts
        if task is None:
            return HealthReport(module=MODULE, status=HealthStatus.STOPPED)
        state = "pending" if not failed else "degraded" if failed >= b.max_attempts else "retrying"
        facts = ["startup=done" if self._done else f"startup={state}"]
        if err is not None:
            facts.append(f"attempts={failed} last_error={err.__name__}")
        degraded = err is not None and state == "degraded"
        status = HealthStatus.DEGRADED if degraded else HealthStatus.OK
        return HealthReport(module=MODULE, status=status, detail=" ".join(facts))

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
                await startup_reconcile(
                    self._sessions,
                    self._policy,
                    process_start_us=self._start_us,
                    restore_b11=self._restore_b11,
                    seed=self._seed,
                )
        except Exception as exc:  # the gate stays closed; a CancelledError is not one
            self._attempts, self._last_error = self._attempts + 1, type(exc)
            logger().warning(
                "recorder_startup_failed",
                attempt=self._attempts,
                error=type(exc).__name__,
                gate_closed_s=int(self._clock() - self._t0),
            )
            return False
        self._done, self._last_error = True, None
        logger().info("recorder_startup_done", failed_attempts=self._attempts)
        return True

    async def _tick(self) -> None:
        steps: tuple[_Step, ...] = (
            ("policy", self._policy.tick),
            ("sessions", lambda: self._sessions.poll_writer(self._writer)),
        )
        for step, call in steps:  # each isolated: a failing one never skips the other
            try:
                async with asyncio.timeout(self._bounds.tick_timeout_s):
                    await call()
            except Exception as exc:  # the loop outlives a failed step
                logger().error("recorder_tick_failed", step=step, error=type(exc).__name__)
