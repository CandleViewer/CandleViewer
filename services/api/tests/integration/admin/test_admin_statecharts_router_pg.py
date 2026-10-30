"""Integration (E42-T07): the statechart inspector's routes over a real `order` machine row on
Postgres 16, its scope bound from the `machines.{entity}.state` registry as the app binds it.

The row is the degraded order of E42-Q01 (`seed_latched_machine`, sealed with a test key), its
timeline two `machine_events` rows written through the composition root's adapter. The Managers'
grants are `user_account_access` rows read through the app's `build_admin_grants`. The Owner and a
Manager granted the order's account list it and read its detail; a Manager granted another account
neither lists it nor reads it, and its `404` is the same answer a missing machine gets; once the
registry holds no entry for it, the Owner sees it no more (fail closed). Once its stored snapshot
no longer matches its seal, the reads leave it out and write exactly one critical `statechart`
`system_events` row through the app's writer, which `listIncidents` shows (#1025, migration 0057).
Needs Docker (testcontainers); CI `integration` runs it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI, Request

from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.admin.inspector import SEAL_EVENT_KIND, SEAL_FAILED, StatechartInspector
from candleviewer.admin.ops.incidents import AdminIncidentsService
from candleviewer.admin.overview.fanout import SliceFanOut
from candleviewer.admin.wiring import system_event_redactor
from candleviewer.admin_wiring import RegistryScopedStore, build_admin_grants
from candleviewer.api.admin_statecharts import machine_key, make_statechart_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.health_wiring import PgSystemEventWriter
from candleviewer.settings import Settings
from candleviewer.statechart.plugins.audit import GENESIS_HASH, MachineEventRow, row_digest
from candleviewer.statechart.registry import Registry
from candleviewer.statechart_wiring import EventsAdapter, SnapshotAdapter
from candleviewer.storage.repositories.incidents_sqlalchemy import SqlAlchemyIncidents
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from candleviewer.storage.repositories.statechart_sqlalchemy import (
    SqlAlchemyEventStore,
    SqlAlchemySnapshotStore,
)
from candleviewer.storage.repositories.system_settings_sqlalchemy import SqlAlchemySystemSettings
from candleviewer.ws.machines import MachineEntity, MachineStateRegistry
from candleviewer.ws.topics import EntityScope
from tests.fixtures.admin.latched_machine import ENTITY_ID, ENV, KIND, seed_latched_machine
from tests.integration import _refused
from tests.unit.admin._admin_fakes import AuditSpy

pytestmark = pytest.mark.integration

pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16, migrated; its database is named `test`
_NOW = datetime(2026, 10, 29, 20, 0, tzinfo=UTC)
_REGISTRY = Registry()
_ACC_ORDER, _ACC_OTHER = UUID(int=0xA1), UUID(int=0xB2)
_OWNER, _MANAGER, _GRANTED = UUID(int=1), UUID(int=2), UUID(int=3)
_USER = sa.text(
    "INSERT INTO users (id, email, username, password_hash, status) VALUES (CAST(:id AS uuid), "
    ":email, :name, '$argon2id$fixture', 'active') ON CONFLICT DO NOTHING"
)
_ACCOUNT = sa.text(
    "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label, is_enabled) "
    "VALUES (CAST(:id AS uuid), 'bybit', CAST(:env AS exchange_env), 'main', :uid, :label, true) "
    "ON CONFLICT DO NOTHING"
)
_GRANT = sa.text(
    "INSERT INTO user_account_access (user_id, exchange_account_id, can_view, can_trade) "
    "VALUES (CAST(:user AS uuid), CAST(:account AS uuid), true, false) ON CONFLICT DO NOTHING"
)
_KEY = f"order:{ENTITY_ID}"
_MISSING = "order:0a000000-0000-4000-8000-0000000000ff"


class _Keys:
    """`HmacKeys` with one test key, never a real one."""

    def current(self) -> str:
        return "k1"

    def key(self, key_id: str) -> bytes:
        return {"k1": b"\x01" * 32}[key_id]


class _Resolver:
    """By `x-role`: the Owner, the Manager granted another account, or the one granted the
    order's (`granted`); each also holds `admin:read`, and all read orders."""

    async def resolve(self, request: Request) -> AuditPrincipal | None:
        perms = frozenset({"admin:read", "orders:read"})
        role = request.headers.get("x-role")
        if role == "owner":
            return AuditPrincipal(_OWNER, "owner", perms, is_owner=True)
        return AuditPrincipal(_GRANTED if role == "granted" else _MANAGER, "manager", perms)


async def _seed_grants(rel: SqlAlchemyRelationalRepository) -> None:
    """Two Managers, each with a view grant: `_MANAGER` on another account, `_GRANTED` on the
    order's. Idempotent: the module's database is shared by both tests."""
    async with rel.engine.begin() as conn:
        for user in (_MANAGER, _GRANTED):
            name = f"manager-{user.int}"
            await conn.execute(_USER, {"id": str(user), "email": f"{name}@x.invalid", "name": name})
        for account, user in ((_ACC_OTHER, _MANAGER), (_ACC_ORDER, _GRANTED)):
            n = account.int
            await conn.execute(
                _ACCOUNT, {"id": str(account), "env": ENV, "uid": str(n), "label": f"a-{n}"}
            )
            await conn.execute(_GRANT, {"user": str(user), "account": str(account)})


@pytest.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repo = SqlAlchemyRelationalRepository(pg_dsn, "inspector")
    try:
        yield repo
    finally:
        await repo.dispose()


def _events() -> list[MachineEventRow]:
    rows, prev = [], GENESIS_HASH
    for i, (event, to) in enumerate([("SUBMIT", "submitted"), ("TRIGGER", "triggered")]):
        row = MachineEventRow(
            machine_kind=KIND, entity_id=ENTITY_ID, env=ENV, event_type=event,
            payload={"note": "never served"}, from_states=["order.lifecycle"],
            to_states=[f"order.lifecycle.{to}"], actions_run=[], fault=None,
            occurred_at=_NOW.replace(second=i).isoformat(), phase="commit", prev_hash=prev,
        )  # fmt: skip
        rows.append(replace(row, row_hash=row_digest(row)))
        prev = rows[-1].row_hash
    return rows


def _published(machines: MachineStateRegistry, entity: MachineEntity) -> None:
    payload = {
        "machine_kind": KIND, "state": "triggered", "tags": [], "degraded": True,
        "machine_hash": _REGISTRY.hash(KIND), "environment": ENV, "updated_at_ms": 1,
    }  # fmt: skip
    assert machines.publish(entity, payload)


async def _client(
    rel: SqlAlchemyRelationalRepository, *, system_events: PgSystemEventWriter | None = None
) -> tuple[httpx.AsyncClient, Any]:
    await seed_latched_machine(rel, _Keys(), now=_NOW)
    await _seed_grants(rel)
    grants = build_admin_grants(
        Settings(storage_backend="real"), system_settings=SqlAlchemySystemSettings(rel)
    )
    assert grants is not None
    events = EventsAdapter(SqlAlchemyEventStore(rel))
    await events.insert_batch(_events())
    machines = MachineStateRegistry()
    entity = MachineEntity("order", ENTITY_ID, EntityScope(frozenset({_ACC_ORDER})))
    _published(machines, entity)
    store = RegistryScopedStore(
        SnapshotAdapter(SqlAlchemySnapshotStore(rel)), machines.scope, env=ENV
    )
    fan = SliceFanOut(budget_s=60, ttl_s=0.0, now=lambda: _NOW)  # no 300 ms timer on a busy host
    lock = {KIND: _REGISTRY.hash(KIND)}
    inspector = StatechartInspector(
        fan, machine_key, lock, store=store, keys=_Keys(), registry=_REGISTRY, events=events,
        system_events=system_events,
    )  # fmt: skip
    app = FastAPI()
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    app.include_router(
        make_statechart_router(inspector, resolver=_Resolver(), audit=AuditSpy(), grants=grants)
    )
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return client, (machines, entity, inspector)


async def _detail(client: httpx.AsyncClient, key: str, role: str) -> httpx.Response:
    params = {"environment": ENV}
    return await client.get(f"/admin/statecharts/{key}", params=params, headers={"x-role": role})


async def _listed(client: httpx.AsyncClient, role: str) -> list[str]:
    body = (await client.get("/admin/statecharts", headers={"x-role": role})).json()
    return [item["machine_key"] for item in body["items"]]


async def test_the_owner_sees_the_order_and_a_foreign_manager_gets_the_missing_answer(
    rel: SqlAlchemyRelationalRepository,
) -> None:
    client, _ = await _client(rel)
    async with client:
        assert await _listed(client, "owner") == [_KEY]
        detail = await _detail(client, _KEY, "owner")
        body = detail.json()
        assert detail.status_code == 200 and body["machine"]["degraded"] is True
        assert body["machine"]["state"] == "triggered" and body["config"]["id"] == KIND
        assert [e["event_type"] for e in body["recent_events"]] == ["TRIGGER", "SUBMIT"]
        assert all("payload" not in e for e in body["recent_events"])
        assert "never served" not in detail.text

        assert await _listed(client, "granted") == [_KEY]  # a Manager granted the order's account
        granted = await _detail(client, _KEY, "granted")
        assert granted.status_code == 200 and granted.json()["machine"] == body["machine"]

        assert await _listed(client, "manager") == []
        foreign = await _detail(client, _KEY, "manager")
        missing = await _detail(client, _MISSING, "manager")
        owner_missing = await _detail(client, _MISSING, "owner")
        assert foreign.status_code == missing.status_code == owner_missing.status_code == 404
        assert foreign.json() == missing.json() == owner_missing.json()
        assert ENTITY_ID not in foreign.text


async def test_without_its_registry_entry_the_order_is_shown_to_no_role(
    rel: SqlAlchemyRelationalRepository,
) -> None:
    client, (machines, entity, _) = await _client(rel)
    async with client:
        assert await _listed(client, "owner") == [_KEY]
        assert machines.remove(entity)  # the machine stopped: its entry, and its scope, are gone
        assert await _listed(client, "owner") == []
        assert (await _detail(client, _KEY, "owner")).status_code == 404


_FORGE = sa.text(
    "UPDATE machine_snapshots SET snapshot = (snapshot::jsonb || '{\"chain_trips\": 0}')::json "
    "WHERE machine_kind = :kind AND entity_id = :entity AND env = :env"
)
_STATECHART_ROWS = sa.text(
    "SELECT kind, severity::text, message, details FROM system_events "
    "WHERE component = 'statechart'"
)


async def test_a_forged_snapshot_is_left_out_and_raises_one_statechart_incident(
    rel: SqlAlchemyRelationalRepository,
) -> None:
    writer = PgSystemEventWriter(rel, redact_details=system_event_redactor())
    client, (_, _, inspector) = await _client(rel, system_events=writer)
    async with rel.engine.begin() as conn:
        await conn.execute(_FORGE, {"kind": KIND, "entity": ENTITY_ID, "env": ENV})
    async with client:
        for _ in range(2):
            listed = (await client.get("/admin/statecharts", headers={"x-role": "owner"})).json()
            assert listed["items"] == [] and listed["snapshots"]["detail"] == SEAL_FAILED
            detail = (await _detail(client, _KEY, "owner")).json()
            assert set(detail) == {"snapshots"} and detail["snapshots"]["detail"] == SEAL_FAILED
    assert inspector.seal_failures is not None
    await inspector.seal_failures.drain()
    async with rel.engine.connect() as conn:
        rows = (await conn.execute(_STATECHART_ROWS)).all()
    assert len(rows) == 1  # four reads of one snapshot version: one row
    kind, severity, message, details = rows[0]
    assert (kind, severity) == (SEAL_EVENT_KIND, "critical")
    assert details == {
        "machine_kind": KIND, "machine": _KEY, "environment": ENV, "updated_at": _NOW.isoformat(),
        "reason": "seal",
    }  # fmt: skip
    assert "chain_trips" not in message and "k1" not in str(details)
    page = await AdminIncidentsService(SqlAlchemyIncidents(rel)).page(
        status=None, cursor=None, limit=50
    )
    (incident,) = [i for i in page.items if i.component == "statechart"]
    assert (incident.severity, incident.status, incident.occurrences) == ("critical", "open", 1)
