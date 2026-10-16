"""#2915: `pr.yml` runs the `security` job when only a Semgrep gate path changes.

`.semgrep/**` (the cv-* rules and their rule-test fixtures), `.semgrep-fixtures/**`,
`.semgrepignore` and `tools/ci/check_semgrep_rule_tests.py` are what the Semgrep rule-test checker
and the product scan read. No `changed-paths` filter named them and `security` ran only on
js/py/infra changes, so a PR that edited just a rule, a fixture or the ignore file skipped the
gates built to check exactly that change.

The `ci-required` resolver restates the `security` condition by hand, and
scripts/ci_gate_resolver.mjs treats a lane that ran while "not applicable" as fine. A Semgrep-only
run that failed would therefore stay green in `ci-required` unless the resolver names the same
filters as the job, so these tests pin the filter, the job condition and the resolver together."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
PR_YML = ROOT / ".github" / "workflows" / "pr.yml"
SEMGREP_PATHS = (
    ".semgrep/**",
    ".semgrep-fixtures/**",
    ".semgrepignore",
    "security/semgrep/**",
    "tools/ci/check_semgrep_rule_tests.py",
)
RESOLVER_STEP = "Resolve ci-required conclusion"


def _jobs() -> dict[str, Any]:
    jobs: dict[str, Any] = yaml.safe_load(PR_YML.read_text(encoding="utf-8"))["jobs"]
    return jobs


def _filters() -> dict[str, list[str]]:
    """The `dorny/paths-filter` rules of the `changed-paths` job (its `filters:` block is YAML)."""
    steps = _jobs()["changed-paths"]["steps"]
    (step,) = [s for s in steps if str(s.get("uses", "")).startswith("dorny/paths-filter@")]
    filters: dict[str, list[str]] = yaml.safe_load(step["with"]["filters"])
    return filters


def _outputs_in(condition: str) -> set[str]:
    """The `changed-paths` outputs a job `if:` tests for `'true'`."""
    return set(re.findall(r"needs\.changed-paths\.outputs\.(\w+) == 'true'", condition))


def _resolver_step() -> dict[str, Any]:
    steps: list[dict[str, Any]] = _jobs()["ci-required"]["steps"]
    (step,) = [s for s in steps if s.get("name") == RESOLVER_STEP]
    return step


def _resolver_security_filters() -> set[str]:
    """The filters the resolver script consults when it decides whether `security` applied."""
    lane = re.search(r"\bsecurity:\s*\{(.*?)RESULT_SECURITY", _resolver_step()["run"], re.DOTALL)
    assert lane, "the ci-required resolver script has no `security` lane"
    return {name.lower() for name in re.findall(r"FILTER_(\w+)", lane.group(1))}


def test_pr_yml_semgrep_filter_covers_every_semgrep_gate_path() -> None:
    covered = set(_filters().get("semgrep") or [])
    assert set(SEMGREP_PATHS) <= covered, sorted(set(SEMGREP_PATHS) - covered)


def test_pr_yml_semgrep_filter_paths_exist_in_the_repo() -> None:
    # A path that was renamed away would leave the filter matching nothing, silently.
    for pattern in SEMGREP_PATHS:
        assert (ROOT / pattern.removesuffix("/**")).exists(), pattern


def test_pr_yml_changed_paths_exports_the_semgrep_output() -> None:
    outputs = _jobs()["changed-paths"]["outputs"]
    assert outputs.get("semgrep") == "${{ steps.filter.outputs.semgrep }}"


def test_pr_yml_security_job_runs_when_only_semgrep_paths_change() -> None:
    assert "semgrep" in _outputs_in(_jobs()["security"]["if"])


def test_pr_yml_resolver_security_lane_names_the_same_filters_as_the_job() -> None:
    # Otherwise a failing `security` run that the job condition let through is "not applicable"
    # to the resolver, and ci-required stays green over it.
    assert _resolver_security_filters() == _outputs_in(_jobs()["security"]["if"])


def test_pr_yml_resolver_reads_each_security_filter_from_its_changed_paths_output() -> None:
    env = _resolver_step()["env"]
    for name in sorted(_resolver_security_filters()):
        expected = "${{ needs.changed-paths.outputs." + name + " }}"
        assert env.get("FILTER_" + name.upper()) == expected, name
