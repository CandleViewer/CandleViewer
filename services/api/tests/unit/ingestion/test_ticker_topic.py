"""E08-T08 (#4707): the `ticker` topics' snapshot source and delta publisher (23 §7.7, §8, §14.8).

Fakes for the hub and the merged state, a fake clock, no sleeps: the loop runs for real with a
tiny window, and its tests wait on events. Every rendered body validates against the §14.8 schema.
The rows are the recorded BTCUSDT snapshot's fields (`tests/_tickers.py`), re-keyed for other
symbols.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.api.ticker import _DECIMALS as REST_DECIMALS
from candleviewer.bus.bus import Bus
from candleviewer.bus.models import StreamInvalidated, Topic
from candleviewer.exchange.base.models import TickerEvent
from candleviewer.exchange.bybit.ticker import parse_ticker_frame
from candleviewer.ingestion import ticker_topic
from candleviewer.ingestion.ticker_stream import ticker_event
from candleviewer.ingestion.ticker_topic import _DECIMALS as WS_DECIMALS
from candleviewer.ingestion.ticker_topic import STALE_S, WINDOW_S, TickerTopic, served
from tests import _tickers as t
from tests.contract.ws._harness import check_schema

SCHEMA = "cv://ws/v1/ticker.schema.json"
_FIRST = parse_ticker_frame(t.FRAMES[0])
assert _FIRST is not None
FIELDS: Mapping[str, Decimal | int] = _FIRST.fields


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def us(self) -> int:
        return 1_790_000_000_000_000 + round(self.t * 1e6)


@dataclass
class Sub:
    """The fields of a WS `Subscription` the topic reads."""

    ch: str
    opts: dict[str, Any] = field(default_factory=dict)
    replay_session_id: str | None = None
    snapshot_pending: bool = True
    ended: bool = False

    @property
    def topic(self) -> SimpleNamespace:
        family, _, rest = self.ch.partition(".")
        return SimpleNamespace(symbol=(rest or None) if family == "ticker" else None)


class Hub:
    """`SequencingHub`'s `subscriptions`, `publish` and `resnapshot`, recorded."""

    def __init__(self) -> None:
        self.subs: list[Sub] = []
        self.sent: list[tuple[str, dict[str, Any], list[Sub]]] = []
        self.resyncs: list[tuple[Callable[[Any], bool], str]] = []
        self.fail = False
        self.published = asyncio.Event()

    def subscriptions(self, ch: str) -> list[Sub]:
        return [s for s in self.subs if s.ch == ch and s.replay_session_id is None]

    def publish(
        self,
        ch: str,
        body: Mapping[str, Any] | None = None,
        *,
        select: Callable[[Any], bool] | None = None,
        wake: bool = False,
    ) -> int:
        if self.fail:
            raise RuntimeError("fan-out broke")
        assert wake is True and body is not None
        check_schema(SCHEMA, dict(body), ch)
        hit = [s for s in self.subscriptions(ch) if select is None or select(s)]
        self.sent.append((ch, dict(body), hit))
        self.published.set()
        return len(hit)

    def resnapshot(self, match: Callable[[Any], bool], reason: str) -> int:
        self.resyncs.append((match, reason))
        return 0


class Reader:
    """The ticker stream's merged state; `reads` counts the `latest` calls."""

    def __init__(self) -> None:
        self.events: dict[str, TickerEvent] = {}
        self.phases: dict[str, str] = {}
        self.reads = 0

    def latest(self, symbol: str) -> TickerEvent | None:
        self.reads += 1
        return self.events.get(symbol)

    def phase(self, symbol: str) -> str | None:
        return self.phases.get(symbol)

    def push(self, event: TickerEvent) -> TickerEvent:
        self.events[event.symbol], self.phases[event.symbol] = event, "live"
        return event


class Counter:
    def __init__(self) -> None:
        self.count = 0

    def inc(self, amount: float = 1) -> None:
        self.count += int(amount)


def _event(clock: Clock, symbol: str = "BTCUSDT", last: str | None = None) -> TickerEvent:
    fields = dict(FIELDS) | ({"last_price": Decimal(last)} if last else {})
    return ticker_event(symbol, fields, ts_event_us=clock.us(), ts_ingest_us=clock.us())


def _body(structured: Mapping[str, Any]) -> dict[str, Any]:
    return dict(structured)


@dataclass
class Rig:
    clock: Clock = field(default_factory=Clock)
    hub: Hub = field(default_factory=Hub)
    reader: Reader = field(default_factory=Reader)
    bus: Bus = field(default_factory=Bus)
    overdue: Counter = field(default_factory=Counter)

    def topic(self, **kw: Any) -> TickerTopic[dict[str, Any]]:
        return TickerTopic(
            self.hub.subscriptions,
            self.hub.publish,
            self.hub.resnapshot,
            _body,
            reader=lambda: self.reader,
            bus=self.bus,
            env="live",
            overdue=self.overdue,
            clock=self.clock,
            now_us=self.clock.us,
            **kw,
        )

    def push(self, topic: TickerTopic[Any], symbol: str = "BTCUSDT", last: str = "") -> None:
        topic.offer(self.reader.push(_event(self.clock, symbol, last or None)))


def _batched(*symbols: str) -> Sub:
    return Sub("ticker", {"symbols": list(symbols)})


def _item(topic: TickerTopic[dict[str, Any]], sub: Sub) -> dict[str, Any]:
    body = topic.build(sub)
    assert body is not None
    item: dict[str, Any] = body["tickers"][0]
    return item


# -- snapshots -----------------------------------------------------------------------------------


def test_a_complete_state_snaps_each_served_symbol_sorted_whole_and_valid() -> None:
    rig = Rig()
    topic = rig.topic()
    for symbol in ("BTCUSDT", "ETHUSDT"):
        rig.reader.push(_event(rig.clock, symbol))
    body = topic.build(_batched("ETHUSDT", "BTCUSDT"))
    assert body is not None
    check_schema(SCHEMA, body, "snap")
    btc, eth = body["tickers"]
    assert (btc["symbol"], eth["symbol"]) == ("BTCUSDT", "ETHUSDT")
    assert (btc["high_24h"], btc["low_24h"]) == (t.DATA["highPrice24h"], t.DATA["lowPrice24h"])
    assert btc["last_price"] == t.DATA["lastPrice"] and btc["bid1_size"] == t.DATA["bid1Size"]
    assert btc["ts_ms"] == rig.clock.us() // 1000 and btc["stale"] is False
    assert btc["next_funding_time_ms"] == int(t.DATA["nextFundingTime"])


def test_a_warming_symbol_holds_the_snapshot_and_a_replay_is_never_served() -> None:
    rig = Rig()
    topic = rig.topic()
    rig.reader.push(_event(rig.clock))
    rig.reader.phases["ETHUSDT"] = "warming"  # demanded, no complete state yet
    assert topic.build(_batched("BTCUSDT", "ETHUSDT")) is None
    assert topic.build(Sub("ticker.BTCUSDT", replay_session_id="r")) is None
    assert topic.build(Sub("ticker.BTCUSDT")) is not None


def test_a_per_symbol_topic_serves_its_name_never_its_symbols_option() -> None:
    rig = Rig()
    topic = rig.topic()
    rig.reader.push(_event(rig.clock))  # ETHUSDT is never ingested
    body = topic.build(Sub("ticker.BTCUSDT", {"symbols": ["ETHUSDT"]}))
    assert body is not None and [i["symbol"] for i in body["tickers"]] == ["BTCUSDT"]


def test_a_field_the_merged_state_lacks_is_left_out_never_null() -> None:
    rig = Rig()
    topic = rig.topic()
    bare = {k: v for k, v in FIELDS.items() if k not in {"high_24h", "open_interest_value"}}
    rig.reader.push(ticker_event("BTCUSDT", bare, ts_event_us=rig.clock.us(), ts_ingest_us=0))
    body = topic.build(Sub("ticker.BTCUSDT"))
    assert body is not None
    (item,) = body["tickers"]
    assert {"high_24h", "open_interest_value"}.isdisjoint(item) and None not in item.values()


def test_the_ws_item_and_the_rest_ticker_read_every_decimal_of_the_event_alike() -> None:
    """Two tables (ingestion may not import the api): both read every `Decimal` field of
    `TickerEvent`, under the same names, so neither drifts from the other or from the event."""
    event = _event(Clock())  # every field recorded, the 24 h range included
    decimals = {
        name for name in TickerEvent.model_fields if isinstance(getattr(event, name), Decimal)
    }
    assert WS_DECIMALS == REST_DECIMALS
    assert sorted(source for _, source in WS_DECIMALS) == sorted(decimals)
    assert len(decimals) == len(WS_DECIMALS) == 15


def test_stale_follows_the_merged_states_age_on_a_fake_clock() -> None:
    rig = Rig()
    topic = rig.topic()
    rig.reader.push(_event(rig.clock))
    sub = Sub("ticker.BTCUSDT")
    rig.clock.t += STALE_S  # exactly the threshold: still fresh
    assert _item(topic, sub)["stale"] is False
    rig.clock.t += 0.001
    assert _item(topic, sub)["stale"] is True


def test_the_generation_moves_with_a_new_state_or_a_stale_flip_only() -> None:
    rig = Rig()
    topic = rig.topic()
    sub = _batched("BTCUSDT", "ETHUSDT")
    for symbol in ("BTCUSDT", "ETHUSDT"):
        rig.reader.push(_event(rig.clock, symbol))
    first = topic.generation(sub)
    assert topic.generation(sub) == first
    rig.reader.push(_event(rig.clock, "ETHUSDT", "2500"))
    pushed = topic.generation(sub)
    assert pushed > first and topic.generation(sub) == pushed
    rig.clock.t += STALE_S + 1.0  # both flip stale with no new state
    assert topic.generation(sub) > pushed
    assert topic.continuity(sub, None) is False and topic.continuity(sub, 1) is False


# -- deltas --------------------------------------------------------------------------------------


def _frames(rig: Rig, ch: str) -> list[dict[str, Any]]:
    return [body for sent_ch, body, _ in rig.hub.sent if sent_ch == ch]


def test_a_change_goes_out_at_once_then_at_most_once_per_window() -> None:
    rig = Rig()
    topic = rig.topic()
    rig.push(topic, last="1")
    assert topic.tick() == 0 and len(_frames(rig, "ticker.BTCUSDT")) == 1  # the leading edge
    for last in ("2", "3"):
        rig.clock.t += WINDOW_S / 4  # binary fractions: exact window edges
        rig.push(topic, last=last)
        topic.tick()
    assert len(_frames(rig, "ticker.BTCUSDT")) == 1  # held inside the window
    rig.clock.t += WINDOW_S / 2
    topic.tick()  # the window closes: the latest state goes out, whole
    frames = _frames(rig, "ticker.BTCUSDT")
    assert [f["tickers"][0]["last_price"] for f in frames] == ["1", "3"]
    rig.clock.t += WINDOW_S
    assert topic.tick() == 0 and len(rig.hub.sent) == 2  # nothing changed: nothing goes out


def test_a_batched_group_gets_one_frame_per_window_with_its_changed_items() -> None:
    rig = Rig()
    pair, single = _batched("ETHUSDT", "BTCUSDT"), _batched("ETHUSDT")
    rig.hub.subs += [pair, single, Sub("ticker.BTCUSDT")]
    topic = rig.topic()
    rig.push(topic, "BTCUSDT")
    rig.push(topic, "ETHUSDT")
    assert topic.tick() == 3  # ticker.BTCUSDT's holder and each group; ticker.ETHUSDT has none
    batched = {
        tuple(i["symbol"] for i in body["tickers"]): [id(s) for s in hit]
        for ch, body, hit in rig.hub.sent
        if ch == "ticker"
    }
    assert batched == {("BTCUSDT", "ETHUSDT"): [id(pair)], ("ETHUSDT",): [id(single)]}


def test_a_flush_computes_each_batched_subscriptions_symbols_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The groups are taken once per flush: `served` runs once per batched subscription, however
    many groups there are, and each group's frame still reaches exactly its own subscriptions."""
    calls: list[int] = []

    def counted(sub: Any) -> tuple[str, ...]:
        calls.append(id(sub))
        return served(sub)

    monkeypatch.setattr(ticker_topic, "served", counted)
    rig = Rig()
    batched = [_batched("ETHUSDT", "BTCUSDT"), _batched("BTCUSDT", "ETHUSDT"), _batched("SOLUSDT")]
    pair, same, single = batched
    rig.hub.subs += [*batched, Sub("ticker.BTCUSDT")]
    topic = rig.topic()
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        rig.push(topic, symbol)
    assert topic.tick() == 4  # ticker.BTCUSDT's holder, both BTCUSDT+ETHUSDT ones, the SOLUSDT one
    assert sorted(calls) == sorted(map(id, batched))
    sent = {
        tuple(i["symbol"] for i in body["tickers"]): [id(s) for s in hit]
        for ch, body, hit in rig.hub.sent
        if ch == "ticker"
    }
    assert sent == {("BTCUSDT", "ETHUSDT"): [id(pair), id(same)], ("SOLUSDT",): [id(single)]}
    calls.clear()
    rig.clock.t += WINDOW_S
    rig.push(topic, "SOLUSDT")
    assert topic.tick() == 1  # the next flush: only the SOLUSDT one's symbol changed
    assert sorted(calls) == sorted(map(id, batched))


def test_the_held_symbols_are_swept_at_most_once_per_window() -> None:
    """A wake between two sweeps reads none of the held symbols' merged state."""
    rig = Rig()
    topic = rig.topic()
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        rig.push(topic, symbol)
    topic.tick()  # the first sweep, and the leading edge
    reads = rig.reader.reads
    for _ in range(10):
        rig.clock.t += WINDOW_S / 16  # binary fractions: ten wakes inside one window
        assert topic.tick() == 0
    assert rig.reader.reads == reads
    rig.clock.t += WINDOW_S
    topic.tick()
    assert rig.reader.reads == reads + 3  # the next window: one sweep of the three


def test_a_symbol_past_the_threshold_goes_out_once_more_as_stale_until_its_next_push() -> None:
    rig = Rig()
    topic = rig.topic()
    rig.push(topic)
    topic.tick()
    rig.clock.t += STALE_S + 0.1
    topic.tick()
    rig.clock.t += 1.0
    topic.tick()  # announced once
    rig.push(topic, last="1")
    rig.clock.t += WINDOW_S
    topic.tick()
    stale = [f["tickers"][0]["stale"] for f in _frames(rig, "ticker.BTCUSDT")]
    assert stale == [False, True, False]


def test_a_reconnecting_symbol_never_goes_out_as_live_and_an_older_push_never_lands() -> None:
    rig = Rig()
    topic = rig.topic()
    older = _event(rig.clock, last="1")
    rig.clock.t += 1.0
    rig.push(topic, last="2")
    topic.offer(older)  # a push older than the held state
    topic.tick()
    assert [f["tickers"][0]["last_price"] for f in _frames(rig, "ticker.BTCUSDT")] == ["2"]
    rig.clock.t += WINDOW_S
    topic.offer(_event(rig.clock, last="3"))  # in flight as the stream reconnects
    del rig.reader.events["BTCUSDT"]
    rig.reader.phases["BTCUSDT"] = "warming"
    topic.tick()
    assert len(rig.hub.sent) == 1  # its pre-drop values are never presented as live


def test_the_symbols_held_are_bounded_and_let_go_with_the_stream() -> None:
    rig = Rig()
    topic = rig.topic(max_symbols=2)
    for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        rig.push(topic, symbol)
    topic.tick()
    assert sorted(ch for ch, _, _ in rig.hub.sent) == ["ticker.BTCUSDT", "ticker.ETHUSDT"]
    del rig.reader.events["ETHUSDT"], rig.reader.phases["ETHUSDT"]  # the stream let it go
    rig.clock.t += WINDOW_S
    topic.tick()
    rig.push(topic, "SOLUSDT")
    rig.clock.t += WINDOW_S
    topic.tick()
    assert rig.hub.sent[-1][0] == "ticker.SOLUSDT"


def test_a_lost_bus_queue_or_a_failed_publish_resyncs_every_live_ticker_subscription() -> None:
    rig = Rig()
    topic = rig.topic()
    topic.offer(StreamInvalidated(topic="live.md.BTCUSDT.ticker", ts_event=0))
    rig.hub.fail = True
    rig.push(topic)
    topic.tick()
    assert [reason for _, reason in rig.hub.resyncs] == ["upstream_desync"] * 2
    match = rig.hub.resyncs[0][0]
    assert match(Sub("ticker")) and match(Sub("ticker.BTCUSDT"))
    assert not match(Sub("ticker.BTCUSDT", replay_session_id="r"))
    assert not match(Sub("book.BTCUSDT.50"))


def test_a_subscription_pending_past_the_threshold_counts_once_per_wait() -> None:
    """23 §16.6 W11: it stays pending, never an error, and counts once per wait."""
    rig = Rig()
    topic = rig.topic()
    sub = _batched("BTCUSDT", "ETHUSDT")
    rig.reader.push(_event(rig.clock))
    assert topic.build(sub) is None  # ETHUSDT has no state: a wait starts
    rig.clock.t += STALE_S
    topic.tick()
    assert rig.overdue.count == 0
    rig.clock.t += 0.01
    topic.tick()
    rig.clock.t += 10.0
    topic.build(sub)
    topic.tick()
    assert rig.overdue.count == 1  # once for this wait
    rig.reader.push(_event(rig.clock, "ETHUSDT"))
    assert topic.build(sub) is not None
    sub.snapshot_pending = False
    topic.tick()  # snapped: the wait is over
    sub.snapshot_pending = True
    del rig.reader.events["ETHUSDT"]
    assert topic.build(sub) is None  # a new wait
    rig.clock.t += STALE_S + 0.01
    topic.tick()
    assert rig.overdue.count == 2


async def test_the_loop_publishes_a_push_from_the_bus_and_stop_lets_go() -> None:
    rig = Rig()
    topic = rig.topic()
    topic.start()
    event = rig.reader.push(_event(rig.clock))
    await rig.bus.publish(Topic(env="live", domain="md", symbol="BTCUSDT", detail="ticker"), event)
    await asyncio.wait_for(rig.hub.published.wait(), timeout=5)
    assert rig.hub.sent[0][0] == "ticker.BTCUSDT"
    await topic.stop()
    await topic.stop()  # idempotent
    assert topic.pump() == 0


async def test_the_loop_sends_a_push_held_in_the_window_once_it_closes_with_no_push_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real loop with a tiny window: the window is the fake clock's, and the loop's wait for
    the next push times out on its own, so the held state goes out once the window has closed."""
    rig = Rig()
    topic = rig.topic(window_s=0.01)
    taken = asyncio.Event()
    offer = topic.offer

    def spy(item: object) -> None:
        offer(item)
        taken.set()

    monkeypatch.setattr(topic, "offer", spy)
    btc = Topic(env="live", domain="md", symbol="BTCUSDT", detail="ticker")
    topic.start()
    await rig.bus.publish(btc, rig.reader.push(_event(rig.clock, last="1")))
    await asyncio.wait_for(rig.hub.published.wait(), timeout=5)  # the leading edge
    rig.hub.published.clear()
    taken.clear()
    await rig.bus.publish(btc, rig.reader.push(_event(rig.clock, last="2")))
    await asyncio.wait_for(taken.wait(), timeout=5)  # the loop holds it, and waits again
    assert len(rig.hub.sent) == 1  # inside the window: nothing goes out
    rig.clock.t += 0.02  # the window closes; no push follows
    await asyncio.wait_for(rig.hub.published.wait(), timeout=5)  # the trailing edge
    await topic.stop()
    assert [f["tickers"][0]["last_price"] for f in _frames(rig, "ticker.BTCUSDT")] == ["1", "2"]


async def test_a_turn_that_keeps_failing_resyncs_once_per_window_never_in_a_spin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each failed turn re-snaps every live ticker subscription, then waits one window (the
    injected sleep, held on an event here) before the next turn."""
    rig = Rig()
    naps: list[float] = []
    napping, wake = asyncio.Event(), asyncio.Event()

    async def nap(seconds: float) -> None:
        naps.append(seconds)
        napping.set()
        await wake.wait()
        wake.clear()

    def broken() -> int:
        raise RuntimeError("tick broke")

    topic = rig.topic(window_s=0.001, sleep=nap)
    monkeypatch.setattr(topic, "tick", broken)
    topic.start()
    await asyncio.wait_for(napping.wait(), timeout=5)
    for _ in range(50):  # the loop is parked in its back-off: no further turn
        await asyncio.sleep(0)
    assert (naps, [reason for _, reason in rig.hub.resyncs]) == ([0.001], ["upstream_desync"])
    napping.clear()
    wake.set()
    await asyncio.wait_for(napping.wait(), timeout=5)  # the next turn failed too
    await topic.stop()
    assert (naps, len(rig.hub.resyncs)) == ([0.001, 0.001], 2)


@pytest.mark.parametrize("item", [object(), "noise"])
def test_an_item_that_is_no_ticker_event_is_ignored(item: object) -> None:
    rig = Rig()
    topic = rig.topic()
    topic.offer(item)
    assert topic.tick() == 0 and rig.hub.resyncs == []


async def test_a_publisher_running_behind_yields_to_the_event_loop_every_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # #4929's sibling (C-2.18): a turn whose window is already due awaits nothing else, so it must
    # yield once, or the publisher keeps the loop it shares with the OMS while it runs late.
    rig = Rig()
    topic = rig.topic()
    topic.open()
    topic._changed.add("BTCUSDT")  # a change pending since a flush long past: every turn is late
    turns: list[int] = []
    other = 0

    def tick() -> None:
        turns.append(other)
        if len(turns) == 5:
            topic._sub = None  # stop the loop after five late turns

    monkeypatch.setattr(topic, "pump", lambda: None)
    monkeypatch.setattr(topic, "tick", tick)

    async def neighbour() -> None:
        nonlocal other
        while len(turns) < 5:
            other += 1
            await asyncio.sleep(0)

    await asyncio.wait_for(asyncio.gather(topic._run(), neighbour()), timeout=5)
    assert turns == [1, 2, 3, 4, 5]  # the neighbour ran once between each of the publisher's turns


async def test_a_fault_that_persists_waits_a_window_each_turn_and_never_spins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # #4929's sibling (C-2.18): a `pump` that raises every turn resyncs, then waits one window
    # before the next turn, so a persistent fault costs one resync per window, never a tight loop.
    waits: list[float] = []
    topic: TickerTopic[dict[str, Any]]

    async def sleep(s: float) -> None:
        waits.append(s)
        if len(waits) == 3:
            topic._sub = None  # stop the loop after three faulted turns
        await asyncio.sleep(0)

    rig = Rig()
    topic = rig.topic(sleep=sleep)
    topic.open()
    resyncs: list[None] = []
    monkeypatch.setattr(topic, "_resync", lambda: resyncs.append(None))

    def pump() -> None:
        raise RuntimeError("persistent")

    monkeypatch.setattr(topic, "pump", pump)
    topic._changed.add("BTCUSDT")
    await asyncio.wait_for(topic._run(), timeout=5)
    assert waits == [WINDOW_S] * 3 and len(resyncs) == 3
