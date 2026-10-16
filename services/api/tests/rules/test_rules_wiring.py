"""E35-S01 composition: `/rules` mounted in the real app, gated, fail-closed, step-up registered."""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.rules_crud import _from_error
from candleviewer.api.step_up import (
    AUDIT_UNAVAILABLE_TITLE,
    HANDLER_GATED_ROUTES,
    SESSION_READ_ONLY_TITLE,
    STEP_UP_REQUIRED_DETAIL,
    STEP_UP_REQUIRED_TITLE,
    readonly_problem,
)
from candleviewer.api.step_up_challenge import request_fingerprint
from candleviewer.app import create_app
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.errors import (
    SessionReadOnly,
    SessionRevoked,
    StepUpMismatch,
    StepUpRequired,
    UnknownActionClass,
)
from candleviewer.auth.step_up import CHALLENGE_WINDOW, StepUpChallenge
from candleviewer.rules.manager import RuleError


def test_app_gives_the_rules_resolver_the_emitter_of_its_mismatch_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live arm presented with another request's grant is audited before it is answered
    (C-2.9, `auth.step_up_mismatch`): the composition root wires the emitter that writes it."""
    from candleviewer.api.rules_actor import SessionRulesActorResolver
    from candleviewer.app import _LazyAuditEmitter

    emitters: list[object] = []

    class _Spy(SessionRulesActorResolver):
        def __init__(self, *args: Any) -> None:
            super().__init__(*args)
            emitters.append(self._emitter)

    monkeypatch.setattr("candleviewer.app.build_identity_provider", lambda _settings: object())
    monkeypatch.setattr("candleviewer.app.SessionRulesActorResolver", _Spy)
    create_app()
    assert [type(emitter) for emitter in emitters] == [_LazyAuditEmitter]


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
_READ_ONLY_EXTRA = {"title": SESSION_READ_ONLY_TITLE, "readonly_until": _UNTIL.isoformat()}
#: `PUT /rules/r1/mode` as the client sent it, and the fingerprint of the object it parses to.
_BODY = b'{"reason": null, "mode": "armed"}'
_HELD = request_fingerprint("PUT", b"/rules/r1/mode", {"mode": "armed", "reason": None})


class _BoundStepUp:
    """`StepUpService` holding a one-shot `live_enablement` grant bound to `bound`, or none."""

    def __init__(self, bound: str | None) -> None:
        self.bound = bound
        self.pending: list[str | None] = []
        self.issued = StepUpChallenge(uuid.uuid4(), "live_enablement", _UNTIL + CHALLENGE_WINDOW)

    async def consume_single_use(self, sid: str, cls: str, *, fingerprint: str) -> None:
        if self.bound is None:
            raise StepUpRequired(cls)
        if self.bound != fingerprint:
            raise StepUpMismatch(
                cls, user_id=_UID, challenge_id="c", bound=self.bound, refused=fingerprint
            )

    async def record_pending(
        self, sid: str, cls: str, *, fingerprint: str | None = None
    ) -> StepUpChallenge:
        self.pending.append(fingerprint)
        return self.issued


class _Audit:
    def __init__(self) -> None:
        self.actions: list[str] = []

    async def emit(self, action: str, **kwargs: object) -> None:
        self.actions.append(action)


async def _arm_consume(
    step_up: object, audit: object = None, body: bytes = _BODY
) -> Callable[[], Awaitable[bool]]:
    """`Actor.consume_step_up` of the real resolver for `PUT /rules/r1/mode` with `body`."""
    from types import SimpleNamespace

    from starlette.requests import Request

    from candleviewer.api.rules_actor import SessionRulesActorResolver

    class _Sessions:
        async def authenticate_access_token(self, token: str) -> object:
            return SimpleNamespace(user_id=_UID, id="s1")

    class _Identity:
        async def user(self, uid: str) -> dict[str, object]:
            return {"status": "active", "roles": ["manager"]}

        async def session_info(self, uid: str) -> dict[str, object]:
            return {"permissions": ["rules.arm.live"], "account_scope": []}

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "method": "PUT",
        "path": "/rules/r1/mode",
        "raw_path": b"/rules/r1/mode",
        "query_string": b"",
        "headers": [(b"authorization", b"Bearer t"), (b"content-type", b"application/json")],
    }
    resolver = SessionRulesActorResolver(lambda: _Sessions(), lambda: step_up, _Identity(), audit)
    actor = await resolver.resolve(Request(scope, receive))
    assert actor is not None and actor.consume_step_up is not None
    return actor.consume_step_up


async def test_actor_consume_arms_with_the_grant_bound_to_this_request() -> None:
    """The hard-coded `step_up_fresh=True` is safe only because `consume` is the real check:
    #2304, the one-shot grant is used only by the request it is bound to."""
    step_up, audit = _BoundStepUp(_HELD), _Audit()
    assert await (await _arm_consume(step_up, audit))() is True
    assert step_up.pending == [] and audit.actions == []


@pytest.mark.parametrize(
    ("bound", "audited"),
    [(None, []), ("0" * 64, ["auth.step_up_mismatch"])],
    ids=["no-grant", "bound-to-another-request"],
)
async def test_actor_consume_refusal_carries_the_challenge_issued_for_this_request(
    bound: str | None, audited: list[str]
) -> None:
    """A refusal is the challenge issued for this request (#2304), which a no-grace step-up
    must name; never a bare `step_up_required` that no client could answer."""
    step_up, audit = _BoundStepUp(bound), _Audit()
    consume = await _arm_consume(step_up, audit)
    with pytest.raises(RuleError) as refused:
        await consume()
    assert (refused.value.status, refused.value.code) == (403, "step_up_required")
    assert refused.value.message == STEP_UP_REQUIRED_DETAIL  # what every challenge states
    assert refused.value.extra == {
        "title": STEP_UP_REQUIRED_TITLE,
        "action_class": "live_enablement",
        "challenge_id": str(step_up.issued.challenge_id),
        "challenge_expires_at": step_up.issued.expires_at.isoformat(),
    }
    assert step_up.pending == [_HELD] and audit.actions == audited


async def test_actor_consume_of_a_body_that_cannot_be_bound_is_400_never_a_challenge() -> None:
    step_up = _BoundStepUp(_HELD)
    consume = await _arm_consume(step_up, _Audit(), b'{"mode": "armed", "reason": "\\ud800"}')
    with pytest.raises(RuleError) as refused:
        await consume()
    assert (refused.value.status, refused.value.code) == (400, "validation_failed")
    assert step_up.pending == []


@pytest.mark.parametrize(
    ("raised", "status", "code", "extra"),
    [
        (SessionReadOnly(_UNTIL), 403, "session_read_only", _READ_ONLY_EXTRA),
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


async def test_actor_consume_on_a_read_only_session_states_the_write_guards_wording() -> None:
    """One wording for `403 session_read_only`: the rules route states what the write guard
    (`make_read_only_guard`) states, title and detail, not a text of its own."""

    class _StepUp:
        async def consume_single_use(self, sid: str, cls: str, **bound: object) -> None:
            raise SessionReadOnly(_UNTIL)

    consume = await _arm_consume(_StepUp())
    with pytest.raises(RuleError) as refused:
        await consume()
    assert json.loads(bytes(_from_error(refused.value).body)) == json.loads(
        bytes(readonly_problem(SessionReadOnly(_UNTIL)).body)
    )


async def test_actor_consume_without_its_mismatch_record_is_503_never_a_challenge() -> None:
    """A grant bound to another request is refused only after `auth.step_up_mismatch` is written
    ahead (C-2.9): without it there is no challenge and no arming."""

    class _Down:
        async def emit(self, action: str, **kwargs: object) -> None:
            raise AuditUnavailable("WAL unwritable")

    step_up = _BoundStepUp("0" * 64)
    consume = await _arm_consume(step_up, _Down())
    with pytest.raises(RuleError) as refused:
        await consume()
    assert (refused.value.status, refused.value.code) == (503, "audit_unavailable")
    assert refused.value.extra == {"title": AUDIT_UNAVAILABLE_TITLE}
    assert step_up.pending == []


async def test_actor_consume_of_an_unregistered_class_is_a_defect_never_swallowed() -> None:
    """`UnknownActionClass` is a server defect (the route demands an unregistered class): it
    reaches the 500 handler as itself, never read as a refusal of the caller or a pass."""

    class _Unregistered(_BoundStepUp):
        async def record_pending(
            self, sid: str, cls: str, *, fingerprint: str | None = None
        ) -> StepUpChallenge:
            raise UnknownActionClass(cls)

    consume = await _arm_consume(_Unregistered(None), _Audit())
    with pytest.raises(UnknownActionClass):
        await consume()


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
        async def authenticate_access_token(self, token: str) -> object:
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
