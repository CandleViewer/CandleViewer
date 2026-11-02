"""Gherkin scenarios and unit cases for `TimeBarBuilder` (E12-S01, 24 §3.3)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from candleviewer.bars.errors import BarsError, BarSpecError
from candleviewer.bars.models import Bar, BarBuilder, BarSpec, BarUpdate
from candleviewer.bars.time_builder import (
    TimeBarBuilder,
    bars_late_trade_dropped_total,
    bucket_bounds,
    validate_time_spec,
)
from tests.unit.bars._trades import SYM, closes, trade, us

M1 = BarSpec(kind="time", interval_ms=60_000)
H1_480 = BarSpec(kind="time", interval_ms=3_600_000, session_anchor_utc_min=480)


def _b(spec: BarSpec = M1) -> TimeBarBuilder:
    return TimeBarBuilder(spec, SYM)


def _forming(b: TimeBarBuilder) -> Bar:
    """The open bar, read on demand: a trade that only extends it emits nothing (#2022)."""
    u = b.forming()
    assert u is not None and u.kind == "update" and not u.bar.closed
    return u.bar


def _dropped(reason: str) -> float:
    return float(bars_late_trade_dropped_total.labels(symbol=SYM, reason=reason)._value.get())


def test_time_builder_satisfies_bar_builder_protocol() -> None:
    b: BarBuilder = _b()
    assert b.spec is M1


# --- Scenario: Bars close on the boundary ------------------------------------------------


def test_on_trade_boundary_trades_split_into_adjacent_bars_close_once() -> None:
    b = _b()
    out = [*b.on_trade(trade(us("10:00:59.900"), seq=1))]
    out += b.on_trade(trade(us("10:01:00.100"), seq=2))
    assert [u.kind for u in out] == ["open", "close", "open"]
    first, second = out[1].bar, out[2].bar
    assert (first.open_time, first.close_time) == (us("10:00:00"), us("10:01:00"))
    assert first.closed and first.trade_count == 1
    assert second.open_time == us("10:01:00") and not second.closed
    assert b.on_clock(us("10:01:00.500")) == ()
    assert len(closes(out)) == 1
    assert out[1].amended is False


def test_on_trade_exact_boundary_timestamp_opens_next_bar() -> None:
    assert bucket_bounds(M1, us("10:01:00")) == (us("10:01:00"), us("10:02:00"))
    assert bucket_bounds(M1, us("10:00:59.999999")) == (us("10:00:00"), us("10:01:00"))


# --- Scenario: A dead market still closes bars -------------------------------------------


def test_on_clock_dead_market_closes_open_bar_on_its_boundary_and_emits_nothing_else() -> None:
    b = _b()
    b.on_trade(trade(us("10:00:30")))
    assert b.on_clock(us("10:00:59.999999")) == ()
    out = b.on_clock(us("10:01:00"))
    assert [u.kind for u in out] == ["close"] and out[0].bar.close_time == us("10:01:00")
    emitted = [u for m in range(2, 7) for u in b.on_clock(us(f"10:0{m}:00"))]
    assert emitted == []
    nxt = b.on_trade(trade(us("10:06:10")))
    assert [u.kind for u in nxt] == ["open"]
    assert nxt[0].bar.gap_before and nxt[0].bar.index == 1


def test_on_clock_without_any_trade_emits_nothing() -> None:
    assert _b().on_clock(us("10:00:00")) == ()


def test_on_trade_adjacent_bar_has_no_gap_before() -> None:
    b = _b()
    b.on_trade(trade(us("10:00:01")))
    b.on_clock(us("10:01:00"))
    assert not b.on_trade(trade(us("10:01:01")))[0].bar.gap_before


# --- Scenario: Late trade amends a closed bar --------------------------------------------


def test_on_trade_late_within_60s_amends_closed_bar_and_reemits_close() -> None:
    b = _b()
    b.on_trade(trade(us("10:00:10"), px="100", qty="2", side="buy"))
    b.on_clock(us("10:01:00"))
    b.on_trade(trade(us("10:01:20"), px="101", qty="1"))
    out = b.on_trade(trade(us("10:00:05"), px="98", qty="3", side="sell", seq=9))
    assert len(out) == 1
    u = out[0]
    assert isinstance(u, BarUpdate)
    assert u.kind == "close" and u.amended and u.bar.index == 0 and u.bar.closed
    bar = u.bar
    # The late trade is OLDER than the bar's only trade: it becomes the open, not the close.
    assert (bar.open, bar.low, bar.close) == (Decimal("98"), Decimal("98"), Decimal("100"))
    assert bar.volume == Decimal("5")
    assert (bar.delta, bar.min_delta, bar.max_delta) == (Decimal(-1), Decimal(-1), Decimal(2))
    assert bar.volume + Decimal(1) == Decimal(6)  # BI-1: 2 + 3 + 1 traded


def test_on_trade_reordered_trades_keep_open_close_in_event_order() -> None:
    """Review repro: 10:00:10 @100, 10:00:50 @101, then late 10:00:05 @97."""
    b = _b()
    b.on_trade(trade(us("10:00:10"), px="100", seq=1))
    b.on_trade(trade(us("10:00:50"), px="101", seq=2))
    assert b.on_trade(trade(us("10:00:05"), px="97", seq=3)) == ()  # folded (#2022)
    bar = _forming(b)
    assert (bar.open, bar.high, bar.low, bar.close) == tuple(
        map(Decimal, ("97", "101", "97", "101"))
    )
    restored = _b()
    restored.restore(b.snapshot())
    after = restored.on_clock(us("10:01:00"))[0].bar
    assert (after.open, after.close) == (Decimal("97"), Decimal("101"))


def test_on_trade_equal_timestamps_order_by_seq() -> None:
    b = _b()
    b.on_trade(trade(us("10:00:10"), px="100", seq=5))
    assert b.on_trade(trade(us("10:00:10"), px="99", seq=4)) == ()  # folded (#2022)
    bar = _forming(b)
    assert (bar.open, bar.close) == (Decimal("99"), Decimal("100"))


# --- Scenario: Very late trade is dropped ------------------------------------------------


def test_on_trade_late_beyond_60s_is_dropped_and_counted() -> None:
    b = _b()
    b.on_trade(trade(us("10:00:10")))
    b.on_clock(us("10:01:00"))
    b.on_clock(us("10:02:30"))
    before = _dropped("late_window")
    assert b.on_trade(trade(us("10:00:40"))) == ()
    assert _dropped("late_window") == before + 1


def test_on_trade_late_into_empty_interval_is_dropped() -> None:
    b = _b()
    b.on_trade(trade(us("10:00:10")))
    b.on_trade(trade(us("10:04:30")))  # 10:01-10:04 empty; 10:03 bucket closed 30 s ago
    before = _dropped("empty_interval")
    assert b.on_trade(trade(us("10:03:30"))) == ()
    assert _dropped("empty_interval") == before + 1
    old = _dropped("late_window")
    assert b.on_trade(trade(us("10:02:30"))) == ()  # empty AND >60 s: past the window wins
    assert _dropped("late_window") == old + 1


def test_on_trade_out_of_order_inside_open_bar_is_applied() -> None:
    b = _b()
    b.on_trade(trade(us("10:00:30"), px="100"))
    assert b.on_trade(trade(us("10:00:10"), px="99")) == ()  # applied, nothing emitted (#2022)
    forming = b.forming()
    assert forming is not None and forming.kind == "update" and forming.bar.trade_count == 2


# --- Scenario: Session anchor shifts the grid --------------------------------------------


def test_bucket_bounds_session_anchor_480_shifts_hour_grid_and_hash() -> None:
    assert bucket_bounds(H1_480, us("08:30:00")) == (us("08:00:00"), us("09:00:00"))
    assert bucket_bounds(H1_480, us("07:59:59")) == (us("07:00:00"), us("08:00:00"))
    d4 = BarSpec(kind="time", interval_ms=14_400_000, session_anchor_utc_min=480)
    assert bucket_bounds(d4, us("09:00:00")) == (us("08:00:00"), us("12:00:00"))
    assert H1_480.spec_hash != BarSpec(kind="time", interval_ms=3_600_000).spec_hash


@pytest.mark.parametrize(
    ("anchor", "ts", "expected"),
    [
        (0, "23:59:59", ("00:00:00", "2026-10-06T00:00:00")),
        (480, "07:00:00", ("2026-10-04T08:00:00", "08:00:00")),  # funding-time anchor
        (1439, "23:59:00", ("23:59:00", "2026-10-06T23:59:00")),  # custom anchor
    ],
)
def test_bucket_bounds_daily_bar_respects_anchor(
    anchor: int, ts: str, expected: tuple[str, str]
) -> None:
    spec = BarSpec(kind="time", interval_ms=86_400_000, session_anchor_utc_min=anchor)

    def at(s: str) -> int:
        return us(s.split("T")[1], s.split("T")[0]) if "T" in s else us(s)

    assert bucket_bounds(spec, us(ts)) == (at(expected[0]), at(expected[1]))


def test_bucket_bounds_session_grid_truncates_last_bar_at_session_end() -> None:
    m7 = BarSpec(kind="time", interval_ms=420_000, align_to_epoch=False)  # 1440 % 7 != 0
    assert bucket_bounds(m7, us("23:57:00")) == (us("23:55:00"), us("00:00:00", "2026-10-06"))
    assert bucket_bounds(m7, us("00:03:00", "2026-10-06"))[0] == us("00:00:00", "2026-10-06")
    epoch7 = BarSpec(kind="time", interval_ms=420_000)
    s, e = bucket_bounds(epoch7, us("23:57:00"))
    assert e - s == 420_000_000 and s % 420_000_000 == 0


# --- Spec bounds (security note) ---------------------------------------------------------


@pytest.mark.parametrize("ms", [999, 1_500, 86_400_001, 7 * 86_400_000])
def test_validate_time_spec_rejects_out_of_range_or_fractional_seconds(ms: int) -> None:
    with pytest.raises(BarSpecError):
        TimeBarBuilder(BarSpec(kind="time", interval_ms=ms), SYM)


def test_validate_time_spec_rejects_non_time_kind_and_accepts_ladder() -> None:
    with pytest.raises(BarSpecError):
        validate_time_spec(BarSpec(kind="tick", tick_count=10))
    for ms in (1_000, 60_000, 420_000, 86_400_000):
        assert validate_time_spec(BarSpec(kind="time", interval_ms=ms)) == ms


# --- Fields, flags, errors ---------------------------------------------------------------


def test_on_trade_populates_every_field_and_tracks_delta_path() -> None:
    b = _b()
    b.on_trade(trade(us("10:00:01"), "100", "2", "buy"))
    b.on_trade(trade(us("10:00:02"), "102", "5", "sell"))
    b.on_trade(trade(us("10:00:03"), "101", "4", "buy"))
    bar = b.on_clock(us("10:01:00"))[0].bar
    assert (bar.open, bar.high, bar.low, bar.close) == tuple(
        map(Decimal, "100 102 100 101".split())
    )
    assert (bar.buy_volume, bar.sell_volume, bar.volume) == (Decimal(6), Decimal(5), Decimal(11))
    assert (bar.delta, bar.min_delta, bar.max_delta) == (Decimal(1), Decimal(-3), Decimal(2))
    assert bar.turnover == Decimal(1114) and bar.vwap == Decimal("101.27272727")
    assert bar.trade_count == 3 and bar.partial and not bar.gap_before and not bar.synthetic
    assert bar.spec_hash == M1.spec_hash and bar.symbol == SYM


def test_on_trade_only_first_bar_is_partial() -> None:
    b = _b()
    b.on_trade(trade(us("10:00:01")))
    assert not b.on_trade(trade(us("10:01:01")))[1].bar.partial


def test_on_trade_wrong_symbol_raises() -> None:
    t = trade(us("10:00:00")).model_copy(update={"symbol": "ETHUSDT"})
    with pytest.raises(BarsError):
        _b().on_trade(t)


def test_restore_rejects_foreign_or_unknown_state() -> None:
    state = _b().snapshot()
    with pytest.raises(BarsError):
        TimeBarBuilder(H1_480, SYM).restore(state)
    with pytest.raises(BarsError):
        _b().restore(state.model_copy(update={"state_version": 99}))


def test_snapshot_records_last_trade_seq() -> None:
    b = _b()
    b.on_trade(trade(us("10:00:01"), seq=41))
    assert b.snapshot().last_trade_seq == 41
