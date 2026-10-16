"""E42-T01: the recorded sub-account tier is read from the `settings` store, never inferred.

`SettingsTierReader` is the capacity `TierPort` over `SystemSettings`; `build_system_settings` and
`build_admin_read_models(system_settings=...)` wire it. No row is the contract's "unrecorded"
(`tier` and `cap` null) whatever the sub-account count says; a store that cannot be read is an
error slice, never "unrecorded"."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

import candleviewer.admin_wiring as wiring
from candleviewer.admin.overview.capacity import AdminCapacityService, SubaccountCapacity, Tier
from candleviewer.admin.overview.fanout import SliceFanOut
from candleviewer.admin.overview.ports import SUBACCOUNT_TIER_KEY, RecordedTier
from candleviewer.settings import Settings
from candleviewer.storage.repositories.system_settings import StoredSetting
from tests.unit.storage.fakes_system_settings import FakeSystemSettings

_AT = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
_NOW = datetime(2026, 10, 16, 0, 30, tzinfo=UTC)


class _Used:
    def __init__(self, used: int) -> None:
        self.used = used

    async def subaccounts_in_use(self) -> int:
        return self.used


def _store(word: str | None = None) -> FakeSystemSettings:
    store = FakeSystemSettings()
    if word is not None:
        store.rows[SUBACCOUNT_TIER_KEY] = StoredSetting(word, _AT)
    return store


async def _slice(store: FakeSystemSettings | None, used: int = 3) -> Any:
    reader = None if store is None else wiring.SettingsTierReader(store)
    fan = SliceFanOut(now=lambda: _NOW)
    service = AdminCapacityService(fan, subaccounts=_Used(used), tier=reader, now=lambda: _NOW)
    return (await service.capacity()).subaccounts


async def test_no_row_reads_as_none_and_a_row_as_its_word_and_time() -> None:
    assert await wiring.SettingsTierReader(_store()).recorded_tier() is None
    reader = wiring.SettingsTierReader(_store("business_kyc"))
    assert await reader.recorded_tier() == RecordedTier("business_kyc", _AT)


@pytest.mark.parametrize("used", [0, 7, 21], ids=["none", "over-5", "over-20"])
async def test_an_empty_store_is_unrecorded_whatever_the_sub_account_count_suggests(
    used: int,
) -> None:
    got = await _slice(_store(), used)
    assert got.status == "ok"  # "never recorded" is a fact, not a failure
    assert got.value == SubaccountCapacity(None, None, used, "unrecorded", None)


@pytest.mark.parametrize(("word", "cap"), [("regular", 5), ("business_kyc", 20)])
async def test_a_recorded_tier_sets_the_cap_and_names_its_time(word: Tier, cap: int) -> None:
    got = await _slice(_store(word), used=3)
    assert (got.status, got.value) == ("ok", SubaccountCapacity(word, cap, 3, "recorded", _AT))


@pytest.mark.parametrize("word", ["enterprise", "Regular", "null"])
async def test_a_stored_word_that_is_no_tier_is_an_error_never_a_guess(word: str) -> None:
    got = await _slice(_store(word))
    assert (got.status, got.detail) == ("error", "tier: unrecognised value")
    assert got.value == SubaccountCapacity(None, None, 3, None, None)  # tier fields stay unread


async def test_an_unreachable_store_is_an_error_slice_never_unrecorded() -> None:
    store = _store("regular")
    store.down = True
    got = await _slice(store)
    assert (got.status, got.detail) == ("error", "tier: source failed")
    assert got.value == SubaccountCapacity(None, None, 3, None, None)  # `used` is still read


async def test_with_no_store_wired_the_tier_is_unavailable_not_unrecorded() -> None:
    got = await _slice(None)
    assert (got.status, got.detail) == ("unavailable", "tier: no provider wired")


# -- composition-root wiring ---------------------------------------------------------------------


def test_only_the_real_backend_has_a_settings_store(monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[tuple[str, str]] = []

    def relational(dsn: str, suffix: str) -> str:
        made.append((dsn, suffix))
        return "relational"

    monkeypatch.setattr(wiring, "SqlAlchemyRelationalRepository", relational)
    monkeypatch.setattr(wiring, "SqlAlchemySystemSettings", lambda rel: ("settings", rel))
    assert wiring.build_system_settings(Settings(storage_backend="fake")) is None
    settings = Settings(storage_backend="real")
    built: Any = wiring.build_system_settings(settings)  # the patched constructor's tuple
    assert (built, made) == (
        ("settings", "relational"),
        [(settings.pg_dsn.get_secret_value(), "admin")],
    )


def test_the_admin_area_builds_one_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[str] = []
    monkeypatch.setattr(
        wiring, "SqlAlchemyRelationalRepository", lambda _d, name: made.append(name)
    )
    monkeypatch.setattr(wiring, "SqlAlchemyAdminCounts", lambda _rel, *, env: made.append("counts"))
    settings = Settings(storage_backend="real")
    wiring.build_admin_read_models(settings, system_settings=wiring.build_system_settings(settings))
    assert made == ["admin", "counts"]  # the settings store's repository, once; the counts ride it


async def test_the_read_models_get_the_tier_only_when_a_store_is_passed() -> None:
    fake = Settings(storage_backend="fake")
    _, wired = wiring.build_admin_read_models(
        fake, now=lambda: _NOW, system_settings=_store("regular")
    )
    _, bare = wiring.build_admin_read_models(fake, now=lambda: _NOW)
    got, unwired = (await wired.capacity()).subaccounts, (await bare.capacity()).subaccounts
    assert got.value is not None and (got.value.tier, got.value.cap) == ("regular", 5)
    assert got.value.recorded_at == _AT and got.detail == "subaccounts: no provider wired"
    assert unwired.value == SubaccountCapacity(None, None, None, None, None)  # nothing wired
