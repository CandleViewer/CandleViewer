"""#3751: every pull_request-triggered workflow cancels the PR's superseded run.

Without a concurrency group, each PR body edit or push queues another full run behind the
account's concurrency limit, and every PR's `ci-required` waits behind the duplicates. A
group keyed on the PR (its head ref, number or merge ref) with `cancel-in-progress` true for
pull_request events replaces the previous run instead. Scheduled, dispatched and push runs
keep groups a PR run never shares, so they are never cancelled by one.

The orchestrator's count on 2026-10-19 found about 950 auxiliary runs against 14 `pr` runs in
10 hours, so the auxiliary workflows also start fewer runs: `regression-guard` no longer runs on
a PR label event, which changes nothing it reads, and `board-automation` runs no job unless
`GOVERNANCE_ENFORCE` is "true" (observe-only runs enforced nothing) and runs its three close
guards in one job.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
# A PR's own key: its head ref, its number, or its merge ref (github.ref is refs/pull/N/merge).
PR_KEYS = ("github.head_ref", "github.event.pull_request.number", "github.ref")


def _on(doc: dict[Any, Any]) -> Any:
    # YAML 1.1 reads a bare `on:` key as the boolean True.
    return doc.get("on", doc.get(True))


def _pull_request_workflows() -> list[Path]:
    found = []
    for path in WORKFLOWS:
        on = _on(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        names = [on] if isinstance(on, str) else list(on or [])
        if "pull_request" in names or "pull_request_target" in names:
            found.append(path)
    return found


def test_the_scan_finds_the_pull_request_workflows() -> None:
    # Guards the test itself: an empty or wrong list would pass every case below.
    names = {path.stem for path in _pull_request_workflows()}
    assert {"pr", "pr-metadata", "governance", "regression-guard"} <= names


@pytest.mark.parametrize("path", _pull_request_workflows(), ids=lambda p: p.stem)
def test_a_pull_request_workflow_cancels_the_prs_superseded_run(path: Path) -> None:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    concurrency = doc.get("concurrency")
    assert isinstance(concurrency, dict), f"{path.name}: no top-level concurrency group (#3751)"
    group = str(concurrency.get("group", ""))
    assert any(key in group for key in PR_KEYS), f"{path.name}: group {group!r} is not per PR"
    cancel = concurrency.get("cancel-in-progress")
    # True, or an expression that is true for a pull_request event only.
    assert cancel is True or (
        isinstance(cancel, str) and "github.event_name == 'pull_request'" in cancel
    ), f"{path.name}: cancel-in-progress {cancel!r} does not cancel a superseded PR run"


def _load(name: str) -> dict[Any, Any]:
    doc: dict[Any, Any] = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text("utf-8"))
    return doc


def test_regression_guard_reruns_only_when_what_it_reads_changes() -> None:
    # It reads the PR's files, its body (`Closes #N`) and each closed issue's own labels.
    doc = _load("regression-guard.yml")
    assert _on(doc)["pull_request"]["types"] == ["opened", "edited", "synchronize", "reopened"]
    assert doc["concurrency"]["group"] == "regression-guard-${{ github.event.pull_request.number }}"


ENFORCING = "vars.GOVERNANCE_ENFORCE == 'true'"
CLOSE_GUARDS = ["qa-guard", "security-guard --mode close", "a11y-guard"]


def test_board_automation_runs_no_job_unless_the_guards_enforce() -> None:
    jobs = _load("board-automation.yml")["jobs"]
    assert sorted(jobs) == ["close-guards", "kind-sync", "security-label-sync"]
    for name, job in jobs.items():
        # Only `&&` after the gate: an `||` would let a job run without it.
        assert str(job["if"]).startswith(f"{ENFORCING} && "), name
        assert "||" not in str(job["if"]), name
        assert job["permissions"] == {"issues": "write", "contents": "read"}, name
    # A close has its own group, so a label event right after it cannot cancel the close guards.
    group = (
        "board-${{ github.event.issue.number }}-"
        "${{ github.event.action == 'closed' && 'close' || 'sync' }}"
    )
    assert _load("board-automation.yml")["concurrency"] == {
        "group": group,
        "cancel-in-progress": True,
    }


def test_board_automation_runs_the_three_close_guards_in_one_job() -> None:
    job = _load("board-automation.yml")["jobs"]["close-guards"]
    assert job["if"] == f"{ENFORCING} && github.event.action == 'closed'"
    assert job["env"] == {
        "ISSUE_NUMBER": "${{ github.event.issue.number }}",
        "ACTOR_LOGIN": "${{ github.event.sender.login }}",
    }
    steps = job["steps"]
    guards = [step for step in steps if "run" in step]
    assert [step["run"] for step in guards] == [
        f"python -m scripts.gh.run_guard {guard}" for guard in CLOSE_GUARDS
    ]
    # One guard's failure never skips another's check: each later guard runs unless the run was
    # cancelled or Python never got set up, and a hung guard fails its own step at the timeout.
    assert "if" not in guards[0]
    after = "${{ !cancelled() && steps.python.outcome == 'success' }}"
    assert [step["if"] for step in guards[1:]] == [after, after]
    assert [step["timeout-minutes"] for step in guards] == [5, 5, 5]
    # The step that condition reads exists, sets up Python, and comes before every guard.
    (python,) = [i for i, step in enumerate(steps) if step.get("id") == "python"]
    assert str(steps[python]["uses"]).startswith("actions/setup-python@")
    assert python < steps.index(guards[0])
