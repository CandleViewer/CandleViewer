"""Driver-free port for `watchlists` (E08-T07, #4706; 21 Sec.3.8.6). Stdlib only.

Every call names its owner and no statement reads or writes another user's list, so one of theirs
is not found, exactly as an id that does not exist; `exists_for_other_owner` answers only whether
another user holds the id, for the router's `rbac.denied` record. A write awaits its record in its
own transaction, after its statement and before the commit (C-2.9): if the record is refused or
outlasts its bound, nothing is written. `replace` locks the row, compares the version the caller
names, then writes the list and the next version in one statement guarded by that version, so of
two writers holding the same version exactly one wins. An error carries no value (C-12.6).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class WatchlistFields:
    """What a create inserts and a replace sets: the name and both lists, in order."""

    name: str
    symbols: tuple[str, ...]
    columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WatchlistRow:
    """A stored list, every column in table order."""

    id: UUID
    user_id: UUID
    name: str
    symbols: tuple[str, ...]
    columns: tuple[str, ...]
    version: int
    created_at: datetime
    updated_at: datetime


#: Awaited in the write's transaction before its commit, with the row before and after it (`None`
#: before a create, after a delete); if it raises or outlasts its bound, nothing is written.
WatchlistWriteAhead = Callable[[WatchlistRow | None, WatchlistRow | None], Awaitable[None]]


class WatchlistNotFoundError(Exception):
    """The owner holds no list with this id; nothing was written."""


class WatchlistStaleError(Exception):
    """The list is not at the version the caller named; nothing was written."""

    def __init__(self, version: int) -> None:
        super().__init__("the list is at another version")
        self.version = version  # the current one


class WatchlistNameTakenError(Exception):
    """`ux_wl_name`: another of the owner's lists holds the name as `lower()` folds it."""


class WatchlistStore(Protocol):
    """The owner's lists. `replace` takes `expected_version=None` for a tag that can name no
    version: the list then answers `WatchlistStaleError`, or `WatchlistNotFoundError` first."""

    async def list_own(self, owner: UUID) -> list[WatchlistRow]: ...

    async def get_own(self, owner: UUID, watchlist_id: UUID) -> WatchlistRow | None: ...

    async def exists_for_other_owner(self, owner: UUID, watchlist_id: UUID) -> bool: ...

    async def create(
        self,
        owner: UUID,
        watchlist_id: UUID,
        fields: WatchlistFields,
        *,
        write_ahead: WatchlistWriteAhead,
    ) -> WatchlistRow: ...

    async def replace(
        self,
        owner: UUID,
        watchlist_id: UUID,
        fields: WatchlistFields,
        *,
        expected_version: int | None,
        write_ahead: WatchlistWriteAhead,
    ) -> WatchlistRow: ...

    async def delete(
        self, owner: UUID, watchlist_id: UUID, *, write_ahead: WatchlistWriteAhead
    ) -> WatchlistRow: ...
