"""`FakeSystemSettings` against the shared contract (E42-T01)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from uuid import UUID

import pytest

from tests.unit.storage.fakes_system_settings import FakeSystemSettings
from tests.unit.storage.system_settings_contract import SystemSettingsContract


class TestFakeSystemSettings(SystemSettingsContract):
    @pytest.fixture
    def store(self) -> FakeSystemSettings:
        return FakeSystemSettings()

    @pytest.fixture
    def actor(self) -> UUID:
        return uuid.uuid4()

    @pytest.fixture
    def tick(self, store: FakeSystemSettings) -> Callable[[], None]:
        def advance() -> None:
            store.clock.advance(seconds=1)

        return advance
