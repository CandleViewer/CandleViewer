"""`0039_trade_groups` (E28-T01 #905): offline render, plan-doc parity, the integrity triggers and
their guards, the deferred foreign keys, the grants, the PII comments, the downgrade guard and the
model mirror. Real Postgres: `tests/integration/storage/test_trade_groups_migration.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid
from collections.abc import Callable
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from sqlalchemy import CheckConstraint, Column, Index, Numeric, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import DOMAIN, ENUM
from sqlalchemy.schema import DefaultClause

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0039_trade_groups", "0038_risk_state"
_UP, _DOWN = f"{_PREV}:{_REV}", f"{_REV}:{_PREV}"
_GROUPS = "3.3.2 `trade_groups`"
_LEGS = "3.3.3 `trade_group_legs`"
_DEFINITIONS = "3.3.3a `trade_group_definitions` and `trade_group_definition_members`"
_TABLES = {
    t.name: t
    for t in (
        models.trade_group_definitions,
        models.trade_group_definition_members,
        models.trade_groups,
        models.trade_group_legs,
    )
}
#: (heading, n-th ```sql block under it): each section's tables, then its triggers.
_BLOCKS = (
    (_GROUPS, 0),
    (_GROUPS, 1),
    (_LEGS, 0),
    (_LEGS, 1),
    (_DEFINITIONS, 0),
    (_DEFINITIONS, 1),
)
_BLOCK_IDS = ["groups", "group-triggers", "legs", "leg-triggers", "definitions", "guards"]


class _Guard(NamedTuple):
    """One integrity trigger: its function, the table it sits on, when it fires and the tables
    its function reads (schema-qualified in the body)."""

    function: str
    trigger: str
    table: str
    when: str
    reads: tuple[str, ...]


#: The eight integrity triggers, in the order the revision creates them.
_GUARDS = (
    _Guard(
        "tg_env_check", "trg_tg_env", "trade_groups", "BEFORE INSERT", ("trade_group_definitions",)
    ),
    _Guard("tg_write_once", "trg_tg_write_once", "trade_groups", "BEFORE UPDATE", ()),
    _Guard(
        "tgl_env_check",
        "trg_tgl_env",
        "trade_group_legs",
        "BEFORE INSERT OR UPDATE OF trade_group_id, exchange_account_id",
        ("trade_groups", "exchange_accounts"),
    ),
    _Guard(
        "tgl_profile_check",
        "trg_tgl_profile",
        "trade_group_legs",
        "BEFORE INSERT",
        ("account_profiles",),
    ),
    _Guard(
        "tgl_write_once",
        "trg_tgl_write_once",
        "trade_group_legs",
        "BEFORE UPDATE",
        ("account_profiles",),
    ),
    _Guard("tgd_write_once", "trg_tgd_write_once", "trade_group_definitions", "BEFORE UPDATE", ()),
    _Guard(
        "tgdm_env_check",
        "trg_tgdm_env",
        "trade_group_definition_members",
        "BEFORE INSERT OR UPDATE OF definition_id, exchange_account_id",
        ("trade_group_definitions", "exchange_accounts"),
    ),
    _Guard(
        "ea_env_in_use_check",
        "trg_ea_env_in_use",
        "exchange_accounts",
        "BEFORE UPDATE OF env",
        ("trade_group_definition_members", "trade_group_legs"),
    ),
)
_GUARD_IDS = [g.trigger for g in _GUARDS]
#: The write-once triggers and the columns each one freezes, in the order its CASE tests them.
_WRITE_ONCE = {
    "trg_tg_write_once": (
        "id",
        "env",
        "created_by",
        "client_group_ref",
        "client_body_sha256",
        "definition_id",
    ),
    "trg_tgl_write_once": (
        "id",
        "trade_group_id",
        "exchange_account_id",
        "profile_version",
        "profile_snapshot",
        "account_profile_id",
    ),
    "trg_tgd_write_once": ("id", "env"),
}
_WRITE_ONCE_GUARDS = [g for g in _GUARDS if g.trigger in _WRITE_ONCE]
_WRITE_ONCE_IDS = [g.trigger for g in _WRITE_ONCE_GUARDS]
_CHECK_GUARDS = [g for g in _GUARDS if g.trigger not in _WRITE_ONCE]
_CHECK_IDS = [g.trigger for g in _CHECK_GUARDS]
#: The four `updated_at` bookkeeping triggers, the only ones not always enabled.
_TOUCH = (
    ("trg_trade_groups_touch", "trade_groups"),
    ("trg_trade_group_legs_touch", "trade_group_legs"),
    ("trg_trade_group_definitions_touch", "trade_group_definitions"),
    ("trg_trade_group_definition_members_touch", "trade_group_definition_members"),
)
#: (table, column, referenced table): the keys 0013 and 0029 deferred to this revision.
_LEG_FKS = (
    ("orders", "trade_group_leg_id", "trade_group_legs"),
    ("executions", "trade_group_leg_id", "trade_group_legs"),
    ("rule_runs", "trade_group_id", "trade_groups"),
)
_LOCK_ON, _LOCK_OFF = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
#: `RAISE EXCEPTION '<message>' <arguments and USING clause>;` of a trigger function body.
_RAISE = re.compile(r"RAISE EXCEPTION '([^']*)'([^;]*);")
#: Any statement that changes the schema, grants or locks: none may run outside the lock bracket.
_DDL = re.compile(r"\b(?:CREATE|ALTER|DROP|DO|COMMENT|REVOKE|LOCK)\b")
#: The pre-flight condition and the start of its refusal, as rendered.
_PREFLIGHT = (
    "IF EXISTS (SELECT 1 FROM orders WHERE trade_group_leg_id IS NOT NULL) "
    "OR EXISTS (SELECT 1 FROM executions WHERE trade_group_leg_id IS NOT NULL) "
    "OR EXISTS (SELECT 1 FROM rule_runs WHERE trade_group_id IS NOT NULL) THEN "
    "RAISE EXCEPTION '0039_trade_groups upgrade refused: "
)


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#905)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments and collapse whitespace, and the space inside a bracket, so layout
    never matters."""
    flat = " ".join(re.sub(r"--[^\n]*", "", sql).split())
    return flat.replace("( ", "(").replace(" )", ")")


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", _UP, "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", _DOWN, "--sql"))


@cache
def _section(heading: str) -> str:
    """`#### <heading>` of 21-database-schema.md, to the next heading."""
    section = _DOC.read_text(encoding="utf-8").split(f"#### {heading}", 1)[1]
    return re.split(r"\n#{1,4} ", section, maxsplit=1)[0]


def _doc_block(heading: str, index: int) -> str:
    return _section(heading).split("```sql")[index + 1].split("```", 1)[0]


def _doc_table(name: str) -> str:
    """One `CREATE TABLE <name> (...);` of the doc, raw (comments kept)."""
    text = "\n".join(_doc_block(h, i) for h, i in _BLOCKS)
    return text.split(f"CREATE TABLE {name} (", 1)[1].split("\n);", 1)[0]


def _in_order(sql: str, steps: list[str]) -> bool:
    missing = [step for step in steps if step not in sql]
    assert not missing, f"not in the rendered SQL: {missing}"
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def _function(name: str) -> str:
    """`CREATE FUNCTION <name>()` of the upgrade, from its `RETURNS` to its closing `END`."""
    return _up().split(f"CREATE FUNCTION {name}() ", 1)[1].split("END $BODY$;", 1)[0]


def _fk_name(table: str, column: str) -> str:
    """The name Postgres gives the plan's inline `REFERENCES` (`<table>_<column>_fkey`)."""
    return f"{table}_{column}_fkey"


def test_revision_chains_onto_0038() -> None:
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", _UP)


@pytest.mark.parametrize(
    ("enum", "name"),
    [
        (models.trade_group_status, "trade_group_status"),
        (models.leg_status, "leg_status"),
        (models.algo_kind, "algo_kind"),
    ],
)
def test_upgrade_creates_each_enum_as_the_plan_doc_and_the_model_declare_it(
    enum: ENUM, name: str
) -> None:
    statement = f"CREATE TYPE {name} AS ENUM ({','.join(repr(v) for v in enum.enums)});"
    assert statement in _norm(_DOC.read_text(encoding="utf-8")) and statement in _up()
    assert enum.name == name and enum.create_type is False  # the migration creates and drops it


@pytest.mark.parametrize("heading", [_GROUPS, _LEGS, _DEFINITIONS])
def test_each_plan_doc_section_has_exactly_the_two_sql_fences_the_revision_ships(
    heading: str,
) -> None:
    """The verbatim test below walks the fences by index: a third one would go unchecked."""
    assert _section(heading).count("```sql") == 2


@pytest.mark.parametrize(("heading", "index"), _BLOCKS, ids=_BLOCK_IDS)
def test_upgrade_ddl_is_the_plan_doc_ddl_verbatim(heading: str, index: int) -> None:
    assert _norm(_doc_block(heading, index)) in _up()


def test_upgrade_creates_in_dependency_order_under_a_bounded_lock_wait() -> None:
    """The enums and the definitions exist before the tables that use them, each table before its
    triggers, the pre-flight before the first deferred key, every key added NOT VALID before it is
    validated, and the grants and comments before the lock wait is restored."""
    adds = [f"ALTER TABLE {t} ADD CONSTRAINT {_fk_name(t, c)} " for t, c, _ in _LEG_FKS]
    validates = [f"ALTER TABLE {t} VALIDATE CONSTRAINT {_fk_name(t, c)};" for t, c, _ in _LEG_FKS]
    assert _in_order(
        _up(),
        [
            _LOCK_ON,
            "CREATE TYPE trade_group_status",
            "CREATE TYPE leg_status",
            "CREATE TYPE algo_kind",
            "CREATE TABLE trade_group_definitions (",
            "CREATE TABLE trade_group_definition_members (",
            "CREATE TABLE trade_groups (",
            "CREATE TABLE trade_group_legs (",
            "CREATE FUNCTION tg_env_check()",
            "CREATE TRIGGER trg_trade_groups_touch",
            "CREATE FUNCTION tgl_env_check()",
            "CREATE TRIGGER trg_trade_group_legs_touch",
            "CREATE FUNCTION tgd_write_once()",
            "CREATE TRIGGER trg_ea_env_in_use",
            _PREFLIGHT,
            *adds,
            *validates,
            "REVOKE DELETE ON trade_groups FROM cv_app",
            "COMMENT ON COLUMN trade_groups.requested_qty_value",
            "COMMENT ON COLUMN trade_groups.intent_note",
            _LOCK_OFF,
        ],
    )


@pytest.mark.parametrize("render", [_up, _down], ids=["upgrade", "downgrade"])
def test_nothing_changes_the_schema_outside_the_lock_timeout_bracket(
    render: Callable[[], str],
) -> None:
    """C-5.6: `SET LOCAL lock_timeout = '5s'` is the first statement and its reset the last one
    of the revision; alembic's own `BEGIN`, version stamp and `COMMIT` stay outside."""
    sql = render()
    assert sql.count("SET LOCAL lock_timeout") == 2
    before = sql.split(_LOCK_ON, 1)[0]
    after = sql.split(_LOCK_OFF, 1)[1]
    assert not _DDL.search(before) and not _DDL.search(after)


@pytest.mark.parametrize(("table", "column", "target"), _LEG_FKS, ids=[t for t, _, _ in _LEG_FKS])
def test_upgrade_adds_each_deferred_foreign_key_not_valid_then_validates_it(
    table: str, column: str, target: str
) -> None:
    """0013 and 0029 left these keys to this revision: SET NULL, named as Postgres names an inline
    `REFERENCES`, validated (C-5.6) only after the lock-light `NOT VALID` add."""
    name = _fk_name(table, column)
    add = (
        f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY ({column}) "
        f"REFERENCES {target}(id) ON DELETE SET NULL NOT VALID;"
    )
    validate = f"ALTER TABLE {table} VALIDATE CONSTRAINT {name};"
    assert _up().count(add) == 1 and _up().count(validate) == 1
    assert _in_order(_up(), [_PREFLIGHT, add, validate, _LOCK_OFF])


def test_upgrade_refuses_before_any_foreign_key_when_a_row_already_names_a_group_or_leg() -> None:
    """Nothing can name a group or a leg before they exist, so a dangling id is refused with a
    plain message instead of failing the validation with a less useful one (0022's precedent)."""
    sql = _up()
    first_add = min(sql.index(f"ALTER TABLE {t} ADD CONSTRAINT") for t, _, _ in _LEG_FKS)
    assert sql.count(_PREFLIGHT) == 1 and sql.index(_PREFLIGHT) < first_add
    assert "Clear the dangling ids first'; END IF; END $BODY$;" in sql


def test_upgrade_ships_only_these_objects() -> None:
    sql = _up()
    doc = " ".join(_doc_block(h, i) for h, i in _BLOCKS)
    assert sql.count("CREATE TABLE ") == 4 and sql.count("CREATE TYPE ") == 3
    assert sql.count("CREATE UNIQUE INDEX ") == doc.count("CREATE UNIQUE INDEX ") == 1
    assert sql.count("CREATE INDEX ") == doc.count("CREATE INDEX ") == 11
    assert sql.count("CREATE FUNCTION ") == 8 and sql.count("CREATE TRIGGER ") == 12
    assert sql.count("ENABLE ALWAYS TRIGGER ") == 8 and sql.count("COMMENT ON COLUMN ") == 17
    assert sql.count("ADD CONSTRAINT ") == 3 and sql.count("VALIDATE CONSTRAINT ") == 3
    assert sql.count("REVOKE ") == 3
    for absent in ("GRANT ", "IF NOT EXISTS", "DROP ", "INSERT INTO ", "SECURITY DEFINER"):
        assert absent not in sql


@pytest.mark.parametrize("guard", _GUARDS, ids=_GUARD_IDS)
def test_each_integrity_trigger_fires_on_the_events_the_plan_names(guard: _Guard) -> None:
    create = (
        f"CREATE TRIGGER {guard.trigger} {guard.when} ON {guard.table} "
        f"FOR EACH ROW EXECUTE FUNCTION {guard.function}();"
    )
    assert _in_order(_up(), [f"CREATE FUNCTION {guard.function}() ", create])


@pytest.mark.parametrize("guard", _GUARDS, ids=_GUARD_IDS)
def test_integrity_triggers_fire_under_the_replica_role(guard: _Guard) -> None:
    """`ENABLE ALWAYS`, so `session_replication_role = replica` cannot switch a guard off."""
    enable = f"ALTER TABLE {guard.table} ENABLE ALWAYS TRIGGER {guard.trigger};"
    assert _in_order(_up(), [f"CREATE TRIGGER {guard.trigger} ", enable])


def test_only_the_bookkeeping_touch_triggers_follow_the_replication_role() -> None:
    """`updated_at` bookkeeping keeps the default; every integrity trigger is always enabled."""
    created = re.findall(r"CREATE TRIGGER (\w+) ", _up())
    always = re.findall(r"ENABLE ALWAYS TRIGGER (\w+);", _up())
    assert sorted(always) == sorted(g.trigger for g in _GUARDS)
    assert sorted(set(created) - set(always)) == sorted(trigger for trigger, _ in _TOUCH)


@pytest.mark.parametrize(("trigger", "table"), _TOUCH, ids=[t for t, _ in _TOUCH])
def test_each_bookkeeping_trigger_runs_set_updated_at_before_every_update(
    trigger: str, table: str
) -> None:
    touch = (
        f"CREATE TRIGGER {trigger} BEFORE UPDATE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )
    assert touch in _up() and "updated_at" in _TABLES[table].columns


@pytest.mark.parametrize("guard", _GUARDS, ids=_GUARD_IDS)
def test_every_trigger_function_pins_its_search_path(guard: _Guard) -> None:
    head = f"CREATE FUNCTION {guard.function}() RETURNS trigger LANGUAGE plpgsql "
    assert f"{head}SET search_path = pg_catalog, pg_temp AS $BODY$ " in _up()


def test_no_trigger_function_runs_with_its_owners_rights() -> None:
    """Every check runs as the writer, unlike 0037's one revision writer: no definer here."""
    assert "SECURITY DEFINER" not in _up()


@pytest.mark.parametrize("guard", _GUARDS, ids=_GUARD_IDS)
def test_every_trigger_function_names_the_tables_it_reads_in_full(guard: _Guard) -> None:
    """With `search_path` pinned to `pg_catalog`, an unqualified table would not resolve."""
    tables = re.findall(r"(?<!DISTINCT )\bFROM\s+(\S+)", _function(guard.function))
    assert sorted(tables) == sorted(f"public.{t}" for t in guard.reads)


@pytest.mark.parametrize("guard", _GUARDS, ids=_GUARD_IDS)
def test_every_column_a_trigger_function_references_exists(guard: _Guard) -> None:
    """plpgsql resolves `NEW.x` and `alias.x` only when the trigger first fires, so a typo would
    survive CREATE FUNCTION: check each name against the table it belongs to in the models."""
    body = _function(guard.function)
    own = {c.name for c in models.metadata.tables[guard.table].columns}
    missing = [f"NEW/OLD.{c}" for c in re.findall(r"\b(?:NEW|OLD)\.(\w+)", body) if c not in own]
    for table, alias in re.findall(r"FROM public\.(\w+) (\w+)", body):
        columns = {c.name for c in models.metadata.tables[table].columns}
        missing += [
            f"{table}.{c}" for c in re.findall(rf"\b{alias}\.(\w+)", body) if c not in columns
        ]
    assert missing == []


@pytest.mark.parametrize("guard", _GUARDS, ids=_GUARD_IDS)
def test_every_trigger_function_hands_the_row_back_as_its_only_return(guard: _Guard) -> None:
    """A BEFORE ROW trigger that returns NULL silently drops the write it guards."""
    body = _function(guard.function)
    assert body.count("RETURN ") == 1 and body.rstrip().endswith("RETURN NEW;")


@pytest.mark.parametrize("guard", _CHECK_GUARDS, ids=_CHECK_IDS)
def test_a_check_trigger_refuses_under_its_own_name_and_never_prints_a_value(
    guard: _Guard,
) -> None:
    """SQLSTATE 23514 with the trigger as the constraint; the message is a fixed sentence."""
    body = _function(guard.function)
    refusals = _RAISE.findall(body)
    assert len(refusals) == 1 and body.count("RAISE ") == 1
    ((message, rest),) = refusals
    assert message.startswith(f"{guard.trigger}: ") and "%" not in message
    assert rest == f" USING ERRCODE = 'check_violation', CONSTRAINT = '{guard.trigger}'"


@pytest.mark.parametrize("guard", _WRITE_ONCE_GUARDS, ids=_WRITE_ONCE_IDS)
def test_a_write_once_trigger_prints_only_the_name_of_the_column_that_changed(
    guard: _Guard,
) -> None:
    """The one `%` is filled from `changed`, which holds a column name literal and no value."""
    body = _function(guard.function)
    assert body.count("changed :=") == 1
    assert "IF changed IS NOT NULL THEN RAISE EXCEPTION '" in body  # only when a column changed
    refusals = _RAISE.findall(body)
    assert len(refusals) == 1 and body.count("RAISE ") == 1
    ((message, rest),) = refusals
    assert message == f"{guard.trigger}: {guard.table}.% is write-once"
    assert rest == f", changed USING ERRCODE = 'check_violation', CONSTRAINT = '{guard.trigger}'"


def _write_once_arms(function: str) -> list[tuple[str, str]]:
    """`(condition, column)` of every WHEN arm of the function's `changed := CASE`."""
    case = _function(function).split("changed := CASE ", 1)[1].split(" END; ", 1)[0]
    assert " ELSE " not in case  # nothing changed leaves `changed` NULL
    return re.findall(r"WHEN (.+?) THEN '(\w+)'", case)


@pytest.mark.parametrize("guard", _WRITE_ONCE_GUARDS, ids=_WRITE_ONCE_IDS)
def test_a_write_once_trigger_names_exactly_its_columns_and_compares_them_null_safely(
    guard: _Guard,
) -> None:
    columns = _WRITE_ONCE[guard.trigger]
    arms = _write_once_arms(guard.function)
    assert [column for _, column in arms] == list(columns)
    assert set(columns) <= {c.name for c in _TABLES[guard.table].columns}
    plain = [(cond, column) for cond, column in arms if column != "account_profile_id"]
    assert all(c == f"NEW.{col} IS DISTINCT FROM OLD.{col}" for c, col in plain)


def test_a_leg_loses_its_profile_link_only_once_the_profile_row_is_gone() -> None:
    """`account_profile_id` may only become NULL, and only as the FK's ON DELETE SET NULL does it
    (21 Sec.3.3.3): any other change, or a NULL while the profile still exists, is refused."""
    ((condition, column),) = [
        arm for arm in _write_once_arms("tgl_write_once") if arm[1] == "account_profile_id"
    ]
    assert column == "account_profile_id"
    assert condition == _norm("""NEW.account_profile_id IS DISTINCT FROM OLD.account_profile_id
        AND (NEW.account_profile_id IS NOT NULL
          OR EXISTS (SELECT FROM public.account_profiles p WHERE p.id = OLD.account_profile_id))""")


def test_a_leg_is_sized_from_a_live_profile_of_its_own_account() -> None:
    """Cross-account: the profile must belong to the leg's account and must not be soft-deleted;
    a leg with no profile is refused as well."""
    assert _norm("""IF NEW.account_profile_id IS NULL OR NOT EXISTS (
          SELECT FROM public.account_profiles p
          WHERE p.id = NEW.account_profile_id AND p.exchange_account_id = NEW.exchange_account_id
            AND p.deleted_at IS NULL) THEN""") in _function("tgl_profile_check")


@pytest.mark.parametrize("function", ["tgl_env_check", "tgdm_env_check"])
def test_the_leg_and_member_environment_triggers_read_the_account_row_for_share(
    function: str,
) -> None:
    """SR-E28-16: an environment change waits for the writing transaction, and
    `trg_ea_env_in_use` then sees the leg or member row."""
    body = _function(function)
    assert _ACCOUNT_LOOKUP in body and body.count("FOR SHARE") == 1


def test_only_the_two_account_readers_take_a_row_lock() -> None:
    assert _up().count("FOR SHARE") == 2 and "FOR UPDATE" not in _up()


_ACCOUNT_LOOKUP = (
    "SELECT a.env::text INTO account_env FROM public.exchange_accounts a "
    "WHERE a.id = NEW.exchange_account_id FOR SHARE;"
)
#: Each environment check: the lookups keyed by the new row, then the comparison that refuses.
_ENV_CHECKS = (
    (
        "tg_env_check",
        (
            "SELECT d.env::text INTO definition_env FROM public.trade_group_definitions d "
            "WHERE d.id = NEW.definition_id;",
        ),
        "IF FOUND AND definition_env <> NEW.env::text THEN",
    ),
    (
        "tgl_env_check",
        (
            "SELECT g.env::text INTO group_env FROM public.trade_groups g "
            "WHERE g.id = NEW.trade_group_id;",
            _ACCOUNT_LOOKUP,
        ),
        "IF group_env IS NOT NULL AND account_env IS NOT NULL AND group_env <> account_env THEN",
    ),
    (
        "tgdm_env_check",
        (
            "SELECT d.env::text INTO definition_env FROM public.trade_group_definitions d "
            "WHERE d.id = NEW.definition_id;",
            _ACCOUNT_LOOKUP,
        ),
        "IF definition_env IS NOT NULL AND account_env IS NOT NULL "
        "AND definition_env <> account_env THEN",
    ),
)


@pytest.mark.parametrize(
    ("function", "lookups", "clause"), _ENV_CHECKS, ids=[c[0] for c in _ENV_CHECKS]
)
def test_the_environment_triggers_look_up_by_the_new_row_and_compare_as_text(
    function: str, lookups: tuple[str, ...], clause: str
) -> None:
    body = _function(function)
    casts = re.findall(r"SELECT \w+\.env(\S*) INTO", body)
    assert all(lookup in body for lookup in lookups) and clause in body
    assert len(casts) == len(lookups) and set(casts) == {"::text"}


def test_no_function_declares_a_variable_of_the_environment_type() -> None:
    """The pinned `search_path` hides `public.exchange_env`, so no variable is declared with it:
    every DECLARE holds only `text` variables (six functions declare any)."""
    declares = re.findall(r"DECLARE (.*?) BEGIN", _up())
    assert len(declares) == 6 and all("exchange_env" not in d for d in declares)
    assert all(re.fullmatch(r"(?:\w+ text; ?)+", d) for d in declares)


def test_the_environment_of_an_account_in_a_definition_or_a_leg_is_fixed() -> None:
    """SR-E28-16: blanket immutability of `exchange_accounts.env` is #2333's; this guard is the
    part E28-T01 owns, and it looks at both places an account can be in use."""
    assert (
        "CREATE TRIGGER trg_ea_env_in_use BEFORE UPDATE OF env ON exchange_accounts "
        "FOR EACH ROW EXECUTE FUNCTION ea_env_in_use_check();"
    ) in _up()
    assert _norm("""IF NEW.env IS DISTINCT FROM OLD.env AND (
          EXISTS (SELECT FROM public.trade_group_definition_members m
                  WHERE m.exchange_account_id = OLD.id)
          OR EXISTS (SELECT FROM public.trade_group_legs l WHERE l.exchange_account_id = OLD.id))
        THEN""") in _function("ea_env_in_use_check")


def test_the_app_role_cannot_hard_delete_a_group_a_leg_or_a_definition() -> None:
    """0024's `api_keys` precedent: a group and its legs are history and a definition leaves by
    soft delete, so `cv_app` loses DELETE on those three where the role exists. Members keep it."""
    sql = _up()
    revokes = " ".join(
        f"EXECUTE 'REVOKE DELETE ON {table} FROM cv_app';"
        for table in ("trade_groups", "trade_group_legs", "trade_group_definitions")
    )
    guarded = (
        "DO $BODY$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN "
        f"{revokes} END IF; END $BODY$;"
    )
    assert guarded in sql
    assert sql.count("REVOKE ") == 3 and sql.count("pg_roles") == 1  # no other revoke or role


_COMMENT = re.compile(r"COMMENT ON COLUMN (\w+)\.(\w+) IS '([^']*)';")
#: The columns whose comment is not the money one: the exchange's answer to a leg, a user's note.
_EXCHANGE_TEXT = {"trade_group_legs": {"rejection_code", "rejection_message"}}
_NOTES = {"trade_groups": {"intent_note"}}


@pytest.mark.parametrize("name", list(_TABLES))
def test_columns_carry_the_p1_classification_comment_the_plan_gives_them(name: str) -> None:
    """C-5.9 / 21 Sec.12: every `numeric(38,18)` column is class P1, so are the legs' rejection
    code and message (the exchange's answer can repeat order values) and the group's note;
    everything else, `profile_snapshot` and the definitions included, is P0 and carries none."""
    table = _TABLES[name]
    money = {
        c.name
        for c in table.columns
        if isinstance(c.type, Numeric) and (c.type.precision, c.type.scale) == (38, 18)
    }
    want = dict.fromkeys(money, models.OMS_MONEY_COMMENT)
    want |= dict.fromkeys(_EXCHANGE_TEXT.get(name, ()), models.OMS_EXCHANGE_TEXT_COMMENT)
    want |= dict.fromkeys(_NOTES.get(name, ()), models.GROUP_NOTE_COMMENT)
    assert {c.name: c.comment for c in table.columns if c.comment} == want
    for column, comment in want.items():
        assert f"COMMENT ON COLUMN {name}.{column} IS '{comment}';" in _up()


def test_the_models_classify_six_group_columns_and_eleven_leg_columns() -> None:
    """Counted from the models, so a classification dropped from a column and from the SQL
    together still fails here."""
    classified = {
        name: {c.name for c in table.columns if c.comment} for name, table in _TABLES.items()
    }
    assert len(classified["trade_groups"]) == 5 + 1  # money columns, intent_note
    assert len(classified["trade_group_legs"]) == 9 + 2  # money columns, rejection text
    assert (
        classified["trade_group_definitions"]
        == classified["trade_group_definition_members"]
        == set()
    )
    assert "resolved_leverage" not in classified["trade_group_legs"]  # a multiplier, not money
    assert "profile_snapshot" not in classified["trade_group_legs"]


def test_every_rendered_comment_is_a_model_comment_and_the_other_way_round() -> None:
    """`alembic check` diffs column comments: the SQL and `db.models` carry the same set, text for
    text."""
    rendered = _COMMENT.findall(_up())
    model = [
        (t.name, c.name, str(c.comment)) for t in _TABLES.values() for c in t.columns if c.comment
    ]
    assert len(rendered) == len(model) == 17
    assert sorted(rendered) == sorted(model)


@pytest.mark.parametrize(
    "comment",
    [models.OMS_MONEY_COMMENT, models.OMS_EXCHANGE_TEXT_COMMENT, models.GROUP_NOTE_COMMENT],
    ids=["money", "exchange-text", "note"],
)
def test_each_classification_comment_is_a_p1_text_that_fits_a_sql_literal(comment: str) -> None:
    assert comment.startswith("PII: ") and "class P1" in comment
    assert "'" not in comment  # it sits in a single-quoted SQL literal


def test_downgrade_refuses_unless_empty_then_drops_in_dependency_order() -> None:
    """C-5.2: groups are trading history and definitions are configuration, so the downgrade locks
    the four tables, refuses while any holds a row, and only then drops the guard on
    `exchange_accounts`, the three keys, the tables, the functions and the types."""
    functions = [
        "tgl_write_once",
        "tgl_profile_check",
        "tgl_env_check",
        "tg_write_once",
        "tg_env_check",
        "tgdm_env_check",
        "tgd_write_once",
    ]
    assert _in_order(
        _down(),
        [
            _LOCK_ON,
            "LOCK TABLE trade_groups, trade_group_legs, trade_group_definitions, "
            "trade_group_definition_members IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM trade_groups) OR EXISTS (SELECT 1 FROM trade_group_legs) "
            "OR EXISTS (SELECT 1 FROM trade_group_definitions) "
            "OR EXISTS (SELECT 1 FROM trade_group_definition_members) THEN",
            "RAISE EXCEPTION '0039_trade_groups downgrade refused: trade groups or group "
            "definitions exist,",
            "Fix forward with a new revision instead (C-5.2)';",
            "DROP TRIGGER trg_ea_env_in_use ON exchange_accounts;",
            "DROP FUNCTION ea_env_in_use_check();",
            *(f"ALTER TABLE {t} DROP CONSTRAINT {_fk_name(t, c)};" for t, c, _ in _LEG_FKS[::-1]),
            "DROP TABLE trade_group_legs;",
            "DROP TABLE trade_groups;",
            "DROP TABLE trade_group_definition_members;",
            "DROP TABLE trade_group_definitions;",
            *(f"DROP FUNCTION {name}();" for name in functions),
            "DROP TYPE algo_kind;",
            "DROP TYPE leg_status;",
            "DROP TYPE trade_group_status;",
            _LOCK_OFF,
        ],
    )


def test_downgrade_drops_exactly_what_the_upgrade_created() -> None:
    """Nothing is left behind and nothing else is dropped, so the round trip (C-5.5) is clean:
    the objects of the revision, the keys it added to tables it does not own and the one trigger
    it put on `exchange_accounts`."""
    up, down = _up(), _down()
    for kind in ("TABLE", "TYPE", "FUNCTION"):
        created = re.findall(rf"CREATE {kind} (\w+)", up)
        assert created and sorted(created) == sorted(re.findall(rf"DROP {kind} (\w+)", down)), kind
    added = re.findall(r"ALTER TABLE (\w+) ADD CONSTRAINT (\w+) ", up)
    assert added and sorted(added) == sorted(
        re.findall(r"ALTER TABLE (\w+) DROP CONSTRAINT (\w+);", down)
    )
    on_tables = re.findall(r"CREATE TRIGGER (\w+) [^;]*? ON (\w+) FOR EACH ROW", up)
    survivors = sorted(t for t, table in on_tables if table not in _TABLES)
    assert (
        survivors
        == sorted(re.findall(r"DROP TRIGGER (\w+) ON \w+;", down))
        == ["trg_ea_env_in_use"]
    )


def _default(column: Column[Any]) -> str | None:
    default = column.server_default
    if default is None:
        return None
    assert isinstance(default, DefaultClause)
    return str(default.arg)


def _doc_columns(table: str) -> list[tuple[str, bool, str | None]]:
    """`(name, nullable, server default)` for every column line of the doc's CREATE TABLE."""
    columns: list[tuple[str, bool, str | None]] = []
    for line in _doc_table(table).splitlines():
        found = re.match(r"  ([a-z][a-z0-9_]*) ", line)
        if found is None:  # CONSTRAINT / PRIMARY KEY lines and their continuations
            continue
        ddl = line.split("--", 1)[0].strip()
        default = re.search(r"DEFAULT (\S+?),?$", ddl)
        nullable = "NOT NULL" not in ddl and "PRIMARY KEY" not in ddl
        columns.append((found[1], nullable, default[1] if default else None))
    return columns


def _checks(table: Table) -> dict[str, str]:
    """Every model CHECK of the table by its given name, the body on one line."""
    return {
        str(c.name).removeprefix(f"ck_{table.name}_"): " ".join(str(c.sqltext).split())
        for c in table.constraints
        if isinstance(c, CheckConstraint)
    }


def _create_index(ix: Index) -> str:
    """The `CREATE INDEX` statement a model index stands for, in the migration's spelling."""
    assert ix.table is not None
    columns = ", ".join(str(e).removeprefix(f"{ix.table.name}.") for e in ix.expressions)
    where = ix.dialect_options["postgresql"]["where"]
    tail = "" if where is None else f" WHERE {where}"
    unique = "UNIQUE " if ix.unique else ""
    return f"CREATE {unique}INDEX {ix.name} ON {ix.table.name} ({columns}){tail};"


@pytest.mark.parametrize("table", _TABLES.values(), ids=list(_TABLES))
def test_models_mirror_the_doc_columns(table: Table) -> None:
    """The `migrations` job autogenerate-diffs the DB against `db.models.metadata`; names,
    nullability and server defaults are pinned against the plan doc here."""
    got = [(c.name, bool(c.nullable), _default(c)) for c in table.columns]
    assert got == _doc_columns(table.name)


@pytest.mark.parametrize("table", _TABLES.values(), ids=list(_TABLES))
def test_models_mirror_the_foreign_keys_and_their_delete_rules(table: Table) -> None:
    doc = re.findall(
        r"^  (\w+)\s+uuid(?: NOT NULL)? REFERENCES (\w+)\(id\) "
        r"ON DELETE (RESTRICT|CASCADE|SET NULL)",
        _doc_table(table.name),
        re.MULTILINE,
    )
    got = {
        (c.column_keys[0], c.referred_table.name, c.ondelete)
        for c in table.foreign_key_constraints
        if len(c.column_keys) == 1
    }
    assert got == set(doc) and got


def test_models_mirror_the_composite_foreign_key_to_the_profile_revision() -> None:
    """`tgl_profile_revision` (account_profile_id, profile_version) names a revision row, which
    is append-only, so it needs no delete rule; a NULL profile id (the profile's hard delete)
    switches the key off under MATCH SIMPLE and the snapshot keeps the history."""
    doc = re.findall(
        r"CONSTRAINT (\w+) FOREIGN KEY \(([^)]*)\)\s+REFERENCES (\w+) \(([^)]*)\)",
        _doc_table("trade_group_legs"),
    )
    composite = [
        c for c in models.trade_group_legs.foreign_key_constraints if len(c.column_keys) > 1
    ]
    got = [
        (
            c.name,
            ", ".join(c.column_keys),
            c.referred_table.name,
            ", ".join(e.column.name for e in c.elements),
        )
        for c in composite
    ]
    assert (
        got
        == doc
        == [
            (
                "tgl_profile_revision",
                "account_profile_id, profile_version",
                "account_profile_revisions",
                "profile_id, version",
            )
        ]
    )
    assert all(c.ondelete is None for c in composite)
    assert (
        "CONSTRAINT tgl_profile_revision FOREIGN KEY (account_profile_id, profile_version) "
        "REFERENCES account_profile_revisions (profile_id, version),"
    ) in _up()


def test_a_leg_snapshot_is_frozen_and_tied_to_the_profile_version_it_was_sized_from() -> None:
    """The offline half of the ticket scenario "Leg snapshot survives a profile edit": the copy,
    its version and its account never change, the copy is tied to the columns, and the version
    is a key to the append-only revision."""
    assert {"profile_snapshot", "profile_version", "exchange_account_id"} <= set(
        _WRITE_ONCE["trg_tgl_write_once"]
    )
    assert models.trade_group_legs.c.profile_snapshot.nullable is False
    snapshot = _checks(models.trade_group_legs)["tgl_snapshot"]
    assert "profile_snapshot ->> 'account_id' = exchange_account_id::text" in snapshot
    assert "profile_snapshot ->> 'version' = profile_version::text" in snapshot
    assert "CONSTRAINT tgl_profile_revision FOREIGN KEY (account_profile_id, profile_version) " in (
        _up()
    )


def test_membership_is_keyed_by_definition_and_account() -> None:
    members = models.trade_group_definition_members
    assert [c.name for c in members.primary_key.columns] == ["definition_id", "exchange_account_id"]
    assert "PRIMARY KEY (definition_id, exchange_account_id)" in _up()


@pytest.mark.parametrize(("table", "column", "target"), _LEG_FKS, ids=[t for t, _, _ in _LEG_FKS])
def test_models_carry_the_deferred_foreign_keys_with_set_null(
    table: str, column: str, target: str
) -> None:
    foreign_keys = list(models.metadata.tables[table].c[column].foreign_keys)
    assert [(fk.column.table.name, fk.column.name, fk.ondelete) for fk in foreign_keys] == [
        (target, "id", "SET NULL")
    ]


def test_the_rule_run_key_is_named_and_added_later_because_of_the_cycle_with_the_group() -> None:
    """`trade_groups.origin_rule_run_id` points back at `rule_runs`, so metadata creation needs
    this key as a separate ALTER, which needs its name (the one Postgres gives it)."""
    (fk,) = models.rule_runs.c.trade_group_id.foreign_keys
    assert fk.name == _fk_name("rule_runs", "trade_group_id") and fk.use_alter is True
    origin = models.trade_groups.c.origin_rule_run_id.foreign_keys
    assert {(x.column.table.name, x.ondelete) for x in origin} == {("rule_runs", "SET NULL")}


@pytest.mark.parametrize("table", _TABLES.values(), ids=list(_TABLES))
def test_models_mirror_the_check_constraints(table: Table) -> None:
    """`alembic check` never diffs CHECK bodies, so they are pinned against the SQL here."""
    checks = _checks(table)
    assert set(checks) == set(re.findall(r"CONSTRAINT (\w+)\s+CHECK", _doc_table(table.name)))
    for name, body in checks.items():
        assert _norm(f"CONSTRAINT {name} CHECK ({body})") in _up(), name


def test_models_mirror_the_unique_constraints_under_their_given_names() -> None:
    """One group per (creator, ref) and one leg per (group, account); the anchor is never unique
    across creators and nothing indexes it alone (G-6(b), 21 Sec.3.3.2)."""
    uniques = {
        (str(c.name), tuple(col.name for col in c.columns))
        for table in _TABLES.values()
        for c in table.constraints
        if isinstance(c, UniqueConstraint)
    }
    assert uniques == {
        ("ux_tg_creator_ref", ("created_by", "client_group_ref")),
        ("ux_tgl_group_account", ("trade_group_id", "exchange_account_id")),
    }
    assert "CONSTRAINT ux_tg_creator_ref UNIQUE (created_by, client_group_ref)" in _up()
    assert "CONSTRAINT ux_tgl_group_account UNIQUE (trade_group_id, exchange_account_id)" in _up()
    assert not [
        ix for ix in models.trade_groups.indexes if "client_group_ref" in str(ix.expressions)
    ]


@pytest.mark.parametrize("table", _TABLES.values(), ids=list(_TABLES))
def test_models_mirror_the_indexes(table: Table) -> None:
    doc = "\n".join(_doc_block(h, i) for h, i in _BLOCKS)
    assert sorted(str(ix.name) for ix in table.indexes) == sorted(
        re.findall(rf"INDEX (\w+)\s+ON {table.name} ", doc)
    )
    for ix in table.indexes:
        assert _create_index(ix) in _up(), ix.name


def test_every_numeric_column_reads_back_as_decimal() -> None:
    """`Decimal` end to end: no numeric column may hand a writer or a reader a float."""
    numeric = [c.type for t in _TABLES.values() for c in t.columns if isinstance(c.type, Numeric)]
    assert len(numeric) == 5 + 10  # trade_groups, trade_group_legs
    assert all(n.asdecimal and n.python_type is Decimal for n in numeric)


@pytest.mark.parametrize(
    ("table", "check", "count"),
    [(models.trade_groups, "tg_finite", 5), (models.trade_group_legs, "tgl_finite", 10)],
    ids=["trade_groups", "trade_group_legs"],
)
def test_no_group_or_leg_number_may_be_nan(table: Table, check: str, count: int) -> None:
    """NaN sorts above every number in Postgres, so a bound alone admits it (`tgl_qty_pos` passes
    a NaN quantity): the finite check names every numeric column, once, and joins them with AND."""
    numeric = {c.name for c in table.columns if isinstance(c.type, Numeric)}
    finite = _up().split(f"CONSTRAINT {check} CHECK (", 1)[1].split(")", 1)[0]
    assert sorted(re.findall(r"(\w+) <> 'NaN'", finite)) == sorted(numeric)
    assert len(numeric) == count and " OR " not in finite


@pytest.mark.parametrize(
    ("table", "name"),
    [
        ("trade_groups", "tg_limit_px"),
        ("trade_groups", "tg_cond_px"),
        ("trade_group_legs", "tgl_snapshot"),
        ("trade_group_legs", "tgl_sl_px"),
    ],
)
def test_a_check_that_could_evaluate_to_null_is_wrapped_in_is_true(table: str, name: str) -> None:
    """A bare CHECK passes a NULL result: a Limit group without its price, a snapshot without its
    keys or a leg with no stop would otherwise be stored."""
    assert _checks(_TABLES[table])[name].endswith(") IS TRUE")


def test_no_check_ties_the_paper_flag_to_the_environment() -> None:
    """24's `is_paper` is orthogonal to `env` (the plan's `tg_paper_env` said otherwise)."""
    assert "tg_paper_env" not in _up()
    assert not [n for n, body in _checks(models.trade_groups).items() if "is_paper" in body]


#: UUIDs of three versions, spelled canonically; the version is asserted where they are used.
_REFS = {
    4: "9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59",
    5: str(uuid.uuid5(uuid.NAMESPACE_DNS, "candleviewer.example")),
    7: "0192f3a4-7b6c-7d8e-9f01-23456789abcd",
}
_NOT_REFS = {
    "upper case": _REFS[4].upper(),
    "braces": f"{{{_REFS[4]}}}",
    "no hyphens": _REFS[4].replace("-", ""),
    "trailing newline": _REFS[4] + "\n",
    "leading space": f" {_REFS[4]}",
    "urn prefix": f"urn:uuid:{_REFS[4]}",
    "non-hex digit": _REFS[4][:-1] + "g",
    "short last group": _REFS[4][:-1],
    "ulid": "01ARZ3NDEKTSV4RRFFQ69G5FAV",
    "server ref": "cv-0c000000",
    "empty": "",
}


def test_tg_ref_fmt_is_the_model_pattern_in_the_plan_doc_and_in_the_sql() -> None:
    check = f"CONSTRAINT tg_ref_fmt CHECK (client_group_ref ~ '{models.GROUP_REF_PATTERN}'),"
    assert check in _up() and check in _norm(_doc_table("trade_groups") + "\n);")
    assert (
        _checks(models.trade_groups)["tg_ref_fmt"]
        == f"client_group_ref ~ '{models.GROUP_REF_PATTERN}'"
    )


@pytest.mark.parametrize("version", _REFS, ids=[f"v{v}" for v in _REFS])
def test_the_ref_pattern_admits_a_canonical_lower_case_uuid_of_any_version(version: int) -> None:
    ref = _REFS[version]
    assert uuid.UUID(ref).version == version and str(uuid.UUID(ref)) == ref
    assert re.fullmatch(models.GROUP_REF_PATTERN, ref)


@pytest.mark.parametrize("ref", _NOT_REFS.values(), ids=list(_NOT_REFS))
def test_the_ref_pattern_refuses_every_other_spelling(ref: str) -> None:
    """`fullmatch`, because Postgres `~` reads `$` as the very end of the string while Python's
    `$` alone would let a trailing newline through."""
    assert re.fullmatch(models.GROUP_REF_PATTERN, ref) is None


def test_the_no_native_stop_alarm_index_covers_every_open_status_including_filled() -> None:
    """C-2.6: a filled leg is an open position, so a filled leg without a confirmed native stop
    is alertable; the plan's `ix_tgl_no_sl` missed `filled` and its `ix_tgl_open` named a
    `closing` status the enum does not have."""
    where = {
        str(ix.name): str(ix.dialect_options["postgresql"]["where"])
        for ix in models.trade_group_legs.indexes
    }
    stop = re.findall(r"status IN \(([^)]*)\)", where["ix_tgl_no_sl"])
    assert stop == ["'open','partially_filled','filled'"]
    assert where["ix_tgl_no_sl"].endswith(" AND native_sl_confirmed = false")
    live = re.findall(r"status IN \(([^)]*)\)", where["ix_tgl_open"])
    assert live == ["'pending','submitted','open','partially_filled','filled'"]
    assert "closing" not in models.LEG_STATUSES


@pytest.mark.parametrize(
    ("table", "values"),
    [
        (models.trade_groups, models.TRADE_GROUP_STATUSES),
        (models.trade_group_legs, models.LEG_STATUSES),
    ],
    ids=["trade_groups", "trade_group_legs"],
)
def test_every_status_an_index_or_check_names_is_a_value_of_its_enum(
    table: Table, values: tuple[str, ...]
) -> None:
    """Postgres refuses an unknown enum literal only when the DDL runs, so name each one here."""
    predicates = [str(ix.dialect_options["postgresql"]["where"]) for ix in table.indexes]
    predicates += _checks(table).values()
    named = {
        value
        for predicate in predicates
        for group in re.findall(r"status IN \(([^)]*)\)", predicate)
        for value in re.findall(r"'(\w+)'", group)
    }
    assert named and named <= set(values)


#: The one digest column: the SHA-256 of the request body, a replay fingerprint (G-6(b)), not a
#: credential. It is the one column of these tables allowed to be a hash.
_FINGERPRINT = ("trade_groups", "client_body_sha256")
_CREDENTIAL_NAME = re.compile(r"secret|token|password|key_|cipher|kek|dek")


@pytest.mark.parametrize("table", _TABLES.values(), ids=list(_TABLES))
def test_no_column_is_named_like_a_credential(table: Table) -> None:
    """Class P0/P1 only (21 Sec.12): no key, token, password or ciphertext lives in these tables,
    and `profile_snapshot` is the 24 Sec.9.2 projection of a profile, which holds none."""
    assert [c.name for c in table.columns if _CREDENTIAL_NAME.search(c.name)] == []


def test_the_only_digest_column_is_the_request_body_fingerprint() -> None:
    digests = [
        (t.name, c.name)
        for t in _TABLES.values()
        for c in t.columns
        if isinstance(c.type, DOMAIN) and c.type.name == "sha256_hex"
    ]
    assert digests == [_FINGERPRINT]
