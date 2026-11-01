"""E16-FR-01 (#1738, threat model R-S1, R-D2, AC-02): the cap on symbols recording for an open
chart alone, and the per-session cap and start rate on chart-open triggers. Fake clock, no I/O,
no sleeps."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.recorder.auto_caps import (
    DENIAL_AUDITS_PER_MIN,
    MAX_DENIED,
    MAX_SESSIONS,
    WINDOW_S,
    SessionAutoBook,
)
from candleviewer.recorder.metrics import (
    recorder_auto_record_active,
    recorder_auto_record_refused_total,
)
from candleviewer.recorder.policy import PolicyConfig, RecordingPolicy, user_actor
from candleviewer.recorder_wiring import policy_config
from candleviewer.settings import Settings
from tests.unit.recorder._fakes import FakeAudit, FakeBus, FakeClock, Mem

OWNER = user_actor("owner-1")


def _policy(clock: FakeClock, audit: FakeAudit, **cfg: Any) -> RecordingPolicy:
    p = RecordingPolicy(
        disk_refuses=bool,
        bus=FakeBus(),
        audit=audit,
        env="demo",
        now=clock,
        config=PolicyConfig(**cfg),
        recorded=Mem(),
    )
    p.positions_reloaded()
    return p


def _value(metric: Any, **labels: str) -> float:
    child = metric.labels(**labels) if labels else metric
    return float(child._value.get())


def _denied(audit: FakeAudit, reason: str) -> list[str]:
    return [
        kw["object_id"]
        for a, kw in audit.records
        if a == "recorder.start" and kw["outcome"] == "denied" and kw["reason"] == reason
    ]


def _sym(i: int) -> str:
    return f"S{i:03d}USDT"


async def test_auto_cap_holds_against_200_chart_opens_in_5_minutes(clock: FakeClock) -> None:
    """AC-02: 200 distinct charts over 5 simulated minutes; the auto set stays at the cap."""
    audit = FakeAudit()
    p = _policy(clock, audit, max_symbols=30, max_auto_symbols=20)
    before = _value(recorder_auto_record_refused_total, cause="auto_cap")
    try:
        for i in range(200):
            await p.on_chart_opened(_sym(i), f"c{i}", session_id=None)
            clock.advance(1.5)
            await p.tick()
            assert len(p.effective_set()) <= 20
        clock.advance(60)
        await p.tick()
        await p.tick()
        live = set(p.effective_set())
        assert len(live) == 20 and live == {_sym(i) for i in range(20)}
        refused = {_sym(i) for i in range(20, 200)}
        assert {s for s in refused if p.start_refusal(s) == "symbol_cap"} == refused  # wire cause
        assert _value(recorder_auto_record_refused_total, cause="auto_cap") == before + 180
        assert _value(recorder_auto_record_active) == 20
        denied = _denied(audit, "auto_cap_refused")
        assert sorted(denied) == sorted(refused)  # one denied record per symbol, not per tick
    finally:
        await p.stop()


async def test_manual_entries_are_neither_counted_nor_displaced_by_the_auto_cap(
    clock: FakeClock,
) -> None:
    audit = FakeAudit()
    p = _policy(clock, audit, max_symbols=5, max_auto_symbols=2)
    try:
        await p.add_manual("BTCUSDT", OWNER)
        await p.add_manual("ETHUSDT", OWNER)
        for i in range(3):
            await p.on_chart_opened(_sym(i), f"c{i}", session_id=None)
        clock.advance(60)
        await p.tick()
        assert set(p.effective_set()) == {"BTCUSDT", "ETHUSDT", _sym(0), _sym(1)}
        assert p.start_refusal(_sym(2)) == "symbol_cap"
        assert _denied(audit, "auto_cap_refused") == [_sym(2)]
        await p.add_manual("SOLUSDT", OWNER)  # the total cap still has room for a manual entry
        assert {"BTCUSDT", "ETHUSDT", "SOLUSDT"} <= set(p.effective_set())
    finally:
        await p.stop()


async def test_a_position_at_the_auto_cap_still_starts(clock: FakeClock) -> None:
    audit = FakeAudit()
    p = _policy(clock, audit, max_symbols=5, max_auto_symbols=1)
    try:
        await p.on_chart_opened(_sym(0), "c0", session_id=None)
        clock.advance(60)
        await p.tick()
        await p.on_position_opened("XRPUSDT", "p1")
        assert p.effective_set()["XRPUSDT"].reason == "position_open"
        assert _sym(0) in p.effective_set()
        assert _denied(audit, "auto_cap_refused") == []
    finally:
        await p.stop()


async def test_a_closed_chart_frees_its_auto_slot_after_the_grace(clock: FakeClock) -> None:
    audit = FakeAudit()
    p = _policy(clock, audit, max_auto_symbols=1)
    try:
        await p.on_chart_opened("BTCUSDT", "c1", session_id=None)
        await p.on_chart_opened("ETHUSDT", "c2", session_id=None)
        clock.advance(60)
        await p.tick()
        assert set(p.effective_set()) == {"BTCUSDT"}
        await p.on_chart_closed("BTCUSDT", "c1", session_id=None)
        await p.tick()
        assert set(p.effective_set()) == {"BTCUSDT"}  # lingering: the slot is still held
        clock.advance(1_801)
        await p.tick()
        await p.tick()
        assert set(p.effective_set()) == {"ETHUSDT"}
    finally:
        await p.stop()


async def test_a_session_past_its_distinct_symbol_cap_is_refused(clock: FakeClock) -> None:
    audit = FakeAudit()
    p = _policy(clock, audit, max_symbols=100, max_auto_symbols=100)
    before = _value(recorder_auto_record_refused_total, cause="session_cap")
    try:
        for i in range(20):  # 10 a minute: under the rate
            await p.on_chart_opened(_sym(i), f"c{i}", session_id="sess-a")
            if i == 9:
                clock.advance(60)
        clock.advance(60)
        await p.on_chart_opened(_sym(20), "c20", session_id="sess-a")
        await p.on_chart_opened(_sym(20), "c21", session_id="sess-a")
        assert not p.chart_open(_sym(20))  # the ref is not taken: the chart stays live-only
        assert all(p.chart_open(_sym(i)) for i in range(20))  # held refs are unaffected
        assert _value(recorder_auto_record_refused_total, cause="session_cap") == before + 2
        assert _denied(audit, "session_cap_refused") == [_sym(20)]  # audited once
        await p.on_chart_opened(_sym(3), "c3b", session_id="sess-a")  # a held symbol: admitted
        assert p.chart_open(_sym(3))
        await p.on_chart_closed(_sym(0), "c0", session_id="sess-a")  # frees one slot
        await p.on_chart_opened(_sym(20), "c22", session_id="sess-a")
        assert p.chart_open(_sym(20))
    finally:
        await p.stop()


async def test_a_session_past_its_start_rate_is_refused_until_the_window_moves(
    clock: FakeClock,
) -> None:
    audit = FakeAudit()
    p = _policy(clock, audit, max_symbols=100, max_auto_symbols=100)
    before = _value(recorder_auto_record_refused_total, cause="session_rate")
    t0 = clock.t
    try:
        for i in range(10):
            await p.on_chart_opened(_sym(i), f"c{i}", session_id="sess-a")
            clock.advance(1)
        await p.on_chart_opened(_sym(10), "c10", session_id="sess-a")
        assert not p.chart_open(_sym(10))
        assert _value(recorder_auto_record_refused_total, cause="session_rate") == before + 1
        assert _denied(audit, "session_rate_refused") == [_sym(10)]
        await p.on_chart_opened(_sym(11), "c11", session_id="sess-b")  # another session
        await p.on_chart_opened(
            _sym(12), "c12", session_id=None
        )  # no session: the global caps only
        assert p.chart_open(_sym(11)) and p.chart_open(_sym(12))
        clock.t = t0 + 59.5
        await p.on_chart_opened(_sym(10), "c10", session_id="sess-a")
        assert not p.chart_open(_sym(10))
        clock.t = t0 + 60  # the first start leaves the 60 s window
        await p.on_chart_opened(_sym(10), "c10", session_id="sess-a")
        assert p.chart_open(_sym(10))
    finally:
        await p.stop()


def test_the_session_book_is_bounded_and_evicts_the_least_recently_used() -> None:
    book = SessionAutoBook(max_per_session=20, rate_per_min=10)
    for i in range(MAX_SESSIONS + 1):
        book.commit(f"s{i}", "BTCUSDT", "c", 0.0)
    assert len(book) == MAX_SESSIONS
    assert "s0" not in book and f"s{MAX_SESSIONS}" in book


def test_the_session_book_forgets_a_session_with_nothing_held_or_in_window() -> None:
    book = SessionAutoBook(max_per_session=2, rate_per_min=2)
    book.commit("s", "BTCUSDT", "c1", 0.0)
    book.release("s", "BTCUSDT", "c1", 30.0)
    assert "s" in book  # its start is still in the rate window
    book.release("s", "BTCUSDT", "c1", 60.0)
    assert "s" not in book
    book.release("gone", "BTCUSDT", "c1", 60.0)  # an unknown session is a no-op
    with pytest.raises(ValueError):
        SessionAutoBook(max_per_session=0, rate_per_min=1)


def test_the_session_book_audits_a_bounded_number_of_denials() -> None:
    book = SessionAutoBook(max_per_session=1, rate_per_min=1)
    firsts = [
        book.first_denial("s", f"S{i}", (i // DENIAL_AUDITS_PER_MIN) * WINDOW_S)
        for i in range(MAX_DENIED + 1)
    ]
    assert firsts.count(True) == MAX_DENIED and firsts[-1] is False
    assert book.first_denial("s", "S0", 1e9) is False  # each (session, symbol) once


def test_the_session_book_audits_a_denial_burst_at_its_rate() -> None:
    book = SessionAutoBook(max_per_session=1, rate_per_min=1)
    burst = [book.first_denial("s", f"S{i}", 0.0) for i in range(50)]
    assert burst.count(True) == DENIAL_AUDITS_PER_MIN
    assert book.first_denial("s", "S49", WINDOW_S - 0.5) is False  # the window has not moved
    assert book.first_denial("s", "S49", WINDOW_S) is True  # not audited yet: audited now
    assert book.first_denial("s", "S0", WINDOW_S) is False  # audited once already


async def test_a_session_denial_burst_is_counted_in_full_and_audited_at_the_rate(
    clock: FakeClock,
) -> None:
    audit = FakeAudit()
    p = _policy(clock, audit, max_symbols=100, max_auto_symbols=100, max_auto_per_session=1)
    before = _value(recorder_auto_record_refused_total, cause="session_cap")
    try:
        await p.on_chart_opened(_sym(0), "c0", session_id="sess-a")
        for i in range(1, 51):
            await p.on_chart_opened(_sym(i), f"c{i}", session_id="sess-a")
        assert _value(recorder_auto_record_refused_total, cause="session_cap") == before + 50
        assert len(_denied(audit, "session_cap_refused")) == DENIAL_AUDITS_PER_MIN
    finally:
        await p.stop()


async def test_the_auto_cap_admits_no_new_chart_start_while_a_transition_holds_it_over(
    clock: FakeClock,
) -> None:
    """An admission cap: a manual entry that ends under an open chart leaves the symbol recording
    for its chart (nothing is stopped), past the cap; the next chart-open start is refused."""
    audit = FakeAudit()
    p = _policy(clock, audit, max_symbols=10, max_auto_symbols=1)
    try:
        await p.on_chart_opened(_sym(0), "c0", session_id=None)
        await p.add_manual("BTCUSDT", OWNER)
        await p.on_chart_opened("BTCUSDT", "c1", session_id=None)
        clock.advance(60)
        await p.tick()
        assert _value(recorder_auto_record_active) == 1
        await p.remove_manual("BTCUSDT", OWNER)
        await p.tick()
        assert {_sym(0), "BTCUSDT"} <= set(p.effective_set())  # neither recording is stopped
        assert _value(recorder_auto_record_active) == 2
        await p.on_chart_opened(_sym(1), "c2", session_id=None)
        clock.advance(60)
        await p.tick()
        assert p.start_refusal(_sym(1)) == "symbol_cap"
        assert _sym(1) not in p.effective_set()
        assert _denied(audit, "auto_cap_refused") == [_sym(1)]
    finally:
        await p.stop()


_steps = st.lists(
    st.tuples(st.sampled_from(["open", "close", "wait"]), st.integers(0, 7)),
    min_size=1, max_size=20,
)  # fmt: skip


@settings(max_examples=25, deadline=None)
@given(_steps)
async def test_property_auto_symbols_never_exceed_the_cap(steps: list[tuple[str, int]]) -> None:
    clock = FakeClock()
    p = _policy(clock, FakeAudit(), max_auto_symbols=3, autostop_grace_s=120.0)
    try:
        for op, i in steps:
            if op == "open":
                await p.on_chart_opened(_sym(i), f"c{i}", session_id=None)
            elif op == "close":
                await p.on_chart_closed(_sym(i), f"c{i}", session_id=None)
            else:
                clock.advance(45)
            await p.tick()
            assert len(p.effective_set()) <= 3
    finally:
        await p.stop()


def test_settings_map_the_auto_caps_onto_the_policy() -> None:
    s = Settings()
    assert (
        s.recorder_max_auto_symbols,
        s.recorder_max_auto_per_session,
        s.recorder_auto_start_rate_per_min,
    ) == (20, 20, 10)
    cfg = policy_config(
        Settings(
            recorder_max_auto_symbols=3,
            recorder_max_auto_per_session=4,
            recorder_auto_start_rate_per_min=5,
        )
    )
    assert (cfg.max_auto_symbols, cfg.max_auto_per_session, cfg.auto_start_rate_per_min) == (
        3,
        4,
        5,
    )
