"""Behavioural contract of `SystemSettings` (E42-T01): one suite, two subjects. The in-memory
fake (`test_system_settings_fake.py`) and Postgres (`tests/integration/storage/
test_system_settings_pg.py`) both run it, so the fake the admin route tests rely on cannot drift
from the real adapter. Not collected itself; subclasses supply `store`, `actor` and `tick` (time
passing between two writes)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

import pytest

from candleviewer.storage.repositories.system_settings import (
    StoredSetting,
    SystemSettings,
    WriteAhead,
)

KEY = "accounts.subaccount_tier"


class Refused(Exception):
    """What a refusing write-ahead hook raises: a type of its own, never an `OSError`."""


async def noop(_before: StoredSetting | None) -> None:
    return None


def recording(seen: list[StoredSetting | None]) -> WriteAhead:
    async def hook(before: StoredSetting | None) -> None:
        seen.append(before)

    return hook


class SystemSettingsContract:
    async def test_a_first_write_creates_the_row_a_read_returns(
        self, store: SystemSettings, actor: UUID
    ) -> None:
        assert await store.get_string(KEY) is None  # no row is `None`, never a default
        row = await store.put_string(KEY, "regular", updated_by=actor, write_ahead=noop)
        assert row.value == "regular"
        assert row.updated_at.utcoffset() == timedelta(0)  # tz-aware UTC, never naive
        assert await store.get_string(KEY) == row

    async def test_a_write_replaces_the_row_and_the_hook_sees_the_one_it_replaces(
        self, store: SystemSettings, actor: UUID, tick: Callable[[], None]
    ) -> None:
        seen: list[StoredSetting | None] = []
        rows = []
        for word in ("regular", "business_kyc", "business_kyc"):  # the last is a repeat
            rows.append(
                await store.put_string(KEY, word, updated_by=actor, write_ahead=recording(seen))
            )
            tick()
        assert seen == [None, *rows[:2]]  # no row on the first write, then the row replaced
        assert [r.value for r in rows] == ["regular", "business_kyc", "business_kyc"]
        assert rows[0].updated_at < rows[1].updated_at < rows[2].updated_at  # a repeat is a write
        assert await store.get_string(KEY) == rows[2]

    async def test_the_hook_runs_before_the_new_row_is_visible(
        self, store: SystemSettings, actor: UUID
    ) -> None:
        inside: list[StoredSetting | None] = []

        async def hook(_before: StoredSetting | None) -> None:
            inside.append(await store.get_string(KEY))  # another reader, outside the transaction

        await store.put_string(KEY, "regular", updated_by=actor, write_ahead=hook)
        assert inside == [None]  # write-ahead: the record precedes the commit (C-2.9)

    @pytest.mark.parametrize("seeded", [False, True], ids=["first-write", "replacement"])
    async def test_a_refusing_hook_leaves_the_store_as_it_was(
        self, store: SystemSettings, actor: UUID, seeded: bool
    ) -> None:
        first = None
        if seeded:
            first = await store.put_string(KEY, "regular", updated_by=actor, write_ahead=noop)

        async def refuse(_before: StoredSetting | None) -> None:
            raise Refused

        with pytest.raises(Refused):  # reaches the caller unchanged
            await store.put_string(KEY, "business_kyc", updated_by=actor, write_ahead=refuse)
        assert await store.get_string(KEY) == first
