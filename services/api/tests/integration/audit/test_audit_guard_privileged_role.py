"""Integration (E42-X03, #1026): the append-only triggers refuse a privileged role that is not
the owner, on real Postgres 16.

Owed to E42-X03 by `docs/security/threat-models/e42-admin.md` §12.1 (row "Append-only audit:
triggers", AC-ADM-15). The grant layer is proven alone by `test_audit_guard_cv_app.py` (`cv_app`
holds no UPDATE, DELETE or TRUNCATE), and the owner and superuser cases by `_assert_guard_enforces`
and `test_audit_repository.py::test_truncate_refused_even_for_owner`. This case grants a role every
mutating privilege on `audit_log` and `audit_checkpoints` without making it their owner: only the
triggers stand between it and the history. The role and its password are made up at run time.
Needs Docker (testcontainers); CI `integration` runs it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.rows import TupleRow
from sqlalchemy.engine import make_url
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_TABLES = ("audit_log", "audit_checkpoints")
#: One row in each table, written as the superuser through the chain trigger (as
#: `scripts/seed_fixture_user.py` writes its audit rows).
_SEED = (
    "SELECT pg_advisory_xact_lock(hashtext('audit_log'))",
    "INSERT INTO audit_log (record_id, actor_label, action, object_kind, object_id, outcome, "
    "severity, reason, after_state, event_ts) VALUES (gen_random_uuid(), 'x03', 'users.create', "
    "'user', 'x03', 'success', 'info', 'seed', '{}'::jsonb, now())",
    "INSERT INTO audit_checkpoints (id, head_id, head_hash, row_count) "
    "SELECT gen_random_uuid(), max(id), repeat('0', 64), count(*) FROM audit_log",
)
#: As `test_audit_guard_cv_app.py`'s `_HISTORY_ATTACKS`, which the owner and `cv_app` meet.
_ATTACKS = {
    "audit_log": (
        "UPDATE audit_log SET reason = 'forged'",
        "DELETE FROM audit_log",
        "TRUNCATE audit_log",
    ),
    "audit_checkpoints": (
        "UPDATE audit_checkpoints SET head_hash = repeat('f', 64)",
        "DELETE FROM audit_checkpoints",
        "TRUNCATE audit_checkpoints",
    ),
}


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={**os.environ, "CV_PG_DSN": dsn},
            check=True,
        )
        yield dsn


def _connect(
    dsn: str, user: str | None = None, password: str | None = None
) -> psycopg.Connection[TupleRow]:
    url = make_url(dsn)
    return psycopg.connect(
        host=url.host,
        port=url.port,
        dbname=url.database,
        user=user or url.username,
        password=password or url.password,
        autocommit=True,
    )


def _counts(dsn: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    with _connect(dsn) as conn:
        for table in _TABLES:
            row = conn.execute(
                sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
            ).fetchone()
            assert row is not None
            counts[table] = int(row[0])
    return counts


def test_a_privileged_role_that_is_not_the_owner_is_refused_by_the_triggers(pg_dsn: str) -> None:
    role, secret = f"x03_priv_{uuid.uuid4().hex[:12]}", uuid.uuid4().hex
    with _connect(pg_dsn) as admin:
        with admin.transaction():
            for statement in _SEED:
                admin.execute(statement)
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(secret)
            )
        )
        admin.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(role)))
        for table in _TABLES:
            admin.execute(
                sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON {} TO {}").format(
                    sql.Identifier(table), sql.Identifier(role)
                )
            )
        owner = admin.execute(
            "SELECT tableowner FROM pg_tables WHERE tablename = ANY(%s)", (list(_TABLES),)
        ).fetchall()
    assert role not in {row[0] for row in owner}  # privileged, not the owner
    before = _counts(pg_dsn)
    try:
        with _connect(pg_dsn, role, secret) as attacker:
            for attacks in _ATTACKS.values():
                for attack in attacks:
                    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
                        attacker.execute(attack)
        assert _counts(pg_dsn) == before  # nothing changed, nothing removed
    finally:
        with _connect(pg_dsn) as admin:
            for table in _TABLES:
                admin.execute(
                    sql.SQL("REVOKE ALL ON {} FROM {}").format(
                        sql.Identifier(table), sql.Identifier(role)
                    )
                )
            admin.execute(
                sql.SQL("REVOKE USAGE ON SCHEMA public FROM {}").format(sql.Identifier(role))
            )
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))
