"""E42-T03: the flag write port, its changes counter, and the fakes that stand in for its
adapters: the row lock, the no-row outage, role overrides kept, and the user directory."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from datetime import timedelta
from uuid import UUID

import pytest

from candleviewer.admin.flags import FlagWrite, StaleWriteError, StoredFlag, StoreUnavailableError
from candleviewer.admin.flags.metrics import export_flag_metrics, flag_changes_total
from candleviewer.audit.actions import UnknownAuditAction
from candleviewer.observability.metrics import CollectorRegistry
from tests.unit.admin.flag_fakes import T0, FakeAudit, FakeFlagStore, FakeUsers

_KEY, _USER = "rules.form_editor", UUID(int=1)
_CHANGE = FlagWrite(_KEY, False, {_USER: True}, T0, _USER)


async def _prepare(row: StoredFlag) -> FlagWrite:
    await asyncio.sleep(0)  # yields under the row lock, as a write-ahead audit append does
    return _CHANGE


def _store() -> FakeFlagStore:
    store = FakeFlagStore()
    store.rows[_KEY] = StoredFlag(True, role_overrides={"manager": False}, updated_at=T0)
    return store


def test_the_changes_counter_is_labelled_by_flag_then_result() -> None:
    assert flag_changes_total._labelnames == ("flag", "result")


def test_the_changes_counter_is_exported() -> None:
    registry = CollectorRegistry()
    flag_changes_total.labels(_KEY, "ok").inc()
    collector = export_flag_metrics(registry, env="demo")
    try:
        names = {s.name for family in registry.collect() for s in family.samples}
        assert "cv_feature_flag_changes_total" in names
    finally:
        collector.close()


def test_a_change_cannot_be_altered_after_prepare_returns_it() -> None:
    with pytest.raises(FrozenInstanceError):
        _CHANGE.__setattr__("value", True)


def test_a_stale_write_carries_the_row_as_it_stands() -> None:
    row = StoredFlag(True, updated_at=T0)
    assert (str(StaleWriteError(row)), StaleWriteError(row).current) == ("stale write", row)


async def test_a_write_replaces_value_and_user_overrides_and_keeps_role_overrides() -> None:
    store = _store()
    row = await store.write(_KEY, _prepare)
    assert (row.value, row.user_overrides) == (False, {_USER: True})
    assert row.role_overrides == {"manager": False} and row.updated_by == _USER
    assert row.updated_at == T0 + timedelta(seconds=1) and store.writes == [_CHANGE]


async def test_a_flag_without_a_row_is_a_store_outage() -> None:
    with pytest.raises(StoreUnavailableError):
        await FakeFlagStore().write(_KEY, _prepare)


async def test_the_row_lock_serialises_two_writes_so_the_second_is_stale() -> None:
    store = _store()
    done = await asyncio.gather(
        *(store.write(_KEY, _prepare) for _ in "ab"), return_exceptions=True
    )
    assert [type(result) for result in done] == [StoredFlag, StaleWriteError]
    assert store.writes == [_CHANGE]


async def test_the_fake_directory_names_the_users_it_does_not_know() -> None:
    users = FakeUsers({_USER})
    assert await users.unknown(frozenset({_USER, UUID(int=2)})) == {UUID(int=2)}
    assert users.lookups == [frozenset({_USER, UUID(int=2)})]


async def test_the_fake_audit_refuses_an_unregistered_action_as_emit_does() -> None:
    with pytest.raises(UnknownAuditAction):
        await FakeAudit().emit("flags.unregistered", actor_label="owner")
