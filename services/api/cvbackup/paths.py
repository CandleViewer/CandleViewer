"""Root confinement on the backup volume (ADR-0041 section 3), a mirror of the API's
`storage/backup_artefacts.py` walk, which the sidecar may not import.

Every path is absolute and canonical below the root, or refused before any I/O. A walk opens each
component from `/` with `O_NOFOLLOW`, from the descriptor of the one before, so a symbolic link
swapped in at any step fails it; everything below the root must be on the root's device. Errors
carry a fixed code only, never a path or an OS error's text.

Layout: `<root>/<kind>/<uuid4>.age` artefacts; `<root>/.cvb/` the run record (`ledger.py`);
`<root>/.quarantine/` removed artefacts awaiting their purge (`floor.py`).
"""

from __future__ import annotations

import contextlib
import errno
import os
import stat
from collections.abc import Iterable, Iterator
from typing import Final

from cvbackup import protocol

LEDGER_DIR: Final = ".cvb"
QUARANTINE_DIR: Final = ".quarantine"
_DIRECTORY: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_NOCTTY | os.O_CLOEXEC
#: Faults of the volume or of this process, not of the path: the file may well be there.
_VOLUME: Final = frozenset({
    errno.EIO, errno.EMFILE, errno.ENFILE, errno.ENOMEM, errno.ENOSPC, errno.EROFS, errno.EDQUOT,
    errno.EXDEV, errno.EACCES, errno.EPERM,
})  # fmt: skip


class PathFault(Exception):
    """`code`: `artefact_missing` (nothing usable at the path) or `volume_unavailable`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _fault(error: OSError) -> PathFault:
    return PathFault("volume_unavailable" if error.errno in _VOLUME else "artefact_missing")


def components(path: str) -> tuple[str, ...] | None:
    """The components of an absolute path in canonical form, else None."""
    parts = tuple(path.split("/")[1:])
    if not path.startswith("/") or "\x00" in path or any(p in ("", ".", "..") for p in parts):
        return None
    return parts


def is_artefact_name(name: str) -> bool:
    """`<uuid>.age`, so one component: never `.`, `..`, a `/` or a hidden name."""
    return name.endswith(".age") and protocol.is_uuid(name[:-4])


class Root:
    """The backup root, walked component by component for every access."""

    def __init__(self, root: str) -> None:
        parts = components(root)
        if not parts:
            raise ValueError("the backup root must be an absolute path in canonical form, not /")
        self.path = root
        self._parts = parts

    def relative(self, location: str) -> tuple[str, ...] | None:
        """`location`'s components below the root, else None."""
        parts = components(location)
        depth = len(self._parts)
        if parts is None or len(parts) <= depth or parts[:depth] != self._parts:
            return None
        return parts[depth:]

    def artefact(self, location: str) -> tuple[str, str]:
        """`location`'s kind and file name: exactly `<root>/<kind>/<uuid>.age` (24 §15.8), never
        deeper (the quarantine, the run record), else `artefact_missing` before any I/O."""
        below = self.relative(location)
        if below is None or len(below) != 2 or not protocol.is_kind(below[0]):
            raise PathFault("artefact_missing")
        if not is_artefact_name(below[1]):
            raise PathFault("artefact_missing")
        return below[0], below[1]

    @contextlib.contextmanager
    def directory(self, below: Iterable[str] = ()) -> Iterator[int]:
        """A descriptor of the directory `below` names under the root, closed on exit."""
        fd = self._walk(tuple(below))
        try:
            yield fd
        finally:
            os.close(fd)

    def _walk(self, below: tuple[str, ...]) -> int:
        try:
            fd = os.open("/", _DIRECTORY)
        except OSError as error:
            raise _fault(error) from None
        device = -1
        try:
            for index, name in enumerate((*self._parts, *below), start=1):
                child = os.open(name, _DIRECTORY, dir_fd=fd)
                os.close(fd)
                fd = child
                here = os.fstat(fd).st_dev
                if index == len(self._parts):
                    device = here
                elif index > len(self._parts) and here != device:
                    raise OSError(errno.EXDEV, "another device")
        except OSError as error:
            os.close(fd)
            raise _fault(error) from None
        return fd

    def ensure(self, names: Iterable[str]) -> None:
        """Each directory in `names` directly under the root, created 0700 when missing."""
        with self.directory() as root:
            for name in names:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(name, 0o700, dir_fd=root)
                with self.directory((name,)):
                    pass  # a directory reached without a link, on the root's device

    def open_artefact(self, location: str) -> tuple[int, int]:
        """A read descriptor and the size of the regular file `location` names, with one link,
        on the root's device, else `PathFault`."""
        kind, name = self.artefact(location)
        with self.directory((kind,)) as parent:
            device = os.fstat(parent).st_dev
            try:
                fd = os.open(name, _FILE, dir_fd=parent)
            except OSError as error:
                raise _fault(error) from None
        info = os.fstat(fd)
        if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_dev == device:
            return fd, info.st_size
        os.close(fd)
        raise PathFault("artefact_missing")

    def quarantine(self, location: str, name: str) -> bool:
        """Rename `location` into the quarantine as `name`, at once, with its bytes kept; both
        directories are synced. False when nothing is at `location`. `name` is one artefact
        name (`is_artefact_name`), else `artefact_missing` before any I/O."""
        kind, below = self.artefact(location)
        if not is_artefact_name(name):
            raise PathFault("artefact_missing")
        with self.directory((kind,)) as parent, self.directory((QUARANTINE_DIR,)) as kept:
            try:
                info = os.lstat(below, dir_fd=parent)
            except FileNotFoundError:
                return False
            except OSError as error:
                raise _fault(error) from None
            if not stat.S_ISREG(info.st_mode):
                raise PathFault("artefact_missing")
            try:
                os.lstat(name, dir_fd=kept)
            except FileNotFoundError:
                pass
            else:
                raise PathFault("volume_unavailable")  # a name already taken: never replaced
            try:
                os.rename(below, name, src_dir_fd=parent, dst_dir_fd=kept)
                os.fsync(parent)
                os.fsync(kept)
            except OSError as error:
                raise _fault(error) from None
        return True

    def purge(self, name: str) -> None:
        """Delete `name` from the quarantine; one already gone counts as purged. `name` is one
        artefact name (`is_artefact_name`), else `artefact_missing` before any I/O."""
        if not is_artefact_name(name):
            raise PathFault("artefact_missing")
        with self.directory((QUARANTINE_DIR,)) as kept:
            try:
                os.unlink(name, dir_fd=kept)
                os.fsync(kept)
            except FileNotFoundError:
                return
            except OSError as error:
                raise _fault(error) from None

    def exists(self, location: str) -> bool:
        kind, name = self.artefact(location)
        with self.directory((kind,)) as parent:
            try:
                os.lstat(name, dir_fd=parent)
            except FileNotFoundError:
                return False
            except OSError as error:
                raise _fault(error) from None
        return True
