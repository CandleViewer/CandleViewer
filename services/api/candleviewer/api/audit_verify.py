"""`POST /admin/audit/verify` outcome: its `admin.audit_verify` records and the chain series
(contract #2392, design §5 and §9).

Records go straight to the audit writer, never through the 3a record budget, so a verify
record is never suppressed or folded into a summary. Each run writes at most two: a
write-ahead `started` record, then the result or the reason it stopped. A run cancelled
while it walks (a client that goes away, a shutdown) leaves only its `started` record. A
record that cannot be written in `WRITE_TIMEOUT_S` makes the call `503` with nothing served
(fail closed, C-2.9). The writer's `emit` is cancellation-safe, so the timeout never tears
an append. Outside the budget, these records are bounded only by verify's own run limits
(the per-user rate limit and single-flight that follow in the stack).

Gauge rule (design §5): a break sets `cv_audit_chain_verified_state` to 0 and counts in
`audit_chain_verification_failures_total`; only a run from genesis to the head that found no
break sets it to 1, so a passing partial range never hides a known break. A full-range stop
turns 1 into NaN; 0 stays until a full-range run passes. So a stop never leaves an old 1
standing, and never clears a known break.
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

VERIFY_ACTION = "admin.audit_verify"


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
