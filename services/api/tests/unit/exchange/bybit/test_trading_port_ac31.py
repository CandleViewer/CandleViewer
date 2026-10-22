"""AC-31 and invariant 1 of G-8 (#2877; E29 threat model OM-D09, SR-E29-14).

Through the trading port, over transcribed replies (`rest/trading-*.json`, ruling R2):
`cancel-all`, a cancel by `orderId` of an `ext-` order and an amend by `orderId` of a
Partial-mode stop (the audited loosen of 24 §8.8 rule 5) are each sent on the order class in the
`critical` lane and never refused for a missing `orderLinkId`; a create without one, or a batch
item without one, is still refused, with nothing sent and no token taken.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from candleviewer.domain.order_link import ext_key
from candleviewer.exchange.base.models import AmendOrderRequest, CancelOrderRequest
from candleviewer.exchange.bybit.config import EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.signer import BybitSigner
from tests._corpus import rest
from tests._signing import CREDENTIAL_ID, Call, fake_capability
from tests.unit.exchange.bybit._trading import (
    SIGNER_ID,
    RecordingGovernor,
    Venue,
    account,
    link,
    make_port,
    with_result,
)

CANCEL_ALL = "rest/trading-cancel-all-reply.json"
CANCEL = "rest/trading-cancel-reply.json"
AMEND = "rest/trading-amend-reply.json"


async def test_cancel_all_goes_on_the_order_class_in_the_critical_lane_without_an_id() -> None:
    venue = Venue().on("/v5/order/cancel-all", rest(CANCEL_ALL))
    governor = RecordingGovernor()
    port = make_port(venue, governor=governor)

    acks = await port.cancel_all(account(), "BTCUSDT")

    assert [(cls, lane) for _, cls, lane, _ in governor.acquired] == [
        (EndpointClass.ORDER, "critical")
    ]
    [body] = venue.bodies()
    assert "orderLinkId" not in body and body["orderFilter"] == "Order"
    assert [a.exchange_order_id for a in acks] == ["1616024329462743808", "1616024287544869632"]
    assert all(a.ok and a.transport == "rest" for a in acks)


async def test_cancel_all_acks_name_each_cancelled_order_as_the_reads_would() -> None:
    """24 §14.2 rule 11: an order under a foreign id (the transcription's numeric links) is named
    by its `ext-` key, one under our own id by that id (a test input on the second row): the
    kill switch binds the cancelled rows by these names."""
    reply = rest(CANCEL_ALL)
    cancelled = reply["result"]["list"]
    ours = {**cancelled[1], "orderLinkId": link()}
    venue = Venue().on("/v5/order/cancel-all", with_result(reply, list=[cancelled[0], ours]))

    acks = await make_port(venue).cancel_all(account(), "BTCUSDT")

    assert [(a.order_link_id, a.exchange_order_id) for a in acks] == [
        (ext_key(cancelled[0]["orderId"]), cancelled[0]["orderId"]),
        (link(), cancelled[1]["orderId"]),
    ]


async def test_a_cancel_by_order_id_of_an_ext_order_goes_critical_without_an_id() -> None:
    reply = rest(CANCEL)
    order_id = reply["result"]["orderId"]
    venue = Venue().on("/v5/order/cancel", reply)
    governor = RecordingGovernor()
    port = make_port(venue, governor=governor)
    request = CancelOrderRequest(
        account=account(),
        symbol="BTCUSDT",
        order_link_id=ext_key(order_id),
        exchange_order_id=order_id,
    )

    ack = await port.cancel_order(request)

    assert [(cls, lane) for _, cls, lane, _ in governor.acquired] == [
        (EndpointClass.ORDER, "critical")
    ]
    [body] = venue.bodies()
    assert body == {"category": "linear", "orderId": order_id, "symbol": "BTCUSDT"}
    assert (ack.ok, ack.order_link_id, ack.exchange_order_id) == (True, ext_key(order_id), order_id)


async def test_an_amend_by_order_id_of_a_partial_mode_stop_goes_critical_without_an_id() -> None:
    """The audited loosen of 24 §8.8 rule 5: the OMS chose `critical` for a protective amend."""
    reply = rest(AMEND)
    order_id = reply["result"]["orderId"]
    venue = Venue().on("/v5/order/amend", reply)
    governor = RecordingGovernor()
    port = make_port(venue, governor=governor)
    request = AmendOrderRequest(
        account=account(),
        symbol="BTCUSDT",
        order_link_id=ext_key(order_id),
        exchange_order_id=order_id,
        trigger_price=Decimal("57500"),
        lane="critical",
    )

    ack = await port.amend_order(request)

    assert [(cls, lane) for _, cls, lane, _ in governor.acquired] == [
        (EndpointClass.ORDER, "critical")
    ]
    [body] = venue.bodies()
    assert "orderLinkId" not in body
    assert (body["orderId"], body["triggerPrice"]) == (order_id, "57500")
    assert ack.ok and ack.exchange_order_id == order_id


def _client(venue: Venue, governor: RecordingGovernor, calls: list[Call]) -> BybitRestClient:
    return BybitRestClient(
        RestClientConfig(base_url="https://api-demo.bybit.com", max_retries=0),
        uid="100001",
        signer=BybitSigner(fake_capability(SIGNER_ID, calls), CREDENTIAL_ID),
        governor=governor,
        transport=httpx.MockTransport(venue.handler),
    )


#: A batch whose first item carries an id and whose second does not.
_ONE_UNNAMED = [{"symbol": "BTCUSDT", "orderLinkId": "cv-1"}, {"symbol": "BTCUSDT"}]


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/v5/order/create", {"category": "linear", "symbol": "BTCUSDT"}),
        ("/v5/order/create", {"category": "linear", "symbol": "BTCUSDT", "orderLinkId": ""}),
        ("/v5/order/create-batch", {"category": "linear", "request": [{"symbol": "BTCUSDT"}]}),
        ("/v5/order/create-batch", {"category": "linear", "request": _ONE_UNNAMED}),
        ("/v5/order/create-batch", {"category": "linear", "request": []}),
    ],
    ids=["create", "create-empty-id", "batch-item", "batch-second-item", "batch-empty"],
)
@pytest.mark.parametrize("cls", list(EndpointClass), ids=str)
async def test_a_create_without_an_id_is_refused_with_nothing_sent_and_no_token(
    path: str, body: dict[str, object], cls: EndpointClass
) -> None:
    venue, governor, calls = Venue(), RecordingGovernor(), list[Call]()
    async with _client(venue, governor, calls) as client:
        with pytest.raises(ValueError, match="orderLinkId"):
            await client.signed_request("POST", path, body=body, endpoint_class=cls, lane="entry")
    assert (venue.sent, governor.acquired, calls) == ([], [], [])


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/v5/order/cancel-all", {"category": "linear", "settleCoin": "USDT"}),
        ("/v5/order/cancel", {"category": "linear", "symbol": "BTCUSDT", "orderId": "x-1"}),
        ("/v5/order/amend", {"category": "linear", "symbol": "BTCUSDT", "orderId": "x-1"}),
        ("/v5/position/trading-stop", {"category": "linear", "symbol": "BTCUSDT"}),
    ],
    ids=["cancel-all", "cancel", "amend", "trading-stop"],
)
async def test_every_exit_passes_the_guard_on_the_order_class(
    path: str, body: dict[str, object]
) -> None:
    """OM-D09: the guard that refused these exits on the order class is gone."""
    venue = Venue().on(path, rest(CANCEL))
    governor, calls = RecordingGovernor(), list[Call]()
    async with _client(venue, governor, calls) as client:
        reply = await client.signed_request(
            "POST", path, body=body, endpoint_class=EndpointClass.ORDER, lane="critical"
        )
    assert reply["retCode"] == 0 and venue.paths() == [path] and len(calls) == 1
    assert governor.acquired == [("100001", EndpointClass.ORDER, "critical", None)]
