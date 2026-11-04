"""E40-T03 gating pipeline: each gate in isolation and the normative ORDER (table-driven)."""

from __future__ import annotations

import pytest

from candleviewer.alerts.gating import (
    GATE_ORDER,
    MAX_BAR_KEYS,
    TIMEFRAME_MS,
    AlertState,
    GateResult,
    StormSuppressor,
    bar_open_ms,
    gate,
)

NOW = 1_790_000_000_000


def st(**kw: object) -> AlertState:
    base: dict[str, object] = dict(
        id="a", owner_user_id="u", name="n", symbol="BTCUSDT", condition_hash="h",
        trigger_mode="every_time", cooldown_seconds=60, severity="info", channels=("in_app",),
        message_template="", timeframe="5m",
    )  # fmt: skip
    base.update(kw)
    return AlertState(**base)  # type: ignore[arg-type]  # test builder over a kw dict


def run(a: AlertState, storm: StormSuppressor | None = None, *, muted: bool = False,
        critical: bool = False, ts: int = NOW) -> GateResult:  # fmt: skip
    return gate(a, NOW, ts, storm or StormSuppressor(),
                muted=lambda _a: muted, critical_override=lambda _a: critical)  # fmt: skip


def full_storm() -> StormSuppressor:
    s = StormSuppressor(limit=1)
    s.record("u", NOW)
    return s


#: Every gate closed at once except the ones *before* it: the FIRST closed gate in
#: `GATE_ORDER` must win, and `checked` must be exactly the prefix up to it.
CLOSERS: dict[str, dict[str, object]] = {
    "enabled": {"enabled": False},
    "deleted": {"deleted": True},
    "expired": {"expires_at_ms": NOW},
    "snoozed": {"snoozed_until_ms": NOW + 1},
    "muted": {},
    "cooldown": {"last_fired_ms": NOW - 1},
}


@pytest.mark.parametrize("first", [g for g in GATE_ORDER if g in CLOSERS])
def test_gate_order_first_closed_gate_wins_and_later_gates_unchecked(first: str) -> None:
    idx = GATE_ORDER.index(first)
    kw: dict[str, object] = {}
    for g in GATE_ORDER[idx:]:
        kw.update(CLOSERS.get(g, {}))
    r = run(st(**kw), full_storm(), muted="muted" in GATE_ORDER[idx:])
    assert r.passed is False and r.reason == first
    assert r.checked == GATE_ORDER[: idx + 1]


def test_gate_order_constant_matches_ticket() -> None:
    assert GATE_ORDER == ("enabled", "deleted", "expired", "snoozed", "muted",
                          "trigger_mode", "cooldown", "storm")  # fmt: skip


def test_gate_snoozed_checked_before_cooldown_so_cooldown_not_consumed() -> None:
    r = run(st(snoozed_until_ms=NOW + 1, last_fired_ms=NOW - 1))
    assert r.reason == "snoozed" and "cooldown" not in r.checked


def test_gate_all_open_passes_through_every_gate() -> None:
    r = run(st())
    assert r.passed and r.checked == GATE_ORDER and not r.storm


def test_gate_snooze_in_past_is_open() -> None:
    assert run(st(snoozed_until_ms=NOW)).passed


def test_gate_expiry_in_future_is_open() -> None:
    assert run(st(expires_at_ms=NOW + 1)).passed


def test_gate_muted_but_critical_override_passes() -> None:
    assert run(st(), muted=True, critical=True).passed


def test_gate_muted_follows_critical_override() -> None:
    held = run(st(), muted=True, critical=False)
    assert held.passed is False and held.reason == "muted"
    assert run(st(), muted=True, critical=True).passed


@pytest.mark.parametrize(
    "closed", [g for g in GATE_ORDER if g in CLOSERS and g != "muted"] + ["storm"]
)
def test_gate_critical_override_does_not_reopen_other_closed_gates(closed: str) -> None:
    """Critical override is consulted only by the muted gate; every other closed gate holds."""
    r = run(st(**CLOSERS.get(closed, {})), full_storm() if closed == "storm" else None,
            muted=True, critical=True)  # fmt: skip
    assert r.passed is False and r.reason == closed


def test_gate_cooldown_boundary_exactly_elapsed_reopens() -> None:
    assert run(st(last_fired_ms=NOW - 60_000)).passed
    assert run(st(last_fired_ms=NOW - 59_999)).reason == "cooldown"


def test_gate_cooldown_ignored_for_once_per_bar() -> None:
    assert run(st(trigger_mode="once_per_bar", last_fired_ms=NOW - 1)).passed


def test_gate_storm_marks_storm_not_plain_failure() -> None:
    r = run(st(), full_storm())
    assert r.reason == "storm" and r.storm and r.checked == GATE_ORDER


def test_gate_once_per_bar_late_revision_does_not_reopen_key() -> None:
    a = st(trigger_mode="once_per_bar")
    bar = bar_open_ms(NOW, "5m")
    a.remember_bar(bar)
    late = run(a, ts=bar + 1)  # late tick revising the already-fired bar
    assert late.reason == "trigger_mode" and late.bar_open == bar
    assert run(a, ts=bar + TIMEFRAME_MS["5m"]).passed  # next bar is a new key


@pytest.mark.parametrize("tf", sorted(TIMEFRAME_MS))
def test_bar_open_every_timeframe_is_floor_and_stable(tf: str) -> None:
    ms = TIMEFRAME_MS[tf]
    b = bar_open_ms(NOW, tf)
    assert b <= NOW < b + ms
    assert bar_open_ms(b, tf) == b and bar_open_ms(b + ms - 1, tf) == b


def test_bar_open_weekly_anchored_to_monday() -> None:
    from datetime import UTC, datetime

    d = datetime.fromtimestamp(bar_open_ms(NOW, "1w") / 1000, tz=UTC)
    assert d.weekday() == 0 and (d.hour, d.minute) == (0, 0)


def test_bar_keys_bounded() -> None:
    a = st(trigger_mode="once_per_bar")
    for i in range(MAX_BAR_KEYS + 5):
        a.remember_bar(i)
    assert len(a.fired_bars) == MAX_BAR_KEYS and 0 not in a.fired_bars


def test_storm_window_boundaries_exactly_n_then_n_plus_1() -> None:
    s = StormSuppressor(limit=20, window_ms=60_000)
    for i in range(20):
        assert not s.in_storm("u", NOW + i)
        s.record("u", NOW + i)
    assert s.in_storm("u", NOW + 20)  # the 21st in the window is suppressed
    assert not s.in_storm("other", NOW + 20)  # per USER
    assert s.in_storm("u", NOW + 59_999)
    assert not s.in_storm("u", NOW + 60_000)  # oldest fell out of the window
    assert s.window_end("u", NOW + 60_000) == NOW + 1 + 60_000
    assert StormSuppressor().window_end("x", NOW) == NOW + 60_000
