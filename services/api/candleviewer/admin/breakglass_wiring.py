"""The break-glass flow's ports, composed offline (E09-S11 #2119 slice 5, decision R5).

`candleviewer.breakglass`, the `python -m` entry point, imports neither `secrets` (C-3.2) nor
`audit` (C-3.3): it hands `build_break_glass_ports` the CLI's Postgres side (`BreakGlassStores`,
M10's `SqlAlchemyBreakGlassDatabase`, one pool) and its terminal, and gets the flow's ports. The
journal is an `AuditWriter` on `journal.wal` under the run lock, held exclusively until that writer
has stopped (R2a, R2b); its flusher moves the records into `audit_log` before the CLI exits, and
what Postgres did not take stays for cv-api's boot fold-in (R2d). The KEK proof is
`prove_kek_possession`, which never enrols (O1); the live recovery-code rule is the reset
service's (ADR-0009 Amendment 1; O3 kept). cv-api imports neither this module nor the flow (S8),
which is why this is not `admin.wiring`: the composition root imports that one.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from io import FileIO
from pathlib import Path
from typing import Any, Protocol

from candleviewer.admin.breakglass import AuditTrail, BreakGlassPorts, Terminal
from candleviewer.admin.errors import BreakGlassUnavailable
from candleviewer.audit.actions import UnknownAuditAction
from candleviewer.audit.errors import AuditError
from candleviewer.audit.journal import (
    BREAK_GLASS_ACTIONS,
    JOURNAL_FILE,
    HostFsUnavailable,
    RunLockHeld,
    anchored_journal_dir,
    hold_run_lock,
)
from candleviewer.audit.models import AuditEmission, storable
from candleviewer.audit.redact import redact
from candleviewer.audit.repository import AuditRepository
from candleviewer.audit.wal import AuditWal
from candleviewer.audit.writer import AuditWriter
from candleviewer.auth.break_glass import BreakGlassResetService, BreakGlassResetStore
from candleviewer.observability.context import run_in_thread
from candleviewer.secrets import KcvStore, KekCheckResult, prove_kek_possession
from candleviewer.settings import Settings


class BreakGlassOwners(BreakGlassResetStore, Protocol):
    async def find_active_owner(self, identifier: str) -> str | None:
        """The id of the one active Owner `identifier` (username or email) names, else None."""
        ...


class BreakGlassStores(Protocol):
    """The CLI's Postgres side, every store on one pool (`SqlAlchemyBreakGlassDatabase`)."""

    @property
    def audit_log(self) -> AuditRepository: ...
    @property
    def kcv(self) -> KcvStore: ...
    @property
    def owners(self) -> BreakGlassOwners: ...
    async def reachable(self) -> bool: ...
    async def others_connected(self) -> bool: ...


def build_break_glass_ports(
    settings: Settings, stores: BreakGlassStores, terminal: Terminal, *, recovery_code_key: bytes
) -> BreakGlassPorts:
    """The flow's ports over `stores`, `terminal` and the configured environment. No I/O."""

    async def open_journal() -> AuditTrail:
        return await _open_journal(settings.audit_wal_path, stores.audit_log)

    async def open_direct() -> AuditTrail | None:
        return _DirectTrail(stores.audit_log) if await stores.reachable() else None

    async def prove_kek() -> KekCheckResult:
        return await prove_kek_possession(settings, stores.kcv)

    async def resolve_owner(identifier: str) -> uuid.UUID | None:
        found = await stores.owners.find_active_owner(identifier)
        return None if found is None else uuid.UUID(found)

    reset = BreakGlassResetService(
        stores.owners, recovery_code_key=recovery_code_key, environment=settings.environment
    )
    return BreakGlassPorts(
        open_journal=open_journal,
        open_direct=open_direct,
        prove_kek=prove_kek,
        api_running=stores.others_connected,  # R2c: another session of the database role
        resolve_owner=resolve_owner,
        reset=reset,
        terminal=terminal,
    )


async def _open_journal(audit_wal_path: str, audit_log: AuditRepository) -> AuditTrail:
    """The host journal under the run lock, or `BreakGlassUnavailable`: `api_running` while
    cv-api (or another run) holds the lock, `host_fs_unavailable` for any other failure."""
    try:
        directory = anchored_journal_dir(audit_wal_path)
        lock = hold_run_lock(directory, exclusive=True)
    except RunLockHeld:
        raise BreakGlassUnavailable("api_running") from None
    except (HostFsUnavailable, OSError):
        raise BreakGlassUnavailable("host_fs_unavailable") from None
    journal = directory / JOURNAL_FILE
    try:
        writer = AuditWriter(audit_log, str(journal))
        await writer.start()
    except BaseException as exc:  # no writer runs: nothing for the lock to guard any more
        lock.close()
        if isinstance(exc, AuditError | OSError):  # an unwritable or a corrupt journal
            raise BreakGlassUnavailable("host_fs_unavailable") from None
        raise
    return _JournalTrail(writer, lock, journal)


def _admit(action: str) -> None:
    """Only the CLI's own records: the boot fold-in refuses a journal that holds any other."""
    if action not in BREAK_GLASS_ACTIONS:
        raise UnknownAuditAction(action)


class _JournalTrail:
    """`AuditTrail` over the host journal: durable in `journal.wal` once `emit` returns."""

    def __init__(self, writer: AuditWriter, lock: FileIO, journal: Path) -> None:
        self._writer, self._lock, self._journal = writer, lock, journal

    async def emit(self, action: str, **fields: Any) -> None:
        _admit(action)
        await self._writer.emit(action, **fields)

    async def close(self, grace_s: float) -> int:
        """Flush up to `grace_s`, stop, count what the journal still holds, unlock. The lock
        outlives the writer: a stop that fails or is cancelled leaves it to the process's exit,
        so cv-api never folds in a journal this run may still be writing."""
        await self._writer.stop(grace_s)
        pending = await run_in_thread(_pending_records, self._journal)
        self._lock.close()
        return pending


def _pending_records(journal: Path) -> int:
    return sum(1 for _ in AuditWal(journal).replay())


class _DirectTrail:
    """`AuditTrail` straight to `audit_log` when there is no journal (scenario S3): a record is
    built as `AuditWriter.build` builds one (registered action, redacted states, a new
    `record_id`, `event_ts` read once) and is committed before `emit` returns."""

    def __init__(self, audit_log: AuditRepository) -> None:
        self._audit_log = audit_log

    async def emit(self, action: str, **fields: Any) -> None:
        _admit(action)
        states = {key: redact(fields.get(key)) for key in ("before_state", "after_state")}
        emission = AuditEmission(
            record_id=uuid.uuid4(), action=action, event_ts=datetime.now(UTC), **(fields | states)
        )
        await self._audit_log.insert(storable(json.loads(emission.model_dump_json())))

    async def close(self, grace_s: float) -> int:
        del grace_s  # nothing is buffered: every record was committed by its `emit`
        return 0
