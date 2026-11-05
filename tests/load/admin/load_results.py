"""E42-Q03 (#1216) part 4: judge the export, verify and flood profiles' runs [BQ-8].

    python tests/load/admin/load_results.py judge PROFILE RUN_DIR [RUN_DIR ...] --out DIR \
        [--database NAME --mode chained --rows N]

Each run directory holds k6's `points.json` (`--out json=`) and the driver's `wal.json` (the
WAL readings, `wal_check.watch`). From the points: the load window (the `cv_admin_edge_at`
edges), the Owner's reads (`cv_admin_read_ms`) and E29's probe (`cv_admin_probe_ms`) before it
(idle) and inside it (loaded), the bounds (`cv_admin_bound`), any `audit_unavailable` and the
flood's answers. A sample whose call did not get its answer (tag `ok` other than "1") is never a
duration: its row is ERRORS (part 1's rule). Statistics are nearest-rank (06 section 7.4); each
row's figure is the median over the runs of the per-run figure; a run without it makes the row
INCOMPLETE, never a pass. The rows (plan section 4):

- `reads_loaded_p95`: the Owner's reads inside the window, p95 at most 400 ms (SCR-135);
- `reads_ab` (export): that p95 at most 1.05 times the same reads' before the window;
- `probe_p90`: the probe's first `PROBE_N` inside the window, p90 at most 300 ms (06 row 4);
- `probe_ratio`: that p90 at most 1.2 times the first `PROBE_N` before the window's [BQ-8];
- `wal_depth`: the deepest WAL at most 80 % of its cap (`wal_check`); `audit_unavailable`: none;
- one row per bound of the profile: it held in every run; `flood_sent` (flood): the flood ran;
- `flood_refused` (flood): at least 95 % of the flood's answers are 403 refusals, so a flood of
  404s, 401s or 5xx (no `admin.area_entered` record written) never passes the rows above (C-02).

A load window shorter than `PROBE_N` probes (`PROBE_N` x `PACE_S`, a fast verify) is held open
that long: the probes and reads just after it count as loaded (C-1216P4-04).
The flood is expected to FAIL until #2836 caps the admin guard's refusal records: every flood row
that FAILS names it, as part 1 names #1710 and #1711 (an INCOMPLETE or ERRORS row is the harness's,
and `flood_sent` / `flood_refused` never wait on it). Judged, never skipped.
Only the chained dataset at `FULL_ROWS` is the verdict; any other run is a CONTROL.
`added` (SCR-143's added load, one run, no WAL) is judged by `judge_added`.
Exit 0: every row passes (or is RECORDED); 1: a row fails or is incomplete; 2: nothing to judge.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Final

#: The run directory's files and the judge's two outputs (names, never bare literals in a test).
POINTS_JSON: Final = "points.json"
WAL_JSON: Final = "wal.json"
LOAD_RESULTS_JSON: Final = "results.json"
LOAD_RESULTS_MD: Final = "results.md"
READ_P95_MS: Final = 400.0
READ_AB_RATIO: Final = 1.05
PROBE_P90_MS: Final = 300.0
PROBE_RATIO: Final = 1.2
PROBE_N: Final = 20
PACE_S: Final = 1.05  # lib/loadPlan.js: one probe and one read a second
MIN_LOADED_READS: Final = 5  # [BQ-8] an export may be shorter than 20 one-a-second reads
FLOOD_RPS: Final = 200
FLOOD_S: Final = 60
FLOOD_SENT: Final = 0.95  # of FLOOD_RPS x FLOOD_S: below it the flood did not happen
FLOOD_REFUSED: Final = 0.95  # of the flood's answers 403: below it the flood was not refused
WAL_CAP_BYTES: Final = 64 * 1024 * 1024
WAL_LIMIT: Final = 0.8
FULL_ROWS: Final = 1_000_000  # the chained set the verify and export budgets are judged on
BOUNDS: Final = {
    "export": ("export_single_flight", "export_succeeded", "export_rows", "export_max_range",
               "export_hourly", "download_hourly"),
    "verify": ("verify_max_span", "verify_single_flight", "verify_verified", "verify_span",
               "verify_deadline", "verify_hourly"),
    "flood": (),
}  # fmt: skip
#: [BQ-8] what each profile's misses wait on: the flood until #2836 lands.
WAITS_ON: Final = {"flood": "#2836"}

Figure = float | None
_TIME = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?(Z|[+-]\d\d:\d\d)$")


def percentile(values: Sequence[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[max(1, math.ceil(q / 100.0 * len(ordered))) - 1]


def epoch_ms(text: str) -> float:
    """k6's RFC 3339 point time (up to nanoseconds) in epoch milliseconds."""
    m = _TIME.match(text)
    if m is None:
        raise ValueError(f"not a point time: {text[:40]}")
    frac = (m.group(2) or ".0")[:7]
    zone = "+00:00" if m.group(3) == "Z" else m.group(3)
    return datetime.fromisoformat(f"{m.group(1)}{frac}{zone}").timestamp() * 1000.0


def read_points(lines: Iterable[str]) -> list[dict[str, Any]]:
    """The part 4 points: metric, time (epoch ms), value and tags."""
    out = []
    for line in lines:
        if not line.strip():
            continue
        point = json.loads(line)
        metric = str(point.get("metric", ""))
        if point.get("type") != "Point" or not metric.startswith("cv_admin_"):
            continue
        data = point["data"]
        tags = data.get("tags") or {}
        at = epoch_ms(str(data["time"]))
        out.append({"metric": metric, "at": at, "value": float(data["value"]), "tags": tags})
    return out


def _of(points: list[dict[str, Any]], metric: str) -> list[dict[str, Any]]:
    return [p for p in points if p["metric"] == metric]


def _window(points: list[dict[str, Any]]) -> tuple[float, float] | None:
    edges = _of(points, "cv_admin_edge_at")
    starts = [p["value"] for p in edges if p["tags"].get("edge") == "start"]
    ends = [p["value"] for p in edges if p["tags"].get("edge") == "end"]
    if not starts or not ends:
        return None
    return min(starts), max(max(ends), min(starts) + PROBE_N * PACE_S * 1000.0)  # C-04


def _split(samples: list[dict[str, Any]], window: tuple[float, float]) -> tuple[list[Any], ...]:
    before = [p for p in samples if p["at"] < window[0]]
    inside = [p for p in samples if window[0] <= p["at"] <= window[1]]
    return before, inside


def _stat(samples: list[dict[str, Any]], q: float, need: int) -> tuple[Figure, bool]:
    """(the percentile or None when short, whether any call failed)."""
    failed = any(p["tags"].get("ok") != "1" for p in samples)
    ok = [p["value"] for p in samples if p["tags"].get("ok") == "1"]
    return (percentile(ok, q) if len(ok) >= need else None), failed


def run_figures(profile: str, points: list[dict[str, Any]], wal: list[Any]) -> dict[str, Any]:
    """One run's figures: each row's measured value (None: not measured) and its errors."""
    fig: dict[str, Any] = {"errors": set()}
    window = _window(points)
    by_time = sorted(points, key=lambda p: float(p["at"]))  # C-07: never file order
    reads, probes = _of(by_time, "cv_admin_read_ms"), _of(by_time, "cv_admin_probe_ms")
    if window is not None:
        idle_r, load_r = _split(reads, window)
        idle_p, load_p = _split(probes, window)
        fig["reads_loaded_p95"], bad_b = _stat(load_r, 95, MIN_LOADED_READS)
        idle_p95, bad_a = _stat(idle_r, 95, MIN_LOADED_READS)
        fig["probe_p90"], bad_pl = _stat(load_p[:PROBE_N], 90, PROBE_N)
        idle_p90, bad_pi = _stat(idle_p[-PROBE_N:], 90, PROBE_N)
        flags = {"reads_loaded_p95": bad_b, "reads_ab": bad_a or bad_b, "probe_p90": bad_pl}
        flags["probe_ratio"] = bad_pi or bad_pl
        fig["errors"] |= {k for k, bad in flags.items() if bad}
        fig["reads_ab"] = _ratio(fig["reads_loaded_p95"], idle_p95)
        fig["probe_ratio"] = _ratio(fig["probe_p90"], idle_p90)
    readings = [r["wal"] for r in wal]
    depths = [w["depth"] for r in readings for w in r.values()]
    fig["wal_depth"] = float(max(depths)) if readings and all(readings) else None
    fig["audit_unavailable"] = sum(p["value"] for p in _of(points, "cv_admin_audit_unavailable"))
    marks = _of(points, "cv_admin_bound")
    for name in BOUNDS[profile]:
        held = [p["tags"].get("ok") == "1" for p in marks if p["tags"].get("bound") == name]
        fig[name] = float(bool(held) and all(held))
    if profile == "flood":
        sent = _of(points, "cv_admin_flood")
        fig["flood_sent"] = sum(p["value"] for p in sent)
        refused = sum(p["value"] for p in sent if p["tags"].get("status") == "403")
        fig["flood_refused"] = refused / fig["flood_sent"] if fig["flood_sent"] else None
    return fig


def _ratio(num: Figure, den: Figure) -> Figure:
    return None if num is None or den is None or den <= 0 else num / den


def rows_for(profile: str) -> list[tuple[str, str, float, str]]:
    """(row, required, limit, how): `max` passes at most the limit, `min` at least (else
    INCOMPLETE), `all` 1.0, `share` at least (else FAIL)."""
    rows = [("reads_loaded_p95", "p95 <= 400 ms", READ_P95_MS, "max")]
    if profile == "export":
        rows.append(("reads_ab", "<= 1.05 x no-load p95", READ_AB_RATIO, "max"))
    rows += [
        ("probe_p90", "p90 <= 300 ms", PROBE_P90_MS, "max"),
        ("probe_ratio", "<= 1.2 x no-load p90", PROBE_RATIO, "max"),
        ("wal_depth", "<= 80 % of 64 MiB", WAL_LIMIT * WAL_CAP_BYTES, "max"),
        ("audit_unavailable", "0", 0.0, "max"),
    ]
    rows += [(name, "held in every run", 1.0, "all") for name in BOUNDS[profile]]
    if profile == "flood":
        rows.append(("flood_sent", f">= {FLOOD_SENT:.0%} of {FLOOD_RPS}/s x {FLOOD_S} s",
                     FLOOD_SENT * FLOOD_RPS * FLOOD_S, "min"))  # fmt: skip
        rows.append(("flood_refused", f">= {FLOOD_REFUSED:.0%} answered 403", FLOOD_REFUSED,
                     "share"))  # fmt: skip
    return rows


def judge(profile: str, runs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for name, required, limit, how in rows_for(profile):
        per_run: list[float] = [v for r in runs if (v := r.get(name)) is not None]
        measured: Figure = None
        if len(per_run) == len(runs):
            measured = min(per_run) if how == "all" else statistics.median(per_run)
        if any(name in r["errors"] for r in runs):
            verdict = "ERRORS"
        elif measured is None:
            verdict = "INCOMPLETE"
        elif how == "min":
            verdict = "PASS" if measured >= limit else "INCOMPLETE"
        elif how in ("all", "share"):
            verdict = "PASS" if measured >= limit else "FAIL"
        else:
            verdict = "PASS" if measured <= limit else "FAIL"
        blame = verdict == "FAIL" and not name.startswith("flood_")  # C-03: only a measured miss
        waits = WAITS_ON.get(profile, "") if blame else ""
        out.append({"row": name, "required": required, "measured": measured, "runs": len(runs),
                    "verdict": verdict, "waits_on": waits})  # fmt: skip
    return out


# SCR-143's added load (plan 5.2) [BQ-8]: the windows of `added_load.js`, in order.
ADDED_WINDOWS: Final = ("aa_1", "aa_2", "a_1", "b_1", "a_2", "b_2", "a_3", "b_3")
ADDED_WINDOW_S: Final = 600
ADDED_LIMIT: Final = 0.01
NOISE_LIMIT: Final = 0.003


def cpu_rates(points: list[dict[str, Any]]) -> dict[str, Figure]:
    """CPU seconds a second per window, from its first and last `process_cpu_seconds_total`."""
    rates: dict[str, Figure] = {}
    for name in ADDED_WINDOWS:
        got = sorted((p["at"], p["value"]) for p in _of(points, "cv_admin_cpu_s")
                     if p["tags"].get("window") == name)  # fmt: skip
        span_s = (got[-1][0] - got[0][0]) / 1000.0 if len(got) > 1 else 0.0
        rates[name] = (got[-1][1] - got[0][1]) / span_s if span_s > 0 else None
    return rates


def judge_added(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The A/A noise; the median of the three B-minus-A deltas as a share of A, judged only when
    the noise is at most `NOISE_LIMIT`; the CPU per read set (a mount or a Re-read: four reads),
    recorded; and no read failed. Per-mount cost times the expected mount rate is the fallback the
    plan names when the noise is higher; the mount rate is not ruled, so it is recorded only."""
    rate = cpu_rates(points)
    sets = {n: sum(p["value"] for p in _of(points, "cv_admin_mounts") if p["tags"].get("window")
                   == n) for n in ADDED_WINDOWS}  # fmt: skip
    pairs = [(rate[f"a_{i}"], rate[f"b_{i}"], sets[f"b_{i}"]) for i in (1, 2, 3)]
    noise: Figure = None
    if rate["aa_1"] and rate["aa_2"]:
        noise = abs(rate["aa_2"] - rate["aa_1"]) / ((rate["aa_1"] + rate["aa_2"]) / 2)
    deltas = [(b - a) / a for a, b, _n in pairs if a and b is not None]
    added: Figure = statistics.median(deltas) if len(deltas) == len(pairs) else None
    costs = [(b - a) * ADDED_WINDOW_S * 1000 / n for a, b, n in pairs if a and b is not None and n]
    per_set: Figure = statistics.median(costs) if len(costs) == len(pairs) else None
    failed = sum(p["value"] for p in _of(points, "cv_admin_read_failed"))
    quiet = noise is not None and noise <= NOISE_LIMIT
    rows = [
        ("noise_floor", "A/A <= 0.3 %", noise, "INCOMPLETE" if noise is None
         else "PASS" if quiet else "NOISY"),
        ("added_load", "median B-A <= 1 % of A", added, "INCOMPLETE" if added is None
         else "NOT JUDGED (noise)" if not quiet else "PASS" if added <= ADDED_LIMIT else "FAIL"),
        ("cpu_ms_per_read_set", "recorded", per_set, "RECORDED" if per_set is not None
         else "INCOMPLETE"),
        ("read_failures", "0", failed, "PASS" if failed == 0 else "FAIL"),
    ]  # fmt: skip
    return [{"row": r, "required": q, "measured": m, "runs": 1, "verdict": v, "waits_on": ""}
            for r, q, m, v in rows]  # fmt: skip


def scope(database: str, mode: str, rows: int | None) -> dict[str, object]:
    verdict = mode == "chained" and rows == FULL_ROWS
    return {"database": database, "mode": mode, "rows": rows, "kind": "verdict" if verdict
            else "CONTROL, not a verdict"}  # fmt: skip


def render(profile: str, rows: Sequence[dict[str, Any]], measured: dict[str, object]) -> str:
    size = "rows unknown" if measured["rows"] is None else f"{measured['rows']} rows"
    lines = [
        f"Profile {profile}. Dataset: {measured['database']} ({measured['mode']}, {size}): "
        f"{measured['kind']}",
        "",
        "| check | required | measured | runs | verdict | waits on |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        value = "n/a" if r["measured"] is None else f"{r['measured']:.3f}"
        lines.append(f"| {r['row']} | {r['required']} | {value} | {r['runs']} | {r['verdict']} |"
                     f" {r['waits_on']} |")  # fmt: skip
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Judge an admin load profile (E42-Q03).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    cmd = sub.add_parser("judge")
    cmd.add_argument("profile", choices=sorted([*BOUNDS, "added"]))
    cmd.add_argument("runs", nargs="+", type=Path)
    cmd.add_argument("--out", type=Path, required=True)
    cmd.add_argument("--database", default="unknown")
    cmd.add_argument("--mode", default="unknown")
    cmd.add_argument("--rows", type=int)
    args = parser.parse_args(argv)
    try:
        runs, every = [], []
        for run in args.runs:
            with (run / POINTS_JSON).open(encoding="utf-8") as fh:
                points = read_points(fh)
            if not points:
                raise ValueError(f"{run.name}: no points")
            every.append(points)
            if args.profile != "added":
                wal = json.loads((run / WAL_JSON).read_text(encoding="utf-8"))
                runs.append(run_figures(args.profile, points, wal))
    except (OSError, ValueError, KeyError) as exc:
        print(f"load_results: {exc}", file=sys.stderr)
        return 2
    rows = judge_added(every[0]) if args.profile == "added" else judge(args.profile, runs)
    measured = scope(args.database, args.mode, args.rows)
    args.out.mkdir(parents=True, exist_ok=True)
    doc = {**measured, "profile": args.profile, "results": rows}
    (args.out / LOAD_RESULTS_JSON).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    table = render(args.profile, rows, measured)
    (args.out / LOAD_RESULTS_MD).write_text(table, encoding="utf-8")
    print(table)
    return 0 if all(r["verdict"] in ("PASS", "RECORDED") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
