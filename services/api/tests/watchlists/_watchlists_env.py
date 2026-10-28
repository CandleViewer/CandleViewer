"""In-memory `WatchlistStore`, audit and metric fakes and a router-only test app for `/watchlists`
(E08-T07, #4706), as `tests/indicator_presets/_presets_env.py` is for presets. The catalogue is
passed in: a test module builds it from the recorded instruments page."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.watchlists import make_watchlists_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.storage.repositories.watchlists import (
    WatchlistFields,
    WatchlistNameTakenError,
    WatchlistNotFoundError,
    WatchlistRow,
    WatchlistStaleError,
    WatchlistWriteAhead,
)

USER_A = uuid.UUID("00000000-0000-4000-8000-00000000000a")
USER_B = uuid.UUID("00000000-0000-4000-8000-00000000000b")
VIEWER = uuid.UUID("00000000-0000-4000-8000-00000000000c")
SID = uuid.UUID("00000000-0000-4000-8000-0000000000e1")
WRITE = frozenset({"workspaces:read", "workspaces:write"})
PERMS = {USER_A: WRITE, USER_B: WRITE, VIEWER: frozenset({"workspaces:read"})}
T0 = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
MISSING = "00000000-0000-4000-8000-0000000000ff"
MAJORS: dict[str, Any] = {"name": "Majors", "symbols": ["BTCUSDT", "ETHUSDT"]}


def tag(watchlist: dict[str, Any]) -> dict[str, str]:
    """The `If-Match` of a list as last read: `W/"<id>:<version>"` (22 `WatchlistETag`)."""
    return {"If-Match": f'W/"{watchlist["id"]}:{watchlist["version"]}"'}


class FakeWatchlistStore:
    """The `WatchlistStore` semantics in memory: owner-scoped calls, `ux_wl_name` per owner as
    `lower()` folds it, the guarded replace, and the write-ahead hook awaited before anything
    changes (a hook that raises leaves the store as it was)."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, WatchlistRow] = {}
        self.fail: Exception | None = None  # raised by every call (a store outage)
        self.tick = 0

    def _check(self) -> None:
        if self.fail is not None:
            raise self.fail

    def _now(self) -> datetime:
        self.tick += 1
        return T0 + timedelta(microseconds=self.tick)

    def _taken(self, owner: uuid.UUID, name: str, exclude: uuid.UUID | None = None) -> bool:
        return any(
            r.user_id == owner and r.name.lower() == name.lower() and r.id != exclude
            for r in self.rows.values()
        )

    def own(self, owner: uuid.UUID, watchlist_id: uuid.UUID) -> WatchlistRow | None:
        row = self.rows.get(watchlist_id)
        return row if row is not None and row.user_id == owner else None

    def seed(self, owner: uuid.UUID, name: str = "Theirs") -> WatchlistRow:
        """A list stored directly, as another session would have."""
        wid, now = uuid.uuid4(), self._now()
        self.rows[wid] = WatchlistRow(wid, owner, name, ("SOLUSDT",), (), 1, now, now)
        return self.rows[wid]

    async def list_own(self, owner: uuid.UUID) -> list[WatchlistRow]:
        self._check()
        return sorted((r for r in self.rows.values() if r.user_id == owner),
                      key=lambda r: (r.created_at, r.id))  # fmt: skip

    async def get_own(self, owner: uuid.UUID, watchlist_id: uuid.UUID) -> WatchlistRow | None:
        self._check()
        return self.own(owner, watchlist_id)

    async def exists_for_other_owner(self, owner: uuid.UUID, watchlist_id: uuid.UUID) -> bool:
        self._check()
        row = self.rows.get(watchlist_id)
        return row is not None and row.user_id != owner

    async def create(
        self, owner: uuid.UUID, watchlist_id: uuid.UUID, fields: WatchlistFields, *,
        write_ahead: WatchlistWriteAhead,
    ) -> WatchlistRow:  # fmt: skip
        self._check()
        if self._taken(owner, fields.name):
            raise WatchlistNameTakenError
        now = self._now()
        row = WatchlistRow(watchlist_id, owner, fields.name, fields.symbols, fields.columns, 1,
                           now, now)  # fmt: skip
        await write_ahead(None, row)
        self.rows[watchlist_id] = row
        return row

    async def replace(
        self, owner: uuid.UUID, watchlist_id: uuid.UUID, fields: WatchlistFields, *,
        expected_version: int | None, write_ahead: WatchlistWriteAhead,
    ) -> WatchlistRow:  # fmt: skip
        self._check()
        before = self.own(owner, watchlist_id)
        if before is None:
            raise WatchlistNotFoundError
        if expected_version != before.version:
            raise WatchlistStaleError(before.version)
        if self._taken(owner, fields.name, watchlist_id):
            raise WatchlistNameTakenError
        after = replace(before, name=fields.name, symbols=fields.symbols, columns=fields.columns,
                        version=before.version + 1, updated_at=self._now())  # fmt: skip
        await write_ahead(before, after)
        self.rows[watchlist_id] = after
        return after

    async def delete(
        self, owner: uuid.UUID, watchlist_id: uuid.UUID, *, write_ahead: WatchlistWriteAhead
    ) -> WatchlistRow:
        self._check()
        before = self.own(owner, watchlist_id)
        if before is None:
            raise WatchlistNotFoundError
        await write_ahead(before, None)
        del self.rows[watchlist_id]
        return before


class Audit:
    """The audit emitter: records every call; `fail` is raised instead (a refused record)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail: Exception | None = None

    async def emit(self, action: str, **kw: Any) -> None:
        if self.fail is not None:
            raise self.fail
        self.calls.append({"action": action, **kw})

    def actions(self) -> list[str]:
        return [c["action"] for c in self.calls]


class Counter:
    """`watchlist_write_conflicts_total`'s child: counts `inc()`."""

    def __init__(self) -> None:
        self.value = 0.0

    def inc(self, amount: float = 1) -> None:
        self.value += amount


class Env:
    """Router-only app over a `FakeWatchlistStore`; `user` is the caller (None = no session),
    `catalogue` the instrument snapshot (None = none attached)."""

    def __init__(self, catalogue: Any) -> None:
        self.store, self.audit, self.conflicts = FakeWatchlistStore(), Audit(), Counter()
        self.user: uuid.UUID | None = USER_A
        self.store_up, self.catalogue = True, catalogue
        env = self

        class _Resolver:  # async, like the session-backed `SessionAuditPrincipalResolver`
            async def resolve(self, _request: Request) -> AuditPrincipal | None:
                if env.user is None:
                    return None
                return AuditPrincipal(env.user, "u", PERMS[env.user], session_id=SID, ip="10.0.0.9")

        ids = iter(range(1, 1_000_000))
        app = FastAPI()
        app.include_router(make_watchlists_router(
            lambda: self.store if self.store_up else None, _Resolver(), self.audit,
            lambda: self.catalogue, conflicts=self.conflicts,
            new_id=lambda: uuid.UUID(int=(0x0193 << 112) | next(ids)),
        ))  # fmt: skip
        self.app = app  # for an `httpx.ASGITransport` (a streamed body read as it arrives)
        self.c = TestClient(app)

    def create(self, **over: Any) -> dict[str, Any]:
        r = self.c.post("/watchlists", json=dict(MAJORS) | over)
        assert r.status_code == 201, r.text
        return dict(r.json())

    def listed(self) -> list[dict[str, Any]]:
        r = self.c.get("/watchlists")
        assert r.status_code == 200, r.text
        return list(r.json()["items"])
