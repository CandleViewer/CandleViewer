"""E22-T02 (#654) SR-E22-03 as ruled by the orchestrator (2026-10-28): `MIN_SIZE_FLOOR` is
max(`min_order_qty`, `min_notional` at the reference price ceiled to `qty_step`), the reference
price the latest print on the hot tape, else the ticker's latest mark price; with neither, or a
zero minimum notional, the floor is `min_order_qty`. Read per call, so it follows the price."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from candleviewer.app import _catalogue_min_size_floor
from tests._bigtrades import Tape, event

_INST = SimpleNamespace(
    min_order_qty=Decimal("1"), min_notional=Decimal("5"), qty_step=Decimal("1")
)


class _Tickers:
    def __init__(self, mark: str | None) -> None:
        self.mark = mark

    def latest(self, symbol: str) -> Any:
        return None if self.mark is None else SimpleNamespace(mark_price=Decimal(self.mark))


def _ctx(tape: Tape | None, mark: str | None, inst: Any = _INST) -> Any:
    snap = {"DOGEUSDT": inst}
    ingestion = SimpleNamespace(
        instruments=SimpleNamespace(snapshot=lambda: snap),
        trades=tape,
        tickers=_Tickers(mark),
    )
    return SimpleNamespace(ingestion=ingestion)


def _doge(price: str) -> Tape:
    return Tape([event(1, "10", price=price, symbol="DOGEUSDT")])


def test_floor_is_min_order_qty_when_the_notional_size_is_smaller() -> None:
    assert _catalogue_min_size_floor(_ctx(_doge("10"), None), "DOGEUSDT") == Decimal("1")


def test_floor_is_the_notional_size_at_the_latest_print_ceiled_to_the_step() -> None:
    # 5 USDT at 0.12 is 41.67 coins: ceiled to 42 lots of 1.
    assert _catalogue_min_size_floor(_ctx(_doge("0.12"), "1"), "DOGEUSDT") == Decimal("42")


def test_floor_falls_back_to_the_mark_price_with_no_print() -> None:
    assert _catalogue_min_size_floor(_ctx(Tape(), "0.1"), "DOGEUSDT") == Decimal("50")
    assert _catalogue_min_size_floor(_ctx(None, "0.1"), "DOGEUSDT") == Decimal("50")


def test_floor_collapses_to_min_order_qty_with_no_price_or_no_minimum_notional() -> None:
    assert _catalogue_min_size_floor(_ctx(None, None), "DOGEUSDT") == Decimal("1")
    free = SimpleNamespace(min_order_qty=Decimal("2"), min_notional=Decimal(0), qty_step=Decimal(1))
    assert _catalogue_min_size_floor(_ctx(_doge("0.12"), None, free), "DOGEUSDT") == Decimal("2")


def test_floor_is_none_for_an_unlisted_symbol() -> None:
    assert _catalogue_min_size_floor(_ctx(None, "0.1"), "BTCUSDT") is None
