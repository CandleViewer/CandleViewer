"""#2304 on `PUT /rules/{ruleId}/mode`, the only mounted no-grace route, end to end with the
real `StepUpService`, `SessionRulesActorResolver` and rules router: the refusal is a challenge
the client answers by id, and the held request, re-sent unchanged with its `Idempotency-Key`,
arms the rule once; the grant it earned arms nothing else. Harness:
`test_step_up_challenge_router._world`."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import FastAPI

from candleviewer.api.rules_actor import SessionRulesActorResolver
from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.auth.models import SessionRecord
from candleviewer.rules.manager import InMemoryRuleStore, RulesManager
from candleviewer.rules.vocabulary import default_registry
from tests.contract.test_step_up_challenge_contract import _SPEC, _STEP_UP_REQUIRED_BODY, _validator
from tests.rules.test_rules_routes import LIVE, _ir
from tests.unit.api.test_step_up_challenge_router import _RELEASE, _World, _world
from tests.unit.api.test_step_up_router import _Sessions

_ARM = {"mode": "armed"}


class _Identity:
    async def user(self, uid: str) -> dict[str, object]:
        return {"status": "active", "roles": ["owner"]}

    async def session_info(self, uid: str) -> dict[str, object]:
        return {"permissions": ["rules:read", "rules:write", "rules:arm_live"], "account_scope": []}


class _TouchingSessions(_Sessions):
    """The resolver authenticates with `touch=True`; the harness sessions keep no idle clock."""

    async def authenticate_access_token(self, token: str, touch: bool = False) -> SessionRecord:
        return await super().authenticate_access_token(token)


async def _armable(w: _World, count: int = 1) -> tuple[list[str], list[str]]:
    """Mount `/rules` on the harness app and create `count` live-scoped rules, simulated and
    ready to arm. Returns their ids and the rules audit trail."""
    trail: list[str] = []

    async def audit(action: str, payload: dict[str, Any]) -> None:
        trail.append(action)

    async def broadcast(payload: dict[str, Any]) -> None:
        return None

    mgr = RulesManager(InMemoryRuleStore(), default_registry(), audit=audit, broadcast=broadcast)
    resolver = SessionRulesActorResolver(
        lambda: _TouchingSessions(w.sessions), lambda: w.auth.step_up, _Identity(), w.audit
    )
    app = w.client.app
    assert isinstance(app, FastAPI)  # the harness app, not yet serving: routes may be added
    app.include_router(make_rules_crud_router(lambda: mgr, resolver.resolve))
    ids = []
    for n in range(count):
        made = w.client.post("/rules", headers=w.h(), json={"ir": _ir(scope=LIVE, name=f"r{n}")})
        rid = str(made.json()["id"])
        simulate = w.h() | {"Idempotency-Key": f"simulate-{rid}"}
        ready = w.client.put(f"/rules/{rid}/mode", headers=simulate, json={"mode": "simulate"})
        assert ready.status_code == 200, ready.text
        versions = w.client.get(f"/rules/{rid}/versions", headers=w.h()).json()
        await mgr.record_simulation(rid, versions["items"][0]["ir_hash"], 5, 0.0)
        ids.append(rid)
    return ids, trail


async def test_rules_refusal_is_a_challenge_answered_by_id_and_the_held_request_arms_once() -> None:
    w = await _world()
    (rid,), trail = await _armable(w)
    denied = w.client.put(f"/rules/{rid}/mode", headers=w.h(), json=_ARM)
    assert denied.status_code == 403
    body = denied.json()
    _validator(_SPEC, _STEP_UP_REQUIRED_BODY).validate(body)  # provider side (C-6.2)
    assert body["action_class"] == "live_enablement"
    assert uuid.UUID(body["challenge_id"]).version == 4
    expires = datetime.fromisoformat(body["challenge_expires_at"])
    assert expires == w.clock.now + timedelta(minutes=5)
    (required,) = w.of("auth.step_up_required")
    assert required["object_id"] == body["challenge_id"]
    granted = w.step_up(challenge_id=body["challenge_id"])
    assert granted.status_code == 200 and granted.json()["single_use"] is True
    for _ in range(2):  # the held request, then a retry of it: the rule is armed once
        resent = w.client.put(f"/rules/{rid}/mode", headers=w.h(), json=_ARM)
        assert resent.status_code == 200 and resent.json()["mode"] == "armed"
    assert trail.count("rule.armed") == 1


async def test_rules_refusal_states_the_step_up_text_every_challenge_states() -> None:
    """#2304 rule 4: the dialog shows the server's text verbatim, so the rules refusal asks for
    what the step-up takes (password and code, #1778) in the words and under the contract title
    of every other challenge. Before, it asked for the authenticator code alone."""
    w = await _world()
    (rid,), _ = await _armable(w)
    rules = w.client.put(f"/rules/{rid}/mode", headers=w.h(), json=_ARM)
    killswitch = w.send(_RELEASE)  # the harness's no-grace refusal: `required_problem`
    assert rules.status_code == killswitch.status_code == 403
    _validator(_SPEC, _STEP_UP_REQUIRED_BODY).validate(rules.json())
    stated = ("title", "detail")
    assert {k: rules.json()[k] for k in stated} == {k: killswitch.json()[k] for k in stated}


async def test_rules_grant_bound_to_one_rule_refuses_to_arm_another() -> None:
    """AC "Bound single-use grant refuses a swapped payload" on the rules route: before #2304 any
    live arm used the session's grant, whichever rule the challenge restated."""
    w = await _world()
    (held, other), trail = await _armable(w, count=2)
    denied = w.client.put(f"/rules/{held}/mode", headers=w.h(), json=_ARM)
    challenge_id = denied.json()["challenge_id"]
    assert w.step_up(challenge_id=challenge_id).status_code == 200
    swapped = w.client.put(f"/rules/{other}/mode", headers=w.h(), json=_ARM)
    assert swapped.status_code == 403
    _validator(_SPEC, _STEP_UP_REQUIRED_BODY).validate(swapped.json())
    assert swapped.json()["challenge_id"] != challenge_id  # a challenge for that request
    (mismatch,) = w.of("auth.step_up_mismatch")
    assert mismatch["object_id"] == challenge_id
    resent = w.client.put(f"/rules/{held}/mode", headers=w.h(), json=_ARM)
    assert resent.status_code == 200 and resent.json()["mode"] == "armed"
    assert trail.count("rule.armed") == 1  # the held rule; the swapped request armed nothing
