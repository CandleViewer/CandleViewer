"""A wall consumed and refilled on the recorded depth-200 snapshot (E21-T04, #710).

The book is the first frame of the recorded `orderbook_BTCUSDT` capture (C-13.5); the wall's
consume/refill and the tape are scripted on top of it, because the capture holds no such episode."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from candleviewer.book.models import BookPhase
from candleviewer.book.state import BookState
from candleviewer.exchange.base.models import BookLevel
from candleviewer.orderflow.liquidity_models import LiquidityPulled, LiquidityReload
from tests.unit.orderflow._liquidity_helpers import MS, TICK, tracker, trade

_CAPTURE = (
    Path(__file__).resolve().parents[5]
    / "packages/fixtures/bybit/2026-10-05/ws/orderbook_BTCUSDT.jsonl"
)


def _snapshot() -> BookState:
    frame = json.loads(_CAPTURE.read_text().splitlines()[0])["data"]

    def levels(rows: list[list[str]]) -> list[BookLevel]:
        return [
            BookLevel(price=Decimal(p), qty=Decimal(q), price_ticks=int(Decimal(p) / TICK))
            for p, q in rows
        ]

    return BookState.from_levels(200, levels(frame["b"]), levels(frame["a"]))


def _set_ask(book: BookState, price: str, qty: str) -> None:
    book.apply(
        [],
        [BookLevel(price=Decimal(price), qty=Decimal(qty), price_ticks=int(Decimal(price) / TICK))],
    )


def test_recorded_wall_consumed_and_refilled_emits_one_reload() -> None:
    book, t = _snapshot(), tracker()
    wall_px = "631210.0"
    wall = int(Decimal(wall_px) / TICK)
    _set_ask(book, wall_px, "50")
    t.on_sample(0, BookPhase.LIVE, book)
    t.on_sample(100 * MS, BookPhase.LIVE, book)  # steady: no event from the capture's own levels
    t.on_trade(trade(150, wall, "30"))
    t.on_trade(trade(160, wall + 1, "10"))  # a sweep through the wall
    _set_ask(book, wall_px, "8")
    assert not t.on_sample(200 * MS, BookPhase.LIVE, book).events
    _set_ask(book, wall_px, "47")
    (r,) = t.on_sample(300 * MS, BookPhase.LIVE, book).events
    assert isinstance(r, LiquidityReload)
    assert (r.side, r.price_ticks, r.prior_size, r.replenished_size, r.refill_count) == (
        "ask",
        wall,
        Decimal(50),
        Decimal(47),
        1,
    )
    assert r.estimated is True and r.symbol == "BTCUSDT"


def test_recorded_wall_pulled_without_prints_emits_one_pulled() -> None:
    book, t = _snapshot(), tracker()
    _set_ask(book, "631210.0", "50")
    t.on_sample(0, BookPhase.LIVE, book)
    _set_ask(book, "631210.0", "1")
    (p,) = t.on_sample(100 * MS, BookPhase.LIVE, book).events
    assert isinstance(p, LiquidityPulled) and p.traded_qty == 0
