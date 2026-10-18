"""The journal-first audit lane's boot and drain (ADR-0037 decisions 7 and 8; #3009 slice S2a2).

`docs/plan/24-internal-schemas.md` §15.6 owns the scan, the hand-over, the rows and the
confirmation (C-16.5); this module runs them and restates none. A boot creates a new lane with
`audit.lane_started` and appends `audit.lane_resumed`. One drain task then hands each unit of the
boot's scan, and of the running scans after it, to `AuditWriter.ingest()` in order, and moves the
marker past a unit once the writer reports its token committed. No log line carries a record (U41).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections import deque
from collections.abc import Callable
from typing import Any

import structlog
from pydantic import ValidationError

from candleviewer.audit import lane_journal as lj
from candleviewer.audit import writer as aw
from candleviewer.audit.actions import UnknownAuditAction
from candleviewer.audit.models import AuditEmission, Severity
from candleviewer.observability.context import spawn

Unit = lj.Handover | lj.Run


class AuditLane:
    """The lane's journal, boot and one drain task; `confirmed` is the last marker's position. A
    failed `start()` leaves the journal unusable (a retry builds a new one); until S2a2b a boot
    that holds raises from it. The deques hold units after the marker, which the journal bounds."""

    def __init__(
        self,
        journal: lj.LaneJournal,
        writer: aw.AuditWriter,
        *,
        retry_s: tuple[float, float] = lj.RETRY_S,
        poll_s: float = lj.CONFIRM_POLL_S,
        batch: int = lj.DRAIN_BATCH,
        new_lane: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self.journal, self._writer, self._new_lane = journal, writer, new_lane
        self._retry, self._poll, self._batch = retry_s, poll_s, batch
        self.confirmed: lj.Pos | None = None
        self._lane: uuid.UUID | None = None  # the scan's; None while no frame or marker set one
        self._origin = lj.LaneMarker(uuid.UUID(int=0), (1, 0), 1, lj.ZERO_MAC, True)  # next scan's
        self._units: deque[Unit] = deque()  # scanned, not yet handed over
        self._pending: deque[tuple[lj.LaneMarker | None, int]] = deque()  # handed over, by token
        self._dirty, self._wake = False, asyncio.Event()  # an append since the last scan
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> lj.LaneScan:
        """Boot: the scan, `audit.lane_started` when frame 1 is due, `audit.lane_resumed` with the
        head its frame follows, then the drain, which hands the scan's units over first."""
        result = await self.journal.open(self._new_lane)
        journal, self._lane = self.journal, result.lane
        self._units.extend(result.units)
        new = lj.LaneMarker(journal.lane, (1, 0), 1, lj.ZERO_MAC, True)
        self._origin = journal.boot_marker or new
        if journal.fresh:
            await self.append(self._own("audit.lane_started", Severity.WARNING))
        (seq, mac), anchored = journal.head, result.state.anchored or result.lane is None
        head = {"head_seq": seq, "head_mac": mac, "anchored": anchored}  # a new lane is anchored
        await self.append(self._own("audit.lane_resumed", Severity.INFO, head))
        self._task = spawn(self._drain(), name="audit-lane-drain")
        self._task.add_done_callback(_log_death)
        return result

    async def append(self, record: AuditEmission) -> int:
        """Journal a record that `build()` made; its `seq` once durable. Refusals propagate."""
        seq = await self.journal.append(json.loads(record.model_dump_json()))
        self._dirty = True
        self._wake.set()
        return seq

    async def close(self) -> None:
        """Stop the drain, then close the journal; what is not confirmed drains at the next boot."""
        if self._task is not None:
            self._task.cancel()
            await asyncio.wait({self._task})
        await self.journal.close()

    def _own(
        self, action: str, level: Severity, after: dict[str, Any] | None = None
    ) -> AuditEmission:
        lane, kind = str(self.journal.lane), "audit_lane"
        return self._writer.build(
            action, actor_label=aw.LANE_ACTOR, object_kind=kind, object_id=lane, severity=level,
            after_state=after,
        )  # fmt: skip

    async def _drain(self) -> None:
        """Ingest: batches in order, a confirmation attempt after each; a running scan once the
        units run out and an append came; backoff after a refusal, which an append cuts short."""
        delay = self._retry[0]
        while True:
            if not self._units and self._dirty:
                self._dirty = False
                result = await self.journal.rescan(self._origin)
                self._lane = result.lane
                self._units.extend(result.units)
            refused = await self._hand_over_batch()
            await self._confirm()
            if refused:
                await self._pause(delay)
                delay = min(2 * delay, self._retry[1])
                continue
            delay = self._retry[0]
            if not (self._units or self._dirty):
                await self._pause(self._poll if self._pending else None)

    async def _hand_over_batch(self) -> bool:
        """Up to `batch` units in order; True when a transient refusal ended it (Ingest step 2)."""
        for _ in range(min(self._batch, len(self._units))):
            unit = self._units[0]
            try:
                token = await self._hand_over(unit)
            except (aw.AuditUnavailable, aw.AuditWriterStopped):
                return True
            self._units.popleft()
            marker = self._marker(unit)
            self._pending.append((marker, token))
            self._origin = marker or self._origin
        return False

    async def _hand_over(self, unit: Unit) -> int:
        """A unit's commit token: a frame's record, or a run's row once its bytes are in
        `quarantine/`; a record that `ingest()` refuses for good gets its `record_invalid` row."""
        if isinstance(unit, lj.Handover):
            try:
                return await self._writer.ingest(unit.frame.rec)
            except (UnknownAuditAction, ValidationError):
                unit = lj.record_invalid(unit)
        await self.journal.quarantine(unit)
        token = await self._writer.ingest(self._row(unit))
        _log().warning("audit.lane.anomaly", reason=unit.reason, seqs=(unit.from_seq, unit.to_seq))
        return token

    def _row(self, run: lj.Run) -> AuditEmission:
        """Ingest step 1: the run's `audit.lane_anomaly` row, under its keyed `record_id`."""
        after = {
            "from_seq": run.from_seq, "to_seq": run.to_seq, "bytes": len(run.data),
            "digest": run.digest, "quarantined": run.quarantined,
            "prev_unverified": run.prev_unverified, "marker_behind": run.marker_behind,
            "marker_ahead": run.marker_ahead,
        }  # fmt: skip
        level = Severity.WARNING if run.reason == "torn_tail" else Severity.CRITICAL
        record_id = self.journal.run_id(self._lane, run)
        return aw._lane_anomaly(
            self._writer, record_id, reason=run.reason, severity=level, lane=self._lane,
            after_state=after,
        )  # fmt: skip

    def _marker(self, unit: Unit) -> lj.LaneMarker | None:
        """The marker once `unit` is committed; None while no frame has set the lane (row 3)."""
        s = unit.state
        if s.next_seq is None:
            return None
        return lj.LaneMarker(self.journal.lane, unit.end, s.next_seq, s.prev, s.anchored)

    async def _confirm(self) -> None:
        """Ingest step 3: the marker passes the last unit with a committed token, then compacts."""
        through, marker = self._writer.committed_through(), None
        while self._pending and self._pending[0][1] <= through:
            marker = self._pending.popleft()[0] or marker
        if marker is not None:
            await self.journal.confirm(marker)
            self.confirmed = marker.pos
            await self.journal.compact()

    async def _pause(self, delay: float | None) -> None:
        """Wait `delay` seconds, or with None for an append; an append ends it early."""
        self._wake.clear()
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(delay):
                await self._wake.wait()


def _log_death(task: asyncio.Task[None]) -> None:
    """The drain's done-callback: an unexpected end is logged by its error class only."""
    error = None if task.cancelled() else task.exception()
    if error is not None:
        _log().critical("audit lane drain died", error=type(error).__name__)


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)
