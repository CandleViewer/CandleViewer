"""E35-T11 slice 3b: the typed parameters of `place_order` and `scale_in` (24 §11.6; the ticket's
Technical notes: money as `Decimal` from its canonical text, never a float; extras forbidden).

A parameter set that does not parse is no request (`entry_params` answers `None`), which the
handler answers `invalid_params` with nothing sent (24 §11.5)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from candleviewer.rules.executor.params import (
    PlaceOrderParams,
    ScaleInParams,
    canonical_decimal,
    entry_params,
)
from candleviewer.rules.ir.canonical import dec_str

MARKET: dict[str, Any] = {"side": "buy", "order_type": "market", "qty_mode": "profile"}
LIMIT: dict[str, Any] = {
    "side": "sell", "order_type": "limit", "qty_mode": "explicit", "qty": "0.010",
    "price": "64000.5",
}  # fmt: skip


def _place(**over: Any) -> PlaceOrderParams:
    parsed = entry_params("place_order", MARKET | over)
    assert isinstance(parsed, PlaceOrderParams)
    return parsed


@pytest.mark.parametrize(
    ("raw", "text"),
    [
        (0.1, "0.1"),  # a float an untyped `params` holds: its shortest repr, as the IR hash reads
        (1e-7, "0.0000001"),
        (3, "3"),
        (Decimal("0.0100"), "0.01"),
        ("0.010", "0.01"),
        (" 2.50 ", "2.5"),
    ],
)
def test_money_params_are_decimal_never_float(raw: object, text: str) -> None:
    """Every money or quantity parameter is the `Decimal` of its canonical text (`dec_str`), so a
    binary float never reaches an order: `0.1` is exactly one tenth, never its binary expansion."""
    explicit = _place(qty_mode="explicit", qty=raw)
    limit = _place(order_type="limit", price=raw, stop_loss={"unit": "price", "value": raw})
    scaled = entry_params("scale_in", {"qty_pct": raw})
    assert isinstance(scaled, ScaleInParams)
    for value in (explicit.qty, limit.price, limit.stop_loss and limit.stop_loss.value,
                  scaled.qty_pct):  # fmt: skip
        assert type(value) is Decimal and value == Decimal(text) and dec_str(value) == text
    assert canonical_decimal(raw) == Decimal(text)


@pytest.mark.parametrize(
    "raw",
    [True, float("nan"), float("inf"), "NaN", "-Infinity", "abc", "", None, [1], {}, "1e70"],
)  # "1e70": finite, but its plain form passes the content hash's 64 characters
def test_a_value_with_no_canonical_decimal_is_refused(raw: object) -> None:
    assert entry_params("place_order", MARKET | {"qty_mode": "explicit", "qty": raw}) is None
    with pytest.raises((ValueError, TypeError)):
        canonical_decimal(raw)


@pytest.mark.parametrize(
    ("action_type", "params"),
    [
        ("place_order", MARKET | {"qty_mode_typo": "profile"}),
        ("place_order", MARKET | {"leverage": 10}),
        ("place_order", MARKET | {"stop_loss": {"unit": "price", "value": 1, "trail": True}}),
        ("place_order", MARKET | {"algo": {"kind": "none", "slices": 3}}),
        ("scale_in", {"qty": 1, "side": "buy"}),
        ("scale_in", {"qty_percent": 10}),
    ],
    ids=["typo", "undeclared", "offset-extra", "algo-extra", "scale-in-side", "scale-in-typo"],
)
def test_extra_params_are_refused(action_type: str, params: dict[str, Any]) -> None:
    """`extra="forbid"` at every depth: a parameter the action does not declare is no request."""
    assert entry_params(action_type, params) is None


@pytest.mark.parametrize(
    "over",
    [
        {"qty_mode": "explicit"},  # an explicit size names its qty
        {"qty": "1"},  # a profile-sized order names none
        {"qty_mode": "risk"},  # neither of 24 Sec.8.1's two modes
        {"order_type": "limit"},  # a limit order names its price
        {"price": "60000"},  # a market order names none
        {"side": "long"},
        {"qty_mode": "explicit", "qty": "0"},
        {"qty_mode": "explicit", "qty": "-1"},
        {"take_profits": [{"unit": "price", "value": 1}, {"unit": "price", "value": 2}]},
        {"algo": {"kind": "twap"}},
        {"profile": "default"},  # a profile is named by its id
        {"stop_loss": {"unit": "pips", "value": 1}},
    ],
    ids=lambda over: ",".join(f"{k}={v}" for k, v in over.items())[:40],
)
def test_place_order_reads_one_shape_only(over: dict[str, Any]) -> None:
    assert entry_params("place_order", MARKET | over) is None


def test_place_order_keeps_what_the_rule_asked_for() -> None:
    parsed = entry_params(
        "place_order",
        LIMIT | {
            "profile": "00000000-0000-4000-8000-0000000000aa",
            "stop_loss": {"unit": "percent", "value": 1.5},
            "take_profits": [{"unit": "price", "value": "70000"}],
            "algo": {"kind": "none"},
        },
    )  # fmt: skip
    assert isinstance(parsed, PlaceOrderParams)
    assert (parsed.side, parsed.order_type, parsed.qty_mode) == ("sell", "limit", "explicit")
    assert (parsed.qty, parsed.price) == (Decimal("0.01"), Decimal("64000.5"))
    assert parsed.stop_loss is not None and parsed.stop_loss.value == Decimal("1.5")
    assert [tp.value for tp in parsed.take_profits] == [Decimal("70000")]


@pytest.mark.parametrize(
    ("params", "valid"),
    [
        ({}, True),
        ({"qty": "0.5"}, True),
        ({"qty_pct": 100}, True),
        ({"qty_pct": "100.0001"}, False),
        ({"qty_pct": 0}, False),
        ({"qty": 1, "qty_pct": 10}, False),
    ],
)
def test_scale_in_names_qty_or_qty_pct_not_both(params: dict[str, Any], valid: bool) -> None:
    assert (entry_params("scale_in", params) is not None) is valid


def test_a_type_other_than_the_two_entries_has_no_params() -> None:
    assert entry_params("scale_out", {"qty": 1, "order_type": "market"}) is None
