"""#2893 S2: the entry point of the account fixture transport.

`candleviewer.account_fixture_wiring` imports this module only when `CV_ACCOUNT_FIXTURE` is set.
`build` re-checks the dev/test gate that `Settings` enforced at load (ruling 2), as
`build_test_clock` does, so settings that skipped validation never reach a transport. The REST
transport and the private-socket connector it returns refuse every request, as a closed port
would: no reply is ever produced, so nothing is served before the host, key-id and signature
guards land. `guard_boot` is the boot guard (S8, `boot.run`), named here so this module stays the
package's one entry point. Nothing here imports `candleviewer.secrets`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, NoReturn

import httpx

from candleviewer.account_fixture_wiring import (
    AccountFixture,
    AccountFixtureAudit,
    AccountFixtureRefused,
)
from candleviewer.settings import Settings
from cvdev.account_fixture import boot

#: Why every request is refused for now.
REFUSAL: Final = "the account fixture transport answers nothing until its guards land (#2893)"


class RefusingTransport(httpx.AsyncBaseTransport):
    """Never answers: every request raises `httpx.ConnectError`, an httpx transport error."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(REFUSAL, request=request)


async def refuse_private_socket() -> NoReturn:
    """Never connects: every dial raises `ConnectionRefusedError`, as a closed port does."""
    raise ConnectionRefusedError(REFUSAL)


@dataclass(frozen=True, slots=True)
class _Fixture:
    rest_transport: httpx.AsyncBaseTransport
    private_ws_connect: Callable[[], Awaitable[object]]


def build(settings: Settings) -> AccountFixture:
    """The fixture handle; `AccountFixtureRefused` unless the settings are dev/test."""
    refusal = settings.account_fixture_refusal()
    if refusal is not None:
        raise AccountFixtureRefused(refusal)
    return _Fixture(rest_transport=RefusingTransport(), private_ws_connect=refuse_private_socket)


async def guard_boot(settings: Settings, audit: AccountFixtureAudit | None) -> None:
    """The boot guard (`boot.run`): refuses boot by raising, or passes and writes the record."""
    await boot.run(settings, audit)
