"""An amend's settle keeps its reserve (E29-T04 #913, the closing slice's CG19; S4-B2's Fable L2).

The command port's amend ends its venue call `AMEND_SETTLE_RESERVE_S` before the amend's deadline,
so that the settle of the rows it recorded ahead still runs (S4-B2's review fold 2). A refused call
that carries an `AUTH_ERROR` with the exchange's return code is reported first (24 Sec.8.6, before
any answer), and that report ran on the amend's whole deadline: one that did not answer took the
settle's reserve, so the rows stayed in flight, their key held, until the complete read. The report
ends with the venue call instead, as it does for an `AuthError` the call raises, and a report cut
short is logged and lost, never the answer (`oms_auth_rejection_lost`)."""

from __future__ import annotations

import asyncio
import selectors
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.exchange.base.errors import OmsErrorCode
from candleviewer.exchange.base.fakes import FakeReject
from candleviewer.oms import commands as oc
from candleviewer.statechart.bindings import b01_order as b01
from tests.unit.oms import command_rig as cr
from tests.unit.oms.command_rig import Rig

_REFUSED = FakeReject(OmsErrorCode.AUTH_ERROR, 10003)
_TIGHTER = "58500"  # the rig's entry holds its stop at 58000: recorded ahead, then sent


async def _live(rig: Rig) -> Any:
    """An entry resting at the venue, stored `submitted` as B1's `amend_pending` finds it."""
    order = cr.new_order()
    await rig.stored(order, lifecycle="submitted")
    rig.demo.seed_order(cr.exchange_order(order), uid="100001")
    return order


def _amend(order: Any) -> b01.Command:
    return cr.command("amend", order, {"stop_loss": _TIGHTER})


async def _hangs(*_args: object, **_kwargs: object) -> None:
    await asyncio.Event().wait()


class _JumpingClock(selectors.DefaultSelector):
    """The loop's selector on a virtual clock (C-13.7): where the loop would wait for its next
    timer, the clock jumps to it instead, so each bound is met at once and in its order, and
    nothing waits on the wall clock. A loop with no timer and nothing to run would wait forever:
    that fails, never hangs."""

    def __init__(self) -> None:
        super().__init__()
        self.now = 0.0

    def select(self, timeout: float | None = None) -> list[tuple[selectors.SelectorKey, int]]:
        ready = super().select(0)
        if ready or timeout == 0:
            return ready
        if timeout is None:
            raise RuntimeError("the loop would wait forever: no timer and nothing to run")
        self.now += timeout
        return ready


class _VirtualLoop(asyncio.SelectorEventLoop):
    """A loop on `_JumpingClock`'s time."""

    def __init__(self) -> None:
        self._clock = _JumpingClock()
        super().__init__(self._clock)

    def time(self) -> float:
        return self._clock.now


async def test_a_refused_credentials_report_ends_with_the_venue_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The report's bound is the venue call's, `AMEND_SETTLE_RESERVE_S` before the amend's, and
    the settle's is the amend's own: the report never spends the settle's reserve."""
    rig = cr.build_rig()
    order = await _live(rig)
    fixed = asyncio.get_running_loop().time() + 1000.0  # each deadline, pinned far ahead
    monkeypatch.setattr(rig.port, "_deadline", lambda _seconds: fixed)
    rig.demo.script("amend_order", _REFUSED)
    reported: list[float | None] = []
    settled: list[float | None] = []
    real_venue, real_settle = rig.port._venue, rig.port._settle_stop

    async def venue(account: Any, code: str | None, ret: int | None, *, by: Any = None) -> None:
        reported.append(by)
        await real_venue(account, code, ret, by=by)

    async def settle(*args: Any, **kwargs: Any) -> None:
        settled.append(kwargs.get("by"))
        await real_settle(*args, **kwargs)

    monkeypatch.setattr(rig.port, "_venue", venue)
    monkeypatch.setattr(rig.port, "_settle_stop", settle)
    answer = await rig.port.amend(_amend(order))
    assert (answer["error_code"], answer["exchange_ret_code"]) == ("AUTH_ERROR", 10003)
    assert reported == [fixed - oc.AMEND_SETTLE_RESERVE_S] and settled == [fixed]
    assert [call[1:] for call in rig.credentials.calls] == [("AUTH_ERROR", 10003)]
    assert {row.status for row in rig.store._stops.values()} == {"void"}


def test_a_report_that_does_not_answer_leaves_the_settle_its_reserve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A credential report that never answers is cut where the venue call's bound ends and logged
    lost; the settle still voids the rows within its reserve, so their key is free at once, where
    before it found the amend's deadline spent and left them in flight. It runs on the virtual
    clock (`_VirtualLoop`): the hanging report's bound, then the settle's, are met at once."""
    monkeypatch.setattr(oc, "AMEND_SETTLE_RESERVE_S", 0.25)  # the timeline scaled down, as
    monkeypatch.setattr(oc, "AMEND_AUDIT_GRACE_S", 0.01)  # the constructor bounds it (L1)

    async def amend() -> None:
        rig = cr.build_rig(amend_timeout_s=0.5, port_timeout_s=60.0, submit_timeout_s=60.0)
        order = await _live(rig)
        rig.demo.script("amend_order", _REFUSED)
        monkeypatch.setattr(rig.credentials, "refused", _hangs)
        with capture_logs() as logs:
            answer = await asyncio.wait_for(rig.port.amend(_amend(order)), 5.0)  # virtual time
        assert answer["error_code"] == "AUTH_ERROR"
        assert {row.status for row in rig.store._stops.values()} == {"void"}  # settled, in time
        events = [log["event"] for log in logs if log.get("log_level") in ("error", "critical")]
        assert events == ["oms_auth_rejection_lost"]  # the report lost, never the settle

    with asyncio.Runner(loop_factory=_VirtualLoop) as runner:
        runner.run(amend())
