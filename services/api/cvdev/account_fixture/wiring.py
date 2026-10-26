"""#2893 S2, S12b: the entry point of the account fixture transport.

`candleviewer.account_fixture_wiring` imports this module only when `CV_ACCOUNT_FIXTURE` is set.
`build` re-checks the dev/test gate that `Settings` enforced at load (ruling 2), as
`build_test_clock` does, and returns a `FixtureDoor`: the REST transport and private-socket
connector the exchange adapter keeps. They refuse every request, as a closed port would, until
`guard_boot` (the boot guard, S8's `boot.run`) has passed: `arm` takes that pass's record, so
nothing builds the pair unguarded. Then, before any module starts, it builds the pair behind them
once a process (`guards.BUILD_ONCE`): one fixture clock, `KeyStates` and `RequestLog`, one
`FixtureTransport` on the process's guard latch (`guards.LATCH`) and read-only gate, and one
`FixtureSockets` on that transport. A second or failed build refuses boot with a fixed message that
names no path; so does a switched-on boot whose guard is handed no handle, since the adapter would
then keep its real transport and socket. The fixture clock goes to the stub alone; the adapter
keeps signing on real time. Nothing here imports `candleviewer.secrets` or `candleviewer.audit`.
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
UNGUARDED: Final = _REFUSED + "the fixture pair is built only on its boot guard's passed record"


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


class _Handoff:
    """`_built`'s request log, handed back across the thread. If the awaiter is gone (a cancel of
    boot during the build), whichever side comes last closes it, so no descriptor outlives the
    abandoned pair. The state files it made stay, as after any failed build: boot is aborting."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gone = False
        self._log: RequestLog | None = None

    def keep(self, log: RequestLog) -> bool:
        """In the thread, once the pair is built: whether the awaiter still takes it."""
        with self._lock:
            if not self._gone:
                self._log = log
                return True
        log.close()
        return False

    def abandon(self) -> None:
        """On the loop, when the await ends in an exception: the awaiter takes nothing."""
        with self._lock:
            self._gone, log, self._log = True, self._log, None
        if log is not None:
            log.close()


class FixtureDoor:
    """`create_app()`'s handle (`AccountFixture`): the same transport and connector objects for the
    life of the process, refusing until `arm` builds the pair behind them."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._armed: Armed | None = None
        self.rest_transport: Final = _DoorTransport(self)
        self.private_ws_connect: Final[Callable[[str], Awaitable[PrivateSocket]]] = self._dial

    def lane_rest_transport(self) -> httpx.AsyncBaseTransport:
        """A new refusing transport for the order lane's loop at each call (#913 L1d)."""
        return RefusingTransport()

    @property
    def armed(self) -> Armed | None:
        """The pair, once built; only `arm` sets it. Its request log lives for the process."""
        return self._armed

    async def _dial(self, url: str) -> PrivateSocket:
        armed = self._armed
        if armed is None:
            await refuse_private_socket(url)
        return await armed.sockets.connect(url)

    async def arm(self, passed: boot.Passed, gate: ReadOnlyLatch, pack: Pack) -> None:
        """Build the pair on `pack` and `gate`, once a process, off the event loop. `passed` is the
        boot guard's record on that pack: only `guard_boot` holds one to hand over."""
        if not isinstance(passed, boot.Passed):
            raise AccountFixtureRefused(UNGUARDED)
        if not guards.BUILD_ONCE.acquire(blocking=False):
            raise AccountFixtureRefused(BUILT_ONCE)
        refusal = self._settings.account_fixture_refusal()
        if refusal is not None:
            raise AccountFixtureRefused(refusal)
        handoff = _Handoff()
        try:
            armed = await asyncio.to_thread(_built, self._settings, gate, pack, handoff)
        except BaseException:
            handoff.abandon()
            raise
        if armed is None:  # no cause and, even inside a caller's `except`, no context or path
            raise AccountFixtureRefused(BUILD_REFUSAL) from None
        self._armed = armed


def _built(settings: Settings, gate: ReadOnlyLatch, pack: Pack, handoff: _Handoff) -> Armed | None:
    """The pair, or None; the error's type is logged, never its text. The request log is closed
    again if anything after it fails, or if `handoff` says the awaiter is gone; a
    `BaseException` (a cancel) propagates."""
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
            armed = Armed(transport, FixtureSockets(transport))
        except BaseException:
            log.close()
            raise
        return armed if handoff.keep(log) else None
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
    A handle it cannot build, or none (the adapter would keep its real transport and socket),
    refuses boot before the guard reads anything."""
    if not isinstance(fixture, FixtureDoor) or gate is None:
        raise AccountFixtureRefused(NOT_BUILDABLE)
    pack = Pack(account_pack.PACK_ROOT)
    passed = await boot.run(settings, pack=pack)
    await fixture.arm(passed, gate, pack)
    return passed
