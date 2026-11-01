"""`FakeUserSettings` against the shared contract (E02-T13, #5181), and its outage switches."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from uuid import UUID

import pytest

from candleviewer.storage.errors import StorageTierUnavailable
from tests.unit.storage.fakes_user_settings import FakeUserSettings, same_json
from tests.unit.storage.user_settings_contract import THEME, UserSettingsContract, noop


class TestFakeUserSettings(UserSettingsContract):
    @pytest.fixture
    def store(self) -> FakeUserSettings:
        return FakeUserSettings()

    @pytest.fixture
    def user(self) -> UUID:
        return uuid.uuid4()

    @pytest.fixture
    def other(self) -> UUID:
        return uuid.uuid4()

    @pytest.fixture
    def tick(self, store: FakeUserSettings) -> Callable[[], None]:
        def advance() -> None:
            store.clock.advance(seconds=1)

        return advance


async def test_fake_user_settings_down_fails_every_call_as_an_outage() -> None:
    store, user = FakeUserSettings(), uuid.uuid4()
    store.down = True
    with pytest.raises(StorageTierUnavailable):
        await store.read(user)
    with pytest.raises(StorageTierUnavailable):
        await store.apply(user, {THEME: "light"}, write_ahead=noop)


async def test_fake_user_settings_a_failed_commit_runs_the_hook_and_keeps_the_rows() -> None:
    store, user, seen = FakeUserSettings(), uuid.uuid4(), []

    async def hook(changes: object) -> None:
        seen.append(changes)

    store.commit_fails = True
    with pytest.raises(StorageTierUnavailable):
        await store.apply(user, {THEME: "light"}, write_ahead=hook)
    assert len(seen) == 1
    assert await store.read(user) == ()


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        (1, 1.0, True),
        (True, 1, False),
        (False, 0, False),
        ([1, "a"], [1.0, "a"], True),
        ([1], [1, 2], False),
        ({"a": 1}, {"a": 1, "b": 2}, False),
        ({"a": [True]}, {"a": [True]}, True),
        ("1", 1, False),
    ],
)
def test_same_json_compares_as_jsonb_does(a: object, b: object, same: bool) -> None:
    assert same_json(a, b) is same
