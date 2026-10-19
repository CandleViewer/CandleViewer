"""#3789: the governance unit tests run in two shards; the `governance` job judges them together.

One job ran every governance check plus the whole unit-test suite, and the tests alone took
55-69 s of its 90 s budget (E01-Q02), so the budget step failed on more than half of the PR runs
with every test green. `governance.yml` now runs three jobs in parallel: `governance-checks` (the
GOV checks, the canary and the reports), two `governance-tests` shards that write raw coverage
data, and `governance`, which combines that data, applies the 85% gate on `scripts/**` and fails
unless every other job passed. `tools/ci/governance_shards.py` splits the test files by measured
weight. These tests pin the split and the shape; nothing the old job checked is dropped.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.ci import governance_shards as gs  # noqa: E402 - the repo root is on sys.path above

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "governance.yml"
BUDGET = "Job duration budget (<=BUDGET_MS, E01-Q02)"


def _weight(files: list[str]) -> float:
    return sum(gs.WEIGHTS.get(name, gs.DEFAULT_WEIGHT) for name in files)


def _workflow() -> dict[Any, Any]:
    doc: dict[Any, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return doc


def _runs(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in job["steps"])


def test_the_two_shards_partition_every_test_file() -> None:
    files = gs.suite_files()
    first, second = gs.shards(files, 2)
    assert first and second and not set(first) & set(second)
    assert sorted(first + second) == files
    assert gs.shards(files, 2) == [first, second]  # deterministic


def test_the_split_is_balanced_by_the_measured_weights() -> None:
    first, second = gs.shards(gs.suite_files(), 2)
    # Greedy, heaviest first: the shards differ by at most the heaviest single file.
    assert abs(_weight(first) - _weight(second)) <= max(gs.WEIGHTS.values())


def test_every_weighted_file_exists() -> None:
    # A renamed or deleted heavy file would silently fall back to the default weight.
    assert set(gs.WEIGHTS) <= set(gs.suite_files())


def test_the_cli_prints_one_shard_and_refuses_a_bad_index(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert gs.main(["2", "2"]) == 0
    assert capsys.readouterr().out.split() == gs.shards(gs.suite_files(), 2)[1]
    for bad in (["0", "2"], ["3", "2"], ["x", "2"], ["1"], []):
        assert gs.main(bad) == 2, bad
    with pytest.raises(ValueError):
        gs.shards(["a"], 0)


def test_an_empty_shard_fails_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    # More shards than files: a shard job with nothing to run must fail, not run the whole suite.
    monkeypatch.setattr(gs, "suite_files", lambda root=gs.REPO_ROOT: ["scripts/tests/test_a.py"])
    assert gs.main(["2", "2"]) == 1


def test_governance_runs_the_checks_two_test_shards_and_an_aggregate() -> None:
    doc = _workflow()
    jobs = doc["jobs"]
    assert list(jobs) == ["governance-checks", "governance-tests", "governance"]
    assert jobs["governance-tests"]["strategy"] == {"fail-fast": False, "matrix": {"shard": [1, 2]}}
    tests = _runs(jobs["governance-tests"])
    assert 'governance_shards.py "$SHARD" 2' in tests
    assert "--cov=scripts --cov-report= --cov-fail-under=0" in tests
    aggregate = jobs["governance"]
    assert aggregate["needs"] == ["governance-checks", "governance-tests"]
    assert aggregate["if"] == "${{ !cancelled() }}"
    combined = _runs(aggregate)
    assert "python -m coverage combine coverage-shard-1 coverage-shard-2" in combined
    assert "python -m coverage report -m --fail-under=85" in combined
    assert '[ "$CHECKS" = success ] && [ "$TESTS" = success ]' in combined


def test_the_checks_job_keeps_every_check_and_runs_no_unit_tests() -> None:
    checks = _runs(_workflow()["jobs"]["governance-checks"])
    assert "pytest" not in checks
    for script in ("check_rule_refs.py", "check_codeowners_coverage.py", "check_issue_forms.py",
                   "validate.py --check", "validate-backlog.py --quiet",
                   "check_required_check_reconciliation.py", "check_markdown_governance_docs.py",
                   "check_owned_docs_untouched.py", "check_threat_model_ticket_map.py",
                   "check_runbook_completeness.py", "check_bypass_register.py",
                   "check_accepted_risk_expiry.py", "gov_self_test.py --self-test"):  # fmt: skip
        assert script in checks, script


def test_every_job_is_read_only_and_ends_with_its_duration_budget() -> None:
    doc = _workflow()
    assert doc["permissions"] == {"contents": "read"}
    for name, job in doc["jobs"].items():
        assert "permissions" not in job, name
        last = job["steps"][-1]
        assert (last["name"], last["if"], last["env"]["BUDGET_MS"]) == (BUDGET, "always()", "90000")
