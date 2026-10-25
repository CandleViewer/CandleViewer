"""Process-wide Prometheus registry and `Metrics` facade (E04-T03, US-OBS-001).

Other modules import *this*, never `prometheus_client` directly (the
import-linter contract lands in the follow-up PR once existing call sites are
migrated). The facade guarantees, mechanically rather than by convention:

- a single `CollectorRegistry` per process (`Metrics.registry`);
- a mandatory `env` label injected by the facade itself, so demo and live
  series can never blur together (call sites cannot set or omit it);
- disallowed label *names* (secrets, personal data, order ids, free-form
  messages) are rejected at registration time;
- a per-metric `max_series` cardinality bound: new label combinations past
  the bound are refused (no series created), `metric_cardinality_breach_total`
  increments and an error is logged naming the metric — the process never
  crashes and the registry never grows unbounded;
- staleness-style gauges are computed *at scrape time* from a last-update
  timestamp (`staleness_gauge`), so a topic that stops updating shows a
  growing value instead of freezing at its last pushed one.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal, Protocol, cast

import structlog
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Enum,
    Gauge,
    GCCollector,
    Histogram,
    PlatformCollector,
    ProcessCollector,
)
from prometheus_client import REGISTRY as _DEFAULT_REGISTRY
from prometheus_client import values as _values
from prometheus_client.metrics import MetricWrapperBase
from prometheus_client.metrics_core import CounterMetricFamily, GaugeMetricFamily, Metric
from prometheus_client.openmetrics.exposition import escape_label_name, escape_metric_name
from prometheus_client.registry import Collector
from prometheus_client.samples import Sample
from prometheus_client.utils import floatToGoString

# Re-exported so modules outside `candleviewer.observability` never import
# `prometheus_client` directly (import-linter contract, E04-T03). `generate_latest` is this
# module's own renderer (byte-identical to the library's, #4530).
__all__ = [
    "CONTENT_TYPE_LATEST",
    "CollectorRegistry",
    "Counter",
    "Gauge",
    "Histogram",
    "ReexportCollector",
    "ScrapeCollector",
    "ScrapedFamily",
    "generate_latest",
]

MetricKind = Literal["counter", "gauge", "histogram", "enum"]

#: Environments a process may declare (`CV_ENV`, ticket config keys) plus the
#: structural exchange `testnet` environment (`settings.Environment`).
ALLOWED_ENVS: Final[frozenset[str]] = frozenset({"dev", "staging", "demo", "live", "testnet"})

#: Label names that may never appear on any metric (ticket Security notes,
#: SR-125): secrets, session material, personal data, order identifiers and
#: free-form exchange/error text. Matching is case-insensitive.
DISALLOWED_LABEL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "api_key",
        "apikey",
        "key",
        "secret",
        "api_secret",
        "signature",
        "token",
        "session",
        "session_id",
        "session_token",
        "cookie",
        "password",
        "totp",
        "email",
        "user",
        "user_name",
        "username",
        "user_id",
        "name",
        "ip",
        "order_id",
        "order_link_id",
        "orderlinkid",
        "exec_id",
        "trade_id",
        "message",
        "msg",
        "error",
        "error_message",
        "ret_msg",
        "reason_text",
    }
)

#: The injected label; call sites may not declare it themselves.
ENV_LABEL: Final[str] = "env"

DEFAULT_MAX_SERIES: Final[int] = 200

_LOGGER_NAME = "candleviewer.observability.metrics"


def single_process_values() -> bool:
    """Whether metric values take prometheus_client's in-process lock, the default. Multiprocess
    mode (`PROMETHEUS_MULTIPROC_DIR`) runs Python code under one module-wide lock, so a garbage
    collection callback that updates a metric could deadlock its own thread there (#3641)."""
    return _values.ValueClass is _values.MutexValue


class MetricsError(ValueError):
    """Invalid metric declaration (bad label, conflicting re-registration)."""


def check_label_names(metric: str, labels: Iterable[str]) -> None:
    """Raise `MetricsError` if any label name is disallowed or reserved."""
    for label in labels:
        lowered = label.lower()
        if lowered == ENV_LABEL:
            raise MetricsError(f"{metric}: '{ENV_LABEL}' is injected by the registry")
        if lowered in DISALLOWED_LABEL_NAMES:
            raise MetricsError(f"{metric}: label '{label}' is a disallowed label name")


@dataclass(frozen=True, slots=True)
class _Decl:
    kind: MetricKind
    labels: tuple[str, ...]
    buckets: tuple[float, ...] | None
    states: tuple[str, ...] | None
    max_series: int


class MetricChild(Protocol):
    """Structural type of a bound child; unused methods are no-ops per kind."""

    def inc(self, amount: float = 1) -> None: ...

    def dec(self, amount: float = 1) -> None: ...

    def set(self, value: float) -> None: ...

    def observe(self, amount: float) -> None: ...

    def state(self, state: str) -> None: ...


class _NoopChild:
    """Returned for label combinations refused by the cardinality guard."""

    def inc(self, amount: float = 1) -> None:
        return None

    def dec(self, amount: float = 1) -> None:
        return None

    def set(self, value: float) -> None:
        return None

    def observe(self, amount: float) -> None:
        return None

    def state(self, state: str) -> None:
        return None


NOOP_CHILD: Final[MetricChild] = _NoopChild()


class BoundedMetric:
    """A registered metric whose label combinations are capped at `max_series`.

    Hot paths should pre-bind children once at startup (`labels(...)` returns
    the cached child on repeat calls, so the lookup is one dict hit).
    """

    __slots__ = ("_breached", "_children", "_env", "_max_series", "_metric", "_owner", "name")

    def __init__(
        self,
        name: str,
        owner: Metrics,
        metric: MetricWrapperBase,
        env: str,
        max_series: int,
    ) -> None:
        self.name = name
        self._owner = owner
        self._metric = metric
        self._env = env
        self._max_series = max_series
        self._children: dict[tuple[str, ...], MetricChild] = {}
        self._breached = False

    @property
    def series_count(self) -> int:
        return len(self._children)

    @property
    def breached(self) -> bool:
        return self._breached

    def labels(self, *values: str) -> MetricChild:
        """Return the child for `values`, or a no-op child past `max_series`."""
        key = tuple(str(v) for v in values)
        child = self._children.get(key)
        if child is not None:
            return child
        if len(self._children) >= self._max_series:
            self._owner._record_breach(self, key)
            return NOOP_CHILD
        child = cast(MetricChild, self._metric.labels(self._env, *key))
        self._children[key] = child
        return child

    def child(self) -> MetricChild:
        """The single child of a metric declared with no call-site labels."""
        return self.labels()

    def sample_count(self) -> int:
        """Exported series for this metric (histograms count once per child)."""
        return len(self._children)


def _now() -> float:
    return time.monotonic()


@dataclass(slots=True)
class StalenessGauge:
    """A gauge whose value is `now - last_update`, computed at scrape time.

    `touch(key)` is the only hot-path call (one dict store). A key that has
    never been touched reports `+Inf` so a topic that never arrived is as
    visible as one that stopped.
    """

    metric: BoundedMetric
    clock: Callable[[], float]
    _last: dict[tuple[str, ...], float] = field(default_factory=dict)

    def track(self, *key: str) -> None:
        """Pre-bind a key (e.g. a topic known at startup) with a scrape callback."""
        k = tuple(key)
        if k in self._last:
            return
        self._last[k] = float("-inf")
        child = self.metric.labels(*k)
        set_function = getattr(child, "set_function", None)
        if set_function is not None:
            set_function(lambda k=k: self.age(*k))

    def touch(self, *key: str) -> None:
        k = tuple(key)
        if k not in self._last:
            self.track(*k)
        self._last[k] = self.clock()

    def age(self, *key: str) -> float:
        last = self._last.get(tuple(key), float("-inf"))
        return self.clock() - last


class Metrics:
    """The facade: one registry, env-labelled factories, cardinality guard."""

    def __init__(
        self,
        env: str,
        *,
        registry: CollectorRegistry | None = None,
        clock: Callable[[], float] = _now,
        process_collectors: bool = False,
    ) -> None:
        if env not in ALLOWED_ENVS:
            raise MetricsError(f"env must be one of {sorted(ALLOWED_ENVS)}, got {env!r}")
        self.env = env
        self.registry = registry if registry is not None else CollectorRegistry()
        self.clock = clock
        self._decls: dict[str, _Decl] = {}
        self._metrics: dict[str, BoundedMetric] = {}
        self._breach_counter = Counter(
            "metric_cardinality_breach_total",
            "Label combinations refused because a metric reached its max_series.",
            [ENV_LABEL, "metric"],
            registry=self.registry,
        )
        self._series_gauge = Gauge(
            "metrics_registry_series",
            "Label combinations currently held by facade-registered metrics.",
            [ENV_LABEL],
            registry=self.registry,
        )
        self._series_gauge.labels(env).set_function(self.total_series)
        self._process_collectors = False
        if process_collectors:
            self.add_process_collectors()

    def add_process_collectors(self) -> None:
        """Register process/GC/platform collectors once (reads `/proc`, so
        `create_app()` defers this to the lifespan; E04-T06)."""
        if self._process_collectors:
            return
        self._process_collectors = True
        ProcessCollector(registry=self.registry)
        GCCollector(registry=self.registry)
        PlatformCollector(registry=self.registry)

    # -- factories -------------------------------------------------------

    def counter(
        self,
        name: str,
        help_text: str,
        labels: Sequence[str] = (),
        *,
        max_series: int = DEFAULT_MAX_SERIES,
    ) -> BoundedMetric:
        return self._register(name, help_text, "counter", labels, max_series=max_series)

    def gauge(
        self,
        name: str,
        help_text: str,
        labels: Sequence[str] = (),
        *,
        max_series: int = DEFAULT_MAX_SERIES,
    ) -> BoundedMetric:
        return self._register(name, help_text, "gauge", labels, max_series=max_series)

    def histogram(
        self,
        name: str,
        help_text: str,
        labels: Sequence[str] = (),
        *,
        buckets: Sequence[float],
        max_series: int = DEFAULT_MAX_SERIES,
    ) -> BoundedMetric:
        return self._register(
            name, help_text, "histogram", labels, buckets=tuple(buckets), max_series=max_series
        )

    def enum(
        self,
        name: str,
        help_text: str,
        labels: Sequence[str] = (),
        *,
        states: Sequence[str],
        max_series: int = DEFAULT_MAX_SERIES,
    ) -> BoundedMetric:
        return self._register(
            name, help_text, "enum", labels, states=tuple(states), max_series=max_series
        )

    def staleness_gauge(
        self,
        name: str,
        help_text: str,
        labels: Sequence[str],
        *,
        max_series: int = DEFAULT_MAX_SERIES,
    ) -> StalenessGauge:
        return StalenessGauge(
            self.gauge(name, help_text, labels, max_series=max_series), self.clock
        )

    # -- registration ----------------------------------------------------

    def _register(
        self,
        name: str,
        help_text: str,
        kind: MetricKind,
        labels: Sequence[str],
        *,
        buckets: tuple[float, ...] | None = None,
        states: tuple[str, ...] | None = None,
        max_series: int,
    ) -> BoundedMetric:
        """Register (or idempotently re-fetch) a metric.

        Re-registering with an identical declaration returns the existing
        metric; a conflicting declaration raises `MetricsError`.
        """
        if max_series < 1:
            raise MetricsError(f"{name}: max_series must be >= 1")
        if not help_text.strip():
            raise MetricsError(f"{name}: help text is required")
        check_label_names(name, labels)
        decl = _Decl(kind, tuple(labels), buckets, states, max_series)
        existing = self._decls.get(name)
        if existing is not None:
            if existing != decl:
                raise MetricsError(f"{name}: conflicting re-registration")
            return self._metrics[name]
        all_labels = [ENV_LABEL, *labels]
        metric: MetricWrapperBase
        if kind == "counter":
            metric = Counter(name, help_text, all_labels, registry=self.registry)
        elif kind == "gauge":
            metric = Gauge(name, help_text, all_labels, registry=self.registry)
        elif kind == "histogram":
            if not buckets:
                raise MetricsError(f"{name}: histograms need explicit buckets")
            metric = Histogram(name, help_text, all_labels, buckets=buckets, registry=self.registry)
        else:
            if not states:
                raise MetricsError(f"{name}: enums need states")
            metric = Enum(name, help_text, all_labels, states=list(states), registry=self.registry)
        bounded = BoundedMetric(name, self, metric, self.env, max_series)
        self._decls[name] = decl
        self._metrics[name] = bounded
        return bounded

    def get(self, name: str) -> BoundedMetric:
        return self._metrics[name]

    def names(self) -> list[str]:
        return sorted(self._metrics)

    def total_series(self) -> float:
        return float(sum(m.series_count for m in self._metrics.values()))

    def _record_breach(self, metric: BoundedMetric, key: tuple[str, ...]) -> None:
        self._breach_counter.labels(self.env, metric.name).inc()
        if not metric._breached:
            metric._breached = True
            # Label values are not logged: they are the disclosure surface.
            # Resolved per call (rare path): a module-level logger cached under
            # `cache_logger_on_first_use=True` keeps a stale processor chain
            # after `configure_logging()` runs (see storage/cold/observability).
            structlog.get_logger(_LOGGER_NAME).error(
                "metric_cardinality_breach",
                metric=metric.name,
                max_series=metric._max_series,
                label_arity=len(key),
            )

    # -- periodic work ---------------------------------------------------

    def check_cardinality(self) -> list[str]:
        """The 60 s background check: names of metrics currently at their bound."""
        return [m.name for m in self._metrics.values() if m.breached]

    def snapshot(self, names: Iterable[str]) -> dict[str, float]:
        """Compact `{series: value}` view of the named metrics (fallback log)."""
        wanted = set(names)
        out: dict[str, float] = {}
        for family in self.registry.collect():
            if family.name not in wanted:
                continue
            for sample in family.samples:
                if sample.name.endswith(("_bucket", "_created")):
                    continue
                extra = ",".join(
                    f"{k}={v}" for k, v in sorted(sample.labels.items()) if k != ENV_LABEL
                )
                key = f"{sample.name}{{{extra}}}" if extra else sample.name
                out[key] = sample.value
        return out


class ReexportCollector(Collector):
    """Serve named families from a *source* registry (default: the library
    global one module-level metrics land on) on a *target* registry, adding
    constant labels (E08-T06: `env`, `exchange` on every ingestion series).

    Registration on `target` is the side effect of construction; `close()`
    unregisters (idempotent). Families not in `names` are never exposed, so
    the target registry's surface is exactly the declared set.
    """

    def __init__(
        self,
        target: CollectorRegistry,
        *,
        names: frozenset[str],
        const_labels: dict[str, str],
        source: CollectorRegistry = _DEFAULT_REGISTRY,
    ) -> None:
        check_label_names("reexport", [k for k in const_labels if k != ENV_LABEL])
        self._names = names
        self._const = dict(const_labels)
        self._source = source
        self._target: CollectorRegistry | None = target
        target.register(self)

    def describe(self) -> list[Metric]:
        # Empty describe: lets the target registry accept us without name
        # clashes being checked against families that may not exist yet.
        return []

    def collect(self) -> Iterable[Metric]:
        for family in self._source.collect():
            # Counter families drop the `_total` suffix; declarations keep it.
            if family.name not in self._names and f"{family.name}_total" not in self._names:
                continue
            out = Metric(family.name, family.documentation, family.type, family.unit)
            for s in family.samples:
                out.add_sample(s.name, {**s.labels, **self._const}, s.value, s.timestamp)
            yield out

    def close(self) -> None:
        if self._target is not None:
            self._target.unregister(self)
            self._target = None


@dataclass(frozen=True, slots=True)
class ScrapedFamily:
    """A counter or gauge a `ScrapeCollector` serves: (label values, value) per sample."""

    name: str
    kind: MetricKind
    help: str
    labels: tuple[str, ...]
    samples: tuple[tuple[tuple[str, ...], float], ...]


class ScrapeCollector(Collector):
    """Serve on `target` the families `read()` returns at each scrape, with `env`: `read()` runs in
    the scrape's thread, so it reads in-memory values only. Its families are checked once here, as
    the facade checks its own; construction registers it, `close()` unregisters it. A `read()` that
    raises at a scrape serves none of its families and leaves the rest of the scrape whole."""

    def __init__(
        self, target: CollectorRegistry, *, env: str, read: Callable[[], Iterable[ScrapedFamily]]
    ) -> None:
        for family in read():
            check_label_names(family.name, family.labels)
            if family.kind not in ("counter", "gauge"):
                raise MetricsError(f"{family.name}: a scraped family is a counter or a gauge")
            if any(len(values) != len(family.labels) for values, _ in family.samples):
                raise MetricsError(f"{family.name}: a sample has one value per label")
        self._env, self._read, self._failing = env, read, False
        self._target: CollectorRegistry | None = target
        target.register(self)

    def describe(self) -> list[Metric]:
        return []  # as `ReexportCollector`: the families are read at the scrape

    def collect(self) -> Iterable[Metric]:
        try:  # SR-S4A1-01: a failing read loses its own families, never every other alert's
            families = list(self._read())
        except Exception as exc:
            if not self._failing:  # once until a read succeeds again; the error's class only
                structlog.get_logger(_LOGGER_NAME).error(
                    "metrics.scrape_read_failed", error=type(exc).__name__
                )
            self._failing = True
            return
        self._failing = False
        for family in families:
            make = CounterMetricFamily if family.kind == "counter" else GaugeMetricFamily
            out = make(family.name, family.help, labels=[ENV_LABEL, *family.labels])
            for values, value in family.samples:
                out.add_metric([self._env, *values], value)
            yield out

    def close(self) -> None:
        if self._target is not None:
            self._target.unregister(self)
            self._target = None


#: The library's float formatter; untyped upstream, so typed here once.
_go_float: Final = cast(Callable[[float], str], floatToGoString)

#: Samples the text format moves into a gauge family of their own after the metric's samples.
_OM_SUFFIXES: Final = ("_created", "_gsum", "_gcount")


def _label_value(value: str) -> str:
    """A label value as the text format writes it (the library's escaping)."""
    if "\\" in value or "\n" in value or '"' in value:
        return value.replace("\\", r"\\").replace("\n", r"\n").replace('"', r"\"")
    return value


def generate_latest(registry: Collector = _DEFAULT_REGISTRY) -> bytes:
    """The Prometheus text exposition of `registry`, byte for byte what
    `prometheus_client.generate_latest(registry)` (default escaping) returns, at about half its
    cost (#4530); the registry defaults to the process's, as the library's does. The library
    sorts, validates and escapes every label name of every sample; here each distinct label-name
    set becomes one format template per scrape, and each metric name and each nonzero sample
    value is rendered once per scrape (zero every time, as `-0.0 == 0.0` renders differently).
    Label values are escaped as the library does."""
    names: dict[str, str] = {}
    templates: dict[tuple[str, ...], tuple[tuple[str, ...], str]] = {}
    values: dict[float, str] = {}

    def name_of(raw: str) -> str:
        escaped = names.get(raw)
        if escaped is None:
            escaped = names[raw] = escape_metric_name(raw)
        return escaped

    def template_of(key: tuple[str, ...]) -> tuple[tuple[str, ...], str]:
        ordered = tuple(sorted(key))
        pairs = [escape_label_name(k).replace("{", "{{").replace("}", "}}") for k in ordered]
        return ordered, "{{" + ",".join([f'{k}="{{}}"' for k in pairs]) + "}}"

    def sample_line(sample: Sample) -> str:
        labels = sample.labels
        labelstr = ""
        if labels:
            key = tuple(labels)
            found = templates.get(key)
            if found is None:
                found = templates[key] = template_of(key)
            ordered, template = found
            labelstr = template.format(*[_label_value(labels[k]) for k in ordered])
        value = sample.value
        rendered = values.get(value) if value else None
        if rendered is None:
            rendered = _go_float(value)
            if value:
                values[value] = rendered
        timestamp = ""
        if sample.timestamp is not None:  # in milliseconds
            timestamp = f" {int(float(sample.timestamp) * 1000):d}"
        return f"{name_of(sample.name)}{labelstr} {rendered}{timestamp}\n"

    output: list[str] = []
    for metric in registry.collect():
        om_samples: dict[str, list[str]] = {}
        try:
            mname, mtype = metric.name, metric.type
            if mtype == "counter":  # OpenMetrics names and types, in the Prometheus format
                mname += "_total"
            elif mtype == "info":
                mname, mtype = mname + "_info", "gauge"
            elif mtype == "stateset":
                mtype = "gauge"
            elif mtype == "gaugehistogram":
                mtype = "histogram"
            elif mtype == "unknown":
                mtype = "untyped"
            doc = metric.documentation.replace("\\", r"\\").replace("\n", r"\n")
            output.append(f"# HELP {name_of(mname)} {doc}\n")
            output.append(f"# TYPE {name_of(mname)} {mtype}\n")
            moved = {metric.name + suffix: suffix for suffix in _OM_SUFFIXES}
            for sample in metric.samples:
                suffix = moved.get(sample.name)
                if suffix is None:
                    output.append(sample_line(sample))
                else:
                    om_samples.setdefault(suffix, []).append(sample_line(sample))
        except Exception as exception:  # annotated as the library does, then re-raised
            exception.args = (*(exception.args or ("",)), metric)
            raise
        for suffix, lines in sorted(om_samples.items()):
            output.append(f"# HELP {name_of(metric.name + suffix)} {doc}\n")
            output.append(f"# TYPE {name_of(metric.name + suffix)} gauge\n")
            output.extend(lines)
    return "".join(output).encode("utf-8")
