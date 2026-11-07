"""E24-T03 (#667): the `liquidations` WS topics: schema, throttle, append-never-merge, exact
clusters, replay dedup, snapshot, the 41-symbol metric and a 500 prints/s cascade.

Fake clocks and a fake hub; the prints are the docs-shaped burst fixture through the production
`LiquidationStream`, so a print goes socket -> stream -> bus -> topic -> frame, and to the store.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import pytest

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import StreamInvalidated
from candleviewer.exchange.base.models import LiquidationEvent
from candleviewer.exchange.bybit.liquidations import (
    LIQUIDATION_NOTE,
    liquidation_topic,
    parse_liquidation_frame,
)
from candleviewer.ingestion.liquidation_stream import LiquidationStream
from candleviewer.orderflow import deriv_metrics
from candleviewer.orderflow.liquidation_topic import (
    LiquidationsTopic,
    _stopped,
    note_cap_refusal,
    options_of,
)
from candleviewer.orderflow.liquidations import LiquidationMeter, LiquidationService
from candleviewer.storage.questdb.liquidation_store import InMemoryLiquidationStore
from tests._corpus import corpus_path
from tests.contract.ws._harness import check_schema

BURST = corpus_path("ws/allLiquidation_BTCUSDT_burst.jsonl").read_text("utf-8").splitlines()
SCHEMA = "cv://ws/v1/liquidations.schema.json"
T0_US = int(json.loads(BURST[0])["ts"]) * 1000


@dataclass(frozen=True)
class _Topic:
    symbol: str | None


@dataclass(eq=False)
class Sub:
    ch: str
    opts: Mapping[str, Any] = field(default_factory=dict)
    replay_session_id: str | None = None

    @property
    def topic(self) -> _Topic:
        _, _, symbol = self.ch.partition(".")
        return _Topic(symbol or None)


class Hub:
    def __init__(self) -> None:
        self.subs: list[Sub] = []
        self.frames: list[tuple[str, Mapping[str, Any], list[Sub]]] = []
        self.resnaps = 0

    def subscriptions(self, ch: str) -> Sequence[Sub]:
        return [s for s in self.subs if s.ch == ch]

    def publish(
        self,
        ch: str,
        body: Mapping[str, Any] | None = None,
        *,
        select: Any = None,
        wake: bool = False,
    ) -> int:
        to = [s for s in self.subscriptions(ch) if select is None or select(s)]
        assert body is not None
        self.frames.append((ch, body, to))
        return len(to)

    def resnapshot(self, match: Any, reason: Literal["upstream_desync"]) -> int:
        self.resnaps += 1
        return sum(1 for s in self.subs if match(s))


class Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self.us = T0_US

    def mono(self) -> float:
        return self.t

    def now_us(self) -> int:
        return self.us

    def advance(self, s: float) -> None:
        self.t += s
        self.us += int(s * 1_000_000)


class Rig:
    def __init__(self) -> None:
        self.clock, self.bus, self.hub = Clock(), Bus(), Hub()
        self.store = InMemoryLiquidationStore()
        service = LiquidationService(store=self.store, listed=lambda s: True)
        self.stream = LiquidationStream(
            bus=self.bus, env="live", set_desired=lambda t: None,
            parse_frame=parse_liquidation_frame, topic_for=liquidation_topic,
            is_listed=lambda s: True, writer=_Writer(service), observer=LiquidationMeter(),
            clock=self.clock.mono, now_us=self.clock.now_us,
        )  # fmt: skip
        self.topic: LiquidationsTopic[dict[str, Any]] = LiquidationsTopic(
            self.hub.subscriptions, self.hub.publish, self.hub.resnapshot, _body,
            bus=self.bus, env="live", note=LIQUIDATION_NOTE,
            clock=self.clock.mono, now_us=self.clock.now_us,
        )  # fmt: skip
        self.topic.open()
        self.stream.acquire("ws:liquidations:", "BTCUSDT")

    async def feed(self, *frames: str) -> int:
        for frame in frames:
            await self.stream.handle_frame(frame)
        while self.stream.queued:
            await self.stream.write_once()
        self.topic.pump()
        return self.topic.tick()

    def sub(self, ch: str = "liquidations.BTCUSDT", **opts: Any) -> Sub:
        sub = Sub(ch, opts)
        self.hub.subs.append(sub)
        return sub


def _body(structured: Mapping[str, Any]) -> dict[str, Any]:
    return dict(structured)


class _Writer:
    def __init__(self, service: LiquidationService) -> None:
        self.service = service

    async def write_liquidations(self, events: Sequence[LiquidationEvent]) -> None:
        await self.service.write(events)


async def test_liquidation_print_persisted_and_republished_within_throttle() -> None:
    rig = Rig()
    rig.sub()
    assert await rig.feed(BURST[0]) == 1
    (ch, body, to), = rig.hub.frames  # fmt: skip
    assert ch == "liquidations.BTCUSDT" and len(to) == 1 and len(rig.store) == 1
    check_schema(SCHEMA, body, "liquidations d")
    assert body["note"] == LIQUIDATION_NOTE
    rig.clock.advance(0.2)
    assert await rig.feed(BURST[1]) == 0  # inside the 500 ms window: held, never dropped
    rig.clock.advance(0.3)
    assert rig.topic.tick() == 1
    assert len(rig.hub.frames[-1][1]["liquidations"]) == 3


async def test_three_prints_in_one_window_all_delivered() -> None:
    rig = Rig()
    rig.sub()
    await rig.feed(BURST[1])  # three prints, two of them identical but for batch_index
    items = rig.hub.frames[-1][1]["liquidations"]
    assert len(items) == 3 and items[0] == items[1]
    assert all(i["cluster_size"] == 1 for i in items)


async def test_cluster_window_sends_one_exact_item_once_closed_and_no_estimated_key() -> None:
    rig = Rig()
    rig.sub(cluster_window_ms=1000)
    await rig.feed(BURST[3])  # five prints inside one second
    assert rig.hub.frames == []  # open: nothing estimated goes out
    rig.clock.advance(1.0)
    rig.topic.tick()
    assert rig.hub.frames == []  # its end is not yet 500 ms past
    rig.clock.advance(2.0)
    rig.topic.tick()
    items = [i for _, body, _ in rig.hub.frames for i in body["liquidations"]]
    assert sum(i["cluster_size"] for i in items) == 5 and len(items) <= 2  # one per side
    assert "estimated" not in json.dumps([body for _, body, _ in rig.hub.frames])
    check_schema(SCHEMA, rig.hub.frames[-1][1], "clustered d")


async def test_replayed_push_is_not_delivered_twice() -> None:
    rig = Rig()
    rig.sub()
    await rig.feed(*BURST[:8])
    sent = sum(len(b["liquidations"]) for _, b, _ in rig.hub.frames)
    rig.clock.advance(1.0)
    await rig.feed(BURST[8])  # push 2 again, after a reconnect
    assert sum(len(b["liquidations"]) for _, b, _ in rig.hub.frames) == sent == 19
    assert len(rig.store) == 19


async def test_snapshot_is_last_items_oldest_first_with_note_and_options() -> None:
    rig = Rig()
    await rig.feed(*BURST[:8])
    snap = rig.topic.build(rig.sub())
    check_schema(SCHEMA, snap, "liquidations snapshot")
    ts = [i["ts_ms"] for i in snap["liquidations"]]
    assert ts == sorted(ts) and len(ts) == 19 and snap["note"] == LIQUIDATION_NOTE
    rich = rig.topic.build(rig.sub(min_notional_usd="40000"))
    assert all(float(i["notional_usd"]) >= 40000 for i in rich["liquidations"])
    batched = rig.topic.build(rig.sub("liquidations", symbols=["BTCUSDT", "ETHUSDT"]))
    assert len(batched["liquidations"]) == 19
    assert rig.topic.build(Sub("liquidations.BTCUSDT", {}, "r"))["liquidations"] == []
    assert rig.topic.generation(rig.sub()) > 0 and not rig.topic.continuity(rig.sub(), None)


async def test_batched_topic_and_option_groups_get_their_own_frames() -> None:
    rig = Rig()
    plain, rich = rig.sub(), rig.sub(min_notional_usd="40000")
    batched = rig.sub("liquidations", symbols=["BTCUSDT"])
    await rig.feed(BURST[1])
    by_sub = {id(s): body for _, body, to in rig.hub.frames for s in to}
    assert len(by_sub[id(plain)]["liquidations"]) == 3 == len(by_sub[id(batched)]["liquidations"])
    assert all(float(i["notional_usd"]) >= 40000 for i in by_sub.get(id(rich), {}).get(
        "liquidations", []))  # fmt: skip


async def test_lost_bus_items_resnapshot_live_subscriptions() -> None:
    rig = Rig()
    rig.sub()
    rig.topic.offer(StreamInvalidated(topic="live.md.BTCUSDT.liquidation", ts_event=T0_US))
    assert rig.hub.resnaps == 1


def test_41_symbols_count_on_the_sub_cap_metric() -> None:
    before = deriv_metrics.deriv_sub_cap_rejected_total._value.get()
    many = {"ch": "liquidations", "opts": {"symbols": [f"S{k}USDT" for k in range(41)]}}
    note_cap_refusal(many, "liquidations", "invalid_options", "symbols")
    forty = {"ch": "liquidations", "opts": {"symbols": [f"S{k}USDT" for k in range(40)]}}
    note_cap_refusal(forty, "liquidations", "invalid_options", "symbols")
    note_cap_refusal(many, "ticker", "invalid_options", "symbols")
    assert deriv_metrics.deriv_sub_cap_rejected_total._value.get() == before + 1


def _cascade_push(k: int, n: int) -> str:
    """A docs-shaped push of `n` prints, 500 ms after the last (the venue's cadence)."""
    ts = T0_US // 1000 + k * 500
    rows = [{"T": ts - 499 + j % 499, "s": "BTCUSDT", "S": ("Buy", "Sell")[j % 2],
             "v": f"0.{j + 1:03d}", "p": f"{63000 + k}.{j % 10}"} for j in range(n)]  # fmt: skip
    return json.dumps({"topic": "allLiquidation.BTCUSDT", "type": "snapshot", "ts": ts,
                       "data": rows})  # fmt: skip


async def test_liquidation_cascade_500_per_s_no_loss_inside_the_throttle_lag_under_1s() -> None:
    rig = Rig()
    rig.sub()
    for k in range(20):  # 10 s at two pushes a second, 250 prints each: 500 prints/s
        rig.clock.advance(0.5)
        await rig.feed(_cascade_push(k, 250))
        assert deriv_metrics.deriv_liquidation_ingest_lag_seconds._value.get() < 1.0
    rig.clock.advance(0.5)
    rig.topic.tick()
    assert len(rig.store) == 5000  # socket -> table: nothing lost
    assert sum(len(b["liquidations"]) for _, b, _ in rig.hub.frames) == 5000
    assert len(rig.hub.frames) <= 21  # at most one frame per 500 ms window


async def test_topic_bounds_shed_a_new_symbol_and_resnap_on_a_full_pending_list() -> None:
    rig = Rig()
    rig.topic._max, rig.topic._pending_max = 1, 2
    rig.sub()
    other = json.loads(BURST[0]) | {"topic": "allLiquidation.ETHUSDT"}
    other["data"] = [row | {"s": "ETHUSDT"} for row in other["data"]]
    rig.stream.acquire("c", "ETHUSDT")
    await rig.feed(BURST[1], json.dumps(other))  # three prints into a pending list of two
    assert set(rig.topic._symbols) == {"BTCUSDT"} and rig.hub.resnaps == 1
    assert len(rig.store) == 4  # the store never sheds: the topic is only a view


async def test_topic_contains_a_failing_publish_and_resync() -> None:
    rig = Rig()
    rig.sub()

    def boom(*a: Any, **k: Any) -> int:
        raise RuntimeError("socket gone")

    rig.topic._publish = boom
    assert await rig.feed(BURST[0]) == 0 and rig.hub.resnaps == 1
    rig.topic._resnapshot = boom
    rig.topic.offer(StreamInvalidated(topic="live.md.BTCUSDT.liquidation", ts_event=T0_US))


async def test_topic_drops_a_clusterer_once_no_subscription_uses_its_window() -> None:
    rig = Rig()
    clustered = rig.sub(cluster_window_ms=1000)
    rig.sub("liquidations.ETHUSDT")  # served, but no print yet: nothing to cluster
    await rig.feed(BURST[3])
    assert ("BTCUSDT", 1000) in rig.topic._clusterers
    rig.hub.subs.remove(clustered)
    rig.clock.advance(1.0)
    await rig.feed(BURST[4])
    assert ("BTCUSDT", 1000) not in rig.topic._clusterers
    assert options_of({"min_notional_usd": "n/a"}).min_notional is None


async def test_topic_runs_on_its_own_task_and_stops_cleanly() -> None:
    rig = Rig()
    rig.sub()
    sent = asyncio.Event()
    publish = rig.hub.publish

    def spy(*a: Any, **k: Any) -> int:
        sent.set()
        return publish(*a, **k)

    rig.topic._publish, rig.topic._window_s = spy, 0.01
    rig.topic.start()
    await rig.stream.handle_frame(BURST[0])
    await asyncio.wait_for(sent.wait(), 5)
    await rig.topic.stop()
    assert rig.topic._sub is None and rig.topic._task is None


async def test_topic_turn_failure_resyncs_and_waits_one_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Rig()
    waited = asyncio.Event()

    def tick() -> int:
        raise RuntimeError("bad turn")

    async def sleep(s: float) -> None:
        waited.set()
        rig.topic._sub = None  # end the loop after this turn

    monkeypatch.setattr(rig.topic, "tick", tick)
    rig.topic._sleep, rig.topic._window_s = sleep, 0.01
    await rig.topic._run()
    assert waited.is_set() and rig.hub.resnaps == 1

    async def fail() -> None:
        raise RuntimeError("dead")

    task = asyncio.ensure_future(fail())
    await asyncio.gather(task, return_exceptions=True)
    _stopped(task)  # logs, never raises
