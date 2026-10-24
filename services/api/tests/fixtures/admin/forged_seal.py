"""SC-FORGED-SEAL (E42-Q01, #962): a persisted snapshot whose seal fails (AD-T07-N01).

SC-CHAIN-TRIPS's row with its snapshot changed after it was sealed: a forger hides the trips, and
the HMAC no longer holds, so the inspector leaves the row out and says its seal did not verify. It
is written through the composition root's `SnapshotAdapter`, as `seed_latched_machine` writes the
latched row, and takes that row's key: a database holds one of the two handles. The caller's
`HmacKeys` seal it before the change, so the fixture holds no key. Like the latched row it carries
no drain seal, so a `Restorer` refuses it. A database not named for tests is refused before any
read.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import datetime

from candleviewer.admin.inspector import SEAL_FAILED, SnapshotRow, StatechartInspector
from candleviewer.admin.overview.fanout import SliceFanOut
from candleviewer.api.admin_statecharts import machine_key
from candleviewer.statechart.persistence import HmacKeys, MachineKey, open_sealed
from candleviewer.statechart.registry import Registry, machine_hash
from candleviewer.statechart_wiring import SnapshotAdapter
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.statechart_sqlalchemy import SqlAlchemySnapshotStore
from tests.fixtures.admin.latched_machine import ENTITY_ID, ENV, KIND, latched_row
from tests.fixtures.admin.seed import FixtureCheckError, refuse_unless_test_database


class _Rows:
    def __init__(self, rows: Sequence[SnapshotRow]) -> None:
        self._rows = rows

    async def snapshots(self) -> Sequence[SnapshotRow]:
        return self._rows


def forged_row(keys: HmacKeys, *, now: datetime, registry: Registry | None = None) -> SnapshotRow:
    """The latched row, sealed with `keys`, then its trips cleared; the seal no longer holds."""
    sealed = latched_row(keys, now=now, registry=registry)
    hidden = sealed.envelope.snapshot | {"chain_trips": 0}
    envelope = dataclasses.replace(sealed.envelope, snapshot=hidden)
    return dataclasses.replace(sealed, envelope=envelope)


async def _refuse(rel: SqlAlchemyRelationalRepository) -> None:
    async with rel.engine.connect() as conn:
        await refuse_unless_test_database(conn)


async def seed_forged_seal(
    rel: SqlAlchemyRelationalRepository,
    keys: HmacKeys,
    *,
    now: datetime,
    registry: Registry | None = None,
) -> SnapshotRow:
    """Upsert the forged row; a second run writes the same row."""
    await _refuse(rel)
    row = forged_row(keys, now=now, registry=registry)
    adapter = SnapshotAdapter(SqlAlchemySnapshotStore(rel), clock=lambda: now)
    await adapter.write_snapshot(row.envelope.key, row.envelope)
    return row


async def check_left_out(
    rows: Sequence[SnapshotRow], keys: HmacKeys, *, now: datetime, registry: Registry | None = None
) -> None:
    """The handle's row is among `rows` once, its seal fails on the HMAC, and the inspector leaves
    it out and says why; `FixtureCheckError` names what is not."""
    ours = (KIND, ENTITY_ID, ENV)
    mine = [r for r in rows if (r.machine_kind, r.entity_id, r.environment) == ours]
    if len(mine) != 1:
        raise FixtureCheckError(f"SC-FORGED-SEAL: {len(mine)} rows for {KIND}/{ENTITY_ID}, not 1")
    charts = registry or Registry()
    chart, key = charts.get(KIND), MachineKey(KIND, ENTITY_ID, ENV)
    failed: list[str] = []
    try:
        open_sealed(
            keys, chart, mine[0].envelope, key=key, expected_machine_hash=machine_hash(chart)
        )
    except ValueError as refused:
        if "bad HMAC" not in str(refused):
            failed.append(f"its seal fails with {str(refused)!r}, not on the HMAC")
    else:
        failed.append("its seal verifies")
    fan = SliceFanOut(budget_s=60, ttl_s=0.0, now=lambda: now)  # no 300 ms timer on a busy host
    inspector = StatechartInspector(
        fan, machine_key, {KIND: charts.hash(KIND)}, store=_Rows(mine), keys=keys, registry=charts
    )
    listing = await inspector.listing(lambda kind, scope: True)
    if listing.items:
        failed.append(f"the inspector lists {len(listing.items)} machines")
    if (listing.snapshots.status, listing.snapshots.detail) != ("error", SEAL_FAILED):
        failed.append(f"snapshots is {listing.snapshots.status!r}, {listing.snapshots.detail!r}")
    if failed:
        raise FixtureCheckError("SC-FORGED-SEAL: " + "; ".join(failed))


async def check_forged_seal(
    rel: SqlAlchemyRelationalRepository,
    keys: HmacKeys,
    *,
    now: datetime,
    registry: Registry | None = None,
) -> None:
    """`check_left_out` over the rows the composition root's adapter reads back."""
    await _refuse(rel)
    rows = await SnapshotAdapter(SqlAlchemySnapshotStore(rel)).snapshots()
    await check_left_out(rows, keys, now=now, registry=registry)
