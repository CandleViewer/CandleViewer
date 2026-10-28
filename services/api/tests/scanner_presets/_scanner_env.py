"""In-memory `ScannerPresetRepository` and audit fakes, and a router-only test app for
`/scanner/criteria` and `/scanner/presets*` (E08-T09 PR 2a, #4708), as
`tests/indicator_presets/_presets_env.py` is for indicator presets."""

from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.scanner import make_scanner_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.storage.repositories.scanner_presets import (
    MAX_PRESETS,
    ExpectedDefault,
    ScannerPresetConflictError,
    ScannerPresetFields,
    ScannerPresetNotFoundError,
    ScannerPresetRow,
    ScannerPresetWrite,
)

USER_A = uuid.UUID("00000000-0000-4000-8000-00000000000a")
USER_B = uuid.UUID("00000000-0000-4000-8000-00000000000b")
VIEWER = uuid.UUID("00000000-0000-4000-8000-00000000000c")
SID = uuid.UUID("00000000-0000-4000-8000-0000000000e1")
MISSING = "00000000-0000-4000-8000-0000000000ff"
#: E09 grants: every role reads market data; managers write their own presets, a viewer cannot.
PERMS = {
    USER_A: {"marketdata:read", "workspaces:read", "workspaces:write"},
    USER_B: {"marketdata:read", "workspaces:read", "workspaces:write"},
    VIEWER: {"marketdata:read", "workspaces:read"},
}
T0 = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
#: `ScannerPreset` is open for readers (C-6.3), so its exact key set is pinned here.
PRESET_KEYS = frozenset(
    "id name filter sort is_default unavailable_criteria version created_at updated_at".split()
)
MOMENTUM: dict[str, Any] = {
    "name": "Momentum",
    "filter": {
        "price_change_pct_24h": {"min": "0.05"},
        "turnover_24h": {"min": "50000000"},
        "funding_rate": {"max": "0.0005"},
    },
    "sort": "turnover_24h",
    "is_default": False,
}


def body(**over: Any) -> dict[str, Any]:
    """A valid `ScannerPresetInput` (a fresh dict on every call)."""
    return dict(MOMENTUM) | over


def principal(user: uuid.UUID = USER_A) -> AuditPrincipal:
    return AuditPrincipal(user, "u", frozenset(PERMS[user]), session_id=SID, ip="10.0.0.9")


class FakeScannerRepo:
    """The `ScannerPresetRepository` semantics in memory: owner-scoped reads and writes, the hard
    delete, the 100 cap, `ux_sp_name` (case-insensitive per owner), one default per owner (the
    expected default checked as the SQL checks it under the owner lock) and `version`."""

    def __init__(self) -> None:
        self.rows: dict[str, ScannerPresetRow] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail: Exception | None = None  # raised by every call (a store outage)
        self.race: Exception | None = None  # raised by the next write only (a lost race)
        self.tick = 0

    def _call(self, method: str, /, **kw: Any) -> None:
        self.calls.append((method, kw))
        if self.fail is not None:
            raise self.fail

    def _now(self) -> datetime:
        self.tick += 1
        return T0 + timedelta(microseconds=self.tick)

    def own(self, owner: str) -> list[ScannerPresetRow]:
        return [r for r in self.rows.values() if r.user_id == owner]

    def _taken(self, owner: str, name: str, exclude: str | None) -> bool:
        return any(r.name.lower() == name.lower() and r.id != exclude for r in self.own(owner))

    def seed(self, owner: uuid.UUID, name: str = "Seeded", **over: Any) -> str:
        """A preset of `owner` stored directly (a viewer cannot write one)."""
        preset_id = str(uuid.uuid4())
        now = self._now()
        row = ScannerPresetRow(preset_id, str(owner), name, {}, "turnover_24h", False, 1, now, now)
        self.rows[preset_id] = dataclasses.replace(row, **over)
        return preset_id

    async def list_own(self, owner: str) -> list[ScannerPresetRow]:
        self._call("list_own", owner=owner)
        return sorted(self.own(owner), key=lambda r: (r.name.lower(), r.id))

    async def get_own(self, owner: str, preset_id: str) -> ScannerPresetRow | None:
        self._call("get_own", owner=owner, preset_id=preset_id)
        return next((r for r in self.own(owner) if r.id == preset_id), None)

    async def get_default(self, owner: str) -> ScannerPresetRow | None:
        self._call("get_default", owner=owner)
        return next((r for r in self.own(owner) if r.is_default), None)

    async def is_foreign(self, owner: str, preset_id: str) -> bool:
        self._call("is_foreign", owner=owner, preset_id=preset_id)
        row = self.rows.get(preset_id)
        return row is not None and row.user_id != owner

    async def occupancy(
        self, owner: str, name: str | None = None, *, exclude_id: str | None = None
    ) -> tuple[int, bool]:
        self._call("occupancy", owner=owner, name=name, exclude_id=exclude_id)
        return len(self.own(owner)), name is not None and self._taken(owner, name, exclude_id)

    def _clear(
        self, owner: str, preset_id: str, expected: ExpectedDefault | None
    ) -> ScannerPresetRow | None:
        current = next((r for r in self.own(owner) if r.is_default and r.id != preset_id), None)
        if (None if current is None else ExpectedDefault(current.id, current.version)) != expected:
            raise ScannerPresetConflictError("conflict")
        if current is None:
            return None
        cleared = dataclasses.replace(
            current, is_default=False, version=current.version + 1, updated_at=self._now()
        )
        self.rows[current.id] = cleared
        return cleared

    def _raced(self) -> None:
        race, self.race = self.race, None
        if race is not None:
            raise race

    async def create(
        self,
        owner: str,
        preset_id: str,
        fields: ScannerPresetFields,
        *,
        expected_default: ExpectedDefault | None = None,
    ) -> ScannerPresetWrite:
        self._call("create", owner=owner, preset_id=preset_id)
        self._raced()
        if len(self.own(owner)) >= MAX_PRESETS:
            raise ScannerPresetConflictError("limit_reached")
        if self._taken(owner, fields.name, None):
            raise ScannerPresetConflictError("name_taken")
        cleared = self._clear(owner, preset_id, expected_default) if fields.is_default else None
        now = self._now()
        row = ScannerPresetRow(
            preset_id, owner, fields.name, dict(fields.filter), fields.sort, fields.is_default,
            1, now, now,
        )  # fmt: skip
        self.rows[preset_id] = row
        return ScannerPresetWrite(row, cleared)

    async def update(
        self,
        owner: str,
        preset_id: str,
        fields: ScannerPresetFields,
        *,
        expected_default: ExpectedDefault | None = None,
    ) -> ScannerPresetWrite:
        self._call("update", owner=owner, preset_id=preset_id)
        self._raced()
        current = next((r for r in self.own(owner) if r.id == preset_id), None)
        if current is None:
            raise ScannerPresetNotFoundError(preset_id)
        if self._taken(owner, fields.name, preset_id):
            raise ScannerPresetConflictError("name_taken")
        cleared = self._clear(owner, preset_id, expected_default) if fields.is_default else None
        row = dataclasses.replace(
            current, name=fields.name, filter=dict(fields.filter), sort=fields.sort,
            is_default=fields.is_default, version=current.version + 1, updated_at=self._now(),
        )  # fmt: skip
        self.rows[preset_id] = row
        return ScannerPresetWrite(row, cleared)

    async def delete(self, owner: str, preset_id: str) -> bool:
        self._call("delete", owner=owner, preset_id=preset_id)
        self._raced()
        if not any(r.id == preset_id for r in self.own(owner)):
            return False
        del self.rows[preset_id]
        return True


class Audit:
    """Records every `emit`; `fail` is raised by the next emits (a refusing audit writer)."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail: Exception | None = None

    async def emit(self, action: str, **kw: Any) -> None:
        if self.fail is not None:
            raise self.fail
        self.calls.append({"action": action, **kw})

    def actions(self) -> list[str]:
        return [c["action"] for c in self.calls]

    def denied(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["action"] == "rbac.denied"]


def new_ids() -> Any:
    """Deterministic ids for the service's `new_id`: 0193...0001, 0193...0002, ..."""
    counter = iter(range(1, 1_000_000))
    return lambda: uuid.UUID(int=(0x0193 << 112) | next(counter))


class Env:
    """Router-only app over a `FakeScannerRepo`; `user` is the caller (None = no session)."""

    def __init__(self, *, wired: bool = True) -> None:
        self.repo, self.audit = FakeScannerRepo(), Audit()
        self.user: uuid.UUID | None = USER_A
        self.repo_up = True
        self.grants: set[str] | None = None  # replaces PERMS[user]
        self.owner = False
        env = self

        class _Resolver:  # async, like the session-backed `SessionAuditPrincipalResolver`
            async def resolve(self, _request: Request) -> AuditPrincipal | None:
                if env.user is None:
                    return None
                perms = frozenset(PERMS[env.user] if env.grants is None else env.grants)
                return AuditPrincipal(env.user, "u", perms, session_id=SID, ip="10.0.0.9",
                                      is_owner=env.owner)  # fmt: skip

        app = FastAPI()
        app.include_router(make_scanner_router(
            lambda: self.repo if self.repo_up else None, _Resolver() if wired else None,
            self.audit, new_id=new_ids(),
        ))  # fmt: skip
        self.app = app
        self.c = TestClient(app)

    def create(self, **over: Any) -> dict[str, Any]:
        r = self.c.post("/scanner/presets", json=body(**over))
        assert r.status_code == 201, r.text
        return dict(r.json())

    def listed(self) -> list[dict[str, Any]]:
        r = self.c.get("/scanner/presets")
        assert r.status_code == 200, r.text
        return list(r.json()["items"])
