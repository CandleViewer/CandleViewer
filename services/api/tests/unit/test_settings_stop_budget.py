"""#2565: the api stop budget.

The planned shutdown runs the WS grace, the close flush, uvicorn's drain and then the module
teardown, one after another, inside the container's SIGTERM -> SIGKILL budget (compose
`stop_grace_period`). `Settings` sums those terms and refuses a config the budget cannot
cover, and the committed compose files carry that budget. Pure unit tests: no docker, no
network, no sleeps.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import SecretStr, ValidationError

from candleviewer import ws_wiring
from candleviewer.app import Supervisor
from candleviewer.settings import CLOSE_FLUSH_TIMEOUT_S, TEARDOWN_BUDGET_S, Settings, get_settings
from candleviewer.ws import gateway

_COMPOSE_DIR = Path(__file__).resolve().parents[4] / "infra" / "compose"
_BASE_COMPOSE = _COMPOSE_DIR / "docker-compose.yml"


def _needed_s(s: Settings) -> float:
    """The four-term sum `Settings` checks, restated independently of its implementation."""
    return (
        s.ws_shutdown_grace_ms / 1000
        + CLOSE_FLUSH_TIMEOUT_S
        + s.uvicorn_drain_timeout_s
        + TEARDOWN_BUDGET_S
    )


# --- the budget check ---------------------------------------------------------------------


def test_default_settings_fit_the_default_budget() -> None:
    s = Settings()
    assert (s.ws_shutdown_grace_ms, s.uvicorn_drain_timeout_s, s.api_stop_budget_s) == (
        5000,
        5,
        30,
    )
    assert _needed_s(s) == 27.0  # 5 s grace + 2 s flush + 5 s drain + 15 s teardown
    assert _needed_s(s) <= s.api_stop_budget_s


def test_a_60s_grace_cannot_fit_the_default_budget_and_the_message_names_every_term() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(ws_shutdown_grace_ms=60_000)
    message = str(exc_info.value)
    for term in (
        "CV_WS_SHUTDOWN_GRACE_MS=60000",
        "CLOSE_FLUSH_TIMEOUT_S",
        "CV_UVICORN_DRAIN_TIMEOUT_S=5",
        "TEARDOWN_BUDGET_S",
        "CV_API_STOP_BUDGET_S=30",
    ):
        assert term in message
    assert "82 s" in message  # 60 + 2 + 5 + 15


def test_the_same_grace_fits_a_90s_budget() -> None:
    s = Settings(ws_shutdown_grace_ms=60_000, api_stop_budget_s=90)
    assert _needed_s(s) == 82.0
    assert s.api_stop_budget_s == 90


def test_a_sum_exactly_at_the_budget_is_accepted_and_one_millisecond_over_is_refused() -> None:
    assert _needed_s(Settings(ws_shutdown_grace_ms=8000)) == 30.0  # 8 + 2 + 5 + 15
    with pytest.raises(ValidationError, match="CV_API_STOP_BUDGET_S=30"):
        Settings(ws_shutdown_grace_ms=8001)


def test_the_drain_timeout_is_a_term_of_the_sum() -> None:
    with pytest.raises(ValidationError, match="CV_UVICORN_DRAIN_TIMEOUT_S=30"):
        Settings(uvicorn_drain_timeout_s=30)  # 5 + 2 + 30 + 15 = 52 > 30
    assert Settings(uvicorn_drain_timeout_s=30, api_stop_budget_s=60).uvicorn_drain_timeout_s == 30


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("api_stop_budget_s", 9),
        ("api_stop_budget_s", 121),
        ("uvicorn_drain_timeout_s", 0),
        ("uvicorn_drain_timeout_s", 31),
    ],
)
def test_the_budget_and_the_drain_timeout_are_range_checked(field: str, value: int) -> None:
    with pytest.raises(ValidationError, match=field):
        Settings.model_validate({field: value})


def test_the_budget_and_the_drain_timeout_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CV_API_STOP_BUDGET_S", "60")
    monkeypatch.setenv("CV_UVICORN_DRAIN_TIMEOUT_S", "20")
    monkeypatch.setenv("CV_WS_SHUTDOWN_GRACE_MS", "15000")  # 15 + 2 + 20 + 15 = 52 <= 60
    s = get_settings()
    assert (s.api_stop_budget_s, s.uvicorn_drain_timeout_s, s.ws_shutdown_grace_ms) == (
        60,
        20,
        15_000,
    )


def test_the_refusal_message_never_includes_a_secret_value() -> None:
    """The message names terms and numbers only, and `Settings` sets `hide_input_in_errors` (#2086),
    so pydantic appends no `input_value` of the raw input either."""
    sentinels = ("sentinel-api-key", "sentinel-api-secret", "sentinel-dsn-pw", "sentinel-pepper")
    with pytest.raises(ValidationError) as exc_info:
        Settings.model_validate(
            {
                "ws_shutdown_grace_ms": 60_000,
                "bybit_api_key": sentinels[0],
                "bybit_api_secret": sentinels[1],
                "pg_dsn": f"postgresql+asyncpg://cv:{sentinels[2]}@db:5432/cv",
                "auth_pepper": sentinels[3],
            }
        )
    (error,) = exc_info.value.errors()
    assert "CV_API_STOP_BUDGET_S" in error["msg"]
    assert not [s for s in sentinels if s in error["msg"]]


# --- the check and the teardown share their terms ------------------------------------------


def test_the_supervisors_per_module_grace_is_the_teardown_term() -> None:
    default = inspect.signature(Supervisor.stop_all).parameters["grace_s"].default
    assert default == TEARDOWN_BUDGET_S == 15.0  # the value the budget was sized for


@pytest.mark.parametrize("module", [gateway, ws_wiring], ids=lambda m: m.__name__)
def test_the_ws_close_flush_is_the_term_the_budget_sums(module: Any) -> None:
    assert vars(module)["CLOSE_FLUSH_TIMEOUT_S"] == CLOSE_FLUSH_TIMEOUT_S == 2.0


# --- compose: `stop_grace_period` carries the budget ---------------------------------------

_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(us|ms|s|m|h)")
_UNIT_S = {"us": 1e-6, "ms": 1e-3, "s": 1.0, "m": 60.0, "h": 3600.0}


def _seconds(duration: object) -> float:
    """A compose duration (`30s`, `1m30s`, `500ms`) in seconds; anything else is an error."""
    text = str(duration)
    parts = _DURATION_PART.findall(text)
    if not parts or "".join(n + u for n, u in parts) != text:
        raise ValueError(f"not a compose duration with a unit: {text!r}")
    return sum(float(n) * _UNIT_S[u] for n, u in parts)


def _env(service: dict[str, Any]) -> dict[str, str]:
    raw = service.get("environment") or {}
    if isinstance(raw, dict):
        return {str(k): "" if v is None else str(v) for k, v in raw.items()}
    return {k: v for k, _, v in (str(item).partition("=") for item in raw)}


def _api(path: Path) -> dict[str, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    api: dict[str, Any] = (doc.get("services") or {}).get("api") or {}
    return api


def _effective_api(overlay: Path) -> dict[str, Any]:
    """The `api` service as `docker compose -f docker-compose.yml -f <overlay>` merges it:
    a scalar of the overlay replaces the base's, `environment` merges key by key."""
    base, over = _api(_BASE_COMPOSE), _api(overlay)
    merged = {**base, **over}
    merged["environment"] = {**_env(base), **_env(over)}
    return merged


def stop_budget_problems(api: dict[str, Any], budget_s: int) -> list[str]:
    """What is wrong with one effective `api` service for a stop budget of `budget_s`."""
    grace = api.get("stop_grace_period")
    if grace is None:
        return ["no stop_grace_period: Docker's 10 s default would SIGKILL the teardown"]
    try:
        grace_s = _seconds(grace)
    except ValueError as exc:
        return [str(exc)]
    problems: list[str] = []
    if grace_s < budget_s:
        problems.append(f"stop_grace_period {grace} is shorter than the {budget_s} s budget")
    declared = _env(api).get("CV_API_STOP_BUDGET_S")
    if declared is None:
        problems.append("CV_API_STOP_BUDGET_S is not set in the api environment")
    elif not declared.isdigit() or float(declared) != grace_s:
        problems.append(f"CV_API_STOP_BUDGET_S={declared!r} differs from stop_grace_period {grace}")
    return problems


_COMPOSE_FILES = sorted(_COMPOSE_DIR.glob("docker-compose*.yml"))


def test_compose_files_define_the_api_service() -> None:
    assert _BASE_COMPOSE in _COMPOSE_FILES
    assert _api(_BASE_COMPOSE)  # the guard below is never vacuous


@pytest.mark.parametrize("path", _COMPOSE_FILES, ids=lambda p: p.name)
def test_compose_api_stop_grace_period_covers_the_stop_budget(path: Path) -> None:
    assert stop_budget_problems(_effective_api(path), Settings().api_stop_budget_s) == []


@pytest.mark.parametrize("path", _COMPOSE_FILES, ids=lambda p: p.name)
def test_a_compose_file_that_sets_one_half_of_the_budget_sets_both(path: Path) -> None:
    api = _api(path)
    set_here = {"stop_grace_period" in api, "CV_API_STOP_BUDGET_S" in _env(api)}
    assert len(set_here) == 1, f"{path.name} sets only one of stop_grace_period / the budget"


def test_the_base_compose_file_sets_the_budget_the_settings_default_expects() -> None:
    api = _api(_BASE_COMPOSE)
    assert _seconds(api["stop_grace_period"]) == Settings().api_stop_budget_s
    assert _env(api)["CV_API_STOP_BUDGET_S"] == str(Settings().api_stop_budget_s)


@pytest.mark.parametrize(
    ("api", "fragment"),
    [
        ({}, "no stop_grace_period"),
        ({"stop_grace_period": "10s", "environment": {"CV_API_STOP_BUDGET_S": "10"}}, "shorter"),
        ({"stop_grace_period": "30s"}, "CV_API_STOP_BUDGET_S is not set"),
        ({"stop_grace_period": "30s", "environment": ["CV_API_STOP_BUDGET_S=45"]}, "differs"),
        ({"stop_grace_period": "30", "environment": {"CV_API_STOP_BUDGET_S": "30"}}, "unit"),
    ],
    ids=["missing", "too-short", "no-budget-env", "mismatch", "no-unit"],
)
def test_negative_control_the_guard_flags_a_broken_api_service(
    api: dict[str, Any], fragment: str
) -> None:
    assert any(fragment in p for p in stop_budget_problems(api, 30))


@pytest.mark.parametrize(
    ("api", "budget_s"),
    [
        ({"stop_grace_period": "30s", "environment": {"CV_API_STOP_BUDGET_S": "30"}}, 30),
        ({"stop_grace_period": "1m", "environment": {"CV_API_STOP_BUDGET_S": "60"}}, 60),
        ({"stop_grace_period": "30s", "environment": ["CV_API_STOP_BUDGET_S=30"]}, 30),
    ],
    ids=["seconds", "minutes", "list-environment"],
)
def test_the_guard_accepts_every_compose_spelling_of_a_matching_budget(
    api: dict[str, Any], budget_s: int
) -> None:
    assert stop_budget_problems(api, budget_s) == []


def test_a_refused_setting_never_echoes_a_secret_input() -> None:
    """C-12.6: the validator's error must not trail the env as `input_value=...`."""
    probe = "NOT-A-REAL-KEY-ECHO-PROBE"
    with pytest.raises(ValidationError) as err:
        Settings(ws_shutdown_grace_ms=60_000, bybit_api_key=SecretStr(probe))
    assert probe[:6] not in str(err.value) and "input_value" not in str(err.value)
