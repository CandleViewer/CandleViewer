"""Tests for infra/scripts/demo_host_owner_first_run.sh (#3180): the Owner's first run.

The script runs under bash with stubs first on PATH: `docker` (`stub_docker.py`), `curl`
(`stub_curl.py`) and a `python3` that records its arguments; from an empty working directory, HOME
and TMPDIR, with no terminal; stdin holds the answers to its prompts. One run also goes on a real
pty (`on_a_terminal`), where bash's silent reads take effect: what reaches the terminal is checked
there. No network and no Docker.
The bootstrap is #4479's CLI in the overlay's `bootstrap-owner` service (DC-4479-02), as its design
note describes it: #4479 is not merged. The curl stub answers in the shapes the served code gives
(`api/invites.py`, `api/auth.py`, `api/step_up.py`, `api/exchange_accounts.py`,
`api/exchange_keys.py`). Every request is held to docs/plan/22-api-openapi.yaml: the operation's
method and path, and its body against the operation's request schema.
"""

from __future__ import annotations

import functools
import json
import os
import pty
import re
import select
import shutil
import stat
import subprocess
import sys
import termios
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "infra" / "scripts" / "demo_host_owner_first_run.sh"
SPEC = REPO_ROOT / "docs" / "plan" / "22-api-openapi.yaml"
STUB = Path(__file__).with_name("stub_curl.py")
DOCKER = Path(__file__).with_name("stub_docker.py")
BASH = shutil.which("bash") or "/bin/bash"

# What the Owner types. All are secrets but the email, the identifier, the UID and the labels;
# the password holds a quote and a backslash, which the request config and the JSON body escape.
EMAIL = "owner@example.invalid"
TOKEN = "sentinel-invite-sentinel-invite"
PASSWORD = 'pwSentinel "quoted" back\\slash 42'
CODES = ("271828", "314159", "161803")
IDENTIFIER = "owner"
EXCHANGE_UID = "40321987"
API_KEY = "sentinel-apikey-sentinel"
API_SECRET = "sentinel-secret-sentinel-secret"
SECRETS = (TOKEN, PASSWORD, *CODES, API_KEY, API_SECRET)
# What the served code issues, and what the bootstrap CLI prints on its TTY.
ACCESS, CSRF = "accessServerIssued_AbCdEf", "csrfNonceServer.csrfMacServer"
ROTATED = {"access": "accessRotated_GhIjKl", "csrf": "csrfNonceRotated.csrfMacRotated"}
MFA_TOKEN = "mfaServerIssued_MnOpQr"
METHOD_ID = "11111111-2222-4333-8444-555555555555"
ACCOUNT_ID = "a1000000-0000-4000-8000-000000000001"
CHALLENGE_ID = "c1000000-0000-4000-8000-000000000002"
OTPAUTH = "otpauth://totp/CandleViewer:owner?secret=STUBSTUBSTUBSTUB&issuer=CandleViewer"
RECOVERY = tuple(f"rc{i:02d}-wxyz-{i:02d}ab" for i in range(10))
EGRESS = "egress-sentinel"  # where the served code puts the egress IP: never printed
CLI_PRINT = "bootstrap-cli-print-marker"  # stands for the CLI's TTY output, the token's line

#: (method, 22 path, operationId, needs the session): the calls of a full run, in order. The
#: served createExchangeAccount sits behind the `keys` step-up (api/step_up.py), so the step-up
#: comes first and its 5-minute window covers the account and the key.
ROUTES = (
    ("GET", "/invites/{inviteToken}", "getInvite", False),
    ("POST", "/invites/{inviteToken}", "redeemInvite", False),
    ("POST", "/invites/{inviteToken}/confirm", "confirmInvite", False),
    ("POST", "/auth/login", "authLogin", False),
    ("POST", "/auth/mfa/verify", "authMfaVerify", False),
    ("POST", "/auth/step-up", "authStepUp", True),
    ("POST", "/exchange-accounts", "createExchangeAccount", True),
    ("POST", "/exchange-accounts/{accountId}/keys", "createApiKey", True),
)
ORDER = [f"{method} {path}" for method, path, _, _ in ROUTES]
GET_INVITE, REDEEM, CONFIRM, LOGIN, VERIFY, STEP_UP, CREATE, IMPORT = ORDER
CURL_ARGV = ["-q", "--silent", "--noproxy", "*", "--proto", "=http", "--max-time", "60",
             "--dump-header", "-", "--write-out", "\\n%{http_code}", "--config", "-"]  # fmt: skip
#: The runbook's compose files and project, as the script names them.
COMPOSE = ["compose", "-p", "cv-demo"] + [
    arg for name in ("docker-compose.yml", "docker-compose.vps.yml", "docker-compose.demo-host.yml")
    for arg in ("-f", str(REPO_ROOT / "infra" / "compose" / name))
]  # fmt: skip
BOOTSTRAP = [
    [*COMPOSE, "stop", "api"],
    [*COMPOSE, "--profile", "bootstrap-owner", "run", "--rm", "--no-deps", "bootstrap-owner",
     "--owner", EMAIL],
    [*COMPOSE, "--profile", "core", "up", "-d", "--wait", "api"],
]  # fmt: skip
#: L5, F10: the command that starts api again, as a run that stopped it prints it.
UP_API = " ".join(["docker", *BOOTSTRAP[2]])
#: L7: the key import, which signs against the exchange, may take 120 s; every other call 60.
IMPORT_ARGV = [*CURL_ARGV[:7], "120", *CURL_ARGV[8:]]
#: The prompts of a full run, in order (blank: the default label, label and read-only answer).
ANSWERS = [EMAIL, TOKEN, PASSWORD, PASSWORD, CODES[0], CODES[1], EXCHANGE_UID, "", "", "",
           API_KEY, API_SECRET, CODES[2]]  # fmt: skip
VERDICT = {
    "passed": True, "uid": EXCHANGE_UID, "uta": True, "read_only": False,
    "withdraw_enabled": False, "permissions": {"ContractTrade": ["Order", "Position"]},
    "ip_whitelist": [EGRESS], "egress_ip": EGRESS, "warnings": [],
    "ip_whitelist_matches_egress": True, "probe_ret_code": 0, "clock_offset_ms": 12,
}  # fmt: skip
#: L6: no `uid`, which the Owner typed and `passed` already holds to the key's.
VERDICT_LINES = [
    "passed: true", "uta: true", "read_only: false", "withdraw_enabled: false",
    "ip_whitelist_matches_egress: true", "warnings: -", "probe_ret_code: 0", "clock_offset_ms: 12",
]  # fmt: skip


@functools.cache
def spec() -> dict[str, Any]:
    text = SPEC.read_text(encoding="utf-8")
    if hasattr(yaml, "CSafeLoader"):  # libyaml: about a second for the 1 MB contract
        loaded: dict[str, Any] = yaml.load(text, Loader=yaml.CSafeLoader)
        return loaded
    slow: dict[str, Any] = yaml.safe_load(text)
    return slow


def operation(operation_id: str) -> tuple[str, str, dict[str, Any]]:
    for path, item in spec()["paths"].items():
        for method, op in item.items():
            if isinstance(op, dict) and op.get("operationId") == operation_id:
                return method.upper(), path, op
    raise KeyError(operation_id)


@functools.cache
def request_schema(operation_id: str) -> dict[str, Any] | None:
    """The operation's JSON request body schema, with the components it refers to."""
    body = operation(operation_id)[2].get("requestBody")
    if body is None:
        return None
    schema: dict[str, Any] = body["content"]["application/json"]["schema"]
    needed: dict[str, Any] = {}
    todo: list[Any] = [schema]
    while todo:
        node = todo.pop()
        if isinstance(node, dict):
            ref = node.get("$ref", "")
            name = ref.removeprefix("#/components/schemas/")
            if ref != name and name not in needed:
                needed[name] = spec()["components"]["schemas"][name]
                todo.append(needed[name])
            todo.extend(node.values())
        elif isinstance(node, list):
            todo.extend(node)
    dialect = "https://json-schema.org/draft/2020-12/schema"
    return {"$schema": dialect, **schema, "components": {"schemas": needed}}


def answer(status: int, body: Any = None, **extra: Any) -> dict[str, Any]:
    return {"status": status, "body": body, **extra}


def problem(status: int, code: str, detail: str, **extra: Any) -> dict[str, Any]:
    return answer(status, {"type": "about:blank", "status": status, "code": code,
                           "title": code, "detail": detail, **extra})  # fmt: skip


def full_run() -> dict[str, list[dict[str, Any]]]:
    """Each route's calls in order: what the request must carry and the served answer."""
    invite = {"inviteToken": TOKEN}
    signed_in = {
        "status": "authenticated",
        "tokens": {"access_token": ACCESS, "token_type": "Bearer", "expires_in": 600},
        "user": {"id": "u1000000-0000-4000-8000-000000000003", "roles": ["owner"]},
    }
    account = {"id": ACCOUNT_ID, "exchange": "bybit", "environment": "demo", "kind": "main",
               "label": "Bybit demo main", "exchange_uid": EXCHANGE_UID,
               "parent_account_id": None, "connection_state": "pending",
               "key_status": "missing"}  # fmt: skip
    elevated = {"elevated_until": "2026-10-26T04:05:00+00:00", "action_class": "keys",
                "single_use": False, "step_up_expires_at": "2026-10-26T04:05:00+00:00"}  # fmt: skip
    key = {"id": "k1000000-0000-4000-8000-000000000004", "status": "active",
           "key_id_masked": "****ab42"}  # fmt: skip
    return {
        GET_INVITE: [answer(200, {"display_name": "Owner", "role": "viewer",
                                  "expires_at": "2026-10-28T04:00:00+00:00"}, path=invite)],
        REDEEM: [answer(200, {"method_id": METHOD_ID, "otpauth_uri": OTPAUTH,
                              "secret_base32": "STUBSTUBSTUBSTUB"},
                        path=invite, expect={"password": PASSWORD})],
        CONFIRM: [answer(200, {"status": "active", "role": "owner",
                               "recovery_codes": list(RECOVERY)},
                         path=invite, expect={"method_id": METHOD_ID, "code": CODES[0]})],
        LOGIN: [answer(200, {"status": "mfa_required", "mfa_token": MFA_TOKEN,
                             "methods": ["totp"], "expires_in": 300},
                       expect={"identifier": EMAIL, "password": PASSWORD})],
        VERIFY: [answer(200, signed_in, cookies={"cv_refresh": "refreshServerIssued",
                                                 "__Host-cv_csrf": CSRF},
                        session={"access": ACCESS, "csrf": CSRF},
                        expect={"mfa_token": MFA_TOKEN, "method": "totp", "code": CODES[1]})],
        STEP_UP: [answer(200, elevated, expect={"password": PASSWORD, "code": CODES[2],
                                                "action_class": "keys"})],
        CREATE: [answer(201, account, expect={k: account[k] for k in (
            "exchange", "environment", "kind", "label", "exchange_uid")})],
        IMPORT: [answer(201, {"key": key, "verification": VERDICT},
                        path={"accountId": ACCOUNT_ID},
                        expect={"api_key": API_KEY, "api_secret": API_SECRET,
                                "label": "demo host", "read_only": False,
                                "expected_uid": EXCHANGE_UID})],
    }  # fmt: skip


@dataclass
class Run:
    proc: subprocess.CompletedProcess[str]
    records: list[dict[str, Any]]
    argv: list[list[str]]
    docker: list[list[str]]
    sequence: list[str]  # the docker and curl calls, in order
    logs: dict[str, str]  # every file the stubs and the python3 shim wrote, by name
    left: list[Path]  # what the run left in its working directory, HOME and TMPDIR

    @property
    def routes(self) -> list[str]:
        return [r["route"] for r in self.records]


@dataclass
class Stage:
    """A run's directories, its stubs first on PATH, and its environment."""

    stub: Path
    cwd: Path
    dirs: tuple[Path, ...]  # the working directory, HOME and TMPDIR
    env: dict[str, str]


def stage(
    tmp_path: Path, calls: dict[str, list[dict[str, Any]]], *, schemas: bool = False,
    docker: dict[str, int] | None = None, docker_signal: dict[str, str] | None = None,
    with_docker: bool = True,
) -> Stage:  # fmt: skip
    """The stubs and the scenario for one run (`with_docker=False`: no docker, nothing else on
    PATH either, so no docker of the host's can stand in). A `tmux` stub records its arguments,
    so the script's `tmux clear-history` under $TMUX never reaches a real tmux."""
    stub, bin_dir, cwd, home, tmp = (tmp_path / d for d in ("stub", "bin", "cwd", "home", "tmp"))
    for directory in (stub, bin_dir, cwd, home, tmp):
        directory.mkdir()
    routes = [
        {"method": method, "path": path, "session": session,
         "schema": request_schema(op) if schemas else None,
         "calls": calls.get(f"{method} {path}", [])}
        for method, path, op, session in ROUTES
    ]  # fmt: skip
    scenario = {"routes": routes, "docker": docker or {}, "docker_print": CLI_PRINT,
                "docker_signal": docker_signal or {}}  # fmt: skip
    (stub / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    # A run starts some 36 Pythons. Without `site` (-S) each starts in about two thirds of the
    # time; the stubs and the script's python3 need the standard library alone, but for the
    # curl stub's jsonschema when it checks bodies.
    stubs = [("curl", STUB, "-I" if schemas else "-IS"), ("docker", DOCKER, "-IS")]
    tools = []
    for name, source, flags in stubs[: 2 if with_docker else 1]:
        tool = bin_dir / name
        tool.write_text(f"#!{sys.executable} {flags}\n" + source.read_text("utf-8"), "utf-8")
        tools.append(tool)
    tmux = bin_dir / "tmux"
    tmux.write_text('#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$CV_STUB_DIR/tmux.argv"\n', "utf-8")
    tools.append(tmux)
    shim = bin_dir / "python3"  # the script's python3, recording its arguments
    shim.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$CV_STUB_DIR/python3.argv"\n'
                    f'exec "{sys.executable}" -S "$@"\n', encoding="utf-8")  # fmt: skip
    for tool in (*tools, shim):
        tool.chmod(stat.S_IRWXU)
    path = f"{bin_dir}:/usr/bin:/bin" if with_docker else str(bin_dir)
    env = {"PATH": path, "HOME": str(home), "TMPDIR": str(tmp), "CV_STUB_DIR": str(stub)}
    return Stage(stub, cwd, (cwd, home, tmp), env)


def collect(staged: Stage, proc: subprocess.CompletedProcess[str]) -> Run:
    """What the run left: its records, the stubs' logs and any file it wrote."""

    def lines(name: str) -> list[Any]:
        path = staged.stub / name
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        return [json.loads(line) for line in text.splitlines()]

    logs = {p.name: p.read_text(encoding="utf-8") for p in staged.stub.iterdir() if p.is_file()}
    sequence = logs.get("sequence.log", "").splitlines()
    left = [p for d in staged.dirs for p in d.rglob("*")]
    return Run(proc, lines("requests.jsonl"), lines("argv.jsonl"), lines("docker.jsonl"),
               sequence, logs, left)  # fmt: skip


def run(
    tmp_path: Path, calls: dict[str, list[dict[str, Any]]], answers: list[str], *args: str,
    xtrace: bool = False, schemas: bool = False, docker: dict[str, int] | None = None,
    docker_signal: dict[str, str] | None = None, with_docker: bool = True,
) -> Run:  # fmt: skip
    """One run of the script on `calls` (and `docker`'s exit statuses, or the signal it sends,
    by subcommand); `schemas` also holds each body to 22, a slower run."""
    staged = stage(tmp_path, calls, schemas=schemas, docker=docker, docker_signal=docker_signal,
                   with_docker=with_docker)  # fmt: skip
    proc = subprocess.run(
        [BASH, *(["-x"] if xtrace else []), str(SCRIPT), *args],
        input="".join(f"{line}\n" for line in answers),
        capture_output=True, encoding="utf-8", cwd=staged.cwd, env=staged.env, timeout=120,
        check=False,
        start_new_session=True,  # no controlling terminal: /dev/tty cannot be opened
    )  # fmt: skip
    return collect(staged, proc)


#: Starts the script in a session of its own whose controlling terminal is its stdin, the pty.
CTTY = ("import fcntl, os, sys, termios; os.setsid(); fcntl.ioctl(0, termios.TIOCSCTTY, 0); "
        "os.execv(sys.argv[1], sys.argv[1:])")  # fmt: skip
#: A full run's prompts, in order: (how the prompt starts, the answer, typed at a silent prompt).
PROMPTS = [
    ("Owner email", EMAIL, False), ("Invite token", TOKEN, True), ("New password", PASSWORD, True),
    ("The same password again", PASSWORD, True), ("Its current code", CODES[0], True),
    ("A new code from the authenticator", CODES[1], True),
    ("Bybit demo account UID", EXCHANGE_UID, False), ("Account label", "", False),
    ("Key label", "", False), ("Read-only key?", "", False), ("Bybit API key", API_KEY, True),
    ("Bybit API secret", API_SECRET, True), ("A new code for the keys step-up", CODES[2], True),
]  # fmt: skip
ECHO_WAIT_S = 2.0  # a silent prompt that leaves ECHO on this long is answered anyway, and fails
PTY_DEADLINE_S = 120.0


@dataclass
class TerminalRun:
    returncode: int | None
    terminal: str  # what reached the pty: the echo of what was typed, and the script's fd 3
    stdout: str
    stderr: str
    echo_off: list[bool]  # for each silent prompt: ECHO was off when its answer was typed
    unanswered: list[str]  # the prompts the run never showed
    logs: dict[str, str]  # every file the stubs wrote, by name


def on_a_terminal(
    tmp_path: Path, calls: dict[str, list[dict[str, Any]]], prompts: list[tuple[str, str, bool]],
    *args: str, env: dict[str, str] | None = None,
) -> TerminalRun:  # fmt: skip
    """One run with a pty as its stdin and controlling terminal (so /dev/tty, fd 3), and pipes as
    stdout and stderr. Each answer is typed when its prompt reaches stderr, a silent one once
    ECHO is off (or after ECHO_WAIT_S). One read loop, bounded by PTY_DEADLINE_S, reads all three
    streams; it never sleeps beyond its select."""
    staged = stage(tmp_path, calls)
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, "-IS", "-c", CTTY, BASH, str(SCRIPT), *args],
        stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=staged.cwd,
        env=staged.env | (env or {}),
    )  # fmt: skip
    os.close(slave)
    assert proc.stdout is not None and proc.stderr is not None
    terminal, out, err = bytearray(), bytearray(), bytearray()
    streams = {master: terminal, proc.stdout.fileno(): out, proc.stderr.fileno(): err}
    waiting, matched = list(prompts), 0
    echo_off: list[bool] = []
    silent_since: float | None = None
    deadline = time.monotonic() + PTY_DEADLINE_S
    try:
        while streams and time.monotonic() < deadline:
            for fd in select.select(list(streams), [], [], 0.05)[0]:
                try:
                    chunk = os.read(fd, 1 << 16)
                except OSError:  # EIO: every holder of the terminal has closed it
                    chunk = b""
                if chunk:
                    streams[fd] += chunk
                else:
                    del streams[fd]
            at = err.find(waiting[0][0].encode(), matched) if waiting and master in streams else -1
            if at < 0:
                continue
            prompt, answer, silent = waiting[0]
            if silent:
                now = time.monotonic()
                silent_since = now if silent_since is None else silent_since
                echo = bool(termios.tcgetattr(master)[3] & termios.ECHO)
                if echo and now - silent_since < ECHO_WAIT_S:
                    continue
                echo_off.append(not echo)
                silent_since = None
            os.write(master, answer.encode() + b"\n")
            matched = at + len(prompt)
            waiting.pop(0)
        proc.wait(timeout=max(1.0, deadline - time.monotonic()))
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        os.close(master)
        proc.stdout.close()
        proc.stderr.close()
    text = [b.decode("utf-8", "replace") for b in (terminal, out, err)]
    logs = {p.name: p.read_text(encoding="utf-8") for p in staged.stub.iterdir() if p.is_file()}
    return TerminalRun(proc.returncode, *text, echo_off, [p for p, _, _ in waiting], logs)


@pytest.fixture(scope="module")
def full(tmp_path_factory: pytest.TempPathFactory) -> Run:
    return run(tmp_path_factory.mktemp("full"), full_run(), ANSWERS, schemas=True)


@pytest.fixture(scope="module")
def on_tty(tmp_path_factory: pytest.TempPathFactory) -> TerminalRun:
    """A full run on a terminal, answered prompt by prompt, inside tmux (its stub)."""
    tmux = {"TMUX": "stub-socket,1,0", "TMUX_PANE": "%7"}
    return on_a_terminal(tmp_path_factory.mktemp("tty"), full_run(), PROMPTS, env=tmux)


def test_no_secret_typed_at_the_terminal_comes_back_on_it(on_tty: TerminalRun) -> None:
    """The runbook's promise (step 7): every secret is read silently. On a real terminal ECHO is
    off at each silent prompt and nothing typed there reaches the terminal, while the email and
    the UID, typed at visible prompts, are echoed back: the check sees an echo when there is one."""
    assert on_tty.returncode == 0 and on_tty.unanswered == [], on_tty.stderr
    assert on_tty.echo_off == [True] * sum(silent for _, _, silent in PROMPTS)
    assert [s for s in SECRETS if s in on_tty.terminal + on_tty.stdout + on_tty.stderr] == []
    assert EMAIL in on_tty.terminal and EXCHANGE_UID in on_tty.terminal


#: m1: the screen, then the scrollback (ED 2, ED 3), once what was shown once is no longer needed.
CLEAR = "\x1b[H\x1b[2J\x1b[3J"
STILL_THERE = "still in this terminal's scrollback"


def test_a_successful_run_clears_what_it_showed_once_from_the_terminal(on_tty: TerminalRun) -> None:
    """m1: the token, the URI and the codes stay in a terminal's scrollback and tmux's history.
    At the end, before the verdict, a run that succeeds clears both, once."""
    assert on_tty.terminal.count(CLEAR) == 1
    cleared = on_tty.terminal.index(CLEAR)
    assert all(on_tty.terminal.rindex(shown) < cleared for shown in (CLI_PRINT, OTPAUTH, *RECOVERY))
    assert on_tty.logs.get("tmux.argv") == "clear-history -t %7\n"
    assert STILL_THERE not in on_tty.stderr and on_tty.stdout.splitlines() == VERDICT_LINES


def test_a_successful_run_says_it_asked_the_terminal_to_clear(on_tty: TerminalRun) -> None:
    """D-7: a terminal may ignore ED 3 and keep its scrollback, so the run says what it did, ask,
    and to clear what is still there; neither its warning nor its end says the scrollback is or
    will be cleared."""
    assert "was asked to clear" in on_tty.stderr
    assert "are cleared" not in on_tty.stderr and "clears this terminal" not in on_tty.stderr


def test_the_account_id_reaches_the_terminal_alone(on_tty: TerminalRun) -> None:
    """L6: the one value `--account-id` needs is shown on the terminal, never on stdout or
    stderr, which a log could keep."""
    assert ACCOUNT_ID in on_tty.terminal
    assert ACCOUNT_ID not in on_tty.stdout + on_tty.stderr


#: A rerun's prompts (`--skip-invite --account-id`, which step 7 of the runbook gives after a
#: failure past the invite): the sign-in, the key, then the step-up.
RERUN_PROMPTS = [
    ("Owner username or email", EMAIL, False), ("Password", PASSWORD, True),
    ("A new code from the authenticator", CODES[1], True),
    ("Bybit demo account UID", EXCHANGE_UID, False), ("Key label", "", False),
    ("Read-only key?", "", False), ("Bybit API key", API_KEY, True),
    ("Bybit API secret", API_SECRET, True), ("A new code for the keys step-up", CODES[2], True),
]  # fmt: skip


def test_on_a_rerun_no_secret_typed_at_the_terminal_comes_back_on_it(tmp_path: Path) -> None:
    """D-1: a rerun asks for the password at the sign-in, where a first run reuses the invite's,
    then for every code and secret after it. On a real terminal ECHO is off at each of those
    prompts and nothing typed there reaches the terminal, while the email and the UID are echoed
    back; what was typed silently is what was sent."""
    again = on_a_terminal(tmp_path, full_run(), RERUN_PROMPTS, "--skip-invite", "--account-id",
                          ACCOUNT_ID)  # fmt: skip
    assert again.returncode == 0 and again.unanswered == [], again.stderr
    assert again.echo_off == [True] * sum(silent for _, _, silent in RERUN_PROMPTS)
    assert [s for s in SECRETS if s in again.terminal + again.stdout + again.stderr] == []
    assert EMAIL in again.terminal and EXCHANGE_UID in again.terminal
    sent = [json.loads(line) for line in again.logs["requests.jsonl"].splitlines()]
    assert [r["route"] for r in sent] == [LOGIN, VERIFY, STEP_UP, IMPORT]
    assert all(r["path_ok"] and all(r["body_ok"].values()) for r in sent)


# --- the bootstrap: #4479's CLI in bootstrap-owner, while api is stopped ------------------------


def test_the_bootstrap_runs_in_its_service_while_api_is_stopped_then_the_invite(full: Run) -> None:
    """DC-4479-02: `bootstrap-owner` (no logging driver), never `run ... api`; demo, so no
    `--live`; then api again, healthy, before the token is asked for."""
    assert full.docker == BOOTSTRAP
    assert full.sequence == [
        "docker stop",
        "docker run",
        "docker up",
        *(f"curl {r}" for r in ORDER),
    ]


def test_the_owner_is_warned_before_the_first_thing_shown_once(full: Run) -> None:
    """m1: before the CLI prints the token, the run names what would keep a copy of it."""
    before = full.proc.stderr.split(CLI_PRINT)[0]
    assert all(word in before for word in ("session recorder", "clipboard", "scrollback"))


def test_without_a_terminal_to_clear_the_owner_is_told_to_clear_it(full: Run) -> None:
    """m1: no terminal to clear (the test's case), so the end of the run says to."""
    assert full.proc.returncode == 0 and STILL_THERE in full.proc.stderr


def test_the_bootstrap_output_reaches_the_terminal_and_nothing_else(full: Run) -> None:
    """The CLI prints the token once on its TTY: the script neither captures nor copies it."""
    assert full.proc.stderr.count(CLI_PRINT) == 1 and CLI_PRINT not in full.proc.stdout
    assert [name for name, text in full.logs.items() if CLI_PRINT in text] == ["scenario.json"]


@pytest.mark.parametrize(
    ("docker", "message", "made"),
    [
        ({"stop": 1}, "could not stop api", 1),
        ({"run": 12}, "confirmation_mismatch", 2),
        ({"run": 17}, "owner_exists", 2),
        ({"run": 9}, "kek_unproven", 2),
        ({"run": 6}, "audit_unavailable", 2),
        ({"run": 18}, "not_candidate (not a usable bootstrap email, or a user who cannot become "
                      "the Owner)", 2),
        ({"up": 1}, "did not get healthy after the bootstrap: read the logs of migrate (the schema "
                    "step that runs first) and api", 3),
    ],
    ids=["stop", "phrase", "owner-exists", "kek", "audit", "not-candidate", "up"],
)  # fmt: skip
def test_a_failed_bootstrap_step_stops_the_run(
    tmp_path: Path, docker: dict[str, int], message: str, made: int
) -> None:
    """And says how to start api again, with the exact command (F10): the run stopped it."""
    stopped = run(tmp_path, full_run(), ANSWERS, docker=docker)
    assert stopped.proc.returncode == 1 and message in stopped.proc.stderr
    assert stopped.docker == BOOTSTRAP[:made] and stopped.records == []
    assert UP_API in stopped.proc.stderr and "<the runbook's" not in stopped.proc.stderr
    assert [secret for secret in SECRETS if secret in stopped.proc.stderr] == []


@pytest.mark.parametrize(("name", "status"), [("INT", 130), ("TERM", 143), ("HUP", 129)])
def test_a_signal_during_the_bootstrap_ends_the_run_saying_how_to_start_api(
    tmp_path: Path, name: str, status: int
) -> None:
    """L5, F10: Ctrl-C at the CLI reaches the script and the CLI alike (the docker stub signals
    its process group). The run ends with 128 + the signal, through its own trap, and prints the
    command that starts the api it stopped; nothing typed reaches stderr."""
    stopped = run(tmp_path, full_run(), ANSWERS, docker_signal={"run": name})
    assert stopped.proc.returncode == status, stopped.proc.stderr
    assert stopped.sequence == ["docker stop", "docker run"]
    assert UP_API in stopped.proc.stderr
    assert [secret for secret in SECRETS if secret in stopped.proc.stderr] == []


def test_the_restart_line_ends_once_api_is_healthy_again(full: Run, tmp_path: Path) -> None:
    """D-4: once `up --wait` returns, api is healthy again, so no later exit says it may be
    stopped: neither a run that succeeds nor one refused at the next step."""
    scenario = full_run()
    scenario[GET_INVITE] = [REFUSED_INVITE]
    refused = run(tmp_path, scenario, ANSWERS[:2])
    assert (full.proc.returncode, refused.proc.returncode) == (0, 1)
    for done in (full, refused):
        assert done.docker == BOOTSTRAP  # api was stopped, then started again
        assert "api may be stopped" not in done.proc.stderr and UP_API not in done.proc.stderr


def test_a_malformed_email_stops_before_any_call(tmp_path: Path) -> None:
    stopped = run(tmp_path, full_run(), ["owner"])
    assert stopped.proc.returncode == 1 and "an email whose part before @" in stopped.proc.stderr
    assert stopped.docker == [] and stopped.records == []


# --- the run: 22's operations, in order, with valid bodies ---------------------------------------


@pytest.mark.parametrize(("method", "path", "operation_id", "session"), ROUTES)
def test_each_call_is_22s_operation_and_only_the_pre_session_ones_skip_csrf(
    method: str, path: str, operation_id: str, session: bool
) -> None:
    assert operation(operation_id)[:2] == (method, path)
    names = [p.get("$ref", "") for p in operation(operation_id)[2].get("parameters", [])]
    assert ("#/components/parameters/CsrfToken" in names) == session


def test_a_full_run_calls_each_operation_once_in_order_and_exits_0(full: Run) -> None:
    assert full.proc.returncode == 0, full.proc.stderr
    assert full.routes == ORDER


def test_every_body_is_valid_against_22_and_carries_what_was_typed(full: Run) -> None:
    for record, (_, _, operation_id, _) in zip(full.records, ROUTES, strict=True):
        assert record["path_ok"], record["route"]
        if request_schema(operation_id) is not None:  # all but getInvite, which sends no body
            assert record.get("schema_errors") == [], record["route"]
        assert all(record["body_ok"].values()), record
    assert sum("schema_errors" in record for record in full.records) == len(ORDER) - 1
    assert [r["route"] for r in full.records if not r["body_ok"]] == [GET_INVITE]
    assert full.records[0]["body_keys"] is None  # getInvite sends no body
    assert all("content-type" in r["header_names"] for r in full.records[1:])


def test_only_the_session_operations_carry_the_bearer_and_the_double_submit_token(
    full: Run,
) -> None:
    for record, (_, _, _, session) in zip(full.records, ROUTES, strict=True):
        sent = {"authorization", "cookie", "x-csrf-token"} & set(record["header_names"])
        assert record.get("session_ok", False) is session and bool(sent) is session, record


def test_the_writes_carry_a_fresh_idempotency_key(full: Run) -> None:
    keys = {r["route"]: r.get("idempotency_key_is_uuid4") for r in full.records}
    assert keys[CREATE] is True and keys[IMPORT] is True
    assert len({r["idempotency_key"] for r in full.records if "idempotency_key" in r}) == 2


# --- what leaves the script ----------------------------------------------------------------------


def test_stdout_is_only_the_verdict_and_never_the_egress_address(full: Run) -> None:
    assert full.proc.stdout.splitlines() == VERDICT_LINES
    assert EGRESS not in full.proc.stdout + full.proc.stderr


def test_no_typed_secret_reaches_stdout_stderr_an_argument_or_a_record(full: Run) -> None:
    written = {name: text for name, text in full.logs.items() if name != "scenario.json"}
    seen = {"stdout": full.proc.stdout, "stderr": full.proc.stderr, **written}
    leaks = [(s, where) for s in SECRETS for where, text in seen.items() if s in text]
    assert leaks == []
    logs = {"argv.jsonl", "docker.jsonl", "python3.argv", "requests.jsonl", "sequence.log"}
    assert logs <= set(full.logs)


def test_curl_gets_only_fixed_options_on_its_command_line(full: Run) -> None:
    assert full.argv == [CURL_ARGV] * (len(ORDER) - 1) + [IMPORT_ARGV]


def test_the_run_writes_no_file(full: Run) -> None:
    assert full.left == []


def test_the_enrolment_uri_and_the_recovery_codes_are_shown_once_on_the_terminal(
    full: Run,
) -> None:
    """No terminal in the test, so the one-time display falls back to stderr."""
    for shown in (OTPAUTH, *RECOVERY):
        assert full.proc.stderr.count(shown) == 1 and shown not in full.proc.stdout


def test_tracing_stays_off_under_bash_x(tmp_path: Path) -> None:
    traced = run(tmp_path, full_run(), ANSWERS, xtrace=True)
    assert traced.proc.returncode == 0, traced.proc.stderr
    assert [secret for secret in SECRETS if secret in traced.proc.stderr] == []


def test_the_guards_come_before_the_first_prompt() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    first_read = re.search(r"^\s*(?:IFS= )?read ", text, re.MULTILINE)
    assert first_read is not None
    text = text[: first_read.start()]
    for guard in ("set +x", "set -euo pipefail", "umask 077"):
        assert re.search(rf"^{re.escape(guard)}", text, re.MULTILINE), guard


# --- refusals: the run stops with a plain message and a non-zero status --------------------------


REFUSED_INVITE = problem(404, "not_found", "This invitation link is not valid.")
BAD_CODE = problem(422, "invalid_code", "invalid code")
BAD_FACTOR = problem(401, "mfa_invalid", "invalid or expired code")
BAD_STEP_UP = problem(401, "mfa_invalid", "Invalid password or code.", failures_remaining=2)
UID_TAKEN = problem(409, "conflict", "This UID is already registered as Bybit demo main.")
KEY_REFUSED = problem(
    422, "validation_failed", "The key was not imported.",
    errors=[{"field": "api_key", "rule": "key_ip_whitelist_mismatch", "message": "m"}],
    verification={**VERDICT, "passed": False, "ip_whitelist_matches_egress": False},
)  # fmt: skip
VIEWER = answer(200, {"status": "active", "role": "viewer", "recovery_codes": ["rc"]})


@pytest.mark.parametrize(
    ("route", "calls", "answers", "message", "made"),
    [
        (GET_INVITE, [REFUSED_INVITE], ANSWERS[:2], "the invite token is not valid", 1),
        (GET_INVITE, [{"exit": 7}], ANSWERS[:2], "did not answer", 1),
        (REDEEM, [problem(422, "password_policy", "too_short")], ANSWERS[:4], "too_short", 2),
        (CONFIRM, [BAD_CODE] * 3, ANSWERS[:4] + [CODES[0]] * 3, "refused three times", 5),
        (CONFIRM, [VIEWER], ANSWERS[:5], "not owner", 3),
        (LOGIN, [problem(401, "invalid_credentials", "invalid credentials")], ANSWERS[:5],
         "sign-in was refused", 4),
        (VERIFY, [BAD_FACTOR] * 3, ANSWERS[:5] + [CODES[1]] * 3, "refused three times", 7),
        (STEP_UP, [BAD_STEP_UP] * 2, ANSWERS + [CODES[2]], "refused twice", 7),
        (CREATE, [problem(404, "not_found", "Not Found")], ANSWERS,
         "does not serve POST /exchange-accounts", 7),
        (CREATE, [UID_TAKEN], ANSWERS, "already registered as Bybit demo main", 7),
        (IMPORT, [KEY_REFUSED], ANSWERS, "key_ip_whitelist_mismatch", 8),
        (IMPORT, [problem(503, "exchange_unavailable", "no verdict")], ANSWERS, "no verdict", 8),
    ],
    ids=["invite-unknown", "api-down", "password-policy", "enrolment-code", "not-owner",
         "sign-in", "second-factor", "step-up", "older-backend", "uid-taken", "key-refused",
         "exchange-unavailable"],
)  # fmt: skip
def test_a_refused_step_stops_the_run(
    tmp_path: Path, route: str, calls: list[dict[str, Any]], answers: list[str], message: str,
    made: int,
) -> None:  # fmt: skip
    scenario = full_run()
    scenario[route] = calls
    refused = run(tmp_path, scenario, answers)
    assert refused.proc.returncode == 1
    assert message in refused.proc.stderr and STILL_THERE in refused.proc.stderr
    assert len(refused.records) == made
    assert set(refused.routes) <= set(ORDER[: ORDER.index(route) + 1])
    assert [secret for secret in SECRETS if secret in refused.proc.stderr] == []


def test_a_refused_key_prints_its_verdict_and_never_the_egress_address(tmp_path: Path) -> None:
    scenario = full_run()
    scenario[IMPORT] = [KEY_REFUSED]
    refused = run(tmp_path, scenario, ANSWERS)
    assert "passed: false" in refused.proc.stdout.splitlines()
    assert "ip_whitelist_matches_egress: false" in refused.proc.stdout.splitlines()
    assert EGRESS not in refused.proc.stdout + refused.proc.stderr


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        ([EMAIL, "not a token!"], "not an invite token"),
        ([EMAIL, TOKEN, PASSWORD, PASSWORD + "x"], "the two passwords differ"),
        ([EMAIL, TOKEN, "short", "short"], "12 to 512 characters"),
        (ANSWERS[:4] + ["12345"], "6 digits"),
        (ANSWERS[:6] + ["12ab"], "4 to 20 digits"),
    ],
    ids=["token", "passwords-differ", "password-short", "code", "uid"],
)
def test_a_malformed_answer_stops_before_it_is_sent(
    tmp_path: Path, answers: list[str], message: str
) -> None:
    stopped = run(tmp_path, full_run(), answers)
    assert stopped.proc.returncode == 1 and message in stopped.proc.stderr
    assert [r["route"] for r in stopped.records if r["route"] not in ORDER[:5]] == []
    assert [secret for secret in SECRETS if secret in stopped.proc.stderr] == []


BOOTED = ["docker stop", "docker run", "docker up"]
SKIP = ("--skip-invite",)
KEEP = ("--skip-invite", "--account-id", ACCOUNT_ID)
SIGN_IN = [IDENTIFIER, PASSWORD, CODES[1]]  # after --skip-invite: the identifier, password, code
#: After --skip-invite --account-id: to the import (the UID, the key label, read-only, the key).
TO_IMPORT = [*SIGN_IN, EXCHANGE_UID, "", "", API_KEY, API_SECRET, CODES[2]]


def curl(*routes: str) -> list[str]:
    return [f"curl {route}" for route in routes]


@pytest.mark.parametrize(
    ("answers", "args", "message", "sequence"),
    [
        ([], (), "no answer to: Owner email", []),
        ([EMAIL], (), "no answer to: Invite token", BOOTED),
        ([EMAIL, ""], (), "not an invite token", BOOTED),
        ([EMAIL, TOKEN, "", ""], (), "a password is 12 to 512 characters",
         BOOTED + curl(GET_INVITE)),
        ([EMAIL, TOKEN, "p" * 513, "p" * 513], (), "a password is 12 to 512 characters",
         BOOTED + curl(GET_INVITE)),
        ([*ANSWERS[:4], ""], (), "6 digits", BOOTED + curl(GET_INVITE, REDEEM)),
        ([IDENTIFIER, ""], SKIP, "a password is 1 to 512 characters", []),
        ([*SIGN_IN, EXCHANGE_UID, "x" * 81], SKIP, "an account label is 1 to 80",
         curl(LOGIN, VERIFY)),
        ([*SIGN_IN, EXCHANGE_UID, "", "", ""], KEEP, "an API key is 8 to 128 characters",
         curl(LOGIN, VERIFY)),
        ([*SIGN_IN, EXCHANGE_UID, "", "", API_KEY, ""], KEEP, "an API secret is 8 to 256",
         curl(LOGIN, VERIFY)),
    ],
    ids=["eof-first-prompt", "eof-first-secret", "empty-token", "empty-password",
         "password-over-512", "empty-code", "empty-sign-in-password", "long-label",
         "empty-api-key", "empty-api-secret"],
)  # fmt: skip
def test_an_empty_missing_or_oversized_answer_stops_before_it_is_sent(
    tmp_path: Path, answers: list[str], args: tuple[str, ...], message: str, sequence: list[str]
) -> None:
    """EOF at a prompt (the first, and the first silent one) and an empty answer are refused
    where they are typed: nothing after that prompt is called."""
    stopped = run(tmp_path, full_run(), answers, *args)
    assert stopped.proc.returncode == 1 and message in stopped.proc.stderr
    assert stopped.sequence == sequence
    assert [secret for secret in SECRETS if secret in stopped.proc.stderr] == []


def test_a_yes_to_read_only_imports_a_key_declared_read_only(tmp_path: Path) -> None:
    scenario = full_run()
    scenario[LOGIN][0]["expect"] = {"identifier": IDENTIFIER, "password": PASSWORD}
    scenario[IMPORT][0]["expect"] |= {"read_only": True}
    answers = [*SIGN_IN, EXCHANGE_UID, "", "y", API_KEY, API_SECRET, CODES[2]]
    done = run(tmp_path, scenario, answers, *KEEP)
    assert done.proc.returncode == 0, done.proc.stderr
    assert [r["body_ok"] for r in done.records if r["route"] == IMPORT] == [
        dict.fromkeys(scenario[IMPORT][0]["expect"], True)
    ]


def test_a_501_names_the_servers_reason_not_an_older_build(tmp_path: Path) -> None:
    """F12: the served route answers 501 when no principal resolver is wired, which a build
    before #4484 is not the only cause of."""
    scenario = full_run()
    scenario[CREATE] = [problem(501, "not_implemented", "No principal resolver is wired.")]
    stopped = run(tmp_path, scenario, ANSWERS)
    assert stopped.proc.returncode == 1
    assert "HTTP 501 not_implemented: No principal resolver is wired." in stopped.proc.stderr
    assert "a build before #4484" not in stopped.proc.stderr


def test_the_password_bound_counts_characters_not_bytes(tmp_path: Path) -> None:
    """F15: under LC_ALL=C bash counts bytes; 300 two-byte characters are 300 characters, as the
    server counts them, so they are sent as typed."""
    wide = "\u00e9" * 300
    scenario = full_run()
    refusal = problem(422, "password_policy", "too_common")  # stops the run once it is sent
    scenario[REDEEM] = [refusal | {"expect": {"password": wide}}]
    sent = run(tmp_path, scenario, [EMAIL, TOKEN, wide, wide])
    assert [r["body_ok"] for r in sent.records if r["route"] == REDEEM] == [{"password": True}]


@pytest.mark.parametrize(("length", "sent"), [(11, False), (12, True), (512, True), (513, False)])
def test_the_password_bound_holds_at_12_and_512_characters(
    tmp_path: Path, length: int, sent: bool
) -> None:
    """The new password's bound, at both ends: 12 and 512 characters are sent, 11 and 513 are
    refused before anything is sent."""
    password = "p" * length
    scenario = full_run()
    refusal = problem(422, "password_policy", "too_common")  # stops the run once it is sent
    scenario[REDEEM] = [refusal | {"expect": {"password": password}}]
    done = run(tmp_path, scenario, [EMAIL, TOKEN, password, password])
    expected = [{"password": True}] if sent else []
    assert [r["body_ok"] for r in done.records if r["route"] == REDEEM] == expected
    assert ("a password is 12 to 512 characters" in done.proc.stderr) is not sent


#: How a run refused at the step-up says to run again: with the account id once one exists.
STEP_UP_AGAIN = "the step-up was refused twice: wait 5 minutes, then run again with --skip-invite"


@pytest.mark.parametrize(
    ("answers", "args", "rerun"),
    [
        (ANSWERS + [CODES[2]], (), ""),
        (TO_IMPORT + [CODES[2]], KEEP, " --account-id <the account id>"),
    ],
    ids=["no-account-yet", "account-registered"],
)
def test_a_refused_step_up_names_the_rerun(
    tmp_path: Path, answers: list[str], args: tuple[str, ...], rerun: str
) -> None:
    scenario = full_run()
    scenario[STEP_UP] = [BAD_STEP_UP] * 2
    stopped = run(tmp_path, scenario, answers, *args)
    assert stopped.proc.returncode == 1
    assert f"demo_host_owner_first_run: {STEP_UP_AGAIN}{rerun}\n" in stopped.proc.stderr


ELEVATED = {"elevated_until": "2026-10-26T04:05:00+00:00", "action_class": "keys"}
NO_CHALLENGE = problem(403, "step_up_required", "Re-enter your password and code.",
                       action_class="keys")  # fmt: skip


@pytest.mark.parametrize(
    ("route", "calls", "answers", "args", "message", "sequence"),
    [
        (GET_INVITE, [problem(429, "rate_limited", "Too many attempts.")], ANSWERS[:2], (),
         "too many invalid attempts", BOOTED + curl(GET_INVITE)),
        (REDEEM, [problem(429, "rate_limited", "Too many attempts.")], ANSWERS[:4], (),
         "too many invalid attempts", BOOTED + curl(GET_INVITE, REDEEM)),
        (REDEEM, [answer(200, {"method_id": METHOD_ID})], ANSWERS[:4], (),
         "without a TOTP enrolment", BOOTED + curl(GET_INVITE, REDEEM)),
        (LOGIN, [problem(401, "unauthenticated", "Invalid credentials")], SIGN_IN[:2], SKIP,
         "or wait out a lock (15 minutes at most), then run again with --skip-invite",
         curl(LOGIN)),
        (LOGIN, [answer(200, {"status": "authenticated"})], SIGN_IN[:2], SKIP,
         "asked for no code", curl(LOGIN)),
        (STEP_UP, [answer(200, ELEVATED | {"tokens": {"access_token": "not a token!"}})],
         TO_IMPORT, KEEP, "malformed access token", curl(LOGIN, VERIFY, STEP_UP)),
        (CREATE, [answer(201, {"exchange": "bybit"})], ANSWERS, (), "without an account id",
         BOOTED + curl(*ORDER[:7])),
        (IMPORT, [{"exit": 7}], TO_IMPORT, KEEP, "which may have run",
         curl(LOGIN, VERIFY, STEP_UP, IMPORT)),
        (IMPORT, [problem(502, "bad_gateway", "No answer upstream.")], TO_IMPORT, KEEP,
         "no verdict, nothing was stored", curl(LOGIN, VERIFY, STEP_UP, IMPORT)),
        (IMPORT, [NO_CHALLENGE], TO_IMPORT, KEEP, "a step-up without a challenge id",
         curl(LOGIN, VERIFY, STEP_UP, IMPORT)),
    ],
    ids=["invite-check-429", "password-429", "no-totp-enrolment", "sign-in-401",
         "sign-in-without-mfa", "step-up-malformed-token", "account-without-id",
         "import-unanswered", "import-502", "challenge-without-id"],
)  # fmt: skip
def test_each_refusal_branch_stops_the_run_where_it_is(
    tmp_path: Path, route: str, calls: list[dict[str, Any]], answers: list[str],
    args: tuple[str, ...], message: str, sequence: list[str],
) -> None:  # fmt: skip
    scenario = full_run()
    scenario[route] = calls
    stopped = run(tmp_path, scenario, answers, *args)
    assert stopped.proc.returncode == 1 and message in stopped.proc.stderr
    assert stopped.sequence == sequence
    assert [secret for secret in SECRETS if secret in stopped.proc.stderr] == []


def test_help_prints_the_usage_and_exits_0_before_anything(tmp_path: Path) -> None:
    helped = run(tmp_path, full_run(), [], "--help")
    assert helped.proc.returncode == 0 and "usage:" in helped.proc.stderr
    assert helped.sequence == []


def test_a_host_without_docker_stops_before_the_bootstrap(tmp_path: Path) -> None:
    """PATH holds the stubs alone here, so no docker of the host's can answer."""
    stopped = run(tmp_path, full_run(), [EMAIL], with_docker=False)
    assert stopped.proc.returncode == 1 and "docker is not installed" in stopped.proc.stderr
    assert stopped.sequence == []


# --- the step-up: 22's challenge and session rotation --------------------------------------------


@pytest.mark.parametrize("route", [CREATE, IMPORT])
def test_a_step_up_challenge_is_answered_and_the_held_request_sent_again(
    tmp_path: Path, route: str
) -> None:
    scenario = full_run()
    challenge = problem(403, "step_up_required", "Re-enter your password and code.",
                        action_class="keys", challenge_id=CHALLENGE_ID)  # fmt: skip
    scenario[route] = [challenge, scenario[route][0]]
    again = dict(scenario[STEP_UP][0])
    again["expect"] = {"password": PASSWORD, "code": "112358", "challenge_id": CHALLENGE_ID}
    scenario[STEP_UP] = [scenario[STEP_UP][0], again]
    resent = run(tmp_path, scenario, [*ANSWERS, "112358"], schemas=True)
    assert resent.proc.returncode == 0, resent.proc.stderr
    at = ORDER.index(route) + 1
    assert resent.routes == [*ORDER[:at], STEP_UP, route, *ORDER[at:]]
    assert all(all(r["body_ok"].values()) for r in resent.records)
    held = [r["idempotency_key"] for r in resent.records if r["route"] == route]
    assert len(held) == 2 and held[0] == held[1]  # the held request, sent again as is


def test_a_step_up_that_rotates_the_session_is_followed(tmp_path: Path) -> None:
    """22 (SR-013): the step-up's 200 carries the new access token and sets the new CSRF cookie;
    the served code does not rotate yet, and the script takes whichever it is given."""
    scenario = full_run()
    rotated = scenario[STEP_UP][0]
    rotated["body"] = {
        **rotated["body"],
        "tokens": {"access_token": ROTATED["access"], "token_type": "Bearer", "expires_in": 600},
    }
    rotated |= {"cookies": {"__Host-cv_csrf": ROTATED["csrf"]}, "session": ROTATED}
    followed = run(tmp_path, scenario, ANSWERS)
    assert followed.proc.returncode == 0, followed.proc.stderr
    after = [r["session_ok"] for r in followed.records if r["route"] in (CREATE, IMPORT)]
    assert after == [True, True]  # the account and the key used the rotated session


# --- a second run: the invite redeemed, the account registered -----------------------------------


def test_skip_invite_and_account_id_start_at_the_sign_in_and_reuse_the_account(
    tmp_path: Path,
) -> None:
    scenario = full_run()
    scenario[LOGIN][0]["expect"] = {"identifier": IDENTIFIER, "password": PASSWORD}
    answers = [IDENTIFIER, PASSWORD, CODES[1], EXCHANGE_UID, "", "", API_KEY, API_SECRET, CODES[2]]
    again = run(tmp_path, scenario, answers, "--skip-invite", "--account-id", ACCOUNT_ID)
    assert again.proc.returncode == 0, again.proc.stderr
    assert again.routes == [LOGIN, VERIFY, STEP_UP, IMPORT] and again.docker == []
    assert all(r["path_ok"] and all(r["body_ok"].values()) for r in again.records)
    assert again.proc.stdout.splitlines() == VERDICT_LINES
    assert "scrollback" not in again.proc.stderr  # nothing was shown once: nothing to clear


@pytest.mark.parametrize("args", [["--account-id", "not-a-uuid"], ["--bogus"], ["--account-id"]])
def test_bad_arguments_stop_before_any_prompt(tmp_path: Path, args: list[str]) -> None:
    stopped = run(tmp_path, full_run(), ANSWERS, *args)
    assert stopped.proc.returncode == 2 and stopped.records == [] and stopped.docker == []
