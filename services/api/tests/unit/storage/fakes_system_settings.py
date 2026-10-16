"""In-memory `SystemSettings` (E42-T01), kept honest by `system_settings_contract.py`, which runs
against it and against Postgres. Writers of one key queue on a per-key lock; the hook runs before
the new row is visible and a raising hook leaves the store as it was. `down` fails every call like
an unreachable database; `commit_fails` fails only the commit, after the hook ran."""

from __future__ import annotations

import asyncio
from uuid import UUID

from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.system_settings import StoredSetting, WriteAhead
from tests.unit.storage.fakes_replay_sessions import FakeClock


class FakeSystemSettings:
    def __init__(self, clock: FakeClock | None = None) -> None:
        self.clock = clock or FakeClock()
        self.rows: dict[str, StoredSetting] = {}
        self.written_by: dict[str, UUID] = {}
        self.calls: list[tuple[str, str]] = []  # ("get" | "put", key), in call order
        self.down = False
        self.commit_fails = False
        self._locks: dict[str, asyncio.Lock] = {}

    def _reachable(self) -> None:
        if self.down:
            raise StorageTierUnavailable("settings store unavailable")

    async def get_string(self, key: str) -> StoredSetting | None:
        self.calls.append(("get", key))
        self._reachable()
        return self.rows.get(key)

    async def put_string(
        self, key: str, value: str, *, updated_by: UUID, write_ahead: WriteAhead
    ) -> StoredSetting:
        self.calls.append(("put", key))
        self._reachable()
        async with self._locks.setdefault(key, asyncio.Lock()):
            row = StoredSetting(value, self.clock())
            await write_ahead(self.rows.get(key))  # before the new row is visible
            if self.commit_fails:
                raise StorageTierUnavailable("settings store unavailable")
            self.rows[key], self.written_by[key] = row, updated_by
        return row
