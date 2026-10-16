"""#2086 (E09-Q02 part a): the server test clock for the seeded e2e stack.

With `CV_TEST_CLOCK` on, `create_app()` injects `OffsetFileClock` as its `auth_clock`, so every
decision that reads it (login lockout, MFA, sessions, step-up, invites, CSRF) runs on real UTC
plus the offset in `CV_TEST_CLOCK_FILE`, which the harness rewrites (temp file, then rename).
There is no HTTP surface (Q2). `Settings` allows it only on testnet with no exchange key (Q1,
E16-FR-11) and `build_test_clock` re-checks that. It does not move the per-IP login throttle
(monotonic), WS gateway deadlines or B16 timers. The auth clock is a synchronous callable, so the
file is read on every call and a rewrite applies to the very next decision, with no wait.

#2728 bounds that read on the event loop: the open never blocks (a FIFO or device node cannot
stall it) and never follows a symlink as the last path component (`Settings` refuses a symlink
anywhere in the path at load), only a regular file is read, and at most 33 bytes of it.
The offset is not cached: a rename can land inside the filesystem's timestamp granularity, so an
`st_mtime_ns` key could hand the next decision a stale offset. Boot also writes a system-actor
audit record (`audit_test_clock_enabled`), next to the warning log line.
"""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

import structlog

from candleviewer.settings import Settings

Clock = Callable[[], datetime]

#: Signed decimal seconds, at most 9 integer digits (about 31 years) and microsecond precision.
_OFFSET_RE = re.compile(r"[+-]?[0-9]{1,9}(?:\.[0-9]{1,6})?")
_MAX_FILE_BYTES = 32
#: #2728: a FIFO or device node never blocks the open; a symlink as the last component fails it.
_OPEN_FLAGS = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
#: #2728 (E16 R-E3 detection is a config audit): one record per boot while the clock is on.
TEST_CLOCK_AUDIT_ACTION = "system.config.test_clock_enabled"


class OffsetFileError(ValueError):
    """`CV_TEST_CLOCK_FILE` exists but is not a regular file holding bounded decimal seconds."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


class OffsetFileClock:
    """Real UTC plus the offset in *path*; no file means no offset."""

    def __init__(self, path: Path, *, now: Clock = _utc_now) -> None:
        self._path = path
        self._now = now

    def offset(self) -> timedelta:
        """Only a missing file reads as no offset; any other open error propagates (fail closed)."""
        try:
            fd = os.open(self._path, _OPEN_FLAGS)
        except FileNotFoundError:
            return timedelta(0)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OffsetFileError("CV_TEST_CLOCK_FILE must be a regular file")
            raw = os.read(fd, _MAX_FILE_BYTES + 1)
        finally:
            os.close(fd)
        text = raw.decode("ascii", errors="replace").strip()
        if len(raw) > _MAX_FILE_BYTES or _OFFSET_RE.fullmatch(text) is None:
            raise OffsetFileError(
                "CV_TEST_CLOCK_FILE must hold signed decimal seconds, such as 301 or -5.5"
            )
        return timedelta(microseconds=int(Decimal(text) * 1_000_000))

    def __call__(self) -> datetime:
        return self._now() + self.offset()


def build_test_clock(settings: Settings) -> Clock | None:
    """The auth clock for `create_app()`: None (real UTC) unless `CV_TEST_CLOCK` is on.

    On a `Settings` that skipped validation it re-checks the environment and key gate and that
    a file is set; the path rules run at load only. When on, it writes a boot log line, so the
    clock never runs silently (C-2.11). It never reads the file here."""
    if not settings.test_clock:
        return None
    refusal = settings.test_clock_refusal()
    if refusal is not None or not settings.test_clock_file:
        raise RuntimeError(refusal or "CV_TEST_CLOCK requires CV_TEST_CLOCK_FILE")
    path = Path(settings.test_clock_file)
    structlog.get_logger(__name__).warning(
        "auth.test_clock_enabled",
        environment=settings.environment.value,
        clock_file=str(path),
        detail="auth time is UTC plus the offset in CV_TEST_CLOCK_FILE",
    )
    return OffsetFileClock(path)


class _AuditSink(Protocol):
    """The slice of `AuditWriter.emit` the boot record needs; `auth` never imports `audit`."""

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        object_kind: str | None = None,
        object_id: str | None = None,
        severity: Any = ...,
        env: Any = None,
        after_state: dict[str, Any] | None = None,
    ) -> None: ...


async def audit_test_clock_enabled(settings: Settings, audit: _AuditSink) -> None:
    """#2728: the boot audit record of a running test clock, next to the warning log line (E16
    R-E3 detection is a config audit). System actor; the lifespan awaits it before the app
    serves, so a failed write fails boot."""
    await audit.emit(
        TEST_CLOCK_AUDIT_ACTION,
        actor_label="system:test-clock",
        object_kind="settings",
        object_id="CV_TEST_CLOCK",
        severity="warning",
        env=settings.environment.value,
        after_state={"test_clock_file": settings.test_clock_file},
    )
