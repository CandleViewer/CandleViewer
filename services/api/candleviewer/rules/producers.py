"""Metric producer bridge (E35-T15): the one writer of the rules' `PushedMetricSource`.

Producers (the composition root's `rules_producers_wiring.py`: bars, quotes, the book, the ticker)
never see the source. Each is attached to its own `PushSink`, which pushes only what the
`MetricDemand` holds, the bound refs (`bound_ref`, the evaluator's own helper, so the key a
producer writes is the key an instance reads) of every evaluable rule, rebuilt on a rule change
(`poke`) and on a `REFRESH_S` fallback timer. A name outside the registry or the producer's own
set, a ref outside the demand, or a key past `MAX_DEMAND_REFS` is refused and counted, never
written (C-2.18). Every producer callback runs inside the sink's guard: an exception is counted
and logged once per episode, with the producer's name and the exception class only (C-12.6).

Only market-scope metrics are demanded (registry scope ``symbol`` or ``global``, no account in
the ref): the account- and position-scope rows are blocked by #1204 Part B's binding rule.

A 1 s watchdog marks a pushed ref ``source_degraded`` once its producer has been silent for
`max(LOST_AFTER_S, 6 x cadence)`, or when its feed reports itself lost (`feed_degraded`), so
the alert evaluator disarms loudly; the next push overwrites the mark. A mark is stamped at time
0: every reader sees it stale at once, so the rule evaluator skips it (``stale_data``) and never
evaluates its None, while the alert evaluator reads the lost reason before staleness. A producer
that pushes only on a change (`holds`, run in its guard) keeps a quiet symbol's ref unmarked only
while it says the symbol is still live (bounded by the producer: fail closed). One log line per
pass or feed report names the refs marked. A ref never pushed is never marked: it reads
``warmup``. Plain code, never a statechart (C-2.20).

Only the metrics an added producer binds are demanded, so a rule over an unsourced metric
neither takes a demand slot nor counts in `rule_metrics_in_warmup`. Keys of rules that list no
symbol (written per ticking symbol) share what the explicit refs leave of `MAX_DEMAND_REFS`, so
they can never starve another rule's listed symbols.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Literal, ParamSpec, Protocol, TypeVar, get_args

import structlog

from candleviewer.observability import spawn
from candleviewer.observability.metrics import BoundedMetric, MetricChild, Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.rules.evaluator.nodes import referenced_metrics
from candleviewer.rules.evaluator.snapshot import MetricScopes, Value, bound_ref, metric_key
from candleviewer.rules.ir.models import MetricRef, Rule

if TYPE_CHECKING:  # typing only: `manager` and `runner` reach the statechart (C-2.20 hot path)
    from candleviewer.rules.manager import EvaluableRule
    from candleviewer.rules.runner import PushedMetricSource

#: Bound refs the demand (and the source behind it) may hold; the next one is refused.
MAX_DEMAND_REFS: Final = 4096
#: The fallback demand refresh, beside the rule-change poke.
REFRESH_S: Final = 5.0
#: The watchdog's period (off the hot path), and the bound on one producer's stop.
WATCH_S: Final = 1.0
DETACH_S: Final = 5.0
#: Silence after which a pushed ref is marked ``source_degraded`` (PROPOSED, ticket).
LOST_AFTER_S: Final = 60.0
LOST_CADENCE_FACTOR: Final = 6
#: A demanded ref with no value for this long counts in `rule_metrics_in_warmup`.
WARMUP_ALERT_S: Final = 30.0
SOURCE_DEGRADED: Final = "source_degraded"
#: `Want.since`'s key for the part of a want a rule that lists no symbol reads.
ANY_SYMBOL: Final = "*"
#: Registry scopes the bridge serves: the market ones (#1204 Part B's binding rule).
MARKET_SCOPES: Final = frozenset({"symbol", "global"})

Refusal = Literal["unregistered", "undemanded", "demand_cap", "lease", "params"]
_REFUSALS: Final = frozenset(get_args(Refusal))
_SERIES: Final = (
    "rule_metric_pushes_total", "rule_metric_producer_errors_total",
    "rule_metric_refused_total", "rule_metrics_in_warmup",
)  # fmt: skip

P = ParamSpec("P")
R = TypeVar("R")


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def params_key(params: Mapping[str, object]) -> str:
    """The params part of `metric_key`, so the demand keys params exactly as the evaluator."""
    return json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)


class ProducerMetrics:
    """The bridge's four series over the app's facade; `None` counts nothing. No label names a
    symbol, a rule, an account or a value: `metric` is a registry name, `producer` a producer's
    name, `reason` the closed `Refusal` set."""

    def __init__(self, metrics: Metrics | None = None) -> None:
        self._series: dict[str, BoundedMetric] = {}
        self._pushes: dict[str, MetricChild] = {}
        if metrics is None:
            return
        for spec in CATALOGUE:
            if spec.name not in _SERIES:
                continue
            factory = metrics.gauge if spec.kind == "gauge" else metrics.counter
            self._series[spec.name] = factory(
                spec.name, spec.help, spec.labels, max_series=spec.max_series
            )

    def pushed(self, metric: str, count: int) -> None:
        """`count` pushes of `metric`, flushed off the hot path (a push only bumps a slot)."""
        child = self._pushes.get(metric)
        if child is None:
            series = self._series.get("rule_metric_pushes_total")
            if series is None:
                return
            child = self._pushes[metric] = series.labels(metric)
        child.inc(count)

    def error(self, producer: str) -> None:
        if (series := self._series.get("rule_metric_producer_errors_total")) is not None:
            series.labels(producer).inc()

    def refused(self, reason: Refusal) -> None:
        if reason not in _REFUSALS:
            raise ValueError("reason outside its closed set")  # never echoes the value
        if (series := self._series.get("rule_metric_refused_total")) is not None:
            series.labels(reason).inc()

    def in_warmup(self, count: int) -> None:
        if (series := self._series.get("rule_metrics_in_warmup")) is not None:
            series.child().set(count)


class _Live:
    """Push bookkeeping of one written key: its ref (for the mark), the last push, the mark."""

    __slots__ = (
        "any_symbol", "cadence_ms", "feeds", "key", "last_at", "marked", "producer", "ref",
        "sink", "symbol", "ts_ms", "want",
    )  # fmt: skip

    def __init__(
        self, want: Want, symbol: str | None, ref: MetricRef, sink: PushSink, any_symbol: bool
    ) -> None:
        self.want, self.symbol, self.ref, self.any_symbol = want, symbol, ref, any_symbol
        self.sink, self.producer, self.feeds = sink, sink.name, sink.feeds
        self.key = metric_key(ref)
        self.last_at = 0.0
        self.ts_ms = 0
        self.cadence_ms = 0
        self.marked = False


class Want:
    """One demanded ``(metric, params as authored, timeframe)`` and the symbols it is read for:
    ``symbols`` names explicit ones (None is the key with no symbol, a ``global`` metric's),
    ``any_symbol`` a rule that lists none, whose instances are the symbols that tick. Identity
    hashed; a producer holds it from `PushSink.wanted` until the demand changes. ``owners`` names
    the rules reading each symbol (`ANY_SYMBOL`: a rule that lists none), so a lease keeper can
    share its budget fairly; ``since`` when each was first demanded (the warmup gauge)."""

    __slots__ = (
        "any_symbol", "bound", "key", "lives", "metric", "owners", "params", "pushes", "since",
        "template", "timeframe",
    )  # fmt: skip

    def __init__(
        self, metric: str, params: Mapping[str, object], timeframe: str | None, pkey: str
    ) -> None:
        self.metric, self.timeframe = metric, timeframe
        self.params: Mapping[str, object] = MappingProxyType(dict(params))
        self.key = (metric, pkey, timeframe)
        self.any_symbol = False
        self.template: MetricRef | None = None  # the authored ref an any-symbol want binds
        self.bound: dict[str | None, MetricRef] = {}  # explicit symbol -> its bound ref
        self.lives: dict[str | None, _Live] = {}  # symbol -> what was written for it
        self.owners: dict[str | None, set[str]] = {}
        self.since: dict[str | None, float] = {}
        self.pushes = 0  # not yet counted in `rule_metric_pushes_total` (`ProducerBridge.flush`)

    @property
    def symbols(self) -> frozenset[str | None]:
        return frozenset(self.bound)

    def targets(self) -> tuple[str | None, ...]:
        return (*self.bound, *((ANY_SYMBOL,) if self.any_symbol else ()))

    def same_targets(self, other: Want) -> bool:
        return self.any_symbol == other.any_symbol and self.bound.keys() == other.bound.keys()


class MetricDemand:
    """The bound market refs of a set of rules, keyed ``(metric, params, timeframe)``; pure."""

    def __init__(self) -> None:
        self.wants: dict[tuple[str, str, str | None], Want] = {}
        self.by_metric: dict[str, tuple[Want, ...]] = {}
        self.size = 0
        self.explicit = 0  # bound refs of a named symbol (or none, global): one key each
        self.refused = 0

    @classmethod
    def of(
        cls, rules: Iterable[Rule], scopes: MetricScopes, served: frozenset[str] | None = None
    ) -> MetricDemand:
        """Each ref of each rule, bound per listed symbol as the evaluator binds it; a ref whose
        registry scope is not a market one, that names an account, or (with `served`) whose
        metric no producer binds, is not demanded. Past `MAX_DEMAND_REFS` bound refs the rest
        are refused (`refused`) and stay ``warmup``."""
        demand = cls()
        for rule in rules:
            symbols: tuple[str | None, ...] = tuple(rule.scope.symbols) or (None,)
            for authored in referenced_metrics(rule.conditions):
                if scopes.get(authored.metric) not in MARKET_SCOPES or authored.account_id:
                    continue
                if served is not None and authored.metric not in served:
                    continue
                pkey = params_key(authored.params)
                for symbol in symbols:
                    bound = bound_ref(authored, symbol, None, scopes)
                    demand._add(bound, pkey, scopes, str(rule.rule_id))
        demand.index()
        return demand

    def index(self) -> None:
        by_metric: dict[str, list[Want]] = {}
        for want in self.wants.values():
            by_metric.setdefault(want.metric, []).append(want)
        self.by_metric = {metric: tuple(wants) for metric, wants in by_metric.items()}

    def _add(self, ref: MetricRef, pkey: str, scopes: MetricScopes, owner: str) -> None:
        key = (ref.metric, pkey, ref.timeframe)
        want = self.wants.get(key)
        any_symbol = ref.symbol is None and scopes.get(ref.metric) == "symbol"
        if want is None or not (want.any_symbol if any_symbol else ref.symbol in want.bound):
            if self.size >= MAX_DEMAND_REFS:
                self.refused += 1
                return
            if want is None:
                want = self.wants[key] = Want(ref.metric, ref.params, ref.timeframe, pkey)
            self.size += 1
            if any_symbol:
                want.any_symbol, want.template = True, ref
            else:
                want.bound[ref.symbol] = ref
                self.explicit += 1
        want.owners.setdefault(ANY_SYMBOL if any_symbol else ref.symbol, set()).add(owner)

    @property
    def any_budget(self) -> int:
        """Keys the wants of rules that list no symbol may write: what the explicit refs leave."""
        return MAX_DEMAND_REFS - self.explicit

    def current(self, want: Want) -> bool:
        return self.wants.get(want.key) is want


class MetricProducer(Protocol):
    """A producer of registry metrics. ``feeds`` names the market streams it reads (``book``,
    ``trades``, ``ticker``), which `ProducerBridge.feed_degraded` matches; ``attach`` hands it its
    sink (it starts its consumers there), ``detach`` stops them."""

    @property
    def name(self) -> str: ...

    @property
    def metrics(self) -> frozenset[str]: ...

    @property
    def feeds(self) -> frozenset[str]: ...

    def attach(self, sink: PushSink) -> None: ...

    async def detach(self) -> None: ...


class PushSink:
    """One producer's door to the source: the only writer (`ProducerBridge.attach` makes one per
    producer). Sync and never awaits, so a bar sink or a bus consumer may call it in line."""

    def __init__(self, bridge: ProducerBridge, producer: MetricProducer) -> None:
        self._bridge = bridge
        self.name = producer.name
        self._metrics = producer.metrics & bridge.registered
        self.feeds = producer.feeds
        #: Optional: True while the producer, attached and consuming, still holds `symbol`'s
        #: latest event or knows its feed live (it pushes on a change only; a quote feed's book
        #: still applying frames), so a quiet symbol is not a lost one. Bounded by the producer.
        self.holds: Callable[[str], bool] | None = getattr(producer, "holds", None)
        self._failing = False
        self._depth = 0  # open `window`s
        self._window_failed = False

    @property
    def demand_version(self) -> int:
        """Bumped on each demand change, so a producer can re-read what it holds (leases)."""
        return self._bridge.version

    def demanded(self) -> tuple[Want, ...]:
        """Every demanded `Want` of this producer's metrics, read-only (a lease keeper's view)."""
        by_metric = self._bridge.demand.by_metric
        return tuple(w for metric in sorted(self._metrics) for w in by_metric.get(metric, ()))

    def wanted(
        self, metric: str, symbol: str | None, timeframe: str | None = None
    ) -> tuple[Want, ...]:
        """The demanded parameter sets of `metric` read for `symbol` at `timeframe`; a name
        outside the registry or this producer's set is refused, counted, and wants nothing."""
        if metric not in self._metrics:
            self._bridge.metrics.refused("unregistered")
            return ()
        any_ok = symbol is not None
        return tuple(
            w for w in self._bridge.demand.by_metric.get(metric, ())
            if w.timeframe == timeframe and (symbol in w.bound or (w.any_symbol and any_ok))
        )  # fmt: skip

    def push(
        self, want: Want, symbol: str | None, value: Value, ts_ms: int, cadence_ms: int
    ) -> bool:
        """Write `value` (exchange event time `ts_ms`, the producer's real cadence) under the key
        `want` is read by for `symbol`. A None value is not pushed (never defaulted, E3)."""
        bridge = self._bridge
        source = bridge.source
        if source is None or value is None:
            return False
        if want.metric not in self._metrics:
            bridge.metrics.refused("unregistered")
            return False
        if not bridge.demand.current(want):
            bridge.metrics.refused("undemanded")
            return False
        live = want.lives.get(symbol)
        if live is None and (live := bridge.live_for(want, symbol, self)) is None:
            return False
        source.push_key(live.key, value, ts_ms, cadence_ms)
        live.last_at, live.ts_ms, live.cadence_ms = bridge.clock(), ts_ms, cadence_ms
        live.marked = False
        want.pushes += 1
        return True

    def push_metric(
        self,
        metric: str,
        symbol: str | None,
        value: Value,
        ts_ms: int,
        cadence_ms: int,
        *,
        params: Mapping[str, object] | None = None,
        timeframe: str | None = None,
    ) -> bool:
        """`push` by name and params (a producer that does not hold its `Want`s)."""
        if metric not in self._metrics:
            self._bridge.metrics.refused("unregistered")
            return False
        want = self._bridge.demand.wants.get((metric, params_key(params or {}), timeframe))
        if want is None:
            if self._bridge.source is not None and value is not None:
                self._bridge.metrics.refused("undemanded")
            return False
        return self.push(want, symbol, value, ts_ms, cadence_ms)

    def tick(
        self, trigger_type: str, symbol: str | None = None, timeframe: str | None = None
    ) -> bool:
        """Wake the evaluator after the pushes it is woken for (push, then tick: E2)."""
        submit = self._bridge.submit
        return submit is not None and submit(trigger_type, symbol, timeframe)

    def lease_refused(self) -> None:
        """A bar-series lease the caps refused: the metric stays ``warmup``, counted."""
        self._bridge.metrics.refused("lease")

    def params_refused(self) -> None:
        """A demanded parameter set the producer cannot read (a bad ``n``): ``warmup``, counted."""
        self._bridge.metrics.refused("params")

    def guard(self, fn: Callable[P, R], /, *args: P.args, **kwargs: P.kwargs) -> R | None:
        """Run a producer callback; an `Exception` is counted and logged once per episode (name
        and class, never a value) and None returned. Cancellation is never caught. Inside a
        `window` a success does not end the episode; only a window with no failure does."""
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            self.failed(exc)
            return None
        if not self._depth:
            self._failing = False
        return result

    @contextlib.contextmanager
    def window(self) -> Iterator[None]:
        """One pass over many symbols (a flush, a poll): the failure episode ends only when a
        whole pass fails nowhere, so one symbol that keeps raising beside healthy ones is
        logged once, not once per pass."""
        if not self._depth:
            self._window_failed = False
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1
            if not self._depth and not self._window_failed:
                self._failing = False

    def failed(self, exc: Exception) -> None:
        self._window_failed = True
        self._bridge.metrics.error(self.name)
        if not self._failing:
            self._failing = True
            _log().error("rules.producer_failed", producer=self.name, error=type(exc).__name__)


class ProducerBridge:
    """Holds the demand, the producers' sinks, the refresh timer and the watchdog."""

    def __init__(
        self,
        rules: Callable[[], Awaitable[Sequence[EvaluableRule]]],
        scopes: MetricScopes,
        *,
        metrics: Metrics | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._rules, self._scopes = rules, scopes
        self.registered = frozenset(scopes)
        self.metrics = ProducerMetrics(metrics)
        self.clock, self._sleep = clock, sleep
        self._producers: list[MetricProducer] = []
        self._sinks: list[PushSink] = []
        self.demand = MetricDemand()
        self.version = 0
        self.lives = 0
        self.any_lives = 0  # of `lives`, the keys of rules that list no symbol
        self.source: PushedMetricSource | None = None
        self.submit: Callable[[str, str | None, str | None], bool] | None = None
        self._poked = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    def add(self, producer: MetricProducer) -> None:
        """One producer per metric (two must never write one key); before `attach` only."""
        if self.source is not None:
            raise RuntimeError("producers are added before the bridge attaches")
        taken = set().union(*(p.metrics for p in self._producers))
        if producer.metrics & taken:
            raise ValueError("a metric already has a producer")
        self._producers.append(producer)

    def attach(
        self, source: PushedMetricSource, submit: Callable[[str, str | None, str | None], bool]
    ) -> None:
        """Start: the demand refresh, the watchdog, then each producer with its own sink."""
        if self.source is not None:
            return
        self.source, self.submit = source, submit
        self._poked.clear()
        self._tasks = [
            spawn(self._refreshing(), name="rule-producers-demand"),
            spawn(self._watching(), name="rule-producers-watchdog"),
        ]
        self._sinks = [PushSink(self, p) for p in self._producers]
        for producer, sink in zip(self._producers, self._sinks, strict=True):
            sink.guard(producer.attach, sink)

    async def detach(self) -> None:
        """Stop the producers, then the timers; forget the demand. Call before the runner stops."""
        if self.source is None:
            return
        self.submit = None
        try:
            for producer, sink in zip(self._producers, self._sinks, strict=True):
                try:
                    async with asyncio.timeout(DETACH_S):
                        await producer.detach()
                except Exception as exc:  # one stop that raised or hung never keeps the others
                    sink.failed(exc)
        finally:  # a cancelled detach still stops the timers and forgets the source
            tasks, self._tasks = self._tasks, []
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.wait(tasks)
            self.flush(self.demand.wants.values())
            self._sinks, self.source = [], None
            self.demand, self.lives, self.any_lives = MetricDemand(), 0, 0
            self.version += 1

    def poke(self) -> None:
        """A rule changed (the `{env}.rules` broadcast): refresh the demand now."""
        self._poked.set()

    def uncovered(self) -> frozenset[str] | None:
        """Registry names no producer covers, while attached (the vocabulary's marking); None
        detached, so nothing is marked with the evaluator off."""
        return None if self.source is None else self.registered - self.bound

    @property
    def scopes(self) -> MetricScopes:
        """The registry scopes the demand binds refs with (the evaluator's own), read-only."""
        return self._scopes

    @property
    def bound(self) -> frozenset[str]:
        """The registry names the added producers push (24 §7.2.2's ``bound`` rows)."""
        return self.registered & frozenset().union(*(p.metrics for p in self._producers))

    async def refresh(self) -> None:
        """Rebuild the demand from the evaluable rules; a failed read keeps the last demand."""
        try:
            async with asyncio.timeout(REFRESH_S):
                items = await self._rules()
            demand = MetricDemand.of((item.rule for item in items), self._scopes, self.bound)
        except Exception as exc:  # the read or one bad rule: keep the last demand, loop on
            _log().warning("rules.producer_demand_failed", error=type(exc).__name__)
            return
        try:
            self.merge(demand)
        except Exception as exc:
            _log().error("rules.producer_demand_failed", error=type(exc).__name__)

    def merge(self, new: MetricDemand) -> None:
        """Swap in `new`, keeping each unchanged `Want` (and what producers hold of it) and the
        push bookkeeping of every ref still demanded; a dropped ref leaves the source."""
        now, old = self.clock(), self.demand
        changed = new.wants.keys() != old.wants.keys()
        for key, want in new.wants.items():
            prev = old.wants.get(key)
            if prev is None:
                want.since = dict.fromkeys(want.targets(), now)
            elif prev.same_targets(want):
                prev.owners = want.owners  # the same keys, maybe read by other rules now
                new.wants[key] = prev
            else:
                want.since = {t: prev.since.get(t, now) for t in want.targets()}
                changed, want.pushes, prev.pushes = True, prev.pushes, 0
                for symbol, live in prev.lives.items():
                    if symbol in want.bound or (want.any_symbol and symbol is not None):
                        live.want = want
                        want.lives[symbol] = live
                        if live.any_symbol == (symbol in want.bound):  # listed now, or no more
                            live.any_symbol = not live.any_symbol
                            self.any_lives += 1 if live.any_symbol else -1
        kept = {id(live) for want in new.wants.values() for live in want.lives.values()}
        self.flush(w for k, w in old.wants.items() if new.wants.get(k) is not w)
        for want in old.wants.values():
            for live in want.lives.values():
                if id(live) not in kept:
                    self._forget(live)
        for live in self._fit_any(new):
            self._forget(live)
        if new.refused > old.refused:
            for _ in range(new.refused - old.refused):
                self.metrics.refused("demand_cap")
        new.index()
        self.demand = new
        if changed:
            self.version += 1

    def _fit_any(self, new: MetricDemand) -> list[_Live]:
        """Take out the any-symbol keys past `new`'s budget (the last written first), so the
        explicit refs a rule change adds always have room and the source stays within
        `MAX_DEMAND_REFS`; the caller forgets them."""
        over = self.any_lives - new.any_budget
        evicted: list[_Live] = []
        for want in reversed(new.wants.values()):
            for symbol in reversed(list(want.lives)):
                if over <= len(evicted):
                    return evicted
                if want.lives[symbol].any_symbol:
                    evicted.append(want.lives.pop(symbol))
                    self.metrics.refused("demand_cap")
        return evicted

    def live_for(self, want: Want, symbol: str | None, sink: PushSink) -> _Live | None:
        """The bookkeeping of the first push of `want` for `symbol`, or None (refused, counted).
        A key of a rule that lists no symbol fits only in what the explicit refs leave."""
        ref = want.bound.get(symbol)
        any_symbol = ref is None
        if any_symbol and want.any_symbol and want.template is not None and symbol is not None:
            ref = bound_ref(want.template, symbol, None, self._scopes)
        if ref is None:
            self.metrics.refused("undemanded")
            return None
        if any_symbol and self.any_lives >= self.demand.any_budget:
            self.metrics.refused("demand_cap")
            return None
        live = want.lives[symbol] = _Live(want, symbol, ref, sink, any_symbol)
        self.lives += 1
        self.any_lives += any_symbol
        return live

    def _forget(self, live: _Live) -> None:
        self.lives -= 1
        self.any_lives -= live.any_symbol
        if self.source is not None:
            self.source.discard(live.key)

    def flush(self, wants: Iterable[Want]) -> None:
        """Count the pushes `wants` took since the last flush (the watchdog's pass, a merge)."""
        for want in wants:
            if want.pushes:
                self.metrics.pushed(want.metric, want.pushes)
                want.pushes = 0

    def watch(self) -> int:
        """One watchdog pass: count the pushes, mark each pushed ref silent past its lost bound,
        set the warmup gauge. Returns the refs marked."""
        self.flush(self.demand.wants.values())
        now, marked, warm = self.clock(), [], 0
        for want in self.demand.wants.values():
            for live in want.lives.values():
                bound = max(LOST_AFTER_S, LOST_CADENCE_FACTOR * live.cadence_ms / 1000)
                if live.marked or now - live.last_at < bound:
                    continue
                holds, symbol = live.sink.holds, live.symbol
                if holds is not None and symbol is not None and live.sink.guard(holds, symbol):
                    live.last_at = now  # quiet, not lost; a raising `holds` is not held
                    continue
                marked.append(live)
            late = [t for t, at in want.since.items() if now - at > WARMUP_ALERT_S]
            warm += sum(t in want.bound and t not in want.lives for t in late)
            warm += ANY_SYMBOL in late and not want.lives
        self.metrics.in_warmup(warm)
        return self._mark(marked)

    def feed_degraded(self, symbol: str | None, feed: str) -> int:
        """A feed reported ``stale``, ``degraded`` or ``delisted`` (`{env}.health.feed`): mark the
        pushed refs of its producers, for `symbol` (None: every symbol). Returns the refs marked."""
        return self._mark(
            [
                live for want in self.demand.wants.values() for live in want.lives.values()
                if feed in live.feeds and (symbol is None or live.symbol == symbol)
                and not live.marked
            ]
        )  # fmt: skip

    def _mark(self, lives: list[_Live]) -> int:
        """Mark `lives` (stamped 0: stale to every reader at once, the reason kept for the alert
        evaluator) and log them once, by name: never a symbol or a value, and never a line per
        ref (a socket-wide report can mark thousands)."""
        source = self.source
        if source is None or not lives:
            return 0
        for live in lives:
            source.mark(live.ref, SOURCE_DEGRADED)
            live.marked = True
        _log().warning(
            "rules.metric_source_lost", refs=len(lives),
            metrics=sorted({live.want.metric for live in lives}),
            producers=sorted({live.producer for live in lives}),
        )  # fmt: skip
        return len(lives)

    async def _refreshing(self) -> None:
        while True:
            self._poked.clear()
            await self.refresh()
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(REFRESH_S):
                    await self._poked.wait()

    async def _watching(self) -> None:
        while True:
            await self._sleep(WATCH_S)
            try:
                self.watch()
            except Exception as exc:  # the watchdog outlives one bad pass
                _log().error("rules.producer_watchdog_failed", error=type(exc).__name__)
