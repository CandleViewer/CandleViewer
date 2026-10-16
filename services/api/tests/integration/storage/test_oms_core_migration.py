"""Integration: `0029_oms_core` against real Postgres 16 (E29-T01 #845).

The catalog equals 21-database-schema.md Sec.3.3.4-3.3.7 but the two documented leg FKs; the #845
Gherkin scenarios that are pure database behaviour hold on the engine; every invalid row is refused
by its NAMED constraint; the C-5.7 guards (TRUNCATE trigger, revoked grants) and the Sec.3.3.4
adopted-row rule (both id arms) hold; an empty and a seeded database round-trip and a populated
one refuses. `testcontainers` in CI; run on a scratch PostgreSQL 16.2 before push (no docker on
the laptop).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors as pgerr
from psycopg import sql
from testcontainers.postgres import PostgresContainer

from candleviewer.domain.order_link import ext_key
from candleviewer.domain.primitives import AccountId, GroupId
from candleviewer.oms.order_link import OrderLinkIdParts

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0029_oms_core", "0028_incidents_backups"
_TABLES = ("orders", "order_events", "executions", "positions", "position_snapshots")
_BLOCKS = ("3.3.4 `orders`", "3.3.5 `order_events`", "3.3.6 `executions`", "3.3.7 `positions`")
_LEG_FK = " REFERENCES trade_group_legs(id) ON DELETE SET NULL"  # deferred to E28-T01 (#905)
_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
_OUR = "cvl-0TLr6mSAQFGvyfsJ0nLDCh-d0hb-00en"  # the #845 Gherkin id, 24-internal-schemas.md Sec.8.3
_TEMPLATE = "oms_head_template"

Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#845)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _database(dsn: str, name: str) -> str:
    return f"{dsn.rsplit('/', 1)[0]}/{name}"


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """Head, plus an untouched copy of it that `_fresh` clones for tests needing empty tables."""
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        with _conn(_database(dsn, "postgres")) as c:
            c.execute(
                sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                    sql.Identifier(_TEMPLATE), sql.Identifier(dsn.rsplit("/", 1)[1])
                )
            )
        yield dsn


def _fresh(dsn: str) -> str:
    name = f"oms_{uuid.uuid4().hex[:12]}"
    with _conn(_database(dsn, "postgres")) as c:
        c.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name), sql.Identifier(_TEMPLATE)
            )
        )
    return _database(dsn, name)


def _insert(c: Conn, table: str, row: dict[str, object]) -> str:
    stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING id::text").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(k) for k in row),
        sql.SQL(", ").join([sql.Placeholder()] * len(row)),
    )
    got = c.execute(stmt, tuple(row.values())).fetchone()
    assert got is not None
    return str(got[0])


def _account(c: Conn) -> str:
    uid = str(uuid.uuid4().int % 10**15)
    row: dict[str, object] = {"id": str(uuid.uuid4()), "exchange": "bybit", "env": "demo"}
    row |= {"kind": "main", "exchange_uid": uid, "label": f"acct {uid}"}
    return _insert(c, "exchange_accounts", row)


def _link(account: str) -> str:
    """A real `OUR_ID`, from the #846 generator."""
    return OrderLinkIdParts.generate(
        mode="exchange",
        environment="demo",
        group_id=GroupId(uuid.uuid4()),
        account_id=AccountId(uuid.UUID(account)),
        seq=0,
        purpose="entry",
    ).value


def _order(c: Conn, account: str, **cols: object) -> str:
    row = {"id": str(uuid.uuid4()), "exchange_account_id": account, "order_link_id": _link(account)}
    row |= {"symbol": "BTCUSDT", "side": "Buy", "intent": "entry", "order_type": "Market"}
    return _insert(c, "orders", row | {"qty": Decimal("0.010")} | cols)


def _event(c: Conn, account: str, **cols: object) -> str:
    order = str(cols.pop("order_id", None) or _order(c, account))
    row = {"order_id": order, "seq": 0, "kind": "local_create", "source": "local"}
    return _insert(c, "order_events", row | {"event_ts": _NOW} | cols)


def _execution(c: Conn, account: str, **cols: object) -> str:
    row: dict[str, object] = {"id": str(uuid.uuid4()), "exchange_account_id": account}
    row |= {"exec_id": uuid.uuid4().hex, "symbol": "BTCUSDT", "side": "Buy"}
    row |= {"exec_qty": Decimal("0.010"), "exec_price": Decimal("63099.80")}
    row |= {"exec_value": Decimal("630.998"), "exec_type": "Trade", "is_maker": False}
    return _insert(c, "executions", row | {"exec_ts": _NOW} | cols)


def _position(c: Conn, account: str, **cols: object) -> str:
    row = {"id": str(uuid.uuid4()), "exchange_account_id": account, "symbol": "BTCUSDT"}
    return _insert(c, "positions", row | cols)


def _snapshot(c: Conn, account: str, **cols: object) -> str:
    row = {"exchange_account_id": account, "symbol": "BTCUSDT", "size": Decimal("0")}
    return _insert(c, "position_snapshots", row | {"reason": "ws_push"} | cols)


_ROW: dict[str, Callable[..., str]] = {
    "orders": _order,
    "order_events": _event,
    "executions": _execution,
    "positions": _position,
    "position_snapshots": _snapshot,
}

# --- The catalog equals the plan doc, and the round trip leaves nothing behind ----------------

_CATALOG = (
    "SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, a.attgenerated, "
    "pg_get_expr(d.adbin, d.adrelid) FROM pg_attribute a LEFT JOIN pg_attrdef d "
    "ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
    "WHERE a.attrelid = %(t)s::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum",
    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
    "WHERE conrelid = %(t)s::regclass ORDER BY conname",
    "SELECT i.relname, pg_get_indexdef(i.oid) FROM pg_index x "
    "JOIN pg_class i ON i.oid = x.indexrelid WHERE x.indrelid = %(t)s::regclass ORDER BY 1",
    "SELECT tgname, pg_get_triggerdef(oid) FROM pg_trigger "
    "WHERE tgrelid = %(t)s::regclass AND NOT tgisinternal ORDER BY tgname",
)


def _doc_ddl() -> str:
    """Sec.3.3.4-3.3.7's ```sql blocks, to their fences, minus the deferred leg FK clause."""
    text = _DOC.read_text(encoding="utf-8")
    blocks = (
        text.split(f"#### {h}", 1)[1].split("```sql", 1)[1].split("```", 1)[0] for h in _BLOCKS
    )
    return "\n".join(blocks).replace(_LEG_FK, "")


def _catalog(c: Conn, schema: str) -> list[list[tuple[str, ...]]]:
    unqualify = re.compile(r"\b(?:public|doc_ref)\.")
    return [
        [
            tuple(unqualify.sub("", str(v)) for v in row)
            for row in c.execute(q, {"t": f"{schema}.{t}"})
        ]
        for t in _TABLES
        for q in _CATALOG
    ]


def _assert_matches_plan_doc(c: Conn) -> None:
    """Build the doc's DDL in a scratch schema (rolled back) and diff the two catalogs."""
    got: list[list[tuple[str, ...]]] = []
    want: list[list[tuple[str, ...]]] = []
    with c.transaction():
        c.execute("CREATE SCHEMA doc_ref")
        c.execute("SET LOCAL search_path = doc_ref, public")
        c.execute(_doc_ddl().encode())
        got, want = _catalog(c, "public"), _catalog(c, "doc_ref")
        raise psycopg.Rollback
    assert got == want and got[0]


def test_schema_matches_the_plan_doc_but_the_deferred_leg_fks(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _assert_matches_plan_doc(c)
        indexes = set(re.findall(r"INDEX (\w+)\s+ON", _doc_ddl()))
        found = c.execute(
            "SELECT indexname FROM pg_indexes WHERE indexname = ANY(%s)", (list(indexes),)
        )
        assert len(indexes) == 22 and {row[0] for row in found} == indexes
        tagged = c.execute(
            "SELECT attrelid::regclass::text, count(*), min(d), max(d) FROM ("
            "SELECT attrelid, col_description(attrelid, attnum) AS d FROM pg_attribute "
            "WHERE attrelid = ANY(%s::regclass[]) AND attnum > 0) s "
            "WHERE d IS NOT NULL GROUP BY 1",
            (list(_TABLES),),
        ).fetchall()
        p1 = "PII: financial personal data (21 Sec.12, class P1); never sent to third parties"
        counts = {"orders": 10, "executions": 7, "positions": 14, "position_snapshots": 7}
        assert {row[0]: row[1:] for row in tagged} == {t: (n, p1, p1) for t, n in counts.items()}


@pytest.mark.parametrize("seeded", [False, True], ids=["empty", "seeded"])
def test_round_trip_leaves_no_residue_and_restores_the_exact_schema(
    pg_dsn: str, seeded: bool
) -> None:
    """C-5.5: upgrade -> downgrade -> upgrade on an empty and on a seeded database (rows in the
    tables the OMS hangs off survive and the restored FKs attach to them)."""
    dsn = _fresh(pg_dsn)
    with _conn(dsn) as c:
        account = _account(c) if seeded else None
    assert _alembic(dsn, "downgrade", _PREV).returncode == 0
    with _conn(dsn) as c:
        for obj in (
            *_TABLES,
            "ux_orders_link",
            "ux_exec_id",
            "ix_pos_no_sl",
            "order_events_id_seq",
        ):
            assert c.execute("SELECT to_regclass(%s)", (obj,)).fetchone() == (None,)
        for kind in ("order_intent", "order_state", "order_event_kind"):
            assert c.execute("SELECT to_regtype(%s)", (kind,)).fetchone() == (None,)
    assert _alembic(dsn, "upgrade", "head").returncode == 0
    with _conn(dsn) as c:
        _assert_matches_plan_doc(c)
        if account is not None:
            assert _order(c, account) and _position(c, account)


@pytest.mark.parametrize("table", ["orders", "executions", "positions", "position_snapshots"])
def test_downgrade_refuses_while_any_oms_table_holds_rows(pg_dsn: str, table: str) -> None:
    """Order history is never dropped by a downgrade; a refused one changes nothing. An event
    cannot exist without its order, so the `orders` case covers `order_events` too."""
    dsn = _fresh(pg_dsn)
    with _conn(dsn) as c:
        _ROW[table](c, _account(c))
        refused = _alembic(dsn, "downgrade", _PREV)
        assert refused.returncode != 0
        assert "0029_oms_core downgrade refused: the OMS tables hold rows" in refused.stderr
        assert c.execute("SELECT version_num FROM alembic_version").fetchone() == (_REV,)
        assert c.execute("SELECT to_regclass(%s)", (table,)).fetchone() == (table,)


# --- The four #845 Gherkin scenarios that are pure database behaviour --------------------------


def test_idempotency_is_enforced_by_the_database(pg_dsn: str) -> None:
    """Scenario "Idempotency is enforced by the database", database half: `ux_orders_link` refuses a
    second row under the scenario's id, whatever its account or state (the repository's
    DuplicateOrderLinkId mapping is slice 2). A fresh database, so the literal id is never taken."""
    with _conn(_fresh(pg_dsn)) as c:
        _order(c, _account(c), order_link_id=_OUR)
        with pytest.raises(pgerr.UniqueViolation) as exc:
            _order(c, _account(c), order_link_id=_OUR, state="cancelled")
        assert exc.value.diag.constraint_name == "ux_orders_link"


@pytest.mark.parametrize("table", ["order_events", "executions"])
@pytest.mark.parametrize("verb", ["UPDATE {} SET id = id", "DELETE FROM {}", "TRUNCATE {}"])
def test_history_cannot_be_rewritten(pg_dsn: str, table: str, verb: str) -> None:
    """Scenario "History cannot be rewritten": `forbid_mutation()` (row) and, for TRUNCATE,
    `audit_refuse_truncate()` (C-5.7) raise, and the whole transaction aborts."""
    count = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
    with _conn(pg_dsn) as c:
        account = _account(c)
        _ROW[table](c, account)
        before = c.execute(count).fetchone()
        with pytest.raises(pgerr.RaiseException, match=f"table {table} is append-only"):
            with c.transaction():
                _ROW[table](c, account)  # lost with the transaction
                c.execute(sql.SQL(verb).format(sql.Identifier(table)))
        assert c.execute(count).fetchone() == before


def test_fills_deduplicate_across_sources(pg_dsn: str) -> None:
    """Scenario "Fills deduplicate across sources": the WS stream twice and the REST backfill
    insert the same exec_id with ON CONFLICT DO NOTHING; one row per account remains."""
    upsert = (
        "INSERT INTO executions (id, exchange_account_id, exec_id, symbol, side, exec_qty, "
        "exec_price, exec_value, exec_type, is_maker, exec_ts) VALUES (%s, %s, 'E1', 'BTCUSDT', "
        "'Buy', 0.01, 63099.80, 630.998, 'Trade', false, %s) "
        "ON CONFLICT (exchange_account_id, exec_id) DO NOTHING"
    )
    with _conn(pg_dsn) as c:
        a, b = _account(c), _account(c)
        for account in (a, a, a, b):  # ws, ws again, rest backfill; then another account's E1
            c.execute(upsert, (str(uuid.uuid4()), account, _NOW))
        rows = c.execute(
            "SELECT exchange_account_id::text FROM executions WHERE exec_id = 'E1' "
            "AND exchange_account_id = ANY(%s::uuid[]) ORDER BY 1",
            ([a, b],),
        ).fetchall()
        assert rows == sorted([(a,), (b,)])
        with pytest.raises(pgerr.UniqueViolation) as exc:
            _execution(c, a, exec_id="E1")
        assert exc.value.diag.constraint_name == "ux_exec_id"


def test_monetary_precision_is_preserved(pg_dsn: str) -> None:
    """Scenario "Monetary precision is preserved": Decimal in, Decimal out, digit for digit at the
    column's scale 18; the driver never builds a float."""
    qty, price = Decimal("0.000000000000000001"), Decimal("63099.80")
    with _conn(pg_dsn) as c:
        oid = _order(c, _account(c), order_type="Limit", qty=qty, price=price)
        row = c.execute(
            "SELECT qty, price, qty::text, price::text FROM orders WHERE id = %s", (oid,)
        ).fetchone()
    assert row is not None
    assert type(row[0]) is Decimal and type(row[1]) is Decimal and row[:2] == (qty, price)
    scale = Decimal(10) ** -18
    assert (row[0].as_tuple(), row[1].as_tuple()) == (
        qty.quantize(scale).as_tuple(),
        price.quantize(scale).as_tuple(),
    )
    assert row[2:] == ("0.000000000000000001", "63099.800000000000000000")


# --- Every invalid row is refused by its NAMED constraint (#845 test plan) --------------------

_SELF = str(uuid.uuid4())


@pytest.mark.parametrize(
    ("table", "cols", "constraint"),
    [
        ("orders", {"qty": Decimal("0")}, "ord_qty"),
        ("orders", {"qty": Decimal("-0.010")}, "ord_cum"),  # CHECKs run in name order: cum < qty
        ("orders", {"cum_exec_qty": Decimal("0.011")}, "ord_cum"),
        ("orders", {"order_link_id": "cv-l7f3a91c2-ent-00"}, "ord_link_fmt"),
        ("orders", {"order_link_id": _OUR + "\n"}, "ord_link_fmt"),
        ("orders", {"order_link_id": "ext-" + "A" * 32}, "ord_link_fmt"),
        ("orders", {"position_idx": 3}, "ord_posidx"),
        ("orders", {"time_in_force": "GTD"}, "ord_tif"),
        ("orders", {"order_type": "Limit", "price": Decimal("0")}, "ord_limit_px"),
        ("orders", {"side": "Long"}, "ord_side"),
        ("orders", {"order_type": "Stop"}, "ord_type"),
        ("orders", {"trigger_direction": 3}, "ord_trigdir"),
        ("orders", {"trigger_by": "LTP"}, "ord_trigby"),
        ("orders", {"take_profit": Decimal("0")}, "ord_tp_px"),
        ("orders", {"stop_loss": Decimal("0")}, "ord_sl_px"),  # "0" clears a stop: stored as NULL
        ("orders", {"stop_loss": Decimal("-1")}, "ord_sl_px"),
        ("orders", {"tpsl_mode": "full"}, "ord_tpslmode"),  # Bybit casing, as positions
        ("orders", {"submit_attempts": 11}, "ord_attempts"),
        ("orders", {"idempotency_state": "sent"}, "ord_idem"),
        ("orders", {"id": _SELF, "parent_order_id": _SELF}, "ord_no_self"),
        ("order_events", {"source": "bybit"}, "oe_source"),
        ("order_events", {"seq": -1}, "oe_seq"),
        ("order_events", {"latency_ms": -1}, "oe_latency"),
        ("executions", {"exec_qty": Decimal("0")}, "ex_qty"),
        ("executions", {"exec_price": Decimal("0")}, "ex_px"),
        ("executions", {"side": "Long"}, "ex_side"),
        ("executions", {"exec_type": "Fee"}, "ex_type"),
        ("executions", {"position_idx": 3}, "ex_posidx"),
        ("positions", {"size": Decimal("-1")}, "pos_size"),
        ("positions", {"side": "Long"}, "pos_side"),
        ("positions", {"position_idx": 3}, "pos_posidx"),
        ("positions", {"tpsl_mode": "Half"}, "pos_tpslmode"),
        ("position_snapshots", {"reason": "cron"}, "psnap_reason"),
    ],
)
def test_invalid_row_is_refused_by_its_named_constraint(
    pg_dsn: str, table: str, cols: dict[str, object], constraint: str
) -> None:
    with _conn(pg_dsn) as c:
        account = _account(c)
        with pytest.raises(pgerr.CheckViolation) as exc:
            _ROW[table](c, account, **cols)
    assert exc.value.diag.constraint_name == constraint


def test_orders_store_the_attached_tp_and_sl_as_decimal(pg_dsn: str) -> None:
    """C-2.6: the native stop attached on create is stored on the row; `ord_tp_px` and `ord_sl_px`
    admit any price above 0, down to the column's smallest step."""
    tp, sl = Decimal("64000.5"), Decimal("0.000000000000000001")
    with _conn(pg_dsn) as c:
        oid = _order(c, _account(c), take_profit=tp, stop_loss=sl, tpsl_mode="Partial")
        row = c.execute(
            "SELECT take_profit, stop_loss, tpsl_mode FROM orders WHERE id = %s", (oid,)
        ).fetchone()
    assert row == (tp, sl, "Partial")


@pytest.mark.parametrize("arm", ["our_id", "ext_key"])
def test_adopted_row_of_either_id_arm_passes_ord_link_fmt_untracked_to_accepted(
    pg_dsn: str, arm: str
) -> None:
    """Sec.3.3.4 "Adopted rows": `ord_link_fmt` has no state term, so an adopted row keeps the
    adapter-normalised id for life: its own OUR_ID when Bybit reports one, otherwise
    `ext_key(orderId)`."""
    exchange_order_id = str(uuid.uuid4())
    with _conn(pg_dsn) as c:
        account = _account(c)
        link = _link(account) if arm == "our_id" else ext_key(exchange_order_id)
        oid = _order(
            c, account, order_link_id=link, exchange_order_id=exchange_order_id, state="untracked"
        )
        c.execute("UPDATE orders SET state = 'accepted' WHERE id = %s", (oid,))
        row = c.execute("SELECT order_link_id, state::text FROM orders WHERE id = %s", (oid,))
        assert row.fetchone() == (link, "accepted")


def test_exchange_order_id_event_seq_and_position_key_are_unique(pg_dsn: str) -> None:
    """`ux_orders_exch_id` per account (NULL never collides), `UNIQUE (order_id, seq)` and the
    one-row-per-(account, symbol, position_idx) key of `positions`."""
    with _conn(pg_dsn) as c:
        a, b = _account(c), _account(c)
        for account in (a, b, a, a):
            _order(c, account, exchange_order_id="X1" if account == b else None)
        _order(c, a, exchange_order_id="X1")
        order = _order(c, a)
        _event(c, a, order_id=order)
        _position(c, a)
        cases: list[tuple[Callable[[], str], str]] = [
            (lambda: _order(c, a, exchange_order_id="X1"), "ux_orders_exch_id"),
            (lambda: _event(c, a, order_id=order), "order_events_order_id_seq_key"),
            (lambda: _position(c, a), "positions_exchange_account_id_symbol_position_idx_key"),
        ]
        for build, constraint in cases:
            with pytest.raises(pgerr.UniqueViolation) as exc:
                build()
            assert exc.value.diag.constraint_name == constraint


def test_leaves_qty_is_generated_from_qty_and_cum_exec_qty_and_never_written(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        oid = _order(c, _account(c), qty=Decimal("2.5"), cum_exec_qty=Decimal("1"))
        c.execute("UPDATE orders SET cum_exec_qty = 2 WHERE id = %s", (oid,))
        leaves = c.execute("SELECT leaves_qty FROM orders WHERE id = %s", (oid,)).fetchone()
        assert leaves == (Decimal("0.5"),)
        with pytest.raises(pgerr.GeneratedAlways):
            c.execute("UPDATE orders SET leaves_qty = 0 WHERE id = %s", (oid,))


# --- C-5.7: no role may rewrite order history (the 0003 grant pattern) --------------------------


@pytest.fixture(scope="module")
def bootstrapped_dsn() -> Iterator[str]:
    """`pg_bootstrap.sql` first, then the migrations as `cv_owner`: the CI `migrations` order, so
    the default privileges apply and the revision's REVOKE meets real roles."""
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        info = psycopg.conninfo.conninfo_to_dict(dsn.replace("postgresql+asyncpg", "postgresql"))
        psql = shutil.which("psql")
        assert psql is not None, "the migrations CI job installs postgresql-client"
        subprocess.run(  # noqa: S603 -- resolved absolute path, fixed argv, no shell (#845)
            [psql, "-h", str(info["host"]), "-p", str(info["port"]), "-U", str(info["user"]),
             "-d", "candleviewer", "-v", "ON_ERROR_STOP=1", "-v", "owner_pw=cv_owner_test_pw",
             "-v", "app_pw=cv_app_test_pw", "-v", "ro_pw=cv_ro_test_pw",
             "-f", str(_ROOT.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql")],
            check=True, capture_output=True,
            env={**os.environ, "PGPASSWORD": str(info["password"])},
        )  # fmt: skip
        owner = re.sub(r"://[^@]+@", "://cv_owner:cv_owner_test_pw@", dsn)
        assert _alembic(owner, "upgrade", "head").returncode == 0
        yield dsn


def test_no_role_may_rewrite_order_history(bootstrapped_dsn: str) -> None:
    query = "SELECT has_table_privilege(%s, %s, %s)"
    with _conn(bootstrapped_dsn) as c:

        def can(role: str, table: str, privilege: str) -> bool:
            return c.execute(query, (role, table, privilege)).fetchone() == (True,)

        for table in ("order_events", "executions"):
            for role in ("cv_app", "cv_ro"):
                assert not any(can(role, table, p) for p in ("UPDATE", "DELETE", "TRUNCATE"))
            assert can("cv_app", table, "INSERT") and can("cv_ro", table, "SELECT")
        assert can("cv_app", "orders", "UPDATE") and can("cv_app", "positions", "UPDATE")
