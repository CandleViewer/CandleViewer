"""Composition-root wiring (not a module) of the OMS (E29-T04, #913 slice 3; 24 Sec.8.4, 20
Sec.6.2). Parts 1 and 2 are pure: nothing is started or mounted there.

Part 1: the OMS's time bounds from the settings (`OmsBounds`, 20 Sec.7.2), refused together so a
bad set fails the runtime's start, never a request, and the bindings of the ports `oms.ports`
declares, each failing closed. No venue module is imported (C-2.2): the adapter's key-verdict
table comes in as a callable, as `key_selfcheck_wiring` takes it.

Part 2: the reads and adapters that bind the OMS's ports to the modules that own them, as `oms`
imports no `audit`, `ws` or storage driver (C-3.1, C-3.3, ADR-0003).

Part 3: the OMS runtime (`build_oms_runtime`, `OmsRuntime`), which the lifespan starts and stops.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Final, Literal, Protocol, cast
from uuid import UUID

import structlog

from candleviewer.accounts.trade_group_repository import TradeGroupReader, TradeGroupRepository
from candleviewer.accounts.verification import Refusal
from candleviewer.admin.wiring import (
    MachineEventSinkMetrics,
    build_machine_event_sink,
    keyed_record_id,
)
from candleviewer.domain.events import Instrument
from candleviewer.domain.order_entry import OrderEntryCheck, OrderEntryRefusal
from candleviewer.domain.primitives import AccountId, Environment, Px, Symbol
from candleviewer.exchange.base.errors import AuthError, ExchangeError, OmsErrorCode
from candleviewer.exchange.base.models import AccountRef, RateLane, TickerEvent
from candleviewer.observability import spawn, spawn_child
from candleviewer.observability.metrics import BoundedMetric, Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.oms.clock_halt import ClockHalt
from candleviewer.oms.commands import NEVER_SENT_ALERT, OmsCommandPort
from candleviewer.oms.errors import (
    AccountScopeDenied,
    AuditNotDurable,
    OmsNotReady,
    OrderEntryRefused,
    OrderHistoryRefused,
    StoreUnavailable,
    TradingDisabled,
)
from candleviewer.oms.idempotency import AnchorService
from candleviewer.oms.order_link_allocator import OrderLinkIdAllocator
from candleviewer.oms.order_machine import (
    MAX_MACHINES,
    CompositePublisher,
    OrderAuditRecord,
    OrderMachinePorts,
    OrderMachines,
    OrderNotice,
)
from candleviewer.oms.order_steps import OrderStepWriter
from candleviewer.oms.ports import (
    ArmRecords,
    ClockHealth,
    Interim,
    KeyedRecord,
    NoHandoverStore,
    Profiles,
    RequestRecord,
    RuntimePortName,
    SubmissionPorts,
    SubmitActor,
    announce_interim_port,
    announce_interim_ports,
)
from candleviewer.oms.repository import (
    ExecutionRepository,
    IdempotencyAnchorRepository,
    OrderEventRepository,
    OrderRepository,
    RecordedStopRepository,
    SubmissionRepository,
    WriteTimer,
)
from candleviewer.oms.routing import RoutedPort, TradingRouter
from candleviewer.oms.stop_gate import ResolvingStopGate, StopVoidAudit
from candleviewer.oms.stop_resolution import CompleteRead, StopResolver
from candleviewer.oms.submit import RESULT_WAIT_S, STORE_TIMEOUT_S, OrderSubmission, SubmissionDeps
from candleviewer.oms.validator import ReadOnlyCheck, Validator
from candleviewer.settings import OMS_INFLIGHT_STUCK_MAX_S, OMS_STOP_RESERVE_S, Settings
from candleviewer.statechart.bindings.b01_order import ALREADY_TERMINAL
from candleviewer.statechart.config import CV_COMMAND_TIMEOUT, CV_PERSIST_TIMEOUT
from candleviewer.statechart.persistence import ChainTripLatch
from candleviewer.statechart.plugins import LogPager, MachineEventSink, Pager
from candleviewer.statechart.plugins.state_feed import (
    FeedBinding,
    MachineStateHandle,
    MachineStatePort,
)
from candleviewer.statechart.registry import Registry
from candleviewer.statechart_wiring import EventFramesAdapter, EventsAdapter, PersistOps
from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.executions import ExecutionStore
from candleviewer.storage.repositories.executions_sqlalchemy import SqlAlchemyExecutionStore
from candleviewer.storage.repositories.idempotency_anchors import IdempotencyAnchorStore
from candleviewer.storage.repositories.idempotency_anchors_sqlalchemy import (
    SqlAlchemyIdempotencyAnchorStore,
)
from candleviewer.storage.repositories.orders import (
    OrderEventStore,
    OrderRow,
    OrderStore,
    OrderStoreError,
    UnfinishedOrders,
)
from candleviewer.storage.repositories.orders_sqlalchemy import SqlAlchemyOrderStore
from candleviewer.storage.repositories.recorded_stops import (
    SWEEP_REASON,
    RecordedStopStore,
    SweptStop,
)
from candleviewer.storage.repositories.recorded_stops_sqlalchemy import (
    SqlAlchemyRecordedStopStore,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)
from candleviewer.storage.repositories.statechart_sqlalchemy import SqlAlchemyEventStore
from candleviewer.storage.repositories.submissions import SubmissionStore
from candleviewer.storage.repositories.submissions_sqlalchemy import SqlAlchemySubmissionStore
from candleviewer.storage.repositories.trade_groups import TradeGroupReads, TradeGroupStore
from candleviewer.storage.repositories.trade_groups_sqlalchemy import SqlAlchemyTradeGroupStore
from candleviewer.storage.repositories.trading_accounts import (
    TradingAccountReads,
    TradingAccountRow,
)
from candleviewer.storage.repositories.trading_accounts_sqlalchemy import (
    SqlAlchemyTradingAccountReads,
)

if TYPE_CHECKING:
    from candleviewer.app import AppContext

#: The stop request's bound (21 Sec.3.3.11, [LANE-25]), in seconds: how long an unanswered stop
#: request holds its key before it waits for the complete read (`ResolvingStopGate`); above an
#: entry's answer path, 3 x `CV_PERSIST_TIMEOUT` + the submit timeout, and at least an attach's,
#: B1's `CV_COMMAND_TIMEOUT` (`OmsBounds`). No safety knob: either side of it refuses a second
#: request for the key.
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
    submit timeout bounds one create's `place`. An entry's stop request is answered within
    3 x `CV_PERSIST_TIMEOUT` + it (its first persist stamps the row's `created_at`, then its
    `SEND` and its result step), strictly inside `stop_request_s`, and an attach's within B1's
    `CV_COMMAND_TIMEOUT`, at most `stop_request_s`: on its clean path, the complete read never
    lists a row its writer may still answer (21 Sec.3.3.11); a persist whose commit lands late is
    the step writer's compare-and-set's to settle. B1's command timeout never cuts a create, and
    `place_wait_s` outlasts it (D-2B2-01). `stuck_after_s`, the anchor service's own threshold
    (CR-S3D-01), is above `after_anchor_s`, so no repeat decides an anchor whose request may still
    send, and at most `OMS_INFLIGHT_STUCK_MAX_S` (SEC-S3D-02)."""

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
        if not 3 * CV_PERSIST_TIMEOUT + self.submit_timeout_s < self.stop_request_s:
            raise ValueError(
                f"submit_timeout_s ({self.submit_timeout_s:g} s): an entry's stop request, "
                f"answered within 3 x CV_PERSIST_TIMEOUT + it, must land inside "
                f"{self.stop_request_s:g} s"
            )
        if not CV_COMMAND_TIMEOUT <= self.stop_request_s:
            raise ValueError(
                f"stop_request_s ({self.stop_request_s:g} s): an attach's stop request, answered "
                f"within B1's {CV_COMMAND_TIMEOUT:g} s command timeout, must land inside it"
            )
        if not self.submit_timeout_s < CV_COMMAND_TIMEOUT:
            raise ValueError(
                f"submit_timeout_s ({self.submit_timeout_s:g} s): B1's {CV_COMMAND_TIMEOUT:g} s "
                "command timeout must not cut a create"
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
    caps or checks a market order (the orchestrator's ruling, 2026-10-23). With `demand`, each
    ask is told to it, so a symbol no consumer holds is subscribed for the retry (CR-S3B2-03)."""

    def __init__(self, tickers: Tickers | None, *, demand: ReferenceDemand | None = None) -> None:
        self._tickers, self._demand = tickers, demand

    async def reference_price(self, symbol: Symbol) -> Px | None:
        price = self._price(symbol)
        if self._demand is not None:
            self._demand.asked(symbol, priced=price is not None)
        return price

    def _price(self, symbol: Symbol) -> Px | None:
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


#: CR-S3B2-03: how many symbols the reference prices hold a ticker demand for at once (C-2.18),
#: and, in seconds, how long after the last ask for a symbol the next ask of any releases it (no
#: timer runs: with no later ask it is held until the runtime's stop); the stream then keeps the
#: topic its own grace (`ingestion.planner.DEFAULT_GRACE_S`, 30 s). CR-S3E4-02: at most
#: `REFERENCE_DEMAND_NEW` new symbols a `REFERENCE_DEMAND_WINDOW_S`, so market orders on distinct
#: symbols cannot drive the public stream's subscribe frames at the request rate.
REFERENCE_DEMAND_MAX: Final = 16
REFERENCE_DEMAND_TTL_S: Final = 120.0
REFERENCE_DEMAND_NEW: Final = 4
REFERENCE_DEMAND_WINDOW_S: Final = 60.0


class TickerDemand(Protocol):
    """`ingestion.ticker_stream.TickerStream`'s demand: it subscribes a symbol only while a
    consumer holds it, and keeps it a grace after the last one lets go."""

    def acquire(self, consumer: str, symbol: str) -> None: ...

    def release(self, consumer: str, symbol: str) -> None: ...


class DemandTickers(Tickers, TickerDemand, Protocol):
    """The ticker stream as the runtime composes it: its reads and its demand."""


class ReferenceDemand:
    """CR-S3B2-03: the ticker stream subscribes on demand, so a market order on a symbol no
    consumer holds has no reference price and is answered 503 `exchange_unavailable`. On such a
    refusal the reference prices take a demand for the symbol, so the client's retry after
    `Retry-After` finds a price. At most `REFERENCE_DEMAND_MAX` symbols are held, the one asked
    for least recently let go first; each is released at the next ask made `REFERENCE_DEMAND_TTL_S`
    (120 s) after the last one for it: each ask checks, no timer runs, so with no later ask the
    symbols stay held, and subscribed, until `close()`, at the runtime's stop, lets every one go.
    At most `REFERENCE_DEMAND_NEW` new symbols are taken per `REFERENCE_DEMAND_WINDOW_S` across
    the runtime (CR-S3E4-02): past that `asked` takes no new demand, so the order answers 503 as
    before, and the cap is logged once a window. A symbol the stream refuses (no catalogue lists
    it) takes none, and once closed `asked` does nothing (CR-S3E4-05)."""

    CONSUMER: ClassVar[str] = "oms-reference-prices"

    def __init__(
        self, stream: TickerDemand, *, monotonic: Callable[[], float] = time.monotonic
    ) -> None:
        self._stream, self._monotonic = stream, monotonic
        self._held: OrderedDict[str, float] = OrderedDict()
        self._window_at, self._taken, self._capped = -math.inf, 0, False
        self._closed = False

    def asked(self, symbol: str, *, priced: bool) -> None:
        """An ask for `symbol`'s price, `priced` when it had one: held ones are kept from now."""
        if self._closed:
            return
        now = self._monotonic()
        for held, at in list(self._held.items()):
            if now - at >= REFERENCE_DEMAND_TTL_S:
                self._let_go(held)
        if symbol not in self._held:
            if priced or not self._within_budget(now):
                return
            try:
                self._stream.acquire(self.CONSUMER, symbol)
            except ValueError:  # a symbol no catalogue lists: no topic to hold
                return
            self._taken += 1
        self._held[symbol] = now
        self._held.move_to_end(symbol)
        while len(self._held) > REFERENCE_DEMAND_MAX:
            self._let_go(next(iter(self._held)))

    def _within_budget(self, now: float) -> bool:
        """Whether one more new symbol fits this window; the first refusal of a window is logged."""
        if now - self._window_at >= REFERENCE_DEMAND_WINDOW_S:
            self._window_at, self._taken, self._capped = now, 0, False
        if self._taken < REFERENCE_DEMAND_NEW:
            return True
        if not self._capped:
            self._capped = True
            _log().warning(
                "oms_reference_demand_capped",
                new=REFERENCE_DEMAND_NEW, window_s=REFERENCE_DEMAND_WINDOW_S,
            )  # fmt: skip
        return False

    async def close(self) -> None:
        self._closed = True
        for symbol in list(self._held):
            self._let_go(symbol)

    def _let_go(self, symbol: str) -> None:
        del self._held[symbol]
        self._stream.release(self.CONSUMER, symbol)


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
            _log().warning("oms_account_unread", error=type(exc).__name__)
            raise StoreUnavailable from None
        if row is None or row.deleted or row.environment != self._environment:
            raise AccountScopeDenied
        return row


#: The actor of a record no principal asks for (24 Sec.15.5).
SYSTEM_ACTOR: Final = "system:oms"


class AuditWriterPort(Protocol):
    """`AuditWriter`'s durable appends (C-2.9) with the columns this module writes: the root may
    not import `audit` (C-3.3), so `outcome`, `severity` and `env` go as their plain values."""

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: UUID | None = None,
        actor_ip: str | None = None,
        session_id: UUID | None = None,
        object_kind: str | None = None,
        object_id: str | None = None,
        outcome: Any = ...,
        severity: Any = ...,
        reason: str | None = None,
        after_state: dict[str, Any] | None = None,
        request_id: UUID | None = None,
        env: Any = None,
    ) -> None: ...

    async def emit_keyed(self, action: str, name: str, **fields: Any) -> None: ...


def _actor(actor: SubmitActor | None, user_id: UUID | None) -> dict[str, Any]:
    """The columns that say who acted: the user and role of `actor`, else the OMS itself. A record
    that names a user but no actor has no role to record (C-2.9), so it is refused, never
    labelled without one: a site that drops the actor fails its write."""
    if actor is not None:
        return {
            "actor_label": f"user:{actor.role}",
            "actor_user_id": actor.user_id,
            "actor_ip": actor.ip,
            "session_id": actor.session_id,
        }
    if user_id is not None:
        raise ValueError("a record that names a user has no role to record without its actor")
    return {"actor_label": SYSTEM_ACTOR, "actor_user_id": None}


class OmsAudit:
    """The OMS's `SubmitAudit` and `OrderAudit` over the audit writer: a `KeyedRecord` through
    `emit_keyed`, under the id `record_id` names ahead (`keyed_record_id`), a `RequestRecord` and
    an `OrderAuditRecord` through `emit`. A record names its actor and role (`user:<role>`, with
    its session and address), or `system:oms` where none is given, its object, its account and
    detail as `after_state` (ids, state names and codes, C-12.6), its correlation id and the
    process's environment. `write` returns once the record is durable, else raises (C-2.9)."""

    def __init__(self, writer: AuditWriterPort, *, environment: Environment) -> None:
        self._writer, self._environment = writer, environment

    def record_id(self, action: str, name: str) -> UUID:
        return keyed_record_id(action, name)

    async def write(self, record: KeyedRecord | RequestRecord | OrderAuditRecord) -> None:
        fields: dict[str, Any] = {
            "outcome": record.outcome,
            "severity": record.severity,
            "reason": record.reason,
            "after_state": {**record.detail, "account_id": str(record.account_id)},
            "request_id": record.request_id,
            "env": self._environment,
        }
        if isinstance(record, OrderAuditRecord):
            fields |= _actor(None, None) | {"object_kind": "order"}
            await self._writer.emit(record.action, object_id=str(record.order_id), **fields)
            return
        fields |= {"object_kind": record.object_kind, "object_id": str(record.object_id)}
        if isinstance(record, KeyedRecord):
            fields |= _actor(record.actor, record.actor_user_id)
            await self._writer.emit_keyed(record.action, record.name, **fields)
        else:
            fields |= _actor(record.actor, record.actor.user_id)
            await self._writer.emit(record.action, **fields)


#: The notices whose owners have not landed: an ERROR and a page each until they do.
UNOWNED_NOTICES: Final = MappingProxyType(
    {"request_reconciliation": "E29-T06", "request_fallback_sl": "E32"}
)
#: The alerts the pager takes as a ticket, not a page: an order a restart found never sent, and one
#: the venue does not hold (110001), `unknown` until reconciliation reads it (S4-B1's ruling). The
#: request to reconcile that order (`reason` `already_terminal`) is a ticket too: one case, one
#: notice (ruling A); `quarantined`'s request names no reason and pages.
_TICKETS: Final = frozenset({NEVER_SENT_ALERT, "order_already_terminal"})
#: The alerts an order raises, a closed set: the order machine's (`raise_unknown_alert`,
#: `raise_critical_alert` on `quarantined` and `held`, `raise_naked_position_alert`) and the one a
#: resumed create past its history raises (`oms.commands`). Only these are logged and paged by
#: name, so a value of any other source, a key among them, is never a name (SEC-S3C2-01, C-12.6).
ORDER_ALERTS: Final = frozenset(
    {"order_unknown", "order_quarantined", "order_held", "SL_ATTACH_FAILED", NEVER_SENT_ALERT}
    | _TICKETS
)
#: The codes of a refused amend, a closed set too: the adapters' taxonomy (24 Sec.8.6).
_ERROR_CODES: Final = frozenset(code.value for code in OmsErrorCode)
_NAME: Final = re.compile(r"[A-Za-z0-9_]{1,64}")


def _name(value: object) -> str:
    """A code or a name as logged: itself when it is a plain name, else `unnamed`."""
    return value if isinstance(value, str) and _NAME.fullmatch(value) else "unnamed"


def _named(value: object, known: frozenset[str]) -> str:
    """`value` when it is one of the `known` names, else `unnamed`: the shape of `_name` says a
    name is plain, not that it is no secret, so a source with a closed set is held to it."""
    return value if isinstance(value, str) and value in known else "unnamed"


class OrderNoticesRouter:
    """`order_machine.OrderNotices`: an `alert` goes to the pager (a page, but a never-sent
    order's, which is a ticket); `request_reconciliation` and `request_fallback_sl` are an ERROR
    and a page until E29-T06 and E32 own them (but a reconciliation asked for an order the venue
    does not hold, which is a ticket); `amend_rejected` is a log line. It logs the order's
    ids, the notice's names and the venue's code when an integer, never a price, a size or a key
    (C-12.6): an alert is named only from `ORDER_ALERTS` and an amend's code from `OmsErrorCode`,
    else `unnamed`. It never raises: a notice it cannot route is a CRITICAL log and a page,
    whatever it was, and a failing pager is logged at CRITICAL."""

    def __init__(self, pager: Pager) -> None:
        self._pager = pager

    async def notify(self, notice: OrderNotice) -> None:
        try:
            self._route(notice)
        except Exception as exc:  # not routed, maybe page-worthy: logged and paged, never raised
            kind, error = _name(getattr(notice, "kind", None)), type(exc).__name__
            _log().critical("oms_notice_unrouted", kind=kind, error=error)
            self._raise("page", f"order notice {kind} not routed: {error}")

    def _route(self, notice: OrderNotice) -> None:
        log = _log()
        ids = {
            "order_id": str(notice.order_id),
            "account_id": str(notice.account_id),
            "order_link_id": notice.order_link_id,
        }
        kind = notice.kind
        if kind == "alert":
            alert = _named(notice.detail.get("alert"), ORDER_ALERTS)
            ret = notice.detail.get("exchange_ret_code")  # logged only as an integer (C-12.6)
            shown = {"exchange_ret_code": ret} if type(ret) is int else {}
            log.error("oms_order_alert", alert=alert, **ids, **shown)
            self._raise("alert" if alert in _TICKETS else "page", f"order alert {alert}")
        elif kind in UNOWNED_NOTICES:
            owner = UNOWNED_NOTICES[kind]
            log.error("oms_order_notice_unowned", kind=kind, owner=owner, **ids)
            reason = notice.detail.get("reason") if kind == "request_reconciliation" else None
            if reason == ALREADY_TERMINAL and notice.detail.get("alerted") is True:
                return  # its case's `order_already_terminal` alert is the one ticket (14:30Z)
            summary = f"order notice {kind} has no owner until {owner}"
            self._raise("alert" if reason == ALREADY_TERMINAL else "page", summary)
        elif kind == "amend_rejected":
            code = _named(notice.detail.get("error_code"), _ERROR_CODES)
            log.warning("oms_amend_rejected", error_code=code, **ids)
        else:
            log.error("oms_order_notice_unknown", kind=_name(kind), **ids)
            self._raise("page", "order notice of an unknown kind")

    def _raise(self, severity: Literal["page", "alert"], summary: str) -> None:
        try:
            self._pager.raise_alert(severity, summary, machine_kind="order")
        except Exception as exc:  # the alert is lost, never the notice's caller
            _log().critical("oms_pager_failed", summary=summary, failure=type(exc).__name__)


class OrderStateFeed:
    """The machine-state member of the order facade's publisher (`order_machine.CompositePublisher`,
    23 Sec.6.4 `machines.order:{id}.state`; the WS `orders` topics are E29-T10's): each order's slot
    bound through `RegistryFeed` once, scoped to its account (OM-I02), and dropped on its last
    step. A machine stopped before its last step keeps its slot, so at most `max_orders` (one or
    more) are held, the least recently published dropped first (C-2.18): a later step binds it
    again.

    It publishes into the WS registry directly, which is single-threaded and bound to the serving
    loop, so it must run on that loop: the runtime builds the order facade there (slice 3E), and a
    machine on another loop would have to hop with `call_soon_threadsafe` first
    (`machine_state_wiring`)."""

    def __init__(self, feed: MachineStatePort, *, max_orders: int = MAX_MACHINES) -> None:
        if max_orders < 1:  # 0 would bind again at every step and hold no slot
            raise ValueError("max_orders must be at least 1")
        self._feed, self._max = feed, max_orders
        self._handles: OrderedDict[UUID, MachineStateHandle] = OrderedDict()

    def publish(
        self, order_id: UUID, account_id: UUID, payload: Mapping[str, Any], *, last: bool
    ) -> None:
        handle = self._handles.pop(order_id, None)
        if handle is None:
            handle = self._feed.bind(FeedBinding("order", str(order_id), frozenset({account_id})))
        if not last:
            self._handles[order_id] = handle
            if len(self._handles) > self._max:
                self._handles.popitem(last=False)
        handle.publish(payload, last=last)


# --- part 3: the runtime (#913 slice 3E) ---

#: The runtime's state, as `/readyz`'s `oms` check gives it (20 Sec.6.2).
OmsState = Literal["starting", "ok", "degraded"]
#: How often the startup's bounded wait looks at the clock guard and the key standing, in seconds.
STARTUP_POLL_S: Final = 0.25
#: The sweep's own statement cap on its reads, in milliseconds (CR-S3C1C-01). 21 Sec.13.1 row 49
#: scans the environment's orders for `held` rows, which no index serves, and a history the order
#: stores' 2 s cap cannot scan would fail every retry and leave the OMS never ready. 15 s, beside
#: the startup wait's 45 s ceiling, keeps the sweep inside a deploy's 60 s `/readyz` window, and
#: scans about 3 million rows at a conservative 200 000 rows a second.
SWEEP_STATEMENT_TIMEOUT_MS: Final = 15_000
#: What the client waits past that cap for one sweep read or write, in seconds, before it gives up
#: on a stalled connection (CR-S3E3-03): the attempt is retried and logged.
SWEEP_CALL_SLACK_S: Final = 2.0
#: How many orders the sweep hydrates at once (20 Sec.6.2 step 3).
HYDRATE_CONCURRENCY: Final = 8
#: The backoff of a sweep the store or the audit failed, in seconds: the first wait, doubled up to
#: the second.
SWEEP_RETRY_S: Final = (1.0, 30.0)
#: What a retry can outlast: the store's failures, the audit's, a timeout (an `OSError`).
_RETRIED: Final = (StorageError, OrderStoreError, AuditNotDurable, StoreUnavailable, OSError)
#: How many times the sweep meets any other error before it gives up, pages and ends `degraded`
#: (CR-S3E3-02). One order's history raising it again and again must not hold every other order
#: in silence for ever; and no order is skipped on an error no refusal names, which a defect
#: could raise for every one of them (C-2.21).
SWEEP_MAX_FAILURES: Final = 5
#: Step 4's KILL reason (24 Sec.8.4): an order recorded, never sent, and left with no owner.
STARTUP_UNSENT: Final = "startup_unsent"
#: What the sweep counts and skips, its order left as its last step left it (20 Sec.6.2 step 3,
#: SEC-S3C1C-01): a history the facade refuses, and an account the command port refuses
#: (`CommandAccounts`); where it was refused, it was paged.
_SKIPPED: Final = (OrderHistoryRefused, AccountScopeDenied, OrderEntryRefused)
#: The record of a stop the sweep voids, by its kind (21 Sec.3.3.11).
_SWEPT: Final[Mapping[str, str]] = MappingProxyType(
    {"stop_loss": "sl.modified", "take_profit": "tp.modified"}
)
_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_US: Final = timedelta(microseconds=1)


class FlagRead(Protocol):
    """A process-wide flag view (`flags_wiring.FlagView`): its value, and its first read."""

    def __call__(self) -> bool: ...

    async def first_read(self) -> None: ...


class KeyStandingRead(KeyStandingReactions, Protocol):
    """`accounts.key_standing.KeyStandings` as the runtime takes it: whether its first good
    tracking read has landed (20 Sec.6.2 step 1)."""

    @property
    def read_once(self) -> bool: ...


class OwnedPort(RoutedPort, Protocol):
    """The trading port the runtime owns: `stop()` closes its account clients."""

    async def aclose(self) -> None: ...


class Venue(Protocol):
    """The exchange adapter's service as the root composes it (C-2.2): the trading port of the
    process's environment, the waits of its lanes (ruling Q19) and its key-verdict table."""

    def trading_port(
        self, env: str, *, clock_offset_ms: Callable[[], int | None] | None = None
    ) -> OwnedPort: ...

    def lane_waits(self) -> Mapping[RateLane, float]: ...

    def key_refusal(self, error: ExchangeError) -> tuple[str, int] | None: ...


class Ingestion(Protocol):
    """`ingestion.service.IngestionService` as the order path reads it at `start()`: the clock
    guard, the ticker stream and the instrument catalogue, each None until composed, and the
    clock's measured offset, None while unmeasured."""

    @property
    def clock(self) -> ClockHealth | None: ...

    @property
    def tickers(self) -> DemandTickers | None: ...

    @property
    def instruments(self) -> InstrumentCatalogue | None: ...

    def clock_offset_ms(self) -> int | None: ...


class Bundle(Protocol):
    """The statechart persistence bundle's sink and chain-trip latch (E50-T63)."""

    @property
    def sink(self) -> MachineEventSink: ...

    @property
    def latch(self) -> ChainTripLatch: ...


class OwnedSink(MachineEventSink, Protocol):
    """The standalone `machine_events` WAL sink the runtime builds and owns with no bundle."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class OrderStores(OrderStore, OrderEventStore, Protocol):
    """The order rows and their events, in one adapter (`SqlAlchemyOrderStore`)."""


class GroupStores(TradeGroupStore, TradeGroupReads, Protocol):
    """The trade groups: the pipeline's system port and the principal-scoped read a replay goes
    through (`TradeGroupReader`), in one adapter (`SqlAlchemyTradeGroupStore`), so a store that
    lacks the scoped read fails at the type check, not at a replay (SEC-S3F1-01)."""


@dataclass(frozen=True, slots=True)
class OmsStores:
    """The runtime's stores, on one pool of its own that `release` disposes of, and the builder of
    the standalone sink over it. They take no principal, so a route reaches them only through the
    OMS's own surfaces, after its RBAC check (C-12.4): the pipeline, its anchors and `OrderRoute`'s
    reads, the existence read and a replay's two, the order by its account and the group through
    the principal-scoped `TradeGroupReader`. `sweep` is the startup sweep's reads, under their own
    statement cap (`SWEEP_STATEMENT_TIMEOUT_MS`)."""

    orders: OrderStores
    executions: ExecutionStore
    submissions: SubmissionStore
    anchors: IdempotencyAnchorStore
    stops: RecordedStopStore
    groups: GroupStores
    accounts: TradingAccountReads
    sweep: UnfinishedOrders
    sink: Callable[[], OwnedSink]
    release: Callable[[], Awaitable[None]]


def pg_stores(settings: Settings, metrics: Metrics) -> OmsStores:
    """The stores over the runtime's own pool (`oms` in `pg_stat_activity`). Lazy: building them
    connects nothing."""
    pool = SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "oms")
    events, ops = EventFramesAdapter(EventsAdapter(SqlAlchemyEventStore(pool))), PersistOps(metrics)
    counts = MachineEventSinkMetrics(flushed=ops.flushed, pending=ops.pending)
    return OmsStores(
        orders=SqlAlchemyOrderStore(pool),
        executions=SqlAlchemyExecutionStore(pool),
        submissions=SqlAlchemySubmissionStore(pool),
        anchors=SqlAlchemyIdempotencyAnchorStore(pool),
        stops=SqlAlchemyRecordedStopStore(pool),
        groups=SqlAlchemyTradeGroupStore(pool),
        accounts=SqlAlchemyTradingAccountReads(pool),
        sweep=SqlAlchemyOrderStore(pool, statement_timeout_ms=SWEEP_STATEMENT_TIMEOUT_MS),
        sink=lambda: build_machine_event_sink(settings, events, metrics=counts),
        release=pool.dispose,
    )


class StandaloneSink(Interim):
    """No persistence bundle serves B1's `machine_events` (20 Sec.6.2): the startup announces it
    as it does an interim port, `oms_interim_ports{port="machine_event_sink"}` at 1 with a
    WARNING."""

    port: ClassVar[RuntimePortName] = "machine_event_sink"
    replaced_by: ClassVar[str] = "#2701"
    serves: ClassVar[str] = (
        "the standalone machine_events WAL sink, with no HMAC'd journal; on a live process with "
        "CV_TRADING_LIVE_ENABLED on, none, and the OMS is never ready"
    )


class NoMachineEventSink(RuntimeError):
    """A live process with `CV_TRADING_LIVE_ENABLED` on and no persistence bundle: no sink, so the
    runtime is never ready and no live order is admitted (CV-C53)."""


class NoProfileCache(RuntimeError):
    """The process composed no shared effective-profile cache (`profiles_wiring`)."""


type _Closer = tuple[str, Callable[[], Awaitable[object]]]


class AccountExistence(Protocol):
    """`OrderRoute.accounts`: step 4's one read, never `trading_account`'s key ref (C-12.4)."""

    async def environment_of(self, account_id: AccountId) -> Environment: ...


class OrderRead(Protocol):
    """`OrderRoute.orders`: a replay's one read of its order, by its account, never a write."""

    async def get(self, account_id: UUID, order_id: UUID) -> OrderRow | None: ...


@dataclass(frozen=True, slots=True)
class OrderRoute:
    """What `POST /orders` reads of the composed OMS beside the pipeline and its anchors (24
    Sec.8.4), each the instance the pipeline was built with: the existence read (step 4), the arm
    records (step 5), the switches B1's `SEND` asks too (step 10), and a replay's rows (steps 8 and
    12): the order by its account, and the group through the principal-scoped reader (SR-E28-21),
    never the system facade (C-12.4). The account and order reads are typed as the one read each
    step uses."""

    accounts: AccountExistence
    arm_records: ArmRecords
    switches: TradingSwitchesBinding
    orders: OrderRead
    groups: TradeGroupReader


@dataclass(frozen=True, slots=True)
class _Parts:
    """What `start()` composed; `stop()` runs the `closers` after its drain, in their order."""

    submission: OrderSubmission
    anchors: AnchorService
    machines: OrderMachines
    closers: tuple[_Closer, ...]
    stops: RecordedStopRepository
    audit: OmsAudit
    sweep: UnfinishedOrders
    route: OrderRoute
    gate: ResolvingStopGate


async def _drained(tasks: set[asyncio.Task[Any]], timeout_s: float) -> set[asyncio.Task[Any]]:
    """The tasks still running once `timeout_s` has passed, or none."""
    if not tasks:
        return set()
    _, pending = await asyncio.wait(tasks, timeout=timeout_s)
    return set(pending)


def _page(pager: Pager, summary: str) -> None:
    try:
        pager.raise_alert("page", summary, machine_kind="order")
    except Exception as exc:  # the page is lost, never what it pages on
        _log().critical("oms_pager_failed", summary=summary, error=type(exc).__name__)


def _causes(error: BaseException) -> list[BaseException]:
    """What a failed `TaskGroup` holds, nested groups too; any other error is its own cause."""
    if isinstance(error, BaseExceptionGroup):
        return [cause for inner in error.exceptions for cause in _causes(inner)]
    return [error]


def _sweep_audit(audit: OmsAudit) -> Callable[[tuple[SweptStop, ...]], Awaitable[None]]:
    """`void_orphans`' write-ahead hook: each voided stop's record, `sl.modified` or `tp.modified`
    with `unplaced_entry_swept`, as `system:oms`, its ids only (21 Sec.3.3.11, C-2.9)."""

    async def write_ahead(swept: tuple[SweptStop, ...]) -> None:
        for stop in swept:
            detail = {"order_id": str(stop.order_id), "kind": stop.kind, "source": "entry_attach"}
            record = KeyedRecord(
                _SWEPT[stop.kind], str(stop.id), stop.exchange_account_id, "recorded_stop",
                stop.id, "success", "warning", SWEEP_REASON, None, detail,
            )  # fmt: skip
            await audit.write(record)

    return write_ahead


class CommandAccounts:
    """The command port's `TradingAccounts` (CR-S3C1B-02): the binding's, which pages an account
    it refuses before the refusal goes on. SR-E27-07 lets an account be deleted with orders left
    unfinished, which the startup hydrates (20 Sec.6.2); a create such an order resumes, or a stop
    it attaches, meets the refusal in the command port, and B1 lands it in a defined state with
    nothing sent: `unknown` for the create, for reconciliation, and `sl_missing` for the attach.
    Its keys are revoked at the delete (SR-E27-07), so no stop can be attached there anyway: the
    answer to C-2.6 is that recorded end with the page. One that reaches the sweep is skipped."""

    def __init__(self, accounts: TradingAccountsBinding, pager: Pager) -> None:
        self._accounts, self._pager = accounts, pager

    async def trading_account(self, account_id: AccountId) -> AccountRef:
        try:
            return await self._accounts.trading_account(account_id)
        except (AccountScopeDenied, OrderEntryRefused) as exc:
            refusal = type(exc).__name__
            _log().critical(
                "oms_order_account_refused", account_id=str(account_id), refusal=refusal
            )
            _page(self._pager, f"oms_order_account_refused: account {account_id}")
            raise


async def _closed(closers: Sequence[_Closer], deadline: float) -> None:
    """Each closer within an equal share of what is left until the loop's `deadline`, as
    `StorageService.stop` shares its own, so one that hangs (the sink's drain) cannot starve the
    next; isolated: one that fails or runs out is logged, and the next still runs; a cancellation
    propagates."""
    loop = asyncio.get_running_loop()
    for index, (name, close) in enumerate(closers):
        share = max(0.0, deadline - loop.time()) / (len(closers) - index)
        try:
            async with asyncio.timeout(share):
                await close()
        except Exception as exc:  # TimeoutError included
            _log().error("oms_stop_step_failed", step=name, error=type(exc).__name__)


class OmsRuntime:
    """The OMS of this process (20 Sec.6.2). `build_oms_runtime` builds it with no I/O, and
    `start()`, which the lifespan awaits after the account health runtime's, composes it on the
    serving loop: the order facade wires B1's process-wide ports and refuses a second one, so it
    lives from `start()` to `stop()`, never in `create_app()`. A task it tracks runs the startup
    sweep, which sets `ready` at its end only. What `start()` cannot compose fails the runtime
    closed: logged by step (`phase`) and paged, `degraded` and never ready, while market data
    stays up. `run` tracks the route's submits, which `stop()` drains."""

    def __init__(
        self,
        settings: Settings,
        *,
        venue: Venue,
        ingestion: Ingestion,
        read_only: ReadOnlyCheck,
        metrics: Metrics,
        audit: AuditWriterPort,
        gate: OrderEntryCheck,
        standings: KeyStandingRead,
        oms_enabled: FlagRead,
        live_enabled: FlagRead,
        profiles: Profiles | None,
        persistence: Bundle | None,
        feed: MachineStatePort,
        stores: Callable[[], OmsStores] | None = None,
        pager: Pager | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_machines: int = MAX_MACHINES,
        registry: Registry | None = None,
    ) -> None:
        self._settings, self._metrics = settings, metrics
        self._env: Environment = settings.environment.value
        self._venue, self._ingestion, self._read_only = venue, ingestion, read_only
        self._audit, self._gate, self._standings = audit, gate, standings
        self._oms_enabled, self._live_enabled = oms_enabled, live_enabled
        self._persistence, self._feed = persistence, feed
        #: The process's one effective-profile cache (finding 6), `profiles_wiring`'s, which its
        #: owner closes: the pipeline reads it, and E28-T02's writes invalidate the same one.
        self.profiles = profiles
        self._stores = stores or (lambda: pg_stores(settings, metrics))
        self._pager: Pager = LogPager() if pager is None else pager
        self._now, self._monotonic, self._sleep = now, monotonic, sleep
        self._max, self._registry = max_machines, registry
        self._ready = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._parts: _Parts | None = None
        self._startup: asyncio.Task[None] | None = None
        self._running: set[asyncio.Task[Any]] = set()
        self._failed = self._stopping = False
        #: The step `_compose` has reached, which a failed start logs and pages.
        self._phase = "settings"

    @property
    def started(self) -> bool:
        """Between `start()` and `stop()`: `/readyz` carries the `oms` check meanwhile only, as a
        stopped module reports none."""
        return self._loop is not None and not self._stopping

    @property
    def state(self) -> OmsState:
        """`ok` once ready; `degraded` once it will not get ready (it failed closed, its sweep
        refused, or its startup task ended without it); else `starting` (20 Sec.6.2)."""
        if self._ready.is_set():
            return "ok"
        startup = self._startup
        failed = self._failed or (startup is not None and startup.done())
        return "degraded" if failed else "starting"

    @property
    def submission(self) -> OrderSubmission:
        """The pipeline, once composed; `OmsNotReady` before."""
        return self._composed().submission

    @property
    def anchors(self) -> AnchorService:
        """The anchor service the pipeline was built with, which the route's lookup reads
        (SEC-S3D-02); `OmsNotReady` before it is composed."""
        return self._composed().anchors

    @property
    def route(self) -> OrderRoute:
        """The route's reads of the composed OMS (`OrderRoute`); `OmsNotReady` before."""
        return self._composed().route

    def _composed(self) -> _Parts:
        if self._parts is None:
            raise OmsNotReady
        return self._parts

    async def wait_ready(self) -> None:
        """Until the startup sweep has set `ready` (E29-T05's consumer waits on it)."""
        await self._ready.wait()

    def run[T](self, coro: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
        """The route's submit, as a task the runtime tracks and the route shields (24 Sec.8.4 step
        12): `stop()` drains it. Before anything is composed, or once the stop has begun,
        `OmsNotReady`. On the loop that started the runtime only, the facade's and the state
        feed's (CR-S3C2-01): another is a `RuntimeError`. Refused either way, the coroutine is
        closed."""
        if self._stopping or self._parts is None:
            coro.close()
            raise OmsNotReady
        if self._loop is not asyncio.get_running_loop():
            coro.close()
            raise RuntimeError("the OMS runs on the event loop that started it (CR-S3C2-01)")
        task = spawn(coro, name="oms-submit")
        self._running.add(task)
        task.add_done_callback(self._ended)
        return task

    def _ended(self, task: asyncio.Task[Any]) -> None:
        self._running.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            _log().error("oms_submit_task_failed", error=type(error).__name__)

    def _startup_ended(self, task: asyncio.Task[None]) -> None:
        """An error out of the startup task (a flag view or the guard raising) leaves the state
        `degraded` and never ready: logged, not left for asyncio's "never retrieved" at GC."""
        if not task.cancelled() and (error := task.exception()) is not None:
            _log().critical("oms_startup_failed", error=type(error).__name__)

    async def start(self) -> None:
        """Compose the OMS on this loop, then spawn the startup task (20 Sec.6.2). A second call
        does nothing until `stop()`. What cannot be composed fails the runtime closed."""
        if self._loop is not None and not self._stopping:
            return
        self._loop, self._stopping, self._failed = asyncio.get_running_loop(), False, False
        try:
            self._parts = await self._compose()
        except Exception as exc:  # fail closed (C-2.21): never ready, no order admitted
            self._failed, phase = True, self._phase
            _log().critical("oms_runtime_failed_closed", phase=phase, error=type(exc).__name__)
            _page(self._pager, f"oms_runtime_failed_closed: {phase}")
            return
        self._startup = spawn(self._started(), name="oms-startup")
        self._startup.add_done_callback(self._startup_ended)

    async def stop(self) -> None:
        """Clear `ready`; give the submits in flight at most `CV_OMS_DRAIN_S`; cancel what remains
        and the startup task; then close the stop gate (its complete reads and passes cancelled
        with the startup task, before the machines), the facade (it unwires B1's ports), the
        command port, the sink it owns, the trading port and its pool, each isolated, within its
        share of what is left, and all by `OMS_STOP_RESERVE_S` after the drain, inside the OMS
        module's 15 s grace (20 Sec.6.2). The shared profile cache is its owner's to close."""
        self._ready.clear()
        self._stopping = True
        pending = await _drained(set(self._running), self._settings.oms_drain_s)
        startup, self._startup = self._startup, None
        if startup is not None:
            pending.add(startup)
        for task in pending:
            task.cancel()
        deadline = asyncio.get_running_loop().time() + OMS_STOP_RESERVE_S
        parts, self._parts = self._parts, None
        cancelled: list[_Closer] = [("cancelled", lambda: asyncio.wait(pending))] if pending else []
        await _closed([*cancelled, *(() if parts is None else parts.closers)], deadline)
        self._failed = False

    async def _started(self) -> None:
        """The startup sweep (20 Sec.6.2): step 1's waits, then steps 2 to 4, run again after a
        backoff while the store or the audit fails them (any other error ends it `degraded` after
        `SWEEP_MAX_FAILURES`, paged), then step 5, `ready`, never early. A failure met while a
        stop runs ends it, cancelled, never retried."""
        await self._waited()
        parts, (delay, ceiling) = self._composed(), SWEEP_RETRY_S
        stuck = 0  # the failures no retry can outlast (CR-S3E3-02)
        while True:
            try:
                swept = await self._swept(parts)
            except Exception as exc:  # a store or audit failure: retried, never ready on it
                causes = _causes(exc)
                kinds = sorted({type(cause).__name__ for cause in causes})
                if self._stopping:  # the stop's cancel, that a `TaskGroup` gives back as errors
                    _log().warning("oms_startup_stopped", causes=kinds)
                    raise asyncio.CancelledError from exc
                if not all(isinstance(cause, _RETRIED) for cause in causes):
                    stuck += 1
                _log().warning(
                    "oms_startup_sweep_failed", error=type(exc).__name__, causes=kinds,
                    stuck=stuck, retry_s=delay,
                )  # fmt: skip
                if stuck >= SWEEP_MAX_FAILURES:
                    self._failed = True
                    _log().critical("oms_startup_sweep_gave_up", causes=kinds)
                    _page(self._pager, f"oms_startup_sweep_gave_up: {', '.join(kinds)}")
                    return
                await self._sleep(delay)
                delay = min(2 * delay, ceiling)
                continue
            if swept and not self._stopping:  # a stop that began meanwhile clears `ready` for good
                self._ready.set()
                _log().info("oms_ready")
            return

    async def _swept(self, parts: _Parts) -> bool:
        """Steps 2 to 4; False when step 3 refuses `ready`, past `MAX_MACHINES` orders (paged)."""
        env, machines, began = self._env, parts.machines, self._monotonic()
        accounts = await self._bounded(parts.sweep.environment_accounts(env))
        await self._bounded(parts.gate.start_floor())  # Q7: once, before this runtime writes a stop
        for account_id in accounts:  # step 2: this environment's accounts only (C-2.11)
            write_ahead = _sweep_audit(parts.audit)
            void = parts.stops.void_orphans(account_id, at=self._now(), write_ahead=write_ahead)
            await self._bounded(void)
            parts.gate.start_pass(account_id)  # the complete read, never awaited: no `ready` wait
        rows = await self._bounded(parts.sweep.list_unfinished(env, limit=self._max + 1))
        if len(rows) > self._max:  # more than the facade holds: never ready
            self._failed = True
            _log().critical("oms_startup_overflow", unfinished=len(rows), cap=self._max)
            _page(self._pager, f"oms_startup_overflow: more than {self._max} unfinished orders")
            return False
        skipped, abandoned = await self._hydrated(machines, rows), 0
        unsent = [r for r in rows if (machines.state(r.id) or ("",))[0] == "validated"]
        for row in unsent:  # step 4: a KILL from `validated` only, never `kill` (it may cancel)
            kill = machines.abandon(row.exchange_account_id, row.id, STARTUP_UNSENT)
            if await self._kept(kill, row):
                abandoned += 1
            else:
                skipped += 1
        _log().info(
            "oms_startup_swept", accounts=len(accounts), hydrated=len(rows) - skipped,
            skipped=skipped, abandoned=abandoned, elapsed_s=round(self._monotonic() - began, 3),
        )  # fmt: skip
        return True

    async def _bounded[T](self, call: Awaitable[T]) -> T:
        """A sweep read or write within its statement cap and `SWEEP_CALL_SLACK_S`, else
        `TimeoutError`: a stalled connection is retried and logged, not waited on in silence
        (CR-S3E3-03)."""
        async with asyncio.timeout(SWEEP_STATEMENT_TIMEOUT_MS / 1000 + SWEEP_CALL_SLACK_S):
            return await call

    async def _kept(self, step: Awaitable[object], row: OrderRow) -> bool:
        """The order's step, or False with the order skipped (`_SKIPPED`): it stays as its last
        step left it, and the sweep goes on to `ready`."""
        try:
            await step
        except _SKIPPED as exc:
            order_id, account_id = str(row.id), str(row.exchange_account_id)
            reason = type(exc).__name__
            _log().error(
                "oms_startup_order_skipped", order_id=order_id, account_id=account_id, reason=reason
            )
            return False
        return True

    async def _hydrated(self, machines: OrderMachines, rows: Sequence[OrderRow]) -> int:
        """Step 3: each order hydrated, `HYDRATE_CONCURRENCY` at once. Answers how many it
        skipped (`_kept`)."""
        slots, skipped = asyncio.Semaphore(HYDRATE_CONCURRENCY), 0

        async def one(row: OrderRow) -> None:
            nonlocal skipped
            async with slots:
                hydrate = machines.hydrate(row.exchange_account_id, row.id, environment=self._env)
                if not await self._kept(hydrate, row):
                    skipped += 1

        async with asyncio.TaskGroup() as group:
            for row in rows:
                spawn_child(group, one(row), name="oms-hydrate")
        return skipped

    async def _waited(self) -> None:
        """Step 1: at most `CV_OMS_STARTUP_WAIT_S` for the clock guard's first measurement and the
        key standing's first good read, then on (a resumed create meets the halt and the switches
        as they stand, 24 Sec.8.3 rule 6); a guard not composed never measures, so it is not
        waited for. Then the two flag views' first read, however long it takes."""
        deadline = self._monotonic() + self._settings.oms_startup_wait_s
        while not (self._measured() and self._standings.read_once):
            if self._monotonic() >= deadline:
                break
            await self._sleep(STARTUP_POLL_S)
        for flag in (self._oms_enabled, self._live_enabled):
            await flag.first_read()
        clock = self._ingestion.clock
        _log().info(
            "oms_startup_waited",
            clock="none" if clock is None else "measured" if self._measured() else "unmeasured",
            keys_read=self._standings.read_once,
        )

    def _measured(self) -> bool:
        clock = self._ingestion.clock
        return clock is None or math.isfinite(clock.offset_age_s())

    async def _compose(self) -> _Parts:
        """The C6 rig's composition, for the process's environment only (C-2.11): the switches,
        bindings and announcements, the sink and latch (20 Sec.6.2), the trading port and router,
        then over the pool the stores, the command port, the facade, the anchors and the pipeline.
        A failure once the port exists closes what was built before it goes on."""
        self._phase = "settings"
        settings, env, metrics = self._settings, self._env, self._metrics
        ingestion = self._ingestion
        bounds = OmsBounds.from_settings(settings)
        ports = SubmissionPorts.interim(now=self._now)
        announce_interim_ports(ports, metrics=metrics)
        switches = TradingSwitchesBinding(
            live_enabled=settings.trading_live_enabled,
            live_flag=self._live_enabled,
            kill_switch=InterimKillSwitch(),
            gate=self._gate,
        )
        switches.announce(metrics=metrics)
        self._phase = "sink"
        bundle = self._persistence
        sunk = StandaloneSink() if bundle is None else bundle.sink
        announce_interim_port("machine_event_sink", sunk, metrics=metrics)
        if bundle is None and env not in _NOT_LIVE and settings.trading_live_enabled:
            raise NoMachineEventSink
        self._phase = "profiles"
        if self.profiles is None:
            raise NoProfileCache
        self._phase = "port"
        port = self._venue.trading_port(env, clock_offset_ms=ingestion.clock_offset_ms)
        closers: list[_Closer] = [("trading_port", port.aclose)]
        try:
            router = TradingRouter({env: port}, lane_waits=self._venue.lane_waits())
            self._phase = "stores"
            stores = self._stores()
            closers.append(("pool", stores.release))
            self._phase = "commands"
            timer = WriteTimer(_histogram(metrics, "oms_db_write_seconds"))
            orders = OrderRepository(stores.orders, timer)
            stops = RecordedStopRepository(stores.stops, timer)
            audit, notices = OmsAudit(self._audit, environment=env), OrderNoticesRouter(self._pager)
            accounts = TradingAccountsBinding(stores.accounts, environment=env)
            halt = ClockHalt(
                ClockHealthBinding(ingestion.clock), monotonic=self._monotonic, metrics=metrics
            )
            command_accounts = CommandAccounts(accounts, self._pager)
            resolver = StopResolver(
                stops, CompleteRead(orders), StopVoidAudit(audit), now=self._now
            )
            gate = ResolvingStopGate(
                stops, resolver, accounts=command_accounts, port_for=router.port_for,
                bound_s=bounds.stop_request_s, now=self._now, monotonic=self._monotonic,
                metrics=metrics, pager=self._pager,
            )  # fmt: skip
            rejections = CredentialRejectionsBinding(
                self._standings, key_refusal=self._venue.key_refusal, pager=self._pager
            )
            commands = OmsCommandPort(
                router=router, accounts=command_accounts, orders=orders, stops=stops,
                handovers=NoHandoverStore(), credentials=rejections, clock_halt=halt,
                switches=switches, audit=audit, submit_audit=audit, gate=gate, notices=notices,
                now_us=self._now_us, submit_timeout_s=bounds.submit_timeout_s,
            )  # fmt: skip
            steps = OrderStepWriter(
                orders,
                ExecutionRepository(stores.executions, timer),
                clock=self._now,
                submissions=SubmissionRepository(stores.submissions, timer),
            )
            owned = stores.sink() if bundle is None else None
            sink: MachineEventSink = bundle.sink if bundle is not None else cast(OwnedSink, owned)
            feed = CompositePublisher(OrderStateFeed(self._feed, max_orders=self._max))
            self._phase = "facade"
            machines = OrderMachines(
                OrderMachinePorts(
                    steps, orders, commands, audit, feed, notices, sink,
                    OrderEventRepository(stores.orders, timer),
                ),
                metrics=metrics, pager=self._pager,
                latch=ChainTripLatch() if bundle is None else bundle.latch,
                now_us=self._now_us, registry=self._registry, max_machines=self._max,
            )  # fmt: skip
            closers[:0] = [
                ("stop_gate", gate.aclose),  # first: its reads end with the startup task's
                ("machines", machines.stop), ("commands", commands.aclose),
            ]  # fmt: skip
            self._phase = "pipeline"
            anchors = AnchorService(
                IdempotencyAnchorRepository(stores.anchors, timer),
                clock=self._now,
                timeout_s=bounds.store_timeout_s,
                stuck_after_s=bounds.stuck_after_s,
            )
            tickers = ingestion.tickers
            demand = (
                None if tickers is None else ReferenceDemand(tickers, monotonic=self._monotonic)
            )
            if demand is not None:
                closers.insert(3, ("ticker_demand", demand.close))  # after the commands
            deps = SubmissionDeps(
                accounts=accounts,
                instruments=InstrumentsBinding(ingestion.instruments),
                prices=ReferencePricesBinding(tickers, demand=demand),
                profiles=self.profiles,
                switches=switches,
                gate=gate,
                audit=audit,
                groups=TradeGroupRepository(stores.groups),
            )
            submission = OrderSubmission(
                ports, deps, machines=machines, commands=commands,
                allocator=OrderLinkIdAllocator(orders),
                validator=Validator(read_only_gate=self._read_only), router=router,
                anchors=anchors, clock_halt=halt, metrics=metrics, now=self._now,
                monotonic=self._monotonic, pager=self._pager,
                store_timeout_s=bounds.store_timeout_s, place_wait_s=bounds.place_wait_s,
                result_wait_s=bounds.result_wait_s,
            )  # fmt: skip
            # `pg_stores`' one group adapter serves the system port and the scoped read alike.
            reader = TradeGroupReader(stores.groups)
            route = OrderRoute(accounts, ports.arm_records, switches, orders, reader)
            if owned is not None:
                self._phase = "sink_start"
                await owned.start()
                closers.insert(3, ("sink", owned.stop))  # after the commands
        except BaseException:
            await _closed(closers, asyncio.get_running_loop().time() + OMS_STOP_RESERVE_S)
            raise
        return _Parts(
            submission, anchors, machines, tuple(closers), stops, audit, stores.sweep, route, gate
        )

    def _now_us(self) -> int:
        return (self._now() - _EPOCH) // _US


def _histogram(metrics: Metrics, name: str) -> BoundedMetric:
    spec = next(spec for spec in CATALOGUE if spec.name == name)
    return metrics.histogram(
        spec.name, spec.help, spec.labels, buckets=spec.buckets or (), max_series=spec.max_series
    )


def build_oms_runtime(
    ctx: AppContext,
    settings: Settings,
    *,
    metrics: Metrics,
    audit: AuditWriterPort,
    gate: OrderEntryCheck,
    standings: KeyStandingRead,
    oms_enabled: FlagRead,
    live_enabled: FlagRead,
    profiles: Profiles | None,
    persistence: Bundle | None,
    feed: MachineStatePort,
) -> OmsRuntime | None:
    """The process's OMS runtime, with no I/O; None on the fake backend, which composes no OMS, so
    `placeOrder` answers `501 not_implemented` there (20 Sec.6.2)."""
    if settings.storage_backend != "real":
        return None
    return OmsRuntime(
        settings, venue=ctx.exchange_bybit, ingestion=ctx.ingestion,
        read_only=ctx.oms_read_only_gate, metrics=metrics, audit=audit, gate=gate,
        standings=standings, oms_enabled=oms_enabled, live_enabled=live_enabled,
        profiles=profiles, persistence=persistence, feed=feed,
    )  # fmt: skip
