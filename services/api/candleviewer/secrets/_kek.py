"""KEK loader (E27-K01 §3-§5, ADR-0009). Private to M2: never re-exported.

The KEK arrives through exactly one path, `CV_KEK_HANDLE`, and never enters `os.environ` or
`Settings`. Sources: `handle` (read-once FIFO / systemd credential), `file` (dev/ci only;
refused in live), `none` (always degraded). In live a `handle` must be a FIFO (WSL launcher;
nonce-ack mandatory) or a systemd credential: a regular file under `/run/credentials/` whose
opened fd is on tmpfs/ramfs (`fstatfs`). Blocking I/O: callers run `load()` in a worker thread.
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import os
import re
import resource
import select
import stat
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn, Protocol
from uuid import UUID

from candleviewer.secrets import _envelope as env
from candleviewer.secrets.errors import KekLoadError, KekUnavailable

_KCV_LABEL = b"cv-kek-kcv-v1"
_NONCE_RE = re.compile(r"^[A-Za-z0-9-]{8,128}$")
_HANDOFF_NAME = "handoff"
_HANDOFF_MAX = 256
#: systemd `LoadCredential*=` directory; a live regular-file KEK must live here *and* on RAM fs.
LIVE_FILE_PREFIX = "/run/credentials/"
_PR_SET_DUMPABLE, _PR_GET_DUMPABLE = 4, 3


class LoadedKek:
    """32 KEK bytes in memory. Renders as `***`; not picklable; `close()` zeroes."""

    __slots__ = ("_closed", "_key", "is_fifo", "version")

    def __init__(self, key: bytearray, version: int, *, is_fifo: bool = False) -> None:
        if len(key) != env.KEY_LEN:
            raise KekLoadError("kek_unavailable")
        self._key = key
        self.version = version
        self.is_fifo = is_fifo
        self._closed = False

    def _live_key(self) -> bytearray:
        if self._closed:
            raise KekUnavailable("kek_unavailable")
        return self._key

    def __repr__(self) -> str:
        return "***"

    __str__ = __repr__

    def __reduce_ex__(self, protocol: object) -> NoReturn:
        raise TypeError("LoadedKek cannot be pickled")

    def kcv(self) -> bytes:
        return hmac.new(bytes(self._live_key()), _KCV_LABEL, hashlib.sha256).digest()[:8]

    def wrap_dek(self, dek: bytearray, *, credential_id: UUID) -> str:
        return (
            "v1:" + env.seal(self._live_key(), dek, env.dek_aad(credential_id, self.version)).hex()
        )

    def unwrap_dek(self, dek_ref: str, *, credential_id: UUID) -> bytearray:
        """`InvalidTag` on wrong KEK / row / version; `ValueError` on shape."""
        prefix, _, body = dek_ref.partition(":")
        if prefix != "v1":
            raise ValueError("unsupported dek_ref")
        aad = env.dek_aad(credential_id, self.version)
        return env.open_(self._live_key(), bytes.fromhex(body), aad)

    def close(self) -> None:
        self._closed = True
        env.zero(self._key)


class KekSource(Protocol):
    def load(self) -> LoadedKek: ...


def kcv_matches(kek: LoadedKek, expected: bytes) -> bool:
    return hmac.compare_digest(kek.kcv(), expected)


def _check_mode(st: os.stat_result, *, allow_fifo: bool, file_mode: int = 0o400) -> None:
    mode = stat.S_IMODE(st.st_mode)
    ok = (stat.S_ISREG(st.st_mode) and mode == file_mode) or (
        allow_fifo and stat.S_ISFIFO(st.st_mode) and mode == 0o600
    )
    if not ok or st.st_uid != os.geteuid():
        raise KekLoadError("kek_handle_permissions")


def _read_exact(fd: int, deadline: float, clock: Callable[[], float]) -> bytearray:
    buf = bytearray()
    while len(buf) <= env.KEY_LEN:
        remaining = deadline - clock()
        if remaining <= 0:
            break
        ready, _, _ = select.select([fd], [], [], min(remaining, 0.05))
        if not ready:
            continue
        chunk = os.read(fd, env.KEY_LEN + 1 - len(buf))
        if not chunk:
            break
        buf.extend(chunk)
    if len(buf) != env.KEY_LEN:
        env.zero(buf)
        raise KekLoadError("kek_unavailable")
    return buf


def _read_handoff_nonce(path: Path) -> str:
    """O_NOFOLLOW, owner + mode 0400/0600 checked, bounded read."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise KekLoadError("kek_unavailable") from exc
    try:
        st = os.fstat(fd)
        mode = stat.S_IMODE(st.st_mode)
        if not stat.S_ISREG(st.st_mode) or mode not in (0o400, 0o600) or st.st_uid != os.geteuid():
            raise KekLoadError("kek_handle_permissions")
        raw = os.read(fd, _HANDOFF_MAX + 1)
    finally:
        os.close(fd)
    nonce = raw.decode("ascii", "replace").strip()
    if len(raw) > _HANDOFF_MAX or not _NONCE_RE.match(nonce):
        raise KekLoadError("kek_unavailable")
    return nonce


_TMPFS_MAGIC, _RAMFS_MAGIC = 0x01021994, 0x858458F6
_RAM_FS = frozenset({_TMPFS_MAGIC, _RAMFS_MAGIC})


class _StatFs(ctypes.Structure):
    # Linux x86-64/aarch64 `struct statfs`; only f_type (first member) is read.
    _fields_ = [("f_type", ctypes.c_long), ("_rest", ctypes.c_byte * 112)]


def fs_type(fd: int) -> int | None:
    """`fstatfs(fd).f_type` of the *opened* descriptor (no path TOCTOU); None if unknown."""
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        buf = _StatFs()
        if libc.fstatfs(fd, ctypes.byref(buf)) != 0:
            return None
        return int(buf.f_type) & 0xFFFFFFFF
    except (OSError, AttributeError):
        return None


def _fd_path(fd: int) -> str:
    """The kernel's path for the *opened* fd (no `..`/symlink games on the configured string)."""
    try:
        return os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        return ""


@dataclass(frozen=True)
class PathKekSource:
    """Reads exactly 32 raw bytes from `path` (O_NOFOLLOW, bounded timeout, strict mode/owner).

    Live: a regular-file handle (systemd credential) must be on tmpfs/ramfs, checked with
    `fstatfs` on the opened fd, *and* under `/run/credentials/`. FIFOs (the WSL read-once
    launcher handoff) are acked by the service once every handle is drained (`write_ack`).
    `abandoned` is set by the caller on timeout/cancel: the bytes are then zeroed, not returned.
    """

    path: Path
    version: int
    allow_fifo: bool
    live: bool = False
    timeout_s: float = 10.0
    clock: Callable[[], float] = time.monotonic
    abandoned: threading.Event = field(default_factory=threading.Event)

    def load(self) -> LoadedKek:
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as exc:
            raise KekLoadError("kek_unavailable") from exc
        try:
            st = os.fstat(fd)
            _check_mode(st, allow_fifo=self.allow_fifo)
            is_fifo = stat.S_ISFIFO(st.st_mode)
            if self.live and not is_fifo:
                on_ram = fs_type(fd) in _RAM_FS
                if not on_ram or not _fd_path(fd).startswith(LIVE_FILE_PREFIX):
                    raise KekLoadError("kek_handle_permissions")
            key = _read_exact(fd, self.clock() + self.timeout_s, self.clock)
        finally:
            os.close(fd)
        if self.abandoned.is_set():
            env.zero(key)
            raise KekLoadError("kek_unavailable")
        return LoadedKek(key, self.version, is_fifo=is_fifo)


def is_fifo(path: str) -> bool:
    """lstat (no follow): is the configured handle a FIFO (WSL launcher handoff)?"""
    try:
        return stat.S_ISFIFO(os.lstat(path).st_mode)
    except OSError:
        return False


def read_handoff(handoff_dir: Path) -> str:
    """Read + validate the launcher's handoff nonce. Called *before* the first FIFO is opened:
    the launcher unlinks the handoff dir right after writing the KEK (e27-kek.md §3 step 3)."""
    return _read_handoff_nonce(handoff_dir / _HANDOFF_NAME)


def write_ack(nonce: str, ack_path: Path) -> None:
    """Echo the handoff nonce (read earlier, held in memory) to the separate, writable ack path,
    exactly once, after *every* FIFO handle has been drained, so a second reader of any handle
    shows up as a missing/duplicate ack (e27-kek.md §3 step 4)."""
    if not _NONCE_RE.match(nonce):
        raise KekLoadError("kek_unavailable")
    try:
        fd = os.open(ack_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise KekLoadError("kek_unavailable") from exc
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(nonce + "\n")


class NoKekSource:
    def load(self) -> LoadedKek:
        raise KekLoadError("kek_unavailable")


def harden_process() -> bool:
    """SR-009: no core dumps and not dumpable/ptrace-able by same-uid peers.

    Returns True only if both took effect (read back). Swap / `ptrace_scope` are host config
    (runbook). The caller degrades in live when this returns False.
    """
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        core_ok = resource.getrlimit(resource.RLIMIT_CORE) == (0, 0)
    except (ValueError, OSError):
        core_ok = False
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        set_ok = libc.prctl(_PR_SET_DUMPABLE, 0, 0, 0, 0) == 0
        dump_ok = set_ok and libc.prctl(_PR_GET_DUMPABLE, 0, 0, 0, 0) == 0
    except (OSError, AttributeError):
        dump_ok = False
    return core_ok and dump_ok
