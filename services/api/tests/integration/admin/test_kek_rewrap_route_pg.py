"""Integration (#2266 PR D2): a KEK rotation end to end on a real Postgres 16, through the app.

Demo and live keys share the database, each environment on its own KEK lineage (#2338). The demo
process stages v1 to v2 and the Owner's `POST /admin/keys/kek-rewrap` goes through the real CSRF,
step-up and RBAC middleware (`tests/unit/api/test_admin_kek.py`'s world) to M2 on
`SqlAlchemyCredentialStore`; M2's write-ahead records go through a real `AuditWriter`. Every
Postgres call runs on the app's loop (`portal.call`). Needs Docker (testcontainers); CI
`integration` runs it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer

from candleviewer.admin.wiring import secrets_audit_sink
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import AuditWriter
from candleviewer.observability.health import HealthStatus
from candleviewer.secrets.service import SecretsService
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.auth_keys_sqlalchemy import SqlAlchemyAuthKeyStore
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.integration.storage.test_credentials_store_pg import _keys, _sql
from tests.integration.storage.test_kek_lineage_shared_db import _audit_row
from tests.unit.api.test_admin_kek import OWNER, PATH, deploy, elevated
from tests.unit.api.test_invites_create_app_e2e import _h
from tests.unit.credentials_m2._service_fakes import _bound_sources, _ctx, _Src, _svc
from tests.unit.credentials_m2._vectors import KEK_LIVE, KEK_V1, KEK_V2

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_USER = (
    "INSERT INTO users (id, email, username, password_hash, status) "
    "VALUES (%s, %s, %s, '$argon2id$fixture', 'active')"
)
_RUN = "SELECT action, object_id FROM audit_log WHERE after_state->>'run_id' = %s"
_STARTED, _ROTATED = "security.kek_rotation_started", "security.kek_rotated"
_MOVED = "security.credential_rewrapped"
_LINEAGES = [("demo", 1), ("demo", 2), ("live", 1)]


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


async def _boot(store: SqlAlchemyCredentialStore, env: str, *srcs: _Src) -> Any:
    """One process's boot in `env` (its own gate), as a restart of it would be."""
    svc = _svc(*srcs, store=store)
    await svc.start(_ctx(environment=env))
    return svc


async def _stored(store: SqlAlchemyCredentialStore, dsn: str, env: str, src: _Src, n: int) -> Any:
    return await _keys((await _boot(store, env, src))._require(), dsn, n, env.upper(), env)


async def test_a_staged_rotation_runs_end_to_end_through_the_route(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rel = SqlAlchemyRelationalRepository(pg_dsn, "it-kek")
    store = SqlAlchemyCredentialStore(rel, audit_row=_audit_row)
    writer = AuditWriter(SqlAlchemyAuditRepository(rel), str(tmp_path / "audit.wal"))
    staged = SecretsService(  # the rotation boot, its own records through the real writer
        store=store,
        kcv_store=store,
        audit=secrets_audit_sink(cast(Any, SimpleNamespace(writer=writer))),
        sources=_bound_sources(_Src(KEK_V2, 2), _Src(KEK_V1, 1)),
        harden=lambda: True,
        auth_keys=SqlAlchemyAuthKeyStore(rel, env="demo"),
    )
    w, ctx = deploy(monkeypatch, staged)
    await w.auth.start(ctx)
    with TestClient(w.client.app, client=("127.0.0.1", 50000)) as client:
        assert client.portal is not None
        w.client, run = client, client.portal.call  # one loop for every Postgres call
        run(writer.start)
        live = run(_stored, store, pg_dsn, "live", _Src(KEK_LIVE, 1), 1)
        demo = run(_stored, store, pg_dsn, "demo", _Src(KEK_V1, 1), 2)
        run(staged.start, ctx)  # the staged boot enrols demo v2
        early = run(_boot, store, "demo", _Src(KEK_V2, 2))  # a restart that skips the re-wrap
        assert early.health().detail == "kek_rows_stranded"
        owner = await elevated(w, "owner", OWNER)
        uid = w.resolver.by_token[owner].user_id  # rotation records name the Owner (FK users)
        _sql(pg_dsn, _USER, uid, f"{uid.hex}@x.invalid", uid.hex[:16])
        r = client.post(PATH, headers=_h(owner), json={"environment": "demo", "to_version": 2})
        assert (r.status_code, r.json()["rewrapped"], r.json()["complete"]) == (200, 2, True)
        run(writer.flush, 60)
        verified = run(AuditQueryService(SqlAlchemyAuditRepository(rel)).verify)
        after = run(_boot, store, "demo", _Src(KEK_V2, 2))  # the restart without the previous KEK
        lineages = sorted((e, v) for e, v, _, _ in run(store.kcv_versions))
        run(writer.stop, 5)
        run(rel.dispose)
    assert verified.verified and ctx.oms_read_only_gate.reason_code == "secrets.kek_rotation"
    assert _versions(pg_dsn, demo) == [2, 2] and _versions(pg_dsn, live) == [1]
    records = _sql(pg_dsn, _RUN, r.json()["run_id"])  # WAL and in-transaction rows interleave
    run_records = [(_STARTED, None), (_ROTATED, None)] + [(_MOVED, str(k)) for k in demo]
    assert sorted(records) == sorted(run_records)  # one per moved row, none about a live key
    assert (after.health().status, lineages) == (HealthStatus.OK, _LINEAGES)


def _versions(dsn: str, ids: list[UUID]) -> list[int]:
    rows = _sql(dsn, "SELECT id, kek_version FROM api_keys WHERE id = ANY(%s)", ids)
    return [version for _, version in sorted(rows)]
