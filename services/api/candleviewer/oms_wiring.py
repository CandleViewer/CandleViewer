"""Composition-root wiring (not a module) of the OMS (E29-T04, #913 slice 3; 24 Sec.8.4, 20
Sec.6.2), pure: nothing is started or mounted here.

Part 1: the OMS's time bounds from the settings (`OmsBounds`, 20 Sec.7.2), refused together so a
bad set fails the runtime's start, never a request, and the bindings of the ports `oms.ports`
declares, each failing closed. No venue module is imported (C-2.2): the adapter's key-verdict
table comes in as a callable, as `key_selfcheck_wiring` takes it.

Part 2: the reads and adapters that bind the OMS's ports to the modules that own them, as `oms`
imports no `audit`, `ws` or storage driver (C-3.1, C-3.3, ADR-0003).
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import Any, ClassVar, Final, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.verification import Refusal
from candleviewer.domain.events import Instrument
from candleviewer.domain.order_entry import OrderEntryCheck, OrderEntryRefusal
from candleviewer.domain.primitives import AccountId, Environment, Px, Symbol
from candleviewer.exchange.base.errors import AuthError, ExchangeError, OmsErrorCode
from candleviewer.exchange.base.models import AccountRef, TickerEvent
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.errors import (
    AccountScopeDenied,
    OmsNotReady,
    OrderEntryRefused,
    StoreUnavailable,
    TradingDisabled,
)
from candleviewer.oms.ports import ClockHealth, Interim, RuntimePortName, announce_interim_port
from candleviewer.oms.submit import RESULT_WAIT_S, STORE_TIMEOUT_S
from candleviewer.settings import OMS_INFLIGHT_STUCK_MAX_S, Settings
from candleviewer.statechart.config import CV_COMMAND_TIMEOUT, CV_PERSIST_TIMEOUT
from candleviewer.statechart.plugins import LogPager, Pager
from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.orders import OrderStoreError
from candleviewer.storage.repositories.trading_accounts import (
    TradingAccountReads,
    TradingAccountRow,
)

#: The stop request's bound (21 Sec.3.3.11, [LANE-25]), in seconds: how long an unanswered stop
#: request holds its key before it waits for the complete read (`RefuseWhileWaiting`); at least an
#: entry's answer path, 2 x `CV_PERSIST_TIMEOUT` + the submit timeout (`OmsBounds`). No safety
#: knob: either side of it refuses a second request for the key.
STOP_REQUEST_BOUND_S: Final = 10.0
#: B1's turn: what the pipeline's wait for the create's answer adds to the port's deadline.
B1_TURN_S: Final = 1.0
#: The environments whose orders meet no live precondition; any other value is live's (fail closed).
_NOT_LIVE: Final[frozenset[str]] = frozenset({"demo", "testnet"})
_REFUSALS: Final[dict[str, Refusal]] = {refusal.value: refusal for refusal in Refusal}
_PAGE: Final = "oms_credential_rejected"


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class OmsBounds:
    """The OMS's time bounds in seconds (24 Sec.8.4), each finite and above zero (C-2.18). The
    submit timeout bounds one create's `place`: a stop request's answer, 2 x `CV_PERSIST_TIMEOUT`
    + it, fits `stop_request_s`, and B1's `CV_COMMAND_TIMEOUT` never cuts it. `place_wait_s`
    outlasts it (D-2B2-01). `stuck_after_s`, the anchor service's own threshold (CR-S3D-01), is
    above `after_anchor_s`, so no repeat decides an anchor whose request may still send, and at
    most `OMS_INFLIGHT_STUCK_MAX_S` (SEC-S3D-02)."""

    submit_timeout_s: float
    place_wait_s: float
    stuck_after_s: float
    result_wait_s: float = RESULT_WAIT_S
    store_timeout_s: float = STORE_TIMEOUT_S
    stop_request_s: float = STOP_REQUEST_BOUND_S

    def __post_init__(self) -> None:
        for name in (bound.name for bound in fields(self)):
            if not (math.isfinite(seconds := getattr(self, name)) and seconds > 0):
                raise ValueError(f"{name} must be a finite number of seconds above zero")
        answer_s = 2 * CV_PERSIST_TIMEOUT + self.submit_timeout_s
        if answer_s > self.stop_request_s or not self.submit_timeout_s < CV_COMMAND_TIMEOUT:
            raise ValueError(
                f"submit_timeout_s ({self.submit_timeout_s:g} s): a stop request's answer must fit "
                f"{self.stop_request_s:g} s, and B1's command timeout must not cut a create"
            )
        if not self.place_wait_s > self.submit_timeout_s:
            raise ValueError(
                f"place_wait_s must outlast the submit timeout ({self.place_wait_s:g} s)"
            )
        if not self.after_anchor_s < self.stuck_after_s <= OMS_INFLIGHT_STUCK_MAX_S:
            raise ValueError(
                f"CV_OMS_INFLIGHT_STUCK_S ({self.stuck_after_s:g} s) must be above the bounds "
                f"after the anchor ({self.after_anchor_s:g} s) and at most "
                f"{OMS_INFLIGHT_STUCK_MAX_S:g} s"
            )

    @property
    def after_anchor_s(self) -> float:
        """A request's bounds once its anchor exists: `SEND`'s write, the create's answer, its
        result step and four store bounds (24 Sec.8.4; the pipeline's `_after_anchor_s`)."""
        waits = self.place_wait_s + self.result_wait_s
        return CV_PERSIST_TIMEOUT + waits + 4 * self.store_timeout_s

    @classmethod
    def from_settings(cls, settings: Settings) -> OmsBounds:
        submit_s = settings.oms_submit_timeout_ms / 1000
        return cls(
            submit_timeout_s=submit_s,
            place_wait_s=submit_s + B1_TURN_S,
            stuck_after_s=settings.oms_inflight_stuck_s,
        )


class KillSwitch(Protocol):
    """The B18 kill switch's synchronous verdict for an account (24 Sec.8.10): its refusal, or
    None. E39-S03 lands the engine; until then `InterimKillSwitch` serves (ruling Q5)."""

    def refusal(self, account_id: AccountId) -> TradingDisabled | None: ...


class InterimKillSwitch(Interim):
    """The B18 kill switch until E39-S03 (ruling Q5): no engine or writer exists, so it admits,
    announced at startup as an interim port (`TradingSwitchesBinding.announce`)."""

    port: ClassVar[RuntimePortName] = "kill_switch"
    replaced_by: ClassVar[str] = "E39-S03"
    serves: ClassVar[str] = (
        "admits every order; killswitch.order_entry still stops order entry through the gate"
    )

    def refusal(self, account_id: AccountId) -> TradingDisabled | None:
        return None


class TradingSwitchesBinding:
    """`TradingSwitches` (C-2.21; 24 Sec.8.4): the route's step 10 and B1's `SEND` ask it. It reads
    memory only and never awaits, and the first refusal wins:

    1. live trading enabled, for a live account: the `CV_TRADING_LIVE_ENABLED` setting and the
       `trading.live_enabled` flag's view, which is off while unread, both on (rulings Q4, Q6);
       either off is `TradingDisabled` without a `reason`;
    2. the B18 kill switch, `InterimKillSwitch` until E39-S03 (ruling Q5);
    3. the app's one order-entry gate (24 Sec.8.4.1): its refusal is `OrderEntryRefused`, carrying
       the gate's `reason`."""

    def __init__(
        self,
        *,
        live_enabled: bool,
        live_flag: Callable[[], bool],
        kill_switch: KillSwitch,
        gate: OrderEntryCheck,
    ) -> None:
        self._live_enabled, self._live_flag = live_enabled, live_flag
        self._kill_switch, self._gate = kill_switch, gate

    def refusal(self, account_id: AccountId, environment: Environment) -> TradingDisabled | None:
        if environment not in _NOT_LIVE and not (self._live_enabled and self._live_flag()):
            return TradingDisabled()
        switched = self._kill_switch.refusal(account_id)
        if switched is not None:
            return switched
        gate = self._gate.refusal(account_id)
        return None if gate is None else OrderEntryRefused(gate)

    def announce(self, *, metrics: Metrics) -> None:
        """At startup (20 Sec.6.2): `oms_interim_ports{port="kill_switch"}` at 1 with one WARNING
        while the interim serves the B18 kill switch, else at 0."""
        announce_interim_port("kill_switch", self._kill_switch, metrics=metrics)


class KeyStandingReactions(Protocol):
    """The member of `accounts.key_standing.KeyStandings` the binding calls (24 Sec.8.4.1)."""

    def credential_rejected(self, account_id: UUID, refusal: Refusal) -> None: ...


#: The adapter's key-verdict table (`ExchangeBybitService.key_refusal`): `(reason, code)` when a
#: signed call's refusal is a verdict about the key, else None.
KeyRefusalTable = Callable[[ExchangeError], tuple[str, int] | None]


class CredentialRejectionsBinding:
    """`CredentialRejections` (24 Sec.8.4 "A refused credential"; ruling Q10): the return code
    through the adapter's key-verdict table to its `Refusal`; one outside it, `10004` among them, or
    none is `UNKNOWN_KEY`, fail closed. The key standing takes it first, in memory, so the account
    admits no order in this process until a recorded pass clears it; then the Owner is paged, the
    summary naming the account. The durable reaction is #4243.

    Every report flips the standing (fail closed, C-2.21). Only a report of kind `AUTH_ERROR`
    reads the table, which `OmsCommandPort._venue`, the port's one caller, sends with a return
    code; a report of any other kind is `UNKNOWN_KEY` whatever code it carries, and pages."""

    def __init__(
        self,
        standings: KeyStandingReactions,
        *,
        key_refusal: KeyRefusalTable,
        pager: Pager | None = None,
    ) -> None:
        self._standings, self._key_refusal = standings, key_refusal
        self._pager: Pager = LogPager() if pager is None else pager

    def verdict(self, exchange_ret_code: int | None) -> Refusal:
        """The code's `Refusal`: `UNKNOWN_KEY` for a code the table does not hold, or none."""
        if exchange_ret_code is None:  # the table keys on codes: none is looked up
            return Refusal.UNKNOWN_KEY
        refused = AuthError("the exchange refused the key", exchange_ret_code=exchange_ret_code)
        found = self._key_refusal(refused)
        return (
            Refusal.UNKNOWN_KEY if found is None else _REFUSALS.get(found[0], Refusal.UNKNOWN_KEY)
        )

    async def refused(
        self, account_id: AccountId, *, error_code: str, exchange_ret_code: int | None
    ) -> None:
        # Fail closed (ruling Q10): any report flips the standing. Only an `AUTH_ERROR` reads the
        # adapter's table; any other kind, which `_venue` does not report today, is `UNKNOWN_KEY`.
        refusal = (
            self.verdict(exchange_ret_code)
            if error_code == OmsErrorCode.AUTH_ERROR
            else Refusal.UNKNOWN_KEY
        )
        self._standings.credential_rejected(account_id, refusal)  # held before it is logged
        _log().critical(
            _PAGE,
            account_id=str(account_id),
            error_code=error_code,
            exchange_ret_code=exchange_ret_code,
            refusal=refusal.value,
        )
        summary = f"{_PAGE}: account {account_id}"
        try:
            self._pager.raise_alert("page", summary, machine_kind="order")
        except Exception as exc:  # the standing holds whatever the pager does
            _log().critical("oms_pager_failed", summary=summary, failure=type(exc).__name__)


class ClockHealthBinding:
    """`ClockHealth` over the exchange clock guard (`ingestion.clock.ClockGuard`), which only the
    public stream's wiring composes (ruling Q8): with none composed, or one that has not measured
    yet, order entry is not ready (`OmsNotReady`, 503 `oms_not_ready`); only a measured halt is the
    guard's `ClockDriftError` (`clock_drift`, 24 Sec.8.4 item 2)."""

    def __init__(self, guard: ClockHealth | None) -> None:
        self._guard = guard

    def assert_healthy(self) -> None:
        if self._guard is None or not math.isfinite(self._guard.offset_age_s()):
            raise OmsNotReady
        self._guard.assert_healthy()

    def offset_age_s(self) -> float:
        return math.inf if self._guard is None else self._guard.offset_age_s()

    async def resync_after_signature_failure(self, *, reason: str) -> int:
        if self._guard is None:  # nothing to measure; the halt stands (`ClockHalt.resync`)
            raise OmsNotReady
        return await self._guard.resync_after_signature_failure(reason=reason)


class CatalogueReading(Protocol):
    def get(self, symbol: str) -> Instrument | None: ...


class InstrumentCatalogue(Protocol):
    """`ingestion.instruments_refresh.InstrumentsRefreshScheduler`'s read (24 Sec.1.3)."""

    def snapshot(self) -> CatalogueReading | None: ...


class InstrumentsBinding:
    """`Instruments` over the instrument catalogue's snapshot, no I/O (ruling Q8): with none
    composed or none loaded yet, order entry is not ready (`OmsNotReady`), never a 400 saying the
    symbol is not listed; a symbol listed since the last refresh waits for the next one."""

    def __init__(self, catalogue: InstrumentCatalogue | None) -> None:
        self._catalogue = catalogue

    async def instrument(self, symbol: Symbol) -> Instrument | None:
        snapshot = None if self._catalogue is None else self._catalogue.snapshot()
        if snapshot is None:
            raise OmsNotReady
        return snapshot.get(symbol)


class Tickers(Protocol):
    """`ingestion.ticker_stream.TickerStream`'s reads: the last ticker a symbol showed, and
    whether the stream holds that symbol stale."""

    def latest(self, symbol: str) -> TickerEvent | None: ...

    def is_stale(self, symbol: str) -> bool: ...


class ReferencePricesBinding:
    """`ReferencePrices` over the ticker stream (24 Sec.9.3 step 2): the mid of the best bid and
    ask, else the last price; None with neither, with the symbol stale, or with no stream
    composed, which the pipeline answers 503 `exchange_unavailable`: a stale price never sizes,
    caps or checks a market order (the orchestrator's ruling, 2026-10-23)."""

    def __init__(self, tickers: Tickers | None) -> None:
        self._tickers = tickers

    async def reference_price(self, symbol: Symbol) -> Px | None:
        if self._tickers is None or self._tickers.is_stale(symbol):
            return None
        ticker = self._tickers.latest(symbol)
        if ticker is None:
            return None
        bid, ask = ticker.bid1_price, ticker.ask1_price
        if bid is not None and ask is not None and _priced(bid) and _priced(ask):
            return (bid + ask) / 2
        return ticker.last_price


def _priced(price: Px) -> bool:
    return price.is_finite() and price > 0


# --- part 2: the reads and adapters (#913 slice 3C) ---

#: Bounds the account read (C-2.18), whatever its caller bounds its own call with.
ACCOUNT_READ_TIMEOUT_S: Final = 2.0
#: The order-entry gate's answer for an account with no usable key (`accounts.order_gate`), which
#: `trading_account` gives an account whose key went after the gate read it.
NO_ACTIVE_KEY: Final = OrderEntryRefusal("no_active_key", "The account has no verified active key.")


class TradingAccountsBinding:
    """`oms.ports.TradingAccounts` over the principal-free account read, which only this module
    may name (C-12.4, `test_oms_system_reads_callers.py`), for the process's environment (C-2.11).
    An account that does not exist, is soft-deleted or is another environment's is
    `AccountScopeDenied`, all three alike (no oracle). `environment_of` is the route's existence
    step (24 Sec.8.4 step 4), after its RBAC check: a keyless account passes it, so the gate
    answers `no_active_key`, which `trading_account` answers too. A read that fails or does not
    answer within `timeout_s` is `StoreUnavailable`."""

    def __init__(
        self,
        reads: TradingAccountReads,
        *,
        environment: Environment,
        timeout_s: float = ACCOUNT_READ_TIMEOUT_S,
    ) -> None:
        self._reads, self._environment, self._timeout_s = reads, environment, timeout_s

    async def trading_account(self, account_id: AccountId) -> AccountRef:
        """The ref names the account the read returned, so a caller's check catches a read that
        answered another one (SR-E27-21)."""
        row = await self._live(account_id)
        if row.active_key_id is None:
            raise OrderEntryRefused(NO_ACTIVE_KEY)
        return AccountRef(
            account_id=AccountId(row.account_id),
            uid=row.exchange_uid,
            environment=row.environment,
            key_ref=str(row.active_key_id),
        )

    async def environment_of(self, account_id: AccountId) -> Environment:
        return (await self._live(account_id)).environment

    async def _live(self, account_id: AccountId) -> TradingAccountRow:
        try:
            async with asyncio.timeout(self._timeout_s):
                row = await self._reads.read_account(account_id)
        except (TimeoutError, StorageError, OrderStoreError) as exc:
            structlog.get_logger(__name__).warning("oms_account_unread", error=type(exc).__name__)
            raise StoreUnavailable from None
        if row is None or row.deleted or row.environment != self._environment:
            raise AccountScopeDenied
        return row
