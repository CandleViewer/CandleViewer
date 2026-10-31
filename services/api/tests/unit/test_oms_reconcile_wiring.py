"""Reconciliation's composition (E29-T06 #914 PR 2b; 24 Sec.8.5, Sec.15.5; 23 Sec.15.9): each
adapter binds a pass port to its store or writer as the runtime composes it, and
`build_reconciliation` wires the pass, its phases and the driver together. No network, no sleeps.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer import oms_reconcile_wiring as rw
from candleviewer.oms.reconcile_job import ReconcileJobs
from candleviewer.oms.reconcile_report import Notice
from candleviewer.oms.reconciler import PositionDriftSeen
from candleviewer.storage.repositories.positions import PositionRow
from tests.unit.oms.reconcile_rig import ACCOUNT, OTHER, position, record, remote, row

T0 = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
RUN_ID = "00000000-0000-4000-8000-0000000000a1"


@dataclass
class Reads:
    """`ReconcileReads`, recording each call."""

    mark: datetime | None = None
    moves: bool = True
    calls: list[tuple[Any, ...]] = field(default_factory=list)

    async def unfinished_for(self, account_id: UUID) -> Any:
        self.calls.append(("unfinished_for", account_id))
        return (row(1),)

    async def stored(self, account_id: UUID, exec_ids: Any) -> frozenset[str]:
        self.calls.append(("stored", account_id, tuple(exec_ids)))
        return frozenset({"e1"})

    async def live_for_account(self, account_id: UUID) -> Any:
        self.calls.append(("live_for_account", account_id))
        return (record(),)

    async def last_reconciled(self, account_id: UUID) -> datetime | None:
        return self.mark

    async def advance(self, account_id: UUID, to: datetime) -> bool:
        self.calls.append(("advance", account_id, to))
        return self.moves


class Lookups:
    async def get_by_exchange_order_id(self, account_id: UUID, xid: str) -> Any:
        return row(1) if xid == "x1" else None

    async def get_by_link_id(self, account_id: UUID, link: str) -> Any:
        return None

    async def link_id_taken(self, link: str) -> bool:
        return link == "taken"


async def test_the_store_adapters_bind_each_pass_port_to_its_read() -> None:
    reads = Reads()
    inserted: list[Any] = []

    class Fills:
        async def insert(self, execution: Any) -> bool:
            inserted.append(execution)
            return True

    orders, fills, stops = (
        rw.PassOrders(reads, Lookups()),
        rw.PassFills(reads, Fills()),
        rw.PassStops(reads),
    )
    assert [r.order_link_id for r in await orders.unfinished_for(ACCOUNT)] == [row(1).order_link_id]
    assert await orders.get_by_exchange_order_id(ACCOUNT, "x1") == row(1)
    assert await orders.get_by_link_id(ACCOUNT, "l") is None
    assert await orders.link_id_taken("taken") is True
    assert await fills.stored(ACCOUNT, ["e1", "e2"]) == frozenset({"e1"})
    assert await fills.insert(SimpleNamespace(exec_id="e9")) is True and len(inserted) == 1
    assert await stops.live_for_account(ACCOUNT) == (record(),)
    assert ("stored", ACCOUNT, ("e1", "e2")) in reads.calls


async def test_the_watermark_is_kept_in_microseconds_and_a_mark_not_taken_is_logged() -> None:
    reads = Reads(mark=T0)
    marks = rw.AccountWatermarks(reads)
    at_us = (T0 - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(microseconds=1)
    assert await marks.last_reconciled_us(ACCOUNT) == at_us
    await marks.advance(ACCOUNT, at_us + 30_000_000)
    assert reads.calls[-1] == ("advance", ACCOUNT, T0 + timedelta(seconds=30))
    reads.moves, reads.mark = False, None
    with capture_logs() as logs:
        await marks.advance(ACCOUNT, at_us)
    assert [e["event"] for e in logs] == ["reconcile_watermark_not_moved"]
    assert await marks.last_reconciled_us(ACCOUNT) is None


# --- The positions' REST side --------------------------------------------------------------------


def _stored(**over: Any) -> PositionRow:
    values: dict[str, Any] = {
        "exchange_account_id": ACCOUNT, "symbol": "BTCUSDT", "size": Decimal("0.2"),
        "position_idx": 0, "side": "Buy", "exchange_updated_ts": T0,
    }  # fmt: skip
    base = {f: None for f in PositionRow.__dataclass_fields__}
    return PositionRow(**(base | values | over))


@dataclass
class Positions:
    held: list[PositionRow] = field(default_factory=list)
    keep_older: bool = False
    upserts: list[Any] = field(default_factory=list)
    snapshots: list[Any] = field(default_factory=list)
    refuse_snapshot: bool = False

    async def list_open(self, account_id: UUID) -> Any:
        return tuple(self.held)

    async def upsert(self, state: Any) -> PositionRow:
        self.upserts.append(state)
        if self.keep_older:  # the store kept a newer row than this read
            return _stored(exchange_updated_ts=state.exchange_updated_ts + timedelta(seconds=1))
        return _stored(
            size=state.size, side=state.side, exchange_updated_ts=state.exchange_updated_ts
        )

    async def append(self, snapshot: Any) -> Any:
        if self.refuse_snapshot:
            raise ConnectionError("the snapshot store is down")
        self.snapshots.append(snapshot)
        return snapshot


async def test_positions_truth_reads_what_the_projection_holds_by_key() -> None:
    p = Positions(held=[_stored(), _stored(symbol="ETHUSDT", side="Sell", size=Decimal(3))])
    truth = rw.PositionsTruth(p, p, p)
    assert await truth.held(ACCOUNT) == {
        ("BTCUSDT", 0): PositionDriftSeen("buy", Decimal("0.2")),
        ("ETHUSDT", 0): PositionDriftSeen("sell", Decimal(3)),
    }


async def test_positions_truth_applies_a_read_that_changed_it_and_snapshots_it() -> None:
    """Step 4 (24 Sec.8.5): the exchange's read is applied, `rest_reconcile` snapshotted, and the
    position the OMS held before is answered for the report's drift (both values, S3)."""
    p = Positions(held=[_stored(size=Decimal("0.2"))])
    seen = await rw.PositionsTruth(p, p, p).apply(position(qty=Decimal("0.1")), pass_id=RUN_ID)
    assert seen == PositionDriftSeen("buy", Decimal("0.2"))
    [state] = p.upserts
    assert (state.size, state.side) == (Decimal("0.1"), "Buy")
    [snap] = p.snapshots
    assert (snap.reason, snap.size) == ("rest_reconcile", Decimal("0.1"))


async def test_positions_truth_answers_none_for_an_equal_or_older_read() -> None:
    p = Positions(held=[_stored()])
    assert await rw.PositionsTruth(p, p, p).apply(position(), pass_id=RUN_ID) is None
    older = Positions(held=[_stored(size=Decimal(1))], keep_older=True)
    assert await rw.PositionsTruth(older, older, older).apply(position(), pass_id=RUN_ID) is None
    assert p.snapshots == older.snapshots == []


async def test_positions_truth_takes_a_new_position_and_keeps_a_correction_unsnapshotted() -> None:
    p = Positions(refuse_snapshot=True)
    with capture_logs() as logs:
        seen = await rw.PositionsTruth(p, p, p).apply(position(), pass_id=RUN_ID)
    assert seen == PositionDriftSeen(None, Decimal(0))  # the OMS held none: drift from nothing
    assert [e["event"] for e in logs] == ["reconcile_snapshot_failed"]


# --- The records (C-2.9) and the notices (23 Sec.15.9) --------------------------------------------


class Emitter:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, action: str, **fields: Any) -> None:
        self.emitted.append((action, fields))


async def test_the_reports_record_is_oms_reconcile_finished_as_the_system() -> None:
    emitter = Emitter()
    await rw.ReconcileRecords(emitter, environment="demo").finished(
        ACCOUNT, pass_id=RUN_ID, state={"stage": "finished", "result": "clean"}
    )
    [(action, fields)] = emitter.emitted
    assert action == "oms.reconcile" and fields["actor_label"] == "system:oms"
    assert (fields["object_kind"], fields["object_id"]) == ("exchange_account", str(ACCOUNT))
    assert fields["after_state"]["stage"] == "finished" and fields["request_id"] is None


async def test_an_adoption_is_recorded_with_the_venues_identity_and_no_payload() -> None:
    """24 Sec.15.5, BQ-17: written ahead of the row, the order as the venue reported it."""
    emitter, order = Emitter(), remote(7, exchange_placed=True)
    row_id = UUID(int=0xC1)
    await rw.AdoptionRecords(emitter, environment="demo").adopted(
        ACCOUNT, row_id=row_id, order=order, pass_id=RUN_ID
    )
    [(action, fields)] = emitter.emitted
    assert action == "order.adopted_untracked" and fields["object_id"] == str(row_id)
    state = fields["after_state"]
    assert (state["exchange_order_id"], state["exchange_placed"], state["qty"]) == ("x7", True, "1")
    assert set(state) == {
        "account_id", "exchange_order_id", "order_link_id", "symbol", "side", "qty",
        "order_type", "price", "exchange_placed", "pass_id",
    }  # fmt: skip


class Hub:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    def broadcast_system(self, body: dict[str, Any]) -> int:
        self.frames.append(body)
        return 1


class Serving:
    def notify(self, fn: Any, /, *args: Any, **kwargs: Any) -> None:
        fn(*args, **kwargs)


@pytest.mark.parametrize(
    ("notice", "message"),
    [
        (Notice("oms.account_desync", "warning"), "Reconciliation found a difference"),
        (Notice("oms.account_desync", "critical"), "Reconciliation found a difference"),
        (Notice("oms.account_stale", "critical"), "Order entry on an account is refused"),
        (Notice("oms.account_synced", "info"), "An account is reconciled"),
    ],
)
def test_each_notice_is_its_closed_rows_frame_on_the_system_topic(
    notice: Notice, message: str
) -> None:
    hub = Hub()
    rw.ReconcileNoticesBinding(hub, Serving()).publish(ACCOUNT, notice)
    [frame] = hub.frames
    assert (frame["reason"], frame["severity"]) == (notice.reason, notice.severity)
    assert frame["message"].startswith(message) and str(ACCOUNT) not in frame["message"]
    assert frame["exchange_account_ids"] == [str(ACCOUNT)]


def test_a_notice_off_the_closed_table_is_logged_never_sent() -> None:
    hub = Hub()
    with capture_logs() as logs:
        rw.ReconcileNoticesBinding(hub, Serving()).publish(
            ACCOUNT, Notice("oms.account_synced", "critical")
        )
    assert hub.frames == [] and [e["event"] for e in logs] == ["reconcile_notice_refused"]


def test_the_streams_last_message_is_marked_on_each_piece_of_evidence() -> None:
    seen: list[tuple[str, Any]] = []

    class Feed:
        def ws_heartbeat(self, account_id: Any) -> object:
            seen.append(("heartbeat", account_id))
            return None

        def ws_dropped(self, account_id: Any) -> object:
            seen.append(("dropped", account_id))
            return None

        def wallet_pushed(self, account_id: Any, snapshot: Any) -> object:
            seen.append(("wallet", account_id))
            return None

    clock = iter([10, 20])
    marks = rw.LastMessages(Feed(), lambda: next(clock))
    assert marks.last_message_us(ACCOUNT) is None
    marks.ws_heartbeat(ACCOUNT)
    marks.ws_dropped(ACCOUNT)  # a drop is no message: the mark stays
    marks.wallet_pushed(ACCOUNT, object())
    assert marks.last_message_us(ACCOUNT) == 10
    marks.ws_heartbeat(ACCOUNT)
    assert marks.last_message_us(ACCOUNT) == 20
    assert [kind for kind, _ in seen] == ["heartbeat", "dropped", "wallet", "heartbeat"]


# --- The persistence bundle and the composition -------------------------------------------------


def test_job_persistence_is_the_bundles_where_it_carries_one() -> None:
    assert rw.job_persistence(None) is None
    assert rw.job_persistence(SimpleNamespace(sink=object(), latch=object())) is None
    full = SimpleNamespace(
        snapshots=object(), persister=object(), restorer=lambda _lane: None, plugins_for=None
    )
    assert isinstance(rw.job_persistence(full), rw.BundleJobs)


async def test_bundle_jobs_reaches_the_bundles_store_restorer_plugins_and_persister(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[tuple[str, Any]] = []
    key, sealed, interp = object(), object(), object()

    class Snapshots:
        async def load(self, k: Any) -> Any:
            asked.append(("load", k))
            return sealed

    class Persister:
        async def persist(self, i: Any, *, key: Any) -> None:
            asked.append(("persist", key))

    async def plugins_for(k: Any, lane: Any) -> tuple[Any, ...]:
        asked.append(("plugins", lane))
        return ()

    async def restored(restorer: Any, k: Any, s: Any) -> Any:
        asked.append(("restore", restorer))
        return SimpleNamespace(interpreter=interp)

    monkeypatch.setattr(rw, "restore_chart", restored)
    bundle = SimpleNamespace(
        snapshots=Snapshots(), persister=Persister(), restorer=lambda lane: f"restorer:{lane}",
        plugins_for=plugins_for,
    )  # fmt: skip
    jobs = rw.BundleJobs(bundle)
    assert await jobs.load(key) is sealed  # type: ignore[arg-type]  # object() stand-ins
    assert await jobs.restore(key, sealed) is interp  # type: ignore[arg-type]  # object() stand-ins
    assert await jobs.plugins(key) == ()  # type: ignore[arg-type]  # object() stand-ins
    await jobs.persist(interp, key)  # type: ignore[arg-type]  # object() stand-ins
    assert asked == [
        ("load", key), ("restore", "restorer:order"), ("plugins", "order"), ("persist", key),
    ]  # fmt: skip


def _build(**over: Any) -> rw.ReconcileWiring:
    """`build_reconciliation` over the rig's doubles, `over` replacing an argument."""
    from candleviewer.observability.metrics import Metrics
    from candleviewer.oms.reconcile_standing import ReconcileStanding
    from candleviewer.statechart.plugins import InMemoryMachineEventSink
    from tests.unit.oms.reconcile_rig import World

    world, p = World(), Positions()
    feed = SimpleNamespace(ws_heartbeat=lambda a: None, ws_dropped=lambda a: None,
                           wallet_pushed=lambda a, s: None)  # fmt: skip
    given: dict[str, Any] = {
        "environment": "demo", "standing": ReconcileStanding(),
        "router": world.reconciler.ports.router, "accounts": world.reconciler.ports.accounts,
        "reads": Reads(), "orders": Lookups(), "fills": world.oms, "handovers": world.oms,
        "machines": world.oms, "positions": p, "published": p, "snapshots": p,
        "gate": SimpleNamespace(clear=None), "audit": SimpleNamespace(), "emitter": Emitter(),
        "lockout": world.oms, "exchange_placed": world.oms, "hub": Hub(), "serving": Serving(),
        "feed": feed, "metrics": Metrics("dev"), "pager": world.oms,
        "sink": InMemoryMachineEventSink(), "persistence": None,
        "now_us": lambda: world.now_us, "stale_after_s": 120.0, "remediates": lambda _e: True,
    }  # fmt: skip
    return rw.build_reconciliation(**(given | over))


@pytest.mark.parametrize("environment", ["live", "demo"])
def test_a_live_or_demo_record_that_does_not_remediate_fails_the_composition(
    environment: str,
) -> None:
    """24 Sec.14.3, C-2.6: refused while the OMS composes, so the runtime fails closed."""
    with pytest.raises(ValueError, match="always remediates"):
        _build(environment=environment, remediates=lambda _e: False)
    assert isinstance(
        _build(environment="testnet", remediates=lambda _e: False).jobs, ReconcileJobs
    )


async def test_build_reconciliation_wires_the_pass_its_phases_and_the_driver() -> None:
    built = _build()
    assert isinstance(built.jobs, ReconcileJobs)
    assert built.phases._retries._driver is built.jobs  # the retry hop reaches the driver
    assert built.reconciler.ports.protective.__class__.__name__ == "RecordedStopWriter"
    assert built.phases._marks is built.marks


# --- The requests the startup resumed (24 Sec.8.5, Sec.8.2 "Recovery") ---------------------------


@dataclass
class Facade:
    """`ResumingOrders`: each order's lifecycle state, and a `settled` that waits at the order's
    door until the test opens it, or raises `fails`, each wait recorded."""

    states: dict[UUID, str]
    fails: Exception | None = None
    doors: dict[UUID, asyncio.Event] = field(default_factory=dict)
    asked: list[tuple[UUID, UUID, str, float]] = field(default_factory=list)

    def state(self, order_id: UUID) -> tuple[str, str] | None:
        state = self.states.get(order_id)
        return None if state is None else (state, "not_required")

    async def settled(
        self, account_id: UUID, order_id: UUID, *, leaving: str, timeout_s: float
    ) -> str:
        self.asked.append((account_id, order_id, leaving, timeout_s))
        if self.fails is not None:
            raise self.fails
        await self.doors.setdefault(order_id, asyncio.Event()).wait()
        return "settled"


#: Rows 1 to 6 as the sweep hydrated them: three resumed (row 5 another account's), one live, one
#: unsent and one with no machine.
STATES = {
    UUID(int=1): "submitting", UUID(int=2): "submitted", UUID(int=3): "cancel_pending",
    UUID(int=4): "validated", UUID(int=5): "amend_pending",
}  # fmt: skip


def _swept(facade: Facade) -> rw.SweptRequests:
    swept = rw.SweptRequests()
    rows = [row(n, exchange_account_id=OTHER if n == 5 else ACCOUNT) for n in range(1, 7)]
    swept.record(facade, rows)
    return swept


async def _turns() -> None:
    for _ in range(64):
        await asyncio.sleep(0)


async def test_an_accounts_fetch_waits_once_for_its_own_resumed_requests_in_turn() -> None:
    """The sweep records each order its hydration left in a state whose invoke it resumed, by
    account. The account's next fetch waits for each of its own to leave that state, in turn,
    through the facade's `settled` and its bound; only once, so a later fetch waits for nothing,
    nor does an account with none; another account's wait is its own."""
    facade = Facade(dict(STATES))
    swept = _swept(facade)
    waiting = asyncio.create_task(swept.answered(ACCOUNT))
    await _turns()
    assert facade.asked == [(ACCOUNT, UUID(int=1), "submitting", rw.RESUMED_HOLD_S)]
    facade.doors[UUID(int=1)].set()
    await _turns()
    assert facade.asked[1:] == [(ACCOUNT, UUID(int=3), "cancel_pending", rw.RESUMED_HOLD_S)]
    assert not waiting.done()
    facade.doors[UUID(int=3)].set()
    await waiting
    await swept.answered(ACCOUNT)
    await swept.answered(UUID(int=0xAB))
    assert len(facade.asked) == 2
    facade.doors[UUID(int=5)] = asyncio.Event()
    facade.doors[UUID(int=5)].set()
    await swept.answered(OTHER)
    assert facade.asked[2:] == [(OTHER, UUID(int=5), "amend_pending", rw.RESUMED_HOLD_S)]


async def test_a_resumed_request_past_the_bound_is_logged_and_holds_the_pass_no_longer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A resumed request that has not answered within `RESUMED_HOLD_S` holds the pass no longer:
    logged with the account and its count, never raised (INV-B19-a)."""
    monkeypatch.setattr(rw, "RESUMED_HOLD_S", 0.0)
    swept = _swept(Facade(dict(STATES)))
    with capture_logs() as logs:
        await asyncio.wait_for(swept.answered(ACCOUNT), 5)  # a bound on the test
    [log] = [e for e in logs if e["event"] == "reconcile_resumed_unanswered"]
    assert (log["account_id"], log["orders"]) == (str(ACCOUNT), 2)


async def test_a_resumed_order_the_facade_cannot_read_is_logged_and_holds_the_pass_no_longer() -> (
    None
):
    swept = _swept(Facade(dict(STATES), fails=ConnectionError("the order store is down")))
    with capture_logs() as logs:
        await swept.answered(ACCOUNT)
    [log] = [e for e in logs if e["event"] == "reconcile_resumed_unread"]
    assert (log["account_id"], log["failure"]) == (str(ACCOUNT), "ConnectionError")


async def test_a_stop_cancels_a_fetch_that_waits_for_a_resumed_request() -> None:
    waiting = asyncio.create_task(_swept(Facade(dict(STATES))).answered(ACCOUNT))
    await _turns()
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting


def test_the_resumed_states_are_b1s_invoking_ones_and_the_bound_one_attempt_and_its_write() -> None:
    from candleviewer.statechart.bindings import b01_order as b01
    from candleviewer.statechart.config import CV_COMMAND_TIMEOUT, CV_PERSIST_TIMEOUT

    assert rw.RESUMED_STATES == frozenset(b01._INVOKES)
    assert rw.RESUMED_HOLD_S == CV_COMMAND_TIMEOUT + CV_PERSIST_TIMEOUT


def test_the_composition_holds_each_fetch_for_the_requests_the_sweep_resumed() -> None:
    swept = rw.SweptRequests()
    assert _build(resumed=swept).phases._resumed is swept
    assert _build().phases._resumed is None
