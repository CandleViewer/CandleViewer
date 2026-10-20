"""The `alerts` WS topic (E40-T04; 23-ws-protocol.md §6.2, §6.2.1, §15.7): a user's own alert
deliveries, live. The alerts module's `SnapshotSource` for the family, and the deltas its producers
send: the dispatcher's settles and the inbox routes' acknowledgements and desktop reports.

The alerts module may not import `ws` or `storage` (CONSTITUTION §3), so the topic is typed
structurally, as `accounts/wallet_topic.py` is: a subscription by the fields read here, and the
gateway's body constructor and the hub's `publish`, `flush_pending` and `resnapshot` injected
(`ws_wiring.alerts_topic`). The rows are read through `DeliveryReader`, the deliveries repository,
which the composition root attaches.

- **Scope (#2521).** A subscription's owner is recorded at admit (`Subscription.owner`, the
  principal's user id, never a client value). A snapshot reads that user's rows alone, and a delta
  names its owner to the hub (`publish(user=)`), which delivers it only to the subscriptions that
  user owns. A subscription without an owner gets nothing (fail closed).
- **Snapshot** ("unacked deliveries", §6.2): the owner's newest `SNAPSHOT_MAX` deliveries that are
  `sent` and unacknowledged, and the exact `unacked_count`. `build` is synchronous and the rows live
  in Postgres, so an owner's view is loaded beside it: the first `build` for an owner starts one
  tracked load and answers None (the subscription stays `snapshot_pending`, §7.7); the load stores
  the view and flushes that owner's pending subscriptions. The worker drops an owner's view on the
  owner's next change, before it publishes (so a later attach reads again), and marks a load in
  flight dirty, which then reads again (so a change between its read and its flush is never lost
  to a subscription that was pending when the change's delta went out). Views are bounded
  (`MAX_VIEWS`, least recently used first). Private: never cached by the gateway (generation 0),
  and no continuity (§7.6 forces a snapshot).
- **Deltas.** `deliveries_changed(ids)`, the producers' `on_change`, only enqueues the ids in a
  bounded queue and returns, so neither a request nor the dispatcher waits on the fan-out. One
  tracked worker reads the changed rows, the channel-failure notice each failed one raised and
  each owner's `unacked_count`, then publishes per owner, at most `MAX_ITEMS_PER_DELTA` items a
  frame. A subscription with `unacked_only` gets only the rows that enter or leave the unacked set
  (`sent`, `acked`). Deliveries are discrete records, so nothing is coalesced away (§6.2.1): with
  backpressure on, the gateway's pipeline paces them in 250 ms windows, whole and in order, and
  drops an overflowing window for a `backpressure` snapshot that `build` serves like any other
  (§8.4).
- **Failure.** The topic is a view: what fails here is logged by its error type (never its message,
  C-12.6) and goes no further. A change that cannot be published (its read failed, or the queue was
  full) re-snapshots the affected subscriptions, or every `alerts` subscription when the owners are
  unknown, with `upstream_desync` (§7.4), so a client never silently misses one.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.observability import spawn

#: Private topics are flat; the owner comes from the subscription (§6.2).
ALERTS: Final = "alerts"
#: The snapshot's rows: the newest unacknowledged ones (SCR-014 keeps 500; older via REST).
SNAPSHOT_MAX: Final = 500
#: Items per delta frame (an ack-all batch of 500 goes out as five).
MAX_ITEMS_PER_DELTA: Final = 100
#: Pending change batches; past it the topic re-snapshots instead of queueing (C-2.18).
QUEUE_MAX: Final = 1024
#: Changed ids the worker reads in one round (its batches are coalesced up to this).
BATCH_IDS_MAX: Final = 1000
#: Owner views kept, and loads running at once.
MAX_VIEWS: Final = 256
LOADS_MAX: Final = 8
#: A load a change keeps racing reads again at most this often before it serves what it read
#: and re-snapshots (so a burst cannot hold a subscription pending for ever).
LOAD_ROUNDS: Final = 3
#: The rows that enter or leave the unacked set: what an `unacked_only` subscription is sent.
UNACKED_STATUSES: Final = frozenset({"sent", "acked"})
_SYMBOL: Final = re.compile(r"^[A-Z0-9]{2,20}USDT$")
Reason = Literal["upstream_desync"]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class AlertsSub(Protocol):
    """The fields of a WS `Subscription` read here."""

    @property
    def ch(self) -> str: ...
    @property
    def owner(self) -> UUID | None: ...
    @property
    def opts(self) -> Mapping[str, Any]: ...


class DeliveryRecord(Protocol):
    """The `alert_deliveries` columns a §15.7 item is built from (`DeliveryRow` fits)."""

    @property
    def id(self) -> int: ...
    @property
    def alert_id(self) -> str: ...
    @property
    def user_id(self) -> str | None: ...
    @property
    def channel(self) -> str: ...
    @property
    def status(self) -> str: ...
    @property
    def title(self) -> str: ...
    @property
    def body(self) -> str: ...
    @property
    def context(self) -> dict[str, Any]: ...
    @property
    def error_message(self) -> str | None: ...
    @property
    def queued_at(self) -> datetime: ...
    @property
    def acked_at(self) -> datetime | None: ...
    @property
    def severity(self) -> str | None: ...


class DeliveryPage(Protocol):
    @property
    def items(self) -> Sequence[DeliveryRecord]: ...


class DeliveryReader(Protocol):
    """The reads the topic makes (`SqlAlchemyAlertDeliveryRepository` satisfies it)."""

    async def list_page(
        self, *, user_id: str, unacked_only: bool = ..., limit: int = ...
    ) -> DeliveryPage: ...
    async def unacked_count(self, user_id: str) -> int: ...
    async def get_many(self, delivery_ids: Sequence[int]) -> Sequence[DeliveryRecord]: ...
    async def failure_notices(
        self, user_ids: Sequence[str], failed_ids: Sequence[int]
    ) -> Sequence[DeliveryRecord]: ...


Match = Callable[[AlertsSub], bool]


class Publish(Protocol):
    """`SequencingHub.publish`: one delta to the subscriptions of `ch` that `user` owns."""

    def __call__(
        self,
        ch: str,
        body: Mapping[str, Any] | None = ...,
        *,
        user: UUID | None = ...,
        select: Match | None = ...,
    ) -> int: ...


class FlushPending(Protocol):
    """`SequencingHub.flush_pending`: snapshot every pending subscription `match` accepts."""

    def __call__(self, match: Match | None = ...) -> int: ...


class Resnapshot(Protocol):
    """`SequencingHub.resnapshot`: a server-initiated resync of what `match` accepts (§7.4)."""

    def __call__(self, match: Match, reason: Reason) -> int: ...


class BodyFactory[B](Protocol):
    """The gateway's snapshot body from a §15.7 payload."""

    def __call__(self, structured: Mapping[str, Any]) -> B: ...


def _epoch_ms(d: datetime) -> int:
    return int(d.timestamp() * 1000)


def delivery_item(row: DeliveryRecord) -> dict[str, Any]:
    """One §15.7 `deliveries` item: `message` is the `body`, falling back to `title`; `symbol` is
    the firing's when it is one. Never the delivery `context` or anything of the alert's SECRET
    columns."""
    symbol = row.context.get("symbol") if isinstance(row.context, dict) else None
    return {
        "id": row.id, "alert_id": row.alert_id, "channel": row.channel, "status": row.status,
        "severity": row.severity or "info", "title": row.title,
        "message": row.body or row.title,
        "symbol": symbol if isinstance(symbol, str) and _SYMBOL.match(symbol) else None,
        "fired_at_ms": _epoch_ms(row.queued_at),
        "acked_at_ms": None if row.acked_at is None else _epoch_ms(row.acked_at),
        "error": row.error_message,
    }  # fmt: skip


@dataclass(frozen=True, slots=True)
class _View:
    items: tuple[dict[str, Any], ...]
    unacked_count: int


def _unacked_only(sub: AlertsSub) -> bool:
    return bool(sub.opts.get("unacked_only"))


def _every(sub: AlertsSub) -> bool:
    return not _unacked_only(sub)


def _owned_by(owner: UUID) -> Match:
    def match(sub: AlertsSub) -> bool:
        return sub.ch == ALERTS and sub.owner == owner

    return match


def _any_alerts(sub: AlertsSub) -> bool:
    return sub.ch == ALERTS


class AlertsTopic[B]:
    """The `alerts` topic's snapshot source and publisher (see the module docstring), for the event
    loop that runs the gateway and the alerts module: no locks."""

    def __init__(
        self,
        publish: Publish,
        flush_pending: FlushPending,
        resnapshot: Resnapshot,
        body: BodyFactory[B],
        *,
        queue_max: int = QUEUE_MAX,
        views_max: int = MAX_VIEWS,
        loads_max: int = LOADS_MAX,
    ) -> None:
        self._publish, self._flush, self._resnapshot, self._body = (
            publish, flush_pending, resnapshot, body,
        )  # fmt: skip
        self._reader: DeliveryReader | None = None
        self._queue: asyncio.Queue[tuple[int, ...]] = asyncio.Queue(maxsize=queue_max)
        self._overflowed = False
        self._views: OrderedDict[UUID, _View] = OrderedDict()
        self._views_max = views_max
        self._loads: dict[UUID, asyncio.Task[None]] = {}
        self._dirty: set[UUID] = set()
        self._load_slots = asyncio.Semaphore(loads_max)
        self._worker: asyncio.Task[None] | None = None

    def attach(self, reader: DeliveryReader) -> None:
        """Read through *reader*, the deliveries repository, once. Before, `build` gives None, so a
        subscription stays `snapshot_pending` (§7.7), and changes are only counted."""
        if self._reader is not None:
            raise ValueError("the alerts topic is already attached")
        self._reader = reader

    # -- lifecycle (`AlertsService`)

    def start(self) -> None:
        if self._worker is None:
            self._worker = spawn(self._run(), name="alerts-ws-topic")

    async def stop(self) -> None:
        """Cancel the worker and every load: what they held is re-read by the next attach."""
        tasks = [t for t in (self._worker, *self._loads.values()) if t is not None]
        self._worker = None
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._loads.clear()

    # -- SnapshotSource

    def build(self, sub: AlertsSub) -> B | None:
        owner = sub.owner
        if owner is None or self._reader is None:  # fail closed / not attached yet
            return None
        view = self._views.get(owner)
        if view is None:
            self._load(owner)
            return None
        self._views.move_to_end(owner)
        return self._body({"deliveries": list(view.items), "unacked_count": view.unacked_count})

    def generation(self, sub: AlertsSub) -> int:
        return 0  # a private family's snapshot is never cached (SR-190)

    def continuity(self, sub: AlertsSub, from_ts_ms: int | None) -> bool:
        return False  # no delta history: `snapshot: false` is always `snapshot_forced`

    # -- deltas

    async def deliveries_changed(self, delivery_ids: Sequence[int]) -> None:
        """The producers' `on_change`: committed changes to *delivery_ids*. Only enqueued; never
        blocks and never raises. A full queue makes the worker re-snapshot instead."""
        if not delivery_ids:
            return
        try:
            self._queue.put_nowait(tuple(delivery_ids))
        except asyncio.QueueFull:
            if not self._overflowed:
                _log().warning("alerts_topic_queue_full", queue_max=self._queue.maxsize)
            self._overflowed = True
            with contextlib.suppress(asyncio.QueueFull):
                self._queue.put_nowait(())  # wakes the worker, which resyncs everyone

    async def _run(self) -> None:
        """The one worker: a round that fails is contained (every subscription reads again), so
        the worker outlives it; a cancellation (`stop`) ends it."""
        while True:
            ids, taken = list(await self._queue.get()), 1
            while len(ids) < BATCH_IDS_MAX and not self._queue.empty():
                ids.extend(self._queue.get_nowait())
                taken += 1
            try:
                if self._overflowed:  # changes were not queued: their owners are unknown
                    self._overflowed = False
                    self._resync_all("queue_full")
                if ids:
                    await self._changed(ids)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _log().warning("alerts_topic_round_failed", error=type(exc).__name__)
                self._resync_all("round_failed")
            finally:
                for _ in range(taken):  # `Queue.join` (a drain) sees each batch handled
                    self._queue.task_done()

    async def _changed(self, ids: list[int]) -> None:
        reader = self._reader
        if reader is None:
            return
        try:
            rows = list(await reader.get_many(ids))
            failed = [r for r in rows if r.status == "failed" and r.user_id is not None]
            if failed:
                users = sorted({r.user_id for r in failed if r.user_id is not None})
                rows += await reader.failure_notices(users, [r.id for r in failed])
            owners = sorted({r.user_id for r in rows if r.user_id is not None})
            counts = {user: await reader.unacked_count(user) for user in owners}
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # the owners are unknown: every subscription reads again
            _log().warning("alerts_topic_read_failed", error=type(exc).__name__, count=len(ids))
            self._resync_all("read_failed")
            return
        by_owner: dict[str, list[DeliveryRecord]] = {}
        for row in rows:
            if row.user_id is not None:  # a deleted user's row has nobody to tell
                by_owner.setdefault(row.user_id, []).append(row)
        for user, owned in by_owner.items():
            self._send(UUID(user), owned, counts[user])

    def _send(self, owner: UUID, rows: list[DeliveryRecord], unacked: int) -> None:
        """No await from the view drop to the last publish: a load in flight is marked dirty first,
        so it reads again rather than serve a view this change has outdated."""
        self._views.pop(owner, None)
        if owner in self._loads:
            self._dirty.add(owner)
        try:
            items = [delivery_item(r) for r in sorted(rows, key=lambda r: r.id)]
            unacked_items = [i for i in items if i["status"] in UNACKED_STATUSES]
            for group, select in ((items, _every), (unacked_items, _unacked_only)):
                for start in range(0, len(group), MAX_ITEMS_PER_DELTA):
                    body = {"deliveries": group[start : start + MAX_ITEMS_PER_DELTA],
                            "unacked_count": unacked}  # fmt: skip
                    self._publish(ALERTS, body, user=owner, select=select)
        except Exception as exc:  # contained: this owner's subscriptions read again
            _log().warning("alerts_topic_publish_failed", error=type(exc).__name__)
            self._resync(_owned_by(owner), "publish_failed")

    # -- snapshot loads

    def _load(self, owner: UUID) -> None:
        if owner in self._loads:
            return
        self._loads[owner] = spawn(self._load_view(owner), name="alerts-ws-topic-load")

    async def _load_view(self, owner: UUID) -> None:
        reader, user = self._reader, str(owner)
        try:
            if reader is None:
                return
            async with self._load_slots:
                for _ in range(LOAD_ROUNDS):
                    self._dirty.discard(owner)
                    page = await reader.list_page(
                        user_id=user, unacked_only=True, limit=SNAPSHOT_MAX
                    )
                    count = await reader.unacked_count(user)
                    if owner not in self._dirty:
                        break
            view = _View(tuple(delivery_item(r) for r in page.items), count)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # stays pending; its next flush or resync tries again
            _log().warning("alerts_topic_load_failed", error=type(exc).__name__)
            return
        finally:
            self._loads.pop(owner, None)
        self._views[owner] = view
        self._views.move_to_end(owner)
        while len(self._views) > self._views_max:
            self._views.popitem(last=False)
        try:
            self._flush(_owned_by(owner))
        except Exception as exc:
            _log().warning("alerts_topic_flush_failed", error=type(exc).__name__)
        if owner in self._dirty:  # a change kept racing every read: serve, then read again
            self._dirty.discard(owner)
            self._views.pop(owner, None)
            self._resync(_owned_by(owner), "load_raced")

    def _resync(self, match: Match, why: str) -> None:
        try:
            self._resnapshot(match, "upstream_desync")
        except Exception as exc:
            _log().warning("alerts_topic_resync_failed", error=type(exc).__name__, why=why)

    def _resync_all(self, why: str) -> None:
        self._views.clear()
        self._dirty.update(self._loads)
        self._resync(_any_alerts, why)


__all__ = [
    "ALERTS",
    "MAX_ITEMS_PER_DELTA",
    "SNAPSHOT_MAX",
    "AlertsSub",
    "AlertsTopic",
    "DeliveryReader",
    "DeliveryRecord",
    "delivery_item",
]
