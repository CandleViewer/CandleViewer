"""The order checks of `Validator.check_order` and `check_route` (E29-T04, #913).

The validator matrix, both directions: each instrument filter (tick size, qty step, min and max
quantity, the market ceiling, min notional, price bounds, max leverage) on the SIZED and ROUNDED
order; the read-only gate first; a figure that is not finite, refused before any is compared; a
figure above its bound, refused before any meets a step, which cannot judge one of 10**28 steps or
more, and one no step can judge all the same answered `validation_failed`, never a crash; the
trading status; the effective profile's enable flags and symbol lists (24 Sec.9.3 step 1, D11,
SR-E28-06, SR-E28-24, SR-E28-27), which hold any effect but `REDUCE` (fail closed); and the
environment match (C-2.11). Every violated filter is listed in `errors[]` with its fixed sentence,
named by the instrument field it breaks (24-internal-schemas.md Sec.1.3 rule 3), the instrument's
own filters before the order path's.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from candleviewer.accounts.profiles import AccountProfile
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.oms.errors import (
    EnvironmentMismatch,
    FieldError,
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
    ("changes", "error", "field", "rule", "message"),
    [
        (
            {"trigger_price": Decimal("63400.05")},
            TickSizeViolation,
            "trigger.price",
            "tick_size",
            "Price must be a multiple of 0.1.",
        ),
        (
            {"qty": Decimal("0.2505")},
            LotSizeViolation,
            "qty",
            "qty_step",
            "Quantity must be a multiple of 0.001.",
        ),
        (
            {"qty": Decimal("0.005")},
            LotSizeViolation,
            "qty",
            "min_order_qty",
            "Quantity must be at least 0.01.",
        ),
        (
            {"qty": Decimal("100.001")},
            LotSizeViolation,
            "qty",
            "max_order_qty",
            "Quantity must not exceed 100.",
        ),
        (
            {
                "qty": Decimal("0.010"),
                "price": Decimal("400.0"),
                "reference_price": Decimal("400.0"),
                "stop_loss": Decimal("390.0"),
            },
            LotSizeViolation,
            "qty",
            "min_notional",
            "Order notional must be at least 5.",
        ),
        (
            {"price": Decimal("0.0"), "reference_price": Decimal("1"), "stop_loss": Decimal("0.5")},
            OrderInvalid,
            "price",
            "min_price",
            "Price must be at least 0.1.",
        ),
        (
            {"price": Decimal("199999.9")},
            OrderInvalid,
            "price",
            "max_price",
            "Price must not exceed 199999.8.",
        ),
        (
            {"trigger_price": Decimal("199999.9")},
            OrderInvalid,
            "trigger.price",
            "max_price",
            "Price must not exceed 199999.8.",
        ),
        ({"price": None}, OrderInvalid, "price", "required", "A limit order needs a price."),
    ],
)
def test_each_filter_refuses_the_order_that_breaks_it(
    changes: dict[str, Any], error: type[OrderRefused], field: str, rule: str, message: str
) -> None:
    with pytest.raises(error) as refused:
        _check(_order(**changes))
    assert type(refused.value) is error
    assert refused.value.errors == (FieldError(field, rule, message),)


@pytest.mark.parametrize(
    "changes",
    [
        {"trigger_price": Decimal("63400.0")},
        {"qty": Decimal("0.250")},
        {"qty": Decimal("0.01")},  # exactly the minimum
        {"qty": Decimal("100")},  # exactly the maximum
        {
            "qty": Decimal("0.010"),
            "price": Decimal("500.0"),
            "reference_price": Decimal("500.0"),
            "stop_loss": Decimal("490.0"),
        },
        {
            "side": "sell",  # a buy at the minimum price has no stop on a tick above zero
            "price": Decimal("0.1"),
            "qty": Decimal("50"),
            "reference_price": Decimal("0.1"),
            "stop_loss": Decimal("0.2"),
        },
        {
            "price": Decimal("199999.8"),
            "reference_price": Decimal("199999.8"),
            "stop_loss": Decimal("199000.0"),
        },
    ],
)
def test_each_filter_passes_the_order_at_its_limit(changes: dict[str, Any]) -> None:
    _check(_order(**changes))


# --- a figure that is not finite, refused before any figure is compared --------------------------


@pytest.mark.parametrize("figure", ["NaN", "Infinity", "-Infinity"])
@pytest.mark.parametrize(
    ("attribute", "field", "message"),
    [
        ("price", "price", "The price must be a finite number."),
        ("trigger_price", "trigger.price", "The trigger price must be a finite number."),
        ("reference_price", "reference_price", "The reference price must be a finite number."),
        ("qty", "qty", "The quantity must be a finite number."),
    ],
)
def test_a_figure_that_is_not_finite_is_refused_before_any_filter(
    attribute: str, field: str, message: str, figure: str
) -> None:
    """An order that only reduces and carries no stop: `SizedOrder` itself refuses to judge a
    stop against a reference price that is not finite."""
    order = _order(**_REDUCE, **{attribute: Decimal(figure)})
    with pytest.raises(OrderInvalid) as refused:
        _check(order, instrument=_instrument(status="closed"))  # before the trading status too
    assert type(refused.value) is OrderInvalid
    assert refused.value.errors == (FieldError(field, "finite", message),)


def test_every_figure_that_is_not_finite_is_listed() -> None:
    nan = Decimal("NaN")
    with pytest.raises(OrderInvalid) as refused:
        _check(_order(**_REDUCE, price=nan, trigger_price=nan, reference_price=nan, qty=nan))
    assert _rules(refused.value) == [
        ("price", "finite"),
        ("trigger.price", "finite"),
        ("reference_price", "finite"),
        ("qty", "finite"),
    ]


def test_the_read_only_gate_answers_before_a_figure_that_is_not_finite() -> None:
    with pytest.raises(OrderPlacementRefused):
        _check(_order(qty=Decimal("NaN")), gate=_Gate(is_read_only=True))


# --- a figure above its bound, refused before any figure meets a step ----------------------------

_MAX_PRICE = "Price must not exceed 199999.8."
_MARKET = {"order_type": "market", "price": None}


@pytest.mark.parametrize("figure", [Decimal(10**28), Decimal(10**30)], ids=["1e28", "1e30"])
@pytest.mark.parametrize(
    ("changes", "attribute", "error", "expected"),
    [
        ({}, "price", OrderInvalid, FieldError("price", "max_price", _MAX_PRICE)),
        ({}, "trigger_price", OrderInvalid, FieldError("trigger.price", "max_price", _MAX_PRICE)),
        (
            {},
            "qty",
            LotSizeViolation,
            FieldError("qty", "max_order_qty", "Quantity must not exceed 100."),
        ),
        (
            _MARKET,
            "qty",
            LotSizeViolation,
            FieldError("qty", "max_mkt_order_qty", "A market order's quantity must not exceed 50."),
        ),
    ],
    ids=["price", "trigger_price", "qty", "market_qty"],
)
def test_a_figure_no_step_can_judge_is_refused_at_its_bound_never_a_crash(
    changes: dict[str, Any],
    attribute: str,
    error: type[OrderRefused],
    expected: FieldError,
    figure: Decimal,
) -> None:
    """A step check (`%`) raises decimal.InvalidOperation on a figure of 10**28 steps or more, so
    the bounds are judged first, before the trading status too."""
    order = _order(**changes, **{attribute: figure})
    with pytest.raises(error) as refused:
        _check(order, instrument=_instrument(status="closed"))
    assert type(refused.value) is error
    assert refused.value.errors == (expected,)


def test_every_figure_above_its_bound_is_listed() -> None:
    huge = Decimal(10**30)
    with pytest.raises(LotSizeViolation) as refused:
        _check(_order(price=huge, trigger_price=huge, qty=huge))
    assert _rules(refused.value) == [
        ("price", "max_price"),
        ("trigger.price", "max_price"),
        ("qty", "max_order_qty"),
    ]


@pytest.mark.parametrize("reference", [Decimal(10**28), Decimal(10**30)], ids=["1e28", "1e30"])
def test_a_reference_price_no_step_can_judge_is_validation_failed_never_a_crash(
    reference: Decimal,
) -> None:
    """A market order's reference price has no bound of its own: `InstrumentPolicy.validate`
    raises decimal.InvalidOperation on it, answered `validation_failed` with the cause kept."""
    with pytest.raises(OrderInvalid) as refused:
        _check(_order(**_MARKET, reference_price=reference))
    assert type(refused.value) is OrderInvalid
    assert (refused.value.detail, refused.value.errors) == ("The order failed validation.", ())
    assert isinstance(refused.value.__cause__, InvalidOperation)


def test_a_market_quantity_within_a_higher_market_ceiling_goes_on_to_the_filters() -> None:
    """Above `max_order_qty` but within the market's own ceiling: the market's to judge."""
    higher = _instrument(max_mkt_order_qty=Decimal("200"))
    _check(_order(**_MARKET, qty=Decimal("150")), instrument=higher)


def test_a_limit_quantity_above_max_order_qty_is_refused_whatever_the_market_ceiling() -> None:
    """Within a higher market ceiling, so the filters judge it, in the same sentence."""
    higher = _instrument(max_mkt_order_qty=Decimal("200"))
    with pytest.raises(LotSizeViolation) as refused:
        _check(_order(qty=Decimal("150")), instrument=higher)
    expected = FieldError("qty", "max_order_qty", "Quantity must not exceed 100.")
    assert refused.value.errors == (expected,)


def test_a_market_order_is_held_to_the_market_ceiling() -> None:
    market = {"order_type": "market", "price": None}
    _check(_order(**market, qty=Decimal("50")))
    with pytest.raises(LotSizeViolation) as refused:
        _check(_order(**market, qty=Decimal("50.001")))  # under max_order_qty, over the market's
    ceiling = "A market order's quantity must not exceed 50."
    assert refused.value.errors == (FieldError("qty", "max_mkt_order_qty", ceiling),)


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
    stop = Decimal("390")  # below either reference price, as a buy's stop is
    _check(_order(**market, reference_price=Decimal("500"), stop_loss=stop))
    with pytest.raises(LotSizeViolation) as refused:
        _check(_order(**market, reference_price=Decimal("400"), stop_loss=stop))
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


def test_the_instruments_filters_are_listed_before_the_order_paths_own() -> None:
    """The policy's violations (price, qty) come first, then the order path's (the trigger)."""
    order = _order(
        price=Decimal("63100.05"), trigger_price=Decimal("63400.05"), qty=Decimal("0.2505")
    )
    with pytest.raises(TickSizeViolation) as refused:
        _check(order)
    assert _rules(refused.value) == [
        ("price", "tick_size"),
        ("qty", "qty_step"),
        ("trigger.price", "tick_size"),
    ]


def test_a_market_orders_lot_step_is_listed_before_its_ceiling() -> None:
    with pytest.raises(LotSizeViolation) as refused:
        _check(_order(order_type="market", price=None, qty=Decimal("50.0005")))
    assert _rules(refused.value) == [("qty", "qty_step"), ("qty", "max_mkt_order_qty")]


# --- leverage (entries only) ---------------------------------------------------------------------


def test_an_entry_above_the_instruments_max_leverage_is_refused() -> None:
    with pytest.raises(OrderInvalid) as refused:
        _check(instrument=_instrument(max_leverage=Decimal("9.99")))  # the profile's is 10
    message = "The profile's leverage must not exceed 9.99 on this symbol."
    assert refused.value.errors == (FieldError("leverage", "max_leverage", message),)


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
    message = f"BTCUSDT is not currently trading (status: {status})."
    assert refused.value.errors == (FieldError("symbol", "status", message),)


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
    assert refused.value.detail == "The account's profile does not allow this symbol."


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
    with pytest.raises(RiskRefused) as refused:
        validator.check_order(_order(), instrument=_instrument(), profile=None)
    assert refused.value.detail == "No profile allows this order."


# --- the profile's enable flags (24 Sec.9.3 step 1, SR-E28-27) -----------------------------------


@pytest.mark.parametrize(
    ("enabled", "trading_enabled"), [(False, True), (True, False), (False, False)]
)
def test_an_entry_under_a_profile_not_enabled_for_trading_is_refused(
    enabled: bool, trading_enabled: bool
) -> None:
    profile = _profile(enabled=enabled, trading_enabled=trading_enabled)
    with pytest.raises(RiskRefused) as refused:
        _check(profile=profile)
    assert refused.value.errors == ()
    assert refused.value.detail == "The account's profile is not enabled for trading."


def test_the_enable_flags_answer_before_the_symbol_lists() -> None:
    eth = _instrument(symbol="ETHUSDT", base_coin="ETH")
    with pytest.raises(RiskRefused) as refused:
        _check(_order(symbol="ETHUSDT"), instrument=eth, profile=_profile(trading_enabled=False))
    assert refused.value.detail == "The account's profile is not enabled for trading."


@pytest.mark.parametrize(
    ("enabled", "trading_enabled"), [(False, True), (True, False), (False, False)]
)
def test_an_order_that_only_reduces_is_never_refused_by_the_enable_flags(
    enabled: bool, trading_enabled: bool
) -> None:
    """SR-E28-24, SR-E28-27: a risk-reducing order is exempt."""
    _check(_order(**_REDUCE), profile=_profile(enabled=enabled, trading_enabled=trading_enabled))


def test_an_order_that_only_reduces_is_never_refused_by_the_allow_list() -> None:
    validator = Validator(read_only_gate=_Gate())
    eth = _instrument(symbol="ETHUSDT", base_coin="ETH")
    validator.check_order(_order(**_REDUCE, symbol="ETHUSDT"), instrument=eth, profile=_profile())
    validator.check_order(_order(**_REDUCE), instrument=_instrument(), profile=None)


@pytest.mark.parametrize("effect", ["entry", "bogus"])
def test_check_order_holds_any_effect_but_reduce_to_the_entry_checks(effect: str) -> None:
    """Fail closed: an effect that is not the `REDUCE` member is an entry's, so the reduce
    exemption never applies to it. Forced past `SizedOrder`'s own coercion, as only a type
    violation can produce it."""
    order = _order(**_REDUCE)
    object.__setattr__(order, "effect", effect)
    validator = Validator(read_only_gate=_Gate())
    with pytest.raises(RiskRefused) as refused:
        validator.check_order(order, instrument=_instrument(), profile=None)
    assert refused.value.detail == "No profile allows this order."


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
