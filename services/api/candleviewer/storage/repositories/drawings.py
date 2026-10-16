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


#: Rules a failing batch op can report (the API maps them to `errors[0].rule`).
#: `immutable_field`: an update tried to change `symbol` or `tool` (immutable, as on PUT).
#: `target_not_owned` is internal and never on the wire: the update/delete target is not among
#: the caller's rows (another owner's or missing, which the repository cannot and must not tell
#: apart). The API audits it, then answers it exactly as `target_unavailable`, which is what the
#: caller's own soft-deleted target reports, without an audit record.
BATCH_RULES = frozenset(
    {
        "target_unavailable",
        "target_not_owned",
        "version_conflict",
        "id_unavailable",
        "immutable_field",
    }
)


class BatchOpFailed(Exception):
    """First failing batch operation; the whole batch has been rolled back.

    `rule` is one of `BATCH_RULES`.
    """

    def __init__(self, index: int, rule: str) -> None:
        if rule not in BATCH_RULES:
            raise ValueError(f"unknown batch rule: {rule!r}")
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
    "BATCH_RULES", "BatchOp", "BatchOpFailed", "BatchResult", "CreateOp", "DeleteOp",
    "DrawingFields", "DrawingIdUnavailableError", "DrawingNotFoundError", "DrawingRepository",
    "DrawingRow", "DrawingVersionConflictError", "UpdateOp", "format_token",
]  # fmt: skip
