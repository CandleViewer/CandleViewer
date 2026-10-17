"""Generate the seven provisioned Grafana dashboards (E04-S01, ADR-0014 section 3).

The committed JSON in ``infra/grafana/dashboards`` is the reviewed artefact; this
generator keeps it deterministic (no volatile ``id``/``version``). Re-run with
``python infra/grafana/generate_dashboards.py`` after editing panels.
Thresholds come from docs/plan/06-performance-and-load-standard.md section 2.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DS = {"type": "prometheus", "uid": "cv-prometheus"}
OUT = Path(__file__).resolve().parent / "dashboards"
E = 'env="$env"'
# Colour-blind-safe palette (Okabe-Ito): blue ok / orange warn / vermillion bad.
# State is always also shown as a numeric stat value, never colour alone.
OK, WARN, BAD = "#0072B2", "#E69F00", "#D55E00"
RI = "$__rate_interval"


def _th(warn: float | None, bad: float | None) -> dict[str, Any]:
    steps: list[dict[str, Any]] = [{"color": OK, "value": None}]
    if warn is not None:
        steps.append({"color": WARN, "value": warn})
    if bad is not None:
        steps.append({"color": BAD, "value": bad})
    return {"mode": "absolute", "steps": steps}


class Board:
    def __init__(self, uid: str, title: str, tags: list[str]) -> None:
        self.uid, self.title, self.tags = uid, title, tags
        self.panels: list[dict[str, Any]] = []
        self.y = 0
        self.x = 0
        self._id = 0
        self._id += 1
        self.panels.append(
            {
                "id": self._id,
                "type": "text",
                "title": "Environment",
                "gridPos": {"h": 3, "w": 24, "x": 0, "y": 0},
                "options": {
                    "mode": "markdown",
                    "content": f"## {title} - env = **$env**",
                },
            }
        )
        self.y = 3

    def row(self, title: str) -> None:
        self.flush()
        self._id += 1
        self.panels.append(
            {
                "id": self._id,
                "type": "row",
                "title": title,
                "collapsed": False,
                "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.y},
                "panels": [],
            }
        )
        self.y += 1

    def _add(
        self,
        kind: str,
        title: str,
        expr: str,
        unit: str,
        w: int,
        h: int,
        warn: float | None,
        bad: float | None,
        legend: str,
    ) -> dict[str, Any]:
        self._id += 1
        p: dict[str, Any] = {
            "id": self._id,
            "type": kind,
            "title": title,
            "datasource": DS,
            "gridPos": {"h": h, "w": w, "x": self.x, "y": self.y},
            "maxDataPoints": 500,
            "fieldConfig": {
                "defaults": {"unit": unit, "thresholds": _th(warn, bad)},
                "overrides": [],
            },
            "targets": [{"refId": "A", "datasource": DS, "expr": expr, "legendFormat": legend}],
        }
        self.panels.append(p)
        self.x += w
        if self.x >= 24:
            self.x, self.y = 0, self.y + h
        return p

    def ts(
        self,
        title: str,
        expr: str,
        unit: str,
        warn: float | None = None,
        bad: float | None = None,
        legend: str = "",
    ) -> None:
        self._add("timeseries", title, expr, unit, 12, 7, warn, bad, legend)

    def stat(
        self,
        title: str,
        expr: str,
        unit: str,
        warn: float | None = None,
        bad: float | None = None,
        legend: str = "",
    ) -> None:
        p = self._add("stat", title, expr, unit, 6, 4, warn, bad, legend)
        p["options"] = {
            "colorMode": "background",
            "graphMode": "none",
            "textMode": "value_and_name",
        }

    def flush(self) -> None:
        if self.x:
            self.x, self.y = 0, self.y + 7

    def build(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "title": self.title,
            "tags": ["candleviewer", *self.tags],
            "schemaVersion": 39,
            "editable": False,
            "timezone": "utc",
            "refresh": "30s",
            "time": {"from": "now-1h", "to": "now"},
            "annotations": {
                "list": [
                    {
                        "name": "Deploys",
                        "enable": True,
                        "datasource": DS,
                        "expr": f"changes(build_info{{{E}}}[{RI}]) > 0",
                        "titleFormat": "deploy",
                        "tagKeys": "version,commit",
                        "iconColor": OK,
                    }
                ]
            },
            "templating": {
                "list": [
                    {
                        "name": "env",
                        "label": "env",
                        "type": "query",
                        "datasource": DS,
                        "query": {
                            "query": "label_values(build_info, env)",
                            "refId": "env",
                        },
                        "refresh": 2,
                        "sort": 1,
                        "includeAll": False,
                        "multi": False,
                        "current": {"text": "demo", "value": "demo"},
                    }
                ]
            },
            "panels": self.panels,
        }


def q(m: str, by: str = "", pct: str = "0.95") -> str:
    g = f"le, {by}" if by else "le"
    return f"histogram_quantile({pct}, sum by ({g}) (rate({m}_bucket{{{E}}}[{RI}])))"


def rate(m: str, by: str = "", extra: str = "") -> str:
    inner = f"rate({m}{{{E}{extra}}}[{RI}])"
    return f"sum by ({by}) ({inner})" if by else inner


def _describe(b: Board, text: str) -> None:
    """Give the panel just added a description (a hover note, so it never competes with data)."""
    b.panels[-1]["description"] = text


def _threshold_lines(b: Board) -> None:
    """Draw the threshold steps of the panel just added as dashed lines. A timeseries panel shows
    them only when asked (its default is off), and "against the 20 ms line" needs the line."""
    custom = b.panels[-1]["fieldConfig"]["defaults"].setdefault("custom", {})
    custom["thresholdsStyle"] = {"mode": "dashed"}


def system() -> Board:
    b = Board("cv-system-health", "CV / System health", ["system"])
    b.row("Getting worse? (SLO burn)")
    b.stat(
        "Loop lag p99 (budget 50 ms)",
        q("event_loop_lag_seconds", pct="0.99"),
        "s",
        0.05,
        0.1,
    )
    over = (
        f'1 - (sum(rate(event_loop_lag_seconds_bucket{{{E},le="0.1"}}[{RI}])) / '
        f"sum(rate(event_loop_lag_seconds_count{{{E}}}[{RI}])))"
    )
    b.stat("Loop lag > 100 ms fraction", over, "percentunit", 0.01, 0.05)
    b.row("Runtime")
    b.ts("Event loop lag p99", q("event_loop_lag_seconds", pct="0.99"), "s", 0.05, 0.1)
    b.ts("CPU", f"rate(process_cpu_seconds_total{{{E}}}[{RI}])", "percentunit")
    b.ts("RAM (RSS)", f"process_resident_memory_bytes{{{E}}}", "bytes")
    b.ts(
        "WS connection state (1=up)",
        f"ws_connection_state{{{E}}}",
        "short",
        legend="{{socket}}",
    )
    b.ts("Topic staleness", f"topic_staleness_seconds{{{E}}}", "s", 5, 15, "{{topic}}")
    b.ts("Ingest queue depth", f"ingest_queue_depth{{{E}}}", "short", legend="{{stage}}")
    b.row("Component health and observability stack")
    b.ts(
        "health_component_state (0=ok, higher=worse)",
        f"health_component_state{{{E}}}",
        "short",
        1,
        2,
        "{{component}}",
    )
    b.ts("Build info", f"build_info{{{E}}}", "short", legend="{{version}} {{commit}}")
    b.ts(
        "Prometheus rule group duration",
        "prometheus_rule_group_last_duration_seconds",
        "s",
    )
    b.ts(
        "Alertmanager failed notifications",
        f"rate(alertmanager_notifications_failed_total[{RI}])",
        "ops",
        0.0001,
        0.01,
    )
    b.ts("Watchdog alert state", 'ALERTS{alertname="Watchdog"}', "short")
    b.flush()
    return b


def market() -> Board:
    b = Board("cv-market-data", "CV / Market data", ["market"])
    b.row("Ingestion")
    b.ts(
        "Messages/s per topic",
        rate("ws_messages_total", "topic"),
        "ops",
        legend="{{topic}}",
    )
    b.ts("WS bytes/s", rate("ws_message_bytes_total"), "Bps")
    b.ts(
        "Book resyncs/s",
        rate("book_resync_total", "symbol, reason"),
        "ops",
        0.05,
        0.2,
        "{{symbol}} {{reason}}",
    )
    b.ts(
        "Engine process p95 (per engine)",
        q("engine_process_seconds", "engine"),
        "s",
        0.005,
        0.01,
        "{{engine}}",
    )
    b.ts("Ingest queue depth", f"ingest_queue_depth{{{E}}}", "short", legend="{{stage}}")
    b.row("WS gateway (client sockets)")
    # E17-T06 (#571). Only series that exist are plotted. Not yet: connection class, queue depth and
    # bytes, bandwidth per connection (no series), overflow actions (`cv_ws_overflow_total`, #2873:
    # the series exists, but nothing increments it until the outbound ladder is wired into the
    # gateway, E17-T03 #412). The 1 and 5 lines of the resync panel are 23-ws-protocol.md 16.3.
    b.ts("Open client connections", f"sum(cv_ws_connections_in_use{{{E}}})", "short")
    b.ts(
        "WS fan-out latency p95 (budget 20 ms)",
        q("cv_ws_fanout_seconds", pct="0.95"),
        "s",
        0.02,
    )
    _describe(
        b,
        "Gateway segment of budget #6, sampled 1 in 32, first 31 frames not observed: from a "
        "subscription's turn in the hub loop to the writer handing the frame to the socket. The "
        "20 ms line is the whole backend envelope of budget #6, and this stage is one share of "
        "it (06 section 5.1). A congested client's drain wait, a slow consumer's backlog and "
        "replay frames are inside it. WsFanoutP95OverBudget judges it only with 40 sampled "
        "frames in 5 minutes, so an empty line is a quiet gateway, not a healthy one.",
    )
    _threshold_lines(b)
    b.ts(
        "WS resyncs in the range, by reason (lines: 1 and 5 an hour)",
        f"round(sum by (reason) (increase(cv_ws_resync_total{{{E}}}[$__range])))",
        "short",
        1,
        5,
        "{{reason}}",
    )
    _describe(
        b,
        "Gateway-wide sum over the dashboard range before each point (1 h by default, which the "
        "lines are for: target under 1, hard fail above 5 an hour), rounded to whole events as "
        "WsUpstreamDesyncHigh rounds. Each affected subscription counts once, so one upstream "
        "desync adds one per subscribed book topic across all connections; 23-ws-protocol.md "
        "16.3 is per topic, so group the `ws resync` log lines by `ch`. upstream_desync and "
        "backpressure are the incident reasons (7.4) and the only ones the lines judge; "
        "reconfigure and client_resync cross them in normal use. Only client_resync and "
        "reconfigure have a trigger today: upstream_desync, upstream_reconnect, "
        "instrument_revision, replay_seek and backpressure read zero whatever happens until "
        "their callers are wired (the outbound ladder, E17-T03 #412, for backpressure; the book "
        "feed, the instrument cache and the replay engine for the other four), so a flat zero "
        "here is not coverage. WsUpstreamDesyncHigh fires above 5 upstream_desync in an hour.",
    )
    _threshold_lines(b)
    b.ts(
        "WS closes in the range, by reason",
        f"round(sum by (reason) (increase(cv_ws_closes_total{{{E}}}[$__range])))",
        "short",
        legend="{{reason}}",
    )
    _describe(
        b,
        "Server-initiated closes by bye reason; the close code is fixed per reason. Any "
        "slow_consumer raises WsSlowConsumerClosed (a user lost their feed); a burst of "
        "origin_forbidden raises WsOriginRefusalsHigh. Every reason exists from process start, "
        "so the first close of any reason is counted; normal, server_shedding_load and other "
        "have no counting path yet, so they read zero whatever happens.",
    )
    b.flush()
    return b


def trading() -> Board:
    b = Board("cv-trading", "CV / Trading", ["trading"])
    b.row("Execution (populates when E29 lands)")
    b.ts(
        "Order submit p99 (budget 500 ms)",
        q("order_submit_seconds", "transport", "0.99"),
        "s",
        0.4,
        0.5,
        "{{transport}}",
    )
    b.ts("Orders/s by state", rate("orders_total", "state"), "ops", legend="{{state}}")
    b.ts(
        "Reject rate",
        rate("orders_total", "state", ',state=~"rejected.*"'),
        "ops",
        legend="{{state}}",
    )
    b.ts("Rate-limit rejects/s", rate("oms_rate_reject_total"), "ops", 0.01, 0.1)
    b.ts(
        "Exchange rate remaining",
        f"bybit_rate_remaining{{{E}}}",
        "short",
        legend="{{endpoint_group}}",
    )
    b.stat(
        "Unknown orders (page > 0 for 60 s)",
        f"oms_unknown_orders{{{E}}}",
        "short",
        1,
        1,
    )
    b.stat(
        "Naked-position alerts (page > 0)",
        f"increase(naked_position_alerts_total{{{E}}}[$__range])",
        "short",
        1,
        1,
    )
    # #2314 (E27-T01): M13 row gauges, scoped to $env. `max`, not `sum`: replicas report the
    # same database, so summing would multiply the counts.
    b.row("Accounts and API keys")
    b.ts(
        "Exchange accounts by kind",
        f"max by (kind) (cv_accounts_rows{{{E}}})",
        "short",
        legend="{{kind}}",
    )
    b.ts(
        "API keys by state",
        f"max by (state) (cv_api_keys_rows{{{E}}})",
        "short",
        legend="{{state}}",
    )
    b.flush()
    return b


def rules() -> Board:
    b = Board("cv-rules", "CV / Rules", ["rules"])
    b.row("Rule engine")
    b.ts("Evaluations/s", rate("rule_evaluations_total"), "ops")
    b.ts(
        "Fires/s per rule",
        rate("rule_fires_total", "rule_id"),
        "ops",
        legend="{{rule_id}}",
    )
    b.ts("Auto-disarms/s", rate("rule_autodisarm_total"), "ops", 0.0001, 0.001)
    b.ts(
        "Circuit-breaker trips/s",
        rate("rule_circuit_breaker_trips_total"),
        "ops",
        0.0001,
        0.001,
    )
    b.flush()
    return b


def storage() -> Board:
    b = Board("cv-storage", "CV / Storage", ["storage"])
    b.row("Recorder and stores")
    b.ts(
        "Recorded rows/s",
        rate("recorder_rows_total", "stream"),
        "ops",
        legend="{{stream}}",
    )
    b.ts("Recorder spill bytes", f"recorder_spill_bytes{{{E}}}", "bytes")
    b.ts(
        "Disk used ratio (warn 80 %, page 95 %)",
        f"disk_used_ratio{{{E}}}",
        "percentunit",
        0.8,
        0.95,
    )
    b.ts("QuestDB write p95", q("questdb_write_seconds"), "s", 0.05, 0.25)
    b.ts("Postgres pool in use", f"pg_pool_in_use{{{E}}}", "short")
    b.ts("Postgres query p95", q("pg_query_seconds"), "s", 0.05, 0.25)
    b.flush()
    return b


def ingestion() -> Board:
    """E08-T06 "Ingestion" board. Series come from the declaration-first
    registry `services/api/candleviewer/ingestion/metrics.py`. Every state
    panel shows a numeric/text value (never colour alone, 05-accessibility)."""
    b = Board("cv-ingestion", "CV / Ingestion", ["ingestion"])
    b.row("Connection and pipeline")
    b.stat("Ingestion wired (1 = yes)", f"max(ingest_enabled{{{E}}})", "short")
    b.stat("Public socket up (1 = open)", f"min(ingest_ws_up{{{E}}})", "short")
    b.stat("Books LIVE (count)", f"sum(ingest_book_live{{{E}}})", "short")
    b.stat("Clock drift (ms)", f"max(abs(exchange_clock_drift_ms{{{E}}}))", "ms", 500, 2000)
    b.row("Event rates and latency")
    b.ts(
        "Events/s per stream and symbol",
        rate("ingest_events_total", "stream, symbol"),
        "ops",
        legend="{{stream}} {{symbol}}",
    )
    b.ts(
        "Ingest lag by stream (budget 20 ms)",
        f"max by (stream) (ingest_lag_seconds{{{E}}})",
        "s",
        0.02,
        0.1,
        "{{stream}}",
    )
    b.ts(
        "Topic staleness (book 2 s, trades 10 s)",
        f"max by (topic) (ws_topic_staleness_seconds{{{E}}})",
        "s",
        2,
        10,
        "{{topic}}",
    )
    b.row("Queues and backpressure")
    b.ts(
        "Subscriber queue depth",
        f"max by (subscriber) (bus_subscriber_lag{{{E}}})",
        "short",
        2048,
        4096,
        "{{subscriber}}",
    )
    b.ts(
        "Never-drop queue full events/s",
        rate("ingest_queue_full_total", "class"),
        "ops",
        legend="{{class}}",
    )
    b.ts(
        "Write-behind queue depth",
        f"max by (table) (questdb_write_queue_depth{{{E}}})",
        "short",
        legend="{{table}}",
    )
    b.row("Book health and tape integrity")
    b.ts(
        "Book resyncs/min",
        f"60 * {rate('ingest_book_resyncs_total', 'symbol, reason')}",
        "short",
        3,
        5,
        "{{symbol}} {{reason}}",
    )
    b.ts(
        "Unrecovered trade gaps per interval",
        f'sum by (symbol) (increase(trade_gaps_total{{{E},recovered="false"}}[{RI}]))',
        "short",
        None,
        1,
        "{{symbol}}",
    )
    b.row("Exchange REST")
    b.ts(
        "Rate-limit headroom",
        f"min by (scope, endpoint_class) (bybit_rate_limit_remaining{{{E}}})",
        "short",
        10,
        1,
        "{{scope}} {{endpoint_class}}",
    )
    b.ts("REST p95 by endpoint", q("bybit_rest_latency_seconds", "endpoint"), "s", 0.25, 1)
    b.flush()
    return b


def frontend() -> Board:
    b = Board("cv-frontend", "CV / Frontend", ["frontend"])
    b.row("Getting worse? (SLO burn)")
    b.stat("Frame time p95 (budget 16 ms)", q("fe_frame_time_ms"), "ms", 16, 33)
    # Budget-ratio stats computed directly from catalogue histograms (no recording-rule
    # dependency): >1 means the p95 is over its budget.
    b.stat("WS decode p95 / budget (2 ms)", f"{q('fe_ws_decode_ms')} / 2", "short", 1, 2.5)
    b.stat(
        "Frame time p95 / budget (16 ms)",
        f"{q('fe_frame_time_ms')} / 16",
        "short",
        1,
        2,
    )
    b.row("Rendering")
    b.ts("Frame time p95", q("fe_frame_time_ms"), "ms", 16, 33)
    b.ts("Dropped frames/s", rate("fe_dropped_frames_total"), "ops", 1, 5)
    b.ts("WS decode p95", q("fe_ws_decode_ms"), "ms", 2, 5)
    b.ts("GPU memory", f"fe_gpu_memory_mb{{{E}}}", "decmbytes")
    b.flush()
    return b


# --- GA readiness: defects (E49-T02) ------------------------------------------------
# Target numbers are the R5 exit criteria (docs/plan/30-release-roadmap.md 9.3 item 3) and the
# S26 boundary from docs/plan/backlog/_tools/calendar_cv.py; tests pin both so they cannot drift.
GA_P01_TARGET, GA_P2_TARGET = 0, 10
GA_DATE = "2027-03-25"
STALE_S = 7200
GA_FRESH = f'(time() - push_time_seconds{{job="ga_defects"}} < {STALE_S})'
GA_LEDGER_FRESH = f'(time() - push_time_seconds{{job="design_qa_ledger"}} < {STALE_S})'
NO_DATA = "STALE: no push for over 2 h (or no data)"


def _fresh(metric: str, fresh: str = GA_FRESH) -> str:
    """Drop the series when the pushgateway group is stale so the panel shows NO_DATA."""
    return f"{metric} and on() {fresh}"


def _extra(b: Board, refid: str, expr: str, legend: str) -> None:
    b.panels[-1]["targets"].append(
        {"refId": refid, "datasource": DS, "expr": expr, "legendFormat": legend}
    )


def _finish(b: Board, desc: str) -> None:
    p = b.panels[-1]
    p["description"] = desc
    p["fieldConfig"]["defaults"]["noValue"] = NO_DATA


def ga_defects() -> Board:
    b = Board("cv-ga-defects", "GA readiness - defects", ["ga", "defects"])
    b.panels[0]["options"]["content"] = f"## GA readiness - defects (GA {GA_DATE}) - env = **$env**"
    b.row("Burn-down vs GA target (S23-S26, GA " + GA_DATE + ")")
    b.ts(
        "Open defects by severity (stacked P0 > P1 > P2 > P3) vs target",
        _fresh("ga_defects_open"),
        "short",
        legend="{{severity}} open",
    )
    _extra(b, "B", f"vector({GA_P01_TARGET})", f"TARGET P0/P1 = {GA_P01_TARGET} by {GA_DATE}")
    _extra(b, "C", f"vector({GA_P2_TARGET})", f"TARGET P2 <= {GA_P2_TARGET} by {GA_DATE}")
    p = b.panels[-1]
    p["fieldConfig"]["defaults"]["custom"] = {"stacking": {"mode": "normal"}}
    p["fieldConfig"]["overrides"] = [
        {
            "matcher": {"id": "byRegexp", "options": "TARGET.*"},
            "properties": [
                {"id": "custom.stacking", "value": {"mode": "none"}},
                {"id": "custom.lineStyle", "value": {"fill": "dash", "dash": [10, 10]}},
            ],
        }
    ]
    _finish(b, "Legend lists severity P0 (most severe) to P3. Dashed lines are the exit targets.")
    b.stat(
        "Zero-crossing, linear fit (days from now; no value = undefined)",
        _fresh('ga_defect_forecast_days_to_zero{method="linear"}'),
        "d",
        legend="linear 3-week fit",
    )
    _finish(b, "Linear regression, trailing 3 weeks. A projection, not a commitment.")
    b.stat(
        "Zero-crossing, 3-week trailing rate (days from now)",
        _fresh('ga_defect_forecast_days_to_zero{method="trailing_3w"}'),
        "d",
        legend="trailing 3-week rate",
    )
    _finish(b, "Mean net burn rate, trailing 3 weeks. A projection, not a commitment.")
    b.row("Flow, ageing and queue health")
    b.ts(
        "Arrival vs closure, rolling 7 days (arrival above closure cannot converge)",
        _fresh("ga_defects_arrived_7d"),
        "short",
        legend="arrived (7d)",
    )
    _extra(b, "B", _fresh("ga_defects_closed_7d"), "closed (7d)")
    _finish(b, "Leading indicator: when arrived exceeds closed the open curve rises.")
    b.ts(
        "Ageing: defects at most N days old (SLA: P0 2h, P1 1d, P2 3d, P3 5d)",
        _fresh("ga_defect_age_days_bucket"),
        "short",
        legend="{{severity}} <= {{le}} d",
    )
    _finish(b, "Cumulative histogram; triage SLA windows per 03-testing-strategy 11.3.")
    b.stat("Untriaged open bugs", _fresh("ga_defects_untriaged"), "short", 1, 5, "untriaged")
    _finish(b, "Open type/bug issues without the triaged label.")
    b.stat(
        "SLA at-risk / breached by severity",
        _fresh("sum by (severity, state) (ga_defects_sla_state)"),
        "short",
        1,
        1,
        "{{severity}} {{state}}",
    )
    _finish(b, "Any P0/P1 breached fires GADefectSLABreached.")
    b.ts(
        "Open defects by component",
        _fresh("ga_defects_open_by_component"),
        "short",
        legend="{{component}}",
    )
    _finish(b, "Where the debt sits (area/* labels).")
    b.ts(
        "Design-QA findings open by severity (E49-D01 ledger)",
        _fresh("design_qa_findings_open", GA_LEDGER_FRESH),
        "short",
        legend="design {{severity}}",
    )
    _finish(b, "From e49-design-qa-ledger.csv; design debt next to functional debt.")
    b.flush()
    return b


BOARDS = {
    "system-health": system,
    "market-data": market,
    "trading": trading,
    "rules": rules,
    "storage": storage,
    "ingestion": ingestion,
    "frontend": frontend,
    "ga-defects": ga_defects,
}


def render() -> dict[str, str]:
    return {
        f"{n}.json": json.dumps(fn().build(), indent=2, sort_keys=True) + "\n"
        for n, fn in BOARDS.items()
    }


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, text in render().items():
        (OUT / name).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
