"""Meta-test: the a11y workflows run the E47-Q04 gates, redact before upload, add no permission."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PR_JOB = (ROOT / ".github/workflows/_job-a11y.yml").read_text(encoding="utf-8")
NIGHTLY = (ROOT / ".github/workflows/a11y-nightly.yml").read_text(encoding="utf-8")
PR_YML = (ROOT / ".github/workflows/pr.yml").read_text(encoding="utf-8")
UPLOAD_IF = "if: ${{ always() && steps.redact.outcome == 'success' }}"


def _redact_then_upload(wf: str, artifact: str) -> None:
    redact = wf.index("id: redact")
    assert "tools.a11y.redact reports/a11y" in wf[redact : redact + 400]
    upload = wf.index(f"name: {artifact}")
    assert redact < upload
    assert UPLOAD_IF in wf[wf.rindex("upload-artifact", 0, upload) : upload]


def test_pr_job_runs_inventory_and_uploads_only_after_a_successful_redaction() -> None:
    assert "inventory reports/a11y/axe.json" in PR_JOB
    _redact_then_upload(PR_JOB, "a11y-reports")


def test_nightly_runs_the_full_tier_inventory_and_redacts_before_upload() -> None:
    assert "inventory reports/a11y/axe.json --tier full" in NIGHTLY
    _redact_then_upload(NIGHTLY, "a11y-sweep-reports")


def test_pa11y_runs_in_the_nightly_only_with_its_config_and_no_chromium_download() -> None:
    assert "pa11y" not in PR_JOB
    assert 'PUPPETEER_SKIP_DOWNLOAD: "true"' in NIGHTLY
    assert "gates pa11y reports/a11y/pa11y.json --config reports/a11y/pa11yci.json" in NIGHTLY
    assert NIGHTLY.index("pa11y-ci --config") < NIGHTLY.index("id: redact")
    ws = (ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8")
    assert "\n  puppeteer: false\n" in ws


def test_gate_output_is_redacted_before_the_job_summary() -> None:
    for wf in (PR_JOB, NIGHTLY):
        for line in wf.splitlines():
            if "tools.a11y.gates" in line and "GITHUB_STEP_SUMMARY" in line:
                assert "2>&1 | python -m tools.a11y.redact -" in line, line  # stderr (A11Y-INFRA) too


def test_no_workflow_level_write_permission_was_added() -> None:
    for wf in (PR_JOB, NIGHTLY):
        assert "\npermissions:\n  contents: read\n\njobs:" in wf


def test_pr_path_filter_covers_the_new_tests_and_the_register() -> None:
    for path in (
        "scripts/tests/test_a11y_gates.py",
        "scripts/tests/test_a11y_inventory.py",
        "scripts/tests/test_a11y_redact.py",
        "scripts/tests/test_a11y_workflow.py",
        "docs/plan/a11y/findings.json",
    ):
        assert f"- '{path}'" in PR_YML, path
    assert "test_a11y_inventory.py" in PR_JOB and "test_a11y_workflow.py" in PR_JOB
