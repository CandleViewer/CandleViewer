"""Outputs of an E29-K01 run: `summary.json` and `summary.md` (the tables for #843 and the
ADR-0006 §Validation addendum), CSVs of every REST call, cycle and stream item, a snapshot of
the metrics, and the scrubbed fixture staging."""

from __future__ import annotations

import csv
import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from candleviewer.exchange.bybit.mapping import map_ret_code
from candleviewer.observability.metrics import generate_latest

from .capture import Capture
from .stats import (
    EXEC_TOPICS,
    OrderingReport,
    Quantiles,
    backfill_only,
    check_ordering,
    latencies,
    quantiles,
)

if TYPE_CHECKING:
    from .runner import Harness

#: 06-performance §5.2 budget #4 on demo: the REST round trip's share, and the end-to-end p95.
RTT_ALLOCATION_MS: Final = 250.0
END_TO_END_P95_MS: Final = 300.0
_Q: Final = ["", "n", "p50", "p95", "p99"]


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


def build_report(h: Harness, rest: dict[str, str], outcome: str) -> dict[str, Any]:
    stats, rows = h.stream.stats, h.rows
    rtt: dict[str, list[float]] = {}
    for s in h.recorder.samples:
        rtt.setdefault(f"{s.op} {s.method} {s.path}", []).append(s.rtt_ms)
    p95 = quantiles(s.rtt_ms for s in h.recorder.samples if s.op == "create").p95
    mine = [it for it in h.items if it.symbol == h.symbol]
    parity = {}
    for topic in EXEC_TOPICS:
        ids = {it.exec_id for it in mine if it.topic == topic and it.exec_id}
        parity[topic] = {"streamed": len(ids), "rest_only": backfill_only(rest, ids)}
        parity[topic]["stream_only"] = len(ids - rest.keys())
    cycles = [r for r in rows if r["cycle"] >= 0]
    return {
        "mode": h.cfg.mode,
        "symbol": h.symbol,
        "window_ms": [h.started_ms, h.now_ms()],
        "outcome": outcome,
        "clock_offset_ms": [h.offset_ms, round(h.offset_err_ms, 1)],
        "budget_4": {
            "create_rtt_p95_ms": p95,
            "within_allocation": p95 is not None and p95 <= RTT_ALLOCATION_MS,
            "backend_headroom_ms": None if p95 is None else round(END_TO_END_P95_MS - p95, 1),
        },
        "rest_rtt_ms": {k: _q(quantiles(v)) for k, v in sorted(rtt.items())},
        "order_submit_ms": _q(quantiles(h.submit_ms)),
        "ws_latency_ms": {k: _q(v) for k, v in latencies(h.items).items()},
        "rest_executions": len(rest),
        "parity": parity,
        "ordering": {t: _ordering(check_ordering(mine, t)) for t in EXEC_TOPICS},
        "stream": {
            "connects": stats.connects,
            "drops": stats.drops,
            "pong_rtt_ms": _q(quantiles(stats.pong_rtt_ms)),
            "subscribed": stats.subscribed,
        },
        "errors": [
            _error(c) for c in h.recorder.captures.values() if c.status >= 400 or c.ret_code
        ],
        "cycles": {
            "cycles": len(cycles),
            "acked": sum(r.get("create") == "0" for r in cycles),
            "partial_fill": sum(bool(r.get("partial")) for r in cycles),
            "filled": sum(r.get("status") == "Filled" for r in cycles),
            "amended": sum(r.get("amend") == "0" for r in cycles),
            "cancelled": sum(r.get("cancel") == "0" for r in cycles),
            "flattens": len(rows) - len(cycles),
        },
        "notes": h.notes,
    }


def _csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(h: Harness, report: dict[str, Any]) -> None:
    out = h.cfg.out
    out.mkdir(parents=True, exist_ok=True)
    report["fixtures"] = [e["path"] for e in h.sink.write(h.recorder.captures)]
    report["ws_capture_withheld"] = h.sink.ws_withheld
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "summary.md").write_text(render(report), encoding="utf-8")
    (out / "metrics.prom").write_bytes(generate_latest(h.metrics.registry))
    _csv(out / "rest_calls.csv", [dataclasses.asdict(s) for s in h.recorder.samples])
    _csv(out / "orders.csv", h.rows)
    stand_in = h.scrubber.stand_in  # stream ids leave the process only as stand-ins
    items = [
        dataclasses.asdict(it)
        | {
            "order_id": stand_in("opaque", it.order_id),
            "link_id": stand_in("link", it.link_id),
            "exec_id": stand_in("opaque", it.exec_id),
        }
        for it in h.items
    ]
    _csv(out / "ws_items.csv", items)


def _f(value: object) -> str:
    if value is None:
        return "n/a"
    return f"{value:.1f}" if isinstance(value, float) else str(value).replace("|", "\\|")


def _table(head: list[str], rows: list[list[object]]) -> list[str]:
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    return [*lines, *("| " + " | ".join(_f(c) for c in row) + " |" for row in rows), ""]


def _quantiles(table: dict[str, dict[str, Any]]) -> list[str]:
    return _table(_Q, [[name, v["n"], v["p50"], v["p95"], v["p99"]] for name, v in table.items()])


def render(r: dict[str, Any]) -> str:
    start, end = (datetime.fromtimestamp(ms / 1000, UTC).isoformat() for ms in r["window_ms"])
    b, (offset, err) = r["budget_4"], r["clock_offset_ms"]
    verdict = "within" if b["within_allocation"] else "NOT within"
    subscribed = r["stream"]["subscribed"]
    parity = [[t, subscribed.get(t), p["streamed"], p["rest_only"] or 0, p["stream_only"]]
              for t, p in r["parity"].items()]  # fmt: skip
    order = [[t, o["executions"], o["violations"], o["unmatched"], o["lag_ms"]["p95"]]
             for t, o in r["ordering"].items()]  # fmt: skip
    errors = [[e["op"], e["call"], e["http"], e["retCode"], e["retMsg"], e.get("adapter"),
               e.get("retryable")] for e in r["errors"]]  # fmt: skip
    rest = {k: r[k] for k in ("stream", "cycles", "notes", "fixtures", "ws_capture_withheld")}
    return "\n".join(
        [
            f"# E29-K01 `{r['mode']}` run on {r['symbol']} (demo)",
            "",
            f"{start} to {end}: {r['outcome']}. Clock offset {offset} ms (±{err} ms).",
            "",
            "## Budget #4 (06-performance §5.2)",
            "",
            f"Demo `POST /v5/order/create` round trip p95: {_f(b['create_rtt_p95_ms'])} ms, "
            f"{verdict} the {RTT_ALLOCATION_MS:.0f} ms allocation. Backend headroom at p95 "
            f"inside {END_TO_END_P95_MS:.0f} ms: {_f(b['backend_headroom_ms'])} ms.",
            "",
            "## REST round trip per call (ms)",
            "",
            *_quantiles(r["rest_rtt_ms"]),
            "## order_submit_seconds: the create call with signing and governor (ms)",
            "",
            *_quantiles({"create": r["order_submit_ms"]}),
            "## Private stream: exchange stamp to receipt (ms)",
            "",
            *_quantiles(r["ws_latency_ms"]),
            f"## Execution parity: the REST backfill listed {r['rest_executions']}",
            "",
            *_table(["stream", "subscribed", "streamed", "REST-only (0)", "stream-only"], parity),
            "## Ordering, 23-ws S5: executions received after the order push they caused",
            "",
            *_table(["stream", "executions", "violations", "unmatched", "lag p95 ms"], order),
            "## Error shapes and the E08 adapter taxonomy",
            "",
            *_table(["op", "call", "HTTP", "retCode", "retMsg", "adapter", "retryable"], errors),
            "## Stream, cycles, notes, fixtures",
            "",
            "```json",
            json.dumps(rest, indent=2),
            "```",
            "",
        ]
    )
