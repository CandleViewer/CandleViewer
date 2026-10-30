"""tests/xstate_contract/test_b01_order_reconcile.py: B1 chart version 7 (#914, E29-T06 PR 1).

Membership module of the blocking gate for B1's reconciliation outcomes (24 Sec.8.5 step 3b, 28
B1.8 version 7, INV-B1-s). A settled live row that a pass finds nowhere moves to `unknown`
(`missing_remote`) with its miss count restarted, and only a second consecutive `RECON_MISS` there
ends it `rejected`, with the closed `reject_code` that miss carries; a row with a cancel or an
amend in flight takes no miss, as the pass leaves it to its request. Each live state is reached as
a real order reaches it, on the real binding with the recording step writer and command port
(`b01_ports`), on the library. Nothing sends a `RECON_MISS` in production until E29-T06's pass is
wired, so these arms change no behaviour yet.
"""

from __future__ import annotations

import contextlib
from collections import OrderedDict
from collections.abc import AsyncIterator, Mapping
from typing import Any, Final

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from structlog.testing import capture_logs
from xstate_statemachine import SimulatedClock

from candleviewer.oms import order_link_resolution
from candleviewer.oms.errors import IllegalTransition
from candleviewer.oms.execution import apply_fields
from candleviewer.oms.order_machine import Legality
from candleviewer.statechart import build
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.config import CV_EVENT_SCHEMAS
from candleviewer.statechart.registry import Registry
from tests.unit.oms.order_rig import ACCOUNT, fill_of, order_of
from tests.xstate_contract._harness import AuditTap, settle
from tests.xstate_contract.b01_ports import Commands, Store

REGISTRY = Registry()
CHART = REGISTRY.get("order")
#: The settled live states 24 Sec.8.5 step 3b sends a `RECON_MISS` (INV-B1-s), in chart order.
MISSED_LIVE: Final = ("submitted", "triggered", "partially_filled", "quarantined")
#: The live states with a request in flight, which the pass leaves to it (#4807).
IN_FLIGHT_LIVE: Final = ("cancel_pending", "amend_pending")
#: Version 7's arm in each of them.
ARM: Final = {"target": "#order.lifecycle.unknown", "actions": ["record_missing_remote"]}
UNRESOLVED: Final = b01.UNRESOLVED_AFTER_RECONCILE
DEMO: Final = b01.DEMO_RETENTION_EXPIRED
_ORDER = {"order_id": str(order_of().id), "order_link_id": order_of().order_link_id}
_ORDER |= {"account_id": str(ACCOUNT), "symbol": "BTCUSDT", "side": "buy", "qty": "1"}
_ORDER |= {"price": "63000", "stop_loss": "62000"}
VALIDATE: Final[dict[str, Any]] = {"gates": dict.fromkeys(b01.GATES, b01.PASSED), "order": _ORDER}
#: How a placed order (`submitted`, bound to `x1`) reaches each settled live state: by the event a
#: real order takes there.
_REACH: Final[dict[str, tuple[str, dict[str, Any]] | None]] = {
    "submitted": None,
    "triggered": ("TRIGGERED", {"updated_time": 1}),
    "partially_filled": ("EXEC", fill_of(order_of(), "e1", "0.4", exchange_order_id="x1")),
    "quarantined": ("FAULT", {"reason": "OM-T04"}),
}
_HYP = settings(
    max_examples=20, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)


class _Event:
    """An event as an action reads it: its name and its payload."""

    def __init__(self, kind: str, payload: Mapping[str, Any]) -> None:
        self.type, self.payload = kind, dict(payload)


def _leaf(interp: Any) -> str:
    head = "order.lifecycle."
    return str(next(s for s in interp.current_state_ids if s.startswith(head)))[len(head) :]


def _miss(code: str | None, run: str = "p1") -> dict[str, str]:
    """A `RECON_MISS` payload: the pass (*run*) and, when given, the closed code it carries."""
    return {"pass_id": run} | ({} if code is None else {"reject_code": code})


@contextlib.asynccontextmanager
async def _placed() -> AsyncIterator[tuple[Any, Store, Commands]]:
    """A placed order on B1's real binding: validated, sent, acked as `x1` and so bound, at rest
    in `submitted`."""
    store, commands = Store(), Commands()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(b01, "_ATTEMPTS", OrderedDict())
        mp.setattr(b01, "_REPLAYS", {})
        mp.setattr(b01, "_ports", b01.OrderPorts(persist=store, commands=commands))
        mp.setattr(b01, "_core", apply_fields)
        built = await build(
            "order", clock=SimulatedClock(), lane="order", registry=REGISTRY, plugins=(AuditTap(),)
        )
        interp = built.interpreter
        try:
            await interp.send("VALIDATE", wait=True, **VALIDATE)
            await interp.send("SEND", wait=True)
            await settle()
            assert _leaf(interp) == "submitted"
            yield interp, store, commands
        finally:
            await interp.stop()


async def _reach(interp: Any, state: str) -> None:
    step = _REACH[state]
    if step is not None:
        event, payload = step
        await interp.send(event, wait=True, **payload)
        await settle()
    assert _leaf(interp) == state


# --- The chart and its static table ------------------------------------------------------------


def test_inv_b1_s_the_four_settled_live_states_take_a_miss_into_unknown_and_no_other_does() -> None:
    """24 Sec.8.5 step 3b's settled live rows each take `RECON_MISS` into `unknown` through
    `record_missing_remote`, and every other state but `unknown` and `untracked` has no arm for
    it, so the OMS facade's static table, read from the chart, refuses one there before any
    send (24 Sec.8.2)."""
    states = CHART["states"]["lifecycle"]["states"]
    taking = [
        name for name, node in states.items() if (node.get("on") or {}).get("RECON_MISS") == ARM
    ]
    assert taking == list(MISSED_LIVE)
    armed = {name for name, node in states.items() if "RECON_MISS" in (node.get("on") or {})}
    assert armed - set(MISSED_LIVE) == {"unknown", "untracked"}
    handled = Legality.of(CHART).handled
    takes = {name for name, events in handled.items() if "RECON_MISS" in events}
    assert takes == {*MISSED_LIVE, "unknown", "untracked"}


def test_inv_b1_s_a_row_with_a_request_in_flight_takes_no_miss() -> None:
    """28 B1.8 version 7 (c): no state that runs an invoke has a `RECON_MISS` arm, so a cancel or
    an amend in flight is never ended by a miss and every state a command lands in stays settled
    (#4807, `test_command_settled_state.py`); the facade refuses the miss there before any send,
    and step 3b leaves such a row to its request, as it leaves a create to its send."""
    legality = Legality.of(CHART)
    assert set(IN_FLIGHT_LIVE) < legality.in_flight
    assert legality.in_flight.isdisjoint(MISSED_LIVE)
    for state in sorted(legality.in_flight):
        assert "RECON_MISS" not in (CHART["states"]["lifecycle"]["states"][state].get("on") or {})
        with pytest.raises(IllegalTransition):
            legality.require(state, "RECON_MISS")


def test_the_recon_miss_schema_takes_a_closed_reject_code_and_nothing_else() -> None:
    """28 B1.8 version 7 (b): `RECON_MISS` carries `pass_id` and, closed, one of the two codes a
    pass may end an `unknown` row with; any other key or code is refused before the guards."""
    validator = Draft202012Validator(CV_EVENT_SCHEMAS["order"]["RECON_MISS"])
    assert b01.RECON_REJECT_CODES == (UNRESOLVED, DEMO)
    for good in ({}, {"pass_id": "p1"}, _miss(UNRESOLVED), _miss(DEMO)):
        assert validator.is_valid(good), good
    for bad in ({"reject_code": "EXPIRED_UNSENT"}, {"reason": "missing_remote"}, {"pass_id": ""}):
        assert not validator.is_valid(bad), bad


def test_demo_retention_expired_is_the_oms_code() -> None:
    """The statechart package imports no `oms` module (C-3.1), so B1 holds its own copy of the
    code `oms.order_link_resolution` defines (24 Sec.8.6): the two never differ."""
    assert b01.DEMO_RETENTION_EXPIRED == order_link_resolution.DEMO_RETENTION_EXPIRED


# --- The actions ---------------------------------------------------------------------------------


async def test_record_missing_remote_restarts_the_count_and_logs_the_pass_and_the_state() -> None:
    """A live row enters `unknown` with no miss counted, so two further consecutive misses there
    end it, never one (INV-B1-s); the finding is logged at ERROR with the pass and the state the
    row leaves, its last written one (`persisted_state`)."""
    context: dict[str, Any] = {"order_link_id": "cv-x", "recon_misses": 3}
    context["persisted_state"] = "partially_filled"
    with capture_logs() as logs:
        await b01.record_missing_remote(None, context, _Event("RECON_MISS", _miss(None)), None)
    assert context["recon_misses"] == 0
    [entry] = [e for e in logs if e["event"] == "b01_missing_remote"]
    assert (entry["log_level"], entry["left"], entry["pass_id"]) == (
        "error",
        "partially_filled",
        "p1",
    )


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({}, UNRESOLVED),
        (_miss(UNRESOLVED), UNRESOLVED),
        (_miss(DEMO), DEMO),
        ({"reject_code": "EXPIRED_UNSENT"}, UNRESOLVED),  # outside the closed set: the default
    ],
)
async def test_set_reject_unresolvable_takes_the_closed_code_the_miss_carries(
    payload: dict[str, str], code: str
) -> None:
    context: dict[str, Any] = {"order_link_id": "cv-x"}
    await b01.set_reject_unresolvable(None, context, _Event("RECON_MISS", payload), None)
    assert context["reject_code"] == code


# --- On the real binding -------------------------------------------------------------------------


@pytest.mark.parametrize("state", MISSED_LIVE)
async def test_inv_b1_s_a_live_row_a_pass_misses_waits_in_unknown_its_count_restarted(
    state: str,
) -> None:
    """Each settled live row a pass finds nowhere moves to `unknown` by one written step
    (`RECON_MISS`, out of the state it held), with nothing sent: no create again (S1), no
    cancel, no amend."""
    async with _placed() as (interp, store, commands):
        await _reach(interp, state)
        sent = [c.kind for c in commands.sent]
        await interp.send("RECON_MISS", wait=True, **_miss(None))
        await settle()
        assert (_leaf(interp), interp.context["recon_misses"]) == ("unknown", 0)
        step = store.steps[-1]
        assert (step.from_state, step.to_state, step.event) == (state, "unknown", "RECON_MISS")
        assert dict(step.payload) == _miss(None)
        assert [c.kind for c in commands.sent] == sent


@pytest.mark.parametrize("code", [None, UNRESOLVED, DEMO])
async def test_inv_b1_s_two_further_misses_end_the_row_rejected_with_the_code_the_second_carries(
    code: str | None,
) -> None:
    """A live row missed once waits in `unknown`; a second miss there counts one, and only the
    third consecutive miss in all ends it `rejected`, its `reject_code` the closed one that miss
    carries (`UNRESOLVED_AFTER_RECONCILE` when it names none), written with the step."""
    async with _placed() as (interp, store, commands):
        for run in ("p1", "p2"):
            await interp.send("RECON_MISS", wait=True, **_miss(None, run))
            await settle()
            assert _leaf(interp) == "unknown"
        assert interp.context["recon_misses"] == 1
        await interp.send("RECON_MISS", wait=True, **_miss(code, "p3"))
        await settle()
        assert _leaf(interp) == "rejected"
        step = store.steps[-1]
        assert (step.from_state, step.to_state, step.event) == ("unknown", "rejected", "RECON_MISS")
        assert step.context["reject_code"] == (code or UNRESOLVED)
        assert [c.kind for c in commands.sent] == ["place"]


_EVENTS = st.lists(st.sampled_from(("MISS", "MISS_U", "MISS_D", "FOUND")), max_size=6)
_CODES: Final[dict[str, str | None]] = {"MISS": None, "MISS_U": UNRESOLVED, "MISS_D": DEMO}


@_HYP
@given(start=st.sampled_from(MISSED_LIVE), events=_EVENTS)
async def test_inv_b1_s_a_miss_never_ends_a_live_row_property(
    start: str, events: list[str]
) -> None:
    """Whatever the misses and findings after it, a live row's first miss moves it to `unknown`
    and never ends it; a finding there (`RECON_FOUND_LIVE`) restarts the count; and the row ends
    only on the second consecutive miss in `unknown`, `rejected` with that miss's code."""
    async with _placed() as (interp, _store, _commands):
        await _reach(interp, start)
        model, misses, code = start, 0, UNRESOLVED
        for event in events:
            if event == "FOUND":
                if model != "unknown":
                    continue  # a live state takes no finding: the facade refuses it unsent
                await interp.send("RECON_FOUND_LIVE", wait=True, exchange_order_id="x1")
                model = "submitted"
            else:
                await interp.send("RECON_MISS", wait=True, **_miss(_CODES[event]))
                if model != "unknown":
                    model, misses = "unknown", 0
                elif misses < 1:
                    misses += 1
                else:
                    model, code = "rejected", _CODES[event] or UNRESOLVED
            await settle()
            assert _leaf(interp) == model
            if model == "rejected":
                assert interp.context["reject_code"] == code
                break
            if model == "unknown":
                assert interp.context["recon_misses"] == misses
