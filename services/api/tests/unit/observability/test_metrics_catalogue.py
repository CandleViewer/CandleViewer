"""Catalogue, exposition and fallback-snapshot tests (E04-T03)."""

from __future__ import annotations

import asyncio
import json
import os
import re
import typing
from pathlib import Path

import structlog
from prometheus_client import generate_latest
from prometheus_client.parser import text_string_to_metric_families

from candleviewer.observability import metrics_catalogue
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
#: `_safe`: `net_binding_safe`, the 1/0 mesh-guard gauge named by E09-T04 (US-ONB-008).
#: `_events`: `auth_break_glass_unresolved_events`, a gauge of unresolved system events (#2496).
#: `_attempts`: `auth_break_glass_attempts`, a gauge of CLI runs on record in `audit_log` (#2496).
_UNIT_SUFFIX = re.compile(
    r"_(seconds|bytes|total|depth|state|in_use|remaining|ms|mb|rows|safe|events|attempts)$"
)
#: The samples a histogram serves beside its base name.
_SAMPLES = ("_bucket", "_count", "_sum")
#: Exact names fixed by the E16-T07 ticket (`disk_used_ratio` predates it in the alert rules), by
#: the E12-T02 ticket's Observability section (`bars_symbol_cardinality{table}`, #1998), by the
#: E42-T03 ticket's 1/0 order-gate gauge `cv_maintenance_mode`, and by E17-T06
#: (`cv_ws_connection_class`, a gauge per class; `cv_ws_queue_frames`, a histogram of frames).
#: `cv_ws_coalesced_updates`, a histogram of updates, is #412's ruling D6 name
#: `cv_ws_coalesced_count` without the `_count` end that a histogram may not have (see below).
_SUFFIX_EXCEPTIONS = frozenset(
    {
        "cv_keys_failing_policy",  # named by the E27-T03 ticket's Observability section (#836)
        "disk_used_ratio",
        "cv_maintenance_mode",
        "recorder_disk_pressure_level",
        "recorder_bytes_per_day",
        "recorder_projected_full_timestamp",
        "bars_symbol_cardinality",
        "cv_ws_connection_class",
        "cv_ws_coalesced_updates",
        "cv_ws_queue_frames",
    }
)

#: Golden: one JSON row per catalogue metric, `[name, kind, labels, status, owner]`, sorted and
#: compared as a set, so two PRs that add different metrics merge cleanly (#2743).
#: `CV_REGEN_GOLDEN=1` rewrites it. Changing a row means updating 20-architecture.md §12.1
#: (checked below) and the dashboards/alerts that use the metric.
GOLDEN_CATALOGUE = Path(__file__).with_name("golden") / "metrics_catalogue.jsonl"

_KNOWN_EPICS = re.compile(r"^E\d{2}(-[A-Z]\d{2})?$")


def _catalogue_rows() -> set[str]:
    return {json.dumps([s.name, s.kind, list(s.labels), s.status, s.owner_epic]) for s in CATALOGUE}


def test_catalogue_matches_golden_rows() -> None:
    rows = _catalogue_rows()
    if os.environ.get("CV_REGEN_GOLDEN") == "1":
        text = "".join(f"{row}\n" for row in sorted(rows))
        GOLDEN_CATALOGUE.write_text(text, encoding="utf-8", newline="\n")
    golden = GOLDEN_CATALOGUE.read_text(encoding="utf-8").splitlines()
    unreviewed, stale = sorted(rows - set(golden)), sorted(set(golden) - rows)
    assert (unreviewed, stale) == ([], []), "review, then rerun with CV_REGEN_GOLDEN=1"
    assert golden == sorted(set(golden)), "one sorted row per metric: rerun with CV_REGEN_GOLDEN=1"


def test_catalogue_names_are_unique_and_documented() -> None:
    names = [s.name for s in CATALOGUE]
    assert len(names) == len(set(names))
    for s in CATALOGUE:
        assert s.help and s.alert and s.unit


def test_catalogue_live_names_are_unit_suffixed() -> None:
    for s in live_specs():
        assert _UNIT_SUFFIX.search(s.name) or s.name in _SUFFIX_EXCEPTIONS, s.name


def test_catalogue_histogram_names_do_not_end_in_a_sample_suffix() -> None:
    """`_bucket`, `_count` and `_sum` are the samples a histogram serves. A base name that ends in
    one serves `x_count_count`, reads like a counter that has no samples (`increase(x_count[5m])`
    is empty) and names a family that a later `x` histogram could not register (E17-T06 review)."""
    ending = [s.name for s in CATALOGUE if s.kind == "histogram" and s.name.endswith(_SAMPLES)]
    assert ending == []


def test_catalogue_every_planned_entry_has_owning_epic() -> None:
    for s in CATALOGUE:
        if s.status == "planned":
            assert _KNOWN_EPICS.match(s.owner_epic), s.name


#: A section comment of the catalogue source, `# --- <title> ---`. The trailing dashes are optional:
#: the recorder headers have none, and a pattern that needed them let those two run into the section
#: above (#2319 review).
_SECTION_HEADER = re.compile(r"^[ \t]*# --- (.+?)(?: -+)?[ \t]*$", flags=re.MULTILINE)


def _sections(source: str) -> list[tuple[str, str]]:
    """(title, body) of each `# ---` section; the body runs to the next header or the end."""
    parts = _SECTION_HEADER.split(source)  # head, title, body, title, body, ...
    return list(zip(parts[1::2], parts[2::2], strict=True))


def test_catalogue_section_split_finds_every_header_comment() -> None:
    source = Path(metrics_catalogue.__file__).read_text(encoding="utf-8")
    headers = [line for line in source.splitlines() if line.lstrip().startswith("# --- ")]
    sections = _sections(source)
    assert headers  # the catalogue has section comments at all
    assert len(sections) == len(headers)
    for header, (title, _) in zip(headers, sections, strict=True):
        assert title in header, f"{header.strip()!r} was split as {title!r}"


def test_catalogue_planned_section_headers_only_cover_planned_entries() -> None:
    # A `# --- ... (planned) ---` comment reads as the status of its block; the SR-125 one went on
    # saying so after its auth series went live (#2319 review).
    source = Path(metrics_catalogue.__file__).read_text(encoding="utf-8")
    status = {spec.name: spec.status for spec in CATALOGUE}
    for title, body in _sections(source):
        live = [name for name in re.findall(r'_s\(\s*"(\w+)"', body) if status[name] != "planned"]
        assert "(planned)" not in title or not live, f"{title!r} heads live entries: {live}"


def test_catalogue_no_disallowed_label_names() -> None:
    for s in CATALOGUE:
        assert not {lbl.lower() for lbl in s.labels} & DISALLOWED_LABEL_NAMES, s.name


def _architecture_12_1_rows() -> list[tuple[list[str], list[str]]]:
    """(backticked names in the Metric cell, `/`-separated Type kinds) per §12.1 table row."""
    doc = next(
        p / "docs/plan/20-architecture.md"
        for p in Path(__file__).resolve().parents
        if (p / "docs/plan/20-architecture.md").exists()
    ).read_text(encoding="utf-8")
    rows: list[tuple[list[str], list[str]]] = []
    for line in doc[doc.index("### 12.1") : doc.index("### 12.2")].splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) == 4:  # Domain | Metric | Type | Purpose / alert
            names = re.findall(r"`([a-z][a-z0-9_:]+)(?:\{[^`]*\})?`", cells[1])
            rows.append((names, [kind.strip() for kind in cells[2].split("/")]))
    return rows


def test_catalogue_rows_are_documented_in_architecture_12_1() -> None:
    """A golden row change is a §12.1 change: every metric is in the table's Metric column, and
    its row's Type cell lists each metric's kind in order or, the other convention in use, the
    row's distinct kinds in order of first use (labels: test_architecture_doc_sync.py)."""
    kinds = {s.name: s.kind for s in CATALOGUE}
    rows = _architecture_12_1_rows()
    missing = sorted(kinds.keys() - {name for names, _ in rows for name in names})
    wrong_kind: list[str] = []
    for names, types in rows:
        row = [kinds.get(name) for name in names]  # None: a label value or uncatalogued name
        first_use = list(dict.fromkeys(kind for kind in row if kind))
        in_order = len(types) == len(row) and all(
            kind in (None, documented) for kind, documented in zip(row, types, strict=True)
        )
        if first_use and not in_order and types != first_use:
            wrong_kind.append(f"{', '.join(names)}: Type {'/'.join(types)}")
    assert (missing, wrong_kind) == ([], [])


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
    r["cv_accounts_rows"].labels("main").set(1)
    r["cv_api_keys_rows"].labels("active").set(1)
    r["cv_audit_verify_runs_total"].labels("ok").inc()
    r["cv_http_request_duration_seconds"].labels("/v1/x", "GET", "2xx").observe(0.01)
    r["cv_key_verification_total"].labels("failed", "key_expired").inc()
    r["cv_key_selfcheck_runs_total"].labels("failed").inc()
    r["cv_keys_failing_policy"].labels("key_expired").set(1)
    text = generate_latest(m.registry).decode()
    families = {f.name: f for f in text_string_to_metric_families(text)}
    for spec in registered_specs():
        family_name = spec.name.removesuffix("_total")
        fam = families[family_name]
        assert fam.documentation, spec.name
        assert fam.samples and all(s.labels["env"] == "demo" for s in fam.samples), spec.name
        assert f"# HELP {spec.name} " in text


def test_account_row_gauges_are_live_and_bounded_by_their_enums() -> None:
    """#2314: one series per closed-enum value; `env` is the facade's process environment."""
    from candleviewer.accounts.models import AccountKind, KeyStatus

    specs = {s.name: s for s in registered_specs()}
    rows, keys = specs["cv_accounts_rows"], specs["cv_api_keys_rows"]
    assert (rows.kind, rows.labels, rows.max_series) == ("gauge", ("kind",), len(AccountKind))
    assert (keys.kind, keys.labels, keys.max_series) == ("gauge", ("state",), len(KeyStatus))
    assert rows.owner_epic == keys.owner_epic == "E27"


def test_key_selfcheck_series_are_bounded_by_their_closed_sets() -> None:
    """E27-T03 (#836): `rule` is the verification `Rule` enum (plus `none`), `result` a closed
    set; the age, missed-run and expiry series carry no label at all (decision 13)."""
    from candleviewer.accounts.verification import Rule

    specs = {s.name: (s.labels, s.max_series) for s in registered_specs()}
    assert specs["cv_key_verification_total"] == (("result", "rule"), len(Rule) + 2)
    assert specs["cv_keys_failing_policy"] == (("rule",), len(Rule))
    assert specs["cv_key_selfcheck_runs_total"] == (("result",), 4)
    single = ("verification_seconds", "verification_age_seconds", "soonest_expiry_seconds")
    assert {specs[f"cv_key_{n}"] for n in (*single, "selfcheck_missed_runs_total")} == {((), 1)}


def test_wallet_sizing_counter_is_live_and_carries_no_label() -> None:
    """E27-T04 (#837, Option B): decisions taken on a snapshot older than the reconciliation
    period. No account, balance or verdict in a label: the log line says which account."""
    spec = next(s for s in registered_specs() if s.name == "cv_wallet_sizing_old_snapshot_total")
    assert (spec.kind, spec.labels, spec.max_series, spec.owner_epic) == ("counter", (), 1, "E27")


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
    from candleviewer.admin.flags.metrics import EXPORTED_NAMES as FLAG_NAMES
    from candleviewer.admin.lifecycle_metrics import EXPORTED_NAMES as LIFECYCLE_NAMES
    from candleviewer.auth.metrics import AUTH_EXPORTED_NAMES
    from candleviewer.bars import reader, writer  # noqa: F401 - the write and read path (#1998)
    from candleviewer.bars.metrics import EXPORTED_NAMES, export_bars_metrics
    from candleviewer.bars.time_builder import bars_built_total
    from candleviewer.net.metrics import NET_EXPORTED_NAMES
    from candleviewer.observability.audit_query_metrics import EXPORTED_NAMES as AUDIT_NAMES
    from candleviewer.recorder.metrics import EXPORTED_NAMES as RECORDER_NAMES
    from candleviewer.secrets.metrics import EXPORTED_NAMES as SECRETS_NAMES
    from candleviewer.ws.metrics import CV_WS_NAMES
    from candleviewer.ws.metrics import EXPORTED_NAMES as CVWB_NAMES

    others = (
        CVWB_NAMES
        | RECORDER_NAMES
        | CV_WS_NAMES
        | AUTH_EXPORTED_NAMES
        | SECRETS_NAMES
        | NET_EXPORTED_NAMES
    )
    others |= FLAG_NAMES
    assert FLAG_NAMES <= {s.name for s in live_specs() if s.exported}
    others |= AUDIT_NAMES
    others |= LIFECYCLE_NAMES
    exported = {s.name for s in live_specs() if s.exported} - others
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


def test_exported_secrets_metrics_served_on_app_registry_with_env() -> None:
    """E27-T02: every M2 series is served on the scraped registry with `env`."""
    from candleviewer.secrets import _metrics as sm
    from candleviewer.secrets.metrics import EXPORTED_NAMES, export_secrets_metrics

    m = Metrics("demo")
    collector = export_secrets_metrics(m.registry, env="demo")
    try:
        sm.kek_load_failures_total.labels(reason="kek_unavailable").inc(0)
        sm.credential_borrow_total.labels(stage="t", result="ok").inc(0)
        text = generate_latest(m.registry).decode()
        for name in EXPORTED_NAMES:
            assert f"# HELP {name} " in text, name
        assert 'cv_kek_load_failures_total{env="demo",reason="kek_unavailable"}' in text
        catalogued = {s.name for s in live_specs() if s.exported}
        assert EXPORTED_NAMES <= catalogued  # every exported M2 series is catalogued
    finally:
        collector.close()


def test_drawings_rows_catalogue_cap_equals_the_closed_tool_set() -> None:
    """`cv_drawings_rows{tool}` is capped at the closed TOOLS set; app.py uses len(TOOLS)."""
    from candleviewer.api.drawings_models import TOOLS

    spec = next(s for s in CATALOGUE if s.name == "cv_drawings_rows")
    assert spec.max_series == len(TOOLS)


def test_workspaces_catalogue_caps_equal_the_closed_label_sets() -> None:
    """The E15-T01 label sets are closed; app.py derives each cap from the same constants."""
    from candleviewer.api.workspaces import OPERATIONS
    from candleviewer.storage.retention.workspaces_tasks import KINDS, USER_BUCKETS

    caps = {s.name: s.max_series for s in CATALOGUE}
    assert caps["cv_workspace_users"] == len(USER_BUCKETS)
    assert caps["cv_workspaces_purged_total"] == caps["cv_workspace_conflicts_total"] == len(KINDS)
    assert caps["cv_workspace_request_seconds"] == len(OPERATIONS)
    panes = next(s for s in CATALOGUE if s.name == "cv_layout_panes")
    assert panes.buckets == (0, 1, 2, 4, 8, 12, 16)


def test_exported_audit_query_metrics_served_with_env_and_closed_labels() -> None:
    """E42-T02: the audit read-path series are catalogued, served with `env`, and labelled
    only by closed sets."""
    from candleviewer.observability import audit_query_metrics as aq

    assert aq.EXPORTED_NAMES <= {s.name for s in live_specs() if s.exported}
    spec = {s.name: s for s in CATALOGUE}["cv_audit_query_duration_seconds"]
    assert spec.max_series == len(aq.FILTER_CLASSES)
    m = Metrics("demo")
    collector = aq.export_audit_query_metrics(m.registry, env="demo")
    try:
        aq.cv_audit_query_timeouts_total.labels("pool").inc(0)
        aq.cv_audit_query_duration_seconds.labels("none").observe(0)
        text = generate_latest(m.registry).decode()
        for name in aq.EXPORTED_NAMES:
            assert f"# HELP {name} " in text, name
        assert 'cv_audit_query_timeouts_total{cause="pool",env="demo"}' in text
    finally:
        collector.close()


def test_user_lifecycle_caps_and_help_cover_the_writers_closed_sets() -> None:
    """E42-T04 (#965 R7): the label values are closed sets fixed by their writers: the cascade's
    steps (`admin/user_disable.py`, its closing record too) and the grants push
    (`admin/account_access.py`, #2648: `pushed`, `timeout`, `failed`). Each cap is the size of its
    sets and each help names every value, for the dashboard and alert authors who read it."""
    from candleviewer.admin import account_access, user_disable
    from candleviewer.admin import lifecycle_metrics as lm

    push = lm.STEP_OUTCOMES[account_access.PUSH_STEP]
    assert push == ("pushed", "timeout", "failed")
    assert typing.get_args(typing.get_type_hints(account_access._pushed)["outcome"]) == push
    cascade = [step for step in lm.STEP_OUTCOMES if step != account_access.PUSH_STEP]
    assert cascade == [*user_disable.STEPS, "closing_record"]
    specs = {s.name: s for s in CATALOGUE}
    for name, sets in (
        ("cv_user_lifecycle_total", lm.ACTION_RESULTS),
        ("cv_user_lifecycle_steps_total", lm.STEP_OUTCOMES),
    ):
        assert specs[name].max_series == sum(map(len, sets.values())), name
        named = {*sets, *(value for values in sets.values() for value in values)}
        assert named <= set(re.findall(r"\w+", specs[name].help)), name


def test_user_lifecycle_series_are_bound_at_import_and_served_with_env() -> None:
    """#965 R7: every value of the closed sets exists from import, so a first failure is an
    `increase()` the tickets can see; the export serves each with `env`, and so does the app."""
    from candleviewer.admin import lifecycle_metrics as lm
    from candleviewer.app import create_app
    from candleviewer.settings import Environment, Settings

    m = Metrics("demo")
    collector = lm.export_user_lifecycle_metrics(m.registry, env="demo")
    try:
        text = generate_latest(m.registry).decode()
    finally:
        collector.close()
    for k, values in lm.ACTION_RESULTS.items():
        for v in values:
            assert f'cv_user_lifecycle_total{{action="{k}",env="demo",result="{v}"}} ' in text
    for k, values in lm.STEP_OUTCOMES.items():
        for v in values:
            assert f'cv_user_lifecycle_steps_total{{env="demo",outcome="{v}",step="{k}"}} ' in text
    app = create_app(Settings(environment=Environment.DEMO))
    scraped = generate_latest(app.state.app_context.metrics).decode()
    assert all(f"# HELP {name} " in scraped for name in lm.EXPORTED_NAMES)


def test_user_lifecycle_binding_leaves_no_loop_names_in_the_module() -> None:
    """The import-time binding runs in a private function, so the namespace that `app.py` and
    both writers import holds the declarations and helpers only, not the loops' variables."""
    from candleviewer.admin import lifecycle_metrics as lm

    loop_names = {"_action", "_results", "_result", "_step", "_outcomes", "_outcome"}
    assert not loop_names & vars(lm).keys()
