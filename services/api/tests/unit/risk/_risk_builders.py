"""Builders for the E39-T01 evaluator tests: a roomy baseline that every check admits."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from candleviewer.domain.primitives import AccountId, UserId
from candleviewer.risk.caps import ManagerCaps, PolicyCaps, ProfileCaps, ResolvedCaps, resolve_caps
from candleviewer.risk.evaluator import RiskEvaluation, evaluate
from candleviewer.risk.inputs import RiskFigures, RiskOrder

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


def order(**fields: Any) -> RiskOrder:
    """A notional given alone is priced at 1, so it stays `qty` at the reference price."""
    if "notional" in fields and not {"qty", "reference_price"} & fields.keys():
        fields = {"qty": fields["notional"], "reference_price": D(1), **fields}
    base = RiskOrder(
        account_id=AccountId(UUID(int=1)),
        environment="demo",
        paper=False,
        user_id=UserId(UUID(int=2)),
        symbol="BTCUSDT",
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
