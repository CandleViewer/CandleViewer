"""E42-Q03 (#1216): judge the audit profile's runs from k6's point files [BQ-1, BQ-2, BQ-10].

    python tests/load/admin/results.py judge RUN_DIR [RUN_DIR ...] --out DIR \
        [--database NAME --mode bulk|chained --rows N]

Each run directory holds k6's `points.json` (`--out json=`, one JSON object a line). Only `Point`
lines of `cv_admin_audit_ms` count, keyed by their `combo`, `pos` and `cls` tags; the warm-up call
(tag `warm` = "1") is dropped. A sample is a duration only when its tag `ok` is exactly "1" (a 200
with a page of at most `limit` items, not vacuous unless sparse: `pageOk` in the k6 lib) and its
value a finite, non-negative number; any other sample is a failed call, never a duration: its key
is ERRORS, never a pass. Per run and key: N, p50, p95, p99 and max,
nearest-rank (06 section 7.4). The figure of record is the median over the runs of each statistic
(the median of 3). The verdict is the median p95 against its class's budget, at most: `common`
400 ms, `q` 2 s (SCR-135 "<=400 ms", US-ADMIN-009 "<=2 s", ADR-0025). A key without `SAMPLES`
samples in every run is INCOMPLETE, never a pass: the keys judged are the profile's whole plan
(`PLANNED`, the k6 `plan()` of 14 combinations at page 1 and deep), so a key a run lacks reads
INCOMPLETE too.

[BQ-1] ruled: two rows miss their budget by design until ADR-0025's follow-ups land (both #889's).
`severity_actor` reads FAIL (#1710). `q_selective` hits the server's 4 s stop as a 503, which is
not a duration, so its row reads ERRORS (or FAIL if the call ever answers 200 over budget); both
wait on #1711. They are judged like every other row, never skipped or widened; the table names the
issue they wait on. A statistic with no 200 sample behind it is null in results.json, n/a in the
table.
[BQ-10] Nothing is gated on a baseline yet: the budgets are absolute.

Writes `results.json` and `results.md` to `--out`, each naming the database, mode and rows it
measured: only `bulk` at `FULL_ROWS` rows is the verdict; any other run is a CONTROL, not a
verdict. Exit 0: every row passes; 1: a row fails or is
incomplete; 2: nothing to judge (no points, or a key the plan does not have).
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

METRIC: Final = "cv_admin_audit_ms"
BUDGET_MS: Final = {"common": 400.0, "q": 2000.0}
SAMPLES: Final = 20
FULL_ROWS: Final = 10_000_000  # AUDIT-10M: the only size the budgets are judged at
STATS: Final = ("p50", "p95", "p99", "max")
#: [BQ-1] the combinations K01 measured over budget on the indexes main has, and what fixes each.
WAITS_ON: Final = {"severity_actor": "#1710", "q_selective": "#1711"}
#: The profile's combinations and their class (`tests/load/k6/admin/lib/combos.js`, pinned equal).
COMBOS: Final = {
    "unfiltered": "common", "range": "common", "actor": "common", "action": "common",
    "action_range": "common", "actor_action": "common", "actor_action_range": "common",
    "severity": "common", "severity_actor": "common", "subject": "common",
    "outcome_action": "common", "ip": "common", "q_selective": "q", "q_common": "q",
}  # fmt: skip
PLANNED: Final = frozenset((c, pos, cls) for c, cls in COMBOS.items() for pos in ("page1", "deep"))
RESULTS_JSON: Final = "results.json"
RESULTS_MD: Final = "results.md"

Key = tuple[str, str, str]  # (combo, pos, cls)
Sample = float | None  # None: not a duration (a failed call)


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile, q in 0..100 (with fewer than 100 samples p99 is the max)."""
    if not values:
        raise ValueError("no samples")
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q / 100.0 * len(ordered))) - 1]


def read_points(lines: Iterable[str]) -> dict[Key, list[Sample]]:
    """The measured samples per key, warm-up dropped; a failed call is None."""
    out: dict[Key, list[Sample]] = defaultdict(list)
    for line in lines:
        if not line.strip():
            continue
        point = json.loads(line)
        if point.get("type") != "Point" or point.get("metric") != METRIC:
            continue
        data = point["data"]
        tags = data.get("tags") or {}
        if tags.get("warm") != "0":
            continue
        out[(str(tags["combo"]), str(tags["pos"]), str(tags["cls"]))].append(
            _duration(tags.get("ok"), data.get("value"))
        )
    return dict(out)


def _duration(ok: object, value: object) -> Sample:
    """The sample's duration, or None: only an `ok` of exactly "1" and a finite, non-negative
    number (never a boolean) is one."""
    if ok != "1" or isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def run_stats(samples: Sequence[Sample]) -> dict[str, float | None]:
    ok = [v for v in samples if v is not None]
    stats: dict[str, float | None] = {s: None for s in STATS}  # none: no 200 sample behind it
    if ok:
        stats = {s: max(ok) if s == "max" else percentile(ok, float(s[1:])) for s in STATS}
    return {"n": float(len(samples)), "errors": float(len(samples) - len(ok)), **stats}


def _median(values: Sequence[float | None]) -> float | None:
    """The median, or None when any run has no figure (never a NaN, which is not JSON)."""
    if any(v is None for v in values):
        return None
    return statistics.median(v for v in values if v is not None)


def judge(runs: Sequence[dict[Key, list[Sample]]]) -> list[dict[str, object]]:
    """One row per planned key, the median over the runs of each statistic, and its verdict."""
    if not runs or not any(runs) or any(set(r) - PLANNED for r in runs):
        raise ValueError("nothing to judge: no points, or a key the plan does not have")
    rows: list[dict[str, object]] = []
    for key in sorted(PLANNED):
        combo, pos, cls = key
        per_run = [run_stats(r.get(key, [])) for r in runs]
        row: dict[str, object] = {"combo": combo, "pos": pos, "cls": cls, "runs": len(runs)}
        med = {s: _median([p[s] for p in per_run]) for s in STATS}
        row.update(med)
        row["budget_p95_ms"] = BUDGET_MS[cls]
        if any(p["errors"] for p in per_run):
            verdict = "ERRORS"
        elif any(p["n"] != SAMPLES for p in per_run) or med["p95"] is None:
            verdict = "INCOMPLETE"
        else:
            verdict = "PASS" if float(str(med["p95"])) <= BUDGET_MS[cls] else "FAIL"
        row["verdict"] = verdict
        row["waits_on"] = WAITS_ON.get(combo, "") if verdict != "PASS" else ""
        rows.append(row)
    return rows


def scope(database: str, mode: str, rows: int | None) -> dict[str, object]:
    """What a results file measured, and whether it is the verdict or a control."""
    verdict = mode == "bulk" and rows == FULL_ROWS
    return {"database": database, "mode": mode, "rows": rows, "kind": "verdict" if verdict
            else "CONTROL, not a verdict"}  # fmt: skip


def render(rows: Sequence[dict[str, object]], measured: dict[str, object]) -> str:
    size = "rows unknown" if measured["rows"] is None else f"{measured['rows']} rows"
    title = f"Dataset: {measured['database']} ({measured['mode']}, {size}): {measured['kind']}"
    head = (
        "| combo | pos | class | budget p95 | p50 | p95 | p99 | max | runs | verdict | waits on |"
    )
    lines = [title, "", head, "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        ms = " | ".join("n/a" if r[s] is None else f"{float(str(r[s])):.1f} ms" for s in STATS)
        lines.append(
            f"| {r['combo']} | {r['pos']} | {r['cls']} | {float(str(r['budget_p95_ms'])):.0f} ms"
            f" | {ms} | {r['runs']} | {r['verdict']} | {r['waits_on']} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="cmd", required=True)
    cmd = sub.add_parser("judge")
    cmd.add_argument("runs", nargs="+", type=Path)
    cmd.add_argument("--out", type=Path, required=True)
    cmd.add_argument("--database", default="unknown")
    cmd.add_argument("--mode", default="unknown")
    cmd.add_argument("--rows", type=int)
    args = parser.parse_args(argv)
    try:
        runs = []
        for run in args.runs:
            with (run / "points.json").open(encoding="utf-8") as fh:
                runs.append(read_points(fh))
        rows = judge(runs)
    except (OSError, ValueError, KeyError) as exc:
        print(f"results: {exc}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    measured = scope(args.database, args.mode, args.rows)
    doc = {**measured, "results": rows}
    (args.out / RESULTS_JSON).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    table = render(rows, measured)
    (args.out / RESULTS_MD).write_text(table, encoding="utf-8")
    print(table)
    return 0 if all(r["verdict"] == "PASS" for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
