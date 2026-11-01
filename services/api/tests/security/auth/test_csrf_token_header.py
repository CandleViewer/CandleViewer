"""The `X-CSRF-Token` response header through `create_app()` (ADR-0038 3b and F8, #3519 S4.2).

Each operation that issues the SR-041 token gives it in the header only to a request whose one
`Origin` is listed while `desktop.backend_connection` is on; every response that issues the token
is `Cache-Control: no-store` whatever the flag. An expiry (logout) and step-up, which issues no
token yet (F5, #2101), never carry the header. The operations are the contract's own set
(`components.headers.CsrfTokenIssued`), so this is the C-6.2 provider check of that header.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from structlog.testing import capture_logs

from candleviewer.auth.csrf import CSRF_COOKIE, CSRF_HEADER
from tests.contract.test_csrf_token_header_contract import _ISSUING
from tests.csrf_helpers import csrf_headers

from ._stack import PW, Stack, open_stack

_DESKTOP = "app://candleviewer"
Sent = list[tuple[str, str]]
Op = tuple[str, str, str]


def _desktop(monkeypatch: pytest.MonkeyPatch, on: bool) -> AbstractContextManager[Stack]:
    return open_stack(monkeypatch, listed=(_DESKTOP,), backend_connection=on)


def _user(stack: Stack, *, enrolled: bool = True) -> tuple[str, str, bytes]:
    """A new user with `PW` and a TOTP seed: (name, id, seed). Not *enrolled*, the user store
    lists no method, so the password signs in to an enrolment-only session (#2295)."""
    name = f"user{len(stack.users.users)}"
    uid, seed = stack.add_user(name)
    if not enrolled:
        stack.users.add(stack.users.users[str(uid)].model_copy(update={"mfa_methods": ()}))
    return name, str(uid), seed


def _password(stack: Stack, name: str, sent: Sent | None = None) -> Any:
    stack.client.cookies.clear()
    return stack.client.post("/auth/login", headers=sent, json={"identifier": name, "password": PW})


def _bearer(stack: Stack, signed_in: Any) -> dict[str, str]:
    """The bearer of *signed_in*'s session and an SR-041 pair bound to it (the jar is cleared)."""
    access = signed_in.json()["tokens"]["access_token"]
    record = stack.call(stack.auth.sessions.peek_access_token, access)
    stack.client.cookies.clear()
    return {"Authorization": f"Bearer {access}", **csrf_headers(stack.state.csrf_codec, record.id)}


def _login(stack: Stack, sent: Sent) -> Any:
    """`POST /auth/login`'s enrolment-only answer, the one that issues the token."""
    return _password(stack, _user(stack, enrolled=False)[0], sent)


def _verify(stack: Stack, sent: Sent) -> Any:
    name, _, seed = _user(stack)
    challenge = _password(stack, name).json()["mfa_token"]
    body = {"mfa_token": challenge, "method": "totp", "code": stack.code(seed)}
    return stack.client.post("/auth/mfa/verify", headers=sent, json=body)


def _recovery(stack: Stack, sent: Sent) -> Any:
    name, uid, _ = _user(stack)
    code = stack.call(stack.auth.mfa.regenerate_recovery_codes, uid).recovery_codes[0]
    body = {"mfa_token": _password(stack, name).json()["mfa_token"], "recovery_code": code}
    return stack.client.post("/auth/mfa/recovery", headers=sent, json=body)


def _confirm(stack: Stack, sent: Sent) -> Any:
    auth = _bearer(stack, _password(stack, _user(stack, enrolled=False)[0]))
    enrol = stack.client.post("/auth/mfa/enroll", headers=auth, json={"method": "totp"}).json()
    secret = parse_qs(urlparse(enrol["otpauth_uri"]).query)["secret"][0]
    seed = base64.b32decode(secret + "=" * (-len(secret) % 8))
    body = {"method_id": enrol["method_id"], "code": stack.code(seed)}
    return stack.client.post("/auth/mfa/enroll/confirm", headers=[*sent, *auth.items()], json=body)


def _refresh(stack: Stack, sent: Sent) -> Any:
    """The desktop's refresh: `cv_refresh` and the SR-041 pair, as cookies and header."""
    name, _, seed = _user(stack)
    signed_in = stack.sign_in(name, seed)
    token, refresh = signed_in.cookies[CSRF_COOKIE], signed_in.cookies["cv_refresh"]
    stack.client.cookies.clear()
    pair = [(CSRF_HEADER, token), ("Cookie", f"cv_refresh={refresh}; {CSRF_COOKIE}={token}")]
    return stack.client.post("/auth/refresh", headers=[*sent, *pair])


def _session(stack: Stack, sent: Sent) -> Any:
    """`GET /auth/session` without the cookie, so it re-issues one."""
    name, _, seed = _user(stack)
    access = stack.sign_in(name, seed).json()["tokens"]["access_token"]
    stack.client.cookies.clear()
    return stack.client.get("/auth/session", headers=[*sent, ("Authorization", f"Bearer {access}")])


def _change_password(stack: Stack, sent: Sent) -> Any:
    """`PUT /auth/password` (#5292): the change rotates the session, so it issues a new token."""
    name, _, seed = _user(stack)
    auth = _bearer(stack, stack.sign_in(name, seed))
    body = {"current_password": PW, "new_password": "brand-new-Secret-42!"}  # test-only literal
    return stack.client.put("/auth/password", headers=[*sent, *auth.items()], json=body)


_DRIVE: dict[Op, Callable[[Stack, Sent], Any]] = {
    ("post", "/auth/login", "200"): _login,
    ("post", "/auth/mfa/verify", "200"): _verify,
    ("post", "/auth/mfa/recovery", "200"): _recovery,
    ("post", "/auth/mfa/enroll/confirm", "200"): _confirm,
    ("post", "/auth/refresh", "200"): _refresh,
    ("put", "/auth/password", "200"): _change_password,
    ("get", "/auth/session", "200"): _session,
}


# The C-6.2 provider check: one case per operation the contract declares the header on.
@pytest.mark.parametrize("op", sorted(_ISSUING), ids=lambda op: f"{op[0]}{op[1]}")
def test_issuing_operation_listed_origin_flag_on_gets_its_new_token_in_the_header(
    monkeypatch: pytest.MonkeyPatch, op: Op
) -> None:
    with _desktop(monkeypatch, on=True) as stack, capture_logs() as logs:
        answer = _DRIVE[op](stack, [("Origin", _DESKTOP)])

    assert answer.status_code == 200, answer.text
    token = answer.headers[CSRF_HEADER]
    assert token == answer.cookies[CSRF_COOKIE]
    assert answer.headers["cache-control"] == "no-store"
    assert token not in answer.text and token not in repr(logs)
    assert CSRF_HEADER in answer.headers["access-control-expose-headers"].split(", ")


#: Each way a request misses "its one `Origin` listed, the flag on": its `Origin`s and the flag.
_MISSED: dict[str, tuple[list[str], bool]] = {
    "flag_off": ([_DESKTOP], False),
    "unlisted": (["https://evil.example"], True),
    "absent": ([], True),
    "repeated": ([_DESKTOP, _DESKTOP], True),
}
#: Which operations still issue the cookie: all the contract's (so the drivers are exactly those),
#: less the ones SR-042 refuses first: an unlisted `Origin`'s writes, a cookie refresh without one.
_ISSUED: dict[str, set[Op]] = {
    "flag_off": _ISSUING,
    "unlisted": {("get", "/auth/session", "200")},
    "absent": _ISSUING - {("post", "/auth/refresh", "200")},
    "repeated": _ISSUING,
}


@pytest.mark.parametrize("case", list(_MISSED))
def test_issuing_operations_without_a_listed_origin_and_the_flag_get_no_header_but_no_store(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    origins, on = _MISSED[case]
    sent = [("Origin", origin) for origin in origins]
    with _desktop(monkeypatch, on=on) as stack:
        answers = {op: drive(stack, sent) for op, drive in _DRIVE.items()}

    issued = {op for op, answer in answers.items() if CSRF_COOKIE in answer.cookies}
    assert issued == _ISSUED[case]
    assert [op for op, answer in answers.items() if CSRF_HEADER in answer.headers] == []
    assert {answers[op].headers.get("cache-control") for op in issued} == {"no-store"}  # F8


def _session_with_its_cookie(stack: Stack, origins: list[str]) -> tuple[Any, str]:
    """`GET /auth/session` of a fresh session with its own valid SR-041 cookie, sent from
    *origins*: (the answer, that cookie's value)."""
    name, _, seed = _user(stack)
    signed_in = stack.sign_in(name, seed)
    token = signed_in.cookies[CSRF_COOKIE]
    sent = [
        ("Authorization", f"Bearer {signed_in.json()['tokens']['access_token']}"),
        ("Cookie", f"{CSRF_COOKIE}={token}"),
        *(("Origin", origin) for origin in origins),
    ]
    stack.client.cookies.clear()
    return stack.client.get("/auth/session", headers=sent), token


def test_session_with_a_valid_cookie_gets_that_value_without_set_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _desktop(monkeypatch, on=True) as stack:
        answer, token = _session_with_its_cookie(stack, [_DESKTOP])

    assert answer.status_code == 200
    assert (answer.headers[CSRF_HEADER], answer.headers["cache-control"]) == (token, "no-store")
    assert "set-cookie" not in answer.headers and token not in answer.text


@pytest.mark.parametrize("case", list(_MISSED))
def test_session_with_a_valid_cookie_but_no_listed_origin_and_flag_gets_todays_answer(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    origins, on = _MISSED[case]
    with _desktop(monkeypatch, on=on) as stack:
        answer, _ = _session_with_its_cookie(stack, origins)

    assert answer.status_code == 200
    assert not {CSRF_HEADER.lower(), "set-cookie", "cache-control"} & set(answer.headers)


def test_step_up_and_logout_never_carry_the_header_that_the_sign_in_before_them_does(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listed = {"Origin": _DESKTOP}
    with _desktop(monkeypatch, on=True) as stack:
        headers, seed = stack.principal("stepper", "owner")
        signed_in = stack.sign_in("stepper", seed, carried=listed)
        stack.client.cookies.clear()  # what follows is the principal's session, not this one
        step = {"code": stack.code(seed), "password": PW, "action_class": "users"}
        # F5: step-up issues no token yet (#2101)
        stepped = stack.client.post("/auth/step-up", headers={**listed, **headers}, json=step)
        out = stack.client.post("/auth/logout", headers={**listed, **headers})

    assert CSRF_HEADER in signed_in.headers
    assert (stepped.status_code, out.status_code) == (200, 204), stepped.text
    assert CSRF_HEADER not in stepped.headers and CSRF_HEADER not in out.headers
    assert [c for c in out.headers.get_list("set-cookie") if c.startswith(f"{CSRF_COOKIE}=")]
