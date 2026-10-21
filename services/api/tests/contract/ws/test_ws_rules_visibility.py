"""#3488 (23 §6.3, §15.6): a `rules` update reaches a Manager only for a rule they may read, as
`GET /rules` lists it, and a grant revoked ends delivery of the rules that named it. Real gateway,
hub and principal; the producer routes each update to account A, as the family's scope needs."""

from __future__ import annotations

import uuid
from functools import partial
from typing import Any

from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.rules.manager import RuleRow
from candleviewer.ws_wiring import rule_frame_visible
from tests.contract.ws._harness import World, connect
from tests.unit.ws._seq_support import ACC_A, ACC_B, USER
from tests.unit.ws.test_rule_frame_visible import OTHER as OWNER
from tests.unit.ws.test_rule_frame_visible import _row


def _send(w: World, row: RuleRow) -> int:
    body: dict[str, Any] = {"rules": [{"id": row.id, "mode": "armed", "updated_at_ms": 1}]}
    viewer = partial(rule_frame_visible, row)
    return int(w.call(lambda: w.hub.publish("rules", body, account=ACC_A, viewer=viewer)))


def test_rules_update_withholds_an_owners_rule_from_a_manager_and_follows_their_grants() -> None:
    w = World()
    theirs, bare = _row(OWNER, ACC_A), _row(OWNER)
    mine, on_a = _row(USER, ACC_A, ACC_B), _row(USER, ACC_A)
    with connect(w) as c:
        ids = sorted(r.id for r in (theirs, bare, mine, on_a))
        opts = {"exchange_account_ids": [str(ACC_A)], "rule_ids": ids}
        result = c.sub({"ch": "rules", "opts": opts})["p"]["results"][0]
        assert result["ok"] and result["effective"]["rule_ids"] == ids  # no id told apart
        assert c.recv()["t"] == "snap"
        assert [_send(w, r) for r in (theirs, bare, mine)] == [0, 0, 1]
        assert [(d["s"], d["p"]["rules"][0]["id"]) for d in [c.recv()]] == [(2, mine.id)]
        w.grants = (AccountGrant(ACC_A, True, False, False),)  # account B is withdrawn
        w.call(w.registry.grants_changed, USER)
        c.next_of("permission_change")
        assert [_send(w, r) for r in (mine, on_a)] == [0, 1]
        assert c.recv()["p"]["rules"][0]["id"] == on_a.id


class _OwnerRole(World):
    async def _resolve(self, uid: uuid.UUID) -> PrincipalSnapshot:
        return PrincipalSnapshot(uid, frozenset({"owner"}), self.perms, self.grants)


def test_rules_update_reaches_the_owner_role_for_every_rule_it_routes() -> None:
    w = _OwnerRole()
    with connect(w) as c:
        c.sub({"ch": "rules", "opts": {"exchange_account_ids": [str(ACC_A)]}})
        assert c.recv()["t"] == "snap"
        rows = (_row(OWNER, ACC_A), _row(OWNER), _row(USER, ACC_A, ACC_B))
        assert [_send(w, r) for r in rows] == [1, 1, 1]  # the stream #3488 leaves unchanged
