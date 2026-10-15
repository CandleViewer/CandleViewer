"""Role-filtered `system` pushes of flag changes and maintenance notices (E42-T03, module M21).

`FlagPush.flag_changed` is the `FlagWriter` change hook. For every authenticated session it sends
`SystemUpdate {kind: "feature_flags", feature_flags: {key: value}}` carrying only the changed
key, resolved for that session's user exactly as `GET /admin/feature-flags` resolves it. A
session whose role may not see the flag gets no frame, so a manager or viewer never learns an
owner-only key (`23-ws-protocol.md` 15.9). Changing `maintenance.mode` also sends every session
a `notice` with `reason` `maintenance.enabled` or `maintenance.disabled`.

Sessions come through the `SessionDirectory` port (the composition root adapts the WS hub to
it), so the admin module never imports the WS gateway. The push is synchronous fan-out onto
each session's bounded outbound queue, measured by `cv_flag_push_latency_seconds`.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Final, Protocol
from uuid import UUID

from candleviewer.admin.flags.catalogue import MAINTENANCE_MODE
from candleviewer.admin.flags.metrics import flag_push_latency_seconds
from candleviewer.admin.flags.registry import Visibility
from candleviewer.admin.flags.service import FlagService

NOTICES: Final = {
    True: ("maintenance.enabled", "warning", "Maintenance mode: order entry is paused."),
    False: ("maintenance.disabled", "info", "Maintenance mode ended."),
}


@dataclass(frozen=True, slots=True)
class Session:
    user_id: UUID
    roles: frozenset[str]
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

    async def flag_changed(self, key: str) -> None:
        """Push the changed key to every session that may see it (the `FlagWriter` hook)."""
        start = self._clock()
        spec = self._service.registry[key]
        maintenance: bool | None = None
        if key == MAINTENANCE_MODE:
            maintenance = bool(await self._service.value(key))
        for session in self._sessions.authenticated():
            if maintenance is not None:
                reason, severity, message = NOTICES[maintenance]
                session.push_system(
                    {"kind": "notice", "severity": severity, "reason": reason, "message": message}
                )
            if spec.visibility is Visibility.OWNER_ONLY and "owner" not in session.roles:
                continue
            value = await self._service.value(key, user_id=session.user_id, roles=session.roles)
            session.push_system({"kind": "feature_flags", "feature_flags": {key: value}})
        flag_push_latency_seconds.observe(self._clock() - start)
