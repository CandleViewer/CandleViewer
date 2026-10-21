"""#1891 / SR-040a: request paths can never steer a signed request off-host. C-2.8 (#2877): a path
that moves money or edits a key's rights is refused at the same choke point, however it was
built, before a token is taken or anything is signed."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import httpx
import pytest
import yaml
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


#: Every v5 path is lower case, and the guard admits nothing else (#2877).
_SEG = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1)
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
    "A",  # any upper-case letter: no v5 path has one (#2877)
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


#: C-2.8 (#2877 ruling R14): the withdrawal and transfer families and the key-permission writes,
#: each with every path under it.
BANNED = [
    _path("user", "update-api"),
    _path("user", "update-sub-api"),
    _path("user", "create-sub-api"),
    _path("user", "update-api", "x"),
    _path("user", "update-sub-api", "x"),
    _path("user", "create-sub-api", "x"),
    _path("asset", "withdraw", "create"),
    _path("asset", "transfer", "inter-transfer"),
    _path("asset", "withdraw"),
    _path("asset", "transfer"),
]
#: The bare asset roots: refused at run time only, as no v5 call is one (`rest.py` says so).
BARE_ROOTS = [_path("asset", "withdraw"), _path("asset", "transfer")]


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


#: Case variants of a banned, a create and a category-taking path: never another path's twin.
CASE_VARIANTS = [
    _path("User", "update-api"),
    _path("user", "Update-Api"),
    _path("ASSET", "withdraw", "create"),
    _path("asset", "Withdraw", "create"),
    _path("asset", "TRANSFER", "inter-transfer"),
    _path("order", "Create"),
    _path("Order", "cancel"),
]


@pytest.mark.parametrize("path", CASE_VARIANTS)
async def test_a_case_variant_of_a_v5_path_is_refused_before_any_token(path: str) -> None:
    """Every v5 path is lower case: a variant is refused, never read as a path the C-2.8 list,
    the create guard (C-2.10) or the category check (SR-054) does not know (#2877)."""
    hosts: list[str] = []
    governor = RecordingGovernor()

    def handler(req: httpx.Request) -> httpx.Response:
        hosts.append(req.url.host)
        return httpx.Response(200, json={"retCode": 0, "retMsg": "OK", "result": {}})

    client = BybitRestClient(
        RestClientConfig(base_url=BASE),
        signer=BybitSigner(fake_capability("DUMMYKEY" + "q" * 10), CREDENTIAL_ID),
        governor=governor,
        transport=httpx.MockTransport(handler),
    )
    async with client:
        for method in ("POST", "GET"):
            with pytest.raises(RestPathRejected, match="SR-040a"):
                await client.signed_request(method, path, body={}, lane="critical")
    assert (hosts, governor.acquired) == ([], [])


_RULE = Path(__file__).resolve().parents[6] / ".semgrep" / "cv-withdrawal-endpoint-ban.yml"


def _rule_regexes() -> list[re.Pattern[str]]:
    """The `pattern-regex` entries of `cv-withdrawal-endpoint-ban`, the source half of C-2.8."""
    (rule,) = yaml.safe_load(_RULE.read_text(encoding="utf-8"))["rules"]
    assert rule["id"] == _RULE.stem
    either = [entry for block in rule["patterns"] for entry in block.get("pattern-either", [])]
    regexes = [re.compile(entry["pattern-regex"]) for entry in either if "pattern-regex" in entry]
    assert regexes, "cv-withdrawal-endpoint-ban no longer declares a pattern-regex"
    return regexes


@pytest.mark.parametrize("path", [p for p in BANNED if p not in BARE_ROOTS])
@pytest.mark.parametrize("quote", ['"', "'"])
def test_the_source_rule_flags_every_path_the_run_time_list_refuses(path: str, quote: str) -> None:
    """R14 lives in two lists, the Semgrep rule and `rest.py`'s: a path one refuses, written as a
    literal, the other flags, so neither can drift alone. Only the bare roots are run time's."""
    literal = quote + path + quote
    assert any(regex.search(literal) for regex in _rule_regexes()), literal


@pytest.mark.parametrize(
    "path", [_path("user", "query-api"), _path("user", "update-api-key")], ids=["read", "longer"]
)
def test_the_source_rule_leaves_a_read_and_a_longer_name_alone(path: str) -> None:
    literal = '"' + path + '"'
    assert not any(regex.search(literal) for regex in _rule_regexes())
