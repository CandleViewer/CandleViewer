"""#2893's closure: `infra/scripts/account_fixture_stack.py`, run against a stub `docker`.

The script runs as a subprocess with a stub first on PATH, as `test_demo_host_owner_first_run.py`
runs its script: the stub records each call's arguments and the names of the environment it got,
answers the label listings from the test's scenario, and exits as the scenario says. No Docker, no
network: the only socket is a loopback bind the script makes to find free ports.
"""

from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import pytest

REPO: Final = Path(__file__).resolve().parents[3]
SCRIPT: Final = REPO / "infra" / "scripts" / "account_fixture_stack.py"
FILES: Final = [
    str(REPO / "infra" / "compose" / name)
    for name in (
        "docker-compose.yml",
        "docker-compose.dev.yml",
        "docker-compose.account-fixture.yml",
        "docker-compose.account-fixture-real.yml",
    )
]
PROJECT: Final = "cv-acctfix-0a1b2c"
#: The stub: logs its call to $HOME/docker.jsonl (HOME is one of the names the script keeps).
STUB: Final = """
import json, os, sys
home = os.environ["HOME"]
args = sys.argv[1:]
scenario = json.load(open(os.path.join(home, "scenario.json"), encoding="utf-8"))
record = {"args": args, "env": sorted(os.environ), "default": os.environ.get("CV_ACCOUNT_FIXTURE")}
with open(os.path.join(home, "docker.jsonl"), "a", encoding="utf-8") as log:
    log.write(json.dumps(record) + "\\n")
kind = {"ps": "containers", "network": "networks", "volume": "volumes"}.get(args[0])
if kind and "--filter" in args:
    print("\\n".join(scenario.get(kind, [])))
for word, status in scenario.get("exit", {}).items():
    if word in args:
        raise SystemExit(status)
"""
SECRET_NAMES: Final = (
    "POSTGRES_PASSWORD",
    "CV_PG_DSN",
    "CV_PG_OWNER_DSN",
    "CV_AUTH_PEPPER",
    "CV_AUTH_TOTP_KEY_HEX",
    "CV_AUTH_RECOVERY_HMAC_KEY_HEX",
    "CV_AUTH_CSRF_KEY_HEX",
)


class Host:
    """One test's host: the stub on PATH, HOME, the user's runtime directory and the scenario."""

    def __init__(self, tmp_path: Path, **scenario: Any) -> None:
        names = ("home", "bin", "runtime", "tmp")
        self.home, self.bin, self.runtime, self.tmp = (tmp_path / d for d in names)
        for directory in (self.home, self.bin, self.runtime, self.tmp):
            directory.mkdir(mode=0o700)
        stub = self.bin / "docker"
        stub.write_text(f"#!{sys.executable} -IS\n{STUB}", encoding="utf-8")
        stub.chmod(stat.S_IRWXU)
        self.scenario(**scenario)

    def scenario(self, **scenario: Any) -> None:
        (self.home / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")

    def run(self, *args: str, **extra_env: str) -> subprocess.CompletedProcess[str]:
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.home)}
        env |= {"XDG_RUNTIME_DIR": str(self.runtime), "TMPDIR": str(self.tmp), **extra_env}
        return subprocess.run(  # noqa: S603 - this interpreter and the script under test
            [sys.executable, "-I", str(SCRIPT), *args],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )

    def calls(self) -> list[dict[str, Any]]:
        log = self.home / "docker.jsonl"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def compose_calls(self) -> list[list[str]]:
        return [call["args"] for call in self.calls() if call["args"][:1] == ["compose"]]

    def env_values(self, project: str = PROJECT) -> dict[str, str]:
        text = (self.runtime / project / "stack.env").read_text(encoding="ascii")
        return dict(line.split("=", 1) for line in text.splitlines())


def _compose(project: str, env_file: str, *extra: str) -> list[str]:
    files = [word for path in (*FILES, *extra) for word in ("-f", path)]
    return ["compose", "-p", project, *files, "--env-file", env_file]


def test_up_runs_the_steps_in_order(tmp_path: Path) -> None:
    """Postgres and QuestDB, the schema step (both profiles: migrate depends on Postgres), the
    seed's one-shot, then the api, each over the four files and the run's env file."""
    host = Host(tmp_path)

    done = host.run("up", "--project", PROJECT)

    assert done.returncode == 0, done.stderr
    base = _compose(PROJECT, str(host.runtime / PROJECT / "stack.env"))
    assert host.compose_calls() == [
        [*base, "--profile", "core", "up", "-d", "--wait", "postgres", "questdb"],
        [*base, "--profile", "core", "--profile", "migrate", "run", "--rm", "migrate"],
        [*base, "--profile", "fixture-init", "run", "--rm", "--no-deps", "fixture-init"],
        [*base, "--profile", "core", "up", "-d", "--wait", "api"],
    ]
    assert done.stdout.splitlines()[-1] == f"account-fixture-stack: up: {PROJECT}"
    listings = [call["args"][0] for call in host.calls()[:3]]
    assert listings == ["ps", "network", "volume"]  # nothing of the project is left, first


@pytest.mark.parametrize(
    "project", ["cv-demo", "cv-demo-api", "cv-acctfix-xyz123", "cv-acctfix-0a1b2c3", "other"]
)
def test_up_refuses_the_demo_project_and_any_name_not_cv_acctfix(
    tmp_path: Path, project: str
) -> None:
    host = Host(tmp_path)

    for command in (["up"], ["down"], ["drive"], ["restart-api", "--default", "compliant"]):
        done = host.run(*command[:1], "--project", project, *command[1:])
        assert done.returncode == 2 and "cv-acctfix-<6 hex digits>" in done.stderr, command

    assert host.calls() == [] and list(host.runtime.iterdir()) == []


def test_up_writes_stack_env_0600_and_prints_no_value(tmp_path: Path) -> None:
    """T3 at the script's level: the run directory is 0700 and flat, `stack.env` 0600 with every
    name compose needs, and no generated value is in its output or in any docker argument."""
    host = Host(tmp_path)

    done = host.run("up", "--project", PROJECT)

    run_dir = host.runtime / PROJECT
    assert done.returncode == 0, done.stderr
    assert stat.S_IMODE(run_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE((run_dir / "stack.env").stat().st_mode) == 0o600
    assert [p.name for p in run_dir.iterdir()] == ["stack.env"]  # the one-shot writes the rest
    values = host.env_values()
    assert values["CV_KEK_FILE"] == str(run_dir / "kek")
    assert values["CV_AUDIT_LANE_MAC_SOURCE"] == str(run_dir / "lane.key")
    assert (values["CV_ACCTFIX_RUN_DIR"], values["CV_ACCTFIX_RUN_UID"]) == (
        str(run_dir),
        str(os.getuid()),
    )
    assert values["CV_PG_DSN"].endswith("@postgres:5432/acctfix_test")  # the seed's *_test
    assert values["CV_ACCOUNT_FIXTURE"] == "compliant"
    generated = [values[name] for name in SECRET_NAMES]
    shown = [done.stdout, done.stderr, *(json.dumps(call["args"]) for call in host.calls())]
    echoed = any(value in text for value in generated for text in shown)  # a boolean
    assert not echoed


def test_values_are_fresh_per_run(tmp_path: Path) -> None:
    host = Host(tmp_path)
    assert host.run("up", "--project", PROJECT).returncode == 0
    assert host.run("up", "--project", "cv-acctfix-0a1b2d").returncode == 0

    first, second = host.env_values(), host.env_values("cv-acctfix-0a1b2d")

    fresh = all(first[name] != second[name] for name in SECRET_NAMES)  # a boolean: no value shown
    assert fresh
    distinct = len({first[name] for name in SECRET_NAMES[3:]}) == 4  # pepper and the three keys
    assert distinct


def test_down_removes_volumes_and_the_run_dir_and_is_idempotent(tmp_path: Path) -> None:
    """`down -v --remove-orphans` with every profile active (with none, compose removes nothing,
    as every service here has a profile), then the run directory, root's files in it included;
    a second `down` finds nothing and still says so."""
    host = Host(tmp_path)
    assert host.run("up", "--project", PROJECT).returncode == 0
    run_dir = host.runtime / PROJECT
    (run_dir / "kek").write_bytes(b"x")  # what the one-shot leaves, here the test user's own
    host.scenario(volumes=[f"{PROJECT}_cv-postgres-data"])  # still there when down starts

    first = host.run("down", "--project", PROJECT)

    assert not os.path.lexists(run_dir)
    base = _compose(PROJECT, str(run_dir / "stack.env"))
    assert host.compose_calls()[-1] == [*base, "--profile", "*", "down", "-v", "--remove-orphans"]
    assert first.returncode == 1  # the stub's volume is still listed after: reported, not hidden
    assert "1 volumes left" in first.stdout
    host.scenario()  # docker removed it
    calls_before = len(host.compose_calls())

    second = host.run("down", "--project", PROJECT)

    assert second.returncode == 0, second.stderr
    assert len(host.compose_calls()) == calls_before  # nothing left to take down
    expected = "0 containers, 0 networks, 0 volumes left; run directory removed"
    assert second.stdout.strip().endswith(expected)


def test_down_without_the_env_file_uses_inert_values_and_keeps_none(tmp_path: Path) -> None:
    """After a reboot the tmpfs run directory is gone but the volumes are not: compose still
    needs every required variable, so `down` hands it inert ones in a file it then removes."""
    host = Host(tmp_path, volumes=[f"{PROJECT}_cv-postgres-data"])

    host.run("down", "--project", PROJECT)

    [down] = host.compose_calls()
    env_file = Path(down[down.index("--env-file") + 1])
    assert env_file.is_relative_to(host.tmp) and not env_file.exists()  # removed after
    assert down[-5:] == ["--profile", "*", "down", "-v", "--remove-orphans"]


def test_up_refuses_volumes_whose_run_dir_is_gone(tmp_path: Path) -> None:
    host = Host(tmp_path, volumes=[f"{PROJECT}_cv-postgres-data"])

    done = host.run("up", "--project", PROJECT)

    assert done.returncode == 2 and "take it down first" in done.stderr
    assert host.compose_calls() == [] and list(host.runtime.iterdir()) == []


def test_a_failed_step_stops_up_and_names_it(tmp_path: Path) -> None:
    host = Host(tmp_path, exit={"migrate": 4})

    done = host.run("up", "--project", PROJECT)

    assert done.returncode == 2
    assert done.stderr.strip().endswith("the schema step exited 4: take the project down")
    assert [call[-1] for call in host.compose_calls()] == ["questdb", "migrate"]


def test_no_config_or_inspect_is_ever_invoked(tmp_path: Path) -> None:
    """`docker compose config` and `docker inspect` print environment values: never run."""
    host = Host(tmp_path)
    host.run("up", "--project", PROJECT)
    host.run("restart-api", "--project", PROJECT, "--default", "ws_auth_then_drop")
    host.run("drive", "--project", PROJECT, "--", "signin", "qa-owner-1")
    host.run("down", "--project", PROJECT)

    words = {word for call in host.calls() for word in call["args"]}
    assert len(host.calls()) > 10
    assert {"config", "inspect"}.isdisjoint(words)


def test_extra_compose_files_and_ports_are_taken_from_the_lane(tmp_path: Path) -> None:
    """A lane-local file (a private subnet for `cv-internal`) goes after the four, as an absolute
    path, on every call; a port the lane names lands in the env file; one in use is refused."""
    host = Host(tmp_path)
    lane = tmp_path / "net.yml"
    lane.write_text("networks: {}\n", encoding="utf-8")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # the socket is closed here, so the port is free again for the script to check

    done = host.run("up", "--project", PROJECT, "-f", str(lane), "--port", f"POSTGRES_PORT={port}")

    assert done.returncode == 0, done.stderr
    base = _compose(PROJECT, str(host.runtime / PROJECT / "stack.env"), str(lane))
    assert all(call[: len(base)] == base for call in host.compose_calls())
    assert host.env_values()["POSTGRES_PORT"] == str(port)
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        taken = busy.getsockname()[1]
        refused = host.run(
            "up", "--project", "cv-acctfix-0a1b2e", "--port", f"CV_BIND_PORT={taken}"
        )
    assert refused.returncode == 2 and "in use" in refused.stderr


def test_docker_runs_with_the_env_file_alone_never_the_shells_variables(tmp_path: Path) -> None:
    """Compose lets the shell override the env file: a stray `CV_PG_DSN` or `COMPOSE_FILE` in the
    caller's shell would steer the stack, so docker gets PATH, HOME and DOCKER_* alone."""
    host = Host(tmp_path)

    host.run("up", "--project", PROJECT, CV_PG_DSN="postgresql://x", COMPOSE_FILE="x.yml")

    names = {name for call in host.calls() for name in call["env"]}
    assert names <= {"PATH", "HOME", "LC_CTYPE"}  # the stub's own python may set LC_CTYPE


def test_restart_api_recreates_the_api_alone_with_the_new_default(tmp_path: Path) -> None:
    host = Host(tmp_path)
    assert host.run("up", "--project", PROJECT).returncode == 0

    done = host.run("restart-api", "--project", PROJECT, "--default", "demo_ws_unreachable")

    assert done.returncode == 0, done.stderr
    last = host.calls()[-1]
    base = _compose(PROJECT, str(host.runtime / PROJECT / "stack.env"))
    tail = ["--profile", "core", "up", "-d", "--no-deps", "--force-recreate", "--wait", "api"]
    assert last["args"] == [*base, *tail]
    assert last["default"] == "demo_ws_unreachable"
    assert host.run("restart-api", "--project", PROJECT, "--default", "../x").returncode == 2


def test_drive_runs_the_driver_in_its_one_shot_and_returns_its_status(tmp_path: Path) -> None:
    host = Host(tmp_path)
    assert host.run("up", "--project", PROJECT).returncode == 0
    host.scenario(exit={"fixture-drive": 3})

    done = host.run("drive", "--project", PROJECT, "--", "call", "qa-owner-1", "GET", "/me")

    base = _compose(PROJECT, str(host.runtime / PROJECT / "stack.env"))
    run = ["--profile", "fixture-drive", "run", "--rm", "--no-deps", "-T", "fixture-drive"]
    assert host.compose_calls()[-1] == [*base, *run, "call", "qa-owner-1", "GET", "/me"]
    assert done.returncode == 3


def test_the_run_dir_is_the_users_tmpfs_else_dev_shm(tmp_path: Path) -> None:
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import account_fixture_stack as stack
    finally:
        sys.path.remove(str(SCRIPT.parent))

    assert stack.run_root({"XDG_RUNTIME_DIR": str(tmp_path)}) == tmp_path
    shm = Path("/dev/shm")  # noqa: S108 - the fallback the script names, never written here
    assert stack.run_root({"XDG_RUNTIME_DIR": "relative"}) == shm
    assert stack.run_root({}) == shm
