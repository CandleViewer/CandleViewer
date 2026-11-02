"""#2152 S5b: the provider half of `AuthUnavailable` (`22-api-openapi.yaml`, C-6.1). Over the real
`create_app()` routers and services of `tests/security/auth/_stack.py`, each of the eight MFA
operations answers `503 auth_unavailable` while the keyring refuses: `Retry-After: 30`, a body that
conforms to `Problem` and names no cause, and one `auth.mfa_unavailable` record naming the
operation. A request an invite route answered so stored nothing to replay: sent again, key and
all, it executes once (BQ-17). A user without a method and an existing session are unaffected."""

from __future__ import annotations

import base64
import inspect
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from prometheus_client import generate_latest
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from structlog.testing import capture_logs

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.audit.actions import validate_action
from candleviewer.audit.models import AuditOutcome
from candleviewer.auth.models import InviteCreateRequest
from candleviewer.auth.session_service import ENROLMENT_ONLY_LIFETIME
from candleviewer.auth.throttle import PerIpLoginThrottle
from tests.csrf_helpers import csrf_headers
from tests.security.auth._stack import INVITE_PW, PW, Stack, open_stack
from tests.unit.auth.auth_fakes import make_user
from tests.unit.auth.mfa_fakes import TEST_RECOVERY_KEY, TEST_TOTP_KEY, FakeMfaRepository

_BASE = "urn:cv:openapi"
DOWN = "kek_unavailable"
_ACTION = "auth.mfa_unavailable"


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    with open_stack(monkeypatch) as s:
        yield s


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    return load_openapi_spec()


def _password_step(stack: Stack, name: str) -> str:
    """The `mfa_token` of `name`'s password step, taken while the keyring serves."""
    answer = stack.client.post("/auth/login", json={"identifier": name, "password": PW})
    assert answer.status_code == 200, answer.text
    return str(answer.json()["mfa_token"])


def _methodless(stack: Stack, name: str) -> dict[str, str]:
    """The bearer and CSRF headers of the enrolment-only session of a user with no method yet,
    minted as sign-in mints one (#2295)."""
    unusable = "$argon2id$v=19$m=65536,t=3,p=4$" + uuid.uuid4().hex  # verifies no password
    email = f"{name}@example.test"
    user = make_user(username=name, email=email, password_hash=unusable, mfa_methods=())
    stack.users.add(user)
    expires_at = stack.clock.now + ENROLMENT_ONLY_LIFETIME
    minted = stack.call(
        stack.auth.sessions.mint, str(user.id), mfa_satisfied=False, expires_at=expires_at
    )
    csrf = csrf_headers(stack.state.csrf_codec, minted.session_id)
    return {"Authorization": f"Bearer {minted.access_token}", **csrf}


def _invite(stack: Stack) -> str:
    async def ok(user_id: uuid.UUID, role: str) -> None:
        """An accepting write-ahead hook."""

    body = {"email": "ann@example.test", "username": "annie", "roles": ["viewer"]}
    created = stack.call(
        stack.auth.invites.create,
        InviteCreateRequest.model_validate(body),
        invited_by=uuid.uuid4(),
        audit=ok,
    )
    return str(created.token)


def _login(stack: Stack) -> Any:
    stack.add_user("alice")
    stack.keyring.down = DOWN
    return stack.client.post("/auth/login", json={"identifier": "alice", "password": PW})


def _verify(stack: Stack) -> Any:
    stack.add_user("alice")
    token = _password_step(stack, "alice")
    stack.keyring.down = DOWN
    body = {"mfa_token": token, "method": "totp", "code": "123456"}
    return stack.client.post("/auth/mfa/verify", json=body)


def _recovery(stack: Stack) -> Any:
    stack.add_user("alice")
    token = _password_step(stack, "alice")
    stack.keyring.down = DOWN
    body = {"mfa_token": token, "recovery_code": "ABCD-EFGH-JKLM"}
    return stack.client.post("/auth/mfa/recovery", json=body)


def _enroll(stack: Stack) -> Any:
    headers = _methodless(stack, "carol")
    stack.keyring.down = DOWN
    return stack.client.post("/auth/mfa/enroll", headers=headers, json={"method": "totp"})


def _enroll_confirm(stack: Stack) -> Any:
    headers = _methodless(stack, "carol")
    started = stack.client.post("/auth/mfa/enroll", headers=headers, json={"method": "totp"})
    assert started.status_code == 201, started.text
    stack.keyring.down = DOWN
    body = {"method_id": started.json()["method_id"], "code": "123456"}
    return stack.client.post("/auth/mfa/enroll/confirm", headers=headers, json=body)


def _step_up(stack: Stack) -> Any:
    headers, seed = stack.principal("bob", "owner")
    stack.keyring.down = DOWN
    body = {"code": stack.code(seed), "password": PW, "action_class": "users"}  # a grace class
    return stack.client.post("/auth/step-up", headers=headers, json=body)


def _redeem(stack: Stack) -> Any:
    token = _invite(stack)
    stack.keyring.down = DOWN
    return stack.client.post(f"/invites/{token}", json={"password": INVITE_PW})


def _confirm_invite(stack: Stack) -> Any:
    token = _invite(stack)
    start = stack.client.post(f"/invites/{token}", json={"password": INVITE_PW})
    assert start.status_code == 200, start.text
    stack.keyring.down = DOWN
    body = {"method_id": start.json()["method_id"], "code": "123456"}
    return stack.client.post(f"/invites/{token}/confirm", json=body)


#: The eight operations (ruling D4), each driven into the `503` after what the contract lets
#: come first.
OPERATIONS: dict[str, Callable[[Stack], Any]] = {
    "authLogin": _login,
    "authMfaVerify": _verify,
    "authMfaRecovery": _recovery,
    "authMfaEnroll": _enroll,
    "authMfaEnrollConfirm": _enroll_confirm,
    "authStepUp": _step_up,
    "redeemInvite": _redeem,
    "confirmInvite": _confirm_invite,
}


def _seed(start: dict[str, Any]) -> bytes:
    b32 = str(start["secret_base32"])
    return base64.b32decode(b32 + "=" * (-len(b32) % 8))


def _conforms(spec: dict[str, Any], value: Any, pointer: str) -> None:
    resource = Resource.from_contents(spec, default_specification=DRAFT202012)
    Draft202012Validator(
        {"$ref": f"{_BASE}#{pointer}"},
        registry=Registry().with_resource(_BASE, resource),
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    ).validate(value)


@pytest.mark.parametrize("operation", sorted(OPERATIONS))
def test_each_mfa_operation_answers_the_contract_s_503(
    stack: Stack, spec: dict[str, Any], operation: str
) -> None:
    answer = OPERATIONS[operation](stack)

    assert answer.status_code == 503, answer.text
    assert answer.headers["content-type"].startswith("application/problem+json")
    assert answer.headers["retry-after"] == "30"
    body = answer.json()
    _conforms(spec, body, "/components/schemas/Problem")
    example = spec["components"]["responses"]["AuthUnavailable"]["content"][
        "application/problem+json"
    ]["examples"]["mfaUnavailable"]["value"]
    for field in ("type", "title", "status", "code", "detail", "retry_after_seconds"):
        assert body[field] == example[field], field
    (record,) = stack.audit.of(_ACTION)
    assert record["outcome"] is AuditOutcome.FAILURE
    assert record["after_state"] == {"operation": operation, "reason": "auth_keyring_unavailable"}


#: The two second-factor routes, which share one per-address budget of refusals (#4664, SR-015),
#: each with a body and the factor its failures are counted under.
_SECOND_FACTOR: dict[str, tuple[str, dict[str, str], str]] = {
    "authMfaVerify": ("/auth/mfa/verify", {"method": "totp", "code": "123456"}, "totp"),
    "authMfaRecovery": (
        "/auth/mfa/recovery", {"recovery_code": "ABCD-EFGH-JKLM"}, "recovery_code"
    ),
}  # fmt: skip


@pytest.mark.parametrize("operation", sorted(_SECOND_FACTOR))
def test_the_503_spends_none_of_the_address_s_second_factor_budget(
    stack: Stack, operation: str
) -> None:
    """AC5 at the router: the `503` is no refusal of the caller (#4664), so the budget's limit
    plus one requests from one address while the keyring is down each answer it, never the `429`
    of an address over its budget, and no failure is counted. `create_app` builds the router
    with the default budget."""
    limit: int = inspect.signature(PerIpLoginThrottle).parameters["max_attempts"].default
    path, body, factor = _SECOND_FACTOR[operation]
    stack.add_user("alice")
    body = body | {"mfa_token": _password_step(stack, "alice")}
    failures = stack.scraped("auth_login_failures_total", method=factor)
    stack.keyring.down = DOWN
    answers = [stack.client.post(path, json=body).status_code for _ in range(limit + 1)]
    assert answers == [503] * (limit + 1)
    assert stack.scraped("auth_login_failures_total", method=factor) == failures


def test_an_enrolment_refused_at_the_seal_records_its_user(
    stack: Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The keyring passes the check, then refuses the seal, where M2's refusal names no user: the
    record still names the enrolling user, whom the handler knows (as the confirm routes' do)."""
    headers = _methodless(stack, "carol")
    seal = stack.keyring.seal_totp_seed

    async def down_at_the_seal(seed: bytes | bytearray, user_id: uuid.UUID) -> tuple[bytes, str]:
        stack.keyring.down = DOWN
        return await seal(seed, user_id)

    monkeypatch.setattr(stack.keyring, "seal_totp_seed", down_at_the_seal)
    answer = stack.client.post("/auth/mfa/enroll", headers=headers, json={"method": "totp"})
    assert answer.status_code == 503, answer.text
    carol = next(u for u in stack.users.users.values() if u.username == "carol")
    (record,) = stack.audit.of(_ACTION)
    assert (record["actor_user_id"], record["actor_label"]) == (carol.id, str(carol.id))
    assert record["after_state"]["operation"] == "authMfaEnroll"


@pytest.mark.parametrize("operation", ["redeemInvite", "confirmInvite"])
def test_an_invite_request_met_by_the_503_executes_once_when_sent_again(
    stack: Stack, operation: str
) -> None:
    """BQ-17: the `503` stored no idempotency record and changed nothing, so the same request
    with the same `Idempotency-Key` is a first submission once the keyring serves again."""
    token = _invite(stack)
    key = {"Idempotency-Key": str(uuid.uuid4())}
    path, body = f"/invites/{token}", {"password": INVITE_PW}
    if operation == "confirmInvite":
        start = stack.client.post(path, headers=key, json=body)
        assert start.status_code == 200, start.text
        path = f"/invites/{token}/confirm"
        body = {"method_id": start.json()["method_id"], "code": stack.code(_seed(start.json()))}
    stack.keyring.down = DOWN
    assert stack.client.post(path, headers=key, json=body).status_code == 503
    stack.keyring.down = None
    again = stack.client.post(path, headers=key, json=body)
    assert again.status_code == 200, again.text
    assert "idempotency-replayed" not in again.headers


def test_the_record_is_a_registered_action_of_the_closed_vocabulary() -> None:
    """`24-internal-schemas.md` §15.5 lists it, so dashboards and alerts can be exhaustive."""
    internal = (Path(__file__).resolve().parents[4] / "docs/plan/24-internal-schemas.md").read_text(
        encoding="utf-8"
    )
    closed = internal[internal.index("### 15.5 Audited action vocabulary") :]
    assert f"`{_ACTION}`" in closed.split("\n\n", 2)[1]
    assert validate_action(_ACTION) == _ACTION


def test_users_without_a_method_and_existing_sessions_are_unaffected(stack: Stack) -> None:
    """AC5: a user without MFA still signs in, and a session minted before keeps working."""
    headers, _ = stack.principal("bob", "owner")
    hashed = next(iter(stack.users.users.values())).password_hash  # `PW`, as the stack hashes it
    dave = make_user(username="dave", email="dave@example.test", password_hash=hashed)
    stack.users.add(dave.model_copy(update={"mfa_methods": ()}))
    stack.keyring.down = DOWN
    assert stack.client.get("/auth/session", headers=headers).status_code == 200
    signed_in = stack.client.post("/auth/login", json={"identifier": "dave", "password": PW})
    assert signed_in.status_code == 200, signed_in.text  # an enrolment-only session (#2295)
    assert stack.audit.of(_ACTION) == []


def _encodings(value: bytes) -> list[str]:
    """A secret as a sink could show it: hex either case, base32 and base64."""
    hexed = value.hex()
    b32, b64 = base64.b32encode(value).decode(), base64.b64encode(value).decode()
    return [hexed, hexed.upper(), b32, b32.rstrip("="), b64, b64.rstrip("=")]


@pytest.mark.parametrize("operation", sorted(OPERATIONS))
def test_no_key_seed_or_code_reaches_a_sink_on_the_503(stack: Stack, operation: str) -> None:
    """AC13 on the new paths: the answer, its record, every log line and the metrics name no
    keyring key, no seed made for the run's users and no code sent."""
    with capture_logs() as logs:
        answer = OPERATIONS[operation](stack)
    assert answer.status_code == 503
    repo = stack.auth._mfa_repository
    assert isinstance(repo, FakeMfaRepository)
    seeds = [m.secret_enc for m in repo.methods.values()]  # sealed blobs
    opened = [bytes(stack.keyring.decrypt(blob)) for blob in seeds if blob is not None]
    sentinels = [*_encodings(TEST_TOTP_KEY), *_encodings(TEST_RECOVERY_KEY)]
    sentinels += [text for seed in opened for text in _encodings(seed)]
    sentinels += ["ABCD-EFGH-JKLM", "ABCDEFGHJKLM", PW, INVITE_PW]
    exposition = generate_latest(stack.state.app_context.metrics).decode()
    shown = [answer.text, repr(stack.audit.records), repr(logs), exposition]
    assert [s for s in sentinels for text in shown if s in text] == []
