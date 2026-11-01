"""What every mode runs against (#843 A4): the guarded port, the account, the public reads, the
measurements, the outputs and the shutdown, composed online (`compose.py`) or offline.

The port has no ticker, instrument or server-time read (`trading.ENDPOINTS`), so the reference
price and the instrument's filters come through `PublicReads`: online, the adapter's own unsigned
public client (`ExchangeBybitService.public_rest_client`, the live public host, as production
reads demo's market data: demo has no public feed), limited to two `GET` paths and carrying no
key; offline, the corpus. The clock offset comes from the signed wallet read's envelope `time`,
timed at the seam (`ClockOffset`).

Every mode that signs anything checks the key first: its first signed call is `check_key`, the
key's rights against what M2's import admitted (the adapter's own signed key-info read, never a
write; the coordinator's ruling 2 of fold 4): `soak` before its stream's `auth` and any signed
read, `retention` before its history read, and the modes that touch orders in their `preflight`.
That preflight goes on: the size limits set, the account flat (every USDT perpetual's open
orders and positions, and no row of those reads set aside by the adapter as another account's or
environment's), the offset measured; only then is the run armed (`arm`), and never once a
stop arrived (R2-06: it ends `stopped`). Until it is armed, nothing it does touches the account,
and the shutdown touches nothing either (ruling R1C-02 (a)). A stop ends a fill wait at once
(`wait`), so a stopped run reaches its flatten at once.
Every create the run sends is written to its intent ledger first (`ledger.IntentLedger`: no row,
no order), and its `RunScope` owns exactly what that ledger lists and the fills of those orders,
so the shutdown flatten cancels and closes only what the run itself placed and opened (ruling
R1C-02 (b)). Its `orderLinkId`s still share one prefix (`Links`, one trade group per run), which
names the run in the venue's UI; ownership is the ledger's.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, Protocol
from uuid import uuid4

from candleviewer.domain.primitives import AccountId, GroupId
from candleviewer.exchange.base.models import (
    AccountRef,
    Execution,
    Order,
    PrivateEvent,
    PrivateStreamStatus,
)
from candleviewer.exchange.bybit.instruments import parse_instrument
from candleviewer.exchange.bybit.trades import RECENT_TRADE_PATH, recent_trades_fetcher
from candleviewer.observability.context import spawn
from candleviewer.oms.order_link import SEQ_MAX, OrderLinkIdParts, OrderPurpose
from spike.oms_demo_path.config import SYMBOL
from spike.oms_demo_path.ledger import IntentLedger
from spike.oms_demo_path.measure import ClockOffset, StreamMonitor
from spike.oms_demo_path.outputs import RunOutputs
from spike.oms_demo_path.safety import (
    LINK_PREFIX_LEN,
    GuardedPort,
    Refused,
    RunScope,
    Shutdown,
    Stopped,
    check_flat,
    check_none_set_aside,
    flatten,
    key_mismatch,
    key_record,
    rows_set_aside,
)
from spike.oms_demo_path.scrub import Scrubber

if TYPE_CHECKING:
    from candleviewer.accounts.verification import KeyFacts
    from candleviewer.domain.events import Instrument
    from candleviewer.exchange.base.ports import TradingPort
    from spike.oms_demo_path.recorder import RecordingConnector, RecordingTransport

INSTRUMENTS_PATH: Final = "/v5/market/instruments-info"
_PUBLIC_PATHS: Final = frozenset({RECENT_TRADE_PATH, INSTRUMENTS_PATH})
WALLET_PATH: Final = "/v5/account/wallet-balance"
#: The stream's first `resyncing` (its subscriptions acknowledged), at most this long.
STREAM_READY_S: Final = 30.0
#: The `seq2` values kept for the flatten's closes: past `SEQ_MAX` minus these, no other order is
#: given a link (the run's `orderLinkId` space is one trade group's).
FLATTEN_RESERVE: Final = 100


class GetPublic(Protocol):
    def __call__(self, path: str, *, params: Mapping[str, Any] | None = None) -> Awaitable[Any]: ...


class PublicReads:
    """The reference price (the last trade) and the instrument, over a public `get_public`."""

    def __init__(self, get_public: GetPublic, now_us: Callable[[], int]) -> None:
        self._get = get_public
        self._now_us = now_us
        self.reads = 0

    async def _read(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        if path not in _PUBLIC_PATHS:
            raise Refused("the harness's public reads are the last trades and the instrument")
        self.reads += 1
        return await self._get(path, params=params)

    async def reference(self) -> Decimal:
        prints = await recent_trades_fetcher(self._read)(SYMBOL)
        if not prints:
            raise Refused("no recent trade to price from")
        return max(prints, key=lambda p: p.ts_event_us).price

    async def instrument(self) -> Instrument:
        body = await self._read(INSTRUMENTS_PATH, params={"category": "linear", "symbol": SYMBOL})
        rows = [r for r in body["result"]["list"] if r.get("symbol") == SYMBOL]
        if len(rows) != 1:
            raise Refused("the instrument read names no single BTCUSDT row")
        return parse_instrument(rows[0], fetched_at_us=self._now_us())


class Links:
    """Our own `orderLinkId`s (24 §8.3), all in one trade group of the run's own, numbered by
    `seq2`, so each carries the run's prefix (`prefix`: `cvd-` and the group); each registered
    with the scrubber before it is sent, so no output carries one. The last `FLATTEN_RESERVE`
    numbers are kept for the flatten's closes."""

    def __init__(
        self, account_id: AccountId, scrubber: Scrubber, group: GroupId | None = None
    ) -> None:
        self._account_id = account_id
        self._scrubber = scrubber
        self._group = GroupId(uuid4()) if group is None else group
        self._seq = 0
        self.prefix = self._render(0, "entry")[:LINK_PREFIX_LEN]

    def _render(self, seq: int, purpose: OrderPurpose) -> str:
        return OrderLinkIdParts.generate(
            mode="exchange",
            environment="demo",
            group_id=self._group,
            account_id=self._account_id,
            seq=seq,
            purpose=purpose,
        ).value

    def new(self, purpose: OrderPurpose = "entry") -> str:
        limit = SEQ_MAX if purpose == "flatten" else SEQ_MAX - FLATTEN_RESERVE
        if self._seq > limit:
            raise Refused("the run's orderLinkId space is spent: start another run")
        value = self._render(self._seq, purpose)
        self._seq += 1
        self._scrubber.known("link", value)
        return value

    def flatten(self) -> str:
        return self.new("flatten")


def _wall_us() -> int:
    return int(time.time() * 1_000_000)


@dataclass
class Harness:
    port: GuardedPort
    account: AccountRef
    public: PublicReads
    outputs: RunOutputs
    scrubber: Scrubber
    shutdown: Shutdown
    offset: ClockOffset = field(default_factory=ClockOffset)
    monitor: StreamMonitor | None = None
    recorder: RecordingTransport | None = None
    connector: RecordingConnector | None = None
    skewed_port: Callable[[int], TradingPort] | None = None
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    now_us: Callable[[], int] = _wall_us
    monotonic: Callable[[], float] = time.monotonic
    #: Called once the run is armed (`run.py` writes the provisional summary then).
    on_armed: Callable[[], None] | None = None
    #: The adapter's own key-info read of the run's key (`compose.Composed.key_info_read`).
    key_info: Callable[[], Awaitable[KeyFacts]] | None = None
    links: Links = field(init=False)
    ledger: IntentLedger = field(init=False)
    scope: RunScope = field(init=False)
    armed: bool = field(init=False, default=False)
    #: The key-rights preflight's record (`safety.key_record`), once the key was read.
    key_check: dict[str, object] | None = field(init=False, default=None)
    #: The key's rights matched (`check_key`): a mode that never arms is committed from here.
    key_passed: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        self.links = Links(self.account.account_id, self.scrubber)
        self.ledger = IntentLedger(
            self.outputs.directory, self.scrubber, elapsed=self.outputs.elapsed
        )
        self.scope = RunScope(self.ledger, self.account.account_id, self.monotonic)
        self.port.scope, self.port.ledger = self.scope, self.ledger
        if self.monitor is None:
            self.monitor = StreamMonitor(self.offset, self.monotonic)

    @property
    def stream(self) -> StreamMonitor:
        monitor = self.monitor
        if monitor is None:  # pragma: no cover - set in __post_init__
            raise RuntimeError("no stream monitor")
        return monitor

    def venue_now_us(self, *, slack: int) -> int:
        """Now on the exchange's clock (host plus the measured offset), as `execTime` reads,
        moved by `slack` times the offset's own uncertainty: half its best round trip, plus the
        1 ms the venue's whole-ms `time` truncates. A window read from the venue is widened by
        it at both ends (`slack=-1` at its start, `+1` at its end), so none of its executions
        falls outside it (R1C-11: no fixed lead)."""
        rtt = self.offset.best_rtt_ms or 0.0
        return self.now_us() + (self.offset.value or 0) * 1000 + slack * round((1 + rtt / 2) * 1000)

    async def preflight(self) -> None:
        """Ruling R1C-02 (a): the size limits set, the key's rights checked (`check_key`), the
        account flat (no open order on any USDT perpetual, no position: R2-08; no row of those
        reads set aside by the adapter: R3-04), the offset measured; then the run is armed.
        Whatever fails first refuses the run, and nothing was sent: the shutdown then touches
        nothing either."""
        if self.port.limits is None:
            raise Refused("no size limits: the instrument read comes first; nothing was sent")
        await self.check_key()
        before = rows_set_aside()
        orders = await self.port.open_orders(self.account)  # every symbol (`settleCoin`)
        positions = await self.port.positions(self.account)
        check_flat(orders, positions)
        check_none_set_aside(before, rows_set_aside())  # no order of ours hidden from the reads
        await self.measure_offset()
        self.arm()

    async def check_key(self) -> None:
        """The key's live rights against what M2's import admitted it with (`safety.key_mismatch`,
        C-2.8), from the adapter's own key-info read (one signed `GET /v5/user/query-api`, never
        a write): the first signed call of every mode that signs anything (ruling 2), before
        anything else is signed, read, dialled or armed. A mismatch, or no read wired, refuses
        the run with nothing touched (ruling R1C-02 (a)). The UID and the allow-list's addresses
        it reads are registered with the scrubber, never written."""
        if self.key_info is None:
            raise Refused("no key-info read is wired: the key's rights are unchecked")
        facts = await self.key_info()
        for value in (facts.uid, *facts.ip_whitelist):
            self.scrubber.secret(value)
        mismatch = key_mismatch(facts)
        self.key_check = key_record(facts, mismatch)
        if mismatch is not None:
            raise Refused(f"{mismatch}; nothing was touched")
        self.key_passed = True

    async def flatten(self) -> dict[str, object]:
        """`safety.flatten` over the run's own scope (ruling R1C-02 (b)), on its clocks."""
        return await flatten(
            self.port,
            self.account,
            self.scope,
            self.links.flatten,
            venue_now_us=lambda: self.venue_now_us(slack=1),
            sleep=self.sleep,
            monotonic=self.monotonic,
        )

    def arm(self) -> None:
        """From here on the run may touch the account, and its shutdown flattens what it owns:
        its window starts now, on the exchange's clock. Never once a stop arrived (R2-06): the
        run then ends `stopped`, unarmed, with nothing touched (`Stopped`)."""
        if self.shutdown.event.is_set():
            raise Stopped("a stop arrived before the run was armed: nothing was touched")
        start, held = self.venue_now_us(slack=-1), self.scope.start_us
        self.scope.start_us = start if held is None else min(held, start)  # an adopted scope's
        self.armed = True
        if self.on_armed is not None:
            self.on_armed()

    async def wait(self, predicate: Callable[[], bool], timeout_s: float) -> bool:
        """`StreamMonitor.wait` (`predicate` on the stream, at most `timeout_s`), ended at once
        by a stop (R2-06): a stopped cycle never waits out its `--fill-wait-s`, so it reaches the
        flatten's 40 s well inside the container's 60 s grace. Whether `predicate()` holds."""
        if not self.shutdown.event.is_set():
            waiter = spawn(self.stream.wait(predicate, timeout_s), name="spike-fill-wait")
            stop = spawn(self.shutdown.event.wait(), name="spike-fill-wait-stop")
            try:
                await asyncio.wait({waiter, stop}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in (waiter, stop):
                    task.cancel()
                await asyncio.gather(waiter, stop, return_exceptions=True)
        return predicate()

    async def measure_offset(self, samples: int = 5) -> int | None:
        """The offset from the signed wallet read's envelope `time` against its exchange at the
        seam (offline with no recorder: the port's own call time, which includes M2)."""
        self.offset.reset_best()
        for _ in range(samples):
            sent = self.now_us() / 1000
            wallet = await self.port.wallet(self.account)
            received = self.now_us() / 1000
            exchange = None if self.recorder is None else self.recorder.last.get(WALLET_PATH)
            if exchange is not None and exchange.venue_ms is not None:
                sent, received = exchange.sent_wall_ms, exchange.received_wall_ms
            self.offset.sample(sent, received, wallet.updated_at // 1000)
        self.outputs.event(
            "clock",
            offset_ms=self.offset.value,
            best_rtt_ms=None
            if self.offset.best_rtt_ms is None
            else round(self.offset.best_rtt_ms, 2),
            samples=samples,
        )
        return self.offset.value

    @asynccontextmanager
    async def private_stream(self) -> AsyncIterator[StreamMonitor]:
        """The account's private stream, read by a task this context owns into the monitor,
        until the context ends (the stream closed, the task awaited)."""
        monitor = self.stream
        stream = await self.port.subscribe_private(self.account)

        async def consume() -> None:
            async for item in stream:
                monitor.observe(item)
                if isinstance(item, PrivateEvent) and isinstance(item.payload, Execution):
                    self.scope.add([item.payload])
                self.outputs.event("private", _describe(item))

        task = spawn(consume(), name="spike-private-consumer")
        try:
            if not await monitor.wait(lambda: monitor.live, STREAM_READY_S):
                raise Refused("the private stream did not come up")
            yield monitor
        finally:
            await stream.aclose()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)  # its own end, never re-raised


def _describe(item: object) -> dict[str, object]:
    """A private item as an event line: its kind, the state and ids an order carries."""
    if isinstance(item, PrivateStreamStatus):
        return {"status": f"{item.state}:{item.reason}", "epoch": item.epoch}
    if isinstance(item, PrivateEvent):
        payload = item.payload
        out: dict[str, object] = {"item": item.kind, "ts_event": item.ts_event}
        if isinstance(payload, Order):
            out |= {
                "state": payload.state,
                "filled": str(payload.filled_qty),
                "exchange_order_id": payload.exchange_order_id,
            }
        exec_id = getattr(payload, "exec_id", None)
        if isinstance(exec_id, str):
            out["exec_id"] = exec_id
        return out
    return {"item": type(item).__name__}
