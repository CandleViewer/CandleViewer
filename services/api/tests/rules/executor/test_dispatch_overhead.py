"""Performance: a rule fire's overhead up to its OMS submit call (E35-T11 slice 3c; the ticket's
performance note: at most 10 ms from the fire decision to the submit call, against budget #4's
300 ms submit-to-ack; #5231's carry from K1b; #5003's carry: `PostgresRuleStore.get` reads the
rule and its versions, two queries, for each dispatch-time point read).

From the fire's dispatch (`ActionExecutor.execute`) to the moment the OMS pipeline is called: check
1's point read through the rules manager over a store that makes that read as two awaited queries,
as `PostgresRuleStore.get` does; checks 2 to 8 over in-memory views; the records written ahead;
the handler's prepare and the order port's admission (the runtime's readiness and the anchor's
lookup). The ports answer at once, so this is the engine's own share, before any database or
network time, which CI's Postgres lane measures (`tests/integration/rules`).

`perf`-marked, so the unit lane deselects it and the `py-perf` job runs it without coverage; the
other perf tests' calibration (#1943): GC off around the timed rounds, a warm-up, and the fastest
round's p95 (host load only ever adds time)."""

from __future__ import annotations

import asyncio
import gc
import itertools
import json
import time
import uuid
from collections.abc import Coroutine
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.oms.idempotency import Fresh
from candleviewer.oms.submit import OrderRequest, SubmitContext, SubmitOutcome
from candleviewer.rules.executor.budget import OrderBudget
from candleviewer.rules.executor.dispatch import Fire
from candleviewer.rules.executor.engine import ActionExecutor, RowVerdict
from candleviewer.rules.executor.gates import Gates
from candleviewer.rules.executor.handlers import HANDLERS, bind_handlers
from candleviewer.rules.manager import InMemoryRuleStore, RuleRow, RulesManager
from candleviewer.rules.scope import ActionRequest
from candleviewer.rules.vocabulary import default_registry
from candleviewer.rules_oms_orders import rule_order_handlers
from tests.rules.executor.engine_rig import ACTOR, FIXTURE
from tests.rules.executor.request_builders import Principals, Records, Switches
from tests.rules.executor.test_order_handlers import NoHistory, request
from tests.unit.oms import command_rig as cr

pytestmark = pytest.mark.perf

ROUNDS = 3
FIRES = 50
#: The ticket's target, from the fire decision to the OMS submit call (p95).
BUDGET_NS = 10_000_000
_ANCHOR, _GROUP = uuid.UUID(int=0xA0), uuid.UUID(int=0xA1)
_RUNS = itertools.count(0x1000)  # each fire its own run, so each action its own fire key


class TwoQueryStore(InMemoryRuleStore):
    """A rule store whose point read is two awaited queries, the rule and then its versions, as
    `PostgresRuleStore.get` makes it (#5003's carry): `queries` counts them."""

    def __init__(self) -> None:
        super().__init__()
        self.queries = 0

    async def get(self, rule_id: str) -> RuleRow | None:
        for _ in ("rules", "rule_versions"):
            self.queries += 1
            await asyncio.sleep(0)  # each query a round trip to the loop, with no latency
        return await super().get(rule_id)


class Submits:
    """The OMS's pipeline, answering at once; `called` is when each submit call came in."""

    def __init__(self) -> None:
        self.called: list[int] = []

    async def submit(self, request: OrderRequest, context: SubmitContext) -> SubmitOutcome:
        self.called.append(time.perf_counter_ns())
        return SubmitOutcome(
            status=202, anchor_id=_ANCHOR, order_id=uuid.uuid4(), trade_group_id=_GROUP,
            lifecycle="submitted", notional_usd=Decimal("600"),
        )  # fmt: skip

    async def answer_replay(self, account_id: Any, replay: Any) -> SubmitOutcome:
        raise AssertionError("no fire here repeats a key")


class Anchors:
    async def lookup(self, created_by: uuid.UUID, client_ref: uuid.UUID, sha: str) -> Fresh:
        return Fresh()


class Runtime:
    readiness = "ok"

    def __init__(self) -> None:
        self.submission, self.anchors = Submits(), Anchors()

    def run(self, coro: Coroutine[Any, Any, SubmitOutcome]) -> asyncio.Task[SubmitOutcome]:
        return asyncio.ensure_future(coro)


async def _armed(manager: RulesManager, store: TwoQueryStore) -> str:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    raw["actions"] = [{"node_id": "a1", "type": "log_journal_tag", "params": {"tag": "t"}}]
    rule_id = str((await manager.create(raw, ACTOR))["id"])
    row = await store.get(rule_id)
    assert row is not None
    row.mode = "armed"
    return rule_id


def _executor(manager: RulesManager, runtime: Runtime) -> tuple[ActionExecutor, Records]:
    principals, records = Principals(frozenset({cr.ACCOUNT})), Records()
    handlers = rule_order_handlers(
        lambda: runtime, oms_enabled=lambda: True, principals=principals, positions=None
    )

    async def check_one(req: ActionRequest) -> RowVerdict:
        stored = await manager.current_mode(req.rule_id)
        return "armed" if stored is not None and stored.mode == "armed" else "mode_changed"

    executor = ActionExecutor(
        check_one=check_one, scope_check=lambda req: None,
        gates=Gates(switches=Switches(), principal=principals), records=records, audit=records,
        handlers=bind_handlers(HANDLERS, handlers),
        budget=OrderBudget(10_000, 100_000, rebuild=NoHistory()),  # never the limit here
    )  # fmt: skip
    return executor, records


async def _round(executor: ActionExecutor, rule_id: str, runtime: Runtime) -> list[int]:
    samples: list[int] = []
    emit = _emitter(executor)
    for _ in range(FIRES):
        req = replace(request(run=uuid.UUID(int=next(_RUNS))), rule_id=rule_id)
        fire = Fire(rule_id, req.run_id, (req,), emit)
        before = len(runtime.submission.called)
        started = time.perf_counter_ns()
        await executor.execute(fire)
        assert len(runtime.submission.called) == before + 1
        samples.append(runtime.submission.called[-1] - started)
    return samples


def _emitter(executor: ActionExecutor) -> Any:
    async def emit(req: ActionRequest) -> str | None:
        await executor.hand_over(req)
        return None

    return emit


def _p95(samples: list[int]) -> int:
    ordered = sorted(samples)
    return ordered[int(0.95 * (len(ordered) - 1))]


async def test_fire_to_submit_overhead_is_within_10_ms() -> None:
    store = TwoQueryStore()
    manager = RulesManager(store, default_registry())
    rule_id = await _armed(manager, store)
    runtime = Runtime()
    executor, records = _executor(manager, runtime)
    best = 0
    gc.collect()
    gc.disable()  # a collection inside one timed fire would skew the sample
    try:
        store.queries = 0
        await _round(executor, rule_id, runtime)  # warm-up: compiled models, the first lookups
        assert store.queries == 2 * FIRES  # each fire's check 1: the rule, then its versions
        for _ in range(ROUNDS):
            p95 = _p95(await _round(executor, rule_id, runtime))
            best = p95 if best == 0 else min(best, p95)
    finally:
        gc.enable()
    oks = [e for _, e in records.events if e.kind == "action_ok"]
    assert len(oks) == FIRES * (ROUNDS + 1)
    assert best <= BUDGET_NS, f"fire-to-submit p95 {best / 1e6:.2f} ms > 10 ms"
