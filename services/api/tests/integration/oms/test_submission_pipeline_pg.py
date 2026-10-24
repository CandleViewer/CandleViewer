"""Integration: the submission pipeline's Gherkin scenarios on real Postgres 16 (E29-T04 #913,
slice 2b).

`OrderSubmission` runs over the real B1 facade, its step writer and the command port, with every
store a Postgres adapter: `cv_app` on a database set up like production (`pg_bootstrap.sql`'s
roles, then the migrations as `cv_owner`), and the effective profile read through the real
`EffectiveProfiles`. The exchange is a `FakeTradingPort` (C-13.5: no venue is reached). Each
scenario of the ticket's Gherkin asserts its rows, its audit records, each carrying the request's
correlation id ([AUDIT-REQUEST-ID]), and its exchange calls: the happy path, the filters, the
missing stop, the transport failure, the replay after a restart, the store that cannot record,
the retry that reuses its id, and the persist-time collision (Gherkin 9), with the two concurrent
submits of one key and the Q4 race on one position. A race is gated on a `pg_stat_activity` lock
wait, as the 2a suites gate theirs, and a wait the pipeline makes is recorded, never slept
(`Sleeps`). The audit writer and the notice route are recording doubles, as their real bindings
are slice 3's.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import sys
import uuid
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any, Final

import psycopg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

from candleviewer.accounts.profile_cache import EffectiveProfiles
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.accounts.trade_group_repository import TradeGroupRepository
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, GroupId, Px, Side
from candleviewer.exchange.base.fakes import FakeTradingPort, LandedThenAmbiguous
from candleviewer.exchange.base.models import AccountRef, PlaceOrderRequest
from candleviewer.observability.metrics import Metrics
from candleviewer.oms import submit as pipeline_module
from candleviewer.oms.clock_halt import ClockHalt
from candleviewer.oms.commands import OmsCommandPort
from candleviewer.oms.errors import (
    IdempotencyInFlight,
    OmsError,
    OrderInvalid,
    OrderLinkIdExhausted,
    StopRequestPending,
    StoreUnavailable,
    TickSizeViolation,
    problem_for,
)
from candleviewer.oms.fakes import FakeClockHealth, InMemoryTradingAccounts
from candleviewer.oms.idempotency import AnchorService
from candleviewer.oms.order_link import OrderLinkIdParts
from candleviewer.oms.order_link_allocator import OrderLinkIdAllocator
from candleviewer.oms.order_machine import OrderMachinePorts, OrderMachines
from candleviewer.oms.order_steps import OrderStepWriter
from candleviewer.oms.ports import (
    InterimStopResolver,
    KeyedRecord,
    OrderEffect,
    RequestRecord,
    StopOffset,
    SubmissionPorts,
    SubmitActor,
)
from candleviewer.oms.repository import (
    ExecutionRepository,
    IdempotencyAnchorRepository,
    OrderEventRepository,
    OrderRepository,
    RecordedStopRepository,
    SubmissionRepository,
)
from candleviewer.oms.routing import TradingRouter
from candleviewer.oms.submit import (
    OrderRequest,
    OrderSubmission,
    SubmissionDeps,
    SubmitContext,
    SubmitOutcome,
)
from candleviewer.oms.validator import Validator
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.config import CV_COMMAND_TIMEOUT, CV_PERSIST_TIMEOUT
from candleviewer.statechart.plugins import InMemoryMachineEventSink
from candleviewer.storage.repositories.account_profiles_sqlalchemy import (
    SqlAlchemyAccountProfileStore,
)
from candleviewer.storage.repositories.executions_sqlalchemy import SqlAlchemyExecutionStore
from candleviewer.storage.repositories.idempotency_anchors_sqlalchemy import (
    SqlAlchemyIdempotencyAnchorStore,
)
from candleviewer.storage.repositories.orders_sqlalchemy import SqlAlchemyOrderStore
from candleviewer.storage.repositories.recorded_stops_sqlalchemy import (
    SqlAlchemyRecordedStopStore,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.submissions_sqlalchemy import SqlAlchemySubmissionStore
from candleviewer.storage.repositories.trade_groups_sqlalchemy import SqlAlchemyTradeGroupStore
from tests.unit.oms import command_rig as cr
from tests.unit.oms.order_rig import Notices, Pager, Publish
from tests.unit.oms.submit_rig import (
    REGISTRY,
    SHA,
    STOP,
    SYMBOL,
    TAKE_PROFIT,
    Instruments,
    Prices,
    ReadOnly,
    Sleeps,
    entry,
    instrument,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_BOOTSTRAP = _ROOT.parents[1] / "infra" / "scripts" / "pg_bootstrap.sql"
#: The pipeline's pool, `candleviewer:<this>` in `pg_stat_activity`, where a race is gated.
_APP: Final = "submission-pipeline-it"
#: The second symbol the profile allows: an entry on another position than `SYMBOL`'s.
_OTHER: Final = "ETHUSDT"
#: The correlation ids of two concurrent requests (`X-Correlation-Id`, [AUDIT-REQUEST-ID]).
_FIRST: Final = uuid.UUID("6f1d2c3b-4a59-4e68-8f7a-9b0c1d2e3f40")
_SECOND: Final = uuid.UUID("7a2e3d4c-5b6a-4f79-8a8b-0c1d2e3f4a51")
#: How long a race may hold its first persist open: the step's write and the store's statement
#: and hook bounds are widened to it, so the race's own lock wait is the only wait.
_RACE_BOUND_S: Final = 15.0
#: How long a create a restart resumes may take to leave `submitting`: B1 bounds its attempt (the
#: lookups and the one create) by `CV_COMMAND_TIMEOUT` and its step's write by
#: `CV_PERSIST_TIMEOUT`. The wait ends at that step, so the bound only turns a hang into a failure.
_RESUME_BOUND_S: Final = CV_COMMAND_TIMEOUT + CV_PERSIST_TIMEOUT


def _login(dsn: str, role: str) -> str:
    return re.sub(r"://[^@]+@", f"://{role}:{role}_test_pw@", dsn)


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    """Superuser DSN of a database set up like production (test_order_submission_pg.py)."""
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


@pytest.fixture
def stopped_dsn() -> str:
    """The DSN of a Postgres 16 that was started, then stopped: nothing answers at its port."""
    container = PostgresContainer("postgres:16-alpine", dbname="candleviewer")
    container.start()
    try:
        return container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
    finally:
        container.stop()


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


def _uid(account: uuid.UUID) -> str:
    return str(account.int % 10**15)


def _trading_account(dsn: str) -> AccountId:
    """A demo account whose default profile (`trg_ea_default_profile`) is made to trade the two
    symbols (D11): `fixed_qty`, its caps set (`ap_trading_caps`), its stop offset the default
    10 ticks. The edit moves the profile to version 2, which the leg then records."""
    account = uuid.uuid4()
    _sql(
        dsn,
        "INSERT INTO exchange_accounts (id, exchange, env, kind, exchange_uid, label) "
        "VALUES (%s, 'bybit', 'demo', 'main', %s, %s)",
        account, _uid(account), f"acct {account.hex[:8]}",
    )  # fmt: skip
    _sql(
        dsn,
        "UPDATE account_profiles SET trading_enabled = true, sizing_mode = 'fixed_qty', "
        "size_fixed_qty = 0.01, risk_pct_equity = NULL, leverage = 10, max_leverage_cap = 10, "
        "max_position_notional_usd = 20000, max_daily_loss_usd = 500, max_open_positions = 1, "
        "max_concurrent_orders = 5, allowed_symbols = ARRAY['BTCUSDT', 'ETHUSDT'] "
        "WHERE exchange_account_id = %s AND is_default",
        account,
    )
    return AccountId(account)


def _db_now(dsn: str) -> datetime:
    [(now,)] = _sql(dsn, "SELECT clock_timestamp()")
    assert isinstance(now, datetime) and now.tzinfo is not None
    return now


def _held(dsn: str, account: uuid.UUID, user: uuid.UUID) -> tuple[int, ...]:
    """The account's orders, the principal's anchors and groups, and the account's legs and
    recorded stops."""
    [counts] = _sql(
        dsn,
        "SELECT (SELECT count(*) FROM orders WHERE exchange_account_id = %s), "
        "(SELECT count(*) FROM idempotency_anchors WHERE created_by = %s), "
        "(SELECT count(*) FROM trade_groups WHERE created_by = %s), "
        "(SELECT count(*) FROM trade_group_legs WHERE exchange_account_id = %s), "
        "(SELECT count(*) FROM recorded_stops WHERE exchange_account_id = %s)",
        account, user, user, account, account,
    )  # fmt: skip
    return tuple(int(n) for n in counts)


@dataclass(frozen=True, slots=True)
class _Row:
    """An `orders` row as the scenarios read it."""

    lifecycle_state: str
    state: str
    order_link_id: str
    stop_loss: Decimal | None
    take_profit: Decimal | None
    cum_exec_qty: Decimal
    submit_attempts: int
    idempotency_state: str | None
    exchange_order_id: str | None


def _order(dsn: str, order_id: uuid.UUID) -> _Row:
    [row] = _sql(
        dsn,
        "SELECT lifecycle_state::text, state::text, order_link_id, stop_loss, take_profit, "
        "cum_exec_qty, submit_attempts, idempotency_state::text, exchange_order_id "
        "FROM orders WHERE id = %s",
        order_id,
    )
    return _Row(*row)


def _orders(dsn: str, account: uuid.UUID) -> list[tuple[uuid.UUID, str, str]]:
    """(id, `order_link_id`, lifecycle state) of the account's orders, oldest first."""
    rows = _sql(
        dsn,
        "SELECT id, order_link_id, lifecycle_state::text FROM orders "
        "WHERE exchange_account_id = %s ORDER BY created_ts, id",
        account,
    )
    return [(uuid.UUID(str(i)), str(link), str(state)) for i, link, state in rows]


def _events(dsn: str, order_id: uuid.UUID) -> list[str]:
    """The `to_state` of each of the order's events, in `seq` order (24 Sec.8.2's write-ahead)."""
    rows = _sql(
        dsn, "SELECT to_state::text FROM order_events WHERE order_id = %s ORDER BY seq", order_id
    )
    return [str(to_state) for (to_state,) in rows]


def _anchor(dsn: str, anchor_id: uuid.UUID) -> tuple[int | None, str | None]:
    [(status, code)] = _sql(
        dsn, "SELECT outcome_status, outcome_code FROM idempotency_anchors WHERE id = %s", anchor_id
    )
    return status, code


def _stops(dsn: str, order_id: uuid.UUID) -> list[tuple[str, str, bool]]:
    """(kind, status, answered) of the order's recorded stops."""
    rows = _sql(
        dsn,
        "SELECT kind::text, status::text, answered_at IS NOT NULL FROM recorded_stops "
        "WHERE order_id = %s ORDER BY kind",
        order_id,
    )
    return [(str(kind), str(status), bool(answered)) for kind, status, answered in rows]


def _group(dsn: str, group_id: uuid.UUID) -> tuple[str, list[str]]:
    """The group's status and its legs'."""
    [(status,)] = _sql(dsn, "SELECT status::text FROM trade_groups WHERE id = %s", group_id)
    legs = _sql(
        dsn, "SELECT status::text FROM trade_group_legs WHERE trade_group_id = %s", group_id
    )
    return str(status), [str(leg) for (leg,) in legs]


def _fills(dsn: str, order_id: uuid.UUID) -> int:
    [(n,)] = _sql(dsn, "SELECT count(*) FROM executions WHERE order_id = %s", order_id)
    return int(n)


async def _wait_until_blocked(dsn: str) -> None:
    """Poll, as the superuser, until a connection of the pipeline's pool waits on a heavyweight
    lock: at most 1000 polls, 10 ms apart (test_order_submission_pg.py's recipe)."""

    def blocked() -> bool:
        with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True) as c:
            for _ in range(1000):
                row = c.execute(
                    "SELECT count(*) FROM pg_stat_activity WHERE application_name = %s "
                    "AND wait_event_type = 'Lock'",
                    (f"candleviewer:{_APP}",),
                ).fetchone()
                if row is not None and row[0] > 0:
                    return True
                c.execute("SELECT pg_sleep(0.01)")
        return False

    assert await asyncio.to_thread(blocked), f"candleviewer:{_APP} never waited on a lock"


@contextmanager
def _orders_locked(dsn: str) -> Iterator[None]:
    """`orders` held in ACCESS EXCLUSIVE mode by an open transaction of the superuser, so every
    read of it waits: a store that hangs."""
    with psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql")) as c:
        c.execute("LOCK TABLE orders IN ACCESS EXCLUSIVE MODE")
        try:
            yield
        finally:
            c.rollback()


# -- the doubles around the stores ----------------------------------------------------------------


@dataclass
class Clock:
    """The app's clock, started at the database's own time, as `now()` stamps the anchors and the
    stop requests (21 Sec.3.3.10, Sec.3.3.11): a test moves it, never sleeps."""

    at: datetime

    def __call__(self) -> datetime:
        return self.at

    def us(self) -> int:
        return (self.at - cr.EPOCH) // timedelta(microseconds=1)

    def advance(self, seconds: float) -> None:
        self.at += timedelta(seconds=seconds)


@dataclass
class Holding(cr.Audits):
    """`cr.Audits` that can hold its next write (`hold`): the write-ahead hook of a first persist
    then keeps that persist's transaction open, its rows uncommitted, until `release`."""

    armed: bool = False
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    released: asyncio.Event = field(default_factory=asyncio.Event)

    def hold(self) -> None:
        self.armed = True
        self.entered.clear()
        self.released.clear()

    async def write(self, record: cr.AnyRecord) -> None:
        if self.armed:
            self.armed = False
            self.entered.set()
            await self.released.wait()
        await super().write(record)

    def of(self, request_id: uuid.UUID | None) -> list[cr.AnyRecord]:
        return [record for record, _ in self.written if record.request_id == request_id]


class Lookup:
    """The allocator's `OrderLinkLookup` over the order store, recording every id it is asked
    about; `lies` answers "free" whatever the index holds (24 Sec.8.3 rule 5's lookup that
    disagrees with it)."""

    def __init__(self, orders: OrderRepository, *, lies: bool = False) -> None:
        self._orders = orders
        self.lies = lies
        self.asked: list[str] = []

    async def exists(self, order_link_id: str) -> bool:
        self.asked.append(order_link_id)
        return False if self.lies else await self._orders.exists(order_link_id)


class NoProfileOffset(InterimStopResolver):
    """The interim resolver for a profile that defines no SL offset: a stop the request does not
    name resolves to none. The schema keeps an offset on every profile (`ap_sl_pos`), so the
    Gherkin's profile is the resolver's answer, which the guard judges whatever the port is (R4,
    C-2.6)."""

    def resolve(
        self,
        stop: StopOffset | None,
        *,
        side: Side,
        reference_price: Px,
        effect: OrderEffect,
        instrument: Instrument,
        profile: AccountProfile | None,
    ) -> Px | None:
        if stop is None:
            return None
        return super().resolve(
            stop,
            side=side,
            reference_price=reference_price,
            effect=effect,
            instrument=instrument,
            profile=profile,
        )


class OneCandidate:
    """`OrderLinkIdParts` for the pipeline, every candidate named from one group: two requests of
    one account allocate the same id, as two allocations that raced to one do (24 Sec.8.3
    rule 5)."""

    group = GroupId(uuid.UUID("2d4c6e8a-0b1d-4f3e-9a5c-7e9b1d3f5a70"))

    @classmethod
    def generate(cls, **parts: Any) -> OrderLinkIdParts:
        return OrderLinkIdParts.generate(**(parts | {"group_id": cls.group}))


# -- one process: the pipeline, B1's facade and the command port over Postgres --------------------


@dataclass
class Rig:
    """One process's pipeline over the Postgres stores (`_build`)."""

    pipeline: OrderSubmission
    machines: OrderMachines
    demo: FakeTradingPort
    audits: Holding
    notices: Notices
    lookup: Lookup
    sleeps: Sleeps
    clock: Clock
    account: AccountId
    user: uuid.UUID
    #: Another pipeline over the same parts, with other keywords.
    make: Callable[..., OrderSubmission]

    def ref(self) -> AccountRef:
        return AccountRef(
            account_id=self.account, uid=_uid(self.account), environment="demo",
            key_ref=cr.KEYS["demo"],
        )  # fmt: skip

    def entry(self, **over: Any) -> OrderRequest:
        return entry(**({"account_id": self.account} | over))

    def context(self, **over: Any) -> SubmitContext:
        actor = SubmitActor(
            user_id=self.user, role="owner", session_id=uuid.uuid4(), ip="100.64.0.7"
        )
        base = SubmitContext(
            actor=actor, client_ref=uuid.uuid4(), request_sha256=SHA, request_id=_FIRST
        )
        return replace(base, **over)

    async def submit(
        self, request: OrderRequest | None = None, context: SubmitContext | None = None
    ) -> SubmitOutcome:
        return await self.pipeline.submit(request or self.entry(), context or self.context())

    def calls(self) -> list[str]:
        return [call.method for call in self.demo.calls]

    def creates(self) -> list[PlaceOrderRequest]:
        sent = [call.request for call in self.demo.calls if call.method == "place_order"]
        assert all(isinstance(create, PlaceOrderRequest) for create in sent)
        return [create for create in sent if isinstance(create, PlaceOrderRequest)]

    async def settle(self) -> None:
        """Until the facade's turns settled every step an invoke's answer brought. An invoke still
        in flight runs in B1's own task, which `idle` does not wait on: one that reads or writes
        Postgres before it answers is waited for by its step (`machines.settled`)."""
        for _ in range(4):
            for _ in range(32):
                await asyncio.sleep(0)
            await self.machines.idle()


def _build(
    rel: SqlAlchemyRelationalRepository,
    *,
    account: AccountId,
    user: uuid.UUID,
    clock: Clock,
    demo: FakeTradingPort | None = None,
    race: bool = False,
    ports: SubmissionPorts | None = None,
) -> Rig:
    """The pipeline, B1's facade and the command port over the Postgres stores on `rel`, the
    exchange `demo` (a new one by default). `race` widens the first persist's statement and hook
    bounds to `_RACE_BOUND_S`, so a held persist outlasts the lock wait it causes."""
    orders_store = SqlAlchemyOrderStore(rel)
    orders, events = OrderRepository(orders_store), OrderEventRepository(orders_store)
    stops = RecordedStopRepository(SqlAlchemyRecordedStopStore(rel))
    bounds: Mapping[str, Any] = (
        {"statement_timeout_ms": int(_RACE_BOUND_S * 1000), "audit_timeout_s": _RACE_BOUND_S}
        if race
        else {}
    )
    submissions = SubmissionRepository(SqlAlchemySubmissionStore(rel, **bounds))
    venue = demo if demo is not None else FakeTradingPort(environment="demo", now_us=clock.us)
    live = FakeTradingPort(environment="live", now_us=clock.us)
    accounts = InMemoryTradingAccounts(
        AccountRef(account_id=account, uid=_uid(account), environment="demo",
                   key_ref=cr.KEYS["demo"]),
    )  # fmt: skip
    audits = Holding(sent=lambda: len(venue.calls))
    switches, notices, pager = cr.Switches(), Notices(), Pager()
    monotonic, metrics = cr.Monotonic(), Metrics("dev")  # one registry, the process's
    health = FakeClockHealth(monotonic)
    health.measure()
    halt = ClockHalt(health, monotonic=monotonic, metrics=metrics)
    router = TradingRouter({"demo": venue, "live": live}, lane_waits=cr.LANE_WAITS)
    gate = cr.stop_gate(stops, orders, audits, accounts, router, clock, monotonic, metrics)
    commands = OmsCommandPort(
        router=router, accounts=accounts, orders=orders, stops=stops, handovers=cr.Handovers(),
        credentials=cr.Credentials(), clock_halt=halt, switches=switches, audit=audits,
        submit_audit=audits, gate=gate, notices=notices, now_us=clock.us,
    )  # fmt: skip
    writer = OrderStepWriter(
        orders,
        ExecutionRepository(SqlAlchemyExecutionStore(rel)),
        clock=clock,
        submissions=submissions,
    )
    machines = OrderMachines(
        OrderMachinePorts(
            writer, orders, commands, audits, Publish(), notices, InMemoryMachineEventSink(),
            events,
        ),
        metrics=metrics, pager=pager, now_us=clock.us, registry=REGISTRY,
    )  # fmt: skip
    deps = SubmissionDeps(
        accounts=accounts,
        instruments=Instruments(
            listed={SYMBOL: instrument(), _OTHER: instrument(symbol=_OTHER, base_coin="ETH")}
        ),
        prices=Prices(),
        profiles=EffectiveProfiles(SqlAlchemyAccountProfileStore(rel)),
        switches=switches,
        gate=gate,
        audit=audits,
        groups=TradeGroupRepository(SqlAlchemyTradeGroupStore(rel)),
    )
    lookup, sleeps = Lookup(orders), Sleeps()
    make = partial(
        OrderSubmission,
        ports=ports if ports is not None else SubmissionPorts.interim(now=clock),
        deps=deps,
        machines=machines,
        commands=commands,
        allocator=OrderLinkIdAllocator(lookup),
        validator=Validator(read_only_gate=ReadOnly()),
        router=router,
        anchors=AnchorService(IdempotencyAnchorRepository(
            SqlAlchemyIdempotencyAnchorStore(rel)), clock=clock, timeout_s=2.0),
        clock_halt=halt,
        metrics=metrics,
        now=clock,
        monotonic=monotonic,
        sleep=sleeps,
        pager=pager,
    )  # fmt: skip
    return Rig(make(), machines, venue, audits, notices, lookup, sleeps, clock, account, user, make)


@pytest_asyncio.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repo = SqlAlchemyRelationalRepository(_login(pg_dsn, "cv_app"), _APP)
    try:
        yield repo
    finally:
        await repo.dispose()


@pytest_asyncio.fixture
async def pg(
    rel: SqlAlchemyRelationalRepository, pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Rig]:
    """A fresh account and principal, and one process over them; B1's command attempts its own
    (one facade per process)."""
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    rig = _build(
        rel, account=_trading_account(pg_dsn), user=_user(pg_dsn), clock=Clock(_db_now(pg_dsn))
    )
    try:
        yield rig
    finally:
        await rig.machines.stop()


async def _restart(rig: Rig, rel: SqlAlchemyRelationalRepository) -> Rig:
    """A crash and a restart: the facade stops, the binding's attempts go with the process's
    memory, and a new process runs over the same database, account and venue."""
    await rig.machines.stop()
    b01._ATTEMPTS.clear()
    return _build(rel, account=rig.account, user=rig.user, clock=rig.clock, demo=rig.demo)


async def _refused(
    rig: Rig, request: OrderRequest | None = None, context: SubmitContext | None = None
) -> OmsError:
    with pytest.raises(OmsError) as refused:
        await rig.submit(request, context)
    return refused.value


def _denied(rig: Rig, request_id: uuid.UUID | None = _FIRST) -> list[RequestRecord]:
    return [
        record for record in rig.audits.of(request_id)
        if isinstance(record, RequestRecord) and record.outcome == "denied"
    ]  # fmt: skip


@pytest_asyncio.fixture
async def racing(
    rel: SqlAlchemyRelationalRepository, pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Rig]:
    """`pg` for a race: the first persist's bounds (B1's step write, the store's statement and its
    hook) widened to `_RACE_BOUND_S`, so a persist the race holds open outlasts the lock wait it
    causes, and that wait is the only one."""
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    monkeypatch.setattr(b01, "CV_PERSIST_TIMEOUT", _RACE_BOUND_S)
    rig = _build(
        rel,
        account=_trading_account(pg_dsn),
        user=_user(pg_dsn),
        clock=Clock(_db_now(pg_dsn)),
        race=True,
    )
    try:
        yield rig
    finally:
        await rig.machines.stop()


type _Submission = tuple[OrderRequest, SubmitContext]


async def _race(
    rig: Rig, dsn: str, first: _Submission, second: _Submission
) -> tuple[asyncio.Task[SubmitOutcome], asyncio.Task[SubmitOutcome]]:
    """The first request's persist holds its transaction open in its write-ahead hook; the second
    request's persist waits on the first's uncommitted row (`pg_stat_activity`); then the first
    commits. Answers the two requests' tasks, still running."""
    rig.audits.hold()
    task_a = asyncio.create_task(rig.submit(*first))
    await rig.audits.entered.wait()
    task_b = asyncio.create_task(rig.submit(*second))
    try:
        await _wait_until_blocked(dsn)
    finally:
        rig.audits.released.set()
    return task_a, task_b


def _held_at_the_door(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> asyncio.Event:
    """Every create waits at the venue's door until the event is set, then lands."""
    door, land = asyncio.Event(), rig.demo.place_order

    async def held(create: PlaceOrderRequest) -> Any:
        await door.wait()
        return await land(create)

    monkeypatch.setattr(rig.demo, "place_order", held)
    return door


def _requests_of(rig: Rig, request_id: uuid.UUID) -> list[RequestRecord | KeyedRecord]:
    """The pipeline's own records of a request: its intent, its group, its stop requests, its
    outcome or its refusal."""
    return [r for r in rig.audits.of(request_id) if isinstance(r, RequestRecord | KeyedRecord)]


# -- the Gherkin -----------------------------------------------------------------------------------


async def test_happy_path_is_an_acceptance_not_a_fill(pg: Rig, pg_dsn: str) -> None:
    """Gherkin "Happy path is an acceptance, not a fill": 202 with the trade group and its order
    `submitted`, which claims no fill. The rows are written ahead of the one create (C-2.9), which
    carries the persisted id, stop and take-profit (C-2.6, C-2.10)."""
    outcome = await pg.submit()
    assert (outcome.status, outcome.lifecycle, outcome.code) == (202, "submitted", None)
    assert outcome.order_id is not None and outcome.trade_group_id is not None
    row = _order(pg_dsn, outcome.order_id)
    assert (row.lifecycle_state, row.state) == ("submitted", "accepted")
    assert row.cum_exec_qty == Decimal(0)
    assert _fills(pg_dsn, outcome.order_id) == 0  # an acceptance, not a fill
    assert (row.submit_attempts, row.idempotency_state) == (1, "acked")
    assert row.exchange_order_id is not None and (row.stop_loss, row.take_profit) == (
        STOP, TAKE_PROFIT,
    )  # fmt: skip
    [create] = pg.creates()
    assert (create.order_link_id, create.stop_loss, create.take_profit) == (
        row.order_link_id, STOP, TAKE_PROFIT,
    )  # fmt: skip
    events = _events(pg_dsn, outcome.order_id)
    assert (events[0], events[-1]) == ("pending_submit", "accepted") and "submitted" in events
    assert _group(pg_dsn, outcome.trade_group_id) == ("submitting", ["submitted"])
    assert _stops(pg_dsn, outcome.order_id) == [
        ("stop_loss", "pending", True),
        ("take_profit", "pending", True),
    ]
    assert _anchor(pg_dsn, outcome.anchor_id) == (202, None)
    assert _held(pg_dsn, pg.account, pg.user) == (1, 1, 1, 1, 2)
    written = [(r.action, r.reason, sent) for r, sent in pg.audits.written]
    names = [name for name in written if not name[0].startswith("orders.c")]
    assert names[:4] == [
        ("orders.submit", "validated", 0),
        ("trade_group.submit", "submitting", 0),
        ("sl.attached", "entry_attach", 0),
        ("tp.modified", "entry_attach", 0),
    ]
    assert names[-1] == ("orders.submit", "submitted", 1)
    assert {r.request_id for r, _ in pg.audits.written} == {_FIRST}


async def test_filters_are_enforced_before_any_exchange_call(pg: Rig, pg_dsn: str) -> None:
    """Gherkin "Filters are enforced before any exchange call": a price that is no multiple of the
    tick is refused `tick_size_violation`; nothing reaches the exchange and nothing is recorded,
    the refusal audited first (C-2.9)."""
    refused = await _refused(pg, pg.entry(price=Decimal("60000.05")))
    assert isinstance(refused, TickSizeViolation)
    assert problem_for(refused).code == "tick_size_violation"
    assert pg.demo.calls == []
    assert _held(pg_dsn, pg.account, pg.user) == (0, 0, 0, 0, 0)
    [record] = _denied(pg)
    assert (record.reason, record.detail["step"]) == ("tick_size_violation", "validate")
    assert _requests_of(pg, _FIRST) == [record]


async def test_entry_without_a_stop_is_refused(pg: Rig, pg_dsn: str) -> None:
    """Gherkin "Entry without a stop is refused": an entry with no `stop_loss`, on a profile with
    no SL offset (`NoProfileOffset`), is refused `validation_failed` / `native_stop_required`
    before any exchange call, with nothing recorded (C-2.6)."""
    ports = replace(SubmissionPorts.interim(now=pg.clock), stop_resolver=NoProfileOffset())
    pipeline = pg.make(ports=ports)
    with pytest.raises(OrderInvalid) as refused:
        await pipeline.submit(pg.entry(stop_loss=None), pg.context())
    assert problem_for(refused.value).code == "validation_failed"
    assert [(e.field, e.rule) for e in refused.value.errors] == [
        ("stop_loss", "native_stop_required")
    ]
    assert pg.demo.calls == []
    assert _held(pg_dsn, pg.account, pg.user) == (0, 0, 0, 0, 0)
    [record] = _denied(pg)
    assert (record.reason, record.detail["step"]) == ("validation_failed", "classify")


async def test_transport_failure_lands_in_unknown_never_in_a_retry(pg: Rig, pg_dsn: str) -> None:
    """Gherkin "Transport failure lands in Unknown, never in a retry": the create landed and its
    answer was lost (`LandedThenAmbiguous`, a timeout after the send). The order is persisted
    `unknown` with its event and an alert, the answer is 202 `unknown`, its stop requests wait for
    reconciliation, and no second create is issued (24 Sec.8.2 S1, C-2.10)."""
    pg.demo.script("place_order", LandedThenAmbiguous())
    outcome = await pg.submit()
    assert (outcome.status, outcome.lifecycle) == (202, "unknown")
    assert outcome.order_id is not None and outcome.trade_group_id is not None
    await pg.settle()
    row = _order(pg_dsn, outcome.order_id)
    assert (row.lifecycle_state, row.state) == ("unknown", "unknown")
    assert _events(pg_dsn, outcome.order_id)[-1] == "unknown"
    alerts = [(n.order_id, n.detail.get("alert")) for n in pg.notices.got if n.kind == "alert"]
    assert alerts == [(outcome.order_id, "order_unknown")]
    [create] = pg.creates()  # one create, and no second once the facade settled
    assert create.order_link_id == row.order_link_id
    landed = await pg.demo.open_orders(pg.ref(), order_link_id=row.order_link_id)
    assert len(landed) == 1  # the venue holds the one order
    assert _anchor(pg_dsn, outcome.anchor_id) == (202, None)
    assert _group(pg_dsn, outcome.trade_group_id) == ("submitting", ["submitted"])
    assert _stops(pg_dsn, outcome.order_id) == [
        ("stop_loss", "pending", False),
        ("take_profit", "pending", False),
    ]
    own = [r for r, _ in pg.audits.written if isinstance(r, RequestRecord | KeyedRecord)]
    assert {r.request_id for r in own} == {_FIRST} and own[-1].reason == "unknown"
    assert {r.request_id for r, _ in pg.audits.written} <= {_FIRST, None}


async def test_idempotent_replay_after_a_restart(
    pg: Rig, rel: SqlAlchemyRelationalRepository, pg_dsn: str
) -> None:
    """Gherkin "Idempotent replay", across a restart: the same Idempotency-Key and body posted
    again reach the permanent anchor (21 Sec.3.3.10) and get the original result, `replayed` (the
    route's `Idempotency-Replayed: true`), with the order's reconciled state. No second order, no
    second create, nothing recorded for the repeat."""
    context = pg.context()
    first = await pg.submit(pg.entry(), context)
    assert (first.status, first.lifecycle) == (202, "submitted")
    again = await _restart(pg, rel)
    try:
        replay = await again.submit(again.entry(), replace(context, request_id=_SECOND))
        assert replay == replace(
            first, order_id=None, lifecycle="submitted", replayed=True, written=None
        )
        assert len(again.creates()) == 1  # the first process's, and none since
        assert _held(pg_dsn, pg.account, pg.user) == (1, 1, 1, 1, 2)
        assert again.audits.of(_SECOND) == []
    finally:
        await again.machines.stop()


async def test_order_entry_blocked_when_we_cannot_record_it_a_hanging_store(
    pg: Rig, pg_dsn: str
) -> None:
    """Gherkin "Order entry blocked when we cannot record it", a store that does not answer:
    `orders` locked by another transaction, the allocation's lookup waits on it (gated on
    `pg_stat_activity`) past the pipeline's bound, and the request is 503 `store_unavailable`
    (the Gherkin's `service_unavailable`) before any exchange call, nothing recorded."""
    pipeline = pg.make(store_timeout_s=1.0)
    with _orders_locked(pg_dsn):
        task = asyncio.create_task(pipeline.submit(pg.entry(), pg.context()))
        await _wait_until_blocked(pg_dsn)
        with pytest.raises(StoreUnavailable) as refused:
            await task
    problem = problem_for(refused.value)
    assert (problem.status, problem.code) == (503, "store_unavailable")
    assert pg.demo.calls == []
    assert _held(pg_dsn, pg.account, pg.user) == (0, 0, 0, 0, 0)
    [record] = _denied(pg)
    assert (record.reason, record.detail["step"]) == ("store_unavailable", "allocate")


async def test_order_entry_blocked_when_we_cannot_record_it_a_stopped_postgres(
    stopped_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gherkin "Order entry blocked when we cannot record it", Postgres unreachable: every store
    on a Postgres that was stopped. The first read the request needs (its profile) fails, and it
    is 503 `store_unavailable` before any exchange call, its refusal audited first (C-2.9)."""
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    rel = SqlAlchemyRelationalRepository(_login(stopped_dsn, "cv_app"), _APP)
    rig = _build(rel, account=AccountId(uuid.uuid4()), user=uuid.uuid4(), clock=Clock(cr.T0))
    try:
        refused = await _refused(rig)
        problem = problem_for(refused)
        assert (type(refused), problem.status, problem.code) == (
            StoreUnavailable, 503, "store_unavailable",
        )  # fmt: skip
        assert rig.demo.calls == []
        [record] = _denied(rig)
        assert (record.reason, record.detail["step"]) == ("store_unavailable", "resolve")
    finally:
        await rig.machines.stop()
        await rel.dispose()


async def test_retry_reuses_the_id(
    pg: Rig, rel: SqlAlchemyRelationalRepository, pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gherkin "Retry reuses the id", after a restart: an order whose `order_link_id` was persisted
    before its first send, which never left (the process went down with the create at the
    venue's door), is hydrated `submitting`. Its id is looked up first, then the create goes out
    once under the persisted id with the same native stop (C-2.10, C-2.6); no id is allocated,
    and the exchange holds one order."""
    entered, door, land = asyncio.Event(), asyncio.Event(), pg.demo.place_order

    async def at_the_door(create: PlaceOrderRequest) -> Any:
        entered.set()
        await door.wait()  # never opened: this process goes down first
        return await land(create)

    monkeypatch.setattr(pg.demo, "place_order", at_the_door)
    task = asyncio.create_task(pg.submit())
    await entered.wait()
    task.cancel()  # the process goes down: the request first, then its facade
    await asyncio.gather(task, return_exceptions=True)
    [(order_id, link, state)] = _orders(pg_dsn, pg.account)
    row = _order(pg_dsn, order_id)
    assert (state, row.submit_attempts, row.idempotency_state) == ("submitting", 1, "in_flight")
    again = await _restart(pg, rel)
    monkeypatch.setattr(pg.demo, "place_order", land)
    try:
        assert again.creates() == []  # nothing left the first process
        assert await again.machines.hydrate(again.account, order_id, environment="demo") == (
            "submitting"
        )
        # The create resumes in B1's `place` invoke once the replay ends, and reads the row from
        # Postgres before its lookups and its send: wait for the step its answer brings.
        left = await again.machines.settled(
            again.account, order_id, leaving="submitting", timeout_s=_RESUME_BOUND_S
        )
        assert left == "submitted"
        await again.settle()
        methods = again.calls()
        sent = methods.index("place_order")
        assert methods.count("place_order") == 1
        assert sent > 0 and set(methods[:sent]) <= {"open_orders", "order_history"}
        [create] = again.creates()
        assert (create.order_link_id, create.stop_loss) == (link, STOP)
        assert again.lookup.asked == []  # no id allocated
        assert _order(pg_dsn, order_id).lifecycle_state == "submitted"
        assert len(await again.demo.open_orders(again.ref(), order_link_id=link)) == 1
    finally:
        await again.machines.stop()


def _candidate(rig: Rig) -> OrderLinkIdParts:
    """The one candidate every entry of the rig's account is allocated from (`OneCandidate`)."""
    return OneCandidate.generate(
        mode="exchange", environment="demo", group_id=OneCandidate.group,
        account_id=rig.account, seq=0, purpose="entry",
    )  # fmt: skip


async def test_a_persist_time_id_collision_is_re_allocated(
    racing: Rig, pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gherkin 9, "A persist-time id collision is re-allocated": two concurrent submissions are
    allocated the same `order_link_id`; the second's INSERT waits on the first's uncommitted row
    (gated on `pg_stat_activity`), then violates `ux_orders_link`. It allocates again from the
    same candidate (24 Sec.8.3 rule 5) and persists the new id before its send: each order goes
    out once, under its own persisted id."""
    monkeypatch.setattr(pipeline_module, "OrderLinkIdParts", OneCandidate)
    first, second = _candidate(racing).value, _candidate(racing).with_seq(1).value
    async with asyncio.timeout(60):
        task_a, task_b = await _race(
            racing,
            pg_dsn,
            (racing.entry(), racing.context()),
            (racing.entry(symbol=_OTHER), racing.context(request_id=_SECOND)),
        )
        a, b = await task_a, await task_b
    assert (a.status, a.lifecycle, b.status, b.lifecycle) == (202, "submitted", 202, "submitted")
    assert a.order_id is not None and b.order_id is not None
    assert (_order(pg_dsn, a.order_id).order_link_id, _order(pg_dsn, b.order_id).order_link_id) == (
        first, second,
    )  # fmt: skip
    assert sorted(c.order_link_id for c in racing.creates()) == sorted([first, second])
    assert (racing.lookup.asked.count(first), racing.lookup.asked.count(second)) == (3, 1)
    for request_id, link in ((_FIRST, first), (_SECOND, second)):
        intents = [r for r in _requests_of(racing, request_id) if r.reason == "validated"]
        assert [r.detail["order_link_id"] for r in intents] == [link]  # written with its persist


async def test_a_collision_past_the_bound_of_rule_5_is_exhausted_with_nothing_sent(
    pg: Rig, rel: SqlAlchemyRelationalRepository, pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gherkin 9's bound: a lookup that disagrees with the index keeps answering the taken id
    free, so each persist violates `ux_orders_link`; after 16 allocations again the 17th
    violation is `OrderLinkIdExhausted` (500 `internal_error`, which pages), nothing sent or
    recorded for that request."""
    monkeypatch.setattr(pipeline_module, "OrderLinkIdParts", OneCandidate)
    taken = await pg.submit()
    assert taken.status == 202
    liar = Lookup(OrderRepository(SqlAlchemyOrderStore(rel)), lies=True)
    pipeline = pg.make(allocator=OrderLinkIdAllocator(liar))
    with pytest.raises(OrderLinkIdExhausted) as refused:
        await pipeline.submit(pg.entry(), pg.context(request_id=_SECOND))
    assert problem_for(refused.value).code == "internal_error"
    assert liar.asked == [_candidate(pg).value] * 17
    assert _held(pg_dsn, pg.account, pg.user) == (1, 1, 1, 1, 2)  # the first request's alone
    assert len(pg.creates()) == 1
    [record] = _denied(pg, _SECOND)
    assert (record.reason, record.detail["step"]) == ("internal_error", "persist")
    assert _requests_of(pg, _SECOND) == [record]


async def test_two_concurrent_submits_of_one_key_send_one_order(
    racing: Rig, pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two concurrent first submissions of one Idempotency-Key and body: the second's INSERT of
    the key (`ux_tg_creator_ref`) waits on the first's uncommitted one (gated on
    `pg_stat_activity`), then meets the key held while the first's create is still in flight:
    409 `idempotency_in_flight` with `Retry-After`, nothing recorded or sent for it. One order and
    one create (C-2.10)."""
    door = _held_at_the_door(racing, monkeypatch)
    context = racing.context()
    async with asyncio.timeout(60):
        task_a, task_b = await _race(
            racing,
            pg_dsn,
            (racing.entry(), context),
            (racing.entry(), replace(context, request_id=_SECOND)),
        )
        [refused] = await asyncio.gather(task_b, return_exceptions=True)
        door.set()
        a = await task_a
    assert isinstance(refused, IdempotencyInFlight) and refused.retry_after_s == 1
    assert (a.status, a.lifecycle) == (202, "submitted") and a.order_id is not None
    assert _held(pg_dsn, racing.account, racing.user) == (1, 1, 1, 1, 2)
    [create] = racing.creates()
    assert create.order_link_id == _order(pg_dsn, a.order_id).order_link_id
    [record] = _denied(racing, _SECOND)
    assert (record.reason, record.detail["step"]) == ("idempotency_in_flight", "persist")
    assert _requests_of(racing, _SECOND) == [record]


@pytest.mark.parametrize("answered", [True, False], ids=["answered_between_tries", "in_flight"])
async def test_the_q4_race_on_one_position(
    racing: Rig, pg_dsn: str, monkeypatch: pytest.MonkeyPatch, answered: bool
) -> None:
    """Q4, two entries on one position: the second's stop request waits on the first's
    uncommitted one (`ux_rs_in_flight`, gated on `pg_stat_activity`), then meets it in flight and
    is tried again after 0.1 s, then 0.25 s (recorded, never slept). Answered between the tries,
    the second goes through; still in flight, it is 409 `stop_request_in_flight` with
    `Retry-After: 1`, nothing recorded and its key unbound, so the key is a first submission
    once the first is answered."""
    door = _held_at_the_door(racing, monkeypatch)
    second_context = racing.context(request_id=_SECOND)
    tasks: list[asyncio.Task[SubmitOutcome]] = []

    async def first_answers() -> None:
        if answered and not door.is_set():
            door.set()
            await tasks[0]  # its create answered, so its step answered its stop request

    racing.sleeps.then = first_answers
    async with asyncio.timeout(60):
        tasks.extend(
            await _race(
                racing,
                pg_dsn,
                (racing.entry(), racing.context()),
                (racing.entry(), second_context),
            )
        )
        [second] = await asyncio.gather(tasks[1], return_exceptions=True)
        door.set()
        first = await tasks[0]
    assert (first.status, first.lifecycle) == (202, "submitted")
    if answered:
        assert isinstance(second, SubmitOutcome)
        assert (second.status, second.lifecycle) == (202, "submitted")
        assert racing.sleeps.waits == [0.1]
        assert _held(pg_dsn, racing.account, racing.user) == (2, 2, 2, 2, 4)
        assert len(racing.creates()) == 2
        return
    assert isinstance(second, StopRequestPending) and second.retry_after_s == 1
    assert problem_for(second).code == "stop_request_in_flight"
    assert racing.sleeps.waits == [0.1, 0.25]
    assert _held(pg_dsn, racing.account, racing.user) == (1, 1, 1, 1, 2)
    assert len(racing.creates()) == 1
    [record] = _denied(racing, _SECOND)
    assert (record.reason, record.detail["step"]) == ("stop_request_in_flight", "persist")
    again = await racing.submit(racing.entry(), second_context)  # the key is unbound
    assert (again.status, again.replayed) == (202, False)
