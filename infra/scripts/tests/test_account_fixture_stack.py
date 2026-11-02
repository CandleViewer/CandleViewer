"""#2893's closure: `infra/scripts/account_fixture_stack.py`, run against a stub `docker`.

The script runs as a subprocess with a stub `docker` and nothing else on PATH, as
`test_demo_host_owner_first_run.py` runs its script, so no docker of the host's can answer: the stub
records each call's arguments, the names of the environment it got (and its `DOCKER_*` values) and
the directory it ran in, answers the label listings from the test's scenario (with nothing once a
`down` is logged, when the scenario says `clear_after_down`), and exits as the scenario says. A
listing is answered as docker answers it: the stub fills the call's `--format` (a name, or an
object's `cv.lane` label, bare or as `printf "%q"` prints it) and fails on a field docker has not,
so the lane label shows only when the script asks for it. No Docker, no network: the only socket
is a loopback bind the script makes to find free ports.
"""

from __future__ import annotations

import json
import os
import re
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
LABEL: Final = f"label=com.docker.compose.project={PROJECT}"
LANE: Final = "lane-a"
OTHER_LANE: Final = "lane-b"
#: What each listing prints after the object's name and a tab: its `cv.lane` label, quoted (`""`
#: when it has none), so an object is one line whatever its value holds.
QUOTED_LABEL: Final = '{{printf "%q" (.Label "cv.lane")}}'
#: The three listings that keep a command to the project's own objects, whole.
LISTINGS: Final = [
    ["ps", "-a", "--filter", LABEL, "--format", "{{.Names}}\t" + QUOTED_LABEL],
    ["network", "ls", "--filter", LABEL, "--format", "{{.Name}}\t" + QUOTED_LABEL],
    ["volume", "ls", "--filter", LABEL, "--format", "{{.Name}}\t" + QUOTED_LABEL],
]
#: One object of the project in each listing, as a scenario gives them (a bare name carries the
#: test's lane; `[name, lane]` carries that lane, and `""` no label at all).
OWN: Final = {
    "containers": [f"{PROJECT}-api-1"],
    "networks": [f"{PROJECT}_cv-internal"],
    "volumes": [f"{PROJECT}_cv-postgres-data"],
}
#: The two refusals the lane adds: each is one fixed line, never the lane's name.
LANE_LINE: Final = (
    "CV_ACCTFIX_LANE must be set to this lane's name: 1 to 63 of a-z, 0-9 and -, the first not -"
)
OTHER_LINE: Final = (
    "the project has an object that carries another lane's label, or none: it is not this lane's"
)
#: A lane label that is not the caller's: another lane's, a name that starts with the caller's, the
#: caller's in capitals, the caller's padded with a space, with a newline or a tab, none.
OTHER_OWNERS: Final = {
    "another-lane": OTHER_LANE,
    "a-longer-name": f"{LANE}2",
    "capitals": LANE.upper(),
    "padded": f" {LANE}",
    "a-newline": f"{LANE}\n",
    "a-tab": f"{LANE}\t",
    "no-label": "",
}
#: One object that is not this lane's, in a kind each, as the subprocess runs list it: another
#: lane's, none, a longer name, capitals, padded, and a value that holds a newline.
REFUSED_LISTINGS: Final = {
    "a-container-of-another-lane": ("containers", OTHER_LANE),
    "an-unlabelled-network": ("networks", ""),
    "a-volume-of-a-longer-name": ("volumes", f"{LANE}2"),
    "a-container-in-capitals": ("containers", LANE.upper()),
    "a-network-padded-with-a-space": ("networks", f" {LANE}"),
    "a-volume-whose-value-holds-a-newline": ("volumes", f"{LANE}\n "),
}
#: Each command's arguments, for the project `PROJECT`.
COMMANDS: Final = {
    "up": ["up", "--project", PROJECT],
    "restart-api": ["restart-api", "--project", PROJECT, "--default", "compliant"],
    "drive": ["drive", "--project", PROJECT, "--", "signin", "qa-owner-1"],
    "down": ["down", "--project", PROJECT],
}
#: The lines of a synthetic `stack.env` that does not name this lane, as a run directory made by
#: hand holds them: another lane's name, no lane line, an empty one, a longer name, the name
#: padded, two lane lines (this lane's and another's).
OTHER_ENVS: Final = {
    "another-lane": [f"CV_ACCTFIX_LANE={OTHER_LANE}"],
    "no-lane-line": [f"COMPOSE_PROJECT_NAME={PROJECT}", "CV_ACCOUNT_FIXTURE=compliant"],
    "an-empty-lane": ["CV_ACCTFIX_LANE="],
    "a-longer-name": [f"CV_ACCTFIX_LANE={LANE}2"],
    "padded": [f"CV_ACCTFIX_LANE= {LANE}"],
    "two-lane-lines": [f"CV_ACCTFIX_LANE={LANE}", f"CV_ACCTFIX_LANE={OTHER_LANE}"],
}
#: What the script prints for a file, socket or process call that fails (then the class's name).
FAILED_LINE: Final = "a file, socket or process call failed"
#: The refusal for a run directory whose `stack.env` is not this lane's: one fixed line.
RUN_DIR_LINE: Final = (
    "the run directory's stack.env names another lane, or none: it is not this lane's"
)
#: A `CV_ACCTFIX_LANE` the script refuses.
MALFORMED_LANES: Final = {
    "empty": "",
    "a-leading-hyphen": "-lane",
    "capitals": "Lane",
    "an-underscore": "lane_a",
    "a-dot": "lane.a",
    "a-space": "lane a",
    "a-path": "../lane",
    "non-ascii": "l\u00e4ne",
    "64-characters": "a" * 64,
    "a-trailing-newline": "lane-a\n",
    "a-newline-and-a-variable": "lane-a\nCV_PG_DSN=x",
}
#: `down`'s one compose call: the project name alone, no compose file, env file or profile.
TEARDOWN: Final = ["compose", "-p", PROJECT, "down", "-v", "--remove-orphans"]
PORT_NAMES: Final = (
    "POSTGRES_PORT",
    "QUESTDB_PG_PORT",
    "QUESTDB_ILP_PORT",
    "QUESTDB_HTTP_PORT",
    "CV_BIND_PORT",
)
#: The stub: logs its call to $HOME/docker.jsonl (HOME is one of the names the script keeps).
STUB: Final = """
import json, os, re, sys
home = os.environ["HOME"]
args = sys.argv[1:]
scenario = json.load(open(os.path.join(home, "scenario.json"), encoding="utf-8"))
record = {"args": args, "env": sorted(os.environ), "default": os.environ.get("CV_ACCOUNT_FIXTURE")}
record["docker"] = {k: v for k, v in os.environ.items() if k.startswith("DOCKER_")}
record |= {"cwd": os.getcwd(), "cwd_empty": not os.listdir(os.getcwd())}
logged = os.path.join(home, "docker.jsonl")
with open(logged, "a", encoding="utf-8") as log:
    log.write(json.dumps(record) + "\\n")
kind = {"ps": "containers", "network": "networks", "volume": "volumes"}.get(args[0])
if kind and "--filter" in args:
    with open(logged, encoding="utf-8") as log:
        calls = [json.loads(line)["args"] for line in log]
    gone = scenario.get("clear_after_down") and any("down" in call for call in calls)
    field = "Names" if kind == "containers" else "Name"
    shown = args[args.index("--format") + 1]
    lines = []
    for entry in [] if gone else scenario.get(kind, []):
        name, lane = (entry, scenario["lane"]) if isinstance(entry, str) else entry
        labels = {"cv.lane": lane} if lane else {}
        def fill(match):
            word = match.group(1).strip()
            asked = re.fullmatch('[.]Label "([^"]+)"', word)
            quoted = re.fullmatch('printf "%q" [(][.]Label "([^"]+)"[)]', word)
            if word == "." + field:
                return name
            if asked:
                return labels.get(asked.group(1), "")
            if quoted:
                return json.dumps(labels.get(quoted.group(1), ""), ensure_ascii=False)
            sys.exit("template: cannot evaluate " + word)
        lines.append(re.sub("[{][{](.*?)[}][}]", fill, shown))
    print("\\n".join(lines))
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
        listed = {"lane": LANE, **scenario}  # a bare name in a listing carries the test's lane
        (self.home / "scenario.json").write_text(json.dumps(listed), encoding="utf-8")

    def run(
        self, *args: str, lane: str | None = LANE, **extra_env: str
    ) -> subprocess.CompletedProcess[str]:
        """The script under the test's lane (`lane=None`: `CV_ACCTFIX_LANE` unset)."""
        env = {"PATH": str(self.bin), "HOME": str(self.home)}  # the stub alone answers `docker`
        env |= {"XDG_RUNTIME_DIR": str(self.runtime), "TMPDIR": str(self.tmp), **extra_env}
        if lane is not None:
            env["CV_ACCTFIX_LANE"] = lane
        return subprocess.run(  # noqa: S603 - this interpreter and the script under test
            [sys.executable, "-I", str(SCRIPT), *args],
            cwd=self.home,
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
        return [call["args"] for call in self.compose_records()]

    def compose_records(self) -> list[dict[str, Any]]:
        return [call for call in self.calls() if call["args"][:1] == ["compose"]]

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
    assert [call["args"] for call in host.calls()[:3]] == LISTINGS  # nothing left, first


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
    assert values["CV_ACCTFIX_LANE"] == LANE  # the overlay's `cv.lane` label reads it
    published = [values[name] for name in PORT_NAMES]
    assert all(port.isascii() and port.isdecimal() for port in published)
    assert len(set(published)) == len(PORT_NAMES)  # five distinct ports
    lines = [line for f in FILES for line in Path(f).read_text("utf-8").splitlines()]
    text = "\n".join(line for line in lines if not line.lstrip().startswith("#"))
    required = set(re.findall(r"\$\{([A-Z0-9_]+):\?", text))  # each file's `${NAME:?...}`
    required |= set(re.findall(r"^ +environment: ([A-Z0-9_]+)$", text, re.MULTILINE))  # secrets
    assert len(required) >= 15 and required <= set(values)
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


def test_down_goes_by_the_project_name_and_keeps_the_run_dir_until_nothing_is_left(
    tmp_path: Path,
) -> None:
    """`docker compose -p <project> down -v --remove-orphans` and nothing else (no compose file,
    env file or profile), from an empty directory. While the project's label still lists
    something, the run directory stays and `down` says to run it again; once nothing is listed it
    goes, root's files in it included; a third `down` finds neither and says so."""
    host = Host(tmp_path)
    assert host.run("up", "--project", PROJECT).returncode == 0
    run_dir = host.runtime / PROJECT
    (run_dir / "kek").write_bytes(b"x")  # what the one-shot leaves, here the test user's own
    host.scenario(volumes=[f"{PROJECT}_cv-postgres-data"])  # listed before and after down

    first = host.run("down", "--project", PROJECT)

    teardown = host.compose_records()[-1]
    assert teardown["args"] == TEARDOWN
    assert teardown["cwd_empty"] and Path(teardown["cwd"]).is_relative_to(host.tmp)
    assert [call["args"] for call in host.calls()[-3:]] == LISTINGS  # what is left, after
    assert first.returncode == 1 and (run_dir / "kek").exists()  # reported, not hidden
    kept = "0 containers, 0 networks, 1 volumes left; run directory kept: run down again"
    assert first.stdout == f"account-fixture-stack: down: {PROJECT}: {kept}\n"
    host.scenario()  # docker removed it
    calls_before = len(host.compose_calls())

    second = host.run("down", "--project", PROJECT)
    third = host.run("down", "--project", PROJECT)

    assert (second.returncode, third.returncode) == (0, 0) and not os.path.lexists(run_dir)
    assert len(host.compose_calls()) == calls_before  # nothing left to take down
    gone = "0 containers, 0 networks, 0 volumes left"
    assert (
        second.stdout == f"account-fixture-stack: down: {PROJECT}: {gone}; run directory removed\n"
    )
    assert third.stdout == f"account-fixture-stack: down: {PROJECT}: {gone}; no run directory\n"


def test_down_after_a_reboot_needs_no_run_dir_env_file_or_compose_file(tmp_path: Path) -> None:
    """After a reboot the tmpfs run directory is gone but the project's volumes are not: `down`
    still runs, by the project name alone, from an empty directory it then removes."""
    host = Host(tmp_path, volumes=[f"{PROJECT}_cv-postgres-data"])

    done = host.run("down", "--project", PROJECT)

    [teardown] = host.compose_records()
    assert teardown["args"] == TEARDOWN  # no -f, no --env-file: nothing to load or fill in
    assert teardown["cwd_empty"] and not Path(teardown["cwd"]).exists()
    assert done.stdout.endswith("1 volumes left; no run directory: run down again\n")


def test_a_failed_teardown_keeps_the_run_dir_and_is_retried_by_running_down_again(
    tmp_path: Path,
) -> None:
    host = Host(tmp_path)
    assert host.run("up", "--project", PROJECT).returncode == 0
    host.scenario(volumes=[f"{PROJECT}_cv-postgres-data"], exit={"down": 4})

    failed = host.run("down", "--project", PROJECT)

    assert failed.returncode == 1 and (host.runtime / PROJECT / "stack.env").exists()
    assert failed.stdout.endswith("run directory kept: run down again\n")
    host.scenario()  # the retry: compose answers, and nothing is listed after
    assert host.run("down", "--project", PROJECT).returncode == 0
    assert not os.path.lexists(host.runtime / PROJECT)


def test_a_compose_exit_alone_keeps_the_run_dir_though_nothing_is_listed_after(
    tmp_path: Path,
) -> None:
    """The compose half of `down`'s failure, apart from the listing's: the label lists a volume,
    compose exits 4, and the listings after it are empty (`clear_after_down`). The exit status
    alone ends `down` with exit 1, the run directory kept and the line that says to run it again;
    the next `down` finds nothing left and removes the directory."""
    host = Host(tmp_path)
    assert host.run("up", "--project", PROJECT).returncode == 0
    host.scenario(volumes=[f"{PROJECT}_cv-postgres-data"], exit={"down": 4}, clear_after_down=True)

    failed = host.run("down", "--project", PROJECT)

    assert host.compose_calls()[-1] == TEARDOWN  # compose ran, and exited 4
    assert [call["args"] for call in host.calls()[-3:]] == LISTINGS  # and listed nothing after
    kept = "0 containers, 0 networks, 0 volumes left; run directory kept: run down again"
    assert failed.stdout == f"account-fixture-stack: down: {PROJECT}: {kept}\n"
    assert failed.returncode == 1 and (host.runtime / PROJECT / "stack.env").exists()
    assert host.run("down", "--project", PROJECT).returncode == 0  # the retry: nothing is left
    assert not os.path.lexists(host.runtime / PROJECT)


def test_down_takes_no_file_option(tmp_path: Path) -> None:
    """`down` goes by the project name alone and reads no compose file, so it has no `-f`: a
    command line that gives one is refused as an unknown option, with no docker call, and the
    run directory stays as it was."""
    host = Host(tmp_path)
    assert host.run("up", "--project", PROJECT).returncode == 0
    calls_before = len(host.calls())

    done = host.run("down", "--project", PROJECT, "-f", "lane-net.yml")

    assert (done.returncode, done.stdout) == (2, "")
    assert "unrecognized arguments: -f lane-net.yml" in done.stderr
    assert len(host.calls()) == calls_before and (host.runtime / PROJECT / "stack.env").exists()


@pytest.mark.parametrize("kind", ["symlink", "subdirectory"])
def test_down_leaves_a_run_dir_up_never_made_and_says_so(tmp_path: Path, kind: str) -> None:
    """The run directory is flat and real: a link in its place, or a directory in it, is
    refused with one fixed line and left as it is, never followed or half removed."""
    host = Host(tmp_path)
    run_dir, elsewhere = host.runtime / PROJECT, tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "kept").write_text("kept", encoding="utf-8")
    if kind == "symlink":
        run_dir.symlink_to(elsewhere)
        line = "the run directory is not the directory up made: check it by hand"
    else:
        assert host.run("up", "--project", PROJECT).returncode == 0
        (run_dir / "sub").mkdir()
        line = "the run directory holds a directory, which up never makes: check it by hand"

    done = host.run("down", "--project", PROJECT)

    assert (done.returncode, done.stderr) == (2, f"account-fixture-stack: refused: {line}\n")
    assert (elsewhere / "kept").exists() and os.path.lexists(run_dir)
    assert kind == "symlink" or (run_dir / "stack.env").exists()


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


@pytest.mark.parametrize(
    ("word", "kind"), [("ps", "containers"), ("network", "networks"), ("volume", "volumes")]
)
def test_a_listing_docker_does_not_answer_stops_up_and_down(
    tmp_path: Path, word: str, kind: str
) -> None:
    """The label listings keep `up` and `down` to the project's own objects: one that fails is a
    refusal, never read as nothing left."""
    host = Host(tmp_path, exit={word: 1})

    for command in ("up", "down"):
        done = host.run(command, "--project", PROJECT)
        refused = f"account-fixture-stack: refused: docker did not list the project's {kind}\n"
        assert (done.returncode, done.stdout, done.stderr) == (2, "", refused), command

    assert host.compose_calls() == [] and list(host.runtime.iterdir()) == []


def _hand_made_run_dir(host: Host, *lines: str) -> Path:
    """A run directory made by hand under the host's run root, with a synthetic `stack.env` of
    these lines (never a real file's): no `up` ran, so no Docker object exists for it."""
    run_dir = host.runtime / PROJECT
    run_dir.mkdir(mode=0o700)
    (run_dir / "stack.env").write_text("".join(f"{line}\n" for line in lines), encoding="ascii")
    return run_dir


def _printed(label: str) -> str:
    """A label value as `printf "%q"` prints it, which for these values is JSON's quoting."""
    return json.dumps(label, ensure_ascii=False)


def _listed(kind: str, owner: str) -> dict[str, Any]:
    """Every kind lists one object of this lane, but `kind`'s, which carries `owner` as its lane
    label (`""`: no label at all)."""
    return {k: ([[names[0], owner]] if k == kind else list(names)) for k, names in OWN.items()}


def test_the_listings_ask_for_each_objects_lane_label(tmp_path: Path) -> None:
    """Each listing of `up` and `down` (`down` lists before the teardown and after it) is the
    project's compose label and prints the name and the `cv.lane` label: nothing else."""
    host = Host(tmp_path)
    assert host.run("up", "--project", PROJECT).returncode == 0
    host.scenario(**OWN, clear_after_down=True)
    assert host.run("down", "--project", PROJECT).returncode == 0

    listed = [call["args"] for call in host.calls() if call["args"][:1] != ["compose"]]

    assert listed == LISTINGS * 3
    assert all(args[-1].endswith("\t" + QUOTED_LABEL) for args in listed)


@pytest.mark.parametrize("command", ["up", "restart-api", "drive", "down"])
@pytest.mark.parametrize("lane", [None, "Lane-A"], ids=["unset", "malformed"])
def test_every_command_refuses_a_lane_that_is_unset_or_malformed(
    tmp_path: Path, command: str, lane: str | None
) -> None:
    """The script takes the lane from `CV_ACCTFIX_LANE` and refuses a command without a lane:
    exit 2, one fixed line that never shows the value, no docker call, no run directory."""
    host = Host(tmp_path)

    done = host.run(*COMMANDS[command], lane=lane)

    assert (done.returncode, done.stdout) == (2, "")
    assert done.stderr == f"account-fixture-stack: refused: {LANE_LINE}\n"
    assert host.calls() == [] and list(host.runtime.iterdir()) == []


@pytest.mark.parametrize("lane", ["a", "0", "lane-1", "a-" * 31 + "a", "a" * 63])
def test_a_lane_name_is_1_to_63_of_a_z_0_9_and_hyphen_the_first_not_a_hyphen(lane: str) -> None:
    stack = _stack()
    assert stack.checked_lane({"CV_ACCTFIX_LANE": lane}) == lane
    with pytest.raises(stack.Refused, match="must be set to this lane's name"):
        stack.checked_lane({})  # unset


@pytest.mark.parametrize("case", MALFORMED_LANES)
def test_a_malformed_lane_is_one_fixed_line_and_never_shown(case: str) -> None:
    """A trailing newline is no lane (`fullmatch`, not `$`): it would put another line into the
    env file `up` writes."""
    stack, lane = _stack(), MALFORMED_LANES[case]

    with pytest.raises(stack.Refused) as refused:
        stack.checked_lane({"CV_ACCTFIX_LANE": lane})

    assert str(refused.value) == LANE_LINE and (not lane or lane not in str(refused.value))


def test_up_writes_the_lane_it_runs_under_into_stack_env(tmp_path: Path) -> None:
    host = Host(tmp_path)
    lane = "z" + "-y" * 31  # 63 characters, the longest a lane name is

    done = host.run("up", "--project", PROJECT, lane=lane)

    assert done.returncode == 0, done.stderr
    assert host.env_values()["CV_ACCTFIX_LANE"] == lane


@pytest.mark.parametrize("kind", list(OWN))
@pytest.mark.parametrize("owner", OTHER_OWNERS.values(), ids=list(OTHER_OWNERS))
def test_a_listed_object_of_another_lane_or_none_is_refused(kind: str, owner: str) -> None:
    """Any one object, of any kind, with a lane label that is not this lane's exactly (another
    lane's, a longer name, the capitals, none) refuses the whole project; this lane's alone pass."""
    stack = _stack()
    found = {k: [(names[0], _printed(LANE))] for k, names in OWN.items()}
    stack.lane_only(found, LANE)
    found[kind].append((f"{kind}-2", _printed(owner)))

    with pytest.raises(stack.Refused) as refused:
        stack.lane_only(found, LANE)

    assert str(refused.value) == OTHER_LINE


def test_a_label_docker_did_not_quote_is_not_this_lanes() -> None:
    """The listings ask for the label quoted, so this lane's is its name in double quotes: a bare
    name is output docker should not have printed, and fails closed."""
    stack = _stack()

    stack.lane_only({"volumes": [("v", f'"{LANE}"')]}, LANE)
    with pytest.raises(stack.Refused, match="another lane's label, or none"):
        stack.lane_only({"volumes": [("v", LANE)]}, LANE)


@pytest.mark.parametrize("case", REFUSED_LISTINGS)
def test_down_refuses_a_project_that_is_not_wholly_this_lanes_and_changes_nothing(
    tmp_path: Path, case: str
) -> None:
    """Exit 2 and one fixed line, before any compose call, the run directory kept as it was;
    running `down` again changes nothing (the listings are the only calls it makes)."""
    host = Host(tmp_path)
    assert host.run("up", "--project", PROJECT).returncode == 0
    host.scenario(**_listed(*REFUSED_LISTINGS[case]))
    run_dir = host.runtime / PROJECT
    kept = sorted(path.name for path in run_dir.iterdir())
    compose_before = len(host.compose_calls())

    first = host.run("down", "--project", PROJECT)
    second = host.run("down", "--project", PROJECT)

    refused = f"account-fixture-stack: refused: {OTHER_LINE}\n"
    assert [(d.returncode, d.stdout, d.stderr) for d in (first, second)] == [(2, "", refused)] * 2
    assert len(host.compose_calls()) == compose_before  # compose was never called
    assert sorted(path.name for path in run_dir.iterdir()) == kept
    assert [call["args"] for call in host.calls()[-6:]] == LISTINGS * 2  # all each `down` ran


def test_down_takes_a_project_down_when_every_object_of_it_carries_this_lane(
    tmp_path: Path,
) -> None:
    host = Host(tmp_path)
    assert host.run("up", "--project", PROJECT).returncode == 0
    host.scenario(**OWN, clear_after_down=True)  # a container, a network and a volume of this lane

    done = host.run("down", "--project", PROJECT)

    gone = "0 containers, 0 networks, 0 volumes left; run directory removed"
    said = f"account-fixture-stack: down: {PROJECT}: {gone}\n"
    assert (done.returncode, done.stdout) == (0, said)
    assert host.compose_calls()[-1] == TEARDOWN and not os.path.lexists(host.runtime / PROJECT)


@pytest.mark.parametrize("case", REFUSED_LISTINGS)
def test_up_refuses_a_project_whose_leftovers_carry_another_lane_or_none(
    tmp_path: Path, case: str
) -> None:
    """The same line as `down`'s, not the one for this lane's own leftovers (`take it down first`),
    with no compose call and no run directory."""
    host = Host(tmp_path, **_listed(*REFUSED_LISTINGS[case]))

    done = host.run("up", "--project", PROJECT)

    refused = f"account-fixture-stack: refused: {OTHER_LINE}\n"
    assert (done.returncode, done.stdout, done.stderr) == (2, "", refused)
    assert [call["args"] for call in host.calls()] == LISTINGS
    assert list(host.runtime.iterdir()) == []


@pytest.mark.parametrize("command", ["restart-api", "drive"])
@pytest.mark.parametrize("case", ["a-container-of-another-lane", "an-unlabelled-network"])
def test_restart_api_and_drive_refuse_a_project_that_is_not_wholly_this_lanes(
    tmp_path: Path, command: str, case: str
) -> None:
    """`restart-api` would force-recreate another lane's api and `drive` would run in its network:
    each lists the project first and refuses it as `down` does, exit 2 and one fixed line, and
    never reaches compose (the three listings are all it runs)."""
    host = Host(tmp_path)
    assert host.run("up", "--project", PROJECT).returncode == 0
    host.scenario(**_listed(*REFUSED_LISTINGS[case]))
    calls_before = len(host.calls())

    done = host.run(*COMMANDS[command])

    refused = f"account-fixture-stack: refused: {OTHER_LINE}\n"
    assert (done.returncode, done.stdout, done.stderr) == (2, "", refused)
    assert [call["args"] for call in host.calls()[calls_before:]] == LISTINGS


@pytest.mark.parametrize("command", ["down", "restart-api", "drive"])
@pytest.mark.parametrize("case", OTHER_ENVS)
def test_a_run_dir_whose_stack_env_names_another_lane_or_none_is_refused(
    tmp_path: Path, command: str, case: str
) -> None:
    """No Docker object is listed, so the check on the objects passes: the run directory's own
    `stack.env` says whose it is. Exit 2 and one fixed line that shows neither the file's value nor
    this lane's name, no docker call at all (the directory is judged first), the directory as it
    was; run again, the same."""
    host = Host(tmp_path)
    run_dir = _hand_made_run_dir(host, *OTHER_ENVS[case])
    before = {path.name: path.read_bytes() for path in run_dir.iterdir()}

    first = host.run(*COMMANDS[command])
    second = host.run(*COMMANDS[command])

    refused = f"account-fixture-stack: refused: {RUN_DIR_LINE}\n"
    assert [(d.returncode, d.stdout, d.stderr) for d in (first, second)] == [(2, "", refused)] * 2
    assert host.calls() == []
    assert {path.name: path.read_bytes() for path in run_dir.iterdir()} == before
    assert LANE not in first.stderr and OTHER_LANE not in first.stderr


@pytest.mark.parametrize("command", ["down", "restart-api", "drive"])
def test_a_run_dir_whose_stack_env_names_this_lane_is_used_as_before(
    tmp_path: Path, command: str
) -> None:
    host = Host(tmp_path)
    lines = (f"COMPOSE_PROJECT_NAME={PROJECT}", f"CV_ACCTFIX_LANE={LANE}", "CV_ACCOUNT_FIXTURE=x")
    run_dir = _hand_made_run_dir(host, *lines)

    done = host.run(*COMMANDS[command])

    assert done.returncode == 0, done.stderr
    if command == "down":  # nothing is listed: no teardown, and the directory goes
        assert host.compose_calls() == [] and not os.path.lexists(run_dir)
    else:  # the three listings, then the one compose call
        assert [call["args"] for call in host.calls()[:3]] == LISTINGS
        assert len(host.compose_calls()) == 1


def test_a_run_dir_with_no_stack_env_is_treated_as_before(tmp_path: Path) -> None:
    """There is no lane to compare: `restart-api` and `drive` say to bring the project up first
    (exit 2, no compose call), and `down`, with nothing of the project listed, removes it."""
    host = Host(tmp_path)
    run_dir = host.runtime / PROJECT
    run_dir.mkdir(mode=0o700)
    (run_dir / "left-behind").write_text("synthetic", encoding="ascii")

    said = (
        "account-fixture-stack: refused: the project has no run directory here: bring it up first"
    )
    for command in ("restart-api", "drive"):
        done = host.run(*COMMANDS[command])
        assert (done.returncode, done.stdout, done.stderr) == (2, "", said + "\n")
    assert host.compose_calls() == [] and (run_dir / "left-behind").exists()
    down = host.run(*COMMANDS["down"])

    assert down.returncode == 0 and not os.path.lexists(run_dir)


@pytest.mark.parametrize("command", ["down", "restart-api", "drive"])
def test_a_stack_env_that_is_a_link_is_not_followed(tmp_path: Path, command: str) -> None:
    """The file is opened without following a link: one fixed line naming the exception's class,
    nothing of the file read, no docker call, the directory as it was."""
    host = Host(tmp_path)
    run_dir = host.runtime / PROJECT
    run_dir.mkdir(mode=0o700)
    target = tmp_path / "elsewhere"
    target.write_text(f"CV_ACCTFIX_LANE={LANE}\n", encoding="ascii")  # this lane, behind a link
    (run_dir / "stack.env").symlink_to(target)

    done = host.run(*COMMANDS[command])

    said = f"account-fixture-stack: refused: {FAILED_LINE} (OSError)\n"
    assert (done.returncode, done.stdout, done.stderr) == (2, "", said)
    assert host.calls() == [] and (run_dir / "stack.env").is_symlink()


def test_up_refuses_an_existing_run_dir_without_reading_it(tmp_path: Path) -> None:
    """`up` makes a run directory only where there is none and refuses one that is there, so it
    neither uses nor removes it: another lane's directory is refused as any other is, untouched."""
    host = Host(tmp_path)
    run_dir = _hand_made_run_dir(host, *OTHER_ENVS["another-lane"])

    done = host.run(*COMMANDS["up"])

    assert (done.returncode, done.stdout) == (2, "")
    assert done.stderr.startswith(
        "account-fixture-stack: refused: the run directory already exists"
    )
    assert host.calls() == [] and sorted(path.name for path in run_dir.iterdir()) == ["stack.env"]


#: `ENV_READ_BOUND`: the longest `stack.env` the reader takes whole (the test below pins it).
BOUND: Final = 65536


def _ending_at_the_bound(line: bytes) -> bytes:
    """Lines of `x`, then `line`, so that `line` starts a line and ends at byte `BOUND`."""
    return b"x" * (BOUND - len(line) - 1) + b"\n" + line


@pytest.mark.parametrize(
    ("content", "named"),
    [
        (b"CV_ACCTFIX_LANE=lane-a\n", True),
        (b"A=1\nCV_ACCTFIX_LANE=lane-a\nB=2\n", True),
        (b"CV_ACCTFIX_LANE=lane-a", True),
        (b"CV_ACCTFIX_LANE=lane-a\r\nB=2\r\n", True),
        (b"", False),
        (b"B=2\n", False),
        (b"CV_ACCTFIX_LANE=\n", False),
        (b"CV_ACCTFIX_LANE=lane-b\n", False),
        (b"CV_ACCTFIX_LANE=lane-a2\n", False),
        (b"CV_ACCTFIX_LANE=lane-\n", False),
        (b"CV_ACCTFIX_LANE= lane-a\n", False),
        (b"CV_ACCTFIX_LANE=lane-a \n", False),
        (b"CV_ACCTFIX_LANE=lane-a\xff\n", False),
        (b'CV_ACCTFIX_LANE="lane-a"\n', False),
        (b" CV_ACCTFIX_LANE=lane-a\n", False),
        (b"\xff\xfeCV_ACCTFIX_LANE=lane-a\n", False),
        (b"CV_ACCTFIX_LANE=lane-a\nCV_ACCTFIX_LANE=lane-a\n", False),
        (b"CV_ACCTFIX_LANE=lane-a\nCV_ACCTFIX_LANE=lane-b\n", False),
        (b"CV_ACCTFIX_LANE=lane-b\nCV_ACCTFIX_LANE=lane-a\n", False),
        (b"x" * 65536 + b"\nCV_ACCTFIX_LANE=lane-a\n", False),
        pytest.param(
            _ending_at_the_bound(b"CV_ACCTFIX_LANE=lane-a\n"),
            True,
            id="exactly-the-bound-ending-in-this-lane",
        ),
        pytest.param(
            _ending_at_the_bound(b"CV_ACCTFIX_LANE=lane-a") + b"2\n",
            False,
            id="lane-line-straddles-the-bound",
        ),
        pytest.param(
            b"CV_ACCTFIX_LANE=lane-a\n" + b"x" * 65536 + b"\nCV_ACCTFIX_LANE=lane-b\n",
            False,
            id="second-lane-line-past-the-bound",
        ),
    ],
    ids=lambda value: value[:26].decode("ascii", "replace") if isinstance(value, bytes) else None,
)
def test_names_lane_is_yes_only_when_the_one_lane_line_names_it(
    tmp_path: Path, content: bytes, named: bool
) -> None:
    """The reader's whole answer is a boolean: exactly one line starting `CV_ACCTFIX_LANE=`, equal
    to this lane's, in a file of at most the bound. A longer file is not read whole, so it names
    no lane, wherever its lane line sits: the bound can cut one line short (`lane-a2` read as
    `lane-a`) or leave the second of two lines unread."""
    env_file = tmp_path / "stack.env"
    env_file.write_bytes(content)

    assert _stack().ENV_READ_BOUND == BOUND
    assert _stack().names_lane(env_file, LANE) is named


def test_names_lane_reads_the_stack_env_up_writes_whole(tmp_path: Path) -> None:
    """The file `up` writes, whole, is within the bound and names this lane: the bound refuses
    only what `up` does not write."""
    host = Host(tmp_path)
    done = host.run("up", "--project", PROJECT)
    env_file = host.runtime / PROJECT / "stack.env"

    assert done.returncode == 0, done.stderr
    assert 0 < env_file.stat().st_size <= BOUND
    assert _stack().names_lane(env_file, LANE) is True


#: `up`'s refusals before any docker call: the arguments after `up --project P`, the case's
#: environment, and the start of its one line (`{port}` is a free port).
UP_REFUSALS: Final[dict[str, tuple[tuple[str, ...], str]]] = {
    "a-second-up-of-one-project": ((), "the run directory already exists"),
    "a-default-with-a-newline": (("--default", "compliant\nCV_PG_DSN=x"), "the default scenario"),
    "a-default-with-a-path": (("--default", "../compliant"), "the default scenario must be"),
    "no-docker-on-path": ((), "docker is not on PATH"),
    "a-port-of-an-unknown-name": (("--port", "REDIS_PORT=6379"), "--port takes NAME=N"),
    "a-port-not-a-number": (("--port", "POSTGRES_PORT=x"), "--port takes NAME=N"),
    "a-port-of-a-superscript-digit": (("--port", "POSTGRES_PORT=5\u00b2"), "--port takes NAME=N"),
    "two-ports-alike": (
        ("--port", "POSTGRES_PORT={port}", "--port", "CV_BIND_PORT={port}"),
        "each --port must name a port of its own",
    ),
}


@pytest.mark.parametrize("case", UP_REFUSALS)
def test_up_refuses_before_any_docker_call(tmp_path: Path, case: str) -> None:
    """Each refusal is exit 2 and one fixed line, with no docker call; a scenario name never
    carries a newline into the env file, and a port is ASCII digits."""
    host = Host(tmp_path)
    args, line = UP_REFUSALS[case]
    if case == "a-second-up-of-one-project":
        assert host.run("up", "--project", PROJECT).returncode == 0
    env = {"PATH": str(host.tmp)} if case == "no-docker-on-path" else {}
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = str(probe.getsockname()[1])
    calls_before = len(host.calls())

    done = host.run("up", "--project", PROJECT, *(a.format(port=port) for a in args), **env)

    assert (done.returncode, done.stdout) == (2, "")
    assert done.stderr.startswith(f"account-fixture-stack: refused: {line}")
    assert done.stderr.count("\n") == 1 and len(host.calls()) == calls_before


def test_a_file_error_is_one_fixed_line_naming_its_class(tmp_path: Path) -> None:
    """A file, socket or process call that fails ends as one line naming the exception's class,
    never its text (which names a path): here a run root `up` cannot write."""
    if os.geteuid() == 0:
        pytest.skip("root writes a directory of any mode")
    host = Host(tmp_path)
    host.runtime.chmod(0o500)
    try:
        done = host.run("up", "--project", PROJECT)
    finally:
        host.runtime.chmod(0o700)

    failed = "a file, socket or process call failed (PermissionError)"
    assert (done.returncode, done.stdout) == (2, "")
    assert done.stderr == f"account-fixture-stack: refused: {failed}\n"
    assert host.compose_calls() == [] and list(host.runtime.iterdir()) == []


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
    caller's shell would steer the stack, so docker gets PATH, HOME and DOCKER_* alone; the
    caller's daemon (`DOCKER_HOST`, `DOCKER_CONTEXT`) reaches every call."""
    host = Host(tmp_path)
    daemon = {"DOCKER_HOST": "unix:///run/lane/docker.sock", "DOCKER_CONTEXT": "lane"}

    done = host.run(
        "up", "--project", PROJECT, CV_PG_DSN="postgresql://x", COMPOSE_FILE="x.yml", **daemon
    )

    assert done.returncode == 0, done.stderr
    names = {name for call in host.calls() for name in call["env"]}
    assert names <= {"PATH", "HOME", "LC_CTYPE", *daemon}  # the stub's python may set LC_CTYPE
    assert all(call["docker"] == daemon for call in host.calls())


def test_restart_api_recreates_the_api_alone_with_the_new_default(tmp_path: Path) -> None:
    host = Host(tmp_path)
    assert host.run("up", "--project", PROJECT).returncode == 0
    host.scenario(**OWN)  # this lane's container, network and volume: taken, after the listings

    done = host.run("restart-api", "--project", PROJECT, "--default", "demo_ws_unreachable")

    assert done.returncode == 0, done.stderr
    assert [call["args"] for call in host.calls()[-4:-1]] == LISTINGS
    last = host.calls()[-1]
    base = _compose(PROJECT, str(host.runtime / PROJECT / "stack.env"))
    tail = ["--profile", "core", "up", "-d", "--no-deps", "--force-recreate", "--wait", "api"]
    assert last["args"] == [*base, *tail]
    assert last["default"] == "demo_ws_unreachable"
    assert host.run("restart-api", "--project", PROJECT, "--default", "../x").returncode == 2


def test_drive_runs_the_driver_in_its_one_shot_and_returns_its_status(tmp_path: Path) -> None:
    host = Host(tmp_path)
    assert host.run("up", "--project", PROJECT).returncode == 0
    host.scenario(**OWN, exit={"fixture-drive": 3})  # this lane's objects, listed, then taken

    done = host.run("drive", "--project", PROJECT, "--", "call", "qa-owner-1", "GET", "/me")

    assert [call["args"] for call in host.calls()[-4:-1]] == LISTINGS
    base = _compose(PROJECT, str(host.runtime / PROJECT / "stack.env"))
    run = ["--profile", "fixture-drive", "run", "--rm", "--no-deps", "-T", "fixture-drive"]
    assert host.compose_calls()[-1] == [*base, *run, "call", "qa-owner-1", "GET", "/me"]
    assert done.returncode == 3


def _stack() -> Any:
    """The script as a module, for its pure parts."""
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import account_fixture_stack as stack
    finally:
        sys.path.remove(str(SCRIPT.parent))
    return stack


def test_the_free_ports_are_drawn_again_until_the_five_differ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stack = _stack()
    draws = iter([5001, 5001, 5002, 5003, 5004, 6001, 6002, 6003, 6004, 6005])
    monkeypatch.setattr(stack, "free_port", lambda: next(draws))

    assert list(stack.ports([]).values()) == ["6001", "6002", "6003", "6004", "6005"]
    monkeypatch.setattr(stack, "free_port", lambda: 5001)
    with pytest.raises(stack.Refused, match="no five distinct free ports"):
        stack.ports([])


def test_the_run_dir_is_the_users_tmpfs_else_dev_shm(tmp_path: Path) -> None:
    stack = _stack()

    assert stack.run_root({"XDG_RUNTIME_DIR": str(tmp_path)}) == tmp_path
    shm = Path("/dev/shm")  # noqa: S108 - the fallback the script names, never written here
    assert stack.run_root({"XDG_RUNTIME_DIR": "relative"}) == shm
    assert stack.run_root({}) == shm
