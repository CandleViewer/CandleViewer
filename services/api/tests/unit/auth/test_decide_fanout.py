"""The WS fan-out's inline permission check is `decide()`'s permission clause (#2527).

`ws.sequencing.in_scope` tests `family.permission not in principal.permissions` at publish time
and does not call `decide()`, which allocates an `Allow()` per call: too dear per delta per
subscriber. `sub` and the §9.5 re-evaluation do call it (`ws/permissions.py`), so a global deny
added to `decide` (a frozen principal, a step-up, a disabled flag) would apply there and not in
the fan-out: the gap #2521 closed (#2398). The first test fails on any change to `decide`'s answer
for scope NONE or SELF, the second keeps the principals it draws complete, and the third fails if
`in_scope` stops answering as `decide` does for a private family.
"""

from __future__ import annotations

import dataclasses
import uuid

from hypothesis import given
from hypothesis import strategies as st

from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import _SYSTEM_ROLES, AccountGrant, Allow, PrincipalSnapshot, decide
from candleviewer.ws.permissions import ConnectionAuthz, Subscription
from candleviewer.ws.sequencing import in_scope
from candleviewer.ws.topics import FAMILIES, ParsedTopic

#: Every field of `AccountGrant`, so that a grant is drawn over its whole range as well.
_GRANT_FIELDS = {
    "exchange_account_id": st.uuids(),
    "can_view": st.booleans(),
    "can_trade": st.booleans(),
    "frozen": st.booleans(),
}
_GRANTS = st.lists(st.builds(AccountGrant, **_GRANT_FIELDS), max_size=3).map(tuple)
#: Every field of `PrincipalSnapshot`, over its whole range: for scope NONE or SELF only the
#: permissions may matter. The full set (the owner's) is drawn as well as subsets of it, so any
#: one permission is held in a large share of the draws and missing in another. The roles are
#: `_SYSTEM_ROLES` itself, so a role added later is drawn too.
_FIELDS = {
    "user_id": st.uuids(),
    "roles": st.frozensets(st.sampled_from(sorted(_SYSTEM_ROLES))),
    "permissions": st.frozensets(st.sampled_from(Permission)) | st.just(frozenset(Permission)),
    "account_grants": _GRANTS,
}
_PRINCIPALS = st.builds(PrincipalSnapshot, **_FIELDS)
_ACCOUNT = uuid.UUID(int=1)
#: Every private family with a permission and its scope: `alerts` (SELF), `recorder` (NONE) and
#: the six scoped to accounts, whose inline check is the same line behind an account clause.
_PRIVATE = {
    family.family: (family, family.permission, family.scope)
    for family in FAMILIES.values()
    if family.private and family.permission is not None and family.scope is not None
}


@given(principal=_PRINCIPALS, scope=st.sampled_from((Scope.NONE, Scope.SELF)))
def test_decide_with_scope_none_or_self_allows_exactly_the_permissions_the_principal_holds(
    principal: PrincipalSnapshot, scope: Scope
) -> None:
    allowed = {
        perm for perm in Permission if isinstance(decide(principal, perm, scope=scope), Allow)
    }
    assert allowed == principal.permissions, (
        "`ws.sequencing.in_scope` applies `permission in principal.permissions` inline: change"
        " both, and this pin, together (#2527)"
    )


def test_the_principals_drawn_cover_every_field_of_the_snapshot() -> None:
    """A field the snapshot or a grant gains (a frozen flag) keeps its default unless `_FIELDS` or
    `_GRANT_FIELDS` draws it, so a global deny keyed on it would pass the other tests. Only `init`
    fields can be drawn: a derived one is a function of them."""
    snapshot = {f.name for f in dataclasses.fields(PrincipalSnapshot) if f.init}
    grant = {f.name for f in dataclasses.fields(AccountGrant) if f.init}
    assert (snapshot, grant) == (set(_FIELDS), set(_GRANT_FIELDS)), (
        "PrincipalSnapshot's or AccountGrant's fields changed: draw the new one in `_FIELDS` or"
        " `_GRANT_FIELDS`; `decide` must ignore it for NONE/SELF, or `in_scope` must apply it too"
        " (#2527)"
    )


@given(principal=_PRINCIPALS)
def test_in_scope_reaches_every_private_family_as_decide_allows_it(
    principal: PrincipalSnapshot,
) -> None:
    authz = ConnectionAuthz(principal)
    for name, (family, permission, scope) in _PRIVATE.items():
        account = _ACCOUNT if family.account_scoped else None
        accounts = frozenset({account}) if account is not None else frozenset()
        sub = Subscription("s1", ParsedTopic(name, family), {}, {}, accounts)
        reached = in_scope(authz, sub, account, principal.user_id)
        asked = Scope.NONE if family.account_scoped else scope  # `sub` asks those at NONE too
        allowed = isinstance(decide(principal, permission, scope=asked), Allow)
        assert reached == allowed, f"`in_scope` must answer as `decide` does for {name} (#2527)"
