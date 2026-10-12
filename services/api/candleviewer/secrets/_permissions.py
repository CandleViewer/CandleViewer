"""C-2.8 / SR-030a permission gate and snapshot projection (E27-T02). Private to M2."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from candleviewer.secrets.errors import SnapshotInvalid, WithdrawPermissionRejected

_SNAPSHOT_KEYS = frozenset(
    {"fetched_at", "uid", "note", "readOnly", "permissions", "ips", "type", "expiredAt"}
)
_FORBIDDEN_TOKENS = ("withdraw", "transfer")


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


def reject_withdraw(permissions: Mapping[str, object]) -> None:
    """C-2.8 / SR-030a: refuse any key whose permissions name a withdraw *or* transfer
    right (`Withdraw`, `AccountTransfer`, `SubMemberTransfer`, ...) as a group key or a value,
    at any depth, case/space-insensitive. An empty group (`"Withdraw": []`) grants nothing."""
    normed = _norm(dict(permissions))
    if not isinstance(normed, dict):  # pragma: no cover - json of a dict is a dict
        raise WithdrawPermissionRejected("key_withdraw_permission")
    for name, value in normed.items():
        if _bad_token(value) or (_bad_token(name) and value not in (None, [], "")):
            raise WithdrawPermissionRejected("key_withdraw_permission")


def project_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only the allow-listed query-api fields (no `apiKey`, `rsaPublicKey`, ids)."""
    projected = _norm({k: v for k, v in snapshot.items() if k in _SNAPSHOT_KEYS})
    if not isinstance(projected, dict) or not isinstance(projected.get("permissions"), dict):
        raise SnapshotInvalid("snapshot_invalid")
    reject_withdraw(projected["permissions"])
    return projected
