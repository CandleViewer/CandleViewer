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
   the WAL commit cursor. Postgres errors are retried with backoff; the WAL
   is the buffer.
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
these tasks before and after it cancels the flusher.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Concatenate

import structlog

from candleviewer.audit.actions import validate_action
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditEmission, AuditOutcome, ExchangeEnv, Severity
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
        self._running = False
        self._pending = 0
        self._written_total = 0
        self._write_errors_total = 0
        self._refused_total = 0
        self._inflight = False
        self._max_insert_attempts = max_insert_attempts
        self._failure: BaseException | None = None

    @property
    def written_total(self) -> int:
        return self._written_total

    @property
    def refused_total(self) -> int:
        """`emit()` calls refused with `AuditUnavailable` (WAL full/unwritable)."""
        return self._refused_total

    @property
    def write_errors_total(self) -> int:
        return self._write_errors_total

    @property
    def buffer_depth(self) -> int:
        """Records accepted into the WAL by this process, not yet in Postgres."""
        return self._pending

    @property
    def failure(self) -> BaseException | None:
        """Why the flusher died (None while healthy)."""
        return self._failure

    async def start(self) -> None:
        """Start the flusher. It replays WAL backlog from a previous run
        first, inside the task, so `start()` never blocks on Postgres.
        Also the recovery path after a fail-closed flusher death."""
        if self._task is not None and not self._task.done():
            return
        self._failure = None
        self._running = True
        self._idle.clear()
        self._wake.set()
        self._task = spawn(self._supervised(), name="audit-writer")
        self._task.add_done_callback(_log_task_failure)

    async def flush(self, timeout_s: float) -> None:
        """Wait until every WAL record is committed to Postgres."""
        async with asyncio.timeout(timeout_s):
            await self._idle.wait()

    async def stop(self, grace_s: float = 5.0) -> None:
        self._running = False
        # Appends already handed to a WAL op land before the flusher is
        # cancelled (#2250). Not bounded by `grace_s`: each op is one WAL call
        # plus bookkeeping, and a WAL still being written after stop() returns
        # could be truncated as a torn tail by the next writer on the same file.
        await self._drain_wal_ops()
        if self._task is None:
            return
        if self._task.done():
            # Flusher already died (fail-closed; `failure` holds the cause and
            # the alarm has fired). Nothing to drain; the WAL keeps the backlog.
            self._task = None
            return
        try:
            await self.flush(grace_s)
        except TimeoutError:
            logger().warning("AuditWriter.stop: WAL not drained within %.1fs", grace_s)
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            # Expected: we cancelled it. Every record emit() accepted is
            # already fsync'd in the WAL; unflushed ones are replayed
            # (idempotently, by record_id) on the next start().
            pass
        self._task = None
        # A read or commit + compaction the flusher was inside keeps
        # `_wal_lock` until its WAL thread returns; wait for it as well.
        await self._drain_wal_ops()

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
        """Durably append one audit entry to the WAL, then return.

        Raises `AuditWriterStopped` if not running, `UnknownAuditAction` for
        an unregistered action, and `AuditUnavailable` if the record could
        not be made durable — the caller must then refuse the action.
        Cancelling the caller never interrupts an append that has started:
        that record is still accepted. Cancelled while still queued for
        `_wal_lock`, nothing is appended (see `_shielded`)."""
        if self._failure is not None:
            self._refused_total += 1
            raise AuditUnavailable(f"audit flusher failed: {type(self._failure).__name__}")
        if not self._running:
            raise AuditWriterStopped()
        validate_action(action)
        emission = AuditEmission(
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
        record = json.loads(emission.model_dump_json())
        await self._shielded("audit-wal-append", self._accept, record)

    async def _accept(self, op: _WalOp, record: dict[str, Any]) -> None:
        """`emit()`'s WAL op: append + bookkeeping under `_wal_lock`, then the
        fail-closed alarm and the flusher wake-up. Once it holds the lock it
        runs to the end even if `emit()`'s caller, or the op task itself, was
        cancelled; a cancel of the op task is raised after the wake-up."""
        try:
            async with self._wal_lock:
                op.holding = True
                await self._append_durably(op, record)
                self._pending += 1
                # Under the lock, so the flusher cannot mark idle after this.
                self._idle.clear()
        except (AuditWalFull, OSError) as exc:
            self._refused_total += 1
            reason_text = f"audit WAL unavailable: {type(exc).__name__}"
            if self._on_alarm is not None:
                await self._on_alarm(reason_text)
            logger().critical(reason_text)
            raise AuditUnavailable(reason_text) from exc
        self._wake.set()
        op.raise_if_cancelled()

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

    async def _drain_wal_ops(self) -> None:
        """Wait until no WAL op is in flight (`stop()`)."""
        while self._wal_ops:
            await asyncio.wait(set(self._wal_ops))

    async def _append_durably(self, op: _WalOp, record: dict[str, Any]) -> None:
        """Caller holds `_wal_lock`. On `AuditWalFull`, reclaim the committed
        prefix (only when no flush batch is in flight, whose offsets a
        compaction would invalidate) and retry once."""
        try:
            await _uninterruptible(op, self._wal.append, record)
        except AuditWalFull:
            if self._inflight or self._wal.committed_offset() == 0:
                raise
            await _uninterruptible(op, self._wal.compact)
            await _uninterruptible(op, self._wal.append, record)

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
            if self._on_alarm is not None:
                await self._on_alarm(reason_text)
            raise

    async def _run(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while True:
                batch = await self._shielded("audit-wal-read", self._read_batch)
                if not batch:
                    break
                for _end_offset, record in batch:
                    await self._write_with_retry(record)
                    self._written_total += 1
                # One cursor fsync per batch: a crash mid-batch re-inserts the
                # already-written prefix, which ON CONFLICT (record_id) ignores.
                await self._shielded("audit-wal-commit", self._commit, batch[-1][0], len(batch))

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

    async def _commit(self, op: _WalOp, end_offset: int, count: int) -> None:
        """Flusher WAL op: advance the commit cursor, then compact — both under
        `_wal_lock`, so no append can land between the copy and the file swap."""
        async with self._wal_lock:
            op.holding = True
            await _uninterruptible(op, self._wal.mark_committed, end_offset)
            self._pending = max(0, self._pending - count)
            self._inflight = False
            # Cancelled during the cursor write: the cursor is durable and the
            # bookkeeping above is done; compaction is optional, so it is skipped.
            # (If mark_committed raised, its error propagated before any of this.)
            if not op.cancel_pending:
                await _uninterruptible(op, self._wal.compact)
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
    if not task.cancelled() and task.exception() is not None:
        logger().critical("audit writer task died", exc_info=task.exception())


def _path(raw: str) -> Path:
    return Path(raw)
