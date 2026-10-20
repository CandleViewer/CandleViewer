"""`0038_risk_state` (E39-T02 #882): offline render, plan-doc parity, models.

Real-Postgres behaviour (named-constraint rejection with its SQLSTATE, the unique indexes, the
delete rules, the seed, the downgrade guard, the round trip and the lock bounds) is covered by
`tests/integration/storage/test_risk_state_migration.py`.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Numeric,
    SmallInteger,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.schema import DefaultClause

from candleviewer.db import models
from candleviewer.risk import KillSwitchScope, LockoutReason, RiskRefusal
from candleviewer.risk.models import Reason

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_DOC24 = _ROOT.parents[1] / "docs" / "plan" / "24-internal-schemas.md"
_REV, _PREV = "0038_risk_state", "0037_account_profiles"
_UP, _DOWN = f"{_PREV}:{_REV}", f"{_REV}:{_PREV}"
_TABLES = ("risk_lockouts", "risk_policy", "kill_switch_state")


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#882)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments and collapse whitespace so layout never matters."""
    return " ".join(re.sub(r"--[^\n]*", "", sql).split())


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", _UP, "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", _DOWN, "--sql"))


def _doc_block(n: int) -> str:
    """Sec.3.11's n-th ```sql block (1: the tables, 2: the seed), to its fence."""
    section = _DOC.read_text(encoding="utf-8").split("### 3.11 Risk state", 1)[1]
    return section.split("```sql", n)[n].split("```", 1)[0]


def _doc_checks(table: str) -> dict[str, str]:
    """`CONSTRAINT <name> CHECK (<body>)` of one Sec.3.11 table, balanced parentheses."""
    ddl = _norm(_doc_block(1)).split(f"CREATE TABLE {table} (", 1)[1].split(");", 1)[0]
    out: dict[str, str] = {}
    for match in re.finditer(r"CONSTRAINT (\w+) CHECK \(", ddl):
        depth, end = 1, match.end()
        while depth:
            depth += {"(": 1, ")": -1}.get(ddl[end], 0)
            end += 1
        out[match.group(1)] = ddl[match.end() : end - 1]
    return out


def test_revision_chains_onto_0037() -> None:
    history = _alembic("history", "-r", _UP)
    assert f"{_PREV} -> {_REV}" in history, f"0038 must revise 0037, got: {history}"


def test_upgrade_ddl_and_seed_are_the_plan_doc_blocks_verbatim() -> None:
    ddl, seed = _norm(_doc_block(1)), _norm(_doc_block(2))
    assert ddl.startswith("CREATE TABLE risk_lockouts ("), "Sec.3.11's DDL block moved"
    assert ddl.endswith("(scope, exchange_account_id) NULLS NOT DISTINCT;"), "block cut short"
    assert seed.startswith("INSERT INTO risk_policy (") and seed.endswith("'global', false);")
    sql = _up()
    assert ddl in sql, "the upgrade DDL has drifted from Sec.3.11 (comments and layout aside)"
    assert seed in sql, "the upgrade seed has drifted from Sec.3.11"
    assert sql.index(ddl) < sql.index(seed), "the tables precede their seed"


def test_upgrade_ships_only_the_three_tables_their_seed_and_the_delete_revoke() -> None:
    """Sec.3.11 and nothing else: no trigger, type, grant, audit or system_events write; the one
    REVOKE takes DELETE from `cv_app` on the three tables, only where the role exists."""
    sql = _up()
    assert sql.count("CREATE TABLE ") == 3, "tables"
    assert sql.count("CREATE UNIQUE INDEX ") == 2 and sql.count("CREATE INDEX ") == 0, "indexes"
    assert sql.count("INSERT INTO ") == 2 and sql.count("COMMENT ON COLUMN ") == 1, "seed, tags"
    revoke = (
        "IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN EXECUTE 'REVOKE DELETE "
        "ON risk_lockouts, risk_policy, kill_switch_state FROM cv_app'; END IF;"
    )
    assert sql.count("REVOKE ") == 1 and revoke in sql, "DELETE is revoked once, role-guarded"
    for absent in ("CREATE TRIGGER", "CREATE TYPE", "GRANT ", "audit_log", "system_events"):
        assert absent not in sql, f"{absent!r} is outside this revision's scope"


def test_upgrade_bounds_every_lock_with_lock_timeout() -> None:
    """C-5.6: the FKs lock `exchange_accounts` and `users`; every statement sits inside 5 s."""
    sql = _up()
    opened = sql.index("SET LOCAL lock_timeout = '5s';")
    assert opened < sql.index("CREATE TABLE risk_lockouts"), "the bound opens before the first FK"
    assert sql.rindex("INSERT INTO kill_switch_state") < sql.index(
        "SET LOCAL lock_timeout = DEFAULT;"
    ), "the bound must stay open until the seed is written"


def test_downgrade_locks_refuses_beyond_the_seed_then_drops_every_table() -> None:
    sql = _down()
    steps = [
        "SET LOCAL lock_timeout = '5s';",
        "LOCK TABLE risk_lockouts, risk_policy, kill_switch_state IN SHARE MODE;",
        "IF EXISTS (SELECT 1 FROM risk_lockouts)",
        "WHERE scope <> 'global' OR engaged OR engaged_at IS NOT NULL)",
        "OR EXISTS (SELECT 1 FROM risk_policy WHERE updated_by IS NOT NULL) THEN",
        "RAISE EXCEPTION '0038_risk_state downgrade refused",
        "DROP TABLE kill_switch_state;",
        "DROP TABLE risk_policy;",
        "DROP TABLE risk_lockouts;",
        "SET LOCAL lock_timeout = DEFAULT;",
    ]
    positions = [sql.index(step) for step in steps]
    order = dict(zip(steps, positions, strict=True))
    assert positions == sorted(positions), f"steps out of order: {order}"


def _default(column: Column[Any]) -> str | None:
    default = column.server_default
    if default is None:
        return None
    assert isinstance(default, DefaultClause)
    return str(default.arg)


_UTC = TIMESTAMP
_COLUMNS: dict[str, list[tuple[str, bool, str | None, type]]] = {
    # (name, nullable, server_default, type) in DDL order (Sec.3.11).
    "risk_lockouts": [
        ("id", False, None, UUID),
        ("exchange_account_id", False, None, UUID),
        ("user_id", True, None, UUID),
        ("reason", False, None, Text),
        ("threshold", True, None, Numeric),
        ("actual_value", True, None, Numeric),
        ("since", False, "now()", _UTC),
        ("until", True, None, _UTC),
        ("released_at", True, None, _UTC),
        ("released_by", True, None, UUID),
        ("release_reason", True, None, Text),
        ("actions_taken", False, "'{}'::jsonb", JSONB),
    ],
    "risk_policy": [
        ("id", False, None, UUID),
        ("singleton", False, "true", Boolean),
        ("max_total_notional_usd", False, None, Numeric),
        ("max_daily_loss_usd", False, None, Numeric),
        ("max_drawdown_pct", False, None, Numeric),
        ("max_open_positions", False, None, SmallInteger),
        ("max_leverage", False, None, Numeric),
        ("max_orders_per_minute", False, None, SmallInteger),
        ("per_symbol_concentration_pct", False, None, Numeric),
        ("override_extra_loss_max_usd", False, "0", Numeric),
        ("breach_behaviour", False, None, JSONB),
        ("lockout_minutes_default", False, "60", SmallInteger),
        ("block_trading_when_degraded", False, "true", Boolean),
        ("day_boundary_utc_offset_minutes", False, "0", SmallInteger),
        ("updated_by", True, None, UUID),
        ("updated_at", False, "now()", _UTC),
    ],
    "kill_switch_state": [
        ("id", False, None, UUID),
        ("scope", False, None, Text),
        ("exchange_account_id", True, None, UUID),
        ("engaged", False, None, Boolean),
        ("engaged_at", True, None, _UTC),
        ("engaged_by", True, None, UUID),
        ("reason", True, None, Text),
        ("options", False, "'{}'::jsonb", JSONB),
        ("updated_at", False, "now()", _UTC),
    ],
}


def _table(name: str) -> Table:
    table = models.metadata.tables[name]
    assert isinstance(table, Table)
    return table


def test_models_mirror_the_columns_of_the_three_tables() -> None:
    """The `migrations` job autogenerate-diffs the DB against `db.models.metadata`."""
    for name, columns in _COLUMNS.items():
        table = _table(name)
        assert [(c.name, c.nullable, _default(c)) for c in table.columns] == [
            (col, nullable, default) for col, nullable, default, _ in columns
        ], name
        assert [c.name for c in table.primary_key.columns] == ["id"]
        for col, _, _, kind in columns:
            column_type = table.c[col].type
            assert isinstance(column_type, kind), f"{name}.{col}"
            if isinstance(column_type, TIMESTAMP):
                assert column_type.timezone is True, f"{name}.{col}"
    money = {
        ("risk_lockouts", "threshold"): (38, 18),
        ("risk_lockouts", "actual_value"): (38, 18),
        ("risk_policy", "max_total_notional_usd"): (38, 18),
        ("risk_policy", "max_daily_loss_usd"): (38, 18),
        ("risk_policy", "override_extra_loss_max_usd"): (38, 18),
        ("risk_policy", "max_drawdown_pct"): (9, 6),
        ("risk_policy", "per_symbol_concentration_pct"): (9, 6),
        ("risk_policy", "max_leverage"): (10, 2),
    }
    for (name, col), scale in money.items():
        column_type = _table(name).c[col].type
        assert isinstance(column_type, Numeric)
        assert (column_type.precision, column_type.scale) == scale, f"{name}.{col}"


def test_models_mirror_the_foreign_keys_and_their_delete_rules() -> None:
    fks = {
        (table, fk.parent.name, fk.column.table.name, fk.ondelete)
        for table in _TABLES
        for fk in _table(table).foreign_keys
    }
    assert fks == {
        ("risk_lockouts", "exchange_account_id", "exchange_accounts", "RESTRICT"),
        ("risk_lockouts", "user_id", "users", "RESTRICT"),
        ("risk_lockouts", "released_by", "users", "RESTRICT"),
        ("risk_policy", "updated_by", "users", "RESTRICT"),
        ("kill_switch_state", "exchange_account_id", "exchange_accounts", "RESTRICT"),
        ("kill_switch_state", "engaged_by", "users", "RESTRICT"),
    }


def test_models_mirror_the_plan_doc_checks_uniques_and_indexes() -> None:
    """`alembic check` never diffs CHECK bodies, so they are pinned against Sec.3.11 here."""
    for name in _TABLES:
        table = _table(name)
        checks = {
            # CHECK names get the metadata naming-convention prefix (`ck_<table>_`).
            str(c.name).removeprefix(f"ck_{name}_"): " ".join(str(c.sqltext).split())
            for c in table.constraints
            if isinstance(c, CheckConstraint)
        }
        assert checks == _doc_checks(name), name
    uniques = [c for c in _table("risk_policy").constraints if isinstance(c, UniqueConstraint)]
    # Postgres's own name for the inline `singleton ... UNIQUE`, so autogenerate sees no rename.
    assert [(str(c.name), [col.name for col in c.columns]) for c in uniques] == [
        ("risk_policy_singleton_key", ["singleton"])
    ]
    ix = {str(i.name): i for name in _TABLES for i in _table(name).indexes}
    assert set(ix) == {"ux_risk_lockout_active", "ux_kill_switch_state_scope"}
    active, scope = ix["ux_risk_lockout_active"], ix["ux_kill_switch_state_scope"]
    assert [c.name for c in active.columns] == ["exchange_account_id", "user_id"]
    assert [c.name for c in scope.columns] == ["scope", "exchange_account_id"]
    assert str(active.dialect_options["postgresql"]["where"]) == "released_at IS NULL"
    assert scope.dialect_options["postgresql"]["where"] is None
    for index in (active, scope):
        assert index.unique and index.dialect_options["postgresql"]["nulls_not_distinct"] is True


def test_models_tag_actual_value_with_the_revisions_pii_comment() -> None:
    comment = _table("risk_lockouts").c.actual_value.comment
    assert comment == models.RISK_LOCKOUT_ACTUAL_VALUE_COMMENT
    assert f"COMMENT ON COLUMN risk_lockouts.actual_value IS '{comment}';" in _up()
    tagged = [(t, c.name) for t in _TABLES for c in _table(t).columns if c.comment]
    assert tagged == [("risk_lockouts", "actual_value")], "Sec.12 lists no other column"


def test_the_refusal_codes_match_their_plan_doc_row() -> None:
    """`RiskRefusal` has no table, so its 24 section 8.11 row pins it, in the row's order."""
    rows = _DOC24.read_text(encoding="utf-8").splitlines()
    row = next(line for line in rows if line.startswith("| `RiskRefusal`"))
    assert re.findall(r"`(\w+)`", row.split("|")[2]) == [code.value for code in RiskRefusal]


def test_the_domain_enums_and_reason_bounds_match_the_plan_doc_checks() -> None:
    """The models refuse what the tables refuse: enums equal the IN-lists, `Reason` the bounds."""
    lockouts, switches = _doc_checks("risk_lockouts"), _doc_checks("kill_switch_state")
    assert set(re.findall(r"'(\w+)'", lockouts["rl_reason"])) == {r.value for r in LockoutReason}
    assert set(re.findall(r"'(\w+)'", switches["kss_scope"])) == {s.value for s in KillSwitchScope}
    reason = TypeAdapter(Reason)
    for check in (lockouts["rl_text"], switches["kss_reason"]):
        longest = int(re.findall(r"<= (\d+)", check)[0])
        shortest = int(re.findall(r">= (\d+)", check)[0])
        assert reason.validate_python("x" * longest) and reason.validate_python("x" * shortest)
        for refused in ("x" * (longest + 1), "x" * (shortest - 1), " " * shortest):
            with pytest.raises(ValidationError):
                reason.validate_python(refused)
