"""AD-F24 (#2304, E42-X01 threat model §12.3): every `401` of the step-up router is the
registry's `unauthenticated` (`x-error-codes`), never an uncatalogued `unauthorized`: a bearer
missing from `POST /auth/step-up`, one no session accepts, and a principal that is not the
session's subject on the owner TOTP reset routes."""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.step_up import make_step_up_router
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from tests.unit.api.test_step_up_challenge_router import _assert_unauthenticated, _world
from tests.unit.api.test_step_up_router import _PW, _build, _Positions, _Resolver, _Users


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer no-such-token"}],
    ids=["no-bearer", "unknown-bearer"],
)
async def test_step_up_without_a_session_is_401_unauthenticated(headers: dict[str, str]) -> None:
    client, emitter, *_ = await _build()
    body = {"code": "123456", "password": _PW, "action_class": "keys"}
    r = client.post("/auth/step-up", headers=headers, json=body)
    assert r.status_code == 401
    _assert_unauthenticated(r.json())
    assert emitter.calls == []  # refused before any factor or challenge


@pytest.mark.parametrize(
    ("method", "suffix"),
    [("GET", "reset-preview"), ("POST", "reset")],
)
async def test_reset_route_whose_principal_is_not_the_session_subject_is_401_unauthenticated(
    method: str, suffix: str
) -> None:
    w = await _world()
    stranger = PrincipalSnapshot(
        user_id=uuid.uuid4(),  # not the user whose session the bearer names
        roles=frozenset({"owner"}),
        permissions=frozenset({Permission.USERS_WRITE}),
    )
    app = FastAPI()
    app.include_router(
        make_step_up_router(
            w.auth,
            w.audit,
            principal_resolver=_Resolver(stranger),
            positions=_Positions(),
            users=_Users(),
            audit_ready=lambda: True,
        )
    )
    r = TestClient(app).request(method, f"/users/{uuid.uuid4()}/mfa/{suffix}", headers=w.h())
    assert r.status_code == 401
    _assert_unauthenticated(r.json())
    assert not w.of("auth.mfa_reset_by_owner")
