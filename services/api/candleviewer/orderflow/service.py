"""Lifecycle contract for the orderflow module (M9).

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
    from candleviewer.orderflow.funding import FundingService
    from candleviewer.orderflow.open_interest import OpenInterestService


class OrderflowService:
    """Empty scaffold for the M9 `orderflow` module lifecycle."""

    def __init__(self) -> None:
        self._started = False
        #: E24-T02: attached by the composition root once storage/ingestion exist.
        self.funding: FundingService | None = None
        #: E24-T01: attached by the composition root (`oi_wiring`).
        self.open_interest: OpenInterestService | None = None

    def attach_funding(self, service: FundingService) -> None:
        self.funding = service

    def attach_open_interest(self, service: OpenInterestService) -> None:
        self.open_interest = service

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
