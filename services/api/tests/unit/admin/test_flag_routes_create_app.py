"""`setFeatureFlag` through the real `create_app()` wiring (E42-T03): the step-up port, the audit
emitter, the user directory, the WS hub, the order-entry gate and the metrics the composition root
gives the flag runtime; a no-grace write through the real `StepUpService`. Only storage-facing
seams are fakes: the fake backend's in-memory flags, the auth fakes of the invite e2e harness, the
identity provider and the user-role store."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from prometheus_client import generate_latest

from candleviewer import app as app_module
from candleviewer.api.step_up_challenge import request_fingerprint
from candleviewer.audit.models import AuditOutcome
from candleviewer.auth.generated_permissions import Permission
from tests.contract.test_step_up_challenge_contract import (
    _SPEC,
    _STEP_UP_REQUIRED_BODY,
    _validator,
)
from tests.unit.api.test_invites_create_app_e2e import _h, _login, _World
from tests.unit.api.test_step_up_guard_create_app import _world

_KEY = "rules.graph_editor"
_LIVE, _EVIDENCE = "trading.live_enabled", "https://github.com/basiltt/CandleViewer/issues/412"


class _Identity:
    async def user(self, user_id: str) -> dict[str, Any]:
        return {"username": "owner", "status": "active", "roles": ["owner"]}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": ["flags:read", "flags:write"]}


class _Socket:
    """An authenticated `system` socket of `user_id` on the app's own WS hub."""

    def __init__(self, user_id: uuid.UUID, frames: list[dict[str, Any]]) -> None:
        self.user_id, self.push_system = user_id, frames.append
        self.authz = SimpleNamespace(principal=SimpleNamespace(roles=frozenset({"owner"})))
        self.lifecycle = SimpleNamespace(authenticated=True)


async def _owner(monkeypatch: pytest.MonkeyPatch) -> tuple[_World, str, uuid.UUID]:
    """The app `create_app()` builds, and an owner signed in to it with `flags:write`, who exists
    in its user store."""
    known: set[uuid.UUID] = set()
    users = SimpleNamespace(
        get_roles=AsyncMock(side_effect=lambda u: {"owner"} if u in known else None)
    )
    monkeypatch.setattr(app_module, "build_identity_provider", lambda _s: _Identity())
    monkeypatch.setattr(app_module, "build_user_role_store", lambda _s: users)
    w = await _world(monkeypatch, with_user_repository=True)
    owner = await _login(w, "owner", frozenset({Permission.FLAGS_WRITE}))
    known.add(uid := w.resolver.by_token[owner].user_id)
    return w, owner, uid


async def test_a_flag_write_through_the_app_is_stepped_up_audited_and_pushed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w, owner, uid = await _owner(monkeypatch)
    app = cast(FastAPI, w.client.app)
    frames: list[dict[str, Any]] = []
    app.state.ws_hub._live.add(_Socket(uid, frames))
    listed = w.client.get("/admin/feature-flags", headers=_h(owner)).json()["items"]
    read = next(item for item in listed if item["key"] == _KEY)["updated_at"]

    def put(override: uuid.UUID) -> Any:
        body = {"value": False, "reason": "drill", "expected_updated_at": read}
        body["overrides"] = [{"user_id": str(override), "value": True}]
        return w.client.put(f"/admin/feature-flags/{_KEY}", headers=_h(owner), json=body)

    refused = put(uuid.uuid4())  # no such user: refused before any step-up
    assert refused.json()["errors"] == [{"field": "overrides", "rule": "unknown_user"}]
    challenge = put(uid)
    assert (challenge.status_code, challenge.json()["code"]) == (403, "step_up_required")
    summary = f"Set feature flag '{_KEY}' to false, user overrides 1"
    assert (challenge.json()["action_summary"], challenge.json()["target"]) == (summary, None)
    assert w.elevate(owner).json()["action_class"] == "flags"
    assert put(uid).status_code == 200
    records = [(r["reason"], r["after_state"].get("phase")) for r in w.audit.of("flags.change")]
    assert records == [("unknown_user", None), ("drill", "intent"), ("ok", "outcome")]
    assert frames == [{"kind": "feature_flags", "feature_flags": {_KEY: True}}]  # its override
    assert app.state.order_entry_gate is app.state.feature_flags.order_entry_gate
    assert b"cv_feature_flag_changes_total" in generate_latest(app.state.app_context.metrics)


async def test_a_no_grace_flag_write_waits_for_the_step_up_bound_to_its_own_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`trading.live_enabled: true` takes a `live_enablement` step-up, whose grant is single use and
    bound to the request the challenge refused (#2304): here through the app's own step-up port and
    audit emitter, and the real `StepUpService`. A write with another body is refused and audited,
    the grant stays, and the held request, re-sent unchanged, commits once."""
    w, owner, uid = await _owner(monkeypatch)
    session = await w.auth.sessions.authenticate_access_token(owner)  # the one the grant is on

    def shown() -> dict[str, Any]:
        items = w.client.get("/admin/feature-flags", headers=_h(owner)).json()["items"]
        return next(item for item in items if item["key"] == _LIVE)

    target = f"/admin/feature-flags/{_LIVE}"  # the raw request target the grant is bound to
    held = {"value": True, "reason": "pen test passed", "evidence_url": _EVIDENCE}
    held |= {"expected_updated_at": shown()["updated_at"]}
    other = held | {"reason": "a different reason"}
    held_hash = request_fingerprint("PUT", target.encode(), held)

    def put(body: dict[str, Any]) -> Any:
        return w.client.put(target, headers=_h(owner), json=body)

    challenge = put(held)
    assert (challenge.status_code, challenge.json()["code"]) == (403, "step_up_required")
    _validator(_SPEC, _STEP_UP_REQUIRED_BODY).validate(challenge.json())  # provider side (C-6.2)
    challenge_id = challenge.json()["challenge_id"]
    summary = f"Set feature flag '{_LIVE}' to true, user overrides 0"
    assert (challenge.json()["action_class"], challenge.json()["action_summary"]) == (
        "live_enablement",
        summary,
    )
    [required] = w.audit.of("auth.step_up_required")
    assert required["object_id"] == challenge_id
    granted = w.elevate(owner, challenge_id=challenge_id)
    assert (granted.status_code, granted.json()["single_use"]) == (200, True)
    [grant] = w.audit.of("auth.step_up_granted")
    assert grant["after_state"]["bound_request_sha256"] == held_hash

    swapped = put(other)  # the grant is bound to `held`, not to this body
    assert (swapped.status_code, swapped.json()["code"]) == (403, "step_up_required")
    _validator(_SPEC, _STEP_UP_REQUIRED_BODY).validate(swapped.json())  # as the first one is
    assert swapped.json()["challenge_id"] != challenge_id  # a challenge for this very request
    [mismatch] = w.audit.of("auth.step_up_mismatch")
    assert (mismatch["object_id"], mismatch["reason"], mismatch["outcome"]) == (
        challenge_id,
        "live_enablement",
        AuditOutcome.DENIED,
    )
    assert (mismatch["actor_user_id"], mismatch["session_id"]) == (str(uid), str(session.id))
    assert mismatch["after_state"] == {
        "bound_request_sha256": held_hash,
        "refused_request_sha256": request_fingerprint("PUT", target.encode(), other),
    }
    steps = [call["action"] for call in w.audit.calls if call["action"].startswith("auth.step_up")]
    assert steps == [  # the mismatch is written ahead of the fresh challenge's own record
        "auth.step_up_required",
        "auth.step_up_granted",
        "auth.step_up_mismatch",
        "auth.step_up_required",
    ]
    assert (w.audit.of("flags.change"), shown()["value"]) == ([], False)  # nothing was written

    committed = put(held)  # the held request, re-sent unchanged, spends the grant
    assert (committed.status_code, committed.json()["value"]) == (200, True)
    records = [(r["reason"], r["after_state"].get("phase")) for r in w.audit.of("flags.change")]
    assert records == [("pen test passed", "intent"), ("ok", "outcome")]
    assert shown()["value"] is True
    assert put(held).json()["code"] == "step_up_required"  # single use: nothing left to spend
