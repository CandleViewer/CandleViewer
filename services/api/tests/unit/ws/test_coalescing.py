from __future__ import annotations

import asyncio
import copy
import json
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import assume, example, given
from hypothesis import strategies as st

from candleviewer.ws.binary import BOOK_DELTA, FLAG_ESTIMATED, FLAG_REPLAY, HEATMAP_COLUMN, Frame
from candleviewer.ws.coalescing import (
    _EXACT,
    _MAX_EXPONENT,
    MAX_PENDING_FRAMES,
    MAX_PENDING_KEYS,
    MERGED_FAMILIES,
    SENT_COLUMNS_MEMORY,
    CoalescingQueue,
    Emission,
)

Body = dict[str, Any]
State = dict[str, Any]
_LISTS = frozenset(
    {"bids", "asks", "bars", "trades", "liquidations", "dropped", "coalesced", "coalesced_count"}
    | {"series", "tickers", "balances", "health", "positions", "removed", "columns"}
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


def _apply_footprint(state: State, body: Mapping[str, Any]) -> None:
    _root(state, body)
    for bar in body["bars"]:
        key = (bar["generation"], bar["index"])  # the §8.2 bar key, never `t_ms`
        entry = state.setdefault("bars", {}).setdefault(key, {"fields": {}, "cells": {}})
        entry["fields"].update((k, v) for k, v in bar.items() if k != "cells")
        for cell in bar["cells"]:
            cur = entry["cells"].setdefault(Decimal(cell["price"]), {})
            for field, value in cell.items():
                if field in ("bid_volume", "ask_volume", "delta", "total_volume"):
                    cur[field] = cur.get(field, Decimal(0)) + Decimal(value)  # increments (§8.2)
                elif field == "trades":
                    cur[field] = cur.get(field, 0) + value
                else:
                    cur[field] = value


def _keyed(field: str, key: Callable[[Body], Any], *, newer: bool = False) -> Callable[..., None]:
    def apply(state: State, body: Mapping[str, Any]) -> None:
        _root(state, body)
        items = state.setdefault(field, {})
        for item in body.get(field, ()):
            cur = items.get(key(item))
            if newer and cur is not None and item["updated_at_ms"] < cur["updated_at_ms"]:
                continue  # §15: a late-arriving older entity is discarded
            items[key(item)] = item
        for pid in body.get("removed", ()):
            items.pop(pid, None)

    return apply


def _apply_wallet(state: State, body: Mapping[str, Any]) -> None:
    _keyed("balances", lambda b: (b["exchange_account_id"], b["coin"]), newer=True)(state, body)
    health = state.setdefault("health", {})
    for entry in body.get("health", ()):
        health[entry["exchange_account_id"]] = entry  # arrival order (§8.2, E27-T04)


def _append(field: str) -> Callable[..., None]:
    def apply(state: State, body: Mapping[str, Any]) -> None:
        _root(state, body)
        state.setdefault(field, []).extend(body[field])
        state["dropped"] = state.get("dropped", 0) + body.get("dropped", 0)

    return apply


# -- update generators --------------------------------------------------------------------------

_PRICE = st.sampled_from(["100", "100.0", "100.5", "101", "99.5"])
_SIZE = st.sampled_from(["0", "0.5", "1", "3.25"])
_DEC = st.sampled_from(["0.5", "1", "1.25", "2.000", "7.5"])
#: Producers never set the emitter-owned disclosure fields; a stray one must not leak through.
_STRAY = st.sampled_from([{}, {}, {"coalesced": True, "coalesced_count": 9}])
_book = st.builds(
    lambda xu, bids, asks, stray: {
        "symbol": "BTCUSDT",
        "depth": 50,
        "xu": xu,
        "bids": bids,
        "asks": asks,
        **stray,
    },
    st.integers(0, 9),
    st.lists(st.tuples(_PRICE, _SIZE).map(list), max_size=3),
    st.lists(st.tuples(_PRICE, _SIZE).map(list), max_size=3),
    _STRAY,
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
_cell = st.builds(
    lambda price, bid, ask, delta, total, n: {
        "price": price,
        "bid_volume": bid,
        "ask_volume": ask,
        "delta": delta,
        "total_volume": total,
        "trades": n,
    },
    _PRICE,
    st.sampled_from(["0.5", "1", "0.00000001", "2.000"]),
    st.sampled_from(["0.5", "1.25", "7.5"]),
    st.sampled_from(["-1.5", "0", "0.00000001", "-0.00000002"]),  # signed: no exponent form
    st.sampled_from(["1", "2.75", "0.00000003"]),
    st.integers(0, 3),
)
#: Every bar opens at one `t_ms`, as non-time bars may: only `(generation, index)` tells them apart.
_footprint = st.builds(
    lambda g, i, poc, cells: {
        "symbol": "BTCUSDT",
        "bar_type": "tick",
        "param": "1000",
        "bars": [{"generation": g, "index": i, "t_ms": 0, "poc_price": poc, "cells": cells}],
    },
    st.integers(0, 1),
    st.integers(0, 2),
    _PRICE,
    st.lists(_cell, max_size=3),
)
#: A footprint bar's key and open time (§14.4).
_FP_BAR = {"generation": 0, "index": 0, "t_ms": 0}


def _heatmap(ops: list[tuple[int, bool, int]]) -> list[Body]:
    """Columns per 100 ms bucket; once a bucket is complete its column is final (repeats only)."""
    final: set[int] = set()
    out = []
    for t_ms, complete, level in ops:
        done = complete or t_ms in final
        if done:
            final.add(t_ms)
        col = {"t_ms": t_ms, "price_min": "100", "price_step": "0.5", "complete": done}
        col |= {"bids": [t_ms / 100.0], "asks": [1.0]} if done else {"bids": [level], "asks": []}
        out.append({"symbol": "BTCUSDT", "time_bucket_ms": 100, "columns": [col]})
    return out


_heatmaps = st.lists(
    st.tuples(st.sampled_from([0, 100, 200]), st.booleans(), st.integers(0, 9)), max_size=25
).map(_heatmap)
_metrics = st.builds(
    lambda m, params, v: {
        "symbol": "BTCUSDT",
        "series": [{"metric": m, "t_ms": 5, "v": v, **({"params": params} if params else {})}],
    },
    st.sampled_from(["cvd", "delta"]),
    st.sampled_from([None, {}, {"window": 5}]),
    _DEC,
)
_ticker = st.builds(
    lambda sym, price: {"tickers": [{"symbol": sym, "last_price": price, "ts_ms": 1}]},
    st.sampled_from(["BTCUSDT", "ETHUSDT"]),
    _DEC,
)
_balance = st.builds(
    lambda acc, coin, equity, at: {
        "exchange_account_id": acc,
        "coin": coin,
        "equity": equity,
        "updated_at_ms": at,
    },
    st.sampled_from(["a1", "a2"]),
    st.sampled_from(["USDT", "BTC"]),
    _DEC,
    st.integers(0, 5),
)
_account_health = st.builds(
    lambda acc, state, at: {"exchange_account_id": acc, "state": state, "changed_at_ms": at},
    st.sampled_from(["a1", "a2"]),
    st.sampled_from(["healthy", "degraded", "down"]),
    st.integers(0, 5),
)
#: E27-T04: a delta may carry balances, health entries, both, or health only (§8.2).
_wallet = st.builds(
    lambda balances, health: {"balances": balances, **({"health": health} if health else {})},
    st.lists(_balance, max_size=1),
    st.lists(_account_health, max_size=2),
)
_position = st.builds(
    lambda pid, size, at: {
        "id": pid,
        "exchange_account_id": "a1",
        "symbol": "BTCUSDT",
        "side": "long",
        "size": size,
        "updated_at_ms": at,
    },
    st.sampled_from(["p1", "p2"]),
    _DEC,
    st.integers(0, 5),
)
_positions = st.builds(
    lambda ups, removed: {"positions": ups, **({"removed": removed} if removed else {})},
    st.lists(_position, max_size=2),
    st.lists(st.sampled_from(["p1", "p2"]), max_size=1),
)
_trades = st.builds(
    lambda ids, dropped, stray: {
        "symbol": "BTCUSDT",
        "trades": [{"id": f"t{i}", "price": "1", "size": "1", "side": "buy"} for i in ids],
        **({"dropped": dropped} if dropped else {}),
        **stray,
    },
    st.lists(st.integers(0, 999), max_size=4),
    st.integers(0, 3),
    _STRAY,
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
    ("footprint", st.lists(_footprint, max_size=25), _apply_footprint),
    ("heatmap", _heatmaps, _keyed("columns", lambda c: c["t_ms"])),
    (
        "metrics",
        st.lists(_metrics, max_size=25),
        _keyed("series", lambda m: (m["metric"], json.dumps(m.get("params") or {}))),
    ),
    ("ticker", st.lists(_ticker, max_size=25), _keyed("tickers", lambda t: t["symbol"])),
    ("wallet", st.lists(_wallet, max_size=25), _apply_wallet),
    (
        "positions",
        st.lists(_positions, max_size=25),
        _keyed("positions", lambda p: p["id"], newer=True),
    ),
    ("trades", st.lists(_trades, max_size=25), _append("trades")),
    ("liquidations", st.lists(_liquidations, max_size=25), _append("liquidations")),
]
_IDS = [f[0] for f in FAMILIES]
#: One step of a stream: an update, then optionally close the window and/or toggle `coalesce`.
_STEP = st.tuples(st.booleans(), st.sampled_from([None, True, False]))


def _run(queue: CoalescingQueue, updates: list[Body], steps: list[Any]) -> list[Emission] | None:
    """Offer every update, cutting windows and toggling `coalesce` as `steps` say; None when the
    queue refused an update (a bound was hit: the topic would be re-snapshotted instead)."""
    emitted: list[Emission] = []
    for update, (cut, toggle) in zip(updates, steps + [(False, None)] * len(updates), strict=False):
        if not queue.offer(update):
            return None
        if toggle is not None:
            queue.set_coalesce(toggle)
        if cut:
            emitted += queue.take()
    return emitted + queue.take()


def _state(apply: Callable[..., None], bodies: Sequence[Mapping[str, Any]]) -> State:
    state: State = {}
    for body in bodies:
        apply(state, body)
    return {k: v for k, v in state.items() if v}  # an update that changed nothing leaves no trace


@pytest.mark.parametrize(("family", "updates", "apply"), FAMILIES, ids=_IDS)
def test_coalescer_state_matches_every_source_update_applied(
    family: str, updates: Any, apply: Callable[..., None]
) -> None:
    """§16.4: "coalescer produces state identical to applying every source update", whatever
    the windows and however `coalesce` is toggled along the way."""

    @given(updates, st.lists(_STEP, max_size=25), st.booleans(), st.integers(2, 4))
    def check(source: list[Body], steps: list[Any], coalesce: bool, max_frames: int) -> None:
        emitted = _run(
            CoalescingQueue(family, coalesce=coalesce, max_frames=max_frames), source, steps
        )
        assume(emitted is not None)
        assert emitted is not None
        assert _state(apply, [e.body for e in emitted]) == _state(apply, source)

    check()


@pytest.mark.parametrize(("family", "updates", "apply"), FAMILIES, ids=_IDS)
def test_coalescer_never_mutates_its_input(
    family: str, updates: Any, apply: Callable[..., None]
) -> None:
    @given(updates, st.lists(_STEP, max_size=25))
    def check(source: list[Body], steps: list[Any]) -> None:
        pristine = copy.deepcopy(source)
        _run(CoalescingQueue(family), source, steps)
        assert source == pristine

    check()


@pytest.mark.parametrize(("family", "updates", "apply"), FAMILIES, ids=_IDS)
def test_coalescer_never_emits_the_disclosure_fields(
    family: str, updates: Any, apply: Callable[..., None]
) -> None:
    """The emitter owns `coalesced` / `coalesced_count` (§8.2); a producer's copy never leaks."""

    @given(updates, st.lists(_STEP, max_size=25))
    def check(source: list[Body], steps: list[Any]) -> None:
        for emission in _run(CoalescingQueue(family), source, steps) or []:
            assert not {"coalesced", "coalesced_count"} & emission.body.keys()

    check()


@given(st.lists(_book, min_size=1, max_size=25))
def test_coalescer_book_window_counts_every_update(source: list[Body]) -> None:
    queue = CoalescingQueue("book")
    for update in source:
        queue.offer(update)
    [frame] = queue.take()
    assert frame.coalesced_count == len(source)


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
    assert frame.coalesced_count == 1  # the discarded update merged nothing


_BARS_HEAD = {"symbol": "BTCUSDT", "bar_type": "time", "param": "5"}


def test_coalescer_40_updates_of_one_forming_bar_leave_as_one_frame_with_the_latest_state() -> None:
    """#399 scenario 3, first half: 40 trades update the forming bar inside one window."""
    queue = CoalescingQueue("bars")
    for n in range(1, 41):
        forming = {"generation": 0, "index": 5, "t_ms": 36_300_000, "c": str(n), "confirm": False}
        queue.offer({**_BARS_HEAD, "bars": [forming]})
    [frame] = queue.take()
    assert frame.body["bars"] == [forming]  # the 40th update's state
    assert frame.coalesced_count == 40


def test_coalescer_a_close_and_the_next_open_in_one_window_both_leave_the_close_confirmed() -> None:
    """#399 scenario 3, second half: the close is not collapsed into the open that follows it."""
    queue = CoalescingQueue("bars")
    bar = {"generation": 0, "t_ms": 36_300_000}
    for index, confirm, close in [(5, False, "1"), (5, True, "2"), (6, False, "2")]:
        item = {**bar, "index": index, "c": close, "confirm": confirm}
        queue.offer({**_BARS_HEAD, "bars": [item]})
    [frame] = queue.take()
    assert [(b["index"], b["confirm"], b["c"]) for b in frame.body["bars"]] == [
        (5, True, "2"),
        (6, False, "2"),
    ]
    assert frame.coalesced_count == 3


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


def test_coalescer_unknown_family_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown topic family"):
        CoalescingQueue("nope")


# -- emission contract ---------------------------------------------------------------------------


def test_coalescer_single_update_leaves_verbatim_with_its_binary_part() -> None:
    queue = CoalescingQueue("book")
    part = Frame(BOOK_DELTA)
    body = {"symbol": "BTCUSDT", "bids": [["100", "1"]], "asks": [], "coalesced": False}
    queue.offer(body, part, ts_ms=7)
    [frame] = queue.take()
    assert frame == Emission({"symbol": "BTCUSDT", "bids": [["100", "1"]], "asks": []}, part, 1, 7)
    assert frame.body is not body
    assert queue.take() == []


def test_coalescer_merged_book_frame_is_sorted_without_binary_part() -> None:
    queue = CoalescingQueue("book")
    queue.offer({"symbol": "X", "bids": [["100", "1"]], "asks": [["103", "1"]]}, Frame(BOOK_DELTA))
    queue.offer({"symbol": "X", "bids": [["100.0", "0"], ["99", "2"]], "asks": [["101", "2"]]})
    [frame] = queue.take()
    assert frame.part is None
    assert frame.coalesced_count == 2
    assert frame.body == {
        "symbol": "X",
        "bids": [["100.0", "0"], ["99", "2"]],
        "asks": [["101", "2"], ["103", "1"]],
    }


def test_coalescer_replay_time_is_kept_per_frame_and_latest_when_merged() -> None:
    whole = CoalescingQueue("profile")
    whole.offer({"symbol": "X", "kind": "volume", "profiles": []}, ts_ms=1)
    whole.offer({"symbol": "X", "kind": "volume", "profiles": []}, ts_ms=2)
    assert [f.ts_ms for f in whole.take()] == [1, 2]
    merged = CoalescingQueue("book")
    for ts_ms, price in ((5, "1"), (9, "2"), (8, "3")):
        merged.offer({"bids": [[price, "1"]], "asks": []}, ts_ms=ts_ms)
    assert [f.ts_ms for f in merged.take()] == [8]


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


def test_coalescer_merged_private_frames_share_nothing_between_connections() -> None:
    first = {"positions": [{"id": "p1", "size": "1", "updated_at_ms": 1}]}
    second = {"positions": [{"id": "p2", "size": "2", "updated_at_ms": 1}]}
    a, b = CoalescingQueue("positions"), CoalescingQueue("positions")
    for queue in (a, b):
        queue.offer(first)
        queue.offer(second)
    [fa], [fb] = a.take(), b.take()
    fa.body["positions"][0]["size"] = "9"
    assert fb.body["positions"][0]["size"] == "1"
    assert first["positions"][0]["size"] == "1"


# -- bounds, refusals and modes ------------------------------------------------------------------


def test_coalescer_book_level_bound_refuses_until_cleared() -> None:
    queue = CoalescingQueue("book", max_keys=2)
    assert queue.offer({"bids": [["1", "1"], ["2", "1"]], "asks": []})
    assert queue.offer({"bids": [["1", "5"]], "asks": []})  # an existing level never grows it
    assert not queue.offer({"bids": [], "asks": [["3", "1"]]})
    assert queue.overflowed
    assert not queue.pending
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
        (
            "footprint",
            {"bars": [{**_FP_BAR, "cells": []}]},
            {"bars": [{**_FP_BAR, "cells": [{"price": "1", "bid_volume": "1"}]}]},
        ),
        ("ticker", {"tickers": [{"symbol": "A"}]}, {"tickers": [{"symbol": "B"}]}),
        ("positions", {"positions": [], "removed": ["p1"]}, {"positions": [], "removed": ["p2"]}),
        ("trades", {"trades": [{"id": "1"}]}, {"trades": [{"id": "2"}]}),
        (
            "wallet",
            {"balances": [], "health": [{"exchange_account_id": "a1"}]},
            {"balances": [], "health": [{"exchange_account_id": "a2"}]},
        ),
    ],
)
def test_coalescer_bound_reached_sets_overflowed(family: str, first: Body, grown: Body) -> None:
    queue = CoalescingQueue(family, max_keys=1, max_items=1)
    assert queue.offer(first)
    assert not queue.offer(grown)
    assert queue.overflowed and queue.refusal == "full"


@pytest.mark.parametrize(
    ("family", "malformed"),
    [
        ("book", {"bids": [["100", "1"], ["abc", "1"]], "asks": []}),
        ("book", {"bids": [["NaN", "1"]], "asks": []}),
        ("book", {"bids": [["100", "1", "2"]], "asks": []}),
        ("bars", {"bars": [{"index": 0, "confirm": False}]}),
        ("footprint", {"bars": [{**_FP_BAR, "cells": [{"price": "1", "bid_volume": "x"}]}]}),
        ("footprint", {"bars": [{"index": 0, "t_ms": 0, "cells": []}]}),  # §14.4: both keys
        ("footprint", {"bars": [{"generation": 0, "t_ms": 0, "cells": []}]}),
        ("wallet", {"balances": [{"coin": "USDT"}]}),
        ("wallet", {"balances": [], "health": [{"state": "down"}]}),
        ("trades", {"trades": 7}),
    ],
)
def test_coalescer_unmergeable_update_is_refused_like_an_overflow(
    family: str, malformed: Body
) -> None:
    """A malformed producer payload never escapes as an exception or leaves half-applied: the
    queue refuses it and the topic is re-snapshotted."""
    queue = CoalescingQueue(family)
    assert not queue.offer(malformed)
    assert queue.overflowed and queue.refusal == "malformed"
    assert queue.take() == []
    queue.clear()
    assert not queue.pending


def test_coalescer_unmerged_family_queues_whole_frames_in_order() -> None:
    queue = CoalescingQueue("profile")
    bodies = [
        {"symbol": "X", "kind": "volume", "profiles": [{"period_start_ms": i}]} for i in (1, 2)
    ]
    for body in bodies:
        queue.offer(body)
    assert [(f.body, f.coalesced_count) for f in queue.take()] == [(b, 1) for b in bodies]


def test_coalescer_unmerged_family_overflows_at_its_frame_bound() -> None:
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


def test_coalescer_coalesce_false_folds_at_the_frame_bound_instead_of_overflowing() -> None:
    queue = CoalescingQueue("book", coalesce=False, max_frames=2)
    for price in ("1", "2", "3"):
        assert queue.offer(_level(price))
    [frame] = queue.take()
    assert frame.coalesced_count == 3
    queue.offer(_level("4"))
    queue.offer(_level("5"))
    assert len(queue.take()) == 2  # back to whole frames once the fold has left


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


def test_coalescer_pending_bytes_track_state_not_updates() -> None:
    queue = CoalescingQueue("book")
    assert queue.pending_bytes == 0
    queue.offer(_level("100"))
    one_level = queue.pending_bytes
    for _ in range(50):
        queue.offer(_level("100"))  # overwrites never grow it
    assert queue.pending_bytes == one_level
    queue.offer(_level("101"))
    assert queue.pending_bytes > one_level
    queue.take()
    assert queue.pending_bytes == 0
    frames = CoalescingQueue("profile")
    frames.offer({"symbol": "X", "kind": "volume", "profiles": []})
    assert frames.pending_bytes > 0


# -- family rules ------------------------------------------------------------------------------


def test_coalescer_trades_dropped_counts_add_up() -> None:
    queue = CoalescingQueue("trades")
    queue.offer({"symbol": "X", "trades": [], "dropped": 2})
    queue.offer({"symbol": "X", "trades": [{"id": "1"}], "dropped": 3})
    [frame] = queue.take()
    assert frame.body == {"symbol": "X", "trades": [{"id": "1"}], "dropped": 5}


def test_coalescer_positions_removed_after_upsert_and_upsert_after_removed() -> None:
    queue = CoalescingQueue("positions")
    pos = {"id": "p1", "size": "1", "updated_at_ms": 1}
    queue.offer({"positions": [pos]})
    queue.offer({"positions": [], "removed": ["p1"]})
    queue.offer({"positions": [{**pos, "id": "p2"}]})
    [frame] = queue.take()
    assert frame.body == {"positions": [{**pos, "id": "p2"}], "removed": ["p1"]}
    queue.offer({"positions": [], "removed": ["p1"]})
    queue.offer({"positions": [pos]})
    assert [f.body for f in queue.take()] == [
        {"positions": [], "removed": ["p1"]},
        {"positions": [pos]},
    ]


def test_coalescer_wallet_older_balance_is_discarded() -> None:
    queue = CoalescingQueue("wallet")
    new = {"exchange_account_id": "a1", "coin": "USDT", "equity": "2", "updated_at_ms": 9}
    queue.offer({"balances": [new]})
    queue.offer({"balances": [{**new, "equity": "1", "updated_at_ms": 3}]})
    [frame] = queue.take()
    assert frame.coalesced_count == 1
    assert frame.body == {"balances": [new]}


def _health(account: str, state: str, changed_at_ms: int) -> Body:
    return {
        "exchange_account_id": account,
        "state": state,
        "reason": "no_success" if state == "down" else "ws_heartbeat",
        "heartbeat_age_ms": None,
        "rest_only": False,
        "changed_at_ms": changed_at_ms,
    }


def test_coalescer_wallet_health_only_delta_is_emitted() -> None:
    """§8.2 (E27-T04): health is state, so a delta with no balance is never discarded."""
    queue = CoalescingQueue("wallet")
    down = {"balances": [], "health": [_health("a1", "down", 5)]}
    assert queue.offer(down) and queue.pending
    [frame] = queue.take()
    assert (frame.body, frame.coalesced_count) == (down, 1)


def test_coalescer_wallet_window_keeps_the_latest_health_of_every_account() -> None:
    queue = CoalescingQueue("wallet")
    balance = {"exchange_account_id": "a1", "coin": "USDT", "equity": "2", "updated_at_ms": 9}
    entries = [_health("a1", "down", 5), _health("a2", "healthy", 6), _health("a1", "healthy", 7)]
    queue.offer({"balances": [balance]})
    for entry in entries:
        queue.offer({"balances": [], "health": [entry]})
    [frame] = queue.take()
    assert frame.coalesced_count == 4
    assert frame.body == {"balances": [balance], "health": entries[1:]}


def test_coalescer_wallet_balance_only_window_carries_no_health_list() -> None:
    """Additive (C-6.3): a window with no health entry keeps the frame shape it always had."""
    queue = CoalescingQueue("wallet")
    usdt = {"exchange_account_id": "a1", "coin": "USDT", "equity": "2", "updated_at_ms": 9}
    btc = usdt | {"coin": "BTC"}
    for balance in (usdt, btc):
        queue.offer({"balances": [balance]})
    [frame] = queue.take()
    assert (frame.body, frame.coalesced_count) == ({"balances": [usdt, btc]}, 2)


def test_coalescer_wallet_later_health_entry_wins_even_when_dated_earlier() -> None:
    """`changed_at_ms` follows the wall clock, which can step back: arrival order decides."""
    queue = CoalescingQueue("wallet")
    for entry in (_health("a1", "healthy", 9_000), _health("a1", "down", 1_000)):
        queue.offer({"balances": [], "health": [entry]})
    [frame] = queue.take()
    assert frame.body["health"] == [_health("a1", "down", 1_000)]


def test_coalescer_wallet_pending_bytes_count_health_entries() -> None:
    queue = CoalescingQueue("wallet")
    queue.offer({"balances": [], "health": [_health("a1", "down", 1)]})
    one = queue.pending_bytes
    queue.offer({"balances": [], "health": [_health("a2", "down", 1)]})
    assert 0 < one < queue.pending_bytes
    queue.take()
    assert queue.pending_bytes == 0


def test_coalescer_metrics_params_keep_series_apart() -> None:
    queue = CoalescingQueue("metrics")
    for params, v in (({"w": 5}, "1"), (None, "2"), ({"w": 5}, "3")):
        item = {"metric": "cvd", "t_ms": 1, "v": v, **({"params": params} if params else {})}
        queue.offer({"symbol": "X", "series": [item]})
    [frame] = queue.take()
    assert [s["v"] for s in frame.body["series"]] == ["2", "3"]


def _column(t_ms: int, *, complete: bool = True) -> Body:
    return {
        "t_ms": t_ms,
        "price_min": "1",
        "price_step": "1",
        "bids": [1.0],
        "asks": [],
        "complete": complete,
    }


def test_coalescer_heatmap_complete_column_already_sent_is_dropped() -> None:
    queue = CoalescingQueue("heatmap")
    body = {"symbol": "X", "time_bucket_ms": 100, "columns": [_column(0)]}
    queue.offer(body)
    assert len(queue.take()) == 1
    queue.offer(body)
    assert not queue.pending
    assert queue.take() == []
    queue.offer({**body, "max_value": 2.0})  # a new root value still goes out
    assert [f.body["max_value"] for f in queue.take()] == [2.0]


def test_coalescer_heatmap_late_column_for_a_sent_complete_bucket_is_dropped() -> None:
    queue = CoalescingQueue("heatmap")
    queue.offer({"symbol": "X", "time_bucket_ms": 100, "columns": [_column(0)]})
    queue.take()
    queue.offer({"symbol": "X", "time_bucket_ms": 100, "columns": [_column(0, complete=False)]})
    assert queue.take() == []


def test_coalescer_heatmap_incomplete_column_then_complete_is_sent() -> None:
    queue = CoalescingQueue("heatmap")
    queue.offer({"symbol": "X", "time_bucket_ms": 100, "columns": [_column(0, complete=False)]})
    queue.take()
    queue.offer({"symbol": "X", "time_bucket_ms": 100, "columns": [_column(0)]})
    assert [f.body["columns"] for f in queue.take()] == [[_column(0)]]


def test_coalescer_heatmap_sent_memory_is_bounded() -> None:
    queue = CoalescingQueue("heatmap")
    for t_ms in range(SENT_COLUMNS_MEMORY + 1):
        queue.offer({"symbol": "X", "time_bucket_ms": 100, "columns": [_column(t_ms)]})
        queue.take()
    queue.offer({"symbol": "X", "time_bucket_ms": 100, "columns": [_column(0)]})
    assert queue.pending  # the oldest bucket was forgotten, so it is sent again


def test_coalescer_footprint_sums_cells_exactly_within_a_bar_only() -> None:
    queue = CoalescingQueue("footprint")
    cell = {"price": "100", "bid_volume": "0.00000001", "ask_volume": "1.5", "trades": 1}
    queue.offer({"bars": [{**_FP_BAR, "poc_price": "100", "cells": [cell]}]})
    queue.offer({"bars": [{**_FP_BAR, "poc_price": "101", "cells": [cell]}]})
    queue.offer({"bars": [{**_FP_BAR, "index": 1, "cells": [cell]}]})  # the same open time
    [frame] = queue.take()
    first, second = frame.body["bars"]
    assert first["poc_price"] == "101"
    assert first["cells"] == [
        {"price": "100", "bid_volume": "0.00000002", "ask_volume": "3.0", "trades": 2}
    ]
    assert second["cells"] == [
        {"price": "100", "bid_volume": "0.00000001", "ask_volume": "1.5", "trades": 1}
    ]


def test_coalescer_fold_refused_by_the_key_bound_overflows() -> None:
    queue = CoalescingQueue("book", coalesce=False, max_frames=2, max_keys=1)
    assert queue.offer(_level("1"))
    assert queue.offer(_level("2"))
    assert not queue.offer(_level("3"))  # the fold itself hits the one-level bound
    assert queue.overflowed


def test_coalescer_clear_resets_a_frame_queue_after_overflow() -> None:
    queue = CoalescingQueue("rules", max_frames=1)
    queue.offer({"rules": []})
    assert not queue.offer({"rules": []})
    queue.clear()
    assert not queue.overflowed
    assert queue.offer({"rules": []})


def test_coalescer_fold_keeps_a_positions_removal_before_its_reopen() -> None:
    """Hypothesis counterexample: folding whole frames must honour the removed-then-re-opened
    split, or the client applies the removal last and loses the position."""
    queue = CoalescingQueue("positions", coalesce=False)
    pos = {"id": "p1", "size": "0.5", "updated_at_ms": 0}
    queue.offer({"positions": [], "removed": ["p1"]})
    queue.offer({"positions": [pos]})
    queue.set_coalesce(True)
    assert [f.body for f in queue.take()] == [
        {"positions": [], "removed": ["p1"]},
        {"positions": [pos]},
    ]


def _nested(depth: int) -> Body:
    item: Body = {"id": "1"}
    for _ in range(depth):
        item = {"x": item}
    return item


@pytest.mark.parametrize(
    ("family", "body"),
    [
        ("trades", {"trades": [_nested(5_000)]}),
        ("positions", {"positions": [{"id": "p1", "updated_at_ms": 1, "x": _nested(5_000)}]}),
    ],
)
def test_coalescer_pathologically_nested_update_is_refused(family: str, body: Body) -> None:
    queue = CoalescingQueue(family)
    assert not queue.offer(body)
    assert queue.overflowed


def test_coalescer_heatmap_merged_columns_leave_in_time_order() -> None:
    queue = CoalescingQueue("heatmap")
    for t_ms in (200, 100, 300):
        queue.offer({"symbol": "X", "time_bucket_ms": 100, "columns": [_column(t_ms)]})
    [frame] = queue.take()
    assert [col["t_ms"] for col in frame.body["columns"]] == [100, 200, 300]


@pytest.mark.parametrize("malformed", [[{"x": 1}], 5, [3]])
def test_coalescer_malformed_positions_after_a_removal_is_refused(malformed: Any) -> None:
    """The removed-then-re-opened check runs inside the refusal guard too."""
    queue = CoalescingQueue("positions")
    queue.offer({"positions": [], "removed": ["p1"]})
    assert not queue.offer({"positions": malformed})
    assert queue.overflowed


def test_coalescer_windows_split_off_count_against_the_frame_bound() -> None:
    queue = CoalescingQueue("positions", max_frames=3)
    refused = False
    for at in range(10):
        refused = not queue.offer({"positions": [], "removed": ["p1"]})
        refused = refused or not queue.offer({"positions": [{"id": "p1", "updated_at_ms": at}]})
        if refused:
            break
    assert refused
    assert queue.overflowed


def test_coalescer_uncopyable_private_update_is_refused() -> None:
    class _Uncopyable:
        def __deepcopy__(self, memo: Any) -> Any:
            raise TypeError("cannot copy")

    queue = CoalescingQueue("positions")
    assert not queue.offer({"positions": [{"id": "p1", "updated_at_ms": 1, "x": _Uncopyable()}]})
    assert queue.overflowed


def test_coalescer_keyed_entities_leave_in_last_write_order() -> None:
    """A client keyed more coarsely than the merge (per metric code) still ends on the last
    write, because entities leave in the order they were last written."""
    queue = CoalescingQueue("metrics")
    for params, v in (({"period": 14}, "1"), (None, "2"), ({"period": 14}, "3")):
        item = {"metric": "atr", "t_ms": 1, "v": v, **({"params": params} if params else {})}
        queue.offer({"symbol": "X", "series": [item]})
    [frame] = queue.take()
    assert [s["v"] for s in frame.body["series"]] == ["2", "3"]


@pytest.mark.parametrize(
    ("family", "body"),
    [
        ("profile", {"symbol": "X", "kind": "volume", "profiles": [_nested(5_000)]}),
        ("book", {"symbol": "X", "bids": [["1", "1"]], "asks": [], "meta": _nested(5_000)}),
    ],
)
def test_coalescer_nested_whole_frame_or_root_field_is_refused(family: str, body: Body) -> None:
    queue = CoalescingQueue(family)
    assert not queue.offer(body)
    assert queue.overflowed


def test_coalescer_heatmap_single_update_drops_a_column_of_a_sent_bucket() -> None:
    """#2500 review: a lone update mixing a sent bucket and a new one must not leave verbatim."""
    queue = CoalescingQueue("heatmap")
    queue.offer({"symbol": "X", "time_bucket_ms": 100, "columns": [_column(1)]})
    queue.take()
    stale, fresh = _column(1, complete=False), _column(2, complete=False)
    queue.offer({"symbol": "X", "time_bucket_ms": 100, "columns": [stale, fresh]})
    [frame] = queue.take()
    assert frame.body["columns"] == [fresh]


def test_coalescer_heatmap_root_change_never_resends_a_sent_bucket() -> None:
    queue = CoalescingQueue("heatmap")
    queue.offer({"symbol": "X", "time_bucket_ms": 100, "max_value": 1.0, "columns": [_column(1)]})
    queue.take()
    body = {"symbol": "X", "time_bucket_ms": 100, "max_value": 2.0}
    queue.offer({**body, "columns": [_column(1, complete=False)]})
    [frame] = queue.take()
    assert frame.body == {**body, "columns": []}


def test_coalescer_heatmap_single_update_with_a_bucket_twice_leaves_its_completing_column() -> None:
    """A lone update leaves verbatim, and every frame is read as it leaves (#3423): one that holds
    a bucket twice, which no producer sends, loses the later column as a whole frame does."""
    queue = CoalescingQueue("heatmap")
    twice = [_column(0), _column(0, complete=False)]
    assert queue.offer({"symbol": "X", "time_bucket_ms": 100, "columns": twice})
    [frame] = queue.take()
    assert frame.body["columns"] == [_column(0)]


# -- a heatmap frame that leaves whole (`coalesce: false`) is trimmed like a window (#3423) -----

_HEAT = {"symbol": "X", "time_bucket_ms": 100}


def _sent_whole(*buckets: int) -> CoalescingQueue:
    """A whole-frame heatmap queue that has sent each of `buckets` complete."""
    queue = CoalescingQueue("heatmap", coalesce=False)
    for t_ms in buckets:
        queue.offer({**_HEAT, "columns": [_column(t_ms)]})
    assert len(queue.take()) == len(buckets)
    return queue


#: A later column for a bucket sent complete: it repeats that column, differs from it, or is open.
_LATER = pytest.mark.parametrize(
    "later",
    [_column(0), {**_column(0), "bids": [9.0]}, _column(0, complete=False)],
    ids=["identical", "differing", "incomplete"],
)


@_LATER
@pytest.mark.parametrize("seq", [list, tuple, deque], ids=["list", "tuple", "deque"])
def test_coalescer_whole_heatmap_frame_of_a_sent_complete_bucket_alone_sends_nothing(
    later: Body, seq: Callable[[list[Body]], Sequence[Body]]
) -> None:
    """§8.2 "Completed heatmap buckets": a complete bucket is final, so a later column for it is
    dropped whatever it holds, and a frame left with no column is not queued."""
    queue = _sent_whole(0)
    assert queue.offer({**_HEAT, "columns": seq([later])})
    assert (queue.pending, queue.pending_bytes, queue.take()) == (False, 0, [])


def test_coalescer_whole_heatmap_frame_loses_its_sent_columns_only() -> None:
    """The rest is as it was: root fields, column order, counts, `ts_ms` and `meta`; its part is
    not, as it mirrored the dropped columns. The producer's body is untouched."""
    queue = _sent_whole(0, 200)
    new, root = [_column(300, complete=False), _column(100)], {**_HEAT, "max_value": 2.0}
    body = {**root, "columns": [new[0], _column(0), _column(200, complete=False), new[1]]}
    before = copy.deepcopy(body)
    assert queue.offer(body, Frame(HEATMAP_COLUMN), ts_ms=7, meta={"k": 1}, count=3)
    twin = CoalescingQueue("heatmap", coalesce=False)
    assert twin.offer({**root, "columns": new})
    assert queue.pending_bytes == twin.pending_bytes  # sized as what is left
    assert queue.take() == [Emission({**root, "columns": new}, None, 3, 7, {"k": 1})]
    assert body == before


def test_coalescer_whole_heatmap_frames_keep_their_order_and_an_untouched_one_its_part() -> None:
    queue, part = _sent_whole(0), Frame(HEATMAP_COLUMN)
    for count, columns in enumerate(([_column(0), _column(100)], [_column(0)], [_column(200)]), 1):
        assert queue.offer({**_HEAT, "columns": columns}, part, count=count)
    first, last = queue.take()  # the second frame was left with no column
    assert (first.body["columns"], first.part, first.coalesced_count) == ([_column(100)], None, 1)
    assert (last.body["columns"], last.part, last.coalesced_count) == ([_column(200)], part, 3)


@_LATER
def test_coalescer_whole_heatmap_frames_in_one_window_never_regress_a_complete_bucket(
    later: Body,
) -> None:
    """§8.2: a column that completes a bucket makes it final as it leaves, so a later column for it
    in the same window does not follow it (the client would go from complete back to open), and a
    complete one after the take is dropped: the client holds the complete column."""
    queue, first = CoalescingQueue("heatmap", coalesce=False), {**_HEAT, "columns": [_column(0)]}
    other = {**_HEAT, "columns": [_column(100)]}
    assert queue.offer(first) and queue.offer({**_HEAT, "columns": [later]}) and queue.offer(other)
    assert [f.body for f in queue.take()] == [first, other]
    assert queue.offer({**_HEAT, "columns": [{**_column(0), "asks": [2.0]}]})
    assert (queue.pending, queue.take()) == (False, [])


@_LATER
def test_coalescer_whole_heatmap_frame_with_a_bucket_twice_keeps_the_completing_column(
    later: Body,
) -> None:
    """The same rule inside one frame: its columns reach the client in order, so each one after
    the column that completes its bucket is dropped (three here: a dropped one never stands in for
    the completing one), however many open ones came before it and whatever stands between them."""
    queue, open_ = CoalescingQueue("heatmap", coalesce=False), _column(0, complete=False)
    kept = [open_, _column(0), _column(100, complete=False)]
    assert queue.offer({**_HEAT, "columns": [*kept, later, later, later]})
    [frame] = queue.take()
    assert frame.body["columns"] == kept


def test_coalescer_whole_heatmap_frame_open_columns_before_a_complete_one_stay_whole() -> None:
    """Only a complete column makes a bucket final: open ones before it are sent, with the part."""
    queue, part = CoalescingQueue("heatmap", coalesce=False), Frame(HEATMAP_COLUMN)
    open_ = _column(0, complete=False)
    body = {**_HEAT, "columns": [open_, open_, _column(0)]}
    assert queue.offer(body, part)
    assert queue.take() == [Emission(body, part)]


def test_coalescer_whole_heatmap_frame_trimmed_at_take_keeps_its_counts_not_its_part() -> None:
    """The next frame of the window is trimmed as it leaves, as one trimmed as it is queued is:
    root fields, counts, `ts_ms` and `meta` stay, and its part goes with the dropped column."""
    queue, part, root = CoalescingQueue("heatmap", coalesce=False), Frame(HEATMAP_COLUMN), _HEAT
    assert queue.offer({**root, "columns": [_column(0)]}, part, count=2)
    later = {**root, "max_value": 2.0, "columns": [_column(0, complete=False), _column(100)]}
    assert queue.offer(later, part, ts_ms=7, meta={"k": 1}, count=3)
    assert queue.take() == [
        Emission({**root, "columns": [_column(0)]}, part, 2),
        Emission({**root, "max_value": 2.0, "columns": [_column(100)]}, None, 3, 7, {"k": 1}),
    ]


def test_coalescer_whole_heatmap_frame_trimmed_at_take_is_recorded_as_sent() -> None:
    """A frame trimmed as it leaves is recorded as sent like any other: the next frame of the
    window loses its open column for bucket 0, which the frame before it completed, and the
    complete bucket 100 it keeps is final from then on."""
    queue = CoalescingQueue("heatmap", coalesce=False)
    assert queue.offer({**_HEAT, "columns": [_column(0)]})
    assert queue.offer({**_HEAT, "columns": [_column(0, complete=False), _column(100)]})
    assert [f.body["columns"] for f in queue.take()] == [[_column(0)], [_column(100)]]
    assert queue.offer({**_HEAT, "columns": [_column(100, complete=False)]})
    assert not queue.pending  # bucket 100 left complete in the frame that was trimmed as it left


def test_coalescer_whole_heatmap_emptied_frame_is_not_queued_whatever_its_root_fields() -> None:
    """The merging path sends a changed root field with `columns: []` (above); a whole frame the
    filter leaves with no column is not queued, `max_value` changed or not. Pinned, so that
    sending it one day is a decision."""
    queue = _sent_whole(0)
    assert queue.offer({**_HEAT, "max_value": 2.0, "columns": [_column(0)]})
    assert (queue.pending, queue.pending_bytes, queue.take()) == (False, 0, [])


def test_coalescer_whole_heatmap_frame_is_trimmed_by_the_snapshot_that_seeded_the_queue() -> None:
    """The memory is the merge's own, bound included: what a snapshot sent (`seed`) is final too."""
    queue = CoalescingQueue("heatmap", coalesce=False)
    queue.seed(range(SENT_COLUMNS_MEMORY + 1), _HEAT)  # buckets 1 to 2000 are kept, 0 is not
    assert queue.offer({**_HEAT, "columns": [_column(1), _column(0)]})
    [frame] = queue.take()
    assert frame.body["columns"] == [_column(0)]


def test_coalescer_whole_heatmap_frame_for_a_bucket_sent_incomplete_is_sent() -> None:
    queue = CoalescingQueue("heatmap", coalesce=False)
    queue.offer({**_HEAT, "columns": [_column(0, complete=False)]})
    queue.take()
    queue.offer({**_HEAT, "columns": [_column(0)]})
    assert [f.body["columns"] for f in queue.take()] == [[_column(0)]]


@pytest.mark.parametrize("coalesce", [False, True], ids=["whole", "merging"])
@pytest.mark.parametrize("complete", [1, "true", "false", None], ids=["1", "true", "false", "none"])
def test_coalescer_heatmap_only_the_json_true_completes_a_bucket(
    complete: Any, coalesce: bool
) -> None:
    """§8.2: a column completes its bucket when `complete` is the JSON `true` and for no other
    value, truthy or not. One that carries another value is sent and leaves the bucket open: a
    complete column for it after the take is sent too, and inside one frame it does not end it."""
    odd, done = {**_column(0), "complete": complete}, _column(0)
    queue = CoalescingQueue("heatmap", coalesce=coalesce)
    for columns in ([odd], [done]):  # one take each
        assert queue.offer({**_HEAT, "columns": columns})
        assert [f.body["columns"] for f in queue.take()] == [columns]
    twice = CoalescingQueue("heatmap", coalesce=coalesce)
    assert twice.offer({**_HEAT, "columns": [odd, done]})
    assert [f.body["columns"] for f in twice.take()] == [[odd, done]]


@pytest.mark.parametrize("coalesce", [False, True], ids=["whole", "merging"])
def test_coalescer_heatmap_reads_a_bucket_by_its_t_ms_as_an_int(coalesce: bool) -> None:
    """A bucket is its `t_ms` read as an int (`_t_key`), as `validate` and a window read it: a
    later column that carries it as a string is that bucket's, whether an earlier take sent the
    bucket complete or the column before it in the same frame did."""
    as_text = {**_column(0, complete=False), "t_ms": "0"}
    queue = CoalescingQueue("heatmap", coalesce=coalesce)
    assert queue.offer({**_HEAT, "columns": [_column(0)]}) and len(queue.take()) == 1
    assert queue.offer({**_HEAT, "columns": [as_text]})
    assert (queue.pending, queue.take()) == (False, [])
    twice = CoalescingQueue("heatmap", coalesce=coalesce)
    assert twice.offer({**_HEAT, "columns": [_column(0), as_text]})
    assert [f.body["columns"] for f in twice.take()] == [[_column(0)]]


@pytest.mark.parametrize("coalesce", [False, True], ids=["whole", "merging"])
def test_coalescer_heatmap_remembers_a_sent_bucket_by_its_t_ms_as_an_int(coalesce: bool) -> None:
    """The mirror of the test above, on the side that records: `emitted` reads the `t_ms` of a
    complete column as an int too, so one that carries it as a string is that bucket's, and a
    later column for the bucket, an int, is dropped."""
    as_text = {**_column(0), "t_ms": "0"}
    queue = CoalescingQueue("heatmap", coalesce=coalesce)
    assert queue.offer({**_HEAT, "columns": [as_text]}) and len(queue.take()) == 1
    assert queue.offer({**_HEAT, "columns": [_column(0, complete=False)]})
    assert (queue.pending, queue.take()) == (False, [])


@pytest.mark.parametrize(
    "columns", [{"columns": []}, {"columns": deque()}, {}], ids=["empty", "empty-deque", "absent"]
)
def test_coalescer_whole_heatmap_frame_with_no_column_to_begin_with_is_sent(columns: Body) -> None:
    """Only a frame the filter emptied is dropped: a root-only update still leaves."""
    queue = _sent_whole(0)
    body = {**_HEAT, "max_value": 2.0, **columns}
    assert queue.offer(body)
    assert [f.body for f in queue.take()] == [body]


@pytest.mark.parametrize(
    "unreadable",
    [3, {"complete": True}, {"t_ms": "abc"}, {"t_ms": float("inf")}],
    # what `_t_key` raises on each: a TypeError, a KeyError, a ValueError, an OverflowError
    ids=["not-an-object", "no-t_ms", "bad-t_ms", "t_ms-inf"],
)
def test_coalescer_whole_heatmap_frame_the_filter_cannot_read_stays_whole(
    monkeypatch: pytest.MonkeyPatch, unreadable: Any
) -> None:
    """Defence in depth behind `validate`, as for `take`: a frame it let through with a column that
    cannot be read, whichever way, is queued as it came, a sent bucket's column included, for
    `take` to refuse."""
    queue = _sent_whole(0)
    monkeypatch.setattr(queue._merge, "validate", lambda body: None)
    monkeypatch.setattr(queue._merge, "emitted", lambda body: None)  # hand the frame back
    body = {**_HEAT, "columns": [_column(0), unreadable]}
    assert queue.offer(body)
    assert [f.body for f in queue.take()] == [body]


#: One whole frame's columns, as `(t_ms, complete)`: none to three, so a frame that is trimmed, not
#: emptied, as it leaves is drawn as well as one that is dropped.
_WHOLE_FRAME = st.lists(st.tuples(st.sampled_from([0, 100, 200]), st.booleans()), max_size=3)


@example([([(0, True)], False), ([(0, False)], True)])  # complete, then open, in one window
@example([([(0, True)], False), ([(0, False), (100, True)], True), ([(100, False)], True)])
@given(st.lists(st.tuples(_WHOLE_FRAME, st.booleans()), max_size=30))
def test_coalescer_whole_heatmap_frames_never_resend_a_complete_bucket(
    ops: list[tuple[list[tuple[int, bool]], bool]],
) -> None:
    """§8.2: however frames and takes interleave, no column of a bucket follows its complete one on
    the wire, in the order the client reads them: across takes, within one and inside a frame. The
    second example is a frame trimmed, not emptied, as it leaves, and then an open column for the
    bucket it completed."""
    queue, wire = CoalescingQueue("heatmap", coalesce=False), list[Body]()
    for cells, cut in ops:
        columns = [_column(t_ms, complete=complete) for t_ms, complete in cells]
        assert queue.offer({**_HEAT, "columns": columns})
        if cut:
            wire += [col for out in queue.take() for col in out.body["columns"]]
    wire += [col for out in queue.take() for col in out.body["columns"]]
    final = set[int]()
    for col in wire:
        assert col["t_ms"] not in final
        if col["complete"]:
            final.add(col["t_ms"])


def test_coalescer_footprint_update_without_bars_changes_nothing() -> None:
    queue = CoalescingQueue("footprint")
    queue.offer({"symbol": "X", "bars": []})
    assert not queue.pending


def test_coalescer_footprint_absurd_exponent_is_refused() -> None:
    queue = CoalescingQueue("footprint")
    cell = {"price": "1", "bid_volume": "1E+999999"}
    assert not queue.offer({"bars": [{**_FP_BAR, "cells": [cell]}]})
    assert queue.overflowed and queue.error == "ValueError"


@pytest.mark.parametrize("body", [["x"], None, "bids"])
def test_coalescer_body_that_is_not_a_mapping_is_refused(body: Any) -> None:
    queue = CoalescingQueue("book")
    assert not queue.offer(body)
    assert queue.overflowed


# -- #2500 security review --------------------------------------------------------------------


@pytest.mark.parametrize(
    "columns",
    [5, [3], ["x"], [{"complete": True}], [{"complete": True, "t_ms": "abc"}]],
    ids=["not-a-list", "int-column", "str-column", "no-t_ms", "bad-t_ms"],
)
def test_coalescer_whole_heatmap_frame_with_unreadable_columns_is_refused_at_entry(
    columns: Any,
) -> None:
    """`coalesce: false` queues whole frames; `take()` must never meet one it cannot read."""
    queue = CoalescingQueue("heatmap", coalesce=False)
    assert not queue.offer({"symbol": "X", "time_bucket_ms": 100, "columns": columns})
    assert queue.overflowed and queue.take() == []


_JSON = st.recursive(
    st.none() | st.booleans() | st.integers(-3, 3) | st.sampled_from(["", "x", "1", "-2.5"]),
    lambda inner: st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=8), inner),
    max_leaves=12,
)
_BODY_KEYS = ["columns", "bars", "bids", "asks", "items", "t_ms", "complete", "symbol"]


@given(
    family=st.sampled_from(sorted(MERGED_FAMILIES)),
    body=st.dictionaries(st.sampled_from(_BODY_KEYS), _JSON, max_size=4),
)
def test_coalescer_whole_frame_take_never_raises(family: str, body: dict[str, Any]) -> None:
    queue = CoalescingQueue(family, coalesce=False)
    queue.offer(body)
    queue.take()  # refused or emitted, never an exception


def test_coalescer_footprint_keys_bars_by_generation_and_index_never_by_open_time() -> None:
    """§8.2 "Bar key", §14.4: bars that share an open time stay apart and leave in key order;
    two items of one bar merge, even in one update (#3297). Generation 1 here exercises the key's
    other half only: the coalescer does not police generations, and a swap is a `snap` (§7.4)."""
    queue = CoalescingQueue("footprint")
    cell = {"price": "1", "bid_volume": "1"}
    bar = {**_FP_BAR, "cells": [cell]}
    assert queue.offer({"bars": [{**bar, "index": 1}, {**bar, "index": 1}]})
    assert queue.offer({"bars": [bar, {**bar, "generation": 1}]})
    [frame] = queue.take()
    assert [(b["generation"], b["index"], b["cells"]) for b in frame.body["bars"]] == [
        (0, 0, [cell]),
        (0, 1, [{"price": "1", "bid_volume": "2"}]),
        (1, 0, [cell]),
    ]


@pytest.mark.parametrize("missing", ["generation", "index"])
def test_coalescer_footprint_whole_frame_without_its_key_is_malformed(missing: str) -> None:
    """`coalesce: false` queues whole frames, yet every bar item is checked for its key (§14.4):
    one without it, here between two keyed items, is refused as malformed at entry, as the merge
    path refuses it."""
    keyless = {k: v for k, v in _FP_BAR.items() if k != missing}
    first, last = {**_FP_BAR, "cells": []}, {**_FP_BAR, "index": 1, "cells": []}
    queue = CoalescingQueue("footprint", coalesce=False)
    assert not queue.offer({"bars": [first, {**keyless, "cells": []}, last]})
    assert (queue.refusal, queue.error) == ("malformed", "KeyError")


def test_coalescer_footprint_refuses_an_update_to_a_bar_confirmed_in_the_window() -> None:
    """A confirmed footprint bar is final (§8.2): an update to it in its window breaks the merge
    rule (`unmergeable`, a producer bug), while the next bar, at the same open time, merges."""
    queue = CoalescingQueue("footprint")
    cells = [{"price": "1", "bid_volume": "1"}]
    assert queue.offer({"bars": [{**_FP_BAR, "confirm": True, "cells": cells}]})
    assert queue.offer({"bars": [{**_FP_BAR, "index": 1, "cells": cells}]})
    assert not queue.offer({"bars": [{**_FP_BAR, "confirm": False, "cells": cells}]})
    assert queue.refusal == "unmergeable"


def test_coalescer_footprint_a_truthy_confirm_counts_as_confirmed() -> None:
    """`confirm` is read by truthiness, as `BarCoalescer` reads it: a truthy non-boolean makes
    the next update to the bar unmergeable (a re-snapshot), not a merge into a confirmed bar."""
    queue = CoalescingQueue("footprint")
    cells = [{"price": "1", "bid_volume": "1"}]
    assert queue.offer({"bars": [{**_FP_BAR, "confirm": 1, "cells": cells}]})
    assert not queue.offer({"bars": [{**_FP_BAR, "confirm": False, "cells": cells}]})
    assert queue.refusal == "unmergeable"


def test_coalescer_footprint_sums_exactly_or_refuses() -> None:
    """The largest summed value (`1E+_MAX_EXPONENT`) plus a fraction is exact while the sum fits
    `_EXACT.prec` digits; one more fraction digit is refused, never rounded."""
    whole = _MAX_EXPONENT + 1  # integer digits of 1E+_MAX_EXPONENT
    fits = _EXACT.prec - whole  # fraction digits that still fit beside them
    big = {"price": "1", "bid_volume": f"1E+{_MAX_EXPONENT}"}
    queue = CoalescingQueue("footprint")
    queue.offer({"bars": [{**_FP_BAR, "cells": [big]}]})
    queue.offer({"bars": [{**_FP_BAR, "cells": [{"price": "1", "bid_volume": f"1E-{fits}"}]}]})
    [frame] = queue.take()
    exact = "1" + "0" * _MAX_EXPONENT + "." + "0" * (fits - 1) + "1"
    assert frame.body["bars"][0]["cells"][0]["bid_volume"] == exact
    over = {"price": "1", "bid_volume": f"1E-{fits + 1}"}  # `_EXACT.prec` + 1 digits: inexact
    queue.offer({"bars": [{**_FP_BAR, "cells": [big]}]})
    assert not queue.offer({"bars": [{**_FP_BAR, "cells": [over]}]})
    assert queue.overflowed and queue.error == "Inexact"


def test_coalescer_heatmap_discarded_stale_column_keeps_the_next_lone_update_verbatim() -> None:
    queue = CoalescingQueue("heatmap")
    root = {"symbol": "X", "time_bucket_ms": 100}
    queue.offer({**root, "columns": [_column(0)]})
    queue.take()
    queue.offer({**root, "columns": [_column(0, complete=False)]})  # a sent bucket: discarded
    part = Frame(HEATMAP_COLUMN)
    queue.offer({**root, "columns": [_column(100)]}, part)
    [frame] = queue.take()
    assert frame.part is part  # left verbatim, with its binary part


def test_coalescer_heatmap_root_fields_seen_are_bounded() -> None:
    """Every in-bound offer is accepted; the first root field past the bound is refused. Each
    update carries `symbol`, so it takes one of the `MAX_PENDING_KEYS` slots itself."""
    fixed = {"symbol": "X"}
    queue = CoalescingQueue("heatmap")
    for i in range(MAX_PENDING_KEYS - len(fixed)):
        assert queue.offer({**fixed, f"k{i}": i})
        queue.take()
    assert not queue.overflowed
    assert not queue.offer({**fixed, "past-the-bound": 0})
    assert queue.refusal == "full"
    queue.clear()
    assert queue.offer({"symbol": "X"})  # the refusal discarded the overgrown merge


def test_coalescer_take_turns_an_unreadable_frame_into_an_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defence in depth behind `validate`: `take()` never raises, it overflows."""
    queue = CoalescingQueue("heatmap", coalesce=False)
    monkeypatch.setattr(queue._merge, "validate", lambda body: None)
    assert queue.offer({"symbol": "X", "columns": [3]})
    assert queue.take() == [] and queue.overflowed


class _Boom:
    """A producer bug no merge rule anticipates: reading it raises."""

    def __str__(self) -> str:
        raise RuntimeError("producer bug")

    def __deepcopy__(self, memo: Any) -> Any:
        raise RuntimeError("producer bug")


class _GetRaises(dict[str, Any]):
    def get(self, key: str, default: Any = None) -> Any:
        raise RuntimeError("producer bug")


@pytest.mark.parametrize(
    ("family", "body"),
    [
        ("book", {"bids": [["1", "1"]], "asks": [], "meta": _Boom()}),
        ("profile", {"symbol": "X", "kind": "volume", "profiles": [_Boom()]}),
        ("positions", {"positions": [{"id": "p1", "updated_at_ms": 1, "x": _Boom()}]}),
    ],
    ids=["merge-size", "frame-size", "private-deepcopy"],
)
def test_coalescer_any_error_a_payload_raises_is_refused_as_malformed(
    family: str, body: Body
) -> None:
    queue = CoalescingQueue(family)
    assert not queue.offer(body)
    assert (queue.refusal, queue.error, queue.pending_bytes) == ("malformed", "RuntimeError", 0)


def _cancelled(*_: Any) -> Any:
    raise asyncio.CancelledError


@pytest.mark.parametrize(
    ("hook", "coalesce", "step"),
    [
        ("merge", True, lambda queue: queue.offer(_level("1"))),
        ("validate", False, lambda queue: queue.offer(_level("1"))),
        ("merge", False, lambda queue: queue.set_coalesce(True)),
        ("emitted", True, lambda queue: queue.take()),
    ],
    ids=["offer-merge", "offer-validate", "set-coalesce-fold", "take-emitted"],
)
def test_coalescer_cancellation_inside_a_step_reaches_the_caller_unrefused(
    monkeypatch: pytest.MonkeyPatch,
    hook: str,
    coalesce: bool,
    step: Callable[[CoalescingQueue], object],
) -> None:
    """A `CancelledError` raised inside a coalescing step (here by a merge rule or validation
    hook) reaches the caller: it is never swallowed, nor counted as a refused update (#3297)."""
    queue = CoalescingQueue("book", coalesce=coalesce)
    if hook != "validate":
        assert queue.offer(_level("0"))  # pending: a merge, or a whole frame for the fold
    monkeypatch.setattr(queue._merge, hook, _cancelled)
    with pytest.raises(asyncio.CancelledError):
        step(queue)
    assert (queue.refusal, queue.error) == (None, None)


def test_coalescer_take_refuses_a_frame_it_cannot_record_as_sent() -> None:
    queue = CoalescingQueue("heatmap", coalesce=False)
    assert queue.offer({"symbol": "X", "time_bucket_ms": 100, "columns": [_GetRaises(_column(0))]})
    assert queue.take() == []
    assert (queue.refusal, queue.error) == ("malformed", "RuntimeError")
    queue.clear()
    assert (queue.refusal, queue.error) == (None, None)


def test_coalescer_byte_bound_refuses_and_frees_every_buffer_at_once() -> None:
    queue = CoalescingQueue("book", max_bytes=40)
    assert queue.offer(_level("1")) and queue.offer(_level("2"))  # 23 + 9 estimated bytes
    assert not queue.offer(_level("3"))
    assert (queue.refusal, queue.pending_bytes) == ("full", 0)  # before any `clear()`
    frames = CoalescingQueue("profile", max_bytes=40)
    assert not frames.offer({"symbol": "X", "kind": "volume", "profiles": [{"pad": "x" * 30}]})
    assert frames.refusal == "full"


def test_coalescer_metrics_params_key_is_canonical_json_for_any_params() -> None:
    queue = CoalescingQueue("metrics")
    for params, v in (
        ({"k": Decimal("1.5"), "w": [Decimal("5")]}, "1"),
        ({"w": (Decimal("5"),), "k": Decimal("1.5")}, "2"),  # the same series
        ({"k": Decimal("2.5"), 1: "x"}, "3"),  # another series, with a non-string key
    ):
        item = {"metric": "atr", "t_ms": 1, "v": v, "params": params}
        assert queue.offer({"symbol": "X", "series": [item]})
    [frame] = queue.take()
    assert [s["v"] for s in frame.body["series"]] == ["2", "3"]


def _delta(*records: tuple[int, int, int], flags: int = 0, ts: int = 0) -> Frame:
    return Frame(BOOK_DELTA, records, flags, price_scale=1, qty_scale=3, ts_base_ms=ts)


def test_coalescer_merged_book_window_is_one_cvwb_delta_at_the_latest_part() -> None:
    queue = CoalescingQueue("book")
    low, high, top = "-922337203685477580.8", "922337203685477580.7", "18446744073709551.615"
    for bids, asks, part in (  # the i64 and u64 extremes at scales 1 and 3 are in range
        ([["100", "1"], [low, "0"]], [["103", "2"]], _delta(ts=1)),
        ([["99.5", "0"]], [["101", "5"], [high, top]], _delta(flags=FLAG_ESTIMATED, ts=2)),
        ([["100", "3"]], [], _delta(flags=FLAG_REPLAY, ts=3)),  # only `estimated` is carried over
    ):
        queue.offer({"bids": bids, "asks": asks}, part)
    [frame] = queue.take()
    sold = ((0, 1000, 3000), (0, 995, 0), (0, -(2**63), 0))  # bids high to low; "0" deletes
    bought = ((1, 1010, 5000), (1, 1030, 2000), (1, 2**63 - 1, 2**64 - 1))  # asks low to high
    assert frame.part == _delta(*sold, *bought, flags=FLAG_ESTIMATED, ts=3)


_PART, _BID = _delta(), ["101", "1"]
_OTHER_KIND = replace(_PART, body_kind=HEATMAP_COLUMN)


@pytest.mark.parametrize(
    ("first", "bid", "second"),
    [
        pytest.param(None, _BID, _PART, id="first-without-a-part"),
        pytest.param(_OTHER_KIND, _BID, _PART, id="first-not-a-book-delta"),
        pytest.param(_PART, _BID, _OTHER_KIND, id="next-not-a-book-delta"),
        pytest.param(_PART, _BID, replace(_PART, price_scale=0), id="other-price-scale"),
        pytest.param(_PART, _BID, replace(_PART, qty_scale=2), id="other-qty-scale"),
        pytest.param(_PART, ["100.55", "1"], _PART, id="inexact-price"),
        pytest.param(_PART, ["101", "1.0005"], _PART, id="inexact-size"),
        pytest.param(_PART, ["100.0000000000000000000000000001", "1"], _PART, id="over-28-digits"),
        pytest.param(_PART, ["101", "abc"], _PART, id="size-not-a-number"),
        pytest.param(_PART, ["101", "Infinity"], _PART, id="size-infinite"),
        pytest.param(_PART, ["922337203685477580.8", "1"], _PART, id="price-above-i64"),
        pytest.param(_PART, ["-922337203685477580.9", "1"], _PART, id="price-below-i64"),
        pytest.param(_PART, ["101", "18446744073709551.616"], _PART, id="size-above-u64"),
        pytest.param(_PART, ["101", "-0.001"], _PART, id="size-negative"),
    ],
)
def test_coalescer_merged_book_window_is_structured_unless_every_part_fits(
    first: Frame | None, bid: list[str], second: Frame
) -> None:
    queue = CoalescingQueue("book")
    queue.offer({"bids": [["100", "1"]], "asks": []}, first)
    queue.offer({"bids": [bid], "asks": []}, second)
    [frame] = queue.take()
    assert (frame.part, frame.coalesced_count) == (None, 2)
