"""Key-age policy evaluation (E27-T04, US-ACCT-005): `ApiKey.rotation_due_at` and `rotation_state`.

Pure: the answer follows from the key's registration time and status, the policy and `now`, and
nothing is stored, so a policy change recomputes every key on the same call. `rotation_due_at` is
`created_at` plus the policy, never the exchange-reported `expires_at` (US-ACCT-005 NFR). Age only
reports: nothing here disables a key, and the order-entry gate never reads it. The column
`api_keys.rotation_due_at` is never written and stays NULL (21-database-schema.md), so serve both
fields from `KeyRotationPolicy.evaluate`, never from `ApiKeyMetadata.rotation_due_at`.

`KeyAgeNotices` is the key-age job that the KeyRotationWarn and KeyRotationOverdue tickets read
(#837 W6); it too only reports.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Final
from uuid import UUID

import structlog

from candleviewer.accounts.health import Clock
from candleviewer.accounts.models import KeyStatus
from candleviewer.settings import Settings

if TYPE_CHECKING:
    from candleviewer.observability.metrics import BoundedMetric

#: An overdue key is counted again this long after its last notice, on the boot-time clock: the
#: daily alert of US-ACCT-005 while it stays overdue.
OVERDUE_EVERY_S: Final = 86_400.0


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


@dataclass(frozen=True, slots=True)
class RegisteredKey:
    """A stored key as the key-age job reads it: its id, its account, when it was registered and
    its status."""

    key_id: UUID
    account_id: UUID
    created_at: datetime
    status: KeyStatus


class KeyAgeNotices:
    """The key-age job: `observe` evaluates every key it is given, which the account health runtime
    does at boot and at each read of the stored keys after it. It sets `cv_keys_rotation_state` per
    state and counts a notice in `cv_key_rotation_notices_total` once per key as it enters `warn`
    and once a day per `overdue` key, each logged as `account.key_rotation_notice`. It never
    disables a key, writes nothing, and the order-entry gate never reads it (US-ACCT-005). What it
    counted is held in memory, so a restart counts the keys already in `warn` or `overdue` again
    at its first read. For one event loop; no I/O."""

    def __init__(
        self,
        policy: KeyRotationPolicy,
        clock: Clock,
        *,
        notices: BoundedMetric,
        states: BoundedMetric,
    ) -> None:
        self._policy, self._clock = policy, clock
        self._notices, self._states = notices, states
        self._warned: set[UUID] = set()  # the keys in `warn` at the last read
        self._overdue: dict[UUID, float] = {}  # each overdue key's last notice, monotonic

    def observe(self, keys: Iterable[RegisteredKey]) -> None:
        """Evaluate `keys`, the whole of one read: a key missing from it is forgotten, so one
        that comes back in `warn` or `overdue` is counted again. All or nothing: every key is
        evaluated before anything is counted, set or kept, so a read that raises midway (a key
        it cannot evaluate) leaves the notices, the gauge and what was counted as they were."""
        now, mono = self._clock.now(), self._clock.monotonic()
        rotations = [
            (key, self._policy.evaluate(key.created_at, key.status, now=now)) for key in keys
        ]
        held = dict.fromkeys(RotationState, 0)
        warned: set[UUID] = set()
        overdue: dict[UUID, float] = {}
        notices: list[tuple[RegisteredKey, RotationState, datetime]] = []
        for key, rotation in rotations:
            state, due = rotation.rotation_state, rotation.rotation_due_at
            if state is None or due is None:
                continue
            held[state] += 1
            if state is RotationState.WARN:
                warned.add(key.key_id)
                if key.key_id not in self._warned:
                    notices.append((key, state, due))
            elif state is RotationState.OVERDUE:
                last = self._overdue.get(key.key_id, -math.inf)
                if mono - last >= OVERDUE_EVERY_S:
                    notices.append((key, state, due))
                    last = mono
                overdue[key.key_id] = last
        self._warned, self._overdue = warned, overdue
        for rotation_state, count in held.items():
            self._states.labels(rotation_state).set(count)
        for key, state, due in notices:
            self._notice(key, state, due)

    def _notice(self, key: RegisteredKey, state: RotationState, due: datetime) -> None:
        """Count and log one notice. The due date is logged to the second: a stored
        `created_at` carries microseconds, and a 6-digit run reads as a TOTP code to the log
        redaction, which would replace the whole value (C-12.6)."""
        self._notices.labels(state).inc()
        structlog.get_logger(__name__).warning(
            "account.key_rotation_notice",
            key_id=str(key.key_id),
            account_id=str(key.account_id),
            state=state.value,
            rotation_due_at=due.isoformat(timespec="seconds"),
        )
