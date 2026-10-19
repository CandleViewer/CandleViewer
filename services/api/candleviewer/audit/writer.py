"""`AuditWriter` — WAL-first, never-lossy audit append path (C-2.9, C-2.18).

Write path (PR #1561 security findings 1-2):

1. `emit()` validates the action, redacts `before_state`/`after_state`,
   assigns a `record_id` (uuid) and **durably appends** the record to the
   local WAL (`write` + `fsync`, in a worker thread so the loop never blocks,
   serialised by `_wal_lock`) *before it returns*. Acceptance == durability:
   once `emit()` returns, the record survives `stop()`, a crash or a
   Postgres outage.
2. A single flusher task reads uncommitted records from the WAL in append
   order and inserts each into `audit_log` (the repository and the
   `audit_chain()` trigger both take `pg_advisory_xact_lock`), then advances
   the WAL commit cursor. Each record is made storable first
   (`models.storable`), whenever it was appended. Postgres errors are retried
   with backoff; the WAL is the buffer.
3. `start()` replays any WAL records left by a previous run first (same
   loop). Replay is idempotent: `record_id` is UNIQUE and the insert is
   `ON CONFLICT (record_id) DO NOTHING`, closing the "row committed, cursor
   not advanced" crash window — every record reaches the DB exactly once.

Overflow policy (bounded, fail-closed, never drop): the WAL is capped at
`max_wal_bytes`. When full, the committed prefix is compacted and the append
retried; if it is still full (Postgres down long enough to fill it), or the
WAL cannot be written at all (`OSError`), `emit()` raises
`AuditUnavailable` and fires `on_alarm`. Callers MUST treat that as "refuse
the audited action". No record that `emit()` accepted is ever discarded.

Append-failure latch (#2510), recoverable unlike a flusher death: such a refusal
sets `append_failure` (its `clock` time) until an append succeeds; within
`APPEND_FAILURE_COOLDOWN` of it `app._audit_ready()` answers the audited owner
routes 503 up front. It never refuses `emit()`, so after the cooldown the next
write-ahead record re-probes the WAL (success clears it, failure re-arms it).

Flusher death (PR #1561 N2) — fail closed, no in-process restart: if the
flusher task raises (mid-WAL `AuditWalCorrupt`, an unexpected bug, or an
insert that exhausted `max_insert_attempts`), `_running` goes False,
`on_alarm` fires once and every later `emit()` raises `AuditUnavailable`.
Chosen over bounded auto-restart because every failure that escapes the
retry loop is deterministic (corruption or a poison record) — restarting
would fail the same way. The WAL is untouched, so `start()` (after the
cause is fixed) replays everything accepted so far.

Cancellation (#2250): `AuditWal` has no lock of its own, so every
`_wal_lock` critical section (append, batch read, commit + compaction) runs
as a tracked task that its caller awaits through `asyncio.shield`. A
cancelled caller (an `asyncio.timeout` around `emit()`, or `stop()`
cancelling the flusher) can no longer release the lock while a WAL worker
thread is still running; before, the next append truncated the in-flight
frame as a torn tail and `AuditWal._end` drifted past EOF. A cancel of an
op task itself (event-loop teardown) is deferred until its WAL call has
returned and its bookkeeping is done (`_uninterruptible`). `stop()` drains
these tasks before and after it cancels the flusher. It runs as one owned
shutdown task shared by every caller: a cancelled caller (a supervisor's
timeout) returns at once while the shutdown still completes.

Build, commit tokens (#3009, ADR-0037 decisions 2 and 7): `build()` is `emit()`'s
validating half. It checks the action, redacts the states and builds the `AuditEmission`
with a new `record_id` and an `event_ts` read from the clock once, and writes nothing, so
a record can be built while the writer refuses. `ingest()` appends a built record, or its
JSON form, keeping both, and returns a commit token: the record's ordinal in this writer's
WAL append order. `committed_through()` is the highest token whose record the flusher has
inserted into Postgres; it inserts in WAL order, so every token at or below it is there.
Tokens are process-local and never persisted; a compaction or a flusher restart keeps them.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Concatenate

import structlog

from candleviewer.audit.actions import validate_action
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditEmission, AuditOutcome, ExchangeEnv, Severity, storable
from candleviewer.audit.redact import redact
from candleviewer.audit.repository import AuditRepository
from candleviewer.audit.wal import AuditWal, AuditWalFull
from candleviewer.observability.context import spawn, thread_future


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


AlarmCallback = Callable[[str], Awaitable[None]] | None
Clock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[None]]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _uuid_or_none(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)


async def _uninterruptible[T](op: _WalOp, fn: Callable[..., T], /, *args: Any) -> T:
    """Run one blocking WAL call in a worker thread and wait for it to return even if
    the op task is cancelled meanwhile (#2250 review).

    The op holds `_wal_lock`: releasing it while the thread still runs would let a
    second append truncate the in-flight frame. `thread_future` returns the plain
    executor future, not a Task, so event-loop teardown cannot cancel it; never wrap
    the call in a Task (`spawn(run_in_thread(...))`, `asyncio.to_thread`), because
    teardown would cancel that Task and with it the future, while the thread runs.

    A cancellation of the op task does not end the op here. It is recorded as
    `op.cancel_pending` and the call's result is returned, so the op finishes its
    bookkeeping (`_pending`, `_idle`, `_wake`, `_inflight`) before it raises
    `CancelledError` itself (`_WalOp.raise_if_cancelled`). If the WAL call raised,
    that exception propagates instead and the deferred cancel is not re-raised
    here: an op that ends with the WAL error reports it in place of the cancel
    (an emit then gets `AuditUnavailable`)."""
    fut = thread_future(fn, *args)
    while not fut.done():
        try:
            await asyncio.shield(fut)
        except asyncio.CancelledError:
            if not op.cancel_pending:
                logger().critical(
                    "audit WAL op cancelled while its worker thread runs; "
                    "holding _wal_lock until it returns",
                    call=getattr(fn, "__name__", "?"),
                )
            op.cancel_pending = True
    return fut.result()


#: Upper bound on the `on_alarm` callback (a slow pager must not stall a WAL op).
_ALARM_TIMEOUT_S = 2.0
#: How long a failed WAL append keeps `append_failure_active` true (#2510): long enough
#: to turn a burst of owner actions away up front, short enough to re-probe a fixed disk.
APPEND_FAILURE_COOLDOWN = timedelta(seconds=5)


class AuditWriter:
    """Owns the WAL and the single flusher task.

    `start()` spawns the flusher (which first replays WAL backlog);
    `stop(grace_s)` stops accepting `emit()`, waits up to `grace_s` for the
    WAL to drain into Postgres, then cancels the flusher. Anything not yet
    flushed is already durable in the WAL and is replayed on the next start.
    """

    def __init__(
        self,
        repository: AuditRepository,
        wal_path: str,
        *,
        flush_batch_size: int = 500,
        max_wal_bytes: int = 64 * 1024 * 1024,
        retry_initial_delay_s: float = 0.5,
        retry_max_delay_s: float = 30.0,
        on_alarm: AlarmCallback = None,
        clock: Clock = _utc_now,
        sleep: Sleeper = asyncio.sleep,
        max_insert_attempts: int | None = None,
    ) -> None:
        self._repository = repository
        self._wal = AuditWal(_path(wal_path), max_bytes=max_wal_bytes)
        self._wal_lock = asyncio.Lock()
        #: In-flight `_wal_lock` critical sections (see `_shielded`); `stop()` drains them.
        self._wal_ops: set[asyncio.Task[Any]] = set()
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._flush_batch_size = flush_batch_size
        self._retry_initial_delay_s = retry_initial_delay_s
        self._retry_max_delay_s = retry_max_delay_s
        self._on_alarm = on_alarm
        self._clock = clock
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None
        #: The one shutdown run behind `stop()`, shared by every caller (see `stop`).
        self._stopping: asyncio.Task[None] | None = None
        self._running = False
        self._pending = 0
        self._written_total = 0
        self._write_errors_total = 0
        self._refused_total = 0
        self._drain_overruns_total = 0
        self._inflight = False
        self._max_insert_attempts = max_insert_attempts
        self._failure: BaseException | None = None
        self._append_failed_at: datetime | None = None
        #: The WAL position of each append whose record is not yet in Postgres, oldest first:
        #: entry i holds token `_committed_through + i + 1`. One per frame in the WAL, so the
        #: WAL's cap bounds it (C-2.18).
        self._uncommitted: deque[int] = deque()
        self._committed_through = 0
        #: Records confirmed since the last cursor commit: their frames are still in the WAL.
        self._confirmed_since_commit = 0
        #: Bytes that compactions removed from the front of the WAL file, so `_base + offset`
        #: is a position no compaction moves.
        self._base = 0

    @property
    def written_total(self) -> int:
        return self._written_total

    @property
    def refused_total(self) -> int:
        """`emit()` calls refused with `AuditUnavailable` (WAL full/unwritable)."""
        return self._refused_total

    @property
    def drain_overruns_total(self) -> int:
        """`stop()` drain intervals that expired with a WAL op still running (hung disk)."""
        return self._drain_overruns_total

    @property
    def write_errors_total(self) -> int:
        return self._write_errors_total

    @property
    def buffer_depth(self) -> int:
        """Records accepted into the WAL by this process whose batch is not yet committed, so
        a frame leaves the count with its bytes; an earlier run's backlog is not in it."""
        return self._pending

    @property
    def failure(self) -> BaseException | None:
        """Why the flusher died (None while healthy)."""
        return self._failure

    @property
    def append_failure(self) -> datetime | None:
        """When the last WAL append failed (`AuditWalFull`/`OSError`); None once a later
        append succeeded. Never refuses `emit()` (see the module docstring, #2510)."""
        return self._append_failed_at

    @property
    def append_failure_active(self) -> bool:
        """True within `APPEND_FAILURE_COOLDOWN` of an unrecovered append failure. A clock
        stepped back past the failure reads as expired: a re-probe, never a stuck refusal."""
        failed = self._append_failed_at
        if failed is None:
            return False
        return timedelta(0) <= self._clock() - failed < APPEND_FAILURE_COOLDOWN

    def committed_through(self) -> int:
        """The highest commit token (`ingest()`) whose record the flusher has inserted into
        Postgres, 0 before the first. It inserts in WAL order, so every token at or below
        this one is in Postgres. It never decreases: a compaction and a flusher restart
        (`start()` after `stop()` or after a flusher death) keep it."""
        return self._committed_through

    async def start(self) -> None:
        """Start the flusher. It replays WAL backlog from a previous run
        first, inside the task, so `start()` never blocks on Postgres.
        Also the recovery path after a fail-closed flusher death. Raises
        `RuntimeError` while a `stop()` is still shutting the writer down."""
        if self._stopping is not None:
            if not self._stopping.done():
                raise RuntimeError("AuditWriter.start(): stop() is still in progress")
            self._stopping = None  # finished: the next stop() runs a new shutdown
        if self._task is not None and not self._task.done():
            return
        self._failure = None
        # A flusher that stopped mid-batch confirmed records it never committed: count them
        # again, since the restart reads the whole batch from the unmoved cursor.
        self._pending = len(self._uncommitted) + self._confirmed_since_commit
        self._running = True
        # An op abandoned by a previous stop() may have read a batch with no commit
        # to clear this; a stale flag would refuse the emergency compaction (#2250).
        self._inflight = False
        self._idle.clear()
        self._wake.set()
        self._task = spawn(self._supervised(), name="audit-writer")
        self._task.add_done_callback(_log_task_failure)

    async def flush(self, timeout_s: float) -> None:
        """Wait until every WAL record is committed to Postgres."""
        async with asyncio.timeout(timeout_s):
            await self._idle.wait()

    async def stop(self, grace_s: float = 5.0) -> None:
        """Stop accepting `emit()`, drain in-flight WAL ops, give the flusher up to
        `grace_s` to empty the WAL into Postgres, then cancel it.

        The shutdown runs once, in an owned task that repeated and concurrent calls
        share (the first call's `grace_s` applies). Callers await it through
        `asyncio.shield`: a cancelled caller gets `CancelledError` at once and does
        not wait for it, so a timeout around `stop()` (`Supervisor._stop_each` in
        `app.py`) still moves on to the next module, while the shutdown itself runs
        to the end and always cancels the flusher. A failure of the shutdown reaches
        the callers still waiting and is logged at critical in any case."""
        if self._stopping is None:
            self._stopping = spawn(self._stop(grace_s), name="audit-writer-stop")
            self._stopping.add_done_callback(_log_task_failure)
        await asyncio.shield(self._stopping)

    async def _stop(self, grace_s: float) -> None:
        """The shutdown behind `stop()`; at most one runs at a time."""
        self._running = False
        # Appends already handed to a WAL op land before the flusher is
        # cancelled (#2250); see `_drain_wal_ops` for why this is unbounded.
        await self._drain_wal_ops(grace_s)
        task = self._task
        if task is not None and not task.done():
            try:
                await self.flush(grace_s)
            except TimeoutError:
                logger().warning("AuditWriter.stop: WAL not drained within %.1fs", grace_s)
            task.cancel()
            # Raises only if this shutdown is itself cancelled, never with the flusher's
            # outcome: cancelled as asked, or dead first (fail-closed, already logged).
            await asyncio.wait({task})
        # Every record emit() accepted is fsync'd in the WAL; whatever the flusher did
        # not commit is replayed (idempotently, by record_id) on the next start(). A
        # flusher that died earlier keeps its cause in `failure` (the alarm has fired).
        self._task = None
        # A read or commit + compaction the flusher was inside keeps
        # `_wal_lock` until its WAL thread returns; wait for it as well.
        await self._drain_wal_ops(grace_s)

    def build(
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
    ) -> AuditEmission:
        """`emit()`'s validating half (ADR-0037 decision 2): check the action, redact the
        states and build the record with a new `record_id` and an `event_ts` read from the
        clock once, here; `ingest()` keeps both. It writes nothing and does not check whether
        the writer runs, so a record can be built while the writer refuses. Raises
        `UnknownAuditAction` for an unregistered action and `ValueError` (a pydantic
        `ValidationError` among them) for a malformed field."""
        validate_action(action)
        return AuditEmission(
            record_id=uuid.uuid4(),
            action=action,
            actor_label=actor_label,
            actor_user_id=_uuid_or_none(actor_user_id),
            actor_ip=actor_ip,
            session_id=_uuid_or_none(session_id),
            object_kind=object_kind,
            object_id=object_id,
            object_label=object_label,
            outcome=outcome,
            severity=severity,
            reason=reason,
            before_state=redact(before_state),
            after_state=redact(after_state),
            request_id=_uuid_or_none(request_id),
            env=env,
            event_ts=self._clock(),
        )

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
    ) -> None:
        """Durably append one audit entry to the WAL, then return: `build()`, then `ingest()`.

        Raises `AuditWriterStopped` if not running, `UnknownAuditAction` for
        an unregistered action, and `AuditUnavailable` if the record could
        not be made durable — the caller must then refuse the action. A writer
        that refuses does so before `build()`: the action is not checked and the
        clock is not read. Cancelling the caller never interrupts an append that has started:
        that record is still accepted. Cancelled while still queued for
        `_wal_lock`, nothing is appended (see `_shielded`)."""
        self._refuse_unless_accepting()
        emission = self.build(
            action,
            actor_label=actor_label,
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            session_id=session_id,
            object_kind=object_kind,
            object_id=object_id,
            object_label=object_label,
            outcome=outcome,
            severity=severity,
            reason=reason,
            before_state=before_state,
            after_state=after_state,
            request_id=request_id,
            env=env,
        )
        await self.ingest(emission)

    async def ingest(self, record: AuditEmission | dict[str, Any]) -> int:
        """Durably append an already-redacted record that `build()` made, or one in its JSON
        form from elsewhere (`audit.journal.fold_in`, the lane's drain), keeping its `record_id`
        and `event_ts`. It validates the record, a model too, but never redacts it. Refuses as
        `emit()`; a record that is not a valid `AuditEmission` raises `UnknownAuditAction` or a
        pydantic `ValidationError`.

        Returns the record's commit token: its ordinal in this writer's WAL append order,
        from 1, process-local and never reused. `committed_through()` reaches it once the
        record is in Postgres. A `record_id` ingested before is appended again and gets the
        next token like any record; its insert is a no-op
        (`ON CONFLICT (record_id) DO NOTHING`), and that insert commits the token."""
        self._refuse_unless_accepting()
        if isinstance(record, AuditEmission):  # `model_validate()` returns an instance unchecked
            record = record.model_dump(warnings=False)
        emission = AuditEmission.model_validate(record)
        validate_action(emission.action)
        return await self._shielded(
            "audit-wal-append", self._accept, json.loads(emission.model_dump_json())
        )

    def _refuse_unless_accepting(self) -> None:
        """`AuditUnavailable` once the flusher died; `AuditWriterStopped` when not running."""
        if self._failure is not None:
            self._refused_total += 1
            raise AuditUnavailable(f"audit flusher failed: {type(self._failure).__name__}")
        if not self._running:
            raise AuditWriterStopped()

    async def _accept(self, op: _WalOp, record: dict[str, Any]) -> int:
        """`ingest()`'s WAL op: append + bookkeeping under `_wal_lock`, then the
        fail-closed alarm and the flusher wake-up; returns the commit token. Once it holds the
        lock it runs to the end even if `ingest()`'s caller, or the op task itself, was
        cancelled; a cancel of the op task is raised after the wake-up."""
        try:
            async with self._wal_lock:
                op.holding = True
                end_offset = await self._append_durably(op, record)
                self._pending += 1
                # Under the lock, so the flusher cannot mark idle after this.
                self._idle.clear()
                # Under the lock too, so tokens follow the WAL's append order.
                self._uncommitted.append(self._base + end_offset)
                token = self._committed_through + len(self._uncommitted)
        except (AuditWalFull, OSError) as exc:
            self._refused_total += 1
            self._append_failed_at = self._clock()  # the latch; the next append clears it
            reason_text = f"audit WAL unavailable: {type(exc).__name__}"
            logger().critical(reason_text)
            await self._alarm(reason_text)
            raise AuditUnavailable(reason_text) from exc
        self._append_failed_at = None
        self._wake.set()
        op.raise_if_cancelled()
        return token

    async def _alarm(self, reason_text: str) -> None:
        """Fire the fail-closed alarm without letting a slow or broken callback hold
        up the WAL op (and so `stop()`'s drain): bounded, errors logged, never raised."""
        if self._on_alarm is None:
            return
        try:
            async with asyncio.timeout(_ALARM_TIMEOUT_S):
                await self._on_alarm(reason_text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # an alarm sink failure must not mask the refusal
            logger().error("audit alarm callback failed", error=type(exc).__name__)

    async def _shielded[**P, T](
        self,
        name: str,
        body: Callable[Concatenate[_WalOp, P], Coroutine[Any, Any, T]],
        /,
        *args: P.args,
        **kwargs: P.kwargs,
    ) -> T:
        """Run one `_wal_lock` critical section as a tracked task awaited through
        `asyncio.shield` (#2250).

        `body` sets `op.holding` as soon as it holds `_wal_lock`. If the caller
        is cancelled after that, it gets `CancelledError` at once, but the task
        keeps the lock until its WAL thread has returned and its bookkeeping is
        done; a failure nobody awaits any more is logged. A task still queued
        for the lock holds nothing and has started no thread, so it is cancelled
        with its caller: a cancelled `emit()` that never reached the WAL appends
        nothing and leaves no task behind (C-2.18)."""
        op = _WalOp()
        task = spawn(body(op, *args, **kwargs), name=name)
        self._wal_ops.add(task)
        task.add_done_callback(self._wal_ops.discard)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if op.holding:
                task.add_done_callback(_log_abandoned_op)
            else:
                task.cancel()
            raise

    async def _drain_wal_ops(self, grace_s: float = 5.0) -> None:
        """Wait until no WAL op is in flight (`stop()`). Deliberately unbounded: a WAL
        call still running when stop() returns could be truncated as a torn tail by the
        next writer on the same file. A hung disk is made visible instead: each
        `grace_s` that passes logs at critical and counts `drain_overruns_total`."""
        while self._wal_ops:
            _done, pending = await asyncio.wait(set(self._wal_ops), timeout=grace_s)
            if pending:
                self._drain_overruns_total += 1
                logger().critical(
                    "AuditWriter.stop: WAL op still running after grace; waiting",
                    pending=len(pending),
                    grace_s=grace_s,
                )

    async def _append_durably(self, op: _WalOp, record: dict[str, Any]) -> int:
        """Caller holds `_wal_lock`. On `AuditWalFull`, reclaim the committed
        prefix (only when no flush batch is in flight, whose offsets a
        compaction would invalidate) and retry once. Returns the frame's end offset."""
        try:
            return await _uninterruptible(op, self._wal.append, record)
        except AuditWalFull:
            committed = 0 if self._inflight else self._wal.committed_offset()
            if committed == 0:
                raise
            await _uninterruptible(op, self._wal.compact)
            self._base += committed  # `compact()` dropped the committed prefix
            return await _uninterruptible(op, self._wal.append, record)

    async def _supervised(self) -> None:
        try:
            await self._run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._failure = exc
            self._running = False
            reason_text = f"audit flusher died: {type(exc).__name__}; emit() now fails closed"
            logger().critical(reason_text)
            await self._alarm(reason_text)
            raise

    async def _run(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while True:
                batch = await self._shielded("audit-wal-read", self._read_batch)
                if not batch:
                    break
                for end_offset, record in batch:
                    # A frame appended before records were normalised is made storable here.
                    await self._write_with_retry(storable(record))
                    self._written_total += 1
                    self._confirm(end_offset)
                # One cursor fsync per batch: a crash mid-batch re-inserts the
                # already-written prefix, which ON CONFLICT (record_id) ignores.
                await self._shielded("audit-wal-commit", self._commit, batch[-1][0])

    def _confirm(self, end_offset: int) -> None:
        """The record whose frame ends at `end_offset` is in Postgres, and so is every frame
        before it (the flusher inserts in WAL order): commit their tokens. No compaction runs
        while a batch is in flight, so `_base` is the one the batch was read under."""
        position = self._base + end_offset
        while self._uncommitted and self._uncommitted[0] <= position:
            self._uncommitted.popleft()
            self._committed_through += 1
            self._confirmed_since_commit += 1  # only this process's records have tokens

    async def _read_batch(self, op: _WalOp) -> list[tuple[int, dict[str, Any]]]:
        """Flusher WAL op: the next uncommitted batch; marks idle when empty."""
        async with self._wal_lock:
            op.holding = True
            batch = await _uninterruptible(op, self._wal.read_pending, self._flush_batch_size)
            # A cancelled read ends this flusher run, so nothing writes or commits
            # the batch: no stale in-flight flag may block the emergency compaction.
            self._inflight = bool(batch) and not op.cancel_pending
            if not batch:
                self._idle.set()
        op.raise_if_cancelled()
        return batch

    async def _commit(self, op: _WalOp, end_offset: int) -> None:
        """Flusher WAL op: advance the commit cursor, then compact — both under
        `_wal_lock`, so no append can land between the copy and the file swap. The records
        confirmed since the last commit leave `buffer_depth` with their frames."""
        async with self._wal_lock:
            op.holding = True
            await _uninterruptible(op, self._wal.mark_committed, end_offset)
            self._pending = max(0, self._pending - self._confirmed_since_commit)
            self._confirmed_since_commit = 0
            self._inflight = False
            # Cancelled during the cursor write: the cursor is durable and the
            # bookkeeping above is done; compaction is optional, so it is skipped.
            # (If mark_committed raised, its error propagated before any of this.)
            if not op.cancel_pending:
                await _uninterruptible(op, self._wal.compact)
                self._base += end_offset  # `compact()` dropped the committed prefix
        op.raise_if_cancelled()

    async def _write_with_retry(self, record: dict[str, Any]) -> None:
        delay = self._retry_initial_delay_s
        attempts = 0
        while True:
            attempts += 1
            try:
                await self._repository.insert(record)
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # any driver error is retried; the record stays in the WAL
                self._write_errors_total += 1
                if self._max_insert_attempts is not None and attempts >= self._max_insert_attempts:
                    raise
                logger().warning(
                    "audit insert failed (%s), retrying in %.2fs", type(exc).__name__, delay
                )
                await self._sleep(delay)
                delay = min(delay * 2, self._retry_max_delay_s)


class AuditWriterStopped(AuditError):
    """Raised by `emit()` when the writer is not running (fail loudly, never drop)."""

    def __init__(self) -> None:
        super().__init__("AuditWriter is not running; emit() refused")


class AuditUnavailable(AuditError):
    """Raised by `emit()` when the record could not be made durable (WAL full
    or unwritable). The audited action must be refused (C-2.9 fail-closed)."""


#: The actor of the audit lane's own records (§15.6 Ingest step 1).
LANE_ACTOR = "system:audit-lane"


def _lane_anomaly(
    writer: AuditWriter,
    record_id: uuid.UUID,
    *,
    reason: str,
    severity: Severity,
    lane: uuid.UUID | None,
    after_state: dict[str, Any],
) -> AuditEmission:
    """The lane drain's `audit.lane_anomaly` row (ADR-0037 decision 8; §15.6 Ingest step 1).
    Package-private: the drain in `audit/lane.py` is its only caller. It is `build()`, so the
    action check, the redaction and the model are the same, with the run's keyed `record_id`
    in place of a new one, which the public `build()` never takes."""
    row = writer.build(
        "audit.lane_anomaly",
        actor_label=LANE_ACTOR,
        object_kind="audit_lane",
        object_id=None if lane is None else str(lane),
        outcome=AuditOutcome.FAILURE,
        severity=severity,
        reason=reason,
        after_state=after_state,
    )
    return row.model_copy(update={"record_id": record_id})


@dataclass(slots=True)
class _WalOp:
    """One `_wal_lock` critical section (see `AuditWriter._shielded`)."""

    #: Set by the op right after it takes `_wal_lock`. From then on a cancellation of the
    #: op task cannot release the lock mid-call: each WAL call runs via `_uninterruptible`.
    holding: bool = False
    #: Set by `_uninterruptible` when the op task was cancelled during a WAL call. The op
    #: finishes that call and its bookkeeping, then raises (`raise_if_cancelled`).
    cancel_pending: bool = False

    def raise_if_cancelled(self) -> None:
        """Raise the deferred cancellation, once the op's bookkeeping is done."""
        if self.cancel_pending:
            raise asyncio.CancelledError


def _log_abandoned_op(task: asyncio.Task[Any]) -> None:
    """Done-callback of a WAL op whose caller was cancelled: nobody else sees its
    outcome. `AuditUnavailable` has already alarmed and logged inside the op."""
    exc = None if task.cancelled() else task.exception()
    if exc is not None and not isinstance(exc, AuditUnavailable):
        logger().critical(
            "audit WAL op failed after its caller was cancelled",
            op=task.get_name(),
            error=type(exc).__name__,
            exc_info=exc,
        )


def _log_task_failure(task: asyncio.Task[None]) -> None:
    """Done-callback of the flusher and of the shared shutdown task: logs, and so
    retrieves, an exception even when nobody awaits the task any more."""
    if not task.cancelled() and task.exception() is not None:
        logger().critical("audit writer task died", task=task.get_name(), exc_info=task.exception())


def _path(raw: str) -> Path:
    return Path(raw)
