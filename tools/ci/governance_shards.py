#!/usr/bin/env python3
"""#3789: split the governance unit-test suite (`scripts/tests`, `scripts/gh/tests`) into shards.

`governance.yml` runs one shard per matrix job, and its final `governance` job combines their
coverage data, so the 85% gate on `scripts/**` still judges the whole suite. The files are the
ones `pytest scripts/tests scripts/gh/tests` collects: recursive, pytest's default `python_files`
(scripts/pytest.ini sets no other), no `__pycache__` or dot directories, as
`tools/ci/py_test_lanes.py` lists services/api's. Files go greedily, heaviest first, to the
lightest shard. `WEIGHTS` holds the measured cost, in seconds, of every file that took 0.5 s or
more (one sequential run of `pytest -n 0 --durations=0` with coverage on, setup and teardown
included, measured the way CI's governance job runs it: semgrep and gitleaks off PATH, so the
tests gated on those tools skip, as they do there; 2026-10-24: 5,960 tests, about 108 s, the
lower of two runs per file), and any other file costs `DEFAULT_WEIGHT`, about the
median of the rest. So a new, renamed or moved file always lands in a shard, and the split is
deterministic for a given set of files; stale weights cost balance, never coverage.

Two rules for whoever edits the table. (a) A file that is not in the table falls to the
lightest shard and is never dropped; `test_the_shards_partition_every_test_file` (in
`scripts/tests/test_governance_shards.py`) asserts every governance test file maps to exactly
one shard. (b) The pytest wall time each shard prints in its job summary is the signal to
re-measure the table: refresh it when one shard's time creeps up.

`python tools/ci/governance_shards.py 1 4` prints shard 1 of 4, one path per line, relative to
the repository root. Stdlib only.
"""

from __future__ import annotations

import fnmatch
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUITES = ("scripts/tests", "scripts/gh/tests")
PYTHON_FILES = ("test_*.py", "*_test.py")  # pytest's default; scripts/pytest.ini sets no other
DEFAULT_WEIGHT = 0.1
WEIGHTS: dict[str, float] = {
    "scripts/tests/test_backlog_validate_check.py": 11.90,
    "scripts/tests/test_pr_yml_path_filters.py": 6.05,
    "scripts/tests/test_event_coverage.py": 5.95,
    "scripts/tests/test_pr_gate.py": 4.99,
    "scripts/tests/test_error_registry.py": 4.55,
    "scripts/tests/test_pr_yml_gates.py": 4.05,
    "scripts/tests/test_migration_lint.py": 3.80,
    "scripts/tests/test_zap_admin.py": 3.70,
    "scripts/tests/test_relayroom_scripts.py": 3.67,
    "scripts/tests/test_pr_yml_merge_group.py": 3.59,
    "scripts/tests/test_check_secrets_hygiene.py": 3.44,
    "scripts/tests/test_dependabot_alert_gate.py": 3.13,
    "scripts/tests/test_check_gen_freshness.py": 2.93,
    "scripts/tests/test_perf_ingestion_nightly.py": 2.72,
    "scripts/tests/test_check_required_check_reconciliation.py": 2.64,
    "scripts/tests/test_zap_nightly.py": 2.37,
    "scripts/tests/test_check_accepted_risk_expiry.py": 1.89,
    "scripts/tests/test_security_lane.py": 1.83,
    "scripts/tests/test_pr_metadata_yml.py": 1.64,
    "scripts/tests/test_codeowners_backend_paths.py": 1.27,
    "scripts/tests/test_pnpm_effective_policy.py": 1.25,
    "scripts/tests/test_allowed_postinstall_runner.py": 1.08,
    "scripts/tests/test_perf_ws_load.py": 1.06,
    "scripts/tests/test_fuzz_nightly_budget.py": 0.93,
    "scripts/tests/test_perf_storage_nightly.py": 0.91,
    "scripts/tests/test_ws_contracts.py": 0.87,
    "scripts/tests/test_check_pr_metadata.py": 0.79,
    "scripts/tests/test_prepull_images.py": 0.73,
    "scripts/tests/test_nightly_issue.py": 0.61,
    "scripts/tests/test_security_gate.py": 0.53,
    "scripts/tests/test_web_tests_build_deps.py": 0.52,
    "scripts/tests/test_check_backlog_twin_eol.py": 0.50,
}


def suite_files(root: Path = REPO_ROOT) -> list[str]:
    """Every test module pytest collects from `SUITES`, as POSIX paths relative to `root`."""
    found: list[str] = []
    for suite in SUITES:
        for path in (root / suite).rglob("*.py"):
            parts = path.relative_to(root / suite).parts
            if any(part == "__pycache__" or part.startswith(".") for part in parts):
                continue
            if any(fnmatch.fnmatch(path.name, pattern) for pattern in PYTHON_FILES):
                found.append(path.relative_to(root).as_posix())
    return sorted(found)


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
