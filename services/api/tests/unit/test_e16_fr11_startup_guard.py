"""E16-FR-11 (#1741, threat model R-E3, AC-14): neither test-only switch, `CV_TEST_CLOCK` nor
`CV_ALLOW_SHARED_VOLUME`, boots outside testnet. Both are refused when `Settings` loads, before
any module starts; the refusal names the switch and its payload carries only the offending field;
and no request path (`candleviewer.api`) reads either switch."""

from __future__ import annotations

import ast
import pkgutil
from pathlib import Path

import pytest
from pydantic import ValidationError

import candleviewer.api as api_pkg
from candleviewer.settings import Environment, Settings

_CLOCK = {"CV_TEST_CLOCK": "true", "CV_TEST_CLOCK_FILE": "/run/cv-test-clock/offset"}
_SHARED = {"CV_ALLOW_SHARED_VOLUME": "true"}
_SWITCHES = {"CV_TEST_CLOCK": _CLOCK, "CV_ALLOW_SHARED_VOLUME": _SHARED}
#: An inert value for an unrelated setting, which must not appear in a refusal payload.
_MARKER = "cv-e16-fr11-unrelated-value"
_READ_NAMES = frozenset({"test_clock", "test_clock_file", "allow_shared_volume", *_CLOCK, *_SHARED})


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("CV_ENVIRONMENT", "CV_FEED_SAMPLE_PATH", "CV_BYBIT_API_KEY", *_CLOCK, *_SHARED):
        monkeypatch.delenv(name, raising=False)


def _load(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> Settings:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return Settings()


@pytest.mark.parametrize("switch", sorted(_SWITCHES))
@pytest.mark.parametrize("environment", ["live", "demo"])
def test_a_test_switch_refuses_boot_outside_testnet_naming_only_its_own_field(
    monkeypatch: pytest.MonkeyPatch, environment: str, switch: str
) -> None:
    env = {"CV_ENVIRONMENT": environment, "CV_FEED_SAMPLE_PATH": _MARKER, **_SWITCHES[switch]}
    with pytest.raises(ValidationError, match=switch) as refused:
        _load(monkeypatch, env)
    error = refused.value
    assert "CV_ENVIRONMENT" in str(error)
    assert _MARKER not in str(error)
    assert _MARKER not in repr(error.errors())
    assert _MARKER not in error.json()


def test_the_shared_volume_hatch_is_accepted_on_testnet(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _load(monkeypatch, {"CV_ENVIRONMENT": "testnet", **_SHARED})
    assert settings.environment is Environment.TESTNET and settings.allow_shared_volume


def test_the_test_clock_is_accepted_only_on_a_keyless_testnet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _load(monkeypatch, {"CV_ENVIRONMENT": "testnet", **_CLOCK})
    assert settings.test_clock and settings.test_clock_refusal() is None
    with pytest.raises(ValidationError, match="exchange key"):
        _load(monkeypatch, {"CV_BYBIT_API_KEY": _MARKER})


def test_both_switches_default_off() -> None:
    settings = Settings()
    assert (settings.test_clock, settings.test_clock_file, settings.allow_shared_volume) == (
        False,
        None,
        False,
    )


def _reads(source: str) -> set[str]:
    """Attribute names, bare names and string constants that name a switch."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute) and node.attr in _READ_NAMES:
            found.add(node.attr)
        elif isinstance(node, ast.Name) and node.id in _READ_NAMES:
            found.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.update(name for name in _READ_NAMES if name in node.value)
    return found


def test_no_request_path_reads_either_switch() -> None:
    root = Path(api_pkg.__path__[0])
    scanned = {path.relative_to(root).as_posix(): path for path in root.rglob("*.py")}
    assert len(scanned) > 20 and "recorder_purge.py" in scanned
    assert len(list(pkgutil.walk_packages(api_pkg.__path__))) > 20
    readers = {name: hits for name, p in scanned.items() if (hits := _reads(p.read_text("utf-8")))}
    assert readers == {}


def test_the_scan_would_see_a_read() -> None:
    assert _reads("def f(s):\n    return s.allow_shared_volume\n") == {"allow_shared_volume"}
    assert _reads("X = os.environ['CV_TEST_CLOCK']\n") == {"CV_TEST_CLOCK"}
