"""Integration: `0028_incidents_backups` against real Postgres 16 (E42-T05 #966).

The catalog equals 21-database-schema.md Sec.3.10.2a and Sec.3.10.3; every invalid row is rejected
by its NAMED constraint; the grouping key, the user FKs, the SECRET comment, the downgrade guard
and the 5 s `lock_timeout` brackets are exercised on the real engine. `testcontainers`, CI-only
(no docker socket in WSL); every statement was run on a scratch Postgres 16.4 first.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors as pgerr
from psycopg import sql
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0028_incidents_backups", "0027_feature_flags"
_TABLES = ("incidents", "backups")
_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)

Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Bounded, so a lost `lock_timeout` fails the test instead of hanging it."""
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        yield dsn


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _heal(dsn: str) -> None:
    """Back to head whatever a test did, so one failure cannot cascade into the others."""
    done = _alembic(dsn, "upgrade", "head")
    assert done.returncode == 0, done.stderr


def _insert(c: Conn, table: str, row: dict[str, object]) -> str:
    stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(k) for k in row),
        sql.SQL(", ").join([sql.Placeholder()] * len(row)),
    )
    c.execute(stmt, tuple(row.values()))
    return str(row["id"])


def _incident(c: Conn, **cols: object) -> str:
    """A valid open incident under a never-reused signature (`ux_incidents_group`)."""
    row: dict[str, object] = {"id": str(uuid.uuid4()), "signature": uuid.uuid4().hex[:16]}
    row |= {"component": "ws", "severity": "error", "title": "WS disconnect <n>"}
    return _insert(c, "incidents", row | {"first_seen_at": _NOW, "last_seen_at": _NOW} | cols)


def _backup(c: Conn, **cols: object) -> str:
    row = {"id": str(uuid.uuid4()), "kind": "pg_dump", "target_path": "/backups/x.dump"}
    return _insert(c, "backups", row | cols)


def _user(c: Conn) -> str:
    uid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO users (id, email, username, password_hash) VALUES (%s, %s, %s, '$argon2id$x')",
        (uid, f"{uid[:8]}@x.io", f"u{uid[:8]}"),
    )
    return uid


def _active_owner(c: Conn) -> None:
    """Keep one active owner so `trg_owner_floor_fn` allows deleting other users."""
    uid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO users (id, email, username, display_name, password_hash, status) "
        "VALUES (%s, %s, %s, 'o', '$argon2id$x', 'active')",
        (uid, f"{uid}@example.test", f"o{uid[:12]}"),
    )
    c.execute(
        "INSERT INTO user_roles (user_id, role_id) SELECT %s, id FROM roles WHERE name = 'owner'",
        (uid,),
    )


# --- The catalog equals the plan doc, and the round trip leaves nothing behind ----------------

_COLUMNS = (
    "SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, "
    "pg_get_expr(d.adbin, d.adrelid), col_description(a.attrelid, a.attnum) IS NOT NULL "
    "FROM pg_attribute a LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
    "WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum"
)
_CONSTRAINTS = (
    "SELECT conname, contype, pg_get_constraintdef(oid) FROM pg_constraint "
    "WHERE conrelid = %s::regclass ORDER BY conname"
)
_INDEXES = (
    "SELECT i.relname, pg_get_indexdef(i.oid) FROM pg_index x "
    "JOIN pg_class i ON i.oid = x.indexrelid WHERE x.indrelid = %s::regclass ORDER BY i.relname"
)


def _doc_ddl() -> str:
    """Sec.3.10.2a's and Sec.3.10.3's ```sql blocks, each to its fence."""
    text = _DOC.read_text(encoding="utf-8")
    return "\n".join(
        text.split(heading, 1)[1].split("```sql", 1)[1].split("```", 1)[0]
        for heading in ("#### 3.10.2a `incidents`", "#### 3.10.3 `backups`")
    )


def _catalog(c: Conn, schema: str) -> list[Any]:
    """Columns, constraints and indexes of both tables, schema qualifiers stripped."""
    unqualify = re.compile(r"\b(?:public|doc_ref)\.")
    out: list[Any] = []
    for table in _TABLES:
        for query in (_COLUMNS, _CONSTRAINTS, _INDEXES):
            rows = c.execute(query, (f"{schema}.{table}",)).fetchall()
            out.append([tuple(unqualify.sub("", str(v)) for v in row) for row in rows])
    return out


def _without_comment_flag(catalog: list[Any]) -> list[Any]:
    return [[row[:4] for row in rows] if i % 3 == 0 else rows for i, rows in enumerate(catalog)]


def _assert_matches_plan_doc(c: Conn) -> None:
    """Build the doc's DDL in a scratch schema (rolled back) and diff the two catalogs. The doc
    holds no COMMENT, so the comment flag is checked on its own: only `encryption_ref` has one."""
    got: list[Any] = []
    want: list[Any] = []
    with c.transaction():
        c.execute("CREATE SCHEMA doc_ref")
        c.execute("SET LOCAL search_path = doc_ref, public")
        c.execute(_doc_ddl().encode())
        got, want = _catalog(c, "public"), _catalog(c, "doc_ref")
        raise psycopg.Rollback
    assert _without_comment_flag(got) == _without_comment_flag(want) and got
    assert [row[0] for rows in got[0::3] for row in rows if row[4] == "True"] == ["encryption_ref"]


def test_schema_matches_the_plan_doc_exactly(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _assert_matches_plan_doc(c)
        comment = c.execute(
            "SELECT col_description(attrelid, attnum) FROM pg_attribute "
            "WHERE attrelid = 'backups'::regclass AND attname = 'encryption_ref'"
        ).fetchone()
        assert comment is not None and str(comment[0]).startswith("SECRET:")


def test_round_trip_leaves_no_residue_and_restores_the_exact_schema(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM incidents")
        c.execute("DELETE FROM backups")
        try:
            assert _alembic(pg_dsn, "downgrade", _PREV).returncode == 0
            for obj in (*_TABLES, "ux_incidents_group", "ix_backups_failed"):
                assert c.execute("SELECT to_regclass(%s)", (obj,)).fetchone() == (None,)
            for kind in ("backup_kind", "backup_status"):
                assert c.execute("SELECT to_regtype(%s)", (kind,)).fetchone() == (None,)
        finally:
            _heal(pg_dsn)  # the upgrade half of the round trip, even when a check above failed
        _assert_matches_plan_doc(c)


@pytest.mark.parametrize("table", _TABLES)
def test_downgrade_refuses_while_either_table_holds_rows(pg_dsn: str, table: str) -> None:
    with _conn(pg_dsn) as c:
        rid = _incident(c) if table == "incidents" else _backup(c)
        try:
            refused = _alembic(pg_dsn, "downgrade", _PREV)
            assert refused.returncode != 0
            assert "0028_incidents_backups downgrade refused" in refused.stderr
            assert c.execute("SELECT to_regclass(%s)", (table,)).fetchone() == (table,)
        finally:
            _heal(pg_dsn)  # a regressed guard would have dropped the tables; keep that local
            c.execute(sql.SQL("DELETE FROM {} WHERE id = %s").format(sql.Identifier(table)), (rid,))


@pytest.mark.parametrize(
    ("direction", "target", "lock"),
    [
        pytest.param("upgrade", _REV, "LOCK TABLE users IN ROW EXCLUSIVE MODE", id="upgrade"),
        pytest.param("downgrade", _PREV, "LOCK TABLE users IN ACCESS SHARE MODE", id="downgrade"),
    ],
)
def test_a_held_users_lock_makes_either_direction_give_up(
    pg_dsn: str, direction: str, target: str, lock: str
) -> None:
    """The FKs need SHARE ROW EXCLUSIVE on `users` on the way in (an open writer blocks it) and
    the drops a lock an open reader blocks on the way out; the 5 s `lock_timeout` bounds both
    waits and the failed step changes nothing."""
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM incidents")
        c.execute("DELETE FROM backups")
        try:
            # Start at the revision before the step under test, whatever the head is.
            start = _PREV if direction == "upgrade" else _REV
            assert _alembic(pg_dsn, "downgrade", start).returncode == 0
            before = c.execute("SELECT version_num FROM alembic_version").fetchone()
            assert before == (start,)
            with _conn(pg_dsn) as holder, holder.transaction():
                holder.execute(lock)
                refused = _alembic(pg_dsn, direction, target)
            assert refused.returncode != 0 and "lock timeout" in refused.stderr
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == before
        finally:
            _heal(pg_dsn)


# --- Every invalid row is rejected by its NAMED constraint -------------------------------------


@pytest.mark.parametrize(
    ("cols", "constraint"),
    [
        pytest.param({"signature": "ABCDEF0123456789"}, "inc_signature", id="signature-upper"),
        pytest.param({"signature": "0123456789abcde"}, "inc_signature", id="signature-15"),
        pytest.param({"signature": "0123456789abcdef0"}, "inc_signature", id="signature-17"),
        pytest.param({"severity": "warning"}, "inc_severity", id="severity-below-error"),
        pytest.param({"status": "closed"}, "inc_status", id="status-unknown"),
        pytest.param({"occurrences": 0}, "inc_count", id="no-occurrence"),
        pytest.param({"last_seen_at": _NOW - timedelta(seconds=1)}, "inc_seen", id="seen-order"),
        pytest.param({"status": "acknowledged"}, "inc_ack", id="ack-without-time"),
        pytest.param({"status": "resolved"}, "inc_resolved", id="resolved-without-time"),
    ],
)
def test_invalid_incident_is_rejected_by_its_named_constraint(
    pg_dsn: str, cols: dict[str, object], constraint: str
) -> None:
    with _conn(pg_dsn) as c, pytest.raises(pgerr.CheckViolation) as exc:
        _incident(c, **cols)
    assert exc.value.diag.constraint_name == constraint


@pytest.mark.parametrize(
    ("cols", "constraint"),
    [
        pytest.param({"triggered_by": "cron"}, "bk_trigger", id="trigger-unknown"),
        pytest.param({"verify_method": "eyeball"}, "bk_verify", id="verify-unknown"),
    ],
)
def test_invalid_backup_is_rejected_by_its_named_constraint(
    pg_dsn: str, cols: dict[str, object], constraint: str
) -> None:
    with _conn(pg_dsn) as c, pytest.raises(pgerr.CheckViolation) as exc:
        _backup(c, **cols)
    assert exc.value.diag.constraint_name == constraint


def test_the_plan_defaults_apply(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        iid, bid = _incident(c), _backup(c)
        incident = c.execute(
            "SELECT status, occurrences, detail, acknowledged_by FROM incidents WHERE id = %s",
            (iid,),
        ).fetchone()
        assert incident == ("open", 1, None, None)
        backup = c.execute(
            "SELECT status, encrypted, triggered_by, started_at <= now() FROM backups "
            "WHERE id = %s",
            (bid,),
        ).fetchone()
        assert backup == ("running", True, "schedule", True)
        assert _incident(c, status="acknowledged", acknowledged_at=_NOW, severity="critical")
        assert _incident(c, status="resolved", resolved_at=_NOW)


def test_one_incident_per_component_and_signature(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        signature = uuid.uuid4().hex[:16]
        _incident(c, signature=signature)
        assert _incident(c, signature=signature, component="oms")  # another component: allowed
        with pytest.raises(pgerr.UniqueViolation) as exc:
            _incident(c, signature=signature)
        assert exc.value.diag.constraint_name == "ux_incidents_group"


def test_user_references_must_exist_and_detach_on_delete(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        for insert, column, fk in (
            (_incident, "acknowledged_by", "incidents_acknowledged_by_fkey"),
            (_backup, "triggered_by_user", "backups_triggered_by_user_fkey"),
        ):
            with pytest.raises(pgerr.ForeignKeyViolation) as exc:
                insert(c, **{column: str(uuid.uuid4())})
            assert exc.value.diag.constraint_name == fk
        _active_owner(c)
        user = _user(c)
        iid = _incident(c, status="acknowledged", acknowledged_at=_NOW, acknowledged_by=user)
        bid = _backup(c, triggered_by="manual", triggered_by_user=user)
        c.execute("DELETE FROM users WHERE id = %s", (user,))
        ack = c.execute("SELECT acknowledged_by FROM incidents WHERE id = %s", (iid,)).fetchone()
        by = c.execute("SELECT triggered_by_user FROM backups WHERE id = %s", (bid,)).fetchone()
        assert (ack, by) == ((None,), (None,))
