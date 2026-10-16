"""Operator-facing reporting of TOTP clock skew (E09-Q05 gap #2146).

`verify_code` refuses any code beyond +/-1 step (SR-021), so a user whose authenticator clock is
further off is refused like one who mistyped, and nobody can tell why. After a refusal,
`TotpSkewReporter.report_rejection` asks whether the code fits a step a little further out
(`totp.detect_skew`; a replay of an accepted step is not skew) and, if so, holds one report.

It only observes: it never accepts a code and never changes the user's answer (a skew-specific one
would be an oracle, PR #1618 review finding 4). The report is no oracle either. `/metrics` is
served unauthenticated, so a counter that moved at once would tell whoever holds a user's password
that a refused guess is the right code for a step up to 5 minutes ahead, which is still acceptable.
So `report_rejection` awaits nothing and does no I/O (a sink write cannot show in the refusal's
timing, stall it or cost it the attempt), and a task owned by `AuthService` publishes the counter
and one `system_events` row only after `SKEW_HOLD_S`, when the matched code is dead. The event holds
no user id, code or seed; find the request by `refused_at` and the source address.

The held list is bounded (C-2.18): beyond `MAX_HELD` the newest report is dropped and counted
(`auth.totp_clock_skew_dropped`), and `stop()` discards the rest. A failing or stalled sink is
logged by class and never raised.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any, Final

import structlog

from candleviewer.auth.metrics import auth_totp_clock_skew_total
from candleviewer.auth.totp import (
    TOTP_SKEW_DIAGNOSTIC_STEPS,
    TOTP_SKEW_STEPS,
    TOTP_STEP_SECONDS,
    detect_skew,
)
from candleviewer.observability.context import spawn
from candleviewer.observability.health_probes import SystemEvent, SystemEventWriter

#: A code for a step at most DIAGNOSTIC ahead stays acceptable until the server's step is SKEW past
#: it, and the refusal may fall on the last instant of its own step (the +1).
SKEW_HOLD_S: Final = (TOTP_SKEW_DIAGNOSTIC_STEPS + TOTP_SKEW_STEPS + 1) * TOTP_STEP_SECONDS
MAX_HELD: Final = 256
PUBLISH_TICK_S: Final = 15.0
EVENT_WRITE_TIMEOUT_S: Final = 1.0  # a stalled sink must not wedge the publisher


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class TotpSkewReporter:
    def __init__(
        self,
        events: SystemEventWriter | None = None,
        *,
        clock: Callable[[], float] = time.time,
        max_held: int = MAX_HELD,
        tick_s: float = PUBLISH_TICK_S,
        timeout_s: float = EVENT_WRITE_TIMEOUT_S,
    ) -> None:
        self._events = events
        self._clock = clock  # unix seconds: the clock the refusing services verify against
        self._max_held = max_held
        self._tick_s = tick_s
        self._timeout_s = timeout_s
        self._held: list[tuple[float, int]] = []  # (refused at, step offset)
        self._dropped = 0
        self._task: asyncio.Task[None] | None = None

    def report_rejection(
        self,
        methods: Iterable[tuple[bytes, int | None]],
        code: str,
        *,
        unix_time: float,
    ) -> None:
        """Call once every method has refused `code`, before the failure is recorded and raised.

        `methods` are the plaintext seeds the caller already decrypted, each with its method's last
        accepted step. Silent unless `code` fits a step beyond the accepted window and newer than
        that. Never awaits, does no I/O and never raises."""
        offsets = [detect_skew(seed, code, unix_time=unix_time, floor=f) for seed, f in methods]
        offset = next((o for o in offsets if o is not None), None)
        if offset is None:
            return
        if len(self._held) >= self._max_held:
            self._dropped += 1
            return
        self._held.append((unix_time, offset))

    async def publish_due(self, now: float) -> None:
        """Publish every held report whose hold has elapsed at `now` (unix seconds)."""
        if self._dropped:
            _log().warning("auth.totp_clock_skew_dropped", count=self._dropped)
            self._dropped = 0
        cutoff = now - SKEW_HOLD_S  # due: refused at or before this
        due = [held for held in self._held if held[0] <= cutoff]
        self._held = [held for held in self._held if held[0] > cutoff]
        for refused_at, offset in due:
            await self._publish(refused_at, offset)

    async def _publish(self, refused_at: float, offset: int) -> None:
        kind = "authenticator_behind" if offset < 0 else "authenticator_ahead"
        auth_totp_clock_skew_total.labels(kind=kind).inc()
        if self._events is None:
            return
        seconds, side = abs(offset) * TOTP_STEP_SECONDS, "behind" if offset < 0 else "ahead of"
        refused = datetime.fromtimestamp(refused_at, UTC).isoformat(timespec="seconds")
        event = SystemEvent(
            component="auth",
            kind="totp_clock_skew",
            severity="warning",
            message=(
                f"clock skew: the authenticator is {abs(offset)} steps ({seconds} s) {side} the "
                f"server clock; its code was refused at {refused} "
                f"(accepted: +/-{TOTP_SKEW_STEPS} step)"
            ),
            details={"kind": kind, "offset_steps": str(offset), "refused_at": refused},
        )
        try:
            async with asyncio.timeout(self._timeout_s):
                await self._events.write(event)
        except Exception as exc:  # telemetry must never wedge the publisher
            _log().error("auth.totp_clock_skew_event_failed", error=type(exc).__name__)

    def start(self) -> None:
        """Start the publisher task (idempotent); `AuthService` owns it."""
        if self._task is None:
            self._task = spawn(self._run(), name="totp-skew-publisher")

    async def stop(self) -> None:
        """Cancel the publisher, wait for it, and discard whatever is still held."""
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})  # unlike `await task`, an outer cancellation still raises
        self._held.clear()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._tick_s)
            await self.publish_due(self._clock())
