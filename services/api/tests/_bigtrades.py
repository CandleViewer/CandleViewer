"""Shared E22-T02 (#654) test helpers: trade events, synthetic or from the recorded corpus, and the
hot-tape reader both `GET /market/trades` and `trades.{symbol}` read (no network)."""

from __future__ import annotations

from decimal import Decimal

from candleviewer.exchange.base.models import TradeEvent
from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.ingestion.ticker_stream import uuid7
from tests._corpus import TICKS, frames, normalize

T0_US = 1_792_391_736_000_000
TICK = TICKS["BTCUSDT"]


def event(
    i: int,
    qty: str,
    *,
    side: str = "buy",
    price: str = "82745.8",
    ts_us: int | None = None,
    symbol: str = "BTCUSDT",
    block: bool = False,
) -> TradeEvent:
    """A synthetic print `t{i}`, `i` ms after `T0_US` unless `ts_us` says otherwise."""
    ts = T0_US + i * 1000 if ts_us is None else ts_us
    px, q = Decimal(price), Decimal(qty)
    return TradeEvent.model_validate(
        {
            "event_id": uuid7(ts // 1000),
            "ts_event": ts,
            "ts_ingest": ts,
            "source": "live",
            "symbol": symbol,
            "trade_id": f"t{i:05d}",
            "price": px,
            "qty": q,
            "side": side,
            "is_block_trade": block,
            "price_ticks": int(px / TICK),
            "notional": px * q,
            "seq": i,
        }
    )


def from_print(p: TradePrint, seq: int) -> TradeEvent:
    """A recorded print as the ingestion trade stream publishes it (`TradeStream._event`)."""
    tick = TICKS[p.symbol]
    return TradeEvent.model_validate(
        {
            "event_id": uuid7(p.ts_event_us // 1000),
            "ts_event": p.ts_event_us,
            "ts_ingest": p.ts_event_us,
            "source": "live",
            "symbol": p.symbol,
            "trade_id": p.trade_id,
            "price": p.price,
            "qty": p.qty,
            "side": p.side,
            "is_block_trade": p.is_block_trade,
            "price_ticks": int((p.price / tick).to_integral_value()),
            "notional": p.price * p.qty,
            "seq": seq,
        }
    )


def recorded_batches(rel: str = "ws/clean_publicTrade_BTCUSDT.jsonl") -> list[list[TradeEvent]]:
    """The recorded tape, one batch per frame, as the stream publishes it."""
    out: list[list[TradeEvent]] = []
    seq = 0
    for raw in frames(rel):
        batch = []
        for p in normalize(raw):
            if isinstance(p, TradePrint):
                seq += 1
                batch.append(from_print(p, seq))
        if batch:
            out.append(batch)
    return out


class Tape:
    """The hot tape both surfaces read (`TradeStream.recent`, `tick_size`, listing, demand)."""

    def __init__(self, events: list[TradeEvent] | None = None) -> None:
        self.events: list[TradeEvent] = list(events or [])
        self.acquired: list[tuple[str, str]] = []

    def recent(self, symbol: str) -> list[TradeEvent]:
        return [e for e in self.events if e.symbol == symbol][-1000:]

    def tick_size(self, symbol: str) -> Decimal | None:
        return TICKS.get(symbol)

    def is_listed(self, symbol: str) -> bool:
        return symbol in TICKS

    def acquire(self, consumer: str, symbol: str) -> None:
        self.acquired.append((consumer, symbol))

    def release(self, consumer: str, symbol: str) -> None:
        pass
