"""Catalogue, exposition and fallback-snapshot tests (E04-T03)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re

import structlog
from prometheus_client import generate_latest
from prometheus_client.parser import text_string_to_metric_families

from candleviewer.observability.metrics import DISALLOWED_LABEL_NAMES, Metrics
from candleviewer.observability.metrics_catalogue import (
    CATALOGUE,
    FANOUT_BUCKETS,
    LOOP_LAG_BUCKETS,
    live_specs,
    register_r0,
    registered_specs,
)
from candleviewer.observability.metrics_runtime import (
    run_cardinality_check,
    run_fallback_snapshots,
    run_loop_lag_sampler,
)

#: `_ms`/`_mb`: frontend-pushed names fixed by 20-architecture.md §12.1 (E04-T06).
#: `_rows`: `recorder_write_backlog_rows`, named by E16-T03 (a gauge of queued rows).
_UNIT_SUFFIX = re.compile(r"_(seconds|bytes|total|depth|state|in_use|remaining|ms|mb|rows)$")

#: Golden: sha256 of the sorted (name, kind, labels, status, owner) catalogue.
#: Changing it requires updating 20-architecture.md §12.1 and dashboards/alerts.
GOLDEN_CATALOGUE_SHA256 = "41d2e0b7e5a93749bfb6398444fa31e66f0e26c3ed276cf60e73aeebe936ddb9"

_KNOWN_EPICS = re.compile(r"^E\d{2}(-[A-Z]\d{2})?$")


def _catalogue_digest() -> str:
    rows = sorted((s.name, s.kind, list(s.labels), s.status, s.owner_epic) for s in CATALOGUE)
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def test_catalogue_golden_snapshot_unchanged() -> None:
    assert _catalogue_digest() == GOLDEN_CATALOGUE_SHA256


def test_catalogue_names_are_unique_and_documented() -> None:
    names = [s.name for s in CATALOGUE]
    assert len(names) == len(set(names))
    for s in CATALOGUE:
        assert s.help and s.alert and s.unit


#: Count-valued gateway series whose names are fixed by the E17 tickets / 23-ws-protocol.md
#: (#377): the unit is the noun itself. Exactly these names; nothing else is exempt.
_UNIT_SUFFIX_EXEMPT = frozenset(
    {"cv_ws_clients", "cv_ws_topics_per_client", "cv_ws_upstream_refcount", "cv_ws_stale_topics"}
)


def test_catalogue_live_names_are_unit_suffixed() -> None:
    for s in live_specs():
        assert _UNIT_SUFFIX.search(s.name) or s.name in _UNIT_SUFFIX_EXEMPT, s.name


def test_catalogue_every_planned_entry_has_owning_epic() -> None:
    for s in CATALOGUE:
        if s.status == "planned":
            assert _KNOWN_EPICS.match(s.owner_epic), s.name


def test_catalogue_no_disallowed_label_names() -> None:
    for s in CATALOGUE:
        assert not {lbl.lower() for lbl in s.labels} & DISALLOWED_LABEL_NAMES, s.name


def test_catalogue_architecture_doc_lists_every_metric() -> None:
    from pathlib import Path

    doc = next(
        p / "docs/plan/20-architecture.md"
        for p in Path(__file__).resolve().parents
        if (p / "docs/plan/20-architecture.md").exists()
    ).read_text(encoding="utf-8")
    missing = [s.name for s in CATALOGUE if f"`{s.name}" not in doc]
    assert missing == []


def test_histogram_buckets_bracket_documented_budgets() -> None:
    assert 0.05 in LOOP_LAG_BUCKETS and 0.1 in LOOP_LAG_BUCKETS
    assert 0.02 in FANOUT_BUCKETS


def test_exposition_parses_and_every_live_metric_present_with_env_and_help() -> None:
    m = Metrics("demo", process_collectors=True)
    r = register_r0(m)
    r["ws_connection_state"].labels("public").set(1)
    r["ws_messages_total"].labels("publicTrade").inc()
    r["topic_staleness_seconds"].labels("orderbook.50").set(0.5)
    r["ingest_queue_depth"].labels("normalize").set(3)
    r["book_resync_total"].labels("BTCUSDT", "gap").inc()
    r["engine_process_seconds"].labels("footprint").observe(0.001)
    r["bybit_rate_remaining"].labels("order").set(10)
    r["ingest_stage_seconds"].labels("parse").observe(0.002)
    r["telemetry_rejected_total"].labels("invalid").inc()
    for fe in ("fe_frame_time_ms", "fe_ws_decode_ms"):
        r[fe].labels("R-100").observe(1.0)
    r["fe_dropped_frames_total"].labels("R-100").inc()
    r["fe_gpu_memory_mb"].labels("R-100").set(64)
    r["support_bundle_generations_total"].labels("ok").inc()
    text = generate_latest(m.registry).decode()
    families = {f.name: f for f in text_string_to_metric_families(text)}
    for spec in registered_specs():
        family_name = spec.name.removesuffix("_total")
        fam = families[family_name]
        assert fam.documentation, spec.name
        assert fam.samples and all(s.labels["env"] == "demo" for s in fam.samples), spec.name
        assert f"# HELP {spec.name} " in text


def test_labels_exercised_contain_no_personal_data() -> None:
    m = Metrics("live")
    register_r0(m)
    text = generate_latest(m.registry).decode()
    assert "@" not in text
    for fam in text_string_to_metric_families(text):
        for sample in fam.samples:
            assert not set(sample.labels) & DISALLOWED_LABEL_NAMES


async def _no_sleep(_: float) -> None:
    await asyncio.sleep(0)


def test_loop_lag_sampler_records_overshoot() -> None:
    t = [0.0]

    async def sleep(interval: float) -> None:
        t[0] += interval + 0.12

    m = Metrics("demo")
    h = register_r0(m)["event_loop_lag_seconds"]
    asyncio.run(run_loop_lag_sampler(h, lambda: t[0], sleep=sleep, iterations=3))
    snap = m.snapshot(["event_loop_lag_seconds"])
    assert snap["event_loop_lag_seconds_count"] == 3
    assert abs(snap["event_loop_lag_seconds_sum"] - 0.36) < 1e-9


def test_scrape_outage_of_10_minutes_leaves_two_fallback_snapshots() -> None:
    m = Metrics("demo")
    register_r0(m)["pg_pool_in_use"].child().set(4)
    elapsed = [0.0]

    async def sleep(interval: float) -> None:
        elapsed[0] += interval

    with structlog.testing.capture_logs() as logs:
        asyncio.run(run_fallback_snapshots(m, sleep=sleep, iterations=2))
    entries = [e for e in logs if e["event"] == "metrics_fallback_snapshot"]
    assert elapsed[0] == 600.0 and len(entries) >= 2
    assert entries[0]["metrics"]["pg_pool_in_use"] == 4.0


def test_cardinality_check_logs_breached_metrics() -> None:
    m = Metrics("demo")
    c = m.counter("x_total", "h", ("k",), max_series=1)
    c.labels("a")
    c.labels("b")
    with structlog.testing.capture_logs() as logs:
        asyncio.run(run_cardinality_check(m, sleep=_no_sleep, iterations=1))
    assert logs[-1]["event"] == "metric_cardinality_at_bound"
    assert logs[-1]["metrics"] == ["x_total"]


def test_exported_bars_metrics_served_on_app_registry_with_env() -> None:
    """E12-T03: the bars series are `live` via `export_bars_metrics`, not `register_r0`."""
    import candleviewer.bars.builder_set  # noqa: F401 - owns metric families (via its imports)
    from candleviewer.bars.metrics import EXPORTED_NAMES, export_bars_metrics
    from candleviewer.bars.time_builder import bars_built_total
    from candleviewer.recorder.metrics import EXPORTED_NAMES as RECORDER_NAMES
    from candleviewer.ws.metrics import CV_WS_NAMES
    from candleviewer.ws.metrics import EXPORTED_NAMES as CVWB_NAMES

    exported = (
        {s.name for s in live_specs() if s.exported} - CVWB_NAMES - RECORDER_NAMES - CV_WS_NAMES
    )
    assert exported == EXPORTED_NAMES
    m = Metrics("demo")
    register_r0(m)
    collector = export_bars_metrics(m.registry, env="demo")
    try:
        bars_built_total.labels(symbol="BTCUSDT", kind="time").inc()
        text = generate_latest(m.registry).decode()
        assert 'bars_built_total{env="demo",kind="time",symbol="BTCUSDT"}' in text
        # every exported bars family (all 14) is served on the scraped registry
        families = {f.name for f in text_string_to_metric_families(text)}
        missing = [n for n in sorted(EXPORTED_NAMES) if n.removesuffix("_total") not in families]
        assert missing == []
        for name in EXPORTED_NAMES:
            assert f"# HELP {name} " in text, name
    finally:
        collector.close()


def test_cvwb_encode_metrics_served_with_bounded_body_kind() -> None:
    from candleviewer.ws.binary import Frame, encode
    from candleviewer.ws.metrics import EXPORTED_NAMES, export_cvwb_metrics

    assert EXPORTED_NAMES <= {s.name for s in live_specs() if s.exported}
    m = Metrics("demo")
    register_r0(m)
    collector = export_cvwb_metrics(m.registry, env="demo")
    try:
        encode(Frame(4))
        text = generate_latest(m.registry).decode()
        assert 'cvwb_frames_encoded_total{env="demo",kind="bars"}' in text
        assert 'cvwb_bytes_encoded_total{env="demo",kind="bars"}' in text
    finally:
        collector.close()


def test_exported_recorder_metrics_served_with_env() -> None:
    """E16-T03: the StreamWriter series are `live`, served via `export_recorder_metrics`."""
    from candleviewer.recorder.metrics import (
        EXPORTED_NAMES,
        export_recorder_metrics,
        recorder_rows_total,
    )

    assert EXPORTED_NAMES <= {s.name for s in live_specs() if s.exported}
    m = Metrics("demo")
    register_r0(m)
    collector = export_recorder_metrics(m.registry, env="demo")
    try:
        recorder_rows_total.labels(stream="trades").inc()
        text = generate_latest(m.registry).decode()
        assert 'recorder_rows_total{env="demo",stream="trades"}' in text
        for name in EXPORTED_NAMES:
            assert f"# HELP {name} " in text, name
    finally:
        collector.close()
