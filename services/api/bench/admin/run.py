"""E42-Q03 (#1216): run an admin perf profile with k6 and judge it [BQ-1, BQ-2, BQ-3, BQ-9].

    uv run python -m bench.admin.run audit --base-url URL --runs 3 --out <dir> [--rows N]
        [--dry-run]

`--base-url` has no default (S-1216P1-d01): the API under test is always named, never assumed, so a
local run cannot land on another stack that happens to answer on a well-known port. Until 1b's
`bench/admin/api_up.py` merges, nothing here proves that the API at `--base-url` serves the guarded
database: the operator vouches for it (a run against another `demo` API leaves permanent audit
rows there, C-5.7).

Inputs from the environment (the workflow `perf-admin.yml` sets them; `make admin-perf` reads
yours): `CV_ADMIN_PERF_DSN` (the database the API serves, checked, never printed),
`CV_ENVIRONMENT` (the API's: testnet or demo), `CV_ADMIN_USERS_FILE` and `CV_ADMIN_PASSWORD`
(passed to k6 through the environment, never argv), and `K6_BIN`: the pinned k6, an absolute
path checked by `bench/ws/runner.py`'s `k6_binary()` (never found through PATH). k6 gets only
`CHILD_ENV` of the caller's environment and the run's own values: never the DSN, the pepper or a
key (C-12.2). `--rows` is the count the dataset was loaded with; only `bulk` at 10 M rows is the
verdict, any other run is marked a CONTROL in the results.

Order: every guard first (the API target, the database, the environment), and nothing connects
or starts before they pass. Then each run is one k6 process writing `<out>/run-N/points.json`
and `summary.json`; the next run starts after it, even after a red or a timed-out one (exit
124; 06 section 7.4 wants all three). Last, `tests/load/admin/results.py` judges the runs into
`<out>/results.{json,md}`.
The k6 script checks the API's own `/healthz` environment again in its setup.
`--dry-run` checks the same guards and prints the plan (argv per run, the database's name), and
starts nothing.

Exit: 2 refused or unusable; otherwise the worst of the k6 runs and the judge (k6 exits 99 when a
threshold fails). [BQ-1] A dispatch today exits non-zero by design: two rows fail until #1710 and
#1711 land; the results table says which.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from bench.admin import REPO, load, load_harness
from bench.ws.runner import k6_binary

SCRIPTS: Final = {
    "audit": REPO / "tests" / "load" / "k6" / "admin" / "audit_first_page.js",
    **load.SCRIPTS,  # part 4: export, verify, flood (bench/admin/load.py)
}
RUN_TIMEOUT_S: Final = 3600
#: The only variables of the caller's environment k6 sees (S-03), by name: the sign-in inputs,
#: part 4's manager list and probe account, and k6's colour switch. Every other k6 option is the
#: run's own (`k6_env`).
CHILD_ENV: Final = (
    "PATH",
    "HOME",
    "TZ",
    "CV_ADMIN_USERS_FILE",
    "CV_ADMIN_PASSWORD",
    "CV_ADMIN_MANAGERS_FILE",
    "CV_ADMIN_PROBE_ACCOUNT",
    "K6_NO_COLOR",
)


def k6_argv(k6: str, profile: str, run_dir: Path) -> list[str]:
    return [k6, "run", "--quiet", "--out", f"json={run_dir / 'points.json'}", str(SCRIPTS[profile])]


def k6_env(base_url: str, database: str, run: int, run_dir: Path) -> dict[str, str]:
    """The child's env: `CHILD_ENV` of the caller's, by name, plus the run's own values."""
    kept = {name: os.environ[name] for name in CHILD_ENV if name in os.environ}
    return {
        **kept,
        "BASE_URL": base_url,
        "CV_ADMIN_PERF_DB": database,
        "CV_ADMIN_RUN": str(run),
        "CV_ADMIN_OUT": str(run_dir),
        "K6_NO_USAGE_REPORT": "true",
        "K6_AUTO_EXTENSION_RESOLUTION": "false",  # nothing phones home to resolve extensions
    }


def guarded(base_url: str) -> tuple[str, str, str]:
    """The checked base URL, database name and its mode, or the guard's `TargetRefused`."""
    guard = load_harness("guard")
    base = str(guard.check_target(base_url))
    database = str(guard.check_dataset(os.environ.get("CV_ADMIN_PERF_DSN", "")))
    guard.check_environment(os.environ.get("CV_ENVIRONMENT"))
    mode = next(m for m, name in guard.DATASETS.items() if name == database)
    return base, database, str(mode)


def run_once(k6: str, profile: str, run: int, run_dir: Path, base: str, database: str) -> int:
    """One k6 run's exit; a run past `RUN_TIMEOUT_S` is 124 and the next run still starts."""
    try:
        return subprocess.run(  # noqa: S603 - fixed argv: the checked k6 binary, flags, a repo path
            k6_argv(k6, profile, run_dir),
            env=k6_env(base, database, run, run_dir),
            timeout=RUN_TIMEOUT_S,
            check=False,
        ).returncode
    except subprocess.TimeoutExpired:
        return 124


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run an admin perf profile (E42-Q03).")
    parser.add_argument("profile", choices=sorted(SCRIPTS))
    parser.add_argument("--runs", type=int, choices=[1, 2, 3], default=3)
    parser.add_argument("--out", type=Path, default=Path("bench/reports/admin-perf"))
    parser.add_argument("--base-url", required=True, help="the API under test (no default)")
    parser.add_argument("--rows", type=int, help="the rows the dataset was loaded with")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        base, database, mode = guarded(args.base_url)
    except ValueError as exc:  # the guard's TargetRefused is one
        print(f"admin-perf: refused: {exc}", file=sys.stderr)
        return 2
    if args.profile in load.SCRIPTS:
        return load.run_profile(args, base, database, mode)
    dirs = [args.out / f"run-{i}" for i in range(1, args.runs + 1)]
    if args.dry_run:
        runs = [k6_argv("$K6_BIN", args.profile, d) for d in dirs]
        plan = {"database": database, "mode": mode, "rows": args.rows, "base_url": base,
                "runs": runs}  # fmt: skip
        print(json.dumps(plan, indent=2))
        return 0
    k6 = k6_binary()  # SystemExit with the reason when K6_BIN is not the pinned k6
    worst = 0
    for i, run_dir in enumerate(dirs, start=1):
        run_dir.mkdir(parents=True, exist_ok=True)
        code = run_once(k6, args.profile, i, run_dir, base, database)
        print(f"admin-perf: run {i} of {args.runs}: k6 exit {code}")
        worst = max(worst, code)
    measured = ["--database", database, "--mode", mode]
    if args.rows is not None:
        measured += ["--rows", str(args.rows)]
    results = load_harness("results")
    judged = int(results.main(["judge", *map(str, dirs), "--out", str(args.out), *measured]))
    return max(worst, judged)


if __name__ == "__main__":
    sys.exit(main())
