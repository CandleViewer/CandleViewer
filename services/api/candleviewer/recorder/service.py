"""Lifecycle contract for the recorder module (M11).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. This is an
empty scaffold — the supervisor (Sec.6.2) can construct and sequence this
module, but it does no real work until its owning epic lands.

Once `attach_runtime` (#2188) has given it a `RecorderRuntime`, the three delegate to it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from candleviewer.observability.health import HealthReport, HealthStatus

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.recorder.coverage import CoverageService
    from candleviewer.recorder.runtime import RecorderRuntime


class RecorderService:
    """The M11 `recorder` module lifecycle: a scaffold until a runtime is attached."""

    def __init__(self) -> None:
        self._started = False
        #: E16-T04 `CoverageService` (composed by `create_app` on the real backend).
        self.coverage: CoverageService | None = None
        self._runtime: RecorderRuntime | None = None

    def attach_coverage(self, service: CoverageService) -> None:
        self.coverage = service

    def attach_runtime(self, runtime: RecorderRuntime) -> None:
        self._runtime = runtime

    def recorded_symbols(self) -> frozenset[str]:
        """Symbols with an active recording: the policy's effective set (lingering ones included)
        once a runtime is attached, else empty."""
        return frozenset() if self._runtime is None else self._runtime.recorded_symbols()

    async def start(self, ctx: AppContext) -> None:
        """Start the module; the runtime's start returns at once, its startup is a task."""
        self._started = True
        if self._runtime is not None:
            await self._runtime.start()

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds."""
        self._started = False
        if self._runtime is not None:
            await self._runtime.stop(grace_s)

    def health(self) -> HealthReport:
        """The runtime's health; a scaffold reports `ok` once started."""
        if self._runtime is not None:
            return self._runtime.health()
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        return HealthReport(module="", status=status, detail="scaffold module — no real logic yet")
