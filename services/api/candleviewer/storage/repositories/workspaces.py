"""Driver-free workspaces/layouts repository surface (E15-T01, migration `0022_workspaces`).

`api` may not import a storage driver (ADR-0003), so routers type against `WorkspaceRepository`
and these frozen dataclasses; `workspaces_sqlalchemy.py` implements it.

Owner scoping (C-12.4): every method takes the caller's `owner` and the implementation re-checks
it in SQL. A missing, soft-deleted or foreign object is indistinguishable to the caller
(`WorkspaceNotFoundError`, `None`), so ids cannot be probed across users.

Concurrency token (D12): `updated_at` at microsecond precision, strictly increasing. The layout
token versions the aggregate (row + panes); the workspace token versions metadata only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol


def format_token(value: datetime) -> str:
    """Concurrency token: UTC, always six fractional digits and a `Z` suffix (D26)."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class WorkspaceNotFoundError(Exception):
    """Workspace/layout missing, soft-deleted or another user's (all identical, HTTP 404)."""

    def __init__(self, kind: Literal["workspace", "layout"] = "workspace") -> None:
        super().__init__(f"no such {kind}")
        self.kind = kind


class WorkspaceVersionConflictError(Exception):
    """`if_match` no longer equals the stored `updated_at` token (HTTP 412).

    The single argument is the id of the workspace or layout whose token was stale.
    """


class WorkspaceConflictError(Exception):
    """Stored-state conflict (HTTP 409). `rule`: name_taken, hotkey_slot_taken, limit_reached,
    last_workspace or concurrent_update; `field` names the offending input when there is one."""

    def __init__(self, rule: str, field: str | None) -> None:
        super().__init__(rule)
        self.rule = rule
        self.field = field


@dataclass(frozen=True, slots=True)
class WorkspaceFields:
    name: str
    is_default: bool
    icon_token: str
    sort_order: int


@dataclass(frozen=True, slots=True)
class WorkspaceRow:
    id: str
    user_id: str
    name: str
    is_default: bool
    icon_token: str
    sort_order: int
    layout_count: int
    created_at: datetime
    updated_at: datetime

    @property
    def token(self) -> str:
        return format_token(self.updated_at)

    def to_fields(self) -> WorkspaceFields:
        return WorkspaceFields(self.name, self.is_default, self.icon_token, self.sort_order)


@dataclass(frozen=True, slots=True)
class PaneFields:
    slot_index: int
    pane_kind: str
    symbol: str | None
    interval_code: str | None
    chart_template_id: str | None
    indicator_preset_ids: tuple[str, ...]
    pane_config: dict[str, Any]
    scale_mode: str


@dataclass(frozen=True, slots=True)
class LayoutFields:
    name: str
    grid_preset: str
    grid_spec: dict[str, Any] | None  # None for a named preset (stored as `{}`)
    crosshair_sync: bool
    level_sync: bool
    symbol_sync: bool
    hotkey_slot: int | None
    is_default: bool
    panes: tuple[PaneFields, ...]  # sorted by slot_index


@dataclass(frozen=True, slots=True)
class LayoutRow:
    id: str
    workspace_id: str
    name: str
    grid_preset: str
    grid_spec: dict[str, Any] | None
    crosshair_sync: bool
    level_sync: bool
    symbol_sync: bool
    hotkey_slot: int | None
    is_default: bool
    panes: tuple[PaneFields, ...]
    created_at: datetime
    updated_at: datetime

    @property
    def token(self) -> str:
        return format_token(self.updated_at)

    def to_fields(self) -> LayoutFields:
        return LayoutFields(
            self.name, self.grid_preset, self.grid_spec, self.crosshair_sync, self.level_sync,
            self.symbol_sync, self.hotkey_slot, self.is_default, self.panes,
        )  # fmt: skip


@dataclass(frozen=True, slots=True)
class WorkspaceDetailRow:
    workspace: WorkspaceRow
    layouts: tuple[LayoutRow, ...]


@dataclass(frozen=True, slots=True)
class WriteResult[T]:
    row: T
    changed: bool  # False = the body equalled the stored state; nothing was written (D13)


class WorkspaceRepository(Protocol):
    async def list_workspaces(
        self, owner: str, *, after: tuple[int, str] | None, limit: int
    ) -> list[WorkspaceRow]:
        """Live rows ordered by (sort_order, id); at most `limit` (callers ask for limit + 1)."""
        ...

    async def get_workspace_detail(
        self, owner: str, workspace_id: str
    ) -> WorkspaceDetailRow | None:
        """Workspace + live layouts + their panes in three statements (no N+1)."""
        ...

    async def create_workspace(
        self, owner: str, workspace_id: str, fields: WorkspaceFields
    ) -> WorkspaceRow: ...

    async def update_workspace(
        self,
        owner: str,
        workspace_id: str,
        fields: WorkspaceFields,
        *,
        if_match: datetime | None,
    ) -> WriteResult[WorkspaceRow]: ...

    async def soft_delete_workspace(self, owner: str, workspace_id: str) -> None: ...

    async def list_layouts(
        self, owner: str, workspace_id: str, *, after_id: str | None, limit: int
    ) -> list[LayoutRow] | None:
        """`None` = workspace not found."""
        ...

    async def get_layout(
        self, owner: str, workspace_id: str, layout_id: str
    ) -> LayoutRow | None: ...

    async def create_layout(
        self, owner: str, workspace_id: str, layout_id: str, fields: LayoutFields
    ) -> LayoutRow: ...

    async def replace_layout(
        self,
        owner: str,
        workspace_id: str,
        layout_id: str,
        fields: LayoutFields,
        *,
        if_match: datetime | None,
    ) -> WriteResult[LayoutRow]:
        """Full pane-set replacement in one transaction; a failure leaves the stored set intact."""
        ...

    async def soft_delete_layout(self, owner: str, workspace_id: str, layout_id: str) -> None: ...

    async def exists_for_other_owner(
        self, owner: str, kind: Literal["workspace", "layout"], object_id: str
    ) -> bool:
        """True when a live object with this id belongs to someone else (audit only)."""
        ...

    async def is_live_layout(self, owner: str, layout_id: str) -> bool: ...

    async def is_chart_open(self, symbol: str) -> bool:
        """Recorder probe, all users (E16): served by `ix_lp_symbol`."""
        ...

    async def chart_open_symbols(self) -> list[str]:
        """Distinct symbols on panes of live layouts, sorted (set rebuilds only)."""
        ...

    async def purge_deleted(self, older_than_days: int, limit: int) -> int:
        """Hard-delete soft-deleted layouts then workspaces past the cut-off (FKs cascade)."""
        ...


__all__ = [
    "LayoutFields", "LayoutRow", "PaneFields", "WorkspaceConflictError", "WorkspaceDetailRow",
    "WorkspaceFields", "WorkspaceNotFoundError", "WorkspaceRepository", "WorkspaceRow",
    "WorkspaceVersionConflictError", "WriteResult", "format_token",
]  # fmt: skip
