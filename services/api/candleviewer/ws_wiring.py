"""Composition-root wiring (not a module): the E17 client WS gateway (#377, #378, #411).

Only the composition root sees ingestion, bars, auth/audit and the ws package together
(C-3.1), the same pattern as `bars_wiring.py`. Everything here is constructed without I/O so
`create_app()` stays cheap; `WsRuntime.start()` / `.stop()` are driven by the ASGI lifespan.

* **Upstream sink** (E08, read-only): `UpstreamRefs` opens/drops one demand lease per
  `(symbol, family)` on the ingestion streams' existing `acquire`/`release` interface. Families
  with no ingestion stream yet are a logged no-op; a refused symbol never fails the socket.
* **Snapshots** (E17-S03 port): `SnapshotRouter` dispatches per topic family to the owning
  module's adapter (bars #2195, book #2196, order-flow #2197). Until one lands, its family maps
  to `PendingSnapshotSource`, which raises `NotImplementedError`; the router turns that into
  `None`, so the subscription reports `snapshot_pending` and no `d` is ever emitted.
* **Events** (E09 / kill switch): `WsEvents` is the one entry point producers call:
  `grants_changed`, `user_disabled`, `kill_switch_changed`.
* **Shutdown** (§9.4): `WsRuntime.stop()` runs FIRST in the lifespan teardown: the gateway sends
  `shutdown_notice` on `system`, waits the grace period, then `bye` + `1001`.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Protocol

import structlog

from candleviewer.observability.context import spawn
from candleviewer.ws.gateway import CLOSE_FLUSH_TIMEOUT_S, GatewayHub
from candleviewer.ws.permissions import ConnectionRegistry, Subscription
from candleviewer.ws.sequencing import SnapshotBody, SnapshotSource
from candleviewer.ws.upstream import UpstreamKey, UpstreamRefs

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.settings import Settings


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: Topic family -> owning-module adapter ticket, for families whose adapter has not landed.
PENDING_ADAPTERS: Final[Mapping[str, str]] = {
    "bars": "#2195",
    "book": "#2196",
    "footprint": "#2197",
    "heatmap": "#2197",
    "profile": "#2197",
    "metrics": "#2197",
}


class _Demand(Protocol):
    def acquire(self, consumer: str, symbol: str) -> None: ...

    def release(self, consumer: str, symbol: str) -> None: ...


class IngestionUpstreamSink:
    """`UpstreamSink` over the E08 ingestion streams (public market data only).

    `UpstreamRefs` already collapses every WS consumer of a key into one, so each key holds
    exactly one ingestion lease under the consumer id `ws:<family>:<params>`."""

    def __init__(self, streams: Callable[[str], _Demand | None]) -> None:
        self._streams = streams

    @staticmethod
    def _consumer(key: UpstreamKey) -> str:
        return f"ws:{key[1]}:{':'.join(key[2])}"

    async def open(self, key: UpstreamKey) -> None:
        stream = self._streams(key[1])
        if stream is None:
            return
        try:
            stream.acquire(self._consumer(key), key[0])
        except Exception:
            # A refused/unlisted symbol leaves the subscription pending, never the socket faulted.
            logger().warning("ws upstream open refused", symbol=key[0], family=key[1])

    async def drop(self, key: UpstreamKey) -> None:
        stream = self._streams(key[1])
        if stream is not None:
            stream.release(self._consumer(key), key[0])


def ingestion_streams(ctx: AppContext) -> Callable[[str], _Demand | None]:
    """Family -> the ingestion stream that owns its upstream demand (resolved per call: the
    streams are attached by `wire_public_ws` only when its flag is on)."""

    def resolve(family: str) -> _Demand | None:
        ing = ctx.ingestion
        if family == "trades":
            return ing.trades
        if family == "book":
            return ing.books
        if family == "ticker":
            return ing.tickers
        return None

    return resolve


class PendingSnapshotSource:
    """Stand-in for an owning-module adapter that has not landed (#1778 Q2)."""

    def __init__(self, family: str, ticket: str) -> None:
        self.family = family
        self.ticket = ticket

    def build(self, sub: Subscription) -> SnapshotBody | None:
        raise NotImplementedError(f"{self.family} snapshot adapter pending ({self.ticket})")

    def generation(self, sub: Subscription) -> int:
        raise NotImplementedError(f"{self.family} snapshot adapter pending ({self.ticket})")

    def continuity(self, sub: Subscription, from_ts_ms: int | None) -> bool:
        raise NotImplementedError(f"{self.family} snapshot adapter pending ({self.ticket})")


class SnapshotRouter:
    """One `SnapshotSource` dispatching per topic family. A pending adapter yields `None`
    (subscription stays `snapshot_pending`), generation 0 and no continuity (§7.6 forces a
    snapshot)."""

    def __init__(self, sources: Mapping[str, SnapshotSource]) -> None:
        self._sources = dict(sources)

    def _source(self, sub: Subscription) -> SnapshotSource | None:
        return self._sources.get(sub.topic.family.family)

    def build(self, sub: Subscription) -> SnapshotBody | None:
        source = self._source(sub)
        if source is None:
            return None
        try:
            return source.build(sub)
        except NotImplementedError:
            return None

    def generation(self, sub: Subscription) -> int:
        source = self._source(sub)
        try:
            return 0 if source is None else source.generation(sub)
        except NotImplementedError:
            return 0

    def continuity(self, sub: Subscription, from_ts_ms: int | None) -> bool:
        source = self._source(sub)
        try:
            return False if source is None else source.continuity(sub, from_ts_ms)
        except NotImplementedError:
            return False


def default_snapshot_router(
    adapters: Mapping[str, SnapshotSource] | None = None,
) -> SnapshotRouter:
    sources: dict[str, SnapshotSource] = {
        fam: PendingSnapshotSource(fam, ticket) for fam, ticket in PENDING_ADAPTERS.items()
    }
    sources.update(adapters or {})
    return SnapshotRouter(sources)


@dataclass
class KillSwitchView:
    """The live kill-switch value served in `auth_ok.kill_switch` and pushed on `system`.

    Plain state published by the kill-switch owner on transition (C-2.20/C-2.21: the
    enforcing check is synchronous in the OMS; this is display + RBAC re-evaluation only)."""

    engaged: bool = False
    scope: str = "global"
    detail: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        return {"engaged": self.engaged, "scope": self.scope} | self.detail


class WsEvents:
    """The single entry point for E09 auth/grant events and kill-switch transitions."""

    def __init__(
        self, registry: ConnectionRegistry, hub: GatewayHub, kill_switch: KillSwitchView
    ) -> None:
        self.registry = registry
        self.hub = hub
        self.kill_switch = kill_switch

    async def grants_changed(self, user_id: uuid.UUID) -> None:
        await self.registry.grants_changed(user_id)

    async def user_disabled(self, user_id: uuid.UUID) -> int:
        return await self.registry.user_disabled(user_id)

    async def kill_switch_changed(
        self, *, engaged: bool, scope: str = "global", **detail: Any
    ) -> None:
        """§12.5: the `system` frame first (the UI disables order entry on it alone), then
        every connected user is re-evaluated (`permission_change` + `revoked`)."""
        self.kill_switch.engaged, self.kill_switch.scope = engaged, scope
        self.kill_switch.detail = dict(detail)
        self.hub.broadcast_system(
            {
                "kind": "kill_switch",
                "kill_switch": self.kill_switch.snapshot(),
                "severity": "critical" if engaged else "info",
            }
        )
        await self.registry.kill_switch_changed()


class WsRuntime:
    """Lifespan owner of the gateway's background work and its planned shutdown."""

    def __init__(
        self,
        hub: GatewayHub,
        upstream: UpstreamRefs,
        settings: Settings,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.hub = hub
        self.upstream = upstream
        self._settings = settings
        self._clock = clock
        self._sweeper: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._sweeper is None:
            self._sweeper = spawn(self.upstream.run(self._clock), name="ws-upstream-sweeper")

    async def stop(self) -> int:
        """§9.4: `shutdown_notice`, grace, `bye` + `1001`; then wait (bounded) for the sockets
        to flush and stop the sweeper. Returns the number of connections notified."""
        s = self._settings
        notified = await self.hub.shutdown(
            grace_ms=s.ws_shutdown_grace_ms,
            expected_downtime_ms=s.ws_shutdown_expected_downtime_ms,
        )
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(CLOSE_FLUSH_TIMEOUT_S):
                await self.hub.wait_empty()
        if self._sweeper is not None:
            self._sweeper.cancel()
            await asyncio.wait({self._sweeper})  # never raises; our own cancel is consumed
            self._sweeper = None
        return notified
