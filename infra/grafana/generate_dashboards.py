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
    # #836 (E27-T03): keys failing the self-check; the oldest last pass, lines at the default 3600 s
    # interval and its +900 s stale latch (ticketed). More series: #3658. `max`: replicas agree.
    b.ts(
        "Stored API keys failing the self-check, by rule (dashed: ticket at 1)",
        f"max by (rule) (cv_keys_failing_policy{{{E}}})",
        "short",
        None,
        1,
        "{{rule}}",
    )
    _threshold_lines(b)  # a line, not colour alone, marks the alert
    b.ts(
        "Oldest stored API key's last pass (dashed: the default interval; stale latch at +15 min)",
        f"max(cv_key_verification_age_seconds{{{E}}})",
        "s",
        3600,
        4500,
    )
    _threshold_lines(b)
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
    _ws_gateway(b)
    _ws_queue(b)
    _ws_handshake(b)
    _ws_subscriptions(b)
    _ws_cost(b)
    b.flush()
    return b


# --- WS gateway (E17-T06, #571) -------------------------------------------------------------
# Every series is a live one of the metric catalogue, with its as-built labels; a line is drawn
# only at a documented value. 23-ws-protocol.md section 16.3: the resync lines, the bandwidth and
# the re-snapshot budget; 8.3: the class edges of the queue and RTT panels; 16.2: the 200
# subscriptions and the 4 MiB frame; 4.2: the clock-skew warning; the catalogue: handshake p99.
#: The default 23-ws-protocol.md 8.4 outbound queue budget (a deployment may only lower it).
WS_QUEUE_BYTES, WS_QUEUE_FRAMES = 8 * 1024 * 1024, 2000
KIB, MIB = 1024, 1024 * 1024


def _in_range(metric: str, by: str = "") -> str:
    """Whole events over the dashboard range, as the WS alerts round them."""
    grouped = f"sum by ({by}) " if by else "sum"
    return f"round({grouped}(increase({metric}{{{E}}}[$__range])))"


def _ws_gateway(b: Board) -> None:
    b.row("WS gateway (client sockets)")
    # The ticket's row: connections, class, fan-out p95 against 20 ms, resyncs against the 16.3
    # lines, overflow actions and bandwidth per connection; closes and gaps feed its alerts.
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
        _in_range("cv_ws_resync_total", "reason"),
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
        "desync adds one per subscribed topic across all connections; 23-ws-protocol.md 16.3 is "
        "per topic, so group the `ws resync` log lines by `ch`. upstream_desync and backpressure "
        "are the incident reasons (7.4) and the only ones the lines judge; the other reasons "
        "cross them in normal use. Moving today: client_resync, reconfigure, the bars and "
        "indicator series' generation_swap and history_repair, upstream_desync from the alerts "
        "topic (6.2.1) and from a delta the hub failed to emit, and backpressure with "
        "CV_WS_BACKPRESSURE_ENABLED on. The book feed does not call the hub's upstream_desync "
        "trigger yet, and upstream_reconnect, instrument_revision and replay_seek have no caller, "
        "so a flat zero for those is not coverage. WsUpstreamDesyncHigh fires above 5 "
        "upstream_desync in an hour.",
    )
    _threshold_lines(b)
    b.ts(
        "WS closes in the range, by reason",
        _in_range("cv_ws_closes_total", "reason"),
        "short",
        legend="{{reason}}",
    )
    _describe(
        b,
        "Server-initiated closes by bye reason; the close code is fixed per reason. Any "
        "slow_consumer raises WsSlowConsumerClosed (a user lost their feed); a burst of "
        "origin_forbidden raises WsOriginRefusalsHigh. Every reason exists from process start, "
        "so the first close of any reason is counted; server_shedding_load counts sockets shed at "
        "the cap on sockets awaiting auth; normal and other have no counting path yet, so they "
        "read zero whatever happens.",
    )
    b.ts(
        "WS connections by class (backpressure flag on)",
        f"sum by (state) (cv_ws_connection_class{{{E}}})",
        "short",
        legend="{{state}}",
    )
    _describe(
        b,
        "Open client connections per 23-ws-protocol.md 8.3 class (`state`), from the first "
        "auth_ok to the teardown, summed over processes. Set only with "
        "CV_WS_BACKPRESSURE_ENABLED on (off by default): with it off every class reads zero, so a "
        "flat zero is not health. A connection's class is read when its writer runs; a writer "
        "held in a send keeps its last class, and a stuck socket shows in the overflow and "
        "closes panels.",
    )
    b.ts(
        "WS overflow actions in the range, by reason",
        _in_range("cv_ws_overflow_total", "reason"),
        "short",
        legend="{{reason}}",
    )
    _describe(
        b,
        "The 23-ws-protocol.md 8.4 ladder: drop, drop_share, unmergeable and resnapshot count per "
        "topic; close_budget and close_redrop per close (a slow_consumer close, which the closes "
        "panel and WsSlowConsumerClosed see too); close_flush_deadline per close whose flush "
        "expired, beside its step 3; withdrawn per queued frame that a withdrawn grant or "
        "permission dropped (9.5). The ladder runs only with CV_WS_BACKPRESSURE_ENABLED on; with "
        "it off only close_flush_deadline and withdrawn move. A reason's series starts at its "
        "first event, so the first one after a restart may not show.",
    )
    b.ts(
        "WS bandwidth per connection, sampled (lines: 350 KiB/s target, 1 MiB/s hard fail)",
        f'sum(rate(cv_ws_frame_bytes_sum{{{E},kind=~"json|msgpack"}}[{RI}])) '
        f"/ clamp_min(sum(cv_ws_connections_in_use{{{E}}}), 1)",
        "binBps",
        350 * KIB,
        MIB,
    )
    _describe(
        b,
        "Data-frame bytes per second over the open connections: a mean, not the busiest client. "
        "Estimated from cv_ws_frame_bytes, kind json or msgpack, sampled 1 in 32 with weight 32, "
        "so each subscription's first 31 frames, control frames and system frames are left out "
        "and it reads low. Bytes are as encoded for the send, before permessage-deflate and less "
        "the span id sp; with the backpressure flag on a frame counts at its encode, so one the "
        "ladder drops later is in it. A connection feeds only its own codec, so json and msgpack "
        "never count the same frame; the CVWB kinds do, so they are left out. The lines are "
        "23-ws-protocol.md 16.3's server-to-client budget for the reference workspace.",
    )
    _threshold_lines(b)
    b.ts(
        "WS client-reported sequence gaps in the range (line: 1)",
        _in_range("cv_ws_sequence_gaps_detected_total"),
        "short",
        None,
        1,
    )
    _describe(
        b,
        "Client resync frames with reason sequence_gap (23-ws-protocol.md 7.5). The server "
        "guarantees gap-free sequences, so any count is a bug to chase, though the server does "
        "not verify the client's report. WsSequenceGapDetected (ticket) fires on any in 10 "
        "minutes; the `ws client resync` log lines name the ch and the client's last seq.",
    )
    _threshold_lines(b)


def _ws_queue(b: Board) -> None:
    b.row("WS queue, RTT and coalescing (backpressure flag on)")
    # Per process, flag on only (ruling D6 of #412): read once per connection per
    # CV_WS_CLASSIFY_INTERVAL_MS (the probe and the depth) or as a merged window leaves.
    b.ts(
        "WS outbound queue depth p95, share of the default budget (lines: 25 % and 60 %)",
        f"{q('cv_ws_queue_bytes')} / {WS_QUEUE_BYTES}",
        "percentunit",
        0.25,
        0.6,
        "bytes of 8 MiB",
    )
    _extra(b, "B", f"{q('cv_ws_queue_frames')} / {WS_QUEUE_FRAMES}", "frames of 2 000")
    _describe(
        b,
        "Depth sampled per connection at each classification, as a share of the default "
        "23-ws-protocol.md 8.4 budget (8 MiB or 2 000 frames). The class reads the larger share, "
        "and the lines are its 8.3 edges: lagging from 25 % (throttles x2), x4 from 60 %, "
        "overflowing above 90 %. A deployment may only lower the budget, so a lowered one "
        "reaches the edges before this panel does. A writer held in a send takes no sample; a "
        "stuck socket shows in the overflow and closes panels.",
    )
    _threshold_lines(b)
    b.ts(
        "WS probe RTT p95 (lines: 150 ms and 500 ms)",
        q("cv_ws_rtt_seconds"),
        "s",
        0.15,
        0.5,
    )
    _describe(
        b,
        "One sample per answered 23-ws-protocol.md 9.1 probe, from its queueing to the pong; a "
        "probe unanswered for 10 s counts its age when it is retired. The lines are the 8.3 class "
        "edges (lagging, throttles x2, from 150 ms; x4 above 500 ms). A client that never answers "
        "server pings is classed x4 from its second classification on (8.6).",
    )
    _threshold_lines(b)
    b.ts(
        "WS updates merged away per second, by family",
        rate("cv_ws_conflated_total", "topic"),
        "ops",
        legend="{{topic}}",
    )
    _describe(
        b,
        "Source updates a throttle window merged away, by family (`topic`): a window of n updates "
        "that left as one frame adds n - 1 (23-ws-protocol.md 8.2). Only families with a merge "
        "rule are counted, append families never. The pacer's own merges, not a producer's "
        "carried coalesced_count.",
    )
    b.ts(
        "WS updates per merged window p95",
        q("cv_ws_coalesced_updates"),
        "short",
    )
    _describe(b, "Source updates (2 and up) in each merged window that left as one frame.")


def _ws_handshake(b: Board) -> None:
    b.row("WS handshake and auth (E17-S01)")
    b.ts(
        "WS handshake p99, accept to first auth_ok (line: 2 s)",
        q("cv_ws_handshake_seconds", pct="0.99"),
        "s",
        2,
    )
    _describe(
        b,
        "From the socket's accept to its first auth_ok; a re-auth is not observed. The line is the "
        "catalogue's p99 line for this series; it falls between the 1 s and 2.5 s bucket edges, "
        "so a p99 near it is interpolated. The auth timeout is 10 s (23-ws-protocol.md 16.2).",
    )
    _threshold_lines(b)
    b.ts(
        "WS auth failures in the range, by reason",
        _in_range("cv_ws_auth_failures_total", "reason"),
        "short",
        legend="{{reason}}",
    )
    _describe(
        b,
        "Failed auth frames by bounded reason: missing_token, rejected, token_expired, "
        "user_mismatch. A sudden rise can mean credential stuffing; the `ws auth failed` log "
        "lines carry the connection_id and source_ip. A reason's series starts at its first "
        "failure, so the first one after a restart may not show.",
    )
    b.ts(
        "WS client clock skew p99 (line: 2 000 ms)",
        q("cv_ws_clock_skew_ms", pct="0.99"),
        "ms",
        2000,
    )
    _describe(
        b,
        "The absolute skew of each welcome: server time minus the hello's clock_ms (a hello "
        "without a valid one adds no sample). The UI warns above 2 000 ms because a skewed "
        "client mis-renders bar countdowns (23-ws-protocol.md 4.2).",
    )
    _threshold_lines(b)
    b.ts(
        "WS sockets refused by the per-user connect rate, in the range",
        _in_range("cv_ws_connect_rate_limited_total"),
        "short",
    )
    _describe(
        b,
        "Sockets closed client_rate_limited after a valid auth because their user passed 20 "
        "successful auths in a sliding minute (23-ws-protocol.md 4.3, 16.2). A sustained count "
        "means a client with no backoff, or one token in use from more places than expected; the "
        "`ws connect rate limited` log line names the user, once per user per window.",
    )


def _ws_subscriptions(b: Board) -> None:
    b.row("WS subscriptions and revocation (E17-S02)")
    b.ts(
        "WS subscribe results per second, by result",
        rate("cv_ws_subscribe_total", "result"),
        "ops",
        legend="{{result}}",
    )
    _describe(
        b,
        "Each topic result of a sub_ok: ok, or the 23-ws-protocol.md 10.2 code that refused it. "
        "The series also carry `topic`, the family (unknown for a name no family owns): split by "
        "it in Explore when a refusal code rises.",
    )
    b.ts(
        "WS subscriptions per connection, p50 and p95 (line: 200, the cap)",
        q("cv_ws_client_topics_depth", pct="0.5"),
        "short",
        None,
        200,
        "p50",
    )
    _extra(b, "B", q("cv_ws_client_topics_depth"), "p95")
    _describe(
        b,
        "Observed after each sub_ok and unsub_ok, so a connection that changes its set often "
        "weighs more than a quiet one. 200 is the per-connection cap (23-ws-protocol.md 16.2). "
        "The ticket's cv_ws_topics_per_client gauge is built as this histogram (6.2, Metrics as "
        "built).",
    )
    _threshold_lines(b)
    b.ts(
        "WS upstream consumers, by family",
        f"sum by (topic) (cv_ws_upstream_consumers_in_use{{{E}}})",
        "short",
        legend="{{topic}}",
    )
    _describe(
        b,
        "Consumers of the shared upstream leases, summed over symbols per family (`topic`). The "
        "series are per symbol for the first 20 symbols and symbol=other after them, and each is "
        "removed at 0, so an idle family has no line.",
    )
    b.ts(
        "WS subscriptions revoked in the range, by reason",
        _in_range("cv_ws_revoked_total", "reason"),
        "short",
        legend="{{reason}}",
    )
    _describe(
        b,
        "Subscriptions the server ended mid-connection with a revoked frame (23-ws-protocol.md "
        "9.5): a withdrawn permission, account scope or key, a disabled user or account, an "
        "ended session or replay, the resync rate limit or a removed topic. A reason's series "
        "starts at its first revocation.",
    )


def _ws_cost(b: Board) -> None:
    b.row("WS frame and snapshot cost")
    b.ts(
        "WS frame encode time p95, by kind (sampled 1 in 32)",
        q("cv_ws_frame_encode_seconds", "kind"),
        "s",
        legend="{{kind}}",
    )
    _describe(
        b,
        "kind is a CVWB body kind (a delta the hub stamped, and every snapshot chunk) or json / "
        "msgpack (a stamped data frame in its connection's codec; a binary frame's msgpack time "
        "includes the base64 decode of its p). The same frame counts under its body kind and "
        "again under its codec, so the kinds are not summed.",
    )
    b.ts(
        "WS frame size p95, by kind (sampled 1 in 32; line: the 4 MiB frame limit)",
        q("cv_ws_frame_bytes", "kind"),
        "bytes",
        None,
        4 * MIB,
        "{{kind}}",
    )
    _describe(
        b,
        "Encoded size before permessage-deflate; json and msgpack leave out the span id sp. 4 MiB "
        "is the outbound frame limit (23-ws-protocol.md 3.6): a larger frame is logged and sent, "
        "and a p95 above the top bucket reads as 4 MiB.",
    )
    _threshold_lines(b)
    b.ts(
        "WS snapshot build p99, by family (lines: 400 ms and 1.5 s)",
        q("cv_ws_snapshot_build_seconds", "topic", "0.99"),
        "s",
        0.4,
        1.5,
        "{{topic}}",
    )
    _describe(
        b,
        "Build and render time of each snapshot the cache builds, by family; one served from the "
        "cache is not observed. The lines are 23-ws-protocol.md 16.3's budget for a full "
        "re-snapshot of the reference workspace (target 400 ms, hard fail 1.5 s), so one family "
        "alone above them breaks it. Below them is no proof of the budget, which is the sum over "
        "the workspace.",
    )
    _threshold_lines(b)
    b.ts(
        "WS snapshot size p95, by family (lines: 700 KiB and 2 MiB)",
        q("cv_ws_snapshot_bytes", "topic"),
        "bytes",
        700 * KIB,
        2 * MIB,
        "{{topic}}",
    )
    _describe(
        b,
        "All chunks of each snapshot sent, by family. The lines are 16.3's workspace re-snapshot "
        "budget (target 700 KiB, hard fail 2 MiB), as for the build time: below them is no proof "
        "of the budget, which is the sum over the workspace.",
    )
    _threshold_lines(b)


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
    # #837 (E27-T04): per state, never per account (SR-125); the log lines name the account.
    b.ts(
        "Accounts by health state and reason",
        f"sum by (state, reason) (cv_account_health_state{{{E}}})",
        "short",
        legend="{{state}} {{reason}}",
    )
    _describe(
        b,
        "Monitored accounts, set at each health tick. down with no_success went down after it was "
        "up and pages AccountDown. down with never_connected has not connected since boot, which "
        "every account reads until the private WS (#848) and the wallet read (E29) land; it does "
        "not page.",
    )
    b.ts(
        "Health transitions in the range, by state entered",
        "round(sum by (state, reason) "
        f"(increase(cv_account_health_transitions_total{{{E}}}[$__range])))",
        "short",
        legend="{{state}} {{reason}}",
    )
    b.ts(
        "Oldest wallet snapshot (lines: 10 s stale, 60 s REST read)",
        f"max(cv_wallet_snapshot_age_seconds{{{E}}})",
        "s",
        10,
        60,
    )
    _describe(
        b,
        "Seconds since the oldest monitored account's last wallet refresh. Past the stale window "
        "(CV_WALLET_STALE_S, 10 s by default) its balance shows stale; past the reconciliation "
        "period (CV_WALLET_RECONCILE_S, 60 s) a REST read is due and risk-based sizing will not "
        "use it.",
    )
    _threshold_lines(b)
    b.ts(
        "Wallet reconciliation reads/s by result",
        rate("cv_wallet_reconcile_total", "result"),
        "ops",
        legend="{{result}}",
    )
    b.ts(
        "Sizing decisions/s on a snapshot a period old (refused)",
        f"sum(rate(cv_wallet_sizing_old_snapshot_total{{{E}}}[{RI}]))",
        "ops",
    )
    b.ts(
        "API keys by rotation state (never disabled for age)",
        f"max by (state) (cv_keys_rotation_state{{{E}}})",
        "short",
        legend="{{state}}",
    )
    # #906 (E28-T02): profile saves by result and refusal rule, the save p95 against the second
    # pass's 1.5 s catalogue deadline and SCR-131's 2 s budget (dashed lines), and the catalogue
    # refreshes a save may wait for (ruling B8). Per result or rule, never per account, profile
    # or principal.
    b.row("Account profiles")
    b.ts(
        "Profile saves/s by result",
        rate("cv_profile_saves_total", "result"),
        "ops",
        legend="{{result}}",
    )
    b.ts(
        "Refused profile saves/s by rule",
        rate("cv_profile_validation_failures_total", "rule"),
        "ops",
        legend="{{rule}}",
    )
    b.ts("Profile save p95 (budget 2 s)", q("cv_profile_save_seconds"), "s", 1.5, 2.0)
    _describe(
        b,
        "A profile save's round trip in the router, from the handler's entry. The dashed lines: "
        "1.5 s is the second validation pass's catalogue deadline, the longest a save waits for a "
        "catalogue refresh; 2 s is SCR-131's save budget, a cold refresh included.",
    )
    _threshold_lines(b)
    b.ts(
        "Instrument catalogue refreshes/s by result",
        rate("instruments_refresh_total", "result"),
        "ops",
        legend="{{result}}",
    )
    _describe(
        b,
        "Instrument catalogue refreshes by result: ok, or error once its retries are spent. They "
        "run on the 12 h schedule, at start-up and on demand: a profile save that adds allow "
        "scope or moves a limit waits up to 1.5 s for one when the catalogue is over 15 minutes "
        "old or marked stale. timeout is a start-up fetch given up; throttled is an unknown-symbol "
        "lookup refused a refresh inside its cool-down, so none ran.",
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


def recorder() -> Board:
    """E16-T09 (#567) board for infra/prometheus/alerts/recorder.yml (docs/ops/runbooks/recorder.md).
    Declared series only: no retention or recorder-gap series is exported yet."""
    b = Board("cv-recorder", "CV / Recorder", ["recorder", "storage"])
    b.row("Writes")
    by_symbol = rate("recorder_bytes_written_total", "symbol")
    b.ts("Recorder write rate by symbol (bytes/s)", by_symbol, "Bps", legend="{{symbol}}")
    _describe(b, "A flat line while other symbols write is a silent stop (RecorderSilentStop).")
    by_stream = f"3600 * {rate('recorder_rows_total', 'stream')}"
    b.ts("Recorded rows per hour by stream", by_stream, "short", legend="{{stream}}")
    lag = f"max by (stream) (ingest_lag_seconds{{{E}}})"
    b.ts("Ingest lag by stream (budget 20 ms)", lag, "s", 0.02, 0.1, "{{stream}}")
    b.row("Backpressure")
    dropped = rate("trade_writes_dropped_total", "reason")
    b.ts("Dropped rows/s", dropped, "ops", legend="trades {{reason}}")
    _extra(b, "B", rate("book_writes_dropped_total", "reason"), "book {{reason}}")
    _extra(b, "C", f"sum({rate('ticker_writes_dropped_total')})", "tickers")
    b.ts("Write backlog (rows)", f"recorder_write_backlog_rows{{{E}}}", "short")
    b.ts("Spill bytes (WAL)", f"recorder_spill_bytes{{{E}}}", "bytes", 1)
    b.row("Disk")
    disk = "Disk used (warn 80 %, autostop 90 %, halt 95 %)"
    b.ts(disk, f"disk_used_ratio{{{E}}}", "percentunit", 0.8, 0.95)
    steps = b.panels[-1]["fieldConfig"]["defaults"]["thresholds"]["steps"]
    steps.insert(2, {"color": "#CC79A7", "value": 0.9})  # Okabe-Ito reddish purple: autostop
    _threshold_lines(b)
    full = f"1000 * (max(recorder_projected_full_timestamp{{{E}}}) > 0)"
    b.stat("Projected full date (UTC)", full, "dateTimeAsIso")
    b.panels[-1]["fieldConfig"]["defaults"]["noValue"] = "none projected"
    b.row("Gaps and roll-off")
    gaps = f"sum by (symbol, recovered) (increase(trade_gaps_total{{{E}}}[{RI}]))"
    b.ts("Gaps per interval by symbol", gaps, "short", legend="{{symbol}} {{recovered}}")
    mark = f"max by (stream) (recorder_watermark_lag_days{{{E}}})"
    b.ts("Roll-off watermark lag (days)", mark, "d", legend="{{stream}}")
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
    "recorder": recorder,
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
