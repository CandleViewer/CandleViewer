"""The size step of `OrderSubmission` (E29-T04 #913 S4-S; 24 Sec.8.4 item 2, step 3c; 22
`placeOrder`): an entry is sized by its profile's sizer, each outcome is its answer, a request's
sizing or stop that goes past the profile is refused whole, and the stop sent is the sizer's
(C-2.6)."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.accounts.sizer_metrics import SizerMetrics
from candleviewer.audit.redact import redact
from candleviewer.exchange.base.models import PlaceOrderRequest
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.errors import (
    ExchangeUnavailable,
    LotSizeViolation,
    OmsError,
    OrderInvalid,
    RiskRefused,
    SizingUnavailable,
    problem_for,
)
from candleviewer.oms.ports import UNKNOWN_FIGURES, NoDayFigures, SizingRequest, StopOffset
from candleviewer.oms.sizing import EntryIntent, EntrySizer
from candleviewer.statechart.bindings import b01_order as b01
from tests.unit.accounts import test_sizer as sizer_rig
from tests.unit.accounts.test_sizer_golden import VECTORS
from tests.unit.oms import command_rig as cr
from tests.unit.oms.submit_rig import (
    SYMBOL,
    Figures,
    SubmitRig,
    build_rig,
    context,
    entry,
    figures,
    flatten,
    instrument,
    profile,
    rigged,
)

D = Decimal
_BY_PROFILE = SizingRequest(mode="profile")


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[SubmitRig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    built = build_rig()
    yield built
    await built.machines.stop()


async def _refused(rig: SubmitRig, request: Any) -> OmsError:
    with pytest.raises(OmsError) as refused:
        await rig.submit(request)
    assert rig.calls() == [] and rig.written() == (0, 0, 0, 0)  # nothing recorded or sent
    return refused.value


def _sent(rig: SubmitRig) -> PlaceOrderRequest:
    [create] = [c.request for c in rig.port.demo.calls if c.method == "place_order"]
    assert isinstance(create, PlaceOrderRequest)
    return create


def _by_profile(**over: Any) -> Any:
    return entry(**({"sizing": _BY_PROFILE, "stop_loss": None, "take_profit": None} | over))


# --- each mode against its golden vector (E28-T03's own, read unchanged) ------------------------


@pytest.mark.parametrize("vid", ["V01", "V06", "V07", "V10", "T21"])
async def test_entry_sizer_profile_mode_matches_the_golden_vector(vid: str) -> None:
    """risk_based, pct_equity, fixed_qty (a limit and a market order) and fixed_notional, sized
    through the size step's adapter exactly as `size_leg` sizes the vector."""
    v = next(x for x in VECTORS if x["id"] == vid)
    m, it = v["market"], v["intent"]
    held = sizer_rig.profile(v["profile"]["id"], **v["profile"]["set"])
    known = sizer_rig.wallet(
        v["wallet"]["equity"], m["taker_fee_rate"], realised_loss_today=m["daily_loss_used"]
    ).model_copy(update={"available_margin": D(v["wallet"]["available_margin"])})
    sizer = EntrySizer(Figures(known=known), SizerMetrics.register(Metrics("demo")))
    price = None if it.get("price") is None else D(it["price"])
    intent = EntryIntent(
        symbol=it["symbol"], side=it["side"].lower(), order_type=it["order_type"], price=price,
        sizing=_BY_PROFILE, stop_loss=None,
    )  # fmt: skip
    mid, last = (None if m.get(k) is None else D(m[k]) for k in ("mid", "last_price"))
    size = await sizer.size(
        intent, account=cr.ref(), instrument=sizer_rig.instrument(it["symbol"]), profile=held,
        mid=mid, last=last,
    )  # fmt: skip
    assert (size.qty, size.stop) == (D(v["expected"]["qty"]), D(v["expected"]["stop"]))
    assert size.mode == held.sizing_mode and size.value is None


# --- each outcome row, through the pipeline -----------------------------------------------------

_ROWS: list[Any] = [
    ("figure_unknown", {"figures": UNKNOWN_FIGURES}, SizingUnavailable, "sizing_unavailable", None),
    ("symbol_not_allowed", {"allowed_symbols": ["ETHUSDT"]}, RiskRefused, "risk_limit_breached",
     ("symbol", "symbol_not_allowed")),
    ("below_min_notional", {"min_leg_notional": "1000"}, LotSizeViolation, "lot_size_violation",
     ("sizing", "min_leg_notional")),
    ("cap_breached", {"max_position_notional": "50"}, RiskRefused, "risk_limit_breached",
     ("sizing", "max_position_notional")),
    ("insufficient_margin", {"figures": figures(available_margin="1")}, RiskRefused,
     "risk_limit_breached", ("sizing", "insufficient_margin")),
    ("leverage_unavailable", {"instrument": instrument(max_leverage=D(5))}, OrderInvalid,
     "validation_failed", ("leverage", "max_leverage")),
    ("invalid_stop_distance", {"price": D("62000"), "mid": D("60000"), "sl_offset_value": "0.01"},
     OrderInvalid, "validation_failed", ("stop_loss", "invalid_stop_distance")),
    ("stop_beyond_liquidation", {"leverage": "50", "max_leverage_cap": "50"}, OrderInvalid,
     "validation_failed", ("stop_loss", "stop_beyond_liquidation")),
    ("no_reference_price", {"market": True}, ExchangeUnavailable, "exchange_unavailable", None),
]  # fmt: skip


@pytest.mark.parametrize(
    ("over", "error", "code", "named"), [row[1:] for row in _ROWS], ids=[row[0] for row in _ROWS]
)
async def test_submit_each_sizer_outcome_is_its_answer(
    rig: SubmitRig, over: dict[str, Any], error: type[OmsError], code: str, named: Any
) -> None:
    """22 `placeOrder`'s mapping, one row each, before anything is recorded or sent."""
    over = dict(over)
    rig.figures.known = over.pop("figures", rig.figures.known)
    rig.instruments.listed[SYMBOL] = over.pop("instrument", instrument())
    request = _by_profile(price=over.pop("price", D("60000")))
    if over.pop("market", False):  # a market entry whose venue shows no price at all
        request = _by_profile(order_type="market", price=None)
        rig.prices.price, rig.figures.refuse = None, None
    rig.prices.price = over.pop("mid", rig.prices.price)
    rig.profiles.held[(cr.ACCOUNT, None)] = profile(**over)
    refused = await _refused(rig, request)
    assert type(refused) is error and problem_for(refused).code == code
    if named is not None:
        assert isinstance(refused, OrderInvalid | RiskRefused | LotSizeViolation)
        assert [(e.field, e.rule) for e in refused.errors] == [named]
    if isinstance(refused, SizingUnavailable):
        assert refused.retry_after_s == 1


async def test_submit_a_disabled_profile_is_403_before_any_figure_is_read(rig: SubmitRig) -> None:
    rig.profiles.held[(cr.ACCOUNT, None)] = profile(trading_enabled=False)
    refused = await _refused(rig, _by_profile())
    assert problem_for(refused).code == "risk_limit_breached" and rig.figures.reads == []


async def test_submit_a_reduce_only_order_keeps_its_qty_and_reads_no_figures(
    rig: SubmitRig,
) -> None:
    rig.port.demo.seed_position(cr.position(qty="0.050"))
    sizing = SizingRequest(mode="fixed_qty", qty=D("0.0257"))
    assert (await rig.submit(flatten(sizing=sizing))).status == 202
    assert _sent(rig).qty == D("0.025") and rig.figures.reads == []  # floored to the lot only


@pytest.mark.parametrize("mode", ["pct_position", "profile", "fixed_notional"])
async def test_submit_a_reduce_only_order_in_another_mode_is_unsupported(
    rig: SubmitRig, mode: Any
) -> None:
    refused = await _refused(rig, flatten(sizing=SizingRequest(mode=mode, pct=D(50))))
    assert isinstance(refused, OrderInvalid)
    assert [e.rule for e in refused.errors] == ["sizing_mode_unsupported"]


# --- the request's overlay (ruling Q2) ----------------------------------------------------------


@pytest.mark.parametrize(
    ("request_", "named"),
    [
        (entry(sizing=SizingRequest(mode="fixed_qty", qty=D("1"))), ("sizing", "max_daily_loss")),
        (entry(sizing=SizingRequest(mode="fixed_qty", qty=D("0.1"))),
         ("sizing.qty", "fixed_qty")),
        (entry(stop_loss=StopOffset(unit="price", value=D("56000"))),
         ("stop_loss", "sl_offset_value")),
    ],
    ids=["qty_past_a_cap", "qty_above_the_profiles_under_every_cap", "stop_further"],
)  # fmt: skip
async def test_submit_an_overlay_that_widens_the_profile_is_refused_whole(
    rig: SubmitRig, request_: Any, named: tuple[str, str]
) -> None:
    """Never clamped: the whole request is 403, nothing recorded or sent."""
    refused = await _refused(rig, request_)
    assert isinstance(refused, RiskRefused)
    assert named in [(e.field, e.rule) for e in refused.errors]


@pytest.mark.parametrize(
    ("sizing", "qty", "mode", "value"),
    [
        (SizingRequest(mode="fixed_qty", qty=D("0.005")), D("0.005"), "fixed_qty", D("0.005")),
        (SizingRequest(mode="fixed_qty", qty=D("0.01")), D("0.010"), "fixed_qty", D("0.01")),
    ],
    ids=["fixed_qty", "fixed_qty_at_the_profiles"],
)  # fmt: skip
async def test_submit_an_overlay_inside_the_profile_is_sized_and_recorded(
    rig: SubmitRig, sizing: SizingRequest, qty: Decimal, mode: str, value: Decimal
) -> None:
    """The request's values size the leg (a percent of equity, times leverage, at entry), and the
    group records the resolved mode and the request's own value."""
    outcome = await rig.submit(entry(sizing=sizing))
    assert outcome.status == 202 and _sent(rig).qty == qty
    assert outcome.trade_group_id is not None
    record = rig.store._groups[outcome.trade_group_id]
    assert (record.group.requested_qty_mode, record.group.requested_qty_value) == (mode, value)


# --- risk, C-2.6, persistence and the audit record ----------------------------------------------


async def test_submit_the_risk_gate_sees_the_sized_qty(rig: SubmitRig) -> None:
    """R8 (SR-E29-04): risk runs after sizing, on the profile's quantity, never the request's."""
    rig.profiles.held[(cr.ACCOUNT, None)] = profile(
        sizing_mode="risk_based", fixed_qty=None, risk_fixed_amount="30"
    )
    assert (await rig.submit(_by_profile())).status == 202
    [seen] = rig.risk.seen
    assert seen.qty == _sent(rig).qty == D("0.009")  # 30 / (3000 + both taker fees), floored


async def test_submit_an_entry_sized_by_the_profile_sends_the_sizers_stop(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C-2.6, one stop source: the create's stop is the `ResolvedStop` the risk was computed from,
    and the leg records it with its risk with fees and the explanation (SR-E28-13)."""
    sizer, sized = rig.pipeline._sizer, []
    real = sizer.size

    async def size(*args: Any, **kwargs: Any) -> Any:
        sized.append(await real(*args, **kwargs))
        return sized[-1]

    monkeypatch.setattr(sizer, "size", size)
    outcome = await rig.submit(_by_profile())
    [got] = sized
    create = _sent(rig)
    assert outcome.status == 202 and create.stop_loss == got.stop == got.leg.stop.price
    assert create.stop_loss == D("57000.0")  # the profile's 5 % below 60000
    assert got.leg.risk_usdt == create.qty * got.leg.stop.distance  # the risk is the stop's
    assert outcome.trade_group_id is not None
    [leg] = rig.store._groups[outcome.trade_group_id].legs
    assert (leg.resolved_sl_price, leg.target_qty) == (create.stop_loss, create.qty)
    assert leg.risk_usd == got.leg.risk_with_fees_usdt  # 1R plus both taker fees
    [record] = rig.records("trade_group.submit")
    text = str(record.detail["sizing_explanation"])
    assert "stop 57000 USDT" in text and "1R = " in text
    assert rig.count("cv_sizer_outcomes_total", outcome="ok", reason="none") == 1


_MODES = st.sampled_from(
    [
        SizingRequest(mode="profile"),
        SizingRequest(mode="fixed_qty", qty=D("0.004")),
    ]
)
_STOPS = st.one_of(
    st.none(),
    st.builds(StopOffset, unit=st.just("percent"), value=st.decimals("0.5", "8", places=2)),
    st.builds(StopOffset, unit=st.just("ticks"), value=st.integers(1, 40_000).map(D)),
    st.builds(StopOffset, unit=st.just("atr"), value=st.decimals("0.5", "4", places=1)),
    st.builds(StopOffset, unit=st.just("price"), value=st.integers(50_000, 70_000).map(D)),
)


@settings(max_examples=40, deadline=None)
@given(sizing=_MODES, side=st.sampled_from(["buy", "sell"]), stop=_STOPS)
async def test_submit_no_sized_entry_reaches_the_send_without_its_stop(
    sizing: SizingRequest, side: str, stop: StopOffset | None
) -> None:
    """C-2.6 over modes, sides and stop units: whatever the size step answers, every create
    carries a stop on the protective side of the leg's anchor, never none."""
    async with rigged() as rig:
        request = entry(sizing=sizing, side=side, stop_loss=stop, take_profit=None)
        try:
            await rig.submit(request)
        except OmsError:
            assert rig.calls() == []
            return
        create = _sent(rig)
        assert create.stop_loss is not None
        assert create.stop_loss < D(60000) if side == "buy" else create.stop_loss > D(60000)


# --- the figures' cache and the overlap ---------------------------------------------------------


async def test_submit_an_accepted_send_drops_the_accounts_figures(rig: SubmitRig) -> None:
    assert (await rig.submit()).status == 202
    assert rig.figures.invalidated == [cr.ACCOUNT]


async def test_submit_a_refused_entry_drops_nothing(rig: SubmitRig) -> None:
    await _refused(rig, entry(sizing=SizingRequest(mode="pct_position", pct=D(5))))
    assert rig.figures.invalidated == []


async def test_submit_two_overlapping_entries_on_one_account_are_judged_in_turn(
    rig: SubmitRig,
) -> None:
    """The second entry's size step waits for the first's answer and its figures' drop, so it
    reads the room the first took (24 Sec.9.3.6): here the day's room fits one entry only."""
    rig.profiles.held[(cr.ACCOUNT, None)] = profile(max_daily_loss="40")
    held = rig.figures
    order: list[str] = []
    real_read = held.read

    async def read(*args: Any, **kwargs: Any) -> Any:
        order.append("read")
        return await real_read(*args, **kwargs)

    def invalidate(account_id: Any) -> None:
        order.append("invalidate")
        held.known = figures(committed_risk="21")  # the first entry's 1R with fees, now held

    held.read, held.invalidate = read, invalidate  # type: ignore[method-assign]  # spies
    first, second = await asyncio.gather(
        rig.pipeline.submit(entry(), context(client_ref=uuid4())),
        rig.pipeline.submit(entry(), context(client_ref=uuid4())),
        return_exceptions=True,
    )
    assert getattr(first, "status", None) == 202
    assert isinstance(second, RiskRefused)
    assert order == ["read", "invalidate", "read"]


async def test_submit_a_live_entry_is_503_sizing_unavailable(rig: SubmitRig) -> None:
    """On live nothing serves the day's figures (`NoDayFigures`, the wiring's binding there), so
    every live entry is `figure_unknown`: 503 `sizing_unavailable`, nothing recorded or sent."""
    rig.pipeline._sizer = EntrySizer(
        NoDayFigures(), SizerMetrics.register(rig.metrics), tier_requests=rig.tiers
    )
    rig.profiles.held[(cr.LIVE_ACCOUNT, None)] = profile(cr.LIVE_ACCOUNT)
    refused = await _refused(rig, entry(account_id=cr.LIVE_ACCOUNT))
    assert isinstance(refused, SizingUnavailable)
    assert rig.count("cv_sizer_outcomes_total", outcome="fail", reason="figure_unknown") == 1
    assert rig.tiers.asked == []  # the figures source is absent, not the tiers: none requested


def _free(rig: SubmitRig) -> bool:
    return not any(turn.locked() for turn in rig.pipeline._turns)


async def test_submit_a_refused_entry_frees_its_turn(rig: SubmitRig) -> None:
    rig.figures.known = UNKNOWN_FIGURES
    await _refused(rig, _by_profile())
    assert _free(rig)


async def test_submit_a_cancelled_entry_frees_its_turn(rig: SubmitRig) -> None:
    gate = asyncio.Event()
    real_read = rig.figures.read

    async def read(*args: Any, **kwargs: Any) -> Any:
        gate.set()
        await asyncio.Event().wait()  # never answers: the caller goes away first
        return await real_read(*args, **kwargs)

    rig.figures.read = read  # type: ignore[method-assign]  # a read that hangs
    task = asyncio.ensure_future(rig.submit(_by_profile()))
    await gate.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert _free(rig)


async def test_submit_a_turn_not_had_in_time_is_503_and_holds_nothing(rig: SubmitRig) -> None:
    rig.pipeline._turn_wait_s = 0
    turns = rig.pipeline._turns
    held = turns[hash(cr.ACCOUNT) % len(turns)]
    await held.acquire()  # another entry of the account holds its turn
    refused = await _refused(rig, _by_profile())
    assert isinstance(refused, SizingUnavailable) and refused.retry_after_s == 1
    held.release()
    assert _free(rig)


async def test_submit_a_drop_that_raises_still_frees_the_turn(rig: SubmitRig) -> None:
    def invalidate(account_id: Any) -> None:
        raise RuntimeError("the cache refused")

    rig.figures.invalidate = invalidate  # type: ignore[method-assign]  # a drop that raises
    with pytest.raises(RuntimeError):
        await rig.submit()
    assert _free(rig)


@pytest.mark.parametrize(
    "sizing",
    [
        SizingRequest(mode="fixed_notional", notional_usd=D("600")),
        SizingRequest(mode="pct_equity", pct=D("0.06")),
        SizingRequest(mode="risk_based", risk_per_trade_usd=D("10")),
    ],
    ids=["fixed_notional", "pct_equity", "risk_based"],
)
async def test_submit_an_entry_in_a_mode_not_served_yet_is_unsupported(
    rig: SubmitRig, sizing: SizingRequest
) -> None:
    """An interim until the overlay is judged (#913 S4-S-b2b): nothing read, recorded or sent."""
    refused = await _refused(rig, entry(sizing=sizing))
    assert isinstance(refused, OrderInvalid) and rig.figures.reads == []
    assert [(e.field, e.rule) for e in refused.errors] == [
        ("sizing.mode", "sizing_mode_unsupported")
    ]


async def test_submit_an_entry_with_no_stop_and_no_profile_is_400_native_stop_required(
    rig: SubmitRig,
) -> None:
    """C-2.6 first (22 `placeOrder`): with no profile to give an offset, an entry naming no stop
    is `native_stop_required`; one naming a stop is still refused, 403 (D11)."""
    rig.profiles.held.clear()
    refused = await _refused(rig, entry(stop_loss=None))
    assert isinstance(refused, OrderInvalid)
    assert [(e.field, e.rule) for e in refused.errors] == [("stop_loss", "native_stop_required")]
    assert problem_for(await _refused(rig, entry())).code == "risk_limit_breached"


async def test_submit_the_sizing_explanation_passes_the_audit_redactor_unchanged(
    rig: SubmitRig,
) -> None:
    """SR-E28-13 beside C-12.6: the explanation holds figures, never a credential, and no figure
    string reads as one to the redactor, so the audit row keeps it whole."""
    assert (await rig.submit(_by_profile())).status == 202
    [record] = rig.records("trade_group.submit")
    detail = dict(record.detail)
    assert "1R = " in str(detail["sizing_explanation"])
    assert redact(detail) == detail


async def test_submit_a_fixed_qty_request_on_a_profile_of_another_mode_is_unsupported(
    rig: SubmitRig,
) -> None:
    """An interim until the overlay is judged (#913 S4-S-b2b): a `fixed_qty` request on a
    `risk_based` profile is not sized, so nothing is read, recorded or sent."""
    rig.profiles.held[(cr.ACCOUNT, None)] = profile(
        sizing_mode="risk_based", fixed_qty=None, risk_fixed_amount="30"
    )
    refused = await _refused(rig, entry(sizing=SizingRequest(mode="fixed_qty", qty=D("0.001"))))
    assert isinstance(refused, OrderInvalid) and rig.figures.reads == []
    assert [(e.field, e.rule) for e in refused.errors] == [
        ("sizing.mode", "sizing_mode_unsupported")
    ]


async def test_submit_a_request_stop_nearer_than_the_profiles_is_sent(rig: SubmitRig) -> None:
    """The profile's stop is 5 % (57000) below 60000; the request's 58000 is nearer, so it is the
    stop the leg is sized from and the create carries."""
    outcome = await rig.submit(entry(stop_loss=StopOffset(unit="price", value=D("58000"))))
    assert outcome.status == 202 and _sent(rig).stop_loss == D("58000")


async def test_submit_a_request_stop_whose_leg_a_cap_clamps_is_refused_whole(
    rig: SubmitRig,
) -> None:
    """A stop alone in `profile` mode is an overlay too: a tighter stop raises a risk-based leg's
    quantity, and a cap that would clamp it refuses the request whole, never clamped (ADR-0040)."""
    rig.profiles.held[(cr.ACCOUNT, None)] = profile(
        sizing_mode="risk_based", fixed_qty=None, risk_fixed_amount="30",
        max_position_notional="1000",
    )  # fmt: skip
    request = _by_profile(stop_loss=StopOffset(unit="price", value=D("59900")))
    refused = await _refused(rig, request)
    assert isinstance(refused, RiskRefused)
    assert [(e.field, e.rule) for e in refused.errors] == [("sizing", "max_position_notional")]


@pytest.mark.parametrize("request_of", [_by_profile, entry], ids=["profile", "fixed_qty_and_stop"])
async def test_submit_a_figure_unknown_for_missing_tiers_requests_them_once_and_is_503(
    rig: SubmitRig, request_of: Any
) -> None:
    """24 Sec.9.3.6: the symbol's maintenance margin rate is unknown (its tiers are missing from
    the catalogue), so the size step asks for its tiers once, never awaited, and the answer is
    still 503 `sizing_unavailable`, with nothing recorded or sent."""
    rig.figures.known = figures(maintenance_margin_rate=None)
    refused = await _refused(rig, request_of())
    assert isinstance(refused, SizingUnavailable)
    assert problem_for(refused).code == "sizing_unavailable"
    assert rig.tiers.asked == [SYMBOL]


async def test_submit_a_figure_unknown_with_the_tiers_known_requests_none(rig: SubmitRig) -> None:
    """Another figure unknown (the equity), the maintenance margin rate known: no tiers asked."""
    rig.figures.known = figures(equity=None)
    assert isinstance(await _refused(rig, _by_profile()), SizingUnavailable)
    assert rig.tiers.asked == []


async def test_submit_an_unread_figures_read_requests_no_tiers(rig: SubmitRig) -> None:
    """A read that fails says nothing of the tiers: 503, and no tiers asked."""
    rig.figures.refuse = TimeoutError()
    assert isinstance(await _refused(rig, _by_profile()), SizingUnavailable)
    assert rig.tiers.asked == []
