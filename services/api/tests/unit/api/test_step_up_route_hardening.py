"""#2304 over HTTP: the review Lows of the step-up route, each with the test that fails without
its fix: the password cap, what a schema `400` echoes, the reset's refusals after its own gate,
the refusal problems pinned to the contract, and the audit records an answer depends on, written
ahead of it and bounded (`503`, never the `400`, `403` or `200`). Harness:
`test_step_up_challenge_router`."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field, ValidationError
from structlog.testing import capture_logs

from candleviewer.api import step_up as step_up_api
from candleviewer.api.csrf import AUDIT_TIMEOUT_S
from candleviewer.api.step_up import readonly_problem, required_problem
from candleviewer.app import _LazyAuditEmitter
from candleviewer.audit.actions import UnknownAuditAction
from candleviewer.audit.service import AuditService
from candleviewer.audit.writer import AuditUnavailable, AuditWriterStopped
from candleviewer.auth.errors import SelfResetRefused, SessionReadOnly
from candleviewer.auth.step_up import READONLY_WINDOW, StepUpChallenge
from candleviewer.rules import manager as rules_manager
from tests.contract.test_step_up_challenge_contract import _SPEC, _ref, _validator
from tests.unit.api.test_step_up_challenge_router import _RELEASE, _reset_client, _World, _world
from tests.unit.api.test_step_up_rules_route import _ARM, _armable


def _declared(path: str, method: str, status: int) -> Draft202012Validator:
    """The validator of the problem body the contract declares for `status` of an operation: a
    shared response, or the one the operation states itself (`authStepUp`'s `503`)."""
    spec: dict[str, Any] = _SPEC
    response = spec["paths"][path][method]["responses"][str(status)]
    where = (
        f"/components/responses/{response['$ref'].rsplit('/', 1)[1]}"
        if "$ref" in response
        else f"/paths/{path.replace('/', '~1')}/{method}/responses/{status}"
    )
    return _validator(spec, _ref(f"{where}/content/application~1problem+json/schema"))


@pytest.mark.parametrize(
    ("length", "status", "strikes"),
    [(512, 401, 1), (513, 422, 0)],
    ids=["at-the-login-cap", "over-the-login-cap"],
)
async def test_step_up_password_is_capped_like_login_before_any_factor(
    length: int, status: int, strikes: int
) -> None:
    """`LoginRequest.password` is at most 512 characters. A longer one is refused by the schema:
    it never reaches the Argon2id check and counts no strike."""
    w = await _world()
    w.client.put(f"/users/{uuid.uuid4()}/roles", headers=w.h())  # a live grace challenge
    r = w.step_up(password="p" * length)
    assert r.status_code == status
    assert w.rows.sessions[str(w.sessions["tok"].id)].step_up_failures == strikes
    if status == 422:
        assert r.json()["detail"] == "password is too long"
        _declared("/auth/step-up", "post", 422).validate(r.json())  # provider side (C-6.2)
        assert "p" * 8 not in r.text and not w.of("auth.step_up_failed")


async def test_step_up_400_names_declared_fields_only_and_quotes_no_value() -> None:
    """A member the schema does not declare is reported as `body`, never by the name the client
    sent; a malformed value is never quoted."""
    w = await _world()
    w.client.put(f"/users/{uuid.uuid4()}/roles", headers=w.h())  # a live grace challenge
    sent: dict[str, Any] = {"hunter2-looking-member": 1, "code": "12ab56"}
    r = w.step_up(**sent)
    assert r.status_code == 400
    assert sorted((e["field"], e["rule"]) for e in r.json()["errors"]) == [
        ("body", "extra_forbidden"),
        ("code", "string_pattern_mismatch"),
    ]
    assert "hunter2" not in r.text and "12ab56" not in r.text


_CHALLENGE = StepUpChallenge(uuid.uuid4(), "keys", datetime(2026, 9, 30, tzinfo=UTC))


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (required_problem(_CHALLENGE), "step_up_required"),
        (step_up_api._audit_unavailable(), "audit_unavailable"),
    ],
)
def test_refusal_problem_is_the_one_the_contract_catalogues(response: Any, code: str) -> None:
    """Code, status and title are `x-error-codes`' own, as the `401`'s are."""
    spec: dict[str, Any] = _SPEC
    entry = {e["code"]: e for e in spec["x-error-codes"]}[code]
    body, keys = json.loads(bytes(response.body)), ("code", "status", "title")
    assert {k: body[k] for k in keys} == {k: entry[k] for k in keys}


def test_rules_refusal_record_is_bounded_like_the_step_up_write_ahead() -> None:
    assert rules_manager.REFUSAL_AUDIT_TIMEOUT_S == AUDIT_TIMEOUT_S


class _Downgrading:
    """The read model the reset previews: while it is read, three strikes of another request
    turn the owner's session read-only, after the route's own gate passed."""

    source = "oms"

    def __init__(self, w: _World) -> None:
        self._w = w

    async def open_position_count(self, user_id: str) -> int | None:
        until = self._w.clock.now + READONLY_WINDOW
        await self._w.rows.save_step_up_state(
            str(self._w.sessions["tok"].id), elevations={}, failures=3, readonly_until=until
        )
        return 2


async def test_reset_whose_session_turned_read_only_after_the_gate_is_403_never_a_500() -> None:
    w = await _world()
    client = await _reset_client(w, _Downgrading(w))
    r = client.post(f"/users/{uuid.uuid4()}/mfa/reset", headers=w.h())
    until = w.clock.now + READONLY_WINDOW
    assert r.status_code == 403 and r.json()["code"] == "session_read_only"
    assert r.json() == json.loads(bytes(readonly_problem(SessionReadOnly(until)).body))
    assert not w.of("auth.mfa_reset_by_owner")


async def test_reset_that_the_service_refuses_as_a_self_reset_is_403_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route's own check passed, so only the service's refusal (defence in depth) can raise
    it here: answered as the route answers it, never a challenge and never a 500."""
    w = await _world()
    client = await _reset_client(w)

    async def refuse(**_: object) -> None:
        raise SelfResetRefused("the owner cannot reset their own TOTP")

    monkeypatch.setattr(w.auth.step_up, "reset_totp", refuse)
    r = client.post(f"/users/{uuid.uuid4()}/mfa/reset", headers=w.h())
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert "challenge_id" not in r.json()


_BROKEN = ["unavailable", "stopped", "not-started", "stalled"]


def _break_audit(
    w: _World, monkeypatch: pytest.MonkeyPatch, how: str, action: str | None = None
) -> None:
    """From now on `action`'s record (every record, for None) cannot be written: the WAL is full,
    the writer stopped or never started, or it never answers (every wait is out at once)."""
    real = w.audit.emit
    refusal = {
        "unavailable": AuditUnavailable("WAL unwritable"),
        "stopped": AuditWriterStopped(),
        "defect": RuntimeError("a defect"),
        "unknown-action": UnknownAuditAction("auth.typo"),
    }

    async def emit(name: str, **kwargs: Any) -> None:
        if action is not None and name != action:
            return await real(name, **kwargs)
        if how == "stalled":
            for _ in range(100):
                await asyncio.sleep(0)  # a bound of 0 s ends the wait at the first yield
            raise AssertionError("the wait was not bounded")
        if how == "not-started":
            await _LazyAuditEmitter(AuditService()).emit(name, **kwargs)  # RuntimeError
        raise refusal[how]

    monkeypatch.setattr(w.audit, "emit", emit)
    if how == "stalled":
        monkeypatch.setattr(step_up_api, "AUDIT_TIMEOUT_S", 0.0)
        monkeypatch.setattr(rules_manager, "REFUSAL_AUDIT_TIMEOUT_S", 0.0)


@pytest.mark.parametrize(
    ("how", "error"),
    [
        ("unavailable", "AuditUnavailable"),
        ("stopped", "AuditWriterStopped"),
        ("not-started", "RuntimeError"),
        ("stalled", "TimeoutError"),
    ],
)
async def test_refusal_whose_record_cannot_be_written_ahead_is_503_never_the_400(
    monkeypatch: pytest.MonkeyPatch, how: str, error: str
) -> None:
    w = await _world()
    _break_audit(w, monkeypatch, how, "auth.step_up_failed")
    with capture_logs() as logs:
        r = w.step_up(challenge_id=str(uuid.uuid4()))  # an id this session never issued
    assert r.status_code == 503 and r.json()["code"] == "audit_unavailable"
    _declared("/auth/step-up", "post", 503).validate(r.json())  # provider side (C-6.2)
    assert w.rows.sessions[str(w.sessions["tok"].id)].step_up_failures == 0
    # One line for the operator: why the record failed, nothing of the request.
    assert [e for e in logs if e["event"] == "auth.step_up_audit_refused"] == [
        {"event": "auth.step_up_audit_refused", "log_level": "error", "error": error}
    ]


@pytest.mark.parametrize(
    ("how", "defect"), [("defect", RuntimeError), ("unknown-action", UnknownAuditAction)]
)
async def test_refusal_record_that_fails_with_a_defect_is_not_answered_as_503(
    monkeypatch: pytest.MonkeyPatch, how: str, defect: type[Exception]
) -> None:
    """Only the writer's own failures and `audit not started` mean `503`. A `RuntimeError` of
    another kind, or an action the registry lacks (a typo no retry can fix), is a defect and
    reaches the 500 handler as itself."""
    w = await _world()
    _break_audit(w, monkeypatch, how, "auth.step_up_failed")
    with pytest.raises(defect):
        w.step_up(challenge_id=str(uuid.uuid4()))


def test_only_a_too_long_password_reads_as_password_too_long() -> None:
    """`string_too_long` of any other field (none has a maximum today) is not the password's."""

    class _Probe(BaseModel):
        code: str = Field(max_length=1)
        password: str = Field(min_length=1)

    with pytest.raises(ValidationError) as refused:
        _Probe.model_validate({"code": "12", "password": ""})
    body = json.loads(bytes(step_up_api._invalid_body(refused.value).body))
    assert body["detail"] == "password is required"


@pytest.mark.parametrize("how", _BROKEN)
async def test_mismatch_whose_record_cannot_be_written_ahead_is_503_and_keeps_the_grant(
    monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    w = await _world()
    assert w.step_up(challenge_id=w.send(_RELEASE).json()["challenge_id"]).status_code == 200
    with monkeypatch.context() as broken:
        _break_audit(w, broken, how, "auth.step_up_mismatch")
        swapped = w.send({"engaged": False, "scope": "account"})
    assert swapped.status_code == 503 and swapped.json()["code"] == "audit_unavailable"
    assert "challenge_id" not in swapped.json() and w.executed == []  # no challenge, nothing ran
    assert w.send(_RELEASE).status_code == 200  # the grant is still bound to the held request


@pytest.mark.parametrize("how", _BROKEN)
async def test_reset_whose_record_cannot_be_written_ahead_is_503_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    w = await _world()
    client = await _reset_client(w)
    _break_audit(w, monkeypatch, how, "auth.mfa_reset_by_owner")
    target = w.sessions["other"]
    r = client.post(f"/users/{target.user_id}/mfa/reset", headers=w.h())
    assert r.status_code == 503 and r.json()["code"] == "audit_unavailable"
    _declared("/users/{userId}/mfa/reset", "post", 503).validate(r.json())
    assert w.rows.sessions[str(target.id)].revoked_at is None


@pytest.mark.parametrize("how", _BROKEN)
async def test_live_arm_with_the_audit_writer_down_is_503_never_a_500_or_a_hang(
    monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    """`PUT /rules/{ruleId}/mode` with the writer down for every record: neither the mismatch
    record nor the refusal's own `rule.mode_refused` can be written. The `503` stands (it was a
    `500`, or a hang), the rule stays unarmed and the grant stays bound."""
    w = await _world()
    (held, other), trail = await _armable(w, count=2)
    challenge = w.client.put(f"/rules/{held}/mode", headers=w.h(), json=_ARM).json()
    assert w.step_up(challenge_id=challenge["challenge_id"]).status_code == 200
    with monkeypatch.context() as down, capture_logs() as logs:
        _break_audit(w, down, how)
        swapped = w.client.put(f"/rules/{other}/mode", headers=w.h(), json=_ARM)
    assert swapped.status_code == 503 and swapped.json()["code"] == "audit_unavailable"
    _declared("/rules/{ruleId}/mode", "put", 503).validate(swapped.json())
    assert [e["rule_id"] for e in logs if e["event"] == "rules.mode_refusal_unrecorded"] == [other]
    assert "challenge_id" not in swapped.json() and "rule.armed" not in trail
    resent = w.client.put(f"/rules/{held}/mode", headers=w.h(), json=_ARM)  # the writer is back
    assert resent.status_code == 200 and trail.count("rule.armed") == 1
