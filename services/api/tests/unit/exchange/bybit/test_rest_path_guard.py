"""#1891 / SR-040a: request paths can never steer a signed request off-host."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.exchange.base.errors import ExchangeError
from candleviewer.exchange.bybit.config import RestClientConfig
from candleviewer.exchange.bybit.rest import BybitRestClient, RestPathRejected, validate_rest_path
from candleviewer.exchange.bybit.signer import BybitSigner
from tests._signing import CREDENTIAL_ID, fake_capability

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
        RestClientConfig(base_url=BASE), signer=signer, transport=httpx.MockTransport(handler)
    )


@pytest.mark.parametrize("path", BAD)
async def test_signed_request_bad_path_rejected_before_send(path: str) -> None:
    hosts: list[str] = []
    async with _client(hosts) as c:
        with pytest.raises(RestPathRejected) as ei:
            await c.signed_request("GET", path)
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
        await c.signed_request("GET", "/v5/account/wallet-balance")
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
                await c.signed_request("GET", path)
            with pytest.raises(RestPathRejected):
                await c.get_public(path)

    asyncio.run(run())
    assert hosts == []
