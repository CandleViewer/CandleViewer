"""In-memory delivery store + test app for the E40-T04 inbox routes (`/alerts/deliveries*`).

`FakeDeliveryStore` mirrors `SqlAlchemyAlertDeliveryRepository`'s conditional updates (ack only
`sent` rows of the caller, desktop reports only `queued` desktop rows, ack-all in bounded
batches). The app mounts the deliveries router before the real `/alerts` CRUD router, as
`create_app()` does, so a shadowed route shows up here too.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.alert_deliveries import DenialBudget, make_alert_deliveries_router
from candleviewer.api.alerts import make_alerts_router
from candleviewer.rules.manager import Actor
from candleviewer.rules.vocabulary import default_registry
from candleviewer.storage.repositories.alert_deliveries_sqlalchemy import DeliveryRow
from candleviewer.storage.repositories.alerts import Page
from candleviewer.storage.repositories.alerts_sqlalchemy import decode_cursor, encode_cursor
from tests.alerts._alert_api_env import USER_A, USER_B, Audit, FakeAlertRepo

ALERT_A = "13000000-0000-4000-8000-00000000000a"
ALERT_B = "13000000-0000-4000-8000-00000000000b"
T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


class Metrics:
    def __init__(self) -> None:
        self.seen: list[tuple[str, tuple[str, ...], float]] = []

    def __call__(self, name: str, labels: tuple[str, ...]) -> Any:
        rec = self.seen

        class _I:
            def inc(self, amount: float = 1) -> None:
                rec.append((name, labels, amount))

            def observe(self, amount: float) -> None:
                rec.append((name, labels, amount))

        return _I()


class FakeDeliveryStore:
    def __init__(self) -> None:
        self.rows: dict[int, DeliveryRow] = {}
        self.owners: dict[str, str] = {ALERT_A: USER_A, ALERT_B: USER_B}
        self.next_id = 100
        self.ack_all_calls: list[int] = []
        self.desktop_reports: list[tuple[int, str]] = []
        self.clock = T0

    def add(self, *, user: str = USER_A, alert: str = ALERT_A, **over: Any) -> DeliveryRow:
        self.next_id += 1
        row = DeliveryRow(
            id=self.next_id, alert_id=alert, user_id=user, channel="in_app", status="sent",
            title="BTC reclaims 64k", body="BTCUSDT crossed 64000", context={"symbol": "BTCUSDT"},
            attempt=1, http_status=None, error_message=None,
            queued_at=T0 + timedelta(seconds=self.next_id), sent_at=T0, acked_at=None,
            acked_by=None, severity="info",
        )  # fmt: skip
        row = replace(row, **over)
        self.rows[row.id] = row
        return row

    async def get(self, delivery_id: int) -> DeliveryRow | None:
        return self.rows.get(delivery_id)

    async def alert_owner(self, alert_id: str) -> str | None:
        return self.owners.get(alert_id)

    async def unacked_count(self, user_id: str) -> int:
        return sum(
            r.user_id == user_id and r.status == "sent" and r.acked_at is None
            for r in self.rows.values()
        )

    async def list_page(
        self,
        *,
        user_id: str,
        alert_id: str | None = None,
        status: str | None = None,
        unacked_only: bool = False,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[DeliveryRow]:
        after = decode_cursor(cursor) if cursor else None
        items = sorted(
            (
                r
                for r in self.rows.values()
                if r.user_id == user_id
                and (alert_id is None or r.alert_id == alert_id)
                and (status is None or r.status == status)
                and (not unacked_only or (r.status == "sent" and r.acked_at is None))
                and (from_ts is None or r.queued_at >= from_ts)
                and (to_ts is None or r.queued_at < to_ts)
                and (after is None or (r.queued_at, r.id) < (after[0], int(after[1])))
            ),
            key=lambda r: (r.queued_at, r.id),
            reverse=True,
        )
        page = items[:limit]
        more = len(items) > limit
        return Page(page, encode_cursor(page[-1].queued_at, page[-1].id) if more else None)

    async def ack(self, delivery_id: int, user_id: str) -> DeliveryRow | None:
        r = self.rows.get(delivery_id)
        if r is None or r.user_id != user_id or r.status != "sent" or r.acked_at is not None:
            return None
        self.clock += timedelta(seconds=1)
        new = replace(r, status="acked", acked_at=self.clock, acked_by=user_id)
        self.rows[delivery_id] = new
        return new

    async def ack_all(self, user_id: str, cap: int = 1000) -> list[int]:
        todo = sorted(
            (r for r in self.rows.values()
             if r.user_id == user_id and r.status == "sent" and r.acked_at is None),
            key=lambda r: r.queued_at, reverse=True,
        )[:cap]  # fmt: skip
        for r in todo:
            await self.ack(r.id, user_id)
        self.ack_all_calls.append(len(todo))
        return [r.id for r in todo]

    async def report_desktop(
        self, delivery_id: int, *, user_id: str, error: str | None, notice_title: str
    ) -> DeliveryRow | None:
        self.desktop_reports.append((delivery_id, user_id))
        r = self.rows.get(delivery_id)
        if r is None or r.user_id != user_id or r.channel != "desktop" or r.status != "queued":
            return None
        if error is None:
            new = replace(r, status="sent", sent_at=self.clock, error_message=None)
        else:
            new = replace(r, status="failed", error_message=error)
            self.add(user=r.user_id or USER_A, alert=r.alert_id, title=notice_title, body="",
                     context={"channel_failure": True, "failed_delivery_id": r.id})  # fmt: skip
        self.rows[delivery_id] = new
        return new


class Env:
    """Both routers mounted as `create_app()` mounts them; `user`/`perms` switch the caller."""

    def __init__(self, *, wired: bool = True, denials: DenialBudget | None = None) -> None:
        self.store, self.audit, self.metrics = FakeDeliveryStore(), Audit(), Metrics()
        self.changes: list[list[int]] = []
        self.change_fails = False
        self.change_hangs = False
        self.user: str | None = USER_A
        self.perms = frozenset({"alerts:read", "alerts:write"})
        self.store_up = True

        def resolve(_r: Request) -> Actor | None:
            return None if self.user is None else Actor(self.user, "s", self.perms)

        async def on_change(ids: Sequence[int]) -> None:
            self.changes.append(list(ids))
            if self.change_fails:
                raise RuntimeError("topic down")
            if self.change_hangs:
                await asyncio.Event().wait()  # never set: only the router's timeout ends it

        app = FastAPI()
        app.include_router(
            make_alert_deliveries_router(
                lambda: self.store if self.store_up else None,
                resolve if wired else None,
                self.audit,
                metric=self.metrics,
                now=lambda: T0 + timedelta(hours=1),
                on_change=on_change,
                denials=denials,
            )
        )
        app.include_router(
            make_alerts_router(lambda: FakeAlertRepo(), default_registry, resolve, self.audit)
        )
        self.c = TestClient(app)

    def denials(self) -> list[dict[str, Any]]:
        return [kw for a, kw in self.audit.calls if a == "alert.denied"]
