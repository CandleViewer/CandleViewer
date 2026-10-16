"""#836 (E27-T03): the stored-key self-check's system port takes no principal scope.

`KeySelfCheckStore` can rewrite the verification columns of any key of the environment, with no
principal. `accounts.selfcheck` is its one caller and the M10 port its one definition; the
Postgres adapter joins `ALLOWED` when it lands (#836 slice 2b). A reference anywhere else in
`candleviewer` (an `api/` router, a WS topic, the `AccountsRepository` facade) fails here and must
be reviewed as an RBAC bypass first (C-12.4, SR-051), as for the row counts in
`test_accounts_row_counts_callers.py`.

A module uses the port when it names the port type or calls one of its methods on an object
(`store.targets()`). Methods match as attribute calls, not text: `record_error` is also the name
of a statechart action.
"""

from __future__ import annotations

import ast
from pathlib import Path

import candleviewer

PKG = Path(candleviewer.__file__).resolve().parent
PORT = "KeySelfCheckStore"
METHODS = frozenset({"targets", "record_pass", "record_error"})
ALLOWED = frozenset({"accounts/selfcheck.py", "storage/repositories/accounts.py"})


def _uses(text: str) -> set[str]:
    called = {
        node.func.attr
        for node in ast.walk(ast.parse(text))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    return (called & METHODS) | ({PORT} if PORT in text else set())


def _users() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in PKG.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(name in text for name in (PORT, *METHODS)) and (names := _uses(text)):
            found[path.relative_to(PKG).as_posix()] = names
    return found


def test_the_self_check_port_is_used_only_by_the_job_and_the_store() -> None:
    assert set(_users()) == ALLOWED


def test_the_scan_still_finds_every_port_method_the_job_calls() -> None:
    assert _users()["accounts/selfcheck.py"] == METHODS | {PORT}
