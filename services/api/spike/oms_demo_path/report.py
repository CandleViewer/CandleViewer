"""`report` (#843 A4 brief item 4): the tables of a run, from its scrubbed `summary.json` only.

The findings PR quotes them: the RTT and our overhead per call class against budget #4, the
private stream's latency per kind, parity and ordering, the cycle outcomes, the soak's stream
counts, the error shapes and the retention reading.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_STATS = ("n", "p50", "p95", "p99", "max")


def _cell(value: object) -> str:
    return "" if value is None else str(value)


def _table(title: str, rows: Mapping[str, Any], columns: tuple[str, ...]) -> list[str]:
    if not rows:
        return []
    out = [f"### {title}", "", "| | " + " | ".join(columns) + " |"]
    out.append("|---" * (len(columns) + 1) + "|")
    for name, row in rows.items():
        values = row if isinstance(row, Mapping) else {"value": row}
        out.append(f"| {name} | " + " | ".join(_cell(values.get(c)) for c in columns) + " |")
    return [*out, ""]


def _pairs(title: str, values: Mapping[str, Any]) -> list[str]:
    return _table(title, {k: {"value": v} for k, v in values.items()}, ("value",))


def render(run_dir: Path) -> str:
    summary: dict[str, Any] = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    venue = "offline corpus venue" if summary.get("offline") else "demo venue"
    lines = [
        f"## E29-K01 harness run: {summary.get('mode')} ({venue})",
        "",
        f"Ended: {summary.get('shutdown', {}).get('reason', summary.get('refused', 'n/a'))}",
        "",
    ]
    lines += _table("Venue RTT at the seam (ms)", summary.get("rtt_ms", {}), _STATS)
    lines += _table("Port latency (ms)", summary.get("port_ms", {}), _STATS)
    lines += _table("Our overhead, port minus RTT (ms)", summary.get("overhead_ms", {}), _STATS)
    lines += _pairs("Budget #4 (create)", summary.get("budget4", {}))
    private = summary.get("private", {})
    lines += _table("Private stream latency (ms)", private.get("latency_ms", {}), _STATS)
    lines += _pairs("Execution parity (stream vs REST backfill)", private.get("parity", {}))
    lines += _pairs("Ordering (23 S5)", private.get("ordering", {}))
    lines += _pairs("Order transitions", private.get("transitions", {}))
    lines += _pairs("Stream statuses", private.get("statuses", {}))
    cycles = summary.get("cycles", {})
    lines += _pairs("Cycle outcomes", cycles.get("outcomes", {}))
    lines += _pairs("Cycle actions", cycles.get("actions", {}))
    soak = summary.get("soak", {})
    lines += _pairs("Soak", {k: v for k, v in soak.items() if not isinstance(v, Mapping)})
    for code, shape in summary.get("error_shapes", {}).items():
        lines += [f"### Reply shape {code}", "", "```json", json.dumps(shape, indent=2), "```", ""]
    lines += _pairs("Retention", {k: v for k, v in summary.get("retention", {}).items()})
    lines += _pairs("Shutdown", summary.get("shutdown", {}))
    lines += _pairs("Clock", summary.get("clock", {}))
    return "\n".join(lines) + "\n"
