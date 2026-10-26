"""The adapter's private streams as its service builds them (G-8b, #3963; 24 §14.2 rule 13).

Every trading port of the adapter opens streams from its one registry, so one stream per account
and the cap hold across ports; the streams dial with the connector the composition root injects
(the dev-only account fixture's, #2893) or production's; they draw on the adapter's one
connection budget; and `stop()` ends each with `closed(shutdown)` before it returns. #913 L1d-2a:
`open_private_stream` opens from that one registry, signed by the adapter's own capability, and
the order lane's port opens through the stream source it is given, after its own environment
check. Nothing here waits on a clock: each read is guarded by a bound only.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

import pytest

from candleviewer.exchange.base.models import AccountRef, PrivateStreamStatus
from candleviewer.exchange.base.ports import PrivateStream
from candleviewer.exchange.bybit import key_ws_probe
from candleviewer.exchange.bybit import private_stream as ps
from candleviewer.exchange.bybit.config import PRIVATE_WS_URLS
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.secrets import CredentialBorrower, Purpose, RequestSignature
from candleviewer.secrets.signing import SigningMessage
from candleviewer.statechart import build
from tests._signing import Call, fake_capability
from tests.chaos.ingestion._clock import VirtualClock
from tests.unit.exchange.bybit._private_venue import PrivateVenue
from tests.unit.exchange.bybit._trading import ACCOUNT_B, SIGNER_ID, account


def _adapter(venue: PrivateVenue, calls: list[Call] | None = None) -> ExchangeBybitService:
    return ExchangeBybitService(
        fake_capability(SIGNER_ID, calls), private_ws_connect=venue.connect, environment="demo"
    )


async def _statuses(stream: PrivateStream, count: int) -> list[str]:
    seen: list[str] = []
    async with asyncio.timeout(5):  # a guard only: the chart reaches `live` with no clock
        while len(seen) < count:
            item = await stream.__anext__()
            if isinstance(item, PrivateStreamStatus):
                seen.append(f"{item.state}:{item.reason}")
    return seen


async def test_every_port_of_the_adapter_shares_its_one_registry() -> None:
    venue = PrivateVenue(VirtualClock())
    adapter = _adapter(venue)
    first, second = adapter.trading_port("demo"), adapter.trading_port("demo")
    stream = await first.subscribe_private(account())
    with pytest.raises(ValueError, match="already has a private stream"):
        await second.subscribe_private(account())
    other = await second.subscribe_private(account(ACCOUNT_B))
    for opened in (stream, other):
        await opened.aclose()
    await adapter.stop(5.0)


async def test_the_streams_dial_with_the_injected_connector_and_count_in_the_budget() -> None:
    venue, calls = PrivateVenue(VirtualClock()), list[Call]()
    adapter = _adapter(venue, calls)
    before = adapter.ws_connection_budget.remaining("private")
    stream = await adapter.trading_port("demo").subscribe_private(account())
    assert await _statuses(stream, 2) == ["heartbeat:evidence", "resyncing:connected"]
    assert venue.dialled == [PRIVATE_WS_URLS["demo"]]
    assert [c[2] for c in calls] == ["sign_ws_auth"]
    assert adapter.ws_connection_budget.remaining("private") == before - 1
    await stream.aclose()
    await adapter.stop(5.0)


async def test_stop_ends_every_stream_with_closed_shutdown_and_closes_its_socket() -> None:
    venue = PrivateVenue(VirtualClock())
    adapter = _adapter(venue)
    stream = await adapter.trading_port("demo").subscribe_private(account())
    await _statuses(stream, 2)
    await adapter.stop(5.0)
    assert await _statuses(stream, 1) == ["closed:shutdown"]
    assert venue.sockets[0].closed
    with pytest.raises(RuntimeError, match="shut down"):
        await adapter.trading_port("demo").subscribe_private(account(ACCOUNT_B))


def test_production_dials_the_stream_with_the_streams_own_connector() -> None:
    """Without an injected connector the streams take `connect_private_stream` (1 MiB frames),
    never the probe's 4 KiB one."""
    adapter = ExchangeBybitService(fake_capability(), environment="live")
    assert adapter._stream_connect is key_ws_probe.connect_private_stream


def _on_thread(calls: list[Call], threads: list[int]) -> CredentialBorrower:
    """The M2 double, also recording the thread each signature is asked on."""
    inner = fake_capability(SIGNER_ID, calls)

    async def sign(key_id: UUID, message: SigningMessage, purpose: Purpose) -> RequestSignature:
        threads.append(threading.get_ident())
        return await inner.sign(key_id, message, purpose=purpose)

    return CredentialBorrower(sign)


async def test_open_private_stream_opens_from_the_one_registry_signed_by_the_adapters_borrower(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#913 L1d-2a (24 §14.1): the registry is built on first use with the adapter's own
    capability, never the order lane's borrower, even with a lane port built first; each dial's
    `auth` is signed on the calling thread under `sign_ws_auth`, B13 is built on lane `platform`,
    and the trading port shares the same registry (one stream per account, SR-E29-02)."""
    venue, calls, lane_calls = PrivateVenue(VirtualClock()), list[Call](), list[Call]()
    threads = list[int]()
    adapter = ExchangeBybitService(
        _on_thread(calls, threads), private_ws_connect=venue.connect, environment="demo"
    )
    lanes: list[str] = []

    async def spied(machine_key: str, **kwargs: Any) -> Any:
        lanes.append(f"{machine_key}:{kwargs['lane']}")
        return await build(machine_key, **kwargs)

    monkeypatch.setattr(ps, "build", spied)
    adapter.lane_trading_port("demo", credentials=fake_capability(SIGNER_ID, lane_calls))
    stream = await adapter.open_private_stream(account())
    assert await _statuses(stream, 2) == ["heartbeat:evidence", "resyncing:connected"]
    assert ([c[2] for c in calls], lane_calls) == (["sign_ws_auth"], [])
    assert threads == [threading.get_ident()] and lanes == ["ws_conn:platform"]
    with pytest.raises(ValueError, match="already has a private stream"):
        await adapter.trading_port("demo").subscribe_private(account())
    await stream.aclose()
    await adapter.stop(5.0)


@pytest.mark.parametrize(
    ("capability", "opened", "refusal"),
    [
        (None, account(), "no signing capability is wired"),
        (fake_capability(SIGNER_ID), account(environment="live"), "another environment"),
    ],
    ids=["no-capability", "another-environment"],
)
async def test_open_private_stream_refuses_before_anything_is_dialled(
    capability: CredentialBorrower | None, opened: AccountRef, refusal: str
) -> None:
    venue = PrivateVenue(VirtualClock())
    adapter = ExchangeBybitService(capability, private_ws_connect=venue.connect, environment="demo")
    with pytest.raises((RuntimeError, ValueError), match=refusal):
        await adapter.open_private_stream(opened)
    assert venue.dialled == []


class _Opener:
    """A stream source as the order lane's composition root gives one (#913 L1d-2b's bridge)."""

    def __init__(self, stream: PrivateStream) -> None:
        self.stream = stream
        self.opened: list[tuple[AccountRef, Callable[[], int | None] | None]] = []

    async def open(
        self, account: AccountRef, *, clock_offset_ms: Callable[[], int | None] | None = None
    ) -> PrivateStream:
        self.opened.append((account, clock_offset_ms))
        return self.stream


async def test_the_lane_port_opens_through_its_opener_after_its_own_environment_check() -> None:
    """#913 L1d-2a: the lane port's `subscribe_private` refuses another environment's account
    first, with nothing reaching its opener (C-2.11), then opens through the opener with the
    port's own offset reader; a lane port given none refuses every account, as before."""
    adapter = ExchangeBybitService(fake_capability(SIGNER_ID), environment="demo")
    stream = cast("PrivateStream", object())  # compared by identity only

    def offset() -> int | None:
        return None

    opener = _Opener(stream)
    port = adapter.lane_trading_port(
        "demo", credentials=fake_capability("lane"), clock_offset_ms=offset, private_streams=opener
    )
    with pytest.raises(ValueError, match="another environment"):
        await port.subscribe_private(account(environment="live"))
    assert opener.opened == []
    assert await port.subscribe_private(account()) is stream
    assert opener.opened == [(account(), offset)]
    bare = adapter.lane_trading_port("demo", credentials=fake_capability("lane"))
    with pytest.raises(RuntimeError, match="no private stream is wired"):
        await bare.subscribe_private(account())
