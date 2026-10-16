"""Integration: `SqlAlchemyCredentialStore` + `CredentialBroker` on real Postgres 16 (#835).

Exercises the real SQL the unit fakes stand in for: insert/get/borrow, revoke, keyset paging,
the rewrap compare-and-set (incl. a concurrent writer), kill-and-resume over 50 rows,
`kek_versions` record/re-read and `last_used_at` touch. Fixed test vectors only; no network
beyond the local testcontainer. Not run locally (no docker); CI integration lane.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.secrets import KEY_ID_SLOT
from candleviewer.secrets._kek import LoadedKek
from candleviewer.secrets._rotation import RotatingBroker as CredentialBroker
from candleviewer.secrets.errors import CredentialUnavailable
from candleviewer.secrets.secret import Secret
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_SNAP: dict[str, Any] = {"uid": "1", "permissions": {"ContractTrade": ["Order"], "Wallet": []}}


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


def _account(dsn: str) -> UUID:
    acct = uuid4()
    uid = str(abs(hash(acct)) % 10**12)
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        c.execute(
            "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
            "VALUES (%s, 'bybit', 'demo', 'main', %s, %s)",
            (acct, uid, f"acct-{acct}"),
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
    store = SqlAlchemyCredentialStore(rel)
    _DSNS[id(store)] = dsn
    return rel, store


def _activate(dsn: str, ids: list[UUID], status: str = "active") -> None:
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        for k in ids:
            c.execute("UPDATE api_keys SET status = %s::key_status WHERE id = %s", (status, k))


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
            store.rewrap(key_id, from_version=1, dek_ref=rec["dek_ref"], kek_version=2),
            store.rewrap(key_id, from_version=1, dek_ref=rec["dek_ref"], kek_version=2),
        )
        assert sorted(results) == [False, True]
        await store.mark_revoked(key_id)
        assert not await store.rewrap(key_id, from_version=2, dek_ref="x", kek_version=3)
    finally:
        await rel.dispose()


async def test_kcv_record_and_reread(pg_dsn: str) -> None:
    rel, store = _store(pg_dsn)
    try:
        assert await store.kcv_for("demo", 77) is None
        first, second = await asyncio.gather(
            store.record_kcv("demo", 77, b"A" * 8), store.record_kcv("demo", 77, b"B" * 8)
        )
        assert first == second and await store.kcv_for("demo", 77) == first
        # #2338: (live, 77) is another lineage's key; it neither conflicts nor shadows demo's
        assert await store.record_kcv("live", 77, b"C" * 8) == b"C" * 8
        assert await store.kcv_for("demo", 77) == first
    finally:
        await rel.dispose()


async def test_status_env_and_flags_from_real_rows(pg_dsn: str) -> None:
    rel, store = _store(pg_dsn)
    try:
        acct = _account(pg_dsn)
        (key_id,) = await _seed(store, acct, 1)
        rec = await store.get(key_id, "demo")
        assert rec is not None and rec["env"] == "demo" and rec["status"] == "active"
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
        await store.record_kcv("demo", 90, b"U" * 8)
        with pytest.raises(Exception):  # noqa: B017 -- kv_kcv_unique IntegrityError
            await store.record_kcv("live", 91, b"U" * 8)  # one KEK, two environments (#2338)
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
