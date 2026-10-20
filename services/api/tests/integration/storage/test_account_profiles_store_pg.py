"""Integration: `SqlAlchemyAccountProfileStore` and `ProfilesRepository` on real Postgres 16
(E28-T01 #905).

The database is set up like production (`pg_bootstrap.sql`'s roles, the migrations as `cv_owner`)
and the store runs as `cv_app`. What only a database proves: Decimal through asyncpg and the
`tp_ladder` JSON numbers with no float; every write bumping `version` once and leaving its
revision; the scope predicates (a live owner, a live `can_view` grant that is not frozen, a live
account); the stale-version, default-move and default-delete refusals; the named constraints the
store reports; and the order path's system read. The DDL itself is
`test_account_profiles_migration.py`'s.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from candleviewer.accounts.errors import (
    AccountConflictError,
    AccountNotFoundError,
    AccountRuleError,
    AccountScopeDeniedError,
    AccountVersionConflictError,
)
from candleviewer.accounts.profile_cache import EffectiveProfiles
from candleviewer.accounts.profile_repository import ProfilesRepository
from candleviewer.accounts.profiles import AccountProfile, TakeProfitRung
from candleviewer.storage.repositories.account_profiles import (
    AccountProfileRow,
    AccountProfileStoreRuleError,
    LadderRung,
)
from candleviewer.storage.repositories.account_profiles_sqlalchemy import (
    SqlAlchemyAccountProfileStore,
)
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP = _ROOT.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql"
_FIXTURES = _ROOT / "tests" / "fixtures" / "profiles"


def _login(dsn: str, role: str) -> str:
    return re.sub(r"://[^@]+@", f"://{role}:{role}_test_pw@", dsn)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """Superuser DSN of a database set up like production: `pg_bootstrap.sql` first, then the
    migrations as `cv_owner`, so the default privileges and the revision's grants apply."""
    with PostgresContainer("postgres:16-alpine", dbname="candleviewer") as container:
        dsn = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        info = psycopg.conninfo.conninfo_to_dict(dsn.replace("postgresql+asyncpg", "postgresql"))
        psql = shutil.which("psql")
        assert psql is not None, "the CI integration and migrations jobs have postgresql-client"
        bootstrap = subprocess.run(  # noqa: S603 -- resolved absolute path, fixed argv, no shell
            [psql, "-h", str(info["host"]), "-p", str(info["port"]), "-U", str(info["user"]),
             "-d", "candleviewer", "-v", "ON_ERROR_STOP=1", "-v", "owner_pw=cv_owner_test_pw",
             "-v", "app_pw=cv_app_test_pw", "-v", "ro_pw=cv_ro_test_pw", "-f", str(_BOOTSTRAP)],
            check=False, capture_output=True, text=True, timeout=120,
            env={**os.environ, "PGPASSWORD": str(info["password"])},
        )  # fmt: skip
        assert bootstrap.returncode == 0, bootstrap.stderr
        owner = _login(dsn, "cv_owner").replace("postgresql+asyncpg", "postgresql+psycopg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT, env={**os.environ, "CV_PG_DSN": owner}, check=True, timeout=300,
        )  # fmt: skip
        yield dsn


def _sql(dsn: str, query: str, *args: object) -> list[tuple[Any, ...]]:
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
        cursor = c.execute(query, args)
        return cursor.fetchall() if cursor.description else []


def _user(dsn: str, role: str | None = None) -> uuid.UUID:
    uid = uuid.uuid4()
    _sql(
        dsn,
        "INSERT INTO users (id, email, username, password_hash, status) "
        "VALUES (%s, %s, %s, '$argon2id$x', 'active')",
        uid, f"{uid}@example.test", f"u{uid.hex[:12]}",
    )  # fmt: skip
    if role:
        _sql(
            dsn,
            "INSERT INTO user_roles (user_id, role_id) SELECT %s, id FROM roles WHERE name = %s",
            uid,
            role,
        )
    return uid


def _account(dsn: str) -> uuid.UUID:
    account = uuid.uuid4()
    _sql(
        dsn,
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', 'demo', 'main', %s, %s)",
        account, str(account.int % 10**15), f"acct {account.hex[:8]}",
    )  # fmt: skip
    return account


def _grant(dsn: str, user: uuid.UUID, account: uuid.UUID, *, can_view: bool, frozen: bool) -> None:
    _sql(
        dsn,
        "INSERT INTO user_account_access (user_id, exchange_account_id, can_view, frozen, "
        "frozen_at) VALUES (%s, %s, %s, %s, CASE WHEN %s THEN now() END)",
        user, account, can_view, frozen, frozen,
    )  # fmt: skip


def _profile(account: uuid.UUID, **changes: Any) -> AccountProfile:
    data = json.loads((_FIXTURES / "risk_based.json").read_text(encoding="utf-8"))
    data |= {"profile_id": str(uuid.uuid4()), "account_id": str(account), "is_default": False}
    return AccountProfile.model_validate(data | changes)


@pytest_asyncio.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repo = SqlAlchemyRelationalRepository(_login(pg_dsn, "cv_app"), "profiles-it")
    try:
        yield repo
    finally:
        await repo.dispose()


@pytest.fixture
def repo(rel: SqlAlchemyRelationalRepository) -> ProfilesRepository:
    return ProfilesRepository(SqlAlchemyAccountProfileStore(rel), cache=None)


@pytest.fixture
def owner(pg_dsn: str) -> OwnerScope:
    return OwnerScope(_user(pg_dsn, "owner"))


async def test_the_bootstrap_default_lists_first_and_a_created_profile_round_trips(
    repo: ProfilesRepository, owner: OwnerScope, pg_dsn: str
) -> None:
    """Decimal in, Decimal out, and the ladder's numbers exact; the database sets version 1."""
    account = _account(pg_dsn)
    ladder = (
        TakeProfitRung(qty_pct=Decimal("0.123456789"), r=Decimal("1.5")),
        TakeProfitRung(qty_pct=Decimal("0.5"), r=Decimal("3")),
    )
    wanted = _profile(account, name="Scalp", tp_ladder=ladder, version=9)
    created = await repo.create_profile(owner, account, wanted)
    assert created.version == 1 and created.tp_ladder == ladder
    assert created.model_dump(exclude={"version", "updated_at"}) == wanted.model_dump(
        exclude={"version", "updated_at"}
    )
    listed = await repo.list_profiles(owner, account)
    assert [p.name for p in listed] == ["Default", "Scalp"] and listed[0].is_default
    raw = _sql(pg_dsn, "SELECT tp_ladder::text FROM account_profiles WHERE id = %s",
               created.profile_id)  # fmt: skip
    rungs = json.loads(raw[0][0], parse_float=Decimal)  # JSON numbers, as trg_ap_ladder_sum reads
    assert [(r["pct"], r["r"]) for r in rungs] == [
        (Decimal("12.3456789"), Decimal("1.5")),
        (Decimal("50"), 3),
    ]


async def test_every_write_bumps_the_version_once_and_leaves_its_revision(
    repo: ProfilesRepository, owner: OwnerScope, pg_dsn: str
) -> None:
    account = _account(pg_dsn)
    created = await repo.create_profile(owner, account, _profile(account))
    narrowed = created.model_copy(update={"max_open_positions": 1})
    updated = await repo.update_profile(
        owner, account, created.profile_id, narrowed, expected_version=1
    )
    assert updated.version == 2 and updated.max_open_positions == 1
    at_one = await repo.get_revision(owner, account, created.profile_id, 1)
    assert at_one.max_open_positions == created.max_open_positions and at_one.version == 1
    deleted = await repo.delete_profile(owner, account, created.profile_id, expected_version=2)
    assert deleted.version == 3
    with pytest.raises(AccountNotFoundError):
        await repo.get_profile(owner, account, created.profile_id)
    assert (await repo.get_revision(owner, account, created.profile_id, 2)).max_open_positions == 1
    rows = _sql(
        pg_dsn,
        "SELECT version, changed_by FROM account_profile_revisions WHERE profile_id = %s "
        "ORDER BY version",
        created.profile_id,
    )
    assert rows == [(1, owner.user_id), (2, owner.user_id), (3, owner.user_id)]


async def test_a_stale_if_match_is_refused_and_writes_nothing(
    repo: ProfilesRepository, owner: OwnerScope, pg_dsn: str
) -> None:
    account = _account(pg_dsn)
    created = await repo.create_profile(owner, account, _profile(account))
    ids = (account, created.profile_id)
    await repo.update_profile(owner, *ids, created.model_copy(update={"leverage": Decimal("2")}),
                              expected_version=1)  # fmt: skip
    with pytest.raises(AccountVersionConflictError):
        await repo.update_profile(owner, *ids, created, expected_version=1)
    assert (await repo.get_profile(owner, account, created.profile_id)).version == 2


async def test_the_default_moves_only_by_set_default_and_is_never_deleted(
    repo: ProfilesRepository, owner: OwnerScope, pg_dsn: str
) -> None:
    """D7: the bound profile is the account's ceiling; it moves as one change, never by an edit,
    and the account is never left without one."""
    account = _account(pg_dsn)
    bootstrap = (await repo.list_profiles(owner, account))[0]
    alternate = await repo.create_profile(owner, account, _profile(account))
    with pytest.raises(AccountRuleError) as moved_by_edit:
        await repo.update_profile(owner, account, alternate.profile_id,
                                  alternate.model_copy(update={"is_default": True}),
                                  expected_version=1)  # fmt: skip
    assert moved_by_edit.value.rule == "default_moves_alone"
    with pytest.raises(AccountConflictError) as delete_default:
        await repo.delete_profile(owner, account, bootstrap.profile_id, expected_version=None)
    assert delete_default.value.constraint == "default_profile"
    move = await repo.set_default_profile(owner, account, alternate.profile_id, expected_version=1)
    assert move.profile.is_default and move.profile.version == 2
    assert move.previous is not None and move.previous.profile_id == bootstrap.profile_id
    assert not move.previous.is_default and move.previous.version == 2
    again = await repo.set_default_profile(owner, account, alternate.profile_id, expected_version=2)
    assert again.previous is None and again.profile.version == 2
    assert (
        await repo.delete_profile(owner, account, bootstrap.profile_id, expected_version=2)
    ).version == 3


async def test_two_concurrent_default_moves_serialise_and_leave_one_default(
    repo: ProfilesRepository, owner: OwnerScope, pg_dsn: str
) -> None:
    """D7 under concurrency: the per-account advisory lock orders the two moves, so neither meets
    `ux_ap_default` and exactly one default remains."""
    account = _account(pg_dsn)
    a = await repo.create_profile(owner, account, _profile(account, name="A"))
    b = await repo.create_profile(owner, account, _profile(account, name="B"))
    moves = await asyncio.gather(
        repo.set_default_profile(owner, account, a.profile_id, expected_version=None),
        repo.set_default_profile(owner, account, b.profile_id, expected_version=None),
    )
    assert all(move.profile.is_default for move in moves)
    defaults = [p for p in await repo.list_profiles(owner, account) if p.is_default]
    assert len(defaults) == 1 and defaults[0].profile_id in {a.profile_id, b.profile_id}


async def test_two_concurrent_updates_at_one_version_admit_exactly_one(
    repo: ProfilesRepository, owner: OwnerScope, pg_dsn: str
) -> None:
    """The If-Match compare-and-set holds when two writes race: the second sees version 2."""
    account = _account(pg_dsn)
    created = await repo.create_profile(owner, account, _profile(account))
    ids = (account, created.profile_id)
    results = await asyncio.gather(
        *(
            repo.update_profile(owner, *ids, created.model_copy(update={"max_open_positions": n}),
                                expected_version=1)
            for n in (1, 2)
        ),
        return_exceptions=True,
    )  # fmt: skip
    assert sorted(type(r).__name__ for r in results) == [
        "AccountProfile",
        "AccountVersionConflictError",
    ]
    assert (await repo.get_profile(owner, *ids)).version == 2


async def test_the_write_ahead_hook_runs_in_the_write_and_a_failure_leaves_no_trace(
    repo: ProfilesRepository, owner: OwnerScope, pg_dsn: str
) -> None:
    """C-2.9: the hook sees the row before and after, inside the write's transaction; when it
    fails, the profile, its version and its history are exactly as they were."""
    account = _account(pg_dsn)
    created = await repo.create_profile(owner, account, _profile(account))
    ids = (account, created.profile_id)
    seen: list[tuple[int | None, int]] = []

    async def records(before: AccountProfileRow | None, after: AccountProfileRow) -> None:
        seen.append((None if before is None else before.version, after.version))

    narrowed = created.model_copy(update={"max_open_positions": 1})
    await repo.update_profile(owner, *ids, narrowed, expected_version=1, write_ahead=records)
    assert seen == [(1, 2)]
    state = "SELECT version, max_open_positions FROM account_profiles WHERE id = %s"
    history = "SELECT count(*) FROM account_profile_revisions WHERE profile_id = %s"
    before = (_sql(pg_dsn, state, created.profile_id), _sql(pg_dsn, history, created.profile_id))

    async def refuses(before: AccountProfileRow | None, after: AccountProfileRow) -> None:
        raise RuntimeError("audit store down")

    with pytest.raises(RuntimeError):
        await repo.update_profile(owner, *ids, created.model_copy(update={"max_open_positions": 2}),
                                  expected_version=2, write_ahead=refuses)  # fmt: skip
    after = (_sql(pg_dsn, state, created.profile_id), _sql(pg_dsn, history, created.profile_id))
    assert after == before


async def test_a_soft_deleted_profile_is_gone_from_every_read_and_write(
    repo: ProfilesRepository, owner: OwnerScope, pg_dsn: str
) -> None:
    """#905: soft delete is honoured on every path; a move to a deleted profile never unsets
    the live default. The default leads the list even when another name sorts first."""
    account = _account(pg_dsn)
    await repo.create_profile(owner, account, _profile(account, name="Alpha"))
    gone = await repo.create_profile(owner, account, _profile(account, name="Gone"))
    await repo.delete_profile(owner, account, gone.profile_id, expected_version=1)
    listed = await repo.list_profiles(owner, account)
    assert [p.name for p in listed] == ["Default", "Alpha"]
    ids = (account, gone.profile_id)
    for write in (
        repo.get_profile(owner, *ids),
        repo.update_profile(owner, *ids, gone, expected_version=None),
        repo.set_default_profile(owner, *ids, expected_version=None),
        repo.delete_profile(owner, *ids, expected_version=None),
    ):
        with pytest.raises(AccountNotFoundError):
            await write
    assert [p.name for p in await repo.list_profiles(owner, account) if p.is_default] == ["Default"]


async def test_the_database_names_each_refusal(
    repo: ProfilesRepository, owner: OwnerScope, pg_dsn: str
) -> None:
    account = _account(pg_dsn)
    with pytest.raises(AccountConflictError) as name:
        await repo.create_profile(owner, account, _profile(account, name="DEFAULT"))
    assert name.value.constraint == "ux_ap_name"
    with pytest.raises(AccountConflictError) as second_default:
        await repo.create_profile(owner, account, _profile(account, is_default=True))
    assert second_default.value.constraint == "ux_ap_default"


async def test_an_owner_scope_held_by_a_non_owner_is_denied(
    repo: ProfilesRepository, pg_dsn: str
) -> None:
    impostor = OwnerScope(_user(pg_dsn, "manager"))
    account = _account(pg_dsn)
    with pytest.raises(AccountScopeDeniedError):
        await repo.list_profiles(impostor, account)
    with pytest.raises(AccountScopeDeniedError):
        await repo.create_profile(impostor, account, _profile(account))


async def test_a_grant_reads_only_live_viewable_unfrozen_accounts(
    repo: ProfilesRepository, pg_dsn: str
) -> None:
    manager = _user(pg_dsn, "manager")
    granted, hidden, frozen, other = (_account(pg_dsn) for _ in range(4))
    _grant(pg_dsn, manager, granted, can_view=True, frozen=False)
    _grant(pg_dsn, manager, hidden, can_view=False, frozen=False)
    _grant(pg_dsn, manager, frozen, can_view=True, frozen=True)
    scope = GrantScope(manager, frozenset({granted, hidden, frozen}))
    assert [p.name for p in await repo.list_profiles(scope, granted)] == ["Default"]
    for account in (hidden, frozen, other):
        assert await repo.list_profiles(scope, account) == ()
    snapshot_only = GrantScope(manager, frozenset({other}))
    assert await repo.list_profiles(snapshot_only, other) == ()


async def test_a_profile_is_reachable_only_under_its_own_account(
    repo: ProfilesRepository, owner: OwnerScope, pg_dsn: str
) -> None:
    """IDOR (C-12.4, SR-051, SEC-1B-03): account B's profile, addressed under account A's path,
    is missing to every read and write, for the owner and for a grant that holds both."""
    a, b = _account(pg_dsn), _account(pg_dsn)
    theirs = await repo.create_profile(owner, b, _profile(b))
    pid = theirs.profile_id
    as_a = theirs.model_copy(update={"account_id": a, "max_open_positions": 1})
    misses = [
        repo.get_profile(owner, a, pid),
        repo.update_profile(owner, a, pid, as_a, expected_version=None),
        repo.set_default_profile(owner, a, pid, expected_version=None),
        repo.delete_profile(owner, a, pid, expected_version=None),
        repo.get_revision(owner, a, pid, 1),
    ]
    manager = _user(pg_dsn, "manager")
    for account in (a, b):
        _grant(pg_dsn, manager, account, can_view=True, frozen=False)
    both = GrantScope(manager, frozenset({a, b}))
    misses += [repo.get_profile(both, a, pid), repo.get_revision(both, a, pid, 1)]
    for miss in misses:
        with pytest.raises(AccountNotFoundError):
            await miss
    assert pid not in {p.profile_id for p in await repo.list_profiles(both, a)}
    unchanged = await repo.get_profile(owner, b, pid)
    assert unchanged.version == 1 and unchanged.max_open_positions == theirs.max_open_positions


async def test_a_soft_deleted_account_hides_its_profiles_from_every_read(
    repo: ProfilesRepository, owner: OwnerScope, pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    account = _account(pg_dsn)
    default = (await repo.list_profiles(owner, account))[0]
    _sql(pg_dsn, "UPDATE exchange_accounts SET deleted_at = now() WHERE id = %s", account)
    assert await repo.list_profiles(owner, account) == ()
    with pytest.raises(AccountNotFoundError):
        await repo.get_revision(owner, account, default.profile_id, 1)
    with pytest.raises(AccountNotFoundError):
        await repo.create_profile(owner, account, _profile(account))
    cache = EffectiveProfiles(SqlAlchemyAccountProfileStore(rel))
    with pytest.raises(AccountNotFoundError):
        await cache.get_effective_profile(account)


async def test_the_order_path_reads_the_default_then_a_narrowed_version(
    owner: OwnerScope, pg_dsn: str, rel: SqlAlchemyRelationalRepository
) -> None:
    """SR-E28-15: the write invalidates before it returns, so the next read sees the new caps."""
    store = SqlAlchemyAccountProfileStore(rel)
    cache = EffectiveProfiles(store)
    repo = ProfilesRepository(store, cache=cache)
    account = _account(pg_dsn)
    default = await cache.get_effective_profile(account)
    assert default.name == "Default" and not default.trading_enabled
    caps = {
        "trading_enabled": True, "max_position_notional": Decimal("1000"),
        "max_daily_loss": Decimal("100"), "max_open_positions": 1, "max_concurrent_orders": 2,
        "max_leverage_cap": Decimal("2"), "all_symbols": True,
    }  # fmt: skip
    await repo.update_profile(
        owner, account, default.profile_id, default.model_copy(update=caps), expected_version=1
    )
    read = await cache.get_effective_profile(account)
    assert read.version == 2 and read.trading_enabled and read.max_open_positions == 1
    assert (await cache.get_effective_profile(account, default.profile_id)).version == 2


async def test_a_ladder_beyond_the_whole_leg_is_refused_by_the_trigger(
    rel: SqlAlchemyRelationalRepository, owner: OwnerScope, pg_dsn: str
) -> None:
    """The model refuses it first; the database names its own rule for a writer that bypassed it."""
    store = SqlAlchemyAccountProfileStore(rel)
    account = _account(pg_dsn)
    values = (await store.list_profiles(owner, account))[0].values
    over = (LadderRung(Decimal("60"), Decimal("1")), LadderRung(Decimal("60"), Decimal("2")))
    with pytest.raises(AccountProfileStoreRuleError) as ei:
        await store.create_profile(owner, account, uuid.uuid4(),
                                   dataclasses.replace(values, name="Over", is_default=False,
                                                       tp_ladder=over))  # fmt: skip
    assert ei.value.rule == "trg_ap_ladder_sum"
