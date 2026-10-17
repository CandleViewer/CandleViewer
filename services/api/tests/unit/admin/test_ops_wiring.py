"""Composition-root wiring of the incident list (E42-T05): nothing reads the `incidents` table
until the incident materialiser sets `INCIDENTS_MATERIALISED`; with it set, what each backend
serves."""

from __future__ import annotations

from typing import Any, ClassVar, Literal

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


@pytest.fixture
def materialised(monkeypatch: pytest.MonkeyPatch) -> None:
    """What the incident materialiser's PR sets: something now writes the `incidents` table."""
    monkeypatch.setattr(wiring, "INCIDENTS_MATERIALISED", True)


@pytest.mark.parametrize("backend", ["fake", "real"])
async def test_the_list_is_501_on_every_backend_until_the_materialiser_ships(
    backend: Literal["fake", "real"],
) -> None:
    # An empty page would read as "no incidents" while `system_events` holds errors.
    incidents = wiring.build_admin_incidents(Settings(storage_backend=backend))
    with pytest.raises(OpsNotWired):
        await incidents.page(status=None, cursor=None, limit=1)
    assert FakeIncidents.built == []  # no reader and no engine were even built


@pytest.mark.usefixtures("materialised")
async def test_the_fake_backend_has_no_incident_store_so_the_list_is_never_made_up() -> None:
    incidents = wiring.build_admin_incidents(Settings(storage_backend="fake"))
    with pytest.raises(OpsNotWired):
        await incidents.page(status=None, cursor=None, limit=1)


@pytest.mark.usefixtures("materialised")
async def test_the_real_backend_serves_the_incidents_table_on_the_admin_engine() -> None:
    incidents = wiring.build_admin_incidents(Settings(storage_backend="real"), now=lambda: NOW)
    page = await incidents.page(status=None, cursor=None, limit=5)
    assert page.items == (row(1),) and FakeIncidents.built == ["admin"]


@pytest.mark.usefixtures("materialised")
def test_the_real_backend_shares_the_settings_stores_engine() -> None:
    shared: Any = object()
    store = SqlAlchemySystemSettings(shared)
    wiring.build_admin_incidents(Settings(storage_backend="real"), system_settings=store)
    assert FakeIncidents.built == [shared]  # not a second engine
