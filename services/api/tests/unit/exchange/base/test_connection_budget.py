"""G-8b (#3963): the one per-IP WebSocket connection budget (24 §14.2 rule 13; C-12.7, OM-D07).

Every socket the process dials draws on one sliding window: 480 opens in any 300 s, public opens
stopping 60 short of it so private streams can always reconnect, and `testApiKey`'s key probe
counted inside it at most 10 per window, never in the reserve and never queued (SR-E27-05,
KV-D01). An open counts only against the windows that hold it, so opens a lane booked ahead
never take the private reserve now, and a lane books at most one window ahead, refusing past it,
so the budget stays bounded (CR-G8B-A-01, C-2.18). Time is a fake monotonic clock; no sleeps.
"""

from __future__ import annotations

import bisect
import contextlib
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.exchange.base.errors import RateBudgetExceededError
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


#: A small budget, so a run fills it, books ahead and meets the one-window horizon often. Whole
#: seconds keep every time exact, so the reading below may walk them one by one.
S_LIMIT, S_RESERVE, S_PROBES, S_WINDOW = 8, 2, 2, 10
S_CAPS = {"public": S_LIMIT - S_RESERVE, "private": S_LIMIT}

Ops = list[tuple[str, int, int]]
#: A lane (or the probe), how far the clock moves first, and how many opens it asks for at once:
#: a burst of public ones books the lane ahead, past what one window holds.
OPS = st.lists(
    st.tuples(
        st.sampled_from(["public", "private", "probe"]),
        st.integers(min_value=0, max_value=S_WINDOW + 2),
        st.integers(min_value=1, max_value=S_LIMIT),
    ),
    min_size=1,
    max_size=50,
)


def _held(times: list[int], end: int) -> int:
    """How many of the sorted `times` lie in the window `(end - S_WINDOW, end]`."""
    return bisect.bisect_right(times, end) - bisect.bisect_right(times, end - S_WINDOW)


def _load(times: list[int], at: int) -> int:
    """The most opens any window holding `at` holds: every whole second such a window ends at."""
    return max(_held(times, end) for end in range(at, at + S_WINDOW))


def _slot(times: list[int], cap: int, now: int) -> int | None:
    """The first whole second from `now` to one window ahead at which one more open leaves every
    window holding it within `cap`, trying each second in turn."""
    return next((s for s in range(now, now + S_WINDOW + 1) if _load(times, s) < cap), None)


@settings(max_examples=100, deadline=None)
@given(OPS)
def test_every_open_goes_where_a_second_by_second_reading_of_the_windows_puts_it(
    ops: Ops,
) -> None:
    """C-12.7 and CR-G8B-A-01, against a reading that walks every second: a lane's open goes at
    the first second, from now to one window ahead, at which every window holding it stays within
    the lane's cap (public 6 of 8, private all 8), and is refused with nothing booked when there
    is none; a probe goes now or never. So `remaining` is what the fullest window holding now
    leaves, public opens booked ahead never take the private reserve now, no window ever holds
    more than the limit, the public cap or the probe cap, and at most two windows are kept."""
    clock = Clock()
    budget = ConnectionBudget(
        clock,
        limit=S_LIMIT,
        window_s=float(S_WINDOW),
        private_reserve=S_RESERVE,
        probe_cap=S_PROBES,
    )
    now = 0
    opens: list[int] = []
    publics: list[int] = []
    others: list[int] = []  # private and probe opens
    probes: list[int] = []
    for lane, advance, count in ops:
        now += advance
        clock.now = float(now)
        for _ in range(count):
            if lane == "probe":
                recent = len(probes) - bisect.bisect_right(probes, now - S_WINDOW)
                fits = recent < S_PROBES and _load(opens, now) < S_CAPS["public"]
                assert budget.admit_probe() is fits
                if fits:
                    for kept in (opens, others, probes):
                        bisect.insort(kept, now)
                continue
            guard = budget.lane("public" if lane == "public" else "private")
            slot = _slot(opens, S_CAPS[lane], now)
            if slot is None:
                with pytest.raises(RateBudgetExceededError):
                    guard.reserve()
                continue
            assert guard.reserve() == slot - now
            bisect.insort(opens, slot)
            bisect.insort(publics if lane == "public" else others, slot)
        load = _load(opens, now)
        recent = len(probes) - bisect.bisect_right(probes, now - S_WINDOW)
        assert budget.remaining("private") == max(0, S_LIMIT - load)
        assert budget.remaining("public") == max(0, S_CAPS["public"] - load)
        assert budget.remaining("probe") == max(0, min(S_PROBES - recent, S_CAPS["public"] - load))
        # Liveness: the public lane's opens, made now or booked ahead, leave the reserve free now.
        assert budget.remaining("private") >= S_RESERVE - _load(others, now)
        assert len(budget._opens) <= 2 * S_LIMIT
    for end in opens:  # a window holds the most just as one of its opens is made
        assert _held(opens, end) <= S_LIMIT
        assert _held(publics, end) <= S_CAPS["public"]
        assert _held(probes, end) <= S_PROBES


def test_public_opens_booked_a_window_ahead_leave_the_private_reserve_free_now() -> None:
    """CR-G8B-A-01: 420 public opens now and 60 more booked a window ahead share no window, so a
    private open now meets 420 of them at most: the private lane keeps its 60 and opens at once,
    where counting every booked open left it none and waited 299 s."""
    clock = Clock()
    budget = ConnectionBudget(clock)
    public, private = budget.lane("public"), budget.lane("private")
    assert [public.reserve() for _ in range(PUBLIC)] == [0.0] * PUBLIC
    assert [public.reserve() for _ in range(RESERVE)] == [WINDOW_S] * RESERVE
    clock.now = 1.0
    assert (private.remaining(), private.reserve()) == (RESERVE, 0.0)


def test_a_public_thrash_books_two_windows_at_most_and_refuses_the_rest() -> None:
    """C-2.18: 5,000 public opens asked at once go 420 now and 420 a window ahead; every other is
    refused with nothing booked, counted under its lane, so the budget keeps two windows at most
    and the private lane still has its 60."""
    refused = ws_conn_budget_refused_total.labels(scope="public")
    before = refused._value.get()
    budget = ConnectionBudget(Clock())
    public = budget.lane("public")
    delays: list[float] = []
    for _ in range(5_000):
        with contextlib.suppress(RateBudgetExceededError):
            delays.append(public.reserve())
    assert delays == [0.0] * PUBLIC + [WINDOW_S] * PUBLIC
    assert refused._value.get() == before + 5_000 - 2 * PUBLIC
    assert len(budget._opens) == 2 * PUBLIC <= 2 * LIMIT
    assert budget.lane("private").remaining() == RESERVE
    with pytest.raises(RateBudgetExceededError) as more:
        public.reserve()
    assert more.value.retryable and more.value.__cause__ is None
    assert more.value.__context__ is None


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


def test_the_probe_is_refused_at_once_past_its_cap() -> None:
    """SR-E27-05: the 11th probe in 300 s is refused and takes nothing from the window."""
    clock = Clock()
    budget = ConnectionBudget(clock)
    assert [budget.admit_probe() for _ in range(PROBES + 1)] == [True] * PROBES + [False]
    assert budget.remaining("private") == LIMIT - PROBES  # the probes' opens count in it
    clock.now = WINDOW_S  # they leave the window
    assert budget.admit_probe()


def test_the_probe_is_refused_at_once_inside_the_reserve() -> None:
    """KV-D01: while only the private reserve is left, a probe is refused and takes nothing."""
    budget = ConnectionBudget(Clock())
    for _ in range(PUBLIC):
        budget.lane("public").reserve()
    assert (budget.admit_probe(), budget.remaining("probe")) == (False, 0)
    assert budget.lane("private").remaining() == RESERVE


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


def test_a_reading_refreshes_what_the_budget_publishes() -> None:
    """The gauge follows the window when nothing opens: a lane's `remaining` publishes too."""
    clock = Clock()
    budget = ConnectionBudget(clock)
    budget.lane("public").reserve()
    clock.now = WINDOW_S  # the open leaves the window
    assert budget.lane("private").remaining() == LIMIT
    assert ws_conn_budget_remaining.labels(scope="public")._value.get() == PUBLIC


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
