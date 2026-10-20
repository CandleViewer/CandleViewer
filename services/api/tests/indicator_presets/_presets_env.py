"""In-memory `IndicatorPresetRepository`, audit and metric fakes, and a router-only test app for
`/indicator-presets` (E13-T03, #427), as `tests/drawings/_drawings_api_env.py` is for drawings."""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.indicator_presets import make_indicator_presets_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.db.builtin_indicator_presets import BUILTIN_PRESETS
from candleviewer.orderflow.indicators.catalogue import default_catalogue
from candleviewer.storage.repositories.indicator_presets import (
    MAX_IMPORT_PRESETS,
    MAX_LIVE_PRESETS,
    Occupancy,
    OtherClass,
    PresetConflictError,
    PresetFields,
    PresetNotFoundError,
    PresetRow,
    unique_name,
)

USER_A = uuid.UUID("00000000-0000-4000-8000-00000000000a")
USER_B = uuid.UUID("00000000-0000-4000-8000-00000000000b")
VIEWER = uuid.UUID("00000000-0000-4000-8000-00000000000c")
SID = uuid.UUID("00000000-0000-4000-8000-0000000000e1")
#: E09 grants: managers read and write their own presets, a viewer only reads.
PERMS = {USER_A: {"workspaces:read", "workspaces:write"},
         USER_B: {"workspaces:read", "workspaces:write"}, VIEWER: {"workspaces:read"}}  # fmt: skip
T0 = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
BUILTIN_IDS = frozenset(p.id for p in BUILTIN_PRESETS)
EMA9 = BUILTIN_PRESETS[0].id  # the built-in `ema(9)`
#: `IndicatorPreset` is open for readers (C-6.3), so its exact key set is pinned here: no
#: internal column (`deleted_at`) may ever reach a response.
PRESET_KEYS = frozenset(("id owner_user_id indicator_code name params style pane_target "
                         "is_builtin is_favourite created_at updated_at").split())  # fmt: skip
ATR14: dict[str, Any] = {"name": "ATR 14", "indicator_code": "atr", "params": {"n": 14},
                         "style": {}, "pane_target": "subpane", "is_favourite": False}  # fmt: skip


def principal(user: uuid.UUID = USER_A) -> AuditPrincipal:
    return AuditPrincipal(user, "u", frozenset(PERMS[user]), session_id=SID, ip="10.0.0.9")


def body(**over: Any) -> dict[str, Any]:
    """A valid `IndicatorPresetInput` (a fresh dict on every call)."""
    return dict(ATR14) | over


class FakePresetRepo:
    """The `IndicatorPresetRepository` semantics in memory: the 18 built-ins seeded, owner-scoped
    reads and writes, the soft delete, the 500 cap, `ux_ip_name` (case-insensitive per owner and
    code among live rows) and an all-or-nothing import with the SQL implementation's renaming."""

    def __init__(self) -> None:
        self.rows: dict[str, PresetRow] = {}
        self.deleted: set[str] = set()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail: Exception | None = None  # raised by every call (a store outage)
        self.tick = 0
        for p in BUILTIN_PRESETS:
            self.rows[p.id] = PresetRow(p.id, None, p.indicator_code, p.name, dict(p.params), {},
                                        p.pane_target, True, False, T0, T0)  # fmt: skip

    def _call(self, name: str, **kw: Any) -> None:
        self.calls.append((name, kw))
        if self.fail is not None:
            raise self.fail

    def _live(self) -> list[PresetRow]:
        return [r for i, r in self.rows.items() if i not in self.deleted]

    def _now(self) -> datetime:
        self.tick += 1  # every write moves `updated_at` strictly forward
        return T0 + timedelta(microseconds=self.tick)

    def _taken(self, owner: str | None, code: str, name: str, exclude: str | None) -> bool:
        return any(
            r.owner_user_id == owner and r.indicator_code == code
            and r.name.lower() == name.lower() and r.id != exclude
            for r in self._live()
        )  # fmt: skip

    def seed(self, owner: uuid.UUID, name: str = "Seeded", code: str = "atr") -> str:
        """A live preset of `owner` stored directly (a viewer cannot write one)."""
        preset_id = str(uuid.uuid4())
        fields = PresetFields(code, name, {"n": 14}, {}, "subpane", False)
        self._insert(str(owner), preset_id, fields)
        return preset_id

    def own_live(self, owner: str) -> list[PresetRow]:
        return [r for r in self._live() if r.owner_user_id == owner and not r.is_builtin]

    async def list_visible(self, owner: str) -> list[PresetRow]:
        self._call("list_visible", owner=owner)
        visible = [r for r in self._live() if r.owner_user_id in (None, owner)]
        return sorted(visible, key=lambda r: (not r.is_builtin, r.indicator_code,
                                              r.name.lower(), r.id))  # fmt: skip

    async def get_own(self, owner: str, preset_id: str) -> PresetRow | None:
        self._call("get_own", owner=owner, preset_id=preset_id)
        return next((r for r in self.own_live(owner) if r.id == preset_id), None)

    async def other_class(self, owner: str, preset_id: str) -> OtherClass | None:
        self._call("other_class", owner=owner, preset_id=preset_id)
        row = self.rows.get(preset_id)
        if row is None or preset_id in self.deleted or row.owner_user_id == owner:
            return None
        return "builtin" if row.is_builtin else "foreign"

    async def occupancy(
        self, owner: str, name_key: tuple[str, str] | None = None, *, exclude_id: str | None = None
    ) -> Occupancy:
        self._call("occupancy", owner=owner, name_key=name_key, exclude_id=exclude_id)
        taken = name_key is not None and self._taken(owner, *name_key, exclude_id)
        return Occupancy(len(self.own_live(owner)), taken)

    def _insert(self, owner: str, preset_id: str, fields: PresetFields) -> PresetRow:
        if self._taken(owner, fields.indicator_code, fields.name, None):
            raise PresetConflictError("name_taken")
        now = self._now()
        self.rows[preset_id] = PresetRow(
            preset_id, owner, fields.indicator_code, fields.name, fields.params, fields.style,
            fields.pane_target, False, fields.is_favourite, now, now,
        )  # fmt: skip
        return self.rows[preset_id]

    async def create(self, owner: str, preset_id: str, fields: PresetFields) -> PresetRow:
        self._call("create", owner=owner, preset_id=preset_id)
        if len(self.own_live(owner)) >= MAX_LIVE_PRESETS:
            raise PresetConflictError("limit_reached")
        return self._insert(owner, preset_id, fields)

    async def update(self, owner: str, preset_id: str, fields: PresetFields) -> PresetRow:
        self._call("update", owner=owner, preset_id=preset_id)
        row = next((r for r in self.own_live(owner) if r.id == preset_id), None)
        if row is None:
            raise PresetNotFoundError(preset_id)
        if self._taken(owner, row.indicator_code, fields.name, preset_id):
            raise PresetConflictError("name_taken")
        self.rows[preset_id] = dataclasses.replace(
            row, name=fields.name, params=fields.params, style=fields.style,
            pane_target=fields.pane_target, is_favourite=fields.is_favourite,
            updated_at=self._now(),
        )  # fmt: skip
        return self.rows[preset_id]

    async def soft_delete(self, owner: str, preset_id: str) -> bool:
        self._call("soft_delete", owner=owner, preset_id=preset_id)
        if not any(r.id == preset_id for r in self.own_live(owner)):
            return False
        self.deleted.add(preset_id)
        self.rows[preset_id] = dataclasses.replace(self.rows[preset_id], updated_at=self._now())
        return True

    async def import_many(
        self, owner: str, items: Sequence[tuple[str, PresetFields]]
    ) -> list[PresetRow]:
        self._call("import_many", owner=owner, count=len(items))
        if len(items) > MAX_IMPORT_PRESETS:
            raise ValueError("too many")
        if len(self.own_live(owner)) + len(items) > MAX_LIVE_PRESETS:
            raise PresetConflictError("limit_reached")
        taken: dict[str, set[str]] = {}
        for r in self.own_live(owner):
            taken.setdefault(r.indicator_code, set()).add(r.name.lower())
        out = []
        for preset_id, fields in items:
            names = taken.setdefault(fields.indicator_code, set())
            free = unique_name(fields.name, names)
            names.add(free.lower())
            out.append(self._insert(owner, preset_id, dataclasses.replace(fields, name=free)))
        return out

    async def count_live_by_builtin(self) -> dict[bool, int]:
        self._call("count_live_by_builtin")
        counts: dict[bool, int] = {}
        for r in self._live():
            counts[r.is_builtin] = counts.get(r.is_builtin, 0) + 1
        return counts


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


class Series:
    """A `BoundedMetric` stand-in: `labels(*values)` -> a child that records `inc`/`set`."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, ...], float] = {}

    def labels(self, *values: str) -> Series._Child:
        return Series._Child(self, values)

    class _Child:
        def __init__(self, series: Series, key: tuple[str, ...]) -> None:
            self._series, self._key = series, key

        def inc(self, amount: float = 1) -> None:
            self._series.values[self._key] = self._series.values.get(self._key, 0) + amount

        def set(self, value: float) -> None:
            self._series.values[self._key] = value


class Metrics:
    """`IndicatorPresetMetricsLike` with two `Series` (typed `Any`: they stand in for
    `BoundedMetric`, whose `labels(...)` child they mimic)."""

    def __init__(self) -> None:
        self.presets: Any = Series()
        self.denied: Any = Series()


def new_ids() -> Any:
    """Deterministic ids for the service's `new_id`: 0193...0001, 0193...0002, ..."""
    counter = iter(range(1, 1_000_000))
    return lambda: uuid.UUID(int=(0x0193 << 112) | next(counter))


class Env:
    """Router-only app over a `FakePresetRepo`; `user` is the caller (None = no session)."""

    def __init__(self, *, wired: bool = True) -> None:
        self.repo, self.audit, self.metrics = FakePresetRepo(), Audit(), Metrics()
        self.user: uuid.UUID | None = USER_A
        self.repo_up = True
        self.grants: set[str] | None = None  # replaces PERMS[user] ("*", unknown codes, ...)
        self.owner = False  # the owner flag the session resolver derives
        env = self

        class _Resolver:  # async, like the session-backed `SessionAuditPrincipalResolver`
            async def resolve(self, _request: Request) -> AuditPrincipal | None:
                if env.user is None:
                    return None
                perms = frozenset(PERMS[env.user] if env.grants is None else env.grants)
                return AuditPrincipal(env.user, "u", perms, session_id=SID, ip="10.0.0.9",
                                      is_owner=env.owner)  # fmt: skip

        app = FastAPI()
        app.include_router(make_indicator_presets_router(
            lambda: self.repo if self.repo_up else None, _Resolver() if wired else None,
            self.audit, default_catalogue(), metrics=self.metrics, new_id=new_ids(),
        ))  # fmt: skip
        self.c = TestClient(app)

    def create(self, **over: Any) -> dict[str, Any]:
        r = self.c.post("/indicator-presets", json=body(**over))
        assert r.status_code == 201, r.text
        return dict(r.json())

    def listed(self) -> list[dict[str, Any]]:
        r = self.c.get("/indicator-presets")
        assert r.status_code == 200, r.text
        return list(r.json()["items"])

    def mine(self) -> list[dict[str, Any]]:
        return [item for item in self.listed() if not item["is_builtin"]]
