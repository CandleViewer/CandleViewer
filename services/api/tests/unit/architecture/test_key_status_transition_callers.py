"""#836 (E27-T03, SR-E27-01, AC-34): a key is promoted to `active` only after the pipeline's pass.

`AccountsStore.transition_key_status` flips a key's status with a compare-and-set and no
verification evidence, so it has exactly one production caller: key import's activation
(`accounts/key_import.py`), reached only once M2 stored a key the pipeline passed. Apart from its
port, its Postgres adapter and the `AccountsRepository` facade that hands the call down, any
call of it anywhere in `candleviewer` (a router, a job, another flow) fails here and must be
reviewed as a way to promote an unverified key first (threat model KV-T03, KV-E07).
"""

from __future__ import annotations

import ast
from pathlib import Path

import candleviewer
from candleviewer.accounts import key_import

PKG = Path(candleviewer.__file__).resolve().parent
NAME = "transition_key_status"
#: The facade that hands the call down to the store, and the one production caller.
CALLERS = frozenset({"accounts/repository.py", "accounts/key_import.py"})


def _calls(tree: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == NAME
    ]


def test_the_status_transition_has_one_production_caller_and_its_facade() -> None:
    found = {
        path.relative_to(PKG).as_posix()
        for path in PKG.rglob("*.py")
        if NAME in (text := path.read_text(encoding="utf-8")) and _calls(ast.parse(text))
    }
    assert found == CALLERS


def test_key_import_promotes_once_and_only_from_pending_to_active() -> None:
    tree = ast.parse(Path(key_import.__file__).read_text(encoding="utf-8"))
    (call,) = _calls(tree)
    keywords = {k.arg: ast.unparse(k.value) for k in call.keywords}
    assert keywords == {"expected": "KeyStatus.PENDING", "new": "KeyStatus.ACTIVE"}
    (activate,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and call in ast.walk(node)
    ]
    assert activate.name == "_activate"  # reached only with the key M2 stored after a pass
