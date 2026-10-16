"""Decision-matrix tests for `candleviewer.auth.scopes.decide` (E09-T03).

Covers the ticket's Gherkin scenarios that are pure decision-point logic
(deny-by-default, manager cross-account isolation, frozen/trade-scope
checks); the WS-propagation and owner-floor scenarios are integration-level
and out of this module's unit-test scope (see ticket "Test plan").
"""

from __future__ import annotations

import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import (
    AccountGrant,
    Allow,
    Deny,
    DenyReason,
    PrincipalSnapshot,
    account_scope,
    decide,
)
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope

ACCOUNT_A = uuid.UUID("a1000000-0000-4000-8000-000000000001")
ACCOUNT_B = uuid.UUID("a1000000-0000-4000-8000-000000000002")


def _manager(*, grants: tuple[AccountGrant, ...] = ()) -> PrincipalSnapshot:
    return PrincipalSnapshot(
        user_id=uuid.uuid4(),
        roles=frozenset({"manager"}),
        permissions=frozenset({Permission.ORDERS_READ, Permission.ORDERS_WRITE}),
        account_grants=grants,
    )


def _owner() -> PrincipalSnapshot:
    return PrincipalSnapshot(
        user_id=uuid.uuid4(),
        roles=frozenset({"owner"}),
        permissions=frozenset(Permission),
    )


def _viewer() -> PrincipalSnapshot:
    return PrincipalSnapshot(
        user_id=uuid.uuid4(),
        roles=frozenset({"viewer"}),
        permissions=frozenset({Permission.ORDERS_READ}),
    )


def test_missing_permission_denies_by_default() -> None:
    principal = _viewer()
    result = decide(principal, Permission.ORDERS_WRITE)
    assert isinstance(result, Deny)
    assert result.reason == DenyReason.MISSING_PERMISSION
    # PR #1629 review finding 2: the denial must name the permission and
    # scope so the audited `rbac.denied` record can be built from it alone.
    assert result.permission == Permission.ORDERS_WRITE
    assert result.scope == Scope.NONE


def test_admin_write_denied_unless_role_holds_it() -> None:
    # #1637 added admin:write (setLogLevelOverride); only owner is seeded with it.
    for principal in (_manager(), _viewer()):
        result = decide(principal, Permission.ADMIN_WRITE)
        assert isinstance(result, Deny)
        assert result.reason == DenyReason.MISSING_PERMISSION
    assert isinstance(decide(_owner(), Permission.ADMIN_WRITE), Allow)


def test_scope_none_allows_on_permission_alone() -> None:
    principal = _manager()
    result = decide(principal, Permission.ORDERS_READ, scope=Scope.NONE)
    assert isinstance(result, Allow)


def test_granted_accounts_requires_object() -> None:
    principal = _manager(
        grants=(AccountGrant(ACCOUNT_A, can_view=True, can_trade=True, frozen=False),)
    )
    result = decide(principal, Permission.ORDERS_READ, scope=Scope.GRANTED_ACCOUNTS)
    assert isinstance(result, Deny)
    assert result.reason == DenyReason.OBJECT_REQUIRED


def test_manager_cannot_reach_another_managers_account() -> None:
    """Ticket scenario: "A manager cannot reach another manager's account"."""
    principal = _manager(
        grants=(AccountGrant(ACCOUNT_A, can_view=True, can_trade=True, frozen=False),)
    )
    result = decide(
        principal,
        Permission.ORDERS_READ,
        scope=Scope.GRANTED_ACCOUNTS,
        exchange_account_id=ACCOUNT_B,
    )
    assert isinstance(result, Deny)
    assert result.reason == DenyReason.ACCOUNT_NOT_GRANTED


def test_manager_can_reach_own_granted_account() -> None:
    principal = _manager(
        grants=(AccountGrant(ACCOUNT_A, can_view=True, can_trade=True, frozen=False),)
    )
    result = decide(
        principal,
        Permission.ORDERS_READ,
        scope=Scope.GRANTED_ACCOUNTS,
        exchange_account_id=ACCOUNT_A,
    )
    assert isinstance(result, Allow)


def test_frozen_account_denies_even_with_grant() -> None:
    principal = _manager(
        grants=(AccountGrant(ACCOUNT_A, can_view=True, can_trade=True, frozen=True),)
    )
    result = decide(
        principal,
        Permission.ORDERS_READ,
        scope=Scope.GRANTED_ACCOUNTS,
        exchange_account_id=ACCOUNT_A,
    )
    assert isinstance(result, Deny)
    assert result.reason == DenyReason.ACCOUNT_FROZEN


def test_view_only_grant_denies_trade_when_requires_trade() -> None:
    principal = _manager(
        grants=(AccountGrant(ACCOUNT_A, can_view=True, can_trade=False, frozen=False),)
    )
    result = decide(
        principal,
        Permission.ORDERS_WRITE,
        scope=Scope.GRANTED_ACCOUNTS,
        exchange_account_id=ACCOUNT_A,
        requires_trade=True,
    )
    assert isinstance(result, Deny)
    assert result.reason == DenyReason.TRADING_NOT_GRANTED


def test_owner_reaches_any_account_with_no_grant_rows() -> None:
    """Ticket text: "empty allowed_account_ids means all, owner only"."""
    principal = _owner()
    result = decide(
        principal,
        Permission.ORDERS_WRITE,
        scope=Scope.GRANTED_ACCOUNTS,
        exchange_account_id=ACCOUNT_B,
        requires_trade=True,
    )
    assert isinstance(result, Allow)


def test_missing_permission_short_circuits_before_scope_check() -> None:
    """A principal without the base permission is denied even for an
    account they are granted — permission is checked first."""
    principal = _manager(
        grants=(AccountGrant(ACCOUNT_A, can_view=True, can_trade=True, frozen=False),)
    )
    result = decide(
        principal,
        Permission.KEYS_MANAGE,
        scope=Scope.GRANTED_ACCOUNTS,
        exchange_account_id=ACCOUNT_A,
    )
    assert isinstance(result, Deny)
    assert result.reason == DenyReason.MISSING_PERMISSION


@pytest.mark.parametrize(
    "role,permission,expected",
    [
        ("owner", Permission.KEYS_MANAGE, Allow),
        ("owner", Permission.USERS_WRITE, Allow),
        ("manager", Permission.USERS_WRITE, Deny),
        ("manager", Permission.KEYS_MANAGE, Deny),
        # manager holds killswitch:write scoped to their own granted
        # accounts (ticket "Role seeds": "no killswitch:write beyond own
        # scope" — the seed grants the base permission; GRANTED_ACCOUNTS
        # scope is what narrows it, covered by the account-scope tests
        # above, not this permission-only matrix).
        ("manager", Permission.KILLSWITCH_WRITE, Allow),
        ("viewer", Permission.ORDERS_WRITE, Deny),
        # 04 §7.2.1 / SR-067 (#2083): owner raw, manager own-redacted, viewer none.
        ("owner", Permission.AUDIT_READ, Allow),
        ("manager", Permission.AUDIT_READ, Allow),
        ("viewer", Permission.AUDIT_READ, Deny),
    ],
)
def test_role_permission_matrix(
    role: str, permission: Permission, expected: type[Allow] | type[Deny]
) -> None:
    """Exhaustive-flavoured matrix over the seed's role_permissions grants
    (ticket "Role seeds": manager has no `users:write`/`keys:manage`/
    `killswitch:write` beyond own scope; viewer has no audit read, manager does)."""
    import json
    from pathlib import Path

    seed_path = Path(__file__).resolve().parents[3] / "candleviewer" / "auth" / "rbac_seed.json"
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    granted_codes = seed["role_permissions"][role]
    has_permission = granted_codes == ["*"] or permission.value in granted_codes

    principal = PrincipalSnapshot(
        user_id=uuid.uuid4(),
        roles=frozenset({role}),
        permissions=frozenset(Permission) if has_permission else frozenset(),
    )
    result = decide(principal, permission)
    assert isinstance(result, expected)


def test_custom_role_named_owner_is_rejected() -> None:
    """PR #1629 review finding 3: `is_owner` matches the role name alone,
    so a `PrincipalSnapshot` must never be constructible with a role
    outside the DB's fixed `role_name` ENUM (`owner`/`manager`/`viewer`) —
    a hypothetical custom role called "owner" cannot silently inherit the
    owner floor's account-grant bypass."""
    with pytest.raises(ValueError, match="unknown role"):
        PrincipalSnapshot(
            user_id=uuid.uuid4(),
            roles=frozenset({"owner_impersonator"}),
            permissions=frozenset({Permission.ORDERS_WRITE}),
        )


def test_wildcard_grant_is_owner_only_in_seed_and_contract() -> None:
    """`*` means every permission (and the raw audit view); only `owner` may hold it (#2083)."""
    import json
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    seed = json.loads((root / "candleviewer" / "auth" / "rbac_seed.json").read_text("utf-8"))
    holders = {r for r, codes in seed["role_permissions"].items() if "*" in codes}
    assert holders == {"owner"}
    assert seed["role_permissions"]["owner"] == ["*"]

    text = (root.parent.parent / "docs" / "plan" / "22-api-openapi.yaml").read_text("utf-8")
    block = re.search(r"x-permissions:\n(.*?)\npaths:", text, re.S)
    assert block is not None
    for role in ("manager", "viewer"):
        codes = re.search(role + r":\n((?:    - .*\n)+)", block.group(1))
        assert codes is not None
        assert "*" not in {c.strip("- ").strip() for c in codes.group(1).splitlines()}


# --- account_scope (E27-T01, SR-051) -------------------------------------------------------


def _acct_principal(roles: frozenset[str], grants: tuple[AccountGrant, ...]) -> PrincipalSnapshot:
    return PrincipalSnapshot(
        user_id=uuid.uuid4(),
        roles=roles,
        permissions=frozenset({Permission.ACCOUNTS_READ}),
        account_grants=grants,
    )


def test_account_scope_owner_is_owner_scope() -> None:
    p = _owner()
    assert account_scope(p) == OwnerScope(p.user_id)


def test_account_scope_keeps_only_viewable_unfrozen_grants() -> None:
    c, d = uuid.uuid4(), uuid.uuid4()
    p = _acct_principal(
        frozenset({"manager"}),
        (
            AccountGrant(ACCOUNT_A, True, True, False),
            AccountGrant(ACCOUNT_B, True, True, True),
            AccountGrant(c, False, False, False),
            AccountGrant(d, True, False, False),
        ),
    )
    assert account_scope(p) == GrantScope(p.user_id, frozenset({ACCOUNT_A, d}))


def test_account_scope_zero_grants_is_empty_never_all() -> None:
    p = _acct_principal(frozenset({"viewer"}), ())
    assert account_scope(p) == GrantScope(p.user_id, frozenset())


@given(
    st.lists(
        st.tuples(st.integers(0, 3), st.booleans(), st.booleans(), st.booleans()),
        max_size=8,
    ),
    st.sampled_from(["owner", "manager", "viewer"]),
    st.integers(0, 4),
)
def test_account_scope_membership_matches_decide(
    raw: list[tuple[int, bool, bool, bool]], role: str, probe: int
) -> None:
    ids = [uuid.UUID(int=i + 1) for i in range(5)]
    seen: dict[int, AccountGrant] = {}
    for i, v, t, f in raw:
        seen[i] = AccountGrant(ids[i], v, t, f)
    p = _acct_principal(frozenset({role}), tuple(seen.values()))
    scope = account_scope(p)
    in_scope = isinstance(scope, OwnerScope) or (
        isinstance(scope, GrantScope) and ids[probe] in scope.account_ids
    )
    allowed = isinstance(
        decide(
            p,
            Permission.ACCOUNTS_READ,
            scope=Scope.GRANTED_ACCOUNTS,
            exchange_account_id=ids[probe],
        ),
        Allow,
    )
    assert in_scope == allowed
