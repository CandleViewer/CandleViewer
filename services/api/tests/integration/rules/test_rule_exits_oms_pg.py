"""Integration: a rule's reduce-only exit through the OMS pipeline on real Postgres 16 (E35-T12
slice 3d; 24 §11.5 "Exits"; the rulings of record on #5004, BQ-5 and BQ-6).

The executor writes its records ahead on Postgres (`RuleRunRecords` over the rules repository) and
hands the exit to the composition root's handler (`rules_oms_exits`), whose order port runs the C6
pipeline (`test_submission_pipeline_pg.py`, shared by import): B1's facade, its step writer and
the command port over the Postgres stores, with a demo `FakeTradingPort` as the exchange (C-13.5:
no venue is reached). The position the exit reads is the private stream's row as stored, built
here.

**Derived, not evidence.** No recorded demo capture of an order-path reply exists yet (every
order-path file under `packages/fixtures/bybit/2026-10-05/` is `docs-transcribed`), as
`test_private_stream_replay_pg.py` labels its rows: the venue's acknowledgement of the close is the
fake port's. E29-K01 (#843) runs this row again against its recordings once the owner's demo key
exists.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.exchange.base.models import PlaceOrderRequest
from candleviewer.rules.executor.budget import OrderBudget
from candleviewer.rules.executor.dispatch import Fire
from candleviewer.rules.executor.engine import ActionExecutor, RowVerdict
from candleviewer.rules.executor.gates import Gates
from candleviewer.rules.executor.handlers import HANDLERS, BoundHandler, bind_handlers
from candleviewer.rules.executor.ports import PrincipalView
from candleviewer.rules.ir.models import Action, RuleLimits, RuleScope
from candleviewer.rules.scope import ActionRequest, ScopeInstanceRef
from candleviewer.rules_oms_exits import rule_reduce_handlers
from candleviewer.rules_oms_wiring import RuleRunRecords
from candleviewer.storage.repositories.positions import PositionRow
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.rules_sqlalchemy import SqlAlchemyRulesRepository
from tests.integration.oms.test_submission_pipeline_pg import Rig, _sql, pg, pg_dsn, rel
from tests.integration.rules.test_rule_actions_oms_pg import _rule
from tests.rules.executor.native_sl import assert_position_stop_untouched
from tests.rules.executor.request_builders import Principals, Records, Switches, action_request
from tests.rules.executor.test_order_handlers import Lookups, NoHistory, Recorded, Runtime
from tests.unit.oms import command_rig as cr

pytestmark = pytest.mark.integration
__all__ = ["pg", "pg_dsn", "rel"]  # C6's database, its pool and its pipeline, for this module

GUARD_S = 30.0
STOP = Decimal("58500")
T0 = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


class Held:
    """The account's stored open position, as the private stream wrote it (derived)."""

    def __init__(self, row: PositionRow) -> None:
        self.row = row

    async def open_positions(self, owner: PrincipalView, account_id: uuid.UUID) -> Any:
        return (self.row,) if account_id == self.row.exchange_account_id else ()


async def test_a_rule_flatten_reaches_the_fake_venue_reduce_only_on_entry(
    pg: Rig, pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """G "A reduce-only exit never opens a position" and "Rule exits ride the entry lane (RE-D6)",
    on Postgres: a rule's `flatten_position` persists one reduce-only `flatten` order, the
    rule's (`origin` `rule`, `origin_ref` the rule's id), sends it to the venue reduce-only with
    no stop or take-profit on `entry`, and records its run `ok`; no stop is set or cancelled, so
    the position's native stop stays in force."""
    rule, version = _rule(pg_dsn, pg.user)
    held = Held(
        PositionRow(
            exchange_account_id=pg.account, symbol=cr.SYMBOL, size=Decimal("0.050"),
            side="Buy", avg_price=Decimal("60000"), stop_loss=STOP, tpsl_mode="Full",
            id=uuid.uuid4(), recv_ts=T0, updated_at=T0,
        )
    )  # fmt: skip
    pg.demo.seed_position(cr.position(pg.account, qty="0.050", stop_loss=STOP))
    runtime = Runtime(None, None)
    runtime.submission = Recorded(pg.pipeline, runtime)
    runtime.anchors = Lookups(pg.pipeline._anchors)
    principals = Principals(frozenset({pg.account}))
    handlers: dict[str, BoundHandler] = dict(
        rule_reduce_handlers(
            lambda: runtime, oms_enabled=lambda: True, principals=principals, positions=held
        )
    )
    audits = Records()

    async def armed(_req: ActionRequest) -> RowVerdict:
        return "armed"

    executor = ActionExecutor(
        check_one=armed, scope_check=lambda req: None,
        gates=Gates(switches=Switches(), principal=principals),
        records=RuleRunRecords(SqlAlchemyRulesRepository(rel)), audit=audits,
        handlers=bind_handlers(HANDLERS, handlers), budget=OrderBudget(rebuild=NoHistory()),
    )  # fmt: skip

    async def emit(req: ActionRequest) -> str | None:
        await executor.hand_over(req)
        return None

    run = uuid.uuid4()
    instance = ScopeInstanceRef(f"BTCUSDT@{pg.account}", "BTCUSDT", pg.account)
    payload = Action.model_validate({"node_id": "x1", "type": "flatten_position", "params": {}})
    req = action_request(
        RuleScope.model_validate({"level": "account"}), pg.user, instance,
        action_type="flatten_position", payload=payload, rule_id=rule, run_id=run,
        armed_by=str(pg.user),
    )  # fmt: skip
    fire = Fire(
        rule, run, (req,), emit, version_id=version, trigger_type="on_bar_close",
        limits=RuleLimits(),
    )  # fmt: skip
    async with asyncio.timeout(GUARD_S):
        await executor.execute(fire)
        await pg.settle()
    [(kind, outcome)] = _sql(
        pg_dsn,
        "SELECT kind::text, payload->>'outcome' FROM rule_events WHERE rule_run_id = %s "
        "AND kind IN ('action_ok', 'action_fail')",
        run,
    )
    assert (kind, outcome) == ("action_ok", "ok")
    [(status,)] = _sql(pg_dsn, "SELECT status::text FROM rule_runs WHERE id = %s", run)
    [(reduce_only, intent, origin, origin_ref, qty)] = _sql(
        pg_dsn,
        "SELECT reduce_only, intent::text, origin, origin_ref, qty FROM orders "
        "WHERE exchange_account_id = %s",
        pg.account,
    )
    assert (status, reduce_only, intent) == ("ok", True, "flatten")
    assert (origin, origin_ref, qty) == ("rule", rule, Decimal("0.050"))
    creates = [
        (c.lane, c.request.reduce_only, c.request.stop_loss)
        for c in pg.demo.calls
        if isinstance(c.request, PlaceOrderRequest)
    ]
    assert creates == [("entry", True, None)]
    assert not {c.method for c in pg.demo.calls} & {"set_trading_stop", "cancel_order"}
    [venue] = await pg.demo.positions(cr.ref(pg.account))
    assert_position_stop_untouched("Buy", before=STOP, after=venue.stop_loss)
