"""The exit service's amend (E29-T04 slice 4, `oms.exits`; 22 `amendOrder`; rulings Q3 to Q5 and
Q10, the S4-A decisions D1 and D3): over the real B1 facade, the real command port and the fake
venue (`submit_rig`), the rig's limit buy entry resting `submitted` (0.010 at 60000, its stop
58000 and its take-profit 64000, Full mode, unfilled)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import fields
from decimal import Decimal
from typing import Any

import pytest

from candleviewer.api.order_etag import NO_VERSION
from candleviewer.exchange.base.errors import OmsErrorCode
from candleviewer.exchange.base.fakes import FakeReject
from candleviewer.oms.errors import (
    AccountScopeDenied,
    IllegalTransition,
    TradingDisabled,
    VersionConflict,
)
from candleviewer.oms.exits import AmendTerms, ExitCaller, risk_increasing
from candleviewer.oms.ports import StopOffset
from candleviewer.risk.models import RiskDecision, RiskRefusal
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.accounts import OwnerScope
from candleviewer.storage.repositories.orders import OrderRow, ScopedOrder
from tests.unit.oms import command_rig as cr
from tests.unit.oms import submit_rig as sr
from tests.unit.oms.submit_rig import SubmitRig
from tests.unit.oms.test_exits import OWNER, actor, exits_of, placed, refuse_after, requests

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
        ({}, AmendTerms(qty=D("0.010")), False),
        ({"price": D("60000")}, AmendTerms(price=D("NaN")), False),
        ({"trigger_price": D("61000")}, AmendTerms(trigger_price=D("Infinity")), False),
        ({}, AmendTerms(qty=D("NaN")), False),
    ],
    ids=["qty-up", "qty-cut", "reduce-only-qty", "price-moved", "price-same",
         "reduce-only-price", "trigger-moved", "trigger-same", "trigger-added", "tp-and-sl",
         "qty-same", "price-no-number", "trigger-no-number", "qty-no-number"],
)  # fmt: skip
def test_risk_increasing_is_a_quantity_up_or_a_price_or_trigger_moved_on_an_entry(
    over: dict[str, Any], terms: AmendTerms, raises: bool
) -> None:
    """24 Sec.8.10, ruling Q10 (D5), SEC-S4A-01: every other amend is never gated (C-2.6); the
    quantity it holds is no raise, and a figure that is no number is never compared."""
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
_IN_ATR = {"stop_loss": StopOffset("atr", D(1))}


@pytest.mark.parametrize(
    ("terms", "seq", "status", "code", "rules"),
    [
        (AmendTerms(), None, 400, "validation_failed", ("nothing_to_amend",)),
        (AmendTerms(qty=D("0")), None, 400, "validation_failed",
         ("qty_not_above_filled", "min_order_qty")),
        (AmendTerms(sides={"take_profit": None}), None, 400, "validation_failed",
         ("tpsl_clear_unsupported",)),
        (AmendTerms(sides={"stop_loss": None}), None, 400, "validation_failed",
         ("native_stop_required",)),
        (AmendTerms(price=D("57000")), None, 400, "validation_failed", ("native_stop_required",)),
        (AmendTerms(price=D("64500")), None, 400, "validation_failed", ("take_profit_side",)),
        (AmendTerms(price=D("60000.05")), None, 400, "tick_size_violation", ("tick_size",)),
        (AmendTerms(qty=D("0.0105")), None, 400, "lot_size_violation", ("qty_step",)),
        (AmendTerms(qty=D("NaN")), None, 400, "validation_failed", ("finite",)),
        (AmendTerms(sides=_IN_ATR), None, 400, "validation_failed", ("stop_unit_unsupported",)),
        (AmendTerms(sides=_SL_LOOSER), None, 403, "risk_limit_breached", ()),
        (AmendTerms(price=D("60100")), "stale", 412, "version_conflict", ()),
        (AmendTerms(price=D("60100")), NO_VERSION, 412, "version_conflict", ()),
    ],
    ids=["empty", "qty-not-above-zero", "tp-clear", "native-sl-clear", "price-past-the-stop",
         "price-past-the-take-profit", "tick", "lot", "no-number", "a-unit-unresolved",
         "native-sl-looser", "stale-if-match", "foreign-if-match"],
)  # fmt: skip
async def test_native_sl_each_refusal_is_audited_and_nothing_is_recorded_or_sent(
    rig: SubmitRig, terms: AmendTerms, seq: Any, status: int, code: str, rules: tuple[str, ...]
) -> None:
    """C-2.6: `stop_loss: null` is refused for good, and a looser stop is refused before any
    record or send (Q4's one ratchet); D3's order: the body (400, every rule that fails listed,
    22 `amendOrder`), the ratchet (403), then `If-Match` (412). Each refusal is `orders.amend`
    denied with its code, written ahead."""
    found, exits = await scoped(rig), exits_of(rig)
    stops = len(rig.store._stops)
    expected = rig.machines.version(found.order.id)
    expected = (expected or 0) - 1 if seq == "stale" else seq
    got = await exits.amend(found, terms, caller=CALLER, expected_seq=expected)
    assert (got.kind, got.status, got.code) == ("refused", status, code)
    assert tuple(e.rule for e in got.errors) == rules
    assert amends(rig) == [] and len(rig.store._stops) == stops
    assert requests(rig, "orders.amend") == [("denied", code)]


_FILL = "0.004"


async def placed_as(rig: SubmitRig, request: Any) -> ScopedOrder:
    """`request` placed and resting (`submitted`), as the scope reads it."""
    outcome = await rig.submit(request)
    await rig.quiet()
    assert outcome.order_id is not None
    found = await exits_of(rig).scope(CALLER, outcome.order_id)
    assert isinstance(found, ScopedOrder) and found.order.lifecycle_state == "submitted"
    return found


async def in_partial_mode(rig: SubmitRig) -> ScopedOrder:
    """The rig's entry, placed under `tpsl_mode: Partial`."""
    return await placed_as(rig, sr.entry(tpsl_mode="Partial"))


async def partly_filled(rig: SubmitRig) -> ScopedOrder:
    """The rig's entry partly filled by a real `EXEC` of `_FILL` on its bound exchange order, the
    venue holding the long it opened, as the scope then reads it (`partially_filled`)."""
    row = (await scoped(rig)).order
    rig.port.demo.seed_position(cr.position(qty=_FILL))  # so the stop's attach reads it back
    fill = {
        "order_id": str(row.id), "order_link_id": row.order_link_id,
        "account_id": str(cr.ACCOUNT), "symbol": row.symbol, "side": "buy", "exec_id": "e1",
        "exchange_order_id": row.exchange_order_id, "qty": _FILL, "exec_type": "trade",
        "price": "60000", "fee": "0", "fee_rate": "0.0002", "ts_exec": cr.T0_US,
    }  # fmt: skip
    await rig.machines.push(cr.ACCOUNT, row.id, "EXEC", fill)
    await rig.quiet()
    found = await exits_of(rig).scope(CALLER, row.id)
    assert isinstance(found, ScopedOrder) and found.order.cum_exec_qty == D(_FILL)
    assert found.order.lifecycle_state == "partially_filled"
    return found


async def reducing(rig: SubmitRig) -> ScopedOrder:
    """A reduce-only limit sell resting over the account's long, with no stop of its own."""
    rig.port.demo.seed_position(cr.position(qty="0.050"))
    return await placed_as(rig, sr.flatten(order_type="limit", price=D("61000")))


async def at_market(rig: SubmitRig) -> ScopedOrder:
    """A reduce-only market sell resting over the account's long: no price, no trigger."""
    rig.port.demo.seed_position(cr.position(qty="0.050"))
    return await placed_as(rig, sr.flatten())


async def unlisted(rig: SubmitRig) -> ScopedOrder:
    """The rig's entry, its symbol no longer listed."""
    found = await scoped(rig)
    rig.instruments.listed.clear()
    return found


_VARIANTS: dict[str, Callable[[SubmitRig], Awaitable[ScopedOrder]]] = {
    "partial": in_partial_mode, "filled": partly_filled, "reducing": reducing,
    "at_market": at_market, "unlisted": unlisted,
}  # fmt: skip


@pytest.mark.parametrize(
    ("variant", "terms", "code", "rules"),
    [
        ("partial", AmendTerms(sides={"take_profit": _TICKS}), "validation_failed",
         ("tpsl_partial_mode",)),
        ("filled", AmendTerms(sides={"stop_loss": _TICKS}), "validation_failed",
         ("tpsl_after_fill",)),
        ("filled", AmendTerms(qty=D(_FILL)), "validation_failed", ("qty_not_above_filled",)),
        ("reducing", AmendTerms(sides={"take_profit": _TICKS}), "validation_failed",
         ("reduce_only_tpsl",)),
        ("at_market", AmendTerms(qty=D("0.009")), "validation_failed", ("required",)),
        ("unlisted", AmendTerms(price=D("60100")), "validation_failed", ("listed",)),
        ("filled", AmendTerms(qty=D(_FILL), sides={"stop_loss": None}), "validation_failed",
         ("native_stop_required", "qty_not_above_filled")),
        ("filled", AmendTerms(qty=D(_FILL), price=D("60000.05")), "validation_failed",
         ("qty_not_above_filled", "tick_size")),
    ],
    ids=["tpsl-partial-mode", "tpsl-after-fill", "qty-not-above-a-real-fill", "reduce-only-tpsl",
         "no-price-to-measure-from", "unlisted-symbol", "q3-and-the-quantity",
         "the-quantity-and-the-tick"],
)  # fmt: skip
async def test_each_refusal_of_an_order_its_rule_fits_is_audited_nothing_recorded_or_sent(
    rig: SubmitRig, variant: str, terms: AmendTerms, code: str, rules: tuple[str, ...]
) -> None:
    """Q3 on the orders its rules fit (Partial mode, a fill, reduce-only), a quantity not above a
    real fill, an order with no price to measure from and an unlisted symbol; `errors[]` lists
    every rule that fails, `validation_failed` when rules of both kinds do (22 `amendOrder`)."""
    found = await _VARIANTS[variant](rig)
    exits, stops, sent = exits_of(rig), len(rig.store._stops), len(amends(rig))
    got = await exits.amend(found, terms, caller=CALLER, expected_seq=None)
    assert (got.kind, got.status, got.code) == ("refused", 400, code)
    assert tuple(e.rule for e in got.errors) == rules
    assert len(amends(rig)) == sent and len(rig.store._stops) == stops
    assert requests(rig, "orders.amend") == [("denied", code)]


def _outage() -> StorageTierUnavailable:
    return StorageTierUnavailable("postgres unreachable (OSError)")


async def _down(*_args: Any, **_kwargs: Any) -> Any:
    raise _outage()


def _instrument_down(rig: SubmitRig, _monkeypatch: pytest.MonkeyPatch) -> AmendTerms:
    rig.instruments.refuse = _outage()
    return AmendTerms(price=D("60100"))


def _stops_down(rig: SubmitRig, monkeypatch: pytest.MonkeyPatch) -> AmendTerms:
    monkeypatch.setattr(rig.port.stops, "live_for_key", _down)
    return AmendTerms(sides={"stop_loss": _TICKS})  # the ratchet reads them for a named stop


def _profile_down(rig: SubmitRig, _monkeypatch: pytest.MonkeyPatch) -> AmendTerms:
    rig.profiles.refuse = _outage()
    return AmendTerms(qty=D("0.011"))  # a risk-increasing amend reads its leg's profile


@pytest.mark.parametrize(
    "down", [_instrument_down, _stops_down, _profile_down],
    ids=["instrument", "live-for-key", "profile"],
)  # fmt: skip
async def test_a_read_the_amend_needs_that_fails_is_503_and_nothing_is_recorded_or_sent(
    rig: SubmitRig,
    down: Callable[[SubmitRig, pytest.MonkeyPatch], AmendTerms],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """24 Sec.8.4: a read before anything is sent that fails answers `503 store_unavailable` with
    the shared `Retry-After: 1`, audited, the order live: the instrument, the key's stops in force
    (the ratchet's) and a risk-increasing amend's profile."""
    found, exits = await scoped(rig), exits_of(rig)
    stops, terms = len(rig.store._stops), down(rig, monkeypatch)
    got = await exits.amend(found, terms, caller=CALLER, expected_seq=None)
    assert (got.kind, got.status, got.code, got.retry_after_s) == (
        "refused", 503, "store_unavailable", 1,
    )  # fmt: skip
    assert amends(rig) == [] and len(rig.store._stops) == stops
    assert requests(rig, "orders.amend") == [("denied", "store_unavailable")]
    assert rig.machines.state(found.order.id) == ("submitted", "not_required")


async def test_an_amend_whose_intent_cannot_be_recorded_is_503_and_nothing_is_sent(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.9: the write-ahead `orders.amend` that does not land answers `503 audit_unavailable`,
    nothing commanded, recorded or sent, the order on its terms."""
    found, exits = await scoped(rig), exits_of(rig)
    stops = len(rig.store._stops)
    refuse_after(rig.port.audits, len(rig.port.audits.written), monkeypatch)
    got = await exits.amend(found, AmendTerms(price=D("60100")), caller=CALLER, expected_seq=None)
    assert (got.kind, got.status, got.code) == ("refused", 503, "audit_unavailable")
    assert amends(rig) == [] and len(rig.store._stops) == stops
    assert requests(rig, "orders.amend") == []
    assert rig.machines.state(found.order.id) == ("submitted", "not_required")


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [(VersionConflict(), 412, "version_conflict"),
     (IllegalTransition("amend_pending", "AMEND"), 422, "order_not_amendable")],
    ids=["version-moved-under-the-lock", "state-moved"],
)  # fmt: skip
async def test_an_amend_the_facade_refuses_is_refused_beside_its_intent_nothing_sent(
    rig: SubmitRig, error: Exception, status: int, code: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Q5: the facade compares the version again under the order's lock (412), and a state that
    moved under the amend takes no `AMEND` (422): nothing sent or recorded, the refusal recorded
    beside the intent."""
    found, exits = await scoped(rig), exits_of(rig)
    stops = len(rig.store._stops)

    async def refuses(*_args: Any, **_kwargs: Any) -> str:
        raise error

    monkeypatch.setattr(rig.machines, "command", refuses)
    got = await exits.amend(found, AmendTerms(price=D("60100")), caller=CALLER, expected_seq=None)
    assert (got.kind, got.status, got.code) == ("refused", status, code)
    assert amends(rig) == [] and len(rig.store._stops) == stops
    assert requests(rig, "orders.amend") == [("success", "user"), ("denied", code)]


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


async def test_after_aclose_an_amend_starts_nothing(rig: SubmitRig) -> None:
    """Once the service is closed no exit starts: `503 oms_not_ready`, nothing recorded or sent."""
    found, exits = await scoped(rig), exits_of(rig)
    await exits.aclose()
    got = await exits.amend(found, AmendTerms(price=D("60100")), caller=CALLER, expected_seq=None)
    assert (got.kind, got.status, got.code) == ("refused", 503, "oms_not_ready")
    assert amends(rig) == [] and requests(rig, "orders.amend") == []


async def test_an_amend_whose_intent_was_written_as_aclose_ran_starts_nothing(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`aclose` while the amend's intent is written: nothing starts, `503 oms_not_ready`, the
    refusal recorded beside the intent (C-2.9)."""
    found, exits = await scoped(rig), exits_of(rig)
    entered, release, write = asyncio.Event(), asyncio.Event(), rig.port.audits.write

    async def held(record: cr.AnyRecord) -> None:
        entered.set()
        await release.wait()
        await write(record)

    monkeypatch.setattr(rig.port.audits, "write", held)
    terms = AmendTerms(price=D("60100"))
    task = asyncio.ensure_future(exits.amend(found, terms, caller=CALLER, expected_seq=None))
    await entered.wait()
    await exits.aclose()
    release.set()
    got = await task
    assert (got.kind, got.status, got.code) == ("refused", 503, "oms_not_ready")
    assert amends(rig) == []
    assert requests(rig, "orders.amend") == [("success", "user"), ("denied", "oms_not_ready")]
