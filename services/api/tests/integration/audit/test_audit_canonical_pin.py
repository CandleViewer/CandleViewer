"""Integration: the canonical form `verify` hashes, pinned byte for byte against the real
`audit_chain()` trigger on Postgres 16 (ticket "Technical notes"; design §5).

One entry has every nullable hashed column NULL and goes in through the repository's own
`insert` (the single writer path). The other has every column set, with nested and
non-ASCII jsonb, and goes in under a session TimeZone and DateStyle unlike the reader's, so
the pin also shows that no rendering depends on session settings.

Not run locally (no docker); exercised by the CI integration job (testcontainers).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from candleviewer.audit.query import (
    HASHED_FIELDS,
    AuditQueryService,
    _canonical_field,
    _canonical_hash,
)
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_ACTOR = uuid.UUID(int=0xC3)
_GENESIS = "0" * 64
_NULLABLE = {
    "actor_user_id",
    "actor_ip",
    "session_id",
    "object_kind",
    "object_id",
    "reason",
    "before_state",
    "after_state",
    "request_id",
    "env",
}
_FRAMING = [None, "", "é", "e\u0301", "日本", "\U0001f600", "1:-"]


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        migrate_dsn = url.replace("postgresql+psycopg2", "postgresql+psycopg")
        subprocess.run(  # fixed argv, literal alembic subcommand, no shell
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={**os.environ, "CV_PG_DSN": migrate_dsn},
            check=True,
        )
        with psycopg.connect(url.replace("postgresql+psycopg2", "postgresql")) as conn:
            conn.execute(
                "INSERT INTO users (id, email, username, password_hash, status) "
                "VALUES (%s, 'it_pin@example.invalid', 'it_pin', '$argon2id$synthetic', 'active')",
                (_ACTOR,),
            )
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture
async def repo(pg_dsn: str) -> AsyncIterator[SqlAlchemyAuditRepository]:
    """Built inside the test's own loop and disposed before it closes."""
    relational = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield SqlAlchemyAuditRepository(relational)
    finally:
        await relational.dispose()


def _sync(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg", "postgresql")


def _insert_all_set(dsn: str) -> None:
    """Every column set, through the trigger, in a session unlike the reader's."""
    state = {"注文": {"qty": "0.01", "tags": ["é", "\U0001f600"]}, "e\u0301": None, "n": [1, {}]}
    state["esc"] = 'quote" back\\ newline\n tab\t ctl\u0001'  # escaped on jsonb output
    ids = (uuid.uuid4(), _ACTOR, uuid.uuid4())
    with psycopg.connect(_sync(dsn)) as conn:
        conn.execute("SET TIME ZONE 'Pacific/Chatham'")
        conn.execute("SET DateStyle = 'SQL, DMY'")
        conn.execute(
            "INSERT INTO audit_log (record_id, actor_user_id, actor_label, actor_ip, session_id, "
            "action, object_kind, object_id, object_label, outcome, severity, reason, "
            "before_state, after_state, request_id, env, event_ts) VALUES (%s, %s, 'Zoë 日本', "
            "'2001:db8::7', %s, 'orders.submit', 'order', 'ord-1:-', 'BTC 注文', 'denied', "
            "'critical', 'reason: 1:- \U0001f600', %s::jsonb, %s::jsonb, %s, 'demo', "
            "'2026-10-14 23:59:59.123456+05:30')",
            (*ids, json.dumps(state), json.dumps([state]), uuid.uuid4()),
        )


def test_python_framing_equals_the_sql_audit_field(pg_dsn: str) -> None:
    with psycopg.connect(_sync(pg_dsn)) as conn:
        # `length()` counts characters as `len()` does only in a UTF8 database.
        assert conn.execute("SHOW server_encoding").fetchone() == ("UTF8",)
        for value in _FRAMING:
            row = conn.execute("SELECT audit_field(%s::text)", (value,)).fetchone()
            assert row is not None and row[0] == _canonical_field(value), value


async def test_python_canonical_hash_equals_the_trigger_entry_hash(
    repo: SqlAlchemyAuditRepository, pg_dsn: str
) -> None:
    await repo.insert(
        {
            "record_id": uuid.uuid4(),
            "actor_label": "pin",
            "action": "auth.login",
            "outcome": "success",
            "severity": "info",
            "event_ts": datetime(2026, 10, 14, 12, 0, 0, 1, tzinfo=UTC).isoformat(),
        }
    )
    _insert_all_set(pg_dsn)
    head = await repo.read_head()
    assert head is not None
    rows = await repo.fetch_verify_batch(after_id=0, to_id=head[0], limit=10)
    assert len(rows) == 2 and rows[0][1] == _GENESIS and rows[1][1] == rows[0][2]
    rendered: list[dict[str, Any]] = [dict(zip(HASHED_FIELDS, r[3:], strict=True)) for r in rows]
    assert {k for k, v in rendered[0].items() if v is None} == _NULLABLE
    assert None not in rendered[1].values()
    assert "日本" in rendered[1]["actor_label"] and "注文" in rendered[1]["after_state"]
    assert "\\u0001" in rendered[1]["after_state"]  # jsonb rendered it escaped
    assert rendered[1]["event_ts"] == "2026-10-14T18:29:59.123456+00"
    for row, fields in zip(rows, rendered, strict=True):
        assert _canonical_hash(row[1], fields) == row[2]  # byte for byte, as hex
    result = await AuditQueryService(repo).verify()
    assert (result.verified, result.entries_checked, result.first_bad_id) == (True, 2, None)
