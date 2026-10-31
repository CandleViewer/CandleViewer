"""The recorder chaos suite's real-filesystem leg (E16-Q04, C-13.6 #13; BQ-5 as re-ruled on #5259).

The PR lane runs the ladder over `VirtualVolume` (sized files under `tmp_path`, the "mount layer
faked in unit tests"). The nightly also runs it over a real, fixed-size ext4 loopback image that
`chaos-recorder-nightly.yml` creates and mounts with sudo, as the storage chaos stack does
(`tests/chaos/storage/_stack.py` `CV_CHAOS_LOOPBACK_DIR`), so free space is the kernel's and a
full volume is a real `ENOSPC`.

Guards, in order:
- `CV_CHAOS_LOOPBACK` unset (or not `1`): the leg is skipped. Local runs and the PR lane never
  mount anything, so they never reach it.
- set, but the directory is not the mount point of a `/dev/loop*` device, or the filesystem is
  larger than `LOOP_MAX_BYTES`: the test FAILS (`RuntimeError`), never skips: a misconfigured
  nightly must go red rather than fill some other disk.
"""

from __future__ import annotations

import errno
import os
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

import pytest

from tests.chaos.recorder._volume import VirtualVolume

ENABLE_ENV: Final = "CV_CHAOS_LOOPBACK"
DIR_ENV: Final = "CV_CHAOS_LOOPBACK_DIR"
DEFAULT_DIR: Final = Path("/mnt/cv-chaos-recorder")
#: The nightly's image is 64 MiB; anything bigger is not the chaos image.
LOOP_MAX_BYTES: Final = 64 * 1024 * 1024
_MOUNTINFO: Final = Path("/proc/self/mountinfo")


def _unescape(field: str) -> str:
    """mountinfo octal-escapes space, tab, newline and backslash."""
    for code, char in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
        field = field.replace(code, char)
    return field


def mount_source(path: Path, mountinfo: str) -> str | None:
    """The source device of the mount whose mount point is exactly `path`, if any (the last
    one listed wins, as the kernel stacks mounts)."""
    found: str | None = None
    for line in mountinfo.splitlines():
        left, sep, right = line.partition(" - ")
        fields, tail = left.split(), right.split()
        if not sep or len(fields) < 5 or len(tail) < 2:
            continue
        if Path(_unescape(fields[4])) == path:
            found = tail[1]
    return found


def check_loopback(path: Path, *, mountinfo: str, total_bytes: int) -> None:
    """Refuse (`RuntimeError`) anything but a small loop-device mount point (see module)."""
    source = mount_source(path, mountinfo)
    if source is None or not source.startswith("/dev/loop"):
        raise RuntimeError(f"{path} is not a loopback mount (source {source!r}); refusing to fill")
    if total_bytes > LOOP_MAX_BYTES:
        raise RuntimeError(f"{path} is {total_bytes} bytes; not the chaos loopback image")


def loopback_dir() -> Path:
    """The verified loopback mount, or a skip when the leg is not enabled (see module)."""
    if os.environ.get(ENABLE_ENV) != "1":
        pytest.skip(f"the real loopback leg runs in the nightly only ({ENABLE_ENV}=1)")
    mount = Path(os.environ.get(DIR_ENV, str(DEFAULT_DIR))).resolve()
    mountinfo = _MOUNTINFO.read_text(encoding="utf-8")
    check_loopback(mount, mountinfo=mountinfo, total_bytes=shutil.disk_usage(mount).total)
    return mount


@contextmanager
def scratch(mount: Path) -> Iterator[Path]:
    """A fresh directory on the image, removed afterwards, pass or fail."""
    root = mount / f"recorder-{uuid.uuid4().hex}"
    root.mkdir()
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


class LoopbackVolume(VirtualVolume):
    """`VirtualVolume` whose free space is the kernel's. Its size is what the image can hold for
    files when it is created (free + the files already under `root`, ext4's own metadata
    excluded), so a fill to N % of it leaves about 100 - N % of the real filesystem free; block
    rounding moves that by well under one percent."""

    def __init__(self, root: Path, *, mount: Path) -> None:
        super().__init__(root, 1, tmp_root=mount)
        free = shutil.disk_usage(self.root).free
        self.total = (free + super().used()) // 100 * 100

    def free(self) -> int:
        return shutil.disk_usage(self.root).free


def fill_completely(path: Path) -> int:
    """Write `path` until the filesystem refuses with `ENOSPC`; returns the bytes written."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    written = 0
    try:
        for size in (1 << 20, 1 << 12, 1):
            chunk = b"\0" * size
            while True:
                try:
                    n = os.write(fd, chunk)
                except OSError as exc:
                    if exc.errno != errno.ENOSPC:
                        raise
                    break
                written += n
                if n < size:
                    break
        os.fsync(fd)
    finally:
        os.close(fd)
    return written
