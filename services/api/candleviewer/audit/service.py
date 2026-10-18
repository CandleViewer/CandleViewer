"""Lifecycle contract for the audit module (M19).

Wires `AuditWriter` (the WAL-backed single-writer append path) and
`AuditQueryService` (read/verify/export) when an `AuditRepository` is
injected; without one (fake backend, CI/dev default) it stays the no-op
scaffold so `create_app()`/tests keep working without a database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from candleviewer.audit.journal import fold_in, hold_run_lock, journal_dir
from candleviewer.observability.health import HealthReport, HealthStatus

if TYPE_CHECKING:
    from io import FileIO

    from candleviewer.app import AppContext
    from candleviewer.audit.query import AuditQueryService
    from candleviewer.audit.repository import AuditRepository
    from candleviewer.audit.writer import AuditWriter


class AuditService:
    """M19 `audit` module lifecycle.

    `writer`/`query` are `None` until `start()` has wired a real backend;
    callers (the `admin.audit` router, other modules' `audit.emit` calls)
    must check `is_active` first — mirrors `StorageService`'s
    `StorageTierUnavailable` pattern but as a plain `None` check since audit
    being unwired is an expected, non-fatal state on the fake backend.
    """

    def __init__(self, repository: AuditRepository | None = None) -> None:
        self._started = False
        self._repository = repository
        self._writer: AuditWriter | None = None
        self._query: AuditQueryService | None = None
        #: E09-S11: the break-glass run lock, held shared while a real writer may run.
        self._run_lock: FileIO | None = None

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

    async def start(self, ctx: AppContext) -> None:
        """Start the module. Wires `AuditWriter`/`AuditQueryService` only when
        a concrete `AuditRepository` was injected by the composition root
        (M10's `SqlAlchemyAuditRepository` once the real relational backend
        is wired); otherwise stays the no-op scaffold. `audit` never imports
        a storage driver (ADR-0003 import-linter contract).

        E09-S11 (#2119): with a real backend it first takes the break-glass run lock shared,
        held until `stop()`, and refuses to boot (`RunLockHeld`) while the offline CLI holds
        it; once the writer runs it folds in the CLI's journaled records (`fold_in`)."""
        if self._writer is not None:
            # Two writers on one WAL file would truncate each other's in-flight frames.
            raise RuntimeError("AuditService.start(): a writer is already running; stop() first")
        if self._repository is not None:
            lock_dir = journal_dir(ctx.settings.audit_wal_path)
            self._run_lock = hold_run_lock(lock_dir, exclusive=False)
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

    async def stop(self, grace_s: float) -> None:
        """Stop the module within `grace_s` seconds. No-op scaffold."""
        if self._writer is not None:
            await self._writer.stop(grace_s)
            self._writer = None
        if self._query is not None:
            self._query.close()
        self._query = None
        self._started = False
        if self._run_lock is not None:  # after the writer: the CLI may run from here on
            self._run_lock.close()
            self._run_lock = None

    def health(self) -> HealthReport:
        """Report module health. Scaffold modules report `ok` when constructed."""
        status = HealthStatus.OK if self._started else HealthStatus.STOPPED
        detail = "" if self.is_active else "scaffold module — fake storage backend"
        return HealthReport(module="audit", status=status, detail=detail)
