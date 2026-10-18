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
        pytest.param("{tmp}/var/audit/b", {"audit_wal_path": "var/audit/a.wal"}, _AUDIT, id="cwd"),
        pytest.param(
            "{tmp}/real/parquet/b",
            {"parquet_root": "{tmp}/link/parquet"},
            "CV_PARQUET_ROOT",
            id="lake-reached-through-a-symlink",
        ),
        pytest.param("{tmp}/data/bars", {}, "CV_BARS_STATE_ROOT", id="above-the-default-bar-state"),
        # The spill WAL and the bar state are stripped, and their `~` expanded, as their own
        # checks do; so is the lake's `~`, for the defaults derived from it.
        pytest.param(
            "{tmp}/st/b", {"bars_state_root": " {tmp}/st "}, "CV_BARS_STATE_ROOT", id="bars-padded"
        ),
        pytest.param(
            "{tmp}/data/spill/b",
            {"recorder_wal_dir": " {tmp}/data/spill "},
            "CV_RECORDER_WAL_DIR",
            id="spill-padded",
        ),
        pytest.param(
            "{tmp}/data/home/st/b", {"bars_state_root": "~/st"}, "CV_BARS_STATE_ROOT", id="bars-~"
        ),
        pytest.param(
            "{tmp}/data/home/sp/b",
            {"recorder_wal_dir": "~/sp"},
            "CV_RECORDER_WAL_DIR",
            id="spill-~",
        ),
        pytest.param(
            "{tmp}/data/home/bars/state/b",
            {"parquet_root": "~/lake"},
            "CV_BARS_STATE_ROOT",
            id="default-bar-state-of-a-~-lake",
        ),
        pytest.param(
            "{tmp}/data/home/recorder-wal/b",
            {"parquet_root": "~/lake"},
            "CV_RECORDER_WAL_DIR",
            id="default-spill-of-a-~-lake",
        ),
        # Every other path is opened as written, the lake itself too: `~` is a directory name,
        # under the cwd.
        pytest.param("{tmp}/~/b", {"kek_handle": "~/k"}, "of CV_KEK_HANDLE", id="kek-handle-~"),
        pytest.param("{tmp}/~/lake/b", {"parquet_root": "~/lake"}, "CV_PARQUET_ROOT", id="lake-~"),
    ],
)
def test_a_data_directory_is_compared_where_its_consumer_opens_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, root: str, paths: dict[str, str], name: str
) -> None:
    """Resolved against the working directory or through a symlink; stripped or `~`-expanded
    where the consumer does, and not where it does not."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", f"{tmp_path}/data/home")
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real", target_is_directory=True)

    with pytest.raises(ValidationError, match=re.escape(name)):
        _settings(tmp_path, root, **paths)


def test_a_path_opened_as_written_is_not_stripped_or_expanded_for_the_comparison(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`~/k` is opened as `./~/k`, and a padded path keeps its spaces (a leading one makes it
    relative): neither `$HOME` nor the stripped directory is a data directory, so a root there is
    accepted (the table above refuses the directories these paths do name)."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", f"{tmp_path}/home")

    for paths, root in (
        ({"kek_handle": "~/k"}, f"{tmp_path}/home"),
        ({"parquet_root": "~/lake"}, f"{tmp_path}/home/lake"),
        ({"audit_wal_path": " {tmp}/audit/w"}, f"{tmp_path}/audit"),
    ):
        assert _settings(tmp_path, root, **paths).backup_root == root


@pytest.mark.parametrize("setting", ["parquet_root", "recorder_wal_dir", "bars_state_root"])
def test_an_unknown_user_home_where_the_comparison_expands_it_is_a_validation_error(
    tmp_path: Path, setting: str
) -> None:
    """The root cannot be compared with a directory that names no home: refused, naming the
    setting, never the user (#2728, C-12.6), not escaped as a `RuntimeError`."""
    with pytest.raises(
        ValidationError, match=f"~ in CV_{setting.upper()} names no home"
    ) as refused:
        _settings(tmp_path, "{tmp}/backups", **{setting: "~no-such-user-cv966/x"})

    for rendered in (str(refused.value), repr(refused.value.errors()), refused.value.json()):
        assert "no-such-user-cv966" not in rendered


#: Each directory the root is compared with: the label a refusal names, and the `Settings`
#: keywords that put it at `{d}` (the spill WAL must lie in the data directory, `{tmp}/data`).
#: The test patches the database directories in, at `{tmp}/data/postgres/data` and `questdb/data`.
_DIRECTORIES = {
    "audit-wal": (_AUDIT, {"audit_wal_path": "{d}/w"}),
    "checkpoint": ("the directory of CV_AUDIT_CHECKPOINT_PATH", {"audit_checkpoint_path": "{d}/c"}),
    "lake": ("CV_PARQUET_ROOT", {"parquet_root": "{d}"}),
    "spill": ("CV_RECORDER_WAL_DIR", {"recorder_wal_dir": "{d}"}),
    "bar-state": ("CV_BARS_STATE_ROOT", {"bars_state_root": "{d}"}),
    "kek": ("the directory of CV_KEK_HANDLE", {"kek_handle": "{d}/k"}),
    "kek-prev": ("the directory of CV_KEK_PREV_HANDLE", {"kek_prev_handle": "{d}/k"}),
    "kek-ack": ("the directory of CV_KEK_ACK_PATH", {"kek_ack_path": "{d}/k"}),
    "lane-key": ("the directory of CV_AUDIT_LANE_KEY_FILE", {"CV_AUDIT_LANE_KEY_FILE": "{d}/k"}),
    "lane-key-prev": (
        "the directory of CV_AUDIT_LANE_PREVIOUS_KEY_FILE",
        {"CV_AUDIT_LANE_PREVIOUS_KEY_FILE": "{d}/k"},
    ),
    "postgres": ("{d}", {}),
    "questdb": ("{d}", {}),
}


@pytest.mark.parametrize("shape", ["equal", "inside", "containing", "beside", "beside-short"])
@pytest.mark.parametrize("key", _DIRECTORIES)
def test_every_data_directory_is_refused_equal_inside_and_above_but_not_beside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str, shape: str
) -> None:
    """Each directory has a subtree of its own, so only it can refuse the root. The root is
    refused as the directory, inside it and above it, and accepted beside it, sharing its name as
    a prefix, longer or shorter: each entry is the directory itself, not its file, its parent or
    a string prefix."""
    monkeypatch.chdir(tmp_path)
    databases = tuple(f"{tmp_path}/data/{name}/data" for name in ("postgres", "questdb"))
    monkeypatch.setattr(settings_module, "DATABASE_DATA_DIRS", databases)
    label, keywords = _DIRECTORIES[key]
    directory = f"{tmp_path}/data/{key}/data"
    root = {
        "equal": directory,
        "inside": f"{directory}/b",
        "containing": f"{tmp_path}/data/{key}",
        "beside": f"{directory}-old",
        "beside-short": directory[:-1],
    }[shape]
    paths = {name: value.format(d=directory) for name, value in keywords.items()}

    if shape.startswith("beside"):
        assert _settings(tmp_path, root, **paths).backup_root == root
    else:
        with pytest.raises(ValidationError, match=re.escape(label.format(d=directory))):
            _settings(tmp_path, root, **paths)


@pytest.mark.parametrize("lake", ["{tmp}/data/parquet", "{tmp}/x/link"], ids=["plain", "symlink"])
def test_the_default_spill_wal_and_bar_state_are_where_their_own_checks_put_them(
    tmp_path: Path, lake: str
) -> None:
    """The anchors are the source of truth for both defaults, so a drift fails here. A lake that
    is a symlink to another directory moves the spill WAL's parent, not the bar state's."""
    (tmp_path / "x").mkdir()
    (tmp_path / "y" / "real").mkdir(parents=True)
    (tmp_path / "x" / "link").symlink_to(tmp_path / "y" / "real", target_is_directory=True)
    anchored = _settings(tmp_path, "", parquet_root=lake)  # unwired: only the anchors ran

    for name, directory in (
        ("CV_RECORDER_WAL_DIR", anchored.recorder_wal_dir),
        ("CV_BARS_STATE_ROOT", anchored.bars_state_root),
    ):
        for root in (directory, f"{directory}/b"):
            with pytest.raises(ValidationError, match=name):
                _settings(tmp_path, root, parquet_root=lake)
        for root in (f"{directory}-old", directory[:-1]):  # beside it, as above
            assert _settings(tmp_path, root, parquet_root=lake).backup_root == root


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
