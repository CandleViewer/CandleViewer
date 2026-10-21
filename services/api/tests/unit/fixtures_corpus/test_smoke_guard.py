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
        {"CV_INGEST_REST_URL": "https://api.bybit.com/v5/market/time"},  # not `CV_BYBIT*` (#1849)
        {"CV_UPSTREAM_HOST": "api.bytick.com:443"},  # a bare host
        {"CV_CI_ALLOWED_HOSTS": "api-demo.bybit.com,api.bybit.com"},  # a list
        {"CV_FEED_CONFIG": '{"rest": "api.bybit.eu"}'},  # JSON, a regional live host
        {"CV_INGEST_REST_URL": "https://api-testnet.bybit.com"},  # testnet is not demo either
        {"CV_BYBIT_ACCOUNT_LABEL": "live-desk"},  # a `CV_BYBIT*` value is read whatever its shape
        {"CV_PUBLIC_WS_URL": "wss://stream-testnet.bybit.com/v5/public/linear"},  # testnet stream
        {"CV_INGEST_REST_URL": "https://\uff41pi.bybit.com"},  # a fullwidth letter (NFKC)
        {"CV_INGEST_REST_URL": "https://api.by\u200bbit.com"},  # a zero-width space
        {"CV_INGEST_REST_URL": "https://api-test\u00adnet.bybit.com"},  # a soft hyphen
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


@pytest.mark.parametrize(
    "env",
    [
        {"CV_RELEASE_CHANNEL": "production"},  # a word in no URL is not read
        {"CV_SETTINGS_FILE": "settings.prod.yaml"},  # nor in a file name
        {"CV_PUBLIC_WS_URL": "wss://stream.bybit.com/v5/public/linear"},  # demo's public stream
        {"CV_DEMO_REST_URL": "https://api-demo.bybit.com"},
    ],
)
def test_smoke_guard_cv_value_naming_no_live_host_passes(env: dict[str, str]) -> None:
    assert_demo_only({"CV_EXCHANGE_SMOKE": "1", **env})


# Each scheme is a separate literal, so the secret scanners never read a whole credentialed URL
# in this file and it stays scanned (`docs/ci-runbook.md`, #3482).
@pytest.mark.parametrize(
    "env",
    [
        {"CV_BYBIT_REST_BASE_URL": "https" + "://reader:s3cret@api.bybit.com"},
        {"CV_INGEST_REST_URL": "https" + "://reader:s3cret@api.bybit.com/v5"},
        {"CV_PUBLIC_WS_URL": "wss" + "://reader:s3cret@example.com/live"},
        {"CV_ENVIRONMENT": "s3cret"},  # an environment name set to something it should not be
    ],
)
def test_smoke_guard_error_names_the_variable_never_its_value(env: dict[str, str]) -> None:
    """A URL may carry a password, and the error reaches the CI log."""
    with pytest.raises(SmokeGuardError) as refused:
        assert_demo_only({"CV_EXCHANGE_SMOKE": "1", **env})
    (name,) = env
    assert name in str(refused.value) and "s3cret" not in str(refused.value)


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


@pytest.mark.parametrize(
    "env",
    [
        pytest.param({"CV_ENVIRONMENT": "live"}, id="environment"),
        pytest.param({"CV_BYBIT_REST_BASE_URL": "https://api.bybit.com"}, id="rest-base"),
        pytest.param({"CV_INGEST_REST_URL": "https://api.bybit.com/v5/market/time"}, id="cv-url"),
    ],
)
def test_smoke_conftest_live_configuration_aborts_before_any_lookup_or_socket(
    monkeypatch: pytest.MonkeyPatch, env: dict[str, str]
) -> None:
    """#1849: the abort comes first; no name is looked up and no socket is built before it."""
    for key in [k for k in os.environ if k.upper().startswith("CV_")]:
        monkeypatch.delenv(key)
    for key, value in {"CV_EXCHANGE_SMOKE": "1", **env}.items():
        monkeypatch.setenv(key, value)
    reached: list[str] = []

    def refused(name: str) -> Any:
        def call(*_args: object, **_kwargs: object) -> Any:
            reached.append(name)
            raise AssertionError(f"{name} ran before the demo-only guard")

        return call

    for name in ("getaddrinfo", "gethostbyname", "socket"):
        monkeypatch.setattr(socket, name, refused(name))
    spec = importlib.util.spec_from_file_location("cv_smoke_conftest_live", _SMOKE_CONFTEST)
    assert spec is not None and spec.loader is not None
    with pytest.raises(SmokeGuardError, match="demo-only"):
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
    assert reached == []
