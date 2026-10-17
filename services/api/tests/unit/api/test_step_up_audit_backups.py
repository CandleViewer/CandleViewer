"""#2751: SR-025 step-up for the audit-log export (`audit`) and backup restore (`backups`).

On `main` the mounted `POST /admin/audit/export` had no registry row, so an Owner
session that was not elevated exported the audit log. `audit` keeps the 5-minute
grace. `backups` is no-grace because a restore is irreversible: one fresh code
authorises exactly one restore, which its handler binds and spends (#2304).
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.step_up import require_elevation_for
from candleviewer.api.step_up_challenge import raw_request_target, request_fingerprint
from candleviewer.auth import step_up as step_up_service
from candleviewer.auth.generated_permissions import Permission
from candleviewer.statechart.bindings import b16_session
from tests.unit.api.test_invites_create_app_e2e import _h, _login
from tests.unit.api.test_step_up_challenge_router import _World
from tests.unit.api.test_step_up_challenge_router import _world as _challenge_world
from tests.unit.api.test_step_up_guard_create_app import _world

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
        # The guard let it through: whatever the handler answers, it is not a step-up refusal.
        assert r.status_code != 403 and r.json().get("code") != "step_up_required"


def _restore_route(w: _World) -> list[str]:
    """Mount a stand-in `restoreBackup` (no handler exists yet) that, like its ticket's handler,
    gates the request it validated (#2304): a no-grace grant binds that request."""
    ran: list[str] = []

    @cast(FastAPI, w.client.app).post("/admin/backups/{backup_id}/restore")
    async def restore(backup_id: str, request: Request) -> Any:
        body = await request.json()
        denied = await require_elevation_for(
            w.auth,
            str(w.sessions["tok"].id),
            "backups",
            fingerprint=request_fingerprint(request.method, raw_request_target(request), body),
            emitter=w.audit,
        )
        if denied is not None:
            return denied
        ran.append(backup_id)
        return {"ok": True}

    return ran


#: The restore the client holds, and where it sends it.
_HELD = {"confirm_backup_id": str(uuid.UUID(int=7)), "reason": "restore drill"}
_RESTORE = f"/admin/backups/{uuid.UUID(int=7)}/restore"


async def test_backup_restore_spends_one_fresh_code_per_restore() -> None:
    w = await _challenge_world()
    ran = _restore_route(w)
    denied = w.client.post(_RESTORE, headers=w.h(), json=_HELD)
    assert denied.status_code == 403 and denied.json()["code"] == "step_up_required"
    assert denied.json()["action_class"] == "backups" and not ran
    ok = w.step_up(challenge_id=denied.json()["challenge_id"])
    assert ok.status_code == 200 and ok.json()["action_class"] == "backups"
    assert ok.json()["single_use"] is True and ok.json()["step_up_expires_at"] is None
    assert w.client.post(_RESTORE, headers=w.h(), json=_HELD).status_code == 200 and len(ran) == 1
    again = w.client.post(_RESTORE, headers=w.h(), json=_HELD)  # no grace: the code was spent
    assert again.status_code == 403 and again.json()["action_class"] == "backups"
    assert len(ran) == 1 and len(w.of("auth.step_up_required")) == 2


async def test_backup_restore_grant_is_bound_to_the_restore_it_was_given_for() -> None:
    w = await _challenge_world()
    ran = _restore_route(w)
    challenge_id = w.client.post(_RESTORE, headers=w.h(), json=_HELD).json()["challenge_id"]
    assert w.step_up(challenge_id=challenge_id).status_code == 200
    other = {**_HELD, "reason": "another restore"}
    refused = w.client.post(_RESTORE, headers=w.h(), json=other)
    assert refused.status_code == 403 and refused.json()["challenge_id"] != challenge_id
    assert len(w.of("auth.step_up_mismatch")) == 1 and not ran
    assert w.client.post(_RESTORE, headers=w.h(), json=_HELD).status_code == 200  # still bound


@pytest.mark.parametrize(("action_class", "single_use"), [("audit", False), ("backups", True)])
async def test_step_up_accepts_the_new_classes_and_b16_records_the_grant(
    action_class: str, single_use: bool
) -> None:
    w = await _challenge_world()
    answer: dict[str, Any] = {"action_class": action_class}
    if single_use:  # a no-grace class is answered by its challenge, which binds one request
        sid = str(w.sessions["tok"].id)
        issued = await w.auth.step_up.record_pending(sid, action_class, fingerprint="a" * 64)
        answer = {"challenge_id": str(issued.challenge_id)}
    ok = w.step_up(**answer)
    assert ok.status_code == 200 and ok.json()["single_use"] is single_use
    (granted,) = w.of("auth.step_up_granted")
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


#: Classes the `authStepUp` contract declares before the service accepts them (C-6.1,
#: contract first). `flags` is E42-T03's (#964, contract in #2592): its service slice adds it
#: to `ACTION_CLASSES` and removes it from here.
_CONTRACT_AHEAD = frozenset({"flags"})


def test_contract_step_up_classes_match_the_service() -> None:
    """Contract first (C-6.1): the `authStepUp` enum is the service's classes plus pending ones."""
    op = cast(dict[str, Any], load_openapi_spec())["paths"]["/auth/step-up"]["post"]
    schema = op["requestBody"]["content"]["application/json"]["schema"]
    contract = set(schema["properties"]["action_class"]["enum"])
    assert contract == step_up_service.ACTION_CLASSES | _CONTRACT_AHEAD
    assert not _CONTRACT_AHEAD & step_up_service.ACTION_CLASSES  # a landed class leaves the list
