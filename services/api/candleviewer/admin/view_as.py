"""`ViewAsService`: a view-as context's evaluation, its one end, the viewer's leave and its clear
(#3085).

`22-api-openapi.yaml` "View-as session" and `endViewAs`; the state, its phase and the store
contract are `auth/view_as.py`'s. The sweeper (`admin/view_as_sweeper.py`) runs it from the
lifespan; nothing starts a context until the HTTP routes land (Q13), and the socket closer is a
no-op until the WebSocket side is wired.

A context ends exactly once: of concurrent ends only the call whose conditional write
(`end_view_as`, or `leave_view_as`, which also clears it) ended it closes the session's sockets
and writes `admin.view_as_ended`. That record is never waited on: the app's refusal-audit tracker
runs it, and one that fails, outlasts its bound or finds the tracker full leaves the end pending
on the row until the sweeper writes it late (`recorded_late`). It is keyed by its context id
(`AuditWriter.emit_keyed`), so writing it again, after a crash too, stores no second row. Its
actor is the viewer and the viewer's session; the target is only its object (Q2), and no state
dict holds a session id (the redactor masks one).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Collection, Coroutine, Mapping
from datetime import datetime, timedelta
from functools import partial
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.admin.audited import audit_exempt, audited
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.view_as import (
    ViewAsBinding,
    ViewAsEndReason,
    ViewAsPhase,
    ViewAsSessionStore,
)
from candleviewer.observability.context import current_request_uuid

_ENDED_ACTION: Final = "admin.view_as_ended"
RECORD_TIMEOUT_S: Final = 2.0  # bounds a record's read, write and mark; past it the end is pending
CLOSE_TIMEOUT_S: Final = 2.0  # bounds the socket close; the record follows whatever it did

#: The reasons the eligibility port ends a live context with.
Ineligible = Literal[ViewAsEndReason.VIEWER_INELIGIBLE, ViewAsEndReason.TARGET_INELIGIBLE]
#: 23 section 9.6: `bye` `view_as_changed` (4401) when the viewer ends the context,
#: `view_as_expired` (4403) when the server does.
CloseReason = Literal["view_as_changed", "view_as_expired"]


class ViewAsAudit(Protocol):  # `AuditWriter.emit_keyed` (Q3), with `emit()`'s keywords
    async def emit_keyed(
        self,
        action: str,
        name: str,
        *,
        actor_label: str,
        actor_user_id: UUID,
        session_id: UUID,
        object_kind: str,
        object_id: str,
        object_label: str | None,
        outcome: AuditOutcome,
        severity: Severity,
        reason: str,
        before_state: dict[str, Any],
        after_state: dict[str, Any],
        request_id: UUID | None,
    ) -> None: ...


class EndRecordRunner(Protocol):  # `api.csrf.RefusalAuditTracker`, which admin may not import
    @property
    def full(self) -> bool: ...  # its cap of writes in flight is reached

    def track(
        self, coro: Coroutine[Any, Any, None], *, on_lost: Callable[[], None] | None = None
    ) -> object: ...  # `on_lost`: its shutdown drain left the write running


class ViewAsEligibility(Protocol):  # a read it cannot make raises: 503, never a scope
    async def ineligible(self, viewer: SessionRecord, target_user_id: UUID) -> Ineligible | None:
        """`viewer_ineligible` once the viewer's session lacks `users:write`; `target_ineligible`
        once the target is gone, disabled or an Owner (`PrincipalSnapshot.is_owner`; a role it
        cannot read fails closed); `None` while both hold."""
        ...


class ViewAsSocketCloser(Protocol):  # every socket of the session's rotation family
    async def close_family(self, session_id: str, *, reason: CloseReason) -> None: ...


class ViewAsLabels(Protocol):  # a user whose row is gone is absent
    async def usernames(self, user_ids: Collection[UUID]) -> Mapping[UUID, str]: ...


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _pending(context_id: UUID, error: str, *, late: bool = False) -> None:
    """The end's record is not written: the end stays pending on the row, for the sweeper."""
    _log().warning(
        "admin.view_as_ended.record_pending", context_id=str(context_id), late=late, error=error
    )


class ViewAsService:
    def __init__(
        self,
        store: ViewAsSessionStore,
        audit: ViewAsAudit,
        *,
        runner: EndRecordRunner,
        eligibility: ViewAsEligibility,
        sockets: ViewAsSocketCloser,
        labels: ViewAsLabels,
        clock: Callable[[], datetime],  # the auth clock: it stamps `end_recorded_at`
        record_timeout_s: float = RECORD_TIMEOUT_S,
        close_timeout_s: float = CLOSE_TIMEOUT_S,
    ) -> None:
        self._store, self._audit, self._runner = store, audit, runner
        self._eligibility, self._sockets, self._labels = eligibility, sockets, labels
        self._clock = clock
        self._record_timeout_s, self._close_timeout_s = record_timeout_s, close_timeout_s

    @audited("admin.view_as_ended")
    async def evaluate(self, record: SessionRecord, *, now: datetime) -> ViewAsBinding | None:
        """What a request or a socket of `record`'s session is bound to at `now`, the auth clock:
        `None` with no context or on a revoked row; held once it ended or expired (an expiry is
        read here, never written: the sweeper writes it); else live while its viewer and its
        target stay eligible. One that is not ends here with that reason and answers held. A
        failed read raises. A revoked row is never ended here: a revoked session grants nothing,
        and a rotated row keeps a copy of the context its successor carries, so an end here would
        spend the context's one record while the successor is live. The sweeper ends a
        revoked session's context, through `end`. A caller holding a binding that now reads
        `None` (a revoked row: a rotated predecessor, say) never widens its scope on it: it keeps
        the binding until re-auth, or closes `view_as_changed`; `None` never means the viewer's
        scope."""
        state = None if record.is_revoked else record.view_as
        binding = None if state is None else state.binding(now=now)
        if state is None or binding is None or binding.phase is ViewAsPhase.HELD:
            return binding
        reason = await self._eligibility.ineligible(record, state.target_user_id)
        if reason is None:
            return binding
        await self.end(record, reason=reason, now=now)  # lost to another end: held all the same
        return binding.model_copy(update={"phase": ViewAsPhase.HELD})

    @audited("admin.view_as_ended")
    async def end(self, record: SessionRecord, *, reason: ViewAsEndReason, now: datetime) -> bool:
        """End `record`'s context at `now`, or at `expires_at` as `expired` once that has passed,
        whatever `reason` asked. True iff this call's conditional write applied: only then are the
        session's sockets closed and `admin.view_as_ended` written, never waited on. False with no
        context or one already ended: no close, no record. A store failure raises, with no end.
        A revoked row's context ends too: the sweeper ends an orphaned or revoked session's
        from the store's due list, which already leaves out a copy another row carries."""
        state = record.view_as
        if state is None or state.ended_at is not None:
            return False
        ended_at, applied = state.end_at(now=now, reason=reason)
        ended = await self._store.end_view_as(
            str(record.id), state.context_id, ended_at=ended_at, reason=applied
        )
        if ended is None:
            return False
        by_viewer = applied is ViewAsEndReason.ENDED
        why: CloseReason = "view_as_changed" if by_viewer else "view_as_expired"
        await self._ended(ended, state.context_id, why)
        return True

    @audited("admin.view_as_ended")
    async def leave(self, record: SessionRecord, *, now: datetime) -> SessionRecord | None:
        """The viewer's `DELETE /auth/session/view-as`: one conditional write ends the context if it
        has not ended (`ended`, or `expired` at `expires_at` once that passed) and clears it, so a
        store failure raises with nothing changed. The row, or `None` when nothing applied (no
        context, or a cleared one). Only when this call ended it are the session's sockets closed,
        `view_as_changed` (the session is back in the viewer's scope), and `admin.view_as_ended`
        written, never waited on; leaving a held context keeps its end, pending or not."""
        state = record.view_as
        if state is None or state.cleared_at is not None:
            return None
        if state.ended_at is not None and state.end_reason is not None:
            ended_at, reason = state.ended_at, state.end_reason  # held: the store keeps its end
        else:
            ended_at, reason = state.end_at(now=now, reason=ViewAsEndReason.ENDED)
        left = await self._store.leave_view_as(
            str(record.id), state.context_id, ended_at=ended_at, reason=reason, now=now
        )
        if left is None:
            return None
        row, ended_here = left
        if ended_here:
            await self._ended(row, state.context_id, "view_as_changed")
        return row

    @audited("admin.view_as_ended")
    async def write_end_record(self, record: SessionRecord, *, late: bool) -> bool:
        """Write the `admin.view_as_ended` of `record`'s ended context, keyed by the context, with
        `recorded_late` only when `late` (the sweeper's path), then mark it recorded. True once
        written; False, logged, when a read or the write failed or outlasted the bound, and the
        end stays pending. It never raises for the record; an unended context is a caller error."""
        state = record.view_as
        if state is None or state.ended_at is None or state.end_reason is None:
            raise ValueError("only an ended view-as context has an end record")
        after: dict[str, Any] = {"ended_at": state.ended_at.isoformat()}
        try:
            async with asyncio.timeout(self._record_timeout_s):
                names = await self._labels.usernames((record.user_id, state.target_user_id))
                await self._audit.emit_keyed(
                    _ENDED_ACTION,
                    str(state.context_id),  # its key: one record per context
                    actor_label=names.get(record.user_id) or str(record.user_id),
                    actor_user_id=record.user_id,
                    session_id=record.id,
                    object_kind="user",
                    object_id=str(state.target_user_id),
                    object_label=names.get(state.target_user_id),
                    outcome=AuditOutcome.SUCCESS,
                    severity=Severity.WARNING,
                    reason=state.end_reason.value,
                    before_state={
                        "target_user_id": str(state.target_user_id),
                        "started_at": state.started_at.isoformat(),
                        "expires_at": state.expires_at.isoformat(),
                    },
                    after_state=(after | {"recorded_late": True}) if late else after,
                    request_id=current_request_uuid(),  # the ending request; none from the sweeper
                )
                await self._store.mark_view_as_recorded(
                    str(record.id), state.context_id, now=self._clock()
                )
        except Exception as exc:  # a timeout too: a later write of the keyed record adds no row
            _pending(state.context_id, type(exc).__name__, late=late)
            return False
        return True

    @property
    @audit_exempt("read")
    def end_record_bound(self) -> timedelta:
        """How long after an end's write its own record may still land: the bounded socket close,
        then the bounded record. A late write before then could race it (`recorded_late`)."""
        return timedelta(seconds=self._close_timeout_s + self._record_timeout_s)

    @audit_exempt("contract_unrecorded")
    async def clear(self, record: SessionRecord, *, now: datetime) -> SessionRecord | None:
        """Let go of `record`'s held context, one that has ended: the row, or `None` when nothing
        applied (no context, a live one, or one already cleared). A pending end stays until its
        record is written. A clear has no record of its own (22 `endViewAs`): the end that it
        follows wrote `admin.view_as_ended`, or the sweeper will."""
        state = record.view_as
        if state is None:
            return None
        return await self._store.clear_view_as(str(record.id), state.context_id, now=now)

    async def _ended(self, row: SessionRecord, context_id: UUID, why: CloseReason) -> None:
        """This call's write ended the context: close the session's sockets, bounded, then hand
        over the record. A failed close is logged by its context, never raised: the end stands."""
        try:
            async with asyncio.timeout(self._close_timeout_s):
                await self._sockets.close_family(str(row.id), reason=why)
        except Exception as exc:  # a timeout too
            _log().error(
                "admin.view_as.close_failed",
                context_id=str(context_id),
                reason=why,
                error=type(exc).__name__,
            )
        finally:  # a caller cancelled during the close still leaves the record to the tracker
            self._record_soon(row, context_id)

    def _record_soon(self, ended: SessionRecord, context_id: UUID) -> None:
        """Hand the end's record to the tracker; at its cap the end stays pending."""
        if self._runner.full:
            _pending(context_id, "tracker_full")
            return
        self._runner.track(
            self._record(ended), on_lost=partial(_pending, context_id, "lost_at_shutdown")
        )

    async def _record(self, ended: SessionRecord) -> None:
        await self.write_end_record(ended, late=False)
