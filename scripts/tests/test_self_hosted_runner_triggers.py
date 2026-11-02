"""E11-X02 (#392; CE-E08): a self-hosted runner never runs a pull request's code.

The bench and deploy runners (cv-bench-01, dev-host, staging-host) execute repository code on a
machine the project owns. A job on one of them must sit in a workflow that no pull request,
`pull_request_target` or merge-queue event starts, and that no other workflow calls
(`workflow_call`, which a PR workflow could reach). A `workflow_run` job is allowed only when its
`if:` pins the triggering run to a push (deploy-dev's guard): the event itself carries a PR head.
A `runs-on` built from an expression may resolve to a self-hosted label, so it counts as one.
Fork-PR approval is a repository setting this test cannot see; ci-gates-e11.md records it (BQ-167).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
PR_EVENTS = frozenset({"pull_request", "pull_request_target", "merge_group", "workflow_call"})


def _triggers(doc: dict[Any, Any]) -> set[str]:
    on = doc.get("on", doc.get(True))  # YAML 1.1 reads a bare `on:` key as True
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(t) for t in on}
    return {str(t) for t in (on or {})}


def _maybe_self_hosted(runs_on: object) -> bool:
    if isinstance(runs_on, dict):
        runs_on = runs_on.get("labels", runs_on.get("group", ""))
    labels = runs_on if isinstance(runs_on, list) else [runs_on]
    return any("self-hosted" in str(x) or "${{" in str(x) for x in labels)


def violations(doc: dict[Any, Any], name: str) -> list[str]:
    """One message per self-hosted job a pull request's code can reach."""
    found: list[str] = []
    events = _triggers(doc)
    for job_id, job in (doc.get("jobs") or {}).items():
        if not isinstance(job, dict) or not _maybe_self_hosted(job.get("runs-on", "")):
            continue
        for event in sorted(events & PR_EVENTS):
            found.append(f"{name}: job '{job_id}' runs on a self-hosted runner on '{event}'")
        guard = str(job.get("if", "")).replace('"', "'")
        if "workflow_run" in events and "workflow_run.event == 'push'" not in guard:
            found.append(f"{name}: job '{job_id}' runs a workflow_run that is not pinned to a push")
    return found


def _load(path: Path) -> dict[Any, Any]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, dict), path
    return doc


def test_self_hosted_jobs_never_run_pr_code() -> None:
    files = sorted(WORKFLOWS.glob("*.y*ml"))
    assert files, "no workflow found"
    found = [v for f in files for v in violations(_load(f), f.name)]
    assert found == [], "\n".join(found)


def test_the_repo_has_self_hosted_jobs_to_check() -> None:
    # The guard must not pass vacuously: the bench and deploy runners exist today.
    hosted = [
        f.name
        for f in sorted(WORKFLOWS.glob("*.y*ml"))
        for job in (_load(f).get("jobs") or {}).values()
        if isinstance(job, dict) and _maybe_self_hosted(job.get("runs-on", ""))
    ]
    assert {"perf-ws-load.yml", "deploy-dev.yml"} <= set(hosted)


@pytest.mark.parametrize(
    ("on", "runs_on", "guard", "expected"),
    [
        ({"pull_request": None}, ["self-hosted", "bench"], "", "on 'pull_request'"),
        ({"pull_request_target": None}, "self-hosted", "", "on 'pull_request_target'"),
        (["merge_group", "push"], ["self-hosted"], "", "on 'merge_group'"),
        ({"workflow_call": None}, ["self-hosted", "gpu"], "", "on 'workflow_call'"),
        ({"pull_request": None}, "${{ fromJSON(vars.RUNNER) }}", "", "on 'pull_request'"),
        ({"workflow_run": {"workflows": ["pr"]}}, ["self-hosted"], "true", "not pinned to a push"),
    ],
)
def test_a_planted_workflow_fails(on: object, runs_on: object, guard: str, expected: str) -> None:
    doc = {"on": on, "jobs": {"bench": {"runs-on": runs_on, "if": guard, "steps": []}}}
    found = violations(doc, "planted.yml")
    assert len(found) == 1 and expected in found[0] and "job 'bench'" in found[0]


@pytest.mark.parametrize(
    ("on", "runs_on", "guard"),
    [
        ({"pull_request": None}, "ubuntu-latest", ""),
        ({"workflow_dispatch": None, "schedule": [{"cron": "0 3 * * *"}]}, ["self-hosted"], ""),
        (
            {"workflow_run": {"workflows": ["main"]}},
            ["self-hosted", "dev-host"],
            "github.event.workflow_run.event == 'push'",
        ),
    ],
)
def test_a_safe_workflow_passes(on: object, runs_on: object, guard: str) -> None:
    doc = {"on": on, "jobs": {"bench": {"runs-on": runs_on, "if": guard, "steps": []}}}
    assert violations(doc, "safe.yml") == []
