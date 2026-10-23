"""#3990: every audit write an HTTP route or a socket makes names the request.

An `emit`, `emit_keyed` or `enforce` call under `candleviewer/api`, `candleviewer/admin` or
`candleviewer/ws` (a socket's rows name its upgrade's request, #3085), and a call of the socket's
bounded writers that wrap one (`_emit_bounded`, `refuse_frame`), passes a `request_id=` that is
not `None` and reads no header (the defect), or a `**mapping` in a file that says `request_id`.
The values are checked at run time (`tests/security/admin/`,
`tests/security/auth/test_audit_request_id_on_auth_paths.py`, and for the socket's rows
`tests/unit/ws/test_ws_audit_trail.py`). A row held as data, as `ws/permissions.py`'s `_AuditRow`
rows are (`ws.permission_snapshot.refused` and the revocation rows, written once every socket of a
change has its frames), carries its `request_id` in a dict this scan does not read: only the run
time checks those. The scan reads calls by name only:
one through an alias (`audit = writer.emit`), `functools.partial` or `getattr` is invisible to it,
and review is what catches those. A file whose calls cannot name the request is in `EXEMPT` with
its reason and how many such calls it holds: an exemption cannot grow, and a spent one must go.
"""

from __future__ import annotations

import ast
import functools
from collections import Counter
from pathlib import Path

import pytest

import candleviewer

_ROOT = Path(candleviewer.__file__).resolve().parent
_AUDIT_CALLS = frozenset({"emit", "emit_keyed", "enforce", "_emit_bounded", "refuse_frame"})
_FORWARDS = "forwards the caller's fields, which carry the id; a system write (a flush) has none"

#: File (relative to the package) -> (how many of its audit calls cannot name the request, why).
EXEMPT = {
    "api/audit_budget.py": (2, _FORWARDS),
    "api/audit_verify.py": (1, _FORWARDS),
    "api/refusal_session.py": (1, _FORWARDS),  # #4174: `NamesSession` adds the session only
    "admin/breakglass_wiring.py": (1, "the host CLI's break-glass journal: no HTTP request"),
    "admin/flags/maintenance.py": (1, "`system:maintenance`, the poller's own transition"),
}


def _says_request_id(tree: ast.AST) -> bool:
    """The module's code names `request_id`; a comment or a docstring that says it does not."""
    return any(
        (isinstance(node, (ast.keyword, ast.arg)) and node.arg == "request_id")
        or (isinstance(node, ast.Constant) and node.value == "request_id")
        or (isinstance(node, ast.Attribute) and node.attr == "request_id")
        or (isinstance(node, ast.Name) and node.id == "request_id")
        for node in ast.walk(tree)
    )


def _names_it(call: ast.Call, says_it: bool) -> bool:
    for kw in call.keywords:
        if kw.arg is None:  # `**mapping`: it can carry the id only where the code names it
            if says_it:
                return True
        elif kw.arg == "request_id":
            value = ast.unparse(kw.value)
            if value != "None" and "headers" not in value:  # neither dropped nor a header read
                return True
    return False


def _scan(source: str) -> list[tuple[int, bool]]:
    """`(line, names the request)` of every audit call in `source`."""
    found: list[tuple[int, bool]] = []
    tree = ast.parse(source)
    says_it = _says_request_id(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
            if name in _AUDIT_CALLS:
                found.append((node.lineno, _names_it(node, says_it)))
    return found


@functools.cache
def _calls() -> tuple[tuple[str, int, bool], ...]:
    """`(file, line, names the request)` of every audit call under the three areas."""
    return tuple(
        (path.relative_to(_ROOT).as_posix(), line, carries)
        for area in ("api", "admin", "ws")
        for path in sorted((_ROOT / area).rglob("*.py"))
        if "_generated" not in path.parts
        for line, carries in _scan(path.read_text(encoding="utf-8"))
    )


def test_the_scan_sees_the_audit_calls_of_each_area() -> None:
    files = {file for file, _, _ in _calls()}
    assert len(_calls()) > 80
    assert {"api/users.py", "api/invites.py", "api/auth.py", "admin/http.py"} <= files
    assert {"ws/gateway.py", "ws/permissions.py", "ws/origin_audit.py"} <= files


def test_the_calls_that_do_not_name_the_request_are_exactly_those_exempt_files_pin() -> None:
    bare = [(file, line) for file, line, carries in _calls() if not carries]
    held = dict(Counter(file for file, _ in bare))
    pinned = {file: count for file, (count, _) in EXEMPT.items()}
    assert held == pinned, (
        f"bare {bare}, pinned {pinned}: a new bare call passes `request_id=current_request_uuid()`;"
        " a pin its file no longer needs is lowered or dropped"
    )


@pytest.mark.parametrize(
    ("source", "bare"),
    [
        ("emit('a', request_id=current_request_uuid())", False),
        ("enforce(p, perm, request_id=principal.request_id)", False),
        ("who = {'request_id': rid}\nemit('a', **who)", False),
        ("emit('a')", True),
        ("emit('a', request_id=None)", True),
        ("emit('a', request_id=request.headers.get('x-request-id'))", True),
        ("emit('a', **who)", True),  # a mapping in a file that never says `request_id`
        ("# request_id\nemit('a', **who)", True),  # a comment is not code
        ('"""Carries request_id."""\nemit(\'a\', **who)', True),  # nor is a docstring
        ("audit = writer.emit\naudit('a')", False),  # not seen at all, as the docstring says
    ],
)
def test_the_predicate_rejects_each_way_of_dropping_the_id(source: str, bare: bool) -> None:
    assert any(not carries for _, carries in _scan(source)) is bare
