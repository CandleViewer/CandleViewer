"""Feature-flag service, write path (E42-T03, module M21).

`FlagWriter.set` serves `PUT /admin/feature-flags/{flagKey}` (`22-api-openapi.yaml`
`setFeatureFlag`). RBAC comes first, so a caller without `flags:write` learns nothing from a 404
or a 422. Then, under the flag's row lock and from the row as stored there, never a cached value:
request validation, the step-up gate, the `expected_updated_at` precondition and the write.
Validation runs under the lock, not before it as the contract orders it, because every 422 is
audited with the row's `before`: a 422 holds the lock while it is audited, and an invalid request
during a store outage answers 503. The rules: `reason` and `expected_updated_at` are required,
values fit the kind, the live gate and the kill switches take no overrides, overrides name
existing users (`unknown_user`, the only rule with a lookup, so it runs last), and `evidence.py`
judges `evidence_url`, which enabling `trading.live_enabled` requires. The gate is one
elevation, `policy.step_up_class`. A stale write is a conflict.

Audit (C-2.9): every attempt past RBAC is a `flags.change` record: a failure record for a 404 or
a 422, else a write-ahead intent (unrecorded, nothing is written) and its outcome; the auth module
audits a step-up challenge. A store outage before the row is read is logged and counted instead
(SR-125); once the row was read, the outcome `store_unavailable` is also recorded, best effort.
An unreadable row is recorded as `unreadable`. A real transition of the stored `maintenance.mode`
adds `maintenance.enabled|disabled`. The writer's own awaits are bounded (`WRITE_AWAIT_TIMEOUT_S`).
A committed write drops the cache, runs the change hook with the locked and committed rows, then
records its outcome; neither a hook nor an audit failure undoes it. `readable`,
`stored_transition`, `AuditEmitter` and `ChangeHook` are re-exported for the push and the gate.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, cast

import structlog

from candleviewer.admin.errors import AdminError
from candleviewer.admin.flags.catalogue import MAINTENANCE_MODE
from candleviewer.admin.flags.evidence import check_evidence_url
from candleviewer.admin.flags.metrics import flag_changes_total
from candleviewer.admin.flags.policy import readable as readable
from candleviewer.admin.flags.policy import step_up_class
from candleviewer.admin.flags.policy import stored_transition as stored_transition
from candleviewer.admin.flags.registry import FlagSpec, FlagValue, value_matches
from candleviewer.admin.flags.resolver import StoredFlag, override_matches
from candleviewer.admin.flags.service import FlagService
from candleviewer.admin.flags.store import AuditEmitter as AuditEmitter
from candleviewer.admin.flags.store import ChangeHook as ChangeHook
from candleviewer.admin.flags.store import (
    FlagWrite,
    StaleWriteError,
    StepUp,
    StoreUnavailableError,
    UserDirectory,
)
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.models import AuditOutcome, Severity

#: The bound on the writer's own awaits (the store adapter bounds `store.write`): under the row
#: lock, the user lookup, the step-up and the audit records together, and an unknown key's record
#: (past it, `503 store_unavailable`); after the commit, the hook and each record (past it, logged).
WRITE_AWAIT_TIMEOUT_S: Final = 2.0


class FlagsWriteDenied(AdminError, PermissionError):
    """The principal lacks `flags:write` (`403`); raised before any lookup."""


class UnknownFlagError(AdminError, LookupError):
    """No flag has this key (`404 not_found`)."""


class FlagValidationError(AdminError, ValueError):
    """`422 validation_failed`; `rule` and `field` name the failed check."""

    def __init__(self, rule: str, field: str) -> None:
        super().__init__(f"{field}: {rule}")
        self.rule, self.field = rule, field


class FlagConflictError(AdminError):
    """`409 conflict`; `current` is the row as it stands now (rendered for the caller)."""

    def __init__(self, current: StoredFlag) -> None:
        super().__init__("conflict")
        self.current = current


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(__name__))


class FlagWriter:
    """Writes one feature flag through the store's row-locked `write`; the module docstring
    gives the order, the audit and the bounds."""

    def __init__(
        self,
        service: FlagService,
        audit: AuditEmitter,
        step_up: StepUp,
        users: UserDirectory,
        *,
        on_change: ChangeHook | None = None,
        await_timeout_s: float = WRITE_AWAIT_TIMEOUT_S,
    ) -> None:
        self._service, self._audit, self._step_up = service, audit, step_up
        self._users, self._on_change, self._timeout = users, on_change, await_timeout_s

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
        """Write `value`, and `user_overrides` unless `None` (which keeps the stored ones), to the
        flag `key` for `principal`; returns the committed row. Raises `FlagsWriteDenied` (403),
        `UnknownFlagError` (404), `FlagValidationError` (422), the step-up's refusal (403
        `step_up_required`), `FlagConflictError` (409) or `StoreUnavailableError` (503)."""
        if not principal.has("flags:write"):  # before every lookup and every 422
            raise FlagsWriteDenied("flags:write")
        evidence, audited_url = check_evidence_url(evidence_url)  # once per request
        request = {
            "value": value,
            "overrides": _overrides(user_overrides),
            "reason": reason,
            "evidence_url": audited_url,
        }
        spec = self._service.registry.get(key)
        audit = _Audit(self._audit, key, principal, request, spec, self._timeout)
        if spec is None:
            try:
                await audit.refused(None, "not_found", counted=False)
            except TimeoutError:  # a stalled record is a 503, as one under the row lock is
                raise StoreUnavailableError("a write await timed out") from None
            raise UnknownFlagError(key)
        url_rule: str | None = evidence
        if spec.requires_evidence and value is True and not evidence_url:
            url_rule = "gate_evidence_required"
        locked: list[StoredFlag] = []

        async def prepare(row: StoredFlag) -> FlagWrite:
            locked.append(row)
            # Omitted overrides keep the stored ones and a list replaces them (`[]` clears); a
            # safety flag keeps none, not even a row that reached the store another way.
            kept = row.user_overrides if user_overrides is None else user_overrides
            overrides = {k: cast(FlagValue, v) for k, v in kept.items()} if spec.overridable else {}
            new = cast(FlagValue, value)
            try:
                async with asyncio.timeout(self._timeout):  # bounds the row lock's hold
                    try:
                        expected = _validated(
                            spec, value, user_overrides, reason, expected_updated_at, url_rule
                        )
                        if user_overrides and await self._users.unknown(frozenset(user_overrides)):
                            raise FlagValidationError("unknown_user", "overrides")
                    except FlagValidationError as refusal:  # validation precedes the gate
                        await audit.refused(row, refusal.rule)
                        raise
                    change = FlagWrite(key, new, overrides, expected, principal.user_id)
                    await self._step_up(principal, step_up_class(spec, row, value), change)
                    await audit.intent(row)  # write-ahead: unrecorded, nothing is written
            except TimeoutError:  # nothing commits: answered as a store outage
                raise StoreUnavailableError("a write await timed out") from None
            return change  # the change the step-up restated

        try:
            after = await self._service.store.write(key, prepare)
        except StaleWriteError as exc:
            self._service.invalidate()
            await audit.outcome(exc.current, None, "conflict")
            raise FlagConflictError(exc.current) from None
        except StoreUnavailableError:  # the log carries the key and the correlation id only
            ids = {} if principal.request_id is None else {"request_id": str(principal.request_id)}
            logger().warning("feature_flag_write_store_unavailable", key=key, **ids)
            if not locked:  # no row was read: logged and counted instead (SR-125)
                flag_changes_total.labels(key, "store_unavailable").inc()
                raise
            self._service.invalidate()  # a commit may have landed before the store failed
            await audit.outcome(locked[-1], None, "store_unavailable")  # counts it; best effort
            raise
        before = locked[-1]
        self._service.invalidate()
        if self._on_change is not None:  # before the outcome record, which may be slow
            try:
                async with asyncio.timeout(self._timeout):
                    await self._on_change(key, before, after)
            except Exception:  # committed already: the hook is best effort, logged
                logger().exception("feature_flag_push_failed", key=key)
        await audit.outcome(before, after, "ok")
        if spec.key == MAINTENANCE_MODE and stored_transition(spec, before, after):
            await audit.maintenance(after)
        return after


def _validated(
    spec: FlagSpec,
    value: object,
    overrides: Mapping[uuid.UUID, object] | None,
    reason: str | None,
    expected_updated_at: datetime | None,
    url_rule: str | None,
) -> datetime:
    """The precondition, once every rule without a lookup holds; raises the first refusal."""
    if not reason or not reason.strip():
        raise FlagValidationError("required", "reason")
    if expected_updated_at is None:
        raise FlagValidationError("required", "expected_updated_at")
    if overrides and not spec.overridable:
        raise FlagValidationError("overrides_not_allowed", "overrides")
    if not value_matches(spec, value):
        raise FlagValidationError("kind_mismatch", "value")
    if not all(override_matches(spec, v) for v in (overrides or {}).values()):
        raise FlagValidationError("kind_mismatch", "overrides")
    if url_rule is not None:  # `evidence.py`'s rule, else the live gate's need for a URL
        raise FlagValidationError(url_rule, "evidence_url")
    return expected_updated_at


def _overrides(overrides: Mapping[uuid.UUID, object] | None) -> dict[str, object] | None:
    return None if overrides is None else {str(k): v for k, v in overrides.items()}


@dataclass(frozen=True, slots=True)
class _Audit:
    _emitter: AuditEmitter
    _key: str
    _who: AuditPrincipal
    _request: dict[str, Any]
    _spec: FlagSpec | None
    _timeout: float

    def _state(self, stored: StoredFlag | None) -> dict[str, Any] | None:
        if stored is None or self._spec is None:
            return None
        if readable(self._spec, stored) is None:  # never an unreadable row's raw value
            return {"unreadable": True}
        return {"value": stored.value, "overrides": _overrides(stored.user_overrides)}

    async def _emit(self, action: str, **kwargs: Any) -> None:
        who = self._who
        async with asyncio.timeout(self._timeout):
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
            before_state=self._state(before),
            after_state={**self._request, "result": result},
        )

    async def intent(self, before: StoredFlag) -> None:
        await self._emit(
            "flags.change",
            outcome=AuditOutcome.SUCCESS,
            reason=self._request["reason"],
            before_state=self._state(before),
            after_state={**self._request, "phase": "intent"},
        )

    async def outcome(self, before: StoredFlag, after: StoredFlag | None, result: str) -> None:
        flag_changes_total.labels(self._key, result).inc()
        try:
            await self._emit(
                "flags.change",
                outcome=AuditOutcome.SUCCESS if after is not None else AuditOutcome.FAILURE,
                reason=result,
                before_state=self._state(before),
                after_state={**(self._state(after) or self._request), "phase": "outcome"},
            )
        except Exception:  # best effort: the write's fate is settled, a lost record is logged
            logger().exception("flags_change_outcome_audit_failed", key=self._key, result=result)

    async def maintenance(self, after: StoredFlag) -> None:
        action = "maintenance.enabled" if after.value is True else "maintenance.disabled"
        try:
            await self._emit(action, reason=self._request["reason"], after_state=self._state(after))
        except Exception:  # best effort: the hook ran first and the intent holds the toggle
            logger().exception("maintenance_audit_failed", key=self._key)
