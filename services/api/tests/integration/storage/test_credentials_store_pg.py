"""Integration: `SqlAlchemyCredentialStore` + `CredentialBroker` on real Postgres 16 (#835).

Exercises the real SQL the unit fakes stand in for: insert/get/borrow, revoke, keyset paging,
the rewrap compare-and-set (incl. a concurrent writer), kill-and-resume over 50 rows,
`kek_versions` record/re-read and `last_used_at` touch. Fixed test vectors only; no network
beyond the local testcontainer. Not run locally (no docker); CI integration lane.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
import sqlalchemy as sa
from psycopg import sql
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.wiring import secrets_audit_row
from candleviewer.audit.actions import UnknownAuditAction
from candleviewer.secrets import KEY_ID_SLOT
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets._rotation import RotatingBroker as CredentialBroker
from candleviewer.secrets.errors import CredentialUnavailable, SnapshotInvalid
from candleviewer.secrets.secret import Secret
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.unit.credentials_m2._vectors import AuditLog

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_SNAP: dict[str, Any] = {"uid": "1", "permissions": {"ContractTrade": ["Order"], "Wallet": []}}
_REWRAPPED = "security.credential_rewrapped"
_ENROLLED = "security.kek_enrolled"
_CHAIN_LOCK = "SELECT pg_advisory_xact_lock(hashtext('audit_log'))"
_TERMINATE = "SELECT pg_terminate_backend(%s)"
#: A backend waiting for the chain lock while it holds the api_keys lock of an UPDATE it ran.
_WAITER = (
    "SELECT w.pid FROM pg_locks w JOIN pg_locks r ON r.pid = w.pid "
    "WHERE w.locktype = 'advisory' AND NOT w.granted "
    "AND r.relation = 'api_keys'::regclass AND r.mode = 'RowExclusiveLock' AND r.granted"
)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={
                **os.environ,
                "CV_PG_DSN": url.replace("postgresql+psycopg2", "postgresql+psycopg"),
            },
            check=True,
        )
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


def _account(dsn: str, env: str = "demo") -> UUID:
    acct = uuid4()
    uid = str(abs(hash(acct)) % 10**12)
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        c.execute(
            "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
            "VALUES (%s, 'bybit', %s::exchange_env, 'main', %s, %s)",
            (acct, env, uid, f"acct-{acct}"),
        )
    return acct


async def _audit(action: str, fields: dict[str, str]) -> None:
    return None


def _kek(seed: int, version: int, env: str = "demo") -> LoadedKek:
    return LoadedKek(bytearray(range(seed, seed + 32)), version, env_name=env)


async def _seed(store: SqlAlchemyCredentialStore, acct: UUID, n: int) -> list[UUID]:
    """`n` keys; key 0 on `acct`, the rest on fresh accounts (`ux_api_keys_active` allows one
    active key per account)."""
    b = CredentialBroker(store, _audit, _kek(0, 1))
    out = []
    for i in range(n):
        owner = acct if i == 0 else _account(store_dsn(store))
        meta = await b.store("demo", owner, f"k{i}", Secret(f"KEY{i:04d}ABCD"), Secret("S"), _SNAP)
        out.append(meta.key_id)
    _activate(store_dsn(store), out)
    return out


_DSNS: dict[int, str] = {}


def store_dsn(store: SqlAlchemyCredentialStore) -> str:
    return _DSNS[id(store)]


def _store(dsn: str) -> tuple[SqlAlchemyRelationalRepository, SqlAlchemyCredentialStore]:
    rel = SqlAlchemyRelationalRepository(dsn)
    store = SqlAlchemyCredentialStore(rel, audit_row=secrets_audit_row("demo"))
    _DSNS[id(store)] = dsn
    return rel, store


def _activate(dsn: str, ids: list[UUID], status: str = "active") -> None:
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        for k in ids:
            c.execute("UPDATE api_keys SET status = %s::key_status WHERE id = %s", (status, k))


def _sql(dsn: str, query: str, *params: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        cur = c.execute(query, params)
        return cur.fetchall() if cur.description else []


def _wrap(dsn: str, key_id: UUID) -> tuple[Any, ...]:
    return _sql(dsn, "SELECT kek_version, dek_ref FROM api_keys WHERE id = %s", key_id)[0]


def _records(dsn: str, key_id: UUID) -> list[tuple[Any, ...]]:
    """`(action, env, after_state)` of every audit record about `key_id`."""
    query = "SELECT action, env::text, after_state FROM audit_log WHERE object_id = %s ORDER BY id"
    return _sql(dsn, query, str(key_id))


def _move(key_id: UUID, ref: str, action: str = _REWRAPPED, **cas: Any) -> dict[str, Any]:
    """`rewrap` kwargs of a run's v1 -> v2 compare-and-set of `key_id`, with its row record."""
    fields = {"key_id": str(key_id), "actor_kind": "system", "actor_role": "secrets"}
    fields |= cas.pop("fields", {})
    return {"env": "demo", "from_version": 1, "dek_ref": ref, "kek_version": 2, **cas} | {
        "audit": (action, fields)
    }


async def _enrol(
    store: SqlAlchemyCredentialStore, env: str, version: int, kcv: bytes
) -> tuple[bytes, bool]:
    """`record_kcv` with the record `verify_kcv` commits with the row (#2266)."""
    fields = {"actor_kind": "system", "actor_role": "secrets", "env": env, "kcv": kcv.hex()}
    return await store.record_kcv(env, version, kcv, audit=(_ENROLLED, fields))


def _enrolments(dsn: str, kcv: bytes) -> list[tuple[Any, ...]]:
    """The `security.kek_enrolled` records of `kcv` (`kek_version` is redacted in the state)."""
    query = "SELECT env::text FROM audit_log WHERE action = %s AND after_state->>'kcv' = %s"
    return _sql(dsn, query, _ENROLLED, kcv.hex())


@pytest.fixture
async def one_key(pg_dsn: str) -> AsyncIterator[tuple[SqlAlchemyCredentialStore, UUID]]:
    rel, store = _store(pg_dsn)
    try:
        yield store, (await _seed(store, _account(pg_dsn), 1))[0]
    finally:
        await rel.dispose()


async def _borrow(b: CredentialBroker, key_id: UUID) -> str:
    """Sign through the exchange-adapter handle (#2339); returns the key id M2 hands back. The
    signing only starts its `last_used_at` write (#2776), so await it here: the row is read after
    it lands, and no write outlives the test or races `rel.dispose()`."""
    h = b.borrow_handle("exchange_adapter")
    out = await h.sign(key_id, (KEY_ID_SLOT,), purpose="sign_rest")
    await asyncio.gather(*b._touches.values())
    return out.api_key.reveal()


async def test_store_borrow_touch_revoke(pg_dsn: str) -> None:
    rel, store = _store(pg_dsn)
    try:
        acct = _account(pg_dsn)
        (key_id,) = await _seed(store, acct, 1)
        b = CredentialBroker(store, _audit, _kek(0, 1))
        assert await _borrow(b, key_id) == "KEY0000ABCD"
        with psycopg.connect(pg_dsn.replace("postgresql+asyncpg", "postgresql")) as c:
            row = c.execute(
                "SELECT last_used_at, octet_length(enc_nonce), key_id_last4 FROM api_keys "
                "WHERE id = %s",
                (key_id,),
            ).fetchone()
        assert row is not None and row[0] is not None and row[1] == 12 and row[2] == "ABCD"
        await b.destroy(key_id)
        rec = await store.get(key_id, "demo")
        assert rec is not None and rec["revoked"] is True
        assert key_id not in await store.ids_at_kek_version(1, 100, "demo")
    finally:
        await rel.dispose()


async def test_rewrap_kill_resume_and_keyset_over_50_rows(pg_dsn: str) -> None:
    rel, store = _store(pg_dsn)
    try:
        acct = _account(pg_dsn)
        ids = await _seed(store, acct, 50)
        before = {k: (await store.get(k, "demo"))["secret_enc"] for k in ids}  # type: ignore[index]
        real = store.rewrap
        calls = 0

        async def dying(key_id: UUID, **kw: Any) -> bool:
            nonlocal calls
            if calls == 20:
                raise asyncio.CancelledError  # a kill mid-run (not mapped to a typed error)
            calls += 1
            return await real(key_id, **kw)

        store.rewrap = dying  # type: ignore[method-assign]  # crash after 20 rows
        rot = CredentialBroker(store, _audit, _kek(100, 2), prev_kek=_kek(0, 1))
        with pytest.raises(asyncio.CancelledError):
            await rot.rewrap_all(2, batch=7)
        for k in ids:  # mixed state: every row still decrypts (prev or current KEK)
            assert (await _borrow(rot, k)).startswith("KEY")
        store.rewrap = real  # type: ignore[method-assign]
        rep = await CredentialBroker(store, _audit, _kek(100, 2), prev_kek=_kek(0, 1)).rewrap_all(
            2, batch=7
        )
        assert (rep.rewrapped, rep.remaining) == (30, 0)
        per_key = (
            "SELECT count(DISTINCT object_id), count(*) FROM audit_log WHERE object_id = ANY(%s)"
        )
        assert _sql(pg_dsn, per_key, [str(k) for k in ids]) == [(50, 50)]  # one per moved row
        only_v2 = CredentialBroker(store, _audit, _kek(100, 2))
        for k in ids:
            rec = await store.get(k, "demo")
            assert rec is not None and rec["kek_version"] == 2 and rec["secret_enc"] == before[k]
            await _borrow(only_v2, k)
    finally:
        await rel.dispose()


async def test_rewrap_cas_with_concurrent_writer(pg_dsn: str) -> None:
    rel, store = _store(pg_dsn)
    try:
        (key_id,) = await _seed(store, _account(pg_dsn), 1)
        rec = await store.get(key_id, "demo")
        assert rec is not None
        results = await asyncio.gather(
            store.rewrap(key_id, **_move(key_id, rec["dek_ref"])),
            store.rewrap(key_id, **_move(key_id, rec["dek_ref"])),
        )
        assert sorted(results) == [False, True] and len(_records(pg_dsn, key_id)) == 1
        await store.mark_revoked(key_id)
        assert not await store.rewrap(key_id, **_move(key_id, "x", from_version=2, kek_version=3))
    finally:
        await rel.dispose()


async def test_kcv_record_and_reread(pg_dsn: str) -> None:
    """Two boots enrol one version at once: one KCV is stored, and only the boot whose insert
    landed commits a `security.kek_enrolled` record, with the row (#2266)."""
    rel, store = _store(pg_dsn)
    try:
        assert await store.kcv_for("demo", 77) is None
        first, second = await asyncio.gather(
            _enrol(store, "demo", 77, b"A" * 8), _enrol(store, "demo", 77, b"B" * 8)
        )
        assert first[0] == second[0] and await store.kcv_for("demo", 77) == first[0]
        assert sorted((first[1], second[1])) == [False, True]
        records = [len(_enrolments(pg_dsn, kcv)) for kcv in (b"A" * 8, b"B" * 8)]
        assert sorted(records) == [0, 1] and len(_enrolments(pg_dsn, first[0])) == 1
        # #2338: (live, 77) is another lineage's key; it neither conflicts nor shadows demo's
        assert await _enrol(store, "live", 77, b"C" * 8) == (b"C" * 8, True)
        assert await store.kcv_for("demo", 77) == first[0]
    finally:
        await rel.dispose()


async def test_status_env_and_flags_from_real_rows(pg_dsn: str) -> None:
    rel, store = _store(pg_dsn)
    try:
        acct = _account(pg_dsn)
        (key_id,) = await _seed(store, acct, 1)
        rec = await store.get(key_id, "demo")
        assert rec is not None and rec["env"] == "demo" and rec["status"] == "active"
        # SR-E27-14: the borrow's C-2.8 re-check reads real bools and a decoded jsonb dict
        assert rec["can_withdraw"] is False and rec["can_transfer"] is False
        assert isinstance(rec["permission_snapshot"], dict)
        _activate(pg_dsn, [key_id], "invalid")
        with pytest.raises(CredentialUnavailable):
            await _borrow(CredentialBroker(store, _audit, _kek(0, 1)), key_id)
        b = CredentialBroker(store, _audit, _kek(0, 1))
        with pytest.raises(CredentialUnavailable) as ei:  # M2 refuses another env up front
            await b.store("live", acct, "x", Secret("KEYXABCD"), Secret("S"), _SNAP)
        assert str(ei.value) == "environment_mismatch"
        live = CredentialBroker(store, _audit, _kek(50, 1, "live"), env_name="live")
        with pytest.raises(CredentialUnavailable) as ei:  # and the M10 insert refuses too
            await live.store("live", acct, "x", Secret("KEYXABCD"), Secret("S"), _SNAP)
        assert str(ei.value) == "store_unavailable"
    finally:
        await rel.dispose()


async def test_kcv_unique_and_versions(pg_dsn: str) -> None:
    rel, store = _store(pg_dsn)
    try:
        await _enrol(store, "demo", 90, b"U" * 8)
        with pytest.raises(Exception):  # noqa: B017 -- kv_kcv_unique IntegrityError
            await _enrol(store, "live", 91, b"U" * 8)  # one KEK, two environments (#2338)
        assert ("demo", 90, b"U" * 8, False) in await store.kcv_versions()
    finally:
        await rel.dispose()


async def test_get_is_namespaced_by_environment(pg_dsn: str) -> None:
    """C-2.11: a read for one environment never returns another environment's row."""
    rel, store = _store(pg_dsn)
    try:
        (key_id,) = await _seed(store, _account(pg_dsn), 1)  # a demo account
        assert await store.get(key_id, "demo") is not None
        assert await store.get(key_id, "live") is None
    finally:
        await rel.dispose()


#: KV-T03 (#836): an array of pairs, which `dict()` would read as an object.
_PAIRS = [["permissions", {"ContractTrade": ["Order", "Position"]}], ["uid", "1"]]


@pytest.fixture
async def tampered(pg_dsn: str) -> AsyncIterator[tuple[SqlAlchemyCredentialStore, list[UUID]]]:
    """Three active keys at KEK version 5 (no other test's); DDL drops `ak_snapshot_shape` and sets
    the lowest id's snapshot to `_PAIRS`. The snapshot and the CHECK, as the catalog read it, come
    back afterwards."""
    plain = pg_dsn.replace("postgresql+asyncpg", "postgresql")
    rel, store = _store(pg_dsn)
    old = CredentialBroker(store, _audit, _kek(7, 5))
    ids = []
    for i in range(3):
        key = Secret(f"KEY{i:04d}TAMP")
        meta = await old.store("demo", _account(pg_dsn), f"t{i}", key, Secret("S"), _SNAP)
        ids.append(meta.key_id)
    _activate(pg_dsn, ids)
    with psycopg.connect(plain, autocommit=True) as c:
        found = c.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conname = 'ak_snapshot_shape' AND conrelid = 'api_keys'::regclass"
        ).fetchone()
        assert found is not None
        c.execute("ALTER TABLE api_keys DROP CONSTRAINT ak_snapshot_shape")
        c.execute(
            "UPDATE api_keys SET permission_snapshot = %s::jsonb WHERE id = %s",
            (json.dumps(_PAIRS), min(ids)),
        )
    try:
        yield store, ids
    finally:
        with psycopg.connect(plain, autocommit=True) as c:
            c.execute(
                "UPDATE api_keys SET permission_snapshot = %s::jsonb WHERE id = %s",
                (json.dumps(_SNAP), min(ids)),
            )
            add = sql.SQL("ALTER TABLE api_keys ADD CONSTRAINT ak_snapshot_shape {}")
            c.execute(add.format(sql.SQL(found[0])))
        await rel.dispose()


async def test_a_snapshot_edited_past_its_check_is_refused_as_snapshot_invalid(
    tampered: tuple[SqlAlchemyCredentialStore, list[UUID]],
) -> None:
    store, ids = tampered
    with pytest.raises(SnapshotInvalid):
        await _borrow(CredentialBroker(store, _audit, _kek(7, 5)), min(ids))


async def test_destroy_revokes_a_row_whose_snapshot_was_edited_past_its_check(
    tampered: tuple[SqlAlchemyCredentialStore, list[UUID]],
) -> None:
    store, ids = tampered
    await CredentialBroker(store, _audit, _kek(7, 5)).destroy(min(ids))
    rec = await store.get(min(ids), "demo")
    assert rec is not None and rec["revoked"] is True


async def test_a_kek_rewrap_moves_a_row_whose_snapshot_was_edited_and_every_other(
    tampered: tuple[SqlAlchemyCredentialStore, list[UUID]],
) -> None:
    store, ids = tampered
    rotating = CredentialBroker(store, _audit, _kek(8, 6), prev_kek=_kek(7, 5))
    assert (await rotating.rewrap_all(6)).failed == ()
    assert [(await store.get(k, "demo") or {}).get("kek_version") for k in ids] == [6, 6, 6]


async def test_rewrap_commits_the_row_and_its_audit_record_together(
    pg_dsn: str, one_key: tuple[SqlAlchemyCredentialStore, UUID]
) -> None:
    store, key_id = one_key
    assert await store.rewrap(key_id, **_move(key_id, "v1:moved", fields={"to": "2"})) is True
    assert _wrap(pg_dsn, key_id) == (2, "v1:moved")
    [(action, env, after)] = _records(pg_dsn, key_id)
    assert (action, env, after["key_id"], after["to"]) == (_REWRAPPED, "demo", str(key_id), "2")


@pytest.mark.parametrize(
    ("change", "move"),
    [
        ("UPDATE api_keys SET label = label WHERE id = %s", {"from_version": 2}),
        ("UPDATE api_keys SET revoked_at = now() WHERE id = %s", {}),
        ("UPDATE api_keys SET status = 'revoked' WHERE id = %s", {}),
        ("UPDATE api_keys SET label = label WHERE id = %s", {"env": "live"}),
    ],
    ids=["stale", "revoked_at", "status_revoked", "other_environment"],
)
async def test_a_cas_that_moves_nothing_writes_no_audit_record(
    pg_dsn: str, one_key: tuple[SqlAlchemyCredentialStore, UUID], change: str, move: dict[str, Any]
) -> None:
    """Either revocation signal fences the row, as do a stale version and another environment."""
    store, key_id = one_key
    before = _wrap(pg_dsn, key_id)
    _sql(pg_dsn, change, key_id)
    assert await store.rewrap(key_id, **_move(key_id, "v1:moved", **move)) is False
    assert _wrap(pg_dsn, key_id) == before and _records(pg_dsn, key_id) == []


@pytest.mark.parametrize(
    ("action", "fields", "error"),
    [
        ("security.not_registered", {}, UnknownAuditAction),  # the row builder refuses it
        (_REWRAPPED, {"actor_user_id": str(UUID(int=1))}, sa.exc.IntegrityError),  # no such user
    ],
    ids=["builder", "insert"],
)
async def test_a_failed_audit_record_rolls_the_cas_back(
    pg_dsn: str,
    one_key: tuple[SqlAlchemyCredentialStore, UUID],
    action: str,
    fields: dict[str, str],
    error: type[Exception],
) -> None:
    store, key_id = one_key
    before = _wrap(pg_dsn, key_id)
    with pytest.raises(error):
        await store.rewrap(key_id, **_move(key_id, "v1:moved", action, fields=fields))
    assert _wrap(pg_dsn, key_id) == before and _records(pg_dsn, key_id) == []


@pytest.mark.parametrize(
    ("abort", "error"),
    [
        (lambda dsn, pid, cas: _sql(dsn, _TERMINATE, *pid), sa.exc.DBAPIError),
        (lambda dsn, pid, cas: cas.cancel(), asyncio.CancelledError),
    ],
    ids=["killed", "cancelled"],
)
async def test_a_rewrap_aborted_while_it_waits_for_the_chain_lock_moves_nothing(
    pg_dsn: str, one_key: tuple[SqlAlchemyCredentialStore, UUID], abort: Any, error: Any
) -> None:
    """The CAS has updated its row and waits for the chain lock, which another connection holds.
    There its backend is terminated, or its task cancelled (as M2's `_io` timeout cancels it).
    Its transaction ends at once with the lock held, nothing commits, and a rerun moves the row."""
    store, key_id = one_key
    before = _wrap(pg_dsn, key_id)
    sync = pg_dsn.replace("postgresql+asyncpg", "postgresql")
    async with await psycopg.AsyncConnection.connect(sync) as holder:
        await holder.execute(_CHAIN_LOCK)
        cas = asyncio.ensure_future(store.rewrap(key_id, **_move(key_id, "v1:moved")))
        async with asyncio.timeout(30):  # fails a missed wait fast
            while not (pids := await (await holder.execute(_WAITER)).fetchall()):
                pass
        abort(pg_dsn, pids[0], cas)
        with pytest.raises(error):
            await cas
        async with asyncio.timeout(5):  # ended by the abort, not the 30 s statement_timeout
            while await (await holder.execute(_WAITER)).fetchall():
                pass
        assert _wrap(pg_dsn, key_id) == before and _records(pg_dsn, key_id) == []
    assert await store.rewrap(key_id, **_move(key_id, "v1:moved")) is True
    assert _wrap(pg_dsn, key_id) == (2, "v1:moved") and len(_records(pg_dsn, key_id)) == 1


async def _keys(b: CredentialBroker, dsn: str, n: int, tag: str, env: str = "demo") -> list[UUID]:
    """`n` keys of `env` stored by `b`, each on its own account, sorted by id."""
    out = []
    for i in range(n):
        key, acct = Secret(f"KEY{i:04d}{tag}"), _account(dsn, env)
        out.append((await b.store(env, acct, f"{tag}{i}", key, Secret("S"), _SNAP)).key_id)
    return sorted(out)


async def test_a_demo_run_moves_and_counts_only_the_demo_rows_of_a_shared_database(
    pg_dsn: str,
) -> None:
    """#2266 item 7 (C-2.11): demo and live rows at one KEK version share the database. A demo run
    lists, moves and counts demo rows only; every live row, count and record stays as it was."""
    rel, store = _store(pg_dsn)
    try:
        demo = await _keys(CredentialBroker(store, _audit, _kek(110, 8)), pg_dsn, 3, "DEMO")
        live_broker = CredentialBroker(store, _audit, _kek(140, 8, "live"), env_name="live")
        live = await _keys(live_broker, pg_dsn, 2, "LIVE", "live")
        await _enrol(store, "demo", 9, _kek(120, 9).kcv())  # the rotation boot enrols v9
        await _enrol(store, "live", 9, _kek(141, 9, "live").kcv())  # live's own lineage
        wraps = {k: _wrap(pg_dsn, k) for k in live}
        rot = CredentialBroker(store, _audit, _kek(120, 9), prev_kek=_kek(110, 8))
        rep = await rot.rewrap_all(9, batch=2)
        assert (rep.rewrapped, rep.remaining, rep.failed) == (3, 0, ())
        assert [_wrap(pg_dsn, k)[0] for k in demo] == [9, 9, 9]
        assert {k: _wrap(pg_dsn, k) for k in live} == wraps
        assert [_records(pg_dsn, k) for k in live] == [[], []]
        assert await store.ids_at_kek_version(8, 10, "live") == live
        assert await store.count_at_kek_version(8, "live") == 2
        assert await store.count_rewrapped_since_enrolment(9, "live") == 0
        assert await store.count_rewrapped_since_enrolment(9, "demo") == 3
    finally:
        await rel.dispose()


async def test_a_run_resumes_from_every_row_an_earlier_run_moved_revoked_or_not(
    pg_dsn: str,
) -> None:
    """The resume count is the rows at the new version created before it was enrolled, revoked
    or not, never a row stored under it since. A status-revoked row is neither listed nor
    counted, so the run completes with it fenced at the previous version."""
    rel, store = _store(pg_dsn)
    try:
        ids = await _keys(CredentialBroker(store, _audit, _kek(150, 12)), pg_dsn, 4, "RSME")
        await _enrol(store, "demo", 13, _kek(160, 13).kcv())
        await _keys(CredentialBroker(store, _audit, _kek(160, 13)), pg_dsn, 1, "NEWK")
        for k in ids[:2]:  # an earlier run moved two rows
            assert await store.rewrap(k, **_move(k, "v1:moved", from_version=12, kek_version=13))
        await store.mark_revoked(ids[0])
        _sql(pg_dsn, "UPDATE api_keys SET status = 'revoked' WHERE id = %s", ids[2])
        assert await store.count_rewrapped_since_enrolment(13, "demo") == 2
        assert await store.ids_at_kek_version(12, 10, "demo") == [ids[3]]
        assert await store.count_at_kek_version(12, "demo") == 1
        audit = AuditLog()
        rot = CredentialBroker(store, audit, _kek(160, 13), prev_kek=_kek(150, 12))
        rep = await rot.rewrap_all(13)
        action, fields = audit.records[0]
        assert action == "security.kek_rotation_resumed"
        assert (fields["remaining"], fields["already_rewrapped"]) == ("1", "2")
        assert (rep.resumed, rep.rewrapped, rep.remaining) == (True, 1, 0)
        assert _wrap(pg_dsn, ids[2])[0] == 12
    finally:
        await rel.dispose()


@pytest.mark.parametrize(
    ("n", "action", "fields", "error"),
    [
        (1, "security.not_registered", {}, UnknownAuditAction),  # the row builder refuses it
        (2, _ENROLLED, {"actor_user_id": str(UUID(int=1))}, sa.exc.IntegrityError),  # no such user
    ],
    ids=["builder", "insert"],
)
async def test_a_kcv_enrolment_whose_record_fails_commits_nothing(
    pg_dsn: str, n: int, action: str, fields: dict[str, str], error: type[Exception]
) -> None:
    """#2266 item 6: the `kek_versions` row and its `security.kek_enrolled` commit together or
    not at all, so no KCV is pinned without its record; a rerun enrols it with one."""
    rel, store = _store(pg_dsn)
    version, kcv = 30 + n, bytes([70 + n]) * 8
    try:
        with pytest.raises(error):
            await store.record_kcv("demo", version, kcv, audit=(action, fields))
        assert await store.kcv_for("demo", version) is None and _enrolments(pg_dsn, kcv) == []
        assert await _enrol(store, "demo", version, kcv) == (kcv, True)
        assert _enrolments(pg_dsn, kcv) == [("demo",)]
    finally:
        await rel.dispose()


async def test_a_stranded_count_is_of_unrevoked_rows_of_its_environment(pg_dsn: str) -> None:
    """#2266 item 5: the rows a boot at v21 alone cannot open, never a revoked one (either signal)
    nor another environment's (C-2.11); other tests' rows share the database, hence deltas."""
    rel, store = _store(pg_dsn)
    loads = (("demo", 21), ("demo", 20, 21), ("live", 21))
    try:
        before = [await store.count_stranded(*load) for load in loads]
        old = await _keys(CredentialBroker(store, _audit, _kek(170, 20)), pg_dsn, 4, "STRD")
        await _keys(CredentialBroker(store, _audit, _kek(172, 21)), pg_dsn, 1, "CURR")
        live_broker = CredentialBroker(store, _audit, _kek(174, 20, "live"), env_name="live")
        await _keys(live_broker, pg_dsn, 1, "LIVE", "live")
        _sql(pg_dsn, "UPDATE api_keys SET revoked_at = now() WHERE id = %s", old[0])
        _sql(pg_dsn, "UPDATE api_keys SET status = 'revoked' WHERE id = %s", old[1])
        after = [await store.count_stranded(*load) for load in loads]
        assert [a - b for a, b in zip(after, before, strict=True)] == [2, 0, 1]
    finally:
        await rel.dispose()
