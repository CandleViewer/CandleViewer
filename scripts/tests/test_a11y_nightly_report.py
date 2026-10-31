"""#5151: `a11y-nightly.yml` (E47-T02, the full accessibility sweep) was red for days with no
report, as no job filed one. It now reports a red scheduled run as `e2e-nightly.yml` and
`storybook-nightly.yml` do: a comment on the tracker issue the repository variable
CV_A11Y_NIGHTLY_TRACKER_ISSUE names, or a P1 while it is unset, from a job that holds
`issues: write` and nothing else and runs only the runner's gh CLI."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
NIGHTLY = ROOT / ".github" / "workflows" / "a11y-nightly.yml"
REPORT_IF = "${{ always() && github.event_name == 'schedule' && needs.sweep.result != 'success' }}"
TRACKER_VAR = "CV_A11Y_NIGHTLY_TRACKER_ISSUE"
#: A stand-in `gh` that logs its arguments, one JSON list per call.
FAKE_GH = """import json, os, sys
with open(os.environ["GH_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
"""


def _load() -> dict[Any, Any]:
    doc: dict[Any, Any] = yaml.safe_load(NIGHTLY.read_text(encoding="utf-8"))
    return doc


def test_a11y_nightly_reads_contents_only_and_one_job_can_open_issues() -> None:
    doc = _load()
    assert doc["permissions"] == {"contents": "read"}
    held = {name: job.get("permissions") for name, job in doc["jobs"].items()}
    assert held == {"sweep": None, "report": {"issues": "write"}}


def test_a11y_nightly_report_runs_only_the_gh_cli_for_a_red_scheduled_run() -> None:
    report = _load()["jobs"]["report"]
    assert (report["needs"], report["if"]) == ("sweep", REPORT_IF)
    (step,) = report["steps"]
    # No checkout and no action share the job with the write token: only the runner's gh CLI.
    assert set(step) == {"name", "env", "run"}
    assert step["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "GH_REPO": "${{ github.repository }}",
        "RESULT": "${{ needs.sweep.result }}",
        # Named, never searched for; no default, so an unset variable keeps the P1.
        "TRACKER_ISSUE": f"${{{{ vars.{TRACKER_VAR} }}}}",
    }
    # Values reach the script through env, never as expressions expanded into it.
    assert "${{" not in step["run"]


def _report(tmp_path: Path, tracker: str) -> tuple[int, str, list[list[str]]]:
    """Run the report step's script as the runner does (`bash -e`) with a stand-in `gh` first on
    PATH and HOME in tmp_path (no stored gh auth, no network): exit code, output and gh calls."""
    if not shutil.which("bash"):  # CI must run these fail-closed proofs
        (pytest.fail if os.environ.get("CI") else pytest.skip)("bash runs the step")
    bin_dir, log = tmp_path / "bin", tmp_path / "gh.log"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(f"#!{sys.executable}\n{FAKE_GH}", encoding="utf-8")
    (bin_dir / "gh").chmod(0o755)
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}", "HOME": str(tmp_path)}
    env |= {"GH_LOG": str(log), "TRACKER_ISSUE": tracker, "RESULT": "failure"}
    env |= {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "owner/repo"}
    env |= {"GITHUB_RUN_ID": "7", "GITHUB_SHA": "0" * 40}
    (step,) = _load()["jobs"]["report"]["steps"]
    proc = subprocess.run(
        ["bash", "-e", "-c", step["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return proc.returncode, proc.stdout + proc.stderr, [json.loads(line) for line in lines]


def test_report_opens_a_p1_while_no_tracker_issue_is_named(tmp_path: Path) -> None:
    rc, out, calls = _report(tmp_path, "")
    assert rc == 0, out
    (call,) = calls
    assert call[:3] == ["issue", "create", "--title"]
    assert re.fullmatch(r"a11y: nightly accessibility sweep failed \(\d{4}-\d{2}-\d{2}\)", call[3])
    labels = ["--label", "qa", "--label", "area/frontend-platform", "--label", "priority/p1"]
    assert call[4:-2] == labels
    assert call[-2] == "--body" and "/owner/repo/actions/runs/7" in call[-1]
    assert "(C-9.2)" in call[-1] and "a11y-sweep-reports" in call[-1]


def test_report_comments_on_the_named_tracker_issue(tmp_path: Path) -> None:
    rc, out, calls = _report(tmp_path, "3853")
    assert rc == 0, out
    (call,) = calls
    assert call[:4] == ["issue", "comment", "3853", "--body"] and len(call) == 5
    assert "/owner/repo/actions/runs/7" in call[4] and "(C-9.2)" in call[4]


@pytest.mark.parametrize(
    "value",
    ["0", "012", "-3", "12a", "#12", " 12", "12 ", "1.5", "owner/repo#12", "7\n::warning::cv-mark"],
)
def test_report_fails_closed_when_the_tracker_is_not_an_issue_number(
    tmp_path: Path, value: str
) -> None:
    # A set value that is not a positive integer files nothing and turns the job red, naming the
    # variable but never echoing the value, which could otherwise add a workflow command.
    rc, out, calls = _report(tmp_path, value)
    assert (rc, calls) == (1, [])
    assert f"::error title=a11y-nightly-report::{TRACKER_VAR} " in out
    assert value.strip() not in out and "cv-mark" not in out
