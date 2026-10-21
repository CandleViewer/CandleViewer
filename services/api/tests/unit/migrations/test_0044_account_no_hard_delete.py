"""`0044_account_no_hard_delete` (#2758 item 1): offline render, the one privilege change each way,
the chain and the stamps, what the docstring and the docs record, and the premise the revoke rests
on: the application never hard-deletes an account. The scan below reads raw SQL; Core and the ORM
reach the table only through a name that `tests/unit/storage/test_account_env_write_once_surface.py`
refuses outside its definition and one read-only module.
Real Postgres: `tests/integration/storage/test_account_no_hard_delete_migration.py`."""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import warnings
from functools import cache
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_REPO = _ROOT.parents[1]
_DOC = _REPO / "docs" / "plan" / "21-database-schema.md"
_THREATS = _REPO / "docs" / "security" / "threat-models" / "E27-accounts.md"
_REV, _PREV = "0044_account_no_hard_delete", "0041_account_env_write_once"
_UP, _DOWN = f"{_PREV}:{_REV}", f"{_REV}:{_PREV}"
_FILE = _ROOT / "candleviewer" / "migrations" / "versions" / f"{_REV}.py"
_LOCK, _RESET = "SET LOCAL lock_timeout = '5s'", "SET LOCAL lock_timeout = DEFAULT"
#: 0024/0032's role guard, cut at its inner `;` like every statement list here.
_GUARD = (
    "DO $BODY$ BEGIN IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'cv_app') THEN EXECUTE '{}'"
)
#: Alembic's version stamp, each way.
_STAMP = "UPDATE alembic_version SET version_num='{}' WHERE alembic_version.version_num = '{}'"


def _alembic(*args: str) -> str:
    r = subprocess.run(  # noqa: S603 -- fixed argv, literal alembic subcommands, no shell (#2758)
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT, env={**os.environ}, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr
    return r.stdout


def _norm(sql: str) -> str:
    """Drop `--` comments and collapse whitespace, so layout never matters."""
    return " ".join(re.sub(r"--[^\n]*", "", sql).split())


def _statements(sql: str) -> list[str]:
    """`sql` cut at every `;`, blanks dropped (alembic ends each `op.execute` with one more `;`)."""
    return [part.strip() for part in sql.split(";") if part.strip()]


@cache
def _up() -> str:
    return _norm(_alembic("upgrade", _UP, "--sql"))


@cache
def _down() -> str:
    return _norm(_alembic("downgrade", _DOWN, "--sql"))


def test_revision_chains_onto_0041() -> None:
    assert f"{_PREV} -> {_REV}" in _alembic("history", "-r", _UP)


def test_revision_id_fits_alembics_version_column() -> None:
    """`alembic_version.version_num` is VARCHAR(32): a longer id fails the stamp (SQLSTATE 22001)
    after the REVOKE has run and takes the whole migration with it. The id first proposed for
    this revision, `0044_exchange_accounts_no_hard_delete`, has 37 characters."""
    assert len(_REV) <= 32


def test_upgrade_is_one_guarded_revoke_under_a_bounded_lock_wait() -> None:
    assert _statements(_up()) == [
        "BEGIN",
        _LOCK,
        _GUARD.format("REVOKE DELETE ON exchange_accounts FROM cv_app"),
        "END IF",
        "END $BODY$",
        _RESET,
        _STAMP.format(_REV, _PREV),
        "COMMIT",
    ]


def test_downgrade_is_one_guarded_grant_under_a_bounded_lock_wait() -> None:
    assert _statements(_down()) == [
        "BEGIN",
        _LOCK,
        _GUARD.format("GRANT DELETE ON exchange_accounts TO cv_app"),
        "END IF",
        "END $BODY$",
        _RESET,
        _STAMP.format(_PREV, _REV),
        "COMMIT",
    ]


def test_the_only_privilege_change_is_delete_on_the_accounts_table_for_cv_app() -> None:
    """A narrowing (0024/0032) and its mirror: one REVOKE up, one GRANT down, of DELETE alone, so
    a round trip restores the ACL. No TRUNCATE (cv_app never held it: the integration tests pin
    what it holds), no `cv_ro` (SELECT only), no other table."""
    up, down = _up(), _down()
    assert [sql.count(verb) for sql in (up, down) for verb in ("REVOKE ", "GRANT ")] == [1, 0, 0, 1]
    for sql in (up, down):
        assert set(re.findall(r"\bON (\w+)", sql)) == {"exchange_accounts"}
        assert sql.count("pg_roles") == 1 and sql.count("DELETE") == 1
        for absent in ("TRUNCATE", "cv_ro", "PUBLIC", "ALL "):
            assert absent not in sql


def test_the_docstring_records_the_truncate_finding_the_premise_and_the_residual() -> None:
    docstring = ast.get_docstring(ast.parse(_FILE.read_text(encoding="utf-8")))
    assert docstring is not None
    text = " ".join(docstring.split())
    for fact in (
        "#2758",
        "TRUNCATE needs no REVOKE",
        "the store soft-deletes",
        "No foreign key cascades into the table",
        "the owner (`cv_owner`, migrations only) and superusers can still delete accounts",
    ):
        assert fact in text, fact


def test_the_plan_doc_registers_the_revision_and_states_the_revoke() -> None:
    doc = _DOC.read_text(encoding="utf-8")
    assert f"| `{_REV}` " in doc.split("### 9.4 ", 1)[1]
    accounts = doc.split("#### 3.2.1 ", 1)[1].split("#### 3.2.2 ", 1)[0]
    assert f"revision `{_REV}`" in accounts and "revokes DELETE on `exchange_accounts`" in accounts
    keys = doc.split("#### 3.2.3a ", 1)[1].split("#### 3.2.4 ", 1)[0]
    assert "none on the parent `exchange_accounts` either" in " ".join(keys.split())
    assert "no revision revokes it" not in doc


def test_the_threat_model_closes_the_account_delete_residual() -> None:
    text = _THREATS.read_text(encoding="utf-8")
    rows = {line.split("|")[1].strip(): line for line in text.splitlines() if line[:6] == "| KV-T"}
    assert all("#2758" in rows[risk] for risk in ("KV-T02", "KV-T04"))
    assert "Consider `REVOKE DELETE ON exchange_accounts" not in text
    assert "parent-cascade DELETE then re-insert" not in text


# -- The premise: no statement of the application deletes from or truncates the table
#: A DELETE FROM or a TRUNCATE naming the accounts table (not `exchange_accounts_archive`).
_HARD_DELETE = re.compile(
    r"\b(?:delete\s+from|truncate(?:\s+table)?)\s+(?:only\s+)?"
    r"(?:public\s*\.\s*)?\"?exchange_accounts\b",
    re.IGNORECASE,
)
_APP = (_ROOT / "candleviewer", _ROOT / "cvdev")


def _hard_deletes(root: Path) -> tuple[set[Path], list[str]]:
    """`(modules that name the table, path:line of each string constant that deletes from or
    truncates it)` under `root`, `migrations/versions` aside (DDL run by the owner) and docstrings
    skipped. Raw SQL only: Core and ORM reach the Table through a name the surface scan refuses,
    and SQL assembled from parts is refused by the `cv-raw-sql-string-interpolation` rule. It stops
    an honest regression, not a deliberate bypass: the revoke is the enforcement."""
    named: set[Path] = set()
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        rel, source = path.relative_to(root), path.read_text(encoding="utf-8")
        if rel.parts[:2] == ("migrations", "versions") or "exchange_accounts" not in source.lower():
            continue
        named.add(rel)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)  # a `\:` in some SQL text
            tree = ast.parse(source)
        prose = {n.value for n in ast.walk(tree) if isinstance(n, ast.Expr)}
        found += [
            f"{rel.as_posix()}:{n.lineno}"
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n not in prose
            if _HARD_DELETE.search(n.value)
        ]
    return named, found


def test_nothing_under_the_application_deletes_from_or_truncates_the_accounts_table() -> None:
    scans = [_hard_deletes(root) for root in _APP]
    named = {rel for rels, _ in scans for rel in rels}
    assert Path("storage/repositories/accounts_sqlalchemy.py") in named  # the scan sees the store
    assert [hit for _, hits in scans for hit in hits] == []


#: `(path, source, hits)`: a DELETE or TRUNCATE of the table in raw SQL is reported; another table,
#: a delete that only joins it, prose, and the migrations (run as the owner) are not.
_CASES = {
    "delete": ("repo.py", 'S = "DELETE FROM exchange_accounts WHERE id = :id"', 1),
    "schema-qualified": ("repo.py", 'S = "delete from public.exchange_accounts"', 1),
    "split literal": ("repo.py", 'S = ("DELETE FROM "\n     "exchange_accounts")', 1),
    "truncate": ("repo.py", 'S = "TRUNCATE TABLE ONLY exchange_accounts CASCADE"', 1),
    "other table": ("repo.py", 'S = "DELETE FROM exchange_accounts_archive"', 0),
    "join": (
        "repo.py",
        'S = "DELETE FROM api_keys k USING exchange_accounts ea WHERE ea.id = 1"',
        0,
    ),
    "docstring": ("repo.py", '"""DELETE FROM exchange_accounts (prose, not SQL)."""', 0),
    "migration": ("migrations/versions/x.py", 'op.execute("DELETE FROM exchange_accounts")', 0),
}


@pytest.mark.parametrize(("rel", "source", "hits"), list(_CASES.values()), ids=list(_CASES))
def test_the_scan_reports_a_delete_or_truncate_of_the_accounts_table_and_nothing_else(
    tmp_path: Path, rel: str, source: str, hits: int
) -> None:
    (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(source + "\n", encoding="utf-8")
    assert len(_hard_deletes(tmp_path)[1]) == hits
