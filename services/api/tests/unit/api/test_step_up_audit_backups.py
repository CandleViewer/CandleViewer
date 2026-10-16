"""#2751: SR-025 step-up for the audit-log export (`audit`) and backup restore (`backups`).

On `main` the mounted `POST /admin/audit/export` had no registry row, so an Owner
session that was not elevated exported the audit log. `audit` keeps the 5-minute
grace. `backups` is no-grace because a restore is irreversible: one fresh code
authorises exactly one restore, and the guard spends it.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.auth import step_up as step_up_service
from candleviewer.auth.generated_permissions import Permission
from candleviewer.statechart.bindings import b16_session
from tests.unit.api.test_invites_create_app_e2e import _h, _login
from tests.unit.api.test_step_up_guard_create_app import _world
from tests.unit.api.test_step_up_router import _H, _PW, _build, _code

_EXPORT = {"from": "2026-09-01T00:00:00Z", "to": "2026-09-30T00:00:00Z"}


async def test_audit_export_on_create_app_needs_step_up_then_reaches_the_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    w = await _world(monkeypatch, with_user_repository=True)
    owner = await _login(w, "owner", frozenset({Permission.AUDIT_EXPORT}))
    denied = w.client.post("/admin/audit/export", headers=_h(owner), json=_EXPORT)
    assert denied.status_code == 403 and denied.json()["code"] == "step_up_required"
    assert denied.json()["action_class"] == "audit"
    ok = w.elevate(owner)  # `{code}` only: the server elevates the class it challenged
    assert ok.status_code == 200 and ok.json()["action_class"] == "audit"
    assert ok.json()["single_use"] is False
    for _ in range(2):  # the grace window covers a second export
        r = w.client.post("/admin/audit/export", headers=_h(owner), json=_EXPORT)
        # The handler answers: this fake backend wires no audit principal resolver.
        assert r.status_code == 501 and r.json()["title"] == "Not implemented"


def _restore_route(c: TestClient) -> list[str]:
    """Mount a stand-in `restoreBackup` (no handler exists yet) behind the real guard."""
    ran: list[str] = []

    @cast(FastAPI, c.app).post("/admin/backups/{backup_id}/restore")
    async def restore(backup_id: str) -> dict[str, bool]:
        ran.append(backup_id)
        return {"ok": True}

    return ran


async def test_backup_restore_spends_one_fresh_code_per_restore() -> None:
    c, em, seed, clock, _ = await _build()
    ran = _restore_route(c)
    path = f"/admin/backups/{uuid.uuid4()}/restore"
    denied = c.post(path, headers=_H)
    assert denied.status_code == 403 and denied.json()["code"] == "step_up_required"
    assert denied.json()["action_class"] == "backups" and not ran
    ok = c.post("/auth/step-up", headers=_H, json={"code": _code(seed, clock), "password": _PW})
    assert ok.status_code == 200 and ok.json()["action_class"] == "backups"
    assert ok.json()["single_use"] is True and ok.json()["step_up_expires_at"] is None
    assert c.post(path, headers=_H).status_code == 200 and len(ran) == 1
    again = c.post(path, headers=_H)  # no grace: the code was spent on the first restore
    assert again.status_code == 403 and again.json()["action_class"] == "backups"
    assert len(ran) == 1
    assert em.actions().count("auth.step_up_required") == 2


@pytest.mark.parametrize(("action_class", "single_use"), [("audit", False), ("backups", True)])
async def test_step_up_accepts_the_new_classes_and_b16_records_the_grant(
    action_class: str, single_use: bool
) -> None:
    c, em, seed, clock, _ = await _build()
    body = {"code": _code(seed, clock), "password": _PW, "action_class": action_class}
    ok = c.post("/auth/step-up", headers=_H, json=body)
    assert ok.status_code == 200 and ok.json()["single_use"] is single_use
    (granted,) = [x for x in em.calls if x["action"] == "auth.step_up_granted"]
    assert granted["reason"] == action_class
    # A grace class opens a window on the chart; a no-grace one never does.
    window = [] if single_use else [action_class]
    assert granted["after_state"]["elevated_classes"] == window


def test_backups_never_has_a_grace_window_while_audit_does() -> None:
    for module in (step_up_service, b16_session):
        assert {"audit", "backups"} <= module.ACTION_CLASSES
        assert "backups" in module.NO_GRACE_ACTION_CLASSES
        assert "audit" not in module.NO_GRACE_ACTION_CLASSES
    context = {"elevated_classes": {"audit": 10, "backups": 10}}
    assert b16_session.grace_window_valid(context, {"action_class": "audit", "now_us": 9})
    assert not b16_session.grace_window_valid(context, {"action_class": "backups", "now_us": 9})


def test_contract_step_up_classes_match_the_service() -> None:
    """Contract first (C-6.1): the `authStepUp` enum is the class list the server accepts."""
    op = cast(dict[str, Any], load_openapi_spec())["paths"]["/auth/step-up"]["post"]
    schema = op["requestBody"]["content"]["application/json"]["schema"]
    assert set(schema["properties"]["action_class"]["enum"]) == step_up_service.ACTION_CLASSES
