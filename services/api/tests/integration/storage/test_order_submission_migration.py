"""Integration: `0043_order_submission` on real Postgres 16 (E29-T04 #913): the catalogue against
the plan doc, the round trip on an empty and a seeded database, the refused downgrades, each CHECK
by name, the guards under the replica role, the TRUNCATE triggers, the foreign keys and the two
unique indexes. Grants: test_cv_app_role_privileges.py. `testcontainers` in CI."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0043_order_submission", "0046_audit_signing_keys"
_TEMPLATE = "order_submission_head"
_TABLES = ("idempotency_anchors", "recorded_stops")
_CATALOG = (
    "SELECT attname, format_type(atttypid, atttypmod), attnotnull, "
    "pg_get_expr(d.adbin, d.adrelid) FROM pg_attribute a LEFT JOIN pg_attrdef d "
    "ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
    "WHERE attrelid = %(t)s::regclass AND attnum > 0 AND NOT attisdropped ORDER BY attnum",
    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
    "WHERE conrelid = %(t)s::regclass ORDER BY conname",
    "SELECT i.relname, pg_get_indexdef(i.oid) FROM pg_index x "
    "JOIN pg_class i ON i.oid = x.indexrelid WHERE x.indrelid = %(t)s::regclass ORDER BY 1",
    "SELECT tgname, tgenabled, pg_get_triggerdef(oid) FROM pg_trigger "
    "WHERE tgrelid = %(t)s::regclass AND NOT tgisinternal ORDER BY tgname",
)
_VERSION = "SELECT version_num FROM alembic_version"
_USER, _ACCOUNT, _ORDER, _GROUP = (uuid.UUID(int=n) for n in (0xA1, 0xB1, 0xC1, 0xD1))
_REF, _SHA = "9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59", "ab" * 32
_LINK = "cvd-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"

Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#913)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ, "CV_PG_DSN": dsn}, capture_output=True, text=True,
        check=False, timeout=120,
    )  # fmt: skip


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """A server whose `_TEMPLATE` database is at head and untouched, for each test to clone."""
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+psycopg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        server = dsn.rsplit("/", 1)[0]
        with _conn(f"{server}/postgres") as c:
            stmt = sql.SQL("CREATE DATABASE {} TEMPLATE {}")
            c.execute(stmt.format(sql.Identifier(_TEMPLATE), sql.Identifier(dsn.rsplit("/")[-1])))
        yield dsn


@pytest.fixture
def db(pg_dsn: str) -> str:
    """A fresh clone of the head database, this test's own."""
    name = f"t_{uuid.uuid4().hex[:16]}"
    server = pg_dsn.rsplit("/", 1)[0]
    with _conn(f"{server}/postgres") as c:
        stmt = sql.SQL("CREATE DATABASE {} TEMPLATE {}")
        c.execute(stmt.format(sql.Identifier(name), sql.Identifier(_TEMPLATE)))
    return f"{server}/{name}"


def _fence(heading: str, index: int) -> str:
    section = _DOC.read_text(encoding="utf-8").split(f"#### {heading}", 1)[1]
    section = re.split(r"\n#{1,4} ", section, maxsplit=1)[0]
    return section.split("```sql")[index + 1].split("```", 1)[0]


def _doc_ddl() -> str:
    """21 Sec.3.3.10 and Sec.3.3.11, both blocks each: each table's second block holds its guard
    and its TRUNCATE trigger."""
    anchors = "3.3.10 `idempotency_anchors`"
    stops = "3.3.11 `recorded_stops`"
    blocks = [_fence(anchors, 0), _fence(anchors, 1), _fence(stops, 0), _fence(stops, 1)]
    return "\n".join(blocks)


def _catalog(c: Conn, schema: str) -> list[list[tuple[str, ...]]]:
    unqualify = re.compile(r"\b(?:public|doc_ref)\.")
    catalogue: list[list[tuple[str, ...]]] = []
    for table, query in ((t, q) for t in _TABLES for q in _CATALOG):
        rows = c.execute(query, {"t": f"{schema}.{table}"})
        catalogue.append([tuple(unqualify.sub("", str(v)) for v in row) for row in rows])
    return catalogue


def _seed(c: Conn) -> None:
    """A user, an account (with its bootstrap profile), an entry's group and leg, and an order."""
    c.execute(
        "INSERT INTO users (id, email, username, password_hash, status) "
        "VALUES (%s, 'u@example.test', 'user_one', '$argon2id$x', 'active')",
        (_USER,),
    )
    c.execute(
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', 'demo', 'main', '1001', 'acct')",
        (_ACCOUNT,),
    )
    profile, version = c.execute(
        "SELECT id, version FROM account_profiles WHERE exchange_account_id = %s AND is_default",
        (_ACCOUNT,),
    ).fetchone() or (None, None)
    c.execute(
        "INSERT INTO trade_groups (id, client_group_ref, client_body_sha256, created_by, env, "
        "symbol, side, status, leg_failure_policy) VALUES (%s, %s, %s, %s, 'demo', 'BTCUSDT', "
        "'Buy', 'submitting', 'best_effort')",
        (_GROUP, _REF, _SHA, _USER),
    )
    snapshot = {"account_id": str(_ACCOUNT), "profile_id": str(profile), "version": version}
    leg = uuid.uuid4()
    c.execute(
        "INSERT INTO trade_group_legs (id, trade_group_id, exchange_account_id, account_profile_id,"
        " profile_version, profile_snapshot, status, sequence_no, target_qty, resolved_leverage, "
        "resolved_sl_price) VALUES (%s, %s, %s, %s, %s, %s::jsonb, 'pending', 0, 0.010, 5, 62000)",
        (leg, _GROUP, _ACCOUNT, profile, version, json.dumps(snapshot)),
    )
    c.execute(
        "INSERT INTO orders (id, trade_group_leg_id, exchange_account_id, order_link_id, symbol, "
        "side, intent, order_type, qty, stop_loss, state, lifecycle_state) VALUES (%s, %s, %s, "
        "%s, 'BTCUSDT', 'Buy', 'entry', 'Market', 0.010, 62000, 'pending_submit', 'validated')",
        (_ORDER, leg, _ACCOUNT, _LINK),
    )


_ANCHOR_SQL = (
    "INSERT INTO idempotency_anchors (id, created_by, operation, client_ref, request_sha256, "
    "trade_group_id, order_id) VALUES (%(id)s, %(user)s, %(op)s, %(ref)s, %(sha)s, %(group)s, "
    "%(order)s)"
)
_STOP_SQL = (
    "INSERT INTO recorded_stops (id, exchange_account_id, symbol, position_idx, position_side, "
    "kind, source, order_id, tpsl_mode, trigger_price, size, audit_record_id, actor_user_id, "
    "position_marker) VALUES (%(id)s, %(account)s, 'BTCUSDT', 0, 'Buy', %(kind)s, %(source)s, "
    "%(order)s, %(mode)s, %(px)s, %(size)s, %(audit)s, %(user)s, %(marker)s)"
)


def _anchor(c: Conn, **over: Any) -> uuid.UUID:
    values = _values("anchor", over)
    c.execute(_ANCHOR_SQL, values)
    return uuid.UUID(str(values["id"]))


def _stop(c: Conn, **over: Any) -> uuid.UUID:
    values = _values("stop", over)
    c.execute(_STOP_SQL, values)
    return uuid.UUID(str(values["id"]))


def _refused(c: Conn, statement: str | sql.Composed, params: Any = None) -> psycopg.Error:
    with pytest.raises(psycopg.Error) as exc:
        c.execute(statement, params)
    return exc.value


def test_the_catalogue_at_head_is_the_plan_doc(db: str) -> None:
    """Build the doc's DDL in a scratch schema (rolled back) and diff the two catalogues."""
    with _conn(db) as c, c.transaction():
        c.execute("CREATE SCHEMA doc_ref")
        c.execute("SET LOCAL search_path = doc_ref, public")
        c.execute(_doc_ddl().encode())
        got, want = _catalog(c, "public"), _catalog(c, "doc_ref")
        raise psycopg.Rollback
    assert got == want and all(got)
    triggers = [row for table in got[3::4] for row in table]
    assert {row[0] for row in triggers} == {
        "trg_ia_no_truncate", "trg_ia_write_once", "trg_rs_guard", "trg_rs_no_truncate"
    } and {row[1] for row in triggers} == {"A"}  # fmt: skip


@pytest.mark.parametrize("seeded", [False, True], ids=["empty", "seeded"])
def test_the_revision_round_trips(db: str, seeded: bool) -> None:
    """C-5.5: an order that came the usual way does not hold the downgrade back."""
    with _conn(db) as c:
        if seeded:
            _seed(c)
        head = _catalog(c, "public")
    assert _alembic(db, "downgrade", _PREV).returncode == 0
    with _conn(db) as c:
        gone = c.execute(
            "SELECT to_regclass('idempotency_anchors'), to_regclass('recorded_stops'), "
            "(SELECT count(*) FROM pg_attribute WHERE attrelid = 'orders'::regclass "
            "AND attname = 'provenance' AND NOT attisdropped), "
            "(SELECT count(*) FROM pg_proc WHERE proname = 'audit_refuse_truncate')"
        ).fetchone()
        assert gone == (None, None, 0, 1)
        kept = c.execute("SELECT count(*) FROM orders").fetchone()
        assert kept == ((1,) if seeded else (0,))
    assert _alembic(db, "upgrade", "head").returncode == 0
    with _conn(db) as c:
        assert _catalog(c, "public") == head


_RECORDS: dict[str, Callable[[Conn], object]] = {
    "an anchor": lambda c: _anchor(c),
    "a recorded stop": lambda c: _stop(c),
    "a reconciled order": lambda c: c.execute(
        "UPDATE orders SET provenance = 'reconciliation' WHERE id = %s", (_ORDER,)
    ),
}


@pytest.mark.parametrize("record", list(_RECORDS))
def test_the_downgrade_refuses_while_the_record_holds_a_row(db: str, record: str) -> None:
    with _conn(db) as c:
        _seed(c)
        _RECORDS[record](c)
        before = c.execute(_VERSION).fetchone(), _catalog(c, "public")
    refused = _alembic(db, "downgrade", _PREV)
    assert refused.returncode != 0 and "0043_order_submission downgrade refused" in refused.stderr
    with _conn(db) as c:
        assert (c.execute(_VERSION).fetchone(), _catalog(c, "public")) == before


_CHECKS: dict[str, tuple[str, dict[str, Any], str]] = {
    "ia_operation": ("anchor", {"op": "cancelOrder"}, "ia_operation"),
    "ia_ref_fmt": ("anchor", {"ref": _REF.upper()}, "ia_ref_fmt"),
    "ia_target-none": ("anchor", {"group": None}, "ia_target"),
    "ia_target-both": ("anchor", {"order": _ORDER}, "ia_target"),
    "sha256_hex": ("anchor", {"sha": "AB" * 32}, "sha256_hex_check"),
    "rs_entry": ("stop", {"order": None}, "rs_entry"),
    "rs_restore": ("stop", {"source": "restore", "order": None, "kind": "take_profit"},
                   "rs_restore"),
    "rs_px": ("stop", {"px": 0}, "rs_px"),
    "rs_size": ("stop", {"mode": "Partial"}, "rs_size"),
    "rs_finite": ("stop", {"px": "NaN"}, "rs_finite"),
    "rs_marker": ("stop", {"marker": ""}, "rs_marker"),
}  # fmt: skip


@pytest.mark.parametrize("case", list(_CHECKS))
def test_each_check_refuses_by_its_name(db: str, case: str) -> None:
    table, over, name = _CHECKS[case]
    with _conn(db) as c:
        _seed(c)
        error = _refused(c, _ANCHOR_SQL if table == "anchor" else _STOP_SQL, _values(table, over))
    assert error.diag.sqlstate == "23514" and error.diag.constraint_name == name


def _values(table: str, over: dict[str, Any]) -> dict[str, Any]:
    if table == "anchor":
        return {"id": uuid.uuid4(), "user": _USER, "op": "placeOrder", "ref": _REF, "sha": _SHA,
                "group": _GROUP, "order": None} | over  # fmt: skip
    return {"id": uuid.uuid4(), "account": _ACCOUNT, "kind": "stop_loss", "source": "entry_attach",
            "order": _ORDER, "mode": "Full", "px": 62000, "size": None, "audit": uuid.uuid4(),
            "user": _USER, "marker": None} | over  # fmt: skip


def test_ord_provenance_admits_three_values(db: str) -> None:
    with _conn(db) as c:
        _seed(c)
        for value in ("reconciliation", "recorded_stop", "placed"):
            c.execute("UPDATE orders SET provenance = %s WHERE id = %s", (value, _ORDER))
        error = _refused(c, "UPDATE orders SET provenance = 'imported' WHERE id = %s", (_ORDER,))
    assert error.diag.constraint_name == "ord_provenance"


def _update(c: Conn, record: uuid.UUID, assignments: str) -> None:
    update = sql.SQL("UPDATE recorded_stops SET {} WHERE id = %s")
    c.execute(update.format(sql.SQL(assignments)), (record,))


def test_the_guards_hold_under_the_replica_role(db: str) -> None:
    """`ENABLE ALWAYS`: one bind and one stamped release, never a re-bind; the times and the
    marker set once; only the lifecycle's status moves; the anchor's outcome written once."""
    with _conn(db) as c:
        _seed(c)
        record, anchor = _stop(c), _anchor(c)
        c.execute("SET session_replication_role = replica")
        refusals = {
            "request": "trigger_price = 61000",
            "status": "status = 'ended', closed_at = now()",
        }
        for assignments in refusals.values():
            assert _refused_update(c, record, assignments) == "trg_rs_guard"
        _update(c, record, "answered_at = now(), exchange_order_id = 'X1', position_marker = 'm1'")
        for assignments in ("answered_at = now() + interval '1 s'", "position_marker = 'm2'",
                            "exchange_order_id = 'X2'", "exchange_order_id = NULL"):  # fmt: skip
            assert _refused_update(c, record, assignments) == "trg_rs_guard"
        _update(c, record, "exchange_order_id = NULL, released_at = now()")
        assert _refused_update(c, record, "exchange_order_id = 'X3'") == "trg_rs_guard"
        _update(c, record, "status = 'in_force', in_force_at = now()")
        assert _refused_update(c, record, "status = 'pending'") == "trg_rs_guard"
        c.execute(
            "UPDATE idempotency_anchors SET outcome_status = 202, decided_at = now() "
            "WHERE id = %s AND outcome_status IS NULL",
            (anchor,),
        )
        error = _refused(
            c, "UPDATE idempotency_anchors SET decided_at = now() WHERE id = %s", (anchor,)
        )
        assert error.diag.constraint_name == "trg_ia_write_once"


def test_a_record_ends_unread_only_once_answered(db: str) -> None:
    """#4010's CR-G6-R4-05 (f): `pending` -> `ended` once the request is answered, `in_force_at`
    left NULL; the guard refuses the move unanswered, and `rs_times` refuses an `ended` row that
    holds neither time."""
    with _conn(db) as c:
        _seed(c)
        record = _stop(c)
        assert _refused_update(c, record, "status = 'ended', closed_at = now()") == "trg_rs_guard"
        _update(c, record, "answered_at = now()")
        _update(c, record, "status = 'ended', closed_at = now()")
        ended = c.execute(
            "SELECT status, in_force_at IS NULL, answered_at IS NOT NULL FROM recorded_stops "
            "WHERE id = %s",
            (record,),
        ).fetchone()
        assert ended == ("ended", True, True)
        unanswered = _STOP_SQL.replace(") VALUES (", ", status, closed_at) VALUES (").replace(
            "%(marker)s)", "%(marker)s, 'ended', now())"
        )
        trading = _values("stop", {"order": None, "source": "trading_stop"})
        error = _refused(c, unanswered, trading)
    assert error.diag.constraint_name == "rs_times"


def _refused_update(c: Conn, record: uuid.UUID, assignments: str) -> str | None:
    with pytest.raises(psycopg.Error) as exc:
        _update(c, record, assignments)
    assert exc.value.diag.sqlstate == "23514"
    return exc.value.diag.constraint_name


@pytest.mark.parametrize("table", _TABLES)
def test_no_role_truncates_the_record(db: str, table: str) -> None:
    with _conn(db) as c:
        error = _refused(c, sql.SQL("TRUNCATE {}").format(sql.Identifier(table)))
    assert error.diag.sqlstate == "P0001"
    assert f"table {table} is append-only: TRUNCATE refused" in str(error)


#: Every reference the two tables hold (21 Sec.3.3.10, Sec.3.3.11), each `ON DELETE RESTRICT`.
_KEPT = (
    "idempotency_anchors_created_by_fkey",
    "idempotency_anchors_trade_group_id_fkey",
    "idempotency_anchors_order_id_fkey",
    "recorded_stops_exchange_account_id_fkey",
    "recorded_stops_order_id_fkey",
    "recorded_stops_actor_user_id_fkey",
)


def test_the_rows_the_record_names_are_kept(db: str) -> None:
    """RESTRICT: an order, a group or a user the record names is never deleted under it. Where
    two references name one row, the RI triggers' name order, which their OIDs set, picks the
    one that refuses, so the test asks only that one of them does, and reads each reference's
    action from the catalogue."""
    other = uuid.UUID(int=0xA2)
    with _conn(db) as c:
        _seed(c)
        _stop(c)
        _anchor(c)
        c.execute(
            "INSERT INTO users (id, email, username, password_hash, status) "
            "VALUES (%s, 'v@example.test', 'user_two', '$argon2id$x', 'active')",
            (other,),
        )
        _anchor(c, user=other, group=None, order=_ORDER)
        refused = {
            "orders": _refused(c, "DELETE FROM orders WHERE id = %s", (_ORDER,)),
            "trade_groups": _refused(c, "DELETE FROM trade_groups WHERE id = %s", (_GROUP,)),
            "users": _refused(c, "DELETE FROM users WHERE id = %s", (other,)),
        }
        actions = c.execute(
            "SELECT conname, confdeltype FROM pg_constraint WHERE conname = ANY(%s)", (list(_KEPT),)
        ).fetchall()
    assert {name: e.diag.sqlstate for name, e in refused.items()} == dict.fromkeys(refused, "23503")
    assert refused["orders"].diag.constraint_name in {
        "idempotency_anchors_order_id_fkey",
        "recorded_stops_order_id_fkey",
    }
    assert refused["users"].diag.constraint_name == "idempotency_anchors_created_by_fkey"
    assert dict(actions) == dict.fromkeys(_KEPT, "r")


def test_one_request_in_flight_and_one_row_in_force_per_position(db: str) -> None:
    with _conn(db) as c:
        _seed(c)
        first = _stop(c)
        trading = {"source": "trading_stop", "order": None}
        error = _refused(c, _STOP_SQL, _values("stop", trading))
        assert error.diag.constraint_name == "ux_rs_in_flight"
        _update(c, first, "answered_at = now(), status = 'in_force', in_force_at = now()")
        second = _stop(c, **trading)
        error = _refused(
            c,
            "UPDATE recorded_stops SET answered_at = now(), status = 'in_force', "
            "in_force_at = now() WHERE id = %s",
            (second,),
        )
        assert error.diag.constraint_name == "ux_rs_in_force"
