"""`MachineEventWalSink`: the durable, synchronous `machine_events` sink (E50-T63, M19).

`CvAuditPlugin`'s hooks cannot await, so `append(row)` cannot call the async events store. The
sink follows `wal.py` and `AuditWriter` (acceptance is durability; the WAL is the buffer; never
lossy; fail closed) and reuses `AuditWal` (24-internal-schemas.md §17.6):

- `append` writes and `fsync`s one self-validating frame on the calling loop thread before it
  returns: one small frame of lifecycle-rate traffic, no network I/O (C-2.17, C-2.20). A row the
  table would refuse, or whose frame is over `MAX_FRAME_BYTES`, raises `MachineEventRejected` and
  writes nothing, so it never becomes a poison row: `occurred_at` must be the `+00:00` UTC form the
  row digest covers, the frame strict JSON (`json` refuses NaN and the infinities), and the CHECKs
  of `machine_events` and `sha256_hex` must hold. A rejection is counted (`event_flush`,
  `refused`); the plugin's CRITICAL line for it is a page.
- One supervised flusher, woken by `append`, waits `FLUSH_COALESCE_S`, reads one window
  (`AuditWal.read_window`: at most `FLUSH_BATCH_ROWS` rows and `FLUSH_WINDOW_BYTES`), inserts it
  (idempotent on `row_hash`), commits the cursor, and compacts only when that is O(1) (nothing
  pending) or a copy of at most `COMPACT_COPY_MAX_BYTES` (the committed prefix over half the cap).
  Every WAL call is bounded and runs on the loop thread; every await has a deadline. An outage, or
  a statement error of any SQLSTATE class but 22 and 23, retries with capped doubling backoff: the
  WAL is the buffer, so an outage with room in it loses nothing and blocks nothing. A data
  exception or integrity violation (class 22 or 23), a frame the store adapter refuses, or a
  corrupt frame is poison: the flusher stops (no in-process restart, as in `AuditWriter`), a P1
  page goes out (a CRITICAL `cv_page=true` line) and every later `append` fails closed. So does
  any error a WAL call raises (`read_window`, `mark_committed`, `compact`), an `OSError` such as
  ENOSPC included: the flusher fails closed rather than retry a disk it cannot trust, and the WAL
  keeps every accepted row for the next start. An insert that keeps failing without a commit for
  `FLUSH_STALL_PAGE_S` pages once per such window (the WAL has room, so `append` would not page
  until it fills). A frame declared larger than `MAX_FRAME_BYTES` is corruption, refused unread.
- `append` raises `MachineEventUnavailable` when the WAL is full or unwritable, the flusher has
  died or the sink is not running; the plugin counts it (`sink_failures`), logs and re-raises, and
  the machine keeps running. A full or unwritable WAL pages once per `APPEND_FAILURE_COOLDOWN_S`
  window (`machine_events.append_failed`), and so does a sink that is not running, before `start()`
  or after `stop()` (`machine_events.append_refused_not_running`, a refused `seed` included): its
  rows are lost audit rows that nothing else pages. A dead flusher paged once, as it died.
  A known bound, the ticket's policy: compaction runs only between batches, so a WAL whose
  committed prefix is reclaimable but whose remainder stays above `COMPACT_COPY_MAX_BYTES` (Postgres
  up but slower than the appends) still reaches its cap and fails closed until a batch compacts.
- The failure latch is `AuditWriter`'s (#2510): `append_failure_active` is true for
  `APPEND_FAILURE_COOLDOWN_S` after a failed append and false afterwards even if nothing appended
  since (a clock stepped back reads as expired). It never refuses an append and never waits for
  one; the next append re-probes the WAL. Its consumer is the order family's (E29-T03).
- `start()` takes an exclusive lock on `<wal>.lock` (one writer per file) and opens the WAL, whose
  open scans the whole file, in a worker thread, where the WAL and its cursor are made owner-only
  (0600: they hold the table's P1 payloads; a commit or a compaction replaces the files, so it is
  re-applied after each); the flusher then replays the leftover frames. It never waits on
  Postgres. `stop()` stops accepting, drains for at most `STOP_GRACE_S` and leaves the rest
  durable in the WAL, replayed at the next start (a kill during the drain loses nothing).
- Chain continuity: one hash chain per machine key, advanced by every writer (the audit plugin
  and the fault-row writers) and continuous across restarts. `head(key)` is the last accepted
  `row_hash`, O(1) from a map bounded at `HEAD_KEYS_MAX` (least recently used evicted).
  `seed(key)` returns at once for a held key; otherwise it waits for the WAL to drain (rows of the
  key may still be in it) and reads the head through the store, both within `SEED_DRAIN_S`; a
  timeout or a read error raises `MachineEventUnavailable`, so no machine starts a chain that
  could fork. It is awaited before a restore calls `plugins(key)`, before an owner builds a
  machine, and by the fault-row writers before they build a row.
- A live machine whose key was evicted is not re-seeded automatically: `CvAuditPlugin` fails
  closed on a head it saw held and no longer finds, so each of its rows is refused, and paged,
  until a fault-row write for the key or its owner's `seed(key)` holds the head again. Owners that
  adopt `plugins_for` keep their long-lived machines' keys resident until the keys that have a
  live plugin are pinned (review round 2, a follow-up).

A sink serves one event loop (D6, #913 L2): the one it was built on, or, built outside one (the
persistence bundle's, as `main.py` builds the app at import), the one its `start()` runs on, which
alone binds it (SEC-S3L2-07): until then every other call is refused, from any loop, so a first
caller elsewhere never takes it. `append`, `head`, `seed`, `start` and `stop` each refuse a call
from any other loop, or from a thread that runs none, with `MachineEventWrongLoop` before anything
is read or written; the first refusal of each `APPEND_FAILURE_COOLDOWN_S` window, on the sink's
clock, is logged CRITICAL as a page (CR-S3L2-08). The order lane (29 CV-C13) has a sink of its
own, on its own loop and WAL file, besides any the serving loop holds (E29-T04's ruling Q13).

Rows are dataclass instances and frames the dicts `dataclasses.asdict` gives. `MachineEventRow`
lives in `statechart/plugins/audit.py` and is named here for annotations only: a run-time import
would load the statechart runtime into M19.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import re
import threading
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import FileIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Protocol

import structlog

from candleviewer.audit.errors import AuditError
from candleviewer.audit.wal import AuditWal, AuditWalFull, AuditWalLocked, lock_wal_file
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
#: Inserts failing for this long with no commit page, once per such window (review round 1).
FLUSH_STALL_PAGE_S: Final = 60.0
#: The WAL's and its cursor's mode: owner-only.
_OWNER_ONLY: Final = 0o600

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


class MachineEventWrongLoop(MachineEventUnavailable):
    """A call from an event loop other than the sink's own, or from a thread that runs none:
    refused before anything is read or written (D6, fail closed), a wiring defect that pages."""


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


def _running_loop() -> asyncio.AbstractEventLoop | None:
    """The event loop running on this thread, or `None`."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


@dataclass(frozen=True, slots=True)
class SinkMetrics:
    """The sink's injected metric handles: each outcome, which the composition root counts as
    `cv_machine_persist_ops_total{operation="event_flush"}` (`ok`: a batch committed; `error`: an
    insert failed, or the flusher stopped; `refused`: a row rejected at `append`), and the WAL
    depth (`cv_machine_event_wal_pending`)."""

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
    """`lock_wal_file`'s exclusive lock on `<wal>.lock`; another holder is unavailability."""
    try:
        return lock_wal_file(path)
    except AuditWalLocked:
        refused = "the machine-event WAL is locked by another process"
        raise MachineEventUnavailable(refused) from None


def _owner_only(path: Path) -> None:
    """The WAL and its cursor, 0600 (they hold the table's P1 payloads)."""
    for file in (path, path.with_suffix(path.suffix + ".committed")):
        if file.exists():
            os.chmod(file, _OWNER_ONLY)


def _open_wal(path: Path, max_bytes: int) -> AuditWal:
    """Open (and scan) the WAL in a worker thread, owner-only."""
    wal = AuditWal(path, max_bytes)
    _owner_only(path)
    return wal


def frames_left(wal_path: str | Path, max_bytes: int) -> int:
    """The bytes of frames the `machine_events` WAL at `wal_path` holds past its commit cursor,
    which Postgres has not taken (#913 L2, SEC-S3L2-03), for a WAL no sink of this process holds:
    0 with no file. Read under the WAL's lock and its open's scan, as `start()` reads them (a torn
    tail cut, a corrupt frame `AuditWalCorrupt`); `MachineEventUnavailable` while another process
    holds the file. Blocking: run it off the loop."""
    path = Path(wal_path)
    if not path.exists():
        return 0
    with _lock_wal(path):
        wal = _open_wal(path, max_bytes)
        return max(0, wal.acknowledged_end - wal.committed_offset())


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
        #: D6: the event loop the sink serves, the one it was built on, else the one its `start()`
        #: binds (`_on_its_loop`, SEC-S3L2-07); when a refusal from another loop last paged, and
        #: the lock the refusing threads take to read and set it (CR-S3L2-08), which a binding
        #: `start()` takes too.
        self._loop = _running_loop()
        self._wrong_loop_paged_at: datetime | None = None
        self._wrong_loop_guard = threading.Lock()
        self._wal: AuditWal | None = None
        self._lock: FileIO | None = None
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._idle = asyncio.Event()
        self._accepting = False
        self._failure: BaseException | None = None
        self._append_failed_at: datetime | None = None
        #: When a refusal by a sink that is not running last paged (`_not_running`).
        self._not_running_paged_at: datetime | None = None
        #: The logical end (`_base` + offset) of each frame this process appended that Postgres
        #: does not hold yet, oldest first; one per frame, so the WAL's cap bounds it (C-2.18).
        self._uncommitted: deque[int] = deque()
        #: Bytes compactions removed from the front of the file.
        self._base = 0
        #: Since when inserts fail with no commit, and when that last paged (`_insert`).
        self._stalled_since: datetime | None = None
        self._stall_paged_at: datetime | None = None
        #: Each machine key's chain head, the last accepted `row_hash`; the least recently used is
        #: evicted past `HEAD_KEYS_MAX`. Nothing re-seeds an evicted key by itself: its live plugin
        #: fails closed until a fault-row write or the owner's `seed` holds the head again.
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

    def _on_its_loop(self, *, binds: bool = False) -> None:
        """D6: a call from any loop but the sink's own, or from none, is `MachineEventWrongLoop`,
        before anything is read or written, the first of each `APPEND_FAILURE_COOLDOWN_S` window
        on the sink's clock paged, as `_not_running` pages (CR-S3L2-08). A sink built outside a
        loop serves the loop of the first call that `binds`, its `start()`, taken under the guard
        so two loops never both take it (SEC-S3L2-07); before that every call is refused, so a
        first caller elsewhere never takes it."""
        running = _running_loop()
        if binds and running is not None and self._loop is None:
            with self._wrong_loop_guard:
                if self._loop is None:
                    self._loop = running
        if running is None or running is not self._loop:
            now, cooldown = self._clock(), timedelta(seconds=APPEND_FAILURE_COOLDOWN_S)
            with self._wrong_loop_guard:
                paged, first = self._wrong_loop_paged_at, False
                if paged is None or not timedelta(0) <= now - paged < cooldown:
                    self._wrong_loop_paged_at, first = now, True
            if first:
                logger().critical("machine_events.wrong_loop", cv_page=True)
            raise MachineEventWrongLoop("the machine-event sink serves another event loop")

    def head(self, key: ChainKey) -> str | None:
        """The key's chain head, the last accepted `row_hash`, or `None` when not held. O(1)."""
        self._on_its_loop()
        chain = (key.machine_kind, key.entity_id, key.env)
        held = self._heads.get(chain)
        if held is not None:
            self._heads.move_to_end(chain)
        return held

    async def seed(self, key: ChainKey) -> None:
        """Hold the key's chain head before anything appends to it: at once when held; else after
        the WAL drained, from the store, both within `SEED_DRAIN_S`. `MachineEventUnavailable`
        on a timeout, a read error, a dead flusher or a sink that is not running."""
        self._on_its_loop()
        chain = (key.machine_kind, key.entity_id, key.env)
        if chain in self._heads:
            self._heads.move_to_end(chain)
            return
        if self._failure is not None:
            raise MachineEventUnavailable(
                f"the machine-event flusher died ({type(self._failure).__name__})"
            )
        if not self._accepting:
            raise self._not_running("seed")
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

    def _not_running(self, operation: str) -> MachineEventUnavailable:
        """The refusal of a sink that is not running (before `start()`, after `stop()`): the row,
        or the chain a seed was for, is lost and nothing else pages it, so the first refusal of
        each `APPEND_FAILURE_COOLDOWN_S` window, `append`'s or `seed`'s, logs one CRITICAL
        `cv_page` line by the operation (review round 2), on the injected clock (a clock stepped
        back reads as expired). The window spans restarts: `start()` does not reset it.
        `append_failure_active` stays the WAL's, as `AuditWriter`'s."""
        now, paged = self._clock(), self._not_running_paged_at
        cooldown = timedelta(seconds=APPEND_FAILURE_COOLDOWN_S)
        if paged is None or not timedelta(0) <= now - paged < cooldown:
            self._not_running_paged_at = now
            logger().critical(
                "machine_events.append_refused_not_running", cv_page=True, operation=operation
            )
        return MachineEventUnavailable("the machine-event sink is not running")

    async def start(self) -> None:
        """Lock and open the WAL off the loop, then start the flusher, which replays the leftover
        frames first. Never waits on Postgres. `MachineEventUnavailable` if another process holds
        the WAL; a corrupt WAL raises `AuditWalCorrupt` (fail closed: the boot stops). A sink
        built outside a loop is bound to this call's here (SEC-S3L2-07)."""
        self._on_its_loop(binds=True)
        if self._task is not None and not self._task.done():
            return
        if self._lock is None:
            self._lock = await run_in_thread(_lock_wal, self.wal_path)
        if self._wal is None:
            try:
                self._wal = await run_in_thread(_open_wal, self.wal_path, self.max_bytes)
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
        self._on_its_loop()
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
        self._on_its_loop()
        if self._failure is not None:
            raise MachineEventUnavailable(
                f"the machine-event flusher died ({type(self._failure).__name__})"
            )
        wal = self._wal
        if not self._accepting or wal is None:
            raise self._not_running("append")
        try:
            frame = _frame(row)
        except MachineEventRejected:
            self._metrics.flushed("refused")
            raise
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
            while batch := wal.read_window(
                FLUSH_BATCH_ROWS, FLUSH_WINDOW_BYTES, max_frame=MAX_FRAME_BYTES
            ):
                await self._insert([record for _end, record in batch])
                end = batch[-1][0]
                wal.mark_committed(end)
                self._confirm(end)
                self._metrics.flushed("ok")
                self._compact(wal)
                _owner_only(self.wal_path)  # the commit and a compaction replaced the files
            self._idle.set()

    async def _insert(self, frames: list[dict[str, Any]]) -> None:
        """One batch, retried with capped doubling backoff until it lands; poison is raised."""
        delay = RETRY_INITIAL_S
        while True:
            try:
                async with asyncio.timeout(INSERT_TIMEOUT_S):
                    await self._store.insert_batch(frames)
                self._stalled_since = self._stall_paged_at = None
                return
            except Exception as exc:
                if _is_poison(exc):
                    raise
                self._metrics.flushed("error")
                logger().warning(
                    "machine_events.insert_failed", error=type(exc).__name__, retry_in_s=delay
                )
                self._page_if_stalled(exc)
            await self._sleep(delay)
            delay = min(delay * 2, RETRY_MAX_S)

    def _page_if_stalled(self, exc: Exception) -> None:
        """Inserts failing for `FLUSH_STALL_PAGE_S` with no commit: one CRITICAL `cv_page=true`
        line per such window, by the error's type (the injected clock decides)."""
        now = self._clock()
        since = self._stalled_since
        if since is None:
            self._stalled_since = now
            return
        window = timedelta(seconds=FLUSH_STALL_PAGE_S)
        paged = self._stall_paged_at
        if now - since >= window and (paged is None or now - paged >= window):
            self._stall_paged_at = now
            logger().critical(
                "machine_events.flush_stalled",
                cv_page=True,
                error=type(exc).__name__,
                failing_for_s=round((now - since).total_seconds(), 1),
                pending=self.pending,
            )

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
