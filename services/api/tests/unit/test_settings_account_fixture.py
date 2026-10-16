"""#2893 S2: the `CV_ACCOUNT_FIXTURE` gate (rulings 2 and 10 on the issue).

The dev/test account fixture transport answers exchange calls for fabricated keys, so `Settings`
refuses it before any module starts unless the process is dev/test: `CV_ENVIRONMENT=demo`,
`CV_FEED=synthetic`, no `CV_BYBIT_API_*` variable at all and no test clock. The scenario is a token
and the optional state dir follows the test clock's path rules. Unset, nothing changes.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from candleviewer.settings import Environment, FeedMode, Settings

_SCENARIO = "compliant"
#: An inert marker standing in for a secret value; never a credential.
_MARKER = "cv-2893-marker-" + "not-a-secret"
_VARIABLES = (
    "CV_ENVIRONMENT",
    "CV_FEED",
    "CV_TEST_CLOCK",
    "CV_TEST_CLOCK_FILE",
    "CV_ACCOUNT_FIXTURE",
    "CV_ACCOUNT_FIXTURE_DIR",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _VARIABLES:
        monkeypatch.delenv(name, raising=False)
    for name in [n for n in os.environ if n.upper().startswith("CV_BYBIT_API_")]:
        monkeypatch.delenv(name)


@pytest.fixture
def fixture_dir(tmp_path: Path) -> str:
    return str(tmp_path / "account-fixture")


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return Settings()


def _on(fixture_dir: str, **env: str) -> dict[str, str]:
    """The switch on a dev/test process, with `env` on top."""
    return {"CV_ACCOUNT_FIXTURE": _SCENARIO, "CV_ACCOUNT_FIXTURE_DIR": fixture_dir, **env}


def test_unset_by_default() -> None:
    settings = Settings()

    assert (settings.account_fixture, settings.account_fixture_dir) == (None, None)


def test_accepted_on_a_keyless_synthetic_demo(
    monkeypatch: pytest.MonkeyPatch, fixture_dir: str
) -> None:
    settings = _settings(monkeypatch, **_on(fixture_dir))

    assert (settings.environment, settings.feed) == (Environment.DEMO, FeedMode.SYNTHETIC)
    assert (settings.account_fixture, settings.account_fixture_dir) == (_SCENARIO, fixture_dir)
    assert settings.account_fixture_refusal() is None


def test_accepted_without_a_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(monkeypatch, CV_ACCOUNT_FIXTURE=_SCENARIO)

    assert (settings.account_fixture, settings.account_fixture_dir) == (_SCENARIO, None)


def test_refused_on_live(monkeypatch: pytest.MonkeyPatch, fixture_dir: str) -> None:
    with pytest.raises(ValidationError, match="refused unless CV_ENVIRONMENT=demo"):
        _settings(monkeypatch, **_on(fixture_dir, CV_ENVIRONMENT="live"))


def test_refused_on_testnet(monkeypatch: pytest.MonkeyPatch, fixture_dir: str) -> None:
    with pytest.raises(ValidationError, match="refused unless CV_ENVIRONMENT=demo"):
        _settings(monkeypatch, **_on(fixture_dir, CV_ENVIRONMENT="testnet"))


def test_refused_with_live_feed(monkeypatch: pytest.MonkeyPatch, fixture_dir: str) -> None:
    with pytest.raises(ValidationError, match="refused unless CV_FEED=synthetic"):
        _settings(monkeypatch, **_on(fixture_dir, CV_FEED="live"))


@pytest.mark.parametrize(
    "variable",
    ["CV_BYBIT_API_KEY", "CV_BYBIT_API_SECRET", "cv_bybit_api_key", "CV_BYBIT_API_PASSPHRASE"],
    ids=["key", "secret", "lower-case-key", "undeclared-name"],
)
def test_refused_with_env_exchange_key_and_never_echoes_it(
    monkeypatch: pytest.MonkeyPatch, fixture_dir: str, variable: str
) -> None:
    """Ruling 2's rider: any live credential variable refuses the switch, even a name `Settings`
    does not declare, which it would otherwise ignore. The refusal is a field validator's, so
    `str()`, `errors()` and `json()` carry only the dir's input, never the key (#2728, C-12.6)."""
    with pytest.raises(ValidationError, match=r"while any CV_BYBIT_API_\* variable is set") as err:
        _settings(monkeypatch, **_on(fixture_dir, **{variable: _MARKER}))

    error = err.value
    for rendered in (str(error), repr(error.errors()), error.json()):
        assert _MARKER[:12] not in rendered
    assert "input_value" not in str(error)
    assert [(e["loc"], e["input"]) for e in error.errors()] == [
        (("account_fixture_dir",), fixture_dir)
    ]


@pytest.mark.parametrize("environment", ["demo", "testnet"])
def test_refused_with_the_test_clock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fixture_dir: str, environment: str
) -> None:
    """Ruling 10: the fixture needs demo and #2086's test clock needs testnet, so the two never
    run together; the refusal says so instead of only naming one environment."""
    clock = {"CV_TEST_CLOCK": "true", "CV_TEST_CLOCK_FILE": str(tmp_path / "offset")}

    with pytest.raises(ValidationError, match="refused while CV_TEST_CLOCK is on"):
        _settings(monkeypatch, **_on(fixture_dir, CV_ENVIRONMENT=environment, **clock))


@pytest.mark.parametrize("scenario", ["../x", "A", "", "a" * 65, "compliant\n", "with-dash"])
def test_scenario_must_be_a_token(
    monkeypatch: pytest.MonkeyPatch, fixture_dir: str, scenario: str
) -> None:
    with pytest.raises(ValidationError, match="must be a scenario token"):
        _settings(monkeypatch, **_on(fixture_dir, CV_ACCOUNT_FIXTURE=scenario))


def test_scenario_token_may_be_64_characters(
    monkeypatch: pytest.MonkeyPatch, fixture_dir: str
) -> None:
    scenario = "a_0" * 21 + "z"

    settings = _settings(monkeypatch, **_on(fixture_dir, CV_ACCOUNT_FIXTURE=scenario))

    assert settings.account_fixture == scenario


@pytest.mark.parametrize(
    ("environment", "reason"),
    [("demo", "CV_ACCOUNT_FIXTURE is not set"), ("live", "refused unless CV_ENVIRONMENT=demo")],
)
def test_dir_without_the_switch_is_refused(
    monkeypatch: pytest.MonkeyPatch, fixture_dir: str, environment: str, reason: str
) -> None:
    """Never silently ignored: a dir alone is a half-configured fixture stack."""
    with pytest.raises(ValidationError, match=reason):
        _settings(monkeypatch, CV_ENVIRONMENT=environment, CV_ACCOUNT_FIXTURE_DIR=fixture_dir)


@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("relative", "must be an absolute path"),
        ("dot-dot", "must not contain '..'"),
        ("symlink", "must not be a symlink"),
        ("under-a-symlink", "must not be under a symlinked directory"),
    ],
)
def test_fixture_dir_absolute_no_dotdot_no_symlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: str, reason: str
) -> None:
    """The test clock's path rules (#2728), checked at load before any module starts."""
    (tmp_path / "real").mkdir()
    (tmp_path / "linked").symlink_to(tmp_path / "real")
    fixture_dir = {
        "relative": "account-fixture",
        "dot-dot": str(tmp_path / "real" / ".." / "account-fixture"),
        "symlink": str(tmp_path / "linked"),
        "under-a-symlink": str(tmp_path / "linked" / "account-fixture"),
    }[case]

    with pytest.raises(ValidationError, match=re.escape(f"CV_ACCOUNT_FIXTURE_DIR {reason}")):
        _settings(monkeypatch, **_on(fixture_dir))


def test_fixture_dir_with_a_trailing_slash_is_not_a_symlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture_dir = f"{tmp_path / 'account-fixture'}/"

    assert _settings(monkeypatch, **_on(fixture_dir)).account_fixture_dir == fixture_dir
