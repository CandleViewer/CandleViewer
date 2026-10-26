"""A committed profile write tells its account's sockets (E28-T02, #906 D3e; ADR-0040 Decision 3).

`ProfileNotices` holds `{env}.profiles.*.changed` (24 Sec.9.2) with `NEVER_DROP`, writes being
rare, and offers each `ProfilesChanged` to every authenticated socket as one `system` frame of
`kind: "account_notice"`, reason `profiles.changed`, through `GatewayHub.broadcast_system`, whose
`system_view` cuts it to each socket's `account_scope`: a socket that may view none of the accounts
gets nothing (23 Sec.15.9, SR-188, SR-E29-10). The frame names the account and nothing else of the
write, no profile id, version, value or actor (C-12.6). It is an event, never replayed: a client
holding the account's profiles re-reads them, and the backstops are E28-S01's. Propagation, not a
guard: the order path's version check at submit keeps a stale profile from sizing (SR-E28-15).

It runs after the commit, on its own task: an offer that raises is logged (the account, the error
class) and counted, and never reaches the writer, as is an item on the pattern that is no
`ProfilesChanged` (logged by its class alone); a cancellation propagates. Each change offered to
a socket is one sample of `cv_profile_propagation_seconds` (`env` only), from its `ts_event`, the
write's transaction time, at or before its commit (so a sample reads long by that transaction), to
the hand-off. The composition root builds it (`accounts` and `ws` import nothing of each other,
C-3.1), and the lifespan stops it before the bus drains.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any, Final, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.profile_changes import ProfilesChanged
from candleviewer.bus import Bus, QueuePolicy, Subscription, TopicPattern
from candleviewer.bus.models import WILDCARD
from candleviewer.observability.context import spawn
from candleviewer.observability.metrics import Metrics

#: The `account_notice` reason this bridge sends: an event, never an account's state (23 Sec.15.9).
PROFILES_CHANGED: Final = "profiles.changed"
#: The bridge's queue (C-2.18). A full one holds the next write's announcement, at most
#: `ANNOUNCE_TIMEOUT_S`, never the write (24 Sec.9.2).
NOTICE_QUEUE_SIZE: Final = 1024


def _log() -> Any:
    """Resolved per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _now_us() -> int:
    return time.time_ns() // 1_000


def _stopped(task: asyncio.Task[None]) -> None:
    """A bridge that ends other than by `stop` says so, never silently: from then on no socket
    hears a change (C-2.18). A cancellation is `stop`'s, and logs nothing."""
    if not task.cancelled() and (exc := task.exception()) is not None:
        _log().error("profile.notices_stopped", error=type(exc).__name__)  # never a value


class SystemBroadcast(Protocol):
    """`GatewayHub.broadcast_system`: each authenticated socket queues its Sec.15.9 view of `body`,
    or nothing; the answer is how many sockets were offered it."""

    def broadcast_system(self, body: dict[str, Any]) -> int: ...


def profiles_notice(account_id: UUID) -> dict[str, Any]:
    """ADR-0040's frame: the account, in `exchange_account_ids` only, and nothing of the write; the
    `message` names no account and counts none."""
    return {
        "kind": "account_notice",
        "severity": "info",
        "reason": PROFILES_CHANGED,
        "message": "An account profile changed.",
        "exchange_account_ids": [str(account_id)],
    }


class ProfileNotices:
    """`start` holds the pattern and drains it on one owned task; `stop` lets go of the pattern and
    cancels the task, so the bus's drain at shutdown waits for nothing here."""

    def __init__(
        self,
        bus: Bus,
        environment: str,
        hub: SystemBroadcast,
        metrics: Metrics,
        *,
        now_us: Callable[[], int] = _now_us,
    ) -> None:
        self._bus, self._hub, self._now_us = bus, hub, now_us
        self.pattern = TopicPattern(
            env=environment, domain="profiles", symbol=WILDCARD, detail="changed"
        )
        self._seconds = metrics.get("cv_profile_propagation_seconds").child()
        self._failed = metrics.get("cv_profile_notices_failed_total").child()
        self._running: tuple[Subscription, asyncio.Task[None]] | None = None

    def start(self) -> None:
        if self._running is None:
            sub = self._bus.subscribe(
                "profile-notices", self.pattern, QueuePolicy.NEVER_DROP, maxsize=NOTICE_QUEUE_SIZE
            )
            task = spawn(self._run(sub), name="profile-notices")
            task.add_done_callback(_stopped)
            self._running = (sub, task)

    async def stop(self) -> None:
        running, self._running = self._running, None
        if running is not None:
            sub, task = running
            self._bus.unsubscribe(sub)
            task.cancel()
            await asyncio.wait({task})

    async def _run(self, sub: Subscription) -> None:
        while True:
            event = await sub.get()
            if not isinstance(event, ProfilesChanged):  # the topics' one producer sends no other
                self._failed.inc()
                _log().warning("profile.notice_failed", error=type(event).__name__)
                continue
            try:
                offered = self._hub.broadcast_system(profiles_notice(event.exchange_account_id))
                if offered:
                    self._observe(event.ts_event)
            except Exception as exc:  # committed already: a lost notice never reaches the writer
                self._failed.inc()
                _log().warning(
                    "profile.notice_failed",
                    account_id=str(event.exchange_account_id),
                    error=type(exc).__name__,  # never a value
                )

    def _observe(self, ts_event: int) -> None:
        """From `ts_event` to this hand-off; a `ts_event` after the clock's reading is a clock step,
        never a sample (as `observability.latency` drops a negative stage)."""
        elapsed_us = self._now_us() - ts_event
        if elapsed_us >= 0:
            self._seconds.observe(elapsed_us / 1_000_000)
