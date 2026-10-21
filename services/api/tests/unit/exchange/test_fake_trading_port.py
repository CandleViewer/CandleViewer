"""`FakeTradingPort` (G-8, #2877): the in-memory `TradingPort` the OMS's tests drive.

Its refusals are shared with the exchange's port through `test_trading_conformance.py`; this
file covers what only the fake has: scripted outcomes, venue-like state and the private stream.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from uuid import UUID

import pytest

from candleviewer.domain.order_link import ext_key
from candleviewer.domain.primitives import AccountId, GroupId
from candleviewer.exchange.base import FakeTradingPort, TradingPort
from candleviewer.exchange.base.errors import (
    AmbiguousResultError,
    AuthError,
    DuplicateClientIdError,
    NotFoundError,
    OmsErrorCode,
    RateBudgetExceededError,
    TransportError,
)
from candleviewer.exchange.base.fakes import (
    CANCEL_ALL_LIMIT,
    CANCEL_ALL_SCOPE,
    FakeCall,
    FakeOutcome,
    FakeReject,
    LandedThenAmbiguous,
    fake_capabilities,
)
from candleviewer.exchange.base.models import (
    AccountInfo,
    AccountRef,
    AmendOrderRequest,
    CancelOrderRequest,
    ClosedPnl,
    Execution,
    FeeRate,
    Order,
    PlaceOrderRequest,
    Position,
    PrivateEvent,
    TradingStopRequest,
    Wallet,
)
from candleviewer.oms.order_link import OrderLinkIdParts
from candleviewer.oms.order_link_resolution import Adopted, place_or_adopt

ACCOUNT = AccountId(UUID("5b1c9d2e-7f30-4a6b-8c4d-2e3f4a5b6c7d"))
OTHER = AccountId(UUID("6c2d0e3f-8041-4b7c-9d5e-3f4a5b6c7d8e"))
GROUP = UUID("0f8e2b6c-3d4a-4b5c-9e7f-1a2b3c4d5e6f")
T0 = 1_790_000_000_000_000


def _ref(account_id: AccountId = ACCOUNT) -> AccountRef:
    return AccountRef(
        account_id=account_id,
        uid="100001",
        environment="demo",
        key_ref="00000000-0000-4000-8000-0000000000c1",
    )


def _link(seq: int = 0, account_id: AccountId = ACCOUNT) -> str:
    return OrderLinkIdParts.generate(
        mode="exchange",
        environment="demo",
        group_id=GroupId(GROUP),
        account_id=account_id,
        seq=seq,
        purpose="entry",
    ).value


def _place(seq: int = 0, **overrides: object) -> PlaceOrderRequest:
    fields: dict[str, object] = {
        "account": _ref(),
        "symbol": "BTCUSDT",
        "side": "buy",
        "order_type": "limit",
        "qty": Decimal("1"),
        "price": Decimal("60000"),
        "order_link_id": _link(seq),
        "stop_loss": Decimal("58000"),
    }
    return PlaceOrderRequest.model_validate(fields | overrides)


def _port() -> FakeTradingPort:
    return FakeTradingPort(environment="demo", now_us=lambda: T0)


def test_the_fake_is_a_trading_port() -> None:
    port: TradingPort = _port()
    assert isinstance(port, TradingPort)
    assert port.capabilities == fake_capabilities("demo")


def test_fake_capabilities_take_overrides_and_describe_the_environment() -> None:
    live = fake_capabilities("live", max_batch_size=5)
    assert (live.environment, live.max_batch_size, live.order_retention_days) == ("live", 5, None)
    assert fake_capabilities("demo").order_retention_days == 7


async def test_a_create_lands_with_a_deterministic_id_and_is_recorded_with_its_lane() -> None:
    port = _port()
    first = await port.place_order(_place(0))
    second = await port.place_order(_place(1, lane="critical", trigger_price=Decimal("59000")))
    assert (first.exchange_order_id, second.exchange_order_id) == (
        "fake-000000000001",
        "fake-000000000002",
    )
    assert [(c.method, c.lane) for c in port.calls] == [
        ("place_order", "entry"),
        ("place_order", "critical"),
    ]
    assert port.calls[0] == FakeCall("place_order", ACCOUNT, _place(0), "entry")
    [plain] = await port.open_orders(_ref(), order_link_id=_link(0))
    [conditional] = await port.open_orders(_ref(), order_link_id=_link(1))
    assert (plain.state, plain.order_kind, plain.stop_loss) == ("new", "order", Decimal("58000"))
    assert (conditional.state, conditional.order_kind) == ("untriggered", "conditional")


async def test_a_reused_id_is_a_duplicate_even_once_the_order_is_gone() -> None:
    port = _port()
    ack = await port.place_order(_place())
    cancel = CancelOrderRequest(
        account=_ref(), symbol="BTCUSDT", exchange_order_id=ack.exchange_order_id
    )
    assert (await port.cancel_order(cancel)).ok
    with pytest.raises(DuplicateClientIdError):
        await port.place_order(_place())
    [gone] = await port.order_history(_ref(), order_link_id=_link())
    assert (gone.state, gone.terminal_at) == ("cancelled", T0)


async def test_scripted_outcomes_come_in_order_then_the_venue_answers() -> None:
    port = _port()
    port.script(
        "place_order",
        TransportError("refused before the send"),
        FakeReject(OmsErrorCode.INSUFFICIENT_MARGIN, 110007, "insufficient"),
    )
    with pytest.raises(TransportError):
        await port.place_order(_place())
    rejected = await port.place_order(_place())
    assert (rejected.ok, rejected.error_code, rejected.exchange_ret_code) == (
        False,
        "INSUFFICIENT_MARGIN",
        110007,
    )
    assert (await port.place_order(_place())).ok  # nothing landed before: not a duplicate


async def test_a_create_that_lands_then_goes_unanswered_is_ambiguous() -> None:
    port = _port()
    port.script("place_order", LandedThenAmbiguous())
    with pytest.raises(AmbiguousResultError) as caught:
        await port.place_order(_place())
    assert caught.value.order_link_id == _link() and caught.value.retryable is False
    assert [o.order_link_id for o in await port.open_orders(_ref())] == [_link()]
    with pytest.raises(DuplicateClientIdError):
        await port.place_order(_place())


@pytest.mark.parametrize(
    "error",
    [AuthError("bad key"), RateBudgetExceededError("no token"), NotFoundError("gone")],
)
async def test_a_scripted_error_is_raised_by_any_method(error: Exception) -> None:
    port = _port()
    port.script("positions", error)
    with pytest.raises(type(error)):
        await port.positions(_ref())
    assert await port.positions(_ref()) == []


@pytest.mark.parametrize(
    ("method", "outcome"),
    [
        ("subscribe_private", TransportError("x")),
        ("wallet", FakeReject(OmsErrorCode.AUTH_ERROR)),
        ("cancel_order", LandedThenAmbiguous()),
    ],
)
def test_a_script_that_cannot_happen_is_refused(method: str, outcome: FakeOutcome) -> None:
    with pytest.raises(ValueError):
        _port().script(method, outcome)


async def test_a_batch_lands_each_order_and_answers_a_duplicate_per_item() -> None:
    port = _port()
    await port.place_order(_place(1))
    acks = await port.place_batch([_place(0), _place(1)])
    assert [(a.ok, a.error_code) for a in acks] == [(True, None), (False, "DUPLICATE_CLIENT_ID")]
    port.script("place_batch", FakeReject(OmsErrorCode.RATE_LIMITED, retryable=True))
    refused = await port.place_batch([_place(2), _place(3)])
    assert [(a.ok, a.retryable) for a in refused] == [(False, True), (False, True)]


async def test_an_amend_changes_the_order_and_a_missing_one_is_not_found() -> None:
    port = _port()
    ack = await port.place_order(_place())
    amend = AmendOrderRequest(
        account=_ref(), symbol="BTCUSDT", order_link_id=_link(), stop_loss=Decimal("58500")
    )
    assert (await port.amend_order(amend)).ok
    [order] = await port.open_orders(_ref())
    assert order.stop_loss == Decimal("58500") and order.exchange_order_id == ack.exchange_order_id
    missing = amend.model_copy(update={"order_link_id": _link(9)})
    answer = await port.amend_order(missing)
    assert (answer.ok, answer.error_code) == (False, "ORDER_NOT_FOUND")
    port.script("amend_order", FakeReject(OmsErrorCode.RATE_LIMITED))
    assert (await port.amend_order(amend)).error_code == "RATE_LIMITED"


async def test_cancel_all_cancels_plain_orders_only_and_records_its_scope() -> None:
    port = _port()
    await port.place_order(_place(0))
    await port.place_order(_place(1, trigger_price=Decimal("59000")))
    port.seed_order(_order(ext_key("tp-1"), "tp-1", kind="partial_stop_loss"), uid="100001")
    acks = await port.cancel_all(_ref(), "BTCUSDT")
    assert [a.order_link_id for a in acks] == [_link(0)]
    assert {o.order_kind for o in await port.open_orders(_ref())} == {
        "conditional",
        "partial_stop_loss",
    }
    assert port.cancel_all_scopes == [(ACCOUNT, "BTCUSDT", CANCEL_ALL_SCOPE)]
    port.script("cancel_all", FakeReject(OmsErrorCode.RATE_LIMITED))
    [refused] = await port.cancel_all(_ref(), None)
    assert (refused.ok, refused.order_link_id) == (False, None)


async def test_one_cancel_all_takes_at_most_its_limit_the_oldest_first() -> None:
    """As the venue's futures cancel-all takes 500 a call (24 §14.2 rule 12): the caller repeats
    it until the book is empty."""
    port = FakeTradingPort(environment="demo", now_us=lambda: T0, cancel_all_limit=2)
    for seq in range(3):
        await port.place_order(_place(seq))
    first = await port.cancel_all(_ref(), None)
    assert [a.order_link_id for a in first] == [_link(0), _link(1)]
    assert [o.order_link_id for o in await port.open_orders(_ref())] == [_link(2)]
    assert [a.order_link_id for a in await port.cancel_all(_ref(), None)] == [_link(2)]
    assert await port.cancel_all(_ref(), None) == []


def test_the_cancel_all_limit_is_the_venues_by_default_and_never_below_one() -> None:
    assert FakeTradingPort()._cancel_all_limit == CANCEL_ALL_LIMIT == 500
    with pytest.raises(ValueError, match="at least one"):
        FakeTradingPort(cancel_all_limit=0)


def _order(order_link_id: str, exchange_order_id: str, *, kind: str = "order") -> Order:
    return Order.model_validate(
        {
            "order_link_id": order_link_id,
            "exchange_order_id": exchange_order_id,
            "account_id": ACCOUNT,
            "symbol": "BTCUSDT",
            "side": "sell",
            "order_type": "market",
            "qty": Decimal("1"),
            "price": None,
            "state": "untriggered",
            "filled_qty": Decimal(0),
            "leaves_qty": Decimal("1"),
            "avg_fill_price": None,
            "created_at": T0,
            "terminal_at": None,
            "order_kind": kind,
        }
    )


def _position(account_id: AccountId = ACCOUNT) -> Position:
    return Position(
        account_id=account_id,
        symbol="BTCUSDT",
        position_idx=0,
        side="buy",
        qty=Decimal("1"),
        avg_entry_price=Decimal("60000"),
        mark_price=Decimal("60100"),
        liq_price=None,
        leverage=Decimal("5"),
        unrealised_pnl=Decimal("100"),
        cum_realised_pnl=Decimal(0),
        take_profit=None,
        stop_loss=None,
        trailing_stop_distance=None,
        updated_at=T0,
    )


async def test_position_writes_change_the_seeded_position() -> None:
    port = _port()
    port.seed_position(_position())
    port.seed_position(_position(OTHER))
    stop = TradingStopRequest(account=_ref(), symbol="BTCUSDT", stop_loss=Decimal("58000"))
    ack = await port.set_trading_stop(stop)
    await port.set_leverage(_ref(), "BTCUSDT", Decimal("3"))
    [mine] = await port.positions(_ref())
    assert (ack.ok, ack.order_link_id) == (True, None)
    assert (mine.stop_loss, mine.leverage) == (Decimal("58000"), Decimal("3"))
    [theirs] = await port.positions(_ref(OTHER))
    assert (theirs.stop_loss, theirs.leverage) == (None, Decimal("5"))
    port.script("set_trading_stop", FakeReject(OmsErrorCode.UNKNOWN_STATE))
    assert (await port.set_trading_stop(stop)).ok is False


async def test_reads_answer_the_seeded_state_by_account_and_window() -> None:
    port = _port()
    fill = Execution(
        exec_id="x-1", exchange_order_id="fake-000000000001", order_link_id=_link(),
        account_id=ACCOUNT, symbol="BTCUSDT", side="buy", price=Decimal("60000"),
        qty=Decimal("1"), fee=Decimal("0.1"), fee_rate=Decimal("0.00055"), fee_currency="USDT",
        is_maker=False, exec_type="trade", closed_pnl=None, ts_exec=T0, ts_ingest=T0, seq=1,
    )  # fmt: skip
    closed = ClosedPnl(
        account_id=ACCOUNT, symbol="BTCUSDT", side="sell", qty=Decimal("1"),
        avg_entry_price=Decimal("60000"), avg_exit_price=Decimal("61000"),
        closed_pnl=Decimal("1000"), leverage=Decimal("5"), opened_at=T0, closed_at=T0,
    )  # fmt: skip
    port.seed_execution(fill)
    port.seed_closed_pnl(closed)
    assert await port.executions(_ref(), T0, T0) == [fill]
    assert await port.executions(_ref(), T0 + 1, T0 + 2) == []
    assert await port.executions(_ref(OTHER), T0, T0) == []
    assert await port.closed_pnl(_ref(), T0 - 1, T0) == [closed]
    assert await port.order_history(_ref(), start=T0 + 1) == []


async def test_account_reads_answer_what_was_set_and_refuse_what_was_not() -> None:
    port = _port()
    for read in (port.wallet(_ref()), port.fee_rate(_ref(), "BTCUSDT"), port.account_info(_ref())):
        with pytest.raises(NotFoundError):
            await read
    wallet = Wallet(
        account_id=ACCOUNT, equity=Decimal(1), wallet_balance=Decimal(1),
        available_to_withdraw=None, available_margin=Decimal(1), used_margin=Decimal(0),
        unrealised_pnl=Decimal(0), cum_realised_pnl=Decimal(0), account_im_rate=Decimal(0),
        account_mm_rate=Decimal(0), updated_at=T0,
    )  # fmt: skip
    fee = FeeRate(
        symbol="BTCUSDT", maker=Decimal("0.0002"), taker=Decimal("0.00055"), fetched_at=T0
    )
    info = AccountInfo(
        account_id=ACCOUNT, uid="100001", margin_mode="regular", position_mode=None,
        unified_margin=True,
    )  # fmt: skip
    port.set_wallet(wallet)
    port.set_fee_rate(ACCOUNT, fee)
    port.set_account_info(info)
    assert (await port.wallet(_ref()), await port.fee_rate(_ref(), "BTCUSDT")) == (wallet, fee)
    assert await port.account_info(_ref()) == info


def _event(account_id: AccountId, seq: int) -> PrivateEvent:
    return PrivateEvent(
        kind="position",
        account_id=account_id,
        payload=_position(account_id),
        ts_event=T0,
        ts_ingest=T0,
        seq=seq,
    )


async def test_the_private_stream_replays_the_seeded_then_the_pushed_events() -> None:
    port = FakeTradingPort(private_events=[_event(ACCOUNT, 1), _event(OTHER, 2)])
    port.push(_event(OTHER, 3))
    port.push(_event(ACCOUNT, 4))
    port.end_stream()
    stream = await port.subscribe_private(_ref())
    seen = [event.seq async for event in stream]
    assert seen == [1, 4]


async def test_the_private_stream_is_bounded_and_refuses_another_environment() -> None:
    port = FakeTradingPort(queue_size=1)
    port.push(_event(ACCOUNT, 1))
    with pytest.raises(asyncio.QueueFull):
        port.push(_event(ACCOUNT, 2))
    live = _ref().model_copy(update={"environment": "live"})
    with pytest.raises(ValueError, match="another environment"):
        await port.subscribe_private(live)


async def test_success_after_lookup_runs_over_the_fake_as_over_the_exchange() -> None:
    """The OMS's `place_or_adopt` adopts what the fake holds under a reused id (24 §8.3 rule 3)."""
    port = _port()
    first = await port.place_order(_place())
    outcome = await place_or_adopt(port, _place())
    assert isinstance(outcome, Adopted) and outcome.source == "realtime"
    assert outcome.order.exchange_order_id == first.exchange_order_id
    assert [c.method for c in port.calls] == ["place_order", "place_order", "open_orders"]


async def test_a_cancel_meets_only_this_accounts_orders_and_can_be_scripted() -> None:
    port = _port()
    await port.place_order(_place())
    other = await port.cancel_order(
        CancelOrderRequest(account=_ref(OTHER), symbol="BTCUSDT", order_link_id=_link())
    )
    assert (other.ok, other.error_code) == (False, "ORDER_NOT_FOUND")
    port.script("cancel_order", FakeReject(OmsErrorCode.RATE_LIMITED, retryable=True))
    scripted = await port.cancel_order(
        CancelOrderRequest(account=_ref(), symbol="BTCUSDT", order_link_id=_link())
    )
    assert (scripted.ok, scripted.retryable) == (False, True)


@pytest.mark.parametrize("second", ["account", "lane"])
async def test_a_batch_is_one_accounts_in_one_lane(second: str) -> None:
    other = (
        _place(1, account=_ref(OTHER), order_link_id=_link(1, OTHER))
        if second == "account"
        else _place(1, lane="critical")
    )
    with pytest.raises(ValueError, match="one account's, in one lane"):
        await _port().place_batch([_place(0), other])
