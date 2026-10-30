"""#4992 (`23-ws-protocol.md` §12.1): the `system` snap that follows a socket's first `auth_ok`.

Socket tests that are not about it step over it with `is_system_snap`, so the frame each reads
next is the one it read before the snap existed; `test_system_snap.py` pins the snap itself. A
principal with none of `SYSTEM_ROLES` gets no `system` frame (§15.9), so no snap, and an in-place
re-`auth` gets none either."""

from __future__ import annotations

from typing import Any

#: The roles a `system` frame reaches (§15.9).
SYSTEM_ROLES = frozenset({"owner", "manager", "viewer"})


def is_system_snap(frame: dict[str, Any]) -> bool:
    """Whether `frame` is a `system` snap."""
    return frame.get("t") == "snap" and frame.get("ch") == "system"
