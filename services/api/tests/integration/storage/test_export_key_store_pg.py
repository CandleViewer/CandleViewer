"""Integration: `SqlAlchemyExportKeyStore` on real Postgres 16 (#889 S4b), in the container and at
the revision of S4a's file (`0046_audit_signing_keys`, migrated as `cv_owner`), run as `cv_app`, so
every write passes `trg_audit_signing_keys_write_once`. Placeholder bytes, never key material;
needs docker, and `psql` for `pg_bootstrap.sql` (CI runners ship it)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest

from candleviewer.secrets.store import EXPORT_KEY_PUBLIC, EXPORT_KEY_SEALED
from candleviewer.storage.errors import (
    ExportKeyAuditNotWritten,
    ExportKeyRequestTaken,
    StorageQueryFailed,
)
from candleviewer.storage.repositories.export_keys_sqlalchemy import SqlAlchemyExportKeyStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.integration.storage.test_audit_signing_keys_pg import _REV, _as, _at, _exec, pg
from tests.unit.credentials_m2.test_export_key_store import (
    DESTROYED,
    GENERATED,
    MOVE,
    NEXT_WRAP,
    ROTATED,
    SEED,
    WRAP,
    export_key,
    key_id,
    rotation_request,
)

pytestmark = pytest.mark.integration
__all__ = ["pg"]  # S4a's module-scoped Postgres 16: a fresh container for this module
Store = SqlAlchemyExportKeyStore
Rows = list[tuple[Any, ...]]
_USER = (
    "INSERT INTO users (id, email, username, password_hash) "
    "VALUES (gen_random_uuid(), %s, %s, '$argon2id$x') RETURNING id"
)
#: The whole table, and how long the chain is: what a failed rotation must leave as it was.
_STATE = (
    "SELECT (SELECT array_agg(k::text ORDER BY k.version) FROM audit_signing_keys k), "
    "(SELECT count(*) FROM audit_log)"
)
_WAITING = "SELECT count(*) FROM pg_stat_activity WHERE usename='cv_app' AND wait_event_type='Lock'"


class Records:
    """The WAL format `secrets_audit_row` builds, without its action registry (S6 registers the
    generation's and the rotation's), keeping each record built; `reuse` repeats a record id."""

    def __init__(self, env: str = "demo") -> None:
        self.env, self.reuse = env, ""
        self.built: list[dict[str, Any]] = []

    def __call__(self, action: str, fields: dict[str, str]) -> dict[str, Any]:
        row = {"record_id": self.reuse or str(uuid4()), "actor_label": "system:", "action": action,
               "outcome": "success", "severity": "info", "env": self.env, "after_state": fields,
               "event_ts": datetime.now(UTC).isoformat()}  # fmt: skip
        self.built.append(row)
        return row


@pytest.fixture(autouse=True)
def _head_and_empty(pg: str) -> None:
    _at(pg, _REV)
    _exec(pg, "TRUNCATE audit_signing_keys")


def _pool(pg: str, role: str) -> SqlAlchemyRelationalRepository:
    dsn = _as(pg, role).replace("postgresql:", "postgresql+asyncpg:")
    return SqlAlchemyRelationalRepository(dsn)


@pytest.fixture
async def rel(pg: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    """The runtime role's pool, as the app wires the store."""
    repo = _pool(pg, "cv_app")
    yield repo
    await repo.dispose()


@pytest.fixture
def records() -> Records:
    return Records()


@pytest.fixture
def store(rel: SqlAlchemyRelationalRepository, records: Records) -> Store:
    return Store(rel, env="demo", audit_row=records)


def _user(pg: str) -> UUID:
    """A rotating Owner (`created_by` references `users`)."""
    name = uuid4().hex[:12]
    return UUID(str(_exec(pg, _USER, (f"{name}@x.io", name))[0][0]))


def _event_ts(pg: str, record: dict[str, Any]) -> Rows:
    return _exec(pg, "SELECT event_ts FROM audit_log WHERE record_id = %s", (record["record_id"],))


async def _rotate(
    store: Store, version: int, owner: UUID, *, env: str = "demo", ref: str = "", retire: int = 0,
    pk: bytes | None = None,
) -> Any:  # fmt: skip
    """Key `version` of `env`, made active for `owner`'s request `ref` by retiring key `retire`."""
    record = export_key(version, env=env, pk=pk, **rotation_request(owner, ref or None))
    retiring = key_id(retire or version - 1)
    return await store.rotate(record, retire=retiring, reason="compromise", audit=ROTATED)


async def test_a_rotation_commits_with_its_record_at_the_records_time(
    pg: str, store: Store, records: Records, rel: SqlAlchemyRelationalRepository
) -> None:
    """And `active` reads the process environment's sealed key: none, v1, then v2."""
    owner, ref = _user(pg), str(uuid4())
    assert await store.active("demo") is None  # an empty table
    live = Store(rel, env="live", audit_row=Records("live"))
    await live.insert_first(export_key(1, env="live", pk=bytes(32)), audit=GENERATED)
    assert await store.active("demo") is None  # a live key only
    assert await store.insert_first(export_key(1), audit=GENERATED) is True
    first = await store.active("demo")
    made = await _rotate(store, 2, owner, ref=ref)
    [(generated,)], [(rotated,)] = (_event_ts(pg, r) for r in records.built)
    q = (
        "SELECT status, sealed_seed IS NULL, valid_from, valid_until, retired_reason "
        "FROM audit_signing_keys WHERE env = 'demo' ORDER BY version"
    )
    assert _exec(pg, q) == [
        ("retired", True, generated, rotated, "compromise"),  # its seed destroyed with it (Q3)
        ("active", False, rotated, None, None),
    ]
    assert made == await store.rotation("demo", created_by=owner, client_ref=ref)
    for version, key in enumerate((first, await store.active("demo")), 1):
        assert key is not None and tuple(key) == EXPORT_KEY_SEALED  # the record S6 opens
        assert (key["env"], key["key_id"], key["sealed_seed"]) == ("demo", key_id(version), SEED)


@pytest.mark.parametrize(
    ("again", "retire", "version", "pk", "refused"),
    [
        (False, 9, 2, None, None),  # `retire` is not the active key: no rotation
        (True, 1, 3, None, None),  # a replay: v1 is retired already
        (False, 1, 3, None, ValueError),  # under the row lock: a version gap
        (False, 1, 2, bytes([1]) * 32, StorageQueryFailed),  # the insert: v1's fingerprint (23505)
        (False, 1, 2, None, ExportKeyAuditNotWritten),  # the record: its id is stored already
        (True, 2, 3, None, ExportKeyRequestTaken),  # the request again: a retry that raced
    ],
    ids=["stale", "replay", "version", "insert", "record", "request"],
)
async def test_a_rotation_failing_at_any_step_changes_nothing(
    pg: str,
    store: Store,
    records: Records,
    again: bool,
    retire: int,
    version: int,
    pk: bytes | None,
    refused: type[Exception] | None,
) -> None:
    await store.insert_first(export_key(1), audit=GENERATED)
    owner, ref = _user(pg), str(uuid4())
    if again:  # a rotation to v2 with this request committed first
        await _rotate(store, 2, owner, ref=ref)
    records.reuse = records.built[0]["record_id"] if refused is ExportKeyAuditNotWritten else ""
    before = _exec(pg, _STATE)
    if refused is None:
        assert await _rotate(store, version, owner, ref=ref, retire=retire, pk=pk) is None
    else:
        with pytest.raises(refused) as failed:
            await _rotate(store, version, owner, ref=ref, retire=retire, pk=pk)
        assert failed.value.__context__ is None and "ek1:" not in repr(failed.value)
    assert _exec(pg, _STATE) == before  # the active key as it was, with its seed


@pytest.fixture
async def gate(pg: str) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    """Each key insert parks on advisory lock 889, held here until the test lets go: no sleep."""
    _exec(
        pg,
        "CREATE FUNCTION park() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
        "PERFORM pg_advisory_xact_lock_shared(889); RETURN NULL; END $$; CREATE TRIGGER "
        "trg_park AFTER INSERT ON audit_signing_keys FOR EACH ROW EXECUTE FUNCTION park()",
    )
    async with await psycopg.AsyncConnection.connect(pg, autocommit=True) as holder:
        await holder.execute("SELECT pg_advisory_lock(889)")
        yield holder
    _exec(pg, "DROP FUNCTION park() CASCADE")


async def test_two_concurrent_first_boots_insert_one_key(
    pg: str, store: Store, records: Records, gate: Any
) -> None:
    """The second boot's v1 waits on the first's, then meets `ask_env_version`: it lost, False."""
    firsts = (export_key(1, pk=bytes([n]) * 32) for n in (1, 2))
    boots = asyncio.gather(*(store.insert_first(k, audit=GENERATED) for k in firsts))
    async with asyncio.timeout(30):  # fails a missed wait fast
        while await (await gate.execute(_WAITING)).fetchone() != (2,):
            pass
    await gate.execute("SELECT pg_advisory_unlock(889)")
    assert sorted(await boots) == [False, True]
    assert _exec(pg, "SELECT count(*) FROM audit_signing_keys") == [(1,)]
    assert [bool(_event_ts(pg, r)) for r in records.built].count(True) == 1  # one generation


async def test_two_rotations_of_one_key_make_one_successor(
    pg: str, store: Store, records: Records, gate: Any
) -> None:
    """One parks past its retire; the other waits on v1's row lock, then reads it retired: None."""
    await gate.execute("SELECT pg_advisory_unlock(889)")  # open while v1 goes in
    await store.insert_first(export_key(1), audit=GENERATED)
    await gate.execute("SELECT pg_advisory_lock(889)")
    rotations = asyncio.gather(*(_rotate(store, 2, _user(pg), pk=bytes([n]) * 32) for n in (2, 3)))
    async with asyncio.timeout(30):
        while await (await gate.execute(_WAITING)).fetchone() != (2,):
            pass
    await gate.execute("SELECT pg_advisory_unlock(889)")
    assert sorted(made is None for made in await rotations) == [False, True]
    q = "SELECT version, status FROM audit_signing_keys ORDER BY version"
    assert _exec(pg, q) == [(1, "retired"), (2, "active")]
    assert [bool(_event_ts(pg, r)) for r in records.built[1:]].count(True) == 1  # one rotation


async def test_the_rewrap_compares_and_sets_on_keys_holding_their_seed(
    pg: str, store: Store, records: Records
) -> None:
    """S6a: the move commits with its record, and the trigger refuses a DEK kept (S4b's F1)."""
    await store.insert_first(export_key(1), audit=GENERATED)
    await _rotate(store, 2, _user(pg))  # v1 retired, its seed destroyed
    assert not await store.rewrap(key_id(1), **MOVE)  # no seed: nothing to re-wrap (Q3)
    assert not await store.rewrap(key_id(2), **MOVE | {"from_version": 3})  # stale
    with pytest.raises(StorageQueryFailed, match="23514") as refused:
        await store.rewrap(key_id(2), **MOVE | {"dek_ref": WRAP})
    assert refused.value.__context__ is None and "ek1:" not in repr(refused.value)  # C-12.6
    assert await store.rewrap(key_id(2), **MOVE) is True  # past the guard
    assert not await store.rewrap(key_id(2), **MOVE)  # a replay: it moved on
    q = "SELECT version, kek_version, dek_ref FROM audit_signing_keys ORDER BY version"
    assert _exec(pg, q) == [(1, 1, WRAP), (2, 2, NEXT_WRAP)]
    assert [await store.count_at_kek_version(v, "demo") for v in (1, 2)] == [0, 1]
    assert [bool(_event_ts(pg, r)) for r in records.built[2:]] == [False] * 3 + [True, False]


async def test_a_retired_key_holding_its_seed_counts_until_its_destroy(
    pg: str, store: Store, rel: SqlAlchemyRelationalRepository, records: Records
) -> None:
    await store.insert_first(export_key(1), audit=GENERATED)
    await Store(rel, env="live", audit_row=Records("live")).insert_first(
        export_key(1, env="live"), audit=GENERATED
    )
    # A retire that kept the seed, which the table admits and the store never writes (Q3).
    _exec(
        _as(pg, "cv_app"),
        "UPDATE audit_signing_keys SET status = 'retired', valid_until = now(), "
        "retired_reason = 'scheduled'",
    )
    assert await store.count_retired_with_seed("demo") == 1
    assert await store.count_at_kek_version(1, "demo") == 1  # a KEK re-wrap waits for it (I2)
    assert await store.destroy_retired_seeds("demo", audit=DESTROYED) == 1
    assert await store.count_retired_with_seed("demo") == 0
    assert await store.destroy_retired_seeds("demo", audit=DESTROYED) == 0  # nothing left
    assert [bool(_event_ts(pg, r)) for r in records.built[1:]] == [True, False]  # S6a's record
    q = "SELECT env::text, sealed_seed IS NULL FROM audit_signing_keys ORDER BY 1"
    assert _exec(pg, q) == [("demo", True), ("live", False)]  # the process environment's only


async def test_the_idempotency_read_is_the_owners_in_its_environment_at_any_age(
    pg: str, store: Store, rel: SqlAlchemyRelationalRepository
) -> None:
    owner, other, ref, live_only = _user(pg), _user(pg), str(uuid4()), str(uuid4())
    live = Store(rel, env="live", audit_row=Records("live"))
    await live.insert_first(export_key(1, env="live"), audit=GENERATED)
    await _rotate(live, 2, owner, env="live", ref=ref)  # the same Owner and key, in live
    await _rotate(live, 3, owner, env="live", ref=live_only)
    await store.insert_first(export_key(1), audit=GENERATED)
    made = await _rotate(store, 2, owner, ref=ref)
    await _rotate(store, 3, other)  # later, the key that rotation made retires in turn
    assert await store.rotation("demo", created_by=other, client_ref=ref) is None
    assert await store.rotation("demo", created_by=owner, client_ref=live_only) is None
    again = await store.rotation("demo", created_by=owner, client_ref=ref.upper())  # canonical
    assert again == made and again is not None and again["active"]["status"] == "active"
    assert again["client_body_sha256"] == "a" * 64  # S7 compares it: 409 on another body


async def test_the_public_reads_never_name_the_seed_or_its_wrap(pg: str, store: Store) -> None:
    """As `cv_ro`, left every column but `sealed_seed` and `dek_ref`: Postgres checks each column
    a statement names, so a read naming either is refused (42501), and these are not."""
    owner, ref = _user(pg), str(uuid4())
    await store.insert_first(export_key(1), audit=GENERATED)
    made = await _rotate(store, 2, owner, ref=ref)
    _exec(
        pg,
        "REVOKE SELECT ON audit_signing_keys FROM cv_ro; GRANT SELECT (id, env, version, key_id, "
        "public_key, fingerprint_sha256, kek_version, status, valid_from, valid_until, "
        "retired_reason, created_by, client_ref, client_body_sha256, created_at) "
        "ON audit_signing_keys TO cv_ro",
    )
    pool = _pool(pg, "cv_ro")
    try:
        public = Store(pool, env="demo", audit_row=Records())
        listed = await public.list_keys("demo")
        assert [r["version"] for r in listed] == [2, 1]  # newest first
        assert {tuple(r) for r in listed} == {EXPORT_KEY_PUBLIC}
        assert await public.rotation("demo", created_by=owner, client_ref=ref) == made
        with pytest.raises(StorageQueryFailed) as refused:
            await public.active("demo")  # it names the seed: the column check is live
        assert refused.value.sqlstate == "42501"
    finally:
        await pool.dispose()
