"""The OMS under the audit-chain break halt (#2904; 04 §8.1 "Enforced posture"; C-2.6, C-2.21): the
halt reaches the order path only as the B18 kill switch port's `TradingDisabled`, so what every
switch-consulting path does with it is asserted here over the real rigs, the halt's verdict taken
from the real `TradingSwitchesBinding` over the real `HaltingKillSwitch`. Refused: a new entry and a
risk-increasing amend. Admitted: a protective close, every leg of `closeAllPositions`, a cancel, a
quantity cut, a tightened stop and, the native-SL assertion (AGENTS §6), the attach of a missing
native stop-loss on an open position."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.api.position_close import CLOSE_ALL_PATH
from candleviewer.audit.break_halt import AuditBreakHalt, BreakIdentity
from candleviewer.exchange.base.models import TradingStopRequest
from candleviewer.observability.audit_query_metrics import cv_audit_break_halt_state
from candleviewer.oms.errors import OmsError, TradingDisabled
from candleviewer.oms.exits import AmendTerms
from candleviewer.oms.ports import StopOffset
from candleviewer.oms_wiring import HaltingKillSwitch, InterimKillSwitch, TradingSwitchesBinding
from candleviewer.statechart.bindings import b01_order as b01
from tests.unit.api.position_writes_world import World, post
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr
from tests.unit.oms.submit_rig import SubmitRig, context, entry, flatten
from tests.unit.oms.test_exits import OWNER, actor, exits_of, placed
from tests.unit.oms.test_exits_amend import CALLER, amends, scoped

D = Decimal
BREAK = BreakIdentity(3, "entry_hash_mismatch")


class _Gate:
    def refusal(self, account_id: Any) -> None:
        return None


def halted() -> TradingSwitchesBinding:
    """The process's switches with the halt engaged on a break, nothing else refusing."""
    halt = AuditBreakHalt(unread=False)
    assert halt.trip(BREAK)
    return TradingSwitchesBinding(
        live_enabled=True,
        live_flag=lambda: True,
        kill_switch=HaltingKillSwitch(InterimKillSwitch(), halt),
        gate=_Gate(),
        fenced=lambda: False,
    )


def verdict() -> TradingDisabled:
    refusal = halted().refusal(cr.ACCOUNT, "demo")
    assert type(refusal) is TradingDisabled  # no gate `reason`: 403 trading_disabled as is (BQ-242)
    return refusal


def reset_halt_gauge() -> None:
    """`cv_audit_break_halt_state` is one process-wide series that `halted()`'s trip sets to 1:
    set it back to 0 so no later test reads this module's halt."""
    cv_audit_break_halt_state.set(0)


@pytest.fixture
def halt_gauge_reset() -> Iterator[None]:
    yield
    reset_halt_gauge()


#: Every test here engages a halt through `halted()` or `verdict()`.
pytestmark = pytest.mark.usefixtures("halt_gauge_reset")


# ---- submits (`oms.submit`) -------------------------------------------------------------------


@pytest.fixture
async def submit_rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[SubmitRig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    built = sr.build_rig()
    yield built
    await built.machines.stop()


async def test_a_new_entry_under_the_halt_is_trading_disabled_and_nothing_is_sent(
    submit_rig: SubmitRig,
) -> None:
    submit_rig.port.switches.refusals[cr.ACCOUNT] = verdict()
    with pytest.raises(OmsError) as refused:
        await submit_rig.submit(entry(), context())
    assert isinstance(refused.value, TradingDisabled)
    assert "place_order" not in submit_rig.calls()


async def test_a_protective_close_under_the_halt_is_recorded_and_sent(
    submit_rig: SubmitRig,
) -> None:
    """Stops new risk, never traps a position (C-2.6): the close carve-out passes the halt."""
    submit_rig.port.demo.seed_position(cr.position(qty="0.050"))
    submit_rig.port.switches.refusals[cr.ACCOUNT] = verdict()
    outcome = await submit_rig.submit(flatten(), context(protective=True))
    assert (outcome.status, outcome.lifecycle) == (202, "submitted")
    assert submit_rig.calls() == ["positions", "place_order"]


async def test_close_all_positions_under_the_halt_sends_every_leg_marked_protective() -> None:
    """22 `closeAllPositions` (24 Sec.8.10, C-2.6): the route asks the switches and the halt's
    `TradingDisabled` refuses no leg; each is a reduce-only flatten marked `protective`."""
    world = World()
    world.route.switches.refusal_of = verdict()
    answer = await post(world, CLOSE_ALL_PATH, body={})
    assert answer.status_code == 200, answer.text
    assert (answer.json()["requested"], answer.json()["succeeded"]) == (1, 1)
    sent = world.pipeline.submitted
    assert len(sent) == 2
    assert all(r.reduce_only and r.intent == "flatten" and c.protective for r, c in sent)
    assert {c.operation for _, c in sent} == {"closeAllPositions"}


async def test_a_close_all_leg_under_the_halt_is_recorded_and_sent(submit_rig: SubmitRig) -> None:
    """The leg the route hands the pipeline passes the halt at step 6 and at `SEND` (C-2.6)."""
    submit_rig.port.demo.seed_position(cr.position(qty="0.050"))
    submit_rig.port.switches.refusals[cr.ACCOUNT] = verdict()
    leg = context(protective=True, operation="closeAllPositions")
    outcome = await submit_rig.submit(flatten(), leg)
    assert (outcome.status, outcome.lifecycle) == (202, "submitted")
    assert submit_rig.calls() == ["positions", "place_order"]


# ---- amends (`oms.exits`) ---------------------------------------------------------------------


@pytest.fixture
async def rig() -> AsyncIterator[SubmitRig]:
    async with sr.rigged() as built:
        built.store.seed_owner(OWNER)
        yield built


async def test_a_risk_increasing_amend_under_the_halt_is_refused_and_a_cut_is_sent(
    rig: SubmitRig,
) -> None:
    found, exits = await scoped(rig), exits_of(rig, switches=halted())
    up = await exits.amend(found, AmendTerms(qty=D("0.011")), caller=CALLER, expected_seq=None)
    assert (up.kind, up.status, up.code) == ("refused", 403, "trading_disabled")
    assert amends(rig) == []
    down = await exits.amend(found, AmendTerms(qty=D("0.009")), caller=CALLER, expected_seq=None)
    assert down.kind == "accepted" and len(amends(rig)) == 1


async def test_a_stop_tightened_under_the_halt_is_sent(rig: SubmitRig) -> None:
    """The rig's long entry carries its native stop at 58000: 59000 tightens it (C-2.6)."""
    found, exits = await scoped(rig), exits_of(rig, switches=halted())
    tighter = AmendTerms(sides={"stop_loss": StopOffset("price", D("59000"))})
    kept = await exits.amend(found, tighter, caller=CALLER, expected_seq=None)
    assert kept.kind == "accepted" and len(amends(rig)) == 1


async def test_a_stop_loosened_under_the_halt_is_never_sent(rig: SubmitRig) -> None:
    """57000 loosens the rig's stop at 58000: risk-increasing, never sent (BQ-245)."""
    found, exits = await scoped(rig), exits_of(rig, switches=halted())
    looser = AmendTerms(sides={"stop_loss": StopOffset("price", D("57000"))})
    loosened = await exits.amend(found, looser, caller=CALLER, expected_seq=None)
    assert loosened.kind == "refused" and amends(rig) == []


async def test_a_cancel_under_the_halt_is_recorded_and_sent(rig: SubmitRig) -> None:
    """22 `cancelOrder` (C-2.6): a cancel never meets the switches, so under the halt it is
    written ahead and goes out."""
    row = await placed(rig)
    exits = exits_of(rig, switches=halted())
    got = await exits.cancel_admitted(row, actor=actor(), reason="user", request_id=None)
    assert (got.kind, got.status, got.lifecycle_state) == ("accepted", 202, "cancelled")
    assert [c.method for c in rig.port.demo.calls].count("cancel_order") == 1


# ---- the native stop-loss attach (`oms.commands`, B1/B8) --------------------------------------


async def test_native_sl_attach_on_an_open_position_succeeds_under_the_halt() -> None:
    """The native-SL assertion (C-2.6): a filled entry whose stop is missing at the venue gets
    it attached while order entry is halted; the attach never asks the switches."""
    rig = cr.build_rig()
    rig.switches.refusals[cr.ACCOUNT] = verdict()
    order = cr.new_order()
    await rig.stored(order, lifecycle="submitted")
    rig.demo.seed_position(cr.position())
    answer = await rig.port.attach_stop(cr.command("attach_stop", order, {"stop_loss": "58000"}))
    assert answer["ok"] is True and answer["position"]["stop_loss"] == "58000"
    assert rig.calls() == ["positions", "set_trading_stop", "positions"]
    sent = rig.demo.calls[1].request
    assert isinstance(sent, TradingStopRequest)
    assert sent.stop_loss == cr.STOP  # the native stop-loss itself reached the venue
