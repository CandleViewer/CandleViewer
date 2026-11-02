"""Integration (E29-T05 #848, S9): the private stream on real Postgres 16, over C6's database
(`test_submission_pipeline_pg.py`, shared by import).

**The replay.** A first process (C6's pipeline) leaves an entry `submitted` and goes down. A second
process's OMS runtime (S8b), its stores on `pg_stores`' own pool and its standalone
`machine_events` WAL sink in `tmp_path`, hydrates it and, once ready, starts its consumer on the
order lane. The consumer subscribes the account on the lane's port, across the lane bridge
(`oms_streams.LaneStreams`), to the account's stream in the adapter's registry on the serving loop:
here a scripted session, derived in-test from the corpus's docs transcriptions and read by the
adapter's own parser (derived, not evidence; the recorded session is E29-K01's, #843). It holds the
order row, a fill, a disconnect, the reconnect, a fill, a bundle of that fill again and a third,
the `Filled` row, a position row and a wallet row. Keeping a fill until the backfill is E29-T06's
(the ruling Q2), and so are the reconciliation passes the runtime runs (#914): the port's REST
side answers what the session reports, so they read the venue the stream does.

**Scenario 8.** The position store `pg_stores` builds, over an exchange-synced clock
(`ExchangeWallClock`) whose host time and measured offset the test moves, under the consumer as
`build_stream_consumer` composes it (`stream_world`, on the test's own loop: a store across a
socket takes real time, so these tests never run on fake seconds)."""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
import pytest_asyncio
from pydantic import SecretStr
from structlog.testing import capture_logs

from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.exchange.base.models import (
    AccountRef,
    Execution,
    Order,
    Position,
    PrivateEvent,
    PrivateStreamStatus,
)
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.fakes import FakeClockHealth
from candleviewer.oms.repository import PositionRepository, PositionSnapshotRepository
from candleviewer.oms_stream_wiring import ExchangeWallClock
from candleviewer.oms_wiring import OmsRuntime, pg_stores
from candleviewer.settings import Settings
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.trading_accounts import (
    InMemoryTradingAccountReads,
    TradingAccountRow,
)
from tests.integration.oms import test_submission_pipeline_pg as c6
from tests.integration.oms.test_submission_pipeline_pg import pg_dsn
from tests.unit.exchange.bybit._private import linear_execution, linear_order, row, usdt_wallet
from tests.unit.oms import command_rig as cr
from tests.unit.oms.order_rig import Pager
from tests.unit.oms.stream_world import RESYNCING, opened
from tests.unit.oms.submit_rig import REGISTRY, STOP, Profiles, ReadOnly
from tests.unit.oms.test_e29_t05_acceptance import (
    FEE_RATE,
    FILLS,
    ORDERS,
    POSITIONS,
    WALLET,
    parsed,
)
from tests.unit.oms.test_oms_runtime import (
    Binder,
    BridgedPort,
    BridgedVenue,
    Flag,
    Hub,
    Port,
    Tracked,
    Writer,
    started,
)

pytestmark = pytest.mark.integration
__all__ = ["pg_dsn"]  # C6's database for this module

#: How long a step may take on Postgres: the bound only turns a hang into a failure.
BOUND_S = 30.0


@pytest.fixture(autouse=True)
def _own_attempts(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """B1's command attempts are this test's (one facade per process)."""
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    yield


@pytest_asyncio.fixture
async def rel(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    repo = SqlAlchemyRelationalRepository(c6._login(pg_dsn, "cv_app"), c6._APP)
    try:
        yield repo
    finally:
        await repo.dispose()


class Session:
    """The account's stream in the adapter's registry, read on the serving loop and `Batched`, as
    the registry's is: the items the test queues, in arrival order, `ready()` those queued now.
    `starved` is set when its reader asks for more and finds none: the consumer, which takes the
    next item only once it has handled the last, has handled every item before. It ends once
    closed."""

    def __init__(self) -> None:
        self._items: deque[Any] = deque()
        self._more = asyncio.Event()
        self.starved = asyncio.Event()
        self.closed = False

    def put(self, *items: Any) -> None:
        self.starved.clear()
        self._items.extend(items)
        self._more.set()

    def ready(self) -> int:
        return len(self._items)

    def __aiter__(self) -> Session:
        return self

    async def __anext__(self) -> Any:
        while not self._items:
            if self.closed:
                raise StopAsyncIteration
            self._more.clear()
            self.starved.set()
            await self._more.wait()
        return self._items.popleft()

    async def aclose(self) -> None:
        self.closed = True
        self._more.set()

    async def handled(self) -> None:
        async with asyncio.timeout(BOUND_S):
            await self.starved.wait()


type Truth = Order | Execution | Position


class ReplayPort(BridgedPort):
    """The lane's port, its REST side the venue's as the session reports it (`ReplayVenue`): an
    account-wide open-orders read, a reconciliation pass's first (24 Sec.8.5 step 1), waits while
    the venue holds the passes back."""

    venue: ReplayVenue

    async def open_orders(
        self, account: AccountRef, symbol: Any = None, *, order_link_id: Any = None
    ) -> Any:
        held = self.venue.held
        if held is not None and symbol is None and order_link_id is None:
            await asyncio.wrap_future(held)
        return await super().open_orders(account, symbol, order_link_id=order_link_id)

    def learn(self, rows: Iterable[Truth]) -> None:
        """The REST side takes `rows` as the session reports them: an order replaces its earlier
        self (open, or in history once ended), a fill is listed, a position replaces its key's."""
        for taken in rows:
            if isinstance(taken, Order):
                self._open.pop(taken.exchange_order_id, None)
                self.seed_order(taken, uid=self.venue.uid)
            elif isinstance(taken, Execution):
                self.seed_execution(taken)
            else:
                self.seed_position(taken)


@dataclass
class ReplayVenue(BridgedVenue):
    """The adapter's service: the lane's port opens the account's stream through the lane bridge
    it is given (`BridgedVenue`), and the registry's open answers the scripted session. The port's
    REST side holds what the session reports at the venue by then (`truth`, then `learned`), so a
    reconciliation pass reads the venue the stream does: the entry open, as the session's first
    order row shows it; once its first fill lands, the fill and the position it opens, so the
    entry's stop attach reads its stop back (24 Sec.8.8 rule 2); and the session's end. While the
    test holds the passes back (`hold`), a pass's first read waits until it lets them go."""

    session: Session = field(default_factory=Session)
    truth: list[Truth] = field(default_factory=list)
    uid: str = ""
    now_us: Callable[[], int] = lambda: 0
    held: concurrent.futures.Future[None] | None = None

    def port(self, env: str) -> Port:
        port = ReplayPort(environment=cast(Environment, env), now_us=self.now_us)
        port.asked, port.venue = [], self
        port.learn(self.truth)
        return port

    async def learned(self, runtime: OmsRuntime, *rows: Truth) -> None:
        """The REST side takes `rows`, on the lane, where its port answers."""
        port = cast(ReplayPort, self.ports[-1])

        async def learn() -> None:
            port.learn(rows)

        await runtime._composed().lane.call(learn())

    def hold(self) -> None:
        self.held = concurrent.futures.Future()

    def release(self) -> None:
        assert self.held is not None
        self.held.set_result(None)

    async def open_private_stream(self, account: AccountRef, *, clock_offset_ms: Any = None) -> Any:
        self.opened.set()
        return self.session


def _rest(*events: Iterable[PrivateEvent]) -> list[Truth]:
    """What the venue's REST reads return for the session's rows: the adapter's own read of each
    (`parsed`), so the two sides agree by construction."""
    return [cast(Truth, event.payload) for batch in events for event in batch]


def _passes(writer: Writer) -> list[tuple[str, str]]:
    """Each reconciliation pass's trigger and result, from its `oms.reconcile` record (24
    Sec.15.5), in the order the passes ended."""
    return [
        (fields["after_state"]["trigger"], fields["after_state"]["result"])
        for action, fields in writer.records
        if action == "oms.reconcile"
    ]


async def _rested(runtime: OmsRuntime, account: UUID) -> str | None:
    """The state of the account's reconciliation job once it rests with nothing left to run, past
    its record's write (the driver's own wait, on the lane, where the job runs)."""
    parts = runtime._composed()
    assert parts.reconcile is not None
    jobs, account_id = parts.reconcile.jobs, AccountId(account)
    await parts.lane.call(jobs._quiesced(jobs._jobs[account_id].interp))
    return jobs.state(account_id)


async def _submitted(rel: SqlAlchemyRelationalRepository, dsn: str) -> tuple[c6.Rig, UUID]:
    """A first process's entry, sent and acknowledged (`submitted`), then the process down: its
    facade stops and its attempts go with its memory."""
    rig = c6._build(
        rel, account=c6._trading_account(dsn), user=c6._user(dsn), clock=c6.Clock(c6._db_now(dsn))
    )
    try:
        outcome = await rig.submit()
    finally:
        await rig.machines.stop()
        b01._ATTEMPTS.clear()
    assert (outcome.status, outcome.lifecycle) == (202, "submitted") and outcome.order_id
    return rig, outcome.order_id


def _runtime(
    rig: c6.Rig, dsn: str, tmp_path: Path, venue: ReplayVenue, parts: SimpleNamespace
) -> OmsRuntime:
    """The second process's runtime over the same database: the real stores and the standalone
    WAL sink, the account read in memory (C6's has no key row), the clock guard measured; account
    health streams the one account, and the hub, the audit writer, the pager and the metrics are
    `parts`'."""
    settings = Settings(
        storage_backend="real", pg_dsn=SecretStr(c6._login(dsn, "cv_app")),
        machine_event_wal_path=str(tmp_path / "machine_events.wal"),
    )  # fmt: skip
    metrics = parts.metrics
    key = UUID(cr.KEYS["demo"])
    account = TradingAccountRow(rig.account, "demo", c6._uid(rig.account), False, key)
    flags = (Flag(), Flag())
    for flag in flags:
        flag.read()
    guard = FakeClockHealth(cr.Monotonic())
    guard.measure()
    return OmsRuntime(
        settings, venue=venue,
        ingestion=SimpleNamespace(
            clock=guard, tickers=None, instruments=None, clock_offset_snapshot_ms=lambda: None
        ),
        read_only=ReadOnly(), metrics=metrics, gate=SimpleNamespace(refusal=lambda _account: None),
        standings=SimpleNamespace(read_once=True, credential_rejected=lambda *_args: None),
        oms_enabled=flags[0], live_enabled=flags[1], profiles=Profiles(), persistence=None,
        feed=SimpleNamespace(bind=lambda _b: SimpleNamespace(publish=lambda *_a, **_k: None)),
        lane_signing=cast(Any, Binder()), health=cast(Any, parts.health), hub=cast(Any, parts.hub),
        stores=lambda: replace(  # the lane's own writer is the test's (#913 L2)
            pg_stores(settings, metrics), accounts=InMemoryTradingAccountReads(account),
            audit=lambda _alarm: parts.writer,
        ),
        pager=parts.pager, now=rig.clock, registry=REGISTRY, fencing=_unfenced,
    )  # fmt: skip


async def _unfenced(_seconds: float) -> None:
    """The fencing grace (SEC-S3L2-01) passed at once: no other process held the lock."""


def _ms(at: datetime) -> int:
    return round(at.timestamp() * 1_000)


def _terms(dsn: str, order_id: UUID) -> tuple[Decimal, Decimal, str, str]:
    """The order's quantity, price, `order_link_id` and bound exchange order id."""
    [(qty, price, link, xid)] = c6._sql(
        dsn,
        "SELECT qty, price, order_link_id, exchange_order_id FROM orders WHERE id = %s",
        order_id,
    )
    return Decimal(qty), Decimal(price), str(link), str(xid)


def _text(value: Decimal) -> str:
    """A figure as the venue writes it: plain, with no trailing zero (`numeric(38,18)` reads back
    with eighteen)."""
    return format(value.normalize(), "f")


def _position(at: datetime, **over: Any) -> dict[str, Any]:
    """A long of 0.01 BTCUSDT holding its stop, as of `at` on the venue's clock (derived)."""
    values: dict[str, Any] = {"positionIdx": 0, "side": "Buy", "size": "0.01"}
    values |= {"entryPrice": "60000"}
    values |= {"markPrice": "60000", "stopLoss": str(STOP), "updatedTime": str(_ms(at))}
    return row("position") | values | over


def _snapshots(dsn: str, account: UUID) -> int:
    """The account's `position_snapshots` rows the stream wrote (`ws_push`)."""
    [(count,)] = c6._sql(
        dsn,
        "SELECT count(*) FROM position_snapshots "
        "WHERE exchange_account_id = %s AND reason = 'ws_push'",
        account,
    )
    return int(count)


async def _until(done: Any) -> None:
    """Loop turns until `done()`: a hop from the lane lands between them; the bound only turns a
    hang into a failure (03 Sec.14)."""
    async with asyncio.timeout(BOUND_S):
        while not done():  # noqa: ASYNC110 - the lane's notices to this loop, bounded above
            await asyncio.sleep(0)


async def test_a_private_session_replayed_across_a_mid_sequence_disconnect_misses_no_execution(
    rel: SqlAlchemyRelationalRepository, pg_dsn: str, tmp_path: Path
) -> None:
    """The test plan's integration case, E29-T05's half (scenarios 2 and 4 on Postgres), with
    E29-T06's reconciliation wired: a session replayed through the runtime, across the lane
    bridge, with a disconnect in its middle, its statuses as 24 Sec.14.2 rule 13 orders them. Each
    of its three fills is one `executions` row, its order `filled` with their sum; the position row
    is one `ws_push` snapshot; the drop is one notice. The venue's REST side answers what the
    session reports, so the passes read the venue the stream does: the startup pass, before the
    session, finds nothing to correct; the first `live`'s request starts a pass, which the test
    holds at its first read until the session's end is in, so the reconnect's request finds it
    running and is skipped, never queued (24 Sec.8.5); that pass reads the session's end and finds
    nothing to correct either. No request is refused, nothing pages and nothing opens the
    lockout."""
    rig, order_id = await _submitted(rel, pg_dsn)
    qty, price, link, xid = _terms(pg_dsn, order_id)
    at_ms = _ms(c6._db_now(pg_dsn)) - 1_000
    ref = rig.ref()

    def read(topic: str, *rows: dict[str, Any]) -> list[Any]:
        return list(parsed(topic, rows, ref, at_ms * 1_000))

    def status(state: str, reason: str, epoch: int) -> PrivateStreamStatus:
        values = {"account_id": rig.account, "state": state, "reason": reason, "epoch": epoch}
        return PrivateStreamStatus.model_validate(values | {"ts": at_ms * 1_000})

    def fill(exec_id: str, share: str, seq: int) -> dict[str, Any]:
        values: dict[str, Any] = {"orderId": xid, "orderLinkId": link, "execId": exec_id}
        part = qty * Decimal(share)
        values |= {"execQty": _text(part), "execPrice": _text(price), "seq": seq}
        values |= {"execFee": _text(part * price * FEE_RATE), "feeRate": _text(FEE_RATE)}
        values |= {"side": "Buy"}
        return linear_execution(**(values | {"execTime": str(at_ms), "isMaker": False}))

    def order(status: str, filled: Decimal) -> dict[str, Any]:
        values = {"orderId": xid, "orderLinkId": link, "side": "Buy", "orderType": "Limit"}
        values |= {"price": _text(price), "qty": _text(qty), "timeInForce": "GTC"}
        values |= {"orderStatus": status, "cumExecQty": _text(filled), "leavesQty": "0"}
        return linear_order(**(values | {"createdTime": str(at_ms), "updatedTime": str(at_ms)}))

    e1, e2, e3 = fill("e1", "0.4", 1), fill("e2", "0.3", 2), fill("e3", "0.3", 3)
    position = _position(c6._db_now(pg_dsn) - timedelta(seconds=1))
    parts = SimpleNamespace(
        health=Tracked(accounts=frozenset({rig.account})), hub=Hub(), writer=Writer(),
        pager=Pager(), metrics=Metrics("demo"),
    )  # fmt: skip
    first = Position(  # what e1 opens at the venue, its stop not attached yet
        account_id=rig.account, symbol="BTCUSDT", position_idx=0, side="buy",
        qty=qty * Decimal("0.4"), avg_entry_price=price, mark_price=price, liq_price=None,
        leverage=Decimal(10), unrealised_pnl=Decimal(0), cum_realised_pnl=Decimal(0),
        take_profit=None, stop_loss=None, trailing_stop_distance=None, updated_at=rig.clock.us(),
    )  # fmt: skip
    entry = _rest(read(ORDERS, order("New", Decimal(0))))  # open at the venue, as at the restart
    venue = ReplayVenue(truth=entry, uid=ref.uid, now_us=rig.clock.us)
    async with started(_runtime(rig, pg_dsn, tmp_path, venue, parts)) as runtime:
        await asyncio.wait_for(runtime.wait_ready(), BOUND_S)
        await asyncio.wait_for(venue.opened.wait(), BOUND_S)
        await _until(lambda: len(_passes(parts.writer)) == 1)  # the startup pass, before it all
        assert await _rested(runtime, rig.account) == "idle"  # where the next trigger is taken
        venue.hold()  # the next pass's first read waits for the session's end
        session = venue.session
        await venue.learned(runtime, *_rest(read(FILLS, e1)), first)
        session.put(status("resyncing", "connected", 1))  # the stream's first `live`: a pass
        session.put(*read(ORDERS, order("New", Decimal(0))), *read(FILLS, e1))
        session.put(status("down", "socket_closed", 1))  # the socket drops mid-sequence
        await session.handled()
        ended = _rest(read(ORDERS, order("Filled", qty)), read(FILLS, e2, e3))
        await venue.learned(runtime, *ended, *_rest(read(POSITIONS, position)))
        session.put(
            status("resyncing", "reconnected", 2), *read(FILLS, e2), *read(FILLS, e2, e3),
            *read(ORDERS, order("Filled", qty)), *read(POSITIONS, position),
            *read(WALLET, usdt_wallet()),
        )  # fmt: skip
        await session.handled()
        await _until(lambda: ("wallet_pushed", rig.account) in parts.health.evidence)
        venue.release()  # the held pass reads the session's end
        await _until(lambda: len(_passes(parts.writer)) == 2)
    executions = c6._sql(
        pg_dsn,
        "SELECT exec_id, count(*) FROM executions WHERE exchange_account_id = %s "
        "GROUP BY exec_id ORDER BY exec_id",
        rig.account,
    )
    assert [(str(e), int(n)) for e, n in executions] == [("e1", 1), ("e2", 1), ("e3", 1)]
    after = c6._order(pg_dsn, order_id)
    assert (after.lifecycle_state, after.cum_exec_qty) == ("filled", qty)
    assert _snapshots(pg_dsn, rig.account) == 1
    frames = [(f["reason"], f["exchange_account_ids"]) for f in parts.hub.frames]
    assert frames == [(RESYNCING, [str(rig.account)])]
    labels = {"env": "demo", "stage": "consumer", "outcome": "reconciliation_unavailable"}
    refused = parts.metrics.registry.get_sample_value("oms_stream_outcomes_total", labels)
    assert (refused, parts.pager.calls) == (0.0, [])  # each request taken: nothing paged
    assert _passes(parts.writer) == [("startup", "clean"), ("reconnect", "clean")]
    assert "oms.no_intent_detected" not in [action for action, _ in parts.writer.actions]


@dataclass
class Host:
    """The host's clock, and the clock guard's measured offset (ms, server minus local): both the
    test's to move."""

    at: datetime
    offset: int | None = None

    def __call__(self) -> datetime:
        return self.at

    def offset_ms(self) -> int | None:
        return self.offset


def _positions(dsn: str, account: UUID) -> list[datetime]:
    rows = c6._sql(
        dsn, "SELECT exchange_updated_ts FROM positions WHERE exchange_account_id = %s", account
    )
    return [stamp for (stamp,) in rows]


async def test_a_position_stamped_ahead_of_the_clock_is_refused_and_alerted(pg_dsn: str) -> None:
    """Gherkin "A position stamped ahead of the clock is refused and alerted": the venue's clock
    10 s ahead of the host's, the offset unmeasured, the store refuses the row
    (`FutureDatedPositionError`) and writes nothing; it is logged with its account and symbol,
    counted and paged once at critical (`page`). A measured offset past the clock guard's drift is
    never applied (`MAX_OFFSET_MS`): still refused. Once the host's clock steps forward and the
    guard measures within its drift, the clock's epoch moves and the held row is applied."""
    account = AccountId(c6._trading_account(pg_dsn))
    now = c6._db_now(pg_dsn)
    host = Host(now.replace(microsecond=now.microsecond // 1_000 * 1_000))  # a venue time is ms
    t0 = host.at
    settings = Settings(storage_backend="real", pg_dsn=SecretStr(c6._login(pg_dsn, "cv_app")))
    stores = pg_stores(settings, Metrics("demo"))
    clock = ExchangeWallClock(host.offset_ms, now=host)
    store = stores.positions(clock)  # the runtime's own builder (CG14)
    guard = FakeClockHealth(cr.Monotonic())  # unmeasured
    ports = {"positions": PositionRepository(store), "snapshots": PositionSnapshotRepository(store)}
    ports |= {"clock": clock, "clock_health": guard, "offset_ms": host.offset_ms, "wall_now": host}
    dated = ("page", "oms.positions", "a position push is dated ahead of the clock: clock fault")
    try:
        # The refusals send no statement (`FutureDatedPositionError` comes first), so warm the
        # pool here: the re-apply's 4 s bound (`REAPPLY_BOUND_S`) then covers its upsert, never
        # the engine's first connect.
        assert await store.list_open(account) == ()
        async with opened(parsed, account, **ports) as w:
            with capture_logs() as logs:
                ahead = t0 + timedelta(seconds=10)  # the venue's clock, 10 s ahead of the host's
                w.send(POSITIONS, _position(ahead), who=account, at_us=_ms(t0) * 1_000)
                await w.until(lambda: w.count("position", "future_dated") == 1)
            [log] = [e for e in logs if e["event"] == "position_future_dated"]
            assert (log["account_id"], log["symbol"]) == (str(account), "BTCUSDT")
            assert _positions(pg_dsn, account) == [] and _snapshots(pg_dsn, account) == 0
            assert w.pages == [dated]
            guard.measure(10_000)  # measured past the guard's drift: never applied
            host.offset = 10_000
            assert clock() == t0
            later = ahead + timedelta(milliseconds=500)
            w.send(POSITIONS, _position(later), who=account, at_us=_ms(t0) * 1_000)
            await w.until(lambda: w.count("position", "future_dated") == 2)
            assert _positions(pg_dsn, account) == [] and w.pages == [dated]
            host.at, host.offset = ahead, 250  # the host's clock steps forward; measured
            guard.measure(250)
            w.status("heartbeat", "evidence", who=account)  # the account's next item
            await w.until(lambda: w.count("position", "reapplied") == 1)
            assert _positions(pg_dsn, account) == [later] and _snapshots(pg_dsn, account) == 1
            assert w.pages == [dated]
    finally:
        await stores.release()
