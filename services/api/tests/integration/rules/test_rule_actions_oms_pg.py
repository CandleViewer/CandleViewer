"""Integration: a rule fire's entries through the OMS pipeline on real Postgres 16 (E35-T11 slice
3c; G "Recorded exchange answers are handled (integration)"; 24 §11.5, §11.7, §11.9; BQ-5 and
BQ-8 of #5003 as ruled).

The executor writes its records ahead on Postgres (`RuleRunRecords` over the rules repository: the
fire's run row, its events, its close) and hands each entry to the composition root's handler,
whose order port runs the C6 pipeline (`test_submission_pipeline_pg.py`, shared by import): B1's
facade, its step writer and the command port over the Postgres stores, with a demo
`FakeTradingPort` as the exchange (C-13.5: no venue is reached).

**Derived, not evidence.** No recorded demo capture of an order-path reply exists yet (every
order-path file under `packages/fixtures/bybit/2026-10-05/` is `docs-transcribed`;
`rest/error_10018.json` is a documented-shape corpus file; no `10001` text is documented; no
capture holds a partial fill or a private-stream drop), as `test_private_stream_replay_pg.py`
labels its rows: the `10001` rejection is the port's typed rejection with that code, the `10018`
the adapter's mapped `RateLimitError` (`exchange.bybit.mapping`), the partial fill B1's `EXEC`
event shaped as the transcribed execution frame is, and the drop the fake private stream's end.
E29-K01 (#843) runs these rows again against its recordings once the owner's demo key exists.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any, cast

import pytest

from candleviewer.exchange.base.errors import OmsErrorCode, RateLimitError
from candleviewer.exchange.base.fakes import FakeReject
from candleviewer.oms.submit import OrderRequest, SubmitContext, SubmitOutcome
from candleviewer.rules.executor.budget import OrderBudget
from candleviewer.rules.executor.dispatch import Fire
from candleviewer.rules.executor.engine import ActionExecutor, RowVerdict
from candleviewer.rules.executor.gates import Gates
from candleviewer.rules.executor.handlers import HANDLERS, bind_handlers
from candleviewer.rules.ir.models import Action, RuleLimits, RuleScope
from candleviewer.rules.manager import RulesManager
from candleviewer.rules.scope import ActionRequest, ScopeInstanceRef
from candleviewer.rules.vocabulary import default_registry
from candleviewer.rules_oms_orders import rule_order_handlers
from candleviewer.rules_oms_wiring import RuleNotionalRebuild, RuleRunRecords
from candleviewer.rules_store_pg import PostgresRuleStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.rules_sqlalchemy import SqlAlchemyRulesRepository
from candleviewer.storage.repositories.scope_sqlalchemy import SqlAlchemyScopeSource
from tests.integration.oms.test_rule_origin_submit_pg import _entry_row, _stops
from tests.integration.oms.test_submission_pipeline_pg import (
    Rig,
    _fills,
    _login,
    _order,
    _orders,
    _sql,
    pg,
    pg_dsn,
    rel,
)
from tests.rules.executor.native_sl import assert_entry_carries_native_stop
from tests.rules.executor.request_builders import Principals, Records, Switches, action_request
from tests.rules.executor.test_order_handlers import Lookups, NoHistory, Recorded, Runtime
from tests.unit.oms import command_rig as cr

pytestmark = pytest.mark.integration
__all__ = ["pg", "pg_dsn", "rel"]  # C6's database, its pool and its pipeline, for this module

GUARD_S = 30.0
MARKET: dict[str, Any] = {"side": "buy", "order_type": "market", "qty_mode": "profile"}


def _rule(dsn: str, owner: uuid.UUID) -> tuple[str, str]:
    """A rule of `owner` and its first version, as the run row's and the group's FKs need them;
    the executor writes the fire's run row itself."""
    rule, version = uuid.uuid4(), uuid.uuid4()
    _sql(
        dsn, "INSERT INTO rules (id, name, owner_user_id) VALUES (%s, %s, %s)", rule, str(rule),
        owner,
    )  # fmt: skip
    _sql(
        dsn,
        "INSERT INTO rule_versions (id, rule_id, version, ir, ir_hash, compiler_version) "
        "VALUES (%s, %s, 1, '{\"conditions\": [], \"actions\": []}', repeat('ab', 32), 'v1')",
        version, rule,
    )  # fmt: skip
    return str(rule), str(version)


class Fires:
    """One executor over the C6 pipeline (module docstring), the rule `rule` of `pg.user`; check 1
    answers armed unless a test hands its own read."""

    def __init__(
        self,
        pg: Rig,
        rel: SqlAlchemyRelationalRepository,
        dsn: str,
        check_one: Callable[[ActionRequest], Any] | None = None,
    ) -> None:
        self.pg, self.dsn = pg, dsn
        self.rule, self.version = _rule(dsn, pg.user)
        self.runtime = Runtime(None, None)
        self.lookups = Lookups(pg.pipeline._anchors)
        self.runtime.submission = Recorded(pg.pipeline, self.runtime)
        self.runtime.anchors = self.lookups
        self.audits = Records()
        principals = Principals(frozenset({pg.account}))
        handlers = rule_order_handlers(
            lambda: self.runtime, oms_enabled=lambda: True, principals=principals,
            positions=None,
        )  # fmt: skip
        self.repository = SqlAlchemyRulesRepository(rel)
        self.executor = ActionExecutor(
            check_one=check_one or self.check_one, scope_check=lambda req: None,
            gates=Gates(switches=Switches(), principal=principals), records=RuleRunRecords(
                self.repository), audit=self.audits, handlers=bind_handlers(HANDLERS, handlers),
            budget=OrderBudget(rebuild=NoHistory()),
        )  # fmt: skip

    async def check_one(self, req: ActionRequest) -> RowVerdict:
        return "armed"

    async def emit(self, req: ActionRequest) -> str | None:
        await self.executor.hand_over(req)
        return None

    def request(self, node: str, params: dict[str, Any], run: uuid.UUID, **action: Any) -> Any:
        payload = Action.model_validate(
            {"node_id": node, "type": "place_order", "params": params} | action
        )
        account = self.pg.account
        instance = ScopeInstanceRef(f"BTCUSDT@{account}", "BTCUSDT", account)
        scope = RuleScope.model_validate({"level": "account"})
        return action_request(
            scope, self.pg.user, instance, action_type="place_order", payload=payload,
            rule_id=self.rule, run_id=run, armed_by=str(self.pg.user),
        )  # fmt: skip

    async def run(self, *reqs: ActionRequest) -> uuid.UUID:
        run = reqs[0].run_id
        fire = Fire(
            self.rule, run, reqs, self.emit, version_id=self.version, trigger_type="on_bar_close",
            limits=RuleLimits(),
        )  # fmt: skip
        async with asyncio.timeout(GUARD_S):
            await self.executor.execute(fire)
            await self.pg.settle()
        return run

    def results(self, run: uuid.UUID) -> list[tuple[str, str, Any]]:
        """`(kind, node, payload)` of the run's result events on Postgres, in `seq` order."""
        rows = _sql(
            self.dsn,
            "SELECT kind, node_ref, payload FROM rule_events WHERE rule_run_id = %s "
            "AND kind IN ('action_ok', 'action_fail') ORDER BY seq",
            run,
        )
        return [(str(k), str(n), p) for k, n, p in rows]

    def status(self, run: uuid.UUID) -> str:
        [(status,)] = _sql(self.dsn, "SELECT status::text FROM rule_runs WHERE id = %s", run)
        return str(status)


def _exec(
    row: Any, order_id: uuid.UUID, account: uuid.UUID, qty: str, at_us: int
) -> dict[str, Any]:
    """A trade `EXEC` for `qty` of the order, shaped as the transcribed execution frame is
    (`ws/private-execution.jsonl`, docs-transcribed): derived, not evidence."""
    return {
        "order_id": str(order_id), "order_link_id": row.order_link_id, "account_id": str(account),
        "symbol": "BTCUSDT", "side": "buy", "exec_id": f"x-{uuid.uuid4().hex[:12]}",
        "exchange_order_id": row.exchange_order_id, "qty": qty, "exec_type": "trade",
        "price": "60000", "fee": "0.33", "fee_rate": "0.00055", "ts_exec": at_us,
    }  # fmt: skip


async def test_partial_fill_mid_action_is_recorded_and_the_next_action_runs(
    pg: Rig, pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """G "Recorded exchange answers are handled (integration)": the fire's first entry is filled
    in part between its two actions (an `EXEC` for half its quantity, derived); the fill is
    recorded on the order and in `executions`, the first action stays `ok`, and the second runs."""
    fires = Fires(pg, rel, pg_dsn)
    filled: list[uuid.UUID] = []
    inner = fires.runtime.submission

    class FillsAfterFirst:
        async def submit(self, request: OrderRequest, context: SubmitContext) -> SubmitOutcome:
            outcome: SubmitOutcome = await inner.submit(request, context)
            if not filled and outcome.order_id is not None:
                filled.append(outcome.order_id)
                await pg.settle()
                # the venue holds the half it filled, so B1's stop attach reads it back
                pg.demo.seed_position(cr.position(pg.account, qty="0.005"))
                row = _order(pg_dsn, outcome.order_id)
                fill = _exec(row, outcome.order_id, pg.account, "0.005", pg.clock.us())
                await pg.machines.push(pg.account, outcome.order_id, "EXEC", fill)
                await pg.settle()
            return outcome

        async def answer_replay(self, account_id: Any, replay: Any) -> SubmitOutcome:
            replayed: SubmitOutcome = await inner.answer_replay(account_id, replay)
            return replayed

    fires.runtime.submission = FillsAfterFirst()
    run = await fires.run(
        fires.request("a1", MARKET, uuid.uuid4()),
        fires.request("a2", MARKET | {"qty_mode": "explicit", "qty": "0.002"}, uuid.uuid4()),
    )
    results = fires.results(run)
    assert [(k, n, p["outcome"]) for k, n, p in results] == [
        ("action_ok", "a1", "ok"), ("action_ok", "a2", "ok"),
    ]  # fmt: skip
    [first] = filled
    row = _order(pg_dsn, first)
    assert (row.lifecycle_state, row.cum_exec_qty) == ("partially_filled", Decimal("0.005"))
    assert _fills(pg_dsn, first) == 1 and fires.status(run) == "ok"


async def test_rejection_10001_is_recorded(
    pg: Rig, pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """G same: the venue's rejection `10001` (a parameter error, derived as the port's typed
    rejection) lands the order `rejected`, its anchor `502` with the code, and the action `failed`
    with `exchange_error`, recorded ahead and after; never retried (a definite answer)."""
    fires = Fires(pg, rel, pg_dsn)
    pg.demo.script(
        "place_order", FakeReject(OmsErrorCode.INSTRUMENT_FILTER, exchange_ret_code=10001)
    )
    run = await fires.run(fires.request("a1", MARKET, uuid.uuid4(), on_error="retry_once"))
    [(kind, _node, payload)] = fires.results(run)
    assert (kind, payload["outcome"], payload["error_code"]) == (
        "action_fail", "failed", "exchange_error",
    )  # fmt: skip
    [(_id, _link, state)] = _orders(pg_dsn, pg.account)
    assert state == "rejected"
    [(status, ret_code)] = _sql(
        pg_dsn,
        "SELECT outcome_status, outcome_ret_code FROM idempotency_anchors WHERE created_by = %s",
        pg.user,
    )
    assert (status, ret_code) == (502, 10001)
    assert len(fires.lookups.asked) == 1 and fires.status(run) == "error"


async def test_rate_limit_10018_is_recorded_and_not_retried_past_its_bound(
    pg: Rig, pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """G same: the venue's IP limit `10018` on the create (derived: the adapter's mapped
    `RateLimitError`) leaves its outcome to reconciliation: B1 holds the order `unknown`, the
    answer is `202 unknown`, and the action is recorded `unknown`, never sent again, even under
    `retry_once`: one create reached the venue, within the adapter's own bound."""
    fires = Fires(pg, rel, pg_dsn)
    pg.demo.script("place_order", RateLimitError("rate limited", exchange_ret_code=10018))
    run = await fires.run(fires.request("a1", MARKET, uuid.uuid4(), on_error="retry_once"))
    [(kind, _node, payload)] = fires.results(run)
    assert (kind, payload["outcome"], payload["error_code"]) == (
        "action_fail", "unknown", "unknown",
    )  # fmt: skip
    assert len(pg.creates()) == 1 and len(fires.lookups.asked) == 1
    [(_id, _link, state)] = _orders(pg_dsn, pg.account)
    assert state == "unknown"


async def test_ws_disconnect_between_two_actions_of_one_fire_keeps_order_and_idempotency(
    pg: Rig, pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """G same: the private stream drops between the fire's two actions (the fake stream's end,
    derived) and the second's answer is lost in transit; its retry meets its own anchor and is
    answered as a replay. The fire keeps its order (the first entry before the second), each
    action its own key and anchor, and no order is placed twice."""
    fires = Fires(pg, rel, pg_dsn)
    inner, calls = fires.runtime.submission, [0]

    class DropsAfterFirst:
        async def submit(self, request: OrderRequest, context: SubmitContext) -> SubmitOutcome:
            calls[0] += 1
            outcome: SubmitOutcome = await inner.submit(request, context)
            if calls[0] == 1:
                pg.demo.end_stream()  # the private stream drops after the first action
            elif calls[0] == 2:
                raise ConnectionError("the answer was lost in transit")
            return outcome

        async def answer_replay(self, account_id: Any, replay: Any) -> SubmitOutcome:
            replayed: SubmitOutcome = await inner.answer_replay(account_id, replay)
            return replayed

    fires.runtime.submission = DropsAfterFirst()
    run = await fires.run(
        fires.request("a1", MARKET, uuid.uuid4()),
        fires.request("a2", MARKET | {"qty_mode": "explicit", "qty": "0.002"}, uuid.uuid4(),
                      on_error="retry_once"),
    )  # fmt: skip
    assert [(n, p["outcome"]) for _k, n, p in fires.results(run)] == [("a1", "ok"), ("a2", "ok")]
    orders = _orders(pg_dsn, pg.account)
    assert len(orders) == 2 and calls[0] == 2  # the retry was answered by the anchor, not sent
    [(owner, first, _), (_, second, _), retried] = fires.lookups.asked
    assert retried[1] == second != first and owner == pg.user
    created = [c.order_link_id for c in pg.creates()]
    assert created == [link for _id, link, _state in orders]  # in the fire's order, once each


async def test_a_rule_entry_carries_its_native_stop_on_postgres(
    pg: Rig, pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """C-2.6 on the stores: the rule's entry is recorded with its stop, its `entry_attach` row and
    its `sl.attached` record, and the create carried the stop."""
    fires = Fires(pg, rel, pg_dsn)
    run = await fires.run(fires.request("a1", MARKET, uuid.uuid4()))
    [(_k, _n, payload)] = fires.results(run)
    entry, origin, ref = _entry_row(pg_dsn, uuid.UUID(payload["order_id"]))
    assert (origin, ref) == ("rule", fires.rule)
    assert_entry_carries_native_stop(
        entry, reference_price=Decimal("60000"), stops=_stops(pg_dsn, entry.id),
        records=[r for r, _ in pg.audits.written], calls=pg.demo.calls,
    )  # fmt: skip


async def test_the_day_notional_rebuild_reads_the_accepted_entries_on_postgres(
    pg: Rig, pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """24 §11.7, BQ-5 of #5003: the accepted entry's `action_ok` row names its sized notional,
    which the day's rebuild sums over the rule's armed runs of the UTC day; a refused action's
    row and another rule's are not counted."""
    fires = Fires(pg, rel, pg_dsn)
    run = await fires.run(fires.request("a1", MARKET, uuid.uuid4()))
    [(_k, _n, payload)] = fires.results(run)
    assert payload["notional_usd"] == "600"  # the profile's 0.01 at the market's 60000
    other = Fires(pg, rel, pg_dsn)
    pg.demo.script(
        "place_order", FakeReject(OmsErrorCode.INSTRUMENT_FILTER, exchange_ret_code=10001)
    )
    await other.run(other.request("a1", MARKET, uuid.uuid4()))
    [(day,)] = _sql(pg_dsn, "SELECT (now() AT TIME ZONE 'UTC')::date")
    rebuild = RuleNotionalRebuild(SqlAlchemyRulesRepository(rel))
    assert await rebuild.day_notional(fires.rule, day) == Decimal("600")
    assert await rebuild.day_notional(other.rule, day) == Decimal(0)


async def test_the_principal_reads_an_owners_accounts_of_its_environment_alone(
    pg: Rig, pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """24 §11.5 "The principal": an Owner admits every live account of the process's
    environment, read by one static query (`load_environment_accounts`), never another
    environment's account."""
    live = uuid.uuid4()
    _sql(
        pg_dsn,
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', 'live', 'main', %s, %s)",
        live, str(live.int % 10**15), f"live {live.hex[:8]}",
    )  # fmt: skip
    source = SqlAlchemyScopeSource(rel)
    demo_accounts = await source.load_environment_accounts("demo")
    assert pg.account in demo_accounts and live not in demo_accounts
    assert live in await source.load_environment_accounts("live")


async def test_fire_to_submit_on_postgres_reads_the_rule_with_two_queries(
    pg: Rig, pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """#5003's carry (from #5153): `PostgresRuleStore.get`, check 1's point read, reads the rule
    and all its versions, two statements per read; measured here with the records written ahead
    on Postgres, from the fire's dispatch to the OMS submit call (informational beside the unit
    perf test's 10 ms bound: CI's database time, never a gate on the host's load)."""
    reads = SqlAlchemyRelationalRepository(_login(pg_dsn, "cv_app"), "rule-read-it")
    statements: list[str] = []
    store = PostgresRuleStore(cast(Any, _Counting(reads, statements)))
    manager = RulesManager(store, default_registry())

    async def check_one(req: ActionRequest) -> RowVerdict:
        await manager.current_mode(req.rule_id)
        return "armed"

    fires = Fires(pg, rel, pg_dsn, check_one)
    submitted: list[float] = []
    inner = fires.runtime.submission

    class Timed:
        async def submit(self, request: OrderRequest, context: SubmitContext) -> SubmitOutcome:
            submitted.append(time.perf_counter())
            outcome: SubmitOutcome = await inner.submit(request, context)
            return outcome

        async def answer_replay(self, account_id: Any, replay: Any) -> SubmitOutcome:
            replayed: SubmitOutcome = await inner.answer_replay(account_id, replay)
            return replayed

    fires.runtime.submission = Timed()
    try:
        started = time.perf_counter()
        await fires.run(fires.request("a1", MARKET, uuid.uuid4()))
    finally:
        await reads.dispose()
    elapsed_ms = (submitted[0] - started) * 1000
    assert len(statements) == 2  # the rule, then all its versions: one read, two statements
    assert elapsed_ms < 2_000  # within check 1's own bound; the figure is reported, not gated
    print(f"fire-to-submit on Postgres: {elapsed_ms:.2f} ms; check 1's read: 2 statements")


class _Counting:
    """The rule store's pool, each statement its sessions run recorded."""

    def __init__(self, inner: SqlAlchemyRelationalRepository, seen: list[str]) -> None:
        self._inner, self._seen = inner, seen

    def unit_of_work(self) -> Any:
        return _CountedUnit(self._inner.unit_of_work(), self._seen)


class _CountedUnit:
    def __init__(self, unit: Any, seen: list[str]) -> None:
        self._unit, self._seen = unit, seen

    async def __aenter__(self) -> Any:
        uow = await self._unit.__aenter__()
        execute, seen = uow.session.execute, self._seen

        async def counted(statement: Any, *args: Any, **kwargs: Any) -> Any:
            seen.append(str(statement))
            return await execute(statement, *args, **kwargs)

        uow.session.execute = counted
        return uow

    async def __aexit__(self, *exc: Any) -> Any:
        return await self._unit.__aexit__(*exc)
