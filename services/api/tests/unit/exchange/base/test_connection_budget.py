"""G-8b (#3963): the one per-IP WebSocket connection budget (24 §14.2 rule 13; C-12.7, OM-D07).

Every socket the process dials draws on one sliding window: 480 opens in any 300 s, public opens
stopping 60 short of it so private streams can always reconnect, and `testApiKey`'s key probe
counted inside it at most 10 per window, never in the reserve and never queued (SR-E27-05,
KV-D01). Time is a fake monotonic clock; no sleeps.
"""

from __future__ import annotations

import bisect
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.exchange.base.reconnect import (
    ConnectionBudget,
    ConnectionGuard,
    ws_conn_budget_refused_total,
    ws_conn_budget_remaining,
)
from candleviewer.ingestion.reconnect import ConnectionRateGuard, ReconnectPolicy

LIMIT, WINDOW_S, RESERVE, PROBES = 480, 300.0, 60, 10
PUBLIC = LIMIT - RESERVE


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


def _in_window(times: list[float], end: float) -> int:
    """How many of the sorted `times` fall in the window `(end - 300 s, end]`."""
    return bisect.bisect_right(times, end) - bisect.bisect_right(times, end - WINDOW_S)


Ops = list[tuple[str, float]]
#: What a run does: a lane (or the probe) and how far the clock moves first, in whole seconds so
#: the windows' edges are exact (`x + 300 - 300 == x`).
OPS = st.lists(
    st.tuples(
        st.sampled_from(["public", "private", "probe"]),
        st.one_of(st.just(0.0), st.integers(min_value=0, max_value=45).map(float)),
    ),
    min_size=1,
    max_size=700,
)


@settings(max_examples=60, deadline=None)
@given(OPS)
def test_no_window_ever_holds_more_opens_than_the_budget_allows(ops: Ops) -> None:
    """C-12.7: across every lane, no 300 s ever holds more than 480 opens, public ones at most
    420 of them and probes at most 10, and every reading of `remaining` is what is left of its
    lane's cap counting every open in the window or scheduled ahead."""
    clock = Clock()
    budget = ConnectionBudget(clock)
    opens: list[float] = []
    publics: list[float] = []
    probes: list[float] = []
    for lane, advance in ops:
        clock.now += advance
        if lane == "probe":
            if budget.admit_probe():
                bisect.insort(opens, clock.now)
                probes.append(clock.now)
        else:
            delay = budget.lane("public" if lane == "public" else "private").reserve()
            assert delay >= 0.0
            bisect.insort(opens, clock.now + delay)
            if lane == "public":
                bisect.insort(publics, clock.now + delay)
        held = len(opens) - bisect.bisect_right(opens, clock.now - WINDOW_S)
        assert budget.remaining("private") == max(0, LIMIT - held)
        assert budget.remaining("public") == max(0, PUBLIC - held)
        recent = len(probes) - bisect.bisect_right(probes, clock.now - WINDOW_S)
        assert budget.remaining("probe") == max(0, min(PROBES - recent, PUBLIC - held))
    for end in opens:  # a window holds the most just as one of its opens is made
        assert _in_window(opens, end) <= LIMIT
        assert _in_window(publics, end) <= PUBLIC
        assert _in_window(probes, end) <= PROBES


def test_public_opens_leave_the_reserve_to_private_ones() -> None:
    clock = Clock()
    budget = ConnectionBudget(clock)
    public, private = budget.lane("public"), budget.lane("private")
    assert [public.reserve() for _ in range(PUBLIC)] == [0.0] * PUBLIC
    assert (public.remaining(), private.remaining()) == (0, RESERVE)
    assert [private.reserve() for _ in range(RESERVE)] == [0.0] * RESERVE
    assert (private.remaining(), budget.remaining("probe")) == (0, 0)
    # Full: the next open of either lane waits for the first ones to leave the window.
    assert (private.reserve(), public.reserve()) == (WINDOW_S, WINDOW_S)
    clock.now = WINDOW_S  # the first 480 have left; the two scheduled for now are in it
    assert (private.remaining(), public.remaining()) == (LIMIT - 2, PUBLIC - 2)


def test_a_lane_is_the_same_view_each_time() -> None:
    budget = ConnectionBudget(Clock())
    assert budget.lane("public") is budget.lane("public")
    assert budget.lane("public") is not budget.lane("private")


def test_the_probe_is_refused_at_once_past_its_cap_or_inside_the_reserve() -> None:
    """SR-E27-05 and KV-D01: the 11th probe in 300 s is refused, and so is any probe while only
    the private reserve is left; a refusal takes nothing from the window."""
    clock = Clock()
    budget = ConnectionBudget(clock)
    assert [budget.admit_probe() for _ in range(PROBES + 1)] == [True] * PROBES + [False]
    assert budget.remaining("private") == LIMIT - PROBES  # the probes' opens count in it
    clock.now = WINDOW_S  # they leave the window
    assert budget.admit_probe()

    crowded = ConnectionBudget(Clock())
    for _ in range(PUBLIC):
        crowded.lane("public").reserve()
    assert (crowded.admit_probe(), crowded.remaining("probe")) == (False, 0)
    assert crowded.lane("private").remaining() == RESERVE


def test_the_budget_publishes_what_is_left_and_counts_a_refused_probe() -> None:
    """24 §14.2 rule 9: `ws_conn_budget_remaining{scope}` after each open, and a refused probe
    counted in `ws_conn_budget_refused_total{scope="probe"}` (no account or key label)."""
    refused = ws_conn_budget_refused_total.labels(scope="probe")
    before = refused._value.get()
    budget = ConnectionBudget(Clock())
    budget.lane("private").reserve()
    left = {s: ws_conn_budget_remaining.labels(scope=s)._value.get() for s in ("public", "private")}
    assert left == {"public": PUBLIC - 1, "private": LIMIT - 1}
    for _ in range(PROBES + 1):
        budget.admit_probe()
    assert refused._value.get() == before + 1
    assert ws_conn_budget_remaining.labels(scope="probe")._value.get() == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"private_reserve": LIMIT},
        {"private_reserve": -1},
        {"probe_cap": 0},
        {"window_s": 0.0},
    ],
)
def test_a_budget_refuses_a_shape_it_cannot_keep(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match=r"positive|limit"):
        ConnectionBudget(Clock(), **kwargs)


def _waits(guard: ConnectionGuard) -> float:
    """What B13's `open_socket` does with any guard: reserve, then wait out the delay."""
    return guard.reserve()


def test_the_ingestion_guard_and_a_budget_lane_are_both_connection_guards() -> None:
    clock = Clock()
    assert _waits(ConnectionRateGuard(clock)) == 0.0
    assert _waits(ConnectionBudget(clock).lane("private")) == 0.0


def test_ingestion_still_reexports_the_reconnect_policy() -> None:
    from candleviewer.exchange.base import reconnect

    assert ReconnectPolicy is reconnect.ReconnectPolicy


def test_the_public_stream_draws_on_the_adapters_public_lane() -> None:
    """The composition root gives the public stream the adapter's one budget, not a window of
    its own, so public reconnects and private streams share the venue's count (OM-D07)."""
    from candleviewer.app import build_app_context, wire_public_ws

    ctx = build_app_context()
    manager = wire_public_ws(ctx)
    assert manager._guard is ctx.exchange_bybit.ws_connection_budget.lane("public")
