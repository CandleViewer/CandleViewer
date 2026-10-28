"""Composition-root wiring (not a module): the E17 client WS gateway (#377, #378, #411).

Only the composition root sees ingestion, bars, auth/audit and the ws package together
(C-3.1), the same pattern as `bars_wiring.py`. Everything here is constructed without I/O so
`create_app()` stays cheap; `WsRuntime.start()` / `.stop()` are driven by the ASGI lifespan.

* **Upstream sink** (E08, read-only): `UpstreamRefs` opens/drops one demand lease per
  `(symbol, family)` on the ingestion streams' existing `acquire`/`release` interface. Families
  with no ingestion stream yet are a logged no-op; a refused symbol never fails the socket.
* **Snapshots** (E17-S03 port): `SnapshotRouter` dispatches per topic family to the owning
  module's adapter: `book_snapshot_source` (#2196), `BarsSnapshotSource` (#2195), the accounts
  module's `wallet` topic (`wallet_topic`, #837), which the account health runtime attaches to
  and publishes its deltas on, and the ingestion module's `ticker` topic (`ticker_topic`, #4707),
  whose deltas `WsRuntime` runs with the `InstrumentRevisions` bridge (23 §7.4). Until order-flow
  (#2197) lands, its families map to `PendingSnapshotSource`, which raises
  `NotImplementedError`; the router turns that into `None`, so the subscription reports
  `snapshot_pending` and no `d` is ever emitted.
* **Principal** (E09, #2505): `StorePrincipalLoader` reads a user's roles, permission codes and
  account grants from the store at every `auth` and every re-evaluation. It fails closed to the
  deny-all snapshot and never raises.
* **Events** (E09 / kill switch): `WsEvents` is the one entry point producers call:
  `grants_changed`, `user_disabled`, `account_revoked` (E27-S04), `kill_switch_changed`.
* **Rule readers** (#3488): `rule_frame_visible` reads a WS principal as `/rules` reads a session;
  it is the `viewer` a `rules` publish must name (23 §15.6).
* **Shutdown** (§9.4): `candleviewer.server.PlannedShutdownServer` runs `WsRuntime.stop()` before
  uvicorn's own shutdown (#2546): the gateway sends `shutdown_notice` on `system`, waits the grace
  period, then `bye` + `1001`. The lifespan teardown's later call only stops the sweeper. The grace
  and the `CLOSE_FLUSH_TIMEOUT_S` flush are two terms of the container stop budget that `Settings`
  checks (`api_stop_budget_s`, #2565).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Final, Protocol

import structlog

from candleviewer.accounts.wallet_topic import WalletTopic
from candleviewer.alerts.ws_topic import AlertsTopic
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot, scoped_account_ids
from candleviewer.book.resync import BookEngine
from candleviewer.book.snapshot_source import BookSnapshotSource, Record
from candleviewer.bus import Bus, QueuePolicy, TopicPattern
from candleviewer.bus import Subscription as BusSubscription
from candleviewer.bus.models import WILDCARD
from candleviewer.domain.events import InstrumentUpdatedEvent
from candleviewer.ingestion.ticker_topic import TickerTopic
from candleviewer.observability.context import spawn
from candleviewer.orderbook_wiring import BookStream
from candleviewer.recorder.ws_topic import RecorderTopic
from candleviewer.rules.manager import Actor, RuleRow, rule_visible
from candleviewer.settings import CLOSE_FLUSH_TIMEOUT_S
from candleviewer.ws import permissions as ws_permissions
from candleviewer.ws.binary import BOOK_SNAPSHOT, Frame
from candleviewer.ws.gateway import GatewayHub
from candleviewer.ws.limits import MACHINE_AUDIT_PENDING_MAX
from candleviewer.ws.machines import MachineStateRegistry
from candleviewer.ws.metrics import PRINCIPAL_LOAD_FAILURES, count_audit_failure
from candleviewer.ws.permissions import ConnectionAuthz, ConnectionRegistry, Subscription
from candleviewer.ws.revocation import AccountRevokedReason
from candleviewer.ws.sequencing import (
    SequencingHub,
    SnapshotBody,
    SnapshotSource,
    cv_ws_snapshot_overdue_total,
)
from candleviewer.ws.trades_publish import Floor, Scales, TradesTopic
from candleviewer.ws.upstream import UpstreamKey, UpstreamRefs

if TYPE_CHECKING:
    from candleviewer.app import AppContext
    from candleviewer.settings import Settings


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


#: Upper bound on one principal load. A hung store denies the principal instead of holding the
#: socket's `auth` or a role/grant change fan-out.
PRINCIPAL_LOAD_TIMEOUT_S: Final = 5.0

#: Topic family -> owning-module adapter ticket, for families whose adapter has not landed.
PENDING_ADAPTERS: Final[Mapping[str, str]] = {
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
    streams are attached by `wire_public_ws` only when its flag is on); `bars` and `indicators`
    (whose series' builder they feed, E13-T02) need trades."""

    def resolve(family: str) -> _Demand | None:
        ing = ctx.ingestion
        if family in ("trades", "bars", "indicators"):
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


def book_snapshot_body(
    structured: Mapping[str, Any],
    records: tuple[Record, ...],
    trailer: tuple[int, int],
    *,
    price_scale: int,
    qty_scale: int,
    stale: bool = False,
) -> SnapshotBody:
    """A book snapshot's gateway body: the §14.1 payload and its CVWB kind-1 twin (§3.4)."""
    part = Frame(
        BOOK_SNAPSHOT, records, price_scale=price_scale, qty_scale=qty_scale, trailer=trailer
    )
    return SnapshotBody(
        structured, (part,), price_scale=price_scale, qty_scale=qty_scale, stale=stale
    )


def book_snapshot_source(ctx: AppContext) -> BookSnapshotSource[SnapshotBody]:
    """#2196: the `book` family's adapter over the E08 live book and instrument catalogue, both
    resolved per call (attached only with the public WS); without them `build` gives `None`.
    #2487: `stale` is `BookStream.is_stale`, the freshness `GET /market/orderbook` serves, so the
    two surfaces share one derivation (the watchdog's book limit, `23-ws-protocol.md` §6)."""

    def engine(symbol: str) -> BookEngine | None:
        books = ctx.ingestion.books
        return books.engine(symbol) if isinstance(books, BookStream) else None

    def stale(symbol: str) -> bool:
        books = ctx.ingestion.books
        return books.is_stale(symbol) if isinstance(books, BookStream) else True

    def steps(symbol: str) -> tuple[Decimal, Decimal] | None:
        scheduler = ctx.ingestion.instruments
        snap = scheduler.snapshot() if scheduler is not None else None
        inst = snap.get(symbol) if snap is not None else None
        return None if inst is None else (inst.tick_size, inst.qty_step)

    return BookSnapshotSource(engine, steps, book_snapshot_body, stale=stale)


def series_stale(
    ctx: AppContext, quarantined: Callable[[str, str], bool]
) -> Callable[[str, str], bool]:
    """#2487: `stale` of a `bars` or `indicators` series (§7.2): its builder is quarantined, or
    the symbol's trade feed, which builds its bars from the tape, is past the watchdog's `trade`
    limit (`TradeStream.is_stale`, resolved per call). Without a trade stream (the public WS is
    not wired) nothing can be fresh, so every series is stale (25 §3), as `book_snapshot_source`'s
    `stale` is without a `BookStream`: both fail closed when their upstream is missing."""

    def stale(symbol: str, spec_hash: str) -> bool:
        if quarantined(symbol, spec_hash):
            return True
        trades = ctx.ingestion.trades
        return trades is None or trades.is_stale(symbol)

    return stale


def wallet_topic(hub: SequencingHub) -> WalletTopic[SnapshotBody]:
    """#837: the `wallet` family's adapter, which the accounts module owns: it renders through the
    gateway's `SnapshotBody` and publishes its deltas through `hub`. The account health runtime
    attaches its health `view` and wallet cache (`wire_account_health`); before, `build` gives
    `None`."""
    return WalletTopic(hub.publish, SnapshotBody)


def alerts_topic(hub: SequencingHub) -> AlertsTopic[SnapshotBody]:
    """E40-T04: the `alerts` family's adapter, which the alerts module owns: it renders through the
    gateway's `SnapshotBody`, publishes its deltas through `hub` (each naming its owner), and wakes
    or resyncs an owner's subscriptions through it. The composition root attaches the deliveries
    reader; before, `build` gives `None`."""
    return AlertsTopic(hub.publish, hub.flush_pending, hub.resnapshot, SnapshotBody)


def ticker_topic(ctx: AppContext, hub: SequencingHub) -> TickerTopic[SnapshotBody]:
    """E08-T08 (#4707): the `ticker` family's adapter, which the ingestion module owns: snapshots
    from the ticker stream's merged state (resolved per call: attached only with the public WS),
    deltas from its bus topic through `hub`, at most one frame per window (23 §6.1, §8), and the
    W11 count of its overdue waits. `WsRuntime` starts and stops it."""
    return TickerTopic(
        hub.subscriptions,
        hub.publish,
        hub.resnapshot,
        SnapshotBody,
        reader=lambda: ctx.ingestion.tickers,
        bus=ctx.bus.bus,
        env=ctx.settings.environment.value,
        overdue=cv_ws_snapshot_overdue_total.labels(topic="ticker"),  # served at 0 from now
    )


def trades_topic(
    ctx: AppContext, hub: SequencingHub, *, scales: Scales, floor: Floor
) -> TradesTopic:
    """E22-T02 (#654): the `trades` family's leases, snapshot source and publisher over the
    ingestion trade stream (resolved per call: attached only with the public WS) and its bus
    topic, with the instrument scales (kind 3) and `MIN_SIZE_FLOOR` (SR-E22-03) from the
    catalogue. `WsRuntime` starts and stops it."""
    return TradesTopic(
        hub,
        reader=lambda: ctx.ingestion.trades,
        bus=ctx.bus.bus,
        env=ctx.settings.environment.value,
        scales=scales,
        floor=floor,
    )


#: The revision bridge's queue (C-2.18): revisions are rare, so a full one makes the catalogue
#: refresh that publishes them wait (`NEVER_DROP`), never a hot path, and none is lost.
REVISION_QUEUE_MAX: Final = 1024


class InstrumentRevisions:
    """E08-T08 (#4707, 23 §7.4): each `InstrumentUpdatedEvent` on `{env}.instruments.*.updated`
    re-snaps its symbol's subscriptions (`SequencingHub.instrument_revision`). `start` holds the
    pattern (one environment, never a replay's) and drains it on one owned task; `stop` lets go of
    both. A revision that raises is logged by symbol and error class and the next still runs; an
    item that is no revision is skipped."""

    def __init__(self, bus: Bus, environment: str, revise: Callable[[str], int]) -> None:
        self._bus, self._revise = bus, revise
        self.pattern = TopicPattern(
            env=environment, domain="instruments", symbol=WILDCARD, detail="updated"
        )
        self._running: tuple[BusSubscription, asyncio.Task[None]] | None = None

    def start(self) -> None:
        if self._running is None:
            sub = self._bus.subscribe(
                "ws-instrument-revisions",
                self.pattern,
                QueuePolicy.NEVER_DROP,
                maxsize=REVISION_QUEUE_MAX,
            )
            self._running = (sub, spawn(self._run(sub), name="ws-instrument-revisions"))

    async def stop(self) -> None:
        running, self._running = self._running, None
        if running is not None:
            sub, task = running
            self._bus.unsubscribe(sub)
            task.cancel()
            await asyncio.wait({task})

    async def _run(self, sub: BusSubscription) -> None:
        while True:
            event = await sub.get()
            if not isinstance(event, InstrumentUpdatedEvent):
                continue
            try:
                self._revise(event.symbol)
            except Exception as exc:  # contained: the next revision still re-snaps
                logger().warning(
                    "ws instrument revision failed", symbol=event.symbol, error=type(exc).__name__
                )


def recorder_topic(hub: SequencingHub) -> RecorderTopic[SnapshotBody]:
    """E16-T08 (#492): the `recorder` family's adapter, which the recorder module owns: it renders
    through the gateway's `SnapshotBody`, publishes each 1 Hz status through `hub` (one frame per
    group of subscriptions) and resyncs through it. The recording status cache attaches to it;
    before, `build` gives `None`."""
    return RecorderTopic(hub.subscriptions, hub.publish, hub.resnapshot, SnapshotBody)


def rule_frame_visible(row: RuleRow, principal: PrincipalSnapshot) -> bool:
    """#3488: whether a frame about `row` may reach `principal` on the `rules` topic: the rules
    module's reading rule (`rule_visible`) on what `/rules` reads of a session: the user, the owner
    role and the grants with `can_view` that are not frozen (`api/rules_actor.py`). `rules` imports
    no `auth`, so the two meet here: `publish(.., viewer=partial(rule_frame_visible, row))`."""
    actor = Actor(
        str(principal.user_id),
        "",  # the session id: no part of who may read a rule
        granted_accounts=frozenset(str(a) for a in scoped_account_ids(principal)),
        is_owner=principal.is_owner,
    )
    return rule_visible(row, actor)


class _Identity(Protocol):
    """The SQL identity read path (`SqlAlchemyIdentityProvider`), as `/auth/session` reads it."""

    async def user(self, user_id: str) -> dict[str, Any]: ...

    async def session_info(self, user_id: str) -> dict[str, Any]: ...


class _Grants(Protocol):
    """`user_account_access` rows as `(exchange_account_id, can_view, frozen)`
    (`SqlAlchemyScopeSource`)."""

    async def load_grants(self, owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]: ...


def _deny_all(user_id: uuid.UUID) -> PrincipalSnapshot:
    return PrincipalSnapshot(user_id, frozenset(), frozenset())


class StorePrincipalLoader:
    """The WS `SnapshotLoader` on the real backend (#2505).

    Roles and permission codes come from the SQL identity read path, account grants from
    `user_account_access`. They are read at every `auth` and at every role, grant or kill-switch
    re-evaluation, never cached (C-12.4). Unknown permission codes are dropped. An owner gets no
    grant rows, because an owner's empty grants mean every account (`auth/scopes.py`).
    `can_trade` is not loaded and is `False`, because no WS decision asks for trade rights.

    Fails closed and never raises. An unknown or non-active user, a role outside the system set,
    a store error, or a load slower than `PRINCIPAL_LOAD_TIMEOUT_S` yields the deny-all snapshot.
    Each of those that raised is counted in `cv_ws_principal_load_failures_total` (`timeout` for
    the bound, `error` for the rest; #571) and logged once; a non-active user is not a failure.
    Not raising matters on re-evaluation: an exception there would leave the live sockets on
    their previous, possibly wider, principal.
    """

    def __init__(
        self,
        identity: _Identity,
        grants: _Grants,
        *,
        timeout_s: float = PRINCIPAL_LOAD_TIMEOUT_S,
    ) -> None:
        self._identity = identity
        self._grants = grants
        self._timeout_s = timeout_s

    async def __call__(self, user_id: uuid.UUID) -> PrincipalSnapshot:
        try:
            return await self._load(user_id)
        except Exception as exc:  # LookupError (unknown user), ValueError (unknown role), store
            # #571: counted by the one kind this `except` can tell apart, its own bound expiring
            reason = "timeout" if isinstance(exc, TimeoutError) else "error"
            PRINCIPAL_LOAD_FAILURES[reason].inc()
            logger().warning(
                "ws principal load failed; denying all",
                user_id=str(user_id),
                error=type(exc).__name__,
            )
            return _deny_all(user_id)

    async def _load(self, user_id: uuid.UUID) -> PrincipalSnapshot:
        async with asyncio.timeout(self._timeout_s):
            user = await self._identity.user(str(user_id))
            info = await self._identity.session_info(str(user_id))
            rows = await self._grants.load_grants(user_id)
        if user.get("status") != "active":
            return _deny_all(user_id)
        codes = {str(code) for code in info.get("permissions", ())}
        principal = PrincipalSnapshot(
            user_id=user_id,
            roles=frozenset(str(role) for role in user.get("roles") or ()),
            permissions=frozenset(p for p in Permission if p.value in codes),
        )
        if principal.is_owner:
            return principal
        grants = tuple(AccountGrant(acc, view, False, frozen) for acc, view, frozen in rows)
        return replace(principal, account_grants=grants)


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

    async def account_revoked(self, account_id: uuid.UUID, reason: AccountRevokedReason) -> int:
        """23 §9.5 (E27-S04, #898): the account's last signable key revoked (`key_revoked`) or
        the account disabled (`account_disabled`): its subscriptions narrow or end on every
        socket (`ConnectionRegistry.account_revoked`)."""
        return await self.registry.account_revoked(account_id, reason)

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


def loop_call_later(delay: float, callback: Callable[[], None]) -> asyncio.TimerHandle:
    """`MachineStateRegistry`'s timers: the running loop's, the loop the registry runs on."""
    return asyncio.get_running_loop().call_later(delay, callback)


class MachineRevocationAudit:
    """`MachineStateRegistry.on_revoked` (§6.4): the `evicted` rows of every removal, written by ONE
    task, one row at a time, as a resync loop's are. The audit writer appends under one lock with an
    fsync, so a task per connection or per removal would only time its rows out against each other.
    At most `MACHINE_AUDIT_PENDING_MAX` frames wait (C-2.18): past it the oldest removal's are
    dropped, as are those queued when the task ends: counted, logged. With no loop it only logs."""

    def __init__(self, registry: ConnectionRegistry) -> None:
        self.registry = registry
        self._pending: deque[list[tuple[ConnectionAuthz, dict[str, Any]]]] = deque()
        self._waiting = 0  # frames in `_pending`
        self._task: asyncio.Task[None] | None = None

    def __call__(self, revoked: list[tuple[ConnectionAuthz, dict[str, Any]]]) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:  # a synchronous caller: no loop, so no writer either
            logger().warning("ws machine revocations not audited", count=len(revoked))
            return
        self._pending.append(revoked)
        self._waiting += len(revoked)
        over, drop = self._waiting - MACHINE_AUDIT_PENDING_MAX, 0
        while over > 0 and drop < len(self._pending) - 1:  # the oldest first, never this removal
            over, drop = over - len(self._pending[drop]), drop + 1
        if drop:  # one line per call, however many removals it drops (C-2.18)
            self._abandon(drop, "queue")
        if self._task is None or self._task.done():
            self._task = spawn(self._write(), name="ws-machine-revoked-audit")
            self._task.add_done_callback(self._ended)

    def _abandon(self, batches: int, cause: str) -> None:
        """Drop the `batches` oldest removals: counted `abandoned`, logged with their actors'
        ids (a viewing socket's viewer, §9.6)."""
        frames = [frame for _ in range(batches) for frame in self._pending.popleft()]
        users = list(dict.fromkeys(authz.actor_user_id for authz, _ in frames))
        self._waiting -= len(frames)
        count_audit_failure(len(frames), "abandoned")
        logger().warning(
            "ws machine revocations not audited",
            count=len(frames),
            cause=cause,
            actor_user_ids=users[: ws_permissions._ABANDONED_USERS_LOGGED],
            users=len(users),
        )

    async def _write(self) -> None:
        while self._pending:
            batch = self._pending.popleft()
            self._waiting -= len(batch)
            try:
                await self.registry.audit_revoked_many(batch)
            except Exception as exc:  # outside the row writes, which contain their own errors
                count_audit_failure(len(batch), "error")
                logger().error("ws machine revocation audit failed", error=type(exc).__name__)

    def _ended(self, task: asyncio.Task[None]) -> None:
        """A done callback, so it runs even for a task cancelled before its first step (C-2.9)."""
        error = None if task.cancelled() else task.exception()
        if task is self._task and self._pending:  # counted before any log; else a later writer's
            self._abandon(len(self._pending), "cancelled" if task.cancelled() else "writer_stopped")
        if error is not None:
            logger().error("ws machine revocation audit writer failed", error=type(error).__name__)

    async def drain(self) -> None:
        """Wait until no writer runs (`WsRuntime.stop`): one started as the last ended too."""
        while (task := self._task) is not None and not task.done():
            await asyncio.wait({task})


class _Refresher(Protocol):
    def start(self) -> None: ...

    async def stop(self) -> None: ...


class WsRuntime:
    """Lifespan owner of the gateway's background work and its planned shutdown. It also starts
    and stops `recorder_status`, the 1 Hz recording status (E16-T08), once the app sets it, and its
    `feeds`, the publishers the gateway's topics need (E08-T08: the `ticker` topic and the
    instrument revisions), stopped first so no frame starts after the notice."""

    def __init__(
        self,
        hub: GatewayHub,
        upstream: UpstreamRefs,
        settings: Settings,
        *,
        clock: Callable[[], float] = time.monotonic,
        machines: MachineStateRegistry | None = None,
        feeds: Sequence[_Refresher] = (),
    ) -> None:
        self.hub = hub
        self.upstream = upstream
        self.machines = machines
        self._settings = settings
        self._clock = clock
        self._sweeper: asyncio.Task[None] | None = None
        self._notified = False
        self.recorder_status: _Refresher | None = None
        self.feeds = tuple(feeds)

    def start(self) -> None:
        self._notified = False
        self.hub.shutting_down = False  # an in-process restart: the server is up again
        if self._sweeper is None:
            self._sweeper = spawn(self.upstream.run(self._clock), name="ws-upstream-sweeper")
        if self.recorder_status is not None:
            self.recorder_status.start()
        for feed in self.feeds:
            feed.start()

    async def stop(self) -> int:
        """§9.4: `shutdown_notice`, grace, `bye` + `1001`; then wait (bounded) for the sockets
        to flush and stop the sweeper. Returns the number of connections offered the notice.

        The notice and grace run once (#2546): the server runs this before uvicorn's own
        shutdown closes the sockets, and the lifespan teardown's later call only stops the
        sweeper."""
        notified = 0
        if self.recorder_status is not None:  # no status frame starts after the notice
            await self.recorder_status.stop()
        for feed in self.feeds:  # nor a `ticker` frame or a revision's `snap`
            await feed.stop()
        if not self._notified:
            self._notified = True
            s = self._settings
            try:
                notified = await self.hub.shutdown(
                    grace_ms=s.ws_shutdown_grace_ms,
                    expected_downtime_ms=s.ws_shutdown_expected_downtime_ms,
                )
            except asyncio.CancelledError:
                self._notified = False  # cut short (force_exit): a later call may notify again
                raise
            finally:
                if self.machines is not None:  # the sockets are closing, cut short or not
                    self.machines.close()
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(CLOSE_FLUSH_TIMEOUT_S):
                    await self.hub.wait_empty()
                    audit = None if self.machines is None else self.machines.on_revoked
                    if isinstance(audit, MachineRevocationAudit):  # before the audit writer stops
                        await audit.drain()
        if self._sweeper is not None:
            self._sweeper.cancel()
            await asyncio.wait({self._sweeper})  # never raises; our own cancel is consumed
            self._sweeper = None
        if self.machines is not None:  # every call: a timer armed since the notice is cancelled too
            self.machines.close()
        return notified
