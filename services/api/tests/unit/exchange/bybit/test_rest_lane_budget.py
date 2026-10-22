"""A lane's wait bounds the whole signed call, retries included (G-8, #2877; 24 §8.7).

The wait is a deadline from the call's start: each attempt takes its own token within what is
left of it, an attempt's time on the network and a clock re-measure after a `10002` count against
it, and a retry whose pause (a backoff, the venue's reset time or an IP hold) would end past it is
not made, so the last attempt's own failure is raised at once; a token refused once something has
been sent raises that failure, so "nothing was sent" is said only when it is true. Without a wait
(the public clients) the retries are as before. Virtual time: the governor's clock, the client's
and the sleeper are one; no network.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx
import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.base.errors import (
    ClockDriftError,
    RateBudgetExceededError,
    RateLimitError,
    TransportError,
)
from candleviewer.exchange.bybit.config import EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.signer import BybitSigner
from tests._corpus import http_status, rest
from tests._signing import CREDENTIAL_ID, fake_capability
from tests.unit.exchange.bybit._trading import FakeClock, RecordingGovernor

BASE_URL = "https://api-demo.bybit.com"
CANCEL_BODY = {"category": "linear", "symbol": "BTCUSDT", "orderId": "e-1"}
CREATE_BODY = {"category": "linear", "symbol": "BTCUSDT", "orderLinkId": "cv-link-1"}
#: The documented rate-limit envelope with the other code, a test input.
LIMITED_10006 = {**rest("rest/error_10018.json"), "retCode": 10006}
UNAVAILABLE = rest("rest/error_503.json")
CLOCK_DRIFT = rest("rest/error_10002.json")
CANCELLED = rest("rest/trading-cancel-reply.json")


def _client(
    clock: FakeClock,
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    governor: TokenBucketGovernor | None = None,
    on_signature_failure: Callable[[], Awaitable[object]] | None = None,
) -> tuple[BybitRestClient, TokenBucketGovernor]:
    """A signed client with three retries and no jitter (each backoff is its floor: 1, 2, 4 s)."""
    gov = governor or TokenBucketGovernor(
        default_capacity=1000.0, default_refill_per_s=1000.0, clock=clock.now, sleep=clock.sleep
    )
    client = BybitRestClient(
        RestClientConfig(base_url=BASE_URL, max_retries=3),
        uid="100001",
        signer=BybitSigner(fake_capability("fixture-signer-id"), CREDENTIAL_ID),
        governor=gov,
        transport=httpx.MockTransport(handler),
        sleep=clock.sleep,
        random_fn=lambda: 0.0,
        monotonic=clock.now,
        on_signature_failure=on_signature_failure,
    )
    return client, gov


def _answers(
    sent: list[httpx.Request], clock: FakeClock, *replies: tuple[float, dict[str, object]]
) -> Callable[[httpx.Request], httpx.Response]:
    """Answers in order, each `(seconds on the network, body)`: the clock moves while out."""
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        took_s, body = queue.pop(0) if len(queue) > 1 else queue[0]
        clock.now_s += took_s
        return httpx.Response(200, json=body)

    return handler


def _unavailable(sent: list[httpx.Request]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(http_status("rest/error_503.json"), json=UNAVAILABLE)

    return handler


async def _cancel(client: BybitRestClient, wait_s: float | None) -> object:
    async with client:
        return await client.signed_request(
            "POST",
            "/v5/order/cancel",
            body=CANCEL_BODY,
            endpoint_class=EndpointClass.ORDER,
            lane="critical",
            budget_wait_s=wait_s,
        )


async def test_a_lane_wait_stops_the_backoffs_that_would_end_past_it() -> None:
    clock, sent = FakeClock(), list[httpx.Request]()
    client, _ = _client(clock, _unavailable(sent))

    with pytest.raises(TransportError, match="HTTP 503 after 3 attempts"):
        await _cancel(client, 5.0)

    assert clock.sleeps == [1.0, 2.0] and len(sent) == 3  # a third pause (4 s) would end at 7 s


async def test_a_backoff_ending_exactly_at_the_wait_is_made() -> None:
    """The wait is inclusive: the 2 s pause after the second attempt ends on a 3 s wait."""
    clock, sent = FakeClock(), list[httpx.Request]()
    client, _ = _client(clock, _unavailable(sent))

    with pytest.raises(TransportError, match="HTTP 503 after 3 attempts"):
        await _cancel(client, 3.0)

    assert clock.sleeps == [1.0, 2.0] and len(sent) == 3


async def test_a_public_call_draws_the_poll_lane_with_no_wait() -> None:
    """The public clients (catalogue, kline, server time) read in the `poll` lane, unbounded."""
    governor = RecordingGovernor()
    time_reply = rest("rest/server_time.json")
    client = BybitRestClient(
        RestClientConfig(base_url="https://api.bybit.com"),
        governor=governor,
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=time_reply)),
    )
    async with client:
        await client.get_public("/v5/market/time")
    assert governor.acquired == [("public", EndpointClass.MARKET_DATA, "poll", None)]


async def test_without_a_lane_wait_every_retry_is_made_as_before() -> None:
    clock, sent = FakeClock(), list[httpx.Request]()
    client, _ = _client(clock, _unavailable(sent))

    with pytest.raises(TransportError, match="HTTP 503 after 4 attempts"):
        await _cancel(client, None)

    assert clock.sleeps == [1.0, 2.0, 4.0] and len(sent) == 4


async def test_a_hold_set_while_the_call_was_out_stops_its_retry_at_once() -> None:
    """Another client's `10018` holds the IP for 10 s while this cancel is answered `10006`:
    its 1 s backoff fits the 5 s wait, the hold does not, so the answer comes back unslept."""
    clock = FakeClock()
    governor = TokenBucketGovernor(clock=clock.now, sleep=clock.sleep)
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        governor.hold_ip(10.0)
        return httpx.Response(200, json=LIMITED_10006)

    client, _ = _client(clock, handler, governor=governor)

    with pytest.raises(RateLimitError) as limited:
        await _cancel(client, 5.0)

    assert limited.value.exchange_ret_code == 10006
    assert (clock.sleeps, len(sent)) == ([], 1)


async def test_a_token_refused_after_only_unsent_attempts_says_nothing_was_sent() -> None:
    """A connect error proves nothing left; when the retry's token is then refused, nothing
    was sent at all, and the refusal says so."""
    clock = FakeClock()
    governor = TokenBucketGovernor(
        default_capacity=1.0, default_refill_per_s=0.1, clock=clock.now, sleep=clock.sleep
    )
    sent: list[httpx.Request] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        raise httpx.ConnectError("refused", request=request)

    client, _ = _client(clock, refuse, governor=governor)

    async with client:
        with pytest.raises(RateBudgetExceededError, match="nothing was sent"):
            await client.signed_request(
                "POST",
                "/v5/order/create",
                body=CREATE_BODY,
                endpoint_class=EndpointClass.ORDER,
                lane="critical",
                budget_wait_s=5.0,
            )

    assert len(sent) == 1 and clock.sleeps == [1.0]


async def test_a_token_refused_after_a_sent_attempt_raises_that_attempts_failure() -> None:
    clock, sent = FakeClock(), list[httpx.Request]()
    governor = TokenBucketGovernor(
        default_capacity=1.0, default_refill_per_s=0.1, clock=clock.now, sleep=clock.sleep
    )
    client, _ = _client(clock, _unavailable(sent), governor=governor)

    with pytest.raises(TransportError, match="HTTP 503 after 1 attempts"):
        await _cancel(client, 5.0)

    assert len(sent) == 1 and clock.sleeps == [1.0]  # the answer, never "nothing was sent"


async def test_a_slow_attempt_leaves_no_time_for_a_retry() -> None:
    """The deadline runs from the call's start: an answer that took 4.5 s of a 5 s wait leaves
    no room for the 1 s backoff, so the 503 is the call's answer, unslept."""
    clock, sent = FakeClock(), list[httpx.Request]()

    def slow(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        clock.now_s += 4.5
        return httpx.Response(http_status("rest/error_503.json"), json=UNAVAILABLE)

    client, _ = _client(clock, slow)

    with pytest.raises(TransportError, match="HTTP 503 after 1 attempts"):
        await _cancel(client, 5.0)

    assert (clock.sleeps, len(sent)) == ([], 1)


async def test_a_10002_answered_past_the_wait_skips_the_resync_and_is_the_answer() -> None:
    clock, sent, resyncs = FakeClock(), list[httpx.Request](), list[float]()

    async def resync() -> None:
        resyncs.append(clock.now())

    client, _ = _client(
        clock, _answers(sent, clock, (5.5, CLOCK_DRIFT)), on_signature_failure=resync
    )

    with pytest.raises(ClockDriftError):
        await _cancel(client, 5.0)

    assert (resyncs, len(sent)) == ([], 1)


async def test_a_resync_that_uses_up_the_wait_leaves_the_10002_as_the_answer() -> None:
    """The re-measure runs within what is left (24 §8.7); once it has used that up, no retry."""
    clock, sent = FakeClock(), list[httpx.Request]()

    async def resync() -> None:
        await clock.sleep(5.0)

    client, _ = _client(
        clock,
        _answers(sent, clock, (4.5, CLOCK_DRIFT), (0.0, CANCELLED)),
        on_signature_failure=resync,
    )

    with pytest.raises(ClockDriftError):
        await _cancel(client, 5.0)

    assert len(sent) == 1


async def test_a_resync_that_would_outlast_the_wait_is_cut_at_what_is_left() -> None:
    """A re-measure that never returns is cut when the lane's wait runs out (0.01 s here), not
    after its own 5 s bound; the re-signed retry then answers."""
    clock, sent, never = FakeClock(), list[httpx.Request](), asyncio.Event()

    async def hang() -> None:
        await never.wait()

    client, _ = _client(
        clock,
        _answers(sent, clock, (4.99, CLOCK_DRIFT), (0.0, CANCELLED)),
        on_signature_failure=hang,
    )

    with capture_logs() as logs:
        async with asyncio.timeout(1.0):  # a guard: the cut comes at 0.01 s, not the hook's 5 s
            reply = await _cancel(client, 5.0)

    assert reply == CANCELLED and len(sent) == 2
    assert [e["error"] for e in logs if e["event"] == "bybit_clock_resync_failed"] == [
        "TimeoutError"
    ]


async def test_a_resync_that_answers_within_the_wait_runs_to_its_end() -> None:
    """The re-measure is bounded by what is left of the wait (24 §8.7), never cut at once: one
    that yields and then answers runs to its end, and the re-signed retry answers."""
    clock, sent, measured = FakeClock(), list[httpx.Request](), list[float]()

    async def resync() -> None:
        await asyncio.sleep(0)  # yields once, as a real server-time call does
        measured.append(clock.now())

    client, _ = _client(
        clock,
        _answers(sent, clock, (0.0, CLOCK_DRIFT), (0.0, CANCELLED)),
        on_signature_failure=resync,
    )

    with capture_logs() as logs:
        reply = await _cancel(client, 5.0)

    assert reply == CANCELLED and measured == [0.0] and len(sent) == 2
    assert [e for e in logs if e["event"] == "bybit_clock_resync_failed"] == []


async def test_a_token_refused_for_the_retry_after_a_10002_raises_the_10002() -> None:
    """The 10002 was sent and answered: the refused retry token never says "nothing was sent"."""
    clock, sent = FakeClock(), list[httpx.Request]()
    governor = TokenBucketGovernor(
        default_capacity=1.0, default_refill_per_s=0.1, clock=clock.now, sleep=clock.sleep
    )

    async def resync() -> None:
        return None

    client, _ = _client(
        clock,
        _answers(sent, clock, (0.0, CLOCK_DRIFT)),
        governor=governor,
        on_signature_failure=resync,
    )

    with pytest.raises(ClockDriftError):
        await _cancel(client, 5.0)

    assert len(sent) == 1


async def test_the_retry_after_a_resync_waits_only_for_what_is_left() -> None:
    clock, sent = FakeClock(), list[httpx.Request]()
    governor = RecordingGovernor(clock=clock.now, sleep=clock.sleep)

    async def resync() -> None:
        await clock.sleep(4.0)

    client, _ = _client(
        clock,
        _answers(sent, clock, (0.0, CLOCK_DRIFT), (0.0, CANCELLED)),
        governor=governor,
        on_signature_failure=resync,
    )

    await _cancel(client, 5.0)

    assert [deadline for *_, deadline in governor.acquired] == [5.0, 1.0] and len(sent) == 2
