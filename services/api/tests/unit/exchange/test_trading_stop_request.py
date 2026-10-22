"""`TradingStopRequest`'s sizes (G-8b, #3963; 24 §8.9 and §14.4, the slice-2b rulings in
RelayRoom [LANE-20]): a size is a Partial-mode stop's alone, a positive number beside its side's
price, every Partial-mode price has its size, and the venue requires the two sizes equal. The
request refuses anything else when it is built, so no port is ever handed one to sign."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from pydantic import ValidationError

from candleviewer.exchange.base.models import TradingStopRequest
from tests.unit.exchange.bybit._trading import account

SL, TP = Decimal("58000"), Decimal("65000")


def _stop(**fields: Any) -> TradingStopRequest:
    return TradingStopRequest(account=account(), symbol="BTCUSDT", **fields)


def test_a_full_mode_stop_takes_no_size_and_defaults_to_none() -> None:
    stop = _stop(stop_loss=SL, take_profit=TP)
    assert (stop.tpsl_mode, stop.tp_size, stop.sl_size) == ("full", None, None)


@pytest.mark.parametrize(
    "fields",
    [
        {"stop_loss": SL, "sl_size": Decimal("0.5")},
        {"take_profit": TP, "tp_size": Decimal("0.5")},
        {"stop_loss": SL, "sl_size": Decimal("0.5"), "take_profit": TP, "tp_size": Decimal("0.50")},
        {"trailing_distance": Decimal("150")},  # no price, so no size
    ],
    ids=["stop-loss", "take-profit", "both-equal", "trailing-only"],
)
def test_a_partial_mode_stop_sends_each_price_with_its_size(fields: dict[str, Any]) -> None:
    stop = _stop(tpsl_mode="partial", **fields)
    assert (stop.tp_size, stop.sl_size) == (fields.get("tp_size"), fields.get("sl_size"))


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"stop_loss": SL, "sl_size": Decimal("1")}, "takes no size"),
        ({"take_profit": TP, "tp_size": Decimal("1")}, "takes no size"),
    ],
    ids=["sl-size", "tp-size"],
)
def test_a_full_mode_stop_refuses_a_size(fields: dict[str, Any], reason: str) -> None:
    """Full mode covers the whole position: a size there is a caller's mistake, refused rather
    than dropped, so no stop is ever sent other than as asked."""
    with pytest.raises(ValidationError, match=reason):
        _stop(tpsl_mode="full", **fields)


@pytest.mark.parametrize(
    ("fields", "reason"),
    [
        ({"stop_loss": SL}, "each price with its size"),
        ({"take_profit": TP}, "each price with its size"),
        ({"sl_size": Decimal("1")}, "each price with its size"),
        ({"stop_loss": SL, "sl_size": Decimal("0")}, "positive"),
        ({"stop_loss": SL, "sl_size": Decimal("-1")}, "positive"),
        ({"take_profit": TP, "tp_size": Decimal("0")}, "positive"),
        (
            {"stop_loss": SL, "sl_size": Decimal("1"), "take_profit": TP, "tp_size": Decimal("2")},
            "two sizes are equal",
        ),
    ],
    ids=["sl-unsized", "tp-unsized", "size-alone", "zero", "negative", "tp-zero", "unequal"],
)
def test_a_partial_mode_stop_refuses_a_size_out_of_place(
    fields: dict[str, Any], reason: str
) -> None:
    with pytest.raises(ValidationError, match=reason):
        _stop(tpsl_mode="partial", **fields)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_a_size_that_is_no_finite_number_is_refused(value: str) -> None:
    with pytest.raises(ValidationError):
        _stop(tpsl_mode="partial", stop_loss=SL, sl_size=Decimal(value))
