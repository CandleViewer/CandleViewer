"""E28-T03 (#907) AC 10, determinism: the sizer over every frozen golden vector, QA's 14
(`tests/fixtures/e28/golden_sizing_vectors.json`, read unchanged) and the ticket's own in the same
schema (`golden/e28_sizer_vectors.json`, QA's Q-08 gaps), matching every recorded value exactly,
and QA's spreadsheet (`sizing_recomputation.csv`) cross-checked step by step."""

from __future__ import annotations

import csv
from decimal import ROUND_DOWN, Context, Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from candleviewer.accounts import sizer as sz
from candleviewer.accounts.override_comparator import MARGIN_SHARE
from tests.unit.accounts.test_sizer import _E28, _json
from tests.unit.accounts.test_sizer_caps import _QA, assert_every_figure_has_a_unit, run

D = Decimal
_OWN: Final = _json(Path(__file__).parent / "golden" / "e28_sizer_vectors.json")
_VECTORS: Final = [*_QA, *_OWN]
#: QA's `binding_cap` labels (the fixture README) and the caps each names.
_LABELS: Final[dict[str, set[str | None]]] = {
    "none": {None},
    "leverage": {"max_leverage_cap"},
    "pct_equity": {"max_position_pct_equity"},
    "notional": {"max_position_notional"},
    "daily_loss": {"max_daily_loss", "max_daily_loss_pct"},
    "instrument": {"max_order_qty", "max_mkt_order_qty"},
}
_FIGURES: Final = ("qty", "notional", "risk_usdt", "risk_with_fees_usdt", "initial_margin")


def test_golden_vectors_are_at_least_forty_with_unique_ids() -> None:
    ids = [v["id"] for v in _VECTORS]
    assert len(ids) == len(set(ids)) >= 40


@pytest.mark.parametrize("v", _VECTORS, ids=[v["id"] for v in _VECTORS])
def test_size_leg_golden_vector_matches_to_the_last_decimal(v: dict[str, Any]) -> None:
    got, want, also = run(v), v["expected"], v.get("also", {})
    assert (got.outcome, got.reason) == (want["outcome"], want.get("code"))
    record = {**also, **want}
    for name in _FIGURES:
        if name in record:
            assert getattr(got, name) == D(record[name]), name
    if "stop" in want:
        assert got.stop is not None
        assert (got.stop.price, got.stop_fallback) == (
            D(want["stop"]),
            also.get("stop_fallback", False),
        )
    for kind in ("min_order_qty", "min_notional", "min_leg_notional"):
        if kind in also:
            assert got.minimum == (kind, D(also[kind]))
    if "binding_cap" in also:
        assert (got.binding and got.binding.cap) in _LABELS[also["binding_cap"]]
    if want.get("code") == "insufficient_margin":  # the margin the leg needed is past the share
        assert got.initial_margin is not None
        assert got.initial_margin > D(v["wallet"]["available_margin"]) * MARGIN_SHARE
    ladder = v.get("ladder", {"tp_prices": also.get("tp_prices")})
    if want["outcome"] != "ok" or ladder["tp_prices"] == []:  # a vector that expects none
        assert got.tps == ()
    elif ladder["tp_prices"] is not None:
        assert [tp.price for tp in got.tps] == [D(x) for x in ladder["tp_prices"]]
        sizes = ladder.get("tp_qtys", [want["qty"]] * len(got.tps))
        assert [tp.qty for tp in got.tps] == [D(x) for x in sizes]


@pytest.mark.parametrize("v", _OWN, ids=[v["id"] for v in _OWN])
def test_tickets_ok_vector_records_its_take_profits(v: dict[str, Any]) -> None:
    # So none passes vacuously; QA's file is frozen and is not held to this.
    if v["expected"]["outcome"] == "ok":
        assert "tp_prices" in v.get("ladder", v.get("also", {}))


@pytest.mark.parametrize("v", _OWN, ids=[v["id"] for v in _OWN])
def test_render_every_figure_carries_a_unit_on_the_tickets_vectors(v: dict[str, Any]) -> None:
    assert_every_figure_has_a_unit(run(v).render())


def _cut(value: Decimal) -> Decimal:
    """QA's spreadsheet writes a quotient that does not end to 28 digits, cut (its README)."""
    return Context(prec=28, rounding=ROUND_DOWN).plus(value)


_CAP_COLUMNS: Final = {
    "max_leverage_cap": "cap_leverage_qty",
    "max_position_pct_equity": "cap_pct_equity_qty",
    "max_position_notional": "cap_notional_qty",
    "max_daily_loss": "cap_daily_qty",
    "max_daily_loss_pct": "cap_daily_qty",
    "max_order_qty": "cap_instrument_qty",
}
_ROWS: Final = list(
    csv.DictReader((_E28 / "sizing_recomputation.csv").read_text(encoding="utf-8").splitlines())
)


@pytest.mark.parametrize("row", _ROWS, ids=[row["id"] for row in _ROWS])
def test_size_leg_matches_the_recomputation_spreadsheet_step_by_step(row: dict[str, str]) -> None:
    v = next(x for x in _VECTORS if x["id"] == row["id"])
    got = run(v)
    if row["code"] == "symbol_not_allowed":
        assert got == sz.LegSizing("skip", sz.SkipReason.SYMBOL_NOT_ALLOWED)
        return
    assert got.stop is not None and got.raw_qty is not None
    assert got.qty is not None and got.rounding_delta is not None
    assert (got.stop.price, got.stop.distance) == (D(row["stop"]), D(row["stop_distance"]))
    assert _cut(got.raw_qty) == D(row["qty_raw"])
    assert _cut(Context(prec=100).add(got.qty, got.rounding_delta)) == D(row["qty_capped"])
    if row["fee_per_unit"]:
        assert got.per_unit == got.stop.distance + D(row["fee_per_unit"])
    for clamp in got.clamps:
        # Q3 left the fee in the daily room open; BQ-11 ruled it in: only a fee-free row agrees
        if clamp.cap.startswith("max_daily") and D(v["market"]["taker_fee_rate"]) != 0:
            continue
        assert _cut(clamp.limit) == D(row[_CAP_COLUMNS[clamp.cap]]), clamp.cap
    judged = {_CAP_COLUMNS[clamp.cap] for clamp in got.clamps}
    assert judged == {column for column in set(_CAP_COLUMNS.values()) if row[column]}
