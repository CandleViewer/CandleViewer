"""`0057_se_component_statechart` (E42-T07 #1025): offline render, plan-doc parity
(21 Sec.3.10.2, the 0057 block), the downgrade guard and the model mirror. Real Postgres (the
widened CHECK, the round trip and the refused downgrade):
tests/integration/storage/test_system_events_statechart_migration.py."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

from sqlalchemy import CheckConstraint

from candleviewer.db import models

_ROOT = Path(__file__).resolve().parents[3]
_DOC = _ROOT.parents[1] / "docs" / "plan" / "21-database-schema.md"
_FILE = (
    _ROOT / "candleviewer" / "migrations" / "versions"
    / "0057_se_component_statechart.py"
)  # fmt: skip
_LOCK, _RESET = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
_OLD = (
    "'ingestion','book_engine','bars','orderflow','oms','rules','recorder','replay','api','ws',"
    "'db','exchange','auth','backup'"
)
_NEW = _OLD + ",'statechart'"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rev_0057", _FILE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MOD = _module()
_REV, _PREV = _MOD.revision, _MOD.down_revision


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#1025)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    return " ".join(re.sub(r"--[^\n]*", "", sql).split()).replace("( ", "(").replace(";;", ";")


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", f"{_PREV}:{_REV}", "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", f"{_REV}:{_PREV}", "--sql"))


def _in_order(sql: str, steps: list[str]) -> bool:
    missing = [step for step in steps if step not in sql]
    assert not missing, f"not in the rendered SQL: {missing}"
    positions = [sql.index(step) for step in steps]
    return positions == sorted(positions)


def _doc_section() -> str:
    return _DOC.read_text(encoding="utf-8").split("#### 3.10.2 ", 1)[1].split("#### 3.10.2a ")[0]


def test_revision_is_named_0057_and_chains_onto_0056() -> None:
    assert (_REV, _PREV) == ("0057_se_component_statechart", "0056_sessions_lock_state")
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")


def test_the_revision_register_lists_the_revision() -> None:
    assert f"| `{_REV}` " in _DOC.read_text(encoding="utf-8").split("### 9.4 ", 1)[1]


def test_upgrade_is_the_0057_block_not_valid_then_validated_under_a_bounded_lock_wait() -> None:
    (block,) = [
        _norm(b.split("```", 1)[0])
        for b in _doc_section().split("```sql")[1:]
        if b.lstrip().startswith("-- 0057_se_component_statechart")
    ]
    assert block.startswith("ALTER TABLE system_events DROP CONSTRAINT se_component,")
    assert _in_order(_up(), [
        _LOCK,
        f"ADD CONSTRAINT se_component CHECK (component IN ({_NEW})) NOT VALID;",
        "ALTER TABLE system_events VALIDATE CONSTRAINT se_component;",
        _RESET,
    ])  # fmt: skip
    assert block in _up()
    for absent in ("GRANT", "DELETE FROM system_events", "UPDATE system_events"):
        assert absent not in _up(), absent


def test_the_plan_ddl_lists_statechart_in_se_component() -> None:
    assert f"CONSTRAINT se_component CHECK (component IN ({_NEW}))" in _doc_section()


def test_downgrade_refuses_while_a_statechart_row_exists_then_restores_0008s_list() -> None:
    """C-5.2: 0008's CHECK cannot hold a `statechart` row, and dropping one is not a rollback."""
    assert _in_order(
        _down(),
        [
            _LOCK,
            "LOCK TABLE system_events IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM system_events WHERE component = 'statechart') THEN",
            "RAISE EXCEPTION '0057_se_component_statechart downgrade refused:",
            f"ADD CONSTRAINT se_component CHECK (component IN ({_OLD})) NOT VALID;",
            "ALTER TABLE system_events VALIDATE CONSTRAINT se_component;",
            _RESET,
        ],
    )
    assert "(C-5.2)" in _down() and "DELETE FROM system_events" not in _down()


def test_the_model_mirrors_the_widened_check() -> None:
    (check,) = [
        c for c in models.system_events.constraints
        if isinstance(c, CheckConstraint) and str(c.name).endswith("se_component")
    ]  # fmt: skip
    assert f"CHECK ({_norm(str(check.sqltext))}) NOT VALID" in _up()
