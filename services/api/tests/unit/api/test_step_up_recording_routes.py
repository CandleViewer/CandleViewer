"""#2738 (SR-025, 04 §7.2.2 rows 9 and 9a): the guard demands `recorder` step-up on the
retention routes it gates by path, before E16-T08 (#492) mounts them, and leaves the
recorded-symbol add, PATCH and DELETE to their handler: only the body or query tells whether
one changes retention or deletes data, and a plain add needs no code.
"""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.unit.api.test_step_up_router import _H, _PW, _build, _code


def _stand_in(c: TestClient, method: str, path: str) -> list[str]:
    """Mount a stand-in for a route E16-T08 has not mounted yet, behind the real guard."""
    ran: list[str] = []

    async def handler() -> dict[str, bool]:
        ran.append(method)
        return {"ok": True}

    cast(FastAPI, c.app).add_api_route(path, handler, methods=[method])
    return ran


@pytest.mark.parametrize("path", ["/recording/retention-policies", "/recording/symbols/s1/pin"])
async def test_retention_change_needs_recorder_step_up_then_gets_a_grace_window(
    path: str,
) -> None:
    c, em, seed, clock, _ = await _build()
    ran = _stand_in(c, "PUT", path)
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
    ],
)
async def test_guard_leaves_recorded_symbol_writes_to_the_handler(method: str, path: str) -> None:
    c, em, *_ = await _build()
    ran = _stand_in(c, method, path)
    assert c.request(method, path, headers=_H).status_code == 200
    assert ran == [method] and "auth.step_up_required" not in em.actions()
