"""#2565: the api stop budget.

The planned shutdown runs the WS grace, the close flush, uvicorn's drain and then the module
teardown, one after another, inside the container's SIGTERM -> SIGKILL budget (compose
`stop_grace_period`). `Settings` sums those terms and refuses a config the budget cannot
cover, and the committed compose files carry that budget. Pure unit tests: no docker, no
network, no sleeps.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import uvicorn
import yaml
from pydantic import ValidationError

from candleviewer import ws_wiring
from candleviewer.app import AppContext, Supervisor
from candleviewer.settings import (
    CLOSE_AUDIT_TIMEOUT_S,
    CLOSE_FLUSH_TIMEOUT_S,
    MIN_DRAIN_TIMEOUT_S,
    MIN_STOP_BUDGET_S,
    SHUTDOWN_TICKS_S,
    STOP_SLACK_S,
    TEARDOWN_BUDGET_S,
    TEARDOWN_STOP_CAP_S,
    Settings,
    get_settings,
)
from candleviewer.ws import gateway

_COMPOSE_DIR = Path(__file__).resolve().parents[4] / "infra" / "compose"
_BASE_COMPOSE = _COMPOSE_DIR / "docker-compose.yml"


def _needed_s(s: Settings) -> float:
    """The worst case `Settings` checks, restated independently of its implementation: the grace,
    the flush, the drain, one module cut at its hard bound (its grace plus the supervisor's slack)
    and the two 0.1 s ticks of the exit path."""
    return (
        s.ws_shutdown_grace_ms / 1000
        + CLOSE_FLUSH_TIMEOUT_S
        + s.uvicorn_drain_timeout_s
        + (TEARDOWN_BUDGET_S + STOP_SLACK_S)
        + SHUTDOWN_TICKS_S
    )


# --- the budget check ---------------------------------------------------------------------


def test_default_settings_fit_the_default_budget() -> None:
    s = Settings()
    assert (s.ws_shutdown_grace_ms, s.uvicorn_drain_timeout_s, s.api_stop_budget_s) == (
        5000,
        5,
        30,
    )
    assert _needed_s(s) == pytest.approx(28.2)  # 5 grace + 2 flush + 5 drain + 16 module + 0.2
    assert _needed_s(s) <= s.api_stop_budget_s


def test_a_60s_grace_cannot_fit_the_default_budget_and_the_message_names_every_term() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(ws_shutdown_grace_ms=60_000)
    message = str(exc_info.value)
    for term in (
        "CV_WS_SHUTDOWN_GRACE_MS=60000",
        "CLOSE_FLUSH_TIMEOUT_S",
        "CV_UVICORN_DRAIN_TIMEOUT_S=5",
        "TEARDOWN_BUDGET_S + STOP_SLACK_S",
        "SHUTDOWN_TICKS_S",
        "CV_API_STOP_BUDGET_S=30",
    ):
        assert term in message
    assert "83.2 s" in message  # 60 + 2 + 5 + 16 + 0.2


def test_the_same_grace_fits_a_90s_budget() -> None:
    s = Settings(ws_shutdown_grace_ms=60_000, api_stop_budget_s=90)
    assert _needed_s(s) == pytest.approx(83.2)
    assert s.api_stop_budget_s == 90


def test_a_sum_exactly_at_the_budget_is_accepted_and_one_millisecond_over_is_refused() -> None:
    at_the_edge = Settings(ws_shutdown_grace_ms=6800)  # 6.8 + 2 + 5 + 16 + 0.2 = 30
    assert _needed_s(at_the_edge) == pytest.approx(30.0)
    with pytest.raises(ValidationError, match="CV_API_STOP_BUDGET_S=30"):
        Settings(ws_shutdown_grace_ms=6801)


def test_the_old_8s_grace_no_longer_fits_because_one_hung_module_is_cut_at_16s_not_15s() -> None:
    """The pre-review sum (15 s teardown, no ticks) accepted 8 s: 8 + 2 + 5 + 15 = 30. Then one
    module that ignores its grace is cut at 16 s and uvicorn's ticks add 0.2 s: 31.2 s, and the
    runtime would SIGKILL the teardown (secrets zeroing, storage flushes) before it ends."""
    assert TEARDOWN_STOP_CAP_S == TEARDOWN_BUDGET_S + STOP_SLACK_S == 16.0
    with pytest.raises(ValidationError, match=r"needs 31\.2 s"):
        Settings(ws_shutdown_grace_ms=8000)


def test_the_drain_timeout_is_a_term_of_the_sum() -> None:
    with pytest.raises(ValidationError, match="CV_UVICORN_DRAIN_TIMEOUT_S=30"):
        Settings(uvicorn_drain_timeout_s=30)  # 5 + 2 + 30 + 16 + 0.2 = 53.2 > 30
    assert Settings(uvicorn_drain_timeout_s=30, api_stop_budget_s=60).uvicorn_drain_timeout_s == 30


# --- the drain floor: a close's audit write is not cut off -----------------------------------
# uvicorn cancels what is still running when its drain ends and sends the lifespan `shutdown`
# without awaiting the cancelled handlers. A close can need the flush and then the audit write
# after `WsRuntime.stop()` stopped waiting (a writer stalled on a peer that stopped reading frees
# its handler only when uvicorn's `connection.shutdown()` runs), so the drain may not be shorter
# than their sum. `test_drain_floor_real_socket` shows it on a real server.


def test_the_floor_is_the_flush_plus_the_audit_write_and_the_budget_floor_follows() -> None:
    assert MIN_DRAIN_TIMEOUT_S == CLOSE_FLUSH_TIMEOUT_S + CLOSE_AUDIT_TIMEOUT_S == 4
    assert MIN_STOP_BUDGET_S == 23  # 0 grace + 2 flush + 4 drain + 16 module + 0.2, rounded up
    s = Settings(ws_shutdown_grace_ms=0, uvicorn_drain_timeout_s=4, api_stop_budget_s=23)
    assert _needed_s(s) == pytest.approx(22.2) and s.api_stop_budget_s == MIN_STOP_BUDGET_S


def test_a_drain_below_the_floor_is_refused_and_the_message_names_both_terms() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(uvicorn_drain_timeout_s=3)
    (error,) = exc_info.value.errors()
    assert error["loc"] == ("uvicorn_drain_timeout_s",)
    for term in (
        "CV_UVICORN_DRAIN_TIMEOUT_S=3",
        "4 s",
        "CLOSE_FLUSH_TIMEOUT_S (2 s)",
        "CLOSE_AUDIT_TIMEOUT_S (2 s)",
        "ws.connection.closed",
    ):
        assert term in error["msg"]


@pytest.mark.parametrize("drain_s", [4, 5, 10, 30])
def test_a_drain_at_or_above_the_floor_is_accepted(drain_s: int) -> None:
    s = Settings(uvicorn_drain_timeout_s=drain_s, api_stop_budget_s=120)
    assert s.uvicorn_drain_timeout_s == drain_s >= MIN_DRAIN_TIMEOUT_S


def test_the_default_drain_covers_the_floor() -> None:
    assert Settings().uvicorn_drain_timeout_s >= MIN_DRAIN_TIMEOUT_S


def test_a_drain_below_the_floor_is_refused_from_the_environment_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CV_UVICORN_DRAIN_TIMEOUT_S", "3")
    with pytest.raises(ValidationError, match="CLOSE_FLUSH_TIMEOUT_S"):
        get_settings()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("api_stop_budget_s", MIN_STOP_BUDGET_S - 1),  # no grace or drain could ever fit it
        ("api_stop_budget_s", 121),
        ("uvicorn_drain_timeout_s", 0),
        ("uvicorn_drain_timeout_s", 31),
        ("uvicorn_drain_timeout_s", "abc"),  # not a number: the field's own check refuses it
        ("uvicorn_drain_timeout_s", float("inf")),  # `int(inf)` is an OverflowError, not a refusal
        ("ws_shutdown_grace_ms", 60_001),  # the budget check skips a term whose own check failed
    ],
)
def test_the_budget_and_the_drain_timeout_are_range_checked(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match=field) as exc_info:
        Settings.model_validate({field: value})
    # that setting's own error and nothing on top: a term that failed is never summed
    assert [e["loc"] for e in exc_info.value.errors()] == [(field,)]


def test_the_declared_ranges_are_the_ones_that_can_validate() -> None:
    """The advertised minimums are the smallest values some configuration accepts."""
    fields = Settings.model_fields
    drain_min = next(m.ge for m in fields["uvicorn_drain_timeout_s"].metadata if hasattr(m, "ge"))
    budget_min = next(m.ge for m in fields["api_stop_budget_s"].metadata if hasattr(m, "ge"))
    assert (drain_min, budget_min) == (MIN_DRAIN_TIMEOUT_S, MIN_STOP_BUDGET_S)


def test_the_budget_and_the_drain_timeout_come_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CV_API_STOP_BUDGET_S", "60")
    monkeypatch.setenv("CV_UVICORN_DRAIN_TIMEOUT_S", "20")
    monkeypatch.setenv("CV_WS_SHUTDOWN_GRACE_MS", "15000")  # 15 + 2 + 20 + 16 + 0.2 = 53.2 <= 60
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


def test_the_ws_close_audit_bound_is_the_term_the_floor_uses() -> None:
    """One value for the check and the teardown. The gateway reads it as a module global when it
    writes the close row (`test_lifecycle_socket` patches it there), so a literal in its place
    would break that test."""
    assert vars(gateway)["CLOSE_AUDIT_TIMEOUT_S"] == CLOSE_AUDIT_TIMEOUT_S == 2.0


async def test_the_supervisor_cuts_a_hung_stop_at_its_grace_plus_the_shared_slack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The slack in the budget's sum is the one `_stop_each` spends (patched small to run fast)."""
    monkeypatch.setattr("candleviewer.app.STOP_SLACK_S", 0.1)

    class _Hung:
        async def stop(self, grace_s: float) -> None:
            await asyncio.Event().wait()

    loop = asyncio.get_running_loop()
    started = loop.time()
    supervisor = Supervisor(cast(AppContext, SimpleNamespace(audit=_Hung())))
    await supervisor._stop_each(["audit"], 0.05)
    # The grace plus the patched slack. The ceiling is generous (0.8 s of scheduling slack) and
    # still excludes a literal 1 s slack in `_stop_each`, which would end no earlier than 1.05 s.
    assert 0.15 <= loop.time() - started < 0.95


def test_the_two_uvicorn_ticks_the_budget_counts_are_still_in_uvicorn() -> None:
    """`SHUTDOWN_TICKS_S` is two 0.1 s ticks of uvicorn's own: its main loop, and the settle
    sleep before the drain. A uvicorn upgrade that changes either must change the constant."""
    for method in (uvicorn.Server.main_loop, uvicorn.Server.shutdown):
        assert "asyncio.sleep(0.1)" in inspect.getsource(method)
    assert SHUTDOWN_TICKS_S == 0.2


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


def test_a_refused_setting_never_echoes_a_secret_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """C-12.6: the key reaches the process as an environment string, and a refusal must carry it
    in none of `str()`, `errors()` and `json()`. The check is a field validator on the drain
    (#2728's precedent), so its error's input is that one value and not every setting; #2778
    tracks the model validators that still echo them all."""
    probe = "NOT-A-REAL-KEY-ECHO-PROBE"
    monkeypatch.setenv("CV_BYBIT_API_KEY", probe)
    monkeypatch.setenv("CV_WS_SHUTDOWN_GRACE_MS", "60000")
    with pytest.raises(ValidationError) as err:
        Settings()
    assert "CV_API_STOP_BUDGET_S" in str(err.value)  # the probed refusal is the budget check
    for rendered in (str(err.value), repr(err.value.errors()), err.value.json()):
        assert probe[:6] not in rendered
    assert "input_value" not in str(err.value)
    assert [e["input"] for e in err.value.errors()] == [5]  # the drain timeout, and nothing else
