"""Feature-flag service, write path (E42-T03, module M21).

A write is refused before the store is touched unless it names a known flag, carries `reason`
and `expected_updated_at`, every value fits the flag's kind, and the store could be read.
`trading.live_enabled: true` also needs `evidence_url` (E44-T04 binds the evidence; this only
enforces the precondition). D2: the live gate and kill-switch-class flags take no overrides at
all, so the gate can never be bypassed per user. The store locks the row and compares
`updated_at`, so a stale write is a conflict carrying the current flag, never last-write-wins.

Audit (C-2.9): a refusal is one `flags.change` failure record. A write is audited write-ahead:
the intent record is emitted before `store.write`, and if it cannot be recorded nothing is
written; the outcome (`ok`, `conflict`, `unavailable`) follows as a second record. States carry
the value and the user overrides. `maintenance.mode` toggles add `maintenance.enabled|disabled`.
A committed write drops the cache and runs the change hook with the committed before and after
rows (the `system` push); a hook failure is logged and never undoes the write.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from typing import Any, Protocol, cast

import structlog

from candleviewer.admin.errors import AdminError
from candleviewer.admin.flags.catalogue import MAINTENANCE_MODE
from candleviewer.admin.flags.metrics import flag_changes_total
from candleviewer.admin.flags.registry import FlagSpec, FlagValue, value_matches
from candleviewer.admin.flags.resolver import StoredFlag, override_matches
from candleviewer.admin.flags.service import FlagService
from candleviewer.admin.flags.store import FlagWrite, StaleWriteError, StoreUnavailableError
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, ExchangeEnv, Severity

#: Change hook: `(key, before, after)` with the committed rows (the `system` push).
ChangeHook = Callable[[str, StoredFlag | None, StoredFlag], Awaitable[None]]


class AuditEmitter(Protocol):
    """Mirrors `AuditWriter.emit`'s keyword-only signature."""

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: str | uuid.UUID | None = None,
        actor_ip: str | None = None,
        session_id: str | uuid.UUID | None = None,
        object_kind: str | None = None,
        object_id: str | None = None,
        object_label: str | None = None,
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        severity: Severity = Severity.INFO,
        reason: str | None = None,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        request_id: str | uuid.UUID | None = None,
        env: ExchangeEnv | None = None,
    ) -> None: ...


class UnknownFlagError(AdminError, LookupError):
    """No flag has this key (`404 not_found`)."""


class FlagValidationError(AdminError, ValueError):
    """`422 validation_failed`; `rule` and `field` name the failed check."""

    def __init__(self, rule: str, field: str) -> None:
        super().__init__(f"{field}: {rule}")
        self.rule, self.field = rule, field


class FlagConflictError(AdminError):
    """`409 conflict`; `current` is the flag as stored now."""

    def __init__(self, current: StoredFlag) -> None:
        super().__init__("conflict")
        self.current = current


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


class FlagWriter:
    def __init__(
        self, service: FlagService, audit: AuditEmitter, *, on_change: ChangeHook | None = None
    ) -> None:
        self._service, self._audit, self._on_change = service, audit, on_change

    async def set(
        self,
        key: str,
        principal: AuditPrincipal,
        *,
        value: object,
        reason: str | None,
        expected_updated_at: datetime | None,
        evidence_url: str | None = None,
        user_overrides: Mapping[uuid.UUID, object] | None = None,
    ) -> StoredFlag:
        request = {
            "value": value,
            "overrides": _overrides(user_overrides),
            "reason": reason,
            "evidence_url": evidence_url,
        }
        audit = _Audit(self._audit, key, principal, request)
        spec = self._service.registry.get(key)
        if spec is None:
            await audit.refused(None, "not_found", counted=False)
            raise UnknownFlagError(key)
        self._service.invalidate()
        before = await self._service.stored(spec)
        if before is None:
            await audit.refused(None, "unavailable")
            raise StoreUnavailableError("flag store unreadable; nothing written")
        refusal = _refusal(spec, value, user_overrides, reason, expected_updated_at, evidence_url)
        if refusal is not None or expected_updated_at is None:
            refusal = refusal or FlagValidationError("required", "expected_updated_at")
            await audit.refused(before, refusal.rule)
            raise refusal
        # Omitted overrides keep the stored ones; a list replaces them (an empty one clears).
        kept = before.user_overrides if user_overrides is None else user_overrides
        change = FlagWrite(
            key,
            cast(FlagValue, value),
            {k: cast(FlagValue, v) for k, v in kept.items()},
            expected_updated_at,
            principal.user_id,
        )
        await audit.intent(before)  # write-ahead: raises, and nothing is written, if unrecorded
        try:
            after = await self._service.store.write(change)
        except StaleWriteError as exc:
            self._service.invalidate()
            await audit.outcome(exc.current, None, "conflict")
            raise FlagConflictError(exc.current) from None
        except StoreUnavailableError:
            await audit.outcome(before, None, "unavailable")
            raise
        self._service.invalidate()
        await audit.outcome(before, after, "ok")
        if spec.key == MAINTENANCE_MODE and before.value != after.value:
            await audit.maintenance(after)
        if self._on_change is not None:
            try:
                await self._on_change(key, before, after)
            except Exception:  # committed already: the push is best effort, logged
                logger().exception("feature_flag_push_failed", key=key)
        return after


def _refusal(
    spec: FlagSpec,
    value: object,
    overrides: Mapping[uuid.UUID, object] | None,
    reason: str | None,
    expected_updated_at: datetime | None,
    evidence_url: str | None,
) -> FlagValidationError | None:
    if not reason or not reason.strip():
        return FlagValidationError("required", "reason")
    if expected_updated_at is None:
        return FlagValidationError("required", "expected_updated_at")
    if overrides and not spec.overridable:
        return FlagValidationError("overrides_not_allowed", "overrides")
    if not value_matches(spec, value):
        return FlagValidationError("kind_mismatch", "value")
    if not all(override_matches(spec, v) for v in (overrides or {}).values()):
        return FlagValidationError("kind_mismatch", "overrides")
    if spec.requires_evidence and value is True and not evidence_url:
        return FlagValidationError("gate_evidence_required", "evidence_url")
    return None


def _overrides(overrides: Mapping[uuid.UUID, object] | None) -> dict[str, object] | None:
    return None if overrides is None else {str(k): v for k, v in overrides.items()}


def _state(stored: StoredFlag | None) -> dict[str, Any] | None:
    if stored is None:
        return None
    return {"value": stored.value, "overrides": _overrides(stored.user_overrides)}


class _Audit:
    def __init__(
        self, emitter: AuditEmitter, key: str, who: AuditPrincipal, request: dict[str, Any]
    ) -> None:
        self._emitter, self._key, self._request = emitter, key, request
        self._who = who

    async def _emit(self, action: str, **kwargs: Any) -> None:
        who = self._who
        await self._emitter.emit(
            action,
            actor_label=who.username,
            actor_user_id=who.user_id,
            actor_ip=who.ip,
            session_id=who.session_id,
            request_id=who.request_id,
            object_kind="feature_flag",
            object_id=self._key,
            severity=Severity.WARNING,
            **kwargs,
        )

    async def refused(
        self, before: StoredFlag | None, result: str, *, counted: bool = True
    ) -> None:
        if counted:  # unknown keys never reach a series: the label set stays bounded
            flag_changes_total.labels(self._key, result).inc()
        await self._emit(
            "flags.change",
            outcome=AuditOutcome.FAILURE,
            reason=result,
            before_state=_state(before),
            after_state={**self._request, "result": result},
        )

    async def intent(self, before: StoredFlag) -> None:
        await self._emit(
            "flags.change",
            outcome=AuditOutcome.SUCCESS,
            reason=self._request["reason"],
            before_state=_state(before),
            after_state={**self._request, "phase": "intent"},
        )

    async def outcome(self, before: StoredFlag, after: StoredFlag | None, result: str) -> None:
        flag_changes_total.labels(self._key, result).inc()
        try:
            await self._emit(
                "flags.change",
                outcome=AuditOutcome.SUCCESS if after is not None else AuditOutcome.FAILURE,
                reason=result,
                before_state=_state(before),
                after_state={**(_state(after) or self._request), "phase": "outcome"},
            )
        except Exception:  # the intent record already holds the change; the outcome is logged
            logger().exception("flags_change_outcome_audit_failed", key=self._key, result=result)

    async def maintenance(self, after: StoredFlag) -> None:
        action = "maintenance.enabled" if after.value is True else "maintenance.disabled"
        try:
            await self._emit(action, reason=self._request["reason"], after_state=_state(after))
        except Exception:  # never block the gate hook: the intent record holds the toggle
            logger().exception("maintenance_audit_failed", key=self._key)
