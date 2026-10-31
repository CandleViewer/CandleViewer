"""In-memory `UserSettings` (E02-T13, #5181), kept honest by `user_settings_contract.py`, which
runs against it and against Postgres. Writers of one user queue on a per-user lock; the hook runs
before the change is visible, and a raising hook leaves the store as it was. Two values are the
same as Postgres `jsonb` compares them: a boolean never equals a number, and numbers compare by
value. `down` fails every call like an unreachable database; `commit_fails` fails only the commit,
after the hook ran."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from uuid import UUID

from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.user_settings import (
    LeafChange,
    UserSetting,
    UserSettingsWriteAhead,
)
from tests.unit.storage.fakes_replay_sessions import FakeClock


def same_json(a: object, b: object) -> bool:
    """`jsonb` equality: booleans only equal booleans, numbers compare by value, and arrays and
    objects compare member by member."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same_json(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same_json(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


class FakeUserSettings:
    def __init__(self, clock: FakeClock | None = None) -> None:
        self.clock = clock or FakeClock()
        self.rows: dict[UUID, dict[str, UserSetting]] = {}
        self.calls: list[tuple[str, UUID]] = []  # ("read" | "apply", user id), in call order
        self.down = False
        self.commit_fails = False
        self._locks: dict[UUID, asyncio.Lock] = {}

    def _reachable(self) -> None:
        if self.down:
            raise StorageTierUnavailable("the settings store is unavailable")

    async def read(self, user_id: UUID) -> tuple[UserSetting, ...]:
        self.calls.append(("read", user_id))
        self._reachable()
        held = self.rows.get(user_id, {})
        return tuple(held[key] for key in sorted(held))

    async def apply(
        self, user_id: UUID, patch: Mapping[str, object], *, write_ahead: UserSettingsWriteAhead
    ) -> tuple[UserSetting, ...]:
        self.calls.append(("apply", user_id))
        self._reachable()
        async with self._locks.setdefault(user_id, asyncio.Lock()):
            held = self.rows.get(user_id, {})
            after, changes = dict(held), []
            for key in sorted(patch):
                value, row = patch[key], held.get(key)
                before = None if row is None else row.value
                if value is None and row is not None:
                    changes.append(LeafChange(key, before, None))
                    del after[key]
                elif value is not None and (row is None or not same_json(row.value, value)):
                    changes.append(LeafChange(key, before, value))
                    after[key] = UserSetting(key, value, self.clock())
            if changes:
                await write_ahead(tuple(changes))  # before the change is visible
                if self.commit_fails:
                    raise StorageTierUnavailable("the settings store is unavailable")
                self.rows[user_id] = after
        return tuple(after[key] for key in sorted(after))
