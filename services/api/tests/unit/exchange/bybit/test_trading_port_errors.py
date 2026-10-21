"""The trading port's error surface (G-8, #2877; ruling 11) and the duplicate rule (ruling R9).

A venue answer with a return code is an `OrderAck(ok=False)` that B1 records as a rejection;
a create's duplicate and a create's open outcome raise; a transport fault and a local refusal
raise; a read raises on every failure; no exception leaves with a cause or context, which can
hold the signed request (SR-E29-08). Replies are transcribed shapes (ruling R2) or the corpus.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from uuid import UUID

import httpx
import pytest

from candleviewer.domain.order_link import ext_key
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.errors import (
    AmbiguousResultError,
    AuthError,
    DuplicateClientIdError,
    ExchangeError,
    InstrumentFilterError,
    RateLimitError,
    TransportError,
    UnknownStateError,
)
from candleviewer.exchange.base.models import AmendOrderRequest, CancelOrderRequest
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
from tests._signing import fake_capability
from tests.unit.exchange.bybit._trading import (
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
