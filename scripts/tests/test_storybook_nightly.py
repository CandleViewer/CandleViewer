"""#269 (E05-T03): the Storybook gate, `_job-a11y.yml`'s `storybook` job, runs on `pr.yml`'s `e2e`
filter, which leaves the root dependency manifests out on purpose (docs/ci-runbook.md section 2).
So a lockfile-only bump in its tree (a transitive `axe-core` under `@storybook/addon-a11y`, say)
met that gate only on the next PR on the filter. The coordinator's ruling (SYNC-34) adds the
accepted control, designed as `e2e-nightly.yml` (#3383): `storybook-nightly.yml` calls the lane on
`main` every night with its `storybook_only` input, which skips the `a11y` job (a11y-nightly.yml
sweeps every route), and a red scheduled run comments on the tracker issue a repository variable
names, or opens a P1 while it is unset, from a job that holds `issues: write` and nothing else.
A red nightly blocks the next release (C-9.2) through the release checklist (07 section 4.1 and
the issue form `release.yml` opens for each cut)."""

from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
RELEASE_DOC = ROOT / "docs" / "plan" / "07-release-and-prr.md"
RELEASE_FORM = ROOT / ".github" / "ISSUE_TEMPLATE" / "release-checklist.yml"
NIGHTLY = "storybook-nightly.yml"
LANE_FILE = "_job-a11y.yml"
LANE = f"./.github/workflows/{LANE_FILE}"
CRON = "13 2 * * *"
A11Y_IF = "${{ !inputs.storybook_only }}"
REPORT_IF = (
    "${{ always() && github.event_name == 'schedule' && needs.storybook.result != 'success' }}"
)
TRACKER_VAR = "CV_STORYBOOK_NIGHTLY_TRACKER_ISSUE"
#: Context a scheduled run leaves empty or reads differently: the storybook job reads none.
EVENT = ("github.head_ref", "github.base_ref", "github.event", "github.ref")
#: A stand-in `gh` that logs its arguments, one JSON list per call.
FAKE_GH = """import json, os, sys
with open(os.environ["GH_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
"""


@functools.cache
def _load(name: str) -> dict[Any, Any]:
    """A workflow's YAML; its keys are strings except `on`, which YAML 1.1 reads as True."""
    doc: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return doc


def _strings(node: object) -> Iterator[str]:
    """Every string value in a parsed workflow node (not its keys, not its comments)."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def test_storybook_nightly_runs_on_its_schedule_and_on_demand_only() -> None:
    on = _load(NIGHTLY)[True]
    assert set(on) == {"schedule", "workflow_dispatch"}
    assert on["schedule"] == [{"cron": CRON}]
    # A manual run is the scheduled run on demand: no inputs.
    assert on["workflow_dispatch"] == {}


def test_its_cron_minute_is_off_the_hour_marks_and_no_other_workflow_uses_it() -> None:
    minute = CRON.split()[0]
    assert minute not in {"0", "30"}
    others = {
        entry["cron"].split()[0]
        for path in WORKFLOWS.glob("*.yml")
        if path.name != NIGHTLY
        for entry in (_load(path.name).get(True) or {}).get("schedule") or []
    }
    assert others and minute not in others


def test_no_concurrency_group_can_drop_a_scheduled_run() -> None:
    # #3449: a group shared with manual runs lets a newer pending run replace the scheduled one.
    for name in (NIGHTLY, LANE_FILE):
        doc = _load(name)
        assert "concurrency" not in doc
        assert [job for job, body in doc["jobs"].items() if "concurrency" in body] == []


def test_storybook_nightly_runs_the_lanes_storybook_job_alone() -> None:
    jobs = _load(NIGHTLY)["jobs"]
    assert [name for name, job in jobs.items() if "uses" in job] == ["storybook"]
    # No `if:`, secrets or permissions of its own: it runs every night, on `contents: read`.
    assert jobs["storybook"] == {
        "name": "storybook-nightly",
        "uses": LANE,
        "with": {"storybook_only": True},
    }
    only = _load(LANE_FILE)[True]["workflow_call"]["inputs"]["storybook_only"]
    assert (only["type"], only["default"]) == ("boolean", False)
    lane = _load(LANE_FILE)["jobs"]
    # The input skips `a11y` and nothing else: the storybook job runs on every call.
    assert {name: job.get("if") for name, job in lane.items()} == {
        "a11y": A11Y_IF,
        "storybook": None,
    }


def test_pr_calls_the_whole_lane_and_the_nightly_is_its_only_other_caller() -> None:
    calls: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        jobs = (_load(path.name).get("jobs") or {}).values()
        calls[path.name] = [job for job in jobs if job.get("uses") == LANE]
    assert sorted(name for name, found in calls.items() if found) == ["pr.yml", NIGHTLY]
    # pr.yml passes nothing, so a PR runs `a11y` and `storybook`, the required check's two jobs.
    assert [job for job in calls["pr.yml"] if "with" in job] == []


def test_the_storybook_job_reads_no_event_context_a_schedule_changes() -> None:
    # The nightly runs the job on a schedule event on `main`: a step that needed a PR's context
    # would break only at night. The checkout's default ref is the run's commit, the main tip.
    job = _load(LANE_FILE)["jobs"]["storybook"]
    assert [text for text in _strings(job) if any(name in text for name in EVENT)] == []


def test_storybook_nightly_reads_contents_only_and_one_job_can_open_issues() -> None:
    doc = _load(NIGHTLY)
    assert doc["permissions"] == {"contents": "read"}
    held = {name: job.get("permissions") for name, job in doc["jobs"].items()}
    assert held == {"storybook": None, "report": {"issues": "write"}}
    assert _load(LANE_FILE)["jobs"]["storybook"]["permissions"] == {"contents": "read"}


def test_storybook_nightly_report_runs_only_the_gh_cli_for_a_red_scheduled_run() -> None:
    report = _load(NIGHTLY)["jobs"]["report"]
    assert (report["needs"], report["if"]) == ("storybook", REPORT_IF)
    (step,) = report["steps"]
    # No checkout and no action share the job with the write token: only the runner's gh CLI.
    assert set(step) == {"name", "env", "run"}
    assert step["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "GH_REPO": "${{ github.repository }}",
        "RESULT": "${{ needs.storybook.result }}",
        # Named, never searched for; no default, so an unset variable keeps the P1.
        "TRACKER_ISSUE": f"${{{{ vars.{TRACKER_VAR} }}}}",
    }
    # Values reach the script through env, never as expressions expanded into it.
    assert "${{" not in step["run"]


def _report(tmp_path: Path, tracker: str) -> tuple[int, str, list[list[str]]]:
    """Run the report step's script as the runner does (`bash -e`) with the variable's value in
    TRACKER_ISSUE (empty when unset), a stand-in `gh` first on PATH and HOME in tmp_path (no
    stored gh auth, no network): the exit code, output and gh calls."""
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
    (step,) = _load(NIGHTLY)["jobs"]["report"]["steps"]
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
    assert re.fullmatch(r"storybook: nightly Storybook gate failed \(\d{4}-\d{2}-\d{2}\)", call[3])
    labels = ["--label", "qa", "--label", "area/design-system", "--label", "priority/p1"]
    assert call[4:-2] == labels
    assert call[-2] == "--body" and "/owner/repo/actions/runs/7" in call[-1]
    assert "(C-9.2)" in call[-1] and "CI-A11Y-002..004" in call[-1]


def test_report_comments_on_the_named_tracker_issue(tmp_path: Path) -> None:
    rc, out, calls = _report(tmp_path, "269")
    assert rc == 0, out
    (call,) = calls
    assert call[:4] == ["issue", "comment", "269", "--body"] and len(call) == 5
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
    assert f"::error title=storybook-nightly-report::{TRACKER_VAR} " in out
    assert value.strip() not in out and "cv-mark" not in out


def test_release_checklist_needs_a_green_storybook_nightly_on_the_tip_it_cuts() -> None:
    # C-9.2: a red nightly blocks the next release. 07 section 4.1 lists the pre-cut items, and the
    # issue form release.yml opens copies them, so the box the release owner ticks names the run.
    pre_cut = RELEASE_DOC.read_text(encoding="utf-8").split("### 4.1 ", 1)[1].split("\n### ", 1)[0]
    items = [line for line in pre_cut.splitlines() if line.startswith("- [ ] ")]
    named = [item for item in items if f"`{NIGHTLY}`" in item]
    assert len(named) == 1 and "`storybook` job" in named[0]
    form = yaml.safe_load(RELEASE_FORM.read_text(encoding="utf-8"))
    (box,) = [item for item in form["body"] if item.get("id") == "pre-cut"]
    labels: list[str] = [option["label"] for option in box["attributes"]["options"]]
    assert len([label for label in labels if NIGHTLY in label]) == 1


def test_storybook_nightly_adds_no_check_a_required_context_names() -> None:
    # C-9.1 is unchanged: the nightly's check runs carry names no branch-protection context uses.
    protection = json.loads((ROOT / ".github/branch-protection.json").read_text(encoding="utf-8"))
    required = {check["context"] for check in protection["required_status_checks"]["checks"]}
    required |= {name for name in protection["pending_checks"] if name[:1] != "$"}
    jobs = _load(NIGHTLY)["jobs"]
    lane = _load(LANE_FILE)["jobs"]
    checks = {f"{jobs['storybook']['name']} / {job.get('name', n)}" for n, job in lane.items()}
    checks |= {job["name"] for job in jobs.values()}
    assert len(checks) == len(lane) + 2 and not checks & required
