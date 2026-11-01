"""The halt after a verified audit-chain break (#2904; `04-security-program.md` §8.1 "Enforced
posture", which owns the rules: this module enforces them and restates none).

`AuditBreakHalt` is the process-wide flag: synchronous, O(1), no I/O, a `threading.Lock` (the
order lane reads it from its own thread). The composition root folds it into the B18 kill switch
port (`oms_wiring.HaltingKillSwitch`), so while it is engaged every position-opening order is
`403 trading_disabled` and every protective write passes as it does under the kill switch (C-2.6,
C-2.21). It is engaged while any break it holds is unacknowledged, or while the chain has not
been read (fail closed: from construction on the real backend until the first read, and again
after any read that fails).

A break is named by `BreakIdentity` (`first_bad_id`, `kind`), from the `VerifyResult` that found
it. `AuditBreakHaltService.trip` engages the halt synchronously, before any await, so a submit
made while its record is being written is already refused; `record_trip` then writes the
`audit.chain_break_halted` record (system actor). The halt's state is rebuilt from the chain:
`read_halt_view` reads every `audit.chain_break_halted` and `audit.chain_break_acknowledged`
record, and an identity whose latest record is a halt is engaged. Each process reads it once at
boot, before traffic (`start()`), then every `REFRESH_INTERVAL_S`, so an acknowledgement written
by any process, or the host console, clears every process within that interval. An acknowledged
identity never trips again; a different identity does, a later break past an acknowledged one
included: the verifier names only the first break, so the scheduled run resumes its walk past an
acknowledged one (`acknowledges`, `ChainVerifyRunner`). A trip whose record could not be written
stays engaged here and its record is written again at each read until the chain holds it.

`acknowledge_break` is the one acknowledgement path (the host console now, the Owner's route in
PR 2): Owner only, against a named engaged break, written ahead; a refusal is recorded as
`audit.chain_break_ack_denied`.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
import uuid
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol

import structlog

from candleviewer.audit.cursor import AuditCursor
from candleviewer.audit.models import AuditOutcome, AuditPage, Severity, VerifyResult
from candleviewer.observability.audit_query_metrics import cv_audit_break_halt_state
from candleviewer.observability.context import spawn

HALTED: Final = "audit.chain_break_halted"
ACKNOWLEDGED: Final = "audit.chain_break_acknowledged"
ACK_DENIED: Final = "audit.chain_break_ack_denied"
#: Every halt record's and acknowledgement's `object_kind`; `object_id` is the break's identity.
OBJECT_KIND: Final = "audit_chain_break"
#: The halt record's actor: the verifier that found the break.
SYSTEM_ACTOR: Final = "system:cv-audit-verify"
#: How often each process re-reads the chain's halt records (ruling BQ-248: at most 5 s).
REFRESH_INTERVAL_S: Final = 5.0
#: Bound on one read of the halt records, and on one record write.
READ_TIMEOUT_S: Final = 4.0
WRITE_TIMEOUT_S: Final = 2.0
#: The gateway's `kill_switch.reason` (23 §15.9: a free string, the Owner's view only) for each
#: cause: an unacknowledged break, or a chain not read yet or whose last read failed (fail closed).
HALT_REASON_BREAK: Final = "audit_chain_break"
HALT_REASON_UNREAD: Final = "audit_halt_unread"
_PAGE: Final = 500
#: More halt and acknowledgement records than this many pages is no state this module can hold:
#: the read fails, so the halt engages (fail closed).
_MAX_PAGES: Final = 20


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True, order=True)
class BreakIdentity:
    """A break as the verifier reported it (ruling BQ-246): its first divergent entry and how
    it diverges. Its `object_id` is the records' `object_id`."""

    first_bad_id: int
    kind: str

    @classmethod
    def of(cls, result: VerifyResult) -> BreakIdentity:
        """A break's identity; a break with no id or kind (none is reported so) is `0:unknown`,
        still a break."""
        kind = "unknown" if result.kind is None else result.kind.value
        return cls(0 if result.first_bad_id is None else result.first_bad_id, kind)

    @classmethod
    def parse(cls, text: str | None) -> BreakIdentity | None:
        head, sep, kind = (text or "").partition(":")
        if not sep or not head.isdigit() or not kind:
            return None
        return cls(int(head), kind)

    @property
    def object_id(self) -> str:
        return f"{self.first_bad_id}:{self.kind}"


@dataclass(frozen=True, slots=True)
class ChainHaltView:
    """What the chain records: the identities whose latest record is a halt (`halted`), and
    those whose latest is an acknowledgement (`acknowledged`)."""

    halted: frozenset[BreakIdentity] = frozenset()
    acknowledged: frozenset[BreakIdentity] = frozenset()


class HaltViewTooLarge(RuntimeError):
    """More halt records than `_MAX_PAGES` pages: the read fails, and the halt engages."""


class HaltRecordQuery(Protocol):
    """The member of `AuditQueryService` the read uses."""

    async def query(
        self,
        *,
        restrict_to_actor: str | None,
        actions: list[str] | None = None,
        outcome: str | None = None,
        after: AuditCursor | None = None,
        limit: int = 100,
    ) -> AuditPage: ...


async def read_halt_view(query: HaltRecordQuery) -> ChainHaltView:
    """Every successful halt and acknowledgement record, newest first, folded per identity by
    its latest record (by id). Raises what the read raises, or `HaltViewTooLarge`."""
    latest: dict[BreakIdentity, tuple[int, str]] = {}
    after: AuditCursor | None = None
    for _ in range(_MAX_PAGES):
        page = await query.query(
            restrict_to_actor=None,
            actions=[HALTED, ACKNOWLEDGED],
            outcome=AuditOutcome.SUCCESS.value,
            after=after,
            limit=_PAGE,
        )
        for entry in page.items:
            identity = BreakIdentity.parse(entry.subject_id)
            if identity is None:
                _log().error("audit.break_halt.unnamed_record", entry_id=entry.id)
                continue
            if identity not in latest or entry.id > latest[identity][0]:
                latest[identity] = (entry.id, entry.action)
        if not page.meta.has_more or not page.items:
            halted = frozenset(i for i, (_, action) in latest.items() if action == HALTED)
            return ChainHaltView(halted, frozenset(latest) - halted)
        last = page.items[-1]
        after = AuditCursor(last.ts, last.id)
    raise HaltViewTooLarge


class AuditBreakHalt:
    """The flag. `unread` is True on the real backend, where nothing may trade before the chain
    has been read; the fake backend, which runs no verifier, starts it False."""

    def __init__(self, *, unread: bool) -> None:
        self._lock = threading.Lock()
        self._unread = unread
        self._chain: frozenset[BreakIdentity] = frozenset()
        self._acknowledged: frozenset[BreakIdentity] = frozenset()
        #: This process's own trips, each with whether its record is known written.
        self._local: dict[BreakIdentity, bool] = {}
        self._publish()

    @property
    def engaged(self) -> bool:
        with self._lock:
            return self._engaged()

    @property
    def unread(self) -> bool:
        with self._lock:
            return self._unread

    @property
    def reason(self) -> str | None:
        """Why it is engaged: a break names it over an unread chain; None when clear."""
        with self._lock:
            if self._breaks():
                return HALT_REASON_BREAK
            return HALT_REASON_UNREAD if self._unread else None

    @property
    def breaks(self) -> tuple[BreakIdentity, ...]:
        """The unacknowledged breaks, lowest id first."""
        with self._lock:
            return tuple(sorted(self._breaks()))

    def trip(self, identity: BreakIdentity) -> bool:
        """Engage on `identity` unless it is acknowledged or already held. True when this call
        engaged it (its record is then owed)."""
        with self._lock:
            if identity in self._acknowledged or identity in self._breaks():
                return False
            self._local[identity] = False
        self._publish()
        _log().critical(
            "audit.break_halt.engaged", first_bad_id=identity.first_bad_id, kind=identity.kind
        )
        return True

    def is_acknowledged(self, identity: BreakIdentity) -> bool:
        with self._lock:
            return identity in self._acknowledged

    def recorded(self, identity: BreakIdentity) -> None:
        with self._lock:
            if identity in self._local:
                self._local[identity] = True

    def owed(self) -> tuple[BreakIdentity, ...]:
        """This process's trips whose record the chain does not hold yet."""
        with self._lock:
            return tuple(i for i, done in self._local.items() if not done and i not in self._chain)

    def apply(self, view: ChainHaltView) -> None:
        """A successful read: the chain's state replaces the last read's; a trip of this
        process stays until the chain acknowledges it."""
        with self._lock:
            self._unread = False
            self._chain, self._acknowledged = view.halted, view.acknowledged
            for identity in view.acknowledged:
                self._local.pop(identity, None)
            for identity in view.halted:  # held by the chain now
                if identity in self._local:
                    self._local[identity] = True
        self._publish()

    def read_failed(self) -> None:
        """A read that failed: engaged until a read succeeds (fail closed)."""
        with self._lock:
            self._unread = True
        self._publish()

    def acknowledged(self, identity: BreakIdentity) -> None:
        """This process wrote the acknowledgement of `identity`: cleared here at once."""
        with self._lock:
            self._acknowledged |= {identity}
            self._chain -= {identity}
            self._local.pop(identity, None)
        self._publish()

    def _breaks(self) -> frozenset[BreakIdentity]:
        return (self._chain | frozenset(self._local)) - self._acknowledged

    def _engaged(self) -> bool:
        return self._unread or bool(self._breaks())

    def _publish(self) -> None:
        cv_audit_break_halt_state.set(1 if self.engaged else 0)


class HaltAudit(Protocol):
    """What the service needs of the audit module (`AuditService`); each raises `RuntimeError`
    until the module is up."""

    @property
    def query(self) -> HaltRecordQuery: ...

    @property
    def writer(self) -> Any: ...


async def _never(reason: str | None) -> None:
    del reason


class AuditBreakHaltService:
    """The halt's writer and reader in this process: trips, records, re-reads and publishes.
    `on_change` is awaited with the halt's `reason` once per change of it (the gateway's
    `system` frame; None is clear), best effort; `sleep` paces the re-reads (a test's never
    sleeps)."""

    def __init__(
        self,
        halt: AuditBreakHalt,
        audit: HaltAudit,
        *,
        on_change: Callable[[str | None], Awaitable[None]] = _never,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        interval_s: float = REFRESH_INTERVAL_S,
    ) -> None:
        self.halt, self._audit = halt, audit
        self._on_change, self._sleep, self._interval_s = on_change, sleep, interval_s
        #: What was last published: the gateway's view starts clear, as the halt does but on
        #: the real backend, whose boot read publishes only a halt it finds.
        self._shown: str | None = None
        self._task: asyncio.Task[None] | None = None

    def trip(self, result: VerifyResult) -> BreakIdentity | None:
        """Synchronous, before any await (C-2.21): a break engages the halt at once. The
        identity whose record is owed, or None (verified, acknowledged or already held)."""
        if result.verified:
            return None
        identity = BreakIdentity.of(result)
        return identity if self.halt.trip(identity) else None

    def acknowledges(self, result: VerifyResult) -> bool:
        """The break `result` names is one the Owner acknowledged: a scheduled run then looks
        past it for a later one (`ChainVerifyRunner`), which an acknowledgement never covers."""
        return not result.verified and self.halt.is_acknowledged(BreakIdentity.of(result))

    async def record_trip(
        self, identity: BreakIdentity, result: VerifyResult, *, trigger: str
    ) -> bool:
        """The `audit.chain_break_halted` record of a trip, then the change published. False
        when it could not be written: the halt stays, and the next read writes it again."""
        after = {"trigger": trigger, "from_id": result.from_id, "to_id": result.to_id}
        written = await self._write_halt(identity, after)
        await self._publish()
        return written

    async def refresh(self) -> None:
        """One read of the chain: applied, or the halt engaged when it fails. Owed records are
        written again, and a change is published. Never raises but on cancellation."""
        try:
            async with asyncio.timeout(READ_TIMEOUT_S):
                view = await read_halt_view(self._audit.query)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # unread, refused, timed out: fail closed
            _log().error("audit.break_halt.read_failed", error=type(exc).__name__)
            self.halt.read_failed()
        else:
            self.halt.apply(view)
            for identity in self.halt.owed():
                await self._write_halt(identity, {"trigger": "rewrite"})
        await self._publish()

    async def start(self) -> None:
        """Before traffic: one read (engaged on failure), then the re-reads start."""
        await self.refresh()
        if self._task is None:
            self._task = spawn(self._run(), name="audit-break-halt")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _run(self) -> None:
        while True:
            await self._sleep(self._interval_s)
            await self.refresh()

    async def _write_halt(self, identity: BreakIdentity, after: dict[str, Any]) -> bool:
        state = {"first_bad_id": identity.first_bad_id, "kind": identity.kind, **after}
        try:
            async with asyncio.timeout(WRITE_TIMEOUT_S):
                await self._audit.writer.emit(
                    HALTED,
                    actor_label=SYSTEM_ACTOR,
                    object_kind=OBJECT_KIND,
                    object_id=identity.object_id,
                    outcome=AuditOutcome.SUCCESS,
                    severity=Severity.CRITICAL,
                    reason="order_entry_halted",
                    after_state=state,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # the halt stands; the next read writes it again
            _log().error("audit.break_halt.record_failed", error=type(exc).__name__)
            return False
        self.halt.recorded(identity)
        return True

    async def _publish(self) -> None:
        reason = self.halt.reason
        if reason == self._shown:
            return
        self._shown = reason
        try:
            await self._on_change(reason)
        except Exception as exc:  # display only: the flag already enforces
            _log().warning("audit.break_halt.publish_failed", error=type(exc).__name__)


class AckOutcome(StrEnum):
    ACKNOWLEDGED = "acknowledged"
    NOT_OWNER = "not_owner"
    NOT_ENGAGED = "not_engaged"
    RECORD_FAILED = "record_failed"


@dataclass(frozen=True, slots=True)
class AckRequest:
    """An acknowledgement: the named break, the typed reason and who asks."""

    identity: BreakIdentity
    reason: str
    actor_user_id: uuid.UUID | None
    actor_label: str
    session_id: uuid.UUID | None = None
    actor_ip: str | None = None
    request_id: uuid.UUID | None = None


async def acknowledge_break(
    request: AckRequest,
    *,
    is_owner: bool,
    engaged: Iterable[BreakIdentity],
    emit: Callable[..., Awaitable[None]],
) -> AckOutcome:
    """Owner only, against a break in `engaged`; the acknowledgement is written ahead of any
    effect, so `ACKNOWLEDGED` means the record is written, and the caller then clears its own
    halt (`AuditBreakHalt.acknowledged`). A refusal writes `audit.chain_break_ack_denied`,
    best effort; a failed acknowledgement record is `RECORD_FAILED` and changes nothing."""
    identity = request.identity
    fields: dict[str, Any] = {
        "actor_label": request.actor_label,
        "actor_user_id": request.actor_user_id,
        "session_id": request.session_id,
        "actor_ip": request.actor_ip,
        "request_id": request.request_id,
        "object_kind": OBJECT_KIND,
        "object_id": identity.object_id,
    }
    state = {"first_bad_id": identity.first_bad_id, "kind": identity.kind}
    refusal = None
    if not is_owner:
        refusal = AckOutcome.NOT_OWNER
    elif identity not in frozenset(engaged):
        refusal = AckOutcome.NOT_ENGAGED
    if refusal is not None:
        await _try_emit(
            emit,
            ACK_DENIED,
            fields,
            outcome=AuditOutcome.DENIED,
            severity=Severity.WARNING,
            reason=refusal.value,
            after_state=state,
        )
        return refusal
    written = await _try_emit(
        emit,
        ACKNOWLEDGED,
        fields,
        outcome=AuditOutcome.SUCCESS,
        severity=Severity.CRITICAL,
        reason=request.reason,
        after_state=state | {"reason": request.reason},
    )
    if not written:
        return AckOutcome.RECORD_FAILED
    _log().critical(
        "audit.break_halt.acknowledged", first_bad_id=identity.first_bad_id, kind=identity.kind
    )
    return AckOutcome.ACKNOWLEDGED


async def _try_emit(
    emit: Callable[..., Awaitable[None]], action: str, fields: dict[str, Any], **record: Any
) -> bool:
    try:
        async with asyncio.timeout(WRITE_TIMEOUT_S):
            await emit(action, **fields, **record)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _log().error("audit.break_halt.ack_record_failed", action=action, error=type(exc).__name__)
        return False
    return True
