"""E39-T01 (#881) slice 2: the day's counters (Gherkin 5; E39-K01 §5, §6).

Idempotent by exec id (SR-E39-11), dated by exchange fill time, closes at the provisional taker
bound until a record confirms them, backfills pessimistic, reconciliation tighten-only, the record
timeout, `min(0, unrealised)` at a fresh mark, and fail closed on every unknown.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.risk import counters as counters_module
from candleviewer.risk.clock import DayCalendar
from candleviewer.risk.counters import CloseState, FillOutcome, RecordOutcome
from candleviewer.risk.evaluator import evaluate
from candleviewer.risk.inputs import RiskFill, RiskPosition, VenueClosedPnl
from candleviewer.risk.models import RiskRefusal
from tests.unit.risk._risk_builders import NOW, D, caps, counters, fill, mark, order

S = timedelta(seconds=1)
H = timedelta(hours=1)


_RECORD = VenueClosedPnl("r1", "BTCUSDT", "buy", D(1), D(90), D("0.1"), D(-10), NOW + 30 * S)


_BAD_FILLS = "qty=0 price=NaN entry_price=-1 fee=Inf exec_pnl=NaN".split()
_BAD_RECORDS = "tick=0 qty=0 avg_exit_price=NaN pnl=sNaN".split()


def bad(field: str) -> dict[str, Any]:
    name, value = field.split("=")
    return {name: D(value)}


def record(rid: str = "r1", pnl: Decimal | int = -10, **fields: Any) -> VenueClosedPnl:
    return replace(_RECORD, record_id=rid, pnl=D(pnl), **fields)


def opened() -> counters_module.AccountCounters:
    """A long of 1 at 100, opening fee 0.02 (rate 0.0002)."""
    c = counters()
    c.apply_fill(fill("open", opening=True, fee=D("0.02"), fee_rate=D("0.0002")), NOW)
    return c


def close(c: counters_module.AccountCounters, eid: str = "c1", **fields: Any) -> None:
    fields = {"price": D(90), "fee": D("0.05"), "exec_pnl": D(-10)} | fields
    c.apply_fill(fill(eid, **fields), NOW)


def test_gherkin5_day_rollover_resets_the_loss_and_unblocks() -> None:
    c = counters(taker=D(0))
    late = NOW + 11 * H  # 23:00 UTC, before the boundary
    c.apply_fill(fill("x", exec_pnl=D(-1400), exec_time=late), late)
    limit = caps(pol={"max_daily_loss_usd": D(1000)})
    before = c.figures(late)
    assert before is not None and before.daily_figure == D(-1400)
    refused = evaluate(order(), before, limit, now=late).decision
    assert refused.code is RiskRefusal.RISK_LIMIT_BREACHED and refused.cap == "max_daily_loss_usd"
    after_at = NOW + 12 * H + S
    after = c.figures(after_at)
    assert after is not None and after.daily_figure == 0 and after.day_peak_figure == 0
    assert evaluate(order(), after, limit, now=after_at).decision.allowed


def test_apply_fill_duplicate_exec_id_is_ignored_even_after_rollover() -> None:
    c = counters(taker=D(0))
    assert c.apply_fill(fill("x", exec_pnl=D(-5)), NOW) is FillOutcome.APPLIED
    assert c.apply_fill(fill("x", exec_pnl=D(-5)), NOW) is FillOutcome.DUPLICATE
    assert c.realised_today == D(-5)
    tomorrow = NOW + 13 * H
    replay = c.apply_fill(fill("x", exec_pnl=D(-5), exec_time=tomorrow), tomorrow)
    assert replay is FillOutcome.DUPLICATE
    assert c.realised_today == 0


def test_apply_fill_dated_by_exec_time_not_receive_time() -> None:
    c = counters(taker=D(0))
    tomorrow = NOW + 13 * H
    yesterday = fill("y", exec_pnl=D(-7), exec_time=NOW - 13 * H)
    assert c.apply_fill(yesterday, NOW) is FillOutcome.PRIOR_DAY
    early = fill("z", exec_pnl=D(-3), exec_time=tomorrow, order_ref="o2")
    assert c.apply_fill(early, NOW) is FillOutcome.QUEUED
    c.apply_fill(fill("w", exec_pnl=D(-1), exec_time=NOW + 40 * H, order_ref="o3"), NOW)
    assert c.realised_today == 0
    assert c.figures(tomorrow) is not None and c.realised_today == D(-3)  # waited for its key


def test_apply_fill_early_overflow_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(counters_module, "MAX_EARLY", 1)
    c = counters()
    outcomes = [c.apply_fill(fill(f"e{n}", exec_time=NOW + 13 * H), NOW) for n in range(2)]
    assert outcomes == [FillOutcome.QUEUED, FillOutcome.OVERFLOW] and c.figures(NOW) is None


def test_apply_fill_id_bound_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(counters_module, "MAX_IDS", 1)
    c = counters()
    assert c.apply_fill(fill("a"), NOW) is FillOutcome.APPLIED
    assert c.apply_fill(fill("b"), NOW) is FillOutcome.OVERFLOW
    assert c.figures(NOW) is None


def test_close_booked_at_the_provisional_taker_bound() -> None:
    c = opened()
    close(c)
    # exact = -10 - 0.05 - 0.02; bound charges the opening at 0.00055 x 100 = 0.055
    assert c.realised_today == D("-10.105") and c.settled_today == 0 and c.unconfirmed


def test_close_prorates_the_opening_fee_and_uses_the_highest_rate() -> None:
    c = counters()
    c.apply_fill(fill("open", opening=True, qty=D(2), fee=D("0.04"), fee_rate=D("0.0002")), NOW)
    close(c, fee=D(0), exec_pnl=D(0), fee_rate=D("0.001"))  # half the position
    assert c.realised_today == D("-0.1")  # 0.001 x 100, over the prorated 0.02
    figures = c.figures(NOW)
    assert figures is None  # one still open, no mark yet
    c.apply_mark(mark(100))
    figures = c.figures(NOW)
    assert figures is not None and figures.daily_figure == D("-0.1") - D("0.055")


def test_backfilled_close_is_pessimistic_and_unconfirmed() -> None:
    c = opened()
    close(c, exec_pnl=None, price=D(90))  # entry 100 from the position
    assert c.realised_today == D("-10.105")
    c.apply_fill(fill("open2", opening=True, order_ref="o2", fee=D(0)), NOW)
    c.apply_fill(fill("gain", exec_pnl=None, price=D(150), order_ref="o3"), NOW)
    assert c.realised_today == D("-10.105")  # no gain credited
    assert c._closes["o3"].state is CloseState.UNCONFIRMED


def test_backfilled_close_with_entry_price_uses_it() -> None:
    c = counters(taker=D(0))
    c.apply_fill(fill("b", exec_pnl=None, price=D(90), entry_price=D(95)), NOW)
    assert c.realised_today == D(-5)


def test_backfilled_close_with_no_entry_fails_closed() -> None:
    c = counters()
    assert c.apply_fill(fill("b", exec_pnl=None), NOW) is FillOutcome.INVALID
    assert c.figures(NOW) is None


def test_record_tightens_a_provisional_close() -> None:
    c = opened()
    close(c)
    assert c.apply_venue_record(record(pnl=-12), NOW) is RecordOutcome.TIGHTENED
    assert c.realised_today == D(-12) == c.settled_today and not c.unconfirmed


def test_record_settles_a_bound_and_confirms_an_equal_one() -> None:
    c = opened()
    close(c)
    assert c.apply_venue_record(record(pnl=D("-10.07")), NOW) is RecordOutcome.BOUND_SETTLED
    assert c.realised_today == D("-10.07")
    c2 = opened()
    close(c2)
    outcome = c2.apply_venue_record(record(pnl=D("-10.105")), NOW)
    assert outcome is RecordOutcome.CONFIRMED


def test_record_never_loosens_a_confirmed_close_and_ids_are_idempotent() -> None:
    c = opened()
    close(c)
    c.apply_venue_record(record(pnl=-12), NOW)
    assert c.apply_venue_record(record("r2", pnl=-11), NOW) is RecordOutcome.UNCHANGED
    assert c.apply_venue_record(record("r3", pnl=-13), NOW) is RecordOutcome.TIGHTENED
    assert c.apply_venue_record(record("r3", pnl=-99), NOW) is RecordOutcome.DUPLICATE
    assert c.realised_today == D(-13)


@pytest.mark.parametrize(
    "fields",
    [
        {"qty": D(2)},
        {"avg_exit_price": D("90.2")},
        {"updated_at": NOW + 200 * S},
        {"updated_at": NOW - S},
        {"symbol": "ETHUSDT"},
    ],
)
@pytest.mark.parametrize(("pnl", "booked"), [(-4, -4), (4, 0)])  # M2: no unconfirmed gain
def test_record_unmatched_books_a_loss_in_full(
    fields: dict[str, Any], pnl: int, booked: int
) -> None:
    c = opened()
    close(c)
    assert c.apply_venue_record(record(pnl=pnl, **fields), NOW) is RecordOutcome.UNMATCHED_BOOKED
    assert c.realised_today == D("-10.105") + booked


def test_record_unmatched_out_of_the_day_is_not_booked() -> None:
    c = counters()
    outcome = c.apply_venue_record(record(updated_at=NOW - 13 * H), NOW)
    assert outcome is RecordOutcome.OUT_OF_DAY and c.realised_today == 0


def test_record_timeout_settles_for_the_flatten_only() -> None:
    c = opened()
    close(c)
    assert c.expire_records(NOW + 4 * 60 * S) == ()
    assert c.expire_records(NOW + 5 * 60 * S) == ("o1",)
    assert c.settled_today == D("-10.07") and c.realised_today == D("-10.105")
    assert c.apply_venue_record(record(pnl=-1), NOW) is RecordOutcome.UNCHANGED
    assert c.apply_venue_record(record("r2", pnl=-11), NOW) is RecordOutcome.TIGHTENED


def test_figures_unrealised_counts_a_loss_never_a_gain() -> None:
    c = opened()
    c.apply_mark(mark(150))
    gain = c.figures(NOW)
    assert gain is not None and gain.daily_figure == 0 and gain.symbol_notional == {"BTCUSDT": 150}
    assert gain.open_positions == 1 and gain.day_peak_figure == 0
    c.apply_mark(mark(90, NOW + S))
    assert (loss := c.figures(NOW + S)) is not None and loss.daily_figure == D(-10) - D("0.055")


def test_figures_short_position_marks_the_other_way() -> None:
    c = counters(taker=D(0))
    c.apply_fill(fill("s", opening=True, position_side="sell"), NOW)
    c.apply_mark(mark(110))
    assert (figures := c.figures(NOW)) is not None and figures.daily_figure == D(-10)


def test_figures_stale_mark_falls_back_then_fails_closed() -> None:
    c = opened()
    c.apply_mark(mark(100, NOW - 11 * S))
    assert c.figures(NOW) is None
    c.apply_mark(mark(95, NOW - 10 * S, source="position"))
    assert (figures := c.figures(NOW)) is not None and figures.symbol_notional == {"BTCUSDT": 95}
    c.apply_mark(mark(99, NOW - 20 * S, source="position"))  # older: ignored
    c.apply_mark(mark(100, NOW + S))  # future-dated: not fresh at NOW
    assert (figures := c.figures(NOW)) is not None and figures.symbol_notional == {"BTCUSDT": 95}
    assert c.figures(NOW + 12 * S) is None


def test_figures_cold_start_is_unavailable_until_ready() -> None:
    fresh = counters_module.AccountCounters(DayCalendar(0, NOW), taker_rate=D(0))
    assert fresh.figures(NOW) is None
    fresh.mark_ready()
    figures = fresh.figures(NOW)
    assert figures is not None and figures.equity is None


def test_position_push_overrides_fills_unless_older() -> None:
    c = counters(taker=D(0))
    c.apply_fill(fill("o", opening=True), NOW)
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(3), D(80), NOW - S))
    c.apply_mark(mark(100))
    assert (older := c.figures(NOW)) is not None and older.symbol_notional == {"BTCUSDT": 100}
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(3), D(80), NOW))
    assert (newer := c.figures(NOW)) is not None and newer.symbol_notional == {"BTCUSDT": 300}
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(0), D(0), NOW + S))
    assert (gone := c.figures(NOW + S)) is not None and gone.open_positions == 0


def test_figures_peak_and_drawdown_and_day_start_equity() -> None:
    c = counters(taker=D(0))
    c.apply_fill(fill("g", exec_pnl=D(50)), NOW)
    c.figures(NOW)
    c.apply_fill(fill("l", exec_pnl=D(-80), order_ref="o2"), NOW)
    figures = c.figures(NOW)
    assert figures is not None and figures.day_peak_figure == 50 and figures.daily_figure == -30
    c.set_equity(D(90_000), NOW)
    tomorrow = c.figures(NOW + 13 * H)
    assert tomorrow is not None and tomorrow.day_start_equity == D(90_000)


def test_consecutive_losses_reset_by_a_break_even_close() -> None:
    c = counters(taker=D(0))
    for n, pnl in enumerate([-1, 0, -2, -3]):
        c.apply_fill(fill(f"f{n}", exec_pnl=D(pnl), order_ref=f"o{n}", exec_time=NOW + n * S), NOW)
    assert (figures := c.figures(NOW)) is not None and figures.consecutive_losses == 2


_pnl = st.decimals(min_value=-99, max_value=1000, places=2)  # per unit, opened at 100


@given(
    closes=st.lists(st.tuples(_pnl, st.integers(1, 5)), min_size=1, max_size=12),
    replays=st.lists(st.integers(0, 11), max_size=12),
    rate=st.decimals(min_value=0, max_value=D("0.01"), places=5),
)
def test_counter_never_under_counts_an_oracle_and_ignores_replays(
    closes: list[tuple[Decimal, int]], replays: list[int], rate: Decimal
) -> None:
    c = counters(taker=rate)
    oracle = Decimal(0)
    fills: list[RiskFill] = []
    for n, (unit, qty) in enumerate(closes):
        opening = fill(f"o{n}", opening=True, qty=D(qty), order_ref=f"a{n}", fee=D("0.01"))
        pnl, exit_at = unit * qty, 100 + unit
        closing = fill(f"c{n}", qty=D(qty), price=exit_at, order_ref=f"b{n}", exec_pnl=pnl)
        fills += [opening, replace(closing, fee=D("0.01"))]
        oracle += pnl - D("0.02")
    for f in fills + [fills[i % len(fills)] for i in replays]:
        c.apply_fill(f, NOW)
    assert c.realised_today <= oracle
    assert c.realised_today >= oracle - rate * sum(D(q) * 100 for _, q in closes)


def test_partial_closing_fills_are_one_close_and_stay_unconfirmed() -> None:
    c = counters(taker=D(0))
    c.apply_fill(fill("open", opening=True, qty=D(2)), NOW)
    c.apply_fill(fill("p1", exec_pnl=None, price=D(90)), NOW)
    c.apply_fill(fill("p2", exec_pnl=D(-10), price=D(90), exec_time=NOW + S), NOW)
    assert c._closes["o1"].state is CloseState.UNCONFIRMED and c.realised_today == D(-20)
    outcome = c.apply_venue_record(record(pnl=-19, qty=D(2)), NOW)
    assert outcome is RecordOutcome.BOUND_SETTLED and c.realised_today == D(-19)


def test_apply_fill_at_the_boundary_instant_belongs_to_the_next_key() -> None:
    c = counters(taker=D(0))
    boundary = NOW + 12 * H
    c.apply_fill(fill("b", exec_pnl=D(-9), exec_time=boundary), NOW)
    assert c.realised_today == 0
    assert c.figures(boundary) is not None and c.realised_today == D(-9)


def test_record_with_an_awaiting_sibling_still_tightens() -> None:
    c = opened()
    close(c)
    c.apply_fill(fill("open2", opening=True, order_ref="o2"), NOW)
    c.apply_fill(fill("c2", order_ref="o3", price=D(50), exec_pnl=D(-1)), NOW)
    assert c.apply_venue_record(record(pnl=-30), NOW) is RecordOutcome.TIGHTENED


@pytest.mark.parametrize(("pnl", "realised"), [(-10, -40), (10, 20)])
def test_record_matching_two_closes_is_ambiguous_and_never_a_gain(pnl: int, realised: int) -> None:
    c = counters(taker=D(0))  # M2, the lens probe: two equal closes, two ambiguous records
    c.apply_fill(fill("a", exec_pnl=D(pnl), price=D(100 + pnl)), NOW)
    c.apply_fill(fill("b", exec_pnl=D(pnl), price=D(100 + pnl), order_ref="o2"), NOW)
    for rid in ("r1", "r2"):
        ambiguous = record(rid, pnl=pnl, avg_exit_price=D(100 + pnl))
        assert c.apply_venue_record(ambiguous, NOW) is RecordOutcome.UNMATCHED_BOOKED
    assert c.realised_today == D(realised)  # a loss counted twice, a gain only once


def test_close_with_no_tracked_open_bounds_the_fee_on_the_entry() -> None:
    c = counters()
    c.apply_fill(fill("a", exec_pnl=D(-1000), price=D(90), qty=D(100)), NOW)
    assert c.realised_today == D("-1005.5")  # entry 100 from exec_pnl: 0.00055 x 10_000 (m1)
    c.apply_fill(fill("b", exec_pnl=D(0), entry_price=D(100), price=D(90), order_ref="o2"), NOW)
    assert c.realised_today == D("-1005.555")  # the larger of the entry and exec_pnl's entry


def test_close_bound_uses_the_opening_fills_pushed_rate() -> None:
    c = counters()
    c.apply_fill(fill("open", opening=True, fee=D(0), fee_rate=D("0.001")), NOW)
    c.apply_fill(fill("c", exec_pnl=D(0)), NOW)
    assert c.realised_today == D("-0.1")


def test_day_start_equity_is_the_first_of_the_key() -> None:
    c = counters()
    c.set_equity(D(1), NOW)
    figures = c.figures(NOW)
    assert figures is not None and (figures.equity, figures.day_start_equity) == (D(1), D(100_000))


def test_record_ids_reset_with_the_day_and_records_never_match_records() -> None:
    c = counters()
    assert c.apply_venue_record(record("r1"), NOW) is RecordOutcome.UNMATCHED_BOOKED
    assert c.apply_venue_record(record("r2"), NOW) is RecordOutcome.UNMATCHED_BOOKED
    assert c.realised_today == D(-20)
    tomorrow = NOW + 13 * H
    assert c.apply_venue_record(record("r1"), tomorrow) is RecordOutcome.OUT_OF_DAY


def test_record_id_bound_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(counters_module, "MAX_IDS", 1)
    c = counters()
    c.apply_venue_record(record("r1"), NOW)
    assert c.apply_venue_record(record("r2"), NOW) is RecordOutcome.OVERFLOW
    assert c.figures(NOW) is None


def test_record_sibling_on_another_symbol_does_not_hold_the_bound() -> None:
    c = opened()
    close(c)
    c.apply_fill(fill("eth", symbol="ETHUSDT", order_ref="o2", exec_pnl=D(-1)), NOW)
    assert c.apply_venue_record(record(pnl=0), NOW) is RecordOutcome.BOUND_SETTLED


def test_push_includes_earlier_backfilled_closes_the_lens_probe() -> None:  # M1
    c = counters(taker=D(0))
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(3), D(100), NOW))
    for n, back in enumerate((30, 20)):
        late = fill(f"g{n}", order_ref=f"o{n}", price=D(90), exec_time=NOW - back * S)
        assert c.apply_fill(replace(late, exec_pnl=D(-10)), NOW) is FillOutcome.APPLIED
    c.apply_mark(mark(80))
    assert (figures := c.figures(NOW)) is not None and figures.open_positions == 1
    assert figures.symbol_notional == {"BTCUSDT": 240} and figures.daily_figure == D(-80)


def test_push_after_a_fill_then_the_fill_dated_before_it_arrives() -> None:  # M1
    c = counters(taker=D(0))
    c.apply_fill(fill("open", opening=True, qty=D(2), exec_time=NOW - S), NOW)
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(1), D(100), NOW + S / 2))
    c.apply_fill(fill("c", price=D(90), exec_pnl=D(-10)), NOW + S)
    c.apply_fill(fill("late-open", opening=True, exec_time=NOW, order_ref="o2"), NOW + S)
    c.apply_mark(mark(80, NOW + S))
    assert (figures := c.figures(NOW + S)) is not None and figures.open_positions == 1
    assert figures.daily_figure == D(-30) and figures.symbol_notional == {"BTCUSDT": 80}


def test_push_that_enlarges_bounds_the_opening_fee_on_its_value() -> None:  # m5
    c = counters()
    c.apply_fill(fill("open", opening=True, fee=D(0), exec_time=NOW - S), NOW)
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(3), D(80), NOW))
    c.apply_mark(mark(80))
    assert (figures := c.figures(NOW)) is not None and figures.daily_figure == D("-0.132")
    c.apply_fill(fill("c", qty=D(3), price=D(80), exec_pnl=D(0), exec_time=NOW + S), NOW)
    assert c.realised_today == D("-0.132")  # 0.00055 x 240, not x 100


def test_flat_push_keeps_the_entry_for_a_late_backfilled_close() -> None:
    c = counters(taker=D(0))
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(1), D(100), NOW - S))
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(0), D(0), NOW))
    c.apply_fill(fill("c", price=D(90), exec_pnl=None, exec_time=NOW - S / 2), NOW)
    figures = c.figures(NOW)
    assert figures is not None and figures.daily_figure == D(-10) and figures.open_positions == 0


_MALFORMED: list[Callable[[counters_module.AccountCounters], object]] = [
    *(lambda c, f=f: c.apply_fill(fill("bad", **bad(f)), NOW) for f in _BAD_FILLS),
    *(lambda c, f=f: c.apply_venue_record(record(**bad(f)), NOW) for f in _BAD_RECORDS),
    lambda c: c.apply_position(RiskPosition("BTCUSDT", "buy", D(-1), D(100), NOW)),
    lambda c: c.apply_position(RiskPosition("BTCUSDT", "buy", D("NaN"), D(100), NOW)),
    lambda c: c.apply_position(RiskPosition("BTCUSDT", "buy", D(1), D(0), NOW)),
    lambda c: c.apply_mark(mark(0)),
]


@pytest.mark.parametrize("feed", _MALFORMED)
def test_malformed_input_fails_closed_without_raising(
    feed: Callable[[counters_module.AccountCounters], object],
) -> None:  # m3: never a bare decimal exception out of the reconcile cycle
    c = opened()
    close(c)
    assert feed(c) in (None, FillOutcome.INVALID, RecordOutcome.INVALID)
    assert c.figures(NOW) is None


def test_held_record_keeps_its_pnl_and_the_timeout_settles_on_it() -> None:  # m2
    c = opened()
    close(c)
    c.apply_fill(fill("open2", opening=True, order_ref="o2", fee=D("0.02")), NOW)
    c.apply_fill(fill("c2", order_ref="o3", price=D(99), fee=D("0.05"), exec_pnl=D(-1)), NOW)
    assert c.apply_venue_record(record(pnl=D("-10.09")), NOW) is RecordOutcome.HELD
    second = record("r2", pnl=D("-1.0"), avg_exit_price=D(99))
    assert c.apply_venue_record(second, NOW) is RecordOutcome.HELD
    assert c.apply_venue_record(record(pnl=D("-10.09")), NOW) is RecordOutcome.HELD  # not lost
    assert sorted(c.expire_records(NOW + 5 * 60 * S)) == ["o1", "o3"]
    assert c.settled_today == D("-11.09")  # the venue figures, not the stream's -11.14


def test_held_record_confirms_on_a_re_poll_once_the_sibling_settles() -> None:  # m2
    c = opened()
    close(c)
    c.apply_fill(fill("open2", opening=True, order_ref="o2"), NOW)
    c.apply_fill(fill("c2", order_ref="o3", price=D(99), exec_pnl=D(-1)), NOW)
    assert c.apply_venue_record(record(pnl=D("-10.09")), NOW) is RecordOutcome.HELD
    sibling = record("r2", pnl=D(-2), avg_exit_price=D(99))
    assert c.apply_venue_record(sibling, NOW) is RecordOutcome.TIGHTENED
    outcome = c.apply_venue_record(record(pnl=D("-10.09")), NOW)
    assert outcome is RecordOutcome.BOUND_SETTLED and c.realised_today == D("-12.09")


def test_early_fill_is_booked_when_an_offset_change_stretches_the_key() -> None:  # l1
    calendar = DayCalendar(0, NOW)
    c = counters_module.AccountCounters(calendar, taker_rate=D(0))
    c.mark_ready()
    after_end = NOW + 12 * H + 30 * 60 * S
    assert c.apply_fill(fill("e", exec_pnl=D(-50), exec_time=after_end), NOW) is FillOutcome.QUEUED
    calendar.change_offset(-60, NOW)  # the key now ends at 01:00 tomorrow
    assert (figures := c.figures(NOW + S)) is not None and figures.daily_figure == D(-50)
    assert c.figures(NOW + 13 * H + S) is not None and c.realised_today == 0  # not booked twice


def test_consecutive_losses_follow_exec_time_not_arrival() -> None:
    c = counters(taker=D(0))
    c.apply_fill(fill("a", exec_pnl=D(-1), order_ref="a", exec_time=NOW + 2 * S), NOW)
    c.apply_fill(fill("b", exec_pnl=D(-1), order_ref="b", exec_time=NOW + 3 * S), NOW)
    c.apply_fill(fill("g", exec_pnl=D(1), order_ref="g", exec_time=NOW + S), NOW)  # older gain
    assert (figures := c.figures(NOW)) is not None and figures.consecutive_losses == 2
    c.apply_fill(fill("a2", exec_pnl=D(2), order_ref="a", exec_time=NOW + 4 * S), NOW)
    assert (figures := c.figures(NOW)) is not None and figures.consecutive_losses == 0
    c.apply_fill(fill("z", exec_pnl=D(-1), order_ref="z", exec_time=NOW + 5 * S), NOW)
    assert (figures := c.figures(NOW)) is not None and figures.consecutive_losses == 1


def test_consecutive_losses_recount_after_a_record_tightens() -> None:
    c = counters(taker=D(0))
    c.apply_fill(fill("a", exec_pnl=D(-1), order_ref="a", exec_time=NOW - S), NOW)
    c.apply_fill(fill("b", price=D(90), exec_pnl=D(0)), NOW)
    assert (figures := c.figures(NOW)) is not None and figures.consecutive_losses == 0
    assert c.apply_venue_record(record(pnl=-3), NOW) is RecordOutcome.TIGHTENED
    assert (figures := c.figures(NOW)) is not None and figures.consecutive_losses == 2


_step = st.tuples(st.booleans(), st.integers(1, 3), st.integers(50, 150), st.booleans())


@given(
    steps=st.lists(_step, min_size=1, max_size=10),
    side=st.sampled_from(["buy", "sell"]),
    shuffle=st.randoms(use_true_random=False),
)
def test_fills_and_pushes_in_any_order_never_under_count(
    steps: list[tuple[bool, int, int, bool]], side: Any, shuffle: Any
) -> None:  # M1: the oracle is the position after every event, in exchange time
    sign, size, entry, realised = (1 if side == "buy" else -1), D(0), D(0), D(0)
    events: list[RiskFill | RiskPosition] = []
    for n, (opening, qty, price, push) in enumerate(steps):
        at, q, p = NOW - (len(steps) - n) * S, D(qty) if opening else min(D(qty), size), D(price)
        if q == 0:
            continue
        base = fill(f"f{n}", order_ref=f"o{n}", position_side=side, qty=q, price=p, exec_time=at)
        if opening:
            entry, size = (entry * size + p * q) / (size + q), size + q
            events.append(replace(base, opening=True))
        else:
            realised += (p - entry) * q * sign
            size -= q
            events.append(replace(base, exec_pnl=(p - entry) * q * sign))
        if push:
            events.append(RiskPosition("BTCUSDT", side, size, entry if size else D(0), at))
    shuffle.shuffle(events)
    c = counters(taker=D(0))
    for event in events:
        if isinstance(event, RiskPosition):
            c.apply_position(event)
        else:
            c.apply_fill(event, NOW)
    c.apply_mark(mark(100))
    figures = c.figures(NOW)
    assert figures is not None
    # equal, or over when a close arrives ahead of its own open (clamped: never under)
    assert figures.symbol_notional.get("BTCUSDT", D(0)) >= size * 100
    oracle = realised + min(D(0), (100 - entry) * size * sign)
    assert figures.daily_figure <= oracle + D("1e-12")


@pytest.mark.parametrize(("side", "first", "later"), [("buy", 50, 101), ("sell", 150, 99)])
def test_fills_out_of_exchange_order_bound_the_entry(side: Any, first: int, later: int) -> None:
    c = counters(taker=D(0))
    lot = fill("a", position_side=side, opening=True, price=D(first), exec_time=NOW - 3 * S)
    c.apply_fill(lot, NOW)
    c.apply_fill(replace(lot, exec_id="b", price=D(later), exec_time=NOW - S), NOW)
    c.apply_fill(fill("c", position_side=side, price=D(first), exec_time=NOW - 2 * S), NOW)
    c.apply_mark(mark(100))
    assert (figures := c.figures(NOW)) is not None and figures.daily_figure == D(-1)  # true entry
    c.apply_fill(fill("d", order_ref="o2", position_side=side, exec_pnl=None, qty=D("0.5")), NOW)
    assert c.realised_today == D("-0.5")  # a backfilled close is priced on that entry too
    c.apply_position(RiskPosition("BTCUSDT", side, D("0.5"), D(100), NOW))
    assert (figures := c.figures(NOW)) is not None and figures.daily_figure == D("-0.5")
    assert not c._positions[("BTCUSDT", side)].disordered


def test_a_close_ahead_of_its_open_never_nets_a_phantom_gain() -> None:
    c = counters(taker=D(0))
    c.apply_fill(fill("c", price=D(90), exec_time=NOW - S), NOW)  # its open is still in flight
    c.apply_fill(fill("o", opening=True, price=D(80), exec_time=NOW - 2 * S), NOW)
    c.apply_fill(fill("e", opening=True, symbol="ETHUSDT", exec_time=NOW - S), NOW)
    c.apply_mark(mark(100))
    c.apply_mark(mark(95, symbol="ETHUSDT"))
    figures = c.figures(NOW)
    assert figures is not None and figures.symbol_notional == {"BTCUSDT": 100, "ETHUSDT": 95}
    assert figures.daily_figure == D(-5)  # the phantom long's +20 does not offset ETH's -5


def test_a_late_close_prorates_on_the_size_before_the_push() -> None:  # M1
    c = counters(taker=D(0))
    c.apply_fill(fill("o", opening=True, qty=D(2), fee=D("0.04"), exec_time=NOW - 2 * S), NOW)
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(1), D(100), NOW))
    c.apply_fill(fill("c", exec_time=NOW - S), NOW)
    assert c.realised_today == D("-0.02")  # half the opening fee: it closed 1 of 2


def test_a_late_close_keeps_the_pushed_value_for_the_open_part() -> None:  # m5
    c = counters()
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(1), D(100), NOW))
    c.apply_fill(fill("c", exec_time=NOW - S), NOW)
    c.apply_mark(mark(100))
    figures = c.figures(NOW)
    assert figures is not None and figures.daily_figure == D("-0.110")  # 2 x 0.00055 x 100


def test_fills_at_the_same_instant_are_in_order() -> None:
    c = counters(taker=D(0))
    c.apply_fill(fill("a", opening=True, price=D(100)), NOW)
    c.apply_fill(fill("b", opening=True, price=D(50)), NOW)
    c.apply_mark(mark(80))
    assert (figures := c.figures(NOW)) is not None and figures.daily_figure == 0  # entry 75


@pytest.mark.parametrize(
    ("side", "old", "prices", "at"), [("buy", 200, (60, 50), 52), ("sell", 20, (40, 50), 48)]
)
def test_flat_push_restarts_the_entry_bound(
    side: Any, old: int, prices: tuple[int, int], at: int
) -> None:
    c = counters(taker=D(0))
    c.apply_fill(
        fill("old", position_side=side, opening=True, price=D(old), exec_time=NOW - 9 * S), NOW
    )
    c.apply_position(RiskPosition("BTCUSDT", side, D(0), D(0), NOW - 8 * S))
    for n, (price, back) in enumerate(zip(prices, (1, 2), strict=True)):
        lot = fill(
            f"n{n}", position_side=side, opening=True, price=D(price), exec_time=NOW - back * S
        )
        c.apply_fill(lot, NOW)
    c.apply_mark(mark(at))
    assert (figures := c.figures(NOW)) is not None and figures.daily_figure == D(-16)


def test_consecutive_losses_recount_stops_at_a_break_even_close() -> None:
    c = counters(taker=D(0))
    for n, pnl in ((3, -1), (2, 0), (1, -1)):
        c.apply_fill(fill(f"f{n}", exec_pnl=D(pnl), order_ref=f"o{n}", exec_time=NOW + n * S), NOW)
    assert (figures := c.figures(NOW)) is not None and figures.consecutive_losses == 1
