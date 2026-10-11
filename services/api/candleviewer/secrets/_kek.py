"""KEK loader (E27-K01 §3-§5, ADR-0009). Private to M2: never re-exported.

The KEK arrives through exactly one path, `CV_KEK_HANDLE`, and is never put in
`os.environ` or `Settings`. Sources: `handle` (read-once FIFO / systemd credential),
`file` (dev/ci only; refused in live), `none` (always degraded).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import select
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, Protocol
from uuid import UUID

from candleviewer.secrets import _envelope as env
from candleviewer.secrets.errors import KekLoadError, KekSourceNotPermitted
from candleviewer.settings import Environment, Settings

_KCV_LABEL = b"cv-kek-kcv-v1"
_NONCE_RE = re.compile(r"^[A-Za-z0-9-]{8,128}$")
_HANDOFF_NAME = "handoff"


class LoadedKek:
    """32 KEK bytes in memory. Renders as `***`; not picklable; `close()` zeroes."""

    __slots__ = ("_key", "version")

    def __init__(self, key: bytearray, version: int) -> None:
        if len(key) != env.KEY_LEN:
            raise KekLoadError("kek_unavailable")
        self._key = key
        self.version = version

    def __repr__(self) -> str:
        return "***"

    __str__ = __repr__

    def __reduce_ex__(self, protocol: object) -> NoReturn:
        raise TypeError("LoadedKek cannot be pickled")

    def kcv(self) -> bytes:
        return hmac.new(bytes(self._key), _KCV_LABEL, hashlib.sha256).digest()[:8]

    def wrap_dek(self, dek: bytearray, *, credential_id: UUID) -> str:
        nonce, sealed = env.seal(self._key, bytes(dek), env.dek_aad(credential_id, self.version))
        return f"v1:{(nonce + sealed).hex()}"

    def unwrap_dek(self, dek_ref: str, *, credential_id: UUID) -> bytearray:
        """Raises `InvalidTag` on wrong KEK / wrong row / wrong version; `ValueError` on shape."""
        prefix, _, body = dek_ref.partition(":")
        if prefix != "v1":
            raise ValueError("unsupported dek_ref")
        raw = bytes.fromhex(body)
        aad = env.dek_aad(credential_id, self.version)
        return bytearray(env.open_(self._key, raw[: env.NONCE_LEN], raw[env.NONCE_LEN :], aad))

    def close(self) -> None:
        env.zero(self._key)


class KekSource(Protocol):
    def load(self) -> LoadedKek: ...


def kcv_matches(kek: LoadedKek, expected: bytes) -> bool:
    return hmac.compare_digest(kek.kcv(), expected)


def _check_mode(st: os.stat_result, *, allow_fifo: bool) -> None:
    mode = stat.S_IMODE(st.st_mode)
    ok = (stat.S_ISREG(st.st_mode) and mode == 0o400) or (
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


@dataclass(frozen=True)
class PathKekSource:
    """Reads exactly 32 raw bytes from `path` (O_NOFOLLOW, bounded timeout, strict mode/owner)."""

    path: Path
    version: int
    allow_fifo: bool
    timeout_s: float = 10.0
    ack_path: Path | None = None
    clock: Callable[[], float] = time.monotonic

    def load(self) -> LoadedKek:
        try:
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError as exc:
            raise KekLoadError("kek_unavailable") from exc
        try:
            _check_mode(os.fstat(fd), allow_fifo=self.allow_fifo)
            key = _read_exact(fd, self.clock() + self.timeout_s, self.clock)
        finally:
            os.close(fd)
        if self.ack_path is not None:
            try:
                self._ack()
            except BaseException:
                env.zero(key)
                raise
        return LoadedKek(key, self.version)

    def _ack(self) -> None:
        """Echo the handoff nonce to the (separate, writable) ack path, exactly once."""
        assert self.ack_path is not None  # noqa: S101 -- narrowed by caller
        try:
            nonce = (self.path.parent / _HANDOFF_NAME).read_text(encoding="ascii").strip()
            if not _NONCE_RE.match(nonce):
                raise KekLoadError("kek_unavailable")
            fd = os.open(self.ack_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except OSError as exc:
            raise KekLoadError("kek_unavailable") from exc
        with os.fdopen(fd, "w", encoding="ascii") as fh:
            fh.write(nonce + "\n")


def harden_process() -> None:
    """SR-009 best effort before key material is loaded: no core dumps, not ptrace-able
    by same-uid peers (`PR_SET_DUMPABLE=0`). Swap/ptrace_scope are host config (runbook)."""
    import ctypes
    import resource

    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl(4, 0, 0, 0, 0)  # PR_SET_DUMPABLE = 4
    except (OSError, AttributeError):  # pragma: no cover - non-Linux libc; rlimit still applies
        return


class NoKekSource:
    def load(self) -> LoadedKek:
        raise KekLoadError("kek_unavailable")


def source_from_settings(settings: Settings, *, previous: bool = False) -> KekSource:
    """Enforce the §4 hard rules; `file` in live raises `KekSourceNotPermitted` (fatal)."""
    kind = "handle" if settings.kek_source == "host-keychain" else settings.kek_source
    if kind == "file" and settings.environment is Environment.LIVE:
        raise KekSourceNotPermitted("kek_source_not_permitted")
    raw = settings.kek_prev_handle if previous else settings.kek_handle
    if kind == "none" or not raw:
        return NoKekSource()
    version = settings.kek_version - 1 if previous else settings.kek_version
    ack = settings.kek_ack_path
    return PathKekSource(
        path=Path(raw),
        version=version,
        allow_fifo=kind == "handle",
        ack_path=Path(ack) if ack and kind == "handle" and not previous else None,
    )
