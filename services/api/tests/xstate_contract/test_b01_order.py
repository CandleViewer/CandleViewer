"""tests/xstate_contract/test_b01_order.py — B1 `order` contract module (#1650).

Membership module of the blocking gate (29-statechart-adoption-plan.md §1.7).
Every §B1.3 arm (both service spellings) and the persist→restore round-trip run
from the generated suites (`test_contract_transitions.py`,
`test_contract_persistence.py`). This module pins the §B1.7 ledger and adds the
golden traces for the *Corrected 2026-10-09* KILL arm (owner decision #1778
item X, option a): root `KILL` → final `killed`, `halted_by_kill` set, exactly
one exchange cancel and one audit, `protection` region untouched.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from hypothesis import HealthCheck, example, given, settings
from hypothesis import strategies as st

from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.config import CV_EVENT_SCHEMAS
from candleviewer.statechart.registry import Registry
from tests.xstate_contract._harness import (
    Charts,
    _done,
    _fail,
    all_events,
    entry_of,
    exits,
    instrument,
    is_terminal,
    node_at,
    park,
    settle,
    walk,
)
from tests.xstate_contract.b01_ports import Commands
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
_UNOWNED = ("untracked", "held")
_EXCHANGE_LIVE = ("submitted", "triggered", "partially_filled", "cancel_pending", "amend_pending")


def _names(node: Any) -> set[str]:
    """Every action, guard and service name the chart JSON names (C-2.19)."""
    if isinstance(node, list):
        return set().union(*map(_names, node)) if node else set()
    if not isinstance(node, dict):
        return set()
    out = {str(node[k]) for k in ("guard", "src") if k in node}
    for key in ("actions", "entry", "exit"):
        out |= {a for a in node.get(key) or () if isinstance(a, str)}
    return out.union(*(_names(v) for k, v in node.items() if k != "context"))


_NAMED = _names(CHART)

INVARIANTS: dict[str, str | tuple[str, ...]] = {
    "INV-B1-a": "test_b01_order_core.py::test_inv_b1_a_fills_in_any_order_give_the_same_totals",
    "INV-B1-b": "test_b01_order_core.py::test_duplicate_fill_never_double_counts",
    "INV-B1-c": "test_inv_b1_c_amend_rejected_never_terminal",
    "INV-B1-d": "test_inv_b1_d_cancel_pending_handles_exec",
    "INV-B1-e": "test_inv_b1_e_unknown_resolved_only_by_recon",
    "INV-B1-f": "test_inv_b1_f_sl_present_only_from_the_exchange_property",
    "INV-B1-g": "test_b01_order_effects.py::test_inv_b1_g_every_step_is_written_before_it_is_seen",
    "INV-B1-h": (
        "test_inv_b1_h_kill_at_most_one_cancel_only_if_submitted",
        "test_b01_order_core.py::test_inv_b1_h_kill_cancels_a_reconciled_duplicate",
        "test_b01_order_core.py::test_inv_b1_h_kill_cancels_nothing_under_an_unverified_duplicate",
        "test_b01_order_recorded_stop.py::test_kill_spares_a_recorded_stop_in_each_live_state",
    ),
    "INV-B1-i": (
        "test_inv_b1_i_kill_never_touches_protection_property",
        "test_b01_order_recorded_stop.py::test_kill_spares_a_materialised_stop_which_still_takes_its_fills",
    ),
    "INV-B1-j": "test_inv_b1_j_result_adopted_only_if_ret_code_ok_property",
    "INV-B1-k": "test_inv_b1_k_exchange_end_is_never_stranded_property",
    "INV-B1-l": "test_inv_b1_l_untracked_is_never_managed_property",
    "INV-B1-m": (
        "test_inv_b1_m_held_is_left_only_by_the_operator_property",
        "test_inv_b1_m_a_stray_operator_command_is_refused_never_kept",
    ),
    "INV-B1-n": "test_inv_b1_n_kill_never_cancels_an_unowned_order_property",
    "INV-B1-o": (
        "test_inv_b1_o_every_arm_into_a_filled_state_raises_the_notice",
        "test_inv_b1_o_a_fill_reaching_a_final_or_held_order_is_an_audited_anomaly",
    ),
    "INV-B1-p": (
        "test_b01_order_recorded_stop.py::test_inv_b1_p_a_recorded_stop_is_never_killed_and_keeps_every_fill_property",
        "test_b01_order_recorded_stop.py::test_the_entry_is_taken_only_in_draft_and_invokes_no_service",
        "test_b01_order_recorded_stop.py::test_a_materialised_stop_is_written_submitted_and_bound_with_nothing_sent",
        "test_b01_order_recorded_stop.py::test_a_recorded_stops_fills_are_committed_as_a_live_rows",
        "test_b01_order_recorded_stop.py::test_kill_meets_the_guarded_arm_first_in_every_live_state_the_row_reaches",
        "test_b01_order_recorded_stop.py::test_a_cancel_reaches_a_recorded_stop_only_through_the_cancel_service",
        "test_b01_order_recorded_stop.py::test_a_recorded_stop_replays_from_its_first_row",
    ),
}


def test_b01_invariant_ledger_matches_catalogue() -> None:
    check_ledger(1, INVARIANTS, globals())
    deferred = [inv for inv, where in INVARIANTS.items() if "deferred:" in str(where)]
    assert deferred == []  # #847: no B1 invariant waits for a later epic's bindings
    text = _CATALOGUE.read_text(encoding="utf-8")  # C-2.19: B1.1 is the chart, root keys aside
    block = re.search(r"### B1\.1 Contract \(normative\)\s*```json\n(.*?)\n```", text, re.S)
    skip = ("version", "strictConfig", "maxIterations")
    assert block and json.loads(block[1]) == {k: v for k, v in CHART.items() if k not in skip}


def _edges(chart: dict[str, Any]) -> set[tuple[str, str]]:
    """The `lifecycle` region's (from, to) pairs, self-loops included, KILL's arms into `killed`
    aside (24 §8.2's note names them)."""
    out: set[tuple[str, str]] = set()
    for name, node in node_at(chart, "lifecycle")["states"].items():
        groups = list((node.get("on") or {}).values())
        groups += [v for k, v in (node.get("invoke") or {}).items() if k in ("onDone", "onError")]
        for spec in groups:
            for arm in spec if isinstance(spec, list) else [spec]:
                target = str(arm.get("target") or "").rsplit(".", 1)[-1]
                if target and target != "killed":
                    out.add((name, target))
    return out


def test_b01_24_diagram_draws_every_lifecycle_edge() -> None:
    """C-2.19: 24 §8.2's diagram draws exactly the chart's `lifecycle` edges, so the owner
    document cannot drift from the contract (C-2.19)."""
    text = (_CATALOGUE.parent / "24-internal-schemas.md").read_text(encoding="utf-8")
    block = text[text.index("### 8.2 Order state machine") : text.index("**Binding transition")]
    states = node_at(CHART, "lifecycle")["states"]
    camel = {"".join(w.capitalize() for w in s.split("_")): s for s in states}
    drawn = re.findall(r"^\s+(\w+) --> (\w+)", block, re.M)
    assert {(camel[a], camel[b]) for a, b in drawn if "[*]" not in (a, b)} == _edges(CHART)


def test_inv_b1_c_amend_rejected_never_terminal() -> None:
    out = [t for e, _g, t in exits(CHART, "lifecycle.amend_pending") if e == "AMEND_REJECTED"]
    assert out and all(t is not None and t.rsplit(".", 1)[-1] not in TERMINALS for t in out)


def test_inv_b1_d_cancel_pending_handles_exec() -> None:
    assert "EXEC" in node_at(CHART, "lifecycle.cancel_pending")["on"]


def test_inv_b1_e_unknown_resolved_only_by_recon() -> None:
    """Besides reconciliation, only `MISMATCH` (#847: held) and INV-B1-h's `KILL` leave it; version
    4 puts that arm on the state, after INV-B1-p's guarded one."""
    leaving = {(e, t) for e, _g, t in exits(CHART, "lifecycle.unknown")}
    others = {(e, t) for e, t in leaving if not e.startswith("RECON_")}
    assert others == {("MISMATCH", "order.lifecycle.held"), ("KILL", "order.lifecycle.killed")}


def test_b01_killed_is_final_terminal_with_cancel_and_audit() -> None:
    assert node_at(CHART, "lifecycle.killed")["type"] == "final"
    assert is_terminal(CHART, "lifecycle.killed")
    entry = entry_of(CHART, "lifecycle.killed")
    for name in ("mark_halted_by_kill", "issue_kill_cancel", "audit_kill"):
        assert entry.count(name) == 1
    assert CHART["context"]["halted_by_kill"] is False


def _restore_real(monkeypatch: pytest.MonkeyPatch, *, hang: bool = False) -> list[str]:
    """Real KILL actions. A cancel is recorded whether the `cancel_pending` invoke sends it (it
    hangs if *hang*, to keep that invoke in flight) or the KILL does, through the OMS's audited
    cancel service (SR-E29-06)."""
    cancels: list[str] = []

    async def _cancel(*_a: object, **_k: object) -> None:
        cancels.append("cancel_order")
        if hang:
            await asyncio.Event().wait()

    for name in _REAL_KILL_ACTIONS:
        monkeypatch.setitem(b01.ACTIONS, name, getattr(b01, name))
    monkeypatch.setitem(b01.SERVICES, "cancel_order", _cancel)
    monkeypatch.setattr(b01, "_ports", b01.OrderPorts(commands=Commands(on_cancel=_cancel)))
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
        if state in _UNOWNED:  # KILL only audits there: INV-B1-n's property
            return
        assert interp.context["halted_by_kill"] is True
        assert interp.error is None
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
    monkeypatch.setattr(b01, "_ports", b01.OrderPorts(commands=Commands(on_cancel=_cancel)))
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

    monkeypatch.setattr(b01, "_ports", b01.OrderPorts(commands=Commands(on_cancel=_boom)))
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


_HYP = settings(
    max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
_PROT = "audit_kill_protection_retained"
_MANAGING = frozenset(
    "adopt_ack adopt_amend adopt_cancel_ack adopt_recon adopt_untracked apply_fill"
    " issue_kill_cancel keep_prior_order_live mark_needs_lookup record_cancel_refused"
    " reserve_rate_token stamp_validated".split()
)
_UNTRACKED_EXITS = {
    ("cancelled", "RECON_FOUND_CANCELLED"),
    ("cancelled", "RECON_MISS"),
    ("filled", "RECON_FOUND_FILLED"),
}


def _into(state: str) -> set[tuple[str, str]]:
    return {(p, e) for p, _n in walk(CHART) for e, _g, t in exits(CHART, p) if t == state}


def _leaf(interp: Any, region: str = "lifecycle") -> str:
    head = f"order.{region}."
    return str(next(s for s in interp.current_state_ids if s.startswith(head)))[len(head) :]


@contextlib.asynccontextmanager
async def _at(
    state: str, charts: Charts, real_kill: bool = False, **kw: Any
) -> AsyncIterator[tuple[Any, Any, list[str]]]:
    with pytest.MonkeyPatch.context() as mp:
        rec = instrument("order", mp, "async_def", **kw)
        cancels = _restore_real(mp) if real_kill else []
        for name, service in kw.get("service_mode", {}).items():
            mp.setitem(b01.SERVICES, name, service)
        res = await park("order", CHART, state if "." in state else f"lifecycle.{state}", charts)
        try:
            yield res.interpreter, rec, cancels
        finally:
            await res.interpreter.stop()


async def test_b01_bindings_schemas_guards_and_audits() -> None:
    """Every event has a closed schema of this machine's own (#847), every guard denies an empty
    event (A6), only `adoption_allowed` denies everything (until E45-S01 records D6), and every
    audit reaches the hook (C-2.9)."""
    schemas = CV_EVENT_SCHEMAS["order"]
    assert all_events(CHART) == set(schemas) == set(b01.SCHEMAS)
    assert all(
        s["type"] == "object" and s["additionalProperties"] is False for s in schemas.values()
    )
    assert not any(guard({}, None) for guard in b01.GUARDS.values())
    assert b01.GUARDS["adoption_allowed"] is b01.adoption_allowed
    assert set(b01.ACTIONS) | set(b01.GUARDS) | set(b01.SERVICES) == _NAMED
    audits, hook = sorted(n for n in b01.ACTIONS if n.startswith("audit_")), AsyncMock()
    b01.set_audit_hook(hook)
    try:
        for name in audits:
            await b01.ACTIONS[name](None, {}, None, None)
    finally:
        b01.set_audit_hook(None)
    want = [{"audit_kill": "halted_by_kill"}.get(n, n[6:]) for n in audits]
    assert len(audits) == 12 and [c.args[0] for c in hook.await_args_list] == want


@_HYP
@given(ok=st.booleans(), bad=st.booleans(), full=st.booleans(), dup=st.booleans())
async def test_b01_place_result_binds_only_an_ack_or_a_full_match_property(
    ok: bool, bad: bool, full: bool, dup: bool, charts: Charts
) -> None:
    """OM-S05 regression (INV-B1-m): with no positive full match, a duplicate-id result never
    reaches `submitted`; it parks in `unknown`, where a KILL cancels nothing under the id."""
    names = "ret_code_ok is_link_id_mismatch is_duplicate_link_id_full_match is_duplicate_link_id"
    plan = dict(zip(names.split(), (ok, bad, full, dup), strict=True))
    bound = ok or (full and not bad)  # an ack, or a full match no mismatch read refuted
    want = "submitted" if bound else "held" if bad else "unknown" if dup else "rejected"
    done = {"place_order": _done}
    async with _at("submitting", charts, True, guards=plan, service_mode=done) as (i, _r, cancels):
        await settle()
        assert _leaf(i) == want
        await i.send("KILL", wait=True)
        await settle()
        assert len(cancels) == bound


async def test_b01_kill_then_refused_cancel_keeps_halt_and_one_cancel(charts: Charts) -> None:
    """INV-B1-h: KILL reuses the in-flight cancel; if the exchange refuses it, the order is live
    again with `halted_by_kill` set and no second cancel (B18's cancel-all is the backstop)."""
    gate, calls = asyncio.Event(), [0]

    async def _refused(*_a: object, **_k: object) -> dict[str, Any]:
        calls[0] += 1
        await gate.wait()
        return {}  # `ret_code_ok` denied: the exchange refused the cancel

    done = {"cancel_order": _refused}
    async with _at("cancel_pending", charts, True, service_mode=done) as (i, rec, _c):
        await i.send("KILL", wait=True)
        gate.set()
        await settle()
        assert _leaf(i) == "submitted" and i.context["halted_by_kill"] is True and calls == [1]
        assert rec.actions.count("record_cancel_refused") == 1


_RESULTS = {  # invoking state -> (service, adopting action, refusing action)
    "cancel_pending": ("cancel_order", "adopt_cancel_ack", "record_cancel_refused"),
    "amend_pending": ("amend_order", "adopt_amend", "keep_prior_order_live"),
}


@_HYP
@given(state=st.sampled_from(sorted(_RESULTS)), ok=st.booleans(), fills=st.booleans())
async def test_inv_b1_j_result_adopted_only_if_ret_code_ok_property(
    state: str, ok: bool, fills: bool, charts: Charts
) -> None:
    """INV-B1-j and INV-B1-c's half: ruling 3's regression (a business reject ran adopt_amend)."""
    src, adopt, refuse = _RESULTS[state]
    plan = {"ret_code_ok": ok, "has_fills": fills, "ret_code_ok_and_has_fills": ok and fills}
    async with _at(state, charts, guards=plan, service_mode={src: _done}) as (i, rec, _c):
        await settle()
        live = "partially_filled" if fills else "submitted"
        assert _leaf(i) == ("cancelled" if ok and src == "cancel_order" else live)
        assert (adopt in rec.actions) is ok and (refuse in rec.actions) is not ok


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
    async with _at(start, charts) as (i, _r, _c):
        for ev in [*events, end]:
            before = _leaf(i)
            await i.send(ev, wait=True)
            await settle()
        states, terminal = _ENDS[end]
        assert before not in states or _leaf(i) == terminal


@_HYP
@given(events=st.lists(st.sampled_from(_EVENTS), max_size=8), miss=st.booleans(), ok=st.booleans())
async def test_inv_b1_l_untracked_is_never_managed_property(
    events: list[str], miss: bool, ok: bool, charts: Charts
) -> None:
    """No event before an ADOPT, allowed or not, runs a managing action: commands are refused."""
    assert _into("order.lifecycle.untracked") == {("lifecycle.draft", "DISCOVERED")}
    plan = {"second_consecutive_miss": miss, "adoption_allowed": ok}
    done = {"cancel_order": _done, "amend_order": _done}
    async with _at("untracked", charts, guards=plan, service_mode=done) as (i, rec, _c):
        for ev in [*"CANCEL AMEND SEND VALIDATE".split(), *filter("ADOPT".__ne__, events), "ADOPT"]:
            before = _leaf(i)
            await i.send(ev, wait=True)
            await settle()
            assert ev == "ADOPT" or before == _leaf(i) or (_leaf(i), ev) in _UNTRACKED_EXITS
        assert rec.actions[1:5] == ["audit_command_refused_unowned"] * 4  # consumed, never deferred
        assert not (_MANAGING - {"adopt_recon", "adopt_untracked"}) & set(rec.actions)


@_HYP
@given(
    events=st.lists(st.sampled_from([e for e in _EVENTS if e != "OPERATOR_RESOLVED"]), max_size=8)
)
async def test_inv_b1_m_held_is_left_only_by_the_operator_property(
    events: list[str], charts: Charts
) -> None:
    """Every guard allowed: only the operator's OPERATOR_RESOLVED moves it (to rejected)."""
    sources = {f"lifecycle.{s}" for s in ("submitting", "submitted", "unknown", "quarantined")}
    assert {p for p, _e in _into("order.lifecycle.held")} == sources
    async with _at("held", charts, guards=dict.fromkeys(b01.GUARDS, True)) as (i, rec, _c):
        for ev in [*events, "OPERATOR_RESOLVED"]:
            assert _leaf(i) == "held"
            await i.send(ev, wait=True)
            await settle()
        assert _leaf(i) == "rejected" and not _MANAGING & set(rec.actions)


_OWNED_BY = {"OPERATOR_RESOLVED": "held", "ADOPT": "untracked"}


@pytest.mark.parametrize("command", sorted(_OWNED_BY))
@pytest.mark.parametrize("state", [*LIVE, *TERMINALS])
async def test_inv_b1_m_a_stray_operator_command_is_refused_never_kept(
    state: str, command: str, charts: Charts
) -> None:
    """Every guard allowed: `OPERATOR_RESOLVED` outside `held`, or `ADOPT` outside `untracked`,
    is consumed and audited by the `lifecycle` arm, never deferred, so a later MISMATCH still
    holds the order for the Owner."""
    if _OWNED_BY[command] == state:
        return  # the owner's own arm: INV-B1-m's property and INV-B1-l's
    async with _at(state, charts, guards=dict.fromkeys(b01.GUARDS, True)) as (i, rec, _c):
        mark = len(rec.actions)
        await i.send(command, wait=True)
        await settle()
        assert (_leaf(i), i.deferred_count) == (state, 0)
        assert rec.actions[mark:] == ["audit_operator_command_refused"]
        if "MISMATCH" in (node_at(CHART, f"lifecycle.{state}").get("on") or {}):
            await i.send("MISMATCH", wait=True)
            await settle()
            assert _leaf(i) == "held"


@_HYP
@given(state=st.sampled_from(_UNOWNED), events=st.lists(st.sampled_from(_EVENTS), max_size=5))
async def test_inv_b1_n_kill_never_cancels_an_unowned_order_property(
    state: str, events: list[str], charts: Charts
) -> None:
    """Whatever came before, a KILL on an untracked or held order only audits (SR-E29-06)."""
    async with _at(state, charts, True) as (i, rec, cancels):
        for ev in [e for e in events if e != "KILL"]:
            await i.send(ev, wait=True)
        await settle()
        before, mark = _leaf(i), len(rec.actions)
        await i.send("KILL", wait=True)
        await settle()
        if before in _UNOWNED:
            assert _leaf(i) == before and cancels == []
            assert rec.actions[mark:] == ["audit_kill_ignored_unowned", _PROT]
            assert i.context["halted_by_kill"] is False


# --- #847 slice 1b, chart version 2: the protection region's C-2.6 gaps --------------------------


#: INV-B1-o: the arms that put an order into a filled state, by the state they leave.
_FILLED_STATES = ("order.lifecycle.filled", "order.lifecycle.partially_filled")
_ENDS_WITH_FILLS = ("order.lifecycle.cancelled", "order.lifecycle.expired")


def test_inv_b1_o_every_arm_into_a_filled_state_raises_the_notice() -> None:
    """The notice is the target's entry, so no arm into `filled` or `partially_filled` can lack
    it, and `cancelled` and `expired` run it too, for an order ended with fills (version 3)."""
    arms = {(p, e) for p, _n in walk(CHART) for e, _g, t in exits(CHART, p) if t in _FILLED_STATES}
    assert {e for _p, e in arms} >= {"EXEC", "RECON_FOUND_PARTIAL", "RECON_FOUND_FILLED"}
    for target in (*_FILLED_STATES, *_ENDS_WITH_FILLS):
        entry = entry_of(CHART, target.split(".", 1)[1])
        assert entry[0] == "persist_event" and "notify_protection_region" in entry, target
    for path, node in walk(CHART):  # and no arm carries a second copy of it
        for spec in (node.get("on") or {}).values():
            for arm in spec if isinstance(spec, list) else [spec]:
                late = arm.get("target") is None and path.split(".")[-1] in _LATE_FILL
                assert late or "notify_protection_region" not in arm.get("actions", ()), path


@pytest.mark.parametrize(
    ("state", "event"),
    [
        *[(s, e) for s in ("submitted", "triggered", "cancel_pending") for e in ["EXEC"]],
        *[(s, "RECON_FOUND_FILLED") for s in ("unknown", "quarantined", "untracked")],
        *[(s, "RECON_FOUND_PARTIAL") for s in ("unknown", "quarantined")],
    ],
)
async def test_b01_a_fill_into_a_filled_state_notifies_the_protection_region(
    state: str, event: str, charts: Charts
) -> None:
    """24 §8.8 rule 2: however the first fill arrives, one notice starts the SL deadline; the
    reconciliation arms of `unknown`, `quarantined` and `untracked` included (slice 1b's gaps)."""
    plan = {"exec_new_and_closes": True}
    async with _at(state, charts, guards=plan) as (i, rec, _c):
        mark = len(rec.actions)
        await i.send(event, wait=True)
        await settle()
        assert _leaf(i) in ("filled", "partially_filled") and i.deferred_count == 0
        assert rec.actions[mark:].count("notify_protection_region") == 1


#: Where a fill can still arrive although the order no longer takes one (INV-B1-o).
_LATE_FILL = ("held", "filled", "cancelled", "rejected", "expired", "killed")


@pytest.mark.parametrize("state", _LATE_FILL)
async def test_inv_b1_o_a_fill_reaching_a_final_or_held_order_is_an_audited_anomaly(
    state: str, charts: Charts
) -> None:
    """S6: the EXEC is consumed, never deferred, by an arm that audits a `ReconcileAnomaly` and
    notifies the protection region; the lifecycle state stays (a fill racing a cancel, an expiry
    or a KILL starts the SL deadline, slice 1b's security Low 2)."""
    async with _at(state, charts, guards=dict.fromkeys(b01.GUARDS, True)) as (i, rec, _c):
        mark = len(rec.actions)
        await i.send("EXEC", wait=True)
        await settle()
        assert (_leaf(i), i.deferred_count) == (state, 0)
        assert rec.actions[mark:] == ["audit_reconcile_anomaly", "notify_protection_region"]


@pytest.mark.parametrize("event", ["RECON_FOUND_LIVE", "RECON_FOUND_PARTIAL", "EXEC"])
async def test_b01_untracked_consumes_the_exchange_facts(event: str, charts: Charts) -> None:
    """INV-B1-l (version 3): `untracked` records the facts and restarts its miss count, never
    deferring them (past DEFER_MAX a deferred event is evicted), and runs no managing action."""
    async with _at("untracked", charts) as (i, rec, _c):
        mark = len(rec.actions)
        await i.send(event, wait=True)
        await settle()
        assert (_leaf(i), i.deferred_count) == ("untracked", 0)
        assert rec.actions[mark:] == ["record_remote_state"]


@pytest.mark.parametrize("leaf", ["sl_present", "sl_missing"])
async def test_b01_a_repeated_first_fill_or_a_late_deadline_is_consumed(
    leaf: str, charts: Charts
) -> None:
    """INV-B1-f: after the attach result a repeated FIRST_FILL and a
    late SL_DEADLINE are consumed by the region's arm, never deferred, and move nothing."""
    async with _at(f"protection.{leaf}", charts) as (i, rec, _c):
        mark = len(rec.actions)
        for event in ("FIRST_FILL", "SL_DEADLINE"):
            await i.send(event, wait=True)
        await settle()
        assert (_leaf(i, "protection"), i.deferred_count) == (leaf, 0)
        assert rec.actions[mark:] == ["record_sl_fact_ignored"] * 2


_INTO_SL_PRESENT = {
    ("protection.sl_pending", "onDone", "sl_attach_ok"),
    ("protection.sl_missing", "SL_OBSERVED", "sl_observed_ok"),
}
_READS = st.lists(st.sampled_from(("SL_OBSERVED", "SL_LOST")), max_size=3)
_EARLY = st.lists(st.sampled_from(("SL_OBSERVED", "SL_LOST", "SL_DEADLINE")), max_size=3)
_LIFECYCLE_ONLY = {e for e in _EVENTS if e not in ("SL_OBSERVED", "SL_LOST", "SL_DEADLINE")}


@_HYP
@given(
    attach=st.sampled_from(("confirmed", "rejected", "failed")),
    own=st.booleans(),
    early=_EARLY,
    during=_READS,
    events=st.lists(st.sampled_from(_EVENTS), max_size=6),
)
@example(attach="rejected", own=True, early=[], during=["SL_OBSERVED"], events=[])
@example(attach="failed", own=True, early=["SL_OBSERVED"], during=[], events=[])
@example(attach="confirmed", own=True, early=[], during=[], events=["SL_OBSERVED", "SL_LOST"])
@example(attach="rejected", own=False, early=[], during=[], events=["SL_OBSERVED", "SL_DEADLINE"])
async def test_inv_b1_f_sl_present_only_from_the_exchange_property(
    attach: str, own: bool, early: list[str], during: list[str], events: list[str], charts: Charts
) -> None:
    """Every other guard allowed: the attach result counts only if `sl_attach_ok` confirms it, an
    `SL_OBSERVED` in `sl_missing` only if `sl_observed_ok` does (*own*), a reading or a late
    `SL_DEADLINE` the leaf does not act on is consumed, never deferred, and after the attach
    result the last confirmed reading decides (C-2.6; slice 1b's replays, version 3)."""
    present = "order.protection.sl_present"
    arms = {(p, e, g) for p, _n in walk(CHART) for e, g, t in exits(CHART, p) if t == present}
    assert arms == _INTO_SL_PRESENT
    gate = asyncio.Event()

    async def _attach(*a: object, **k: object) -> Any:
        await gate.wait()
        return await (_fail if attach == "failed" else _done)(*a, **k)

    plan = {**dict.fromkeys(b01.GUARDS, True), "sl_attach_ok": attach == "confirmed"}
    plan["sl_observed_ok"] = own
    svc = {"attach_native_sl": _attach}
    async with _at("protection.not_required", charts, guards=plan, service_mode=svc) as (i, rec, _):
        for ev in [*early, "FIRST_FILL", *during]:
            await i.send(ev, wait=True)
        assert _leaf(i, "protection") == "sl_pending" and i.deferred_count == 0
        gate.set()
        on = attach == "confirmed"
        for ev in ["", *events]:  # "": the attach result itself
            if ev:
                await i.send(ev, wait=True)
            await settle()
            on = (ev == "SL_OBSERVED" and own) or (on and ev != "SL_LOST")
            assert _leaf(i, "protection") == ("sl_present" if on else "sl_missing")
            assert i.has_tag("protected") is on
        assert attach == "failed" or ("sl_attach_ok", attach == "confirmed") in rec.guards
        if not set(events) & _LIFECYCLE_ONLY:  # nothing the protection region owns is deferred
            assert i.deferred_count == 0
