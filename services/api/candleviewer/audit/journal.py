"""Break-glass host journal and run lock (E09-S11 #2119, SR-023, E09 threat model Sec.3.6.1).

The offline CLI journals its records in `<dir of CV_AUDIT_WAL_PATH>/breakglass/journal.wal`
and flushes them to `audit_log` before it exits; what is left (Postgres was down) cv-api folds
in at boot. `instance.lock` keeps the two apart: cv-api holds it shared from `AuditService.start`
to `stop`, the CLI exclusively, and the CLI refuses an unanchored path (`anchored_journal_dir`).
"""

from __future__ import annotations

import contextlib
import fcntl
import os
from io import FileIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditEmission, AuditOutcome, Severity
from candleviewer.audit.wal import AuditWal

if TYPE_CHECKING:
    from candleviewer.audit.writer import AuditWriter

#: The CLI's records (#2119 decision R3); nothing else may come in through the journal.
BREAK_GLASS_ACTIONS = frozenset(a for a in AUDIT_ACTIONS if a.startswith("auth.break_glass_"))
ACTOR = "system:breakglass"
JOURNAL_FILE = "journal.wal"
LOCK_FILE = "instance.lock"


class HostFsUnavailable(AuditError):
    """The break-glass directory is not anchored or cannot be opened."""

    reason = "host_fs_unavailable"


class RunLockHeld(AuditError):
    """`instance.lock` is held in a conflicting mode by another process."""


def journal_dir(audit_wal_path: str) -> Path:
    """`<dir of audit_wal_path>/breakglass`, as cv-api resolves it (against its cwd)."""
    return Path(audit_wal_path).parent / "breakglass"


def anchored_journal_dir(audit_wal_path: str) -> Path:
    """`journal_dir` for the CLI: the WAL path must be absolute and free of `..`, and none of
    the audit dir, the break-glass dir, the journal or the lock may be a symlink."""
    raw = Path(audit_wal_path)
    if not raw.is_absolute() or ".." in raw.parts:
        raise HostFsUnavailable("CV_AUDIT_WAL_PATH must be absolute and free of '..'")
    directory = journal_dir(audit_wal_path)
    for path in (raw.parent, directory, directory / JOURNAL_FILE, directory / LOCK_FILE):
        if path.is_symlink():
            raise HostFsUnavailable(f"break-glass path {path.name!r} must not be a symlink")
    return directory


def hold_run_lock(directory: Path, *, exclusive: bool) -> FileIO:
    """Take `instance.lock` without waiting, shared for cv-api, exclusive for the CLI; closing
    the returned file drops it. `RunLockHeld` if another process holds it in a conflicting
    mode, `HostFsUnavailable` if it cannot be created or opened (never through a symlink)."""
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(directory / LOCK_FILE, os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise HostFsUnavailable(f"break-glass run lock unavailable: {type(exc).__name__}") from exc
    try:
        fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
    except BaseException as exc:
        os.close(fd)
        if isinstance(exc, BlockingIOError):
            raise RunLockHeld("the break-glass run lock is held by another process") from exc
        raise
    return FileIO(fd, "r")


async def fold_in(writer: AuditWriter, directory: Path) -> int:
    """Move the journal's pending records into the main audit WAL (boot-time, small: on the
    loop like the WAL's open; the caller holds the run lock); returns how many. A re-fold after
    a crash re-appends the same `record_id`s, which the insert ignores. An unusable journal
    stays as evidence and raises a critical event; a refused append keeps it. Neither blocks
    boot."""
    path = directory / JOURNAL_FILE
    if not path.exists() and not path.is_symlink():
        return 0
    try:
        journal, pending = _read_pending(path)
    except (AuditError, OSError, ValueError) as exc:  # AuditWalCorrupt, ValidationError, ...
        _log().critical("break-glass journal unusable; kept", error=type(exc).__name__)
        with contextlib.suppress(AuditError):  # the WAL refused it too: the log above stays
            await writer.emit(
                "auth.break_glass_refused",
                actor_label=ACTOR,
                object_kind="breakglass_journal",
                outcome=AuditOutcome.FAILURE,
                severity=Severity.CRITICAL,
                reason="journal_unusable",
                after_state={"error": type(exc).__name__},
            )
        return 0
    try:
        for _end, record in pending:
            await writer.ingest(record)
        if pending:
            journal.mark_committed(pending[-1][0])
            journal.compact()
    except (AuditError, OSError) as exc:
        _log().critical("break-glass journal not folded in; kept", error=type(exc).__name__)
        return 0
    return len(pending)


def _read_pending(path: Path) -> tuple[AuditWal, list[tuple[int, dict[str, Any]]]]:
    if path.is_symlink():  # AuditWal would truncate a "torn tail" of whatever it points at
        raise OSError("the break-glass journal is a symlink")
    journal = AuditWal(path)
    pending = list(journal.replay())
    for _end, record in pending:
        if AuditEmission.model_validate(record).action not in BREAK_GLASS_ACTIONS:
            raise ValueError("the break-glass journal holds a foreign record")
    return journal, pending


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)
