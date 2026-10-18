"""Integration (#2338): live and non-live `SecretsService`s on one real Postgres 16.

AC-02, AC-31 and the failed cross-environment open, through `SqlAlchemyCredentialStore` and the
real `kek_versions` key `(env, version)`. Fake KEK sources, synthetic KEKs; CI integration lane.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from cryptography.exceptions import InvalidTag
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.wiring import secrets_audit_row
from candleviewer.observability.health import HealthStatus
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.service import SecretsService
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _svc, _zeroed
from tests.unit.credentials_m2._vectors import KEK_LIVE, KEK_V1, KEK_V2, AuditLog, kek

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_SNAP: dict[str, Any] = {"uid": "1", "permissions": {"ContractTrade": ["Order"], "Wallet": []}}


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        dsn = url.replace("postgresql+psycopg2", "postgresql+psycopg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT, env={**os.environ, "CV_PG_DSN": dsn}, check=True,
        )  # fmt: skip
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


def _sql(dsn: str, query: str, params: tuple[object, ...] = ()) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        cur = c.execute(query, params)
        return cur.fetchall() if cur.description else []


def _audit_row(action: str, fields: dict[str, str]) -> dict[str, Any]:
    """The production row builder, bound per record to the environment of the boot that writes
    it: one store here stands in for each environment's process (#2266: `kek_enrolled`)."""
    return secrets_audit_row(fields["env"])(action, fields)


@pytest.fixture
async def store(pg_dsn: str) -> AsyncIterator[SqlAlchemyCredentialStore]:
    """No lineage and no key at the start of every test."""
    _sql(pg_dsn, "DELETE FROM api_keys")
    _sql(pg_dsn, "DELETE FROM kek_versions")
    rel = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield SqlAlchemyCredentialStore(rel, audit_row=_audit_row)
    finally:
        await rel.dispose()


async def _boot(
    store: SqlAlchemyCredentialStore,
    env_name: str,
    *srcs: _Src,
    audit: AuditLog | None = None,
    **settings: Any,
) -> tuple[SecretsService, Any]:
    svc = _svc(*srcs, store=store, audit=audit)
    ctx = _ctx(environment=env_name, **settings)
    await svc.start(ctx)
    return svc, ctx


async def _lineages(store: SqlAlchemyCredentialStore) -> list[tuple[str, int]]:
    return sorted((e, v) for e, v, _, _ in await store.kcv_versions())


@pytest.mark.parametrize("env_name", ["demo", "testnet"])
async def test_live_kek_refused_outside_live(
    store: SqlAlchemyCredentialStore, env_name: str
) -> None:
    """AC-02 on the shared database: refused before any insert, so no `kv_kcv_unique` race."""
    await _boot(store, "live", _Src(KEK_LIVE, 1))
    src, audit = _Src(KEK_LIVE, 1), AuditLog()
    svc, ctx = await _boot(store, env_name, src, audit=audit, kek_source="file")
    assert svc.health().detail == "kek_reused" and ctx.oms_read_only_gate.is_read_only
    assert _zeroed(src) and audit.records[-1][1]["env"] == env_name
    assert await _lineages(store) == [("live", 1)]


async def test_other_environment_versions_do_not_affect_a_live_boot(
    store: SqlAlchemyCredentialStore, pg_dsn: str
) -> None:
    """AC-31 on the shared database, with (demo, 1) retired by hand as the runbook does."""
    await _boot(store, "live", _Src(KEK_LIVE, 1))
    await _boot(store, "demo", _Src(KEK_V1, 1))
    await _boot(store, "demo", _Src(KEK_V2, 2), _Src(KEK_V1, 1))
    _sql(pg_dsn, "UPDATE kek_versions SET retired_at = now() WHERE env = 'demo' AND version = 1")
    svc, _ = await _boot(store, "live", _Src(KEK_LIVE, 1))
    assert svc.health().status is HealthStatus.OK, svc.health().detail
    assert await _lineages(store) == [("demo", 1), ("demo", 2), ("live", 1)]


async def test_demo_kek_cannot_open_a_live_row(
    store: SqlAlchemyCredentialStore, pg_dsn: str
) -> None:
    acct = uuid4()
    _sql(
        pg_dsn,
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', 'live', 'main', %s, %s)",
        (acct, str(acct.int % 10**12), f"live-{acct}"),
    )
    live, _ = await _boot(store, "live", _Src(KEK_LIVE, 1))
    key = await live._require().store("live", acct, "k", Secret("KEY0ABCD"), Secret("S"), _SNAP)
    demo, _ = await _boot(store, "demo", _Src(KEK_V1, 1), kek_source="file")
    assert demo.health().status is HealthStatus.OK
    (ref,) = _sql(pg_dsn, "SELECT dek_ref FROM api_keys WHERE id = %s", (key.key_id,))[0]
    for env_name in ("live", "demo"):
        with pytest.raises(InvalidTag):
            kek(KEK_V1, 1, env_name).unwrap_dek(ref, credential_id=key.key_id)
    assert await store.get(key.key_id, "demo") is None
