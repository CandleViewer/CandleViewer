"""SR-193 (#2293): one connection's rebuild budget (`ws/rebuild_budget.py`, `23-ws-protocol.md`
§7.5): two limits, one sliding window, refusals that record nothing, bounded keys; and the limit of
its user, which all of the user's connections share (#3476)."""

from __future__ import annotations

import uuid
from typing import cast

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from candleviewer.observability.metrics import CollectorRegistry
from candleviewer.ws.limits import (
    MAX_SUBSCRIPTIONS,
    REBUILD_MAX_PER_CONNECTION,
    REBUILD_MAX_PER_TOPIC,
    REBUILD_MAX_PER_USER,
    REBUILD_WINDOW_S,
)
from candleviewer.ws.metrics import export_ws_metrics
from candleviewer.ws.rebuild_budget import Key, RebuildBudget, RebuildPath, UserRebuilds, topic_key
from candleviewer.ws.topics import parse_topic
from tests.unit.ws._seq_support import USER, Clock

LIVE: Key = ("book.BTCUSDT.50", None)
RS = "bb000000-0000-4000-8000-000000000001"


def _budget(
    per_topic: int = REBUILD_MAX_PER_TOPIC, per_connection: int = REBUILD_MAX_PER_CONNECTION
) -> tuple[RebuildBudget, Clock]:
    clock = Clock()
    return RebuildBudget(clock, per_topic=per_topic, per_connection=per_connection), clock


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
    """All nine series are served on the scraped registry, bound at import."""
    scraped = CollectorRegistry()
    export_ws_metrics(scraped, env="demo")
    series = {
        (s.labels["kind"], s.labels["cause"])
        for family in scraped.collect()
        for s in family.samples
        if s.name == "cv_ws_rebuild_refused_total"
    }
    causes = ("topic", "connection", "user")
    assert series == {(p, s) for p in ("resync", "ctl", "sub") for s in causes}


def test_a_user_s_connections_together_draw_at_most_its_limit_until_the_window_slides() -> None:
    """#3476 (§7.5, §16.2), the real limits: four connections of one user spend its 1 600; a fifth's
    first draw is refused for the user on every path, and passes once the draws are a window old."""
    users, clock = UserRebuilds(), Clock()
    budgets = [RebuildBudget(clock, user=(users, USER)) for _ in range(5)]
    for budget in budgets[:4]:  # 400 each, all at t = 0 but the very last, at t = 1
        for i in range(REBUILD_MAX_PER_CONNECTION - 1):
            assert budget.take((f"trades.S{i:03d}USDT", None), ("resync", "ctl")[i % 2]) is None
        clock.now = 1.0 if budget is budgets[3] else 0.0
        assert budget.refusal(LIVE, "sub") is None
        budget.hold()  # a `sub` start: its user's draw is held, then drawn
        budget.draw(LIVE, "sub", held=True)
    fifth = budgets[4]
    assert [fifth.refusal(LIVE, path) for path in ("resync", "ctl", "sub")] == ["user"] * 3
    assert (fifth.take(LIVE, "ctl"), fifth.drawn(LIVE)) == ("user", 0)  # it records nothing
    clock.now = REBUILD_WINDOW_S - 1e-9
    assert fifth.take(LIVE, "resync") == "user"
    clock.now = REBUILD_WINDOW_S  # the draws of t = 0 are a full window old (exclusive edge)
    assert fifth.take(LIVE, "resync") is None
    assert REBUILD_MAX_PER_USER == 4 * REBUILD_MAX_PER_CONNECTION == 1600  # never from C


_SHARED = st.tuples(
    st.integers(0, 2),
    st.integers(0, 5),
    st.sampled_from([*_ACTS, "start", "end"]),
    st.sampled_from([0.0, 0.5, 20.0, 60.0]),
)


Step = tuple[int, int, str | None, float]
_FILL: list[Step] = [(1, k, "ctl", 0.0) for k in range(1, 5)]  # connection 1 spends 4 of the 6
# A held `sub` refuses another connection's draw for the user, which its start then spends.
_HOLD: list[Step] = [(0, 0, "sub", 0.0), *_FILL, (2, 0, "resync", 0.0), (2, 1, "resync", 0.0)]
_HOLD += [(0, 0, "start", 0.0), (2, 2, "ctl", 0.5)]
# The topic's limit and the user's both refuse, then the connection's and the user's.
_BOTH: list[Step] = [(0, 0, "ctl", 0.0), (0, 0, "ctl", 0.0), *_FILL, (0, 0, "ctl", 0.0)]
_BOTH += [(1, 5, "ctl", 0.0), (2, 0, "sub", 0.0)]


@settings(max_examples=300, deadline=None, derandomize=True)
@given(steps=st.lists(_SHARED, max_size=80))
@example(steps=_HOLD)
@example(steps=_BOTH)
def test_three_connections_of_one_user_match_a_naive_model(steps: list[Step]) -> None:
    """#3476: three budgets share a user limit of 6 (2 per topic, 4 per connection). A `sub` holds
    one of its user's draws from its check until it starts (`draw`, held) or ends (`unhold`),
    across the others' steps. Same answers as a naive model, which checks topic, connection, then
    user, and never more than 6 draws plus holds in the window."""
    users, clock = UserRebuilds(6), Clock()
    shared = (users, USER)
    budgets = [RebuildBudget(clock, per_topic=2, per_connection=4, user=shared) for _ in "abc"]
    drawn: list[list[tuple[float, int]]] = [[], [], []]  # each connection's topic draws
    every: list[list[float]] = [[], [], []]  # each connection's draws
    released: list[dict[int, float]] = [{}, {}, {}]
    stamps: list[float] = []  # the user's
    pending: dict[int, int] = {}  # a connection's held `sub`: its key
    for b, k, act, dt in steps:
        clock.now += dt
        window, budget = clock.now - REBUILD_WINDOW_S, budgets[b]
        if act is None:
            budget.released(_KEYS[k])
            released[b][k] = clock.now
        elif act == "end" and b in pending:
            del pending[b]
            budget.unhold()
        elif act == "start" and b in pending:
            started = pending.pop(b)
            budget.draw(_KEYS[started], "sub", held=True)
            every[b].append(clock.now)
            stamps.append(clock.now)
            if released[b].get(started, window) > window:
                drawn[b].append((clock.now, started))
        elif act in ("resync", "ctl") or (act == "sub" and b not in pending):
            path = cast("RebuildPath", act)
            mine = path != "sub" or released[b].get(k, window) > window
            topic = mine and len([t for t, i in drawn[b] if i == k and t > window]) >= 2
            spent = len([t for t in every[b] if t > window]) >= 4
            user = len([t for t in stamps if t > window]) + len(pending) >= 6
            want = "topic" if topic else "connection" if spent else "user" if user else None
            if path == "sub":
                assert budget.refusal(_KEYS[k], path) == want
                if want is None:
                    budget.hold()
                    pending[b] = k
            else:
                assert budget.take(_KEYS[k], path) == want
                if want is None:
                    every[b].append(clock.now)
                    stamps.append(clock.now)
                    drawn[b].append((clock.now, k))
        held = len([t for t in stamps if t > window]) + len(pending)
        assert held <= 6 and users.spent(USER, clock.now) is (held >= 6)


def test_users_stay_bounded_by_the_window() -> None:
    """C-2.18: a user is kept while it has a draw in the window (in the order of its newest), and
    each keeps at most its limit of stamps."""
    users, first = UserRebuilds(), uuid.UUID(int=0)
    for i in range(10_000):  # a new user draws every 1/64 s for 156 s, and so does the first
        now, user = i / 64, uuid.UUID(int=i)
        users.stamp(user, now)
        users.stamp(first, now)
        assert users.first_refusal(user, now)
        assert len(users._stamps) == min(i + 1, 3840) + (i >= 3840)  # 3 840 = 64 x 60 s
        assert len(users._audited) == min(i + 1, 3840)
    assert users._stamps[user].maxlen == REBUILD_MAX_PER_USER


def test_a_user_s_first_user_refusal_in_a_window_is_the_one_audited() -> None:
    """#3476: one record per user per window, the first `user` refusal's; users are apart."""
    users, a, b = UserRebuilds(), uuid.UUID(int=1), uuid.UUID(int=2)
    steps = [(a, 0.0), (a, 59.9), (b, 59.9), (a, 60.0), (b, 60.0)]
    assert [users.first_refusal(u, t) for u, t in steps] == [True, False, True, True, False]


def test_clock_values_out_of_order_never_break_the_shared_window() -> None:
    """#3476: a user whose draws all leave the window is forgotten at once, so the sweep never meets
    an empty window, whatever the order of the clock values it is given."""
    users, x, y, z = UserRebuilds(), uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=3)
    users.stamp(x, 100.0)
    users.stamp(y, 90.0)
    assert not users.spent(y, 155.0) and not users.spent(z, 161.0)
    users.stamp(z, 162.0)
    assert list(users._stamps) == [z]
