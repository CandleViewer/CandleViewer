"""Visibility-filtered `system` pushes of flag changes and maintenance notices (E42-T03, M21).

`FlagPush.flag_changed` is the `FlagWriter` change hook. Every authenticated session that the
flag's mandatory `visibility` admits gets `SystemUpdate {kind: "feature_flags", feature_flags:
{key: value}}` carrying only the changed key, resolved for that session's user exactly as
`GET /admin/feature-flags` resolves it; no other session gets a frame, so a manager or viewer
never learns an `owner_only` key (`23-ws-protocol.md` 15.9, D6a). A real transition of the
stored `maintenance.mode` (`setFeatureFlag`) also sends every session a `notice`. Sessions come
through the `SessionDirectory` port (the composition root adapts the WS hub to it), so the admin
module never imports the WS gateway. The push is synchronous fan-out onto each session's bounded
outbound queue, past the 1 s `system` throttle (8.1), measured by `cv_flag_push_latency_seconds`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Final, Protocol
from uuid import UUID

import structlog

from candleviewer.admin.flags.catalogue import MAINTENANCE_MODE
from candleviewer.admin.flags.metrics import flag_push_latency_seconds
from candleviewer.admin.flags.resolver import StoredFlag, resolve
from candleviewer.admin.flags.service import FlagService
from candleviewer.admin.flags.writes import stored_transition


def logger() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


NOTICES: Final = {
    True: ("maintenance.enabled", "warning", "Maintenance mode: order entry is paused."),
    False: ("maintenance.disabled", "info", "Maintenance mode ended."),
}


@dataclass(frozen=True, slots=True)
class Session:
    user_id: UUID
    roles: frozenset[str]
    #: Enqueues one frame on the session's bounded outbound queue, past the `system` throttle
    #: (8.1). Must not raise; one that does is logged and skipped, never stopping the fan-out.
    push_system: Callable[[dict[str, Any]], None]


class SessionDirectory(Protocol):
    def authenticated(self) -> Iterable[Session]: ...


class FlagPush:
    def __init__(
        self,
        service: FlagService,
        sessions: SessionDirectory,
        *,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._service, self._sessions, self._clock = service, sessions, clock

    async def flag_changed(self, key: str, before: StoredFlag | None, after: StoredFlag) -> None:
        """The `FlagWriter` hook: push the committed `after` row, resolved per session, to every
        session that may see the flag; a real maintenance toggle also notifies every session."""
        start = self._clock()
        spec = self._service.registry[key]
        toggled = key == MAINTENANCE_MODE and stored_transition(spec, before, after)
        notice = _notice(after.value is True) if toggled else None
        for session in tuple(self._sessions.authenticated()):
            frames: list[dict[str, Any]] = [] if notice is None else [notice]
            if spec.visible_to(session.roles):
                value = resolve(spec, after, user_id=session.user_id, roles=session.roles)
                frames.append({"kind": "feature_flags", "feature_flags": {key: value}})
            for frame in frames:
                _send(session, frame, key)
        flag_push_latency_seconds.observe(self._clock() - start)

    def notify_maintenance(self, on: bool) -> None:
        """The maintenance `notice` to every session, for a stored transition the controller
        reads (D1c); a write's own transition is announced by `flag_changed`."""
        notice = _notice(on)
        for session in tuple(self._sessions.authenticated()):
            _send(session, notice, MAINTENANCE_MODE)


def _notice(on: bool) -> dict[str, Any]:
    reason, severity, message = NOTICES[on]
    return {"kind": "notice", "severity": severity, "reason": reason, "message": message}


def _send(session: Session, frame: dict[str, Any], key: str) -> None:
    try:
        session.push_system(frame)
    except Exception:  # one broken session never stops the fan-out
        logger().exception("feature_flag_push_session_failed", key=key)
