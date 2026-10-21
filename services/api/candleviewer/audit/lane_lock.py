"""`lane.lock`, taken through descriptors (ADR-0037 decision 9; SEC-REM-03 on #3009).

cv-api's `lock_lane` and S2c's release command take it here. The audit directory (that of
`CV_AUDIT_WAL_PATH`) is opened `O_DIRECTORY | O_NOFOLLOW`, `lane/` relative to its descriptor and
`lane.lock` relative to `lane/`'s, as `storage/backup_artefacts.py` walks a location: no path is
checked before its open, so a symlink swapped in after a check is never followed. A symlink or a
file where either directory should be fails its open with `ENOTDIR`, and a symlink where the lock
should be with `ELOOP`: each is `LaneUnanchored`, as are a relative WAL path and one with `..`,
and its message names the component, never its path. Another holder is `BlockingIOError`; any
other error is raised as it is. Each caller maps them: boot refused, lane held, exit status.

Only these three opens are anchored to descriptors: `LaneFiles` and the release command's own
file operations still name paths under `lane/`, so whoever swaps `lane/` while they run can
redirect them. That takes cv-api's uid or root, the residual RR-01 accepts (ADR-0037).
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
from pathlib import Path

from candleviewer.audit import lane_journal as lj

#: Decision 9: held exclusively by the one running cv-api; S2c's release command takes it too.
LOCK_FILE = "lane.lock"
#: Read, not `O_PATH`: the audit directory is fsynced once `lane/` is made in it.
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY
#: `O_NONBLOCK`: a FIFO in the lock's place never blocks the open (cv-api takes it on the loop).
_LOCK = os.O_RDONLY | os.O_CREAT | os.O_NONBLOCK
#: The refusal of an open that met a symlink or a file, by the directories open before it:
#: fixed words that name the component, never its path.
_UNANCHORED = (
    "the audit directory is a symlink or not a directory",
    "lane/ is a symlink or not a directory",
    "lane.lock is a symlink",
)


class LaneUnanchored(lj.LaneError):
    """Decision 9: the WAL path is relative or has `..`, a symlink is where the audit directory,
    `lane/` or `lane.lock` should be, or a file is where either directory should be."""


def take_lane_lock(audit_wal_path: str, *, create: bool) -> int:
    """`lane.lock`'s descriptor, locked exclusively without waiting; closing it drops the lock.
    With `create` (cv-api only) a missing `lane/` is made `0700`, then the audit directory is
    fsynced; the lock is made `0600` if missing. Every open is `O_NOFOLLOW | O_CLOEXEC`, and on
    every path each descriptor but the one returned is closed."""
    raw, opened = Path(audit_wal_path), list[int]()
    if not raw.is_absolute() or ".." in raw.parts:
        raise LaneUnanchored("CV_AUDIT_WAL_PATH must be absolute and free of '..'")
    try:
        opened.append(lj._open(raw.parent, _DIRECTORY))
        if create:
            with contextlib.suppress(FileExistsError):
                os.mkdir("lane", 0o700, dir_fd=opened[0])
                os.fsync(opened[0])
        opened.append(lj._open("lane", _DIRECTORY, opened[0]))
        fd = lj._open(LOCK_FILE, _LOCK, opened[1])
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR):
            raise LaneUnanchored(_UNANCHORED[len(opened)]) from exc
        raise
    finally:
        for directory in opened:
            os.close(directory)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        os.close(fd)
        raise
    return fd
