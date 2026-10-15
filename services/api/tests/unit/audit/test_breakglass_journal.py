"""Break-glass host journal and run lock (E09-S11 #2119 slice 1: plan scenarios S3, S4, S7).
No network; files only under `tmp_path`."""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from audit_fakes import FakeAuditRepository

from candleviewer.audit.journal import (
    HostFsUnavailable,
    RunLockHeld,
    anchored_journal_dir,
    fold_in,
    hold_run_lock,
    journal_dir,
)
from candleviewer.audit.service import AuditService
from candleviewer.audit.wal import AuditWal
from candleviewer.audit.writer import AuditWriter
from candleviewer.settings import Settings

_ATTEMPT, _REFUSED = "auth.break_glass_attempt", "auth.break_glass_refused"
#: What the CLI journals while Postgres is down: refusals of its own.
_CLI = {"actor_label": "system:breakglass", "outcome": "denied", "event_ts": "2026-10-15T12:00:00Z"}


def _ctx(wal: Path) -> Any:
    return SimpleNamespace(settings=Settings(audit_wal_path=str(wal)))


def _journal(path: Path, *actions: str) -> list[str]:
    """Journal records as the CLI does while Postgres is down; returns their `record_id`s."""
    ids = [str(uuid.uuid4()) for _ in actions]
    journal = AuditWal(path)
    for record_id, action in zip(ids, actions, strict=True):
        journal.append({"record_id": record_id, "action": action, "severity": "critical"} | _CLI)
    return ids


@pytest.mark.parametrize(
    ("wal", "link"),
    [
        ("var/audit/audit.wal", None),
        ("{tmp}/x/../audit/audit.wal", None),
        ("{tmp}/audit/audit.wal", "audit"),
        ("{tmp}/audit/audit.wal", "audit/breakglass"),
        ("{tmp}/audit/audit.wal", "audit/breakglass/journal.wal"),
        ("{tmp}/audit/audit.wal", "audit/breakglass/instance.lock"),
    ],
)
def test_journal_dir_refuses_relative_or_symlink(
    tmp_path: Path, wal: str, link: str | None
) -> None:
    if link is not None:
        (tmp_path / link).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / link).symlink_to(tmp_path)
    with pytest.raises(HostFsUnavailable) as refused:
        anchored_journal_dir(wal.format(tmp=tmp_path))
    assert refused.value.reason == "host_fs_unavailable"


def test_lock_is_never_opened_through_a_symlink(tmp_path: Path) -> None:
    (tmp_path / "breakglass").mkdir()
    (tmp_path / "breakglass" / "instance.lock").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(HostFsUnavailable):
        hold_run_lock(tmp_path / "breakglass", exclusive=False)
    assert not (tmp_path / "elsewhere").exists()


async def test_api_refuses_boot_while_cli_holds_lock(tmp_path: Path) -> None:
    wal = tmp_path / "a.wal"
    cli = hold_run_lock(anchored_journal_dir(str(wal)), exclusive=True)
    svc = AuditService(FakeAuditRepository())
    with pytest.raises(RunLockHeld):
        await svc.start(_ctx(wal))
    assert not svc.is_active  # no writer and no fold-in while the CLI runs
    cli.close()
    await svc.start(_ctx(wal))  # boots once the CLI has exited, and then keeps it out
    with pytest.raises(RunLockHeld):
        hold_run_lock(journal_dir(str(wal)), exclusive=True)
    await svc.stop(1)
    hold_run_lock(journal_dir(str(wal)), exclusive=True).close()  # released by stop()


_PROBE = """import sys, pathlib
from candleviewer.audit.journal import RunLockHeld, hold_run_lock
try: hold_run_lock(pathlib.Path(sys.argv[1]), exclusive=True)
except RunLockHeld: print("held")
else: print("acquired")"""


def _second_process_lock(directory: Path) -> str:
    done = subprocess.run(  # noqa: S603 -- fixed argv: this interpreter, a literal probe, tmp dir
        [sys.executable, "-B", "-c", _PROBE, str(directory)],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    return done.stdout.splitlines()[-1]


def test_lock_excludes_second_process(tmp_path: Path) -> None:
    directory = anchored_journal_dir(str(tmp_path / "a.wal"))
    with hold_run_lock(directory, exclusive=True):
        assert _second_process_lock(directory) == "held"
    assert _second_process_lock(directory) == "acquired"


async def test_fold_in_once(tmp_path: Path, repo: FakeAuditRepository) -> None:
    wal = tmp_path / "a.wal"
    journal = journal_dir(str(wal)) / "journal.wal"
    ids = _journal(journal, _ATTEMPT, _REFUSED)
    unfolded = journal.read_bytes()
    svc = AuditService(repo)
    for crash_before_cursor in (True, False, False):
        await svc.start(_ctx(wal))
        await svc.writer.flush(5)
        await svc.stop(1)
        if crash_before_cursor:  # as if the journal cursor never moved: the next boot re-folds
            journal.write_bytes(unfolded)
    assert [row["record_id"] for row in repo.rows] == ids
    assert journal.read_bytes() == b""  # folded and compacted


def _unusable(journal: Path, case: str) -> None:
    if case == "foreign_record":
        _journal(journal, _ATTEMPT, "orders.submit")
        return
    target = journal.with_name("elsewhere.wal") if case == "symlink" else journal
    _journal(target, _ATTEMPT, _REFUSED)
    if case == "symlink":
        journal.symlink_to(target)
    else:  # a damaged frame with a good one after it: corruption, not a torn tail
        data = bytearray(journal.read_bytes())
        data[data.index(b"auth.break_glass")] ^= 0x01
        journal.write_bytes(bytes(data))


@pytest.mark.parametrize("case", ["damaged_frame", "foreign_record", "symlink"])
async def test_fold_in_corruption_does_not_block_boot(
    tmp_path: Path, repo: FakeAuditRepository, case: str
) -> None:
    wal = tmp_path / "a.wal"
    journal = journal_dir(str(wal)) / "journal.wal"
    _unusable(journal, case)
    evidence = journal.read_bytes()
    svc = AuditService(repo)
    await svc.start(_ctx(wal))
    assert svc.is_active  # boot goes on
    await svc.writer.flush(5)
    await svc.stop(1)
    [event] = repo.rows  # the critical event only: nothing is folded in
    assert (event["action"], event["severity"]) == (_REFUSED, "critical")
    assert (event["actor_label"], event["reason"]) == ("system:breakglass", "journal_unusable")
    assert journal.read_bytes() == evidence  # left in place for the investigation


async def test_fold_in_refused_append_keeps_the_journal(
    tmp_path: Path, repo: FakeAuditRepository
) -> None:
    wal = tmp_path / "a.wal"
    journal = journal_dir(str(wal)) / "journal.wal"
    ids = _journal(journal, _ATTEMPT, _REFUSED)
    stopped = AuditWriter(repo, str(wal))  # never started: it refuses every append
    assert await fold_in(stopped, journal.parent) == 0
    svc = AuditService(repo)
    await svc.start(_ctx(wal))  # the next boot folds the kept journal: each record lands once
    await svc.writer.flush(5)
    await svc.stop(1)
    assert [row["record_id"] for row in repo.rows] == ids
