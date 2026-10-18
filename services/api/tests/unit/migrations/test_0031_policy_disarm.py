"""`0031_policy_disarm` (#836 slice 2d): offline render, plan-doc parity, the downgrade guard, the
code CHECK against every rule the job can disarm for, and the model mirror.
Real Postgres: `tests/integration/storage/test_policy_disarm_migration.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

from candleviewer.accounts import selfcheck
from candleviewer.accounts.verification import Rule
from candleviewer.db.models import exchange_accounts

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_REV, _PREV = "0031_policy_disarm", "0030_auth_keys"
_COLUMNS = ("policy_disarm_code", "policy_disarmed_at", "policy_disarm_audited_at")


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#836)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments and collapse whitespace, so layout never matters."""
    return " ".join(re.sub(r"--[^\n]*", "", sql).split())


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", f"{_PREV}:{_REV}", "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", f"{_REV}:{_PREV}", "--sql"))


def _in_order(sql: str, steps: list[str]) -> bool:
    positions = [sql.index(step) for step in steps]  # a step that is missing raises ValueError
    return positions == sorted(positions)


def test_upgrade_is_the_plan_doc_ddl_verbatim_under_a_bounded_lock_wait() -> None:
    """The second ```sql block of Sec.3.2.1, to its fence; no GRANT and no comment tag (P0)."""
    section = _DOC.read_text(encoding="utf-8").split("#### 3.2.1 ", 1)[1].split("#### 3.2.2 ")[0]
    ddl = _norm(section.split("```sql", 2)[2].split("```", 1)[0])
    assert ddl.startswith("ALTER TABLE exchange_accounts ADD COLUMN policy_disarm_code text,")
    lock, ddl_end, reset = "SET LOCAL lock_timeout = '5s';", ddl[-40:], "lock_timeout = DEFAULT;"
    assert _in_order(_up(), [lock, ddl, ddl_end, reset])
    assert "GRANT" not in _up() and "COMMENT ON" not in _up()


def test_downgrade_refuses_while_a_record_is_owed_then_drops_what_it_added() -> None:
    assert _in_order(
        _down(),
        [
            "SET LOCAL lock_timeout = '5s';",
            "LOCK TABLE exchange_accounts IN SHARE MODE;",
            "WHERE policy_disarmed_at IS NOT NULL AND policy_disarm_audited_at IS NULL) THEN",
            "RAISE EXCEPTION '0031_policy_disarm downgrade refused:",
            "ALTER TABLE exchange_accounts DROP CONSTRAINT ea_disarm_shape,",
            "DROP COLUMN policy_disarm_code;",
            "SET LOCAL lock_timeout = DEFAULT;",
        ],
    )
    assert "(C-2.9)" in _down() and "(C-5.2)" in _down()


def test_every_rule_the_job_can_disarm_for_fits_the_code_check() -> None:
    """The force-disable and its code commit in one statement, so a code the CHECK refused would
    refuse the disable too (C-2.8): every rule fits, and the CHECK is the job's own code shape."""
    found = re.search(r"CHECK \(policy_disarm_code ~ '([^']+)'\)", _up())
    assert found is not None and found.group(1) == f"^{selfcheck._CODE.pattern}$"
    assert [rule for rule in Rule if not re.fullmatch(found.group(1), rule.value)] == []


def test_the_model_mirrors_the_columns_nullable_with_no_default_or_comment() -> None:
    columns = [exchange_accounts.c[name] for name in _COLUMNS]
    assert [(c.nullable, c.server_default, c.comment) for c in columns] == [(True, None, None)] * 3
    checks = {str(c.name) for c in exchange_accounts.constraints}
    assert {f"ck_exchange_accounts_ea_disarm_{n}" for n in ("code_fmt", "shape")} <= checks
