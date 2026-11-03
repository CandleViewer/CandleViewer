"""Meta-test: _job-a11y.yml runs the E47-Q04 gates and redacts before upload, with no new permission."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_workflow_wires_the_new_gates_without_new_permissions() -> None:
    wf = (ROOT / ".github/workflows/_job-a11y.yml").read_text(encoding="utf-8")
    assert "inventory reports/a11y/axe.json" in wf and "pa11y reports/a11y/pa11y.json" in wf
    assert "tools.a11y.redact reports/a11y" in wf
    assert wf.index("tools.a11y.redact") < wf.index("name: a11y-reports")
    assert "write" not in wf.split("jobs:")[0]  # the workflow-level permissions stay read-only
