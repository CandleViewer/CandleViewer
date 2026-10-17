"""`InMemoryFlagRepository` (E42-T03), the fake backend's flag store: seeded at the defaults it is
given, and the Postgres repository's write contract (the stale check, a missing row, user overrides
replaced and role overrides kept, `updated_at` always moving on)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from candleviewer.storage.repositories import flags_sqlalchemy as f
from candleviewer.storage.testing.flags import InMemoryFlagRepository

_T0 = datetime(2026, 10, 16, 8, 0, tzinfo=UTC)
_ACTOR, _USER = uuid.UUID(int=7), uuid.UUID(int=9)
_SEEDS = [f.FlagSeed("a.b", "boolean", "", True, False)]


def _to(value: object, at: datetime, users: dict[uuid.UUID, object] | None = None) -> f.RowPrepare:
    async def prepare(row: f.FlagRow) -> f.FlagChange:
        return f.FlagChange(value, users or {}, at, _ACTOR)

    return prepare


async def test_it_starts_at_the_defaults_and_ensure_never_overwrites() -> None:
    repo = InMemoryFlagRepository(_SEEDS, clock=lambda: _T0)
    await repo.ensure(
        [f.FlagSeed("a.b", "", "", False, False), f.FlagSeed("c.d", "", "", 0, False)]
    )
    rows = {"a.b": f.FlagRow(True, {}, {}, _T0, None), "c.d": f.FlagRow(0, {}, {}, _T0, None)}
    assert await repo.load() == rows


async def test_a_write_replaces_the_user_overrides_keeps_the_role_ones_and_moves_on() -> None:
    repo = InMemoryFlagRepository(_SEEDS, clock=lambda: _T0)  # a clock that stands still
    repo._rows["a.b"] = replace(repo._rows["a.b"], role_overrides={"viewer": False})
    with pytest.raises(f.StaleFlagRowError) as stale:  # one microsecond before: another state
        await repo.write("a.b", _to(False, _T0 - timedelta(microseconds=1)))
    assert stale.value.current == (await repo.load())["a.b"]
    with pytest.raises(f.FlagRowMissingError):
        await repo.write("x.y", _to(False, _T0))
    written = await repo.write("a.b", _to(False, _T0, {_USER: True}))
    later = _T0 + timedelta(microseconds=1)  # so `updated_at` moves on by one microsecond
    assert written == f.FlagRow(False, {_USER: True}, {"viewer": False}, later, _ACTOR)
    assert (await repo.load())["a.b"] == written
