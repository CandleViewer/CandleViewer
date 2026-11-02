"""E35-T11 slice 3c: the rules service keeps check 5's principal reads fresh (24 §11.5 "The
principal"; BQ-6 of #5003 as ruled).

A bound principal port that refreshes itself (`PrincipalRefresh`, the composition root's
`RulePrincipals`) is started with the evaluator, naming the users to read, and stopped with the
module; the users are the owners of the rules the evaluator holds, so an owner is read before
its rule is armed, and the armers of the armed ones, as of the evaluator's last work list. A port
with no refresh of its own is bound as before. The runner is driven by hand, never its task."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Callable, Collection
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.rules import service as rules_service
from candleviewer.rules.executor.ports import PrincipalRefresh
from candleviewer.rules.manager import InMemoryRuleStore, RulesManager
from candleviewer.rules.runner import EvalTick, RuleEvaluationRunner
from candleviewer.rules.service import RulesService
from tests.rules.executor.engine_rig import ACTOR, FIXTURE
from tests.rules.executor.request_builders import Principals, Records, Switches
from tests.rules.test_evaluator import Clock
from tests.rules.test_scope_wiring import OWNER, Source
from tests.rules.test_scope_wiring import A as ACCOUNT

ARMER, OTHER = uuid.UUID(int=0xA2), uuid.UUID(int=0xA3)


@dataclass
class Refreshed(Principals):
    """A `PrincipalRefresh` in memory: the users it is told to read, its starts and its stops."""

    starts: list[Callable[[], Collection[uuid.UUID]]] = field(default_factory=list)
    stops: int = 0

    def start(self, users: Callable[[], Collection[uuid.UUID]]) -> None:
        self.starts.append(users)

    async def stop(self) -> None:
        self.stops += 1


async def _service(
    principal: Principals, monkeypatch: pytest.MonkeyPatch
) -> tuple[RulesService, RulesManager, InMemoryRuleStore]:
    clock = Clock()
    monkeypatch.setattr(rules_service, "default_clocks", lambda: (clock, clock))
    monkeypatch.setattr(RuleEvaluationRunner, "start", lambda self: None)  # driven by hand

    async def audit(_event: str, _data: dict[str, Any]) -> None:
        return None

    store, records = InMemoryRuleStore(), Records()
    svc = RulesService()
    svc.bind(store=store, audit=audit, records=(records, records), switches=Switches())
    svc.bind(principal=principal)
    svc.wire_scope(Source(), "demo", audit)
    ctx: Any = SimpleNamespace(settings=SimpleNamespace(rules_evaluator_enabled=True))
    await svc.start(ctx)
    manager = svc.manager()
    assert manager is not None
    return svc, manager, store


async def _rule(
    manager: RulesManager, store: InMemoryRuleStore, *, owner: uuid.UUID, mode: str,
    armed_by: uuid.UUID | None = None,
) -> None:  # fmt: skip
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["name"] = f"rule-{len(await store.all())}"
    raw["scope"] = {"level": "account", "account_ids": [str(ACCOUNT)], "symbols": ["BTCUSDT"]}
    raw["actions"] = [{"node_id": "a1", "type": "log_journal_tag", "params": {"tag": "t"}}]
    rid = str((await manager.create(raw, ACTOR))["id"])
    row = await store.get(rid)
    assert row is not None
    row.owner, row.mode = str(owner), mode
    row.armed_by = None if armed_by is None else str(armed_by)


@pytest.fixture
async def refreshed(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[Refreshed, RulesService, RulesManager, InMemoryRuleStore]]:
    principal = Refreshed(frozenset({ACCOUNT}))
    svc, manager, store = await _service(principal, monkeypatch)
    try:
        yield principal, svc, manager, store
    finally:
        await svc.stop(1.0)


async def test_the_service_starts_the_refresh_with_the_evaluator_and_stops_it_with_the_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    principal = Refreshed(frozenset({ACCOUNT}))
    assert isinstance(principal, PrincipalRefresh)
    svc, _, _ = await _service(principal, monkeypatch)
    assert len(principal.starts) == 1 and principal.starts[0] == svc.principal_users
    assert principal.stops == 0
    await svc.stop(1.0)
    assert principal.stops == 1


async def test_the_refresh_reads_the_owners_and_the_armers_of_the_rules_the_evaluator_holds(
    refreshed: tuple[Refreshed, RulesService, RulesManager, InMemoryRuleStore],
) -> None:
    """BQ-6: the users read are the owners of the rules the evaluator holds (an owner is read
    before its rule is armed) and the armers of the armed ones, as of its last work list; a rule
    that is not evaluated (disabled) names no one, and an armer that is no id is left out."""
    principal, svc, manager, store = refreshed
    assert svc.principal_users() == frozenset()
    await _rule(manager, store, owner=OWNER, mode="armed", armed_by=ARMER)
    await _rule(manager, store, owner=OTHER, mode="simulate")
    await _rule(manager, store, owner=uuid.UUID(int=0xA9), mode="disabled")
    runner = svc.runner
    assert runner is not None
    await runner.process(EvalTick("on_price_update", "BTCUSDT"))
    assert svc.principal_users() == frozenset({OWNER, ARMER, OTHER})
    assert principal.starts[0]() == frozenset({OWNER, ARMER, OTHER})
    [armed] = [r for r in await store.all() if r.mode == "armed"]
    armed.armed_by = "not-a-user-id"
    await runner.process(EvalTick("on_price_update", "BTCUSDT"))
    assert svc.principal_users() == frozenset({OWNER, OTHER})


async def test_a_principal_port_with_no_refresh_of_its_own_is_bound_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plain = Principals(frozenset({ACCOUNT}))
    assert not isinstance(plain, PrincipalRefresh)
    svc, _, _ = await _service(plain, monkeypatch)
    await svc.stop(1.0)  # nothing to start or stop: the reads are served as bound
