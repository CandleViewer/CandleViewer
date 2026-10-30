"""Builders for LiquidityTracker tests (no network, no wall clock)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal

from candleviewer.book.models import BookPhase
from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.orderflow.liquidity import LiquidityTracker
from candleviewer.orderflow.liquidity_models import LiquidityConfig, LiquiditySample

TICK = Decimal("0.1")
STEP = Decimal("0.001")
MS = 1000
_n = 0


class FakeBook:
    """`{price_ticks: qty}` per side; `walk` yields best first like `BookState.walk`."""

    def __init__(self, bids: dict[int, str], asks: dict[int, str]) -> None:
        self.bids = {t: Decimal(q) for t, q in bids.items()}
        self.asks = {t: Decimal(q) for t, q in asks.items()}

    def walk(self, *, bids: bool) -> Iterator[tuple[int, Decimal]]:
        if bids:
            return iter(sorted(self.bids.items(), reverse=True))
        return iter(sorted(self.asks.items()))


def book(wall: str = "10", **kw: dict[int, str]) -> FakeBook:
    """Best bid 1000, best ask 1001, the wall under test at ask 1002."""
    return FakeBook(
        kw.get("bids", {1000: "20", 999: "5"}),
        kw.get("asks", {1001: "4", 1002: wall, 1003: "20"}),
    )


def trade(
    ts_ms: int, tick: int, qty: str, side: str = "buy", trade_id: str | None = None
) -> TradeEvent:
    global _n
    _n += 1
    p, q = Decimal(tick) * TICK, Decimal(qty)
    return TradeEvent(
        event_id=EventId(uuid.UUID(int=_n)),
        ts_event=ts_ms * MS,
        ts_ingest=ts_ms * MS,
        source="live",
        symbol="BTCUSDT",
        trade_id=trade_id or f"t{_n}",
        price=p,
        qty=q,
        side=side,  # type: ignore[arg-type]  # str to the TradeSide Literal; pydantic validates it
        is_block_trade=False,
        price_ticks=tick,
        notional=p * q,
        seq=_n,
    )


def tracker(**cfg: object) -> LiquidityTracker:
    return LiquidityTracker("BTCUSDT", TICK, STEP, LiquidityConfig(**cfg))  # type: ignore[arg-type]  # kwargs are test-chosen config fields


def sample(
    t: LiquidityTracker, ts_ms: int, b: FakeBook, phase: BookPhase = BookPhase.LIVE
) -> LiquiditySample:
    return t.on_sample(ts_ms * MS, phase, b)
