"""Integration (#906 slice D3d, E28-T02): the profile routes end to end on a migrated Postgres 16
(testcontainers, `alembic upgrade head`). The RBAC pack's real `create_app()` (`build_world`) with
the real backend's profile wiring over the container (`wire_profiles`: the store, the order path's
effective-profile cache, the accounts, the armed rules and the bus doorbell), a real `AuditWriter`
over `audit_log`, and only the exchange's catalogue the provider world's `Limits`. One loop serves
the requests, the writer and the pools. Needs Docker; CI `integration` runs it.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import psycopg
import pytest
from pydantic import SecretStr

import candleviewer.app as appmod
from candleviewer.api.profile_writes import ProfileWrites
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import AuditWriter
from candleviewer.bus import QueuePolicy, TopicPattern
from candleviewer.bus.models import WILDCARD
from candleviewer.profiles_wiring import wire_profiles
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.contract._profile_writes_world import Limits
from tests.contract.rbac import rbac_harness as rbac
from tests.contract.test_account_profile_write_cells import _heard
from tests.contract.test_account_profile_writes_provider import _RISK
from tests.integration import _refused

pytestmark = pytest.mark.integration

pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16, migrated; its database is named `test`
_RAISED = {**_RISK, "risk_caps": {**_RISK["risk_caps"], "max_open_positions": 5}}  # looser: 3 -> 5


def _sql(dsn: str, query: str, *args: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        cursor = c.execute(query, args)
        return cursor.fetchall() if cursor.description else []


@pytest.fixture(scope="module")
def owner(pg_dsn: str) -> uuid.UUID:
    """The pack's Owner as a live user with the owner role: the store's scope reads both."""
    uid = rbac.user_id_of("owner")
    _sql(
        pg_dsn,
        "INSERT INTO users (id, email, username, password_hash, status) "
        "VALUES (%s, 'owner@example.test', 'rbac-owner', '$argon2id$x', 'active')",
        uid,
    )
    _sql(pg_dsn, "INSERT INTO user_roles (user_id, role_id) SELECT %s, id FROM roles "
                 "WHERE name = 'owner'", uid)  # fmt: skip
    return uid


@pytest.fixture
def account(pg_dsn: str, owner: uuid.UUID) -> uuid.UUID:
    """A demo account, whose `Default` its trigger creates."""
    account = uuid.uuid4()
    _sql(
        pg_dsn,
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', 'demo', 'main', %s, %s)",
        account, str(account.int % 10**15), f"d3d {account.hex[:8]}",
    )  # fmt: skip
    return account


@pytest.fixture
def world(pg_dsn: str, account: uuid.UUID) -> Iterator[rbac.World]:
    with pytest.MonkeyPatch.context() as mp:

        def wired(settings: Any, metrics: Any, bus: Any) -> Any:
            update = {"storage_backend": "real", "pg_dsn": SecretStr(pg_dsn)}
            return wire_profiles(settings.model_copy(update=update), metrics, bus)

        def writes(wiring: Any, _ctx: Any, **_kw: Any) -> ProfileWrites:
            return ProfileWrites(wiring.repository, wiring.accounts, Limits(), wiring.rules, "demo")

        mp.setattr(appmod, "wire_profiles", wired)
        mp.setattr(appmod, "profile_writes", writes)
        yield rbac.build_world(mp)


@contextlib.contextmanager
def _served(world: rbac.World, dsn: str, wal: Path) -> Iterator[SimpleNamespace]:
    """The world's client on one loop, its audit writer real and a probe on the profiles' topics;
    then the writer stopped and every pool disposed."""
    ctx, app = world.app.state.app_context, world.app
    pattern = TopicPattern(env="demo", domain="profiles", symbol=WILDCARD, detail="changed")
    probe = ctx.bus.bus.subscribe("d3d-pg-probe", pattern, QueuePolicy.NEVER_DROP, maxsize=16)
    relational = SqlAlchemyRelationalRepository(dsn, "d3d-audit")
    writer = AuditWriter(SqlAlchemyAuditRepository(relational), str(wal))
    with world.client as client:
        portal = client.portal
        assert portal is not None
        portal.call(writer.start)
        ctx.audit._writer = writer  # the lazy emitters resolve it per call
        verify = AuditQueryService(SqlAlchemyAuditRepository(relational)).verify
        with contextlib.ExitStack() as stack:  # each teardown runs even if one before it raises
            stack.callback(ctx.bus.bus.unsubscribe, probe)
            stack.callback(portal.call, relational.dispose)
            stack.callback(portal.call, app.state.profiles.dispose)
            stack.callback(portal.call, writer.stop, 5.0)
            yield SimpleNamespace(
                client=client, portal=portal, probe=probe, writer=writer, verify=verify
            )


def _tag(*parts: object) -> dict[str, str]:
    return {**rbac.bearer("owner"), "if-match": 'W/"' + ":".join(map(str, parts)) + '"'}


def test_a_profile_lives_through_its_routes_on_postgres_with_its_revisions_and_records(
    world: rbac.World, pg_dsn: str, account: uuid.UUID, tmp_path: Path
) -> None:
    """Create (201, v1), replace with a raised cap (200, v2), move the default onto it (200),
    delete the demoted default (204), delete the new default (409, nothing written): three
    revisions each, five records written ahead in order with an intact chain, the Owner's two
    notices (SR-E28-01), four changes on the bus (24 Sec.9.2), and the order path's cache reading
    the new default right after the move (SR-E28-15)."""
    ((old,),) = _sql(pg_dsn, "SELECT id FROM account_profiles WHERE exchange_account_id = %s "
                             "AND is_default", account)  # fmt: skip
    ((bound,),) = _sql(pg_dsn, "SELECT default_binding_version FROM exchange_accounts "
                               "WHERE id = %s", account)  # fmt: skip
    base, headers = f"/exchange-accounts/{account}", rbac.bearer("owner")
    with _served(world, pg_dsn, tmp_path / "audit.wal") as s:
        effective = world.app.state.profiles.effective.get_effective_profile
        created = s.client.post(f"{base}/profiles", json=_RISK, headers=headers)
        new = uuid.UUID(created.json()["id"])
        sent = [created, s.client.put(f"{base}/profiles/{new}", json=_RAISED, headers=_tag(new, 1))]
        was = s.portal.call(effective, account)  # cached, until a write on the account drops it
        bind, at = {"profile_id": str(new)}, _tag(account, "default", bound)
        sent.append(s.client.put(f"{base}/default-profile", json=bind, headers=at))
        now = s.portal.call(effective, account)  # so the move dropped it
        sent += [
            s.client.delete(f"{base}/profiles/{old}", headers=_tag(old, 2)),
            s.client.delete(f"{base}/profiles/{new}", headers=_tag(new, 3)),
        ]
        heard = s.portal.call(_heard, s.probe)
        s.portal.call(s.writer.flush, 60.0)
        chain = s.portal.call(s.verify)
    assert [r.status_code for r in sent] == [201, 200, 200, 204, 409]
    assert sent[2].json()["version"] == bound + 1 and sent[4].json()["code"] == "conflict"
    assert ((was.profile_id, was.version), (now.profile_id, now.version)) == ((old, 1), (new, 3))
    revisions = _sql(pg_dsn, "SELECT profile_id, version FROM account_profile_revisions "
                             "WHERE profile_id IN (%s, %s) ORDER BY id", old, new)  # fmt: skip
    assert sorted(revisions) == sorted([(p, v) for p in (old, new) for v in (1, 2, 3)])
    records = _sql(
        pg_dsn,
        "SELECT action, object_id, before_state IS NOT NULL, after_state IS NOT NULL, "
        "after_state->>'relaxing' FROM audit_log WHERE object_id IN (%s, %s) ORDER BY id",
        str(old), str(new),
    )  # fmt: skip
    n, o = str(new), str(old)
    assert records == [
        ("profile.created", n, False, True, None), ("profile.updated", n, True, True, "true"),
        ("profile.unbound", o, True, True, None), ("profile.bound", n, True, True, "true"),
        ("profile.deleted", o, True, False, None),
    ]  # fmt: skip
    caps = _sql(pg_dsn, "SELECT before_state->>'max_open_positions', after_state->>'max_open_"
                        "positions' FROM audit_log WHERE object_id = %s AND action = 'profile."
                        "updated'", n)  # fmt: skip
    assert caps == [("3", "5")]  # the replace's record holds the cap before and after it
    assert chain.verified
    notices = _sql(pg_dsn, "SELECT details->>'profile_id', details->>'previous_profile_id', "
                           "correlation_id::text FROM system_events WHERE exchange_account_id = "
                           "%s AND kind = 'profile_relaxed' ORDER BY id", account)  # fmt: skip
    ids = [r.headers["x-correlation-id"] for r in sent[1:3]]
    assert notices == [(n, None, ids[0]), (n, o, ids[1])]
    assert heard == [
        (account, "created", ((new, 1),), None), (account, "updated", ((new, 2),), None),
        (account, "default_moved", ((old, 2), (new, 3)), bound + 1),
        (account, "deleted", ((old, 3),), None),
    ]  # fmt: skip


async def _two_replaces(app: Any, path: str, bodies: list[Any], headers: Any) -> list[Any]:
    """Both at once on the app's own loop, as a burst would."""
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
    async with httpx.AsyncClient(transport=transport, base_url=rbac.WS_ORIGIN) as client:
        sends = (client.put(path, json=body, headers=headers) for body in bodies)
        return list(await asyncio.gather(*sends))


def test_two_replaces_at_one_etag_through_the_routes_admit_exactly_one(
    world: rbac.World,
    pg_dsn: str,
    account: uuid.UUID,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gherkin 5, P7: two replaces of one profile at its one `ETag`, each past the router's read
    of version 1 before either writes; the store's version check admits one (200) and the other is
    412, so the profile holds the winner's body at version 2, with one revision and one
    `profile.updated` past its create."""
    base = f"/exchange-accounts/{account}/profiles"
    bodies = [{**_RISK, "name": name} for name in ("Left", "Right")]
    repository, both = world.app.state.profiles.repository, asyncio.Barrier(2)
    read = repository.read_profile

    async def read_together(*args: Any, **kwargs: Any) -> Any:
        stored = await read(*args, **kwargs)
        async with asyncio.timeout(30):  # each replace waits for the other's read, never longer
            await both.wait()
        return stored

    with _served(world, pg_dsn, tmp_path / "audit.wal") as s:
        new = uuid.UUID(s.client.post(base, json=_RISK, headers=rbac.bearer("owner")).json()["id"])
        headers = {"origin": rbac.WS_ORIGIN, **_tag(new, 1)}
        monkeypatch.setattr(repository, "read_profile", read_together)
        raced = s.portal.call(_two_replaces, world.app, f"{base}/{new}", bodies, headers)
        s.portal.call(s.writer.flush, 60.0)
    assert sorted(r.status_code for r in raced) == [200, 412]
    (won,) = [body["name"] for body, r in zip(bodies, raced, strict=True) if r.status_code == 200]
    assert _sql(pg_dsn, "SELECT name, version FROM account_profiles WHERE id = %s", new) == [
        (won, 2)
    ]
    versions = "SELECT version FROM account_profile_revisions WHERE profile_id = %s ORDER BY id"
    assert _sql(pg_dsn, versions, new) == [(1,), (2,)]
    updated = "SELECT count(*) FROM audit_log WHERE action = 'profile.updated' AND object_id = %s"
    assert _sql(pg_dsn, updated, str(new)) == [(1,)]
