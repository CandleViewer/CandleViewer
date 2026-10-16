"""#2893 S2: the fail-closed, dev-only loader of the account fixture transport (ruling 1).

`candleviewer.account_fixture_wiring` is the one door to the dev-only `cvdev` package. It imports
the package only when `CV_ACCOUNT_FIXTURE` is set, and a build without it (a release image) refuses
boot instead of ignoring the variable. Until the guard and serving slices land, the REST transport
and the private-socket connector refuse every request, so nothing is ever answered unguarded.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs

from candleviewer import app as app_module
from candleviewer.account_fixture_wiring import (
    NO_FIXTURE_TRANSPORT,
    AccountFixtureRefused,
    build_account_fixture,
)
from candleviewer.exchange.base.errors import TransportError
from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.observability.support_bundle import filter_config
from candleviewer.settings import Environment, FeedMode, Settings

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


def _forget_the_dev_package(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every imported `cvdev` module for this test, so an import shows up again."""
    for name in [n for n in sys.modules if n == "cvdev" or n.startswith("cvdev.")]:
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
    assert not [n for n in sys.modules if n == "cvdev" or n.startswith("cvdev.")]


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
        await fixture.private_ws_connect()


def test_set_in_checkout_create_app_keeps_the_handle_for_later_slices(tmp_path: Path) -> None:
    app = app_module.create_app(_dev(tmp_path))

    assert app.state.account_fixture is not None


def test_set_logs_a_boot_warning(tmp_path: Path) -> None:
    """The fixture never runs silently (the #2086 test clock's precedent)."""
    with capture_logs() as logs:
        build_account_fixture(_dev(tmp_path))

    assert [(e["event"], e["log_level"], e["scenario"], e["environment"]) for e in logs] == [
        ("exchange.account_fixture_enabled", "warning", _SCENARIO, "demo")
    ]


_KEYS = {"bybit_api_key": SecretStr("k"), "bybit_api_secret": SecretStr("s")}


@pytest.mark.parametrize(
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
def test_the_dev_package_rechecks_settings_that_skipped_validation(
    fields: dict[str, Any], reason: str
) -> None:
    settings = Settings.model_construct(**{"account_fixture": _SCENARIO, **fields})

    with pytest.raises(AccountFixtureRefused, match=re.escape(reason)):
        build_account_fixture(settings)


def test_a_support_bundle_shows_fixture_mode() -> None:
    assert filter_config({"CV_ACCOUNT_FIXTURE": _SCENARIO}) == {"CV_ACCOUNT_FIXTURE": _SCENARIO}
