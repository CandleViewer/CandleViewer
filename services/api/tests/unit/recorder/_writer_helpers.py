"""Fakes and event builders for StreamWriter tests (no I/O beyond `tmp_path`, no sleeps)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from candleviewer.domain.primitives import EventId
from candleviewer.exchange.base.models import (
    BookDelta,
    BookLevel,
    BookSnapshot,
    LiquidationEvent,
    TickerEvent,
    TradeEvent,
)
from candleviewer.observability.health_probes import SystemEvent
from candleviewer.recorder.writer import DiskGate, StreamWriter, WriterConfig

T0 = 1_700_000_000_000_000
#: E16-T07: the gate is required; tests that do not exercise it keep it open.
OPEN_GATE = DiskGate(halted=lambda: False, position_open=lambda _symbol: True)


class FakeClock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


class FakeSink:
    """`RowSink` recording every flushed batch; `down` makes writes raise like a dead ILP."""

    def __init__(self) -> None:
        self.flushed: dict[str, list[dict[str, object]]] = {}
        self.pending: dict[str, list[dict[str, object]]] = {}
        self.down: set[str] = set()
        self.fail_after: int | None = None

    async def write_rows(self, table: str, rows: list[dict[str, object]], ts_us_key: str) -> None:
        assert ts_us_key == "ts"
        if table in self.down or "*" in self.down:
            raise ConnectionError("questdb down")
        self.pending.setdefault(table, []).extend(rows)

    async def flush(self, table: str | None = None) -> None:
        assert table is not None
        if self.fail_after is not None:
            if self.fail_after <= 0:
                self.pending.pop(table, None)
                raise ConnectionError("questdb died mid-replay")
            self.fail_after -= 1
        self.flushed.setdefault(table, []).extend(self.pending.pop(table, []))

    def rows(self, table: str) -> list[dict[str, object]]:
        return self.flushed.get(table, [])


class FakeStore:
    def __init__(self) -> None:
        self.counters: list[tuple[str, dict[str, int]]] = []
        self.gaps: list[dict[str, object]] = []
        self.fail = False
        #: False = no live recording session (E16-T04 has not opened one yet).
        self.session = True

    async def add_session_counters(self, symbol: str, **kw: int) -> bool:
        if self.fail:
            raise ConnectionError("pg down")
        if not self.session:
            return False
        self.counters.append((symbol, kw))
        return True

    async def record_live_gap(
        self, *, symbol: str, stream: str, gap_start: datetime, gap_end: datetime, cause: str
    ) -> bool:
        if self.fail:
            raise ConnectionError("pg down")
        if not self.session:
            return False
        self.gaps.append(
            {"symbol": symbol, "stream": stream, "start": gap_start, "end": gap_end, "cause": cause}
        )
        return True


class FakeEvents:
    def __init__(self) -> None:
        self.events: list[SystemEvent] = []

    async def write(self, event: SystemEvent) -> None:
        self.events.append(event)


class FsyncCounter:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, fd: int) -> None:
        self.calls += 1


async def make_writer(
    tmp_path: Path, *, sink: FakeSink | None = None, **cfg: object
) -> tuple[StreamWriter, FakeSink, FakeStore, FakeEvents, FakeClock]:
    """A writer whose five lanes share one per-table `FakeSink` (it fails/delays per table)."""
    sink = sink or FakeSink()
    store, events, clock = FakeStore(), FakeEvents(), FakeClock()
    config = WriterConfig(wal_dir=tmp_path / "wal", **cfg)  # type: ignore[arg-type]
    w = StreamWriter(
        lambda _stream: sink,
        store,
        events,
        config,
        clock=clock,
        wall_clock_us=lambda: T0 + int(clock.t * 1e6),
        fsync=FsyncCounter(),
        disk_gate=OPEN_GATE,
    )
    await w.open()
    w.seed(["BTCUSDT"])
    return w, sink, store, events, clock


def _env(symbol: str, ts: int) -> dict[str, object]:
    return {
        "event_id": EventId(uuid.uuid4()),
        "ts_event": ts,
        "ts_ingest": ts + 5,
        "source": "live",
        "symbol": symbol,
    }


def trade(i: int, symbol: str = "BTCUSDT", ts: int | None = None) -> TradeEvent:
    return TradeEvent(
        **_env(symbol, T0 + i if ts is None else ts),  # type: ignore[arg-type]
        trade_id=f"t{i}",
        price=Decimal("65000.5"),
        qty=Decimal("0.001"),
        side="buy",
        is_block_trade=False,
        price_ticks=650005,
        notional=Decimal("65.0005"),
        seq=i,
    )


def _lv(px: str, q: str) -> BookLevel:
    return BookLevel(price=Decimal(px), qty=Decimal(q), price_ticks=int(Decimal(px) * 10))


def delta(uid: int, prev: int | None = None, symbol: str = "BTCUSDT") -> BookDelta:
    return BookDelta(
        **_env(symbol, T0 + uid),  # type: ignore[arg-type]
        depth=200,
        bids=(_lv("65000.0", "1.5"),),
        asks=(_lv("65000.5", "0"),),
        update_id=uid,
        prev_update_id=uid - 1 if prev is None else prev,
        cross_seq=uid * 10,
        ts_match=T0 + uid,
    )


def snapshot(uid: int, symbol: str = "BTCUSDT") -> BookSnapshot:
    return BookSnapshot(
        **_env(symbol, T0 + uid),  # type: ignore[arg-type]
        depth=200,
        bids=(_lv("65000.0", "1.5"), _lv("64999.5", "2")),
        asks=(_lv("65000.5", "3"),),
        update_id=uid,
        cross_seq=uid * 10,
        ts_match=T0 + uid,
        reason="subscribe",
    )


def ticker(i: int, symbol: str = "BTCUSDT") -> TickerEvent:
    return TickerEvent(
        **_env(symbol, T0 + i),  # type: ignore[arg-type]
        last_price=Decimal("65000.5"),
        mark_price=Decimal("65000.1"),
        index_price=Decimal("64999.9"),
        bid1_price=Decimal("65000.0"),
        bid1_qty=Decimal("1"),
        ask1_price=Decimal("65000.5"),
        ask1_qty=Decimal("2"),
        open_interest=Decimal("10"),
        open_interest_value=Decimal("650000"),
        turnover_24h=None,
        volume_24h=None,
        price_24h_pcnt=Decimal("0.01"),
        funding_rate=Decimal("0.0001"),
        next_funding_time=T0 + 3_600_000_000,
        is_delta=False,
    )


def liquidation(i: int, symbol: str = "BTCUSDT") -> LiquidationEvent:
    return LiquidationEvent(
        **_env(symbol, T0 + i),  # type: ignore[arg-type]
        price=Decimal("64000"),
        qty=Decimal("0.5"),
        side="sell",
        liquidated_side="long",
        notional=Decimal("32000"),
        batch_index=i,
        ts_estimated=False,
    )
