"""Tests for tools/ci/registry_retry.py (#5113, E03-T14; CI-INFRA-002/003).

The retry loop runs in-process with a fake runner and a fake sleep (a recorded clock: no waits).
The end-to-end cases put fake `uv`, `pnpm` and `pip` executables on PATH that fail or hang the way
a PyPI, npm or GHCR outage does; the per-attempt timeout there is a fraction of a second, set
through the environment, and the waits are 0. No network.
"""

from __future__ import annotations

import io
import os
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools" / "ci" / "registry_retry.py"
sys.path.insert(0, str(REPO))

from tools.ci import registry_retry as rr

# A fake client: fails its first $FAILS calls (exit 1), hangs on each when $HANG=1, then succeeds.
FAKE_CLIENT = r"""#!/bin/bash
n=$(cat "$FAKE/calls" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$FAKE/calls"
echo "$(basename "$0") $*" >> "$FAKE/argv"
if [ "${HANG:-0}" = 1 ]; then echo "fake-pid $$" >&2; exec sleep 60; fi
[ "$n" -gt "${FAILS:-0}" ] || { echo "ERR_SOCKET_TIMEOUT fetching the registry" >&2; exit 1; }
exit 0
"""


class FakeClock:
    def __init__(self) -> None:
        self.waits: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.waits.append(seconds)


def scripted(statuses: Sequence[int]) -> tuple[rr.Runner, list[float]]:
    seen: list[float] = []
    it = iter(statuses)

    def runner(cmd: Sequence[str], timeout: float) -> int:
        seen.append(timeout)
        return next(it)

    return runner, seen


POLICY = rr.Policy(attempts=3, timeout=120.0, backoff=(10.0, 30.0))


def test_retry_first_attempt_succeeds_no_wait_no_warning() -> None:
    runner, seen = scripted([0])
    clock, err = FakeClock(), io.StringIO()
    assert (
        rr.retry(
            "npm",
            ["pnpm", "install"],
            POLICY,
            runner=runner,
            sleep=clock.sleep,
            err=err,
        )
        == 0
    )
    assert seen == [120.0] and clock.waits == [] and err.getvalue() == ""


def test_retry_later_success_warns_and_writes_summary(tmp_path: Path) -> None:
    runner, _ = scripted([1, rr.TIMED_OUT, 0])
    clock, err, summary = FakeClock(), io.StringIO(), tmp_path / "summary.md"
    status = rr.retry(
        "pypi",
        ["uv", "sync"],
        POLICY,
        runner=runner,
        sleep=clock.sleep,
        err=err,
        summary=str(summary),
    )
    assert status == 0 and clock.waits == [10.0, 30.0]
    assert (
        "::warning::PyPI (pypi.org): `uv sync` succeeded on attempt 3 of 3"
        in err.getvalue()
    )
    assert "registry retry: PyPI (pypi.org)" in summary.read_text(encoding="utf-8")


def test_retry_every_attempt_times_out_fails_naming_registry() -> None:
    runner, seen = scripted([rr.TIMED_OUT] * 3)
    clock, err = FakeClock(), io.StringIO()
    assert (
        rr.retry(
            "ghcr",
            ["docker", "pull", "x"],
            POLICY,
            runner=runner,
            sleep=clock.sleep,
            err=err,
        )
        == 1
    )
    out = err.getvalue()
    assert out.count("CI-INFRA-003: GHCR (ghcr.io): attempt") == 3
    assert "timed out after 120 s" in out
    assert (
        "CI-INFRA-002: install from GHCR (ghcr.io) failed after 3 attempts (last: timed out"
        in out
    )
    assert seen == [120.0] * 3 and clock.waits == [10.0, 30.0]


def test_retry_last_backoff_repeats_and_reports_exit_status() -> None:
    runner, _ = scripted([2] * 4)
    clock, err = FakeClock(), io.StringIO()
    policy = rr.Policy(attempts=4, timeout=5.0, backoff=(7.0,))
    assert (
        rr.retry(
            "npm", ["pnpm", "i"], policy, runner=runner, sleep=clock.sleep, err=err
        )
        == 1
    )
    assert clock.waits == [7.0, 7.0, 7.0]
    assert "CI-INFRA-003" not in err.getvalue()
    assert "(last: exit status 2)" in err.getvalue()


def test_parse_policy_flags_beat_env_and_env_beats_defaults() -> None:
    env = {
        "REGISTRY_RETRY_ATTEMPTS": "5",
        "REGISTRY_RETRY_TIMEOUT": "60",
        "REGISTRY_RETRY_BACKOFF": "1 2",
    }
    assert rr.parse_policy(None, None, None, {}) == rr.Policy(3, 300.0, (10.0, 30.0))
    assert rr.parse_policy(None, None, None, env) == rr.Policy(5, 60.0, (1.0, 2.0))
    assert rr.parse_policy("2", "9", "4", env) == rr.Policy(2, 9.0, (4.0,))
    assert rr.parse_policy(None, None, "", {}).backoff == (0.0,)


@pytest.mark.parametrize(
    ("attempts", "timeout", "backoff"),
    [
        ("0", None, None),
        ("x", None, None),
        (None, "0", None),
        (None, "-1", None),
        (None, None, "-3"),
    ],
)
def test_parse_policy_rejects_bad_values(
    attempts: str | None, timeout: str | None, backoff: str | None
) -> None:
    with pytest.raises(ValueError):
        rr.parse_policy(attempts, timeout, backoff, {})


def test_main_usage_errors_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as no_cmd:
        rr.main(["--registry", "npm", "--"], env={})
    with pytest.raises(SystemExit) as bad:
        rr.main(["--registry", "npm", "--attempts", "0", "--", "true"], env={})
    with pytest.raises(SystemExit) as unknown:
        rr.main(["--registry", "dockerhub", "--", "true"], env={})
    assert no_cmd.value.code == bad.value.code == unknown.value.code == 2
    assert "no command given" in capsys.readouterr().err


def test_run_bounded_returns_status_and_kills_on_timeout() -> None:
    assert rr.run_bounded([sys.executable, "-c", "raise SystemExit(3)"], 30) == 3
    start = time.monotonic()
    assert rr.run_bounded(["sleep", "30"], 0.2) == rr.TIMED_OUT
    assert time.monotonic() - start < 10


def test_run_bounded_kills_the_group_when_the_wait_is_interrupted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # #5113 security lens (Low): a cancel interrupts the wait; the install must not outlive it.
    started: list[subprocess.Popen[bytes]] = []

    class Interrupted(subprocess.Popen[bytes]):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            started.append(self)

        def wait(self, timeout: float | None = None) -> int:
            if timeout is not None:
                raise KeyboardInterrupt
            return super().wait()

    monkeypatch.setattr(rr.subprocess, "Popen", Interrupted)
    with pytest.raises(KeyboardInterrupt):
        rr.run_bounded(["sleep", "30"], 30)
    (proc,) = started
    assert proc.returncode == -signal.SIGKILL
    with pytest.raises(ProcessLookupError):
        os.killpg(proc.pid, 0)


def test_main_turns_sigterm_into_exit_143_and_restores_the_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = signal.getsignal(signal.SIGTERM)
    seen: list[object] = []

    def runner_sees_handler(cmd: Sequence[str], timeout: float) -> int:
        seen.append(signal.getsignal(signal.SIGTERM))
        return 0

    assert rr.retry.__kwdefaults__ is not None
    monkeypatch.setitem(rr.retry.__kwdefaults__, "runner", runner_sees_handler)
    assert rr.main(["--registry", "pypi", "--", "true"], env={}) == 0
    assert seen == [rr._raise_on_term] and signal.getsignal(signal.SIGTERM) == before
    with pytest.raises(SystemExit) as term:
        rr._raise_on_term(signal.SIGTERM, None)
    assert term.value.code == 143


@pytest.fixture
def fake(tmp_path: Path) -> dict[str, str]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("uv", "pnpm", "pip"):
        exe = bindir / name
        exe.write_text(FAKE_CLIENT, encoding="utf-8")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("REGISTRY_RETRY_", "GITHUB_"))
    }
    env.update(
        FAKE=str(tmp_path),
        PATH=f"{bindir}{os.pathsep}{env['PATH']}",
        REGISTRY_RETRY_BACKOFF="0",
        REGISTRY_RETRY_TIMEOUT="0.3",
    )
    return env


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _calls(env: dict[str, str]) -> int:
    return int((Path(env["FAKE"]) / "calls").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("registry", "client", "label"),
    [
        ("pypi", "uv", "PyPI (pypi.org)"),
        ("npm", "pnpm", "npm (registry.npmjs.org)"),
        ("ghcr", "pip", "GHCR (ghcr.io)"),
    ],
)
def test_cli_registry_hang_fails_within_bound_naming_registry(
    fake: dict[str, str], registry: str, client: str, label: str
) -> None:
    fake["HANG"] = "1"
    start = time.monotonic()
    proc = _run(fake, "--registry", registry, "--", client, "install")
    assert proc.returncode == 1
    # three 0.3 s attempts, not the fake's 60 s hang
    assert time.monotonic() - start < 30
    assert proc.stderr.count(f"CI-INFRA-003: {label}: attempt") == 3
    assert f"CI-INFRA-002: install from {label} failed after 3 attempts" in proc.stderr
    assert _calls(fake) == 3


def test_cli_sigterm_kills_the_install_and_exits_143(fake: dict[str, str]) -> None:
    # #5113 security lens (Low): a step timeout or cancel SIGTERMs the wrapper; the hung install
    # in its own session dies with it instead of running on until the job ends.
    fake["HANG"] = "1"
    fake["REGISTRY_RETRY_TIMEOUT"] = "60"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-I",
            str(SCRIPT),
            "--registry",
            "npm",
            "--",
            "pnpm",
            "install",
        ],
        env=fake,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert proc.stderr is not None
    line = proc.stderr.readline()  # blocks until the fake client is running
    assert line.startswith("fake-pid "), line
    child = int(line.split()[1])
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=30) == 143
    proc.stderr.close()
    with pytest.raises(ProcessLookupError):
        os.killpg(child, 0)


def test_cli_transient_failure_recovers_and_passes_args_through(
    fake: dict[str, str],
) -> None:
    fake["FAILS"] = "2"
    fake["REGISTRY_RETRY_TIMEOUT"] = "30"
    summary = Path(fake["FAKE"]) / "summary.md"
    fake["GITHUB_STEP_SUMMARY"] = str(summary)
    proc = _run(fake, "--registry", "npm", "--", "pnpm", "install", "--frozen-lockfile")
    assert proc.returncode == 0, proc.stderr
    assert _calls(fake) == 3
    assert (
        "succeeded on attempt 3 of 3" in proc.stderr
        and "CI-INFRA-002" not in proc.stderr
    )
    argv = (Path(fake["FAKE"]) / "argv").read_text(encoding="utf-8").splitlines()
    assert argv == ["pnpm install --frozen-lockfile"] * 3
    assert "registry retry:" in summary.read_text(encoding="utf-8")


def test_cli_hard_failure_stops_at_attempt_budget(fake: dict[str, str]) -> None:
    fake["FAILS"] = "99"
    fake["REGISTRY_RETRY_TIMEOUT"] = "30"
    proc = _run(
        fake, "--registry", "pypi", "--attempts", "2", "--", "uv", "sync", "--frozen"
    )
    assert proc.returncode == 1 and _calls(fake) == 2
    assert "(last: exit status 1)" in proc.stderr


WORKFLOWS = REPO / ".github" / "workflows"


@pytest.mark.parametrize(
    ("workflow", "registry", "install"),
    [
        ("_job-js.yml", "npm", "pnpm install"),
        ("_job-engine-bench.yml", "npm", "pnpm install"),
        ("_job-py.yml", "pypi", "uv sync"),
    ],
)
def test_central_jobs_route_every_install_through_the_wrapper(
    workflow: str, registry: str, install: str
) -> None:
    lines = (WORKFLOWS / workflow).read_text(encoding="utf-8").splitlines()
    runs = [
        ln
        for ln in lines
        if install in ln and not ln.lstrip().startswith(("#", "- name:"))
    ]
    assert runs, f"no {install} step in {workflow}"
    for ln in runs:
        assert f"registry_retry.py --registry {registry}" in ln, ln


@pytest.mark.parametrize(
    "workflow", ["_job-js.yml", "_job-engine-bench.yml", "_job-py.yml", "pr.yml"]
)
def test_every_wrapper_call_resolves_from_its_step_working_directory(
    workflow: str,
) -> None:
    # #5422 review High: a step under `working-directory: services/api` named the wrapper by a
    # root-relative path, so the script was not found and every py job went red. Resolve the path
    # from the step's effective folder (step, then job default) instead of matching a substring.
    import yaml

    root = WORKFLOWS.parent.parent
    doc = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))
    seen = 0
    for job in (doc.get("jobs") or {}).values():
        default = ((job.get("defaults") or {}).get("run") or {}).get(
            "working-directory", "."
        )
        for step in job.get("steps") or []:
            run = str(step.get("run", ""))
            base = str(step.get("working-directory", default)).replace(
                "${{ github.workspace }}", "."
            )
            for line in run.splitlines():
                folder, words = base, line.replace("(", " ").replace(")", " ").split()
                for i, word in enumerate(words):
                    if word == "cd" and i + 1 < len(words):
                        folder = f"{folder}/{words[i + 1]}"  # an inline `cd X && …` moves the folder
                    if not word.endswith("registry_retry.py"):
                        continue
                    seen += 1
                    target = (root / folder / word).resolve()
                    assert target == (root / "tools/ci/registry_retry.py").resolve(), (
                        f"{workflow}: {word!r} from {folder!r} resolves to {target}"
                    )
    assert seen, f"no registry_retry.py call in {workflow}"


def test_uv_jobs_set_the_native_client_settings() -> None:
    for workflow in ("_job-py.yml", "pr.yml"):
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        assert "UV_HTTP_TIMEOUT:" in text and "UV_HTTP_RETRIES:" in text, workflow
