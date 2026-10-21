"""`0047_system_events_recipient` (#3085 S13a): the offline render, plan-doc parity, the downgrade
and the model mirror; `alembic check` diffs no index predicate, so it is pinned here. Real
Postgres: tests/integration/storage/test_system_events_recipient_migration.py."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

from sqlalchemy.dialects.postgresql import UUID

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0047_system_events_recipient", "0046_audit_signing_keys"
_LOCK, _RESET = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
_ADD = (
    "ALTER TABLE system_events ADD COLUMN recipient_user_id uuid "
    "REFERENCES users(id) ON DELETE SET NULL;"
)
_INDEX = (
    "CREATE INDEX ix_se_recipient ON system_events (recipient_user_id, event_ts DESC) "
    "WHERE recipient_user_id IS NOT NULL;"
)


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
    """Sec.3.10.2's second ```sql block (this revision's DDL), to its fence."""
    section = _DOC.read_text(encoding="utf-8").split("#### 3.10.2 ", 1)[1].split("#### 3.10.2a ")[0]
    return _norm(section.split("```sql", 2)[2].split("```", 1)[0])


def _in_order(sql: str, steps: list[str]) -> bool:
    missing = [step for step in steps if step not in sql]
    assert not missing, f"not in the rendered SQL: {missing}"
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def test_revision_chains_onto_the_head_it_was_written_on_and_is_registered() -> None:
    """Whoever merges second re-parents it (C-5.3); 21 Sec.9.4 keeps a row per revision."""
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")
    assert f"| `{_REV}` " in _DOC.read_text(encoding="utf-8").split("### 9.4 ", 1)[1]


def test_upgrade_is_the_plan_doc_block_verbatim_adding_one_nullable_column() -> None:
    """Sec.3.10.2's second block, verbatim, under `lock_timeout` (C-5.6): one nullable column with
    no default (C-5.1, Sec.9.3 rule 2) and its partial index, no GRANT, no backfill."""
    assert _ddl() == f"{_ADD} {_INDEX}"
    assert _in_order(_up(), [_LOCK, _ADD, _INDEX, _RESET, "UPDATE alembic_version"])
    for absent in ("GRANT", "COMMENT ON", "UPDATE system_events", "DEFAULT ", "CONCURRENTLY"):
        assert absent not in _up(), f"{absent!r} is outside this revision"


def test_downgrade_refuses_while_a_row_is_addressed_then_drops_only_what_upgrade_added() -> None:
    """C-5.2: it refuses while any row is addressed (a user's notice would become the Owner's
    alone); otherwise it drops the index and the column (the FK goes with it), and nothing else."""
    assert _in_order(
        _down(),
        [
            _LOCK,
            "LOCK TABLE system_events IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM system_events WHERE recipient_user_id IS NOT NULL) THEN",
            "RAISE EXCEPTION '0047_system_events_recipient downgrade refused:",
            "DROP INDEX ix_se_recipient;",
            "ALTER TABLE system_events DROP COLUMN recipient_user_id;",
            _RESET,
        ],
    )
    assert _down().count("DROP ") == 2 and "(C-5.2)" in _down()


def test_the_model_mirrors_the_column_its_fk_and_the_partial_index() -> None:
    """`alembic check` (CI-MIG-002) compares the type, nullability and the FK's `ON DELETE`; the
    index predicate it does not, so it is compared here."""
    column = models.system_events.c.recipient_user_id
    assert (column.nullable, column.server_default, column.comment) == (True, None, None)
    (fk,) = column.foreign_keys
    assert (fk.column.table.name, fk.column.name, fk.ondelete) == ("users", "id", "SET NULL")
    assert isinstance(fk.column.type, UUID)
    (ix,) = (ix for ix in models.system_events.indexes if ix.name == "ix_se_recipient")
    columns = ", ".join(str(e).removeprefix("system_events.") for e in ix.expressions)
    where = ix.dialect_options["postgresql"]["where"]
    assert f"CREATE INDEX ix_se_recipient ON system_events ({columns}) WHERE {where};" == _INDEX
