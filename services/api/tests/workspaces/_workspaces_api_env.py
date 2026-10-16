"""In-memory `WorkspaceRepository` + router-only test app for /workspaces (E15-T01, #402)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api._generated import openapi_models
from candleviewer.api.workspaces import make_workspaces_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.storage.repositories.workspaces import (
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


def wire(data: dict[str, Any], model: str = "WorkspaceInput") -> dict[str, Any]:
    """`data` as a contract-generated client sends it (`exclude_unset`). Needs #2400."""
    assert hasattr(openapi_models, "WorkspaceInput"), "workspaces contract not merged"
    cls = getattr(openapi_models, model)
    return dict(cls.model_validate(data).model_dump(mode="json", exclude_unset=True))


def contract_valid(body: dict[str, Any], model: str = "Workspace") -> None:
    """The response validates against the generated contract schema (C-6.2)."""
    assert hasattr(openapi_models, model), "workspaces contract not merged"
    getattr(openapi_models, model).model_validate(body)


class FakeWorkspaceRepo:
    """The `WorkspaceRepository` workspace semantics in memory (owner-scoped, soft delete)."""

    def __init__(self) -> None:
        self.rows: dict[str, WorkspaceRow] = {}
        self.deleted: set[str] = set()
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
        return ()

    async def exists_for_other_owner(
        self, owner: str, kind: Literal["workspace", "layout"], object_id: str
    ) -> bool:
        self._call("exists_for_other_owner", owner=owner, kind=kind, object_id=object_id)
        row = self.rows.get(object_id)
        return (kind == "workspace" and row is not None and row.user_id != owner
                and object_id not in self.deleted)  # fmt: skip

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

    def as_user(self, user: uuid.UUID | None) -> Env:
        self.user = user
        return self

    def create(self, name: str = "Scalping", **over: Any) -> dict[str, Any]:
        r = self.c.post("/workspaces", json=wire({"name": name} | over))
        assert r.status_code == 201, r.text
        return dict(r.json())
