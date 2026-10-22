"""`FakeTradingPort` (G-8, #2877): the in-memory `TradingPort` the OMS's tests drive.

Its refusals are shared with the exchange's port through `test_trading_conformance.py`; this
file covers what only the fake has: scripted outcomes, venue-like state and the private stream.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
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
    FRESH_HEADROOM_TOKENS,
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
    PrivateStreamReason,
    PrivateStreamState,
    PrivateStreamStatus,
    RateHeadroom,
    TradingStopRequest,
    Wallet,
)
from candleviewer.exchange.base.ports import PrivateStream
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
    [empty] = await port.cancel_all(_ref(), None)  # accepted, nothing cancelled: no order named
    assert (empty.ok, empty.order_link_id, empty.exchange_order_id) == (True, None, None)


def test_the_cancel_all_limit_is_the_venues_by_default_and_never_below_one() -> None:
    assert FakeTradingPort()._cancel_all_limit == CANCEL_ALL_LIMIT == 500
    with pytest.raises(ValueError, match="at least one"):
        FakeTradingPort(cancel_all_limit=0)


def _order(
    order_link_id: str,
    exchange_order_id: str,
    *,
    kind: str = "order",
    account_id: AccountId = ACCOUNT,
    state: str = "untriggered",
    created_at: int = T0,
) -> Order:
    return Order.model_validate(
        {
            "order_link_id": order_link_id,
            "exchange_order_id": exchange_order_id,
            "account_id": account_id,
            "symbol": "BTCUSDT",
            "side": "sell",
            "order_type": "market",
            "qty": Decimal("1"),
            "price": None,
            "state": state,
            "filled_qty": Decimal(0),
            "leaves_qty": Decimal("1"),
            "avg_fill_price": None,
            "created_at": created_at,
            "terminal_at": None,
            "order_kind": kind,
        }
    )


#: Where a seeded order is listed: (history, open book), by the exchange's id.
HISTORY: tuple[list[str], list[str]] = (["fake-seeded"], [])
OPEN: tuple[list[str], list[str]] = ([], ["fake-seeded"])


@pytest.mark.parametrize(
    ("state", "listed"),
    [
        ("rejected", HISTORY),
        ("partially_filled_canceled", HISTORY),
        ("filled", HISTORY),
        ("cancelled", HISTORY),
        ("deactivated", HISTORY),
        ("new", OPEN),
        ("partially_filled", OPEN),
        ("untriggered", OPEN),
        ("triggered", OPEN),
    ],
)
async def test_a_seeded_order_is_in_history_once_terminal_and_open_before(
    state: str, listed: tuple[list[str], list[str]]
) -> None:
    """The states the exchange's parser gives (24 §8.2): a terminal one is history, as the
    venue keeps it, and any other is in the open book."""
    port = _port()
    port.seed_order(_order(_link(), "fake-seeded", state=state), uid="100001")
    history = await port.order_history(_ref())
    is_open = await port.open_orders(_ref())
    assert ([o.exchange_order_id for o in history], [o.exchange_order_id for o in is_open]) == (
        listed
    )


async def test_open_orders_answer_only_the_accounts_own() -> None:
    port = _port()
    mine = _order(_link(0), "fake-mine")
    theirs = _order(_link(1, OTHER), "fake-theirs", account_id=OTHER)
    port.seed_order(mine, uid="100001")
    port.seed_order(theirs, uid="100001")
    assert (await port.open_orders(_ref()), await port.open_orders(_ref(OTHER))) == (
        [mine],
        [theirs],
    )


def _history_port() -> tuple[FakeTradingPort, Order, Order]:
    """Two orders in history: a filled one created before `T0` and a cancelled one at `T0`."""
    port = _port()
    early = _order(_link(0), "fake-early", state="filled", created_at=T0 - 10)
    late = _order(_link(1), "fake-late", state="cancelled")
    port.seed_order(early, uid="100001")
    port.seed_order(late, uid="100001")
    return port, early, late


async def test_history_filters_by_the_exchange_order_id() -> None:
    port, early, late = _history_port()
    assert await port.order_history(_ref(), exchange_order_id="fake-late") == [late]
    assert await port.order_history(_ref(), exchange_order_id="fake-early") == [early]


async def test_history_filters_by_the_window() -> None:
    port, early, late = _history_port()
    assert await port.order_history(_ref(), start=T0 - 5) == [late]
    assert await port.order_history(_ref(), end=T0 - 5) == [early]
    assert await port.order_history(_ref(), start=T0 - 10, end=T0) == [early, late]


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


def _seq(item: PrivateEvent | PrivateStreamStatus) -> int | None:
    assert isinstance(item, PrivateEvent)
    return item.seq


async def test_the_private_stream_replays_the_seeded_then_the_pushed_events() -> None:
    port = FakeTradingPort(private_events=[_event(ACCOUNT, 1), _event(OTHER, 2)])
    port.push(_event(OTHER, 3))
    port.push(_event(ACCOUNT, 4))
    port.end_stream()
    stream = await port.subscribe_private(_ref())
    seen = [_seq(event) async for event in stream]
    assert seen == [1, 4]


async def test_each_account_has_its_own_private_queue_and_every_stream_ends() -> None:
    """One account's pushed event never reaches another account's subscriber, and `end_stream`
    ends every subscription. The G-8b planner's finding: one queue shared by every account let
    a subscriber take, and drop, another account's events, and `end_stream` ended only one."""
    port = FakeTradingPort(private_events=[_event(OTHER, 1)])
    mine = await port.subscribe_private(_ref())
    theirs = await port.subscribe_private(_ref(OTHER))
    for seq, account_id in enumerate((OTHER, ACCOUNT, OTHER, ACCOUNT), start=2):
        port.push(_event(account_id, seq))
    port.end_stream()
    async with asyncio.timeout(5):  # a guard only: every event is queued before the reads
        seen_theirs = [_seq(event) async for event in theirs]
        seen_mine = [_seq(event) async for event in mine]
    assert (seen_mine, seen_theirs) == ([3, 5], [1, 2, 4])


async def test_a_stream_opened_after_the_end_replays_its_seeded_events_and_ends() -> None:
    port = FakeTradingPort(private_events=[_event(ACCOUNT, 1)])
    port.end_stream()
    async with asyncio.timeout(5):
        seen = [_seq(event) async for event in await port.subscribe_private(_ref())]
    assert seen == [1]


async def test_the_private_stream_is_bounded_and_refuses_another_environment() -> None:
    port = FakeTradingPort(queue_size=1)
    port.push(_event(ACCOUNT, 1))
    with pytest.raises(asyncio.QueueFull):
        port.push(_event(ACCOUNT, 2))
    live = _ref().model_copy(update={"environment": "live"})
    with pytest.raises(ValueError, match="another environment"):
        await port.subscribe_private(live)


def _status(
    account_id: AccountId, state: PrivateStreamState, reason: PrivateStreamReason, epoch: int = 1
) -> PrivateStreamStatus:
    return PrivateStreamStatus(
        account_id=account_id, state=state, reason=reason, epoch=epoch, ts=T0
    )


def _shown(item: PrivateEvent | PrivateStreamStatus) -> str:
    return f"{item.state}:{item.reason}" if isinstance(item, PrivateStreamStatus) else str(item.seq)


async def test_the_private_stream_interleaves_statuses_with_events_in_push_order() -> None:
    """G-8b (24 §14.2 rule 13): a stream's statuses arrive in order with its events, per account;
    the other account's never reach it."""
    port = FakeTradingPort(private_events=[_event(ACCOUNT, 1)])
    stream = await port.subscribe_private(_ref())
    for item in (
        _status(ACCOUNT, "heartbeat", "evidence"),
        _status(OTHER, "down", "socket_closed"),
        _status(ACCOUNT, "resyncing", "connected"),
        _event(ACCOUNT, 2),
        _status(ACCOUNT, "down", "pong_timeout"),
        _status(ACCOUNT, "resyncing", "reconnected", epoch=2),
        _event(ACCOUNT, 3),
    ):
        port.push(item)
    port.end_stream()
    async with asyncio.timeout(5):  # a guard only: every item is queued before the reads
        seen = [_shown(item) async for item in stream]
    expected = ["1", "heartbeat:evidence", "resyncing:connected", "2", "down:pong_timeout"]
    assert seen == [*expected, "resyncing:reconnected", "3"]


async def test_a_closed_status_is_the_streams_last_item() -> None:
    port = FakeTradingPort()
    stream = await port.subscribe_private(_ref())
    port.push(_event(ACCOUNT, 1))
    port.push(_status(ACCOUNT, "closed", "key_revoked"))
    port.push(_event(ACCOUNT, 2))
    async with asyncio.timeout(5):
        seen = [_shown(item) async for item in stream]
    assert seen == ["1", "closed:key_revoked"]


async def test_an_account_has_one_subscriber_until_its_stream_is_closed_or_ends() -> None:
    """One consumer per account (SR-E29-02), as the exchange's port refuses a second stream: an
    `aclose()`, even before a read, frees the account, and so does a stream that ended."""
    port = FakeTradingPort()
    first = await port.subscribe_private(_ref())
    with pytest.raises(ValueError, match="already has a private stream"):
        await port.subscribe_private(_ref())
    other = await port.subscribe_private(_ref(OTHER))  # another account is free
    await first.aclose()
    second = await port.subscribe_private(_ref())
    port.push(_status(ACCOUNT, "closed", "shutdown"))
    async with asyncio.timeout(5):
        assert [_shown(item) async for item in second] == ["closed:shutdown"]
    third = await port.subscribe_private(_ref())
    await third.aclose()
    with pytest.raises(StopAsyncIteration):
        await third.__anext__()  # a closed stream yields nothing more
    await other.aclose()


def test_the_headroom_reads_what_was_scripted_else_a_fresh_budget_and_records_no_call() -> None:
    """#2877 ruling 4: `headroom` is scriptable per account and lane, and like the exchange
    adapter's it sends nothing and takes no token, so no call is recorded."""
    port = _port()
    fresh = RateHeadroom(lane="entry", tokens=FRESH_HEADROOM_TOKENS, wait_s=0.0)
    assert port.headroom(_ref(), "entry") == fresh
    starved = RateHeadroom(lane="entry", tokens=0.0, wait_s=2.5)
    port.set_headroom(ACCOUNT, starved)
    assert port.headroom(_ref(), "entry") == starved
    assert port.headroom(_ref(), "critical").wait_s == 0.0  # another lane: unscripted
    assert port.headroom(_ref(OTHER), "entry") == fresh  # another account: unscripted
    assert port.calls == []
    with pytest.raises(ValueError, match="another environment"):
        port.headroom(_ref().model_copy(update={"environment": "live"}), "entry")


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


@pytest.mark.parametrize(
    "second",
    [
        lambda: _place(1, account=_ref(OTHER), order_link_id=_link(1, OTHER)),
        lambda: _place(1, lane="critical"),
    ],
    ids=["account", "lane"],
)
async def test_a_batch_is_one_accounts_in_one_lane(second: Callable[[], PlaceOrderRequest]) -> None:
    with pytest.raises(ValueError, match="one account's, in one lane"):
        await _port().place_batch([_place(0), second()])


# -- the round-3 fold (#2877): scoping, limits and the exit's order, each a mutant's test --------


async def test_cancel_all_takes_only_its_accounts_orders_of_its_symbol() -> None:
    """The multi-account and per-symbol kill switch of E29-T04 runs on this fake."""
    port = _port()
    for order in (
        _order(_link(0), "a-btc"),
        _order(_link(1), "a-eth").model_copy(update={"symbol": "ETHUSDT"}),
        _order(_link(2, OTHER), "b-btc", account_id=OTHER),
    ):
        port.seed_order(order, uid="100001")
    acks = await port.cancel_all(_ref(), "BTCUSDT")
    assert [a.exchange_order_id for a in acks] == ["a-btc"]
    assert [o.exchange_order_id for o in await port.open_orders(_ref())] == ["a-eth"]
    assert [o.exchange_order_id for o in await port.open_orders(_ref(OTHER))] == ["b-btc"]


async def test_a_rejected_cancel_all_still_records_its_scope() -> None:
    """E29-T04 asserts that every cancel-all carries its filter, a rejected one's included: the
    filter went on the wire whatever the venue answered."""
    port = _port()
    port.script("cancel_all", FakeReject(OmsErrorCode.RATE_LIMITED, retryable=True))
    [refused] = await port.cancel_all(_ref(), "BTCUSDT")
    assert refused.ok is False
    assert port.cancel_all_scopes == [(ACCOUNT, "BTCUSDT", CANCEL_ALL_SCOPE)]


async def test_history_and_closed_pnl_answer_only_the_accounts_own() -> None:
    port = _port()
    port.seed_order(_order(_link(0), "a-done", state="filled"), uid="100001")
    theirs = _order(_link(1, OTHER), "b-done", account_id=OTHER, state="filled")
    port.seed_order(theirs, uid="100001")
    mine_pnl = ClosedPnl(
        account_id=ACCOUNT, symbol="BTCUSDT", side="sell", qty=Decimal("1"),
        avg_entry_price=Decimal("60000"), avg_exit_price=Decimal("61000"),
        closed_pnl=Decimal("1000"), leverage=Decimal("5"), opened_at=T0, closed_at=T0,
    )  # fmt: skip
    port.seed_closed_pnl(mine_pnl)
    port.seed_closed_pnl(mine_pnl.model_copy(update={"account_id": OTHER}))
    assert [o.exchange_order_id for o in await port.order_history(_ref())] == ["a-done"]
    assert await port.closed_pnl(_ref(), T0 - 1, T0) == [mine_pnl]


async def test_set_leverage_changes_only_its_symbols_position() -> None:
    port = _port()
    port.seed_position(_position())
    port.seed_position(_position().model_copy(update={"symbol": "ETHUSDT"}))
    await port.set_leverage(_ref(), "ETHUSDT", Decimal("3"))
    assert {p.symbol: p.leverage for p in await port.positions(_ref())} == {
        "BTCUSDT": Decimal("5"),
        "ETHUSDT": Decimal("3"),
    }


async def test_a_position_seeded_twice_on_one_key_is_the_last_one() -> None:
    port = _port()
    port.seed_position(_position())
    resized = _position().model_copy(update={"qty": Decimal("2")})
    port.seed_position(resized)
    assert await port.positions(_ref()) == [resized]


async def test_a_market_create_lands_with_no_price_and_its_whole_quantity_left() -> None:
    """As the venue reads a market order: a price the request carried is not its price."""
    port = _port()
    await port.place_order(_place(order_type="market", qty=Decimal("3")))
    [order] = await port.open_orders(_ref())
    assert (order.order_type, order.price, order.leaves_qty) == ("market", None, Decimal("3"))


async def test_an_amend_changes_the_price_and_the_take_profit_too() -> None:
    port = _port()
    await port.place_order(_place())
    amend = AmendOrderRequest(
        account=_ref(), symbol="BTCUSDT", order_link_id=_link(), price=Decimal("60500"),
        take_profit=Decimal("65000"),
    )  # fmt: skip
    assert (await port.amend_order(amend)).ok
    [order] = await port.open_orders(_ref())
    assert (order.price, order.take_profit) == (Decimal("60500"), Decimal("65000"))


async def test_an_exit_with_an_empty_exchange_id_is_named_by_its_link() -> None:
    """An empty exchange id names nothing, as the exchange adapter reads it: the link names the
    order (24 §14.2 rule 11), for an amend and for a cancel."""
    port = _port()
    await port.place_order(_place())
    amend = AmendOrderRequest(
        account=_ref(), symbol="BTCUSDT", order_link_id=_link(), exchange_order_id="",
        qty=Decimal("2"),
    )  # fmt: skip
    assert (await port.amend_order(amend)).ok
    cancel = CancelOrderRequest(
        account=_ref(), symbol="BTCUSDT", order_link_id=_link(), exchange_order_id=""
    )
    ack = await port.cancel_order(cancel)
    assert (ack.ok, ack.order_link_id) == (True, _link())
    assert await port.open_orders(_ref()) == []


async def test_a_cancel_by_the_second_orders_exchange_id_cancels_the_second() -> None:
    port = _port()
    first = await port.place_order(_place(0))
    second = await port.place_order(_place(1))
    cancel = CancelOrderRequest(
        account=_ref(), symbol="BTCUSDT", exchange_order_id=second.exchange_order_id
    )
    ack = await port.cancel_order(cancel)
    assert (ack.order_link_id, ack.exchange_order_id) == (_link(1), second.exchange_order_id)
    assert [o.exchange_order_id for o in await port.open_orders(_ref())] == [
        first.exchange_order_id
    ]


async def test_a_refused_cancel_naming_both_ids_is_named_by_its_own_link() -> None:
    """As the exchange adapter names it: by the request's link, never the exchange id's key."""
    port = _port()
    port.script("cancel_order", FakeReject(OmsErrorCode.RATE_LIMITED, retryable=True))
    request = CancelOrderRequest(
        account=_ref(), symbol="BTCUSDT", order_link_id=_link(), exchange_order_id="fake-1"
    )
    ack = await port.cancel_order(request)
    assert (ack.ok, ack.order_link_id) == (False, _link())


async def test_a_second_subscription_after_the_end_replays_its_seeded_events_and_ends() -> None:
    """The end is sticky: a reconnect test subscribes again once the first stream has ended."""
    port = FakeTradingPort(private_events=[_event(ACCOUNT, 1)])
    port.end_stream()
    async with asyncio.timeout(5):  # a guard only: the streams end at once
        first = [_seq(event) async for event in await port.subscribe_private(_ref())]
        again = [_seq(event) async for event in await port.subscribe_private(_ref())]
    assert first == again == [1]


async def _seqs(stream: PrivateStream) -> list[int | None]:
    return [_seq(event) async for event in stream]


async def test_a_waiting_subscriber_ends_and_the_accounts_next_one_ends_at_once() -> None:
    """The end marker ends the subscriber waiting on the account's queue, and the end is
    sticky: the reader that takes it puts it back, so the next subscriber, which the account
    admits once the first has ended (one at a time, G-8b), ends at once too."""
    port = FakeTradingPort()
    reader = asyncio.ensure_future(_seqs(await port.subscribe_private(_ref())))
    port.push(_event(ACCOUNT, 1))
    await asyncio.sleep(0)  # a yield: the reader takes the event, then waits
    port.end_stream()
    async with asyncio.timeout(5):  # a guard only: both end at once
        assert await reader == [1]
        assert await _seqs(await port.subscribe_private(_ref())) == []


async def test_ending_a_full_stream_raises_nothing_and_each_ends_once_drained() -> None:
    """A full queue takes no end marker and drains first; every account's stream still ends."""
    port = FakeTradingPort(queue_size=1)
    port.push(_event(ACCOUNT, 1))
    port.push(_event(OTHER, 2))
    port.end_stream()
    async with asyncio.timeout(5):  # a guard only: the streams end at once
        mine = [_seq(event) async for event in await port.subscribe_private(_ref())]
        theirs = [_seq(event) async for event in await port.subscribe_private(_ref(OTHER))]
    assert (mine, theirs) == ([1], [2])


def test_a_private_queue_must_hold_an_event() -> None:
    """asyncio's size 0 is an unbounded queue: refused, as every queue is bounded (C-2.18)."""
    with pytest.raises(ValueError, match="at least one event"):
        FakeTradingPort(queue_size=0)
