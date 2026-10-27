"""`0053_tg_frozen_after_draft` (E28-T05 #909, SEC-2-04): offline render, plan-doc parity, the
function's shape and the downgrade, which restores 0039's function verbatim. Real Postgres:
`tests/integration/storage/test_tg_frozen_after_draft_pg.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

from candleviewer.storage.repositories.trade_groups import (
    CREATE_ONLY_GROUP_COLUMNS,
    GROUP_PATCH_COLUMNS,
    WRITE_ONCE_GROUP_COLUMNS,
)

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_0039 = _ROOT / "candleviewer" / "migrations" / "versions" / "0039_trade_groups.py"
_REV, _PREV = "0053_tg_frozen_after_draft", "0052_ia_purge_anchor"
_LOCK, _RESET = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
_STAMP = "UPDATE alembic_version SET version_num='{}' WHERE alembic_version.version_num = '{}';"
_FROZEN = ("symbol", "side", "entry_type", "origin", "is_paper", "algo_params", "origin_rule_id")


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#909)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """No `--` comments, one space between tokens, and the `;` alembic appends to a statement that
    has one folded."""
    flat = " ".join(re.sub(r"--[^\n]*", "", sql).split())
    return flat.replace("( ", "(").replace(" )", ")").replace(";;", ";")


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", f"{_PREV}:{_REV}", "--sql"))


def _function(sql: str) -> str:
    """The `tg_write_once()` that `sql` (normalized) creates, to its closing `END`."""
    start = sql.index("FUNCTION tg_write_once()")
    return sql[start : sql.index("END $BODY$;", start) + len("END $BODY$;")]


def _section() -> str:
    text = _DOC.read_text(encoding="utf-8")
    return text.split("#### 3.3.2 ", 1)[1].split("#### 3.3.3 ", 1)[0]


def _old() -> str:
    """0039's function, normalized."""
    return _function(_norm(_0039.read_text(encoding="utf-8")))


def test_revision_chains_onto_0052() -> None:
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")


def test_upgrade_is_exactly_the_plan_doc_block_under_a_bounded_lock_wait() -> None:
    block = _norm(_section().split("```sql")[3].split("```", 1)[0])  # the third fence
    assert _up() == f"BEGIN; {_LOCK} {block} {_RESET} {_STAMP.format(_REV, _PREV)} COMMIT;"
    assert _section().count("```sql") == 3  # the parity walks the fences by index


def test_the_function_keeps_0039s_list_and_freezes_the_create_only_columns_after_draft() -> None:
    new = _function(_up())
    kept = _old().split("changed := CASE ", 1)[1].split(" END; IF", 1)[0]
    assert f"changed := CASE {kept} WHEN OLD.status <> 'draft' THEN CASE " in new
    after = new.split("'draft'", 1)[1]
    arms = re.findall(r"WHEN NEW\.(\w+) IS DISTINCT FROM OLD\.\1 (?:AND|THEN)", after)
    assert tuple(arms) == _FROZEN and set(arms) == CREATE_ONLY_GROUP_COLUMNS
    assert not set(arms) & (WRITE_ONCE_GROUP_COLUMNS | set(GROUP_PATCH_COLUMNS))  # the CAS passes
    assert new.count("OLD.status") == 1  # one place decides what a draft may still take
    assert not re.search(r"NEW\.\w+ *(=|<>|!=)", new)  # IS DISTINCT FROM throughout: changes only


def test_a_refusal_names_the_column_never_a_value_and_the_function_runs_as_its_caller() -> None:
    up, using = _up(), "USING ERRCODE = 'check_violation', CONSTRAINT = 'trg_tg_write_once'"
    assert re.findall(r"RAISE EXCEPTION '([^']*)'(.*?);", up) == [
        ("trg_tg_write_once: trade_groups.% is write-once", f", changed {using}")
    ]
    assert set(re.findall(r"THEN '(\w+)'", up)) == WRITE_ONCE_GROUP_COLUMNS | set(_FROZEN)
    assert "SET search_path = pg_catalog, pg_temp" in up and "SECURITY DEFINER" not in up
    assert re.findall(r"(?<!DISTINCT )\bFROM (\S+)", _function(up)) == ["public.rules"]
    assert not re.search(r"\b(?:CREATE TRIGGER|ALTER TABLE|DROP)\b", up)  # the trigger stays as is


def test_downgrade_restores_0039s_function_under_a_bounded_lock_wait() -> None:
    down = _norm(_alembic("downgrade", f"{_REV}:{_PREV}", "--sql"))
    stamp = _STAMP.format(_PREV, _REV)
    assert down == f"BEGIN; {_LOCK} CREATE OR REPLACE {_old()} {_RESET} {stamp} COMMIT;"


def test_the_plan_doc_names_the_frozen_columns_the_carve_out_and_closes_sec_2_04() -> None:
    section = _section()
    (bullet,) = re.findall(r"^- `trg_tg_write_once` .*$", section, re.MULTILINE)
    named = (*sorted(WRITE_ONCE_GROUP_COLUMNS), *_FROZEN, "draft")
    assert all(f"`{name}`" in bullet for name in named) and "ON DELETE SET NULL" in bullet
    assert _REV in section and "left to E28-T05" not in section  # 0039's deferral is closed
