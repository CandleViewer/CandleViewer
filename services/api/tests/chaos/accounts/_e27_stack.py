"""E27-Q03 (#892) chaos helpers: drive the account fixture stack from pytest (BQ-06 option a).

BQ-nn markers here: RULED (orchestrator, 2026-11-01, #892 ruling of record 6555033109).

Everything goes through the stack's own interfaces: the switch/clock CLI run in the api container
(`python -m cvdev.account_fixture.cli`, #2893), the request log read back from the container, the
public REST routes and `/metrics`. No exchange host is ever named (C-13.5): the only target is the
loopback or compose-service URL that `tests/load/accounts/guard.py` allows (BQ-11).

Credentials: the seeded roster's files in `CV_E27_RUN_DIR` (`pw-<user>`, `totp-<user>`, written by
`cvdev.account_fixture.seed`), read here and never printed, logged or put in an exception.
The compose command is a constant, not built from the environment, so no input reaches an argv
except the two values `_validated` accepts.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
import os
import re
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, Final

REPO: Final = Path(__file__).resolve().parents[5]
COMPOSE: Final = (
    "docker", "compose",
    "-f", "infra/compose/docker-compose.yml",
    "-f", "infra/compose/docker-compose.dev.yml",
    "-f", "infra/compose/docker-compose.account-fixture.yml",
    "--profile", "core",
)  # fmt: skip
FIXTURE_DIR: Final = (
    "/var/lib/candleviewer/account-fixture"  # infra/compose/docker-compose.account-fixture.yml
)
CSRF_COOKIE: Final = "__Host-cv_csrf"
_KEY: Final = re.compile(r"fixture-[a-z0-9_]{1,64}-[0-9]{4}")
_SCENARIO: Final = re.compile(r"[a-z0-9_]{1,64}")


def load_module(name: str, relative: str) -> ModuleType:
    """A repo file outside this package (tests/load/accounts/*), by path; no import-path edits."""
    path = REPO / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))  # the module's own sibling imports (soak_sampler -> guard)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


guard = load_module("e27_guard", "tests/load/accounts/guard.py")


def base_url() -> str:
    return str(guard.check_target(os.environ.get("CV_E27_BASE_URL", "http://127.0.0.1:8000")))


def _validated(key_id: str, scenario: str) -> None:
    if not _KEY.fullmatch(key_id) or not _SCENARIO.fullmatch(scenario):
        raise ValueError("a pack key id and a scenario name only")


def _exec(*args: str, timeout_s: float = 60.0) -> str:
    done = subprocess.run(  # noqa: S603 - constant argv head, validated tail
        [*COMPOSE, "exec", "-T", "api", *args],
        cwd=REPO, capture_output=True, text=True, timeout=timeout_s, check=False,
    )  # fmt: skip
    if done.returncode != 0:
        raise RuntimeError(f"stack command failed: exit {done.returncode}")  # never the output
    return done.stdout


def switch(key_id: str, scenario: str) -> None:
    """The stored key answers as `scenario` from now; its scenario time restarts (pack README)."""
    _validated(key_id, scenario)
    _exec("python", "-m", "cvdev.account_fixture.cli", "switch", key_id, "--to", scenario)


def advance_clock(seconds: int) -> None:
    _exec(
        "python",
        "-m",
        "cvdev.account_fixture.cli",
        "clock",
        "advance",
        str(int(seconds)),
    )


def request_log() -> list[dict[str, Any]]:
    """The stub's request log (cvdev/account_fixture/requestlog.py); never a signature or secret."""
    return [
        json.loads(x)
        for x in _exec("cat", f"{FIXTURE_DIR}/requests.jsonl").splitlines()
        if x.strip()
    ]


# -- REST and metrics ---------------------------------------------------------------------------
def _totp(seed_b32: str, now: float | None = None) -> str:
    key = base64.b32decode(seed_b32.strip().upper() + "=" * (-len(seed_b32.strip()) % 8))
    mac = hmac.new(key, struct.pack(">Q", int((now or time.time()) // 30)), hashlib.sha1).digest()
    off = mac[-1] & 15
    return f"{(struct.unpack('>I', mac[off : off + 4])[0] & 0x7FFFFFFF) % 10**6:06d}"


class Api:
    """One signed-in Owner session on the stack (stdlib urllib, CSRF carried by hand)."""

    def __init__(self) -> None:
        self.base = base_url()
        run_dir, user = Path(os.environ["CV_E27_RUN_DIR"]), os.environ["CV_E27_USER"]
        password = (run_dir / f"pw-{user}").read_text().strip()
        seed = (run_dir / f"totp-{user}").read_text().strip()
        login = self._call("POST", "/auth/login", {"identifier": user, "password": password})[1]
        deadline = time.monotonic() + 35.0
        while True:  # the API refuses a spent TOTP step (SR-021): retry on the next step
            status, body, headers = self._call(
                "POST", "/auth/mfa/verify",
                {"mfa_token": login["mfa_token"], "method": "totp", "code": _totp(seed)},
            )  # fmt: skip
            if status == 200 or time.monotonic() > deadline:
                break
            wait_until(lambda: False, 1.0, 1.0)
        assert status == 200, f"mfa/verify {status}"
        self.token = body["tokens"]["access_token"]
        m = re.search(rf"{re.escape(CSRF_COOKIE)}=([^;,\s]+)", headers.get("Set-Cookie", ""))
        self.csrf = m.group(1) if m else headers.get("X-Csrf-Token", "")

    def _call(
        self, method: str, path: str, body: Any = None, auth: bool = False
    ) -> tuple[int, Any, Any]:
        headers = {"Content-Type": "application/json"}
        if auth:
            headers |= {"Authorization": f"Bearer {self.token}", "X-CSRF-Token": self.csrf,
                        "Cookie": f"{CSRF_COOKIE}={self.csrf}"}  # fmt: skip
        req = urllib.request.Request(  # noqa: S310 - base_url() is guarded
            self.base + path, method=method, headers=headers,
            data=None if body is None else json.dumps(body).encode(),
        )  # fmt: skip
        try:
            with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310
                raw, status, hdrs = r.read(), r.status, r.headers
        except urllib.error.HTTPError as e:
            raw, status, hdrs = e.read(), e.code, e.headers
        return status, (json.loads(raw) if raw else None), hdrs

    def get(self, path: str) -> tuple[int, Any]:
        s, b, _ = self._call("GET", path, auth=True)
        return s, b

    def post(self, path: str, body: Any = None) -> tuple[int, Any]:
        s, b, _ = self._call("POST", path, body, auth=True)
        return s, b

    def accounts_and_keys(self) -> list[tuple[str, dict[str, Any]]]:
        """(account id, key row) for every signable key (22 listExchangeAccounts, listApiKeys)."""
        out = []
        for acct in self.get("/exchange-accounts?include_balance=false")[1]["items"]:
            for key in self.get(f"/exchange-accounts/{acct['id']}/keys")[1]["items"]:
                if key["status"] in ("active", "rotating"):
                    out.append((acct["id"], key))
        return out

    def test_key(self, account_id: str, key_id: str) -> tuple[int, Any]:
        """22 testApiKey with the REST half only (the scheduled self-check opens no WS)."""
        return self.post(
            f"/exchange-accounts/{account_id}/keys/{key_id}/test", {"include_ws": False}
        )


def metric(name: str, **labels: str) -> float:
    """The sum of `name`'s samples whose labels include `labels`; 0.0 when none (a series that has
    not been seen). `/metrics` is a public operational route (deny_by_default.py)."""
    with urllib.request.urlopen(base_url() + "/metrics", timeout=10) as r:  # noqa: S310
        body = r.read().decode()
    total = 0.0
    for line in body.splitlines():
        if not line.startswith(name):
            continue
        head, _, value = line.rpartition(" ")
        if head.split("{")[0] != name:
            continue
        if all(f'{k}="{v}"' in head for k, v in labels.items()):
            total += float(value)
    return total


def health_count(state: str) -> float:
    return metric("cv_account_health_state", state=state)


def wait_until(cond: Callable[[], bool], timeout_s: float, step_s: float = 1.0) -> bool:
    """Poll `cond` until true or `timeout_s` passes. Bounded, and the only wait: the stack runs on
    wall-clock time, so a fake clock cannot stand in (C-13.7 binds unit tests; qa/plans/e27/chaos.md
    section 6 item 5).
    """
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step_s)  # the one real wait in the module
    return cond()
