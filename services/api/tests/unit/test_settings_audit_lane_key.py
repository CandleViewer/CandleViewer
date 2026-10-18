"""ADR-0037 decision 6 (#3009 S2b): the audit lane's key files are settings.

`CV_AUDIT_LANE_KEY_FILE` and `CV_AUDIT_LANE_PREVIOUS_KEY_FILE` name files, checked like
`CV_TEST_CLOCK_FILE` (#2728): absolute, without `..`, and no component a symlink. An explicit
value is checked at load. The default is checked by the loader that reads it
(`candleviewer.audit_lane_wiring`), so no boot changes before that loader is wired. Paths are no
secret: the field names stay clear of the redaction pattern and `repr()` shows them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

import candleviewer.settings as settings_mod
from candleviewer.settings import Settings

KEY, PREVIOUS = "CV_AUDIT_LANE_KEY_FILE", "CV_AUDIT_LANE_PREVIOUS_KEY_FILE"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (KEY, PREVIOUS):
        monkeypatch.delenv(name, raising=False)


def test_the_defaults_are_the_compose_secret_and_no_previous_key() -> None:
    settings = Settings()

    assert settings.audit_lane_mac_file == "/run/secrets/cv_audit_lane_key"
    assert settings.audit_lane_previous_mac_file is None


def test_the_default_key_file_is_not_checked_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """S2b-1 changes no boot: only an explicit value is checked when `Settings` loads."""

    def _never(value: str) -> str | None:
        raise AssertionError(f"{value} was checked at load")

    monkeypatch.setattr(settings_mod, "key_file_path_refusal", _never)

    assert Settings().audit_lane_mac_file == "/run/secrets/cv_audit_lane_key"


@pytest.mark.parametrize("variable", [KEY, PREVIOUS])
@pytest.mark.parametrize(
    ("path", "reason"),
    [
        ("cv_audit_lane_key", "must be an absolute path"),
        ("/run/secrets/../cv_audit_lane_key", "must not contain '..'"),
    ],
    ids=["relative", "dot-dot"],
)
def test_a_key_file_that_is_relative_or_has_dot_dot_is_refused_at_load(
    monkeypatch: pytest.MonkeyPatch, variable: str, path: str, reason: str
) -> None:
    monkeypatch.setenv(variable, path)

    with pytest.raises(ValidationError, match=f"{variable} {reason}"):
        Settings()


@pytest.mark.parametrize("variable", [KEY, PREVIOUS])
@pytest.mark.parametrize(
    ("name", "reason"),
    [("link", "must not be a symlink"), ("linked/key", "must not be under a symlinked directory")],
    ids=["symlink", "under-symlink"],
)
def test_a_key_file_that_is_or_lies_under_a_symlink_is_refused_at_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, variable: str, name: str, reason: str
) -> None:
    root = tmp_path.resolve()
    (root / "real").mkdir()
    (root / "linked").symlink_to(root / "real")
    (root / "link").symlink_to(root / "real" / "key")
    monkeypatch.setenv(variable, str(root / name))

    with pytest.raises(ValidationError, match=f"{variable} {reason}"):
        Settings()


def test_the_key_files_come_from_their_documented_variables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    current, previous = str(tmp_path.resolve() / "k1"), str(tmp_path.resolve() / "k0")
    monkeypatch.setenv("CV_AUDIT_LANE_MAC_FILE", "/elsewhere")  # the field's name: no variable
    monkeypatch.setenv(KEY, current)
    monkeypatch.setenv(PREVIOUS, previous)

    settings = Settings()

    assert (settings.audit_lane_mac_file, settings.audit_lane_previous_mac_file) == (
        current,
        previous,
    )
    assert f"audit_lane_mac_file='{current}'" in repr(settings)


@pytest.mark.parametrize(
    ("variable", "expected"), [(KEY, "/run/secrets/cv_audit_lane_key"), (PREVIOUS, None)]
)
def test_a_blank_key_file_counts_as_unset(
    monkeypatch: pytest.MonkeyPatch, variable: str, expected: str | None
) -> None:
    """A compose passthrough of an unset variable is blank; it never stops a boot."""
    monkeypatch.setenv(variable, " ")

    settings = Settings()

    assert {KEY: settings.audit_lane_mac_file, PREVIOUS: settings.audit_lane_previous_mac_file}[
        variable
    ] == expected
