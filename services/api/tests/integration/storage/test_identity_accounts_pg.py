"""Integration (#2713, #415): `SqlAlchemyIdentityProvider` on real Postgres 16.

The accounts `GET /me` lists: an owner reaches every live account with `trade`; anyone else
only the live, unfrozen, viewable grants of their own, `trade` where `can_trade`. A soft-deleted
account, a soft-revoked or frozen grant, and another user's grant never appear, and an expired
owner role, or an owner who is disabled, locked or deleted, is no owner. The `account_scope` of
`session_info` applies the same grant predicate to a non-owner (`can_view AND NOT frozen`, C-12.4);
`Me.accounts` also joins the live account, as before. The `/rules` API reads that scope as the
accounts a caller may target, so the last tests drive it end to end. Every test runs alone and
in any order: the `db` fixture keeps one active owner standing, because the owner floor (migration
0001) refuses a commit that leaves none. Not run locally (no docker); exercised by CI `integration`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from candleviewer.api.rules_actor import SessionRulesActorResolver
from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.rules.manager import InMemoryRuleStore, RulesManager
from candleviewer.rules.vocabulary import default_registry
from candleviewer.storage.repositories.identity_sqlalchemy import SqlAlchemyIdentityProvider
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from tests.rules.test_rules_manager import _ir

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_USER = sa.text(
    "INSERT INTO users (id, email, username, password_hash, status) VALUES (CAST(:id AS uuid), "
    ":email, :name, '$argon2id$fixture', 'active')"
)
# The standing owner: fixed id, so seeding it again is a no-op.
_BASELINE_OWNER = "00000000-0000-4000-8000-0000000000b0"
_BASELINE_USER = sa.text(
    "INSERT INTO users (id, email, username, password_hash, status) VALUES (CAST(:id AS uuid), "
    "'baseline-owner@x.invalid', 'baseline-owner', '$argon2id$fixture', 'active') "
    "ON CONFLICT DO NOTHING"
)
_BASELINE_ROLE = sa.text(
    "INSERT INTO user_roles (user_id, role_id) SELECT CAST(:id AS uuid), id FROM roles "
    "WHERE name = 'owner' ON CONFLICT DO NOTHING"
)
_ROLE = sa.text(
    "INSERT INTO user_roles (user_id, role_id, granted_at, expires_at) "
    "SELECT CAST(:id AS uuid), id, now() - interval '2 hours', "
    "CASE WHEN :expired THEN now() - interval '1 hour' END "
    "FROM roles WHERE name = CAST(:role AS role_name)"
)
_ACCOUNT = sa.text(
    "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label, created_at) "
    "VALUES (CAST(:id AS uuid), 'bybit', CAST(:env AS exchange_env), 'main', :uid, :label, "
    "now() - make_interval(mins => :age))"
)
_GRANT = sa.text(
    "INSERT INTO user_account_access (user_id, exchange_account_id, can_view, can_trade, frozen, "
    "frozen_at) VALUES (CAST(:user AS uuid), CAST(:account AS uuid), :view, :trade, :frozen, "
    "CASE WHEN :frozen THEN now() END)"
)
_SOFT_DELETE = sa.text(
    "UPDATE exchange_accounts SET deleted_at = now() WHERE id = CAST(:id AS uuid)"
)
_SET_STATUS = sa.text(
    "UPDATE users SET status = CAST(:status AS user_status) WHERE id = CAST(:id AS uuid)"
)
_SOFT_DELETE_USER = sa.text("UPDATE users SET deleted_at = now() WHERE id = CAST(:id AS uuid)")
_FREEZE = sa.text(
    "UPDATE user_account_access SET frozen = true, frozen_at = now() "
    "WHERE user_id = CAST(:user AS uuid) AND exchange_account_id = CAST(:account AS uuid)"
)
_UNFREEZE = sa.text(
    "UPDATE user_account_access SET frozen = false "
    "WHERE user_id = CAST(:user AS uuid) AND exchange_account_id = CAST(:account AS uuid)"
)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={
                **os.environ,
                "CV_PG_DSN": dsn.replace("postgresql+asyncpg", "postgresql+psycopg"),
            },
            check=True,
        )
        yield dsn


@pytest.fixture
async def db(pg_dsn: str) -> AsyncIterator[tuple[SqlAlchemyIdentityProvider, AsyncEngine]]:
    rel, engine = SqlAlchemyRelationalRepository(pg_dsn), create_async_engine(pg_dsn)
    try:
        await _ensure_owner(engine)
        yield SqlAlchemyIdentityProvider(rel), engine
    finally:
        await rel.dispose()
        await engine.dispose()


async def _exec(engine: AsyncEngine, stmt: sa.TextClause, **params: object) -> None:
    async with engine.begin() as conn:
        await conn.execute(stmt, params)


async def _ensure_owner(engine: AsyncEngine) -> None:
    """Keep one active owner standing (idempotent). The owner floor of migration 0001 raises
    23514 at commit when a role row is written while the database holds no active owner, so
    without this a test passes only after another one left an owner behind (C-13.7)."""
    async with engine.begin() as conn:
        await conn.execute(_BASELINE_USER, {"id": _BASELINE_OWNER})
        await conn.execute(_BASELINE_ROLE, {"id": _BASELINE_OWNER})


async def _user(engine: AsyncEngine, role: str, *, expired: bool = False) -> str:
    uid = str(uuid.uuid4())
    name = f"u-{uid[:12]}"
    await _exec(engine, _USER, id=uid, email=f"{name}@x.invalid", name=name)
    await _exec(engine, _ROLE, id=uid, role=role, expired=expired)
    return uid


async def _account(engine: AsyncEngine, label: str, *, age: int, env: str = "demo") -> str:
    """A live account created `age` minutes ago, so `created_at` fixes the order."""
    aid = str(uuid.uuid4())
    await _exec(
        engine,
        _ACCOUNT,
        id=aid,
        env=env,
        uid=str(uuid.UUID(aid).int % 10**12),
        label=label,
        age=age,
    )
    return aid


async def _grant(
    engine: AsyncEngine,
    user: str,
    account: str,
    *,
    view: bool = True,
    trade: bool = False,
    frozen: bool = False,
) -> None:
    await _exec(engine, _GRANT, user=user, account=account, view=view, trade=trade, frozen=frozen)


def _view(accounts: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(a["label"], a["mode"]) for a in accounts]


async def test_names_reads_a_users_row_whatever_its_status(db: Any) -> None:
    """#3085 (Q12): a view-as target's names, a disabled and soft-deleted user's too; an id with
    no row is a `LookupError`."""
    provider, engine = db
    uid = await _user(engine, "viewer")
    await _exec(engine, _SET_STATUS, id=uid, status="disabled")
    await _exec(engine, _SOFT_DELETE_USER, id=uid)
    assert await provider.names(uid) == (f"u-{uid[:12]}", None)
    with pytest.raises(LookupError):
        await provider.names(str(uuid.uuid4()))


async def test_an_owner_reaches_every_live_account_with_trade(db: Any) -> None:
    provider, engine = db
    owner = await _user(engine, "owner")
    old = await _account(engine, f"o-old-{owner[:6]}", age=30)
    live = await _account(engine, f"o-live-{owner[:6]}", age=20, env="testnet")
    gone = await _account(engine, f"o-gone-{owner[:6]}", age=10)
    await _exec(engine, _SOFT_DELETE, id=gone)
    got = await provider.accounts(owner)
    mine = [a for a in got if a["exchange_account_id"] in {old, live, gone}]
    assert [(a["exchange_account_id"], a["mode"]) for a in mine] == [
        (old, "trade"),
        (live, "trade"),
    ]
    assert {a["environment"] for a in mine} == {"demo", "testnet"}
    assert gone not in {a["exchange_account_id"] for a in got}


async def test_a_manager_reaches_only_live_unfrozen_viewable_grants_with_their_mode(
    db: Any,
) -> None:
    provider, engine = db
    manager, other = await _user(engine, "manager"), await _user(engine, "manager")
    tag = manager[:6]
    trade = await _account(engine, f"m-trade-{tag}", age=50)
    read = await _account(engine, f"m-read-{tag}", age=40)
    frozen = await _account(engine, f"m-frozen-{tag}", age=30)
    revoked = await _account(engine, f"m-revoked-{tag}", age=25)
    deleted = await _account(engine, f"m-deleted-{tag}", age=20)
    theirs = await _account(engine, f"m-theirs-{tag}", age=15)
    await _grant(engine, manager, trade, trade=True)
    await _grant(engine, manager, read)
    await _grant(engine, manager, frozen, trade=True, frozen=True)
    await _grant(engine, manager, revoked, view=False)
    await _grant(engine, manager, deleted, trade=True)
    await _exec(engine, _SOFT_DELETE, id=deleted)
    await _grant(engine, other, theirs, trade=True)
    got = await provider.accounts(manager)
    assert _view(got) == [(f"m-trade-{tag}", "trade"), (f"m-read-{tag}", "read")]
    assert [a["exchange_account_id"] for a in got] == [trade, read]


async def test_a_viewer_with_no_grant_reaches_nothing_and_an_unknown_user_nothing(db: Any) -> None:
    provider, engine = db
    viewer = await _user(engine, "viewer")
    await _account(engine, f"v-unreached-{viewer[:6]}", age=5)
    assert await provider.accounts(viewer) == []
    assert await provider.accounts(str(uuid.uuid4())) == []


async def test_an_expired_owner_role_is_no_owner(db: Any) -> None:
    provider, engine = db
    lapsed = await _user(engine, "owner", expired=True)
    granted = await _account(engine, f"x-granted-{lapsed[:6]}", age=9)
    await _account(engine, f"x-other-{lapsed[:6]}", age=8)
    await _grant(engine, lapsed, granted)
    assert _view(await provider.accounts(lapsed)) == [(f"x-granted-{lapsed[:6]}", "read")]


def _reached(accounts: list[dict[str, Any]]) -> set[str]:
    return {a["exchange_account_id"] for a in accounts}


@pytest.mark.parametrize("status", ["disabled", "locked"])
async def test_an_owner_who_is_not_active_reaches_nothing(db: Any, status: str) -> None:
    provider, engine = db
    owner = await _user(engine, "owner")
    account = await _account(engine, f"n-{status}-{owner[:6]}", age=7)
    assert account in _reached(await provider.accounts(owner))
    await _exec(engine, _SET_STATUS, id=owner, status=status)
    assert await provider.accounts(owner) == []


async def test_a_soft_deleted_owner_reaches_nothing(db: Any) -> None:
    provider, engine = db
    owner = await _user(engine, "owner")
    account = await _account(engine, f"n-deleted-{owner[:6]}", age=6)
    assert account in _reached(await provider.accounts(owner))
    await _exec(engine, _SOFT_DELETE_USER, id=owner)
    assert await provider.accounts(owner) == []


async def _scope(provider: SqlAlchemyIdentityProvider, user: str) -> list[str]:
    return sorted((await provider.session_info(user))["account_scope"])


async def test_the_session_scope_lists_the_view_grants_that_are_not_frozen(db: Any) -> None:
    provider, engine = db
    manager, other = await _user(engine, "manager"), await _user(engine, "manager")
    tag = manager[:6]
    trade = await _account(engine, f"s-trade-{tag}", age=50)
    read = await _account(engine, f"s-read-{tag}", age=40)
    frozen = await _account(engine, f"s-frozen-{tag}", age=30)
    revoked = await _account(engine, f"s-revoked-{tag}", age=25)
    theirs = await _account(engine, f"s-theirs-{tag}", age=15)
    await _grant(engine, manager, trade, trade=True)
    await _grant(engine, manager, read)
    await _grant(engine, manager, frozen, trade=True, frozen=True)
    await _grant(engine, manager, revoked, view=False)
    await _grant(engine, other, theirs, trade=True)
    scope = await _scope(provider, manager)
    assert scope == sorted([trade, read])
    # The same grant predicate as `/me`; `Me.accounts` also joins the live account, as before.
    assert set(scope) == _reached(await provider.accounts(manager))


async def test_a_freeze_takes_a_grant_out_of_the_session_scope_at_the_next_read(db: Any) -> None:
    provider, engine = db
    manager = await _user(engine, "manager")
    account = await _account(engine, f"s-flip-{manager[:6]}", age=12)
    await _grant(engine, manager, account, trade=True)
    assert await _scope(provider, manager) == [account]
    await _exec(engine, _FREEZE, user=manager, account=account)
    assert await _scope(provider, manager) == []
    await _exec(engine, _UNFREEZE, user=manager, account=account)
    assert await _scope(provider, manager) == [account]


class _Sessions:
    """`SessionService.authenticate_access_token` for one user: any token is that user's session."""

    def __init__(self, user: str) -> None:
        self.record = SimpleNamespace(user_id=uuid.UUID(user), id=uuid.uuid4(), view_as=None)

    async def authenticate_access_token(self, token: str, *, touch: bool = True) -> Any:
        return self.record


def _rules() -> tuple[RulesManager, list[tuple[str, dict[str, Any]]]]:
    """A rule manager, and the audit records it writes ahead of each answer (C-2.9)."""
    audits: list[tuple[str, dict[str, Any]]] = []

    async def audit(action: str, payload: dict[str, Any]) -> None:
        audits.append((action, payload))

    async def broadcast(payload: dict[str, Any]) -> None:
        return None

    rules = RulesManager(InMemoryRuleStore(), default_registry(), audit=audit, broadcast=broadcast)
    return rules, audits


def _api(provider: SqlAlchemyIdentityProvider, rules: RulesManager, user: str) -> httpx.AsyncClient:
    """The `/rules` API as `user` calls it: the real session resolver over the real identity read.
    The router's own `ScopeResolver` pre-check is not wired here (`tests/rules/test_scope_crud.py`
    covers it): the refusals below are the manager's, from the accounts the actor is granted."""
    resolver = SessionRulesActorResolver(lambda: _Sessions(user), lambda: None, provider)
    app = FastAPI()
    app.include_router(make_rules_crud_router(lambda: rules, resolver.resolve))
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://rules.invalid",
        headers={"authorization": "Bearer session-token"},
    )


async def _save(api: httpx.AsyncClient, name: str, *accounts: str) -> httpx.Response:
    """`POST /rules`: a BTCUSDT rule in demo that names `accounts`."""
    scope = {"level": "symbol", "symbols": ["BTCUSDT"], "environments": ["demo"]}
    ir = _ir(name=name, scope=scope | {"account_ids": list(accounts)})
    return await api.post("/rules", json={"ir": ir})


async def _mode(api: httpx.AsyncClient, rule: str, mode: str) -> httpx.Response:
    headers = {"Idempotency-Key": uuid.uuid4().hex}
    return await api.put(f"/rules/{rule}/mode", json={"mode": mode}, headers=headers)


async def test_the_rules_api_refuses_a_rule_on_an_account_once_its_grant_is_frozen(db: Any) -> None:
    """The `/rules` checks read the session scope as the accounts the caller may target: the same
    account takes a rule while its grant is live and is refused, and audited, once it is frozen,
    as is an account never granted (both read `account_not_granted`: the actor holds one flat set
    of granted accounts). A session without `rules:write` is refused at the permission gate."""
    provider, engine = db
    manager, viewer = await _user(engine, "manager"), await _user(engine, "viewer")
    account = await _account(engine, f"s-rules-{manager[:6]}", age=11)
    never = await _account(engine, f"s-never-{manager[:6]}", age=10)
    await _grant(engine, manager, account, trade=True)
    await _grant(engine, viewer, account)
    rules, audits = _rules()
    async with _api(provider, rules, manager) as api:
        live = await _save(api, "on-live", account)
        await _exec(engine, _FREEZE, user=manager, account=account)
        frozen = await _save(api, "on-frozen", account)
        ungranted = await _save(api, "on-never-granted", never)
    async with _api(provider, rules, viewer) as api:
        read_only = await _save(api, "by-viewer", account)
    assert live.status_code == 201
    for refused in (frozen, ungranted):
        assert refused.status_code == 403
        assert refused.json()["code"] == "forbidden"
    assert read_only.status_code == 403
    assert read_only.json()["detail"] == "requires rules:write"
    # The refused requests stored nothing (one `rule.created`); each scope refusal is audited
    # ahead of its answer (C-2.9).
    assert [(action, payload.get("reason")) for action, payload in audits] == [
        ("rule.created", None),
        ("rule.scope_refused", "account_not_granted"),
        ("rule.scope_refused", "account_not_granted"),
    ]


async def test_a_frozen_grant_hides_an_armed_rule_from_its_manager_but_not_the_owner(
    db: Any,
) -> None:
    """Ruled 19 Oct (#415): an armed rule naming a live and a frozen account stays armed on the
    live one; until the grant is unfrozen its manager cannot read or disarm it through the API
    (404). The Owner can. The runtime's `manager_frozen` is pinned in tests/rules/test_scope.py."""
    provider, engine = db
    manager, owner = await _user(engine, "manager"), await _user(engine, "owner")
    live = await _account(engine, f"s-both-live-{manager[:6]}", age=9)
    frozen = await _account(engine, f"s-both-frozen-{manager[:6]}", age=8)
    for account in (live, frozen):
        await _grant(engine, manager, account, trade=True)
    rules, _ = _rules()
    async with _api(provider, rules, manager) as api:
        rule = (await _save(api, "on-both", live, frozen)).json()["id"]
        versions = await api.get(f"/rules/{rule}/versions")
        assert (await _mode(api, rule, "simulate")).status_code == 200
        await rules.record_simulation(rule, versions.json()["items"][0]["ir_hash"], 5, 0.0)
        assert (await _mode(api, rule, "armed")).status_code == 200
        await _exec(engine, _FREEZE, user=manager, account=frozen)
        read, disarm = await api.get(f"/rules/{rule}"), await _mode(api, rule, "disabled")
    async with _api(provider, rules, owner) as api:
        seen, stop = await api.get(f"/rules/{rule}"), await _mode(api, rule, "disabled")
    assert (read.status_code, disarm.status_code) == (404, 404)
    assert (seen.status_code, stop.status_code) == (200, 200)
    assert (seen.json()["mode"], stop.json()["mode"]) == ("armed", "disabled")
