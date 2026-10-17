"""In-memory flag repository (E42-T03), the fake backend's flag store, seeded at the registry
defaults: `SqlAlchemyFlagRepository`'s contract without a database."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta

from candleviewer.storage.repositories.flags_sqlalchemy import (
    FlagRow,
    FlagRowMissingError,
    FlagSeed,
    RowPrepare,
    StaleFlagRowError,
)


class InMemoryFlagRepository:
    def __init__(
        self,
        seeds: Iterable[FlagSeed],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._clock, self._lock = clock, asyncio.Lock()
        self._rows: dict[str, FlagRow] = {}
        self._seed(seeds)

    def _seed(self, seeds: Iterable[FlagSeed]) -> None:
        now = self._clock()
        for seed in seeds:
            self._rows.setdefault(seed.key, FlagRow(seed.default, {}, {}, now, None))

    async def ensure(self, seeds: Iterable[FlagSeed]) -> None:
        self._seed(seeds)

    async def load(self) -> Mapping[str, FlagRow]:
        return dict(self._rows)

    async def write(self, key: str, prepare: RowPrepare) -> FlagRow:
        async with self._lock:
            row = self._rows.get(key)
            if row is None:
                raise FlagRowMissingError(key)
            change = await prepare(row)
            if change.expected_updated_at != row.updated_at:
                raise StaleFlagRowError(row)
            at = max(self._clock(), row.updated_at + timedelta(microseconds=1))
            users = dict(change.user_overrides)
            self._rows[key] = FlagRow(change.value, users, row.role_overrides, at, change.actor)
            return self._rows[key]


__all__ = ["InMemoryFlagRepository"]
