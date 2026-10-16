"""C-2.8 / SR-030a withdraw/transfer predicate for M13 (#2240).

Mirrors the M2 credential gate `reject_withdraw` added by E27-T02 (#2237): C-3.2 bars M13 from
importing M2, so the rule is restated here instead of shared. Migration 0019's
`ak_snapshot_shape` CHECK encodes the same rule in SQL; the shared corpus in
`tests/unit/accounts/_permission_cases.py` keeps the three in agreement. The M2 gate also applies
the SR-030 allow-list before a key is stored (#2270). This predicate and the CHECK stay deny-list
backstops that agree with each other; they move to the allow-list together, with the migration
that changes the CHECK.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from candleviewer.accounts.errors import WithdrawPermissionError

#: A fund-movement right is any name or value containing one of these, ignoring case
#: (`Withdraw`, `AccountTransfer`, `SubMemberTransfer`). Migration 0019's regex is
#: `withdraw|transfer` with the `i` flag.
FORBIDDEN_TOKENS = ("withdraw", "transfer")


def _normalise(permissions: Mapping[str, object]) -> dict[str, object]:
    """JSON round-trip: a value JSON cannot carry (bytes, iterators, NaN) raises, so the
    check fails closed instead of judging a value pydantic would later coerce."""
    try:
        normalised: dict[str, object] = json.loads(json.dumps(dict(permissions), allow_nan=False))
    except (TypeError, ValueError):
        raise WithdrawPermissionError("key_withdraw_permission") from None
    return normalised


def _names_right(value: object) -> bool:
    if isinstance(value, str):
        text = value.strip().lower()
        return any(token in text for token in FORBIDDEN_TOKENS)
    if isinstance(value, dict):
        return any(_names_right(k) or _names_right(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_names_right(v) for v in value)
    return False


def reject_withdraw(permissions: Mapping[str, object]) -> None:
    """Raise `WithdrawPermissionError` if any permission grants a withdraw or transfer right.

    A right counts as a value inside a group (`"Wallet": ["AccountTransfer"]`, the shape the
    exchange reports) or as a key, at any depth. Matching ignores case and leading/trailing
    whitespace only, not inner spacing or lookalike characters (the M2 allow-list refuses those).
    A group named for a right that grants nothing (`[]`, `null` or `""`) is allowed. That
    exemption is this predicate's alone: for the legacy key `Withdraw`, `PermissionSnapshot`
    (a list of strings) and 0017's DB conjunct (`jsonb_array_length`) still refuse `null`/`""`.
    """
    for name, value in _normalise(permissions).items():
        if _names_right(value) or (_names_right(name) and value not in (None, [], "")):
            raise WithdrawPermissionError("key_withdraw_permission")
