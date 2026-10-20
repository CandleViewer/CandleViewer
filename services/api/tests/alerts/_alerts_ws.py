"""E40-T04 PR-B test helpers: `alerts` subscribers on the real gateway parts (`ConnectionAuthz`,
`TopicEmitter`, `SequencingHub`), each frame validated against 23-ws-protocol.md §13-§15 (§15.7
`AlertUpdate` for `snap`/`d`), an in-memory deliveries reader, and the topic on a hub of its own."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from candleviewer.alerts.ws_topic import AlertsTopic
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.storage.repositories.alert_deliveries_sqlalchemy import DeliveryRow
from candleviewer.storage.repositories.alerts import Page
from candleviewer.ws.permissions import ConnectionAuthz, SubscriptionServices
from candleviewer.ws.sequencing import SequencingHub, SnapshotBody, TopicEmitter
from tests.unit.ws._seq_support import validate

USER_A = UUID("00000000-0000-4000-8000-00000000000a")
USER_B = UUID("00000000-0000-4000-8000-00000000000b")
ALERT_A = "13000000-0000-4000-8000-00000000000a"
ALERT_B = "13000000-0000-4000-8000-00000000000b"
T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
READ = frozenset({Permission.ALERTS_READ})


def principal(user: UUID, permissions: frozenset[Permission] = READ) -> PrincipalSnapshot:
    return PrincipalSnapshot(user, frozenset({"manager"}), permissions)


class FakeReader:
    """`DeliveryReader` over rows in memory; records each read and can hold or fail one."""

    def __init__(self) -> None:
        self.rows: dict[int, DeliveryRow] = {}
        self.calls: list[tuple[str, Any]] = []
        self.fail: set[str] = set()
        self.gate: asyncio.Event | None = None  # `list_page` waits on it (a load held mid-read)
        self.entered = asyncio.Event()  # set once a `list_page` has started
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

    def _check(self, name: str) -> None:
        if name in self.fail:
            raise RuntimeError(f"{name} failed")

    async def list_page(
        self, *, user_id: str, unacked_only: bool = False, limit: int = 50
    ) -> Page[DeliveryRow]:
        self.calls.append(("list_page", user_id))
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        self._check("list_page")
        items = sorted(
            (r for r in self.rows.values()
             if r.user_id == user_id
             and (not unacked_only or (r.status == "sent" and r.acked_at is None))),
            key=lambda r: (r.queued_at, r.id), reverse=True,
        )  # fmt: skip
        return Page(items[:limit], None)

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

    def take(self) -> list[tuple[str, dict[str, Any]]]:
        """The type and payload of every frame since the last take."""
        frames, self.frames = self.frames, []
        return [(frame["t"], frame["p"]) for frame in frames]

    def items(self) -> list[tuple[str, list[int], int | None]]:
        """Per frame since the last take: its type, its delivery ids and its unacked count."""
        return [(t, [d["id"] for d in p["deliveries"]], p.get("unacked_count"))
                for t, p in self.take()]  # fmt: skip


class World:
    """The topic on a hub of its own, reading a `FakeReader`, its worker running."""

    def __init__(self, **topic_kw: Any) -> None:
        self.hub = SequencingHub()
        self.reader = FakeReader()
        self.topic = AlertsTopic(
            self.hub.publish, self.hub.flush_pending, self.hub.resnapshot, SnapshotBody,
            **topic_kw,
        )  # fmt: skip
        self.topic.attach(self.reader)

    def conn(self, user: UUID, permissions: frozenset[Permission] = READ) -> Conn:
        return Conn(self.hub, self.topic, principal(user, permissions))

    async def loads(self) -> None:
        """Every snapshot load in flight has landed (and flushed what it woke)."""
        while self.topic._loads:
            await asyncio.gather(*list(self.topic._loads.values()), return_exceptions=True)

    async def changes(self) -> None:
        """Every queued change has been read and published (the worker must be started)."""
        await asyncio.wait_for(self.topic._queue.join(), timeout=5)
