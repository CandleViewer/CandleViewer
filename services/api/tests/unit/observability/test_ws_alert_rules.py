"""E17-T06 (#571): the WS gateway alert rules, tied to the metrics catalogue and to the code.

`infra/prometheus/tests/ws_alerts.test.yml` (promtool, run by CI) proves what each rule fires on.
These tests prove what no promtool case can: every series and label an expression reads is a live,
catalogued one with a real value, the minimum-rate floor still matches the sampling period in the
code, the `for`, windows and thresholds are the ones the ticket and 23-ws-protocol.md section 16.3
state, each alert has its runbook and its place in the docs, and the dashboard row plots only series
that exist. No PromQL is evaluated here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml

from candleviewer.observability.metrics_catalogue import CATALOGUE, FANOUT_BUCKETS, MetricSpec
from candleviewer.ws.lifecycle import CLOSE_REASONS
from candleviewer.ws.metrics import SAMPLE_EVERY
from candleviewer.ws.sequencing import SNAP_REASONS

_ROOT = Path(__file__).resolve().parents[5]
_ALERTS = _ROOT / "infra" / "prometheus" / "alerts"
_PROMTOOL = _ROOT / "infra" / "prometheus" / "tests" / "ws_alerts.test.yml"
_CI = _ROOT / ".github" / "workflows" / "_job-py.yml"
_PRR = _ROOT / "docs" / "plan" / "07-release-and-prr.md"
_ARCH = _ROOT / "docs" / "plan" / "20-architecture.md"
_MARKET = _ROOT / "infra" / "grafana" / "dashboards" / "market-data.json"
_MATRIX = _ROOT / "qa" / "plans" / "e04-alert-drill-matrix.md"

#: The ticket's four alerts and their E04 severity (`20-architecture.md` 12.5: warning = ticket,
#: critical = page). The ticket calls the gap alert critical; it is a ticket because its counter
#: is a client report the server does not verify, and a page would also inhibit the other three.
SEVERITY = {
    "WsFanoutP95OverBudget": "ticket",
    "WsUpstreamDesyncHigh": "ticket",
    "WsSlowConsumerClosed": "ticket",
    "WsSequenceGapDetected": "ticket",
}
#: The `for` each alert holds before it fires: five minutes for the p95 (the ticket's "for 5
#: minutes") and for the hour's desync count; a slow-consumer close and a reported gap are events,
#: so none.
FOR = {
    "WsFanoutP95OverBudget": "5m",
    "WsUpstreamDesyncHigh": "5m",
    "WsSlowConsumerClosed": None,
    "WsSequenceGapDetected": None,
}
#: `keep_firing_for` of the two any-event tickets: Alertmanager mutes tickets 22:00-07:00 UTC, so a
#: ticket that clears inside it is never sent; each is held past the 9 h mute instead.
HOLD = {"WsSlowConsumerClosed": "9h30m", "WsSequenceGapDetected": "9h30m"}
#: The counter each event alert reads, its window and its line (`> line`): above 5 `upstream_desync`
#: re-snapshots in an hour (23-ws-protocol.md 16.3), any `slow_consumer` close in 15 minutes, any
#: client-reported gap in 10.
COUNTER_LINES = {
    "WsUpstreamDesyncHigh": ('cv_ws_resync_total{reason="upstream_desync"}', "1h", 5),
    "WsSlowConsumerClosed": ('cv_ws_closes_total{reason="slow_consumer"}', "15m", 0),
    "WsSequenceGapDetected": ("cv_ws_sequence_gaps_detected_total", "10m", 0),
}
#: Policy: sampled frames the p95 alert needs in its 5 m window before it judges (rule comment).
FANOUT_MIN_SAMPLES = 40
WS_ROW = "WS gateway (client sockets)"
#: The four series the row plots, in panel order: connections, fan-out, resyncs, closes.
WS_SERIES = (
    "cv_ws_connections_in_use",
    "cv_ws_fanout_seconds",
    "cv_ws_resync_total",
    "cv_ws_closes_total",
)
#: Closed values of the `reason` label each alert may name, from the code that increments it.
_REASONS = {
    "cv_ws_closes_total": frozenset((*CLOSE_REASONS, "other")),
    "cv_ws_resync_total": frozenset(r for r in SNAP_REASONS if r != "initial"),
}
_SERIES = re.compile(r"\bcv_ws_[a-z0-9_]+\b")
_IDENT = re.compile(r"[A-Za-z_]\w*")
_SELECTOR = re.compile(r"(?P<name>cv_ws_[a-z0-9_]+)\s*\{(?P<body>[^}]*)\}")
_MATCHER = re.compile(r'(?P<label>[a-zA-Z_]\w*)\s*(?P<op>=~|!~|!=|=)\s*"(?P<value>[^"]*)"')
_GROUPING = re.compile(r"\b(?:by|on|without|ignoring)\s*\(([^)]*)\)")
_BY_NAME: Mapping[str, MetricSpec] = {s.name: s for s in CATALOGUE}


def _load(path: Path) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc


def _alerts() -> dict[str, dict[str, Any]]:
    doc = _load(_ALERTS / "ws_gateway.yml")
    return {r["alert"]: r for g in doc["groups"] for r in g["rules"] if "alert" in r}


def _expr(rule: Mapping[str, Any]) -> str:
    return " ".join(str(rule["expr"]).split())


def _base(series: str) -> str:
    """The catalogued name behind a series: a histogram's `_bucket`/`_count`/`_sum` fold back."""
    stem = re.sub(r"_(?:bucket|count|sum)$", "", series)
    return stem if stem in _BY_NAME and _BY_NAME[stem].kind == "histogram" else series


def test_the_file_holds_exactly_the_four_ticket_alerts() -> None:
    assert set(_alerts()) == set(SEVERITY)


def test_each_alert_has_its_severity_the_gateway_component_and_text() -> None:
    for name, rule in _alerts().items():
        assert rule["labels"] == {"severity": SEVERITY[name], "component": "gateway"}, name
        assert {"summary", "description", "runbook_url"} <= set(rule["annotations"]), name


def test_each_expression_reads_only_live_catalogued_series_and_labels() -> None:
    for name, rule in _alerts().items():
        expr = _expr(rule)
        series = set(_SERIES.findall(expr))
        assert series, name
        for s in series:
            spec = _BY_NAME.get(_base(s))
            assert spec is not None, f"{name}: {s} is not in the metrics catalogue"
            assert spec.status == "live", f"{name}: {spec.name} is only planned"
        for sel in _SELECTOR.finditer(expr):
            spec = _BY_NAME[_base(sel["name"])]
            for m in _MATCHER.finditer(sel["body"]):
                assert m["label"] in {*spec.labels, "le"}, f"{name}: {m['label']} on {spec.name}"
                if m["op"] == "=" and m["label"] == "reason":
                    assert m["value"] in _REASONS[spec.name], f"{name}: {m['value']}"
        for grouping in _GROUPING.findall(expr):
            kept = {x.strip() for x in grouping.split(",") if x.strip()}
            assert kept <= {"env", "le"}, f"{name}: groups by {sorted(kept)}"


def test_the_fanout_floor_is_forty_sampled_frames_at_the_sampling_weight() -> None:
    expr = _expr(_alerts()["WsFanoutP95OverBudget"])
    window = re.search(r"rate\(cv_ws_fanout_seconds_bucket\[(\w+)\]\)", expr)
    floor = re.search(r"increase\(cv_ws_fanout_seconds_count\[(\w+)\]\)\) >= (\d+)", expr)
    assert window and floor and window[1] == floor[1] == "5m"
    assert int(floor[2]) == FANOUT_MIN_SAMPLES * SAMPLE_EVERY


def test_the_budget_line_is_a_fanout_bucket_edge_and_the_quantile_is_the_p95() -> None:
    assert 0.02 in FANOUT_BUCKETS
    expr = _expr(_alerts()["WsFanoutP95OverBudget"])
    assert expr.startswith("histogram_quantile(0.95, ") and ") > 0.02 and on (env) " in expr


def test_each_alert_holds_for_the_duration_the_ticket_names() -> None:
    assert {name: rule.get("for") for name, rule in _alerts().items()} == FOR


def test_only_the_any_event_tickets_are_held_firing_past_the_nine_hour_mute() -> None:
    held = {name: rule.get("keep_firing_for") for name, rule in _alerts().items()}
    assert held == {name: HOLD.get(name) for name in SEVERITY}


@pytest.mark.parametrize("name", sorted(COUNTER_LINES))
def test_each_counter_alert_reads_its_window_and_fires_above_its_line(name: str) -> None:
    series, window, line = COUNTER_LINES[name]
    expr = _expr(_alerts()[name]).removeprefix("round(")
    found = re.fullmatch(
        rf"sum by \(env\) \(increase\({re.escape(series)}\[(\w+)\]\)\)\)? > (\d+)", expr
    )
    assert found, expr
    assert (found[1], int(found[2])) == (window, line)


def test_the_desync_alert_rounds_the_extrapolated_count() -> None:
    """`increase()` extrapolates to the window edges: five events read 5.08, so `> 5` fires."""
    assert _expr(_alerts()["WsUpstreamDesyncHigh"]).startswith("round(")


def test_budget_6_burn_rates_read_the_gateway_series_not_the_ingestion_stage() -> None:
    doc = _load(_ALERTS / "latency_budget.yml")
    rules = {r["record"]: r for g in doc["groups"] for r in g["rules"] if "record" in r}
    for window in ("1h", "6h"):
        expr = _expr(rules[f"cv:slo_backend_fanout:burn_rate_{window}"])
        assert 'cv_ws_fanout_seconds_bucket{le="0.02"}' in expr, window
        assert f"cv_ws_fanout_seconds_count[{window}]" in expr, window
        assert "ingest_stage_seconds" not in expr, window
    # The per-stage attribution still reads every ingestion stage, `fanout` included.
    assert "ingest_stage_seconds_bucket" in _expr(rules["cv:ingest_stage_seconds:p95_5m"])


def test_each_alert_links_a_runbook_section_named_after_it() -> None:
    prr = _PRR.read_text(encoding="utf-8")
    for name, rule in _alerts().items():
        anchor = f"alert-{name.lower()}"
        assert rule["annotations"]["runbook_url"] == f"docs/plan/07-release-and-prr.md#{anchor}"
        assert f'<a id="{anchor}"></a>\n\n### {name}\n' in prr, name


def test_each_runbook_states_the_alerts_severity() -> None:
    prr = _PRR.read_text(encoding="utf-8")
    for name, rule in _alerts().items():
        section = prr[prr.index(f'<a id="alert-{name.lower()}"></a>') :]
        row = next(r for r in section.splitlines() if r.startswith("| 1. What fired"))
        severity = rule["labels"]["severity"]
        assert severity.capitalize() in row, name
        assert ("Page" in row) == (severity == "page"), name


def test_the_drill_matrix_row_states_the_rules_severity_and_for() -> None:
    matrix = _MATRIX.read_text(encoding="utf-8")
    for name, rule in _alerts().items():
        row = rf"^\| {name} \| {rule['labels']['severity']} \| {rule.get('for', '0m')} \|"
        assert re.search(row, matrix, re.M), name


def test_promtool_covers_each_alert_firing_and_quiet_and_ci_runs_the_file() -> None:
    doc = _load(_PROMTOOL)
    assert "../alerts/ws_gateway.yml" in doc["rule_files"]
    firing: set[str] = set()
    quiet: set[str] = set()
    for case in doc["tests"]:
        for check in case.get("alert_rule_test", []):
            (firing if check["exp_alerts"] else quiet).add(check["alertname"])
    assert set(SEVERITY) <= firing and set(SEVERITY) <= quiet
    assert "/p/tests/ws_alerts.test.yml" in _CI.read_text(encoding="utf-8")


def test_the_catalogue_names_the_alert_that_reads_each_series() -> None:
    reader = {
        "WsFanoutP95OverBudget": "cv_ws_fanout_seconds",
        "WsUpstreamDesyncHigh": "cv_ws_resync_total",
        "WsSlowConsumerClosed": "cv_ws_closes_total",
        "WsSequenceGapDetected": "cv_ws_sequence_gaps_detected_total",
    }
    assert set(reader) == set(SEVERITY)
    for alert, metric in reader.items():
        assert alert in _BY_NAME[metric].alert, metric
        assert f"({SEVERITY[alert]})" in _BY_NAME[metric].alert, metric
        assert metric in _expr(_alerts()[alert]), alert


def test_the_architecture_doc_lists_each_alert_in_the_alert_policy() -> None:
    text = _ARCH.read_text(encoding="utf-8")
    policy = text[text.index("### 12.5 Alert policy") :]
    policy = policy[: policy.index("\n---\n")]
    assert [n for n in SEVERITY if n not in policy] == []


def test_the_architecture_doc_states_the_ws_set_with_the_rules_severities() -> None:
    text = _ARCH.read_text(encoding="utf-8")
    paragraph = text[text.index("WS gateway set (E17-T06") :].split("\n\n")[0]
    assert "Ticket (warning)" in paragraph
    assert ("Page (critical)" in paragraph) == ("page" in SEVERITY.values())


def _ws_row() -> list[dict[str, Any]]:
    """The panels under the WS gateway row of Market data."""
    row: list[dict[str, Any]] = []
    in_row = False
    for panel in json.loads(_MARKET.read_text(encoding="utf-8"))["panels"]:
        if panel["type"] == "row":
            in_row = panel["title"] == WS_ROW
        elif in_row:
            row.append(panel)
    assert row, f"no panels under the {WS_ROW!r} row"
    return row


def _plotting(series: str) -> dict[str, Any]:
    """The WS row panel that plots `series`."""
    panel = next((p for p in _ws_row() if series in p["targets"][0]["expr"]), None)
    assert panel is not None, f"no panel in the WS row plots {series}"
    return panel


def _steps(panel: Mapping[str, Any]) -> set[float]:
    """The threshold values of a panel (its base step has none)."""
    steps = panel["fieldConfig"]["defaults"]["thresholds"]["steps"]
    return {s["value"] for s in steps if s["value"] is not None}


def test_the_ws_row_plots_the_four_series_live_and_groups_by_reason_only() -> None:
    exprs = [t["expr"] for panel in _ws_row() for t in panel["targets"]]
    # Every catalogued name the queries mention, whatever its prefix: a planned one would be an
    # empty panel that reads healthy.
    plotted = {_base(i) for e in exprs for i in _IDENT.findall(e) if _base(i) in _BY_NAME}
    assert plotted == set(WS_SERIES)
    assert [n for n in sorted(plotted) if _BY_NAME[n].status != "live"] == []
    grouped = {x.strip() for e in exprs for g in _GROUPING.findall(e) for x in g.split(",")}
    assert grouped <= {"reason", "le"}


def test_the_ws_row_queries_keep_their_shape() -> None:
    """Byte equality with the generator passes whatever the generator says, so pin the shapes: a
    regenerated row that drops `round()` would read five events as 5.08 and cross the 5 line."""
    exprs = {s: _plotting(s)["targets"][0]["expr"] for s in WS_SERIES}
    assert exprs["cv_ws_connections_in_use"] == 'sum(cv_ws_connections_in_use{env="$env"})'
    assert re.fullmatch(
        r"histogram_quantile\(0\.95, sum by \(le\) \(rate\(cv_ws_fanout_seconds_bucket"
        r'\{env="\$env"\}\[\$__rate_interval\]\)\)\)',
        exprs["cv_ws_fanout_seconds"],
    )
    for series in ("cv_ws_resync_total", "cv_ws_closes_total"):  # whole events, as the alert rounds
        assert re.fullmatch(
            rf'round\(sum by \(reason\) \(increase\({series}\{{env="\$env"\}}\[\$__range\]\)\)\)',
            exprs[series],
        ), series


def test_the_ws_row_draws_the_budget_and_resync_lines() -> None:
    connections, fanout, resync, closes = (_plotting(s) for s in WS_SERIES)
    units = [p["fieldConfig"]["defaults"]["unit"] for p in (connections, fanout, resync, closes)]
    assert units == ["short", "s", "short", "short"]
    assert _steps(fanout) == {0.02}  # the 20 ms budget line (06 section 2), and no other
    assert _steps(resync) == {1, 5}  # 23-ws-protocol.md 16.3: target under 1 an hour, hard fail 5
    assert _steps(closes) == set()
    for panel in (fanout, resync):  # a timeseries draws its thresholds only when asked
        style = panel["fieldConfig"]["defaults"]["custom"]["thresholdsStyle"]["mode"]
        assert style in {"line", "dashed"}, panel["title"]
    assert "lines: 1 and 5" in resync["title"]  # the title names the lines, so colour is not alone


def test_the_ws_row_says_what_its_panels_do_not_show() -> None:
    _, fanout, resync, closes = (_plotting(s) for s in WS_SERIES)
    assert "sampled 1 in 32" in fanout["description"]
    assert "Only client_resync and reconfigure have a trigger today" in resync["description"]
    assert "flat zero here is not coverage" in resync["description"]
    assert "zero whatever happens" in closes["description"]
