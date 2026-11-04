"""E09-X02 authorisation abuse cases (AC-AUTHZ-*): D1, O1, O7, U4, U30, U31, SR-050/051."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import (
    AccountGrant,
    Allow,
    Deny,
    DenyReason,
    ForbiddenError,
    PrincipalSnapshot,
    decide,
    enforce,
)

SEED = json.loads(
    (Path(__file__).parents[3] / "candleviewer" / "auth" / "rbac_seed.json").read_text("utf-8")
)


def _p(role: str, *grants: AccountGrant) -> PrincipalSnapshot:
    g = SEED["role_permissions"][role]
    perms = frozenset(Permission) if g == ["*"] else frozenset(Permission(c) for c in g)
    return PrincipalSnapshot(uuid.uuid4(), frozenset({role}), perms, tuple(grants))


class _Em:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def emit(self, action: str, **kw: object) -> None:
        self.calls.append(action)


def _scoped_perm() -> Permission:
    """A permission a manager holds, so the second (account) layer is what decides."""
    return next(
        Permission(c)
        for c in SEED["role_permissions"]["manager"]
        if c in Permission._value2member_map_
    )


def test_ac_authz_01_manager_and_viewer_never_gain_owner_only_permissions() -> None:  # D1 / U3
    owner_only = [
        p
        for p in Permission
        if p.value not in SEED["role_permissions"]["manager"]
        and p.value not in SEED["role_permissions"]["viewer"]
    ]
    assert owner_only, "seed must withhold something from non-owners"
    for role in ("manager", "viewer"):
        for perm in owner_only:
            assert isinstance(decide(_p(role), perm), Deny)


def test_ac_authz_02_account_id_tampering_denied_without_grant() -> None:  # O1 / SR-050
    mine, other = uuid.uuid4(), uuid.uuid4()
    mgr = _p("manager", AccountGrant(mine, True, True, False))
    perm = _scoped_perm()
    assert isinstance(
        decide(mgr, perm, scope=Scope.GRANTED_ACCOUNTS, exchange_account_id=mine), Allow
    )
    d = decide(mgr, perm, scope=Scope.GRANTED_ACCOUNTS, exchange_account_id=other)
    assert isinstance(d, Deny) and d.reason is DenyReason.ACCOUNT_NOT_GRANTED


def test_ac_authz_03_missing_account_id_is_denied_not_permissive() -> None:  # U30 / SR-E09-05
    d = decide(_p("manager"), _scoped_perm(), scope=Scope.GRANTED_ACCOUNTS)
    assert isinstance(d, Deny) and d.reason is DenyReason.OBJECT_REQUIRED


def test_ac_authz_04_view_only_frozen_and_no_trade_grants_refuse_trading() -> None:  # U31
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    mgr = _p(
        "manager",
        AccountGrant(a, True, False, False),
        AccountGrant(b, True, True, True),
        AccountGrant(c, False, True, False),
    )
    perm = _scoped_perm()
    g = Scope.GRANTED_ACCOUNTS
    assert decide(mgr, perm, exchange_account_id=a, requires_trade=True, scope=g) == Deny(
        DenyReason.TRADING_NOT_GRANTED, permission=perm, scope=Scope.GRANTED_ACCOUNTS
    )
    assert getattr(decide(mgr, perm, exchange_account_id=b, scope=g), "reason", None) is (
        DenyReason.ACCOUNT_FROZEN
    )
    assert getattr(decide(mgr, perm, exchange_account_id=c, scope=g), "reason", None) is (
        DenyReason.ACCOUNT_NOT_GRANTED
    )


def test_ac_authz_05_unknown_role_cannot_be_forged_into_a_snapshot() -> None:  # U4 / SR-055
    with pytest.raises(ValueError):
        PrincipalSnapshot(uuid.uuid4(), frozenset({"owner-ish"}), frozenset(Permission))
    # A role-name string 'owner' alone grants nothing without being the system role set member
    assert _p("viewer").is_owner is False


def test_ac_authz_06_demotion_takes_effect_on_the_next_snapshot() -> None:  # U32
    perm = next(
        p
        for p in Permission
        if p.value in SEED["role_permissions"]["manager"]
        and p.value not in SEED["role_permissions"]["viewer"]
    )
    uid = uuid.uuid4()
    before = PrincipalSnapshot(uid, frozenset({"manager"}), _p("manager").permissions)
    after = PrincipalSnapshot(uid, frozenset({"viewer"}), _p("viewer").permissions)
    assert isinstance(decide(before, perm), Allow)
    assert isinstance(decide(after, perm), Deny)  # refresh-on-change is the bus's job (E09-T05)


async def test_ac_authz_07_every_denial_is_audited() -> None:  # U19
    em = _Em()
    perm = next(p for p in Permission if p.value not in SEED["role_permissions"]["viewer"])
    with pytest.raises(ForbiddenError):
        await enforce(_p("viewer"), perm, emitter=em)
    assert em.calls == ["rbac.denied"]
