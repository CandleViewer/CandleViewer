"""#3433: `pr.yml` listens to `merge_group`, so `main` can move to GitHub's merge queue.

The queue builds `main` plus the PR as a merge group and waits for `ci-required` on it, the one
check protection requires. These tests pin what a merge group's run needs: the trigger; a
concurrency group per merge group that is never cancelled; the `change` step that hands
paths-filter `main` and the group's head, so a group's lanes cover the entries ahead of it too (a
PR's own diff stays on the API path); the PR-metadata gates, not applicable on a merge group only,
while every other lane resolves as before; every pull-request read in pr.yml and the lanes it
calls, guarded to pull_request or given a merge_group fallback, and every condition or value there
that reads the event; the migrations lane's base; and the `workflow_run` consumers of `pr`, and the
coverage ratchet whatever it follows, which ignore a queue run."""

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
#: Pull-request context, empty or null on a merge group, in dot or index form. A whole-event read
#: counts too (github-script's `context.payload` and `context.issue` included): a script could take
#: a PR field from it.
PR_READ = re.compile(
    r"github\.event\.(?:pull_request|number)\b|github\.(?:head|base)_ref\b"
    r"|github\.event\[\s*['\"](?:pull_request|number)['\"]|github\[\s*['\"](?:head|base)_ref"
    r"|\bGITHUB_(?:HEAD_REF|BASE_REF|EVENT_PATH)\b|toJSON\(\s*github\.event\s*\)"
    r"|\bcontext\.(?:payload|issue)\b"
)
#: The event in any form: a condition or value that reads it can skip or weaken a queue run's check.
EVENT_READ = re.compile(
    PR_READ.pattern + r"|github\.(?:event|event_name|actor|triggering_actor|ref|ref_name)\b"
    r"|\bGITHUB_(?:EVENT_NAME|REF|REF_NAME|ACTOR)\b|\boutputs\.pr\b"
)
#: A condition is false on a merge group when one of its top-level `&&` terms is one of these.
PR_GUARDS = ("github.event_name == 'pull_request'", "needs.changed-paths.outputs.pr != 'false'")
EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
FREEZE_UPLOAD = (
    "_job-security.yml:read-only-scans:"
    "Upload freeze-manifest proposal for the reviewer (Dependabot / dependencies PRs)"
)
#: Every job or step `if:` in pr.yml and the lanes it calls that reads the event, verbatim
#: (whitespace folded). A merge group can skip a check only through one of these, so a new or
#: changed one (a PR guard on a real gate, a guard inside an `||`) is reviewed here first.
EVENT_CONDITIONS = {
    **dict.fromkeys(
        ["pr.yml:gates:changelog-fragment", "pr.yml:gates:commitlint"],
        "${{ !cancelled() && needs.changed-paths.outputs.pr != 'false' }}",
    ),
    # #2892: the C-10.2 label. A merge group has no PR to label, and its PR's own run labelled it
    # before it could be enqueued; the job still runs, so its always-applicable lane passes.
    "pr.yml:security-review-label:label": "github.event_name == 'pull_request'",
    # The a11y baseline's PR citation, the PR base checkout only that step reads (#3449), and the
    # coverage comment: nothing else reads any of them.
    **dict.fromkeys(
        [
            "_job-a11y.yml:a11y:Check out the PR base's accessibility baseline",
            "_job-a11y.yml:a11y:Baseline changes must cite finding id in PR description",
        ],
        "github.event_name == 'pull_request'",
    ),
    "_job-coverage.yml:coverage-thresholds:Post PR summary comment": (
        "always() && github.event_name == 'pull_request'"
    ),
    # False on a merge group by construction (no labels, no head branch), as on an unlabelled PR
    # from a non-release branch. The opt-in audit query-plan spike, not a lane of its own:
    "_job-integration.yml:audit-query-plan": "${{ github.event_name == 'workflow_dispatch' || "
    "contains(github.event.pull_request.labels.*.name, 'run-audit-spike') }}",
    # The freeze proposal artifact for a dependency PR's reviewer; the freeze check still runs:
    FREEZE_UPLOAD: "${{ !cancelled() && steps.freeze.outcome == 'failure' && (github.actor == "
    "'dependabot[bot]' || contains(github.event.pull_request.labels.*.name, 'dependencies')) }}",
    # release/* heads only; the nightly matrix covers `main` (07-release-and-prr.md section 4.1;
    # test_e2e_nightly.py pins the expression):
    "_job-e2e.yml:e2e-electron": (
        "${{ inputs.electron || startsWith(github.head_ref, 'release/') }}"
    ),
}
#: The unguarded pull-request reads: the three conditions above that are false on a merge group,
#: each allowed as exactly that read, not as a place where any read may go.
FALSE_ON_A_MERGE_GROUP = {
    (where, EVENT_CONDITIONS[where].removeprefix("${{ ").removesuffix(" }}"))
    for where in (
        "_job-integration.yml:audit-query-plan",
        FREEZE_UPLOAD,
        "_job-e2e.yml:e2e-electron",
    )
}
#: Every other value that reads the event where a merge group runs it (any key, `run:` text too),
#: by job: a value can weaken a check there as a condition can (a `continue-on-error`, a lane's
#: input, a shell test of the event), so a new or changed one is reviewed here first.
EVENT_VALUES = [
    ("pr.yml", "github.event.merge_group.head_sha || github.head_ref"),
    ("pr.yml", "github.event_name == 'pull_request'"),
    ("pr.yml:changed-paths", "steps.change.outputs.pr"),
    ("pr.yml:changed-paths", "github.event_name"),
    ("pr.yml:changed-paths", "github.event.merge_group.base_ref"),
    ("pr.yml:changed-paths", "github.event.merge_group.head_sha"),
    ("pr.yml:gates", "github.event.pull_request.base.sha || github.event.merge_group.base_sha"),
    ("pr.yml:gates", "github.event.pull_request.head.sha || github.event.merge_group.head_sha"),
    ("pr.yml:ci-required", "needs.changed-paths.outputs.pr"),
    ("_job-migrations.yml:migrations", "github.base_ref || github.event.merge_group.base_ref"),
]
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


def _queue(pr: int, head: str) -> dict[str, str]:
    """A merge group's context: no head_ref; its ref (the PR and its base SHA) and its head."""
    group = "github.event.merge_group"
    ref = f"refs/heads/gh-readonly-queue/main/pr-{pr}-{BASE}"
    return {"github.event_name": "merge_group", f"{group}.head_ref": ref, f"{group}.head_sha": head}


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
    # Each merge group build runs in its own group (an empty head_ref would put every queue run in
    # `pr-`), even a PR enqueued again on the same base, whose queue ref is the same, and is never
    # cancelled: the queue would read the cancelled check as a failure.
    builds = [_queue(7, "3" * 40), _queue(7, "4" * 40), _queue(8, "5" * 40)]
    groups = {_render(group, build) for build in builds}
    assert len(groups) == 3 and not {"pr-", "pr-chore/e03-x"} & groups
    assert {_render(cancel, build) for build in builds} == {"false"}


def _change_step() -> dict[str, Any]:
    steps = [step for step in JOBS["changed-paths"]["steps"] if step.get("id") == "change"]
    assert len(steps) == 1, "changed-paths has one `change` step"
    return steps[0]


MAIN = "refs/heads/main"


@pytest.mark.parametrize(
    ("event", "base_ref", "head", "expected"),
    [
        ("pull_request", "", "", {"pr": "true"}),
        ("merge_group", MAIN, HEAD, {"pr": "false", "base": "main", "head": HEAD}),
        ("merge_group", "", HEAD, None),  # never diff against a default
        ("merge_group", "refs/heads/release/v1", HEAD, None),  # the queue is main's only
        ("merge_group", MAIN, "main", None),  # a ref, not the group's head commit
        ("push", "", "", None),
        ("workflow_dispatch", MAIN, HEAD, None),
    ],
    ids=["pull-request", "merge-group", "no-base", "not-main", "bad-head", "push", "dispatch"],
)
def test_change_step_maps_the_event_to_the_change_under_test(
    event: str, base_ref: str, head: str, expected: dict[str, str] | None, tmp_path: Path
) -> None:
    step = _change_step()
    # Never the group's base_sha: that is the entry ahead, so the diff would miss its change.
    assert step["env"] == {
        "EVENT": "${{ github.event_name }}",
        "GROUP_BASE_REF": "${{ github.event.merge_group.base_ref }}",
        "GROUP_HEAD": "${{ github.event.merge_group.head_sha }}",
    }
    _needs("bash")
    output = tmp_path / "github-output"
    output.write_text("", encoding="utf-8")
    env = {"PATH": os.environ.get("PATH", ""), "GITHUB_OUTPUT": str(output)}
    env |= {"EVENT": event, "GROUP_BASE_REF": base_ref, "GROUP_HEAD": head}
    run = ["bash", "-c", step["run"]]
    proc = subprocess.run(run, env=env, capture_output=True, text=True, timeout=30)
    written = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    if expected is None:
        assert (proc.returncode, written, "::error::" in proc.stdout) == (1, {}, True)
    else:
        assert (proc.returncode, written) == (0, expected)


def test_paths_filter_diffs_a_merge_group_against_main_from_their_merge_base() -> None:
    job = JOBS["changed-paths"]
    ids = [step.get("id") for step in job["steps"]]
    assert ids.index("change") < ids.index("filter")
    # The pinned paths-filter lists a PR's files through the API while `base` and `ref` are empty,
    # as the change step leaves them on a PR. On a merge group they win over its defaults (the
    # group's base_sha and head_sha), and a branch base takes its merge-base path: it fetches
    # `main` and the head itself and diffs `main...head`, every entry ahead in the queue included.
    # With grouping HEADGREEN (.github/branch-protection.json) the queue merges a failed entry with
    # a later one that passed, so the later run must have chosen its lanes for both changes.
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
    # `!= 'false'` fails closed: if changed-paths lost the output, they run.
    pr_only = "${{ !cancelled() && needs.changed-paths.outputs.pr != 'false' }}"
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
    # Fail closed: only `pr` false (a merge group) makes them not applicable, never a lost output.
    lost = {"needs.changed-paths.outputs.pr": "", f"needs.gates.outputs.{gate}": "skipped"}
    assert _resolve(lost) == (1, {SKIP % gate})


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


def _guards(condition: object) -> bool:
    """Whether a job or step `if:` is false on a merge group: a PR guard is one of its top-level
    `&&` terms. A top-level `||`, or a `!` or parentheses around the guard, does not count."""
    text = str(condition or "").strip()
    wrapped = re.fullmatch(r"\$\{\{(.*)\}\}", text, re.DOTALL)
    text = wrapped[1] if wrapped else text
    while (folded := re.sub(r"\([^()]*\)", "_", text)) != text:  # each parenthesised group
        text = folded
    terms = {" ".join(term.split()) for term in text.split("&&")}
    return "||" not in text and bool(terms & set(PR_GUARDS))


def _has_fallback(read: str) -> bool:
    """`a || b` of two context paths, one of them under `github.event.merge_group`."""
    terms = [term.strip() for term in read.split("||")]
    group = [term.startswith("github.event.merge_group.") for term in terms]
    return len(terms) == 2 and all(re.fullmatch(r"[\w.]+", term) for term in terms) and any(group)


def _places(name: str) -> Iterator[tuple[str, dict[str, Any], dict[str, Any]]]:
    """(place, node, its job) for each job and step of workflow `name`."""
    for job_id, job in _load(name)["jobs"].items():
        yield f"{name}:{job_id}", job, job
        for step in job.get("steps") or []:
            yield f"{name}:{job_id}:{step.get('id') or step.get('name')}", step, job


def _owned(name: str) -> Iterator[tuple[str, dict[str, Any], bool]]:
    """(place, its own keys, whether a PR guard keeps it off a merge group) for workflow `name`
    (minus `on` and `jobs`) and each of its jobs and steps (minus a job's `steps`)."""
    top = {key: value for key, value in _load(name).items() if key not in ("jobs", True)}
    yield name, top, False
    for where, node, job in _places(name):
        own = {key: value for key, value in node.items() if key != "steps"}
        yield where, own, _guards(job.get("if")) or _guards(node.get("if"))


def _parts(node: object) -> Iterator[str]:
    """Each `${{ }}` expression in `node`'s strings, and each line of text outside one (a shell
    read, a bare `if:`), whitespace folded."""
    for text in _strings(node):
        for part in [*EXPRESSION.findall(text), *EXPRESSION.sub("", text).splitlines()]:
            yield " ".join(part.split())


def _unguarded_reads() -> set[tuple[str, str]]:
    """(place, read) for each pull-request read in pr.yml or a lane it calls with neither a PR
    guard on its step or job nor a merge_group fallback in the same `a || b`."""
    return {
        (where, part)
        for name in dict.fromkeys(_called("pr.yml"))
        for where, own, guarded in _owned(name)
        for part in _parts(own)
        if PR_READ.search(part) and not guarded and not _has_fallback(part)
    }


@pytest.mark.parametrize(
    ("condition", "guarded"),
    [
        ("github.event_name == 'pull_request'", True),
        ("${{ !cancelled() && needs.changed-paths.outputs.pr != 'false' }}", True),
        ("${{ github.event_name == 'pull_request' || github.event_name == 'merge_group' }}", False),
        ("${{ !(github.event_name == 'pull_request') }}", False),
        ("${{ needs.changed-paths.outputs.pr == 'true' }}", False),  # an empty output runs it
        (None, False),
    ],
)
def test_a_pr_guard_counts_only_as_a_top_level_and_term(condition: str, guarded: bool) -> None:
    assert _guards(condition) is guarded


@pytest.mark.parametrize(
    "read",
    [
        "github.event['pull_request'].head.sha",
        'github["base_ref"]',
        "$GITHUB_EVENT_PATH",
        "issue_number: context.issue.number,",  # github-script
        "const { pull_request: pr } = context.payload;",
    ],
)
def test_the_scan_finds_pull_request_context_in_any_form(read: str) -> None:
    assert PR_READ.search(read)


def test_every_pull_request_read_is_guarded_or_has_a_merge_group_fallback() -> None:
    # On a merge group these reads are empty: unguarded, one fails, hangs or skips a check that
    # matters for the queued tree. Guard it to pull_request, give it a merge_group fallback in the
    # same `a || b`, or, if it is false on a merge group by construction, review the exact read
    # into EVENT_CONDITIONS and FALSE_ON_A_MERGE_GROUP with the reason.
    assert _unguarded_reads() == FALSE_ON_A_MERGE_GROUP


def test_every_condition_and_value_that_reads_the_event_is_reviewed() -> None:
    conditions, values = {}, []
    for name in dict.fromkeys(_called("pr.yml")):
        for where, own, guarded in _owned(name):
            condition = " ".join(str(own.get("if", "")).split())
            if EVENT_READ.search(condition):
                conditions[where] = condition
            if not guarded:  # a guarded job or step never runs on a merge group
                job = ":".join(where.split(":")[:2])
                rest = {key: value for key, value in own.items() if key != "if"}
                values += [(job, part) for part in _parts(rest) if EVENT_READ.search(part)]
    assert conditions == EVENT_CONDITIONS
    assert sorted(values) == sorted(EVENT_VALUES)


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
    run = ["bash", "-c", step["run"]]
    proc = subprocess.run(run, env=env, capture_output=True, text=True, timeout=30)
    args = proc.stdout.splitlines()
    assert (proc.returncode, args[args.index("--base-ref") + 1]) == (0, "origin/main")


def test_workflow_run_consumers_of_pr_ignore_merge_group_runs() -> None:
    # A queue run's tree may never land (the queue can still drop its PR), so nothing that follows
    # `pr` may write on one: a baseline, a comment, a branch.
    event = re.compile(r"github\.event\.workflow_run\.event (?:!= 'merge_group'|== '\w+')")
    for path in sorted(WORKFLOWS.glob("*.yml")):
        on = _load(path.name).get(True)
        if isinstance(on, dict) and "pr" in (on.get("workflow_run") or {}).get("workflows", []):
            for job_id, job in _load(path.name)["jobs"].items():
                condition = str(job.get("if", ""))
                assert event.search(condition) and "== 'merge_group'" not in condition, job_id
    # The coverage ratchet, the one consumer until #3508 took it off `pr` (it waits for a push run
    # of `main` that uploads coverage), keeps a gate that ignores a queue run whatever it follows.
    for job_id, job in _load("coverage-ratchet.yml")["jobs"].items():
        condition = str(job.get("if", ""))
        assert event.search(condition) and "== 'merge_group'" not in condition, job_id
