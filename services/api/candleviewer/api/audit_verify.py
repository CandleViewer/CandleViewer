"""`POST /admin/audit/verify` outcome: its `admin.audit_verify` records and the chain series
(contract #2392, design §5 and §9).

Records go straight to the audit writer, never through the 3a record budget, so a verify
record is never suppressed or folded into a summary. Each run writes at most two: a
write-ahead `started` record, then the result or the reason it stopped. A run cancelled
while it walks (a client that goes away, a shutdown) leaves only its `started` record. A
record that cannot be written in `WRITE_TIMEOUT_S` makes the call `503` with nothing served
(fail closed, C-2.9). The writer's `emit` is cancellation-safe, so the timeout never tears
an append. Outside the budget, these records are bounded only by verify's own run limits:
the per-user rate limit and single-flight.

Gauge rule (design §5): a break sets `cv_audit_chain_verified_state` to 0 and counts in
`audit_chain_verification_failures_total`; only a run from genesis to the head that found no
break sets it to 1, so a passing partial range never hides a known break. A full-range stop
turns 1 into NaN; 0 stays until a full-range run passes. So a stop never leaves an old 1
standing, and never clears a known break.

A break also raises the critical `audit_chain_break` system event (`system_events`, component
`db`), best effort as the recorder's integrity job does: bounded by `EVENT_TIMEOUT_S`, a
failure logged with its class only, never changing the response or the record.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from candleviewer.api.audit_budget import WRITE_TIMEOUT_S
from candleviewer.audit.models import AuditOutcome, Severity, VerifyResult
from candleviewer.observability.audit_query_metrics import (
    audit_chain_verification_failures_total,
    cv_audit_chain_verified_state,
)
from candleviewer.observability.health_probes import SystemEvent, SystemEventWriter
from candleviewer.settings import Settings

VERIFY_ACTION = "admin.audit_verify"
#: How long a run waits for its system event: best effort, the record is the primary.
EVENT_TIMEOUT_S = 2.0
#: The `audit_verify_deadline_s` default: how long one run may take before it is stopped
#: (503) and the single-flight slot is free again; well above a full `audit_verify_max_span` run.
VERIFY_DEADLINE_S: float = Settings.model_fields["audit_verify_deadline_s"].default


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


async def write_verify_record(
    emit: Callable[..., Awaitable[None]],
    fields: dict[str, Any],
    *,
    outcome: AuditOutcome,
    severity: Severity,
    reason: str,
    after_state: dict[str, Any],
) -> bool:
    """One `admin.audit_verify` record. False when the writer refused it or had not taken it
    within `WRITE_TIMEOUT_S`; `emit` is WAL-first and finishes an append it has started, so
    a record counted here as unwritten may still land (it errs toward recording more)."""
    try:
        async with asyncio.timeout(WRITE_TIMEOUT_S):
            await emit(
                VERIFY_ACTION,
                **fields,
                outcome=outcome,
                severity=severity,
                reason=reason,
                after_state=after_state,
            )
    except Exception as exc:  # the writer refused or ran out of time: the call is 503
        _log().warning("audit.verify.record_failed", reason=reason, error=type(exc).__name__)
        return False
    return True


def result_record(result: VerifyResult) -> tuple[AuditOutcome, Severity, str, dict[str, Any]]:
    """Outcome, severity, reason and `after_state` of a finished run's record: success/info
    when verified; failure/critical with reason `<kind>@<id>` on a break."""
    kind = None if result.kind is None else result.kind.value
    after = {
        "from_id": result.from_id,
        "to_id": result.to_id,
        "entries_checked": result.entries_checked,
        "verified": result.verified,
        "first_bad_id": result.first_bad_id,
        "kind": kind,
    }
    if result.verified:
        return AuditOutcome.SUCCESS, Severity.INFO, "verified", after
    return AuditOutcome.FAILURE, Severity.CRITICAL, f"{kind}@{result.first_bad_id}", after


def _chain_state() -> float:
    """The gauge's own value, the last one this process set (NaN, 0 or 1), read through the
    gauge's public `collect()`."""
    family = next(iter(cv_audit_chain_verified_state.collect()))
    return float(family.samples[0].value)


def observe_stop(*, full_chain: bool) -> None:
    """A full-range stop turns 1 into NaN; 0 stays until a full-range run passes. So a stop
    cannot keep an old 1 standing while such runs keep stopping, and cannot clear a known
    break or the alert on it. NaN stays NaN, and a partial range that stops leaves the gauge
    as it is."""
    if full_chain and _chain_state() == 1:
        cv_audit_chain_verified_state.set(math.nan)


def observe_verify(result: VerifyResult) -> None:
    """Apply the gauge rule and count a break."""
    if not result.verified:
        cv_audit_chain_verified_state.set(0)
        audit_chain_verification_failures_total.inc()
        _log().error("audit.verify.break", kind=result.kind, first_bad_id=result.first_bad_id)
    elif result.full_chain:
        cv_audit_chain_verified_state.set(1)


async def raise_break_event(
    events: SystemEventWriter | None, result: VerifyResult, correlation_id: str | None
) -> None:
    """The critical `audit_chain_break` system event for a break; nothing when verified or
    when no writer is wired."""
    if events is None or result.verified:
        return
    kind = None if result.kind is None else result.kind.value
    details = {"first_bad_id": result.first_bad_id, "kind": kind}
    details |= {"from_id": result.from_id, "to_id": result.to_id}
    event = SystemEvent(
        component="db",
        kind="audit_chain_break",
        severity="critical",
        message=f"audit chain break at id {result.first_bad_id}",
        details={key: "" if value is None else str(value) for key, value in details.items()},
        correlation_id=correlation_id,
    )
    try:
        async with asyncio.timeout(EVENT_TIMEOUT_S):
            await events.write(event)
    except Exception as exc:  # best effort: never the response, never the record
        _log().error("audit.verify.event_write_failed", error=type(exc).__name__)
