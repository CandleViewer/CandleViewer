"""The path guard challenges each profile write with `risk_caps` before its handler runs, and B16
records the refusal (E28-T02, #906; SR-E28-02, ruling B4).

This is the guard half of the threat model's owed `test_profile_write_without_step_up_is_403_and_
audited`: the four rows of `DANGEROUS_ROUTES` are what refuse, so a stand-in handler proves it
is never reached. The route's own half (the real handler, no row written) is the router slice's.
"""

from __future__ import annotations

from datetime import timedelta
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

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


def _stand_ins(c: TestClient) -> list[str]:
    """The seven contract operations as handlers with no gate; the list names those that ran."""
    app, reached = cast(FastAPI, c.app), []

    async def collection(aid: str) -> dict[str, bool]:
        reached.append("collection")
        return {"ok": True}

    async def item(aid: str, pid: str) -> dict[str, bool]:
        reached.append("item")
        return {"ok": True}

    async def binding(aid: str) -> dict[str, bool]:
        reached.append("binding")
        return {"ok": True}

    app.add_api_route("/exchange-accounts/{aid}/profiles", collection, methods=["GET", "POST"])
    app.add_api_route(
        "/exchange-accounts/{aid}/profiles/{pid}", item, methods=["GET", "PUT", "DELETE"]
    )
    app.add_api_route("/exchange-accounts/{aid}/default-profile", binding, methods=["GET", "PUT"])
    return reached


@pytest.mark.parametrize(("method", "path"), _WRITES)
async def test_a_profile_write_without_step_up_is_403_and_audited_before_the_handler(
    method: str, path: str
) -> None:
    c, em, *_ = await _build()
    reached = _stand_ins(c)
    r = c.request(method, path, headers=_H)
    assert r.status_code == 403 and r.json()["code"] == "step_up_required"
    assert r.json()["action_class"] == "risk_caps"
    (record,) = [call for call in em.calls if call["action"] == "auth.step_up_required"]
    assert record["outcome"] == AuditOutcome.DENIED and record["reason"] == "risk_caps"
    assert reached == []  # nothing ran, so nothing could have been written


async def test_one_risk_caps_step_up_admits_every_profile_write_inside_its_window() -> None:
    """`risk_caps` is a grace class: one code opens five minutes for the four writes, no more."""
    c, em, seed, clock, _ = await _build()
    reached = _stand_ins(c)
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


async def test_profile_reads_pass_the_guard_without_a_step_up() -> None:
    c, em, *_ = await _build()
    reached = _stand_ins(c)
    for method, path in _READS:
        assert c.request(method, path, headers=_H).status_code == 200, path
    assert len(reached) == len(_READS) and "auth.step_up_required" not in em.actions()


async def test_the_guard_challenges_an_unmounted_profile_write_before_the_404() -> None:
    """The rows are registered ahead of the mount: an un-elevated write is challenged, and an
    elevated one meets the 404 of a path nothing serves yet."""
    c, _em, seed, clock, _ = await _build()
    path = _WRITES[0][1]
    assert c.post(path, headers=_H).status_code == 403
    ok = c.post("/auth/step-up", headers=_H, json=_modal_body(_code(seed, clock)))
    assert ok.status_code == 200 and ok.json()["action_class"] == "risk_caps"
    assert c.post(path, headers=_H).status_code == 404
