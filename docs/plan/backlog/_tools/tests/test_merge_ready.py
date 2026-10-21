"""Tests for merge_ready.py's design-evidence gate. No network: `subprocess.run` is stubbed.

The script does its work at import, so each case runs it as `__main__` with `sys.argv`
patched and `gh` / `verify_pr.py` replaced by canned results. The stubbed `gh pr merge`
always fails, so "reached the merge step" means every gate before it, the design-evidence
gate included, let the PR through.
"""

from __future__ import annotations

import contextlib
import io
import json
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

SCRIPT = str(Path(__file__).resolve().parent.parent / "merge_ready.py")
PAGE_ID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
PNG = "![SCR-1/default](docs/design/E42/img/scr-1.png)"
LINK = "https://design.penpot.app/#/workspace?team-id=t&file-id=f&page-id=p"
APPROVE = {"submittedAt": "2026-10-21T01:00:00Z", "body": "VERDICT: APPROVE"}
CI_OK = {"name": "ci-required", "conclusion": "SUCCESS", "workflowName": "ci"}
Result = subprocess.CompletedProcess[str]


def run_merge_ready(body: str, *flags: str) -> tuple[str, bool]:
    """Run merge_ready.py on PR 1 with `body`; return (last output line, reached merge)."""
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], *_a: Any, **_k: Any) -> Result:
        calls.append([str(c) for c in cmd])
        if calls[-1][:3] == ["gh", "pr", "view"]:
            pr = {
                "state": "OPEN",
                "isDraft": False,
                "mergeable": "MERGEABLE",
                "body": body,
                "commits": [{"committedDate": "2026-10-21T00:00:00Z"}],
                "reviews": [APPROVE],
                "comments": [],
                "statusCheckRollup": [CI_OK],
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(pr), "")
        if calls[-1][:3] == ["gh", "pr", "merge"]:
            return subprocess.CompletedProcess(cmd, 1, "", "stub: merge refused")
        if calls[-1][1].endswith("verify_pr.py"):
            return subprocess.CompletedProcess(cmd, 0, "verify_pr PASS", "")
        raise AssertionError(f"unexpected subprocess call: {cmd}")

    out = io.StringIO()
    with (
        mock.patch.object(sys, "argv", ["merge_ready.py", "1", "E42-D02", *flags]),
        mock.patch("subprocess.run", fake_run),
        contextlib.redirect_stdout(out),
        pytest.raises(SystemExit),
    ):
        runpy.run_path(SCRIPT, run_name="__main__")
    reached_merge = any(c[:3] == ["gh", "pr", "merge"] for c in calls)
    return out.getvalue().strip().splitlines()[-1], reached_merge


@pytest.mark.parametrize(
    "body",
    [f"{LINK}\n{PNG}", f"Page `E42-D02` · id `{PAGE_ID}`\n{PNG}"],
    ids=["workspace-link", "page-id"],
)
def test_design_merge_accepts_workspace_link_or_page_id_with_png(body: str) -> None:
    assert run_merge_ready(body, "--design")[1]


@pytest.mark.parametrize(
    "body",
    [
        f"page **`E42-D02`**\n{PNG}",  # a page name alone
        f"page id pending (file `{PAGE_ID}`)\n{PNG}",  # look-alike prose
        f"https://design.penpot.app/\n{PNG}",  # a bare host mention
        f"page id `{PAGE_ID}`",  # no embedded PNG
        LINK,  # no embedded PNG
    ],
    ids=["page-name-only", "look-alike", "bare-host", "page-id-no-png", "link-no-png"],
)
def test_design_merge_without_penpot_reference_or_png_is_refused(body: str) -> None:
    last, reached_merge = run_merge_ready(body, "--design")
    assert "design evidence missing" in last and not reached_merge


def test_non_design_merge_needs_no_evidence_and_never_imports_done_gate() -> None:
    # `import done_gate` raises ImportError while sys.modules maps it to None
    with mock.patch.dict(sys.modules, {"done_gate": None}):
        assert run_merge_ready("no Penpot evidence at all")[1]
