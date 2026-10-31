"""E29-S03 (#978) acceptance: the partial close's five Gherkin scenarios by name, on the real
submission pipeline (`submit_rig`: `OrderSubmission` over the real B1 facade and the venue's
`FakeTradingPort`), each close sized as the route's step 13 sizes it (`resolve_close`) and marked
`protective` as the close route marks it.

The native stop (C-2.6) as the orchestrator ruled BQ-1 (option A): a partial close sends exactly
one reduce-only create and no stop write or cancel; the remainder's position push reads
`SL_OBSERVED`, and a remainder with no stop reads `SL_LOST`, which pages; a refusal sends nothing;
and no order these tests send could open a position (every create reduce-only, none with a stop).

The 110017 race reuses the plan-origin `accounts/close_rejected` fixture, its own stub answering
the reduce-only create, mapped by the adapter's own table (BQ-7 as ruled), until E29-K01 records a
reply: this test invents no payload shape. No network (C-13.5)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

import pytest

from candleviewer.domain.events import Instrument
from candleviewer.exchange.base.fakes import FakeReject
from candleviewer.exchange.base.models import PlaceOrderRequest, Position
from candleviewer.exchange.bybit.mapping import map_ret_code
from candleviewer.oms.errors import OrderInvalid, PositionChanged
from candleviewer.oms.ports import NoPositionProtection
from candleviewer.oms.position_writes import (
    CloseSize,
    CloseTerms,
    close_request,
    resolve_close,
)
from candleviewer.oms.push_mapping import reading
from candleviewer.oms.submit import SubmitOutcome
from candleviewer.storage.repositories.positions import PositionRow
from tests._account_fixtures import load
from tests.unit.api.oms_reads_world import position as stored
from tests.unit.audit.audit_waits import virtual
from tests.unit.oms import command_rig as cr
from tests.unit.oms import position_rig as pr
from tests.unit.oms.submit_rig import SYMBOL, SubmitRig, context, instrument, rigged

#: The close as the route sends it: `closePosition`'s anchor, marked protective (C-2.6).
CLOSING = replace(context(), operation="closePosition", protective=True)
HALF = CloseTerms("market", pct=Decimal(50))
T0 = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)


@pytest.fixture
async def rig() -> AsyncIterator[SubmitRig]:
    async with rigged() as built:
        yield built


def held(size: str, *, side: Literal["Buy", "Sell"] = "Buy", idx: int = 0) -> PositionRow:
    """The stored row the route admitted: `size` BTCUSDT on the rig's demo account."""
    return stored(1, cr.ACCOUNT, side=side, size=Decimal(size), position_idx=idx)


def venue(
    size: str, *, side: Literal["buy", "sell"] = "buy", idx: Literal[0, 1, 2] = 0
) -> Position:
    """The venue's position, its Full-mode native stop on it (C-2.6)."""
    stop = cr.STOP if side == "buy" else Decimal("62000")
    return cr.position(qty=size, side=side, position_idx=idx, stop_loss=stop)


def lot(rig: SubmitRig, **figures: str) -> Instrument:
    """The rig's BTCUSDT with `figures` (its `qty_step` and `min_order_qty`), as both read it."""
    listed = instrument(**{name: Decimal(value) for name, value in figures.items()})
    rig.instruments.listed[SYMBOL] = listed
    return listed


async def close(
    rig: SubmitRig, row: PositionRow, terms: CloseTerms = HALF
) -> tuple[CloseSize, SubmitOutcome]:
    """Step 13's size, then the close through the pipeline, as the route sends it."""
    size = resolve_close(row, terms, rig.instruments.listed[SYMBOL])
    return size, await rig.pipeline.submit(close_request(row, terms, size.qty), CLOSING)


def creates(rig: SubmitRig) -> list[PlaceOrderRequest]:
    return [c.request for c in rig.port.demo.calls if c.method == "place_order"]


def assert_never_opens(rig: SubmitRig) -> None:
    """C-2.6 (the ruling's assertion): no position-opening order; every close reduce-only."""
    assert all(c.reduce_only and c.stop_loss is None and c.lane == "critical" for c in creates(rig))


def close_rejected() -> FakeReject:
    """The plan-origin `close_rejected` scenario's answer to a reduce-only create (its stub
    matches `reduceOnly: true`), through the adapter's own mapping of its code."""
    body = (
        load("close_rejected", now=T0)
        .reply("POST", "/v5/order/create", body={"reduceOnly": True})
        .body
    )
    mapped = map_ret_code(body["retCode"], body["retMsg"], create=True)
    return FakeReject(mapped.code, exchange_ret_code=body["retCode"],
                      exchange_ret_msg=body["retMsg"])  # fmt: skip


# --- Scenario: Percentage close ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("step", "sent", "rounded"), [("0.001", "0.125", False), ("0.01", "0.12", True)]
)
async def test_scenario_percentage_close_sends_the_floored_half_reduce_only_as_flatten(
    rig: SubmitRig, step: str, sent: str, rounded: bool
) -> None:
    """Given a long position of 0.250 BTC, when I choose 50 %, then a reduce-only order for 0.125
    rounded to the lot size is submitted with purpose flatten, on the critical lane."""
    lot(rig, qty_step=step, min_order_qty=step)
    rig.port.demo.seed_position(venue("0.250"))
    size, outcome = await close(rig, held("0.250"))
    assert (size.qty, size.rounded, size.remaining) == (
        Decimal(sent),
        rounded,
        Decimal("0.250") - Decimal(sent),
    )
    assert outcome.status == 202 and outcome.order_id is not None
    [create] = creates(rig)
    assert (create.side, create.qty, create.reduce_only) == ("sell", Decimal(sent), True)
    assert rig.store._orders[outcome.order_id].intent == "flatten"
    assert_never_opens(rig)


# --- Scenario: Protective quantities follow the remainder (BQ-1 option A as ruled) -----------


async def test_scenario_protective_quantities_follow_the_remainder_one_create_no_stop_write(
    rig: SubmitRig,
) -> None:
    """The partial close sends exactly one reduce-only create, with no trading-stop write and no
    cancel: the Full-mode stop on the position covers whatever remains, so no protective order is
    ever sized larger than the position (C-2.6); resizing a Partial-mode stop is E32-S02's."""
    rig.port.demo.seed_position(venue("0.250"))
    _size, outcome = await close(rig, held("0.250"))
    assert outcome.status == 202
    assert rig.calls() == ["positions", "place_order"]  # the venue's read, then the create alone
    assert_never_opens(rig)


@virtual
async def test_scenario_protective_quantities_follow_the_remainder_its_push_reads_sl_observed() -> (
    None
):
    """The remainder's push keeps the position's own stop: `SL_OBSERVED`, its size the
    remainder's, and nothing pages."""
    remainder = pr.position(qty=Decimal("0.125"), stop_loss=cr.STOP)
    shown = reading(remainder)
    assert (shown.event, shown.size, shown.stop_loss) == ("SL_OBSERVED", Decimal("0.125"), cr.STOP)
    projection = pr.Rig()
    await projection.take(remainder, readings=NoPositionProtection())
    assert projection.pages == [] and "reading_unavailable" not in projection.counts


@virtual
async def test_native_sl_a_remainder_with_no_stop_reads_sl_lost_and_pages() -> None:
    """A remainder the push shows with no stop is `SL_LOST`: no machine protects it until
    E32-T02, so `NoPositionProtection` refuses it and the projection pages P1 (C-2.6)."""
    lost = pr.position(qty=Decimal("0.125"), stop_loss=None)
    assert reading(lost).event == "SL_LOST"
    projection = pr.Rig()
    await projection.take(lost, readings=NoPositionProtection())
    assert len(projection.pages) == 1 and "reading_unavailable" in projection.counts


# --- Scenario: Rounding leaves dust ----------------------------------------------------------


async def test_scenario_rounding_leaves_dust_refused_before_any_exchange_call(
    rig: SubmitRig,
) -> None:
    """Given closing 50 % would leave a remainder below the symbol's minimum order quantity, then
    the request is refused `dust_remainder` before any exchange call, naming the remainder so a
    client offers the full close, which is then sent whole (a full close is never refused)."""
    listed = lot(rig, qty_step="0.01", min_order_qty="0.1")
    rig.port.demo.seed_position(venue("0.15"))
    with pytest.raises(OrderInvalid) as refused:
        resolve_close(held("0.15"), HALF, listed)
    dust = refused.value.errors[0]
    assert (dust.rule, dust.remaining, dust.resolved, dust.limit) == (
        "dust_remainder",
        Decimal("0.08"),
        Decimal("0.07"),
        Decimal("0.1"),
    )
    assert rig.calls() == []  # refused before any exchange call
    size, outcome = await close(rig, held("0.15"), CloseTerms("market", pct=Decimal(100)))
    assert (size.qty, size.full, outcome.status) == (Decimal("0.15"), True, 202)
    assert_never_opens(rig)


# --- Scenario: Never reverses ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("shown", "rule"),
    [(("0.100", "buy"), "exceeds_position"), (None, "position_flat"),
     (("0.100", "sell"), "position_flat")],
    ids=["shrunk", "flat", "other_side"],
)  # fmt: skip
async def test_scenario_never_reverses_a_position_that_moved_before_the_send_is_refused_unsent(
    rig: SubmitRig, shown: tuple[str, Any] | None, rule: str
) -> None:
    """Given the position shrank (or closed) between the request and the send, the venue's read
    refuses the close before anything is recorded or sent, and its size is never re-derived."""
    if shown is not None:
        rig.port.demo.seed_position(venue(shown[0], side=shown[1]))
    with pytest.raises(PositionChanged) as refused:
        await close(rig, held("0.250"))
    assert [e.rule for e in refused.value.errors] == [rule]
    assert rig.calls() == ["positions"] and rig.written()[0] == 0  # nothing recorded or sent


async def test_scenario_never_reverses_a_close_the_venue_rejects_with_110017_opens_nothing(
    rig: SubmitRig,
) -> None:
    """The reduce-only flag makes the venue cap or reject the close (`close_rejected`'s 110017):
    the answer is a 502 with its return code alone, and no opposite-side position is opened."""
    rig.port.demo.seed_position(venue("0.250"))
    rig.port.demo.script("place_order", close_rejected())
    _size, outcome = await close(rig, held("0.250"))
    assert (outcome.status, outcome.code, outcome.ret_code) == (502, "exchange_error", 110017)
    assert_never_opens(rig)
    held_now = await rig.port.demo.positions(cr.ref())
    assert [(p.side, p.qty) for p in held_now] == [("buy", Decimal("0.250"))]


# --- Scenario: Hedge mode (BQ-6) ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("idx", "side", "closing", "other"), [(1, "Buy", "sell", 2), (2, "Sell", "buy", 1)]
)
async def test_scenario_hedge_mode_closes_only_the_requested_index_the_other_side_untouched(
    rig: SubmitRig, idx: Literal[1, 2], side: Literal["Buy", "Sell"], closing: str, other: int
) -> None:
    """Given a long on index 1 and a short on index 2 of one symbol, the close applies only to the
    requested index, from the stored row alone, and the other side's position and stop are left
    as they are: no create, stop write or cancel reaches it."""
    rig.port.demo.seed_position(venue("0.250", side="buy", idx=1))
    rig.port.demo.seed_position(venue("0.300", side="sell", idx=2))
    size = "0.250" if idx == 1 else "0.300"
    _size, outcome = await close(rig, held(size, side=side, idx=idx))
    assert outcome.status == 202
    [create] = creates(rig)
    assert (create.position_idx, create.side, create.reduce_only) == (idx, closing, True)
    assert rig.calls() == ["positions", "place_order"]
    untouched = next(p for p in await rig.port.demo.positions(cr.ref()) if p.position_idx == other)
    assert untouched.qty == Decimal("0.300" if other == 2 else "0.250")
    assert untouched.stop_loss is not None
    assert_never_opens(rig)


async def test_the_venue_read_refusal_is_a_close_routes_never_a_plain_reduce_only_orders(
    rig: SubmitRig,
) -> None:
    """A reduce-only order no close route marked protective, which the read does not show
    reducing, keeps the pipeline's own refusal as an entry (SR-E29-01), never `PositionChanged`."""
    plain = replace(CLOSING, protective=False)
    with pytest.raises(OrderInvalid) as refused:
        await rig.pipeline.submit(close_request(held("0.250"), HALF, Decimal("0.125")), plain)
    assert not isinstance(refused.value, PositionChanged)
    assert rig.calls() == ["positions"]
