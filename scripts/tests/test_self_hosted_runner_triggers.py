"""E11-X02 (#392; CE-E08): a self-hosted runner never runs a pull request's code.

The bench and deploy runners (cv-bench-01, dev-host, staging-host) execute repository code on a
machine the project owns. No self-hosted job is reachable by trigger set alone: a job on one of
them must sit in a workflow that no pull request, `pull_request_target` or merge-queue event
starts, and that no other workflow calls (`workflow_call`, which a PR workflow could reach). A
`workflow_run` job is allowed only when its `if:` pins the triggering run to a push (deploy-dev's
guard): the event itself carries a PR head. A `runs-on` built from an expression may resolve to a
self-hosted label, so it counts as one.
One exemption, E03-T14's K01 policy P4: a job whose `runs-on` is `fromJSON` of a hosted `needs:`
job's `runs_on` output, where that job's only steps are actions/checkout and one step whose whole
command is ROUTE_COMMAND and whose id the output names. The exemption does not look at the calling
workflow's triggers because the route decides per event (every pull_request event goes to the
hosted fallback; scripts/tests/test_gpu_runner_health.py pins that). The route is trusted only
because runner-side admission (E03-K01 §7) is the control; the residual, a PR editing the route
script on pull_request, is recorded open in docs/plan/threat-models/E03-supply-chain.md (§5, G1).
Fork-PR approval is a repository setting this test cannot see; ci-gates-e11.md records it (BQ-167).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
PR_EVENTS = frozenset(
    {"pull_request", "pull_request_target", "merge_group", "workflow_call"}
)
ROUTE_COMMAND = (
    "python3 -I tools/ci/gpu_runner_health.py route"  # _job-engine-bench.yml
)


def _triggers(doc: dict[Any, Any]) -> set[str]:
    on = doc.get("on", doc.get(True))  # YAML 1.1 reads a bare `on:` key as True
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(t) for t in on}
    return {str(t) for t in (on or {})}


# GitHub-hosted image labels; any other label (a bare custom label, a larger-runner name) or a
# runner `group:` may land on a machine the project owns, so it counts as self-hosted.
_HOSTED_LABEL = re.compile(r"(?:ubuntu|windows|macos)-[A-Za-z0-9.]+(?:-[A-Za-z0-9.]+)*")
# The route step's environment, exactly as _job-engine-bench.yml sets it.
ROUTE_ENV = {
    "CV_GPU_BENCH_RUNNER": "${{ vars.CV_GPU_BENCH_RUNNER }}",
    "GITHUB_REPOSITORY": "${{ github.repository }}",
}
_ROUTE_STEP_KEYS = frozenset({"id", "name", "env", "run"})
_ROUTE_JOB_KEYS = frozenset(
    {"name", "runs-on", "timeout-minutes", "outputs", "steps", "permissions"}
)
_CHECKOUT_KEYS = frozenset({"uses", "name", "with"})
_CHECKOUT_WITH_KEYS = frozenset({"persist-credentials", "sparse-checkout"})


def _maybe_self_hosted(runs_on: object) -> bool:
    if runs_on is None or runs_on == "":
        return False  # a job that calls a reusable workflow has no runs-on of its own
    if isinstance(runs_on, dict):
        if "group" in runs_on or set(runs_on) != {"labels"}:
            return True
        runs_on = runs_on["labels"]
    labels = runs_on if isinstance(runs_on, list) else [runs_on]
    return not labels or any(
        not isinstance(x, str) or not _HOSTED_LABEL.fullmatch(x) for x in labels
    )


def _is_checkout(step: object) -> bool:
    """actions/checkout with nothing that picks another ref, repository or path."""
    if not isinstance(step, dict) or not set(step) <= _CHECKOUT_KEYS:
        return False
    with_ = step.get("with") or {}
    return (
        str(step.get("uses", "")).startswith("actions/checkout@")
        and isinstance(with_, dict)
        and set(with_) <= _CHECKOUT_WITH_KEYS
    )


def _is_route_step(step: object) -> bool:
    return (
        isinstance(step, dict)
        and set(step) <= _ROUTE_STEP_KEYS
        and isinstance(step.get("run"), str)
        and step["run"].strip() == ROUTE_COMMAND
        and step.get("env") == ROUTE_ENV
    )


def _is_p4_route(route: object) -> bool:
    """A hosted job whose only steps are checkout and the exact route command it exports."""
    if not isinstance(route, dict) or not set(route) <= _ROUTE_JOB_KEYS:
        return False
    if _maybe_self_hosted(route.get("runs-on")):
        return False
    steps = route.get("steps")
    if not isinstance(steps, list):
        return False
    cmd = [s for s in steps if not _is_checkout(s)]
    if len(cmd) != 1 or not _is_route_step(cmd[0]):
        return False
    step_id = cmd[0].get("id")
    outputs = route.get("outputs")
    output = outputs.get("runs_on") if isinstance(outputs, dict) else None
    return (
        isinstance(step_id, str)
        and isinstance(output, str)
        and output.replace(" ", "") == f"${{{{steps.{step_id}.outputs.runs_on}}}}"
    )


def _policy_routed(job: dict[Any, Any], doc: dict[Any, Any]) -> bool:
    """E03-T14: runs-on is the runs_on output of a needs: job that is exactly the P4 route."""
    if "env" in doc or "defaults" in doc:
        return False  # a workflow-wide env or default shell reaches the route step
    jobs = doc.get("jobs") or {}
    needs = job.get("needs", [])
    runs_on = job.get("runs-on")
    if not isinstance(runs_on, str):
        return False
    return any(
        isinstance(dep, str)
        and re.fullmatch(
            rf"\$\{{\{{\s*fromJSON\(needs\.{re.escape(dep)}\.outputs\.runs_on\)\s*\}}\}}",
            runs_on,
        )
        is not None
        and _is_p4_route(jobs.get(dep))
        for dep in ([needs] if isinstance(needs, str) else needs)
    )


def violations(doc: dict[Any, Any], name: str) -> list[str]:
    """One message per self-hosted job a pull request's code can reach."""
    found: list[str] = []
    events = _triggers(doc)
    jobs = doc.get("jobs") or {}
    for job_id, job in jobs.items():
        if not isinstance(job, dict) or not _maybe_self_hosted(job.get("runs-on", "")):
            continue
        # A P4-routed job skips only the PR-trigger check; the workflow_run pin still applies.
        pr_events = set() if _policy_routed(job, doc) else events & PR_EVENTS
        for event in sorted(pr_events):
            found.append(
                f"{name}: job '{job_id}' runs on a self-hosted runner on '{event}'"
            )
        guard = str(job.get("if", "")).replace('"', "'")
        if "workflow_run" in events and "workflow_run.event == 'push'" not in guard:
            found.append(
                f"{name}: job '{job_id}' runs a workflow_run that is not pinned to a push"
            )
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
        # a label-only runs-on, and a runner group, without the word self-hosted
        ({"pull_request": None}, ["gpu-box"], "", "on 'pull_request'"),
        ({"pull_request": None}, "bench", "", "on 'pull_request'"),
        ({"pull_request": None}, {"group": "gpu"}, "", "on 'pull_request'"),
        (
            {"pull_request": None},
            "${{ fromJSON(vars.RUNNER) }}",
            "",
            "on 'pull_request'",
        ),
        (
            {"workflow_run": {"workflows": ["pr"]}},
            ["self-hosted"],
            "true",
            "not pinned to a push",
        ),
    ],
)
def test_a_planted_workflow_fails(
    on: object, runs_on: object, guard: str, expected: str
) -> None:
    doc = {"on": on, "jobs": {"bench": {"runs-on": runs_on, "if": guard, "steps": []}}}
    found = violations(doc, "planted.yml")
    assert len(found) == 1 and expected in found[0] and "job 'bench'" in found[0]


@pytest.mark.parametrize(
    ("on", "runs_on", "guard"),
    [
        ({"pull_request": None}, "ubuntu-latest", ""),
        (
            {"workflow_dispatch": None, "schedule": [{"cron": "0 3 * * *"}]},
            ["self-hosted"],
            "",
        ),
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


_CHECKOUT = {
    "uses": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
    "with": {"persist-credentials": False, "sparse-checkout": "tools/ci"},
}
_ROUTE_STEP = {"name": "route", "id": "route", "env": ROUTE_ENV, "run": ROUTE_COMMAND}
_ROUTE_OUT = "${{ steps.route.outputs.runs_on }}"
_LITERAL = '["self-hosted","gpu"]'


def _routed(
    steps: list[dict[str, Any]] | None = None,
    route_runs_on: object = "ubuntu-latest",
    output: str = _ROUTE_OUT,
    on: object = None,
    needs: object = "route",
    bench_runs_on: object = "${{ fromJSON(needs.route.outputs.runs_on) }}",
) -> dict[Any, Any]:
    route = {
        "name": "engine-bench-route",
        "runs-on": route_runs_on,
        "timeout-minutes": 5,
        "outputs": {"runs_on": output},
        "steps": [_CHECKOUT, _ROUTE_STEP] if steps is None else steps,
    }
    other = {
        "runs-on": "ubuntu-latest",
        "outputs": {"runs_on": "${{ steps.x.outputs.runs_on }}"},
    }
    other["steps"] = [
        {"id": "x", "run": 'echo runs_on=["self-hosted"] >> $GITHUB_OUTPUT'}
    ]
    return {
        "on": {"workflow_call": {}} if on is None else on,
        "permissions": {"contents": "read"},
        "jobs": {
            "route": route,
            "other": other,
            "bench": {"needs": needs, "runs-on": bench_runs_on},
        },
    }


def test_a_p4_routed_job_passes() -> None:
    assert violations(_routed(), "routed.yml") == []


def test_the_real_engine_bench_route_passes() -> None:
    doc = _load(WORKFLOWS / "_job-engine-bench.yml")
    assert _policy_routed(doc["jobs"]["bench"], doc)
    assert violations(doc, "_job-engine-bench.yml") == []


def test_a_p4_routed_job_on_pull_request_target_passes() -> None:
    # Pinned on purpose: the exemption ignores the caller's triggers because the route itself
    # sends every PR event to the hosted fallback (test_gpu_runner_health.py), and runner-side
    # admission (E03-K01 §7) is the control; the open residual is E03-supply-chain.md §5 G1.
    # The trigger itself is banned repo-wide by tools/ci/check_action_pins.py (SR-132).
    doc = _routed(on={"pull_request_target": None})
    assert violations(doc, "routed.yml") == []


def test_a_p4_routed_job_on_an_unpinned_workflow_run_fails() -> None:
    doc = _routed(on={"workflow_run": {"workflows": ["pr"]}})
    found = violations(doc, "routed.yml")
    assert len(found) == 1 and "not pinned to a push" in found[0]


def _step(**extra: Any) -> dict[str, Any]:
    return {**_ROUTE_STEP, **extra}


def _env(**extra: str) -> dict[str, Any]:
    return {**_ROUTE_STEP, "env": {**ROUTE_ENV, **extra}}


def _checkout(**extra: Any) -> dict[str, Any]:
    return {**_CHECKOUT, "with": {**_CHECKOUT["with"], **extra}}


def _with_route(**extra: Any) -> dict[Any, Any]:
    doc = _routed()
    doc["jobs"]["route"].update(extra)
    return doc


def _with_top(**extra: Any) -> dict[Any, Any]:
    doc = _routed()
    doc.update(extra)
    return doc


_SHELL = {"run": {"shell": "bash --noprofile -e {0}"}}


@pytest.mark.parametrize(
    "doc",
    [
        _routed(
            steps=[
                _CHECKOUT,
                {**_ROUTE_STEP, "run": "python3 -I tools/ci/other.py route"},
            ]
        ),
        _routed(route_runs_on="self-hosted"),
        # a step other than checkout beside the route command
        _routed(steps=[_CHECKOUT, _ROUTE_STEP, {"id": "y", "run": "echo"}]),
        # runs_on sourced from another step than the route command
        _routed(output="${{ steps.y.outputs.runs_on }}"),
        # the script path only in a comment or an echo
        _routed(steps=[_CHECKOUT, _step(run=f"# {ROUTE_COMMAND}\necho x")]),
        _routed(steps=[_CHECKOUT, _step(run=f"echo {ROUTE_COMMAND}")]),
        # needs both, but runs-on points at the job that is not the route
        _routed(
            needs=["route", "other"],
            bench_runs_on="${{ fromJSON(needs.other.outputs.runs_on) }}",
        ),
        _routed(steps=[{"uses": "actions/setup-node@v4"}, _ROUTE_STEP]),
        # the runner variable replaced by a literal: on the step, the route job, the workflow
        _routed(steps=[_CHECKOUT, _env(CV_GPU_BENCH_RUNNER=_LITERAL)]),
        _with_route(env={"CV_GPU_BENCH_RUNNER": _LITERAL}),
        _with_top(env={"CV_GPU_BENCH_RUNNER": _LITERAL}),
        # the route command's interpreter or directory changed around it
        _routed(steps=[_CHECKOUT, _step(shell="bash -e {0}")]),
        _with_route(defaults=_SHELL),
        _with_top(defaults=_SHELL),
        _routed(steps=[_CHECKOUT, _step(**{"working-directory": "tools"})]),
        _routed(steps=[_CHECKOUT, _env(PATH="/tmp/bin")]),
        _with_route(container={"image": "node:22"}),
        # checkout of another ref, repository or path
        _routed(steps=[_checkout(ref="refs/pull/1/head"), _ROUTE_STEP]),
        _routed(steps=[_checkout(repository="someone/fork"), _ROUTE_STEP]),
        _routed(steps=[_checkout(path="tools"), _ROUTE_STEP]),
        # the routed output wrapped in a larger expression
        _routed(
            bench_runs_on="${{ fromJSON(needs.route.outputs.runs_on || '[\"x\"]') }}"
        ),
        _routed(bench_runs_on="${{ fromJSON(needs.route.outputs.runs_on) }}-gpu"),
        # the route step doubled
        _routed(steps=[_CHECKOUT, _ROUTE_STEP, _ROUTE_STEP]),
    ],
)
def test_a_route_that_is_not_exactly_p4_fails(doc: dict[Any, Any]) -> None:
    found = violations(doc, "routed.yml")
    assert any("job 'bench'" in v and "workflow_call" in v for v in found)
