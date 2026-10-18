"""SR-050 layer 2: the rules manager's own grant check, exercised without the HTTP route.

The route-level scope resolver is layer 1; these tests call `RulesManager` directly so that
only the manager's `_require_grants` / visibility checks stand between the actor and the store.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleError, RulesManager
from candleviewer.rules.vocabulary import default_registry

FIX = Path(__file__).parents[1] / "fixtures/rule_ir"
A1, A2 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"
SCOPE = {"level": "symbol", "symbols": ["BTCUSDT"], "environments": ["demo"]}
OWNER = Actor("owner", "s0", frozenset({"rules:write"}), is_owner=True)
MGR_A1 = Actor("mgr", "s1", frozenset({"rules:write"}), frozenset({A1}))
NO_GRANTS = Actor("nobody", "s2", frozenset({"rules:write"}), frozenset())


def _ir(*accts: str, name: str = "r1") -> dict[str, Any]:
    raw = json.loads((FIX / "form_simple_0.json").read_text(encoding="utf-8"), parse_float=str)
    raw["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x"}
    return {**raw, "name": name, "scope": {**SCOPE, "account_ids": list(accts)}}


def _mgr() -> tuple[RulesManager, InMemoryRuleStore, list[tuple[str, dict[str, Any]]]]:
    audits: list[tuple[str, dict[str, Any]]] = []

    async def audit(a: str, p: dict[str, Any]) -> None:
        audits.append((a, p))

    store = InMemoryRuleStore()
    return RulesManager(store, default_registry(), audit=audit), store, audits


async def test_create_on_ungranted_account_is_refused_and_not_persisted() -> None:
    m, store, audits = _mgr()
    for actor, accts in ((MGR_A1, (A2,)), (MGR_A1, (A1, A2)), (NO_GRANTS, (A1,))):
        with pytest.raises(RuleError) as exc:
            await m.create(_ir(*accts), actor)
        assert exc.value.status == 403 and exc.value.code == "forbidden"
    assert await store.all() == []
    assert not [a for a, _ in audits if a == "rule.created"]


async def test_create_without_any_grant_is_refused_even_for_accountless_rule() -> None:
    m, store, _ = _mgr()
    with pytest.raises(RuleError) as exc:
        await m.create(_ir(), NO_GRANTS)
    assert exc.value.status == 403
    assert await store.all() == []


async def test_update_retargeting_to_ungranted_account_is_refused_and_not_persisted() -> None:
    m, store, audits = _mgr()
    rid = (await m.create(_ir(A1), MGR_A1))["id"]
    before = [v.ir_hash for v in (await store.get(rid)).versions]  # type: ignore[union-attr]
    with pytest.raises(RuleError) as exc:
        await m.update(rid, _ir(A2), 1, MGR_A1)
    assert exc.value.status == 403 and exc.value.code == "forbidden"
    row = await store.get(rid)
    assert row is not None and row.latest_version == 1
    assert [v.ir_hash for v in row.versions] == before
    assert [a for a, _ in audits].count("rule.updated") == 0  # no update for a refused edit


async def test_update_of_another_accounts_rule_is_refused_and_not_persisted() -> None:
    m, store, _ = _mgr()
    rid = (await m.create(_ir(A2), OWNER))["id"]
    with pytest.raises(RuleError) as exc:
        await m.update(rid, _ir(A1, name="renamed"), 1, MGR_A1)
    assert exc.value.status == 404
    row = await store.get(rid)
    assert row is not None and row.latest_version == 1 and row.name == "r1"


async def test_all_accounts_fanout_is_refused_for_non_owner() -> None:
    m, store, _ = _mgr()
    ir = _ir(A1)
    ir["actions"][0]["targets"] = "all_accounts"
    with pytest.raises(RuleError) as exc:
        await m.create(ir, MGR_A1)
    assert exc.value.status == 403
    assert await store.all() == []


async def test_list_hides_rules_on_ungranted_accounts() -> None:
    m, _, _ = _mgr()
    await m.create(_ir(A1, name="mine"), MGR_A1)
    await m.create(_ir(A1, name="owners"), OWNER)  # on a granted account, but not MGR_A1's
    await m.create(_ir(A2, name="theirs"), OWNER)
    await m.create(_ir(A1, A2, name="both"), OWNER)
    names = {r["name"] for r in (await m.list_rules(MGR_A1))["items"]}
    assert names == {"mine"}
    assert (await m.list_rules(NO_GRANTS))["items"] == []
    assert len((await m.list_rules(OWNER))["items"]) == 4


async def test_arm_of_ungranted_rule_is_refused_and_mode_unchanged() -> None:
    m, store, audits = _mgr()
    rid = (await m.create(_ir(A2), OWNER))["id"]
    for target in ("simulate", "armed"):
        with pytest.raises(RuleError) as exc:
            await m.set_mode(rid, target, MGR_A1, f"k-{target}")
        assert exc.value.status == 404
    row = await store.get(rid)
    assert row is not None and row.mode == "disabled" and row.armed_by is None
    assert not [a for a, _ in audits if a in ("rule.armed", "rule.simulated")]


async def test_set_active_version_to_ungranted_version_is_refused() -> None:
    m, store, _ = _mgr()
    rid = (await m.create(_ir(A1), OWNER))["id"]
    await m.update(rid, _ir(A1, A2), 1, OWNER)
    row = await store.get(rid)
    assert row is not None
    v2, active_before = row.versions[1].id, row.active_version_id
    # The rule is no longer visible to a manager granted only A1 (every version counts).
    with pytest.raises(RuleError) as exc:
        await m.set_active_version(rid, v2, "n", MGR_A1)
    assert exc.value.status == 404
    assert row.active_version_id == active_before


# ---- C-2.9: refusals are audited (write-ahead, one record each, no secrets) -------------------
def _refusals(audits: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    return [p for a, p in audits if a == "rule.scope_refused"]


@pytest.mark.parametrize(
    ("actor", "accts", "reason"),
    [
        (MGR_A1, (A2,), "account_not_granted"),
        (NO_GRANTS, (), "no_grants"),
    ],
)
async def test_require_grants_refusal_on_create_is_audited_once(
    actor: Actor, accts: tuple[str, ...], reason: str
) -> None:
    m, store, audits = _mgr()
    with pytest.raises(RuleError):
        await m.create(_ir(*accts), actor)
    (rec,) = _refusals(audits)
    assert rec["op"] == "create" and rec["reason"] == reason and rec["actor"] == actor.user_id
    assert set(rec) == {"rule_id", "op", "reason", "actor"}
    assert await store.all() == []


async def test_require_grants_refusal_on_update_is_audited_once() -> None:
    m, _, audits = _mgr()
    rid = (await m.create(_ir(A1), MGR_A1))["id"]
    with pytest.raises(RuleError):
        await m.update(rid, _ir(A2), 1, MGR_A1)
    (rec,) = _refusals(audits)
    assert (
        rec["op"] == "update" and rec["rule_id"] == rid and rec["reason"] == "account_not_granted"
    )


async def test_all_accounts_target_refusal_is_audited() -> None:
    m, _, audits = _mgr()
    ir = _ir(A1)
    ir["actions"][0]["targets"] = "all_accounts"
    with pytest.raises(RuleError):
        await m.create(ir, MGR_A1)
    (rec,) = _refusals(audits)
    assert rec["reason"] == "all_accounts_needs_owner"


async def test_visible_refusal_on_mutation_and_arm_is_audited_but_reads_are_not() -> None:
    m, _, audits = _mgr()
    rid = (await m.create(_ir(A2), OWNER))["id"]
    other = Actor("m2", "s3", frozenset({"rules:write"}), frozenset({A1}))
    with pytest.raises(RuleError):
        await m.update(rid, _ir(A1), 1, other)
    with pytest.raises(RuleError):
        await m.delete(rid, other)
    with pytest.raises(RuleError):
        await m.set_mode(rid, "simulate", other, "k1")
    assert [r["op"] for r in _refusals(audits)] == ["update", "delete", "set_mode"]
    assert all(r["reason"] == "rule_not_visible" for r in _refusals(audits))
    n = len(audits)
    with pytest.raises(RuleError):
        await m.get(rid, other)
    assert (await m.list_rules(other))["items"] == []
    assert len(audits) == n  # reads / list filtering are scoping, not refusals
