"""tests/xstate_contract/test_e50_t43_round14.py — E50-T43 (#581): the four round-14 our-side fixes.

The fixes already live in the corrected machine JSON (catalogue "Corrected 2026-09-24");
these tests ASSERT them, only through `cv.statechart.factory.build` (C-2.19). No JSON,
binding or lock changes belong here.

R14-03 reading (written nowhere beyond the catalogue; docs/research/xstate/78 only names it):
the "Corrected" markers on B11 (§B11.5) say guards run against the PRE-action context
(XState v5 / SCXML), so `all_streams_healthy` / `reasons_remain` must be event-aware
("once this event is applied"), and `degraded` must handle `GAP_DETECTED`. Tests below
pin exactly those three behaviours on the real bindings.

B8 counter: bindings for B8 are still stubs (E32), so the counter arithmetic is supplied
test-locally (bump on `naked` entry, reset on `protected` entry, guard `attempts < N`) —
what is asserted is the CHART WIRING of `fallback_attempts_left` (INV-B8-f). There is no
`CV_B8_MAX_FALLBACK` constant in code yet; N is a test parameter.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from xstate_statemachine import SimulatedClock

import candleviewer.statechart.bindings.b11_recording as b11
import candleviewer.statechart.bindings.b16_session  # noqa: F401  (registers "session")
from candleviewer.statechart import build
from candleviewer.statechart.bindings import b08_position_protection as b08
from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import Charts, instrument, park, settle, walk

#: #2301: `IDLE_DEADLINE` is the idle LOCK (`auth.idle_locked`), no longer a revocation.
REVOCATION = ("LOGOUT", "ABSOLUTE_DEADLINE", "REVOKE")
B16 = Registry().get("session")
B18 = Registry().get("kill_switch")
B8 = Registry().get("position_protection")


async def _quiesce(n: int = 8) -> None:
    for _ in range(n):
        await settle()


# --------------------------------------------------------------------------- B16 (C-04)


def _b16_leaves() -> list[str]:
    """Every atomic/final state nested under a `session` region, from the JSON."""
    return [p for p, node in walk(B16) if "." in p and not node.get("states")]


def test_b16_c04_root_declares_every_revocation_event_to_dead() -> None:
    assert set(REVOCATION) <= set(B16["on"])
    assert {B16["on"][e]["target"] for e in REVOCATION} == {"#session.elevation.dead"}
    # The deeper region-level handler outranks the root arm (catalogue note): none may remain.
    for path, node in walk(B16):
        if path.startswith("elevation."):
            assert "REVOKE" not in node.get("on", {}), path


def test_b16_c04_enumeration_is_nonempty_and_covers_both_regions() -> None:
    leaves = _b16_leaves()
    assert {p.split(".")[0] for p in leaves} == {"auth", "elevation"}
    assert len(leaves) >= 7


@pytest.mark.parametrize("event", REVOCATION)
@pytest.mark.parametrize("leaf", _b16_leaves())
async def test_b16_c04_revocation_from_every_nested_state_reaches_dead(
    leaf: str, event: str, charts: Charts
) -> None:
    res = await park("session", B16, leaf, charts)
    interp = res.interpreter
    try:
        assert f"session.{leaf}" in interp.current_state_ids
        await interp.send(event, wait=True)
        await _quiesce()
        assert "session.elevation.dead" in interp.current_state_ids, (leaf, event)
        assert interp.deferred_count == 0, "revocation must not be deferred via onUnhandled"
        assert interp.error is None and interp.is_running
        # Dead session can never be re-elevated.
        if interp.can("STEP_UP_OK"):
            pytest.fail(f"STEP_UP_OK accepted after {event} from {leaf}")
    finally:
        await interp.stop()


@pytest.mark.parametrize("event", REVOCATION)
async def test_b16_c04_active_session_ends_revoked_and_dead(event: str, charts: Charts) -> None:
    res = await park("session", B16, "auth.active", charts)
    interp = res.interpreter
    try:
        await interp.send(event, wait=True)
        await _quiesce()
        assert "session.auth.revoked" in interp.current_state_ids
        assert "session.elevation.dead" in interp.current_state_ids
    finally:
        await interp.stop()


# --------------------------------------------------------------------------- B18 (C-07b)


async def test_b18_c07b_denied_release_audits_keeps_state_and_is_not_bricked(
    charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = {"owner_and_elevated": False}
    rec = instrument("kill_switch", monkeypatch, "async_def", guards=plan)
    assert B18["onUnhandled"] == "defer"
    res = await park("kill_switch", B18, "engaged", charts)
    interp = res.interpreter
    try:
        before = set(interp.current_state_ids)
        for n in (1, 2):  # repeated denial: still audited each time, never fatal
            await interp.send("RELEASE", wait=True)
            await _quiesce()
            assert set(interp.current_state_ids) == before
            assert rec.actions.count("audit_release_denied") == n
            assert "audit_kill_switch_released" not in rec.actions
            assert interp.deferred_count == 0
            assert interp.error is None and interp.is_running
        # Not bricked: an authorised RELEASE now succeeds, and ENGAGE works again.
        plan["owner_and_elevated"] = True
        await interp.send("RELEASE", wait=True)
        await _quiesce()
        assert "kill_switch.clear" in interp.current_state_ids
        assert rec.actions.count("audit_kill_switch_released") == 1
        await interp.send("ENGAGE", wait=True)
        await _quiesce()
        assert "kill_switch.clear" not in interp.current_state_ids
    finally:
        await interp.stop()


def test_b18_c07b_release_arms_are_ordered_guarded_then_unguarded_audit() -> None:
    for state in ("engaged", "engaged_incomplete"):
        arms = B18["states"][state]["on"]["RELEASE"]
        assert arms[0].get("guard") and arms[0]["target"] == "#kill_switch.clear"
        assert "guard" not in arms[-1] and arms[-1]["actions"] == ["audit_release_denied"]


# --------------------------------------------------------------------------- B11 (R14-03)


async def _b11(events: list[dict[str, Any]]) -> Any:
    interp = (await build("recording", clock=SimulatedClock(), lane="platform")).interpreter

    async def _hook(_name: str, _ctx: object) -> None:
        return None

    b11.attach_hook(interp, _hook)
    for ev in events:
        await interp.send(ev, wait=True)
        await _quiesce(16)
    return interp


def _leaf(interp: Any) -> str:
    return str(next(iter(interp.current_state_ids))).split(".")[1]


_ADD = {"type": "REASON_ADDED", "reason": "manual", "symbol": "BTCUSDT"}


async def test_b11_r14_03_degraded_recovers_on_last_unhealthy_stream_only() -> None:
    """Guard must see the stream this very event announces healthy."""
    interp = await _b11(
        [
            _ADD,
            {"type": "STREAM_UNHEALTHY", "stream": "trades"},
            {"type": "STREAM_UNHEALTHY", "stream": "book"},
            {"type": "STREAM_HEALTHY", "stream": "trades"},
        ]
    )
    try:
        assert _leaf(interp) == "degraded"  # book still unhealthy
        await interp.send({"type": "STREAM_HEALTHY", "stream": "book"}, wait=True)
        await _quiesce(16)
        assert _leaf(interp) == "recording"  # pre-fix this stayed degraded forever
        assert interp.chain_trips == 0
    finally:
        await interp.stop()


async def test_b11_r14_03_reason_removal_lingers_only_when_last_reason_goes() -> None:
    interp = await _b11(
        [_ADD, {**_ADD, "reason": "chart_open"}, {"type": "REASON_REMOVED", "reason": "manual"}]
    )
    try:
        assert _leaf(interp) == "recording" and interp.context["reasons"] == ["chart_open"]
        await interp.send({"type": "REASON_REMOVED", "reason": "chart_open"}, wait=True)
        await _quiesce(16)
        assert _leaf(interp) == "lingering" and interp.context["reasons"] == []
    finally:
        await interp.stop()


async def test_b11_r14_03_degraded_handles_gap_detected_in_place() -> None:
    interp = await _b11(
        [
            _ADD,
            {"type": "STREAM_UNHEALTHY", "stream": "trades"},
            {"type": "GAP_DETECTED", "stream": "trades"},
        ]
    )
    try:
        assert _leaf(interp) == "degraded" and interp.context["gap_count_24h"] == 1
        assert interp.deferred_count == 0 and interp.error is None
    finally:
        await interp.stop()


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    order=st.permutations(["trades", "book", "tickers"]),
    k=st.integers(min_value=1, max_value=3),
)
async def test_b11_r14_03_recovery_exactly_when_last_stream_heals(order: list[str], k: int) -> None:
    streams = order[:k]
    evs: list[dict[str, Any]] = [_ADD] + [
        {"type": "STREAM_UNHEALTHY", "stream": s} for s in streams
    ]
    interp = await _b11(evs)
    try:
        for i, s in enumerate(streams):
            assert _leaf(interp) == "degraded"
            await interp.send({"type": "STREAM_HEALTHY", "stream": s}, wait=True)
            await _quiesce(16)
            assert _leaf(interp) == ("recording" if i == len(streams) - 1 else "degraded")
    finally:
        await interp.stop()


# --------------------------------------------------------------------------- B8 (B610-OC-CD03)


async def _b8_run(n: int, heal_at: int | None, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Any]:
    """Drive POSITION_OPENED with a fallback attach that always succeeds. The exchange
    reports an SL only once `fallback_attempts >= heal_at` (None = never)."""

    async def _ok(*_a: object, **_k: object) -> dict[str, Any]:
        return {}

    def _left(ctx: dict[str, Any], _e: Any) -> bool:
        return int(ctx["fallback_attempts"]) < n

    def _reports(ctx: dict[str, Any], _e: Any) -> bool:
        return heal_at is not None and int(ctx["fallback_attempts"]) >= heal_at

    async def _bump(_i: Any, ctx: dict[str, Any], _e: Any, _a: Any) -> None:
        ctx["fallback_attempts"] = int(ctx["fallback_attempts"]) + 1

    async def _reset(_i: Any, ctx: dict[str, Any], _e: Any, _a: Any) -> None:
        ctx["fallback_attempts"] = 0

    rec = instrument(
        "position_protection",
        monkeypatch,
        "async_def",
        service_mode={
            "attach_native_sl": _ok,
            "read_position_sl": _ok,
            "attach_fallback_sl": _ok,
        },
    )
    monkeypatch.setitem(b08.GUARDS, "fallback_attempts_left", _left)
    monkeypatch.setitem(b08.GUARDS, "exchange_reports_sl", _reports)
    monkeypatch.setitem(b08.ACTIONS, "bump_fallback_attempts", _bump)
    monkeypatch.setitem(b08.ACTIONS, "reset_fallback_attempts", _reset)
    res = await build("position_protection", clock=SimulatedClock(), lane="platform")
    interp = res.interpreter
    await interp.send({"type": "POSITION_OPENED"}, wait=True)
    for _ in range(40):
        await settle()
    return interp, rec


def test_b08_chart_wires_fallback_counter() -> None:
    sl = B8["states"]["sl"]["states"]
    assert "bump_fallback_attempts" in sl["naked"]["entry"]
    assert "reset_fallback_attempts" in sl["protected"]["entry"]
    for arms in (sl["verifying"]["invoke"]["onDone"], sl["verifying"]["invoke"]["onError"]):
        assert any(a.get("guard") == "fallback_attempts_left" for a in arms)
        assert arms[-1]["target"] == "#position_protection.sl.naked_unrecoverable"


@settings(
    max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(n=st.integers(min_value=1, max_value=8))
async def test_b08_attempt_counter_exhaustion_pages_after_exactly_n_laps(n: int) -> None:
    with pytest.MonkeyPatch.context() as mp:
        interp, rec = await _b8_run(n, None, mp)
        try:
            assert "position_protection.sl.naked_unrecoverable" in interp.current_state_ids
            assert interp.context["fallback_attempts"] == n
            assert rec.actions.count("raise_critical_alert") == n
            assert rec.actions.count("page_owner") == 1
            assert interp.chain_trips == 0 and interp.error is None
        finally:
            await interp.stop()
            b08.clear_frozen_flags()


@settings(
    max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(n=st.integers(min_value=2, max_value=8))
async def test_b08_attempt_counter_boundary_n_minus_1_recovers(n: int) -> None:
    with pytest.MonkeyPatch.context() as mp:
        interp, rec = await _b8_run(n, n - 1, mp)
        try:
            assert "position_protection.sl.protected" in interp.current_state_ids
            assert interp.context["fallback_attempts"] == 0  # reset on protected entry
            assert rec.actions.count("page_owner") == 0
            assert interp.chain_trips == 0
        finally:
            await interp.stop()
            b08.clear_frozen_flags()


async def test_b08_attempt_counter_boundary_n_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    interp, _rec = await _b8_run(3, 3, monkeypatch)  # heals on the Nth (=3rd) attempt
    try:
        assert "position_protection.sl.protected" in interp.current_state_ids
    finally:
        await interp.stop()
    interp2, rec2 = await _b8_run(3, 4, monkeypatch)  # heal needs a 4th attempt: N=3 is out
    try:
        assert "position_protection.sl.naked_unrecoverable" in interp2.current_state_ids
        assert rec2.actions.count("page_owner") == 1
    finally:
        await interp2.stop()
