"""Driver-free port for `hotkey_profiles` (E10-T05, #5211; 21 Sec.3.8.5). Stdlib only.

Every call names its owner and no statement reads or writes another user's profile, so one of theirs
is not found, exactly as an id that does not exist; `exists_for_other_owner` answers only whether
another user holds the id, for the router's `rbac.denied` record. A write runs, in one
transaction, the owner's lock, its reads, its statements, then the write-ahead hook, then the
commit (C-2.9): the hook is the audit record, so if it raises or outlasts its bound, nothing is
written. Under that lock a create counts the owner's profiles against `MAX_PROFILES`, an
activation deactivates the owner's other profile, and a delete refuses the active one, so none of
them can race another write of the same owner. A replace guarded by a version compares it under the
lock and writes in one statement guarded by it; one with no version is last-write-wins. `bindings`
is the stored object of command id to binding (`""` unbinds), judged before it gets here
(`api.hotkey_rules`). An error carries no value (C-12.6).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Protocol
from uuid import UUID

#: 22 `createHotkeyProfile`: a user holds at most this many profiles (`409 limit_reached`).
MAX_PROFILES: Final = 20
#: `hk_name_len` and 22's `name` bound.
NAME_MAX: Final = 80


@dataclass(frozen=True, slots=True)
class HotkeyProfileFields:
    """What a create inserts and a replace sets: the name and the stored bindings."""

    name: str
    bindings: dict[str, str]


@dataclass(frozen=True, slots=True)
class HotkeyProfileRow:
    """A stored profile, every column in table order (`bindings` as stored, string values only)."""

    id: UUID
    owner_user_id: UUID
    name: str
    is_active: bool
    bindings: dict[str, str]
    version: int
    created_at: datetime
    updated_at: datetime


#: Awaited in the write's transaction before its commit, with the row before and after it (`None`
#: before a create, after a delete); if it raises or outlasts its bound, nothing is written.
HotkeyProfileWriteAhead = Callable[
    [HotkeyProfileRow | None, HotkeyProfileRow | None], Awaitable[None]
]
#: An activation's write-ahead: the profile before and after, and the id of the profile it
#: deactivates (`None` when none was active), as `hotkey_profile.activated` records them.
HotkeyActivationWriteAhead = Callable[
    [HotkeyProfileRow, HotkeyProfileRow, UUID | None], Awaitable[None]
]


class HotkeyProfileNotFoundError(Exception):
    """The owner holds no profile with this id; nothing was written."""


class HotkeyProfileStaleError(Exception):
    """The profile is not at the version the caller named; nothing was written."""

    def __init__(self, version: int) -> None:
        super().__init__("the profile is at another version")
        self.version = version  # the current one


class HotkeyProfileNameTakenError(Exception):
    """`ux_hk_name`: another of the owner's profiles holds the name as `lower()` folds it."""


class HotkeyProfileLimitError(Exception):
    """The owner already holds `MAX_PROFILES` profiles (`limit_reached`); nothing was written."""


class HotkeyProfileActiveError(Exception):
    """The profile to delete is the owner's active one (`profile_active`); nothing was written."""


class HotkeyProfileStore(Protocol):
    """The owner's profiles. `replace` takes `expected_version=None` when the request names no
    version (no `If-Match`: last write wins); any other value is compared under the lock, so one
    that no row holds, such as 0, always answers `HotkeyProfileStaleError` with the current one,
    or `HotkeyProfileNotFoundError` first."""

    async def list_own(self, owner: UUID) -> list[HotkeyProfileRow]: ...

    async def get_own(self, owner: UUID, profile_id: UUID) -> HotkeyProfileRow | None: ...

    async def get_active(self, owner: UUID) -> HotkeyProfileRow | None: ...

    async def exists_for_other_owner(self, owner: UUID, profile_id: UUID) -> bool: ...

    async def create(
        self,
        owner: UUID,
        profile_id: UUID,
        fields: HotkeyProfileFields,
        *,
        write_ahead: HotkeyProfileWriteAhead,
    ) -> HotkeyProfileRow: ...

    async def replace(
        self,
        owner: UUID,
        profile_id: UUID,
        fields: HotkeyProfileFields,
        *,
        expected_version: int | None,
        write_ahead: HotkeyProfileWriteAhead,
    ) -> HotkeyProfileRow: ...

    async def activate(
        self, owner: UUID, profile_id: UUID, *, write_ahead: HotkeyActivationWriteAhead
    ) -> HotkeyProfileRow: ...

    async def delete(
        self, owner: UUID, profile_id: UUID, *, write_ahead: HotkeyProfileWriteAhead
    ) -> HotkeyProfileRow: ...


__all__ = [
    "MAX_PROFILES", "NAME_MAX", "HotkeyActivationWriteAhead", "HotkeyProfileActiveError",
    "HotkeyProfileFields", "HotkeyProfileLimitError", "HotkeyProfileNameTakenError",
    "HotkeyProfileNotFoundError", "HotkeyProfileRow", "HotkeyProfileStaleError",
    "HotkeyProfileStore", "HotkeyProfileWriteAhead",
]  # fmt: skip
