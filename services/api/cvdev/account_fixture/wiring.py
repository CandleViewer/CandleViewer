"""#2893 S2, S12b: the entry point of the account fixture transport.

`candleviewer.account_fixture_wiring` imports this module only when `CV_ACCOUNT_FIXTURE` is set.
`build` re-checks the dev/test gate that `Settings` enforced at load (ruling 2), as
`build_test_clock` does, and returns a `FixtureDoor`: the REST transport and private-socket
connector the exchange adapter keeps. They refuse every request, as a closed port would, until
`guard_boot` (the boot guard, S8's `boot.run`) has passed. Then, before any module starts, it builds
the pair behind them once a process: one fixture clock, `KeyStates` and `RequestLog`, one
`FixtureTransport` on the process's guard latch (`guards.LATCH`) and read-only gate, and one
`FixtureSockets` on that transport. A second or failed build refuses boot with a fixed message that
names no path. The fixture clock goes to the stub alone; the adapter keeps signing on real time.
Nothing here imports `candleviewer.secrets` or `candleviewer.audit`.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, NoReturn

import httpx
import structlog

from candleviewer.account_fixture_wiring import AccountFixture, AccountFixtureRefused, PrivateSocket
from candleviewer.settings import Settings
from cvdev.account_fixture import boot, guards
from cvdev.account_fixture import pack as account_pack
from cvdev.account_fixture.control import FixtureClock, KeyStates
from cvdev.account_fixture.pack import Pack, fixture_key_ids
from cvdev.account_fixture.private_ws import FixtureSockets
from cvdev.account_fixture.requestlog import RequestLog
from cvdev.account_fixture.transport import FixtureTransport, ReadOnlyLatch

#: The process's one key-id guard latch (`guards.LATCH`, the same object), the built pair's.
LATCH: Final = guards.LATCH
REFUSAL: Final = "the account fixture answers nothing until its boot guard has passed (#2893)"
_REFUSED: Final = "CV_ACCOUNT_FIXTURE refuses boot: "
BUILD_REFUSAL: Final = _REFUSED + "the fixture pair could not be built from its pack and dir"
BUILT_ONCE: Final = _REFUSED + "the fixture pair is built once a process"
NOT_BUILDABLE: Final = _REFUSED + "the boot guard needs this package's door and the read-only gate"
#: Taken by the process's one build and never released: a second build, or a retry, refuses.
_ONCE: Final = threading.Lock()


class RefusingTransport(httpx.AsyncBaseTransport):
    """Never answers: every request raises `httpx.ConnectError`, an httpx transport error."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(REFUSAL, request=request)


async def refuse_private_socket(_url: str) -> NoReturn:
    """Never connects: every dial raises `ConnectionRefusedError`, as a closed port does."""
    raise ConnectionRefusedError(REFUSAL)


@dataclass(frozen=True, slots=True)
class Armed:
    """The process's one fixture pair: the transport, and the socket connector built on it."""

    transport: FixtureTransport
    sockets: FixtureSockets


class _DoorTransport(RefusingTransport):
    """The adapter's REST transport: refusing until the door is built, then the pair's."""

    def __init__(self, door: FixtureDoor) -> None:
        self._door = door

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        armed = self._door.armed
        if armed is None:
            return await super().handle_async_request(request)
        return await armed.transport.handle_async_request(request)


class FixtureDoor:
    """`create_app()`'s handle (`AccountFixture`): the same transport and connector objects for the
    life of the process, refusing until `arm` builds the pair behind them."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        #: The pair, once built; only `arm` sets it.
        self.armed: Armed | None = None
        self.rest_transport: Final = _DoorTransport(self)
        self.private_ws_connect: Final[Callable[[str], Awaitable[PrivateSocket]]] = self._dial

    async def _dial(self, url: str) -> PrivateSocket:
        if self.armed is None:
            await refuse_private_socket(url)
        return await self.armed.sockets.connect(url)

    async def arm(self, gate: ReadOnlyLatch, pack: Pack) -> None:
        """Build the pair on `pack` and `gate`, once a process, off the event loop. Only
        `guard_boot` calls it, once the boot guard passed on that pack."""
        if not _ONCE.acquire(blocking=False):
            raise AccountFixtureRefused(BUILT_ONCE)
        refusal = self._settings.account_fixture_refusal()
        if refusal is not None:
            raise AccountFixtureRefused(refusal)
        armed = await asyncio.to_thread(_built, self._settings, gate, pack)
        if armed is None:  # raised outside the handler: no cause, no context, no path
            raise AccountFixtureRefused(BUILD_REFUSAL)
        self.armed = armed


def _built(settings: Settings, gate: ReadOnlyLatch, pack: Pack) -> Armed | None:
    """The pair, or None; the error's type is logged, never its text. The request log is closed
    again if anything after it fails; a `BaseException` (a cancel) propagates."""
    directory, default = settings.account_fixture_dir, settings.account_fixture
    try:
        if directory is None or default is None:
            raise ValueError("the fixture needs CV_ACCOUNT_FIXTURE and CV_ACCOUNT_FIXTURE_DIR")
        clock = FixtureClock(directory)
        key_ids = fixture_key_ids(pack)
        log = RequestLog(
            directory, process_env=settings.environment, clock=clock, pack_key_ids=key_ids
        )
        try:
            keys = KeyStates(directory, pack, log=log, clock=clock)
            transport = FixtureTransport(
                pack, log=log, gate=gate, clock=clock, default=default, keys=keys, latch=LATCH
            )
            return Armed(transport, FixtureSockets(transport))
        except BaseException:
            log.close()
            raise
    except Exception as exc:
        structlog.get_logger(__name__).error(
            "exchange.account_fixture_build_refused", error=type(exc).__name__
        )
        return None


def build(settings: Settings) -> AccountFixture:
    """The fixture's door, closed; `AccountFixtureRefused` unless the settings are dev/test."""
    refusal = settings.account_fixture_refusal()
    if refusal is not None:
        raise AccountFixtureRefused(refusal)
    return FixtureDoor(settings)


async def guard_boot(
    settings: Settings, fixture: AccountFixture | None, gate: ReadOnlyLatch | None
) -> boot.Passed:
    """The boot guard (`boot.run`), before any module starts: refuses boot by raising, or passes,
    builds `fixture`'s pair on `gate` and the pack it checked, and hands back the boot record.
    Without a handle it only guards; one it cannot build refuses boot."""
    pack = Pack(account_pack.PACK_ROOT)
    passed = await boot.run(settings, pack=pack)
    if fixture is None:
        return passed
    if not isinstance(fixture, FixtureDoor) or gate is None:
        raise AccountFixtureRefused(NOT_BUILDABLE)
    await fixture.arm(gate, pack)
    return passed
