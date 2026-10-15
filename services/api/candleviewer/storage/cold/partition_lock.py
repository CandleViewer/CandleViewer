"""Per-partition writer lock for the cold tier (E16-T10 review #2217).

Every cold-tier writer that allocates a `part-NNNN` name, sweeps orphan parts or rewrites a
manifest takes this lock for the partition directory first: the exporter (roll-off), the
compactor, the downsampler and the archive importer. Without it, one writer's orphan sweep can
delete another's renamed-but-not-yet-manifested part, and two writers can pick the same part
number from the same manifest snapshot.

Process-local (`asyncio.Lock` per resolved partition path, created on demand). The app runs
one writer process per cold root (SR-096 single-writer volume); a cross-process guard would be
the Postgres advisory lock the reaper uses (`storage.retention.locks`).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from candleviewer.observability import spawn
from candleviewer.observability.context import run_in_thread

_LOCKS: dict[str, asyncio.Lock] = {}


def _key(partition_dir: Path) -> str:
    return str(partition_dir.resolve(strict=False))


@asynccontextmanager
async def partition_write_lock(partition_dir: Path) -> AsyncIterator[None]:
    """Serialise every cold writer on one partition directory."""
    lock = _LOCKS.setdefault(_key(partition_dir), asyncio.Lock())
    async with lock:
        yield


def is_locked(partition_dir: Path) -> bool:
    lock = _LOCKS.get(_key(partition_dir))
    return lock is not None and lock.locked()


async def run_locked_to_completion[T](
    partition_dir: Path, work: Callable[[], T], *, acquire_timeout_s: float
) -> T:
    """Acquire the partition lock within `acquire_timeout_s` (TimeoutError otherwise, nothing
    started), then run `work` in a thread and keep the lock until it has FINISHED, even if the
    caller is cancelled meanwhile (E16-T06 review M2): a destructive op never outlives its lock,
    so no other writer can enter a directory that is still being removed."""
    lock = _LOCKS.setdefault(_key(partition_dir), asyncio.Lock())
    async with asyncio.timeout(acquire_timeout_s):
        await lock.acquire()
    fut = spawn(run_in_thread(work), name="cold-partition-delete")
    fut.add_done_callback(lambda _f: lock.release())
    return await asyncio.shield(fut)
