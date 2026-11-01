"""`oms.position_writes` (E29-T07 #915 PR 2): the close and entry terms, the reversal's anchor
refs, the native-stop pre-check, the fill wait on the injected clock, the correlation records and
the Partial-mode sweep after a full close, on recording doubles; and the native stop (C-2.6) of
both orders on the real submission pipeline (`submit_rig`, the venue's `FakeTradingPort`). No
network (C-13.5)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Context, Decimal, localcontext
from typing import Any

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from candleviewer.accounts.errors import AccountNotFoundError, ProfileUnavailableError
from candleviewer.domain.events import Instrument
from candleviewer.domain.primitives import AccountId, Environment, Symbol
from candleviewer.exchange.base.errors import TransportError
from candleviewer.exchange.base.models import (
    AccountRef,
    CancelOrderRequest,
    OrderAck,
    PlaceOrderRequest,
    Position,
)
from candleviewer.oms.errors import (
    EnvironmentMismatch,
    IdempotencyKeyReuse,
    LotSizeViolation,
    OmsNotReady,
    OrderInvalid,
    StoreUnavailable,
)
from candleviewer.oms.ports import RequestRecord, SubmitActor
from candleviewer.oms.position_writes import (
    CLOSE_ACTION,
    REFRESH_WAIT_S,
    CloseTerms,
    PositionWrites,
    PositionWritesDeps,
    close_request,
    entry_request,
    is_full_close,
    resolve_close,
    reversal_refs,
)
from candleviewer.storage.repositories.positions import PositionRow, PositionState
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow
from candleviewer.storage.repositories.trade_groups import GroupAnchor
from tests.unit.api.oms_reads_world import position
from tests.unit.audit.audit_waits import virtual
from tests.unit.oms import command_rig as cr
from tests.unit.oms.submit_rig import (
    SYMBOL,
    Instruments,
    SubmitRig,
    context,
    entry,
    instrument,
    rigged,
)

ACCOUNT = cr.ACCOUNT
ACTOR = SubmitActor(user_id=uuid.uuid4(), role="owner")
ORDER = uuid.UUID("0a000000-0000-4000-8000-0000000000aa")
T0 = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


#: The resolver's exact context (`position_writes._EXACT`), for the property's own figures.
_EXACT = Context(prec=100)


def row(**over: Any) -> PositionRow:
    return position(1, ACCOUNT, **over)


# --- the terms ----------------------------------------------------------------------------------


def test_close_request_full_takes_the_whole_size_reduce_only_on_the_opposite_side() -> None:
    request = close_request(row(), CloseTerms("market", pct=Decimal(100)))
    assert (request.side, request.reduce_only, request.intent) == ("sell", True, "flatten")
    assert (request.sizing.mode, request.sizing.qty) == ("fixed_qty", Decimal("0.200"))
    assert request.stop_loss is None and request.position_idx == 0


def test_close_request_a_percent_or_a_quantity_and_a_short_closes_by_a_buy() -> None:
    half = close_request(row(side="Sell"), CloseTerms("limit", Decimal(63000), pct=Decimal(25)))
    assert (half.side, half.sizing.qty, half.price) == ("buy", Decimal("0.05"), Decimal(63000))
    by_qty = close_request(row(), CloseTerms("market", qty=Decimal("0.010")))
    assert by_qty.sizing.qty == Decimal("0.010")


def test_close_request_refuses_a_flat_position_and_terms_without_a_size() -> None:
    with pytest.raises(ValueError, match="flat"):
        close_request(row(side="None"), CloseTerms("market", pct=Decimal(100)))
    with pytest.raises(ValueError, match="percent or a quantity"):
        close_request(row(), CloseTerms("market"))


def test_is_full_close_by_percent_or_by_the_whole_size() -> None:
    assert is_full_close(row(), CloseTerms("market", pct=Decimal(100)))
    assert not is_full_close(row(), CloseTerms("market", pct=Decimal("99.9")))
    assert is_full_close(row(), CloseTerms("market", qty=Decimal("0.200")))
    assert not is_full_close(row(), CloseTerms("market", qty=Decimal("0.1")))


@pytest.mark.parametrize(("idx", "other"), [(0, 0), (1, 2), (2, 1)])
def test_entry_request_is_profile_sized_on_the_closing_side_and_the_other_hedge_index(
    idx: Any, other: int
) -> None:
    request = entry_request(row(position_idx=idx), "market", None)
    assert (request.side, request.position_idx, request.reduce_only) == ("sell", other, False)
    assert (request.sizing.mode, request.intent, request.stop_loss) == ("profile", "entry", None)


def test_reversal_refs_are_the_keys_uuid5_close_then_open_fixed_for_good() -> None:
    key = uuid.UUID("9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59")
    assert reversal_refs(key) == (uuid.uuid5(key, "close"), uuid.uuid5(key, "open"))
    assert len(set(reversal_refs(key))) == 2


# --- the service on doubles -----------------------------------------------------------------------


@dataclass
class Machines:
    """B1's plain view: `first` from `state`, then each `settled` answer in turn (`TimeoutError`
    or another exception raised)."""

    first: str | None = "submitted"
    answers: list[str | BaseException] = field(default_factory=list)
    asked: list[tuple[str, float]] = field(default_factory=list)

    def state(self, order_id: uuid.UUID) -> tuple[str, str] | None:
        return None if self.first is None else (self.first, "none")

    async def settled(
        self, account_id: uuid.UUID, order_id: uuid.UUID, *, leaving: str, timeout_s: float
    ) -> str:
        self.asked.append((leaving, timeout_s))
        answer = self.answers.pop(0) if self.answers else TimeoutError()
        if isinstance(answer, BaseException):
            raise answer
        return answer


@dataclass
class Port:
    held: list[Position] = field(default_factory=list)
    unread: bool = False
    cancel_fails: bool = False
    cancels: list[CancelOrderRequest] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    async def positions(self, account: AccountRef) -> Sequence[Position]:
        if self.unread:
            raise TransportError("down")
        return self.held

    async def cancel_order(self, req: CancelOrderRequest) -> OrderAck:
        self.log.append("cancel")
        self.cancels.append(req)
        if self.cancel_fails:
            raise TransportError("gone")
        return OrderAck.model_construct()


@dataclass
class Audit:
    log: list[str]
    written: list[RequestRecord] = field(default_factory=list)
    fail: bool = False

    def record_id(self, action: str, name: str) -> uuid.UUID:
        raise AssertionError

    async def write(self, record: Any) -> None:
        if self.fail:
            raise RuntimeError("down")
        self.log.append("record")
        self.written.append(record)


@dataclass
class Profiles:
    refuse: BaseException | None = None

    async def get_effective_profile(self, account_id: uuid.UUID, profile_id: Any = None) -> Any:
        if self.refuse is not None:
            raise self.refuse
        return object()


@dataclass
class Accounts:
    environment: Environment = "demo"

    async def trading_account(self, account_id: AccountId) -> AccountRef:
        return cr.ref(account_id, self.environment).model_copy(update={"account_id": account_id})


@dataclass
class Stops:
    """The key's live stops: `rows`, then `later` from the second read on (a stop placed while
    the sweep waited); `fail_at` raises on that read (0-based)."""

    rows: tuple[RecordedStopRow, ...] = ()
    later: tuple[RecordedStopRow, ...] | None = None
    fail_at: int | None = None
    reads: int = 0

    async def live_for_key(
        self, account_id: uuid.UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]:
        read, self.reads = self.reads, self.reads + 1
        if read == self.fail_at:
            raise TimeoutError
        return self.rows if read == 0 or self.later is None else self.later


@dataclass
class Store:
    """The position store's upsert: each state it took; `stale` answers a newer stored row (a
    stale write changes nothing), `fail` raises."""

    states: list[PositionState] = field(default_factory=list)
    stale: bool = False
    fail: bool = False

    async def upsert(self, state: PositionState) -> PositionRow:
        if self.fail:
            raise RuntimeError("down")
        self.states.append(state)
        stored = state.exchange_updated_ts
        if self.stale and stored is not None:
            stored += timedelta(seconds=1)
        values = asdict(state) | {"exchange_updated_ts": stored}
        return PositionRow(**values, id=uuid.uuid4(), recv_ts=T0, updated_at=T0)


@dataclass
class GroupKeys:
    """The groups' anchor read: `found` for every ref; `error` raised instead; each ask kept."""

    found: GroupAnchor | None = None
    error: BaseException | None = None
    asked: list[tuple[uuid.UUID, str, str]] = field(default_factory=list)

    async def find_anchor(
        self, created_by: uuid.UUID, client_group_ref: str, client_body_sha256: str
    ) -> GroupAnchor | None:
        self.asked.append((created_by, client_group_ref, client_body_sha256))
        if self.error is not None:
            raise self.error
        return self.found


def stop(mode: str = "Partial", exchange_order_id: str | None = "ex-1", **over: Any) -> Any:
    values: dict[str, Any] = {
        "id": uuid.uuid4(), "exchange_account_id": ACCOUNT, "symbol": "BTCUSDT",
        "position_idx": 0, "position_side": "Buy", "kind": "stop_loss", "source": "trading_stop",
        "order_id": None, "tpsl_mode": mode, "trigger_price": Decimal(60000),
        "size": Decimal("0.1"), "trailing_distance": None, "trailing_active_price": None,
        "exchange_order_id": exchange_order_id, "status": "in_force",
        "audit_record_id": uuid.uuid4(), "actor_user_id": None, "created_at": T0,
        "answered_at": T0, "in_force_at": T0, "closed_at": None, "released_at": None,
        "position_marker": None,
    }  # fmt: skip
    return RecordedStopRow(**(values | over))


@dataclass
class Rig:
    machines: Machines = field(default_factory=Machines)
    port: Port = field(default_factory=Port)
    profiles: Profiles = field(default_factory=Profiles)
    stops: Stops = field(default_factory=Stops)
    accounts: Accounts = field(default_factory=Accounts)
    groups: GroupKeys = field(default_factory=GroupKeys)
    instruments: Instruments = field(default_factory=Instruments)
    store: Store = field(default_factory=Store)
    clock: list[float] = field(default_factory=lambda: [0.0])
    audit: Audit = field(init=False)

    def __post_init__(self) -> None:
        self.audit = Audit(self.port.log)

    def service(self, **kw: Any) -> PositionWrites:
        deps = PositionWritesDeps(
            accounts=self.accounts, profiles=self.profiles, machines=self.machines,
            stops=self.stops, groups=self.groups, ports=lambda env: self.port, audit=self.audit,
            environment="demo", instruments=self.instruments, positions=self.store,
        )  # fmt: skip
        return PositionWrites(deps, monotonic=lambda: self.clock[0], **kw)


async def test_entry_stop_ready_passes_with_a_profile() -> None:
    await Rig().service().entry_stop_ready(ACCOUNT)


async def test_entry_stop_ready_native_sl_no_default_profile_is_native_stop_required() -> None:
    """C-2.6: no profile, no stop: the reversal is refused before anything is sent."""
    rig = Rig()
    rig.profiles.refuse = AccountNotFoundError("profile")
    with pytest.raises(OrderInvalid) as refused:
        await rig.service().entry_stop_ready(ACCOUNT)
    assert [e.rule for e in refused.value.errors] == ["native_stop_required"]


@pytest.mark.parametrize("error", [ProfileUnavailableError("down"), TimeoutError()])
async def test_entry_stop_ready_an_unread_profile_is_store_unavailable(error: Any) -> None:
    rig = Rig()
    rig.profiles.refuse = error
    with pytest.raises(StoreUnavailable):
        await rig.service().entry_stop_ready(ACCOUNT)


async def test_group_key_free_asks_the_creators_raw_key_and_passes_when_none_anchors() -> None:
    rig, key = Rig(), uuid.uuid4()
    await rig.service().group_key_free(ACTOR.user_id, key, "a" * 64)
    assert rig.groups.asked == [(ACTOR.user_id, str(key), "a" * 64)]


@pytest.mark.parametrize("matches", [True, False])
async def test_group_key_free_a_key_anchoring_a_group_is_key_reuse(matches: bool) -> None:
    """Fable m1: the raw key already names one of this creator's groups (a `placeOrder` entry's
    or a `createTradeGroup`'s): 409 before the close, whatever its fingerprint."""
    rig = Rig()
    rig.groups.found = GroupAnchor(uuid.uuid4(), body_matches=matches)
    with pytest.raises(IdempotencyKeyReuse):
        await rig.service().group_key_free(ACTOR.user_id, uuid.uuid4(), "a" * 64)


async def test_group_key_free_an_unread_store_is_store_unavailable() -> None:
    rig = Rig()
    rig.groups.error = TimeoutError()
    with pytest.raises(StoreUnavailable):
        await rig.service().group_key_free(ACTOR.user_id, uuid.uuid4(), "a" * 64)


async def test_await_fill_follows_b1_until_filled() -> None:
    rig = Rig(machines=Machines("submitted", ["partially_filled", "filled"]))
    assert await rig.service().await_fill(ACCOUNT, ORDER, deadline=2.0) == "filled"
    assert [leaving for leaving, _ in rig.machines.asked] == ["submitted", "partially_filled"]


async def test_await_fill_a_filled_order_answers_at_once_and_a_gone_machine_reads_the_row() -> None:
    assert (
        await Rig(machines=Machines("filled")).service().await_fill(ACCOUNT, ORDER, deadline=0.0)
        == "filled"
    )
    gone = Rig(machines=Machines(None, ["filled"]))
    assert await gone.service().await_fill(ACCOUNT, ORDER, deadline=1.0) == "filled"
    assert gone.machines.asked == [("submitting", 1.0)]


@pytest.mark.parametrize(
    ("first", "answers", "fill"),
    [("submitted", [TimeoutError()], "unfilled"),
     ("submitted", ["partially_filled", TimeoutError()], "partially_filled"),
     ("submitted", ["cancelled"], "unfilled"),
     ("partially_filled", ["cancelled"], "partially_filled"),
     ("submitted", [RuntimeError("unread")], "unfilled")],
)  # fmt: skip
async def test_await_fill_never_takes_an_unconfirmed_close_for_a_fill(
    first: str, answers: list[Any], fill: str
) -> None:
    rig = Rig(machines=Machines(first, answers))
    assert await rig.service().await_fill(ACCOUNT, ORDER, deadline=2.0) == fill


async def test_await_fill_waits_only_what_is_left_of_the_deadline_on_the_injected_clock() -> None:
    rig = Rig(machines=Machines("submitted", ["filled"]))
    rig.clock[0] = 1.25
    await rig.service().await_fill(ACCOUNT, ORDER, deadline=2.0)
    assert rig.machines.asked == [("submitted", 0.75)]
    late = Rig(machines=Machines("submitted", ["filled"]))
    late.clock[0] = 3.0
    assert await late.service().await_fill(ACCOUNT, ORDER, deadline=2.0) == "unfilled"
    assert late.machines.asked == []


async def test_record_is_true_when_it_lands_false_when_it_does_not() -> None:
    rig = Rig()
    record = RequestRecord(CLOSE_ACTION, ACCOUNT, "position", ORDER, "success", "info", "x",
                           ACTOR, {})  # fmt: skip
    assert await rig.service().record(record) is True
    rig.audit.fail = True
    assert await rig.service().record(record) is False


# --- the sweep (22 closePosition at 100 %; C-2.6) ------------------------------------------------


async def swept(rig: Rig, **kw: Any) -> PositionWrites:
    service = rig.service(**kw)
    assert await service.sweep_after_close(row(), ORDER, actor=ACTOR, request_id=None)
    await asyncio.gather(*service._sweeps)  # the tracked task, ended here
    return service


def flat_rig(*stops: RecordedStopRow) -> Rig:
    return Rig(machines=Machines("filled"), stops=Stops(stops))


async def test_sweep_cancels_the_partial_conditionals_once_filled_and_flat_recorded_first() -> None:
    partial, full, unbound = stop(), stop("Full", "ex-2"), stop(exchange_order_id=None)
    rig = flat_rig(partial, full, unbound)
    await swept(rig)
    assert [c.exchange_order_id for c in rig.port.cancels] == ["ex-1"]
    assert rig.port.log == ["record", "cancel"]  # C-2.9: recorded ahead of the cancel
    [record] = rig.audit.written
    assert (record.action, record.reason) == (CLOSE_ACTION, "partial_stop_cancelled")
    assert record.detail["recorded_stop_id"] == str(partial.id)


async def test_sweep_native_sl_never_touches_a_position_the_venue_still_shows_open() -> None:
    """C-2.6: the close filled, yet the venue's read shows size on the key: nothing is cancelled."""
    rig = flat_rig(stop())
    rig.port.held = [cr.position(ACCOUNT, qty="0.1")]
    await swept(rig)
    assert rig.port.cancels == [] and rig.audit.written == []


async def test_sweep_another_key_open_does_not_hold_it() -> None:
    rig = flat_rig(stop())
    rig.port.held = [cr.position(ACCOUNT, qty="0.1", position_idx=1)]
    await swept(rig)
    assert len(rig.port.cancels) == 1


@pytest.mark.parametrize("change", ["unfilled", "unread"])
async def test_sweep_native_sl_an_unconfirmed_fill_or_an_unread_venue_cancels_nothing(
    change: str,
) -> None:
    rig = flat_rig(stop())
    if change == "unfilled":
        rig.machines = Machines("submitted", [TimeoutError()])
    else:
        rig.port.unread = True
    await swept(rig)
    assert rig.port.cancels == []


async def test_sweep_native_sl_a_partial_stop_placed_after_the_close_is_never_cancelled() -> None:
    """Fable M3: the sweep snapshots the key's stops before it waits for the fill; a Partial-mode
    stop placed after the close order is not in it and is never cancelled (C-2.6)."""
    old, new = stop(), stop(exchange_order_id="ex-new")
    rig = flat_rig(old)
    rig.stops.later = (old, new)
    await swept(rig)
    assert [c.exchange_order_id for c in rig.port.cancels] == ["ex-1"]
    assert rig.stops.reads == 2


async def test_sweep_a_stop_gone_by_the_flat_read_is_not_cancelled() -> None:
    gone = stop()
    rig = flat_rig(gone)
    rig.stops.later = ()
    await swept(rig)
    assert rig.port.cancels == []


@pytest.mark.parametrize("fail_at", [0, 1], ids=["snapshot", "after_flat"])
async def test_sweep_native_sl_unread_stops_cancel_nothing(fail_at: int) -> None:
    rig = flat_rig(stop())
    rig.stops.fail_at = fail_at
    await swept(rig)
    assert rig.port.cancels == [] and rig.audit.written == []


async def test_sweep_an_unrecorded_cancel_is_never_sent_and_a_failed_one_is_let_go() -> None:
    unrecorded = flat_rig(stop())
    unrecorded.audit.fail = True
    await swept(unrecorded)
    assert unrecorded.port.cancels == []
    failing = flat_rig(stop(), stop(exchange_order_id="ex-3"))
    failing.port.cancel_fails = True
    await swept(failing)
    assert len(failing.port.cancels) == 2


async def test_sweep_is_bounded_and_closed_with_the_service() -> None:
    rig = Rig(machines=Machines("submitted", [asyncio.CancelledError()]))
    service = rig.service(max_sweeps=1)
    hold = asyncio.Event()

    async def blocked(*_a: Any, **_k: Any) -> str:
        await hold.wait()
        return "filled"

    rig.machines.settled = blocked  # type: ignore[method-assign]  # a fill that never comes
    assert await service.sweep_after_close(row(), ORDER, actor=ACTOR, request_id=None)
    assert not await service.sweep_after_close(row(), ORDER, actor=ACTOR, request_id=None)
    await service.aclose()
    assert service._sweeps == set()


async def test_sweep_another_environments_account_is_never_swept() -> None:
    rig = flat_rig(stop())
    rig.accounts.environment = "live"
    service = rig.service()
    await service.sweep_after_close(row(), ORDER, actor=ACTOR, request_id=None)
    [task] = service._sweeps
    with pytest.raises(EnvironmentMismatch):
        await task
    assert rig.port.cancels == []


async def test_venue_position_reads_the_key_flat_open_or_unread() -> None:
    """Fable M2: the read a reversal makes before its entry, the sweep's own."""
    rig = Rig()
    assert await rig.service().venue_position(row()) == "flat"
    rig.port.held = [cr.position(ACCOUNT, qty="0.1", position_idx=1)]  # another key
    assert await rig.service().venue_position(row()) == "flat"
    rig.port.held = [cr.position(ACCOUNT, qty="0.001")]
    assert await rig.service().venue_position(row()) == "open"
    rig.port.unread = True
    assert await rig.service().venue_position(row()) == "unread"


async def test_venue_position_an_account_of_another_environment_is_unread() -> None:
    rig = Rig()
    rig.accounts.environment = "live"
    assert await rig.service().venue_position(row()) == "unread"


def test_the_service_refuses_unbounded_settings() -> None:
    with pytest.raises(ValueError, match="above zero"):
        Rig().service(sweep_wait_s=0)
    with pytest.raises(ValueError, match="above zero"):
        Rig().service(max_sweeps=0)


# --- the native stop on the real pipeline (C-2.6) -------------------------------------------------


@pytest.fixture
async def rig() -> AsyncIterator[SubmitRig]:
    async with rigged() as built:
        yield built


def _creates(rig: SubmitRig) -> list[PlaceOrderRequest]:
    return [c.request for c in rig.port.demo.calls if c.method == "place_order"]


async def test_native_sl_a_reversals_entry_carries_the_profiles_stop_on_the_real_pipeline(
    rig: SubmitRig,
) -> None:
    held = row(exchange_account_id=ACCOUNT)
    key = uuid.uuid4()
    entry = entry_request(held, "market", None)
    outcome = await rig.pipeline.submit(
        entry, replace(context(client_ref=key), operation="reversePosition",
                       anchor_ref=reversal_refs(key)[1]),
    )  # fmt: skip
    assert outcome.status == 202 and outcome.trade_group_id is not None
    [create] = _creates(rig)
    assert create.reduce_only is False and create.stop_loss is not None  # C-2.6
    [anchor] = rig.store._anchors.values()  # the anchor the persist wrote
    assert anchor.key()[1:] == ("reversePosition", str(reversal_refs(key)[1]))


@pytest.mark.parametrize(("idx", "other"), [(1, 2), (2, 1)])
async def test_native_sl_a_hedge_reversals_entry_carries_the_profiles_stop_on_the_real_pipeline(
    rig: SubmitRig, idx: int, other: int
) -> None:
    """#915 QA hold: a hedge-mode reversal's entry opens the other side's index through the real
    pipeline and carries the profile's native stop, as the one-way entry does (C-2.6)."""
    held = row(exchange_account_id=ACCOUNT, position_idx=idx)
    key = uuid.uuid4()
    entry = entry_request(held, "market", None)
    assert entry.stop_loss is None  # the profile, never the request, gives the stop
    outcome = await rig.pipeline.submit(
        entry, replace(context(client_ref=key), operation="reversePosition",
                       anchor_ref=reversal_refs(key)[1]),
    )  # fmt: skip
    assert outcome.status == 202 and outcome.trade_group_id is not None
    [create] = _creates(rig)
    assert (create.position_idx, create.reduce_only) == (other, False)
    assert create.stop_loss is not None  # C-2.6


async def test_native_sl_a_partial_close_sends_only_its_reduce_only_order(rig: SubmitRig) -> None:
    """22 closePosition below 100 %: one reduce-only order, no trading-stop and no cancel, so the
    remaining position keeps its native stop (C-2.6)."""
    rig.port.demo.seed_position(cr.position(qty="0.050"))
    held = row(exchange_account_id=ACCOUNT, size=Decimal("0.050"))
    request = close_request(held, CloseTerms("market", pct=Decimal(50)))
    outcome = await rig.pipeline.submit(request, replace(context(), operation="closePosition"))
    assert outcome.status == 202 and outcome.trade_group_id is None
    assert [c for c in rig.calls() if c != "positions"] == ["place_order"]
    [create] = _creates(rig)
    assert (create.reduce_only, create.stop_loss) == (True, None)


# --- BQ-5 as ruled (E29-S03 #978): the server's own min_notional never traps an exit -------------


async def test_bq5_a_reduce_only_close_under_the_minimum_notional_is_sent(rig: SubmitRig) -> None:
    """C-2.6: a close of 0.001 at the reference 60000 is a notional of 60, under a minimum of 100;
    the venue arbitrates it, so it is recorded and sent, reduce-only."""
    rig.instruments.listed[SYMBOL] = instrument(min_notional=Decimal("100"))
    rig.port.demo.seed_position(cr.position(qty="0.050"))
    held = row(exchange_account_id=ACCOUNT, size=Decimal("0.050"))
    request = close_request(held, CloseTerms("market", qty=Decimal("0.001")))
    closing = replace(context(), operation="closePosition", protective=True)
    outcome = await rig.pipeline.submit(request, closing)
    assert outcome.status == 202
    [create] = _creates(rig)
    assert (create.reduce_only, create.qty, create.stop_loss) == (True, Decimal("0.001"), None)


async def test_bq5_an_entry_under_the_minimum_notional_is_still_refused_unsent(
    rig: SubmitRig,
) -> None:
    """An order that opens exposure is held to the minimum notional as before: nothing is sent."""
    rig.instruments.listed[SYMBOL] = instrument(min_notional=Decimal("1000"))
    with pytest.raises(LotSizeViolation):
        await rig.pipeline.submit(entry(), context())
    assert _creates(rig) == []


# --- the persist's check of a reversal entry's anchor (21 Sec.3.3.10) -----------------------------


def test_first_persist_a_reversal_entrys_anchor_holds_the_open_ref_of_its_groups_key() -> None:
    """#5013: the entry's group keeps the raw key, its anchor `uuid5(key, "open")`; any other
    ref, the raw key included, is refused before any statement, as `placeOrder`'s twin is."""
    from tests.unit.oms import submission_contract as sc

    first, order = sc.entry(uuid.uuid4(), ACCOUNT, uuid.uuid4())
    assert first.group is not None
    key = uuid.UUID(first.group.client_group_ref)
    derived = replace(first.anchor, operation="reversePosition",
                      client_ref=str(reversal_refs(key)[1]))  # fmt: skip
    replace(first, anchor=derived).check(order)
    for wrong in (str(key), str(reversal_refs(key)[0])):
        refused = replace(first, anchor=replace(derived, client_ref=wrong))
        with pytest.raises(ValueError, match="principal, key and fingerprint"):
            refused.check(order)
    with pytest.raises(ValueError, match="principal, key and fingerprint"):
        replace(first, anchor=replace(first.anchor, client_ref=str(reversal_refs(key)[1]))).check(
            order
        )  # a placeOrder entry keeps the key itself


# --- the close's size (E29-S03 #978, BQ-2 to BQ-4 as ruled) ---------------------------------------


def pct(value: str) -> CloseTerms:
    return CloseTerms("market", pct=Decimal(value))


def qty(value: str) -> CloseTerms:
    return CloseTerms("market", qty=Decimal(value))


def lot(step: str, minimum: str | None = None) -> Instrument:
    return instrument(qty_step=Decimal(step), min_order_qty=Decimal(minimum or step))


@pytest.mark.parametrize(
    ("size", "terms", "step", "minimum", "sent", "left", "rounded"),
    [
        ("0.250", pct("50"), "0.001", None, "0.125", "0.125", False),  # the Gherkin scenario
        ("0.250", pct("33"), "0.001", None, "0.082", "0.168", True),  # 33 %: 0.0825 floored
        ("0.300", pct("33"), "0.001", None, "0.099", "0.201", False),  # 33 % on the grid
        ("10", pct("33"), "1", None, "3", "7", True),  # a qty_step of 1: 3.3 floored
        ("1.50", pct("25"), "0.01", None, "0.37", "1.13", True),  # D02's OQ-K: 0.375 floored
        ("0.250", qty("0.1005"), "0.001", None, "0.100", "0.150", True),  # a qty floored too
        ("0.250", qty("0.100"), "0.001", None, "0.100", "0.150", False),
        ("0.250", pct("100"), "0.001", None, "0.250", "0", False),  # the whole size
        ("0.250", qty("0.250"), "0.001", None, "0.250", "0", False),
        ("0.002", pct("50"), "0.001", None, "0.001", "0.001", False),  # one lot of two
        ("0.001", pct("100"), "0.001", None, "0.001", "0", False),  # a one-lot position, whole
        ("0.4", pct("50"), "0.01", "0.2", "0.2", "0.2", False),  # a minimum above the step, met
        ("0.05", pct("100"), "0.01", "0.1", "0.05", "0", False),  # whole, under the minimum
    ],
)  # fmt: skip
def test_resolve_close_rounding_table(
    size: str, terms: CloseTerms, step: str, minimum: str | None, sent: str, left: str,
    rounded: bool,
) -> None:  # fmt: skip
    """BQ-2: from the stored size, floored to the lot step and never up, the whole size at
    100 % or for a qty equal to it; a close of the whole size is never refused (BQ-4)."""
    resolved = resolve_close(row(size=Decimal(size)), terms, lot(step, minimum))
    assert (resolved.qty, resolved.remaining) == (Decimal(sent), Decimal(left))
    assert resolved.rounded is rounded and resolved.full is (resolved.remaining == 0)


@pytest.mark.parametrize(
    ("size", "terms", "step", "minimum", "rules", "resolved", "remaining"),
    [
        ("0.15", pct("50"), "0.01", "0.1", ["dust_remainder", "qty_below_minimum"], "0.07", "0.08"),
        ("0.25", pct("65"), "0.01", "0.1", ["dust_remainder"], "0.16", "0.09"),
        ("0.25", qty("0.2"), "0.01", "0.1", ["dust_remainder"], "0.2", "0.05"),
        ("0.200", pct("0.4"), "0.001", None, ["qty_below_minimum"], "0.000", None),
        ("0.001", pct("50"), "0.001", None, ["qty_below_minimum"], "0.000", None),  # one lot
        ("0.25", qty("0.05"), "0.01", "0.1", ["qty_below_minimum"], "0.05", None),
    ],
)  # fmt: skip
def test_resolve_close_refuses_a_partial_close_leaving_dust_or_under_the_minimum(
    size: str, terms: CloseTerms, step: str, minimum: str | None, rules: list[str],
    resolved: str, remaining: str | None,
) -> None:  # fmt: skip
    """BQ-3 and BQ-4: each rule named, dust first (only the whole close answers it), with the
    symbol, the minimum as the limit, the resolved size and, for dust, the remainder."""
    with pytest.raises(OrderInvalid) as refused:
        resolve_close(row(size=Decimal(size)), terms, lot(step, minimum))
    errors = refused.value.errors
    assert [e.rule for e in errors] == rules
    field_name = "pct" if terms.pct is not None else "qty"
    limit, sent = Decimal(minimum or step), Decimal(resolved)
    assert all((e.field, e.symbol, e.limit, e.resolved) == (field_name, "BTCUSDT", limit, sent)
               for e in errors)  # fmt: skip
    assert errors[0].remaining == (None if remaining is None else Decimal(remaining))
    detail = errors[0].message if len(errors) == 1 else f"{len(errors)} rules failed."
    assert refused.value.detail == detail


def test_resolve_close_a_refusals_figures_never_show_in_its_repr() -> None:
    """C-12.6: the limit, the resolved size and the remainder are the problem body's alone; a
    repr, which a log could carry, names the field, the rule, the sentence and the symbol."""
    with pytest.raises(OrderInvalid) as refused:
        resolve_close(row(size=Decimal("0.15")), pct("50"), lot("0.01", "0.1"))
    for error in refused.value.errors:
        assert (error.limit, error.resolved) == (Decimal("0.1"), Decimal("0.07"))
        assert repr(error) == (
            f"FieldError(field='pct', rule={error.rule!r}, message={error.message!r}, "
            "symbol='BTCUSDT')"
        )


def test_resolve_close_bq5_a_remainder_under_the_floor_is_dust_above_the_minimum() -> None:
    """BQ-5 as ruled: until E29-K01 confirms the venue fact, a remainder under SR-E22-03's
    `MIN_SIZE_FLOOR` is dust even above `min_order_qty`, named with that floor as its limit; at the
    floor it passes, a floor under the minimum changes nothing, and the whole size still goes."""
    whole, three_quarters = row(size=Decimal("0.200")), pct("75")
    with pytest.raises(OrderInvalid) as refused:
        resolve_close(whole, three_quarters, lot("0.001"), floor=Decimal("0.060"))
    [dust] = refused.value.errors
    assert (dust.rule, dust.limit, dust.resolved, dust.remaining) == (
        "dust_remainder",
        Decimal("0.060"),
        Decimal("0.150"),
        Decimal("0.050"),
    )
    assert resolve_close(whole, three_quarters, lot("0.001"), floor=Decimal("0.050")).qty == (
        Decimal("0.150")
    )
    assert resolve_close(
        whole, three_quarters, lot("0.001"), floor=Decimal("0.0005")
    ).remaining == (Decimal("0.050"))
    assert resolve_close(whole, pct("100"), lot("0.001"), floor=Decimal("1")).full is True


def test_resolve_close_needs_a_percent_or_a_quantity() -> None:
    with pytest.raises(ValueError, match="percent or a quantity"):
        resolve_close(row(), CloseTerms("market"), lot("0.001"))


@given(
    lots=st.integers(min_value=1, max_value=10**6),
    exponent=st.integers(min_value=-6, max_value=0),
    minimum_lots=st.integers(min_value=1, max_value=100),
    percent=st.decimals(min_value=Decimal("0.01"), max_value=Decimal(100), places=2),
    floor_lots=st.one_of(st.none(), st.integers(min_value=0, max_value=200)),
)
@example(lots=250, exponent=-3, minimum_lots=1, percent=Decimal(50), floor_lots=None)
@example(lots=15, exponent=-2, minimum_lots=10, percent=Decimal(50), floor_lots=None)
@example(lots=200, exponent=-3, minimum_lots=1, percent=Decimal(75), floor_lots=60)
@example(  # a numeric(38,18) size, 38 digits: exact only in the resolver's own 100-digit context
    lots=12345678901234567890123456789012345678,
    exponent=-18,
    minimum_lots=1,
    percent=Decimal("33.33"),
    floor_lots=None,
)
@settings(max_examples=200, deadline=None, derandomize=True)
def test_property_resolve_close_on_the_grid_within_the_size_never_leaving_dust(
    lots: int, exponent: int, minimum_lots: int, percent: Decimal, floor_lots: int | None
) -> None:
    """For any size, lot step, minimum, percent and dust floor: a close `resolve_close` admits is
    on the lot grid, above zero, never above the size or what was asked, and leaves no remainder
    in (0, the larger of min_order_qty and the floor); one it refuses is a partial close, for
    those two rules alone. The test's own figures are exact; the resolver runs in the default
    context, so its own exact context is what keeps a 38-digit size exact."""
    with localcontext(_EXACT):
        step = Decimal(1).scaleb(exponent)
        size, minimum = lots * step, minimum_lots * step
        floor = None if floor_lots is None else floor_lots * step
    listed = instrument(qty_step=step, min_order_qty=minimum)
    terms = CloseTerms("market", pct=percent)
    try:
        resolved = resolve_close(row(size=size), terms, listed, floor=floor)
    except OrderInvalid as refused:
        assert percent != 100
        assert {e.rule for e in refused.errors} <= {"dust_remainder", "qty_below_minimum"}
        return
    least = minimum if floor is None else max(minimum, floor)
    with localcontext(_EXACT):
        assert resolved.qty % step == 0 and 0 < resolved.qty <= size
        assert resolved.qty <= size * percent / 100
        assert not 0 < resolved.remaining < least
        assert resolved.qty + resolved.remaining == size
    assert resolved.full is (percent == 100)


def test_close_request_sends_the_resolved_size_as_its_fixed_qty() -> None:
    request = close_request(row(), pct("33"), Decimal("0.066"))
    assert (request.sizing.mode, request.sizing.qty, request.reduce_only) == (
        "fixed_qty",
        Decimal("0.066"),
        True,
    )


# --- the instrument step 13 reads (E29-S03) -------------------------------------------------------


async def test_instrument_reads_the_symbols_instrument_through_the_pipelines_port() -> None:
    assert (await Rig().service().instrument(SYMBOL)).symbol == SYMBOL


@pytest.mark.parametrize("error", [TimeoutError(), RuntimeError("down")])
async def test_instrument_an_unread_catalogue_is_store_unavailable(error: Exception) -> None:
    rig = Rig()
    rig.instruments.refuse = error
    with pytest.raises(StoreUnavailable):
        await rig.service().instrument(SYMBOL)


async def test_instrument_no_catalogue_yet_answers_oms_not_ready_as_itself() -> None:
    rig = Rig()
    rig.instruments.refuse = OmsNotReady()
    with pytest.raises(OmsNotReady):
        await rig.service().instrument(SYMBOL)


@pytest.mark.parametrize("listed", [False, True], ids=["unlisted", "another_symbols"])
async def test_instrument_a_symbol_none_lists_is_validation_failed(listed: bool) -> None:
    rig = Rig()
    if listed:
        rig.instruments.listed["ETHUSDT"] = instrument()  # BTCUSDT's, under another name
    with pytest.raises(OrderInvalid) as refused:
        await rig.service().instrument(Symbol("ETHUSDT"))
    assert [e.rule for e in refused.value.errors] == ["listed"]


# --- a rejected close's re-read (E29-S03 BQ-7) ----------------------------------------------------


async def test_refresh_upserts_the_row_the_venue_read_shows_for_the_key() -> None:
    rig = Rig()
    rig.port.held = [cr.position(ACCOUNT, qty="0.040"), cr.position(ACCOUNT, qty="0.1",
                                                                    position_idx=1)]  # fmt: skip
    assert await rig.service().refresh(row()) is True
    [state] = rig.store.states
    assert (state.exchange_account_id, state.symbol, state.position_idx, state.size) == (
        ACCOUNT,
        "BTCUSDT",
        0,
        Decimal("0.040"),
    )


@pytest.mark.parametrize(
    "change", ["absent", "twice", "unread", "store_down", "stale", "another_environment"]
)
async def test_refresh_changes_nothing_on_a_key_unshown_or_a_failure(change: str) -> None:
    """Best effort: nothing applied, and a key the read does not show is never written flat on a
    guess (C-2.6): the private stream's push and reconciliation write it."""
    rig = Rig()
    rig.port.held = [cr.position(ACCOUNT, qty="0.040")]
    if change == "absent":
        rig.port.held = [cr.position(ACCOUNT, qty="0.1", position_idx=1)]
    elif change == "twice":
        rig.port.held = [cr.position(ACCOUNT, qty="0.040")] * 2
    elif change == "unread":
        rig.port.unread = True
    elif change == "store_down":
        rig.store.fail = True
    elif change == "stale":
        rig.store.stale = True
    else:
        rig.accounts.environment = "live"
    assert await rig.service().refresh(row()) is False
    assert len(rig.store.states) == (1 if change == "stale" else 0)


@virtual
async def test_refresh_is_bounded_at_5_s_and_a_hung_read_writes_nothing() -> None:
    """The re-read's bound is the `poll` lane's own deadline, 5 s (24 Sec.8.4, Sec.8.7), on the
    fake clock: the answer waits no longer than that for a read that never answers."""
    rig = Rig()
    hold = asyncio.Event()

    async def hung(account: AccountRef) -> Sequence[Position]:
        await hold.wait()
        return []

    rig.port.positions = hung  # type: ignore[method-assign]  # a read that never answers
    loop = asyncio.get_running_loop()
    started = loop.time()
    assert await rig.service().refresh(row()) is False
    assert loop.time() - started == pytest.approx(5.0) and REFRESH_WAIT_S == 5.0
    assert rig.store.states == []


def test_the_service_refuses_an_unbounded_refresh() -> None:
    with pytest.raises(ValueError, match="above zero"):
        Rig().service(refresh_wait_s=0)
