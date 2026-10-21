"""Shared pieces of the G-8 trading-port tests (#2877): accounts and ids, a governor that records
every acquisition, and a scripted venue behind an `httpx.MockTransport`. No network (C-13.5):
a call the test did not script fails the test at once.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
import pytest

from candleviewer.domain.primitives import AccountId, Environment, GroupId, TsUs
from candleviewer.exchange.base.models import AccountRef, PlaceOrderRequest, RateLane

# nosemgrep: cv-adapter-isolation reason=G-8-harness owner=@CandleViewer/security review=2027-03-25
from candleviewer.exchange.bybit.config import EndpointClass

# nosemgrep: cv-adapter-isolation reason=G-8-harness owner=@CandleViewer/security review=2027-03-25
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor

# nosemgrep: cv-adapter-isolation reason=G-8-harness owner=@CandleViewer/security review=2027-03-25
from candleviewer.exchange.bybit.trading import BybitTradingPort
from candleviewer.oms.order_link import OrderLinkIdParts, OrderPurpose
from tests._signing import CREDENTIAL_ID, Call, fake_capability

#: The key id the signing double answers with: long enough that the client masks it.
SIGNER_ID = "fixture-signer-id"
ACCOUNT_A = AccountId(UUID("5b1c9d2e-7f30-4a6b-8c4d-2e3f4a5b6c7d"))
ACCOUNT_B = AccountId(UUID("6c2d0e3f-8041-4b7c-9d5e-3f4a5b6c7d8e"))
GROUP = GroupId(UUID("0f8e2b6c-3d4a-4b5c-9e7f-1a2b3c4d5e6f"))
NOW_US: TsUs = 1_790_000_000_000_000
DAY_US: TsUs = 86_400_000_000


def account(
    account_id: AccountId = ACCOUNT_A,
    *,
    environment: Environment = "demo",
    uid: str = "100001",
    key_ref: str = str(CREDENTIAL_ID),
) -> AccountRef:
    return AccountRef(account_id=account_id, uid=uid, environment=environment, key_ref=key_ref)


def link(
    account_id: AccountId = ACCOUNT_A,
    *,
    environment: Environment = "demo",
    seq: int = 0,
    purpose: OrderPurpose = "entry",
) -> str:
    """An id the generator makes for `account_id` (24 §8.3)."""
    parts = OrderLinkIdParts.generate(
        mode="exchange",
        environment=environment,
        group_id=GROUP,
        account_id=account_id,
        seq=seq,
        purpose=purpose,
    )
    return parts.value


def place(ref: AccountRef | None = None, **overrides: Any) -> PlaceOrderRequest:
    """A limit entry carrying its native stop (C-2.6)."""
    ref = account() if ref is None else ref
    fields: dict[str, Any] = {
        "account": ref,
        "symbol": "BTCUSDT",
        "side": "buy",
        "order_type": "limit",
        "qty": Decimal("0.010"),
        "price": Decimal("60000"),
        "order_link_id": link(ref.account_id, environment=ref.environment),
        "stop_loss": Decimal("58000"),
    }
    return PlaceOrderRequest(**(fields | overrides))


class RecordingGovernor(TokenBucketGovernor):
    """Records each acquisition as `(uid, endpoint class, lane, deadline)`."""

    def __init__(self, **kwargs: Any) -> None:
        options: dict[str, Any] = {"default_capacity": 1000.0, "default_refill_per_s": 1000.0}
        super().__init__(**(options | kwargs))
        self.acquired: list[tuple[str, EndpointClass, RateLane, float | None]] = []

    async def acquire(
        self,
        uid: str,
        endpoint_class: EndpointClass,
        *,
        lane: RateLane,
        deadline_s: float | None = None,
    ) -> None:
        self.acquired.append((uid, endpoint_class, lane, deadline_s))
        await super().acquire(uid, endpoint_class, lane=lane, deadline_s=deadline_s)


@dataclass
class FakeClock:
    """Monotonic time that only the injected sleep advances; it records every sleep."""

    now_s: float = 0.0
    sleeps: list[float] = field(default_factory=list)

    def now(self) -> float:
        return self.now_s

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now_s += seconds


@dataclass
class Venue:
    """Answers each path with its scripted bodies in order (the last one repeats) and records
    every request. An unscripted path fails the test."""

    answers: dict[str, list[tuple[int, Any, dict[str, str]]]] = field(default_factory=dict)
    sent: list[httpx.Request] = field(default_factory=list)

    def on(
        self, path: str, *bodies: Any, status: int = 200, headers: Mapping[str, str] | None = None
    ) -> Venue:
        answers = self.answers.setdefault(path, [])
        answers.extend((status, body, dict(headers or {})) for body in bodies)
        return self

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        queue = self.answers.get(request.url.path)
        if not queue:
            pytest.fail(f"unscripted venue call: {request.method} {request.url.path}")
        status, body, headers = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(body, bytes):
            return httpx.Response(status, content=body, headers=headers)
        return httpx.Response(status, json=body, headers=headers)

    def bodies(self) -> list[dict[str, Any]]:
        """The JSON bodies the port sent: our own requests, already bounded by the client."""
        out: list[dict[str, Any]] = []
        for request in self.sent:
            # nosemgrep: cv-unbounded-read reason=own-body owner=@basiltt review=2027-03-25
            sent = request.content
            out.append(json.loads(sent) if sent else {})
        return out

    def queries(self) -> list[dict[str, str]]:
        return [dict(request.url.params) for request in self.sent]

    def payloads(self) -> list[dict[str, Any]]:
        """What each request carried: its query for a GET, its JSON body for a POST."""
        return [
            dict(request.url.params) if request.method == "GET" else body
            for request, body in zip(self.sent, self.bodies(), strict=True)
        ]

    def origins(self) -> list[tuple[str, str]]:
        """The scheme and host each request went to (C-2.11: the environment's own)."""
        return [(request.url.scheme, request.url.host) for request in self.sent]

    def paths(self) -> list[str]:
        return [request.url.path for request in self.sent]


async def _no_sleep(_seconds: float) -> None:
    return None


def make_port(
    venue: Venue,
    *,
    environment: str = "demo",
    governor: TokenBucketGovernor | None = None,
    calls: list[Call] | None = None,
    max_retries: int = 0,
    entry_wait_s: float = 0.75,
    now_us: Callable[[], TsUs] = lambda: NOW_US,
    clock: FakeClock | None = None,
) -> BybitTradingPort:
    """The port over `venue`, signed by the M2 double, on `governor` (a recording one). With
    `clock`, the port sleeps on it and measures its lanes' waits by it."""
    timing: dict[str, Any] = (
        {"sleep": _no_sleep} if clock is None else {"sleep": clock.sleep, "monotonic": clock.now}
    )
    return BybitTradingPort(
        environment=environment,
        credentials=fake_capability(SIGNER_ID, calls),
        governor=RecordingGovernor() if governor is None else governor,
        transport=httpx.MockTransport(venue.handler),
        max_retries=max_retries,
        entry_wait_s=entry_wait_s,
        now_us=now_us,
        **timing,
    )


def with_result(body: Mapping[str, Any], **result: Any) -> dict[str, Any]:
    """`body` with fields of its result replaced: a test input built on a transcribed shape,
    never a venue fact (#2877 ruling R2)."""
    return {**body, "result": {**body["result"], **result}}
