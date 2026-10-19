"""Ingestion metric registry (E08-T06) — the single owner of every metric name
emitted by the ingestion path (`E08-T02/T03/T04/S01/S03/S04/S05/S06/S07`).

Declaration-first: every metric is a `MetricSpec` in `SPECS` (name, kind,
call-site labels, help, owning module). Ingestion-owned metrics are built
from their spec here and imported by child modules; metrics owned by layers
that may not import ingestion (`exchange.base`, the concrete adapter, `bus` —
CONSTITUTION §3 / `.importlinter`) are declared here and instantiated in
their owner module. `tests/unit/ingestion/test_metric_registry.py` scans the
packages and fails naming any undeclared, duplicated, orphaned or
spec-mismatched metric.

Labels: `env` and `exchange` are attached once, at scrape time, by
`export_ingestion_metrics()` (the composition root passes them), so they are
consistent across every series and no call site can set them. Call-site
labels come from `ALLOWED_LABELS` only; symbol values pass through
`symbol_label()` (bounded cardinality, no free-form input). Adapter-owned
series keep their adapter prefix (C-2.2: the adapter module owns them).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal

from candleviewer.observability.metrics import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    ReexportCollector,
)

Kind = Literal["counter", "gauge", "histogram"]
Owner = Literal["ingestion", "exchange.base", "adapter", "bus"]

#: Call-site label names any ingestion-path metric may use. `env`/`exchange`
#: are deliberately absent: they are attached at export time, never by code.
ALLOWED_LABELS: Final[frozenset[str]] = frozenset(
    {
        "symbol",
        "stream",
        "topic",
        "interval",
        "result",
        "reason",
        "recovered",
        "table",
        "endpoint",
        "endpoint_class",
        "scope",
        "code",
        "class",
        "socket",
        "topic_class",
        "subscriber",
    }
)


@dataclass(frozen=True, slots=True)
class MetricSpec:
    name: str
    kind: Kind
    labels: tuple[str, ...]
    help: str
    owner: Owner = "ingestion"


def _c(name: str, help_text: str, *labels: str, owner: Owner = "ingestion") -> MetricSpec:
    return MetricSpec(name, "counter", labels, help_text, owner)


def _g(name: str, help_text: str, *labels: str, owner: Owner = "ingestion") -> MetricSpec:
    return MetricSpec(name, "gauge", labels, help_text, owner)


def _h(name: str, help_text: str, *labels: str, owner: Owner = "ingestion") -> MetricSpec:
    return MetricSpec(name, "histogram", labels, help_text, owner)


#: Every ingestion-path metric, declared once. Order is presentation only.
SPECS: Final[tuple[MetricSpec, ...]] = (
    # E08-S07 ClockGuard (alert rules: infra/prometheus/alerts/clock_sync.yml)
    _g("exchange_clock_drift_ms", "Signed offset (server - local) to exchange time, ms."),
    _g("clock_offset_age_seconds", "Seconds since the last successful clock offset measurement."),
    _c("clock_measurements_total", "Clock offset measurement attempts, by result.", "result"),
    _c("clock_resync_triggered_total", "Out-of-schedule clock resyncs, by reason.", "reason"),
    # E08-S01 instrument catalogue refresh
    _c("instruments_refresh_total", "Instrument catalogue refresh attempts, by result.", "result"),
    _g("instruments_cache_age_seconds", "Seconds since the served catalogue was fetched."),
    _g("instruments_catalogue_size", "Symbols in the served instrument catalogue snapshot."),
    # E08-S03 ticker / E08-S04 trade tape
    _c("ingest_events_total", "Normalised market events ingested.", "stream", "symbol"),
    _g("ws_topic_staleness_seconds", "Seconds since the last message on a watched topic.", "topic"),
    _c("ticker_merge_incomplete_total", "Ticker deltas held: merge incomplete.", "symbol"),
    _g("ingest_lag_seconds", "Latest ingest lag (ingest time - exchange time).", "stream"),
    _c("ticker_writes_dropped_total", "Ticker rows dropped from write-behind (oldest first)."),
    _c("trade_duplicates_suppressed_total", "Trade prints suppressed as duplicates.", "symbol"),
    _c("trade_gaps_total", "Tape gap windows, by backfill recovery.", "symbol", "recovered"),
    _c("trade_backfill_rows_total", "Rows returned by the trade gap backfill.", "result"),
    _c("trade_prints_rejected_total", "Malformed trade frames rejected before dedupe."),
    _c(
        "ingest_rejected_total",
        "Frames rejected at the ingest boundary, by stream and bounded reason.",
        "stream",
        "reason",
    ),
    _c(
        "ingest_dispatch_overflow_total",
        "Frames dropped by a full per-topic dispatch lane (resync follows), by stream.",
        "stream",
    ),
    _g("questdb_write_queue_depth", "Rows waiting in a write-behind queue.", "table"),
    _c(
        "trade_writes_dropped_total",
        "Trade rows evicted from write-behind (oldest first), by reason (outage|queue_full).",
        "reason",
    ),
    _c(
        "book_writes_dropped_total",
        "Book rows evicted from write-behind (oldest first), by reason (outage|queue_full).",
        "reason",
    ),
    _c(
        "write_behind_lost_runs_truncated_total",
        "Lost hot-tier runs merged because a symbol hit the per-symbol run cap.",
        "table",
    ),
    # E08-S05 book health (E08-T06: resync rate + live state for the dashboard/alerts)
    _c("ingest_book_resyncs_total", "Book resyncs (left LIVE), by reason.", "symbol", "reason"),
    _g("ingest_book_live", "1 while the symbol's book is LIVE, else 0.", "symbol"),
    # E08-T04 connection (E08-T06: dashboard + silent-death meta-alert)
    _g("ingest_ws_up", "1 while the public socket is open, else 0.", "socket"),
    _g("ingest_enabled", "1 when the ingestion pipeline is wired in this process."),
    # E08-S06 kline backfill
    _c("kline_backfill_pages_total", "Kline page fetches.", "symbol", "interval", "result"),
    _h("kline_backfill_duration_seconds", "Kline range backfill time.", "symbol", "interval"),
    _g("kline_cache_hit_ratio", "Cache-covered fraction of a kline range.", "symbol", "interval"),
    _g("kline_coverage_holes", "Uncovered kline sub-ranges after backfill.", "symbol", "interval"),
    # E12-S05 SR-E12-08/09/10
    _c("kline_backfill_rate_limited_total", "Rate-limited kline pages.", "symbol", "interval"),
    _c(
        "kline_backfill_pages_rejected_total",
        "Kline pages rejected by strict validation (SR-E12-09).",
        "symbol",
        "interval",
        "reason",
    ),
    _c(
        "kline_backfill_jobs_total",
        "Finished kline backfill jobs by outcome.",
        "symbol",
        "interval",
        "result",
    ),
    _c(
        "kline_crosscheck_divergence_total",
        "Kline bars diverging from tape-built bars beyond tolerance.",
        "symbol",
        "interval",
    ),
    # Owned by layers ingestion may not be imported by (declared here, built there).
    _c(
        "exchange_errors_total",
        "Exchange errors by taxonomy class.",
        "class",
        owner="exchange.base",
    ),
    _c(
        "bybit_rest_requests_total",
        "Adapter REST requests, by endpoint and result.",
        "endpoint",
        "result",
        owner="adapter",
    ),
    _h(
        "bybit_rest_latency_seconds",
        "Adapter REST latency, by endpoint.",
        "endpoint",
        owner="adapter",
    ),
    _g(
        "bybit_rate_limit_remaining",
        "Last-observed remaining rate-limit budget (scope public|account, never a UID).",
        "scope",
        "endpoint_class",
        owner="adapter",
    ),
    _g(
        "bybit_ip_hold_remaining_seconds",
        "Seconds left on the IP-wide REST hold after a 10018 (0 when none; no UID label).",
        owner="adapter",
    ),
    _c(
        "bybit_rate_limited_total",
        "Rate-limited responses, by code.",
        "code",
        owner="adapter",
    ),
    _c("bus_published_total", "Events published, by topic class.", "topic_class", owner="bus"),
    _c("bus_delivered_total", "Events delivered to a subscriber.", "subscriber", owner="bus"),
    _c(
        "bus_conflated_total",
        "Events superseded under CONFLATE_LATEST.",
        "topic_class",
        owner="bus",
    ),
    _c("ingest_queue_full_total", "NEVER_DROP queue observed full.", "class", owner="bus"),
    _g("bus_subscriber_lag", "Current queue depth per subscriber.", "subscriber", owner="bus"),
    _c(
        "bus_stream_invalidated_total",
        "INVALIDATE_ON_FULL markers delivered.",
        "topic_class",
        owner="bus",
    ),
)

SPEC_BY_NAME: Final[dict[str, MetricSpec]] = {s.name: s for s in SPECS}

# --- symbol label cardinality guard (ticket Security/Performance notes) ------

#: Overflow bucket for any symbol outside the bound universe.
OTHER_SYMBOL: Final[str] = "other"
#: Hard cap on distinct symbol label values when no universe is bound yet.
MAX_SYMBOLS: Final[int] = 32
_SYMBOL_RE: Final = re.compile(r"^[A-Z0-9]{2,24}$")


class _SymbolGuard:
    __slots__ = ("seen", "universe")

    def __init__(self) -> None:
        self.universe: frozenset[str] | None = None
        self.seen: set[str] = set()


_GUARD: Final = _SymbolGuard()


def bind_symbol_universe(symbols: Iterable[str]) -> None:
    """Restrict `symbol` label values to the configured/recorded set."""
    _GUARD.universe = frozenset(s for s in symbols if _SYMBOL_RE.fullmatch(s))
    _GUARD.seen.clear()
    _EVENT_CHILDREN.clear()


def reset_symbol_universe() -> None:
    """Return to the unbound (capped) mode."""
    _GUARD.universe = None
    _GUARD.seen.clear()
    _EVENT_CHILDREN.clear()


def symbol_label(value: str) -> str:
    """Map `value` to a bounded label: a known symbol, else `other`.

    Free-form text (lowercase, punctuation, spaces, over-long strings) can
    never become a label value; an unbound process admits at most
    `MAX_SYMBOLS` distinct well-formed symbols before folding to `other`.
    """
    universe = _GUARD.universe
    if universe is not None:
        return value if value in universe else OTHER_SYMBOL
    if value in _GUARD.seen:  # hot path: already admitted (and validated)
        return value
    if not _SYMBOL_RE.fullmatch(value) or len(_GUARD.seen) >= MAX_SYMBOLS:
        return OTHER_SYMBOL
    _GUARD.seen.add(value)
    return value


# --- ingestion-owned metric objects (child modules import these) ------------


def _counter(name: str) -> Counter:
    spec = SPEC_BY_NAME[name]
    if spec.kind != "counter" or spec.owner != "ingestion":  # pragma: no cover
        raise ValueError(f"{name}: not an ingestion-owned counter")
    return Counter(name, spec.help, list(spec.labels))


def _gauge(name: str) -> Gauge:
    spec = SPEC_BY_NAME[name]
    if spec.kind != "gauge" or spec.owner != "ingestion":  # pragma: no cover
        raise ValueError(f"{name}: not an ingestion-owned gauge")
    return Gauge(name, spec.help, list(spec.labels))


def _histogram(name: str) -> Histogram:
    spec = SPEC_BY_NAME[name]
    if spec.kind != "histogram" or spec.owner != "ingestion":  # pragma: no cover
        raise ValueError(f"{name}: not an ingestion-owned histogram")
    return Histogram(name, spec.help, list(spec.labels))


exchange_clock_drift_ms = _gauge("exchange_clock_drift_ms")
clock_offset_age_seconds = _gauge("clock_offset_age_seconds")
clock_measurements_total = _counter("clock_measurements_total")
clock_resync_triggered_total = _counter("clock_resync_triggered_total")
instruments_refresh_total = _counter("instruments_refresh_total")
instruments_cache_age_seconds = _gauge("instruments_cache_age_seconds")
instruments_catalogue_size = _gauge("instruments_catalogue_size")
ingest_events_total = _counter("ingest_events_total")
ws_topic_staleness_seconds = _gauge("ws_topic_staleness_seconds")
ticker_merge_incomplete_total = _counter("ticker_merge_incomplete_total")
ingest_lag_seconds = _gauge("ingest_lag_seconds")
ticker_writes_dropped_total = _counter("ticker_writes_dropped_total")
trade_duplicates_suppressed_total = _counter("trade_duplicates_suppressed_total")
trade_gaps_total = _counter("trade_gaps_total")
trade_backfill_rows_total = _counter("trade_backfill_rows_total")
trade_prints_rejected_total = _counter("trade_prints_rejected_total")
ingest_rejected_total = _counter("ingest_rejected_total")
ingest_dispatch_overflow_total = _counter("ingest_dispatch_overflow_total")
questdb_write_queue_depth = _gauge("questdb_write_queue_depth")
trade_writes_dropped_total = _counter("trade_writes_dropped_total")
book_writes_dropped_total = _counter("book_writes_dropped_total")
write_behind_lost_runs_truncated_total = _counter("write_behind_lost_runs_truncated_total")
ingest_book_resyncs_total = _counter("ingest_book_resyncs_total")
ingest_book_live = _gauge("ingest_book_live")
ingest_ws_up = _gauge("ingest_ws_up")
ingest_enabled = _gauge("ingest_enabled")
kline_backfill_pages_total = _counter("kline_backfill_pages_total")
kline_backfill_duration_seconds = _histogram("kline_backfill_duration_seconds")
kline_cache_hit_ratio = _gauge("kline_cache_hit_ratio")
kline_coverage_holes = _gauge("kline_coverage_holes")
kline_backfill_rate_limited_total = _counter("kline_backfill_rate_limited_total")
kline_backfill_pages_rejected_total = _counter("kline_backfill_pages_rejected_total")
kline_backfill_jobs_total = _counter("kline_backfill_jobs_total")
kline_crosscheck_divergence_total = _counter("kline_crosscheck_divergence_total")

_EVENT_CHILDREN: dict[tuple[str, str], Counter] = {}


def count_event(stream: str, symbol: str) -> None:
    """Hot path (per trade / ticker message): one dict hit + `inc()` on a
    pre-bound `ingest_events_total` child; the symbol is bounded first."""
    key = (stream, symbol)
    child = _EVENT_CHILDREN.get(key)
    if child is None:
        child = ingest_events_total.labels(stream=stream, symbol=symbol_label(symbol))
        if len(_EVENT_CHILDREN) < 4 * (MAX_SYMBOLS + 1):  # bounded cache
            _EVENT_CHILDREN[key] = child
    child.inc()


def export_ingestion_metrics(
    registry: CollectorRegistry, *, env: str, exchange: str
) -> ReexportCollector:
    """Expose every declared ingestion-path metric on `registry` (the scraped
    `/metrics` registry) with consistent `env` + `exchange` labels.

    Before E08-T06 these series lived only on the library default registry,
    which `/metrics` does not serve — so none of them were scraped.
    """
    return ReexportCollector(
        registry, names=frozenset(SPEC_BY_NAME), const_labels={"env": env, "exchange": exchange}
    )
