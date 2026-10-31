"""Integration (E29-S03 #978): a partial close on real Postgres 16, over C6's database and
process (`test_submission_pipeline_pg.py`, shared by import). The stored position the route
admits, read back from `positions`; the close's size resolved from it before any exchange call; its
one reduce-only create through the pipeline over the Postgres stores, with no stop write and no
cancel; the fill B1 records; and the remainder's position push applied through the position store,
which keeps the position's own native stop: `SL_OBSERVED`, nothing paged (C-2.6, BQ-1 option A as
the orchestrator ruled it). The venue is a `FakeTradingPort` (C-13.5: no venue is reached)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from decimal import Decimal

import pytest

from candleviewer.exchange.base.models import Execution
from candleviewer.oms.ports import NoPositionProtection, PositionKey
from candleviewer.oms.position_writes import CloseTerms, close_request, resolve_close
from candleviewer.oms.positions import PositionProjection, row_state
from candleviewer.oms.push_mapping import ForProtection, exec_payload, reading
from candleviewer.oms.repository import (
    OrderRepository,
    PositionRepository,
    PositionSnapshotRepository,
    RecordedStopRepository,
)
from candleviewer.storage.repositories.orders_sqlalchemy import SqlAlchemyOrderStore
from candleviewer.storage.repositories.positions_sqlalchemy import SqlAlchemyPositionStore
from candleviewer.storage.repositories.recorded_stops_sqlalchemy import (
    SqlAlchemyRecordedStopStore,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.integration.oms import test_submission_pipeline_pg as c6
from tests.integration.oms.test_submission_pipeline_pg import pg, pg_dsn, rel
from tests.unit.oms import command_rig as cr
from tests.unit.oms.order_rig import Pager
from tests.unit.oms.submit_rig import STOP, SYMBOL, instrument

pytestmark = pytest.mark.integration
__all__ = ["pg", "pg_dsn", "rel"]  # C6's database, its pool and one process over a fresh account

HALF = CloseTerms("market", pct=Decimal(50))


@dataclass
class Counts:
    """The projection's counts, as `StageCounts` takes them."""

    seen: list[str] = field(default_factory=list)

    def count(self, outcome: str) -> None:
        self.seen.append(outcome)


def _position(dsn: str, account: object) -> tuple[Decimal, Decimal | None]:
    [(size, stop)] = c6._sql(
        dsn,
        "SELECT size, stop_loss FROM positions "
        "WHERE exchange_account_id = %s AND symbol = %s AND position_idx = 0",
        account,
        SYMBOL,
    )
    return size, stop


async def test_a_partial_close_fills_and_its_remainders_push_keeps_its_native_stop(
    pg: c6.Rig, rel: SqlAlchemyRelationalRepository, pg_dsn: str
) -> None:
    rig, at = pg, pg.clock.us()
    store = SqlAlchemyPositionStore(rel, clock=rig.clock)
    positions = PositionRepository(store)
    long = cr.position(rig.account, qty="0.250", stop_loss=STOP, updated_at=at - 1_000_000)
    rig.demo.seed_position(long)
    admitted = await positions.upsert(row_state(long))  # as the private stream stored it

    size = resolve_close(admitted, HALF, instrument())  # step 13, before any exchange call
    closing = replace(rig.context(), operation="closePosition", protective=True)
    outcome = await rig.pipeline.submit(close_request(admitted, HALF, size.qty), closing)
    assert outcome.status == 202 and outcome.order_id is not None
    [create] = rig.creates()
    assert (create.side, create.qty, create.reduce_only, create.stop_loss) == (
        "sell",
        Decimal("0.125"),
        True,
        None,
    )
    assert rig.calls() == ["positions", "place_order"]  # no stop write, no cancel (C-2.6)
    await rig.settle()
    placed = c6._order(pg_dsn, outcome.order_id)
    assert placed.exchange_order_id is not None

    fill = Execution(
        exec_id="e29-s03-fill-1", exchange_order_id=placed.exchange_order_id,
        order_link_id=placed.order_link_id, account_id=rig.account, symbol=SYMBOL, side="sell",
        price=Decimal("60000"), qty=Decimal("0.125"), fee=Decimal("0.004"),
        fee_rate=Decimal("0.00055"), fee_currency="USDT", is_maker=False, exec_type="trade",
        closed_pnl=None, ts_exec=at, ts_ingest=at, seq=1,
    )  # fmt: skip
    payload = exec_payload(fill, order_id=outcome.order_id, order_link_id=placed.order_link_id)
    await rig.machines.push(rig.account, outcome.order_id, "EXEC", payload)
    await rig.settle()
    assert c6._order(pg_dsn, outcome.order_id).lifecycle_state == "filled"
    assert c6._fills(pg_dsn, outcome.order_id) == 1

    counts, pager = Counts(), Pager()
    projection = PositionProjection(
        orders=rig.machines, positions=positions, snapshots=PositionSnapshotRepository(store),
        readings=NoPositionProtection(), counts=counts, pager=pager,
        stops=RecordedStopRepository(SqlAlchemyRecordedStopStore(rel)),
        order_rows=OrderRepository(SqlAlchemyOrderStore(rel)),
        monotonic=asyncio.get_running_loop().time, now=rig.clock,
    )  # fmt: skip
    remainder = cr.position(rig.account, qty="0.125", stop_loss=STOP, updated_at=at)
    shown = reading(remainder)
    assert (shown.event, shown.size) == ("SL_OBSERVED", Decimal("0.125"))
    await projection.take(rig.account, remainder, ForProtection(PositionKey(rig.account, SYMBOL,
                                                                            0), shown))  # fmt: skip
    assert "applied" in counts.seen and pager.calls == []
    assert _position(pg_dsn, rig.account) == (Decimal("0.125"), STOP)
