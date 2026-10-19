"""Outputs of an E29-K01 run: `summary.json` and `summary.md` (the tables for #843 and the
ADR-0006 §Validation addendum), CSVs of every REST call, order, cycle, stream item and REST
execution, a snapshot of the metrics, and the scrubbed fixture staging. Every output has the
run's known values masked and passes the scrubber's leak check, or is withheld (C-12.2): the
summary goes on a public issue. The REST call, order and cycle CSVs are not written here: the run
appends to them as it goes (`journal.py`), so one that was aborted or killed still has them."""

from __future__ import annotations

import csv
import dataclasses
import io
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import structlog

from candleviewer.exchange.bybit.mapping import map_ret_code
from candleviewer.observability.metrics import generate_latest

from .capture import Capture
from .scrub import LeakError
from .stats import (
    EXEC_TOPICS,
    OVERLAP_MS,
    OrderingReport,
    Quantiles,
    RestExecution,
    backfill_only,
    check_ordering,
    delivering_at,
    down_windows,
    latencies,
    quantiles,
    split_rest_only,
)

if TYPE_CHECKING:
    from .runner import Harness

#: 06-performance §5.2 budget #4 on demo: the REST round trip's share, and the end-to-end p95.
RTT_ALLOCATION_MS: Final = 250.0
END_TO_END_P95_MS: Final = 300.0
_Q: Final = ["", "n", "p50", "p95", "p99"]


def _log() -> Any:
    return structlog.get_logger(__name__)


def budget_4(p95: float | None) -> dict[str, Any]:
    """Budget #4 on demo: the create round trip's p95 against its 250 ms allocation, and the
    backend headroom left inside the 300 ms end-to-end p95. No creates, no verdict (`None`)."""
    if p95 is None:
        return {"create_rtt_p95_ms": None, "within_allocation": None, "backend_headroom_ms": None}
    return {
        "create_rtt_p95_ms": p95,
        "within_allocation": p95 <= RTT_ALLOCATION_MS,
        "backend_headroom_ms": round(END_TO_END_P95_MS - p95, 1),
    }


def _q(value: Quantiles) -> dict[str, Any]:
    """Quantiles as a dict, in ms to 0.1."""
    return {
        k: round(v, 1) if isinstance(v, float) else v for k, v in dataclasses.asdict(value).items()
    }


def _ordering(report: OrderingReport) -> dict[str, Any]:
    return {**dataclasses.asdict(report), "lag_ms": _q(report.lag_ms)}


def _error(c: Capture) -> dict[str, Any]:
    entry: dict[str, Any] = {"op": c.op, "call": f"{c.method} {c.path}", "http": c.status}
    entry |= {"retCode": c.ret_code, "retMsg": c.ret_msg}
    if c.ret_code is not None:
        mapped = map_ret_code(c.ret_code, c.ret_msg)
        entry |= {"adapter": f"{type(mapped).__name__} ({mapped.code.value})"}
        entry |= {"retryable": mapped.retryable}
    return entry


def build_report(h: Harness, rest: Mapping[str, RestExecution], outcome: str) -> dict[str, Any]:
    stats, rows = h.stream.stats, h.rows
    rtt: dict[str, list[float]] = {}
    for s in h.recorder.samples:
        rtt.setdefault(f"{s.op} {s.method} {s.path}", []).append(s.rtt_ms)
    p95 = quantiles(s.rtt_ms for s in h.recorder.samples if s.op == "create").p95
    mine = [it for it in h.items if it.symbol == h.symbol]
    live = [(begin, end) for begin, end in stats.live]
    listed = h.backfill_error is None
    parity: dict[str, dict[str, Any]] = {}
    for topic in EXEC_TOPICS:
        ids = {it.exec_id for it in mine if it.topic == topic and it.exec_id}
        parity[topic] = {"streamed": len(ids)}
        if listed:
            parity[topic]["rest_only"] = backfill_only(rest, ids)
            parity[topic]["rest_only_when"] = split_rest_only(rest, ids, live)
            parity[topic]["stream_only"] = len(ids - rest.keys())
        else:  # no listing: no count that needs one, and none of them may read as zero
            parity[topic] |= {"rest_only": None, "rest_only_when": None, "stream_only": None}
    cycles = [r for r in rows if r["cycle"] >= 0]
    partial = {it.link_id for it in mine if it.topic == "order" and it.status == "PartiallyFilled"}
    start, end = h.started_ms, h.now_ms()
    return {
        "mode": h.cfg.mode,
        "symbol": h.symbol,
        "window_ms": [start, end],
        "outcome": outcome,
        "stop_reason": h.stop_reason,
        "clock_offset_ms": [h.offset_ms, round(h.offset_err_ms, 1)],
        "budget_4": budget_4(p95),
        "rest_rtt_ms": {k: _q(quantiles(v)) for k, v in sorted(rtt.items())},
        "order_submit_ms": _q(quantiles(h.submit_ms)),
        "ws_latency_ms": {k: _q(v) for k, v in latencies(h.items).items()},
        "rest_executions": len(rest) if listed else None,
        "rest_backfill_error": h.backfill_error,
        "parity": parity,
        "ordering": {t: _ordering(check_ordering(mine, t)) for t in EXEC_TOPICS},
        "stream": {
            "connects": stats.connects,
            "drops": stats.drops,
            "live_ms": live,
            "down_ms": down_windows(live, start - OVERLAP_MS, end),
            "pong_rtt_ms": _q(quantiles(stats.pong_rtt_ms)),
            "subscribed": stats.subscribed,
        },
        "errors": [
            _error(c) for c in h.recorder.captures.values() if c.status >= 400 or c.ret_code
        ],
        "cycles": {
            "cycles": len(cycles),
            "acked": sum(r.get("create") == "0" for r in cycles),
            "partial_fill_stream": sum(r.get("order_link_id") in partial for r in cycles),
            "partial_fill_rest": sum(bool(r.get("partial")) for r in cycles),
            "filled": sum(r.get("status") == "Filled" for r in cycles),
            "amended": sum(r.get("amend") == "0" for r in cycles),
            "cancelled": sum(r.get("cancel") == "0" for r in cycles),
            "failed": sum("error" in r for r in cycles),
            "flattens": len(rows) - len(cycles),
        },
        "notes": h.notes,
    }


def _csv(rows: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def _write(h: Harness, path: Path, text: str) -> None:
    """`text` with the run's known values masked, then leak-checked; a file that still fails the
    check is withheld: what is written names the failed checks only."""
    try:
        text = h.scrubber.check(h.scrubber.mask_known(text))
    except LeakError as exc:
        _log().warning("output_withheld", file=path.name, patterns=exc.patterns)
        text = f"withheld by the leak check: {', '.join(exc.patterns)}\n"
    path.write_text(text, encoding="utf-8", newline="")


def write_outputs(h: Harness, report: dict[str, Any], rest: Mapping[str, RestExecution]) -> None:
    out = h.cfg.out
    out.mkdir(parents=True, exist_ok=True)
    report["fixtures"] = [e["path"] for e in h.sink.write(h.recorder.captures)]
    report["ws_capture_withheld"] = h.sink.ws_withheld
    _write(h, out / "summary.json", json.dumps(report, indent=2) + "\n")
    _write(h, out / "summary.md", render(report))
    _write(h, out / "metrics.prom", generate_latest(h.metrics.registry).decode())
    stand_in = h.scrubber.stand_in  # exchange ids leave the process only as stand-ins
    items = [
        dataclasses.asdict(it)
        | {
            "order_id": stand_in("opaque", it.order_id),
            "link_id": stand_in("link", it.link_id),
            "exec_id": stand_in("opaque", it.exec_id),
        }
        for it in h.items
    ]
    _write(h, out / "ws_items.csv", _csv(items))
    _write(h, out / "rest_executions.csv", _csv(_rest_rows(h, rest)))


def _rest_rows(h: Harness, rest: Mapping[str, RestExecution]) -> list[dict[str, Any]]:
    """One row per REST execution: whether the stream was delivering when it happened, and on
    which execution topic the stream delivered it."""
    live = [(begin, end) for begin, end in h.stream.stats.live]
    seen = {t: {it.exec_id for it in h.items if it.topic == t} for t in EXEC_TOPICS}
    rows = []
    for exec_id, row in sorted(rest.items(), key=lambda kv: kv[1].exec_ms or 0):
        state = delivering_at(row.exec_ms, live)
        rows.append(
            {
                "exec_id": h.scrubber.stand_in("opaque", exec_id),
                "exec_type": row.exec_type,
                "exec_ms": row.exec_ms,
                "stream": "" if state is None else "connected" if state else "down",
            }
            | {f"on_{t.replace('.', '_')}": exec_id in seen[t] for t in EXEC_TOPICS}
        )
    return rows


def _f(value: object) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}" if isinstance(value, float) else str(value).replace("|", "\\|")


def _table(head: list[str], rows: list[list[object]]) -> list[str]:
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    return [*lines, *("| " + " | ".join(_f(c) for c in row) + " |" for row in rows), ""]


def _quantiles(table: dict[str, dict[str, Any]]) -> list[str]:
    return _table(_Q, [[name, v["n"], v["p50"], v["p95"], v["p99"]] for name, v in table.items()])


def _budget(r: dict[str, Any]) -> list[str]:
    """The budget #4 and `order_submit_seconds` sections; none for a run with no creates."""
    b = r["budget_4"]
    if b["create_rtt_p95_ms"] is None:
        return []
    verdict = "within" if b["within_allocation"] else "NOT within"
    return [
        "## Budget #4 (06-performance §5.2)",
        "",
        f"Demo `POST /v5/order/create` round trip p95: {_f(b['create_rtt_p95_ms'])} ms, "
        f"{verdict} the {RTT_ALLOCATION_MS:.0f} ms allocation. Backend headroom at p95 "
        f"inside {END_TO_END_P95_MS:.0f} ms: {_f(b['backend_headroom_ms'])} ms.",
        "",
        "## order_submit_seconds: the create call with signing and governor (ms)",
        "",
        *_quantiles({"create": r["order_submit_ms"]}),
    ]


def _rest_cells(p: dict[str, Any]) -> list[object]:
    """The cells of a parity row that need the REST listing: `None` (n/a) when it failed."""
    if p["rest_only"] is None:
        return [None] * 4
    when = p["rest_only_when"]
    return [p["rest_only"] or 0, when["while_connected"], when["stream_down"], p["stream_only"]]


def _parity_head(r: dict[str, Any]) -> list[str]:
    """The heading of the parity section and how to read it; a failed backfill says so first."""
    if r["rest_backfill_error"] is not None:
        return [
            f"## Execution parity: the REST backfill FAILED ({r['rest_backfill_error']})",
            "",
            "No REST-only count was measured: the #843 AC2 number is missing, and every cell "
            "below that needs the backfill reads n/a, not 0.",
            "",
        ]
    return [
        f"## Execution parity: the REST backfill listed {r['rest_executions']}",
        "",
        "A REST-only execution that happened while the stream was delivering (`connected`) is "
        "evidence against the stream as the source of truth. One inside a down window "
        "(`down`: before the first connect, from a drop's last frame to the next connect, "
        "after the stop) is expected: the harness does not resync. `stream.down_ms` lists the "
        "windows; `rest_executions.csv` places each execution.",
        "",
    ]


def _stop_reason(r: dict[str, Any]) -> list[str]:
    """The first reason the run stopped, when the outcome does not already say it: a stop request
    that came after it, and cut the cleanup short, turns the outcome into `interrupted`."""
    reason = r["stop_reason"]
    if reason is None or reason in r["outcome"]:
        return []
    return [f"First stop reason: {reason}.", ""]


def _duplicate(r: dict[str, Any]) -> list[str]:
    """The duplicate-`orderLinkId` reply is an acceptance criterion of #843: a run that could not
    capture it says so among the error shapes, in the words of its note."""
    note = r["notes"].get("duplicate_order_link_id")
    if not isinstance(note, str) or not note.startswith("not captured"):
        return []
    return [f"duplicate_order_link_id: {note}", ""]


def _partial(r: dict[str, Any]) -> list[str]:
    """How many cycles saw a partial fill; nothing for a run with no cycles."""
    c = r["cycles"]
    if not c["cycles"]:
        return []
    return [
        f"Cycles with a partial fill: {c['partial_fill_stream']} by the stream's `order` pushes "
        f"({c['partial_fill_rest']} by the REST status at lookup). Zero means this run did not "
        "observe the S5 ordering of a partial fill.",
        "",
    ]


def render(r: dict[str, Any]) -> str:
    start, end = (datetime.fromtimestamp(ms / 1000, UTC).isoformat() for ms in r["window_ms"])
    offset, err = r["clock_offset_ms"]
    subscribed = r["stream"]["subscribed"]
    parity = [
        [t, subscribed.get(t), p["streamed"], *_rest_cells(p)] for t, p in r["parity"].items()
    ]
    order = [[t, o["executions"], o["violations"], o["unmatched"], o["lag_ms"]["p95"]]
             for t, o in r["ordering"].items()]  # fmt: skip
    errors = [[e["op"], e["call"], e["http"], e["retCode"], e["retMsg"], e.get("adapter"),
               e.get("retryable")] for e in r["errors"]]  # fmt: skip
    rest = {k: r[k] for k in ("stream", "cycles", "notes", "fixtures", "ws_capture_withheld")}
    head = ["stream", "subscribed", "streamed", "REST-only (0)", "connected", "down", "stream-only"]
    return "\n".join(
        [
            f"# E29-K01 `{r['mode']}` run on {r['symbol']} (demo)",
            "",
            f"{start} to {end}: {r['outcome']}. Clock offset {offset} ms (±{err} ms).",
            "",
            *_stop_reason(r),
            *_budget(r),
            "## REST round trip per call (ms)",
            "",
            *_quantiles(r["rest_rtt_ms"]),
            "## Private stream: exchange stamp to receipt (ms)",
            "",
            *_quantiles(r["ws_latency_ms"]),
            *_parity_head(r),
            *_table(head, parity),
            "## Ordering, 23-ws S5: executions received after the order push they caused",
            "",
            *_partial(r),
            *_table(["stream", "executions", "violations", "unmatched", "lag p95 ms"], order),
            "## Error shapes and the E08 adapter taxonomy",
            "",
            *_duplicate(r),
            *_table(["op", "call", "HTTP", "retCode", "retMsg", "adapter", "retryable"], errors),
            "## Stream, cycles, notes, fixtures",
            "",
            "```json",
            json.dumps(rest, indent=2),
            "```",
            "",
        ]
    )
