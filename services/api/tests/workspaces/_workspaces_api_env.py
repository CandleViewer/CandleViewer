"""In-memory `WorkspaceRepository` + router-only test app for /workspaces (E15-T01, #402)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api._generated import openapi_models
from candleviewer.api.workspaces import make_workspaces_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.errors import SessionNotFound
from candleviewer.storage.repositories.workspaces import (
    LayoutFields,
    LayoutRow,
    WorkspaceConflictError,
    WorkspaceDetailRow,
    WorkspaceFields,
    WorkspaceNotFoundError,
    WorkspaceRow,
    WorkspaceVersionConflictError,
    WriteResult,
)  # fmt: skip

USER_A = uuid.UUID("00000000-0000-4000-8000-00000000000a")
USER_B = uuid.UUID("00000000-0000-4000-8000-00000000000b")
VIEWER = uuid.UUID("00000000-0000-4000-8000-00000000000c")
SID = uuid.UUID("00000000-0000-4000-8000-0000000000e1")
MISSING = "00000000-0000-4000-8000-0000000000ff"
PERMS = {USER_A: {"workspaces:read", "workspaces:write"},
         USER_B: {"workspaces:read", "workspaces:write"}, VIEWER: {"workspaces:read"}}  # fmt: skip
#: `Workspace` is open for readers (C-6.3): its exact key set is pinned, no internal column leaks.
WORKSPACE_KEYS = frozenset(("id user_id name is_default icon_token sort_order layout_count "
                            "created_at updated_at").split())  # fmt: skip
T0 = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


def astuple_fields(f: LayoutFields) -> tuple[Any, ...]:
    return (f.name, f.grid_preset, f.grid_spec, f.crosshair_sync, f.level_sync, f.symbol_sync,
            f.hotkey_slot, f.is_default, f.panes)  # fmt: skip


LAYOUT: dict[str, Any] = {
    "name": "Main",
    "grid_preset": "2x2",
    "hotkey_slot": 3,
    "panes": [
        {"slot_index": 1, "pane_kind": "dom", "symbol": "ETHUSDT"},
        {"slot_index": 0, "pane_kind": "chart", "symbol": "BTCUSDT", "interval_code": "time:15",
         "pane_config": {"sync_group": "A", "settings": {"depth": 20, "footprint": True}}},
        {"slot_index": 2, "pane_kind": "alerts"},
        {"slot_index": 3, "pane_kind": "tape", "symbol": "SOLUSDT", "scale_mode": "log"},
    ],
}  # fmt: skip


def wire(data: dict[str, Any], model: str = "WorkspaceInput") -> dict[str, Any]:
    """`data` as a contract-generated client sends it (`exclude_unset`). Needs #2400."""
    assert hasattr(openapi_models, "LayoutGridSpec"), "workspaces contract not merged"
    cls = getattr(openapi_models, model)
    return dict(cls.model_validate(data).model_dump(mode="json", exclude_unset=True))


def contract_valid(body: dict[str, Any], model: str = "Workspace") -> None:
    """The response validates against the generated contract schema (C-6.2)."""
    # the pre-contract draft defines WorkspaceInput: key on a type only the new contract has
    assert hasattr(openapi_models, "LayoutGridSpec"), "workspaces contract not merged"
    getattr(openapi_models, model).model_validate(body)


class FakeWorkspaceRepo:
    """The `WorkspaceRepository` workspace semantics in memory (owner-scoped, soft delete)."""

    def __init__(self) -> None:
        self.rows: dict[str, WorkspaceRow] = {}
        self.deleted: set[str] = set()
        self.layouts: dict[str, LayoutRow] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.tick = 0

    def _call(self, name: str, **kw: Any) -> None:
        self.calls.append((name, kw))

    def _live(self, owner: str, wid: str) -> WorkspaceRow | None:
        row = self.rows.get(wid)
        return row if row is not None and row.user_id == owner and wid not in self.deleted else None

    def _put(self, owner: str, wid: str, f: WorkspaceFields, created: datetime) -> WorkspaceRow:
        self.tick += 1  # every write moves the token strictly forward
        stamp = T0 + timedelta(microseconds=self.tick)
        self.rows[wid] = WorkspaceRow(
            wid, owner, f.name, f.is_default, f.icon_token, f.sort_order, 0, created, stamp
        )
        return self.rows[wid]

    def _live_of(self, owner: str) -> list[WorkspaceRow]:
        return [r for i, r in self.rows.items() if self._live(owner, i)]

    async def get_workspace_detail(self, owner: str, wid: str) -> WorkspaceDetailRow | None:
        self._call("get_workspace_detail", owner=owner, wid=wid)
        row = self._live(owner, wid)
        return None if row is None else WorkspaceDetailRow(row, self.layouts_of(owner, wid))

    def layouts_of(self, owner: str, wid: str) -> tuple[LayoutRow, ...]:
        mine = [
            r for r in self.layouts.values() if r.workspace_id == wid and self._lay(owner, r.id)
        ]
        return tuple(sorted(mine, key=lambda r: r.id))

    def _lay(self, owner: str, lid: str, wid: str | None = None) -> LayoutRow | None:
        row, ws = self.layouts.get(lid), None
        if row is not None:
            ws = self._live(owner, row.workspace_id)
        gone = lid in self.deleted
        return row if row and ws and not gone and wid in (None, row.workspace_id) else None

    async def list_workspaces(
        self, owner: str, *, after: tuple[int, str] | None, limit: int
    ) -> list[WorkspaceRow]:
        self._call("list_workspaces", owner=owner, after=after, limit=limit)
        rows = sorted(self._live_of(owner), key=lambda r: (r.sort_order, r.id))
        return [r for r in rows if after is None or (r.sort_order, r.id) > after][:limit]

    async def list_layouts(
        self, owner: str, wid: str, *, after_id: str | None, limit: int
    ) -> list[LayoutRow] | None:
        self._call("list_layouts", owner=owner, wid=wid, after_id=after_id, limit=limit)
        if self._live(owner, wid) is None:
            return None
        rows = self.layouts_of(owner, wid)
        return [r for r in rows if after_id is None or r.id > after_id][:limit]

    async def get_layout(self, owner: str, wid: str, lid: str) -> LayoutRow | None:
        self._call("get_layout", owner=owner, wid=wid, lid=lid)
        return self._lay(owner, lid, wid)

    def _put_layout(
        self, owner: str, wid: str, lid: str, f: LayoutFields, created: datetime
    ) -> LayoutRow:
        self.tick += 1
        stamp = T0 + timedelta(microseconds=self.tick)
        self.layouts[lid] = LayoutRow(lid, wid, *astuple_fields(f), created, stamp)
        return self.layouts[lid]

    async def create_layout(self, owner: str, wid: str, lid: str, f: LayoutFields) -> LayoutRow:
        self._call("create_layout", owner=owner, wid=wid, lid=lid)
        if self._live(owner, wid) is None:
            raise WorkspaceNotFoundError("workspace")
        mine = self.layouts_of(owner, wid)
        if len(mine) >= 32:
            raise WorkspaceConflictError("limit_reached", None)
        if any(r.name.lower() == f.name.lower() for r in mine):
            raise WorkspaceConflictError("name_taken", "name")
        if f.hotkey_slot is not None and any(r.hotkey_slot == f.hotkey_slot for r in mine):
            raise WorkspaceConflictError("hotkey_slot_taken", "hotkey_slot")
        return self._put_layout(owner, wid, lid, f, T0)

    async def replace_layout(
        self, owner: str, wid: str, lid: str, f: LayoutFields, *, if_match: datetime | None
    ) -> WriteResult[LayoutRow]:
        self._call("replace_layout", owner=owner, wid=wid, lid=lid, if_match=if_match)
        row = self._lay(owner, lid, wid)
        if row is None:
            raise WorkspaceNotFoundError("layout")
        if row.to_fields() == f:
            return WriteResult(row, False)
        if if_match is not None and if_match != row.updated_at:
            raise WorkspaceVersionConflictError(lid)
        taken = [r for r in self.layouts_of(owner, wid) if r.id != lid]
        if any(r.name.lower() == f.name.lower() for r in taken):
            raise WorkspaceConflictError("name_taken", "name")
        return WriteResult(self._put_layout(owner, wid, lid, f, row.created_at), True)

    async def soft_delete_layout(self, owner: str, wid: str, lid: str) -> None:
        self._call("soft_delete_layout", owner=owner, wid=wid, lid=lid)
        if self._lay(owner, lid, wid) is None:
            raise WorkspaceNotFoundError("layout")
        self.deleted.add(lid)

    async def exists_for_other_owner(
        self, owner: str, kind: Literal["workspace", "layout"], object_id: str
    ) -> bool:
        self._call("exists_for_other_owner", owner=owner, kind=kind, object_id=object_id)
        if kind == "layout":
            lay = self.layouts.get(object_id)
            owned = lay is not None and self.rows[lay.workspace_id].user_id != owner
            return owned and object_id not in self.deleted
        row = self.rows.get(object_id)
        return row is not None and row.user_id != owner and object_id not in self.deleted

    async def create_workspace(self, owner: str, wid: str, fields: WorkspaceFields) -> WorkspaceRow:
        self._call("create_workspace", owner=owner, wid=wid)
        mine = self._live_of(owner)
        if len(mine) >= 32:
            raise WorkspaceConflictError("limit_reached", None)
        if any(r.name.lower() == fields.name.lower() for r in mine):
            raise WorkspaceConflictError("name_taken", "name")
        self._clear_default(owner, fields, keep=wid)
        return self._put(owner, wid, fields, T0)

    def _clear_default(self, owner: str, f: WorkspaceFields, keep: str) -> None:
        for r in self._live_of(owner):
            if f.is_default and r.is_default and r.id != keep:
                self.tick += 1
                stamp = T0 + timedelta(microseconds=self.tick)
                self.rows[r.id] = replace(r, is_default=False, updated_at=stamp)

    async def update_workspace(
        self, owner: str, wid: str, fields: WorkspaceFields, *, if_match: datetime | None
    ) -> WriteResult[WorkspaceRow]:
        self._call("update_workspace", owner=owner, wid=wid, if_match=if_match)
        row = self._live(owner, wid)
        if row is None:
            raise WorkspaceNotFoundError("workspace")
        if row.to_fields() == fields:
            return WriteResult(row, False)  # the no-op wins over a stale token (D13)
        if if_match is not None and if_match != row.updated_at:
            raise WorkspaceVersionConflictError(wid)
        if any(r.name.lower() == fields.name.lower() and r.id != wid for r in self._live_of(owner)):
            raise WorkspaceConflictError("name_taken", "name")
        self._clear_default(owner, fields, keep=wid)
        return WriteResult(self._put(owner, wid, fields, row.created_at), True)

    async def soft_delete_workspace(self, owner: str, wid: str) -> None:
        self._call("soft_delete_workspace", owner=owner, wid=wid)
        if self._live(owner, wid) is None:
            raise WorkspaceNotFoundError("workspace")
        if len(self._live_of(owner)) == 1:
            raise WorkspaceConflictError("last_workspace", "workspaceId")
        self.deleted.add(wid)


class Audit:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls.append({"action": action, **kw})

    def denied(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["action"] == "rbac.denied"]


class Env:
    """Router-only app with a fake repository; `user` is the caller (None = no session)."""

    def __init__(self, *, wired: bool = True) -> None:
        self.repo, self.audit = FakeWorkspaceRepo(), Audit()
        self.user: uuid.UUID | None = USER_A
        env = self

        class _Resolver:  # async, like the session-backed `SessionAuditPrincipalResolver`
            async def resolve(self, _request: Request) -> AuditPrincipal | None:
                if env.user is None:
                    return None
                perms = frozenset(PERMS[env.user])
                return AuditPrincipal(env.user, "u", perms, session_id=SID, ip="10.0.0.9")

        app = FastAPI()
        app.include_router(
            make_workspaces_router(lambda: self.repo, _Resolver() if wired else None, self.audit)
        )
        self.c = TestClient(app)

    def make_layout(self, wid: str, **over: Any) -> dict[str, Any]:
        r = self.c.post(f"/workspaces/{wid}/layouts", json=wire(LAYOUT | over, "LayoutInput"))
        assert r.status_code == 201, r.text
        return dict(r.json())

    def as_user(self, user: uuid.UUID | None) -> Env:
        self.user = user
        return self

    def create(self, name: str = "Scalping", **over: Any) -> dict[str, Any]:
        r = self.c.post("/workspaces", json=wire({"name": name} | over))
        assert r.status_code == 201, r.text
        return dict(r.json())


class Sessions:  # session-store seam of the real app (`ctx.auth._sessions`): tok-a = user A
    async def authenticate_access_token(self, token: str, **_kw: Any) -> Any:
        if (user_id := {"tok-a": USER_A}.get(token)) is None:
            raise SessionNotFound("unknown token")
        return SimpleNamespace(id=SID, user_id=user_id)

    async def peek_access_token(self, token: str) -> Any:  # the CSRF guard's session binding
        return await self.authenticate_access_token(token)


class Identity:  # identity-store seam: an active manager
    async def user(self, _user_id: str) -> dict[str, Any]:
        return {"username": "a", "roles": ["manager"], "status": "active"}

    async def session_info(self, _user_id: str) -> dict[str, Any]:
        return {"permissions": sorted(PERMS[USER_A]), "account_scope": []}
