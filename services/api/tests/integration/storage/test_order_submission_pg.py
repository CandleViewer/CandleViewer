"""Integration: the first persist and the order-submission stores on real Postgres 16 (E29-T04
#913, revision `0043_order_submission`).

The database is set up like production (`pg_bootstrap.sql`'s roles, then the migrations as
`cv_owner`) and the stores run as `cv_app`, which also proves their privileges. What only a database
proves: an entry's group, leg, order, recorded stops and anchor in one transaction, all or none
(a refused order, a refusing hook, a profile past the leg's version); the anchor's lookup under its
principal, its fingerprint compared in SQL and its outcome written once; the recorded stops'
settle; and the races, gated on `pg_stat_activity` lock waits and never on a fixed sleep: two first
persists of one key (an entry's and a reduce-only order's) and two stop requests on one position.
The DDL itself is test_order_submission_migration.py's.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from candleviewer.storage.repositories.idempotency_anchors import AnchorOutcome, NewAnchor
from candleviewer.storage.repositories.idempotency_anchors_sqlalchemy import (
    SqlAlchemyIdempotencyAnchorStore,
)
from candleviewer.storage.repositories.orders import (
    NewOrder,
    NewOrderEvent,
    OrderConstraintError,
)
from candleviewer.storage.repositories.recorded_stops import NewRecordedStop, StaleRecordedStop
from candleviewer.storage.repositories.recorded_stops_sqlalchemy import (
    SqlAlchemyRecordedStopStore,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.submissions import (
    AnchorTakenError,
    FirstPersist,
    FirstPersisted,
)
from candleviewer.storage.repositories.submissions_sqlalchemy import SqlAlchemySubmissionStore
from candleviewer.storage.repositories.trade_groups import (
    JsonObject,
    NewTradeGroup,
    NewTradeGroupLeg,
    TradeGroupStoreRefusedError,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP = _ROOT.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql"
_T0 = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
_SHA = "ab" * 32
_EVENT = NewOrderEvent(kind="local_create", source="local", event_ts=_T0)


def _login(dsn: str, role: str) -> str:
    return re.sub(r"://[^@]+@", f"://{role}:{role}_test_pw@", dsn)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """Superuser DSN of a database set up like production (test_trade_groups_store_pg.py)."""
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


def _user(dsn: str) -> uuid.UUID:
    uid = uuid.uuid4()
    _sql(
        dsn,
        "INSERT INTO users (id, email, username, password_hash, status) "
        "VALUES (%s, %s, %s, '$argon2id$x', 'active')",
        uid, f"{uid}@example.test", f"u{uid.hex[:12]}",
    )  # fmt: skip
    return uid


def _account(dsn: str) -> tuple[uuid.UUID, uuid.UUID]:
    """An account and its bootstrap profile (`trg_ea_default_profile`, version 1)."""
    account = uuid.uuid4()
    _sql(
        dsn,
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', 'demo', 'main', %s, %s)",
        account, str(account.int % 10**15), f"acct {account.hex[:8]}",
    )  # fmt: skip
    [(profile,)] = _sql(
        dsn,
        "SELECT id FROM account_profiles WHERE exchange_account_id = %s AND is_default",
        account,
    )
    return account, uuid.UUID(str(profile))


def _link() -> str:
    return f"cvd-0{uuid.uuid4().hex[:21]}-d0hb-00en"


def _entry(user: uuid.UUID, account: uuid.UUID, profile: uuid.UUID, **over: Any) -> tuple[
    FirstPersist, NewOrder
]:  # fmt: skip
    """An entry's first persist: a one-leg group, the order, its stop-loss and the anchor."""
    group_id, leg_id, order_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    ref = over.pop("ref", str(uuid.uuid4()))
    group = NewTradeGroup(
        id=group_id, client_group_ref=ref, client_body_sha256=_SHA, created_by=user, env="demo",
        symbol="BTCUSDT", side="Buy", status="submitting", leg_failure_policy="best_effort",
        algo="none", algo_params=None, intent_note=None, origin="manual", origin_rule_id=None,
        origin_rule_run_id=None, definition_id=None, requested_qty_mode="fixed_qty",
        requested_qty_value=Decimal("0.010"), entry_type="Market", entry_price=None,
        trigger_price=None, trigger_by=None, sl_price_hint=Decimal("62000"), tp_price_hint=None,
        is_paper=False,
    )  # fmt: skip
    snapshot: JsonObject = {"account_id": str(account), "profile_id": str(profile), "version": 1}
    leg = NewTradeGroupLeg(
        id=leg_id, exchange_account_id=account, account_profile_id=profile, profile_version=1,
        profile_snapshot=snapshot, status="pending", sequence_no=0, target_qty=Decimal("0.010"),
        resolved_leverage=Decimal("5"), resolved_sl_price=Decimal("62000"),
        resolved_tp_price=None, risk_usd=None, rejection_code=None, rejection_message=None,
    )  # fmt: skip
    order = NewOrder(
        id=order_id, exchange_account_id=account, order_link_id=over.pop("link", _link()),
        symbol="BTCUSDT", side="Buy", intent="entry", order_type="Market",
        qty=Decimal("0.010"), stop_loss=Decimal("62000"), state="pending_submit",
        lifecycle_state="validated", trade_group_leg_id=leg_id,
    )  # fmt: skip
    stop = NewRecordedStop(
        id=uuid.uuid4(), exchange_account_id=account, symbol="BTCUSDT", position_idx=0,
        position_side="Buy", kind="stop_loss", source="entry_attach", order_id=order_id,
        tpsl_mode="Full", trigger_price=Decimal("62000"), size=None,
        audit_record_id=uuid.uuid4(), actor_user_id=user,
    )  # fmt: skip
    anchor = NewAnchor(
        id=uuid.uuid4(), created_by=user, operation="placeOrder", client_ref=ref,
        request_sha256=_SHA, trade_group_id=group_id,
    )  # fmt: skip
    first = FirstPersist(anchor=anchor, group=group, legs=(leg,), recorded_stops=(stop,), **over)
    return first, order


def _reduce_only(user: uuid.UUID, account: uuid.UUID, ref: str, **over: Any) -> tuple[
    FirstPersist, NewOrder
]:  # fmt: skip
    order = NewOrder(
        id=uuid.uuid4(), exchange_account_id=account, order_link_id=_link(), symbol="BTCUSDT",
        side="Sell", intent="flatten", order_type="Market", qty=Decimal("0.010"),
        reduce_only=True, state="pending_submit", lifecycle_state="validated",
    )  # fmt: skip
    anchor = NewAnchor(
        id=uuid.uuid4(), created_by=user, operation="placeOrder", client_ref=ref,
        request_sha256=_SHA, order_id=order.id,
    )  # fmt: skip
    return FirstPersist(anchor=anchor, **over), order


def _held(dsn: str, first: FirstPersist, order: NewOrder) -> tuple[int, ...]:
    """How many of the persist's anchor, group, leg, order and stop rows exist."""
    [counts] = _sql(
        dsn,
        "SELECT (SELECT count(*) FROM idempotency_anchors WHERE id = %s), "
        "(SELECT count(*) FROM trade_groups WHERE id = %s), "
        "(SELECT count(*) FROM trade_group_legs WHERE id = ANY(%s)), "
        "(SELECT count(*) FROM orders WHERE id = %s), "
        "(SELECT count(*) FROM recorded_stops WHERE id = ANY(%s))",
        first.anchor.id, first.group.id if first.group else None,
        [leg.id for leg in first.legs], order.id, [s.id for s in first.recorded_stops],
    )  # fmt: skip
    return tuple(int(n) for n in counts)


@pytest_asyncio.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repo = SqlAlchemyRelationalRepository(_login(pg_dsn, "cv_app"), "order-submission-it")
    try:
        yield repo
    finally:
        await repo.dispose()


@asynccontextmanager
async def _racing(dsn: str, suffix: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    """A pool of its own, named `candleviewer:<suffix>` in `pg_stat_activity`."""
    repo = SqlAlchemyRelationalRepository(_login(dsn, "cv_app"), suffix)
    try:
        yield repo
    finally:
        await repo.dispose()


async def _wait_until_blocked(dsn: str, suffix: str) -> None:
    """Poll, as the superuser, until `candleviewer:<suffix>` waits on a heavyweight lock: at most
    1000 polls, 10 ms apart (test_trade_groups_store_pg.py's recipe)."""

    def blocked() -> bool:
        with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
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


async def _race(dsn: str, a: tuple[FirstPersist, NewOrder], b: tuple[FirstPersist, NewOrder]) -> (
    tuple[FirstPersisted, BaseException | FirstPersisted]
):  # fmt: skip
    """A's persist holds its transaction open in its hook; B's waits on A's uncommitted row; A
    commits; B's answer is returned beside A's."""
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold(persisted: FirstPersisted) -> None:
        entered.set()
        await release.wait()

    first = (dataclasses.replace(a[0], write_ahead=hold), a[1])
    async with (
        asyncio.timeout(20),
        _racing(dsn, "submit-race-a") as rel_a,
        _racing(dsn, "submit-race-b") as rel_b,
    ):
        store_a = SqlAlchemySubmissionStore(rel_a, statement_timeout_ms=15_000, audit_timeout_s=15)
        store_b = SqlAlchemySubmissionStore(rel_b, statement_timeout_ms=15_000)
        task_a = asyncio.create_task(store_a.create_first(*first, _EVENT))
        task_b: asyncio.Task[FirstPersisted] | None = None
        try:
            await entered.wait()
            task_b = asyncio.create_task(store_b.create_first(*b, _EVENT))
            await _wait_until_blocked(dsn, "submit-race-b")
            release.set()
            done_a = await task_a
            done_b = (await asyncio.gather(task_b, return_exceptions=True))[0]
        finally:
            release.set()
            for task in (task_a, task_b):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(task_a, *([task_b] if task_b else []), return_exceptions=True)
    return done_a, done_b


# -- the persist -----------------------------------------------------------------------------------


async def test_an_entry_persists_its_rows_together_and_its_anchor_answers_its_principal(
    rel: SqlAlchemyRelationalRepository, pg_dsn: str
) -> None:
    user, (account, profile) = _user(pg_dsn), _account(pg_dsn)
    first, order = _entry(user, account, profile)
    persisted = await SqlAlchemySubmissionStore(rel).create_first(first, order, _EVENT)
    assert _held(pg_dsn, first, order) == (1, 1, 1, 1, 1)
    assert persisted.order.provenance == "placed" and persisted.order.state == "pending_submit"
    assert persisted.recorded_stops[0].status == "pending"
    assert persisted.recorded_stops[0].trigger_price == Decimal("62000")
    anchors = SqlAlchemyIdempotencyAnchorStore(rel)
    found = await anchors.find(user, "placeOrder", first.anchor.client_ref, _SHA)
    assert found is not None and found.trade_group_id == first.anchor.trade_group_id
    assert found.body_matches and found.outcome_status is None
    other = await anchors.find(user, "placeOrder", first.anchor.client_ref, "cd" * 32)
    assert other is not None and not other.body_matches
    assert await anchors.find(_user(pg_dsn), "placeOrder", first.anchor.client_ref, _SHA) is None
    outcome = AnchorOutcome(status=502, code="exchange_error", ret_code=110007, decided_at=_T0)
    assert await anchors.record_outcome(first.anchor.id, outcome) is True
    accepted = AnchorOutcome(status=202, decided_at=_T0)
    assert await anchors.record_outcome(first.anchor.id, accepted) is False  # written once


@pytest.mark.parametrize("cause", ["taken link", "refusing hook", "profile moved on"])
async def test_a_refused_persist_leaves_no_row(
    rel: SqlAlchemyRelationalRepository, pg_dsn: str, cause: str
) -> None:
    user, (account, profile) = _user(pg_dsn), _account(pg_dsn)
    store = SqlAlchemySubmissionStore(rel)
    link = _link()
    first, order = _entry(user, account, profile, link=link)
    if cause == "taken link":
        await store.create_first(*_entry(user, account, profile, link=link), _EVENT)
        expected: type[BaseException] = OrderConstraintError
    elif cause == "refusing hook":

        async def refuse(persisted: FirstPersisted) -> None:
            raise RuntimeError("the audit trail refused the record")

        first = dataclasses.replace(first, write_ahead=refuse)
        expected = RuntimeError
    else:
        _sql(pg_dsn, "UPDATE account_profiles SET leverage = 3 WHERE id = %s", profile)
        expected = TradeGroupStoreRefusedError
    with pytest.raises(expected):
        await store.create_first(first, order, _EVENT)
    assert _held(pg_dsn, first, order) == (0, 0, 0, 0, 0)


async def test_two_first_persists_of_one_entry_key_store_one(pg_dsn: str) -> None:
    user, (account, profile) = _user(pg_dsn), _account(pg_dsn)
    ref = str(uuid.uuid4())
    a = _entry(user, account, profile, ref=ref)
    b = _entry(user, account, profile, ref=ref)
    done_a, done_b = await _race(pg_dsn, a, b)
    assert isinstance(done_b, AnchorTakenError) and done_b.constraint == "ux_tg_creator_ref"
    assert done_a.anchor_id == a[0].anchor.id
    assert _held(pg_dsn, *b) == (0, 0, 0, 0, 0)


async def test_two_first_persists_of_one_reduce_only_key_store_one(pg_dsn: str) -> None:
    user, (account, _) = _user(pg_dsn), _account(pg_dsn)
    ref = str(uuid.uuid4())
    done_a, done_b = await _race(
        pg_dsn, _reduce_only(user, account, ref), b := _reduce_only(user, account, ref)
    )
    assert isinstance(done_b, AnchorTakenError) and done_b.constraint == "ux_ia_principal_ref"
    assert done_a.group is None and _held(pg_dsn, *b) == (0, 0, 0, 0, 0)


async def test_two_stop_requests_on_one_position_leave_one_in_flight(pg_dsn: str) -> None:
    user, (account, profile) = _user(pg_dsn), _account(pg_dsn)
    done_a, done_b = await _race(
        pg_dsn, _entry(user, account, profile), b := _entry(user, account, profile)
    )
    assert isinstance(done_b, OrderConstraintError) and done_b.constraint == "ux_rs_in_flight"
    assert done_a.recorded_stops[0].answered_at is None and _held(pg_dsn, *b) == (0, 0, 0, 0, 0)


# -- the recorded stops ----------------------------------------------------------------------------


async def test_a_stop_request_is_settled_once_and_only_in_its_account(
    rel: SqlAlchemyRelationalRepository, pg_dsn: str
) -> None:
    user, (account, profile) = _user(pg_dsn), _account(pg_dsn)
    first, order = _entry(user, account, profile)
    await SqlAlchemySubmissionStore(rel).create_first(first, order, _EVENT)
    stops = SqlAlchemyRecordedStopStore(rel)
    [record] = [stop.id for stop in first.recorded_stops]
    with pytest.raises(StaleRecordedStop):
        await stops.settle(uuid.uuid4(), [record], "answered", at=_T0)  # another account's view
    [answered] = await stops.settle(account, [record], "answered", at=_T0)
    assert (answered.status, answered.answered_at) == ("pending", _T0)
    with pytest.raises(StaleRecordedStop):
        await stops.settle(account, [record], "refused", at=_T0)
    trading = NewRecordedStop(
        id=uuid.uuid4(), exchange_account_id=account, symbol="BTCUSDT", position_idx=0,
        position_side="Buy", kind="stop_loss", source="trading_stop", order_id=None,
        tpsl_mode="Full", trigger_price=Decimal("62500"), size=None,
        audit_record_id=uuid.uuid4(), actor_user_id=user, position_marker="m1",
    )  # fmt: skip
    [recorded] = await stops.insert([trading])
    [voided] = await stops.settle(account, [recorded.id], "not_shown", at=_T0)
    assert (voided.status, voided.answered_at, voided.closed_at) == ("void", None, _T0)
    assert [row.id for row in await stops.for_order(account, order.id)] == [record]
    assert await stops.for_order(uuid.uuid4(), order.id) == ()
