"""Lifecycle contract for the replay module (M12).

Every module implements the lifecycle contract from
`docs/plan/20-architecture.md` Sec.3: `start`, `stop`, `health`. E26-T01: the composition root
attaches a `ReplaySessionService` (real storage backend only); `start` then revives the live
sessions and starts its mirror and idle-reclaim tasks, and `stop` persists or stops every chart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from candleviewer.observability.health import HealthReport, HealthStatus

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.replay.sessions_service import ReplaySessionService


class ReplayService:
    """The M12 `replay` module lifecycle."""

    def __init__(self) -> None:
        self._started = False
        self.sessions: ReplaySessionService | None = None

    def attach_sessions(self, sessions: ReplaySessionService) -> None:
        self.sessions = sessions

    async def start(self, ctx: AppContext) -> None:
        """Start the module (and the session service when one is attached)."""
        if self.sessions is not None:
            await self.sessions.start()
        self._started = True

    async def stop(self, grace_s: float) -> None:
        """Stop the module (the supervisor bounds this by `grace_s`)."""
        if self.sessions is not None:
            await self.sessions.stop()
        self._started = False

    def health(self) -> HealthReport:
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        detail = "replay sessions on" if self.sessions is not None else "replay sessions off"
        return HealthReport(module="", status=status, detail=detail)
