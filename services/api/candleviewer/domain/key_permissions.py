"""The C-2.8 / SR-030a key-permission deny-list: one predicate for M2 and M13 (#2240).

The credential gate (M2, `secrets/_permissions.py`) and the accounts model and key verification
(M13, `accounts/_permissions.py`) each used to keep a copy of this rule, held equal only by tests,
because C-3.2 bars M13 from importing M2. It lives here instead, in the shared kernel, which every
module may import and which imports no other `candleviewer` module (see the package docstring).
Each module keeps a thin wrapper that raises its own error. Migration 0019's `ak_snapshot_shape`
CHECK encodes the same rule in SQL, and one corpus (`tests/unit/accounts/_permission_cases.py`)
holds the predicate, the accounts model and the CHECK to it.

Permissions grant a fund-movement right when a group name or a value names `withdraw` or
`transfer`, ignoring case and leading or trailing whitespace, at any depth: a right listed inside
a group (the shape the exchange reports) or a key. A group named for a right that grants nothing
(`[]`, `null` or `""`) is allowed. It is a substring deny-list: inner spacing and lookalike
characters pass it, and M2's allow-list refuses them (#2270).

Permissions the rule cannot judge exactly are unreadable, and both wrappers refuse them (fail
closed): a key that is not a string at any depth, nesting deeper than `MAX_DEPTH`, or a value JSON
cannot carry (bytes, iterators, NaN). Keys and depth are checked before the JSON round trip that
normalises the input, because that round trip writes `None` as `"null"` and `1` as `"1"` and keeps
the last of two equal keys, so a later empty group would hide an earlier right.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Final

#: A right is a name or value containing one of these, ignoring case (migration 0019's regex is
#: `withdraw|transfer` with the `i` flag).
FORBIDDEN_TOKENS: Final = ("withdraw", "transfer")
#: The deepest container judged, counted below the permissions object. A stored snapshot holds
#: its rights two levels down (a group, then its list), so nothing near this bound is a reply.
MAX_DEPTH: Final = 32
#: What a group named for a right may hold and still grant nothing.
_GRANTS_NOTHING: Final[tuple[object, ...]] = (None, [], "")


class PermissionsUnreadable(ValueError):
    """The permissions cannot be judged exactly, so they are refused (fail closed). The message
    is fixed: it never carries any part of the input."""

    def __init__(self) -> None:
        super().__init__("permissions_unreadable")


def grants_fund_right(permissions: Mapping[str, object]) -> bool:
    """Whether `permissions` grants a withdraw or transfer right (C-2.8, SR-030a); raises
    `PermissionsUnreadable` when they cannot be judged exactly."""
    _require_plain(permissions, 0)
    try:
        normalised: dict[str, object] = json.loads(json.dumps(dict(permissions), allow_nan=False))
    except (TypeError, ValueError):
        raise PermissionsUnreadable from None
    return any(
        _names_right(value) or (_names_right(name) and value not in _GRANTS_NOTHING)
        for name, value in normalised.items()
    )


def _require_plain(value: object, depth: int) -> None:
    """Refuse what the JSON round trip would change without failing: a key that is not a string
    (a `str` subclass included) and nesting past `MAX_DEPTH`, which also stops a cycle."""
    children: Iterable[object]
    if isinstance(value, Mapping):
        if depth > MAX_DEPTH or any(type(key) is not str for key in value):
            raise PermissionsUnreadable
        children = value.values()
    elif isinstance(value, list | tuple):
        if depth > MAX_DEPTH:
            raise PermissionsUnreadable
        children = value
    else:
        return
    for child in children:
        _require_plain(child, depth + 1)


def _names_right(value: object) -> bool:
    if isinstance(value, str):
        text = value.strip().lower()
        return any(token in text for token in FORBIDDEN_TOKENS)
    if isinstance(value, dict):
        return any(_names_right(k) or _names_right(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_names_right(v) for v in value)
    return False
