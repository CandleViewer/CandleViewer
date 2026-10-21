"""E50-T63: the machine-event WAL's settings. `CV_MACHINE_EVENT_WAL_PATH` defaults to beside the
configured audit WAL (the compose root filesystem is read-only, so only the audit volume is
writable), which with the stock audit path is the ticket's `var/audit/machine_events.wal`; an
explicit path's directory is a data directory the backup root stays apart from. The cap is
`AuditWriter`'s, 64 MiB, at least 1 MiB."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from candleviewer.settings import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in [v for v in os.environ if v.startswith(("CV_MACHINE_EVENT", "CV_AUDIT_WAL"))]:
        monkeypatch.delenv(variable)
    monkeypatch.delenv("CV_BACKUP_ROOT", raising=False)


def test_the_wal_sits_beside_the_stock_audit_wal_by_default() -> None:
    settings = Settings()
    assert settings.machine_event_wal_path == "var/audit/machine_events.wal"
    assert settings.machine_event_wal_max_bytes == 64 * 1024 * 1024


def test_the_wal_follows_a_configured_audit_wal_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compose sets `CV_AUDIT_WAL_PATH` inside its one writable volume; the WAL goes there too."""
    monkeypatch.setenv("CV_AUDIT_WAL_PATH", "/var/lib/candleviewer/audit/audit.wal")
    expected = "/var/lib/candleviewer/audit/machine_events.wal"
    assert Settings().machine_event_wal_path == expected


def test_an_explicit_wal_path_is_kept(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CV_MACHINE_EVENT_WAL_PATH", f"{tmp_path}/ev/machine_events.wal")
    assert Settings().machine_event_wal_path == f"{tmp_path}/ev/machine_events.wal"


def test_the_backup_root_stays_apart_from_an_explicit_wal_directory(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="CV_MACHINE_EVENT_WAL_PATH"):
        Settings(
            audit_wal_path=f"{tmp_path}/audit/audit.wal",
            machine_event_wal_path=f"{tmp_path}/ev/machine_events.wal",
            backup_root=f"{tmp_path}/ev",
        )


@pytest.mark.parametrize("cap", [0, 1024 * 1024 - 1])
def test_a_cap_under_1_mib_is_refused(cap: int) -> None:
    with pytest.raises(ValidationError, match="machine_event_wal_max_bytes"):
        Settings(machine_event_wal_max_bytes=cap)


def test_the_cap_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CV_MACHINE_EVENT_WAL_MAX_BYTES", str(2 * 1024 * 1024))
    assert Settings().machine_event_wal_max_bytes == 2 * 1024 * 1024
