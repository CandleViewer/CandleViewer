"""E40-Q02 (#1203): the +5 % p95 regression gate (06 section 7.4, C-13.9) for the alert k6 runs:
the median over the runs of each gated metric against `baseline.json`, as a JSON report and a
markdown summary. Stdlib only.

    python3 tests/load/k6/alerts/compare_baseline.py --baseline tests/load/k6/alerts/baseline.json \
        --out-dir alerts-load run-1/k6-summary-alerts-ws.json run-2/... run-3/...

A spec's optional `skip_if_has` names a metric: a summary holding it is left out of that spec (the
`/notifications` run's plain http_req_duration is not a WS run's). A metric without a baseline value is reported, never gated; a baseline whose `mode` is
`warn-only` (until a reviewed PR records CI-runner numbers, BQ-04) WARNs instead of failing, as
the E08 pack's laptop baselines do. Any other `mode` is refused (a typo must not disable the gate).
A metric read from fewer than MIN_RUNS summaries (a spec's `min_runs` overrides it) FAILs in `gate`
and WARNs in `warn-only`: a run that wrote no summary never turns the median of three into one of two.
Exit 1 on a FAIL, an unknown `mode`, or a summary that holds setup_data.
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


def stat(summary: dict[str, Any], metric: str, key: str) -> float | None:
    m = summary.get("metrics", {}).get(metric)
    if not m:
        return None
    v = m.get("values", m).get(key)
    return float(v) if v is not None else None


def compare(
    summaries: list[dict[str, Any]], baseline: dict[str, Any]
) -> dict[str, Any]:
    if baseline.get("mode") not in MODES:
        raise ValueError(
            f"baseline mode {baseline.get('mode')!r} is not one of {MODES}"
        )
    rows, status = [], "PASS"
    for name, spec in baseline["metrics"].items():
        skip = spec.get("skip_if_has")  # the notifications run's own http_req_duration
        got = [
            x
            for x in (
                stat(s, spec["metric"], spec["stat"])
                for s in summaries
                if not (skip and stat(s, skip, spec["stat"]) is not None)
            )
            if x is not None
        ]
        median = statistics.median(got) if got else None
        base, verdict = spec.get("value"), "NO-BASELINE"
        need = spec.get("min_runs", MIN_RUNS)
        if (
            type(need) is not int or need < 1
        ):  # 0 or a negative would disable the minimum
            raise ValueError(f"{name}: min_runs {need!r} is not a positive int")
        if median is None:
            verdict = "MISSING"
        elif len(got) < need:  # a run that wrote no summary: never a median of fewer
            verdict = "WARN" if baseline["mode"] == "warn-only" else "FAIL"
        elif base is not None:
            over = median > base * (1 + TOLERANCE)
            verdict = (
                ("WARN" if baseline["mode"] == "warn-only" else "FAIL")
                if over
                else "PASS"
            )
        if verdict in ("FAIL", "MISSING") and baseline["mode"] == "gate":
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
    return {
        "mode": baseline["mode"],
        "tolerance": TOLERANCE,
        "rows": rows,
        "status": status,
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        f"### E40-Q02 alert load: {report['status']} (baseline mode {report['mode']}, +5 % p95)",
        "",
        "| Metric | Runs | Median | Baseline | Verdict |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in report["rows"]:
        runs = ", ".join(f"{x:.1f}" for x in r["runs"]) or "none"
        if 0 < len(r["runs"]) < r["min_runs"]:
            runs += f" ({len(r['runs'])} of {r['min_runs']} runs)"
        med = "n/a" if r["median"] is None else f"{r['median']:.1f}"
        lines.append(
            f"| {r['name']} | {runs} | {med} | {r['baseline']} | {r['verdict']} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("summaries", type=Path, nargs="+")
    args = ap.parse_args(argv)
    summaries = [
        json.loads(p.read_text(encoding="utf-8")) for p in args.summaries if p.is_file()
    ]
    if any("setup_data" in s for s in summaries):
        print("a summary holds setup_data (session tokens): refusing to report it")
        return 1
    try:
        report = compare(
            summaries, json.loads(args.baseline.read_text(encoding="utf-8"))
        )
    except ValueError as exc:
        print(f"refusing: {exc}")
        return 1
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "compare.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (args.out_dir / "compare.md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
