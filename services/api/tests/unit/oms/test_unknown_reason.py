"""E29-T08's `reason` on `oms_unknown_orders` (#916 BQ-7; 24-internal-schemas.md Sec.8.6; 20
Sec.12.1): the order facade derives why an order is in `unknown` from the step that moved it there,
its trigger and its new notices, B1 keeping none, with no chart change. Each of the closed four is
driven here through the real facade and B1 (`order_rig`): a create with no known outcome
(`transport`), a cancel the venue answered `110001` (`already_terminal`), a pass that found a live
row nowhere (`missing_remote`) and a duplicate-id create the full match has not verified
(`duplicate_unverified`). Every child exists at 0, so the series is never absent."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import AsyncIterator, Mapping
from typing import Any

import pytest

from candleviewer.exchange.base.errors import NotFoundError
from candleviewer.oms.order_machine import UNKNOWN_REASONS, unknown_reason
from candleviewer.statechart.bindings import b01_order as b01
from tests.unit.oms.order_rig import ACCOUNT, Rig, build_rig, order_of

_GAUGE = "oms_unknown_orders"


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Rig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())  # the binding's attempts, per test
    built = build_rig()
    yield built
    await built.facade.stop()


def _by_reason(rig: Rig) -> dict[str, float]:
    return {reason: rig.count(_GAUGE, reason=reason) for reason in UNKNOWN_REASONS}


def _only(reason: str) -> dict[str, float]:
    return {r: (1.0 if r == reason else 0.0) for r in UNKNOWN_REASONS}


def test_the_closed_set_is_the_four_the_ruling_names() -> None:
    assert UNKNOWN_REASONS == ("already_terminal", "missing_remote", "duplicate_unverified",
                               "transport")  # fmt: skip


@pytest.mark.parametrize(
    ("trigger", "notices", "needs_lookup", "reason"),
    [
        ("error.platform.cancel", [{"kind": "alert", "alert": "order_already_terminal"}], False,
         "already_terminal"),
        ("RECON_MISS", [{"kind": "alert", "alert": "order_unknown"}], False, "missing_remote"),
        ("done.invoke.place", [{"kind": "alert", "alert": "order_unknown"}], True,
         "duplicate_unverified"),
        ("error.platform.place", [{"kind": "alert", "alert": "order_unknown"}], False,
         "transport"),
        ("TRANSPORT_FAULT", [], False, "transport"),
        ("", [{"kind": "request_reconciliation"}], False, "transport"),  # nothing named: it pages
    ],
)  # fmt: skip
def test_the_reason_is_derived_from_the_trigger_and_the_new_notices(
    trigger: str, notices: list[Mapping[str, Any]], needs_lookup: bool, reason: str
) -> None:
    assert unknown_reason(trigger, notices, needs_lookup=needs_lookup) == reason


async def test_every_reason_exists_at_zero_before_any_order(rig: Rig) -> None:
    """A labelled gauge with no child exports nothing (BQ-7): the absent-series guard would fire."""
    assert _by_reason(rig) == dict.fromkeys(UNKNOWN_REASONS, 0.0)


async def test_a_create_with_no_known_outcome_counts_as_transport(rig: Rig) -> None:
    async def ambiguous(_command: b01.Command) -> Mapping[str, Any]:
        raise TimeoutError

    rig.commands.on_place = ambiguous
    order = order_of()
    await rig.start(order)
    await rig.facade.command(ACCOUNT, order.id, "SEND", actor="user")
    await rig.quiet()
    assert rig.facade.state(order.id) == ("unknown", "not_required")
    assert _by_reason(rig) == _only("transport")


async def test_a_cancel_the_venue_answered_110001_counts_as_already_terminal(rig: Rig) -> None:
    """24 Sec.8.6: B1 parks the order in `unknown`, ticketed; the page leaves it out."""

    async def gone(_command: b01.Command) -> Mapping[str, Any]:
        raise NotFoundError("no such order", exchange_ret_code=110001)

    order = await rig.submitted()
    rig.commands.on_cancel = gone
    await rig.facade.command(ACCOUNT, order.id, "CANCEL", actor="user")
    await rig.quiet()
    assert rig.facade.state(order.id) == ("unknown", "not_required")
    assert _by_reason(rig) == _only("already_terminal")


async def test_a_live_row_a_pass_found_nowhere_counts_as_missing_remote(rig: Rig) -> None:
    order = await rig.submitted()
    await rig.facade.command(ACCOUNT, order.id, "RECON_MISS", {"pass_id": "p1"}, actor="system")
    assert rig.facade.state(order.id) == ("unknown", "not_required")
    assert _by_reason(rig) == _only("missing_remote")


async def test_an_unverified_duplicate_create_counts_as_duplicate_unverified(rig: Rig) -> None:
    async def duplicate(_command: b01.Command) -> Mapping[str, Any]:
        return {"ok": False, "error_code": "DUPLICATE_CLIENT_ID"}

    rig.commands.on_place = duplicate
    order = order_of()
    await rig.start(order)
    await rig.facade.command(ACCOUNT, order.id, "SEND", actor="user")
    await rig.quiet()
    assert rig.facade.state(order.id) == ("unknown", "not_required")
    assert _by_reason(rig) == _only("duplicate_unverified")


async def test_the_reason_holds_while_the_order_stays_and_clears_when_it_leaves(rig: Rig) -> None:
    """A step that keeps the order in `unknown` keeps its reason; leaving, or the machine's
    eviction, takes it out of its child."""
    order = await rig.submitted()
    await rig.facade.command(ACCOUNT, order.id, "RECON_MISS", {"pass_id": "p1"}, actor="system")
    await rig.facade.command(ACCOUNT, order.id, "RECON_MISS", {"pass_id": "p2"}, actor="system")
    assert rig.facade.state(order.id) == ("unknown", "not_required")
    assert _by_reason(rig) == _only("missing_remote")
    found = {"exchange_order_id": "x1"}
    await rig.facade.command(ACCOUNT, order.id, "RECON_FOUND_LIVE", found, actor="system")
    assert _by_reason(rig) == dict.fromkeys(UNKNOWN_REASONS, 0.0)


async def test_a_restart_rebuilds_the_reason_from_the_replayed_steps(rig: Rig) -> None:
    order = await rig.submitted()
    await rig.facade.command(ACCOUNT, order.id, "RECON_MISS", {"pass_id": "p1"}, actor="system")
    restarted = await rig.restart()
    try:
        assert await restarted.facade.hydrate(ACCOUNT, order.id, environment="demo") == "unknown"
        assert _by_reason(restarted) == _only("missing_remote")
    finally:
        await restarted.facade.stop()
