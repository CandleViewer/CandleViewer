"""`oms.position_writes` (E29-T07 #915 PR 2): the close and entry terms, the reversal's anchor
refs, the native-stop pre-check, the fill wait on the injected clock, the correlation records and
the Partial-mode sweep after a full close, on recording doubles; and the native stop (C-2.6) of
both orders on the real submission pipeline (`submit_rig`, the venue's `FakeTradingPort`). No
network (C-13.5)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.accounts.errors import AccountNotFoundError, ProfileUnavailableError
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.exchange.base.errors import TransportError
from candleviewer.exchange.base.models import (
    AccountRef,
    CancelOrderRequest,
    OrderAck,
    PlaceOrderRequest,
    Position,
)
from candleviewer.oms.errors import EnvironmentMismatch, OrderInvalid, StoreUnavailable
from candleviewer.oms.ports import RequestRecord, SubmitActor
from candleviewer.oms.position_writes import (
    CLOSE_ACTION,
    CloseTerms,
    PositionWrites,
    PositionWritesDeps,
    close_request,
    entry_request,
    is_full_close,
    reversal_refs,
)
from candleviewer.storage.repositories.positions import PositionRow
from candleviewer.storage.repositories.recorded_stops import RecordedStopRow
from tests.unit.api.oms_reads_world import position
from tests.unit.oms import command_rig as cr
from tests.unit.oms.submit_rig import SubmitRig, context, rigged

ACCOUNT = cr.ACCOUNT
ACTOR = SubmitActor(user_id=uuid.uuid4(), role="owner")
ORDER = uuid.UUID("0a000000-0000-4000-8000-0000000000aa")
T0 = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


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
    rows: tuple[RecordedStopRow, ...] = ()

    async def live_for_key(
        self, account_id: uuid.UUID, symbol: str, position_idx: int
    ) -> tuple[RecordedStopRow, ...]:
        return self.rows


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
    clock: list[float] = field(default_factory=lambda: [0.0])
    audit: Audit = field(init=False)

    def __post_init__(self) -> None:
        self.audit = Audit(self.port.log)

    def service(self, **kw: Any) -> PositionWrites:
        deps = PositionWritesDeps(
            accounts=self.accounts, profiles=self.profiles, machines=self.machines,
            stops=self.stops, ports=lambda env: self.port, audit=self.audit, environment="demo",
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
