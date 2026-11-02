"""E21-X02 (#652; 23 §6.1, §16.2): the server's heatmap spec points in `HeatmapTopic._check`.

Beside the count caps (4 a symbol, 32 a server, E21-T02), the live specs' points (`spec_points`,
a spec's columns at its bucket) stay within `HEATMAP_MAX_POINTS_PER_SERVER`: a new spec past them is
refused `HeatmapSpecCapError` naming the budget, with nothing held; a spec already held never
re-checks; a spec's last release frees its points; and a `ctl` moving a spec frees its own points
first, as it frees its count."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from candleviewer.bus.bus import Bus
from candleviewer.orderflow.heatmap import (
    HEATMAP_MAX_POINTS_PER_SERVER,
    HEATMAP_MAX_SPECS_PER_SERVER,
    HEATMAP_MAX_SPECS_PER_SYMBOL,
    HeatmapLease,
    HeatmapSpec,
    HeatmapSpecCapError,
    HeatmapTopic,
    spec_points,
)
from candleviewer.ws.sequencing import SnapshotBody
from candleviewer.ws_wiring import heatmap_part

#: A depth-500 spec at 100 ms: the heaviest a bucket allows (512 rows, 10 a second).
HEAVY = 80
SYMBOLS = tuple(f"S{n:02d}USDT" for n in range(20))


class _Hub:
    def publish(self, ch: str, body: Any = None, **kw: Any) -> int:
        return 0

    def flush_pending(self, match: Any = None) -> int:
        return 0


def _topic(
    *,
    max_specs_per_symbol: int = HEATMAP_MAX_SPECS_PER_SYMBOL,
    max_specs_per_server: int = HEATMAP_MAX_SPECS_PER_SERVER,
    max_points_per_server: int = HEATMAP_MAX_POINTS_PER_SERVER,
) -> HeatmapTopic:
    return HeatmapTopic(
        _Hub(), engine=lambda _s: None, steps=lambda _s: (Decimal("0.1"), Decimal("0.001")),
        part=heatmap_part, body=SnapshotBody, bus=Bus(), env="live", queue_bytes=8_388_608,
        queue_frames=2_000, clock_ms=lambda: 1_700_000_000_000.0,
        max_specs_per_symbol=max_specs_per_symbol, max_specs_per_server=max_specs_per_server,
        max_points_per_server=max_points_per_server,
    )  # fmt: skip


def _heavy(n: int, grouping: int = 1) -> HeatmapSpec:
    return HeatmapSpec(SYMBOLS[n], 500, grouping, 100)


def _fill(topic: HeatmapTopic, n: int = 16) -> list[HeatmapLease]:
    """`n` heavy specs; 16 hold the whole 1 280 points, under both count caps."""
    leases = [topic.hold(f"c/{i}", _heavy(i)) for i in range(n)]
    assert topic._points == n * HEAVY
    return leases


def test_a_new_spec_past_the_server_budget_is_refused_naming_it() -> None:
    assert spec_points(_heavy(0)) == HEAVY and HEATMAP_MAX_POINTS_PER_SERVER == 1280
    topic = _topic()
    leases = _fill(topic)  # 1 280: the budget exactly, so the sixteenth was admitted at its edge
    light = HeatmapSpec(SYMBOLS[16], 50, 1, 5000)
    assert spec_points(light) == 1
    with pytest.raises(HeatmapSpecCapError, match="heatmap budget of 1280 points") as refused:
        topic.hold("c/new", light)  # one point past it, under both count caps
    assert refused.value.cap == "points" and SYMBOLS[16] not in topic._symbols  # nothing held
    topic.release(leases[-1])
    assert topic.hold("c/light", light).spec == light and topic._points == 15 * HEAVY + 1


def test_a_spec_already_held_is_shared_and_never_checked_again() -> None:
    topic = _topic(max_points_per_server=HEAVY)
    first = topic.hold("c/1", _heavy(0))
    assert topic.hold("c/2", first.spec) == HeatmapLease("c/2", first.spec)  # at the budget
    assert topic._points == HEAVY


def test_each_refusal_names_its_cap_and_the_count_caps_come_first() -> None:
    """`cap` tells the gateway which limit refused (its refusal count's reason)."""
    with pytest.raises(HeatmapSpecCapError, match="0 points") as points:
        _topic(max_points_per_server=0).hold("c/1", _heavy(0))
    assert points.value.cap == "points"
    by_symbol = _topic(max_specs_per_symbol=1, max_points_per_server=0)
    by_server = _topic(max_specs_per_server=1, max_points_per_server=0)
    for topic in (by_symbol, by_server):
        topic._max_points = HEAVY  # room for the first spec only
        topic.hold("c/1", _heavy(0))
        topic._max_points = 0  # the next is past the points too: the count cap still names it
    with pytest.raises(HeatmapSpecCapError, match="1 heatmap specs per symbol") as symbol:
        by_symbol.hold("c/2", _heavy(0, grouping=2))
    with pytest.raises(HeatmapSpecCapError, match="At most 1 heatmap specs are served") as server:
        by_server.hold("c/2", _heavy(1))
    assert (symbol.value.cap, server.value.cap) == ("symbol", "server")


def test_a_specs_last_release_frees_its_points() -> None:
    topic = _topic()
    leases = _fill(topic)
    shared = topic.hold("c/again", leases[0].spec)  # a second lease on spec 0
    topic.release(leases[0])
    with pytest.raises(HeatmapSpecCapError):
        topic.hold("c/new", _heavy(16))  # spec 0 still held: still 1 280
    topic.release(shared)  # its last lease: its points back
    assert topic._points == 15 * HEAVY
    assert topic.hold("c/new", _heavy(16)).spec == _heavy(16)
    for lease in leases[1:]:
        topic.release(lease)
    topic.release(HeatmapLease("c/new", _heavy(16)))
    assert topic._points == 0 and topic._symbols == {}


def test_a_ctl_moving_a_spec_is_checked_against_the_budget() -> None:
    topic = _topic()
    leases = _fill(topic, 15)  # 1 200
    mid = topic.hold("c/mid", HeatmapSpec(SYMBOLS[15], 200, 1, 100))  # 63: 1 263
    light = topic.hold("c/light", HeatmapSpec(SYMBOLS[16], 50, 1, 1000))  # 2: 1 265
    assert topic._points == 1265
    with pytest.raises(HeatmapSpecCapError, match="1280 points") as refused:
        topic.check_retune(light, _heavy(16))  # 80 in place of its own 2: 1 343
    assert refused.value.cap == "points" and topic._points == 1265  # nothing changed
    moved = topic.retune(leases[0], _heavy(0, grouping=2))  # its own 80 freed first: 1 265
    assert moved.spec == _heavy(0, grouping=2) and topic._points == 1265
    shared = topic.hold("c/share", _heavy(1))  # spec 1 now has two leases: a move frees nothing
    with pytest.raises(HeatmapSpecCapError):
        topic.check_retune(leases[1], _heavy(1, grouping=2))
    topic.release(shared)
    assert topic.retune(leases[1], _heavy(1, grouping=2)).spec == _heavy(1, grouping=2)
    assert topic.retune(mid, HeatmapSpec(SYMBOLS[15], 200, 1, 5000)).spec.time_bucket_ms == 5000
