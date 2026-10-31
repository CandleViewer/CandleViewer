"""Driver-free surface of the per-user `settings` repository (E02-T13, #5181; migration 0025).

`api` may not import a storage driver (ADR-0003), so the `/settings` routes and `GET
/me/preferences` type against `UserSettings`; `user_settings_sqlalchemy.py` implements it, beside
the system-scope `SystemSettings`. Only the `scope = 'user'` rows of the one user a call names are
reachable: a system-scope row, or another user's row, is never read, locked or written. One row
per leaf: `key` is the leaf's dotted path, `value` its JSON, never JSON null (a leaf reset to its
default has no row). A read that fails raises; it never answers "no rows".
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class UserSetting:
    """One of a user's rows: the leaf's dotted path, its JSON value, its last write (UTC)."""

    key: str
    value: object
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class LeafChange:
    """A leaf a write changed: its value before and after, `None` where it has no row."""

    key: str
    before: object
    after: object


#: Awaited in the write's transaction, after the writes and before the commit, with the leaves the
#: write changed, never none: a write that changes nothing awaits no hook. It writes the audit
#: record (C-2.9). What it raises rolls the write back and reaches the caller as is, so it must
#: raise a type of its own: an `OSError` would be taken for a store outage.
UserSettingsWriteAhead = Callable[[tuple[LeafChange, ...]], Awaitable[None]]


class UserSettings(Protocol):
    async def read(self, user_id: UUID) -> tuple[UserSetting, ...]:
        """`user_id`'s rows, by key; none is an empty tuple. A failing read raises."""

    async def apply(
        self,
        user_id: UUID,
        patch: Mapping[str, object],
        *,
        write_ahead: UserSettingsWriteAhead,
    ) -> tuple[UserSetting, ...]:
        """Set each leaf of `patch` to its value, or delete its row where the value is `None`, in
        one transaction under the user's lock, written by the user. A leaf set to the value it
        holds, or reset with no row, is no change. `write_ahead` sees the changes before the
        commit. Returns the user's rows after the write, by key. `StorageTierUnavailable`,
        `WriteAheadTimeout` and what the hook raises leave every row as it was."""


__all__ = ["LeafChange", "UserSetting", "UserSettings", "UserSettingsWriteAhead"]
