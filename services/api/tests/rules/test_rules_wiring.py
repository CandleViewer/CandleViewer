"""E35-S01 composition: `/rules` mounted in the real app, gated, fail-closed, step-up registered."""

from __future__ import annotations

import pytest

from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.step_up import HANDLER_GATED_ROUTES
from candleviewer.app import create_app


def test_rules_routes_mounted_and_declared_in_openapi() -> None:
    app = create_app()  # asserts every served route has an x-rbac declaration
    paths = served_operations(app)
    for op in [
        ("GET", "/rules"), ("POST", "/rules"), ("GET", "/rules/{ruleId}"),
        ("PUT", "/rules/{ruleId}"), ("DELETE", "/rules/{ruleId}"),
        ("GET", "/rules/{ruleId}/versions"), ("GET", "/rules/{ruleId}/versions/{versionId}"),
        ("PUT", "/rules/{ruleId}/active-version"), ("PUT", "/rules/{ruleId}/mode"),
    ]:  # fmt: skip
        assert op in paths, op


def test_live_arm_route_is_registered_as_step_up_gated() -> None:
    assert ("PUT", "/rules/{ruleId}/mode", "live_enablement") in HANDLER_GATED_ROUTES


def test_rules_fail_closed_without_identity() -> None:
    from fastapi.testclient import TestClient

    r = TestClient(create_app(), client=("127.0.0.1", 50000)).get("/rules")
    assert r.status_code in (401, 501)


def test_create_app_binds_postgres_rule_store_not_in_memory() -> None:
    from candleviewer.rules_store_pg import PostgresRuleStore

    app = create_app()
    assert isinstance(app.state.app_context.rules._store, PostgresRuleStore)


_UID = "00000000-0000-4000-8000-000000000001"


@pytest.mark.parametrize("revoked", [False, True], ids=["live", "revoked-meanwhile"])
async def test_actor_consume_refuses_without_fresh_step_up(revoked: bool) -> None:
    """The hard-coded `step_up_fresh=True` is safe only because `consume` is the real check.
    #2304: a session revoked before its challenge is issued is refused all the same."""
    from types import SimpleNamespace

    from starlette.requests import Request

    from candleviewer.api.rules_actor import SessionRulesActorResolver
    from candleviewer.auth.errors import SessionRevoked, StepUpRequired

    class _Sessions:
        async def authenticate_access_token(self, token: str, touch: bool = True) -> object:
            return SimpleNamespace(user_id=_UID, id="s1")

    class _Identity:
        async def user(self, uid: str) -> dict[str, object]:
            return {"status": "active", "roles": ["manager"]}

        async def session_info(self, uid: str) -> dict[str, object]:
            return {"permissions": ["rules.arm.live"], "account_scope": []}

    pending: list[str] = []

    class _StepUp:
        async def consume_single_use(self, sid: str, cls: str) -> None:
            raise StepUpRequired("no fresh step-up")

        async def record_pending(self, sid: str, cls: str) -> None:
            if revoked:
                raise SessionRevoked("step_up")
            pending.append(sid)

    req = Request({"type": "http", "headers": [(b"authorization", b"Bearer t")]})
    actor = await SessionRulesActorResolver(
        lambda: _Sessions(), lambda: _StepUp(), _Identity()
    ).resolve(req)
    assert actor is not None and actor.consume_step_up is not None
    assert await actor.consume_step_up() is False
    assert pending == ([] if revoked else ["s1"])


async def test_service_sink_records_simulation_for_simulating_rule() -> None:
    import asyncio

    from candleviewer.rules.evaluator.engine import EvaluationResult
    from candleviewer.rules.manager import Actor
    from candleviewer.rules.service import RulesService

    svc = RulesService()
    await svc.start(None)  # type: ignore[arg-type]
    m = svc.manager()
    assert m is not None
    owner = Actor("u1", "s1", frozenset({"rules:arm_live"}), is_owner=True, step_up_fresh=True)
    import json
    from pathlib import Path

    raw = json.loads(
        (Path(__file__).parents[1] / "fixtures/rule_ir/form_simple_0.json").read_text("utf-8"),
        parse_float=str,
    )
    raw["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x"}
    rid = (await m.create(raw, owner))["id"]
    await m.set_mode(rid, "simulate", owner, "k1")
    sink = svc.evaluation_sink()
    for i in range(5):
        sink(EvaluationResult(rid, 1, "BTCUSDT@*", "tick", i, True, None))
    await asyncio.gather(*svc._tasks)
    assert (await m.set_mode(rid, "armed", owner, "k2"))["mode"] == "armed"
    await svc.stop(1.0)


def _resolver(roles: list[str]) -> object:
    from types import SimpleNamespace

    from candleviewer.api.rules_actor import SessionRulesActorResolver

    class _Sessions:
        async def authenticate_access_token(self, token: str, touch: bool = True) -> object:
            return SimpleNamespace(user_id=_UID, id="s1")

    class _Identity:
        async def user(self, uid: str) -> dict[str, object]:
            return {"status": "active", "roles": roles}

        async def session_info(self, uid: str) -> dict[str, object]:
            return {"permissions": [], "account_scope": []}

    return SessionRulesActorResolver(lambda: _Sessions(), lambda: object(), _Identity())


async def _resolve(roles: list[str]) -> object:
    from starlette.requests import Request

    req = Request({"type": "http", "headers": [(b"authorization", b"Bearer t")]})
    return await _resolver(roles).resolve(req)  # type: ignore[attr-defined]  # test helper


async def test_actor_owner_role_sets_is_owner() -> None:
    actor = await _resolve(["owner"])
    assert actor is not None and actor.is_owner is True  # type: ignore[attr-defined]


async def test_actor_non_owner_roles_not_owner() -> None:
    for roles in (["manager"], ["viewer"], []):
        actor = await _resolve(roles)
        assert actor is not None and actor.is_owner is False  # type: ignore[attr-defined]


async def test_actor_unknown_role_fails_closed() -> None:
    assert await _resolve(["owner", "superadmin"]) is None
    assert await _resolve(["Owner"]) is None
