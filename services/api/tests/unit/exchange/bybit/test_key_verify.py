"""E27-T03 (#836): the stored-key self-check's signed calls, one environment's host each.

Replies: the documented-shape `tests/fixtures/key_verification/` (README there) and the corpus's
10002/10018 replies. `respx` answers for every host, so a wrong host is recorded. No network.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
import respx

from candleviewer.exchange.base.errors import (
    AuthError,
    ClockDriftError,
    RateLimitError,
    TransportError,
)
from candleviewer.exchange.bybit.config import SIGNED_REST_BASES, EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.key_info import (
    KEY_INFO_PATH,
    PROBE_PATH,
    ProbeFacts,
    probe_error,
)
from candleviewer.exchange.bybit.key_verify import (
    CALL_TIMEOUT_S,
    KeyVerificationCalls,
    key_verification_calls,
)
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.exchange.bybit.signer import BybitSigner
from candleviewer.settings import Environment
from tests._corpus import rest
from tests._signing import CREDENTIAL_ID, Call, fake_capability

FIXTURES = Path(__file__).parents[3] / "fixtures" / "key_verification"
HOSTS = {"live": "api.bybit.com", "demo": "api-demo.bybit.com", "testnet": "api-testnet.bybit.com"}
UID, OTHER_KEY = "1000001", UUID(int=2)


def load(name: str) -> dict[str, Any]:
    body: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return body


class Governor(TokenBucketGovernor):
    """Records each draw: `(uid, endpoint class)`."""

    def __init__(self) -> None:
        super().__init__(default_capacity=1000.0, default_refill_per_s=1000.0)
        self.drawn: list[tuple[str, EndpointClass]] = []

    async def acquire(self, uid: str, endpoint_class: EndpointClass) -> None:
        self.drawn.append((uid, endpoint_class))
        await super().acquire(uid, endpoint_class)


@pytest.fixture
def venue() -> Iterator[respx.MockRouter]:
    """Every environment's host answers both calls; tests read which host was asked."""
    with respx.mock(assert_all_called=False) as router:
        for host in HOSTS.values():
            router.get(f"https://{host}{KEY_INFO_PATH}").respond(json=load("key_info_trade.json"))
            router.get(f"https://{host}{PROBE_PATH}").respond(json=load("wallet_balance.json"))
        yield router


def asked(router: respx.MockRouter) -> list[tuple[str, str]]:
    return [(call.request.url.host, call.request.url.path) for call in router.calls]


def build(
    env: str, signed: list[Call] | None = None, offset: Callable[[], int] | None = None
) -> tuple[KeyVerificationCalls, Governor]:
    governor = Governor()
    calls = key_verification_calls(
        fake_capability("test-key", signed), env, CREDENTIAL_ID, uid=UID, recv_window_ms=5000,
        governor=governor, clock_offset_ms=offset,
    )  # fmt: skip
    return calls, governor


async def both(calls: KeyVerificationCalls) -> str:
    uid = (await calls.key_info()).uid
    await calls.probe()
    await calls.aclose()
    return uid


@pytest.mark.parametrize("env", sorted(HOSTS))
async def test_each_environment_signs_on_its_own_host_only(
    venue: respx.MockRouter, env: str
) -> None:
    assert await both(build(env)[0]) == UID
    assert asked(venue) == [(HOSTS[env], KEY_INFO_PATH), (HOSTS[env], PROBE_PATH)]
    assert SIGNED_REST_BASES[env] == f"https://{HOSTS[env]}"


@pytest.mark.parametrize(
    "failure",
    [httpx.Response(503, json={}), httpx.ConnectError("unreachable")],
    ids=["5xx", "unreachable"],
)
async def test_a_failing_demo_host_never_falls_back_to_another_host(
    venue: respx.MockRouter, failure: httpx.Response | Exception
) -> None:
    venue.get(f"https://{HOSTS['demo']}{KEY_INFO_PATH}").mock(side_effect=[failure])
    calls, _ = build("demo")
    with pytest.raises(TransportError):
        await calls.key_info()
    await calls.aclose()
    assert asked(venue) == [(HOSTS["demo"], KEY_INFO_PATH)]  # once, and no other host


@pytest.mark.parametrize(
    ("failure", "name"),
    [
        (httpx.Response(503, json={}), "service_unavailable"),
        (httpx.Response(502, text="bad gateway"), "service_unavailable"),
        (httpx.ConnectError("unreachable"), "transport_error"),
        (httpx.ReadTimeout("slow"), "timeout"),
        (httpx.Response(200, text="<html>not json</html>"), "transport_error"),
        # Pinned gaps (#3281): the contract names a 403 `ip_not_allowed` and a 429
        # `rate_limited`, but the client exposes no HTTP status, so with no JSON body they read as
        # a transport fault. The day it does, these two cases fail and take their contract names.
        (httpx.Response(403, text="<html>forbidden</html>"), "transport_error"),
        (httpx.Response(429, text="slow down"), "transport_error"),
    ],
    ids=["503", "502_html", "reset", "slow", "non_json_200", "403_gap", "429_gap"],
)
async def test_a_failing_call_is_named_by_the_probe_table_from_the_real_clients_error(
    venue: respx.MockRouter, failure: httpx.Response | Exception, name: str
) -> None:
    """The table reads the REST client's own errors: a 5xx is its cause-less `TransportError`, a
    reset, a timeout or a body that is not JSON chains its own error. A change to how the client
    raises them fails here, not in production."""
    venue.get(f"https://{HOSTS['demo']}{KEY_INFO_PATH}").mock(side_effect=[failure])
    calls, _ = build("demo")
    with pytest.raises(TransportError) as caught:
        await calls.key_info()
    await calls.aclose()
    assert probe_error(caught.value) == name


async def test_both_calls_are_signed_by_m2_under_key_verify_for_the_stored_key(
    venue: respx.MockRouter,
) -> None:
    signed: list[Call] = []
    await both(build("live", signed)[0])
    assert [(key, purpose) for key, _, purpose in signed] == [(CREDENTIAL_ID, "key_verify")] * 2
    sent = venue.calls.last.request
    assert (sent.headers["X-BAPI-API-KEY"], sent.headers["X-BAPI-RECV-WINDOW"]) == (
        "test-key", "5000",
    )  # fmt: skip
    assert sent.url.params["accountType"] == "UNIFIED"


async def test_both_calls_draw_the_account_reads_class_never_the_order_or_position_reserve(
    venue: respx.MockRouter,
) -> None:
    calls, governor = build("demo")
    await both(calls)
    assert governor.drawn == [(UID, EndpointClass.ACCOUNT)] * 2


@pytest.mark.parametrize(
    ("reply", "error", "sent"),
    [
        (rest("rest/error_10018.json"), RateLimitError, 1),
        (load("error_10004.json"), AuthError, 1),
        (rest("rest/error_10002.json"), ClockDriftError, 2),  # the client's one re-sign (E08-S07)
    ],
    ids=["10018", "10004", "10002"],
)
async def test_no_refused_call_is_retried(
    venue: respx.MockRouter, reply: dict[str, Any], error: type[Exception], sent: int
) -> None:
    venue.get(f"https://{HOSTS['demo']}{PROBE_PATH}").respond(json=reply)
    calls, _ = build("demo")
    with pytest.raises(error):
        await calls.probe()
    await calls.aclose()
    assert asked(venue) == [(HOSTS["demo"], PROBE_PATH)] * sent


async def test_the_probe_reports_the_exchange_clock_and_the_local_send_and_receive_times(
    venue: respx.MockRouter,
) -> None:
    config = RestClientConfig(base_url=SIGNED_REST_BASES["demo"], max_retries=0)
    signer = BybitSigner(fake_capability(), CREDENTIAL_ID, purpose="key_verify")
    governor = Governor()
    client = BybitRestClient(config, uid=UID, signer=signer, governor=governor)
    ticks = iter([100, 160])
    calls = KeyVerificationCalls(client, governor, wall_ms=lambda: next(ticks))
    seen = await calls.probe()
    await calls.aclose()
    assert seen == ProbeFacts(load("wallet_balance.json")["time"], 100, 160)


def test_an_unknown_environment_is_refused_never_defaulted() -> None:
    with pytest.raises(ValueError, match="unknown environment"):
        build("mainnet")


def test_every_process_environment_has_exactly_one_signed_host() -> None:
    assert set(SIGNED_REST_BASES) == {env.value for env in Environment}


async def test_a_measured_offset_stamps_requests_on_the_exchange_clock_not_the_probe_times(
    venue: respx.MockRouter,
) -> None:
    calls, _ = build("demo", offset=lambda: -12_000)  # the host clock runs 12 s ahead
    before = int(time.time() * 1000)
    seen = await calls.probe()
    after = int(time.time() * 1000)
    await calls.aclose()
    stamp = int(venue.calls.last.request.headers["X-BAPI-TIMESTAMP"])
    assert before - 12_000 <= stamp <= after - 12_000
    assert before <= seen.sent_at_ms <= seen.received_at_ms <= after  # the host clock


def test_each_call_is_bounded_at_five_seconds_and_never_retried_by_the_client() -> None:
    config = build("demo")[0]._client._config
    assert (config.connect_timeout_s, config.total_timeout_s, config.max_retries) == (5.0, 5.0, 0)


@pytest.mark.parametrize("call", ["key_info", "probe"])
async def test_a_call_under_an_ip_hold_longer_than_its_bound_is_refused_at_once_never_sent(
    venue: respx.MockRouter, call: str
) -> None:
    signed: list[Call] = []
    calls, governor = build("demo", signed)
    governor.hold_ip(600.0)  # what a 10018 sets: every caller waits 10 minutes
    with pytest.raises(RateLimitError) as refused:
        await asyncio.wait_for(getattr(calls, call)(), timeout=1.0)  # a wait fails fast
    await calls.aclose()
    assert (asked(venue), governor.drawn, signed) == ([], [], [])
    assert refused.value.retry_after_s == pytest.approx(600.0, abs=1.0)


async def test_a_hold_within_one_calls_bound_is_waited_out_and_the_call_is_sent(
    venue: respx.MockRouter,
) -> None:
    now = [0.0]

    async def wait(delay: float) -> None:  # the governor's sleep on a fake clock
        now[0] += delay

    governor = TokenBucketGovernor(
        default_capacity=10.0, default_refill_per_s=10.0, clock=lambda: now[0], sleep=wait
    )
    calls = key_verification_calls(
        fake_capability("test-key"), "demo", CREDENTIAL_ID, uid=UID, recv_window_ms=5000,
        governor=governor,
    )  # fmt: skip
    governor.hold_ip(CALL_TIMEOUT_S)
    assert (await calls.key_info()).uid == UID
    await calls.aclose()
    assert (asked(venue), now) == ([(HOSTS["demo"], KEY_INFO_PATH)], [CALL_TIMEOUT_S])


async def test_the_service_builds_every_verification_client_on_one_capped_governor(
    venue: respx.MockRouter,
) -> None:
    svc = ExchangeBybitService(credentials=fake_capability())
    first = svc.key_verification_calls("testnet", CREDENTIAL_ID, uid=UID, recv_window_ms=5000)
    second = svc.key_verification_calls("testnet", OTHER_KEY, uid="7", recv_window_ms=5000)
    await first.key_info()
    for calls in (first, second):
        await calls.aclose()
    governor = first._client._governor  # SR-E27-05: 10 calls per second, all UIDs together
    assert governor is second._client._governor and governor._ip_bucket.capacity == 50.0
    assert asked(venue) == [(HOSTS["testnet"], KEY_INFO_PATH)]
    with pytest.raises(RuntimeError, match="no signing capability"):
        ExchangeBybitService().key_verification_calls("demo", OTHER_KEY, uid=UID, recv_window_ms=1)
