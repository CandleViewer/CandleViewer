"""Each profile write demands `risk_caps` in its handler, and B16 records the challenge (E28-T02,
#906; SR-E28-02, ruling B4; #2304 slice 3c).

The path guard no longer gates these routes (a path row challenged before the handler's RBAC,
validation and lookups), so a stand-in with no gate is reached; a stand-in that gates as the real
handlers do, through `request_elevation` over the real step-up service, is challenged and audited.
The real handlers' order is `test_account_profile_writes_provider.py`'s.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, cast

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.step_up import demand_elevation, request_elevation
from candleviewer.api.step_up_challenge import ChallengeText
from candleviewer.audit.models import AuditOutcome
from tests.unit.api.test_step_up_router import _H, _build, _code, _modal_body

_WRITES = [
    ("POST", "/exchange-accounts/a1/profiles"),
    ("PUT", "/exchange-accounts/a1/profiles/p1"),
    ("DELETE", "/exchange-accounts/a1/profiles/p1"),
    ("PUT", "/exchange-accounts/a1/default-profile"),  # setAccountDefaultProfile (#906 0d)
]
_READS = [
    ("GET", "/exchange-accounts/a1/profiles"),
    ("GET", "/exchange-accounts/a1/profiles/p1"),
    ("GET", "/exchange-accounts/a1/default-profile"),
]


def _stand_ins(c: TestClient, *, gated: bool) -> list[str]:
    """The seven contract operations as handlers; a write demands `risk_caps` first when
    `gated`, as the real handlers do once a write is checked. The list names those that ran."""
    app, reached = cast(FastAPI, c.app), []
    gate = request_elevation(app.state.step_up_auth, "risk_caps") if gated else None

    async def ran(request: Request, kind: str) -> Any:
        if gated and request.method != "GET":
            text = ChallengeText(f"{request.method} {kind}")
            if (refused := await demand_elevation(gate, request, text)) is not None:
                return refused
        reached.append(kind)
        return {"ok": True}

    async def collection(aid: str, request: Request) -> Any:
        return await ran(request, "collection")

    async def item(aid: str, pid: str, request: Request) -> Any:
        return await ran(request, "item")

    async def binding(aid: str, request: Request) -> Any:
        return await ran(request, "binding")

    app.add_api_route("/exchange-accounts/{aid}/profiles", collection, methods=["GET", "POST"])
    app.add_api_route(
        "/exchange-accounts/{aid}/profiles/{pid}", item, methods=["GET", "PUT", "DELETE"]
    )
    app.add_api_route("/exchange-accounts/{aid}/default-profile", binding, methods=["GET", "PUT"])
    return reached


@pytest.mark.parametrize(("method", "path"), _WRITES)
async def test_the_path_guard_leaves_each_profile_write_to_its_handler(
    method: str, path: str
) -> None:
    c, em, *_ = await _build()
    reached = _stand_ins(c, gated=False)
    assert c.request(method, path, headers=_H).status_code == 200
    assert len(reached) == 1 and "auth.step_up_required" not in em.actions()


@pytest.mark.parametrize(("method", "path"), _WRITES)
async def test_a_profile_write_without_step_up_is_403_and_audited_by_its_handler(
    method: str, path: str
) -> None:
    c, em, *_ = await _build()
    reached = _stand_ins(c, gated=True)
    r = c.request(method, path, headers=_H)
    assert r.status_code == 403 and r.json()["code"] == "step_up_required"
    assert r.json()["action_class"] == "risk_caps"
    (record,) = [call for call in em.calls if call["action"] == "auth.step_up_required"]
    assert record["outcome"] == AuditOutcome.DENIED and record["reason"] == "risk_caps"
    assert reached == []  # nothing past the gate ran


async def test_one_risk_caps_step_up_admits_every_profile_write_inside_its_window() -> None:
    """`risk_caps` is a grace class: one code opens five minutes for the four writes, no more."""
    c, em, seed, clock, _ = await _build()
    reached = _stand_ins(c, gated=True)
    for method, path in _WRITES:
        assert c.request(method, path, headers=_H).status_code == 403, path
    ok = c.post("/auth/step-up", headers=_H, json=_modal_body(_code(seed, clock)))
    assert ok.status_code == 200 and ok.json()["action_class"] == "risk_caps"
    clock.now += timedelta(minutes=3)
    for method, path in _WRITES:
        assert c.request(method, path, headers=_H).status_code == 200, path
    assert len(reached) == len(_WRITES)
    clock.now += timedelta(minutes=3)
    assert c.post(_WRITES[0][1], headers=_H).status_code == 403
    assert "auth.step_up_granted" in em.actions()


async def test_profile_reads_pass_without_a_step_up() -> None:
    c, em, *_ = await _build()
    reached = _stand_ins(c, gated=True)
    for method, path in _READS:
        assert c.request(method, path, headers=_H).status_code == 200, path
    assert len(reached) == len(_READS) and "auth.step_up_required" not in em.actions()
