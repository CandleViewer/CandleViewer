"""Driver-free drawings repository surface (E14-T01, migration `0021_drawings`).

The `api` module may not import a storage driver (ADR-0003), so routers type against
`DrawingRepository` and these plain frozen dataclasses; `drawings_sqlalchemy.py` is the
implementation.

Owner scoping (C-12.4): every method takes the caller's `owner` and the implementation
re-checks it in SQL. The router's RBAC check is the first line of defence; the data-layer
filter means a router bug can never read or write another user's drawing.

No existence oracle: a missing row, a soft-deleted row and another owner's row are
indistinguishable to the caller (`DrawingNotFoundError`, `target_unavailable`,
`id_unavailable`), so ids cannot be probed for existence across users.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


class DrawingNotFoundError(Exception):
    """Row is missing, soft-deleted or owned by someone else (all identical, HTTP 404)."""


class DrawingVersionConflictError(Exception):
    """`if_match` no longer equals the row's `updated_at` token (HTTP 412)."""


class DrawingIdUnavailableError(Exception):
    """A create reused an id held by ANY row, any owner, any state (HTTP 409)."""


class BatchOpFailed(Exception):
    """First failing batch operation; the whole batch has been rolled back."""

    def __init__(self, index: int, rule: str) -> None:
        super().__init__(f"operations.{index}: {rule}")
        self.index = index
        self.rule = rule


@dataclass(frozen=True, slots=True)
class DrawingFields:
    """Writable columns, already validated and sanitised by `api.drawings_models`."""

    symbol: str
    layout_id: str | None
    tool: str
    geometry: dict[str, Any]
    style: dict[str, Any]
    label: str | None
    locked: bool
    visible: bool
    z_index: int
    anchor_start: datetime | None
    anchor_end: datetime | None


def format_token(value: datetime) -> str:
    """Concurrency token: UTC, always six fractional digits and a `Z` suffix."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass(frozen=True, slots=True)
class DrawingRow:
    id: str
    owner_user_id: str
    symbol: str
    layout_id: str | None
    tool: str
    geometry: dict[str, Any]
    style: dict[str, Any]
    label: str | None
    locked: bool
    visible: bool
    z_index: int
    created_at: datetime
    updated_at: datetime

    @property
    def token(self) -> str:
        return format_token(self.updated_at)


@dataclass(frozen=True, slots=True)
class CreateOp:
    id: str
    fields: DrawingFields


@dataclass(frozen=True, slots=True)
class UpdateOp:
    id: str
    if_match: datetime
    fields: DrawingFields


@dataclass(frozen=True, slots=True)
class DeleteOp:
    id: str
    if_match: datetime


BatchOp = CreateOp | UpdateOp | DeleteOp


@dataclass(frozen=True, slots=True)
class BatchResult:
    created: tuple[DrawingRow, ...]
    updated: tuple[DrawingRow, ...]
    deleted: tuple[str, ...]


class DrawingRepository(Protocol):
    async def list_page(
        self,
        owner: str,
        *,
        symbol: str,
        layout_id: str | None,
        after_id: str | None,
        limit: int,
    ) -> list[DrawingRow]:
        """Live rows ordered by id; at most `limit` (callers ask for limit + 1)."""
        ...

    async def get(self, owner: str, drawing_id: str) -> DrawingRow | None: ...

    async def exists_for_other_owner(self, owner: str, drawing_id: str) -> bool:
        """True when a live row with this id belongs to someone else (audit only)."""
        ...

    async def create(self, owner: str, drawing_id: str, fields: DrawingFields) -> DrawingRow: ...

    async def update(
        self,
        owner: str,
        drawing_id: str,
        fields: DrawingFields,
        *,
        if_match: datetime | None,
    ) -> DrawingRow: ...

    async def soft_delete(self, owner: str, drawing_id: str) -> bool: ...

    async def apply_batch(self, owner: str, ops: Sequence[BatchOp]) -> BatchResult: ...

    async def purge_deleted(self, older_than_days: int, limit: int) -> int: ...


__all__ = [
    "BatchOp", "BatchOpFailed", "BatchResult", "CreateOp", "DeleteOp", "DrawingFields",
    "DrawingIdUnavailableError", "DrawingNotFoundError", "DrawingRepository", "DrawingRow",
    "DrawingVersionConflictError", "UpdateOp", "format_token",
]  # fmt: skip
