"""Integration: `SqlAlchemyTradeGroupStore` on real Postgres 16 (E28-T01 #905).

The database is set up like production (`pg_bootstrap.sql`'s roles, then the migrations as
`cv_owner`) and the store runs as `cv_app`, which also proves its `FOR SHARE` privileges. What
only a database proves: Decimal and the leg snapshot through asyncpg with no float; the replay
anchor under its creator, also when two creates race; the share-locked refusals of a soft-deleted
account or definition and of a profile past the leg's version (SR-E28-15), also when the profile
update races the create; that any refusal leaves no row; `tgl_sl_px` (C-2.6) named through the
store; the failure policy stored as named and never changed; the set-once times and the status
compare-and-set; the partial indexes the C-2.6 reads use; the SR-E28-21 visibility matrix and the
owner predicate inside the scoped statements; and the constraint names the store maps. The DDL
itself is test_trade_groups_migration.py's.

Profiles come from plain SQL: each account's bootstrap default profile (`trg_ea_default_profile`),
at version 1, which a test moves to version 2 with a superuser UPDATE when it needs to. A leg's
snapshot is `AccountProfile.model_dump(mode="json")` of a profile fixture under that account,
profile and version (`_projection`): the projection `leg_values` stores (SR-E28-07).

The race tests poll `pg_stat_activity` for a lock wait and never sleep for a fixed time; each
is bounded by `asyncio.timeout`. The facade (`TradeGroupRepository`, `TradeGroupReader`) is
imported only where a test needs its outcome: `GroupReplay`, `ProfileChangedError` and
`shows_private_fields`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
import pytest_asyncio
import sqlalchemy as sa
from psycopg import sql
from sqlalchemy.engine import Dialect, make_url
from testcontainers.postgres import PostgresContainer

from candleviewer.accounts.profiles import AccountProfile
from candleviewer.db.models import LEG_FAILURE_POLICIES
from candleviewer.domain.primitives import GroupId, UserId
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope
from candleviewer.storage.repositories.exchange_payload import redact_exchange_text
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.trade_groups import (
    ACCOUNT_NOT_LIVE,
    DEFINITION_NOT_LIVE,
    PROFILE_CHANGED,
    TRADE_GROUP_CONFLICTS,
    TRADE_GROUP_RULES,
    GroupAnchor,
    GroupCreated,
    GroupExists,
    GroupPatch,
    JsonObject,
    LegPatch,
    NewTradeGroup,
    NewTradeGroupLeg,
    TradeGroupRecord,
    TradeGroupStoreConflictError,
    TradeGroupStoreRefusedError,
    TradeGroupStoreRuleError,
    TradeGroupStoreScopeDeniedError,
    TradeGroupStoreStaleError,
)
from candleviewer.storage.repositories.trade_groups_sqlalchemy import (
    SqlAlchemyTradeGroupStore,
    open_groups_statement,
    scoped_group_statement,
    scoped_legs_statement,
    unprotected_legs_statement,
)
from tests.integration._refused import assert_no_row_values, server_text

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP = _ROOT.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql"
_FIXTURES = _ROOT / "tests" / "fixtures" / "profiles"
_PROFILE_FIXTURES = ("risk_based.json", "fixed_qty.json", "pct_equity.json", "fixed_notional.json")
_BODY = hashlib.sha256(b'{"symbol":"BTCUSDT","side":"Buy","qty":"0.010"}').hexdigest()
_OTHER_BODY = hashlib.sha256(b'{"symbol":"BTCUSDT","side":"Sell","qty":"0.010"}').hexdigest()
_T0 = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
_POSTGRES: Dialect = make_url("postgresql+psycopg://").get_dialect()()
#: A run of 18+ letters alone, which the message rule replaces (synthetic, SR-145).
_LETTER_RUN = "error sign! origin_string[" + "Qwerty" * 4 + "]"
# P1 columns of a refused group row, planted by name (#2748, C-12.6); money on a digit run.
_NOTE, _PARAM, _STOP = "planted intent note", "planted-algo-param", Decimal("61234.5678")


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


def _conn(dsn: str) -> psycopg.Connection[tuple[Any, ...]]:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def _sql(dsn: str, query: str, *args: object) -> list[tuple[Any, ...]]:
    """One superuser statement, committed."""
    with _conn(dsn) as c:
        cursor = c.execute(query, args)
        return cursor.fetchall() if cursor.description else []


def _one(dsn: str, query: str, *args: object) -> Any:
    rows = _sql(dsn, query, *args)
    assert len(rows) == 1
    return rows[0][0]


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


def _account(dsn: str, env: str = "demo") -> uuid.UUID:
    """An account; `trg_ea_default_profile` gives it its bootstrap profile, version 1."""
    account = uuid.uuid4()
    _sql(
        dsn,
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', %s, 'main', %s, %s)",
        account, env, str(account.int % 10**15), f"acct {account.hex[:8]}",
    )  # fmt: skip
    return account


def _default_profile(dsn: str, account: uuid.UUID) -> uuid.UUID:
    found = _one(
        dsn,
        "SELECT id FROM account_profiles WHERE exchange_account_id = %s AND is_default "
        "AND deleted_at IS NULL",
        account,
    )
    return uuid.UUID(str(found))


def _grant(dsn: str, user: uuid.UUID, account: uuid.UUID) -> None:
    _sql(
        dsn,
        "INSERT INTO user_account_access (user_id, exchange_account_id, can_view, frozen) "
        "VALUES (%s, %s, true, false)",
        user,
        account,
    )


def _definition(dsn: str) -> uuid.UUID:
    definition = uuid.uuid4()
    _sql(
        dsn,
        "INSERT INTO trade_group_definitions (id, name, env) VALUES (%s, %s, 'demo')",
        definition,
        f"def {definition.hex[:8]}",
    )
    return definition


def _profile_model(
    account: uuid.UUID, profile: uuid.UUID, version: int, fixture: str = "risk_based.json"
) -> AccountProfile:
    data = json.loads((_FIXTURES / fixture).read_text(encoding="utf-8"))
    data |= {"profile_id": str(profile), "account_id": str(account), "version": version}
    return AccountProfile.model_validate(data)


def _projection(
    account: uuid.UUID, profile: uuid.UUID, version: int, fixture: str = "risk_based.json"
) -> JsonObject:
    """What a leg stores (SR-E28-07): the profile's `model_dump(mode="json")`."""
    return _profile_model(account, profile, version, fixture).model_dump(mode="json")


def _new_group(creator: uuid.UUID, *, ref: str | None = None, **over: Any) -> NewTradeGroup:
    """A demo Market group; `client_group_ref` is a fresh lower-case UUID text unless given."""
    values: dict[str, Any] = {
        "id": uuid.uuid4(), "client_group_ref": ref or str(uuid.uuid4()),
        "client_body_sha256": _BODY, "created_by": creator, "env": "demo", "symbol": "BTCUSDT",
        "side": "Buy", "status": "submitting", "leg_failure_policy": "best_effort",
        "algo": "none", "algo_params": None, "intent_note": None, "origin": "manual",
        "origin_rule_id": None, "origin_rule_run_id": None, "definition_id": None,
        "requested_qty_mode": "risk_based", "requested_qty_value": None, "entry_type": "Market",
        "entry_price": None, "trigger_price": None, "trigger_by": None,
        "sl_price_hint": Decimal("62000"), "tp_price_hint": None, "is_paper": False,
    }  # fmt: skip
    return NewTradeGroup(**(values | over))


def _new_leg(
    dsn: str,
    account: uuid.UUID,
    *,
    seq: int = 0,
    profile: uuid.UUID | None = None,
    version: int = 1,
    fixture: str = "risk_based.json",
    **over: Any,
) -> NewTradeGroupLeg:
    """A pending leg with a native stop, sized from the account's default profile at version 1
    (its bootstrap revision) unless told otherwise."""
    sized_from = profile or _default_profile(dsn, account)
    values: dict[str, Any] = {
        "id": uuid.uuid4(), "exchange_account_id": account, "account_profile_id": sized_from,
        "profile_version": version,
        "profile_snapshot": _projection(account, sized_from, version, fixture),
        "status": "pending", "sequence_no": seq, "target_qty": Decimal("0.010"),
        "resolved_leverage": Decimal("5"), "resolved_sl_price": Decimal("62000"),
        "resolved_tp_price": None, "risk_usd": None, "rejection_code": None,
        "rejection_message": None,
    }  # fmt: skip
    return NewTradeGroupLeg(**(values | over))


def _groups_with_ref(dsn: str, creator: uuid.UUID, ref: str) -> list[uuid.UUID]:
    rows = _sql(
        dsn,
        "SELECT id FROM trade_groups WHERE created_by = %s AND client_group_ref = %s",
        creator,
        ref,
    )
    return [uuid.UUID(str(row[0])) for row in rows]


def _rows_of(dsn: str, group: NewTradeGroup, legs: list[NewTradeGroupLeg]) -> tuple[int, int]:
    """How many of this group's and these legs' rows exist."""
    groups = _one(dsn, "SELECT count(*) FROM trade_groups WHERE id = %s", group.id)
    stored = _one(
        dsn,
        "SELECT count(*) FROM trade_group_legs WHERE id = ANY(%s)",
        [leg.id for leg in legs],
    )
    return int(groups), int(stored)


class _Hook:
    """A write-ahead hook recording the records it was handed."""

    def __init__(self) -> None:
        self.seen: list[TradeGroupRecord] = []

    async def __call__(self, record: TradeGroupRecord) -> None:
        self.seen.append(record)


class _HookRefusedError(RuntimeError):
    """The audit trail refused the record: the hook's own typed refusal."""


@pytest_asyncio.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repo = SqlAlchemyRelationalRepository(_login(pg_dsn, "cv_app"), "trade-groups-it")
    try:
        yield repo
    finally:
        await repo.dispose()


@pytest.fixture
def store(rel: SqlAlchemyRelationalRepository) -> SqlAlchemyTradeGroupStore:
    return SqlAlchemyTradeGroupStore(rel)


@asynccontextmanager
async def _racing_store(dsn: str, suffix: str) -> AsyncIterator[SqlAlchemyTradeGroupStore]:
    """A store on its own pool, named `candleviewer:<suffix>` in `pg_stat_activity`."""
    repo = SqlAlchemyRelationalRepository(_login(dsn, "cv_app"), suffix)
    try:
        yield SqlAlchemyTradeGroupStore(repo, statement_timeout_ms=10_000)
    finally:
        await repo.dispose()


async def _wait_until_blocked(dsn: str, suffix: str) -> None:
    """Poll, as the superuser, until the session `candleviewer:<suffix>` waits on a heavyweight
    lock: at most 1000 polls, 10 ms apart (test_trade_groups_migration.py's recipe)."""

    def blocked() -> bool:
        with _conn(dsn) as c:
            for _ in range(1000):
                row = c.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name = %s "
                    "AND wait_event_type = 'Lock'",
                    (f"candleviewer:{suffix}",),
                ).fetchone()
                if row is not None and row[0] > 0:
                    return True
                c.execute("SELECT pg_sleep(0.01)")
        return False

    assert await asyncio.to_thread(blocked), f"candleviewer:{suffix} never waited on a lock"


async def _settle(*tasks: asyncio.Task[Any]) -> None:
    """Cancel what a failed test left running, and wait for it."""
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


# -- round trip and snapshot -----------------------------------------------------------------------


async def test_a_group_and_its_legs_round_trip_with_exact_decimals(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    """38 digits with 18 places, the smallest step and a numeric(10,2) leverage, exact through
    asyncpg, from the create, `load_group` and the scoped read alike."""
    owner = _user(pg_dsn, "owner")
    wide = Decimal("12345678901234567890.123456789012345678")
    group = _new_group(
        owner, entry_type="Limit", entry_price=Decimal("5.000000000000000001"),
        requested_qty_mode="fixed_qty", requested_qty_value=wide, algo="oco",
        algo_params={"legs": 2, "tp": "65000.5", "big": 10**20},
    )  # fmt: skip
    leg = _new_leg(
        pg_dsn, _account(pg_dsn), target_qty=Decimal("5.000000000000000001"),
        resolved_leverage=Decimal("99.99"), resolved_sl_price=Decimal("0.000000000000000001"),
        risk_usd=wide,
    )  # fmt: skip
    hook = _Hook()
    created = await store.create_group(group, [leg], write_ahead=hook)
    assert isinstance(created, GroupCreated) and hook.seen == [created.record]
    loaded = await store.load_group(group.id)
    scoped = await store.get_group(OwnerScope(owner), group.id)
    assert loaded == scoped == created.record
    stored = created.record
    assert str(stored.group.entry_price) == "5.000000000000000001"
    assert str(stored.group.requested_qty_value) == str(wide)
    assert stored.group.algo_params == {"legs": 2, "tp": "65000.5", "big": 10**20}
    (row,) = stored.legs
    assert row.target_qty == Decimal("5.000000000000000001") and row.risk_usd == wide
    assert str(row.resolved_leverage) == "99.99"
    assert format(row.resolved_sl_price, "f") == "0.000000000000000001"  # str() is 1E-18
    assert row.filled_qty == 0 and row.realised_pnl == 0 and not row.native_sl_confirmed


@pytest.mark.parametrize("policy", LEG_FAILURE_POLICIES)
async def test_the_failure_policy_is_stored_as_named_and_read_back(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str, policy: str
) -> None:
    """The store writes the policy its writer names, never the column default by omission, and
    every read returns it: B2, the unwind and a restart read it from the row (24 Sec.9.5)."""
    owner = _user(pg_dsn, "owner")
    group = _new_group(owner, leg_failure_policy=policy)
    created = await store.create_group(group, [_new_leg(pg_dsn, _account(pg_dsn))])
    assert isinstance(created, GroupCreated)
    assert created.record.group.leg_failure_policy == policy
    stored = "SELECT leg_failure_policy FROM trade_groups WHERE id = %s"
    assert _one(pg_dsn, stored, group.id) == policy
    loaded = await store.load_group(group.id)
    scoped = await store.get_group(OwnerScope(owner), group.id)
    opened = {record.group.id: record for record in await store.list_open_groups()}
    assert loaded == scoped == opened[group.id] == created.record


@pytest.mark.parametrize("fixture", _PROFILE_FIXTURES)
async def test_the_leg_snapshot_reads_back_as_the_profile_it_was_sized_from(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str, fixture: str
) -> None:
    account = _account(pg_dsn)
    profile = _default_profile(pg_dsn, account)
    leg = _new_leg(pg_dsn, account, profile=profile, fixture=fixture)
    await store.create_group(_new_group(_user(pg_dsn)), [leg])
    found = await store.load_leg(leg.id)
    assert found is not None and found.leg.account_profile_id == profile
    sized_from = _profile_model(account, profile, 1, fixture)
    assert AccountProfile.model_validate(found.profile_snapshot) == sized_from  # Decimal equality
    assert json.dumps(found.profile_snapshot, sort_keys=True) == json.dumps(
        sized_from.model_dump(mode="json"), sort_keys=True
    )  # identical string forms


def _floats(value: object) -> list[float]:
    if isinstance(value, float):
        return [value]
    if isinstance(value, dict):
        return [f for item in value.values() for f in _floats(item)]
    if isinstance(value, list):
        return [f for item in value for f in _floats(item)]
    return []


async def test_the_stored_snapshot_is_the_profile_projection_and_nothing_else(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    account = _account(pg_dsn)
    leg = _new_leg(pg_dsn, account)
    await store.create_group(_new_group(_user(pg_dsn)), [leg])
    stored = _one(pg_dsn, "SELECT profile_snapshot FROM trade_group_legs WHERE id = %s", leg.id)
    assert stored == leg.profile_snapshot
    assert set(stored) == set(AccountProfile.model_fields)
    assert _floats(stored) == []


async def test_a_profile_edit_after_the_leg_leaves_its_snapshot_and_version(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    """The store half of #905's scenario "Leg snapshot survives a profile edit"."""
    account = _account(pg_dsn)
    profile = _default_profile(pg_dsn, account)
    leg = _new_leg(pg_dsn, account, profile=profile)
    await store.create_group(_new_group(_user(pg_dsn)), [leg])
    _sql(pg_dsn, "UPDATE account_profiles SET leverage = 3 WHERE id = %s", profile)
    assert _one(pg_dsn, "SELECT version FROM account_profiles WHERE id = %s", profile) == 2
    found = await store.load_leg(leg.id)
    assert found is not None
    assert (found.leg.account_profile_id, found.leg.profile_version) == (profile, 1)
    assert found.profile_snapshot == leg.profile_snapshot


# -- the replay anchor -----------------------------------------------------------------------------


async def test_a_replay_with_the_same_body_answers_the_first_group_and_writes_nothing(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    creator, account = _user(pg_dsn), _account(pg_dsn)
    first = _new_group(creator)
    first_legs = [_new_leg(pg_dsn, account)]
    await store.create_group(first, first_legs)
    again = _new_group(creator, ref=first.client_group_ref)
    again_legs = [_new_leg(pg_dsn, account)]
    hook = _Hook()
    outcome = await store.create_group(again, again_legs, write_ahead=hook)
    assert outcome == GroupExists(GroupAnchor(first.id, True)) and hook.seen == []
    assert _groups_with_ref(pg_dsn, creator, first.client_group_ref) == [first.id]
    assert _rows_of(pg_dsn, again, again_legs) == (0, 0)
    record = await store.load_group(first.id)
    assert record is not None and [leg.id for leg in record.legs] == [first_legs[0].id]
    anchor = await store.find_anchor(creator, first.client_group_ref, _BODY)
    assert anchor == GroupAnchor(first.id, True)


async def test_a_replay_after_the_profile_changed_still_answers_the_first_group(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    """The anchor comes first: a replay never reaches the profile check."""
    creator, account = _user(pg_dsn), _account(pg_dsn)
    profile = _default_profile(pg_dsn, account)
    first = _new_group(creator)
    await store.create_group(first, [_new_leg(pg_dsn, account, profile=profile)])
    _sql(pg_dsn, "UPDATE account_profiles SET leverage = 3 WHERE id = %s", profile)
    replay = _new_group(creator, ref=first.client_group_ref)
    outcome = await store.create_group(replay, [_new_leg(pg_dsn, account, profile=profile)])
    assert outcome == GroupExists(GroupAnchor(first.id, True))


async def test_the_same_ref_with_another_body_is_key_reuse(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    creator, account = _user(pg_dsn), _account(pg_dsn)
    first = _new_group(creator)
    await store.create_group(first, [_new_leg(pg_dsn, account)])
    reused = _new_group(creator, ref=first.client_group_ref, client_body_sha256=_OTHER_BODY)
    outcome = await store.create_group(reused, [_new_leg(pg_dsn, account)])
    assert outcome == GroupExists(GroupAnchor(first.id, False))
    found = await store.find_anchor(creator, first.client_group_ref, _OTHER_BODY)
    assert found == GroupAnchor(first.id, False)
    assert _groups_with_ref(pg_dsn, creator, first.client_group_ref) == [first.id]


async def test_another_users_ref_reads_as_missing_and_creates_its_own_group(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    first_user, second_user, account = _user(pg_dsn), _user(pg_dsn), _account(pg_dsn)
    first = _new_group(first_user)
    await store.create_group(first, [_new_leg(pg_dsn, account)])
    assert await store.find_anchor(second_user, first.client_group_ref, _BODY) is None
    second = _new_group(second_user, ref=first.client_group_ref)
    outcome = await store.create_group(second, [_new_leg(pg_dsn, account)])
    assert isinstance(outcome, GroupCreated) and outcome.record.group.id == second.id
    assert _groups_with_ref(pg_dsn, first_user, first.client_group_ref) == [first.id]


# -- deterministic concurrency ---------------------------------------------------------------------


async def test_two_concurrent_creates_of_one_anchor_store_one_group(pg_dsn: str) -> None:
    """B's insert waits on A's uncommitted anchor; once A commits, B writes nothing and answers
    A's group, which the facade reads as a `GroupReplay`."""
    from candleviewer.accounts.trade_group_repository import TradeGroupRepository
    from candleviewer.accounts.trade_groups import GroupReplay

    creator, account = _user(pg_dsn), _account(pg_dsn)
    group_a = _new_group(creator)
    group_b = _new_group(creator, ref=group_a.client_group_ref)
    legs_b = [_new_leg(pg_dsn, account)]
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold(record: TradeGroupRecord) -> None:
        entered.set()
        await release.wait()

    async with (
        asyncio.timeout(15),
        _racing_store(pg_dsn, "tg-race-a") as store_a,
        _racing_store(pg_dsn, "tg-race-b") as store_b,
    ):
        first = asyncio.create_task(
            store_a.create_group(group_a, [_new_leg(pg_dsn, account)], write_ahead=hold)
        )
        second: asyncio.Task[GroupCreated | GroupExists] | None = None
        try:
            await entered.wait()
            second = asyncio.create_task(store_b.create_group(group_b, legs_b))
            await _wait_until_blocked(pg_dsn, "tg-race-b")
            release.set()
            created = await first
            exists = await second
        finally:
            release.set()
            await _settle(first, *([second] if second is not None else []))
        assert isinstance(created, GroupCreated)
        assert exists == GroupExists(GroupAnchor(group_a.id, True))
        replay = await TradeGroupRepository(store_b).find_replay(
            UserId(creator), uuid.UUID(group_a.client_group_ref), _BODY
        )
    assert replay == GroupReplay(GroupId(group_a.id))
    assert _groups_with_ref(pg_dsn, creator, group_a.client_group_ref) == [group_a.id]
    assert _rows_of(pg_dsn, group_b, legs_b) == (0, 0)


async def test_a_rolled_back_first_create_lets_the_second_store_its_group(pg_dsn: str) -> None:
    creator, account = _user(pg_dsn), _account(pg_dsn)
    group_a = _new_group(creator)
    legs_a = [_new_leg(pg_dsn, account)]
    group_b = _new_group(creator, ref=group_a.client_group_ref)
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold_then_refuse(record: TradeGroupRecord) -> None:
        entered.set()
        await release.wait()
        raise _HookRefusedError

    async with (
        asyncio.timeout(15),
        _racing_store(pg_dsn, "tg-race-a") as store_a,
        _racing_store(pg_dsn, "tg-race-b") as store_b,
    ):
        first = asyncio.create_task(
            store_a.create_group(group_a, legs_a, write_ahead=hold_then_refuse)
        )
        second: asyncio.Task[GroupCreated | GroupExists] | None = None
        try:
            await entered.wait()
            second = asyncio.create_task(store_b.create_group(group_b, [_new_leg(pg_dsn, account)]))
            await _wait_until_blocked(pg_dsn, "tg-race-b")
            release.set()
            with pytest.raises(_HookRefusedError):
                await first
            stored = await second
        finally:
            release.set()
            await _settle(first, *([second] if second is not None else []))
    assert isinstance(stored, GroupCreated) and stored.record.group.id == group_b.id
    assert _groups_with_ref(pg_dsn, creator, group_a.client_group_ref) == [group_b.id]
    assert _rows_of(pg_dsn, group_a, legs_a) == (0, 0)


async def _create_through_the_facade(
    store: SqlAlchemyTradeGroupStore,
    creator: uuid.UUID,
    account: uuid.UUID,
    profile_id: uuid.UUID,
    version: int,
) -> object:
    """The facade's create of a one-leg demo Market group sized from the profile at `version`."""
    from candleviewer.accounts.trade_group_repository import TradeGroupRepository
    from candleviewer.accounts.trade_groups import LegDraft, TradeGroupDraft

    profile = _profile_model(account, profile_id, version)
    group = TradeGroupDraft.model_validate(
        {
            "group_id": uuid.uuid4(), "client_group_ref": uuid.uuid4(),
            "client_body_sha256": _BODY, "created_by": creator, "environment": "demo",
            "symbol": "BTCUSDT", "side": "buy", "status": "submitting",
            "leg_failure_policy": "best_effort", "algo": "none", "algo_params": None,
            "note": None, "origin": "manual", "rule_id": None, "rule_run_id": None,
            "definition_id": None, "requested_qty_mode": "risk_based",
            "requested_qty_value": None, "entry_type": "market", "entry_price": None,
            "trigger_price": None, "trigger_by": None, "sl_price_hint": None,
            "tp_price_hint": None, "is_paper": False,
        }
    )  # fmt: skip
    leg = LegDraft.model_validate(
        {
            "leg_id": uuid.uuid4(), "profile": profile, "status": "pending", "sequence_no": 0,
            "target_qty": Decimal("0.010"), "resolved_leverage": Decimal("5"),
            "resolved_sl_price": Decimal("62000"), "resolved_tp_price": None, "risk_usd": None,
            "rejection_code": None, "rejection_message": None,
        }
    )  # fmt: skip
    return await TradeGroupRepository(store).create(group, [leg], write_ahead=_Hook())


def _groups_of(dsn: str, creator: uuid.UUID) -> int:
    return int(_one(dsn, "SELECT count(*) FROM trade_groups WHERE created_by = %s", creator))


async def test_stale_profile_version_is_refused_at_submit(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    """The store half of the SR-E28-15 owed test: the profile moved to version 2 before the
    create of a leg sized from version 1, which writes nothing."""
    from candleviewer.accounts.errors import ProfileChangedError

    creator, account = _user(pg_dsn), _account(pg_dsn)
    profile = _default_profile(pg_dsn, account)
    _sql(pg_dsn, "UPDATE account_profiles SET leverage = 3 WHERE id = %s", profile)
    with pytest.raises(ProfileChangedError):
        await _create_through_the_facade(store, creator, account, profile, 1)
    with pytest.raises(TradeGroupStoreRefusedError) as ei:
        await store.create_group(
            _new_group(creator), [_new_leg(pg_dsn, account, profile=profile, version=1)]
        )
    assert ei.value.reason == PROFILE_CHANGED
    assert _groups_of(pg_dsn, creator) == 0


async def test_a_profile_update_racing_a_create_is_serialised(pg_dsn: str) -> None:
    """A profile UPDATE held open: the create waits on its `FOR SHARE`, then reads the committed
    version 2 and refuses the leg sized from version 1."""
    from candleviewer.accounts.errors import ProfileChangedError

    creator, account = _user(pg_dsn), _account(pg_dsn)
    profile = _default_profile(pg_dsn, account)
    async with asyncio.timeout(15), _racing_store(pg_dsn, "tg-race-b") as racing:
        with _conn(pg_dsn) as holder:
            holder.autocommit = False
            holder.execute("UPDATE account_profiles SET leverage = 3 WHERE id = %s", (profile,))
            create = asyncio.create_task(
                _create_through_the_facade(racing, creator, account, profile, 1)
            )
            try:
                await _wait_until_blocked(pg_dsn, "tg-race-b")
                await asyncio.to_thread(holder.commit)
                with pytest.raises(ProfileChangedError):
                    await create
            finally:
                await _settle(create)
    assert _one(pg_dsn, "SELECT version FROM account_profiles WHERE id = %s", profile) == 2
    assert _groups_of(pg_dsn, creator) == 0


# -- refusals and integrity ------------------------------------------------------------------------


@pytest.mark.parametrize("gone", ["account", "definition"])
async def test_a_soft_deleted_account_or_definition_refuses_the_create(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str, gone: str
) -> None:
    creator, kept, other = _user(pg_dsn), _account(pg_dsn), _account(pg_dsn)
    definition = _definition(pg_dsn)
    group = _new_group(creator, definition_id=definition if gone == "definition" else None)
    legs = [_new_leg(pg_dsn, kept), _new_leg(pg_dsn, other, seq=1)]
    if gone == "account":
        _sql(pg_dsn, "UPDATE exchange_accounts SET deleted_at = now() WHERE id = %s", other)
    else:
        _sql(
            pg_dsn,
            "UPDATE trade_group_definitions SET deleted_at = now() WHERE id = %s",
            definition,
        )
    hook = _Hook()
    with pytest.raises(TradeGroupStoreRefusedError) as ei:
        await store.create_group(group, legs, write_ahead=hook)
    assert ei.value.reason == (ACCOUNT_NOT_LIVE if gone == "account" else DEFINITION_NOT_LIVE)
    assert hook.seen == [] and _rows_of(pg_dsn, group, legs) == (0, 0)


async def test_a_group_fired_from_a_live_definition_is_stored(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    group = _new_group(_user(pg_dsn), definition_id=_definition(pg_dsn))
    outcome = await store.create_group(group, [_new_leg(pg_dsn, _account(pg_dsn))])
    assert isinstance(outcome, GroupCreated)
    assert outcome.record.group.definition_id == group.definition_id


async def test_a_duplicate_leg_account_is_a_conflict_and_leaves_no_orphan_rows(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    account = _account(pg_dsn)
    group = _new_group(_user(pg_dsn))
    legs = [_new_leg(pg_dsn, account), _new_leg(pg_dsn, account, seq=1)]
    with pytest.raises(TradeGroupStoreConflictError) as ei:
        await store.create_group(group, legs)
    assert ei.value.constraint == "ux_tgl_group_account"
    assert _rows_of(pg_dsn, group, legs) == (0, 0)


async def test_a_leg_refused_mid_insert_rolls_back_its_group(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    """The port admits a leverage numeric(10,2) holds; `tgl_lev` (1..100) refuses it."""
    group = _new_group(_user(pg_dsn))
    legs = [
        _new_leg(pg_dsn, _account(pg_dsn)),
        _new_leg(pg_dsn, _account(pg_dsn), seq=1, resolved_leverage=Decimal("150")),
    ]
    with pytest.raises(TradeGroupStoreRuleError) as ei:
        await store.create_group(group, legs)
    assert ei.value.rule == "tgl_lev" and str(ei.value) == "tgl_lev"
    assert _rows_of(pg_dsn, group, legs) == (0, 0)


@pytest.mark.parametrize("stop", [None, Decimal("0")], ids=["no-stop", "zero-stop"])
async def test_a_leg_that_may_open_without_a_positive_stop_is_refused_as_tgl_sl_px(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str, stop: Decimal | None
) -> None:
    """C-2.6 through the store: a pending leg without a positive native stop is refused by name
    and leaves no row; a rejected one needs no stop and is stored, and opening it is refused the
    same way."""
    creator = _user(pg_dsn)
    pending = _new_group(creator)
    legs = [_new_leg(pg_dsn, _account(pg_dsn), resolved_sl_price=stop)]
    with pytest.raises(TradeGroupStoreRuleError) as refused:
        await store.create_group(pending, legs)
    assert refused.value.rule == "tgl_sl_px" and _rows_of(pg_dsn, pending, legs) == (0, 0)
    rejected = _new_group(creator)
    leg = _new_leg(pg_dsn, _account(pg_dsn), status="rejected", resolved_sl_price=stop)
    assert isinstance(await store.create_group(rejected, [leg]), GroupCreated)
    with pytest.raises(TradeGroupStoreRuleError) as reopened:
        await store.update_leg(rejected.id, leg.id, LegPatch(status="open"))
    assert reopened.value.rule == "tgl_sl_px"
    stored = "SELECT status::text FROM trade_group_legs WHERE id = %s"
    assert _one(pg_dsn, stored, leg.id) == "rejected"  # nothing written


async def test_a_leg_outside_the_group_environment_is_refused_by_trg_tgl_env(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    group = _new_group(_user(pg_dsn))
    legs = [_new_leg(pg_dsn, _account(pg_dsn)), _new_leg(pg_dsn, _account(pg_dsn, "live"), seq=1)]
    with pytest.raises(TradeGroupStoreRuleError) as ei:
        await store.create_group(group, legs)
    assert ei.value.rule == "trg_tgl_env"
    assert _rows_of(pg_dsn, group, legs) == (0, 0)


async def test_a_refused_group_leaves_without_its_note_or_prices(
    rel: SqlAlchemyRelationalRepository, store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    group = _new_group(
        _user(pg_dsn), entry_type="Limit", entry_price=Decimal(0), intent_note=_NOTE,
        algo_params={"n": _PARAM}, sl_price_hint=_STOP,
    )  # fmt: skip
    legs = [_new_leg(pg_dsn, _account(pg_dsn))]
    with server_text(rel) as seen, pytest.raises(TradeGroupStoreRuleError) as err:
        await store.create_group(group, legs)
    assert err.value.rule == "tg_limit_px" and _rows_of(pg_dsn, group, legs) == (0, 0)
    assert (err.value.__cause__, err.value.__suppress_context__) == (None, True)
    assert_no_row_values(err.value, seen, _NOTE, _PARAM, str(_STOP))


async def test_a_failing_write_ahead_hook_leaves_nothing(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    group = _new_group(_user(pg_dsn))
    legs = [_new_leg(pg_dsn, _account(pg_dsn))]

    async def refuses(record: TradeGroupRecord) -> None:
        assert record.group.id == group.id and len(record.legs) == 1
        raise _HookRefusedError

    with pytest.raises(_HookRefusedError):
        await store.create_group(group, legs, write_ahead=refuses)
    assert _rows_of(pg_dsn, group, legs) == (0, 0)


# -- updates ---------------------------------------------------------------------------------------


async def _created(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str, **group: Any
) -> tuple[NewTradeGroup, NewTradeGroupLeg]:
    new = _new_group(_user(pg_dsn), **group)
    leg = _new_leg(pg_dsn, _account(pg_dsn))
    assert isinstance(await store.create_group(new, [leg]), GroupCreated)
    return new, leg


async def test_update_leg_compare_and_set_and_set_once_submitted_at(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    group, leg = await _created(store, pg_dsn)
    later = _T0 + timedelta(seconds=5)
    sent = await store.update_leg(
        group.id, leg.id, LegPatch(status="submitted", submitted_at=_T0), expected_status="pending"
    )
    assert sent is not None and (sent.status, sent.submitted_at) == ("submitted", _T0)
    with pytest.raises(TradeGroupStoreStaleError):
        await store.update_leg(group.id, leg.id, LegPatch(status="open"), expected_status="pending")
    opened = await store.update_leg(
        group.id, leg.id, LegPatch(status="open", submitted_at=later), expected_status="submitted"
    )
    assert opened is not None and (opened.status, opened.submitted_at) == ("open", _T0)
    confirmed = await store.update_leg(
        group.id, leg.id,
        LegPatch(native_sl_confirmed=True, native_sl_confirmed_at=later,
                 rejection_message=_LETTER_RUN),
    )  # fmt: skip
    assert confirmed is not None and confirmed.native_sl_confirmed
    assert confirmed.native_sl_confirmed_at == later
    assert confirmed.rejection_message == redact_exchange_text(_LETTER_RUN, message=True)
    assert confirmed.rejection_message != _LETTER_RUN
    with pytest.raises(TradeGroupStoreRuleError) as ei:
        await store.update_leg(group.id, leg.id, LegPatch(filled_qty=Decimal("1")))
    assert ei.value.rule == "tgl_filled_rng"
    assert await store.update_leg(uuid.uuid4(), leg.id, LegPatch(status="closed")) is None


async def test_update_group_sets_submitted_and_opened_once(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    group, _ = await _created(store, pg_dsn)
    t1, t2, t3 = (_T0 + timedelta(seconds=s) for s in (1, 2, 3))
    first = await store.update_group(
        group.id, GroupPatch(status="open", submitted_at=_T0, opened_at=t1),
        expected_status="submitting",
    )  # fmt: skip
    assert first is not None and (first.status, first.submitted_at, first.opened_at) == (
        "open", _T0, t1,
    )  # fmt: skip
    second = await store.update_group(
        group.id, GroupPatch(status="closed", submitted_at=t2, opened_at=t2, closed_at=t3)
    )
    assert second is not None
    assert (second.submitted_at, second.opened_at, second.closed_at) == (_T0, t1, t3)
    with pytest.raises(TradeGroupStoreStaleError):
        await store.update_group(group.id, GroupPatch(status="open"), expected_status="open")
    with pytest.raises(TradeGroupStoreRuleError) as ei:
        await store.update_group(group.id, GroupPatch(closed_at=_T0))  # before opened_at
    assert ei.value.rule == "tg_times"
    assert await store.update_group(uuid.uuid4(), GroupPatch(status="open")) is None


#: The create-only columns, then the write-once policy.
_FIXED_SELECT = (
    "SELECT symbol::text, side, entry_type, origin, origin_rule_id, is_paper, algo_params, "
    "leg_failure_policy FROM trade_groups WHERE id = %s"
)


async def test_the_store_never_changes_a_create_only_or_write_once_column(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    """Every status and time update leaves them as written; a policy change would be
    `trg_tg_write_once`'s refusal, which no update here meets."""
    group, leg = await _created(
        store, pg_dsn, algo="oco", algo_params={"legs": 2}, entry_type="Limit",
        entry_price=Decimal("63000.5"), is_paper=True, leg_failure_policy="all_or_none",
    )  # fmt: skip
    before = _sql(pg_dsn, _FIXED_SELECT, group.id)
    await store.update_group(group.id, GroupPatch(status="open", submitted_at=_T0, opened_at=_T0))
    await store.update_leg(group.id, leg.id, LegPatch(status="filled", filled_qty=leg.target_qty))
    await store.update_group(group.id, GroupPatch(status="closed", closed_at=_T0))
    assert _sql(pg_dsn, _FIXED_SELECT, group.id) == before
    assert before[0][5:] == (True, {"legs": 2}, "all_or_none")


# -- index use -------------------------------------------------------------------------------------


def _plan(dsn: str, stmt: sa.Select[Any]) -> str:
    """EXPLAIN of the statement as compiled, under `enable_seqscan = off`, after ANALYZE."""
    text = str(stmt.compile(dialect=_POSTGRES, compile_kwargs={"literal_binds": True}))
    with _conn(dsn) as c:
        c.execute("ANALYZE trade_groups, trade_group_legs")
        with c.transaction():
            c.execute("SET LOCAL enable_seqscan = off")
            rows = c.execute(sql.SQL("EXPLAIN {}").format(sql.SQL(text))).fetchall()
    return "\n".join(str(row[0]) for row in rows)


async def test_open_groups_use_ix_tg_open(store: SqlAlchemyTradeGroupStore, pg_dsn: str) -> None:
    creator = _user(pg_dsn)
    for _ in range(20):  # closed groups, so the partial index is the smaller one
        _sql(
            pg_dsn,
            "INSERT INTO trade_groups (id, client_group_ref, client_body_sha256, env, symbol, "
            "side, status, created_by) VALUES (%s, %s, %s, 'demo', 'BTCUSDT', 'Buy', 'closed', %s)",
            uuid.uuid4(), str(uuid.uuid4()), _BODY, creator,
        )  # fmt: skip
    group, _ = await _created(store, pg_dsn)
    assert group.id in {r.group.id for r in await store.list_open_groups()}
    assert "ix_tg_open" in _plan(pg_dsn, open_groups_statement())


async def test_unprotected_legs_use_ix_tgl_no_sl(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    group = _new_group(_user(pg_dsn))
    legs = [_new_leg(pg_dsn, _account(pg_dsn), seq=i) for i in range(3)]  # pending: not in it
    await store.create_group(group, legs)
    await store.update_leg(group.id, legs[0].id, LegPatch(status="filled"))
    assert legs[0].id in {r.leg.id for r in await store.list_unprotected_legs()}
    assert "ix_tgl_no_sl" in _plan(pg_dsn, unprotected_legs_statement())


async def test_a_filled_leg_without_a_confirmed_stop_is_listed_even_on_a_soft_deleted_account(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    group, leg = await _created(store, pg_dsn)
    await store.update_group(group.id, GroupPatch(status="open"))
    await store.update_leg(group.id, leg.id, LegPatch(status="filled", filled_qty=leg.target_qty))
    _sql(
        pg_dsn, "UPDATE exchange_accounts SET deleted_at = now() WHERE id = %s",
        leg.exchange_account_id,
    )  # fmt: skip
    listed = {r.leg.id: r for r in await store.list_unprotected_legs()}
    assert leg.id in listed
    assert (listed[leg.id].symbol, listed[leg.id].env, listed[leg.id].side) == (
        "BTCUSDT", "demo", "Buy",
    )  # fmt: skip
    assert group.id in {r.group.id for r in await store.list_open_groups()}
    await store.update_leg(
        group.id, leg.id, LegPatch(native_sl_confirmed=True, native_sl_confirmed_at=_T0)
    )
    assert leg.id not in {r.leg.id for r in await store.list_unprotected_legs()}


# -- scope and IDOR (SR-E28-21) --------------------------------------------------------------------

#: A Manager granted A and B, each cell changing one thing; the Owner sees every group. The E28
#: world's G-CORE3 (A, B, C) and G-PAIR (A, C) are the cells `legs-a-b-and-c` and
#: `a-leg-on-ungranted-c`: hidden from a manager missing E28-C, on `get_group` and the list alike.
_CELLS = {
    "legs-a-and-b": True,
    "legs-a-b-and-c": False,
    "a-leg-on-ungranted-c": False,
    "the-a-grant-frozen": False,
    "the-a-grant-soft-revoked": False,
    "the-scope-lists-c-without-a-grant": False,
    "account-b-soft-deleted": False,
    "a-leg-less-group": False,
    "another-managers-group": True,
}


@pytest.mark.parametrize(("cell", "visible"), list(_CELLS.items()), ids=list(_CELLS))
async def test_group_with_ungranted_leg_is_invisible(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str, cell: str, visible: bool
) -> None:
    from candleviewer.accounts.trade_group_repository import TradeGroupReader

    owner, manager = _user(pg_dsn, "owner"), _user(pg_dsn, "manager")
    a, b, c = _account(pg_dsn), _account(pg_dsn), _account(pg_dsn)
    for granted in (a, b):
        _grant(pg_dsn, manager, granted)
    scope = GrantScope(manager, frozenset({a, b}))
    creator = _user(pg_dsn, "manager") if cell == "another-managers-group" else manager
    group = _new_group(creator)
    if cell == "a-leg-less-group":  # no store path writes one: plain SQL
        _sql(
            pg_dsn,
            "INSERT INTO trade_groups (id, client_group_ref, client_body_sha256, env, symbol, "
            "side, created_by) VALUES (%s, %s, %s, 'demo', 'BTCUSDT', 'Buy', %s)",
            group.id, group.client_group_ref, _BODY, creator,
        )  # fmt: skip
    else:
        on_c = cell in {"a-leg-on-ungranted-c", "the-scope-lists-c-without-a-grant"}
        accounts = (a, b, c) if cell == "legs-a-b-and-c" else (a, c) if on_c else (a, b)
        legs = [_new_leg(pg_dsn, acct, seq=i) for i, acct in enumerate(accounts)]
        assert isinstance(await store.create_group(group, legs), GroupCreated)
    if cell == "the-a-grant-frozen":
        _sql(
            pg_dsn,
            "UPDATE user_account_access SET frozen = true, frozen_at = now() "
            "WHERE user_id = %s AND exchange_account_id = %s",
            manager, a,
        )  # fmt: skip
    elif cell == "the-a-grant-soft-revoked":
        _sql(
            pg_dsn,
            "UPDATE user_account_access SET can_view = false, can_trade = false "
            "WHERE user_id = %s AND exchange_account_id = %s",
            manager, a,
        )  # fmt: skip
    elif cell == "the-scope-lists-c-without-a-grant":
        scope = GrantScope(manager, frozenset({a, b, c}))
    elif cell == "account-b-soft-deleted":
        _sql(pg_dsn, "UPDATE exchange_accounts SET deleted_at = now() WHERE id = %s", b)
    seen = await store.get_group(scope, group.id)
    assert (seen is not None) is visible
    page = await TradeGroupReader(store).list(scope, limit=100)  # the same predicate, on a page
    listed, gid = {s.record.group.group_id: s for s in page}, GroupId(group.id)
    assert (gid in listed) is visible
    as_owner = await store.get_group(OwnerScope(owner), group.id)
    assert as_owner is not None and as_owner.group.id == group.id
    if seen is not None:
        assert seen == as_owner
        shown = await TradeGroupReader(store).get(scope, gid)
        assert shown.shows_private_fields is (creator == manager) and listed[gid] == shown


async def test_a_non_owner_holding_an_owner_scope_is_refused(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    group, _ = await _created(store, pg_dsn)
    with pytest.raises(TradeGroupStoreScopeDeniedError):
        await store.get_group(OwnerScope(_user(pg_dsn, "manager")), group.id)


@pytest.mark.parametrize(
    "build", [scoped_group_statement, scoped_legs_statement], ids=["group", "legs"]
)
async def test_the_scoped_statements_carry_the_owner_predicate_beyond_the_gate(
    rel: SqlAlchemyRelationalRepository,
    store: SqlAlchemyTradeGroupStore,
    pg_dsn: str,
    build: Any,
) -> None:
    """Run on a session with no live-owner gate before it, a scoped statement reads nothing for
    a manager holding an `OwnerScope`, and the group or its leg for the Owner: a path that
    skipped the gate stays scoped."""
    owner, manager = _user(pg_dsn, "owner"), _user(pg_dsn, "manager")
    group, _ = await _created(store, pg_dsn)
    async with rel.unit_of_work() as uow:
        as_manager = (await uow.session.execute(build(OwnerScope(manager), group.id))).all()
        as_owner = (await uow.session.execute(build(OwnerScope(owner), group.id))).all()
    assert as_manager == [] and len(as_owner) == 1


async def test_an_empty_grant_scope_sees_nothing(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    group, _ = await _created(store, pg_dsn)
    assert await store.get_group(GrantScope(_user(pg_dsn), frozenset()), group.id) is None


# -- the list and a leg's orders (E28-T05 S2e) ----------------------------------------------------


def _page(**over: Any) -> dict[str, Any]:
    """`list_groups`' arguments: no filter and no cursor, ten rows, unless given."""
    nothing: dict[str, Any] = {"symbol": None, "statuses": (), "created_from": None}
    return nothing | {"created_to": None, "after": None, "limit": 10} | over


async def test_the_list_filters_and_its_keyset_is_stable_across_equal_creation_times(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    """Newest first by `(created_at, id)`: pages of two over five groups, three made in one
    instant, repeat none and skip none; each filter narrows the page and only it."""
    symbol, elsewhere = (f"T{uuid.uuid4().hex[:10].upper()}" for _ in range(2))
    t1, t2 = _T0 + timedelta(seconds=1), _T0 + timedelta(seconds=2)
    stamps, statuses = [_T0, _T0, _T0, t1, t2], ["open", "closed", "open", "closed", "open"]
    made: list[uuid.UUID] = []
    for at, status in zip(stamps, statuses, strict=True):
        group, _ = await _created(store, pg_dsn, symbol=symbol, status="draft")
        update = "UPDATE trade_groups SET created_at = %s, status = %s WHERE id = %s"
        _sql(pg_dsn, update, at, status, group.id)  # 0053 freezes `created_at` after `draft`
        made.append(group.id)
    foreign, _ = await _created(store, pg_dsn, symbol=elsewhere)
    scope, seen = OwnerScope(_user(pg_dsn, "owner")), []
    after: tuple[datetime, uuid.UUID] | None = None
    for _ in range(3):
        page = await store.list_groups(scope, **_page(symbol=symbol, after=after, limit=2))
        seen += [r.group.id for r in page]
        after = (page[-1].group.created_at, page[-1].group.id)
    assert seen == [i for _, i in sorted(zip(stamps, made, strict=True), reverse=True)]
    cases: list[tuple[dict[str, Any], set[int]]] = [
        ({"statuses": ("open",)}, {0, 2, 4}), ({"created_from": t1}, {3, 4}),
        ({"created_to": t1}, {0, 1, 2}),  # the start is in, the end is out
        ({"statuses": ("closed",), "created_from": t1, "created_to": t2}, {3}),
    ]  # fmt: skip
    for filters, wanted in cases:
        got = await store.list_groups(scope, **_page(symbol=symbol, **filters))
        assert {r.group.id for r in got} == {made[i] for i in wanted}, filters
    only = await store.list_groups(scope, **_page(symbol=elsewhere))
    assert [r.group.id for r in only] == [foreign.id]


async def test_leg_order_ids_are_those_of_a_visible_group_oldest_first(
    store: SqlAlchemyTradeGroupStore, pg_dsn: str
) -> None:
    """A leg's orders are read under its group's predicate: a granted leg in a group that also
    has a leg on C reads none, whoever asks for its id; an order of the leg on another account
    (C) is not its own."""
    from candleviewer.accounts.trade_group_repository import TradeGroupReader

    owner, manager = _user(pg_dsn, "owner"), _user(pg_dsn, "manager")
    a, c = _account(pg_dsn), _account(pg_dsn)
    _grant(pg_dsn, manager, a)
    mine, hidden = _new_leg(pg_dsn, a), _new_leg(pg_dsn, a)
    await store.create_group(_new_group(manager), [mine])
    await store.create_group(_new_group(manager), [hidden, _new_leg(pg_dsn, c, seq=1)])
    later, earlier = sorted((uuid.uuid4(), uuid.uuid4()))  # the older order has the higher id
    stray, t = uuid.uuid4(), _T0 + timedelta(seconds=1)
    placed = [(later, mine, a, t), (earlier, mine, a, _T0), (stray, hidden, a, t)]
    for order, leg, account, at in [*placed, (uuid.uuid4(), mine, c, t)]:  # the last: on C
        _sql(
            pg_dsn,
            "INSERT INTO orders (id, trade_group_leg_id, exchange_account_id, order_link_id, "
            "symbol, side, intent, order_type, qty, created_ts) VALUES (%s, %s, %s, "
            "'ext-' || md5(%s::text), 'BTCUSDT', 'Buy', 'entry', 'Market', 1, %s)",
            order, leg.id, account, order.hex, at,
        )  # fmt: skip
    asked, reader = [mine.id, hidden.id], TradeGroupReader(store)
    granted = await reader.order_ids(GrantScope(manager, frozenset({a})), asked)
    assert granted == {mine.id: (earlier, later)}  # by `created_ts`, whatever the ids
    everything = await reader.order_ids(OwnerScope(owner), asked)
    assert everything == {mine.id: (earlier, later), hidden.id: (stray,)}


# -- the catalog -----------------------------------------------------------------------------------


def test_the_error_names_match_the_catalog(pg_dsn: str) -> None:
    """Every constraint of both tables and every trigger's `USING CONSTRAINT` name is a rule or a
    conflict the store maps, and the domain CHECKs are the domains' own."""
    constraints = _sql(
        pg_dsn,
        "SELECT conname FROM pg_constraint "
        "WHERE conrelid IN ('trade_groups'::regclass, 'trade_group_legs'::regclass)",
    )
    names = {row[0] for row in constraints}
    sources = _sql(
        pg_dsn,
        "SELECT p.prosrc FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid "
        "WHERE t.tgrelid IN ('trade_groups'::regclass, 'trade_group_legs'::regclass) "
        "AND NOT t.tgisinternal",
    )
    triggers = {name for (src,) in sources for name in re.findall(r"CONSTRAINT = '(trg_\w+)'", src)}
    domains = {
        row[0]
        for row in _sql(
            pg_dsn,
            "SELECT conname FROM pg_constraint "
            "WHERE contypid IN ('sha256_hex'::regtype, 'symbol_code'::regtype)",
        )
    }
    assert domains == {"sha256_hex_check", "symbol_code_check"}
    assert names | triggers == (TRADE_GROUP_RULES | TRADE_GROUP_CONFLICTS) - domains
    assert triggers == {n for n in TRADE_GROUP_RULES if n.startswith("trg_")}
