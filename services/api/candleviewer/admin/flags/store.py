"""The ports of the flag service and its write path (E42-T03). The Postgres adapter over
`feature_flags` / `feature_flag_overrides` (`21-database-schema.md` 3.9) implements `FlagStore`;
the route slice adapts the users repository to `UserDirectory` and the auth module's step-up to
`StepUp`; `AuditWriter` is an `AuditEmitter`; the push and the maintenance gate are change hooks."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from candleviewer.admin.flags.policy import StepUpClass
from candleviewer.admin.flags.registry import FlagSpec, FlagValue
from candleviewer.admin.flags.resolver import StoredFlag
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, ExchangeEnv, Severity


class StoreUnavailableError(Exception):
    """The flag store could not be read or written."""


class StaleWriteError(Exception):
    """`expected_updated_at` no longer matches the stored row; `current` is the row now."""

    def __init__(self, current: StoredFlag) -> None:
        super().__init__("stale write")
        self.current = current


@dataclass(frozen=True, slots=True)
class FlagWrite:
    """The change `prepare` returns for the row it was given; `key` is the key being written."""

    key: str
    value: FlagValue
    user_overrides: Mapping[UUID, FlagValue]
    expected_updated_at: datetime
    actor: UUID


#: Called under the row lock with the row as stored; returns the change to write.
Prepare = Callable[[StoredFlag], Awaitable[FlagWrite]]


class FlagStore(Protocol):
    async def ensure(self, specs: Iterable[FlagSpec]) -> None:
        """Insert a row at the spec default for every flag that has none (startup, idempotent),
        so every flag has an `updated_at` a writer can name."""

    async def load(self) -> Mapping[str, StoredFlag]:
        """Every stored flag; raises `StoreUnavailableError`."""

    async def write(self, key: str, prepare: Prepare) -> StoredFlag:
        """In one transaction: lock the flag's row (`SELECT ... FOR UPDATE`), await `prepare` once
        with the row as stored, unreadable or not (it decides the step-up and returns the
        change, or raises and nothing is written), compare `updated_at` with
        `change.expected_updated_at` and write the value and the user overrides; the role
        overrides stay as they are. Returns the committed row. `prepare` is never retried: its
        step-up may be single-use and its intent is already audited.

        Raises `StaleWriteError` carrying the locked row on a mismatch, and
        `StoreUnavailableError` when the row cannot be locked and read within the read budget,
        when the flag has no row (its start-up `ensure` failed) or when the write fails. An
        exception `prepare` raises reaches the caller unchanged after the rollback, never
        wrapped, so a 422, a refused step-up or the writer's own 503 keeps its meaning. The
        read budget bounds the lock and the read; the writer bounds the awaits inside `prepare`.
        `updated_at` is compared at microsecond precision, the precision `isoformat()`
        serialises, so a value read back through `GET /admin/feature-flags` matches its row."""


class UserDirectory(Protocol):
    """Which users exist, for the `unknown_user` rule of a write's overrides. A user deleted
    after this check fails the override row's foreign key at commit, past the write-ahead
    intent: the store raises `StoreUnavailableError` and the writer records that outcome."""

    async def unknown(self, user_ids: frozenset[UUID]) -> frozenset[UUID]:
        """The ids in `user_ids` that name no user."""


#: Change hook: `(key, before, after)` with the locked and the committed rows (the `system` push).
ChangeHook = Callable[[str, StoredFlag | None, StoredFlag], Awaitable[None]]
#: Demands a fresh elevation of the class for the principal's session; raises to refuse (the
#: route answers `403 step_up_required` and the auth module audits `auth.step_up_required`).
StepUp = Callable[[AuditPrincipal, StepUpClass], Awaitable[None]]


class AuditEmitter(Protocol):
    """Mirrors `AuditWriter.emit`'s keyword-only signature."""

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: str | UUID | None = None,
        actor_ip: str | None = None,
        session_id: str | UUID | None = None,
        object_kind: str | None = None,
        object_id: str | None = None,
        object_label: str | None = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        severity: Severity = Severity.INFO,
        reason: str | None = None,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        request_id: str | UUID | None = None,
        env: ExchangeEnv | None = None,
    ) -> None: ...
