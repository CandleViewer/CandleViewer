"""What every mode runs against (#843 A4): the guarded port, the account, the public reads, the
measurements, the outputs and the shutdown, composed online (`compose.py`) or offline.

The port has no ticker, instrument or server-time read (`trading.ENDPOINTS`), so the reference
price and the instrument's filters come through `PublicReads`: online, the adapter's own unsigned
public client (`ExchangeBybitService.public_rest_client`, the live public host, as production
reads demo's market data: demo has no public feed), limited to two `GET` paths and carrying no
key; offline, the corpus. The clock offset comes from the signed wallet read's envelope `time`,
timed at the seam (`ClockOffset`).
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
from candleviewer.exchange.base.models import AccountRef, Order, PrivateEvent, PrivateStreamStatus
from candleviewer.exchange.bybit.instruments import parse_instrument
from candleviewer.exchange.bybit.trades import RECENT_TRADE_PATH, recent_trades_fetcher
from candleviewer.observability.context import spawn
from candleviewer.oms.order_link import OrderLinkIdParts, OrderPurpose
from spike.oms_demo_path.config import SYMBOL
from spike.oms_demo_path.measure import ClockOffset, StreamMonitor
from spike.oms_demo_path.outputs import RunOutputs
from spike.oms_demo_path.safety import GuardedPort, Refused, Shutdown, check_flat
from spike.oms_demo_path.scrub import Scrubber

if TYPE_CHECKING:
    from candleviewer.domain.events import Instrument
    from candleviewer.exchange.base.ports import TradingPort
    from spike.oms_demo_path.recorder import RecordingConnector, RecordingTransport

INSTRUMENTS_PATH: Final = "/v5/market/instruments-info"
_PUBLIC_PATHS: Final = frozenset({RECENT_TRADE_PATH, INSTRUMENTS_PATH})
WALLET_PATH: Final = "/v5/account/wallet-balance"
#: The stream's first `resyncing` (its subscriptions acknowledged), at most this long.
STREAM_READY_S: Final = 30.0


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
    """Our own `orderLinkId`s (24 §8.3), a fresh trade group each, each registered with the
    scrubber before it is sent, so no output carries one."""

    def __init__(self, account_id: AccountId, scrubber: Scrubber) -> None:
        self._account_id = account_id
        self._scrubber = scrubber

    def new(self, purpose: OrderPurpose = "entry") -> str:
        value = OrderLinkIdParts.generate(
            mode="exchange",
            environment="demo",
            group_id=GroupId(uuid4()),
            account_id=self._account_id,
            seq=0,
            purpose=purpose,
        ).value
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
    links: Links = field(init=False)

    def __post_init__(self) -> None:
        self.links = Links(self.account.account_id, self.scrubber)
        if self.monitor is None:
            self.monitor = StreamMonitor(self.offset, self.monotonic)

    @property
    def stream(self) -> StreamMonitor:
        monitor = self.monitor
        if monitor is None:  # pragma: no cover - set in __post_init__
            raise RuntimeError("no stream monitor")
        return monitor

    async def preflight(self) -> None:
        """The flat-book check, then the size limits from the instrument read."""
        orders = await self.port.open_orders(self.account, SYMBOL)
        positions = await self.port.positions(self.account)
        check_flat(orders, positions)

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
