"""#3085 S13a (the #4139 re-check's Info 6): one statement addresses a system event to a user.

Row 34b of the security program makes one exception to the Owner's `system` stream: the view-as
start's notice, addressed to its target. `GET /notifications` gates the exception on
`recipient_user_id` alone, so any other writer of the column would widen it. This guard keeps the
start's insert (`sessions_sqlalchemy._VIEW_AS_NOTICE_SQL`) the only production statement that
writes it: an `INSERT` or `UPDATE` of `system_events` naming the column, or a keyword or dict key
`recipient_user_id` passed anywhere.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import candleviewer

_ROOT = Path(candleviewer.__file__).parent
_WRITE = re.compile(r"\b(INSERT\s+INTO|UPDATE)\s+SYSTEM_EVENTS\b")
_ONE_WRITER = ("storage/repositories/sessions_sqlalchemy.py",)


def _writes(source: str) -> list[int]:
    """The lines of `source` that write `recipient_user_id` (module docstring)."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            sql = node.value.upper()
            if _WRITE.search(sql) and "RECIPIENT_USER_ID" in sql:
                lines.append(node.lineno)
        elif isinstance(node, ast.keyword) and node.arg == "recipient_user_id":
            lines.append(node.value.lineno)
        elif isinstance(node, ast.Dict):
            keys = [k for k in node.keys if isinstance(k, ast.Constant)]
            lines += [k.lineno for k in keys if k.value == "recipient_user_id"]
    return lines


def test_only_the_view_as_start_writes_a_recipient() -> None:
    writers = {
        path.relative_to(_ROOT).as_posix(): lines
        for path in sorted(_ROOT.rglob("*.py"))
        if "migrations" not in path.parts
        if (lines := _writes(path.read_text(encoding="utf-8")))
    }
    assert list(writers) == list(_ONE_WRITER)
    assert len(writers[_ONE_WRITER[0]]) == 1  # `_VIEW_AS_NOTICE_SQL`


def test_the_guard_finds_a_statement_a_keyword_and_a_dict_key() -> None:
    planted = (
        'SQL = "UPDATE system_events SET recipient_user_id = NULL"\n'
        "stmt = table.insert().values(recipient_user_id=uid)\n"
        'params = {"recipient_user_id": uid}\n'
    )
    assert sorted(_writes(planted)) == [1, 2, 3]
