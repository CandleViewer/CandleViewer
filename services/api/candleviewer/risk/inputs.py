"""The evaluator's own input types (E39-T01, M17).

`risk/` may not import `oms` or `exchange.base` (`.importlinter` M17), so the order and the
figures the gate judges are defined here and adapted to by the OMS. Frozen, slotted and plain: they
are built once per order on the order path, so they carry no validation cost; `evaluate` refuses
malformed values itself (non-finite, negative, tz-naive). Money is `Decimal`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, Environment, Side, UserId


@dataclass(frozen=True, slots=True)
class RiskOrder:
    """One order as the gate sees it; the OMS derives every field server-side.

    `reduce_only`, `opens_exposure` and `opens_position` come from the outbound order and its
    computed effect, never from a label or a client field: only an order that is reduce-only *and*
    opens no exposure and no position is exempt from the caps (SR-E39-02), so a reduce-only flag on
    an order that opens or flips is never exempt. `opens_position` is true when the order opens a
    position the account does not hold (a new symbol, or in hedge mode a new side), and counts
    toward `max_open_positions`.
    """

    account_id: AccountId
    environment: Environment
    paper: bool
    user_id: UserId | None  # the acting user; None for a system origin (no manager override)
    instrument: Instrument  # the catalogue's row: a symbol pattern matches only a USDT perpetual
    side: Side
    qty: Decimal
    reference_price: Decimal
    notional: Decimal  # absolute USDT notional the order adds when it opens exposure
    reduce_only: bool
    opens_exposure: bool
    opens_position: bool

    @property
    def symbol(self) -> str:
        return self.instrument.symbol

    @property
    def exempt(self) -> bool:
        """Reduce-only and opening nothing: every check is skipped (US-PROF-004, US-ADMIN-003)."""
        return self.reduce_only and not self.opens_exposure and not self.opens_position


@dataclass(frozen=True, slots=True)
class RiskFigures:
    """One account's figures at `as_of`, the counters' snapshot the evaluator reads.

    `daily_figure` is the day's blocking PnL figure (realised today plus the unrealised loss, never
    an unrealised gain; E39-K01 §5): a loss is negative. `day_peak_figure` is its high this day key,
    the drawdown's reference. `symbol_notional` is the gross open notional per symbol, frozen only
    shallowly: the caller hands over a mapping it no longer mutates. `as_of` is stamped by the same
    injected clock that gives `evaluate` its `now`.
    """

    as_of: datetime
    equity: Decimal | None
    day_start_equity: Decimal | None
    daily_figure: Decimal
    day_peak_figure: Decimal
    open_positions: int
    open_orders: int
    orders_last_minute: int
    consecutive_losses: int
    symbol_notional: Mapping[str, Decimal] = field(default_factory=dict)
    lockout_active: bool = False
    kill_switch_engaged: bool = False

    @property
    def gross_notional(self) -> Decimal:
        return sum(self.symbol_notional.values(), Decimal(0))


# The stream events the counters read (E39-K01 §5). The adapter builds them from the private
# stream, a REST backfill or the reconcile cycle; `risk/` never sees an exchange type.


@dataclass(frozen=True, slots=True)
class RiskFill:
    """One execution: it opens or closes `position_side`'s position (buy = long).

    A fill that flips a one-way position arrives as two fills. `fee` is the paid `execFee`,
    `fee_rate` the pushed `feeRate`. `exec_pnl` is the closing push's price PnL, None for a REST
    backfill, then booked from `entry_price` (the projection's average entry) and unconfirmed.
    """

    exec_id: str
    order_ref: str  # the order the fill belongs to: one close is all of an order's closing fills
    symbol: str
    position_side: Side
    opening: bool
    qty: Decimal
    price: Decimal
    fee: Decimal
    fee_rate: Decimal
    exec_time: datetime  # exchange `execTime`: the fill's date, never its receive time
    exec_pnl: Decimal | None = None
    entry_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class RiskPosition:
    """A position push: authoritative over the fills when it is at least as new as them."""

    symbol: str
    side: Side
    size: Decimal
    entry_price: Decimal
    at: datetime


@dataclass(frozen=True, slots=True)
class RiskMark:
    """A mark price: the cached public mark, or the `markPrice` of a private position push."""

    symbol: str
    price: Decimal
    at: datetime
    source: Literal["public", "position"]


@dataclass(frozen=True, slots=True)
class VenueClosedPnl:
    """One venue closed-PnL record, matched to a local close by the interim key (K01 §5.4)."""

    record_id: str
    symbol: str
    position_side: Side
    qty: Decimal
    avg_exit_price: Decimal
    tick: Decimal  # the instrument tick the average exit price is compared at
    pnl: Decimal
    updated_at: datetime
