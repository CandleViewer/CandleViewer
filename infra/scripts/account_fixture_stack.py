#!/usr/bin/env python3
"""#2893's closure: bring the account fixture's real-backend stack up, drive it, take it down.

    python3 infra/scripts/account_fixture_stack.py up [--project P] [-f EXTRA]... [--port NAME=N]...
    python3 infra/scripts/account_fixture_stack.py restart-api --project P --default S [-f ...]
    python3 infra/scripts/account_fixture_stack.py drive --project P [-f ...] -- signin qa-owner-1
    python3 infra/scripts/account_fixture_stack.py down --project P

One compose project, `cv-acctfix-<6 hex>` (never `cv-demo`, never another name), over the base, dev,
account-fixture and real-backend files, then any lane-local file (`-f`, such as a private subnet for
`cv-internal` on a host that runs another stack), with the run's env file. `up` checks the host
first (the project name, the run root, five distinct free loopback ports, no container, network or
volume of the project left over), then makes the run directory (`$XDG_RUNTIME_DIR/<project>`, else
under `/dev/shm`; mode 0700, flat, on tmpfs) and its `stack.env` (0600, a new file): the Postgres
password and DSNs, the pepper and three auth keys (each new per run), the two secret files' paths,
the run directory, the invoking user's uid, the default scenario, the host ports and inert values
for the stores that never start. Then, in order: Postgres and QuestDB, the schema step,
`fixture-init` (the seed's `init`: the run's KEK, audit lane key and users, as root, into the run
directory), the api (the base file makes the schema step the api's dependency, so the api's start
runs that step once more, which changes nothing on a migrated database).

`down` goes by the project name alone (`docker compose -p <project> down -v --remove-orphans`, run
from an empty directory): compose then reads no compose file and no env file, so `down` works with
the run directory gone (a reboot), and running it again is how a failed `down` is retried. The run
directory goes last, once the project's label lists nothing; until then `down` keeps it.

It prints the project name, the steps, exit statuses and counts, never a value. Docker runs with
`PATH`, `HOME` and `DOCKER_*` alone from the caller's environment, so no stray variable of the
shell overrides the run's env file. It never runs `docker compose config` or `docker inspect`,
which print values. Stdlib only. Runbook: docs/ops/runbooks/account-fixture-stack.md.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

REPO: Final = Path(__file__).resolve().parents[2]
COMPOSE_DIR: Final = REPO / "infra" / "compose"
COMPOSE_FILES: Final = tuple(
    COMPOSE_DIR / name
    for name in (
        "docker-compose.yml",
        "docker-compose.dev.yml",
        "docker-compose.account-fixture.yml",
        "docker-compose.account-fixture-real.yml",
    )
)
PROJECT: Final = re.compile(r"cv-acctfix-[0-9a-f]{6}")
SCENARIO: Final = re.compile(r"[a-z0-9_]{1,64}")
PORT_NAMES: Final = (
    "POSTGRES_PORT",
    "QUESTDB_PG_PORT",
    "QUESTDB_ILP_PORT",
    "QUESTDB_HTTP_PORT",
    "CV_BIND_PORT",
)
#: The seed's gate refuses a database whose name is not `test` or `*_test`.
DATABASE: Final = "acctfix_test"
ENV_FILE: Final = "stack.env"
DEFAULT_SCENARIO: Final = "compliant"
EXIT_REFUSED: Final = 2
FAILED: Final = "a file, socket or process call failed"
#: How often `up` draws the free ports again while two of them coincide.
PORT_DRAWS: Final = 8
#: What compose demands on every command for the stores and alerts this stack never starts.
INERT: Final = {
    "GF_SECURITY_ADMIN_PASSWORD": "unused",
    "MINIO_ROOT_PASSWORD": "unused",
    "CV_ALERT_PAGE_WEBHOOK_URL": "http://127.0.0.1:1/unused",
    "CV_ALERT_TICKET_WEBHOOK_URL": "http://127.0.0.1:1/unused",
    "CV_ALERT_DEADMAN_URL": "http://127.0.0.1:1/unused",
}
#: `down`'s compose command after `-p <project>`: no file and no env file, the name is enough.
TEARDOWN: Final = ("down", "-v", "--remove-orphans")
#: The caller's environment docker keeps: nothing else, so the env file alone sets the stack.
_DOCKER_ENV: Final = re.compile(r"PATH|HOME|DOCKER_[A-Z_]+")
_LABEL: Final = "label=com.docker.compose.project={}"
_LISTS: Final = (
    ("containers", ("ps", "-a")),
    ("networks", ("network", "ls")),
    ("volumes", ("volume", "ls")),
)


class Refused(Exception):
    """A fixed message, printed as one line; it never holds a value."""


def run_root(environ: Mapping[str, str]) -> Path:
    """`$XDG_RUNTIME_DIR` (the user's own tmpfs) when it is an absolute directory, else /dev/shm."""
    runtime = environ.get("XDG_RUNTIME_DIR", "")
    if runtime.startswith("/") and os.path.isdir(runtime):
        return Path(runtime)
    return Path("/dev/shm")  # noqa: S108 - the tmpfs fallback; the run directory is a new mkdir


def checked_project(name: str) -> str:
    if PROJECT.fullmatch(name) is None:
        raise Refused("the project must be named cv-acctfix-<6 hex digits>, never another stack's")
    return name


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def is_free(port: int) -> bool:
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def ports(given: Sequence[str]) -> dict[str, str]:
    """A free loopback port for each published service, or the lane's `NAME=N` for it: five
    distinct ports, the free ones drawn again while two coincide."""
    chosen: dict[str, str] = {}
    for item in given:
        name, _, number = item.partition("=")
        decimal = number.isascii() and number.isdecimal()  # `isdigit` also takes a superscript
        if name not in PORT_NAMES or not decimal or not 0 < int(number) < 65536:
            raise Refused(f"--port takes NAME=N, NAME one of {', '.join(PORT_NAMES)}")
        if not is_free(int(number)):
            raise Refused(f"the port given for {name} is in use on 127.0.0.1")
        chosen[name] = str(int(number))
    if len(set(chosen.values())) != len(chosen):
        raise Refused("each --port must name a port of its own")
    for _ in range(PORT_DRAWS):
        drawn = {name: chosen.get(name) or str(free_port()) for name in PORT_NAMES}
        if len(set(drawn.values())) == len(PORT_NAMES):
            return drawn
    raise Refused("no five distinct free ports were found on 127.0.0.1: name them with --port")


def stack_values(
    project: str, run_dir: Path, uid: int, scenario: str, host_ports: Mapping[str, str]
) -> dict[str, str]:
    """The run's env file: generated values, new per run, and the paths and names compose needs."""
    password = secrets.token_urlsafe(24)
    dsn = f"postgresql+asyncpg://cv:{password}@postgres:5432/{DATABASE}"
    return {
        "COMPOSE_PROJECT_NAME": project,
        "POSTGRES_PASSWORD": password,
        "POSTGRES_DB": DATABASE,
        "CV_PG_DSN": dsn,
        "CV_PG_OWNER_DSN": dsn,  # on the dev stack `cv` owns the schema (storage-migrate.md)
        "CV_AUTH_PEPPER": secrets.token_urlsafe(32),
        "CV_AUTH_TOTP_KEY_HEX": secrets.token_hex(32),
        "CV_AUTH_RECOVERY_HMAC_KEY_HEX": secrets.token_hex(32),
        "CV_AUTH_CSRF_KEY_HEX": secrets.token_hex(32),
        "CV_KEK_FILE": str(run_dir / "kek"),
        "CV_AUDIT_LANE_MAC_SOURCE": str(run_dir / "lane.key"),
        "CV_ACCTFIX_RUN_DIR": str(run_dir),
        "CV_ACCTFIX_RUN_UID": str(uid),
        "CV_ACCOUNT_FIXTURE": scenario,
        **INERT,
        **host_ports,
    }


def write_env(path: Path, values: Mapping[str, str]) -> None:
    """A new file of mode 0600: an existing file or link is never replaced or followed."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as out:
        os.fchmod(descriptor, 0o600)
        out.write("".join(f"{name}={value}\n" for name, value in values.items()))


def docker_env(environ: Mapping[str, str], **extra: str) -> dict[str, str]:
    return {k: v for k, v in environ.items() if _DOCKER_ENV.fullmatch(k)} | extra


def compose(project: str, env_file: Path, extra: Sequence[str]) -> list[str]:
    files = [*COMPOSE_FILES, *(Path(path).resolve() for path in extra)]
    argv = ["docker", "compose", "-p", project]
    for path in files:
        argv += ["-f", str(path)]
    return [*argv, "--env-file", str(env_file)]


def call(argv: Sequence[str], env: Mapping[str, str], cwd: str | None = None) -> int:
    done = subprocess.run(  # noqa: S603 - docker, an argument list built here
        list(argv), env=dict(env), cwd=cwd, check=False
    )
    return done.returncode


def leftovers(project: str, env: Mapping[str, str]) -> dict[str, list[str]]:
    """The project's containers, networks and volumes, by its compose label: names only."""
    found: dict[str, list[str]] = {}
    for kind, command in _LISTS:
        argv = ["docker", *command, "--filter", _LABEL.format(project), "--format", "{{.Name}}"]
        if kind == "containers":
            argv[-1] = "{{.Names}}"
        done = subprocess.run(  # noqa: S603 - docker, an argument list built here
            argv, env=dict(env), capture_output=True, text=True, check=False
        )
        if done.returncode != 0:
            raise Refused(f"docker did not list the project's {kind}")
        found[kind] = [line for line in done.stdout.splitlines() if line.strip()]
    return found


def up(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    project = checked_project(args.project or f"cv-acctfix-{secrets.token_hex(3)}")
    scenario = args.default
    if SCENARIO.fullmatch(scenario) is None:
        raise Refused("the default scenario must be a scenario name (a-z, 0-9 and _)")
    root = run_root(environ)
    run_dir = root / project
    if os.path.lexists(run_dir):
        raise Refused("the run directory already exists: take that run down first")
    host_ports = ports(args.port)
    env = docker_env(environ)
    if any(leftovers(project, env).values()):
        raise Refused("the project has containers, networks or volumes left: take it down first")
    os.mkdir(run_dir, 0o700)
    os.chmod(run_dir, 0o700)  # the umask never loosens or tightens it
    env_file = run_dir / ENV_FILE
    write_env(env_file, stack_values(project, run_dir, os.getuid(), scenario, host_ports))
    base = compose(project, env_file, args.file)
    steps = (
        (
            "postgres and questdb",
            ["--profile", "core", "up", "-d", "--wait", "postgres", "questdb"],
        ),
        ("schema", ["--profile", "core", "--profile", "migrate", "run", "--rm", "migrate"]),
        ("fixture-init", ["--profile", "fixture-init", "run", "--rm", "--no-deps", "fixture-init"]),
        ("api", ["--profile", "core", "up", "-d", "--wait", "api"]),
    )
    for name, step in steps:
        print(f"account-fixture-stack: {project}: {name}", flush=True)
        status = call([*base, *step], env)
        if status != 0:
            raise Refused(f"the {name} step exited {status}: take the project down")
    print(f"account-fixture-stack: up: {project}")
    return 0


def restart_api(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    """Recreate the api alone, with another stack default (`CV_ACCOUNT_FIXTURE`, decision 6)."""
    project = checked_project(args.project)
    if args.default is None or SCENARIO.fullmatch(args.default) is None:
        raise Refused("restart-api takes --default <scenario>, a scenario name")
    env_file = _env_file(project, environ)
    argv = [*compose(project, env_file, args.file), "--profile", "core", "up", "-d", "--no-deps"]
    status = call([*argv, "--force-recreate", "--wait", "api"],
                  docker_env(environ, CV_ACCOUNT_FIXTURE=args.default))  # fmt: skip
    if status != 0:
        raise Refused(f"the api did not come back healthy (exit {status})")
    print(f"account-fixture-stack: {project}: api restarted on {args.default}")
    return 0


def drive(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    """`python -m cvdev.account_fixture.drive` in the project's `fixture-drive` one-shot."""
    project = checked_project(args.project)
    env_file = _env_file(project, environ)
    argv = [*compose(project, env_file, args.file), "--profile", "fixture-drive", "run", "--rm"]
    return call([*argv, "--no-deps", "-T", "fixture-drive", *args.rest], docker_env(environ))


def down(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    """Everything of the project, by its name alone, then the run directory; idempotent."""
    project = checked_project(args.project)
    run_dir = run_root(environ) / project
    env = docker_env(environ)
    status = 0
    if any(leftovers(project, env).values()):
        with tempfile.TemporaryDirectory() as empty:  # with `-p` alone compose reads no file
            status = call(["docker", "compose", "-p", project, *TEARDOWN], env, cwd=empty)
    left = leftovers(project, env)
    counts = ", ".join(f"{len(names)} {kind}" for kind, names in left.items())
    if status != 0 or any(left.values()):
        kept = "run directory kept" if os.path.lexists(run_dir) else "no run directory"
        print(f"account-fixture-stack: down: {project}: {counts} left; {kept}: run down again")
        return 1
    print(f"account-fixture-stack: down: {project}: {counts} left; {remove_run_dir(run_dir)}")
    return 0


def remove_run_dir(run_dir: Path) -> str:
    """Unlink the flat run directory `up` made (its owner unlinks root's files in it), and say
    what happened; anything `up` never makes there is refused and left as it is."""
    if not os.path.lexists(run_dir):
        return "no run directory"
    if os.path.islink(run_dir) or not os.path.isdir(run_dir):
        raise Refused("the run directory is not the directory up made: check it by hand")
    names = sorted(os.listdir(run_dir))  # listed whole first: nothing is unlinked mid-listing
    if any(os.path.isdir(run_dir / name) and not os.path.islink(run_dir / name) for name in names):
        raise Refused("the run directory holds a directory, which up never makes: check it by hand")
    for name in names:
        os.unlink(run_dir / name)
    os.rmdir(run_dir)
    return "run directory removed"


def _env_file(project: str, environ: Mapping[str, str]) -> Path:
    env_file = run_root(environ) / project / ENV_FILE
    if not os.path.isfile(env_file):
        raise Refused("the project has no run directory here: bring it up first")
    return env_file


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="infra/scripts/account_fixture_stack.py",
        description="The account fixture's real-backend stack: up, restart-api, drive, down.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("up", "restart-api", "drive", "down"):
        sub = commands.add_parser(name)
        sub.add_argument("--project", required=name != "up", help="cv-acctfix-<6 hex digits>")
        sub.add_argument("-f", "--file", action="append", default=[], help="a lane-local file")
        if name in ("up", "restart-api"):
            fallback = DEFAULT_SCENARIO if name == "up" else None
            sub.add_argument("--default", default=fallback, help="the stack default scenario")
        if name == "up":
            sub.add_argument("--port", action="append", default=[], help="NAME=N, a host port")
        if name == "drive":
            sub.add_argument("rest", nargs=argparse.REMAINDER, help="the driver's arguments")
    return parser


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] = os.environ) -> int:
    args = _parser().parse_args(argv)
    if shutil.which("docker", path=environ.get("PATH")) is None:
        print("account-fixture-stack: refused: docker is not on PATH", file=sys.stderr)
        return EXIT_REFUSED
    if args.command == "drive" and args.rest[:1] == ["--"]:
        args.rest = args.rest[1:]
    handlers = {"up": up, "restart-api": restart_api, "drive": drive, "down": down}
    try:
        return handlers[args.command](args, environ)
    except Refused as refused:
        print(f"account-fixture-stack: refused: {refused}", file=sys.stderr)
        return EXIT_REFUSED
    except OSError as failure:  # its text may name a path: the class alone is shown
        print(
            f"account-fixture-stack: refused: {FAILED} ({type(failure).__name__})", file=sys.stderr
        )
        return EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
