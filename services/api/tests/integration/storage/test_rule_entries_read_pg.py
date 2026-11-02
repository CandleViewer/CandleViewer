"""Integration: the read of a rule's resting entries on real Postgres 16 (E35-T12 slice 3e; 24
§11.5 "Exits", §11.7; the rulings of record on #5004, BQ-7, BQ-8 and BQ-10).

`SqlAlchemyOrderStore.rule_resting_entries` is what a rule's cancels and amends read on an account
check 5 admitted, and what its circuit breaker reads on every account: the orders of the rule's
groups (`trade_groups.origin_rule_id`, `ix_tg_rule`), `placed`, open, not reduce-only, with no
parent, in a group whose algo is `none`. The orders are the C6 pipeline's
(`test_submission_pipeline_pg.py`, shared by import), placed with a rule's origin or a user's, with
a demo `FakeTradingPort` as the exchange (C-13.5: no venue is reached; nothing here is a
recording).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from candleviewer.oms.ports import SubmitActor
from candleviewer.oms.submit import SubmitContext
from candleviewer.storage.repositories.orders_sqlalchemy import SqlAlchemyOrderStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.integration.oms.test_rule_origin_submit_pg import _rule, _rule_context
from tests.integration.oms.test_submission_pipeline_pg import Rig, _sql, pg, pg_dsn, rel
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr

pytestmark = pytest.mark.integration
__all__ = ["pg", "pg_dsn", "rel"]  # C6's database, its pool and its pipeline, for this module


async def test_the_rule_entries_read_selects_the_rules_resting_entries_alone(
    pg: Rig, pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """BQ-7, BQ-10: the read selects the rule's own resting entries through its groups, never
    another rule's entry, a user's manual entry or the rule's own reduce-only close (no group, and
    reduce-only); on the account and the symbol when named; of the environment named; oldest
    first, at most `limit`. An entry of the rule's that is cancelled, and one that is an algo's
    child (its `parent_order_id` set), leave the read: a group's `algo` is write-once once the
    group fired (`trg_tg_write_once`), so the statement test pins that filter."""
    mine, theirs = _rule(pg_dsn, pg.user), _rule(pg_dsn, pg.user)
    first = await pg.submit(pg.entry(), _rule_context(pg, mine))
    second = await pg.submit(pg.entry(price=Decimal("59900")), _rule_context(pg, mine))
    await pg.submit(pg.entry(), _rule_context(pg, theirs))
    user = SubmitContext(SubmitActor(user_id=pg.user, role="owner"), uuid.uuid4(), sr.SHA, None)
    await pg.submit(pg.entry(), user)
    pg.demo.seed_position(cr.position(pg.account, qty="0.050"))
    close = sr.flatten(account_id=pg.account, order_type="limit", price=Decimal("61000"))
    await pg.submit(close, _rule_context(pg, mine))
    await pg.settle()
    store = SqlAlchemyOrderStore(rel)
    read = await store.rule_resting_entries(mine.rule_id, "demo", limit=10)
    assert [row.id for row in read] == [first.order_id, second.order_id]
    assert {(row.provenance, row.reduce_only, row.origin) for row in read} == {
        ("placed", False, "rule")
    }
    on_account = await store.rule_resting_entries(
        mine.rule_id, "demo", account_id=pg.account, symbol=sr.SYMBOL, limit=1
    )
    assert [row.id for row in on_account] == [first.order_id]
    for missed in (
        store.rule_resting_entries(mine.rule_id, "demo", account_id=uuid.uuid4(), limit=10),
        store.rule_resting_entries(mine.rule_id, "demo", symbol="ETHUSDT", limit=10),
        store.rule_resting_entries(mine.rule_id, "testnet", limit=10),
        store.rule_resting_entries(uuid.uuid4(), "demo", limit=10),
    ):
        assert await missed == ()
    with pytest.raises(ValueError, match="limit"):
        await store.rule_resting_entries(mine.rule_id, "demo", limit=0)
    third = await pg.submit(pg.entry(price=Decimal("59800")), _rule_context(pg, mine))
    await pg.settle()
    _sql(pg_dsn, "UPDATE orders SET state = 'cancelled', lifecycle_state = 'cancelled' "
         "WHERE id = %s", second.order_id)  # fmt: skip
    _sql(pg_dsn, "UPDATE orders SET parent_order_id = %s WHERE id = %s",
         first.order_id, third.order_id)  # fmt: skip
    after = await store.rule_resting_entries(mine.rule_id, "demo", limit=10)
    assert [row.id for row in after] == [first.order_id]
