"""`oms.leverage.PositionLeverage` (E29-T07 #915; 22 `setPositionLeverage`), on fakes: the
exchange's `FakeTradingPort`, the command rig's account refs and the submit rig's instruments and
profile, with recording doubles of the switches and the audit writer. No network (C-13.5)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from candleviewer.accounts.errors import AccountNotFoundError, ProfileUnavailableError
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.domain.primitives import AccountId, Environment, Symbol
from candleviewer.exchange.base.errors import (
    InstrumentFilterError,
    InsufficientMarginError,
    RateBudgetExceededError,
    TransportError,
)
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.oms.errors import (
    AuditNotDurable,
    EnvironmentMismatch,
    ExchangeRejected,
    ExchangeUnavailable,
    OmsError,
    OmsNotReady,
    RateBudgetExceeded,
    StoreUnavailable,
    TradingDisabled,
)
from candleviewer.oms.fakes import InMemoryTradingAccounts
from candleviewer.oms.leverage import (
    LEVERAGE_ACTION,
    LeverageDeps,
    LeverageOutOfBounds,
    LeverageRequest,
    PositionLeverage,
    bounds_errors,
)
from candleviewer.oms.ports import RequestRecord, SubmitActor
from candleviewer.storage.errors import StorageQueryFailed
from tests.unit.oms import command_rig as cr
from tests.unit.oms.submit_rig import Instruments, instrument, profile

POSITION = UUID("0d000000-0000-4000-8000-000000000001")
ACTOR = SubmitActor(UUID("3a7c1e2d-5b40-4c6f-8e9a-1b2c3d4e5f60"), "owner", None, "100.64.0.7")
REQUEST_ID = UUID("6f1d2c3b-4a59-4e68-8f7a-9b0c1d2e3f40")


def _uncapped() -> AccountProfile:
    """A profile that names no `max_leverage_cap`: one not enabled for trading (D11)."""
    return profile(max_leverage_cap=None, trading_enabled=False)


@dataclass
class Profiles:
    """`Profiles`: the account's default, None for an account with none, or an error raised."""

    found: AccountProfile | None = field(
        default_factory=lambda: profile(max_leverage_cap=Decimal(100))
    )
    refuse: Exception | None = None

    async def get_effective_profile(
        self, account_id: UUID, profile_id: UUID | None = None
    ) -> AccountProfile:
        if self.refuse is not None:
            raise self.refuse
        if self.found is None:
            raise AccountNotFoundError(str(account_id))
        return self.found


@dataclass
class Switches:
    refusal_of: TradingDisabled | OmsNotReady | None = None

    def refusal(
        self, account_id: AccountId, environment: Environment
    ) -> TradingDisabled | OmsNotReady | None:
        return self.refusal_of


@dataclass
class Records:
    """The audit writer: each record with the venue calls made before it was written."""

    port: FakeTradingPort
    written: list[tuple[RequestRecord, int]] = field(default_factory=list)
    fail_at: int | None = None

    def record_id(self, action: str, name: str) -> UUID:  # the keyed records are not this path's
        raise AssertionError("a leverage change writes no keyed record")

    async def write(self, record: Any) -> None:
        if self.fail_at is not None and len(self.written) >= self.fail_at:
            raise RuntimeError("the audit writer is not started")
        self.written.append((record, len(self.port.calls)))

    def reasons(self) -> list[tuple[str, str]]:
        return [(r.outcome, r.reason) for r, _ in self.written]


@dataclass
class Rig:
    environment: Environment = "demo"
    port: FakeTradingPort = field(default_factory=lambda: FakeTradingPort(environment="demo"))
    instruments: Instruments = field(default_factory=Instruments)
    profiles: Profiles = field(default_factory=Profiles)
    switches: Switches = field(default_factory=Switches)
    account_env: Environment = "demo"
    records: Records = field(init=False)

    def __post_init__(self) -> None:
        self.records = Records(self.port)

    def deps(self) -> LeverageDeps:
        accounts = InMemoryTradingAccounts()
        accounts.seed(cr.ref(cr.ACCOUNT, self.account_env), as_id=cr.ACCOUNT)
        return LeverageDeps(
            accounts=accounts, instruments=self.instruments, profiles=self.profiles,
            ports=lambda env: self.port, switches=self.switches, audit=self.records,
            environment=self.environment,
        )  # fmt: skip

    def service(self) -> PositionLeverage:
        return PositionLeverage(self.deps())

    async def apply(self, leverage: str, before: str | None = "10") -> Any:
        asked = LeverageRequest(
            POSITION, cr.ACCOUNT, Symbol(cr.SYMBOL),
            None if before is None else Decimal(before), Decimal(leverage),
        )  # fmt: skip
        return await self.service().apply(asked, actor=ACTOR, request_id=REQUEST_ID)

    def sent(self) -> list[tuple[str, Decimal]]:
        return [c.request for c in self.port.calls if c.method == "set_leverage"]  # type: ignore[misc]  # (symbol, leverage)


async def test_position_leverage_a_change_is_recorded_ahead_then_sent_as_a_decimal() -> None:
    rig = Rig()
    outcome = await rig.apply("12.5")
    assert (outcome.leverage, outcome.changed) == (Decimal("12.5"), True)
    assert rig.sent() == [(cr.SYMBOL, Decimal("12.5"))]
    assert isinstance(rig.sent()[0][1], Decimal)
    [(ahead, calls_before), (after, _)] = rig.records.written
    assert calls_before == 0, "the intent is durable before the venue is called (C-2.9)"
    assert (ahead.action, ahead.outcome, ahead.reason) == (LEVERAGE_ACTION, "success", "requested")
    assert (after.outcome, after.reason) == ("success", "applied")
    assert (ahead.object_kind, ahead.object_id, ahead.account_id) == (
        "position", POSITION, cr.ACCOUNT,
    )  # fmt: skip
    assert ahead.detail["leverage_before"] == "10" and ahead.detail["leverage_after"] == "12.5"
    assert ahead.actor == ACTOR and ahead.request_id == REQUEST_ID


async def test_position_leverage_the_venues_not_modified_answer_is_an_idempotent_success() -> None:
    """Ruling BQ-8: setting the value the venue holds is the change done, never an error."""
    rig = Rig()
    rig.port.script(
        "set_leverage", InstrumentFilterError("held", filter_name="leverage_not_modified")
    )
    outcome = await rig.apply("10")
    assert (outcome.leverage, outcome.changed) == (Decimal("10"), False)
    assert rig.records.reasons() == [("success", "requested"), ("success", "not_modified")]


@pytest.mark.parametrize(
    ("leverage", "rule"),
    [
        ("101", "max_leverage"), ("0.5", "min_leverage"), ("10.005", "leverage_step"),
        ("0", "range"), ("-3", "range"),
    ],
)  # fmt: skip
async def test_position_leverage_outside_the_instrument_is_refused_unsent(
    leverage: str, rule: str
) -> None:
    rig = Rig(profiles=Profiles(_uncapped()))
    with pytest.raises(LeverageOutOfBounds) as refused:
        await rig.apply(leverage)
    assert [e.rule for e in refused.value.errors] == [rule]
    assert rig.sent() == []
    [(record, _)] = rig.records.written
    assert (record.outcome, record.reason, record.detail["step"]) == (
        "denied", "validation_failed", "bounds",
    )  # fmt: skip


async def test_position_leverage_above_the_profile_cap_is_refused_unsent() -> None:
    rig = Rig(profiles=Profiles(profile(max_leverage_cap=Decimal(20), leverage=Decimal(10))))
    with pytest.raises(LeverageOutOfBounds) as refused:
        await rig.apply("25")
    assert [e.rule for e in refused.value.errors] == ["max_leverage_cap"]
    assert rig.sent() == []
    assert (await rig.apply("20")).changed is True  # the cap itself is allowed


async def test_position_leverage_above_both_bounds_names_both_rules() -> None:
    rig = Rig(
        instruments=Instruments({cr.SYMBOL: instrument(max_leverage=Decimal(50))}),
        profiles=Profiles(profile(max_leverage_cap=Decimal(20), leverage=Decimal(10))),
    )
    with pytest.raises(LeverageOutOfBounds) as refused:
        await rig.apply("60")
    assert [e.rule for e in refused.value.errors] == ["max_leverage", "max_leverage_cap"]


async def test_position_leverage_with_no_profile_cap_the_instrument_alone_bounds_it() -> None:
    """The coordinator's ruling (2026-10-29): an empty cap (a profile not enabled for trading,
    as D11 bounds every trading one), or no default profile, leaves the instrument's maximum as
    the only bound."""
    rig = Rig(profiles=Profiles(_uncapped()))
    assert (await rig.apply("100")).changed is True
    rig = Rig(profiles=Profiles(None))
    assert (await rig.apply("100")).changed is True
    with pytest.raises(LeverageOutOfBounds):
        await Rig(profiles=Profiles(None)).apply("100.01")


@pytest.mark.parametrize(
    "error", [ProfileUnavailableError("down"), TimeoutError()], ids=["unavailable", "timeout"]
)
async def test_position_leverage_an_unread_profile_refuses_never_drops_the_cap(
    error: Exception,
) -> None:
    """SR-E28-24: a profile that cannot be read is no default; nothing is sent unbounded."""
    rig = Rig(profiles=Profiles(refuse=error))
    with pytest.raises(StoreUnavailable):
        await rig.apply("5")
    assert rig.sent() == []
    assert rig.records.reasons() == [("denied", "store_unavailable")]


async def test_position_leverage_an_unlisted_instrument_refuses_unsent() -> None:
    rig = Rig(instruments=Instruments({}))
    with pytest.raises(StoreUnavailable):
        await rig.apply("5")
    assert rig.sent() == []


async def test_position_leverage_the_switches_refuse_before_anything_is_read_or_sent() -> None:
    """C-2.21: the kill switch, live trading and the gate are consulted synchronously first."""
    rig = Rig(switches=Switches(TradingDisabled()))
    with pytest.raises(TradingDisabled):
        await rig.apply("5")
    assert rig.sent() == []
    [(record, _)] = rig.records.written
    assert (record.outcome, record.reason, record.detail["step"]) == (
        "denied", "trading_disabled", "switches",
    )  # fmt: skip


async def test_position_leverage_a_fenced_switch_is_not_ready_and_unrecorded() -> None:
    rig = Rig(switches=Switches(OmsNotReady()))
    with pytest.raises(OmsNotReady):
        await rig.apply("5")
    assert rig.records.written == [] and rig.sent() == []


async def test_position_leverage_an_unrecorded_intent_sends_nothing() -> None:
    rig = Rig()
    rig.records.fail_at = 0
    with pytest.raises(AuditNotDurable):
        await rig.apply("5")
    assert rig.sent() == []


async def test_position_leverage_an_unrecorded_refusal_is_audit_unavailable() -> None:
    rig = Rig(switches=Switches(TradingDisabled()))
    rig.records.fail_at = 0
    with pytest.raises(AuditNotDurable):
        await rig.apply("5")


async def test_position_leverage_an_unrecorded_outcome_never_changes_the_answer() -> None:
    rig = Rig()
    rig.records.fail_at = 1  # the intent lands, the outcome does not
    assert (await rig.apply("5")).changed is True


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (RateBudgetExceededError("spent", retry_after_s=2.2), RateBudgetExceeded),
        (TransportError("reset"), ExchangeUnavailable),
        (TimeoutError(), ExchangeUnavailable),
        (InsufficientMarginError("margin", exchange_ret_code=110012), ExchangeRejected),
        (InstrumentFilterError("tier", filter_name="risk_limit_tier"), ExchangeRejected),
    ],
    ids=["rate", "transport", "timeout", "rejected", "filter"],
)
async def test_position_leverage_a_venue_refusal_is_answered_and_recorded(
    raised: Exception, expected: type[OmsError]
) -> None:
    rig = Rig()
    rig.port.script("set_leverage", raised)
    with pytest.raises(expected) as refused:
        await rig.apply("5")
    assert [o for o, _ in rig.records.reasons()] == ["success", "failure"]
    if isinstance(refused.value, RateBudgetExceeded):
        assert refused.value.retry_after_s == 3
    if isinstance(refused.value, ExchangeRejected) and isinstance(raised, InsufficientMarginError):
        assert refused.value.ret_code == 110012


async def test_position_leverage_never_signs_for_another_environment() -> None:
    """C-2.11: a live account never reaches a demo process's port."""
    rig = Rig(account_env="live")
    with pytest.raises(EnvironmentMismatch):
        await rig.apply("5")
    assert rig.sent() == []


def test_position_leverage_bounds_must_be_positive() -> None:
    with pytest.raises(ValueError):
        PositionLeverage(Rig().deps(), call_timeout_s=0)


@given(
    st.decimals(min_value=Decimal("-5"), max_value=Decimal("150"), places=3),
    st.one_of(st.none(), st.integers(min_value=1, max_value=100).map(Decimal)),
)
def test_position_leverage_bounds_pass_exactly_the_values_inside_every_bound(
    value: Decimal, cap: Decimal | None
) -> None:
    """Hypothesis: no leverage outside a bound passes, and every one inside them does."""
    listed = instrument()
    held = _uncapped() if cap is None else profile(max_leverage_cap=cap, leverage=Decimal(1))
    inside = (
        listed.min_leverage <= value <= listed.max_leverage
        and value % listed.leverage_step == 0
        and (cap is None or value <= cap)
    )
    assert (bounds_errors(value, listed, held) == ()) is inside


class _Unread:
    """`TradingAccounts` whose read fails, or answers another account's ref."""

    def __init__(self, error: Exception | None) -> None:
        self.error = error

    async def trading_account(self, account_id: AccountId) -> Any:
        if self.error is not None:
            raise self.error
        return cr.ref(cr.LIVE_ACCOUNT)


@pytest.mark.parametrize(
    ("error", "expected"),
    [(TimeoutError(), StoreUnavailable), (StorageQueryFailed("57014"), StoreUnavailable),
     (None, ValueError)],
    ids=["timeout", "storage", "another_account"],
)  # fmt: skip
async def test_position_leverage_an_unread_account_sends_nothing(
    error: Exception | None, expected: type[Exception]
) -> None:
    rig = Rig()
    deps = replace(rig.deps(), accounts=_Unread(error))
    asked = LeverageRequest(POSITION, cr.ACCOUNT, Symbol(cr.SYMBOL), None, Decimal(5))
    with pytest.raises(expected):
        await PositionLeverage(deps).apply(asked, actor=ACTOR, request_id=None)
    assert rig.sent() == []


async def test_position_leverage_an_instrument_read_that_hangs_refuses() -> None:
    rig = Rig(instruments=Instruments(refuse=TimeoutError()))
    with pytest.raises(StoreUnavailable):
        await rig.apply("5")
    assert rig.sent() == []


async def test_position_leverage_a_rate_refusal_with_no_hint_waits_one_second() -> None:
    rig = Rig()
    rig.port.script("set_leverage", RateBudgetExceededError("spent"))
    with pytest.raises(RateBudgetExceeded) as refused:
        await rig.apply("5")
    assert refused.value.retry_after_s == 1


def test_position_leverage_a_value_no_context_can_divide_is_off_every_step() -> None:
    errors = bounds_errors(Decimal("1E+40"), instrument(), None)
    assert [e.rule for e in errors] == ["max_leverage", "leverage_step"]
