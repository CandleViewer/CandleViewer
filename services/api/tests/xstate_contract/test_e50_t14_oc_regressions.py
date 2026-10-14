"""tests/xstate_contract/test_e50_t14_oc_regressions.py — E50-T14 (#383): round-5 OC regressions.

Findings are defined in docs/research/xstate/33-r5-findings-register.md §6. Only fixes PRESENT
in the committed machine JSON are asserted green (OC-01/02/04/07/10, OC-09 narrowed). OC-03/05/06/08
landed in #2204 and their former strict xfails now run as regular tests. No machine JSON or
`machine_hashes.lock` change belongs in this file; everything runs through the factory (C-2.19).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import Charts, instrument, park, settle, walk
from tests.xstate_contract.conftest import _MACHINES

CHARTS: dict[str, dict[str, Any]] = {
    p.name.split(".")[0]: json.loads(p.read_text(encoding="utf-8"))
    for p in sorted(_MACHINES.glob("*.machine.json"))
}
B16 = Registry().get("session")


def _nodes(chart: dict[str, Any]) -> list[dict[str, Any]]:
    return [chart, *(n for _, n in walk(chart))]


def _arms(spec: Any) -> list[dict[str, Any]]:
    return [spec] if isinstance(spec, dict) else list(spec)


async def _quiesce(n: int = 8) -> None:
    for _ in range(n):
        await settle()


# ----------------------------------------------------------------------------- OC-01


def test_oc_01_chart_set_is_nonempty() -> None:
    assert len(CHARTS) >= 20


@pytest.mark.parametrize("bid", sorted(CHARTS))
def test_oc_01_no_catch_all_arm_anywhere(bid: str) -> None:
    """Fails if any `"*"` key is added to any `on` map (the A3 scaffolding), since it
    pre-empts `onUnhandled:"defer"` and disables `strict`."""
    for node in _nodes(CHARTS[bid]):
        assert "*" not in (node.get("on") or {}), bid
    assert CHARTS[bid]["onUnhandled"] == "defer" and CHARTS[bid]["strict"] is True


# ----------------------------------------------------------------------------- OC-02


def _raises_evaluate(arms: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(a, dict)
        and a.get("type") == "raise"
        and a["params"]["event"]["type"] == "EVALUATE"
        for arm in arms
        for a in arm.get("actions", [])
    )


def test_oc_02_submitting_progress_events_raise_evaluate() -> None:
    """Fails if `raise`->EVALUATE is replaced by a plain named action (OC-02 defect)."""
    on = CHARTS["B02"]["states"]["submitting"]["on"]
    for ev in ("LEG_OPEN", "LEG_FAILED", "LEG_SKIPPED", "QUIESCE_DEADLINE"):
        assert _raises_evaluate(_arms(on[ev])), ev
    assert "raise_evaluate" not in json.dumps(CHARTS["B02"])


async def test_oc_02_leg_open_runs_evaluate_guards(
    charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behavioural: the raised EVALUATE is consumed (its first guard is consulted) and an
    `all_or_none` failure unwinds. Fails if the raise is dropped."""
    plan = {"policy_all_or_none_and_any_failed": True}
    rec = instrument("trade_group", monkeypatch, "async_def", guards=plan)
    res = await park("trade_group", CHARTS["B02"], "submitting", charts)
    interp = res.interpreter
    try:
        await interp.send("LEG_OPEN", wait=True)
        await _quiesce()
        assert ("policy_all_or_none_and_any_failed", True) in rec.guards
        assert "trade_group.unwinding" in interp.current_state_ids
        assert interp.deferred_count == 0
    finally:
        await interp.stop()


# ----------------------------------------------------------------------------- OC-04


def test_oc_04_revocation_arms_on_root_and_active() -> None:
    """Fails if REVOKE/LOGOUT is removed from the B16 root or from `auth.active`."""
    for ev in ("REVOKE", "LOGOUT"):
        assert B16["on"][ev]["target"] == "#session.elevation.dead"
        assert B16["states"]["auth"]["states"]["active"]["on"][ev]["target"].endswith("revoked")


@pytest.mark.parametrize("event", ["REVOKE", "LOGOUT"])
async def test_oc_04_elevated_session_revoked_not_reacquirable(event: str, charts: Charts) -> None:
    """Fails if the elevation region ignores revocation (elevation survives, deferred)."""
    res = await park("session", B16, "elevation.elevated", charts)
    interp = res.interpreter
    try:
        await interp.send(event, wait=True)
        await _quiesce()
        assert "session.elevation.dead" in interp.current_state_ids
        assert interp.deferred_count == 0
        await interp.send("STEP_UP_OK", wait=True)  # cannot be re-acquired after revocation
        await _quiesce()
        assert "session.elevation.dead" in interp.current_state_ids
        assert "session.elevation.elevated" not in interp.current_state_ids
    finally:
        await interp.stop()


# ----------------------------------------------------------------------------- OC-07


@pytest.mark.parametrize("bid", sorted(CHARTS))
def test_oc_07_action_error_policy_is_rollback(bid: str) -> None:
    """Fails if any chart reverts to `actionErrorPolicy:"fail"` (does not halt on this library)."""
    assert CHARTS[bid]["actionErrorPolicy"] == "rollback"


# ----------------------------------------------------------------------------- OC-10


def test_oc_10_both_step_up_ok_arms_audit() -> None:
    """Fails if `audit_step_up` is dropped from either the first-grant or the re-entry arm."""
    states = B16["states"]["elevation"]["states"]
    for src in ("normal", "elevated"):
        grant = next(a for a in _arms(states[src]["on"]["STEP_UP_OK"]) if a.get("target"))
        assert "audit_step_up" in grant["actions"], src


async def test_oc_10_step_up_while_elevated_writes_audit(
    charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behavioural twin; fails if the re-entry arm omits the audit action."""
    rec = instrument("session", monkeypatch, "async_def")
    res = await park("session", B16, "elevation.elevated", charts)
    interp = res.interpreter
    try:
        await interp.send("STEP_UP_OK", wait=True)
        await _quiesce()
        assert rec.actions.count("audit_step_up") == 1
        assert "session.elevation.elevated" in interp.current_state_ids
    finally:
        await interp.stop()


# ----------------------------------------------------------------------------- OC-09 (narrowed)
# B08 has no `stateIn` guard by design (enforceable form is temporal, INV-B8-f). Only the
# chart guarantee is asserted: while `naked`/`verifying`, no SL amend can run.


def test_oc_09_only_protected_can_enter_amending() -> None:
    """Fails if any state other than `protected` gains an arm targeting `amending`."""
    sl = CHARTS["B08"]["states"]["sl"]["states"]
    for name, node in sl.items():
        targets = {a.get("target") for spec in (node.get("on") or {}).values() for a in _arms(spec)}
        if name != "protected":
            assert "#position_protection.sl.amending" not in targets, name
    assert "TIGHTEN_SL" not in sl["naked"].get("on", {})
    assert "TIGHTEN_SL" not in sl["verifying"].get("on", {})


@pytest.mark.parametrize("leaf", ["sl.naked", "sl.verifying"])
@pytest.mark.parametrize("event", ["TIGHTEN_SL", "LOOSEN_SL"])
async def test_oc_09_no_sl_amend_while_naked_or_verifying(
    leaf: str, event: str, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails if an amend arm is added to naked/verifying (set_trading_stop would be invoked)."""
    calls: list[str] = []

    async def _amend(*_a: object, **_k: object) -> dict[str, Any]:
        calls.append("set_trading_stop")
        return {}

    # Permissive guards: even so, no amend may run from these states.
    guards = {g: True for g in ("tightens_only", "explicit_audited_override")}
    rec = instrument(
        "position_protection",
        monkeypatch,
        "async_def",
        guards=guards,
        service_mode={"set_trading_stop": _amend},
    )
    res = await park("position_protection", CHARTS["B08"], leaf, charts)
    interp = res.interpreter
    try:
        await interp.send(event, wait=True)
        await _quiesce()
        assert calls == []
        assert "position_protection.sl.amending" not in interp.current_state_ids
        assert "audit_amend_refused_frozen" not in rec.actions
    finally:
        await interp.stop()


# ----------------------------------------------------------------------------- #2204 fixes
# OC-03/05/06/08 landed in #2204 (catalogue *Corrected 2026-10-10*); the former strict
# xfails are now regular tests. Behavioural traces: test_e50_t14b_round5_fixes.py.


def test_oc_03_b04_completing_absorbs_late_leg_fills() -> None:
    on = CHARTS["B04"]["states"]["completing"]["on"]
    assert {"LEG_A_FILL", "LEG_B_FILL"} <= set(on)


def test_oc_05_b19_stale_lockout_handles_operator_resolved() -> None:
    assert "OPERATOR_RESOLVED" in CHARTS["B19"]["states"]["stale_lockout"]["on"]


def test_oc_06_b11_degraded_handles_stream_unhealthy() -> None:
    assert "STREAM_UNHEALTHY" in CHARTS["B11"]["states"]["degraded"]["on"]


def test_oc_08_b14_delta_buffer_is_bounded() -> None:
    text = json.dumps(CHARTS["B14"]).lower()
    assert any(k in text for k in ("max_buffered", "buffer_bound", "buffer_limit", "overflow"))
