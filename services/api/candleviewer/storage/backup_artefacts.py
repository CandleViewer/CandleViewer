"""Backup artefacts, read only inside the backup root (E42-T05 BK-6a, #966 Q7 and Q8).

Verification hashes a single-file artefact before anything decrypts it, and the download link
serves it (BK-9 to BK-11, not wired yet). A catalogue `location` must be absolute and canonical
below the root (else refused before any I/O). The walk opens each component from `/`, the root's
own included, `O_NOFOLLOW` from the descriptor of the one before, so a symlink swapped in at any
step fails it; `fstat` of the descriptors then requires a regular file with one link on the
root's device. Refusals carry the contract's code only, nothing chained (C-12.6). Nothing is
logged or decrypted; each read is `CHUNK_BYTES`, in a worker thread.
"""

from __future__ import annotations

import asyncio
import contextlib
import errno
import hashlib
import os
import stat
import threading
import weakref
from collections.abc import AsyncIterator, Callable
from typing import Any, ClassVar, Final, TypeVar

from candleviewer.observability.context import thread_future

#: Bytes per read: the digest's chunk (1 MiB) and the most one streamed chunk holds.
CHUNK_BYTES: Final = 1 << 20
_T = TypeVar("_T")  # not PEP 695 `[T]`: Semgrep 1.99.0 (CI) would skip the rest of this file
#: `O_PATH`: a directory is walked, never read, so search permission is enough. With
#: `O_DIRECTORY|O_NOFOLLOW`, a symbolic link fails (`ENOTDIR`) rather than being opened itself.
_DIRECTORY: Final = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
#: `O_NONBLOCK`: a FIFO or a device never blocks the open before `fstat` refuses it.
#: `O_NOCTTY`: a terminal device never becomes the process's controlling terminal.
_FILE: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC
#: Failures of the volume or of this process, not of the location: the file may well be there.
_UNREADABLE: Final = frozenset({errno.EIO, errno.EMFILE, errno.ENFILE, errno.ENOMEM})


class ArtefactError(Exception):
    """A refusal that carries the contract's code only, never a path or an OS error (C-12.6)."""

    code: ClassVar[str]

    def __init__(self) -> None:
        super().__init__(self.code)


class ArtefactMissing(ArtefactError):
    """Missing, or not a single regular file reached inside the root without a symlink."""

    code = "artefact_missing"


class ArtefactUnreadable(ArtefactError):
    """An I/O error, or this process out of descriptors or memory: the file may well be there.
    `store_unavailable` is the contract's code for the backup volume (`deleteBackup`)."""

    code = "store_unavailable"


def _components(path: str) -> tuple[str, ...] | None:
    """The components of an absolute path in canonical form, else None."""
    parts = tuple(path.split("/")[1:])
    if not path.startswith("/") or "\x00" in path or any(p in ("", ".", "..") for p in parts):
        return None
    return parts


class ResolvedArtefact:
    """The descriptor `resolve` checked, read by `digest()` and `stream()` one read at a time and
    released exactly once, never under a read: by `close()` once no read is in flight, or by
    collection, which a read in flight prevents (its done callback holds the artefact)."""

    def __init__(self, fd: int, size: int) -> None:
        self._fd = fd
        self.size = size
        self._release = weakref.finalize(self, os.close, fd)
        self._closing = False
        self._stop = threading.Event()
        self._reading: asyncio.Future[Any] | None = None

    async def digest(self) -> str:
        """The file's SHA-256, hex: one worker-thread job reading `CHUNK_BYTES` at a time.
        Cancelled, it closes the artefact; a `close()` stops its thread within one chunk, as
        `ArtefactMissing`, never a partial digest."""
        try:
            return await self._run(_sha256, self._stop)
        except asyncio.CancelledError:
            self.close()
            raise

    async def stream(self) -> AsyncIterator[bytes]:
        """The file in `CHUNK_BYTES` chunks, one worker-thread job per read. Once started, it
        closes the artefact when it ends, fails, is cancelled or is closed; a stream never started
        leaves that to `close()`."""
        try:
            offset = 0
            while chunk := await self._run(_pread, CHUNK_BYTES, offset):
                offset += len(chunk)
                yield chunk
        finally:
            self.close()

    def close(self) -> None:
        """No read starts after this. The descriptor is released now, or when the read in flight
        returns (`_settled`); a second call does nothing."""
        self._closing = True
        self._stop.set()
        if self._reading is None or self._reading.done():
            self._release()

    def _settled(self, reading: asyncio.Future[Any]) -> None:
        """Every read's done callback, a bound method: it keeps the artefact, so its descriptor,
        alive until the read returns, then releases the descriptor if `close()` came meanwhile.
        Only for the read still current: `_run` admits a newer one once this one is done, before
        this callback runs, and that read's own callback, or `close()`, releases it."""
        if not reading.cancelled():
            reading.exception()  # retrieved: a cancelled caller never will
        if self._closing and self._reading is reading:
            self._release()

    async def _run(self, read: Callable[..., _T], *args: Any) -> _T:
        """`read(fd, *args)` in a worker thread: `thread_future` (#2250), so a cancelled caller
        leaves the read running, and its descriptor open, until it returns."""
        if self._closing or not (self._reading is None or self._reading.done()):
            raise ValueError("an artefact serves one read at a time, and none once closed")
        self._reading = reading = thread_future(read, self._fd, *args)
        reading.add_done_callback(self._settled)
        return await asyncio.shield(reading)


def _pread(fd: int, size: int, offset: int) -> bytes:
    """`os.pread`, its OS error raised as `ArtefactUnreadable` with nothing chained."""
    chunk = None
    with contextlib.suppress(OSError):
        chunk = os.pread(fd, size, offset)
    if chunk is None:
        raise ArtefactUnreadable
    return chunk


def _sha256(fd: int, stop: threading.Event) -> str:
    digest = hashlib.sha256()
    offset = 0
    while chunk := _pread(fd, CHUNK_BYTES, offset):
        if stop.is_set():
            raise ArtefactMissing
        digest.update(chunk)
        offset += len(chunk)
    return digest.hexdigest()


class LocalArtefactStore:
    """Reads single-file artefacts below `root`, the backup root, which settings check."""

    def __init__(self, root: str) -> None:
        parts = _components(root)
        if not parts:
            raise ValueError("the backup root must be an absolute path in canonical form, not /")
        self._root_parts = parts

    async def resolve(self, location: str) -> ResolvedArtefact:
        """Opens the regular file `location` names inside the root, else `ArtefactMissing` (or
        `ArtefactUnreadable`). The caller bounds the wait; if it is cancelled, the walk's file is
        closed when the walk returns."""
        parts = _components(location)
        depth = len(self._root_parts)
        if parts is None or len(parts) <= depth or parts[:depth] != self._root_parts:
            raise ArtefactMissing
        walk = thread_future(_open, parts, depth)
        try:
            fd, size = await asyncio.shield(walk)
        except asyncio.CancelledError:
            walk.add_done_callback(_close_unclaimed)
            raise
        return ResolvedArtefact(fd, size)


def _open(names: tuple[str, ...], depth: int) -> tuple[int, int]:
    """In a worker thread: the descriptor and size of the file `names` spells, kept only if it is a
    regular file with one link on the device of the root (`depth` components deep). The refusal is
    raised after the OS error is handled, so nothing is chained to it."""
    fd = size = -1
    unreadable = False
    try:
        fd, root_dev = _walk(names, depth)
        info = os.fstat(fd)
        if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_dev == root_dev:
            size = info.st_size
    except (OSError, ValueError) as error:  # ValueError: a name the OS cannot encode
        unreadable = isinstance(error, OSError) and error.errno in _UNREADABLE
    if size < 0:
        if fd >= 0:
            os.close(fd)
        raise ArtefactUnreadable if unreadable else ArtefactMissing
    return fd, size


def _walk(names: tuple[str, ...], depth: int) -> tuple[int, int]:
    """Opens the path from `/` one `O_NOFOLLOW` component at a time, each from the descriptor of
    the one before, holding one directory descriptor at a time. Returns the file's descriptor and
    the root's device, from an `fstat` of the root's descriptor."""
    directory = os.open("/", _DIRECTORY)
    root_dev = -1
    try:
        for index, name in enumerate(names[:-1], start=1):
            child = os.open(name, _DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
            if index == depth:
                root_dev = os.fstat(directory).st_dev
        return os.open(names[-1], _FILE, dir_fd=directory), root_dev
    finally:
        os.close(directory)


def _close_unclaimed(walk: asyncio.Future[tuple[int, int]]) -> None:
    """A cancelled `resolve`'s walk: the file it opened, if any, is closed when it returns."""
    if not walk.cancelled() and walk.exception() is None:
        os.close(walk.result()[0])
