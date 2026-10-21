"""`MachineEventWalSink`: the durable, synchronous `machine_events` sink (E50-T63, M19).

`CvAuditPlugin`'s hooks cannot await, so `append(row)` cannot call the async events store. The
sink follows `wal.py` and `AuditWriter` (acceptance is durability; the WAL is the buffer; never
lossy; fail closed) and reuses `AuditWal` (24-internal-schemas.md §17.6):

- `append` writes and `fsync`s one self-validating frame on the calling loop thread before it
  returns: one small frame of lifecycle-rate traffic, no network I/O (C-2.17, C-2.20). A row the
  table would refuse, or whose frame is over `MAX_FRAME_BYTES`, raises `MachineEventRejected` and
  writes nothing, so it never becomes a poison row: `occurred_at` must be the `+00:00` UTC form the
  row digest covers, the frame strict JSON (`json` refuses NaN and the infinities), and the CHECKs
  of `machine_events` and `sha256_hex` must hold.
- One supervised flusher, woken by `append`, waits `FLUSH_COALESCE_S`, reads one window
  (`AuditWal.read_window`: at most `FLUSH_BATCH_ROWS` rows and `FLUSH_WINDOW_BYTES`), inserts it
  (idempotent on `row_hash`), commits the cursor, and compacts only when that is O(1) (nothing
  pending) or a copy of at most `COMPACT_COPY_MAX_BYTES` (the committed prefix over half the cap).
  Every WAL call is bounded and runs on the loop thread; every await has a deadline. An outage, or
  a statement error of any SQLSTATE class but 22 and 23, retries with capped doubling backoff: the
  WAL is the buffer, so an outage with room in it loses nothing and blocks nothing. A data
  exception or integrity violation (class 22 or 23), a frame the store adapter refuses, or a
  corrupt frame is poison: the flusher stops (no in-process restart, as in `AuditWriter`), a P1
  page goes out (a CRITICAL `cv_page=true` line) and every later `append` fails closed.
- `append` raises `MachineEventUnavailable` when the WAL is full or unwritable, or the flusher has
  died; the plugin counts it (`sink_failures`), logs and re-raises, and the machine keeps running.
- The failure latch is `AuditWriter`'s (#2510): `append_failure_active` is true for
  `APPEND_FAILURE_COOLDOWN_S` after a failed append and false afterwards even if nothing appended
  since (a clock stepped back reads as expired). It never refuses an append and never waits for
  one; the next append re-probes the WAL. Its consumer is the order family's (E29-T03).
- `start()` takes an exclusive lock on `<wal>.lock` (one writer per file) and opens the WAL, whose
  open scans the whole file, in a worker thread; the flusher then replays the leftover frames. It
  never waits on Postgres. `stop()` stops accepting, drains for at most `STOP_GRACE_S` and leaves
  the rest durable in the WAL, replayed at the next start (a kill during the drain loses nothing).
- Chain continuity: one hash chain per machine key, advanced by every writer (the audit plugin
  and the fault-row writers) and continuous across restarts. `head(key)` is the last accepted
  `row_hash`, O(1) from a map bounded at `HEAD_KEYS_MAX` (least recently used evicted).
  `seed(key)` returns at once for a held key; otherwise it waits for the WAL to drain (rows of the
  key may still be in it) and reads the head through the store, both within `SEED_DRAIN_S`; a
  timeout or a read error raises `MachineEventUnavailable`, so no machine starts a chain that
  could fork. It is awaited before a restore calls `plugins(key)`, before an owner builds a
  machine, and by the fault-row writers before they build a row.

Rows are dataclass instances and frames the dicts `dataclasses.asdict` gives. `MachineEventRow`
lives in `statechart/plugins/audit.py` and is named here for annotations only: a run-time import
would load the statechart runtime into M19.
"""

from __future__ import annotations

import asyncio
import dataclasses
import fcntl
import json
import os
import re
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import FileIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Protocol

import structlog

from candleviewer.audit.errors import AuditError
from candleviewer.audit.wal import AuditWal, AuditWalFull
from candleviewer.observability.context import run_in_thread, spawn
from candleviewer.storage.errors import StorageQueryFailed

if TYPE_CHECKING:
    from candleviewer.statechart.plugins.audit import MachineEventRow


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: A row whose frame encodes to more bytes is rejected.
MAX_FRAME_BYTES: Final = 64 * 1024
#: Rows per `insert_batch`, and the byte bound of one `read_window`.
FLUSH_BATCH_ROWS: Final = 200
FLUSH_WINDOW_BYTES: Final = 256 * 1024
#: Appends of one burst share a batch.
FLUSH_COALESCE_S: Final = 0.05
#: Capped doubling backoff of a failed insert, as `AuditWriter`.
RETRY_INITIAL_S: Final = 0.5
RETRY_MAX_S: Final = 30.0
#: The largest copy a compaction may make on the loop thread.
COMPACT_COPY_MAX_BYTES: Final = 1024 * 1024
#: How long a failed append keeps `append_failure_active` true (#2510).
APPEND_FAILURE_COOLDOWN_S: Final = 5.0
#: The bounded drain of `stop()`, as `AuditWriter.stop`.
STOP_GRACE_S: Final = 5.0
#: The bound on `seed(key)`'s wait for the WAL to drain and its head read.
SEED_DRAIN_S: Final = 5.0
#: The chain-head map's bound (least recently used evicted).
HEAD_KEYS_MAX: Final = 10_000
#: The bound on one `insert_batch` (#3898's deadline carry). The store's own client deadline is
#: 3 s, so this cuts only a hang outside it.
INSERT_TIMEOUT_S: Final = 5.0

#: SQLSTATE classes of a poison batch: a data exception, an integrity violation.
_POISON_CLASSES: Final = frozenset({"22", "23"})
#: `machine_events`' CHECKs (24 §17.6) and the `sha256_hex` domain, mirrored at append.
_ENVS: Final = frozenset({"live", "demo", "testnet"})
_PHASES: Final = frozenset({"ahead", "commit", "fault"})
_SHA256_HEX: Final = re.compile(r"[0-9a-f]{64}")
_FRAME_OVERHEAD: Final = 1 + 1 + 9  # the header's newline, the body's newline, the CRC field


class MachineEventUnavailable(AuditError):
    """The row could not be made durable (the WAL full or unwritable, the flusher dead, the sink
    not running), or a chain head could not be read: fail closed (C-2.9)."""


class MachineEventRejected(AuditError, ValueError):
    """The row is refused before anything is written: the table would never accept it."""


class ChainKey(Protocol):
    """A machine key (`statechart.persistence.MachineKey`): one chain per key."""

    @property
    def machine_kind(self) -> str: ...

    @property
    def entity_id(self) -> str: ...

    @property
    def env(self) -> str: ...


class MachineEventStore(Protocol):
    """`machine_events` behind the sink: E50-T62's events store, through the composition root's
    adapter, which rebuilds each `MachineEventRow` from its frame."""

    async def insert_batch(self, frames: Sequence[Mapping[str, Any]]) -> None: ...

    async def head(self, machine_kind: str, entity_id: str, env: str) -> str: ...


def _ignore(_value: Any) -> None:
    return None


@dataclass(frozen=True, slots=True)
class SinkMetrics:
    """The sink's injected metric handles: each flush outcome (`ok`, `error`), which the
    composition root counts as `cv_machine_persist_ops_total{operation="event_flush"}`, and the
    WAL depth (`cv_machine_event_wal_pending`)."""

    flushed: Callable[[str], None] = _ignore
    pending: Callable[[int], None] = _ignore


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _is_utc_iso(value: object) -> bool:
    """`occurred_at` as the plugin writes it and Postgres returns it: ISO-8601 in `+00:00`."""
    if not isinstance(value, str):
        return False
    try:
        at = datetime.fromisoformat(value)
    except ValueError:
        return False
    return at.tzinfo is not None and at.astimezone(UTC).isoformat() == value


def _refusal(frame: Mapping[str, Any]) -> str | None:
    """Why `machine_events` would refuse the row, or `None`."""
    if not frame.get("entity_id"):
        return "entity_id is empty"
    if frame.get("env") not in _ENVS:
        return "env is not live, demo or testnet"
    phase = frame.get("phase")
    if phase not in _PHASES:
        return "phase is not ahead, commit or fault"
    if (phase == "fault") != (frame.get("fault") is not None):
        return "fault must be set exactly on phase fault"
    for name in ("prev_hash", "row_hash"):
        value = frame.get(name)
        if not isinstance(value, str) or _SHA256_HEX.fullmatch(value) is None:
            return f"{name} is not 64 lowercase hex"
    if not _is_utc_iso(frame.get("occurred_at")):
        return "occurred_at is not ISO-8601 in UTC (+00:00)"
    return None


def _frame(row: MachineEventRow) -> dict[str, Any]:
    """The row's WAL frame, checked; `MachineEventRejected` names what the table would refuse."""
    if not dataclasses.is_dataclass(row) or isinstance(row, type):
        raise MachineEventRejected("a machine event row must be a MachineEventRow")
    frame = dataclasses.asdict(row)
    why = _refusal(frame)
    if why is not None:
        raise MachineEventRejected(f"machine event row refused: {why}")
    try:
        body = json.dumps(frame, separators=(",", ":"), sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        error = type(exc).__name__
        raise MachineEventRejected(f"machine event row is not strict JSON ({error})") from None
    size = len(body.encode("utf-8"))
    if len(str(size)) + size + _FRAME_OVERHEAD > MAX_FRAME_BYTES:
        raise MachineEventRejected("machine event row encodes past MAX_FRAME_BYTES")
    return frame


def _is_poison(exc: Exception) -> bool:
    """A batch that can never be inserted: SQLSTATE class 22 or 23, or a frame the store adapter
    refuses before any statement. Anything else (an outage, a deadline) is retried."""
    if isinstance(exc, StorageQueryFailed):
        return (exc.sqlstate or "")[:2] in _POISON_CLASSES
    return isinstance(exc, ValueError | TypeError | KeyError)


def _lock_wal(path: Path) -> FileIO:
    """An exclusive, non-blocking lock on `<wal>.lock`, never through a symlink; closing the
    returned file drops it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW
    fd = os.open(path.with_name(path.name + ".lock"), flags, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException as exc:
        os.close(fd)
        if isinstance(exc, BlockingIOError):
            raise MachineEventUnavailable(
                "the machine-event WAL is locked by another process"
            ) from None
        raise
    return FileIO(fd, "r")


def _log_task_failure(task: asyncio.Task[None]) -> None:
    """The flusher's done-callback: anything it did not handle is logged by its type only."""
    if not task.cancelled() and task.exception() is not None:
        error = type(task.exception()).__name__
        logger().critical("machine_events.task_failed", task=task.get_name(), error=error)


class MachineEventWalSink:
    """The WAL-backed sink (see the module docstring). One per process; `start()` before the
    first `append`, `stop()` after the last."""

    def __init__(
        self,
        store: MachineEventStore,
        wal_path: str | Path,
        *,
        max_bytes: int = 64 * 1024 * 1024,
        clock: Callable[[], datetime] = _utc_now,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        metrics: SinkMetrics | None = None,
    ) -> None:
        self._store = store
        self.wal_path = Path(wal_path)
        self.max_bytes = max_bytes
        self._clock, self._sleep = clock, sleep
        self._metrics = metrics or SinkMetrics()
        self._wal: AuditWal | None = None
        self._lock: FileIO | None = None
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._accepting = False
        self._failure: BaseException | None = None
        self._append_failed_at: datetime | None = None
        #: The logical end (`_base` + offset) of each frame this process appended that Postgres
        #: does not hold yet, oldest first; one per frame, so the WAL's cap bounds it (C-2.18).
        self._uncommitted: deque[int] = deque()
        #: Bytes compactions removed from the front of the file.
        self._base = 0
        #: Each machine key's chain head, the last accepted `row_hash`; least recently used last
        #: evicted past `HEAD_KEYS_MAX` (an evicted key is seeded again before its next writer).
        self._heads: OrderedDict[tuple[str, str, str], str] = OrderedDict()

    @property
    def failure(self) -> BaseException | None:
        """Why the flusher died (`None` while healthy)."""
        return self._failure

    @property
    def pending(self) -> int:
        """Frames this process appended that Postgres does not hold yet (an earlier run's backlog
        is not in it, as `AuditWriter.buffer_depth`)."""
        return len(self._uncommitted)

    @property
    def head_count(self) -> int:
        """Machine keys whose chain head is held."""
        return len(self._heads)

    def head(self, key: ChainKey) -> str | None:
        """The key's chain head, the last accepted `row_hash`, or `None` when not held. O(1)."""
        chain = (key.machine_kind, key.entity_id, key.env)
        held = self._heads.get(chain)
        if held is not None:
            self._heads.move_to_end(chain)
        return held

    async def seed(self, key: ChainKey) -> None:
        """Hold the key's chain head before anything appends to it: at once when held; else after
        the WAL drained, from the store, both within `SEED_DRAIN_S`. `MachineEventUnavailable`
        on a timeout, a read error, a dead flusher or a sink that is not running."""
        chain = (key.machine_kind, key.entity_id, key.env)
        if chain in self._heads:
            self._heads.move_to_end(chain)
            return
        if self._failure is not None:
            raise MachineEventUnavailable(
                f"the machine-event flusher died ({type(self._failure).__name__})"
            )
        if not self._accepting:
            raise MachineEventUnavailable("the machine-event sink is not running")
        try:
            async with asyncio.timeout(SEED_DRAIN_S):
                await self._idle.wait()
                head = await self._store.head(*chain)
        except Exception as exc:
            raise MachineEventUnavailable(
                f"the machine_events head could not be read ({type(exc).__name__})"
            ) from None
        if chain not in self._heads:  # an append meanwhile holds a newer head
            self._hold(chain, head)

    def _hold(self, chain: tuple[str, str, str], head: str) -> None:
        self._heads[chain] = head
        self._heads.move_to_end(chain)
        while len(self._heads) > HEAD_KEYS_MAX:
            self._heads.popitem(last=False)

    @property
    def append_failed_at(self) -> datetime | None:
        """When the last append failed; `None` once a later append succeeded."""
        return self._append_failed_at

    @property
    def append_failure_active(self) -> bool:
        """True within `APPEND_FAILURE_COOLDOWN_S` of an unrecovered append failure."""
        failed = self._append_failed_at
        if failed is None:
            return False
        cooldown = timedelta(seconds=APPEND_FAILURE_COOLDOWN_S)
        return timedelta(0) <= self._clock() - failed < cooldown

    async def start(self) -> None:
        """Lock and open the WAL off the loop, then start the flusher, which replays the leftover
        frames first. Never waits on Postgres. `MachineEventUnavailable` if another process holds
        the WAL; a corrupt WAL raises `AuditWalCorrupt` (fail closed: the boot stops)."""
        if self._task is not None and not self._task.done():
            return
        if self._lock is None:
            self._lock = await run_in_thread(_lock_wal, self.wal_path)
        if self._wal is None:
            try:
                self._wal = await run_in_thread(AuditWal, self.wal_path, self.max_bytes)
            except BaseException:
                self._release_lock()
                raise
        self._failure = None
        self._accepting = True
        self._idle.clear()
        self._wake.set()
        self._task = spawn(self._supervised(), name="machine-events-flusher")
        self._task.add_done_callback(_log_task_failure)

    async def stop(self) -> None:
        """Stop accepting, give the flusher `STOP_GRACE_S` to drain, cancel it and drop the lock.
        What Postgres does not hold yet stays durable in the WAL for the next start."""
        self._accepting = False
        task, self._task = self._task, None
        if task is not None and not task.done():
            try:
                async with asyncio.timeout(STOP_GRACE_S):
                    await self._idle.wait()
            except TimeoutError:
                logger().warning(
                    "machine_events.stop_not_drained", pending=self.pending, grace_s=STOP_GRACE_S
                )
            task.cancel()
            await asyncio.wait({task}, timeout=STOP_GRACE_S)
        self._wal = None
        self._release_lock()

    def _release_lock(self) -> None:
        lock, self._lock = self._lock, None
        if lock is not None:
            lock.close()

    def append(self, row: MachineEventRow) -> None:
        """Durably append one row: when this returns its frame is written and `fsync`'d. Raises
        `MachineEventRejected` (nothing written) or `MachineEventUnavailable` (fail closed)."""
        if self._failure is not None:
            raise MachineEventUnavailable(
                f"the machine-event flusher died ({type(self._failure).__name__})"
            )
        wal = self._wal
        if not self._accepting or wal is None:
            raise MachineEventUnavailable("the machine-event sink is not running")
        frame = _frame(row)
        try:
            end = wal.append(frame)
        except (AuditWalFull, OSError) as exc:
            if not self.append_failure_active:  # one page per cooldown window
                logger().critical(
                    "machine_events.append_failed", cv_page=True, error=type(exc).__name__
                )
            self._append_failed_at = self._clock()
            raise MachineEventUnavailable(
                f"machine-event WAL unavailable ({type(exc).__name__})"
            ) from None
        self._append_failed_at = None
        self._hold((frame["machine_kind"], frame["entity_id"], frame["env"]), frame["row_hash"])
        self._uncommitted.append(self._base + end)
        self._metrics.pending(self.pending)
        self._idle.clear()
        self._wake.set()

    async def _supervised(self) -> None:
        try:
            await self._run()
        except Exception as exc:  # poison: fail closed, no in-process restart
            self._failure = exc
            self._metrics.flushed("error")
            logger().critical("machine_events.flusher_died", cv_page=True, error=type(exc).__name__)

    async def _run(self) -> None:
        wal = self._wal
        if wal is None:
            raise RuntimeError("the machine-event WAL is not open")
        while True:
            await self._wake.wait()  # idle until an append (or stop's cancel)
            self._wake.clear()
            await self._sleep(FLUSH_COALESCE_S)
            while batch := wal.read_window(FLUSH_BATCH_ROWS, FLUSH_WINDOW_BYTES):
                await self._insert([record for _end, record in batch])
                end = batch[-1][0]
                wal.mark_committed(end)
                self._confirm(end)
                self._metrics.flushed("ok")
                self._compact(wal)
            self._idle.set()

    async def _insert(self, frames: list[dict[str, Any]]) -> None:
        """One batch, retried with capped doubling backoff until it lands; poison is raised."""
        delay = RETRY_INITIAL_S
        while True:
            try:
                async with asyncio.timeout(INSERT_TIMEOUT_S):
                    await self._store.insert_batch(frames)
                return
            except Exception as exc:
                if _is_poison(exc):
                    raise
                self._metrics.flushed("error")
                logger().warning(
                    "machine_events.insert_failed", error=type(exc).__name__, retry_in_s=delay
                )
            await self._sleep(delay)
            delay = min(delay * 2, RETRY_MAX_S)

    def _confirm(self, end: int) -> None:
        """Every frame up to `end` is in Postgres (the flusher inserts in WAL order)."""
        position = self._base + end
        while self._uncommitted and self._uncommitted[0] <= position:
            self._uncommitted.popleft()
        self._metrics.pending(self.pending)

    def _compact(self, wal: AuditWal) -> None:
        """O(1) when nothing is pending; otherwise only a bounded copy, once the committed prefix
        is over half the cap. Runs between batches, so no read is in flight."""
        committed, end = wal.committed_offset(), wal.acknowledged_end
        if committed == 0:
            return
        bounded = committed > self.max_bytes // 2 and end - committed <= COMPACT_COPY_MAX_BYTES
        if committed == end or bounded:
            wal.compact()
            self._base += committed
