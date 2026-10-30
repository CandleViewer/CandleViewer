"""`POST /auth/login` (#4961, SR-014): every failed sign-in gets the contract's one answer.

`22` (`authLogin`) names each account state at sign-in and answers every failed sign-in with the
one `401` `unauthenticated` problem, the same body and the same headers; the audit record keeps
the cause. The text is pinned first. Then the composed app (`create_app()` over the in-memory auth
stack of `tests/security/auth/_stack.py`) is asked once per account state, and each answer is
compared with a wrong password's: the status, the body's bytes and every header but the request's
own `X-Correlation-Id`. The states are the ones the login service and its router tell apart: an
unknown identifier, a disabled or a locked account with the right password or a wrong one, a user
without `mfa_required`, and a user who must enrol and is disabled during the sign-in itself. Each
keeps its own audit row. No network; the minimum time of a refused step is kept, and only its
wait is skipped (`no_wait`), as the unit suites do.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.audit.models import AuditOutcome
from candleviewer.auth.models import UserStatus
from tests.security.auth._stack import PW, T0, Stack, open_stack
from tests.unit.auth.auth_fakes import no_wait
from tests.unit.auth.session_fakes import FakeSessionRepository

_BASE = "urn:cv:openapi"
_WRONG = "wrong-guess"  # never `PW`
_FAILED, _LOCKED = "auth.login_failed", "auth.account_locked"
Answer = tuple[int, bytes, dict[str, str]]


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return load_openapi_spec()


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    with open_stack(monkeypatch) as opened:
        opened.auth.login._failure_hold._sleep = no_wait  # the hold runs; its wait is skipped
        yield opened


def _flat(text: str) -> str:
    """Collapse YAML line wrapping so prose pins survive a re-wrap."""
    return " ".join(text.split())


def _login_operation(spec: dict[str, Any]) -> dict[str, Any]:
    operation: dict[str, Any] = spec["paths"]["/auth/login"]["post"]
    return operation


def _conforms(spec: dict[str, Any], value: Any, pointer: str) -> None:
    resource = Resource.from_contents(spec, default_specification=DRAFT202012)
    Draft202012Validator(
        {"$ref": f"{_BASE}#{pointer}"},
        registry=Registry().with_resource(_BASE, resource),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).validate(value)


@pytest.mark.parametrize(
    "rule",
    [
        "Every failed sign-in gets one answer, whatever the account's state (SR-014, #4961).",
        "An unknown identifier, a wrong password, a disabled or a locked account and a user "
        "without `mfa_required`, whether the password sent is right or wrong, are all answered "
        "`401` `unauthenticated`, with the same body and the same headers.",
        "No state has a status, a header or a problem member of its own, and a refused password "
        "step returns no sooner than the same minimum time.",
        "The audit record, never the answer, keeps the cause.",
        "That refusal is decided before the identifier is read, so it says nothing about any "
        "account.",
    ],
)
def test_login_contract_states_one_answer_for_every_account_state(
    spec: dict[str, Any], rule: str
) -> None:
    assert rule in _flat(_login_operation(spec)["description"])


def test_login_contract_declares_the_one_401_and_no_status_of_any_account_state(
    spec: dict[str, Any],
) -> None:
    responses = _login_operation(spec)["responses"]
    assert set(responses) == {"200", "401", "429", "503"}
    assert responses["401"] == {"$ref": "#/components/responses/Unauthorized"}


def _answer(reply: Any) -> Answer:
    """What a caller can compare: the status, the body's bytes and every header but the
    request's own correlation id."""
    headers = {k: v for k, v in reply.headers.items() if k != "x-correlation-id"}
    return reply.status_code, reply.content, headers


def _sign_in(stack: Stack, identifier: str, password: str) -> Any:
    stack.client.cookies.clear()
    return stack.client.post("/auth/login", json={"identifier": identifier, "password": password})


def _alice(stack: Stack, **update: Any) -> str:
    """`alice`, with `PW` and a confirmed TOTP method, her user row then given *update*."""
    uid, _ = stack.add_user("alice")
    stack.users.add(stack.users.users[str(uid)].model_copy(update=update))
    return str(uid)


_D, _F = AuditOutcome.DENIED, AuditOutcome.FAILURE
_OFF, _UNTIL = {"status": UserStatus.DISABLED}, {"locked_until": T0 + timedelta(minutes=10)}
#: The one state the session repository holds, not the user row: a user who must enrol, disabled
#: between the password check and the session's insert, so the mint refuses her (#2911).
_DURING = "disabled_during_the_sign_in"
#: Each account state: alice's row update (None: no such user), the password sent, and the audit
#: row the refusal writes (action, outcome, reason).
_STATES: dict[str, tuple[dict[str, Any] | None, str, tuple[str, AuditOutcome, str | None]]] = {
    "unknown_identifier": (None, PW, (_FAILED, _F, None)),
    "disabled_right_password": (_OFF, PW, (_FAILED, _D, None)),
    "disabled_wrong_password": (_OFF, _WRONG, (_FAILED, _F, None)),
    "locked_right_password": (_UNTIL, PW, (_LOCKED, _D, None)),
    "locked_wrong_password": (_UNTIL, _WRONG, (_LOCKED, _D, None)),
    "without_mfa_required": ({"mfa_required": False}, PW, (_FAILED, _D, "mfa_not_required")),
    _DURING: ({"mfa_methods": ()}, PW, (_FAILED, _D, "user_disabled")),
}


def _attempt(stack: Stack, name: str) -> Any:
    """Put alice in the state *name*, then sign in as her (as nobody, for an unknown one)."""
    update, password, _ = _STATES[name]
    if update is None:
        return _sign_in(stack, "mallory", password)
    uid = _alice(stack, **update)
    if name == _DURING:
        cast(FakeSessionRepository, stack.auth._session_repository).user_statuses[uid] = (
            UserStatus.DISABLED
        )
    return _sign_in(stack, "alice", password)


def test_the_one_answer_is_the_contracts_unauthenticated_problem(
    spec: dict[str, Any], stack: Stack
) -> None:
    stack.add_user("bob")
    reply = _sign_in(stack, "bob", _WRONG)

    body = reply.json()
    _conforms(spec, body, "/components/schemas/Problem")
    assert (reply.status_code, body["status"], body["code"]) == (401, 401, "unauthenticated")
    assert body["type"] == "https://candleviewer.local/errors/unauthenticated"
    assert reply.headers["content-type"] == "application/problem+json"
    assert "retry-after" not in reply.headers and "set-cookie" not in reply.headers


@pytest.mark.parametrize("name", sorted(_STATES))
def test_each_account_state_answers_byte_for_byte_like_a_wrong_password(
    stack: Stack, name: str
) -> None:
    stack.add_user("bob")
    wrong_password = _answer(_sign_in(stack, "bob", _WRONG))

    assert _answer(_attempt(stack, name)) == wrong_password


@pytest.mark.parametrize("name", sorted(_STATES))
def test_each_account_state_keeps_its_cause_in_the_audit_record(stack: Stack, name: str) -> None:
    _attempt(stack, name)

    (row,) = [r for r in stack.audit.records if r["action"] in (_FAILED, _LOCKED)]
    assert (row["action"], row["outcome"], row.get("reason")) == _STATES[name][2]
