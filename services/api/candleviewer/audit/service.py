"""Lifecycle contract for the audit module (M19).

Wires `AuditWriter` (the WAL-backed single-writer append path) and
`AuditQueryService` (read/verify/export) when an `AuditRepository` is
injected; without one (fake backend, CI/dev default) it stays the no-op
scaffold so `create_app()`/tests keep working without a database. With a lane key loader it
also runs the journal-first audit lane and its façade, `lane` (ADR-0037, #3009).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog

from candleviewer.audit.journal import fold_in, hold_run_lock, journal_dir
from candleviewer.audit.lane import (
    AuditLane,
    LaneFacade,
    LaneLockUnavailable,
    boot_lane,
    links_work,
    lock_lane,
)
from candleviewer.observability.context import run_in_thread
from candleviewer.observability.health import HealthReport, HealthStatus

if TYPE_CHECKING:
    from io import FileIO

    from candleviewer.app import AppContext
    from candleviewer.audit.query import AuditQueryService
    from candleviewer.audit.repository import AuditRepository
    from candleviewer.audit.writer import AuditWriter

#: The composition root's lane key loader (ADR-0037 decision 6): the current and the previous key,
#: or None while no real backend is wired. `start()` runs it once, off the loop.
LaneKeyLoader = Callable[[], tuple[bytes, bytes | None] | None]


def _flag_off() -> bool:
    return False


class AuditService:
    """M19 `audit` module lifecycle.

    `writer`/`query` are `None` until `start()` has wired a real backend;
    callers (the `admin.audit` router, other modules' `audit.emit` calls)
    must check `is_active` first — mirrors `StorageService`'s
    `StorageTierUnavailable` pattern but as a plain `None` check since audit
    being unwired is an expected, non-fatal state on the fake backend.
    """

    def __init__(
        self, repository: AuditRepository | None = None, *, lane_keys: LaneKeyLoader | None = None
    ) -> None:
        self._started = False
        self._repository = repository
        self._writer: AuditWriter | None = None
        self._query: AuditQueryService | None = None
        #: E09-S11: the break-glass run lock, held shared while a real writer may run.
        self._run_lock: FileIO | None = None
        #: ADR-0037: no lane without a key loader (unit tests) or a real backend.
        self._lane_keys = lane_keys
        self._journal_first: Callable[[], bool] = _flag_off
        self.lane_lock_failures = 0  # READY-21: a `lane.lock` that held the lane (S4a's metric)
        self.lane_link_failures = 0  # a failed hard-link probe that held the lane (S4a's metric)
        self._lane: AuditLane | None = None
        self._lane_lock: FileIO | None = None
        self._facade: LaneFacade | None = None

    @property
    def is_active(self) -> bool:
        return self._writer is not None

    @property
    def writer(self) -> AuditWriter:
        if self._writer is None:
            raise RuntimeError("AuditService.start() has not wired a real backend")
        return self._writer

    @property
    def query(self) -> AuditQueryService:
        if self._query is None:
            raise RuntimeError("AuditService.start() has not wired a real backend")
        return self._query

    @property
    def lane(self) -> LaneFacade:
        """The journal-first façade (ADR-0037 decisions 1 and 2), once a real backend runs."""
        if self._facade is None:
            raise RuntimeError("AuditService.start() has not wired a real backend")
        return self._facade

    def use_lane_flag(self, journal_first: Callable[[], bool]) -> None:
        """Decision 12: the composition root's cached read of `audit.lane_journal_first`, with no
        principal (`audit` may not import `admin`); unwired (unit tests), it reads off."""
        self._journal_first = journal_first

    async def start(self, ctx: AppContext) -> None:
        """Start the module. Wires `AuditWriter`/`AuditQueryService` only when
        a concrete `AuditRepository` was injected by the composition root
        (M10's `SqlAlchemyAuditRepository` once the real relational backend
        is wired); otherwise stays the no-op scaffold. `audit` never imports
        a storage driver (ADR-0003 import-linter contract).

        E09-S11 (#2119): with a real backend it first takes the break-glass run lock shared,
        held until `stop()`, and refuses to boot (`RunLockHeld`) while the offline CLI holds
        it; once the writer runs it folds in the CLI's journaled records (`fold_in`).

        ADR-0037 (#3009): it first runs the lane key loader off the loop; its refusals refuse boot,
        the environment form on every backend. With keys and a real backend it takes `lane.lock`
        before the writer, which an unanchored directory or another holder refuses (any other lock
        error holds the lane), and boots the lane after the fold-in (`boot_lane`); a volume that
        fails the hard-link probe holds it too."""
        if self._writer is not None:
            # Two writers on one WAL file would truncate each other's in-flight frames.
            raise RuntimeError("AuditService.start(): a writer is already running; stop() first")
        keys = None if self._lane_keys is None else await run_in_thread(self._lane_keys)
        if self._repository is not None:
            lock_dir = journal_dir(ctx.settings.audit_wal_path)
            self._run_lock = hold_run_lock(lock_dir, exclusive=False)
            if keys is not None:
                try:
                    self._lane_lock = lock_lane(ctx.settings.audit_wal_path)
                except LaneLockUnavailable:
                    self.lane_lock_failures += 1
                except BaseException:
                    self._run_lock.close()
                    self._run_lock = None
                    raise
            from candleviewer.audit.query import AuditQueryService
            from candleviewer.audit.writer import AuditWriter

            self._writer = AuditWriter(self._repository, ctx.settings.audit_wal_path)
            await self._writer.start()
            self._query = AuditQueryService(
                self._repository, structure_budget=ctx.settings.audit_page_structure_budget
            )
        self._started = True
        if self._writer is not None:
            await fold_in(self._writer, journal_dir(ctx.settings.audit_wal_path))
            if keys is not None:
                wal, held = ctx.settings.audit_wal_path, self._lane_lock is None
                if not held and not await run_in_thread(links_work, wal):
                    held, self.lane_link_failures = True, self.lane_link_failures + 1
                self._lane = await boot_lane(wal, keys, self._writer, held)
            self._facade = LaneFacade(self._writer, self._lane, lambda: self._journal_first())

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds: the lane first (its drain hands records to
        the writer), within half of it, then the writer with what is left, then the locks. A lane
        close that fails or overruns is logged critical and the writer stops all the same; what
        the lane did not confirm drains at the next boot. Each lock outlives what it guards
        (#2250): after the writer stopped, and `lane.lock` only after the lane closed too, so a
        step that failed leaves its lock to the process's exit."""
        loop, self._facade = asyncio.get_running_loop(), None
        deadline, closed = loop.time() + grace_s, await self._close_lane(grace_s / 2)
        try:
            if self._writer is not None:
                await self._writer.stop(max(deadline - loop.time(), 0.0))
                self._writer = None
        finally:
            if self._query is not None:
                self._query.close()
            self._query, self._started = None, False
            if self._writer is None:
                if closed and self._lane_lock is not None:  # a second cv-api may boot from here on
                    self._lane_lock.close()
                    self._lane_lock = None
                if self._run_lock is not None:  # the CLI may run from here on
                    self._run_lock.close()
                    self._run_lock = None

    async def _close_lane(self, bound_s: float) -> bool:
        """Close the lane within `bound_s`; False when that failed or overran, logged critical."""
        lane, self._lane = self._lane, None
        if lane is None:
            return True
        try:
            async with asyncio.timeout(bound_s):
                await lane.close()
        except Exception as exc:  # `TimeoutError` among them: the writer stops all the same
            _log().critical("audit lane close failed; the writer stops all the same",
                            error=type(exc).__name__)  # fmt: skip
            return False
        return True

    def health(self) -> HealthReport:
        """Report module health. Scaffold modules report `ok` when constructed."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        detail = "" if self.is_active else "scaffold module — fake storage backend"
        return HealthReport(module="audit", status=status, detail=detail)


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)
