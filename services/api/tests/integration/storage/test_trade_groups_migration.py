"""Integration: `0039_trade_groups` against real Postgres 16 (E28-T01 #905).

The four tables, their constraints, indexes and triggers, the three enums and the eight trigger
functions equal 21-database-schema.md Sec.1.2, Sec.3.3.2, Sec.3.3.3 and Sec.3.3.3a; every invalid
row is refused by its NAMED constraint or trigger; the replay anchor takes one format and is
unique per creator (G-6(b), SR-E29-07); a leg, a member and a group fired from a definition are in
their environment, and an account in use keeps its own, also under a race (SR-E28-16); a leg's
attribution is write-once and survives a profile edit and a profile delete (SR-E28-07); the
deferred leg FKs are validated and never delete history; the integrity triggers hold under the
replica role, and `cv_app` holds no DELETE on history. An empty and a seeded database round-trip;
one holding a group, a leg, a definition or a member refuses. `testcontainers` in CI.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors as pgerr
from psycopg import sql
from psycopg.types.json import Jsonb
from testcontainers.postgres import PostgresContainer

from candleviewer.accounts.profiles import AccountProfile
from candleviewer.db.models import LEG_FAILURE_POLICIES
from candleviewer.domain.primitives import AccountId, GroupId
from candleviewer.oms.order_link import OrderLinkIdParts

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_FIXTURES = _ROOT / "tests" / "fixtures" / "profiles"
_REV, _PREV = "0039_trade_groups", "0038_risk_state"
_TABLES = (
    "trade_group_definitions",
    "trade_group_definition_members",
    "trade_groups",
    "trade_group_legs",
)
_ENUMS = ("trade_group_status", "leg_status", "algo_kind")
_FUNCTIONS = (
    "ea_env_in_use_check",
    "tg_env_check",
    "tg_write_once",
    "tgd_write_once",
    "tgdm_env_check",
    "tgl_env_check",
    "tgl_profile_check",
    "tgl_write_once",
)
_LEG_FKS = (
    "executions_trade_group_leg_id_fkey",
    "orders_trade_group_leg_id_fkey",
    "rule_runs_trade_group_id_fkey",
)
_TEMPLATE = "trade_groups_head_template"
_NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
#: A request body's fingerprint as the service stores it: lower-case hex, 64 digits.
_BODY = hashlib.sha256(b'{"symbol":"BTCUSDT","side":"Buy","qty":"0.010"}').hexdigest()
_OTHER_BODY = hashlib.sha256(b'{"symbol":"BTCUSDT","side":"Sell","qty":"0.010"}').hexdigest()
_NAN = Decimal("NaN")

Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#905)
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
    """Head, plus an untouched copy of it that `_fresh` clones for tests needing their own
    database; the matrix tests write uniquely keyed rows to the head database itself."""
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
    name = f"tg_{uuid.uuid4().hex[:12]}"
    with _conn(_database(dsn, "postgres")) as c:
        c.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name), sql.Identifier(_TEMPLATE)
            )
        )
    return _database(dsn, name)


def _insert(c: Conn, table: str, row: dict[str, object], key: str = "id") -> str:
    stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING {}::text").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(k) for k in row),
        sql.SQL(", ").join([sql.Placeholder()] * len(row)),
        sql.Identifier(key),
    )
    got = c.execute(stmt, tuple(row.values())).fetchone()
    assert got is not None
    return str(got[0])


def _user(c: Conn) -> str:
    uid = uuid.uuid4()
    c.execute(
        "INSERT INTO users (id, email, username, password_hash, status) "
        "VALUES (%s, %s, %s, '$argon2id$x', 'active')",
        (str(uid), f"{uid}@example.test", f"u{uid.hex[:12]}"),
    )
    return str(uid)


def _account(c: Conn, env: str = "demo") -> str:
    """An account; `trg_ea_default_profile` gives it its bootstrap profile, version 1."""
    uid = str(uuid.uuid4().int % 10**15)
    row: dict[str, object] = {"id": str(uuid.uuid4()), "exchange": "bybit", "env": env}
    row |= {"kind": "main", "exchange_uid": uid, "label": f"acct {uid}"}
    return _insert(c, "exchange_accounts", row)


def _profile(c: Conn, account: str, **cols: object) -> str:
    row: dict[str, object] = {"id": str(uuid.uuid4()), "exchange_account_id": account}
    row |= {"name": f"p {uuid.uuid4().hex[:8]}", "risk_pct_equity": Decimal("1")}
    return _insert(c, "account_profiles", row | cols)


def _one(c: Conn, query: str, *args: object) -> Any:
    row = c.execute(query, args).fetchone()
    assert row is not None
    return row[0]


def _count(c: Conn, table: str) -> int:
    return int(_one(c, f"SELECT count(*) FROM {table}"))  # noqa: S608 -- literal table names only


def _default_of(c: Conn, account: str) -> str:
    return str(
        _one(
            c,
            "SELECT id::text FROM account_profiles WHERE exchange_account_id = %s "
            "AND is_default AND deleted_at IS NULL",
            account,
        )
    )


def _definition(c: Conn, **cols: object) -> str:
    """A live demo definition with a unique name."""
    row: dict[str, object] = {"id": str(uuid.uuid4()), "name": f"def {uuid.uuid4().hex[:8]}"}
    return _insert(c, "trade_group_definitions", row | {"env": "demo"} | cols)


def _member(c: Conn, definition: str, account: str) -> str:
    row: dict[str, object] = {"definition_id": definition, "exchange_account_id": account}
    return _insert(c, "trade_group_definition_members", row, key="definition_id")


def _group(c: Conn, created_by: str, **cols: object) -> str:
    """A valid demo Market group; `client_group_ref` is a fresh lower-case UUID text."""
    row: dict[str, object] = {"id": str(uuid.uuid4()), "client_group_ref": str(uuid.uuid4())}
    row |= {"client_body_sha256": _BODY, "env": "demo", "symbol": "BTCUSDT", "side": "Buy"}
    return _insert(c, "trade_groups", row | {"created_by": created_by} | cols)


def _snapshot(profile: str | None, account: str, version: int = 1) -> dict[str, object]:
    """The least a frozen copy carries: the three keys `tgl_snapshot` ties to the leg's columns.
    `test_the_real_profile_projection_satisfies_the_snapshot_check` stores the real projection."""
    return {"profile_id": profile, "account_id": account, "version": version, "name": "Default"}


def _leg(c: Conn, group: str, account: str, **cols: object) -> str:
    """A valid pending leg with a resolved native stop, sized from the account's live default
    profile at version 1 (its bootstrap revision); a caller naming another profile brings its
    own snapshot."""
    row: dict[str, object] = {"id": str(uuid.uuid4()), "trade_group_id": group}
    row |= {"exchange_account_id": account, "profile_version": 1, "sequence_no": 0}
    row |= {"target_qty": Decimal("0.010"), "resolved_leverage": Decimal("5")}
    row |= {"resolved_sl_price": Decimal("62000")}
    if "account_profile_id" not in cols:
        profile = _default_of(c, account)
        row |= {"account_profile_id": profile}
        row |= {"profile_snapshot": Jsonb(_snapshot(profile, account))}
    return _insert(c, "trade_group_legs", row | cols)


def _attribution(c: Conn, leg: str) -> tuple[Any, ...]:
    """What a leg records of the profile it was sized from."""
    row = c.execute(
        "SELECT account_profile_id::text, profile_version, profile_snapshot "
        "FROM trade_group_legs WHERE id = %s",
        (leg,),
    ).fetchone()
    assert row is not None
    return row


def _legs_in(c: Conn, group: str) -> int:
    return int(_one(c, "SELECT count(*) FROM trade_group_legs WHERE trade_group_id = %s", group))


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


def _execution(c: Conn, account: str, **cols: object) -> str:
    row: dict[str, object] = {"id": str(uuid.uuid4()), "exchange_account_id": account}
    row |= {"exec_id": uuid.uuid4().hex, "symbol": "BTCUSDT", "side": "Buy"}
    row |= {"exec_qty": Decimal("0.010"), "exec_price": Decimal("63099.80")}
    row |= {"exec_value": Decimal("630.998"), "exec_type": "Trade", "is_maker": False}
    return _insert(c, "executions", row | {"exec_ts": _NOW} | cols)


_ROW: dict[str, Callable[..., str]] = {"orders": _order, "executions": _execution}

# --- The catalog equals the plan doc, and the round trip leaves nothing behind ----------------

_TABLE_CATALOG = (
    "SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, "
    "pg_get_expr(d.adbin, d.adrelid) FROM pg_attribute a LEFT JOIN pg_attrdef d "
    "ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
    "WHERE a.attrelid = %(t)s::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum",
    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
    "WHERE conrelid = %(t)s::regclass ORDER BY conname",
    "SELECT i.relname, pg_get_indexdef(i.oid) FROM pg_index x "
    "JOIN pg_class i ON i.oid = x.indexrelid WHERE x.indrelid = %(t)s::regclass ORDER BY 1",
    "SELECT tgname, tgenabled::text, pg_get_triggerdef(oid) FROM pg_trigger "
    "WHERE tgrelid = %(t)s::regclass AND NOT tgisinternal ORDER BY tgname",
)
_ENUM_CATALOG = (
    "SELECT enumlabel FROM pg_enum WHERE enumtypid = %(t)s::regtype ORDER BY enumsortorder"
)
_FUNCTION_CATALOG = "SELECT pg_get_functiondef(%(t)s::regprocedure)"
_GUARD = (
    "CREATE TRIGGER trg_ea_env_in_use BEFORE UPDATE OF env ON public.exchange_accounts "
    "FOR EACH ROW EXECUTE FUNCTION ea_env_in_use_check()"
)


def _doc_section(heading: str) -> str:
    section = _DOC.read_text(encoding="utf-8").split(heading, 1)[1]
    return re.split(r"\n#{1,4} ", section, maxsplit=1)[0]


def _doc_blocks(heading: str) -> list[str]:
    return [b.split("```", 1)[0] for b in _doc_section(f"#### {heading}").split("```sql")[1:]]


def _doc_enums() -> str:
    """Sec.1.2's three trade-group enums, line for line."""
    fence = _doc_section("### 1.2 Enum types").split("```sql", 1)[1].split("```", 1)[0]
    names = "|".join(_ENUMS)
    lines = [m[0] for m in re.finditer(rf"^CREATE TYPE ({names}) .*$", fence, re.MULTILINE)]
    assert len(lines) == len(_ENUMS)
    return "\n".join(lines)


def _doc_ddl() -> tuple[str, str]:
    """The enums, then the six fences in dependency order (definitions first, as `trade_groups`
    references them) and Sec.3.3.2's third, which replaces `tg_write_once()`; and apart, the account
    guard, whose trigger sits on `exchange_accounts`, outside the scratch schema."""
    groups, group_triggers, frozen = _doc_blocks("3.3.2 `trade_groups`")
    legs, leg_triggers = _doc_blocks("3.3.3 `trade_group_legs`")
    definitions, guards = _doc_blocks(
        "3.3.3a `trade_group_definitions` and `trade_group_definition_members`"
    )
    own_guards, account_guard = guards.split("CREATE FUNCTION ea_env_in_use_check()", 1)
    blocks = [_doc_enums(), definitions, groups, legs, group_triggers, leg_triggers, own_guards]
    blocks.append(frozen)  # Sec.3.3.2's third block, `0053_tg_frozen_after_draft`'s: head holds it
    return "\n".join(blocks), "CREATE FUNCTION ea_env_in_use_check()" + account_guard


def _catalog(c: Conn, schema: str) -> list[list[tuple[str, ...]]]:
    unqualify = re.compile(r"\b(?:public|doc_ref)\.")

    def rows(query: str, name: str) -> list[tuple[str, ...]]:
        found = c.execute(query, {"t": f"{schema}.{name}"})
        return [tuple(unqualify.sub("", str(v)) for v in row) for row in found]

    return [
        *(rows(query, table) for table in _TABLES for query in _TABLE_CATALOG),
        *(rows(_ENUM_CATALOG, kind) for kind in _ENUMS),
        *(rows(_FUNCTION_CATALOG, f"{function}()") for function in _FUNCTIONS),
    ]


def _account_guard(c: Conn) -> list[tuple[Any, ...]]:
    return c.execute(
        "SELECT tgenabled::text, pg_get_triggerdef(oid) FROM pg_trigger "
        "WHERE tgrelid = 'public.exchange_accounts'::regclass AND tgname = 'trg_ea_env_in_use'"
    ).fetchall()


def _assert_matches_plan_doc(c: Conn) -> None:
    """Build the doc's DDL in a scratch schema (rolled back) and diff the two catalogs, function
    bodies included. The account guard is diffed by swapping the live trigger for the doc's on
    `exchange_accounts`, inside the same rollback."""
    tables, account_guard = _doc_ddl()
    got: list[list[tuple[str, ...]]] = []
    want: list[list[tuple[str, ...]]] = []
    guards: list[list[tuple[Any, ...]]] = []
    with c.transaction():
        c.execute("CREATE SCHEMA doc_ref")
        c.execute("SET LOCAL search_path = doc_ref, public")
        c.execute(tables.encode())
        guards.append(_account_guard(c))
        c.execute("DROP TRIGGER trg_ea_env_in_use ON public.exchange_accounts")
        c.execute(account_guard.encode())
        guards.append(_account_guard(c))
        got, want = _catalog(c, "public"), _catalog(c, "doc_ref")
        raise psycopg.Rollback
    assert got == want and all(got)
    assert guards == [[("A", _GUARD)], [("A", _GUARD)]]


def test_schema_matches_the_plan_doc(pg_dsn: str) -> None:
    """The four tables (columns, constraints, indexes, triggers with `tgenabled`), the three
    enums and the eight trigger functions equal the doc's DDL. Each function pins its
    `search_path` and runs as its caller, and the P1 columns carry their `PII:` comments (C-5.9)."""
    with _conn(pg_dsn) as c:
        _assert_matches_plan_doc(c)
        pinned = c.execute(
            "SELECT proname, proconfig, prosecdef FROM pg_proc WHERE proname = ANY(%s) "
            "ORDER BY proname",
            (list(_FUNCTIONS),),
        ).fetchall()
        assert [p[0] for p in pinned] == sorted(_FUNCTIONS)
        assert [p[1] for p in pinned] == [["search_path=pg_catalog, pg_temp"]] * len(_FUNCTIONS)
        assert not any(p[2] for p in pinned)  # no trigger function is SECURITY DEFINER
        tagged = c.execute(
            "SELECT attrelid::regclass::text, d, count(*) FROM ("
            "SELECT attrelid, col_description(attrelid, attnum) AS d FROM pg_attribute "
            "WHERE attrelid = ANY(%s::regclass[]) AND attnum > 0) s "
            "WHERE d IS NOT NULL GROUP BY 1, 2",
            (list(_TABLES),),
        ).fetchall()
        money = "PII: financial personal data (21 Sec.12, class P1); never sent to third parties"
        text = (
            "PII: exchange answer text that can repeat order values (21 Sec.12, class P1); "
            "redacted before insert; never logged"
        )
        note = "PII: free text a user wrote (21 Sec.12, class P1); never logged"
        algo = (
            "PII: algo parameters that can repeat order prices and quantities (21 Sec.12, class "
            "P1); never logged"
        )
        assert {(row[0], row[1]): row[2] for row in tagged} == {
            ("trade_groups", money): 5, ("trade_groups", note): 1, ("trade_groups", algo): 1,
            ("trade_group_legs", money): 9, ("trade_group_legs", text): 2,
        }  # fmt: skip


def _assert_no_residue(c: Conn) -> None:
    for table in _TABLES:
        assert c.execute("SELECT to_regclass(%s)", (table,)).fetchone() == (None,)
    for kind in _ENUMS:
        assert c.execute("SELECT to_regtype(%s)", (kind,)).fetchone() == (None,)
    assert not c.execute(
        "SELECT 1 FROM pg_proc WHERE proname = ANY(%s)", (list(_FUNCTIONS),)
    ).fetchall()
    assert not c.execute("SELECT 1 FROM pg_trigger WHERE tgname = 'trg_ea_env_in_use'").fetchall()
    assert not c.execute(
        "SELECT 1 FROM pg_constraint WHERE conname = ANY(%s)", (list(_LEG_FKS),)
    ).fetchall()


@pytest.mark.parametrize("seeded", [False, True], ids=["empty", "seeded"])
def test_round_trip_leaves_no_residue_and_restores_the_schema(pg_dsn: str, seeded: bool) -> None:
    """C-5.5: head -> 0038 -> head on an empty and on a seeded database (accounts with their
    bootstrap profiles, and orders naming no leg). The downgrade drops the four tables, the three
    enums, the eight functions, the account guard and the three FKs and keeps every other row; the
    upgrade restores the plan doc's schema, and its FKs attach to the rows that stayed."""
    dsn = _fresh(pg_dsn)
    with _conn(dsn) as c:
        accounts = [_account(c), _account(c)] if seeded else []
        orders = [_order(c, account) for account in accounts]
    downgraded = _alembic(dsn, "downgrade", _PREV)
    assert downgraded.returncode == 0, downgraded.stderr
    with _conn(dsn) as c:
        _assert_no_residue(c)
        assert _count(c, "exchange_accounts") == _count(c, "account_profiles") == len(accounts)
        assert _count(c, "orders") == len(orders)
        assert _one(c, "SELECT count(trade_group_leg_id) FROM orders") == 0
    upgraded = _alembic(dsn, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    with _conn(dsn) as c:
        _assert_matches_plan_doc(c)
        validated = c.execute(
            "SELECT conname FROM pg_constraint WHERE conname = ANY(%s) AND convalidated "
            "ORDER BY conname",
            (list(_LEG_FKS),),
        ).fetchall()
        assert [row[0] for row in validated] == list(_LEG_FKS)
        for account, order in zip(accounts, orders, strict=True):
            leg = _leg(c, _group(c, _user(c)), account)
            c.execute("UPDATE orders SET trade_group_leg_id = %s WHERE id = %s", (leg, order))
        assert _one(c, "SELECT count(trade_group_leg_id) FROM orders") == len(orders)


_HELD: dict[str, Callable[[Conn], object]] = {
    "definition": lambda c: _definition(c),
    "definition-with-member": lambda c: _member(c, _definition(c), _account(c)),
    "group": lambda c: _group(c, _user(c)),
    "group-with-leg": lambda c: _leg(c, _group(c, _user(c)), _account(c)),
}


@pytest.mark.parametrize("held", list(_HELD))
def test_downgrade_refuses_while_a_group_definition_or_member_exists(
    pg_dsn: str, held: str
) -> None:
    """Groups and legs are trading history and definitions configuration: dropping them would
    lose both, so the downgrade refuses while any row exists (C-5.2), and a refused downgrade
    changes nothing."""
    dsn = _fresh(pg_dsn)
    with _conn(dsn) as c:
        _HELD[held](c)
        head = c.execute("SELECT version_num FROM alembic_version").fetchone()  # not always 0039
        before = [_count(c, table) for table in _TABLES]
        refused = _alembic(dsn, "downgrade", _PREV)
        assert refused.returncode != 0
        assert (
            f"{_REV} downgrade refused: trade groups or group definitions exist"
        ) in refused.stderr
        assert c.execute("SELECT version_num FROM alembic_version").fetchone() == head
        assert [_count(c, table) for table in _TABLES] == before


# --- Every invalid row is refused by its NAMED constraint ---------------------------------------
# Postgres runs a row's CHECKs in the order of their names (after NOT NULL), so each value below is
# one whose first failing CHECK is the named one, starting from a valid row.

_INVALID_GROUP: dict[str, tuple[str, dict[str, object]]] = {
    "tg_side": ("tg_side", {"side": "Long"}),
    "tg_policy": ("tg_policy", {"leg_failure_policy": "compensate"}),
    "tg_origin": ("tg_origin", {"origin": "api"}),
    "tg_entrytype": ("tg_entrytype", {"entry_type": "Stop"}),
    "tg_limit_px-zero": ("tg_limit_px", {"entry_type": "Limit", "entry_price": Decimal("0")}),
    "tg_limit_px-null": ("tg_limit_px", {"entry_type": "Limit"}),
    "tg_cond_px-null-price": (
        "tg_cond_px",
        {"entry_type": "Conditional", "trigger_by": "LastPrice"},
    ),
    "tg_cond_px-zero-price": (
        "tg_cond_px",
        {"entry_type": "Conditional", "trigger_price": Decimal("0"), "trigger_by": "MarkPrice"},
    ),
    "tg_cond_px-no-trigger-by": (
        "tg_cond_px",
        {"entry_type": "Conditional", "trigger_price": Decimal("63000")},
    ),
    "tg_trigby": ("tg_trigby", {"trigger_by": "LTP"}),
    "tg_times": ("tg_times", {"opened_at": _NOW, "closed_at": _NOW - timedelta(seconds=1)}),
    "tg_ref_fmt": ("tg_ref_fmt", {"client_group_ref": "not-a-uuid"}),
    "tg_finite": ("tg_finite", {"entry_type": "Limit", "entry_price": _NAN}),
}


@pytest.mark.parametrize(
    ("constraint", "bad"), list(_INVALID_GROUP.values()), ids=list(_INVALID_GROUP)
)
def test_invalid_group_is_refused_by_its_named_constraint(
    pg_dsn: str, constraint: str, bad: dict[str, object]
) -> None:
    """The group's constraint matrix; NULL prices are refused too (`tg_limit_px` and
    `tg_cond_px` are `IS TRUE`), and a NaN price, which `NaN > 0` would admit, by `tg_finite`."""
    with _conn(pg_dsn) as c:
        user = _user(c)
        assert _group(c, user)  # the base row is valid
        with pytest.raises(pgerr.CheckViolation) as exc:
            _group(c, user, **bad)
        assert exc.value.diag.constraint_name == constraint
        assert _one(c, "SELECT count(*) FROM trade_groups WHERE created_by = %s", user) == 1


#: The columns a leg changes, given its account and that account's default profile.
_Bad = Callable[[str, str], dict[str, object]]
#: No account's or profile's id.
_ELSEWHERE = str(uuid.UUID(int=1))


def _cols(**cols: object) -> _Bad:
    return lambda account, profile: cols


def _snapshot_with(**changes: object) -> _Bad:
    return lambda account, profile: {
        "profile_snapshot": Jsonb(_snapshot(profile, account) | changes)
    }


_INVALID_LEG: dict[str, tuple[str, _Bad]] = {
    "tgl_qty_pos": ("tgl_qty_pos", _cols(target_qty=Decimal("0"))),
    "tgl_filled_rng-over": ("tgl_filled_rng", _cols(filled_qty=Decimal("0.011"))),
    "tgl_filled_rng-negative": ("tgl_filled_rng", _cols(filled_qty=Decimal("-0.001"))),
    "tgl_seq": ("tgl_seq", _cols(sequence_no=101)),
    "tgl_lev": ("tgl_lev", _cols(resolved_leverage=Decimal("0.99"))),
    "tgl_sl_conf": ("tgl_sl_conf", _cols(native_sl_confirmed=True)),
    "tgl_fees_nonneg": ("tgl_fees_nonneg", _cols(fees_paid=Decimal("-0.01"))),
    "tgl_profile_version": (
        "tgl_profile_version",
        lambda account, profile: {
            "profile_version": 0,
            "profile_snapshot": Jsonb(_snapshot(profile, account, version=0)),
        },
    ),
    "tgl_snapshot-not-an-object": (
        "tgl_snapshot",
        lambda account, profile: {"profile_snapshot": Jsonb([profile, account, 1])},
    ),
    "tgl_snapshot-other-account": ("tgl_snapshot", _snapshot_with(account_id=_ELSEWHERE)),
    "tgl_snapshot-other-version": ("tgl_snapshot", _snapshot_with(version=2)),
    "tgl_snapshot-other-profile": ("tgl_snapshot", _snapshot_with(profile_id=_ELSEWHERE)),
    "tgl_sl_px-null": ("tgl_sl_px", _cols(resolved_sl_price=None)),
    "tgl_sl_px-zero": ("tgl_sl_px", _cols(resolved_sl_price=Decimal("0"))),
    "tgl_finite": ("tgl_finite", _cols(resolved_sl_price=_NAN)),
}


@pytest.mark.parametrize(("constraint", "bad"), list(_INVALID_LEG.values()), ids=list(_INVALID_LEG))
def test_invalid_leg_is_refused_by_its_named_constraint(
    pg_dsn: str, constraint: str, bad: _Bad
) -> None:
    """The leg's constraint matrix, from a valid leg of the same account and profile in another
    group: a pending leg without a positive stop is refused (`tgl_sl_px`, SR-E28-08), and its
    snapshot must name its account, its version and its profile (`tgl_snapshot`, SR-E28-07)."""
    with _conn(pg_dsn) as c:
        user, account = _user(c), _account(c)
        assert _leg(c, _group(c, user), account)  # the base row is valid
        with pytest.raises(pgerr.CheckViolation) as exc:
            _leg(c, _group(c, user), account, **bad(account, _default_of(c, account)))
        assert exc.value.diag.constraint_name == constraint
        assert (
            _one(c, "SELECT count(*) FROM trade_group_legs WHERE exchange_account_id = %s", account)
            == 1
        )


@pytest.mark.parametrize("name", ["", "x" * 81], ids=["empty", "81-chars"])
def test_invalid_definition_is_refused_by_its_named_constraint(pg_dsn: str, name: str) -> None:
    """`tgd_name`: a definition's name holds 1 to 80 characters."""
    with _conn(pg_dsn) as c:
        assert _definition(c)  # the base row is valid
        with pytest.raises(pgerr.CheckViolation) as exc:
            _definition(c, name=name)
        assert exc.value.diag.constraint_name == "tgd_name"


@pytest.mark.parametrize(
    "column",
    ["requested_qty_value", "entry_price", "trigger_price", "sl_price_hint", "tp_price_hint"],
)
def test_a_nan_in_a_group_is_refused(pg_dsn: str, column: str) -> None:
    """Postgres sorts NaN above every number, so a NaN passes any lower bound alone."""
    with _conn(pg_dsn) as c, pytest.raises(pgerr.CheckViolation) as exc:
        _group(c, _user(c), **{column: _NAN})
    assert exc.value.diag.constraint_name == "tg_finite"


_LEG_NUMBERS = (
    "target_qty",
    "avg_entry_price",
    "avg_exit_price",
    "resolved_leverage",
    "resolved_sl_price",
    "resolved_tp_price",
    "risk_usd",
    "realised_pnl",
    "fees_paid",
)


@pytest.mark.parametrize(
    ("column", "constraint"),
    # a NaN fill exceeds target_qty, and `tgl_filled_rng` runs before `tgl_finite`
    [*((column, "tgl_finite") for column in _LEG_NUMBERS), ("filled_qty", "tgl_filled_rng")],
)
def test_a_nan_in_a_leg_is_refused(pg_dsn: str, column: str, constraint: str) -> None:
    """A NaN stop would satisfy `tgl_sl_px` and a NaN fee `tgl_fees_nonneg`; neither is stored."""
    with _conn(pg_dsn) as c, pytest.raises(pgerr.CheckViolation) as exc:
        _leg(c, _group(c, _user(c)), _account(c), **{column: _NAN})
    assert exc.value.diag.constraint_name == constraint


@pytest.mark.parametrize(
    "bounds",
    [
        {"sequence_no": 0, "resolved_leverage": Decimal("1"), "filled_qty": Decimal("0")},
        {"sequence_no": 100, "resolved_leverage": Decimal("100"), "filled_qty": Decimal("0.010")},
    ],
    ids=["lower", "upper"],
)
def test_a_leg_at_its_bounds_is_stored(pg_dsn: str, bounds: dict[str, object]) -> None:
    """`tgl_seq`, `tgl_lev` and `tgl_filled_rng` include both of their ends."""
    with _conn(pg_dsn) as c:
        leg = _leg(c, _group(c, _user(c)), _account(c), **bounds)
        row = c.execute(
            "SELECT sequence_no, resolved_leverage, filled_qty FROM trade_group_legs WHERE id = %s",
            (leg,),
        ).fetchone()
        assert row == tuple(bounds.values())


def test_a_definition_name_is_unique_among_live_definitions(pg_dsn: str) -> None:
    """`ux_tgd_name` compares names case-insensitively, over live definitions only: a
    soft-deleted definition frees its name."""
    with _conn(_fresh(pg_dsn)) as c:
        scalp = _definition(c, name="Scalp")
        with pytest.raises(pgerr.UniqueViolation) as exc:
            _definition(c, name="SCALP")
        assert exc.value.diag.constraint_name == "ux_tgd_name"
        c.execute("UPDATE trade_group_definitions SET deleted_at = now() WHERE id = %s", (scalp,))
        assert _definition(c, name="scalp")


# --- G-6(b) / SR-E29-07: the replay anchor is per creator, one format, with its fingerprint ----


def test_another_users_ref_is_a_separate_group(pg_dsn: str) -> None:
    """Uniqueness is per creator, never across users: another user's key creates their own group
    (it reads as a missing one), so the anchor is no existence oracle and no IDOR."""
    ref = str(uuid.uuid4())
    with _conn(pg_dsn) as c:
        first, second = _user(c), _user(c)
        groups = {_group(c, first, client_group_ref=ref), _group(c, second, client_group_ref=ref)}
        rows = c.execute(
            "SELECT id::text, created_by::text FROM trade_groups WHERE client_group_ref = %s",
            (ref,),
        ).fetchall()
    assert len(groups) == len(rows) == 2
    assert {row[0] for row in rows} == groups
    assert {row[1] for row in rows} == {first, second}


@pytest.mark.parametrize("body", [_BODY, _OTHER_BODY], ids=["same-body", "other-body"])
def test_the_same_user_and_ref_twice_is_refused_by_ux_tg_creator_ref(
    pg_dsn: str, body: str
) -> None:
    """A re-sent ticket under the same key never creates a second group, whatever its body: the
    service answers it from the first group, or with a conflict when the fingerprint differs."""
    ref = str(uuid.uuid4())
    with _conn(pg_dsn) as c:
        user = _user(c)
        _group(c, user, client_group_ref=ref)
        with pytest.raises(pgerr.UniqueViolation) as exc:
            _group(c, user, client_group_ref=ref, client_body_sha256=body)
        assert exc.value.sqlstate == "23505"
        assert exc.value.diag.constraint_name == "ux_tg_creator_ref"
        assert _one(c, "SELECT count(*) FROM trade_groups WHERE created_by = %s", user) == 1


_HEX_UUID = "6f9619ff-8b86-d011-b42d-00c04fc964ff"


def _outcome(write: Callable[[], object]) -> str:
    """`stored`, or the name of the CHECK that refused the write."""
    try:
        write()
    except pgerr.CheckViolation as exc:
        return str(exc.diag.constraint_name)
    return "stored"


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("01ARZ3NDEKTSV4RRFFQ69G5FAV", "tg_ref_fmt"),
        ("cv-0c000000", "tg_ref_fmt"),
        (_HEX_UUID.upper(), "tg_ref_fmt"),
        ("{" + _HEX_UUID + "}", "tg_ref_fmt"),
        (_HEX_UUID.replace("-", ""), "tg_ref_fmt"),
        (_HEX_UUID + "\n", "tg_ref_fmt"),
        ("", "tg_ref_fmt"),
        ("0b5f6d0e-28a1-4c1e-9e01-00000000000a", "stored"),
        (str(uuid.uuid5(uuid.NAMESPACE_OID, "candleviewer.trade-group")), "stored"),
    ],
    ids=["ulid", "cv-prefixed", "upper-case", "braced", "hyphenless", "trailing-newline", "empty",
         "v4", "v5"],
)  # fmt: skip
def test_the_ref_takes_one_format(pg_dsn: str, ref: str, expected: str) -> None:
    """`tg_ref_fmt`: the canonical lower-case UUID text of any version (the service stores
    `str(UUID(header))`); every other spelling of a key is refused, so one key has one anchor."""
    with _conn(pg_dsn) as c:
        user = _user(c)
        assert _outcome(lambda: _group(c, user, client_group_ref=ref)) == expected


@pytest.mark.parametrize(
    ("body", "refusal", "sqlstate", "constraint"),
    [
        (_BODY[:63], pgerr.CheckViolation, "23514", "sha256_hex_check"),
        (_BODY.upper(), pgerr.CheckViolation, "23514", "sha256_hex_check"),
        (_BODY + "0", pgerr.StringDataRightTruncation, "22001", None),
        (None, pgerr.NotNullViolation, "23502", None),
    ],
    ids=["63-digits", "upper-case", "65-digits", "null"],
)
def test_the_fingerprint_is_lower_case_hex_of_64(
    pg_dsn: str,
    body: str | None,
    refusal: type[psycopg.Error],
    sqlstate: str,
    constraint: str | None,
) -> None:
    """`client_body_sha256` is the `sha256_hex` domain (`char(64)`, lower-case hex) and NOT NULL:
    a short or upper-case fingerprint fails the domain CHECK, a long one the type's length."""
    with _conn(pg_dsn) as c:
        user = _user(c)
        with pytest.raises(refusal) as exc:
            _group(c, user, client_body_sha256=body)
        assert exc.value.sqlstate == sqlstate
        assert exc.value.diag.constraint_name == constraint


def _wait_until_blocked(watcher: Conn, pid: int) -> None:
    """Poll until backend `pid` waits on a heavyweight lock: at most 3000 polls, 10 ms apart."""
    for _ in range(3000):
        waiting = watcher.execute(
            "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", (pid,)
        ).fetchone()
        if waiting == ("Lock",):
            return
        watcher.execute("SELECT pg_sleep(0.01)")
    pytest.fail("the second write never waited on the first")


def _race(
    dsn: str, first_write: Callable[[Conn], object], second_write: Callable[[Conn], object]
) -> list[psycopg.Error | None]:
    """`first_write` in an open transaction, then `second_write` on another connection, which
    must block on it; commit the first and return what the second raised, if anything."""
    outcome: list[psycopg.Error | None] = []
    with _conn(dsn) as first, _conn(dsn) as second, _conn(dsn) as watcher:
        first.autocommit = False
        first_write(first)
        blocked = second.info.backend_pid

        def contend() -> None:
            try:
                second_write(second)
                outcome.append(None)
            except psycopg.Error as exc:
                outcome.append(exc)

        worker = threading.Thread(target=contend)
        worker.start()
        _wait_until_blocked(watcher, blocked)
        first.commit()
        worker.join(timeout=30)
    return outcome


def test_two_concurrent_inserts_of_one_ref_admit_exactly_one(pg_dsn: str) -> None:
    """The second insert waits on the first's uncommitted `ux_tg_creator_ref` entry, then fails
    when it commits: a ticket re-sent while its first send is in flight creates one group."""
    dsn = _fresh(pg_dsn)
    ref = str(uuid.uuid4())
    with _conn(dsn) as c:
        user = _user(c)
    outcome = _race(
        dsn,
        lambda c: _group(c, user, client_group_ref=ref),
        lambda c: _group(c, user, client_group_ref=ref),
    )
    assert len(outcome) == 1, outcome
    refused = outcome[0]
    assert isinstance(refused, pgerr.UniqueViolation)
    assert refused.diag.constraint_name == "ux_tg_creator_ref"
    with _conn(dsn) as c:
        assert _one(c, "SELECT count(*) FROM trade_groups WHERE client_group_ref = %s", ref) == 1


# --- SR-E28-16: a group, its legs, a definition and its members share one environment ---------

_ENV_CHANGE = "UPDATE exchange_accounts SET env = 'live' WHERE id = %s"


def _env_of(c: Conn, account: str) -> str:
    return str(_one(c, "SELECT env::text FROM exchange_accounts WHERE id = %s", account))


def _without_the_write_once_guard(dsn: str) -> None:
    """In this test's own database only, as the superuser: switch off 0041's blanket
    `trg_ea_env_write_once` (#2333), which refuses every change of `env`, so the scenario meets
    0039's narrower guards alone."""
    with _conn(dsn) as c:
        c.execute("ALTER TABLE exchange_accounts DISABLE TRIGGER trg_ea_env_write_once")


def test_leg_env_must_match_group_env(pg_dsn: str) -> None:
    """`trg_tgl_env`, by its name: a live account's leg in a demo group is refused, with a message
    that names no value; a demo account's leg is stored."""
    with _conn(_fresh(pg_dsn)) as c:
        group = _group(c, _user(c))
        live = _account(c, env="live")
        with pytest.raises(pgerr.CheckViolation) as exc:
            _leg(c, group, live)
        assert exc.value.diag.constraint_name == "trg_tgl_env"
        assert exc.value.diag.message_primary == (
            "trg_tgl_env: a leg account is outside its group environment"
        )
        assert _leg(c, group, _account(c))
        assert _legs_in(c, group) == 1


_MEMBER_WRITES: dict[str, Callable[[Conn, str, str, str], object]] = {
    "INSERT": lambda c, definition, demo, live: _member(c, definition, live),
    "UPDATE": lambda c, definition, demo, live: c.execute(
        "UPDATE trade_group_definition_members SET exchange_account_id = %s "
        "WHERE definition_id = %s AND exchange_account_id = %s",
        (live, definition, demo),
    ),
}


@pytest.mark.parametrize("verb", list(_MEMBER_WRITES))
def test_group_member_env_mismatch_refused_by_trigger(pg_dsn: str, verb: str) -> None:
    """`trg_tgdm_env`, by its name: a live account joins a demo definition neither by insert nor by
    moving a member row (a member's account is not write-once); a demo account joins it."""
    with _conn(_fresh(pg_dsn)) as c:
        definition, demo, live = _definition(c), _account(c), _account(c, env="live")
        _member(c, definition, demo)
        with pytest.raises(pgerr.CheckViolation) as exc:
            _MEMBER_WRITES[verb](c, definition, demo, live)
        assert exc.value.diag.constraint_name == "trg_tgdm_env"
        assert exc.value.diag.message_primary == (
            "trg_tgdm_env: a member account is outside its definition environment"
        )
        members = c.execute(
            "SELECT exchange_account_id::text FROM trade_group_definition_members "
            "WHERE definition_id = %s",
            (definition,),
        ).fetchall()
        assert members == [(demo,)]


def test_a_group_fired_from_a_definition_takes_its_environment(pg_dsn: str) -> None:
    """`trg_tg_env`: a live group fired from a demo definition is refused; a demo one is stored."""
    with _conn(_fresh(pg_dsn)) as c:
        user, definition = _user(c), _definition(c)
        with pytest.raises(pgerr.CheckViolation) as exc:
            _group(c, user, env="live", definition_id=definition)
        assert exc.value.diag.constraint_name == "trg_tg_env"
        assert _group(c, user, definition_id=definition)


_IN_USE: dict[str, Callable[[Conn, str], object]] = {
    "member": lambda c, account: _member(c, _definition(c), account),
    "leg": lambda c, account: _leg(c, _group(c, _user(c)), account),
    "rejected-leg-only": lambda c, account: _leg(
        c, _group(c, _user(c)), account, status="rejected", resolved_sl_price=None
    ),
}


@pytest.mark.parametrize("use", list(_IN_USE))
def test_an_account_in_use_keeps_its_environment(pg_dsn: str, use: str) -> None:
    """`trg_ea_env_in_use`: once an account is a member of a definition or has a leg, whatever
    the leg's status, its environment is fixed."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        _IN_USE[use](c, account)
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute(_ENV_CHANGE, (account,))
        assert exc.value.diag.constraint_name == "trg_ea_env_in_use"
        assert _env_of(c, account) == "demo"


def test_the_in_use_guard_lets_an_account_in_no_group_or_definition_move(pg_dsn: str) -> None:
    """`trg_ea_env_in_use` is the part E28-T01 owns, and it is narrow: it refuses only an account
    that is a member or has a leg. Since #2333 `trg_ea_env_write_once` (0041) refuses every
    account (`test_account_env_write_once_migration.py`); with it switched off, an account in no
    group and no definition passes this guard and moves."""
    dsn = _fresh(pg_dsn)
    _without_the_write_once_guard(dsn)  # isolates 0039's guard from 0041's blanket one
    with _conn(dsn) as c:
        account = _account(c)
        _leg(c, _group(c, _user(c)), _account(c))  # another account is in use
        c.execute(_ENV_CHANGE, (account,))
        assert _env_of(c, account) == "live"


def test_a_leg_insert_and_an_env_change_serialise(pg_dsn: str) -> None:
    """`trg_tgl_env` reads the account FOR SHARE, so an environment change waits for the open
    leg insert; once it commits, `trg_ea_env_in_use` sees the leg and refuses the change."""
    dsn = _fresh(pg_dsn)
    with _conn(dsn) as c:
        account = _account(c)
        group = _group(c, _user(c))
    outcome = _race(
        dsn,
        lambda c: _leg(c, group, account),
        lambda c: c.execute(_ENV_CHANGE, (account,)),
    )
    assert len(outcome) == 1, outcome
    refused = outcome[0]
    assert isinstance(refused, pgerr.CheckViolation)
    assert refused.diag.constraint_name == "trg_ea_env_in_use"
    with _conn(dsn) as c:
        assert _env_of(c, account) == "demo"
        assert _legs_in(c, group) == 1


def test_an_env_change_and_a_leg_insert_serialise(pg_dsn: str) -> None:
    """The other order, for `trg_tgl_env`: the leg insert waits on the open environment change,
    then reads the committed environment and refuses the leg. Since #2333
    `trg_ea_env_write_once` (0041) refuses the change itself, so it is switched off here: the
    lock and the re-read are 0039's own defence and stay tested."""
    dsn = _fresh(pg_dsn)
    _without_the_write_once_guard(dsn)  # isolates 0039's guards from 0041's blanket one
    with _conn(dsn) as c:
        account = _account(c)
        group = _group(c, _user(c))
    outcome = _race(
        dsn,
        lambda c: c.execute(_ENV_CHANGE, (account,)),
        lambda c: _leg(c, group, account),
    )
    assert len(outcome) == 1, outcome
    refused = outcome[0]
    assert isinstance(refused, pgerr.CheckViolation)
    assert refused.diag.constraint_name == "trg_tgl_env"
    with _conn(dsn) as c:
        assert _env_of(c, account) == "live"
        assert _legs_in(c, group) == 0


# --- SR-E28-07: a leg's attribution and a group's identity are write-once ----------------------


def test_revisions_and_snapshots_are_write_once(pg_dsn: str) -> None:
    """Both halves: a leg's `profile_snapshot` and `profile_version` never change
    (`trg_tgl_write_once`, naming the column and no value), and the revision the leg names is
    INSERT-only (`forbid_mutation`)."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        profile = _default_of(c, account)
        leg = _leg(c, _group(c, _user(c)), account)
        written = _attribution(c, leg)
        edits: dict[str, object] = {
            "profile_snapshot": Jsonb(_snapshot(profile, account) | {"name": "Edited"}),
            "profile_version": 2,
        }
        for column, value in edits.items():
            with pytest.raises(pgerr.CheckViolation) as exc:
                c.execute(
                    sql.SQL("UPDATE trade_group_legs SET {} = %s WHERE id = %s").format(
                        sql.Identifier(column)
                    ),
                    (value, leg),
                )
            assert exc.value.diag.constraint_name == "trg_tgl_write_once"
            assert exc.value.diag.message_primary == (
                f"trg_tgl_write_once: trade_group_legs.{column} is write-once"
            )
        with pytest.raises(
            pgerr.RaiseException, match="table account_profile_revisions is append-only"
        ):
            c.execute(
                "UPDATE account_profile_revisions SET payload = '{}'::jsonb "
                "WHERE profile_id = %s AND version = 1",
                (profile,),
            )
        assert _attribution(c, leg) == written


def test_leg_snapshot_survives_a_profile_edit(pg_dsn: str) -> None:
    """Scenario "Leg snapshot survives a profile edit" (#905), from the bootstrap profile: a leg
    created from version 1 still records version 1 and the snapshot as written after the profile
    is edited to version 2, and the version-1 revision it names still holds version 1's values."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        profile = _default_of(c, account)
        leg = _leg(c, _group(c, _user(c)), account)
        c.execute("UPDATE account_profiles SET leverage = 3 WHERE id = %s", (profile,))
        assert _one(c, "SELECT version FROM account_profiles WHERE id = %s", profile) == 2
        assert _attribution(c, leg) == (profile, 1, _snapshot(profile, account))
        named = _one(
            c,
            "SELECT payload FROM account_profile_revisions WHERE profile_id = %s AND version = 1",
            profile,
        )
        assert Decimal(str(named["leverage"])) == 1


_REWRITES: dict[str, Callable[[Conn], object]] = {
    "id": lambda c: str(uuid.uuid4()),
    "env": lambda c: "live",
    "created_by": lambda c: _user(c),
    "client_group_ref": lambda c: str(uuid.uuid4()),
    "client_body_sha256": lambda c: _OTHER_BODY,
    "definition_id": lambda c: _definition(c),
    "leg_failure_policy": lambda c: "all_or_none",
}


@pytest.mark.parametrize("column", list(_REWRITES))
def test_the_group_identity_and_anchor_are_write_once(pg_dsn: str, column: str) -> None:
    """`trg_tg_write_once`: the group's identity, environment, author, replay anchor, the
    definition it was fired from and its failure policy never change once written."""
    with _conn(_fresh(pg_dsn)) as c:
        group = _group(c, _user(c))
        other = _REWRITES[column](c)
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute(
                sql.SQL("UPDATE trade_groups SET {} = %s WHERE id = %s").format(
                    sql.Identifier(column)
                ),
                (other, group),
            )
        assert exc.value.diag.constraint_name == "trg_tg_write_once"
        assert exc.value.diag.message_primary == (
            f"trg_tg_write_once: trade_groups.{column} is write-once"
        )


@pytest.mark.parametrize("policy", LEG_FAILURE_POLICIES)
def test_a_group_stores_its_policy_and_defaults_to_best_effort(pg_dsn: str, policy: str) -> None:
    """24 Sec.9.5: the failure policy that the unwind and a restart read is on the row (21
    Sec.3.3.2); `best_effort`, the manual-ticket default, is the column's."""
    with _conn(_fresh(pg_dsn)) as c:
        user = _user(c)
        plain = _group(c, user)
        named = _group(c, user, leg_failure_policy=policy)
        stored = "SELECT leg_failure_policy FROM trade_groups WHERE id = %s"
        assert (_one(c, stored, plain), _one(c, stored, named)) == ("best_effort", policy)


def test_a_group_holds_one_leg_per_account_so_an_exit_is_never_a_leg(pg_dsn: str) -> None:
    """Groups are entry fan-outs: `ux_tgl_group_account` admits one leg per account, so a
    take-profit or an unwind for that account is a reduce-only order on the entry leg, never a
    second leg row: `tgl_sl_px` binds every leg that has not ended rejected, cancelled or error,
    and every leg is an entry (C-2.6)."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        group = _group(c, _user(c))
        _leg(c, group, account)
        with pytest.raises(pgerr.UniqueViolation) as exc:
            _leg(c, group, account, sequence_no=1)
        assert exc.value.diag.constraint_name == "ux_tgl_group_account"
        with pytest.raises(pgerr.CheckViolation) as stopless:
            _leg(c, _group(c, _user(c)), account, resolved_sl_price=None)
        assert stopless.value.diag.constraint_name == "tgl_sl_px"


#: Re-points that stay in the leg's environment, so only `trg_tgl_write_once` can refuse them.
_LEG_REWRITES: dict[str, Callable[[Conn, str], object]] = {
    "id": lambda c, user: str(uuid.uuid4()),
    "trade_group_id": lambda c, user: _group(c, user),
    "exchange_account_id": lambda c, user: _account(c),
}


@pytest.mark.parametrize("column", list(_LEG_REWRITES))
def test_a_leg_identity_group_and_account_are_write_once(pg_dsn: str, column: str) -> None:
    """`trg_tgl_write_once` on SR-E28-16's re-point path: a leg never changes its id, its group
    or its account, even to an existing group or account of its own (demo) environment."""
    with _conn(_fresh(pg_dsn)) as c:
        user = _user(c)
        leg = _leg(c, _group(c, user), _account(c))
        other = _LEG_REWRITES[column](c, user)
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute(
                sql.SQL("UPDATE trade_group_legs SET {} = %s WHERE id = %s").format(
                    sql.Identifier(column)
                ),
                (other, leg),
            )
        assert exc.value.diag.constraint_name == "trg_tgl_write_once"
        assert exc.value.diag.message_primary == (
            f"trg_tgl_write_once: trade_group_legs.{column} is write-once"
        )


@pytest.mark.parametrize("column", ["exchange_account_id", "trade_group_id"])
def test_a_leg_moved_out_of_its_environment_is_refused_by_the_environment_guard(
    pg_dsn: str, column: str
) -> None:
    """Both guards refuse a re-point into the other environment; `trg_tgl_env` sorts before
    `trg_tgl_write_once`, so it names the refusal (SR-E28-16)."""
    with _conn(_fresh(pg_dsn)) as c:
        user = _user(c)
        leg = _leg(c, _group(c, user), _account(c))
        if column == "exchange_account_id":
            live = _account(c, "live")
        else:
            live = _group(c, user, env="live")
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute(
                sql.SQL("UPDATE trade_group_legs SET {} = %s WHERE id = %s").format(
                    sql.Identifier(column)
                ),
                (live, leg),
            )
        assert exc.value.diag.constraint_name == "trg_tgl_env"


def test_a_definition_identity_is_write_once(pg_dsn: str) -> None:
    """`trg_tgd_write_once`'s other arm: a definition's id never changes."""
    with _conn(_fresh(pg_dsn)) as c:
        definition = _definition(c)
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute(
                "UPDATE trade_group_definitions SET id = %s WHERE id = %s",
                (str(uuid.uuid4()), definition),
            )
        assert exc.value.diag.constraint_name == "trg_tgd_write_once"
        assert exc.value.diag.message_primary == (
            "trg_tgd_write_once: trade_group_definitions.id is write-once"
        )


def test_a_definition_environment_is_write_once(pg_dsn: str) -> None:
    """`trg_tgd_write_once`: a definition stays in its environment; its name and its soft delete
    remain writable."""
    with _conn(_fresh(pg_dsn)) as c:
        definition = _definition(c)
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute(
                "UPDATE trade_group_definitions SET env = 'live' WHERE id = %s", (definition,)
            )
        assert exc.value.diag.constraint_name == "trg_tgd_write_once"
        c.execute(
            "UPDATE trade_group_definitions SET name = 'Renamed', deleted_at = now() WHERE id = %s",
            (definition,),
        )
        assert (
            _one(c, "SELECT env::text FROM trade_group_definitions WHERE id = %s", definition)
            == "demo"
        )


def test_a_profile_delete_detaches_the_leg_and_keeps_its_snapshot(pg_dsn: str) -> None:
    """E28-X01 Q3: a hard profile delete (a superuser's; `cv_app` holds no DELETE) sets the leg's
    `account_profile_id` to NULL through the FK, which `trg_tgl_write_once` admits once the profile
    row is gone; the version and the snapshot stay."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        profile = _default_of(c, account)
        leg = _leg(c, _group(c, _user(c)), account)
        c.execute("DELETE FROM account_profiles WHERE id = %s", (profile,))
        assert _attribution(c, leg) == (None, 1, _snapshot(profile, account))


_REPOINTS: dict[str, Callable[[Conn, str], str | None]] = {
    "another-profile": lambda c, account: _profile(c, account),
    "detached-early": lambda c, account: None,
}


@pytest.mark.parametrize("rewrite", list(_REPOINTS))
def test_a_leg_keeps_its_profile_until_the_profile_is_gone(pg_dsn: str, rewrite: str) -> None:
    """`account_profile_id` only becomes NULL, and only once its profile row is gone: pointing a
    leg at another profile of its account, or detaching it while its profile exists, is refused."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        leg = _leg(c, _group(c, _user(c)), account)
        written = _attribution(c, leg)
        other = _REPOINTS[rewrite](c, account)
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute(
                "UPDATE trade_group_legs SET account_profile_id = %s WHERE id = %s", (other, leg)
            )
        assert exc.value.diag.constraint_name == "trg_tgl_write_once"
        assert _attribution(c, leg) == written


def _soft_deleted_default(c: Conn, account: str) -> str:
    profile = _default_of(c, account)
    c.execute("UPDATE account_profiles SET deleted_at = now() WHERE id = %s", (profile,))
    return profile


_FOREIGN_PROFILES: dict[str, Callable[[Conn, str], str | None]] = {
    "another-accounts": lambda c, account: _default_of(c, _account(c)),
    "soft-deleted": _soft_deleted_default,
    "none": lambda c, account: None,
}


@pytest.mark.parametrize("source", list(_FOREIGN_PROFILES))
def test_a_leg_is_sized_from_a_live_profile_of_its_own_account(pg_dsn: str, source: str) -> None:
    """`trg_tgl_profile`: a leg is sized from a live profile of its own account, never from
    another account's, a soft-deleted one, or none (its snapshot would name it)."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        group = _group(c, _user(c))
        chosen = _FOREIGN_PROFILES[source](c, account)
        snapshot = Jsonb(_snapshot(chosen, account))
        with pytest.raises(pgerr.CheckViolation) as exc:
            _leg(c, group, account, account_profile_id=chosen, profile_snapshot=snapshot)
        assert exc.value.diag.constraint_name == "trg_tgl_profile"


def test_a_leg_version_must_be_a_recorded_revision(pg_dsn: str) -> None:
    """`tgl_profile_revision`: (profile, version) names a revision, so a leg cannot claim a
    version its profile never had (the bootstrap profile has only version 1)."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        profile = _default_of(c, account)
        with pytest.raises(pgerr.ForeignKeyViolation) as exc:
            _leg(
                c,
                _group(c, _user(c)),
                account,
                account_profile_id=profile,
                profile_version=2,
                profile_snapshot=Jsonb(_snapshot(profile, account, version=2)),
            )
        assert exc.value.sqlstate == "23503"
        assert exc.value.diag.constraint_name == "tgl_profile_revision"


def test_the_real_profile_projection_satisfies_the_snapshot_check(pg_dsn: str) -> None:
    """The snapshot is the 24 Sec.9.2 `AccountProfile` projection (SR-E28-07): its
    `model_dump(mode="json")` carries `profile_id`, `account_id` and `version` as `tgl_snapshot`
    reads them, and is stored as written."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        profile = _default_of(c, account)
        data = json.loads((_FIXTURES / "risk_based.json").read_text(encoding="utf-8"))
        data |= {"profile_id": profile, "account_id": account, "version": 1}
        projection = AccountProfile.model_validate(data).model_dump(mode="json")
        leg = _leg(
            c,
            _group(c, _user(c)),
            account,
            account_profile_id=profile,
            profile_snapshot=Jsonb(projection),
        )
        assert _attribution(c, leg) == (profile, 1, projection)


# --- The leg FKs 0013 and 0029 deferred to this revision ---------------------------------------


def test_the_leg_foreign_keys_are_validated_and_set_null(pg_dsn: str) -> None:
    """Added NOT VALID, then validated (C-5.6), `ON DELETE SET NULL`, under the names Postgres
    gives the doc's inline REFERENCES; an order or an execution naming no leg is refused by name."""
    with _conn(_fresh(pg_dsn)) as c:
        found = c.execute(
            "SELECT conname, convalidated, confdeltype::text, confrelid::regclass::text "
            "FROM pg_constraint WHERE conname = ANY(%s) ORDER BY conname",
            (list(_LEG_FKS),),
        ).fetchall()
        assert found == [
            ("executions_trade_group_leg_id_fkey", True, "n", "trade_group_legs"),
            ("orders_trade_group_leg_id_fkey", True, "n", "trade_group_legs"),
            ("rule_runs_trade_group_id_fkey", True, "n", "trade_groups"),
        ]
        account = _account(c)
        for table in ("orders", "executions"):
            with pytest.raises(pgerr.ForeignKeyViolation) as exc:
                _ROW[table](c, account, trade_group_leg_id=str(uuid.uuid4()))
            assert exc.value.diag.constraint_name == f"{table}_trade_group_leg_id_fkey"


@pytest.mark.parametrize("target", ["trade_group_legs", "trade_groups"], ids=["leg", "group"])
def test_a_leg_with_executions_is_never_deleted(pg_dsn: str, target: str) -> None:
    """`ON DELETE SET NULL` toward `executions` is an UPDATE of an append-only row, which
    `trg_exec_append` refuses: once an execution names a leg, neither the leg nor, through the
    CASCADE, its group can be deleted, even by a superuser (Sec.3.3.3a implementation note)."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        group = _group(c, _user(c))
        leg = _leg(c, group, account)
        order = _order(c, account, trade_group_leg_id=leg)
        _execution(c, account, order_id=order, trade_group_leg_id=leg)
        with pytest.raises(pgerr.RaiseException, match="table executions is append-only"):
            c.execute(
                sql.SQL("DELETE FROM {} WHERE id = %s").format(sql.Identifier(target)),
                ({"trade_group_legs": leg, "trade_groups": group}[target],),
            )
        assert _one(c, "SELECT trade_group_leg_id::text FROM executions") == leg
        assert _one(c, "SELECT trade_group_leg_id::text FROM orders WHERE id = %s", order) == leg


def test_a_leg_without_executions_detaches_its_orders_on_delete(pg_dsn: str) -> None:
    """Deleting a leg no execution names (a superuser's; `cv_app` holds no DELETE) keeps its
    orders and sets their `trade_group_leg_id` to NULL."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        leg = _leg(c, _group(c, _user(c)), account)
        order = _order(c, account, trade_group_leg_id=leg)
        c.execute("DELETE FROM trade_group_legs WHERE id = %s", (leg,))
        assert _one(c, "SELECT trade_group_leg_id FROM orders WHERE id = %s", order) is None


@pytest.mark.parametrize("table", ["orders", "executions"])
def test_the_upgrade_refuses_a_dangling_leg_id(pg_dsn: str, table: str) -> None:
    """No row can name a leg before `trade_group_legs` exists: the pre-flight refuses one with a
    message saying what to clear, rather than letting VALIDATE CONSTRAINT fail, and the refused
    upgrade changes nothing."""
    dsn = _fresh(pg_dsn)
    downgraded = _alembic(dsn, "downgrade", _PREV)
    assert downgraded.returncode == 0, downgraded.stderr
    with _conn(dsn) as c:
        _ROW[table](c, _account(c), trade_group_leg_id=str(uuid.uuid4()))
    refused = _alembic(dsn, "upgrade", "head")
    assert refused.returncode != 0
    assert f"{_REV} upgrade refused: an order, execution or rule run names" in refused.stderr
    with _conn(dsn) as c:
        assert c.execute("SELECT version_num FROM alembic_version").fetchone() == (_PREV,)
        assert c.execute("SELECT to_regclass('trade_group_legs')").fetchone() == (None,)
        assert _count(c, table) == 1  # the dangling row is the operator's to clear


# --- C-2.6: the safety alarm covers every open position without a confirmed stop ---------------

_ALARM = (
    "SELECT id::text FROM trade_group_legs "
    "WHERE status IN ('open','partially_filled','filled') AND native_sl_confirmed = false"
)


def test_a_filled_leg_without_a_confirmed_stop_is_in_the_alarm_set(pg_dsn: str) -> None:
    """A filled leg is an open position, so it stays in the alarm set until its native stop is
    confirmed, and `ix_tgl_no_sl` (whose plan version missed `filled`) covers it."""
    with _conn(_fresh(pg_dsn)) as c:
        leg = _leg(c, _group(c, _user(c)), _account(c))
        c.execute(
            "UPDATE trade_group_legs SET status = 'filled', filled_qty = target_qty WHERE id = %s",
            (leg,),
        )
        assert c.execute(_ALARM).fetchall() == [(leg,)]
        c.execute(
            "UPDATE trade_group_legs SET native_sl_confirmed = true, "
            "native_sl_confirmed_at = now() WHERE id = %s",
            (leg,),
        )
        assert c.execute(_ALARM).fetchall() == []
        indexdef = _one(c, "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_tgl_no_sl'")
        assert "'filled'::leg_status" in indexdef
        assert "native_sl_confirmed = false" in indexdef


# --- The integrity triggers are ENABLE ALWAYS ---------------------------------------------------


def _world(c: Conn) -> dict[str, str]:
    """A demo definition with one member, a demo group fired from it with that member's leg, a
    spare demo account and a live one."""
    world = {"user": _user(c), "demo": _account(c), "spare": _account(c)}
    world |= {"live": _account(c, env="live"), "definition": _definition(c)}
    _member(c, world["definition"], world["demo"])
    world["group"] = _group(c, world["user"], definition_id=world["definition"])
    world["leg"] = _leg(c, world["group"], world["demo"])
    return world


_INTEGRITY: dict[str, Callable[[Conn, dict[str, str]], object]] = {
    "trg_tg_env": lambda c, w: _group(c, w["user"], env="live", definition_id=w["definition"]),
    "trg_tg_write_once": lambda c, w: c.execute(
        "UPDATE trade_groups SET env = 'live' WHERE id = %s", (w["group"],)
    ),
    "trg_tgl_env": lambda c, w: _leg(c, w["group"], w["live"]),
    "trg_tgl_profile": lambda c, w: _leg(
        c,
        w["group"],
        w["spare"],
        account_profile_id=None,
        profile_snapshot=Jsonb(_snapshot(None, w["spare"])),
    ),
    "trg_tgl_write_once": lambda c, w: c.execute(
        "UPDATE trade_group_legs SET profile_version = 2 WHERE id = %s", (w["leg"],)
    ),
    "trg_tgd_write_once": lambda c, w: c.execute(
        "UPDATE trade_group_definitions SET env = 'live' WHERE id = %s", (w["definition"],)
    ),
    "trg_tgdm_env": lambda c, w: _member(c, w["definition"], w["live"]),
    "trg_ea_env_in_use": lambda c, w: c.execute(_ENV_CHANGE, (w["demo"],)),
}


@pytest.mark.parametrize("trigger", list(_INTEGRITY))
def test_the_integrity_triggers_fire_under_the_replica_role(pg_dsn: str, trigger: str) -> None:
    """`session_replication_role = replica` switches off ordinary triggers and the FK checks;
    each integrity trigger is `ENABLE ALWAYS` and still refuses, under its own name."""
    with _conn(_fresh(pg_dsn)) as c:
        world = _world(c)
        with c.transaction():
            c.execute("SET LOCAL session_replication_role = replica")
            with pytest.raises(pgerr.CheckViolation) as exc:
                _INTEGRITY[trigger](c, world)
            assert exc.value.diag.constraint_name == trigger
            raise psycopg.Rollback


# --- C-5.7: groups and legs are history for the app role (the 0024 grant precedent) -----------


@pytest.fixture(scope="module")
def bootstrapped_dsn() -> Iterator[str]:
    """`pg_bootstrap.sql` first, then the migrations as `cv_owner`: the CI `migrations` order, so
    the default privileges apply and the revision's REVOKE meets real roles."""
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        info = psycopg.conninfo.conninfo_to_dict(dsn.replace("postgresql+asyncpg", "postgresql"))
        psql = shutil.which("psql")
        assert psql is not None, "the migrations CI job installs postgresql-client"
        bootstrap = subprocess.run(  # noqa: S603 -- resolved absolute path, fixed argv, no shell
            [psql, "-h", str(info["host"]), "-p", str(info["port"]), "-U", str(info["user"]),
             "-d", "candleviewer", "-v", "ON_ERROR_STOP=1", "-v", "owner_pw=cv_owner_test_pw",
             "-v", "app_pw=cv_app_test_pw", "-v", "ro_pw=cv_ro_test_pw",
             "-f", str(_ROOT.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql")],
            check=False, capture_output=True, text=True, timeout=120,
            env={**os.environ, "PGPASSWORD": str(info["password"])},
        )  # fmt: skip
        assert bootstrap.returncode == 0, bootstrap.stderr
        owner = re.sub(r"://[^@]+@", "://cv_owner:cv_owner_test_pw@", dsn)
        assert _alembic(owner, "upgrade", "head").returncode == 0
        yield dsn


def test_the_app_role_cannot_delete_groups_legs_or_definitions(bootstrapped_dsn: str) -> None:
    """A group and its legs are trading history and a definition leaves by soft delete, so
    `cv_app` holds no DELETE on them; a member is removed outright, so it keeps DELETE there."""
    with _conn(bootstrapped_dsn) as root:
        user = _user(root)
    app = re.sub(r"://[^@]+@", "://cv_app:cv_app_test_pw@", bootstrapped_dsn)
    with _conn(app) as c:
        account, definition = _account(c), _definition(c)
        _member(c, definition, account)
        group = _group(c, user, definition_id=definition)
        rows = {"trade_groups": group, "trade_group_legs": _leg(c, group, account)}
        rows |= {"trade_group_definitions": definition}
        for table, row in rows.items():
            with pytest.raises(pgerr.InsufficientPrivilege):
                c.execute(
                    sql.SQL("DELETE FROM {} WHERE id = %s").format(sql.Identifier(table)), (row,)
                )
        c.execute(
            "DELETE FROM trade_group_definition_members WHERE definition_id = %s", (definition,)
        )
        assert (
            _one(
                c,
                "SELECT count(*) FROM trade_group_definition_members WHERE definition_id = %s",
                definition,
            )
            == 0
        )
        assert _legs_in(c, group) == 1


def test_the_app_role_writes_a_group_with_its_legs(bootstrapped_dsn: str) -> None:
    """The runtime path as `cv_app`: a definition and its member, a group fired from it with a
    leg (the environment triggers read the account FOR SHARE, which takes `cv_app`'s UPDATE grant
    on `exchange_accounts`), then the leg's stop confirmed and both opened."""
    with _conn(bootstrapped_dsn) as root:
        user = _user(root)
    app = re.sub(r"://[^@]+@", "://cv_app:cv_app_test_pw@", bootstrapped_dsn)
    with _conn(app) as c:
        account, definition = _account(c), _definition(c)
        _member(c, definition, account)
        group = _group(c, user, definition_id=definition)
        leg = _leg(c, group, account)
        c.execute(
            "UPDATE trade_group_legs SET status = 'open', native_sl_confirmed = true, "
            "native_sl_confirmed_at = now() WHERE id = %s",
            (leg,),
        )
        c.execute(
            "UPDATE trade_groups SET status = 'open', opened_at = now() WHERE id = %s", (group,)
        )
        row = c.execute(
            "SELECT g.status::text, l.status::text, l.native_sl_confirmed FROM trade_groups g "
            "JOIN trade_group_legs l ON l.trade_group_id = g.id WHERE g.id = %s",
            (group,),
        ).fetchone()
        assert row == ("open", "open", True)
