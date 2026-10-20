"""E40-T04: `RulesManager.visible_rule_ids` is the REST reads' visibility, as a set of ids.

`GET /notifications` filters rule history by it, so a rule's events are visible exactly when
`GET /rules` lists the rule (#3334's predicate: the Owner reaches every rule, anyone else only
their own rules while every account any version names is granted).
"""

from __future__ import annotations

import itertools

from candleviewer.rules.manager import Actor, RulesManager
from tests.rules.test_rule_ownership import A1, KINDS, MANAGER, OWNER, PERMS, _mgr
from tests.rules.test_rules_routes import _ir

_NAMES = itertools.count()


async def _seed(m: RulesManager, kind: str, owner: Actor) -> str:
    """A rule of *kind* saved by *owner* (rule names are unique across users)."""
    ir = _ir(name=f"visible-{next(_NAMES)}", scope=KINDS[kind])
    return str((await m.create(ir, owner))["id"])


async def test_the_owner_reaches_every_rule() -> None:
    m, _ = _mgr()
    await _seed(m, "accountless", MANAGER)
    assert await m.visible_rule_ids(OWNER) is None


async def test_a_manager_sees_only_their_own_fully_granted_rules() -> None:
    m, _ = _mgr()
    own = await _seed(m, "fully_granted", MANAGER)
    await _seed(m, "fully_granted", OWNER)  # someone else's rule on a granted account
    assert await m.visible_rule_ids(MANAGER) == {own}


async def test_a_revoked_grant_hides_the_managers_own_rule() -> None:
    m, _ = _mgr()
    await _seed(m, "fully_granted", MANAGER)
    revoked = Actor(MANAGER.user_id, "s2", PERMS, frozenset())
    assert await m.visible_rule_ids(revoked) == frozenset()


async def test_deleted_rules_are_not_listed_for_a_manager() -> None:
    m, _ = _mgr()
    rid = await _seed(m, "accountless", MANAGER)
    await m.delete(rid, MANAGER)
    assert await m.visible_rule_ids(MANAGER) == frozenset()


async def test_it_agrees_with_list_rules_for_every_actor() -> None:
    m, _ = _mgr()
    for kind in KINDS:
        await _seed(m, kind, MANAGER)
        await _seed(m, kind, OWNER)
    other = Actor("other", "s9", PERMS, frozenset({A1}))
    for actor in (MANAGER, other):
        listed = {str(i["id"]) for i in (await m.list_rules(actor, limit=100))["items"]}
        assert await m.visible_rule_ids(actor) == listed
