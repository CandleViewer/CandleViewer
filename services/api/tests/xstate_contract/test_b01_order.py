"""tests/xstate_contract/test_b01_order.py — B1 `order` contract module (#1650).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B1.3 arm (both service spellings) and the persist→restore round-trip run
from the generated suites (`test_contract_transitions.py`,
`test_contract_persistence.py`). This module pins the §B1.7 ledger and adds the
golden traces for the *Corrected 2026-10-09* KILL arm (owner decision #1778
item X, option a): root `KILL` → final `killed`, `halted_by_kill` set, exactly
one exchange cancel and one audit, `protection` region untouched.
#847 slice 1 adds a golden trace per new arm and a property per new invariant (B1 version 1).
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.config import CV_EVENT_SCHEMAS
from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import (
    Charts,
    all_events,
    entry_of,
    exits,
    instrument,
    is_terminal,
    node_at,
    park,
    service_for,
    settle,
    transition_cases,
    walk,
)
from tests.xstate_contract.membership import _CATALOGUE, check_ledger

CHART = Registry().get("order")
TERMINALS = ("filled", "cancelled", "rejected", "expired", "killed")
LIVE = tuple(
    p.split(".", 1)[1]
    for p, _n in walk(CHART)
    if p.startswith("lifecycle.") and p.split(".", 1)[1] not in TERMINALS
)
_REAL_KILL_ACTIONS = ("mark_halted_by_kill", "issue_kill_cancel", "skip_kill_cancel")
_UNSUBMITTED = ("draft", "validated")
_SL_ACTIONS = {"request_fallback_sl", "arm_sl_deadline", "raise_naked_position_alert"}
#: #847 slice 1: orders the OMS does not own (G-3); states where the order is live on the exchange.
_UNOWNED = ("untracked", "held")
_EXCHANGE_LIVE = ("submitted", "triggered", "partially_filled", "cancel_pending", "amend_pending")

INVARIANTS: dict[str, str] = {
    "INV-B1-a": "deferred:E29",  # #847 slice 4: apply_fill bodies, cum_exec_value and fee_paid
    "INV-B1-b": "deferred:E29",  # #847 slice 4: exec_id dedupe in apply_fill
    "INV-B1-c": "test_inv_b1_c_amend_rejected_never_terminal",
    "INV-B1-d": "test_inv_b1_d_cancel_pending_handles_exec",
    "INV-B1-e": "test_inv_b1_e_unknown_resolved_only_by_recon",
    "INV-B1-f": "test_inv_b1_f_sl_present_only_from_exchange_read",
    "INV-B1-g": "deferred:E29",  # #847 slice 5: persist_event writes ahead through slice 3
    "INV-B1-h": "test_inv_b1_h_kill_at_most_one_cancel_only_if_submitted",
    "INV-B1-i": "test_inv_b1_i_kill_never_touches_protection_property",
    "INV-B1-j": "test_inv_b1_j_result_adopted_only_if_ret_code_ok_property",
    "INV-B1-k": "test_inv_b1_k_exchange_end_is_never_stranded_property",
    "INV-B1-l": "test_inv_b1_l_untracked_is_never_managed_property",
    "INV-B1-m": "test_inv_b1_m_held_is_left_only_by_the_operator_property",
    "INV-B1-n": "test_inv_b1_n_kill_never_cancels_an_unowned_order_property",
}


def test_b01_invariant_ledger_matches_catalogue() -> None:
    check_ledger(1, INVARIANTS, globals())


def test_inv_b1_c_amend_rejected_never_terminal() -> None:
    out = [t for e, _g, t in exits(CHART, "lifecycle.amend_pending") if e == "AMEND_REJECTED"]
    assert out and all(t is not None and t.rsplit(".", 1)[-1] not in TERMINALS for t in out)
    for arm in node_at(CHART, "lifecycle.amend_pending")["invoke"]["onDone"]:  # #847 ruling 3
        assert ("adopt_amend" in arm["actions"]) == arm.get("guard", "").startswith("ret_code_ok")
        assert arm["target"].rsplit(".", 1)[-1] in ("submitted", "partially_filled")


def test_inv_b1_d_cancel_pending_handles_exec() -> None:
    assert "EXEC" in node_at(CHART, "lifecycle.cancel_pending")["on"]


def test_inv_b1_e_unknown_resolved_only_by_recon() -> None:
    leaving = {(e, t) for e, _g, t in exits(CHART, "lifecycle.unknown") if e[:6] != "RECON_"}
    assert leaving == {("MISMATCH", "order.lifecycle.held")}  # #847: never SEND, never adopt


def test_inv_b1_f_sl_present_only_from_exchange_read() -> None:
    into = [
        (p, e)
        for p, _n in walk(CHART)
        if p.startswith("protection.")
        for e, _g, t in exits(CHART, p)
        if t == "order.protection.sl_present"
    ]
    assert ("protection.sl_missing", "SL_OBSERVED") in into


def test_b01_killed_is_final_terminal_with_cancel_and_audit() -> None:
    assert node_at(CHART, "lifecycle.killed")["type"] == "final"
    assert is_terminal(CHART, "lifecycle.killed")
    entry = entry_of(CHART, "lifecycle.killed")
    for name in ("mark_halted_by_kill", "issue_kill_cancel", "audit_kill"):
        assert entry.count(name) == 1
    assert CHART["context"]["halted_by_kill"] is False


def _restore_real(monkeypatch: pytest.MonkeyPatch, *, hang: bool = False) -> list[str]:
    """Real KILL actions; `cancel_order` records each call (and hangs if *hang*,
    to keep a parked `cancel_pending` invoke in flight)."""
    cancels: list[str] = []

    async def _cancel(*_a: object, **_k: object) -> None:
        cancels.append("cancel_order")
        if hang:
            await asyncio.Event().wait()

    for name in _REAL_KILL_ACTIONS:
        monkeypatch.setitem(b01.ACTIONS, name, getattr(b01, name))
    monkeypatch.setitem(b01.SERVICES, "cancel_order", _cancel)
    return cancels


@pytest.mark.parametrize("state", LIVE)
async def test_inv_b1_h_kill_at_most_one_cancel_only_if_submitted(
    state: str, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = instrument("order", monkeypatch, "async_def")
    in_flight = state == "cancel_pending"
    cancels = _restore_real(monkeypatch, hang=in_flight)
    res = await park("order", CHART, f"lifecycle.{state}", charts)
    interp = res.interpreter
    try:
        await settle()
        before = len(cancels)  # 1 for the parked cancel_pending invoke, else 0
        await interp.send("KILL", wait=True)
        await settle()
        assert interp.error is None
        if state in _UNOWNED:  # INV-B1-n: audit only; nothing halted, nothing cancelled
            assert f"order.lifecycle.{state}" in interp.current_state_ids and cancels == []
            assert rec.actions.count("audit_kill_ignored_unowned") == 1
            assert interp.context["halted_by_kill"] is False
            return
        assert interp.context["halted_by_kill"] is True
        if in_flight:  # reuse the in-flight cancel: no second call
            assert before == 1 and len(cancels) == 1
            assert "order.lifecycle.cancel_pending" in interp.current_state_ids
            assert rec.actions.count("audit_kill_cancel_in_flight") == 1
            return
        assert "order.lifecycle.killed" in interp.current_state_ids
        assert rec.actions.count("audit_kill") == 1
        assert len(cancels) == (0 if state in _UNSUBMITTED else 1)
        assert rec.actions.index("audit_kill") < rec.actions.index("emit_terminal")
    finally:
        await interp.stop()


async def test_b01_kill_audit_is_write_ahead_of_cancel(
    charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = instrument("order", monkeypatch, "async_def")
    _restore_real(monkeypatch)
    order: list[str] = []

    async def _audit(*_a: object, **_k: object) -> None:
        order.append("audit_kill")

    async def _cancel(*_a: object, **_k: object) -> None:
        order.append("cancel_order")

    monkeypatch.setitem(b01.ACTIONS, "audit_kill", _audit)
    monkeypatch.setitem(b01.SERVICES, "cancel_order", _cancel)
    res = await park("order", CHART, "lifecycle.submitted", charts)
    try:
        await res.interpreter.send("KILL", wait=True)
        await settle()
        assert order == ["audit_kill", "cancel_order"]
        assert rec.actions.count("emit_terminal") == 1
    finally:
        await res.interpreter.stop()


@pytest.mark.parametrize("exc", [TimeoutError(), RuntimeError("exchange down")])
async def test_b01_kill_cancel_timeout_or_failure_is_audited(
    exc: BaseException, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`asyncio.timeout` raises TimeoutError at the await; simulated directly so no
    wall clock is involved (C-13.7). The kill proceeds either way."""
    instrument("order", monkeypatch, "async_def")
    _restore_real(monkeypatch)
    seen: list[str] = []

    async def _boom(*_a: object, **_k: object) -> None:
        raise exc

    async def _hook(name: str, _ctx: dict[str, object]) -> None:
        seen.append(name)

    monkeypatch.setitem(b01.SERVICES, "cancel_order", _boom)
    b01.set_audit_hook(_hook)
    try:
        res = await park("order", CHART, "lifecycle.submitted", charts)
        await res.interpreter.send("KILL", wait=True)
        await settle()
        assert "order.lifecycle.killed" in res.interpreter.current_state_ids
        want = "kill_cancel_timeout" if isinstance(exc, TimeoutError) else "kill_cancel_failed"
        assert seen == [want]
        await res.interpreter.stop()
    finally:
        b01.set_audit_hook(None)


async def test_b01_kill_cancel_uses_config_timeout() -> None:
    import inspect

    from candleviewer.statechart.config import CV_KILL_CANCEL_TIMEOUT

    assert CV_KILL_CANCEL_TIMEOUT > 0
    assert "asyncio.timeout(CV_KILL_CANCEL_TIMEOUT)" in inspect.getsource(b01.issue_kill_cancel)


@pytest.mark.parametrize("state", TERMINALS)
async def test_b01_kill_on_terminal_only_audits(
    state: str, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    rec = instrument("order", monkeypatch, "async_def")
    res = await park("order", CHART, f"lifecycle.{state}", charts)
    try:
        rec.actions.clear()
        await res.interpreter.send("KILL", wait=True)
        await settle()
        assert f"order.lifecycle.{state}" in res.interpreter.current_state_ids
        assert sorted(rec.actions) == [
            "audit_kill_ignored_terminal",
            "audit_kill_protection_retained",
        ]
    finally:
        await res.interpreter.stop()


_PROTECTION = ("not_required", "sl_pending", "sl_present", "sl_missing")
_EVENTS = sorted(all_events(CHART))


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(prot=st.sampled_from(_PROTECTION), events=st.lists(st.sampled_from(_EVENTS), max_size=6))
async def test_inv_b1_i_kill_never_touches_protection_property(
    prot: str, events: list[str], charts: Charts
) -> None:
    """Whatever came before, a KILL leaves the protection leaf as it found it and
    runs no SL action (C-2.6, C-4.14)."""
    with pytest.MonkeyPatch.context() as mp:
        rec = instrument("order", mp, "async_def")
        _restore_real(mp)
        res = await park("order", CHART, f"protection.{prot}", charts)
        interp = res.interpreter
        try:
            for ev in events:
                if ev != "KILL":
                    await interp.send(ev, wait=True)
            await settle()
            before = {s for s in interp.current_state_ids if ".protection." in s}
            mark = len(rec.actions)
            await interp.send("KILL", wait=True)
            await settle()
            after = {s for s in interp.current_state_ids if ".protection." in s}
            assert after == before
            assert not _SL_ACTIONS & set(rec.actions[mark:])
            assert "audit_kill_protection_retained" in rec.actions[mark:]
        finally:
            await interp.stop()


# --- #847 slice 1: G-3 (`untracked`, `held`) and exchange outcomes, chart version 1 -----------

_HYP = settings(
    max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
_KEEP = ("keep_prior_order_live", "notify_amend_rejected")
_PROT = "audit_kill_protection_retained"
_RC = "adopt_remote_cancel"
#: New or re-guarded arm (generated-suite id less `order:lifecycle.`) -> (leaf, *arm actions).
_NEW_ARMS: dict[str, tuple[str, ...]] = {
    "draft:on:DISCOVERED[0]": ("untracked", "record_discovered"),
    "submitting:onDone:onDone[1]": ("held", "record_mismatch"),
    "submitted:on:REMOTE_CANCELLED[0]": ("cancelled", _RC),
    "submitted:on:MISMATCH[0]": ("held", "record_mismatch"),
    "triggered:on:EXPIRE[0]": ("expired",),
    "triggered:on:REMOTE_CANCELLED[0]": ("cancelled", _RC),
    "partially_filled:on:EXPIRE[0]": ("expired",),
    "partially_filled:on:REMOTE_CANCELLED[0]": ("cancelled", _RC),
    "cancel_pending:onDone:onDone[0]": ("cancelled", "adopt_cancel_ack"),
    "cancel_pending:onDone:onDone[1]": ("partially_filled", "record_cancel_refused"),
    "cancel_pending:onDone:onDone[2]": ("submitted", "record_cancel_refused"),
    "cancel_pending:on:REMOTE_CANCELLED[0]": ("cancelled", _RC),
    "amend_pending:onDone:onDone[0]": ("partially_filled", "adopt_amend"),
    "amend_pending:onDone:onDone[1]": ("submitted", "adopt_amend"),
    "amend_pending:onDone:onDone[2]": ("partially_filled", *_KEEP),
    "amend_pending:onDone:onDone[3]": ("submitted", *_KEEP),
    "amend_pending:on:REMOTE_CANCELLED[0]": ("cancelled", _RC),
    "unknown:on:MISMATCH[0]": ("held", "record_mismatch"),
    "quarantined:on:RECON_FOUND_CANCELLED[0]": ("cancelled", "adopt_recon"),
    "untracked:on:ADOPT[0]": ("submitted", "adopt_untracked"),
    "untracked:on:ADOPT[1]": ("untracked", "audit_adoption_denied"),
    "untracked:on:RECON_FOUND_CANCELLED[0]": ("cancelled", "adopt_recon"),
    "untracked:on:RECON_MISS[0]": ("cancelled", "set_cancel_missing_remote"),
    "untracked:on:RECON_MISS[1]": ("untracked", "bump_recon_misses"),
    "untracked:on:KILL[0]": ("untracked", "audit_kill_ignored_unowned", _PROT),
    "held:on:OPERATOR_RESOLVED[0]": ("rejected", "audit_operator_resolved"),
    "held:on:KILL[0]": ("held", "audit_kill_ignored_unowned", _PROT),
}
_CASES = {c.id.removeprefix("order:lifecycle."): c for c in transition_cases("order", CHART)}
#: Lifecycle actions that act on, bind or adopt an order (INV-B1-l, INV-B1-m).
_MANAGING = frozenset(
    "adopt_ack adopt_amend adopt_cancel_ack adopt_recon adopt_untracked apply_fill"
    " issue_kill_cancel mark_needs_lookup reserve_rate_token stamp_validated".split()
)
_UNTRACKED_EXITS = {("cancelled", "RECON_FOUND_CANCELLED"), ("cancelled", "RECON_MISS")}


def _into(state: str) -> set[tuple[str, str]]:
    return {(p, e) for p, _n in walk(CHART) for e, _g, t in exits(CHART, p) if t == state}


def _leaf(interp: Any) -> str:
    return str(next(s for s in interp.current_state_ids if s.startswith("order.lifecycle.")))[16:]


async def _result(*_a: object, **_k: object) -> dict[str, Any]:
    return {}  # the forced guards decide the outcome (ret_code_ok False = a business reject)


def test_b01_catalogue_contract_matches_machine_json() -> None:
    """C-2.19: catalogue B1.1 is the machine JSON minus the keys no entry repeats."""
    text = _CATALOGUE.read_text(encoding="utf-8")
    block = re.search(r"### B1\.1 Contract \(normative\)\s*```json\n(.*?)\n```", text, re.S)
    assert block is not None and CHART["version"] == 1
    skip = ("version", "strictConfig", "maxIterations")
    assert json.loads(block.group(1)) == {k: v for k, v in CHART.items() if k not in skip}


@pytest.mark.parametrize("arm", sorted(_NEW_ARMS))
async def test_b01_new_arm_golden_trace(
    arm: str, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The arm reaches its leaf and runs its own actions, then the target's entry."""
    case = _CASES[arm]
    rec = instrument(
        "order", monkeypatch, "async_def", guards=case.guards, service_mode=service_for(case)
    )
    res = await park("order", CHART, case.source, charts)
    try:
        if case.kind == "on":
            await res.interpreter.send(case.event, wait=True)
        await settle()
        leaf, *actions = _NEW_ARMS[arm]
        entered = entry_of(CHART, f"lifecycle.{leaf}") if case.target else []
        assert _leaf(res.interpreter) == leaf and res.interpreter.error is None
        assert rec.actions == [*entry_of(CHART, case.source), *actions, *entered]
    finally:
        await res.interpreter.stop()


@pytest.mark.parametrize("fills", [False, True])
async def test_b01_amend_business_reject_never_runs_adopt_amend(
    fills: bool, charts: Charts, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression (#847 ruling 3): the `amend` result had no return-code guard, so a business
    reject ran `adopt_amend` and a stop looked moved that the exchange never moved (S2)."""
    plan = {"has_fills": fills}  # ret_code_ok denied: the exchange rejected the amend
    rec = instrument(
        "order", monkeypatch, "async_def", guards=plan, service_mode={"amend_order": _result}
    )
    res = await park("order", CHART, "lifecycle.amend_pending", charts)
    try:
        await settle()
        assert "adopt_amend" not in rec.actions and rec.actions[1:3] == list(_KEEP)
        assert _leaf(res.interpreter) == ("partially_filled" if fills else "submitted")
    finally:
        await res.interpreter.stop()


async def test_b01_binding_stubs_and_event_schemas() -> None:
    assert all_events(CHART) <= set(CV_EVENT_SCHEMAS)  # every B1 event has a registered schema
    new = ("adoption_allowed", "is_link_id_mismatch", "ret_code_ok_and_has_fills")
    assert not any(b01.GUARDS[g]() for g in new)  # deny until #847 slice 4 (A6)
    await b01.ACTIONS[_RC]()  # the stub bodies run and return nothing
    assert await b01.SERVICES["place_order"]() is None
    seen: list[str] = []

    async def _hook(name: str, _ctx: dict[str, Any]) -> None:
        seen.append(name)

    names = "audit_kill audit_kill_cancel_in_flight audit_kill_ignored_terminal"
    b01.set_audit_hook(_hook)
    try:
        for name in f"{names} audit_kill_protection_retained audit_guard_denied".split():
            await getattr(b01, name)(None, {}, None, None)
    finally:
        b01.set_audit_hook(None)
    want = "halted_by_kill kill_cancel_in_flight kill_ignored_terminal kill_protection_retained"
    assert seen == [*want.split(), "guard_denied"]


_RESULTS = {  # invoking state -> (service, adopting action, refusing action)
    "cancel_pending": ("cancel_order", "adopt_cancel_ack", "record_cancel_refused"),
    "amend_pending": ("amend_order", "adopt_amend", "keep_prior_order_live"),
}


@_HYP
@given(state=st.sampled_from(sorted(_RESULTS)), ok=st.booleans(), fills=st.booleans())
async def test_inv_b1_j_result_adopted_only_if_ret_code_ok_property(
    state: str, ok: bool, fills: bool, charts: Charts
) -> None:
    """Adopted only if `ret_code_ok`, else back to the live state (INV-B1-j; INV-B1-c's half)."""
    src, adopt, refuse = _RESULTS[state]
    plan = {"ret_code_ok": ok, "has_fills": fills, "ret_code_ok_and_has_fills": ok and fills}
    with pytest.MonkeyPatch.context() as mp:
        rec = instrument("order", mp, "async_def", guards=plan, service_mode={src: _result})
        res = await park("order", CHART, f"lifecycle.{state}", charts)
        try:
            await settle()
            live = "partially_filled" if fills else "submitted"
            assert _leaf(res.interpreter) == ("cancelled" if ok and src == "cancel_order" else live)
            assert (adopt in rec.actions) is ok and (refuse in rec.actions) is not ok
        finally:
            await res.interpreter.stop()


#: INV-B1-k: an end the exchange reports without a fill -> (states that honour it, terminal).
_ENDS: dict[str, tuple[tuple[str, ...], str]] = {
    "REMOTE_CANCELLED": (_EXCHANGE_LIVE, "cancelled"),
    "EXPIRE": (("submitted", "triggered", "partially_filled"), "expired"),
    "RECON_FOUND_CANCELLED": (("unknown", "quarantined", "untracked"), "cancelled"),
}


@_HYP
@given(
    start=st.sampled_from(_EXCHANGE_LIVE),
    events=st.lists(st.sampled_from(_EVENTS), max_size=4),
    end=st.sampled_from(sorted(_ENDS)),
)
async def test_inv_b1_k_exchange_end_is_never_stranded_property(
    start: str, events: list[str], end: str, charts: Charts
) -> None:
    """Whatever came before, a state that honours the exchange's end reaches the terminal."""
    with pytest.MonkeyPatch.context() as mp:
        instrument("order", mp, "async_def")
        res = await park("order", CHART, f"lifecycle.{start}", charts)
        try:
            for ev in [*events, end]:
                before = _leaf(res.interpreter)
                await res.interpreter.send(ev, wait=True)
                await settle()
            states, terminal = _ENDS[end]
            assert before not in states or _leaf(res.interpreter) == terminal
        finally:
            await res.interpreter.stop()


@_HYP
@given(events=st.lists(st.sampled_from(_EVENTS), max_size=8), miss=st.booleans())
async def test_inv_b1_l_untracked_is_never_managed_property(
    events: list[str], miss: bool, charts: Charts
) -> None:
    """Adoption denied (until D6): it stays or ends cancelled by reconciliation, unmanaged."""
    assert _into("order.lifecycle.untracked") == {("lifecycle.draft", "DISCOVERED")}
    with pytest.MonkeyPatch.context() as mp:
        rec = instrument("order", mp, "async_def", guards={"second_consecutive_miss": miss})
        res = await park("order", CHART, "lifecycle.untracked", charts)
        try:
            for ev in events:
                before = _leaf(res.interpreter)
                await res.interpreter.send(ev, wait=True)
                await settle()
                moved = (before, _leaf(res.interpreter), ev)
                assert moved[0] == moved[1] or moved[1:] in _UNTRACKED_EXITS
            assert not (_MANAGING - {"adopt_recon"}) & set(rec.actions)
        finally:
            await res.interpreter.stop()


@_HYP
@given(
    events=st.lists(st.sampled_from([e for e in _EVENTS if e != "OPERATOR_RESOLVED"]), max_size=8)
)
async def test_inv_b1_m_held_is_left_only_by_the_operator_property(
    events: list[str], charts: Charts
) -> None:
    """Every guard allowed: only the operator's OPERATOR_RESOLVED moves it (to rejected)."""
    sources = {"lifecycle.submitting", "lifecycle.submitted", "lifecycle.unknown"}
    assert {p for p, _e in _into("order.lifecycle.held")} == sources
    with pytest.MonkeyPatch.context() as mp:
        rec = instrument("order", mp, "async_def", guards=dict.fromkeys(b01.GUARDS, True))
        res = await park("order", CHART, "lifecycle.held", charts)
        try:
            for ev in [*events, "OPERATOR_RESOLVED"]:
                assert _leaf(res.interpreter) == "held"
                await res.interpreter.send(ev, wait=True)
                await settle()
            assert _leaf(res.interpreter) == "rejected" and not _MANAGING & set(rec.actions)
        finally:
            await res.interpreter.stop()


@_HYP
@given(state=st.sampled_from(_UNOWNED), events=st.lists(st.sampled_from(_EVENTS), max_size=5))
async def test_inv_b1_n_kill_never_cancels_an_unowned_order_property(
    state: str, events: list[str], charts: Charts
) -> None:
    """Whatever came before, a KILL on an untracked or held order only audits (SR-E29-06)."""
    with pytest.MonkeyPatch.context() as mp:
        rec = instrument("order", mp, "async_def")
        cancels = _restore_real(mp)
        res = await park("order", CHART, f"lifecycle.{state}", charts)
        try:
            for ev in [e for e in events if e != "KILL"]:
                await res.interpreter.send(ev, wait=True)
            await settle()
            before, mark = _leaf(res.interpreter), len(rec.actions)
            await res.interpreter.send("KILL", wait=True)
            await settle()
            if before in _UNOWNED:
                assert _leaf(res.interpreter) == before and cancels == []
                assert rec.actions[mark:] == ["audit_kill_ignored_unowned", _PROT]
                assert res.interpreter.context["halted_by_kill"] is False
        finally:
            await res.interpreter.stop()
