"""Feature-flag service, write path (E42-T03, module M21).

A write is refused before the store is touched unless it names a known flag, carries `reason`
and `expected_updated_at`, and every value fits the flag's kind. `trading.live_enabled: true`
also needs `evidence_url` (the evidence binding is E44-T04; this only enforces the
precondition), and nothing is written without it. The store locks the row and compares
`updated_at`, so a stale write is a conflict carrying the current flag, never last-write-wins.

Every attempt that reaches this service (RBAC and step-up passed at the route) is audited as
`flags.change` with the key, before, after, reason and evidence, ahead of the response: refused,
conflicting and failed attempts too. Toggling `maintenance.mode` also writes
`maintenance.enabled` or `maintenance.disabled`. After a committed write the service cache is
dropped and the change hook (the `system` push) runs; a hook failure is logged, never raised,
because the write has already committed.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, Protocol, cast
from uuid import UUID

import structlog

from candleviewer.admin.flags.catalogue import MAINTENANCE_MODE
from candleviewer.admin.flags.metrics import flag_changes_total
from candleviewer.admin.flags.registry import FlagSpec, FlagValue, value_matches
from candleviewer.admin.flags.resolver import StoredFlag, override_matches
from candleviewer.admin.flags.service import FlagService
from candleviewer.admin.flags.store import FlagWrite, StaleWriteError, StoreUnavailableError
from candleviewer.audit.models import AuditOutcome, Severity


class AuditEmitter(Protocol):
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class UnknownFlagError(LookupError):
    """No flag has this key (`404 not_found`)."""


class FlagValidationError(ValueError):
    """`422 validation_failed`; `rule` and `field` name the failed check."""

    def __init__(self, rule: str, field: str) -> None:
        super().__init__(f"{field}: {rule}")
        self.rule, self.field = rule, field


class FlagConflictError(Exception):
    """`409 conflict`; `current` is the flag as stored now."""

    def __init__(self, current: StoredFlag) -> None:
        super().__init__("conflict")
        self.current = current


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


class FlagWriter:
    def __init__(
        self,
        service: FlagService,
        audit: AuditEmitter,
        *,
        on_change: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._service, self._audit, self._on_change = service, audit, on_change

    async def set(
        self,
        key: str,
        *,
        actor_id: UUID,
        actor_label: str,
        value: object,
        reason: str | None,
        expected_updated_at: datetime | None,
        evidence_url: str | None = None,
        user_overrides: Mapping[UUID, object] | None = None,
    ) -> StoredFlag:
        request = {"value": value, "reason": reason, "evidence_url": evidence_url}
        audit = _Audit(self._audit, key, actor_id, actor_label, request)
        spec = self._service.registry.get(key)
        if spec is None:
            await audit.refused(None, "not_found")
            raise UnknownFlagError(key)
        overrides = dict(user_overrides or {})
        before = await self._current(spec)
        refusal = _refusal(spec, value, overrides, reason, expected_updated_at, evidence_url)
        if refusal is not None or expected_updated_at is None:
            refusal = refusal or FlagValidationError("required", "expected_updated_at")
            await audit.refused(before, refusal.rule, spec)
            raise refusal
        change = FlagWrite(
            key,
            cast(FlagValue, value),
            {k: cast(FlagValue, v) for k, v in overrides.items()},
            expected_updated_at,
            actor_id,
        )
        try:
            after = await self._service.store.write(change)
        except StaleWriteError as exc:
            self._service.invalidate()
            await audit.refused(exc.current, "conflict", spec)
            raise FlagConflictError(exc.current) from None
        except StoreUnavailableError:
            await audit.refused(before, "unavailable", spec)
            raise
        self._service.invalidate()
        await audit.committed(spec, before, after)
        if self._on_change is not None:
            try:
                await self._on_change(key)
            except Exception:  # committed already: the push is best effort, logged
                logger().exception("feature_flag_push_failed", key=key)
        return after

    async def _current(self, spec: FlagSpec) -> StoredFlag | None:
        self._service.invalidate()
        return await self._service.stored(spec)


def _refusal(
    spec: FlagSpec,
    value: object,
    overrides: Mapping[UUID, object],
    reason: str | None,
    expected_updated_at: datetime | None,
    evidence_url: str | None,
) -> FlagValidationError | None:
    if not reason or not reason.strip():
        return FlagValidationError("required", "reason")
    if expected_updated_at is None:
        return FlagValidationError("required", "expected_updated_at")
    if not value_matches(spec, value):
        return FlagValidationError("kind_mismatch", "value")
    if not all(override_matches(spec, v) for v in overrides.values()):
        return FlagValidationError("kind_mismatch", "overrides")
    if spec.requires_evidence and value is True and not evidence_url:
        return FlagValidationError("gate_evidence_required", "evidence_url")
    return None


class _Audit:
    def __init__(
        self, emitter: AuditEmitter, key: str, actor: UUID, label: str, request: dict[str, Any]
    ) -> None:
        self._emitter, self._key, self._request = emitter, key, request
        self._common: dict[str, Any] = {
            "actor_label": label,
            "actor_user_id": actor,
            "object_kind": "feature_flag",
            "object_id": key,
            "severity": Severity.WARNING,
        }

    async def refused(
        self, before: StoredFlag | None, result: str, spec: FlagSpec | None = None
    ) -> None:
        if spec is not None:  # unknown keys never reach a series: the label set stays bounded
            flag_changes_total.labels(self._key, result).inc()
        await self._emitter.emit(
            "flags.change",
            outcome=AuditOutcome.FAILURE,
            reason=result,
            before_state=_state(before),
            after_state={**self._request, "result": result},
            **self._common,
        )

    async def committed(self, spec: FlagSpec, before: StoredFlag | None, after: StoredFlag) -> None:
        flag_changes_total.labels(self._key, "ok").inc()
        await self._emitter.emit(
            "flags.change",
            outcome=AuditOutcome.SUCCESS,
            reason=self._request["reason"],
            before_state=_state(before),
            after_state={**self._request, "value": after.value},
            **self._common,
        )
        if spec.key == MAINTENANCE_MODE and (before is None or before.value != after.value):
            action = "maintenance.enabled" if after.value is True else "maintenance.disabled"
            await self._emitter.emit(
                action,
                reason=self._request["reason"],
                after_state={"value": after.value},
                **self._common,
            )


def _state(stored: StoredFlag | None) -> dict[str, Any] | None:
    return None if stored is None else {"value": stored.value}
