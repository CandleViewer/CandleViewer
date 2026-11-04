"""The `closed_pnl_records` revision (E29-S06 #981 slice 2; 21 Sec.3.3.13, Sec.3.3.6, Sec.3.3.7):
offline render, plan-doc parity, the guard's refusals as SQL text, the grants and comments, the
model mirror, the ledger row and the CI-MIG-006 list. Its id and parent are read from its file,
so a renumber or re-parent at the PR's open (C-5.3) changes nothing here. Real Postgres:
`tests/integration/storage/test_closed_pnl_records_migration.py`."""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
from functools import cache
from pathlib import Path

from sqlalchemy import CheckConstraint, Index, Table

from candleviewer.db import models
from candleviewer.storage.guarded_privileges import GUARDED_PRIVILEGES

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_CI = _ROOT.parents[1] / "tools" / "ci"
_VERSIONS = _ROOT / "candleviewer" / "migrations" / "versions"
[_FILE] = sorted(_VERSIONS.glob("*_closed_pnl_records.py"))
_TABLE: Table = models.closed_pnl_records
_LOCK_ON, _LOCK_OFF = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
_IDS = {
    node.target.id: node.value.value
    for node in ast.parse(_FILE.read_text(encoding="utf-8")).body
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    and isinstance(node.value, ast.Constant)
}  # fmt: skip
_REV, _PREV = str(_IDS["revision"]), str(_IDS["down_revision"])


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#981)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments, collapse whitespace and the space inside a bracket, and fold the `;`
    alembic appends, as the 0058 suite does."""
    flat = " ".join(re.sub(r"--[^\n]*", "", sql).split())
    return flat.replace("( ", "(").replace(" )", ")").replace(";;", ";")


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", f"{_PREV}:{_REV}", "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", f"{_REV}:{_PREV}", "--sql"))


def _blocks(heading: str) -> list[str]:
    """Every ```sql block of `#### <heading>`, to the next heading."""
    section = re.split(r"\n#{1,4} ", _DOC.read_text(encoding="utf-8").split(heading, 1)[1])[0]
    return [block.split("```", 1)[0] for block in section.split("```sql")[1:]]


def _in_order(sql: str, steps: list[str]) -> bool:
    missing = [step for step in steps if step not in sql]
    assert not missing, f"not in the rendered SQL: {missing}"
    return [sql.index(step) for step in steps] == sorted(sql.index(step) for step in steps)


def test_the_file_is_named_for_its_revision_and_chains_onto_the_head_before_it() -> None:
    assert _FILE.stem == _REV and re.fullmatch(r"\d{4}_closed_pnl_records", _REV)
    below = sorted(p.stem for p in _VERSIONS.glob("[0-9][0-9][0-9][0-9]_*.py") if p.stem < _REV)
    assert _PREV == below[-1] and f"{_PREV} -> {_REV}" in _alembic(
        "history", "-r", f"{_PREV}:{_REV}"
    )


def test_the_upgrade_is_the_sections_sql_in_one_transaction_under_a_bounded_lock_wait() -> None:
    """Sec.3.3.13's block and Sec.3.3.6's and Sec.3.3.7's second blocks word for word, in the
    revision's one transaction under `lock_timeout` (C-5.6): the two walk indexes are plain builds
    there, never CONCURRENTLY (Sec.9.3 rule 3); nothing else is created, granted or dropped."""
    [table] = _blocks("#### 3.3.13 `closed_pnl_records`")
    added = [_norm(_blocks(h)[1]) for h in ("#### 3.3.6 `executions`", "#### 3.3.7 `positions`")]
    sql = _up()
    assert _in_order(sql, [
        f"BEGIN; {_LOCK_ON} {_norm(table)}", "CREATE FUNCTION cpr_guard()",
        "REVOKE DELETE, TRUNCATE ON closed_pnl_records FROM cv_app", " ".join(added),
        "COMMENT ON COLUMN executions.closed_size", f"{_LOCK_OFF} UPDATE alembic_version",
    ])  # fmt: skip
    assert sql.count("BEGIN;") == sql.count("COMMIT;") == 1 and sql.endswith("COMMIT;")
    assert "CONCURRENTLY" not in sql and "VALIDATE CONSTRAINT ex_closed;" in added[0]
    assert sql.count("CREATE TABLE ") == 1 and sql.count("CREATE FUNCTION ") == 1
    assert sql.count("CREATE UNIQUE INDEX ") == 1 and sql.count("CREATE INDEX ") == 5
    assert sql.count("CREATE TRIGGER ") == 3 and sql.count("ENABLE ALWAYS TRIGGER ") == 3
    assert not re.search(r"GRANT |IF NOT EXISTS|INSERT INTO |SECURITY DEFINER|DROP ", sql)


def test_the_downgrade_refuses_while_anything_is_stored_then_drops_it_all() -> None:
    """C-5.2, in the one transaction under `lock_timeout`: a record, a `closed_size` or an
    `exchange_updated_ts`, each on its own, refuses the downgrade, as a stored fill is never
    written again; with none stored it drops what the upgrade added, the guard's function last."""
    refuse = (
        "LOCK TABLE closed_pnl_records, executions, position_snapshots IN SHARE MODE; DO $BODY$ "
        "BEGIN IF EXISTS (SELECT 1 FROM closed_pnl_records) OR EXISTS (SELECT 1 FROM executions "
        "WHERE closed_size IS NOT NULL) OR EXISTS (SELECT 1 FROM position_snapshots WHERE "
        "exchange_updated_ts IS NOT NULL) THEN RAISE EXCEPTION '"
    )
    drop = (
        "(C-5.2)'; END IF; END $BODY$; DROP INDEX ix_psnap_flat; ALTER TABLE position_snapshots "
        "DROP COLUMN exchange_updated_ts; DROP INDEX ix_exec_walk; ALTER TABLE executions DROP "
        "CONSTRAINT ex_closed; ALTER TABLE executions DROP COLUMN closed_size; DROP TABLE "
        f"closed_pnl_records; DROP FUNCTION cpr_guard(); {_LOCK_OFF} UPDATE alembic_version "
    )
    sql = _down()
    assert sql.startswith(f"BEGIN; {_LOCK_ON} {refuse}{_REV} downgrade refused: ")
    assert _in_order(sql, [refuse, drop])
    assert sql.count("BEGIN;") == sql.count("COMMIT;") == 1 and sql.endswith("COMMIT;")


def test_the_guard_refuses_what_section_3_3_13_lists_and_leaves_the_group_writable() -> None:
    """`trg_cpr_guard`: the identity always, each stamp once set, and only once `final_at` is set
    the venue's columns; the local figures, `divergent` and its pair stay writable, and so does
    `trade_group_id`, the composition's alone, the record final or not."""
    body = _up().split("CREATE FUNCTION cpr_guard() ", 1)[1].split("END $BODY$;", 1)[0]
    identity = ("id", "exchange_account_id", "exchange_order_id", "symbol", "side")
    venue = ("qty", "avg_entry_price", "avg_exit_price", "leverage", "closed_pnl", "closed_at",
             "venue_created_at")  # fmt: skip
    once = [(f"OLD.{c} IS NOT NULL AND NEW.{c} IS DISTINCT FROM OLD.{c}", f"'{c}'")
            for c in ("settled_at", "final_at")]  # fmt: skip
    assert re.findall(r"WHEN (.+?) THEN (NULL|'\w+')", body) == [
        *((f"NEW.{c} IS DISTINCT FROM OLD.{c}", f"'{c}'") for c in identity), *once,
        ("OLD.final_at IS NULL", "NULL"),  # not final: no venue column is frozen yet
        *((f"NEW.{c} IS DISTINCT FROM OLD.{c}", f"'{c}'") for c in venue),
    ]  # fmt: skip
    assert "trade_group_id" not in body
    assert "SET search_path = pg_catalog, pg_temp" in body and body.endswith("RETURN NEW; ")
    assert (
        "RAISE EXCEPTION 'trg_cpr_guard: closed_pnl_records.% may not change so', changed" in body
    )
    assert "USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_cpr_guard'" in body
    writes = " ".join(_DOC.read_text(encoding="utf-8").split("#### 3.3.13 ", 1)[1].split())
    assert (
        "(`qty`, the prices, `leverage`, `closed_pnl`, `closed_at`, `venue_created_at`)" in writes
    )
    assert "and `trg_cpr_guard` refuses no change to it, the record final or not;" in writes


def test_the_grants_are_pinned_and_every_p1_column_carries_the_money_comment() -> None:
    """Sec.3.3.13: `cv_app` keeps INSERT, SELECT and UPDATE (the 0024 idiom, pinned for the boot
    check, Sec.9.1); C-5.9 / Sec.12: every `numeric` column and `executions.closed_size` are P1,
    and `trade_group_id`, an id, is P0 with no comment."""
    assert (
        "DO $BODY$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN EXECUTE "
        "'REVOKE DELETE, TRUNCATE ON closed_pnl_records FROM cv_app'; END IF; END $BODY$;"
    ) in _up()
    assert GUARDED_PRIVILEGES["closed_pnl_records"] == frozenset({"DELETE", "TRUNCATE"})
    rendered = re.findall(r"COMMENT ON COLUMN (\w+)\.(\w+) IS '([^']*)';", _up())
    numeric = [c for c in _TABLE.columns if str(c.type).startswith("NUMERIC")]
    model = [(_TABLE.name, c.name, c.comment) for c in _TABLE.columns if c.comment]
    added = models.executions.c.closed_size
    assert rendered == [*model, ("executions", "closed_size", added.comment)]
    assert {c.comment for c in numeric} == {added.comment} == {models.OMS_MONEY_COMMENT}
    assert len(numeric) == len(model) == 10 and _TABLE.c.trade_group_id.comment is None
    assert models.position_snapshots.c.exchange_updated_ts.comment is None


def test_ci_mig_006_lists_the_table_so_the_revision_is_flagged_for_security_review(
    tmp_path: Path,
) -> None:
    """The orchestrator's C4: `closed_pnl_records` is on the CI-MIG-006 list, so the revision's
    own lint run warns for a security reviewer (informational, the lint still passes)."""
    text = (_CI / "security-sensitive-tables.txt").read_text(encoding="utf-8")
    assert "closed_pnl_records" in {ln.strip() for ln in text.splitlines() if ln[:1] != "#"}
    shutil.copy(_FILE, tmp_path / _FILE.name)
    r = subprocess.run(  # noqa: S603 -- fixed argv, the repo's own lint script, no shell (#981)
        [sys.executable, str(_CI / "migration_lint.py"), "--versions-dir", str(tmp_path)],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    name = tmp_path / _FILE.name
    assert f"WARN CI-MIG-006: {name}: touches security-sensitive table 'closed_pnl_records'" in (
        r.stderr
    )


def _create_index(ix: Index) -> str:
    assert ix.table is not None
    columns = ", ".join(str(e).removeprefix(f"{ix.table.name}.") for e in ix.expressions)
    where = ix.dialect_options["postgresql"]["where"]
    tail = "" if where is None else f" WHERE {where}"
    unique = "UNIQUE " if ix.unique else ""
    return f"CREATE {unique}INDEX {ix.name} ON {ix.table.name} ({columns}){tail};"


def test_the_models_mirror_the_doc_columns_checks_and_indexes() -> None:
    """`alembic check` diffs names, types, defaults and comments; the CHECK bodies, the partial
    predicates and the objects added to `executions` and `position_snapshots` are pinned here."""
    [block] = _blocks("#### 3.3.13 `closed_pnl_records`")
    table = block.split("CREATE TABLE closed_pnl_records (", 1)[1].split("\n);", 1)[0]
    assert [c.name for c in _TABLE.columns] == re.findall(r"^  ([a-z_]+)\s+[a-z]", table, re.M)
    assert [c.name for c in _TABLE.columns if not c.nullable] == [
        "id", "exchange_account_id", "symbol", "side", "closed_at", "divergent", "updated_at",
    ]  # fmt: skip
    fks = sorted(
        (fk.column_keys, fk.referred_table.name, fk.ondelete)
        for fk in _TABLE.foreign_key_constraints
    )
    assert fks == [
        (["exchange_account_id"], "exchange_accounts", "RESTRICT"),
        (["trade_group_id"], "trade_groups", "RESTRICT"),
    ]
    for model in (_TABLE, models.executions):
        checks = {
            str(c.name).removeprefix(f"ck_{model.name}_"): " ".join(str(c.sqltext).split())
            for c in model.constraints if isinstance(c, CheckConstraint)
        }  # fmt: skip
        if model is _TABLE:
            assert set(checks) == set(re.findall(r"CONSTRAINT (\w+)\s+CHECK", table))
            assert all(_norm(f"CONSTRAINT {n} CHECK ({b})") in _up() for n, b in checks.items())
        else:
            assert f"ADD CONSTRAINT ex_closed CHECK ({checks['ex_closed']}) NOT VALID;" in _up()
    assert {str(ix.name) for ix in _TABLE.indexes} == {
        "ux_cpr_order",
        "ix_cpr_day",
        "ix_cpr_pending",
        "ix_cpr_group",
    }
    assert all(_create_index(ix) in _up() for ix in _TABLE.indexes)
    for model, column, index in (
        (models.executions, "closed_size", "ix_exec_walk"),
        (models.position_snapshots, "exchange_updated_ts", "ix_psnap_flat"),
    ):
        assert model.c[column].nullable and model.c[column].server_default is None
        [ix] = [ix for ix in model.indexes if ix.name == index]
        assert _create_index(ix) in _up(), index


def test_section_9_4_registers_the_revision() -> None:
    plan = _DOC.read_text(encoding="utf-8").split("### 9.4 ", 1)[1].split("### 9.5 ", 1)[0]
    [row] = [line for line in plan.splitlines() if line.startswith(f"| `{_REV}`")]
    assert "**E29-S06 #981**" in row and f"on `{_PREV}`" in row and "CONCURRENTLY" not in row
    assert "with `trade_group_id`, `ix_cpr_group`, `trg_cpr_guard`" in row
    assert "plain `ix_exec_walk` and `ix_psnap_flat`" in row
    assert "the downgrade refuses while any of them holds data" in row
