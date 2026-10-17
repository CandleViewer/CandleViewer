"""#2893 S2: the composition root's one door to the dev-only account fixture transport.

`CV_ACCOUNT_FIXTURE` selects a stub exchange transport for the E27 fault-injection pack. Its code
is the `cvdev.account_fixture` package, a sibling of `candleviewer` that is never packaged and
never copied into an image (ruling 1). This module is the only one that names it, and it imports
it lazily, only when the variable is set: unset, nothing is imported and nothing changes. A build
without the package refuses boot instead of ignoring the variable (fail closed). `Settings` has
already refused the variable outside dev/test (ruling 2); this module checks that again before it
imports anything, so the shipped side never relies on the dev package to refuse, and the package
re-checks it as well.

S4: `build_app_context` hands the handle's REST transport to the exchange adapter, which builds
every key-verification client on it; the private socket's connector waits for its own slice. Until
the guard and serving slices land, the package's transport and connector refuse every request.

S8: the lifespan awaits `account_fixture_guard`, the dev package's boot guard, before any module
starts, and `account_fixture_record` once they run: the guard's boot record goes through the audit
writer injected here, so `cvdev` never imports `candleviewer.audit`.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from types import ModuleType
from typing import Any, Final, Protocol

import httpx
import structlog

from candleviewer.settings import Settings

#: The dev-only package, and its entry point: a module exposing `build(settings) -> AccountFixture`
#: and (S8) the boot guard `guard_boot(settings) -> AccountFixtureBoot`, which refuses by raising.
_DEV_PACKAGE: Final = "cvdev"
_DEV_WIRING: Final = "cvdev.account_fixture.wiring"
#: S8 (FX-R01): one record per boot while the fixture is on, written once its guard passed.
ACCOUNT_FIXTURE_AUDIT_ACTION: Final = "system.config.account_fixture_enabled"
NO_FIXTURE_TRANSPORT: Final = (
    "CV_ACCOUNT_FIXTURE is set but this build carries no fixture transport"
)


class AccountFixtureRefused(RuntimeError):
    """The account fixture transport may not run in this process, so boot stops (fail closed)."""


class AccountFixture(Protocol):
    """What the dev-only package hands the composition root: the transport of the account REST
    clients (`BybitRestClient(transport=...)`, threaded into the exchange adapter by S4) and the
    private socket's zero-argument connector, which a later slice threads."""

    @property
    def rest_transport(self) -> httpx.AsyncBaseTransport: ...

    @property
    def private_ws_connect(self) -> Callable[[], Awaitable[object]]: ...


def build_account_fixture(settings: Settings) -> AccountFixture | None:
    """The fixture handle for `create_app()`: None unless `CV_ACCOUNT_FIXTURE` is set.

    Raises `AccountFixtureRefused` when the settings are not dev/test (checked before any import)
    or the dev package is absent (a release image). A module the dev package itself misses is a
    broken checkout, not a release build: that `ModuleNotFoundError` propagates as is, so boot
    still stops but names the real cause. When on, it writes a boot warning, so fixture mode never
    runs silently."""
    scenario = settings.account_fixture
    if scenario is None:
        return None
    build: Callable[[Settings], AccountFixture] = _dev_module(settings, _DEV_WIRING).build
    fixture = build(settings)
    structlog.get_logger(__name__).warning(
        "exchange.account_fixture_enabled",
        environment=settings.environment.value,
        scenario=scenario,
        fixture_dir=settings.account_fixture_dir,
        detail="the dev-only account fixture transport stands in for the exchange",
    )
    return fixture


class AccountFixtureAudit(Protocol):
    """The slice of `AuditWriter.emit` the boot record needs, injected into the dev package. C-3.3
    keeps this module from importing `candleviewer.audit`, hence `Any` for its enum parameters."""

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        object_kind: str | None = None,
        object_id: str | None = None,
        severity: Any = ...,
        env: Any = None,
        after_state: dict[str, Any] | None = None,
    ) -> None: ...


class _AuditModule(Protocol):
    @property
    def is_active(self) -> bool: ...

    @property
    def writer(self) -> AccountFixtureAudit: ...


class AccountFixtureBoot(Protocol):
    """A passed boot guard: `record` writes its boot record once the audit writer runs."""

    async def record(self, audit: AccountFixtureAudit) -> None: ...


async def account_fixture_guard(settings: Settings) -> AccountFixtureBoot | None:
    """#2893 S8, for the lifespan before any module starts: the dev package's boot guard refuses
    boot (`AccountFixtureRefused`) while the database holds a key the stub must never answer for;
    a pass logs a warning. Unset, it imports nothing and returns None."""
    if settings.account_fixture is None:
        return None
    guard: Callable[[Settings], Awaitable[AccountFixtureBoot]] = _dev_module(
        settings, _DEV_WIRING
    ).guard_boot
    return await guard(settings)


async def account_fixture_record(passed: AccountFixtureBoot | None, audit: _AuditModule) -> None:
    """#2893 S8, for the lifespan once the modules run, before the app serves: the passed guard's
    boot record, through the audit writer. The fake backend has none (`is_active` is False and
    `writer` raises), so there the guard's warning is the only record."""
    if passed is not None and audit.is_active:
        await passed.record(audit.writer)


def _dev_module(settings: Settings, name: str) -> ModuleType:
    """A module of the dev package, imported only after the dev/test gate is re-checked. A build
    without the package (a release image) refuses boot; a module the package itself misses is a
    broken checkout, so that `ModuleNotFoundError` propagates as is."""
    refusal = settings.account_fixture_refusal()
    if refusal is not None:
        raise AccountFixtureRefused(refusal)
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if not _names_the_dev_package(exc.name):
            raise
        raise AccountFixtureRefused(NO_FIXTURE_TRANSPORT) from exc


def _names_the_dev_package(module: str | None) -> bool:
    """Whether a failed import was `cvdev` itself or one of its modules, not a dependency."""
    return module is not None and (module == _DEV_PACKAGE or module.startswith(f"{_DEV_PACKAGE}."))
