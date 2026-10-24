"""The exit service's amend (E29-T04 slice 4, `oms.exits`; 22 `amendOrder`; rulings Q3 to Q5 and
Q10, the S4-A decisions D1 and D3): over the real B1 facade, the real command port and the fake
venue (`submit_rig`), the rig's limit buy entry resting `submitted` (0.010 at 60000, its stop
58000 and its take-profit 64000, Full mode, unfilled)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import fields
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.api.order_etag import NO_VERSION
from candleviewer.exchange.base.errors import OmsErrorCode
from candleviewer.exchange.base.fakes import FakeReject
from candleviewer.oms.errors import AccountScopeDenied, TradingDisabled
from candleviewer.oms.exits import AmendTerms, ExitCaller, risk_increasing
from candleviewer.oms.ports import StopOffset
from candleviewer.risk.models import RiskDecision, RiskRefusal
from candleviewer.storage.repositories.accounts import OwnerScope
from candleviewer.storage.repositories.orders import OrderRow, ScopedOrder
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr
from tests.unit.oms.submit_rig import SubmitRig
from tests.unit.oms.test_exits import OWNER, actor, exits_of, placed, requests

CALLER = ExitCaller(OwnerScope(OWNER), actor(OWNER))
D = Decimal


@pytest.fixture
async def rig() -> AsyncIterator[SubmitRig]:
    async with sr.rigged() as built:
        built.store.seed_owner(OWNER)
        yield built


async def scoped(rig: SubmitRig) -> ScopedOrder:
    """The rig's entry as the scope reads it, its leg's profile held under its id (D1's check)."""
    row = await placed(rig)
    got = await exits_of(rig).scope(CALLER, row.id)
    assert isinstance(got, ScopedOrder)
    rig.profiles.held[(cr.ACCOUNT, got.profile_id)] = sr.profile()
    return got


def amends(rig: SubmitRig) -> list[Any]:
    return [call.request for call in rig.port.demo.calls if call.method == "amend_order"]


_TICKS = StopOffset("ticks", D(10))


@pytest.mark.parametrize(
    ("over", "terms", "raises"),
    [
        ({}, AmendTerms(qty=D("0.011")), True),
        ({}, AmendTerms(qty=D("0.009")), False),
        ({"reduce_only": True}, AmendTerms(qty=D("0.011")), False),
        ({"price": D("60000")}, AmendTerms(price=D("61000")), True),
        ({"price": D("60000")}, AmendTerms(price=D("60000")), False),
        ({"reduce_only": True, "price": D("60000")}, AmendTerms(price=D("61000")), False),
        ({"trigger_price": D("61000")}, AmendTerms(trigger_price=D("61500")), True),
        ({"trigger_price": D("61000")}, AmendTerms(trigger_price=D("61000")), False),
        ({}, AmendTerms(trigger_price=D("61500")), True),
        ({}, AmendTerms(sides={"stop_loss": _TICKS, "take_profit": _TICKS}), False),
    ],
    ids=["qty-up", "qty-cut", "reduce-only-qty", "price-moved", "price-same",
         "reduce-only-price", "trigger-moved", "trigger-same", "trigger-added", "tp-and-sl"],
)  # fmt: skip
def test_risk_increasing_is_a_quantity_up_or_a_price_or_trigger_moved_on_an_entry(
    over: dict[str, Any], terms: AmendTerms, raises: bool
) -> None:
    """24 Sec.8.10, ruling Q10 (D5), SEC-S4A-01: every other amend is never gated (C-2.6)."""
    base: dict[str, Any] = dict.fromkeys(f.name for f in fields(OrderRow))
    base |= {"qty": D("0.010"), "reduce_only": False, "price": None, "trigger_price": None}
    assert risk_increasing(OrderRow(**(base | over)), terms) is raises


async def test_a_deep_limit_entry_repriced_to_a_marketable_price_is_gated_and_risk_checked(
    rig: SubmitRig,
) -> None:
    """SEC-S4A-01: the bid moved through the market (60000) fills at once, new exposure: it meets
    the flag, and D1's risk check on the amended order."""
    found, through = await scoped(rig), AmendTerms(price=D("61000"))
    off = await exits_of(rig, oms_enabled=lambda: False).amend(
        found, through, caller=CALLER, expected_seq=None
    )
    assert (off.status, off.code) == (403, "trading_disabled") and amends(rig) == []
    got = await exits_of(rig).amend(found, through, caller=CALLER, expected_seq=None)
    assert got.kind == "accepted" and rig.risk.seen[-1].price == D("61000")


async def test_an_amend_is_sent_once_its_checks_pass_and_answers_its_new_version(
    rig: SubmitRig,
) -> None:
    """Q5: the `ETag`'s seq moves with the amend's step; the amend is written ahead and its
    outcome recorded; nothing of the order's stop is touched by a price amend."""
    found, exits = await scoped(rig), exits_of(rig)
    before = rig.machines.version(found.order.id)
    got = await exits.amend(found, AmendTerms(price=D("60100")), caller=CALLER, expected_seq=before)
    assert (got.kind, got.status, got.lifecycle_state) == ("accepted", 202, "submitted")
    assert got.row is not None and got.row.price == D("60100")
    assert got.version is not None and before is not None and got.version > before
    [sent] = amends(rig)
    assert (sent.price, sent.stop_loss, sent.take_profit) == (D("60100"), None, None)
    assert requests(rig, "orders.amend") == [("success", "user"), ("success", "submitted")]


async def test_an_offset_resolves_from_the_amended_price_and_both_sides_are_re_paired(
    rig: SubmitRig,
) -> None:
    """Q2's re-pairing: the stop moved by 10 ticks below the new price, the take-profit re-sent at
    its current value; the amended stop recorded ahead as the entry's own (S4-B2)."""
    found, exits = await scoped(rig), exits_of(rig)
    sides = {"stop_loss": StopOffset("ticks", D(10))}
    terms = AmendTerms(price=D("60100"), sides=sides)
    got = await exits.amend(found, terms, caller=CALLER, expected_seq=None)
    assert got.kind == "accepted"
    [sent] = amends(rig)
    assert (sent.price, sent.stop_loss, sent.take_profit) == (D("60100"), D("60099"), D("64000"))


_SL_LOOSER = {"stop_loss": StopOffset("price", D("57000"))}


@pytest.mark.parametrize(
    ("terms", "seq", "status", "code", "rule"),
    [
        (AmendTerms(), None, 400, "validation_failed", "required"),
        (AmendTerms(qty=D("0")), None, 400, "validation_failed", "qty_not_above_filled"),
        (AmendTerms(sides={"take_profit": None}), None, 400, "validation_failed",
         "tpsl_clear_unsupported"),
        (AmendTerms(sides={"stop_loss": None}), None, 400, "validation_failed",
         "native_stop_required"),
        (AmendTerms(price=D("57000")), None, 400, "validation_failed", "native_stop_required"),
        (AmendTerms(price=D("60000.05")), None, 400, "tick_size_violation", "tick_size"),
        (AmendTerms(sides=_SL_LOOSER), None, 403, "risk_limit_breached", None),
        (AmendTerms(price=D("60100")), "stale", 412, "version_conflict", None),
        (AmendTerms(price=D("60100")), NO_VERSION, 412, "version_conflict", None),
    ],
    ids=["empty", "qty-not-above-fill", "tp-clear", "native-sl-clear", "price-past-the-stop",
         "tick", "native-sl-looser", "stale-if-match", "foreign-if-match"],
)  # fmt: skip
async def test_native_sl_each_refusal_is_audited_and_nothing_is_recorded_or_sent(
    rig: SubmitRig, terms: AmendTerms, seq: Any, status: int, code: str, rule: str | None
) -> None:
    """C-2.6: `stop_loss: null` is refused for good, and a looser stop is refused before any
    record or send (Q4's one ratchet); D3's order: the body (400), the ratchet (403), then
    `If-Match` (412). Each refusal is `orders.amend` denied with its code, written ahead."""
    found, exits = await scoped(rig), exits_of(rig)
    stops = len(rig.store._stops)
    expected = rig.machines.version(found.order.id)
    expected = (expected or 0) - 1 if seq == "stale" else seq
    got = await exits.amend(found, terms, caller=CALLER, expected_seq=expected)
    assert (got.kind, got.status, got.code) == ("refused", status, code)
    assert [e.rule for e in got.errors] == ([] if rule is None else [rule])
    assert amends(rig) == [] and len(rig.store._stops) == stops
    assert requests(rig, "orders.amend") == [("denied", code)]


async def test_the_state_is_checked_before_if_match_and_a_final_order_is_422(
    rig: SubmitRig,
) -> None:
    """Q5: 404, then 422, then 412: a cancelled order with a stale tag is 422, nothing sent."""
    found, exits = await scoped(rig), exits_of(rig)
    await exits.cancel_admitted(found.order, actor=actor(), reason="user", request_id=None)
    got = await exits.amend(found, AmendTerms(price=D("60100")), caller=CALLER, expected_seq=0)
    assert (got.status, got.code) == (422, "order_not_amendable") and amends(rig) == []


@pytest.mark.parametrize("gate", ["none", "flag", "switch", "read_only", "profile", "risk"])
async def test_a_risk_increasing_amend_meets_place_orders_gates_and_a_reducing_one_none(
    rig: SubmitRig, gate: str
) -> None:
    """Q10 and D1, on the amended order: `trading.oms_enabled`, the switches, then
    `Validator.check_order` (the read-only gate, the order's own profile) and the risk gate; a
    smaller quantity meets none of them (C-2.6's carve-out)."""
    found, flag = await scoped(rig), gate != "flag"
    if gate == "profile":  # no profile allows an entry (D11)
        rig.profiles.held.clear()
    if gate == "switch":
        rig.port.switches.refusals[cr.ACCOUNT] = TradingDisabled()
    rig.read_only.is_read_only = gate == "read_only"
    refusal = RiskDecision(
        allowed=False, code=RiskRefusal.RISK_STATE_UNAVAILABLE, message="No.", evaluated_at=cr.T0
    )
    over: dict[str, Any] = {"oms_enabled": lambda: flag}
    if gate == "risk":
        over["risk_gate"] = type("Refuse", (), {"check": lambda *_a, **_k: refusal})()
    exits = exits_of(rig, **over)
    up = await exits.amend(found, AmendTerms(qty=D("0.011")), caller=CALLER, expected_seq=None)
    if gate == "none":
        assert up.kind == "accepted" and rig.risk.seen[-1].qty == D("0.011")
        return
    code = "risk_limit_breached" if gate in ("risk", "profile") else "trading_disabled"
    assert (up.kind, up.status, up.code) == ("refused", 403, code) and amends(rig) == []
    down = await exits.amend(found, AmendTerms(qty=D("0.009")), caller=CALLER, expected_seq=None)
    assert down.kind == "accepted" and len(amends(rig)) == 1


async def test_the_venues_refusal_is_502_and_the_order_kept_on_its_prior_terms(
    rig: SubmitRig,
) -> None:
    found, exits = await scoped(rig), exits_of(rig)
    rig.port.demo.script("amend_order", FakeReject(OmsErrorCode.PRICE_OUT_OF_BOUNDS, 110003))
    got = await exits.amend(found, AmendTerms(price=D("60100")), caller=CALLER, expected_seq=None)
    assert (got.status, got.code, got.exchange_ret_code) == (502, "exchange_error", 110003)
    row = await rig.port.orders.get(cr.ACCOUNT, found.order.id)
    assert row is not None and row.price == D("60000")


async def test_an_account_the_port_cannot_sign_for_is_409_account_unavailable(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 11:34Z ruling, B: the command port answers it, no retry, never `conflict`."""
    found, exits = await scoped(rig), exits_of(rig)

    async def refused(*_args: Any, **_kwargs: Any) -> Any:
        raise AccountScopeDenied

    monkeypatch.setattr(rig.port.accounts, "trading_account", refused)
    got = await exits.amend(found, AmendTerms(price=D("60100")), caller=CALLER, expected_seq=None)
    assert (got.status, got.code, got.retry_after_s, got.retryable) == (
        409, "account_unavailable", None, False,
    )  # fmt: skip
    assert amends(rig) == []
