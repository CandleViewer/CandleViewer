"""The order path's day figures from the venue (E29-T04, #913 S4-S ruling Q1; 24 Sec.9.3.6).

`DayRiskFigures` is the announced interim (`oms_interim_ports{port="risk_figures"}`) that serves
`OrderFigures` on demo and testnet until E39-T01 (#881); it refuses `live` at construction, and a
live process keeps `ports.NoDayFigures`. It answers only for its own process's environment: an
`AccountRef` of another (testnet on a demo process) gets every figure None and a CRITICAL log
naming the two environments (C-2.11). Every venue read goes through the trading port the OMS
routes its orders to (`TradingRouter.port_for`), for the `AccountRef` the size step resolved, on
the lane the adapter assigns (poll), never the stop and cancel reserve:

- equity and the available margin: the venue's wallet; a negative equity is None;
- `realised_loss_today`: the venue's closed P&L since 00:00 UTC on the injected wall clock, a loss
  as a positive figure, a net gain as 0. The adapter pages through the day inside one read, so a
  day with more records than fit in `FIGURES_READ_TIMEOUT_S` fails closed (None); reading only
  the records since the last read is E39-T01's;
- `committed_risk`: the sum of `|entry - stop| x qty` over the venue's positions and its open
  entry orders (reduce-only orders and the venue's position stops and take-profits add no risk).
  The stop distance is the stop the venue records on the item (a position's trailing distance
  when it has no stop), else the profile's fallback, `entry x fallback_sl_offset_pct`, which
  errs high. An order's `partial` stop covers part of its size only, so it counts as no stop.
  A position's `stop_loss` is taken as covering its whole `qty`; in Partial mode the venue leaves
  the position's `stopLoss` empty and its stops are `partial_stop_loss` orders, which are
  excluded, so the fallback applies (errs high). This is an assumption E39-T01 carries.
  An item with no entry, or with neither stop, makes the figure None, never 0;
- `taker_fee_rate`: the venue's taker rate per (account, symbol); an estimated rate, or one
  outside `[0, 1)`, is None;
- per symbol, the maintenance margin rate of the lowest risk-limit tier by `risk_limit_value`
  (`accounts.tiers.lowest_tier_rate`), from the catalogue's tiers, read in place.

The reads run concurrently, each within `FIGURES_READ_TIMEOUT_S` and all within
`FIGURES_BUDGET_S`; one that fails or times out gives None for its own figures only, keeps
nothing, and is logged by its figure and error type alone (balances are Confidential, C-12.6).
Figures the `AccountFigures` model refuses make every account figure None, logged as
`figures` with the error type alone.
Each answer is kept `FIGURES_TTL_S` on the injected monotonic clock. `invalidate` drops the
account's wallet, day's loss and book and bumps their generation, so a read in flight across it
answers its value but keeps none of it: the next read is the venue's. Overlapping reads on one
account are not serialised here; 24 Sec.9.3.6's overlap rule is the size step's (S4-S-b2).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar, Final

import structlog
from pydantic import ValidationError

from candleviewer.accounts.override_comparator import AccountFigures
from candleviewer.accounts.tiers import lowest_tier_rate
from candleviewer.domain.primitives import AccountId, Environment, Symbol
from candleviewer.exchange.base.models import (
    AccountRef,
    FeeRate,
    Order,
    Position,
    RiskLimitTier,
    Wallet,
)
from candleviewer.exchange.base.ports import TradingPort
from candleviewer.observability import spawn_child

from .ports import UNKNOWN_FIGURES, FiguresReading, Interim, RuntimePortName, SymbolRates

#: How long a figure read from the venue is kept, on the monotonic clock.
FIGURES_TTL_S: Final = 5.0
#: The bound on each venue read; past it the read's figures are None.
FIGURES_READ_TIMEOUT_S: Final = 2.0
#: The bound on one whole `read`, all its venue reads together. The figures are read in the size
#: step, before the send, so this is spent ahead of `oms_submit_timeout_ms` (which bounds the
#: create's `place`, 1 to 6 s) and never counts against it; it stays below that setting's 5 s
#: default, so sizing an entry never waits longer than sending it may.
FIGURES_BUDGET_S: Final = 2.5
#: The environments `DayRiskFigures` serves (ruling Q1).
_SERVED: Final[frozenset[Environment]] = frozenset({"demo", "testnet"})
#: The venue's orders that open exposure; the rest protect a position.
_ENTRY_KINDS: Final = frozenset({"order", "conditional"})
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)

type Tiers = Callable[[Symbol], Sequence[RiskLimitTier] | None]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _distance(entry: Decimal, stop: Decimal | None, fallback: Decimal | None) -> Decimal | None:
    if stop is not None:
        return abs(entry - stop)
    return None if fallback is None else entry * fallback


def committed_risk(
    positions: Iterable[Position], orders: Iterable[Order], fallback_pct: Decimal | None
) -> Decimal | None:
    """The sum of `|entry - stop| x qty` over the positions and the open entry orders; None when
    any item has no entry, or neither a recorded stop nor a fallback."""
    total = Decimal(0)
    for p in positions:
        if p.qty <= 0:
            continue
        if p.avg_entry_price is None:
            return None
        if p.stop_loss is None and p.trailing_stop_distance is not None:
            distance: Decimal | None = p.trailing_stop_distance
        else:
            distance = _distance(p.avg_entry_price, p.stop_loss, fallback_pct)
        if distance is None:
            return None
        total += distance * p.qty
    for o in orders:
        if o.order_kind not in _ENTRY_KINDS or o.reduce_only or o.leaves_qty <= 0:
            continue
        entry = o.price if o.price is not None else o.trigger_price
        if entry is None:
            return None
        stop = None if o.tpsl_mode == "partial" else o.stop_loss  # a partial stop covers part
        distance = _distance(entry, stop, fallback_pct)
        if distance is None:
            return None
        total += distance * o.leaves_qty
    return total


def _rate(value: Decimal | None) -> Decimal | None:
    """A rate `AccountFigures` accepts, `0 <= rate < 1`, else None."""
    return value if value is not None and value.is_finite() and 0 <= value < 1 else None


@dataclass(frozen=True, slots=True)
class _Kept[T]:
    value: T
    at: float


@dataclass(frozen=True, slots=True)
class _Book:
    positions: Sequence[Position]
    orders: Sequence[Order]


class DayRiskFigures(Interim):
    """`OrderFigures` from the venue's own reads, on demo and testnet only (module docstring)."""

    port: ClassVar[RuntimePortName] = "risk_figures"
    replaced_by: ClassVar[str] = "E39-T01 (#881)"
    serves: ClassVar[str] = (
        "demo and testnet day figures from the venue's reads, kept seconds; refuses live"
    )

    def __init__(
        self,
        environment: Environment,
        *,
        port_for: Callable[[Environment], TradingPort],
        tiers: Tiers,
        now: Callable[[], datetime],
        monotonic: Callable[[], float],
    ) -> None:
        if environment not in _SERVED:
            raise ValueError(f"DayRiskFigures serves demo and testnet only, not {environment!r}")
        self._environment = environment
        self._port_for, self._tiers = port_for, tiers
        self._now, self._monotonic = now, monotonic
        self._wallets: dict[AccountId, _Kept[Wallet]] = {}
        self._losses: dict[AccountId, _Kept[Decimal]] = {}
        self._books: dict[AccountId, _Kept[_Book]] = {}
        self._fees: dict[tuple[AccountId, Symbol], _Kept[FeeRate]] = {}
        self._generations: dict[tuple[str, object], int] = {}

    async def read(
        self,
        account: AccountRef,
        symbols: Sequence[Symbol],
        *,
        fallback_sl_offset_pct: Decimal | None,
    ) -> FiguresReading:
        if account.environment != self._environment:  # never another venue's account (C-2.11)
            _log().critical(
                "oms_figures_environment_mismatch",
                process_environment=self._environment,
                account_environment=account.environment,
            )
            return FiguresReading(UNKNOWN_FIGURES, dict.fromkeys(symbols, SymbolRates()))
        key, port = account.account_id, self._port_for(account.environment)
        deadline = asyncio.get_running_loop().time() + FIGURES_BUDGET_S
        unique = tuple(dict.fromkeys(symbols))
        # Each read catches its own failure, so one failing never cancels the others.
        async with asyncio.TaskGroup() as group:
            read_wallet = self._kept(
                self._wallets, key, "wallet", deadline, lambda: port.wallet(account)
            )
            wallet = spawn_child(group, read_wallet, name="oms-figures-wallet")
            read_loss = self._kept(
                self._losses, key, "day_loss", deadline, lambda: self._loss(port, account)
            )
            lost = spawn_child(group, read_loss, name="oms-figures-day-loss")
            read_book = self._kept(self._books, key, "book", deadline, lambda: _book(port, account))
            book = spawn_child(group, read_book, name="oms-figures-book")
            fees = [
                spawn_child(group, self._rates(port, account, s, deadline), name="oms-figures-fee")
                for s in unique
            ]
        return self._reading(
            wallet.result(), lost.result(), book.result(), fallback_sl_offset_pct,
            dict(zip(unique, (fee.result() for fee in fees), strict=True)),
        )  # fmt: skip

    def invalidate(self, account_id: AccountId) -> None:
        stores: dict[str, dict[AccountId, Any]] = {
            "wallet": self._wallets, "day_loss": self._losses, "book": self._books
        }  # fmt: skip
        for figure, store in stores.items():
            store.pop(account_id, None)
            slot = (figure, account_id)
            self._generations[slot] = self._generations.get(slot, 0) + 1

    @staticmethod
    def _reading(
        wallet: Wallet | None,
        lost: Decimal | None,
        book: _Book | None,
        fallback: Decimal | None,
        rates: dict[Symbol, SymbolRates],
    ) -> FiguresReading:
        held = None if book is None else committed_risk(book.positions, book.orders, fallback)
        try:
            figures = AccountFigures.model_validate(
                {
                    **dict(UNKNOWN_FIGURES),
                    "equity": None if wallet is None or wallet.equity < 0 else wallet.equity,
                    "available_margin": None if wallet is None else wallet.available_margin,
                    "realised_loss_today": lost,
                    "committed_risk": held,
                }
            )
        except ValidationError as exc:  # a figure the model refuses: unknown, type name only
            _log().warning("oms_figures_read_failed", figure="figures", error=type(exc).__name__)
            return FiguresReading(UNKNOWN_FIGURES, rates)
        return FiguresReading(figures, rates)

    async def _rates(
        self, port: TradingPort, account: AccountRef, symbol: Symbol, deadline: float
    ) -> SymbolRates:
        try:
            margin = _rate(lowest_tier_rate(self._tiers(symbol)))
        except Exception as exc:  # an unreadable catalogue: unknown, never a guessed rate
            _log().warning("oms_figures_read_failed", figure="tiers", error=type(exc).__name__)
            margin = None
        fee = await self._kept(
            self._fees, (account.account_id, symbol), "fee", deadline,
            lambda: port.fee_rate(account, symbol),
        )  # fmt: skip
        taker = None if fee is None or fee.estimated else _rate(fee.taker)
        return SymbolRates(maintenance_margin_rate=margin, taker_fee_rate=taker)

    async def _kept[K, T](
        self,
        kept: dict[K, _Kept[T]],
        key: K,
        figure: str,
        deadline: float,
        read: Callable[[], Awaitable[T]],
    ) -> T | None:
        """The figure kept under `key` while younger than `FIGURES_TTL_S`, else read again within
        `FIGURES_READ_TIMEOUT_S` and the read's `deadline`. A read that fails is None and keeps
        nothing; one that `invalidate` crossed answers its value and keeps nothing either."""
        held, now = (
            kept.get(key),
            self._monotonic(),
        )  # the stamp is the read's START: slow re-reads sooner
        if held is not None and now - held.at < FIGURES_TTL_S:
            return held.value
        kept.pop(key, None)
        generation = self._generations.get((figure, key), 0)
        loop = asyncio.get_running_loop()
        try:
            async with asyncio.timeout_at(min(loop.time() + FIGURES_READ_TIMEOUT_S, deadline)):
                value = await read()
        except Exception as exc:  # a failed or late read: unknown; a cancel propagates
            _log().warning("oms_figures_read_failed", figure=figure, error=type(exc).__name__)
            return None
        if self._generations.get((figure, key), 0) == generation:
            kept[key] = _Kept(value, now)
        return value

    async def _loss(self, port: TradingPort, account: AccountRef) -> Decimal:
        now = self._now().astimezone(UTC)
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        records = await port.closed_pnl(account, _us(midnight), _us(now))
        return max(Decimal(0), -sum((r.closed_pnl for r in records), Decimal(0)))


async def _book(port: TradingPort, account: AccountRef) -> _Book:
    positions = tuple(await port.positions(account))
    return _Book(positions, tuple(await port.open_orders(account)))


def _us(at: datetime) -> int:
    return (at - _EPOCH) // timedelta(microseconds=1)
