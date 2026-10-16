"""Feature-flag service, write path (E42-T03, module M21).

Request validation precedes the step-up gate; the gate, the `expected_updated_at` precondition and
the write then run under the flag's row lock, from the row as stored there, never a cached value
(D3b). Validation: `reason` and `expected_updated_at` are required, values fit the kind, safety
flags take no overrides (D2a), and `evidence_url` is an `https` URL of at most 2048 characters
with no credential (userinfo, a query token), never dereferenced, required to enable
`trading.live_enabled`. The gate is one elevation from `step_up_class`; an unreadable row counts as
engaged, and this console is never the emergency control. A stale write is a conflict.

Audit (C-2.9): every attempt past authentication and RBAC is a `flags.change` failure record (the
422s included), or a write-ahead intent (unrecorded, nothing is written) and its outcome; the auth
module audits a step-up challenge. A store outage (`503 store_unavailable`) is logged and counted
instead (SR-125). An unreadable row is recorded as `unreadable`. A real transition of the stored
`maintenance.mode` adds `maintenance.enabled|disabled` (D1c). A committed write drops the cache and
runs the change hook with the locked and committed rows; a hook failure never undoes the write.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, Protocol, cast
from urllib.parse import parse_qsl, urlsplit

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
from candleviewer.audit.redact import REDACTION_MARKER, redact

#: Change hook: `(key, before, after)` with the locked and the committed rows (the `system` push).
ChangeHook = Callable[[str, StoredFlag | None, StoredFlag], Awaitable[None]]
StepUpClass = Literal["killswitch", "live_enablement", "flags"]
#: Demands a fresh elevation of the class for the principal's session; raises to refuse (the
#: route answers `403 step_up_required` and the auth module audits `auth.step_up_required`).
StepUp = Callable[[AuditPrincipal, StepUpClass], Awaitable[None]]
EVIDENCE_URL_MAX: Final = 2048
#: Query or fragment parameter names that carry a credential, besides the audit redactor's (L3).
_TOKEN_PARAMS: Final = frozenset({"sig", "code", "auth", "pass", "pwd"})


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
    """`409 conflict`; `current` is the row as it stands now (rendered for the caller)."""

    def __init__(self, current: StoredFlag) -> None:
        super().__init__("conflict")
        self.current = current


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


def readable(spec: FlagSpec, row: StoredFlag | None) -> FlagValue | None:
    """The row's stored value, or `None` when the row is missing or unreadable (unknown)."""
    return row.value if row is not None and value_matches(spec, row.value) else None


def step_up_class(spec: FlagSpec, row: StoredFlag, value: object) -> StepUpClass:
    """D3a/D3b: the one elevation a write needs, from the key and the row as stored under the
    write's lock. An unreadable row counts as its fail-closed value: engaged for a kill switch.
    Writing `true` to the live gate needs `live_enablement` whatever is stored (L1)."""
    if spec.is_killswitch and value is False and readable(spec, row) is not False:
        return "killswitch"
    return "live_enablement" if spec.requires_evidence and value is True else "flags"


def stored_transition(spec: FlagSpec, before: StoredFlag | None, after: StoredFlag) -> bool:
    """D1c: a real transition of the stored value. An unknown (unreadable or missing) row to
    `True` counts, as a boot that finds a stored `True` does; unknown to `False` does not."""
    was = readable(spec, before)
    return after.value != was and (was is not None or after.value is True)


class FlagWriter:
    def __init__(
        self,
        service: FlagService,
        audit: AuditEmitter,
        step_up: StepUp,
        *,
        on_change: ChangeHook | None = None,
    ) -> None:
        self._service, self._audit, self._step_up = service, audit, step_up
        self._on_change = on_change

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
            "evidence_url": _audited_url(evidence_url),
        }
        if not principal.has("flags:write"):  # RBAC precedes every lookup and every 422 (L2)
            raise PermissionError("flags:write")
        spec = self._service.registry.get(key)
        audit = _Audit(self._audit, key, principal, request, spec)
        if spec is None:
            await audit.refused(None, "not_found", counted=False)
            raise UnknownFlagError(key)
        locked: list[StoredFlag] = []

        async def prepare(row: StoredFlag) -> FlagWrite:
            locked.append(row)
            refusal = _refusal(
                spec, value, user_overrides, reason, expected_updated_at, evidence_url
            )
            if refusal is not None or expected_updated_at is None:  # validation precedes the gate
                refusal = refusal or FlagValidationError("required", "expected_updated_at")
                await audit.refused(row, refusal.rule)
                raise refusal
            await self._step_up(principal, step_up_class(spec, row, value))
            # Omitted overrides keep the stored ones; a list replaces them (an empty one clears).
            kept = row.user_overrides if user_overrides is None else user_overrides
            await audit.intent(row)  # write-ahead: raises, and nothing is written, if unrecorded
            overrides = {k: cast(FlagValue, v) for k, v in kept.items()}
            return FlagWrite(
                key, cast(FlagValue, value), overrides, expected_updated_at, principal.user_id
            )

        try:
            after = await self._service.store.write(key, prepare)
        except StaleWriteError as exc:
            self._service.invalidate()
            await audit.outcome(exc.current, None, "conflict")
            raise FlagConflictError(exc.current) from None
        except StoreUnavailableError:  # the audit lives in this store: logged and counted instead
            flag_changes_total.labels(key, "store_unavailable").inc()
            rid = str(principal.request_id)  # the key and the correlation id only (L3)
            logger().warning("feature_flag_write_store_unavailable", key=key, request_id=rid)
            raise
        before = locked[-1]
        self._service.invalidate()
        await audit.outcome(before, after, "ok")
        if spec.key == MAINTENANCE_MODE and stored_transition(spec, before, after):
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
    if evidence_url and (rule := _evidence_rule(evidence_url)):
        return FlagValidationError(rule, "evidence_url")
    if spec.requires_evidence and value is True and not evidence_url:
        return FlagValidationError("gate_evidence_required", "evidence_url")
    return None


def _evidence_rule(url: str) -> str | None:
    """`credential_in_url` for userinfo or a query or fragment parameter that the audit would
    redact as a secret; `https_required` unless an `https` URL with a host; then the length."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:  # e.g. an unbalanced IPv6 bracket
        return "credential_in_url" if "@" in url else "https_required"
    params = dict.fromkeys(
        [n for q in (parts.query, parts.fragment) for n, _ in parse_qsl(q.replace(";", "&"))], ""
    )
    secret = REDACTION_MARKER in (redact(params) or {}).values() or not _TOKEN_PARAMS.isdisjoint(
        name.lower() for name in params
    )
    if "@" in parts.netloc or secret:
        return "credential_in_url"
    if parts.scheme.lower() != "https" or not host or not url.isprintable() or " " in url:
        return "https_required"
    return "string_too_long" if len(url) > EVIDENCE_URL_MAX else None


def _audited_url(url: str | None) -> str | None:
    """`evidence_url` as audited: a refused credential never reaches the record."""
    return "<redacted:credential>" if url and _evidence_rule(url) == "credential_in_url" else url


def _overrides(overrides: Mapping[uuid.UUID, object] | None) -> dict[str, object] | None:
    return None if overrides is None else {str(k): v for k, v in overrides.items()}


@dataclass(frozen=True, slots=True)
class _Audit:
    _emitter: AuditEmitter
    _key: str
    _who: AuditPrincipal
    _request: dict[str, Any]
    _spec: FlagSpec | None

    def _state(self, stored: StoredFlag | None) -> dict[str, Any] | None:
        if stored is None or self._spec is None:
            return None
        if readable(self._spec, stored) is None:  # never an unreadable row's raw value
            return {"unreadable": True}
        return {"value": stored.value, "overrides": _overrides(stored.user_overrides)}

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
        except Exception:  # the intent record already holds the change; the outcome is logged
            logger().exception("flags_change_outcome_audit_failed", key=self._key, result=result)

    async def maintenance(self, after: StoredFlag) -> None:
        action = "maintenance.enabled" if after.value is True else "maintenance.disabled"
        try:
            await self._emit(action, reason=self._request["reason"], after_state=self._state(after))
        except Exception:  # never block the gate hook: the intent record holds the toggle
            logger().exception("maintenance_audit_failed", key=self._key)
