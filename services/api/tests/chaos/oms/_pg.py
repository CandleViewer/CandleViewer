"""E29-Q04's Postgres tier (#1148; the ruling's BQ-3 (a) and BQ-4): the OMS runtime as cv-api
composes it (`OmsRuntime` over `pg_stores`, 20 Sec.6.2) on a real Postgres 16 node, the venue
handed from one process to the next. Marker `chaos and integration`, which the PR lanes deselect
(`_job-py.yml`); the nightly that runs it is slice 4's.

**The node** (`node`): testcontainers' Postgres 16, published on loopback only (as
`tests/integration/_refused.py` publishes its own) at a port picked here, so the node stopped and
started again keeps its address (`Node.stop`, `Node.start`); set up as production is, as
`test_submission_pipeline_pg.pg_dsn` sets it up: the roles (`pg_bootstrap.sql`), then the
migrations at head as `cv_owner`. Each test clones the migrated database (`fresh`), so a sweep
meets its own test's orders alone, with its account and the user who trades it.

**A process** (`running`): the runtime over `pg_stores` on the test's database, its order lane on
a thread of its own, the environment's lock, the fencing grace, the startup sweep and the startup
pass as in production; as the startup sweep's Postgres test composes it
(`test_startup_sweep_pg._runtime`), the account read in memory and the lane's writer a double
(`Records`). The account has no private stream. `ready` is awaited within `READY_S` of the start,
and the account's startup pass within a cycle of it (its `oms.reconcile` record), both kept
(`ready_s`, `passed_s`): wall time, bounded as that test bounds it.

**The venue** (`HostPort`): the chaos suite's (`_venue.VenuePort`) on the host's wall clock, which
the OMS's clock is too. A process hands it to the next as it stood (`handed`, `take`): its orders,
executions and positions, the exchange ids it issued and the creates it counted, so the next one
counts its creates on top. Its truth is read on the order lane, where the OMS calls it.

Every wait is wall time, bounded (`WAIT_S`): a bound turns a hang into a failure. The venue facts
are 24's documented ones: derived, not evidence (E29-K01, #843)."""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Coroutine, Iterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from time import monotonic, time_ns
from types import SimpleNamespace
from typing import Any, Final
from uuid import UUID

import psycopg
import pytest
from psycopg import sql
from pydantic import SecretStr
from testcontainers.core.wait_strategies import ExecWaitStrategy
from testcontainers.postgres import PostgresContainer

from candleviewer.accounts.profile_cache import EffectiveProfiles
from candleviewer.domain.primitives import AccountId, TsUs
from candleviewer.exchange.base.models import (
    AccountRef,
    Execution,
    FeeRate,
    Order,
    Position,
    RiskLimitTier,
    Wallet,
)
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.fakes import FakeClockHealth
from candleviewer.oms.reconcile_job import INTERVAL_S
from candleviewer.oms.submit import SubmitOutcome
from candleviewer.oms_reconcile_wiring import RECONCILE
from candleviewer.oms_wiring import OmsRuntime, environment_lock_key, pg_stores
from candleviewer.settings import Environment as Env
from candleviewer.settings import Settings
from candleviewer.storage.repositories.account_profiles_sqlalchemy import (
    SqlAlchemyAccountProfileStore,
)
from candleviewer.storage.repositories.executions_sqlalchemy import SqlAlchemyExecutionStore
from candleviewer.storage.repositories.orders_sqlalchemy import SqlAlchemyOrderStore
from candleviewer.storage.repositories.positions_sqlalchemy import SqlAlchemyPositionStore
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.trading_accounts import (
    InMemoryTradingAccountReads,
    TradingAccountRow,
)
from tests.chaos.oms._oracle import Book, Truth
from tests.chaos.oms._venue import TAKER, Venue, VenuePort
from tests.chaos.oms._world import BUILT, PRICE, SYMBOL
from tests.integration.oms.test_submission_pipeline_pg import (
    _BOOTSTRAP,
    _RESUME_BOUND_S,
    _ROOT,
    _login,
    _sql,
    _trading_account,
    _uid,
    _user,
)
from tests.unit.oms import command_rig as cr
from tests.unit.oms import test_oms_runtime as rt
from tests.unit.oms.order_rig import Pager
from tests.unit.oms.submit_rig import ACTOR, REGISTRY, ReadOnly, context, entry, instrument

#: Every wait on the node, a child process or the runtime, in seconds of wall time.
WAIT_S: Final = 120.0
#: How long a process may take to be ready: `test_startup_sweep_pg._READY_BOUND_S`.
READY_S: Final = 30.0
#: The node's database, migrated once; each test's is a clone of it.
TEMPLATE: Final = "candleviewer"
_END_US: Final = 2**62  # the executions read's end: after every fill the venue stamped
_ORDER_IDS: Final = "SELECT id FROM orders WHERE exchange_account_id = %s ORDER BY created_ts, id"


def _sync(dsn: str) -> str:
    return dsn.replace("postgresql+asyncpg", "postgresql")


# --- The node and each test's database -------------------------------------------------------


@dataclass(frozen=True)
class Node:
    """The Postgres 16 node of a module's tests (`node`): its container and its loopback port."""

    container: PostgresContainer
    port: int

    def dsn(self, database: str) -> str:
        """The superuser's DSN of `database` on the node, in the runtime's driver's form."""
        c = self.container
        return f"postgresql+asyncpg://{c.username}:{c.password}@127.0.0.1:{self.port}/{database}"

    def stop(self) -> None:
        """The node stopped (`docker stop`, its fast shutdown): every session ended, and nothing
        answers at its port until `start`."""
        self.container.get_wrapped_container().stop(timeout=10)

    def start(self) -> None:
        """The node started again at its port, once it accepts connections (`pg_isready`, as
        testcontainers waits for a container, within `WAIT_S`)."""
        self.container.get_wrapped_container().start()
        ready = ExecWaitStrategy(["pg_isready", "-q", "-h", "127.0.0.1"])
        ready.with_startup_timeout(int(WAIT_S)).wait_until_ready(self.container)


def _free_port() -> int:
    """A loopback port nothing listens on now, for the node to keep across a restart."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _bootstrap(dsn: str) -> None:
    """The cluster's roles (`pg_bootstrap.sql`, as `test_submission_pipeline_pg.pg_dsn` runs it)."""
    info = psycopg.conninfo.conninfo_to_dict(_sync(dsn))
    psql = shutil.which("psql")
    assert psql is not None, "the CI integration and migrations jobs have postgresql-client"
    bootstrap = subprocess.run(  # noqa: S603 -- resolved absolute path, fixed argv, no shell
        [psql, "-h", str(info["host"]), "-p", str(info["port"]), "-U", str(info["user"]),
         "-d", TEMPLATE, "-v", "ON_ERROR_STOP=1", "-v", "owner_pw=cv_owner_test_pw",
         "-v", "app_pw=cv_app_test_pw", "-v", "ro_pw=cv_ro_test_pw", "-f", str(_BOOTSTRAP)],
        check=False, capture_output=True, text=True, timeout=120,
        env={**os.environ, "PGPASSWORD": str(info["password"])},
    )  # fmt: skip
    assert bootstrap.returncode == 0, bootstrap.stderr


@pytest.fixture(scope="module")
def node() -> Iterator[Node]:
    """The module's Postgres 16 (module docstring), its database at head the template each test
    clones (`fresh`); its bootstrap and migrations each bounded, as the precedent's are."""
    container = PostgresContainer("postgres:16-alpine", dbname=TEMPLATE)
    port, ports = _free_port(), container.ports
    published: dict[Any, Any] = ports
    published[5432] = ("127.0.0.1", port)  # loopback only, and the same port after a restart
    with container:
        started = container.get_wrapped_container()
        started.reload()  # read back, not assumed (`_refused.pg_dsn`)
        bound = {b["HostIp"] for binds in started.ports.values() for b in binds or []}
        assert bound == {"127.0.0.1"}, f"the Postgres port is published on {bound or 'nowhere'}"
        up = Node(container, port)
        _bootstrap(up.dsn(TEMPLATE))
        owner = _login(up.dsn(TEMPLATE), "cv_owner").replace("+asyncpg", "+psycopg")
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT, env={**os.environ, "CV_PG_DSN": owner}, check=True, timeout=300,
        )  # fmt: skip
        yield up


@dataclass(frozen=True)
class Db:
    """A test's own database on the node (`fresh`): the runtime's DSN (`cv_app`), the account it
    trades and the user who trades it, and the superuser's DSN (`su`; a child has none)."""

    app: str
    account: AccountId
    user: UUID
    su: str = ""

    @property
    def ref(self) -> AccountRef:
        """The account as the venue's port takes it (`test_submission_pipeline_pg.Rig.ref`)."""
        return AccountRef(
            account_id=self.account, uid=_uid(self.account), environment="demo",
            key_ref=cr.KEYS["demo"],
        )  # fmt: skip

    def order(self, **more: str) -> dict[str, str]:
        """What a child process is told, on its stdin (never argv, the environment or a file)."""
        return {"dsn": self.app, "account": str(self.account), "user": str(self.user)} | more

    @classmethod
    def given(cls, order: Mapping[str, str]) -> Db:
        return cls(order["dsn"], AccountId(UUID(order["account"])), UUID(order["user"]))


def fresh(node: Node) -> Db:
    """A database of the test's own, cloned from the node's migrated one, with a demo account
    whose default profile trades the symbol (`_trading_account`) and a user who trades it."""
    name = f"q04_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(_sync(node.dsn("postgres")), autocommit=True) as c:
        c.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE {}").format(
                sql.Identifier(name), sql.Identifier(TEMPLATE)
            )
        )
    su = node.dsn(name)
    return Db(_login(su, "cv_app"), _trading_account(su), _user(su), su)


async def freed(db: Db, within_s: float = WAIT_S) -> None:
    """Until the environment's lock (SEC-S3N-01) is free in `db`, its holder's session gone and
    the lock with it: Postgres itself waits for it (`pg_advisory_lock`), within `lock_timeout`."""

    def taken_and_given_back() -> None:
        key = environment_lock_key("demo")
        with psycopg.connect(_sync(db.su), autocommit=True) as c:
            c.execute("SELECT set_config('lock_timeout', %s, false)", (str(int(within_s * 1000)),))
            c.execute("SELECT pg_advisory_lock(%s::bigint)", (key,))
            c.execute("SELECT pg_advisory_unlock(%s::bigint)", (key,))

    await asyncio.to_thread(taken_and_given_back)


# --- The venue, handed from one process to the next ------------------------------------------


def now_us() -> TsUs:
    """The venue's clock: the host's wall clock in µs, the OMS's too (`OmsRuntime`'s `now`)."""
    return time_ns() // 1_000


class HostPort(VenuePort):
    """The venue's demo port on the host's wall clock (module docstring), for `ref`'s account,
    funded as `_world.opened` funds it: what it holds handed to the next process (`handed`),
    and taken up by that one's port (`take`)."""

    def __init__(self, ref: AccountRef) -> None:
        super().__init__(now_us=now_us)
        self.ref = ref
        self.set_wallet(Wallet(
            account_id=ref.account_id, equity=Decimal(100_000), wallet_balance=Decimal(100_000),
            available_to_withdraw=None, available_margin=Decimal(100_000),
            used_margin=Decimal(0), unrealised_pnl=Decimal(0), cum_realised_pnl=Decimal(0),
            account_im_rate=Decimal(0), account_mm_rate=Decimal(0), updated_at=0,
        ))  # fmt: skip
        fee = FeeRate(symbol=SYMBOL, maker=Decimal("0.0002"), taker=TAKER, fetched_at=0)
        self.set_fee_rate(ref.account_id, fee)

    def creates(self) -> Counter[str]:
        """Each `order_link_id`'s creates that reached this port (`Venue.creates`)."""
        return Venue(self, self.ref, now_us).creates()

    def handed(self) -> dict[str, Any]:
        """What the venue holds, as JSON: its orders, executions and positions, the exchange ids
        it issued and the creates it counted."""
        orders = (*self._open.values(), *self._history.values())
        return {
            "orders": [o.model_dump(mode="json") for o in orders],
            "executions": [e.model_dump(mode="json") for e in self._executions],
            "positions": [p.model_dump(mode="json") for p in self._positions],
            "issued": self._next_id,
            "creates": dict(self.creates()),
        }

    def take(self, handed: Mapping[str, Any]) -> Counter[str]:
        """The venue as a process handed it over (`handed`), seeded here; the creates it counted."""
        for order in handed["orders"]:
            self.seed_order(Order.model_validate(order), uid=self.ref.uid)
        for fill in handed["executions"]:
            self.seed_execution(Execution.model_validate(fill))
        for position in handed["positions"]:
            self.seed_position(Position.model_validate(position))
        self._next_id = int(handed["issued"])
        return Counter(handed["creates"])


@dataclass
class Host(rt.Venue):
    """The adapter's service (`test_oms_runtime.Venue`) whose lane port is `held`, demo only."""

    held: HostPort = field(kw_only=True)

    def port(self, env: str) -> HostPort:
        assert env == "demo", "the chaos suite runs on demo only (C-13.5)"
        return self.held


# --- A process -------------------------------------------------------------------------------


@dataclass
class Records(rt.Writer):
    """The lane's writer double (`test_oms_runtime.Writer`), which also tells the serving loop
    (`loop`) from the lane's thread when a pass's record (`oms.reconcile`) has landed."""

    loop: asyncio.AbstractEventLoop | None = None
    passed: asyncio.Event = field(default_factory=asyncio.Event)

    async def emit(self, action: str, **fields: Any) -> None:
        await super().emit(action, **fields)
        if action == RECONCILE and self.loop is not None:
            self.loop.call_soon_threadsafe(self.passed.set)


@dataclass
class Paging(Pager):
    """The pager double (`order_rig.Pager`), each page also told to the serving loop (`loop`)."""

    loop: asyncio.AbstractEventLoop | None = None
    raised: asyncio.Event = field(default_factory=asyncio.Event)

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        super().raise_alert(severity, summary, machine_kind=machine_kind)
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.raised.set)

    async def paged(self, summary: str, within_s: float = WAIT_S) -> None:
        """Until the pager has taken `summary`, at most `within_s`."""
        async with asyncio.timeout(within_s):
            while True:
                self.raised.clear()
                if summary in self.calls:
                    return
                await self.raised.wait()


@dataclass
class PgWorld:
    """A process on the test's database (`running`): its runtime, the venue it trades, its doubles
    and the creates the process before it left at the venue (`before`); what the oracle checks
    (`_oracle.Checked`): the book read from Postgres, the truth from the venue."""

    db: Db
    host: Path
    venue: Host
    before: Counter[str] = field(default_factory=Counter)
    writer: Records = field(default_factory=Records)
    pager: Paging = field(default_factory=Paging)
    flags: tuple[rt.Flag, rt.Flag] = field(default_factory=lambda: (rt.Flag(), rt.Flag()))
    checked: bool = False
    #: From its start, when it was ready and when its account's startup pass reported (wall time).
    ready_s: float = 0.0
    passed_s: float = 0.0
    oms: OmsRuntime = field(init=False)

    def __post_init__(self) -> None:
        self.pool = SqlAlchemyRelationalRepository(self.db.app, "q04-oracle")
        BUILT.append(self)

    @property
    def port(self) -> HostPort:
        return self.venue.held

    def creates(self) -> Counter[str]:
        """Each `order_link_id`'s creates at the venue, the process before this one's among them."""
        return self.before + self.port.creates()

    def reports(self) -> list[dict[str, Any]]:
        """Each pass's `oms.reconcile` record as the lane's writer took it (its `after_state`)."""
        return [f["after_state"] for action, f in self.writer.records if action == RECONCILE]

    async def submit(self, *, key: int = 1) -> SubmitOutcome:
        """`placeOrder`'s pipeline: the limit buy entry with its stop and take-profit attached
        (`submit_rig.entry`), the user's, under the client key `key`."""
        made = context(actor=replace(ACTOR, user_id=self.db.user), client_ref=UUID(int=key))
        return await self.oms.submission.submit(entry(account_id=self.db.account), made)

    async def on_lane[T](self, coro: Coroutine[Any, Any, T]) -> T:
        """`coro` run on the order lane, where the OMS runs and calls the venue."""
        return await self.oms._composed().lane.call(coro)

    async def settled(self, order_id: UUID, *, leaving: str) -> str:
        """The order's state once it has left `leaving` (B1's `settled`, the precedent's wait)."""
        machines = self.oms._composed().machines
        left = machines.settled(
            self.db.account, order_id, leaving=leaving, timeout_s=_RESUME_BOUND_S
        )
        return await self.on_lane(left)

    async def settle(self) -> None:
        """Settled: the account's startup pass has reported (`running` waits for it)."""
        await asyncio.wait_for(self.writer.passed.wait(), INTERVAL_S)

    async def book(self) -> Book:
        """The account's `orders`, `executions` and open `positions` rows, read through the
        stores as the runtime's role (`cv_app`)."""
        account = self.db.account
        ids = await asyncio.to_thread(_sql, self.db.su, _ORDER_IDS, account)
        orders = SqlAlchemyOrderStore(self.pool)
        rows = [await orders.get(account, UUID(str(order_id))) for (order_id,) in ids]
        fills = await SqlAlchemyExecutionStore(self.pool).list_recent(account)
        positions = await SqlAlchemyPositionStore(self.pool).list_open(account)
        return Book(tuple(row for row in rows if row is not None), fills, positions)

    async def truth(self) -> Truth:
        """What the venue holds for the account, through its own reads, and its creates."""

        async def read() -> Truth:
            port, ref = self.port, self.db.ref
            orders = (*await port.open_orders(ref), *await port.order_history(ref))
            fills, positions = await port.executions(ref, 0, _END_US), await port.positions(ref)
            return Truth(orders, tuple(fills), tuple(positions), self.creates())

        return await self.on_lane(read())


def _runtime(world: PgWorld, profiles: EffectiveProfiles) -> OmsRuntime:
    """The process's runtime (module docstring): `test_startup_sweep_pg._runtime`'s composition
    with the chaos suite's venue, the instrument, quote and risk tiers `_world.opened` lists, and
    the process's doubles."""
    db, host = world.db, world.host
    settings = Settings(
        environment=Env("demo"), storage_backend="real", pg_dsn=SecretStr(db.app),
        audit_wal_path=str(host / "audit.wal"),
        machine_event_wal_path=str(host / "machine_events.wal"),
    )  # fmt: skip
    metrics = Metrics("demo")
    row = TradingAccountRow(db.account, "demo", db.ref.uid, False, UUID(cr.KEYS["demo"]))
    health = FakeClockHealth(cr.Monotonic())
    health.measure()
    tiers = (RiskLimitTier(
        tier_id=1, risk_limit_value=Decimal(2_000_000), maintenance_margin_rate=Decimal("0.005"),
        initial_margin_rate=Decimal("0.01"), max_leverage=Decimal(100),
    ),)  # fmt: skip
    listed = {SYMBOL: instrument()}
    quote = SimpleNamespace(bid1_price=PRICE, ask1_price=PRICE, last_price=PRICE)
    built: dict[str, Any] = {
        "venue": world.venue, "read_only": ReadOnly(), "metrics": metrics, "profiles": profiles,
        "ingestion": SimpleNamespace(
            clock=health, clock_offset_snapshot_ms=lambda: None,
            instruments=SimpleNamespace(snapshot=lambda: SimpleNamespace(
                get=listed.get, risk_limit_tiers=lambda _s: tiers,
            )),
            tickers=SimpleNamespace(
                latest=lambda _s: quote, is_stale=lambda _s: False,
                acquire=lambda _c, _s: None, release=lambda _c, _s: None,
            ),
        ),
        "gate": SimpleNamespace(refusal=lambda _account: None),
        "standings": SimpleNamespace(read_once=True, credential_rejected=lambda *_args: None),
        "oms_enabled": world.flags[0], "live_enabled": world.flags[1], "persistence": None,
        "feed": SimpleNamespace(bind=lambda _b: SimpleNamespace(publish=lambda *_a, **_k: None)),
        "lane_signing": rt.Binder(), "health": rt.Tracked(), "hub": rt.Hub(),
        "pager": world.pager, "registry": REGISTRY,
        "stores": lambda: replace(  # the lane's own writer is the double (#913 L2)
            pg_stores(settings, metrics), accounts=InMemoryTradingAccountReads(row),
            audit=lambda _alarm: world.writer,
        ),
    }  # fmt: skip
    return OmsRuntime(settings, **built)


@asynccontextmanager
async def running(
    db: Db, host: Path, venue: Host, *, before: Counter[str] | None = None
) -> AsyncIterator[PgWorld]:
    """A process over `db` and `venue` (module docstring), after one that left `before` creates at
    the venue: started as `test_oms_runtime.started` starts a runtime, ready within `READY_S` of
    its start, its account's startup pass reported within a cycle of that; stopped at the end."""
    loop = asyncio.get_running_loop()
    world = PgWorld(db, host, venue, before if before is not None else Counter())
    world.writer.loop = world.pager.loop = loop
    profiles = SqlAlchemyRelationalRepository(db.app, "q04-profiles")
    try:
        world.oms = _runtime(world, EffectiveProfiles(SqlAlchemyAccountProfileStore(profiles)))
        for flag in world.flags:
            flag.read()
        began = monotonic()
        async with rt.started(world.oms):
            try:
                await asyncio.wait_for(world.oms.wait_ready(), READY_S)
                world.ready_s = monotonic() - began
                await asyncio.wait_for(world.writer.passed.wait(), INTERVAL_S)
            except TimeoutError:  # what the process said meanwhile, for the failure
                state, paged = world.oms.state, world.pager.calls
                raise AssertionError(f"not ready, or no startup pass: {state}, {paged}") from None
            world.passed_s = monotonic() - began
            yield world
    finally:
        await world.pool.dispose()
        await profiles.dispose()
