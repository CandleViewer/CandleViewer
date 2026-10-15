from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.ws.binary import BOOK_DELTA, Frame
from candleviewer.ws.coalescing import MAX_PENDING_FRAMES, CoalescingQueue, Emission

Body = dict[str, Any]
State = dict[str, Any]
_LISTS = frozenset(
    {"bids", "asks", "bars", "trades", "liquidations", "dropped", "coalesced", "coalesced_count"}
)

# -- reference clients: every payload, coalesced or not, is applied the same way (§8.2) --------


def _root(state: State, body: Mapping[str, Any]) -> None:
    state.setdefault("root", {}).update((k, v) for k, v in body.items() if k not in _LISTS)


def _apply_book(state: State, body: Mapping[str, Any]) -> None:
    _root(state, body)
    for side in ("bids", "asks"):
        levels = state.setdefault(side, {})
        for price, size in body.get(side, ()):
            if Decimal(size) == 0:
                levels.pop(Decimal(price), None)
            else:
                levels[Decimal(price)] = Decimal(size)


def _apply_bars(state: State, body: Mapping[str, Any]) -> None:
    _root(state, body)
    bars = state.setdefault("bars", {})
    for item in body["bars"]:
        key = (item["generation"], item["index"])
        cur = bars.get(key)
        if cur is None or not cur["confirm"] or (item["confirm"] and item.get("amended")):
            bars[key] = item


def _append(field: str) -> Callable[..., None]:
    def apply(state: State, body: Mapping[str, Any]) -> None:
        _root(state, body)
        state.setdefault(field, []).extend(body[field])
        state["dropped"] = state.get("dropped", 0) + body.get("dropped", 0)

    return apply


# -- update generators --------------------------------------------------------------------------

_PRICE = st.sampled_from(["100", "100.0", "100.5", "101", "99.5"])
_SIZE = st.sampled_from(["0", "0.5", "1", "3.25"])
_book = st.builds(
    lambda xu, bids, asks: {"symbol": "BTCUSDT", "depth": 50, "xu": xu, "bids": bids, "asks": asks},
    st.integers(0, 9),
    st.lists(st.tuples(_PRICE, _SIZE).map(list), max_size=3),
    st.lists(st.tuples(_PRICE, _SIZE).map(list), max_size=3),
)
_bar_item = st.builds(
    lambda g, i, c, conf, am: {
        "generation": g,
        "index": i,
        "t_ms": 1000,
        "c": str(c),
        "confirm": conf,
        "amended": am,
    },
    st.integers(0, 1),
    st.integers(0, 2),
    st.integers(0, 9),
    st.booleans(),
    st.booleans(),
)
_bars = st.builds(
    lambda items: {"symbol": "BTCUSDT", "bar_type": "time", "param": "1m", "bars": items},
    st.lists(_bar_item, min_size=1, max_size=2),
)
_trades = st.builds(
    lambda ids, dropped: {
        "symbol": "BTCUSDT",
        "trades": [{"id": f"t{i}", "price": "1", "size": "1", "side": "buy"} for i in ids],
        **({"dropped": dropped} if dropped else {}),
    },
    st.lists(st.integers(0, 999), max_size=4),
    st.integers(0, 3),
)
_liquidations = st.builds(
    lambda ids, note: {
        "liquidations": [{"symbol": "BTCUSDT", "ts_ms": i, "side": "buy"} for i in ids],
        **({"note": note} if note else {}),
    },
    st.lists(st.integers(0, 999), max_size=3),
    st.sampled_from([None, "n1", "n2"]),
)

FAMILIES: list[tuple[str, Any, Callable[..., None]]] = [
    ("book", st.lists(_book, max_size=25), _apply_book),
    ("bars", st.lists(_bars, max_size=25), _apply_bars),
    ("trades", st.lists(_trades, max_size=25), _append("trades")),
    ("liquidations", st.lists(_liquidations, max_size=25), _append("liquidations")),
]


def _run(queue: CoalescingQueue, updates: list[Body], cuts: list[bool]) -> list[Emission]:
    """Offer every update, taking a frame wherever `cuts` closes a throttle window."""
    emitted: list[Emission] = []
    for update, cut in zip(updates, cuts + [False] * len(updates), strict=False):
        assert queue.offer(update)
        if cut:
            emitted += queue.take()
    return emitted + queue.take()


def _state(apply: Callable[..., None], bodies: Sequence[Mapping[str, Any]]) -> State:
    state: State = {}
    for body in bodies:
        apply(state, body)
    return {k: v for k, v in state.items() if v}  # an update that changed nothing leaves no trace


@pytest.mark.parametrize(("family", "updates", "apply"), FAMILIES, ids=[f[0] for f in FAMILIES])
def test_coalescer_state_matches_every_source_update_applied(
    family: str, updates: Any, apply: Callable[..., None]
) -> None:
    """§16.4: "coalescer produces state identical to applying every source update"."""

    @given(updates, st.lists(st.booleans(), max_size=25))
    def check(source: list[Body], cuts: list[bool]) -> None:
        pristine = copy.deepcopy(source)
        emitted = _run(CoalescingQueue(family), source, cuts)
        assert _state(apply, [e.body for e in emitted]) == _state(apply, pristine)
        assert source == pristine  # the queue never mutates its input
        assert not any("coalesced" in e.body or "coalesced_count" in e.body for e in emitted)

    check()


# -- acceptance scenarios (#412) ------------------------------------------------------------------


def test_coalescer_500_book_updates_one_window_one_lossless_frame_counted_500() -> None:
    queue = CoalescingQueue("book")
    updates = [
        {"symbol": "BTCUSDT", "xu": i, "bids": [[str(100 + i % 7), str(i % 3)]], "asks": []}
        for i in range(500)
    ]
    for update in updates:
        queue.offer(update)
    [frame] = queue.take()
    assert frame.coalesced_count == 500
    assert frame.part is None
    assert _state(_apply_book, [frame.body]) == _state(_apply_book, updates)


def test_coalescer_unconfirmed_after_confirmed_bar_keeps_confirmed() -> None:
    queue = CoalescingQueue("bars")
    bar = {"generation": 0, "index": 5, "t_ms": 36_300_000, "c": "1", "confirm": True}
    queue.offer({"symbol": "BTCUSDT", "bar_type": "time", "param": "5m", "bars": [bar]})
    late = {**bar, "c": "2", "confirm": False}
    queue.offer({"symbol": "BTCUSDT", "bar_type": "time", "param": "5m", "bars": [late]})
    [frame] = queue.take()
    assert frame.body["bars"] == [bar]


def test_coalescer_200_prints_one_window_all_in_order_unmerged() -> None:
    queue = CoalescingQueue("trades")
    prints = [{"id": f"t{i}", "price": "1", "size": "1", "side": "buy"} for i in range(200)]
    for p in prints:
        queue.offer({"symbol": "BTCUSDT", "trades": [p]})
    [frame] = queue.take()
    assert frame.body["trades"] == prints
    assert frame.coalesced_count == 1  # appended, never merged: nothing to disclose


@pytest.mark.parametrize("family", ["orders", "executions"])
def test_coalescer_orders_and_executions_cannot_be_queued(family: str) -> None:
    with pytest.raises(ValueError, match="never coalesced"):
        CoalescingQueue(family)


# -- queue contract ------------------------------------------------------------------------------


def test_coalescer_single_update_leaves_verbatim_with_its_binary_part() -> None:
    queue = CoalescingQueue("book")
    part = Frame(BOOK_DELTA)
    body = {"symbol": "BTCUSDT", "bids": [["100", "1"]], "asks": [], "coalesced": False}
    queue.offer(body, part)
    [frame] = queue.take()
    assert frame == Emission({"symbol": "BTCUSDT", "bids": [["100", "1"]], "asks": []}, part, 1)
    assert frame.body is not body
    assert queue.take() == []


def test_coalescer_two_updates_merge_without_binary_part() -> None:
    queue = CoalescingQueue("book")
    queue.offer({"symbol": "X", "bids": [["100", "1"]], "asks": []}, Frame(BOOK_DELTA))
    queue.offer({"symbol": "X", "bids": [["100.0", "0"]], "asks": [["101", "2"]]})
    [frame] = queue.take()
    assert frame.part is None
    assert frame.coalesced_count == 2
    assert frame.body == {"symbol": "X", "bids": [["100.0", "0"]], "asks": [["101", "2"]]}


def test_coalescer_private_update_shares_nothing_between_connections() -> None:
    """SR-190: two subscriptions fed the same private update get independent copies."""
    body = {"trade_groups": [{"id": "g1", "status": "open", "updated_at_ms": 1}]}
    a, b = CoalescingQueue("trade_groups"), CoalescingQueue("trade_groups")
    for queue in (a, b):
        queue.offer(body)
    [fa], [fb] = a.take(), b.take()
    fa.body["trade_groups"][0]["status"] = "closed"
    assert fb.body["trade_groups"][0]["status"] == "open"
    assert body["trade_groups"][0]["status"] == "open"


def test_coalescer_book_level_bound_refuses_and_drops_until_cleared() -> None:
    queue = CoalescingQueue("book", limit=2)
    assert queue.offer({"bids": [["1", "1"], ["2", "1"]], "asks": []})
    assert queue.offer({"bids": [["1", "5"]], "asks": []})  # an existing level never grows it
    assert not queue.offer({"bids": [], "asks": [["3", "1"]]})
    assert queue.overflowed
    assert not queue.offer({"bids": [["1", "1"]], "asks": []})
    assert queue.take() == []
    queue.clear()
    assert not queue.overflowed
    assert queue.offer({"bids": [["9", "1"]], "asks": []})
    assert [f.body["bids"] for f in queue.take()] == [[["9", "1"]]]


@pytest.mark.parametrize(
    ("family", "first", "grown"),
    [
        (
            "bars",
            {"bars": [{"generation": 0, "index": 0, "confirm": False}]},
            {"bars": [{"generation": 0, "index": 1, "confirm": False}]},
        ),
        ("trades", {"trades": [{"id": "1"}]}, {"trades": [{"id": "2"}]}),
    ],
)
def test_coalescer_bound_reached_sets_overflowed(family: str, first: Body, grown: Body) -> None:
    queue = CoalescingQueue(family, limit=1)
    assert queue.offer(first)
    assert not queue.offer(grown)
    assert queue.overflowed


def test_coalescer_unmerged_family_queues_whole_frames_in_order() -> None:
    queue = CoalescingQueue("profile")
    bodies = [
        {"symbol": "X", "kind": "volume", "profiles": [{"period_start_ms": i}]} for i in (1, 2)
    ]
    for body in bodies:
        queue.offer(body)
    assert [(f.body, f.coalesced_count) for f in queue.take()] == [(b, 1) for b in bodies]


def test_coalescer_frame_queue_bound_overflows() -> None:
    queue = CoalescingQueue("alerts")
    for _ in range(MAX_PENDING_FRAMES):
        assert queue.offer({"deliveries": []})
    assert not queue.offer({"deliveries": []})
    assert queue.overflowed


def _level(price: str) -> Body:
    return {"symbol": "X", "bids": [[price, "1"]], "asks": []}


def test_coalescer_coalesce_false_emits_each_update_individually() -> None:
    queue = CoalescingQueue("book", coalesce=False)
    for price in ("1", "2"):
        queue.offer(_level(price))
    assert [f.body for f in queue.take()] == [_level("1"), _level("2")]


def test_coalescer_forced_coalesce_folds_queued_frames_into_one_merge() -> None:
    queue = CoalescingQueue("book", coalesce=False)
    for price in ("1", "2", "3"):
        queue.offer(_level(price))
    queue.set_coalesce(True)
    [frame] = queue.take()
    assert frame.coalesced_count == 3
    assert frame.body == {"symbol": "X", "bids": [["3", "1"], ["2", "1"], ["1", "1"]], "asks": []}


def test_coalescer_coalesce_off_waits_for_the_pending_merge() -> None:
    queue = CoalescingQueue("book")
    queue.offer(_level("1"))
    queue.set_coalesce(False)
    queue.offer(_level("2"))
    assert [f.coalesced_count for f in queue.take()] == [2]
    for price in ("3", "4"):
        queue.offer(_level(price))
    assert len(queue.take()) == 2


def test_coalescer_set_coalesce_unchanged_keeps_queued_frames() -> None:
    queue = CoalescingQueue("book", coalesce=False)
    queue.offer(_level("1"))
    queue.set_coalesce(False)
    assert len(queue.take()) == 1


def test_coalescer_clear_resets_a_frame_queue_after_overflow() -> None:
    queue = CoalescingQueue("rules", limit=1)
    queue.offer({"rules": []})
    assert not queue.offer({"rules": []})
    queue.clear()
    assert not queue.overflowed
    assert not queue.pending
    assert queue.offer({"rules": []})


def test_coalescer_trades_dropped_counts_add_up() -> None:
    queue = CoalescingQueue("trades")
    queue.offer({"symbol": "X", "trades": [], "dropped": 2})
    queue.offer({"symbol": "X", "trades": [{"id": "1"}], "dropped": 3})
    [frame] = queue.take()
    assert frame.body == {"symbol": "X", "trades": [{"id": "1"}], "dropped": 5}
