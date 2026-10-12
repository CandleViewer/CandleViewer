"""E04-T06: `create_app()` wiring of `/telemetry/frontend` (fail-closed vs authenticated)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from candleviewer import app as app_module
from candleviewer.app import create_app
from candleviewer.auth.errors import SessionNotFound
from tests.csrf_helpers import arm_csrf

PATH = "/telemetry/frontend"
_BODY = {
    "screen": "R-100",
    "engine_version": "0.1.0",
    "fe_frame_time_ms": {"counts": [1, 0, 0, 0, 0, 0, 0, 0, 0]},
    "fe_ws_decode_ms": {"counts": [1, 0, 0, 0, 0, 0, 0, 0, 0]},
    "fe_dropped_frames_total": 0,
    "fe_gpu_memory_mb": 1.0,
}


_SID = uuid.uuid4()


class _Sessions:
    async def authenticate_access_token(self, token: str, **_kw: Any) -> Any:
        if token != "good":  # noqa: S105 - test token
            raise SessionNotFound("nope")
        return SimpleNamespace(id=_SID, user_id=_SID)


class _Identity:
    async def user(self, user_id: str) -> dict[str, Any]:
        return {"username": "u", "status": "active"}

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": ["*"]}


def test_fake_backend_fails_closed_501() -> None:
    app = create_app()
    c = arm_csrf(TestClient(app, client=("127.0.0.1", 50000)), app.state.csrf_codec)
    assert c.post(PATH, json=_BODY, headers={"Authorization": "Bearer good"}).status_code == 501


def test_authenticated_session_gets_204_and_series_recorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "build_identity_provider", lambda _s: _Identity())
    app = create_app()
    app.state.app_context.auth._sessions = _Sessions()
    c = arm_csrf(TestClient(app, client=("127.0.0.1", 50000)), app.state.csrf_codec, _SID)
    assert c.post(PATH, json=_BODY).status_code == 401
    r = c.post(PATH, json=_BODY, headers={"Authorization": "Bearer good"})
    assert r.status_code == 204
    reg = app.state.metrics_facade.registry
    count = reg.get_sample_value("fe_frame_time_ms_count", {"env": "demo", "screen": "R-100"})
    assert count == 1
