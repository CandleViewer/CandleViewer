"""The store contract on the in-memory fake (E10-T05, #5211): every case of
tests/hotkey_profiles/_store_contract.py, which tests/integration/storage/
test_hotkey_profiles_store_pg.py runs on Postgres too, and the fake's outage switch."""

from __future__ import annotations

import uuid

import pytest

from tests.hotkey_profiles._fake_store import FakeHotkeyProfileStore
from tests.hotkey_profiles._store_contract import CASES, FIELDS, Recorder


class _FakeHarness:
    def __init__(self) -> None:
        self.store = FakeHotkeyProfileStore()

    async def owner(self) -> uuid.UUID:
        return uuid.uuid4()


@pytest.mark.parametrize("name", sorted(CASES))
async def test_the_fake_holds_the_store_contract(name: str) -> None:
    await CASES[name](_FakeHarness())


async def test_an_outage_refuses_every_call() -> None:
    harness = _FakeHarness()
    owner, pid, rec = await harness.owner(), uuid.uuid4(), Recorder()
    harness.store.fail = ConnectionError("down")
    store = harness.store
    calls = [
        store.list_own(owner), store.get_own(owner, pid), store.get_active(owner),
        store.exists_for_other_owner(owner, pid),
        store.create(owner, pid, FIELDS, write_ahead=rec.write),
        store.replace(owner, pid, FIELDS, expected_version=None, write_ahead=rec.write),
        store.activate(owner, pid, write_ahead=rec.activation),
        store.delete(owner, pid, write_ahead=rec.write),
    ]  # fmt: skip
    for call in calls:
        with pytest.raises(ConnectionError):
            await call
    assert rec.calls == [] and store.rows == {}


async def test_seed_stores_a_profile_as_another_session_would() -> None:
    store, owner = FakeHotkeyProfileStore(), uuid.uuid4()
    row = store.seed(owner, "Mine", is_active=True, bindings={"dom.arm": "Ctrl+Shift+T"})
    assert await store.get_active(owner) == row
    assert (row.version, row.bindings) == (1, {"dom.arm": "Ctrl+Shift+T"})
    assert store.seed(owner).bindings == {"ticket.side_buy": "B"}
