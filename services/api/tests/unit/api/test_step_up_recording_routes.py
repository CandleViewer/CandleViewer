"""#2738 (SR-025, 04 §7.2.2 rows 9 and 9a): every recording write demands `recorder` in its
handler, never the path guard (#2304 slice 3c moved the retention set and the pin off their path
rows): only the handler has the body, the caller's RBAC and the entry to decide on, and a plain
add needs no code.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.step_up import request_elevation
from candleviewer.api.step_up_challenge import ChallengeText
from tests.unit.api.test_step_up_router import _H, _PW, _build, _code


def _stand_in(c: TestClient, method: str, path: str, *, gated: bool = False) -> list[str]:
    """Mount a stand-in for a recording write behind the real guard; `gated`: it demands
    `recorder` itself first, as the retention set's and the pin's handlers do."""
    ran: list[str] = []
    gate = request_elevation(cast(FastAPI, c.app).state.step_up_auth, "recorder")

    async def handler(request: Request) -> Any:
        if gated and (refused := await gate(request, ChallengeText("Change retention"))):
            return refused
        ran.append(method)
        return {"ok": True}

    cast(FastAPI, c.app).add_api_route(path, handler, methods=[method])
    return ran


@pytest.mark.parametrize("path", ["/recording/retention-policies", "/recording/symbols/s1/pin"])
async def test_retention_change_needs_recorder_step_up_then_gets_a_grace_window(
    path: str,
) -> None:
    c, em, seed, clock, _ = await _build()
    ran = _stand_in(c, "PUT", path, gated=True)
    denied = c.put(path, headers=_H)
    assert denied.status_code == 403 and denied.json()["code"] == "step_up_required"
    assert denied.json()["action_class"] == "recorder" and not ran
    assert "auth.step_up_required" in em.actions()
    ok = c.post("/auth/step-up", headers=_H, json={"code": _code(seed, clock), "password": _PW})
    assert ok.status_code == 200 and ok.json()["action_class"] == "recorder"
    assert ok.json()["single_use"] is False
    for _ in range(2):  # a grace class: the window covers the next change too
        assert c.put(path, headers=_H).status_code == 200
    assert len(ran) == 2


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/recording/symbols"),
        ("PATCH", "/recording/symbols/s1"),
        ("DELETE", "/recording/symbols/s1"),
        ("PUT", "/recording/retention-policies"),
        ("PUT", "/recording/symbols/s1/pin"),
    ],
)
async def test_guard_leaves_recorded_symbol_writes_to_the_handler(method: str, path: str) -> None:
    c, em, *_ = await _build()
    ran = _stand_in(c, method, path)
    assert c.request(method, path, headers=_H).status_code == 200
    assert ran == [method] and "auth.step_up_required" not in em.actions()
