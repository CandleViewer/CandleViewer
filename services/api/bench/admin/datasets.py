"""E42-Q03 (#1216): load an admin perf dataset into its own test database [BQ-3, BQ-9].

    CV_ADMIN_PERF_DSN=postgresql://cv:<pw>@127.0.0.1:55432/admin_perf_test \\
      uv run python -m bench.admin.datasets load --mode bulk --rows 10000000

The DSN is read from the environment, never from argv (it carries a password), and never
printed. Two lines guard it, the first before anything connects:
1. `tests/load/admin/guard.py`: a loopback postgres URL with no query, naming the database that
   `--mode`'s dataset owns (`bulk` -> `admin_perf_test`, `chained` -> `admin_perf1m_test`);
2. the fixture loader's own refusal (`tests/fixtures/admin/seed.connect_test_database`), which
   reads the server's `current_database()` before any row.
The loader is AUDIT-10M's (`tests/fixtures/admin/audit_10m.load_audit_10m`), imported, never
copied: `bulk` is K01's bulk load (`chained=False`, the query budgets), `chained` goes through the
chain trigger (verify and export, part 4). Audit rows are permanent (C-5.7), so a database holds one
set: a second load of the same mode and size loads nothing, any other is refused by the loader.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from typing import Final

from bench.admin import load_harness

DSN_ENV: Final = "CV_ADMIN_PERF_DSN"
MAX_ROWS: Final = 10_000_000  # AUDIT-10M's size: the loader's own ROWS
DEFAULT_ROWS: Final = {"bulk": 10_000_000, "chained": 1_000_000}  # [BQ-3]

Loader = Callable[..., int]


def _audit_10m() -> Loader:
    from tests.fixtures.admin.audit_10m import load_audit_10m  # psycopg, on use

    return load_audit_10m


def load(dsn: str, mode: str, rows: int, loader: Loader | None = None) -> tuple[str, int]:
    """Guard, then load; the database name and the dataset's row count after."""
    guard = load_harness("guard")
    name = str(guard.check_dataset(dsn, mode))  # TargetRefused before any connection
    if not 1 <= rows <= MAX_ROWS:
        raise ValueError(f"--rows must be 1 to {MAX_ROWS}")
    run = loader if loader is not None else _audit_10m()
    return name, int(run(dsn, rows, chained=mode == "chained"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load an admin perf dataset (E42-Q03).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    cmd = sub.add_parser("load")
    cmd.add_argument("--mode", choices=sorted(DEFAULT_ROWS), required=True)
    cmd.add_argument("--rows", type=int)
    args = parser.parse_args(argv)
    dsn = os.environ.get(DSN_ENV, "")
    rows = args.rows if args.rows is not None else DEFAULT_ROWS[args.mode]
    try:
        name, count = load(dsn, args.mode, rows)
    except ValueError as exc:  # the guard's TargetRefused is one
        print(f"datasets: refused: {exc}", file=sys.stderr)
        return 2
    print(f"datasets: {name} holds AUDIT-10M ({args.mode}): {count} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
