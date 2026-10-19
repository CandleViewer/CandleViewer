"""The journal-first audit lane's boot and drain (ADR-0037 decisions 7 and 8; #3009 slice S2a2),
its directory lock and its façade (decisions 1, 2 and 9; slice S2b-2a).

`docs/plan/24-internal-schemas.md` §15.6 owns the scan, the hand-over, the rows and the
confirmation (C-16.5); this module runs them and restates none. A boot creates a new lane with
`audit.lane_started` and appends `audit.lane_resumed`. One drain task then hands each unit of the
boot's scan, and of the running scans after it, to `AuditWriter.ingest()` in order, and moves the
marker past a unit once the writer reports its token committed. No log line carries a record (U41).
A held boot writes neither row; otherwise no cap refuses them (§15.6 Limits).
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import fcntl
import json
import os
import time
import uuid
from collections import deque
from collections.abc import Callable
from io import FileIO
from pathlib import Path
from typing import Any, get_args

import structlog
from pydantic import ValidationError

from candleviewer.audit import lane_journal as lj
from candleviewer.audit import writer as aw
from candleviewer.audit.actions import LANE_ACTIONS, LaneClass, UnknownAuditAction
from candleviewer.audit.models import AuditEmission, AuditOutcome, ExchangeEnv, Severity
from candleviewer.observability.context import spawn

Unit = lj.Handover | lj.Run
REFUSALS: tuple[str, ...] = (*get_args(lj.LaneReason), "timeout")  # §15.6's, and the façade's


class AuditLane:
    """The lane's journal, boot and one drain task; `confirmed` is the last marker's position. A
    failed `start()` leaves the journal unusable (a retry builds a new one). The deques hold units
    after the marker, which the journal bounds (C-2.18)."""

    def __init__(
        self,
        journal: lj.LaneJournal,
        writer: aw.AuditWriter,
        *,
        retry_s: tuple[float, float] = lj.RETRY_S,
        poll_s: float = lj.CONFIRM_POLL_S,
        batch: int = lj.DRAIN_BATCH,
        pause_depth: int = lj.DRAIN_PAUSE_DEPTH,
        new_lane: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self.journal, self._writer, self._new_lane = journal, writer, new_lane
        self._retry, self._poll, self._batch = retry_s, poll_s, batch
        self._pause_depth, self._paused = pause_depth, False  # Limits: the drain's pacing
        self.paused_batches = 0  # each pause at `pause_depth` (S4a's metric)
        self.drained = 0  # S4a: units whose rows the writer reports committed
        self.anomalies = dict.fromkeys(lj.ANOMALY_REASONS, 0)  # S4a: rows handed over, by reason
        self.drain_failures = {"held": 0, "stopped": 0}  # S4a: a hold a running scan met; a death
        self.confirmed: lj.Pos | None = None
        self._lane: uuid.UUID | None = None  # the scan's; None while no frame or marker set one
        self._origin = lj.LaneMarker(uuid.UUID(int=0), (1, 0), 1, lj.ZERO_MAC, True)  # next scan's
        self._units: deque[Unit] = deque()  # scanned, not yet handed over
        self._pending: deque[tuple[lj.LaneMarker | None, int]] = deque()  # handed over, by token
        self._dirty, self._wake = False, asyncio.Event()  # an append since the last scan
        self._moved = asyncio.Event()  # the marker moved
        self._task: asyncio.Task[None] | None = None
        self._copied: str | None = None  # the last run copied to `quarantine/`

    async def start(self) -> lj.LaneScan:
        """Boot: the scan; unless it holds, `audit.lane_started` when frame 1 is due and
        `audit.lane_resumed` with the head its frame follows, past any cap; then the drain. A
        failed `open()` (a file longer than any the lane writes, a symlinked file) holds the lane,
        then raises: the caller boots on, and every append is refused with `held` (S2b-2a). One
        cancelled meanwhile stops it, though the shielded open runs on to its end."""
        try:
            result = await self.journal.open(self._new_lane)
        except (lj.LaneError, OSError):
            self.journal.hold()
            raise
        except BaseException as exc:  # no lane accepts an append that no drain hands over
            self.journal.stop(exc)
            raise
        journal, self._lane = self.journal, result.lane
        self._units.extend(result.units)
        new = lj.LaneMarker(journal.lane, (1, 0), 1, lj.ZERO_MAC, True)
        self._origin = journal.boot_marker or new
        held = journal.refusal == "held"  # Hold: no lane creation, no resumed row, no appends
        if journal.fresh and not held:
            await self._boot_row(self._own("audit.lane_started", Severity.WARNING))
        (seq, mac), anchored = journal.head, result.state.anchored or result.lane is None
        head = {"head_seq": seq, "head_mac": mac, "anchored": anchored}  # a new lane is anchored
        if held:
            _log().critical("audit lane held at boot", hold=result.hold)
        else:
            await self._boot_row(self._own("audit.lane_resumed", Severity.INFO, head))
        self._task = spawn(self._drain(), name="audit-lane-drain")
        self._task.add_done_callback(self._died)
        return result

    async def _boot_row(self, record: AuditEmission) -> None:
        """A boot row refused all the same, or cancelled, stops the lane: a failed `start()`
        refuses appends."""
        try:
            await self.append(record)
        except BaseException as exc:
            if self.journal.refusal is None:
                self.journal.stop(exc)
            raise

    async def append(self, record: AuditEmission) -> int:
        """Journal a record that `build()` made; its `seq` once durable. A refusal wakes nothing;
        a cancelled caller's frame can still land (#2250), so it wakes the drain too (one still
        queued for the lock lands nothing, which costs one scan)."""
        try:
            seq = await self.journal.append(json.loads(record.model_dump_json()))
        except asyncio.CancelledError:
            self._landed()
            raise
        self._landed()
        return seq

    def _landed(self) -> None:
        self._dirty = True
        self._wake.set()

    async def flush(self, timeout_s: float) -> None:
        """Return once every frame appended before the call is confirmed (§15.6 Ingest step 3),
        or raise `TimeoutError`; a held or stopped lane never confirms them."""
        target = self.journal.end
        async with asyncio.timeout(timeout_s):
            while self.confirmed is None or self.confirmed < target:
                self._moved.clear()
                await self._moved.wait()

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
            self._wake.clear()  # here, not in `_pause()`: an append during this iteration wakes it
            if self._writer.failure is not None:  # Ingest step 2: no retry until a restart
                await self._pause(self._retry[1])
                continue
            if not self._units and self._dirty:
                self._dirty = False
                result = await self.journal.rescan(self._origin)
                if result.held:
                    self.drain_failures["held"] += 1
                    self.journal.hold()
                self._lane = result.lane
                self._units.extend(result.units)
            refused = await self._hand_over_batch()
            await self._confirm()
            if refused:
                await self._pause(delay)
                delay = min(2 * delay, self._retry[1])
                continue
            delay = self._retry[0]
            if self._paused or not (self._units or self._dirty):
                await self._pause(self._poll if self._pending or self._paused else None)

    async def _hand_over_batch(self) -> bool:
        """Up to `batch` units in order, none while the writer holds `pause_depth` records not
        yet in Postgres (Limits); True when a transient refusal ended it (Ingest step 2)."""
        for _ in range(min(self._batch, len(self._units))):
            if self._writer.buffer_depth >= self._pause_depth:  # Limits: live `emit()` keeps it
                if not self._paused:  # a pause counts once, however often the drain looks
                    self.paused_batches += 1
                self._paused = True
                return False
            self._paused, unit = False, self._units[0]
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
        if unit.quarantined != self._copied:  # a retry after a refusal copies nothing again
            await self.journal.quarantine(unit)
            self._copied = unit.quarantined
        token = await self._writer.ingest(self._row(unit))
        if unit.reason in self.anomalies:  # closed by the scan; a metric never ends the drain
            self.anomalies[unit.reason] += 1
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
            self.drained += 1
        if marker is not None:
            await self.journal.confirm(marker)
            self.confirmed = marker.pos
            self._moved.set()
            await self.journal.compact()

    async def _pause(self, delay: float | None) -> None:
        """Wait `delay` seconds, or with None for an append; an append ends it early."""
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(delay):
                await self._wake.wait()

    def _died(self, task: asyncio.Task[None]) -> None:
        """Failures while running: a drain that ends with an error stops the lane (`stopped`, a
        hold stays a hold), so the façade falls back. The log names the error class only."""
        error = None if task.cancelled() else task.exception()
        if error is not None:
            self.drain_failures["stopped"] += 1
            _log().critical("audit lane drain died", error=type(error).__name__)
            if self.journal.refusal is None:  # `_io()` has stopped it already: one log line
                self.journal.stop(error)


#: Decision 9: held exclusively by the one running cv-api; S2c's release command takes it too.
LOCK_FILE = "lane.lock"
#: The hard-link probe's file in `lane/` (and its link, `.link`); the scan reads neither.
PROBE_FILE = "link.probe"
#: The façade logs `audit.lane.fallback` once per refusal reason per this many seconds, with the
#: fallbacks it did not log: a held or stopped lane falls back on every admitted record until a
#: restart, so S4a's refusal counter is the signal, not this line.
FALLBACK_LOG_S = 60.0


class LaneBootRefused(lj.LaneError):
    """Decision 9 refuses boot: the lane directory is not anchored, or `lane.lock` is held."""


class LaneLockUnavailable(lj.LaneError):
    """`lane.lock` cannot be taken for another reason (`EACCES`, …): the lane holds (READY-21)."""


def lane_dir(audit_wal_path: str) -> Path:
    """`<dir of CV_AUDIT_WAL_PATH>/lane/` (decision 9), as cv-api resolves the WAL path."""
    return Path(audit_wal_path).parent / "lane"


def lock_lane(audit_wal_path: str) -> FileIO:
    """Take `lane.lock` exclusively without waiting; closing the file drops it. The WAL path must
    be absolute and free of `..`, and neither the audit directory, `lane/` nor the lock may be a
    symlink (the `anchored_journal_dir` rule; the lock by `O_NOFOLLOW`). A missing `lane/` is made
    `0700`; one that exists keeps its mode, in the `0700` audit directory the image creates."""
    raw, directory = Path(audit_wal_path), lane_dir(audit_wal_path)
    if not raw.is_absolute() or ".." in raw.parts:
        raise LaneBootRefused("CV_AUDIT_WAL_PATH must be absolute and free of '..'")
    for path in (raw.parent, directory):
        if path.is_symlink():
            raise LaneBootRefused(f"audit lane path {path.name!r} must not be a symlink")
    try:
        if lj._mkdir(directory):
            lj.LaneFiles(directory).sync_dir(raw.parent)
        fd = lj._open(directory / LOCK_FILE, os.O_RDONLY | os.O_CREAT)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(fd)
            raise
    except BlockingIOError as exc:
        raise LaneBootRefused("lane.lock is held by another process") from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise LaneBootRefused("audit lane path must not be a symlink") from exc
        _log().critical("audit lane lock unavailable; the lane holds", error=type(exc).__name__)
        raise LaneLockUnavailable(type(exc).__name__) from exc
    return FileIO(fd, "r")


def links_work(audit_wal_path: str) -> bool:
    """§15.6 Failures while running: a segment is published by a hard link, so on a volume
    without them the lane would stop at its first publish. Probed at boot, under `lane.lock`, in
    a worker thread; any error is a boot failure, so the lane holds (READY-21), logged critical."""
    probe = lane_dir(audit_wal_path) / PROBE_FILE
    link = probe.with_name(f"{PROBE_FILE}.link")
    try:
        for path in (link, probe):  # a crash's leftovers
            path.unlink(missing_ok=True)
        os.close(lj._open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL))
        try:
            os.link(probe, link, follow_symlinks=False)
        finally:
            for path in (link, probe):
                path.unlink(missing_ok=True)
    except OSError as exc:
        _log().critical("audit lane hard-link probe failed; it holds", error=type(exc).__name__)
        return False
    return True


async def boot_lane(
    audit_wal_path: str, keys: tuple[bytes, bytes | None], writer: aw.AuditWriter, held: bool
) -> AuditLane:
    """The lane at boot, after the writer and the break-glass fold-in. Without `lane.lock`
    (`held`) it holds unopened; a failed `start()` leaves it held or stopped (S2a2b). Either way
    it refuses every append, the façade falls back, and boot goes on."""
    journal = lj.LaneJournal(lj.LaneFiles(lane_dir(audit_wal_path)), lj.LaneKeys(*keys))
    lane = AuditLane(journal, writer)
    if held:
        journal.hold()
    else:
        with contextlib.suppress(lj.LaneError, OSError):
            await lane.start()
    return lane


class LaneFacade:
    """`AuditService.lane` (decisions 1, 2 and 12): `emit()`'s keywords and `deadline_s`, the
    caller's deadline, shared by the lane's wait and the fallback. `build()` validates and redacts
    once. With `journal_first` on, a record `LANE_ACTIONS` admits goes to the lane first; a refusal
    or no answer within `wait_s` hands the same record to `ingest()`, which takes all else. One
    rule: `audit.lane_*` comes from the lane only, a `LaneNotAdmitted` never reaches the sink, and
    a lane that cannot boot holds, so an action fails closed (C-2.9) only if `ingest()` refuses too:
    the caller gets what it raises, or `AuditUnavailable` past the deadline."""

    def __init__(
        self,
        writer: aw.AuditWriter,
        lane: AuditLane | None,
        journal_first: Callable[[], bool],
        *,
        wait_s: float = lj.APPEND_WAIT_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._writer, self._lane, self._journal_first = writer, lane, journal_first
        self._wait_s, self._clock = wait_s, clock
        self._fallbacks: dict[str, tuple[float, int]] = {}  # per reason: last line, since then
        #: S4a: the records the lane refused or left unanswered past `wait_s`, by class and reason.
        self.refused = {(c, r): 0 for c in get_args(LaneClass) for r in REFUSALS}

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
        deadline_s: float | None = None,
    ) -> None:
        if action.startswith("audit.lane_"):
            raise lj.LaneNotAdmitted("audit.lane_* records come from the audit lane only")
        record = self._writer.build(
            action, actor_label=actor_label, actor_user_id=actor_user_id, actor_ip=actor_ip,
            session_id=session_id, object_kind=object_kind, object_id=object_id,
            object_label=object_label, outcome=outcome, severity=severity, reason=reason,
            before_state=before_state, after_state=after_state, request_id=request_id, env=env,
        )  # fmt: skip
        try:
            async with asyncio.timeout(deadline_s):
                if not await self._journaled(record):
                    await self._writer.ingest_counted(record)
        except TimeoutError:
            raise aw.AuditUnavailable("the audit record missed its caller's deadline") from None

    async def _journaled(self, record: AuditEmission) -> bool:
        """Decision 1: True once the lane holds the record; False sends it to `ingest()`."""
        row = LANE_ACTIONS.get(record.action)
        if self._lane is None or row is None or record.outcome not in row[1]:
            return False
        if not self._journal_first():  # a cached read: never the caller's deadline (READY-21)
            return False
        try:
            async with asyncio.timeout(self._wait_s):
                await self._lane.append(record)
        except (lj.LaneRefused, TimeoutError) as exc:
            refusal = exc.reason if isinstance(exc, lj.LaneRefused) else "timeout"
            self.refused[row[0], refusal] += 1
            self._fell_back(refusal, record)
            return False
        return True

    def _fell_back(self, reason: str, record: AuditEmission) -> None:
        """One `audit.lane.fallback` WARNING per §15.6 reason per `FALLBACK_LOG_S`, which counts
        the fallbacks since the last one; the reasons are a closed set, so the map is bounded."""
        now, last = self._clock(), self._fallbacks.get(reason)
        if last is not None and now - last[0] < FALLBACK_LOG_S:
            self._fallbacks[reason] = (last[0], last[1] + 1)
            return
        self._fallbacks[reason] = (now, 0)
        skipped = 0 if last is None else last[1]
        _log().warning("audit.lane.fallback", reason=reason, action=record.action, skipped=skipped)

    async def flush(self, timeout_s: float) -> None:
        """§15.6 Ingest step 3, for a test that reads rows after a lane write; no lane, no wait."""
        if self._lane is not None:
            await self._lane.flush(timeout_s)


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)
