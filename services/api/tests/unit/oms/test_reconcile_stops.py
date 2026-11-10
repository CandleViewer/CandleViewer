"""Reconciliation's step-5 stop writer (E29-T06 #914 PR 2b; 24 Sec.8.5 step 5, Sec.8.8 rules 3 to
6; BQ-9; C-2.6): the record in force put on a position over `trading-stop`, on the `critical` lane,
from the writer's own read, its record written ahead of the send. Over `FakeTradingPort`; no
network, no sleeps."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.exchange.base.fakes import FakeTradingPort, fake_capabilities
from candleviewer.oms.errors import StopRequestPending
from candleviewer.oms.ports import KeyedRecord, PositionKey
from candleviewer.oms.reconcile_stops import ATTACH_REASON, RESTORE_REASON, RecordedStopWriter
from candleviewer.oms.routing import TradingRouter
from tests.unit.oms.reconcile_rig import ACCOUNT, NOW_US, position, record, ref

RUN_ID = "00000000-0000-4000-8000-0000000000a1"


class Gate:
    def __init__(self, pending: bool = False) -> None:
        self.pending, self.asked = pending, list[tuple[PositionKey, float, bool]]()

    async def clear(
        self, key: PositionKey, *, wait_s: float = 0.0, protective: bool = False
    ) -> None:
        self.asked.append((key, wait_s, protective))
        if self.pending:
            raise StopRequestPending(retry_after_s=5)


class Audit:
    def __init__(self, log: list[Any], refuse: bool = False) -> None:
        self.log, self.refuse = log, refuse

    def record_id(self, action: str, name: str) -> Any:
        raise AssertionError("not used")

    async def write(self, record: Any) -> None:
        if self.refuse:
            raise ConnectionError("the audit store is down")
        self.log.append(("audit", record))


def _writer(**over: Any) -> tuple[RecordedStopWriter, FakeTradingPort, list[Any], Gate]:
    venue = FakeTradingPort(environment="demo", capabilities=fake_capabilities("demo"),
                            now_us=lambda: NOW_US)  # fmt: skip
    router = TradingRouter({"demo": venue}, lane_waits={"critical": 5.0, "entry": 5.0, "poll": 5.0})
    log: list[Any] = []
    gate = over.get("gate") or Gate()
    writer = RecordedStopWriter(router=router, gate=gate, audit=over.get("audit") or Audit(log))
    return writer, venue, log, gate


def _sent(venue: FakeTradingPort) -> list[Any]:
    return [c for c in venue.calls if c.method == "set_trading_stop"]


async def test_an_attach_sends_the_record_in_force_on_the_critical_lane_its_record_ahead() -> None:
    writer, venue, log, gate = _writer()
    naked = position(stop_loss=None, take_profit=Decimal(65000), mark_price=Decimal(63100))
    venue.seed_position(naked)
    assert await writer.attach_recorded(ref(), naked, record(), pass_id=RUN_ID) == "sent"
    [call] = _sent(venue)
    assert (call.lane, call.request.stop_loss, call.request.take_profit) == (
        "critical", Decimal(62000), Decimal(65000),
    )  # native SL (C-2.6), the take-profit kept (24 Sec.8.9)  # fmt: skip
    [(_, written)] = log
    assert isinstance(written, KeyedRecord)
    assert (written.action, written.reason, written.object_id) == (
        "sl.attached", ATTACH_REASON, record().id,
    )  # fmt: skip
    assert written.detail["pass_id"] == RUN_ID and written.actor_user_id is None
    assert gate.asked == [(PositionKey(ACCOUNT, "BTCUSDT", 0), 2.0, True)]  # protective


@pytest.mark.parametrize(
    "shown",
    [
        {"stop_loss": Decimal(61000)},  # protected since step 1's read
        {"qty": Decimal(0), "side": None, "stop_loss": None},  # flat
        # reversed since step 1's read: a naked short the long's trigger could be placed on (above
        # the mark), which is the other side's record, never this one's
        {"side": "sell", "stop_loss": None, "mark_price": Decimal(61900)},
    ],
)
async def test_an_attach_the_writers_own_read_finds_unneeded_sends_nothing(
    shown: dict[str, Any],
) -> None:
    writer, venue, log, _ = _writer()
    venue.seed_position(position(**shown))
    naked = position(stop_loss=None)
    outcome = await writer.attach_recorded(ref(), naked, record(), pass_id=RUN_ID)
    assert (outcome, _sent(venue), log) == ("not_looser", [], [])


@pytest.mark.parametrize(
    ("side", "mark", "placeable"),
    [("buy", "61900", False), ("buy", "62100", True), ("sell", "62100", False),
     ("sell", "61900", True), ("buy", None, False)],
)  # fmt: skip
async def test_an_attach_is_sent_only_while_the_market_is_not_through_the_trigger(
    side: str, mark: str | None, placeable: bool
) -> None:
    """24 Sec.8.8 rule 3: a stop the market is through cannot be placed; that position is the
    fallback's (E32-T02), so nothing is sent and the pass pages it."""
    writer, venue, log, _ = _writer()
    shown = position(stop_loss=None, side=side, mark_price=None if mark is None else Decimal(mark))
    venue.seed_position(shown)
    rec = record(position_side="Buy" if side == "buy" else "Sell")
    outcome = await writer.attach_recorded(ref(), shown, rec, pass_id=RUN_ID)
    assert outcome == ("sent" if placeable else "not_sent")
    assert len(_sent(venue)) == int(placeable) == len(log)


async def test_an_attach_the_gate_holds_or_the_audit_refuses_sends_nothing() -> None:
    held, venue, log, _ = _writer(gate=Gate(pending=True))
    naked = position(stop_loss=None)
    venue.seed_position(naked)
    assert await held.attach_recorded(ref(), naked, record(), pass_id=RUN_ID) == "not_sent"
    unaudited, venue2, _, _ = _writer(audit=Audit([], refuse=True))
    venue2.seed_position(naked)
    with pytest.raises(ConnectionError):  # C-2.9: no record, no send
        await unaudited.attach_recorded(ref(), naked, record(), pass_id=RUN_ID)
    assert (_sent(venue), _sent(venue2), log) == ([], [], [])


async def test_an_attach_the_venue_refuses_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    writer, venue, _, _ = _writer()
    naked = position(stop_loss=None)
    venue.seed_position(naked)

    async def refused(_request: Any) -> Any:
        return SimpleNamespace(ok=False)  # the writer reads the ack's `ok` alone

    monkeypatch.setattr(venue, "set_trading_stop", refused)
    assert await writer.attach_recorded(ref(), naked, record(), pass_id=RUN_ID) == "refused"


async def test_a_restore_puts_the_record_back_over_a_looser_stop_with_both_values() -> None:
    writer, venue, log, gate = _writer()
    looser = position(stop_loss=Decimal(61000))  # lower for a long
    venue.seed_position(looser)
    assert await writer.restore_recorded(ref(), looser, record(), pass_id=RUN_ID) == "sent"
    [call] = _sent(venue)
    assert (call.lane, call.request.stop_loss) == ("critical", Decimal(62000))
    [(_, written)] = log
    assert (written.action, written.reason) == ("sl.modified", RESTORE_REASON)
    assert (written.detail["stop_loss_before"], written.detail["stop_loss"]) == ("61000", "62000")
    assert gate.asked[0][2] is True


@pytest.mark.parametrize(
    "shown",
    [
        {"stop_loss": Decimal(62500)},  # tighter now: it stays (24 Sec.8.8 rule 5)
        {"stop_loss": Decimal(62000)},  # the record's own: nothing to put back
        {"stop_loss": None},  # naked now: the attach's, next pass
        {"qty": Decimal(0), "side": None, "stop_loss": None},  # flat
        {"side": "sell", "stop_loss": Decimal(61000)},  # reversed: looser for a long, not a short's
    ],
)
async def test_a_restore_the_writers_own_read_finds_unneeded_sends_nothing(
    shown: dict[str, Any],
) -> None:
    writer, venue, log, _ = _writer()
    venue.seed_position(position(**shown))
    looser = position(stop_loss=Decimal(61000))
    assert await writer.restore_recorded(ref(), looser, record(), pass_id=RUN_ID) == "not_looser"
    assert (_sent(venue), log) == ([], [])


async def test_a_restore_the_gate_holds_sends_nothing() -> None:
    writer, venue, log, _ = _writer(gate=Gate(pending=True))
    looser = position(stop_loss=Decimal(61000))
    venue.seed_position(looser)
    assert await writer.restore_recorded(ref(), looser, record(), pass_id=RUN_ID) == "not_sent"
    assert (_sent(venue), log) == ([], [])
