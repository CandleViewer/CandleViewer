"""Invariants 2 to 5, 8 and 9 of the trading port (G-8, #2877), with rulings R1, R5 and R13.

2. every call draws the process governor in its class and lane, with a bounded wait (OM-D08);
3. one governor per process, shared by public, trading and key-verification clients (R5);
4. demo is REST-only and the account's environment is refused before anything is sent (C-2.11);
5. `category=linear` on every call that takes it, refused unsigned otherwise (SR-054);
8. the id filters are keyword-only, sent and re-applied (E29-T02 ruling Q5);
9. `cancel-all` always sends `orderFilter=Order` (ruling R10).
Replies are the transcribed shapes of `rest/trading-*.json` (ruling R2).
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

import candleviewer.exchange.bybit as adapter_package
from candleviewer.domain.order_link import ext_key
from candleviewer.domain.primitives import Environment
from candleviewer.exchange.base.errors import ExchangeError, RateBudgetExceededError
from candleviewer.exchange.base.models import (
    AmendOrderRequest,
    CancelOrderRequest,
    TradingStopRequest,
)
from candleviewer.exchange.bybit import trading
from candleviewer.exchange.bybit.config import EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.exchange.bybit.signer import BybitSigner
from candleviewer.exchange.bybit.trading import (
    CRITICAL_WAIT_S,
    ENDPOINTS,
    BybitTradingPort,
    _rest_offset,
)
from tests._corpus import rest
from tests._signing import CREDENTIAL_ID, Call, fake_capability
from tests.unit.exchange.bybit._trading import (
    ACCOUNT_B,
    NOW_US,
    SIGNER_ID,
    FakeClock,
    RecordingGovernor,
    Venue,
    account,
    link,
    make_port,
    place,
    with_result,
)

ORDER, POSITION, READS = EndpointClass.ORDER, EndpointClass.POSITION, EndpointClass.ACCOUNT
CANCEL = rest("rest/trading-cancel-reply.json")
ORDER_ID = CANCEL["result"]["orderId"]

Call_ = Callable[[BybitTradingPort], Awaitable[object]]


def _calls() -> dict[str, tuple[Call_, str, EndpointClass, str, Any]]:
    """Each port method: how to call it, its path, class, lane and a transcribed answer."""
    ref = account()
    created = with_result(rest("rest/trading-create-reply.json"), orderLinkId=link())
    return {
        "place_order": (
            lambda p: p.place_order(place()), "/v5/order/create", ORDER, "entry", created,
        ),
        "place_order_critical": (
            lambda p: p.place_order(place(lane="critical")), "/v5/order/create", ORDER, "critical",
            created,
        ),
        "place_batch": (
            lambda p: p.place_batch([place()]), "/v5/order/create-batch", ORDER, "entry",
            rest("rest/trading-create-batch-reply.json"),
        ),
        "place_batch_critical": (
            lambda p: p.place_batch([place(lane="critical")]), "/v5/order/create-batch", ORDER,
            "critical", rest("rest/trading-create-batch-reply.json"),
        ),
        "amend_order": (
            lambda p: p.amend_order(
                AmendOrderRequest(account=ref, symbol="BTCUSDT", order_link_id=ext_key(ORDER_ID),
                                  exchange_order_id=ORDER_ID, qty=Decimal("0.02"))
            ), "/v5/order/amend", ORDER, "entry", rest("rest/trading-amend-reply.json"),
        ),
        "cancel_order": (
            lambda p: p.cancel_order(
                CancelOrderRequest(account=ref, symbol="BTCUSDT", exchange_order_id=ORDER_ID)
            ), "/v5/order/cancel", ORDER, "critical", CANCEL,
        ),
        "cancel_all": (
            lambda p: p.cancel_all(ref, None), "/v5/order/cancel-all", ORDER, "critical",
            rest("rest/trading-cancel-all-reply.json"),
        ),
        "set_trading_stop": (
            lambda p: p.set_trading_stop(
                TradingStopRequest(account=ref, symbol="BTCUSDT", stop_loss=Decimal("58000"))
            ), "/v5/position/trading-stop", POSITION, "critical",
            rest("rest/trading-trading-stop-reply.json"),
        ),
        "set_leverage": (
            lambda p: p.set_leverage(ref, "BTCUSDT", Decimal("5")), "/v5/position/set-leverage",
            POSITION, "entry", rest("rest/trading-set-leverage-reply.json"),
        ),
        "open_orders": (
            lambda p: p.open_orders(ref), "/v5/order/realtime", READS, "poll",
            with_result(rest("rest/trading-order-realtime.json"), nextPageCursor=""),
        ),
        "order_history": (
            lambda p: p.order_history(ref), "/v5/order/history", READS, "poll",
            with_result(rest("rest/trading-order-history.json"), nextPageCursor=""),
        ),
        "positions": (
            lambda p: p.positions(ref), "/v5/position/list", READS, "poll",
            rest("rest/trading-position-list.json"),
        ),
        "executions": (
            lambda p: p.executions(ref, NOW_US - 1_000_000, NOW_US), "/v5/execution/list", READS,
            "poll", with_result(rest("rest/trading-execution-list.json"), nextPageCursor=""),
        ),
        "closed_pnl": (
            lambda p: p.closed_pnl(ref, NOW_US - 1_000_000, NOW_US), "/v5/position/closed-pnl",
            READS, "poll", with_result(rest("rest/trading-closed-pnl.json"), nextPageCursor=""),
        ),
        "wallet": (
            lambda p: p.wallet(ref), "/v5/account/wallet-balance", READS, "poll",
            rest("rest/trading-wallet-balance.json"),
        ),
        "fee_rate": (
            lambda p: p.fee_rate(ref, "BTCUSDT"), "/v5/account/fee-rate", READS, "poll",
            rest("rest/trading-fee-rate.json"),
        ),
        "account_info": (
            lambda p: p.account_info(ref), "/v5/account/info", READS, "poll",
            rest("rest/trading-account-info.json"),
        ),
    }  # fmt: skip


CALLS = _calls()
WAITS = {"entry": 0.75, "critical": 5.0, "poll": 5.0}


async def _run(name: str, port: BybitTradingPort) -> None:
    """Call `name`; a transcribed answer the linear parser refuses is fine here."""
    try:
        await CALLS[name][0](port)
    except ExchangeError:
        pass


@pytest.mark.parametrize("name", sorted(CALLS))
async def test_every_call_draws_its_class_and_lane_once_with_its_wait(name: str) -> None:
    _, path, cls, lane, answer = CALLS[name]
    venue, governor = Venue().on(path, answer), RecordingGovernor()

    await _run(name, make_port(venue, governor=governor))

    assert governor.acquired == [("100001", cls, lane, WAITS[lane])]
    assert venue.paths() == [path]


@pytest.mark.parametrize("name", sorted(n for n, c in CALLS.items() if c[2] is READS))
async def test_reads_never_draw_the_order_or_position_classes(name: str) -> None:
    """OM-D02: a poll storm cannot drain the buckets exits draw from."""
    _, path, _, _, answer = CALLS[name]
    governor = RecordingGovernor()
    await _run(name, make_port(Venue().on(path, answer), governor=governor))
    assert {(cls, lane) for _, cls, lane, _ in governor.acquired} == {(READS, "poll")}


async def test_an_entry_past_its_wait_is_refused_with_nothing_sent() -> None:
    governor = RecordingGovernor(default_capacity=1.0, default_refill_per_s=0.1, clock=lambda: 0.0)
    governor.drain("100001", ORDER, 1.0)  # the bucket needs 10 s; entry waits 0.75 s
    venue, calls = Venue(), list[Call]()
    port = make_port(venue, governor=governor, calls=calls)

    with pytest.raises(RateBudgetExceededError) as refused:
        await port.place_order(place())

    assert (venue.sent, calls) == ([], [])
    assert refused.value.retryable and refused.value.retry_after_s == pytest.approx(10.0)
    assert refused.value.__cause__ is None and refused.value.__context__ is None


async def test_a_critical_exit_under_a_long_ip_hold_is_refused_with_nothing_sent() -> None:
    governor = RecordingGovernor(clock=lambda: 0.0)
    governor.hold_ip(600.0)
    venue = Venue()
    port = make_port(venue, governor=governor)
    request = CancelOrderRequest(account=account(), symbol="BTCUSDT", exchange_order_id=ORDER_ID)

    with pytest.raises(RateBudgetExceededError) as refused:
        await port.cancel_order(request)

    assert venue.sent == [] and refused.value.retry_after_s == pytest.approx(600.0)


# -- 2. the lane's wait bounds the whole call, retries included (24 §8.7) ----------------------

#: The documented rate-limit envelope (`rest/error_10018.json`); a `10006` is the same envelope
#: with the other code, a test input.
LIMITED_10018 = rest("rest/error_10018.json")
LIMITED_10006 = {**LIMITED_10018, "retCode": 10006}


def _cancel(ref_account: Any = None) -> CancelOrderRequest:
    ref_account = account() if ref_account is None else ref_account
    return CancelOrderRequest(account=ref_account, symbol="BTCUSDT", exchange_order_id=ORDER_ID)


def _reset_in(seconds: float) -> dict[str, str]:
    """The venue's reset header, `seconds` from now on the wall clock the client reads."""
    return {"X-Bapi-Limit-Reset-Timestamp": str(int((time.time() + seconds) * 1000))}


async def test_a_critical_exit_answered_10006_retries_within_its_wait() -> None:
    clock = FakeClock()
    governor = RecordingGovernor(clock=clock.now, sleep=clock.sleep)
    venue = Venue().on("/v5/order/cancel", LIMITED_10006, CANCEL)
    port = make_port(venue, governor=governor, max_retries=3, clock=clock)

    ack = await port.cancel_order(_cancel())

    assert ack.ok and len(venue.sent) == 2
    [pause] = clock.sleeps
    assert 1.0 <= pause <= CRITICAL_WAIT_S  # the jittered first backoff, inside the lane's wait
    deadlines = [deadline for *_, deadline in governor.acquired]
    assert deadlines == [CRITICAL_WAIT_S, pytest.approx(CRITICAL_WAIT_S - pause)]


@pytest.mark.parametrize("reset", [600.0, None], ids=["reset-header-600s", "no-header"])
@pytest.mark.parametrize(
    ("lane", "send"),
    [
        ("critical", lambda port: port.cancel_order(_cancel())),
        ("entry", lambda port: port.place_order(place())),
    ],
    ids=["critical", "entry"],
)
async def test_a_10018_comes_back_at_once_as_a_retryable_rejection(
    lane: str, send: Callable[[BybitTradingPort], Awaitable[Any]], reset: float | None
) -> None:
    """The hold it sets outlasts every lane's wait: no sleep, the venue's answer, whatever the
    retries (the default configuration takes three)."""
    clock = FakeClock()
    governor = RecordingGovernor(clock=clock.now, sleep=clock.sleep)
    headers = None if reset is None else _reset_in(reset)
    venue = (
        Venue()
        .on("/v5/order/cancel", LIMITED_10018, headers=headers)
        .on("/v5/order/create", LIMITED_10018, headers=headers)
    )
    port = make_port(venue, governor=governor, max_retries=3, clock=clock)

    ack = await send(port)

    assert (ack.ok, ack.error_code, ack.retryable, ack.exchange_ret_code) == (
        False,
        "RATE_LIMITED",
        True,
        10018,
    )
    assert (len(venue.sent), sum(clock.sleeps)) == (1, 0.0)
    assert [taken for _, _, taken, _ in governor.acquired] == [lane]
    assert governor.ip_hold_remaining_s() >= 600.0


async def test_an_entry_answered_10006_comes_back_at_once_as_a_retryable_rejection() -> None:
    """The first backoff (1 s at least) outlasts the entry lane's 0.75 s: no sleep, no retry."""
    clock = FakeClock()
    venue = Venue().on("/v5/order/create", LIMITED_10006)
    port = make_port(venue, max_retries=3, clock=clock)

    ack = await port.place_order(place())

    assert (ack.ok, ack.error_code, ack.retryable) == (False, "RATE_LIMITED", True)
    assert (len(venue.sent), clock.sleeps) == (1, [])


async def test_a_token_refused_for_a_retry_returns_the_answer_not_nothing_sent() -> None:
    """The answer left and came back: the refusal of the retry's token is not "nothing was
    sent" (24 §8.7), so the call answers with the venue's own rejection."""
    clock = FakeClock()
    governor = RecordingGovernor(
        default_capacity=1.0, default_refill_per_s=0.1, clock=clock.now, sleep=clock.sleep
    )
    venue = Venue().on("/v5/order/cancel", LIMITED_10006, CANCEL)
    port = make_port(venue, governor=governor, max_retries=3, clock=clock)

    ack = await port.cancel_order(_cancel())

    assert (ack.ok, ack.error_code, ack.exchange_ret_code, ack.retryable) == (
        False,
        "RATE_LIMITED",
        10006,
        True,
    )
    assert len(venue.sent) == 1 and sum(clock.sleeps) <= CRITICAL_WAIT_S


async def test_the_service_port_answers_a_10018_as_an_ack_with_its_default_retries() -> None:
    """The factory's port (three retries, the process governor, real sleeps) answers at once."""
    venue = Venue().on("/v5/order/cancel", LIMITED_10018, headers=_reset_in(600.0))
    svc = ExchangeBybitService(
        credentials=fake_capability(SIGNER_ID),
        environment="demo",
        rest_transport=httpx.MockTransport(venue.handler),
    )
    port = svc.trading_port("demo")

    async with asyncio.timeout(5.0):  # a regression would sleep out the 600 s hold
        ack = await port.cancel_order(_cancel())

    assert port._config.max_retries == 3
    assert (ack.ok, ack.error_code, ack.retryable) == (False, "RATE_LIMITED", True)
    assert len(venue.sent) == 1 and svc._governor.ip_hold_remaining_s() >= 590.0


@pytest.mark.parametrize(
    ("name", "requested", "lane"),
    [
        ("cancel_order", None, "critical"),
        ("cancel_all", None, "critical"),
        ("set_trading_stop", None, "critical"),
        ("set_leverage", None, "entry"),
        ("open_orders", None, "poll"),
        ("place_order", "critical", "critical"),
        ("place_batch", "entry", "entry"),
        ("amend_order", "critical", "critical"),
    ],
)
def test_a_calls_lane_is_the_tables_or_its_requests(name: str, requested: Any, lane: str) -> None:
    assert trading._lane(ENDPOINTS[name], requested) == lane


@pytest.mark.parametrize(
    ("name", "requested"),
    [("cancel_order", "entry"), ("open_orders", "critical"), ("place_order", None)],
    ids=["exit-given-a-lane", "read-given-a-lane", "create-given-none"],
)
def test_a_call_naming_its_lane_twice_or_never_is_refused(name: str, requested: Any) -> None:
    """One place names each lane: a call site that also names one could only mask a mismatch."""
    with pytest.raises(ValueError, match="endpoint table's or its request's"):
        trading._lane(ENDPOINTS[name], requested)


async def test_a_call_site_naming_a_lane_the_table_fixes_is_refused_unsent() -> None:
    venue, governor = Venue(), RecordingGovernor()
    port = make_port(venue, governor=governor)
    body = {"category": "linear", "symbol": "BTCUSDT", "orderId": ORDER_ID}
    with pytest.raises(ValueError, match="endpoint table's or its request's"):
        await port._trade("cancel_order", account(), body=body, lane="entry")
    assert (venue.sent, governor.acquired) == ([], [])


# -- the port's own wiring: what its factory and its caller give it -------------------------------


async def test_the_entry_wait_given_to_the_port_bounds_a_creates_token() -> None:
    """T04's rate step: the factory-set bound, not the default, is the create's token deadline."""
    venue = Venue().on("/v5/order/create", with_result(rest("rest/trading-create-reply.json"),
                                                       orderLinkId=link()))  # fmt: skip
    governor = RecordingGovernor()
    await make_port(venue, governor=governor, entry_wait_s=0.25).place_order(place())
    assert [deadline for _, _, _, deadline in governor.acquired] == [0.25]


async def test_the_retries_given_to_the_port_bound_an_exits_attempts() -> None:
    """One retry given, two attempts made: the port's client takes its caller's count."""
    venue = Venue().on("/v5/order/cancel", rest("rest/error_503.json"), status=503)
    with pytest.raises(ExchangeError):
        await make_port(venue, max_retries=1).cancel_order(_cancel())
    assert len(venue.sent) == 2


async def test_the_clock_offset_given_to_the_port_stamps_every_signed_call() -> None:
    """E08-S07: a drifted host clock is corrected by the measured offset, or every signed call
    meets `10002`."""
    venue = Venue().on("/v5/order/cancel", CANCEL)
    before_ms = int(time.time() * 1000)
    await make_port(venue, clock_offset_ms=lambda: 600_000).cancel_order(_cancel())
    after_ms = int(time.time() * 1000)
    [request] = venue.sent
    assert before_ms + 600_000 <= int(request.headers["X-BAPI-TIMESTAMP"]) <= after_ms + 600_000


async def test_each_account_draws_its_own_uids_budget() -> None:
    """C-12.7: the rate budget is per UID; a constant one would pool every account's."""
    venue = Venue().on("/v5/order/cancel", CANCEL)
    governor = RecordingGovernor()
    await make_port(venue, governor=governor).cancel_order(_cancel(account(uid="200002")))
    assert [uid for uid, _, _, _ in governor.acquired] == ["200002"]


async def test_the_service_factory_hands_the_port_its_clock_offset_and_entry_wait() -> None:
    """The composition root's values reach the port: the entry lane's bound, and the offset
    that stamps a signed call about 4 s ahead of the host's clock."""
    venue = Venue().on("/v5/order/cancel", CANCEL)
    svc = ExchangeBybitService(
        credentials=fake_capability(SIGNER_ID),
        environment="demo",
        rest_transport=httpx.MockTransport(venue.handler),
    )
    port = svc.trading_port("demo", clock_offset_ms=lambda: 4_000, entry_wait_s=0.2)
    before_ms = int(time.time() * 1000)
    await port.cancel_order(_cancel())
    after_ms = int(time.time() * 1000)
    [request] = venue.sent
    assert before_ms + 4_000 <= int(request.headers["X-BAPI-TIMESTAMP"]) <= after_ms + 4_000
    assert port._waits["entry"] == 0.2
    await port.aclose()


@pytest.mark.parametrize("entry_wait_s", [trading.DEFAULT_ENTRY_WAIT_S, 0.2])
def test_the_service_names_the_lane_waits_of_the_port_it_builds(entry_wait_s: float) -> None:
    """#913 ruling Q19: the OMS router's lane bounds are the port's own, read off the service."""
    svc = ExchangeBybitService(credentials=fake_capability(), environment="demo")
    port = svc.trading_port("demo", entry_wait_s=entry_wait_s)
    assert svc.lane_waits(entry_wait_s) == port._waits
    assert ExchangeBybitService.lane_waits() == svc.trading_port("demo")._waits


# -- 3. one governor per process (OM-D08, R5) ---------------------------------------------------


def test_the_service_builds_one_governor_for_every_client() -> None:
    svc = ExchangeBybitService(credentials=fake_capability(), environment="demo")
    port = svc.trading_port("demo")
    assert port._governor is svc._governor
    lane = svc.lane_trading_port("demo", credentials=fake_capability())  # the OMS's, #913 L1d
    assert lane._governor is svc._governor  # one budget per UID across both loops (C-12.7)
    assert svc.public_rest_client("demo")._governor is svc._governor
    verifying = svc.key_verification_calls("demo", CREDENTIAL_ID, uid="7", recv_window_ms=5000)
    assert verifying._governor is svc._verify_governor
    assert svc._verify_governor._ip is svc._governor._ip  # the IP bucket and the hold
    assert svc._verify_governor._buckets is svc._governor._buckets


def test_the_process_governor_holds_the_ip_budget_of_600_requests_per_5_s() -> None:
    """C-12.7: the governor's default is the IP budget's one definition (no client states one
    since OM-D08), so it is pinned here: 600 requests per 5 s, refilled at 120 a second."""
    svc = ExchangeBybitService(credentials=fake_capability(), environment="demo")
    bucket = svc._governor._ip.bucket
    assert (bucket.capacity, bucket.refill_per_s) == (600.0, 120.0)


async def test_a_10018_on_one_account_holds_every_other_account_and_the_public_client() -> None:
    svc = ExchangeBybitService(credentials=fake_capability(), environment="demo")
    venue = Venue().on("/v5/order/cancel", rest("rest/error_10018.json"))
    port = make_port(venue, governor=svc._governor)
    first = CancelOrderRequest(account=account(), symbol="BTCUSDT", exchange_order_id=ORDER_ID)

    refused = await port.cancel_order(first)
    with pytest.raises(RateBudgetExceededError):
        await port.cancel_order(first.model_copy(update={"account": account(ACCOUNT_B)}))

    assert (refused.ok, refused.error_code, refused.exchange_ret_code) == (
        False,
        "RATE_LIMITED",
        10018,
    )
    assert len(venue.sent) == 1  # B's cancel was never sent
    assert svc.public_rest_client("live")._governor.ip_hold_remaining_s() > 590.0  # >= 600 s


# -- 4. REST only, one environment (C-2.11, SR-040a) -------------------------------------------


def test_the_adapter_package_holds_no_trade_socket() -> None:
    """No trade-socket route (`/v5/trade`, the WS order-entry path) anywhere in the adapter."""
    root = Path(adapter_package.__file__).resolve().parent
    found = [
        (path.name, node.value)
        for path in sorted(root.glob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "/v5/trade" in node.value
    ]
    assert found == []


def _live_calls() -> dict[str, Call_]:
    """Each port method of `CALLS`, called with a live account."""
    live = account(environment="live")
    return {
        "place_order": lambda p: p.place_order(place(live)),
        "place_order_critical": lambda p: p.place_order(place(live, lane="critical")),
        "place_batch": lambda p: p.place_batch([place(live)]),
        "place_batch_critical": lambda p: p.place_batch([place(live, lane="critical")]),
        "amend_order": lambda p: p.amend_order(
            AmendOrderRequest(account=live, symbol="BTCUSDT", order_link_id=link(),
                              qty=Decimal("1"))
        ),
        "cancel_order": lambda p: p.cancel_order(
            CancelOrderRequest(account=live, symbol="BTCUSDT", order_link_id=link())
        ),
        "cancel_all": lambda p: p.cancel_all(live, None),
        "set_trading_stop": lambda p: p.set_trading_stop(
            TradingStopRequest(account=live, symbol="BTCUSDT")
        ),
        "set_leverage": lambda p: p.set_leverage(live, "BTCUSDT", Decimal("5")),
        "open_orders": lambda p: p.open_orders(live),
        "order_history": lambda p: p.order_history(live),
        "positions": lambda p: p.positions(live),
        "executions": lambda p: p.executions(live, NOW_US - 1, NOW_US),
        "closed_pnl": lambda p: p.closed_pnl(live, NOW_US - 1, NOW_US),
        "wallet": lambda p: p.wallet(live),
        "fee_rate": lambda p: p.fee_rate(live, "BTCUSDT"),
        "account_info": lambda p: p.account_info(live),
    }  # fmt: skip


LIVE_CALLS = _live_calls()


@pytest.mark.parametrize("name", sorted(CALLS))
async def test_an_account_of_another_environment_is_refused_before_anything(name: str) -> None:
    """Nothing signed, no token taken, no client built: the demo port meets a live account."""
    venue, governor, calls = Venue(), RecordingGovernor(), list[Call]()
    port = make_port(venue, governor=governor, calls=calls)

    with pytest.raises(ValueError, match="another environment"):
        await LIVE_CALLS[name](port)

    assert (venue.sent, governor.acquired, calls, port._clients) == ([], [], [], {})


@pytest.mark.parametrize(
    ("environment", "origin"),
    [("demo", ("https", "api-demo.bybit.com")), ("live", ("https", "api.bybit.com"))],
)
async def test_each_environments_port_sends_to_its_own_host(
    environment: Environment, origin: tuple[str, str]
) -> None:
    """C-2.11, SR-040a: a port signs and sends for its own environment's host only (the mock
    transport answers in-process; nothing leaves the test)."""
    venue = Venue().on("/v5/account/info", rest("rest/trading-account-info.json"))
    port = make_port(venue, environment=environment)
    await port.account_info(account(environment=environment))
    assert venue.origins() == [origin]


async def test_every_ack_says_rest() -> None:
    missing = rest("rest/trading-error-110001.json")
    venue = Venue().on("/v5/order/cancel", CANCEL, missing)
    port = make_port(venue)
    request = CancelOrderRequest(account=account(), symbol="BTCUSDT", exchange_order_id=ORDER_ID)
    acks = [await port.cancel_order(request), await port.cancel_order(request)]
    assert [(a.ok, a.transport) for a in acks] == [(True, "rest"), (False, "rest")]


def test_the_factory_pins_the_process_environment() -> None:
    svc = ExchangeBybitService(credentials=fake_capability(), environment="demo")
    assert svc.trading_port("demo").environment == "demo"
    assert svc.trading_port("demo").capabilities.supports_ws_order_entry is False
    with pytest.raises(ValueError, match="process's environment"):
        svc.trading_port("live")
    testnet = ExchangeBybitService(credentials=fake_capability(), environment="testnet")
    with pytest.raises(ValueError, match="no trading capability record"):
        testnet.trading_port("testnet")
    with pytest.raises(RuntimeError, match="no signing capability"):
        ExchangeBybitService(environment="demo").trading_port("demo")


def test_the_factory_and_port_signatures_hold_no_trade_transport() -> None:
    names = set(inspect.signature(BybitTradingPort).parameters)
    assert not {"ws", "socket", "trade_socket", "ws_connect"} & names


# -- 5. category=linear (SR-054) ----------------------------------------------------------------


#: The account endpoints, which take no category.
NO_CATEGORY = {"wallet", "account_info"}


@pytest.mark.parametrize("name", sorted(set(CALLS) - NO_CATEGORY))
async def test_every_call_that_takes_a_category_states_linear(name: str) -> None:
    _, path, _, _, answer = CALLS[name]
    venue = Venue().on(path, answer)
    await _run(name, make_port(venue))
    assert [sent["category"] for sent in venue.payloads()] == ["linear"]


@pytest.mark.parametrize("name", sorted(NO_CATEGORY))
async def test_the_account_endpoints_send_no_category(name: str) -> None:
    _, path, _, _, answer = CALLS[name]
    venue = Venue().on(path, answer)
    await _run(name, make_port(venue))
    [sent] = venue.payloads()
    assert "category" not in sent


@pytest.mark.parametrize(
    ("method", "path", "params", "body"),
    [
        ("GET", "/v5/order/realtime", {"symbol": "BTCUSDT"}, None),
        ("GET", "/v5/execution/list", {"category": "spot"}, None),
        ("POST", "/v5/order/cancel", None, {"symbol": "BTCUSDT", "orderId": "x-1"}),
        ("POST", "/v5/position/trading-stop", None, {"category": "inverse"}),
        ("GET", "/v5/account/fee-rate", {"symbol": "BTCUSDT"}, None),
        # SR-054 reads what goes on the wire: a POST sends its body, a GET its query.
        ("POST", "/v5/order/cancel", {"category": "linear"}, {"category": "spot", "orderId": "x"}),
        ("POST", "/v5/order/cancel", {"category": "linear"}, {"orderId": "x-1"}),
        ("GET", "/v5/order/realtime", None, {"category": "linear"}),
        ("GET", "/v5/order/realtime", {"category": "linear"}, {"category": "spot"}),
    ],
    ids=[
        "no-category", "spot", "no-category-post", "inverse", "fee-rate", "post-other-body",
        "post-category-in-the-query", "get-category-in-the-body", "get-other-in-the-body",
    ],
)  # fmt: skip
async def test_the_client_refuses_a_missing_or_other_category_unsigned(
    method: str, path: str, params: dict[str, str] | None, body: dict[str, str] | None
) -> None:
    venue, governor, calls = Venue(), RecordingGovernor(), list[Call]()
    client = BybitRestClient(
        RestClientConfig(base_url="https://api-demo.bybit.com"),
        uid="100001",
        signer=BybitSigner(fake_capability(SIGNER_ID, calls), CREDENTIAL_ID),
        governor=governor,
        transport=httpx.MockTransport(venue.handler),
    )
    async with client:
        with pytest.raises(ValueError, match="SR-054"):
            await client.signed_request(method, path, params=params, body=body, lane="poll")
    assert (venue.sent, governor.acquired, calls) == ([], [], [])


@pytest.mark.parametrize(
    ("method", "path", "params", "body"),
    [
        ("POST", "/v5/order/cancel", {"category": "linear"}, {"category": "linear"}),
        ("GET", "/v5/order/realtime", {"category": "linear"}, {"category": "linear"}),
    ],
    ids=["post", "get"],
)
async def test_the_client_sends_linear_stated_on_the_wire_whatever_the_other_mapping_repeats(
    method: str, path: str, params: dict[str, str], body: dict[str, str]
) -> None:
    """The mapping left behind may repeat `linear`: only another category is refused."""
    ok = {"retCode": 0, "retMsg": "OK", "result": {}}  # a test input: no shape is parsed here
    venue = Venue().on(path, ok)
    client = BybitRestClient(
        RestClientConfig(base_url="https://api-demo.bybit.com"),
        uid="100001",
        signer=BybitSigner(fake_capability(SIGNER_ID), CREDENTIAL_ID),
        governor=RecordingGovernor(),
        transport=httpx.MockTransport(venue.handler),
    )
    async with client:
        await client.signed_request(method, path, params=params, body=body, lane="poll")
    assert [sent["category"] for sent in venue.payloads()] == ["linear"]


# -- 8. the id filters (Q5) ---------------------------------------------------------------------


async def test_the_id_filters_are_keyword_only() -> None:
    port: Any = make_port(Venue())  # untyped on purpose: the calls below break the signature
    ref = account()
    with pytest.raises(TypeError):
        await port.open_orders(ref, "BTCUSDT", link())
    with pytest.raises(TypeError):
        await port.order_history(ref, link())


async def test_an_open_orders_filter_goes_on_the_wire_and_is_applied_again() -> None:
    """The transcribed row carries a foreign id, so it is not ours: filtered out."""
    page = with_result(rest("rest/trading-order-realtime.json"), nextPageCursor="")
    venue = Venue().on("/v5/order/realtime", page)
    found = await make_port(venue).open_orders(account(), order_link_id=link())
    assert found == []
    assert venue.queries() == [
        {"category": "linear", "limit": "50", "settleCoin": "USDT", "orderLinkId": link()}
    ]


async def test_a_history_filter_by_order_id_goes_on_the_wire_and_is_applied_again() -> None:
    page = with_result(rest("rest/trading-order-history.json"), nextPageCursor="")
    row_id = page["result"]["list"][0]["orderId"]
    venue = Venue().on("/v5/order/history", page, page)
    port = make_port(venue)

    found = await port.order_history(account(), exchange_order_id=row_id)
    other = await port.order_history(account(), exchange_order_id="another-order")

    assert [o.exchange_order_id for o in found] == [row_id] and other == []
    assert venue.queries()[0]["orderId"] == row_id and "orderLinkId" not in venue.queries()[0]


async def test_a_history_lookup_by_both_ids_sends_the_exchange_id_and_applies_both() -> None:
    """One id names the order on the wire, the exchange's; both are applied again locally, so a
    row under another of our ids is not this lookup's (a test input on the transcribed row)."""
    page = with_result(rest("rest/trading-order-history.json"), nextPageCursor="")
    row = page["result"]["list"][0]
    venue = Venue().on(
        "/v5/order/history", with_result(page, list=[{**row, "orderLinkId": link()}])
    )
    port = make_port(venue)

    found = await port.order_history(
        account(), order_link_id=link(), exchange_order_id=row["orderId"]
    )
    other = await port.order_history(
        account(), order_link_id=link(seq=5), exchange_order_id=row["orderId"]
    )

    assert ([o.exchange_order_id for o in found], other) == ([row["orderId"]], [])
    assert [(q.get("orderId"), q.get("orderLinkId")) for q in venue.queries()] == [
        (row["orderId"], None),
        (row["orderId"], None),
    ]


@pytest.mark.parametrize("key", [ext_key("x-1"), "linear-004", "cv-1"])
async def test_a_filter_that_is_not_a_generated_id_is_refused_unsent(key: str) -> None:
    venue = Venue()
    port = make_port(venue)
    with pytest.raises(ValueError, match="generated id"):
        await port.open_orders(account(), order_link_id=key)
    with pytest.raises(ValueError, match="generated id"):
        await port.order_history(account(), order_link_id=key)
    assert venue.sent == []


# -- 9. the cancel-all filter (R10) -------------------------------------------------------------


@pytest.mark.parametrize(("symbol", "scope"), [("BTCUSDT", "symbol"), (None, "settleCoin")])
async def test_every_cancel_all_sends_the_order_filter(symbol: str | None, scope: str) -> None:
    venue = Venue().on("/v5/order/cancel-all", rest("rest/trading-cancel-all-reply.json"))
    await make_port(venue).cancel_all(account(), symbol)
    [body] = venue.bodies()
    assert body["orderFilter"] == "Order" and body[scope] == (symbol or "USDT")
    assert set(body) == {"category", "orderFilter", scope}


# -- R1, R13 and the client cache ---------------------------------------------------------------


async def test_subscribe_private_is_refused_when_no_stream_is_wired() -> None:
    """G-8b (#3963): a port built without the adapter's registry opens no stream; another
    environment's account is refused first, as on every call."""
    port = make_port(Venue())
    with pytest.raises(ValueError, match="another environment"):
        await port.subscribe_private(account(environment="live"))
    with pytest.raises(RuntimeError, match="no private stream is wired"):
        await port.subscribe_private(account())


async def test_subscribe_private_opens_from_the_adapters_registry_on_its_clock() -> None:
    """The port delegates to the registry with the exchange clock's offset it was built with,
    which the stream signs `auth` on and counts refusals by (OQ-4)."""
    opened: list[tuple[object, object]] = []
    stream = object()

    class Registry:
        async def open(self, ref: object, *, clock_offset_ms: object = None) -> object:
            opened.append((ref, clock_offset_ms))
            return stream

    def offset() -> int | None:
        return None

    port = make_port(Venue(), private_streams=Registry(), clock_offset_ms=offset)
    returned: object = await port.subscribe_private(account())
    assert returned is stream
    assert opened == [(account(), offset)]


def test_rest_signs_on_the_measured_offset_and_on_the_hosts_clock_while_unmeasured() -> None:
    """The offset is `None` while unmeasured (G-8b OQ-4): REST then stamps the host's clock."""
    assert _rest_offset(None) is None
    unmeasured, measured = _rest_offset(lambda: None), _rest_offset(lambda: -1500)
    assert unmeasured is not None and measured is not None
    assert (unmeasured(), measured()) == (0, -1500)


@pytest.mark.parametrize(
    "key_ref",
    [
        "kref-1",
        str(CREDENTIAL_ID).upper(),
        "{" + str(CREDENTIAL_ID) + "}",
        "urn:uuid:" + str(CREDENTIAL_ID),
        str(CREDENTIAL_ID).replace("-", ""),
    ],
)
async def test_a_key_ref_that_is_not_an_api_keys_id_is_refused_unsent(key_ref: str) -> None:
    venue, calls = Venue(), list[Call]()
    port = make_port(venue, calls=calls)
    with pytest.raises(ValueError, match="api_keys id"):
        await port.wallet(account(key_ref=key_ref))
    assert (venue.sent, calls) == ([], [])


async def test_a_new_key_retires_the_old_keys_client() -> None:
    venue = Venue().on("/v5/account/info", rest("rest/trading-account-info.json"))
    calls: list[Call] = []
    port = make_port(venue, calls=calls)
    other_key = "00000000-0000-4000-8000-0000000000c2"

    await port.account_info(account())
    first = port._clients[account().account_id][1]
    await port.account_info(account())
    assert port._clients[account().account_id][1] is first  # same key: same client
    await port.account_info(account(key_ref=other_key))
    second = port._clients[account().account_id][1]

    assert second is not first and first._client.is_closed
    assert [str(credential) for credential, _, _ in calls] == [
        str(CREDENTIAL_ID),
        str(CREDENTIAL_ID),
        other_key,
    ]
    await port.aclose()
    assert port._clients == {} and second._client.is_closed


# -- cancellation propagates (24 §14.2 rule 8) ---------------------------------------------------


def _echoing_create(
    sent: list[httpx.Request], received: asyncio.Event, hang_first: asyncio.Event
) -> Any:
    """A venue that holds the first create until `hang_first` is set, then answers every create
    with the transcribed reply under the id it was sent; `received` is set by the first one."""

    async def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        received.set()
        if len(sent) == 1:
            await hang_first.wait()
        own = json.loads(request.content)  # our own request body, already bounded
        created = with_result(
            rest("rest/trading-create-reply.json"), orderLinkId=own["orderLinkId"]
        )
        return httpx.Response(200, json=created)

    return handler


async def _until(event: asyncio.Event) -> None:
    async with asyncio.timeout(5.0):  # a guard: each event is set as soon as the task reaches it
        await event.wait()


async def test_a_create_cancelled_in_flight_propagates_and_the_port_stays_usable() -> None:
    sent: list[httpx.Request] = []
    received = asyncio.Event()
    port = BybitTradingPort(
        environment="demo",
        credentials=fake_capability(SIGNER_ID),
        governor=RecordingGovernor(),
        transport=httpx.MockTransport(_echoing_create(sent, received, asyncio.Event())),
        max_retries=0,
    )
    task = asyncio.create_task(port.place_order(place()))
    await _until(received)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()
    ack = await port.place_order(place(order_link_id=link(seq=1)))
    assert (ack.ok, ack.order_link_id, len(sent)) == (True, link(seq=1), 2)


async def test_an_exit_cancelled_while_it_waits_for_its_token_leaves_the_bucket_free() -> None:
    """The cancel waits for a token on a sleeper that never returns; cancelled, it sends nothing,
    and the bucket's lock is free for the next taker, which is refused at once, not stuck."""
    sleeping = asyncio.Event()

    async def never(_seconds: float) -> None:
        sleeping.set()
        await asyncio.Event().wait()

    governor = RecordingGovernor(default_capacity=1.0, default_refill_per_s=0.5, sleep=never)
    governor.drain("100001", ORDER, 1.0)
    venue = Venue()
    port = make_port(venue, governor=governor)
    task = asyncio.create_task(
        port.cancel_order(
            CancelOrderRequest(account=account(), symbol="BTCUSDT", exchange_order_id=ORDER_ID)
        )
    )
    await _until(sleeping)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert venue.sent == []
    with pytest.raises(RateBudgetExceededError):
        async with asyncio.timeout(1.0):
            await governor.acquire("100001", ORDER, lane="critical", deadline_s=0.05)


async def test_an_exit_cancelled_in_its_retry_backoff_propagates() -> None:
    backing_off = asyncio.Event()

    async def never(_seconds: float) -> None:
        backing_off.set()
        await asyncio.Event().wait()

    venue = Venue().on("/v5/order/cancel", rest("rest/error_503.json"), status=503)
    port = BybitTradingPort(
        environment="demo",
        credentials=fake_capability(SIGNER_ID),
        governor=RecordingGovernor(),
        transport=httpx.MockTransport(venue.handler),
        max_retries=3,
        sleep=never,
    )
    task = asyncio.create_task(
        port.cancel_order(
            CancelOrderRequest(account=account(), symbol="BTCUSDT", exchange_order_id=ORDER_ID)
        )
    )
    await _until(backing_off)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled() and len(venue.sent) == 1


async def test_the_factorys_port_waits_its_default_entry_bound() -> None:
    """`ExchangeBybitService.trading_port` with its defaults: an entry waits 0.75 s at most,
    an exit 5 s (T04's rate step, 24 §8.7)."""
    created = with_result(rest("rest/trading-create-reply.json"), orderLinkId=link())
    venue = Venue().on("/v5/order/create", created).on("/v5/order/cancel", CANCEL)
    svc = ExchangeBybitService(
        credentials=fake_capability(SIGNER_ID),
        environment="demo",
        rest_transport=httpx.MockTransport(venue.handler),
    )
    governor = RecordingGovernor()
    svc._governor = governor
    port = svc.trading_port("demo")
    await port.place_order(place())
    await port.cancel_order(
        CancelOrderRequest(account=account(), symbol="BTCUSDT", exchange_order_id=ORDER_ID)
    )
    assert [(lane, deadline) for *_, lane, deadline in governor.acquired] == [
        ("entry", 0.75),
        ("critical", CRITICAL_WAIT_S),
    ]
