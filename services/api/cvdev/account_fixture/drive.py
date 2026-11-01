"""#2893's closure: the account-fixture stack's driver, run in its `fixture-drive` one-shot.

    python -m cvdev.account_fixture.drive --run-dir /run-dir --session-dir /session signin USER
    python -m cvdev.account_fixture.drive ... call USER METHOD PATH [--body-json JSON]
    python -m cvdev.account_fixture.drive ... scan PATH...

`signin` signs a roster user in on the stack's api (`http://api:8000`, the compose service): the
password from `pw-<user>`, then a TOTP code made from `totp-<user>` for a 30 s step this user has
not used (the api refuses a replayed step), then `GET /me`. The session (a bearer, the CSRF token of
`__Host-cv_csrf` and the last step used) goes to `<session-dir>/<user>.json`, mode 0600, and never
to a terminal. `call` sends one request with that session: the bearer, the CSRF cookie and its
`X-CSRF-Token` header and, on a write, a new `Idempotency-Key`. A `403 step_up_required` is answered
transparently: the password and a code for an unused step go to `POST /auth/step-up` with the
challenge's id, and the held request is sent again unchanged, its body and key included. It prints
`HTTP <status> <problem code or ->` and the answer's body with every credential, token and code it
knows masked, and any field named for one too. `scan` counts, per path, how often any value this
run generated (the run directory's files, the env file's secrets, the sessions' tokens) appears in
it, and prints counts, never a value.

The gate comes first, as the seed's does, each refusal one fixed line (`account-fixture: refused:
...`) and exit 2: ADR-0036's structural gate (`cli.armed`), then the run directory (absolute, its
own real path, owned by the uid named in `CV_ACCTFIX_RUN_UID`, else the effective uid, with no group
or other permission bit, and seeded: `.seeded` present). The driver reads the run directory and
writes only its session file. Its HTTP and TOTP are the standard library's; neither
`candleviewer.secrets` nor `candleviewer.audit` is imported (C-3.2, C-3.3).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import http.client
import json
import os
import re
import struct
import sys
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any, Final

from candleviewer.settings import Settings
from cvdev.account_fixture.cli import CliRefused, armed

API_HOST: Final = "api"  # the stack's api, by its compose service name
API_PORT: Final = 8000
CSRF_COOKIE: Final = "__Host-cv_csrf"
STEP_S: Final = 30
TIMEOUT_S: Final = 30.0
MAX_BODY_BYTES: Final = 1 << 20
MAX_SCAN_BYTES: Final = 64 << 20
MAX_FILE_BYTES: Final = 64 << 10  # a run-directory or session file: a few hundred bytes
EXIT_REFUSED: Final = 2
EXIT_HITS: Final = 1
RUN_UID_VARIABLE: Final = "CV_ACCTFIX_RUN_UID"
SEEDED_MARKER: Final = ".seeded"
#: The env file's names whose values are secrets (the rest: names, paths, ports, inert values).
SECRET_ENV: Final = (
    "POSTGRES_PASSWORD",
    "CV_PG_DSN",
    "CV_AUTH_PEPPER",
    "CV_AUTH_TOTP_KEY_HEX",
    "CV_AUTH_RECOVERY_HMAC_KEY_HEX",
    "CV_AUTH_CSRF_KEY_HEX",
)
METHODS: Final = ("GET", "POST", "PUT", "PATCH", "DELETE")
WRITES: Final = frozenset(METHODS) - {"GET"}

NOT_ROOTED: Final = "the run directory must be an absolute path without '..'"
LINKED: Final = "the run directory must be a real directory, not a symlink or under one"
SHARED: Final = (
    "the run directory must be owned by the invoking user, with no group or other access"
)
NOT_SEEDED: Final = "the run directory holds no seeded run: bring the stack up first"
BAD_UID: Final = f"{RUN_UID_VARIABLE} must be a uid: digits only"
NOT_A_USER: Final = "not a user of this run's roster"
NO_SESSION: Final = "no session for that user: sign in first"
BAD_REQUEST: Final = "a request is a method (GET, POST, PUT, PATCH or DELETE) and an absolute path"
BAD_BODY: Final = "--body-json must be one JSON object"
SIGN_IN_FAILED: Final = "the sign-in did not complete"
STEP_UP_FAILED: Final = "the step-up did not complete: the held request was not sent"
FAILED: Final = "the driver did not complete"
INVALID_SETTINGS: Final = "invalid settings; nothing changed"

_UID: Final = re.compile(r"[0-9]{1,10}")
_PATH: Final = re.compile(r"/[A-Za-z0-9\-._~/%?=&:+,]{0,2047}")
_SECRET_FIELD: Final = re.compile(
    r"(?i)(?:.*_)?(?:totp|otp|token|secret|password|passcode|csrf)(?:_.*)?"
)  # a name part, so `access_token` and `api_secret` match and `footprint` does not
_JWT: Final = re.compile(r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")
MASK: Final = "***"


class Refused(Exception):
    """A fixed message, printed as the driver's one line; it never names a path or a value."""


@dataclass(frozen=True)
class Answer:
    status: int
    body: dict[str, Any]
    cookies: dict[str, str]


Http = Callable[[str, str, bytes | None, Mapping[str, str]], Answer]


def exchange(method: str, path: str, body: bytes | None, headers: Mapping[str, str]) -> Answer:
    """One plain-HTTP exchange with the stack's api, inside the project's network."""
    connection = http.client.HTTPConnection(API_HOST, API_PORT, timeout=TIMEOUT_S)
    try:
        connection.request(method, path, body=body, headers=dict(headers))
        response = connection.getresponse()
        status, raw = response.status, response.read(MAX_BODY_BYTES)
        set_cookies = response.headers.get_all("Set-Cookie") or []
    finally:
        connection.close()
    cookies: dict[str, str] = {}
    for header in set_cookies:
        jar: SimpleCookie = SimpleCookie()
        jar.load(header)
        cookies.update({name: morsel.value for name, morsel in jar.items()})
    try:
        parsed = json.loads(raw) if raw else {}
    except ValueError:  # not JSON, or not UTF-8: no body to read
        parsed = {}
    return Answer(status, parsed if isinstance(parsed, dict) else {}, cookies)


def totp(secret_b32: str, step: int, digits: int = 6) -> str:
    """RFC 6238 over HMAC-SHA1 for one 30 s step, as `candleviewer.auth.totp` computes it."""
    secret = base64.b32decode(secret_b32.upper() + "=" * (-len(secret_b32) % 8))
    digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


@dataclass
class Driver:
    """The run directory, the session directory, the transport and the clock of one command."""

    run_dir: Path
    session_dir: Path
    send: Http = exchange
    clock: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep
    known: set[str] = field(default_factory=set)  # every credential this command handled

    def read(self, name: str) -> str:
        descriptor = os.open(self.run_dir / name, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, encoding="utf-8") as source:
            return source.read(MAX_FILE_BYTES)

    def roster(self) -> set[str]:
        return {str(user["username"]) for user in json.loads(self.read("roster.json"))["users"]}

    def credentials(self, user: str) -> tuple[str, str]:
        if user not in self.roster():
            raise Refused(NOT_A_USER)
        password, secret = self.read(f"pw-{user}"), self.read(f"totp-{user}").strip()
        self.known |= {password, secret}
        return password, secret

    def load(self, user: str) -> dict[str, Any]:
        try:
            descriptor = os.open(self.session_dir / f"{user}.json", os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return {}
        with os.fdopen(descriptor, encoding="utf-8") as source:
            session: dict[str, Any] = json.loads(source.read(MAX_FILE_BYTES))
        self.known |= {str(session.get("bearer", "")), str(session.get("csrf", ""))} - {""}
        return session

    def save(self, user: str, session: Mapping[str, Any]) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
        descriptor = os.open(self.session_dir / f"{user}.json", flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as out:
            os.fchmod(descriptor, 0o600)  # an existing file keeps no wider mode
            json.dump(dict(session), out)

    def code(self, secret: str, session: dict[str, Any]) -> str:
        """A code for a step this user has not used, waiting for the next one when needed."""
        while int(self.clock() // STEP_S) <= int(session.get("step", -1)):
            self.sleep(STEP_S - self.clock() % STEP_S + 0.5)
        session["step"] = int(self.clock() // STEP_S)
        made = totp(secret, session["step"])
        self.known.add(made)
        return made

    def post(self, path: str, body: Mapping[str, Any], headers: Mapping[str, str]) -> Answer:
        return self.send("POST", path, json.dumps(dict(body)).encode(), _json(headers))

    def signin(self, user: str) -> str:
        password, secret = self.credentials(user)
        session = self.load(user)
        login = self.post("/auth/login", {"identifier": user, "password": password}, {})
        if login.status != 200 or login.body.get("status") != "mfa_required":
            raise Refused(f"{SIGN_IN_FAILED}: login HTTP {login.status} {_code(login)}")
        mfa = {"mfa_token": login.body.get("mfa_token"), "method": "totp"}
        verify = self.post("/auth/mfa/verify", {**mfa, "code": self.code(secret, session)}, {})
        tokens = verify.body.get("tokens")
        bearer = tokens.get("access_token") if isinstance(tokens, dict) else None
        csrf = verify.cookies.get(CSRF_COOKIE)
        if verify.status != 200 or not isinstance(bearer, str) or not csrf:
            raise Refused(f"{SIGN_IN_FAILED}: verify HTTP {verify.status} {_code(verify)}")
        self.known |= {bearer, csrf}
        session |= {"bearer": bearer, "csrf": csrf}
        self.save(user, session)
        me = self.send("GET", "/me", None, _auth(session, write=False))
        if me.status != 200:
            raise Refused(f"{SIGN_IN_FAILED}: GET /me HTTP {me.status} {_code(me)}")
        return f"{user} signed in: HTTP {me.status} ({me.body.get('role', '-')})"

    def call(self, user: str, method: str, path: str, body: bytes | None) -> list[str]:
        session = self.load(user)
        if not session.get("bearer"):
            raise Refused(NO_SESSION)
        key = str(uuid.uuid4()) if method in WRITES else None
        answer = self.send(method, path, body, _auth(session, method in WRITES, key, body))
        lines = []
        if answer.status == 403 and answer.body.get("code") == "step_up_required":
            password, secret = self.credentials(user)
            challenge = {"password": password, "challenge_id": answer.body.get("challenge_id")}
            challenge["code"] = self.code(secret, session)
            up = self.post("/auth/step-up", challenge, _auth(session, write=True))
            if up.status != 200:
                raise Refused(f"{STEP_UP_FAILED}: HTTP {up.status} {_code(up)}")
            tokens = up.body.get("tokens")
            if isinstance(tokens, dict) and isinstance(tokens.get("access_token"), str):
                session["bearer"] = tokens["access_token"]  # a step-up that rotates the session
            session["csrf"] = up.cookies.get(CSRF_COOKIE, session["csrf"])
            self.known |= {str(session["bearer"]), str(session["csrf"])}
            self.save(user, session)
            lines.append(f"step-up {up.body.get('action_class', '-')}: HTTP {up.status} -")
            answer = self.send(method, path, body, _auth(session, method in WRITES, key, body))
        lines += [f"HTTP {answer.status} {_code(answer)}", self.masked(answer.body)]
        return lines

    def masked(self, body: Any) -> str:
        """The body as one JSON line: a field named for a credential, and any value this command
        handled or shaped as a bearer, shows as `***`."""

        def walk(node: Any, name: str = "") -> Any:
            if isinstance(node, dict):
                return {k: walk(v, str(k)) for k, v in node.items()}
            if isinstance(node, list):
                return [walk(item, name) for item in node]
            if isinstance(node, str) and (
                _SECRET_FIELD.fullmatch(name) or node in self.known or _JWT.search(node)
            ):
                return MASK
            return node

        text = json.dumps(walk(body), sort_keys=True)
        for value in sorted(self.known, key=len, reverse=True):
            text = text.replace(value, MASK) if value else text
        return text

    def scan(self, paths: Sequence[str]) -> tuple[list[str], int]:
        values = self.generated()
        lines, total = [], 0
        for path in paths:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor, "rb") as source:
                content = source.read(MAX_SCAN_BYTES)
            hits = sum(content.count(value) for value in values)
            total += hits
            lines.append(f"scan: {path}: {hits} hits")
        lines.append(f"scan: {total} hits in {len(paths)} paths, {len(values)} values searched")
        return lines, total

    def generated(self) -> set[bytes]:
        """Every value this run generated, in each form a text holds it in: never shown."""
        values: set[bytes] = set()
        for entry in sorted(os.listdir(self.run_dir)):
            if entry.startswith(("pw-", "totp-")) or entry == "lane.key":
                values.add(self.read(entry).strip().encode())
            elif entry == "kek":
                descriptor = os.open(self.run_dir / entry, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(descriptor, "rb") as source:
                    kek = source.read(MAX_FILE_BYTES)
                values |= {kek, kek.hex().encode(), base64.b64encode(kek)}
            elif entry == "stack.env":
                pairs = (
                    line.split("=", 1) for line in self.read(entry).splitlines() if "=" in line
                )
                values |= {value.encode() for name, value in pairs if name in SECRET_ENV}
        for entry in sorted(os.listdir(self.session_dir)):
            if entry.endswith(".json"):
                session = self.load(entry.removesuffix(".json"))
                values |= {str(session.get(k, "")).encode() for k in ("bearer", "csrf")}
        return {value for value in values if len(value) >= 8}


def _json(headers: Mapping[str, str]) -> dict[str, str]:
    return {"Content-Type": "application/json", **headers}


def _auth(
    session: Mapping[str, Any], write: bool, key: str | None = None, body: bytes | None = None
) -> dict[str, str]:
    """The session's bearer and CSRF cookie; on a write the CSRF header too, and its key."""
    headers = {"Authorization": f"Bearer {session['bearer']}"}
    headers["Cookie"] = f"{CSRF_COOKIE}={session['csrf']}"
    if write:
        headers["X-CSRF-Token"] = str(session["csrf"])
    if key is not None:
        headers["Idempotency-Key"] = key
    if body is not None:
        headers["Content-Type"] = "application/json"
    return headers


def _code(answer: Answer) -> str:
    code = answer.body.get("code")
    return code if isinstance(code, str) and re.fullmatch(r"[a-z_]{1,64}", code) else "-"


def _owner_uid(named: str | None) -> int:
    if named is None:
        return os.geteuid()
    if _UID.fullmatch(named) is None:
        raise Refused(BAD_UID)
    return int(named)


def seeded_run_dir(value: str, owner: int) -> Path:
    """The run directory as the seed left it: real, the owner's alone, and seeded."""
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise Refused(NOT_ROOTED)
    if os.path.realpath(path) != str(path) or not path.is_dir():
        raise Refused(LINKED)
    info = path.stat()
    if info.st_uid != owner or info.st_mode & 0o077:
        raise Refused(SHARED)
    if not os.path.isfile(path / SEEDED_MARKER):
        raise Refused(NOT_SEEDED)
    return path


def gate(settings: Settings, run_dir: str, owner: str | None) -> Path:
    """ADR-0036's structural gate, then the seeded run directory; before any read or request."""
    try:
        armed(settings)
    except CliRefused as refused:
        raise Refused(str(refused)) from None  # Settings' fixed messages: a rule, never a value
    uid = _owner_uid(owner)
    return seeded_run_dir(run_dir, uid)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m cvdev.account_fixture.drive",
        description="Sign in, call the api and scan records on the account fixture stack.",
    )
    parser.add_argument("--run-dir", required=True, help="the run's directory, read-only")
    parser.add_argument("--session-dir", required=True, help="where the sessions are kept")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("signin").add_argument("user")
    call = commands.add_parser("call")
    call.add_argument("user")
    call.add_argument("method")
    call.add_argument("path")
    call.add_argument("--body-json", default=None)
    commands.add_parser("scan").add_argument("paths", nargs="+")
    return parser


def run(args: argparse.Namespace, settings: Settings, driver: Driver, owner: str | None) -> int:
    """Do what `args` asks after the gate; print its lines. Raises `Refused`."""
    driver.run_dir = gate(settings, args.run_dir, owner)
    if args.command == "signin":
        sys.stdout.write(f"account-fixture: {driver.signin(args.user)}\n")
        return 0
    if args.command == "scan":
        lines, hits = driver.scan(args.paths)
        sys.stdout.write("".join(f"{line}\n" for line in lines))
        return EXIT_HITS if hits else 0
    method = str(args.method).upper()
    if method not in METHODS or _PATH.fullmatch(args.path) is None:
        raise Refused(BAD_REQUEST)
    body = None
    if args.body_json is not None:
        try:
            parsed = json.loads(args.body_json)
        except ValueError:
            raise Refused(BAD_BODY) from None
        if not isinstance(parsed, dict):
            raise Refused(BAD_BODY)
        body = json.dumps(parsed).encode()
    sys.stdout.write(
        "".join(f"{line}\n" for line in driver.call(args.user, method, args.path, body))
    )
    return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    send: Http = exchange,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
    environ: Mapping[str, str] = os.environ,
) -> int:
    args = _parser().parse_args(argv)
    driver = Driver(Path(args.run_dir), Path(args.session_dir), send, clock, sleep)
    try:
        try:
            resolved = settings if settings is not None else Settings()
        except ValueError:  # a pydantic ValidationError: its text may hold an input value
            raise Refused(INVALID_SETTINGS) from None
        return run(args, resolved, driver, environ.get(RUN_UID_VARIABLE))
    except Refused as refused:
        sys.stderr.write(f"account-fixture: refused: {refused}\n")
        return EXIT_REFUSED
    except Exception as failure:  # nothing unexpected may print a traceback, path or value
        sys.stderr.write(f"account-fixture: refused: {FAILED} ({type(failure).__name__})\n")
        return EXIT_REFUSED


if __name__ == "__main__":  # pragma: no cover - `python -m`; `main` is tested in process
    raise SystemExit(main())
