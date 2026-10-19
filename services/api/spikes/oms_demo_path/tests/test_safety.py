"""Guard rails of the E29-K01 harness: every refusal happens before a request leaves (no network:
the inner transport is an `httpx.MockTransport`, and refusals assert it was never called)."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx
import pytest

from candleviewer.domain.order_link import OUR_ID
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.errors import DuplicateClientIdError
from candleviewer.exchange.bybit.config import (
    PRIVATE_WS_URLS,
    SIGNED_REST_BASES,
    EndpointClass,
    RestClientConfig,
)
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.signer import BybitSigner
from candleviewer.secrets import Secret
from spikes.oms_demo_path.safety import (
    DEMO_REST_BASE,
    DEMO_WS_URL,
    LINK_PREFIX,
    PAIR_VARS,
    EnvCredentials,
    GuardedTransport,
    SafetyRefusal,
    check_amend,
    check_order,
    check_permissions,
    check_request,
    check_target,
    check_ws_url,
    load_credentials,
    new_link,
)

CAP = Decimal(250)
#: A host address from the documentation range (RFC 5737), as the key-info fixture uses.
HOST = ["203.0.113.7"]
#: The Bybit v5 doc worked example (`docs/research/06-bybit-api.md`, as `test_signer.py`): the
#: placeholder is both the key id and the synthetic secret; the MAC is the doc's fixed value.
DOC_PLACEHOLDER = "XXXXXXXXXX"
DOC_POST = (1658385579423, '{"category":"option"}')
DOC_POST_MAC = "ff137e622dc52629f41b52ea614eab59502e2b0663f153c528cb570379c469b7"


def _opening(**changes: Any) -> dict[str, Any]:
    body = {
        "category": "linear",
        "symbol": "ETHUSDT",
        "side": "Buy",
        "orderType": "Limit",
        "qty": "0.05",
        "price": "3000.00",
        "stopLoss": "2940.00",
        "orderLinkId": new_link(AccountId(uuid4()), "entry"),
    }
    return {k: v for k, v in (body | changes).items() if v is not None}


def _live_link() -> str:
    """A well-formed 24 §8.3 id for the live environment (`cvl-`): never a demo order (C-2.11)."""
    link = new_link(AccountId(uuid4()), "entry")
    return f"{link[:2]}l{link[3:]}"


def _transport(seen: list[httpx.Request], replies: list[httpx.Response] | None = None) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return replies.pop(0) if replies else httpx.Response(200, json={"retCode": 0})

    recorded: list[tuple[int, bytes, float]] = []
    guarded = GuardedTransport(
        httpx.MockTransport(handler),
        lambda _req, status, _headers, raw, rtt: recorded.append((status, raw, rtt)),
        max_notional=CAP,
    )
    return guarded, recorded


@pytest.mark.parametrize("env", ["live", "testnet"])
def test_check_target_refuses_live_and_testnet(env: str) -> None:
    with pytest.raises(SafetyRefusal):
        check_target(env, SIGNED_REST_BASES[env], PRIVATE_WS_URLS[env])


def test_check_target_refuses_demo_env_on_another_host() -> None:
    with pytest.raises(SafetyRefusal):
        check_target("demo", SIGNED_REST_BASES["live"], DEMO_WS_URL)
    with pytest.raises(SafetyRefusal):
        check_ws_url(PRIVATE_WS_URLS["live"])
    check_target("demo", DEMO_REST_BASE, DEMO_WS_URL)


@pytest.mark.parametrize(
    "url",
    [
        f"{SIGNED_REST_BASES['live']}/v5/market/time",
        f"{SIGNED_REST_BASES['testnet']}/v5/market/time",
        f"{DEMO_REST_BASE}/v5/account/fee-rate",
        "http://api-demo.bybit.com/v5/market/time",
    ],
    ids=["live-host", "testnet-host", "path-off-list", "plain-http"],
)
async def test_guarded_transport_refuses_before_sending(url: str) -> None:
    seen: list[httpx.Request] = []
    guarded, recorded = _transport(seen)
    with pytest.raises(SafetyRefusal):
        await guarded.handle_async_request(httpx.Request("GET", url))
    assert seen == [] and recorded == []


async def test_guarded_transport_refuses_an_opening_order_without_stop_loss() -> None:
    seen: list[httpx.Request] = []
    guarded, _ = _transport(seen)
    body = json.dumps(_opening(stopLoss=None)).encode()
    request = httpx.Request("POST", f"{DEMO_REST_BASE}/v5/order/create", content=body)
    with pytest.raises(SafetyRefusal, match="native stopLoss"):
        await guarded.handle_async_request(request)
    assert seen == []


async def test_guarded_transport_sends_an_allowed_request_and_records_it() -> None:
    seen: list[httpx.Request] = []
    guarded, recorded = _transport(seen)
    reply = await guarded.handle_async_request(
        httpx.Request("GET", f"{DEMO_REST_BASE}/v5/market/time")
    )
    assert len(seen) == 1 and seen[0].headers["Accept-Encoding"] == "identity"
    assert json.loads(await reply.aread()) == {"retCode": 0}
    assert recorded[0][:2] == (200, b'{"retCode":0}') and recorded[0][2] >= 0


@pytest.mark.parametrize(
    ("changes", "rule"),
    [
        ({"stopLoss": None}, "native stopLoss"),
        ({"stopLoss": ""}, "native stopLoss"),
        ({"stopLoss": "3000.00"}, "below its price"),
        ({"stopLoss": "3010.00"}, "below its price"),
        ({"side": "Sell"}, "reduce-only"),
        ({"orderType": "Market", "price": None}, "Buy limit"),
        ({"symbol": "DOGEUSDT"}, "allow-list"),
        ({"category": "spot"}, "linear"),
        ({"qty": "0.10"}, "per-order cap"),
        ({"orderLinkId": "my-own-id"}, r"8\.3"),
        ({"orderLinkId": _live_link()}, r"8\.3"),
    ],
)
def test_check_order_refuses(changes: dict[str, Any], rule: str) -> None:
    with pytest.raises(SafetyRefusal, match=rule):
        check_order(_opening(**changes), max_notional=CAP)


def test_check_order_lets_a_protected_entry_and_a_reduce_only_flatten_through() -> None:
    check_order(_opening(), max_notional=CAP)
    flatten = _opening(side="Sell", orderType="Market", price=None, stopLoss=None)
    check_order(flatten | {"reduceOnly": True}, max_notional=CAP)


def _ref(order: dict[str, Any]) -> dict[str, Any]:
    return {k: order[k] for k in ("category", "symbol", "orderLinkId")}


def test_check_amend_lets_a_price_above_the_order_stop_through() -> None:
    order = _opening()
    check_amend(_ref(order) | {"price": "2999.99"}, stops={order["orderLinkId"]: Decimal(2940)})


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        ({"price": "2999.99", "stopLoss": "0"}, "protection"),
        ({"price": "2999.99", "qty": "5"}, "price only"),
        ({"qty": "5"}, "price only"),
        ({"price": "2940.00"}, "stopLoss"),
        ({"price": "2900.00"}, "stopLoss"),
        ({}, "price must be"),
    ],
    ids=["protection", "qty-and-price", "qty", "price-at-stop", "price-below-stop", "no-price"],
)
def test_check_amend_refuses_anything_but_a_price_above_the_stop(
    change: dict[str, str], rule: str
) -> None:
    order = _opening()
    with pytest.raises(SafetyRefusal, match=rule):
        check_amend(_ref(order) | change, stops={order["orderLinkId"]: Decimal(2940)})


def test_check_amend_refuses_an_order_the_run_did_not_create() -> None:
    with pytest.raises(SafetyRefusal, match="this run created"):
        check_amend(_ref(_opening()) | {"price": "2999.99"}, stops={})


def test_an_opening_create_bounds_the_amends_of_its_order() -> None:
    """The guard keeps the stop of every opening create it lets through: an amend of that order
    may not reach it (C-2.6), while a reduce-only create leaves no bound behind."""
    url = httpx.URL(f"{DEMO_REST_BASE}/v5/order/create")
    order, flatten = _opening(), _opening(side="Sell", orderType="Market", price=None)
    stops: dict[str, Decimal] = {}
    for body in (order, flatten | {"stopLoss": None, "reduceOnly": True}):
        content = json.dumps({k: v for k, v in body.items() if v is not None}).encode()
        check_request("POST", url, content, max_notional=CAP, stops=stops)
    assert stops == {order["orderLinkId"]: Decimal("2940.00")}
    amend = httpx.URL(f"{DEMO_REST_BASE}/v5/order/amend")
    low = json.dumps(_ref(order) | {"price": "2939.99"}).encode()
    with pytest.raises(SafetyRefusal, match="stopLoss"):
        check_request("POST", amend, low, max_notional=CAP, stops=stops)


@pytest.mark.parametrize(
    "permissions",
    [
        {"Wallet": ["AccountTransfer"]},
        {"Withdraw": ["Withdraw"]},
        {"Spot": ["withdraw"]},
        {"Wallet": ["AnyNewRight"]},
        {"FiatP2P": ["P2PTrade"]},
        {"BitCard": ["CardPay"]},
        {"With draw": ["Enabled"]},
    ],
    ids=["transfer", "withdraw", "withdraw-value", "wallet", "fiat", "card", "spelling"],
)
def test_check_permissions_refuses_a_key_that_may_move_funds(
    permissions: dict[str, object],
) -> None:
    with pytest.raises(SafetyRefusal, match=r"C-2\.8"):
        check_permissions(False, permissions, ips=HOST)


@pytest.mark.parametrize(
    "ips",
    [[], ["*"], ["203.0.113.0/24"], ["203.0.113.7", "*"], ["not-an-address"]],
    ids=["none", "wildcard", "range", "wildcard-too", "garbage"],
)
def test_check_permissions_refuses_a_key_without_a_host_ip_allowlist(ips: list[str]) -> None:
    with pytest.raises(SafetyRefusal, match=r"IP allowlist.*C-2\.8"):
        check_permissions(False, {"ContractTrade": ["Order", "Position"]}, ips=ips)


def test_check_permissions_refuses_read_only_and_passes_a_trading_key() -> None:
    trading = {"ContractTrade": ["Order", "Position"], "Wallet": [], "Spot": []}
    with pytest.raises(SafetyRefusal, match="read-only"):
        check_permissions(True, trading, ips=HOST)
    for ips in (HOST, ["203.0.113.7/32"], ["2001:db8::7"]):
        check_permissions(False, trading, ips=ips)


def test_new_link_follows_the_8_3_format_for_demo() -> None:
    account = AccountId(uuid4())
    entry, again, flatten = (new_link(account, p) for p in ("entry", "entry", "flatten"))
    assert all(OUR_ID.fullmatch(link) for link in (entry, again, flatten))
    assert entry[:4] == "cvd-" and len(entry) == 36 and entry != again
    assert (entry[-2:], flatten[-2:]) == ("en", "fl")


async def test_a_retried_create_reuses_its_order_link_id() -> None:
    """C-2.10 through the harness transport: a 503, then the duplicate reply, same id twice."""
    seen: list[httpx.Request] = []
    replies = [httpx.Response(503), httpx.Response(200, json={"retCode": 110072, "retMsg": "dup"})]
    guarded, _ = _transport(seen, replies)

    async def no_sleep(_: float) -> None:
        return None

    creds = EnvCredentials(Secret(DOC_PLACEHOLDER), Secret(DOC_PLACEHOLDER))
    client = BybitRestClient(
        RestClientConfig(base_url=DEMO_REST_BASE),
        signer=BybitSigner(creds, uuid4()),
        transport=guarded,
        sleep=no_sleep,
    )
    body = _opening()
    with pytest.raises(DuplicateClientIdError):
        await client.signed_request(
            "POST", "/v5/order/create", body=body, endpoint_class=EndpointClass.ORDER
        )
    await client.aclose()
    links = [json.loads(r.content)["orderLinkId"] for r in seen]
    assert links == [body["orderLinkId"]] * 2


async def test_env_credentials_sign_the_documented_vector_and_never_render() -> None:
    creds = EnvCredentials(Secret(DOC_PLACEHOLDER), Secret(DOC_PLACEHOLDER))
    timestamp, payload = DOC_POST
    signed = await BybitSigner(creds, uuid4()).sign(
        timestamp_ms=timestamp, recv_window_ms=5000, payload=payload
    )
    assert signed.signature == DOC_POST_MAC
    assert DOC_PLACEHOLDER not in repr(creds) + str(creds)


def test_load_credentials_pops_the_pair_and_refuses_a_missing_part() -> None:
    environ = dict.fromkeys(PAIR_VARS, DOC_PLACEHOLDER)
    assert isinstance(load_credentials(environ), EnvCredentials)
    assert environ == {}
    with pytest.raises(SafetyRefusal):
        load_credentials({PAIR_VARS[0]: DOC_PLACEHOLDER})


def test_every_link_the_harness_sends_starts_with_the_prefix_the_cleanup_text_names() -> None:
    """The owner finds the run's open orders by this prefix when a cleanup did not finish."""
    account = AccountId(uuid4())
    assert LINK_PREFIX == "cvd-"
    assert new_link(account, "entry").startswith(LINK_PREFIX)
    assert new_link(account, "flatten").startswith(LINK_PREFIX)
