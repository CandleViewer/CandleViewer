"""E08-T08 (#4707): the `ticker` topics end to end, through the real `/ws` router (`_harness`, which
validates every frame against `23-ws-protocol.md` §13-§15, the §14.8 `TickerUpdate` included).

Recorded BTCUSDT ticker frames replay through the production `TickerStream` and `TickerTopic`; the
ETHUSDT and SOLUSDT frames are those frames re-keyed in-test (`tests/_tickers.py`). Time is the
harness's fake clock, and the outbound pipeline's window paces each subscription behind the
topic's own 250 ms window (§8.1).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

import pytest

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import Topic
from candleviewer.domain.events import InstrumentUpdatedEvent, uuid7
from candleviewer.domain.primitives import EventId
from candleviewer.exchange.bybit.ticker import parse_ticker_frame, ticker_topic
from candleviewer.ingestion.ticker_stream import REQUIRED_FIELDS, TickerStream
from candleviewer.ingestion.ticker_topic import WINDOW_S, TickerTopic
from candleviewer.ws.sequencing import SnapshotBody
from candleviewer.ws.upstream import GRACE_S, UpstreamRefs
from candleviewer.ws_wiring import IngestionUpstreamSink, InstrumentRevisions, SnapshotRouter
from tests import _tickers as t
from tests.contract.ws import _harness as h

KNOWN = frozenset({"BTCUSDT", "ETHUSDT", "SOLUSDT"})
#: The §14.8 item names of the merged state's required fields (24 §2.3).
_WIRE = {"bid1_qty": "bid1_size", "ask1_qty": "ask1_size", "price_24h_pcnt": "price_change_pct_24h"}
REQUIRED_ITEM = {_WIRE.get(f, f) for f in REQUIRED_FIELDS} | {"symbol", "ts_ms", "stale"}
BATCHED = {"ch": "ticker", "opts": {"symbols": ["BTCUSDT", "ETHUSDT"]}}


@dataclass
class Rig:
    w: h.World
    bus: Bus
    stream: TickerStream
    topic: TickerTopic[SnapshotBody]
    desired: set[str]

    def feed(self, frame: str | None = None) -> None:
        """One frame through the stream on the app loop, then the topic's pump and tick."""
        if frame is not None:
            self.w.call(self.stream.handle_frame, frame)
        self.w.call(self.topic.pump)
        self.w.call(self.topic.tick)


def _rig() -> Rig:
    w = h.World()
    bus = Bus()
    desired: set[str] = set()

    def set_desired(topics: set[str]) -> None:
        desired.clear()
        desired.update(topics)

    def now_us() -> int:
        return w.clock.wall_ms() * 1000

    stream = TickerStream(
        bus=bus, env="live", set_desired=set_desired, parse_frame=parse_ticker_frame,
        topic_for=ticker_topic, is_listed=KNOWN.__contains__, touch=lambda _t: None,
        clock=w.clock, now_us=now_us,
    )  # fmt: skip
    topic = TickerTopic(
        w.hub.subscriptions, w.hub.publish, w.hub.resnapshot, SnapshotBody,
        reader=lambda: stream, bus=bus, env="live", clock=w.clock, now_us=now_us,
    )  # fmt: skip
    topic.open()
    services = w.registry.services
    services.snapshots = SnapshotRouter({"ticker": topic})
    services.instrument_known = KNOWN.__contains__
    sink = IngestionUpstreamSink(lambda family: stream if family == "ticker" else None)
    services.upstream = UpstreamRefs(sink)
    services.clock = w.clock
    return Rig(w, bus, stream, topic, desired)


def _quiet(c: h.Client) -> None:
    """Nothing reached the client: the next frame answers this `ping`."""
    c.send({"t": "ping", "id": "q"})
    assert c.recv()["t"] == "pong"


def _until_pong(c: h.Client) -> list[dict[str, Any]]:
    c.send({"t": "ping", "id": "end"})
    frames: list[dict[str, Any]] = []
    while (frame := c.recv())["t"] != "pong":
        frames.append(frame)
    return frames


def _items(frame: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = h.structured_of(frame)["tickers"]
    return items


def test_ac1_a_ticker_subscription_is_snapped_then_streamed_no_faster_than_250_ms() -> None:
    rig = _rig()
    t0 = json.loads(t.FRAMES[0])["ts"]
    with h.connect(rig.w) as c:
        rig.w.call(rig.stream.acquire, "replay", "BTCUSDT")  # the replay holds the symbol
        rig.feed(t.FRAMES[0])
        assert c.sub("ticker.BTCUSDT")["p"]["results"][0]["ok"]
        snap = c.next_of("snap")  # validated against §14.8 by the harness
        (item,) = _items(snap)
        assert REQUIRED_ITEM <= item.keys() and item["last_price"] == t.DATA["lastPrice"]
        for raw in t.FRAMES[1:]:  # 100 ms apart, as recorded
            rig.w.clock.now = (json.loads(raw)["ts"] - t0) / 1000
            rig.feed(raw)
        rig.w.clock.now += WINDOW_S
        rig.feed()  # the last window closes
        rig.w.clock.now += 1.0  # and the pipeline's, which holds its update (§8.1)
        final = rig.stream.latest("BTCUSDT")
        assert final is not None and final.last_price is not None
        last = format(final.last_price, "f")
        # the topic's own `d`s up to the one holding the final state, read as a fence (a `pong`
        # rides the priority lane, so it can pass a window); a `system` notice may ride along
        deltas: list[dict[str, Any]] = []
        for _ in range(64):  # bounded: a missing final delta fails here, not on a recv timeout
            if deltas and _items(deltas[-1])[0]["last_price"] == last:
                break
            if (f := c.recv())["t"] == "d" and f["ch"] == "ticker.BTCUSDT":
                deltas.append(f)
        assert deltas and _items(deltas[-1])[0]["last_price"] == last
        assert [f for f in _until_pong(c) if f.get("ch") == "ticker.BTCUSDT"] == []
    assert len(deltas) >= 5
    assert min(b["ts"] - a["ts"] for a, b in pairwise(deltas)) >= WINDOW_S * 1000
    assert [d["s"] for d in deltas] == list(range(snap["s"] + 1, snap["s"] + 1 + len(deltas)))


@pytest.mark.parametrize("offer", h.OFFERS.values(), ids=h.OFFERS.keys())
def test_ac2_two_connections_on_the_batched_topic_share_one_upstream_per_symbol(
    offer: list[str],
) -> None:
    """The WS lease (`UpstreamRefs`) holds one key per symbol and lets each go 30 s after the last
    holder leaves; ingestion's own demand then keeps its grace (stacked, ruling 3)."""
    rig = _rig()
    refs = rig.w.registry.services.upstream
    with rig.w.client:
        with (
            rig.w.client.websocket_connect("/ws", subprotocols=offer) as one,
            rig.w.client.websocket_connect("/ws", subprotocols=offer) as two,
        ):
            for ws in (one, two):
                client = h.Client(ws)
                client.open()
                assert client.sub(BATCHED)["p"]["results"][0]["ok"]
            keys = refs.active()
            assert sorted(k[0] for k in keys) == ["BTCUSDT", "ETHUSDT"]
            assert [refs.consumers(k) for k in keys] == [2, 2]
            assert rig.desired == {"tickers.BTCUSDT", "tickers.ETHUSDT"}  # one upstream each
        assert [refs.consumers(k) for k in keys] == [0, 0]
        assert rig.w.call(refs.sweep, rig.w.clock.now + GRACE_S - 0.1) == []
        assert set(rig.w.call(refs.sweep, rig.w.clock.now + GRACE_S)) == keys
    assert rig.desired == {"tickers.BTCUSDT", "tickers.ETHUSDT"}  # ingestion's grace still runs
    rig.w.clock.now += 2 * GRACE_S + 1.0
    rig.stream.sync()
    assert rig.desired == set()


def test_ac3_a_warming_symbol_is_never_snapped_half_populated() -> None:
    rig = _rig()
    with h.connect(rig.w) as c:
        result = c.sub("ticker.BTCUSDT")["p"]["results"][0]
        assert result["ok"] and result["snapshot_pending"]
        rig.feed(t.FRAMES[1])  # the first message after the upstream subscribe: a partial delta
        assert rig.stream.phase("BTCUSDT") == "warming"
        _quiet(c)
        rig.feed(t.FRAMES[0])  # the full push completes the merged state
        snap = c.next_of("snap")
    assert snap["meta"]["reason"] == "initial"
    (item,) = _items(snap)
    assert REQUIRED_ITEM <= item.keys()


def test_a_batched_subscription_waits_for_every_symbol_it_names_then_snaps_them_all() -> None:
    rig = _rig()
    eth = t.rekeyed("ETHUSDT")
    with h.connect(rig.w) as c:
        result = c.sub(BATCHED)["p"]["results"][0]
        assert result["ok"] and result["snapshot_pending"]
        rig.feed(t.FRAMES[0])  # BTCUSDT complete, ETHUSDT still warming
        rig.feed(eth[1])
        _quiet(c)
        rig.w.clock.now += WINDOW_S
        rig.feed(eth[0])
        snap = c.next_of("snap")
    assert [i["symbol"] for i in _items(snap)] == ["BTCUSDT", "ETHUSDT"]
    assert all(REQUIRED_ITEM <= i.keys() for i in _items(snap))


def test_a_batched_subscription_naming_an_unknown_symbol_is_refused_as_the_named_topic_is() -> None:
    """Ruling 10:19Z: each entry of the batched `symbols` is checked against the instrument cache
    with `ticker.{symbol}`'s own code (§5.2), so W11 only ever covers known but slow symbols."""
    rig = _rig()
    with h.connect(rig.w) as c:
        mixed = {"ch": "ticker", "opts": {"symbols": ["BTCUSDT", "NOPEUSDT"]}}
        refused = c.sub(mixed)["p"]["results"][0]
        named = c.sub("ticker.NOPEUSDT")["p"]["results"][0]
        assert (refused["ok"], named["ok"]) == (False, False)
        assert refused["error"]["code"] == named["error"]["code"] == "unsupported_symbol"
        assert c.sub(BATCHED)["p"]["results"][0]["ok"]  # every symbol known: accepted
    assert rig.desired == {"tickers.BTCUSDT", "tickers.ETHUSDT"}  # nothing held for the refused


def test_ac4_an_instrument_revision_resnaps_a_ticker_subscription() -> None:
    rig = _rig()
    revisions = InstrumentRevisions(rig.bus, "live", rig.w.hub.instrument_revision)
    sol = t.rekeyed("SOLUSDT")
    event = InstrumentUpdatedEvent(
        event_id=EventId(uuid7(1)), ts_event=1, ts_ingest=1, source="live", symbol="SOLUSDT",
        metadata_version=2, changed_fields=("tick_size",),
    )  # fmt: skip
    with h.connect(rig.w) as c:
        assert c.sub("ticker.SOLUSDT")["p"]["results"][0]["ok"]
        rig.feed(sol[0])
        first = c.next_of("snap")
        rig.w.call(revisions.start)
        topic = Topic(env="live", domain="instruments", symbol="SOLUSDT", detail="updated")
        rig.w.call(rig.bus.publish, topic, event)
        resync = c.next_of("snap")
        rig.w.call(revisions.stop)
    assert resync["meta"]["reason"] == "instrument_revision"
    assert resync["meta"]["previous_seq"] == first["s"] and resync["s"] == first["s"] + 1
    assert _items(resync)[0]["symbol"] == "SOLUSDT"
