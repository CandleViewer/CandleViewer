"""E49-S07: POST /settings/hotkey-audit appends a server-side audit record (C-2.9)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.hotkey_audit import make_hotkey_audit_router
from candleviewer.audit.errors import AuditError

UID = uuid.uuid4()
BODY = {
    "command_id": "dom.cancel_all",
    "before": "Ctrl+Shift+X",
    "after": "X",
    "acknowledged_unsafe": True,
}


@dataclass
class _P:
    permissions: frozenset[str]
    user_id: uuid.UUID = UID
    username: str = "alice"
    ip: str | None = "127.0.0.1"
    session_id: uuid.UUID | None = None
    request_id: uuid.UUID | None = None


class _Resolver:
    def __init__(self, perms: frozenset[str]) -> None:
        self.perms = perms

    async def resolve(self, request: Request) -> _P | None:
        if not request.headers.get("authorization"):
            return None
        return _P(self.perms)


class _Emitter:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail = fail

    async def emit(self, action: str, **kw: Any) -> None:
        if self.fail:
            raise AuditError("down")
        self.calls.append((action, kw))


def _client(emitter: Any, perms: frozenset[str] = frozenset({"settings:write"})) -> TestClient:
    app = FastAPI()
    app.include_router(make_hotkey_audit_router(emitter, _Resolver(perms)))
    return TestClient(app)


H = {"authorization": "Bearer t"}


def test_record_valid_appends_audit_row_attributed_to_principal() -> None:
    em = _Emitter()
    r = _client(em).post("/settings/hotkey-audit", json=BODY, headers=H)
    assert r.status_code == 204
    action, kw = em.calls[0]
    assert action == "hotkey.trading_binding_changed"
    assert kw["actor_user_id"] == UID and kw["object_id"] == "dom.cancel_all"
    assert kw["before_state"] == {"binding": "Ctrl+Shift+X"}
    assert kw["after_state"]["acknowledged_unsafe"] is True


def test_record_without_session_is_401_and_unaudited() -> None:
    em = _Emitter()
    assert _client(em).post("/settings/hotkey-audit", json=BODY).status_code == 401
    assert em.calls == []


def test_record_without_settings_write_is_403() -> None:
    em = _Emitter()
    c = _client(em, frozenset({"settings:read"}))
    assert c.post("/settings/hotkey-audit", json=BODY, headers=H).status_code == 403
    assert em.calls == []


def test_record_rejects_extra_and_bad_fields_with_422() -> None:
    c = _client(_Emitter())
    assert (
        c.post("/settings/hotkey-audit", json={**BODY, "actor": "x"}, headers=H).status_code == 422
    )
    bad = {**BODY, "command_id": "NOT VALID"}
    assert c.post("/settings/hotkey-audit", json=bad, headers=H).status_code == 422


@pytest.mark.parametrize("field", ["before", "after"])
def test_record_refuses_nul_in_a_binding_with_the_same_422_unaudited(field: str) -> None:
    em = _Emitter()
    r = _client(em).post("/settings/hotkey-audit", json={**BODY, field: "Ctrl+\x00"}, headers=H)
    assert r.status_code == 422
    assert r.json() == {
        "type": "about:blank",
        "title": "Unprocessable",
        "status": 422,
        "detail": "invalid hotkey audit payload",
    }
    assert em.calls == []


def test_record_audit_failure_is_503() -> None:
    assert (
        _client(_Emitter(fail=True))
        .post("/settings/hotkey-audit", json=BODY, headers=H)
        .status_code
        == 503
    )


def test_record_unwired_is_501() -> None:
    app = FastAPI()
    app.include_router(make_hotkey_audit_router(None, None))
    assert TestClient(app).post("/settings/hotkey-audit", json=BODY).status_code == 501
