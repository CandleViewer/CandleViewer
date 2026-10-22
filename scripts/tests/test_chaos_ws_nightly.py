"""#410 (E17-Q02): the nightly WS chaos run keeps the properties its header names.

`chaos-ws-nightly.yml` runs services/api/tests/chaos/ws every night and on demand, in addition to
the PR `py` lane (db-chaos-5): it repeats the suite and picks up any `chaos` test that also carries
`harness`, which the lane's own `-m` deselects there. Nothing runs it until it is on `main`, so
these are its checks: triggers, permissions, a cron minute off the hour marks, one pytest call that
sets its own `-m`, keeps `not flaky` (C-9.3) and never retries, pinned actions, and the step run
under `bash -e` with a stand-in `uv`: a red pytest run must fail the job, which files the report
(test_nightly_issue.py owns the report job and lists the caller)."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
NAME = "chaos-ws-nightly.yml"
CRON = "29 3 * * *"
JUNIT = "chaos-ws-junit.xml"  # what the pytest call writes and the upload step stores
#: A stand-in `uv`: logs its arguments, one line a call, and exits with UV_EXIT.
FAKE_UV = '#!/bin/sh\nprintf "%s\\n" "$*" >> "$UV_LOG"\nexit "$UV_EXIT"\n'


def _load(name: str = NAME) -> dict[Any, Any]:
    """A workflow's YAML; its keys are strings except `on`, which YAML 1.1 reads as True."""
    doc: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    return doc


def _job() -> dict[str, Any]:
    job: dict[str, Any] = _load()["jobs"]["chaos-ws"]
    return job


def _suite() -> dict[str, Any]:
    """The step that runs the suite."""
    steps: list[dict[str, Any]] = _job()["steps"]
    (step,) = [step for step in steps if "pytest" in step.get("run", "")]
    return step


def _sync() -> dict[str, Any]:
    """The step that installs the locked environment."""
    steps: list[dict[str, Any]] = _job()["steps"]
    (step,) = [step for step in steps if step.get("run", "").startswith("uv sync")]
    return step


def test_it_runs_on_its_schedule_and_on_demand_only_with_read_only_permissions() -> None:
    doc = _load()
    assert doc[True] == {"schedule": [{"cron": CRON}], "workflow_dispatch": {}}
    # #3449: no workflow-level group; the report job's per-signal one serialises the filing.
    assert doc["permissions"] == {"contents": "read"} and "concurrency" not in doc
    assert list(doc["jobs"]) == ["chaos-ws", "chaos-ws-issue"]
    job = _job()
    assert (job["runs-on"], job["timeout-minutes"]) == ("ubuntu-latest", 35)
    assert "permissions" not in job  # it holds the workflow's contents: read, and nothing else
    assert job["env"] == {"CV_ENV": "test", "CV_CI_ALLOWED_HOSTS": "", "PYTHONIOENCODING": "utf-8"}
    # A hang fails its own step first: a job that hits its timeout ends cancelled, and the report
    # job files for a failure only. So every step has a cap, and the caps fit inside the job's
    # with 5 minutes to spare for the runner's own set-up and post steps (the uv cache save).
    caps = [step.get("timeout-minutes") for step in job["steps"]]
    assert None not in caps and sum(caps) + 5 <= job["timeout-minutes"], caps
    assert (_sync()["timeout-minutes"], _suite()["timeout-minutes"]) == (5, 15)


def test_its_cron_minute_is_off_the_hour_marks() -> None:
    assert CRON.split()[0] not in {"0", "30"}


def test_its_pytest_call_selects_the_ws_chaos_suite_keeps_not_flaky_and_never_retries() -> None:
    job, step = _job(), _suite()
    assert job["defaults"] == {"run": {"working-directory": "services/api"}}
    argv = shlex.split(step["run"].replace("\\\n", " "))
    assert argv[:4] == ["uv", "run", "pytest", "tests/chaos/ws"]
    # The call's own -m replaces addopts': `not flaky` repeats it (C-9.3), and `chaos` without
    # `not harness` lets the harness-marked heavy runs in. No coverage: addopts' floor is the
    # lanes', which a suite this size cannot meet. No pytest-randomly: the suite's own order.
    # pytest keeps the last -m, and only that expression lets the harness-marked runs in: a
    # `not harness` clause would drop PR 2b's budget #6 run silently.
    marks = [argv[i + 1] for i, word in enumerate(argv) if word == "-m"]
    assert set(marks[-1].split(" and ")) == {"chaos", "not flaky"}
    assert f"--junitxml={JUNIT}" in argv  # the file the upload step stores
    assert "--no-cov" in argv and ("-p", "no:randomly") in pairwise(argv)
    assert not [word for word in argv if word.startswith("--rerun")]
    assert "PYTEST_ADDOPTS" not in (WORKFLOWS / NAME).read_text(encoding="utf-8")
    # A red pytest run must fail the job: nothing may let a failed step pass.
    assert [node for node in (job, *job["steps"]) if "continue-on-error" in node] == []


@pytest.mark.parametrize("code", [0, 1, 2, 5])
def test_the_test_step_exit_code_is_the_job_result(tmp_path: Path, code: int) -> None:
    bash = shutil.which("bash") or ""
    if not bash:  # CI runs these fail-closed proofs
        (pytest.fail if os.environ.get("CI") else pytest.skip)("bash runs the step")
    (tmp_path / "bin").mkdir()
    uv = tmp_path / "bin" / "uv"
    uv.write_text(FAKE_UV, encoding="utf-8")
    uv.chmod(0o755)
    env = {"PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"}
    env |= {"HOME": str(tmp_path), "UV_LOG": str(tmp_path / "uv.log"), "UV_EXIT": str(code)}
    done = subprocess.run(  # noqa: S603 - the workflow's own step text, in a scratch directory
        [bash, "-e", "-c", _suite()["run"]],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    calls = (tmp_path / "uv.log").read_text(encoding="utf-8").splitlines()
    assert (done.returncode, len(calls)) == (code, 1), done.stderr
    assert calls[0].startswith("run pytest tests/chaos/ws ")


def test_every_action_is_pinned_the_checkout_keeps_no_token_and_the_artifact_uploads_always() -> (
    None
):
    steps = _job()["steps"]
    uses = [step for step in steps if "uses" in step]
    assert [step["uses"].partition("@")[0] for step in uses] == [
        "actions/checkout",
        "astral-sh/setup-uv",
        "actions/upload-artifact",
    ]
    assert all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", step["uses"]) for step in uses)
    checkout, _, upload = uses
    assert checkout["with"] == {"persist-credentials": False}
    assert upload["if"] == "always()" and upload["with"]["name"] == "chaos-ws-junit"
    assert upload["with"]["path"] == f"services/api/{JUNIT}"  # the pytest call's --junitxml
    assert upload["with"]["if-no-files-found"] == "warn"
    # Values reach a script through env, never as an expression expanded into it.
    assert [step for step in steps if "${{" in step.get("run", "")] == []
