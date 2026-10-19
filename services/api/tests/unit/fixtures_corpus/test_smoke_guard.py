"""E08-T05: the exchange_smoke demo-only guard fails closed (negative tests).

Runs in the default lane (it is NOT under tests/exchange_smoke/, dials nothing).
"""

from __future__ import annotations

import importlib.util
import os
import socket
import tomllib
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import pytest

from tests.exchange_smoke._guard import DEMO_HOSTS, SmokeGuardError, assert_demo_only, opted_in

_API = Path(__file__).resolve().parents[3]
_REPO = _API.parents[1]
_SMOKE_CONFTEST = _API / "tests" / "exchange_smoke" / "conftest.py"


@pytest.mark.parametrize(
    "env",
    [
        {"CV_ENVIRONMENT": "live"},
        {"CV_SMOKE_ENV": "mainnet"},
        {"CV_BYBIT_REST_BASE_URL": "https://api.bybit.com"},
        {"CV_BYBIT_WS_URL": "wss://stream.bybit.com/v5/private?env=live"},
        {"CV_BYBIT_API_KEY": "DUMMYKEY_not_a_real_key"},
    ],
)
def test_smoke_guard_live_configuration_fails_fast_with_explicit_error(
    env: dict[str, str],
) -> None:
    with pytest.raises(SmokeGuardError, match=r"demo-only|no credentials"):
        assert_demo_only({"CV_EXCHANGE_SMOKE": "1", **env})


def test_smoke_guard_demo_configuration_passes() -> None:
    assert_demo_only(
        {
            "CV_EXCHANGE_SMOKE": "1",
            "CV_ENVIRONMENT": "demo",
            "CV_BYBIT_REST_BASE_URL": "https://api-demo.bybit.com/",
        }
    )


def test_smoke_suite_is_opt_in() -> None:
    assert not opted_in({})
    assert not opted_in({"CV_EXCHANGE_SMOKE": "true"})
    assert opted_in({"CV_EXCHANGE_SMOKE": "1"})


def test_default_ci_job_deselects_exchange_smoke() -> None:
    lane = (_REPO / ".github" / "workflows" / "_job-py.yml").read_text(encoding="utf-8")
    assert '-m "not exchange_smoke' in lane
    markers = tomllib.loads((_API / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(
        m.startswith("exchange_smoke:") for m in markers["tool"]["pytest"]["ini_options"]["markers"]
    )


def test_every_smoke_test_carries_the_marker() -> None:
    src = (_API / "tests" / "exchange_smoke" / "test_demo_smoke.py").read_text(encoding="utf-8")
    assert "pytestmark = pytest.mark.exchange_smoke" in src


@pytest.mark.parametrize(
    ("env", "looked_up", "aborts"),
    [
        pytest.param({}, (), False, id="unset"),
        pytest.param({"CV_EXCHANGE_SMOKE": "1"}, DEMO_HOSTS, False, id="demo"),
        pytest.param({"CV_EXCHANGE_SMOKE": "1", "CV_ENVIRONMENT": "live"}, (), True, id="live"),
    ],
)
def test_smoke_conftest_resolves_the_demo_hosts_at_import_only_when_opted_in_on_demo(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str], looked_up: tuple[str, ...], aborts: bool
) -> None:
    for key in [k for k in os.environ if k.upper().startswith("CV_")]:
        monkeypatch.delenv(key)  # a clean configuration: no CV_* variable but those in `env`
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    seen: list[object] = []

    def resolver(host: object, *_args: object, **_kwargs: object) -> list[Any]:
        seen.append(host)  # stands in for the unguarded resolver: nothing leaves the machine
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.10", 443))]

    monkeypatch.setattr(socket, "getaddrinfo", resolver)
    spec = importlib.util.spec_from_file_location("cv_smoke_conftest_probe", _SMOKE_CONFTEST)
    assert spec is not None and spec.loader is not None
    conftest = importlib.util.module_from_spec(spec)
    with pytest.raises(SmokeGuardError) if aborts else nullcontext():
        spec.loader.exec_module(conftest)  # a fresh import, as collection runs it before the guard
    assert tuple(seen) == looked_up  # unset, or live-looking: the early resolution never runs
    assert getattr(conftest, "DEMO_IPS", frozenset()) == ({"192.0.2.10"} if looked_up else set())
