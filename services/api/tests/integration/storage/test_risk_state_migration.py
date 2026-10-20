"""Integration: `0038_risk_state` against real Postgres 16 (E39-T02 #882).

The catalog equals 21-database-schema.md Sec.3.11's DDL; the seed is the policy singleton and the
never-engaged global kill-switch row; every invalid row is rejected by its NAMED constraint with
its SQLSTATE (the bounds mirror 22 `RiskCaps` and `SetKillSwitchRequest`); one active lockout per
(account, manager), one policy row and one kill-switch row per target; the delete rules, the
downgrade guard, the round trip and the 5 s `lock_timeout` brackets are exercised on the real
engine. Uses `testcontainers` like the other migration suites.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from collections.abc import Iterator
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
_REV, _PREV = "0038_risk_state", "0037_account_profiles"
_TABLES = ("risk_lockouts", "risk_policy", "kill_switch_state")
_LIMITS = (
    "max_total_notional_usd",
    "max_daily_loss_usd",
    "max_drawdown_pct",
    "max_open_positions",
    "max_leverage",
    "max_orders_per_minute",
    "per_symbol_concentration_pct",
)

_EVERY_BLOCK = dict.fromkeys(_LIMITS, "block")

Conn = psycopg.Connection[tuple[Any, ...]]


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """Bounded, so a lost `lock_timeout` fails the test instead of hanging it."""
    return subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#882)
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
        _ok(dsn, "upgrade", "head")
        yield dsn


def _conn(dsn: str) -> Conn:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _ok(dsn: str, *args: str) -> None:
    """Run alembic and fail with its stderr (the Postgres error), not a bare `assert 1 == 0`."""
    done = _alembic(dsn, *args)
    assert done.returncode == 0, done.stderr


def _heal(dsn: str) -> None:
    """Back to head whatever a test did, so one failure cannot cascade into the others."""
    _ok(dsn, "upgrade", "head")


def _insert(c: Conn, table: str, row: dict[str, object]) -> str:
    stmt = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(k) for k in row),
        sql.SQL(", ").join([sql.Placeholder()] * len(row)),
    )
    c.execute(stmt, tuple(row.values()))
    return str(row["id"])


def _user(c: Conn) -> str:
    uid = str(uuid.uuid4())
    c.execute(
        "INSERT INTO users (id, email, username, password_hash) VALUES (%s, %s, %s, '$argon2id$x')",
        (uid, f"{uid[:8]}@example.test", f"u{uid[:8]}"),
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


def _account(c: Conn) -> str:
    acct = uuid.uuid4()
    c.execute(
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', 'demo', 'main', %s, %s)",
        (acct, str(acct.int % 10**15), f"L{acct.hex[:8]}"),
    )
    return str(acct)


def _lockout(c: Conn, account: str | None = None, /, **cols: object) -> str:
    row = {"id": str(uuid.uuid4()), "exchange_account_id": account or _account(c)}
    return _insert(c, "risk_lockouts", {**row, "reason": "daily_loss", **cols})


def _switch(c: Conn, **cols: object) -> str:
    row = {"id": str(uuid.uuid4()), "scope": "accounts", "engaged": False}
    if "exchange_account_id" not in cols and cols.get("scope") != "global":
        row["exchange_account_id"] = _account(c)
    return _insert(c, "kill_switch_state", {**row, **cols})


def _reset(c: Conn) -> None:
    """Back to the seed: the lockouts and account switches go, the policy is the seed again."""
    c.execute("DELETE FROM risk_lockouts")
    c.execute("DELETE FROM kill_switch_state WHERE scope <> 'global'")
    c.execute("UPDATE kill_switch_state SET engaged = false, engaged_at = NULL, reason = NULL")
    c.execute("UPDATE risk_policy SET updated_by = NULL")


# --- The catalog equals the plan doc, and the seed is the plan doc's ---------------------------

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
_NAMES = {
    *(f"{t}_pkey" for t in _TABLES),
    "risk_lockouts_exchange_account_id_fkey",
    "risk_lockouts_user_id_fkey",
    "risk_lockouts_released_by_fkey",
    "rl_reason",
    "rl_manual",
    "rl_until",
    "rl_released",
    "rl_release",
    "rl_text",
    "rl_numbers",
    "rl_actions",
    "ux_risk_lockout_active",
    "risk_policy_singleton_key",
    "risk_policy_updated_by_fkey",
    "rp_singleton",
    "rp_money",
    "rp_pct",
    "rp_positions",
    "rp_leverage",
    "rp_orders",
    "rp_lockout",
    "rp_day",
    "rp_behaviour",
    "kill_switch_state_exchange_account_id_fkey",
    "kill_switch_state_engaged_by_fkey",
    "kss_scope",
    "kss_target",
    "kss_engaged",
    "kss_reason",
    "kss_options",
    "ux_kill_switch_state_scope",
}


def _doc_block(n: int) -> str:
    """Sec.3.11's n-th ```sql block (1: the tables, 2: the seed), to its fence."""
    section = _DOC.read_text(encoding="utf-8").split("### 3.11 Risk state", 1)[1]
    return section.split("```sql", n)[n].split("```", 1)[0]


def _catalog(c: Conn, schema: str) -> list[Any]:
    """Columns, constraints and indexes of the three tables, schema qualifiers stripped."""
    unqualify = re.compile(r"\b(?:public|doc_ref)\.")
    out: list[Any] = []
    for table in _TABLES:
        for query in (_COLUMNS, _CONSTRAINTS, _INDEXES):
            rows = c.execute(query, (f"{schema}.{table}",)).fetchall()
            out.append([tuple(unqualify.sub("", str(v)) for v in row) for row in rows])
    return out


def _assert_matches_plan_doc(c: Conn) -> None:
    """Build the doc's DDL in a scratch schema (rolled back) and diff the two catalogs."""
    with c.transaction():
        c.execute("CREATE SCHEMA doc_ref")
        c.execute("SET LOCAL search_path = doc_ref, public")
        c.execute(_doc_block(1).encode())
        got, want = _catalog(c, "public"), _catalog(c, "doc_ref")
        raise psycopg.Rollback
    assert got == want and got
    assert {name for rows in got[1::3] + got[2::3] for name, *_ in rows} == _NAMES


def test_schema_matches_the_plan_doc_exactly(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _assert_matches_plan_doc(c)


def test_only_actual_value_carries_the_pii_classification_comment(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        rows = c.execute(
            "SELECT c.relname, a.attname, col_description(c.oid, a.attnum) FROM pg_class c "
            "JOIN pg_attribute a ON a.attrelid = c.oid WHERE c.relname = ANY(%s) "
            "AND a.attnum > 0 AND col_description(c.oid, a.attnum) IS NOT NULL",
            (list(_TABLES),),
        ).fetchall()
    assert [(t, col) for t, col, _ in rows] == [("risk_lockouts", "actual_value")]
    assert rows[0][2].startswith("PII: ")


def test_seed_is_one_policy_with_every_limit_set_and_one_disengaged_global_switch(
    pg_dsn: str,
) -> None:
    columns = (
        *_LIMITS,
        "breach_behaviour",
        "lockout_minutes_default",
        "block_trading_when_degraded",
        "day_boundary_utc_offset_minutes",
        "override_extra_loss_max_usd",
        "updated_by",
    )
    stmt = sql.SQL("SELECT {} FROM risk_policy").format(
        sql.SQL(", ").join(sql.Identifier(col) for col in columns)
    )
    with _conn(pg_dsn) as c:
        _reset(c)
        policy = c.execute(stmt).fetchall()
        switches = c.execute("SELECT scope, exchange_account_id, engaged FROM kill_switch_state")
        assert switches.fetchall() == [("global", None, False)]
    assert len(policy) == 1
    *limits, behaviour, lockout, degraded, offset, override_max, updated_by = policy[0]
    assert all(v is not None for v in limits), "every limit is set"
    assert behaviour == dict.fromkeys(_LIMITS, "block")
    assert (lockout, degraded, offset, updated_by) == (60, True, 0, None)
    assert override_max == 0, "D-4: an override extends nothing until the Owner raises the bound"


# --- Round trip and downgrade guard -----------------------------------------------------------


def test_round_trip_leaves_no_residue_and_restores_the_exact_schema(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _reset(c)
        try:
            _ok(pg_dsn, "downgrade", _PREV)
            for obj in (*_TABLES, "ux_risk_lockout_active", "ux_kill_switch_state_scope"):
                found = c.execute("SELECT to_regclass(%s)", (obj,)).fetchone()
                assert found == (None,), f"{obj} must be gone after the downgrade"
        finally:
            _heal(pg_dsn)  # the upgrade half of the round trip, even when a check above failed
        _assert_matches_plan_doc(c)
        seeded = c.execute(
            "SELECT (SELECT count(*) FROM risk_policy), (SELECT count(*) FROM kill_switch_state)"
        )
        assert seeded.fetchone() == (1, 1), "the upgrade re-seeds both singletons"


@pytest.mark.parametrize("seeded", [False, True], ids=["empty", "seeded"])
def test_upgrade_applies_over_an_empty_and_a_seeded_database(pg_dsn: str, seeded: bool) -> None:
    """C-5.5: the revision applies over 0037 whether or not the rows it references exist."""
    with _conn(pg_dsn) as c:
        _reset(c)
        try:
            _ok(pg_dsn, "downgrade", _PREV)
            parents = (_account(c), _user(c)) if seeded else None
            _ok(pg_dsn, "upgrade", _REV)
            _assert_matches_plan_doc(c)
            seeded_rows = c.execute(
                "SELECT (SELECT count(*) FROM risk_policy), "
                "(SELECT count(*) FROM kill_switch_state)"
            ).fetchone()
            assert seeded_rows == (1, 1), "the upgrade seeds both singletons"
            if parents is not None:
                account, manager = parents
                _lockout(c, account, user_id=manager)  # rows from before the upgrade are referenced
        finally:
            _heal(pg_dsn)
            _reset(c)


@pytest.mark.parametrize(
    "state",
    ["lockout", "engaged-global", "account-switch", "policy-written-by-a-person"],
)
def test_downgrade_refuses_while_risk_state_exists_beyond_the_seed(pg_dsn: str, state: str) -> None:
    with _conn(pg_dsn) as c:
        _reset(c)
        if state == "lockout":
            _lockout(c)
        elif state == "engaged-global":
            c.execute(
                "UPDATE kill_switch_state SET engaged = true, engaged_at = now(), reason = 'drill'"
            )
        elif state == "account-switch":
            _switch(c)
        else:
            c.execute("UPDATE risk_policy SET updated_by = %s", (_user(c),))
        try:
            refused = _alembic(pg_dsn, "downgrade", _PREV)
            assert refused.returncode != 0, f"a downgrade over {state} must be refused"
            assert "0038_risk_state downgrade refused" in refused.stderr, refused.stderr
            for table in _TABLES:
                still = c.execute("SELECT to_regclass(%s)", (table,)).fetchone()
                assert still == (table,), "a refused downgrade must leave every table in place"
        finally:
            _heal(pg_dsn)  # a regressed guard would have dropped the tables; keep that local
            _reset(c)


def test_upgrade_gives_up_on_a_held_lock_instead_of_queueing(pg_dsn: str) -> None:
    """The FKs need SHARE ROW EXCLUSIVE on `exchange_accounts`, which an open writer blocks; the
    5 s `lock_timeout` bounds that wait and the failed upgrade leaves the database at 0037."""
    with _conn(pg_dsn) as c:
        _reset(c)
        try:
            _ok(pg_dsn, "downgrade", _PREV)
            with _conn(pg_dsn) as holder, holder.transaction():
                holder.execute("LOCK TABLE exchange_accounts IN ROW EXCLUSIVE MODE")
                refused = _alembic(pg_dsn, "upgrade", _REV)
            assert refused.returncode != 0, "a held exchange_accounts lock must stop the upgrade"
            assert "lock timeout" in refused.stderr, refused.stderr
            version = c.execute("SELECT version_num FROM alembic_version").fetchone()
            assert version == (_PREV,), "the failed upgrade must leave the database at 0037"
        finally:
            _heal(pg_dsn)


def test_downgrade_gives_up_on_a_reader_lock_instead_of_queueing(pg_dsn: str) -> None:
    """Dropping the tables removes their FK triggers on `users`, which an open reader blocks."""
    with _conn(pg_dsn) as c:
        _reset(c)
        try:
            _ok(pg_dsn, "downgrade", _REV)  # start at this revision, whatever head is later
            with _conn(pg_dsn) as holder, holder.transaction():
                holder.execute("LOCK TABLE users IN ACCESS SHARE MODE")
                refused = _alembic(pg_dsn, "downgrade", _PREV)
            assert refused.returncode != 0, "a held users lock must stop the downgrade"
            assert "lock timeout" in refused.stderr, refused.stderr
            version = c.execute("SELECT version_num FROM alembic_version").fetchone()
            assert version == (_REV,), "the failed downgrade must leave the database at 0038"
        finally:
            _heal(pg_dsn)


# --- Every invalid row is rejected by its NAMED constraint (SQLSTATE 23514) ---------------------

_LONG = "x" * 281
_AT = "2026-10-20T10:00Z"
_EARLIER, _LATER, _END = "2026-10-20T09:59Z", "2026-10-20T11:00Z", "2026-10-20T12:00Z"


@pytest.mark.parametrize(
    ("cols", "constraint"),
    [
        pytest.param({"reason": "drawdown"}, "rl_reason", id="reason-unknown"),
        pytest.param(
            {"reason": "manual", "since": _AT, "until": _END}, "rl_manual", id="manual-end"
        ),
        pytest.param({"since": _AT, "until": _AT}, "rl_until", id="until-not-after-since"),
        pytest.param({"release_reason": "no release"}, "rl_release", id="reason-without-release"),
        pytest.param({"since": _AT, "released_at": _LATER}, "rl_release", id="release-without-end"),
        pytest.param(
            {"since": _AT, "until": _END, "released_at": _LATER}, "rl_release", id="early-clock"
        ),
        pytest.param({"threshold": "NaN"}, "rl_numbers", id="threshold-nan"),
        pytest.param({"actual_value": "NaN"}, "rl_numbers", id="actual-value-nan"),
        pytest.param({"actions_taken": Jsonb([])}, "rl_actions", id="actions-not-an-object"),
    ],
)
def test_invalid_lockout_is_rejected_by_its_named_constraint(
    pg_dsn: str, cols: dict[str, object], constraint: str
) -> None:
    with _conn(pg_dsn) as c, pytest.raises(pgerr.CheckViolation) as exc:
        _lockout(c, **cols)
    assert exc.value.diag.sqlstate == "23514"
    assert exc.value.diag.constraint_name == constraint


@pytest.mark.parametrize(
    ("cols", "constraint"),
    [
        pytest.param(
            {"released_at": _EARLIER, "release_reason": "drill"}, "rl_released", id="early"
        ),
        pytest.param({"released_at": _LATER}, "rl_release", id="releaser-without-reason"),
        pytest.param({"released_at": _LATER, "release_reason": "ab"}, "rl_text", id="too-short"),
        pytest.param({"released_at": _LATER, "release_reason": _LONG}, "rl_text", id="too-long"),
        pytest.param({"released_at": _LATER, "release_reason": " \t "}, "rl_text", id="blank"),
        pytest.param({"released_at": _LATER, "release_reason": "  ab"}, "rl_text", id="padded"),
        pytest.param(
            {"released_at": _LATER, "release_reason": "\t\r\n\t"}, "rl_text", id="tabs-and-breaks"
        ),
    ],
)
def test_a_persons_release_is_checked_by_its_named_constraint(
    pg_dsn: str, cols: dict[str, object], constraint: str
) -> None:
    with _conn(pg_dsn) as c, pytest.raises(pgerr.CheckViolation) as exc:
        _lockout(c, since=_AT, released_by=_user(c), **cols)
    assert exc.value.diag.constraint_name == constraint


def test_released_by_without_a_release_time_is_rejected(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c, pytest.raises(pgerr.CheckViolation) as exc:
        _lockout(c, released_by=_user(c))
    assert exc.value.diag.constraint_name == "rl_release"


def test_the_three_release_shapes_are_accepted(pg_dsn: str) -> None:
    """Active (nothing set), a person's release, and the clock's at or after the stored end."""
    with _conn(pg_dsn) as c:
        _lockout(c)
        _lockout(c, since=_AT, released_at=_LATER, released_by=_user(c), release_reason="abc")
        _lockout(c, since=_AT, until=_END, released_at=_END)
        manual = {"reason": "manual", "since": _AT, "released_at": _LATER}
        _lockout(c, **manual, released_by=_user(c), release_reason="x" * 280)


@pytest.mark.parametrize(
    ("column", "value", "constraint"),
    [
        ("singleton", False, "rp_singleton"),
        ("max_total_notional_usd", -1, "rp_money"),
        ("max_daily_loss_usd", -0.01, "rp_money"),
        ("override_extra_loss_max_usd", -1, "rp_money"),
        ("max_total_notional_usd", "NaN", "rp_money"),
        ("max_daily_loss_usd", "NaN", "rp_money"),
        ("override_extra_loss_max_usd", "NaN", "rp_money"),
        ("max_drawdown_pct", 100.5, "rp_pct"),
        ("per_symbol_concentration_pct", -1, "rp_pct"),
        ("max_open_positions", 101, "rp_positions"),
        ("max_open_positions", -1, "rp_positions"),
        ("max_leverage", 0.5, "rp_leverage"),
        ("max_leverage", 101, "rp_leverage"),
        ("max_orders_per_minute", 900, "rp_orders"),
        ("max_orders_per_minute", 0, "rp_orders"),
        ("lockout_minutes_default", 1441, "rp_lockout"),
        ("lockout_minutes_default", -1, "rp_lockout"),
        ("day_boundary_utc_offset_minutes", 841, "rp_day"),
        ("day_boundary_utc_offset_minutes", -721, "rp_day"),
        ("breach_behaviour", Jsonb([]), "rp_behaviour"),
        ("breach_behaviour", Jsonb({}), "rp_behaviour"),
        ("breach_behaviour", Jsonb({**_EVERY_BLOCK, "not_a_limit": "warn"}), "rp_behaviour"),
        ("breach_behaviour", Jsonb(dict.fromkeys(_LIMITS[1:], "block")), "rp_behaviour"),
        ("breach_behaviour", Jsonb({**_EVERY_BLOCK, "max_leverage": "explode"}), "rp_behaviour"),
        ("breach_behaviour", Jsonb({**_EVERY_BLOCK, "max_leverage": 1}), "rp_behaviour"),
        ("breach_behaviour", Jsonb({**_EVERY_BLOCK, "max_leverage": ["warn"]}), "rp_behaviour"),
        ("breach_behaviour", Jsonb({**_EVERY_BLOCK, "max_leverage": []}), "rp_behaviour"),
        (
            "breach_behaviour",
            Jsonb({**_EVERY_BLOCK, "max_leverage": {"a": "warn"}}),
            "rp_behaviour",
        ),
    ],
)
def test_out_of_bounds_policy_is_rejected_by_its_named_constraint(
    pg_dsn: str, column: str, value: object, constraint: str
) -> None:
    stmt = sql.SQL("UPDATE risk_policy SET {} = %s").format(sql.Identifier(column))
    with _conn(pg_dsn) as c, pytest.raises(pgerr.CheckViolation) as exc:
        c.execute(stmt, (value,))
    assert exc.value.diag.sqlstate == "23514"
    assert exc.value.diag.constraint_name == constraint


def test_policy_bounds_are_inclusive_and_every_behaviour_is_accepted(pg_dsn: str) -> None:
    edges = {
        "max_total_notional_usd": (0,),
        "override_extra_loss_max_usd": (0,),
        "max_drawdown_pct": (0, 100),
        "max_open_positions": (0, 100),
        "max_leverage": (1, 100),
        "max_orders_per_minute": (1, 600),
        "lockout_minutes_default": (0, 1440),
        "day_boundary_utc_offset_minutes": (-720, 840),
    }
    with _conn(pg_dsn) as c, c.transaction():
        for column, values in edges.items():
            stmt = sql.SQL("UPDATE risk_policy SET {} = %s").format(sql.Identifier(column))
            for value in values:
                c.execute(stmt, (value,))
        for behaviour in ("warn", "block", "flatten"):
            every = Jsonb(dict.fromkeys(_LIMITS, behaviour))
            c.execute("UPDATE risk_policy SET breach_behaviour = %s", (every,))
        raise psycopg.Rollback


@pytest.mark.parametrize(
    ("cols", "constraint"),
    [
        pytest.param({"scope": "symbol"}, "kss_scope", id="scope-unknown"),
        pytest.param({"exchange_account_id": None}, "kss_target", id="accounts-without-account"),
        pytest.param({"engaged": True, "reason": "freeze"}, "kss_engaged", id="engaged-no-time"),
        pytest.param({"engaged": True, "engaged_at": _AT}, "kss_engaged", id="engaged-no-reason"),
        pytest.param({"reason": "ab"}, "kss_reason", id="reason-too-short"),
        pytest.param({"reason": "   "}, "kss_reason", id="reason-blank"),
        pytest.param({"reason": " ab "}, "kss_reason", id="reason-padded"),
        pytest.param({"reason": "\t\n\t"}, "kss_reason", id="reason-tabs-and-breaks"),
        pytest.param({"reason": _LONG}, "kss_reason", id="reason-too-long"),
        pytest.param({"options": Jsonb([])}, "kss_options", id="options-not-an-object"),
    ],
)
def test_invalid_switch_row_is_rejected_by_its_named_constraint(
    pg_dsn: str, cols: dict[str, object], constraint: str
) -> None:
    with _conn(pg_dsn) as c, pytest.raises(pgerr.CheckViolation) as exc:
        _switch(c, **cols)
    assert exc.value.diag.sqlstate == "23514"
    assert exc.value.diag.constraint_name == constraint


def test_a_global_row_naming_an_account_is_rejected(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c, pytest.raises(pgerr.CheckViolation) as exc:
        _switch(c, scope="global", exchange_account_id=_account(c))
    assert exc.value.diag.constraint_name == "kss_target"


# --- One active lockout per (account, manager), one row per policy and per switch target -------


@pytest.mark.parametrize("manager", [False, True], ids=["account-wide", "one-manager"])
def test_a_second_active_lockout_for_the_same_pair_is_refused(pg_dsn: str, manager: bool) -> None:
    with _conn(pg_dsn) as c:
        account = _account(c)
        user = _user(c) if manager else None
        _lockout(c, account, user_id=user)
        with pytest.raises(pgerr.UniqueViolation) as exc:
            _lockout(c, account, user_id=user, reason="max_positions")
    assert exc.value.diag.sqlstate == "23505"
    assert exc.value.diag.constraint_name == "ux_risk_lockout_active"


def test_released_lockouts_and_other_managers_do_not_count_as_active(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        account = _account(c)
        _lockout(c, account, since=_AT, until=_END, released_at=_END)
        _lockout(c, account)  # the released row no longer holds the pair
        _lockout(c, account, user_id=_user(c))  # a manager's lockout is a pair of its own
        _lockout(c, account, user_id=_user(c))


def test_a_second_policy_row_is_refused(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c, pytest.raises(pgerr.UniqueViolation) as exc:
        every = Jsonb(dict.fromkeys(_LIMITS, "block"))
        row = {"id": str(uuid.uuid4()), **dict.fromkeys(_LIMITS, 1), "breach_behaviour": every}
        _insert(c, "risk_policy", row)
    assert exc.value.diag.constraint_name == "risk_policy_singleton_key"


@pytest.mark.parametrize("scope", ["global", "accounts"])
def test_a_second_switch_row_for_one_target_is_refused(pg_dsn: str, scope: str) -> None:
    with _conn(pg_dsn) as c:
        target: dict[str, object] = {"scope": scope}
        if scope == "accounts":
            target["exchange_account_id"] = _account(c)
            _switch(c, **target)
        with pytest.raises(pgerr.UniqueViolation) as exc:
            _switch(c, **target)  # the seed already holds the global row
    assert exc.value.diag.constraint_name == "ux_kill_switch_state_scope"


# --- Delete rules: risk history pins its account, its manager and its actors ------------------


def test_an_account_or_a_manager_with_risk_history_cannot_be_hard_deleted(pg_dsn: str) -> None:
    with _conn(pg_dsn) as c:
        _active_owner(c)
        account, manager = _account(c), _user(c)
        _lockout(c, account, user_id=manager)
        with pytest.raises(pgerr.ForeignKeyViolation) as exc:
            c.execute("DELETE FROM exchange_accounts WHERE id = %s", (account,))
        assert exc.value.diag.constraint_name == "risk_lockouts_exchange_account_id_fkey"
        with pytest.raises(pgerr.ForeignKeyViolation) as exc:
            c.execute("DELETE FROM users WHERE id = %s", (manager,))
        assert exc.value.diag.constraint_name == "risk_lockouts_user_id_fkey"


@pytest.mark.parametrize(
    "fk",
    [
        "risk_lockouts_released_by_fkey",
        "kill_switch_state_engaged_by_fkey",
        "risk_policy_updated_by_fkey",
    ],
)
def test_an_actor_of_risk_history_cannot_be_hard_deleted(pg_dsn: str, fk: str) -> None:
    """A NULL actor means "the system" or "never owner-confirmed", never "deleted"."""
    with _conn(pg_dsn) as c:
        _reset(c)
        _active_owner(c)
        actor = _user(c)
        if fk.startswith("risk_lockouts"):
            _lockout(c, since=_AT, released_at=_LATER, released_by=actor, release_reason="drill")
        elif fk.startswith("kill_switch_state"):
            _switch(c, engaged=True, engaged_at=_AT, engaged_by=actor, reason="drill")
        else:
            c.execute("UPDATE risk_policy SET updated_by = %s", (actor,))
        try:
            with pytest.raises(pgerr.ForeignKeyViolation) as exc:
                c.execute("DELETE FROM users WHERE id = %s", (actor,))
            assert exc.value.diag.constraint_name == fk
        finally:
            _reset(c)
