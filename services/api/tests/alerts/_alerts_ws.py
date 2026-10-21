"""E40-T04 PR-B test helpers: `alerts` subscribers on the real gateway parts (`ConnectionAuthz`,
`TopicEmitter`, `SequencingHub`), each frame validated against 23-ws-protocol.md §13-§15 (§15.7
`AlertUpdate` for `snap`/`d`), an in-memory deliveries reader, and the topic on a hub of its own."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from candleviewer.alerts.ws_topic import AlertsTopic
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.storage.repositories.alert_deliveries_sqlalchemy import DeliveryRow
from candleviewer.storage.repositories.alerts import Page
from candleviewer.ws.permissions import ConnectionAuthz, Subscription, SubscriptionServices
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody, TopicEmitter
from tests.unit.ws._seq_support import validate

USER_A = UUID("00000000-0000-4000-8000-00000000000a")
USER_B = UUID("00000000-0000-4000-8000-00000000000b")
USER_C = UUID("00000000-0000-4000-8000-00000000000c")
ALERT_A = "13000000-0000-4000-8000-00000000000a"
ALERT_B = "13000000-0000-4000-8000-00000000000b"
T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
READ = frozenset({Permission.ALERTS_READ})


def principal(user: UUID, permissions: frozenset[Permission] = READ) -> PrincipalSnapshot:
    return PrincipalSnapshot(user, frozenset({"manager"}), permissions)


def is_attached(topic: AlertsTopic[Any]) -> bool:
    """A deliveries reader is attached: `build` can read, so a subscription is not left pending."""
    return topic._reader is not None


async def drained(topic: AlertsTopic[Any], within_s: float = 5) -> None:
    """Every queued change has been read and published (the topic's worker must be started)."""
    await asyncio.wait_for(topic._queue.join(), timeout=within_s)


async def landed(topic: AlertsTopic[Any], within_s: float = 5) -> None:
    """Every snapshot load in flight has landed (and flushed what it woke)."""
    async with asyncio.timeout(within_s):
        while topic._loads:
            await asyncio.gather(*list(topic._loads.values()), return_exceptions=True)


async def settled(topic: AlertsTopic[Any], within_s: float = 5) -> None:
    """The changes are published and the loads they and the subscribers started have landed."""
    await drained(topic, within_s)
    await landed(topic, within_s)


class FakeReader:
    """`DeliveryReader` over rows in memory; records each read and can hold or fail one.

    A `list_page` takes its rows when it starts, then waits on `gate` and runs `on_list_page`: a
    change that lands while the read is held or running is not in them, as a slow query's would be
    (`pages` keeps what each read returned)."""

    def __init__(self) -> None:
        self.rows: dict[int, DeliveryRow] = {}
        self.calls: list[tuple[str, Any]] = []
        self.pages: list[list[int]] = []  # the delivery ids each `list_page` returned
        self.fail: set[str] = set()  # reads that fail every time
        self.flaky: dict[str, int] = {}  # reads that fail this many more times, then work
        self.gate: asyncio.Event | None = None  # `list_page` waits on it (a load held mid-read)
        self.on_list_page: Callable[[], Awaitable[None]] | None = None  # runs mid-read
        self.entered = asyncio.Event()  # set once a `list_page` has started
        self.reading = 0  # `list_page` reads in flight now
        self.most_reading = 0  # the most that were in flight at once
        self.next_id = 100

    def add(self, user: UUID | None, **over: Any) -> DeliveryRow:
        self.next_id += 1
        row = DeliveryRow(
            id=self.next_id, alert_id=ALERT_A if user == USER_A else ALERT_B,
            user_id=None if user is None else str(user), channel="in_app", status="sent",
            title="BTC reclaims 64k", body="BTCUSDT crossed 64000", context={"symbol": "BTCUSDT"},
            attempt=1, http_status=None, error_message=None,
            queued_at=T0 + timedelta(seconds=self.next_id), sent_at=T0, acked_at=None,
            acked_by=None, severity="info",
        )  # fmt: skip
        row = replace(row, **over)
        self.rows[row.id] = row
        return row

    def set(self, row_id: int, **over: Any) -> DeliveryRow:
        self.rows[row_id] = replace(self.rows[row_id], **over)
        return self.rows[row_id]

    def ack(self, row_id: int) -> DeliveryRow:
        """The owner acknowledged the delivery (what the inbox route commits)."""
        return self.set(row_id, status="acked", acked_at=self.rows[row_id].queued_at)

    def count(self, name: str) -> int:
        """How many times *name* was read."""
        return sum(1 for call, _ in self.calls if call == name)

    def _check(self, name: str) -> None:
        if name in self.fail:
            raise RuntimeError(f"{name} failed")
        if self.flaky.get(name, 0) > 0:
            self.flaky[name] -= 1
            raise RuntimeError(f"{name} failed")

    async def list_page(
        self, *, user_id: str, unacked_only: bool = False, limit: int = 50
    ) -> Page[DeliveryRow]:
        self.calls.append(("list_page", user_id))
        self.reading += 1
        self.most_reading = max(self.most_reading, self.reading)
        try:
            self.entered.set()
            items = sorted(
                (r for r in self.rows.values()
                 if r.user_id == user_id
                 and (not unacked_only or (r.status == "sent" and r.acked_at is None))),
                key=lambda r: (r.queued_at, r.id), reverse=True,
            )[:limit]  # fmt: skip
            if self.gate is not None:
                await self.gate.wait()
            if self.on_list_page is not None:
                await self.on_list_page()
            self._check("list_page")
            self.pages.append([r.id for r in items])
            return Page(items, None)
        finally:
            self.reading -= 1

    async def unacked_count(self, user_id: str) -> int:
        self.calls.append(("unacked_count", user_id))
        self._check("unacked_count")
        return sum(
            r.user_id == user_id and r.status == "sent" and r.acked_at is None
            for r in self.rows.values()
        )

    async def get_many(self, delivery_ids: Sequence[int]) -> list[DeliveryRow]:
        self.calls.append(("get_many", tuple(delivery_ids)))
        self._check("get_many")
        return [self.rows[i] for i in sorted(set(delivery_ids)) if i in self.rows]

    async def failure_notices(
        self, user_ids: Sequence[str], failed_ids: Sequence[int]
    ) -> list[DeliveryRow]:
        self.calls.append(("failure_notices", (tuple(user_ids), tuple(failed_ids))))
        self._check("failure_notices")
        failed = {str(i) for i in failed_ids}
        return [
            r for r in self.rows.values()
            if r.user_id in user_ids and r.status == "sent" and r.acked_at is None
            and str(r.context.get("failed_delivery_id")) in failed
        ]  # fmt: skip


class Conn:
    """One authenticated socket on `hub`: its subscription and the frames it was sent."""

    def __init__(
        self, hub: SequencingHub, topic: AlertsTopic[SnapshotBody], principal: PrincipalSnapshot
    ) -> None:
        self.frames: list[dict[str, Any]] = []
        self.authz = ConnectionAuthz(principal, SubscriptionServices(snapshots=topic))
        self.emitter = TopicEmitter(
            self._push, connection_id="ws_test", wall_ms=lambda: 1_790_000_000_000,
            clock=lambda: 1_000.0, source=topic,
        )  # fmt: skip
        hub.register(self.authz, self.emitter)

    def _push(self, frame: dict[str, Any]) -> None:
        validate(frame)
        self.frames.append(frame)

    def sub(self, **opts: Any) -> dict[str, Any]:
        """Subscribe to `alerts` and return the `sub_ok` result; the `snap` follows its load."""
        entry: dict[str, Any] = {"ch": "alerts"} | ({"opts": opts} if opts else {})
        result, sub = self.authz.admit(entry)
        if sub is not None:
            sub.announced = True  # the gateway's `sub_ok` is queued (#2831)
            self.emitter.flush_pending([sub])
        return result

    def subscription(self) -> Subscription:
        """The connection's one subscription."""
        (sub,) = self.authz.by_id.values()
        return sub

    def take(self) -> list[tuple[str, dict[str, Any]]]:
        """The type and payload of every frame since the last take."""
        frames, self.frames = self.frames, []
        return [(frame["t"], frame["p"]) for frame in frames]

    def snap_reasons(self) -> list[str]:
        """The `meta.reason` of each `snap` since the last take, which does not consume them."""
        return [frame["meta"]["reason"] for frame in self.frames if frame["t"] == "snap"]

    def items(self) -> list[tuple[str, list[int], int | None]]:
        """Per frame since the last take: its type, its delivery ids and its unacked count."""
        return [(t, [d["id"] for d in p["deliveries"]], p.get("unacked_count"))
                for t, p in self.take()]  # fmt: skip


class World:
    """The topic on a hub of its own, reading a `FakeReader`; the test starts its worker. A load's
    backoff is recorded in `slept`, never waited (it holds on `backoff_gate` when a test sets one),
    and its jitter is the top of its range. `broken` names the hub calls that raise."""

    def __init__(self, *, attached: bool = True, **topic_kw: Any) -> None:
        self.hub = SequencingHub()
        self.reader = FakeReader()
        self.slept: list[float] = []
        self.backoff_gate: asyncio.Event | None = None  # a backoff waits on it
        self.backing_off = asyncio.Event()  # set once a load has begun to back off
        self.broken: set[str] = set()  # "publish", "flush_pending", "resnapshot": raise
        topic_kw.setdefault("sleep", self._sleep)
        topic_kw.setdefault("rng", lambda: 1.0)
        self.topic = AlertsTopic(
            self._hub("publish"), self._hub("flush_pending"), self._hub("resnapshot"),
            SnapshotBody, **topic_kw,
        )  # fmt: skip
        if attached:
            self.topic.attach(self.reader)

    def _hub(self, name: str) -> Callable[..., int]:
        """The hub's *name*, which raises while it is in `broken` (a fan-out that is down)."""
        real: Callable[..., int] = getattr(self.hub, name)

        def call(*args: Any, **kwargs: Any) -> int:
            if name in self.broken:
                raise RuntimeError(f"hub {name} down")
            return real(*args, **kwargs)

        return call

    async def _sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.backing_off.set()
        if self.backoff_gate is not None:
            await self.backoff_gate.wait()
        await asyncio.sleep(0)  # a yield, as a real wait would be: other tasks run meanwhile

    def conn(self, user: UUID, permissions: frozenset[Permission] = READ) -> Conn:
        return Conn(self.hub, self.topic, principal(user, permissions))

    async def loads(self) -> None:
        """Every snapshot load in flight has landed (and flushed what it woke)."""
        await landed(self.topic)

    async def loaded(self, user: UUID) -> None:
        """*user*'s snapshot load, if one is in flight, has landed; another's may still be."""
        task = self.topic._loads.get(user)
        if task is not None:
            await asyncio.wait_for(task, timeout=5)

    async def changes(self) -> None:
        """Every queued change has been read and published (the worker must be started)."""
        await drained(self.topic)

    def loading(self) -> list[UUID]:
        """The owners whose snapshot load is in flight."""
        return list(self.topic._loads)

    def views(self) -> list[UUID]:
        """The owners whose view is cached, least recently used first."""
        return list(self.topic._views)

    def queued(self) -> int:
        """The change batches no worker has taken yet."""
        return self.topic._queue.qsize()

    def tasks(self) -> list[asyncio.Task[None]]:
        """The worker and every load in flight."""
        return [t for t in (self.topic._worker, *self.topic._loads.values()) if t is not None]

    def running(self) -> bool:
        """The worker is started and has not ended."""
        worker = self.topic._worker
        return worker is not None and not worker.done()
