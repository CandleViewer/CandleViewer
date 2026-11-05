"""Composition-root wiring (not a module): the rules' metric producers (E35-T15, #5745).

Only the composition root sees the bars, the book, the bus and the rules together (C-3.1); each
producer here reads one shipped market path and writes through its own `PushSink` (the bridge,
`rules/producers.py`), never the source. Market-scope metrics only (#1204 Part B's binding rule).

* Bars: `BarFieldProducer` is a `BarSink` on the bars emit path (`wire_bars(extra_sinks=)`, after
  the indicator engine, before the writer). Its `emit` never awaits (the atomicity rule in the
  `bars_wiring` docstring): for each closed, non-synthetic time bar of a demanded
  ``(symbol, timeframe)`` it pushes the bar's own `Decimal` fields, then submits one
  ``on_bar_close`` tick per symbol and timeframe (push, then tick: E2). An amended close re-pushes
  and submits nothing. A close older than one interval, or than `LIVE_CLOSE_GRACE_MS` for an
  interval past a minute, is history, a restored series' catch-up replaying its tape through the
  same emit path (`bars/builder_set.py` "Emit"; `BarEmission` carries no replay flag): it pushes
  and ticks nothing, so a rule never fires on an old close. A close at or before the newest one
  ticked for its series never ticks again, nor one before it pushes, so a rule never fires twice
  for one bar. It keeps one bar-series lease (consumer ``rules``, `user=None`: a system
  consumer, `bars/leases.py`) per demanded ``(symbol, time spec)``, dropped with the demand; a
  refused lease is counted, logged once per key, leaves the metric ``warmup`` and is tried again
  after `LEASE_RETRY_S`. A registration still running `LEASE_TIMEOUT_S` after it took its slot
  (one of `LEASE_CONCURRENCY`; the wait for one is not counted) is never cancelled: it is
  counted ``lease_timeout``, never started again while it runs, and adopted when it ends;
  should it then fail, its key waits a backoff doubling per timeout, up to
  `LEASE_BACKOFF_MAX_S`. Only the chart's own intervals (`bars/spec.TIME_INTERVALS`, up to 1 d) are
  leased, at most `MAX_RULE_LEASES` in all, handed out round-robin across rules and at most
  `MAX_RULE_LEASES_PER_RULE` a rule, so no rule author can use up the bar service's shared caps
  that chart users draw on, nor one rule the rules' share.
* Quotes and the ticker: `QuoteProducer` (``{env}.md.*.quote``) and `TickerProducer`
  (``{env}.md.*.ticker``) are wildcard bus consumers built as `ingestion/ticker_topic.py` is:
  `INVALIDATE_ON_FULL` on a bounded queue (the bus's `CONFLATE_LATEST` keeps one event across
  every symbol of a wildcard subscription), one tracked task, a keyed dict of each symbol's
  latest event capped at `MAX_SYMBOLS`; an invalidation marker clears it, so each symbol's next
  event re-pushes. They push at most once per symbol per window (100 ms and 250 ms), then tick
  ``on_book_update`` / ``on_price_update`` for the symbol. Only the process's own live ``env`` is
  subscribed and only ``source == "live"`` events are taken: a replay session never feeds the
  source (C-2.11).
* The book: `BookDepthProducer` reads the demanded symbols' books every 100 ms (never per delta,
  C-2.20) through `BookStream.view` at the deepest demanded ``n`` the book holds; a want deeper
  than the book, or a book not LIVE, pushes nothing and stays ``warmup`` without holding back
  the shallower wants; `book_staleness_ms` needs no view. It holds no book tier.
  `BookTicks` keeps ``on_book_update`` to one tick per symbol per window across both producers.
* Lost feeds: `FeedHealthWatch` maps a lost ``{env}.health.feed`` event to its symbol and feed
  (the adapter's `StreamForTopic`) and marks that feed's pushed refs ``source_degraded``.

`build_bridge` composes them; the composition root calls it only with `rules_evaluator_enabled`
on, so with the flag off nothing here is built, spliced or subscribed (C-4.13).
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import itertools
import math
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from decimal import Decimal
from functools import lru_cache
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Protocol

import structlog

from candleviewer.bars.emit import BarEmission
from candleviewer.bars.limits import CAP_GLOBAL
from candleviewer.bars.models import Bar, BarSpec
from candleviewer.bars.spec import TIME_INTERVALS
from candleviewer.bars.time_builder import MAX_INTERVAL_MS, MIN_INTERVAL_MS
from candleviewer.book.models import BestQuoteEvent
from candleviewer.book.ws_topic import WINDOW_S as BOOK_WINDOWS_S
from candleviewer.bus import Bus, QueuePolicy, StreamInvalidated, Subscription, TopicPattern
from candleviewer.bus.models import LIVE_ENVS, WILDCARD
from candleviewer.domain.events import MarketEvent
from candleviewer.exchange.base.models import BookLevel, TickerEvent
from candleviewer.exchange.base.ports import StreamForTopic
from candleviewer.ingestion.ticker_topic import BUS_QUEUE_MAX, MAX_SYMBOLS
from candleviewer.ingestion.ticker_topic import WINDOW_S as TICKER_WINDOW_S
from candleviewer.ingestion.watchdog import FeedHealthEvent
from candleviewer.observability import spawn
from candleviewer.observability.metrics import Metrics
from candleviewer.orderbook_wiring import BookView
from candleviewer.rules.evaluator.snapshot import Value
from candleviewer.rules.producers import (
    ANY_SYMBOL,
    LOST_AFTER_S,
    MetricProducer,
    ProducerBridge,
    PushSink,
    Want,
)
from candleviewer.rules.vocabulary import default_registry

if TYPE_CHECKING:  # typing only: the manager reaches the statechart (C-2.20 hot path)
    from candleviewer.rules.manager import EvaluableRule

#: The IR's timeframe grammar (`rules/validator.py` ``_TF``), bounded so the product stays small.
_TIMEFRAME: Final = re.compile(r"^([1-9][0-9]{0,6})([smhdw])$")
_UNIT_MS: Final = {"s": 1_000, "m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
#: The bar metrics bound from the bar (24 §7.2.2): `delta` and `bar_volume` until E13-S08.
BAR_METRICS: Final = ("delta", "bar_volume", "min_delta", "max_delta", "buy_sell_ratio")
#: The intervals a lease may take: the chart's wire table, within what the time builder builds.
LEASABLE_MS: Final = frozenset(
    ms for ms in TIME_INTERVALS.values() if MIN_INTERVAL_MS <= ms <= MAX_INTERVAL_MS
)
#: The lease consumer: one per `(symbol, spec_hash)`, so a second `register` is idempotent.
LEASE_CONSUMER: Final = "rules"
#: Leases the rules hold in all (`bars/leases.py` caps 32 a symbol, 512 a process): the rest
#: is the chart users'. Past it a lease is refused, counted, and its metric stays ``warmup``.
MAX_RULE_LEASES: Final = 64
#: Leases one rule may hold (`Want.owners`), so four rules at least share the pool.
MAX_RULE_LEASES_PER_RULE: Final = 16
#: The lease keeper's period, and the bound on one registration (a cold build replays the tape);
#: registrations run concurrently (`LEASE_CONCURRENCY` at once), so one slow build never delays
#: the others.
LEASE_S: Final = 1.0
LEASE_TIMEOUT_S: Final = 30.0
#: A refused lease is tried again after this long (a cap freed, a stopping service back).
LEASE_RETRY_S: Final = 60.0
#: A key whose registration outran `LEASE_TIMEOUT_S` waits `LEASE_RETRY_S` doubled per timeout
#: in a row, at most this long, before it is registered again.
LEASE_BACKOFF_MAX_S: Final = 960.0
#: Registrations in flight at once (each may cold-build a series off the tape).
LEASE_CONCURRENCY: Final = 8
#: How late a close may be emitted and still be live: one interval, at most this. A longer
#: interval's close replayed minutes later by a catch-up is history, never a fire.
LIVE_CLOSE_GRACE_MS: Final = 60_000
#: Series whose newest ticked close is kept (the bar service builds no more, `bars/limits.py`).
MAX_TICKED_SERIES: Final = CAP_GLOBAL
#: 24 §11.6 ``on_book_update`` at 10 Hz: the book publisher's window at depth 200.
BOOK_WINDOW_S: Final = BOOK_WINDOWS_S[200]
BOOK_CADENCE_MS: Final = round(BOOK_WINDOW_S * 1000)
#: The ticker family's window (23 §6.1), the `price` cadence.
TICKER_CADENCE_MS: Final = round(TICKER_WINDOW_S * 1000)
QUOTE_METRICS: Final = ("spread_ticks", "spread_bps", "mid", "microprice")
DEPTH_METRICS: Final = ("dom_imbalance_ratio", "book_pressure", "book_staleness_ms")
#: The registry's default ``n`` (`rules/vocabulary/metrics.py`); ``n`` past `MAX_BOOK_N` (the
#: deepest tier) or not a positive integer (an int, or up to 3 ASCII digits) is never served: the
#: want stays ``warmup``, counted as a ``params`` refusal.
DEPTH_N_DEFAULT: Final = {"dom_imbalance_ratio": 10, "book_pressure": 20}
MAX_BOOK_N: Final = 500
#: `price`'s ``source`` parameter (registry default ``last``) -> the `TickerEvent` field.
PRICE_SOURCES: Final = {"last": "last_price", "mark": "mark_price", "index": "index_price"}


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@lru_cache(maxsize=256)
def timeframe_spec(timeframe: str | None) -> BarSpec | None:
    """The time `BarSpec` an IR timeframe (``1m``, ``4h``) names, with the defaults `from_wire`
    builds, so a lease joins the chart's series (one `spec_hash`); None for a string it cannot map
    or an interval outside the chart's table (`LEASABLE_MS`): never leased, the metric stays
    ``warmup``. Pure."""
    if timeframe is None or (match := _TIMEFRAME.fullmatch(timeframe)) is None:
        return None
    ms = int(match[1]) * _UNIT_MS[match[2]]
    if ms not in LEASABLE_MS:
        return None
    return BarSpec(kind="time", interval_ms=ms)


class LeaseHolder(Protocol):
    """The slice of `BarBuilderSet` the lease keeper needs."""

    async def register(
        self, spec: BarSpec, symbol: str, consumer: str, user: str | None = None
    ) -> None: ...

    def release(self, spec_hash: str, symbol: str, consumer: str) -> None: ...


class BarFieldProducer:
    """Bar fields of closed time bars into the rules' source; a `MetricProducer` and a `BarSink`.

    Built before `wire_bars` (it is one of its `extra_sinks`) and attached to the bridge later;
    until attached `emit` does nothing. `builders` returns the set to lease from (None: not
    composed), `qty_step` the catalogue's step of a symbol (None: not listed, so
    `buy_sell_ratio` is not pushed), `now_us` the bars' own UTC wall clock (what tells a live
    close from history), `clock` the monotonic one of the lease retries."""

    def __init__(
        self,
        builders: Callable[[], LeaseHolder | None],
        qty_step: Callable[[str], Decimal | None],
        *,
        now_us: Callable[[], int] = lambda: time.time_ns() // 1000,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.name = "bar_fields"
        self.metrics = frozenset(BAR_METRICS)
        self.feeds = frozenset({"trades"})
        self._builders, self._qty_step, self._sleep = builders, qty_step, sleep
        self._now_us, self._clock = now_us, clock
        self._sink: PushSink | None = None
        self._task: asyncio.Task[None] | None = None
        self._by_spec: dict[str, tuple[str, ...]] = {}
        self._by_spec_of: tuple[PushSink, int] | None = None
        self._held: dict[tuple[str, str], BarSpec] = {}
        self._refused: dict[tuple[str, str], float] = {}  # key -> when it was refused
        self._refused_at = -1
        self._leasing = asyncio.Semaphore(LEASE_CONCURRENCY)
        #: Registrations running (each its own task, never cancelled by the keeper's bound).
        self._pending: dict[tuple[str, str], asyncio.Task[bool]] = {}
        self._late: set[tuple[str, str]] = set()  # pending past `LEASE_TIMEOUT_S`, counted
        #: key -> when its registration took a `_leasing` slot (loop time): its bound starts there.
        self._began: dict[tuple[str, str], float] = {}
        self._timeouts: dict[tuple[str, str], int] = {}  # key -> timeouts in a row (backoff)
        self._logged: set[tuple[str, str]] = set()  # keys whose refusal is logged
        #: (symbol, spec_hash) -> the newest close ticked (us), least recently ticked first.
        self._ticked: dict[tuple[str, str], int] = {}

    # -- the bridge's side ---------------------------------------------------------------------
    def attach(self, sink: PushSink) -> None:
        self._sink = sink
        if self._task is None:
            self._task = spawn(self._keeping(), name="rule-producers-bar-leases")

    async def detach(self) -> None:
        """Stop pushing, stop the keeper and every registration in flight (a cancelled one gives
        its lease back), then release every lease held."""
        self._sink = None
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})
        pending, self._pending = self._pending, {}
        for registering in pending.values():
            registering.cancel()
        if pending:
            await asyncio.wait(pending.values())
        builders = self._builders()
        held, self._held = self._held, {}
        self._refused.clear()
        self._ticked.clear()
        self._late.clear()
        self._began.clear()
        self._timeouts.clear()
        self._logged.clear()
        if builders is not None:
            for key in held:
                self._release(builders, key)

    # -- the bars emit path --------------------------------------------------------------------
    async def emit(self, emission: BarEmission) -> None:
        """Synchronous body: never awaits, so the emit path's atomicity holds (`bars_wiring`)."""
        sink = self._sink
        if sink is not None and emission.spec.kind == "time":
            sink.guard(self._take, sink, emission)

    def _take(self, sink: PushSink, emission: BarEmission) -> None:
        timeframes = self._timeframes(sink).get(emission.spec.spec_hash)
        if not timeframes:
            return
        cadence_ms, now_ms = emission.spec.interval_ms or 0, self._now_us() // 1000
        grace_ms, spec_hash = min(cadence_ms, LIVE_CLOSE_GRACE_MS), emission.spec.spec_hash
        ticks: dict[tuple[str, str], None] = {}  # ordered, one tick per (symbol, timeframe)
        for update in emission.updates:
            bar = update.bar
            if update.kind != "close" or not bar.closed or bar.synthetic:
                continue
            ts_ms = bar.close_time // 1000
            if now_ms - ts_ms >= grace_ms:
                continue  # history (a catch-up replay): never pushed or ticked as live
            series = (bar.symbol, spec_hash)
            newest = self._ticked.get(series, -1)
            if bar.close_time < newest:
                continue  # an older bar than one ticked: never written over the newer
            values, fresh = self._values(bar), not update.amended and bar.close_time > newest
            for timeframe in timeframes:
                hit = False
                for metric, value in values:
                    for want in sink.wanted(metric, bar.symbol, timeframe):
                        hit = sink.push(want, bar.symbol, value, ts_ms, cadence_ms) or hit
                if hit and fresh:
                    ticks[(bar.symbol, timeframe)] = None
                    self._newest(series, bar.close_time)
        for symbol, timeframe in ticks:
            sink.tick("on_bar_close", symbol, timeframe)

    def _newest(self, series: tuple[str, str], close_us: int) -> None:
        """Record `series`' newest ticked close, least recently ticked first; past
        `MAX_TICKED_SERIES` the least recent goes (its next repeat could tick once more)."""
        self._ticked.pop(series, None)
        if len(self._ticked) >= MAX_TICKED_SERIES:
            del self._ticked[next(iter(self._ticked))]
        self._ticked[series] = close_us

    def _values(self, bar: Bar) -> tuple[tuple[str, Value], ...]:
        """The bar's own fields: `delta` and `bar_volume` are what the kernels pass through
        (`orderflow/indicators/kernels/volume.py`), not a second formula."""
        step = self._qty_step(bar.symbol)
        ratio = None if step is None or step <= 0 else bar.buy_volume / max(bar.sell_volume, step)
        return (
            ("delta", bar.delta), ("bar_volume", bar.volume), ("min_delta", bar.min_delta),
            ("max_delta", bar.max_delta), ("buy_sell_ratio", ratio),
        )  # fmt: skip

    def _timeframes(self, sink: PushSink) -> dict[str, tuple[str, ...]]:
        """`spec_hash` -> the demanded timeframes mapping to it, rebuilt on a demand change."""
        if self._by_spec_of != (sink, sink.demand_version):
            by_spec: dict[str, dict[str, None]] = {}
            for want in sink.demanded():
                spec = timeframe_spec(want.timeframe)
                if spec is not None and want.timeframe is not None:
                    by_spec.setdefault(spec.spec_hash, {})[want.timeframe] = None
            self._by_spec = {h: tuple(tfs) for h, tfs in by_spec.items()}
            self._by_spec_of = (sink, sink.demand_version)
            self._ticked = {k: t for k, t in self._ticked.items() if k[1] in self._by_spec}
        return self._by_spec

    # -- the leases ----------------------------------------------------------------------------
    def lease_targets(self, sink: PushSink) -> dict[tuple[str, str], BarSpec]:
        """``(symbol, spec_hash)`` -> spec to lease, in fair order: round-robin across the rules
        reading each (`Want.owners`), every rule's first before any rule's second, at most
        `MAX_RULE_LEASES_PER_RULE` a rule and `MAX_RULE_LEASES` in all. A rule that lists no
        symbol leases nothing (it reads the series others hold)."""
        return self._plan(sink)[0]

    def _plan(self, sink: PushSink) -> tuple[dict[tuple[str, str], BarSpec], int]:
        """`lease_targets`, and how many demanded targets the budgets leave out."""
        per_rule: dict[str, dict[tuple[str, str], BarSpec]] = {}
        for want in sink.demanded():
            if (spec := timeframe_spec(want.timeframe)) is None:
                continue
            for symbol, owners in want.owners.items():
                if symbol is not None and symbol != ANY_SYMBOL:
                    for owner in owners:
                        per_rule.setdefault(owner, {})[(symbol, spec.spec_hash)] = spec
        queues = [sorted(q.items())[:MAX_RULE_LEASES_PER_RULE] for _, q in sorted(per_rule.items())]
        targets: dict[tuple[str, str], BarSpec] = {}
        for item in itertools.chain.from_iterable(itertools.zip_longest(*queues)):
            if item is not None and len(targets) < MAX_RULE_LEASES:
                targets.setdefault(*item)
        return targets, len({k for q in per_rule.values() for k in q}) - len(targets)

    async def sync(self) -> None:
        """One keeper pass: release the leases no longer targeted, then take the new ones
        concurrently, each awaited at most `LEASE_TIMEOUT_S`. A refusal (a cap, a budget, an
        unbuildable spec, a stopping service) is counted and tried again after `LEASE_RETRY_S`,
        or at once when the demand changes; a key still registering is never started again, and
        one that timed out waits its backoff (`retry_s`) whatever the demand does."""
        sink, builders = self._sink, self._builders()
        if sink is None or builders is None:
            return
        targets, dropped = self._plan(sink)
        if self._refused_at != sink.demand_version:
            self._refused = {k: t for k, t in self._refused.items() if k in self._timeouts}
            self._refused_at = sink.demand_version
            for _ in range(len(self.unleasable(sink)) + dropped):
                sink.lease_refused()
        for key in [k for k in self._held if k not in targets]:
            del self._held[key]
            self._release(builders, key)
        self._logged.intersection_update(targets)
        self._timeouts = {k: n for k, n in self._timeouts.items() if k in targets}
        now, room = self._clock(), MAX_RULE_LEASES - len(self._pending)
        new = [
            (key, spec) for key, spec in targets.items()
            if key not in self._held and key not in self._pending
            and now - self._refused.get(key, -math.inf) >= self.retry_s(key)
        ][: max(room, 0)]  # fmt: skip
        if new:  # each registration its own task: a cancelled pass leaves them running
            await asyncio.gather(*(self._lease(sink, builders, key, spec) for key, spec in new))

    def retry_s(self, key: tuple[str, str]) -> float:
        """How long after a refusal `key` is registered again: `LEASE_RETRY_S`, doubled per
        timeout in a row, at most `LEASE_BACKOFF_MAX_S`."""
        return min(LEASE_RETRY_S * (1 << min(self._timeouts.get(key, 0), 16)), LEASE_BACKOFF_MAX_S)

    async def _lease(
        self, sink: PushSink, builders: LeaseHolder, key: tuple[str, str], spec: BarSpec
    ) -> None:
        if self._sink is not sink:  # detached meanwhile: start no build
            return
        task = spawn(self._register(sink, builders, key, spec), name="rule-producers-bar-lease")
        self._pending[key] = task
        task.add_done_callback(functools.partial(self._registered, sink, builders, key, spec))
        done, _ = await asyncio.wait({task}, timeout=LEASE_TIMEOUT_S)
        began = self._began.get(key)
        if done or began is None or asyncio.get_running_loop().time() - began < LEASE_TIMEOUT_S:
            return  # ended (`_registered` took it), or queued or started late: its timer counts
        self._overdue(sink, key, task)

    def _overdue(
        self, sink: PushSink, key: tuple[str, str], task: asyncio.Task[Any] | None
    ) -> None:
        """`key`'s registration ran `LEASE_TIMEOUT_S` past taking its slot: counted once, never
        cancelled, adopted when it ends."""
        if self._pending.get(key) is not task or self._sink is not sink or key in self._late:
            return
        self._late.add(key)
        self._timeouts[key] = self._timeouts.get(key, 0) + 1
        sink.lease_timed_out()
        self._refusal_logged(key, "TimeoutError")

    async def _register(
        self, sink: PushSink, builders: LeaseHolder, key: tuple[str, str], spec: BarSpec
    ) -> bool:
        """Register `key`'s lease; False (nothing to give back) if detached before it began."""
        async with self._leasing:  # `LEASE_CONCURRENCY` registering at once
            if self._sink is not sink:
                return False
            loop = asyncio.get_running_loop()
            self._began[key] = loop.time()  # the bound starts with the slot, not in the queue
            timer = loop.call_later(
                LEASE_TIMEOUT_S, self._overdue, sink, key, asyncio.current_task()
            )
            try:
                await builders.register(spec, key[0], LEASE_CONSUMER, None)
            finally:
                timer.cancel()
            return True

    def _registered(
        self,
        sink: PushSink,
        builders: LeaseHolder,
        key: tuple[str, str],
        spec: BarSpec,
        task: asyncio.Task[bool],
    ) -> None:
        """A registration ended: hold its lease, give it back (detached meanwhile), or count
        the refusal (not again for one already counted as timed out)."""
        if self._pending.get(key) is task:
            del self._pending[key]
            self._began.pop(key, None)
        late = key in self._late
        self._late.discard(key)
        if task.cancelled():
            return  # stopped by `detach`: it gave its lease back
        if (exc := task.exception()) is not None:  # the metric stays warmup, tried again later
            self._refused[key] = self._clock()
            if not late:
                sink.lease_refused()
            self._refusal_logged(key, type(exc).__name__)
            return
        if not task.result():
            return  # detached before it began: nothing registered
        if self._sink is not sink:  # detached meanwhile: give it back at once
            self._release(builders, key)
            return
        self._held[key] = spec
        self._refused.pop(key, None)
        self._timeouts.pop(key, None)
        self._logged.discard(key)

    def _refusal_logged(self, key: tuple[str, str], error: str) -> None:
        """Log a refused or timed-out lease once per key until it is held or no longer wanted."""
        if key not in self._logged:
            self._logged.add(key)
            _log().warning("rules.bar_lease_refused", error=error)

    @staticmethod
    def _release(builders: LeaseHolder, key: tuple[str, str]) -> None:
        """One release; one that raises (a lease the set does not hold) never strands the rest."""
        try:
            builders.release(key[1], key[0], LEASE_CONSUMER)
        except Exception as exc:
            _log().warning("rules.bar_lease_release_failed", error=type(exc).__name__)

    @staticmethod
    def unleasable(sink: PushSink) -> frozenset[str]:
        """The demanded timeframes no lease can take (outside `LEASABLE_MS`)."""
        return frozenset(
            w.timeframe for w in sink.demanded()
            if w.timeframe is not None and timeframe_spec(w.timeframe) is None
        )  # fmt: skip

    @property
    def held(self) -> frozenset[tuple[str, str]]:
        return frozenset(self._held)

    async def _keeping(self) -> None:
        while True:  # sleep first: at attach the bridge has not read the demand yet
            await self._sleep(LEASE_S)
            sink = self._sink
            try:
                await self.sync()
            except Exception as exc:  # the keeper outlives one bad pass
                if sink is not None:
                    sink.failed(exc)


# --- quotes, the ticker, the book -------------------------------------------------------------


def microprice(bid: Decimal, bid_qty: Decimal, ask: Decimal, ask_qty: Decimal) -> Decimal | None:
    """``(bid x ask_qty + ask x bid_qty) / (bid_qty + ask_qty)``; None (not pushed) for an empty
    top, never a defaulted 0 (E3). Pure."""
    total = bid_qty + ask_qty
    return None if total <= 0 else (bid * ask_qty + ask * bid_qty) / total


def depth_sums(levels: Iterable[BookLevel], n: int) -> Decimal:
    total = Decimal(0)
    for i, level in enumerate(levels):
        if i >= n:
            break
        total += level.qty
    return total


def depth_n(want: Want) -> int | None:
    """The book depth `want` reads: its ``n`` as authored (a key is the params as written, so
    nothing is canonicalised), else the registry default; 1 for `book_staleness_ms`. Strict, and
    never raises: a string is read only as at most 3 ASCII digits (no superscript, Arabic-Indic or
    full-width digit, which `str.isdigit` accepts and `int` may not)."""
    default = DEPTH_N_DEFAULT.get(want.metric)
    if default is None:
        return 1
    n = want.params.get("n", default)
    if isinstance(n, str):
        n = int(n) if len(n) <= 3 and n.isascii() and n.isdecimal() else None
    if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_BOOK_N:
        return None
    return n


class BookTicks:
    """One ``on_book_update`` tick per symbol per book window, whichever producer pushed first
    (quotes or depth): windows are clock buckets, so a late timer never doubles a window. One
    entry per symbol, cleared whole at `MAX_SYMBOLS` (a cleared entry costs one extra tick)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._at: dict[str, int] = {}

    def allow(self, symbol: str) -> bool:
        bucket = round(self._clock() * 1000) // BOOK_CADENCE_MS  # whole ms: no float drift
        last = self._at.get(symbol)
        if last == bucket:
            return False
        if last is None and len(self._at) >= MAX_SYMBOLS:
            self._at.clear()
        self._at[symbol] = bucket
        return True


class _KeyedConsumer[E: MarketEvent]:
    """A wildcard ``{env}.md.*.{detail}`` consumer pushing each symbol's latest event at most once
    per window (`ingestion/ticker_topic.py`'s pattern). Subclasses name the producer and `_push`
    one event, returning whether anything was written (then the symbol's tick is submitted)."""

    name: str
    metrics: frozenset[str]
    feeds: frozenset[str]

    def __init__(
        self,
        bus: Bus,
        env: str,
        detail: str,
        kind: type[E],
        window_s: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_symbols: int = MAX_SYMBOLS,
    ) -> None:
        if env not in LIVE_ENVS:  # a replay session's env never feeds the live source (C-2.11)
            raise ValueError("a metric producer subscribes a live env only")
        self._bus, self._env, self._detail, self._kind = bus, env, detail, kind
        self._window_s, self._clock, self._sleep, self._max = window_s, clock, sleep, max_symbols
        self._latest: dict[str, E] = {}
        self._seen: dict[str, float] = {}  # symbol -> when its latest event was received
        self._changed: set[str] = set()
        self._last_flush = -math.inf
        self._full = False
        self._sink: PushSink | None = None
        self._sub: Subscription | None = None
        self._task: asyncio.Task[None] | None = None

    # -- the bridge's side ---------------------------------------------------------------------
    def attach(self, sink: PushSink) -> None:
        self._sink = sink
        self.start()

    async def detach(self) -> None:
        self._sink = None
        await self.stop()
        self._latest.clear()
        self._seen.clear()
        self._changed.clear()

    def holds(self, symbol: str) -> bool:
        """Attached, subscribed, and `symbol`'s latest event received less than `LOST_AFTER_S`
        ago on this consumer's monotonic clock: a quiet symbol, not a lost one
        (`ProducerBridge.watch`). Fail closed: a feed that stops with no health event (a book
        dropped, a ticker unsubscribed) is marked once the bound passes, held event or not. A
        feed that publishes only on a change says more (`QuoteProducer.holds`: the book's
        frames)."""
        seen = self._seen.get(symbol)
        return (
            self._sink is not None and self._sub is not None and seen is not None
            and self._clock() - seen < LOST_AFTER_S
        )  # fmt: skip

    # -- the bus -------------------------------------------------------------------------------
    def offer(self, item: object) -> None:
        """One item from the bus: a symbol's new event, or the bus's overflow marker."""
        if isinstance(item, StreamInvalidated):
            _log().warning("rules.producer_stream_invalidated", producer=self.name)
            self._latest.clear()  # the next event of each symbol re-pushes
            self._seen.clear()
            self._changed.clear()
            self._full = False
        elif isinstance(item, self._kind) and item.source == "live":
            self._take(item)

    def _take(self, event: E) -> None:
        symbol = event.symbol
        held = self._latest.get(symbol)
        if held is None and len(self._latest) >= self._max:
            if not self._full:
                self._full = True
                _log().warning("rules.producer_symbols_full", producer=self.name)
            return
        if held is not None and event.ts_event < held.ts_event:
            return  # never a symbol back in time
        self._latest[symbol] = event
        self._seen[symbol] = self._clock()
        self._changed.add(symbol)

    def pump(self) -> int:
        """Drain the bus subscription without waiting; the items taken."""
        taken = 0
        while self._sub is not None and taken < BUS_QUEUE_MAX:
            try:
                item = self._sub.get_nowait()
            except asyncio.QueueEmpty:
                break
            self.offer(item)
            taken += 1
        return taken

    def flush(self) -> int:
        """Once the window allows, push each changed symbol's latest event, then tick it (push,
        then tick: E2); the symbols ticked."""
        sink = self._sink
        if sink is None or not self._changed or self._clock() < self._last_flush + self._window_s:
            return 0
        self._last_flush = self._clock()
        changed, self._changed = self._changed, set()
        ticked = 0
        with sink.window():
            for symbol in sorted(changed):
                event = self._latest.get(symbol)
                if event is None or not sink.guard(self._push, sink, event):
                    continue
                if self._tick(symbol):
                    sink.tick(self._trigger, symbol)
                    ticked += 1
        return ticked

    _trigger: str

    def _push(self, sink: PushSink, event: E) -> bool:
        raise NotImplementedError

    def _tick(self, symbol: str) -> bool:
        return True

    # -- lifecycle -----------------------------------------------------------------------------
    def open(self) -> None:
        if self._sub is None:
            pattern = TopicPattern(env=self._env, domain="md", symbol=WILDCARD, detail=self._detail)
            self._sub = self._bus.subscribe(
                f"rule-producers-{self._detail}", pattern, QueuePolicy.INVALIDATE_ON_FULL,
                maxsize=BUS_QUEUE_MAX,
            )  # fmt: skip

    def start(self) -> None:
        self.open()
        if self._task is None:
            self._task = spawn(self._run(), name=f"rule-producers-{self._detail}")

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
            wait = self._window_s
            if self._changed and self._sink is not None:  # the window's end, or the next event
                wait = max(0.0, self._last_flush + self._window_s - self._clock())
            try:
                if wait > 0:
                    with contextlib.suppress(TimeoutError):
                        async with asyncio.timeout(wait):
                            self.offer(await sub.get())
                else:  # a late turn still yields: it never starves the loop
                    await asyncio.sleep(0)
                self.pump()
                self.flush()
            except Exception as exc:  # one bad turn never stops the consumer
                if (sink := self._sink) is not None:
                    sink.failed(exc)
                await self._sleep(self._window_s)


class QuoteProducer(_KeyedConsumer[BestQuoteEvent]):
    """`spread_ticks`, `spread_bps`, `mid` (as the quote carries them) and `microprice` from the
    best quote, at most once per symbol per 100 ms, cadence 100 ms, then ``on_book_update``.

    The book publishes a quote only when the top changes, so a quiet top is no lost feed: `books`
    (the stream the quotes come from; None: not composed) says whether frames still apply."""

    _trigger = "on_book_update"

    def __init__(
        self,
        bus: Bus,
        env: str,
        ticks: BookTicks,
        *,
        books: Callable[[], BookReader | None] | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(bus, env, "quote", BestQuoteEvent, BOOK_WINDOW_S, **kw)
        self.name = "quote"
        self.metrics = frozenset(QUOTE_METRICS)
        self.feeds = frozenset({"book"})
        self._ticks, self._books = ticks, books

    def holds(self, symbol: str) -> bool:
        """`_KeyedConsumer.holds`, or, attached and subscribed, `symbol`'s book applied a frame
        less than `LOST_AFTER_S` ago (`BookReader.applied_age_ms`): its top is quiet, the feed is
        live. A book with no frame for the bound, or none at all, is marked (fail closed)."""
        if super().holds(symbol):
            return True
        books = None if self._books is None else self._books()
        if self._sink is None or self._sub is None or books is None:
            return False
        age = books.applied_age_ms(symbol)
        return age is not None and age < LOST_AFTER_S * 1000

    def _push(self, sink: PushSink, event: BestQuoteEvent) -> bool:
        symbol, ts_ms = event.symbol, event.ts_event // 1000
        values: tuple[tuple[str, Value], ...] = (
            ("spread_ticks", Decimal(event.spread_ticks)), ("spread_bps", event.spread_bps),
            ("mid", event.mid),
            ("microprice", microprice(event.bid, event.bid_qty, event.ask, event.ask_qty)),
        )  # fmt: skip
        hit = False
        for metric, value in values:
            if value is None:
                continue
            for want in sink.wanted(metric, symbol):
                hit = sink.push(want, symbol, value, ts_ms, BOOK_CADENCE_MS) or hit
        return hit

    def _tick(self, symbol: str) -> bool:
        return self._ticks.allow(symbol)


class TickerProducer(_KeyedConsumer[TickerEvent]):
    """`price` by its ``source`` parameter (last, mark, index) from the ticker, at most once per
    symbol per 250 ms, cadence 250 ms, then ``on_price_update``. A None field is not pushed."""

    _trigger = "on_price_update"

    def __init__(self, bus: Bus, env: str, **kw: Any) -> None:
        super().__init__(bus, env, "ticker", TickerEvent, TICKER_WINDOW_S, **kw)
        self.name = "ticker"
        self.metrics = frozenset({"price"})
        self.feeds = frozenset({"ticker"})

    def _push(self, sink: PushSink, event: TickerEvent) -> bool:
        symbol, ts_ms = event.symbol, event.ts_event // 1000
        hit = False
        for want in sink.wanted("price", symbol):
            source = want.params.get("source", "last")
            field = PRICE_SOURCES.get(source) if isinstance(source, str) else None
            value = None if field is None else getattr(event, field)
            if value is not None:
                hit = sink.push(want, symbol, value, ts_ms, TICKER_CADENCE_MS) or hit
        return hit


class _Stamped(Protocol):
    @property
    def ts_event(self) -> int: ...


class _Engine(Protocol):
    @property
    def last_applied(self) -> _Stamped | None: ...


class BookReader(Protocol):
    """The slice of `BookStream` (``ctx.ingestion.books``) the depth producer reads."""

    def view(self, symbol: str, depth: int) -> BookView | None: ...

    def applied_age_ms(self, symbol: str) -> int | None: ...

    def engine(self, symbol: str) -> _Engine | None: ...


class BookDepthProducer:
    """`dom_imbalance_ratio` (bid qty over ask qty, top ``n``), `book_pressure` (``(bids - asks)
    / (bids + asks)``, top ``n``) and `book_staleness_ms` of each demanded symbol, every 100 ms.

    Values are as of the last applied frame (its exchange time); `book_staleness_ms` is its age
    on the stream's monotonic clock, stamped at that frame's time plus the age (a deviation from
    the exchange-time stamp: stamped at the frame's time, the staleness value would itself read
    stale exactly when it matters), pushed whenever a frame was applied, at any depth, and on
    through a desync (the book keeps no frame then; the last one seen is kept per symbol), so
    the age grows while the book resyncs. A stale book, or a want deeper than the book, pushes no
    depth value; a zero denominator pushes nothing. A rule that lists no symbol gets no depth
    value (no book tier is held for it: it stays ``warmup``). At most one pass per book window
    (a clock bucket), however often `poll` runs."""

    def __init__(
        self,
        books: Callable[[], BookReader | None],
        ticks: BookTicks,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.name = "book_depth"
        self.metrics = frozenset(DEPTH_METRICS)
        self.feeds = frozenset({"book"})
        self._books, self._ticks, self._clock, self._sleep = books, ticks, clock, sleep
        self._bucket = -1  # the book window `poll` last ran in
        self._last_ts: dict[str, int] = {}  # symbol -> the last applied frame's time (ms)
        self._sink: PushSink | None = None
        self._task: asyncio.Task[None] | None = None
        self._by_symbol: dict[str, tuple[tuple[Want, int], ...]] = {}
        self._by_symbol_of: tuple[PushSink, int] | None = None

    def attach(self, sink: PushSink) -> None:
        self._sink = sink
        if self._task is None:
            self._task = spawn(self._polling(), name="rule-producers-book-depth")

    async def detach(self) -> None:
        self._sink = None
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})
        self._last_ts.clear()

    def poll(self) -> int:
        """One window: read each demanded symbol's book once; the symbols ticked. A second pass
        in the same window does nothing."""
        sink, books = self._sink, self._books()
        bucket = round(self._clock() * 1000) // BOOK_CADENCE_MS  # whole ms: no float drift
        if sink is None or books is None or bucket == self._bucket:
            return 0
        self._bucket = bucket
        ticked = 0
        with sink.window():
            for symbol, wants in self._demand(sink).items():
                if not sink.guard(self._read, sink, books, symbol, wants):
                    continue
                if self._ticks.allow(symbol):
                    sink.tick("on_book_update", symbol)
                    ticked += 1
        return ticked

    def _read(
        self, sink: PushSink, books: BookReader, symbol: str, wants: tuple[tuple[Want, int], ...]
    ) -> bool:
        age = books.applied_age_ms(symbol)
        engine = books.engine(symbol)
        last = None if engine is None else engine.last_applied
        if last is not None:
            self._last_ts[symbol] = last.ts_event // 1000
        ts_ms = self._last_ts.get(symbol)
        if age is None or ts_ms is None:
            return False  # no frame applied: warmup
        hit = False
        depth: list[tuple[Want, int]] = []
        for want, n in wants:
            if want.metric == "book_staleness_ms":  # the frame's age needs no view
                hit = sink.push(want, symbol, Decimal(age), ts_ms + age, BOOK_CADENCE_MS) or hit
            else:
                depth.append((want, n))
        view, held = None, 0
        for n in sorted({n for _, n in depth}, reverse=True):  # the deepest the book holds
            if (view := books.view(symbol, n)) is not None:
                held = n
                break
        if view is None or view.stale:
            return hit  # deeper than the book, not LIVE, or old: never pushed as fresh
        bids, asks = view.snapshot.bids, view.snapshot.asks
        for want, n in depth:
            if n > held:
                continue  # deeper than the book: this want alone stays warmup
            b, a = depth_sums(bids, n), depth_sums(asks, n)
            value: Decimal | None
            if want.metric == "dom_imbalance_ratio":
                value = None if a <= 0 else b / a
            else:
                value = None if b + a <= 0 else (b - a) / (b + a)
            if value is not None:
                hit = sink.push(want, symbol, value, ts_ms, BOOK_CADENCE_MS) or hit
        return hit

    def _demand(self, sink: PushSink) -> dict[str, tuple[tuple[Want, int], ...]]:
        """symbol -> its demanded ``(want, n)``, rebuilt on a demand change; an invalid ``n`` is
        never read (``warmup``) and is counted once per demand, without holding back another."""
        if self._by_symbol_of != (sink, sink.demand_version):
            by_symbol: dict[str, list[tuple[Want, int]]] = {}
            for want in sink.demanded():
                n = sink.guard(depth_n, want)
                if n is None:
                    sink.params_refused()
                    continue
                for symbol in want.symbols:
                    if symbol is not None:
                        by_symbol.setdefault(symbol, []).append((want, n))
            self._by_symbol = {s: tuple(w) for s, w in sorted(by_symbol.items())}
            self._by_symbol_of = (sink, sink.demand_version)
            self._last_ts = {s: t for s, t in self._last_ts.items() if s in self._by_symbol}
        return self._by_symbol

    async def _polling(self) -> None:
        while True:
            await self._sleep(BOOK_WINDOW_S)
            try:
                self.poll()
            except Exception as exc:  # the timer outlives one bad pass
                if (sink := self._sink) is not None:
                    sink.failed(exc)


#: Feed states that mean a feed is lost (`ingestion/watchdog.py`); ``healthy`` clears nothing.
LOST_FEED_STATES: Final = frozenset({"stale", "degraded", "delisted"})
#: The adapter's stream kinds (`StreamForTopic`) -> the producers' ``feeds``.
STREAM_FEEDS: Final = {
    "trades": "trades", "orderbook_delta": "book", "orderbook_snapshot": "book",
    "tickers": "ticker",
}  # fmt: skip
#: The health consumer's bus queue (a few events per feed and minute).
HEALTH_QUEUE_MAX: Final = 256


class FeedHealthWatch:
    """Lost feeds into the bridge: a ``stale``, ``degraded`` or ``delisted`` event on
    ``{env}.health.feed`` marks the pushed refs of the producers reading that feed
    (`ProducerBridge.feed_degraded`), so the alert evaluator disarms loudly before the lost bound.

    It pushes no metric; it is added to the bridge beside the producers only so it subscribes
    exactly while the bridge is attached. The event names a venue topic, which the adapter's
    `StreamForTopic` maps to a symbol (None: every symbol) and stream kinds; a topic it cannot map
    marks nothing (the watchdog's lost bound still covers it). An invalidation marker loses only
    marks, never a value: it is logged and the lost bound covers the gap."""

    def __init__(
        self,
        bus: Bus,
        env: str,
        mark: Callable[[str | None, str], int],
        topics: StreamForTopic,
        *,
        maxsize: int = HEALTH_QUEUE_MAX,
    ) -> None:
        if env not in LIVE_ENVS:
            raise ValueError("a metric producer subscribes a live env only")
        self.name = "feed_health"
        self.metrics: frozenset[str] = frozenset()
        self.feeds: frozenset[str] = frozenset()
        self._bus, self._env, self._mark, self._topics = bus, env, mark, topics
        self._maxsize = maxsize
        self._sink: PushSink | None = None
        self._sub: Subscription | None = None
        self._task: asyncio.Task[None] | None = None

    def attach(self, sink: PushSink) -> None:
        self._sink = sink
        if self._sub is None:
            self._sub = self._bus.subscribe(
                "rule-producers-feed-health",
                TopicPattern(env=self._env, domain="health", detail="feed"),
                QueuePolicy.INVALIDATE_ON_FULL, maxsize=self._maxsize,
            )  # fmt: skip
        if self._task is None:
            self._task = spawn(self._run(), name="rule-producers-feed-health")

    async def detach(self) -> None:
        self._sink = None
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.wait({task})
        sub, self._sub = self._sub, None
        if sub is not None:
            self._bus.unsubscribe(sub)

    def offer(self, item: object) -> int:
        """One bus item; the refs marked."""
        if isinstance(item, StreamInvalidated):
            _log().warning("rules.feed_health_invalidated")
            return 0
        if not isinstance(item, FeedHealthEvent) or item.state not in LOST_FEED_STATES:
            return 0
        symbol, kinds = self._topics(item.topic)
        feeds = sorted({STREAM_FEEDS[k] for k in kinds if k in STREAM_FEEDS})
        return sum(self._mark(symbol, feed) for feed in feeds)

    async def _run(self) -> None:
        while (sub := self._sub) is not None:
            item = await sub.get()
            if (sink := self._sink) is not None:
                sink.guard(self.offer, item)


def build_bridge(
    bus: Bus,
    env: str,
    rules: Callable[[], Awaitable[Sequence[EvaluableRule]]],
    *,
    bars: BarFieldProducer | None,
    books: Callable[[], BookReader | None],
    topics: StreamForTopic,
    metrics: Metrics | None = None,
) -> ProducerBridge:
    """The bridge with its four producers and the feed-health watch, for `RulesService.bind`.
    Called by the composition root only with `rules_evaluator_enabled` on (C-4.13): nothing here
    subscribes before the bridge attaches at `RulesService.start`. `bars` is the producer
    already spliced into `wire_bars` (None: the bar fields stay unproduced)."""
    scopes = MappingProxyType({d.name: d.scope for d in default_registry()})
    bridge = ProducerBridge(rules, scopes, metrics=metrics)
    ticks = BookTicks()
    producers: tuple[MetricProducer | None, ...] = (
        bars, QuoteProducer(bus, env, ticks, books=books), TickerProducer(bus, env),
        BookDepthProducer(books, ticks), FeedHealthWatch(bus, env, bridge.feed_degraded, topics),
    )  # fmt: skip
    for producer in producers:
        if producer is not None:
            bridge.add(producer)
    return bridge
