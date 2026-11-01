"""Behavioural contract of `UserSettings` (E02-T13, #5181): one suite, two subjects. The in-memory
fake (`test_user_settings_fake.py`) and Postgres (`tests/integration/storage/
test_user_settings_pg.py`) both run it, so the fake the route tests rely on cannot drift from the
real adapter. Not collected itself; subclasses supply `store`, two users (`user`, `other`) and
`tick` (time passing between two writes)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

import pytest

from candleviewer.storage.repositories.user_settings import (
    LeafChange,
    UserSetting,
    UserSettings,
    UserSettingsWriteAhead,
)

THEME, DENSITY, DEPTH = "appearance.theme", "appearance.density", "data.default_depth"
QUIET = "notifications.quiet_hours"


class Refused(Exception):
    """What a refusing write-ahead hook raises: a type of its own, never an `OSError`."""


async def noop(_changes: tuple[LeafChange, ...]) -> None:
    return None


def recording(seen: list[tuple[LeafChange, ...]]) -> UserSettingsWriteAhead:
    async def hook(changes: tuple[LeafChange, ...]) -> None:
        seen.append(changes)

    return hook


async def refuse(_changes: tuple[LeafChange, ...]) -> None:
    raise Refused


def _values(rows: tuple[UserSetting, ...]) -> list[tuple[str, object]]:
    return [(row.key, row.value) for row in rows]


class UserSettingsContract:
    async def test_user_settings_read_of_a_user_with_no_rows_is_empty(
        self, store: UserSettings, user: UUID
    ) -> None:
        assert await store.read(user) == ()

    async def test_user_settings_apply_writes_each_leaf_and_read_returns_them_by_key(
        self, store: UserSettings, user: UUID
    ) -> None:
        rows = await store.apply(user, {THEME: "light", DENSITY: "compact"}, write_ahead=noop)
        assert _values(rows) == [(DENSITY, "compact"), (THEME, "light")]
        assert {row.updated_at.utcoffset() for row in rows} == {timedelta(0)}  # tz-aware UTC
        assert await store.read(user) == rows

    async def test_user_settings_apply_hands_the_hook_only_the_changed_leaves_by_key(
        self, store: UserSettings, user: UUID, tick: Callable[[], None]
    ) -> None:
        await store.apply(user, {THEME: "dark", DENSITY: "compact"}, write_ahead=noop)
        tick()
        seen: list[tuple[LeafChange, ...]] = []
        patch = {THEME: "light", DENSITY: "compact", DEPTH: 200}
        rows = await store.apply(user, patch, write_ahead=recording(seen))
        assert seen == [(LeafChange(THEME, "dark", "light"), LeafChange(DEPTH, None, 200))]
        assert _values(rows) == [(DENSITY, "compact"), (THEME, "light"), (DEPTH, 200)]

    async def test_user_settings_a_none_leaf_deletes_its_row_and_the_hook_sees_it_go(
        self, store: UserSettings, user: UUID
    ) -> None:
        await store.apply(user, {THEME: "dark", DENSITY: "compact"}, write_ahead=noop)
        seen: list[tuple[LeafChange, ...]] = []
        rows = await store.apply(user, {THEME: None}, write_ahead=recording(seen))
        assert seen == [(LeafChange(THEME, "dark", None),)]
        assert _values(rows) == [(DENSITY, "compact")]
        assert await store.read(user) == rows

    async def test_user_settings_a_patch_that_changes_nothing_awaits_no_hook_and_keeps_the_rows(
        self, store: UserSettings, user: UUID, tick: Callable[[], None]
    ) -> None:
        before = await store.apply(user, {THEME: "dark", DEPTH: 200}, write_ahead=noop)
        tick()
        seen: list[tuple[LeafChange, ...]] = []
        # the same values (a number equal in value too), and a reset of a leaf with no row
        rows = await store.apply(
            user, {THEME: "dark", DEPTH: 200.0, DENSITY: None}, write_ahead=recording(seen)
        )
        assert seen == []
        assert rows == before == await store.read(user)  # no time moved either

    async def test_user_settings_a_boolean_is_never_equal_to_a_number(
        self, store: UserSettings, user: UUID
    ) -> None:
        await store.apply(user, {QUIET: {"on": 1}}, write_ahead=noop)
        seen: list[tuple[LeafChange, ...]] = []
        await store.apply(user, {QUIET: {"on": True}}, write_ahead=recording(seen))
        assert seen == [(LeafChange(QUIET, {"on": 1}, {"on": True}),)]

    async def test_user_settings_every_json_type_round_trips(
        self, store: UserSettings, user: UUID
    ) -> None:
        patch: dict[str, object] = {
            THEME: "light",
            "appearance.font_scale": 1.25,
            DEPTH: 200,
            "appearance.reduce_motion": False,
            QUIET: {"from": "22:00", "to": "07:00", "days": [1, 2]},
            "trading.default_qty_presets": ["0.01", "0.050"],
        }
        await store.apply(user, patch, write_ahead=noop)
        assert dict(_values(await store.read(user))) == patch

    async def test_user_settings_a_refusing_hook_leaves_every_row_as_it_was(
        self, store: UserSettings, user: UUID
    ) -> None:
        kept = await store.apply(user, {THEME: "dark", DENSITY: "compact"}, write_ahead=noop)
        with pytest.raises(Refused):
            await store.apply(user, {THEME: "light", DENSITY: None}, write_ahead=refuse)
        assert await store.read(user) == kept

    async def test_user_settings_one_users_write_never_reads_or_changes_another_users_rows(
        self, store: UserSettings, user: UUID, other: UUID
    ) -> None:
        theirs = await store.apply(other, {THEME: "dark", DENSITY: "spacious"}, write_ahead=noop)
        seen: list[tuple[LeafChange, ...]] = []
        mine = await store.apply(user, {THEME: "light", DENSITY: None}, write_ahead=recording(seen))
        assert seen == [(LeafChange(THEME, None, "light"),)]  # theirs is no "before" of mine
        assert _values(mine) == [(THEME, "light")]
        assert await store.read(other) == theirs
