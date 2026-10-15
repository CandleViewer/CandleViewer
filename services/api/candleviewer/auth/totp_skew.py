"""Operator-facing reporting of TOTP clock skew (E09-Q05 gap #2146).

`verify_code` refuses any code beyond +/-1 step (SR-021), so a user whose authenticator clock is
further off is refused like one who mistyped, and nobody can tell why. After a refusal,
`TotpSkewReporter` asks whether the code fits a step a little further out (`totp.detect_skew`); if
so it counts it on `auth_totp_clock_skew_total` and writes one `system_events` row.

It only observes: it never accepts a code and never changes the user's answer (the router gives one
generic detail for every failure; a skew-specific one would be an oracle, PR #1618 review finding
4). Its sink cannot change the outcome either: the write is bounded, a failure is logged by class
and swallowed. The event holds no user id, code or seed; the log line carries the request id, which
joins it to the `auth.mfa_failed` audit row.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Any, Final, Literal

import structlog

from candleviewer.auth.metrics import auth_totp_clock_skew_total
from candleviewer.auth.totp import TOTP_SKEW_STEPS, TOTP_STEP_SECONDS, detect_skew
from candleviewer.observability.health_probes import SystemEvent, SystemEventWriter

SKEW_EVENT_KIND: Final = "totp_clock_skew"  # `system_events.kind`; the component is `auth`
#: `auth_totp_clock_skew_total{kind}` values and the event's `details["kind"]`.
KIND_AUTHENTICATOR_BEHIND: Final = "authenticator_behind"
KIND_AUTHENTICATOR_AHEAD: Final = "authenticator_ahead"
EVENT_WRITE_TIMEOUT_S: Final = 1.0  # the write sits on the failed-verification path

Surface = Literal["login", "enrolment", "step_up"]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class TotpSkewReporter:
    def __init__(
        self, events: SystemEventWriter | None = None, *, timeout_s: float = EVENT_WRITE_TIMEOUT_S
    ) -> None:
        self._events = events
        self._timeout_s = timeout_s

    async def report_rejection(
        self, seeds: Iterable[bytes], code: str, *, unix_time: float, surface: Surface
    ) -> None:
        """Call once every method has refused `code`, before the failure is recorded and raised.

        `seeds` are the plaintext seeds the caller already decrypted to verify; they are only
        read here. Silent unless `code` fits a step beyond the accepted window. Never raises
        (cancellation excepted)."""
        offsets = [detect_skew(seed, code, unix_time=unix_time) for seed in seeds]
        offset = next((o for o in offsets if o is not None), None)
        if offset is None:
            return
        kind = KIND_AUTHENTICATOR_BEHIND if offset < 0 else KIND_AUTHENTICATOR_AHEAD
        auth_totp_clock_skew_total.labels(kind=kind).inc()
        _log().warning("auth.totp_clock_skew", surface=surface, kind=kind, offset_steps=offset)
        if self._events is None:
            return
        seconds = abs(offset) * TOTP_STEP_SECONDS
        side = "behind" if offset < 0 else "ahead of"
        event = SystemEvent(
            component="auth",
            kind=SKEW_EVENT_KIND,
            severity="warning",
            message=(
                f"clock skew: the authenticator is {abs(offset)} steps ({seconds} s) {side} the "
                f"server clock; its code was refused (accepted: +/-{TOTP_SKEW_STEPS} step)"
            ),
            details={
                "surface": surface,
                "kind": kind,
                "offset_steps": str(offset),
                "offset_seconds": str(offset * TOTP_STEP_SECONDS),
            },
        )
        try:
            async with asyncio.timeout(self._timeout_s):
                await self._events.write(event)
        except Exception as exc:  # telemetry must never change an authentication outcome
            _log().error("auth.totp_clock_skew_event_failed", error=type(exc).__name__)
