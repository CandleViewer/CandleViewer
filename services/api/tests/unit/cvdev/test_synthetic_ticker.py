"""E29-Q03 (#977): the dev fixture stack's synthetic ticker. Attached only with the fixture on,
`CV_FEED=synthetic` and no public WS; it prices nothing until the boot guard arms the door, then
the reference prices read the synthetic mid. Every log line says `synthetic`; no socket opens."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.account_fixture_wiring import (
    AccountFixtureRefused,
    account_fixture_guard,
    attach_fixture_tickers,
    build_account_fixture,
)
from candleviewer.exchange.base import Ticker, Trade, TradeSide
from candleviewer.ingestion.service import PUMP_YIELD_EVERY, IngestionService
from candleviewer.net.read_only_gate import ReadOnlyGate
from candleviewer.oms_wiring import ReferencePricesBinding
from candleviewer.settings import Environment, FeedMode, Settings
from cvdev.account_fixture import synthetic_ticker as st
from cvdev.account_fixture import wiring
from tests.unit.cvdev.test_fixture_wiring import _dev, _one_process, state  # noqa: F401  fixtures

TS = datetime(2026, 1, 1, tzinfo=UTC)


def _tick(symbol: str = "BTCUSDT", bid: str = "100.0", ask: str = "100.2") -> Ticker:
    return Ticker(
        symbol=symbol,
        last_price=Decimal("100.1"),
        bid_price=Decimal(bid),
        ask_price=Decimal(ask),
        ts=TS,
    )


class _Door:
    """A door whose armed state a test sets by hand."""

    def __init__(self, armed: object | None = None) -> None:
        self.armed = armed


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _refuse_sockets(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """From here on any socket opened fails the test; called inside the test body, once the
    loop (whose self-pipe is a socket pair) exists."""
    opened: list[Any] = []

    def _refuse(*args: Any, **kwargs: Any) -> Any:
        opened.append(args)
        raise AssertionError("the synthetic ticker opened a socket")

    monkeypatch.setattr(socket, "socket", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    return opened


def _attached(settings: Settings) -> tuple[wiring.FixtureDoor, IngestionService]:
    door = build_account_fixture(settings)
    assert isinstance(door, wiring.FixtureDoor)
    ingestion = IngestionService()
    attach_fixture_tickers(settings, door, ingestion)
    return door, ingestion


def _stream(ingestion: IngestionService) -> st.SyntheticTickerStream:
    stream = ingestion.tickers
    assert isinstance(stream, st.SyntheticTickerStream)
    return stream


async def _armed(settings: Settings, door: wiring.FixtureDoor) -> None:
    assert await account_fixture_guard(settings, door, ReadOnlyGate()) is not None
    assert door.armed is not None


@pytest.fixture
def close_pairs() -> Iterator[list[wiring.FixtureDoor]]:
    doors: list[wiring.FixtureDoor] = []
    yield doors
    for door in doors:
        if door.armed is not None:
            door.armed.transport.log.close()


def test_without_the_fixture_no_ticker_is_attached() -> None:
    ingestion = IngestionService()
    attach_fixture_tickers(Settings(feed=FeedMode.SYNTHETIC), None, ingestion)
    assert ingestion.tickers is None


def test_with_the_public_ws_no_synthetic_ticker_is_attached(state: Path) -> None:  # noqa: F811
    settings = _dev(state).model_copy(update={"ingestion_ws_enabled": True})
    _, ingestion = _attached(settings)
    assert ingestion.tickers is None


def test_the_dev_side_refuses_a_live_feed_a_foreign_handle_or_a_second_stream(
    state: Path,  # noqa: F811
) -> None:
    settings = _dev(state)
    door, ingestion = _attached(settings)
    with pytest.raises(AccountFixtureRefused, match="never replaces"):
        st.attach(settings, door, ingestion)
    with pytest.raises(AccountFixtureRefused, match="needs this package's door"):
        wiring.attach_tickers(settings, object(), IngestionService())  # type: ignore[arg-type]  # a foreign handle
    ws_on = settings.model_copy(update={"ingestion_ws_enabled": True})
    with pytest.raises(AccountFixtureRefused, match="no public WS"):
        st.attach(ws_on, door, IngestionService())
    live = settings.model_copy(update={"feed": FeedMode.LIVE})
    with pytest.raises(AccountFixtureRefused):
        st.attach(live, door, IngestionService())


@pytest.mark.parametrize(
    ("environment", "key_variable", "match"),
    [
        (Environment.LIVE, None, "unless CV_ENVIRONMENT=demo"),
        (Environment.TESTNET, None, "unless CV_ENVIRONMENT=demo"),
        (Environment.DEMO, "CV_BYBIT_API_KEY", "any CV_BYBIT_API_\\* variable is set"),
    ],
)
def test_the_dev_side_re_checks_the_fixture_refusal(
    state: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    environment: Environment,
    key_variable: str | None,
    match: str,
) -> None:
    """The settings were valid at load; the dev side reads the refusal again at attach, before
    the feed and the stream checks, which these settings would all pass."""
    settings = _dev(state)
    door = build_account_fixture(settings)
    assert isinstance(door, wiring.FixtureDoor)
    if key_variable is not None:
        monkeypatch.setenv(key_variable, "placeholder-name-only")
    changed = settings.model_copy(update={"environment": environment})
    ingestion = IngestionService()
    with pytest.raises(AccountFixtureRefused, match=match):
        st.attach(changed, door, ingestion)
    assert ingestion.tickers is None


async def test_unarmed_it_prices_nothing_and_stays_idle(
    state: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = _refuse_sockets(monkeypatch)
    door, ingestion = _attached(_dev(state))
    stream = _stream(ingestion)
    ingestion.queue = asyncio.Queue(maxsize=4)

    with capture_logs() as logs:
        await stream.start()
        stream.offer(_tick())
        await stream.stop()

    assert stream.latest("BTCUSDT") is None
    assert stream.phase("BTCUSDT") is None and not stream.is_listed("BTCUSDT")  # offer's check
    assert await ReferencePricesBinding(stream).reference_price("BTCUSDT") is None
    idle = [e for e in logs if e["event"] == "ingestion.synthetic_ticker_idle"]
    assert [(e["source"], e["reason"]) for e in idle] == [("synthetic", "fixture_not_armed")]
    assert opened == [] and door.armed is None


async def test_armed_the_reference_price_is_the_synthetic_mid(
    state: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    close_pairs: list[wiring.FixtureDoor],
) -> None:
    settings = _dev(state)
    with capture_logs() as logs:
        door, ingestion = _attached(settings)
        close_pairs.append(door)
        await _armed(settings, door)
        opened = _refuse_sockets(monkeypatch)  # armed: from here the stream runs
        stream = _stream(ingestion)
        queue: st.FeedQueue = asyncio.Queue(maxsize=8)
        ingestion.queue = queue
        await stream.start()
        trade = Trade(
            symbol="BTCUSDT", price=Decimal("1"), size=Decimal("1"), side=TradeSide.BUY, ts=TS
        )
        for record in (trade, _tick(bid="0"), _tick()):
            queue.put_nowait(record)
        for _ in range(50):  # the drain task takes the queue on the loop's next turns
            if queue.empty() and stream.latest("BTCUSDT") is not None:
                break
            await asyncio.sleep(0)
        await stream.handle_frame('{"topic":"tickers.BTCUSDT"}')  # a venue frame: never taken
        reading = await ReferencePricesBinding(stream).market("BTCUSDT")
        await stream.stop()

    assert reading.mid == Decimal("100.1") and reading.last == Decimal("100.1")
    event = stream.latest("BTCUSDT")
    assert event is not None and event.mark_price == event.index_price == Decimal("100.1")
    assert event.source == "synthetic"
    assert (stream.phase("BTCUSDT"), stream.phase("ETHUSDT")) == ("live", None)
    assert stream.is_listed("BTCUSDT") and not stream.is_listed("ETHUSDT")
    ours = [e for e in logs if str(e["event"]).startswith("ingestion.synthetic_ticker")]
    assert {e["event"] for e in ours} == {
        "ingestion.synthetic_ticker_attached",
        "ingestion.synthetic_ticker_started",
        "ingestion.synthetic_ticker_symbol",
    }
    assert all(e["source"] == "synthetic" for e in ours)
    assert opened == []


async def test_a_symbol_with_no_recent_tick_is_stale_and_prices_nothing(
    state: Path,  # noqa: F811
    close_pairs: list[wiring.FixtureDoor],
) -> None:
    settings = _dev(state)
    door = build_account_fixture(settings)
    assert isinstance(door, wiring.FixtureDoor)
    close_pairs.append(door)
    await _armed(settings, door)
    clock = _Clock()
    stream = st.SyntheticTickerStream(door, lambda: None, env="demo", monotonic=clock)
    stream.offer(_tick())
    assert await ReferencePricesBinding(stream).reference_price("BTCUSDT") == Decimal("100.1")

    clock.now += st.STALE_AFTER_S + 0.1

    assert stream.is_stale("BTCUSDT") and stream.phase("BTCUSDT") == "stale"
    assert await ReferencePricesBinding(stream).reference_price("BTCUSDT") is None
    with capture_logs() as logs:
        await stream.start()  # no synthetic feed queue: idle, said so
        await stream.stop()
    assert [e.get("reason") for e in logs] == ["no_synthetic_feed"]


async def test_a_malformed_record_is_skipped_and_the_next_one_still_prices(
    state: Path,  # noqa: F811
    close_pairs: list[wiring.FixtureDoor],
) -> None:
    settings = _dev(state)
    door, ingestion = _attached(settings)
    close_pairs.append(door)
    await _armed(settings, door)
    stream = _stream(ingestion)
    queue: st.FeedQueue = asyncio.Queue(maxsize=8)
    ingestion.queue = queue
    bad = Ticker.model_construct(
        symbol="BTCUSDT", last_price=None, bid_price=None, ask_price=None, ts=TS
    )
    with capture_logs() as logs:
        await stream.start()
        for record in (bad, _tick()):
            queue.put_nowait(record)
        for _ in range(50):
            if queue.empty() and stream.latest("BTCUSDT") is not None:
                break
            await asyncio.sleep(0)
        await stream.stop()

    event = stream.latest("BTCUSDT")
    assert event is not None and event.mark_price == Decimal("100.1")
    refused = [e for e in logs if e["event"] == "ingestion.synthetic_ticker_record_refused"]
    assert [e["source"] for e in refused] == ["synthetic"]
    assert all("None" not in str(v) for e in refused for v in e.values())


def test_latest_answers_nothing_once_the_door_is_unarmed() -> None:
    """`latest`'s own armed check: a reading taken while armed is not served once unarmed."""
    door = _Door(armed=object())
    stream = st.SyntheticTickerStream(door, lambda: None, env="demo")
    stream.offer(_tick())
    assert stream.latest("BTCUSDT") is not None

    door.armed = None

    assert stream.phase("BTCUSDT") == "live" and stream.is_listed("BTCUSDT")
    assert stream.latest("BTCUSDT") is None


async def test_the_drain_gives_the_loop_a_turn_every_pump_yield_every_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A burst already queued never suspends `queue.get()`; the drain yields on its own, once
    per `PUMP_YIELD_EVERY` records, so another task runs between the blocks."""
    burst = 3 * PUMP_YIELD_EVERY + 5
    queue: st.FeedQueue = asyncio.Queue(maxsize=burst)
    for _ in range(burst):
        queue.put_nowait(_tick())
    stream = st.SyntheticTickerStream(_Door(armed=object()), lambda: queue, env="demo")
    turns = 0
    seen_at: list[int] = []
    monkeypatch.setattr(stream, "offer", lambda _record: seen_at.append(turns))

    async def _other() -> None:
        nonlocal turns
        while True:
            turns += 1
            await asyncio.sleep(0)

    other = asyncio.create_task(_other())
    await stream.start()
    for _ in range(4 * burst):
        if len(seen_at) == burst:
            break
        await asyncio.sleep(0)
    await stream.stop()
    other.cancel()
    await asyncio.gather(other, return_exceptions=True)

    assert len(seen_at) == burst
    changed = [i for i in range(1, burst) if seen_at[i] != seen_at[i - 1]]
    assert changed == [PUMP_YIELD_EVERY * k for k in (1, 2, 3)]
