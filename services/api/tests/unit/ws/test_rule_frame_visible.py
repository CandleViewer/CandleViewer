"""#3488 (23 §6.3, §15.6): who a `rules` update reaches. `rule_frame_visible` reads a WS principal
as `/rules` reads a session; a `rules` publish names that check (`viewer`) or is refused."""

from __future__ import annotations

import uuid

import pytest

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.rules.manager import Actor, RuleRow, VersionRow, rule_visible
from candleviewer.ws.sequencing import SequencingHub
from candleviewer.ws_wiring import rule_frame_visible
from tests.unit.ws._seq_support import ACC_A, USER

OTHER = uuid.UUID(int=0x200)
VIEW, FROZEN = AccountGrant(ACC_A, True, False, False), AccountGrant(ACC_A, True, False, True)


def _row(owner: uuid.UUID, *accounts: uuid.UUID, deleted: bool = False) -> RuleRow:
    rid, ir = str(uuid.uuid4()), {"scope": {"account_ids": [str(a) for a in accounts]}}
    version = VersionRow("v1", rid, 1, ir, "h", "1", "", "", "")
    return RuleRow(rid, rid, str(owner), deleted=deleted, versions=[version])


def _who(role: str, *grants: AccountGrant) -> PrincipalSnapshot:
    return PrincipalSnapshot(USER, frozenset({role}), frozenset({Permission.RULES_READ}), grants)


#: may it reach: another user's rule on A, another user's bare rule, their own on A, their own bare,
#: their own deleted one
_PRINCIPALS = [
    pytest.param(_who("owner"), (True, True, True, True, False), id="owner_role"),
    pytest.param(_who("manager", VIEW), (False, False, True, True, False), id="manager"),
    pytest.param(_who("viewer", VIEW), (False, False, True, True, False), id="viewer"),
    pytest.param(_who("manager"), (False, False, False, True, False), id="grant_revoked"),
    pytest.param(_who("manager", FROZEN), (False, False, False, True, False), id="grant_frozen"),
]


@pytest.mark.parametrize(("principal", "reads"), _PRINCIPALS)
def test_rule_frame_visible_matches_what_rest_lists_for_the_same_user(
    principal: PrincipalSnapshot, reads: tuple[bool, ...]
) -> None:
    rows = (
        _row(OTHER, ACC_A),
        _row(OTHER),
        _row(USER, ACC_A),
        _row(USER),
        _row(USER, deleted=True),
    )
    grants = principal.account_grants
    scope = {str(g.exchange_account_id) for g in grants if not g.frozen}
    session = Actor(
        str(USER), "s", granted_accounts=frozenset(scope), is_owner="owner" in principal.roles
    )
    assert tuple(rule_frame_visible(r, principal) for r in rows) == reads
    assert tuple(rule_visible(r, session) for r in rows) == reads  # the session `/rules` reads


def test_publish_of_rules_without_a_viewer_is_refused() -> None:
    with pytest.raises(ValueError, match="needs its viewer"):
        SequencingHub().publish("rules", {"rules": []}, account=ACC_A)
