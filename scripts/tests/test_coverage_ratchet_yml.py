"""#3508: coverage-ratchet runs only on trusted push runs of this repository's main.

Its job gate, triggers, producers and token are pinned here; docs/ci-runbook.md (CI-COV-*)
records why it has no automatic trigger yet and how to re-enable it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
RATCHET = WORKFLOWS / "coverage-ratchet.yml"
TRUSTED_RUN = {
    "github.event.workflow_run.conclusion == 'success'",
    "github.event.workflow_run.event == 'push'",
    "github.event.workflow_run.head_repository.full_name == github.repository",
    "github.event.workflow_run.head_branch == 'main'",
}


def _load(path: Path) -> dict[Any, Any]:
    doc: dict[Any, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc


def _triggers(doc: dict[Any, Any]) -> dict[str, Any]:
    on = doc.get("on", doc.get(True))  # PyYAML reads the bare key `on` as True
    return {on: None} if isinstance(on, str) else dict(on or {})


def test_every_job_requires_a_successful_push_run_of_this_repositorys_main() -> None:
    for name, job in _load(RATCHET)["jobs"].items():
        # A job-level `if:` is decided before any step; a plain conjunction (no `||`,
        # no negation) keeps every condition binding.
        gate = str(job.get("if", "")).removeprefix("${{").removesuffix("}}")
        assert not re.search(r"\|\||!", gate), name
        assert TRUSTED_RUN <= {" ".join(c.split()) for c in gate.split("&&")}, name


def test_the_ratchet_takes_no_pull_request_or_push_trigger() -> None:
    assert "pull_request_target" not in RATCHET.read_text(encoding="utf-8")
    assert set(_triggers(_load(RATCHET))) <= {"workflow_run", "workflow_dispatch"}


def test_every_producer_the_ratchet_names_runs_on_push_to_main() -> None:
    run = _triggers(_load(RATCHET)).get("workflow_run") or {}
    if run:
        assert (run.get("types"), run.get("branches")) == (["completed"], ["main"])
    by_name = {_load(path).get("name"): path for path in WORKFLOWS.glob("*.yml")}
    for producer in run.get("workflows", []):
        push = _triggers(_load(by_name[producer])).get("push") or {}
        assert "main" in push.get("branches", []), producer


def test_the_token_holds_only_what_the_ratchet_needs() -> None:
    doc = _load(RATCHET)
    assert doc["permissions"] == {"contents": "read"}
    for job in doc["jobs"].values():
        assert job["permissions"] == {
            "actions": "read",
            "contents": "write",
            "pull-requests": "write",
        }


def test_artifacts_come_only_from_the_run_that_triggered_the_ratchet() -> None:
    for job in _load(RATCHET)["jobs"].values():
        downloads = [
            s for s in job["steps"] if "download-artifact@" in s.get("uses", "")
        ]
        assert downloads
        assert {s["with"]["run-id"] for s in downloads} == {
            "${{ github.event.workflow_run.id }}"
        }


def test_steps_check_out_main_and_pass_no_expression_to_a_shell() -> None:
    for job in _load(RATCHET)["jobs"].values():
        uses = [s for s in job["steps"] if "actions/checkout@" in s.get("uses", "")]
        assert [s["with"]["ref"] for s in uses] == ["main"]
        assert not any("${{" in s.get("run", "") for s in job["steps"])
