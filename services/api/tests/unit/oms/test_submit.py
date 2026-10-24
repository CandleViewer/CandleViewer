"""The order submission pipeline (E29-T04 #913; 24-internal-schemas.md Sec.8.4, 22 `placeOrder`).

`OrderSubmission` over the real B1 facade, the command port and `FakeTradingPort`s (`submit_rig`).
Each step refuses before the next runs, with nothing recorded and nothing sent, its refusal
audited first (C-2.9) and counted; the persist is one transaction under the Q4 loop; `SEND` that
does not commit is abandoned (S2-Q5); and the answer is the state B1 recorded, 202, 429 or 502,
whatever the best-effort records after it do. C-2.6 holds on every path: each kind of entry
reaches the venue with its native stop, and once each test of this module ends, every create that
is not reduce-only, read off the venue doubles of every rig the test built, carries one
(`stops_on_every_create`). The request's correlation id rides every record ([AUDIT-REQUEST-ID]),
no stop or take-profit that is no finite price above zero is recorded (#2877 ruling 2), and no
log line carries the key, the fingerprint, the stop or the quantity (C-12.6).
"""

from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4

import pytest
from structlog.testing import capture_logs

from candleviewer.accounts.errors import ProfileUnavailableError
from candleviewer.accounts.profile_cache import EffectiveProfiles
from candleviewer.accounts.profiles import AccountProfile, profile_values
from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.domain.primitives import AccountId
from candleviewer.exchange.base.errors import (
    DuplicateClientIdError,
    OmsErrorCode,
    RateBudgetExceededError,
    ServiceUnavailableError,
)
from candleviewer.exchange.base.fakes import (
    FakeCall,
    FakeReject,
    LandedThenAmbiguous,
    fake_capabilities,
)
from candleviewer.exchange.base.models import PlaceOrderRequest, RateHeadroom
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.commands import SUBMIT_TIMEOUT_S
from candleviewer.oms.errors import (
    PROBLEMS,
    AuditNotDurable,
    ClockDriftBlocked,
    EnvironmentMismatch,
    ExchangeUnavailable,
    IdempotencyInFlight,
    IdempotencyKeyReuse,
    LotSizeViolation,
    OmsError,
    OrderEntryRefused,
    OrderInvalid,
    OrderLinkIdExhausted,
    OrderStepUnknown,
    ProfileNotFound,
    RateBudgetExceeded,
    RiskRefused,
    StopRequestPending,
    StoreUnavailable,
    TickSizeViolation,
    TradingDisabled,
    problem_for,
)
from candleviewer.oms.idempotency import STUCK_AFTER_S, AnchorService, Fresh, Replay
from candleviewer.oms.order_link import OrderLinkIdParts
from candleviewer.oms.order_link_allocator import MAX_SEQ_INCREMENTS
from candleviewer.oms.order_machine import OrderMachines
from candleviewer.oms.ports import KeyedRecord, RequestRecord, SizingRequest, StopOffset
from candleviewer.oms.repository import IdempotencyAnchorRepository
from candleviewer.oms.submit import (
    PLACE_WAIT_S,
    READ_RETRY_AFTER_S,
    RECONCILING,
    RESULT_WAIT_S,
    STORE_TIMEOUT_S,
    OrderRequest,
    OrderTrigger,
    SubmitOutcome,
    _after_anchor_s,
    entry_order_id,
)
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.config import CV_PERSIST_TIMEOUT
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.account_profiles import AccountProfileRow
from candleviewer.storage.repositories.idempotency_anchors import AnchorOutcome
from candleviewer.storage.repositories.orders import OrderRow
from candleviewer.storage.repositories.recorded_stops import NewRecordedStop
from candleviewer.storage.repositories.trade_groups import TradeGroupRecord
from tests.unit.oms import command_rig as cr
from tests.unit.oms.submit_rig import (
    ACTOR,
    KEY,
    QTY,
    REFERENCE,
    REGISTRY,
    REQUEST_ID,
    SHA,
    STOP,
    SYMBOL,
    TAKE_PROFIT,
    SubmitRig,
    build_rig,
    context,
    entry,
    flatten,
    profile,
    rigged,
)

_DUP = OmsErrorCode.DUPLICATE_CLIENT_ID.value


@pytest.fixture
async def rig(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[SubmitRig]:
    monkeypatch.setattr(b01, "_ATTEMPTS", OrderedDict())
    built = build_rig()
    yield built
    await built.machines.stop()


async def _refused(rig: SubmitRig, request: Any = None, ctx: Any = None) -> OmsError:
    with pytest.raises(OmsError) as refused:
        await rig.submit(request, ctx)
    return refused.value


def _denied(rig: SubmitRig) -> list[RequestRecord]:
    return [
        r for r in rig.records("orders.submit")
        if isinstance(r, RequestRecord) and r.outcome == "denied"
    ]  # fmt: skip


def _nothing_done(rig: SubmitRig) -> None:
    """Nothing recorded, nothing sent, no key bound (C-2.10)."""
    assert rig.calls() == [] and rig.written() == (0, 0, 0, 0)


def _create(call: FakeCall) -> PlaceOrderRequest:
    """The create a `place_order` call carried."""
    assert isinstance(call.request, PlaceOrderRequest)
    return call.request


def _creates(port: cr.Rig) -> list[PlaceOrderRequest]:
    """Every create the rig's two venue doubles took (`place_order`), demo's first."""
    return [_create(c) for c in (*port.demo.calls, *port.live.calls) if c.method == "place_order"]


@pytest.fixture(autouse=True)
def stops_on_every_create(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[cr.Rig]]:
    """C-2.6 on every path of this module: once a test ends, every create that is not reduce-only
    and that a venue double of any rig the test built took (the `rig` fixture's, `rigged()`'s, a
    restart's pipeline over either) carries its native stop. It is read off the doubles' own call
    records, never off the pipeline or a mock of it; a create without one errors its test."""
    built: list[cr.Rig] = []
    build = cr.build_rig

    def recording(**kwargs: Any) -> cr.Rig:
        port = build(**kwargs)
        built.append(port)
        return port

    monkeypatch.setattr(cr, "build_rig", recording)
    yield built
    creates = [create for port in built for create in _creates(port)]
    bare = [c.order_link_id for c in creates if not c.reduce_only and c.stop_loss is None]
    assert bare == [], "an entry reached the venue without its native stop (C-2.6)"


def _row(rig: SubmitRig, outcome: SubmitOutcome) -> OrderRow:
    assert outcome.order_id is not None
    return rig.store._orders[outcome.order_id]


def _group(rig: SubmitRig, outcome: SubmitOutcome) -> TradeGroupRecord:
    assert outcome.trade_group_id is not None
    return rig.store._groups[outcome.trade_group_id]


def _position(**over: Any) -> Any:
    """The demo account's long position of 0.050 BTCUSDT, which a flatten reduces."""
    return cr.position(**({"qty": "0.050"} | over))


# --- the accepted path ----------------------------------------------------------------------------


async def test_an_entry_is_recorded_then_sent_once_and_answered_202(rig: SubmitRig) -> None:
    """24 Sec.8.4: an acknowledgement, not a fill. The create carries the order's stop and
    take-profit (C-2.6), its key is the account's own (SR-E27-21) and its lane the entry's."""
    outcome = await rig.submit()
    assert (outcome.status, outcome.lifecycle, outcome.code) == (202, "submitted", None)
    assert outcome.replayed is False and outcome.retry_after_s is None
    [call] = rig.port.demo.calls
    sent = _create(call)
    assert (call.method, call.lane) == ("place_order", "entry")
    assert (sent.stop_loss, sent.take_profit, sent.qty, sent.price) == (
        STOP, TAKE_PROFIT, QTY, REFERENCE,
    )  # fmt: skip
    assert sent.account == cr.ref() and sent.account.key_ref == cr.KEYS["demo"]
    row = _row(rig, outcome)
    assert (row.lifecycle_state, row.stop_loss, row.take_profit) == ("submitted", STOP, TAKE_PROFIT)
    assert (row.order_link_id, row.provenance) == (sent.order_link_id, "placed")
    stored = rig.store._anchors[outcome.anchor_id]
    assert stored.anchor.trade_group_id == outcome.trade_group_id is not None
    assert stored.outcome is not None and stored.outcome.status == 202
    record = _group(rig, outcome)
    assert record.group.status == "submitting"
    assert [(leg.id, leg.status) for leg in record.legs] == [(row.trade_group_leg_id, "submitted")]
    sides = sorted((s.kind, s.source, s.trigger_price) for s in rig.store._stops.values())
    assert sides == [
        ("stop_loss", "entry_attach", STOP),
        ("take_profit", "entry_attach", TAKE_PROFIT),
    ]


async def test_an_entrys_records_are_written_ahead_of_its_rows_and_the_outcome_after(
    rig: SubmitRig,
) -> None:
    """C-2.9: `orders.submit`, `trade_group.submit` and each stop request's keyed record in the
    persist's transaction, before the send; then the outcome. Ids and states only (C-12.6)."""
    outcome = await rig.submit()
    written = rig.port.audits.written
    names = [
        (r.action, r.reason, sent) for r, sent in written if not r.action.startswith("orders.c")
    ]
    assert names[:4] == [
        ("orders.submit", "validated", 0),
        ("trade_group.submit", "submitting", 0),
        ("sl.attached", "entry_attach", 0),
        ("tp.modified", "entry_attach", 0),
    ]
    assert names[-1] == ("orders.submit", "submitted", 1)
    stops = {s.kind: s for s in rig.store._stops.values()}
    for record, _ in written[2:4]:
        assert isinstance(record, KeyedRecord)
        row = stops["stop_loss" if record.action == "sl.attached" else "take_profit"]
        assert (record.name, record.object_id) == (str(row.id), row.id)
        assert row.audit_record_id == rig.port.audits.record_id(record.action, record.name)
        assert record.actor == ACTOR and record.actor_user_id == ACTOR.user_id
    intent = written[0][0]
    assert isinstance(intent, RequestRecord) and intent.object_id == outcome.order_id
    for value in intent.detail.values():
        assert value is None or ("60000" not in value and "0.010" not in value)


async def test_every_record_carries_the_requests_correlation_id(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[AUDIT-REQUEST-ID]: the order's, its group's, its stops', its outcome's and B1's adoption
    record (through `commands.expect`) carry `X-Correlation-Id`."""
    demo = rig.port.demo
    land = demo.place_order

    async def duplicate(request: Any) -> Any:
        await land(request)  # the create landed: the venue holds it under its id
        raise DuplicateClientIdError("the order_link_id was already accepted")

    monkeypatch.setattr(demo, "place_order", duplicate)
    outcome = await rig.submit()
    assert (outcome.status, outcome.lifecycle) == (202, "submitted")
    actions = [r.action for r in rig.records()]
    assert actions.count("orders.submit") == 3  # the intent, the adoption, the outcome
    assert {r.request_id for r in rig.records()} == {REQUEST_ID}


async def test_a_jobs_records_carry_no_correlation_id(rig: SubmitRig) -> None:
    """[AUDIT-REQUEST-ID]: a request no HTTP request carries (a job) records None in each."""
    await rig.submit(entry(), context(request_id=None))
    assert rig.records() and {r.request_id for r in rig.records()} == {None}


# --- steps 1 to 8: each refusal before anything is recorded or sent, audited first --------------


async def test_a_clock_halt_refuses_before_anything_and_is_counted(rig: SubmitRig) -> None:
    rig.port.health.measure(offset_ms=5_000)  # past the hard threshold: order entry halts
    refused = await _refused(rig)
    assert isinstance(refused, ClockDriftBlocked) and refused.retry_after_s == 5
    _nothing_done(rig)
    assert rig.count("oms_clock_drift_blocked_total") == 1
    assert rig.port.accounts.asked == []  # nothing read either


async def test_the_read_only_gate_refuses_after_the_clock(rig: SubmitRig) -> None:
    rig.read_only.is_read_only = True
    refused = await _refused(rig)
    assert problem_for(refused).code == "trading_disabled"
    _nothing_done(rig)


async def test_an_account_the_oms_does_not_trade_is_refused_as_out_of_scope(rig: SubmitRig) -> None:
    refused = await _refused(rig, entry(account_id=AccountId(uuid4())))
    assert problem_for(refused).code == "account_scope_denied"
    _nothing_done(rig)


async def test_an_account_with_no_route_for_its_environment_pages(rig: SubmitRig) -> None:
    """C-2.11: a testnet account, where only demo and live are routed, never reaches a port."""
    testnet = AccountId(uuid4())
    rig.port.accounts.seed(
        cr.ref().model_copy(update={"account_id": testnet, "environment": "testnet"})
    )
    refused = await _refused(rig, entry(account_id=testnet))
    assert isinstance(refused, EnvironmentMismatch)
    problem = problem_for(refused)
    assert (problem.status, problem.pages) == (500, True)
    _nothing_done(rig)


async def test_a_leg_outside_its_groups_environment_is_a_fault_with_nothing_written(
    rig: SubmitRig,
) -> None:
    """D-2B1-02 (C-2.11): the rig seeds every `AccountRef` it trades with, so its store meets
    `trg_tgl_env` as Postgres does. An account the store holds as live, which the trading port
    answers as demo, puts a demo group's leg outside its environment: the first persist refuses
    the order's own rows, a fault (500), with nothing written or sent."""
    assert rig.store._environments == {cr.ACCOUNT: "demo", cr.LIVE_ACCOUNT: "live"}
    rig.submissions.seed_account(cr.ref(cr.ACCOUNT, "live"))  # its row says live: a miswire
    refused = await _refused(rig)
    problem = problem_for(refused)
    assert (problem.status, problem.code) == (500, "internal_error")
    [record] = _denied(rig)
    assert record.reason == "internal_error"
    _nothing_done(rig)


async def test_a_symbol_no_instrument_lists_is_refused_400(rig: SubmitRig) -> None:
    refused = await _refused(rig, entry(symbol="NOPEUSDT"))
    assert isinstance(refused, OrderInvalid)
    assert [(e.field, e.rule) for e in refused.errors] == [("symbol", "listed")]
    _nothing_done(rig)


@pytest.mark.parametrize("part", ["accounts", "instruments", "profiles"])
async def test_a_read_that_fails_before_the_persist_is_503_store_unavailable(
    rig: SubmitRig, part: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """24 Sec.8.4: the order cannot be recorded before its send, so nothing reaches the exchange."""
    if part == "accounts":

        async def down(_account_id: Any) -> Any:
            raise StorageTierUnavailable("postgres unreachable")

        monkeypatch.setattr(rig.port.accounts, "trading_account", down)
    elif part == "instruments":
        rig.instruments.refuse = StorageTierUnavailable("postgres unreachable")
    else:
        rig.profiles.refuse = ProfileUnavailableError("the store timed out")
    refused = await _refused(rig)
    assert isinstance(refused, StoreUnavailable)
    _nothing_done(rig)


async def test_a_store_read_past_its_bound_is_503_with_nothing_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with rigged(store_timeout_s=0.01) as rig:

        async def hangs(_symbol: Any) -> Any:
            await asyncio.Event().wait()

        monkeypatch.setattr(rig.instruments, "instrument", hangs)
        refused = await _refused(rig)
        assert isinstance(refused, StoreUnavailable)
        _nothing_done(rig)


async def test_an_entry_with_no_profile_is_refused_403(rig: SubmitRig) -> None:
    """D11: no profile allows nothing; never a default (SR-E28-24)."""
    rig.profiles.held.clear()
    refused = await _refused(rig)
    assert isinstance(refused, RiskRefused)
    _nothing_done(rig)


#: A `profile_id` a request names.
_NAMED = UUID("5f0e1d2c-3b4a-4c96-8877-665544332211")


def _profile_not_found(rig: SubmitRig, refused: OmsError) -> None:
    """22 `PlaceOrderRequest.profile_id`: one answer whatever the case, recorded denied first at
    the resolve step (C-2.9), naming no profile (no oracle of which case it was)."""
    assert isinstance(refused, ProfileNotFound) and refused.detail == "No such profile."
    assert (problem_for(refused).status, problem_for(refused).code) == (404, "not_found")
    [record] = _denied(rig)
    assert (record.reason, record.object_id) == ("not_found", cr.ACCOUNT)
    assert record.detail == {
        "step": "resolve", "code": "not_found", "symbol": SYMBOL, "environment": "demo",
        "order_link_id": None,
    }  # fmt: skip


@pytest.mark.parametrize("held", ["another_accounts", "missing"])
@pytest.mark.parametrize(
    "request_",
    [entry(profile_id=_NAMED), flatten(profile_id=_NAMED)],
    ids=["entry", "reduce_only"],
)
async def test_a_named_profile_the_account_does_not_hold_is_404_with_nothing_done(
    rig: SubmitRig, held: str, request_: OrderRequest
) -> None:
    """SEC-2B2-01's IDOR, its profile part: another account's profile and one that does not exist
    are refused alike, `404 not_found` before the order is sized, nothing recorded or sent; a
    reduce-only order too, never let through without the profile it names. The double answers
    each as `EffectiveProfiles` does (no such profile of the account)."""
    if held == "another_accounts":
        foreign = profile(cr.LIVE_ACCOUNT, profile_id=str(_NAMED), is_default=False)
        rig.profiles.held[(cr.LIVE_ACCOUNT, _NAMED)] = foreign
    refused = await _refused(rig, request_)
    _profile_not_found(rig, refused)
    _nothing_done(rig)


async def test_a_deleted_profile_is_404_as_a_missing_one_is(rig: SubmitRig) -> None:
    """The profile an earlier order named, once deleted (the store reads no deleted row, and the
    write invalidates the cache), answers as one never seen: nothing more recorded or sent."""
    rig.profiles.held[(cr.ACCOUNT, _NAMED)] = profile(profile_id=str(_NAMED), is_default=False)
    assert (await rig.submit(entry(profile_id=_NAMED))).status == 202
    del rig.profiles.held[(cr.ACCOUNT, _NAMED)]
    written, calls = rig.written(), rig.calls()
    refused = await _refused(rig, entry(profile_id=_NAMED), context(client_ref=uuid4()))
    _profile_not_found(rig, refused)
    assert (rig.written(), rig.calls()) == (written, calls)


class _AnyAccountsRow:
    """`EffectiveProfileReads` over a store that ignores the account: it answers every read with
    the one `row`, and records what it was asked."""

    def __init__(self, row: AccountProfileRow) -> None:
        self.row = row
        self.asked: list[tuple[UUID, UUID | None]] = []

    async def effective_profile(
        self, account_id: UUID, profile_id: UUID | None
    ) -> AccountProfileRow | None:
        self.asked.append((account_id, profile_id))
        return self.row


def _stored(held: AccountProfile) -> AccountProfileRow:
    """`held` as the profiles table returns it."""
    at = datetime(2026, 10, 20, 9, tzinfo=UTC)
    return AccountProfileRow(
        id=held.profile_id, exchange_account_id=held.account_id, version=held.version,
        values=profile_values(held), created_by=None, updated_by=None, created_at=at,
        updated_at=at, deleted_at=None,
    )  # fmt: skip


async def test_a_profile_row_of_another_account_is_404_over_the_real_effective_profiles(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `rig`'s double keys on `(account, profile)`, so another account's row is never asked
    for there. The guard is `EffectiveProfiles`' own (C-12.4): a store that answers the named
    profile with another account's row gets `404 not_found` for the order, the one answer for
    every case, with nothing recorded or sent."""
    foreign = profile(cr.LIVE_ACCOUNT, profile_id=str(_NAMED), is_default=False)
    reads = _AnyAccountsRow(_stored(foreign))
    cache = EffectiveProfiles(reads)
    monkeypatch.setattr(rig.pipeline, "_deps", replace(rig.pipeline._deps, profiles=cache))
    try:
        refused = await _refused(rig, entry(profile_id=_NAMED))
    finally:
        await cache.aclose()
    _profile_not_found(rig, refused)
    _nothing_done(rig)
    assert reads.asked == [(cr.ACCOUNT, _NAMED)]  # it reached the store, and refused its answer


async def test_an_unnamed_reduce_only_order_with_no_default_profile_goes_through(
    rig: SubmitRig,
) -> None:
    """With none named and the account holding no default, an order that only reduces is never
    refused for want of a profile (SR-E28-24, SR-E28-27), nor is it a 404: it is recorded and
    sent as the exits' lane takes it, where an entry in this state is 403 (D11)."""
    rig.profiles.held.clear()
    rig.port.demo.seed_position(_position())
    outcome = await rig.submit(flatten())
    assert (outcome.status, outcome.lifecycle, outcome.trade_group_id) == (202, "submitted", None)
    assert rig.calls() == ["positions", "place_order"]
    sent = rig.port.demo.calls[1]
    assert (sent.lane, _create(sent).reduce_only) == ("critical", True)
    assert _denied(rig) == []


@pytest.mark.parametrize(
    ("request_", "field", "rule"),
    [
        (
            entry(sizing=SizingRequest(mode="fixed_notional")),
            "sizing.mode",
            "sizing_mode_unsupported",
        ),
        (
            entry(stop_loss=StopOffset(unit="atr", value=Decimal(2))),
            "stop_loss",
            "stop_unit_unsupported",
        ),
        (
            entry(take_profit=StopOffset(unit="r_multiple", value=Decimal(2))),
            "take_profit",
            "stop_unit_unsupported",
        ),
        (
            entry(take_profit=StopOffset(unit="atr", value=Decimal(2))),
            "take_profit",
            "stop_unit_unsupported",
        ),
        (
            entry(stop_loss=StopOffset(unit="price", value=Decimal(61000))),
            "stop_loss",
            "native_stop_required",
        ),
        (
            entry(take_profit=StopOffset(unit="price", value=Decimal(59000))),
            "take_profit",
            "take_profit_side",
        ),
        (entry(intent="take_profit"), "intent", "intent_mismatch"),
    ],
    ids=["sizing", "atr_stop", "r_multiple_tp", "atr_tp", "stop_side", "tp_side", "intent"],
)
async def test_the_classify_step_refuses_with_the_rule_that_failed(
    rig: SubmitRig, request_: Any, field: str, rule: str
) -> None:
    """R4's interims and S2-Q6, the native stop (C-2.6) and the intent rule (SR-E29-01)."""
    refused = await _refused(rig, request_)
    assert isinstance(refused, OrderInvalid)
    assert [(e.field, e.rule) for e in refused.errors] == [(field, rule)]
    _nothing_done(rig)


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity", "-Infinity", "sNaN"])
@pytest.mark.parametrize("side", ["stop_loss", "take_profit"])
async def test_a_stop_or_take_profit_that_is_no_price_above_zero_is_never_recorded(
    rig: SubmitRig, side: str, value: str
) -> None:
    """#2877 ruling 2: refused here, before anything is recorded, whatever the command port and
    the exchange port would check later."""
    offset = StopOffset(unit="price", value=Decimal(value))
    refused = await _refused(rig, entry(**{side: offset}))
    assert isinstance(refused, OrderInvalid)
    assert [e.field for e in refused.errors] == [side]
    _nothing_done(rig)


async def test_an_entry_without_a_stop_takes_the_profiles_offset(rig: SubmitRig) -> None:
    """C-2.6: no field waives the stop; the profile's 1 % offset applies, rounded away from the
    entry, and the create carries it."""
    outcome = await rig.submit(entry(stop_loss=None, take_profit=None))
    [call] = rig.port.demo.calls
    assert outcome.status == 202 and _create(call).stop_loss == Decimal("59400.0")
    assert _row(rig, outcome).stop_loss == Decimal("59400.0")


async def test_an_entry_with_neither_a_stop_nor_a_profile_offset_is_refused(rig: SubmitRig) -> None:
    rig.profiles.held[(cr.ACCOUNT, None)] = profile(sl_offset_unit="atr")
    refused = await _refused(rig, entry(stop_loss=None))
    assert [(e.field, e.rule) for e in getattr(refused, "errors", ())] == [
        ("stop_loss", "stop_unit_unsupported")
    ]
    _nothing_done(rig)


@pytest.mark.parametrize("failure", ["raises", "hangs"])
async def test_a_reduce_only_orders_position_read_that_fails_is_503_with_retry_after(
    failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Q-B: the effect cannot be read, so it is no answer: 503 `exchange_unavailable` with
    `Retry-After`, nothing recorded, and the read the only call."""
    async with rigged(position_timeout_s=0.01) as rig:
        if failure == "raises":
            rig.port.demo.script("positions", ServiceUnavailableError("the venue is restarting"))
        else:

            async def hangs(_account: Any) -> Any:
                await asyncio.Event().wait()

            monkeypatch.setattr(rig.port.demo, "positions", hangs)
        refused = await _refused(rig, flatten())
        assert isinstance(refused, ExchangeUnavailable)
        assert refused.retry_after_s == READ_RETRY_AFTER_S == 1  # one name, one second
        assert problem_for(refused).code == "exchange_unavailable"
        assert rig.written() == (0, 0, 0, 0)
        assert [c for c in rig.calls() if c != "positions"] == []


@pytest.mark.parametrize("answer", ["none", "raises", "zero", "nan"])
async def test_a_market_orders_reference_price_that_cannot_be_read_is_503(
    rig: SubmitRig, answer: str
) -> None:
    if answer == "raises":
        rig.prices.refuse = TimeoutError()
    else:
        rig.prices.price = {"none": None, "zero": Decimal(0), "nan": Decimal("NaN")}[answer]
    refused = await _refused(rig, entry(order_type="market", price=None))
    assert isinstance(refused, ExchangeUnavailable)
    assert refused.retry_after_s == READ_RETRY_AFTER_S
    _nothing_done(rig)


async def test_a_limit_order_is_measured_from_its_own_price_and_reads_no_market(
    rig: SubmitRig,
) -> None:
    await rig.submit()
    assert rig.prices.asked == []


@pytest.mark.parametrize("price", ["NaN", "0", "-60000"])
async def test_an_own_price_no_step_can_judge_is_refused_400(rig: SubmitRig, price: str) -> None:
    refused = await _refused(rig, entry(price=Decimal(price)))
    assert isinstance(refused, OrderInvalid) and [e.field for e in refused.errors] == ["price"]
    _nothing_done(rig)


async def test_the_validator_judges_the_sized_order(rig: SubmitRig) -> None:
    """SR-E29-04: the instrument filters on the sized, rounded order: off its tick, 400."""
    refused = await _refused(rig, entry(price=Decimal("60000.05")))
    assert isinstance(refused, TickSizeViolation)
    _nothing_done(rig)


async def test_a_symbol_the_profile_does_not_allow_is_refused_403(rig: SubmitRig) -> None:
    rig.profiles.held[(cr.ACCOUNT, None)] = profile(allowed_symbols=["ETHUSDT"])
    refused = await _refused(rig)
    assert isinstance(refused, RiskRefused)
    _nothing_done(rig)


async def test_the_risk_gate_sees_the_sized_rounded_order_and_refuses_live(rig: SubmitRig) -> None:
    """SR-E29-04 and R4: the gate judges the order as sized and floored to the lot step; the
    interim gate refuses every live order before anything is recorded."""
    await rig.submit(entry(sizing=SizingRequest(mode="fixed_qty", qty=Decimal("0.0109"))))
    assert [order.qty for order in rig.risk.seen] == [Decimal("0.010")]
    rig.profiles.held[(cr.LIVE_ACCOUNT, None)] = profile(cr.LIVE_ACCOUNT)
    before = rig.written()
    refused = await _refused(rig, entry(account_id=cr.LIVE_ACCOUNT), context(client_ref=uuid4()))
    assert isinstance(refused, RiskRefused) and rig.written() == before
    assert rig.port.live.calls == []


async def test_the_switches_refuse_just_before_the_persist(rig: SubmitRig) -> None:
    """Ruling R1's second check: the kill switch, live trading or the order-entry gate, asked
    after the route's own check, refuse with nothing recorded; the gate's refusal keeps its
    reason."""
    rig.port.switches.refusals[cr.ACCOUNT] = TradingDisabled()
    assert isinstance(await _refused(rig), TradingDisabled)
    _nothing_done(rig)
    gate = OrderEntryRefusal("account_unhealthy", "The account is not healthy enough to trade.")
    rig.port.switches.refusals[cr.ACCOUNT] = OrderEntryRefused(gate)
    refused = await _refused(rig)
    assert isinstance(refused, OrderEntryRefused) and refused.reason == "account_unhealthy"
    _nothing_done(rig)
    assert rig.port.switches.asked == [(cr.ACCOUNT, "demo")] * 2


async def test_rate_point_one_refuses_429_with_retry_after_and_binds_no_key(rig: SubmitRig) -> None:
    """24 Sec.8.4 point 4: the headroom read takes no token and sends nothing; the same key and
    body after `Retry-After` are a first submission."""
    rig.port.demo.set_headroom(cr.ACCOUNT, RateHeadroom(lane="entry", tokens=0.0, wait_s=2.5))
    refused = await _refused(rig)
    assert isinstance(refused, RateBudgetExceeded) and refused.retry_after_s == 3
    _nothing_done(rig)
    assert rig.count("oms_rate_reject_total") == 1
    rig.port.demo.set_headroom(cr.ACCOUNT, RateHeadroom(lane="entry", tokens=1.0, wait_s=0.0))
    assert (await rig.submit()).status == 202


async def test_allocation_spent_at_sixteen_collisions_pages_with_nothing_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """24 Sec.8.3 rule 5: every candidate taken, 500 that pages, nothing recorded or sent."""
    async with rigged() as rig:

        async def taken(_link: str) -> bool:
            return True

        monkeypatch.setattr(rig.lookup, "exists", taken)
        refused = await _refused(rig)
        assert isinstance(refused, OrderLinkIdExhausted)
        assert problem_for(refused).pages is True
        _nothing_done(rig)


async def test_allocation_spent_at_seq2_3843_pages_with_nothing_written(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rule 5's other bound: a candidate already at `seq2` 3843 that is taken goes no further."""
    generate = OrderLinkIdParts.generate

    def last(**kwargs: Any) -> OrderLinkIdParts:
        return generate(**kwargs).with_seq(3843)

    async def taken(_link: str) -> bool:
        return True

    monkeypatch.setattr(OrderLinkIdParts, "generate", staticmethod(last))
    monkeypatch.setattr(rig.lookup, "exists", taken)
    refused = await _refused(rig)
    assert isinstance(refused, OrderLinkIdExhausted)
    _nothing_done(rig)


# --- every refusal is recorded first, and counted ------------------------------------------------


async def test_a_refusal_is_audited_denied_with_its_code_before_it_is_raised(
    rig: SubmitRig,
) -> None:
    """C-2.9: the requesting principal, the account, the problem code and the step; never a
    price (C-12.6)."""
    rig.read_only.is_read_only = True
    await _refused(rig)
    [record] = _denied(rig)
    assert (record.action, record.outcome, record.reason) == (
        "orders.submit",
        "denied",
        "trading_disabled",
    )
    assert (record.object_kind, record.object_id) == ("exchange_account", cr.ACCOUNT)
    assert (record.actor, record.request_id) == (ACTOR, REQUEST_ID)
    assert record.detail == {
        "step": "clock", "code": "trading_disabled", "symbol": SYMBOL, "environment": None,
        "order_link_id": None,
    }  # fmt: skip
    assert rig.count("oms_submit_rejected_total", code="trading_disabled") == 1


async def test_a_refusal_whose_record_does_not_land_is_503_audit_unavailable(
    rig: SubmitRig,
) -> None:
    """No refusal is answered unrecorded (C-2.9)."""
    rig.read_only.is_read_only = True
    rig.port.audits.refuse = OSError("the audit lane is down")
    refused = await _refused(rig)
    assert isinstance(refused, AuditNotDurable)
    problem = problem_for(refused)
    assert (problem.status, problem.code) == (503, "audit_unavailable")
    assert rig.count("oms_submit_rejected_total", code="audit_unavailable") == 1


async def test_a_defect_is_recorded_as_an_internal_error_and_raised(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise ZeroDivisionError("a broken port")

    monkeypatch.setattr(rig.pipeline._ports.risk_gate, "check", broken)
    with pytest.raises(ZeroDivisionError):
        await rig.submit()
    [record] = _denied(rig)
    assert record.reason == "internal_error" and record.severity == "error"
    _nothing_done(rig)


# --- step 9: the first persist and the Q4 loop ----------------------------------------------------


def _in_flight(**over: Any) -> NewRecordedStop:
    """A trading-stop request in flight on the demo account's BTCUSDT position 0."""
    values: dict[str, Any] = {
        "id": uuid4(), "exchange_account_id": cr.ACCOUNT, "symbol": SYMBOL, "position_idx": 0,
        "position_side": "Buy", "kind": "stop_loss", "source": "trading_stop", "order_id": None,
        "tpsl_mode": "Full", "trigger_price": Decimal(57000), "size": None,
        "audit_record_id": uuid4(), "actor_user_id": None,
    }  # fmt: skip
    return NewRecordedStop(**(values | over))


async def _record_in_flight(rig: SubmitRig) -> NewRecordedStop:
    stop = _in_flight()

    async def audited(_rows: Any) -> None:
        return None

    await rig.port.stops.record([stop], write_ahead=audited)
    return stop


async def test_a_stop_request_in_flight_is_retried_twice_then_409_with_the_key_unbound(
    rig: SubmitRig,
) -> None:
    """Q-D: one try and two retries, after 0.1 s and 0.25 s, then 409 `stop_request_in_flight`
    with `Retry-After` 1; nothing recorded, nothing sent, and the key free for the same request."""
    stop = await _record_in_flight(rig)
    refused = await _refused(rig)
    assert isinstance(refused, StopRequestPending) and refused.retry_after_s == 1
    assert problem_for(refused).code == "stop_request_in_flight"
    assert rig.sleeps.waits == [0.1, 0.25]
    assert rig.calls() == [] and rig.written()[:3] == (0, 0, 0)
    await rig.port.stops.settle(cr.ACCOUNT, [stop.id], "answered", at=cr.T0)
    assert (await rig.submit()).status == 202  # the same key and body: a first submission


async def test_a_stop_request_answered_between_tries_lets_the_entry_through(rig: SubmitRig) -> None:
    stop = await _record_in_flight(rig)

    async def answered() -> None:
        await rig.port.stops.settle(cr.ACCOUNT, [stop.id], "answered", at=cr.T0)

    rig.sleeps.then = answered
    outcome = await rig.submit()
    assert outcome.status == 202 and rig.sleeps.waits == [0.1]


async def test_a_row_waiting_for_the_complete_read_refuses_at_once_with_retry_after_5(
    rig: SubmitRig,
) -> None:
    """24 Sec.8.4: 409 at once, nothing tried or sent, and the complete read it started runs on,
    so the same request, sent again once that read voided the row, is a first submission."""
    stop = await _record_in_flight(rig)
    rig.port.now.us += 11_000_000  # past the request's bound: it waits for the complete read
    refused = await _refused(rig)
    assert isinstance(refused, StopRequestPending) and refused.retry_after_s == 5
    assert rig.sleeps.waits == [] and "place_order" not in rig.calls()
    for _ in range(10_000):  # the read runs on: a bound on the test, not a time
        if rig.port.store._stops[stop.id].status == "void":
            break
        await asyncio.sleep(0)
    assert rig.port.store._stops[stop.id].status == "void"
    assert (await rig.submit()).status == 202


async def test_a_stop_gate_that_does_not_answer_is_503_with_nothing_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2.18 (`StopRequestGate`: the caller bounds `clear`, whatever the gate bounds itself):
    the gate's clear is a store read of the pipeline's, within `store_timeout_s`, so one that never
    answers is 503 `store_unavailable`, with nothing recorded or sent and no key bound."""
    async with rigged(store_timeout_s=0.01) as rig:

        async def hangs(_key: Any) -> None:
            await asyncio.Event().wait()

        monkeypatch.setattr(rig.pipeline._deps.gate, "clear", hangs)
        async with asyncio.timeout(5.0):  # an unbounded clear fails here, never hangs the run
            refused = await _refused(rig)
        assert isinstance(refused, StoreUnavailable)
        _nothing_done(rig)


async def test_a_reduce_only_order_records_no_stop_request_and_asks_no_gate(rig: SubmitRig) -> None:
    """Q-O: a reduce-only order records no stop of its own, so it meets no stop request."""
    await _record_in_flight(rig)
    rig.port.demo.seed_position(_position())
    outcome = await rig.submit(flatten(sizing=SizingRequest(mode="fixed_qty", qty=QTY)))
    assert outcome.status == 202 and rig.sleeps.waits == []


async def test_a_taken_order_link_id_is_allocated_again_from_the_same_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """24 Sec.8.3 rule 5's race: the check saw the id free, the insert met `ux_orders_link`;
    the persist rolled back, and the next id from the same candidate is sent."""
    async with rigged() as rig:
        first = await rig.submit()
        link = _row(rig, first).order_link_id
        rig.lookup.lies = 1  # the next check misses the stored id once

        def same(**_kwargs: Any) -> OrderLinkIdParts:
            return OrderLinkIdParts.parse(link)

        monkeypatch.setattr(OrderLinkIdParts, "generate", staticmethod(same))
        second = await rig.submit(entry(), context(client_ref=uuid4()))
        sent = _row(rig, second).order_link_id
        assert sent != link and second.status == 202
        assert rig.calls() == ["place_order", "place_order"]


async def test_order_link_id_races_past_the_bound_page_with_nothing_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller gives up after `MAX_SEQ_INCREMENTS` violations too, so a lookup that disagrees
    with the index never loops (the allocator's docstring)."""
    async with rigged(lies=10_000) as rig:
        first = await rig.submit()
        link = _row(rig, first).order_link_id
        rig.port.demo.calls.clear()
        written = rig.written()

        def same(**_kwargs: Any) -> OrderLinkIdParts:
            return OrderLinkIdParts.parse(link)

        monkeypatch.setattr(OrderLinkIdParts, "generate", staticmethod(same))
        refused = await _refused(rig, entry(), context(client_ref=uuid4()))
        assert isinstance(refused, OrderLinkIdExhausted)
        assert rig.written() == written and rig.calls() == []
        assert len(rig.lookup.asked) == 1 + 1 + MAX_SEQ_INCREMENTS


@pytest.mark.parametrize(
    ("reason", "refusal", "code"),
    [("account_not_live", TradingDisabled, "trading_disabled"),
     ("profile_changed", RiskRefused, "risk_limit_breached")],
)  # fmt: skip
async def test_the_share_locked_recheck_refuses_403_with_nothing_written(
    rig: SubmitRig, reason: Any, refusal: type[OmsError], code: str
) -> None:
    """SR-E28-15: the account or the leg's profile is no longer live under the persist's locks."""
    rig.submissions.refuse(cr.ACCOUNT, reason)
    refused = await _refused(rig)
    assert type(refused) is refusal and problem_for(refused).code == code
    _nothing_done(rig)


async def test_a_slow_write_ahead_audit_is_503_audit_unavailable_with_nothing_written(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-2.9: the persist's records must land within the store's bound, else nothing is written."""
    async with rigged(audit_timeout_s=0.01) as rig:
        written = rig.port.audits.write

        async def slow(record: Any) -> None:
            await asyncio.Event().wait()
            await written(record)

        monkeypatch.setattr(rig.port.audits, "write", slow)
        with pytest.raises(AuditNotDurable):
            await rig.pipeline.submit(entry(), context())
        _nothing_done(rig)


async def test_a_write_ahead_audit_refused_is_503_audit_unavailable(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    written = rig.port.audits.write

    async def refuses(record: Any) -> None:
        if getattr(record, "reason", "") == "validated":
            raise OSError("the audit lane is down")
        await written(record)

    monkeypatch.setattr(rig.port.audits, "write", refuses)
    refused = await _refused(rig)
    assert isinstance(refused, AuditNotDurable)
    _nothing_done(rig)


async def test_a_store_that_fails_before_the_send_is_503_with_zero_calls(rig: SubmitRig) -> None:
    """S7: the order cannot be recorded, so nothing reaches the exchange."""
    rig.store.fail_next(StorageTierUnavailable("postgres unreachable"))
    refused = await _refused(rig)
    assert isinstance(refused, StoreUnavailable)
    _nothing_done(rig)


async def test_a_persist_whose_outcome_is_unknown_goes_on_once_the_row_says_validated(
    rig: SubmitRig,
) -> None:
    """S7: the write committed but its answer was lost; the facade rebuilt the order from its
    events, `validated`, so the request goes on to `SEND` once."""
    rig.store.fail_next(TimeoutError(), committed=True)
    outcome = await rig.submit()
    assert outcome.status == 202 and rig.calls() == ["place_order"]
    assert "oms_submit_persist_unknown" not in rig.pager.calls  # a machine owns the order


async def test_a_held_key_is_answered_as_a_repeat_of_its_decided_request(rig: SubmitRig) -> None:
    """21 Sec.3.3.10: a concurrent first persist of the same key committed first and decided;
    this one wrote nothing, sends nothing and replays that outcome, with the order's state now
    (the ruling of 2026-10-22), read by the id its group's names."""
    first = await rig.submit()
    assert first.trade_group_id is not None
    assert first.order_id == entry_order_id(first.trade_group_id)
    rig.port.demo.calls.clear()
    replayed = await rig.submit()
    assert replayed == replace(
        first, order_id=None, lifecycle="submitted", replayed=True, written=None
    )
    assert rig.calls() == [] and len(rig.store._orders) == 1


async def test_a_held_key_still_in_flight_or_with_another_body_is_refused_409(
    rig: SubmitRig,
) -> None:
    await rig.submit()
    rig.store._anchors.update({i: a._replace(outcome=None) for i, a in rig.store._anchors.items()})
    in_flight = await _refused(rig)
    assert isinstance(in_flight, IdempotencyInFlight) and in_flight.retry_after_s == 1
    reused = await _refused(rig, ctx=context(request_sha256="0" * 64))
    assert isinstance(reused, IdempotencyKeyReuse)
    assert rig.calls() == ["place_order"]


async def test_the_routes_own_lookup_replays_what_a_held_keys_repeat_answers(
    rig: SubmitRig,
) -> None:
    """Slice 3's route answers its own lookup's `Replay` with `answer_replay`, which reads the same
    reconciled state as the pipeline's repeat of a held key: nothing sent, no rows of its own."""
    first = await rig.submit()
    lookup = await rig.pipeline._anchors.lookup(ACTOR.user_id, KEY, SHA)
    assert isinstance(lookup, Replay)
    answered = await rig.pipeline.answer_replay(cr.ACCOUNT, lookup)
    assert answered == await rig.submit()
    assert (answered.status, answered.lifecycle, answered.written) == (202, "submitted", None)
    assert (answered.trade_group_id, answered.replayed) == (first.trade_group_id, True)
    assert rig.calls() == ["place_order"]


# --- step 10: SEND --------------------------------------------------------------------------------


async def test_a_send_that_does_not_commit_abandons_the_order_and_is_503(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S2-Q5: the `submitting` step was refused, so nothing was sent and nothing would send it:
    the order is killed from `validated`, the registration dropped, the request 503."""
    original = rig.machines.command

    async def refused_send(*args: Any, **kwargs: Any) -> str:
        rig.store.fail_next(StorageTierUnavailable("postgres unreachable"))
        return await original(*args, **kwargs)

    monkeypatch.setattr(rig.machines, "command", refused_send)
    refused = await _refused(rig)
    assert isinstance(refused, StoreUnavailable)
    await rig.quiet()
    [row] = rig.store._orders.values()
    assert (row.lifecycle_state, row.submit_attempts) == ("killed", 0)
    assert rig.calls() == [] and rig.port.port._watches == {}
    [record] = _denied(rig)
    assert (record.object_kind, record.object_id, record.detail["step"]) == (
        "order",
        row.id,
        "send",
    )


async def test_an_unsent_order_that_cannot_be_abandoned_is_tried_twice_and_paged(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = rig.machines.command
    tries: list[str] = []

    async def refused_send(*args: Any, **kwargs: Any) -> str:
        rig.store.fail_next(StorageTierUnavailable("postgres unreachable"))
        return await original(*args, **kwargs)

    async def stuck(*args: Any) -> str:
        tries.append("abandon")
        raise StorageTierUnavailable("postgres unreachable")

    monkeypatch.setattr(rig.machines, "command", refused_send)
    monkeypatch.setattr(rig.machines, "abandon", stuck)
    with capture_logs() as logs:
        await _refused(rig)
    assert tries == ["abandon", "abandon"]
    assert rig.pager.calls.count("oms_unsent_order_not_abandoned") == 1
    assert any(line["event"] == "oms_unsent_order_not_abandoned" for line in logs)


async def test_a_send_refused_while_the_kill_switch_engaged_answers_the_switch(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Q-P's window: B18 engaged between step 6 and `SEND`; the switch that refuses now is the
    answer, not a store outage."""
    original = rig.machines.command

    async def killed(*args: Any, **kwargs: Any) -> str:
        rig.port.switches.refusals[cr.ACCOUNT] = TradingDisabled()
        rig.store.fail_next(StorageTierUnavailable("postgres unreachable"))
        return await original(*args, **kwargs)

    monkeypatch.setattr(rig.machines, "command", killed)
    assert isinstance(await _refused(rig), TradingDisabled)
    assert rig.calls() == []


# --- step 11: the answer is the state B1 recorded -------------------------------------------------


async def test_a_business_rejection_is_502_with_its_return_code_only(rig: SubmitRig) -> None:
    """SR-E29-09: the code and the exchange's return code, never its text; the anchor records the
    same answer, the leg `rejected` and the group `failed` (S2-Q4)."""
    rig.port.demo.script(
        "place_order",
        FakeReject(OmsErrorCode.INSUFFICIENT_MARGIN, 110007, "ab not enough for new order"),
    )
    outcome = await rig.submit()
    assert (outcome.status, outcome.code, outcome.ret_code, outcome.lifecycle) == (
        502, "exchange_error", 110007, "rejected",
    )  # fmt: skip
    stored = rig.store._anchors[outcome.anchor_id].outcome
    assert stored is not None
    assert (stored.status, stored.code, stored.ret_code) == (502, "exchange_error", 110007)
    record = _group(rig, outcome)
    assert record.group.status == "failed"
    assert [(leg.status, leg.rejection_code) for leg in record.legs] == [
        ("rejected", "INSUFFICIENT_MARGIN")
    ]
    assert rig.count("oms_submit_rejected_total", code="exchange_error") == 1
    texts = [str(r.detail) for r in rig.records()]
    assert not any("not enough" in text for text in texts)


async def test_rate_point_two_answers_429_with_retry_after_and_records_it(rig: SubmitRig) -> None:
    """24 Sec.8.4 point 6: the port got no token, nothing sent, the order `rejected` with
    `RATE_BUDGET_EXCEEDED`; the anchor stores the 429, so a repeat replays it, without
    `Retry-After`."""
    rig.port.demo.script("place_order", RateBudgetExceededError("no token", retry_after_s=1.5))
    outcome = await rig.submit()
    assert (outcome.status, outcome.code, outcome.retry_after_s) == (
        429,
        "exchange_rate_limited",
        2,
    )
    assert _row(rig, outcome).reject_code == "RATE_BUDGET_EXCEEDED"
    assert rig.count("oms_rate_reject_total") == 1
    repeat = await rig.submit()
    assert (repeat.status, repeat.code, repeat.retry_after_s, repeat.replayed) == (
        429, "exchange_rate_limited", None, True,
    )  # fmt: skip


@pytest.mark.parametrize(
    "outcome_",
    [
        LandedThenAmbiguous(),
        ServiceUnavailableError("the venue is restarting", exchange_ret_code=10016),
    ],
    ids=["landed_then_ambiguous", "venue_outage"],
)
async def test_an_outcome_in_doubt_is_202_unknown_after_one_create(
    rig: SubmitRig, outcome_: Any
) -> None:
    """24 Sec.8.2 S1, C-2.10: never a retry, never a 502; the venue's outage too (#4092, #2863)."""
    rig.port.demo.script("place_order", outcome_)
    outcome = await rig.submit()
    assert (outcome.status, outcome.lifecycle, outcome.code) == (202, "unknown", None)
    assert rig.calls() == ["place_order"]
    record = _group(rig, outcome)
    assert [leg.status for leg in record.legs] == ["submitted"]  # S2-Q4: unknown, as submitted


async def test_a_clock_drift_rejection_is_502_and_halts_the_next_request_until_resynced(
    rig: SubmitRig,
) -> None:
    """24 Sec.8.6 `10002`: the create was sent and refused (502 with its code); the command port
    tripped the halt, so the next request is 503 `clock_drift`, until a measurement taken after the
    trip clears it."""
    rig.port.demo.script("place_order", FakeReject(OmsErrorCode.CLOCK_DRIFT, 10002))
    outcome = await rig.submit()
    assert (outcome.status, outcome.ret_code) == (502, 10002)
    resync = rig.port.port.resync_task
    assert resync is not None  # the trip started the clock's resync
    await resync
    blocked = await _refused(rig, entry(), context(client_ref=uuid4()))
    assert isinstance(blocked, ClockDriftBlocked)
    assert rig.count("oms_clock_drift_blocked_total") == 1
    rig.port.monotonic.s += 1.0
    rig.port.health.measure()  # a fresh, healthy measurement after the trip
    assert (await rig.submit(entry(), context(client_ref=uuid4()))).status == 202


async def test_a_duplicate_whose_lookup_matches_is_adopted_202(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """24 Sec.8.3 rule 3: success after lookup; one create, and no second."""
    demo = rig.port.demo
    land = demo.place_order

    async def duplicate(request: Any) -> Any:
        await land(request)
        raise DuplicateClientIdError("the order_link_id was already accepted")

    monkeypatch.setattr(demo, "place_order", duplicate)
    outcome = await rig.submit()
    assert (outcome.status, outcome.lifecycle) == (202, "submitted")
    assert _row(rig, outcome).exchange_order_id is not None


async def test_a_held_order_is_202_and_its_leg_is_left_pending(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Q-M: B1 pages; the operator decides, so the leg stays as the first persist wrote it."""
    demo = rig.port.demo
    land = demo.place_order

    async def squatted(request: Any) -> Any:
        await land(request.model_copy(update={"qty": request.qty * 2}))  # another order
        raise DuplicateClientIdError("the order_link_id was already accepted")

    monkeypatch.setattr(demo, "place_order", squatted)
    outcome = await rig.submit()
    assert (outcome.status, outcome.lifecycle) == (202, "held")
    record = _group(rig, outcome)
    assert [leg.status for leg in record.legs] == ["pending"]
    assert record.group.status == "submitting"


async def test_a_store_failure_after_the_send_is_never_503(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """24 Sec.8.4: the anchor, the leg and the group, and the outcome's record fail; the answer is
    still the order's outcome, each failure logged."""
    rig.groups.refuse = StorageTierUnavailable("postgres unreachable")
    written = rig.port.audits.write
    anchors = rig.store.anchors

    async def no_outcome(record: Any) -> None:
        if getattr(record, "reason", "") == "submitted":
            raise OSError("the audit lane is down")
        await written(record)

    async def no_anchor(*_args: Any) -> bool:
        raise StorageTierUnavailable("postgres unreachable")

    monkeypatch.setattr(rig.port.audits, "write", no_outcome)
    monkeypatch.setattr(anchors, "record_outcome", no_anchor)
    with capture_logs() as logs:
        outcome = await rig.submit()
    assert (outcome.status, outcome.lifecycle) == (202, "submitted")
    events = {line["event"] for line in logs}
    assert {
        "oms_anchor_outcome_unrecorded", "oms_trade_group_status_unrecorded",
        "oms_submit_outcome_unrecorded",
    } <= events  # fmt: skip


async def test_a_stale_leg_is_logged_and_left_alone(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S2-Q4: a compare-and-set that meets another status changes nothing."""
    original = rig.groups.update_leg

    async def moved_on(group_id: Any, leg_id: Any, patch: Any, **kwargs: Any) -> Any:
        record = rig.store._groups[group_id]
        legs = tuple(replace(leg, status="open") for leg in record.legs)
        rig.store._groups[group_id] = replace(record, legs=legs)
        return await original(group_id, leg_id, patch, **kwargs)

    monkeypatch.setattr(rig.groups, "update_leg", moved_on)
    with capture_logs() as logs:
        outcome = await rig.submit()
    assert outcome.status == 202
    assert [leg.status for leg in _group(rig, outcome).legs] == ["open"]
    assert any(line["event"] == "oms_trade_group_status_stale" for line in logs)


@pytest.mark.parametrize(
    ("side", "unit", "value", "sent"),
    [
        ("buy", "ticks", "100", "60010.0"),
        ("buy", "percent", "0.3333", "60199.9"),  # 60199.98, rounded toward the entry
        ("sell", "percent", "0.3333", "59800.1"),  # 59800.02, rounded toward the entry
        ("buy", "price", "64000.07", "64000.0"),
    ],
)
async def test_a_take_profit_offset_is_sent_on_a_tick_rounded_toward_the_entry(
    rig: SubmitRig, side: str, unit: Any, value: str, sent: str
) -> None:
    """S2-Q6 and Q-L: `price`, `ticks` and `percent` (as a client writes it), on the profit side,
    on a tick, rounded toward the entry."""
    stop = StopOffset(unit="price", value=Decimal(61000 if side == "sell" else 58000))
    tp = StopOffset(unit=unit, value=Decimal(value))
    outcome = await rig.submit(entry(side=side, stop_loss=stop, take_profit=tp))
    [create] = rig.port.demo.calls
    assert outcome.status == 202 and _create(create).take_profit == Decimal(sent)
    assert _row(rig, outcome).take_profit == Decimal(sent)


#: An order's own terms, as its first persist wrote them and its row holds them since.
_TERMS = (
    "id", "exchange_account_id", "order_link_id", "symbol", "side", "intent", "order_type", "qty",
    "price", "trigger_price", "trigger_by", "trigger_direction", "take_profit", "stop_loss",
    "tpsl_mode", "time_in_force", "reduce_only", "close_on_trigger", "position_idx",
    "trade_group_leg_id", "provenance",
)  # fmt: skip


@pytest.mark.parametrize(
    ("script", "status"),
    [
        (None, 202),
        (RateBudgetExceededError("no token", retry_after_s=1.5), 429),
        (FakeReject(OmsErrorCode.INSUFFICIENT_MARGIN, 110007, "ab not enough"), 502),
    ],
    ids=["accepted", "rate_limited", "rejected"],
)
async def test_a_first_answer_carries_the_rows_its_persist_wrote(
    rig: SubmitRig, script: Any, status: int
) -> None:
    """Slice 3's finding 7: the route renders a first answer with no read after the send, from the
    rows as the persist wrote them: the order `validated`, its group `submitting` and its leg
    `pending`, whatever the rows hold since."""
    if script is not None:
        rig.port.demo.script("place_order", script)
    outcome = await rig.submit()
    written, row, record = outcome.written, _row(rig, outcome), _group(rig, outcome)
    assert outcome.status == status and written is not None
    assert {n: getattr(written.order, n) for n in _TERMS} == {n: getattr(row, n) for n in _TERMS}
    assert written.order.lifecycle_state == "validated" != row.lifecycle_state
    assert written.group is not None and written.group.id == record.group.id
    assert (written.group.status, written.group.symbol, written.group.side) == (
        "submitting", record.group.symbol, record.group.side,
    )  # fmt: skip
    [leg], [stored] = written.legs, record.legs
    assert (leg.id, leg.status, leg.target_qty, leg.resolved_sl_price) == (
        stored.id, "pending", QTY, STOP,
    )  # fmt: skip


async def test_a_reduce_only_first_answer_carries_its_order_and_no_group(rig: SubmitRig) -> None:
    rig.port.demo.seed_position(_position())
    outcome = await rig.submit(flatten())
    assert outcome.written is not None
    assert (outcome.written.order.id, outcome.written.order.reduce_only) == (outcome.order_id, True)
    assert (outcome.written.group, outcome.written.legs) == (None, ())


# --- the reduce-only path -------------------------------------------------------------------------


async def test_a_reduce_only_order_that_reduces_has_no_group_and_takes_the_critical_lane(
    rig: SubmitRig,
) -> None:
    """SR-E29-01: read against the exchange-truth position, it only reduces: no stop, no group, an
    anchor naming the order, the exits' lane (C-12.7)."""
    rig.port.demo.seed_position(_position())
    outcome = await rig.submit(flatten())
    assert (outcome.status, outcome.trade_group_id) == (202, None)
    assert rig.calls() == ["positions", "place_order"]
    sent = rig.port.demo.calls[1]
    request = _create(sent)
    assert (sent.lane, request.reduce_only, request.stop_loss) == ("critical", True, None)
    assert rig.store._anchors[outcome.anchor_id].anchor.order_id == outcome.order_id
    assert rig.store._groups == {} and rig.store._stops == {}
    assert rig.prices.asked == [SYMBOL]  # a market order's reference price


_SL = StopOffset(unit="price", value=Decimal(61000))
_TP = StopOffset(unit="price", value=Decimal(59000))


@pytest.mark.parametrize(
    "position",
    [None, "same_side", "smaller"],
    ids=["flat", "same_side", "over_sized"],
)
@pytest.mark.parametrize(
    ("request_", "refused_by"),
    [
        (flatten(), ("intent", "intent_mismatch")),
        (flatten(intent="entry"), ("stop_loss", "reduce_only_tpsl")),
        (flatten(intent="entry", stop_loss=_SL), ("stop_loss", "reduce_only_tpsl")),
    ],
    ids=["intent_mismatch", "profile_stop", "named_stop"],
)
async def test_a_reduce_only_order_not_shown_to_reduce_is_refused_with_nothing_sent(
    rig: SubmitRig, position: str | None, request_: OrderRequest, refused_by: tuple[str, str]
) -> None:
    """SR-E29-01, C-2.6: anything not shown to reduce is an entry, so it takes a stop (the
    profile's offset when it names none) and an opening intent. One labelled reducing is
    `intent_mismatch`; one labelled an entry would carry a stop, the profile's or its own, which a
    reduce-only order carries none of on this venue (`supports_reduce_only_tpsl`, the ruling of
    2026-10-22), so it is `reduce_only_tpsl`: nothing recorded or sent, never a late rejection at
    the exchange."""
    if position == "same_side":
        rig.port.demo.seed_position(_position(side="sell"))
    elif position == "smaller":
        rig.port.demo.seed_position(_position(qty="0.005"))
    refused = await _refused(rig, request_)
    assert isinstance(refused, OrderInvalid)
    assert [(e.field, e.rule) for e in refused.errors] == [refused_by]
    assert [c for c in rig.calls() if c != "positions"] == []
    assert rig.written() == (0, 0, 0, 0)


@pytest.mark.parametrize(
    ("sides", "fields"),
    [
        ({"stop_loss": _SL}, ["stop_loss"]),
        ({"take_profit": _TP}, ["take_profit"]),
        ({"stop_loss": _SL, "take_profit": _TP}, ["stop_loss", "take_profit"]),
    ],
    ids=["stop_loss", "take_profit", "both"],
)
async def test_a_reduce_only_order_naming_a_take_profit_or_a_stop_is_refused_before_any_read(
    rig: SubmitRig, sides: dict[str, StopOffset], fields: list[str]
) -> None:
    """The ruling of 2026-10-22 on the venue's `reduceOnly` rule (24 Sec.14.1): one rule and one
    sentence shape per side, refused before the position read, with nothing recorded or sent and
    the denied record first (C-2.9). `validation_failed` answers 400, its registry status."""
    rig.port.demo.seed_position(_position())
    refused = await _refused(rig, flatten(**sides))
    assert isinstance(refused, OrderInvalid)
    assert (problem_for(refused).status, problem_for(refused).code) == (400, "validation_failed")
    assert [(e.field, e.rule) for e in refused.errors] == [(f, "reduce_only_tpsl") for f in fields]
    words = {"stop_loss": "stop-loss", "take_profit": "take-profit"}
    assert [e.message for e in refused.errors] == [
        f"A reduce-only order carries no {words[f]}." for f in fields
    ]
    _nothing_done(rig)
    [record] = _denied(rig)
    assert (record.reason, record.detail["step"], record.request_id) == (
        "validation_failed", "classify", REQUEST_ID,
    )  # fmt: skip


async def test_a_venue_that_sets_them_on_a_reduce_only_order_lets_the_order_carry_them(
    rig: SubmitRig,
) -> None:
    """The rule is the routed venue's capability, never a constant of the pipeline (C-2.2)."""
    rig.port.demo.capabilities = fake_capabilities("demo", supports_reduce_only_tpsl=True)
    rig.port.demo.seed_position(_position())
    outcome = await rig.submit(flatten(take_profit=_TP))
    [create] = [c for c in rig.port.demo.calls if c.method == "place_order"]
    assert (outcome.status, _create(create).reduce_only) == (202, True)
    assert _create(create).take_profit == Decimal(59000)


# --- C-2.6 on every path: each kind of entry, and every create of the module ----------------------


#: A limit buy entry's create, row and group (`entry()`), which each kind below changes in part;
#: the group's in its columns' vocabulary (`tg_entrytype`, `tg_trigby`, 21 Sec.3.3.2).
_SENT: dict[str, object] = {
    "side": "buy", "order_type": "limit", "price": REFERENCE, "trigger_price": None,
    "trigger_by": None, "trigger_direction": None, "tpsl_mode": "full", "position_idx": 0,
}  # fmt: skip
_ROW: dict[str, object] = {
    "side": "Buy", "order_type": "Limit", "price": REFERENCE, "trigger_price": None,
    "trigger_by": None, "trigger_direction": None, "tpsl_mode": "Full", "position_idx": 0,
}  # fmt: skip
_GROUP: dict[str, object] = {
    "entry_type": "Limit", "entry_price": REFERENCE, "trigger_price": None, "trigger_by": None,
}  # fmt: skip
#: The market's price, from which a market entry is measured (24 Sec.9.3 step 2).
_MARKET = Decimal("61000")
_RISE, _FALL = Decimal("60500"), Decimal("59500")


@dataclass(frozen=True)
class _Kind:
    """One kind of entry and what its create, its row and its group carry beyond a limit buy's
    (`_SENT`, `_ROW`, `_GROUP`), written out here, never read off the pipeline's own tables: its
    native stop, the reference prices it reads, its stop requests' size (a Partial side holds the
    order's quantity, 21 Sec.3.3.11 `rs_size`) and its profile's position mode."""

    request: OrderRequest
    stop: Decimal = STOP
    sent: dict[str, object] = field(default_factory=dict)
    row: dict[str, object] = field(default_factory=dict)
    group: dict[str, object] = field(default_factory=dict)
    asked: tuple[str, ...] = ()
    size: Decimal | None = None
    position_mode: str = "one_way"


def _conditional(direction: Any, by: Any, short: str, code: int) -> Any:
    """A conditional limit buy that fires when the price `by` names moves `direction` to its
    trigger: `short` is the create's name for that price, `code` the row's for the direction (22
    `TriggerSpec`, 21 Sec.3.3.4); the row and the group's column name the price as `by` does."""
    price = _RISE if direction == "rise" else _FALL
    return pytest.param(
        _Kind(
            entry(trigger=OrderTrigger(price=price, direction=direction, trigger_by=by)),
            sent={"trigger_price": price, "trigger_by": short, "trigger_direction": direction},
            row={"trigger_price": price, "trigger_by": by, "trigger_direction": code},
            group={"entry_type": "Conditional", "trigger_price": price, "trigger_by": by},
        ),
        id=f"conditional_{direction}_{short}",
    )


@pytest.mark.parametrize(
    "kind",
    [
        pytest.param(_Kind(entry()), id="limit"),
        pytest.param(
            _Kind(
                entry(order_type="market", price=None, stop_loss=None),
                stop=Decimal("60390.0"),  # the profile's 1 % below the market's 61000
                sent={"order_type": "market", "price": None},
                row={"order_type": "Market", "price": None},
                group={"entry_type": "Market", "entry_price": None},
                asked=(SYMBOL,),
            ),
            id="market",
        ),
        _conditional("rise", "LastPrice", "last", 1),
        _conditional("rise", "MarkPrice", "mark", 1),
        _conditional("rise", "IndexPrice", "index", 1),
        _conditional("fall", "LastPrice", "last", 2),
        _conditional("fall", "MarkPrice", "mark", 2),
        _conditional("fall", "IndexPrice", "index", 2),
        pytest.param(
            _Kind(
                entry(tpsl_mode="Partial"),
                sent={"tpsl_mode": "partial"},
                row={"tpsl_mode": "Partial"},
                size=QTY,
            ),
            id="partial",
        ),
        pytest.param(
            _Kind(
                entry(position_idx=1),
                sent={"position_idx": 1},
                row={"position_idx": 1},
                position_mode="hedge",
            ),
            id="hedge_buy",
        ),
        pytest.param(
            _Kind(
                entry(side="sell", position_idx=2, stop_loss=_SL, take_profit=_TP),
                stop=Decimal(61000),
                sent={"side": "sell", "position_idx": 2},
                row={"side": "Sell", "position_idx": 2},
                position_mode="hedge",
            ),
            id="hedge_sell",
        ),
    ],
)
async def test_an_entry_of_each_kind_reaches_the_venue_once_with_its_native_stop(
    rig: SubmitRig, kind: _Kind
) -> None:
    """C-2.6 for every order path: a limit entry, a market one measured from the market's price,
    a conditional one firing either way off each price it may watch, a Partial one and a hedge
    one on either side each reach the venue once, with their native stop, and their row, group,
    leg and stop requests record them as sent."""
    rig.profiles.held[(cr.ACCOUNT, None)] = profile(position_mode=kind.position_mode)
    rig.prices.price = _MARKET
    outcome = await rig.submit(kind.request)
    assert (outcome.status, outcome.lifecycle) == (202, "submitted")
    [create] = _creates(rig.port)
    assert (create.stop_loss, create.reduce_only) == (kind.stop, False)
    assert {name: getattr(create, name) for name in _SENT} == _SENT | kind.sent
    row = _row(rig, outcome)
    assert row.stop_loss == kind.stop
    assert {name: getattr(row, name) for name in _ROW} == _ROW | kind.row
    record = _group(rig, outcome)
    assert {name: getattr(record.group, name) for name in _GROUP} == _GROUP | kind.group
    assert record.group.sl_price_hint == kind.stop
    [leg] = record.legs
    assert (leg.status, leg.resolved_sl_price) == ("submitted", kind.stop)
    stops = {stop.kind: stop for stop in rig.store._stops.values()}
    assert stops["stop_loss"].trigger_price == kind.stop
    assert {(s.position_idx, s.position_side, s.tpsl_mode, s.size) for s in stops.values()} == {
        (row.position_idx, row.side, row.tpsl_mode, kind.size)
    }
    assert rig.prices.asked == list(kind.asked)


async def test_the_stop_check_reads_the_creates_of_every_rig_a_test_builds(
    rig: SubmitRig, stops_on_every_create: list[cr.Rig]
) -> None:
    """`stops_on_every_create` is not vacuous: it holds the `rig` fixture's venue doubles and a
    `rigged()` rig's, and reads each create they took."""
    await rig.submit()
    await rig.machines.stop()  # one facade per process: the next rig's takes the binding over
    async with rigged() as other:
        await other.submit()
    assert [id(port) for port in stops_on_every_create] == [id(rig.port), id(other.port)]
    assert [c.stop_loss for port in stops_on_every_create for c in _creates(port)] == [STOP, STOP]


# --- metrics and bounds ---------------------------------------------------------------------------


async def test_the_answer_is_timed_by_transport(rig: SubmitRig) -> None:
    rig.port.monotonic.s = 100.0
    await rig.submit()
    assert rig.count("order_submit_seconds_count", transport="rest") == 1


def test_the_bounds_after_the_anchor_exists_total_under_the_in_flight_threshold() -> None:
    """#4006 follow-up 3: `SEND`'s write, the create's answer, the result step, then the anchor's,
    the leg's and the group's compare-and-sets and the outcome's record, all under
    `CV_OMS_INFLIGHT_STUCK_S` by default, so a repeat meets the outcome this request records. The
    sum is the pipeline's own, which its constructor checks."""
    after_anchor = _after_anchor_s(
        store_timeout_s=STORE_TIMEOUT_S, place_wait_s=PLACE_WAIT_S, result_wait_s=RESULT_WAIT_S
    )
    assert PLACE_WAIT_S > SUBMIT_TIMEOUT_S and RESULT_WAIT_S > CV_PERSIST_TIMEOUT
    assert after_anchor == CV_PERSIST_TIMEOUT + PLACE_WAIT_S + RESULT_WAIT_S + 4 * STORE_TIMEOUT_S
    assert after_anchor == 17.0 < STUCK_AFTER_S


@pytest.mark.parametrize(
    "bounds",
    [{"place_wait_s": 19.0}, {"result_wait_s": 15.0}, {"store_timeout_s": 5.25}],
    ids=["place_wait", "result_wait", "store_timeout"],
)
async def test_bounds_after_the_anchor_that_reach_the_in_flight_threshold_are_refused(
    rig: SubmitRig, bounds: dict[str, float]
) -> None:
    """#4006 follow-up 3, enforced: bounds that total `CV_OMS_INFLIGHT_STUCK_S` (30 s) or more
    would let a repeat decide the anchor while its request still runs, so no pipeline is built
    with them; each case here totals 30 s exactly."""
    with pytest.raises(ValueError, match="CV_OMS_INFLIGHT_STUCK_S"):
        rig.make(**bounds)


async def test_bounds_after_the_anchor_under_the_in_flight_threshold_are_taken(
    rig: SubmitRig,
) -> None:
    assert rig.make(place_wait_s=18.5)._place_wait_s == 18.5  # 29.5 s in all


def _anchors(rig: SubmitRig, stuck_after_s: float) -> AnchorService:
    """An anchor service over the rig's store whose in-flight threshold is `stuck_after_s`."""
    return AnchorService(
        IdempotencyAnchorRepository(rig.store.anchors),
        clock=lambda: cr.EPOCH + timedelta(microseconds=rig.port.now.us),
        timeout_s=2.0,
        stuck_after_s=stuck_after_s,
    )


async def test_bounds_that_reach_a_lowered_in_flight_threshold_are_refused(rig: SubmitRig) -> None:
    """D-2B2-01: the threshold a repeat meets is the anchor service's own. Lowered to the default
    bounds' 17 s, they reach it, so no pipeline is built over that service."""
    with pytest.raises(ValueError, match=r"CV_OMS_INFLIGHT_STUCK_S \(17\.0 s\)"):
        rig.make(anchors=_anchors(rig, 17.0))


async def test_bounds_under_a_lowered_in_flight_threshold_are_taken(rig: SubmitRig) -> None:
    assert rig.make(anchors=_anchors(rig, 17.25))._anchors.stuck_after_s == 17.25


async def test_bounds_under_a_raised_in_flight_threshold_are_taken(rig: SubmitRig) -> None:
    """The threshold a repeat meets is the anchor service's own, which `CV_OMS_INFLIGHT_STUCK_S`
    may raise past the key's default of 30 s: bounds that total 30 s are taken under a 60 s one,
    with no ceiling of the pipeline's."""
    pipeline = rig.make(anchors=_anchors(rig, 60.0), place_wait_s=19.0)  # 30 s in all
    assert (pipeline._anchors.stuck_after_s, pipeline._place_wait_s) == (60.0, 19.0)


async def test_bounds_that_reach_a_raised_in_flight_threshold_are_refused(rig: SubmitRig) -> None:
    with pytest.raises(ValueError, match=r"CV_OMS_INFLIGHT_STUCK_S \(60\.0 s\)"):
        rig.make(anchors=_anchors(rig, 60.0), place_wait_s=49.0)  # 60 s in all


async def test_a_place_wait_that_does_not_outlast_the_submit_timeout_is_refused(
    rig: SubmitRig,
) -> None:
    """D-2B2-01: the wait for the create's answer must outlast the command port's one deadline on
    all of `place`, or a 429 or 502 answered in time would be given up into a 202; a wait of
    just that deadline races it."""
    with pytest.raises(ValueError, match="does not outlast"):
        rig.make(place_wait_s=SUBMIT_TIMEOUT_S)


@pytest.mark.parametrize("deadline", [PLACE_WAIT_S, float("nan")], ids=["raised", "nan"])
async def test_a_command_port_whose_deadline_the_wait_does_not_outlast_is_refused(
    rig: SubmitRig, deadline: float
) -> None:
    """A command port built with the default wait's 6 s as its deadline, or with none that
    compares, takes no pipeline with that wait."""
    with pytest.raises(ValueError, match="does not outlast"):
        rig.make(commands=cr.build_rig(submit_timeout_s=deadline).port)


async def test_a_wait_that_outlasts_a_lowered_submit_timeout_is_taken(rig: SubmitRig) -> None:
    lowered = cr.build_rig(submit_timeout_s=0.5).port
    assert rig.make(commands=lowered, place_wait_s=0.75)._place_wait_s == 0.75


async def test_an_anchor_write_that_does_not_answer_is_bounded_as_the_other_writes_are(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The anchor's outcome is written within `store_timeout_s`, whatever the anchor service's
    own bound, so the bounds after the anchor hold: a write that never answers is logged, and the
    answer is still the order's outcome."""
    anchors = AnchorService(
        IdempotencyAnchorRepository(rig.store.anchors),
        clock=lambda: cr.EPOCH + timedelta(microseconds=rig.port.now.us),
        timeout_s=3600.0,  # far past the pipeline's own bound
    )
    pipeline = rig.make(anchors=anchors, store_timeout_s=0.25)

    async def hangs(*_args: Any) -> bool:
        await asyncio.Event().wait()
        return True

    monkeypatch.setattr(rig.store.anchors, "record_outcome", hangs)
    with capture_logs() as logs:
        async with asyncio.timeout(5.0):  # an unbounded write fails here, never hangs the run
            outcome = await pipeline.submit(entry(), context())
    assert (outcome.status, outcome.lifecycle) == (202, "submitted")
    [line] = [line for line in logs if line["event"] == "oms_anchor_outcome_unrecorded"]
    assert line["failure"] == "TimeoutError"


def test_the_rejected_counter_holds_one_series_per_problem_code() -> None:
    from candleviewer.observability.metrics_catalogue import CATALOGUE

    [spec] = [s for s in CATALOGUE if s.name == "oms_submit_rejected_total"]
    codes = {problem.code for problem in PROBLEMS.values()} | {"internal_error"}
    assert spec.labels == ("code",) and spec.max_series == len(codes)


# --- the value types ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"status": 202, "code": "exchange_error"},
        {"status": 429},
        {"status": 502, "code": "exchange_rate_limited"},
        {"status": 202, "ret_code": 1},
        {"status": 429, "code": "exchange_rate_limited", "retry_after_s": 0},
        {"status": 429, "code": "exchange_rate_limited", "retry_after_s": 1, "replayed": True},
        {"status": 502, "code": "exchange_error", "ret_code": 2**31},
        {"status": 202, "order_id": None},
    ],
)
def test_an_outcome_holds_only_what_its_anchor_can_record(fields: dict[str, Any]) -> None:
    base: dict[str, Any] = {"anchor_id": uuid4(), "order_id": uuid4()}
    with pytest.raises(ValueError):
        SubmitOutcome(**(base | fields))


def test_an_outcome_decides_its_anchor_with_its_own_answer() -> None:
    outcome = SubmitOutcome(502, uuid4(), uuid4(), None, "rejected", "exchange_error", 170131)
    decided = outcome.anchor_outcome(cr.T0)
    assert decided == AnchorOutcome(
        status=502, decided_at=cr.T0, code="exchange_error", ret_code=170131
    )


@pytest.mark.parametrize(
    "changes",
    [{"order_id": uuid4()}, {"trade_group_id": uuid4()}, {"replayed": True}],
    ids=["another_order", "another_group", "replay"],
)
async def test_an_outcome_carries_only_the_rows_it_names_and_a_replay_none(
    rig: SubmitRig, changes: dict[str, Any]
) -> None:
    outcome = await rig.submit()
    with pytest.raises(ValueError, match="carries the rows it names"):
        replace(outcome, **changes)


async def test_an_outcome_never_shows_its_rows_in_its_repr(rig: SubmitRig) -> None:
    """C-12.6: the rows hold the stop, the prices and the size, which no log line shows: not in
    the outcome's repr, nor in the rows' own (the order, the group and its leg)."""
    outcome = await rig.submit()
    rows = outcome.written
    assert rows is not None and rows.group is not None and len(rows.legs) == 1
    assert "written" not in repr(outcome) and str(STOP) not in repr(outcome)
    hidden = [*map(str, (STOP, TAKE_PROFIT, REFERENCE, QTY, KEY)), SHA]
    assert [value for value in hidden if value in repr(rows)] == []


def test_a_context_never_shows_its_key_or_fingerprint() -> None:
    shown = repr(context())
    assert str(KEY) not in shown and SHA not in shown


#: A number written on its own in a log value: never one inside an id, a key or a fingerprint.
_FIGURE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?!\w|\.\d)")


async def test_no_log_line_of_a_submit_or_its_repeat_shows_the_key_the_fingerprint_or_a_figure(
    rig: SubmitRig,
) -> None:
    """C-12.6 (21 Sec.12): no value of any line a submit and its repeat log, the pipeline's, the
    facade's or the command port's, holds the key, the fingerprint, the stop or the quantity,
    whatever its trailing zeros."""
    with capture_logs() as logs:
        first = await rig.submit()
        repeat = await rig.submit()
    assert (first.replayed, repeat.replayed) == (False, True)
    assert {"oms_submit_answered", "oms_anchor_replayed"} <= {line["event"] for line in logs}
    texts = [str(value) for line in logs for value in line.values()]
    assert [t for t in texts if str(KEY) in t or KEY.hex in t or SHA in t] == []
    figures = {Decimal(token) for text in texts for token in _FIGURE.findall(text)}
    assert figures & {STOP, QTY} == set()


# --- the defensive branches: each fails closed, nothing sent ------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"store_timeout_s": 0}, ValueError),
        ({"position_timeout_s": float("nan")}, ValueError),
        ({"store_timeout_s": True}, TypeError),
        ({"place_wait_s": 0}, ValueError),
        ({"result_wait_s": float("inf")}, ValueError),
        ({"stop_retries": (0.1, -1.0)}, ValueError),
        ({"stop_retries": ("0.1",)}, TypeError),
    ],
)
async def test_the_pipeline_refuses_a_bound_that_bounds_nothing(
    rig: SubmitRig, kwargs: dict[str, Any], error: type[Exception]
) -> None:
    """C-2.18: every wait the pipeline makes is finite."""
    with pytest.raises(error):
        rig.make(**kwargs)


async def test_an_account_that_resolves_to_another_is_a_fault_with_nothing_sent(
    rig: SubmitRig,
) -> None:
    """SR-E27-21: a resolver that answers another account's key is a defect, never a send."""
    rig.port.accounts.seed(cr.ref(cr.LIVE_ACCOUNT, "live"), as_id=cr.ACCOUNT)
    with pytest.raises(ValueError, match="another account"):
        await rig.submit()
    [record] = _denied(rig)
    assert record.reason == "internal_error"
    _nothing_done(rig)


async def test_a_quantity_far_past_its_ceiling_is_refused_400(rig: SubmitRig) -> None:
    qty = Decimal(10**40)
    refused = await _refused(rig, entry(sizing=SizingRequest(mode="fixed_qty", qty=qty)))
    assert isinstance(refused, LotSizeViolation)
    _nothing_done(rig)


async def test_a_quantity_no_step_can_round_is_refused_400(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unroundable(*_args: Any) -> Any:
        raise InvalidOperation

    monkeypatch.setattr(rig.pipeline._ports.sizer, "size", unroundable)
    refused = await _refused(rig)
    assert type(refused) is OrderInvalid and refused.detail == "The quantity cannot be sized."
    _nothing_done(rig)


async def test_a_route_refused_inside_the_position_read_is_answered_as_itself(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def miswired(*_args: Any) -> Any:
        raise EnvironmentMismatch(order_environment="demo", route_environment="live")

    monkeypatch.setattr(rig.pipeline._positions, "position", miswired)
    refused = await _refused(rig, flatten())
    assert isinstance(refused, EnvironmentMismatch)
    _nothing_done(rig)


@pytest.mark.parametrize("note", ["x" * 281, "a NUL \x00 inside"], ids=["too_long", "nul"])
async def test_a_value_its_column_cannot_store_is_refused_400(rig: SubmitRig, note: str) -> None:
    refused = await _refused(rig, entry(note=note))
    assert isinstance(refused, OrderInvalid)
    assert refused.detail == "The order holds a value that cannot be recorded."
    _nothing_done(rig)


async def test_an_allocation_whose_lookup_fails_is_503(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(_link: str) -> bool:
        raise StorageTierUnavailable("postgres unreachable")

    monkeypatch.setattr(rig.lookup, "exists", down)
    assert isinstance(await _refused(rig), StoreUnavailable)
    _nothing_done(rig)


async def test_a_persist_whose_row_did_not_land_is_503_with_nothing_sent(rig: SubmitRig) -> None:
    """S7: the write did not answer, and the rebuilt order has no row: nothing was written."""
    rig.store.fail_next(TimeoutError())
    assert isinstance(await _refused(rig), StoreUnavailable)
    _nothing_done(rig)


async def test_a_persist_whose_outcome_is_unknown_with_no_machine_pages(rig: SubmitRig) -> None:
    """No machine holds the order, so a `validated` row the write may have left has no owner
    until the startup sweep: the request is 503, and the pipeline pages, as it does for an unsent
    order it cannot abandon."""
    rig.store.fail_next(TimeoutError())
    assert isinstance(await _refused(rig), StoreUnavailable)
    assert rig.pager.calls.count("oms_submit_persist_unknown") == 1


async def test_a_store_that_refuses_the_orders_own_rows_is_a_fault(rig: SubmitRig) -> None:
    """A deterministic refusal of the rows the pipeline built is a defect (500), not a 503."""
    rig.store.fail_next(ValueError("a CHECK refused the row"))
    refused = await _refused(rig)
    assert type(refused) is OmsError and problem_for(refused).code == "internal_error"
    _nothing_done(rig)


@pytest.mark.parametrize("answer", ["fresh", "unreadable"])
async def test_a_held_key_whose_anchor_cannot_be_read_is_503(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch, answer: str
) -> None:
    await rig.submit()
    rig.port.demo.calls.clear()
    anchor = next(iter(rig.store._anchors.values()))
    read = anchor.read(SHA)

    async def after_taken(*_args: Any) -> Any:
        if answer == "fresh":
            return Fresh()
        return Replay(replace(read, outcome_status=200))

    monkeypatch.setattr(rig.pipeline._anchors, "after_taken", after_taken)
    assert isinstance(await _refused(rig), StoreUnavailable)
    assert rig.calls() == []


@pytest.mark.parametrize("state", ["validated", "gone", "submitting"])
async def test_a_send_whose_outcome_is_unknown_is_followed_only_once_it_left_validated(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    """#4006's follow-up: a `submitting` row is followed to its outcome; an order still
    `validated`, or with no machine, is answered 503, this request sending nothing."""
    original = rig.machines.command

    async def unknown(account_id: Any, order_id: Any, *args: Any, **kwargs: Any) -> str:
        if state == "submitting":
            await original(account_id, order_id, *args, **kwargs)
        elif state == "gone":
            await rig.machines._close(rig.machines._orders[order_id], publish=False)
        raise OrderStepUnknown("SEND", "StepOutcomeUnknown")

    monkeypatch.setattr(rig.machines, "command", unknown)
    if state == "submitting":
        outcome = await rig.submit()
        assert (outcome.status, outcome.lifecycle) == (202, "submitted")
        assert rig.calls() == ["place_order"]
        return
    assert isinstance(await _refused(rig), StoreUnavailable)
    assert rig.calls() == [] and rig.port.port._watches == {}
    await rig.quiet()
    lifecycle = "killed" if state == "validated" else "validated"
    assert [row.lifecycle_state for row in rig.store._orders.values()] == [lifecycle]
    [anchor] = rig.store._anchors.values()
    assert anchor.outcome is None  # the ruling of 2026-10-22: left undecided (C-2.10)


# --- an unknown SEND and its repeats (the orchestrator's ruling of 2026-10-22, C-2.10) ----------


def _later(seconds: float) -> int:
    """`seconds` in the rig's microseconds."""
    return int(seconds * 1_000_000)


async def _lost_send(rig: SubmitRig, monkeypatch: pytest.MonkeyPatch, request: Any = None) -> Any:
    """A request whose `SEND` committed, then lost its answer with its machine: the row stays
    `submitting`, its create never left (held, then dropped with the machine) and the request
    answers 503. Returns the venue's own create, the hold staying shut."""
    land, held = rig.port.demo.place_order, asyncio.Event()

    async def holding(create: Any) -> Any:
        await held.wait()
        return await land(create)

    original = rig.machines.command

    async def lost(account_id: Any, order_id: Any, *args: Any, **kwargs: Any) -> str:
        await original(account_id, order_id, *args, **kwargs)
        await rig.machines._close(rig.machines._orders[order_id], publish=False)
        raise OrderStepUnknown("SEND", "StepOutcomeUnknown")

    monkeypatch.setattr(rig.port.demo, "place_order", holding)
    monkeypatch.setattr(rig.machines, "command", lost)
    assert isinstance(await _refused(rig, request), StoreUnavailable)
    [row] = rig.store._orders.values()
    assert row.lifecycle_state == "submitting" and "place_order" not in rig.calls()
    return land


async def _restarted(rig: SubmitRig) -> tuple[OrderMachines, Any]:
    """A crash and a restart: the facade stops, the binding's attempts go with the process's
    memory, and a new facade runs over the same stores, with a pipeline over it."""
    await rig.machines.stop()
    b01._ATTEMPTS.clear()
    machines = OrderMachines(
        rig.machines._ports,
        metrics=Metrics("dev"),
        pager=rig.pager,
        now_us=rig.port.now,
        registry=REGISTRY,
    )
    return machines, rig.make(machines=machines)


async def _settle(machines: OrderMachines) -> None:
    for _ in range(4):
        for _ in range(32):
            await asyncio.sleep(0)
        await machines.idle()


@pytest.mark.parametrize(
    ("kind", "after_s"),
    [("entry", 5.0), ("reduce_only", STUCK_AFTER_S - 1)],
    ids=["entry", "reduce_only"],
)
async def test_a_repeat_of_an_unknown_send_within_30_s_is_409_in_flight_and_sends_nothing(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch, kind: str, after_s: float
) -> None:
    """The first request answered 503 and left its anchor undecided; a repeat within
    `CV_OMS_INFLIGHT_STUCK_S` is 409 `idempotency_in_flight` with `Retry-After`: nothing
    recorded, nothing sent (an entry's repeat comes inside its stop request's bound, which the
    stop-request gate reads first)."""
    request = entry() if kind == "entry" else flatten()
    if kind == "reduce_only":
        rig.port.demo.seed_position(_position())
    await _lost_send(rig, monkeypatch, request)
    written = rig.written()
    rig.port.now.us += _later(after_s)
    refused = await _refused(rig, request)
    assert isinstance(refused, IdempotencyInFlight) and refused.retry_after_s == 1
    assert [c for c in rig.calls() if c != "positions"] == [] and rig.written() == written
    [anchor] = rig.store._anchors.values()
    assert anchor.outcome is None


@pytest.mark.parametrize(
    ("case", "state"),
    [("abandoned", "killed"), ("lost", RECONCILING), ("unknown", RECONCILING)],
    ids=["abandoned", "lost", "unknown"],
)
async def test_a_later_repeat_answers_202_with_the_reconciled_state_never_an_assumed_success(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch, case: str, state: str
) -> None:
    """A repeat past `CV_OMS_INFLIGHT_STUCK_S` decides the undecided anchor 202 and answers the
    order's state as B1 resolved it: `killed` for an order abandoned unsent; `reconciling` while
    B1 has not, a `submitting` row waiting for a restart's hydration, an `unknown` one for
    reconciliation (here a decided 202 repeated at once). It sends nothing, under no id (C-2.10)."""
    request: Any = entry()
    if case == "abandoned":

        async def unknown(*_args: Any, **_kwargs: Any) -> str:
            raise OrderStepUnknown("SEND", "StepOutcomeUnknown")

        monkeypatch.setattr(rig.machines, "command", unknown)
        assert isinstance(await _refused(rig), StoreUnavailable)
        await rig.quiet()
        rig.port.now.us += _later(STUCK_AFTER_S + 1)
    elif case == "lost":
        request = flatten()
        rig.port.demo.seed_position(_position())
        await _lost_send(rig, monkeypatch, request)
        rig.port.now.us += _later(STUCK_AFTER_S + 1)
    else:
        rig.port.demo.script("place_order", LandedThenAmbiguous())
        first = await rig.submit()
        assert (first.status, first.lifecycle) == (202, "unknown")
    creates = [c for c in rig.port.demo.calls if c.method == "place_order"]
    repeat = await rig.submit(request)
    assert (repeat.status, repeat.replayed, repeat.lifecycle) == (202, True, state)
    assert [c for c in rig.port.demo.calls if c.method == "place_order"] == creates
    [anchor] = rig.store._anchors.values()
    assert anchor.outcome is not None and anchor.outcome.status == 202
    [row] = rig.store._orders.values()
    assert all(_create(c).order_link_id == row.order_link_id for c in creates)


async def test_a_repeat_whose_order_cannot_be_read_answers_reconciling(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never an assumed success: a state not read within the bound, or an anchor naming no row,
    is answered `reconciling`, logged."""
    await rig.submit()

    async def late(*_args: Any, **_kwargs: Any) -> str:
        raise TimeoutError

    monkeypatch.setattr(rig.machines, "settled", late)
    with capture_logs() as logs:
        repeat = await rig.submit()
    assert (repeat.status, repeat.replayed, repeat.lifecycle) == (202, True, RECONCILING)
    assert any(line["event"] == "oms_replay_state_unread" for line in logs)
    assert await rig.pipeline.reconciled_state(cr.ACCOUNT, None) == RECONCILING


@pytest.mark.parametrize("venue", ["empty", "duplicate"])
async def test_a_lost_send_goes_out_at_the_restart_under_its_id_and_a_later_repeat_answers_it(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch, venue: str
) -> None:
    """The `submitting` row a lost `SEND` left is sent by a restart's hydration, once, after its
    lookup, under its persisted id and with its stop (C-2.10, C-2.6). A duplicate-id rejection
    reads as "already accepted": B1 looks the id up and adopts the order, never re-sending it
    under a new id. A later repeat answers the reconciled state, `submitted`."""
    land = await _lost_send(rig, monkeypatch)
    [row] = rig.store._orders.values()
    machines, pipeline = await _restarted(rig)
    try:
        if venue == "duplicate":

            async def duplicate(create: Any) -> Any:
                await land(create)  # the venue holds the order under its id
                raise DuplicateClientIdError("the order_link_id was already accepted")

            monkeypatch.setattr(rig.port.demo, "place_order", duplicate)
        else:
            monkeypatch.setattr(rig.port.demo, "place_order", land)
        assert await machines.hydrate(cr.ACCOUNT, row.id, environment="demo") == "submitting"
        await _settle(machines)
        assert [r.lifecycle_state for r in rig.store._orders.values()] == ["submitted"]
        methods = rig.calls()
        sent = methods.index("place_order")
        assert methods.count("place_order") == 1
        assert sent > 0 and set(methods[:sent]) <= {"open_orders", "order_history"}
        [create] = [c for c in rig.port.demo.calls if c.method == "place_order"]
        assert (_create(create).order_link_id, _create(create).stop_loss) == (
            row.order_link_id, STOP,
        )  # fmt: skip
        rig.port.now.us += _later(STUCK_AFTER_S + 1)
        repeat = await pipeline.submit(entry(), context())
        assert (repeat.status, repeat.replayed, repeat.lifecycle) == (202, True, "submitted")
        assert rig.calls().count("place_order") == 1
    finally:
        await machines.stop()


async def test_a_create_that_has_not_answered_in_time_is_202_with_its_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The outcome is not known yet: 202, as `unknown` is, never a 503 (24 Sec.8.4). The wait
    outlasts the command port's deadline (D-2B2-01), so it is B1's own turn that runs late here:
    the create has not begun when the wait ends, then lands within its own deadline."""
    async with rigged(submit_timeout_s=0.5, place_wait_s=0.6) as rig:
        gate, place = asyncio.Event(), rig.port.port.place

        async def late(command: Any) -> Any:
            await gate.wait()
            return await place(command)

        monkeypatch.setattr(rig.port.port, "place", late)
        outcome = await rig.submit()
        assert (outcome.status, outcome.lifecycle) == (202, "submitting")
        gate.set()
        row = _row(rig, outcome)
        left = await rig.machines.settled(cr.ACCOUNT, row.id, leaving="submitting", timeout_s=5)
        assert left == _row(rig, outcome).lifecycle_state == "submitted"


async def test_an_outcome_step_not_known_in_time_is_202_as_submitting(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def late(*_args: Any, **_kwargs: Any) -> str:
        raise TimeoutError

    monkeypatch.setattr(rig.machines, "settled", late)
    outcome = await rig.submit()
    assert (outcome.status, outcome.lifecycle) == (202, "submitting")


async def test_an_anchor_a_repeat_decided_first_keeps_its_outcome(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The compare-and-set from none lost: a stale repeat decided it; logged, never the answer."""

    async def taken(*_args: Any) -> bool:
        return False

    monkeypatch.setattr(rig.pipeline._anchors, "record", taken)
    with capture_logs() as logs:
        outcome = await rig.submit()
    assert outcome.status == 202
    assert any(line["event"] == "oms_anchor_outcome_taken" for line in logs)


async def test_a_pager_that_fails_is_logged_never_the_answer(
    rig: SubmitRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = rig.machines.command

    async def refused_send(*args: Any, **kwargs: Any) -> str:
        rig.store.fail_next(StorageTierUnavailable("postgres unreachable"))
        return await original(*args, **kwargs)

    async def stuck(*_args: Any) -> str:
        raise StorageTierUnavailable("postgres unreachable")

    monkeypatch.setattr(rig.machines, "command", refused_send)
    monkeypatch.setattr(rig.machines, "abandon", stuck)
    rig.pager.refuse = True
    with capture_logs() as logs:
        assert isinstance(await _refused(rig), StoreUnavailable)
    assert any(line["event"] == "oms_pager_failed" for line in logs)
