#!/usr/bin/env python3
"""#3789: split the governance unit-test suites (`SUITES`) into shards.

`governance.yml` runs one shard per matrix job, and its final `governance` job combines their
coverage data, so the 85% gate on `scripts/**` still judges the whole suite. #4361: besides
`scripts/tests` and `scripts/gh/tests`, the suites hold the infra script, alert-rule and dashboard
tests (`infra/scripts/tests`, `infra/alertmanager/tests`, `infra/grafana/tests`), which no workflow
ran. They need only PyYAML and pytest, and `--cov=scripts` measures `scripts/` alone, so they change
no coverage figure. `EXCLUDED` holds what a suite collects but another lane runs (a test that fails
by design under CI=true without a Grafana runs in the merge queue's integration lane);
scripts/tests/test_no_orphaned_test_dirs.py fails on a test file that no workflow runs, and on an
exclusion that no gating workflow runs. The files are the ones `pytest <suites>` collects, less
`EXCLUDED`: recursive, pytest's default `python_files` (no pytest.ini sets another), no
`__pycache__` or dot directories, as `tools/ci/py_test_lanes.py` lists services/api's. A shard that
mixes `scripts/` and `infra/` files reads the root pytest.ini, whose addopts match
scripts/pytest.ini's. Files go greedily, heaviest first, to the lightest shard. `WEIGHTS` holds the
measured cost, in seconds, of every file that took 0.5 s or more (one sequential run of
`pytest -n 0 --durations=0` with coverage on, setup and teardown included, measured the way CI's
governance job runs it: semgrep and gitleaks off PATH, so the tests gated on those tools skip,
as they do there; 2026-10-24: 6,171 tests, about 125 s; the lower of two runs per file), and any
other file costs `DEFAULT_WEIGHT`, about the median of the rest. So a new, renamed or moved file
always lands in a shard, and the split is deterministic for a given set of files; stale weights
cost balance, never coverage.

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
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SUITES = (
    "scripts/tests",
    "scripts/gh/tests",
    "infra/scripts/tests",
    "infra/alertmanager/tests",
    "infra/grafana/tests",
)
#: Collected by a suite, run by another lane: {path: why, and which lane}.
EXCLUDED: dict[str, str] = {
    "infra/grafana/tests/test_live_render.py": (
        "needs a running Grafana and fails by design under CI=true without GRAFANA_URL: the "
        "integration lane (_job-integration.yml) starts one and runs it in the merge queue"
    ),
}
PYTHON_FILES = ("test_*.py", "*_test.py")  # pytest's default; no pytest.ini sets another
DEFAULT_WEIGHT = 0.1
WEIGHTS: dict[str, float] = {
    # #3180, 2026-10-25: 105.08 s by this recipe on a loaded host (1-minute load 10-12; the lower
    # of two runs), scaled by test_relayroom_scripts.py's 14.85 s against its 3.92 in the same run:
    # both spend their time starting processes. Re-measure it with the table.
    "infra/scripts/tests/test_demo_host_owner_first_run.py": 27.74,
    "scripts/tests/test_backlog_validate_check.py": 13.08,
    "scripts/tests/test_event_coverage.py": 6.67,
    "scripts/tests/test_pr_yml_path_filters.py": 6.42,
    "scripts/tests/test_pr_gate.py": 5.32,
    "scripts/tests/test_error_registry.py": 5.23,
    "scripts/tests/test_pr_yml_gates.py": 4.69,
    "scripts/tests/test_migration_lint.py": 4.63,
    "scripts/tests/test_pr_yml_merge_group.py": 3.98,
    "scripts/tests/test_zap_admin.py": 3.93,
    "scripts/tests/test_relayroom_scripts.py": 3.92,
    "scripts/tests/test_check_secrets_hygiene.py": 3.80,
    "scripts/tests/test_dependabot_alert_gate.py": 3.47,
    "scripts/tests/test_check_gen_freshness.py": 3.44,
    "scripts/tests/test_perf_ingestion_nightly.py": 2.97,
    "scripts/tests/test_check_required_check_reconciliation.py": 2.89,
    "scripts/tests/test_check_accepted_risk_expiry.py": 2.31,
    "scripts/tests/test_zap_nightly.py": 2.23,
    "scripts/tests/test_security_lane.py": 2.15,
    "infra/alertmanager/tests/test_alerting_config.py": 2.10,
    "scripts/tests/test_pr_metadata_yml.py": 1.93,
    "scripts/tests/test_pnpm_effective_policy.py": 1.53,
    "scripts/tests/test_codeowners_backend_paths.py": 1.50,
    "scripts/tests/test_perf_ws_load.py": 1.20,
    "scripts/tests/test_check_pr_metadata.py": 1.10,
    "scripts/tests/test_allowed_postinstall_runner.py": 1.03,
    "scripts/tests/test_perf_storage_nightly.py": 1.02,
    "scripts/tests/test_fuzz_nightly_budget.py": 1.00,
    "scripts/tests/test_ws_contracts.py": 0.94,
    "scripts/tests/test_prepull_images.py": 0.74,
    "scripts/tests/test_no_orphaned_test_dirs.py": 0.73,
    "scripts/tests/test_nightly_issue.py": 0.72,
    "scripts/tests/test_web_tests_build_deps.py": 0.72,
    "scripts/tests/test_storybook_job.py": 0.62,
    "infra/grafana/tests/test_dashboards.py": 0.57,
    "scripts/tests/test_check_backlog_twin_eol.py": 0.57,
    "scripts/tests/test_security_gate.py": 0.57,
    "scripts/tests/test_workflow_concurrency.py": 0.51,
}


def suite_files(root: Path = REPO_ROOT) -> list[str]:
    """Every test module pytest collects from `SUITES` less `EXCLUDED`, as POSIX paths of `root`."""
    found: list[str] = []
    for suite in SUITES:
        for path in (root / suite).rglob("*.py"):
            parts = path.relative_to(root / suite).parts
            if any(part == "__pycache__" or part.startswith(".") for part in parts):
                continue
            name = path.relative_to(root).as_posix()
            if name not in EXCLUDED and any(fnmatch.fnmatch(path.name, p) for p in PYTHON_FILES):
                found.append(name)
    return sorted(found)


def shards(
    files: Iterable[str],
    count: int,
    weights: Mapping[str, float] = WEIGHTS,
    default: float = DEFAULT_WEIGHT,
    pinned: Mapping[str, int] | None = None,
) -> list[list[str]]:
    """`files` split into `count` shards of about equal weight, each sorted.

    A `pinned` file goes to its shard (1-based) first; every other file goes greedily, heaviest
    first, to the lightest shard. #4605: tools/ci/integration_shards.py splits the merge queue's
    integration suite with its own `weights`, `default` and `pinned`."""
    if count < 1:
        raise ValueError("count must be at least 1")
    pins = dict(pinned or {})
    if any(not 1 <= index <= count for index in pins.values()):
        raise ValueError(f"a pinned shard is outside 1..{count}: {pins}")
    bins: list[list[str]] = [[] for _ in range(count)]
    load = [0.0] * count
    names = set(files)
    for name in sorted(names & pins.keys()):
        bins[pins[name] - 1].append(name)
        load[pins[name] - 1] += weights.get(name, default)
    for name in sorted(names - pins.keys(), key=lambda f: (-weights.get(f, default), f)):
        lightest = load.index(min(load))
        bins[lightest].append(name)
        load[lightest] += weights.get(name, default)
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
