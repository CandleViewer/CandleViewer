"""E42-T05 BK-6b (#966 Q7): `CV_BACKUP_ROOT`, the one directory backup artefacts are read from,
checked at load: empty is unwired; else absolute, not `/`, no `..` or symlink in it, and apart
from every data directory, compared resolved: none of them, nor inside or above one."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer import settings as settings_module
from candleviewer.settings import DATABASE_DATA_DIRS, Settings

#: An inert marker standing in for a secret value; never a credential.
_MARKER = "cv-966-marker-not-a-secret"
_COMPOSE = Path(__file__).resolve().parents[4] / "infra" / "compose" / "docker-compose.yml"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("BACKUP", "BYBIT_API", "PARQUET", "AUDIT", "KEK", "RECORDER_WAL", "BARS"):
        for variable in [v for v in os.environ if v.startswith(f"CV_{name}")]:
            monkeypatch.delenv(variable)


def _settings(tmp_path: Path, root: str, **paths: str) -> Settings:
    """Each data directory under `tmp_path`: the lake in `data/parquet` (the spill WAL and bar
    state default to `data/recorder-wal`, `data/bars/state`), the audit WAL in `audit`, the KEK
    handle in `secrets`."""
    chosen = {
        "parquet_root": "{tmp}/data/parquet",
        "audit_wal_path": "{tmp}/audit/audit.wal",
        "kek_handle": "{tmp}/secrets/cv_kek",
        **paths,
    }
    named: dict[str, Any] = {name: value.format(tmp=tmp_path) for name, value in chosen.items()}
    return Settings(backup_root=root.format(tmp=tmp_path), **named)


def test_backup_root_is_unwired_by_default_and_when_blank(tmp_path: Path) -> None:
    assert Settings().backup_root == _settings(tmp_path, "  ").backup_root == ""


def test_a_root_apart_from_every_data_directory_is_read_from_the_environment_normalised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CV_BACKUP_ROOT", f"{tmp_path}/backups/")

    assert Settings().backup_root == f"{tmp_path}/backups"


def test_a_sibling_that_shares_a_prefix_with_a_data_directory_is_accepted(tmp_path: Path) -> None:
    """Directories compare by component, never as string prefixes (R26)."""
    assert (
        _settings(tmp_path, "{tmp}/data/parquet-old").backup_root == f"{tmp_path}/data/parquet-old"
    )


@pytest.mark.parametrize(
    ("root", "rule"),
    [
        pytest.param("backups", "must be an absolute path", id="relative"),
        pytest.param("/", "must not be /", id="slash"),
        pytest.param("{tmp}/x/../backups", "must not contain '..'", id="dot-dot"),
        pytest.param("{tmp}/link", "must not be a symlink", id="symlink"),
        pytest.param("{tmp}/link/b", "must not be under a symlinked directory", id="under-a-link"),
    ],
)
def test_a_relative_root_slash_dotdot_and_symlinks_are_refused(
    tmp_path: Path, root: str, rule: str
) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)

    with pytest.raises(ValidationError, match=rule):
        _settings(tmp_path, root)


_AUDIT = "the directory of CV_AUDIT_WAL_PATH"


@pytest.mark.parametrize(
    ("root", "paths", "name"),
    [
        pytest.param("{tmp}/audit", {}, _AUDIT, id="audit-wal-dir"),
        pytest.param("{tmp}/audit/b", {}, _AUDIT, id="inside-it"),
        pytest.param("{tmp}/var/audit/b", {"audit_wal_path": "var/audit/a.wal"}, _AUDIT, id="cwd"),
        pytest.param("{tmp}/data", {}, "CV_PARQUET_ROOT", id="above-the-lake"),
        pytest.param("{tmp}/data/parquet/b", {}, "CV_PARQUET_ROOT", id="inside-the-lake"),
        pytest.param(
            "{tmp}/real/parquet/b",
            {"parquet_root": "{tmp}/link/parquet"},
            "CV_PARQUET_ROOT",
            id="lake-reached-through-a-symlink",
        ),
        pytest.param("{tmp}/data/recorder-wal/b", {}, "CV_RECORDER_WAL_DIR", id="default-spill"),
        pytest.param("{tmp}/data/bars", {}, "CV_BARS_STATE_ROOT", id="above-the-default-bar-state"),
        pytest.param(
            "{tmp}/st/b", {"bars_state_root": "{tmp}/st"}, "CV_BARS_STATE_ROOT", id="bars"
        ),
        pytest.param("{tmp}/c/b", {"audit_checkpoint_path": "{tmp}/c/x"}, "CHECKPOINT", id="ckpt"),
        pytest.param("{tmp}/ack", {"kek_ack_path": "{tmp}/ack/n"}, "CV_KEK_ACK_PATH", id="kek-ack"),
        pytest.param(
            "{tmp}/l/b", {"CV_AUDIT_LANE_KEY_FILE": "{tmp}/l/k"}, "LANE_KEY_FILE", id="lane"
        ),
        pytest.param(
            "{tmp}/p",
            {"CV_AUDIT_LANE_PREVIOUS_KEY_FILE": "{tmp}/p/k"},
            "LANE_PREVIOUS",
            id="lane-prev",
        ),
        pytest.param(
            "{tmp}/data/spill", {"recorder_wal_dir": "{tmp}/data/spill"}, "CV_RECORDER_WAL_DIR"
        ),
        pytest.param("{tmp}/secrets", {}, "the directory of CV_KEK_HANDLE", id="kek-handle-dir"),
        pytest.param("{tmp}/o/b", {"kek_prev_handle": "{tmp}/o/k"}, "of CV_KEK_PREV_HANDLE"),
        pytest.param("{tmp}/pg", {}, "{tmp}/pg", id="postgres-data"),
        pytest.param("{tmp}/quest/b", {}, "{tmp}/quest", id="inside-questdb-data"),
    ],
)
def test_a_root_that_is_contains_or_lies_inside_a_data_directory_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, root: str, paths: dict[str, str], name: str
) -> None:
    monkeypatch.chdir(tmp_path)
    data_dirs = (f"{tmp_path}/pg", f"{tmp_path}/quest")
    monkeypatch.setattr(settings_module, "DATABASE_DATA_DIRS", data_dirs)
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)

    with pytest.raises(ValidationError, match=re.escape(name.format(tmp=tmp_path))):
        _settings(tmp_path, root, **paths)


def test_the_database_data_directories_are_where_the_stack_mounts_its_volumes() -> None:
    assert DATABASE_DATA_DIRS == ("/var/lib/postgresql", "/var/lib/questdb")
    assert all(f"-data:{d}" in _COMPOSE.read_text(encoding="utf-8") for d in DATABASE_DATA_DIRS)


def test_a_refused_backup_root_never_echoes_another_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-12.6: a field validator, so the refusal's input is this one value, never every setting
    as a model validator's would be (#2728, #2778)."""
    monkeypatch.setenv("CV_BYBIT_API_KEY", _MARKER)
    monkeypatch.setenv("CV_BACKUP_ROOT", "backups")

    with pytest.raises(ValidationError, match="CV_BACKUP_ROOT") as refused:
        Settings()

    for rendered in (str(refused.value), repr(refused.value.errors()), refused.value.json()):
        assert _MARKER not in rendered
    assert [error["input"] for error in refused.value.errors()] == ["backups"]
