"""#2304 over HTTP: a no-grace grant is bound to the held request. The client holds the refused
request and re-sends it unchanged after the step-up; only that request can use the grant, once,
within 60 seconds. Harness: `test_step_up_challenge_router` (`POST /trading/kill-switch`)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import pytest

from candleviewer.api.step_up import consume_bound_grant, require_elevation_for
from candleviewer.api.step_up_challenge import request_fingerprint
from candleviewer.audit.models import AuditOutcome
from candleviewer.auth.errors import StepUpMismatch
from tests.contract.test_step_up_challenge_contract import _PROBLEM, _SPEC, _ref, _validator
from tests.unit.api.test_step_up_challenge_router import _RELEASE, _KillSwitch, _world
from tests.unit.api.test_step_up_router import _PW, _code


def _fingerprint(body: dict[str, Any], target: bytes = b"/trading/kill-switch") -> str:
    validated = _KillSwitch.model_validate(body).model_dump(mode="json")
    return request_fingerprint("POST", target, validated)


async def test_held_request_executes_once_after_its_bound_step_up() -> None:
    """Re-sent unchanged with the same key, the held request is a first submission: it executes
    once and is never answered from an idempotency store; a second re-send is challenged."""
    w = await _world()
    challenge_id = w.send(_RELEASE).json()["challenge_id"]
    ok = w.step_up(challenge_id=challenge_id)
    assert ok.status_code == 200
    grant = ok.json()
    assert grant["single_use"] is True and grant["step_up_expires_at"] is None
    assert datetime.fromisoformat(grant["elevated_until"]) == w.clock.now + timedelta(seconds=60)
    (granted,) = w.of("auth.step_up_granted")
    assert granted["object_id"] == challenge_id
    assert granted["after_state"]["bound_request_sha256"] == _fingerprint(_RELEASE)
    resent = w.send(_RELEASE)
    assert resent.status_code == 200 and "idempotency-replayed" not in resent.headers
    again = w.send(_RELEASE)
    assert again.status_code == 403 and again.json()["challenge_id"] != challenge_id
    assert len(w.executed) == 1 and len(w.of("auth.step_up_required")) == 2


async def test_bound_grant_refuses_a_swapped_payload() -> None:
    """AC "Bound single-use grant refuses a swapped payload" (#2304)."""
    w = await _world()
    challenge_id = w.send(_RELEASE).json()["challenge_id"]
    assert w.step_up(challenge_id=challenge_id).status_code == 200
    swapped = {"engaged": False, "scope": "account", "account_ids": ["demo-1"]}
    refused = w.send(swapped)
    assert refused.status_code == 403 and refused.json()["code"] == "step_up_required"
    assert refused.json()["challenge_id"] != challenge_id  # a challenge for the new request
    assert refused.json()["action_summary"] == "Release kill switch, scope account"
    (mismatch,) = w.of("auth.step_up_mismatch")
    assert mismatch["outcome"] == AuditOutcome.DENIED and mismatch["reason"] == "killswitch"
    assert mismatch["object_id"] == challenge_id
    assert mismatch["session_id"] == str(w.sessions["tok"].id)
    assert mismatch["after_state"] == {
        "bound_request_sha256": _fingerprint(_RELEASE),
        "refused_request_sha256": _fingerprint(swapped),
    }
    assert w.executed == []
    assert w.send(_RELEASE).status_code == 200  # the refusal did not use up the grant


@pytest.mark.parametrize(
    ("path", "content", "same"),
    [
        ("", '{ "scope" : "global",\n  "engaged" : false }', True),
        ("", '{"engaged": false, "scope": "global", "reason": null}', True),
        ("?scope=account", '{"engaged": false, "scope": "global"}', False),
        ("", '{"engaged": false, "scope": "global", "reason": "x"}', False),
    ],
    ids=["member-order-and-whitespace", "explicit-default", "query-string", "free-text"],
)
async def test_binding_covers_the_target_and_the_validated_body(
    path: str, content: str, same: bool
) -> None:
    w = await _world()
    assert w.step_up(challenge_id=w.send(_RELEASE).json()["challenge_id"]).status_code == 200
    headers = w.h() | {"Content-Type": "application/json", "Idempotency-Key": "another-key"}
    resent = w.client.post(f"/trading/kill-switch{path}", headers=headers, content=content)
    assert (resent.status_code == 200) is same
    assert len(w.of("auth.step_up_mismatch")) == (0 if same else 1)


async def test_grant_expires_sixty_seconds_after_the_step_up() -> None:
    w = await _world()
    assert w.step_up(challenge_id=w.send(_RELEASE).json()["challenge_id"]).status_code == 200
    w.clock.now += timedelta(seconds=60)
    late = w.send(_RELEASE)
    assert late.status_code == 403 and late.json()["code"] == "step_up_required"
    assert w.executed == [] and len(w.of("auth.step_up_required")) == 2


@pytest.mark.parametrize("live", [True, False], ids=["live-challenge", "action-class-only"])
async def test_no_grace_step_up_without_challenge_id_is_400_before_any_factor(
    live: bool,
) -> None:
    w = await _world()
    if live:
        w.send(_RELEASE)
    r = w.client.post(
        "/auth/step-up",
        headers=w.h(),
        json={"code": "000000", "password": "wrong", "action_class": "killswitch"},
    )
    assert r.status_code == 400
    _validator(_SPEC, _ref(_PROBLEM)).validate(r.json())
    assert r.json()["errors"][0]["field"] == "challenge_id"
    assert r.json()["errors"][0]["rule"] == "challenge_required"
    (refused,) = w.of("auth.step_up_failed")  # the refusal, audited; no factor was checked
    assert (refused["outcome"], refused["reason"]) == (AuditOutcome.DENIED, "challenge_required")
    assert w.rows.sessions[str(w.sessions["tok"].id)].step_up_failures == 0
    assert not w.of("auth.step_up_granted")


async def test_no_grace_gate_that_cannot_bind_its_request_fails_closed() -> None:
    w = await _world()
    with pytest.raises(TypeError, match="fingerprint"):
        await require_elevation_for(w.auth, str(w.sessions["tok"].id), "killswitch")


async def test_mismatch_is_never_answered_unaudited() -> None:
    w = await _world()
    assert w.step_up(challenge_id=w.send(_RELEASE).json()["challenge_id"]).status_code == 200
    sid = str(w.sessions["tok"].id)
    with pytest.raises(RuntimeError, match=r"auth\.step_up_mismatch"):
        await consume_bound_grant(w.auth.step_up, None, sid, "killswitch", "b" * 64)
    with pytest.raises(StepUpMismatch):  # the grant is still bound to the held request
        await w.auth.step_up.consume_single_use(sid, "killswitch", fingerprint="b" * 64)


async def test_binding_writes_no_password_code_or_body_to_logs_or_audit(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    w = await _world()
    held = _RELEASE | {"reason": "private-note-7731"}
    code = _code(w.seed, w.clock)
    payload = {"code": code, "password": _PW, "challenge_id": w.send(held).json()["challenge_id"]}
    assert w.client.post("/auth/step-up", headers=w.h(), json=payload).status_code == 200
    w.send(held | {"scope": "account"})  # mismatch
    assert w.send(held).status_code == 200
    recorded = repr(w.audit.calls)
    for secret in (_PW, f"'{code}'", f'"{code}"', "private-note-7731"):
        assert secret not in caplog.text and secret not in recorded
