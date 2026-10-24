"""Integration: the first persist and the order-submission stores on real Postgres 16 (E29-T04
#913, revision `0043_order_submission`).

The database is set up like production (`pg_bootstrap.sql`'s roles, then the migrations as
`cv_owner`) and the stores run as `cv_app`, which also proves their privileges. What only a database
proves: an entry's group, leg, order, recorded stops and anchor in one transaction, all or none
(a refused order, a refusing hook, a profile past the leg's version); the anchor's lookup under its
principal, its fingerprint compared in SQL and its outcome written once; the recorded stops'
settle; and the races, gated on `pg_stat_activity` lock waits and never on a fixed sleep: two first
persists of one key (an entry's and a reduce-only order's), two stop requests on one position and
an end racing a put in force. The DDL itself is test_order_submission_migration.py's.
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
from collections.abc import AsyncIterator, Awaitable, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

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
    OrderTransition,
)
from candleviewer.storage.repositories.orders_sqlalchemy import SqlAlchemyOrderStore
from candleviewer.storage.repositories.recorded_stops import (
    EVERY_ACCOUNT,
    EndWriteAhead,
    NewRecordedStop,
    RecordedStopNotBindable,
    RecordedStopRow,
    StaleRecordedStop,
    SweptStop,
)
from candleviewer.storage.repositories.recorded_stops_sqlalchemy import (
    SqlAlchemyRecordedStopStore,
    end_statement,
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
from tests.unit.oms.submission_contract import audited, trading_stop

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
    noted: list[tuple[RecordedStopRow, ...]] = []

    async def audited(rows: tuple[RecordedStopRow, ...]) -> None:  # a void's write-ahead hook
        noted.append(rows)

    with pytest.raises(StaleRecordedStop):
        await stops.settle(account, [record], "refused", at=_T0, write_ahead=audited)
    trading = NewRecordedStop(
        id=uuid.uuid4(), exchange_account_id=account, symbol="BTCUSDT", position_idx=0,
        position_side="Buy", kind="stop_loss", source="trading_stop", order_id=None,
        tpsl_mode="Full", trigger_price=Decimal("62500"), size=None,
        audit_record_id=uuid.uuid4(), actor_user_id=user, position_marker="m1",
    )  # fmt: skip
    [recorded] = await stops.insert([trading])
    [voided] = await stops.settle(account, [recorded.id], "not_shown", at=_T0, write_ahead=audited)
    assert (voided.status, voided.answered_at, voided.closed_at) == ("void", None, _T0)
    assert noted == [(voided,)]  # the stale refusal wrote nothing, so audited nothing
    assert [row.id for row in await stops.for_order(account, order.id)] == [record]
    assert await stops.for_order(uuid.uuid4(), order.id) == ()


async def test_two_successors_race_for_one_binding_and_the_loser_writes_nothing(
    pg_dsn: str,
) -> None:
    """24 Sec.8.3 rule 7: A's pair holds the predecessor's row lock over its audit, B's pair waits
    for it at its lock-first statement, then its release finds the id already released and is
    refused, its own rows untouched."""
    # `at_a != at_b` is what lets this test see the release's compare-and-set. A release without
    # it would stamp the released row again: with a second timestamp `trg_rs_guard` refuses that
    # (`OrderConstraintError`, not the typed refusal); with the same one it changes nothing, the
    # trigger stays silent and never-two refuses B instead, so the test would still pass.
    account, xid, at_a, at_b = _account(pg_dsn)[0], "x-race", _T0, _T0 + timedelta(minutes=1)
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold(rows: tuple[RecordedStopRow, RecordedStopRow]) -> None:
        entered.set()
        await release.wait()

    async with (
        asyncio.timeout(20),
        _racing(pg_dsn, "bind-race-a") as rel_a,
        _racing(pg_dsn, "bind-race-b") as rel_b,
    ):
        a = SqlAlchemyRecordedStopStore(rel_a, statement_timeout_ms=15_000, audit_timeout_s=15)
        b = SqlAlchemyRecordedStopStore(rel_b, statement_timeout_ms=15_000)
        ids: list[uuid.UUID] = []
        for _ in range(3):  # a predecessor and two later rows, each answered before the next
            [stop] = await a.insert([trading_stop(account)])
            await a.settle(account, [stop.id], "answered", at=_T0)
            ids.append(stop.id)
        old, one, two = ids
        _sql(pg_dsn, "UPDATE recorded_stops SET exchange_order_id = %s WHERE id = %s", xid, old)
        task_a = asyncio.create_task(
            a.release_and_bind(account, old, one, xid, at=at_a, write_ahead=hold)
        )
        try:
            await entered.wait()
            task_b = asyncio.create_task(
                b.release_and_bind(account, old, two, xid, at=at_b, write_ahead=audited)
            )
            await _wait_until_blocked(pg_dsn, "bind-race-b")
            release.set()
            await task_a
            with pytest.raises(RecordedStopNotBindable):
                await task_b
        finally:
            release.set()
    rows = _sql(
        pg_dsn,
        "SELECT id, exchange_order_id, released_at FROM recorded_stops WHERE id = ANY(%s)",
        ids,
    )
    assert {row[0]: row[1:] for row in rows} == {
        old: (None, at_a),
        one: (xid, None),
        two: (None, None),
    }


@pytest.mark.parametrize("row_is", ["unanswered", "ended"])
async def test_an_end_past_its_pre_check_meets_trg_rs_guard_and_writes_nothing(
    rel: SqlAlchemyRelationalRepository, pg_dsn: str, row_is: str
) -> None:
    """21 Sec.3.3.11 "Guard": the table refuses what `check_end` keeps out, whatever a defect runs.
    A pending row never answered keeps its `status`; an ended row keeps its `closed_at`, so a
    second end's new time is refused."""
    account = _account(pg_dsn)[0]
    stops = SqlAlchemyRecordedStopStore(rel)
    [row] = await stops.insert([trading_stop(account)])
    if row_is == "ended":
        [row] = await stops.settle(account, [row.id], "answered", at=_T0)
        [row] = await stops.end(account, [row], at=_T0)
    with pytest.raises(OrderConstraintError) as err:
        async with stops._unit_of_work() as uow:  # the statement alone, as a defect would run it
            await uow.session.execute(end_statement(account, [row], _T0 + timedelta(seconds=1)))
    assert err.value.constraint == "trg_rs_guard"
    stored = _sql(pg_dsn, "SELECT status, closed_at FROM recorded_stops WHERE id = %s", row.id)
    assert stored == [(row.status, row.closed_at)]


@pytest.mark.parametrize("first", ["put_in_force", "end"])
async def test_an_end_and_a_put_in_force_racing_on_one_key_one_commits_and_the_other_is_stale(
    pg_dsn: str, first: str
) -> None:
    """21 Sec.3.3.11: one key holds a row in force and a younger answered row. The first writer
    holds its rows over its audit; the second waits for them, then finds its rows moved
    (`StaleRecordedStop`) and writes nothing: `at_a != at_b` shows its time written nowhere. A put
    in force that wins replaces the row in force, so the end finds it moved; an end that wins
    closes both, so the put finds no live row to lock."""
    account, at_a, at_b = _account(pg_dsn)[0], _T0 + timedelta(hours=1), _T0 + timedelta(hours=2)
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold(rows: tuple[RecordedStopRow, ...]) -> None:
        entered.set()
        await release.wait()

    async with (
        asyncio.timeout(20),
        _racing(pg_dsn, "end-race-a") as rel_a,
        _racing(pg_dsn, "end-race-b") as rel_b,
    ):
        a = SqlAlchemyRecordedStopStore(rel_a, statement_timeout_ms=15_000, audit_timeout_s=15)
        b = SqlAlchemyRecordedStopStore(rel_b, statement_timeout_ms=15_000)
        [old] = await a.insert([trading_stop(account)])
        [old] = await a.settle(account, [old.id], "answered", at=_T0)
        [old] = (await a.put_in_force(account, [old], at=_T0)).in_force
        [new] = await a.insert([trading_stop(account)])
        [new] = await a.settle(account, [new.id], "answered", at=_T0)

        def write(
            store: SqlAlchemyRecordedStopStore, op: str, at: datetime, hook: EndWriteAhead | None
        ) -> Awaitable[object]:
            if op == "end":
                return store.end(account, [old, new], at=at, write_ahead=hook)
            return store.put_in_force(account, [new], at=at, write_ahead=hook)

        task_a = asyncio.ensure_future(write(a, first, at_a, hold))
        try:
            await entered.wait()
            second = "end" if first == "put_in_force" else "put_in_force"
            task_b = asyncio.ensure_future(write(b, second, at_b, None))
            await _wait_until_blocked(pg_dsn, "end-race-b")
            release.set()
            await task_a
            with pytest.raises(StaleRecordedStop):
                await task_b
        finally:
            release.set()
    rows = _sql(
        pg_dsn,
        "SELECT id, status, in_force_at, closed_at FROM recorded_stops WHERE id = ANY(%s)",
        [old.id, new.id],
    )
    expected: dict[uuid.UUID, tuple[Any, ...]] = {
        old.id: ("ended", _T0, at_a),
        new.id: ("ended", None, at_a),
    }
    if first == "put_in_force":
        expected = {old.id: ("replaced", _T0, at_a), new.id: ("in_force", at_a, None)}
    assert {row[0]: row[1:] for row in rows} == expected


# -- E29-T04 commit 4: the order step's settle and the startup sweep -------------------------------


def _stops_of(dsn: str, first: FirstPersist) -> list[tuple[str, bool, bool]]:
    """(status, answered, closed) of the persist's recorded stops."""
    rows = _sql(
        dsn,
        "SELECT status, answered_at IS NOT NULL, closed_at IS NOT NULL FROM recorded_stops "
        "WHERE id = ANY(%s) ORDER BY id",
        [stop.id for stop in first.recorded_stops],
    )
    return [(str(status), bool(answered), bool(closed)) for status, answered, closed in rows]


def _move(order: NewOrder, frm: Any, to: Any, chart: Any, **over: Any) -> OrderTransition:
    said = {"retCode": 0} if to != "rejected" else {"retCode": 10006}
    event = NewOrderEvent(
        kind=over.pop("kind", "ack"), source="rest", event_ts=_T0, payload=said,
        ret_code=over.get("reject_code"),
    )  # fmt: skip
    return OrderTransition(
        account_id=order.exchange_account_id, order_id=order.id, from_state=frm, to_state=to,
        event=event, lifecycle_state=chart, **over,
    )  # fmt: skip


async def test_the_order_step_settles_its_entry_stops_in_its_own_transaction(
    rel: SqlAlchemyRelationalRepository, pg_dsn: str
) -> None:
    """R10: the ack answers the entry's stop request; a refused entry voids it. The send's step
    counts its attempt and marks the create in flight."""
    user, store = _user(pg_dsn), SqlAlchemyOrderStore(rel)
    answered, refused = _entry(user, *_account(pg_dsn)), _entry(user, *_account(pg_dsn))
    for first, order in (answered, refused):
        await SqlAlchemySubmissionStore(rel).create_first(first, order, _EVENT)
        send = _move(order, "pending_submit", "submitted", "submitting", kind="submit_attempt",
                     bump_submit_attempts=True, idempotency_state="in_flight")  # fmt: skip
        sent = (await store.transition(send)).order
        assert (sent.submit_attempts, sent.idempotency_state) == (1, "in_flight")
    order = answered[1]
    ack = _move(order, "submitted", "accepted", "submitted", idempotency_state="acked",
                entry_stops="answered")  # fmt: skip
    assert (await store.transition(ack)).order.idempotency_state == "acked"
    assert _stops_of(pg_dsn, answered[0]) == [("pending", True, False)]
    order = refused[1]
    nack = _move(order, "submitted", "rejected", "rejected", kind="reject",
                 reject_code="10006", idempotency_state="failed", entry_stops="void")  # fmt: skip
    assert (await store.transition(nack)).order.idempotency_state == "failed"
    assert _stops_of(pg_dsn, refused[0]) == [("void", False, True)]


def _end(dsn: str, order: NewOrder, state: str, filled: str = "0") -> None:
    """The row as a writer that bypassed the step's settle would leave it (superuser)."""
    _sql(
        dsn,
        "UPDATE orders SET state = %s::order_state, lifecycle_state = %s::order_lifecycle_state, "
        "cum_exec_qty = %s::numeric WHERE id = %s",
        state, state, filled, order.id,
    )  # fmt: skip


async def _sent(store: SqlAlchemyOrderStore, order: NewOrder) -> None:
    """The send's step as the step writer commits it: the create in flight, one attempt."""
    send = _move(order, "pending_submit", "submitted", "submitting", kind="submit_attempt",
                 bump_submit_attempts=True, idempotency_state="in_flight")  # fmt: skip
    await store.transition(send)


async def test_a_void_never_meets_a_fill_the_store_holds(
    rel: SqlAlchemyRelationalRepository, pg_dsn: str
) -> None:
    """SEC-2A-01: whatever the step decided, its void leaves the rows of an order that holds a
    recorded fill pending, the store's own check run after the step's update, in its transaction."""
    store = SqlAlchemyOrderStore(rel)
    first, order = _entry(_user(pg_dsn), *_account(pg_dsn))
    await SqlAlchemySubmissionStore(rel).create_first(first, order, _EVENT)
    await _sent(store, order)
    _end(pg_dsn, order, "partially_filled", "0.004")
    end = _move(order, "partially_filled", "cancelled", "cancelled", kind="exchange_push",
                entry_stops="void")  # fmt: skip
    assert (await store.transition(end)).order.state == "cancelled"
    assert _stops_of(pg_dsn, first) == [("pending", False, False)]


#: The sweep's cases (the 2026-10-21 ruling, the rulings of 14:26Z): the first three were never
#: placed and are swept; the rest wait for the complete read, or stay an order's that lives or
#: filled.
_SWEPT_CASES: Final = ("never_sent", "refused", "killed_unsent")
_KEPT_CASES: Final = (
    "killed_sent", "unknown_rejected", "cancelled_unfilled", "live", "filled",
)  # fmt: skip


async def test_the_startup_sweep_voids_only_the_stops_of_an_entry_never_placed(
    rel: SqlAlchemyRelationalRepository, pg_dsn: str
) -> None:
    """Never sent (still `pending_submit`, or killed before its send), or refused by its create's
    own answer (its event into `rejected` out of `submitting`), the step's settle bypassed here:
    swept. A KILL after the send, a rejection out of `unknown`, an end the sweep cannot see
    confirmed unfilled, a live and a filled entry's: left as they are, never voided blind (C-2.6).
    Each voided row is audited before the commit, and a refused audit voids nothing."""
    user, store = _user(pg_dsn), SqlAlchemyOrderStore(rel)
    cases = {name: _entry(user, *_account(pg_dsn)) for name in _SWEPT_CASES + _KEPT_CASES}
    for first, order in cases.values():
        await SqlAlchemySubmissionStore(rel).create_first(first, order, _EVENT)
    for name in ("refused", "killed_sent", "unknown_rejected", "cancelled_unfilled", "live",
                 "filled"):  # fmt: skip
        await _sent(store, cases[name][1])
    order = cases["refused"][1]
    await store.transition(_move(order, "submitted", "rejected", "rejected", kind="reject",
                                 reject_code="10006", idempotency_state="failed"))  # fmt: skip
    _end(pg_dsn, cases["killed_unsent"][1], "killed")
    _end(pg_dsn, cases["killed_sent"][1], "killed")
    order = cases["unknown_rejected"][1]
    _end(pg_dsn, order, "unknown")
    await store.transition(_move(order, "unknown", "rejected", "rejected", kind="reject",
                                 reject_code="UNRESOLVED", idempotency_state="failed"))  # fmt: skip
    _end(pg_dsn, cases["cancelled_unfilled"][1], "cancelled")
    _sql(pg_dsn, "UPDATE orders SET state = 'accepted', lifecycle_state = 'submitted' "
         "WHERE id = %s", cases["live"][1].id)  # fmt: skip
    _end(pg_dsn, cases["filled"][1], "filled", "0.010")
    stops = SqlAlchemyRecordedStopStore(rel)

    async def refuse(swept: tuple[SweptStop, ...]) -> None:
        raise RuntimeError("the audit trail refused the record")

    with pytest.raises(RuntimeError):
        await stops.void_orphans(EVERY_ACCOUNT, at=_T0, write_ahead=refuse)
    assert all(
        _stops_of(pg_dsn, first) == [("pending", False, False)] for first, _ in cases.values()
    )
    audited: list[SweptStop] = []

    async def audit(swept: tuple[SweptStop, ...]) -> None:
        audited.extend(swept)

    swept = await stops.void_orphans(EVERY_ACCOUNT, at=_T0, write_ahead=audit)
    ids = {stop.id for stop in swept}
    unplaced = {s.id for n in _SWEPT_CASES for s in cases[n][0].recorded_stops}
    kept = {s.id for n in _KEPT_CASES for s in cases[n][0].recorded_stops}
    assert unplaced <= ids and not kept & ids and list(swept) == audited
    for name in _SWEPT_CASES:
        assert _stops_of(pg_dsn, cases[name][0]) == [("void", False, True)], name
    for name in _KEPT_CASES:
        assert _stops_of(pg_dsn, cases[name][0]) == [("pending", False, False)], name
