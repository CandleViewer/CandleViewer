"""SR-193 (#2293): one connection's rebuild budget (`ws/rebuild_budget.py`, `23-ws-protocol.md`
§7.5): two limits, one sliding window, refusals that record nothing, bounded keys."""

from __future__ import annotations

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from candleviewer.observability.metrics import CollectorRegistry
from candleviewer.ws.limits import (
    MAX_SUBSCRIPTIONS,
    REBUILD_MAX_PER_CONNECTION,
    REBUILD_MAX_PER_TOPIC,
    REBUILD_WINDOW_S,
)
from candleviewer.ws.metrics import export_ws_metrics
from candleviewer.ws.rebuild_budget import Key, RebuildBudget, RebuildPath, topic_key
from candleviewer.ws.topics import parse_topic
from tests.unit.ws._seq_support import Clock

LIVE: Key = ("book.BTCUSDT.50", None)
RS = "bb000000-0000-4000-8000-000000000001"


def _budget(**limits: int) -> tuple[RebuildBudget, Clock]:
    clock = Clock()
    return RebuildBudget(clock, **limits), clock


def test_rebuild_budget_sixth_draw_of_a_topic_is_refused_until_the_first_is_a_window_old() -> None:
    budget, clock = _budget()
    for i in range(REBUILD_MAX_PER_TOPIC):
        clock.now = float(i)
        assert budget.take(LIVE, ("resync", "ctl")[i % 2]) is None
    for i in range(REBUILD_MAX_PER_TOPIC, 60):  # asking again and again does not lengthen the wait
        clock.now = float(i)
        assert budget.take(LIVE, "resync") == "topic"
    assert [budget.drawn(LIVE, path) for path in (None, "resync", "ctl")] == [5, 3, 2]
    assert budget.take(("book.BTCUSDT.50", RS), "resync") is None  # a replay key is its own
    clock.now = REBUILD_WINDOW_S - 1e-9
    assert budget.take(LIVE, "ctl") == "topic"
    clock.now = REBUILD_WINDOW_S  # the stamp of t = 0 is a full window old: gone (exclusive edge)
    assert (budget.take(LIVE, "ctl"), budget.drawn(LIVE, "resync")) == (None, 2)


def test_rebuild_budget_four_hundred_and_first_draw_is_refused_for_the_connection() -> None:
    budget, clock = _budget()
    for i in range(REBUILD_MAX_PER_CONNECTION - REBUILD_MAX_PER_TOPIC):
        assert budget.take((f"trades.S{i:03d}USDT", None), "ctl") is None
    for _ in range(REBUILD_MAX_PER_TOPIC):
        assert budget.take(LIVE, "resync") is None
    assert budget.take(("trades.NEWUSDT", None), "resync") == "connection"
    assert budget.take(("trades.S000USDT", None), "ctl") == "connection"  # its topic has room
    assert budget.take(LIVE, "resync") == "topic"  # both spent: the topic's limit is named
    clock.now = REBUILD_WINDOW_S
    assert budget.take(("trades.NEWUSDT", None), "resync") is None
    assert len(budget._keys) == 1  # each key whose stamps all left the window is forgotten


_KEYS: list[Key] = [(f"trades.S{i}USDT", None) for i in range(5)] + [("trades.S0USDT", RS)]

_ACTS: list[RebuildPath | None] = ["resync", "ctl", "sub", None]  # None: the topic is released
_STEP = st.tuples(
    st.integers(0, 5), st.sampled_from(_ACTS), st.sampled_from([0.0, 0.5, 20.0, 60.0])
)


@settings(max_examples=300, deadline=None, derandomize=True)
@given(steps=st.lists(_STEP, max_size=60))
# Topic 0 is drawn again after topic 1, which leaves the window first and must be forgotten.
@example(
    steps=[(0, "ctl", 0.0), (1, "ctl", 0.5), (0, "ctl", 20.0), (2, "ctl", 20.0), (3, "ctl", 20.0)]
)
def test_rebuild_budget_matches_a_naive_model(
    steps: list[tuple[int, RebuildPath | None, float]],
) -> None:
    """Against a naive model, small limits: same answers, a `sub` counting toward its topic only
    within a window of its release, and only keys with a draw in the window held (C-2.18)."""
    budget, clock = _budget(per_topic=2, per_connection=4)
    drawn: list[tuple[float, int, RebuildPath]] = []  # the topics' draws
    every: list[float] = []  # the connection's
    released: dict[int, float] = {}
    for k, path, dt in steps:
        clock.now += dt
        if path is None:
            budget.released(_KEYS[k])
            released[k] = clock.now
            continue
        window = clock.now - REBUILD_WINDOW_S
        mine = [p for t, i, p in drawn if i == k and t > window]
        topic = path != "sub" or released.get(k, window) > window
        spent = len([t for t in every if t > window]) >= 4
        want = "topic" if topic and len(mine) >= 2 else "connection" if spent else None
        assert budget.take(_KEYS[k], path) == want
        if want is None:
            every.append(clock.now)
            if topic:
                drawn.append((clock.now, k, path))
                mine.append(path)
        assert budget.drawn(_KEYS[k], "resync") == mine.count("resync")
        assert len(budget._keys) == len({i for t, i, _ in drawn if t > window}) <= 4


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("book.BTCUSDT.50", "book.BTCUSDT.050", True),
        ("bars.BTCUSDT.tick.1", "bars.BTCUSDT.tick.01", True),
        ("book.BTCUSDT.50", "book.BTCUSDT.200", False),
        ("bars.BTCUSDT.tick.1", "footprint.BTCUSDT.tick.1", False),
        (f"machines.order:{RS}.state", "machines.order:" + RS.replace("b", "c") + ".state", False),
    ],
)
def test_topic_key_pairs(a: str, b: str, same: bool) -> None:
    assert (topic_key(parse_topic(a), None) == topic_key(parse_topic(b), None)) is same
    assert topic_key(parse_topic(a), RS) != topic_key(parse_topic(a), None)
    assert topic_key(parse_topic("book.BTCUSDT.050"), None) == LIVE


def test_releases_stay_bounded_by_the_window() -> None:
    """Each release follows a start that drew, so a window keeps at most that many (C-2.18)."""
    budget, clock = _budget()
    for i in range(3000):  # a new topic started and ended every 0.05 s, for 150 s
        clock.now, key = i * 0.05, (f"trades.X{i:04d}USDT", None)
        if budget.take(key, "sub") is None:
            budget.released(key)
        assert len(budget._released) < REBUILD_MAX_PER_CONNECTION + MAX_SUBSCRIPTIONS


def test_every_refusal_series_is_bound_at_import_and_exported() -> None:
    """All six series are served on the scraped registry, bound at import."""
    scraped = CollectorRegistry()
    export_ws_metrics(scraped, env="demo")
    series = {
        (s.labels["kind"], s.labels["cause"])
        for family in scraped.collect()
        for s in family.samples
        if s.name == "cv_ws_rebuild_refused_total"
    }
    assert series == {(p, s) for p in ("resync", "ctl", "sub") for s in ("topic", "connection")}
