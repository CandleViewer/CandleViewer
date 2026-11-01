"""#2893's closure: the account-fixture stack's driver (`cvdev.account_fixture.drive`).

`main` runs in process against a fake api (the transport is injected) and a fake clock (`sleep`
moves it), so nothing waits on a wall clock and nothing leaves the process. The fake api holds the
api's rules the driver depends on: one TOTP step per use, the CSRF double-submit on a write, and a
`403 step_up_required` challenge answered by `POST /auth/step-up`. Every credential is fabricated
here and every output is searched for it.
"""

from __future__ import annotations

import ast
import base64
import builtins
import http.client
import json
import logging
import os
import re
import secrets
import stat
import uuid
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import structlog
from pydantic import SecretStr

from candleviewer.auth.totp import (
    base32_to_secret,
    generate_code,
    generate_secret,
    secret_to_base32,
)
from candleviewer.settings import Environment, FeedMode, Settings
from cvdev.account_fixture import cli, drive
from cvdev.account_fixture.drive import Answer

USER = "qa-owner-1"
START = 1_800_000_010.0  # ten seconds into a 30 s step
ACCOUNT = {"exchange": "bybit", "environment": "demo", "kind": "main", "label": "QA Main"}
ACCOUNT |= {"exchange_uid": "90000001"}
RUN_MARK = "runmark-4e2"
#: The env file's names whose values `scan` searches, spelled out apart from the module's own.
SECRET_ENV = (
    "POSTGRES_PASSWORD",
    "CV_PG_DSN",
    "CV_AUTH_PEPPER",
    "CV_AUTH_TOTP_KEY_HEX",
    "CV_AUTH_RECOVERY_HMAC_KEY_HEX",
    "CV_AUTH_CSRF_KEY_HEX",
)


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [n for n in os.environ if n.upper().startswith("CV_")]:
        monkeypatch.delenv(name)


class Clock:
    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        assert 0 < seconds <= 31  # never a wait past the next step
        self.now += seconds


class Run:
    """A seeded run directory (as the seed leaves it), a session directory and the values in
    them; every one of them is fabricated here."""

    def __init__(self, tmp_path: Path) -> None:
        self.dir, self.sessions = tmp_path / "run", tmp_path / "session"
        self.dir.mkdir(mode=0o700)
        self.sessions.mkdir(mode=0o700)
        self.password = secrets.token_urlsafe(24)
        self.secret = secret_to_base32(generate_secret())
        self.kek, self.lane = secrets.token_bytes(32), secrets.token_hex(32)
        self.env = {name: secrets.token_urlsafe(18) for name in SECRET_ENV}
        self.pepper = self.env["CV_AUTH_PEPPER"]
        env_file = "".join(f"{name}={value}\n" for name, value in self.env.items())
        roster = {"users": [{"username": USER, "role": "owner"}]}
        files: dict[str, bytes] = {
            f"pw-{USER}": self.password.encode(),
            f"totp-{USER}": self.secret.encode(),
            "kek": self.kek,
            "lane.key": self.lane.encode(),
            "roster.json": json.dumps(roster).encode(),
            "stack.env": f"{env_file}POSTGRES_DB=acctfix_test\n".encode(),  # a name, not a secret
            ".seeded": b"",
        }
        for name, content in files.items():
            (self.dir / name).write_bytes(content)


class FakeApi:
    """The api as the driver meets it, recording each request (method, path, body, headers)."""

    def __init__(self, run: Run, clock: Clock, *, rotate: bool = False) -> None:
        self.run, self.clock, self.rotate = run, clock, rotate
        self.calls: list[tuple[str, str, bytes | None, dict[str, str]]] = []
        self.used: set[int] = set()
        self.bearer, self.csrf = "bearer-" + secrets.token_hex(16), "csrf-" + secrets.token_hex(16)
        self.elevated = False
        self.challenge = str(uuid.uuid4())
        self.fail: dict[str, Answer] = {}
        self.codes: list[str] = []

    def code_ok(self, code: object) -> bool:
        step = int(self.clock() // 30)
        ok = step not in self.used and code == generate_code(
            base32_to_secret(self.run.secret), step
        )
        self.used.add(step)
        self.codes.append(str(code))
        return ok

    def __call__(
        self, method: str, path: str, body: bytes | None, headers: Mapping[str, str]
    ) -> Answer:
        self.calls.append((method, path, body, dict(headers)))
        if f"{method} {path}" in self.fail:
            return self.fail[f"{method} {path}"]
        sent = json.loads(body) if body else {}
        if path == "/auth/login":
            ok = sent == {"identifier": USER, "password": self.run.password}
            return (
                Answer(200, {"status": "mfa_required", "mfa_token": "mfa-x"}, {}) if ok else _401()
            )
        if path == "/auth/mfa/verify":
            if sent.get("mfa_token") != "mfa-x" or not self.code_ok(sent.get("code")):
                return _401()
            tokens = {"access_token": self.bearer, "refresh_token": None}
            return Answer(
                200, {"status": "authenticated", "tokens": tokens}, {drive.CSRF_COOKIE: self.csrf}
            )
        if headers.get("Authorization") != f"Bearer {self.bearer}":
            return Answer(401, {"code": "unauthenticated"}, {})
        if method != "GET" and (
            headers.get("X-CSRF-Token") != self.csrf
            or headers.get("Cookie") != f"{drive.CSRF_COOKIE}={self.csrf}"
        ):
            return Answer(403, {"code": "csrf_token_invalid"}, {})
        if path == "/me":
            return Answer(200, {"user": {"username": USER}, "role": "owner"}, {})
        if path == "/auth/step-up":
            right = sent.get("password") == self.run.password
            if not (
                right
                and sent.get("challenge_id") == self.challenge
                and self.code_ok(sent.get("code"))
            ):
                return Answer(401, {"code": "mfa_invalid"}, {})
            self.elevated = True
            answer: dict[str, Any] = {"action_class": "keys", "single_use": False}
            cookies: dict[str, str] = {}
            if self.rotate:
                self.bearer, self.csrf = (
                    "bearer-" + secrets.token_hex(16),
                    "csrf-" + secrets.token_hex(16),
                )
                answer["tokens"] = {"access_token": self.bearer}
                cookies[drive.CSRF_COOKIE] = self.csrf
            return Answer(200, answer, cookies)
        if path == "/exchange-accounts" and method == "POST":
            if not self.elevated:
                problem = {"code": "step_up_required", "challenge_id": self.challenge}
                return Answer(403, problem | {"action_class": "keys"}, {})
            # an answer that echoes every credential it can, to test the masking: the password,
            # the TOTP secret and the last code under a name that is not a credential's
            echo = {"bearer_echo": self.bearer, "nested": [{"api_secret": "x" * 12}]}
            echo |= {"note": f"session {self.csrf}", "jwt": "aaaaaaaaaa.bbbbbbbbbb.cccccccccc"}
            echo |= {"echo": [self.run.password, self.run.secret, self.codes[-1]]}
            return Answer(201, {"id": "acct-1", "status": "pending", **echo}, {})
        return Answer(404, {"code": "not_found"}, {})


def _401() -> Answer:
    return Answer(401, {"code": "mfa_invalid"}, {})


def _settings(tmp_path: Path, **fields: Any) -> Settings:
    base: dict[str, Any] = {
        "environment": Environment.DEMO,
        "feed": FeedMode.SYNTHETIC,
        "account_fixture": "compliant",
        "account_fixture_dir": str(tmp_path / "state"),
        "test_clock": False,
    }
    return Settings.model_construct(**{**base, **fields})


@pytest.fixture
def run(tmp_path: Path) -> Run:
    return Run(tmp_path)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def api(run: Run, clock: Clock) -> FakeApi:
    return FakeApi(run, clock)


def _go(
    capsys: pytest.CaptureFixture[str],
    run: Run,
    api: FakeApi,
    clock: Clock,
    *args: str,
    settings: Settings | None = None,
    owner: str | None = None,
    run_dir: str | None = None,
) -> tuple[int, str, str]:
    argv = ["--run-dir", run_dir or str(run.dir), "--session-dir", str(run.sessions), *args]
    environ = {} if owner is None else {drive.RUN_UID_VARIABLE: owner}
    code = drive.main(
        argv,
        settings=settings or _settings(run.dir.parent),
        send=api,
        clock=clock,
        sleep=clock.sleep,
        environ=environ,
    )
    out, err = capsys.readouterr()
    return code, out, err


def _known(run: Run, api: FakeApi) -> list[str]:
    """Every credential of the run, as text, the KEK in each form `scan` searches: none may ever
    be printed."""
    codes = [generate_code(base32_to_secret(run.secret), step) for step in api.used]
    kek = [run.kek.hex(), base64.b64encode(run.kek).decode(), run.kek.decode("latin-1")]
    return [run.password, run.secret, api.bearer, api.csrf, *kek, run.lane, *codes]


# --- Sign-in, the session and T3 -------------------------------------------------------------


def test_drive_signs_in_and_keeps_the_session_out_of_every_output(
    tmp_path: Path, run: Run, api: FakeApi, clock: Clock, capsys: pytest.CaptureFixture[str]
) -> None:
    """The session file is rewritten whole and 0600, whatever was there (here a longer 0644 one)."""
    session_file = run.sessions / f"{USER}.json"
    session_file.write_text('{"step": 0}' + " " * 4096, encoding="utf-8")

    code, out, err = _go(capsys, run, api, clock, "signin", USER)

    assert (code, out, err) == (0, f"account-fixture: {USER} signed in: HTTP 200 (owner)\n", "")
    assert stat.S_IMODE(session_file.stat().st_mode) == 0o600
    text = session_file.read_text(encoding="utf-8")
    session = json.loads(text)
    assert text == json.dumps(session)  # nothing of the longer file is left after it
    kept = (session["bearer"], session["csrf"]) == (api.bearer, api.csrf)  # a boolean
    assert kept and session["step"] == int(START // 30)
    echoed = any(value in text for value in _known(run, api) for text in (out, err))
    assert not echoed


def test_drive_prints_no_credential_token_or_code(
    run: Run,
    api: FakeApi,
    clock: Clock,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T3: an answer that echoes the bearer, the CSRF token, the password, the TOTP secret, the
    code just used, a JWT-shaped value and a field named for a secret prints each as `***`; no
    password, TOTP secret, code or token reaches an output."""
    caplog.set_level(logging.DEBUG)
    with structlog.testing.capture_logs() as events:
        signed = _go(capsys, run, api, clock, "signin", USER)
        body = json.dumps(ACCOUNT)
        called = _go(
            capsys, run, api, clock, "call", USER, "POST", "/exchange-accounts", "--body-json", body
        )

    assert signed[0] == called[0] == 0
    printed = json.loads(called[1].splitlines()[-1])
    assert printed["bearer_echo"] == printed["jwt"] == printed["nested"][0]["api_secret"] == "***"
    assert printed["note"] == "session ***" and printed["id"] == "acct-1"
    assert printed["echo"] == ["***"] * 3
    shown = [*signed[1:], *called[1:], *map(str, events), *(r.getMessage() for r in caplog.records)]
    echoed = any(value in text for value in _known(run, api) for text in shown)  # a boolean
    assert not echoed


def test_drive_waits_for_an_unused_totp_step(
    run: Run, api: FakeApi, clock: Clock, capsys: pytest.CaptureFixture[str]
) -> None:
    """The sign-in uses the current step; the step-up right after it waits for the next one (the
    api refuses a step a user has used), and the session keeps the step last used."""
    assert _go(capsys, run, api, clock, "signin", USER)[0] == 0
    first = int(clock() // 30)

    code, out, _ = _go(
        capsys,
        run,
        api,
        clock,
        "call",
        USER,
        "POST",
        "/exchange-accounts",
        "--body-json",
        json.dumps(ACCOUNT),
    )

    assert code == 0 and "HTTP 201 -" in out
    assert int(clock() // 30) == first + 1 and api.used == {first, first + 1}
    session = json.loads((run.sessions / f"{USER}.json").read_text(encoding="utf-8"))
    assert session["step"] == first + 1


def test_drive_sends_the_csrf_header_and_an_idempotency_key(
    run: Run, api: FakeApi, clock: Clock, capsys: pytest.CaptureFixture[str]
) -> None:
    api.elevated = True
    _go(capsys, run, api, clock, "signin", USER)
    _go(capsys, run, api, clock, "call", USER, "GET", "/me")
    _go(
        capsys,
        run,
        api,
        clock,
        "call",
        USER,
        "POST",
        "/exchange-accounts",
        "--body-json",
        json.dumps(ACCOUNT),
    )

    (_, _, _, read), (_, _, body, write) = api.calls[-2:]
    assert "X-CSRF-Token" not in read and "Idempotency-Key" not in read
    expected = {"Authorization", "Cookie", "X-CSRF-Token", "Idempotency-Key", "Content-Type"}
    assert set(write) == expected
    matched = write["X-CSRF-Token"] == api.csrf and write["Cookie"].endswith(api.csrf)  # a boolean
    assert matched
    assert uuid.UUID(write["Idempotency-Key"]).version == 4
    assert json.loads(body or b"") == ACCOUNT


@pytest.mark.parametrize("rotate", [False, True], ids=["grace", "rotating"])
def test_drive_steps_up_and_resends_the_held_request_unchanged(
    rotate: bool, run: Run, clock: Clock, capsys: pytest.CaptureFixture[str]
) -> None:
    """A `403 step_up_required` is answered with the password, a fresh code and the challenge's
    id; the held request goes again with the same body and `Idempotency-Key`, and with the new
    bearer and CSRF token if the step-up handed new ones."""
    api = FakeApi(run, clock, rotate=rotate)
    _go(capsys, run, api, clock, "signin", USER)

    code, out, err = _go(
        capsys,
        run,
        api,
        clock,
        "call",
        USER,
        "POST",
        "/exchange-accounts",
        "--body-json",
        json.dumps(ACCOUNT),
    )

    assert (code, err) == (0, "")
    assert out.splitlines()[:2] == ["step-up keys: HTTP 200 -", "HTTP 201 -"]
    held, step_up, again = api.calls[-3:]
    assert step_up[:2] == ("POST", "/auth/step-up")
    sent = json.loads(step_up[2] or b"")
    assert (
        set(sent) == {"password", "code", "challenge_id"} and sent["challenge_id"] == api.challenge
    )
    assert (again[0], again[1], again[2]) == (held[0], held[1], held[2])
    assert again[3]["Idempotency-Key"] == held[3]["Idempotency-Key"]
    renewed = again[3]["Authorization"] == f"Bearer {api.bearer}"  # a boolean: no token shown
    assert renewed and (again[3]["Authorization"] != held[3]["Authorization"]) is rotate


def test_a_403_that_asks_for_no_step_up_starts_none(
    run: Run, api: FakeApi, clock: Clock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Only `403 step_up_required` starts a step-up: any other refusal is printed as it is, with
    no password sent and no TOTP step spent."""
    assert _go(capsys, run, api, clock, "signin", USER)[0] == 0
    api.fail["POST /exchange-accounts"] = Answer(403, {"code": "forbidden"}, {})
    sent_before = len(api.calls)

    code, out, err = _go(
        capsys, run, api, clock, "call", USER, "POST", "/exchange-accounts", "--body-json", "{}"
    )

    assert (code, err, out.splitlines()[0]) == (0, "", "HTTP 403 forbidden")
    assert [c[1] for c in api.calls[sent_before:]] == ["/exchange-accounts"]


def test_a_field_named_for_a_credential_is_masked_in_every_form_of_its_name(
    run: Run, api: FakeApi, clock: Clock, capsys: pytest.CaptureFixture[str]
) -> None:
    """Recovery codes, the TOTP enrolment URI (it holds the secret) and a camelCase or upper-case
    credential name are masked by name, though the driver never handled their values; `status`
    and `code_count` are not credentials' names and print as they are."""
    assert _go(capsys, run, api, clock, "signin", USER)[0] == 0
    named: dict[str, Any] = {"recovery_codes": ["rc-1a2b-3c4d", "rc-5e6f-7a8b"]}
    named |= {"recoveryCodes": ["rc-9c0d-1e2f"], "otpauth_uri": "otpauth://totp/x?secret=MZXW6"}
    named |= {"otpauthUri": "otpauth://totp/y?secret=NBSWY", "accessToken": "av-1"}
    named |= {"API_SECRET": "sv-2", "mfaToken": "mv-3", "refreshTokens": ["rv-4"]}  # a plural
    api.fail["GET /auth/mfa/totp"] = Answer(200, {**named, "status": "ok", "code_count": 10}, {})

    code, out, _ = _go(capsys, run, api, clock, "call", USER, "GET", "/auth/mfa/totp")

    printed = json.loads(out.splitlines()[-1])
    masked = {k: ["***"] * len(v) if isinstance(v, list) else "***" for k, v in named.items()}
    assert code == 0 and {name: printed[name] for name in named} == masked
    assert (printed["status"], printed["code_count"]) == ("ok", 10)


def test_a_failed_sign_in_or_step_up_is_one_fixed_line(
    run: Run, api: FakeApi, clock: Clock, capsys: pytest.CaptureFixture[str]
) -> None:
    api.fail["POST /auth/login"] = Answer(
        401, {"code": "invalid_credentials", "detail": run.password}, {}
    )
    code, out, err = _go(capsys, run, api, clock, "signin", USER)
    assert (code, out) == (2, "")
    assert (
        err
        == f"account-fixture: refused: {drive.SIGN_IN_FAILED}: login HTTP 401 invalid_credentials\n"
    )
    del api.fail["POST /auth/login"]
    assert _go(capsys, run, api, clock, "signin", USER)[0] == 0
    api.fail["POST /auth/step-up"] = Answer(401, {"code": "mfa_invalid"}, {})

    code, out, err = _go(
        capsys, run, api, clock, "call", USER, "POST", "/exchange-accounts", "--body-json", "{}"
    )

    assert (code, out) == (2, "")
    assert err == f"account-fixture: refused: {drive.STEP_UP_FAILED}: HTTP 401 mfa_invalid\n"
    assert [c[1] for c in api.calls[-2:]] == ["/exchange-accounts", "/auth/step-up"]  # not re-sent
    session = json.loads((run.sessions / f"{USER}.json").read_text(encoding="utf-8"))
    assert session["step"] == int(clock() // 30)  # the refused step-up's step is kept as spent


@pytest.mark.parametrize(
    ("route", "status", "answer", "line"),
    [
        ("POST /auth/login", 200, {"status": "authenticated"}, "login HTTP 200 -"),
        ("POST /auth/mfa/verify", 401, {"code": "mfa_invalid"}, "verify HTTP 401 mfa_invalid"),
        ("GET /me", 401, {"code": "unauthenticated"}, "GET /me HTTP 401 unauthenticated"),
    ],
)
def test_a_sign_in_that_does_not_complete_is_one_fixed_line(
    route: str,
    status: int,
    answer: dict[str, str],
    line: str,
    run: Run,
    api: FakeApi,
    clock: Clock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A login that asks for no second factor is a refusal too: the driver signs in with TOTP."""
    api.fail[route] = Answer(status, {**answer, "detail": run.password}, {})

    code, out, err = _go(capsys, run, api, clock, "signin", USER)

    assert (code, out) == (2, "")
    assert err == f"account-fixture: refused: {drive.SIGN_IN_FAILED}: {line}\n"


def test_a_refused_verify_spends_its_step_and_the_next_sign_in_waits(
    run: Run, api: FakeApi, clock: Clock, capsys: pytest.CaptureFixture[str]
) -> None:
    """The api can keep the step of a refused verify as used: the session keeps it too, so the
    next sign-in waits for another step instead of being refused again."""
    api.fail["POST /auth/mfa/verify"] = Answer(401, {"code": "mfa_invalid"}, {})
    assert _go(capsys, run, api, clock, "signin", USER)[0] == 2
    spent = int(clock() // 30)
    api.used.add(spent)  # the api kept the refused step as used
    del api.fail["POST /auth/mfa/verify"]

    code, _, err = _go(capsys, run, api, clock, "signin", USER)

    assert (code, err) == (0, "") and int(clock() // 30) == spent + 1


def test_a_root_one_shot_drives_a_run_dir_owned_by_the_uid_it_is_named(
    run: Run,
    api: FakeApi,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The stack's case: the one-shot runs as root and compose names the invoking user's uid, so
    root passes the gate for a directory that uid owns (the matrix below refuses the rest)."""
    owner = str(run.dir.stat().st_uid)
    monkeypatch.setattr(os, "geteuid", lambda: 0)

    code, _, err = _go(capsys, run, api, clock, "signin", USER, owner=owner)

    assert (code, err) == (0, "") and (run.sessions / f"{USER}.json").exists()


def test_main_reads_the_settings_from_the_environment_when_none_are_given(
    run: Run,
    api: FakeApi,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The one-shot's own path: `Settings()` from the variables the overlay gives it."""
    env = {"ENVIRONMENT": "demo", "FEED": "synthetic", "ACCOUNT_FIXTURE": "compliant"}
    env |= {"ACCOUNT_FIXTURE_DIR": str(run.dir.parent / "state")}
    for name, value in env.items():
        monkeypatch.setenv(f"CV_{name}", value)
    argv = ["--run-dir", str(run.dir), "--session-dir", str(run.sessions), "signin", USER]

    code = drive.main(argv, send=api, clock=clock, sleep=clock.sleep, environ={})

    signed = f"account-fixture: {USER} signed in: HTTP 200 (owner)\n"
    assert (code, *capsys.readouterr()) == (0, signed, "")


@pytest.mark.parametrize(
    ("raw", "body"),
    [
        (b'{"status": "authenticated"}', {"status": "authenticated"}),
        (b"[1, 2]", {}),  # not an object
        (b"\xff not json", {}),
        (b"", {}),  # no body, as a 204 has
    ],
)
def test_the_transport_is_one_bounded_request_whose_answer_is_an_object(
    raw: bytes, body: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`exchange`, against a stand-in connection: one request to the api by its service name,
    the body read up to its bound, the `__Host-` cookie parsed from its attributes, the
    connection closed, and an answer that is not a JSON object read as an empty one."""
    seen: list[tuple[Any, ...]] = []
    cookie = f"{drive.CSRF_COOKIE}=csrf-1; Path=/; Secure; HttpOnly; SameSite=Strict"

    class Connection:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            seen.append(("open", host, port, timeout))

        def request(self, method: str, path: str, body: bytes, headers: dict[str, str]) -> None:
            seen.append(("request", method, path, body, headers))

        def getresponse(self) -> Any:
            message = http.client.HTTPMessage()
            message["Set-Cookie"] = cookie
            return SimpleNamespace(status=201, headers=message, read=reading)

        def close(self) -> None:
            seen.append(("close",))

    def reading(limit: int) -> bytes:
        seen.append(("read", limit))
        return raw

    monkeypatch.setattr(http.client, "HTTPConnection", Connection)  # what `exchange` opens

    answer = drive.exchange("POST", "/me", b"{}", {"X-A": "1"})

    assert answer == Answer(201, body, {drive.CSRF_COOKIE: "csrf-1"})
    assert seen == [
        ("open", "api", 8000, drive.TIMEOUT_S),
        ("request", "POST", "/me", b"{}", {"X-A": "1"}),
        ("read", drive.MAX_BODY_BYTES),
        ("close",),
    ]


def test_settings_the_driver_cannot_load_are_one_fixed_line(
    run: Run,
    api: FakeApi,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CV_ENVIRONMENT", RUN_MARK)  # a value `Settings` refuses is never echoed
    argv = ["--run-dir", str(run.dir), "--session-dir", str(run.sessions), "signin", USER]

    code = drive.main(argv, send=api, clock=clock, sleep=clock.sleep, environ={})

    assert (code, *capsys.readouterr()) == (
        2,
        "",
        f"account-fixture: refused: {drive.INVALID_SETTINGS}\n",
    )
    assert api.calls == []


def test_an_unexpected_failure_names_its_class_only(
    run: Run, clock: Clock, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(*args: Any) -> Answer:
        raise ConnectionRefusedError(f"refused: {args!r} {run.password}")

    code, out, err = (
        drive.main(
            ["--run-dir", str(run.dir), "--session-dir", str(run.sessions), "signin", USER],
            settings=_settings(run.dir.parent),
            send=broken,
            clock=clock,
            sleep=clock.sleep,
            environ={},
        ),
        *capsys.readouterr(),
    )

    named = (
        err == f"account-fixture: refused: {drive.FAILED} (ConnectionRefusedError)\n"
    )  # a boolean
    assert (code, out, named) == (2, "", True)


# --- T1: the gate, and the refusals ----------------------------------------------------------


def _prepare(kind: str, run: Run, tmp: Path, patch: pytest.MonkeyPatch) -> tuple[str, str | None]:
    """The `--run-dir` and the named uid for `kind`, the run directory prepared as it needs."""
    match kind:
        case "relative":
            return "run", None
        case "link":
            (tmp / "link").symlink_to(run.dir)
            return str(tmp / "link"), None
        case "other-owner":
            other = os.geteuid() + 1
            patch.setattr(os, "geteuid", lambda: other)
        case "root":
            if run.dir.stat().st_uid == 0:
                pytest.skip("the suite runs as root: no run directory here is another user's")
            patch.setattr(os, "geteuid", lambda: 0)
        case "named-other":
            return str(run.dir), str(run.dir.stat().st_uid + 1)
        case "named-not-digits":
            return str(run.dir), RUN_MARK
        case "group-access":
            run.dir.chmod(0o750)
        case "not-seeded":
            (run.dir / ".seeded").unlink()
    return str(run.dir), None


KEY = SecretStr("k")
#: Settings fields, or `env`, `dir` (a run directory kind) or `args` (the command); the reason.
REFUSALS: dict[str, tuple[dict[str, Any], str]] = {
    "live": ({"environment": Environment.LIVE}, cli.LIVE),
    "testnet": ({"environment": Environment.TESTNET}, "CV_ENVIRONMENT=demo"),
    "live-feed": (
        {"feed": FeedMode.LIVE, "bybit_api_key": KEY, "bybit_api_secret": KEY},
        "CV_FEED",
    ),
    "exchange-key": ({"bybit_api_key": KEY}, "CV_BYBIT_API_*"),
    "undeclared-exchange-variable": ({"env": {"CV_BYBIT_API_OTHER": "x"}}, "CV_BYBIT_API_*"),
    "test-clock": ({"test_clock": True}, "CV_TEST_CLOCK"),
    "fixture-unset": ({"account_fixture": None}, cli.NOT_ARMED),
    "state-dir-unset": ({"account_fixture_dir": None}, cli.NO_DIR),
    "relative-run-dir": ({"dir": "relative"}, drive.NOT_ROOTED),
    "symlinked-run-dir": ({"dir": "link"}, drive.LINKED),
    "run-dir-of-another-owner": ({"dir": "other-owner"}, drive.SHARED),
    "root-with-no-uid-named": ({"dir": "root"}, drive.SHARED),
    "named-uid-that-does-not-own-it": ({"dir": "named-other"}, drive.SHARED),
    "named-uid-not-digits": ({"dir": "named-not-digits"}, drive.BAD_UID),
    "run-dir-open-to-the-group": ({"dir": "group-access"}, drive.SHARED),
    "run-dir-not-seeded": ({"dir": "not-seeded"}, drive.NOT_SEEDED),
    "user-off-the-roster": ({"args": ("signin", "../pw-qa-owner-1")}, drive.NOT_A_USER),
    "call-as-a-user-off-the-roster": ({"args": ("call", "../x", "GET", "/me")}, drive.NOT_A_USER),
    "call-before-sign-in": ({"args": ("call", USER, "GET", "/me")}, drive.NO_SESSION),
    "method-off-the-list": ({"args": ("call", USER, "TRACE", "/me")}, drive.BAD_REQUEST),
    "path-with-a-host": ({"args": ("call", USER, "GET", "http://x/me")}, drive.BAD_REQUEST),
    "body-not-an-object": (
        {"args": ("call", USER, "POST", "/x", "--body-json", "[1]")},
        drive.BAD_BODY,
    ),
    "body-not-json": (
        {"args": ("call", USER, "POST", "/x", "--body-json", RUN_MARK)},
        drive.BAD_BODY,
    ),
}


@pytest.mark.parametrize("name", REFUSALS)
def test_drive_refuses_outside_the_dev_gate(
    name: str,
    tmp_path: Path,
    run: Run,
    api: FakeApi,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """T1 for the driver: each refusal is exit 2 and one fixed line, before any request (the
    session ones after the gate, before any request too); nothing is written, nothing echoed."""
    fields, reason = dict(REFUSALS[name][0]), REFUSALS[name][1]
    extra = {key: fields.pop(key) for key in ("env", "dir", "args") if key in fields}
    for key, value in extra.get("env", {}).items():
        monkeypatch.setenv(key, value)
    run_dir, owner = _prepare(extra.get("dir", ""), run, tmp_path, monkeypatch)
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    args = extra.get("args", ("signin", USER))

    code, out, err = _go(
        capsys,
        run,
        api,
        clock,
        *args,
        settings=_settings(tmp_path, **fields),
        owner=owner,
        run_dir=run_dir,
    )

    assert (code, out) == (2, "") and api.calls == []
    assert err.startswith("account-fixture: refused: ") and reason in err and err.count("\n") == 1
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before
    assert not any(mark in err for mark in (RUN_MARK, str(tmp_path), *_known(run, api)))


# --- T2: the run directory is read, the session file alone is written --------------------------


def test_drive_reads_only_the_run_dir_and_writes_only_the_session_file(
    tmp_path: Path,
    run: Run,
    api: FakeApi,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    opened: list[tuple[Path, int]] = []
    real_open, other = os.open, []

    def spy(path: Any, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        opened.append((Path(path), flags))
        return real_open(path, flags, mode, **kwargs)

    def watch_open(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if set(mode) & set("wax+"):
            other.append(str(file))
        return real_builtin_open(file, mode, *args, **kwargs)

    real_builtin_open = builtins.open
    before = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    with monkeypatch.context() as patch:
        patch.setattr(os, "open", spy)
        patch.setattr(builtins, "open", watch_open)
        _go(capsys, run, api, clock, "signin", USER)
        _go(
            capsys, run, api, clock, "call", USER, "POST", "/exchange-accounts", "--body-json", "{}"
        )

    writes = {path for path, flags in opened if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)}
    reads = {path for path, flags in opened if not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)}
    session = run.sessions / f"{USER}.json"
    assert writes == {session} and other == []
    assert all(flags & os.O_NOFOLLOW for _, flags in opened)
    assert {path.parent for path in reads} <= {run.dir, run.sessions}
    assert {path.name for path in reads if path.parent == run.dir} == {
        "roster.json",
        f"pw-{USER}",
        f"totp-{USER}",
    }
    after = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("*") if p.is_file()}
    assert set(after) - set(before) == {session} and all(after[p] == t for p, t in before.items())


# --- scan --------------------------------------------------------------------------------------


def test_scan_reports_counts_never_values(
    tmp_path: Path, run: Run, api: FakeApi, clock: Clock, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _go(capsys, run, api, clock, "signin", USER)[0] == 0
    (run.sessions / "notes.txt").write_text("not a session", encoding="utf-8")  # passed over
    clean, dirty = tmp_path / "clean.md", tmp_path / "dirty.log"
    clean.write_text("HTTP 201 - acctfix_test, a name and no value\n", encoding="utf-8")
    dirty.write_text(f"x {run.password} y {run.kek.hex()} z {api.bearer} {run.pepper}\n", "utf-8")

    found = _go(capsys, run, api, clock, "scan", str(clean), str(dirty))
    none = _go(capsys, run, api, clock, "scan", str(clean))

    assert found[0] == 1 and none[0] == 0  # exit 1 on a hit, as the runbook says
    lines = found[1].splitlines()
    assert lines[:2] == [f"scan: {clean}: 0 hits", f"scan: {dirty}: 4 hits"]
    assert re.fullmatch(r"scan: 4 hits in 2 paths, \d+ values searched", lines[2])
    echoed = any(value in found[1] + none[1] for value in [*_known(run, api), run.pepper])
    assert not echoed


#: Each value `scan` searches, by where the run keeps it: the run directory's files (the KEK in
#: each of its three forms), the env file's secrets and a session's tokens.
RUN_DIR_SOURCES = ("pw", "totp", "lane.key", "kek", "kek-hex", "kek-base64")
SCAN_SOURCES = (*RUN_DIR_SOURCES, *SECRET_ENV, "bearer", "csrf")


@pytest.mark.parametrize("source", SCAN_SOURCES)
def test_scan_finds_each_value_the_run_generated(
    source: str,
    tmp_path: Path,
    run: Run,
    api: FakeApi,
    clock: Clock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _go(capsys, run, api, clock, "signin", USER)[0] == 0
    values = {"pw": run.password.encode(), "totp": run.secret.encode(), "kek": run.kek}
    values |= {"lane.key": run.lane.encode(), "kek-hex": run.kek.hex().encode()}
    values |= {"kek-base64": base64.b64encode(run.kek), "bearer": api.bearer.encode()}
    values |= {"csrf": api.csrf.encode(), **{n: v.encode() for n, v in run.env.items()}}
    path = tmp_path / "saved.log"
    path.write_bytes(b"before " + values[source] + b" after\n")

    code, out, err = _go(capsys, run, api, clock, "scan", str(path))

    assert (code, err, out.splitlines()[0]) == (1, "", f"scan: {path}: 1 hits")


def test_scan_refuses_what_it_cannot_read_whole(
    tmp_path: Path,
    run: Run,
    api: FakeApi,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A count for a part not read would read as clean: a path past the read bound is refused,
    and a symlink is not followed; each is one fixed line, never a count."""
    longer, link = tmp_path / "longer.log", tmp_path / "link.log"
    longer.write_bytes(b"x" * 2048 + run.password.encode())
    link.symlink_to(longer)
    monkeypatch.setattr(drive, "MAX_SCAN_BYTES", 1024)

    past_the_bound = _go(capsys, run, api, clock, "scan", str(longer))
    linked = _go(capsys, run, api, clock, "scan", str(link))

    assert past_the_bound == (2, "", f"account-fixture: refused: {drive.SCAN_TOO_LONG}\n")
    assert linked == (2, "", f"account-fixture: refused: {drive.FAILED} (OSError)\n")


# --- The order of the gate, and the TOTP the api computes -----------------------------------------


def test_the_drive_gate_runs_before_any_io() -> None:
    """In `run` the gate is the first call; in `gate` the structural gate comes first, then the uid
    the caller names, then the run directory's checks."""
    tree = ast.parse(Path(drive.__file__).read_text("utf-8"))
    functions = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}

    def calls(name: str) -> list[str]:
        found = [c for c in ast.walk(functions[name]) if isinstance(c, ast.Call)]
        return [ast.unparse(c.func) for c in sorted(found, key=lambda c: (c.lineno, c.col_offset))]

    assert calls("run")[0] == "gate"
    in_gate = calls("gate")
    assert in_gate.index("armed") < in_gate.index("_owner_uid") < in_gate.index("seeded_run_dir")


@pytest.mark.parametrize("step", [0, 1, 59_999_999, 60_000_000])
def test_the_drivers_codes_are_the_apis(step: int) -> None:
    secret = secret_to_base32(generate_secret())
    same = drive.totp(secret, step) == generate_code(base32_to_secret(secret), step)  # a boolean
    assert same
