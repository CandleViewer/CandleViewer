"""`0045_audit_search_path` (#4032): offline render, the four pins each way, the chain, and
CI-MIG-003's exemption, which holds for this file only while it holds nothing but its pins.
Real Postgres: `tests/integration/audit/test_audit_search_path_migration.py`."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_LINT = _ROOT.parents[1] / "tools" / "ci" / "migration_lint.py"
_REV, _PREV = "0045_audit_search_path", "0044_account_no_hard_delete"
_FILE = _ROOT / "candleviewer" / "migrations" / "versions" / f"{_REV}.py"
_GUARDS = ("forbid_mutation()", "audit_refuse_truncate()", "audit_chain()", "audit_field(text)")
_PIN = "pg_catalog, public, pg_temp"
#: Alembic's version stamp, each way.
_STAMP = "UPDATE alembic_version SET version_num='{}' WHERE alembic_version.version_num = '{}'"


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#4032)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _statements(sql: str) -> list[str]:
    """`sql` without `--` comments, cut at every `;`, each statement's whitespace collapsed."""
    text = re.sub(r"--[^\n]*", "", sql)
    return [" ".join(part.split()) for part in text.split(";") if part.strip()]


@cache
def _up() -> list[str]:
    return _statements(_alembic("upgrade", f"{_PREV}:{_REV}", "--sql"))


@cache
def _down() -> list[str]:
    return _statements(_alembic("downgrade", f"{_REV}:{_PREV}", "--sql"))


def _lint(versions: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, the repo's own lint script, no shell (#4032)
        [sys.executable, str(_LINT), "--versions-dir", str(versions)],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip


def test_revision_chains_onto_0044() -> None:
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")


def test_upgrade_pins_each_guard_function_and_nothing_else() -> None:
    pins = [f"ALTER FUNCTION {guard} SET search_path = {_PIN}" for guard in _GUARDS]
    assert _up() == ["BEGIN", *pins, _STAMP.format(_REV, _PREV), "COMMIT"]


def test_downgrade_resets_each_guard_function_and_nothing_else() -> None:
    resets = [f"ALTER FUNCTION {guard} RESET search_path" for guard in _GUARDS]
    assert _down() == ["BEGIN", *resets, _STAMP.format(_PREV, _REV), "COMMIT"]


def test_ci_mig_003_exempts_the_revision_as_shipped(tmp_path: Path) -> None:
    (tmp_path / _FILE.name).write_bytes(_FILE.read_bytes())
    r = _lint(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "CI-MIG-003" not in r.stdout + r.stderr


def test_ci_mig_003_refuses_it_with_one_more_statement(tmp_path: Path) -> None:
    """The exemption is the file's shape, not its name: one more statement and every pin is
    read as any revision's again."""
    source = _FILE.read_text(encoding="utf-8")
    one_more = 'search_path = pg_catalog, public, pg_temp"\n    )'
    assert source.count(one_more) == 1
    widened = source.replace(
        one_more, 'search_path = pg_catalog, public, pg_temp"\n    )\n    op.execute("SELECT 1")'
    )
    (tmp_path / _FILE.name).write_text(widened, encoding="utf-8")
    r = _lint(tmp_path)
    assert r.returncode == 1
    assert "the search_path pin revision may hold only" in r.stdout + r.stderr
    assert (
        r.stdout.count("append-only guard function") + r.stderr.count("append-only guard function")
        == 8
    )
