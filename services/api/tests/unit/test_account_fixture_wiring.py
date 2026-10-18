"""#2893 S2: the fail-closed, dev-only loader of the account fixture transport (ruling 1).

`candleviewer.account_fixture_wiring` is the one door to the dev-only `cvdev` package. It imports
the package only when `CV_ACCOUNT_FIXTURE` is set, and a build without it (a release image) refuses
boot instead of ignoring the variable. Until the guard and serving slices land, the REST transport
and the private-socket connector refuse every request, so nothing is ever answered unguarded. S4:
the composition root builds the exchange adapter's key-verification clients on the handle's REST
transport, and a default build passes none.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from structlog.testing import capture_logs

from candleviewer import account_fixture_wiring as wiring_module
from candleviewer import app as app_module
from candleviewer.account_fixture_wiring import (
    NO_FIXTURE_TRANSPORT,
    AccountFixtureRefused,
    build_account_fixture,
)
from candleviewer.exchange.base.errors import TransportError
from candleviewer.exchange.bybit import key_verify
from candleviewer.exchange.bybit import key_ws_probe as private_ws
from candleviewer.exchange.bybit import service as bybit_service
from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.observability.support_bundle import filter_config
from candleviewer.settings import Environment, FeedMode, Settings
from cvdev.account_fixture.wiring import RefusingTransport
from cvdev.account_fixture.wiring import build as dev_build

_SCENARIO = "compliant"
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


def _dev_modules() -> list[str]:
    return [n for n in sys.modules if n == "cvdev" or n.startswith("cvdev.")]


def _forget_the_dev_package(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every imported `cvdev` module for this test, so an import shows up again."""
    for name in _dev_modules():
        monkeypatch.delitem(sys.modules, name)


def _dev(tmp_path: Path) -> Settings:
    return Settings(
        environment=Environment.DEMO,
        feed=FeedMode.SYNTHETIC,
        account_fixture=_SCENARIO,
        account_fixture_dir=str(tmp_path / "account-fixture"),
    )


def test_unset_is_none_and_silent() -> None:
    with capture_logs() as logs:
        built = build_account_fixture(Settings())

    assert (built, logs) == (None, [])


def test_unset_imports_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    _forget_the_dev_package(monkeypatch)

    app = app_module.create_app(Settings())

    assert app.state.account_fixture is None
    assert not _dev_modules()


def test_set_without_dev_package_refuses_boot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A release image carries no `cvdev`: a set variable stops boot, before any module is built,
    instead of being ignored (fail closed)."""
    _forget_the_dev_package(monkeypatch)
    monkeypatch.setitem(sys.modules, "cvdev", None)  # the import system's "no such module"

    def _never(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("modules were built before the fixture refusal")

    monkeypatch.setattr(app_module, "build_app_context", _never)

    with pytest.raises(AccountFixtureRefused, match=re.escape(NO_FIXTURE_TRANSPORT)) as refused:
        app_module.create_app(_dev(tmp_path))

    assert isinstance(refused.value.__cause__, ModuleNotFoundError)


@pytest.mark.parametrize(
    ("missing", "absent"),
    [
        ("cvdev", True),
        ("cvdev.account_fixture.wiring", True),
        ("cvdevtools", False),
        ("cv_2893_missing_dependency", False),
        (None, False),
    ],
)
def test_only_a_missing_dev_package_reads_as_no_fixture_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, missing: str | None, absent: bool
) -> None:
    """A dependency the dev package misses is a broken checkout, not a release build: it is
    raised as is, so the boot still stops but the message names the real cause."""

    def _import_module(name: str, package: str | None = None) -> ModuleType:
        raise ModuleNotFoundError(f"no module named {missing!r}", name=missing)

    monkeypatch.setattr(wiring_module, "importlib", SimpleNamespace(import_module=_import_module))

    with pytest.raises((AccountFixtureRefused, ModuleNotFoundError)) as refused:
        build_account_fixture(_dev(tmp_path))

    assert isinstance(refused.value, AccountFixtureRefused) is absent
    assert (str(refused.value) == NO_FIXTURE_TRANSPORT) is absent


async def test_set_in_checkout_builds_a_transport_that_refuses_everything(
    tmp_path: Path,
) -> None:
    fixture = build_account_fixture(_dev(tmp_path))
    assert fixture is not None
    config = RestClientConfig(base_url="https://api-demo.bybit.com", max_retries=0)

    async with BybitRestClient(config, transport=fixture.rest_transport) as client:
        with pytest.raises(TransportError) as refused:
            await client.get_public("/v5/market/time")

    assert isinstance(refused.value.__cause__, httpx.ConnectError)


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("GET", "https://api-demo.bybit.com/v5/user/query-api"),
        ("POST", "https://api-demo.bybit.com/v5/order/create"),
        ("GET", "https://api.bybit.com/v5/account/wallet-balance"),
        ("GET", "https://api-testnet.bybit.com/v5/market/time"),
    ],
    ids=["demo-key-info", "demo-order", "live", "testnet"],
)
async def test_the_transport_never_answers_any_host(tmp_path: Path, method: str, url: str) -> None:
    fixture = build_account_fixture(_dev(tmp_path))
    assert fixture is not None

    with pytest.raises(httpx.ConnectError):
        await fixture.rest_transport.handle_async_request(httpx.Request(method, url))


async def test_the_private_socket_connector_refuses_every_dial(tmp_path: Path) -> None:
    fixture = build_account_fixture(_dev(tmp_path))
    assert fixture is not None

    with pytest.raises(ConnectionRefusedError):
        await fixture.private_ws_connect("wss://stream-demo.bybit.com/v5/private")


def test_the_adapter_dials_with_productions_connector_or_behind_the_door_the_handles(
    tmp_path: Path,
) -> None:
    """#836 slice 2b5: the adapter's private-WS `auth` probe dials with production's own connector
    unless the door's handle supplies one, which refuses every dial until S12."""
    default = app_module.create_app(Settings()).state.app_context.exchange_bybit
    app = app_module.create_app(_dev(tmp_path))
    fixture = app.state.app_context.exchange_bybit
    assert default._ws_probe._connect is private_ws.connect_private_ws
    assert fixture._ws_probe._connect is app.state.account_fixture.private_ws_connect


@pytest.mark.parametrize("environment", [Environment.DEMO, Environment.TESTNET])
def test_the_composition_root_gives_the_adapter_the_process_environment(
    environment: Environment,
) -> None:
    """#836 slice 2b5: the adapter's private-WS probe dials only the stream of the process's own
    environment, the one whose keys M2 signs (C-2.11)."""
    context = app_module.build_app_context(Settings(environment=environment))
    assert context.exchange_bybit._environment == environment.value


def test_set_in_checkout_create_app_keeps_the_handle_for_later_slices(tmp_path: Path) -> None:
    app = app_module.create_app(_dev(tmp_path))

    assert app.state.account_fixture is not None


_ABSENT = object()


def _client_transports(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """The `transport` each key-verification client is built with (`_ABSENT`: none passed)."""
    seen: list[object] = []
    real = key_verify.BybitRestClient

    def spy(*args: Any, **kwargs: Any) -> BybitRestClient:
        seen.append(kwargs.get("transport", _ABSENT))
        return real(*args, **kwargs)

    monkeypatch.setattr(key_verify, "BybitRestClient", spy)
    return seen


async def _build_a_verification_client(app: FastAPI) -> None:
    exchange = app.state.app_context.exchange_bybit
    calls = exchange.key_verification_calls("demo", UUID(int=1), uid="1", recv_window_ms=5000)
    await calls.aclose()


async def test_unset_the_adapter_builds_its_verification_clients_with_transport_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S4 (hcl-worker-1's ask 3): a default build passes `transport=None`, so httpx keeps its own
    transport, and nothing from the dev package is imported."""
    _forget_the_dev_package(monkeypatch)
    seen = _client_transports(monkeypatch)

    await _build_a_verification_client(app_module.create_app(Settings()))

    assert (seen, _dev_modules()) == ([None], [])


async def test_set_the_adapter_builds_its_verification_clients_on_the_fixture_transport(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """S4: the transport comes only from the door's handle, through a view that never closes it;
    until the serving slice it refuses every request."""
    seen = _client_transports(monkeypatch)
    app = app_module.create_app(_dev(tmp_path))

    await _build_a_verification_client(app)

    (view,) = seen
    assert isinstance(view, bybit_service._NonClosingTransport)
    assert view._transport is app.state.account_fixture.rest_transport
    assert isinstance(view._transport, RefusingTransport)


def test_set_logs_a_boot_warning(tmp_path: Path) -> None:
    """The fixture never runs silently (the #2086 test clock's precedent)."""
    with capture_logs() as logs:
        build_account_fixture(_dev(tmp_path))

    assert [(e["event"], e["log_level"], e["scenario"], e["environment"]) for e in logs] == [
        ("exchange.account_fixture_enabled", "warning", _SCENARIO, "demo")
    ]


_KEYS = {"bybit_api_key": SecretStr("k"), "bybit_api_secret": SecretStr("s")}
_SKIPPED_VALIDATION = pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"environment": Environment.LIVE}, "unless CV_ENVIRONMENT=demo"),
        ({"environment": Environment.TESTNET}, "unless CV_ENVIRONMENT=demo"),
        # `model_post_init` still runs: a live feed without both keys never constructs.
        ({"feed": FeedMode.LIVE, **_KEYS}, "unless CV_FEED=synthetic"),
        ({"bybit_api_key": _KEYS["bybit_api_key"]}, "while any CV_BYBIT_API_* variable"),
        ({"bybit_api_secret": _KEYS["bybit_api_secret"]}, "while any CV_BYBIT_API_* variable"),
        ({"test_clock": True}, "while CV_TEST_CLOCK is on"),
        ({"account_fixture": "../x"}, "must be a scenario token"),
    ],
    ids=["live", "testnet", "live-feed", "api-key", "api-secret", "test-clock", "not-a-token"],
)


@_SKIPPED_VALIDATION
def test_the_loader_refuses_skipped_validation_before_importing_the_dev_package(
    monkeypatch: pytest.MonkeyPatch, fields: dict[str, Any], reason: str
) -> None:
    """The shipped side enforces the gate itself, so it never depends on `cvdev` to refuse."""
    _forget_the_dev_package(monkeypatch)
    settings = Settings.model_construct(**{"account_fixture": _SCENARIO, **fields})

    with pytest.raises(AccountFixtureRefused, match=re.escape(reason)):
        build_account_fixture(settings)

    assert not _dev_modules()


@_SKIPPED_VALIDATION
def test_the_dev_package_rechecks_settings_that_skipped_validation(
    fields: dict[str, Any], reason: str
) -> None:
    settings = Settings.model_construct(**{"account_fixture": _SCENARIO, **fields})

    with pytest.raises(AccountFixtureRefused, match=re.escape(reason)):
        dev_build(settings)


def test_a_support_bundle_shows_fixture_mode() -> None:
    assert filter_config({"CV_ACCOUNT_FIXTURE": _SCENARIO}) == {"CV_ACCOUNT_FIXTURE": _SCENARIO}
