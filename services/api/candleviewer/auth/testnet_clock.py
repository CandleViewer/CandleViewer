"""#2086 (E09-Q02 part a): the server test clock for the seeded e2e stack.

With `CV_TEST_CLOCK` on, `create_app()` injects `OffsetFileClock` as its `auth_clock`, so every
decision that reads it (login lockout, MFA, sessions, step-up, invites, CSRF) runs on real UTC
plus the offset in `CV_TEST_CLOCK_FILE`, which the harness rewrites (temp file, then rename).
There is no HTTP surface (Q2). `Settings` allows it only on testnet with no exchange key (Q1,
E16-FR-11) and `build_test_clock` re-checks that. It does not move the per-IP login throttle
(monotonic), WS gateway deadlines or B16 timers. The file is read on every call (bounded, and
only on the gated stack) because the auth clock is a synchronous callable: a rewrite applies to
the very next decision, with no wait.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import structlog

from candleviewer.settings import Settings

Clock = Callable[[], datetime]

#: Signed decimal seconds, at most 9 integer digits (about 31 years) and microsecond precision.
_OFFSET_RE = re.compile(r"[+-]?[0-9]{1,9}(?:\.[0-9]{1,6})?")
_MAX_FILE_BYTES = 32


class OffsetFileError(ValueError):
    """`CV_TEST_CLOCK_FILE` exists but does not hold a bounded decimal number of seconds."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


class OffsetFileClock:
    """Real UTC plus the offset in *path*; no file means no offset."""

    def __init__(self, path: Path, *, now: Clock = _utc_now) -> None:
        self._path = path
        self._now = now

    def offset(self) -> timedelta:
        try:
            with self._path.open("rb") as handle:
                raw = handle.read(_MAX_FILE_BYTES + 1)
        except FileNotFoundError:
            return timedelta(0)
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

    Fails closed on a `Settings` that skipped validation. When on, it writes a boot log line,
    so the clock never runs silently (C-2.11). It never reads the file here."""
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
