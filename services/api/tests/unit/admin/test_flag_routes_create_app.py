"""`setFeatureFlag` through the real `create_app()` wiring (E42-T03): the step-up port, the audit
emitter, the user directory, the WS hub, the order-entry gate and the metrics the composition root
gives the flag runtime. Only storage-facing seams are fakes: the fake backend's in-memory flags,
the auth fakes of the invite e2e harness, the identity provider and the user-role store."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from prometheus_client import generate_latest

from candleviewer import app as app_module
from candleviewer.auth.generated_permissions import Permission
from tests.unit.api.test_invites_create_app_e2e import _h, _login
from tests.unit.api.test_step_up_guard_create_app import _world

_KEY = "rules.graph_editor"


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


async def test_a_flag_write_through_the_app_is_stepped_up_audited_and_pushed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    known: set[uuid.UUID] = set()
    users = SimpleNamespace(
        get_roles=AsyncMock(side_effect=lambda u: {"owner"} if u in known else None)
    )
    monkeypatch.setattr(app_module, "build_identity_provider", lambda _s: _Identity())
    monkeypatch.setattr(app_module, "build_user_role_store", lambda _s: users)
    w = await _world(monkeypatch, with_user_repository=True)
    app = cast(FastAPI, w.client.app)
    owner = await _login(w, "owner", frozenset({Permission.FLAGS_WRITE}))
    known.add(uid := w.resolver.by_token[owner].user_id)
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
