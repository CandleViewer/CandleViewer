# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""Both arms over the corpus venue, the real port and the real private stream, on a virtual
clock (#856 Scope; the Q5 ruling): the wiring, the timing on the venue's scripted clock, the
taxonomy each sample records, and the guard."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from candleviewer.exchange.base.models import PlaceOrderRequest, TradingStopRequest
from candleviewer.exchange.bybit.config import EndpointClass
from spike.oms_demo_path.safety import Refused
from spike.sl_attach.arms import prices
from spike.sl_attach.config import ArmConfig
from spike.sl_attach.tests._rig import Rig, error


async def test_arm_a_attaches_the_stop_on_the_create_and_times_its_ack(tmp_path: Path) -> None:
    rig = Rig(tmp_path, create_delay_s=0.03)
    await rig.up()
    [sample] = await rig.drive(lambda: rig.runner.run("a", 1))
    [opener, close] = rig.venue.creates
    _, stop, _ = prices(rig.runner.cfg, rig.venue.ref, "buy")
    assert opener["stopLoss"] == str(stop) and opener["slTriggerBy"] == "MarkPrice"
    assert opener["tpslMode"] == "Full" and opener["reduceOnly"] is False
    assert close["reduceOnly"] is True and "stopLoss" not in close
    assert rig.venue.stop_writes == []
    assert sample.outcome == "ok" and sample.discard_reason is None
    assert sample.ack_ms == pytest.approx(30.0) and sample.rtt_ms == pytest.approx(30.0)
    assert sample.overhead_ms == pytest.approx(0.0) and sample.attempts == 1
    assert sample.protected_lag_ms == 0.0 and sample.skew_ms is not None
    assert sample.requests_order_class == 1 and sample.requests_position_class == 0
    assert sample.ret_code == 0 and sample.s86_code is None and sample.order_ref.startswith("link#")
    assert rig.venue.size == 0  # closed


async def test_arm_b_opens_with_the_backstop_then_tightens_on_the_first_execution(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, create_delay_s=0.03, stop_delay_s=0.12)
    await rig.up()
    [sample] = await rig.drive(lambda: rig.runner.run("b", 1))
    _, stop, backstop = prices(rig.runner.cfg, rig.venue.ref, "buy")
    opener = rig.venue.creates[0]
    assert opener["stopLoss"] == str(backstop)  # never naked (Q5, C-2.6)
    assert backstop <= rig.venue.ref * Decimal("0.95") and backstop >= rig.venue.ref * Decimal(
        "0.90"
    )
    [write] = rig.venue.stop_writes
    assert write["stopLoss"] == str(stop) and write["tpslMode"] == "Full"
    assert write["slTriggerBy"] == "MarkPrice" and "takeProfit" not in write
    stop_lanes = [a[2] for a in rig.governor.acquired if a[1] == EndpointClass.POSITION]
    assert stop_lanes == ["critical"]
    assert sample.outcome == "ok" and sample.stage == "trading_stop"
    # the fill and its push at t, the stop applied at t + 60 ms (the venue's `time`), its 200
    # at t + 120 ms: all on the exchange clock
    assert sample.exposure_ms == pytest.approx(120.0)
    assert sample.exposure_venue_ms == pytest.approx(60.0)
    assert sample.push_lag_ms == pytest.approx(0.0) and sample.react_ms == pytest.approx(0.0)
    assert sample.stop_rtt_ms == pytest.approx(120.0) and sample.attempts == 1
    assert sample.requests_order_class == 1 and sample.requests_position_class == 1
    assert rig.venue.size == 0 and rig.port.protected == {}


async def test_the_stop_is_sent_on_the_push_before_the_create_returns(tmp_path: Path) -> None:
    rig = Rig(tmp_path, create_delay_s=0.0, stop_delay_s=0.05)
    rig.ack_delay_s = 0.4  # the venue fills at once; its answer to the create comes late
    await rig.up()
    [sample] = await rig.drive(lambda: rig.runner.run("b", 1))
    assert sample.outcome == "ok" and sample.exposure_ms == pytest.approx(50.0)


async def test_a_push_for_another_order_never_triggers_the_stop(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    await rig.up()
    rig.venue.fill_foreign(Decimal("0.001"))
    seen = await rig.drive(lambda: rig.watch.wait(lambda: "mine" in rig.watch.first, 2.0))
    assert seen is False and len(rig.watch.first) == 1  # the foreign fill, under its own key
    assert rig.venue.stop_writes == []


async def test_a_skewed_sample_is_discarded(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    await rig.up()
    await rig.drive(rig.runner.measure_offset)
    rig.venue_skew_ms = 501  # the venue's clock jumps after the offset was taken
    sample = await rig.drive(lambda: rig.runner.sample_b(0))
    assert sample.outcome == "discarded" and sample.discard_reason == "skew"
    assert sample.skew_ms == pytest.approx(501.0)
    rig.venue_skew_ms = 500
    kept = await rig.drive(lambda: rig.runner.sample_b(1))
    assert kept.outcome == "ok" and kept.skew_ms == pytest.approx(500.0)


async def test_a_trading_stop_10016_is_retried_and_its_attempts_counted(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.venue.stop_answers = [error(10016, "Internal server error")]
    await rig.up()
    [sample] = await rig.drive(lambda: rig.runner.run("b", 1))
    assert sample.outcome == "ok" and sample.attempts == 2
    assert sample.requests_position_class == 2 and len(rig.venue.stop_writes) == 2


async def test_a_create_10016_is_ambiguous_and_never_resent(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.venue.create_answers = [error(10016, "Internal server error")]
    await rig.up()
    [sample] = await rig.drive(lambda: rig.runner.run("a", 1))
    assert sample.outcome == "ambiguous" and sample.attempts == 1 and sample.stage == "create"
    assert sample.ret_code == 10016 and sample.adapter_error_code == "TRANSPORT_ERROR"
    assert sample.s86_code == "TRANSPORT_ERROR" and sample.taxonomy_divergent is False
    assert len(rig.venue.creates) == 1


async def test_a_refused_trading_stop_is_recorded_and_the_position_closed(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.venue.stop_answers = [
        error(10001, "params error: StopLoss set for Buy position should lower than base_price")
    ]
    await rig.up()
    [sample] = await rig.drive(lambda: rig.runner.run("b", 1))
    assert sample.outcome == "rejected" and sample.stage == "trading_stop"
    assert sample.ret_code == 10001 and sample.ret_msg_class == "other"
    assert (
        sample.adapter_error_code == "INSTRUMENT_FILTER" and sample.s86_code == "INSTRUMENT_FILTER"
    )
    assert rig.venue.size == 0  # the backstop held it until the close


async def test_the_guard_refuses_an_opener_without_a_stop(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    naked = PlaceOrderRequest(
        account=rig.account,
        symbol="BTCUSDT",
        side="buy",
        order_type="limit",
        qty=Decimal("0.002"),
        price=rig.venue.ask,
        order_link_id=rig.runner.links.new(),
    )
    with pytest.raises(Refused, match=r"C-2\.6"):
        await rig.port.place_order(naked)
    assert rig.venue.creates == [] and rig.tap.log == [] and rig.port.protected == {}


@pytest.mark.parametrize(
    ("stop", "match"),
    [(None, r"C-2\.6"), (Decimal(0), r"C-2\.6"), (Decimal(1), "loosens")],
)
async def test_the_guard_refuses_a_stop_write_that_removes_or_loosens(
    tmp_path: Path, stop: Decimal | None, match: str
) -> None:
    rig = Rig(tmp_path)
    rig.port.protected[("BTCUSDT", 0)] = ("buy", Decimal(50_000))
    request = TradingStopRequest.model_construct(
        account=rig.account, symbol="BTCUSDT", position_idx=0, stop_loss=stop, tpsl_mode="full"
    )
    with pytest.raises(Refused, match=match):
        await rig.port.set_trading_stop(request)
    rig.port.protected.clear()
    with pytest.raises(Refused, match="openers opened"):
        await rig.port.set_trading_stop(request)
    assert rig.venue.stop_writes == [] and rig.tap.log == []


def test_the_backstop_must_sit_five_to_ten_percent_away() -> None:
    for pct in ("4.99", "10.01"):
        with pytest.raises(Refused, match="5 to 10"):
            ArmConfig(backstop_pct=Decimal(pct))
    with pytest.raises(Refused, match="allow-list"):
        ArmConfig(symbol="SOLUSDT")
    with pytest.raises(Refused, match="tightens"):
        ArmConfig(sl_bps=Decimal(800), backstop_pct=Decimal(5))
