"""E35-S01 composition: `/rules` mounted in the real app, gated, fail-closed, step-up registered."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest

from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.step_up import HANDLER_GATED_ROUTES
from candleviewer.app import create_app
from candleviewer.auth.errors import SessionReadOnly, SessionRevoked
from candleviewer.rules.manager import RuleError


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


_UNTIL = datetime(2026, 9, 30, 12, 5, tzinfo=UTC)


async def _arm_consume(step_up: object) -> Callable[[], Awaitable[bool]]:
    """`Actor.consume_step_up` of the real resolver for `PUT /rules/r1/mode {"mode": "armed"}`."""
    from types import SimpleNamespace

    from starlette.requests import Request

    from candleviewer.api.rules_actor import SessionRulesActorResolver

    class _Sessions:
        async def authenticate_access_token(self, token: str, touch: bool = True) -> object:
            return SimpleNamespace(user_id=_UID, id="s1")

    class _Identity:
        async def user(self, uid: str) -> dict[str, object]:
            return {"status": "active", "roles": ["manager"]}

        async def session_info(self, uid: str) -> dict[str, object]:
            return {"permissions": ["rules.arm.live"], "account_scope": []}

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b'{"mode": "armed"}', "more_body": False}

    scope = {
        "type": "http",
        "method": "PUT",
        "path": "/rules/r1/mode",
        "raw_path": b"/rules/r1/mode",
        "query_string": b"",
        "headers": [(b"authorization", b"Bearer t"), (b"content-type", b"application/json")],
    }
    resolver = SessionRulesActorResolver(lambda: _Sessions(), lambda: step_up, _Identity())
    actor = await resolver.resolve(Request(scope, receive))
    assert actor is not None and actor.consume_step_up is not None
    return actor.consume_step_up


async def test_actor_consume_refusal_carries_the_challenge_it_issued() -> None:
    """The hard-coded `step_up_fresh=True` is safe only because `consume` is the real check. Its
    refusal carries the challenge it issued (#2304), which a no-grace step-up must name."""
    from candleviewer.auth.errors import StepUpRequired
    from candleviewer.auth.step_up import CHALLENGE_WINDOW, StepUpChallenge

    issued = StepUpChallenge(uuid.uuid4(), "live_enablement", _UNTIL + CHALLENGE_WINDOW)
    pending: list[str] = []

    class _StepUp:
        async def consume_single_use(self, sid: str, cls: str) -> None:
            raise StepUpRequired(cls)

        async def record_pending(self, sid: str, cls: str) -> StepUpChallenge:
            pending.append(sid)
            return issued

    consume = await _arm_consume(_StepUp())
    with pytest.raises(RuleError) as refused:
        await consume()
    assert (refused.value.status, refused.value.code) == (403, "step_up_required")
    assert refused.value.extra == {
        "action_class": "live_enablement",
        "challenge_id": str(issued.challenge_id),
        "challenge_expires_at": issued.expires_at.isoformat(),
    }
    assert pending == ["s1"]


@pytest.mark.parametrize(
    ("raised", "status", "code", "extra"),
    [
        (SessionReadOnly(_UNTIL), 403, "session_read_only", {"readonly_until": _UNTIL.isoformat()}),
        (SessionRevoked("logout"), 401, "unauthorized", {}),
    ],
    ids=["read-only", "revoked"],
)
async def test_actor_consume_on_a_session_that_cannot_answer_is_never_a_challenge(
    raised: Exception, status: int, code: str, extra: dict[str, str]
) -> None:
    class _StepUp:
        async def consume_single_use(self, sid: str, cls: str, **bound: object) -> None:
            raise raised

    consume = await _arm_consume(_StepUp())
    with pytest.raises(RuleError) as refused:
        await consume()
    assert (refused.value.status, refused.value.code, refused.value.extra) == (status, code, extra)


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
