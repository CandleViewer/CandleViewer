#!/usr/bin/env python3
"""E42-X03: a real session, with a real TOTP step, for one synthetic role of the ZAP admin profile.

It logs in through the API itself: `POST /auth/login`, then `POST /auth/mfa/verify` with a TOTP
code made from the secret `seed_fixture_user.py --totp-secret-out` wrote, then `GET /me` to
prove the session. It writes the session's bearer and its SR-041 CSRF token (the
`__Host-cv_csrf` cookie, which the API binds to that session) as `ZAP_AUTH_TOKEN` and
`ZAP_CSRF_TOKEN` to an env file of mode 0600 for `docker run --env-file`. Each value is first
announced to GitHub Actions as a mask, and none is printed or logged; a value with a line break,
which would split the file and the mask, is refused. The code is for a TOTP step no earlier
login used: it waits for the next 30-second step, as the API refuses a replay.

The target must be `http://127.0.0.1:<port>` or `http://localhost:<port>` (#1026 Security notes).
Stdlib only. Usage: mint_sessions.py --target URL --username NAME --password-env VAR
--totp-secret-file PATH --out PATH
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import http.client
import json
import os
import struct
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import SplitResult, urlsplit

CSRF_COOKIE = "__Host-cv_csrf"
STEP_S = 30
TIMEOUT_S = 15.0
MAX_BODY_BYTES = 65_536  # the auth answers are small JSON documents; more is never read


class MintFailed(RuntimeError):
    """The session could not be minted; the message names the step, never a credential."""


@dataclass(frozen=True)
class Answer:
    status: int
    body: dict[str, object]
    cookies: dict[str, str]


Http = Callable[[str, str, dict[str, object] | None, dict[str, str]], Answer]


def _shown(parts: SplitResult) -> str:
    """A target as a refusal names it: scheme, host and port, never userinfo, path or query."""
    return f"{parts.scheme}://{parts.netloc.rpartition('@')[2]}"


def check_target(target: str) -> str:
    parts = urlsplit(target)
    loopback = parts.hostname in ("127.0.0.1", "localhost") and parts.path in ("", "/")
    extra = parts.username or parts.password or parts.query or parts.fragment
    if parts.scheme != "http" or not loopback or extra:
        raise MintFailed(
            f"refusing {_shown(parts)!r}: only http://127.0.0.1:<port> or localhost, with no "
            "userinfo, path, query or fragment"
        )
    return target.rstrip("/")


def totp(secret_b32: str, at: float, digits: int = 6) -> str:
    """RFC 6238 over HMAC-SHA1, as `candleviewer.auth.totp.generate_code` computes it."""
    secret = base64.b32decode(secret_b32.upper() + "=" * (-len(secret_b32) % 8))
    digest = hmac.new(secret, struct.pack(">Q", int(at // STEP_S)), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**digits).zfill(digits)


def exchange(
    method: str, url: str, body: dict[str, object] | None, headers: dict[str, str]
) -> Answer:
    """One plain-HTTP exchange with the loopback target `check_target` admitted."""
    parts = urlsplit(url)
    connection = http.client.HTTPConnection(parts.hostname or "", parts.port, timeout=TIMEOUT_S)
    data = None if body is None else json.dumps(body).encode()
    try:
        connection.request(
            method, parts.path, body=data, headers={"Content-Type": "application/json", **headers}
        )
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
    except ValueError:  # not JSON, or not UTF-8 (UnicodeDecodeError): no body to read
        parsed = {}
    return Answer(status, parsed if isinstance(parsed, dict) else {}, cookies)


def _refused(step: str, answer: Answer) -> MintFailed:
    return MintFailed(f"{step}: HTTP {answer.status} {answer.body.get('code', '')}".rstrip())


def mint(
    target: str,
    username: str,
    password: str,
    secret_b32: str,
    *,
    send: Http = exchange,
    clock: Callable[[], float] = time.time,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[str, str]:
    """The bearer and CSRF token of a fresh, verified session for `username`."""
    login = send("POST", f"{target}/auth/login", {"identifier": username, "password": password}, {})
    if login.status != 200 or login.body.get("status") != "mfa_required":
        raise _refused("login", login)
    sleep(STEP_S - clock() % STEP_S + 0.5)  # the next step: no earlier login used its code
    verify = send(
        "POST",
        f"{target}/auth/mfa/verify",
        {
            "mfa_token": login.body.get("mfa_token"),
            "method": "totp",
            "code": totp(secret_b32, clock()),
        },
        {},
    )
    tokens = verify.body.get("tokens")
    bearer = tokens.get("access_token") if isinstance(tokens, dict) else None
    csrf = verify.cookies.get(CSRF_COOKIE)
    if verify.status != 200 or not isinstance(bearer, str) or not csrf:
        raise _refused("mfa verify", verify)
    me = send("GET", f"{target}/me", None, {"Authorization": f"Bearer {bearer}"})
    if me.status != 200:
        raise _refused("session check", me)
    return bearer, csrf


def write_env(path: Path, bearer: str, csrf: str, announce: Callable[[str], None] = print) -> None:
    """Mask both values first, then write them to `path`, mode 0600, for `docker run --env-file`.
    A value with a line break or a NUL is refused before anything is announced or written."""
    for name, value in (("bearer", bearer), ("csrf token", csrf)):
        if not value or any(char in value for char in "\r\n\0"):
            raise MintFailed(f"the {name} is empty or holds a line break: not written")
    for value in (bearer, csrf):
        announce(f"::add-mask::{value}")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)  # an existing file keeps no wider mode
    with os.fdopen(fd, "w", encoding="ascii") as out:
        out.write(f"ZAP_AUTH_TOKEN={bearer}\nZAP_CSRF_TOKEN={csrf}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--target", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password-env", required=True, help="the variable holding the password")
    parser.add_argument("--totp-secret-file", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        target = check_target(args.target)
        password = os.environ.get(args.password_env, "")
        if not password:
            raise MintFailed("the variable --password-env names is empty")  # no name is logged
        secret = args.totp_secret_file.read_text(encoding="ascii").strip()
        bearer, csrf = mint(target, args.username, password, secret)
        write_env(args.out, bearer, csrf)
    except (MintFailed, OSError) as exc:
        print(f"::error title=mint_sessions::{args.username}: {exc}")
        return 1
    print(f"mint_sessions: {args.username}: session minted and verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
