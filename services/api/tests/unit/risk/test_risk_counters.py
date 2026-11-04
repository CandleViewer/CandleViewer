"""E39-T01 (#881) slice 2: the day's counters (Gherkin 5; E39-K01 §5, §6).

Idempotent by exec id (SR-E39-11), dated by exchange fill time, closes at the provisional taker
bound until a record confirms them, backfills pessimistic, reconciliation tighten-only, the record
timeout, `min(0, unrealised)` at a fresh mark, and fail closed on every unknown.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal, localcontext
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
NAIVE = NOW.replace(tzinfo=None)


_RECORD = VenueClosedPnl("r1", "BTCUSDT", "buy", D(1), D(90), D("0.1"), D(-10), NOW + 30 * S)


_BAD_FILLS = "qty=0 price=NaN entry_price=-1 fee=Inf fee_rate=Inf exec_pnl=NaN".split()
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


@pytest.mark.parametrize("pnl", [0, 1])
def test_record_unmatched_without_a_loss_books_nothing_and_keeps_the_run(pnl: int) -> None:
    # m11: a record attributing to no close is not a close; with no loss it carries nothing
    c = counters(taker=D(0))
    for n in range(3):
        c.apply_fill(fill(f"f{n}", exec_pnl=D(-1), order_ref=f"o{n}", exec_time=NOW + n * S), NOW)
    other = record(pnl=pnl, symbol="ETHUSDT", updated_at=NOW + 3 * S)
    assert c.apply_venue_record(other, NOW) is RecordOutcome.UNMATCHED_BOOKED
    assert c.apply_venue_record(other, NOW) is RecordOutcome.DUPLICATE  # read once
    assert (figures := c.figures(NOW)) is not None and figures.consecutive_losses == 3
    assert c.realised_today == D(-3)
    c.apply_fill(fill("late", exec_pnl=D(-1), order_ref="o9", exec_time=NOW + 4 * S), NOW)
    assert (figures := c.figures(NOW)) is not None and figures.consecutive_losses == 4


def test_record_timeout_settles_for_the_flatten_only() -> None:
    c = opened()
    close(c)
    assert c.expire_records(NOW + 4 * 60 * S) == ()
    assert c.expire_records(NOW + 5 * 60 * S) == ("o1",)
    assert not c.unconfirmed and c.expire_records(NOW + 6 * 60 * S) == ()  # expired once
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
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(3), D(80), NOW))
    c.apply_mark(mark(100))
    assert (newer := c.figures(NOW)) is not None and newer.symbol_notional == {"BTCUSDT": 300}
    c.apply_fill(fill("o2", opening=True, exec_time=NOW + S), NOW)
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(9), D(80), NOW))  # older than a fill
    assert (older := c.figures(NOW)) is not None and older.symbol_notional == {"BTCUSDT": 400}
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
    lambda c: c.apply_position(RiskPosition("BTCUSDT", "buy", D(1), D("Infinity"), NOW)),
    lambda c: c.apply_position(RiskPosition("BTCUSDT", "buy", D(1), D("NaN"), NOW)),
    lambda c: c.apply_mark(mark(0)),
    # m7: a tz-naive event time fails closed like any malformed value, never a TypeError
    lambda c: c.apply_fill(fill("naive", exec_time=NAIVE), NOW),
    lambda c: c.apply_venue_record(record(updated_at=NAIVE), NOW),
    lambda c: c.apply_position(RiskPosition("BTCUSDT", "buy", D(1), D(100), NAIVE)),
    lambda c: c.apply_mark(mark(100, at=NAIVE)),
]


@pytest.mark.parametrize("feed", _MALFORMED)
def test_malformed_input_fails_closed_without_raising(
    feed: Callable[[counters_module.AccountCounters], object],
) -> None:  # m3: never a bare decimal exception out of the reconcile cycle
    c = opened()
    close(c)
    c.apply_mark(mark(100))
    assert c.figures(NOW) is not None  # available until the malformed value
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


@pytest.mark.parametrize(
    ("fills", "size"),
    [
        ([("live", True, 1, 0)], 6),  # the lens probe: four held before the start, then one more
        ([("live", True, 1, 0), ("cut", False, 2, 1)], 4),
        ([("old", True, 1, -2), ("live", True, 1, 0)], 6),  # dated before the push: in it
        ([("tie", True, 1, -1), ("live", True, 1, 0)], 6),  # at the push's instant: in it (l10)
    ],
)
def test_first_push_older_than_applied_fills_is_their_baseline(
    fills: list[tuple[str, bool, int, int]], size: int
) -> None:  # m9
    c = counters(taker=D(0))
    for eid, opening, qty, at in fills:
        lot = fill(eid, opening=opening, qty=D(qty), exec_time=NOW + at * S, exec_pnl=D(0))
        c.apply_fill(replace(lot, exec_pnl=None if opening else D(0)), NOW)
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(5), D(100), NOW - S))
    c.apply_mark(mark(100))
    assert (figures := c.figures(NOW)) is not None
    assert figures.symbol_notional == {"BTCUSDT": D(size * 100)}
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(9), D(100), NOW - S / 2))  # stream rule
    assert (
        again := c.figures(NOW)
    ) is not None and again.symbol_notional == figures.symbol_notional


def test_first_push_older_than_an_overflowed_log_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # m9: the replay is bounded; past it the counter answers unavailable
    monkeypatch.setattr(counters_module, "MAX_EARLY", 1)
    c = counters(taker=D(0))
    for n in range(2):  # the second fill finds the log full
        c.apply_fill(fill(f"f{n}", opening=True, exec_time=NOW + n * S), NOW)
    c.apply_mark(mark(100))
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(5), D(100), NOW - S))
    assert c.figures(NOW) is None


@given(
    closes=st.lists(st.tuples(_pnl, st.integers(1, 5), st.booleans()), min_size=1, max_size=8),
)
def test_unattributed_records_never_credit_a_gain(closes: list[tuple[Decimal, int, bool]]) -> None:
    # M2, m11: records re-keyed as unmatched never under-count the loss or the loss run
    c = counters(taker=D(0))
    oracle, run = Decimal(0), 0
    for n, (unit, qty, rekeyed) in enumerate(closes):
        pnl = unit * qty
        c.apply_fill(
            fill(f"c{n}", qty=D(qty), price=100 + unit, order_ref=f"b{n}", exec_pnl=pnl), NOW
        )
        oracle, run = oracle + pnl, run + 1 if pnl < 0 else 0
        if rekeyed:  # its record, re-keyed by qty: it matches no close and is booked unmatched
            c.apply_venue_record(
                record(f"r{n}", pnl, qty=D(qty + 100), avg_exit_price=100 + unit), NOW
            )
    assert c.realised_today <= oracle
    assert (figures := c.figures(NOW)) is not None and figures.consecutive_losses >= run  # m11


# BQ-10: one test per mutant the mutation pass found surviving (comparison, boundary, arithmetic).


def test_first_push_replays_same_instant_fills_in_arrival_order() -> None:
    c = counters(taker=D(0))
    c.apply_fill(fill("a", opening=True), NOW)
    c.apply_fill(fill("b", order_ref="x"), NOW)  # its close, at the same instant
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(0), D(0), NOW - S))
    c.apply_mark(mark(100))
    assert (figures := c.figures(NOW)) is not None and figures.open_positions == 0


def test_disordered_short_after_a_flat_push_bounds_on_the_kept_entry() -> None:
    c = counters(taker=D(0))
    lot = fill("o", position_side="sell", opening=True, exec_time=NOW - 9 * S)
    c.apply_fill(lot, NOW)
    c.apply_position(RiskPosition("BTCUSDT", "sell", D(0), D(0), NOW - 8 * S))
    for eid, price, back in (("a", 90, 1), ("b", 110, 2)):  # b arrives out of exchange order
        late = fill(eid, position_side="sell", price=D(price), exec_pnl=None, order_ref=eid)
        c.apply_fill(replace(late, exec_time=NOW - back * S), NOW)
    assert c.realised_today == D(-10)  # b from the kept entry 100, never from 0


def test_loss_run_is_kept_incrementally_and_restarts_with_the_day() -> None:  # m6
    c = counters(taker=D(0))
    c.apply_fill(fill("a", exec_pnl=D(-1), order_ref="a"), NOW)
    assert c._run == 1
    c.apply_fill(fill("b", exec_pnl=D(-1), order_ref="b"), NOW)  # appended at the same instant
    assert c._run == 2
    assert (figures := c.figures(NOW)) is not None and figures.consecutive_losses == 2
    later = NOW + 12 * H + S
    c.apply_fill(fill("n", exec_pnl=D(-1), order_ref="n", exec_time=later), later)
    assert c._run == 1


def test_mark_at_the_same_instant_replaces_the_held_one() -> None:
    c = counters()
    c.apply_fill(fill("o", opening=True), NOW)
    c.apply_mark(mark(100))
    c.apply_mark(mark(50))
    assert (figures := c.figures(NOW)) is not None and figures.symbol_notional == {"BTCUSDT": 50}


@pytest.mark.parametrize(
    ("steps", "realised"),
    [
        ([("a", True, 1), ("b", True, 1), ("c", False, 2)], "-0.04"),  # opening fees add up
        ([("a", True, 1), ("c", False, 2)], "-0.02"),  # a close past its open takes its fee once
    ],
)
def test_close_takes_the_opening_fees_once(
    steps: list[tuple[str, bool, int]], realised: str
) -> None:
    c = counters(taker=D(0))
    for eid, opening, qty in steps:
        c.apply_fill(
            fill(eid, opening=opening, qty=D(qty), fee=D("0.02") if opening else D(0)), NOW
        )
    assert c.realised_today == D(realised)


def test_close_on_a_flat_pushed_position_takes_the_stale_opening_fee_once() -> None:
    c = counters(taker=D(0))
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(0), D(0), NOW))
    c.apply_fill(fill("a", opening=True, fee=D("0.02"), exec_time=NOW - S), NOW)  # in the push
    c.apply_fill(fill("c", exec_time=NOW + S), NOW)
    assert c.realised_today == D("-0.02")


def test_partial_close_keeps_the_open_value_for_the_next_fee_bound() -> None:
    c = counters(taker=D("0.01"))
    c.apply_fill(fill("o", opening=True, qty=D(2), exec_time=NOW - 3 * S), NOW)
    c.apply_position(RiskPosition("BTCUSDT", "buy", D(2), D(80), NOW - 2 * S))
    for n in (1, 0):
        c.apply_fill(fill(f"c{n}", price=D(80), order_ref=f"c{n}", exec_time=NOW - n * S), NOW)
    assert c.realised_today == D(-2)  # 1 % of the opening value 100 each, never of 80


def test_backfilled_close_times_out_on_its_exact_figure() -> None:
    c = opened()
    close(c, exec_pnl=None)
    assert c.expire_records(NOW + 5 * 60 * S) == ("o1",)
    assert c.settled_today == D("-10.07")


def test_fill_at_the_key_start_is_booked_today() -> None:
    c = counters(taker=D(0))
    start = NOW - 12 * H
    assert c.apply_fill(fill("s", exec_pnl=D(-5), exec_time=start), NOW) is FillOutcome.APPLIED
    assert c.realised_today == D(-5)


def test_loss_run_recounts_when_a_close_moves_to_the_end() -> None:
    c = counters(taker=D(0))
    for eid, ref, back in (("a", "a", 0), ("b", "b", 1), ("a2", "a", 2)):
        c.apply_fill(fill(eid, exec_pnl=D(-1), order_ref=ref, exec_time=NOW + back * S), NOW)
    assert (figures := c.figures(NOW)) is not None and figures.consecutive_losses == 2


def test_closes_at_one_instant_keep_their_arrival_order_on_a_recount() -> None:
    c = counters(taker=D(0))
    c.apply_fill(fill("b", exec_pnl=D(-1), price=D(99), order_ref="b"), NOW)
    c.apply_fill(fill("a", exec_pnl=D(1), order_ref="a"), NOW)
    tighten = record(pnl=D("0.5"), avg_exit_price=D(100))
    assert c.apply_venue_record(tighten, NOW) is RecordOutcome.TIGHTENED
    assert (figures := c.figures(NOW)) is not None and figures.consecutive_losses == 0


def test_sibling_count_follows_each_confirmed_close() -> None:
    c = counters(taker=D(0))
    for ref, price in (("x", 90), ("y", 91), ("z", 92)):
        c.apply_fill(fill(ref, price=D(price), exec_pnl=D(price - 100), order_ref=ref), NOW)
    assert c.apply_venue_record(record(pnl=-20), NOW) is RecordOutcome.TIGHTENED
    held = record("r2", pnl=-9, avg_exit_price=D(91))
    assert c.apply_venue_record(held, NOW) is RecordOutcome.HELD  # z still awaits


def test_record_matches_a_close_of_two_lots_in_one_fill() -> None:
    c = counters(taker=D(0))
    c.apply_fill(fill("o", opening=True, qty=D(2)), NOW)
    c.apply_fill(fill("c", qty=D(2), price=D(90), exec_pnl=D(-20)), NOW)
    assert c.apply_venue_record(record(pnl=-21, qty=D(2)), NOW) is RecordOutcome.TIGHTENED


def test_partial_closing_fills_time_out_on_their_summed_figure() -> None:
    c = counters(taker=D(0))
    c.apply_fill(fill("o", opening=True, qty=D(2)), NOW)
    for eid in ("p1", "p2"):
        c.apply_fill(fill(eid, price=D(90), fee=D("0.05"), exec_pnl=D(-10)), NOW)
    assert c.expire_records(NOW + 5 * 60 * S) == ("o1",) and c.settled_today == D("-20.1")


def test_record_dated_at_the_close_matches_it() -> None:
    c = opened()
    close(c)
    assert c.apply_venue_record(record(pnl=-11, updated_at=NOW), NOW) is RecordOutcome.TIGHTENED


def test_unmatched_records_are_each_kept_and_recounted() -> None:
    c = counters(taker=D(0))
    for rid, pnl, at in (("u1", -3, NOW + 30 * S), ("u2", -4, NOW)):  # u2 lands before u1
        unmatched = record(rid, pnl=pnl, qty=D(5), updated_at=at)
        assert c.apply_venue_record(unmatched, NOW) is RecordOutcome.UNMATCHED_BOOKED
    assert c.settled_today == D(-7) and c.realised_today == D(-7)
    assert (figures := c.figures(NOW)) is not None and figures.consecutive_losses == 2


def test_record_equal_to_the_bound_with_a_sibling_is_held() -> None:
    c = opened()
    close(c)
    c.apply_fill(fill("open2", opening=True, order_ref="o2"), NOW)
    c.apply_fill(fill("c2", order_ref="o3", price=D(99), exec_pnl=D(-1)), NOW)
    assert c.apply_venue_record(record(pnl=D("-10.105")), NOW) is RecordOutcome.HELD


def test_confirmed_close_is_unchanged_by_an_equal_record() -> None:
    c = opened()
    close(c)
    assert c.apply_venue_record(record(pnl=-12), NOW) is RecordOutcome.TIGHTENED
    assert c.apply_venue_record(record("r2", pnl=-12), NOW) is RecordOutcome.UNCHANGED


def test_confirmed_close_joined_by_a_later_fill_times_out_on_the_record() -> None:
    c = opened()
    close(c)
    assert c.apply_venue_record(record(pnl=-12), NOW) is RecordOutcome.TIGHTENED
    assert c._closes["o1"].state is CloseState.CONFIRMED
    c.apply_fill(fill("c2", price=D(90), exec_pnl=D(-1), exec_time=NOW + S), NOW)
    assert c.unconfirmed and c.expire_records(NOW + 5 * 60 * S) == ("o1",)
    assert c.settled_today == D(-13)  # the record's -12, then the new fill's own -1


def test_figures_sum_every_open_position_and_both_hedge_sides() -> None:
    c = counters(taker=D(0))
    c.apply_fill(fill("b", opening=True), NOW)
    c.apply_fill(fill("bc", order_ref="bc"), NOW)  # BTCUSDT is flat, and first
    for symbol, side in (("SOLUSDT", "buy"), ("ETHUSDT", "sell"), ("ETHUSDT", "buy")):
        c.apply_fill(fill(f"{symbol}{side}", symbol=symbol, position_side=side, opening=True), NOW)
    c.apply_mark(mark(105, symbol="SOLUSDT"))
    c.apply_mark(mark(80, symbol="ETHUSDT"))
    figures = c.figures(NOW)
    assert figures is not None and figures.open_positions == 3
    assert figures.symbol_notional == {"SOLUSDT": D(105), "ETHUSDT": D(160)}
    assert figures.daily_figure == 0  # +5 and +20 net the -20: a gain never counts, a net does


def test_early_fill_dated_at_the_next_key_end_waits_one_more_day() -> None:
    c = counters(taker=D(0))
    end = NOW + 36 * H
    assert c.apply_fill(fill("e", exec_pnl=D(-7), exec_time=end), NOW) is FillOutcome.QUEUED
    assert c.figures(NOW + 12 * H) is not None and c.realised_today == 0
    assert c.figures(end) is not None and c.realised_today == D(-7)
    assert c.expire_records(end + 5 * 60 * S) == ("o1",)


def test_record_match_is_independent_of_the_ambient_decimal_rounding() -> None:
    c = counters(taker=D(0))
    c.apply_fill(fill("c", price=D("89.96"), exec_pnl=D(-10)), NOW)
    with localcontext(rounding=ROUND_DOWN):  # 899.6 and 900.4 ticks: both 900, half-even
        outcome = c.apply_venue_record(record(pnl=-11, avg_exit_price=D("90.04")), NOW)
    assert outcome is RecordOutcome.TIGHTENED


def test_offset_change_keeps_the_day_loss_run_and_peak() -> None:  # BQ-10: `_roll`'s key test
    calendar = DayCalendar(0, NOW)
    c = counters_module.AccountCounters(calendar, taker_rate=D(0))
    c.set_equity(D(100_000), NOW)
    c.mark_ready()
    c.apply_fill(fill("g", exec_pnl=D(200), order_ref="o1"), NOW)
    assert c.figures(NOW) is not None  # the peak is read at 200
    c.apply_fill(fill("l", exec_pnl=D(-5200), order_ref="o2", exec_time=NOW + S), NOW + S)
    before = c.figures(NOW + S)
    assert before is not None
    assert (before.daily_figure, before.day_peak_figure, before.consecutive_losses) == (
        D(-5000),
        D(200),
        1,
    )
    calendar.change_offset(-60, NOW + 2 * S)  # stretches the key; the day is the same
    after = c.figures(NOW + 3 * S)
    assert after is not None
    assert (after.daily_figure, after.day_peak_figure, after.consecutive_losses) == (
        D(-5000),
        D(200),
        1,
    )


@pytest.mark.parametrize(
    ("after", "outcome"),
    [
        (timedelta(seconds=120), RecordOutcome.TIGHTENED),
        (timedelta(seconds=120, microseconds=1), RecordOutcome.UNMATCHED_BOOKED),
    ],
    ids=["at_120s_matches", "past_120s_unmatched"],
)
def test_record_match_window_is_120_seconds(after: timedelta, outcome: RecordOutcome) -> None:
    c = opened()
    close(c)  # its last fill at NOW
    assert c.apply_venue_record(record(pnl=-12, updated_at=NOW + after), NOW) is outcome


def test_mark_gap_is_unavailable_until_ready_again() -> None:  # K01 §5.5
    c = opened()
    c.apply_mark(mark(100))
    assert c.figures(NOW) is not None
    c.mark_gap()
    assert c.figures(NOW) is None
    c.mark_ready()
    assert c.figures(NOW) is not None
