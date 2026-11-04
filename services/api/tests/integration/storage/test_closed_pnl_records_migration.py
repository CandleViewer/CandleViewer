"""Integration: the `closed_pnl_records` revision on Postgres 16 (E29-S06 #981 slice 2; 21
Sec.3.3.13, Sec.3.3.6, Sec.3.3.7): the CHECKs, the guard and the triggers refuse what 21 says, and
`trade_group_id` names a group and stays writable; the indexes are built valid in the revision's
transaction; the round trip on an empty and a seeded database, and its refusals."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, LiteralString
from uuid import UUID

import psycopg
import pytest
from psycopg import errors as pgerr
from psycopg import sql
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
[_FILE] = sorted(_ROOT.glob("candleviewer/migrations/versions/*_closed_pnl_records.py"))
_SPEC = importlib.util.spec_from_file_location("rev_closed_pnl_records_it", _FILE)
assert _SPEC is not None and _SPEC.loader is not None
_REVISION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_REVISION)
_T0, _S = datetime(2026, 11, 2, 9, 0, tzinfo=UTC), timedelta(seconds=1)
_SETTLED = {"qty": 4, "avg_entry_price": 148, "avg_exit_price": 150, "leverage": 3, "closed_pnl": 8,
            "venue_created_at": _T0, "settled_at": _T0}  # fmt: skip
_ROWS: dict[str, dict[str, Any]] = {
    "closed_pnl_records": {"exchange_order_id": "o-1", "symbol": "SOLUSDT", "side": "long",
                           "closed_at": _T0},
    "executions": {"symbol": "SOLUSDT", "side": "Sell", "exec_qty": 1, "exec_price": 150,
                   "exec_value": 150, "exec_type": "Trade", "is_maker": False, "exec_ts": _T0},
    "position_snapshots": {"symbol": "SOLUSDT", "size": 0, "reason": "ws_push"},
    "orders": {"symbol": "SOLUSDT", "side": "Sell", "intent": "entry", "order_type": "Market",
               "qty": 4, "state": "partially_filled"},
}  # fmt: skip
Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg")}
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#981)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env=env, capture_output=True, text=True, check=False, timeout=300,
    )  # fmt: skip


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        yield dsn


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _fresh(dsn: str) -> str:
    base, name = dsn.rsplit("/", 1)[0], f"cpr_{uuid.uuid4().hex[:12]}"
    with _conn(f"{base}/postgres") as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return f"{base}/{name}"


def _put(c: Conn, table: str, account: UUID | None = None, **cols: Any) -> Any:
    """One row of `table`, its defaults (`_ROWS`) under `cols`; an account when none is named."""
    row: dict[str, Any] = {"id": uuid.uuid4(), **_ROWS.get(table, {})}
    if account is None:
        uid = str(uuid.uuid4().int % 10**15)
        row |= {
            "exchange": "bybit",
            "env": "demo",
            "kind": "main",
            "exchange_uid": uid,
            "label": uid,
        }
    else:
        row["exchange_account_id"] = account
    row |= {"order_link_id": f"ext-{row['id'].hex}"} if table == "orders" else {}
    row = {k: v for k, v in (row | cols).items() if (k, table) != ("id", "position_snapshots")}
    stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING id").format(
        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, row)),
        sql.SQL(", ").join([sql.Placeholder()] * len(row)),
    )  # fmt: skip
    got = c.execute(stmt, tuple(row.values())).fetchone()
    assert got is not None
    return got[0]


def _group(c: Conn) -> UUID:
    """A trade group (0039, 21 Sec.3.3.2) and the user who created it."""
    user, group = uuid.uuid4(), uuid.uuid4()
    c.execute(
        "INSERT INTO users (id, email, username, password_hash) VALUES (%s, %s, %s, '$argon2id$x')",
        (user, f"{user.hex}@example.test", f"u_{user.hex[:12]}"),
    )
    c.execute(
        "INSERT INTO trade_groups (id, client_group_ref, client_body_sha256, created_by, env, "
        "symbol, side) VALUES (%s, %s, %s, %s, 'demo', 'SOLUSDT', 'Buy')",
        (group, str(uuid.uuid4()), "ab" * 32, user),
    )
    return group


@pytest.mark.parametrize(
    ("over", "constraint"),
    [
        ({"side": "buy"}, "cpr_side"), ({"position_idx": 3}, "cpr_posidx"),
        ({"exchange_order_id": ""}, "cpr_order"), ({"exchange_order_id": "x" * 65}, "cpr_order"),
        ({"exchange_order_id": None}, "cpr_settled"),  # a provisional record names its order
        ({"closed_pnl": 8}, "cpr_settled"),  # the venue's figure, unread
        ({**_SETTLED, "leverage": None}, "cpr_settled"),
        ({"final_at": _T0}, "cpr_final"),  # final, never settled
        ({**_SETTLED, "final_at": _T0 - _S}, "cpr_final"),
        ({**_SETTLED, "exchange_order_id": None, "final_at": _T0}, "cpr_final"),
        ({"qty": 0}, "cpr_qty"), ({**_SETTLED, "audited_local_net": 7}, "cpr_pair"),
        ({**_SETTLED, "divergent": True}, "cpr_pair"),  # divergent with no recorded pair
        ({"divergent": True, "audited_local_net": 7, "audited_closed_pnl": 8}, "cpr_pair"),
        ({"gross_pnl": Decimal("NaN")}, "cpr_numbers"),
    ],
)  # fmt: skip
def test_a_row_the_table_cannot_hold_is_refused_by_its_named_check(
    pg_dsn: str, over: dict[str, Any], constraint: str
) -> None:
    with _conn(pg_dsn) as c:
        account = _put(c, "exchange_accounts")
        with pytest.raises(pgerr.CheckViolation) as err:
            _put(c, "closed_pnl_records", account, **over)
    assert err.value.diag.constraint_name == constraint


def test_one_record_per_order_a_fill_closes_at_most_its_size_and_the_guard_freezes(
    pg_dsn: str,
) -> None:
    """`trg_cpr_guard` refuses what 21 Sec.3.3.13 lists (the identity, a stamp once set, the
    venue's columns once final) and nothing else, `trade_group_id` on a final row included, under
    the replica role too, where the DELETE and TRUNCATE triggers still keep every row."""
    with _conn(pg_dsn) as c:
        account, other = _put(c, "exchange_accounts"), _put(c, "exchange_accounts")
        for _ in range(2):  # no order: no key
            _put(c, "closed_pnl_records", account, exchange_order_id=None, **_SETTLED)
        rid = _put(c, "closed_pnl_records", account)
        with pytest.raises(pgerr.UniqueViolation, match="ux_cpr_order"):
            _put(c, "closed_pnl_records", account)
        _put(c, "executions", account, exec_id="e0", closed_size=1)  # exec_qty 1
        for size in (2, -1):
            with pytest.raises(pgerr.CheckViolation, match="ex_closed"):
                _put(c, "executions", account, exec_id=f"e{size}", closed_size=size)
        update: LiteralString = "UPDATE closed_pnl_records SET {} WHERE id = %s"

        def change(assignment: str, *args: Any) -> None:
            text = sql.SQL(assignment)  # type: ignore[arg-type]  # the test's own SQL
            c.execute(sql.SQL(update).format(text), (*args, rid))

        change("qty = 5, closed_at = closed_at + interval '1 second'")  # provisional: writable
        change(", ".join(f"{k} = %s" for k in _SETTLED), *_SETTLED.values())  # settled
        change("qty = 6, closed_pnl = 9")  # a later read that differs, before final
        change("final_at = now()")
        refusals = [
            ("id", "id = gen_random_uuid()"), ("symbol", "symbol = 'BTCUSDT'"),
            ("side", "side = 'short'"), ("exchange_order_id", "exchange_order_id = 'o-2'"),
            ("exchange_account_id", f"exchange_account_id = '{other}'"),
            ("final_at", "final_at = NULL"), ("qty", "qty = 7"), ("leverage", "leverage = 5"),
            *((k, f"{k} = {k} + interval '1s'") for k in ("settled_at", "closed_at")),
            ("venue_created_at", "venue_created_at = venue_created_at + interval '1s'"),
            *((k, f"{k} = {k} + 1") for k in ("avg_entry_price", "avg_exit_price", "closed_pnl")),
        ]  # fmt: skip
        for column, assignment in refusals:
            with pytest.raises(pgerr.CheckViolation, match=f"closed_pnl_records.{column} may not"):
                change(assignment)
        change("gross_pnl = 9, fee_pnl = -1, funding_pnl = 0, opened_at = now(), divergent = true, "
               "audited_local_net = 8, audited_closed_pnl = 9")  # fmt: skip
        change("trade_group_id = %s", _group(c))  # the composition's alone, final or not (C2)
        change("trade_group_id = NULL")  # several groups, or none
        c.execute("SET session_replication_role = replica")  # ENABLE ALWAYS: still refused
        for statement, error, match in [
            ("DELETE FROM closed_pnl_records", pgerr.RaiseException, "is append-only"),
            ("TRUNCATE closed_pnl_records", pgerr.RaiseException, "TRUNCATE refused"),
            ("UPDATE closed_pnl_records SET side = 'short'", pgerr.CheckViolation, "trg_cpr_guard"),
        ]:  # fmt: skip
            with pytest.raises(error, match=match):
                c.execute(statement)  # type: ignore[call-overload]  # literal SQL under test


def test_the_indexes_are_valid_ex_closed_validated_and_a_group_is_restricted(pg_dsn: str) -> None:
    """The five indexes, plain builds in the revision's transaction, are valid; `ex_closed` was
    validated there; `trade_group_id` names a stored group, `ON DELETE RESTRICT` (Sec.3.3.13)."""
    with _conn(pg_dsn) as c:
        built = c.execute(
            "SELECT count(*), bool_and(indisvalid AND indisready) FROM pg_index WHERE indexrelid "
            "IN ('ix_exec_walk'::regclass, 'ix_psnap_flat'::regclass, 'ix_cpr_day'::regclass, "
            "'ix_cpr_pending'::regclass, 'ix_cpr_group'::regclass)"
        ).fetchone()
        valid = c.execute("SELECT convalidated FROM pg_constraint WHERE conname = 'ex_closed'")
        assert built == (5, True) and valid.fetchone() == (True,)
        fk = c.execute(
            "SELECT confdeltype FROM pg_constraint WHERE contype = 'f' AND conrelid = "
            "'closed_pnl_records'::regclass AND confrelid = 'trade_groups'::regclass"
        )
        assert fk.fetchall() == [("r",)]
        account = _put(c, "exchange_accounts")
        with pytest.raises(pgerr.ForeignKeyViolation, match="trade_group_id"):
            _put(c, "closed_pnl_records", account, trade_group_id=uuid.uuid4())


def test_round_trip_on_an_empty_database(pg_dsn: str) -> None:
    """C-5.5, the empty half: up, down to the parent and up again."""
    dsn, prev = _fresh(pg_dsn), _REVISION.down_revision
    for step in (("upgrade", "head"), ("downgrade", prev), ("upgrade", "head")):
        assert _alembic(dsn, *step).returncode == 0, step


def test_round_trip_on_a_seeded_database_and_each_refused_downgrade(pg_dsn: str) -> None:
    """C-5.2, C-5.5: rows elsewhere never block the round trip; a record, a fill's `closed_size`
    or a venue-dated reading refuses the downgrade, as dropping it would lose it for good."""
    dsn, prev = _fresh(pg_dsn), _REVISION.down_revision
    assert _alembic(dsn, "upgrade", "head").returncode == 0
    with _conn(dsn) as c:
        a = _put(c, "exchange_accounts")
        _put(c, "executions", a, exec_id="s1")
        _put(c, "position_snapshots", a)
        for step in (("downgrade", prev), ("upgrade", "head")):
            assert _alembic(dsn, *step).returncode == 0, step
        stored = [("closed_pnl_records", {}), ("executions", {"exec_id": "s2", "closed_size": 1}),
                  ("position_snapshots", {"exchange_updated_ts": _T0})]  # fmt: skip
        for table, cols in stored:
            with pytest.raises(pgerr.RaiseException, match="downgrade refused"), c.transaction():
                _put(c, table, a, **cols)
                c.execute(_REVISION._REFUSE_SQL)
        _put(c, "closed_pnl_records", a)
        refused = _alembic(dsn, "downgrade", prev)
        assert refused.returncode != 0 and "downgrade refused" in refused.stderr
        kept = c.execute("SELECT to_regclass('closed_pnl_records')::text").fetchone()
        assert kept == ("closed_pnl_records",)
