"""Key-age policy evaluation (E27-T04, US-ACCT-005): `ApiKey.rotation_due_at` and `rotation_state`.

Pure: the answer follows from the key's registration time and status, the policy and `now`, and
nothing is stored, so a policy change recomputes every key on the same call. `rotation_due_at` is
`created_at` plus the policy, never the exchange-reported `expires_at` (US-ACCT-005 NFR). Age only
reports: nothing here disables a key, and the order-entry gate never reads it. The column
`api_keys.rotation_due_at` is never written and stays NULL (21-database-schema.md), so serve both
fields from `KeyRotationPolicy.evaluate`, never from `ApiKeyMetadata.rotation_due_at`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from candleviewer.accounts.models import KeyStatus
from candleviewer.settings import Settings


class RotationState(StrEnum):
    OK = "ok"
    WARN = "warn"
    OVERDUE = "overdue"


@dataclass(frozen=True, slots=True)
class KeyRotation:
    """`ApiKey.rotation_due_at` and `rotation_state`; both `None` unless the key is active."""

    rotation_due_at: datetime | None = None
    rotation_state: RotationState | None = None


@dataclass(frozen=True, slots=True)
class KeyRotationPolicy:
    """`CV_KEY_ROTATION_POLICY_DAYS` and `CV_KEY_ROTATION_WARN_DAYS`, deployment config for v1
    (decision Q4 on #837). Settings caps both; a window of at least a day that ends before the
    due date keeps the warning reachable."""

    policy_days: int = 90
    warn_days: int = 14

    def __post_init__(self) -> None:
        if not 0 < self.warn_days < self.policy_days:
            raise ValueError("key rotation needs 0 < warn_days < policy_days")

    @classmethod
    def from_settings(cls, settings: Settings) -> KeyRotationPolicy:
        return cls(settings.rotation_policy_days, settings.rotation_warn_days)

    def evaluate(self, created_at: datetime, status: KeyStatus, *, now: datetime) -> KeyRotation:
        """`warn` from `warn_days` before `rotation_due_at` through it, `overdue` once the key is
        older than the policy (21-database-schema.md query 33: `rotation_due_at < now()`), so a
        76-day-old key warns under 90/14 and a 90-day-old one is not yet overdue."""
        if status != KeyStatus.ACTIVE:
            return KeyRotation()
        due = created_at + timedelta(days=self.policy_days)
        if now > due:
            return KeyRotation(due, RotationState.OVERDUE)
        if now >= due - timedelta(days=self.warn_days):
            return KeyRotation(due, RotationState.WARN)
        return KeyRotation(due, RotationState.OK)
