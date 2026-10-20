"""`0037_account_profiles` (E28-T01 #905): offline render, plan-doc parity, the triggers and the
revisions' append-only guards, the downgrade guard and the model mirror.
Real Postgres: `tests/integration/storage/test_account_profiles_migration.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import CheckConstraint, Column, Index, Numeric, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.schema import DefaultClause

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0037_account_profiles", "0036_users_purge"
_UP, _DOWN = f"{_PREV}:{_REV}", f"{_REV}:{_PREV}"
_PROFILES, _REVISIONS = "3.2.4 `account_profiles`", "3.2.5 `account_profile_revisions`"
_TABLES = {t.name: t for t in (models.account_profiles, models.account_profile_revisions)}
#: (heading, n-th ```sql block under it): table, triggers, bootstrap; the revisions table.
_BLOCKS = ((_PROFILES, 0), (_PROFILES, 1), (_PROFILES, 2), (_REVISIONS, 0))


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


def test_revision_chains_onto_0036() -> None:
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", _UP)


@pytest.mark.parametrize(
    ("enum", "name"), [(models.sizing_mode, "sizing_mode"), (models.offset_unit, "offset_unit")]
)
def test_upgrade_creates_each_enum_as_the_plan_doc_and_the_model_declare_it(
    enum: ENUM, name: str
) -> None:
    statement = f"CREATE TYPE {name} AS ENUM ({','.join(repr(v) for v in enum.enums)});"
    assert statement in _norm(_DOC.read_text(encoding="utf-8")) and statement in _up()
    assert enum.name == name and enum.create_type is False  # the migration creates and drops it


@pytest.mark.parametrize(("heading", "index"), _BLOCKS)
def test_upgrade_ddl_is_the_plan_doc_ddl_verbatim(heading: str, index: int) -> None:
    assert _norm(_doc_block(heading, index)) in _up()


def test_upgrade_ships_only_these_objects() -> None:
    sql = _up()
    assert sql.count("CREATE TABLE ") == 2 and sql.count("CREATE TYPE ") == 2
    assert sql.count("CREATE UNIQUE INDEX ") == 2 and sql.count("CREATE INDEX ") == 0
    assert sql.count("CREATE FUNCTION ") == 4 and sql.count("CREATE TRIGGER ") == 7
    assert sql.count("ENABLE ALWAYS TRIGGER ") == 6
    assert sql.count("INSERT INTO ") == 3  # two trigger bodies and the backfill
    for absent in ("COMMENT ON", "GRANT ", "IF NOT EXISTS", "DROP "):
        assert absent not in sql


def test_upgrade_creates_in_dependency_order_under_a_bounded_lock_wait() -> None:
    """The revisions table exists before the triggers that write it, and the backfill runs after
    every trigger, so each bootstrap profile gets its version-1 revision."""
    assert _in_order(
        _up(),
        [
            "SET LOCAL lock_timeout = '5s';",
            "CREATE TYPE sizing_mode",
            "CREATE TYPE offset_unit",
            "CREATE TABLE account_profiles (",
            "CREATE TABLE account_profile_revisions (",
            "CREATE TRIGGER trg_ap_revision",
            "CREATE TRIGGER trg_ea_default_profile AFTER INSERT ON exchange_accounts",
            "SELECT gen_random_uuid(), ea.id, 'Default', true, 1, ea.created_by, ea.created_by "
            "FROM exchange_accounts ea",
            "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON account_profile_revisions FROM cv_app",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )


def test_backfill_writes_the_same_row_as_the_bootstrap_trigger() -> None:
    """One bootstrap profile, two writers: the trigger for new accounts, the backfill for the
    accounts that exist when the revision runs."""
    sql = _up()
    columns = "(id, exchange_account_id, name, is_default, risk_pct_equity, created_by, updated_by)"
    trigger = sql.split("INSERT INTO public.account_profiles ", 1)[1].split(";", 1)[0]
    backfill = sql.split("INSERT INTO account_profiles ", 1)[1].split(";", 1)[0]
    assert trigger.split(" VALUES ", 1) == [
        columns,
        "(gen_random_uuid(), NEW.id, 'Default', true, 1, NEW.created_by, NEW.created_by)",
    ]
    assert backfill.split(" SELECT ", 1) == [
        columns,
        "gen_random_uuid(), ea.id, 'Default', true, 1, ea.created_by, ea.created_by "
        "FROM exchange_accounts ea ORDER BY ea.created_at, ea.id",
    ]


def test_revisions_copy_the_audit_log_append_only_guards() -> None:
    """SR-E28-07 / C-5.7: row trigger, TRUNCATE statement trigger, both always enabled, and the
    grant revocation where the roles exist (the 0029 pattern)."""
    sql = _up()
    assert (
        "CREATE TRIGGER trg_apr_append BEFORE UPDATE OR DELETE ON account_profile_revisions "
        "FOR EACH ROW EXECUTE FUNCTION forbid_mutation();"
    ) in sql
    assert (
        "CREATE TRIGGER trg_apr_no_truncate BEFORE TRUNCATE ON account_profile_revisions "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_refuse_truncate();"
    ) in sql
    for trigger in ("trg_apr_append", "trg_apr_no_truncate"):
        assert f"ALTER TABLE account_profile_revisions ENABLE ALWAYS TRIGGER {trigger};" in sql
    for role in ("cv_app", "cv_ro"):
        assert _in_order(
            sql,
            [
                f"IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN",
                "EXECUTE 'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON account_profile_revisions "
                f"FROM {role}';",
            ],
        )


def test_the_app_role_cannot_hard_delete_a_profile() -> None:
    """A profile leaves by soft delete, which leaves a revision; a hard delete would not
    (SEC-D01, 0024's `api_keys` precedent). `cv_ro` has no DELETE to take."""
    sql = _up()
    assert _in_order(
        sql,
        [
            "IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN",
            "EXECUTE 'REVOKE DELETE ON account_profiles FROM cv_app';",
            "IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_ro') THEN",
        ],
    )
    assert sql.count("REVOKE DELETE ON account_profiles") == 1


@pytest.mark.parametrize(
    ("table", "trigger"),
    [
        ("account_profiles", "trg_ap_ladder_sum"),
        ("account_profiles", "trg_ap_version"),
        ("account_profiles", "trg_ap_revision"),
        ("exchange_accounts", "trg_ea_default_profile"),
    ],
)
def test_integrity_triggers_fire_under_the_replica_role(table: str, trigger: str) -> None:
    assert f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {trigger};" in _up()


def test_only_the_bookkeeping_touch_trigger_follows_the_replication_role() -> None:
    """`updated_at` bookkeeping keeps the default; every integrity trigger is always enabled."""
    created = re.findall(r"CREATE TRIGGER (\w+) ", _up())
    always = re.findall(r"ENABLE ALWAYS TRIGGER (\w+);", _up())
    assert sorted(set(created) - set(always)) == ["trg_account_profiles_touch"]


def test_version_is_set_by_the_database_whatever_the_writer_sends() -> None:
    """SR-E28-07: 1 on insert, OLD + 1 on every update; `id` and the account are write-once."""
    body = _up().split("CREATE FUNCTION ap_version_bump()", 1)[1].split("END $$;", 1)[0]
    assert "IF TG_OP = 'INSERT' THEN NEW.version := 1; RETURN NEW;" in body
    assert "NEW.version := OLD.version + 1;" in body
    assert (
        "IF NEW.id IS DISTINCT FROM OLD.id OR NEW.exchange_account_id IS DISTINCT FROM "
        "OLD.exchange_account_id THEN"
    ) in body
    assert "CREATE TRIGGER trg_ap_version BEFORE INSERT OR UPDATE ON account_profiles" in _up()
    assert "USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_ap_version';" in body


def test_every_profile_write_records_its_revision_in_the_same_transaction() -> None:
    body = _up().split("CREATE FUNCTION ap_record_revision()", 1)[1].split("END $$;", 1)[0]
    assert (
        "INSERT INTO public.account_profile_revisions (profile_id, version, payload, changed_by) "
        "VALUES (NEW.id, NEW.version, to_jsonb(NEW), CASE WHEN TG_OP = 'INSERT' THEN "
        "NEW.created_by ELSE NEW.updated_by END);"
    ) in body
    assert "CREATE TRIGGER trg_ap_revision AFTER INSERT OR UPDATE ON account_profiles" in _up()


@pytest.mark.parametrize(
    "function",
    ["ap_ladder_sum_check", "ap_version_bump", "ap_record_revision", "ea_default_profile"],
)
def test_every_trigger_function_pins_its_search_path(function: str) -> None:
    definer = "SECURITY DEFINER " if function == "ap_record_revision" else ""
    head = f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql {definer}"
    assert f"{head}SET search_path = pg_catalog, pg_temp AS $$" in _up()


def test_only_the_revision_writer_runs_as_its_owner_and_nobody_may_call_it() -> None:
    """SEC-905-01: the history's one writer is the definer function, so the runtime role needs no
    INSERT on it; no role but its owner may execute or attach the function."""
    sql = _up()
    assert sql.count("SECURITY DEFINER") == 1
    assert _in_order(
        sql,
        [
            "CREATE FUNCTION ap_record_revision() RETURNS trigger LANGUAGE plpgsql "
            "SECURITY DEFINER",
            "REVOKE EXECUTE ON FUNCTION ap_record_revision() FROM PUBLIC;",
            "CREATE TRIGGER trg_ap_revision AFTER INSERT OR UPDATE ON account_profiles",
        ],
    )


def test_ladder_refusals_name_the_trigger_and_never_a_value() -> None:
    body = _up().split("CREATE FUNCTION ap_ladder_sum_check()", 1)[1].split("END $$;", 1)[0]
    messages = re.findall(r"RAISE EXCEPTION '([^']*)'", body)
    assert messages == [
        "trg_ap_ladder_sum: every tp_ladder rung needs a number pct and r above 0",
        "trg_ap_ladder_sum: the tp_ladder pct values add up to more than the 100%% limit",
    ]
    assert body.count("USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_ap_ladder_sum'") == 2
    assert "CREATE TRIGGER trg_ap_ladder_sum BEFORE INSERT OR UPDATE OF tp_ladder" in _up()


def test_the_native_stop_is_mandatory_and_never_defined_in_r() -> None:
    """SR-E28-08 at the schema layer: the CHECK can only be true, and R is defined by the stop
    (24-internal-schemas.md Sec.9.3.1), so the stop is never `r_multiple`."""
    sql = _up()
    assert "CONSTRAINT ap_native_sl CHECK (require_native_sl = true)," in sql
    assert "CONSTRAINT ap_sl_unit CHECK (sl_offset_unit <> 'r_multiple')," in sql
    assert "CONSTRAINT ap_sl_pos CHECK (sl_offset_value > 0)," in sql


def test_a_trading_enabled_profile_bounds_every_cap() -> None:
    """SR-E28-01 / decision D11: "no cap" is not representable on a trading-enabled profile."""
    assert (
        "CONSTRAINT ap_trading_caps CHECK (NOT trading_enabled OR ((max_position_notional_usd IS "
        "NOT NULL OR max_position_pct_equity IS NOT NULL) AND (max_daily_loss_usd IS NOT NULL OR "
        "max_daily_loss_pct IS NOT NULL) AND max_open_positions IS NOT NULL AND "
        "max_concurrent_orders IS NOT NULL AND max_leverage_cap IS NOT NULL)),"
    ) in _up()
    assert "trading_enabled boolean NOT NULL DEFAULT false," in _up()


def test_no_profile_number_may_be_nan() -> None:
    """NaN sorts above every number in Postgres, so a bound alone admits it and a NaN cap would
    satisfy `ap_trading_caps`: `ap_finite` names every numeric column (CR-D02)."""
    numeric = {
        column.name
        for column in models.account_profiles.columns
        if isinstance(column.type, Numeric)
    }
    finite = _up().split("CONSTRAINT ap_finite CHECK (", 1)[1].split(");", 1)[0]
    assert {c for c in numeric if f"{c} <> 'NaN'" not in finite} == set()
    assert len(numeric) == 16


def test_downgrade_refuses_unless_only_bootstrap_profiles_remain_then_drops() -> None:
    assert _in_order(
        _down(),
        [
            "SET LOCAL lock_timeout = '5s';",
            "LOCK TABLE account_profiles, account_profile_revisions IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM account_profiles WHERE version <> 1 OR name <> 'Default' "
            "OR NOT is_default) OR (SELECT count(*) FROM account_profile_revisions) <> "
            "(SELECT count(*) FROM account_profiles) THEN",
            "RAISE EXCEPTION '0037_account_profiles downgrade refused: a profile was created, "
            "edited or deleted after the bootstrap,",
            "Fix forward with a new revision instead (C-5.2)';",
            "DROP TRIGGER trg_ea_default_profile ON exchange_accounts;",
            "DROP FUNCTION ea_default_profile();",
            "DROP TABLE account_profiles;",
            "DROP FUNCTION ap_record_revision();",
            "DROP FUNCTION ap_version_bump();",
            "DROP FUNCTION ap_ladder_sum_check();",
            "DROP TABLE account_profile_revisions;",
            "DROP TYPE offset_unit;",
            "DROP TYPE sizing_mode;",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
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
        if found is None:  # CONSTRAINT lines and their continuations
            continue
        ddl = line.split("--", 1)[0].strip()
        default = re.search(r"DEFAULT (\S+?),?$", ddl)
        nullable = "NOT NULL" not in ddl and "PRIMARY KEY" not in ddl
        columns.append((found[1], nullable, default[1] if default else None))
    return columns


@pytest.mark.parametrize("table", _TABLES.values(), ids=list(_TABLES))
def test_models_mirror_the_doc_columns(table: Table) -> None:
    """The `migrations` job autogenerate-diffs the DB against `db.models.metadata`; names,
    nullability and server defaults are pinned against the plan doc here."""
    got = [(c.name, bool(c.nullable), _default(c)) for c in table.columns]
    assert got == _doc_columns(table.name)


@pytest.mark.parametrize("table", _TABLES.values(), ids=list(_TABLES))
def test_models_mirror_the_foreign_keys_and_their_delete_rules(table: Table) -> None:
    doc = re.findall(
        r"^  (\w+)\s+uuid(?: NOT NULL)? REFERENCES (\w+)\(id\) ON DELETE (CASCADE|SET NULL)",
        _doc_table(table.name),
        re.MULTILINE,
    )
    got = {(fk.parent.name, fk.column.table.name, fk.ondelete) for fk in table.foreign_keys}
    assert got == set(doc) and got


def test_the_revisions_keep_no_reference_to_the_profile_row() -> None:
    """The history outlives the row (21 Sec.3.2.5)."""
    profile_id = models.account_profile_revisions.c.profile_id
    assert not profile_id.foreign_keys and not profile_id.nullable


@pytest.mark.parametrize("table", _TABLES.values(), ids=list(_TABLES))
def test_models_mirror_the_check_constraints(table: Table) -> None:
    """`alembic check` never diffs CHECK bodies, so they are pinned against the SQL here."""
    checks = {
        str(c.name).removeprefix(f"ck_{table.name}_"): " ".join(str(c.sqltext).split())
        for c in table.constraints
        if isinstance(c, CheckConstraint)
    }
    assert set(checks) == set(re.findall(r"CONSTRAINT (\w+)\s+CHECK", _doc_table(table.name)))
    for name, body in checks.items():
        assert _norm(f"CONSTRAINT {name} CHECK ({body})") in _up(), name


def test_models_mirror_the_unique_constraint_under_its_given_name() -> None:
    uniques = {
        (str(c.name), tuple(col.name for col in c.columns))
        for table in _TABLES.values()
        for c in table.constraints
        if isinstance(c, UniqueConstraint)
    }
    assert uniques == {("ux_apr_version", ("profile_id", "version"))}
    assert "CONSTRAINT ux_apr_version UNIQUE (profile_id, version)" in _up()


def _create_index(ix: Index) -> str:
    """The `CREATE INDEX` statement a model index stands for, in the migration's spelling."""
    assert ix.table is not None
    columns = ", ".join(str(e).removeprefix(f"{ix.table.name}.") for e in ix.expressions)
    where = ix.dialect_options["postgresql"]["where"]
    tail = "" if where is None else f" WHERE {where}"
    unique = "UNIQUE " if ix.unique else ""
    return f"CREATE {unique}INDEX {ix.name} ON {ix.table.name} ({columns}){tail};"


def test_models_mirror_the_indexes() -> None:
    table = models.account_profiles
    assert sorted(str(ix.name) for ix in table.indexes) == ["ux_ap_default", "ux_ap_name"]
    assert not models.account_profile_revisions.indexes
    for ix in table.indexes:
        assert _create_index(ix) in _up(), ix.name


def test_every_numeric_column_reads_back_as_decimal() -> None:
    """Money, quantities and percentages never round-trip through float (C3)."""
    numeric = [c.type for c in models.account_profiles.columns if isinstance(c.type, Numeric)]
    assert len(numeric) == 16
    assert all(kind.asdecimal for kind in numeric)


def test_no_profile_column_is_classified_personal_or_secret() -> None:
    """Class P0 (21 Sec.12): profile configuration, no credential, token, key or personal data."""
    for table in _TABLES.values():
        assert all(c.comment is None for c in table.columns), table.name
