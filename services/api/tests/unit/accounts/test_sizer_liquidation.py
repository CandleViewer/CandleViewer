"""E28-T03 (#907): the one liquidation estimate (24 Sec.9.3.6) and the leg refusal
`stop_beyond_liquidation` (SR-E28-26, F-15, PF-D06; the E28 threat model's AC-27)."""

from __future__ import annotations

import functools
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from candleviewer.accounts import sizer as sz
from tests.unit.accounts.test_sizer import profile, sized, wallet

D = Decimal
_VECTORS: Final = json.loads(
    (Path(__file__).parent / "golden" / "e28_liquidation_vectors.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("v", _VECTORS, ids=[v["id"] for v in _VECTORS])
def test_liquidation_estimate_matches_the_frozen_vectors(v: dict[str, Any]) -> None:
    got = sz.liquidation_estimate(v["side"], D(v["entry"]), D(v["leverage"]), D(v["mmr"]))
    assert got == D(v["liquidation"])
    edge = sz.liquidation_edge(v["side"], D(v["entry"]), got, D(v["tick"]))
    assert edge == D(v["edge"])  # SR-E28-26's buffer: 10 % of the distance, at least a tick


def test_stop_beyond_liquidation_is_refused() -> None:
    """AC-27: a 50x profile on the 2 % fallback stop (62720) lies past the estimate (63040)."""
    got = sized(profile("P-PCT", leverage="50", max_leverage_cap="50"))
    assert (got.outcome, got.reason) == ("fail", sz.FailReason.STOP_BEYOND_LIQUIDATION)
    assert (got.stop_fallback, got.liquidation_price) == (True, D(63040))
    assert got.qty is not None and got.qty > 0  # sized, then refused: the explanation stays


def test_stop_beyond_liquidation_refuses_a_short_and_a_stop_at_the_estimate() -> None:
    short = sized(
        profile("P-PCT", leverage="50", max_leverage_cap="50"), side="sell"
    )  # 65280 past 64960
    assert (short.reason, short.liquidation_price) == (
        sz.FailReason.STOP_BEYOND_LIQUIDATION,
        D(64960),
    )
    # 64000 x (1 - 1/50 + 0.0005) = 62752, and 12480 ticks of 0.1 below 64000 is 62752
    at = profile(
        "P-QTY",
        sl_offset_unit="ticks",
        sl_offset_value="12480",
        leverage="50",
        max_leverage_cap="50",
    )
    got = sized(at, wallet(maintenance_margin_rate="0.0005"))
    assert (got.stop, got.liquidation_price) == (
        sz.ResolvedStop(D(62752), D(1248), fallback=False),
        D(62752),
    )
    assert got.reason is sz.FailReason.STOP_BEYOND_LIQUIDATION  # equality races it


def test_stop_inside_liquidation_is_ok_and_records_the_estimate() -> None:
    got = sized(profile("P-PCT"))  # 10x: the 2 % fallback is well inside 57920
    assert (got.outcome, got.liquidation_price) == ("ok", D(57920))


def test_unknown_maintenance_margin_rate_fails_closed() -> None:
    got = sized(profile("P-PCT"), wallet(maintenance_margin_rate=None))
    assert (got.outcome, got.reason, got.liquidation_price) == (
        "fail",
        sz.FailReason.FIGURE_UNKNOWN,
        None,
    )


@pytest.mark.parametrize(
    ("side", "leverage"),
    [("buy", D(0)), ("buy", D(-1)), ("hold", D(10))],
    ids=["0x", "-1x", "side"],
)
def test_liquidation_estimate_refuses_a_programming_error(side: Any, leverage: Decimal) -> None:
    with pytest.raises(ValueError, match="no liquidation estimate"):
        sz.liquidation_estimate(side, D(64000), leverage, D("0.005"))


def test_beyond_liquidation_counts_the_buffer_edge_itself_as_beyond() -> None:
    """Entry 100, estimate 90: 10 % of the 10 of room is 1, so the long's edge is 91."""
    beyond = functools.partial(sz.beyond_liquidation, entry=D(100), tick=D("0.1"))
    assert beyond("buy", D(91), D(90)) and not beyond("buy", D("91.1"), D(90))
    assert beyond("sell", D(109), D(110)) and not beyond("sell", D("108.9"), D(110))


def test_liquidation_edge_takes_at_least_one_tick() -> None:
    """Entry 100, estimate 99.9: 10 % of 0.1 is 0.01, under the 0.1 tick, so the edge is 100."""
    assert sz.liquidation_edge("buy", D(100), D("99.9"), D("0.1")) == D(100)
    assert sz.liquidation_edge("sell", D(100), D("100.1"), D("0.1")) == D(100)


def test_a_stop_inside_the_estimate_but_within_the_buffer_is_refused() -> None:
    """At 10x a long's estimate is 57920 and its edge 57920 + 10 % of 6080 = 58528: a stop at
    58500 (5500 ticks of 0.1 below 64000) is inside the estimate but not the edge."""
    got = sized(profile("P-QTY", sl_offset_unit="ticks", sl_offset_value="55000", leverage="10"))
    assert (got.stop and got.stop.price, got.liquidation_price) == (D(58500), D(57920))
    assert got.reason is sz.FailReason.STOP_BEYOND_LIQUIDATION


def test_liquidation_edge_refuses_an_unknown_side() -> None:
    side: Any = "hold"
    with pytest.raises(ValueError, match="no liquidation edge"):
        sz.liquidation_edge(side, D(100), D(90), D("0.1"))


def test_liquidation_estimate_refuses_a_negative_rate() -> None:
    with pytest.raises(ValueError, match="negative maintenance margin rate"):
        sz.liquidation_estimate("buy", D(64000), D(10), D("-0.001"))
