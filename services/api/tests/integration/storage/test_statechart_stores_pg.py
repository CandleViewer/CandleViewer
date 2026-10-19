"""Integration: the statechart row stores and adapters on real Postgres 16 (E50-T62 #3793).

The database is set up like production (`pg_bootstrap.sql`'s roles, the migrations as `cv_owner`)
and the stores run as `cv_app`, so they meet `0033_machine_persistence`'s grants. One test per
Gherkin scenario of the ticket: a machine built by `factory.build`, persisted by `Persister` and
restored by a new `Restorer` over the same rows, with values that must survive jsonb; the drain
journal replayed exactly once and stamped; the #3082 key assertion writing nothing; a tampered row
refused by the `Restorer`, never repaired; the inspector's list; the event chain read back byte for
byte; and a store that cannot reach Postgres failing within its bound. `testcontainers` in CI.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.inspector import SnapshotRow
from candleviewer.statechart import build
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.persistence import (
    ChainTripLatch,
    MachineKey,
    Persister,
    Restorer,
    RestoreRefusedError,
    RowStoreDrainJournal,
    SealedSnapshot,
    hmac_sealer,
    open_sealed,
)
from candleviewer.statechart.plugins.audit import (
    GENESIS_HASH,
    MachineEventRow,
    row_digest,
    verify_chain,
)
from candleviewer.statechart.registry import Registry
from candleviewer.statechart_wiring import (
    EventsAdapter,
    JournalRowsAdapter,
    SnapshotAdapter,
    SnapshotKeyMismatchError,
)
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.statechart_sqlalchemy import (
    STORE_TIMEOUT_S,
    EventRecord,
    JournalRecord,
    SnapshotRecord,
    SqlAlchemyEventStore,
    SqlAlchemyJournalStore,
    SqlAlchemySnapshotStore,
)
from tests.xstate_contract.persist_fixtures import binding_persist  # noqa: F401

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP = _ROOT.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql"
_REGISTRY = Registry(machines_dir=_ROOT / "tests" / "xstate_contract" / "persist_fixtures")
_KIND = "persist_min"
_CHART = _REGISTRY.get(_KIND)
#: Integers, floats, unicode, nested lists and nulls: what must survive the jsonb round trip.
_PROBE = {"i": 7, "big": 2**63, "f": 0.1, "g": -2.25, "u": "é✓😀", "nested": [[1, [2.5, None]], []],
          "nul": None}  # fmt: skip
#: Scenario 7's DSN password: a value that must never reach an error message.
_UNREACHABLE_PW = "scenario7-not-a-secret"


class FixedKeys:
    """Fixed HMAC test keys, not real ones (no provider exists: a plan gap, #2701)."""

    def current(self) -> str:
        return "k1"

    def key(self, key_id: str) -> bytes:
        return {"k1": b"\x01" * 32}[key_id]


class Doubles:
    """In-memory `PersistAudit`, `RestoreAudit` and `Pager`."""

    def __init__(self) -> None:
        self.quarantined: list[tuple[MachineKey, str]] = []
        self.pages: list[str] = []

    async def drain_error(self, key: MachineKey, error: str) -> None: ...

    async def persist_refused(self, key: MachineKey, reason: str) -> None: ...

    async def quarantine(self, key: MachineKey, envelope: SealedSnapshot, reason: str) -> None:
        self.quarantined.append((key, reason))

    async def page(self, key: MachineKey, severity: str, message: str) -> None:
        self.pages.append(severity)


def _login(dsn: str, role: str) -> str:
    return re.sub(r"://[^@]+@", f"://{role}:{role}_test_pw@", dsn)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """Superuser DSN of a database set up like production: `pg_bootstrap.sql` first, then the
    migrations as `cv_owner` (the CI `migrations` order), so the default privileges apply."""
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        info = psycopg.conninfo.conninfo_to_dict(dsn.replace("postgresql+asyncpg", "postgresql"))
        psql = shutil.which("psql")
        assert psql is not None, "the CI integration and migrations jobs have postgresql-client"
        subprocess.run(  # noqa: S603 -- resolved absolute path, fixed argv, no shell (#3793)
            [psql, "-h", str(info["host"]), "-p", str(info["port"]), "-U", str(info["user"]),
             "-d", "candleviewer", "-v", "ON_ERROR_STOP=1", "-v", "owner_pw=cv_owner_test_pw",
             "-v", "app_pw=cv_app_test_pw", "-v", "ro_pw=cv_ro_test_pw", "-f", str(_BOOTSTRAP)],
            check=True, capture_output=True,
            env={**os.environ, "PGPASSWORD": str(info["password"])},
        )  # fmt: skip
        owner = _login(dsn, "cv_owner").replace("postgresql+asyncpg", "postgresql+psycopg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={**os.environ, "CV_PG_DSN": owner},
            check=True,
        )
        yield dsn


def _sql(dsn: str, query: str, *args: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        cursor = c.execute(query, args)
        return cursor.fetchall() if cursor.description else []


@dataclass
class Stores:
    snapshots: SnapshotAdapter
    journal: JournalRowsAdapter
    events: EventsAdapter
    doubles: Doubles

    def persister(self) -> Persister:
        return Persister(
            repo=self.snapshots,
            journal=RowStoreDrainJournal(self.journal),
            audit=self.doubles,
            seal=hmac_sealer(FixedKeys(), _CHART),
            machine_hash_of=_REGISTRY.hash,
        )

    def restorer(self, seen: list[MachineKey]) -> Restorer:
        def plugins(key: MachineKey) -> Sequence[Any]:
            seen.append(key)
            return []

        return Restorer(
            registry=_REGISTRY, keys=FixedKeys(), journal=RowStoreDrainJournal(self.journal),
            audit=self.doubles, pager=self.doubles, latch=ChainTripLatch(), plugins=plugins,
            clock=default_clock(), lane="platform",
        )  # fmt: skip


@pytest_asyncio.fixture
async def stores(pg_dsn: str) -> AsyncIterator[Stores]:
    """The stores as `cv_app`, the production role, behind the composition root's adapters."""
    rel = SqlAlchemyRelationalRepository(_login(pg_dsn, "cv_app"), "statechart")
    try:
        yield Stores(
            SnapshotAdapter(SqlAlchemySnapshotStore(rel)),
            JournalRowsAdapter(SqlAlchemyJournalStore(rel)),
            EventsAdapter(SqlAlchemyEventStore(rel)),
            Doubles(),
        )
    finally:
        await rel.dispose()


def _key(env: str = "demo") -> MachineKey:
    return MachineKey(_KIND, str(uuid.uuid4()), env)


async def _persist(stores: Stores, key: MachineKey, *, drain: bool = False) -> None:
    """Build through `factory.build`, then persist at quiescence. With `drain`, two inbox events
    and one priority event are queued first: `send` enqueues before it returns, and nothing is
    awaited before the drain, so the machine has not consumed them."""
    built = await build(_KIND, clock=default_clock(), lane="platform", registry=_REGISTRY)
    interp = built.interpreter
    interp.context["probe"] = _PROBE
    if drain:
        interp.send("PING", n="inbox-1")
        interp.send("PING", n="inbox-2")
        interp.send("PING", priority=True, n="prio-1")
    await stores.persister().persist(interp, key=key)


def _row(dsn: str, key: MachineKey) -> list[tuple[Any, ...]]:
    return _sql(
        dsn,
        "SELECT machine_kind, entity_id, env, snapshot::text, hmac_key_id, hmac_tag, state_ids, "
        "chain_trips, updated_at FROM machine_snapshots WHERE machine_kind = %s AND entity_id = %s",
        key.machine_kind, key.entity_id,
    )  # fmt: skip


async def test_snapshot_drain_and_restore_through_the_real_repositories(
    stores: Stores, pg_dsn: str
) -> None:
    """Scenario 1: the seal verifies for the key the three columns give, after jsonb."""
    key, seen = _key(), list[MachineKey]()
    await _persist(stores, key)
    ((kind, entity, env, *_),) = _row(pg_dsn, key)
    from_columns = MachineKey(kind, entity, env)
    envelope = await stores.snapshots.load(from_columns)
    assert envelope is not None and envelope.key == key
    blob = open_sealed(
        FixedKeys(), _CHART, envelope, key=from_columns, expected_machine_hash=_REGISTRY.hash(_KIND)
    )
    assert blob["context"]["probe"] == _PROBE
    restored = await stores.restorer(seen).restore(from_columns, envelope)
    try:
        assert seen == [key] and restored.interpreter.last_transition_ok is not None
        assert restored.interpreter.is_running and not restored.degraded
        assert restored.interpreter.context["probe"] == _PROBE
    finally:
        await restored.interpreter.stop()


async def test_the_drain_journal_replays_exactly_once_after_restore(
    stores: Stores, pg_dsn: str
) -> None:
    """Scenario 2: priority first, in `ordinal` order, stamped; a second replay re-enqueues
    nothing; a retried append leaves each `send_id` once, and stamped."""
    key = _key()
    await _persist(stores, key, drain=True)
    pending = list(await stores.journal.list_unreplayed(key))
    assert [(e.lane, e.ordinal, e.record["payload"]["n"]) for e in pending] == [
        ("priority", 0, "prio-1"), ("inbox", 1, "inbox-1"), ("inbox", 2, "inbox-2"),
    ]  # fmt: skip
    envelope = await stores.snapshots.load(key)
    assert envelope is not None
    restored = await stores.restorer([]).restore(key, envelope)
    try:
        assert restored.replayed == 3
        await asyncio.wait_for(restored.interpreter.send("PING", wait=True, n="after"), 5)
        assert restored.interpreter.context["seen"] == ["prio-1", "inbox-1", "inbox-2", "after"]
        assert (
            await RowStoreDrainJournal(stores.journal).replay_once(key, restored.interpreter) == 0
        )
    finally:
        await restored.interpreter.stop()
    journal = (
        "SELECT count(*), count(replayed_at), count(DISTINCT send_id) FROM machine_drain_journal "
        "WHERE machine_kind = %s AND entity_id = %s AND env = %s"
    )
    assert _sql(pg_dsn, journal, key.machine_kind, key.entity_id, key.env) == [(3, 3, 3)]
    await stores.journal.append(key, pending)
    assert _sql(pg_dsn, journal, key.machine_kind, key.entity_id, key.env) == [(3, 3, 3)]


_EVERY_ROW = (
    "SELECT machine_kind, entity_id, env, updated_at FROM machine_snapshots ORDER BY 1, 2, 3"
)


@pytest.mark.parametrize(
    "change",
    [
        {"machine_kind": "trade_group"},
        {"entity_id": "0a000000-0000-4000-8000-0000000000ff"},
        {"env": "live"},
        {"entity_id": ""},
    ],
    ids=["kind", "entity", "env", "empty entity"],
)
async def test_the_snapshot_store_refuses_an_envelope_sealed_for_another_key(
    stores: Stores, pg_dsn: str, change: dict[str, str]
) -> None:
    """Scenario 3: `SnapshotKeyMismatchError` before any transaction; no row added or changed."""
    sealed_for = _key()
    await _persist(stores, sealed_for)
    envelope = await stores.snapshots.load(sealed_for)
    assert envelope is not None
    row_key = replace(sealed_for, **change)
    if not row_key.entity_id:
        envelope = replace(envelope, key=row_key)  # agrees with the row, and '' is still refused
    before = _sql(pg_dsn, _EVERY_ROW)
    with pytest.raises(SnapshotKeyMismatchError):
        await stores.snapshots.write_snapshot(row_key, envelope)
    assert _sql(pg_dsn, _EVERY_ROW) == before


_TAMPER = {
    "snapshot bytes": "UPDATE machine_snapshots SET snapshot = jsonb_set(snapshot, "
    "'{context,seen}', '[\"forged\"]') WHERE entity_id = %s",
    "tag": "UPDATE machine_snapshots SET hmac_tag = decode(repeat('00', 32), 'hex') "
    "WHERE entity_id = %s",
    "env column": "UPDATE machine_snapshots SET env = 'testnet' WHERE entity_id = %s",
}


@pytest.mark.parametrize("tamper", _TAMPER)
async def test_a_tampered_row_is_refused_by_the_restorer_never_repaired(
    stores: Stores, pg_dsn: str, tamper: str
) -> None:
    """Scenario 4: `RestoreRefusedError`, the quarantine recorded, `machine_snapshots` as the
    tampering left it."""
    key = _key()
    await _persist(stores, key)
    _sql(pg_dsn, _TAMPER[tamper], key.entity_id)
    ((kind, entity, env, *_),) = _row(pg_dsn, key)
    from_columns = MachineKey(kind, entity, env)
    envelope = await stores.snapshots.load(from_columns)
    assert envelope is not None
    before = _row(pg_dsn, key)
    with pytest.raises(RestoreRefusedError):
        await stores.restorer([]).restore(from_columns, envelope)
    assert [k for k, _ in stores.doubles.quarantined] == [from_columns]
    assert stores.doubles.pages == ["P1"] and _row(pg_dsn, key) == before


async def test_the_inspector_list_is_served_by_the_same_store(stores: Stores) -> None:
    """Scenario 5: `SnapshotRow`s with the environment, a tz-aware `updated_at` and envelopes
    that `open_sealed` verifies; the singleton's `entity_id` is `None`."""
    single, other = MachineKey(_KIND, _KIND, "testnet"), _key()
    await _persist(stores, single)
    await _persist(stores, other)
    rows: dict[MachineKey, SnapshotRow] = {
        MachineKey(r.machine_kind, r.entity_id or r.machine_kind, r.environment): r
        for r in await stores.snapshots.snapshots()
    }
    assert rows[single].entity_id is None and rows[other].entity_id == other.entity_id
    assert (rows[single].environment, rows[other].environment) == ("testnet", "demo")
    for key in (single, other):
        assert rows[key].updated_at.utcoffset() is not None
        expected = _REGISTRY.hash(_KIND)
        open_sealed(
            FixedKeys(), _CHART, rows[key].envelope, key=key, expected_machine_hash=expected
        )


def _chain(entity: str, n: int) -> list[MachineEventRow]:
    rows: list[MachineEventRow] = []
    prev = GENESIS_HASH
    for i in range(n):
        at = datetime(2026, 10, 19, 12, 0, i, 123456, tzinfo=UTC).isoformat()
        row = MachineEventRow(
            machine_kind=_KIND, entity_id=entity, env="demo", event_type="PING",
            payload={"i": i, "f": 0.25 * i + 0.1, "u": "é✓😀", "nested": [[i, [1.5, None]], []],
                     "nul": None},
            from_states=["persist_min.idle"], to_states=["persist_min.idle"],
            actions_run=["record"], fault=None, occurred_at=at, phase="commit", prev_hash=prev,
        )  # fmt: skip
        row = replace(row, row_hash=row_digest(row))
        rows.append(row)
        prev = row.row_hash
    return rows


async def test_the_events_store_returns_what_it_stored_byte_for_byte(stores: Stores) -> None:
    """Scenario 6: inserted twice, each row once, in order; `verify_chain`; the head."""
    key = _key()
    rows = _chain(key.entity_id, 5)
    await stores.events.insert_batch(rows)
    await stores.events.insert_batch(rows)
    back = await stores.events.chain(key)
    assert back == rows and verify_chain(back)
    assert await stores.events.head(key) == rows[-1].row_hash
    assert await stores.events.head(_key()) == GENESIS_HASH


def _calls() -> dict[str, Callable[[SqlAlchemyRelationalRepository], Awaitable[object]]]:
    key, now = ("o", "e", "demo"), datetime.now(UTC)
    snap = SnapshotRecord(*key, 2, 3, "a" * 64, {}, "k1", bytes(32), (), 0, now)
    journal = JournalRecord("b" * 32, "inbox", 0, "PING", {})
    event = EventRecord(*key, "PING", {}, (), (), (), None, now, "commit", "0" * 64, "c" * 64)
    return {
        "snapshots.upsert": lambda r: SqlAlchemySnapshotStore(r).upsert(snap),
        "snapshots.get": lambda r: SqlAlchemySnapshotStore(r).get(*key),
        "snapshots.list_all": lambda r: SqlAlchemySnapshotStore(r).list_all(),
        "journal.append": lambda r: SqlAlchemyJournalStore(r).append(*key, [journal]),
        "journal.list_unreplayed": lambda r: SqlAlchemyJournalStore(r).list_unreplayed(*key),
        "journal.mark_replayed": lambda r: SqlAlchemyJournalStore(r).mark_replayed(*key, ["b"]),
        "events.insert_batch": lambda r: SqlAlchemyEventStore(r).insert_batch([event]),
        "events.head": lambda r: SqlAlchemyEventStore(r).head(*key),
        "events.read_chain": lambda r: SqlAlchemyEventStore(r).read_chain(*key),
    }


@pytest_asyncio.fixture
async def silent_server() -> AsyncIterator[int]:
    """A port that accepts a connection and never answers it."""

    async def hold(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.read()
        finally:
            writer.close()

    server = await asyncio.start_server(hold, "127.0.0.1", 0)
    try:
        yield int(server.sockets[0].getsockname()[1])
    finally:
        server.close()


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.mark.parametrize("unreachable", ["refused", "silent"])
async def test_a_store_that_cannot_reach_postgres_fails_within_its_bound(
    unreachable: str, silent_server: int
) -> None:
    """Scenario 7: every store method raises `StorageTierUnavailable` within STORE_TIMEOUT_S plus
    one second (the client deadline, plus scheduling slack), naming the SQLSTATE or `unknown`,
    never a statement or a parameter."""
    port = silent_server if unreachable == "silent" else _closed_port()
    dsn = f"postgresql+asyncpg://cv:{_UNREACHABLE_PW}@127.0.0.1:{port}/x"
    rel = SqlAlchemyRelationalRepository(dsn, "statechart")
    calls = _calls()

    async def timed(name: str) -> tuple[str, float, BaseException | None]:
        started = time.monotonic()
        try:
            await calls[name](rel)
        except Exception as exc:  # any: the assertions below say which one is right
            return name, time.monotonic() - started, exc
        return name, time.monotonic() - started, None

    try:
        results = await asyncio.gather(*(timed(name) for name in calls))
    finally:
        await rel.dispose()
    for name, elapsed, exc in results:
        assert isinstance(exc, StorageTierUnavailable), (name, exc)
        assert elapsed < STORE_TIMEOUT_S + 1 + 0.5, (name, elapsed)
        text = str(exc)
        assert re.search(r"\(sqlstate (?:[0-9A-Z]{5}|unknown)\)$", text), text
        assert "SELECT" not in text and "INSERT" not in text and _UNREACHABLE_PW not in text
