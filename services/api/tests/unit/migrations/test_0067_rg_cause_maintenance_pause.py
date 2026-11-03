"""`0067_rg_cause_maintenance_pause` (#5629): offline render, plan-doc parity (21 Sec.3.6.2, the
0067 block), the downgrade guard and the model mirror. The real Postgres round trip is the
`migrations` CI job (alembic upgrade/downgrade/upgrade)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
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
_REPO = _ROOT.parents[1]
_DOC = _REPO / "docs" / "plan" / "21-database-schema.md"
_LOCKFILE = _ROOT / "candleviewer" / "migrations" / "lockfile.json"
_FILE = (
    _ROOT / "candleviewer" / "migrations" / "versions"
    / "0067_rg_cause_maintenance_pause.py"
)  # fmt: skip
_LOCK, _RESET = "SET LOCAL lock_timeout = '5s';", "SET LOCAL lock_timeout = DEFAULT;"
_OLD = "'ws_disconnect','backpressure_drop','process_restart','seq_jump','exchange_outage'"
_NEW = _OLD + ",'maintenance_pause'"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rev_0067", _FILE)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_MOD = _module()
_REV, _PREV = _MOD.revision, _MOD.down_revision


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#5629)
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
    return _DOC.read_text(encoding="utf-8").split("#### 3.6.2 ", 1)[1].split("#### 3.6.3 ")[0]


def test_revision_is_named_0067_and_chains_onto_0064() -> None:
    assert (_REV, _PREV) == ("0067_rg_cause_maintenance_pause", "0064_orders_origin")
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")


def test_the_lockfile_names_the_revision() -> None:
    """`tools/ci/verify_migration_lockfile.py`'s ledger: the file's path, its digest, its parent."""
    entry = json.loads(_LOCKFILE.read_text(encoding="utf-8"))["revisions"][_REV]
    assert entry == {
        "path": str(_FILE.relative_to(_REPO)),
        "sha256": hashlib.sha256(_FILE.read_bytes()).hexdigest(),
        "down_revision": _PREV,
    }


def test_the_revision_register_lists_the_revision() -> None:
    assert f"| `{_REV}` " in _DOC.read_text(encoding="utf-8").split("### 9.4 ", 1)[1]


def test_upgrade_is_the_0067_block_not_valid_then_validated_under_a_bounded_lock_wait() -> None:
    (block,) = [
        _norm(b.split("```", 1)[0])
        for b in _doc_section().split("```sql")[1:]
        if b.lstrip().startswith("-- 0067_rg_cause_maintenance_pause")
    ]
    assert block.startswith("ALTER TABLE recording_gaps DROP CONSTRAINT rg_cause,")
    assert _in_order(_up(), [
        _LOCK,
        f"ADD CONSTRAINT rg_cause CHECK (cause IN ({_NEW})) NOT VALID;",
        "ALTER TABLE recording_gaps VALIDATE CONSTRAINT rg_cause;",
        _RESET,
    ])  # fmt: skip
    assert block in _up()
    for absent in ("GRANT", "DELETE FROM recording_gaps", "UPDATE recording_gaps"):
        assert absent not in _up(), absent


def test_the_plan_ddl_lists_maintenance_pause_in_rg_cause() -> None:
    assert f"CONSTRAINT rg_cause  CHECK (cause IN ({_NEW}))" in _doc_section()


def test_downgrade_refuses_while_a_maintenance_pause_row_exists_then_restores_0011s_list() -> None:
    """C-5.2: 0011's CHECK cannot hold a `maintenance_pause` row; deleting one is no rollback."""
    assert _in_order(
        _down(),
        [
            _LOCK,
            "LOCK TABLE recording_gaps IN SHARE MODE;",
            "IF EXISTS (SELECT 1 FROM recording_gaps WHERE cause = 'maintenance_pause') THEN",
            "RAISE EXCEPTION '0067_rg_cause_maintenance_pause downgrade refused:",
            f"ADD CONSTRAINT rg_cause CHECK (cause IN ({_OLD})) NOT VALID;",
            "ALTER TABLE recording_gaps VALIDATE CONSTRAINT rg_cause;",
            _RESET,
        ],
    )
    assert "(C-5.2)" in _down() and "DELETE FROM recording_gaps" not in _down()


def test_the_model_mirrors_the_widened_check() -> None:
    (check,) = [
        c for c in models.recording_gaps.constraints
        if isinstance(c, CheckConstraint) and str(c.name).endswith("rg_cause")
    ]  # fmt: skip
    assert f"CHECK ({_norm(str(check.sqltext))}) NOT VALID" in _up()
