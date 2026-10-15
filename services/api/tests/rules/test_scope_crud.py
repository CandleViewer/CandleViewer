"""E35-S04 AC2/live opt-in: the real save/arm routes enforce account grants (C-12.4)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.auth.generated_permissions import Permission
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RulesManager
from candleviewer.rules.service import RulesService
from candleviewer.rules.vocabulary import default_registry
from tests.rules.test_rules_routes import BASE, _ir

USER = uuid.UUID(int=1)
A, C = uuid.UUID(int=10), uuid.UUID(int=12)


class _Src:
    def __init__(self) -> None:
        self.perms: frozenset[str] = frozenset({"rules:read"})

    async def load_grants(self, owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
        return [(A, True, False)]

    async def load_permissions(self, owner: uuid.UUID) -> frozenset[str]:
        return self.perms


def _setup() -> tuple[TestClient, list[str], _Src, RulesManager]:
    audits: list[str] = []

    async def sink(event: str, data: dict[str, str]) -> None:
        audits.append(event)

    src = _Src()
    svc = RulesService()
    svc.wire_scope(src, "demo", sink)
    mgr = RulesManager(InMemoryRuleStore(), default_registry())

    def resolve(_r: Request) -> Actor:
        # owner flag on: only the scope resolver (user_account_access) may deny
        return Actor(str(USER), "s", frozenset(BASE), is_owner=True, step_up_fresh=True)

    app = FastAPI()
    app.include_router(
        make_rules_crud_router(lambda: mgr, resolve, lambda: svc.scope_resolver, svc.refresh_scope)
    )
    return TestClient(app), audits, src, mgr


def _scoped(acct: uuid.UUID, **sc: Any) -> dict[str, Any]:
    return _ir(scope={"level": "account", "account_ids": [str(acct)], **sc})


def test_create_and_update_reject_ungranted_account() -> None:
    c, audits, _s, _m = _setup()
    assert c.post("/rules", json={"ir": _scoped(C)}).status_code == 403
    assert audits == ["rule_scope_denied"]
    r = c.post("/rules", json={"ir": _scoped(A)})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    put = c.put(f"/rules/{rid}", json={"ir": _scoped(C)}, headers={"If-Match": "1"})
    assert put.status_code == 403


def test_active_version_and_arm_reject_ungranted_scope() -> None:
    c, _a, src, mgr = _setup()
    rid = c.post("/rules", json={"ir": _scoped(A)}).json()["id"]
    src.perms = frozenset()  # no grants needed to read; revoke by mutating source below
    src.load_grants = _no_grants  # type: ignore[method-assign]
    r = c.put(f"/rules/{rid}/mode", json={"mode": "armed"}, headers={"Idempotency-Key": "k"})
    assert r.status_code == 403
    assert mgr is not None


async def _no_grants(_o: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
    return []


def test_arm_live_needs_permission_and_audits_high_severity_on_real_arm() -> None:
    c, audits, src, _m = _setup()
    rid = c.post("/rules", json={"ir": _scoped(A)}).json()["id"]
    # widen to live on a new version (needs the seeded rules:arm_live to save, #2624)
    live = _scoped(A, environments=["demo", "live"])
    assert c.put(f"/rules/{rid}", json={"ir": live}, headers={"If-Match": "1"}).status_code == 403
    src.perms = frozenset({"rules:read", Permission.RULES_ARM_LIVE})
    assert c.put(f"/rules/{rid}", json={"ir": live}, headers={"If-Match": "1"}).status_code == 200
    assert "rule_live_scope_armed" not in audits  # saving is not arming
    c.put(f"/rules/{rid}/mode", json={"mode": "armed"}, headers={"Idempotency-Key": "k2"})
    assert audits.count("rule_live_scope_armed") == 1
