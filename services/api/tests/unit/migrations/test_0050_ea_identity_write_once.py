"""`0050_ea_identity_write_once` (#3968, SR-E27-13): offline render, two-way plan-doc parity, the
trigger's shape, and the downgrade. The application side (no UPDATE or upsert assigns
`exchange_uid` or `kind` after the INSERT, no patch or PATCH body carries either, the store's
typed error): `tests/unit/storage/test_account_env_write_once_surface.py` and
`tests/unit/storage/test_accounts_store_sqlalchemy.py`.
Real Postgres: `tests/integration/storage/test_ea_identity_write_once_migration.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0050_ea_identity_write_once", "0049_ea_env_parent_always"
_UP, _DOWN = f"{_PREV}:{_REV}", f"{_REV}:{_PREV}"
_LOCK, _RESET = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
#: Alembic's version stamp, each way.
_STAMP_UP = (
    "UPDATE alembic_version SET version_num='0050_ea_identity_write_once' "
    "WHERE alembic_version.version_num = '0049_ea_env_parent_always'"
)
_STAMP_DOWN = (
    "UPDATE alembic_version SET version_num='0049_ea_env_parent_always' "
    "WHERE alembic_version.version_num = '0050_ea_identity_write_once'"
)


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#3968)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    flat = " ".join(re.sub(r"--[^\n]*", "", sql).split())
    return flat.replace("( ", "(").replace(" )", ")")


def _statements(sql: str) -> list[str]:
    """`sql` cut at every `;`, blanks dropped (alembic ends each `op.execute` with one more `;`).
    A function body is cut too, the same way on both sides of a comparison."""
    return [part.strip() for part in sql.split(";") if part.strip()]


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", _UP, "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", _DOWN, "--sql"))


def _doc_block() -> str:
    """Sec.3.2.1's sixth ```sql block (0017's, 0031's, 0041's, 0048's and 0049's come first)."""
    section = _DOC.read_text(encoding="utf-8").split("#### 3.2.1 ", 1)[1].split("#### 3.2.2 ")[0]
    return section.split("```sql")[6].split("```", 1)[0]


def test_revision_chains_onto_0049() -> None:
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", _UP)


def test_upgrade_is_exactly_the_plan_doc_ddl_under_a_bounded_lock_wait() -> None:
    """Two-way parity: inside the bounded lock wait the upgrade runs the doc's block and nothing
    else, and the block holds nothing the upgrade does not run; outside it, only the transaction
    and alembic's version stamp."""
    before, rest = _up().split(_LOCK, 1)
    ddl, after = rest.split(_RESET, 1)
    assert _statements(ddl) == _statements(_norm(_doc_block()))
    assert _statements(before) == ["BEGIN"]
    assert _statements(after) == [_STAMP_UP, "COMMIT"]


def test_a_change_of_identity_meets_a_whole_row_trigger_replica_mode_cannot_skip() -> None:
    """SR-E27-13: an account never takes another id or comes to name another exchange UID, and
    never turns from a main account into a sub-account or back, once it exists (#3968; `id` by the
    ruling on SEC-2758-02). The trigger fires on every UPDATE of a row, not only one that names a
    guarded column, like 0041's guard for `env`."""
    sql = _up()
    assert (
        "CREATE TRIGGER trg_ea_identity_write_once BEFORE UPDATE ON exchange_accounts "
        "FOR EACH ROW EXECUTE FUNCTION ea_identity_write_once();"
    ) in sql
    assert "ALTER TABLE exchange_accounts ENABLE ALWAYS TRIGGER trg_ea_identity_write_once;" in sql
    assert "IF NEW.id IS DISTINCT FROM OLD.id THEN" in sql
    assert "IF NEW.exchange_uid IS DISTINCT FROM OLD.exchange_uid THEN" in sql
    assert "IF NEW.kind IS DISTINCT FROM OLD.kind THEN" in sql and "RETURN NEW;" in sql
    assert "NEW.env" not in sql  # `env` keeps 0041's own guard
    # It never rewrites NEW, so sorting after 0041's guard changes nothing that guard judges.
    assert not re.search(r"\bNEW\.\w+\s*:=", sql)


def test_each_refusal_names_its_trigger_and_column_and_never_a_value() -> None:
    sql = _up()
    assert "SET search_path = pg_catalog, pg_temp" in sql and "SECURITY DEFINER" not in sql
    using = " USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_ea_identity_write_once'"
    assert re.findall(r"RAISE EXCEPTION '([^']*)'(.*?);", sql) == [
        ("trg_ea_identity_write_once: exchange_accounts.id is write-once", using),
        ("trg_ea_identity_write_once: exchange_accounts.exchange_uid is write-once", using),
        ("trg_ea_identity_write_once: exchange_accounts.kind is write-once", using),
    ]


def test_downgrade_drops_only_the_trigger_then_its_function_under_a_bounded_lock_wait() -> None:
    """Exactly two DROPs: `trg_ea_env_write_once` (0041) and every row stay."""
    assert _statements(_down()) == [
        "BEGIN",
        _LOCK.rstrip(";"),
        "DROP TRIGGER trg_ea_identity_write_once ON exchange_accounts",
        "DROP FUNCTION ea_identity_write_once()",
        _RESET.rstrip(";"),
        _STAMP_DOWN,
        "COMMIT",
    ]
