"""#2893 S9: the fixture transport serves the account pack once the guards pass (ADR-0036 6, 7).

Requests come from the adapter's own REST client, signed as M2 signs them with each scenario's
derived secret, or are built and signed here the same way (`test_transport_guards`). The pack is
the checkout's, the request log sits under `tmp_path`, and the transport's clock is a fake one the
tests move: a key's scenario time counts from the first call it signs, the stack default's from
boot, and the stub exchange's clock follows the transport's. No socket opens and nothing sleeps.
"""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

import httpx
import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.base.errors import (
    InstrumentFilterError,
    TransportError,
    UnknownStateError,
)
from candleviewer.exchange.bybit.config import EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.key_info import (
    KEY_INFO_PATH,
    PROBE_PATH,
    ApiKeyFacts,
    parse_key_info,
    parse_probe,
    refusal,
)
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.settings import Environment
from cvdev.account_fixture.pack import Pack, Scenario, fixture_key_ids
from cvdev.account_fixture.requestlog import FILE_NAME, RequestLog
from cvdev.account_fixture.transport import PUBLIC_CALLS, FixtureTransport, _listed
from tests._account_fixtures import PACK, PACK_ROOT, load, manifest, scenario_names
from tests.unit.cvdev.test_request_log import OMS_LINK, ORDER
from tests.unit.cvdev.test_transport_guards import DEMO, _client, _get, _key, _of, _secret
from tests.unit.exchange.bybit.test_account_fixture_pack import (
    CLOSE_BODY,
    KEY_INFO,
    KEY_SCENARIOS,
    NOW,
    NOW_MS,
    ORDER_BODY,
    PROBE_FAILS,
    REFERENCE_ORDER,
    _governor,
    _no_sleep,
)

KEY_IDS: Final = fixture_key_ids(PACK)
WALLET: Final = "/v5/account/wallet-balance"
CREATE: Final = "/v5/order/create"
AMEND, STOP = "/v5/order/amend", "/v5/position/trading-stop"
#: An order id no scenario lists, and the orders working_orders_2 seeds: (orderId, orderLinkId).
FOREIGN: Final = "00000000-0000-4000-8000-0000000000f9"
_LISTED = manifest("working_orders_2")["rest"]["GET /v5/order/realtime"]["merge_patch"]["result"]
SEEDED: Final = [(order["orderId"], order["orderLinkId"]) for order in _LISTED["list"]]
#: Every call the pack stubs, but the wildcard.
PACK_CALLS: Final = {c for n in scenario_names() for c in manifest(n).get("rest", {})} - {"*"}


@dataclass
class FakeClock:
    """The transport's clock, moved by hand."""

    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


@dataclass
class Stub:
    transport: FixtureTransport
    clock: FakeClock
    log_dir: Path

    def lines(self) -> list[dict[str, Any]]:
        return [json.loads(line) for line in (self.log_dir / FILE_NAME).read_text().splitlines()]

    async def send(self, request: httpx.Request) -> tuple[int, Any, httpx.Headers]:
        response = await self.transport.handle_async_request(request)
        return response.status_code, json.loads(await response.aread()), response.headers


class _Seeded(FixtureTransport):
    """S10's seam as a switch file will use it: every key answers with these overlays seeded."""

    overlays: tuple[str, ...] = ()

    def _selection(self, key_id: str | None, now: datetime) -> tuple[Scenario, datetime]:
        scenario, started = super()._selection(key_id, now)
        return load(scenario.name, now=started, overlays=self.overlays), started


Make = Callable[..., Stub]


@pytest.fixture
def make(tmp_path: Path) -> Iterator[Make]:
    clock = FakeClock()
    with RequestLog(
        tmp_path, process_env=Environment.DEMO, clock=clock, pack_key_ids=KEY_IDS
    ) as log:

        def build(
            default: str = "compliant",
            kind: type[FixtureTransport] = FixtureTransport,
            pack: Pack = PACK,
        ) -> Stub:
            gate = ReadOnlyGate()
            transport = kind(pack, log=log, gate=gate, clock=clock, default=default)
            return Stub(transport, clock, tmp_path)

        yield build


@pytest.fixture
def stub(make: Make) -> Stub:
    return make()


def _post(scenario: str, path: str, body: Mapping[str, object]) -> httpx.Request:
    content = json.dumps(body).encode()
    headers = _get(scenario, payload=content).headers
    return httpx.Request("POST", DEMO + path, headers=headers, content=content)


async def test_exact_then_wildcard_then_extends_then_overlays_then_root(make: Make) -> None:
    stub = make(kind=_Seeded)
    # One manifest: its exact call beats its `*` (live_key_on_demo: server time, then 10003).
    assert (await stub.send(_get("live_key_on_demo", path="/v5/market/time")))[1]["retCode"] == 0
    assert (await stub.send(_get("live_key_on_demo")))[1]["retCode"] == 10003
    # Along `extends`, nearest first, then the root: the mode switches come from compliant.
    assert (await stub.send(_get("ws_quiet_rest_fail", path=WALLET)))[0] == 503
    switch = _post("ws_quiet_rest_fail", "/v5/position/switch-mode", {})
    assert (await stub.send(switch))[1]["retCode"] == 0
    # Overlays come after the scenario's own answers and before the root.
    assert isinstance(stub.transport, _Seeded)
    stub.transport.overlays = ("open_position_btcusdt_5x_sl",)
    positions = (await stub.send(_get("compliant", path="/v5/position/list")))[1]
    assert [p["symbol"] for p in positions["result"]["list"]] == ["BTCUSDT"]
    assert (await stub.send(_post("compliant", "/v5/position/switch-mode", {})))[1]["retCode"] != 0
    rejected = (await stub.send(_post("close_rejected", CREATE, CLOSE_BODY)))[1]
    assert (rejected["retCode"], rejected["result"]) == (110017, {})  # no order id echoed
    assert (await stub.send(_get("ws_drop_rest_fail", path="/v5/position/list")))[0] == 503
    stub.transport.overlays = ("working_orders_2",)
    await stub.send(_post("compliant", "/v5/position/switch-isolated", {}))
    line = stub.lines()[-1]
    assert _of(line, "scenario", "overlays", "code_unconfirmed") == (
        "compliant",
        ["working_orders_2"],
        True,
    )


async def test_from_until_window_on_scenario_time(stub: Stub) -> None:
    """ws_blip_20s fails REST from 10 s to 30 s after the key's first call, not after boot."""
    first = NOW + timedelta(hours=1)
    statuses = []
    for at_ms in (0, 9_999, 10_000, 29_999, 30_000):
        stub.clock.now = first + timedelta(milliseconds=at_ms)
        statuses.append((await stub.send(_get("ws_blip_20s", path=WALLET)))[0])
    stub.clock.now = first - timedelta(seconds=1)  # before its start, as at its start
    statuses.append((await stub.send(_get("ws_blip_20s", path=WALLET)))[0])
    assert statuses == [200, 200, 503, 503, 200, 200]


async def test_the_stack_default_counts_from_boot(make: Make) -> None:
    stub = make(default="ws_blip_20s")
    stub.clock.advance(seconds=10)
    status, _, _ = await stub.send(httpx.Request("GET", DEMO + "/v5/market/time"))
    assert status == 503
    assert _of(stub.lines()[0], "outcome", "key_class", "scenario") == (
        "served",
        "unsigned",
        "ws_blip_20s",
    )


async def test_anchoring_before_merge_patch(stub: Stub) -> None:
    """uid_mismatch pins its UID over the anchored one; the key's times stay at its first call
    while the exchange clock and the days left follow the transport's clock."""
    first = (await stub.send(_get("uid_mismatch")))[1]
    stub.clock.advance(days=1)
    later = (await stub.send(_get("uid_mismatch")))[1]
    assert parse_key_info(first) == parse_key_info(later) == KEY_INFO["uid_mismatch"]
    assert (first["time"], later["time"]) == (NOW_MS, NOW_MS + 86_400_000)
    assert first["result"]["createdAt"] == later["result"]["createdAt"] == "2026-09-16T09:00:00Z"
    assert (first["result"]["deadlineDay"], later["result"]["deadlineDay"]) == (365, 364)


async def test_http_status_and_anchored_rate_limit_headers(stub: Stub) -> None:
    await stub.send(_get("rate_limited_10018"))  # the key's scenario starts
    stub.clock.advance(seconds=5)
    status, body, headers = await stub.send(_get("rate_limited_10018"))
    assert (status, body["retCode"], body["time"]) == (200, 10018, NOW_MS + 5_000)
    assert (headers["X-Bapi-Limit"], headers["X-Bapi-Limit-Status"]) == ("10", "0")
    assert headers["X-Bapi-Limit-Reset-Timestamp"] == str(NOW_MS + 5_000 + 600_000)
    assert (await stub.send(_get("bybit_5xx")))[0] == 503
    assert [_of(line, "status", "ret_code", "scenario") for line in stub.lines()[1:]] == [
        (200, 10018, "rate_limited_10018"),
        (503, None, "bybit_5xx"),
    ]


async def test_bybit_5xx_retried_then_transport_error(stub: Stub) -> None:
    async with _client(stub.transport, DEMO, _key("bybit_5xx"), _secret("bybit_5xx")) as client:
        with pytest.raises(TransportError, match="HTTP 503 after 4 attempts"):
            await client.signed_request("GET", KEY_INFO_PATH)
    assert [_of(line, "outcome", "status", "verified") for line in stub.lines()] == [
        ("served", 503, True)
    ] * 4


async def test_unstubbed_call_is_non_2xx_and_never_success(stub: Stub) -> None:
    async with _client(stub.transport, DEMO, _key("compliant"), _secret("compliant")) as client:
        with pytest.raises(UnknownStateError, match="HTTP 404 with no usable retCode") as caught:
            await client.signed_request("GET", "/v5/position/closed-pnl")
    assert refusal(caught.value) is None  # never a verdict on the key
    [line] = stub.lines()  # never retried
    assert _of(line, "outcome", "status", "ret_code", "scenario") == (
        "unstubbed",
        404,
        None,
        "compliant",
    )


async def test_order_create_echoes_order_link_id(stub: Stub) -> None:
    links = ["fixture-order-0007", "fixture-order-0008", "fixture-order-0007"]
    order = EndpointClass.ORDER
    async with _client(stub.transport, DEMO, _key("compliant"), _secret("compliant")) as client:
        acks = [
            await client.signed_request(
                "POST", CREATE, body={**ORDER_BODY, "orderLinkId": link}, endpoint_class=order
            )
            for link in links
        ]
        cancel = {**ORDER_BODY, "orderLinkId": links[0]}
        acks.append(await client.signed_request("POST", "/v5/order/cancel", body=cancel))
    assert [ack["result"]["orderLinkId"] for ack in acks] == [*links, links[0]]
    ids = [ack["result"]["orderId"] for ack in acks]
    assert ids[0] == ids[2] == ids[3] != ids[1] and all(str(uuid.UUID(i)) == i for i in ids)


@pytest.mark.parametrize(
    ("overlays", "sent", "named"),
    [
        ((), {"orderId": FOREIGN}, (FOREIGN, "")),
        ((), {"orderId": FOREIGN, "orderLinkId": OMS_LINK}, (FOREIGN, OMS_LINK)),
        (("working_orders_2",), {"orderLinkId": SEEDED[0][1]}, SEEDED[0]),
        (("working_orders_2",), {"orderId": SEEDED[1][0]}, SEEDED[1]),
    ],
    ids=["id-only", "id-and-link", "seeded-by-link", "seeded-by-id"],
)
async def test_a_cancel_names_the_order_it_cancels(
    make: Make, overlays: tuple[str, ...], sent: dict[str, str], named: tuple[str, str]
) -> None:
    """Never another order: one the open-order list holds as listed, any other as sent, with no
    link when none is sent."""
    stub = make(kind=_Seeded)
    assert isinstance(stub.transport, _Seeded)
    stub.transport.overlays = overlays
    cancel = _post("compliant", "/v5/order/cancel", {"category": "linear", **sent})
    result = (await stub.send(cancel))[1]["result"]
    assert (result["orderId"], result["orderLinkId"]) == named


@pytest.mark.parametrize("rest", [{}, {"*": {"payload": "_base/error_10003.json"}}])
def test_an_order_list_nothing_answers_or_an_error_names_no_order(rest: dict[str, Any]) -> None:
    assert _listed(replace(load("compliant", now=NOW), chain=({"rest": rest},)), 0) == []


async def test_the_verified_body_reaches_when(stub: Stub) -> None:
    """close_rejected rejects the flatten's reduce-only close and passes plan section 9.7's
    reference order to compliant's ack."""
    key, secret = _key("close_rejected"), _secret("close_rejected")
    async with _client(stub.transport, DEMO, key, secret) as client:
        with pytest.raises(InstrumentFilterError):
            await client.signed_request(
                "POST", CREATE, body=CLOSE_BODY, endpoint_class=EndpointClass.ORDER
            )
        ack = await client.signed_request(
            "POST", CREATE, body=REFERENCE_ORDER, endpoint_class=EndpointClass.ORDER
        )
    assert (ack["retCode"], ack["result"]["orderLinkId"]) == (0, REFERENCE_ORDER["orderLinkId"])
    assert [_of(line, "outcome", "ret_code") for line in stub.lines()] == [
        ("served", 110017),
        ("served", 0),
    ]


@pytest.mark.parametrize(
    "content",
    [b"{", b"", b"[]", b'"x"', b"[" * 10_000],
    ids=["invalid", "empty", "list", "string", "recursion"],
)
async def test_a_signed_body_not_a_json_object_is_unstubbed(stub: Stub, content: bytes) -> None:
    """No `when` can read such a body, so no stub answers it, the unconditional one neither: a
    malformed close is never acked (the pack holds no 10001 reply to give instead)."""
    headers = _get("close_rejected", payload=content).headers
    request = httpx.Request("POST", DEMO + CREATE, headers=headers, content=content)
    assert (await stub.send(request))[:2] == (404, {"error": "account_fixture_unstubbed"})
    [line] = stub.lines()
    assert _of(line, "outcome", "verified", "ret_code", "order") == ("unstubbed", True, None, None)


async def test_the_log_keeps_an_orders_subset_and_no_other_field(stub: Stub) -> None:
    """Plan section 9.7's evidence that an order carried its native SL (C-2.6), from the verified
    body of a create, an amend (which the pack leaves unstubbed) and a trading-stop."""
    extra = {"category": "linear", "timeInForce": "PostOnly", "tpslMode": "Full", "takeProfit": "7"}
    sl = {"symbol": "BTCUSDT", "slTriggerBy": "MarkPrice"}
    create = REFERENCE_ORDER | extra | sl | {"orderLinkId": OMS_LINK, "reduceOnly": False}
    amend = extra | {"symbol": "BTCUSDT", "orderLinkId": OMS_LINK, "stopLoss": "56759.0"}
    for path, body in ((CREATE, create), (AMEND, amend), (STOP, extra | sl | {"stopLoss": "0"})):
        await stub.send(_post("compliant", path, body))
    none, btc = dict.fromkeys(ORDER), {"symbol": "BTCUSDT"}
    assert [_of(line, "outcome", "order") for line in stub.lines()] == [
        ("served", ORDER),
        ("unstubbed", none | btc | {"order_link_id": OMS_LINK, "stop_loss": "56759.0"}),
        ("served", none | btc | {"stop_loss": "0", "sl_trigger_by": "MarkPrice"}),
    ]


@pytest.mark.parametrize(
    "field",
    [{"orderLinkId": "not-a-minted-link"}, {"qty": "1e999999999"}, {"reduceOnly": "true"}],
    ids=["link", "exponent", "flag"],
)
async def test_an_order_outside_the_log_rules_is_logged_without_it(stub: Stub, field: Any) -> None:
    """The line keeps its path; an exponent is never parsed, so the log never formats it."""
    assert (await stub.send(_post("compliant", CREATE, REFERENCE_ORDER | field)))[0] == 200
    [line] = stub.lines()
    assert _of(line, "outcome", "path", "order") == ("served", CREATE, None)


class _Fenced(FixtureTransport):
    """A GET stub with `when`, which the pack checks refuse: guard 4 signs a GET's query, never
    its body, so a body may never steer the answer."""

    def _selection(self, key_id: str | None, now: datetime) -> tuple[Scenario, datetime]:
        scenario, started = super()._selection(key_id, now)
        stub = {"payload": "_base/error_10004.json", "when": {"body": {"reduceOnly": True}}}
        return (
            replace(scenario, chain=({"rest": {"GET /v5/position/list": stub}}, *scenario.chain)),
            started,
        )


async def test_a_body_the_signature_does_not_cover_never_meets_when(make: Make) -> None:
    stub = make(kind=_Fenced)
    content = json.dumps(CLOSE_BODY).encode()
    request = _get(path="/v5/position/list")  # signed over its empty query
    request = httpx.Request("GET", request.url, headers=request.headers, content=content)
    assert (await stub.send(request))[1]["retCode"] == 0


@pytest.mark.parametrize("name", KEY_SCENARIOS)
async def test_every_key_scenario_answers_key_info_and_probe(stub: Stub, name: str) -> None:
    expected = KEY_INFO[name]
    async with _client(stub.transport, DEMO, _key(name), _secret(name)) as client:
        if isinstance(expected, ApiKeyFacts):
            assert parse_key_info(await client.signed_request("GET", KEY_INFO_PATH)) == expected
        else:
            with pytest.raises(expected):
                await client.signed_request("GET", KEY_INFO_PATH)
        params = {"accountType": "UNIFIED"}
        if name in PROBE_FAILS:
            error, reason = PROBE_FAILS[name]
            with pytest.raises(error) as caught:
                await client.signed_request("GET", PROBE_PATH, params=params)
            found = refusal(caught.value)
            assert (found[0] if found else None) == reason
        else:
            body = await client.signed_request("GET", PROBE_PATH, params=params)
            probe = parse_probe(body, sent_at_ms=NOW_MS, received_at_ms=NOW_MS)
            assert probe.server_time_ms == NOW_MS
    seen = {_of(line, "outcome", "verified", "scenario", "stored_under") for line in stub.lines()}
    assert seen == {("served", True, name, name)}


async def test_the_adapters_unsigned_calls_answer_as_the_stack_default(make: Make) -> None:
    stub = make(default="clock_skew")
    async with BybitRestClient(
        RestClientConfig(base_url=DEMO),
        governor=_governor(),
        transport=stub.transport,
        sleep=_no_sleep,
        wall_clock=lambda: NOW_MS / 1000,
    ) as client:
        assert await client.check_reachable()
        server = await client.server_time()
    assert server.time_us == (NOW_MS + 6_000) * 1_000  # clock_skew's exchange runs 6 s ahead
    assert PUBLIC_CALLS == {"GET /v5/market/time"}
    assert [_of(line, "outcome", "key_class", "scenario") for line in stub.lines()] == [
        ("served", "unsigned", "clock_skew")
    ] * 2


@pytest.mark.parametrize("call", sorted(PACK_CALLS - PUBLIC_CALLS))
async def test_an_unsigned_private_call_is_refused_never_answered(stub: Stub, call: str) -> None:
    method, path = call.split(" ")
    with capture_logs() as events, pytest.raises(httpx.ConnectError, match="refused_key"):
        await stub.transport.handle_async_request(httpx.Request(method, DEMO + path))
    [line] = stub.lines()
    assert _of(line, "outcome", "key_class", "verified", "scenario") == (
        "refused_key",
        "unsigned",
        None,
        None,
    )
    assert [_of(e, "log_level", "priority", "latched") for e in events] == [("error", None, False)]
    assert not stub.transport.latched


async def test_a_request_reads_no_file(tmp_path: Path, make: Make) -> None:
    """Every read happens at construction: with the pack gone, every key scenario answers."""
    root = tmp_path / "fixtures"
    shutil.copytree(PACK_ROOT, root / "accounts")
    corpus = Path("bybit") / "2026-10-05" / "rest"
    shutil.copytree(PACK_ROOT.parent / corpus, root / corpus)
    stub = make(pack=Pack(root / "accounts"))
    shutil.rmtree(root)
    for name in KEY_SCENARIOS:
        for path in (KEY_INFO_PATH, WALLET, "/v5/market/time"):
            await stub.send(_get(name, path=path))
    assert {line["outcome"] for line in stub.lines()} == {"served"}


@pytest.mark.parametrize("default", ["working_orders_2", "rotation_ok", "no_such_scenario"])
def test_the_stack_default_must_be_a_key_scenario(make: Make, default: str) -> None:
    with pytest.raises(ValueError, match="CV_ACCOUNT_FIXTURE"):
        make(default=default)
