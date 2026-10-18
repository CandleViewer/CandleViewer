"""Unit tests for scripts/check_required_check_reconciliation.py (GOV-005)."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import check_required_check_reconciliation as recon

ROOT = SCRIPTS_DIR.parent


def _checks(*names: str) -> dict:
    return {"checks": [{"context": name, "app_id": 15368} for name in names]}


FIXTURE_CONSTITUTION = """\
## 9. Quality gates (required CI checks)

| # | Check name | Gate |
|---|---|---|
| 1 | `lint` | ESLint etc |
| 2 | `typecheck` | tsc etc |
| 3 | `unit-backend` | pytest |

## 10. Something else
"""


def _write_constitution(tmp_path: Path) -> Path:
    path = tmp_path / "CONSTITUTION.md"
    path.write_text(FIXTURE_CONSTITUTION, encoding="utf-8")
    return path


def test_load_constitution_check_names_extracts_all_rows(tmp_path: Path) -> None:
    path = _write_constitution(tmp_path)
    names = recon.load_constitution_check_names(str(path))
    assert names == ["lint", "typecheck", "unit-backend"]


def test_load_constitution_check_names_missing_table_raises(tmp_path: Path) -> None:
    path = tmp_path / "CONSTITUTION.md"
    path.write_text("no table here", encoding="utf-8")
    try:
        recon.load_constitution_check_names(str(path))
        assert False, "expected ReconciliationError"
    except recon.ReconciliationError:
        pass


# Regression: encodes E01-Q01 case 1.11 (originating case id) -- required-check
# reconciliation must stay clean when contexts/pending lists agree with §9.
def test_reconcile_clean_when_fully_covered() -> None:
    desired = {
        "required_status_checks": _checks("lint"),
        "pending_checks": {"typecheck": "why", "unit-backend": "why"},
    }
    errors = recon.reconcile(desired, ["lint", "typecheck", "unit-backend"], {"lint"})
    assert errors == []


def test_reconcile_credits_the_lanes_ci_required_judges_only_while_it_is_required() -> None:
    desired = {"required_status_checks": _checks("ci-required"), "pending_checks": {}}
    assert recon.reconcile(desired, ["lint"], {"ci-required"}, {"lint"}) == []
    desired["required_status_checks"] = _checks("lint")
    assert recon.reconcile(desired, ["lint", "typecheck"], {"lint"}, {"typecheck"}) != []


def test_reconcile_flags_unknown_context_name() -> None:
    desired = {
        "required_status_checks": _checks("not-a-real-check"),
        "pending_checks": {},
    }
    errors = recon.reconcile(desired, ["lint"], {"not-a-real-check"})
    assert any("not-a-real-check" in e for e in errors)


def test_reconcile_flags_missing_check_from_both_lists() -> None:
    desired = {
        "required_status_checks": _checks("lint"),
        "pending_checks": {},
    }
    errors = recon.reconcile(desired, ["lint", "typecheck"], {"lint"})
    assert any("typecheck" in e and "missing" in e for e in errors)


def test_reconcile_flags_an_enforced_or_unexplained_pending_check() -> None:
    desired = {
        "required_status_checks": _checks("lint"),
        "pending_checks": {"lint": "why", "typecheck": " ", "bogus": ""},
    }
    errors = recon.reconcile(desired, ["lint", "typecheck"], {"lint"})
    assert any("'lint' is enforced" in e for e in errors)
    assert any("'typecheck' is missing" in e for e in errors)  # a blank reason does not count
    assert any("'bogus' in branch-protection.json is not a §9 check" in e for e in errors)
    with pytest.raises(recon.ReconciliationError, match="pending_checks must be an object"):
        recon.reconcile({**desired, "pending_checks": ["typecheck"]}, ["lint"], {"lint"})


def test_reconcile_flags_required_context_without_workflow_job() -> None:
    desired = {
        "required_status_checks": _checks("lint"),
        "pending_checks": {},
    }
    errors = recon.reconcile(desired, ["lint"], workflow_job_names={"typecheck"})
    assert any("no check run named 'lint'" in e for e in errors)


def test_reconcile_fails_closed_when_no_workflow_reports_the_check() -> None:
    desired = {"required_status_checks": _checks("lint"), "pending_checks": {}}
    errors = recon.reconcile(desired, ["lint"], workflow_job_names=set())
    assert any("no check run named 'lint'" in e for e in errors)


def test_load_workflow_job_names_extracts_top_level_jobs(tmp_path: Path) -> None:
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "ci.yml").write_text(
        "name: CI\non: [pull_request]\njobs:\n  lint:\n    runs-on: ubuntu-latest\n"
        "  typecheck:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    names = recon.load_workflow_job_names(str(wf_dir / "*.yml"))
    assert names == {"lint", "typecheck"}


def test_load_workflow_job_names_reports_only_names_a_check_run_carries(tmp_path: Path) -> None:
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    (wf_dir / "pr.yml").write_text(
        "on: [pull_request]\njobs:\n  lane:\n    uses: ./.github/workflows/_job.yml\n"
        "  plain:\n    runs-on: x\n  grid:\n    strategy:\n      matrix:\n        n: [1, 2]\n",
        encoding="utf-8",
    )
    (wf_dir / "_job.yml").write_text(
        "on:\n  workflow_call:\njobs:\n  lint:\n    runs-on: x\n"
        "  shard:\n    name: shard (${{ matrix.n }})\n",
        encoding="utf-8",
    )
    (wf_dir / "docs.yml").write_text(
        "on:\n  pull_request:\n    paths: [docs/**]\njobs:\n  docs:\n    runs-on: x\n",
        encoding="utf-8",
    )
    assert recon.load_workflow_job_names(str(wf_dir / "*.yml")) == {"lane / lint", "plain"}


def test_load_workflow_job_names_empty_when_no_files(tmp_path: Path) -> None:
    names = recon.load_workflow_job_names(str(tmp_path / "*.yml"))
    assert names == set()


def test_load_workflow_job_names_skips_reusable_and_unrelated_workflows() -> None:
    names = recon.load_workflow_job_names(str(ROOT / ".github/workflows/*.yml"))
    assert {"ci-required", "pr-metadata", "architecture", "governance", "js / lint"} <= names
    # _job-js.yml's jobs, lanes that call a reusable workflow, a matrix job, a schedule
    unreported = {"lint", "typecheck", "js", "py", "contract", "e2e / e2e-web", "governance-drift"}
    assert not unreported & names


# Security review of #3103: a lane's caller name would never arrive while its lane runs.
def test_reconcile_repo_refuses_a_required_lane_caller_name(tmp_path: Path) -> None:
    desired = json.loads((ROOT / ".github/branch-protection.json").read_text(encoding="utf-8"))
    desired["required_status_checks"]["checks"].append({"context": "contract", "app_id": 15368})
    path = tmp_path / "branch-protection.json"
    path.write_text(json.dumps(desired), encoding="utf-8")
    workflows = str(ROOT / ".github/workflows/*.yml")
    errors, _ = recon.reconcile_repo(str(path), str(ROOT / "CONSTITUTION.md"), workflows)
    assert any("no check run named 'contract'" in e for e in errors), errors


# #3103: the file requires only `ci-required`; prove it judges every C-9.1 check.
def test_repo_ci_required_judges_every_c91_check_or_the_file_lists_it_pending() -> None:
    errors, pending = recon.reconcile_repo(
        str(ROOT / ".github/branch-protection.json"),
        str(ROOT / "CONSTITUTION.md"),
        str(ROOT / ".github/workflows/*.yml"),
    )
    assert errors == []
    assert pending == ["bundle-size", "pr-metadata"]


DUPLICATE_JS_LANE = " js: {applicable: false, result: process.env.RESULT_JS},"


@pytest.mark.parametrize(
    "workflow,old,new,expected",
    [
        ("pr.yml", "      - contract\n", "", "§9 check 'contract' is missing"),
        ("pr.yml", "result: process.env.RESULT_SECURITY", "result: process.env.X", "'sast'"),
        (
            "pr.yml",
            "applicable: isTrue(process.env.FILTER_E2E), result: process.env.RESULT_E2E",
            "applicable: false, result: process.env.RESULT_E2E",
            "'e2e-smoke'",
        ),
        (
            "pr.yml",
            "    if: always()\n    needs:\n      - changed-paths\n      - gates",
            "    needs:\n      - changed-paths\n      - gates",
            "if: always()",
        ),
        ("_job-security.yml", "\n  trivy:\n", "\n  trivy-scan:\n", "'container-scan'] is stale"),
        # Each lane's result must come from its own job or gates output (security review, #3103).
        ("pr.yml", "needs.contract.result", "needs.integration.result", "'contract' is missing"),
        ("pr.yml", "needs.gates.outputs.gen ", "needs.gates.outputs.commitlint ", "no judged gen"),
        ("pr.yml", "gen: ${{ steps.gen.outcome", "gen: ${{ steps.commitlint.outcome", "judged gen"),
        # Code review of #3103: each probe that stayed green.
        ("pr.yml", '"secret-scan": { applicable: true', '"x": { applicable: true', "secret-scan"),
        ("pr.yml", " py: {", DUPLICATE_JS_LANE + " py: {", "lane 'js' repeats"),
        ("pr.yml", "  node scripts/ci_gate", "  true || node scripts/ci_gate", "exit"),
        ("pr.yml", "          ')\"\n", "          ')\" || true\n", "whose exit is the resolver's"),
        ("pr.yml", "conclusion\n", "conclusion\n        continue-on-error: true\n", "continue-on"),
        ("_job-security.yml", "if: ${{ inputs.image_changed }}", "if: ${{ false }}", "trivy"),
    ],
)
def test_dropping_a_lane_from_ci_required_fails_the_proof(
    tmp_path, workflow, old, new, expected
) -> None:
    workflows = tmp_path / "workflows"
    shutil.copytree(ROOT / ".github/workflows", workflows)
    text = (workflows / workflow).read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    (workflows / workflow).write_text(text.replace(old, new), encoding="utf-8")
    errors, _ = recon.reconcile_repo(
        str(ROOT / ".github/branch-protection.json"),
        str(ROOT / "CONSTITUTION.md"),
        str(workflows / "*.yml"),
    )
    assert any(expected in e for e in errors), errors
