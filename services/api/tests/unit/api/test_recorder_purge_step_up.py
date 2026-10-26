"""E16-T06 (#490): a purge of recorded data needs a fresh step-up of its own class.

`recorder_purge` is a no-grace class: a `recorder` grace window (opened by a pin or a retention
change) never authorises a purge, each purge spends one fresh code bound to the exact request
(method, path and body), and the write-ahead `retention.purge` record names the `challenge_id` of
the grant it spent. Over the real `StepUpService`, with the purge router mounted next to
`POST /auth/step-up`.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from candleviewer.api.recorder_admin import AdminJobStore
from candleviewer.api.recorder_purge import make_recorder_purge_router
from candleviewer.api.step_up import SpentGrant, require_bound_elevation
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth import step_up as step_up_service
from candleviewer.statechart.bindings import b16_session
from tests.unit.api._purge_anchors import InMemoryPurgeAnchors
from tests.unit.api.test_recorder_purge import BODY, OWNER, _Gated
from tests.unit.api.test_step_up_challenge_router import _World, _world
from tests.unit.recorder._retention_fakes import NOW, T, World, manager

_PATH = "/admin/recorder/purge"


class _Purge:
    """The purge router on the step-up world's app: the owner's session `tok`, a real
    retention manager over the fake tiers, and an in-memory anchor store."""

    def __init__(self, w: _World) -> None:
        self.w, self.tiers = w, World()
        self.tiers.add_cold("BTCUSDT", T, 2)
        self.backend = _Gated(manager(self.tiers))
        session = w.sessions["tok"]
        principal = AuditPrincipal(
            session.user_id, "o", frozenset(OWNER), session.id, request_id=uuid.uuid4(),
            is_owner=True,
        )  # fmt: skip

        class _Resolver:
            async def resolve(self, request: Any) -> AuditPrincipal:
                return principal

        async def elevation(
            request: Request, action_class: str, fingerprint: str
        ) -> JSONResponse | SpentGrant:
            return await require_bound_elevation(
                w.auth, session.id, action_class, fingerprint=fingerprint, emitter=w.audit
            )

        router = make_recorder_purge_router(
            AdminJobStore(), self.backend, w.audit, _Resolver(), elevation,
            anchors=InMemoryPurgeAnchors(), clock=lambda: NOW,
        )  # fmt: skip
        cast(FastAPI, w.client.app).include_router(router)

    def post(self, body: dict[str, Any], key: str | None = None) -> Any:
        headers = {**self.w.h(), "Idempotency-Key": key or str(uuid.uuid4())}
        return self.w.client.post(_PATH, headers=headers, json=body)

    def intents(self) -> list[dict[str, Any]]:
        return [
            c for c in self.w.of("retention.purge") if "before_state" in c and "outcome" not in c
        ]


def test_recorder_purge_is_a_no_grace_class_in_the_service_and_the_b16_mirror() -> None:
    for module in (step_up_service, b16_session):
        assert "recorder_purge" in module.ACTION_CLASSES
        assert "recorder_purge" in module.NO_GRACE_ACTION_CLASSES
        assert "recorder" not in module.NO_GRACE_ACTION_CLASSES  # retention writes keep grace


async def test_purge_with_only_a_recorder_grace_window_is_refused_with_recorder_purge() -> None:
    w = await _world()
    p = _Purge(w)
    grace = w.step_up(action_class="recorder")  # as a pin or a retention change opens it
    assert grace.status_code == 200 and grace.json()["single_use"] is False
    refused = p.post(BODY)
    assert refused.status_code == 403 and refused.json()["code"] == "step_up_required"
    assert refused.json()["action_class"] == "recorder_purge"
    assert p.backend.plans == 0 and p.tiers.deletes == [] and p.intents() == []


async def test_one_fresh_code_authorises_exactly_one_purge() -> None:
    w = await _world()
    p = _Purge(w)
    challenge = p.post(BODY).json()["challenge_id"]
    granted = w.step_up(challenge_id=challenge)
    assert granted.status_code == 200 and granted.json()["single_use"] is True
    assert p.post(BODY).status_code == 202
    again = p.post(BODY)  # a second purge (another key) finds the code spent
    assert again.status_code == 403 and again.json()["action_class"] == "recorder_purge"
    assert p.backend.plans == 1 and len(p.intents()) == 1


async def test_a_grant_never_authorises_a_purge_with_another_body() -> None:
    w = await _world()
    p = _Purge(w)
    challenge = p.post(BODY).json()["challenge_id"]
    assert w.step_up(challenge_id=challenge).status_code == 200
    other = p.post(BODY | {"reason": "another purge"})
    assert other.status_code == 403 and other.json()["challenge_id"] != challenge
    assert len(w.of("auth.step_up_mismatch")) == 1 and p.backend.plans == 0
    assert p.post(BODY).status_code == 202  # the grant stayed bound to the request it was for


async def test_the_write_ahead_record_names_the_challenge_id_it_spent() -> None:
    w = await _world()
    p = _Purge(w)
    challenge = p.post(BODY).json()["challenge_id"]
    assert w.step_up(challenge_id=challenge).status_code == 200
    accepted = p.post(BODY)
    assert accepted.status_code == 202
    (intent,) = p.intents()
    assert intent["before_state"]["challenge_id"] == challenge
    assert intent["object_id"] == accepted.json()["job_id"]
