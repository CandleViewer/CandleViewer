"""E39-T01 (#881) slice 2: the reservation ledger (SR-E39-04, BQ-7).

`admit` evaluates on the counters plus every in-flight reservation and reserves in the same
synchronous step, so two submits near a cap cannot both pass; reservations convert on fill and are
released on refusal, cancel or a terminal state; an exempt close is never refused.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.domain.primitives import AccountId, UserId
from candleviewer.risk import ledger as ledger_module
from candleviewer.risk.inputs import RiskOrder, VenueClosedPnl
from candleviewer.risk.ledger import RECONCILE_GRACE, ReservationLedger, admit
from candleviewer.risk.models import RiskRefusal
from tests.unit.risk._risk_builders import NOW, D, caps, close_order, counters, instrument, order

S = timedelta(seconds=1)
_LOSS = VenueClosedPnl("r", "ETHUSDT", "buy", D(1), D(1), D("0.1"), D(-100), NOW)
TOTAL = caps(pol={"max_total_notional_usd": D(25_000)})


def test_admit_two_submits_near_the_cap_one_refused_until_released() -> None:
    c, ledger = counters(), ReservationLedger()
    first = admit("a", order(notional=D(15_000)), TOTAL, c, ledger, now=NOW)
    second = admit("b", order(notional=D(15_000)), TOTAL, c, ledger, now=NOW)
    assert first.decision.allowed and not second.decision.allowed
    assert second.decision.cap == "max_total_notional_usd" and second.decision.actual == 15_000
    assert ledger.release("a", filled_notional=D(0)) and not ledger.release(
        "a", filled_notional=D(0)
    )
    assert admit("b", order(notional=D(15_000)), TOTAL, c, ledger, now=NOW).decision.allowed


def test_admit_on_fill_converts_the_reservation() -> None:
    c, ledger = counters(), ReservationLedger()
    admit("a", order(notional=D(15_000)), TOTAL, c, ledger, now=NOW)
    ledger.on_fill("a", "e1", D(10_000))
    ledger.on_fill("missing", "e2", D(1))
    assert ledger.reserved_notional == D(5_000)
    held = ledger._pending["a"]
    assert (held.symbol, held.notional, held.opens_position) == ("BTCUSDT", D(5_000), False)
    ledger.on_fill("a", "e3", D(99_999))
    assert ledger.reserved_notional == 0 and "a" in ledger


def test_admit_counts_in_flight_orders_and_trailing_minute_sends() -> None:
    c, ledger = counters(), ReservationLedger()
    limit = caps(pol={"max_orders_per_minute": 2}, prof={"max_concurrent_orders": 2})
    for ref in ("a", "b"):
        assert admit(ref, order(), limit, c, ledger, now=NOW).decision.allowed
    assert admit("c", order(), limit, c, ledger, now=NOW).decision.cap == "max_orders_per_minute"
    ledger.release("a", filled_notional=D(0))
    ledger.release("b", filled_notional=D(0))
    later = NOW + 60 * S
    assert admit("c", order(), limit, c, ledger, now=later).decision.allowed
    assert admit("d", order(), limit, c, ledger, now=later).decision.allowed
    refused = admit("e", order(), limit, c, ledger, now=later + S).decision
    assert refused.cap == "max_orders_per_minute"
    working = admit("e", order(), limit, c, ledger, now=later + 61 * S).decision
    assert working.cap == "max_concurrent_orders"


def test_admit_pending_opens_count_toward_open_positions() -> None:
    c, ledger = counters(), ReservationLedger()
    limit = caps(pol={"max_open_positions": 1})
    assert admit("a", order(), limit, c, ledger, now=NOW).decision.allowed
    assert admit("b", order(), limit, c, ledger, now=NOW).decision.cap == "max_open_positions"


def test_admit_refuses_when_unavailable_or_full() -> None:
    c, ledger = counters(), ReservationLedger(max_pending=1)
    cold = counters()
    cold._ready = False
    assert admit("x", order(), TOTAL, cold, ledger, now=NOW).decision.message == (
        "risk state is unavailable"
    )
    first = admit("a", order(), TOTAL, c, ledger, now=NOW)
    full = admit("b", order(), TOTAL, c, ledger, now=NOW).decision
    assert full.code is RiskRefusal.RISK_STATE_UNAVAILABLE
    assert not ledger.reserve("b", order(), NOW, first)


def test_admit_repeated_reference_returns_its_verdict_and_reserves_nothing() -> None:  # m4
    c, ledger = counters(), ReservationLedger()
    first = admit("a", order(notional=D(1)), TOTAL, c, ledger, now=NOW)
    again = admit("a", order(notional=D(1)), TOTAL, c, ledger, now=NOW + S)
    assert again is first and first.decision.allowed and ledger.verdict("a") is first
    assert ledger.reserved_notional == 1 and len(ledger._sent) == 1
    assert (
        ledger.release("a", filled_notional=D(0))
        and ledger.verdict("a") is None
        and ledger.reserved_notional == 0
    )


def test_admit_never_admits_unreserved(monkeypatch: pytest.MonkeyPatch) -> None:  # l6
    c, ledger = counters(), ReservationLedger()
    monkeypatch.setattr(ledger, "reserve", lambda *_: False)
    refused = admit("a", order(), TOTAL, c, ledger, now=NOW).decision
    assert refused.code is RiskRefusal.RISK_STATE_UNAVAILABLE and "a" not in ledger


def test_admit_send_bound_refuses_opening_orders() -> None:
    c, ledger = counters(), ReservationLedger(max_submits=1)
    assert admit("a", order(), TOTAL, c, ledger, now=NOW).decision.allowed
    ledger.release("a", filled_notional=D(0))
    assert not admit("b", order(), TOTAL, c, ledger, now=NOW).decision.allowed


def test_admit_exempt_close_never_refused_and_holds_no_notional() -> None:
    c, ledger = counters(), ReservationLedger(max_pending=1)
    c._ready = False  # even with the state unavailable
    assert admit("z", close_order(), TOTAL, c, ledger, now=NOW).decision.allowed
    assert admit("z", close_order(), TOTAL, c, ledger, now=NOW).decision.allowed
    assert admit("y", close_order(), TOTAL, c, ledger, now=NOW).decision.allowed  # full: unrecorded
    assert "z" in ledger and "y" not in ledger and ledger.reserved_notional == 0


def test_admit_repeated_exempt_close_is_recorded_once() -> None:
    c, ledger = counters(), ReservationLedger()
    for _ in range(2):
        assert admit("z", close_order(), TOTAL, c, ledger, now=NOW).decision.allowed
    assert len(ledger._sent) == 1


def test_admit_lockout_and_kill_switch_are_plain_inputs() -> None:
    c, ledger = counters(), ReservationLedger()
    locked = admit("a", order(), TOTAL, c, ledger, now=NOW, lockout_active=True).decision
    killed = admit("b", order(), TOTAL, c, ledger, now=NOW, kill_switch_engaged=True).decision
    assert locked.code is RiskRefusal.ACCOUNT_LOCKED and killed.code is RiskRefusal.TRADING_DISABLED
    assert "a" not in ledger and "b" not in ledger


@given(
    cap=st.decimals(min_value=0, max_value=10**6, places=2),
    steps=st.lists(
        st.tuples(st.booleans(), st.decimals(min_value=0, max_value=10**5, places=2)), max_size=40
    ),
)
def test_reserved_sum_never_exceeds_the_cap_headroom(
    cap: Decimal, steps: list[tuple[bool, Decimal]]
) -> None:
    c, ledger = counters(), ReservationLedger()
    limit = caps(pol={"max_total_notional_usd": cap, "max_orders_per_minute": 10**6})
    refs: list[str] = []
    for n, (submit, notional) in enumerate(steps):
        if submit or not refs:
            if admit(str(n), order(notional=notional), limit, c, ledger, now=NOW).decision.allowed:
                refs.append(str(n))
        else:
            ledger.release(refs.pop(0), filled_notional=D(0))
        assert ledger.reserved_notional <= cap


@pytest.mark.parametrize(
    "fields",
    [
        {"notional": D(10_000_000)},
        {"side": "sell"},
        {"qty": D(2)},
        {"opens_position": False},
        {"opens_exposure": False, "reduce_only": True},
        {"reduce_only": True},
        {"user_id": UserId(UUID(int=9))},
        {"user_id": None},
        {"account_id": AccountId(UUID(int=9))},
        {"environment": "live"},
        {"paper": True},
    ],
)
def test_admit_reused_reference_for_another_order_is_refused_closed(
    fields: dict[str, object],
) -> None:  # m8: the lens probe; the held reservation is kept as it was
    c, ledger = counters(), ReservationLedger()
    first = admit("ref", order(notional=D(1)), TOTAL, c, ledger, now=NOW)
    other = admit("ref", order(**{"notional": D(1)} | fields), TOTAL, c, ledger, now=NOW + S)
    assert other.decision.code is RiskRefusal.RISK_STATE_UNAVAILABLE
    assert other.decision.cap == "order_ref" and other.decision.evaluated_at == NOW + S
    assert ledger.verdict("ref") is first and ledger.reserved_notional == 1


def test_admit_reused_exempt_reference_for_an_opening_order_is_refused() -> None:  # m8
    c, ledger = counters(), ReservationLedger()
    assert admit("ref2", close_order(), TOTAL, c, ledger, now=NOW).decision.allowed
    opening = admit("ref2", order(notional=D(10_000_000)), TOTAL, c, ledger, now=NOW)
    assert opening.decision.cap == "order_ref" and ledger.reserved_notional == 0


@pytest.mark.parametrize(
    ("held", "exempt"),
    [
        (close_order, lambda: replace(close_order(), qty=D(2))),  # an amended close
        (lambda: order(notional=D(15_000)), close_order),  # a close on an opening's reference
    ],
)
def test_admit_exempt_on_a_reference_held_by_another_order_is_admitted(
    held: Callable[[], RiskOrder], exempt: Callable[[], RiskOrder]
) -> None:  # M3: exempt first; the held reservation is kept, not replaced nor charged twice
    c, ledger = counters(), ReservationLedger()
    first = admit("ref", held(), TOTAL, c, ledger, now=NOW)
    assert first.decision.allowed
    notional, sends = ledger.reserved_notional, len(ledger._sent)
    again = admit("ref", exempt(), TOTAL, c, ledger, now=NOW + S)
    assert again.decision.allowed and again.decision.evaluated_at == NOW + S
    assert ledger.verdict("ref") is first and ledger.holds_same("ref", held())
    assert ledger.reserved_notional == notional and len(ledger._sent) == sends


def test_reconcile_releases_only_what_is_no_longer_open() -> None:  # BQ-7
    c, ledger = counters(), ReservationLedger()
    for ref in ("open", "gone"):
        admit(ref, order(notional=D(10)), TOTAL, c, ledger, now=NOW)
    admit("young", order(notional=D(10)), TOTAL, c, ledger, now=NOW + S)
    as_of = NOW + RECONCILE_GRACE
    nothing = {"open": D(0), "gone": D(0), "young": D(0)}
    assert ledger.reconcile({"open"}, as_of, complete=True, filled=nothing) == ("gone",)
    assert "open" in ledger and "young" in ledger and ledger.reserved_notional == 20
    assert ledger.reconcile(set(), as_of + S, complete=True, filled=nothing) == ("open", "young")
    assert ledger.reserved_notional == 0


def test_reconcile_on_an_incomplete_read_releases_nothing() -> None:  # m12
    c, ledger = counters(), ReservationLedger()
    admit("open", order(notional=D(10)), TOTAL, c, ledger, now=NOW)
    later = NOW + 10 * RECONCILE_GRACE
    assert ledger.reconcile(set(), later, complete=False, filled={"open": D(0)}) == ()
    assert "open" in ledger and ledger.reserved_notional == 10


def test_admit_passes_the_override_allowance_to_evaluate() -> None:  # BQ-3
    c, ledger = counters(), ReservationLedger()
    c.apply_venue_record(_LOSS, NOW)
    limit = caps(prof={"max_daily_loss_usd": D(100)})
    assert admit("a", order(), limit, c, ledger, now=NOW).decision.cap == "max_daily_loss_usd"
    lifted = admit("a", order(), limit, c, ledger, now=NOW, extra_loss_usd=D(50))
    assert lifted.decision.allowed


def test_reconcile_grace_is_60_seconds() -> None:  # BQ-7: the literal, not the constant
    c, ledger = counters(), ReservationLedger()
    admit("a", order(notional=D(10)), TOTAL, c, ledger, now=NOW)
    nothing = {"a": D(0)}
    young = NOW + timedelta(seconds=60) - timedelta(microseconds=1)
    assert ledger.reconcile(set(), young, complete=True, filled=nothing) == ()
    assert ledger.reconcile(set(), NOW + timedelta(seconds=60), complete=True, filled=nothing) == (
        "a",
    )


def test_release_keeps_filled_headroom_until_the_fill_converts() -> None:
    c, ledger = counters(), ReservationLedger()
    assert admit("a", order(notional=D(15_000)), TOTAL, c, ledger, now=NOW).decision.allowed
    assert ledger.release("a", filled_notional=D(15_000))  # terminal before its fill is applied
    second = admit("b", order(notional=D(15_000)), TOTAL, c, ledger, now=NOW).decision
    assert second.cap == "max_total_notional_usd" and second.actual == 15_000
    ledger.on_fill("a", "e4", D(15_000))
    assert "a" not in ledger and ledger.reserved_notional == 0


def test_reconcile_keeps_filled_headroom_until_the_fill_converts() -> None:
    c, ledger = counters(), ReservationLedger()
    admit("a", order(notional=D(15_000)), TOTAL, c, ledger, now=NOW)
    later = NOW + 61 * S
    assert ledger.reconcile(set(), later, complete=True, filled={}) == ()  # no figure: kept whole
    assert ledger.reconcile(set(), later, complete=True, filled={"a": D(15_000)}) == ("a",)
    assert not admit("b", order(notional=D(15_000)), TOTAL, c, ledger, now=later).decision.allowed
    assert ledger.reconcile(set(), later, complete=True, filled={"a": D(15_000)}) == ()
    ledger.on_fill("a", "e5", D(15_000))
    assert admit("b", order(notional=D(15_000)), TOTAL, c, ledger, now=later).decision.allowed


def test_release_holds_only_the_unconverted_part_and_no_order_slot() -> None:
    c, ledger = counters(), ReservationLedger()
    limit = caps(pol={"max_open_positions": 1}, prof={"max_concurrent_orders": 1})
    admit("a", order(notional=D(15_000)), limit, c, ledger, now=NOW)
    ledger.on_fill("a", "e6", D(3_000))
    ledger.on_fill("a", "e7", D(4_000))
    assert ledger.release("a", filled_notional=D(12_000)) and ledger.reserved_notional == 5_000
    assert (
        not ledger.release("a", filled_notional=D(9_000)) and ledger.reserved_notional == 5_000
    )  # stale read
    assert not ledger.release("a", filled_notional=D(14_000)) and ledger.reserved_notional == 7_000
    assert admit("b", order(), limit, c, ledger, now=NOW).decision.allowed  # no order slot held
    ledger.on_fill("a", "e8", D(6_000))
    assert ledger.reserved_notional == 1_000 + 10_000
    ledger.on_fill("a", "e9", D(1_000))
    assert "a" not in ledger


def test_release_of_a_converted_order_frees_everything() -> None:
    c, ledger = counters(), ReservationLedger()
    admit("a", order(notional=D(15_000)), TOTAL, c, ledger, now=NOW)
    ledger.on_fill("a", "e10", D(10_000))
    assert (
        ledger.release("a", filled_notional=D(5_000))
        and "a" not in ledger
        and ledger.reserved_notional == 0
    )


def test_released_unfilled_order_keeps_its_position_slot() -> None:
    c, ledger = counters(), ReservationLedger()
    limit = caps(pol={"max_open_positions": 1})
    admit("a", order(), limit, c, ledger, now=NOW)
    ledger.release("a", filled_notional=D(10_000))
    assert admit("b", order(), limit, c, ledger, now=NOW).decision.cap == "max_open_positions"


def test_released_reference_refuses_a_retry_and_keeps_an_exempt_close_apart() -> None:
    c, ledger = counters(), ReservationLedger()
    admit("a", order(notional=D(15_000)), TOTAL, c, ledger, now=NOW)
    ledger.release("a", filled_notional=D(15_000))
    retry = admit("a", order(notional=D(15_000)), TOTAL, c, ledger, now=NOW + S).decision
    assert retry.code is RiskRefusal.RISK_STATE_UNAVAILABLE and retry.cap == "order_ref"
    assert retry.message == (
        "the order reference belongs to a released order whose fills are still held"
    )
    assert admit("a", close_order(), TOTAL, c, ledger, now=NOW + S).decision.allowed
    assert ledger.verdict("a") is None and ledger.reserved_notional == 15_000


def test_on_fill_closing_leg_keeps_the_position_slot() -> None:
    c, ledger = counters(), ReservationLedger()
    limit = caps(pol={"max_open_positions": 1})
    assert admit("flip", order(), limit, c, ledger, now=NOW).decision.allowed
    ledger.on_fill("flip", "e11", D(0))  # the closing leg: no opening notional yet
    refused = admit(
        "b", order(instrument=instrument("ETHUSDT")), limit, c, ledger, now=NOW
    ).decision
    assert refused.cap == "max_open_positions"
    ledger.on_fill("flip", "e12", D(1))  # the opening leg converts: the slot moves to the position
    assert admit(
        "b", order(instrument=instrument("ETHUSDT")), limit, c, ledger, now=NOW
    ).decision.allowed


def test_on_fill_repeated_exec_id_converts_once(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ledger_module.MAX_FILLS == 1024  # pinned: the tests below patch it
    monkeypatch.setattr(ledger_module, "MAX_FILLS", 2)
    c, ledger = counters(), ReservationLedger()
    admit("a", order(notional=D(15_000)), TOTAL, c, ledger, now=NOW)
    for exec_id in ("x", "x", "y", "z"):  # a duplicate push, then one past the bound
        ledger.on_fill("a", exec_id, D(5_000))
    held = ledger._pending["a"]
    assert (held.notional, held.converted, held.fills) == (D(5_000), D(10_000), {"x", "y"})


MALFORMED = [D("NaN"), D("sNaN"), D("Infinity"), D("-Infinity"), D(-1)]


@pytest.mark.parametrize("bad", MALFORMED)
def test_on_fill_malformed_figure_keeps_the_hold_whole(bad: Decimal) -> None:
    c, ledger = counters(), ReservationLedger()
    admit("a", order(notional=D(15_000)), TOTAL, c, ledger, now=NOW)
    ledger.on_fill("a", "e13", bad)
    held = ledger._pending["a"]
    assert (held.notional, held.converted, held.opens_position) == (D(15_000), D(0), True)


@pytest.mark.parametrize("bad", MALFORMED)
def test_release_malformed_figure_keeps_the_hold_whole(bad: Decimal) -> None:
    c, ledger = counters(), ReservationLedger()
    admit("a", order(notional=D(15_000)), TOTAL, c, ledger, now=NOW)
    assert not ledger.release("a", filled_notional=bad)
    assert ledger.verdict("a") is not None and ledger.reserved_notional == 15_000
    later = NOW + 61 * S
    assert ledger.reconcile(set(), later, complete=True, filled={"a": bad}) == ()
    assert ledger.verdict("a") is not None and ledger.reserved_notional == 15_000


@given(
    chunks=st.lists(st.integers(min_value=1, max_value=5_000), min_size=1, max_size=6),
    at=st.integers(min_value=0, max_value=6),
)
def test_release_never_frees_a_fill_before_it_converts(chunks: list[int], at: int) -> None:
    c, ledger = counters(), ReservationLedger()
    filled = D(sum(chunks))
    admit("a", order(notional=filled), caps(), c, ledger, now=NOW)
    converted = D(0)
    for n, chunk in enumerate(chunks):
        if n == at:
            ledger.release(
                "a", filled_notional=filled
            )  # the terminal outcome lands before this fill converts
        assert converted + ledger.reserved_notional >= filled
        ledger.on_fill("a", f"e{n}", D(chunk))
        converted += chunk
    ledger.release("a", filled_notional=filled)
    assert "a" not in ledger and ledger.reserved_notional == 0
