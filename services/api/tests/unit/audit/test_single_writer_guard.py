"""Single-writer guard for `audit_log` (design §5, "Ordering assumption").

`verify` walks the chain in id order. Chain order equals id order only because the one
writer path, `SqlAlchemyAuditRepository.insert`, takes `pg_advisory_xact_lock` *before* its
INSERT, so `nextval` runs under the lock. An INSERT that bypasses it takes the lock only
inside the BEFORE trigger, after `nextval`: two concurrent bypassing INSERTs can chain out
of id order, and `verify` would then report a break that is not one. So no code under
`candleviewer/` (migrations aside) may write to `audit_log` except that repository.

The scan reads the parsed code (`ast`), not raw text: string constants arrive with adjacent
literals merged and escapes decoded, and SQL comments are dropped before matching. It flags
a statement that writes to `audit_log` (`INSERT INTO`, `COPY`, `MERGE INTO`; quoted or
schema-qualified names), an asyncpg bulk copy into it, a Core `insert()` on it, and a table
or ORM object naming it outside the two files that define one for reading.
"""

from __future__ import annotations

import ast
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository

_PACKAGE = Path(__file__).resolve().parents[3] / "candleviewer"
_WRITER = Path("storage/repositories/audit_sqlalchemy.py")
_MODELS = Path("db/models.py")
_NAME = r'(?:"?\w+"?\s*\.\s*)?"?audit_log"?(?![\w"])'
_WRITE = re.compile(rf"\b(?:INSERT\s+INTO|COPY|MERGE\s+INTO)\s+{_NAME}", re.IGNORECASE)
_COMMENT = re.compile(r"/\*.*?\*/|--[^\n]*", re.DOTALL)
_COPIES = frozenset({"copy_records_to_table", "copy_to_table"})


def _name(node: ast.AST) -> str:
    """The last name of `x` or `a.b.x`."""
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else ""


def _audit_log(node: ast.AST | None) -> bool:
    if isinstance(node, ast.Constant):
        return node.value == "audit_log"
    return node is not None and _name(node) == "audit_log"


def _findings(source: str) -> list[str]:
    """Each place in `source` that writes to `audit_log` or names it as a table object."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        text = None
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        elif isinstance(node, ast.JoinedStr):  # an f-string: a stand-in for each field
            text = "".join(v.value if isinstance(v, ast.Constant) else "x" for v in node.values)
        if text is not None and _WRITE.search(_COMMENT.sub(" ", text)):
            found.append("statement")
        if isinstance(node, ast.Call):
            func, first = _name(node.func), node.args[0] if node.args else None
            receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
            if func in _COPIES and _audit_log(first):
                found.append("copy")
            elif func == "insert" and (_audit_log(first) or _audit_log(receiver)):
                found.append("insert")
            elif func in ("Table", "table") and _audit_log(first):
                found.append("table")
        elif isinstance(node, ast.Assign) and _audit_log(node.value):
            if any(_name(target) == "__tablename__" for target in node.targets):
                found.append("table")
    return found


@pytest.mark.parametrize(
    ("snippet", "finding"),
    [
        ('sa.text("INSERT INTO audit_log (record_id) VALUES (:r)")', "statement"),
        ('sa.text(\n    "INSERT INTO "\n    "audit_log (record_id)"\n)', "statement"),
        ('sa.text("INSERT\\tINTO\\naudit_log (record_id)")', "statement"),
        ('sa.text("INSERT /* bulk */ INTO -- note\\n audit_log (x)")', "statement"),
        ('sa.text(\'insert into "public"."audit_log" (x)\')', "statement"),
        ('sa.text(f"INSERT INTO {schema}.audit_log (x)")', "statement"),
        ('sa.text("COPY audit_log FROM STDIN")', "statement"),
        ('sa.text("MERGE INTO audit_log t USING s WHEN NOT MATCHED THEN INSERT")', "statement"),
        ('await conn.copy_records_to_table("audit_log", records=rows)', "copy"),
        ('await conn.copy_to_table("audit_log", source=buf)', "copy"),
        ("stmt = audit_log.insert().values(record_id=r)", "insert"),
        ("stmt = sa.insert(models.audit_log)", "insert"),
        ('stmt = sa.table("audit_log", sa.column("x")).insert()', "table"),
        ('t = Table("audit_log", metadata)', "table"),
        ('class A(Base):\n    __tablename__ = "audit_log"', "table"),
    ],
)
def test_the_guard_finds_every_form(snippet: str, finding: str) -> None:
    assert finding in _findings(snippet)


@pytest.mark.parametrize(
    "snippet",
    [
        'sa.text("INSERT INTO audit_checkpoints (id) VALUES (:i)")',
        'sa.text("INSERT INTO audit_log_archive (id) VALUES (:i)")',
        'sa.text("SELECT entry_hash FROM audit_log WHERE id < :i")',
        "sa.text(\"INSERT INTO other (note) VALUES ('audit_log')\")",
    ],
)
def test_the_guard_ignores_reads_and_other_tables(snippet: str) -> None:
    assert _findings(snippet) == []


def test_only_the_audit_repository_writes_to_audit_log() -> None:
    found = {}
    for path in sorted(_PACKAGE.rglob("*.py")):
        relative = path.relative_to(_PACKAGE)
        if "migrations" not in relative.parts and (hits := _findings(path.read_text("utf-8"))):
            found[relative] = sorted(hits)
    # The repository's one INSERT and its read-only column set; the schema's metadata.
    assert found == {_WRITER: ["statement", "table"], _MODELS: ["table"]}


async def test_the_writer_takes_the_chain_lock_before_its_insert() -> None:
    """The ordering assumption itself: the lock first, so `nextval` runs under it."""
    statements: list[str] = []

    class _Relational:
        @asynccontextmanager
        async def unit_of_work(self) -> AsyncIterator[Any]:
            async def execute(stmt: Any, _params: Any = None) -> None:
                statements.append(" ".join(str(stmt).split()))

            async def commit() -> None:
                statements.append("COMMIT")

            yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)

    repo = SqlAlchemyAuditRepository(_Relational())  # type: ignore[arg-type]  # structural fake
    record = {"record_id": "r", "actor_label": "a", "action": "auth.login", "outcome": "success"}
    await repo.insert({**record, "severity": "info", "event_ts": "2026-10-15T00:00:00+00:00"})
    assert statements[0] == "SELECT pg_advisory_xact_lock(hashtext('audit_log'))"
    assert statements[1].startswith("INSERT INTO audit_log") and statements[2] == "COMMIT"
