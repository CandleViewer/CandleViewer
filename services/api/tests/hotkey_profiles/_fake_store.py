"""The in-memory `HotkeyProfileStore` (E10-T05, #5211), for router and contract tests, as
`tests/watchlists/_watchlists_env.py` keeps the watchlist one. It holds the store's semantics, which
tests/hotkey_profiles/_store_contract.py states once for it and for Postgres."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from candleviewer.storage.repositories.hotkey_profiles import (
    MAX_PROFILES,
    HotkeyActivationWriteAhead,
    HotkeyProfileActiveError,
    HotkeyProfileFields,
    HotkeyProfileLimitError,
    HotkeyProfileNameTakenError,
    HotkeyProfileNotFoundError,
    HotkeyProfileRow,
    HotkeyProfileStaleError,
    HotkeyProfileWriteAhead,
)

T0 = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


class FakeHotkeyProfileStore:
    """Owner-scoped calls, `ux_hk_name` per owner as `lower()` folds it, `MAX_PROFILES`, one
    active profile, the guarded replace, and the write-ahead hook awaited before anything changes
    (a hook that raises leaves the store as it was)."""

    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, HotkeyProfileRow] = {}
        self.fail: Exception | None = None  # raised by every call (a store outage)
        self.tick = 0

    def _check(self) -> None:
        if self.fail is not None:
            raise self.fail

    def _now(self) -> datetime:
        self.tick += 1
        return T0 + timedelta(microseconds=self.tick)

    def _owned(self, owner: uuid.UUID) -> list[HotkeyProfileRow]:
        return [r for r in self.rows.values() if r.owner_user_id == owner]

    def _taken(self, owner: uuid.UUID, name: str, exclude: uuid.UUID | None = None) -> bool:
        return any(r.name.lower() == name.lower() and r.id != exclude for r in self._owned(owner))

    def own(self, owner: uuid.UUID, profile_id: uuid.UUID) -> HotkeyProfileRow | None:
        row = self.rows.get(profile_id)
        return row if row is not None and row.owner_user_id == owner else None

    def seed(
        self, owner: uuid.UUID, name: str = "Theirs", *, is_active: bool = False,
        bindings: dict[str, str] | None = None,
    ) -> HotkeyProfileRow:  # fmt: skip
        """A profile stored directly, as another session would have."""
        pid, now = uuid.uuid4(), self._now()
        stored = {"ticket.side_buy": "B"} if bindings is None else bindings
        self.rows[pid] = HotkeyProfileRow(pid, owner, name, is_active, stored, 1, now, now)
        return self.rows[pid]

    async def list_own(self, owner: uuid.UUID) -> list[HotkeyProfileRow]:
        self._check()
        return sorted(self._owned(owner), key=lambda r: (r.created_at, r.id))

    async def get_own(self, owner: uuid.UUID, profile_id: uuid.UUID) -> HotkeyProfileRow | None:
        self._check()
        return self.own(owner, profile_id)

    async def get_active(self, owner: uuid.UUID) -> HotkeyProfileRow | None:
        self._check()
        return next((r for r in self._owned(owner) if r.is_active), None)

    async def exists_for_other_owner(self, owner: uuid.UUID, profile_id: uuid.UUID) -> bool:
        self._check()
        row = self.rows.get(profile_id)
        return row is not None and row.owner_user_id != owner

    async def create(
        self, owner: uuid.UUID, profile_id: uuid.UUID, fields: HotkeyProfileFields, *,
        write_ahead: HotkeyProfileWriteAhead,
    ) -> HotkeyProfileRow:  # fmt: skip
        self._check()
        if len(self._owned(owner)) >= MAX_PROFILES:
            raise HotkeyProfileLimitError
        if self._taken(owner, fields.name):
            raise HotkeyProfileNameTakenError
        now = self._now()
        row = HotkeyProfileRow(profile_id, owner, fields.name, False, dict(fields.bindings), 1,
                               now, now)  # fmt: skip
        await write_ahead(None, row)
        self.rows[profile_id] = row
        return row

    async def replace(
        self, owner: uuid.UUID, profile_id: uuid.UUID, fields: HotkeyProfileFields, *,
        expected_version: int | None, write_ahead: HotkeyProfileWriteAhead,
    ) -> HotkeyProfileRow:  # fmt: skip
        self._check()
        before = self.own(owner, profile_id)
        if before is None:
            raise HotkeyProfileNotFoundError
        if expected_version is not None and expected_version != before.version:
            raise HotkeyProfileStaleError(before.version)
        if self._taken(owner, fields.name, profile_id):
            raise HotkeyProfileNameTakenError
        after = replace(before, name=fields.name, bindings=dict(fields.bindings),
                        version=before.version + 1, updated_at=self._now())  # fmt: skip
        await write_ahead(before, after)
        self.rows[profile_id] = after
        return after

    async def activate(
        self, owner: uuid.UUID, profile_id: uuid.UUID, *, write_ahead: HotkeyActivationWriteAhead
    ) -> HotkeyProfileRow:
        self._check()
        before = self.own(owner, profile_id)
        if before is None:
            raise HotkeyProfileNotFoundError
        if before.is_active:
            return before
        previous = next((r for r in self._owned(owner) if r.is_active), None)
        after = replace(before, is_active=True)
        await write_ahead(before, after, None if previous is None else previous.id)
        if previous is not None:
            self.rows[previous.id] = replace(previous, is_active=False)
        self.rows[profile_id] = after
        return after

    async def delete(
        self, owner: uuid.UUID, profile_id: uuid.UUID, *, write_ahead: HotkeyProfileWriteAhead
    ) -> HotkeyProfileRow:
        self._check()
        before = self.own(owner, profile_id)
        if before is None:
            raise HotkeyProfileNotFoundError
        if before.is_active:
            raise HotkeyProfileActiveError
        await write_ahead(before, None)
        del self.rows[profile_id]
        return before
