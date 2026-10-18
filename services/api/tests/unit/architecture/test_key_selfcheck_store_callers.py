"""#836 (E27-T03): the stored-key self-check's system port takes no principal scope.

`KeySelfCheckStore` can set `trading_enabled` false on any account of the environment and rewrite
the verification columns of any key, with no principal. `accounts.selfcheck` is its one caller,
the M10 port its one definition, the Postgres adapter its one implementation and the composition
root's `key_selfcheck_wiring` the one place that builds it for the job. Key import (#836 slice
2b4) also writes the verified columns, of the one key its own request stored under the id M2
minted, after the route's RBAC (`keys:manage`): `accounts.key_import` calls `record_pass` only,
and `key_import_wiring` builds its store. A reference anywhere else in
`candleviewer` (an `api/` router, a WS topic, the `AccountsRepository` facade) fails here and must
be reviewed as an RBAC bypass first (C-12.4, SR-051), as for the row counts in
`test_accounts_row_counts_callers.py`.

One reviewed second reader (E27-T04, #837): the composition root's `account_health_wiring` builds a
store of its own bound to the process environment and calls `targets()` and nothing else, to learn
which enabled accounts hold a usable key. It types what it holds as a read-only protocol (mypy
refuses a write) and hands the health runtime the account ids only, never a row; the key standing
(#837 W3) reduces the same read's rows at once to key ids, pass times, error codes and an armed
flag, and keeps none. The last tests below fail if the wiring names a write of the port in any way
at all, a call or not.

A module uses the port when it names the port type or calls one of its methods on an object
(`store.targets()`). Methods match as attribute calls, not text: `record_error` is also the name
of a statechart action. The wiring is held to more, since it may name none of the writes.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import candleviewer

PKG = Path(candleviewer.__file__).resolve().parent
PORT = "KeySelfCheckStore"
METHODS = frozenset(
    {
        "targets",
        "record_pass",
        "record_error",
        "disable_trading",
        "owed_disarms",
        "mark_disarm_audited",
    }
)
WRITES = METHODS - {"targets"}
#: Ways to reach an attribute by a name built at run time: the wiring has no use for one.
DYNAMIC = frozenset({"getattr", "setattr", "vars", "eval", "exec"})
ALLOWED = frozenset(
    {
        "accounts/selfcheck.py",
        "storage/repositories/accounts.py",
        "storage/repositories/key_selfcheck_sqlalchemy.py",
        "key_selfcheck_wiring.py",
        "account_health_wiring.py",
        "accounts/key_import.py",
        "key_import_wiring.py",
    }
)


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


def _reaches_a_write(text: str) -> set[str]:
    """Every name that reaches a write of the port other than as a plain call: an attribute (a
    reference kept in a variable), a name, an import, a string (`getattr(store, "...")`), or a
    lookup by a name built at run time (`getattr` and its kin)."""
    named: set[str] = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Attribute):
            named.add(node.attr)
        elif isinstance(node, ast.Name):
            named.add(node.id)
        elif isinstance(node, ast.alias):
            named.add(node.name.rpartition(".")[2])
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            named.add(node.value)
    return named & (WRITES | DYNAMIC)


def test_the_account_health_wiring_reads_the_usable_keys_and_calls_nothing_else() -> None:
    assert _users()["account_health_wiring.py"] == {"targets", PORT}


def test_the_account_health_wiring_names_no_write_of_the_port() -> None:
    text = (PKG / "account_health_wiring.py").read_text(encoding="utf-8")
    assert _reaches_a_write(text) == set()


@pytest.mark.parametrize(
    ("source", "reached"),
    [
        ("store.disable_trading(account)", {"disable_trading"}),
        ("w = store.disable_trading", {"disable_trading"}),
        ("getattr(store, 'record_pass')", {"getattr", "record_pass"}),
        ("getattr(store, name)", {"getattr"}),
        ("from candleviewer.x import record_error", {"record_error"}),
        ("store.targets()", set()),
    ],
)
def test_the_wiring_check_sees_every_way_to_reach_a_write_and_lets_the_read_through(
    source: str, reached: set[str]
) -> None:
    assert _reaches_a_write(source) == reached


def test_key_import_writes_only_the_verified_columns() -> None:
    assert _users()["accounts/key_import.py"] == {"record_pass"}
