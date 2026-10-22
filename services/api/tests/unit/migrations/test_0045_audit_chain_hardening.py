"""`0045_audit_chain_hardening` (#889 S3, SR-E42-10; #4032): the chain; the offline render, one
function replacement each way and nothing else; both texts held to `0003_audit_log`'s
`audit_chain()` (the downgrade's byte for byte, the upgrade's with only a search_path of its own
and the id drawn right after the lock); CI-MIG-003's exemption, which holds for this file only in
its shipped shape; and what the docs record. Real Postgres, CI only:
`tests/integration/audit/test_audit_repository.py` (`test_two_connection_inserts_link_in_id_order`,
`test_the_trigger_replaces_an_id_the_caller_supplies` and the seeded round trip) and
`tests/integration/audit/test_audit_chain_hardening_migration.py` (the inserting session's
search_path cannot reach what the chain calls, and a temporary `audit_log` cannot stand in for the
chain head)."""

from __future__ import annotations

import ast
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

_ROOT = Path(__file__).resolve().parents[3]
_REPO = _ROOT.parents[1]
_LINT = _REPO / "tools" / "ci" / "migration_lint.py"
_VERSIONS = _ROOT / "candleviewer" / "migrations" / "versions"
_INTEGRATION = _ROOT / "tests" / "integration" / "audit" / "test_audit_repository.py"
_REV, _PREV = "0045_audit_chain_hardening", "0044_account_no_hard_delete"
_FILE = _VERSIONS / f"{_REV}.py"
_AS = " AS $BODY$\n"
_PIN = "\n  SET search_path = pg_catalog, public, pg_temp"
_LOCK = "  PERFORM pg_advisory_xact_lock(hashtext('audit_log'));\n"
_DRAW = "  NEW.id := nextval('audit_log_id_seq');\n"
_STAMP = "UPDATE alembic_version SET version_num='{}' WHERE alembic_version.version_num = '{}';"
_PROOF = "test_two_connection_inserts_link_in_id_order"
_FLAGGED = "line {}: raw-SQL statement targets the append-only guard function 'audit_chain'"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"_{name}_under_test", _VERSIONS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _execute(source: str, function: str) -> ast.Call:
    """`function`'s one statement after an optional docstring: `op.execute` of a string literal,
    the shape CI-MIG-003 exempts."""
    [node] = [n for n in ast.parse(source).body if getattr(n, "name", None) == function]
    assert isinstance(node, ast.FunctionDef)
    [statement] = node.body[1:] if ast.get_docstring(node) is not None else node.body
    assert isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call)
    call = statement.value
    assert ast.unparse(call.func) == "op.execute" and not call.keywords
    [literal] = call.args
    assert isinstance(literal, ast.Constant) and isinstance(literal.value, str)
    return call


def _sql(function: str) -> str:
    """The SQL text `function` runs, stripped: what CI-MIG-003 pins by its sha256."""
    [literal] = _execute(_FILE.read_text(encoding="utf-8"), function).args
    assert isinstance(literal, ast.Constant) and isinstance(literal.value, str)
    return literal.value.strip()


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#889)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _lint(versions: Path) -> str:
    """CI-MIG-003 and the other static checks over `versions`; their output, failing or not."""
    r = subprocess.run(  # noqa: S603 -- fixed argv, the repo's own lint script, no shell (#4032)
        [sys.executable, str(_LINT), "--versions-dir", str(versions)],
        capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    return f"exit {r.returncode}\n{r.stdout}{r.stderr}"


def test_revision_chains_onto_0044() -> None:
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", f"{_PREV}:{_REV}")


def test_the_downgrade_restores_0003s_audit_chain_byte_for_byte() -> None:
    """0003 is immutable (C-5.4), so 0045 carries a copy of its `audit_chain()`: anything but the
    exact text would leave another function behind than the one 0044 ran. A replacement keeps no
    setting it does not name, so this one also drops the upgrade's search_path."""
    sql = _load("0003_audit_log")._UPGRADE_SQL
    [created] = re.findall(r"CREATE FUNCTION audit_chain\(\).*?\$BODY\$;", sql, re.DOTALL)
    assert _sql("downgrade") == "CREATE OR REPLACE " + created.removeprefix("CREATE ")


def test_the_upgrade_is_0003s_plus_only_the_search_path_and_the_id_draw() -> None:
    """The path is set on the definition, `pg_catalog` first and `pg_temp` last; the id is drawn
    under the lock and before the head read and the hash. Every other byte is 0003's, so the hashed
    fields and their encoding are unchanged (the id is not hashed)."""
    restored = _sql("downgrade")
    assert restored.count(_AS) == restored.count(_LOCK) == 1
    assert "search_path" not in restored and _DRAW not in restored
    assert _sql("upgrade") == restored.replace(_AS, _PIN + _AS).replace(_LOCK, _LOCK + _DRAW)


def test_each_direction_replaces_the_function_and_nothing_else() -> None:
    """One `CREATE OR REPLACE FUNCTION` and the version stamp each way: no table, column, grant or
    other function changes (C-5.6, C-5.7), so neither direction touches a row."""
    for direction, span, stamp in (
        ("upgrade", f"{_PREV}:{_REV}", _STAMP.format(_REV, _PREV)),
        ("downgrade", f"{_REV}:{_PREV}", _STAMP.format(_PREV, _REV)),
    ):
        sql = _alembic(direction, span, "--sql")
        assert sql.count(stamp) == 1
        body = sql.split("BEGIN;", 1)[1].split(stamp, 1)[0]
        text = _sql(direction)
        assert body.count(text) == 1
        assert re.sub(r"--[^\n]*", "", body.replace(text, "")).strip(" ;\n") == ""


def test_ci_mig_003_exempts_the_revision_as_shipped(tmp_path: Path) -> None:
    (tmp_path / _FILE.name).write_bytes(_FILE.read_bytes())
    report = _lint(tmp_path)
    assert report.startswith("exit 0\n") and "CI-MIG-003" not in report, report


def test_ci_mig_003_refuses_it_with_one_more_statement(tmp_path: Path) -> None:
    """The exemption is the file's shape, not its name: one more statement and both replacements
    are read as any revision's again."""
    source = _FILE.read_text(encoding="utf-8")
    upgrade, downgrade = (_execute(source, function) for function in ("upgrade", "downgrade"))
    end = upgrade.end_lineno
    assert end is not None  # the line that closes the upgrade's one statement
    lines = source.splitlines(keepends=True)
    widened = [*lines[:end], '    op.execute("SELECT 1")\n', *lines[end:]]
    (tmp_path / _FILE.name).write_text("".join(widened), encoding="utf-8")
    report = _lint(tmp_path)
    assert report.startswith("exit 1\n"), report
    for line in (upgrade.args[0].lineno, downgrade.args[0].lineno + 1):  # one line added above it
        assert _FLAGGED.format(line) in report


def test_the_docs_record_the_revision_and_the_test_that_proves_it() -> None:
    schema = (_REPO / "docs" / "plan" / "21-database-schema.md").read_text(encoding="utf-8")
    assert f"| `{_REV}` " in schema.split("### 9.4 ", 1)[1]
    audit = schema.split("#### 3.10.1 ", 1)[1].split("#### 3.10.2 ", 1)[0]
    for record in (f"`{_REV}`", _PIN.strip(), _DRAW.strip(), "CACHE 1"):
        assert record in audit
    model = _REPO / "docs" / "security" / "threat-models" / "e42-admin.md"
    rows = [r for r in model.read_text(encoding="utf-8").splitlines() if r[:13] == "| SR-E42-10 |"]
    assert len(rows) == 1 and _REV in rows[0] and _PROOF in rows[0]
    assert not rows[0].endswith("| open |")
    assert re.search(rf"^async def {_PROOF}\(", _INTEGRATION.read_text(encoding="utf-8"), re.M)
