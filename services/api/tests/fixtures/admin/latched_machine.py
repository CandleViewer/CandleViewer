"""The latched statechart machine (E42-Q01, #962): the plan's SC-CHAIN-TRIPS handle.

`latched_row` builds a `machine_snapshots` row of a registered kind with a public entity id (an
order, so `GET /admin/statecharts` lists it as `order:<id>`) whose snapshot records two chain trips
and two deferred events: the inspector lists it degraded (AD-S08-01). The row is sealed with the
key provider the caller passes (`HmacKeys`), so the fixture holds no key. A deployed cv-api opens
seals with its own provider, which does not exist yet (#2701), so its inspector lists nothing;
the row is for a test that opens it with the same test provider.

The row is the shape the inspector reads, not a library snapshot: it carries no drain seal
(`cv_epoch`), so a `Restorer` refuses it. `seed_latched_machine` writes it through the composition
root's `SnapshotAdapter`, as cv-api persists a snapshot, into a database named for tests only
(`seed.is_test_database`); anywhere else it raises `FixtureRefused` before reading a row.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Final

from candleviewer.admin.inspector import BoundScope, SnapshotRow, StatechartInspector
from candleviewer.admin.overview.fanout import SliceFanOut
from candleviewer.api.admin_statecharts import machine_key
from candleviewer.statechart.config import SNAPSHOT_V
from candleviewer.statechart.persistence import HmacKeys, MachineKey, SealedSnapshot, seal
from candleviewer.statechart.registry import Registry, machine_hash
from candleviewer.statechart_wiring import SnapshotAdapter
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.statechart_sqlalchemy import SqlAlchemySnapshotStore
from tests.fixtures.admin.seed import FixtureCheckError, refuse_unless_test_database

KIND: Final = "order"
ENTITY_ID: Final = "0a000000-0000-4000-8000-0000000000c7"
ENV: Final = "demo"
#: Its active states: triggered, with its native stop-loss present (C-2.6).
CONFIGURATION: Final = (
    "order",
    "order.lifecycle",
    "order.lifecycle.triggered",
    "order.protection",
    "order.protection.sl_present",
)
CHAIN_TRIPS: Final = 2
#: Deferred events; the inspector counts them and never reads their content.
DEFERRED: Final = 2


def _require_aware(now: datetime) -> None:
    if now.utcoffset() is None:
        raise ValueError("`now` must be timezone-aware: the row's `updated_at`, in UTC")


def latched_row(keys: HmacKeys, *, now: datetime, registry: Registry | None = None) -> SnapshotRow:
    """The handle's row, sealed with `keys`; the same keys and `now` give the same row."""
    _require_aware(now)
    chart = (registry or Registry()).get(KIND)
    blob = {
        "configuration": list(CONFIGURATION),
        "chain_trips": CHAIN_TRIPS,
        "deferred": [{} for _ in range(DEFERRED)],
    }
    digest, key = machine_hash(chart), MachineKey(KIND, ENTITY_ID, ENV)
    tag = seal(keys, chart, blob, digest, SNAPSHOT_V, key=key)
    envelope = SealedSnapshot(key, SNAPSHOT_V, digest, blob, tag)
    return SnapshotRow(KIND, ENTITY_ID, ENV, envelope, now)


class _Rows:
    def __init__(self, rows: Sequence[SnapshotRow]) -> None:
        self._rows = rows

    async def snapshots(self) -> Sequence[SnapshotRow]:
        return self._rows


def _owner_sees_all(machine_kind: str, scope: BoundScope) -> bool:
    return True


async def check_listed_degraded(
    rows: Sequence[SnapshotRow], keys: HmacKeys, *, now: datetime, registry: Registry | None = None
) -> None:
    """The handle's row is among `rows` once, and the inspector, opening it with `keys`, lists it
    degraded with its trips and deferred events; `FixtureCheckError` names what is not."""
    _require_aware(now)
    ours = (KIND, ENTITY_ID, ENV)
    mine = [r for r in rows if (r.machine_kind, r.entity_id, r.environment) == ours]
    if len(mine) != 1:
        raise FixtureCheckError(f"SC-CHAIN-TRIPS: {len(mine)} rows for {KIND}/{ENTITY_ID}, not 1")
    charts = registry or Registry()
    inspector = StatechartInspector(
        SliceFanOut(budget_s=60, ttl_s=0.0, now=lambda: now),  # no 300 ms timer on a busy host
        machine_key,
        {KIND: charts.hash(KIND)},
        store=_Rows(mine),
        keys=keys,
        registry=charts,
    )
    listing = await inspector.listing(_owner_sees_all, kind=KIND, environment=ENV, degraded=True)
    listed = [(m.chain_trips, m.deferred_depth) for m in listing.items]
    if listed != [(CHAIN_TRIPS, DEFERRED)]:
        raise FixtureCheckError(
            f"SC-CHAIN-TRIPS: the inspector lists {listed} (trips, deferred) as degraded, "
            f"not [({CHAIN_TRIPS}, {DEFERRED})]"
        )


async def _refuse(rel: SqlAlchemyRelationalRepository) -> None:
    async with rel.engine.connect() as conn:
        await refuse_unless_test_database(conn)


async def seed_latched_machine(
    rel: SqlAlchemyRelationalRepository,
    keys: HmacKeys,
    *,
    now: datetime,
    registry: Registry | None = None,
) -> SnapshotRow:
    """Upsert the handle's row as cv-api persists a snapshot; a second run writes the same row."""
    await _refuse(rel)
    row = latched_row(keys, now=now, registry=registry)
    adapter = SnapshotAdapter(SqlAlchemySnapshotStore(rel), clock=lambda: now)
    await adapter.write_snapshot(row.envelope.key, row.envelope)
    return row


async def check_latched_machine(
    rel: SqlAlchemyRelationalRepository,
    keys: HmacKeys,
    *,
    now: datetime,
    registry: Registry | None = None,
) -> None:
    """`check_listed_degraded` over the rows the composition root's adapter reads back."""
    await _refuse(rel)
    rows = await SnapshotAdapter(SqlAlchemySnapshotStore(rel)).snapshots()
    await check_listed_degraded(rows, keys, now=now, registry=registry)
