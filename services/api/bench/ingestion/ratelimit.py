"""Scenario 6: rate-limit headroom under sustained catalogue refresh + kline backfill paging.

Drives the *real* `BybitRestClient` + `TokenBucketGovernor` (per-UID, per endpoint class, plus
the IP-wide bucket) through the real adapter calls (`make_instruments_info_fetcher`,
`fetch_kline_page`) over an `httpx.MockTransport` that serves the recorded corpus and models the
exchange's IP window (600 req / 5 s): exceeding it returns the recorded `rest/error_10018.json`.
Virtual time only; headroom is read from the governor before every request. A request that would
have to wait for a token counts as "headroom reached zero" (the assertion), so the bucket's own
wait loop is never entered and the run stays deterministic.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from bench.ingestion.fixture_app import CORPUS

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.config import EndpointClass, RestClientConfig

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.instruments import make_instruments_info_fetcher

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.klines import fetch_kline_page

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor

# nosemgrep: cv-adapter-isolation reason=B5-b-harness owner=@CandleViewer/security review=2026-12-31
from candleviewer.exchange.bybit.rest import BybitRestClient

#: Allowlisted demo origin; never contacted — `MockTransport` answers every request in-process.
BASE_URL = "https://api-demo.bybit.com"
IP_WINDOW_S, IP_WINDOW_MAX = 5.0, 600


@dataclass(slots=True)
class HeadroomResult:
    requests: int = 0
    catalogue_refreshes: int = 0
    backfill_pages: int = 0
    min_uid_tokens: float = float("inf")
    min_ip_window_headroom: int = IP_WINDOW_MAX
    would_block: int = 0
    rate_limited_10018: int = 0
    ip_holds: int = 0
    tokens_trace: list[float] = field(default_factory=list)


class _Exchange:
    """Corpus-backed venue with an IP sliding window that answers 10018 when exceeded."""

    def __init__(self, world: _World, res: HeadroomResult) -> None:
        self.world, self.res = world, res
        self.sent: deque[float] = deque()
        self.instruments = _json("rest/instruments_before.json")
        self.kline = _json("rest/kline_BTCUSDT_1_page0.json")
        self.err = _json("rest/error_10018.json")

    def __call__(self, request: httpx.Request) -> httpx.Response:
        now = self.world.now
        while self.sent and self.sent[0] <= now - IP_WINDOW_S:
            self.sent.popleft()
        self.sent.append(now)
        self.res.min_ip_window_headroom = min(
            self.res.min_ip_window_headroom, IP_WINDOW_MAX - len(self.sent)
        )
        if len(self.sent) > IP_WINDOW_MAX:
            self.res.rate_limited_10018 += 1
            return httpx.Response(200, json=self.err)
        body = self.instruments if "instruments-info" in request.url.path else self.kline
        return httpx.Response(200, json=body)


class _World:
    def __init__(self) -> None:
        self.now = 0.0

    async def sleep(self, seconds: float) -> None:
        self.now += seconds

    def wall(self) -> float:
        return 1_700_000_000.0 + self.now


def _json(rel: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((Path(CORPUS) / rel).read_text(encoding="utf-8"))
    return data


async def run_headroom(
    *,
    duration_s: float,
    refresh_every_s: float,
    backfill_pages_per_s: float,
    symbols: int,
    bucket_capacity: float,
    bucket_refill_per_s: float,
    tick_s: float = 1.0,
) -> HeadroomResult:
    world, res = _World(), HeadroomResult()
    gov = TokenBucketGovernor(
        default_capacity=bucket_capacity,
        default_refill_per_s=bucket_refill_per_s,
        ip_budget_per_5s=IP_WINDOW_MAX,
        clock=lambda: world.now,
        sleep=world.sleep,
    )
    client = BybitRestClient(
        RestClientConfig(base_url=BASE_URL, max_retries=0),
        uid="bench-public",
        governor=gov,
        transport=httpx.MockTransport(_Exchange(world, res)),
        sleep=world.sleep,
        random_fn=lambda: 0.0,
        wall_clock=world.wall,
    )
    fetch_catalogue = make_instruments_info_fetcher(client)
    carry, next_refresh = 0.0, 0.0

    async def guarded(call: str) -> None:
        tokens = gov.remaining("bench-public", EndpointClass.MARKET_DATA)
        res.tokens_trace.append(tokens)
        res.min_uid_tokens = min(res.min_uid_tokens, tokens - 1.0)  # headroom after this call
        if tokens < 1.0:
            res.would_block += 1  # the bucket would have to wait: headroom reached zero
            return
        res.requests += 1
        if call == "catalogue":
            await fetch_catalogue(lambda: int(world.wall() * 1e6))
            res.catalogue_refreshes += 1
        else:
            await fetch_kline_page(
                client,
                "BTCUSDT",
                "1",
                start_us=1_699_900_000_000_000,
                end_us=1_700_026_920_000_000,
                limit=200,
            )
            res.backfill_pages += 1

    try:
        for i in range(int(duration_s / tick_s)):
            world.now = i * tick_s
            if world.now >= next_refresh:
                await guarded("catalogue")
                next_refresh += refresh_every_s
            carry += backfill_pages_per_s * tick_s * symbols
            while carry >= 1.0:
                carry -= 1.0
                await guarded("backfill")
        res.ip_holds = 1 if gov.ip_hold_remaining_s() > 0 else 0
    finally:
        await client.aclose()
    if res.min_uid_tokens == float("inf"):
        res.min_uid_tokens = bucket_capacity
    return res
