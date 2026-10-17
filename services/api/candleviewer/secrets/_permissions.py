"""C-2.8 / SR-030 / SR-030a key permission gate and snapshot projection (E27-T02). Private to M2.

Two lines refuse a key before anything is encrypted or audited: the SR-030 allow-list
(`require_allow_listed`, #2270) first, the substring deny-list (`reject_withdraw`) second. M13
(`accounts/_permissions.py`, `PermissionSnapshot`) and migration 0019's `ak_snapshot_shape` CHECK
keep only the deny-list, as backstops: C-3.2 bars M13 from importing this module, and an
allow-list CHECK needs a new migration (C-5.4).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

from candleviewer.secrets.errors import SnapshotInvalid, WithdrawPermissionRejected

_SNAPSHOT_KEYS = frozenset(
    {"fetched_at", "uid", "note", "readOnly", "permissions", "ips", "type", "expiredAt", "uta"}
)
_FORBIDDEN_TOKENS = ("withdraw", "transfer")

#: The only rights a stored key may hold, by group, spelled exactly (#2270). SR-030: "the scope
#: set is the minimum needed (Contract/Order/Position read+trade)"; SR-030a: the non-trading groups
#: are empty (`docs/plan/04-security-program.md`); E27 threat model section 5 item 2, SR-E27-04.
#: Every other group must be empty (`[]`) or absent. Defined once, here; read-only at run time.
ALLOWED_RIGHTS: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "ContractTrade": frozenset({"Order", "Position"}),
        "Derivatives": frozenset({"DerivativesTrade"}),
    }
)
#: A group name as the exchange spells one: an ASCII letter, then up to 63 ASCII letters or
#: digits. No padding, inner spacing, punctuation, invisible or lookalike characters.
_GROUP_NAME: Final = re.compile(r"[A-Za-z][A-Za-z0-9]{0,63}")


def _norm(value: object) -> object:
    """JSON round-trip: any non-JSON type (bytes, views, generators) raises ⇒ fail closed."""
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError):
        raise SnapshotInvalid("snapshot_invalid") from None


def _bad_token(value: object) -> bool:
    if isinstance(value, str):
        text = value.strip().lower()
        return any(tok in text for tok in _FORBIDDEN_TOKENS)
    if isinstance(value, dict):
        return any(_bad_token(k) or _bad_token(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_bad_token(v) for v in value)
    return False


def require_allow_listed(permissions: Mapping[str, object]) -> None:
    """SR-030 / SR-030a allow-list (#2270), the first line of the C-2.8 gate.

    Refuses the key, fail closed with the C-2.8 code, unless every group has a canonical name
    (`_GROUP_NAME`) and a list of rights, and every right in it is one `ALLOWED_RIGHTS` permits
    for that group, spelled exactly. So an unknown group or right, a right of another group, a
    non-canonical, non-ASCII or padded name, a non-list group (`null` and `""` included) and a
    non-string right are all refused. Group names are checked before the JSON round trip, which
    would turn `1` into `"1"` and could let a later duplicate hide an earlier group."""
    if not all(isinstance(group, str) for group in permissions):
        raise WithdrawPermissionRejected("key_withdraw_permission")
    normed = _norm(dict(permissions))
    if not isinstance(normed, dict):  # pragma: no cover - json of a dict is a dict
        raise WithdrawPermissionRejected("key_withdraw_permission")
    for group, rights in normed.items():
        if _GROUP_NAME.fullmatch(group) is None or not isinstance(rights, list):
            raise WithdrawPermissionRejected("key_withdraw_permission")
        allowed = ALLOWED_RIGHTS.get(group, frozenset())
        if not all(isinstance(right, str) and right in allowed for right in rights):
            raise WithdrawPermissionRejected("key_withdraw_permission")


def reject_withdraw(permissions: Mapping[str, object]) -> None:
    """C-2.8 / SR-030a deny-list, the gate's second line: refuse any key whose permissions name a
    withdraw *or* transfer right (`Withdraw`, `AccountTransfer`, `SubMemberTransfer`, ...) as a
    group key or a value, at any depth, ignoring case and leading/trailing whitespace only (inner
    spacing and lookalike characters are the allow-list's job). An empty group (`"Withdraw": []`)
    grants nothing."""
    normed = _norm(dict(permissions))
    if not isinstance(normed, dict):  # pragma: no cover - json of a dict is a dict
        raise WithdrawPermissionRejected("key_withdraw_permission")
    for name, value in normed.items():
        if _bad_token(value) or (_bad_token(name) and value not in (None, [], "")):
            raise WithdrawPermissionRejected("key_withdraw_permission")


def project_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only the allow-listed query-api fields (no `apiKey`, `rsaPublicKey`, ids), once both
    lines pass: the allow-list on the caller's own `permissions`, then the deny-list."""
    kept = {k: v for k, v in snapshot.items() if k in _SNAPSHOT_KEYS}
    projected = _norm(kept)
    if not isinstance(projected, dict) or not isinstance(projected.get("permissions"), dict):
        raise SnapshotInvalid("snapshot_invalid")
    require_allow_listed(kept["permissions"])
    reject_withdraw(projected["permissions"])
    return projected
