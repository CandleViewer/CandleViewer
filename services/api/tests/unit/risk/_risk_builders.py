"""Builders for the E39-T01 evaluator tests: a roomy baseline that every check admits."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, UserId
from candleviewer.risk.caps import ManagerCaps, PolicyCaps, ProfileCaps, ResolvedCaps, resolve_caps
from candleviewer.risk.clock import DayCalendar
from candleviewer.risk.counters import AccountCounters
from candleviewer.risk.evaluator import RiskEvaluation, evaluate
from candleviewer.risk.inputs import RiskFigures, RiskFill, RiskMark, RiskOrder

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
D = Decimal


def policy(**fields: Any) -> PolicyCaps:
    base = PolicyCaps(
        max_total_notional_usd=D(1_000_000),
        max_daily_loss_usd=D(10_000),
        max_drawdown_pct=D(50),
        max_open_positions=50,
        max_leverage=D(100),
        max_orders_per_minute=600,
        per_symbol_concentration_pct=D(100),
        breach_behaviour={},
    )
    return replace(base, **fields)


def profile(**fields: Any) -> ProfileCaps:
    return replace(ProfileCaps(all_symbols=True), **fields)


def caps(
    pol: dict[str, Any] | None = None,
    prof: dict[str, Any] | None = None,
    mgr: ManagerCaps | None = None,
) -> ResolvedCaps:
    return resolve_caps(policy(**(pol or {})), profile(**(prof or {})), mgr)


def figures(**fields: Any) -> RiskFigures:
    base = RiskFigures(
        as_of=NOW,
        equity=D(100_000),
        day_start_equity=D(100_000),
        daily_figure=D(0),
        day_peak_figure=D(0),
        open_positions=0,
        open_orders=0,
        orders_last_minute=0,
        consecutive_losses=0,
    )
    return replace(base, **fields)


def instrument(symbol: str = "BTCUSDT", **fields: Any) -> Instrument:
    """A trading linear USDT perpetual unless `fields` say otherwise."""
    base: dict[str, Any] = {
        "symbol": symbol,
        "base_coin": "BTC",
        "quote_coin": "USDT",
        "settle_coin": "USDT",
        "status": "trading",
        "contract_type": "linear_perpetual",
        "launch_time": 0,
        "tick_size": D("0.1"),
        "price_scale": 1,
        "min_price": D("0.1"),
        "max_price": D("199999.8"),
        "qty_step": D("0.001"),
        "min_order_qty": D("0.001"),
        "max_order_qty": D(100),
        "max_mkt_order_qty": D(50),
        "min_notional": D(5),
        "max_leverage": D(100),
        "min_leverage": D(1),
        "leverage_step": D("0.01"),
        "funding_interval_min": 480,
        "upper_funding_rate": D("0.00375"),
        "lower_funding_rate": D("-0.00375"),
        "copy_trading": False,
        "metadata_version": 1,
        "fetched_at": 0,
    }
    return Instrument.model_validate(base | fields)


_BTCUSDT = instrument()


def order(**fields: Any) -> RiskOrder:
    """A notional given alone is priced at 1, so it stays `qty` at the reference price."""
    if "notional" in fields and not {"qty", "reference_price"} & fields.keys():
        fields = {"qty": fields["notional"], "reference_price": D(1), **fields}
    base = RiskOrder(
        account_id=AccountId(UUID(int=1)),
        environment="demo",
        paper=False,
        user_id=UserId(UUID(int=2)),
        instrument=_BTCUSDT,
        side="buy",
        qty=D("0.1"),
        reference_price=D(100_000),
        notional=D(10_000),
        reduce_only=False,
        opens_exposure=True,
        opens_position=True,
    )
    return replace(base, **fields)


def close_order() -> RiskOrder:
    return order(reduce_only=True, opens_exposure=False, opens_position=False, side="sell")


def run(
    o: RiskOrder | None = None, f: RiskFigures | None = None, c: ResolvedCaps | None = None
) -> RiskEvaluation:
    return evaluate(o or order(), f or figures(), c or caps(), now=NOW)


# Slice 2: counters, marks and fills on the default UTC day key of `NOW`.
TAKER = D("0.00055")


def counters(now: datetime = NOW, *, taker: Decimal = TAKER, offset: int = 0) -> AccountCounters:
    c = AccountCounters(DayCalendar(offset, now), taker_rate=taker)
    c.set_equity(D(100_000), now)
    c.mark_ready()
    return c


def fill(exec_id: str, **fields: Any) -> RiskFill:
    base = RiskFill(
        exec_id=exec_id,
        order_ref="o1",
        symbol="BTCUSDT",
        position_side="buy",
        opening=False,
        qty=D(1),
        price=D(100),
        fee=D(0),
        fee_rate=D(0),
        exec_time=NOW,
        exec_pnl=D(0),
    )
    return replace(base, **fields)


def mark(price: Decimal | int, at: datetime = NOW, **fields: Any) -> RiskMark:
    return replace(RiskMark("BTCUSDT", D(price), at, "public"), **fields)
