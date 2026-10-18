"""E27-T04 (#837) rig for the account health runtime: the wired runtime on a fake clock and a fake
sleeper, plus a fake private socket, in one process and with no wall-clock wait."""

from __future__ import annotations

import asyncio
import heapq
import itertools
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from candleviewer.account_health_wiring import AccountHealthRuntime, wire_account_health
from candleviewer.accounts.service import AccountHealthFeed, AccountsService
from candleviewer.accounts.wallet import WalletSnapshot
from candleviewer.accounts.wallet_topic import WalletTopic
from candleviewer.observability.context import spawn
from candleviewer.observability.metrics import Metrics
from candleviewer.settings import Settings
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody
from tests.unit.accounts._fakes import ACC, Dms, FakeClock, Journal

#: `FakeClock` starts its boot-time clock here: a time minus this is seconds into the scenario.
START = 1_000.0
#: The private socket pings at half the heartbeat window (`ExchangeConfig.ws_ping_interval_s`).
PING_S = 5.0


def snapshot(updated_at: datetime) -> WalletSnapshot:
    return WalletSnapshot(
        coin="USDT",
        equity=Decimal("1000.50"),
        wallet_balance=Decimal("1000"),
        available_balance=Decimal("800.25"),
        unrealised_pnl=Decimal("0.50"),
        account_im_rate=Decimal("0.0125"),
        account_mm_rate=Decimal("0.005"),
        updated_at=updated_at,
    )


async def settle() -> None:
    """Let every ready task run until it waits again (the loops wait on the fake sleeper)."""
    for _ in range(80):
        await asyncio.sleep(0)


class Sleeper:
    """The loops' `sleep`: a sleeper wakes when `run()` moves the fake clock to its deadline, or
    raises `fail` if it is set (a loop that ends on it). With `stubborn` a cancelled sleep returns
    as if woken instead of raising the cancellation (a sleep that breaks its contract)."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.fail: Exception | None = None
        self.stubborn = False
        self._waiting: list[tuple[float, int, asyncio.Future[None]]] = []
        self._order = itertools.count()

    async def sleep(self, seconds: float) -> None:
        if self.fail is not None:
            raise self.fail
        wake = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiting, (self.clock.monotonic() + seconds, next(self._order), wake))
        try:
            await wake
        except asyncio.CancelledError:
            if not self.stubborn:
                raise

    async def run(self, seconds: float) -> None:
        """Move the fake time on by `seconds`, waking each sleeper at its own deadline."""
        end = self.clock.monotonic() + seconds
        await settle()
        while self._waiting and self._waiting[0][0] <= end:
            at, _, wake = heapq.heappop(self._waiting)
            self.clock.advance(at - self.clock.monotonic())
            if not wake.done():  # a cancelled sleeper is dropped
                wake.set_result(None)
            await settle()
        self.clock.advance(end - self.clock.monotonic())
        await settle()


class Rest:
    """The REST wallet port: a snapshot as of the fake wall clock, or `error` raised; `calls` holds
    the second of the scenario at which each read was made. A read waits until the `hold` event, if
    there is one, is set (a hung exchange); with `stubborn` it swallows every cancellation
    meanwhile (a port that breaks its contract)."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.hold: asyncio.Event | None = None
        self.stubborn = False
        self.error: Exception | None = None
        self.calls: list[float] = []

    async def wallet(self, account_id: UUID) -> WalletSnapshot:
        self.calls.append(self.clock.monotonic() - START)
        while self.hold is not None and not self.hold.is_set():
            try:
                await self.hold.wait()
            except asyncio.CancelledError:
                if not self.stubborn:
                    raise
        if self.error is not None:
            raise self.error
        return snapshot(self.clock.now())


class FakeWs:
    """One account's private socket: the auth reply, then a pong every `PING_S` until it is
    dropped (the close event is seen) or goes silent (it hangs: no pong, no close). `beats`
    holds the second of each heartbeat the feed was given."""

    def __init__(self, feed: AccountHealthFeed, sleeper: Sleeper, account: UUID = ACC) -> None:
        self.feed, self.sleeper, self.account = feed, sleeper, account
        self.beats: list[float] = []
        self._task: asyncio.Task[None] | None = None

    def connect(self) -> None:
        self._task = spawn(self._pong(), name="fake-private-ws")

    async def _pong(self) -> None:
        while True:
            self.beats.append(self.sleeper.clock.monotonic() - START)
            self.feed.ws_heartbeat(self.account)
            await self.sleeper.sleep(PING_S)

    def go_silent(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def drop(self) -> None:
        self.go_silent()
        self.feed.ws_dropped(self.account)


class Rig:
    """The runtime `create_app` builds, on a fake clock and sleeper, tracking `accounts` (`ACC` by
    default) through a fake source. The REST port is a fake only when `rest` is set; otherwise it
    is the production one, which answers every read as unavailable. The socket feeds the runtime
    through `ctx.accounts.account_health`, the path the E29-T05 consumer will use. The runtime
    publishes on the `wallet` topic through `hub`, which no client socket is on until a test
    registers one (`_wallet_ws.Conn`). A `journal` records the dead-man's-switch episodes; rigs
    sharing one are restarts of one process."""

    def __init__(
        self,
        *accounts: UUID,
        rest: bool = False,
        source: bool = True,
        settings: Settings | None = None,
        metrics: Metrics | None = None,
        journal: Journal | None = None,
    ) -> None:
        self.clock = FakeClock()
        self.sleeper = Sleeper(self.clock)
        self.dms = Dms(clock=self.clock)
        self.rest = Rest(self.clock)
        self.metrics = metrics or Metrics("demo")
        self.accounts = AccountsService()
        self.hub = SequencingHub()
        self.topic = WalletTopic(self.hub.publish, SnapshotBody, clock=self.clock.monotonic)
        self.wanted: frozenset[UUID] = frozenset(accounts or (ACC,))
        self.read_error: Exception | None = None  # the tracking source fails with this
        self.read_hangs = False  # or never answers
        self.released: list[str] = []  # the repository's pool, released when the runtime stops
        self.release_hangs = False
        self.runtime: AccountHealthRuntime = wire_account_health(
            settings or Settings(),
            self.metrics,
            clock=self.clock,
            sleep=self.sleeper.sleep,
            dms=self.dms,
            rest=self.rest if rest else None,
            monitored=self._monitored if source else None,
            release=self._release if source else None,
            topic=self.topic,
            journal=journal,
        )
        self.accounts.attach_account_health(self.runtime.feed)
        self.ws = FakeWs(self.accounts.account_health, self.sleeper)

    async def _monitored(self) -> frozenset[UUID]:
        if self.read_hangs:
            await asyncio.Event().wait()
        if self.read_error is not None:
            raise self.read_error
        return self.wanted

    async def _release(self) -> None:
        if self.release_hangs:
            await asyncio.Event().wait()
        self.released.append("pool")

    def track(self) -> None:
        for account in self.wanted:
            self.runtime.monitor.track(account)
            self.runtime.wallets.track(account)

    async def boot(self) -> None:
        """What the lifespan does: start the loops. The tracking loop's first pass, which runs at
        once, makes `accounts` tracked (the fake backend, `source=False`, tracks none)."""
        self.runtime.start()
        await settle()

    async def run(self, seconds: float) -> None:
        await self.sleeper.run(seconds)

    async def close(self) -> None:
        self.ws.go_silent()
        await self.runtime.stop()
