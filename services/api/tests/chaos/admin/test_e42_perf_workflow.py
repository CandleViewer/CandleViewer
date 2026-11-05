"""E42-Q03 (#1216): `perf-admin.yml` is dispatch only, on the bench runner, with the compose file's
pinned images and perf-ws-load.yml's k6 digest, and its first step refuses to start while a 24 h
soak holds the runner. The step's own script runs here with a stand-in `gh` on PATH: idle passes,
a running soak and an unanswered API both go red. The API's port check (`bench/admin/api_up.py`)
runs on a loopback listener of the test's own: another process's listener fails the wait. No
network, no runner.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from bench.admin import REPO, api_up

WORKFLOW = REPO / ".github/workflows/perf-admin.yml"


def _workflow() -> dict[Any, Any]:
    return dict(yaml.safe_load(WORKFLOW.read_text()))


def test_workflow_is_dispatch_only_on_the_bench_runner_with_the_compose_pins() -> None:
    doc = _workflow()
    assert list(doc[True]) == ["workflow_dispatch"]  # YAML 1.1 reads `on` as True
    job = doc["jobs"]["admin-perf"]
    assert job["runs-on"] == ["self-hosted", "Linux", "X64", "bench"]
    compose = (REPO / "infra/compose/docker-compose.yml").read_text()
    assert f"image: {job['env']['PG_IMAGE']}\n" in compose
    assert f"image: {job['env']['QDB_IMAGE']}\n" in compose
    ws = (REPO / ".github/workflows/perf-ws-load.yml").read_text()
    assert f"K6_SHA256: {job['env']['K6_SHA256']}\n" in ws


def _soak_guard(tmp_path: Path, gh: str) -> subprocess.CompletedProcess[str]:
    step = _workflow()["jobs"]["admin-perf"]["steps"][0]
    assert step["name"].startswith("Refuse to start while a 24 h soak")
    fake = tmp_path / "bin" / "gh"
    fake.parent.mkdir()
    fake.write_text(f"#!/bin/bash\n{gh}\n")
    fake.chmod(0o755)
    env = {"PATH": f"{fake.parent}:{os.environ['PATH']}", "GITHUB_REPOSITORY": "o/r"}
    return subprocess.run(  # noqa: S603 - fixed argv; the script is the workflow's own step
        ["/bin/bash", "-c", step["run"]], env=env, capture_output=True, text=True, timeout=30,
        check=False,
    )  # fmt: skip


IDLE = 'case "$*" in *runs\\?status*) exit 0;; *) echo 0;; esac'
BUSY = 'case "$*" in *perf-ingestion-nightly.yml/runs\\?status=in_progress*) echo 7;; *runs\\?status*) exit 0;; *) echo 1;; esac'  # noqa: E501 - one shell line
DOWN = 'echo "gh: Not Found (HTTP 404)" >&2; exit 1'


def test_soak_guard_passes_an_idle_runner(tmp_path: Path) -> None:
    assert _soak_guard(tmp_path, IDLE).returncode == 0


def test_soak_guard_refuses_while_the_ingestion_soak_runs(tmp_path: Path) -> None:
    done = _soak_guard(tmp_path, BUSY)
    assert done.returncode == 1 and "perf-ingestion-nightly.yml (job perf-pack-full)" in done.stderr


def test_soak_guard_fails_closed_when_github_does_not_answer(tmp_path: Path) -> None:
    assert _soak_guard(tmp_path, DOWN).returncode != 0


def _steps() -> dict[str, str]:
    return {s.get("name", ""): s.get("run", "") for s in _workflow()["jobs"]["admin-perf"]["steps"]}


def test_the_api_has_a_port_of_its_own_checked_before_and_after_it_starts() -> None:
    job = _workflow()["jobs"]["admin-perf"]
    port = job["env"]["CV_BIND_PORT"]
    assert port == "58000"
    for path in [*(REPO / "infra").rglob("*.y*ml"), *(REPO / ".github/workflows").glob("*.yml")]:
        assert path == WORKFLOW or port not in path.read_text(), path
    start = next(r for n, r in _steps().items() if n.startswith("Start the API"))
    free, nohup, up = (start.index(k) for k in ("api_up.py free", "nohup", "api_up.py wait"))
    assert free < nohup < up and "curl" not in start
    perf = next(r for n, r in _steps().items() if n.startswith("Admin perf"))
    assert '--base-url "http://127.0.0.1:${CV_BIND_PORT}"' in perf and '--rows "$ROWS"' in perf


def test_the_api_wait_fails_when_another_listener_holds_the_port() -> None:
    with socket.socket() as other:
        other.bind(("127.0.0.1", 0))
        other.listen()
        port = other.getsockname()[1]
        assert api_up.main(["free", "--port", str(port)]) == 1
        api = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:  # the started API is alive and the port answers, but the listener is not its own
            assert api_up.wait(port, api.pid, 1, 0, probe=lambda _p: True) == 1
        finally:
            api.kill()
            api.wait(timeout=10)
        assert api_up.wait(port, api.pid, 1, 0, probe=lambda _p: True) == 1  # it exited
        assert api_up.wait(port, os.getpid(), 1, 0, probe=lambda _p: True) == 0  # its own
        assert api_up.wait(port, os.getpid(), 2, 0, probe=lambda _p: False) == 1  # no answer
    assert api_up.main(["free", "--port", str(port)]) == 0


def test_teardown_signals_the_api_pid_only_while_it_is_still_uv(tmp_path: Path) -> None:
    """S-1216P1-d03: a pid file naming some other process (a reused pid) is left alone."""
    step = next(r for n, r in _steps().items() if n.startswith("Tear down"))
    assert step.index('[ "$(ps -o comm= -p "$pid" 2>/dev/null)" = uv ]') < step.index("pkill")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text("#!/bin/bash\nexit 0\n")
    docker.chmod(0o755)
    (tmp_path / "cv").mkdir()
    other = subprocess.Popen(["/bin/sleep", "60"])
    try:
        (tmp_path / "cv/api.pid").write_text(f"{other.pid}\n")
        env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "RUNNER_TEMP": str(tmp_path)}
        done = subprocess.run(  # noqa: S603 - fixed argv; the script is the workflow's own step
            ["/bin/bash", "-c", step], env=env, capture_output=True, text=True, timeout=30,
            check=False,
        )  # fmt: skip
        assert done.returncode == 0, done.stderr
        assert other.poll() is None  # still running: the guard did not signal it
    finally:
        other.kill()
        other.wait(timeout=10)
