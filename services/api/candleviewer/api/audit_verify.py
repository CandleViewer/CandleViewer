"""`POST /admin/audit/verify` outcome: its `admin.audit_verify` records (contract #2392,
design §9).

Records go straight to the audit writer, never through the 3a record budget, so a verify
record is never suppressed or folded into a summary. Each run writes at most two: a
write-ahead `started` record, then the result or the reason it stopped. A run cancelled
while it walks (a client that goes away, a shutdown) leaves only its `started` record. A
record that cannot be written in `WRITE_TIMEOUT_S` makes the call `503` with nothing served
(fail closed, C-2.9). The writer's `emit` is cancellation-safe, so the timeout never tears
an append. Outside the budget, these records are bounded only by verify's own run limits
(the per-user rate limit and single-flight that follow in the stack).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from candleviewer.api.audit_budget import WRITE_TIMEOUT_S
from candleviewer.audit.models import AuditOutcome, Severity, VerifyResult

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
