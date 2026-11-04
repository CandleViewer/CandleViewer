"""#3319 B1b: the sidecar's configuration is read whole or refused, by name, never echoing a value;
the recipient must match its pinned fingerprint at start (AD-SC03); its `repr` shows no secret
because it holds none."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pytest

from cvbackup import age_format
from cvbackup.config import ConfigError, load
from tests.unit.backup_sidecar._sidecar import recipient

_MARKER = "cvb-3319-marker-not-a-secret"


def _env(tmp_path: Path, **changes: str) -> dict[str, str]:
    root = tmp_path / "backups"
    root.mkdir(exist_ok=True)
    to = recipient()
    env = {
        "CVB_SOCKET": str(tmp_path / "s" / "cvb.sock"),
        "CVB_BACKUP_ROOT": str(root),
        "CVB_API_UID": str(os.getuid() + 1),
        "CVB_RECIPIENT": to,
        "CVB_RECIPIENT_FINGERPRINT": age_format.fingerprint(to),
    }
    env.update(changes)
    return env


def test_config_reads_every_value_and_the_floor_defaults(tmp_path: Path) -> None:
    config = load(_env(tmp_path))
    assert config.api_uid == os.getuid() + 1
    assert (config.run_cap, config.run_window, config.grace) == (
        6, timedelta(days=1), timedelta(days=7)
    )  # fmt: skip
    custom = load(_env(tmp_path, CVB_RUN_CAP="3", CVB_RUN_WINDOW_S="172800",
                       CVB_REMOVE_GRACE_S="3600"))  # fmt: skip
    assert (custom.run_cap, custom.run_window, custom.grace) == (
        3, timedelta(days=2), timedelta(hours=1)
    )  # fmt: skip


@pytest.mark.parametrize(
    ("name", "past", "edge"),
    [
        ("CVB_RUN_CAP", "7", "6"),  # the cap may only be lowered
        ("CVB_RUN_WINDOW_S", "86399", "86400"),  # the window only lengthened
        ("CVB_REMOVE_GRACE_S", "3599", "3600"),  # the grace never under an hour
    ],
)
def test_config_floor_is_not_configurable_past_its_figure(
    tmp_path: Path, name: str, past: str, edge: str
) -> None:
    with pytest.raises(ConfigError, match=f"{name} must be between"):
        load(_env(tmp_path, **{name: past}))
    load(_env(tmp_path, **{name: edge}))  # the figure itself is allowed


@pytest.mark.parametrize(
    ("changes", "rule"),
    [
        ({"CVB_SOCKET": "relative/cvb.sock"}, "CVB_SOCKET must be an absolute path"),
        ({"CVB_SOCKET": "/"}, "CVB_SOCKET must be an absolute path"),
        ({"CVB_BACKUP_ROOT": "/srv/../etc"}, "CVB_BACKUP_ROOT must be an absolute path"),
        ({"CVB_SOCKET": "{root}/cvb.sock"}, "must not be, contain or lie inside"),
        ({"CVB_API_UID": "0"}, "CVB_API_UID must be between"),
        ({"CVB_API_UID": "-5"}, "CVB_API_UID must be a whole number"),
        ({"CVB_API_UID": "{own}"}, "must not be the sidecar's own uid"),
        ({"CVB_RECIPIENT": _MARKER}, "CVB_RECIPIENT must be an age X25519 recipient"),
        ({"CVB_RECIPIENT_FINGERPRINT": _MARKER}, "CVB_RECIPIENT_FINGERPRINT must read"),
        ({"CVB_RECIPIENT_FINGERPRINT": "age-x25519-sha256:" + "0" * 64}, "does not match"),
        ({"CVB_RUN_CAP": "0"}, "CVB_RUN_CAP must be between 1 and 6"),
        ({"CVB_REMOVE_GRACE_S": "60"}, "CVB_REMOVE_GRACE_S must be between 3600"),
        ({"CVB_RUN_WINDOW_S": _MARKER}, "CVB_RUN_WINDOW_S must be a whole number"),
    ],
)
def test_config_refusal_names_the_variable_and_never_its_value(
    tmp_path: Path, changes: dict[str, str], rule: str
) -> None:
    root = str(tmp_path / "backups")
    filled = {k: v.format(root=root, own=os.getuid()) for k, v in changes.items()}
    with pytest.raises(ConfigError, match=rule) as refused:
        load(_env(tmp_path, **filled))
    assert _MARKER not in str(refused.value)


def test_config_recipient_not_matching_pin_refuses_start(tmp_path: Path) -> None:
    other = age_format.fingerprint(recipient())
    with pytest.raises(ConfigError, match="does not match"):
        load(_env(tmp_path, CVB_RECIPIENT_FINGERPRINT=other))


def test_config_paths_through_a_symlink_are_refused(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "real")
    with pytest.raises(ConfigError, match="CVB_BACKUP_ROOT must not be a symlink"):
        load(_env(tmp_path, CVB_BACKUP_ROOT=str(tmp_path / "link")))
    with pytest.raises(ConfigError, match="must not lie under a symlinked directory"):
        load(_env(tmp_path, CVB_BACKUP_ROOT=str(tmp_path / "link" / "backups")))


def test_config_root_with_a_hidden_component_is_refused(tmp_path: Path) -> None:
    (tmp_path / ".hidden").mkdir()
    with pytest.raises(ConfigError, match="CVB_BACKUP_ROOT must have no component that starts"):
        load(_env(tmp_path, CVB_BACKUP_ROOT=str(tmp_path / ".hidden")))


def test_config_repr_holds_paths_and_public_values_only(tmp_path: Path) -> None:
    config = load(_env(tmp_path))
    shown = repr(config)
    assert str(tmp_path) in shown and config.recipient in shown
    for word in ("password", "passfile", "dsn", "identity", "AGE-SECRET-KEY"):
        assert word not in shown.lower() and word.lower() not in shown.lower()
