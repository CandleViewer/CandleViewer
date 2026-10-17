"""E42-T04 S5 (#965): the rule steps of the user-disable cascade over the real rule engine.

`RuleDisarmAdapter` drives B9 DISARM through `RulesManager.set_mode`, so every transition goes
through the statechart gateway and the committed `rule_instance` chart and is audited by the
manager's own hook: these tests use the real manager, store and chart. `ScopeRefreshAdapter`
refreshes the rule engine's scope snapshot and fails closed. The calling service is covered in
`tests/unit/admin/test_user_disable.py`, the readers behind O5 in `tests/integration/storage/`.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleError, RulesManager
from candleviewer.rules.scope_state import ARM_LIVE, SnapshotScopeState
from candleviewer.rules.vocabulary import default_registry
from candleviewer.user_cascade_wiring import (
    RuleDisarmAdapter,
    RulesNotRunning,
    ScopeRefreshAdapter,
    disarm_key,
)
from tests.rules.test_rules_manager import _active_hash, _ir

_T0 = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
_A, _B, _OWNER = uuid.UUID(int=0xA), uuid.UUID(int=0xB), uuid.UUID(int=0xC)
_ACCOUNT = uuid.UUID(int=0x10)


def _actor(user: uuid.UUID) -> Actor:
    return Actor(str(user), "s1", frozenset({ARM_LIVE}), is_owner=True, step_up_fresh=True)


class _Engine:
    """The real rule engine: `RulesManager` over an in-memory store, whose B9 charts the
    statechart factory builds, and the adapter over that same store and manager."""

    def __init__(self) -> None:
        self.audits: list[tuple[str, dict[str, Any]]] = []
        self.store = InMemoryRuleStore()
        self.manager: RulesManager
        self.adapter: RuleDisarmAdapter
        self.restart()

    def restart(self) -> None:
        """A manager with no chart in memory (a new process): each is rebuilt from its row."""

        async def audit(action: str, payload: dict[str, Any]) -> None:
            self.audits.append((action, payload))

        self.manager = RulesManager(self.store, default_registry(), audit=audit)
        self.adapter = RuleDisarmAdapter(self.store, lambda: self.manager)

    async def rule(self, user: uuid.UUID, name: str, mode: str = "armed", **ir: Any) -> str:
        """A rule of `user` taken as far as `mode`: a draft (`disabled`), `simulate` or `armed`.
        `ir` overrides fields of the notification rule's IR (a scope)."""
        rid = str((await self.manager.create(_ir(name=name, **ir), _actor(user)))["id"])
        if mode != "disabled":
            await self.manager.set_mode(rid, "simulate", _actor(user), f"sim-{name}")
        if mode == "armed":
            await self.manager.record_simulation(rid, await _active_hash(self.manager, rid), 5, 0)
            await self.manager.set_mode(rid, "armed", _actor(user), f"arm-{name}")
        return rid

    async def mode(self, rid: str) -> tuple[str, str | None]:
        row = await self.store.get(rid)
        assert row is not None
        return row.mode, row.disabled_reason

    async def disarm(self, rid: str, at: datetime = _T0) -> None:
        await self.adapter.disarm(rid, user_id=_A, actor=_OWNER, disabled_at=at)

    def disarmed(self) -> list[tuple[str, str, str]]:  # the audited disarms: rule, actor, event
        records = [p for a, p in self.audits if a == "rule.disarmed"]
        return sorted((p["rule_id"], p["actor"], p["b9_event"]) for p in records)


async def test_disarms_owner_user_id_rules() -> None:
    """SR-029, AC1: exactly the live armed rules whose owner is the user are disarmed, each by B9
    DISARM on a chart rebuilt from its row (a new process) and audited once with the acting
    Owner; another owner's armed rule, the user's simulating rule and draft, and a deleted row
    that is still `armed` stay as they were and are not listed. One of the user's rules is
    account-scoped: the manager hides a rule that references an account from an actor without
    grants (404, `rule.scope_refused`, left armed) and shows the Owner every rule, so a disarm
    that does not act as the Owner fails here."""
    e = _Engine()
    account = {"level": "account", "account_ids": [str(_ACCOUNT)], "environments": ["demo"]}
    mine = [await e.rule(_A, "a-one"), await e.rule(_A, "a-acct", scope=account)]
    theirs, sim = await e.rule(_B, "b-one"), await e.rule(_A, "a-sim", "simulate")
    draft, gone = await e.rule(_A, "a-draft", "disabled"), await e.rule(_A, "a-gone")
    row = await e.store.get(gone)
    assert row is not None
    row.deleted = True
    await e.store.put(row)
    e.restart()
    assert await e.adapter.armed_rule_ids(_A) == tuple(sorted(mine))
    for rid in mine:
        await e.disarm(rid)
        assert await e.mode(rid) == ("disabled", "disarmed")
        assert e.manager.lifecycle.leaf(rid) == "disarmed"
    assert [await e.mode(r) for r in (theirs, sim, draft)] == [
        *(("armed", None), ("simulate", None), ("disabled", None)),
    ]
    assert e.disarmed() == sorted((rid, str(_OWNER), "DISARM") for rid in mine)
    assert "rule.scope_refused" not in [action for action, _ in e.audits]
    assert await e.adapter.armed_rule_ids(_A) == ()
    assert await e.adapter.armed_rule_ids(_B) == (theirs,)


async def test_disarm_of_a_rule_the_chart_refuses_raises_and_leaves_it_armed() -> None:
    """B9 handles DISARM in `armed`, `cooling_down` and `paused_degraded` only (28 §B9.3): a rule
    that is evaluating is refused, never parked to fire later (CV-C06). The adapter lets the
    refusal out, so the cascade counts a failed step, and names the rule in the log; O4 and O5
    hold the rule meanwhile. (Nothing yet sends TRIGGER outside tests, so none evaluates.)"""
    e = _Engine()
    rid = await e.rule(_A, "a-one")
    await e.manager.lifecycle.send(rid, "TRIGGER")
    assert e.manager.lifecycle.leaf(rid) == "evaluating"  # no await has yielded to its service
    with capture_logs() as logs, pytest.raises(RuleError) as refused:
        await e.disarm(rid)
    assert (refused.value.status, refused.value.code) == (422, "illegal_transition")
    assert await e.mode(rid) == ("armed", None)
    (line,) = [entry for entry in logs if entry["event"] == "users.disable.rule_not_disarmed"]
    assert (line["rule_id"], line["target_user_id"], line["code"]) == (
        *(rid, str(_A), "illegal_transition"),
    )
    assert line["log_level"] == "error" and line["error"] == "RuleError"


def test_idempotency_key_deterministic() -> None:
    """The key is a pure function of (user, rule, disable instant): a disable always sends the
    same key, whatever the zone of its instant, and no two users, rules or disables share one."""
    key = disarm_key(_A, "rule-1", _T0)
    assert key == disarm_key(_A, "rule-1", _T0.astimezone(timezone(timedelta(hours=2))))
    assert str(_A) in key and "rule-1" in key
    others = [disarm_key(_B, "rule-1", _T0), disarm_key(_A, "rule-2", _T0)]
    others.append(disarm_key(_A, "rule-1", _T0 + timedelta(microseconds=1)))
    assert len({key, *others}) == 4


async def test_a_later_disable_disarms_a_rule_that_was_armed_again() -> None:
    """The key carries the disable's instant: `RulesManager` replays the first answer for a key it
    has seen (per process), so a key of (user, rule) alone would let a second disable of the same
    user skip a rule that was enabled and armed again in between."""
    e = _Engine()
    rid = await e.rule(_A, "a-one")
    await e.disarm(rid)
    await e.manager.set_mode(rid, "armed", _actor(_A), "arm-again")  # E42-T09 enable, then arm
    assert await e.mode(rid) == ("armed", None)
    await e.disarm(rid, at=_T0 + timedelta(hours=1))
    assert await e.mode(rid) == ("disabled", "disarmed")
    assert [rule for rule, _, _ in e.disarmed()] == [rid, rid]


async def test_a_rule_already_disarmed_is_a_noop_that_audits_nothing() -> None:
    """A repeat that finds a rule disarmed is silent: `set_mode` to the mode a rule is in writes
    no event and no record, so re-driving a cascade after the first has finished cannot write a
    second one (AC5); overlapping repeats are the next test."""
    e = _Engine()
    rid = await e.rule(_A, "a-one")
    await e.disarm(rid)
    before = list(e.audits)
    await e.disarm(rid, at=_T0 + timedelta(minutes=1))
    assert e.audits == before and await e.mode(rid) == ("disabled", "disarmed")


async def test_overlapping_disarms_of_one_rule_write_one_record_and_park_nothing() -> None:
    """AC5 makes a repeat of the DELETE legal while the first cascade still runs (a double submit,
    a client retry), so two disarms of one rule can overlap. `RulesManager.set_mode` has no
    per-rule lock: unserialised, both pass `RuleLifecycle.handled_event` while the chart is armed
    and both send DISARM, the second lands in `disarmed` and is parked by `onUnhandled: defer`
    (CV-C06), and both write `rule.disarmed`. The adapter serialises them, so the second finds
    the rule disarmed and is `set_mode`'s state-based no-op: one record, nothing parked, and the
    rule arms again the first time it is asked to."""
    e = _Engine()
    rid = await e.rule(_A, "a-one")
    later = _T0 + timedelta(milliseconds=3)  # a different key: only the lock can stop the second
    await asyncio.gather(e.disarm(rid), e.disarm(rid, at=later))
    assert e.disarmed() == [(rid, str(_OWNER), "DISARM")]
    assert e.manager.lifecycle._charts[rid].deferred_count == 0
    await e.manager.set_mode(rid, "armed", _actor(_A), "arm-again")  # E42-T09 enable, then arm
    assert await e.mode(rid) == ("armed", None)


async def test_rules_module_not_running_is_a_failed_disarm() -> None:
    """`RulesService.manager()` is `None` while the module is stopped: nothing can be disarmed,
    and that is said, not skipped."""
    adapter = RuleDisarmAdapter(InMemoryRuleStore(), lambda: None)
    with pytest.raises(RulesNotRunning):
        await adapter.disarm("rule-1", user_id=_A, actor=_OWNER, disabled_at=_T0)


class _Source:
    """`ScopeSource`: one granted account and the live-arming code; `disabled` answers as the
    store does once the user is disabled (grant soft-revoked, O4; no permission, O5). `fail`
    names a read that raises (`grants`, `permissions`) or hangs (`hang-grants`, ...)."""

    def __init__(self) -> None:
        self.fail: str | None = None
        self.disabled = False

    async def load_grants(self, owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
        await self._maybe_fail("grants")
        return [(_ACCOUNT, not self.disabled, False)]

    async def load_permissions(self, owner: uuid.UUID) -> frozenset[str]:
        await self._maybe_fail("permissions")
        return frozenset() if self.disabled else frozenset({ARM_LIVE})

    async def _maybe_fail(self, read: str) -> None:
        if self.fail == f"hang-{read}":
            await asyncio.Event().wait()
        if self.fail == read:
            raise OSError("scope source down")


@pytest.mark.parametrize("fail", ["grants", "permissions", "hang-grants", "hang-permissions"])
async def test_scope_refresh_failure_fails_closed(fail: str) -> None:
    """C-2.21, O5: a refresh that fails (a read raising, or one that hangs until the step's bound
    cuts it) leaves the snapshot with no grant and no live-arming permission, never the old
    ones; the error still reaches the cascade, which counts and alerts the failed step."""
    source = _Source()
    state = SnapshotScopeState(source, "demo")
    await state.refresh(_A)
    assert state.granted_accounts(_A) == {_ACCOUNT} and state.can_arm_live(_A)  # a held entry
    source.fail = fail
    adapter = ScopeRefreshAdapter(lambda: state)
    if fail.startswith("hang"):
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0):  # cut at the first read that hangs
                await adapter.refresh(_A)
    else:
        with pytest.raises(OSError, match="scope source down"):
            await adapter.refresh(_A)
    assert state.granted_accounts(_A) == frozenset() and not state.can_arm_live(_A)


async def test_scope_refresh_without_scope_wiring_has_nothing_to_refresh() -> None:
    """On the fake backend no scope state exists (`RulesService.scope_state` is `None`): the
    rule engine there acts on nothing scoped (501), so there is nothing cached to refresh."""
    await ScopeRefreshAdapter(lambda: None).refresh(_A)
