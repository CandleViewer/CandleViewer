"""`trades.{symbol}` (E22-T02, #654; `23-ws-protocol.md` §3.4 kind 3, §6.1, §8.2, §8.6, §14.2):
the `trades` family's snapshot source, publisher and subscription leases, over the big-trade tape
(`orderflow/bigtrade_tape.py`) that `GET /market/trades` reads too.

- **Leases.** A live subscription holds one `TradesLease` (`hold`, from `ConnectionAuthz`): its
  symbol's `SymbolTape` (one engine per symbol, the server's threshold config) and the `OptionTape`
  of its option set, shared by every subscription with the same options. Refused before anything
  is held: a `min_size` below the instrument's `MIN_SIZE_FLOOR` (SR-E22-03, `invalid_options`
  on `min_size`), a user's 61st `trades` subscription across connections (SR-E22-06) or a third
  distinct option set of one symbol for one user (SR-E22-07), both `subscription_limit`, and a
  symbol past `MAX_SYMBOLS`. The last lease of an option set, then of a symbol, frees it. A lease
  taken while the ingestion trade stream or the symbol's tick size is unknown waits for them: its
  subscription stays `snapshot_pending`, and the first window that finds both opens the tapes and
  snaps it.
- **Prints.** One bus subscription on `{env}.md.*.trade` (`INVALIDATE_ON_FULL`, `BUS_QUEUE_MAX`):
  every drain is one source batch per held symbol, read by the symbol's tape (flags, tick
  direction; `recent` keeps the last `RECENT_PRINTS` read) and by each of its option tapes
  (`min_size`, clustering). A new symbol reads the ingestion hot tape first, and a new option tape
  reads the symbol's `recent`, so the 200-item snapshot is warm and REST and WS start alike. On the
  bus's overflow marker each held symbol catches up from the hot tape and every live `trades`
  subscription re-snapshots (`upstream_desync`, §7.4).
- **Frames.** At most one `d` per option tape per `window_s` (the family's 100 ms, §6.1); with
  `CV_WS_BACKPRESSURE_ENABLED` on the pacer windows after it. A frame appends the items closed
  since the last one (a cluster closes by print time, or once the reader's clock passes its
  deadline plus `LATE_GRACE_US`), `dropped` since the last one (a frame goes out for drops alone:
  never silent; prints `min_size` filtered, plus those shed when more than `PENDING_MAX` items
  waited for one frame, `overflow`), the symbol's `big_trade_threshold`, and `coalesced_count`,
  the source batches it appended. It carries a kind-3 part only when one can say everything
  (§3.4): no cluster of more than one print, no drop, the threshold unchanged since the option
  tape's last frame, and the instrument scales known and exact; else it leaves structured, binary
  subscribers included.
- **Snapshot.** The option tape's last `SNAPSHOT_ITEMS` sent items, oldest first, `dropped` 0 and
  the current threshold; kind 3 beside it unless an item is a cluster. `generation` moves with
  every frame and threshold change; continuity is never proven (§7.6).

Plain asyncio on the hot path, never a statechart (C-2.20); every structure is bounded (C-2.18).
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import math
import time
from collections import Counter, deque
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Final, Protocol

import structlog

from candleviewer.bus import Bus, QueuePolicy, StreamInvalidated, TopicPattern
from candleviewer.bus import Subscription as BusSubscription
from candleviewer.bus.models import WILDCARD
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.observability.context import spawn
from candleviewer.orderflow import limits as L
from candleviewer.orderflow.bigtrade_models import BigTradeConfig
from candleviewer.orderflow.bigtrade_tape import (
    Options,
    OptionTape,
    SymbolTape,
    TapeItem,
    TapePrint,
)
from candleviewer.ws.binary import TRADES, Frame
from candleviewer.ws.metrics import (
    cv_ws_frames_emitted_total,
    cv_ws_tape_frames_coalesced_total,
    cv_ws_tape_prints_dropped_total,
    cv_ws_trades_subscribe_rejected_total,
)
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody
from candleviewer.ws.topics import TopicError

if TYPE_CHECKING:
    from candleviewer.ws.permissions import Subscription

FAMILY: Final = "trades"
#: §6.1: the family's default throttle, one window per option tape.
WINDOW_S: Final = 0.1
#: §6.1: "Last 200 prints".
SNAPSHOT_ITEMS: Final = 200
#: Prints a symbol keeps for a new option tape: the ingestion hot tape's depth. Memory envelope:
#: a `TapePrint` (slots: the event, a bool, an interned direction) plus its deque slot measures
#: ~65 B, so 1 000 of them are ~64 KiB per held symbol and `MAX_SYMBOLS` (1 024) of them ~64 MiB.
#: The `TradeEvent`s (~1.8 KiB each) are the objects the ingestion hot tape already holds: the bus
#: hands the stream's own events over and both deques keep the newest 1 000 of one stream, so
#: they add nothing but a short lag. `MAX_SYMBOLS` stays above the catalogue (~600) rather than at
#: it: a catalogue that grows past a lower cap would refuse a listed symbol.
RECENT_PRINTS: Final = 1000
#: A cluster closes on the reader's clock this long after its deadline, so a print that lands late
#: still joins it as it does on REST (print time).
LATE_GRACE_US: Final = 500_000
#: The bus queue, drained at every wake: only a stuck loop fills it.
BUS_QUEUE_MAX: Final = 16_384
#: Symbols held at once (the catalogue lists some 600).
MAX_SYMBOLS: Final = 1024
#: One window's print budget: budget #5's 5 000 prints/s (`PRINTS_PER_MS_BUDGET`) over the
#: family's 100 ms window, 500 prints.
WINDOW_PRINT_BUDGET: Final = L.PRINTS_PER_MS_BUDGET * 100
#: Items an option tape keeps between two frames: ten windows' budget, room for a paced or late
#: flush. Past it the oldest are shed and their prints counted in `dropped` (`overflow`).
PENDING_MAX: Final = 10 * WINDOW_PRINT_BUDGET
_U32_MAX: Final = 2**32 - 1
_SIDES: Final = {"buy": 0, "sell": 1}
_DEFAULTS: Final[Mapping[str, int]] = {"cluster_window_ms": 0, "cluster_tolerance_ticks": 0}


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _now_us() -> int:
    return time.time_ns() // 1000


class TradeTape(Protocol):
    """The ingestion trade stream's reads (`TradeStream`): the hot tape and the tick size."""

    def recent(self, symbol: str) -> list[TradeEvent]: ...

    def tick_size(self, symbol: str) -> Decimal | None: ...


#: A symbol's `(price_scale, qty_scale)` from the instrument catalogue; `None` when unknown.
Scales = Callable[[str], tuple[int, int] | None]
#: A symbol's `MIN_SIZE_FLOOR` (SR-E22-03); `None` when the catalogue does not list it.
Floor = Callable[[str], Decimal | None]


@dataclass(frozen=True, slots=True)
class TradesLease:
    """What one live `trades.*` subscription holds."""

    consumer: str
    user: str
    symbol: str
    options: Options


@dataclass(slots=True)
class _OptionState:
    options: Options
    tape: OptionTape | None = None  # None while its symbol waits for the stream
    consumers: set[str] = field(default_factory=set)
    history: deque[TapeItem] = field(default_factory=lambda: deque(maxlen=SNAPSHOT_ITEMS))
    pending: deque[TapeItem] = field(default_factory=lambda: deque(maxlen=PENDING_MAX))
    overflow: int = 0  # prints shed from `pending` since the last frame
    batches: int = 0
    version: int = 0
    sent_threshold: Decimal | None = None
    last_flush: float = -math.inf


@dataclass(slots=True)
class _SymbolState:
    symbol: str
    tape: SymbolTape | None = None  # None while the stream or the tick size is unknown
    recent: deque[TapePrint] = field(default_factory=lambda: deque(maxlen=RECENT_PRINTS))
    options: dict[Options, _OptionState] = field(default_factory=dict)


def options_of(raw: Mapping[str, Any]) -> Options:
    """A subscription's option set from its validated `opts` (decimal `min_size` as a string)."""
    min_size = raw.get("min_size")
    return Options(
        None if min_size is None else Decimal(str(min_size)),
        int(raw.get("cluster_window_ms", 0)),
        int(raw.get("cluster_tolerance_ticks", 0)),
    )


def _refuse(code: str, message: str, reason: str, field_: str | None = None) -> TopicError:
    cv_ws_trades_subscribe_rejected_total.labels(reason=reason).inc()
    return TopicError(code, message, field_)


def note_option_refusal(ch: object, code: str, field_: str | None) -> None:
    """Count an out-of-range cluster option the registry refused on a `trades` topic (SR-E22-04)."""
    cluster = field_ in _DEFAULTS
    if cluster and code == "invalid_options" and isinstance(ch, str) and ch.startswith("trades."):
        cv_ws_trades_subscribe_rejected_total.labels(reason="cluster_range").inc()


class TradesTopic:
    """The `trades` family's leases, snapshot source and publisher (module docstring), for the
    event loop that runs the gateway and the ingestion stream: no locks."""

    def __init__(
        self,
        hub: SequencingHub,
        *,
        reader: Callable[[], TradeTape | None],
        bus: Bus,
        env: str,
        scales: Scales,
        floor: Floor,
        config: Callable[[str], BigTradeConfig] = lambda _symbol: BigTradeConfig(),
        clock: Callable[[], float] = time.monotonic,
        now_us: Callable[[], int] = _now_us,
        window_s: float = WINDOW_S,
        max_symbols: int = MAX_SYMBOLS,
        pending_max: int = PENDING_MAX,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._hub, self._reader, self._bus, self._env = hub, reader, bus, env
        self._scales, self._floor, self._config = scales, floor, config
        self._clock, self._now_us, self._window_s = clock, now_us, window_s
        self._max, self._pending_max, self._sleep = max_symbols, pending_max, sleep
        self._symbols: dict[str, _SymbolState] = {}
        self._per_user: Counter[str] = Counter()
        self._sets: dict[tuple[str, str], Counter[Options]] = {}
        self._sub: BusSubscription | None = None
        self._task: asyncio.Task[None] | None = None

    # -- leases (`ConnectionAuthz`) ----------------------------------------------------------

    def hold(self, consumer: str, user: str, symbol: str, options: Options) -> TradesLease:
        """Take a lease for a new subscription, or raise `TopicError` with nothing held."""
        self._check_floor(symbol, options)
        if self._per_user[user] >= L.TRADES_SUBS_PER_USER_MAX:
            n = L.TRADES_SUBS_PER_USER_MAX
            raise _refuse(
                "subscription_limit", f"At most {n} trades subscriptions per user.", "sub_cap_user"
            )
        self._check_sets(user, symbol, options)
        state = self._option(symbol, options)
        lease = TradesLease(consumer, user, symbol, options)
        state.consumers.add(consumer)
        self._per_user[user] += 1
        self._sets.setdefault((user, symbol), Counter())[options] += 1
        return lease

    def check_retune(self, lease: TradesLease, options: Options) -> None:
        """Whether a `ctl` of `min_size` (§6.1) may move `lease` to `options`, as `hold` checks
        a new one; raises `TopicError`, changing nothing."""
        if options == lease.options:
            return
        self._check_floor(lease.symbol, options)
        held = self._sets.get((lease.user, lease.symbol), Counter())
        others = len(held) - (1 if held[lease.options] == 1 else 0)
        if options not in held and others >= L.OPTION_SETS_PER_SYMBOL_MAX:
            raise self._sets_refusal()

    def retune(self, lease: TradesLease, options: Options) -> TradesLease:
        """Move `lease` to `options` once `check_retune` passed. Never re-snapshots."""
        if options == lease.options:
            return lease
        self.check_retune(lease, options)
        state = self._option(lease.symbol, options)
        self._release_sets(lease)
        moved = TradesLease(lease.consumer, lease.user, lease.symbol, options)
        state.consumers.add(lease.consumer)
        self._sets.setdefault((lease.user, lease.symbol), Counter())[options] += 1
        self._free(lease)
        return moved

    def release(self, lease: TradesLease) -> None:
        self._per_user[lease.user] -= 1
        if self._per_user[lease.user] <= 0:
            del self._per_user[lease.user]
        self._release_sets(lease)
        self._free(lease)

    def echo(self, symbol: str) -> dict[str, Any]:
        """`sub_ok.effective`'s threshold fields (§6.1): the current threshold, absolute."""
        state = self._symbols.get(symbol)
        tape = None if state is None else state.tape
        if tape is None:
            config = self._config(symbol)
            value = config.value if config.mode != "percentile" else Decimal(0)
            return {"big_trade_threshold": format(value, "f"), "big_trade_mode": config.mode}
        return {"big_trade_threshold": format(tape.threshold, "f"), "big_trade_mode": tape.mode}

    def _check_floor(self, symbol: str, options: Options) -> None:
        if options.min_size is None:
            return
        floor = self._floor(symbol)
        size = options.min_size
        if floor is None or not size.is_finite() or size < floor:
            bound = "unknown for this instrument" if floor is None else format(floor, "f")
            message = f"min_size must be at least the instrument floor ({bound})."
            raise _refuse("invalid_options", message, "min_size_floor", "min_size")

    def _check_sets(self, user: str, symbol: str, options: Options) -> None:
        held = self._sets.get((user, symbol))
        if held is not None and options not in held and len(held) >= L.OPTION_SETS_PER_SYMBOL_MAX:
            raise self._sets_refusal()

    def _sets_refusal(self) -> TopicError:
        n = L.OPTION_SETS_PER_SYMBOL_MAX
        message = f"At most {n} distinct trades option sets per symbol per user."
        return _refuse("subscription_limit", message, "option_sets")

    def _release_sets(self, lease: TradesLease) -> None:
        key = (lease.user, lease.symbol)
        held = self._sets.get(key)
        if held is None:
            return
        held[lease.options] -= 1
        if held[lease.options] <= 0:
            del held[lease.options]
        if not held:
            del self._sets[key]

    def _option(self, symbol: str, options: Options) -> _OptionState:
        state = self._symbols.get(symbol)
        if state is None:
            if len(self._symbols) >= self._max:
                message = "Too many symbols hold a trades subscription; retry later."
                raise _refuse("subscription_limit", message, "symbols")
            state = self._symbols[symbol] = _SymbolState(symbol)
            self._start(state)
        opt = state.options.get(options)
        if opt is None:
            opt = _OptionState(options, pending=deque(maxlen=self._pending_max))
            state.options[options] = opt
            self._open(state, opt)
        return opt

    def _start(self, state: _SymbolState) -> bool:
        """Open the symbol's tape, and each option tape it waited with, once the stream and the
        tick size are known: True when it is open."""
        if state.tape is not None:
            return True
        reader = self._reader()
        tick = None if reader is None else reader.tick_size(state.symbol)
        if reader is None or tick is None:
            return False
        state.tape = SymbolTape(state.symbol, tick, self._config(state.symbol))
        state.recent.extend(state.tape.read(reader.recent(state.symbol)))
        for opt in state.options.values():
            self._open(state, opt)
        return True

    def _open(self, state: _SymbolState, opt: _OptionState) -> None:
        if state.tape is None or opt.tape is not None:
            return
        opt.tape = OptionTape(state.tape.tick_size, opt.options)
        opt.history.extend(opt.tape.add(list(state.recent)))  # warm, as REST reads the tape
        opt.tape.take_dropped()  # none of those were since a frame of its own
        opt.sent_threshold = state.tape.threshold

    def _free(self, lease: TradesLease) -> None:
        state = self._symbols.get(lease.symbol)
        opt = None if state is None else state.options.get(lease.options)
        if state is None or opt is None:
            return
        opt.consumers.discard(lease.consumer)
        if not opt.consumers:
            del state.options[lease.options]
        if not state.options:
            del self._symbols[lease.symbol]

    # -- SnapshotSource ----------------------------------------------------------------------

    def _held(self, sub: Subscription) -> tuple[SymbolTape, _OptionState] | None:
        lease = sub.trades_lease
        state = None if lease is None else self._symbols.get(lease.symbol)
        opt = None if lease is None or state is None else state.options.get(lease.options)
        if state is None or state.tape is None or opt is None:
            return None
        return state.tape, opt

    def build(self, sub: Subscription) -> SnapshotBody | None:
        held = self._held(sub)
        if held is None:
            return None  # a replay one, not held, or waiting for the stream: it stays pending
        tape, opt = held
        symbol = tape.symbol
        items = list(opt.history)
        body = self._body(symbol, items, 0, tape.threshold)
        if sub.effective.get("encoding") == "binary" and all(i.cluster_size == 1 for i in items):
            part = self._part(symbol, items)
            if part is not None:
                return SnapshotBody(body, (part,), price_scale=part.price_scale,
                                    qty_scale=part.qty_scale)  # fmt: skip
        return SnapshotBody(body)

    def generation(self, sub: Subscription) -> int:
        held = self._held(sub)
        return 0 if held is None else held[1].version

    def continuity(self, sub: Subscription, from_ts_ms: int | None) -> bool:
        return False  # no delta history: `snapshot: false` is always `snapshot_forced`

    # -- deltas ------------------------------------------------------------------------------

    def offer(self, items: Iterable[object]) -> None:
        """One drain of the bus: per held symbol, one source batch."""
        by_symbol: dict[str, list[TradeEvent]] = {}
        invalidated = False
        for item in items:
            if isinstance(item, StreamInvalidated):
                invalidated = True
            elif isinstance(item, TradeEvent) and item.symbol in self._symbols:
                by_symbol.setdefault(item.symbol, []).append(item)
        for symbol, events in by_symbol.items():
            self._read(self._symbols[symbol], events)
        if invalidated:
            _log().warning("trades_topic_stream_invalidated")
            self._resync()

    def _read(self, state: _SymbolState, events: Sequence[TradeEvent]) -> None:
        if state.tape is None:
            return  # waiting: it reads the hot tape when it opens
        prints = state.tape.read(events)
        if not prints:
            return
        state.recent.extend(prints)
        for opt in state.options.values():
            if opt.tape is None:
                continue
            before = opt.tape.dropped
            items = opt.tape.add(prints)
            if items or opt.tape.dropped != before:
                _queue(opt, items)
                opt.batches += 1

    def tick(self) -> int:
        """Close the clusters past their deadline on the reader's clock, then publish each option
        tape whose window allows and that has something to say; the frames sent."""
        now, now_us, sent = self._clock(), self._now_us(), 0
        for state in list(self._symbols.values()):
            if state.tape is None:
                if self._start(state):  # the stream is up: its waiting subscriptions snap
                    sent += self._hub.flush_pending(functools.partial(_waited, symbol=state.symbol))
                continue
            for opt in list(state.options.values()):
                if opt.tape is None:
                    continue
                items = opt.tape.expire(now_us - LATE_GRACE_US)
                if items:
                    _queue(opt, items)
                    opt.batches += 1
                due = opt.pending or opt.tape.dropped or opt.overflow
                if due and now >= opt.last_flush + self._window_s:
                    sent += self._flush(state, opt, now)
        return sent

    def _flush(self, state: _SymbolState, opt: _OptionState, now: float) -> int:
        if state.tape is None or opt.tape is None:
            return 0
        symbol, threshold = state.tape.symbol, state.tape.threshold
        items = list(opt.pending)
        opt.pending.clear()
        filtered, overflow = opt.tape.take_dropped(), opt.overflow
        dropped, count = filtered + overflow, max(opt.batches, 1)
        opt.overflow, opt.batches, opt.last_flush = 0, 0, now
        changed = threshold != opt.sent_threshold
        opt.sent_threshold = threshold
        opt.history.extend(items)
        opt.version += 1
        body = self._body(symbol, items, dropped, threshold)
        part = None
        if not dropped and not changed and all(i.cluster_size == 1 for i in items):
            part = self._part(symbol, items)
        options = opt.tape.options
        try:
            sent = self._hub.publish(
                f"{FAMILY}.{symbol}",
                body,
                part=part,
                coalesced_count=count,
                select=lambda sub: _leased(sub, options),
            )
        except Exception as exc:  # contained: the topic is a view, the stream goes on
            _log().error("trades_topic_publish_failed", error=type(exc).__name__)
            self._resync()
            return 0
        cv_ws_frames_emitted_total.labels(topic=FAMILY).inc(sent)
        if filtered:
            cv_ws_tape_prints_dropped_total.labels(reason="min_size").inc(filtered)
        if overflow:
            cv_ws_tape_prints_dropped_total.labels(reason="overflow").inc(overflow)
        if count > 1:
            cv_ws_tape_frames_coalesced_total.inc()
        return sent

    def _body(
        self, symbol: str, items: Sequence[TapeItem], dropped: int, threshold: Decimal
    ) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "trades": [i.wire() for i in items],
            "dropped": dropped,
            "big_trade_threshold": format(threshold, "f"),
        }

    def _part(self, symbol: str, items: Sequence[TapeItem]) -> Frame | None:
        """The kind-3 form of `items` (§3.4), or None when the scales are unknown or a value is
        not exact at them, or the prints span more than a u32 of milliseconds."""
        scales = self._scales(symbol)
        if scales is None:
            return None
        ps, qs = scales
        base = items[0].first.event.ts_event // 1000 if items else 0
        records: list[tuple[int, ...]] = []
        try:
            for i in items:
                ev = i.first.event
                price, size = ev.price.scaleb(ps), i.size.scaleb(qs)
                offset = ev.ts_event // 1000 - base
                if price != price.to_integral_value() or size != size.to_integral_value():
                    return None
                if not 0 <= offset <= _U32_MAX:
                    return None
                flags = (1 if ev.is_block_trade else 0) | (0b1000 if i.big else 0)
                records.append((offset, int(price), int(size), _SIDES[ev.side], flags))
        except (ArithmeticError, InvalidOperation, KeyError):
            return None
        return Frame(TRADES, tuple(records), price_scale=ps, qty_scale=qs, ts_base_ms=base)

    def _resync(self) -> None:
        """The bus lost prints: catch every held symbol up from the hot tape, then re-snapshot
        every live `trades` subscription (§7.4 `upstream_desync`)."""
        reader = self._reader()
        if reader is not None:
            for state in list(self._symbols.values()):
                with contextlib.suppress(Exception):
                    self._read(state, reader.recent(state.symbol))
        try:
            self._hub.resnapshot(_live_trades, "upstream_desync")
        except Exception as exc:
            _log().error("trades_topic_resync_failed", error=type(exc).__name__)

    # -- lifecycle (`WsRuntime`) -------------------------------------------------------------

    def open(self) -> None:
        """Hold the bus topic (idempotent)."""
        if self._sub is None:
            pattern = TopicPattern(env=self._env, domain="md", symbol=WILDCARD, detail="trade")
            self._sub = self._bus.subscribe(
                "ws-trades-topic", pattern, QueuePolicy.INVALIDATE_ON_FULL, maxsize=BUS_QUEUE_MAX
            )

    def pump(self) -> int:
        """Drain the bus subscription without waiting, as one batch per symbol; the items."""
        taken: list[object] = []
        while self._sub is not None and len(taken) < BUS_QUEUE_MAX:
            try:
                taken.append(self._sub.get_nowait())
            except asyncio.QueueEmpty:
                break
        if taken:
            self.offer(taken)
        return len(taken)

    def start(self) -> None:
        self.open()
        if self._task is None:
            self._task = spawn(self._run(), name="ws-trades-topic")
            self._task.add_done_callback(_stopped)

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})
        sub, self._sub = self._sub, None
        if sub is not None:
            self._bus.unsubscribe(sub)

    async def _run(self) -> None:
        while (sub := self._sub) is not None:
            try:
                with contextlib.suppress(TimeoutError):
                    async with asyncio.timeout(self._window_s):
                        first = await sub.get()
                        self.offer([first])
                self.pump()
                self.tick()
            except Exception as exc:  # never let one bad turn stop every trades `d`
                _log().error("trades_topic_turn_failed", error=type(exc).__name__)
                self._resync()
                await self._sleep(self._window_s)  # a fault that persists: one resync per window


def _queue(opt: _OptionState, items: Iterable[TapeItem]) -> None:
    """Append `items` to the bounded `pending`; an item it sheds counts its prints in `overflow`."""
    for item in items:
        if len(opt.pending) == opt.pending.maxlen:
            opt.overflow += opt.pending[0].cluster_size
        opt.pending.append(item)


def _leased(sub: Subscription, options: Options) -> bool:
    lease = sub.trades_lease
    return lease is not None and lease.options == options


def _waited(sub: Subscription, symbol: str) -> bool:
    lease = sub.trades_lease
    return lease is not None and lease.symbol == symbol and sub.snapshot_pending


def _live_trades(sub: Subscription) -> bool:
    return sub.replay_session_id is None and sub.ch.startswith(f"{FAMILY}.")


def _stopped(task: asyncio.Task[None]) -> None:
    """A loop that ends other than by `stop` says so: from then on no trades `d` goes out."""
    if not task.cancelled() and (exc := task.exception()) is not None:
        _log().error("trades_topic_stopped", error=type(exc).__name__)


__all__ = [
    "BUS_QUEUE_MAX",
    "PENDING_MAX",
    "SNAPSHOT_ITEMS",
    "WINDOW_S",
    "TradeTape",
    "TradesLease",
    "TradesTopic",
    "note_option_refusal",
    "options_of",
]
