"""Lifecycle contract for the recorder module (M11).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. This is an
empty scaffold — the supervisor (Sec.6.2) can construct and sequence this
module, but it does no real work until its owning epic lands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from candleviewer.observability.health import HealthReport, HealthStatus

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.recorder.coverage import CoverageService


class RecorderService:
    """Empty scaffold for the M11 `recorder` module lifecycle."""

    def __init__(self) -> None:
        self._started = False
        #: E16-T04 `CoverageService` (composed by `create_app` on the real backend).
        self.coverage: CoverageService | None = None

    def attach_coverage(self, service: CoverageService) -> None:
        self.coverage = service

    def recorded_symbols(self) -> frozenset[str]:
        """Symbols with an active recording. Empty until the recorder epic (E16) lands."""
        return frozenset()

    async def start(self, ctx: AppContext) -> None:
        """Start the module. No-op until the owning epic implements it."""
        self._started = True

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds. No-op scaffold."""
        self._started = False

    def health(self) -> HealthReport:
        """Report module health. Scaffold modules report `ok` when constructed."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        return HealthReport(module="", status=status, detail="scaffold module — no real logic yet")
