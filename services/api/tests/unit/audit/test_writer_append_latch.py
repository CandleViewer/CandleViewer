"""#2510: a failed WAL append latches a recoverable refusal that `app._audit_ready()` reads;
it never refuses `emit()`, expires after the cooldown and clears on the next append."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from audit_fakes import FakeAuditRepository, FakeClock

from candleviewer.app import _audit_ready
from candleviewer.audit.service import AuditService
from candleviewer.audit.writer import APPEND_FAILURE_COOLDOWN, AuditUnavailable, AuditWriter


async def test_writer_append_failure_latches_for_the_cooldown_then_success_clears_it(
    repo: FakeAuditRepository,
    tmp_path: Path,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = AuditWriter(repo, str(tmp_path / "audit.wal"), clock=clock, sleep=repo.retry_sleep)
    await w.start()
    handle = AuditService()
    handle._writer = w  # a started writer, as `AuditService.start()` wires it
    ready = _audit_ready(handle)
    append = w._wal.append

    def boom(_record: dict[str, Any]) -> int:
        raise OSError("disk gone")

    monkeypatch.setattr(w._wal, "append", boom)
    with pytest.raises(AuditUnavailable):
        await w.emit("auth.login", actor_label="refused")
    failed_at = w.append_failure
    assert failed_at is not None and w.append_failure_active and not ready()
    assert w.failure is None  # recoverable: not the fail-closed flusher death
    clock.now = failed_at - APPEND_FAILURE_COOLDOWN  # a wall clock stepped back: re-probe
    assert not w.append_failure_active
    clock.now = failed_at + APPEND_FAILURE_COOLDOWN
    assert not w.append_failure_active and ready()  # the next request re-probes
    with pytest.raises(AuditUnavailable):  # the re-probe fails: re-armed
        await w.emit("auth.login", actor_label="probe")
    assert w.append_failure_active and not ready()
    monkeypatch.setattr(w._wal, "append", append)
    await w.emit("auth.login", actor_label="kept")  # never refused by the latch itself
    assert w.append_failure is None and not w.append_failure_active and ready()
    await w.flush(5)
    await w.stop(1)
    assert [r["actor_label"] for r in repo.rows] == ["kept"]
