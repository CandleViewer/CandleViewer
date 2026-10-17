"""Every `bars_*` series the app can serve is catalogued, exported and bounded (#1998).

`test_exported_bars_metrics_served_on_app_registry_with_env` compares two lists kept by hand: the
catalogue's `exported` entries and `bars.metrics.EXPORTED_NAMES`. A series on neither passes it,
which is how the writer and reader series sat on the library registry uncatalogued and never
scraped. These tests start from the collectors on `prometheus_client.REGISTRY` instead, so a
`bars_*` series that skips the catalogue or the export set fails here, whichever package defines
it and whether or not it is bound at module level.

Scope: the `bars_` prefix, and the library's own metric classes (`Counter`, `Gauge`, `Histogram`,
...) on the default registry once `candleviewer.app` and every `candleviewer.bars` module are
imported. A series on another registry, a hand-written `Collector`, or code nothing imports is not
seen. The singular `bar_*` series are not checked.
"""

from __future__ import annotations

import importlib
import math
import pkgutil
from typing import get_args

from prometheus_client import REGISTRY, Counter, Gauge, Histogram, generate_latest
from prometheus_client.metrics import MetricWrapperBase
from prometheus_client.parser import text_string_to_metric_families

import candleviewer.bars as bars_package
from candleviewer.bars import reader, writer
from candleviewer.bars.metrics import EXPORTED_NAMES, export_bars_metrics
from candleviewer.bars.models import BarKind
from candleviewer.bars.rows import SOURCE_RANK
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE

#: The series of `bars.writer` and `bars.reader` that #1998 catalogued.
WRITE_AND_READ_PATH = (
    "bars_rows_written_total",
    "bars_write_queue_depth",
    "bars_write_saturation_total",
    "bars_write_failed_total",
    "bars_write_latency_seconds",
    "bars_symbol_cardinality",
    "bars_source_overwrite_refused_total",
    "bars_checksum_mismatch_total",
    "bars_rebuild_scheduled_total",
    "bars_stale_build_version_total",
)
#: Closed by the emitting code, and `test_bars_persistence.py` asserts each value is emitted:
#: `reader._integrity_failure` returns one of the first pair, `writer._write_one` counts one of
#: the second.
INTEGRITY_REASONS = ("mismatch", "missing")
WRITE_FAILURE_REASONS = ("permanent", "transient_exhausted")


def _defined_bars_metrics() -> dict[str, MetricWrapperBase]:
    """The `bars_*` metric objects on `prometheus_client.REGISTRY`, by the name the catalogue uses
    (the library drops a counter's `_total` from its own name), once `candleviewer.app` (the
    composition root) and every module of `candleviewer.bars` are imported: a series defined
    anywhere the app imports, bound at module level or not."""
    importlib.import_module("candleviewer.app")
    for module in pkgutil.walk_packages(bars_package.__path__, "candleviewer.bars."):
        importlib.import_module(module.name)
    found: dict[str, MetricWrapperBase] = {}
    for collector in list(REGISTRY._collector_to_names):
        if isinstance(collector, MetricWrapperBase) and collector._name.startswith("bars_"):
            found[collector._name + ("_total" if collector._type == "counter" else "")] = collector
    return found


def test_every_bars_metric_the_code_defines_is_catalogued_live_and_exported() -> None:
    defined = _defined_bars_metrics()
    # The scan reaches a builder module, the writer and the reader: it is not silently empty.
    scanned = {"bars_built_total", "bars_rows_written_total", "bars_stale_build_version_total"}
    assert scanned <= defined.keys()
    specs = {s.name: s for s in CATALOGUE}
    problems: list[str] = []
    for name, metric in sorted(defined.items()):
        spec = specs.get(name)
        if spec is None:
            problems.append(f"{name}: not in metrics_catalogue.CATALOGUE")
            continue
        if spec.status != "live" or not spec.exported:
            problems.append(f"{name}: module-level, so its entry must be live and exported=True")
        if name not in EXPORTED_NAMES:
            problems.append(f"{name}: not in bars.metrics.EXPORTED_NAMES, so /metrics omits it")
        if spec.kind != metric._type:
            problems.append(f"{name}: catalogue kind {spec.kind}, code {metric._type}")
        if spec.labels != tuple(metric._labelnames):
            problems.append(f"{name}: catalogue labels {spec.labels}, code {metric._labelnames}")
        if isinstance(metric, Histogram):
            bounds = tuple(b for b in metric._upper_bounds if not math.isinf(b))
            if spec.buckets != bounds:
                problems.append(f"{name}: buckets {spec.buckets} in the catalogue, code {bounds}")
    assert problems == []


def test_the_scan_sees_bars_series_defined_outside_the_bars_package() -> None:
    """Neither probe comes from `candleviewer.bars`, and the gauge is not bound at module level:
    the namespace scan this replaced saw neither."""
    probes: list[MetricWrapperBase] = []
    names = {"bars_scan_probe_total", "bars_scan_probe_depth"}
    try:
        probes.append(Counter("bars_scan_probe_total", "A probe the scan must see."))
        probes.append(Gauge("bars_scan_probe_depth", "A probe the scan must see."))
        seen = _defined_bars_metrics().keys()
    finally:
        for probe in probes:
            REGISTRY.unregister(probe)
    assert names <= seen
    assert not names & _defined_bars_metrics().keys()  # unregistered again: nothing leaks


def test_write_and_read_series_caps_equal_their_closed_label_sets() -> None:
    caps = {s.name: s.max_series for s in CATALOGUE}
    tables = len(get_args(BarKind))  # one bars_<kind> table per bar kind
    refusals = {(a, b) for a in SOURCE_RANK for b in SOURCE_RANK if SOURCE_RANK[a] < SOURCE_RANK[b]}
    assert caps["bars_rows_written_total"] == tables
    assert caps["bars_symbol_cardinality"] == tables
    assert caps["bars_checksum_mismatch_total"] == tables * len(INTEGRITY_REASONS)
    assert caps["bars_write_failed_total"] == len(WRITE_FAILURE_REASONS)
    assert caps["bars_source_overwrite_refused_total"] == len(refusals)


def test_write_and_read_series_are_served_on_the_scraped_registry_with_env() -> None:
    m = Metrics("demo")
    collector = export_bars_metrics(m.registry, env="demo")
    try:
        # A labelled series has no sample until a child exists: `inc(0)` creates one and counts
        # nothing, so the process-wide counters other tests read keep their values.
        writer.bars_rows_written_total.labels("time").inc(0)
        writer.bars_write_failed_total.labels("permanent").inc(0)
        writer.bars_symbol_cardinality.labels("bars_time")
        writer.bars_source_overwrite_refused_total.labels("kline", "tape").inc(0)
        reader.bars_checksum_mismatch_total.labels("bars_time", "mismatch").inc(0)
        text = generate_latest(m.registry).decode()
    finally:
        collector.close()
    families = {f.name: f for f in text_string_to_metric_families(text)}
    for name in WRITE_AND_READ_PATH:
        family = families[name.removesuffix("_total")]
        assert f"# HELP {name} " in text, name
        assert family.documentation, name
        assert family.samples and all(s.labels["env"] == "demo" for s in family.samples), name
    # A scrape serves the code's HELP, not the catalogue's: for the saturation counter, which
    # counts rows, the two must say the same.
    saturation = next(s for s in CATALOGUE if s.name == "bars_write_saturation_total")
    assert f"# HELP bars_write_saturation_total {saturation.help}\n" in text
