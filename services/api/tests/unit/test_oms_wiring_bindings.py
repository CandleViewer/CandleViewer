"""#913 slice 3B (E29-T04): the OMS's bounds and its bindings (`oms_wiring`, part 1), each failing
closed: the switches in their order, a refused credential through the adapter's own table, an
absent or unmeasured clock and an absent catalogue answering `oms_not_ready`, and the mid price."""

from __future__ import annotations

import dataclasses
import math
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.accounts.verification import Refusal
from candleviewer.admin.flags import LIVE_ENABLED, StoredFlag
from candleviewer.domain.events import Instrument
from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.exchange.base.errors import ExchangeError
from candleviewer.exchange.base.models import TickerEvent
from candleviewer.exchange.bybit.service import ExchangeBybitService
from candleviewer.flags_wiring import FeatureFlagsRuntime
from candleviewer.observability.metrics import Metrics
from candleviewer.oms import commands, idempotency, submit
from candleviewer.oms.clock_halt import ClockHalt
from candleviewer.oms.errors import (
    ClockDriftBlocked,
    OmsNotReady,
    OrderEntryRefused,
    TradingDisabled,
    problem_for,
)
from candleviewer.oms.fakes import FakeClockHealth
from candleviewer.oms.ports import INTERIM_PORTS_METRIC
from candleviewer.oms_wiring import (
    ClockHealthBinding,
    CredentialRejectionsBinding,
    InstrumentsBinding,
    InterimKillSwitch,
    OmsBounds,
    ReferencePricesBinding,
    TradingSwitchesBinding,
)
from candleviewer.settings import OMS_AFTER_ANCHOR_S, Settings
from tests.unit.admin.flag_fakes import FakeAudit, FakeStepUp, FakeUsers

ACCOUNT = AccountId(UUID(int=7))

# --- OmsBounds ------------------------------------------------------------------------------------


def test_bounds_of_the_default_settings_are_the_pipelines_own_defaults() -> None:
    """The settings and the components agree; M1's 12 s is the pipeline's own sum."""
    bounds = OmsBounds.from_settings(Settings())
    assert (bounds.submit_timeout_s, bounds.place_wait_s, bounds.stuck_after_s) == (
        commands.SUBMIT_TIMEOUT_S,
        submit.PLACE_WAIT_S,
        idempotency.STUCK_AFTER_S,
    )
    pipeline = submit._after_anchor_s(
        store_timeout_s=submit.STORE_TIMEOUT_S,
        place_wait_s=bounds.place_wait_s,
        result_wait_s=submit.RESULT_WAIT_S,
    )
    assert bounds.after_anchor_s == pipeline == bounds.submit_timeout_s + OMS_AFTER_ANCHOR_S


@pytest.mark.parametrize(
    ("change", "refused"),
    [
        (
            {"stuck_after_s": 17.0},
            "CV_OMS_INFLIGHT_STUCK_S",
        ),  # lowered to the 17 s after the anchor
        ({"stuck_after_s": 120.5}, "CV_OMS_INFLIGHT_STUCK_S"),  # past SEC-S3D-02's ceiling
        ({"submit_timeout_s": 8.5, "place_wait_s": 9.5}, "stop request"),  # raised: 2 + 8.5 > 10
        ({"submit_timeout_s": 10.0, "place_wait_s": 11.0, "stop_request_s": 13.0}, "command"),
        ({"place_wait_s": 5.0}, "place_wait_s"),  # not above the deadline (D-2B2-01)
        ({"result_wait_s": math.nan}, "result_wait_s"),
    ],
)
def test_bounds_refuse_a_set_that_breaks_a_relation(change: dict[str, float], refused: str) -> None:
    with pytest.raises(ValueError, match=refused):
        dataclasses.replace(OmsBounds.from_settings(Settings()), **change)


# --- TradingSwitchesBinding -----------------------------------------------------------------------

_GATE = OrderEntryRefusal("no_active_key", "The account has no active key.")


class _Check:
    """A kill switch or a gate answering `answer`, recording each account it is asked about."""

    def __init__(self, answer: Any = None) -> None:
        self.answer, self.asked = answer, list[UUID]()

    def refusal(self, account_id: UUID) -> Any:
        self.asked.append(account_id)
        return self.answer


def _switches(
    *, live: bool = True, flag: bool = True, b18: Any = None, gate: Any = None
) -> tuple[TradingSwitchesBinding, _Check, _Check]:
    kill, entry = _Check(b18), _Check(gate)
    binding = TradingSwitchesBinding(
        live_enabled=live, live_flag=lambda: flag, kill_switch=kill, gate=entry
    )
    return binding, kill, entry


@pytest.mark.parametrize(("live", "flag"), [(False, True), (True, False), (False, False)])
def test_switches_refuse_a_live_order_first_unless_both_preconditions_are_on(
    live: bool, flag: bool
) -> None:
    """Q4: the setting and the flag, else a reasonless `TradingDisabled`, nothing else asked."""
    binding, kill, entry = _switches(live=live, flag=flag, b18=TradingDisabled(), gate=_GATE)
    refused = binding.refusal(ACCOUNT, "live")
    assert type(refused) is TradingDisabled and (kill.asked, entry.asked) == ([], [])


@pytest.mark.parametrize("environment", ["demo", "testnet"])
def test_switches_ask_no_live_precondition_of_another_environment(environment: Environment) -> None:
    binding, kill, entry = _switches(live=False, flag=False)
    assert binding.refusal(ACCOUNT, environment) is None
    assert kill.asked == entry.asked == [ACCOUNT]


def test_switches_run_the_kill_switch_before_the_gate_and_the_first_refusal_wins() -> None:
    b18 = TradingDisabled()
    binding, kill, entry = _switches(b18=b18, gate=_GATE)
    assert binding.refusal(ACCOUNT, "live") is b18
    assert (kill.asked, entry.asked) == ([ACCOUNT], [])


def test_the_gates_refusal_is_order_entry_refused_carrying_its_reason() -> None:
    binding, _, entry = _switches(gate=_GATE)
    refused = binding.refusal(ACCOUNT, "live")
    assert isinstance(refused, OrderEntryRefused) and entry.asked == [ACCOUNT]
    assert (refused.reason, refused.detail) == ("no_active_key", "The account has no active key.")
    assert problem_for(refused).code == "trading_disabled"


async def test_the_live_flag_view_refuses_a_live_order_while_it_is_unread() -> None:
    """21 10.7: off until its first read, so a live order is refused with the setting on."""
    flags = FeatureFlagsRuntime(
        None,
        environment="live",
        audit=FakeAudit(),
        step_up=FakeStepUp(),
        users=FakeUsers(),
        sessions=cast(Any, SimpleNamespace(authenticated=list)),
    )
    binding = TradingSwitchesBinding(
        live_enabled=True,
        live_flag=flags.live_enabled,
        kill_switch=InterimKillSwitch(),
        gate=_Check(),
    )
    assert type(binding.refusal(ACCOUNT, "live")) is TradingDisabled
    await flags.live_enabled.on_change(LIVE_ENABLED, None, StoredFlag(True))
    assert binding.refusal(ACCOUNT, "live") is None


@pytest.mark.parametrize(("switch", "gauge"), [(InterimKillSwitch(), 1.0), (_Check(), 0.0)])
def test_the_kill_switch_is_announced_as_an_interim_port_while_the_interim_serves(
    switch: Any, gauge: float
) -> None:
    """Q5: the interim admits and is announced with one WARNING; a real switch counts 0."""
    binding, metrics = _switches()[0], Metrics("live")
    binding.kill_switch = switch
    with capture_logs() as logs:
        binding.announce(metrics=metrics)
    labels = {"env": "live", "port": "kill_switch"}
    assert metrics.registry.get_sample_value(INTERIM_PORTS_METRIC, labels) == gauge
    expected = [("oms_interim_port", "kill_switch", "E39-S03")] if gauge else []
    assert [(log["event"], log["port"], log["replaced_by"]) for log in logs] == expected
    assert InterimKillSwitch().refusal(ACCOUNT) is None


# --- CredentialRejectionsBinding ------------------------------------------------------------------


class _Standings:
    def __init__(self) -> None:
        self.rejected: list[tuple[UUID, Refusal]] = []

    def credential_rejected(self, account_id: UUID, refusal: Refusal) -> None:
        self.rejected.append((account_id, refusal))


class _Pager:
    """Records each page with what the standing held when it was raised."""

    def __init__(self, standings: _Standings, error: Exception | None = None) -> None:
        self.standings, self.error, self.pages = standings, error, list[tuple[Any, ...]]()

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        self.pages.append((severity, summary, machine_kind, list(self.standings.rejected)))
        if self.error is not None:
            raise self.error


@pytest.mark.parametrize(
    ("code", "refusal"),
    [
        (10003, Refusal.UNKNOWN_KEY),
        (10005, Refusal.PERMISSION_DENIED),
        (10010, Refusal.IP_NOT_ALLOWED),
        (33004, Refusal.KEY_EXPIRED),
        (10004, Refusal.UNKNOWN_KEY),  # a refused signature: no verdict in the table
        (110007, Refusal.UNKNOWN_KEY),  # a code the table does not hold
        (None, Refusal.UNKNOWN_KEY),
    ],
)
async def test_a_refused_credential_flips_the_standing_then_pages(
    code: int | None, refusal: Refusal
) -> None:
    """Q10 through the adapter's own table: an unlisted code or none is `unknown_key`."""
    standings = _Standings()
    pager = _Pager(standings)
    binding = CredentialRejectionsBinding(
        standings, key_refusal=ExchangeBybitService.key_refusal, pager=pager
    )
    await binding.refused(ACCOUNT, error_code="AUTH_ERROR", exchange_ret_code=code)
    assert standings.rejected == [(ACCOUNT, refusal)]
    assert pager.pages == [("page", "oms_credential_rejected", "order", [(ACCOUNT, refusal)])]


async def test_no_code_is_unknown_key_without_asking_the_table_and_a_pager_fault_is_logged() -> (
    None
):
    def table(error: ExchangeError) -> tuple[str, int] | None:
        raise AssertionError("the table keys on codes")

    standings = _Standings()
    binding = CredentialRejectionsBinding(
        standings, key_refusal=table, pager=_Pager(standings, RuntimeError("down"))
    )
    with capture_logs() as logs:
        await binding.refused(ACCOUNT, error_code="AUTH_ERROR", exchange_ret_code=None)
    assert standings.rejected == [(ACCOUNT, Refusal.UNKNOWN_KEY)]
    assert [log["event"] for log in logs] == ["oms_credential_rejected", "oms_pager_failed"]


# --- ClockHealthBinding and InstrumentsBinding: not composed or not measured is not ready ---------


async def test_no_clock_composed_is_not_ready_and_resyncs_nothing() -> None:
    clock = ClockHealthBinding(None)
    with pytest.raises(OmsNotReady):
        clock.assert_healthy()
    with pytest.raises(OmsNotReady):
        await clock.resync_after_signature_failure(reason="signature_failure")
    assert clock.offset_age_s() == math.inf


async def test_an_unmeasured_clock_is_not_ready_and_a_measured_halt_stays_clock_drift() -> None:
    """Q8 through the pipeline's halt: `oms_not_ready` until measured, then `clock_drift`."""
    now = [0.0]
    guard = FakeClockHealth(lambda: now[0])
    clock = ClockHealthBinding(guard)
    halt = ClockHalt(clock, monotonic=lambda: now[0], metrics=Metrics("demo"))
    with pytest.raises(OmsNotReady) as refused:
        halt.refusal()
    assert problem_for(refused.value).code == "oms_not_ready"
    guard.measure(0.0)
    assert halt.refusal() is None and clock.offset_age_s() == 0.0
    guard.measure(5_000.0)  # past the hard threshold
    assert isinstance(halt.refusal(), ClockDriftBlocked)
    await clock.resync_after_signature_failure(reason="signature_failure")
    assert guard.resyncs == ["signature_failure"]


class _Catalogue:
    def __init__(self, listed: dict[str, Instrument] | None) -> None:
        self.listed = listed

    def snapshot(self) -> Any:
        return None if self.listed is None else SimpleNamespace(get=self.listed.get)


@pytest.mark.parametrize("catalogue", [None, _Catalogue(None)], ids=["absent", "not_loaded"])
async def test_no_catalogue_is_not_ready_never_a_400(catalogue: _Catalogue | None) -> None:
    with pytest.raises(OmsNotReady) as refused:
        await InstrumentsBinding(catalogue).instrument("BTCUSDT")
    assert (problem_for(refused.value).status, refused.value.retry_after_s) == (503, 5)


async def test_a_catalogue_answers_a_listed_symbol_and_none_for_another() -> None:
    btc = cast(Instrument, object())
    instruments = InstrumentsBinding(_Catalogue({"BTCUSDT": btc}))
    assert await instruments.instrument("BTCUSDT") is btc
    assert await instruments.instrument("ETHUSDT") is None


# --- ReferencePricesBinding -----------------------------------------------------------------------


class _Tickers:
    def __init__(
        self, bid: str | None, ask: str | None, last: str | None, *, stale: bool = False
    ) -> None:
        prices = {"bid1_price": bid, "ask1_price": ask, "last_price": last}
        self.ticker = SimpleNamespace(
            **{name: None if p is None else Decimal(p) for name, p in prices.items()}
        )
        self.stale = stale

    def latest(self, symbol: str) -> TickerEvent | None:
        return cast(TickerEvent, self.ticker)

    def is_stale(self, symbol: str) -> bool:
        return self.stale


@pytest.mark.parametrize(
    ("tickers", "price"),
    [
        (_Tickers("100", "101", "99"), Decimal("100.5")),  # the mid
        (_Tickers(None, "101", "99"), Decimal("99")),  # one side missing: the last price
        (_Tickers("0", "101", "99"), Decimal("99")),  # a side at zero is no quote
        (_Tickers(None, None, None), None),
        (_Tickers("100", "101", "99", stale=True), None),  # a stale symbol has no price
        (None, None),  # no ticker stream composed
    ],
)
async def test_the_reference_price_is_the_mid_else_the_last(
    tickers: _Tickers | None, price: Decimal | None
) -> None:
    assert await ReferencePricesBinding(tickers).reference_price("BTCUSDT") == price
