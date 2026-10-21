"""#1891 / SR-040a: request paths can never steer a signed request off-host. C-2.8 (#2877): a path
that moves money or edits a key's rights is refused at the same choke point, however it was
built, before a token is taken or anything is signed."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.exchange.base.errors import ExchangeError
from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient, RestPathRejected, validate_rest_path
from candleviewer.exchange.bybit.signer import BybitSigner
from tests._signing import CREDENTIAL_ID, Call, fake_capability
from tests.unit.exchange.bybit._trading import RecordingGovernor

BASE = "https://api.bybit.com"
BAD = [
    "https://api-demo.bybit.com/v5/x",
    "//evil.example/x",
    "//evil.example/v5/x",
    "https://evil.example/v5/y",
    "v5/market/time",
    "/v5/../x",
    "/v5/a//b",
    "/v5/" + chr(92) + "x",
    "/v5/a b",
    "/v5/a\n",
    "/v5/a\x00",
    "/v5/a?x=1",
    "/v5/%2e%2e/x",
    "/v5/",
    "",
]


def _client(hosts: list[str]) -> BybitRestClient:
    def handler(req: httpx.Request) -> httpx.Response:
        hosts.append(req.url.host)
        return httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}})

    signer = BybitSigner(fake_capability("DUMMYKEY" + "q" * 10), CREDENTIAL_ID)
    return BybitRestClient(
        RestClientConfig(base_url=BASE),
        signer=signer,
        governor=TokenBucketGovernor(),
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize("path", BAD)
async def test_signed_request_bad_path_rejected_before_send(path: str) -> None:
    hosts: list[str] = []
    async with _client(hosts) as c:
        with pytest.raises(RestPathRejected) as ei:
            await c.signed_request("GET", path, lane="poll")
    assert isinstance(ei.value, ExchangeError)
    assert "DUMMYKEY" not in str(ei.value) and "evil" not in str(ei.value)
    assert hosts == []


@pytest.mark.parametrize("path", BAD)
async def test_public_request_bad_path_rejected_before_send(path: str) -> None:
    hosts: list[str] = []
    async with _client(hosts) as c:
        with pytest.raises(RestPathRejected):
            await c.get_public(path)
    assert hosts == []


async def test_happy_path_unchanged() -> None:
    hosts: list[str] = []
    async with _client(hosts) as c:
        await c.get_public("/v5/market/time")
        await c.signed_request("GET", "/v5/account/wallet-balance", lane="poll")
    assert hosts == ["api.bybit.com", "api.bybit.com"]


_SEG = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-", min_size=1
)
_SAFE = st.lists(_SEG, min_size=1, max_size=4).map(lambda segs: "/v5/" + "/".join(segs))
_MUTATIONS = [
    "//",
    chr(92),
    "@",
    ":",
    "%2F",
    "%2e",
    "?",
    "#",
    " ",
    chr(10),
    chr(0),
    chr(9),
    chr(0xFF0F),
    chr(0x2215),
    "..",
    "https://evil.example",
    "//evil.example",
]


@given(_SAFE)
def test_built_safe_paths_accepted_and_target_base_host(path: str) -> None:
    assert validate_rest_path(path) == path
    built = httpx.Client(base_url=BASE).build_request("GET", path)
    assert built.url.host == "api.bybit.com"


@st.composite
def _mutated(draw: st.DrawFn) -> str:
    path = draw(_SAFE)
    kind = draw(st.sampled_from(["inject", "no_slash", "empty"]))
    if kind == "empty":
        return ""
    if kind == "no_slash":
        return path[1:]
    pos = draw(st.integers(min_value=0, max_value=len(path)))
    return path[:pos] + draw(st.sampled_from(_MUTATIONS)) + path[pos:]


@given(_mutated())
def test_mutated_paths_rejected_and_nothing_sent(path: str) -> None:
    hosts: list[str] = []

    async def run() -> None:
        async with _client(hosts) as c:
            with pytest.raises(RestPathRejected):
                await c.signed_request("GET", path, lane="poll")
            with pytest.raises(RestPathRejected):
                await c.get_public(path)

    asyncio.run(run())
    assert hosts == []


def _path(*segments: str) -> str:
    """A path built from its segments, as a caller could build one at run time. Never written
    whole here: the source scan that bans these paths finds no call site in this file."""
    return "/" + "/".join(("v5", *segments))


#: C-2.8 (#2877 ruling R14): the withdrawal and transfer families and the key-permission writes.
BANNED = [
    _path("user", "update-api"),
    _path("user", "update-sub-api"),
    _path("user", "create-sub-api"),
    _path("asset", "withdraw", "create"),
    _path("asset", "transfer", "inter-transfer"),
    _path("asset", "withdraw"),
]


@pytest.mark.parametrize("path", BANNED)
async def test_a_path_that_moves_money_or_edits_a_key_is_refused_before_any_token(
    path: str,
) -> None:
    hosts: list[str] = []
    calls: list[Call] = []
    governor = RecordingGovernor()

    def handler(req: httpx.Request) -> httpx.Response:
        hosts.append(req.url.host)
        return httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}})

    client = BybitRestClient(
        RestClientConfig(base_url=BASE),
        signer=BybitSigner(fake_capability("DUMMYKEY" + "q" * 10, calls), CREDENTIAL_ID),
        governor=governor,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        for method in ("POST", "GET"):
            with pytest.raises(RestPathRejected, match="moves money or edits a key"):
                await client.signed_request(method, path, body={}, lane="critical")
        with pytest.raises(RestPathRejected, match="moves money or edits a key"):
            await client.get_public(path)
    assert (hosts, calls, governor.acquired) == ([], [], [])


def test_the_key_verification_read_is_no_key_edit() -> None:
    """Key verification reads its key's facts (E27-T03); that read stays callable."""
    assert validate_rest_path(_path("user", "query-api")) == _path("user", "query-api")
