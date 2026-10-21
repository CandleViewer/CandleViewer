"""`0042_sessions_view_as` (#3085 S2a): the offline render, plan-doc parity, the downgrade and the
model mirror; `alembic check` diffs neither CHECK bodies nor index predicates, so both are pinned
here. Real Postgres: tests/integration/storage/test_sessions_view_as_migration.py."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import timedelta
from functools import cache
from pathlib import Path

from sqlalchemy import CheckConstraint, Index, Text
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

from candleviewer.auth.view_as import VIEW_AS_TTL, ViewAsEndReason
from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0042_sessions_view_as", "0041_account_env_write_once"
_LOCK, _RESET = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
_SHAPE = "sessions_view_as_shape"
#: The eight columns in their `ADD COLUMN` order, each with the type it is added with.
_COLUMNS = {
    "view_as_context_id": "uuid",
    "view_as_target_user_id": "uuid REFERENCES users(id) ON DELETE RESTRICT",
    "view_as_started_at": "timestamptz",
    "view_as_expires_at": "timestamptz",
    "view_as_ended_at": "timestamptz",
    "view_as_end_recorded_at": "timestamptz",
    "view_as_cleared_at": "timestamptz",
    "view_as_end_reason": "text",
}
_INDEXES = {
    "ix_sessions_view_as_due": "(view_as_expires_at) "
    "WHERE view_as_context_id IS NOT NULL AND view_as_end_recorded_at IS NULL;",
    "ix_sessions_view_as_target": "(view_as_target_user_id) "
    "WHERE view_as_context_id IS NOT NULL AND view_as_ended_at IS NULL;",
    "ix_sessions_view_as_context": "(view_as_context_id) WHERE view_as_context_id IS NOT NULL;",
}


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#3085)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments, collapse whitespace and the spaces just inside parentheses, and the `;`
    alembic appends to a statement that has one, so layout never matters."""
    flat = " ".join(re.sub(r"--[^\n]*", "", sql).split())
    return flat.replace("( ", "(").replace(" )", ")").replace(";;", ";")


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", f"{_PREV}:{_REV}", "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", f"{_REV}:{_PREV}", "--sql"))


@cache
def _ddl() -> str:
    """Sec.3.1.4's second ```sql block (this revision's DDL), to its fence."""
    section = _DOC.read_text(encoding="utf-8").split("#### 3.1.4 ", 1)[1].split("#### 3.1.5 ")[0]
    return _norm(section.split("```sql", 2)[2].split("```", 1)[0])


def _in_order(sql: str, steps: list[str]) -> bool:
    missing = [step for step in steps if step not in sql]
    assert not missing, f"not in the rendered SQL: {missing}"
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def _checks() -> dict[str, str]:
    """The model's view-as CHECKs by their given name (the convention prefixes `ck_sessions_`)."""
    return {
        str(c.name).removeprefix("ck_sessions_"): _norm(str(c.sqltext))
        for c in models.sessions.constraints
        if isinstance(c, CheckConstraint) and "view_as" in str(c.name)
    }


def _create_index(ix: Index) -> str:
    """The `CREATE INDEX` statement a model index stands for, in the migration's spelling."""
    columns = ", ".join(str(e).removeprefix("sessions.") for e in ix.expressions)
    where = ix.dialect_options["postgresql"]["where"]
    return f"CREATE INDEX {ix.name} ON sessions ({columns}) WHERE {where};"


def test_revision_chains_onto_the_head_it_was_written_on_and_is_registered() -> None:
    """Whoever merges second re-parents it (C-5.3); 21 Sec.9.4 keeps a row per revision."""
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")
    assert f"| `{_REV}` " in _DOC.read_text(encoding="utf-8").split("### 9.4 ", 1)[1]


def test_upgrade_is_the_plan_doc_block_verbatim_adding_only_nullable_columns() -> None:
    """Sec.3.1.4's second block, verbatim, under `lock_timeout` (C-5.6); nullable columns with no
    default (C-5.1, Sec.9.3 rule 2); ids and times only (Sec.12, P0): no comment tag, no GRANT."""
    assert _ddl().startswith("ALTER TABLE sessions ADD COLUMN view_as_context_id uuid,")
    assert _ddl().endswith(_INDEXES["ix_sessions_view_as_context"])
    assert _in_order(_up(), [_LOCK, _ddl(), _RESET, "UPDATE alembic_version"])
    added = dict(re.findall(r"ADD COLUMN (\w+) ([^,]+),", _ddl()))
    assert added == _COLUMNS and list(added) == list(_COLUMNS) and "DEFAULT" not in _ddl()
    for absent in ("GRANT", "COMMENT ON", "UPDATE sessions", "CREATE TABLE"):
        assert absent not in _up(), f"{absent!r} is outside this revision"


def test_downgrade_refuses_while_a_context_exists_then_drops_only_what_upgrade_added() -> None:
    """C-5.2: it refuses while any row names a context; otherwise it drops the indexes, the
    CHECKs and the eight columns (the FK goes with its column), and nothing else."""
    columns = ", ".join(f"DROP COLUMN {name}" for name in reversed(_COLUMNS))
    assert _in_order(
        _down(),
        [
            _LOCK,
            "LOCK TABLE sessions IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM sessions WHERE view_as_context_id IS NOT NULL) THEN",
            "RAISE EXCEPTION '0042_sessions_view_as downgrade refused:",
            "DROP INDEX ix_sessions_view_as_context;",
            "DROP INDEX ix_sessions_view_as_target;",
            "DROP INDEX ix_sessions_view_as_due;",
            "ALTER TABLE sessions DROP CONSTRAINT sessions_view_as_end_reason, "
            f"DROP CONSTRAINT sessions_view_as_shape, {columns};",
            _RESET,
        ],
    )
    assert _down().count("DROP ") == 3 + 2 + 8 and "(C-5.2)" in _down()


def test_the_model_mirrors_the_columns_and_the_restricting_target_fk() -> None:
    """`alembic check` (CI-MIG-002) compares types, nullability and the FK's `ON DELETE`."""
    columns = [models.sessions.c[name] for name in _COLUMNS]
    assert [(c.nullable, c.server_default, c.comment) for c in columns] == [(True, None, None)] * 8
    ids, times, (reason,) = columns[:2], columns[2:7], columns[7:]
    assert all(isinstance(c.type, UUID) and c.type.as_uuid for c in ids)
    assert all(isinstance(c.type, TIMESTAMP) and c.type.timezone for c in times)
    assert isinstance(reason.type, Text)
    (fk,) = models.sessions.c.view_as_target_user_id.foreign_keys
    assert (fk.column.table.name, fk.column.name, fk.ondelete) == ("users", "id", "RESTRICT")


def test_the_model_mirrors_the_check_constraints_and_the_shape_is_null_safe() -> None:
    """A bare CHECK passes a NULL result; `IS TRUE` refuses it (the `ap_sizing_shape` idiom)."""
    assert set(_checks()) == {_SHAPE, "sessions_view_as_end_reason"}
    for name, body in _checks().items():
        assert f"CONSTRAINT {name} CHECK ({body})" in _ddl(), name
    assert _checks()[_SHAPE].endswith(") IS TRUE")


def test_the_checks_pin_the_ttl_the_one_order_and_the_end_reasons() -> None:
    """As `_shape`: `VIEW_AS_TTL`, and no order between `ended_at`, `end_recorded_at` and
    `cleared_at`, which a clock stepped between two writes could break (`auth/view_as.py`); the
    reasons are `ViewAsEndReason`'s, exactly."""
    (minutes,) = re.findall(r"started_at \+ interval '(\d+) minutes'", _checks()[_SHAPE])
    assert timedelta(minutes=int(minutes)) == VIEW_AS_TTL
    compared = re.findall(r"(view_as_\w+) (?:<=|>=|<|>) (view_as_\w+)", _checks()[_SHAPE])
    assert compared == [("view_as_ended_at", "view_as_expires_at")]
    reasons = re.findall(r"'(\w+)'", _checks()["sessions_view_as_end_reason"])
    assert sorted(reasons) == sorted(reason.value for reason in ViewAsEndReason)


def test_the_model_mirrors_the_three_partial_indexes_built_in_the_transaction() -> None:
    """A plain build under `lock_timeout`, never CONCURRENTLY (`0034_order_vocabulary`)."""
    indexes = {str(ix.name): ix for ix in models.sessions.indexes if "view_as" in str(ix.name)}
    assert set(indexes) == set(_INDEXES)
    for name, ix in indexes.items():
        assert _create_index(ix) == f"CREATE INDEX {name} ON sessions {_INDEXES[name]}"
        assert _create_index(ix) in _ddl()
    assert _up().count("CREATE INDEX ") == 3 and "CONCURRENTLY" not in _up()
