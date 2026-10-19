"""#3751: one runner per PR event runs both the `pr-metadata` check and the regression guard.

`regression-guard.yml` started a runner of its own for each PR push, body edit or reopen (about
1 153 a day in the orchestrator's 7-day count) to make a few API calls. The guard (E49-T01,
03-testing-strategy.md §11.3) is now a step of the `pr-metadata` job. It is not a required check
(CONSTITUTION C-9.1 does not list it; listing it is a C-16 amendment), so its step can neither fail
nor time out the job: `continue-on-error`, a step budget inside the job's, and a finding is a
warning annotation plus a job-summary line (CI-REG-001/002). Like the checker, it runs main's code,
never the PR's: `tools/triage` is extracted from this job's own fetch of `origin/main`.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
DOC: dict[Any, Any] = yaml.safe_load((WORKFLOWS / "pr-metadata.yml").read_text(encoding="utf-8"))
GUARD = "tools.triage.run guard"
READ = {"contents": "read", "pull-requests": "read", "issues": "read"}
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
GIT_ENV |= {f"GIT_{who}_{key}": "t" for who in ("AUTHOR", "COMMITTER") for key in ("NAME", "EMAIL")}
WARNING = "::warning title=regression-guard (non-required)::"
FAIL_12 = (
    f"{WARNING}CI-REG-001: closes Bug issue(s) #12 without a test change or a stated "
    "p3-cosmetic-exempt reason (03-testing-strategy.md §11.3)"
)


def _steps() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = DOC["jobs"]["pr-metadata"]["steps"]
    return steps


def _guard() -> dict[str, Any]:
    found = [step for step in _steps() if GUARD in str(step.get("run", ""))]
    assert len(found) == 1, f"the pr-metadata job runs {GUARD!r} in {len(found)} steps, not 1"
    return found[0]


def test_one_job_runs_the_checker_and_the_guard_on_every_pr_event() -> None:
    assert not (WORKFLOWS / "regression-guard.yml").exists()
    runs = [
        (path.name, job_id)
        for path in sorted(WORKFLOWS.glob("*.y*ml"))
        for job_id, job in (yaml.safe_load(path.read_text("utf-8")).get("jobs") or {}).items()
        for step in job.get("steps") or []
        if GUARD in str(step.get("run", ""))
    ]
    assert runs == [("pr-metadata.yml", "pr-metadata")]
    assert list(DOC["jobs"]) == ["pr-metadata"]
    # The union of the events each read: both read the PR's body, so `edited` stays.
    types = ["opened", "edited", "synchronize", "reopened", "ready_for_review", "labeled"]
    assert DOC.get("on", DOC.get(True)) == {
        "pull_request": {"types": [*types, "unlabeled"], "branches": ["main"]}
    }
    assert DOC["concurrency"] == {
        "group": "metadata-gate-${{ github.event.pull_request.number }}",
        "cancel-in-progress": True,
    }


def test_the_guard_can_neither_fail_nor_time_out_the_required_check() -> None:
    job, steps, guard = DOC["jobs"]["pr-metadata"], _steps(), _guard()
    (checker,) = [step for step in steps if "check_pr_metadata.py" in str(step.get("run", ""))]
    assert "continue-on-error" not in checker and "if" not in checker
    # Last, and after the checker whatever its outcome, so neither hides the other's finding. On
    # every event: a label event's run cancels a push's in the shared group, so it must judge it.
    assert steps.index(checker) < steps.index(guard) == len(steps) - 1
    assert guard["if"] == "${{ !cancelled() && steps.python.outcome == 'success' }}"
    (python,) = [i for i, step in enumerate(steps) if step.get("id") == "python"]
    assert str(steps[python]["uses"]).startswith("actions/setup-python@")
    assert guard["continue-on-error"] is True
    # The job's budget is the old jobs' two (5 + 2), so the guard's step budget fits inside it.
    assert guard["timeout-minutes"] == 2
    assert job["timeout-minutes"] >= 5 + guard["timeout-minutes"]
    # A hung guard is stopped inside the step's budget, so the step still reports CI-REG-002.
    inner = re.search(r"\btimeout (\d+) python -E -s -m tools\.triage\.run guard\b", guard["run"])
    assert inner and int(inner.group(1)) < 60 * guard["timeout-minutes"]


def test_the_guard_needs_no_new_permission_secret_or_package() -> None:
    assert DOC["permissions"] == READ and DOC["jobs"]["pr-metadata"]["permissions"] == READ
    assert _guard()["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "GITHUB_REPOSITORY": "${{ github.repository }}",
        "PR_NUMBER": "${{ github.event.pull_request.number }}",
    }
    for step in _steps():
        run = str(step.get("run", ""))
        assert "${{" not in run and "pip install" not in run, step.get("name")


Files = dict[str, str | PurePosixPath]  # path -> text, or a symlink's target


def _git(repo: Path, *args: str) -> str:
    env = GIT_ENV | {"PATH": os.environ["PATH"]}
    run = subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, check=True)
    return run.stdout.decode().strip()


def _commit(repo: Path, files: Files) -> None:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)  # never write through a symlink main left there
        if isinstance(text, PurePosixPath):
            path.symlink_to(text)
        else:
            path.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "change")


def _stub(out: str, code: int) -> str:
    """A stand-in for tools/triage/run.py: prints what the guard would and exits as it would."""
    return f"import sys\nsys.stdout.write({out!r})\nraise SystemExit({code})\n"


def _run(tmp_path: Path, main: Files, pr: Files) -> Any:
    """The guard step as the runner runs it (`bash -e`), in a checkout of the PR whose
    `refs/remotes/origin/main` is `main`'s tree."""
    repo, bin_dir, temp = tmp_path / "repo", tmp_path / "bin", tmp_path / "runner"
    for path in (repo, bin_dir, temp):
        path.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, {"tools/triage/__init__.py": "", **main})
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _commit(repo, pr)
    python = bin_dir / "python"
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    python.chmod(0o755)
    env = GIT_ENV | {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(temp),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        "PR_NUMBER": "7",
        "GITHUB_REPOSITORY": "o/r",
        "GH_TOKEN": "stand-in",
    }
    bash = shutil.which("bash")
    assert bash, "bash runs the step"
    proc = subprocess.run(
        [bash, "-e", "-c", _guard()["run"]], cwd=repo, env=env, capture_output=True, timeout=60
    )
    summary = tmp_path / "summary.md"
    lines = summary.read_text("utf-8") if summary.exists() else ""
    return proc.returncode, proc.stdout.decode(), lines


PR_COPY: Files = {"tools/triage/run.py": _stub("PR CODE RAN\n", 0)}


def test_a_bug_closed_without_a_test_is_a_warning_and_a_summary_line(tmp_path: Path) -> None:
    out = "#12: FAIL - closing a Bug requires a regression test\n#34: PASS - test file changed\n"
    rc, log, summary = _run(tmp_path, {"tools/triage/run.py": _stub(out, 1)}, PR_COPY)
    assert rc == 1  # the step fails; continue-on-error keeps the job's result the checker's
    assert "PR CODE RAN" not in log  # main's guard judged the PR, never the PR's copy
    assert FAIL_12 in log.splitlines()
    assert "CI-REG-001: closes Bug issue(s) #12 without" in summary and "#34" not in summary


def test_the_guards_output_is_printed_with_workflow_commands_off(tmp_path: Path) -> None:
    # An issue's exemption reason is quoted in the log: none of its lines may act as a command.
    out = "#3: PASS - exempt: typo\n::error title=x::forged\n"
    rc, log, summary = _run(tmp_path, {"tools/triage/run.py": _stub(out, 0)}, {})
    match = re.search(r"^::stop-commands::(\w{32})$", log, re.MULTILINE)
    assert match, log
    start, end = match.end(), log.index(f"\n::{match.group(1)}::\n")
    assert start < log.index("::error title=x::forged") < end
    assert (rc, summary) == (0, "") and WARNING not in log


LINKED: Files = {
    "tools/triage/linked.py": _stub("LINK TARGET RAN\n", 0),
    "tools/triage/run.py": PurePosixPath("linked.py"),
}


@pytest.mark.parametrize("main", [{}, LINKED], ids=["no-guard-on-main", "a-symlink-on-main"])
def test_without_a_guard_on_main_the_prs_copy_never_runs(tmp_path: Path, main: Files) -> None:
    rc, log, summary = _run(tmp_path, main, PR_COPY)
    assert rc == 2 and "PR CODE RAN" not in log and "LINK TARGET RAN" not in log
    assert f"{WARNING}CI-REG-002: no verdict (exit 2); this step's log says why" in log
    assert "CI-REG-002" in summary


def test_a_guard_error_is_no_verdict_not_a_finding(tmp_path: Path) -> None:
    stub = "import sys\nsys.stderr.write('E_TRIAGE_API: HTTP 502\\n')\nraise SystemExit(1)\n"
    rc, log, summary = _run(tmp_path, {"tools/triage/run.py": stub}, {})
    assert rc == 1 and "E_TRIAGE_API: HTTP 502" in log
    assert f"{WARNING}CI-REG-002: no verdict (exit 1); this step's log says why" in log
    assert "CI-REG-001" not in log + summary


def test_the_guard_runs_with_the_prs_number_and_no_environment_hooks(tmp_path: Path) -> None:
    stub = "import sys\nprint(sys.argv[1:], sys.flags.ignore_environment, sys.flags.no_user_site)\n"
    rc, log, _ = _run(tmp_path, {"tools/triage/run.py": stub}, {})
    assert rc == 0 and "['guard', '--number', '7'] 1 1" in log.splitlines()


def test_the_real_guard_runs_on_the_standard_library_alone(tmp_path: Path) -> None:
    # The step installs nothing: the guard's path must not import PyYAML (only sla's calendar does).
    triage, pycache = ROOT / "tools" / "triage", shutil.ignore_patterns("__pycache__")
    shutil.copytree(triage, tmp_path / "tools" / "triage", ignore=pycache)
    code = (
        "import runpy, sys\nsys.modules['yaml'] = None\n"
        "sys.argv = ['run', 'guard', '--number', '7']\n"
        "runpy.run_module('tools.triage.run', run_name='__main__')\n"
    )
    env = {"PATH": os.environ["PATH"]}  # no GH_TOKEN: it stops before any network call
    proc = subprocess.run(
        [sys.executable, "-E", "-s", "-c", code], cwd=tmp_path, env=env, capture_output=True
    )
    assert proc.returncode == 2
    assert proc.stderr.decode().startswith("E_TRIAGE_FIELD_MISSING")
