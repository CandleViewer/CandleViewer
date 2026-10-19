"""#3383: C-9.2 asks for a nightly full Playwright matrix, but no scheduled workflow called
`_job-e2e.yml`: only `a11y-nightly.yml` ran Playwright, with the a11y config. So a change that
`pr.yml`'s `e2e` filter leaves out on purpose, such as a root dependency manifest
(docs/ci-runbook.md section 2), got no e2e signal until a later PR started the lane.

`e2e-nightly.yml` calls `_job-e2e.yml` on `main` every night and runs all of it: the four
`e2e-web` shards, `e2e-staging`, `a11y-axe` and `e2e-electron`. `e2e-electron` runs when its caller
sets `_job-e2e.yml`'s `electron` input, as the nightly does (the suite is green since #3393), or on
a `release/*` head: `pr.yml` keeps the default. A red scheduled run opens an issue from a job that
holds `issues: write` and nothing else, and runs no checkout and no action. A red nightly blocks the
next release (C-9.2) through the release checklist: 07 section 4.1 and the issue form `release.yml`
opens for each cut both ask for a green run on the `main` tip being cut.

#3449, from the #3383 reviews: the nightly has no concurrency group, as most nightlies do, so no
run waits in a pending slot that a later one can take (two manual runs used to drop the
scheduled run and that night's report). A red night comments on the one tracker issue that the
repository variable `CV_E2E_NIGHTLY_TRACKER_ISSUE` names, as `xstate-nightly.yml` does, and opens a
P1 while it is unset; a value that is not an issue number files nothing and fails the job. The e2e
and a11y lanes' checkouts keep no git credential (ADR-0013 rule 6) while `pnpm install` runs
dependency lifecycle scripts, and no step fetches: the a11y lane checks out the PR base's baseline
file instead, so it works whether the repository is public or private."""

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
#: #3449: the repository variable that names the one issue a red night comments on.
TRACKER_VAR = "CV_E2E_NIGHTLY_TRACKER_ISSUE"
#: A stand-in `gh` that logs its arguments, one JSON list per call.
FAKE_GH = """import json, os, sys
with open(os.environ["GH_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
"""
#: A stand-in `python` for the a11y baseline step: logs its arguments and the base file's text.
FAKE_PYTHON = """import json, os, sys
with open(sys.argv[4], encoding="utf-8") as base:
    text = base.read()
with open(os.environ["PY_LOG"], "w", encoding="utf-8") as log:
    json.dump([sys.argv[1:], text], log)
"""
#: A stand-in `git` that fails, so a step that runs git at all fails under `bash -e`.
FAKE_GIT = "import sys\nsys.exit(97)\n"
A11Y_LANE = "_job-a11y.yml"
#: A command that reaches the repository's remote, or GitHub, from a lane's step. git's global
#: options (`-C dir`, `-c key=value`, `--no-pager`) may come before the subcommand. `-c` and `-C`
#: take the next word, as git reads them, or an attached `=value` (git rejects that form, so
#: matching it only makes the check stricter). No other option word can be read as either: each
#: word has one parse, so a match cannot backtrack exponentially (CodeQL py/redos).
REMOTE = re.compile(
    r"\bgit(?:\s+(?:-[cC](?:\s+|=)\S+|-(?:[^\WcC]|-|[cC][\w-])[\w-]*(?:=\S+)?))*\s+"
    r"(?:fetch|pull|push|clone|ls-remote|submodule)\b|\bgh\s"
)
#: The a11y step that compares the PR's baseline file with its base's copy.
BASELINE = "Baseline changes must cite finding id in PR description"
#: The checkout just before it, of that copy: PR-only, sparse, and keeping no credential (#3449).
BASE_CHECKOUT_STEP = "Check out the PR base's accessibility baseline"
BASE_PATH = ".a11y-base"
BASE_CHECKOUT = {
    "ref": "${{ github.event.pull_request.base.sha }}",
    "path": BASE_PATH,
    "sparse-checkout": "tools/a11y",
    "persist-credentials": False,
}
PR_EVENT_IF = "github.event_name == 'pull_request'"


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


def test_no_concurrency_group_can_drop_a_scheduled_run() -> None:
    # #3449: `group: e2e-nightly` was shared with manual runs on any ref, and a newer pending run
    # replaces an older one, so two dispatches near 02:53 UTC could drop the scheduled run and
    # that night's report. As in most nightlies, neither the nightly nor its lane has a group.
    for name in (NIGHTLY, LANE_FILE):
        doc = _load(name)
        assert "concurrency" not in doc
        assert [job for job, body in doc["jobs"].items() if "concurrency" in body] == []


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


def test_e2e_nightly_report_runs_only_the_gh_cli_for_a_red_scheduled_run() -> None:
    report = _load(NIGHTLY)["jobs"]["report"]
    assert (report["needs"], report["if"]) == ("e2e", REPORT_IF)
    (step,) = report["steps"]
    # No checkout and no action share the job with the write token: only the runner's gh CLI.
    assert set(step) == {"name", "env", "run"}
    assert step["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "GH_REPO": "${{ github.repository }}",
        "RESULT": "${{ needs.e2e.result }}",
        # #3449: named, never searched for; no default, so an unset variable keeps the P1.
        "TRACKER_ISSUE": "${{ vars.CV_E2E_NIGHTLY_TRACKER_ISSUE }}",
    }
    # Values reach the script through env, never as expressions expanded into it.
    assert "${{" not in step["run"]
    assert "gh issue create" in step["run"] and "/actions/runs/$GITHUB_RUN_ID" in step["run"]
    assert 'gh issue comment "$TRACKER_ISSUE"' in step["run"]


def _bash(tmp_path: Path, run: str, env: dict[str, str], fakes: dict[str, str]) -> tuple[int, str]:
    """Run a step's script as the runner does (`bash -e`) in tmp_path, with stand-in commands
    first on PATH and HOME in tmp_path (no stored gh auth, no network): exit code and output."""
    if not shutil.which("bash"):  # CI must run these fail-closed proofs
        (pytest.fail if os.environ.get("CI") else pytest.skip)("bash runs the step")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, source in fakes.items():
        (bin_dir / name).write_text(f"#!{sys.executable}\n{source}", encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    base = {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}", "HOME": str(tmp_path)}
    proc = subprocess.run(
        ["bash", "-e", "-c", run],
        cwd=tmp_path,
        env=base | env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _report(tmp_path: Path, tracker: str) -> tuple[int, str, list[list[str]]]:
    """Run the report step's script with the variable's value in TRACKER_ISSUE (empty when it is
    unset) and a fake `gh`: the exit code, output and gh calls."""
    log = tmp_path / "gh.log"
    env = {"GH_LOG": str(log), "TRACKER_ISSUE": tracker, "RESULT": "failure"}
    env |= {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "owner/repo"}
    env |= {"GITHUB_RUN_ID": "7", "GITHUB_SHA": "0" * 40}
    (step,) = _load(NIGHTLY)["jobs"]["report"]["steps"]
    rc, out = _bash(tmp_path, step["run"], env, {"gh": FAKE_GH})
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return rc, out, [json.loads(line) for line in lines]


def test_e2e_nightly_report_opens_a_p1_while_no_tracker_issue_is_named(tmp_path: Path) -> None:
    # An unset repository variable reaches the step as an empty string: the #3383 behaviour.
    rc, out, calls = _report(tmp_path, "")
    assert rc == 0, out
    (call,) = calls
    assert call[:3] == ["issue", "create", "--title"]
    assert re.fullmatch(r"e2e: nightly Playwright matrix failed \(\d{4}-\d{2}-\d{2}\)", call[3])
    labels = ["--label", "qa", "--label", "area/frontend-platform", "--label", "priority/p1"]
    assert call[4:-2] == labels
    assert call[-2] == "--body" and "/owner/repo/actions/runs/7" in call[-1]


def test_e2e_nightly_report_comments_on_the_named_tracker_issue(tmp_path: Path) -> None:
    # #3449: one tracker issue instead of a new P1 every red night, as xstate-nightly.yml does.
    rc, out, calls = _report(tmp_path, "3449")
    assert rc == 0, out
    (call,) = calls
    assert call[:4] == ["issue", "comment", "3449", "--body"] and len(call) == 5
    assert "/owner/repo/actions/runs/7" in call[4] and "(C-9.2)" in call[4]


@pytest.mark.parametrize(
    "value",
    ["0", "012", "-3", "12a", "#12", " 12", "12 ", "1.5", "owner/repo#12", "7\n::warning::cv-mark"],
)
def test_e2e_nightly_report_fails_closed_when_the_tracker_is_not_an_issue_number(
    tmp_path: Path, value: str
) -> None:
    # A set value that is not a positive integer is a misconfiguration: nothing is filed (no P1,
    # no comment, nowhere outside this repository) and the job turns red, naming the variable.
    rc, out, calls = _report(tmp_path, value)
    assert (rc, calls) == (1, [])
    assert f"::error title=e2e-nightly-report::{TRACKER_VAR} " in out
    # Never echoed, so a stored value cannot add a workflow command (the last case) to the log.
    assert value.strip() not in out and "cv-mark" not in out


def test_e2e_and_a11y_lanes_keep_no_git_credential_after_checkout() -> None:
    # #3449 (ADR-0013 rule 6): `pnpm install` runs dependency lifecycle scripts, so no checkout in
    # these lanes leaves its token in the git config, as in pr.yml and xstate-nightly.yml.
    checkouts: list[tuple[str, str, Any]] = []
    remote: list[str] = []
    for name in (LANE_FILE, A11Y_LANE):
        for job_name, job in _load(name)["jobs"].items():
            for step in job["steps"]:
                if str(step.get("uses", "")).startswith("actions/checkout@"):
                    checkouts.append((name, job_name, step.get("with")))
                if REMOTE.search(step.get("run", "")):
                    remote.append(step["name"])
    lanes = [(LANE_FILE, job) for job in EVERY_CALL | {"e2e-electron"}]
    lanes += [(A11Y_LANE, "a11y")] * 2  # its own tree, then the PR base's baseline file
    assert sorted((name, job) for name, job, _ in checkouts) == sorted(lanes)
    kept = [c for c in checkouts if c[2] not in ({"persist-credentials": False}, BASE_CHECKOUT)]
    assert kept == []
    # No later step needs a credential: none fetches, pushes or calls GitHub, so neither a token
    # nor the repository's visibility matters to them.
    assert remote == []


@pytest.mark.parametrize(
    ("run", "remote"),
    [
        ("git fetch origin main", True),
        ('git -C . fetch --no-tags origin "$BASE_SHA" || true', True),
        ("git --no-pager -c core.quotepath=off pull", True),
        ("base=$(git --git-dir=.git ls-remote origin HEAD)", True),
        ("git -C -- -C -- submodule update", True),
        ("git -c=core.x=y push origin HEAD", True),
        ("gh api repos/owner/repo", True),
        ("git -C fetch", False),
        ("git -C . diff --exit-code", False),
        ("echo ${{ github.sha }} > git-fetch.txt", False),
    ],
)
def test_remote_finds_a_remote_git_subcommand_after_global_options_or_gh(
    run: str, remote: bool
) -> None:
    # #3449: what REMOTE finds, now that each word has one parse. `-c` and `-C` take the next
    # word, as git reads them, so in `git -C fetch` the word fetch is a directory, not a command.
    assert bool(REMOTE.search(run)) is remote


def test_a11y_lane_checks_out_the_pr_base_baseline_and_keeps_no_credential() -> None:
    # #3449: actions/checkout reads the base's copy with the job's token and keeps none (cone
    # mode: root files and tools/a11y/ only), so the baseline step after it needs no git fetch.
    steps = _load(A11Y_LANE)["jobs"]["a11y"]["steps"]
    names = [step.get("name") for step in steps]
    at = names.index(BASE_CHECKOUT_STEP)
    assert names[at + 1] == BASELINE
    assert str(steps[at]["uses"]).startswith("actions/checkout@")
    assert steps[at]["with"] == BASE_CHECKOUT
    assert steps[at]["if"] == steps[at + 1]["if"] == PR_EVENT_IF


@pytest.mark.parametrize("on_base", [True, False], ids=["on-base", "first-introduction"])
def test_a11y_baseline_step_compares_with_the_base_copy_and_runs_no_git(
    tmp_path: Path, on_base: bool
) -> None:
    # The step compares with the base checkout's copy, or with an empty baseline where the base has
    # none yet, then removes that checkout before `pnpm install`. The stand-in git fails if called.
    base_text = '{"entries": [{"id": "on-base"}]}\n'
    if on_base:
        copy = tmp_path / BASE_PATH / "tools" / "a11y" / "axe-baseline.json"
        copy.parent.mkdir(parents=True)
        copy.write_text(base_text, encoding="utf-8")
    temp, log = tmp_path / "runner-temp", tmp_path / "python.log"
    temp.mkdir()
    env = {"RUNNER_TEMP": str(temp), "PR_BODY": "A11Y-0001", "PY_LOG": str(log)}
    (step,) = [s for s in _load(A11Y_LANE)["jobs"]["a11y"]["steps"] if s.get("name") == BASELINE]
    rc, out = _bash(tmp_path, step["run"], env, {"python": FAKE_PYTHON, "git": FAKE_GIT})
    assert rc == 0, out
    argv, base = json.loads(log.read_text(encoding="utf-8"))
    files = [f"{temp}/base-baseline.json", "tools/a11y/axe-baseline.json", f"{temp}/pr-body.txt"]
    assert argv == ["-m", "tools.a11y.gates", "baseline-pr", *files]
    assert base == (base_text if on_base else '{"entries": []}\n')
    assert not (tmp_path / BASE_PATH).exists()


def test_release_checklist_needs_a_green_e2e_nightly_on_the_tip_it_cuts() -> None:
    # C-9.2: a red nightly blocks the next release. 07 section 4.1 lists the pre-cut items, and the
    # issue form release.yml opens copies them, so the box the release owner ticks names the run.
    pre_cut = RELEASE_DOC.read_text(encoding="utf-8").split("### 4.1 ", 1)[1].split("\n### ", 1)[0]
    items = [line for line in pre_cut.splitlines() if line.startswith("- [ ] ")]
    named = [item for item in items if f"`{NIGHTLY}`" in item]
    assert len(named) == 1 and "`e2e-electron` included" in named[0]
    form = yaml.safe_load(RELEASE_FORM.read_text(encoding="utf-8"))
    (box,) = [item for item in form["body"] if item.get("id") == "pre-cut"]
    labels: list[str] = [option["label"] for option in box["attributes"]["options"]]
    named = [label for label in labels if NIGHTLY in label]
    assert len(named) == 1 and "e2e-electron included" in named[0]


def test_e2e_nightly_adds_no_check_a_required_context_names() -> None:
    # C-9.1 is unchanged: the nightly's check runs carry names no branch-protection context uses.
    protection = json.loads((ROOT / ".github/branch-protection.json").read_text(encoding="utf-8"))
    required = {check["context"] for check in protection["required_status_checks"]["checks"]}
    required |= {name for name in protection["pending_checks"] if name[:1] != "$"}
    jobs = _load(NIGHTLY)["jobs"]
    lane = _load(LANE_FILE)["jobs"]
    checks = {f"{jobs['e2e']['name']} / {job.get('name', name)}" for name, job in lane.items()}
    checks |= {job["name"] for job in jobs.values()}
    assert len(checks) == len(lane) + 2 and not checks & required
