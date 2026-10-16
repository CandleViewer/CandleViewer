"""#2893 S2: the composition root's one door to the dev-only account fixture transport.

`CV_ACCOUNT_FIXTURE` selects a stub exchange transport for the E27 fault-injection pack. Its code
is the `cvdev.account_fixture` package, a sibling of `candleviewer` that is never packaged and
never copied into an image (ruling 1). This module is the only one that names it, and it imports
it lazily, only when the variable is set: unset, nothing is imported and nothing changes. A build
without the package refuses boot instead of ignoring the variable (fail closed). `Settings` has
already refused the variable outside dev/test (ruling 2), and the package re-checks that.

S4 threads the handle into the exchange adapter's account REST clients and private socket. Until
the guard and serving slices land, the package's transport and connector refuse every request.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from typing import Final, Protocol

import httpx
import structlog

from candleviewer.settings import Settings

#: The dev-only entry point: a module exposing `build(settings) -> AccountFixture`.
_DEV_WIRING: Final = "cvdev.account_fixture.wiring"
NO_FIXTURE_TRANSPORT: Final = (
    "CV_ACCOUNT_FIXTURE is set but this build carries no fixture transport"
)


class AccountFixtureRefused(RuntimeError):
    """The account fixture transport may not run in this process, so boot stops (fail closed)."""


class AccountFixture(Protocol):
    """What the dev-only package hands the composition root: the transport of the account REST
    clients (`BybitRestClient(transport=...)`) and the private socket's zero-argument connector,
    both threaded into the exchange adapter by S4."""

    @property
    def rest_transport(self) -> httpx.AsyncBaseTransport: ...

    @property
    def private_ws_connect(self) -> Callable[[], Awaitable[object]]: ...


def build_account_fixture(settings: Settings) -> AccountFixture | None:
    """The fixture handle for `create_app()`: None unless `CV_ACCOUNT_FIXTURE` is set.

    Raises `AccountFixtureRefused` when the dev package is absent (a release image) or refuses
    these settings. When on, it writes a boot warning, so fixture mode never runs silently."""
    scenario = settings.account_fixture
    if scenario is None:
        return None
    try:
        module = importlib.import_module(_DEV_WIRING)
    except ModuleNotFoundError as exc:
        raise AccountFixtureRefused(NO_FIXTURE_TRANSPORT) from exc
    build: Callable[[Settings], AccountFixture] = module.build
    fixture = build(settings)
    structlog.get_logger(__name__).warning(
        "exchange.account_fixture_enabled",
        environment=settings.environment.value,
        scenario=scenario,
        fixture_dir=settings.account_fixture_dir,
        detail="the dev-only account fixture transport stands in for the exchange",
    )
    return fixture
