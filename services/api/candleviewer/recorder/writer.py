"""StreamWriter — raw recorded streams to QuestDB over ILP (E16-T03, 20-architecture.md §3.8).

Consumes normalised market events for symbols in the RecordingPolicy effective set (kept as a
plain `set[str]` updated from `RecorderSetChanged`, so the hot path never queries a statechart —
C-2.20) and writes `trades`, `orderbook_deltas`, `orderbook_snapshots`, `tickers` and
`liquidations` (21-database-schema.md §4).

One **lane** per stream, each with its own sink (one ILP connection per stream), bounded
queue, spill buffer, WAL and locks, so a stalled stream never delays another. A lane flushes
at `flush_rows` (10 000) rows, or once its oldest queued row is `flush_interval_s` (200 ms) old
by the injected clock. The writer owns that cadence: every batch ends with `sink.flush`.

Backpressure ladder (never silent):
1. bounded in-memory queue (`max_queue_rows` per lane). Admission never awaits I/O.
2. bounded on-disk WAL (`recorder/wal.py`, shared `wal_max_bytes`, default 1 GiB), used when
   the queue is full or the sink failed. While spilling, records are buffered and appended once
   per pump: one write and one fsync per batch.
3. drop. Each (symbol, stream) gets one widening gap window, persisted as a `recording_gaps` row
   (`cause='backpressure_drop'`), plus one `critical` event per episode. An episode ends when the
   lane drains. Gap windows and counter deltas are kept until a live session accepts them, and
   any still unpersisted at `stop()` raise a critical event.

Replay (on startup, on `recover()`, and every `replay_retry_s` while spilling) streams the WAL:
an external sort into bounded runs, then a k-way merge in `exch_ts` order with duplicate keys
suppressed. A durable checkpoint advances after each committed batch, so a failed or killed
replay resumes from it. QuestDB `DEDUP UPSERT KEYS` absorbs the one batch that may be in flight.
"""

from __future__ import annotations

import asyncio
import os
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal, Protocol

import structlog

from candleviewer.observability import spawn
from candleviewer.observability.health_probes import SystemEvent, SystemEventWriter
from candleviewer.recorder.metrics import (
    recorder_bytes_written_total,
    recorder_flush_duration_seconds,
    recorder_rows_total,
    recorder_spill_bytes,
    recorder_write_backlog_rows,
)
from candleviewer.recorder.models import RecorderSetChanged
from candleviewer.recorder.wal import SpillWal, WalBudget, WalRecord
from candleviewer.settings import Settings
from candleviewer.storage.questdb.ilp_writer import serialize_ilp_line
from candleviewer.storage.questdb.schemas import ALL_SCHEMAS

Stream = Literal["trades", "orderbook_deltas", "orderbook_snapshots", "tickers", "liquidations"]
STREAMS: Final[tuple[Stream, ...]] = (
    "trades",
    "orderbook_deltas",
    "orderbook_snapshots",
    "tickers",
    "liquidations",
)
#: QuestDB table -> Postgres `stream_kind` (recording_gaps.stream).
STREAM_KIND: Final[dict[Stream, str]] = {
    "trades": "trades",
    "orderbook_deltas": "orderbook_delta",
    "orderbook_snapshots": "orderbook_snapshot",
    "tickers": "tickers",
    "liquidations": "liquidations",
}
GAP_CAUSE: Final = "backpressure_drop"
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    # structlog types get_logger() as Any; the stdlib-bound processor chain is configured
    # by observability.logging, so the narrowing is sound.
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]


# --- inputs (structural: M11 may not import exchange.base, CONSTITUTION §3) ------------------


class LevelLike(Protocol):
    @property
    def price(self) -> Decimal: ...
    @property
    def qty(self) -> Decimal: ...


class _Market(Protocol):
    @property
    def symbol(self) -> str: ...
    @property
    def ts_event(self) -> int: ...


class TradeLike(_Market, Protocol):
    @property
    def trade_id(self) -> str: ...
    @property
    def price(self) -> Decimal: ...
    @property
    def qty(self) -> Decimal: ...
    @property
    def notional(self) -> Decimal: ...
    @property
    def side(self) -> str: ...
    @property
    def is_block_trade(self) -> bool: ...
    @property
    def seq(self) -> int: ...


class BookSnapshotLike(_Market, Protocol):
    @property
    def depth(self) -> int: ...
    @property
    def bids(self) -> Sequence[LevelLike]: ...
    @property
    def asks(self) -> Sequence[LevelLike]: ...
    @property
    def update_id(self) -> int: ...
    @property
    def cross_seq(self) -> int: ...


class BookDeltaLike(BookSnapshotLike, Protocol):
    @property
    def prev_update_id(self) -> int: ...


class TickerLike(_Market, Protocol):
    @property
    def last_price(self) -> Decimal | None: ...
    @property
    def mark_price(self) -> Decimal | None: ...
    @property
    def index_price(self) -> Decimal | None: ...
    @property
    def bid1_price(self) -> Decimal | None: ...
    @property
    def bid1_qty(self) -> Decimal | None: ...
    @property
    def ask1_price(self) -> Decimal | None: ...
    @property
    def ask1_qty(self) -> Decimal | None: ...
    @property
    def open_interest(self) -> Decimal | None: ...
    @property
    def open_interest_value(self) -> Decimal | None: ...
    @property
    def turnover_24h(self) -> Decimal | None: ...
    @property
    def volume_24h(self) -> Decimal | None: ...
    @property
    def price_24h_pcnt(self) -> Decimal | None: ...
    @property
    def funding_rate(self) -> Decimal | None: ...
    @property
    def next_funding_time(self) -> int | None: ...


class LiquidationLike(_Market, Protocol):
    @property
    def price(self) -> Decimal: ...
    @property
    def qty(self) -> Decimal: ...
    @property
    def liquidated_side(self) -> str: ...
    @property
    def notional(self) -> Decimal: ...
    @property
    def batch_index(self) -> int: ...


# --- outputs -------------------------------------------------------------------------------


class RowSink(Protocol):
    """The ILP surface used (`storage.questdb.IlpWriter` conforms)."""

    async def write_rows(
        self, table: str, rows: list[dict[str, object]], ts_us_key: str
    ) -> None: ...

    async def flush(self, table: str | None = None) -> None: ...


class RecorderStore(Protocol):
    """Postgres side (`SqlAlchemyRecorderRepository` conforms): the symbol's live session."""

    async def add_session_counters(
        self,
        symbol: str,
        *,
        messages_received: int,
        messages_dropped: int,
        bytes_written: int,
        reconnect_count: int,
    ) -> bool: ...

    async def record_live_gap(
        self, *, symbol: str, stream: str, gap_start: datetime, gap_end: datetime, cause: str
    ) -> bool: ...


class RecorderWalVolumeError(RuntimeError):
    """SR-096 / threat S2: the WAL shares a volume with a path the backend needs."""

    code = "recorder_wal_volume_shared"


def check_wal_volume(wal_dir: Path, protected: Sequence[Path]) -> None:
    """Refuse to record when `wal_dir` lives on the same device as any `protected` path.
    Synchronous: call through `asyncio.to_thread`."""
    wal_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    dev = os.stat(wal_dir).st_dev
    for path in protected:
        if path.exists() and os.stat(path).st_dev == dev:
            raise RecorderWalVolumeError(f"WAL dir shares a volume with {path.name!r}")


# --- event -> rows ---------------------------------------------------------------------------


def _num(value: Decimal) -> str:
    """Exact decimal text for an ILP DOUBLE field (never via `float`, never exponent form)."""
    return format(value, "f")


def _rec(
    stream: Stream, symbol: str, ts: int, seq: int, sub: int, row: dict[str, object]
) -> WalRecord:
    row["ts"] = ts
    row["symbol"] = symbol
    return WalRecord(stream=stream, symbol=symbol, exch_ts=ts, seq=seq, sub=sub, row=row)


def trade_records(ev: TradeLike) -> list[WalRecord]:
    row: dict[str, object] = {
        "side": ev.side,
        "price": _num(ev.price),
        "size": _num(ev.qty),
        "notional": _num(ev.notional),
        "trade_id": ev.trade_id,
        "is_block": ev.is_block_trade,
        "seq": ev.seq,
    }
    return [_rec("trades", ev.symbol, ev.ts_event, ev.seq, 0, row)]


def _levels(ev: BookSnapshotLike) -> list[tuple[str, LevelLike]]:
    return [("bid", lv) for lv in ev.bids] + [("ask", lv) for lv in ev.asks]


def delta_records(ev: BookDeltaLike) -> list[WalRecord]:
    out: list[WalRecord] = []
    for sub, (side, lv) in enumerate(_levels(ev)):
        row: dict[str, object] = {
            "depth": ev.depth,
            "side": side,
            "price": _num(lv.price),
            "size": _num(lv.qty),
            # Without book state an insert is indistinguishable from an update (E08 owns it).
            "action": "delete" if lv.qty == 0 else "update",
            "update_id": ev.update_id,
            "cross_seq": ev.cross_seq,
        }
        out.append(_rec("orderbook_deltas", ev.symbol, ev.ts_event, ev.update_id, sub, row))
    return out


def snapshot_records(ev: BookSnapshotLike) -> list[WalRecord]:
    import orjson

    # `epoch_id` (a DEDUP key) is the book module's rebuild counter, which is not on the event,
    # so it stays NULL. The key then reduces to (ts, symbol, depth): one snapshot per exchange
    # instant and depth, so a replay is still idempotent.
    row: dict[str, object] = {
        "depth": ev.depth,
        "update_id": ev.update_id,
        "cross_seq": ev.cross_seq,
        "source": "exchange",
        "bids": orjson.dumps([[_num(lv.price), _num(lv.qty)] for lv in ev.bids]).decode(),
        "asks": orjson.dumps([[_num(lv.price), _num(lv.qty)] for lv in ev.asks]).decode(),
        "level_count": len(ev.bids) + len(ev.asks),
    }
    return [_rec("orderbook_snapshots", ev.symbol, ev.ts_event, ev.update_id, 0, row)]


_TICKER_COLS: Final = (
    ("last_price", "last_price"),
    ("mark_price", "mark_price"),
    ("index_price", "index_price"),
    ("bid1_price", "bid1_price"),
    ("bid1_qty", "bid1_size"),
    ("ask1_price", "ask1_price"),
    ("ask1_qty", "ask1_size"),
    ("open_interest", "open_interest"),
    ("open_interest_value", "open_interest_value"),
    ("turnover_24h", "turnover_24h"),
    ("volume_24h", "volume_24h"),
    ("price_24h_pcnt", "price_24h_pcnt"),
    ("funding_rate", "funding_rate"),
)


def ticker_records(ev: TickerLike) -> list[WalRecord]:
    row: dict[str, object] = {}
    for attr, col in _TICKER_COLS:
        value: Decimal | None = getattr(ev, attr)
        if value is not None:
            row[col] = _num(value)
    if ev.next_funding_time is not None:
        row["next_funding_ts"] = ev.next_funding_time
    return [_rec("tickers", ev.symbol, ev.ts_event, 0, 0, row)]


def liquidation_records(ev: LiquidationLike) -> list[WalRecord]:
    # DDL `side` = the closing order's side: a long is closed by a sell (never read `side`).
    closing = "sell" if ev.liquidated_side == "long" else "buy"
    row: dict[str, object] = {
        "side": closing,
        "price": _num(ev.price),
        "size": _num(ev.qty),
        "notional": _num(ev.notional),
        "stream": "all",
        # Part of the DEDUP key since QuestDB migration 0005: distinct prints in one batch
        # with equal side/price/size must stay distinct rows (C-2.15).
        "batch_index": ev.batch_index,
    }
    return [_rec("liquidations", ev.symbol, ev.ts_event, ev.batch_index, 0, row)]


# --- the writer ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WriterConfig:
    """`CV_RECORDER_WAL_*` (20-architecture.md §7.2) and the §3.8 batching thresholds."""

    wal_dir: Path
    wal_max_bytes: int = 1 << 30
    flush_rows: int = 10_000
    flush_interval_s: float = 0.2
    #: Per-lane in-memory bound (rows); past it the lane spills (C-2.18).
    max_queue_rows: int = 50_000
    #: Rows per WAL run while sorting a replay (the replay memory bound).
    replay_chunk_rows: int = 50_000
    write_timeout_s: float = 5.0
    store_timeout_s: float = 5.0
    replay_retry_s: float = 1.0
    counters_interval_s: float = 10.0
    poll_s: float = 0.01
    #: Symbols whose gap/counter state may wait for a session; past it windows merge (widen).
    max_pending_symbols: int = 1024
    #: SR-096: paths the WAL must not share a device with (Postgres data, logs, the app).
    protected_paths: tuple[Path, ...] = ()


def default_protected_paths(settings: Settings) -> tuple[Path, ...]:
    """SR-096: the data roots the backend needs on a volume separate from the WAL. These are
    the Parquet tier root, the audit WAL dir and the bars state root. The Postgres data dir is
    not visible to the app (`CV_PG_DSN` is a DSN), so deploy docs put it under the data root."""
    roots = [
        Path(settings.parquet_root),
        Path(settings.audit_wal_path).resolve().parent,
        Path(settings.bars_state_root),
    ]
    return tuple(dict.fromkeys(p.expanduser() for p in roots))


def writer_config_from_settings(settings: Settings, **overrides: object) -> WriterConfig:
    """The only production construction path: WAL keys plus SR-096 protected paths, so
    `check_wal_volume` is never vacuous by default."""
    base: dict[str, object] = {
        "wal_dir": Path(settings.recorder_wal_dir),
        "wal_max_bytes": settings.recorder_wal_max_bytes,
        "protected_paths": default_protected_paths(settings),
    }
    base.update(overrides)
    return WriterConfig(**base)  # type: ignore[arg-type]  # keys are WriterConfig fields


@dataclass(slots=True)
class _Counters:
    received: int = 0
    dropped: int = 0
    bytes_written: int = 0
    reconnects: int = 0

    def any(self) -> bool:
        return bool(self.received or self.dropped or self.bytes_written or self.reconnects)

    def add(self, other: _Counters) -> None:
        self.received += other.received
        self.dropped += other.dropped
        self.bytes_written += other.bytes_written
        self.reconnects += other.reconnects


@dataclass(slots=True)
class _Lane:
    """One stream: its own sink (ILP connection), queue, spill buffer, WAL and locks."""

    stream: Stream
    sink: RowSink
    wal: SpillWal
    queue: deque[WalRecord] = field(default_factory=deque)
    oldest_at: float | None = None
    spilling: bool = False
    #: Records admitted while spilling; appended to the WAL in one write+fsync per pump.
    spill_buf: list[WalRecord] = field(default_factory=list)
    next_replay_at: float = 0.0
    #: Symbols with an open drop episode (one critical event each; cleared on drain).
    episodes: set[str] = field(default_factory=set)
    flush_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    wal_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


SinkFactory = Callable[[Stream], RowSink]


class StreamWriter:
    """Per-stream batched ILP writer with WAL spill and explicit drop gaps (module docstring).

    `sink_factory(stream)` gives each lane its own sink (in production, one `IlpWriter` + TCP
    connection per stream, so five in total). This keeps a stalled stream from blocking
    another lane's socket or lock. Construct, then `await open()` (WAL dirs, SR-096 volume
    check, budget recovery, all off the loop), then `await start()`."""

    def __init__(
        self,
        sink_factory: SinkFactory,
        store: RecorderStore,
        events: SystemEventWriter,
        config: WriterConfig,
        *,
        clock: Callable[[], float],
        wall_clock_us: Callable[[], int],
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        fsync: Callable[[int], None] = os.fsync,
    ) -> None:
        self._store = store
        self._events = events
        self._cfg = config
        self._clock = clock
        self._wall_us = wall_clock_us
        self._sleep = sleep
        self._budget = WalBudget(config.wal_max_bytes)
        self._lanes: dict[Stream, _Lane] = {
            s: _Lane(
                stream=s,
                sink=sink_factory(s),
                wal=SpillWal(
                    config.wal_dir / s,
                    self._budget,
                    chunk_rows=config.replay_chunk_rows,
                    fsync=fsync,
                ),
            )
            for s in STREAMS
        }
        self._opened = False
        self._active: set[str] = set()
        self._counters: dict[str, _Counters] = {}
        #: (symbol, stream) -> [first, last] dropped exch_ts (µs), not yet persisted.
        self._gaps: dict[tuple[str, Stream], list[int]] = {}
        #: Last observed delta update_id per symbol (seq jumps are E16-T04's to convert).
        self._last_update_id: dict[str, int] = {}
        self.seq_jumps: deque[tuple[str, int, int]] = deque(maxlen=1024)
        #: E16-T04 signal: (symbol, last delta exch_ts, jumped delta exch_ts) in µs.
        self._seq_jump_windows: deque[tuple[str, int, int]] = deque(maxlen=1024)
        self._last_delta_ts: dict[str, int] = {}
        #: symbol -> [min, max] admitted exch_ts (µs) since the last `take_event_bounds`.
        self._bounds: dict[str, list[int]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._next_counters_at = 0.0
        self._publish_gauges()

    async def open(self) -> None:
        """Create the WAL dirs, enforce SR-096 and recover the budget from a previous process.

        Raises `RecorderWalVolumeError` (shared volume) or `OSError` (unusable WAL dir). The
        caller must then refuse to start recording."""
        await asyncio.to_thread(check_wal_volume, self._cfg.wal_dir, self._cfg.protected_paths)
        for lane in self._lanes.values():
            await asyncio.to_thread(lane.wal.open)
        self._opened = True
        self._publish_gauges()

    # -- effective set (C-2.20: a plain set, never an interpreter) ---------------------------

    def seed(self, symbols: Sequence[str]) -> None:
        self._active = set(symbols)

    def on_set_changed(self, event: RecorderSetChanged) -> None:
        if event.change == "removed":
            self._active.discard(event.symbol)
            # A re-add must not compare against a stale update_id (false seq jump). Counters
            # and gaps are kept until persisted.
            self._last_update_id.pop(event.symbol, None)
            self._last_delta_ts.pop(event.symbol, None)
        else:
            self._active.add(event.symbol)

    def is_recording(self, symbol: str) -> bool:
        return symbol in self._active

    def note_reconnect(self, symbol: str) -> None:
        self._ctr(symbol).reconnects += 1

    # -- hot path ------------------------------------------------------------------------------

    async def on_trade(self, ev: TradeLike) -> None:
        if ev.symbol in self._active:
            await self._admit("trades", ev.symbol, trade_records(ev))

    async def on_book_delta(self, ev: BookDeltaLike) -> None:
        if ev.symbol not in self._active:
            return
        last = self._last_update_id.get(ev.symbol)
        if last is not None and ev.prev_update_id != last:
            self.seq_jumps.append((ev.symbol, last, ev.prev_update_id))
            prev_ts = self._last_delta_ts.get(ev.symbol, ev.ts_event)
            self._seq_jump_windows.append((ev.symbol, prev_ts, ev.ts_event))
        self._last_update_id[ev.symbol] = ev.update_id
        self._last_delta_ts[ev.symbol] = ev.ts_event
        await self._admit("orderbook_deltas", ev.symbol, delta_records(ev))

    async def on_book_snapshot(self, ev: BookSnapshotLike) -> None:
        if ev.symbol in self._active:
            self._last_update_id[ev.symbol] = ev.update_id
            await self._admit("orderbook_snapshots", ev.symbol, snapshot_records(ev))

    async def on_ticker(self, ev: TickerLike) -> None:
        if ev.symbol in self._active:
            await self._admit("tickers", ev.symbol, ticker_records(ev))

    async def on_liquidation(self, ev: LiquidationLike) -> None:
        if ev.symbol in self._active:
            await self._admit("liquidations", ev.symbol, liquidation_records(ev))

    def _ctr(self, symbol: str) -> _Counters:
        ctr = self._counters.get(symbol)
        if ctr is None:
            ctr = self._counters[symbol] = _Counters()
        return ctr

    async def _admit(self, stream: Stream, symbol: str, records: list[WalRecord]) -> None:
        """Never awaits I/O: the queue or the spill buffer, both drained by the lane's pump."""
        self._ctr(symbol).received += 1
        if not records:
            return
        ts = records[0].exch_ts
        b = self._bounds.get(symbol)
        if b is None:
            self._bounds[symbol] = [ts, ts]
        elif ts < b[0]:
            b[0] = ts
        elif ts > b[1]:
            b[1] = ts
        lane = self._lanes[stream]
        if lane.spilling:
            lane.spill_buf.extend(records)
        elif len(lane.queue) + len(records) > self._cfg.max_queue_rows:
            # Enter spill mode; queued rows are older and go to the WAL first.
            lane.spilling = True
            lane.next_replay_at = self._clock() + self._cfg.replay_retry_s
            lane.spill_buf = [*lane.queue, *lane.spill_buf, *records]
            lane.queue.clear()
            lane.oldest_at = None
            logger().warning("recorder_spill_started", stream=stream, reason="queue_full")
        else:
            if not lane.queue:
                lane.oldest_at = self._clock()
            lane.queue.extend(records)
        # The spill buffer is bounded like the queue: past it, the producer pays one batched
        # WAL write (not one per message).
        if len(lane.spill_buf) >= self._cfg.max_queue_rows:
            await self._drain_spill_buf(lane)
        self._publish_gauges()

    # -- flush ---------------------------------------------------------------------------------

    def _due(self, lane: _Lane, now: float) -> bool:
        if not lane.queue or lane.oldest_at is None:
            return False
        full = len(lane.queue) >= self._cfg.flush_rows
        return full or now - lane.oldest_at >= self._cfg.flush_interval_s

    async def pump(self, stream: Stream) -> None:
        """One lane step. Spilling: one batched WAL append, then a replay if it is due.
        Otherwise: flush every due batch (a full batch's remainder goes out promptly)."""
        lane = self._lanes[stream]
        if lane.spilling:
            await self._drain_spill_buf(lane)
            if self._clock() >= lane.next_replay_at:
                await self._replay(lane)
            return
        while not lane.spilling and self._due(lane, self._clock()):
            await self._flush(lane)

    async def _write(self, lane: _Lane, records: Sequence[WalRecord]) -> None:
        """Send one batch through the lane's own sink, bounded by `write_timeout_s`."""
        rows = [dict(r.row) for r in records]
        started = self._clock()
        async with asyncio.timeout(self._cfg.write_timeout_s):
            await lane.sink.write_rows(lane.stream, rows, "ts")
            await lane.sink.flush(lane.stream)
        recorder_flush_duration_seconds.observe(max(self._clock() - started, 0.0))
        recorder_rows_total.labels(stream=lane.stream).inc(len(records))
        schema = ALL_SCHEMAS[lane.stream]
        per_symbol: dict[str, int] = {}
        for r in records:
            body = {k: v for k, v in r.row.items() if k != "ts"}
            size = len(serialize_ilp_line(schema, body, r.exch_ts)) + 1
            per_symbol[r.symbol] = per_symbol.get(r.symbol, 0) + size
        for symbol, size in per_symbol.items():
            self._ctr(symbol).bytes_written += size
            recorder_bytes_written_total.labels(symbol=symbol, stream=lane.stream).inc(size)

    async def _flush(self, lane: _Lane) -> None:
        async with lane.flush_lock:
            if lane.spilling or not lane.queue:
                return
            n = min(len(lane.queue), self._cfg.flush_rows)
            batch = [lane.queue.popleft() for _ in range(n)]
            # The remainder is at least as old as the batch: keep its age (≤200 ms promise).
            if not lane.queue:
                lane.oldest_at = None
            try:
                await self._write(lane, batch)
            except asyncio.CancelledError:
                lane.queue.extendleft(reversed(batch))
                if lane.oldest_at is None:
                    lane.oldest_at = self._clock()
                raise
            except Exception as exc:
                logger().error(
                    "recorder_write_failed", stream=lane.stream, rows=len(batch), error=str(exc)
                )
                lane.spilling = True
                lane.next_replay_at = self._clock() + self._cfg.replay_retry_s
                lane.spill_buf = [*batch, *lane.queue, *lane.spill_buf]
                lane.queue.clear()
                lane.oldest_at = None
                logger().warning("recorder_spill_started", stream=lane.stream, reason="sink")
            finally:
                self._publish_gauges()
        if lane.spilling:
            await self._drain_spill_buf(lane)

    # -- spill / drop --------------------------------------------------------------------------

    async def _drain_spill_buf(self, lane: _Lane) -> None:
        """Append the whole spill buffer to the WAL: one write + one fsync. Refused frames
        (budget) or an `OSError` (disk full, chaos 13) become recorded drops."""
        async with lane.wal_lock:
            records, lane.spill_buf = lane.spill_buf, []
            if not records:
                return
            try:
                written = await asyncio.to_thread(lane.wal.append, records)
            except OSError as exc:
                logger().error("recorder_wal_write_failed", stream=lane.stream, error=str(exc))
                written = 0
        if written < len(records):
            await self._drop(lane, records[written:])
        self._publish_gauges()

    def _widen(self, symbol: str, stream: Stream, lo: int, hi: int) -> None:
        window = self._gaps.get((symbol, stream))
        if window is None:
            if len(self._gaps) >= self._cfg.max_pending_symbols * len(STREAMS):
                # Never dropped: kept and alarmed (the key space is symbols x 5 streams).
                logger().critical("recorder_gap_buffer_full", pending=len(self._gaps))
            self._gaps[(symbol, stream)] = [lo, hi]
        else:
            window[0], window[1] = min(window[0], lo), max(window[1], hi)

    async def _drop(self, lane: _Lane, records: list[WalRecord]) -> None:
        new_episodes: set[str] = set()
        for rec in records:
            self._ctr(rec.symbol).dropped += 1
            self._widen(rec.symbol, lane.stream, rec.exch_ts, rec.exch_ts)
            if rec.symbol not in lane.episodes:
                lane.episodes.add(rec.symbol)
                new_episodes.add(rec.symbol)
        for symbol in sorted(new_episodes):
            await self._critical(
                "recorder_wal_full",
                symbol,
                lane.stream,
                f"recorder dropping {lane.stream} for {symbol}: WAL full, QuestDB unavailable",
            )

    async def _critical(self, kind: str, symbol: str, stream: Stream, message: str) -> None:
        logger().critical(kind, symbol=symbol, stream=stream)
        event = SystemEvent(
            component="recorder",
            kind=kind,
            severity="critical",
            message=message,
            details={"symbol": symbol, "stream": stream, "cause": GAP_CAUSE},
        )
        try:
            async with asyncio.timeout(self._cfg.store_timeout_s):
                await self._events.write(event)
        except Exception as exc:
            logger().error("recorder_event_write_failed", symbol=symbol, error=str(exc))

    # -- replay --------------------------------------------------------------------------------

    async def recover(self) -> None:
        """QuestDB is back (readiness probe): replay every spilling lane now."""
        for lane in self._lanes.values():
            if lane.spilling:
                lane.next_replay_at = 0.0
                await self._drain_spill_buf(lane)
                await self._replay(lane)

    async def _replay(self, lane: _Lane) -> bool:
        """Stream the lane's WAL into QuestDB in `exch_ts` order. Each committed batch moves
        the durable checkpoint forward, so a failed or killed replay resumes where it stopped.
        Returns True once the lane has fully drained and left spill mode."""
        async with lane.flush_lock:
            while True:
                async with lane.wal_lock:
                    try:
                        prep = await asyncio.to_thread(lane.wal.begin_replay)
                    except OSError as exc:
                        lane.next_replay_at = self._clock() + self._cfg.replay_retry_s
                        logger().error(
                            "recorder_replay_io_failed", stream=lane.stream, error=str(exc)
                        )
                        return False
                if prep.corrupt_bytes:
                    await self._corrupt(lane, prep.corrupt_bytes, prep.corrupt_windows)
                if not prep.pending and not lane.spill_buf:
                    lane.spilling = False
                    lane.episodes.clear()
                    logger().info("recorder_spill_drained", stream=lane.stream)
                    self._publish_gauges()
                    return True
                if not prep.pending:
                    await self._drain_spill_buf(lane)
                    continue
                if not await self._replay_runs(lane):
                    return False
                async with lane.wal_lock:
                    await asyncio.to_thread(lane.wal.finish_replay)
                await self._drain_spill_buf(lane)
                self._publish_gauges()

    async def _replay_runs(self, lane: _Lane) -> bool:
        """Verify the runs (a damaged run is quarantined and becomes a gap), then stream them.
        True only once every frame of every run was read and committed."""
        async with lane.wal_lock:
            try:
                verified = await asyncio.to_thread(lane.wal.verify_runs)
            except OSError as exc:
                lane.next_replay_at = self._clock() + self._cfg.replay_retry_s
                logger().error("recorder_replay_io_failed", stream=lane.stream, error=str(exc))
                return False
        # Windows, not bytes: after a crash the damaged file is already in corrupt/ (0 bytes
        # seen now) but its windows are still pending in runs/DAMAGED.
        if verified.corrupt_bytes or verified.corrupt_windows:
            await self._corrupt(lane, verified.corrupt_bytes, verified.corrupt_windows)
            await self.flush_gaps()
            keys = {(sym, lane.stream) for sym in verified.corrupt_windows}
            if not keys & self._gaps.keys():
                # Every window is a persisted row: only now may the durable marker go.
                async with lane.wal_lock:
                    await asyncio.to_thread(lane.wal.ack_damaged)
        it = lane.wal.iter_replay()
        try:
            while True:
                batch = await asyncio.to_thread(_take, it, self._cfg.flush_rows)
                for msg in lane.wal.warnings:
                    logger().warning(
                        "recorder_replay_checkpoint_reset", stream=lane.stream, detail=msg
                    )
                lane.wal.warnings.clear()
                if not batch:
                    if lane.wal.replay_complete():
                        return True
                    # Frames were not all readable (changed after verification): keep runs/,
                    # restart from 0 next time (DEDUP makes the re-send idempotent).
                    logger().error(
                        "recorder_replay_incomplete",
                        stream=lane.stream,
                        read=lane.wal.consumed,
                        expected=lane.wal.total(),
                    )
                    await asyncio.to_thread(lane.wal.commit, 0)
                    lane.next_replay_at = self._clock() + self._cfg.replay_retry_s
                    return False
                try:
                    await self._write(lane, [rec for _, rec in batch])
                except Exception as exc:
                    lane.next_replay_at = self._clock() + self._cfg.replay_retry_s
                    logger().warning("recorder_replay_failed", stream=lane.stream, error=str(exc))
                    return False
                await asyncio.to_thread(lane.wal.commit, batch[-1][0] + 1)
        finally:
            it.close()

    async def _corrupt(
        self, lane: _Lane, corrupt_bytes: int, windows: dict[str, tuple[int, int]]
    ) -> None:
        """A corrupt tail is a loss of unknown extent: one gap per symbol it held (from the WAL
        meta; the active set if the meta is gone), from its last good row to the tail's end."""
        logger().error("recorder_wal_corrupt", stream=lane.stream, bytes=corrupt_bytes)
        if not windows:
            now = self._wall_us()
            windows = {s: (now - 1, now) for s in self._active}
        for symbol, (lo, hi) in sorted(windows.items()):
            self._widen(symbol, lane.stream, lo, hi)
            await self._critical(
                "recorder_wal_corrupt",
                symbol,
                lane.stream,
                f"recorder WAL corrupt for {lane.stream}/{symbol}: tail quarantined",
            )

    # -- periodic: gaps + counters (kept until a live session accepts them) --------------------

    async def flush_gaps(self) -> None:
        for (symbol, stream), (first, last) in list(self._gaps.items()):
            gap_start = _EPOCH + timedelta(microseconds=first)
            gap_end = _EPOCH + timedelta(microseconds=max(last, first + 1))
            try:
                async with asyncio.timeout(self._cfg.store_timeout_s):
                    ok = await self._store.record_live_gap(
                        symbol=symbol,
                        stream=STREAM_KIND[stream],
                        gap_start=gap_start,
                        gap_end=gap_end,
                        cause=GAP_CAUSE,
                    )
            except Exception as exc:
                logger().error("recorder_gap_write_failed", symbol=symbol, error=str(exc))
                continue
            if not ok:
                # No live session yet (E16-T04 opens it): keep the window and retry.
                logger().warning("recorder_gap_awaiting_session", symbol=symbol, stream=stream)
                continue
            window = self._gaps.get((symbol, stream))
            if window == [first, last]:
                del self._gaps[(symbol, stream)]
            elif window is not None:
                # Widened while the insert was in flight: keep only the part not yet written.
                window[0] = max(window[0], last)

    async def flush_counters(self) -> None:
        for symbol, ctr in list(self._counters.items()):
            if not ctr.any():
                del self._counters[symbol]
                continue
            snap = _Counters(ctr.received, ctr.dropped, ctr.bytes_written, ctr.reconnects)
            try:
                async with asyncio.timeout(self._cfg.store_timeout_s):
                    ok = await self._store.add_session_counters(
                        symbol,
                        messages_received=snap.received,
                        messages_dropped=snap.dropped,
                        bytes_written=snap.bytes_written,
                        reconnect_count=snap.reconnects,
                    )
            except Exception as exc:
                logger().error("recorder_counters_write_failed", symbol=symbol, error=str(exc))
                continue
            if not ok:
                continue  # no live session: deltas keep accumulating
            ctr.received -= snap.received
            ctr.dropped -= snap.dropped
            ctr.bytes_written -= snap.bytes_written
            ctr.reconnects -= snap.reconnects
            if not ctr.any():
                del self._counters[symbol]

    async def tick(self) -> None:
        """Every `counters_interval_s`: persist gap rows, then the per-symbol counters."""
        now = self._clock()
        if now < self._next_counters_at:
            return
        self._next_counters_at = now + self._cfg.counters_interval_s
        await self.flush_gaps()
        await self.flush_counters()

    # -- lifecycle -----------------------------------------------------------------------------

    async def start(self) -> None:
        """Replay any WAL a previous process left (startup recovery), then run the lanes."""
        if not self._opened:
            await self.open()
        self._next_counters_at = self._clock() + self._cfg.counters_interval_s
        for lane in self._lanes.values():
            if await asyncio.to_thread(lane.wal.has_data):
                lane.spilling = True
                await self._replay(lane)
        for stream in STREAMS:
            self._spawn(self._lane_loop(stream), f"recorder-lane-{stream}")
        self._spawn(self._tick_loop(), "recorder-counters")

    def _spawn(self, coro: Coroutine[object, object, None], name: str) -> None:
        task = spawn(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger().error(
                "recorder_task_crashed", task=task.get_name(), error=str(task.exception())
            )

    async def _lane_loop(self, stream: Stream) -> None:
        while True:
            try:
                await self.pump(stream)
            except Exception as exc:
                logger().error("recorder_lane_error", stream=stream, error=str(exc))
            await self._sleep(self._cfg.poll_s)

    async def _tick_loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:
                logger().error("recorder_tick_error", error=str(exc))
            await self._sleep(self._cfg.poll_s * 10)

    async def stop(self, timeout_s: float = 10.0) -> None:
        """Cancel the loops, flush what is queued (spilling what cannot be flushed), then
        persist gaps/counters. Gap windows still without a live session are raised as one
        critical event each, which is the durable evidence until a session exists. They are
        never dropped silently."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        try:
            async with asyncio.timeout(timeout_s):
                for lane in self._lanes.values():
                    while lane.queue and not lane.spilling:
                        await self._flush(lane)
        except TimeoutError:
            for lane in self._lanes.values():
                if lane.queue:
                    lane.spilling = True
                    lane.spill_buf = [*lane.queue, *lane.spill_buf]
                    lane.queue.clear()
        for lane in self._lanes.values():
            await self._drain_spill_buf(lane)
        self._next_counters_at = 0.0
        await self.tick()
        for (symbol, stream), (first, last) in sorted(self._gaps.items()):
            logger().critical(
                "recorder_gap_unpersisted", symbol=symbol, stream=stream, start=first, end=last
            )
            await self._critical(
                "recorder_gap_unpersisted",
                symbol,
                stream,
                f"{GAP_CAUSE} gap {first}..{last} (us) for {stream}/{symbol} "
                "has no live recording session to attach to",
            )

    # -- observability -------------------------------------------------------------------------

    @property
    def backlog_rows(self) -> int:
        return sum(len(lane.queue) + len(lane.spill_buf) for lane in self._lanes.values())

    @property
    def spill_bytes(self) -> int:
        return self._budget.used

    def is_spilling(self, stream: Stream) -> bool:
        return self._lanes[stream].spilling

    def take_seq_jump_windows(self) -> list[tuple[str, int, int]]:
        """Drain the seq-jump windows (E16-T04 turns them into `seq_jump` gap rows)."""
        out = list(self._seq_jump_windows)
        self._seq_jump_windows.clear()
        return out

    def take_event_bounds(self) -> dict[str, tuple[int, int]]:
        """Drain per-symbol admitted exch_ts bounds (session `first/last_event_ts`)."""
        out = {sym: (b[0], b[1]) for sym, b in self._bounds.items()}
        self._bounds.clear()
        return out

    def pending_gaps(self) -> dict[tuple[str, Stream], tuple[int, int]]:
        return {k: (v[0], v[1]) for k, v in self._gaps.items()}

    def _publish_gauges(self) -> None:
        recorder_write_backlog_rows.set(self.backlog_rows)
        recorder_spill_bytes.set(self._budget.used)


def _take(it: Iterator[tuple[int, WalRecord]], n: int) -> list[tuple[int, WalRecord]]:
    """Advance a WAL merge iterator by up to `n` items (called via `to_thread`)."""
    out: list[tuple[int, WalRecord]] = []
    for item in it:
        out.append(item)
        if len(out) >= n:
            break
    return out


def dedup_sorted(records: Sequence[WalRecord]) -> list[WalRecord]:
    """`exch_ts` order (stable), first occurrence of each `(symbol, stream, exch_ts, seq, sub)`."""
    seen: set[tuple[str, str, int, int, int]] = set()
    out: list[WalRecord] = []
    for rec in sorted(records, key=lambda r: r.exch_ts):
        if rec.key not in seen:
            seen.add(rec.key)
            out.append(rec)
    return out
