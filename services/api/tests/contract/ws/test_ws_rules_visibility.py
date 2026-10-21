"""#3488 (23 §6.3, §15.6): a `rules` update reaches a Manager only for a rule they may read, as
`GET /rules` lists it, and a grant revoked ends delivery of the rules that named it. Real gateway,
hub and principal; the producer routes each update to account A, as the family's scope needs."""

from __future__ import annotations

import uuid
from functools import partial
from typing import Any

import pytest

from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.rules.manager import RuleRow
from candleviewer.ws_wiring import rule_frame_visible
from tests.contract.ws._harness import World, connect, delta_body
from tests.unit.ws._seq_support import ACC_A, ACC_B, USER
from tests.unit.ws.test_rule_frame_visible import OTHER as OWNER
from tests.unit.ws.test_rule_frame_visible import _row


def _send(w: World, row: RuleRow) -> int:
    body: dict[str, Any] = {"rules": [{"id": row.id, "mode": "armed", "updated_at_ms": 1}]}
    viewer = partial(rule_frame_visible, row)
    return int(w.call(lambda: w.hub.publish("rules", body, account=ACC_A, viewer=viewer)))


def test_rules_update_withholds_an_owners_rule_from_a_manager() -> None:
    w = World()
    theirs, bare, mine = _row(OWNER, ACC_A), _row(OWNER), _row(USER, ACC_A)
    with connect(w) as c:
        ids = sorted(r.id for r in (theirs, bare, mine))
        opts = {"exchange_account_ids": [str(ACC_A)], "rule_ids": ids}
        result = c.sub({"ch": "rules", "opts": opts})["p"]["results"][0]
        assert result["ok"] and result["effective"]["rule_ids"] == ids  # no id told apart
        assert c.recv()["t"] == "snap"
        assert [_send(w, r) for r in (theirs, bare, mine)] == [0, 0, 1]
        d = c.recv()  # the two withheld spent no sequence number
        assert (d["s"], d["p"]["rules"][0]["id"]) == (2, mine.id)


def test_rules_update_ends_for_a_rule_naming_a_withdrawn_grant() -> None:
    w, both, on_a = World(), _row(USER, ACC_A, ACC_B), _row(USER, ACC_A)
    with connect(w) as c:
        c.sub({"ch": "rules", "opts": {"exchange_account_ids": [str(ACC_A)]}})
        assert c.recv()["t"] == "snap"
        assert _send(w, both) == 1  # readable while A and B are both granted
        assert c.recv()["p"]["rules"][0]["id"] == both.id
        w.grants = (AccountGrant(ACC_A, True, False, False),)  # account B is withdrawn
        w.call(w.registry.grants_changed, USER)
        c.next_of("permission_change")
        assert [_send(w, r) for r in (both, on_a)] == [0, 1]
        assert c.recv()["p"]["rules"][0]["id"] == on_a.id


def test_rules_publish_without_a_viewer_is_refused_before_any_frame() -> None:
    w, mine = World(), _row(USER, ACC_A)
    with connect(w) as c:
        for ch in ("rules", "orders"):
            c.sub({"ch": ch, "opts": {"exchange_account_ids": [str(ACC_A)]}})
            assert c.recv()["t"] == "snap"
        event = [("rules", {"rules": []}), ("orders", delta_body("orders"))]  # orders goes first
        for refused in (
            lambda: w.hub.publish("rules", {"rules": []}, account=ACC_A),
            lambda: w.hub.publish_private(ACC_A, event),  # a whole event, before its `orders`
        ):
            with pytest.raises(ValueError, match="needs its viewer"):
                w.call(refused)
        assert _send(w, mine) == 1
        d = c.recv()  # the next frame: nothing went out before it, and no number was spent
        assert (d["ch"], d["s"], [r["id"] for r in d["p"]["rules"]]) == ("rules", 2, [mine.id]), d


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
