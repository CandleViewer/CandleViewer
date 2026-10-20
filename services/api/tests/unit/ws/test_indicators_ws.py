"""`ws/indicators_publish.py` and `ws/indicators_source.py` in isolation (E13-T02, #426;
`23-ws-protocol.md` §6.1, §7.2, §14.10); the socket-level contract is in
`tests/contract/ws/test_ws_indicators_contract.py`."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

import pytest

from candleviewer.bars.models import BarSpec
from candleviewer.bars.series_store import SeriesStore
from candleviewer.orderflow.indicators.engine import IndicatorEngine, resolve_instances
from candleviewer.ws.indicators_publish import IndicatorsPublisher, topic_head, wire_value
from candleviewer.ws.indicators_source import IndicatorsSnapshotSource
from candleviewer.ws.permissions import ConnectionAuthz, Subscription, SubscriptionServices
from candleviewer.ws.sequencing import SequencingHub, TopicEmitter
from candleviewer.ws.topics import FAMILIES, parse_topic
from candleviewer.ws.upstream import UpstreamRefs
from tests.unit.orderflow.indicators._engine import EMA3, M1, SYM, close, wave
from tests.unit.ws._seq_support import principal, validate


@pytest.mark.parametrize(
    ("x", "wire"),
    [
        (None, None),
        (math.nan, None),
        (math.inf, None),
        (-math.inf, None),
        (0.0, "0"),
        (-0.0, "0"),
        (21.0, "21"),
        (123.456, "123.456"),
        (-2.5, "-2.5"),
        (1e-7, "0.0000001"),
        (1e22, "10000000000000000000000"),
        (0.1 + 0.2, "0.30000000000000004"),
    ],
)
def test_a_value_is_its_shortest_round_trip_digits_in_plain_form(
    x: float | None, wire: str | None
) -> None:
    """§14.10: parsed with `float()` it is the same float64; no exponent; `-0` is `0`."""
    assert wire_value(x) == wire
    if wire is not None and x is not None:
        assert float(wire) == x


def _sub(ch: str, *, replay: str | None = None, history: int | None = None) -> Subscription:
    topic = parse_topic(ch)
    effective: dict[str, object] = {"instances": [r.echo() for r in resolve_instances(EMA3, M1)]}
    if history is not None:
        effective["history"] = history
    return Subscription("s_01", topic, {}, effective, replay_session_id=replay)


async def test_the_source_waits_for_an_instance_and_discloses_a_quarantine() -> None:
    store = SeriesStore()
    _hold = await store.ensure(SYM, M1)
    engine = IndicatorEngine(store)
    quarantined: set[tuple[str, str]] = set()
    source = IndicatorsSnapshotSource(engine, stale=lambda s, h: (s, h) in quarantined)
    sub = _sub("indicators.BTCUSDT.time.1", history=2)
    assert source.build(sub) is None  # no instance yet: the subscription stays pending
    resolved = resolve_instances(EMA3, M1)
    engine.admit(SYM, M1, resolved, "c1", "u1", history=500)
    for k in range(4):
        await close(store, engine, wave(k))
    body = source.build(sub)
    assert body is not None and not body.stale
    ((instance,),) = [body.structured["instances"]]
    assert [p["index"] for p in instance["points"]] == [2, 3]
    version = source.generation(sub)
    assert version == engine.version(SYM, M1.spec_hash) > 0
    quarantined.add((SYM, M1.spec_hash))
    stale = source.build(sub)
    assert stale is not None and stale.stale and source.generation(sub) == -version
    assert source.continuity(sub, None) is False
    replay = _sub("indicators.BTCUSDT.time.1", replay="bb000000-0000-4000-8000-000000000001")
    assert source.build(replay) is None and source.generation(replay) == 0
    unbuildable = replace(sub, topic=replace(sub.topic, bar_type="nope"))
    assert source.build(unbuildable) is None and source.generation(unbuildable) == 0


async def test_each_group_of_subscribers_gets_exactly_its_own_instances() -> None:
    """Two connections on one channel name different instances: each `d` of a close carries a
    subscriber's own instances, and validates against §14.10."""
    store, hub = SeriesStore(), SequencingHub()
    _hold = await store.ensure(SYM, M1)
    engine = IndicatorEngine(store)
    engine.listen(IndicatorsPublisher(hub))
    source = IndicatorsSnapshotSource(engine)
    pair = [*EMA3, {"indicator": "atr", "params": {"n": 2}}]
    outs: list[list[dict[str, Any]]] = []
    for n, instances in enumerate((EMA3, pair)):
        out: list[dict[str, Any]] = []
        services = SubscriptionServices(upstream=UpstreamRefs(), snapshots=source)
        authz = ConnectionAuthz(principal(), services)
        emitter = TopicEmitter(
            lambda f, out=out: (validate(f), out.append(f)),
            connection_id=f"c{n}", wall_ms=lambda: 1, clock=lambda: 0.0, source=source,
        )  # fmt: skip
        hub.register(authz, emitter)
        entry = {"ch": "indicators.BTCUSDT.time.1", "opts": {"instances": instances}}
        _, sub = authz.admit(entry)
        assert sub is not None
        resolved = resolve_instances(instances, M1)
        sub.effective["instances"] = [r.echo() for r in resolved]  # as `subscribe_upstream` sets
        engine.admit(SYM, M1, resolved, f"c{n}", "u1", history=500)
        sub.announced, sub.snapshot_pending = True, False
        outs.append(out)
    await close(store, engine, wave(0))
    one, two = (out[-1]["p"]["instances"] for out in outs)
    assert [i["indicator"] for i in one] == ["ema"]
    assert [i["indicator"] for i in two] == ["ema", "atr"]
    assert FAMILIES["indicators"].binary is False  # structured only: never a CVWB part


def test_a_series_no_topic_can_name_is_neither_published_nor_re_snapshotted() -> None:
    """A spec with no wire form (here a 7 s interval) has no `indicators.*` channel: the
    listener's three calls do nothing for it, as `bars_publish` does for its own."""
    hub = SequencingHub()
    publisher = IndicatorsPublisher(hub)
    odd = BarSpec(kind="time", interval_ms=7_000)
    assert topic_head(SYM, odd) is None
    publisher.points(SYM, odd, {})
    publisher.resnapshot(SYM, odd, "generation_swap")
    publisher.ready(SYM, odd)
    assert topic_head(SYM, M1) == (
        "indicators.BTCUSDT.time.1",
        {"symbol": SYM, "bar_type": "time", "param": "1"},
    )
