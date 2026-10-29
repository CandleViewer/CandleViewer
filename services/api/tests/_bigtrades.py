"""Shared E22-T02 (#654) test helpers: trade events, synthetic or from the recorded corpus, the
hot-tape reader both `GET /market/trades` and `trades.{symbol}` read, and the `World` the WS
tests drive `trades.{symbol}` in (no network)."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

from candleviewer.bus.bus import Bus
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.exchange.base.trade_print import TradePrint
from candleviewer.ingestion.ticker_stream import uuid7
from candleviewer.orderflow.bigtrade_models import BigTradeConfig
from candleviewer.ws.permissions import SubscriptionServices
from candleviewer.ws.sequencing import SequencingHub
from candleviewer.ws.trades_publish import PENDING_MAX, TradesTopic
from candleviewer.ws.upstream import UpstreamRefs
from tests._corpus import TICKS, frames, normalize
from tests.unit.ws._seq_support import USER, Clock, Conn

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


SMALL = BigTradeConfig("absolute_size", Decimal("1"))
CH = "trades.BTCUSDT"


class World:
    """One process: the hot tape, the `trades` topic and its hub, and the connections built on
    them (a real `ConnectionAuthz`, `SequencingHub` and `TopicEmitter`; fake clocks)."""

    def __init__(
        self,
        tape: Tape | None = None,
        config: BigTradeConfig = SMALL,
        pending_max: int = PENDING_MAX,
    ) -> None:
        self.tape: Tape | None = tape or Tape()
        self.clock = Clock()
        self.now_us = T0_US
        self.hub = SequencingHub()
        self.topic = TradesTopic(
            self.hub,
            reader=lambda: self.tape,
            bus=Bus(),
            env="demo",
            scales=lambda s: (1, 3) if s == "BTCUSDT" else None,
            floor=lambda s: Decimal("0.001") if s == "BTCUSDT" else None,
            config=lambda _s: config,
            clock=self.clock,
            now_us=lambda: self.now_us,
            pending_max=pending_max,
        )
        self.services = SubscriptionServices(
            upstream=UpstreamRefs(), snapshots=self.topic, trades=self.topic
        )

    def conn(self, user: Any = USER) -> Conn:
        source: Any = self.topic  # the topic is the snapshot source `Conn` renders from
        conn = Conn(source, services=self.services, clock=self.clock, user=user)
        self.hub.register(conn.authz, conn.emitter)
        return conn

    def sub(self, conn: Conn, opts: dict[str, Any] | None = None) -> tuple[dict[str, Any], Any]:
        result, sub = conn.authz.admit({"ch": CH, "opts": opts or {}})
        if sub is None:
            return result, None
        refused = asyncio.run(conn.authz.subscribe_upstream(sub))
        if refused is not None:
            return refused, None
        sub.announced = True
        conn.emitter.flush_pending([sub])
        return result, sub

    def window(self, *batches: list[TradeEvent]) -> int:
        """Offer each batch as one bus drain, then let one window close."""
        for batch in batches:
            self.topic.offer(batch)
        self.clock.now += 1.0
        return self.topic.tick()
