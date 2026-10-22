"""`0048_account_default_binding` (#906 0d): the offline render, two-way plan-doc parity with 21
Sec.3.2.1's and Sec.3.2.4's fourth blocks, the trigger's shape, the downgrade, the model mirror and
the doc's registration. Real Postgres, where the version counts moves (in replica mode too) and the
catalog equals the doc: `tests/integration/storage/test_account_profiles_migration.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

from sqlalchemy import CheckConstraint, Integer
from sqlalchemy.schema import DefaultClause

from candleviewer.db.models import exchange_accounts

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0048_account_default_binding", "0047_system_events_recipient"
_UP, _DOWN = f"{_PREV}:{_REV}", f"{_REV}:{_PREV}"
_LOCK, _RESET = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
#: Alembic's version stamp, each way.
_STAMP_UP = (
    "UPDATE alembic_version SET version_num='0048_account_default_binding' "
    "WHERE alembic_version.version_num = '0047_system_events_recipient'"
)
_STAMP_DOWN = (
    "UPDATE alembic_version SET version_num='0047_system_events_recipient' "
    "WHERE alembic_version.version_num = '0048_account_default_binding'"
)


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#906)
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


def _fourth_block(section: str) -> str:
    blocks = section.split("```sql")
    assert len(blocks) > 4, f"expected a fourth ```sql block, found {len(blocks) - 1}"
    return blocks[4].split("```", 1)[0]


def _doc_blocks() -> tuple[str, str]:
    """Sec.3.2.1's fourth ```sql block (0017's, 0031's and 0041's come first), the column, and
    Sec.3.2.4's fourth (0037's three come first), the trigger."""
    doc = _DOC.read_text(encoding="utf-8")
    accounts = doc.split("#### 3.2.1 ", 1)[1].split("#### 3.2.2 ")[0]
    profiles = doc.split("#### 3.2.4 ", 1)[1].split("#### 3.2.5 ")[0]
    return _fourth_block(accounts), _fourth_block(profiles)


def test_revision_chains_onto_its_parent() -> None:
    """Whoever merges second re-parents it (C-5.3)."""
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", _UP)


def test_upgrade_is_exactly_the_plan_doc_ddl_under_a_bounded_lock_wait() -> None:
    """Two-way parity: inside the bounded lock wait the upgrade runs the column block's
    statements, then the trigger block's, and nothing else; outside it, only the transaction and
    alembic's version stamp."""
    column, trigger = _doc_blocks()
    before, rest = _up().split(_LOCK, 1)
    ddl, after = rest.split(_RESET, 1)
    assert _statements(ddl) == [*_statements(_norm(column)), *_statements(_norm(trigger))]
    assert _statements(before) == ["BEGIN"]
    assert _statements(after) == [_STAMP_UP, "COMMIT"]


def test_every_account_starts_at_one_on_the_fast_path_and_nothing_is_granted() -> None:
    """A constant default, so the ALTER rewrites no row (Sec.9.3 rule 2) and every account starts
    at 1, its bootstrap `Default` being its first binding: no backfill, no GRANT (`cv_app`'s
    table-level DML covers the column) and no comment tag (P0)."""
    sql = _up()
    assert "ADD COLUMN default_binding_version integer NOT NULL DEFAULT 1," in sql
    assert "ADD CONSTRAINT ea_default_binding_version CHECK (default_binding_version >= 1)" in sql
    for absent in ("GRANT", "REVOKE", "COMMENT ON", "UPDATE exchange_accounts SET"):
        assert absent not in sql, f"{absent!r} is outside this revision"
    # The only UPDATEs: the trigger function's own, and alembic's version stamp.
    assert re.findall(r"\bUPDATE (?!OF )(\S+)", sql) == [
        "public.exchange_accounts",
        "alembic_version",
    ]


def test_only_a_profile_becoming_the_default_bumps_and_replica_mode_cannot_skip_it() -> None:
    """The trigger fires on an UPDATE of `is_default` only, and only for the row that becomes the
    default, so an insert, an unset, a re-set default and every other edit leave the version.
    `ENABLE ALWAYS` keeps it firing under `session_replication_role = replica`. The function pins
    its `search_path`, is no SECURITY DEFINER (`cv_app` holds UPDATE on `exchange_accounts`) and
    refuses nothing."""
    sql = _up()
    assert (
        "CREATE TRIGGER trg_ap_default_binding AFTER UPDATE OF is_default ON account_profiles "
        "FOR EACH ROW WHEN (NEW.is_default AND NOT OLD.is_default) "
        "EXECUTE FUNCTION ap_default_binding_bump();"
    ) in sql
    assert "ALTER TABLE account_profiles ENABLE ALWAYS TRIGGER trg_ap_default_binding;" in sql
    assert (
        "UPDATE public.exchange_accounts SET default_binding_version = default_binding_version + 1 "
        "WHERE id = NEW.exchange_account_id; RETURN NULL;"
    ) in sql
    assert "SET search_path = pg_catalog, pg_temp" in sql
    assert "SECURITY DEFINER" not in sql and "RAISE" not in sql


def test_downgrade_drops_the_trigger_its_function_then_the_column_under_a_bounded_lock_wait() -> (
    None
):
    """Rollback only: the versions are lost, so a tag issued before the downgrade could match
    again after a re-upgrade."""
    assert _statements(_down()) == [
        "BEGIN",
        _LOCK.rstrip(";"),
        "DROP TRIGGER trg_ap_default_binding ON account_profiles",
        "DROP FUNCTION ap_default_binding_bump()",
        "ALTER TABLE exchange_accounts DROP CONSTRAINT ea_default_binding_version, "
        "DROP COLUMN default_binding_version",
        _RESET.rstrip(";"),
        _STAMP_DOWN,
        "COMMIT",
    ]


def test_the_model_mirrors_the_column_and_its_check() -> None:
    """`alembic check` (CI-MIG-002) compares the type and nullability, never a CHECK's body."""
    column = exchange_accounts.c.default_binding_version
    assert type(column.type) is Integer and not column.nullable and column.comment is None
    assert isinstance(column.server_default, DefaultClause)
    assert str(column.server_default.arg) == "1"
    checks = {
        str(c.name).removeprefix("ck_exchange_accounts_"): " ".join(str(c.sqltext).split())
        for c in exchange_accounts.constraints
        if isinstance(c, CheckConstraint)
    }
    assert checks["ea_default_binding_version"] == "default_binding_version >= 1"


def test_21_registers_the_revision_and_the_column() -> None:
    """21 Sec.9.4 keeps a row per revision (C-11.2); Sec.3.2.1's column table lists the column."""
    doc = _DOC.read_text(encoding="utf-8")
    rows = [r for r in doc.split("### 9.4 ", 1)[1].splitlines() if r.startswith(f"| `{_REV}` ")]
    assert len(rows) == 1 and "**#906 0d**" in rows[0]
    accounts = doc.split("#### 3.2.1 ", 1)[1].split("#### 3.2.2 ")[0]
    assert re.search(
        r"^\| `default_binding_version` +\| integer +\| no +\| `1` +\|", accounts, re.M
    )
