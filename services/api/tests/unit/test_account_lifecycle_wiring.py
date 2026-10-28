"""#898 B3b1 (E27-S04): the rule disarm that follows an account's disable, delete or last-key
revoke, over the real rule engine (`RulesManager`, `InMemoryRuleStore`, the B9 chart).

It disarms what the R10 predicate lists, a global rule included (ruling 1), acting as the Owner
but recording the initiating actor and role with `executed_as: owner` and the rule's `scope`
(rulings 1, 2). A rule already disarmed is a no-op with no record; one whose active version no
longer covers the account is skipped (SEC-02). A failure never stops the others: each is logged,
one critical page names `account.rule_not_disarmed`, and the answer lists it as not disarmed
(ruling 3). Neither a failing logger nor a failing pager makes it raise (CR-01); a cancellation
passes through (CR-03); the key names the action's instant (CR-02).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.account_lifecycle_wiring import (
    PAGE_EVENT,
    AccountRuleDisarmer,
    Disarmed,
    account_disarm_key,
    coverage,
)
from candleviewer.accounts.consequences import ARMED_LISTED
from candleviewer.accounts.profile_repository import ArmedRule
from candleviewer.rules.manager import Actor, InMemoryRuleStore, RuleRow, RulesManager, VersionRow
from candleviewer.rules.scope_state import ARM_LIVE
from candleviewer.rules.vocabulary import default_registry
from tests.rules.test_rules_manager import _active_hash, _ir

T0 = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
ACC, OTHER = uuid.UUID(int=0x10), uuid.UUID(int=0x20)
OWNER, MANAGER = uuid.UUID(int=0xC), uuid.UUID(int=0xD)
GLOBAL = {"level": "global", "environments": ["demo"]}
MINE = {"level": "account", "account_ids": [str(ACC)], "environments": ["demo"]}
THEIRS = {"level": "account", "account_ids": [str(OTHER)], "environments": ["demo"]}


class _Covering:
    """The R10 listing as the store's predicate gives it: a fixed list, or a failure."""

    def __init__(self) -> None:
        self.rules: list[ArmedRule] = []
        self.fault: Exception | None = None
        self.asked: list[tuple[uuid.UUID, int]] = []

    async def covering(self, account_id: uuid.UUID, *, limit: int) -> tuple[ArmedRule, ...]:
        self.asked.append((account_id, limit))
        if self.fault is not None:
            raise self.fault
        return tuple(self.rules[:limit])


class _Pager:
    def __init__(self, fault: bool = False) -> None:
        self.pages: list[tuple[str, str, str]] = []
        self.fault = fault

    def raise_alert(self, severity: Any, summary: str, *, machine_kind: str) -> None:
        if self.fault:
            raise RuntimeError("pager down")
        self.pages.append((severity, summary, machine_kind))


class _Engine:
    """The real manager over an in-memory store, and the disarmer over both."""

    def __init__(self, *, pager_fault: bool = False) -> None:
        self.audits: list[tuple[str, dict[str, Any]]] = []
        self.store = InMemoryRuleStore()
        self.covering = _Covering()
        self.pager = _Pager(pager_fault)

        async def audit(action: str, payload: dict[str, Any]) -> None:
            self.audits.append((action, payload))

        self.manager: RulesManager | None = RulesManager(
            self.store, default_registry(), audit=audit
        )
        self.disarmer = AccountRuleDisarmer(
            self.covering, self.store, lambda: self.manager, self.pager
        )

    async def rule(self, name: str, scope: dict[str, Any], *, listed: bool = True) -> str:
        """An armed rule of the Owner with `scope`, listed by the predicate unless not."""
        manager = self.manager
        assert manager is not None
        actor = Actor(str(OWNER), "s1", frozenset({ARM_LIVE}), is_owner=True, step_up_fresh=True)
        rid = str((await manager.create(_ir(name=name, scope=scope), actor))["id"])
        await manager.set_mode(rid, "simulate", actor, f"sim-{name}")
        await manager.record_simulation(rid, await _active_hash(manager, rid), 5, 0)
        await manager.set_mode(rid, "armed", actor, f"arm-{name}")
        if listed:
            self.covering.rules.append(ArmedRule(uuid.UUID(rid), name))
        return rid

    async def mode(self, rid: str) -> str:
        row = await self.store.get(rid)
        assert row is not None
        return row.mode

    async def disarm(self, at: datetime = T0, lifecycle: Any = "account_disabled") -> Disarmed:
        return await self.disarmer.disarm(
            ACC, lifecycle=lifecycle, actor=MANAGER, role="manager", at=at
        )

    def records(self) -> list[dict[str, Any]]:
        return [p for a, p in self.audits if a == "rule.disarmed"]


async def test_it_disarms_every_listed_rule_global_ones_included_and_records_their_scope() -> None:
    e = _Engine()
    one, every = await e.rule("one", MINE), await e.rule("every", GLOBAL)
    assert await e.disarm() == Disarmed(("one", "every"), ())
    assert [await e.mode(r) for r in (one, every)] == ["disabled", "disabled"]
    got = {p["rule_id"]: (p["scope"], p["scope_level"]) for p in e.records()}
    assert got == {one: ("account", "account"), every: ("global", "global")}
    assert e.covering.asked == [(ACC, ARMED_LISTED + 1)]
    assert e.pager.pages == []


async def test_the_record_keeps_the_initiating_actor_and_role_executed_as_the_owner() -> None:
    """Ruling 2 (C-2.9): a Manager's disable is executed as the Owner, never hidden behind it."""
    e = _Engine()
    await e.rule("one", MINE)
    await e.disarm()
    (record,) = e.records()
    assert (record["actor"], record["actor_role"], record["executed_as"]) == (
        str(MANAGER),
        "manager",
        "owner",
    )
    assert record["b9_event"] == "DISARM"


async def test_the_broadcast_and_other_records_carry_no_disarm_fields() -> None:
    """`record` adds to the disarm's audit record only; an arm's record has none of them."""
    e = _Engine()
    await e.rule("one", MINE)
    await e.disarm()
    armed = [p for a, p in e.audits if a == "rule.armed"]
    assert armed and all("executed_as" not in p and p["scope"] == "account" for p in armed)


async def test_a_rule_already_disarmed_is_a_noop_that_records_nothing() -> None:
    e = _Engine()
    await e.rule("one", MINE)
    await e.disarm()
    assert await e.disarm(T0 + timedelta(minutes=1)) == Disarmed(("one",), ())
    assert len(e.records()) == 1


async def test_a_rule_no_longer_covering_the_account_or_gone_is_skipped() -> None:
    """SEC-02: the row is read again under the rule's lock: a new active version that left the
    account meanwhile is not disarmed, nor is a deleted row."""
    e = _Engine()
    theirs = await e.rule("theirs", THEIRS)  # listed, as if its version changed after the read
    gone = await e.rule("gone", MINE)
    row = await e.store.get(gone)
    assert row is not None
    row.deleted = True
    await e.store.put(row)
    with capture_logs() as logs:
        assert await e.disarm() == Disarmed((), ())
    assert await e.mode(theirs) == "armed" and e.records() == [] and e.pager.pages == []
    skipped = [x["rule_id"] for x in logs if x["event"] == "accounts.rule_disarm_skipped"]
    assert skipped == [theirs, gone]


async def test_a_failure_pages_once_continues_and_lists_the_rule_not_disarmed() -> None:
    """Ruling 3: the B9 chart refuses an evaluating rule; the next rule is still disarmed."""
    e = _Engine()
    busy, calm = await e.rule("busy", MINE), await e.rule("calm", GLOBAL)
    assert e.manager is not None
    await e.manager.lifecycle.send(busy, "TRIGGER")
    with capture_logs() as logs:
        assert await e.disarm() == Disarmed(("calm",), ("busy",))
    assert await e.mode(busy) == "armed" and await e.mode(calm) == "disabled"
    ((severity, summary, kind),) = e.pager.pages
    assert severity == "page" and kind == "rule_instance" and summary.startswith(PAGE_EVENT)
    (line,) = [x for x in logs if x["event"] == PAGE_EVENT]
    assert (line["rule_id"], line["code"], line["log_level"]) == (
        busy,
        "illegal_transition",
        "error",
    )


async def test_a_stopped_rules_module_is_a_failed_disarm_of_every_rule() -> None:
    e = _Engine()
    await e.rule("one", MINE)
    e.manager = None
    assert await e.disarm() == Disarmed((), ("one",))
    assert len(e.pager.pages) == 1


async def test_an_unread_listing_pages_and_answers_nothing_listed() -> None:
    e = _Engine()
    e.covering.fault = RuntimeError("store down")
    assert await e.disarm() == Disarmed((), (), listed=False)
    assert len(e.pager.pages) == 1 and PAGE_EVENT in e.pager.pages[0][1]


async def test_more_rules_than_one_listing_holds_disarms_those_listed_and_pages() -> None:
    e = _Engine()
    await e.rule("one", MINE)
    e.covering.rules *= ARMED_LISTED + 1  # the listing overflows its bound
    got = await e.disarm()
    assert got.listed is False and got.failed == () and len(got.disarmed) == ARMED_LISTED
    assert len(e.pager.pages) == 1 and "rest not listed" in e.pager.pages[0][1]


async def test_no_armed_rule_answers_success_with_no_page() -> None:
    """CR-03."""
    e = _Engine()
    assert await e.disarm() == Disarmed((), ())
    assert e.pager.pages == []


async def test_neither_a_failing_logger_nor_a_failing_pager_makes_it_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-01: a logger that fails never withholds the page, and a pager that fails is lost
    quietly."""

    def fault(*_args: object, **_fields: object) -> None:
        raise RuntimeError("a structlog processor fault")

    broken = SimpleNamespace(error=fault, critical=fault, info=fault)
    monkeypatch.setattr("candleviewer.account_lifecycle_wiring._log", lambda: broken)
    e = _Engine()
    await e.rule("one", MINE)
    e.manager = None
    assert await e.disarm() == Disarmed((), ("one",))
    assert len(e.pager.pages) == 1  # the log line failed; the page still went
    quiet = _Engine(pager_fault=True)
    quiet.covering.fault = RuntimeError("store down")
    assert await quiet.disarm() == Disarmed((), (), listed=False)


async def test_a_cancellation_passes_through_the_listing_and_each_disarm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CR-03: `except Exception`, never `BaseException`, around the listing and each rule."""
    e = _Engine()
    e.covering.fault = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await e.disarm()
    e.covering.fault = None
    await e.rule("one", MINE)

    async def cancelled(*_args: Any, **_kw: Any) -> dict[str, Any]:
        raise asyncio.CancelledError

    assert e.manager is not None
    monkeypatch.setattr(e.manager, "set_mode", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await e.disarm()
    assert e.pager.pages == []


async def test_a_later_disable_disarms_a_rule_armed_again_since() -> None:
    """CR-02: the key names the action's instant, so `set_mode`'s replay of a seen key never
    skips a rule the Owner re-armed between two disables."""
    e = _Engine()
    rid = await e.rule("one", MINE)
    await e.disarm()
    assert e.manager is not None
    actor = Actor(str(OWNER), "s1", frozenset({ARM_LIVE}), is_owner=True, step_up_fresh=True)
    await e.manager.set_mode(rid, "armed", actor, "arm-again")  # the Owner re-arms it
    assert await e.mode(rid) == "armed"
    await e.disarm(T0 + timedelta(seconds=1))
    assert await e.mode(rid) == "disabled" and len(e.records()) == 2


def test_the_disarm_key_names_the_action_the_account_the_rule_and_the_instant() -> None:
    rule = str(uuid.UUID(int=0x11))
    key = account_disarm_key("account_disabled", ACC, rule, T0)
    assert key == account_disarm_key("account_disabled", ACC, rule.upper(), T0)
    assert T0.strftime("%Y%m%dT%H%M%S%fZ") in key
    others = {
        account_disarm_key("key_revoked", ACC, rule, T0),
        account_disarm_key("account_disabled", OTHER, rule, T0),
        account_disarm_key("account_disabled", ACC, str(uuid.UUID(int=0x12)), T0),
        account_disarm_key("account_disabled", ACC, rule, T0 + timedelta(microseconds=1)),
    }
    assert key not in others and len(others) == 4


@pytest.mark.parametrize(
    ("listed", "expected"),
    [
        (None, "global"),
        ([], "global"),
        ([str(ACC)], "account"),
        ([str(OTHER), str(ACC).upper()], "account"),
        (["not-a-uuid"], "account"),  # `_ARMED_ON` counts it covering: fail closed
        ([7], "account"),
        ([str(OTHER)], None),
    ],
)
def test_coverage_mirrors_the_armed_on_predicate(listed: Any, expected: Any) -> None:
    scope: dict[str, Any] = {"level": "account"}
    if listed is not None:
        scope["account_ids"] = listed
    version = VersionRow("v1", "r1", 1, {"scope": scope}, "h", "c", "", "", "")
    row = RuleRow("r1", "n", str(OWNER), mode="armed", active_version_id="v1", versions=[version])
    assert coverage(row, ACC) == expected
    assert coverage(None, ACC) is None
    row.active_version_id = None
    assert coverage(row, ACC) is None


def test_the_manager_refuses_a_record_field_outside_the_disarm_extras() -> None:
    manager = RulesManager(InMemoryRuleStore(), default_registry())
    actor = Actor(str(OWNER), "s1", is_owner=True)
    with pytest.raises(ValueError, match="scope, executed_as and actor_role"):
        asyncio.run(manager.set_mode("r", "disabled", actor, "k", record={"actor": "x"}))
