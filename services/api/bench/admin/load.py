"""E42-Q03 (#1216) part 4: the export, verify and flood profiles' driver (plan section 4) [BQ-8].

`bench/admin/run.py export|verify|flood` hands over here after its guards (the API target, the
database, the environment) passed. These profiles run on the chained dataset only
(`admin_perf1m_test`: a bulk set fails a verify at row 1 and its export spans nothing chained).
Each run is one k6 process, as part 1's; beside it this samples the audit WAL every second
before, during and after (`tests/load/admin/wal_check.py`, in `<run dir>/wal.json`) from the
directory of `CV_AUDIT_WAL_PATH`, the API's own setting, which the driver needs and never passes to
k6. The flood's operations are the rbac matrix's (`tests/contract/rbac/matrix.yaml`): every
executed `/admin/*` operation it refuses a Manager without a grant, read here, never copied.
Last, `tests/load/admin/load_results.py` judges the runs. A dispatch's flood ends red by design
until #2836 lands; the results say so. The part 4 profiles run on testnet only (S-1216P4-01,
-03): the order probe and `CV_ADMIN_PROBE_ACCOUNT` never meet a demo stack, and the k6 scripts
check `/healthz` again. `added` reads no WAL (C-1216P4-06).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Final

import yaml

from bench.admin import REPO, load_harness
from bench.ws.runner import k6_binary

API: Final = REPO / "services" / "api"
K6_DIR: Final = REPO / "tests" / "load" / "k6" / "admin"
SCRIPTS: Final = {
    "export": K6_DIR / "export_under_load.js",
    "verify": K6_DIR / "verify_span.js",
    "flood": K6_DIR / "refusal_flood.js",
    "added": K6_DIR / "added_load.js",  # SCR-143's added load: one run of 3 A/B pairs (plan 5.2)
}
MATRIX: Final = API / "tests" / "contract" / "rbac" / "matrix.yaml"
MODE: Final = "chained"
RUN_TIMEOUT_S: Final = 3600
ADDED_TIMEOUT_S: Final = 8 * 600 + 900  # added_load.js: eight 10-minute windows and slack
WAL_ENV: Final = "CV_AUDIT_WAL_PATH"


def flood_ops(matrix: Path = MATRIX) -> list[dict[str, Any]]:
    """The matrix's executed `/admin/*` operations a Manager without a grant is refused (403)."""
    doc = yaml.safe_load(matrix.read_text(encoding="utf-8"))
    ops = []
    for name, row in doc["operations"].items():
        method, path = str(name).split(" ", 1)
        refused = str(row["outcomes"]["manager_without_grant"]) == "403"
        if path.startswith("/admin/") and row["state"] == "executed" and refused:
            ops.append({"method": method, "path": path, "request": row.get("request") or {}})
    return ops


def wal_dir() -> Path:
    """The directory of the API's `CV_AUDIT_WAL_PATH`, or ValueError."""
    raw = os.environ.get(WAL_ENV, "")
    if not raw or not Path(raw).is_absolute():
        raise ValueError(f"{WAL_ENV} must be the API's absolute audit WAL path")
    return Path(raw).parent


def run_sampled(
    argv: list[str],
    env: dict[str, str],
    run_dir: Path,
    wal: Path | None,
    timeout_s: int | None = None,
) -> int:
    """One k6 run with the WAL read beside it (none when `wal` is None); past its timeout
    (`RUN_TIMEOUT_S` unless given) it is killed and is 124."""
    wal_check = load_harness("wal_check")
    deadline = time.monotonic() + (RUN_TIMEOUT_S if timeout_s is None else timeout_s)
    late: list[bool] = []
    with subprocess.Popen(argv, env=env) as proc:  # noqa: S603 - the checked k6, flags, repo paths

        def done(interval: float) -> bool:
            try:
                proc.wait(timeout=interval)
            except subprocess.TimeoutExpired:
                if time.monotonic() < deadline:
                    return False
                proc.kill()
                proc.wait()
                late.append(True)
            return True

        if wal is None:
            while not done(1.0):
                pass
        else:
            readings = wal_check.watch(wal, done)
            (run_dir / "wal.json").write_text(json.dumps(readings) + "\n", encoding="utf-8")
    return 124 if late else int(proc.returncode)


def run_profile(args: argparse.Namespace, base: str, database: str, mode: str) -> int:
    """The profile's runs and their judgement; 2 when refused."""
    from bench.admin import run  # run.py dispatches here: imported on use, never at load

    try:
        if mode != MODE:
            raise ValueError(f"the {args.profile} profile runs on the {MODE} dataset only")
        if os.environ.get("CV_ENVIRONMENT") != "testnet":  # S-1216P4-01, -03: never demo
            raise ValueError("the part 4 profiles and CV_ADMIN_PROBE_ACCOUNT run on testnet only")
        wal = None if args.profile == "added" else wal_dir()
    except ValueError as exc:
        print(f"admin-perf: refused: {exc}", file=sys.stderr)
        return 2
    runs = 1 if args.profile == "added" else args.runs  # the method has its own three pairs
    dirs = [args.out / f"run-{i}" for i in range(1, runs + 1)]
    ops_file = args.out / "flood_ops.json"
    if args.dry_run:
        plan = {"profile": args.profile, "database": database, "mode": mode, "rows": args.rows,
                "base_url": base, "wal_dir": None if wal is None else str(wal),
                "runs": [run.k6_argv("$K6_BIN", args.profile, d) for d in dirs]}  # fmt: skip
        print(json.dumps(plan, indent=2))
        return 0
    k6 = k6_binary()  # SystemExit with the reason when K6_BIN is not the pinned k6
    args.out.mkdir(parents=True, exist_ok=True)
    ops_file.write_text(json.dumps(flood_ops()) + "\n", encoding="utf-8")
    worst = 0
    for i, run_dir in enumerate(dirs, start=1):
        run_dir.mkdir(parents=True, exist_ok=True)
        env = run.k6_env(base, database, i, run_dir) | {"CV_ADMIN_FLOOD_OPS": str(ops_file)}
        if args.rows is not None:
            env["CV_ADMIN_ROWS"] = str(args.rows)
        timeout = ADDED_TIMEOUT_S if args.profile == "added" else None
        code = run_sampled(run.k6_argv(k6, args.profile, run_dir), env, run_dir, wal, timeout)
        print(f"admin-perf: {args.profile} run {i} of {runs}: k6 exit {code}")
        worst = max(worst, code)
    measured = ["--database", database, "--mode", mode]
    if args.rows is not None:
        measured += ["--rows", str(args.rows)]
    results = load_harness("load_results")
    argv = ["judge", args.profile, *map(str, dirs), "--out", str(args.out), *measured]
    return max(worst, int(results.main(argv)))
