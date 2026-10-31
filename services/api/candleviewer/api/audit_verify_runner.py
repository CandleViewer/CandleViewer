"""The scheduled audit chain verify run (#2966, for #2111): the real `VerifyRunner` that the
start-up and nightly job (`audit/verify_job.py`) calls once per run, under the verify slot. The
port (`audit/verify_runner.py`) owns the outcome rules; this module meets them. It sits next to
the on-demand route (`api/audit.py`) and shares its helpers (`api/audit_verify.py`), so a scheduled
run and an operator's run are recorded, counted and reported alike.

One run, in order:
1. The write-ahead `admin.audit_verify` `started` record (#2461). A run whose `started` record
   cannot be written never walks.
2. The whole chain, genesis to the head, by `AuditQueryService.run_verify`, the on-demand route's
   verifier, with its bounds (#2464: batch size, per-entry cap, the hasher's bounded queue) and
   no span cap, under the request's `deadline_s`.
3. Its end. A break (`mismatch`) sets the chain gauge to 0, counts in
   `audit_chain_verification_failures_total` and raises the critical `audit_chain_break` system
   event (#2462, #2468), none of which waits for its result record; before any of them it halts
   order entry (#2904, `BreakHalt.trip`), whose record follows the event. A break the Owner has
   acknowledged trips nothing, so the walk resumes past it, to the head, and the first break past
   it that is not acknowledged trips the halt (the verifier names only the first break: without
   this an acknowledged break would hide every later one). A pass sets the gauge to 1
   once its result record is written. Anything else is `stopped`: its stop record carries the
   reason, and a stop turns a gauge of 1 into NaN (a known break, 0, stays).

`cv_audit_verify_runs_total` and `cv_audit_verify_last_ok_timestamp_seconds` are the job's: it
counts each run end once, so this module never touches them.

Records carry the job's `system:` actor label and no user, session or IP. A run cancelled while
it walks (the job's backstop, a shutdown) re-raises, leaves only its `started` record and
turns a gauge of 1 into NaN. The audit module is resolved per run: its writer and query service
exist only once its `start()` has wired the real backend.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Final, Protocol

import structlog

from candleviewer.api.audit import AuditServiceLike
from candleviewer.api.audit_verify import (
    VERIFY_STOP_ERRORS,
    BreakHalt,
    observe_stop,
    observe_verify,
    raise_break_event,
    record_halt,
    result_record,
    verify_stop,
    write_verify_record,
)
from candleviewer.audit.models import AuditOutcome, Severity, VerifyResult
from candleviewer.audit.query import VerifyRangeBeyondHead
from candleviewer.audit.verify_runner import (
    VerifyOutcome,
    VerifyOutcomeKind,
    VerifyRunRequest,
    VerifyStopReason,
)
from candleviewer.observability.health_probes import SystemEventWriter
from candleviewer.storage.errors import AuditEntryTooLarge

#: `plan_verify` defaults to the newest `max_span` entries, clipped to the first one. With the
#: largest id an entry can have it always starts at the first entry: the whole chain.
_WHOLE_CHAIN_SPAN: Final = 2**63 - 1
_SUCCESS, _FAILURE = AuditOutcome.SUCCESS, AuditOutcome.FAILURE
#: Bound on the walks one run resumes past acknowledged breaks (#2904); each must move past
#: the last, so a chain with more acknowledged breaks than this is logged and looked at no further.
_MAX_RESUMES: Final = 64
_INFO, _WARNING = Severity.INFO, Severity.WARNING

__all__ = ["ChainVerifyRunner"]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ResumingBreakHalt(BreakHalt, Protocol):
    """The halt as the scheduled run uses it: also whether a break is one the Owner acknowledged
    (`AuditBreakHaltService.acknowledges`)."""

    def acknowledges(self, result: VerifyResult) -> bool: ...


@dataclass(frozen=True, slots=True)
class _Records:
    """The `admin.audit_verify` records of one run: one actor, one trigger."""

    emit: Callable[..., Awaitable[None]]
    request: VerifyRunRequest

    async def write(
        self,
        outcome: AuditOutcome,
        severity: Severity,
        reason: str,
        after_state: dict[str, Any] | None = None,
    ) -> bool:
        """False when the writer refused the record or did not take it in time (logged)."""
        fields = {"actor_label": self.request.actor, "object_kind": "audit_log"}
        state = {"trigger": self.request.trigger.value, **(after_state or {})}
        return await write_verify_record(
            self.emit, fields, outcome=outcome, severity=severity, reason=reason, after_state=state
        )


class ChainVerifyRunner:
    """`VerifyRunner` over the audit module (`AuditService`). `events` is the system event
    writer for a break, or `None` where none is wired: the record and the series do not
    depend on it; `halt`, the audit-chain break halt (#2904), likewise."""

    def __init__(
        self,
        audit: AuditServiceLike,
        events: SystemEventWriter | None = None,
        *,
        clock: Callable[[], datetime] = _utcnow,
        halt: ResumingBreakHalt | None = None,
    ) -> None:
        self._audit = audit
        self._events = events
        self._clock = clock
        self._halt = halt

    async def run(self, request: VerifyRunRequest) -> VerifyOutcome:
        started_at = self._clock()
        try:
            query, emit = self._audit.query, self._audit.writer.emit
        except RuntimeError:  # the audit module is not up: no record can be written
            observe_stop(full_chain=True)
            return self._stopped(started_at, VerifyStopReason.RECORD_FAILED)
        records = _Records(emit, request)
        try:
            if not await records.write(_SUCCESS, _INFO, "started"):
                observe_stop(full_chain=True)
                return self._stopped(started_at, VerifyStopReason.RECORD_FAILED)
            plan = await query.plan_verify(from_id=None, to_id=None, max_span=_WHOLE_CHAIN_SPAN)
            result: VerifyResult = await query.run_verify(plan, deadline_s=request.deadline_s)
        except asyncio.CancelledError:
            observe_stop(full_chain=True)  # it never ended: no old 1 stands for it
            raise
        except VERIFY_STOP_ERRORS as exc:
            if isinstance(exc, AuditEntryTooLarge):  # the entry's id and the class only
                _log().warning(
                    "audit.verify.entry_too_large", entry_id=exc.entry_id, error=type(exc).__name__
                )
            reason = verify_stop(exc)[0]
            kind = VerifyStopReason(reason.partition("@")[0])  # `entry_too_large@<id>`
            return await self._stop(started_at, records, reason, kind)
        except Exception as exc:  # anything else, e.g. MemoryError: never a pass
            _log().error("audit.verify.failed", error=type(exc).__name__)
            return await self._stop(
                started_at, records, "internal_error", VerifyStopReason.INTERNAL_ERROR
            )
        return await self._end(started_at, records, result, query)

    async def _end(
        self, started_at: datetime, records: _Records, result: VerifyResult, query: Any
    ) -> VerifyOutcome:
        if not result.verified:  # a break: its series and event do not wait for the record
            owed = None if self._halt is None else self._halt.trip(result)  # before any await
            observe_verify(result)
            trigger = records.request.trigger.value
            try:
                await records.write(*result_record(result))
            finally:
                await raise_break_event(self._events, result, None)
                await record_halt(self._halt, owed, result, trigger)
            if self._halt is not None and self._halt.acknowledges(result):
                later = await self._past_acknowledged(
                    self._halt, query, result, records.request.deadline_s
                )
                if later is not None:
                    owed = self._halt.trip(later)  # synchronous, as soon as it is found
                    await record_halt(self._halt, owed, later, trigger)
            return VerifyOutcome(
                outcome=VerifyOutcomeKind.MISMATCH,
                started_at=started_at,
                ended_at=self._clock(),
                entries_checked=result.entries_checked,
                first_bad_id=result.first_bad_id,
            )
        # An empty log has no `from_id`: a whole chain with nothing in it, so a pass too.
        if not (result.full_chain or result.from_id is None):  # a partial pass is no pass
            return await self._stop(
                started_at,
                records,
                "internal_error",
                VerifyStopReason.INTERNAL_ERROR,
                result.entries_checked,
            )
        if not await records.write(*result_record(result)):  # a pass the trail cannot show
            observe_stop(full_chain=True)
            return self._stopped(started_at, VerifyStopReason.RECORD_FAILED, result.entries_checked)
        observe_verify(result.model_copy(update={"full_chain": True}))
        return VerifyOutcome(
            outcome=VerifyOutcomeKind.OK,
            started_at=started_at,
            ended_at=self._clock(),
            entries_checked=result.entries_checked,
        )

    async def _past_acknowledged(
        self, halt: ResumingBreakHalt, query: Any, found: VerifyResult, deadline_s: float
    ) -> VerifyResult | None:
        """The first break past the acknowledged `found` that is not acknowledged itself (#2904),
        or None. Each walk resumes from the id after the last break (`VerifyPlan.resumed`: its
        anchor is that entry's stored hash) to the head, under the run's deadline; one that
        names no break later than the last, or stops, ends the search (logged, by class): as a
        stopped run, it never trips, and the next run looks again."""
        current: VerifyResult = found
        for _ in range(_MAX_RESUMES):
            last = current.first_bad_id
            if last is None:
                return None
            try:
                plan = await query.plan_verify(
                    from_id=last + 1, to_id=None, max_span=_WHOLE_CHAIN_SPAN
                )
                current = await query.run_verify(replace(plan, resumed=True), deadline_s=deadline_s)
            except VerifyRangeBeyondHead:  # the break was the head: nothing past it
                return None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _log().warning("audit.verify.resume_stopped", error=type(exc).__name__)
                return None
            if current.verified:
                return None
            if not halt.acknowledges(current):
                return current
            if current.first_bad_id is None or current.first_bad_id <= last:  # no way past it
                return None
        _log().error("audit.verify.resume_capped", resumes=_MAX_RESUMES)
        return None

    async def _stop(
        self,
        started_at: datetime,
        records: _Records,
        reason: str,
        kind: VerifyStopReason,
        checked: int = 0,
    ) -> VerifyOutcome:
        """A run that ended without a result: the gauge first, then its stop record."""
        observe_stop(full_chain=True)
        await records.write(_FAILURE, _WARNING, reason)
        return self._stopped(started_at, kind, checked)

    def _stopped(
        self, started_at: datetime, reason: VerifyStopReason, checked: int = 0
    ) -> VerifyOutcome:
        return VerifyOutcome(
            outcome=VerifyOutcomeKind.STOPPED,
            started_at=started_at,
            ended_at=self._clock(),
            entries_checked=checked,
            stop_reason=reason,
        )
