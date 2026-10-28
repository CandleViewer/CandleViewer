"""E08-T08 (#4707): the `ticker` adapter and the instrument-revision bridge in the composition root.

`create_app` serves `ticker` snapshots from the ingestion module's adapter and hands `WsRuntime` its
two feeds; the bridge re-snaps a symbol's subscriptions on each `InstrumentUpdatedEvent` of its own
environment (23 §7.4), containing a failure to that revision. No network, no sleeps.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from candleviewer.app import create_app
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import Topic
from candleviewer.domain.events import InstrumentUpdatedEvent, uuid7
from candleviewer.domain.primitives import EventId
from candleviewer.ingestion.ticker_topic import TickerTopic
from candleviewer.ws.gateway import GatewayHub
from candleviewer.ws.upstream import UpstreamRefs
from candleviewer.ws_wiring import PENDING_ADAPTERS, InstrumentRevisions, WsRuntime
from tests.unit.ws.test_app_wiring import _settings


def _revision(symbol: str) -> InstrumentUpdatedEvent:
    return InstrumentUpdatedEvent(
        event_id=EventId(uuid7(1)), ts_event=1, ts_ingest=1, source="live", symbol=symbol,
        metadata_version=2, changed_fields=("tick_size",),
    )  # fmt: skip


def _updated(env: str, symbol: str) -> Topic:
    return Topic(env=env, domain="instruments", symbol=symbol, detail="updated")


def test_create_app_serves_ticker_from_the_ingestion_adapter_and_gives_the_runtime_feeds() -> None:
    app = create_app(_settings())
    sources = app.state.ws_registry.services.snapshots._sources
    feeds = app.state.ws_runtime.feeds
    assert "ticker" not in PENDING_ADAPTERS and isinstance(sources["ticker"], TickerTopic)
    assert [type(f) for f in feeds] == [TickerTopic, InstrumentRevisions]
    assert feeds[0] is sources["ticker"]


async def test_each_revision_of_its_env_resnaps_the_symbol_and_a_failure_is_contained() -> None:
    bus, seen, done = Bus(), [], asyncio.Event()

    def revise(symbol: str) -> int:
        seen.append(symbol)
        if symbol == "ETHUSDT":
            raise RuntimeError("resnapshot broke")
        done.set()
        return 1

    revisions = InstrumentRevisions(bus, "live", revise)
    revisions.start()
    revisions.start()  # idempotent: one subscription, one task
    await bus.publish(_updated("demo", "SOLUSDT"), _revision("SOLUSDT"))  # another env's
    await bus.publish(_updated("live", "ETHUSDT"), _revision("ETHUSDT"))
    await bus.publish(_updated("live", "BTCUSDT"), object())  # no revision: ignored
    await bus.publish(_updated("live", "BTCUSDT"), _revision("BTCUSDT"))
    await asyncio.wait_for(done.wait(), timeout=5)
    await revisions.stop()
    await revisions.stop()
    await bus.publish(_updated("live", "BTCUSDT"), _revision("BTCUSDT"))  # nobody holds it now
    assert seen == ["ETHUSDT", "BTCUSDT"]


class _Feed:
    def __init__(self, log: list[str], name: str) -> None:
        self.log, self.name = log, name

    def start(self) -> None:
        self.log.append(f"start {self.name}")

    async def stop(self) -> None:
        self.log.append(f"stop {self.name}")


async def test_the_runtime_starts_its_feeds_and_stops_them_before_the_shutdown_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log: list[str] = []
    hub = GatewayHub()

    async def notice(**_: Any) -> int:
        log.append("notice")
        return 0

    monkeypatch.setattr(hub, "shutdown", notice)
    feeds = (_Feed(log, "ticker"), _Feed(log, "revisions"))
    runtime = WsRuntime(hub, UpstreamRefs(), _settings(), feeds=feeds)
    runtime.start()
    await runtime.stop()
    assert log == ["start ticker", "start revisions", "stop ticker", "stop revisions", "notice"]
