"""Integration (E29-T04 #913 slice 3G): #913's non-amend Gherkin through the mounted `POST /orders`,
on real Postgres 16. Each test runs one API process, or two for a restart: F's router
(`make_orders_router`) over E's `OmsRuntime` started on the serving loop, its stores on
`pg_stores`' own pool over C6's database (`test_submission_pipeline_pg.py`, shared by import), its
standalone `machine_events` WAL sink in `tmp_path`, the real `EffectiveProfiles` on a pool of its
own, and a `FakeTradingPort` as the venue (C-13.5). As in E4's `test_startup_sweep_pg.py` the
account read is in memory (no key row is seeded); here the instrument catalogue is composed too,
so the pipeline admits. Each scenario asserts the answer against 22 and the rows, the audit
records and the exchange calls behind it, counting the venue's calls from just before its request,
and depends on no other test's rows (`world`); an unreachable Postgres is a loopback relay that is
cut, both pools behind it. "Retry reuses the id" and "A persist-time id collision is re-allocated"
never reach the route: slices 1 and 2 prove them (C6's `test_retry_reuses_the_id`,
`test_a_persist_time_id_collision_is_re_allocated`). Amend is slice 4's. Run once locally before
review (7 passed, Postgres 16); CI's `integration` job runs it in the merge group."""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import psycopg
import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from structlog.testing import capture_logs

from candleviewer.accounts.profile_cache import EffectiveProfiles
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.api.orders import make_orders_router
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.fakes import LandedThenAmbiguous
from candleviewer.exchange.base.models import FeeRate, PlaceOrderRequest, RiskLimitTier, Wallet
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.fakes import FakeClockHealth
from candleviewer.oms.ports import Profiles
from candleviewer.oms_wiring import LaneHeartbeat, OmsAudit, OmsRuntime, pg_stores
from candleviewer.settings import Settings
from candleviewer.storage.repositories.account_profiles_sqlalchemy import (
    SqlAlchemyAccountProfileStore,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.trading_accounts import (
    InMemoryTradingAccountReads,
    TradingAccountRow,
)
from tests.integration.oms import test_submission_pipeline_pg as c6
from tests.integration.oms.test_startup_sweep_pg import _READY_BOUND_S, _Venue
from tests.integration.oms.test_submission_pipeline_pg import pg_dsn
from tests.unit.api.test_order_acceptance import validate
from tests.unit.api.test_orders_route import BODY, KEY
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr
from tests.unit.oms.order_rig import Pager
from tests.unit.oms.test_oms_runtime import Beats, Flag, Port, Writer, started

pytestmark = pytest.mark.integration
__all__ = ["pg_dsn"]  # C6's database for this module

_NOTHING = (0, 0, 0, 0, 0)  # `_held`: no order, anchor, group, leg or recorded stop
#: The venue reads of the size step's figures (`DayRiskFigures`), the only calls before a filter.
_FIGURE_READS = {"wallet", "closed_pnl", "positions", "open_orders", "fee_rate"}


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """One direction of a relayed connection, until either side goes."""
    with contextlib.suppress(OSError):
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()
    writer.close()


class _Relay:
    """A loopback relay in front of the database: `cut` makes Postgres unreachable, its port
    refusing every connection and each connection through it reset."""

    def __init__(self, dsn: str) -> None:
        info = psycopg.conninfo.conninfo_to_dict(dsn.replace("postgresql+asyncpg", "postgresql"))
        self._upstream = (str(info["host"]), int(str(info["port"])))
        self._streams: set[asyncio.StreamWriter] = set()
        self._server: asyncio.Server | None = None

    async def through(self, dsn: str) -> str:
        """`dsn` through the relay, which listens from now on."""
        self._server = await asyncio.start_server(self._relay, "127.0.0.1", 0)
        port = self._server.sockets[0].getsockname()[1]
        return re.sub(r"@[^@/]+/", f"@127.0.0.1:{port}/", dsn)

    async def _relay(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        up_reader, up_writer = await asyncio.open_connection(*self._upstream)
        self._streams |= {writer, up_writer}
        await asyncio.gather(_pipe(reader, up_writer), _pipe(up_reader, writer))

    def cut(self) -> None:
        if self._server is not None:
            self._server.close()  # its socket closes now: a connect is refused
        for stream in self._streams:
            stream.close()


def _owner(user: UUID) -> SimpleNamespace:
    """The route's principal source: every request is the world's Owner, in one session."""
    snapshot = PrincipalSnapshot(user, frozenset({"owner"}), frozenset(Permission))
    principal = TradingPrincipal(sr.SESSION, snapshot)
    return SimpleNamespace(resolve=lambda _request: principal)


@dataclass
class World:
    """One test's account, Owner and venue, and what its processes share: the audit log, the
    pager, the WAL's path, the database, and the beats the lane's heartbeat ticks on."""

    dsn: str  # the superuser's: the assertions read the rows through it
    account: AccountId
    user: UUID
    clock: c6.Clock
    wal: Path
    writer: Writer = field(default_factory=Writer)
    pager: Pager = field(default_factory=Pager)
    retrying: asyncio.Event = field(default_factory=asyncio.Event)
    beats: Beats = field(default_factory=Beats)
    port: Port = field(init=False)
    body: dict[str, Any] = field(init=False)

    def __post_init__(self) -> None:
        self.port = Port(environment="demo", now_us=self.clock.us)
        self.body = BODY | {"exchange_account_id": str(self.account)}
        # The size step's figures (24 Sec.9.3.6): the venue's wallet and fee rate; no position,
        # no open order and no closed P&L today, the fake's own empty answers.
        cash, none = Decimal(100000), Decimal(0)
        self.port.set_wallet(Wallet(
            account_id=self.account, equity=cash, wallet_balance=cash, available_to_withdraw=None,
            available_margin=cash, used_margin=none, unrealised_pnl=none, cum_realised_pnl=none,
            account_im_rate=none, account_mm_rate=none, updated_at=self.clock.us(),
        ))  # fmt: skip
        fee = FeeRate(symbol=sr.SYMBOL, maker=Decimal("0.0002"), taker=Decimal("0.00055"),
                      fetched_at=self.clock.us())  # fmt: skip
        self.port.set_fee_rate(self.account, fee)

    async def backoff(self, seconds: float) -> None:
        """The runtime's sleep: a retry of its start, an environment lock not answered (CR-S3L2-01)
        or a sweep the store failed, waits here until the test ends."""
        self.retrying.set()
        await asyncio.Event().wait()

    async def unfenced(self, seconds: float) -> None:
        """The fencing grace once the lock is held (SEC-S3L2-01), passed at once: no other process
        held it, and the backoff above waits for good."""

    def heartbeat(self, lock: Any, pager: Any) -> LaneHeartbeat:
        """The lane's heartbeat on the world's beats, which no test ticks (CR-S3L2X-05): its first
        tick asks the lock, and no other follows, so a cut the test makes once the runtime is
        ready never meets the watchdog's ask, which would fence the runtime first."""
        return LaneHeartbeat(lock, pager, clock=self.beats.clock, wait=self.beats.wait)

    def creates(self, since: int = 0) -> list[PlaceOrderRequest]:
        sent = [call.request for call in self.port.calls[since:] if call.method == "place_order"]
        return [create for create in sent if isinstance(create, PlaceOrderRequest)]

    def held(self) -> tuple[int, ...]:
        return c6._held(self.dsn, self.account, self.user)


@pytest.fixture
def world(pg_dsn: str, tmp_path: Path) -> Iterator[World]:
    """A new account and Owner. The Owner holds the owner role, which a scoped group read checks
    live (`c6._user` gives none); the account's orders are ended when the test is over, as a
    runtime's startup sweep hydrates the unfinished orders of every `demo` account."""
    clock = c6.Clock(c6._db_now(pg_dsn))
    account, user = c6._trading_account(pg_dsn), c6._user(pg_dsn)
    c6._sql(pg_dsn, "INSERT INTO user_roles (user_id, role_id) "
            "SELECT %s, id FROM roles WHERE name = 'owner'", user)  # fmt: skip
    yield World(pg_dsn, account, user, clock, tmp_path / "machine_events.wal")
    c6._sql(pg_dsn, "UPDATE orders SET state = 'cancelled', lifecycle_state = 'cancelled' "
            "WHERE exchange_account_id = %s", account)  # fmt: skip


class _Listed(dict[str, Any]):
    """The catalogue's snapshot: its instruments, and each one's lowest risk-limit tier, which
    the size step reads its maintenance-margin rate from."""

    def risk_limit_tiers(self, symbol: str) -> tuple[RiskLimitTier, ...] | None:
        tier = RiskLimitTier(
            tier_id=1, risk_limit_value=Decimal(2_000_000), initial_margin_rate=Decimal("0.01"),
            maintenance_margin_rate=Decimal("0.005"), max_leverage=Decimal(100),
        )  # fmt: skip
        return (tier,) if symbol in self else None


def _runtime(world: World, dsn: str, profiles: Profiles, metrics: Metrics) -> OmsRuntime:
    """A process's runtime over the database at `dsn`, as E4's: the clock guard measured, the
    flag views read, the account and its key read in memory, the catalogue composed, and the lane's
    heartbeat on the world's beats."""
    settings = Settings(
        storage_backend="real", pg_dsn=SecretStr(dsn), machine_event_wal_path=str(world.wal)
    )
    key = UUID(cr.KEYS["demo"])
    row = TradingAccountRow(world.account, "demo", c6._uid(world.account), False, key)
    flags = (Flag(), Flag())
    for flag in flags:
        flag.read()
    health = FakeClockHealth(cr.Monotonic())
    health.measure()
    listed = _Listed({sr.SYMBOL: sr.instrument()})
    catalogue = SimpleNamespace(snapshot=lambda: listed)
    # A fresh quote whose mid is the test bodies' price, inside the band the entry is checked in.
    quote = SimpleNamespace(
        bid1_price=Decimal("59999"), ask1_price=Decimal("60001"), last_price=Decimal("60000")
    )
    tickers = SimpleNamespace(
        latest=lambda _symbol: quote,
        is_stale=lambda _symbol: False,
        acquire=lambda _consumer, _symbol: None,
        release=lambda _consumer, _symbol: None,
    )
    return OmsRuntime(
        settings, venue=_Venue(ports=[world.port]),
        ingestion=SimpleNamespace(
            clock=health, tickers=tickers, instruments=catalogue, clock_offset_ms=lambda: None
        ),
        read_only=sr.ReadOnly(), metrics=metrics,
        gate=SimpleNamespace(refusal=lambda _account: None),
        standings=SimpleNamespace(read_once=True, credential_rejected=lambda *_args: None),
        oms_enabled=flags[0], live_enabled=flags[1], profiles=profiles, persistence=None,
        feed=SimpleNamespace(bind=lambda _b: SimpleNamespace(publish=lambda *_a, **_k: None)),
        stores=lambda: replace(  # the lane's own writer is the world's (#913 L2)
            pg_stores(settings, metrics), accounts=InMemoryTradingAccountReads(row),
            audit=lambda _alarm: world.writer,
        ),
        pager=world.pager, now=world.clock, sleep=world.backoff, registry=sr.REGISTRY,
        fencing=world.unfenced, heartbeat=world.heartbeat,
    )  # fmt: skip


@asynccontextmanager
async def _serving(
    world: World, *, dsn: str = "", profiles: Profiles | None = None, ready: bool = True
) -> AsyncIterator[httpx.AsyncClient]:
    """One API process until the block ends, when its facade, once composed, settles and it goes
    down: `POST /orders` mounted over its OMS runtime, which is ready unless `ready` is False, and
    then composed nothing to settle (CR-S3L2X-01). Its own pools, both on `dsn` (the OMS stores',
    and the profile cache's unless `profiles` stands in), metrics and 24 h record; the venue, the
    audit log and the pager are the world's."""
    metrics = Metrics("demo")
    process_dsn = dsn or c6._login(world.dsn, "cv_app")
    pool = SqlAlchemyRelationalRepository(process_dsn, "place-order-route-it")
    cache = EffectiveProfiles(SqlAlchemyAccountProfileStore(pool)) if profiles is None else profiles
    runtime = _runtime(world, process_dsn, cache, metrics)
    app = FastAPI()
    app.include_router(
        make_orders_router(
            _owner(world.user), lambda: runtime, audit=world.writer,
            records=OmsAudit(world.writer, environment="demo"), oms_enabled=lambda: True,
            metrics=metrics, pager=world.pager,
        )
    )  # fmt: skip
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://cv")
    try:
        async with started(runtime), client:
            if ready:
                await asyncio.wait_for(runtime.wait_ready(), _READY_BOUND_S)
            yield client
            if ready:  # composed: a runtime never ready here composed nothing (CR-S3L2X-01)
                parts = runtime._composed()  # the facade's tasks are the order lane's (CV-C13)
                async with asyncio.timeout(_READY_BOUND_S):  # its turns settle (`Rig.settle`)
                    for _ in range(4):
                        for _ in range(32):
                            await asyncio.sleep(0)
                        await parts.lane.call(parts.machines.idle())
    finally:
        await pool.dispose()


async def _post(client: httpx.AsyncClient, body: dict[str, Any]) -> httpx.Response:
    return await client.post("/orders", json=body, headers={"Idempotency-Key": str(KEY)})


def _entry(body: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """An entry's `202`: its one-leg group, the leg, and the leg's one order."""
    group = body["trade_group"]
    (leg,) = group["legs"]
    (order,) = leg["order_details"]
    return group, leg, order


async def test_happy_path_is_an_acceptance_not_a_fill(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gherkin "Happy path is an acceptance, not a fill": 202 with the one-leg trade group
    (`submitting`), its leg and its order `submitted` (`state` `accepted`, 22 `OrderState`), and
    nothing in the body or the rows claims a fill. The intent is recorded ahead of the one create,
    which carries the persisted id and the native stop: the audit log, copied as the create leaves
    for the venue, already holds it (C-2.9, C-2.10, C-2.6)."""
    at_send: list[list[tuple[str, str | None]]] = []  # the audit log, as each create leaves
    land = world.port.place_order

    async def sent(create: PlaceOrderRequest) -> Any:
        at_send.append(list(world.writer.actions))
        return await land(create)

    monkeypatch.setattr(world.port, "place_order", sent)
    async with _serving(world) as client:
        calls = len(world.port.calls)
        answer = await _post(client, world.body)
    assert answer.status_code == 202 and "idempotency-replayed" not in answer.headers
    validate(answer.json())
    group, leg, order = _entry(answer.json())
    assert (answer.json()["order"], answer.json()["reconciling"]) == (None, False)
    assert (group["status"], leg["status"], order["state"], order["lifecycle_state"]) == (
        "submitting", "submitted", "accepted", "submitted",
    )  # fmt: skip
    assert (Decimal(order["filled_qty"]), order["avg_fill_price"]) == (Decimal(0), None)
    row = c6._order(world.dsn, UUID(order["id"]))
    assert (row.lifecycle_state, row.cum_exec_qty, c6._fills(world.dsn, UUID(order["id"]))) == (
        "submitted", Decimal(0), 0,
    )  # fmt: skip
    assert c6._group(world.dsn, UUID(group["id"])) == ("submitting", ["submitted"])
    [create] = world.creates(calls)
    assert (create.order_link_id, create.stop_loss) == (row.order_link_id, sr.STOP)
    [log] = at_send  # the one create left with the intent already in the audit log
    assert ("orders.submit", "validated") in log
    assert ("orders.submit", "submitted") in world.writer.actions  # its outcome, after the send


async def test_filters_are_enforced_before_any_exchange_call(world: World) -> None:
    """Gherkin "Filters are enforced before any exchange call", read as before any order call
    (24 Sec.8.4 item 2): the size step's figure reads (step 3c) come first. A price that is no
    multiple of the tick (0.1) is refused 400 `tick_size_violation`; no order call reaches the
    venue, only those reads, and nothing is recorded, the refusal audited before it is answered
    (C-2.9)."""
    async with _serving(world) as client:
        calls = len(world.port.calls)
        answer = await _post(client, world.body | {"price": "60000.05"})
    assert (answer.status_code, answer.json()["code"]) == (400, "tick_size_violation")
    asked = {call.method for call in world.port.calls[calls:]}
    assert asked == _FIGURE_READS and world.held() == _NOTHING
    assert ("orders.submit", "tick_size_violation") in world.writer.actions


async def test_entry_without_a_stop_is_refused(world: World) -> None:
    """Gherkin "Entry without a stop is refused": an entry with no `stop_loss` on an account whose
    profile gives no SL offset. The schema and the model keep an offset on every profile
    (`ap_sl_pos`), so the runtime's profile port answers none for the account (C6 stands its
    resolver in instead): no stop can be applied, and the request is 400 `validation_failed` /
    `native_stop_required` before any exchange call, nothing recorded (C-2.6, C-4.14)."""
    unstopped = {name: value for name, value in world.body.items() if name != "stop_loss"}
    async with _serving(world, profiles=sr.Profiles(held={})) as client:
        calls = len(world.port.calls)
        answer = await _post(client, unstopped)
    problem = answer.json()
    assert (answer.status_code, problem["code"]) == (400, "validation_failed")
    rules = [(error["field"], error["rule"]) for error in problem["errors"]]
    assert rules == [("stop_loss", "native_stop_required")]
    assert (world.port.calls[calls:], world.held()) == ([], _NOTHING)


async def test_transport_failure_lands_in_unknown_never_in_a_retry(world: World) -> None:
    """Gherkin "Transport failure lands in Unknown, never in a retry": the create lands and its
    answer is lost (`LandedThenAmbiguous`, a timeout after the send). The answer is 202 with the
    order `unknown` and `reconciling`; the row is `unknown` with its event, the alert fired for
    it, and the process sent no second create in its life (24 Sec.8.2 S1, C-2.10)."""
    world.port.script("place_order", LandedThenAmbiguous())
    with capture_logs() as logs:
        async with _serving(world) as client:
            calls = len(world.port.calls)
            answer = await _post(client, world.body)
    validate(answer.json())
    order = _entry(answer.json())[2]
    assert (answer.status_code, order["lifecycle_state"], answer.json()["reconciling"]) == (
        202, "unknown", True,
    )  # fmt: skip
    order_id = UUID(order["id"])
    row = c6._order(world.dsn, order_id)
    assert ((row.lifecycle_state, row.state), c6._events(world.dsn, order_id)[-1]) == (
        ("unknown", "unknown"), "unknown",
    )  # fmt: skip
    alerts = [(e["order_id"], e["alert"]) for e in logs if e["event"] == "oms_order_alert"]
    assert (str(order_id), "order_unknown") in alerts
    [create] = world.creates(calls)
    assert create.order_link_id == row.order_link_id


async def test_idempotent_replay(world: World) -> None:
    """Gherkin "Idempotent replay": the same Idempotency-Key and body again get the original answer
    with `Idempotency-Replayed: true` (the 24 h record). After a restart, a new process over the
    same database, its 24 h record empty, answers from the permanent anchor (21 Sec.3.3.10): the
    same rows as read now. No second order and no second create (C-2.10)."""
    async with _serving(world) as client:
        calls = len(world.port.calls)
        first, again = await _post(client, world.body), await _post(client, world.body)
    held = world.held()
    async with _serving(world) as client:
        later = await _post(client, world.body)
    assert first.status_code == 202 and "idempotency-replayed" not in first.headers
    assert (again.status_code, again.headers["idempotency-replayed"]) == (202, "true")
    assert again.content == first.content
    assert (later.status_code, later.headers["idempotency-replayed"]) == (202, "true")
    validate(later.json())
    ids = [tuple(part["id"] for part in _entry(body.json())) for body in (first, later)]
    assert ids[0] == ids[1] and later.json()["reconciling"] is False
    order = _entry(later.json())[2]
    row = c6._order(world.dsn, UUID(order["id"]))
    assert row.exchange_order_id is not None  # the venue acked it: two Nones would compare equal
    assert (order["lifecycle_state"], order["exchange_order_id"]) == (
        "submitted", row.exchange_order_id,
    )  # fmt: skip
    assert _entry(first.json())[2]["exchange_order_id"] is None  # the first answer's own rows
    assert (len(world.creates(calls)), len(c6._orders(world.dsn, world.account))) == (1, 1)
    assert world.held() == held


async def test_order_entry_blocked_when_we_cannot_record_it_postgres_unreachable_at_boot(
    world: World,
) -> None:
    """Gherkin "Order entry blocked when we cannot record it", Postgres unreachable from the start:
    the runtime's start cannot ask the environment's lock and waits to ask again, never ready
    (20 Sec.6.2, CR-S3L2-01), so the request is 503 `oms_not_ready` with `Retry-After` before any
    exchange call: counted, never audited, nothing recorded (24 Sec.8.4 step 3)."""
    relay = _Relay(world.dsn)
    dsn = await relay.through(c6._login(world.dsn, "cv_app"))
    relay.cut()
    async with _serving(world, dsn=dsn, ready=False) as client:
        await asyncio.wait_for(world.retrying.wait(), _READY_BOUND_S)
        calls = len(world.port.calls)
        answer = await _post(client, world.body)
    problem = answer.json()
    assert (answer.status_code, problem["code"]) == (503, "oms_not_ready")
    assert answer.headers["retry-after"] == str(problem["retry_after_seconds"])
    assert (world.port.calls[calls:], world.writer.actions, world.held()) == ([], [], _NOTHING)


async def test_order_entry_blocked_when_we_cannot_record_it_postgres_unreachable_once_ready(
    world: World,
) -> None:
    """Gherkin "Order entry blocked when we cannot record it", Postgres unreachable once the OMS is
    ready: the request cannot be looked up (step 8's anchor read meets the cut), so it is 503
    `store_unavailable` before any exchange call (24 Sec.8.4, S7), its refusal audited first
    (C-2.9), nothing recorded. The persist that cannot record is C6's: its hanging-store and
    stopped-Postgres tests (`test_order_entry_blocked_when_we_cannot_record_it_a_*`)."""
    relay = _Relay(world.dsn)
    dsn = await relay.through(c6._login(world.dsn, "cv_app"))
    try:
        async with _serving(world, dsn=dsn) as client:
            relay.cut()
            calls = len(world.port.calls)
            answer = await _post(client, world.body)
    finally:
        relay.cut()
    assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")
    assert (world.port.calls[calls:], world.held()) == ([], _NOTHING)
    assert ("orders.submit", "store_unavailable") in world.writer.actions
