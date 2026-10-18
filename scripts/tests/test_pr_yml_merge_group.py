"""#3433: `pr.yml` listens to `merge_group`, so `main` can move to GitHub's merge queue.

The queue builds `main` plus the PR as a merge group and waits for `ci-required` on it, the one
check protection requires. These tests pin what a merge group's run needs: the trigger; a
concurrency group per merge group that is never cancelled; the `change` step that hands
paths-filter the group's base_sha..head_sha (a PR's own diff stays on the API path); the
PR-metadata gates, not applicable on a merge group while every other lane resolves as before; every
pull-request read in pr.yml and the lanes it calls, guarded to pull_request or given a merge_group
fallback; the migrations lane's base; and the `workflow_run` consumers of `pr`, which ignore a
queue run."""

from __future__ import annotations

import functools
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
PATHS_FILTER = "dorny/paths-filter@ceb8a2b8f2d89434be7ff52d3de7ec3738c5cc9d"  # v4.0.3
BASE, HEAD = "1" * 40, "2" * 40
#: The gates that read PR metadata (the title, the body, the PR's own commits).
PR_ONLY = {"commitlint", "changelog-fragment"}
#: Pull-request context, empty or null on a merge group.
PR_READ = re.compile(
    r"github\.event\.pull_request\b|github\.event\.number\b|github\.(?:head|base)_ref\b"
    r"|\bGITHUB_(?:HEAD|BASE)_REF\b"
)
PR_GUARDS = ("github.event_name == 'pull_request'", "needs.changed-paths.outputs.pr == 'true'")
EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
#: Reads that are false on a merge group by construction (no labels, no head branch), so the job
#: or step they start is skipped in the queue, as on an unlabelled PR from a non-release branch.
FALSE_ON_A_MERGE_GROUP = {
    # The opt-in audit query-plan spike (`run-audit-spike` label); not a lane of its own.
    "_job-integration.yml:audit-query-plan",
    # The freeze proposal artifact for a dependency PR's reviewer; the freeze check still runs.
    "_job-security.yml:read-only-scans:"
    "Upload freeze-manifest proposal for the reviewer (Dependabot / dependencies PRs)",
    # release/* heads only. A merge group names no PR head; the nightly matrix covers `main`
    # (07-release-and-prr.md section 4.1; test_e2e_nightly.py pins the expression).
    "_job-e2e.yml:e2e-electron",
}
LANE = r'^\s*"?([\w-]+)"?:\s*\{\s*applicable:\s*(.+?),\s*result:\s*process\.env\.(RESULT_\w+)'
SKIP = "CI-GATE-002: gate misconfiguration: %s applicable but skipped"
FAIL = "CI-GATE-001: %s required and not successful (result: %s)"


@functools.cache
def _load(name: str) -> dict[Any, Any]:
    """A workflow's YAML; its keys are strings except `on`, which YAML 1.1 reads as True."""
    doc: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return doc


PR = _load("pr.yml")
JOBS: dict[str, Any] = PR["jobs"]
(RESOLVER,) = [s for s in JOBS["ci-required"]["steps"] if s.get("name", "").startswith("Resolve")]
#: Resolver lane -> the expression its RESULT_* variable reads, e.g. `needs.gates.outputs.gen`.
RESULTS = {
    m[1]: RESOLVER["env"][m[3]].removeprefix("${{ ").removesuffix(" }}")
    for m in re.finditer(LANE, RESOLVER["run"], re.MULTILINE | re.DOTALL)
}


def _called(name: str) -> list[str]:
    """`name` and every reusable workflow it calls, depth first."""
    files = [name]
    for job in _load(name)["jobs"].values():
        if str(job.get("uses", "")).startswith("./.github/workflows/"):
            files += _called(job["uses"].removeprefix("./.github/workflows/"))
    return files


def _needs(*tools: str) -> None:
    """Skip locally without `tools`; CI must run these proofs."""
    if not all(shutil.which(tool) for tool in tools):
        (pytest.fail if os.environ.get("CI") else pytest.skip)(f"{' and '.join(tools)} run this")


def _render(template: object, context: dict[str, str]) -> str:
    """`template` with each `${{ a || b }}` (first non-empty) or `${{ a == 'b' }}` evaluated."""

    def evaluate(match: re.Match[str]) -> str:
        expression = match[1].strip()
        equal = re.fullmatch(r"([\w.]+) == '([^']*)'", expression)
        if equal:
            return "true" if context.get(equal[1], "") == equal[2] else "false"
        terms = [term.strip() for term in expression.split("||")]
        assert all(re.fullmatch(r"[\w.]+", term) for term in terms), expression
        return next((context[term] for term in terms if context.get(term)), "")

    return EXPRESSION.sub(evaluate, str(template))


def _queue(pr: int) -> dict[str, str]:
    """A merge group's context: no head_ref; the group's own ref (the PR and its base SHA)."""
    ref = f"refs/heads/gh-readonly-queue/main/pr-{pr}-{BASE}"
    return {"github.event_name": "merge_group", "github.event.merge_group.head_ref": ref}


PULL = {"github.event_name": "pull_request", "github.head_ref": "chore/e03-x"}


def test_pr_yml_runs_on_pull_requests_and_on_main_merge_groups_only() -> None:
    # No workflow_dispatch: a dispatch names its own tree, so it could post a green `ci-required`
    # on a commit whose lanes never ran. No push, no pull_request_target (CI-GATE-003).
    assert PR[True] == {
        "pull_request": {
            "types": ["opened", "synchronize", "reopened", "ready_for_review"],
            "branches": ["main"],
        },
        "merge_group": {"types": ["checks_requested"], "branches": ["main"]},
    }


def test_concurrency_cancels_superseded_pr_runs_and_never_a_queue_run() -> None:
    group, cancel = PR["concurrency"]["group"], PR["concurrency"]["cancel-in-progress"]
    # A PR keeps one group per branch, and a push still cancels the branch's last run.
    assert (_render(group, PULL), _render(cancel, PULL)) == ("pr-chore/e03-x", "true")
    # Each merge group runs in its own group (an empty head_ref would put every queue run in `pr-`)
    # and is never cancelled: the queue would read the cancelled check as a failure.
    groups = [_render(group, _queue(pr)) for pr in (7, 8)]
    assert len(set(groups)) == 2 and not {"pr-", "pr-chore/e03-x"} & set(groups)
    assert {_render(cancel, _queue(pr)) for pr in (7, 8)} == {"false"}


def _change_step() -> dict[str, Any]:
    steps = [step for step in JOBS["changed-paths"]["steps"] if step.get("id") == "change"]
    assert len(steps) == 1, "changed-paths has one `change` step"
    return steps[0]


@pytest.mark.parametrize(
    ("event", "base", "head", "expected"),
    [
        ("pull_request", "", "", {"pr": "true"}),
        ("merge_group", BASE, HEAD, {"pr": "false", "base": BASE, "head": HEAD}),
        ("merge_group", "", HEAD, None),  # never diff against a default
        ("merge_group", "main", HEAD, None),  # a ref, not the parent commit
        ("push", "", "", None),
        ("workflow_dispatch", BASE, HEAD, None),
    ],
    ids=["pull-request", "merge-group", "no-base", "base-not-a-sha", "push", "dispatch"],
)
def test_change_step_maps_the_event_to_the_change_under_test(
    event: str, base: str, head: str, expected: dict[str, str] | None, tmp_path: Path
) -> None:
    step = _change_step()
    assert step["env"] == {
        "EVENT": "${{ github.event_name }}",
        "GROUP_BASE": "${{ github.event.merge_group.base_sha }}",
        "GROUP_HEAD": "${{ github.event.merge_group.head_sha }}",
    }
    _needs("bash")
    output = tmp_path / "github-output"
    output.write_text("", encoding="utf-8")
    env = {"PATH": os.environ.get("PATH", ""), "GITHUB_OUTPUT": str(output)}
    env |= {"EVENT": event, "GROUP_BASE": base, "GROUP_HEAD": head}
    run = ["bash", "-c", step["run"]]
    proc = subprocess.run(run, env=env, capture_output=True, text=True, timeout=30)
    written = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    if expected is None:
        assert (proc.returncode, written, "::error::" in proc.stdout) == (1, {}, True)
    else:
        assert (proc.returncode, written) == (0, expected)


def test_paths_filter_diffs_a_merge_group_from_base_sha_to_head_sha() -> None:
    job = JOBS["changed-paths"]
    ids = [step.get("id") for step in job["steps"]]
    assert ids.index("change") < ids.index("filter")
    # The pinned paths-filter lists a PR's files through the API while `base` and `ref` are empty,
    # as the change step leaves them on a PR. On a merge group they win over its defaults: it
    # fetches the base commit (depth 1) and diffs the two trees, so the shallow checkout will do.
    step = job["steps"][ids.index("filter")]
    assert step["uses"] == PATHS_FILTER
    assert {key: step["with"][key] for key in ("base", "ref")} == {
        "base": "${{ steps.change.outputs.base }}",
        "ref": "${{ steps.change.outputs.head }}",
    }
    assert job["outputs"]["pr"] == "${{ steps.change.outputs.pr }}"


def test_pr_metadata_gates_run_on_pull_requests_only() -> None:
    # The PR's run checked its title, body and commits; a queue's squash commit is not its commits.
    steps = {step.get("id"): step for step in JOBS["gates"]["steps"]}
    pr_only = "${{ !cancelled() && needs.changed-paths.outputs.pr == 'true' }}"
    assert {gate: steps[gate]["if"] for gate in PR_ONLY} == dict.fromkeys(PR_ONLY, pr_only)


def _resolve(context: dict[str, str]) -> tuple[int, set[str]]:
    """The resolver step under the env GitHub builds: every job and gate green and every
    changed-paths output true, then `context`; an unresolved expression is ''."""
    _needs("bash", "node")
    values = {f"needs.{job}.result": "success" for job in JOBS}
    values |= {f"needs.gates.outputs.{gate}": "success" for gate in JOBS["gates"]["outputs"]}
    values |= {f"needs.changed-paths.outputs.{o}": "true" for o in JOBS["changed-paths"]["outputs"]}
    values |= context
    env = {"PATH": os.environ.get("PATH", "")}
    for name, expression in RESOLVER["env"].items():
        path = re.fullmatch(r"\$\{\{ ([\w.-]+) \}\}", expression)
        assert path, expression
        env[name] = values.get(path[1], "")
    run = ["bash", "-c", RESOLVER["run"]]
    proc = subprocess.run(run, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    return proc.returncode, {line for line in proc.stderr.splitlines() if line.startswith("CI-")}


#: A merge group's run: `pr` is false, so the PR-metadata gate steps were skipped.
QUEUED = {"needs.changed-paths.outputs.pr": "false"}
QUEUED |= {f"needs.gates.outputs.{gate}": "skipped" for gate in PR_ONLY}


def test_resolver_passes_a_green_merge_group_run() -> None:
    assert _resolve(QUEUED) == (0, set())


@pytest.mark.parametrize("lane", sorted(RESULTS))
def test_resolver_skips_only_the_pr_metadata_gates_on_a_merge_group(lane: str) -> None:
    # Every filter true and one lane skipped: only a PR-metadata gate may be, and every other lane
    # stays applicable, as on a PR (CI-GATE-002).
    expected = (0, set()) if lane in PR_ONLY else (1, {SKIP % lane})
    assert _resolve(QUEUED | {RESULTS[lane]: "skipped"}) == expected


@pytest.mark.parametrize("gate", sorted(PR_ONLY))
def test_resolver_still_requires_the_pr_metadata_gates_on_a_pull_request(gate: str) -> None:
    assert _resolve({f"needs.gates.outputs.{gate}": "skipped"}) == (1, {SKIP % gate})
    assert _resolve({f"needs.gates.outputs.{gate}": "failure"}) == (1, {FAIL % (gate, "failure")})


def test_resolver_fails_a_merge_group_run_whose_tree_gate_failed() -> None:
    red = QUEUED | {"needs.gates.outputs.gen": "failure", "needs.gates.result": "failure"}
    assert _resolve(red) == (1, {FAIL % ("gen", "failure"), FAIL % ("gates", "failure")})


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


def _unguarded_reads() -> set[str]:
    """Where pr.yml or a lane it calls reads pull-request context with neither a pull_request
    guard on the step or job nor a merge_group fallback in the same expression. Text outside
    `${{ }}` (a shell read such as $GITHUB_BASE_REF) counts as one expression."""
    found: set[str] = set()

    def scan(where: str, node: object, guarded: bool) -> None:
        for text in _strings(node):
            for part in [*EXPRESSION.findall(text), EXPRESSION.sub("", text)]:
                if PR_READ.search(part) and not guarded and "github.event.merge_group." not in part:
                    found.add(where)

    def guard(condition: object) -> bool:
        return any(text in str(condition or "") for text in PR_GUARDS)

    for name in dict.fromkeys(_called("pr.yml")):
        doc = _load(name)
        scan(name, {key: value for key, value in doc.items() if key not in ("jobs", True)}, False)
        for job_id, job in doc["jobs"].items():
            job_guard = guard(job.get("if"))
            scan(f"{name}:{job_id}", {k: v for k, v in job.items() if k != "steps"}, job_guard)
            for step in job.get("steps") or []:
                where = f"{name}:{job_id}:{step.get('id') or step.get('name')}"
                scan(where, step, job_guard or guard(step.get("if")))
    return found


def test_every_pull_request_read_is_guarded_or_has_a_merge_group_fallback() -> None:
    # On a merge group these reads are empty: unguarded, one fails, hangs or skips a check that
    # matters for the queued tree. Guard it to pull_request, give it a merge_group fallback in the
    # same expression, or, if it is false on a merge group by construction, add it to
    # FALSE_ON_A_MERGE_GROUP with the reason.
    assert _unguarded_reads() == FALSE_ON_A_MERGE_GROUP


@pytest.mark.parametrize("base_ref", ["main", "refs/heads/main"], ids=["pr", "merge-group"])
def test_migration_lockfile_check_compares_both_events_with_origin_main(
    base_ref: str, tmp_path: Path
) -> None:
    steps = _load("_job-migrations.yml")["jobs"]["migrations"]["steps"]
    (step,) = [s for s in steps if "verify_migration_lockfile.py" in str(s.get("run"))]
    # A merge group has no base_ref; its target branch is merge_group.base_ref, a full ref.
    fallback = "${{ github.base_ref || github.event.merge_group.base_ref }}"
    assert step["env"] == {"BASE_REF": fallback}
    _needs("bash")
    uv = tmp_path / "uv"  # prints its arguments, one per line
    uv.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n', encoding="utf-8")
    uv.chmod(0o755)
    env = {"PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}", "BASE_REF": base_ref}
    proc = subprocess.run(["bash", "-c", step["run"]], env=env, capture_output=True, text=True)
    args = proc.stdout.splitlines()
    assert (proc.returncode, args[args.index("--base-ref") + 1]) == (0, "origin/main")


def test_workflow_run_consumers_of_pr_ignore_merge_group_runs() -> None:
    # A queue run's tree may never land (the queue can still drop its PR), so nothing that follows
    # `pr` may write on one: a baseline, a comment, a branch.
    event = re.compile(r"github\.event\.workflow_run\.event (?:!= 'merge_group'|== '\w+')")
    consumers = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        on = _load(path.name).get(True)
        if isinstance(on, dict) and "pr" in (on.get("workflow_run") or {}).get("workflows", []):
            consumers.append(path.name)
            for job_id, job in _load(path.name)["jobs"].items():
                condition = str(job.get("if", ""))
                assert event.search(condition) and "== 'merge_group'" not in condition, job_id
    assert "coverage-ratchet.yml" in consumers
