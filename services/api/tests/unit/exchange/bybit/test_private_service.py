"""The adapter's private streams as its service builds them (G-8b, #3963; 24 §14.2 rule 13).

Every trading port of the adapter opens streams from its one registry, so one stream per account
and the cap hold across ports; the streams dial with the connector the composition root injects
(the dev-only account fixture's, #2893) or production's; they draw on the adapter's one
connection budget; and `stop()` ends each with `closed(shutdown)` before it returns. Nothing
here waits on a clock: each read is guarded by a bound only.
"""

from __future__ import annotations

import asyncio

import pytest

from candleviewer.exchange.base.models import PrivateStreamStatus
from candleviewer.exchange.base.ports import PrivateStream
from candleviewer.exchange.bybit import key_ws_probe
from candleviewer.exchange.bybit.config import PRIVATE_WS_URLS
from candleviewer.exchange.bybit.service import ExchangeBybitService
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
