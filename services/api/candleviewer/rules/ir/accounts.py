"""Generic account-reference walker over a rule IR document (E35-X02 j/k).

Any key named like ``account_id`` / ``account_ids`` (case-insensitive, any depth, including
free-form ``params`` dicts) is an account reference. The key set is derived from the IR
pydantic models, and a test asserts the walker covers every such model field.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel

#: Matched against the whole key, line breaks included (22 `RuleInput`, #4835).
ACCOUNT_KEY = re.compile(r"(?:.*_)?account_?ids?", re.IGNORECASE | re.DOTALL)


def is_account_key(key: object) -> bool:
    return isinstance(key, str) and ACCOUNT_KEY.fullmatch(key) is not None


def model_account_fields(*models: type[BaseModel]) -> set[str]:
    """Every field name on the given pydantic models that names an account reference."""
    return {name for m in models for name in m.model_fields if is_account_key(name)}


def holds_account_key(doc: Any) -> bool:
    """Whether ``doc`` holds an account-reference key at any depth, whatever its value (an empty
    list names accounts too): a save body names no account outside ``ir`` (#4835). Iterative, so
    no depth exhausts the stack."""
    todo = [doc]
    while todo:
        cur = todo.pop()
        if isinstance(cur, dict):
            if any(is_account_key(k) for k in cur):
                return True
            todo.extend(cur.values())
        elif isinstance(cur, list | tuple):
            todo.extend(cur)
    return False


def collect_account_ids(doc: Any) -> tuple[str, ...]:
    """All account ids referenced anywhere in ``doc`` (dicts/lists/tuples), in order."""
    out: list[str] = []
    _collect(doc, out)
    return tuple(dict.fromkeys(out))


def _collect(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if is_account_key(k):
                _values(v, out)
            else:
                _collect(v, out)
    elif isinstance(node, list | tuple):
        for item in node:
            _collect(item, out)


def _values(v: Any, out: list[str]) -> None:
    if v is None:
        return
    if isinstance(v, list | tuple | set | frozenset):
        for x in v:
            _values(x, out)
    elif isinstance(v, dict):
        _collect(v, out)
    else:
        out.append(str(v))


def redact_account_ids(doc: Any) -> Any:
    """Deep copy of ``doc`` with every account-reference key removed."""
    if isinstance(doc, dict):
        return {k: redact_account_ids(v) for k, v in doc.items() if not is_account_key(k)}
    if isinstance(doc, list | tuple):
        return [redact_account_ids(x) for x in doc]
    return doc
