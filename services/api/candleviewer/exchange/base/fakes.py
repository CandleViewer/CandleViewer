"""In-memory port fakes for downstream unit tests (ticket body, acceptance
criterion 2). No network, no fixtures, no exchange vocabulary — callers seed
them with plain domain objects and get isinstance-conforming adapters back:
`FakeExchange` for `MarketDataPort`, `FakeTradingPort` for `TradingPort` (G-8,
#2877), which refuses what the exchange adapter refuses and behaves like the
venue where the OMS depends on it.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal, get_args

from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import (
    AccountId,
    Environment,
    Exchange,
    OrderLinkId,
    Symbol,
    TsUs,
)

from .errors import AmbiguousResultError, DuplicateClientIdError, NotFoundError, OmsErrorCode
from .guards import check_create_id, check_exit_ids, check_lookup_id, check_window
from .models import (
    AccountInfo,
    AccountRef,
    AmendOrderRequest,
    BookDelta,
    BookSnapshot,
    CancelOrderRequest,
    ClosedPnl,
    ExchangeCapabilities,
    Execution,
    FeeRate,
    FundingEvent,
    KlineEvent,
    LiquidationEvent,
    OpenInterestEvent,
    Order,
    OrderAck,
    PlaceOrderRequest,
    Position,
    PrivateEvent,
    RateLane,
    RiskLimitTier,
    TickerEvent,
    TradeEvent,
    TradingStopRequest,
    Wallet,
)

__all__ = [
    "CANCEL_ALL_LIMIT",
    "FakeCall",
    "FakeExchange",
    "FakeReject",
    "FakeTradingPort",
    "LandedThenAmbiguous",
    "fake_capabilities",
]


class FakeExchange:
    """Satisfies `MarketDataPort` structurally (no inheritance). Seed data
    via the constructor; `subscribe_*` methods replay the seeded sequence
    once and then end the iterator — enough for a unit test to assert on a
    finite stream without a real transport."""

    def __init__(
        self,
        *,
        instruments: Sequence[Instrument] = (),
        trades: Sequence[TradeEvent] = (),
        book_events: Sequence[BookSnapshot | BookDelta] = (),
        tickers: Sequence[TickerEvent] = (),
        klines: Sequence[KlineEvent] = (),
        liquidations: Sequence[LiquidationEvent] = (),
        open_interest: Sequence[OpenInterestEvent] = (),
        funding: Sequence[FundingEvent] = (),
        risk_limits: Sequence[RiskLimitTier] = (),
        server_time: TsUs = 0,
    ) -> None:
        self._instruments = {i.symbol: i for i in instruments}
        self._trades = list(trades)
        self._book_events = list(book_events)
        self._tickers = list(tickers)
        self._klines = list(klines)
        self._liquidations = list(liquidations)
        self._open_interest = list(open_interest)
        self._funding = list(funding)
        self._risk_limits = list(risk_limits)
        self._server_time = server_time

    async def instruments(self) -> Sequence[Instrument]:
        return list(self._instruments.values())

    async def instrument(self, symbol: Symbol) -> Instrument:
        try:
            return self._instruments[symbol]
        except KeyError as exc:
            raise NotFoundError(f"no fake instrument seeded for {symbol!r}") from exc

    async def subscribe_trades(self, symbols: Sequence[Symbol]) -> AsyncIterator[TradeEvent]:
        for event in self._trades:
            if event.symbol in symbols:
                yield event

    async def subscribe_book(
        self, symbols: Sequence[Symbol], depth: int
    ) -> AsyncIterator[BookSnapshot | BookDelta]:
        for event in self._book_events:
            if event.symbol in symbols and event.depth == depth:
                yield event

    async def subscribe_ticker(self, symbols: Sequence[Symbol]) -> AsyncIterator[TickerEvent]:
        for event in self._tickers:
            if event.symbol in symbols:
                yield event

    async def subscribe_klines(
        self, symbols: Sequence[Symbol], interval: str
    ) -> AsyncIterator[KlineEvent]:
        for event in self._klines:
            if event.symbol in symbols and event.interval == interval:
                yield event

    async def subscribe_liquidations(
        self, symbols: Sequence[Symbol]
    ) -> AsyncIterator[LiquidationEvent]:
        for event in self._liquidations:
            if event.symbol in symbols:
                yield event

    async def fetch_klines(
        self,
        symbol: Symbol,
        interval: str,
        start: TsUs,
        end: TsUs,
        limit: int = 1000,
    ) -> Sequence[KlineEvent]:
        matches = [
            k
            for k in self._klines
            if k.symbol == symbol and k.interval == interval and start <= k.start <= end
        ]
        return matches[:limit]

    async def fetch_recent_trades(self, symbol: Symbol, limit: int = 1000) -> Sequence[TradeEvent]:
        matches = [t for t in self._trades if t.symbol == symbol]
        return matches[:limit]

    async def fetch_orderbook(self, symbol: Symbol, depth: int = 200) -> BookSnapshot:
        for event in self._book_events:
            if isinstance(event, BookSnapshot) and event.symbol == symbol and event.depth == depth:
                return event
        raise NotFoundError(f"no fake orderbook snapshot seeded for {symbol!r}@{depth}")

    async def fetch_open_interest(
        self, symbol: Symbol, interval: str, start: TsUs, end: TsUs
    ) -> Sequence[OpenInterestEvent]:
        return [
            e
            for e in self._open_interest
            if e.symbol == symbol and e.interval == interval and start <= e.ts_event <= end
        ]

    async def fetch_funding_history(
        self, symbol: Symbol, start: TsUs, end: TsUs
    ) -> Sequence[FundingEvent]:
        return [e for e in self._funding if e.symbol == symbol and start <= e.ts_event <= end]

    async def fetch_risk_limits(self, symbol: Symbol) -> Sequence[RiskLimitTier]:
        return list(self._risk_limits)

    async def server_time_us(self) -> TsUs:
        return self._server_time


#: The neutral scope a fake `cancel_all` cancels: plain orders only, never conditional or
#: take-profit/stop-loss orders (the scope the exchange adapter sends, 24 §14.2 rule 12).
CANCEL_ALL_SCOPE: Final = "order"
#: The most orders one `cancel_all` cancels, as the venue's futures cancel-all does (24 §14.2
#: rule 12): one call is no proof of a flat book.
CANCEL_ALL_LIMIT: Final = 500
_TERMINAL: Final = frozenset({"rejected", "filled", "cancelled", "deactivated"})


@dataclass(frozen=True, slots=True)
class FakeCall:
    """One `FakeTradingPort` call: the method, the account, what was asked and its lane."""

    method: str
    account_id: AccountId
    request: object
    lane: RateLane


@dataclass(frozen=True, slots=True)
class FakeReject:
    """A scripted business rejection: the call returns `OrderAck(ok=False)` (B1 records it)."""

    error_code: OmsErrorCode
    exchange_ret_code: int | None = None
    exchange_ret_msg: str | None = None
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class LandedThenAmbiguous:
    """A scripted create that lands at the venue and then raises `AmbiguousResultError`, as a
    timeout after the send does (24 §8.6 "Order creates")."""


type FakeOutcome = BaseException | FakeReject | LandedThenAmbiguous


def fake_capabilities(
    environment: Environment = "demo", **overrides: object
) -> ExchangeCapabilities:
    """A neutral capability record for tests; `overrides` replace fields by name."""
    base: dict[str, object] = {
        "exchange": get_args(Exchange)[0],
        "environment": environment,
        "supports_ws_order_entry": False,
        "supports_native_oco": False,
        "supports_native_iceberg": False,
        "supports_native_twap": False,
        "supports_native_chase": False,
        "supports_native_trailing": True,
        "supports_native_conditional": True,
        "supports_attached_sl_tp": True,
        "supports_batch_orders": True,
        "supports_reduce_only": True,
        "supports_post_only": True,
        "supports_hedge_mode": True,
        "supports_dead_mans_switch": False,
        "max_batch_size": 10,
        "max_ws_topics_per_request": 10,
        "max_orders_per_symbol": 500,
        "max_conditional_orders_per_symbol": 10,
        "order_link_id_max_len": 36,
        "order_rate_per_uid_per_s": {"order.create": 10},
        "ip_rate_per_5s": 600,
        "book_depths": (1, 50, 200, 500),
        "book_cadence_ms": {1: 10, 50: 20, 200: 100, 500: 200},
        "position_modes": ("one_way", "hedge"),
        "trigger_sources": ("last", "mark", "index"),
        "order_retention_days": 7 if environment == "demo" else None,
        "has_public_ws": environment != "demo",
    }
    return ExchangeCapabilities.model_validate({**base, **overrides})


class FakeTradingPort:
    """Satisfies `TradingPort` structurally, in memory (G-8, #2877).

    It refuses what the exchange adapter refuses (another environment's account, an `ext-`
    key on the wire, a create without a generated id of its account, a bad window), records
    every call as a `FakeCall` with its lane, and behaves like the venue where the OMS depends
    on it: a reused id is rejected as a duplicate even after the order is terminal, exchange
    ids are deterministic, `cancel_all` cancels plain orders only, at most `cancel_all_limit`
    of them per call (the venue picks them at random; the fake takes the oldest first, so a
    caller repeats it until `open_orders` is empty), and records its scope in
    `cancel_all_scopes`. Each method can be scripted (`script`): an exception is raised (a
    transport error before the send, an auth, clock or rate error, `RateBudgetExceededError`),
    a `FakeReject` comes back as `OrderAck(ok=False)`, and `LandedThenAmbiguous` lands a
    create and raises `AmbiguousResultError`. `subscribe_private` replays the seeded events
    of the account, then what `push` queues, until `end_stream`. It does not model a refusal
    the venue gives on its own (a stop on a flat position, a margin shortfall): script it."""

    def __init__(
        self,
        *,
        environment: Environment = "demo",
        capabilities: ExchangeCapabilities | None = None,
        now_us: Callable[[], TsUs] = lambda: 0,
        private_events: Sequence[PrivateEvent] = (),
        queue_size: int = 1024,
        cancel_all_limit: int = CANCEL_ALL_LIMIT,
    ) -> None:
        if cancel_all_limit < 1:
            raise ValueError("a cancel-all cancels at least one order")
        self.capabilities = (
            capabilities if capabilities is not None else fake_capabilities(environment)
        )
        self._cancel_all_limit = cancel_all_limit
        self.environment: Environment = self.capabilities.environment
        self.calls: list[FakeCall] = []
        self.cancel_all_scopes: list[tuple[AccountId, Symbol | None, str]] = []
        self._now_us = now_us
        self._seen: set[tuple[str, str]] = set()
        self._open: dict[str, Order] = {}
        self._history: dict[str, Order] = {}
        self._positions: list[Position] = []
        self._executions: list[Execution] = []
        self._closed_pnl: list[ClosedPnl] = []
        self._wallets: dict[AccountId, Wallet] = {}
        self._fees: dict[tuple[AccountId, Symbol], FeeRate] = {}
        self._infos: dict[AccountId, AccountInfo] = {}
        self._scripts: dict[str, deque[FakeOutcome]] = {}
        self._next_id = 0
        self._events = list(private_events)
        self._pushed: asyncio.Queue[PrivateEvent | None] = asyncio.Queue(maxsize=queue_size)

    # -- seeding and scripting ------------------------------------------------------------

    def script(self, method: str, *outcomes: FakeOutcome) -> None:
        """Queue outcomes for the next calls of `method`, one per call, first in first out. An
        exception fits any method, a `FakeReject` only one that answers with acks, and
        `LandedThenAmbiguous` only `place_order`."""
        if method not in _SCRIPTABLE:
            raise ValueError(f"not a scriptable TradingPort method: {method!r}")
        for outcome in outcomes:
            if isinstance(outcome, FakeReject) and method not in _ACKING:
                raise ValueError(f"{method} answers with no ack to reject")
            if isinstance(outcome, LandedThenAmbiguous) and method != "place_order":
                raise ValueError("only a create can land and then go unanswered")
        self._scripts.setdefault(method, deque()).extend(outcomes)

    def seed_order(self, order: Order, *, uid: str) -> None:
        """An order the venue holds for the UID: open, or in history once terminal."""
        self._seen.add((uid, order.order_link_id))
        key = order.exchange_order_id or order.order_link_id
        (self._history if order.state in _TERMINAL else self._open)[key] = order

    def seed_position(self, position: Position) -> None:
        key = _position_key(position)
        self._positions = [p for p in self._positions if _position_key(p) != key]
        self._positions.append(position)

    def seed_execution(self, execution: Execution) -> None:
        self._executions.append(execution)

    def seed_closed_pnl(self, record: ClosedPnl) -> None:
        self._closed_pnl.append(record)

    def set_wallet(self, wallet: Wallet) -> None:
        self._wallets[wallet.account_id] = wallet

    def set_fee_rate(self, account_id: AccountId, fee: FeeRate) -> None:
        self._fees[(account_id, fee.symbol)] = fee

    def set_account_info(self, info: AccountInfo) -> None:
        self._infos[info.account_id] = info

    def push(self, event: PrivateEvent) -> None:
        """Queue one private event for `subscribe_private` (bounded: `QueueFull` when full)."""
        self._pushed.put_nowait(event)

    def end_stream(self) -> None:
        """End every `subscribe_private` iteration once the queued events are drained."""
        self._pushed.put_nowait(None)

    # -- trade calls ------------------------------------------------------------------------

    async def place_order(self, req: PlaceOrderRequest) -> OrderAck:
        check_create_id(req.account, req.order_link_id)
        self._enter("place_order", req.account, req, req.lane)
        outcome = self._outcome("place_order")
        if isinstance(outcome, FakeReject):
            return _rejected(req.order_link_id, outcome)
        order = self._land(req)
        if isinstance(outcome, LandedThenAmbiguous):
            raise AmbiguousResultError(
                "the create left and its outcome is unknown", order_link_id=req.order_link_id
            )
        return _ack(req.order_link_id, order.exchange_order_id)

    async def place_batch(self, reqs: Sequence[PlaceOrderRequest]) -> Sequence[OrderAck]:
        if not reqs or len(reqs) > self.capabilities.max_batch_size:
            raise ValueError("a batch holds 1 to max_batch_size orders")
        accounts, lanes = {r.account for r in reqs}, {r.lane for r in reqs}
        if len(accounts) != 1 or len(lanes) != 1:
            raise ValueError("a batch is one account's, in one lane")
        account = reqs[0].account
        for req in reqs:
            check_create_id(account, req.order_link_id)
        self._enter("place_batch", account, tuple(reqs), reqs[0].lane)
        outcome = self._outcome("place_batch")
        if isinstance(outcome, FakeReject):
            return [_rejected(r.order_link_id, outcome) for r in reqs]
        acks: list[OrderAck] = []
        for req in reqs:
            if (account.uid, req.order_link_id) in self._seen:
                duplicate = FakeReject(OmsErrorCode.DUPLICATE_CLIENT_ID)
                acks.append(_rejected(req.order_link_id, duplicate))
                continue
            acks.append(_ack(req.order_link_id, self._land(req).exchange_order_id))
        return acks

    async def amend_order(self, req: AmendOrderRequest) -> OrderAck:
        check_exit_ids(req.order_link_id, req.exchange_order_id)
        self._enter("amend_order", req.account, req, req.lane)
        outcome = self._outcome("amend_order")
        if isinstance(outcome, FakeReject):
            return _rejected(req.order_link_id, outcome)
        key = self._find_open(req.account, req.order_link_id, req.exchange_order_id)
        if key is None:
            return _rejected(req.order_link_id, FakeReject(OmsErrorCode.ORDER_NOT_FOUND))
        changes = {
            name: value
            for name in ("qty", "price", "trigger_price", "take_profit", "stop_loss")
            if (value := getattr(req, name)) is not None
        }
        self._open[key] = self._open[key].model_copy(update=changes)
        return _ack(self._open[key].order_link_id, self._open[key].exchange_order_id)

    async def cancel_order(self, req: CancelOrderRequest) -> OrderAck:
        check_exit_ids(req.order_link_id, req.exchange_order_id)
        self._enter("cancel_order", req.account, req, "critical")
        outcome = self._outcome("cancel_order")
        if isinstance(outcome, FakeReject):
            return _rejected(req.order_link_id, outcome)
        key = self._find_open(req.account, req.order_link_id, req.exchange_order_id)
        if key is None:
            return _rejected(req.order_link_id, FakeReject(OmsErrorCode.ORDER_NOT_FOUND))
        order = self._close(key, "cancelled")
        return _ack(order.order_link_id, order.exchange_order_id)

    async def cancel_all(self, account: AccountRef, symbol: Symbol | None) -> Sequence[OrderAck]:
        self._enter("cancel_all", account, symbol, "critical")
        outcome = self._outcome("cancel_all")
        if isinstance(outcome, FakeReject):
            return [_rejected(None, outcome)]
        self.cancel_all_scopes.append((account.account_id, symbol, CANCEL_ALL_SCOPE))
        keys = [
            key
            for key, order in self._open.items()
            if order.account_id == account.account_id
            and order.order_kind == CANCEL_ALL_SCOPE
            and symbol in (None, order.symbol)
        ][: self._cancel_all_limit]
        acks = []
        for key in keys:
            order = self._close(key, "cancelled")
            acks.append(_ack(order.order_link_id, order.exchange_order_id))
        return acks

    async def set_trading_stop(self, req: TradingStopRequest) -> OrderAck:
        self._enter("set_trading_stop", req.account, req, "critical")
        outcome = self._outcome("set_trading_stop")
        if isinstance(outcome, FakeReject):
            return _rejected(None, outcome)
        changes = {
            name: value
            for name, value in (
                ("take_profit", req.take_profit),
                ("stop_loss", req.stop_loss),
                ("trailing_stop_distance", req.trailing_distance),
            )
            if value is not None
        }
        key = (req.account.account_id, req.symbol, req.position_idx)
        self._positions = [
            p.model_copy(update=changes) if _position_key(p) == key else p for p in self._positions
        ]
        return _ack(None, None)

    async def set_leverage(self, account: AccountRef, symbol: Symbol, leverage: Decimal) -> None:
        if not leverage.is_finite() or leverage <= 0:
            raise ValueError("leverage must be a positive number")
        self._enter("set_leverage", account, (symbol, leverage), "entry")
        self._outcome("set_leverage")
        self._positions = [
            (
                p.model_copy(update={"leverage": leverage})
                if (p.account_id, p.symbol) == (account.account_id, symbol)
                else p
            )
            for p in self._positions
        ]

    # -- reads ----------------------------------------------------------------------------

    async def open_orders(
        self,
        account: AccountRef,
        symbol: Symbol | None = None,
        *,
        order_link_id: OrderLinkId | None = None,
    ) -> Sequence[Order]:
        check_lookup_id(order_link_id)
        self._enter("open_orders", account, (symbol, order_link_id), "poll")
        self._outcome("open_orders")
        return [
            o
            for o in self._open.values()
            if o.account_id == account.account_id
            and symbol in (None, o.symbol)
            and order_link_id in (None, o.order_link_id)
        ]

    async def order_history(
        self,
        account: AccountRef,
        *,
        order_link_id: OrderLinkId | None = None,
        exchange_order_id: str | None = None,
        start: TsUs | None = None,
        end: TsUs | None = None,
    ) -> Sequence[Order]:
        asked = (order_link_id, exchange_order_id, start, end)
        check_lookup_id(order_link_id)
        check_window(start, end)
        self._enter("order_history", account, asked, "poll")
        self._outcome("order_history")
        return [
            o
            for o in self._history.values()
            if o.account_id == account.account_id
            and order_link_id in (None, o.order_link_id)
            and exchange_order_id in (None, o.exchange_order_id)
            and _within(o.created_at, start, end)
        ]

    async def positions(self, account: AccountRef) -> Sequence[Position]:
        self._enter("positions", account, None, "poll")
        self._outcome("positions")
        return [p for p in self._positions if p.account_id == account.account_id]

    async def executions(self, account: AccountRef, start: TsUs, end: TsUs) -> Sequence[Execution]:
        check_window(start, end)
        self._enter("executions", account, (start, end), "poll")
        self._outcome("executions")
        return [
            e
            for e in self._executions
            if e.account_id == account.account_id and _within(e.ts_exec, start, end)
        ]

    async def closed_pnl(self, account: AccountRef, start: TsUs, end: TsUs) -> Sequence[ClosedPnl]:
        check_window(start, end)
        self._enter("closed_pnl", account, (start, end), "poll")
        self._outcome("closed_pnl")
        return [
            c
            for c in self._closed_pnl
            if c.account_id == account.account_id and _within(c.closed_at, start, end)
        ]

    async def wallet(self, account: AccountRef) -> Wallet:
        self._enter("wallet", account, None, "poll")
        self._outcome("wallet")
        return _seeded(self._wallets, account.account_id, "wallet")

    async def fee_rate(self, account: AccountRef, symbol: Symbol) -> FeeRate:
        self._enter("fee_rate", account, symbol, "poll")
        self._outcome("fee_rate")
        return _seeded(self._fees, (account.account_id, symbol), "fee rate")

    async def account_info(self, account: AccountRef) -> AccountInfo:
        self._enter("account_info", account, None, "poll")
        self._outcome("account_info")
        return _seeded(self._infos, account.account_id, "account info")

    async def subscribe_private(self, account: AccountRef) -> AsyncIterator[PrivateEvent]:
        self._check_environment(account)
        return self._stream(account.account_id)

    async def _stream(self, account_id: AccountId) -> AsyncIterator[PrivateEvent]:
        for seeded in self._events:
            if seeded.account_id == account_id:
                yield seeded
        while (pushed := await self._pushed.get()) is not None:
            if pushed.account_id == account_id:
                yield pushed

    # -- internals --------------------------------------------------------------------------

    def _check_environment(self, account: AccountRef) -> None:
        if account.environment != self.environment:
            raise ValueError("the account belongs to another environment")

    def _enter(self, method: str, account: AccountRef, request: object, lane: RateLane) -> None:
        """Refuse another environment's account, then record the call: every refusal comes
        before anything is recorded, as nothing is sent for one at the venue."""
        self._check_environment(account)
        self.calls.append(FakeCall(method, account.account_id, request, lane))

    def _outcome(self, method: str) -> FakeReject | LandedThenAmbiguous | None:
        queue = self._scripts.get(method)
        if not queue:
            return None
        outcome = queue.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def _land(self, req: PlaceOrderRequest) -> Order:
        """The venue takes the create: a duplicate id is refused even once terminal."""
        if (req.account.uid, req.order_link_id) in self._seen:
            raise DuplicateClientIdError("the order_link_id was already accepted")
        self._seen.add((req.account.uid, req.order_link_id))
        self._next_id += 1
        exchange_order_id = f"fake-{self._next_id:012d}"
        order = Order(
            order_link_id=req.order_link_id,
            exchange_order_id=exchange_order_id,
            account_id=req.account.account_id,
            symbol=req.symbol,
            side=req.side,
            order_type=req.order_type,
            qty=req.qty,
            price=req.price if req.order_type == "limit" else None,
            state="untriggered" if req.trigger_price is not None else "new",
            filled_qty=Decimal(0),
            leaves_qty=req.qty,
            avg_fill_price=None,
            created_at=self._now_us(),
            terminal_at=None,
            reduce_only=req.reduce_only,
            trigger_price=req.trigger_price,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
            tpsl_mode=req.tpsl_mode,
            order_kind="conditional" if req.trigger_price is not None else "order",
            position_idx=req.position_idx,
            time_in_force=req.time_in_force,
        )
        self._open[exchange_order_id] = order
        return order

    def _find_open(
        self, account: AccountRef, link: str | None, exchange_order_id: str | None
    ) -> str | None:
        for key, order in self._open.items():
            if order.account_id != account.account_id:
                continue
            if exchange_order_id is not None and order.exchange_order_id == exchange_order_id:
                return key
            if exchange_order_id is None and order.order_link_id == link:
                return key
        return None

    def _close(self, key: str, state: Literal["cancelled"]) -> Order:
        order = self._open.pop(key).model_copy(
            update={"state": state, "terminal_at": self._now_us()}
        )
        self._history[key] = order
        return order


_ACKING: Final = frozenset(
    {
        "place_order",
        "place_batch",
        "amend_order",
        "cancel_order",
        "cancel_all",
        "set_trading_stop",
    }
)
_SCRIPTABLE: Final = _ACKING | frozenset(
    {
        "set_leverage",
        "open_orders",
        "order_history",
        "positions",
        "executions",
        "closed_pnl",
        "wallet",
        "fee_rate",
        "account_info",
    }
)


def _ack(link: str | None, exchange_order_id: str | None) -> OrderAck:
    return OrderAck(
        ok=True,
        order_link_id=link,
        exchange_order_id=exchange_order_id,
        latency_ms=0,
        transport="rest",
    )


def _rejected(link: str | None, reject: FakeReject) -> OrderAck:
    return OrderAck(
        ok=False,
        order_link_id=link,
        exchange_order_id=None,
        error_code=reject.error_code.value,
        exchange_ret_code=reject.exchange_ret_code,
        exchange_ret_msg=reject.exchange_ret_msg,
        retryable=reject.retryable,
        latency_ms=0,
        transport="rest",
    )


def _position_key(position: Position) -> tuple[AccountId, str, int]:
    return (position.account_id, position.symbol, position.position_idx)


def _within(ts: TsUs, start: TsUs | None, end: TsUs | None) -> bool:
    return (start is None or ts >= start) and (end is None or ts <= end)


def _seeded[K, V](table: dict[K, V], key: K, what: str) -> V:
    try:
        return table[key]
    except KeyError:
        raise NotFoundError(f"no fake {what} seeded for this account") from None
