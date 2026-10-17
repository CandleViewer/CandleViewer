"""The stored-key self-check's signed calls on one environment's host (E27-T03, #836).

Key info (`GET /v5/user/query-api`) and the signed no-op probe (`GET /v5/account/wallet-balance`)
for one stored key, signed by M2 under the `key_verify` purpose (C-2.7, #2339). The host is the
key's own environment's (`SIGNED_REST_BASES`, US-ACCT-007): no other host, no fallback (C-2.11).
No call is retried, as the next run is the retry; the one repeat is the client's re-sign after a
clock-drift refusal (10002, E08-S07). Each call is bounded at `CALL_TIMEOUT_S`. Both draw from the
account-reads class of the key's per-UID budget, the `poll` share (`20-architecture.md` §4.3),
never the order or position classes that hold the stop, cancel and SL reserve (C-12.7,
SR-E27-05), on a governor that caps every verification call at `VERIFY_CALLS_PER_5S`. While that
governor holds the IP (a 10018 holds every caller for 10 minutes or more, 24 §8.6) for longer
than one call's bound, a call is refused at once, never sent: waiting would only end at the bound,
so a pass under the hold costs no wait per key. Replies are parsed by `key_info`; errors leave in
the M3 taxonomy.

Clock: given the clock guard's measured offset, a request is stamped on the exchange's clock
(E08-S07 fixes the clock, never the window), so a skewed host still gets a verdict; without one a
skew past the venue's tolerance ends as 10002, no verdict. The probe's send and receive times stay
on the host clock, so the offset the pipeline derives shows the skew.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Final
from uuid import UUID

from candleviewer.exchange.base.errors import RateLimitError
from candleviewer.exchange.bybit.config import SIGNED_REST_BASES, EndpointClass, RestClientConfig
from candleviewer.exchange.bybit.key_info import (
    KEY_INFO_PATH,
    PROBE_PATH,
    ApiKeyFacts,
    ProbeFacts,
    parse_key_info,
    parse_probe,
)
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.exchange.bybit.rest import BybitRestClient
from candleviewer.exchange.bybit.signer import BybitSigner

if TYPE_CHECKING:
    import httpx

    from candleviewer.secrets import SigningCapability

#: Ticket performance notes: at most 5 s per signed call.
CALL_TIMEOUT_S: Final = 5.0
#: SR-E27-05: at most 10 verification calls per second, all UIDs together (the per-IP window).
VERIFY_CALLS_PER_5S: Final = 50
#: The `poll` share: account reads, never `EndpointClass.ORDER` or `POSITION`.
VERIFY_CLASS: Final = EndpointClass.ACCOUNT
#: The probe's query: `wallet-balance` is an account endpoint with no `category` parameter, so
#: SR-054's category rule does not apply (#836).
# nosemgrep: cv-bybit-category-required reason=no-category-param owner=@basiltt review=2027-03-25
_PROBE_PARAMS: Final = {"accountType": "UNIFIED"}


def _wall_ms() -> int:
    return int(time.time() * 1000)


def verification_governor() -> TokenBucketGovernor:
    """The one budget every verification call of the process shares."""
    return TokenBucketGovernor(ip_budget_per_5s=VERIFY_CALLS_PER_5S)


class KeyVerificationCalls:
    """The two signed calls for one stored key, on the host its client was built for, under the
    governor that client draws from."""

    def __init__(
        self,
        client: BybitRestClient,
        governor: TokenBucketGovernor,
        wall_ms: Callable[[], int] = _wall_ms,
    ) -> None:
        self._client, self._governor, self._now_ms = client, governor, wall_ms

    def _refuse_under_ip_hold(self) -> None:
        """A hold longer than one call's bound would only end at that bound: refused, never
        sent (no budget drawn, no request signed)."""
        held = self._governor.ip_hold_remaining_s()
        if held > CALL_TIMEOUT_S:
            raise RateLimitError("an IP-level hold is in force", retry_after_s=held)

    async def key_info(self) -> ApiKeyFacts:
        self._refuse_under_ip_hold()
        body = await self._client.signed_request("GET", KEY_INFO_PATH, endpoint_class=VERIFY_CLASS)
        return parse_key_info(body)

    async def probe(self) -> ProbeFacts:
        """The send and receive times bracket the whole call, its budget wait and M2's signing
        included: a slow wait reads as latency (`probe_slow`, inconclusive) and widens the
        derived offset's error by half of it."""
        self._refuse_under_ip_hold()
        sent = self._now_ms()
        body = await self._client.signed_request(
            "GET", PROBE_PATH, params=_PROBE_PARAMS, endpoint_class=VERIFY_CLASS
        )
        return parse_probe(body, sent_at_ms=sent, received_at_ms=self._now_ms())

    async def aclose(self) -> None:
        await self._client.aclose()


def key_verification_calls(
    credentials: SigningCapability,
    env: str,
    credential_id: UUID,
    *,
    uid: str,
    recv_window_ms: int,
    governor: TokenBucketGovernor,
    clock_offset_ms: Callable[[], int] | None = None,
    transport: httpx.AsyncBaseTransport | None,
) -> KeyVerificationCalls:
    """Calls for `credential_id` on `env`'s host; an unknown `env` is refused, never defaulted.
    `credentials` is the M2 signing capability that signs them. `clock_offset_ms` (exchange minus
    host) stamps each request on the exchange's clock. `transport` is the adapter's account REST
    transport (#2893 S4), with no default, so no signed client can miss it: None keeps httpx's own
    (`test_signed_client_transport.py`)."""
    base = SIGNED_REST_BASES.get(env)
    if base is None:
        raise ValueError("unknown environment")
    config = RestClientConfig(
        base_url=base,
        recv_window_ms=recv_window_ms,
        connect_timeout_s=CALL_TIMEOUT_S,
        total_timeout_s=CALL_TIMEOUT_S,
        max_retries=0,
    )
    signer = BybitSigner(credentials, credential_id, purpose="key_verify")
    client = BybitRestClient(
        config, uid=uid, signer=signer, governor=governor, clock_offset_ms_provider=clock_offset_ms,
        transport=transport,
    )  # fmt: skip
    return KeyVerificationCalls(client, governor)
