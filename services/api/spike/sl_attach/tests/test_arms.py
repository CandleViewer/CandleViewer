# ruff: noqa: S101  (pytest asserts: the project's tests/** ignore does not reach spike/)
"""Both arms over the corpus venue, the real port and the real private stream, on a virtual
clock (#856 Scope; the Q5 ruling): the wiring, the timing on the venue's scripted clock, the
taxonomy each sample records, and the guard."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

import pytest

from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.models import (
    AccountRef,
    OrderAck,
    PlaceOrderRequest,
    TradingStopRequest,
)
from candleviewer.exchange.bybit.config import EndpointClass
from spike.oms_demo_path.safety import QtyLimits, Refused
from spike.oms_demo_path.scrub import Scrubber
from spike.sl_attach import arms
from spike.sl_attach.arms import HeldFloor, RunHalted, SlGuardedPort, _costs, prices
from spike.sl_attach.config import ArmConfig
from spike.sl_attach.results import Sample
from spike.sl_attach.tests._rig import MemoryLedger, Rig, error
from spike.sl_attach.timing import Exchanged
from tests._signing import CREDENTIAL_ID

if TYPE_CHECKING:
    from candleviewer.domain.primitives import Side
    from candleviewer.exchange.base.ports import TradingPort


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
    assert sample.port_parse_ms == 0.0
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


def _lookups(rig: Rig) -> list[float]:
    return [e.sent_wall_ms for e in rig.tap.log if e.path == "/v5/order/realtime"]


async def test_a_create_10016_never_final_halts_at_the_lookup_count(tmp_path: Path) -> None:
    """D1: an ambiguous create the venue never shows is looked up `lookup_tries` times, then the
    run halts with the floor kept; the sample is `stopped`, never `ok`, and never resent."""
    cfg = ArmConfig(lookup_tries=3, lookup_every_s=0.25, lookup_wait_s=10.0)
    rig = Rig(tmp_path, cfg=cfg)
    rig.venue.create_answers = [error(10016, "Internal server error")]
    await rig.up()
    with pytest.raises(RunHalted, match="not final"):
        await rig.drive(lambda: rig.runner.run("a", 1))
    [sample] = rig.runner.samples
    assert sample.outcome == "discarded" and sample.discard_reason == "stopped"
    assert sample.attempts == 1 and sample.stage == "create"
    assert sample.ret_code == 10016 and sample.adapter_error_code == "TRANSPORT_ERROR"
    assert sample.s86_code == "TRANSPORT_ERROR" and sample.taxonomy_divergent is False
    assert len(rig.venue.creates) == 1 and ("BTCUSDT", 0) in rig.port.protected
    sent = _lookups(rig)
    assert len(sent) == 3 and sent[-1] - sent[0] == pytest.approx(500.0)


async def test_the_lookups_stop_at_their_total_wait(tmp_path: Path) -> None:
    cfg = ArmConfig(lookup_tries=100, lookup_every_s=0.25, lookup_wait_s=1.0)
    rig = Rig(tmp_path, cfg=cfg)
    rig.venue.create_answers = [error(10016, "Internal server error")]
    await rig.up()
    with pytest.raises(RunHalted, match="not final"):
        await rig.drive(lambda: rig.runner.run("b", 1))
    sent = _lookups(rig)
    assert len(sent) == 5 and sent[-1] - sent[0] == pytest.approx(1000.0)
    assert rig.runner.samples[0].discard_reason == "stopped" and rig.port.protected != {}


@pytest.mark.parametrize("rest_s", [0.0, 0.3])
async def test_an_ambiguous_create_then_a_late_fill_is_closed_before_the_next_opener(
    tmp_path: Path, rest_s: float
) -> None:
    """D1's reproduction: the create answers 10016 before the venue acts, the venue fills it
    100 ms later (on r1, inside arm (b)'s next sample, which then closed 0.004); the run now
    closes that fill before arm (b)'s next opener is sent. With `rest_s`, the order is seen
    `New` (not final) before it fills."""
    rig = Rig(tmp_path)
    rig.venue.create_late = [error(10016, "Internal server error")]
    rig.late_s, rig.rest_s = 0.1, rest_s
    await rig.up()

    async def both() -> list[Sample]:
        return [*await rig.runner.run("a", 1), *await rig.runner.run("b", 1)]

    [first, second] = await rig.drive(both)
    assert first.outcome == "ambiguous" and first.stage == "create" and first.ret_code == 10016
    creates = rig.venue.creates
    assert [c["reduceOnly"] for c in creates] == [False, True, False, True]
    assert [c["qty"] for c in creates] == ["0.002"] * 4
    assert second.outcome == "ok" and second.stage == "trading_stop" and second.stop_landed
    assert rig.venue.size == 0 and rig.port.protected == {}


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


ACCOUNT = AccountRef(
    account_id=AccountId(uuid4()), uid="spike", environment="demo", key_ref=str(CREDENTIAL_ID)
)


def test_an_order_lookup_is_a_read_not_an_order_class_request() -> None:
    """m5: a `GET /v5/order/realtime` counts once, as a read."""
    log = [
        Exchanged("/v5/order/create", "POST", 0.0, 1.0, None, 0, 200),
        Exchanged("/v5/order/realtime", "GET", 1.0, 2.0, None, 0, 200),
        Exchanged("/v5/position/trading-stop", "POST", 2.0, 3.0, None, 0, 200),
    ]
    assert _costs(log) == {
        "requests_order_class": 1,
        "requests_position_class": 1,
        "requests_reads": 1,
    }


class StopOnly:
    """A port double for the guard's own tests: a stop write is acked and kept; any other call
    fails at once, so a mutated-away check fails its test instead of reaching a venue (N3)."""

    def __init__(self) -> None:
        self.writes: list[TradingStopRequest] = []

    async def set_trading_stop(self, req: TradingStopRequest) -> OrderAck:
        self.writes.append(req)
        return OrderAck(
            ok=True, order_link_id=None, exchange_order_id=None, latency_ms=1, transport="rest"
        )

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the guard let {name} through")


def _guard(tmp: Path) -> tuple[SlGuardedPort, StopOnly]:
    double = StopOnly()
    port = SlGuardedPort(cast("TradingPort", double))
    step = Decimal("0.001")
    port.limits = QtyLimits(step, step, Decimal("0.010"))
    port.ledger = MemoryLedger(tmp, Scrubber(), elapsed=lambda: 0.0)
    return port, double


def _write(stop: Decimal | None, **fields: object) -> TradingStopRequest:
    return TradingStopRequest.model_construct(
        account=ACCOUNT, symbol="BTCUSDT", position_idx=0, stop_loss=stop, tpsl_mode="full"
    ).model_copy(update=fields)


def _opener(side: Side, stop: Decimal, qty: str = "0.002") -> PlaceOrderRequest:
    price = Decimal(50_000)
    return PlaceOrderRequest(
        account=ACCOUNT,
        symbol="BTCUSDT",
        side=side,
        order_type="limit",
        qty=Decimal(qty),
        price=price,
        order_link_id="link-guard-1",
        stop_loss=stop,
        sl_trigger_by="mark",
        tpsl_mode="full",
    )


#: (side, the floor, a write that loosens it, one that tightens it)
SIDES: list[tuple[Side, Decimal, Decimal, Decimal]] = [
    ("buy", Decimal(46_250), Decimal(46_000), Decimal(49_750)),
    ("sell", Decimal(53_750), Decimal(54_000), Decimal(50_250)),
]


@pytest.mark.parametrize(("side", "floor", "loose", "tight"), SIDES)
@pytest.mark.parametrize("kind", ["none", "zero", "loosens"])
async def test_the_guard_refuses_a_stop_write_that_removes_or_loosens(
    tmp_path: Path, side: Side, floor: Decimal, loose: Decimal, tight: Decimal, kind: str
) -> None:
    port, double = _guard(tmp_path)
    port.protected[("BTCUSDT", 0)] = (side, floor)
    stop = {"none": None, "zero": Decimal(0), "loosens": loose}[kind]
    with pytest.raises(Refused, match="loosens" if kind == "loosens" else r"C-2\.6"):
        await port.set_trading_stop(_write(stop))
    port.protected.clear()
    with pytest.raises(Refused, match="openers opened"):
        await port.set_trading_stop(_write(tight))
    assert double.writes == []


@pytest.mark.parametrize(("side", "floor", "loose", "tight"), SIDES)
async def test_the_floor_rises_with_each_tighten(
    tmp_path: Path, side: Side, floor: Decimal, loose: Decimal, tight: Decimal
) -> None:
    """M2: after a tighten, a write between the backstop and the tightened stop loosens."""
    port, double = _guard(tmp_path)
    port.protected[("BTCUSDT", 0)] = (side, floor)
    await port.set_trading_stop(_write(tight))
    assert port.protected[("BTCUSDT", 0)] == (side, tight)
    await port.set_trading_stop(_write(tight))  # the same stop again: admitted
    between = (floor + tight) / 2
    with pytest.raises(Refused, match="loosens"):
        await port.set_trading_stop(_write(between))
    assert [w.stop_loss for w in double.writes] == [tight, tight]


@pytest.mark.parametrize("fields", [{"tpsl_mode": "partial"}, {"trailing_distance": Decimal(100)}])
async def test_the_guard_refuses_a_partial_or_trailing_stop_write(
    tmp_path: Path, fields: dict[str, object]
) -> None:
    port, double = _guard(tmp_path)
    port.protected[("BTCUSDT", 0)] = ("buy", Decimal(46_250))
    with pytest.raises(Refused, match="Full-mode"):
        await port.set_trading_stop(_write(Decimal(49_750), **fields))
    assert double.writes == []


@pytest.mark.parametrize("side", ["buy", "sell"])
async def test_the_guard_refuses_any_opener_while_a_floor_is_held(
    tmp_path: Path, side: Side
) -> None:
    """M1: a live floor (a long's) refuses a same-side opener and an opposite-side one."""
    port, _ = _guard(tmp_path)
    port.protected[("BTCUSDT", 0)] = ("buy", Decimal(49_750))
    stop = Decimal(46_250) if side == "buy" else Decimal(53_750)
    with pytest.raises(HeldFloor, match="not proven flat"):
        await port.place_order(_opener(side, stop))
    assert port.protected == {("BTCUSDT", 0): ("buy", Decimal(49_750))}


async def test_a_refused_opener_leaves_no_floor(tmp_path: Path) -> None:
    """M2 (mutant 1): an opener the guard refuses after its floor was noted takes it back."""
    port, _ = _guard(tmp_path)
    with pytest.raises(Refused, match="off the step"):
        await port.place_order(_opener("buy", Decimal(46_250), qty="0.0015"))
    assert port.protected == {}


async def test_a_refused_close_halts_the_run_and_keeps_the_floor(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.venue.close_answers = [error(110017, "current position is zero, cannot fix reduce-only")]
    await rig.up()
    with pytest.raises(RunHalted, match="refused") as halted:
        await rig.drive(lambda: rig.runner.run("b", 2))
    [sample] = rig.runner.samples
    assert halted.value.sample == sample and sample.discard_reason == "stopped"
    assert rig.venue.size > 0 and ("BTCUSDT", 0) in rig.port.protected
    with pytest.raises(HeldFloor):
        await rig.drive(lambda: rig.runner.sample_b(1))
    assert len(rig.venue.creates) == 2  # the opener and the refused close, nothing after


async def test_a_position_still_held_after_the_close_halts_the_run(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.venue.close_unfilled = True
    await rig.up()
    with pytest.raises(RunHalted, match="still held"):
        await rig.drive(lambda: rig.runner.run("a", 1))
    assert rig.runner.samples[0].discard_reason == "stopped" and rig.port.protected != {}


async def test_a_lost_fill_push_is_no_fill_and_the_leftover_closed(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.venue.drop_every = 1  # every execution push is lost; the position push still comes
    await rig.up()
    samples = await rig.drive(lambda: rig.runner.run("b", 2))
    assert [s.discard_reason for s in samples] == ["no_fill", "no_fill"]
    assert [c["reduceOnly"] for c in rig.venue.creates] == [False, True, False, True]
    assert rig.venue.size == 0 and rig.port.protected == {} and rig.venue.stop_writes == []


async def test_an_ambiguous_create_that_filled_is_closed(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.venue.create_after = [error(10016, "Internal server error")]
    await rig.up()
    [sample] = await rig.drive(lambda: rig.runner.run("a", 1))
    assert sample.outcome == "ambiguous" and sample.discard_reason is None
    [_, close] = rig.venue.creates
    assert close["reduceOnly"] is True and close["qty"] == "0.002"
    assert rig.venue.size == 0 and rig.port.protected == {}


async def test_a_raised_position_read_in_the_flatten_halts_with_the_floor(tmp_path: Path) -> None:
    """D3: the self-check reads, then the flatten's read raises: `stopped`, the floor held."""
    rig = Rig(tmp_path)
    rig.venue.position_answers = [None, error(10001, "params error")]
    await rig.up()
    with pytest.raises(RunHalted, match="position read raised"):
        await rig.drive(lambda: rig.runner.run("b", 2))
    [sample] = rig.runner.samples
    assert sample.discard_reason == "stopped" and sample.stop_landed is True
    assert rig.venue.size > 0 and ("BTCUSDT", 0) in rig.port.protected
    assert [c["reduceOnly"] for c in rig.venue.creates] == [False]  # no close, no next opener


async def test_a_raised_self_check_read_is_incomplete(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.venue.position_answers = [error(10001, "params error")]
    await rig.up()
    [sample] = await rig.drive(lambda: rig.runner.run("b", 1))
    assert sample.discard_reason == "incomplete" and sample.stop_landed is False
    assert rig.venue.size == 0 and rig.port.protected == {}


async def test_a_guard_refused_stop_write_is_a_recorded_discard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D3: a measured stop the guard refuses (here one that would loosen the backstop) ends
    the sample `refused` (never landed), the position flattened before the floor is freed."""

    def loose(cfg: ArmConfig, ref: Decimal, side: Side) -> tuple[Decimal, Decimal, Decimal]:
        price, _, backstop = prices(cfg, ref, side)
        return price, backstop - Decimal(10) if side == "buy" else backstop + 10, backstop

    monkeypatch.setattr(arms, "prices", loose)
    rig = Rig(tmp_path)
    await rig.up()
    [sample] = await rig.drive(lambda: rig.runner.run("b", 1))
    assert sample.outcome == "discarded" and sample.discard_reason == "refused"
    assert sample.stage == "trading_stop" and sample.ret_msg_class == "guard"
    assert sample.stop_landed is False and rig.venue.stop_writes == []
    assert rig.venue.size == 0 and rig.port.protected == {}


async def test_the_close_takes_the_held_qty_not_the_configured_one(tmp_path: Path) -> None:
    """N1: a leftover of two fills (0.001 held, then the opener's 0.002) closes as 0.003."""
    rig = Rig(tmp_path)
    rig.venue.hold_foreign_position(Decimal("0.001"))
    await rig.up()
    await rig.drive(lambda: rig.runner.run("a", 1))
    [_, close] = rig.venue.creates
    assert close["reduceOnly"] is True and close["qty"] == "0.003"
    assert rig.venue.size == 0 and rig.port.protected == {}


def test_the_backstop_must_sit_five_to_ten_percent_away() -> None:
    for pct in ("4.99", "10.01"):
        with pytest.raises(Refused, match="5 to 10"):
            ArmConfig(backstop_pct=Decimal(pct))
    with pytest.raises(Refused, match="allow-list"):
        ArmConfig(symbol="SOLUSDT")
    with pytest.raises(Refused, match="tightens"):
        ArmConfig(sl_bps=Decimal(800), backstop_pct=Decimal(5))
    for bad in ({"lookup_tries": 0}, {"lookup_every_s": 0.0}, {"lookup_wait_s": 0.0}):
        with pytest.raises(Refused, match="bounded"):
            ArmConfig(**bad)
