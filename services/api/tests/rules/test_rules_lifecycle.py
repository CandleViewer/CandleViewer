"""E35-S01 review fixes: the rule mode lifecycle IS the B9 `rule_instance` chart.

Regression tests for PR #1801 review findings: no parallel transition table (C-2.19),
same-mode idempotency, actor-scoped replay cache, audit-before-persist (C-2.9),
orders:write on arming, distinct delete audit verb, rebuild from the persisted row.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest

from candleviewer.api.rules_actor import _ACTIONS, _before
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.rules.lifecycle import RuleLifecycle
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleError, RulesManager
from candleviewer.rules.vocabulary import default_registry
from tests.rules.test_rules_manager import MGR, OWNER, _active_hash, _ir


def _mgr(
    store: InMemoryRuleStore | None = None,
) -> tuple[RulesManager, list[tuple[str, dict[str, Any]]]]:
    audits: list[tuple[str, dict[str, Any]]] = []

    async def _audit(a: str, p: dict[str, Any]) -> None:
        audits.append((a, p))

    return RulesManager(store or InMemoryRuleStore(), default_registry(), audit=_audit), audits


async def _armed(m: RulesManager) -> str:
    rid = str((await m.create(_ir(), OWNER))["id"])
    await m.set_mode(rid, "simulate", OWNER, "s")
    await m.record_simulation(rid, await _active_hash(m, rid), 5, 0.0)
    await m.set_mode(rid, "armed", OWNER, "a")
    return rid


def test_no_hand_written_mode_matrix_module_remains() -> None:
    assert importlib.util.find_spec("candleviewer.rules.mode") is None


async def test_mode_changes_move_the_b9_chart() -> None:
    m, _ = _mgr()
    rid = str((await m.create(_ir(), OWNER))["id"])
    assert await m.lifecycle.current(rid, "disabled", None) == "draft"
    await m.set_mode(rid, "simulate", OWNER, "s")
    assert m.lifecycle.leaf(rid) == "simulating"
    await m.record_simulation(rid, await _active_hash(m, rid), 5, 0.0)
    await m.set_mode(rid, "armed", OWNER, "a")
    assert m.lifecycle.leaf(rid) == "armed"
    await m.set_mode(rid, "disabled", OWNER, "d")
    assert m.lifecycle.leaf(rid) == "disarmed"
    row = await m._s.get(rid)
    assert row is not None and (row.mode, row.disabled_reason) == ("disabled", "disarmed")


async def test_chart_refuses_draft_to_armed_and_row_is_unchanged() -> None:
    m, _ = _mgr()
    rid = str((await m.create(_ir(), OWNER))["id"])
    # Sync arming checks pass (evidence exists), so only the chart can refuse it.
    await m.record_simulation(rid, await _active_hash(m, rid), 5, 0.0)
    with pytest.raises(RuleError) as e:
        await m.set_mode(rid, "armed", OWNER, "x")
    assert e.value.code == "illegal_transition" and "simulate first" in e.value.message
    assert m.lifecycle.leaf(rid) == "draft"


async def test_same_mode_request_is_a_noop_without_audit() -> None:
    m, audits = _mgr()
    rid = await _armed(m)
    n = len(audits)
    out = await m.set_mode(rid, "armed", OWNER, "a-retry-with-new-key")
    assert out["mode"] == "armed" and len(audits) == n
    assert m.lifecycle.leaf(rid) == "armed"


async def test_same_mode_is_noop_after_restart() -> None:
    store = InMemoryRuleStore()
    m, _ = _mgr(store)
    rid = await _armed(m)
    fresh, audits = _mgr(store)  # new process: empty cache, chart rebuilt from the row
    await fresh.set_mode(rid, "armed", OWNER, "a")
    assert audits == [] and fresh.lifecycle.leaf(rid) == "armed"


async def test_replay_cache_is_actor_scoped_and_checks_visibility_first() -> None:
    m, _ = _mgr()
    acct = {"level": "account", "account_ids": ["00000000-0000-4000-8000-0000000000a2"]}
    rid = str((await m.create(_ir(scope=acct), OWNER))["id"])
    await m.set_mode(rid, "simulate", OWNER, "shared")
    with pytest.raises(RuleError) as e:
        await m.set_mode(rid, "simulate", MGR, "shared")
    assert e.value.status == 404


async def test_audit_failure_never_leaves_the_rule_armed() -> None:
    m, _ = _mgr()
    rid = str((await m.create(_ir(), OWNER))["id"])
    await m.set_mode(rid, "simulate", OWNER, "s")
    await m.record_simulation(rid, await _active_hash(m, rid), 5, 0.0)

    async def _down(_a: str, _p: dict[str, Any]) -> None:
        raise RuntimeError("audit down")

    m.set_hooks(audit=_down)
    with pytest.raises(RuntimeError):
        await m.set_mode(rid, "armed", OWNER, "a")
    row = await m._s.get(rid)
    assert row is not None and row.mode == "simulate"
    assert await m.lifecycle.current(rid, row.mode, None) == "simulating"  # rebuilt from row


async def test_arming_an_order_rule_needs_orders_write() -> None:
    m, _ = _mgr()
    acts = [{"node_id": "a1", "type": "cancel_all_orders", "params": {}}]
    rid = str((await m.create(_ir(actions=acts), OWNER))["id"])
    no_perm = Actor("u3", "s3", frozenset(), frozenset())
    (await m._row(rid)).owner = no_perm.user_id  # their own rule: only `orders:write` is missing
    await m.set_mode(rid, "simulate", OWNER, "s")
    await m.record_simulation(rid, await _active_hash(m, rid), 5, 0.0)
    with pytest.raises(RuleError) as e:
        await m.set_mode(rid, "armed", no_perm, "a")
    assert (e.value.status, e.value.code) == (403, "orders_write_required")


def test_delete_and_simulate_have_their_own_audit_verbs() -> None:
    assert _ACTIONS["rule.deleted"] == "rules.delete"
    assert _ACTIONS["rule.simulated"] == "rules.simulate"
    assert set(_ACTIONS.values()) <= AUDIT_ACTIONS


def test_mode_audit_carries_before_state() -> None:
    assert _before({"from": "simulate", "b9_from": "simulating"}) == {
        "mode": "simulate",
        "b9_state": "simulating",
    }
    assert _before({"rule_id": "r"}) is None


async def test_lifecycle_lru_is_bounded() -> None:
    lc = RuleLifecycle(max_charts=2)
    for rid in ("a", "b", "c"):
        await lc.current(rid, "simulate", None)
    assert lc.leaf("a") is None and lc.leaf("c") == "simulating"
    await lc.stop()
