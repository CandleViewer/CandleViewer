"""E29-Q03 (#977): the +5 % p95 regression gate (06 section 7.4, C-13.9) for the OMS submit-ack
k6 runs: the median over the runs of each gated metric against `baseline.json`, as a JSON report
and a markdown summary. Stdlib only; the alert kit's pattern (copied, not imported, BQ-07).

    python3 tests/load/k6/oms/compare_baseline.py --baseline tests/load/k6/oms/baseline.json \
        --out-dir oms-load run-1/k6-summary-oms-submit-ack.json run-2/... run-3/...

A null baseline value is reported, never gated. `warn-only` (until a reviewed PR records CI-runner
numbers, BQ-09) WARNs where `gate` FAILs: a value over +5 %, or one read from fewer than MIN_RUNS
summaries. Exit 1 on a FAIL, an unknown `mode`, a summary holding setup_data, or one not from the
`gate` profile (a calibration run's injected delay is not a baseline).
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

TOLERANCE = 0.05  # 06 section 7.4: over 5 % on the median of the runs' p95s
MIN_RUNS = 3  # the median of three; a spec's `min_runs` may lower it
MODES = ("gate", "warn-only")
PROFILE = "gate"  # oms_submit_ack.js writes `cv_profile` into its summary


def stat(summary: dict[str, Any], metric: str, key: str) -> float | None:
    m = summary.get("metrics", {}).get(metric)
    if not m:
        return None
    v = m.get("values", m).get(key)
    return float(v) if v is not None else None


def compare(summaries: list[dict[str, Any]], baseline: dict[str, Any]) -> dict[str, Any]:
    mode = baseline.get("mode")
    if mode not in MODES:
        raise ValueError(f"baseline mode {mode!r} is not one of {MODES}")
    soft = "WARN" if mode == "warn-only" else "FAIL"
    rows, status = [], "PASS"
    for name, spec in baseline["metrics"].items():
        got = [
            x for x in (stat(s, spec["metric"], spec["stat"]) for s in summaries) if x is not None
        ]
        median = statistics.median(got) if got else None
        base, need = spec.get("value"), int(spec.get("min_runs", MIN_RUNS))
        if median is None:
            verdict = "MISSING"
        elif len(got) < need:
            verdict = soft
        elif base is None:
            verdict = "NO-BASELINE"
        else:
            verdict = soft if median > base * (1 + TOLERANCE) else "PASS"
        if verdict in ("FAIL", "MISSING") and mode == "gate":
            status = "FAIL"
        rows.append(
            {
                "name": name,
                "runs": got,
                "min_runs": need,
                "median": median,
                "baseline": base,
                "verdict": verdict,
            }
        )
    return {"mode": mode, "tolerance": TOLERANCE, "rows": rows, "status": status}


def markdown(report: dict[str, Any]) -> str:
    lines = [
        f"### E29-Q03 OMS submit-ack: {report['status']} (mode {report['mode']}, +5 % p95)",
        "",
        "| Metric | Runs | Median | Baseline | Verdict |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in report["rows"]:
        runs = ", ".join(f"{x:.1f}" for x in r["runs"]) or "none"
        if 0 < len(r["runs"]) < r["min_runs"]:
            runs += f" ({len(r['runs'])} of {r['min_runs']} runs)"
        med = "n/a" if r["median"] is None else f"{r['median']:.1f}"
        lines.append(f"| {r['name']} | {runs} | {med} | {r['baseline']} | {r['verdict']} |")
    return "\n".join(lines) + "\n"


def refusal(summaries: list[dict[str, Any]]) -> str | None:
    if any("setup_data" in s for s in summaries):
        return "a summary holds setup_data (the session token)"
    if any(s.get("cv_profile") != PROFILE for s in summaries):
        return "a summary is not from the `gate` profile"
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("summaries", type=Path, nargs="+")
    args = ap.parse_args(argv)
    summaries = [json.loads(p.read_text(encoding="utf-8")) for p in args.summaries if p.is_file()]
    why = refusal(summaries)
    try:
        if why is not None:
            raise ValueError(why)
        report = compare(summaries, json.loads(args.baseline.read_text(encoding="utf-8")))
    except ValueError as exc:
        print(f"refusing: {exc}")
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "compare.json").write_text(json.dumps(report, indent=2) + "\n", "utf-8")
    (args.out_dir / "compare.md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
