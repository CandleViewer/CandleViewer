#!/usr/bin/env python3
"""#3789: split the governance unit-test suite (`scripts/tests`, `scripts/gh/tests`) into shards.

`governance.yml` runs one shard per matrix job, and its final `governance` job combines their
coverage data, so the 85% gate on `scripts/**` still judges the whole suite. Files go greedily,
heaviest first, to the lightest shard. `WEIGHTS` holds the measured cost of the heaviest files
(test-seconds on 4 CPUs, CI-like: no semgrep binary, coverage on; 2026-10-19), and any other
file costs `DEFAULT_WEIGHT`, about the median of the rest. So a new or renamed file always lands
in a shard, and the split is deterministic for a given set of files; stale weights cost balance,
never coverage. `python tools/ci/governance_shards.py 1 2` prints shard 1 of 2, one path per
line, relative to the repository root. Stdlib only.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUITES = ("scripts/tests", "scripts/gh/tests")
DEFAULT_WEIGHT = 0.2
WEIGHTS: dict[str, float] = {
    "scripts/tests/test_backlog_validate_check.py": 15.7,
    "scripts/tests/test_event_coverage.py": 10.0,
    "scripts/tests/test_dependabot_alert_gate.py": 6.8,
    "scripts/tests/test_pr_yml_gates.py": 5.8,
    "scripts/tests/test_pr_yml_path_filters.py": 4.8,
    "scripts/tests/test_error_registry.py": 4.3,
    "scripts/tests/test_check_gen_freshness.py": 3.9,
    "scripts/tests/test_check_secrets_hygiene.py": 3.2,
    "scripts/tests/test_pr_yml_merge_group.py": 2.9,
    "scripts/tests/test_check_required_check_reconciliation.py": 2.7,
    "scripts/tests/test_check_accepted_risk_expiry.py": 2.5,
    "scripts/tests/test_security_lane.py": 2.5,
}


def suite_files(root: Path = REPO_ROOT) -> list[str]:
    """Every test module the governance suite collects (pytest's default `test_*.py`)."""
    return sorted(
        path.relative_to(root).as_posix()
        for suite in SUITES
        for path in (root / suite).glob("test_*.py")
    )


def shards(files: Iterable[str], count: int) -> list[list[str]]:
    """`files` split into `count` shards of about equal weight, each sorted."""
    if count < 1:
        raise ValueError("count must be at least 1")
    bins: list[list[str]] = [[] for _ in range(count)]
    load = [0.0] * count
    for name in sorted(files, key=lambda f: (-WEIGHTS.get(f, DEFAULT_WEIGHT), f)):
        lightest = load.index(min(load))
        bins[lightest].append(name)
        load[lightest] += WEIGHTS.get(name, DEFAULT_WEIGHT)
    return [sorted(b) for b in bins]


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or not all(a.isdigit() for a in args):
        print("usage: governance_shards.py INDEX COUNT  (1 <= INDEX <= COUNT)", file=sys.stderr)
        return 2
    index, count = int(args[0]), int(args[1])
    if not 1 <= index <= count:
        print("usage: governance_shards.py INDEX COUNT  (1 <= INDEX <= COUNT)", file=sys.stderr)
        return 2
    chosen = shards(suite_files(), count)[index - 1]
    if not chosen:
        print(f"governance_shards: shard {index} of {count} is empty", file=sys.stderr)
        return 1
    print("\n".join(chosen))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
