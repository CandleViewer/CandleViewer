"""E49-Q02 (#1336): tools/qa/explore_stack.sh refusals and cleanup, no docker needed. Linux / WSL only."""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

SCRIPT = ROOT / "tools" / "qa" / "explore_stack.sh"
BASH = shutil.which("bash") or "/bin/bash"
STUBS = ("uv", "pnpm", "openssl", "curl")


def run(
    tmp_path: Path,
    *args: str,
    tools: tuple[str, ...] = (),
    extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the script with a PATH that holds only `grep` and the named stub tools."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    grep = shutil.which("grep")
    assert grep is not None
    if not (bin_dir / "grep").exists():
        (bin_dir / "grep").symlink_to(grep)
    for name in tools:
        stub = bin_dir / name.removesuffix("-ok")
        name = name.removesuffix("-ok") if name.endswith("-ok") else name
        if not stub.exists():
            body = "exit 1" if name == "docker" and "docker-ok" not in tools else "exit 0"
            stub.write_text(f"#!{BASH}\n{body}\n")
            stub.chmod(0o755)
    env = {"PATH": str(bin_dir), "TMPDIR": str(tmp_path), **(extra or {})}
    return subprocess.run(
        [BASH, str(SCRIPT), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_script_is_strict_and_cleans_up() -> None:
    text = SCRIPT.read_text()
    assert "set -euo pipefail" in text
    assert "umask 077" in text and "chmod 700" in text
    assert "docker compose down -v" in text and "trap cleanup EXIT" in text
    assert os.access(SCRIPT, os.X_OK)


def test_help_exits_zero(tmp_path: Path) -> None:
    result = run(tmp_path, "--help")
    assert result.returncode == 0 and "usage:" in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ["--nope"],
        ["--bind"],
        ["--api-port", "80x"],
        ["--preview-port", ""],
        ["--api-port", "0"],
        ["--api-port", "99999"],
        ["--api-port", "5000", "--preview-port", "5000"],
    ],
)
def test_bad_arguments_are_refused(tmp_path: Path, args: list[str]) -> None:
    result = run(tmp_path, *args)
    assert result.returncode == 2


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "example.org", "::"])
def test_non_loopback_bind_is_refused(tmp_path: Path, host: str) -> None:
    result = run(tmp_path, "--bind", host)
    assert result.returncode == 2 and "loopback" in result.stderr


def test_non_testnet_environment_is_refused(tmp_path: Path) -> None:
    result = run(tmp_path, extra={"CV_ENVIRONMENT": "live"})
    assert result.returncode == 2 and "testnet" in result.stderr


def test_exchange_variable_is_refused_without_echoing_it(tmp_path: Path) -> None:
    marker = "synthetic-marker-value"
    result = run(tmp_path, extra={"CV_BYBIT_API_" + "ID": marker})
    assert result.returncode == 2 and "CV_BYBIT_API_*" in result.stderr
    assert marker not in result.stdout + result.stderr


@pytest.mark.parametrize("name", ["CV_METRICS_BIND", "CV_BIND_HOST"])
@pytest.mark.parametrize("value", ["0.0.0.0:9108", "192.168.1.5", "example.org:1"])
def test_non_loopback_api_or_metrics_bind_is_refused(tmp_path: Path, name: str, value: str) -> None:
    result = run(tmp_path, extra={name: value})
    assert result.returncode == 2 and "loopback" in result.stderr


@pytest.mark.parametrize("missing", STUBS)
def test_each_missing_tool_is_refused(tmp_path: Path, missing: str) -> None:
    present = tuple(t for t in (*STUBS, "docker-ok") if t != missing)
    result = run(tmp_path, tools=present)
    assert result.returncode == 2 and missing in result.stderr


def test_busy_port_is_refused(tmp_path: Path) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        result = run(tmp_path, "--api-port", str(port), tools=(*STUBS, "docker-ok"))
    assert result.returncode == 2 and "already in use" in result.stderr
    assert not list(tmp_path.glob("cv-explore.*"))


def test_missing_docker_is_refused(tmp_path: Path) -> None:
    result = run(tmp_path, tools=STUBS)
    assert result.returncode == 2 and "docker" in result.stderr


def test_missing_compose_is_refused_and_leaves_no_run_directory(tmp_path: Path) -> None:
    result = run(tmp_path, tools=(*STUBS, "docker"))
    assert result.returncode == 2 and "compose" in result.stderr
    assert not list(tmp_path.glob("cv-explore.*"))


def _busy(port: int) -> bool:
    with socket.socket() as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _gone(pid: int) -> bool:
    """True once the process is absent or only a zombie, polled for up to 5 s."""
    for _ in range(50):
        try:
            state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
        except (FileNotFoundError, ProcessLookupError):
            return True
        if state == "Z":
            return True
        time.sleep(0.1)
    return False


@pytest.mark.skipif(
    any(_busy(p) for p in (5432, 8812, 9009, 9000, 9108, 8000, 4174)),
    reason="a stack port is in use",
)
def test_full_run_with_stubs_cleans_up_end_to_end(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in (
        "mktemp",
        "chmod",
        "mkdir",
        "rm",
        "seq",
        "sleep",
        "cat",
        "tail",
        "dirname",
        "basename",
        "grep",
    ):
        path = shutil.which(name)
        assert path is not None
        (bin_dir / name).symlink_to(path)
    marker = "marker-not-for-output"
    docker_log = tmp_path / "docker.log"
    child_pid = tmp_path / "child.pid"
    api_env = tmp_path / "api.env"
    pnpm_args = tmp_path / "pnpm.args"
    api_stub = (
        f'case "$*" in *candleviewer.server*) printf "%s\\n" "$CV_BIND_HOST" "$CV_METRICS_BIND" >{api_env}; '
        f"sleep 300 & echo $! >{child_pid}; wait ;; esac"
    )
    curl_stub = f"for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do [ -s {child_pid} ] && break; sleep 0.1; done"
    for name, body in (
        ("docker", f'echo "$COMPOSE_PROJECT_NAME $*" >>{docker_log}'),
        ("uv", api_stub),
        ("pnpm", f'echo "$*" >>{pnpm_args}'),
        ("curl", curl_stub),
        ("openssl", f'if [ "$3" = 32 ]; then echo {marker}; else echo abc123; fi'),
    ):
        stub = bin_dir / name
        stub.write_text(f"#!{BASH}\n{body}\n")
        stub.chmod(0o755)
    env = {"PATH": str(bin_dir), "TMPDIR": str(tmp_path)}
    result = subprocess.run(
        [BASH, str(SCRIPT), "--skip-build"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 2  # the stub preview exits at once
    assert "the preview exited" in result.stderr
    assert marker not in result.stdout + result.stderr
    assert not list(tmp_path.glob("cv-explore.*"))
    logged = docker_log.read_text().splitlines()
    assert any(re.fullmatch(r"cv-explore-[0-9a-f]{6} compose down -v", line) for line in logged)
    assert _gone(int(child_pid.read_text()))
    api_host, metrics_bind = api_env.read_text().split()
    assert api_host == "127.0.0.1" and metrics_bind.startswith("127.0.0.1:")
    preview = [ln for ln in pnpm_args.read_text().splitlines() if "vite preview" in ln]
    assert len(preview) == 1 and f"--host {api_host}" in preview[0]
