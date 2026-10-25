"""`report` (#843 A4 brief item 4): the tables of a run, from its scrubbed `summary.json` only,
and the ADR-0006 §Validation addendum template filled with its numbers (`adr-0006-addendum.md`).

The findings PR quotes them: budget #4 judged by its own rule (the three p95s, the signing share
beside our overhead, the verdict, and the create's p95 by connection and by kind), the RTT (with
the failed exchanges per class), our overhead and the signing time per call class, the private
stream's latency per kind, parity, the two ordering counts kept apart, the cycle outcomes, the
soak's idle phase, the error shapes, the retention reading, the key-rights preflight and the
intent ledger's counts.

What the audit log holds (R1S-05): the harness drives the port directly, so `audit_log` gets one
`security.credential_borrowed` row per signed request (M2's write-ahead record), not one per
order action; the order actions are in the scrubbed `events.jsonl`, kept with the run's
artefacts. The addendum says so, and the findings PR must not claim order-action audit coverage.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from spike.oms_demo_path.measure import DROPPED_COUNT as DROPPED
from spike.oms_demo_path.measure import REORDER_COUNT as REORDER
from spike.oms_demo_path.outputs import Writer, write_file

ADDENDUM: Final = "adr-0006-addendum.md"
MISSING: Final = "missing"
NOT_EVIDENCE: Final = "offline corpus venue: not evidence"
_STATS = ("n", "p50", "p95", "p99", "max")
#: The audit coverage a run has, and what the findings may not claim (R1S-05).
AUDIT_NOTE: Final = (
    "Audit coverage: one `security.credential_borrowed` row per signed request, not one per"
    " order action (the harness drives the port directly). The order actions are in the"
    " scrubbed `events.jsonl`, kept with the run's artefacts; the findings PR must not claim"
    " order-action audit coverage."
)
#: The create's p95 split (`budget4.create_rtt_p95_ms_by_split`, R1C-06), as the report says it.
_SPLIT: Final = (
    ("create:cold", "cold"),
    ("create:warm", "warm"),
    ("create_open", "limit openers"),
    ("create_close", "reduce-only closes"),
)
_GAPS = ("n", "p50", "p95", "max", "over_threshold")
#: The two ordering counts (`StreamMonitor.ordering_counts`): each its question, never merged.
_QUESTIONS: Final = {
    REORDER: "Execution before its order transition (23 S5): a venue reorder, E29-T05's buffer",
    DROPPED: "Execution only via the backfill: a dropped push, ADR-0006's reconciliation",
}
#: Where the intent ledger's row falls (the coordinator's ruling 3 of fold 4), under the table.
LEDGER_NOTE: Final = (
    "Note: the ledger row's write and fsync happen before the measured window opens (no row, no"
    " order): none of these numbers holds them."
)
#: The budget table's rows: the create's stats per kind, and the budget its p95 is held to.
_BUDGET_ROWS: Final = (
    ("rtt_ms", "create RTT at the seam", "<= 250 ms"),
    ("overhead_ms", "our overhead, port minus RTT", "<= 50 ms"),
    ("signing_ms", "of which signing: M2's key read and fsynced audit append", "part of 50 ms"),
    ("port_ms", "end to end, port call to ack", "< 300 ms"),
)


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


def _load(run_dir: Path) -> dict[str, Any]:
    summary: dict[str, Any] = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    return summary


def _of(summary: Mapping[str, Any], *path: str) -> Any:
    """`summary[path[0]][path[1]]...`, or `None` where any step is missing."""
    value: Any = summary
    for key in path:
        value = value.get(key) if isinstance(value, Mapping) else None
    return value


def _num(value: object) -> str:
    return MISSING if value is None else str(value)


def _budget_rows(summary: Mapping[str, Any]) -> list[str]:
    out = ["| create, ms | n | p50 | p95 | max | budget |", "|---|---|---|---|---|---|"]
    for kind, label, held_to in _BUDGET_ROWS:
        row = _of(summary, kind, "create")
        cells = [_num(_of(row, k) if row else None) for k in ("n", "p50", "p95", "max")]
        out.append(f"| {label} | " + " | ".join(cells) + f" | {held_to} |")
    return out


def _split_line(summary: Mapping[str, Any]) -> str:
    split = _of(summary, "budget4", "create_rtt_p95_ms_by_split") or {}
    cells = [f"{label} {_num(split.get(key))}" for key, label in _SPLIT]
    return (
        f"Create RTT p95 by connection and kind (ms): {cells[0]}, {cells[1]}; {cells[2]},"
        f" {cells[3]}"
    )


def _verdict_line(summary: Mapping[str, Any]) -> str:
    budget = summary.get("budget4", {})
    tail = "" if budget.get("evidence") else f" ({NOT_EVIDENCE})"
    return f"Verdict: **{_num(budget.get('verdict'))}**{tail}"


def _budget(summary: Mapping[str, Any]) -> list[str]:
    budget = summary.get("budget4")
    if not isinstance(budget, Mapping):
        return []
    rule = f"Rule: {_num(budget.get('rule'))}"
    rows = _budget_rows(summary)
    split = _split_line(summary)
    return [
        "### Budget #4 (create)",
        "",
        *rows,
        "",
        LEDGER_NOTE,
        "",
        split,
        "",
        rule,
        "",
        _verdict_line(summary),
        "",
    ]


def _ordering_counts(private: Mapping[str, Any]) -> list[str]:
    counts = private.get("ordering_counts")
    if not isinstance(counts, Mapping):
        return []
    out = ["### Two ordering counts, kept apart", "", "| count | value | question |"]
    out.append("|---|---|---|")
    out += [f"| {name} | {_num(counts.get(name))} | {q} |" for name, q in _QUESTIONS.items()]
    return [*out, ""]


def _idle_phase(idle: object) -> list[str]:
    if not isinstance(idle, Mapping):
        return []
    lines = ["### Soak idle phase (ADR-0006 S3: zero missed executions)", ""]
    lines += [f"Zero missed executions: **{_num(idle.get('zero_missed_executions'))}**", ""]
    lines += ["| | value |", "|---|---|"]
    lines += [f"| {k} | {_cell(v)} |" for k, v in idle.items() if not isinstance(v, Mapping)]
    backfill = idle.get("backfill")
    if isinstance(backfill, Mapping):
        lines.append("| backfill | " + ", ".join(f"{k} {v}" for k, v in backfill.items()) + " |")
    lines.append("")
    named = ("ping_gaps_s", "message_gaps_s")
    gaps = {k: idle[k] for k in named if isinstance(idle.get(k), Mapping)}
    return lines + _table("Soak idle phase: ping and message gaps (s)", gaps, _GAPS)


def render(run_dir: Path) -> str:
    summary = _load(run_dir)
    venue = "offline corpus venue" if summary.get("offline") else "demo venue"
    ended = summary.get("shutdown", {}).get("reason", summary.get("refused", "n/a"))
    lines = [f"## E29-K01 harness run: {summary.get('mode')} ({venue})", "", f"Ended: {ended}", ""]
    if summary.get("outcome") == "refused":  # ruling R1C-02 (a): nothing touched, and why
        lines += [f"Refused, nothing touched: {summary.get('refused')}", ""]
    lines += _budget(summary)
    rtt = summary.get("rtt_ms", {})
    lines += _table("Venue RTT at the seam (ms)", rtt, (*_STATS, "failed"))
    lines += _table(
        "Venue RTT by connection and kind (ms)", summary.get("rtt_split_ms", {}), _STATS
    )
    lines += _table("Port latency (ms)", summary.get("port_ms", {}), _STATS)
    lines += _table("Our overhead, port minus RTT (ms)", summary.get("overhead_ms", {}), _STATS)
    signing = summary.get("signing_ms", {})
    lines += _table("Signing: M2's key read and fsynced audit append (ms)", signing, _STATS)
    private = summary.get("private", {})
    lines += _table("Private stream latency (ms)", private.get("latency_ms", {}), _STATS)
    lines += _pairs("Execution parity (stream vs REST backfill)", private.get("parity", {}))
    lines += _ordering_counts(private)
    lines += _pairs("Ordering (23 S5)", private.get("ordering", {}))
    lines += _pairs("Order transitions", private.get("transitions", {}))
    lines += _pairs("Stream statuses", private.get("statuses", {}))
    cycles = summary.get("cycles", {})
    lines += _pairs("Cycle outcomes", cycles.get("outcomes", {}))
    lines += _pairs("Cycle actions", cycles.get("actions", {}))
    soak = summary.get("soak", {})
    lines += _pairs("Soak", {k: v for k, v in soak.items() if not isinstance(v, Mapping)})
    lines += _idle_phase(soak.get("idle_phase"))
    for code, shape in summary.get("error_shapes", {}).items():
        lines += [f"### Reply shape {code}", "", "```json", json.dumps(shape, indent=2), "```", ""]
    lines += _pairs("Retention", {k: v for k, v in summary.get("retention", {}).items()})
    lines += _pairs("Key rights preflight (C-2.8)", summary.get("key_check") or {})
    lines += _pairs("Intent ledger (no row, no order)", summary.get("ledger") or {})
    lines += _pairs("Shutdown", summary.get("shutdown", {}))
    lines += _pairs("Clock", summary.get("clock", {}))
    return "\n".join(lines) + "\n"


# -- the ADR-0006 §Validation addendum template ----------------------------------------------


def _started(summary: Mapping[str, Any]) -> str:
    ms = summary.get("started_at_ms")
    if not isinstance(ms, int):
        return MISSING
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def _heading(title: str, offline: bool) -> str:
    return f"#### {title}" + (f" ({NOT_EVIDENCE})" if offline else "")


def _addendum_budget(summary: Mapping[str, Any], offline: bool) -> list[str]:
    budget = summary.get("budget4", {})
    lines = [_heading("Budget #4 (`06` §5.2)", offline), ""]
    lines += [f"Rule (#843, agreed up front): {_num(budget.get('rule'))}", ""]
    lines += [*_budget_rows(summary), "", LEDGER_NOTE, "", _split_line(summary), ""]
    lines += [_verdict_line(summary), ""]
    return lines


def _consequence(count: object, then: str) -> str:
    if not isinstance(count, int):
        return f"{MISSING}: no execution was measured."
    return f"Non-zero: {then}" if count else "None in this run."


def _injected(summary: Mapping[str, Any], key: str) -> str:
    """The offline venue's own injection behind a count, so a planted one is never read as a
    finding."""
    every = _of(summary, "offline_venue", "injected", key)
    return f" The offline venue injected one every {every} fills." if every else ""


def _addendum_counts(summary: Mapping[str, Any], offline: bool) -> list[str]:
    counts = _of(summary, "private", "ordering_counts") or {}
    ordering, parity = _of(summary, "private", "ordering"), _of(summary, "private", "parity")
    reorder, dropped = counts.get(REORDER), counts.get(DROPPED)
    buffer = "E29-T05 gains a reorder buffer keyed on `(ts_exec, seq)` (#843)."
    cadence = "the reconciliation cadence is revised in ADR-0006 before E29-T06 starts (#843)."
    return [
        _heading("Execution before its order transition (23 §S5): venue reorders", offline),
        "",
        f"`{REORDER}`: **{_num(reorder)}** of {_num(_of(ordering, 'executions'))} executions on"
        f" the stream came after the order transition they caused. {_consequence(reorder, buffer)}"
        + _injected(summary, "reorder_every"),
        "",
        _heading("Execution only via the backfill: dropped pushes", offline),
        "",
        f"`{DROPPED}`: **{_num(dropped)}** of {_num(_of(parity, 'rest'))} executions"
        " `GET /v5/execution/list` listed never came on the stream (target zero)."
        f" {_consequence(dropped, cadence)}" + _injected(summary, "drop_every"),
        "",
    ]


def _addendum_soak(summary: Mapping[str, Any], offline: bool) -> list[str]:
    lines = [_heading("Soak idle phase: zero missed executions (Spike S3)", offline), ""]
    idle = _of(summary, "soak", "idle_phase")
    if not isinstance(idle, Mapping):
        mode = summary.get("mode")
        return [*lines, f"{MISSING}: this is a `{mode}` run; a `soak` run's summary has it.", ""]
    soak = summary["soak"]
    ping, message = idle.get("ping_gaps_s") or {}, idle.get("message_gaps_s") or {}

    def gaps(name: str, row: Mapping[str, Any]) -> str:
        values = ", ".join(f"{k} {_num(row.get(k))}" for k in _GAPS[:4])
        over = _num(row.get("over_threshold"))
        return f"- {name} gaps (s): {values}; over {_num(idle.get('long_silence_s'))} s: {over}."

    return [
        *lines,
        f"- Window: {_num(soak.get('hours'))} h asked (the ticket's 24 h:"
        f" {'met' if soak.get('meets_ticket') else 'not met'}), the stream held"
        f" {_num(idle.get('held_s'))} s; orders sent: {_num(idle.get('orders_sent'))}.",
        f"- Dials: {_num(idle.get('dials'))}; reconnects: {_num(idle.get('reconnects'))};"
        f" outages: {_num(idle.get('outages'))}.",
        gaps("Ping", ping),
        gaps("Message", message),
        f"- Executions only via the backfill over the window:"
        f" {_num(idle.get('backfill_only_executions'))}.",
        f"- **Zero missed executions: {_num(idle.get('zero_missed_executions'))}.**",
        "",
    ]


def _addendum_shapes(summary: Mapping[str, Any], offline: bool) -> list[str]:
    shapes = summary.get("error_shapes", {})
    probes = summary.get("shapes", {})
    named = (
        (("10002",), "clock drift", _of(probes, "10002", "raised")),
        (("110072", "10001"), "duplicate `orderLinkId`", _of(probes, "duplicate", "raised")),
        (("10018",), "rate limit, never provoked", None),
    )
    lines = [_heading("Error shapes", offline), "", "| retCode | reply shape | the port raised |"]
    lines.append("|---|---|---|")
    for codes, what, raised in named:
        held = [code for code in codes if code in shapes]
        shape = f"captured: {', '.join(held)} (`summary.error_shapes`)" if held else MISSING
        lines.append(f"| {' / '.join(codes)} ({what}) | {shape} | {_num(raised)} |")
    known = {code for codes, _, _ in named for code in codes}
    others = [code for code in shapes if code not in known]
    lines.append(f"| other codes met | {', '.join(others) if others else 'none'} | |")
    return [*lines, "", "10018 is captured only if a run meets one.", ""]


def _addendum_retention(summary: Mapping[str, Any], offline: bool) -> list[str]:
    lines = [_heading("Retention (24 §8.3 rule 6)", offline), ""]
    retention = summary.get("retention")
    if not isinstance(retention, Mapping):
        return [*lines, f"{MISSING}: a `retention` run on day 8 or later carries it.", ""]
    return [
        *lines,
        f"{_num(retention.get('rows'))} orders read back since the run's start;"
        f" {_num(retention.get('older_than_7d'))} older than 7 days; by state:"
        f" {_num(retention.get('by_state'))}.",
        "",
    ]


def addendum(run_dir: Path) -> str:
    """The template of ADR-0006 §Validation's "Spike S3" addendum, filled from one run's
    summary: each number measured, `missing` where this run measured none, and every section
    marked when the run was offline (an offline number is never evidence)."""
    summary = _load(run_dir)
    offline = summary.get("offline") is not False
    venue = "the offline corpus venue" if offline else "the demo venue"
    ended = _of(summary, "shutdown", "reason") or summary.get("refused") or MISSING
    lines = [
        "<!-- A template for ADR-0006 §Validation (the Spike S3 bullet), filled by the E29-K01",
        "harness's `report` from one run's scrubbed summary.json. Review every line first. -->",
        "",
        f"### Validation addendum: Spike S3 (E29-K01, #843), a `{summary.get('mode')}` run",
        "",
        f"Run on {venue}, started {_started(summary)}, ended: {ended}.",
        "",
    ]
    if offline:
        lines += [f"**Offline run: every number below comes from {venue}; offline numbers"]
        lines += ["are never evidence. The demo host's run replaces them.**", ""]
    lines += [f"Note: {AUDIT_NOTE}", ""]
    lines += _addendum_budget(summary, offline)
    lines += _addendum_counts(summary, offline)
    lines += _addendum_soak(summary, offline)
    lines += _addendum_shapes(summary, offline)
    lines += _addendum_retention(summary, offline)
    return "\n".join(lines)


def write_addendum(run_dir: Path, out: Path, write: Writer = write_file) -> Path:
    """`adr-0006-addendum.md` in `out` (made `0700` if new; the file `0600`)."""
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = out / ADDENDUM
    write(path, addendum(run_dir).encode(), False)
    return path
