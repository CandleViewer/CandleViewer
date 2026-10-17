"""In-memory `DrawingRepository` + router-only test app for /drawings (E14-T01, #357)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api._generated import openapi_models
from candleviewer.api.drawings import make_drawings_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.errors import SessionNotFound
from candleviewer.storage.repositories.drawings import (
    BatchOp,
    BatchOpFailed,
    BatchResult,
    CreateOp,
    DeleteOp,
    DrawingFields,
    DrawingIdUnavailableError,
    DrawingLayoutNotFoundError,
    DrawingNotFoundError,
    DrawingRow,
    DrawingVersionConflictError,
    UpdateOp,
)
from tests.unit.auth.auth_fakes import MFA_PROVED_AT

USER_A = uuid.UUID("00000000-0000-4000-8000-00000000000a")
USER_B = uuid.UUID("00000000-0000-4000-8000-00000000000b")
VIEWER = uuid.UUID("00000000-0000-4000-8000-00000000000c")
SID = uuid.UUID("00000000-0000-4000-8000-0000000000e1")
#: E09 grants for this ticket: managers read and write their own drawings, a viewer only reads.
PERMS = {USER_A: {"workspaces:read", "workspaces:write"},
         USER_B: {"workspaces:read", "workspaces:write"}, VIEWER: {"workspaces:read"}}  # fmt: skip
#: `Drawing` is open for readers (C-6.3), so its exact key set is pinned here: no internal column
#: (`deleted_at`, `alert_id`, `interval_scope`, `anchor_*`) may ever leak into a response.
BATCH = "DrawingBatchRequest"  # generated model name for `wire(..., BATCH)`
DRAWING_KEYS = frozenset(("id owner_user_id symbol tool layout_id geometry style label locked "
                          "visible z_index created_at updated_at").split())  # fmt: skip
T0 = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
TRENDLINE: dict[str, Any] = {
    "symbol": "BTCUSDT",
    "tool": "trendline",
    "geometry": {
        "points": [{"t": "2026-09-13T12:00:00Z", "p": "61200.10"},
                   {"t": "2026-09-14T09:00:00.250Z", "p": "63000.000000000001"}],
        "extend_right": True,
    },
    "style": {"colour": "#5B8DEF", "width": 2, "dash": "solid"},
    "label": "ascending support",
}  # fmt: skip


def wire(data: dict[str, Any], model: str = "DrawingInput") -> dict[str, Any]:
    """`data` as a contract-generated client sends it: generated model, `exclude_unset=True` (the
    models accept null for non-nullable optionals). Malformed payloads are sent raw. Needs #2380."""
    assert hasattr(openapi_models, "DrawingBatchRequest"), "closed drawings contract not merged"
    cls = getattr(openapi_models, model)
    return dict(cls.model_validate(data).model_dump(mode="json", exclude_unset=True))


class FakeDrawingRepo:
    """The `DrawingRepository` semantics in memory: owner-scoped, soft delete, strict tokens,
    and an all-or-nothing `apply_batch` with the SQL implementation's first-failure rules."""

    def __init__(self) -> None:
        self.rows: dict[str, DrawingRow] = {}
        self.deleted: dict[str, datetime] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail: Exception | None = None  # raised by every call (store outage)
        self.tick = 0
        self.layouts: dict[str, str] = {}  # live layout id -> owner (E15-T01 spec Sec.7)

    def _call(self, name: str, **kw: Any) -> None:
        self.calls.append((name, kw))
        if self.fail is not None:
            raise self.fail

    def _layouts_live(self, owner: str, refs: list[tuple[str, str | None]]) -> None:
        """The SQL repo's first step: every named layout is a live one of `owner`."""
        missing = [f for f, lid in refs if lid is not None and self.layouts.get(lid) != owner]
        if missing:
            raise DrawingLayoutNotFoundError(tuple(missing))

    async def is_live_layout(self, owner: str, layout_id: str) -> bool:  # the `layouts` probe
        self._call("is_live_layout", owner=owner, layout_id=layout_id)
        return self.layouts.get(layout_id) == owner

    def _live(self, owner: str, drawing_id: str) -> DrawingRow | None:
        row = self.rows.get(drawing_id)
        ok = row is not None and row.owner_user_id == owner and drawing_id not in self.deleted
        return row if ok else None

    def _put(self, owner: str, did: str, f: DrawingFields, created: datetime) -> DrawingRow:
        self.tick += 1  # every write moves the token strictly forward
        self.rows[did] = DrawingRow(
            did, owner, f.symbol, f.layout_id, f.tool, f.geometry, f.style, f.label, f.locked,
            f.visible, f.z_index, created, T0 + timedelta(microseconds=self.tick),
        )  # fmt: skip
        return self.rows[did]

    def _delete(self, row: DrawingRow) -> None:
        """`deleted_at` set and the token bumped; the row stays until the purge job."""
        self.tick += 1
        self.rows[row.id] = replace(row, updated_at=T0 + timedelta(microseconds=self.tick))
        self.deleted[row.id] = self.rows[row.id].updated_at

    async def list_page(
        self, owner: str, *, symbol: str, layout_id: str | None, after_id: str | None, limit: int
    ) -> list[DrawingRow]:
        self._call("list_page", owner=owner, symbol=symbol, layout_id=layout_id,
                   after_id=after_id, limit=limit)  # fmt: skip
        return [
            r for i, r in sorted(self.rows.items())
            if self._live(owner, i) and r.symbol == symbol and (after_id is None or i > after_id)
            and (layout_id is None or r.layout_id == layout_id)
        ][:limit]  # fmt: skip

    async def get(self, owner: str, drawing_id: str) -> DrawingRow | None:
        self._call("get", owner=owner, drawing_id=drawing_id)
        return self._live(owner, drawing_id)

    async def exists_for_other_owner(self, owner: str, drawing_id: str) -> bool:
        self._call("exists_for_other_owner", owner=owner, drawing_id=drawing_id)
        row = self.rows.get(drawing_id)
        return row is not None and row.owner_user_id != owner and drawing_id not in self.deleted

    async def create(self, owner: str, drawing_id: str, fields: DrawingFields) -> DrawingRow:
        self._call("create", owner=owner, drawing_id=drawing_id)
        self._layouts_live(owner, [("layout_id", fields.layout_id)])
        if drawing_id in self.rows:
            raise DrawingIdUnavailableError(drawing_id)
        return self._put(owner, drawing_id, fields, T0)

    async def update(
        self, owner: str, drawing_id: str, fields: DrawingFields, *, if_match: datetime | None
    ) -> DrawingRow:
        self._call("update", owner=owner, drawing_id=drawing_id, if_match=if_match)
        self._layouts_live(owner, [("layout_id", fields.layout_id)])
        row = self._live(owner, drawing_id)
        if row is None:
            raise DrawingNotFoundError(drawing_id)
        if if_match is not None and if_match != row.updated_at:
            raise DrawingVersionConflictError(drawing_id)
        return self._put(owner, drawing_id, fields, row.created_at)

    async def soft_delete(self, owner: str, drawing_id: str) -> bool:
        self._call("soft_delete", owner=owner, drawing_id=drawing_id)
        row = self._live(owner, drawing_id)
        if row is not None:
            self._delete(row)
        return row is not None

    async def apply_batch(self, owner: str, ops: Sequence[BatchOp]) -> BatchResult:
        self._call("apply_batch", owner=owner, op_count=len(ops))
        refs = [(f"operations.{i}.drawing.layout_id", op.fields.layout_id)
                for i, op in enumerate(ops) if not isinstance(op, DeleteOp)]  # fmt: skip
        self._layouts_live(owner, refs)
        saved, created, updated, deleted = (dict(self.rows), dict(self.deleted)), [], [], []
        try:
            for i, op in enumerate(ops):
                row = self.rows.get(op.id)  # any owner, any state
                if isinstance(op, CreateOp):  # the SQL: the INSERT's PK collision for a foreign id
                    if row is not None:
                        raise BatchOpFailed(i, "id_unavailable")
                    created.append(self._put(owner, op.id, op.fields, T0))
                elif row is None or row.owner_user_id != owner:  # not in the caller's snapshot
                    raise BatchOpFailed(i, "target_not_owned")
                elif op.id in self.deleted:  # the caller's own soft-deleted row: in the snapshot
                    raise BatchOpFailed(i, "target_unavailable")
                elif row.updated_at != op.if_match:
                    raise BatchOpFailed(i, "version_conflict")
                elif isinstance(op, UpdateOp):
                    if (op.fields.symbol, op.fields.tool) != (row.symbol, row.tool):
                        raise BatchOpFailed(i, "immutable_field")  # same order as the SQL repo
                    updated.append(self._put(owner, op.id, op.fields, row.created_at))
                else:
                    self._delete(row)
                    deleted.append(op.id)
        except BatchOpFailed:
            self.rows, self.deleted = saved  # rolled back: nothing of the batch survives
            raise
        return BatchResult(tuple(created), tuple(updated), tuple(deleted))

    async def purge_deleted(self, older_than_days: int, limit: int) -> int:
        return 0  # the retention job is slice C4; the router never purges

    async def count_live_by_tool(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.rows.values():
            counts[r.tool] = counts.get(r.tool, 0) + 1
        return counts


class Audit:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def emit(self, action: str, **kw: Any) -> None:
        self.calls.append({"action": action, **kw})

    def denied(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["action"] == "rbac.denied"]


class Env:
    """Router-only app with a fake repository; `user` is the caller (None = no session)."""

    def __init__(self, *, wired: bool = True, metrics: Any = None, idempotency: Any = None) -> None:
        self.repo, self.audit = FakeDrawingRepo(), Audit()
        self.user: uuid.UUID | None = USER_A
        self.repo_up, self.now = True, T0.timestamp()  # store reachable; the router's clock
        self.grants: set[str] | None = None  # replaces PERMS[user] ("*", unknown codes, downgrade)
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
        app.include_router(make_drawings_router(
            lambda: self.repo if self.repo_up else None, _Resolver() if wired else None,
            self.audit, clock=lambda: self.now, metrics=metrics, idempotency=idempotency,
            layouts=lambda: self.repo if self.repo_up else None,
        ))  # fmt: skip
        self.c = TestClient(app)

    def create(self, **over: Any) -> dict[str, Any]:
        r = self.c.post("/drawings", json=wire(TRENDLINE | over))
        assert r.status_code == 201, r.text
        return dict(r.json())

    def listed(self, symbol: str = "BTCUSDT") -> list[dict[str, Any]]:
        r = self.c.get("/drawings", params={"symbol": symbol})
        assert r.status_code == 200, r.text
        return list(r.json()["items"])


class Sessions:  # session-store seam of the real app (`ctx.auth._sessions`): tok-a = user A
    async def authenticate_access_token(self, token: str, **_kw: Any) -> Any:
        if (user_id := {"tok-a": USER_A}.get(token)) is None:
            raise SessionNotFound("unknown token")
        return SimpleNamespace(id=SID, user_id=user_id, mfa_satisfied_at=MFA_PROVED_AT)

    async def peek_access_token(self, token: str) -> Any:  # the CSRF guard's session binding
        return await self.authenticate_access_token(token)


class Identity:  # identity-store seam (`build_identity_provider`): an active manager
    async def user(self, _user_id: str) -> dict[str, Any]:
        return {"username": "a", "roles": ["manager"], "status": "active"}

    async def session_info(self, _user_id: str) -> dict[str, Any]:
        return {"permissions": sorted(PERMS[USER_A]), "account_scope": []}
