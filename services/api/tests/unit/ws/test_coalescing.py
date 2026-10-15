from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from candleviewer.ws.binary import BOOK_DELTA, Frame
from candleviewer.ws.coalescing import (
    MAX_PENDING_FRAMES,
    SENT_COLUMNS_MEMORY,
    CoalescingQueue,
    Emission,
)

Body = dict[str, Any]
State = dict[str, Any]
_LISTS = frozenset(
    {"bids", "asks", "bars", "trades", "liquidations", "dropped", "coalesced", "coalesced_count"}
    | {"series", "tickers", "balances", "positions", "removed", "columns"}
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
        entry = state.setdefault("bars", {}).setdefault(bar["t_ms"], {"fields": {}, "cells": {}})
        entry["fields"].update((k, v) for k, v in bar.items() if k != "cells")
        for cell in bar["cells"]:
            cur = entry["cells"].setdefault(Decimal(cell["price"]), {})
            for key, value in cell.items():
                if key in ("bid_volume", "ask_volume"):
                    cur[key] = cur.get(key, Decimal(0)) + Decimal(value)  # increments (§8.2)
                elif key == "trades":
                    cur[key] = cur.get(key, 0) + value
                else:
                    cur[key] = value


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
    lambda price, bid, ask, n: {"price": price, "bid_volume": bid, "ask_volume": ask, "trades": n},
    _PRICE,
    st.sampled_from(["0.5", "1", "0.00000001", "2.000"]),
    st.sampled_from(["0.5", "1.25", "7.5"]),
    st.integers(0, 3),
)
_footprint = st.builds(
    lambda t_ms, poc, cells: {
        "symbol": "BTCUSDT",
        "bar_type": "time",
        "param": "1m",
        "bars": [{"t_ms": t_ms, "poc_price": poc, "cells": cells}],
    },
    st.sampled_from([0, 60_000]),
    _PRICE,
    st.lists(_cell, max_size=3),
)


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
_wallet = st.builds(
    lambda acc, coin, equity, at: {
        "balances": [
            {"exchange_account_id": acc, "coin": coin, "equity": equity, "updated_at_ms": at}
        ]
    },
    st.sampled_from(["a1", "a2"]),
    st.sampled_from(["USDT", "BTC"]),
    _DEC,
    st.integers(0, 5),
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
    (
        "wallet",
        st.lists(_wallet, max_size=25),
        _keyed("balances", lambda b: (b["exchange_account_id"], b["coin"]), newer=True),
    ),
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
            {"bars": [{"t_ms": 0, "cells": []}]},
            {"bars": [{"t_ms": 0, "cells": [{"price": "1", "bid_volume": "1"}]}]},
        ),
        ("ticker", {"tickers": [{"symbol": "A"}]}, {"tickers": [{"symbol": "B"}]}),
        ("positions", {"positions": [], "removed": ["p1"]}, {"positions": [], "removed": ["p2"]}),
        ("trades", {"trades": [{"id": "1"}]}, {"trades": [{"id": "2"}]}),
    ],
)
def test_coalescer_bound_reached_sets_overflowed(family: str, first: Body, grown: Body) -> None:
    queue = CoalescingQueue(family, max_keys=1, max_items=1)
    assert queue.offer(first)
    assert not queue.offer(grown)
    assert queue.overflowed


@pytest.mark.parametrize(
    ("family", "malformed"),
    [
        ("book", {"bids": [["100", "1"], ["abc", "1"]], "asks": []}),
        ("book", {"bids": [["NaN", "1"]], "asks": []}),
        ("book", {"bids": [["100", "1", "2"]], "asks": []}),
        ("bars", {"bars": [{"index": 0, "confirm": False}]}),
        ("footprint", {"bars": [{"t_ms": 0, "cells": [{"price": "1", "bid_volume": "x"}]}]}),
        ("wallet", {"balances": [{"coin": "USDT"}]}),
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
    assert queue.overflowed
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
    queue.offer({"bars": [{"t_ms": 0, "poc_price": "100", "cells": [cell]}]})
    queue.offer({"bars": [{"t_ms": 0, "poc_price": "101", "cells": [cell]}]})
    queue.offer({"bars": [{"t_ms": 60_000, "cells": [cell]}]})
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
