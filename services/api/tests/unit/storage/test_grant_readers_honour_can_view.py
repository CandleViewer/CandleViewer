"""UL-F2 (E42-X03; `e42-user-lifecycle.md` §5, UL2-T2): every read of `user_account_access`
honours `can_view`, so a soft-revoked grant (#965 O4) never grants scope or counts as a binding.

An enumerating test, not a Semgrep rule: Python's AST joins a statement's adjacent literals into
one string, which Semgrep's string matching may not. Each SQL text under `candleviewer/` that reads
the table (`FROM` or `JOIN user_account_access`) names `can_view`, to filter on it or return it,
and the table's SQLAlchemy object is used nowhere but `db/models.py`. A read that ignores
`can_view` on purpose is listed in `_IGNORES_CAN_VIEW` by module and constant, with its reason
and the text it must keep, so a rewrite of that constant loses the exception. The table's bare
name as a string is used nowhere but `db/models.py` either (a `sa.table(...)` stand-in, say).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import candleviewer

_PACKAGE = Path(candleviewer.__file__).resolve().parent
_READ = re.compile(r'\b(?:FROM|JOIN)\s+(?:\w+\.)?"?user_account_access\b', re.IGNORECASE)
_CAN_VIEW = re.compile(r"\bcan_view\b")
_TABLE = "user_account_access"
_SCHEMA_MODULE = "db/models.py"
#: (module, constant) -> why the read ignores `can_view` on purpose, and the start of the text
#: that read must keep: here an UPDATE that sets the freeze columns and nothing else, so a rewrite
#: into a read that returns or grants anything loses the exception.
_IGNORES_CAN_VIEW: dict[tuple[str, str], tuple[str, re.Pattern[str]]] = {
    ("storage/repositories/account_access_sqlalchemy.py", "_INHERIT"): (
        "#2648 Q1: a frozen manager's new or revived grant copies the freeze of their latest "
        "frozen row, live or soft-revoked, so revoking every grant and granting again cannot "
        "escape the freeze; it only ever sets `frozen`, never a grant",
        re.compile(
            r"UPDATE user_account_access AS g SET frozen = true, frozen_at = d\.frozen_at, "
            r"frozen_by = d\.frozen_by, frozen_reason = d\.frozen_reason FROM "
        ),
    ),
}


@dataclass(frozen=True)
class _Read:
    module: str
    line: int
    constant: str | None  # the module-level name the text is assigned to, if any
    text: str


def _modules() -> list[tuple[str, str]]:
    """Each module's path under `candleviewer/` and its source; migrations and generated code are
    the schema's own and the contract's."""
    return [
        (path.relative_to(_PACKAGE).as_posix(), path.read_text(encoding="utf-8"))
        for path in sorted(_PACKAGE.rglob("*.py"))
        if not {"migrations", "_generated"} & set(path.relative_to(_PACKAGE).parts)
    ]


def _reads(module: str, source: str) -> list[_Read]:
    """Every string in `source` that reads the table, an f-string with `{}` for each value."""
    tree = ast.parse(source)
    names: dict[int, str] = {}
    for statement in tree.body:
        if not isinstance(statement, ast.Assign | ast.AnnAssign):
            continue
        targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
        name = next((t.id for t in targets if isinstance(t, ast.Name)), None)
        if name is not None:
            names.update((id(node), name) for node in ast.walk(statement))
    inside_fstrings = {
        id(part)
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        for part in node.values
    }
    found: list[_Read] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = "".join(
                str(part.value) if isinstance(part, ast.Constant) else "{}" for part in node.values
            )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in inside_fstrings:
                continue
            text = node.value
        else:
            continue
        if _READ.search(text):
            found.append(_Read(module, node.lineno, names.get(id(node)), text))
    return sorted(found, key=lambda read: read.line)


def _all_reads() -> list[_Read]:
    return [read for module, source in _modules() for read in _reads(module, source)]


def _excused(read: _Read) -> bool:
    """A listed exception whose text still starts as its entry requires."""
    entry = _IGNORES_CAN_VIEW.get((read.module, read.constant or ""))
    return entry is not None and entry[1].match(read.text) is not None


def test_every_read_of_user_account_access_names_can_view() -> None:
    reads = _all_reads()
    blind = [
        f"{read.module}:{read.line} ({read.constant or 'inline'})"
        for read in reads
        if not _CAN_VIEW.search(read.text) and not _excused(read)
    ]
    assert len(reads) > len(_IGNORES_CAN_VIEW)  # the readers are found at all
    assert blind == [], f"reads of user_account_access that ignore can_view (UL-F2): {blind}"


def test_each_listed_exception_is_still_a_read_that_ignores_can_view() -> None:
    ignoring = {
        (read.module, read.constant)
        for read in _all_reads()
        if read.constant is not None and not _CAN_VIEW.search(read.text)
    }
    assert set(_IGNORES_CAN_VIEW) <= ignoring
    assert all(reason.strip() for reason, _ in _IGNORES_CAN_VIEW.values())


def test_an_exception_rewritten_beyond_its_freeze_columns_loses_its_excuse() -> None:
    (module, constant), (_, kept) = next(iter(_IGNORES_CAN_VIEW.items()))
    (current,) = [
        read for read in _all_reads() if (read.module, read.constant) == (module, constant)
    ]
    assert _excused(current)
    widened = current.text.replace("SET frozen = true,", "SET frozen = true, can_trade = true,")
    assert not _excused(_Read(module, current.line, constant, widened))
    assert not kept.match("SELECT exchange_account_id FROM user_account_access AS d")


def test_the_table_name_is_a_string_only_in_the_schema_module() -> None:
    bare = [
        f"{module}:{node.lineno}"
        for module, source in _modules()
        if module != _SCHEMA_MODULE
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and node.value == _TABLE
    ]
    assert bare == []


def test_the_table_object_is_used_only_by_the_schema_module() -> None:
    uses = [
        f"{module}:{node.lineno}"
        for module, source in _modules()
        if module != _SCHEMA_MODULE
        for node in ast.walk(ast.parse(source))
        if (isinstance(node, ast.Name) and node.id == _TABLE)
        or (isinstance(node, ast.Attribute) and node.attr == _TABLE)
        or (isinstance(node, ast.alias) and _TABLE in (node.name, node.asname))
    ]
    assert uses == []


def test_the_scan_sees_joined_literals_fstrings_and_aliases() -> None:
    source = (
        '_A = sa.text(\n    "SELECT exchange_account_id FROM user_account_access "\n'
        '    "WHERE user_id = :id"\n)\n'
        'def f(t):\n    return f"SELECT 1 FROM public.user_account_access AS g WHERE {t}"\n'
        '_B = "select x from user_account_access where can_view"\n'
        '_C = "UPDATE user_account_access SET can_view = false"\n'
    )
    reads = _reads("x.py", source)
    assert [(read.line, read.constant) for read in reads] == [(2, "_A"), (6, None), (7, "_B")]
    assert [bool(_CAN_VIEW.search(read.text)) for read in reads] == [False, False, True]
