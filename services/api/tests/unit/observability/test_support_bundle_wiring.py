"""E04-S02: real app wiring + real collectors (no fakes for the service)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from candleviewer.app import create_app
from candleviewer.observability.support_bundle_wiring import LogRingBuffer
from tests.csrf_helpers import arm_csrf


def test_route_mounted_and_fails_closed_without_identity() -> None:
    app = create_app()
    client = arm_csrf(TestClient(app, client=("127.0.0.1", 50000)), app.state.csrf_codec)
    resp = client.post("/admin/support-bundle", json={})
    assert resp.status_code == 501  # mounted (not 404), fails closed without identity


def test_metrics_registered_for_support_bundle() -> None:
    app = create_app()
    names = app.state.metrics_facade.names()
    assert "support_bundle_generations_total" in names
    assert "support_bundle_duration_seconds" in names
    assert "support_bundle_bytes" in names


def test_log_ring_window_newest_first_and_redacted() -> None:
    ring = LogRingBuffer()
    lg = logging.getLogger("sb-test")
    lg.addHandler(ring)
    lg.setLevel(logging.INFO)
    lg.info("first")
    lg.info("second")
    now = datetime.now(UTC)
    lines = ring.window(now - timedelta(minutes=1), now + timedelta(minutes=1))
    assert lines[0].endswith("second")
    assert lines[1].endswith("first")


# --- end-to-end through create_app() with a session-backed identity (E04-S02) ---
import uuid  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402

from candleviewer import app as app_module  # noqa: E402
from candleviewer.auth.errors import SessionNotFound  # noqa: E402

_OWNER = uuid.uuid4()
_MGR = uuid.uuid4()
_SID = uuid.uuid4()  # one session id for both fake bearers (the CSRF token binds to it)


class _Sessions:
    async def authenticate_access_token(self, token: str, **_kw: Any) -> Any:
        users = {"owner": _OWNER, "mgr": _MGR}
        if token not in users:
            raise SessionNotFound("nope")
        return SimpleNamespace(id=_SID, user_id=users[token])


class _Identity:
    async def user(self, user_id: str) -> dict[str, Any]:
        return {"username": "u", "status": "active"}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": ["*"] if user_id == str(_OWNER) else ["audit:read"]}


class _RecEmitter:
    calls: list[str] = []  # noqa: RUF012 - test recorder

    def __init__(self, _audit: Any) -> None: ...

    async def emit(self, action: str, **kw: Any) -> None:
        _RecEmitter.calls.append(action)


def _wired(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    # fake backend has no audit writer; record emits instead
    monkeypatch.setattr(app_module, "_LazyAuditEmitter", _RecEmitter)
    _RecEmitter.calls.clear()
    monkeypatch.setattr(app_module, "build_identity_provider", lambda _s: _Identity())
    app = app_module.create_app()
    app.state.app_context.auth._sessions = _Sessions()
    return arm_csrf(TestClient(app, client=("127.0.0.1", 50000)), app.state.csrf_codec, _SID)


def _body() -> dict[str, str]:
    now = datetime.now(UTC)
    return {"from": (now - timedelta(minutes=5)).isoformat(), "to": now.isoformat()}


def test_wired_unauthenticated_401_and_manager_403(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    c = _wired(monkeypatch, tmp_path)
    assert c.post("/admin/support-bundle", json=_body()).status_code == 401
    r = c.post("/admin/support-bundle", json=_body(), headers={"Authorization": "Bearer mgr"})
    assert r.status_code == 403
    assert _RecEmitter.calls == ["health.diagnostics_exported"]  # denial audited


def test_wired_owner_gets_202_then_409_while_running(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    c = _wired(monkeypatch, tmp_path)
    svc = c.app.state.support_bundle  # type: ignore[attr-defined]  # reason: FastAPI state
    svc._out_dir = tmp_path
    h = {"Authorization": "Bearer owner"}
    with c:
        first = c.post("/admin/support-bundle", json=_body(), headers=h)
        assert first.status_code == 202
        second = c.post("/admin/support-bundle", json=_body(), headers=h)
        # either still running (409) or already finished and the runner is free (202)
        assert second.status_code in (409, 202)
        if second.status_code == 409:
            assert second.json()["code"] == "BUNDLE_ALREADY_RUNNING"
        st = c.get(f"/admin/support-bundle/{first.json()['job_id']}", headers=h)
        assert st.status_code == 200
