"""Integration: `0037_account_profiles` against real Postgres 16 (E28-T01 #905).

The catalog equals 21-database-schema.md Sec.3.2.4 and Sec.3.2.5; every invalid row is refused by
its NAMED constraint; the #905 Gherkin scenarios that are pure database behaviour hold on the
engine (native SL, sizing shape, one default, the ladder limit, a soft delete freeing its name);
`version` is the database's, every write leaves a revision, the revisions are append-only even
under the replica role and for the app role; every account gets its bootstrap profile, new ones
by trigger and existing ones by the revision; an empty and a seeded database round-trip, and one
holding a written profile refuses. `0048_account_default_binding` (#906 0d) is here too: the
account's default binding version counts moves, in replica mode as well. `testcontainers` in CI.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import errors as pgerr
from psycopg import sql
from psycopg.types.json import Jsonb
from testcontainers.postgres import PostgresContainer

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0037_account_profiles", "0036_users_purge"
_TABLES = ("account_profiles", "account_profile_revisions")
_TEMPLATE = "profiles_head_template"
_CHECK_VIOLATION = "23514"

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
    """Head, plus an untouched copy of it that `_fresh` clones per test."""
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
    name = f"ap_{uuid.uuid4().hex[:12]}"
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


def _user(c: Conn) -> str:
    uid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO users (id, email, username, password_hash) VALUES (%s, %s, %s, '$argon2id$x')",
        (uid, f"{uid[:8]}@x.io", f"u{uid[:8]}"),
    )
    return uid


def _account(c: Conn, created_by: str | None = None) -> str:
    uid = str(uuid.uuid4().int % 10**15)
    row: dict[str, object] = {"id": str(uuid.uuid4()), "exchange": "bybit", "env": "demo"}
    row |= {"kind": "main", "exchange_uid": uid, "label": f"acct {uid}"}
    return _insert(c, "exchange_accounts", row | {"created_by": created_by})


#: A trading-enabled profile with every cap bounded: valid, and one change away from each refusal.
_TRADING: dict[str, object] = {
    "trading_enabled": True,
    "risk_pct_equity": Decimal("1"),
    "max_position_notional_usd": Decimal("50000"),
    "max_daily_loss_usd": Decimal("1000"),
    "max_open_positions": 3,
    "max_concurrent_orders": 20,
    "max_leverage_cap": Decimal("10"),
}


def _profile(c: Conn, account: str, **cols: object) -> str:
    row: dict[str, object] = {"id": str(uuid.uuid4()), "exchange_account_id": account}
    return _insert(c, "account_profiles", row | {"name": f"p {uuid.uuid4().hex[:8]}"} | cols)


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


def _binding(c: Conn, account: str) -> int:
    """The account's default binding version (0048, #906 0d)."""
    query = "SELECT default_binding_version FROM exchange_accounts WHERE id = %s"
    return int(_one(c, query, account))


# --- The catalog equals the plan doc, and the round trip leaves nothing behind ----------------

_CATALOG = (
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


def _doc_section(heading: str) -> str:
    section = _DOC.read_text(encoding="utf-8").split(f"#### {heading}", 1)[1]
    return re.split(r"\n#{1,4} ", section, maxsplit=1)[0]


def _doc_blocks(heading: str) -> list[str]:
    return [b.split("```", 1)[0] for b in _doc_section(heading).split("```sql")[1:]]


def _doc_ddl() -> str:
    """The table, its triggers, the default binding's trigger (0048) and the revisions table; not
    the bootstrap block, whose trigger sits on `exchange_accounts` (checked by name below)."""
    table, triggers, _bootstrap, binding = _doc_blocks("3.2.4 `account_profiles`")
    revisions = _doc_blocks("3.2.5 `account_profile_revisions`")
    return "\n".join([table, *revisions, triggers, binding])


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


def test_schema_matches_the_plan_doc(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _assert_matches_plan_doc(c)
        bootstrap = c.execute(
            "SELECT tgenabled::text, pg_get_triggerdef(oid) FROM pg_trigger "
            "WHERE tgrelid = 'exchange_accounts'::regclass AND tgname = 'trg_ea_default_profile'"
        ).fetchall()
        assert bootstrap == [
            (
                "A",
                "CREATE TRIGGER trg_ea_default_profile AFTER INSERT ON public.exchange_accounts "
                "FOR EACH ROW EXECUTE FUNCTION ea_default_profile()",
            )
        ]
        pinned = c.execute(
            "SELECT proname, proconfig, prosecdef FROM pg_proc WHERE proname = ANY(%s) "
            "ORDER BY proname",
            (
                [
                    "ap_default_binding_bump",
                    "ap_ladder_sum_check",
                    "ap_record_revision",
                    "ap_version_bump",
                    "ea_default_profile",
                ],
            ),
        ).fetchall()
        assert [p[1] for p in pinned] == [["search_path=pg_catalog, pg_temp"]] * 5
        # SEC-905-01: only the revision writer runs as its owner
        assert [p[0] for p in pinned if p[2]] == ["ap_record_revision"]


def _seed_accounts_at_the_previous_revision(dsn: str, n: int) -> list[str]:
    assert _alembic(dsn, "downgrade", _PREV).returncode == 0
    with _conn(dsn) as c:
        owner = _user(c)
        return [_account(c, created_by=owner) for _ in range(n)]


@pytest.mark.parametrize("seeded", [False, True], ids=["empty", "seeded"])
def test_round_trip_leaves_no_residue_and_backfills_each_account(pg_dsn: str, seeded: bool) -> None:
    """C-5.5: downgrade -> upgrade -> downgrade -> upgrade on an empty and on a seeded database;
    each upgrade gives every existing account its bootstrap profile and revision."""
    dsn = _fresh(pg_dsn)
    accounts = _seed_accounts_at_the_previous_revision(dsn, 3 if seeded else 0)
    for _ in range(2):
        assert _alembic(dsn, "upgrade", "head").returncode == 0
        with _conn(dsn) as c:
            _assert_matches_plan_doc(c)
            for account in accounts:
                profile = _default_of(c, account)
                assert _one(c, "SELECT version FROM account_profiles WHERE id = %s", profile) == 1
                assert (
                    _one(
                        c,
                        "SELECT count(*) FROM account_profile_revisions WHERE profile_id = %s",
                        profile,
                    )
                    == 1
                )
            assert _count(c, "account_profiles") == len(accounts)
        downgraded = _alembic(dsn, "downgrade", _PREV)
        assert downgraded.returncode == 0, downgraded.stderr
        with _conn(dsn) as c:
            for obj in (
                *_TABLES,
                "ux_ap_name",
                "ux_ap_default",
                "account_profile_revisions_id_seq",
            ):
                assert c.execute("SELECT to_regclass(%s)", (obj,)).fetchone() == (None,)
            for kind in ("sizing_mode", "offset_unit"):
                assert c.execute("SELECT to_regtype(%s)", (kind,)).fetchone() == (None,)
            assert not c.execute(
                "SELECT 1 FROM pg_proc WHERE proname IN ('ap_ladder_sum_check', "
                "'ap_record_revision', 'ap_version_bump', 'ea_default_profile')"
            ).fetchall()
            assert not c.execute(
                "SELECT 1 FROM pg_trigger WHERE tgname = 'trg_ea_default_profile'"
            ).fetchall()
            assert _count(c, "exchange_accounts") == len(accounts)


_BOOTSTRAP_AGAIN = (
    "INSERT INTO account_profiles (id, exchange_account_id, name, is_default, risk_pct_equity) "
    "VALUES (gen_random_uuid(), %(a)s, 'Default', true, 1)"
)


@pytest.mark.parametrize(
    "writes",
    [
        ["INSERT INTO account_profiles (id, exchange_account_id, name, risk_pct_equity) "
         "VALUES (gen_random_uuid(), %(a)s, 'Scalp', 1)"],
        ["UPDATE account_profiles SET leverage = 2 WHERE exchange_account_id = %(a)s"],
        ["UPDATE account_profiles SET deleted_at = now() WHERE exchange_account_id = %(a)s"],
        ["DELETE FROM account_profiles WHERE exchange_account_id = %(a)s", _BOOTSTRAP_AGAIN],
        ["DELETE FROM exchange_accounts WHERE id = %(a)s"],
    ],
    ids=["created", "edited", "soft-deleted", "replaced-by-a-lookalike", "account-deleted"],
)  # fmt: skip
def test_downgrade_refuses_while_a_written_profile_or_its_history_exists(
    pg_dsn: str, writes: list[str]
) -> None:
    """Profiles are configuration and their revisions append-only history: fix forward (C-5.2).
    A hard delete leaves its revision behind, so a lookalike `Default` and a deleted account
    refuse too. A refused downgrade changes nothing."""
    dsn = _fresh(pg_dsn)
    with _conn(dsn) as c:
        account = _account(c)
        for write in writes:
            c.execute(write, {"a": account})
        head = c.execute("SELECT version_num FROM alembic_version").fetchone()  # not always 0037
        before = (_count(c, "account_profiles"), _count(c, "account_profile_revisions"))
        refused = _alembic(dsn, "downgrade", _PREV)
        assert refused.returncode != 0
        assert (
            "0037_account_profiles downgrade refused: a profile was created, edited or deleted"
        ) in refused.stderr
        assert c.execute("SELECT version_num FROM alembic_version").fetchone() == head
        assert (_count(c, "account_profiles"), _count(c, "account_profile_revisions")) == before


# --- Every invalid row is refused by its NAMED constraint ---------------------------------------

_INVALID: dict[str, dict[str, object]] = {
    "ap_leverage": {"leverage": Decimal("101"), "max_leverage_cap": None, "trading_enabled": False},
    "ap_native_sl": {"require_native_sl": False},
    "ap_tif": {"time_in_force_default": "DAY"},
    "ap_slip": {"slippage_tolerance_bps": 1001},
    "ap_opm": {"max_orders_per_minute": 0},
    "ap_sl_pos": {"sl_offset_value": Decimal("0")},
    "ap_tp_pair": {"tp_offset_value": Decimal("2")},
    "ap_tp_pos": {"tp_offset_value": Decimal("0"), "tp_offset_unit": "ticks"},
    "ap_maxpos": {"max_open_positions": 51},
    "ap_sizing_shape": {"size_fixed_qty": Decimal("1")},
    "ap_ladder_shape": {"tp_ladder": Jsonb({"pct": 50, "r": 1})},
    "ap_name": {"name": ""},
    "ap_margin_mode": {"margin_mode": "portfolio"},
    "ap_position_mode": {"position_mode": "both"},
    "ap_sl_unit": {"sl_offset_unit": "r_multiple"},
    "ap_atr": {"sl_atr_period": 1},
    "ap_fallback_sl": {"fallback_sl_offset_pct": Decimal("100")},
    "ap_min_leg": {"min_leg_notional_usd": Decimal("-1")},
    "ap_max_notional": {"max_position_notional_usd": Decimal("0")},
    "ap_max_pos_pct": {"max_position_pct_equity": Decimal("100.000001")},
    "ap_daily_loss": {"max_daily_loss_usd": Decimal("0")},
    "ap_daily_loss_pct": {"max_daily_loss_pct": Decimal("0")},
    "ap_max_orders": {"max_concurrent_orders": 501},
    "ap_lev_cap": {"leverage": Decimal("11")},
    "ap_trading_caps": {"max_concurrent_orders": None},
    "ap_all_symbols": {"all_symbols": True, "allowed_symbols": ["BTCUSDT"]},
    "ap_finite": {"max_daily_loss_usd": Decimal("NaN")},
}


@pytest.mark.parametrize(("constraint", "bad"), _INVALID.items(), ids=list(_INVALID))
def test_invalid_profile_is_refused_by_its_named_constraint(
    pg_dsn: str, constraint: str, bad: dict[str, object]
) -> None:
    """The constraint matrix: each CHECK refuses its own violation, starting from a valid
    trading-enabled profile, and no row is written."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        assert _profile(c, account, **_TRADING)  # the base row is valid
        before = _count(c, "account_profiles")
        with pytest.raises(pgerr.CheckViolation) as exc:
            _profile(c, account, **(_TRADING | bad))
        assert exc.value.diag.constraint_name == constraint
        assert _count(c, "account_profiles") == before


_NAN = Decimal("NaN")


@pytest.mark.parametrize(
    "nan",
    [
        {"max_position_notional_usd": _NAN},
        {"max_daily_loss_usd": _NAN},
        {"min_leg_notional_usd": _NAN},
        {"sl_offset_value": _NAN},
        {"sl_atr_multiple": _NAN},
        {"tp_offset_value": _NAN, "tp_offset_unit": "ticks"},
        {"sizing_mode": "fixed_qty", "risk_pct_equity": None, "size_fixed_qty": _NAN},
        {"sizing_mode": "fixed_notional", "risk_pct_equity": None, "size_fixed_notional_usd": _NAN},
        {"risk_pct_equity": None, "risk_fixed_amount_usd": _NAN},
    ],
    ids=["position-cap", "loss-cap", "min-leg", "stop", "atr", "take-profit", "qty", "notional",
         "risk-amount"],
)  # fmt: skip
def test_a_nan_is_no_bound_and_is_refused(pg_dsn: str, nan: dict[str, object]) -> None:
    """Postgres sorts NaN above every number, so each of these columns' bounds admits it alone,
    and a NaN cap would satisfy `ap_trading_caps` (SR-E28-01). `ap_finite` refuses it first."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        with pytest.raises(pgerr.CheckViolation) as exc:
            _profile(c, account, **(_TRADING | nan))
        assert exc.value.diag.constraint_name == "ap_finite"


def test_ap_version_holds_even_with_the_version_trigger_off(pg_dsn: str) -> None:
    """`trg_ap_version` makes a bad version unwritable; the CHECK stays the backstop."""
    with _conn(_fresh(pg_dsn)) as c, c.transaction():
        c.execute("ALTER TABLE account_profiles DISABLE TRIGGER trg_ap_version")
        with pytest.raises(pgerr.CheckViolation) as exc:
            _profile(c, _account(c), risk_pct_equity=Decimal("1"), version=0)
        assert exc.value.diag.constraint_name == "ap_version"
        raise psycopg.Rollback


@pytest.mark.parametrize(
    ("constraint", "column", "value"),
    [("apr_version", "version", 0), ("apr_payload", "payload", Jsonb([]))],
)
def test_invalid_revision_is_refused_by_its_named_constraint(
    pg_dsn: str, constraint: str, column: str, value: object
) -> None:
    row: dict[str, object] = {"profile_id": str(uuid.uuid4()), "version": 1}
    row |= {"payload": Jsonb({"name": "x"})}
    stmt = sql.SQL("INSERT INTO account_profile_revisions ({}) VALUES ({})").format(
        sql.SQL(", ").join(sql.Identifier(k) for k in row),
        sql.SQL(", ").join([sql.Placeholder()] * len(row)),
    )
    with _conn(_fresh(pg_dsn)) as c, pytest.raises(pgerr.CheckViolation) as exc:
        c.execute(stmt, tuple((row | {column: value}).values()))
    assert exc.value.diag.constraint_name == constraint


# --- The #905 Gherkin scenarios that are pure database behaviour -------------------------------


@pytest.mark.parametrize("verb", ["INSERT", "UPDATE"])
def test_the_native_sl_invariant_is_enforced_by_the_database(pg_dsn: str, verb: str) -> None:
    """Scenario "The native-SL invariant is enforced by the database"."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        profile = _default_of(c, account)
        before = c.execute("SELECT to_jsonb(p) FROM account_profiles p").fetchall()
        with pytest.raises(pgerr.CheckViolation) as exc:
            if verb == "INSERT":
                _profile(c, account, risk_pct_equity=Decimal("1"), require_native_sl=False)
            else:
                c.execute(
                    "UPDATE account_profiles SET require_native_sl = false WHERE id = %s",
                    (profile,),
                )
        assert exc.value.diag.constraint_name == "ap_native_sl"
        assert c.execute("SELECT to_jsonb(p) FROM account_profiles p").fetchall() == before


_OWN = {
    "fixed_qty": "size_fixed_qty",
    "fixed_notional": "size_fixed_notional_usd",
    "pct_equity": "size_pct_equity",
    "risk_based": "risk_pct_equity",
}


@pytest.mark.parametrize("mode", list(_OWN))
@pytest.mark.parametrize("extra", list(_OWN.values()))
def test_sizing_shape_is_enforced_by_the_database(pg_dsn: str, mode: str, extra: str) -> None:
    """Scenario "Sizing shape is enforced by the database", as the full 4 x 4 matrix: a mode with
    its own size column is valid, and any other size column beside it is refused."""
    own = {"sizing_mode": mode, _OWN[mode]: Decimal("1")}
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        if extra == _OWN[mode]:
            assert _profile(c, account, **own)
            return
        with pytest.raises(pgerr.CheckViolation) as exc:
            _profile(c, account, **own, **{extra: Decimal("1")})
        assert exc.value.diag.constraint_name == "ap_sizing_shape"


@pytest.mark.parametrize("mode", list(_OWN))
def test_a_sizing_mode_without_its_size_is_refused(pg_dsn: str, mode: str) -> None:
    """A NULL size compares to NULL, which a bare CHECK lets pass: `ap_sizing_shape` is
    `(...) IS TRUE`, so a profile with no size at all is refused in every mode."""
    with _conn(_fresh(pg_dsn)) as c, pytest.raises(pgerr.CheckViolation) as exc:
        _profile(c, _account(c), sizing_mode=mode)
    assert exc.value.diag.constraint_name == "ap_sizing_shape"


@pytest.mark.parametrize(
    ("risk", "valid"),
    [
        ({"risk_fixed_amount_usd": Decimal("250")}, True),
        ({"risk_pct_equity": Decimal("1")}, True),
        ({}, False),
        ({"risk_pct_equity": Decimal("1"), "risk_fixed_amount_usd": Decimal("250")}, False),
    ],
    ids=["fixed-amount", "percent", "neither", "both"],
)
def test_risk_based_takes_exactly_one_of_percent_and_fixed_amount(
    pg_dsn: str, risk: dict[str, object], valid: bool
) -> None:
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        if valid:
            assert _profile(c, account, **risk)
            return
        with pytest.raises(pgerr.CheckViolation) as exc:
            _profile(c, account, **risk)
        assert exc.value.diag.constraint_name == "ap_sizing_shape"


def test_exactly_one_default_profile_per_account(pg_dsn: str) -> None:
    """Scenario "Exactly one default profile per account": the bootstrap profile is the default."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        assert _default_of(c, account)
        with pytest.raises(pgerr.UniqueViolation) as exc:
            _profile(c, account, risk_pct_equity=Decimal("1"), is_default=True)
        assert exc.value.diag.constraint_name == "ux_ap_default"


def test_two_concurrent_default_inserts_admit_exactly_one(pg_dsn: str) -> None:
    """The second transaction waits on the first's index entry, then fails when it commits."""
    dsn = _fresh(pg_dsn)
    with _conn(dsn) as c:
        account = _account(c)
        c.execute("UPDATE account_profiles SET deleted_at = now() WHERE exchange_account_id = %s",
                  (account,))  # fmt: skip
    outcome: list[BaseException | None] = []
    with _conn(dsn) as first, _conn(dsn) as second, _conn(dsn) as watcher:
        first.autocommit = False
        _profile(first, account, risk_pct_equity=Decimal("1"), is_default=True)
        blocked_pid = second.info.backend_pid

        def contend() -> None:
            try:
                _profile(second, account, risk_pct_equity=Decimal("1"), is_default=True)
                outcome.append(None)
            except pgerr.UniqueViolation as exc:
                outcome.append(exc)

        worker = threading.Thread(target=contend)
        worker.start()
        for _ in range(3000):  # until the second insert waits on the first's index entry
            waiting = watcher.execute(
                "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", (blocked_pid,)
            ).fetchone()
            if waiting == ("Lock",):
                break
            watcher.execute("SELECT pg_sleep(0.01)")
        else:
            pytest.fail("the second insert never waited on the first")
        first.commit()
        worker.join(timeout=30)
    assert len(outcome) == 1 and isinstance(outcome[0], pgerr.UniqueViolation)
    with _conn(dsn) as c:
        assert _default_of(c, account)


@pytest.mark.parametrize("rungs", [0, 1, 5])
def test_a_ladder_within_the_limit_is_stored(pg_dsn: str, rungs: int) -> None:
    ladder = [{"pct": 20, "r": n + 1} for n in range(rungs)]
    with _conn(_fresh(pg_dsn)) as c:
        profile = _profile(c, _account(c), risk_pct_equity=Decimal("1"), tp_ladder=Jsonb(ladder))
        stored = _one(c, "SELECT tp_ladder FROM account_profiles WHERE id = %s", profile)
        assert stored == ladder


@pytest.mark.parametrize(
    ("ladder", "message"),
    [
        (
            [{"pct": 60, "r": 1}, {"pct": 60, "r": 2}],
            "trg_ap_ladder_sum: the tp_ladder pct values add up to more than the 100% limit",
        ),
        ([{"pct": 0, "r": 1}], "trg_ap_ladder_sum: every tp_ladder rung needs a number pct"),
        ([{"pct": 50}], "trg_ap_ladder_sum: every tp_ladder rung needs a number pct"),
        ([{"pct": "50", "r": 1}], "trg_ap_ladder_sum: every tp_ladder rung needs a number pct"),
        ([50], "trg_ap_ladder_sum: every tp_ladder rung needs a number pct"),
    ],
    ids=["over-100", "zero-pct", "no-r", "string-pct", "not-an-object"],
)
def test_tp_ladder_percentages_cannot_exceed_100(
    pg_dsn: str, ladder: list[object], message: str
) -> None:
    """Scenario "TP ladder percentages cannot exceed 100": refused by the trigger, with a message
    naming the 100 % limit (and never a value), on INSERT and on UPDATE."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        with pytest.raises(pgerr.CheckViolation) as exc:
            _profile(c, account, risk_pct_equity=Decimal("1"), tp_ladder=Jsonb(ladder))
        assert str(exc.value.diag.message_primary).startswith(message)
        assert exc.value.diag.constraint_name == "trg_ap_ladder_sum"  # the store maps it by name
        with pytest.raises(pgerr.CheckViolation):
            c.execute("UPDATE account_profiles SET tp_ladder = %s WHERE id = %s",
                      (Jsonb(ladder), _default_of(c, account)))  # fmt: skip


def test_a_soft_deleted_profile_frees_its_name(pg_dsn: str) -> None:
    """Scenario "A soft-deleted profile frees its name": `ux_ap_name` covers live rows only, and
    compares names case-insensitively."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        scalp = _profile(c, account, risk_pct_equity=Decimal("1"), name="Scalp")
        with pytest.raises(pgerr.UniqueViolation) as exc:
            _profile(c, account, risk_pct_equity=Decimal("1"), name="SCALP")
        assert exc.value.diag.constraint_name == "ux_ap_name"
        c.execute("UPDATE account_profiles SET deleted_at = now() WHERE id = %s", (scalp,))
        assert _profile(c, account, risk_pct_equity=Decimal("1"), name="scalp")


# --- version is the database's; every write leaves its revision ---------------------------------


def test_version_is_set_by_the_database_whatever_the_writer_sends(pg_dsn: str) -> None:
    with _conn(_fresh(pg_dsn)) as c:
        profile = _profile(c, _account(c), risk_pct_equity=Decimal("1"), version=7)
        assert _one(c, "SELECT version FROM account_profiles WHERE id = %s", profile) == 1
        for expected in (2, 3):
            c.execute("UPDATE account_profiles SET version = 99, leverage = %s WHERE id = %s",
                      (Decimal(expected), profile))  # fmt: skip
            assert (
                _one(c, "SELECT version FROM account_profiles WHERE id = %s", profile) == expected
            )


@pytest.mark.parametrize("column", ["id", "exchange_account_id"])
def test_identity_columns_are_write_once(pg_dsn: str, column: str) -> None:
    with _conn(_fresh(pg_dsn)) as c:
        profile = _default_of(c, _account(c))
        other = str(uuid.uuid4()) if column == "id" else _account(c)
        with pytest.raises(pgerr.CheckViolation) as exc:
            c.execute(
                sql.SQL("UPDATE account_profiles SET {} = %s WHERE id = %s").format(
                    sql.Identifier(column)
                ),
                (other, profile),
            )
        assert str(exc.value.diag.message_primary).startswith(
            "trg_ap_version: account_profiles.id and exchange_account_id are write-once"
        )
        assert exc.value.diag.constraint_name == "trg_ap_version"


def test_every_write_records_the_row_as_a_revision_in_the_same_transaction(pg_dsn: str) -> None:
    """SR-E28-07: revision `version` = the row's `version`, `payload` = the row as written,
    `changed_by` = `created_by` on insert and `updated_by` on update; `updated_at` moves."""
    with _conn(_fresh(pg_dsn)) as c:
        author, editor = _user(c), _user(c)
        profile = _profile(c, _account(c), risk_pct_equity=Decimal("1"), created_by=author)
        c.execute("UPDATE account_profiles SET leverage = 3, updated_by = %s WHERE id = %s",
                  (editor, profile))  # fmt: skip
        c.execute("UPDATE account_profiles SET deleted_at = now() WHERE id = %s", (profile,))
        revisions = c.execute(
            "SELECT version, changed_by::text, payload FROM account_profile_revisions "
            "WHERE profile_id = %s ORDER BY version",
            (profile,),
        ).fetchall()
        assert [(r[0], r[1]) for r in revisions] == [(1, author), (2, editor), (3, editor)]
        assert [Decimal(str(r[2]["leverage"])) for r in revisions] == [1, 3, 3]
        assert revisions[2][2]["deleted_at"] is not None and revisions[1][2]["deleted_at"] is None
        current = _one(c, "SELECT to_jsonb(p) FROM account_profiles p WHERE id = %s", profile)
        assert revisions[2][2] == current
        created, updated = c.execute(
            "SELECT created_at, updated_at FROM account_profiles WHERE id = %s", (profile,)
        ).fetchone() or (None, None)
        assert created is not None and updated is not None and updated >= created


def test_a_revision_that_cannot_be_written_rolls_the_profile_write_back(pg_dsn: str) -> None:
    """`trg_ap_revision` runs in the write's transaction: a planted revision for the next version
    makes the revision insert fail, and the profile is left exactly as it was."""
    with _conn(_fresh(pg_dsn)) as c:
        profile = _default_of(c, _account(c))
        c.execute(
            "INSERT INTO account_profile_revisions (profile_id, version, payload) "
            "VALUES (%s, 2, '{}'::jsonb)",
            (profile,),
        )
        before = _one(c, "SELECT to_jsonb(p) FROM account_profiles p WHERE id = %s", profile)
        with pytest.raises(pgerr.UniqueViolation) as exc:
            c.execute("UPDATE account_profiles SET leverage = 2 WHERE id = %s", (profile,))
        assert exc.value.diag.constraint_name == "ux_apr_version"
        after = _one(c, "SELECT to_jsonb(p) FROM account_profiles p WHERE id = %s", profile)
        assert after == before and after["version"] == 1


@pytest.mark.parametrize(
    "verb",
    [
        "UPDATE account_profile_revisions SET version = version",
        "DELETE FROM account_profile_revisions",
        "TRUNCATE account_profile_revisions CASCADE",
    ],
)
@pytest.mark.parametrize("replica", [False, True], ids=["origin", "replica"])
def test_revisions_cannot_be_rewritten(pg_dsn: str, verb: str, replica: bool) -> None:
    """INSERT-only (SR-E28-07): `forbid_mutation()` per row and `audit_refuse_truncate()` per
    statement, both `ENABLE ALWAYS`, so the replica role does not switch them off. The TRUNCATE
    cascades, because `trade_group_legs` (0039) references the table and a plain one stops at that
    foreign key first. The cascade also reaches tables with truncate guards of their own, so the
    refusal must name this table: its trigger fires first, and only while it exists."""
    with _conn(_fresh(pg_dsn)) as c:
        _account(c)
        before = c.execute("SELECT * FROM account_profile_revisions ORDER BY id").fetchall()
        with c.transaction():
            if replica:
                c.execute("SET LOCAL session_replication_role = replica")
            with pytest.raises(psycopg.errors.RaiseException) as refused:
                c.execute(verb)
            message = refused.value.diag.message_primary or ""
            assert message.startswith("table account_profile_revisions is append-only"), message
            raise psycopg.Rollback
        assert c.execute("SELECT * FROM account_profile_revisions ORDER BY id").fetchall() == before


def test_the_integrity_triggers_fire_under_the_replica_role(pg_dsn: str) -> None:
    """Bootstrap, version, revision and the ladder check are `ENABLE ALWAYS`."""
    with _conn(_fresh(pg_dsn)) as c, c.transaction():
        c.execute("SET LOCAL session_replication_role = replica")
        account = _account(c)
        profile = _default_of(c, account)  # trg_ea_default_profile fired too
        c.execute("UPDATE account_profiles SET version = 50, leverage = 2 WHERE id = %s",
                  (profile,))  # fmt: skip
        assert _one(c, "SELECT version FROM account_profiles WHERE id = %s", profile) == 2
        assert (
            _one(c, "SELECT count(*) FROM account_profile_revisions WHERE profile_id = %s", profile)
            == 2
        )
        over = Jsonb([{"pct": 60, "r": 1}, {"pct": 60, "r": 2}])
        with pytest.raises(pgerr.CheckViolation):
            c.execute("UPDATE account_profiles SET tp_ladder = %s WHERE id = %s", (over, profile))
        raise psycopg.Rollback


# --- Bootstrap: an account is never profile-less ----------------------------------------------


def test_a_new_account_gets_an_inert_default_profile(pg_dsn: str) -> None:
    """Every new account gets `Default`: enabled, not trading-enabled (SR-E28-01), sized at 1 %
    risk, no symbol allowed until the owner completes it; its creator is the profile's."""
    with _conn(_fresh(pg_dsn)) as c:
        owner = _user(c)
        account = _account(c, created_by=owner)
        row = c.execute(
            "SELECT name, is_default, enabled, trading_enabled, version, sizing_mode::text, "
            "risk_pct_equity, all_symbols, allowed_symbols, created_by::text, updated_by::text "
            "FROM account_profiles WHERE exchange_account_id = %s",
            (account,),
        ).fetchall()
        assert row == [
            ("Default", True, True, False, 1, "risk_based", Decimal("1"), False, None, owner, owner)
        ]
        assert (
            _one(
                c,
                "SELECT changed_by::text FROM account_profile_revisions WHERE profile_id = %s",
                _default_of(c, account),
            )
            == owner
        )


def test_deleting_an_account_removes_its_profiles_and_keeps_their_history(pg_dsn: str) -> None:
    """`ON DELETE CASCADE` on the profile; the revisions keep no reference, so they stay."""
    with _conn(_fresh(pg_dsn)) as c:
        account = _account(c)
        profile = _default_of(c, account)
        c.execute("DELETE FROM exchange_accounts WHERE id = %s", (account,))
        assert _count(c, "account_profiles") == 0
        payload = _one(
            c, "SELECT payload FROM account_profile_revisions WHERE profile_id = %s", profile
        )
        assert payload["exchange_account_id"] == account


# --- 0048: the default binding's version (#906 0d) ---------------------------------------------


def test_the_binding_version_counts_moves_and_never_repeats(pg_dsn: str) -> None:
    """21 Sec.3.2.4: one more each time a profile becomes the account's default; an insert, an
    edit, a re-set default, a `false` written to a non-default, a soft-deleted spare and an unset
    alone leave it, and moving back never returns it to a value it had. Another account's version
    is its own."""
    with _conn(_fresh(pg_dsn)) as c:
        account, other = _account(c), _account(c)
        home = _default_of(c, account)
        assert _binding(c, account) == 1  # the bootstrap `Default` is the first binding
        spare = _profile(c, account, risk_pct_equity=Decimal("1"))
        ghost = _profile(c, account, risk_pct_equity=Decimal("1"))
        assert _binding(c, account) == 1
        for quiet in (
            "UPDATE account_profiles SET leverage = 2 WHERE id = %(home)s",
            "UPDATE account_profiles SET is_default = true WHERE id = %(home)s",
            "UPDATE account_profiles SET is_default = false WHERE id = %(spare)s",
            "UPDATE account_profiles SET deleted_at = now() WHERE id = %(ghost)s",
        ):
            c.execute(quiet, {"home": home, "spare": spare, "ghost": ghost})
            assert _binding(c, account) == 1, quiet
        with c.transaction():
            c.execute("UPDATE account_profiles SET is_default = false WHERE id = %s", (home,))
            assert _binding(c, account) == 1  # an unset alone leaves it
            c.execute("UPDATE account_profiles SET is_default = true WHERE id = %s", (spare,))
        assert _binding(c, account) == 2
        with c.transaction():
            c.execute("UPDATE account_profiles SET is_default = false WHERE id = %s", (spare,))
            c.execute("UPDATE account_profiles SET is_default = true WHERE id = %s", (home,))
        assert _binding(c, account) == 3
        assert _binding(c, other) == 1


def test_a_move_counts_in_replica_mode_too(pg_dsn: str) -> None:
    """`trg_ap_default_binding` is `ENABLE ALWAYS`: `session_replication_role = replica` does not
    skip the count."""
    with _conn(_fresh(pg_dsn)) as c, c.transaction():
        c.execute("SET LOCAL session_replication_role = replica")
        account = _account(c)
        home = _default_of(c, account)
        spare = _profile(c, account, risk_pct_equity=Decimal("1"))
        c.execute("UPDATE account_profiles SET is_default = false WHERE id = %s", (home,))
        c.execute("UPDATE account_profiles SET is_default = true WHERE id = %s", (spare,))
        assert _binding(c, account) == 2
        raise psycopg.Rollback


# --- C-5.7: no role may rewrite profile history (the 0003 grant pattern) ------------------------


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


def test_no_role_may_rewrite_profile_history(bootstrapped_dsn: str) -> None:
    query = "SELECT has_table_privilege(%s, %s, %s)"
    with _conn(bootstrapped_dsn) as c:

        def can(role: str, table: str, privilege: str) -> bool:
            return c.execute(query, (role, table, privilege)).fetchone() == (True,)

        for role in ("cv_app", "cv_ro"):
            assert not any(
                can(role, "account_profile_revisions", p)
                for p in ("INSERT", "UPDATE", "DELETE", "TRUNCATE")
            )
            assert c.execute(
                "SELECT has_function_privilege(%s, 'ap_record_revision()', 'EXECUTE')", (role,)
            ).fetchone() == (False,)
        assert can("cv_app", "account_profile_revisions", "SELECT")
        assert can("cv_ro", "account_profile_revisions", "SELECT")
        assert can("cv_app", "account_profiles", "UPDATE")
        assert not can("cv_app", "account_profiles", "DELETE")


def test_a_profile_leaves_only_with_an_account_the_owner_deletes(bootstrapped_dsn: str) -> None:
    """A profile leaves by soft delete: `cv_app` cannot hard-delete one, which would leave no
    revision (SEC-D01), nor the account it belongs to (0044, #2758). The owner's delete of the
    account, the purge path, still cascades, as the RI action runs as the table's owner, and the
    history stays."""
    app = re.sub(r"://[^@]+@", "://cv_app:cv_app_test_pw@", bootstrapped_dsn)
    owner = re.sub(r"://[^@]+@", "://cv_owner:cv_owner_test_pw@", bootstrapped_dsn)
    with _conn(app) as c:
        account = _account(c)
        profile = _default_of(c, account)
        with pytest.raises(pgerr.InsufficientPrivilege):
            c.execute("DELETE FROM account_profiles WHERE id = %s", (profile,))
        with pytest.raises(pgerr.InsufficientPrivilege):
            c.execute("DELETE FROM exchange_accounts WHERE id = %s", (account,))
        assert _one(c, "SELECT count(*) FROM account_profiles WHERE id = %s", profile) == 1
    with _conn(owner) as c:
        c.execute("DELETE FROM exchange_accounts WHERE id = %s", (account,))
        assert _one(c, "SELECT count(*) FROM account_profiles WHERE id = %s", profile) == 0
        assert (
            _one(c, "SELECT count(*) FROM account_profile_revisions WHERE profile_id = %s", profile)
            == 1
        )


def test_the_app_role_creates_an_account_with_its_profile_and_revision(
    bootstrapped_dsn: str,
) -> None:
    """`cv_app` writes the account and its profile; the revision is written by the definer
    function, and `cv_app` can neither forge one nor remove one (SEC-905-01, SR-E28-07)."""
    app = re.sub(r"://[^@]+@", "://cv_app:cv_app_test_pw@", bootstrapped_dsn)
    with _conn(app) as c:
        account = _account(c)
        profile = _default_of(c, account)
        assert (
            _one(c, "SELECT count(*) FROM account_profile_revisions WHERE profile_id = %s", profile)
            == 1
        )
        c.execute("UPDATE account_profiles SET leverage = 2 WHERE id = %s", (profile,))
        assert _one(c, "SELECT max(version) FROM account_profile_revisions WHERE profile_id = %s",
                    profile) == 2  # fmt: skip
        with pytest.raises(pgerr.InsufficientPrivilege):
            c.execute(
                "INSERT INTO account_profile_revisions (profile_id, version, payload) "
                "VALUES (%s, 3, '{}'::jsonb)",
                (profile,),
            )
        with pytest.raises(pgerr.InsufficientPrivilege):
            c.execute("DELETE FROM account_profile_revisions WHERE profile_id = %s", (profile,))
        with pytest.raises(pgerr.InsufficientPrivilege):
            c.execute("SELECT ap_record_revision()")


def test_the_app_role_moves_the_default_and_the_binding_counts_it(bootstrapped_dsn: str) -> None:
    """0048 (#906 0d): `ap_default_binding_bump` is no SECURITY DEFINER, so its UPDATE of
    `exchange_accounts` runs as the role that moves the default. `cv_app` holds that UPDATE
    (`pg_bootstrap.sql`); a revision that narrowed it would fail every move inside the trigger."""
    app = re.sub(r"://[^@]+@", "://cv_app:cv_app_test_pw@", bootstrapped_dsn)
    with _conn(app) as c:
        account = _account(c)
        home = _default_of(c, account)
        spare = _profile(c, account, risk_pct_equity=Decimal("1"))
        assert _binding(c, account) == 1
        with c.transaction():
            c.execute("UPDATE account_profiles SET is_default = false WHERE id = %s", (home,))
            c.execute("UPDATE account_profiles SET is_default = true WHERE id = %s", (spare,))
        assert _binding(c, account) == 2
