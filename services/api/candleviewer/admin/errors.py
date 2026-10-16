"""Domain errors for the admin module (M21)."""

from __future__ import annotations

from typing import Literal

#: Why the break-glass CLI cannot use its host journal (E09-S11 #2119): the anchored directory
#: or the journal is unusable, or the run lock is held (cv-api, or another break-glass run).
JournalRefusal = Literal["host_fs_unavailable", "api_running"]


class AdminError(Exception):
    """Base exception for the M21 `admin` module."""


class BreakGlassUnavailable(AdminError):
    """The break-glass journal port could not open the host journal under the run lock
    (E09-S11 #2119, SR-023). `reason` names no path and no secret; the flow refuses with it."""

    def __init__(self, reason: JournalRefusal) -> None:
        super().__init__(f"break-glass journal unavailable: {reason}")
        self.reason: JournalRefusal = reason
