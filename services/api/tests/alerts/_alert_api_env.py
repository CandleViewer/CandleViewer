"""In-memory `AlertRepository` + test app for the /alerts router (E40-T02)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.alerts import make_alerts_router
from candleviewer.rules.manager import Actor
from candleviewer.rules.vocabulary import default_registry
from candleviewer.storage.repositories.alerts import (
    AlertConflictError,
    AlertNameTakenError,
    AlertRow,
    Page,
)

USER_A = "00000000-0000-4000-8000-00000000000a"
USER_B = "00000000-0000-4000-8000-00000000000b"
T0 = datetime(2026, 10, 5, tzinfo=UTC)

PRICE_CROSS: dict[str, Any] = {
    "name": "BTC reclaims 64k",
    "symbol": "BTCUSDT",
    "trigger_mode": "once",
    "channels": ["in_app", "desktop"],
    "condition_ir": {
        "ir_version": 1,
        "trigger": {"type": "on_price_update", "debounce_ms": 250},
        "conditions": {
            "node_id": "c1",
            "op": "crosses_above",
            "left": {"metric": "price"},
            "right": {"const": 64000},
        },
    },
    "message_template": "BTCUSDT crossed 64000 (last {{market.last_price}})",
    "expires_at": "2026-09-21T00:00:00Z",
}


class FakeAlertRepo:
    def __init__(self) -> None:
        self.rows: dict[str, AlertRow] = {}
        self.deleted: set[str] = set()
        self.tick = 0
        self.refusal: Exception | None = (
            None  # what every write raises while set, as the store would
        )

    def _now(self) -> datetime:
        self.tick += 1
        return T0 + timedelta(seconds=self.tick)

    def _taken(self, owner: str, name: str, skip: str | None = None) -> bool:
        return any(
            r.owner_user_id == owner and r.name.lower() == name.lower() and r.id != skip
            for r in self.rows.values()
            if r.id not in self.deleted
        )

    async def create(
        self, *, owner_user_id: str, alert_id: str | None = None, **f: Any
    ) -> AlertRow:
        if self.refusal is not None:
            raise self.refusal
        if self._taken(owner_user_id, f["name"]):
            raise AlertNameTakenError(f["name"])
        now = self._now()
        row = AlertRow(
            id=alert_id or str(uuid.uuid4()),
            owner_user_id=owner_user_id,
            cooldown_seconds=60,
            snoozed_until=None,
            has_webhook=False,
            last_fired_at=None,
            fire_count=0,
            created_at=now,
            updated_at=now,
            **f,
        )
        self.rows[row.id] = row
        return row

    async def get(self, alert_id: str) -> AlertRow | None:
        return None if alert_id in self.deleted else self.rows.get(alert_id)

    async def list_page(
        self,
        owner_user_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
        enabled: bool | None = None,
        symbol: str | None = None,
    ) -> Page[AlertRow]:
        if cursor == "bad":
            raise ValueError("invalid cursor")
        items = [
            r
            for r in self.rows.values()
            if r.owner_user_id == owner_user_id
            and r.id not in self.deleted
            and (enabled is None or r.enabled == enabled)
            and (symbol is None or r.symbol == symbol)
        ]
        return Page(items[:limit], "next" if len(items) > limit else None)

    async def update(self, alert_id: str, *, if_match: datetime, **f: Any) -> AlertRow:
        row = await self.get(alert_id)
        if row is None or row.updated_at != if_match:
            raise AlertConflictError(alert_id)
        if self.refusal is not None:
            raise self.refusal
        if self._taken(row.owner_user_id, f["name"], skip=alert_id):
            raise AlertNameTakenError(f["name"])
        new = replace(row, updated_at=self._now(), **f)
        self.rows[alert_id] = new
        return new

    async def soft_delete(self, alert_id: str) -> bool:
        if await self.get(alert_id) is None:
            return False
        self.deleted.add(alert_id)
        return True

    async def set_enabled(self, alert_id: str, enabled: bool) -> AlertRow | None:
        row = await self.get(alert_id)
        if row is None:
            return None
        self.rows[alert_id] = replace(row, enabled=enabled, updated_at=self._now())
        return self.rows[alert_id]


class Audit:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls.append((action, kw))

    def actions(self) -> list[str]:
        return [a for a, _ in self.calls]


class Env:
    """App with two users: `user` is the caller, `perms` its permissions, `granted` its account
    grants and `owner` whether it holds the Owner role."""

    def __init__(self, *, wired: bool = True) -> None:
        self.repo, self.audit = FakeAlertRepo(), Audit()
        self.user: str | None = USER_A
        self.perms = frozenset({"alerts:read", "alerts:write"})
        self.granted: frozenset[str] = frozenset()  # the caller's account grants
        self.owner = False  # the caller holds the Owner role
        self.compiles: list[str | None] = []
        self.repo_up, self.registry_up = True, True

        def resolve(_r: Request) -> Actor | None:
            if self.user is None:
                return None
            return Actor(self.user, "s", self.perms, self.granted, is_owner=self.owner)

        app = FastAPI()
        app.include_router(
            make_alerts_router(
                lambda: self.repo if self.repo_up else None,
                lambda: default_registry() if self.registry_up else None,
                resolve if wired else None,
                self.audit,
                on_compile=lambda s, reason: self.compiles.append(reason),
            )
        )
        self.c = TestClient(app)

    def create(self, **over: Any) -> dict[str, Any]:
        r = self.c.post("/alerts", json=PRICE_CROSS | over)
        assert r.status_code == 201, r.text
        return dict(r.json())
