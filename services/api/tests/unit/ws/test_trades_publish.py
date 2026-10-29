"""E22-T02 (#654): `trades.{symbol}` over the big-trade tape (`ws/trades_publish.py`), through a
real `ConnectionAuthz`, `SequencingHub` and `TopicEmitter`: every structured frame is validated
against 23's schemas as it is pushed (`_seq_support.Conn`), and every binary one is decoded and
its twin validated. No network, no bus wait, no sleep: prints are offered and windows ticked by
hand on fake clocks."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.bus.bus import Bus
from candleviewer.bus.models import StreamInvalidated, Topic
from candleviewer.exchange.base.models import TradeEvent
from candleviewer.orderflow import limits as L
from candleviewer.orderflow.bigtrade_models import BigTradeConfig
from candleviewer.ws.binary import TRADES, decode_b64
from candleviewer.ws.cvwb_vectors import structured
from candleviewer.ws.metrics import (
    cv_ws_tape_frames_coalesced_total,
    cv_ws_tape_prints_dropped_total,
    cv_ws_trades_subscribe_rejected_total,
)
from candleviewer.ws.permissions import Subscription
from candleviewer.ws.trades_publish import SNAPSHOT_ITEMS, options_of
from tests._bigtrades import CH, T0_US, Tape, World, event
from tests.contract.ws._harness import check_schema
from tests.unit.ws._seq_support import Conn

_CH = CH


def _data(conn: Conn) -> list[dict[str, Any]]:
    return [f for f in conn.take() if f["t"] in {"snap", "d"}]


def _twin(frame: dict[str, Any], threshold: str) -> dict[str, Any]:
    """A binary frame's §14.2 form, with the threshold a binary client keeps (§3.4)."""
    part = decode_b64(frame["p"])
    assert part.body_kind == TRADES
    body = {"symbol": "BTCUSDT", "big_trade_threshold": threshold, **structured(part)}
    check_schema("cv://ws/v1/trades.schema.json", body, "binary twin")
    return body


def _value(counter: Any, **labels: str) -> float:
    child = counter.labels(**labels) if labels else counter
    return float(child._value.get())


# -- Scenario: Server-side filtering is never silent -------------------------------------------


def test_trades_min_size_drops_are_counted_in_dropped_across_frame_boundaries() -> None:
    w = World()
    conn = w.conn()
    _, sub = w.sub(conn, {"min_size": "0.5", "encoding": "structured"})
    assert sub is not None
    conn.take()
    before = _value(cv_ws_tape_prints_dropped_total, reason="min_size")
    w.window([event(1, "0.1"), event(2, "0.6"), event(3, "0.2")])
    w.window([event(4, "0.3")])  # only drops: a frame still goes out
    w.window([event(5, "0.9"), event(6, "0.4")])
    frames = [f["p"] for f in _data(conn)]
    assert [([t["id"] for t in p["trades"]], p["dropped"]) for p in frames] == [
        (["t00002"], 2), ([], 1), (["t00005"], 1)
    ]  # fmt: skip
    assert sum(p["dropped"] for p in frames) == 4
    assert _value(cv_ws_tape_prints_dropped_total, reason="min_size") - before == 4


def test_trades_pending_is_bounded_and_an_overflow_is_counted_in_dropped() -> None:
    """More items than the pending bound before one frame: the oldest are shed, and their prints
    are counted in `dropped` (`overflow`), beside the `min_size` drops: never silent."""
    w = World(pending_max=3)
    conn = w.conn()
    _, sub = w.sub(conn, {"min_size": "0.05", "encoding": "structured"})
    assert sub is not None
    conn.take()
    over = _value(cv_ws_tape_prints_dropped_total, reason="overflow")
    small = _value(cv_ws_tape_prints_dropped_total, reason="min_size")
    w.window([event(i, "0.1") for i in range(1, 6)] + [event(6, "0.01")])
    [frame] = _data(conn)
    assert [t["id"] for t in frame["p"]["trades"]] == ["t00003", "t00004", "t00005"]
    assert frame["p"]["dropped"] == 3  # two shed, one below min_size
    assert _value(cv_ws_tape_prints_dropped_total, reason="overflow") - over == 2
    assert _value(cv_ws_tape_prints_dropped_total, reason="min_size") - small == 1
    w.window([event(7, "0.1")])
    [after] = _data(conn)
    assert (after["p"]["dropped"], [t["id"] for t in after["p"]["trades"]]) == (0, ["t00007"])


def test_trades_a_shed_cluster_counts_every_print_it_held_in_dropped() -> None:
    """Two two-print clusters close in one window with room for one: the shed cluster's two
    prints, not one item, are counted in `dropped` (`overflow`)."""
    w = World(pending_max=1)
    conn = w.conn()
    w.sub(conn, {"cluster_window_ms": 250, "cluster_tolerance_ticks": 1, "encoding": "structured"})
    conn.take()
    over = _value(cv_ws_tape_prints_dropped_total, reason="overflow")
    buys, sells = (
        [event(1, "0.2"), event(2, "0.3")],
        [event(3, "0.1", side="sell"), event(4, "0.15", side="sell")],
    )
    w.window(buys + sells)
    w.now_us = T0_US + 2_000_000  # the reader's clock passes every deadline and the grace
    w.window()
    frames = _data(conn)
    kept = [t["cluster_size"] for f in frames for t in f["p"]["trades"]]
    assert kept == [2] and sum(f["p"]["dropped"] for f in frames) == 2
    assert _value(cv_ws_tape_prints_dropped_total, reason="overflow") - over == 2


# -- Scenario: Clustering is signalled on both encodings ---------------------------------------


def test_trades_clusters_reach_binary_and_structured_subscribers_with_one_membership() -> None:
    w = World()
    binary, plain = w.conn(), w.conn()
    opts = {"cluster_window_ms": 250, "cluster_tolerance_ticks": 1}
    w.sub(binary, {**opts, "encoding": "binary"})
    w.sub(plain, {**opts, "encoding": "structured"})
    binary.take(), plain.take()
    w.window([event(1, "0.2"), event(2, "1.5"), event(3, "0.1", side="sell")])
    w.now_us = T0_US + 2_000_000  # the reader's clock passes every deadline and the grace
    w.window()
    w.window([event(3000, "0.4")])
    w.now_us = T0_US + 5_000_000
    w.window()
    b, s = _data(binary), _data(plain)
    assert len(b) == len(s) == 2
    assert b[0]["e"] == "j" and b[0]["p"] == s[0]["p"]  # a cluster leaves structured (§3.4)
    sizes = {t["id"]: (t["cluster_size"], t["is_big_trade"]) for t in s[0]["p"]["trades"]}
    assert sizes == {"t00001": (2, True), "t00003": (1, False)}
    assert b[1]["e"] == "b64"  # no cluster, drop or new threshold: kind 3 says everything
    twin = _twin(b[1], s[1]["p"]["big_trade_threshold"])
    assert [(t["ts_ms"], Decimal(t["size"])) for t in twin["trades"]] == [
        (t["ts_ms"], Decimal(t["size"])) for t in s[1]["p"]["trades"]
    ]
    assert decode_b64(b[1]["p"]).records[0][4] & 0b0100 == 0  # bit2: never sent (§3.4)


def test_trades_binary_records_carry_the_big_trade_bit_and_block_flag() -> None:
    w = World()
    conn = w.conn()
    w.sub(conn, {"encoding": "binary"})
    conn.take()
    w.window([event(1, "2", block=True), event(2, "0.1")])
    [frame] = _data(conn)
    flags = [r[4] for r in decode_b64(frame["p"]).records]
    assert flags == [0b1001, 0]  # bit3 big trade, bit0 block; bits 4-7 are 0


@pytest.mark.parametrize(
    ("why", "batch"),
    [
        ("dropped", [event(1, "0.0001")]),
        ("unscaled", [event(1, "0.00011")]),
    ],
)
def test_trades_a_window_that_kind_3_cannot_say_leaves_structured(
    why: str, batch: list[TradeEvent]
) -> None:
    w = World()
    conn = w.conn()
    opts: dict[str, Any] = {"encoding": "binary"}
    if why == "dropped":
        opts["min_size"] = "0.001"
        batch = [*batch, event(2, "0.5")]
    w.sub(conn, opts)
    conn.take()
    w.window(batch)
    [frame] = _data(conn)
    assert frame["e"] == "j"


def test_trades_a_changed_threshold_leaves_structured_then_binary_again() -> None:
    """A percentile threshold moves at a 5 s print-time refresh: the frame after the move says
    so structured (kind 3 has no slot for it, §3.4), and the next goes binary again."""
    w = World(config=BigTradeConfig("percentile", Decimal("50"), 60_000))
    conn = w.conn()
    _, sub = w.sub(conn, {"encoding": "binary"})
    assert sub.effective["big_trade_threshold"] == "0"
    conn.take()
    w.window([event(i, "0.001" if i % 2 else "0.002") for i in range(1, 40)])
    w.window([event(6000, "0.001")])  # the next 5 s slot: the threshold is estimated
    w.window([event(6001, "0.001")])
    first, second, third = _data(conn)
    assert first["e"] == "b64"
    assert second["e"] == "j" and second["p"]["big_trade_threshold"] != "0"
    assert third["e"] == "b64"


# -- Scenario: Out-of-range options are rejected ------------------------------------------------


@pytest.mark.parametrize(
    ("opts", "field", "message", "reason"),
    [
        ({"cluster_window_ms": 999_999}, "cluster_window_ms", "must be 0 to 2000", "cluster_range"),
        ({"cluster_window_ms": 2001}, "cluster_window_ms", "must be 0 to 2000", "cluster_range"),
        ({"cluster_tolerance_ticks": 21}, "cluster_tolerance_ticks", "0 to 20", "cluster_range"),
        ({"min_size": "0.0001"}, "min_size", "floor (0.001)", "min_size_floor"),
        ({"min_size": "0"}, "min_size", "floor (0.001)", "min_size_floor"),
    ],
)
def test_trades_out_of_range_options_are_refused_and_nothing_is_held(
    opts: dict[str, Any], field: str, message: str, reason: str
) -> None:
    w = World()
    conn = w.conn()
    before = _value(cv_ws_trades_subscribe_rejected_total, reason=reason)
    result, sub = w.sub(conn, opts)
    assert sub is None and result["ok"] is False
    assert (result["error"]["code"], result["error"]["field"]) == ("invalid_options", field)
    assert message in result["error"]["message"]
    assert conn.authz.by_id == {} and w.topic._symbols == {}
    assert _value(cv_ws_trades_subscribe_rejected_total, reason=reason) - before == 1


def test_trades_a_decimal_option_longer_than_32_characters_is_refused() -> None:
    """E22 security lens: a decimal option's text is capped (`MAX_DECIMAL_TEXT`), so a crafted
    `min_size` is refused by the registry before it is parsed or compared."""
    w = World()
    at_cap = "1." + "0" * 30  # 32 characters: accepted
    result, sub = w.sub(w.conn(), {"min_size": at_cap})
    assert result["ok"] is True and sub is not None
    conn = w.conn()
    result, sub = w.sub(conn, {"min_size": at_cap + "0"})
    assert sub is None and result["ok"] is False
    assert (result["error"]["code"], result["error"]["field"]) == ("invalid_options", "min_size")
    assert conn.authz.by_id == {}


def test_trades_ack_echoes_the_options_and_the_engine_threshold() -> None:
    w = World(config=BigTradeConfig())
    conn = w.conn()
    result, sub = w.sub(conn, {"min_size": "0.5", "cluster_window_ms": 2000})
    assert sub is not None and result["ok"] is True
    eff = result["effective"]
    assert {k: eff[k] for k in ("min_size", "cluster_window_ms", "cluster_tolerance_ticks")} == {
        "min_size": "0.5", "cluster_window_ms": 2000, "cluster_tolerance_ticks": 0
    }  # fmt: skip
    assert (eff["big_trade_threshold"], eff["big_trade_mode"]) == ("250000", "notional")
    check_schema("cv://ws/v1/sub_ok.schema.json", {"results": [result]}, "sub_ok")
    refused = World().conn()
    assert refused.authz.admit({"ch": _CH, "opts": {"cluster_window_ms": 5000}})[0]["ok"] is False


def test_trades_per_user_cap_and_option_set_cap_refuse_with_nothing_held() -> None:
    w = World()
    t = w.topic
    for n in range(L.TRADES_SUBS_PER_USER_MAX):
        t.hold(f"c{n}", "u1", "BTCUSDT", options_of({}))
    with pytest.raises(Exception, match="At most 60 trades subscriptions per user"):
        t.hold("c60", "u1", "BTCUSDT", options_of({}))
    t.hold("x1", "u2", "BTCUSDT", options_of({"min_size": "0.1"}))
    lease = t.hold("x2", "u2", "BTCUSDT", options_of({"min_size": "0.2"}))
    with pytest.raises(Exception, match="option sets per symbol"):
        t.hold("x3", "u2", "BTCUSDT", options_of({"min_size": "0.3"}))
    moved = t.retune(lease, options_of({"min_size": "0.3"}))  # its own set is let go first
    assert moved.options.min_size == Decimal("0.3") and t.retune(moved, moved.options) is moved
    with pytest.raises(Exception, match="option sets per symbol"):
        t.hold("x4", "u2", "BTCUSDT", options_of({"min_size": "0.4"}))
    with pytest.raises(Exception, match="option sets per symbol"):
        t.check_retune(t.hold("x5", "u2", "BTCUSDT", options_of({"min_size": "0.1"})),
                       options_of({"min_size": "0.4"}))  # fmt: skip
    t.release(moved)
    assert len(t._symbols["BTCUSDT"].options) == 2  # {} and 0.1


def test_trades_pending_leases_count_toward_both_caps() -> None:
    """A lease held while the trade stream (or the tick size) is unknown has no tape yet, but it
    counts toward SR-E22-06 (60 per user) and SR-E22-07 (2 option sets per symbol per user)."""
    w = World()
    w.tape = None
    t = w.topic
    for n in range(L.TRADES_SUBS_PER_USER_MAX):
        t.hold(f"c{n}", "u1", "BTCUSDT", options_of({}))
    assert t._symbols["BTCUSDT"].tape is None  # every one of them pending
    with pytest.raises(Exception, match="At most 60 trades subscriptions per user"):
        t.hold("c60", "u1", "BTCUSDT", options_of({}))
    t.hold("x1", "u2", "BTCUSDT", options_of({"min_size": "0.1"}))
    t.hold("x2", "u2", "BTCUSDT", options_of({"min_size": "0.2"}))
    with pytest.raises(Exception, match="option sets per symbol"):
        t.hold("x3", "u2", "BTCUSDT", options_of({"min_size": "0.3"}))
    assert all(o.tape is None for o in t._symbols["BTCUSDT"].options.values())


def test_trades_ctl_min_size_moves_the_lease_and_never_resnapshots() -> None:
    w = World()
    conn = w.conn()
    _, sub = w.sub(conn, {"min_size": "0.5", "encoding": "structured"})
    conn.take()
    effective, resnapshot, _ = conn.authz.ctl(_CH, {"min_size": "0.05"})
    assert resnapshot is False and effective["min_size"] == "0.05"
    assert sub.trades_lease.options.min_size == Decimal("0.05")
    assert sub.effective["big_trade_threshold"] == "1"
    w.window([event(1, "0.1")])
    [frame] = _data(conn)
    assert [t["id"] for t in frame["p"]["trades"]] == ["t00001"]
    with pytest.raises(Exception, match="floor"):
        conn.authz.ctl(_CH, {"min_size": "0.0001"})
    assert sub.trades_lease.options.min_size == Decimal("0.05")  # a refused ctl changes nothing


# -- Scenario: Coalescing is visible ------------------------------------------------------------


def test_trades_a_burst_coalesces_with_its_batch_count_and_loses_no_print() -> None:
    w = World()
    conn = w.conn()
    w.sub(conn, {"encoding": "structured"})
    conn.take()
    before = _value(cv_ws_tape_frames_coalesced_total)
    batches = [[event(3 * b + i, "0.1") for i in range(3)] for b in range(5)]
    w.window(*batches)
    [frame] = _data(conn)
    p = frame["p"]
    assert (p["coalesced"], p["coalesced_count"]) == (True, 5)
    assert [t["id"] for t in p["trades"]] == [e.trade_id for b in batches for e in b]
    w.window([event(100, "0.1")])
    [lone] = _data(conn)
    assert (lone["p"]["coalesced"], lone["p"]["coalesced_count"]) == (False, 1)
    assert _value(cv_ws_tape_frames_coalesced_total) - before == 1


def test_trades_a_merged_binary_window_sets_the_coalesced_header_bit() -> None:
    w = World()
    conn = w.conn()
    w.sub(conn, {"encoding": "binary"})
    conn.take()
    w.window([event(1, "0.1")], [event(2, "0.1")])
    [frame] = _data(conn)
    assert decode_b64(frame["p"]).flags & 0b0010


# -- snapshot, release, resync, lifecycle -------------------------------------------------------


def test_trades_snapshot_is_the_last_200_items_warm_from_the_hot_tape() -> None:
    w = World(Tape([event(i, "0.1") for i in range(1, 251)]))
    conn = w.conn()
    w.sub(conn, {"encoding": "structured"})
    [snap] = _data(conn)
    assert snap["t"] == "snap"
    ids = [t["id"] for t in snap["p"]["trades"]]
    assert len(ids) == SNAPSHOT_ITEMS and ids[0] == "t00051" and ids[-1] == "t00250"
    assert snap["p"]["big_trade_threshold"] == "1"
    binary = w.conn()
    w.sub(binary, {"encoding": "binary"})
    [bsnap] = _data(binary)
    assert bsnap["e"] == "b64" and len(decode_b64(bsnap["p"]).records) == SNAPSHOT_ITEMS


def test_trades_snapshot_with_a_cluster_is_structured_for_a_binary_subscriber() -> None:
    w = World(Tape([event(1, "0.1"), event(2, "0.1"), event(900, "0.1")]))
    conn = w.conn()
    w.sub(conn, {"encoding": "binary", "cluster_window_ms": 250})
    [snap] = _data(conn)
    assert snap["e"] == "j" and snap["p"]["trades"][0]["cluster_size"] == 2


def test_trades_unsubscribe_releases_every_tape() -> None:
    w = World()
    conn = w.conn()
    w.sub(conn, {"min_size": "0.5"})
    assert w.topic._symbols
    conn.authz.unsubscribe(_CH)
    assert w.topic._symbols == {} and w.topic._per_user == {}


def test_trades_a_lost_bus_batch_catches_up_and_resnapshots() -> None:
    w = World()
    conn = w.conn()
    w.sub(conn, {"encoding": "structured"})
    conn.take()
    w.tape = Tape([event(1, "0.1"), event(2, "0.1")])
    w.topic.offer([StreamInvalidated(topic="demo.md.BTCUSDT.trade", ts_event=T0_US)])
    [snap] = _data(conn)
    assert snap["t"] == "snap" and [t["id"] for t in snap["p"]["trades"]] == []
    w.window()
    [frame] = _data(conn)
    assert [t["id"] for t in frame["p"]["trades"]] == ["t00001", "t00002"]


def test_trades_a_lease_waits_for_the_trade_stream_then_snaps() -> None:
    """With no trade stream yet (the public WS off, or a symbol with no tick size), the
    subscription is held and stays pending; the first window that finds the stream snaps it."""
    w = World()
    w.tape = None
    conn = w.conn()
    result, sub = w.sub(conn, {"encoding": "structured"})
    assert result["ok"] is True and sub is not None and sub.snapshot_pending
    assert result["effective"]["big_trade_threshold"] == "1"  # the config's, until it opens
    w.topic.offer([event(1, "0.1")])  # nothing is read while it waits
    assert w.window() == 0 and _data(conn) == []
    w.tape = Tape([event(1, "0.1"), event(2, "0.1")])
    w.window()
    [snap] = _data(conn)
    assert snap["t"] == "snap" and [t["id"] for t in snap["p"]["trades"]] == ["t00001", "t00002"]
    w.window([event(3, "0.1")])
    [frame] = _data(conn)
    assert [t["id"] for t in frame["p"]["trades"]] == ["t00003"]


def test_trades_a_pending_percentile_symbol_echoes_the_notional_default_never_zero() -> None:
    """§6.1 echoes `big_trade_threshold` always; before the tape opens a percentile has no value,
    so the ack carries the server's notional default and the first snap the engine's own."""
    w = World(config=BigTradeConfig("percentile", Decimal("99")))
    w.tape = None
    conn = w.conn()
    result, sub = w.sub(conn, {"encoding": "structured"})
    assert sub is not None and sub.snapshot_pending
    eff = result["effective"]
    default = format(BigTradeConfig().value, "f")  # the server's notional default
    assert (eff["big_trade_threshold"], eff["big_trade_mode"]) == (default, "percentile")
    w.tape = Tape([event(1, "0.1")])
    w.window()
    [snap] = _data(conn)
    assert snap["t"] == "snap"
    assert snap["p"]["big_trade_threshold"] == w.topic.echo("BTCUSDT")["big_trade_threshold"]


def test_trades_a_subscription_without_a_lease_is_never_served_from_the_live_tape() -> None:
    w = World()
    _, sub = w.conn().authz.admit({"ch": _CH})  # admitted, never upstream: no lease
    assert isinstance(sub, Subscription) and sub.trades_lease is None
    assert w.topic.build(sub) is None and w.topic.generation(sub) == 0
    assert w.topic.continuity(sub, None) is False


def test_trades_topic_drains_its_bus_subscription_and_stops() -> None:
    """The prints arrive on `{env}.md.{symbol}.trade`; the topic's task drains and publishes them,
    and `stop` lets go of the task and the bus subscription (event-loop yields only, no sleep)."""
    w = World()
    bus = Bus()
    w.topic._bus = bus
    conn = w.conn()
    w.sub(conn, {"encoding": "structured"})
    conn.take()

    async def run() -> None:
        w.topic.open()
        topic = Topic(env="demo", domain="md", symbol="BTCUSDT", detail="trade")
        await bus.publish(topic, event(1, "0.1"))
        await bus.publish(topic, event(2, "0.1", symbol="ETHUSDT"))  # held by no subscription
        w.topic.start()
        for _ in range(20):
            await asyncio.sleep(0)  # a yield, never a wait
            if conn.out:
                break
        await w.topic.stop()
        assert w.topic.pump() == 0  # no subscription left to drain

    asyncio.run(run())
    assert [t["id"] for f in _data(conn) for t in f["p"]["trades"]] == ["t00001"]
