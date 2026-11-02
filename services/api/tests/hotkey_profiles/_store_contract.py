"""The `HotkeyProfileStore` contract (E10-T05, #5211): what the in-memory fake and the Postgres
store must both do, stated once. tests/hotkey_profiles/test_hotkey_profiles_store_fake.py runs every
case on the fake; tests/integration/storage/test_hotkey_profiles_store_pg.py runs the same cases on
Postgres 16, so a router test over the fake proves what the real store does.

Each case takes a `Harness`: the store and a way to make an owner (Postgres needs a `users` row).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol

import pytest

from candleviewer.storage.repositories.hotkey_profiles import (
    MAX_PROFILES,
    HotkeyProfileActiveError,
    HotkeyProfileFields,
    HotkeyProfileLimitError,
    HotkeyProfileNameTakenError,
    HotkeyProfileNotFoundError,
    HotkeyProfileRow,
    HotkeyProfileStaleError,
    HotkeyProfileStore,
)

#: Every shape a stored binding takes: a chord, a range, a named key, an arrow, unbound.
BINDINGS = {
    "ticket.side_buy": "Ctrl+B",
    "global.nav_rail": "Alt+1..9",
    "dom.recentre": "Space",
    "replay.step_bar_back": "←",
    "chart.footprint_toggle": "",
}
FIELDS = HotkeyProfileFields("Scalping", BINDINGS)


class Harness(Protocol):
    @property
    def store(self) -> HotkeyProfileStore: ...

    async def owner(self) -> uuid.UUID: ...


class Refused(Exception):
    """What a refused audit record raises inside the write's transaction."""


class Recorder:
    """The write-ahead hooks: each call recorded, or `Refused` raised while `refuse` is set."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.refuse = False

    async def write(self, before: HotkeyProfileRow | None, after: HotkeyProfileRow | None) -> None:
        if self.refuse:
            raise Refused
        self.calls.append((before, after))

    async def activation(
        self, before: HotkeyProfileRow, after: HotkeyProfileRow, previous: uuid.UUID | None
    ) -> None:
        if self.refuse:
            raise Refused
        self.calls.append((before, after, previous))


Case = Callable[[Harness], Awaitable[None]]
CASES: dict[str, Case] = {}


def case(fn: Case) -> Case:
    CASES[fn.__name__] = fn
    return fn


def _named(name: str) -> HotkeyProfileFields:
    return HotkeyProfileFields(name, BINDINGS)


async def _create(h: Harness, owner: uuid.UUID, name: str = "Scalping") -> HotkeyProfileRow:
    return await h.store.create(owner, uuid.uuid4(), _named(name), write_ahead=Recorder().write)


@case
async def create_answers_an_inactive_profile_at_version_1(h: Harness) -> None:
    owner, rec = await h.owner(), Recorder()
    row = await h.store.create(owner, uuid.uuid4(), FIELDS, write_ahead=rec.write)
    assert (row.owner_user_id, row.name, row.bindings) == (owner, "Scalping", BINDINGS)
    assert (row.is_active, row.version, row.created_at) == (False, 1, row.updated_at)
    assert rec.calls == [(None, row)]
    assert await h.store.list_own(owner) == [row]
    assert await h.store.get_own(owner, row.id) == row
    assert await h.store.get_active(owner) is None


@case
async def profiles_are_listed_in_creation_order(h: Harness) -> None:
    owner = await h.owner()
    rows = [await _create(h, owner, name) for name in ("Zeta", "Alpha", "Mid")]
    assert await h.store.list_own(owner) == rows


@case
async def another_owner_neither_sees_nor_writes_a_profile(h: Harness) -> None:
    mine, theirs, rec = await h.owner(), await h.owner(), Recorder()
    row = await _create(h, mine)
    await h.store.activate(mine, row.id, write_ahead=rec.activation)
    held = await h.store.get_own(mine, row.id)
    assert await h.store.get_own(theirs, row.id) is None
    assert await h.store.list_own(theirs) == [] and await h.store.get_active(theirs) is None
    assert await h.store.exists_for_other_owner(theirs, row.id) is True
    assert await h.store.exists_for_other_owner(mine, row.id) is False
    assert await h.store.exists_for_other_owner(mine, uuid.uuid4()) is False
    rec.calls.clear()
    with pytest.raises(HotkeyProfileNotFoundError):
        await h.store.replace(theirs, row.id, FIELDS, expected_version=None, write_ahead=rec.write)
    with pytest.raises(HotkeyProfileNotFoundError):
        await h.store.activate(theirs, row.id, write_ahead=rec.activation)
    with pytest.raises(HotkeyProfileNotFoundError):
        await h.store.delete(theirs, row.id, write_ahead=rec.write)
    assert rec.calls == [] and await h.store.get_own(mine, row.id) == held


@case
async def the_cap_refuses_a_profile_past_the_twentieth(h: Harness) -> None:
    owner, rec = await h.owner(), Recorder()
    for n in range(MAX_PROFILES):
        await _create(h, owner, f"P{n}")
    with pytest.raises(HotkeyProfileLimitError):
        await h.store.create(owner, uuid.uuid4(), _named("One too many"), write_ahead=rec.write)
    assert rec.calls == [] and len(await h.store.list_own(owner)) == MAX_PROFILES
    await _create(h, await h.owner(), "Another user's first")


@case
async def a_name_is_taken_per_owner_as_lower_folds_it(h: Harness) -> None:
    owner, other, rec = await h.owner(), await h.owner(), Recorder()
    first = await _create(h, owner, "Scalping")
    with pytest.raises(HotkeyProfileNameTakenError):
        await h.store.create(owner, uuid.uuid4(), _named("SCALPING"), write_ahead=rec.write)
    second = await _create(h, owner, "Swing")
    with pytest.raises(HotkeyProfileNameTakenError):
        await h.store.replace(owner, second.id, _named("scalping"), expected_version=None,
                              write_ahead=rec.write)  # fmt: skip
    assert rec.calls == [] and await h.store.get_own(owner, second.id) == second
    renamed = await h.store.replace(
        owner, first.id, _named("SCALPING"), expected_version=None, write_ahead=rec.write
    )  # its own name, in other letters
    assert renamed.name == "SCALPING"
    await _create(h, other, "scalping")  # another user's names are another namespace


@case
async def a_replace_with_no_version_wins_and_raises_the_version(h: Harness) -> None:
    owner, rec = await h.owner(), Recorder()
    row = await _create(h, owner)
    swapped = HotkeyProfileFields("Swing", {"ticket.side_buy": "Alt+B"})
    second = await h.store.replace(owner, row.id, swapped, expected_version=None,
                                   write_ahead=rec.write)  # fmt: skip
    assert (second.name, second.bindings, second.version) == ("Swing", swapped.bindings, 2)
    assert (second.created_at, second.is_active) == (row.created_at, row.is_active)
    assert second.updated_at >= row.updated_at
    assert rec.calls == [(row, second)]
    third = await h.store.replace(owner, row.id, FIELDS, expected_version=None,
                                  write_ahead=rec.write)  # fmt: skip
    assert third.version == 3 and await h.store.get_own(owner, row.id) == third


@case
async def a_replace_at_another_version_writes_nothing(h: Harness) -> None:
    owner, rec = await h.owner(), Recorder()
    row = await _create(h, owner)
    for named in (2, 0):  # a later version, and one no row ever holds
        with pytest.raises(HotkeyProfileStaleError) as stale:
            await h.store.replace(owner, row.id, _named("Lost"), expected_version=named,
                                  write_ahead=rec.write)  # fmt: skip
        assert stale.value.version == 1
    assert rec.calls == [] and await h.store.get_own(owner, row.id) == row
    kept = await h.store.replace(owner, row.id, _named("Kept"), expected_version=1,
                                 write_ahead=rec.write)  # fmt: skip
    assert (kept.version, kept.name) == (2, "Kept")
    with pytest.raises(HotkeyProfileNotFoundError):
        await h.store.replace(owner, uuid.uuid4(), FIELDS, expected_version=1,
                              write_ahead=rec.write)  # fmt: skip


@case
async def activating_deactivates_the_other_and_changes_no_version(h: Harness) -> None:
    owner, rec = await h.owner(), Recorder()
    one, two = await _create(h, owner, "One"), await _create(h, owner, "Two")
    first = await h.store.activate(owner, one.id, write_ahead=rec.activation)
    assert first.is_active and (first.version, first.updated_at) == (one.version, one.updated_at)
    assert rec.calls == [(one, first, None)]
    assert await h.store.get_active(owner) == first
    second = await h.store.activate(owner, two.id, write_ahead=rec.activation)
    assert rec.calls[1] == (two, second, one.id)
    assert await h.store.get_active(owner) == second
    assert await h.store.get_own(owner, one.id) == one  # inactive again, as it was
    again = await h.store.activate(owner, two.id, write_ahead=rec.activation)
    assert again == second and len(rec.calls) == 2  # the active one: nothing written
    with pytest.raises(HotkeyProfileNotFoundError):
        await h.store.activate(owner, uuid.uuid4(), write_ahead=rec.activation)


@case
async def a_delete_removes_the_row_but_never_the_active_profile(h: Harness) -> None:
    owner, rec = await h.owner(), Recorder()
    active, spare = await _create(h, owner, "Active"), await _create(h, owner, "Spare")
    active = await h.store.activate(owner, active.id, write_ahead=rec.activation)
    rec.calls.clear()
    with pytest.raises(HotkeyProfileActiveError):
        await h.store.delete(owner, active.id, write_ahead=rec.write)
    assert rec.calls == [] and await h.store.get_own(owner, active.id) == active
    assert await h.store.delete(owner, spare.id, write_ahead=rec.write) == spare
    assert rec.calls == [(spare, None)]
    assert await h.store.get_own(owner, spare.id) is None
    assert await h.store.list_own(owner) == [active]
    with pytest.raises(HotkeyProfileNotFoundError):
        await h.store.delete(owner, spare.id, write_ahead=rec.write)


@case
async def a_refused_record_changes_nothing(h: Harness) -> None:
    owner, rec = await h.owner(), Recorder()
    active, spare = await _create(h, owner, "Active"), await _create(h, owner, "Spare")
    active = await h.store.activate(owner, active.id, write_ahead=rec.activation)
    rec.refuse = True
    with pytest.raises(Refused):
        await h.store.create(owner, uuid.uuid4(), _named("Never"), write_ahead=rec.write)
    with pytest.raises(Refused):
        await h.store.replace(owner, spare.id, _named("Never"), expected_version=None,
                              write_ahead=rec.write)  # fmt: skip
    with pytest.raises(Refused):
        await h.store.activate(owner, spare.id, write_ahead=rec.activation)
    with pytest.raises(Refused):
        await h.store.delete(owner, spare.id, write_ahead=rec.write)
    assert await h.store.list_own(owner) == [active, spare]
    assert await h.store.get_active(owner) == active


__all__ = ["BINDINGS", "CASES", "FIELDS", "Harness", "Recorder", "Refused"]
