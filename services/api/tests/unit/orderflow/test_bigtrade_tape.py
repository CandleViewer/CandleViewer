"""E22-T02 (#654): the big-trade tape that `trades.{symbol}` and `GET /market/trades` both serve
(`orderflow/bigtrade_tape.py`): `min_size` before clustering, cluster items, flags, tick
direction and the threshold (no network, no clock)."""

from __future__ import annotations

from decimal import Decimal

from candleviewer.orderflow import limits as L
from candleviewer.orderflow.bigtrade_models import BigTradeConfig
from candleviewer.orderflow.bigtrade_tape import Options, OptionTape, SymbolTape, tape_page
from tests._bigtrades import TICK, event

_SMALL = BigTradeConfig("absolute_size", Decimal("1"))


def test_tape_min_size_drops_raw_prints_and_counts_them() -> None:
    tape, opt = SymbolTape("BTCUSDT", TICK, _SMALL), OptionTape(TICK, Options(Decimal("0.5")))
    items = opt.add(tape.read([event(1, "0.1"), event(2, "0.6"), event(3, "0.2")]))
    assert [(i.first.event.trade_id, i.size) for i in items] == [("t00002", Decimal("0.6"))]
    assert opt.take_dropped() == 2
    assert opt.take_dropped() == 0  # since the previous frame


def test_tape_min_size_applies_before_clustering() -> None:
    """A dropped print never joins a cluster: its size is not in the total."""
    opt = OptionTape(TICK, Options(Decimal("0.5"), 250, 1))
    tape = SymbolTape("BTCUSDT", TICK, _SMALL)
    opt.add(tape.read([event(1, "0.6"), event(2, "0.1"), event(3, "0.7")]))
    [item] = opt.flush()
    assert (item.cluster_size, item.size, opt.dropped) == (2, Decimal("1.3"), 1)


def test_tape_cluster_item_takes_first_print_total_size_and_any_member_flag() -> None:
    tape = SymbolTape("BTCUSDT", TICK, _SMALL)
    opt = OptionTape(TICK, Options(None, 250, 2))  # one bucket two ticks wide
    prints = tape.read(
        [event(1, "0.2", price="82745.8"), event(2, "1.5", price="82745.9"), event(3, "0.3")]
    )
    assert [p.big for p in prints] == [False, True, False]
    assert opt.add(prints) == []  # open: a cluster leaves once it closes
    [item] = opt.flush()
    wire = item.wire()
    assert (
        wire["id"] == "t00001" and wire["price"] == "82745.8" and wire["ts_ms"] == 1_792_391_736_001
    )
    assert (wire["size"], wire["cluster_size"], wire["is_big_trade"]) == ("2.0", 3, True)


def test_tape_cluster_closes_by_print_time_and_on_expiry() -> None:
    tape = SymbolTape("BTCUSDT", TICK, _SMALL)
    opt = OptionTape(TICK, Options(None, 250, 0))
    first = opt.add(tape.read([event(1, "0.1"), event(100, "0.1")]))
    assert first == []
    closed = opt.add(tape.read([event(400, "0.1")]))  # 399 ms after t1: past the 250 ms window
    assert [(i.first.event.trade_id, i.cluster_size) for i in closed] == [("t00001", 2)]
    late = opt.expire(event(400, "0").ts_event + 300_000)
    assert [(i.first.event.trade_id, i.cluster_size) for i in late] == [("t00400", 1)]
    assert opt.expire(10**18) == [] and OptionTape(TICK, Options()).expire(10**18) == []


def test_tape_cluster_membership_is_not_bounded_by_the_engine_id_list() -> None:
    """A cluster of more than `CLUSTER_IDS_MAX` prints still counts every member."""
    n = L.CLUSTER_IDS_MAX + 6
    tape, opt = SymbolTape("BTCUSDT", TICK, _SMALL), OptionTape(TICK, Options(None, 2000, 0))
    opt.add(tape.read([event(i, "0.001", ts_us=event(0, "1").ts_event + i) for i in range(n)]))
    [item] = opt.flush()
    assert item.cluster_size == n and item.size == Decimal("0.001") * n


def test_tape_sides_and_buckets_cluster_apart() -> None:
    tape, opt = SymbolTape("BTCUSDT", TICK, _SMALL), OptionTape(TICK, Options(None, 250, 0))
    opt.add(tape.read([event(1, "0.1"), event(2, "0.1", side="sell"), event(3, "0.1")]))
    opt.add(tape.read([event(4, "0.1", price="82746.8")]))  # ten ticks away: another bucket
    sizes = sorted((i.first.event.trade_id, i.cluster_size) for i in opt.flush())
    assert sizes == [("t00001", 2), ("t00002", 1), ("t00004", 1)]


def test_symbol_tape_skips_prints_it_already_read_and_derives_tick_direction() -> None:
    tape = SymbolTape("BTCUSDT", TICK, _SMALL)
    a = tape.read([event(1, "0.1", price="10.0"), event(2, "0.1", price="10.1")])
    b = tape.read([event(2, "0.1", price="10.1"), event(3, "0.1", price="10.1")])
    c = tape.read([event(4, "0.1", price="10.0"), event(5, "0.1", price="10.0")])
    assert [p.tick_direction for p in a + b + c] == [
        None, "PlusTick", "ZeroPlusTick", "MinusTick", "ZeroMinusTick"
    ]  # fmt: skip
    assert tape.read([event(1, "9")]) == [] and tape.last == (event(5, "0").ts_event, "t00005")


def test_symbol_tape_reports_the_engine_threshold_and_mode() -> None:
    default = SymbolTape("BTCUSDT", TICK, BigTradeConfig())
    assert (default.threshold, default.mode) == (Decimal("250000"), "notional")
    default.read([event(1, "4")])  # 4 x 82745.8 = 330 983.2 USDT
    assert default.threshold == Decimal("250000")
    pct = SymbolTape("BTCUSDT", TICK, BigTradeConfig("percentile", Decimal("90")))
    assert pct.threshold == 0 and pct.mode == "percentile"


def test_tape_options_never_move_the_threshold() -> None:
    """The flag engine sees every print, whatever `min_size` drops (23 §6.1)."""
    events = [event(i, "0.1" if i % 2 else "2") for i in range(1, 9)]
    _, t1, _ = tape_page(events, "BTCUSDT", TICK, _SMALL, Options())
    items, t2, mode = tape_page(events, "BTCUSDT", TICK, _SMALL, Options(Decimal("1"), 250, 1))
    assert t1 == t2 == Decimal("1") and mode == "absolute_size"
    assert [i.cluster_size for i in items] == [4] and items[0].big


def test_tape_page_side_filter_keeps_flags_and_directions_of_the_whole_tape() -> None:
    events = [event(1, "0.1", price="10.0"), event(2, "2", side="sell", price="10.1")]
    events.append(event(3, "0.1", price="10.1"))
    items, _, _ = tape_page(events, "BTCUSDT", TICK, _SMALL, Options(), side="buy")
    assert [(i.first.event.trade_id, i.first.tick_direction) for i in items] == [
        ("t00001", None), ("t00003", "ZeroPlusTick")
    ]  # fmt: skip
    sells, _, _ = tape_page(events, "BTCUSDT", TICK, _SMALL, Options(), side="sell")
    assert [i.big for i in sells] == [True]
