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
    PAIR_VARS,
    EnvCredentials,
    GuardedTransport,
    SafetyRefusal,
    check_amend,
    check_order,
    check_permissions,
    check_target,
    check_ws_url,
    load_credentials,
    new_link,
)

CAP = Decimal(250)
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
    ],
)
def test_check_order_refuses(changes: dict[str, Any], rule: str) -> None:
    with pytest.raises(SafetyRefusal, match=rule):
        check_order(_opening(**changes), max_notional=CAP)


def test_check_order_lets_a_protected_entry_and_a_reduce_only_flatten_through() -> None:
    check_order(_opening(), max_notional=CAP)
    flatten = _opening(side="Sell", orderType="Market", price=None, stopLoss=None)
    check_order(flatten | {"reduceOnly": True}, max_notional=CAP)


def test_check_amend_never_touches_the_protection() -> None:
    ref = {k: _opening()[k] for k in ("category", "symbol", "orderLinkId")}
    check_amend(ref | {"price": "2999.99"})
    with pytest.raises(SafetyRefusal, match="protection"):
        check_amend(ref | {"stopLoss": "0"})


@pytest.mark.parametrize(
    "permissions",
    [{"Wallet": ["AccountTransfer"]}, {"Withdraw": ["Withdraw"]}, {"Spot": ["withdraw"]}],
)
def test_check_permissions_refuses_a_withdrawal_or_transfer_right(
    permissions: dict[str, object],
) -> None:
    with pytest.raises(SafetyRefusal, match=r"C-2\.8"):
        check_permissions(False, permissions)


def test_check_permissions_refuses_read_only_and_passes_a_trading_key() -> None:
    trading = {"ContractTrade": ["Order", "Position"], "Wallet": []}
    with pytest.raises(SafetyRefusal, match="read-only"):
        check_permissions(True, trading)
    check_permissions(False, trading)


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
