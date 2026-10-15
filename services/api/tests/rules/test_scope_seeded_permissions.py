"""#2624: the rule scope gate checks the permission code the database seeds.

`SqlAlchemyScopeSource.load_permissions` and the session principal both read raw
`permissions.code` rows: migration 0001 expands the owner's `"*"` seed grant into one row per
code and migration 0015 adds `rules:arm_live`. The fakes below return exactly that, read from
`auth/rbac_seed.json`: never a hand-written literal and never `"*"`, either of which would mask
a gate that checks the wrong string.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.api.rules import make_rules_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.generated_permissions import Permission
from candleviewer.rules.arming import LIVE_ARM_PERMISSION
from candleviewer.rules.errors import ScopeForbiddenError
from candleviewer.rules.ir.models import RuleScope
from candleviewer.rules.scope import ScopeResolver
from candleviewer.rules.scope_state import ARM_LIVE, SnapshotScopeState
from candleviewer.rules.vocabulary import default_registry
from candleviewer.rules.vocabulary.catalogue import ARM_LIVE_PERMISSION

SEED = json.loads(
    (Path(__file__).parents[2] / "candleviewer" / "auth" / "rbac_seed.json").read_text("utf-8")
)
OWNER, MANAGER = uuid.UUID(int=1), uuid.UUID(int=2)
LIVE_ACCOUNT = uuid.UUID(int=10)
LIVE_SCOPE = RuleScope.model_validate(
    {"level": "account", "account_ids": [str(LIVE_ACCOUNT)], "environments": ["live"]}
)


def _db_codes(role: str) -> frozenset[str]:
    """The `permissions.code` rows a user holding only `role` has on a migrated database."""
    granted = SEED["role_permissions"][role]
    every = frozenset(p["code"] for p in SEED["permissions"])
    return every if granted == ["*"] else frozenset(granted)


class _SeededSource:
    """`ScopeSource` shaped like `SqlAlchemyScopeSource`: one granted account, seeded codes."""

    roles: ClassVar[dict[uuid.UUID, str]] = {OWNER: "owner", MANAGER: "manager"}

    async def load_grants(self, owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
        return [(LIVE_ACCOUNT, True, False)]

    async def load_permissions(self, owner: uuid.UUID) -> frozenset[str]:
        return _db_codes(self.roles[owner])


async def _gate(user: uuid.UUID) -> tuple[ScopeResolver, list[str]]:
    """Production state + resolver on a live deployment with the live gate open."""
    audits: list[str] = []

    async def audit(event: str, data: dict[str, str]) -> None:
        audits.append(event)

    state = SnapshotScopeState(_SeededSource(), "live", live_gate_open=lambda: True)
    await state.refresh(user)
    return ScopeResolver(state, audit), audits


def test_seed_grants_arm_live_to_owner_and_not_to_manager() -> None:
    assert Permission.RULES_ARM_LIVE in _db_codes("owner")
    assert Permission.RULES_ARM_LIVE not in _db_codes("manager")


async def test_scope_gate_owner_with_seeded_arm_live_can_scope_rule_to_live_account() -> None:
    resolver, audits = await _gate(OWNER)
    await resolver.authorize_accounts(OWNER, [LIVE_ACCOUNT])
    await resolver.authorize_environments(OWNER, LIVE_SCOPE)  # the real arm: must not raise
    assert audits == ["rule_live_scope_armed"]
    res = resolver.resolve(LIVE_SCOPE, OWNER, "live")
    assert not res.env_skipped
    assert [i.account_id for i in res.instances] == [LIVE_ACCOUNT]


async def test_scope_gate_manager_without_arm_live_is_refused_live_and_audited() -> None:
    resolver, audits = await _gate(MANAGER)
    with pytest.raises(ScopeForbiddenError):
        await resolver.authorize_environments(MANAGER, LIVE_SCOPE)
    assert audits == ["rule_scope_denied"]
    assert resolver.resolve(LIVE_SCOPE, MANAGER, "live").env_skipped


def _vocabulary(role: str) -> dict[str, Any]:
    """`GET /rules/vocabulary` as the production session principal for `role` sees it."""
    user = OWNER if role == "owner" else MANAGER
    principal = AuditPrincipal(user_id=user, username=role, permissions=_db_codes(role))

    class _Resolver:
        def resolve(self, request: object) -> AuditPrincipal:
            return principal

    app = FastAPI()
    registry = default_registry()
    app.include_router(make_rules_router(lambda: registry, principal_resolver=_Resolver()))
    response = TestClient(app).get("/rules/vocabulary")
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_vocabulary_seeded_owner_sees_arm_live_code_and_its_actions_available() -> None:
    body = _vocabulary("owner")
    assert body["arm_live_permission"] == Permission.RULES_ARM_LIVE
    actions = {a["id"]: a for a in body["actions"]}
    assert actions["resume_new_orders"]["available"] is True


def test_vocabulary_seeded_manager_is_told_the_seeded_arm_live_code_is_missing() -> None:
    actions = {a["id"]: a for a in _vocabulary("manager")["actions"]}
    resume = actions["resume_new_orders"]
    assert resume["available"] is False
    assert resume["restriction"] == f"Requires {Permission.RULES_ARM_LIVE}."


def test_rule_engine_arm_live_constants_are_the_generated_seed_code() -> None:
    """`rules` may not import `auth` (import-linter M15), so it mirrors the code: pin it."""
    assert {ARM_LIVE, LIVE_ARM_PERMISSION, ARM_LIVE_PERMISSION} == {Permission.RULES_ARM_LIVE}
