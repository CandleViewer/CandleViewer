"""E17-T06 (#571): the WS panels of the Market data dashboard, against the catalogue and the docs.

The ticket's WS row, the panels E17-S01 (#377: handshake, auth failures, clock skew) and E17-S02
(#378: subscriptions and revocation) deferred to it, and a panel for every other scraped series the
ticket names. Each query reads only live catalogued series, with labels those series carry, and each
line sits at the value its document states (`test_ws_alert_rules.py` pins the first four panels'
query shapes). No PromQL is evaluated here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from candleviewer.observability.metrics_catalogue import CATALOGUE, MetricSpec
from candleviewer.ws.limits import MAX_SUBSCRIPTIONS
from candleviewer.ws.metrics import JSON_KIND, MSGPACK_KIND
from candleviewer.ws.outbound import QUEUE_BYTES, QUEUE_FRAMES
from candleviewer.ws.pacing import LAGGING_QUEUE_PCT, LAGGING_RTT_MS
from candleviewer.ws.sequencing import MAX_OUTBOUND_FRAME_BYTES

_ROOT = Path(__file__).resolve().parents[5]
_MARKET = _ROOT / "infra" / "grafana" / "dashboards" / "market-data.json"
_WS_DOC = _ROOT / "docs" / "plan" / "23-ws-protocol.md"
_BY_NAME: Mapping[str, MetricSpec] = {s.name: s for s in CATALOGUE}
_KIB, _MIB = 1024, 1024 * 1024

#: The WS rows of Market data, each panel by the catalogued series it reads, in panel order.
WS_ROWS: dict[str, list[set[str]]] = {
    "WS gateway (client sockets)": [
        {"cv_ws_connections_in_use"},
        {"cv_ws_fanout_seconds"},
        {"cv_ws_resync_total"},
        {"cv_ws_closes_total"},
        {"cv_ws_connection_class"},
        {"cv_ws_overflow_total"},
        {"cv_ws_frame_bytes", "cv_ws_connections_in_use"},
        {"cv_ws_sequence_gaps_detected_total"},
    ],
    "WS queue, RTT and coalescing (backpressure flag on)": [
        {"cv_ws_queue_bytes", "cv_ws_queue_frames"},
        {"cv_ws_rtt_seconds"},
        {"cv_ws_conflated_total"},
        {"cv_ws_coalesced_updates"},
    ],
    "WS handshake and auth (E17-S01)": [
        {"cv_ws_handshake_seconds"},
        {"cv_ws_auth_failures_total"},
        {"cv_ws_clock_skew_ms"},
        {"cv_ws_connect_rate_limited_total"},
    ],
    "WS subscriptions and revocation (E17-S02)": [
        {"cv_ws_subscribe_total"},
        {"cv_ws_client_topics_depth"},
        {"cv_ws_upstream_consumers_in_use"},
        {"cv_ws_revoked_total"},
    ],
    "WS frame and snapshot cost": [
        {"cv_ws_frame_encode_seconds"},
        {"cv_ws_frame_bytes"},
        {"cv_ws_snapshot_build_seconds"},
        {"cv_ws_snapshot_bytes"},
    ],
}
#: The series the ticket names, as built (23-ws-protocol.md 6.2 "Metrics as built", 20 section
#: 12.1), and the gap counter its alerts read. `cv_ws_errors_total` is counted in process only:
#: its `code` label is not on the SR-125 allow-list, so it is not scraped and has no panel.
TICKET_SERIES = (
    "cv_ws_connections_in_use",
    "cv_ws_client_topics_depth",
    "cv_ws_resync_total",
    "cv_ws_overflow_total",
    "cv_ws_conflated_total",
    "cv_ws_frame_encode_seconds",
    "cv_ws_frame_bytes",
    "cv_ws_snapshot_build_seconds",
    "cv_ws_snapshot_bytes",
    "cv_ws_fanout_seconds",
    "cv_ws_connection_class",
    "cv_ws_queue_bytes",
    "cv_ws_queue_frames",
    "cv_ws_rtt_seconds",
    "cv_ws_coalesced_updates",
    "cv_ws_errors_total",
    "cv_ws_auth_failures_total",
    "cv_ws_revoked_total",
    "cv_ws_closes_total",
    "cv_ws_clock_skew_ms",
    "cv_ws_sequence_gaps_detected_total",
)
_IDENT = re.compile(r"[A-Za-z_]\w*")
_SELECTOR = re.compile(r"(?P<name>cv(?:wb)?_[a-z0-9_]+)\s*\{(?P<body>[^}]*)\}")
_MATCHER = re.compile(r'(?P<label>[a-zA-Z_]\w*)\s*(?:=~|!~|!=|=)\s*"[^"]*"')
_GROUPING = re.compile(r"\b(?:by|on|without|ignoring)\s*\(([^)]*)\)")


def _base(series: str) -> str:
    """The catalogued name behind a series: a histogram's `_bucket`/`_count`/`_sum` fold back."""
    stem = re.sub(r"_(?:bucket|count|sum)$", "", series)
    return stem if stem in _BY_NAME and _BY_NAME[stem].kind == "histogram" else series


def _rows() -> dict[str, list[dict[str, Any]]]:
    """Market data's panels under each row title."""
    rows: dict[str, list[dict[str, Any]]] = {}
    current: list[dict[str, Any]] = []
    for panel in json.loads(_MARKET.read_text(encoding="utf-8"))["panels"]:
        if panel["type"] == "row":
            current = rows.setdefault(panel["title"], [])
        elif panel["type"] != "text":
            current.append(panel)
    return rows


def _ws_panels() -> list[dict[str, Any]]:
    rows = _rows()
    return [panel for title in WS_ROWS for panel in rows.get(title, [])]


def _exprs(panel: Mapping[str, Any]) -> list[str]:
    return [str(t["expr"]) for t in panel["targets"]]


def _series(panel: Mapping[str, Any]) -> set[str]:
    """Every catalogued name a panel's queries mention, whatever its prefix."""
    return {_base(i) for e in _exprs(panel) for i in _IDENT.findall(e) if _base(i) in _BY_NAME}


def _panel(title_start: str) -> dict[str, Any]:
    found = [p for p in _ws_panels() if p["title"].startswith(title_start)]
    assert len(found) == 1, f"{title_start!r}: {len(found)} panels"
    return found[0]


def _steps(panel: Mapping[str, Any]) -> set[float]:
    """The threshold values of a panel (its base step has none)."""
    steps = panel["fieldConfig"]["defaults"]["thresholds"]["steps"]
    return {s["value"] for s in steps if s["value"] is not None}


def _doc(pattern: str) -> tuple[str, ...]:
    """The groups of the one 23-ws-protocol.md line that `pattern` finds."""
    found = re.search(pattern, _WS_DOC.read_text(encoding="utf-8"))
    assert found, pattern
    return found.groups()


def _ints(pattern: str) -> tuple[int, ...]:
    """`_doc`'s groups as integers (a digit-grouped "2 000" reads 2000)."""
    return tuple(int(group.replace(" ", "")) for group in _doc(pattern))


def test_each_ws_row_plots_its_series_in_panel_order() -> None:
    rows = _rows()
    for title, expected in WS_ROWS.items():
        assert title in rows, f"no {title!r} row on Market data"
        assert [_series(p) for p in rows[title]] == expected, title


def test_the_panels_deferred_from_e17_s01_and_e17_s02_are_in_their_rows() -> None:
    """The 2026-10-21 scope note: QA checks these panels in the committed JSON."""
    rows = _rows()
    s01 = set().union(*map(_series, rows["WS handshake and auth (E17-S01)"]))
    s02 = set().union(*map(_series, rows["WS subscriptions and revocation (E17-S02)"]))
    assert {"cv_ws_handshake_seconds", "cv_ws_auth_failures_total", "cv_ws_clock_skew_ms"} <= s01
    assert {
        "cv_ws_subscribe_total",
        "cv_ws_client_topics_depth",
        "cv_ws_upstream_consumers_in_use",
        "cv_ws_revoked_total",
    } <= s02


def test_every_scraped_series_the_ticket_names_has_a_panel() -> None:
    plotted = set().union(*map(_series, _ws_panels()))
    assert [n for n in TICKET_SERIES if n in _BY_NAME and n not in plotted] == []
    # The one exception: once `cv_ws_errors_total` is catalogued (scraped), it needs a panel too.
    assert [n for n in TICKET_SERIES if n not in _BY_NAME] == ["cv_ws_errors_total"]


def test_every_ws_query_reads_live_series_with_their_own_labels_and_env() -> None:
    for panel in _ws_panels():
        for expr in _exprs(panel):
            named = {i for i in _IDENT.findall(expr) if i.startswith(("cv_ws_", "cvwb_"))}
            for name in named:
                spec = _BY_NAME.get(_base(name))
                assert spec is not None, f"{panel['title']}: {name} is not catalogued"
                assert spec.status == "live", f"{panel['title']}: {spec.name} is only planned"
            labels = {"le"}
            for sel in _SELECTOR.finditer(expr):
                spec = _BY_NAME[_base(sel["name"])]
                labels |= set(spec.labels)
                matched = [m["label"] for m in _MATCHER.finditer(sel["body"])]
                assert 'env="$env"' in sel["body"], f"{panel['title']}: {sel['name']} without env"
                assert set(matched) <= {*spec.labels, "env"}, f"{panel['title']}: {matched}"
            for grouping in _GROUPING.findall(expr):
                kept = {x.strip() for x in grouping.split(",") if x.strip()}
                assert kept <= labels, f"{panel['title']}: groups by {sorted(kept)}"


def test_each_ws_line_sits_at_its_documented_value() -> None:
    bandwidth_kib, bandwidth_mib = _ints(
        r"\| Server→client bandwidth, reference workspace\s*\| < (\d+) KiB/s sustained\s*"
        r"\| > (\d+) MiB/s"
    )
    size_kib, build_ms, size_mib, build_s = _doc(
        r"\| Full re-snapshot of the reference workspace\s*\| < (\d+) KiB, < (\d+) ms\s*"
        r"\| > (\d+) MiB or > ([\d.]+) s"
    )
    queue_from, queue_to, rtt_from, rtt_to = _ints(
        r"\| `lagging`\s*\| queue (\d+)\u2013(\d+) %, or RTT (\d+)\u2013(\d+) ms"
    )
    (skew,) = _ints(r"warning above ±(\d \d{3}) ms")
    (cap,) = _ints(r"\| Max subscriptions / connection\s*\| (\d+)")
    (frame_mib,) = _ints(r"\| Max outbound frame\s+\| (\d+) MiB")
    resync_target, resync_fail = _ints(
        r"\| Resyncs per hour per topic \(`upstream_desync`\) \| < (\d+)\s*\| > (\d+)"
    )
    handshake = re.fullmatch(r"p99 > (\d+)s", _BY_NAME["cv_ws_handshake_seconds"].alert)
    assert handshake
    assert (queue_from, rtt_from) == (LAGGING_QUEUE_PCT, LAGGING_RTT_MS)  # the code's own edges
    expected: dict[str, set[float]] = {
        "WS fan-out latency p95": {0.02},
        "WS resyncs in the range": {resync_target, resync_fail},
        "WS bandwidth per connection": {bandwidth_kib * _KIB, bandwidth_mib * _MIB},
        "WS client-reported sequence gaps": {1},
        "WS outbound queue depth p95": {queue_from / 100, queue_to / 100},
        "WS probe RTT p95": {rtt_from / 1000, rtt_to / 1000},
        "WS handshake p99": {float(handshake[1])},
        "WS client clock skew p99": {skew},
        "WS subscriptions per connection": {cap},
        "WS frame size p95": {frame_mib * _MIB},
        "WS snapshot build p99": {int(build_ms) / 1000, float(build_s)},
        "WS snapshot size p95": {int(size_kib) * _KIB, int(size_mib) * _MIB},
    }
    assert cap == MAX_SUBSCRIPTIONS and frame_mib * _MIB == MAX_OUTBOUND_FRAME_BYTES
    for panel in _ws_panels():
        lines = next((v for k, v in expected.items() if panel["title"].startswith(k)), set())
        assert _steps(panel) == lines, panel["title"]


def test_each_lined_ws_panel_draws_its_lines_and_names_them() -> None:
    """Colour is never the only signal (E04-S01): the lines are drawn, and the title says them."""
    lined = [p for p in _ws_panels() if _steps(p)]
    assert len(lined) == 12
    for panel in lined:
        style = panel["fieldConfig"]["defaults"]["custom"]["thresholdsStyle"]["mode"]
        assert style == "dashed", panel["title"]
        assert re.search(r"\((?:[^)]*; )?(?:lines?: |budget )", panel["title"]), panel["title"]


def test_the_queue_panel_divides_by_the_codes_default_budget() -> None:
    by_bytes, by_frames = _exprs(_panel("WS outbound queue depth p95"))
    assert by_bytes.endswith(f") / {QUEUE_BYTES}") and "cv_ws_queue_bytes_bucket" in by_bytes
    assert by_frames.endswith(f") / {QUEUE_FRAMES}") and "cv_ws_queue_frames_bucket" in by_frames


def test_the_bandwidth_panel_sums_only_the_two_codec_kinds_per_connection() -> None:
    """json and msgpack never count one frame twice; a CVWB kind repeats the frame's body."""
    (expr,) = _exprs(_panel("WS bandwidth per connection"))
    kinds = re.findall(r'kind=~"([^"]*)"', expr)
    assert kinds == [f"{JSON_KIND}|{MSGPACK_KIND}"]
    assert "cv_ws_frame_bytes_sum{" in expr and "[$__rate_interval]" in expr
    assert expr.endswith('/ clamp_min(sum(cv_ws_connections_in_use{env="$env"}), 1)')


def test_event_counts_over_the_range_are_whole_events() -> None:
    """As the WS alerts round them: `increase()` extrapolates, so five events read 5.08."""
    for panel in _ws_panels():
        for expr in _exprs(panel):
            if "[$__range]" in expr:
                assert re.fullmatch(r"round\(sum(?: by \(\w+\) )?\(increase\(.*\)\)\)", expr), expr


def test_the_flag_on_series_are_marked_as_such() -> None:
    """Class, depth, RTT and the merge series move only with the backpressure flag on."""
    rows = _rows()
    assert "flag on" in _panel("WS connections by class")["title"]
    queue_row = "WS queue, RTT and coalescing (backpressure flag on)"
    assert {s for p in rows[queue_row] for s in _series(p)} == {
        "cv_ws_queue_bytes",
        "cv_ws_queue_frames",
        "cv_ws_rtt_seconds",
        "cv_ws_conflated_total",
        "cv_ws_coalesced_updates",
    }
