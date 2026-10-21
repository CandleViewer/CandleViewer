"""The trading port's error surface (G-8, #2877; ruling 11) and the duplicate rule (ruling R9).

A venue answer with a return code is an `OrderAck(ok=False)` that B1 records as a rejection;
a create's duplicate and a create's open outcome raise; a transport fault and a local refusal
raise; a read raises on every failure; no exception leaves with a cause or context, which can
hold the signed request (SR-E29-08). Replies are transcribed shapes (ruling R2) or the corpus.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from structlog.testing import capture_logs

from candleviewer.domain.order_link import ext_key
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.boundary import exchange_errors_total
from candleviewer.exchange.base.errors import (
    AmbiguousResultError,
    AuthError,
    DuplicateClientIdError,
    ExchangeError,
    InstrumentFilterError,
    RateBudgetExceededError,
    RateLimitError,
    TransportError,
    UnknownStateError,
)
from candleviewer.exchange.base.models import AmendOrderRequest, CancelOrderRequest
from candleviewer.exchange.bybit import trading
from candleviewer.exchange.bybit.config import EndpointClass
from candleviewer.exchange.bybit.trading import BybitTradingPort
from candleviewer.oms.order_link_resolution import Adopted, place_or_adopt
from candleviewer.secrets import (
    CredentialBorrower,
    CredentialUnavailable,
    KekUnavailable,
    RequestSignature,
    SecretsError,
    WithdrawPermissionRejected,
)
from candleviewer.secrets.errors import SnapshotInvalid
from tests._corpus import rest
from tests._signing import Call, fake_capability
from tests.unit.exchange.bybit._trading import (
    NOW_US,
    FakeClock,
    RecordingGovernor,
    Venue,
    account,
    link,
    make_port,
    place,
    with_result,
)

DUPLICATE = rest("rest/trading-error-110072.json")
MISSING = rest("rest/trading-error-110001.json")
CANCEL = rest("rest/trading-cancel-reply.json")
ORDER_ID = CANCEL["result"]["orderId"]


def _bare(error: BaseException) -> bool:
    return error.__cause__ is None and error.__context__ is None


def _cancel() -> CancelOrderRequest:
    return CancelOrderRequest(account=account(), symbol="BTCUSDT", exchange_order_id=ORDER_ID)


async def test_a_creates_duplicate_raises_for_the_oms_to_adopt() -> None:
    venue = Venue().on("/v5/order/create", DUPLICATE)
    with pytest.raises(DuplicateClientIdError) as caught:
        await make_port(venue).place_order(place())
    error = caught.value
    assert (error.exchange_ret_code, error.exchange_ret_msg) == (110072, DUPLICATE["retMsg"])
    assert _bare(error) and len(venue.sent) == 1  # no lookup, no resend in M4


@pytest.mark.parametrize(
    ("answer", "code", "error_code"),
    [(DUPLICATE, 110072, "UNKNOWN_STATE"), (MISSING, 110001, "ORDER_NOT_FOUND")],
    ids=["110072", "110001"],
)
async def test_a_cancel_answered_with_a_code_comes_back_as_a_rejection(
    answer: dict[str, object], code: int, error_code: str
) -> None:
    """A duplicate code on a cancel is no duplicate (R9): the exchange answered, B1 records it."""
    ack = await make_port(Venue().on("/v5/order/cancel", answer)).cancel_order(_cancel())
    assert (ack.ok, ack.error_code, ack.exchange_ret_code) == (False, error_code, code)
    assert ack.exchange_ret_msg == answer["retMsg"] and ack.exchange_order_id is None
    assert ack.record is not None and ack.record.ret_code == code


async def test_an_amend_answered_with_a_duplicate_code_is_a_rejection_too() -> None:
    request = AmendOrderRequest(
        account=account(), symbol="BTCUSDT", order_link_id=link(), qty=Decimal("0.02")
    )
    ack = await make_port(Venue().on("/v5/order/amend", DUPLICATE)).amend_order(request)
    assert (ack.ok, ack.error_code, ack.order_link_id) == (False, "UNKNOWN_STATE", link())


async def test_a_rate_limited_cancel_is_a_retryable_rejection() -> None:
    port = make_port(Venue().on("/v5/order/cancel", rest("rest/error_10018.json")))
    ack = await port.cancel_order(_cancel())
    assert (ack.ok, ack.error_code, ack.retryable) == (False, "RATE_LIMITED", True)


@pytest.mark.parametrize("code", [110079, 999999])
async def test_a_create_answered_with_an_open_outcome_code_raises(code: int) -> None:
    """24 §8.6 "Order creates": its outcome is open, so B1 takes it to `unknown`."""
    answer = {**DUPLICATE, "retCode": code}  # the transcribed envelope, another code
    with pytest.raises(UnknownStateError) as caught:
        await make_port(Venue().on("/v5/order/create", answer)).place_order(place())
    assert caught.value.retryable is False and _bare(caught.value)


async def test_a_creates_5xx_is_ambiguous_and_bare() -> None:
    venue = Venue().on("/v5/order/create", rest("rest/error_503.json"), status=503)
    with pytest.raises(AmbiguousResultError) as caught:
        await make_port(venue).place_order(place())
    assert caught.value.order_link_id == link() and _bare(caught.value)


async def test_a_create_whose_answer_names_another_order_is_ambiguous() -> None:
    """The transcribed reply echoes the documentation's own id, not ours."""
    venue = Venue().on("/v5/order/create", rest("rest/trading-create-reply.json"))
    with pytest.raises(AmbiguousResultError) as caught:
        await make_port(venue).place_order(place())
    assert caught.value.order_link_id == link() and _bare(caught.value)


async def test_a_create_whose_answer_is_unreadable_is_ambiguous() -> None:
    malformed = with_result(rest("rest/trading-create-reply.json"), orderId=12)
    with pytest.raises(AmbiguousResultError):
        await make_port(Venue().on("/v5/order/create", malformed)).place_order(place())


CREATED = rest("rest/trading-create-reply.json")


@pytest.mark.parametrize(
    "answer",
    [
        with_result(CREATED, orderId="", orderLinkId=link()),
        {key: value for key, value in CREATED.items() if key != "result"},
        {**CREATED, "result": None},
        {**CREATED, "result": {}},
        with_result(CREATED, orderLinkId=link(seq=9)),
    ],
    ids=["empty-order-id", "no-result", "null-result", "empty-result", "another-orders-id"],
)
async def test_a_create_answered_zero_without_its_order_id_is_never_an_ok_ack(
    answer: dict[str, object],
) -> None:
    """The orchestrator's ruling 3 on #3972: the ack contract requires `orderId` when `ok` is
    true, so a `retCode` 0 that names no order of this id is an ambiguous outcome (`unknown`,
    never `submitted`): it raises, no ack is returned, and the create is never sent again."""
    venue = Venue().on("/v5/order/create", answer)
    with pytest.raises(AmbiguousResultError) as caught:
        await make_port(venue).place_order(place())
    assert (caught.value.order_link_id, caught.value.retryable) == (link(), False)
    assert _bare(caught.value) and len(venue.sent) == 1


#: The v5 error table's expired-key answer, as the key-verification fixtures hold it (E27-T03).
EXPIRED: dict[str, Any] = json.loads(
    (Path(__file__).parents[3] / "fixtures" / "key_verification" / "error_33004.json").read_text(
        encoding="utf-8"
    )
)


async def test_a_create_meeting_an_expired_key_is_an_auth_rejection_not_unknown() -> None:
    """33004 maps to `AUTH_ERROR` (#2877): the venue answered, so the create is a rejection B1
    records, never an open outcome that sends the order to `unknown`."""
    venue = Venue().on("/v5/order/create", EXPIRED)
    ack = await make_port(venue).place_order(place())
    assert (ack.ok, ack.error_code, ack.retryable) == (False, "AUTH_ERROR", False)
    assert (ack.exchange_ret_code, ack.exchange_ret_msg) == (33004, EXPIRED["retMsg"])
    assert len(venue.sent) == 1


async def test_a_read_meeting_an_expired_key_raises_an_auth_error() -> None:
    venue = Venue().on("/v5/position/list", EXPIRED)
    with pytest.raises(AuthError) as caught:
        await make_port(venue).positions(account())
    assert caught.value.exchange_ret_code == 33004 and _bare(caught.value)


@pytest.mark.parametrize(
    ("builder", "drop", "reason"),
    [("_cancel_body", "category", "SR-054"), ("_create_item", "orderLinkId", "C-2.10")],
    ids=["exit-without-category", "create-without-id"],
)
async def test_a_local_refusal_of_the_client_leaves_as_itself_with_nothing_taken(
    monkeypatch: pytest.MonkeyPatch, builder: str, drop: str, reason: str
) -> None:
    """24 §14.4 (ruling 11): a local refusal raises as itself. A body the client refuses before
    any token (a category it does not state, a create without its id) is a `ValueError`, never
    an unreadable answer: a create so refused never reads as an open outcome (`unknown`)."""
    build = getattr(trading, builder)
    monkeypatch.setattr(
        trading, builder, lambda req: {k: v for k, v in build(req).items() if k != drop}
    )
    venue, governor, calls = Venue(), RecordingGovernor(), list[Call]()
    port = make_port(venue, governor=governor, calls=calls)
    call = port.cancel_order(_cancel()) if builder == "_cancel_body" else port.place_order(place())
    with pytest.raises(ValueError, match=reason) as caught:
        await call
    assert not isinstance(caught.value, ExchangeError)
    assert (venue.sent, governor.acquired, calls) == ([], [], [])


async def test_a_transport_fault_on_a_read_raises_without_its_httpx_cause() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    port = BybitTradingPort(
        environment="demo",
        credentials=_credentials(),
        governor=RecordingGovernor(),
        transport=httpx.MockTransport(refuse),
        max_retries=0,
    )
    with pytest.raises(TransportError) as caught:
        await port.account_info(account())
    assert _bare(caught.value) and caught.value.__traceback__ is not None


async def test_an_undecodable_exit_answer_is_unknown_and_bare() -> None:
    def gzip_lie(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"not gzip")
        )

    port = BybitTradingPort(
        environment="demo",
        credentials=_credentials(),
        governor=RecordingGovernor(),
        transport=httpx.MockTransport(gzip_lie),
        max_retries=0,
    )
    with pytest.raises(UnknownStateError, match="DecodingError") as caught:
        await port.cancel_order(_cancel())
    assert _bare(caught.value)


async def test_a_read_raises_on_a_venue_code_too() -> None:
    port = make_port(Venue().on("/v5/order/realtime", MISSING))
    with pytest.raises(ExchangeError) as caught:
        await port.open_orders(account())
    assert caught.value.exchange_ret_code == 110001 and _bare(caught.value)


async def test_a_leverage_refusal_leaves_as_raised() -> None:
    refused = {**MISSING, "retCode": 110043, "retMsg": "leverage not modified"}
    port = make_port(Venue().on("/v5/position/set-leverage", refused))
    with pytest.raises(InstrumentFilterError) as caught:
        await port.set_leverage(account(), "BTCUSDT", Decimal("5"))
    assert caught.value.filter_name == "leverage_not_modified" and _bare(caught.value)


@pytest.mark.parametrize("leverage", [Decimal(0), Decimal(-2), Decimal("NaN"), Decimal("Inf")])
async def test_a_leverage_that_is_not_positive_is_refused_unsent(leverage: Decimal) -> None:
    venue = Venue()
    with pytest.raises(ValueError, match="positive"):
        await make_port(venue).set_leverage(account(), "BTCUSDT", leverage)
    assert venue.sent == []


def _credentials(refusal: Exception | None = None) -> CredentialBorrower:
    if refusal is None:
        return fake_capability("fixture-signer-id")

    async def sign(_credential: UUID, _message: Sequence[object], purpose: str) -> RequestSignature:
        raise refusal

    return CredentialBorrower(sign)


@pytest.mark.parametrize(
    ("refusal", "taxonomy", "retryable"),
    [
        (CredentialUnavailable("revoked"), AuthError, False),
        (WithdrawPermissionRejected("withdraw"), AuthError, False),
        (SnapshotInvalid("not json"), AuthError, False),
        (KekUnavailable("kek_unavailable"), TransportError, True),
    ],
    ids=lambda value: getattr(type(value), "code", None) or getattr(value, "__name__", None),
)
async def test_an_m2_refusal_leaves_as_its_class_says_with_nothing_sent(
    refusal: SecretsError, taxonomy: type[ExchangeError], retryable: bool
) -> None:
    """A key M2 will not use is an `AuthError` (the account is disabled, 24 §8.6); the vault
    being down is no verdict on the key: a retryable `TransportError` (24 §14.4)."""
    venue = Venue()
    port = BybitTradingPort(
        environment="demo",
        credentials=_credentials(refusal),
        governor=RecordingGovernor(),
        transport=httpx.MockTransport(venue.handler),
        max_retries=3,
    )
    with pytest.raises(ExchangeError) as caught:
        await port.place_order(place())
    error = caught.value
    assert type(error) is taxonomy and error.retryable is retryable
    assert getattr(type(refusal), "code", "") in str(error)
    assert venue.sent == [] and _bare(error)


async def test_the_rate_limit_of_a_read_leaves_as_raised() -> None:
    port = make_port(Venue().on("/v5/account/info", rest("rest/error_10018.json")))
    with pytest.raises(RateLimitError):
        await port.account_info(account())


# -- the duplicate rule end to end (R9, 24 §14.2 rule 2) ----------------------------------------


async def test_place_or_adopt_over_the_port_adopts_the_order_the_venue_holds() -> None:
    """A duplicate create, then the realtime lookup by id: the transcribed row, its id set to
    ours (a test input), is adopted; no second create is sent."""
    page = rest("rest/trading-order-realtime.json")
    row = {**page["result"]["list"][0], "orderLinkId": link()}
    ours = with_result(page, list=[row], nextPageCursor="")
    venue = Venue().on("/v5/order/create", DUPLICATE).on("/v5/order/realtime", ours)

    outcome = await place_or_adopt(make_port(venue), place(symbol="ETHUSDT"))

    assert isinstance(outcome, Adopted) and outcome.source == "realtime"
    assert outcome.order.order_link_id == link() and outcome.order.state == "new"
    assert venue.paths() == ["/v5/order/create", "/v5/order/realtime"]
    assert venue.queries()[1]["orderLinkId"] == link()


async def test_an_ext_key_that_names_another_order_is_refused_unsent() -> None:
    venue = Venue()
    request = CancelOrderRequest(
        account=account(),
        symbol="BTCUSDT",
        order_link_id=ext_key("another-order"),
        exchange_order_id=ORDER_ID,
    )
    with pytest.raises(ValueError, match="another exchange order"):
        await make_port(venue).cancel_order(request)
    assert venue.sent == []


@pytest.mark.parametrize(
    ("order_link_id", "exchange_order_id"),
    [(ext_key("x-1"), None), (None, None), ("linear-004", None)],
    ids=["ext-without-order-id", "nothing", "foreign-id"],
)
async def test_an_exit_that_cannot_name_its_order_is_refused_unsent(
    order_link_id: str | None, exchange_order_id: str | None
) -> None:
    venue = Venue()
    request = CancelOrderRequest(
        account=account(),
        symbol="BTCUSDT",
        order_link_id=order_link_id,
        exchange_order_id=exchange_order_id,
    )
    with pytest.raises(ValueError, match="exchange_order_id"):
        await make_port(venue).cancel_order(request)
    assert venue.sent == []


async def test_an_exit_answer_naming_another_order_is_unknown() -> None:
    answer = with_result(CANCEL, orderId="another-order")
    port = make_port(Venue().on("/v5/order/cancel", answer))
    with pytest.raises(UnknownStateError, match="another order"):
        await port.cancel_order(_cancel())


@pytest.mark.parametrize(
    "key",
    [ext_key("x-1"), "linear-004", link(environment="live"), link(AccountId(UUID(int=7)))],
    ids=["ext", "foreign", "other-environment", "other-account"],
)
async def test_a_create_without_a_generated_id_of_its_account_is_refused_unsent(key: str) -> None:
    venue = Venue()
    with pytest.raises(ValueError, match="order_link_id"):
        await make_port(venue).place_order(place(order_link_id=key))
    assert venue.sent == []


def _errors(cls: str) -> float:
    value: float = exchange_errors_total.labels(**{"class": cls})._value.get()
    return value


async def test_a_token_the_lane_does_not_get_is_counted_and_logged() -> None:
    """DoD C-11.2 item 9: a refused token is an adapter signal too, though nothing was sent."""
    clock = FakeClock()
    governor = RecordingGovernor(
        default_capacity=1.0, default_refill_per_s=0.1, clock=clock.now, sleep=clock.sleep
    )
    governor.drain("100001", EndpointClass.ORDER, 1.0)
    venue = Venue()
    before = _errors("RATE_BUDGET_EXCEEDED")
    with capture_logs() as logs, pytest.raises(RateBudgetExceededError):
        await make_port(venue, governor=governor, clock=clock).place_order(place())
    assert _errors("RATE_BUDGET_EXCEEDED") == before + 1 and venue.sent == []
    [line] = [e for e in logs if e["event"] == "bybit_rate_budget_exceeded"]
    assert (line["path"], line["lane"]) == ("/v5/order/create", "entry")


async def test_a_reply_the_port_cannot_read_is_counted_and_logged_without_its_content() -> None:
    """Ruling R7's drift made visible: a strict-model failure counts `UNKNOWN_STATE` and logs the
    reply's name only, never a value of the reply."""
    executions = rest("rest/trading-execution-list.json")
    row = {**executions["result"]["list"][0], "execQty": "not-a-quantity"}
    venue = Venue().on("/v5/execution/list", with_result(executions, list=[row], nextPageCursor=""))
    before = _errors("UNKNOWN_STATE")
    with capture_logs() as logs, pytest.raises(UnknownStateError, match="malformed executions"):
        await make_port(venue).executions(account(), NOW_US - 1, NOW_US)
    assert _errors("UNKNOWN_STATE") == before + 1
    [line] = [e for e in logs if e["event"] == "bybit_reply_unknown"]
    assert line == {"event": "bybit_reply_unknown", "reply": "executions", "log_level": "warning"}


async def test_an_open_outcome_the_port_finds_in_a_create_answer_is_counted_once() -> None:
    """The create's answer names another order: one `TRANSPORT_ERROR` (the ambiguity raised),
    and no `UNKNOWN_STATE` beside it, logged with the create's id only."""
    venue = Venue().on("/v5/order/create", with_result(CREATED, orderLinkId=link(seq=9)))
    before = (_errors("TRANSPORT_ERROR"), _errors("UNKNOWN_STATE"))
    with capture_logs() as logs, pytest.raises(AmbiguousResultError):
        await make_port(venue).place_order(place())
    assert (_errors("TRANSPORT_ERROR"), _errors("UNKNOWN_STATE")) == (before[0] + 1, before[1])
    [line] = [e for e in logs if e["event"] == "bybit_create_answer_ambiguous"]
    assert (line["order_link_id"], line["order_link_ids"]) == (link(), [])
