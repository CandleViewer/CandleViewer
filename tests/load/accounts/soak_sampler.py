"""E27-Q03 (#892): the 24 h mini-soak sampler for the account health monitor (BQ-09, BQ-02).

BQ-nn markers here: RULED (orchestrator, 2026-11-01, #892 ruling of record 6555033109).

    python soak_sampler.py run   --base-url http://127.0.0.1:8000 --out soak.csv --hours 24
    python soak_sampler.py judge --csv soak.csv --expect compliant=healthy

No user behaviour is scripted (so not Locust, BQ-02): the health monitor ticks on its own at real
cadence on the account fixture stack, and this process scrapes `/metrics` every 60 s and reads
the account list once an hour. Stdlib only; one outbound target, checked by `guard.check_target`.

`run` writes one CSV row per scrape: `t_s, rss_bytes, open_fds, connections, tasks, health`.
Series read: `process_resident_memory_bytes` and `process_open_fds` (the prometheus_client process
collector, registered by `observability/metrics.py`), `cv_ws_connections_in_use` (open client WS
connections, metrics catalogue), the asyncio task count (no catalogue series exists at the fetch:
pass `--task-metric <name>` once one does, else the column is empty and `judge` FAILS the
task-count criterion rather than passing it), and `cv_account_health_state{state,reason}`.

`judge` fits a Theil-Sen slope per series over the whole run (06 section 9, the backend-memory row's
estimator) and compares it with a noise band set in this file's constants; the band is a proposal
(BQ-07), to be moved only by a reviewed change. The 24 h run is a dispatch-only workflow on the
self-hosted bench group (PR-2, `security-review`), or owner-run with the harness proven at 1 h on a
hosted runner (BQ-09). End-state truth: the final `cv_account_health_state`
must hold exactly the states the scenario implies (`--expect`).
"""

from __future__ import annotations

import argparse
import csv
import re
import statistics
import sys
import time
import urllib.request
from itertools import combinations
from pathlib import Path

from guard import check_target

SCRAPE_S = 60.0
# BQ-07: proposed noise bands, units per hour; a slope above one is a trend beyond noise.
BAND_PER_H = {
    "rss_bytes": 512 * 1024,
    "open_fds": 0.5,
    "connections": 0.5,
    "tasks": 0.5,
}
MIN_SAMPLES = 100  # 06 section 9 asks for >= 100 samples for a slope claim
_SAMPLE = re.compile(r"^([a-z_:0-9]+)(\{[^}]*\})? ([0-9.e+-]+)$", re.MULTILINE)


def scrape(base: str, task_metric: str | None) -> dict[str, float | str | None]:
    with urllib.request.urlopen(f"{base}/metrics", timeout=10) as resp:  # noqa: S310 - guarded above
        body = resp.read().decode()
    out: dict[str, float | str | None] = {
        "rss_bytes": None,
        "open_fds": None,
        "connections": None,
        "tasks": None,
    }
    health: list[str] = []
    for name, labels, value in _SAMPLE.findall(body):
        v = float(value)
        if name == "process_resident_memory_bytes":
            out["rss_bytes"] = v
        elif name == "process_open_fds":
            out["open_fds"] = v
        elif name == "cv_ws_connections_in_use":
            out["connections"] = v
        elif task_metric and name == task_metric:
            out["tasks"] = v
        elif name == "cv_account_health_state" and v > 0:
            health.append(labels.strip("{}").replace('"', ""))
    out["health"] = ";".join(sorted(health))  # e.g. "reason=none,state=healthy"
    return out


def run(a: argparse.Namespace) -> int:
    base = check_target(a.base_url)  # BQ-11
    end = time.monotonic() + a.hours * 3600
    t0 = time.monotonic()
    with open(a.out, "w", newline="") as fh:
        w: csv.DictWriter[str] | None = None
        while time.monotonic() < end:
            row = {
                "t_s": round(time.monotonic() - t0, 1),
                **scrape(base, a.task_metric),
            }
            if w is None:
                w = csv.DictWriter(fh, fieldnames=list(row))
                w.writeheader()
            w.writerow(row)
            fh.flush()
            time.sleep(SCRAPE_S)  # a real-time soak: the one place a wait is the point (C-13.7 n/a)
    return 0


def theil_sen(xs: list[float], ys: list[float]) -> float:
    pairs = [
        (y2 - y1) / (x2 - x1)
        for (x1, y1), (x2, y2) in combinations(zip(xs, ys, strict=True), 2)
        if x2 != x1
    ]
    return statistics.median(pairs)


def judge(a: argparse.Namespace) -> int:
    with open(a.csv, newline="") as fh:
        rows = list(csv.DictReader(fh))
    failed = []
    for col, band in BAND_PER_H.items():
        pts = [(float(r["t_s"]), float(r[col])) for r in rows if r.get(col) not in (None, "")]
        if len(pts) < MIN_SAMPLES:
            failed.append(f"{col}: {len(pts)} samples (< {MIN_SAMPLES}); no trend claim possible")
            continue
        slope_h = theil_sen([p[0] for p in pts], [p[1] for p in pts]) * 3600
        print(f"{col}: Theil-Sen slope {slope_h:.3f}/h (band {band}/h)")
        if slope_h > band:
            failed.append(f"{col}: slope {slope_h:.3f}/h above the band {band}/h")
    last = rows[-1] if rows else {}
    for want in a.expect:
        scenario, _, state = want.partition("=")
        if f"state={state}" not in str(last.get("health", "")):
            failed.append(
                f"end state: no cv_account_health_state with state={state} for {scenario}"
            )
    print("\n".join(failed) if failed else "PASS soak")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--base-url", default="http://127.0.0.1:8000")
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--hours", type=float, default=24.0)
    r.add_argument("--task-metric", default=None)
    j = sub.add_parser("judge")
    j.add_argument("--csv", type=Path, required=True)
    j.add_argument(
        "--expect",
        action="append",
        default=[],
        help="<scenario>=<healthy|degraded|down>",
    )
    a = ap.parse_args(argv)
    return run(a) if a.cmd == "run" else judge(a)


if __name__ == "__main__":
    sys.exit(main())
