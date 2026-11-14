"""The meta-test (E29-Q04 #1148, "Test plan": the suite has teeth). Each scenario that depends on
the reconciliation pass runs over the composed pass, where the oracle finds the book equal to the
venue, and over the stand-ins the runtime composes without E29-T06's stores
(`World(handover_store=None, reconcile_reads=None)`: `NoReconciliation`, `NoHandoverStore`), where
the oracle must fail it, naming the fields that differ, two cycles on: neither run passes
vacuously. Without the pass, s5's order stays `unknown` and unbound beside the venue's order (and
its fill and position, once filled); s6's stays `unknown` with no order at the venue; s7's gap
fill never reaches the book; s8's order stays `unknown` through the storm. s4b's book is the
venue's either way, as S6 changes nothing: the pass adds the anomaly's report, alerted and
recorded with it, neither without it.

Each scenario that does not depend on the pass has its negative control: its defence removed, the
outcome it forbids happens. s9: the resumed create's lookup skipped, the venue refuses the
re-send's reused id and the lookup and full match after it still bind the one order, but the venue
counted two creates, which the oracle fails. s10 with no clock halt, s11 with no IP hold, and s13
with a writer that drops what a full log cannot hold (fail open): the create each refuses reaches
the venue."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest

from candleviewer.exchange.base.models import PlaceOrderRequest
from candleviewer.exchange.bybit.rate_limit import TokenBucketGovernor
from candleviewer.oms import commands
from candleviewer.oms.clock_halt import ClockHalt
from candleviewer.oms.order_link_resolution import PlacementPort, PlaceOutcome, place_or_adopt
from candleviewer.oms.reconcile_job import INTERVAL_S, JITTER_S
from tests.chaos.oms._oracle import OracleMismatch, check
from tests.chaos.oms._world import Wal, World, opened
from tests.chaos.oms.test_s4b_post_terminal_pass import ANOMALY, ended_unread
from tests.chaos.oms.test_s5_post_send_timeout import lost_ack
from tests.chaos.oms.test_s6_unresolved_after_reconcile import never_landed
from tests.chaos.oms.test_s7_private_stream_gap import gap
from tests.chaos.oms.test_s8_reconnect_storm import storm
from tests.chaos.oms.test_s9_duplicate_acks import SENDING, crashed
from tests.chaos.oms.test_s10_clock_drift import drifted
from tests.chaos.oms.test_s11_ip_rate_limit import governed, held
from tests.chaos.oms.test_s13_audit_wal_full import ALARM, full
from tests.unit.audit.audit_waits import virtual

pytestmark = pytest.mark.chaos


async def resting(world: World) -> UUID:
    return await lost_ack(world, filled=False)


async def filled(world: World) -> UUID:
    return await lost_ack(world, filled=True)


#: Each scenario's faults, and the (item, field) pairs the oracle names without the pass.
SCENARIOS: dict[str, tuple[Callable[[World], Awaitable[object]], set[tuple[str, str]]]] = {
    "s5-resting": (resting, {("order", "exchange_order_id"), ("order", "lifecycle_state")}),
    "s5-filled": (filled, {
        ("order", "exchange_order_id"), ("order", "lifecycle_state"), ("order", "filled_qty"),
        ("execution", "exec_id"), ("position", "open"),
    }),
    "s6": (never_landed, {("order", "venue order")}),
    "s7": (gap, {
        ("order", "lifecycle_state"), ("order", "filled_qty"), ("order", "executions"),
        ("execution", "exec_id"), ("position", "size"),
    }),
    "s8": (storm, {("order", "exchange_order_id"), ("order", "lifecycle_state")}),
}  # fmt: skip
#: The scenarios on the account's private stream.
STREAMED = frozenset({"s7", "s8"})
STAND_INS: dict[str, Any] = {"handover_store": None, "reconcile_reads": None}


@pytest.mark.parametrize("name", SCENARIOS)
@pytest.mark.parametrize("composed", [True, False], ids=["pass", "stand-ins"])
@virtual
async def test_the_oracle_fails_a_scenario_only_without_the_pass(name: str, composed: bool) -> None:
    drive, named = SCENARIOS[name]
    async with opened(streamed=name in STREAMED, **({} if composed else STAND_INS)) as world:
        await drive(world)
        await world.elapse(2 * INTERVAL_S + JITTER_S)
        if composed:
            await check(world)
            return
        with pytest.raises(OracleMismatch) as raised:
            await check(world)
        assert named <= {(d.item.split()[0], d.field) for d in raised.value.diffs}


@pytest.mark.parametrize("composed", [True, False], ids=["pass", "stand-ins"])
@virtual
async def test_s4bs_anomaly_is_reported_by_the_pass_alone_and_changes_nothing(
    composed: bool,
) -> None:
    async with opened(streamed=True, **({} if composed else STAND_INS)) as world:
        _, ended = await ended_unread(world)
        await world.elapse(2 * INTERVAL_S + JITTER_S)
        alerted = ANOMALY in world.raised("alert")
        listed = any(ended.order_link_id in r["anomalies"] for r in world.reports())
        assert (alerted, listed) == (composed, composed)
        world.exchange.settle(ended)
        await world.elapse(INTERVAL_S)
        await check(world)


async def unfound(_port: object, _request: object) -> None:
    """A lookup that reads nothing: B1's before a create it did not begin, and its resume's."""


async def resent(port: PlacementPort, request: PlaceOrderRequest, **_: object) -> PlaceOutcome:
    """`adopt_or_resend` with its own lookup skipped: the create sent again at once."""
    return await place_or_adopt(port, request)


@virtual
async def test_s9_without_the_resumed_creates_lookups_the_venue_counts_two_creates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(commands, "find_by_link_id", unfound)
    monkeypatch.setattr(commands, "adopt_or_resend", resent)
    async with opened(before=crashed) as world:
        row = await world.row(SENDING.id)  # the venue refused the reused id; looked up, bound
        venue = await world.exchange.order(SENDING.order_link_id)
        assert (row.lifecycle_state, row.exchange_order_id) == (
            "submitted",
            venue.exchange_order_id,
        )
        with pytest.raises(OracleMismatch) as raised:
            await check(world)
        assert {(d.item, d.field, d.venue) for d in raised.value.diffs} == {
            (f"order {SENDING.order_link_id}", "creates", 2)
        }


@virtual
async def test_s10_without_the_clock_halt_the_create_it_refuses_reaches_the_venue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ClockHalt, "refusal", lambda _halt: None)
    async with opened() as world:
        await drifted(world)
        outcome = await world.submit()
        assert (outcome.status, len(world.exchange.creates())) == (202, 2)
        await check(world)


@virtual
async def test_s11_without_the_ip_hold_the_create_it_refuses_reaches_the_venue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(TokenBucketGovernor, "hold_ip", lambda _governor, _s: None)
    async with opened(streamed=True, venue=governed()) as world:
        await held(world)
        outcome = await world.submit()
        assert (outcome.status, len(world.exchange.creates())) == (202, 2)
        await check(world)


@virtual
async def test_s13_a_writer_that_drops_what_a_full_log_cannot_hold_lets_the_create_out() -> None:
    async with opened(streamed=True, writer=Wal(refuses=False)) as world:
        await full(world)
        outcome = await world.submit()
        assert (outcome.status, len(world.exchange.creates())) == (202, 2)
        assert ALARM not in world.raised("page")
        await check(world)
