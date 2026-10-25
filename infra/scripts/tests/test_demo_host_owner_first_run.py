"""Tests for infra/scripts/demo_host_owner_first_run.sh (#3180): the Owner's first run.

The script runs under bash with a stub `curl` first on PATH (`stub_curl.py`) and a `python3` that
records its arguments, from an empty working directory, HOME and TMPDIR, with no terminal; stdin
holds the answers to its prompts. No network: the stub answers in the shapes the served code gives
(`api/invites.py`, `api/auth.py`, `api/step_up.py`, `api/exchange_keys.py`; `createExchangeAccount`
as 22 declares it, #895). Every request is held to docs/plan/22-api-openapi.yaml: the operation's
method and path, and its body against the operation's request schema.
"""

from __future__ import annotations

import functools
import json
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "infra" / "scripts" / "demo_host_owner_first_run.sh"
SPEC = REPO_ROOT / "docs" / "plan" / "22-api-openapi.yaml"
STUB = Path(__file__).with_name("stub_curl.py")
BASH = shutil.which("bash") or "/bin/bash"

# What the Owner types. All are secrets but the identifier, the UID and the labels; the password
# holds a quote and a backslash, which the request config and the JSON body must both escape.
TOKEN = "sentinel-invite-sentinel-invite"
PASSWORD = 'pwSentinel "quoted" back\\slash 42'
CODES = ("271828", "314159", "161803")
IDENTIFIER = "owner"
EXCHANGE_UID = "40321987"
API_KEY = "sentinel-apikey-sentinel"
API_SECRET = "sentinel-secret-sentinel-secret"
SECRETS = (TOKEN, PASSWORD, *CODES, API_KEY, API_SECRET)
# What the served code issues.
ACCESS, CSRF = "accessServerIssued_AbCdEf", "csrfNonceServer.csrfMacServer"
ROTATED = {"access": "accessRotated_GhIjKl", "csrf": "csrfNonceRotated.csrfMacRotated"}
MFA_TOKEN = "mfaServerIssued_MnOpQr"
METHOD_ID = "11111111-2222-4333-8444-555555555555"
ACCOUNT_ID = "a1000000-0000-4000-8000-000000000001"
CHALLENGE_ID = "c1000000-0000-4000-8000-000000000002"
OTPAUTH = "otpauth://totp/CandleViewer:owner?secret=STUBSTUBSTUBSTUB&issuer=CandleViewer"
RECOVERY = tuple(f"rc{i:02d}-wxyz-{i:02d}ab" for i in range(10))
EGRESS = "egress-sentinel"  # where the served code puts the egress IP: never printed

#: (method, 22 path, operationId, needs the session): the calls of a full run, in order.
ROUTES = (
    ("GET", "/invites/{inviteToken}", "getInvite", False),
    ("POST", "/invites/{inviteToken}", "redeemInvite", False),
    ("POST", "/invites/{inviteToken}/confirm", "confirmInvite", False),
    ("POST", "/auth/login", "authLogin", False),
    ("POST", "/auth/mfa/verify", "authMfaVerify", False),
    ("POST", "/exchange-accounts", "createExchangeAccount", True),
    ("POST", "/auth/step-up", "authStepUp", True),
    ("POST", "/exchange-accounts/{accountId}/keys", "createApiKey", True),
)
ORDER = [f"{method} {path}" for method, path, _, _ in ROUTES]
CURL_ARGV = ["-q", "--silent", "--noproxy", "*", "--proto", "=http", "--max-time", "60",
             "--dump-header", "-", "--write-out", "\\n%{http_code}", "--config", "-"]  # fmt: skip
#: The prompts of a full run, in order (blank: the default label, label and read-only answer).
ANSWERS = [TOKEN, PASSWORD, PASSWORD, CODES[0], IDENTIFIER, CODES[1], EXCHANGE_UID, "", "", "",
           API_KEY, API_SECRET, CODES[2]]  # fmt: skip
VERDICT = {
    "passed": True, "uid": EXCHANGE_UID, "uta": True, "read_only": False,
    "withdraw_enabled": False, "permissions": {"ContractTrade": ["Order", "Position"]},
    "ip_whitelist": [EGRESS], "egress_ip": EGRESS, "warnings": [],
    "ip_whitelist_matches_egress": True, "probe_ret_code": 0, "clock_offset_ms": 12,
}  # fmt: skip
VERDICT_LINES = [
    "passed: true", f"uid: {EXCHANGE_UID}", "uta: true", "read_only: false",
    "withdraw_enabled: false", "ip_whitelist_matches_egress: true", "warnings: -",
    "probe_ret_code: 0", "clock_offset_ms: 12",
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
               "label": "Bybit demo main", "exchange_uid": EXCHANGE_UID}  # fmt: skip
    elevated = {"elevated_until": "2026-10-26T04:05:00+00:00", "action_class": "keys",
                "single_use": False, "step_up_expires_at": "2026-10-26T04:05:00+00:00"}  # fmt: skip
    key = {"id": "k1000000-0000-4000-8000-000000000004", "status": "active",
           "key_id_masked": "****ab42"}  # fmt: skip
    return {
        ORDER[0]: [answer(200, {"display_name": "Owner", "role": "viewer",
                                "expires_at": "2026-10-28T04:00:00+00:00"}, path=invite)],
        ORDER[1]: [answer(200, {"method_id": METHOD_ID, "otpauth_uri": OTPAUTH,
                                "secret_base32": "STUBSTUBSTUBSTUB"},
                          path=invite, expect={"password": PASSWORD})],
        ORDER[2]: [answer(200, {"status": "active", "role": "owner",
                                "recovery_codes": list(RECOVERY)},
                          path=invite, expect={"method_id": METHOD_ID, "code": CODES[0]})],
        ORDER[3]: [answer(200, {"status": "mfa_required", "mfa_token": MFA_TOKEN,
                                "methods": ["totp"], "expires_in": 300},
                          expect={"identifier": IDENTIFIER, "password": PASSWORD})],
        ORDER[4]: [answer(200, signed_in, cookies={"cv_refresh": "refreshServerIssued",
                                                   "__Host-cv_csrf": CSRF},
                          session={"access": ACCESS, "csrf": CSRF},
                          expect={"mfa_token": MFA_TOKEN, "method": "totp", "code": CODES[1]})],
        ORDER[5]: [answer(201, account, expect={k: account[k] for k in (
            "exchange", "environment", "kind", "label", "exchange_uid")})],
        ORDER[6]: [answer(200, elevated, expect={"password": PASSWORD, "code": CODES[2],
                                                 "action_class": "keys"})],
        ORDER[7]: [answer(201, {"key": key, "verification": VERDICT},
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
    logs: dict[str, str]  # every file the stub and the python3 shim wrote, by name
    left: list[Path]  # what the run left in its working directory, HOME and TMPDIR

    @property
    def routes(self) -> list[str]:
        return [r["route"] for r in self.records]


def run(
    tmp_path: Path, calls: dict[str, list[dict[str, Any]]], answers: list[str], *args: str,
    xtrace: bool = False, schemas: bool = False,
) -> Run:  # fmt: skip
    """One run of the script on `calls`; `schemas` also holds each body to 22 (a slower run)."""
    stub, bin_dir, cwd, home, tmp = (tmp_path / d for d in ("stub", "bin", "cwd", "home", "tmp"))
    for directory in (stub, bin_dir, cwd, home, tmp):
        directory.mkdir()
    routes = [
        {"method": method, "path": path, "session": session,
         "schema": request_schema(op) if schemas else None,
         "calls": calls.get(f"{method} {path}", [])}
        for method, path, op, session in ROUTES
    ]  # fmt: skip
    (stub / "scenario.json").write_text(json.dumps({"routes": routes}), encoding="utf-8")
    curl = bin_dir / "curl"
    curl.write_text(f"#!{sys.executable}\n" + STUB.read_text(encoding="utf-8"), encoding="utf-8")
    shim = bin_dir / "python3"  # the script's python3, recording its arguments
    shim.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$CV_STUB_DIR/python3.argv"\n'
                    f'exec "{sys.executable}" "$@"\n', encoding="utf-8")  # fmt: skip
    for tool in (curl, shim):
        tool.chmod(stat.S_IRWXU)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(tmp),
           "CV_STUB_DIR": str(stub)}  # fmt: skip
    proc = subprocess.run(
        [BASH, *(["-x"] if xtrace else []), str(SCRIPT), *args],
        input="".join(f"{line}\n" for line in answers),
        capture_output=True, text=True, cwd=cwd, env=env, timeout=120, check=False,
        start_new_session=True,  # no controlling terminal: /dev/tty cannot be opened
    )  # fmt: skip

    def lines(name: str) -> list[Any]:
        path = stub / name
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        return [json.loads(line) for line in text.splitlines()]

    logs = {p.name: p.read_text(encoding="utf-8") for p in stub.iterdir() if p.is_file()}
    left = [p for d in (cwd, home, tmp) for p in d.rglob("*")]
    return Run(proc, lines("requests.jsonl"), lines("argv.jsonl"), logs, left)


@pytest.fixture(scope="module")
def full(tmp_path_factory: pytest.TempPathFactory) -> Run:
    return run(tmp_path_factory.mktemp("full"), full_run(), ANSWERS, schemas=True)


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
    assert [r["route"] for r in full.records if not r["body_ok"]] == [ORDER[0]]
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
    assert keys[ORDER[5]] is True and keys[ORDER[7]] is True
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
    assert {"argv.jsonl", "python3.argv", "requests.jsonl"} <= set(full.logs)


def test_curl_gets_only_fixed_options_on_its_command_line(full: Run) -> None:
    assert full.argv == [CURL_ARGV] * len(ORDER)


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


def _replaced(index: int, calls: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    scenario = full_run()
    scenario[ORDER[index]] = calls
    return scenario


REFUSED_INVITE = problem(404, "not_found", "This invitation link is not valid.")
BAD_CODE = problem(422, "invalid_code", "invalid code")
BAD_FACTOR = problem(401, "mfa_invalid", "invalid or expired code")
BAD_STEP_UP = problem(401, "mfa_invalid", "Invalid password or code.", failures_remaining=2)
KEY_REFUSED = problem(
    422, "validation_failed", "The key was not imported.",
    errors=[{"field": "api_key", "rule": "key_ip_whitelist_mismatch", "message": "m"}],
    verification={**VERDICT, "passed": False, "ip_whitelist_matches_egress": False},
)  # fmt: skip


@pytest.mark.parametrize(
    ("index", "calls", "answers", "message", "made"),
    [
        (0, [REFUSED_INVITE], ANSWERS[:1], "the invite token is not valid", 1),
        (0, [{"exit": 7}], ANSWERS[:1], "did not answer", 1),
        (1, [problem(422, "password_policy", "too_short")], ANSWERS[:3], "too_short", 2),
        (2, [BAD_CODE] * 3, ANSWERS[:3] + [CODES[0]] * 3, "refused three times", 5),
        (2, [answer(200, {"status": "active", "role": "viewer", "recovery_codes": ["rc"]})],
         ANSWERS[:4], "not owner", 3),
        (3, [problem(401, "invalid_credentials", "invalid credentials")], ANSWERS[:5],
         "sign-in was refused", 4),
        (4, [BAD_FACTOR] * 3, ANSWERS[:5] + [CODES[1]] * 3, "refused three times", 7),
        (5, [problem(404, "not_found", "Not Found")], ANSWERS[:12], "#895", 6),
        (6, [BAD_STEP_UP] * 2, ANSWERS + [CODES[2]], "refused twice", 8),
        (7, [KEY_REFUSED], ANSWERS, "key_ip_whitelist_mismatch", 8),
        (7, [problem(503, "exchange_unavailable", "no verdict")], ANSWERS, "no verdict", 8),
    ],
    ids=["invite-unknown", "api-down", "password-policy", "enrolment-code", "not-owner",
         "sign-in", "second-factor", "accounts-not-served", "step-up", "key-refused",
         "exchange-unavailable"],
)  # fmt: skip
def test_a_refused_step_stops_the_run(
    tmp_path: Path, index: int, calls: list[dict[str, Any]], answers: list[str], message: str,
    made: int,
) -> None:  # fmt: skip
    refused = run(tmp_path, _replaced(index, calls), answers)
    assert refused.proc.returncode == 1
    assert message in refused.proc.stderr
    assert len(refused.records) == made and set(refused.routes) <= set(ORDER[: index + 1])
    assert [secret for secret in SECRETS if secret in refused.proc.stderr] == []


def test_a_refused_key_prints_its_verdict_and_never_the_egress_address(tmp_path: Path) -> None:
    refused = run(tmp_path, _replaced(7, [KEY_REFUSED]), ANSWERS)
    assert "passed: false" in refused.proc.stdout.splitlines()
    assert "ip_whitelist_matches_egress: false" in refused.proc.stdout.splitlines()
    assert EGRESS not in refused.proc.stdout + refused.proc.stderr


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        (["not a token!"], "not an invite token"),
        ([TOKEN, PASSWORD, PASSWORD + "x"], "the two passwords differ"),
        ([TOKEN, "short", "short"], "12 to 512 characters"),
        (ANSWERS[:3] + ["12345"], "6 digits"),
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


# --- the step-up: 22's challenge and session rotation --------------------------------------------


def test_a_step_up_challenge_on_the_import_is_answered_and_the_import_sent_again(
    tmp_path: Path,
) -> None:
    scenario = full_run()
    challenge = problem(403, "step_up_required", "Re-enter your password and code.",
                        action_class="keys", challenge_id=CHALLENGE_ID)  # fmt: skip
    scenario[ORDER[7]] = [challenge, scenario[ORDER[7]][0]]
    again = dict(scenario[ORDER[6]][0])
    again["expect"] = {"password": PASSWORD, "code": "112358", "challenge_id": CHALLENGE_ID}
    scenario[ORDER[6]] = [scenario[ORDER[6]][0], again]
    resent = run(tmp_path, scenario, [*ANSWERS, "112358"], schemas=True)
    assert resent.proc.returncode == 0, resent.proc.stderr
    assert resent.routes == [*ORDER, ORDER[6], ORDER[7]]
    assert all(all(r["body_ok"].values()) for r in resent.records)
    imports = [r["idempotency_key"] for r in resent.records if r["route"] == ORDER[7]]
    assert len(imports) == 2 and imports[0] == imports[1]  # the held request, sent again as is


def test_a_step_up_that_rotates_the_session_is_followed(tmp_path: Path) -> None:
    """22 (SR-013): the step-up's 200 carries the new access token and sets the new CSRF cookie;
    the served code does not rotate yet, and the script takes whichever it is given."""
    scenario = full_run()
    rotated = scenario[ORDER[6]][0]
    rotated["body"] = {
        **rotated["body"],
        "tokens": {"access_token": ROTATED["access"], "token_type": "Bearer", "expires_in": 600},
    }
    rotated |= {"cookies": {"__Host-cv_csrf": ROTATED["csrf"]}, "session": ROTATED}
    followed = run(tmp_path, scenario, ANSWERS)
    assert followed.proc.returncode == 0, followed.proc.stderr
    assert followed.records[-1]["session_ok"] is True  # the import used the rotated session


# --- a second run: the invite redeemed, the account registered -----------------------------------


def test_skip_invite_and_account_id_start_at_the_sign_in_and_reuse_the_account(
    tmp_path: Path,
) -> None:
    answers = [IDENTIFIER, PASSWORD, CODES[1], EXCHANGE_UID, "", "", API_KEY, API_SECRET, CODES[2]]
    again = run(tmp_path, full_run(), answers, "--skip-invite", "--account-id", ACCOUNT_ID)
    assert again.proc.returncode == 0, again.proc.stderr
    assert again.routes == [ORDER[3], ORDER[4], ORDER[6], ORDER[7]]
    assert all(r["path_ok"] for r in again.records)
    assert again.proc.stdout.splitlines() == VERDICT_LINES


@pytest.mark.parametrize("args", [["--account-id", "not-a-uuid"], ["--bogus"], ["--account-id"]])
def test_bad_arguments_stop_before_any_prompt(tmp_path: Path, args: list[str]) -> None:
    stopped = run(tmp_path, full_run(), ANSWERS, *args)
    assert stopped.proc.returncode == 2 and stopped.records == []
