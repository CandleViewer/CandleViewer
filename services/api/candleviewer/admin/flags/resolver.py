"""Pure feature-flag resolution (E42-T03, module M21).

The order is fixed by `21-database-schema.md` 3.9: user override, then role override, then
percentage rollout (`hash(user_id || flag_key)`), then the stored deployment value. Resolution is
server-side only; a client copy is advisory for the UI and never enforces anything.

Fail closed: `stored is None` means the store could not be read, and a stored value or override
that does not fit the kind (a hand-edited row) is ignored. Both fall back to the spec's
`fail_closed_value`, which is the restrictive value for safety-relevant flags.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final
from uuid import UUID

from candleviewer.admin.flags.registry import FlagKind, FlagSpec, FlagValue, value_matches

#: Role-override precedence when a principal holds several roles (the closed role_name set).
ROLE_ORDER: Final = ("owner", "manager", "viewer")


@dataclass(frozen=True, slots=True)
class StoredFlag:
    """One flag's persisted state: the deployment value (`feature_flags.default_value`; the
    rollout percentage for a `percentage` flag) and its overrides."""

    value: FlagValue
    user_overrides: Mapping[UUID, FlagValue] = field(default_factory=dict)
    role_overrides: Mapping[str, FlagValue] = field(default_factory=dict)
    updated_at: datetime | None = None
    updated_by: UUID | None = None


def rollout_bucket(user_id: UUID, key: str) -> int:
    """The user's stable bucket 0-99 for `key` (sha256, so it never varies between processes)."""
    digest = hashlib.sha256(f"{user_id}{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % 100


def override_matches(spec: FlagSpec, value: object) -> bool:
    """An override pins the resolved value, so a `percentage` override is a bool (in or out)."""
    if spec.kind is FlagKind.PERCENTAGE:
        return isinstance(value, bool)
    return value_matches(spec, value)


def _override(
    spec: FlagSpec, stored: StoredFlag, user_id: UUID | None, roles: frozenset[str]
) -> FlagValue | None:
    if not spec.overridable:  # D2: a stored override on the live gate or a kill switch is ignored
        return None
    candidates: list[FlagValue] = []
    if user_id is not None and user_id in stored.user_overrides:
        candidates.append(stored.user_overrides[user_id])
    candidates += [
        stored.role_overrides[r] for r in ROLE_ORDER if r in roles and r in stored.role_overrides
    ]
    return next((v for v in candidates if override_matches(spec, v)), None)


def resolve(
    spec: FlagSpec,
    stored: StoredFlag | None,
    *,
    user_id: UUID | None,
    roles: frozenset[str] = frozenset(),
) -> FlagValue:
    """The value `spec` resolves to for one caller (`user_id=None`: a system read, no rollout)."""
    if stored is None:
        value = spec.fail_closed_value
    else:
        pinned = _override(spec, stored, user_id, roles)
        if pinned is not None:
            return pinned
        value = stored.value if value_matches(spec, stored.value) else spec.fail_closed_value
    if spec.kind is FlagKind.PERCENTAGE:
        pct = int(value)
        if user_id is None:
            return pct >= 100
        return rollout_bucket(user_id, spec.key) < pct
    return value
