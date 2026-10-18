"""#3383: C-9.2 asks for a nightly full Playwright matrix, but no scheduled workflow called
`_job-e2e.yml`: only `a11y-nightly.yml` ran Playwright, with the a11y config. So a change that
`pr.yml`'s `e2e` filter leaves out on purpose, such as a root dependency manifest
(docs/ci-runbook.md section 2), got no e2e signal until a later PR started the lane.

`e2e-nightly.yml` calls `_job-e2e.yml` on `main` every night and runs all of it: the four
`e2e-web` shards, `e2e-staging`, `a11y-axe` and `e2e-electron`. `e2e-electron` runs when its caller
sets `_job-e2e.yml`'s `electron` input, as the nightly does (the suite is green since #3393), or on
a `release/*` head: `pr.yml` keeps the default. A red scheduled run opens an issue from a job that
holds `issues: write` and nothing else, and runs no checkout and no action."""

from __future__ import annotations

import functools
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
NIGHTLY = "e2e-nightly.yml"
LANE_FILE = "_job-e2e.yml"
LANE = f"./.github/workflows/{LANE_FILE}"
CRON = "53 2 * * *"
#: The lane's jobs that run on every call: the matrix the ticket's "Done when" names.
EVERY_CALL = {"e2e-web", "e2e-staging", "a11y-axe"}
#: Context a scheduled run leaves empty; only e2e-electron's `if:` may read it ("not release/*").
PR_ONLY = ("github.head_ref", "github.base_ref", "github.event.pull_request", "github.event.number")
ELECTRON_IF = "${{ inputs.electron || startsWith(github.head_ref, 'release/') }}"
REPORT_IF = "${{ always() && github.event_name == 'schedule' && needs.e2e.result != 'success' }}"


@functools.cache
def _load(name: str) -> dict[Any, Any]:
    """A workflow's YAML; its keys are strings except `on`, which YAML 1.1 reads as True."""
    doc: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return doc


def _triggers(name: str) -> dict[str, Any]:
    on: dict[str, Any] = _load(name)[True]
    return on


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


def test_e2e_nightly_runs_on_its_schedule_and_on_demand_only() -> None:
    on = _triggers(NIGHTLY)
    assert set(on) == {"schedule", "workflow_dispatch"}
    assert on["schedule"] == [{"cron": CRON}]
    # A manual run is the scheduled run on demand: no inputs, so none can trim the matrix.
    assert on["workflow_dispatch"] == {}
    assert _load(NIGHTLY)["concurrency"] == {"group": "e2e-nightly", "cancel-in-progress": False}


def test_e2e_nightly_runs_the_whole_e2e_lane_every_night() -> None:
    jobs = _load(NIGHTLY)["jobs"]
    assert [name for name, job in jobs.items() if "uses" in job] == ["e2e"]
    # No `if:`, secrets or permissions of its own: it runs every night, on `contents: read`. It
    # asks for e2e-electron, which pr.yml runs on release/* heads only (C-9.2's full matrix).
    assert jobs["e2e"] == {"name": "e2e-nightly", "uses": LANE, "with": {"electron": True}}
    lane = _load(LANE_FILE)["jobs"]
    assert set(lane) == EVERY_CALL | {"e2e-electron"}
    assert [name for name in sorted(EVERY_CALL) if "if" in lane[name]] == []
    assert lane["e2e-electron"]["if"] == ELECTRON_IF
    assert lane["e2e-web"]["strategy"]["matrix"] == {"shard": [1, 2, 3, 4]}


def test_e2e_lane_reads_no_pull_request_context_a_schedule_leaves_empty() -> None:
    # The nightly calls the lane on a schedule event, where these are empty: a job that needed one
    # would break only at night. e2e-electron's `if:` reads the head ref as "not a release head".
    lane = _load(LANE_FILE)["jobs"]
    assert [text for text in _strings(lane) if any(name in text for name in PR_ONLY)] == [
        ELECTRON_IF
    ]


def test_e2e_electron_runs_when_its_caller_asks_or_on_a_release_head() -> None:
    electron = _triggers(LANE_FILE)["workflow_call"]["inputs"]["electron"]
    assert (electron["type"], electron["default"]) == ("boolean", False)
    assert _load(LANE_FILE)["jobs"]["e2e-electron"]["if"] == ELECTRON_IF
    # The callers: pr.yml passes nothing, so a PR runs the smoke on release/* heads only, as before.
    calls: dict[str, list[dict[str, Any]]] = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        jobs = (_load(path.name).get("jobs") or {}).values()
        calls[path.name] = [job for job in jobs if job.get("uses") == LANE]
    assert sorted(name for name, found in calls.items() if found) == [NIGHTLY, "pr.yml"]
    assert [job for job in calls["pr.yml"] if "with" in job] == []


def test_e2e_nightly_reads_contents_only_and_one_job_can_open_issues() -> None:
    doc = _load(NIGHTLY)
    assert doc["permissions"] == {"contents": "read"}
    held = {name: job.get("permissions") for name, job in doc["jobs"].items()}
    assert held == {"e2e": None, "report": {"issues": "write"}}


def test_e2e_nightly_report_opens_an_issue_for_a_red_scheduled_run() -> None:
    report = _load(NIGHTLY)["jobs"]["report"]
    assert (report["needs"], report["if"]) == ("e2e", REPORT_IF)
    (step,) = report["steps"]
    # No checkout and no action share the job with the write token: only the runner's gh CLI.
    assert set(step) == {"name", "env", "run"}
    assert step["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "GH_REPO": "${{ github.repository }}",
        "RESULT": "${{ needs.e2e.result }}",
    }
    # Values reach the script through env, never as expressions expanded into it.
    assert "${{" not in step["run"]
    assert "gh issue create" in step["run"] and "/actions/runs/$GITHUB_RUN_ID" in step["run"]


def test_e2e_nightly_adds_no_check_a_required_context_names() -> None:
    # C-9.1 is unchanged: the nightly's check runs carry names no branch-protection context uses.
    protection = json.loads((ROOT / ".github/branch-protection.json").read_text(encoding="utf-8"))
    required = set(protection["required_status_checks"]["contexts"])
    required |= set(protection["x-pending-contexts"])
    jobs = _load(NIGHTLY)["jobs"]
    lane = _load(LANE_FILE)["jobs"]
    checks = {f"{jobs['e2e']['name']} / {job.get('name', name)}" for name, job in lane.items()}
    checks |= {job["name"] for job in jobs.values()}
    assert len(checks) == len(lane) + 2 and not checks & required
