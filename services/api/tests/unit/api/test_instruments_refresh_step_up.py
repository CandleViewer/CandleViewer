"""`refreshInstruments` demands the `instruments` step-up over the real step-up service (E08-T10,
#5111; 04 §7.2.2 row 5a, SR-025; the orchestrator's ruling of 2026-10-31).

The route is mounted on the step-up router's test app with the gate the deployed app wires
(`request_elevation(auth, REFRESH_STEP_UP_CLASS)`): without an elevation the Owner gets `403
step_up_required` with `action_class: instruments`, audited by B16 and with nothing started; one
step-up of that class admits the refresh, and `instruments` is a grace class.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.instruments import REFRESH_STEP_UP_CLASS, make_instruments_refresh_router
from candleviewer.api.recorder_admin import AdminJobStore
from candleviewer.api.step_up import request_elevation
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome
from candleviewer.auth.step_up import ACTION_CLASSES, NO_GRACE_ACTION_CLASSES
from tests.unit.api.test_step_up_router import _H, _build, _code, _modal_body


class _Owner:
    async def resolve(self, request: Request) -> AuditPrincipal:
        return AuditPrincipal(uuid.uuid4(), "owner", frozenset({"*"}), is_owner=True)


class _Audit:
    def __init__(self) -> None:
        self.actions: list[str] = []

    async def emit(self, action: str, **_kw: Any) -> None:
        self.actions.append(action)


class _Refresher:
    stopped = False

    def __init__(self) -> None:
        self.calls = 0

    async def refresh_now(self) -> None:
        self.calls += 1


def _mount(c: TestClient) -> tuple[AdminJobStore, _Audit]:
    app = cast(FastAPI, c.app)
    jobs, audit, refresher = AdminJobStore(), _Audit(), _Refresher()
    app.include_router(
        make_instruments_refresh_router(
            lambda: refresher,
            jobs,
            audit=audit,
            environment="demo",
            principal_resolver=_Owner(),
            elevation=request_elevation(app.state.step_up_auth, REFRESH_STEP_UP_CLASS),
        )
    )
    return jobs, audit


def test_instruments_is_a_registered_grace_class() -> None:
    assert REFRESH_STEP_UP_CLASS in ACTION_CLASSES
    assert REFRESH_STEP_UP_CLASS not in NO_GRACE_ACTION_CLASSES


async def test_refresh_without_elevation_is_403_step_up_required_and_audited() -> None:
    c, em, *_ = await _build()
    jobs, audit = _mount(c)
    r = c.post("/instruments/refresh", headers=_H)
    assert r.status_code == 403
    body = r.json()
    assert (body["code"], body["action_class"]) == ("step_up_required", "instruments")
    assert body["action_summary"] == "Refresh the demo instrument catalogue from the exchange"
    (record,) = [call for call in em.calls if call["action"] == "auth.step_up_required"]
    assert record["outcome"] == AuditOutcome.DENIED and record["reason"] == "instruments"
    assert jobs.held() == 0 and audit.actions == []


async def test_one_instruments_step_up_admits_the_refresh_inside_its_window() -> None:
    c, em, seed, clock, _ = await _build()
    jobs, audit = _mount(c)
    denied = c.post("/instruments/refresh", headers=_H)
    ok = c.post("/auth/step-up", headers=_H, json=_modal_body(_code(seed, clock), denied))
    assert ok.status_code == 200 and ok.json()["action_class"] == "instruments"
    assert ok.json()["single_use"] is False  # a grace class
    clock.now += timedelta(minutes=3)
    r = c.post("/instruments/refresh", headers=_H)
    assert r.status_code == 202 and jobs.get(r.json()["job_id"]) is not None
    assert audit.actions[0] == "instruments.refresh.requested"
    assert "auth.step_up_granted" in em.actions()
