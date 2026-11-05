"""Integration: the closed-PnL sync's writes and the writers' two columns on Postgres 16 (E29-S06
#981 slice 3; 24 Sec.8.13, 21 Sec.3.3.6, Sec.3.3.7, Sec.3.3.13). A fill keeps its order row's
`position_idx` and the size it states it closed, which the final rule sums; a snapshot keeps the
venue's time, where row 57 finds a confirmed flat; and the sync keeps the venue's records through
the closed-PnL store (slice 2): inserted settled, replaced until final, made final by its rule, a
read after final never applied, and the ruled seed stored once per key. The venue is
`test_closed_pnl_sync.py`'s fake, its records and readings derived from the transcribed ones there;
the Postgres fixture and helpers are `test_closed_pnl_records_migration.py`'s."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from structlog.testing import capture_logs

from candleviewer.observability.metrics import Metrics
from candleviewer.oms.closed_pnl_compose import ClosedPnlComposer
from candleviewer.oms.closed_pnl_sync import ClosedPnlSync
from candleviewer.risk.day_boundary import DayBoundary
from candleviewer.storage.repositories.closed_pnl import record_id
from candleviewer.storage.repositories.closed_pnl_sqlalchemy import SqlAlchemyClosedPnlStore
from candleviewer.storage.repositories.executions import NewExecution
from candleviewer.storage.repositories.executions_sqlalchemy import SqlAlchemyExecutionStore
from candleviewer.storage.repositories.positions import NewPositionSnapshot
from candleviewer.storage.repositories.positions_sqlalchemy import SqlAlchemyPositionStore
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.risk_policy_sqlalchemy import SqlAlchemyRiskPolicyReads
from tests.integration.storage.test_closed_pnl_records_migration import (
    _T0,
    _conn,
    _group,
    _put,
    pg_dsn,
)
from tests.integration.storage.test_closed_pnl_store_pg import _leg
from tests.unit.oms.submit_rig import Instruments, instrument
from tests.unit.oms.test_closed_pnl_sync import T0, Accounts, Venue, _at, _fill, _reading, _record

pytestmark = pytest.mark.integration
__all__ = ["pg_dsn"]  # the shared module-scoped fixture
_ANY = datetime.max.replace(tzinfo=UTC)


async def test_a_fills_and_a_snapshots_new_columns_land_where_their_readers_look(
    pg_dsn: str,
) -> None:
    with _conn(pg_dsn) as c:
        a, b = _put(c, "exchange_accounts"), _put(c, "exchange_accounts")
        order = _put(c, "orders", a, position_idx=2, exchange_order_id="o-9")
    rel = SqlAlchemyRelationalRepository(pg_dsn, "closed-pnl-sync-it")
    fills, flats = SqlAlchemyExecutionStore(rel), SqlAlchemyClosedPnlStore(rel)
    try:
        fill = NewExecution(
            exchange_account_id=a, exec_id="E1", symbol="SOLUSDT", side="Sell",
            exec_qty=Decimal(1), exec_price=Decimal(150), exec_value=Decimal(150),
            exec_type="Trade", is_maker=False, exec_ts=_T0, order_id=order,
            closed_size=Decimal("0.5"),
        )  # fmt: skip
        assert await fills.insert(fill)
        got = await fills.get(a, "E1")
        assert got is not None and (got.position_idx, got.closed_size) == (2, Decimal("0.5"))
        assert (await fills.closed_size(a, order), await fills.closed_size(b, order)) == (
            Decimal("0.5"), None,
        )  # fmt: skip
        assert await fills.insert(replace(fill, exec_id="E2", closed_size=None))
        assert await fills.closed_size(a, order) is None  # a fill states no size: no sum
        flat = NewPositionSnapshot(
            exchange_account_id=a, symbol="SOLUSDT", size=Decimal(0), reason="ws_push",
            position_idx=2, exchange_updated_ts=_T0,
        )  # fmt: skip
        stored = await SqlAlchemyPositionStore(rel).append(flat)
        assert stored.exchange_updated_ts == _T0
        assert await flats.walk_flats(a, "SOLUSDT", 2, _ANY, 5) == (_T0,)
    finally:
        await rel.dispose()


async def test_the_sync_keeps_records_until_final_and_seeds_a_key_once(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        a = _put(c, "exchange_accounts")
        _put(c, "orders", a, exchange_order_id="o-1")  # partially filled
        done = _put(c, "orders", a, exchange_order_id="o-2", state="filled")
        for exec_id in ("X1", "X2"):
            _put(c, "executions", a, order_id=done, exec_id=exec_id, closed_size=1)
    rel = SqlAlchemyRelationalRepository(pg_dsn, "closed-pnl-sync-it")
    store = SqlAlchemyClosedPnlStore(rel)
    venue = Venue(
        records=[
            _record(exchange_order_id="o-1"),
            _record(exchange_order_id="o-2", qty=Decimal(2)),
        ],
        readings=[_reading()],
    )

    def sync() -> ClosedPnlSync:
        return ClosedPnlSync(
            accounts=Accounts(), router=venue, records=store, closes=SqlAlchemyExecutionStore(rel),
            snapshots=SqlAlchemyPositionStore(rel), metrics=Metrics("demo"), now=lambda: T0,
            on_ended=lambda: None, day_start=DayBoundary(SqlAlchemyRiskPolicyReads(rel)).day_start,
        )  # fmt: skip

    first, second = (record_id(a, x) for x in ("o-1", "o-2"))
    try:
        assert await sync().read(a)
        open_, final = await store.get(a, first), await store.get(a, second)
        assert open_ is not None and open_.settled_at is not None and open_.final_at is None
        assert final is not None and final.final_at is not None  # filled, and 1 + 1 closed
        venue.records = [
            _record(exchange_order_id="o-1", qty=Decimal(4)),
            _record(exchange_order_id="o-2", qty=Decimal(2), closed_pnl=Decimal(-50)),
        ]
        later = sync()  # a restart: its first read seeds again, where no flat is held
        with capture_logs() as logs:
            assert await later.read(a)
        replaced = await store.get(a, first)
        assert replaced is not None and replaced.qty == 4  # replaced until final
        assert await store.get(a, second) == final  # never applied after final
        assert [e["exchange_order_id"] for e in logs if e["event"] == "closed_pnl_read_after_final"
                ] == ["o-2"]  # fmt: skip
        seeded = _at(1_697_682_317_038_000)  # the reading's updatedTime
        assert await store.walk_flats(a, "BTCUSDT", 2, _ANY, 5) == (seeded,)
        with _conn(pg_dsn) as c:
            rows = c.execute(
                "SELECT count(*) FROM position_snapshots WHERE exchange_account_id = %s", (a,)
            ).fetchone()
        assert rows == (1,) and seeded < T0 - timedelta(days=365)  # one seed, from the venue's
    finally:
        await rel.dispose()


async def test_a_close_composed_provisional_settles_in_place_and_the_walk_makes_it_final(
    pg_dsn: str,
) -> None:
    """E29-S06 slice 5b: a long of 3 opened on a leg after a confirmed flat and closed by one
    order's stream fill is composed provisional before the venue read; the record read settles it
    in place, same id, the venue's columns over the local ones, the walk's `opened_at` and group
    kept, and the walk's `c` completes the final rule."""
    opened, closed = T0 - timedelta(minutes=90), T0 - timedelta(minutes=60)
    with _conn(pg_dsn) as c:
        a = _put(c, "exchange_accounts")
        leg = _leg(c, group := _group(c), a)
        opener = _put(c, "orders", a, symbol="ETHUSDT", side="Buy", exchange_order_id="o-6",
                      trade_group_leg_id=leg, state="filled")  # fmt: skip
        closer = _put(c, "orders", a, symbol="ETHUSDT", exchange_order_id="o-7", state="filled")
        _put(
            c,
            "position_snapshots",
            a,
            symbol="ETHUSDT",
            exchange_updated_ts=T0 - timedelta(hours=3),
        )
        for exec_id, order, side, price, fee, size, pnl, at in (
            ("P1", opener, "Buy", 1195, "2.151", 0, 0, opened),
            ("P2", closer, "Sell", 1180, "2.124", 3, -45, closed),
        ):
            _put(c, "executions", a, exec_id=exec_id, order_id=order, symbol="ETHUSDT", side=side,
                 exec_qty=3, exec_price=price, exec_value=3 * price, exec_fee=Decimal(fee),
                 closed_size=size, closed_pnl=pnl, exec_ts=at)  # fmt: skip
    rel = SqlAlchemyRelationalRepository(pg_dsn, "closed-pnl-compose-it")
    store, venue = SqlAlchemyClosedPnlStore(rel), Venue()
    listed = Instruments(listed={"ETHUSDT": instrument(symbol="ETHUSDT")})
    sync = ClosedPnlSync(
        accounts=Accounts(), router=venue, records=store, closes=SqlAlchemyExecutionStore(rel),
        snapshots=SqlAlchemyPositionStore(rel), metrics=Metrics("demo"), now=lambda: T0,
        on_ended=lambda: None, day_start=DayBoundary(SqlAlchemyRiskPolicyReads(rel)).day_start,
        composer=ClosedPnlComposer(store=store, instruments=listed),
    )  # fmt: skip
    rid = record_id(a, "o-7")
    try:
        sync.start([])
        sync.stored(replace(_fill(Decimal(3)), exchange_account_id=a, order_id=closer))
        await sync.stop()  # the named order stays for the read below, which composes it first
        assert await sync.read(a)
        first = await store.get(a, rid)
        assert first is not None and (first.settled_at, first.qty, first.trade_group_id) == (
            None, Decimal(3), group,
        )  # fmt: skip
        assert (first.gross_pnl, first.fee_pnl, first.funding_pnl, first.opened_at) == (
            Decimal(-45), Decimal("-4.275"), Decimal(0), opened,
        )  # fmt: skip
        venue.records = [_record(exchange_order_id="o-7")]
        assert await sync.read(a)
        settled = await store.get(a, rid)
        assert settled is not None and settled.final_at is not None and settled.id == first.id
        assert (settled.closed_pnl, settled.qty, settled.closed_at) == (
            _record().closed_pnl, Decimal(3), _at(_record().closed_at),
        )  # fmt: skip
        assert (settled.opened_at, settled.trade_group_id, settled.gross_pnl) == (
            opened, group, Decimal(-45),
        )  # fmt: skip
    finally:
        await rel.dispose()
