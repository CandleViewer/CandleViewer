"""C-2.8 / SR-030a withdraw/transfer predicate for M13 (#2240).

The rule is the shared kernel's (`candleviewer.domain.key_permissions`), which the M2 credential
gate added by E27-T02 (#2237) wraps too: C-3.2 bars M13 from importing M2, and the kernel imports
neither. This wrapper raises M13's own error. Migration 0019's `ak_snapshot_shape` CHECK encodes
the same rule in SQL; the shared corpus in `tests/unit/accounts/_permission_cases.py` keeps them
in agreement. The M2 gate also applies the SR-030 allow-list before a key is stored (#2270). This
predicate and the CHECK stay deny-list backstops that agree with each other; they move to the
allow-list together, with the migration that changes the CHECK.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from candleviewer.accounts.errors import WithdrawPermissionError
from candleviewer.domain import key_permissions

#: A fund-movement right is any name or value containing one of these, ignoring case
#: (`Withdraw`, `AccountTransfer`, `SubMemberTransfer`). Migration 0019's regex is
#: `withdraw|transfer` with the `i` flag.
FORBIDDEN_TOKENS: Final = key_permissions.FORBIDDEN_TOKENS


def reject_withdraw(permissions: Mapping[str, object]) -> None:
    """Raise `WithdrawPermissionError` if any permission grants a withdraw or transfer right.

    A right counts as a value inside a group (`"Wallet": ["AccountTransfer"]`, the shape the
    exchange reports) or as a key, at any depth. Matching ignores case and leading/trailing
    whitespace only, not inner spacing or lookalike characters (the M2 allow-list refuses those).
    A group named for a right that grants nothing (`[]`, `null` or `""`) is allowed. That
    exemption is this predicate's alone: for the legacy key `Withdraw`, `PermissionSnapshot`
    (a list of strings) and 0017's DB conjunct (`jsonb_array_length`) still refuse `null`/`""`.
    Permissions the kernel cannot judge exactly (a key that is not a string, a value JSON cannot
    carry, nesting past its bound) are refused the same way (fail closed).
    """
    try:
        granted = key_permissions.grants_fund_right(permissions)
    except key_permissions.PermissionsUnreadable:
        raise WithdrawPermissionError("key_withdraw_permission") from None
    if granted:
        raise WithdrawPermissionError("key_withdraw_permission")
