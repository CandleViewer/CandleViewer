"""Integration: `/settings/hotkeys*` through its router over the Postgres store, on real Postgres 16
(E10-T05, #5211). The store contract runs on Postgres in test_hotkey_profiles_store_pg.py; this
module drives the routes themselves: a create, a replace guarded by `If-Match`, the activation
swap (one active profile, `ux_hk_active` never tripped), a delete, and a write whose record is
refused, which changes nothing. `testcontainers`: CI, or locally when the host allows.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from testcontainers.postgres import PostgresContainer

from candleviewer.api.hotkey_profiles import make_hotkey_profiles_router
from candleviewer.audit.access import AuditPrincipal
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.storage.repositories.hotkey_profiles_sqlalchemy import (
    SqlAlchemyHotkeyProfileStore,
)
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.hotkey_profiles._hotkey_env import SCALPING, Audit

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_APP = "hotkey-profiles-api-it"
_WRITE = frozenset({"settings:read", "settings:write"})


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        sync = dsn.replace("postgresql+asyncpg", "postgresql+psycopg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=_ROOT, check=True,
            env={**os.environ, "CV_PG_DSN": sync}, timeout=120,
        )  # fmt: skip
        yield dsn


def _sync(dsn: str) -> psycopg.Connection[tuple[Any, ...]]:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _user(dsn: str) -> uuid.UUID:
    uid = uuid.uuid4()
    with _sync(dsn) as c:
        c.execute(
            "INSERT INTO users (id, email, username, password_hash) "
            "VALUES (%s, %s, %s, '$argon2id$x')",
            (uid, f"{str(uid)[:8]}@x.io", f"u{str(uid)[:8]}"),
        )
    return uid


def _rows(dsn: str, owner: uuid.UUID) -> list[tuple[Any, ...]]:
    """The owner's rows as Postgres holds them: (name, is_active, version, bindings)."""
    with _sync(dsn) as c:
        return c.execute(
            "SELECT name, is_active, version, bindings FROM hotkey_profiles "
            "WHERE owner_user_id = %s ORDER BY created_at, id",
            (owner,),
        ).fetchall()


class _Client:
    """The router over the Postgres store, as one owner's session (async: one event loop)."""

    def __init__(self, store: SqlAlchemyHotkeyProfileStore, owner: uuid.UUID) -> None:
        self.audit, self.owner = Audit(), owner

        class _Resolver:
            async def resolve(self, _request: Request) -> AuditPrincipal:
                return AuditPrincipal(owner, "u", _WRITE, ip="10.0.0.9")

        app = FastAPI()
        app.include_router(make_hotkey_profiles_router(lambda: store, _Resolver(), self.audit))
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                      base_url="http://testserver")  # fmt: skip


@pytest_asyncio.fixture
async def store(pg_dsn: str) -> AsyncIterator[SqlAlchemyHotkeyProfileStore]:
    relational = SqlAlchemyRelationalRepository(pg_dsn, _APP)
    try:
        yield SqlAlchemyHotkeyProfileStore(relational)
    finally:
        await relational.dispose()


@pytest_asyncio.fixture
async def client(pg_dsn: str, store: SqlAlchemyHotkeyProfileStore) -> AsyncIterator[_Client]:
    made = _Client(store, await asyncio.to_thread(_user, pg_dsn))
    try:
        yield made
    finally:
        await made.http.aclose()


async def test_create_and_replace_round_trip_on_postgres(pg_dsn: str, client: _Client) -> None:
    owner = client.owner
    made = await client.http.post("/settings/hotkeys", json=SCALPING)
    assert made.status_code == 201, made.text
    body = made.json()
    assert made.headers["ETag"] == f'W/"{body["id"]}:1"'
    tag = {"If-Match": made.headers["ETag"]}
    renamed = await client.http.put(f"/settings/hotkeys/{body['id']}",
                                    json=SCALPING | {"name": "Swing"}, headers=tag)  # fmt: skip
    assert (renamed.status_code, renamed.json()["version"]) == (200, 2)
    stale = await client.http.put(f"/settings/hotkeys/{body['id']}",
                                  json=SCALPING | {"name": "Stale"}, headers=tag)  # fmt: skip
    assert (stale.status_code, stale.headers["ETag"]) == (412, f'W/"{body["id"]}:2"')
    rows = await asyncio.to_thread(_rows, pg_dsn, owner)
    assert rows == [("Swing", False, 2, {"chart.footprint_toggle": "Ctrl+Alt+F"})]
    assert client.audit.actions() == ["hotkey_profile.created", "hotkey_profile.updated"]
    listed = (await client.http.get("/settings/hotkeys")).json()["items"]
    assert listed == [renamed.json()]


async def test_the_activation_swap_leaves_one_active_profile_on_postgres(
    pg_dsn: str, client: _Client
) -> None:
    owner = client.owner
    one = (await client.http.post("/settings/hotkeys", json=SCALPING)).json()
    two = (await client.http.post("/settings/hotkeys", json=SCALPING | {"name": "Two"})).json()
    for profile in (one, two, two):  # the last one changes nothing
        r = await client.http.post(f"/settings/hotkeys/{profile['id']}/activate")
        assert (r.status_code, r.json()["is_active"], r.json()["version"]) == (200, True, 1)
    rows = await asyncio.to_thread(_rows, pg_dsn, owner)
    assert [(name, active, version) for name, active, version, _ in rows] == [
        ("Scalping", False, 1), ("Two", True, 1)]  # fmt: skip
    activated = [c for c in client.audit.calls if c["action"] == "hotkey_profile.activated"]
    assert [c["before_state"]["previous_active_id"] for c in activated] == [None, one["id"]]


async def test_delete_refuses_the_active_profile_and_removes_another_on_postgres(
    pg_dsn: str, client: _Client
) -> None:
    owner = client.owner
    one = (await client.http.post("/settings/hotkeys", json=SCALPING)).json()
    two = (await client.http.post("/settings/hotkeys", json=SCALPING | {"name": "Two"})).json()
    await client.http.post(f"/settings/hotkeys/{one['id']}/activate")
    in_use = await client.http.delete(f"/settings/hotkeys/{one['id']}")
    assert (in_use.status_code, in_use.json()["errors"][0]["rule"]) == (409, "profile_active")
    assert (await client.http.delete(f"/settings/hotkeys/{two['id']}")).status_code == 204
    assert (await client.http.delete(f"/settings/hotkeys/{two['id']}")).status_code == 404
    rows = await asyncio.to_thread(_rows, pg_dsn, owner)
    assert [(name, active) for name, active, _, _ in rows] == [("Scalping", True)]
    (deleted,) = [c for c in client.audit.calls if c["action"] == "hotkey_profile.deleted"]
    assert deleted["object_id"] == two["id"]


async def test_a_refused_record_rolls_every_write_back_on_postgres(
    pg_dsn: str, client: _Client
) -> None:
    """The record is written in the write's transaction before its commit (C-2.9): refused, it
    is `503 audit_unavailable` and Postgres holds what it held."""
    owner = client.owner
    one = (await client.http.post("/settings/hotkeys", json=SCALPING)).json()
    two = (await client.http.post("/settings/hotkeys", json=SCALPING | {"name": "Two"})).json()
    await client.http.post(f"/settings/hotkeys/{one['id']}/activate")
    before = await asyncio.to_thread(_rows, pg_dsn, owner)
    client.audit.fail = AuditUnavailable("wal full")
    answers = [
        await client.http.post("/settings/hotkeys", json=SCALPING | {"name": "New"}),
        await client.http.put(f"/settings/hotkeys/{one['id']}", json=SCALPING | {"name": "New"}),
        await client.http.post(f"/settings/hotkeys/{two['id']}/activate"),
        await client.http.delete(f"/settings/hotkeys/{two['id']}"),
    ]
    assert {(r.status_code, r.json()["code"]) for r in answers} == {(503, "audit_unavailable")}
    assert await asyncio.to_thread(_rows, pg_dsn, owner) == before
