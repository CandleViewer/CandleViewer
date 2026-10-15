"""Integration: `0022_replay_sessions` against real Postgres 16 (E26-T01 #624).

AC1 (round trip, no residue, catalog == 21-database-schema.md Sec.3.6.4) and AC2 (each
invalid row rejected by its NAMED constraint). Uses `testcontainers` like the other
migration suites; exercised by the integration CI job.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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
_PREV = "0021_drawings"
_T0 = datetime(2026, 9, 10, 13, 0, tzinfo=UTC)
_T1 = _T0 + timedelta(hours=2)

Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        yield dsn


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _user(c: Conn) -> str:
    uid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO users (id, email, username, password_hash) VALUES (%s, %s, %s, '$argon2id$x')",
        (uid, f"{uid[:8]}@x.io", f"u{uid[:8]}"),
    )
    return uid


def _account(c: Conn) -> str:
    aid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', 'demo', 'main', %s, %s)",
        (aid, str(uuid.uuid4().int % 10**12), f"paper-{aid[:8]}"),
    )
    return aid


def _recording_session(c: Conn) -> str:
    symbol = f"T{uuid.uuid4().hex[:8].upper()}"
    c.execute(
        "INSERT INTO instruments (symbol, base_coin, status, tick_size, qty_step, min_order_qty, "
        "max_order_qty, max_leverage, raw) VALUES (%s, 'T', 'Trading', 0.1, 0.001, 0.001, 100, "
        "100, '{}'::jsonb)",
        (symbol,),
    )
    rsid, sid = str(uuid.uuid4()), str(uuid.uuid4())
    c.execute("INSERT INTO recorded_symbols (id, symbol) VALUES (%s, %s)", (rsid, symbol))
    c.execute(
        "INSERT INTO recording_sessions (id, recorded_symbol_id, symbol, streams, "
        "orderbook_depth, ws_endpoint) VALUES (%s, %s, %s, '{trades}', 200, 'public')",
        (sid, rsid, symbol),
    )
    return sid


def _session(c: Conn, user: str, **cols: object) -> str:
    row: dict[str, object] = {
        "id": str(uuid.uuid4()),
        "user_id": user,
        "symbol": "BTCUSDT",
        "range_start": _T0,
        "range_end": _T1,
        **cols,
    }
    stmt = sql.SQL("INSERT INTO replay_sessions ({}) VALUES ({})").format(
        sql.SQL(", ").join(sql.Identifier(k) for k in row),
        sql.SQL(", ").join([sql.Placeholder()] * len(row)),
    )
    c.execute(stmt, tuple(row.values()))
    return str(row["id"])


# --- AC1: the catalog equals the plan doc, and the round trip leaves nothing behind ---------

_COLUMNS = (
    "SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, "
    "pg_get_expr(d.adbin, d.adrelid) FROM pg_attribute a LEFT JOIN pg_attrdef d "
    "ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
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
_STATES = ["created", "buffering", "playing", "paused", "finished", "error"]


def _doc_ddl() -> str:
    """The Sec.3.6.4 `CREATE TABLE` + indexes, verbatim from the plan doc."""
    text = _DOC.read_text(encoding="utf-8")
    return text.split("#### 3.6.4 `replay_sessions`", 1)[1].split("```sql", 1)[1].split("```")[0]


def _catalog(c: Conn, schema: str) -> tuple[list[Any], list[Any], list[Any]]:
    table = f"{schema}.replay_sessions"
    cols = c.execute(_COLUMNS, (table,)).fetchall()
    cons = c.execute(_CONSTRAINTS, (table,)).fetchall()
    idx = [(n, d.replace(f" ON {schema}.", " ON ")) for n, d in c.execute(_INDEXES, (table,))]
    return cols, cons, idx


def _assert_matches_plan_doc(c: Conn) -> None:
    """Build the doc's DDL in a scratch schema (rolled back) and diff the two catalogs."""
    got: tuple[list[Any], list[Any], list[Any]] | None = None
    want: tuple[list[Any], list[Any], list[Any]] | None = None
    with c.transaction():
        c.execute("CREATE SCHEMA doc_ref")
        c.execute("SET LOCAL search_path = doc_ref, public")
        c.execute(_doc_ddl().encode())
        got, want = _catalog(c, "public"), _catalog(c, "doc_ref")
        raise psycopg.Rollback
    assert got is not None and want is not None
    assert got == want
    labels = c.execute(
        "SELECT enumlabel FROM pg_enum WHERE enumtypid = 'replay_state'::regtype "
        "ORDER BY enumsortorder"
    ).fetchall()
    assert [r[0] for r in labels] == _STATES


def test_schema_matches_the_plan_doc_exactly(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _assert_matches_plan_doc(c)


def test_round_trip_leaves_no_residue_and_restores_the_exact_schema(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        c.execute("DELETE FROM replay_sessions")
        assert _alembic(pg_dsn, "downgrade", _PREV).returncode == 0
        for obj in ("replay_sessions", "ix_rps_user_time", "ix_rps_live"):
            assert c.execute("SELECT to_regclass(%s)", (obj,)).fetchone() == (None,)
        assert c.execute("SELECT to_regtype('replay_state')").fetchone() == (None,)
        assert _alembic(pg_dsn, "upgrade", "head").returncode == 0
        _assert_matches_plan_doc(c)


def test_downgrade_refuses_while_sessions_exist(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _session(c, _user(c))
        refused = _alembic(pg_dsn, "downgrade", _PREV)
        assert refused.returncode != 0
        assert "0022_replay_sessions downgrade refused" in refused.stderr
        assert c.execute("SELECT to_regclass('replay_sessions')").fetchone() == ("replay_sessions",)
        c.execute("DELETE FROM replay_sessions")


# --- AC2: every invalid row is rejected by its NAMED constraint ----------------------------

_US = timedelta(microseconds=1)


@pytest.mark.parametrize(
    ("cols", "constraint"),
    [
        pytest.param({"range_end": _T0}, "rps_range", id="end-equals-start"),
        pytest.param({"range_end": _T0 - _US}, "rps_range", id="end-before-start"),
        pytest.param({"speed": Decimal(0)}, "rps_speed", id="speed-0"),
        pytest.param({"speed": Decimal("0.09")}, "rps_speed", id="speed-below-0.1"),
        pytest.param({"speed": Decimal(101)}, "rps_speed", id="speed-101"),
        pytest.param({"source_tier": "s3"}, "rps_tier", id="tier-not-in-enum"),
        pytest.param({"cursor_ts": _T0 - _US}, "rps_cursor", id="cursor-before-range"),
        pytest.param({"cursor_ts": _T1 + _US}, "rps_cursor", id="cursor-after-range"),
        pytest.param({"paper_trading": True}, "rps_paper", id="paper-without-account"),
    ],
)
def test_invalid_session_is_rejected_by_its_named_constraint(
    pg_dsn: str, cols: dict[str, object], constraint: str
) -> None:
    with _conn(pg_dsn) as c:
        user = _user(c)
        with pytest.raises(pgerr.CheckViolation) as exc:
            _session(c, user, **cols)
        assert exc.value.diag.constraint_name == constraint


@pytest.mark.parametrize(
    "cols",
    [
        pytest.param({"speed": Decimal("0.1")}, id="speed-min"),
        pytest.param({"speed": Decimal(100)}, id="speed-max"),
        pytest.param({"cursor_ts": _T0}, id="cursor-at-start"),
        pytest.param({"cursor_ts": _T1}, id="cursor-at-end"),
        pytest.param({"source_tier": "questdb"}, id="tier-questdb"),
        pytest.param({"source_tier": "parquet"}, id="tier-parquet"),
    ],
)
def test_boundary_values_are_accepted(pg_dsn: str, cols: dict[str, object]) -> None:
    with _conn(pg_dsn) as c:
        sid = _session(c, _user(c), **cols)
        assert c.execute("SELECT 1 FROM replay_sessions WHERE id = %s", (sid,)).fetchone()


def test_paper_session_with_an_account_is_accepted(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        sid = _session(c, _user(c), paper_trading=True, paper_account_id=_account(c))
        assert c.execute("SELECT 1 FROM replay_sessions WHERE id = %s", (sid,)).fetchone()


def test_defaults_match_the_plan(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        sid = _session(c, _user(c))
        row = c.execute(
            "SELECT speed, state::text, source_tier, paper_trading, bookmarks, loop_enabled, "
            "events_emitted, gap_warnings, cursor_ts, finished_at, error_message, "
            "recording_session_id, created_at = updated_at FROM replay_sessions WHERE id = %s",
            (sid,),
        ).fetchone()
        assert row == (
            Decimal("1.00"),
            "created",
            "auto",
            False,
            [],
            False,
            0,
            0,
            None,
            None,
            None,
            None,
            True,
        )


# --- Foreign keys --------------------------------------------------------------------------


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


def test_user_delete_cascades_their_sessions(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _active_owner(c)
        user = _user(c)
        sid = _session(c, user)
        c.execute("DELETE FROM users WHERE id = %s", (user,))
        assert c.execute("SELECT 1 FROM replay_sessions WHERE id = %s", (sid,)).fetchone() is None


def test_recording_session_delete_sets_the_reference_null(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        rec = _recording_session(c)
        sid = _session(c, _user(c), recording_session_id=rec)
        c.execute("DELETE FROM recording_sessions WHERE id = %s", (rec,))
        row = c.execute(
            "SELECT recording_session_id FROM replay_sessions WHERE id = %s", (sid,)
        ).fetchone()
        assert row == (None,)


def test_account_delete_detaches_a_non_paper_session(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        acct = _account(c)
        sid = _session(c, _user(c), paper_account_id=acct)
        c.execute("DELETE FROM exchange_accounts WHERE id = %s", (acct,))
        row = c.execute(
            "SELECT paper_account_id FROM replay_sessions WHERE id = %s", (sid,)
        ).fetchone()
        assert row == (None,)


def test_account_delete_is_refused_while_a_paper_session_uses_it(pg_dsn: str) -> None:
    """`ON DELETE SET NULL` would orphan a paper session, so `rps_paper` refuses the delete."""
    with _conn(pg_dsn) as c:
        acct = _account(c)
        _session(c, _user(c), paper_trading=True, paper_account_id=acct)
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute("DELETE FROM exchange_accounts WHERE id = %s", (acct,))
        assert exc.value.diag.constraint_name == "rps_paper"
