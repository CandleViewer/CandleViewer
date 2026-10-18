"""Composition-root wiring of the incident list (E42-T05): what each backend serves, now that
every `error` and `critical` system event materialises its incident when it is written."""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

import candleviewer.admin_wiring as wiring
from candleviewer.admin.errors import OpsNotWired
from candleviewer.settings import Settings
from candleviewer.storage.repositories.incidents import IncidentRow
from candleviewer.storage.repositories.system_settings_sqlalchemy import SqlAlchemySystemSettings
from tests.unit.admin._ops_fakes import NOW, row


class FakeIncidents:
    """Stands in for `SqlAlchemyIncidents`: remembers its engine and serves one row."""

    built: ClassVar[list[Any]] = []

    def __init__(self, relational: Any) -> None:
        self.built.append(relational)

    async def page(self, *, status: str | None, after: Any, limit: int) -> list[IncidentRow]:
        return [row(1)]


@pytest.fixture(autouse=True)
def _fresh(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeIncidents.built = []
    monkeypatch.setattr(wiring, "SqlAlchemyIncidents", FakeIncidents)
    monkeypatch.setattr(wiring, "SqlAlchemyRelationalRepository", lambda dsn, suffix: suffix)


async def test_the_fake_backend_has_no_incident_store_so_the_list_is_never_made_up() -> None:
    incidents = wiring.build_admin_incidents(Settings(storage_backend="fake"))
    with pytest.raises(OpsNotWired):
        await incidents.page(status=None, cursor=None, limit=1)
    assert FakeIncidents.built == []  # no reader and no engine were even built


async def test_the_real_backend_serves_the_incidents_table_on_the_admin_engine() -> None:
    incidents = wiring.build_admin_incidents(Settings(storage_backend="real"), now=lambda: NOW)
    page = await incidents.page(status=None, cursor=None, limit=5)
    assert page.items == (row(1),) and FakeIncidents.built == ["admin"]


def test_the_real_backend_shares_the_settings_stores_engine() -> None:
    shared: Any = object()
    store = SqlAlchemySystemSettings(shared)
    wiring.build_admin_incidents(Settings(storage_backend="real"), system_settings=store)
    assert FakeIncidents.built == [shared]  # not a second engine
