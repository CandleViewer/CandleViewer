"""The order checks of `Validator.check_order` and `check_route` (E29-T04, #913).

The validator matrix, both directions: each instrument filter (tick size, qty step, min and max
quantity, the market ceiling, min notional, price bounds, max leverage) on the SIZED and ROUNDED
order; the read-only gate first; the trading status; the effective profile's symbol allow-list
(D11, SR-E28-06, SR-E28-24); and the environment match (C-2.11). Every violated filter is listed
in `errors[]`, named by the instrument field it breaks (24-internal-schemas.md Sec.1.3 rule 3).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from candleviewer.accounts.profiles import AccountProfile
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.oms.errors import (
    EnvironmentMismatch,
    LotSizeViolation,
    OrderInvalid,
    OrderRefused,
    RiskRefused,
    TickSizeViolation,
    TradingDisabled,
)
from candleviewer.oms.ports import OrderEffect, SizedOrder
from candleviewer.oms.validator import OrderPlacementRefused, Validator, symbol_allowed

ACCOUNT = AccountId(UUID("7d3c9a10-28a1-4c1e-9e01-0000000000a2"))
_PROFILES = Path(__file__).resolve().parents[2] / "fixtures" / "profiles"


class _Gate:
    def __init__(self, *, is_read_only: bool = False) -> None:
        self.is_read_only = is_read_only
        self.reason_code: str | None = None
        self.reason_text: str | None = None


def _instrument(**overrides: object) -> Instrument:
    base: dict[str, object] = {
        "symbol": "BTCUSDT",
        "base_coin": "BTC",
        "quote_coin": "USDT",
        "settle_coin": "USDT",
        "status": "trading",
        "contract_type": "linear_perpetual",
        "launch_time": 0,
        "tick_size": Decimal("0.1"),
        "price_scale": 1,
        "min_price": Decimal("0.1"),
        "max_price": Decimal("199999.8"),
        "qty_step": Decimal("0.001"),
        "min_order_qty": Decimal("0.01"),
        "max_order_qty": Decimal("100"),
        "max_mkt_order_qty": Decimal("50"),
        "min_notional": Decimal("5"),
        "max_leverage": Decimal("100"),
        "min_leverage": Decimal("1"),
        "leverage_step": Decimal("0.01"),
        "funding_interval_min": 480,
        "upper_funding_rate": Decimal("0.00375"),
        "lower_funding_rate": Decimal("-0.00375"),
        "copy_trading": False,
        "metadata_version": 1,
        "fetched_at": 0,
    }
    base.update(overrides)
    return Instrument.model_validate(base)


def _profile(mode: str = "fixed_qty", **changes: Any) -> AccountProfile:
    raw = json.loads((_PROFILES / f"{mode}.json").read_text(encoding="utf-8"))
    return AccountProfile.model_validate({**raw, **changes})


def _order(**changes: Any) -> SizedOrder:
    base: dict[str, Any] = {
        "account_id": ACCOUNT,
        "environment": "demo",
        "symbol": "BTCUSDT",
        "side": "buy",
        "order_type": "limit",
        "qty": Decimal("0.250"),
        "price": Decimal("63100.0"),
        "trigger_price": None,
        "reference_price": Decimal("63100.0"),
        "reduce_only": False,
        "intent": "entry",
        "effect": OrderEffect.ENTRY,
        "stop_loss": Decimal("62900.0"),
    }
    return SizedOrder(**{**base, **changes})


_REDUCE: dict[str, Any] = {
    "reduce_only": True,
    "effect": OrderEffect.REDUCE,
    "intent": "scale_out",
    "side": "sell",
    "stop_loss": None,
}


def _check(
    order: SizedOrder | None = None,
    *,
    instrument: Instrument | None = None,
    profile: AccountProfile | None = None,
    gate: _Gate | None = None,
) -> None:
    validator = Validator(read_only_gate=gate or _Gate())
    validator.check_order(
        order or _order(),
        instrument=instrument or _instrument(),
        profile=profile if profile is not None else _profile(),
    )


def _rules(refused: OrderRefused) -> list[tuple[str, str]]:
    return [(e.field, e.rule) for e in refused.errors]


def test_a_valid_sized_order_passes_every_check() -> None:
    _check()


# --- the instrument filters, both directions -----------------------------------------------------


def test_filters_are_enforced_before_any_exchange_call() -> None:
    """Scenario "Filters are enforced before any exchange call": a price off its tick."""
    with pytest.raises(TickSizeViolation) as refused:
        _check(_order(price=Decimal("63100.05")))
    assert _rules(refused.value) == [("price", "tick_size")]
    assert refused.value.errors[0].message == "Price must be a multiple of 0.1."


@pytest.mark.parametrize(
    ("changes", "error", "rules"),
    [
        (
            {"trigger_price": Decimal("63400.05")},
            TickSizeViolation,
            [("trigger.price", "tick_size")],
        ),
        ({"qty": Decimal("0.2505")}, LotSizeViolation, [("qty", "qty_step")]),
        ({"qty": Decimal("0.005")}, LotSizeViolation, [("qty", "min_order_qty")]),
        ({"qty": Decimal("100.001")}, LotSizeViolation, [("qty", "max_order_qty")]),
        (
            {
                "qty": Decimal("0.010"),
                "price": Decimal("400.0"),
                "reference_price": Decimal("400.0"),
            },
            LotSizeViolation,
            [("qty", "min_notional")],
        ),
        (
            {"price": Decimal("0.0"), "reference_price": Decimal("1")},
            OrderInvalid,
            [("price", "min_price")],
        ),
        ({"price": Decimal("199999.9")}, OrderInvalid, [("price", "max_price")]),
        ({"trigger_price": Decimal("199999.9")}, OrderInvalid, [("trigger.price", "max_price")]),
        ({"price": None}, OrderInvalid, [("price", "required")]),
    ],
)
def test_each_filter_refuses_the_order_that_breaks_it(
    changes: dict[str, Any], error: type[OrderRefused], rules: list[tuple[str, str]]
) -> None:
    with pytest.raises(error) as refused:
        _check(_order(**changes))
    assert type(refused.value) is error
    assert _rules(refused.value) == rules


@pytest.mark.parametrize(
    "changes",
    [
        {"trigger_price": Decimal("63400.0")},
        {"qty": Decimal("0.250")},
        {"qty": Decimal("0.01")},  # exactly the minimum
        {"qty": Decimal("100")},  # exactly the maximum
        {"qty": Decimal("0.010"), "price": Decimal("500.0"), "reference_price": Decimal("500.0")},
        {"price": Decimal("0.1"), "qty": Decimal("50"), "reference_price": Decimal("0.1")},
        {"price": Decimal("199999.8"), "stop_loss": Decimal("199000.0")},
    ],
)
def test_each_filter_passes_the_order_at_its_limit(changes: dict[str, Any]) -> None:
    _check(_order(**changes))


def test_a_market_order_is_held_to_the_market_ceiling() -> None:
    market = {"order_type": "market", "price": None}
    _check(_order(**market, qty=Decimal("50")))
    with pytest.raises(LotSizeViolation) as refused:
        _check(_order(**market, qty=Decimal("50.001")))  # under max_order_qty, over the market's
    assert _rules(refused.value) == [("qty", "max_mkt_order_qty")]


def test_a_market_order_above_both_ceilings_is_listed_once() -> None:
    with pytest.raises(LotSizeViolation) as refused:
        _check(_order(order_type="market", price=None, qty=Decimal("150")))
    assert _rules(refused.value) == [("qty", "max_mkt_order_qty")]


def test_a_market_orders_reference_price_is_not_held_to_the_tick() -> None:
    """A market order has no price of its own: its reference (a mid may sit between ticks) only
    measures the notional."""
    _check(_order(order_type="market", price=None, reference_price=Decimal("63100.05")))


def test_a_market_orders_notional_is_measured_at_its_reference_price() -> None:
    market = {"order_type": "market", "price": None, "qty": Decimal("0.01")}
    _check(_order(**market, reference_price=Decimal("500")))
    with pytest.raises(LotSizeViolation) as refused:
        _check(_order(**market, reference_price=Decimal("400")))
    assert _rules(refused.value) == [("qty", "min_notional")]


def test_every_violated_filter_is_listed_and_the_tick_answers_first() -> None:
    with pytest.raises(TickSizeViolation) as refused:
        _check(_order(price=Decimal("63100.05"), qty=Decimal("0.0055")))
    assert _rules(refused.value) == [
        ("price", "tick_size"),
        ("qty", "qty_step"),
        ("qty", "min_order_qty"),
    ]


def test_a_lot_violation_answers_before_the_leverage_and_lists_it() -> None:
    with pytest.raises(LotSizeViolation) as refused:
        _check(_order(qty=Decimal("0.005")), instrument=_instrument(max_leverage=Decimal("5")))
    assert _rules(refused.value) == [("qty", "min_order_qty"), ("leverage", "max_leverage")]


# --- leverage (entries only) ---------------------------------------------------------------------


def test_an_entry_above_the_instruments_max_leverage_is_refused() -> None:
    with pytest.raises(OrderInvalid) as refused:
        _check(instrument=_instrument(max_leverage=Decimal("9.99")))  # the profile's is 10
    assert _rules(refused.value) == [("leverage", "max_leverage")]


def test_an_entry_at_the_instruments_max_leverage_passes() -> None:
    _check(instrument=_instrument(max_leverage=Decimal("10")))


def test_an_order_that_only_reduces_is_not_held_to_the_leverage() -> None:
    _check(_order(**_REDUCE), instrument=_instrument(max_leverage=Decimal("2")))


# --- the read-only gate and the trading status ---------------------------------------------------


def test_check_order_runs_the_read_only_gate_first() -> None:
    gate = _Gate(is_read_only=True)
    with pytest.raises(OrderPlacementRefused) as refused:
        _check(_order(price=Decimal("63100.05")), gate=gate)  # off its tick too
    assert isinstance(refused.value, TradingDisabled)
    assert refused.value.reason_code == "net.read_only"


@pytest.mark.parametrize("status", ["pre_launch", "delivering", "closed"])
def test_a_symbol_that_is_not_trading_is_refused_before_the_allow_list(status: str) -> None:
    with pytest.raises(OrderInvalid) as refused:
        _check(instrument=_instrument(status=status), profile=_profile(allowed_symbols=[]))
    assert _rules(refused.value) == [("symbol", "status")]


def test_a_symbol_that_is_not_trading_refuses_an_order_that_only_reduces_too() -> None:
    with pytest.raises(OrderInvalid):
        _check(_order(**_REDUCE), instrument=_instrument(status="closed"))


def test_check_order_refuses_an_instrument_of_another_symbol() -> None:
    with pytest.raises(ValueError, match="instrument"):
        _check(instrument=_instrument(symbol="ETHUSDT"))


# --- the symbol allow-list (D11, SR-E28-06, SR-E28-24) -------------------------------------------


def test_a_listed_symbol_is_allowed() -> None:
    assert symbol_allowed(_profile("fixed_qty"), _instrument())  # allowed_symbols: [BTCUSDT]


def test_an_unlisted_symbol_is_refused_with_risk_limit_breached() -> None:
    eth = _instrument(symbol="ETHUSDT", base_coin="ETH")
    with pytest.raises(RiskRefused) as refused:
        _check(_order(symbol="ETHUSDT"), instrument=eth)
    assert refused.value.errors == ()


def test_an_empty_allow_list_without_all_symbols_allows_nothing() -> None:
    assert not symbol_allowed(_profile(allowed_symbols=[]), _instrument())


def test_all_symbols_allows_every_symbol_but_the_denied() -> None:
    profile = _profile("pct_equity")  # all_symbols, DOGEUSDT denied
    assert symbol_allowed(profile, _instrument())
    assert not symbol_allowed(profile, _instrument(symbol="DOGEUSDT", base_coin="DOGE"))


def test_a_suffix_pattern_matches_a_trading_usdt_perpetual() -> None:
    profile = _profile("fixed_notional")  # allowed_symbols: ["*USDT"]
    assert symbol_allowed(profile, _instrument(symbol="SOLUSDT", base_coin="SOL"))


@pytest.mark.parametrize(
    "overrides",
    [
        {"settle_coin": "USDC"},
        {"quote_coin": "USDC"},
        {"status": "closed"},
    ],
)
def test_a_suffix_pattern_never_matches_outside_trading_usdt_perpetuals(
    overrides: dict[str, Any],
) -> None:
    assert not symbol_allowed(_profile("fixed_notional"), _instrument(**overrides))


def test_a_suffix_pattern_needs_a_symbol_longer_than_its_suffix() -> None:
    profile = _profile("fixed_notional", allowed_symbols=["*BTCUSDT"])
    assert not symbol_allowed(profile, _instrument())


def test_the_deny_list_applies_after_the_allow_list_patterns_included() -> None:
    assert not symbol_allowed(_profile(denied_symbols=["BTCUSDT"]), _instrument())
    denied = _profile("pct_equity", denied_symbols=["*USDT"])
    assert not symbol_allowed(denied, _instrument(settle_coin="USDC"))  # deny matches widely


def test_an_entry_without_a_profile_is_refused() -> None:
    validator = Validator(read_only_gate=_Gate())
    with pytest.raises(RiskRefused):
        validator.check_order(_order(), instrument=_instrument(), profile=None)


def test_an_order_that_only_reduces_is_never_refused_by_the_allow_list() -> None:
    validator = Validator(read_only_gate=_Gate())
    eth = _instrument(symbol="ETHUSDT", base_coin="ETH")
    validator.check_order(_order(**_REDUCE, symbol="ETHUSDT"), instrument=eth, profile=_profile())
    validator.check_order(_order(**_REDUCE), instrument=_instrument(), profile=None)


# --- the environment match (C-2.11) --------------------------------------------------------------


@pytest.mark.parametrize(
    ("order_env", "route_env"),
    [("demo", "live"), ("live", "demo"), ("testnet", "live"), ("demo", "testnet")],
)
def test_check_route_refuses_an_order_routed_to_another_environment(
    order_env: Environment, route_env: Environment
) -> None:
    with pytest.raises(EnvironmentMismatch) as refused:
        Validator.check_route(order_env, route_env)
    assert (refused.value.order_environment, refused.value.route_environment) == (
        order_env,
        route_env,
    )


@pytest.mark.parametrize("environment", ["demo", "live", "testnet"])
def test_check_route_passes_an_order_on_its_own_environment(environment: Environment) -> None:
    Validator.check_route(environment, environment)
