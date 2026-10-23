"""#3085 S13a (the #4139 re-check's Info 6): one statement addresses a system event to a user.

Row 34b of the security program makes one exception to the Owner's `system` stream: the view-as
start's notice, addressed to its target. `GET /notifications` gates the exception on
`recipient_user_id` alone, so any other writer of the column would widen it. This guard keeps the
start's insert (`sessions_sqlalchemy._VIEW_AS_NOTICE_SQL`) the only production statement that
writes it:
- an `INSERT`, `UPDATE`, `MERGE` or `COPY` of `system_events` (schema-qualified or not; a string,
  an f-string's text or a `+` of strings) naming the column, or naming no columns at all;
- a keyword, dict key or assignment target `recipient_user_id`, or any `x.recipient_user_id`
  (an ORM or Core column) used as a dict key or assigned to.
A tripwire, not a boundary: the control is C-10.2 review of these files.
"""

from __future__ import annotations

import ast
import re
import unicodedata
from collections.abc import Iterator
from pathlib import Path

import candleviewer

_ROOT = Path(candleviewer.__file__).parent
_TABLE = r'(?:"?\w+"?\s*\.\s*)?"?SYSTEM_EVENTS\b"?+'
_WRITE = re.compile(rf"\b(?:INSERT\s+INTO|UPDATE|MERGE\s+INTO|COPY)\s+{_TABLE}")
_POSITIONAL = re.compile(rf"\b(?:INSERT\s+INTO|COPY)\s+{_TABLE}\s*+(?!\()|\bINSERT\s+VALUES\b")
_ONE_WRITER = ("storage/repositories/sessions_sqlalchemy.py",)


def _text(node: ast.AST) -> str | None:
    """A string, or the literal text of an f-string (each hole a name) or of a `+` of strings."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        return "".join(_text(part) or " x " for part in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _text(node.left), _text(node.right)
        return None if left is None or right is None else left + right
    return None


def _names_column(node: ast.AST | None) -> bool:
    """`"recipient_user_id"`, any `x.recipient_user_id`, or a subscript by either."""
    if isinstance(node, ast.Constant):
        return node.value == "recipient_user_id"
    if isinstance(node, ast.Attribute):
        return node.attr == "recipient_user_id"
    return isinstance(node, ast.Subscript) and _names_column(node.slice)


def _writes(source: str) -> list[int]:
    """The lines of `source` that write `recipient_user_id` (module docstring)."""
    lines: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if (sql := _text(node)) is not None:
            sql = sql.upper()
            if _WRITE.search(sql) and ("RECIPIENT_USER_ID" in sql or _POSITIONAL.search(sql)):
                lines.add(node.lineno)
        elif isinstance(node, ast.keyword) and node.arg == "recipient_user_id":
            lines.add(node.value.lineno)
        elif isinstance(node, ast.Dict):
            lines |= {key.lineno for key in node.keys if key is not None and _names_column(key)}
        elif isinstance(node, (ast.Attribute, ast.Subscript)) and isinstance(node.ctx, ast.Store):
            if _names_column(node):
                lines.add(node.lineno)
    return sorted(lines)


def _sources() -> Iterator[tuple[str, str]]:
    """Each production module naming the table or the column, read NFKC-normalised as Python reads
    its identifiers: no other can write the column, so no other is parsed. A name split across
    string literals is out of the guard's reach, as any obfuscated name is (C-10.2 review)."""
    for path in sorted(_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        named = unicodedata.normalize("NFKC", text).lower()
        if "migrations" in path.parts or not (
            "system_events" in named or "recipient_user_id" in named
        ):
            continue
        yield path.relative_to(_ROOT).as_posix(), text


def test_only_the_view_as_start_writes_a_recipient() -> None:
    writers = {path: lines for path, text in _sources() if (lines := _writes(text))}
    assert list(writers) == list(_ONE_WRITER)
    assert len(writers[_ONE_WRITER[0]]) == 1  # `_VIEW_AS_NOTICE_SQL`


def test_the_guard_finds_a_statement_a_keyword_and_a_dict_key() -> None:
    planted = (
        'SQL = "UPDATE system_events SET recipient_user_id = NULL"\n'
        "stmt = table.insert().values(recipient_user_id=uid)\n"
        'params = {"recipient_user_id": uid}\n'
    )
    assert _writes(planted) == [1, 2, 3]


def test_the_guard_finds_the_shapes_a_review_named() -> None:
    """The #4170 security look's evasions: a schema-qualified table, a positional insert, a
    `MERGE`, an f-string and a `+`, a subscript or attribute assigned, a column object as a key."""
    planted = (
        'Q = "insert into public.system_events (recipient_user_id) values (:u)"\n'
        'P = "INSERT INTO system_events VALUES (:a, :b)"\n'
        'M = "MERGE INTO system_events USING x ON false WHEN NOT MATCHED THEN INSERT VALUES (1)"\n'
        'F = f"INSERT INTO {schema}.system_events (recipient_user_id) VALUES ({u})"\n'
        'C = "INSERT INTO system_events (kind, " + "recipient_user_id) VALUES (:k, :u)"\n'
        'params["recipient_user_id"] = uid\n'
        "row.recipient_user_id = uid\n"
        "stmt = insert(t).values({t.c.recipient_user_id: uid})\n"
        'K = "COPY system_events FROM STDIN"\n'
    )
    assert _writes(planted) == list(range(1, 10))


def test_the_guard_passes_a_read_and_an_insert_that_leaves_the_column_out() -> None:
    planted = (
        'R = "SELECT id FROM system_events WHERE recipient_user_id = :user"\n'
        'W = "INSERT INTO system_events (component, kind) VALUES (:c, :k)"\n'
        "query = select(t).where(t.c.recipient_user_id == uid)\n"
        "recipient_user_id: Mapped[str] = mapped_column()\n"
    )
    assert _writes(planted) == []
