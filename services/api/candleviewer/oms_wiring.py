"""Composition-root wiring (not a module) of the OMS (E29-T04, #913 slice 3; 24 Sec.8.4, 20
Sec.6.2). Parts 1 and 2 are pure: nothing is started or mounted there.

Part 1: the OMS's time bounds from the settings (`OmsBounds`, 20 Sec.7.2), refused together so a
bad set fails the runtime's start, never a request, and the bindings of the ports `oms.ports`
declares, each failing closed. No venue module is imported (C-2.2): the adapter's key-verdict
table comes in as a callable, as `key_selfcheck_wiring` takes it.

Part 2: the reads and adapters that bind the OMS's ports to the modules that own them, as `oms`
imports no `audit`, `ws` or storage driver (C-3.1, C-3.3, ADR-0003).

Part 3: the OMS runtime (`build_oms_runtime`, `OmsRuntime`), which the lifespan starts and stops,
and which builds, starts and stops E29-T05's private-stream consumer (`oms_stream_wiring`, S8b).
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import hashlib
import math
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Collection, Coroutine, Iterable, Mapping, Sequence
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.override_comparator import AccountFigures
from candleviewer.accounts.profiles import AccountProfile
from candleviewer.accounts.trade_group_repository import TradeGroupReader, TradeGroupRepository
from candleviewer.accounts.trade_groups import (
    GroupReplay,
    GroupUpdate,
    LegDraft,
    LegUpdate,
    ScopedTradeGroup,
    TradeGroup,
    TradeGroupDraft,
    TradeGroupLeg,
    TradeGroupWithLegs,
    record_from_rows,
)
from candleviewer.accounts.verification import Refusal
from candleviewer.admin.wiring import (
    LaneSigningBinder,
    LoopSigningBorrower,
    MachineEventSinkMetrics,
    build_lane_audit_writer,
    build_machine_event_sink,
    keyed_record_id,
    unclaimed_machine_events,
)
from candleviewer.domain.events import Instrument
from candleviewer.domain.order_entry import OrderEntryCheck, OrderEntryRefusal
from candleviewer.domain.primitives import AccountId, Environment, GroupId, Px, Symbol
from candleviewer.exchange.base.errors import AuthError, ExchangeError, OmsErrorCode
from candleviewer.exchange.base.models import (
    AccountRef,
    RateLane,
    RiskLimitTier,
    TickerEvent,
)
from candleviewer.exchange.base.ports import PrivateStream
from candleviewer.observability import spawn, spawn_child
from candleviewer.observability.context import run_in_thread
from candleviewer.observability.metrics import BoundedMetric, Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.oms.cancel_all import (
    CancelAll,
    CancelAllOutcome,
    CancelAllRequest,
    ScopedAccounts,
)
from candleviewer.oms.cancel_all_coalescer import CancelAllCoalescer
from candleviewer.oms.cancel_all_fold import CancelAllSpacer
from candleviewer.oms.clock_halt import ClockHalt
from candleviewer.oms.commands import NEVER_SENT_ALERT, OmsCommandPort
from candleviewer.oms.day_figures import DayRiskFigures, Tiers
from candleviewer.oms.errors import (
    AccountScopeDenied,
    AuditNotDurable,
    OmsError,
    OmsNotReady,
    OrderEntryRefused,
    OrderHistoryRefused,
    StoreUnavailable,
    TradingDisabled,
)
from candleviewer.oms.exits import (
    AmendTerms,
    CancelReason,
    ExitCaller,
    ExitDeps,
    ExitOperation,
    ExitOutcome,
    ExitStep,
    InFlightGuard,
    OrderExits,
)
from candleviewer.oms.fanout.guard import LegGuard, S4SGuard
from candleviewer.oms.idempotency import AnchorService, Lookup, Replay
from candleviewer.oms.leverage import (
    LeverageDeps,
    LeverageOutcome,
    LeverageRequest,
    PositionLeverage,
)
from candleviewer.oms.order_link_allocator import OrderLinkIdAllocator
from candleviewer.oms.order_machine import (
    MAX_MACHINES,
    CompositePublisher,
    MachinePublisher,
    OrderAuditRecord,
    OrderMachinePorts,
    OrderMachines,
    OrderNotice,
)
from candleviewer.oms.order_steps import OrderStepWriter
from candleviewer.oms.ports import (
    ATR_FALLBACK,
    NO_TIER_REQUESTS,
    ArmRecords,
    ClockHealth,
    Instruments,
    Interim,
    KeyedRecord,
    MarketReading,
    NoDayFigures,
    NoHandoverStore,
    OrderFigures,
    Profiles,
    RequestRecord,
    RuleOrigin,
    RuntimePortName,
    SubmissionPorts,
    SubmitActor,
    TierRequests,
    TradingAccounts,
    TradingSwitches,
    announce_interim_port,
    announce_interim_ports,
)
from candleviewer.oms.ports import StopResolver as StopPort
from candleviewer.oms.position_writes import (
    CloseFill,
    PositionWrites,
    PositionWritesDeps,
    VenuePosition,
)
from candleviewer.oms.repository import (
    ExecutionRepository,
    IdempotencyAnchorRepository,
    OrderEventRepository,
    OrderRepository,
    PositionRepository,
    PositionSnapshotRepository,
    RecordedStopRepository,
    SubmissionRepository,
    WriteTimer,
)
from candleviewer.oms.routing import RoutedPort, TradingRouter
from candleviewer.oms.sizing import with_rates
from candleviewer.oms.stop_gate import ResolvingStopGate, StopVoidAudit
from candleviewer.oms.stop_resolution import CompleteRead, StopResolver, store_timeout_for
from candleviewer.oms.stream_consumer import StreamEvidence
from candleviewer.oms.submit import (
    RESULT_WAIT_S,
    STORE_TIMEOUT_S,
    OrderRequest,
    OrderSubmission,
    SubmissionDeps,
    SubmitContext,
    SubmitOutcome,
)
from candleviewer.oms.validator import ReadOnlyCheck, Validator
from candleviewer.oms.ws_topics import (
    OVERTAKES,
    AttachedTopics,
    Family,
    LaneClock,
    PublishedPositions,
    StepPublisher,
    TopicReads,
    View,
)
from candleviewer.oms_lane import HOP_TIMEOUT_S, LANE_JOIN_S, Lane, LaneStopped, OrderLane, Serving
from candleviewer.oms_stream_wiring import (
    ExchangeWallClock,
    HealthAccounts,
    StreamWiring,
    SystemBroadcast,
    TrackedAccounts,
    build_stream_consumer,
)
from candleviewer.oms_streams import LaneStreams
from candleviewer.settings import (
    OMS_CONSUMER_STOP_S,
    OMS_INFLIGHT_STUCK_MAX_S,
    OMS_STOP_RESERVE_S,
    Settings,
)
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
from candleviewer.storage.errors import StorageError, StorageTierUnavailable
from candleviewer.storage.repositories.accounts import AccountScope
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.executions import ExecutionStore
from candleviewer.storage.repositories.executions_sqlalchemy import SqlAlchemyExecutionStore
from candleviewer.storage.repositories.idempotency_anchors import (
    AnchorOperation,
    IdempotencyAnchorStore,
)
from candleviewer.storage.repositories.idempotency_anchors_sqlalchemy import (
    SqlAlchemyIdempotencyAnchorStore,
)
from candleviewer.storage.repositories.orders import (
    NewOrder,
    NewOrderEvent,
    OrderEventStore,
    OrderRow,
    OrderStore,
    OrderStoreError,
    ScopedOrder,
    UnfinishedOrders,
)
from candleviewer.storage.repositories.orders_sqlalchemy import SqlAlchemyOrderStore
from candleviewer.storage.repositories.positions import (
    PositionRow,
    PositionSnapshotStore,
    PositionStore,
)
from candleviewer.storage.repositories.positions_sqlalchemy import SqlAlchemyPositionStore
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
from candleviewer.storage.repositories.session_lock_sqlalchemy import SqlAlchemySessionLock
from candleviewer.storage.repositories.statechart_sqlalchemy import SqlAlchemyEventStore
from candleviewer.storage.repositories.submissions import (
    FirstPersist,
    FirstPersisted,
    SubmissionStore,
)
from candleviewer.storage.repositories.submissions_sqlalchemy import SqlAlchemySubmissionStore
from candleviewer.storage.repositories.trade_groups import (
    GroupWriteAhead,
    LegStatus,
    TradeGroupReads,
    TradeGroupRecord,
    TradeGroupStatus,
    TradeGroupStore,
)
from candleviewer.storage.repositories.trade_groups_sqlalchemy import SqlAlchemyTradeGroupStore
from candleviewer.storage.repositories.trading_accounts import (
    TradingAccountReads,
    TradingAccountRow,
)
from candleviewer.storage.repositories.trading_accounts_sqlalchemy import (
    SqlAlchemyTradingAccountReads,
)

if TYPE_CHECKING:
    import httpx

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


class HaltView(Protocol):
    """A process-wide halt read in place, never awaited: `audit.break_halt.AuditBreakHalt`
    (#2904), which `oms` never imports (C-3.3)."""

    @property
    def engaged(self) -> bool: ...


class HaltingKillSwitch:
    """The B18 port with the audit-chain break halt folded in (#2904, ruling BQ-241): while the
    halt is engaged every account is `TradingDisabled` without a `reason`, whatever `inner` says;
    otherwise `inner`'s verdict. Releasing `inner` never clears the halt, and acknowledging the
    break never releases `inner` (BQ-255). One instance serves every reader of the port (G-79):
    the OMS's switches, the trade-group readiness and the gateway's view of the switch."""

    def __init__(self, inner: KillSwitch, halt: HaltView) -> None:
        self.inner, self._halt = inner, halt

    def refusal(self, account_id: AccountId) -> TradingDisabled | None:
        if self._halt.engaged:
            return TradingDisabled()
        return self.inner.refusal(account_id)


class TradingSwitchesBinding:
    """`TradingSwitches` (C-2.21; 24 Sec.8.4): the route's step 10 and B1's `SEND` ask it. It reads
    memory only and never awaits, and the first refusal wins:

    1. the environment's lock held (#913 L2, SEC-S3L2-02): once the order lane's watchdog has
       found it lost (`fenced`), every order is `OmsNotReady`, whatever the rest say, so a submit
       any caller makes on the lane meets the fence, not only the route's;
    2. live trading enabled, for a live account: the `CV_TRADING_LIVE_ENABLED` setting and the
       `trading.live_enabled` flag's view, which is off while unread, both on (rulings Q4, Q6);
       either off is `TradingDisabled` without a `reason`;
    3. the B18 kill switch, `InterimKillSwitch` until E39-S03 (ruling Q5), with the audit-chain
       break halt folded in (`HaltingKillSwitch`, #2904);
    4. the app's one order-entry gate (24 Sec.8.4.1): its refusal is `OrderEntryRefused`, carrying
       the gate's `reason`."""

    def __init__(
        self,
        *,
        live_enabled: bool,
        live_flag: Callable[[], bool],
        kill_switch: KillSwitch,
        gate: OrderEntryCheck,
        fenced: Callable[[], bool],
    ) -> None:
        self._live_enabled, self._live_flag = live_enabled, live_flag
        self._kill_switch, self._gate, self._fenced = kill_switch, gate, fenced

    def refusal(
        self, account_id: AccountId, environment: Environment
    ) -> TradingDisabled | OmsNotReady | None:
        if self._fenced():  # the lock lost: no new order at all, nothing else asked
            return OmsNotReady()
        if environment not in _NOT_LIVE and not (self._live_enabled and self._live_flag()):
            return TradingDisabled()
        switched = self._kill_switch.refusal(account_id)
        if switched is not None:
            return switched
        gate = self._gate.refusal(account_id)
        return None if gate is None else OrderEntryRefused(gate)

    def announce(self, *, metrics: Metrics) -> None:
        """At startup (20 Sec.6.2): `oms_interim_ports{port="kill_switch"}` at 1 with one WARNING
        while the interim serves the B18 kill switch, else at 0; through the audit-chain break
        halt (#2904) to the switch it wraps."""
        switch = self._kill_switch
        inner = switch.inner if isinstance(switch, HaltingKillSwitch) else switch
        announce_interim_port("kill_switch", inner, metrics=metrics)


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

    def risk_limit_tiers(self, symbol: str) -> Sequence[RiskLimitTier] | None: ...


class InstrumentCatalogue(Protocol):
    """`ingestion.instruments_refresh.InstrumentsRefreshScheduler`'s read (24 Sec.1.3), and its
    tier requests (S4-S-d, `ServedTierRequests`): why it dropped one, or None."""

    def snapshot(self) -> CatalogueReading | None: ...

    def request_tiers(self, symbol: str) -> Literal["full", "stopped"] | None: ...


def _tiers(catalogue: InstrumentCatalogue | None) -> Tiers:
    """A symbol's risk-limit tiers from the catalogue's snapshot, read in place (no fetch on the
    lane); None with no catalogue, no snapshot, or tiers not fetched yet."""

    def tiers(symbol: Symbol) -> Sequence[RiskLimitTier] | None:
        snapshot = None if catalogue is None else catalogue.snapshot()
        return None if snapshot is None else snapshot.risk_limit_tiers(symbol)

    return tiers


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


class AskedPrices(Protocol):
    """What the reference prices tell of each ask: `ReferenceDemand`, or its bridge on the lane."""

    def asked(self, symbol: str, *, priced: bool) -> None: ...


class ReferencePricesBinding:
    """`ReferencePrices` over the ticker stream (24 Sec.9.3 step 2): the mid of the best bid and
    ask, else the last price; None with neither, with the symbol stale, or with no stream
    composed, which the pipeline answers 503 `exchange_unavailable`: a stale price never sizes,
    caps or checks a market order (the orchestrator's ruling, 2026-10-23). With `demand`, each
    ask is told to it, so a symbol no consumer holds is subscribed for the retry (CR-S3B2-03)."""

    def __init__(self, tickers: Tickers | None, *, demand: AskedPrices | None = None) -> None:
        self._tickers, self._demand = tickers, demand

    async def reference_price(self, symbol: Symbol) -> Px | None:
        return (await self.market(symbol)).reference

    async def market(self, symbol: Symbol) -> MarketReading:
        """The market read (24 Sec.8.4 step 3a): mid and last apart, each None when not a price
        above zero; the same staleness and the same demand as `reference_price`."""
        reading = self._reading(symbol)
        if self._demand is not None:
            self._demand.asked(symbol, priced=reading.reference is not None)
        return reading

    def _reading(self, symbol: Symbol) -> MarketReading:
        if self._tickers is None or self._tickers.is_stale(symbol):
            return _UNREAD
        ticker = self._tickers.latest(symbol)
        if ticker is None:
            return _UNREAD
        bid, ask, last = ticker.bid1_price, ticker.ask1_price, ticker.last_price
        mid = None
        if bid is not None and ask is not None and _priced(bid) and _priced(ask):
            mid = (bid + ask) / 2
        return MarketReading(mid=mid, last=last if last is not None and _priced(last) else None)


_UNREAD: Final = MarketReading(mid=None, last=None)


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
    not import `audit` (C-3.3), so `outcome`, `severity` and `env` go as their plain values. Each id
    takes what the writer's does, so the lane's own writer is also the one M2 records its lane
    signings through (`admin.wiring.LaneAuditWriter`, #913 L1d)."""

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: str | UUID | None = None,
        actor_ip: str | None = None,
        session_id: str | UUID | None = None,
        object_kind: str | None = None,
        object_id: str | None = None,
        outcome: Any = ...,
        severity: Any = ...,
        reason: str | None = None,
        after_state: dict[str, Any] | None = None,
        request_id: str | UUID | None = None,
        env: Any = None,
    ) -> None: ...

    async def emit_keyed(self, action: str, name: str, **fields: Any) -> None: ...


def _actor(
    actor: SubmitActor | None, user_id: UUID | None, origin: RuleOrigin | None = None
) -> dict[str, Any]:
    """The columns that say who acted: a rule's request's rule (`origin`, `rule:<rule_id>@v<n>`,
    with no user, session or address: 24 Sec.15.5, the E35 threat model's RE-S1), else the user
    and role of `actor`, else the OMS itself. A record that names a user but no actor has no role
    to record (C-2.9), so it is refused, never labelled without one: a site that drops the actor
    fails its write; so is a rule's record that names no owner."""
    if origin is not None:
        if actor is None:
            raise ValueError("a rule's record names the owner it acts for")
        return {"actor_label": origin.actor_label, "actor_user_id": None}
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


def _rule_state(actor: SubmitActor | None, origin: RuleOrigin | None) -> dict[str, Any]:
    """What a rule's request's record adds to `after_state` (24 Sec.15.5, RE-S1): the decision's
    source, the rule's id and version, its run and node, and both users' ids and roles, the owner
    the `SubmitActor` it acts for; ids and names only (C-12.6). Nothing for any other record."""
    if origin is None or actor is None:
        return {}
    armer = origin.armed_by
    return {
        "decision_source": "rule", "actor_type": "rule", "rule_id": str(origin.rule_id),
        "rule_version": str(origin.version), "run_id": str(origin.run_id),
        "node_id": origin.node_id, "owner_user_id": str(actor.user_id), "owner_role": actor.role,
        "armed_by_user_id": None if armer is None else str(armer),
        "armed_by_role": origin.armed_by_role,
    }  # fmt: skip


class OmsAudit:
    """The OMS's `SubmitAudit` and `OrderAudit` over the audit writer: a `KeyedRecord` through
    `emit_keyed`, under the id `record_id` names ahead (`keyed_record_id`), a `RequestRecord` and
    an `OrderAuditRecord` through `emit`. A record names its actor and role (`user:<role>`, with
    its session and address), or `system:oms` where none is given, or a rule's request's rule
    (`rule:<rule_id>@v<n>`, its fields and both users in `after_state`, 24 Sec.15.5), its object,
    its account and detail as `after_state` (ids, state names, codes and, on
    `trade_group.submit`, the sizing explanation with its figures (SR-E28-13), never a
    credential, C-12.6), its correlation id and the process's environment. `write` returns once
    the record is durable, else raises (C-2.9)."""

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
        fields["after_state"] |= _rule_state(record.actor, record.origin)
        if isinstance(record, KeyedRecord):
            fields |= _actor(record.actor, record.actor_user_id, record.origin)
            await self._writer.emit_keyed(record.action, record.name, **fields)
        else:
            fields |= _actor(record.actor, record.actor.user_id, record.origin)
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
    23 Sec.6.4 `machines.order:{id}.state`; the WS `orders` topics are E29-T13's, from the step
    writer's commits, `oms.ws_topics`): each order's slot bound through `RegistryFeed` once,
    scoped to its account (OM-I02), and dropped on its last step. A machine stopped before its
    last step keeps its slot, so at most `max_orders` (one or more) are held, the least recently
    published dropped first (C-2.18): a later step binds it again.

    It publishes into the WS registry directly, which is single-threaded and bound to the serving
    loop, so it runs there: the order facade runs on the order lane (CV-C13), and `ServedFeed`
    hops each publish over with `call_soon_threadsafe` (`machine_state_wiring`)."""

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


# --- the order lane's bridges (#913 slice 3 L1, 29 CV-C13) ---
#
# The OMS runs on the order lane (`oms_lane.OrderLane`); each class below carries one dependency
# bound to the serving loop across to it (`oms_lane.Serving`). The lane reads the rest in place,
# each safe from another thread: the setting and the flag views (one value each, replaced whole),
# the instrument catalogue (a frozen snapshot swapped by one assignment), the ticker stream's last
# ticker and phase (one dict read each, of a frozen event), the clock guard's health
# (`ServedClock`) and its offset's snapshot, the read-only gate and the governor's headroom (each
# under its own lock, #4370), the persistence bundle's chain-trip latch (a dict the serving loop's
# restores write an item at a time), its own refusals of rejected credentials, which the route's
# gate reads on the serving loop too (`ServedStandings.refused`, one dict read), the order-entry
# gate since L4 (`ServedGate`: the maintenance boolean, the key standing's one snapshot and the
# self-check's results a key at a time, the account health's dict read and evidence, 20 Sec.6.2)
# and the serving loop's tick a new submit meets first (`ServingTick`, one float), the metrics and
# the pager. Its audit writer and `machine_events` sink are its own, built on its loop (#913 L2,
# `OmsStores`), and its venue calls never cross: the lane's own port signs and sends them
# (#913 L1d). Its private streams stay on the serving loop's registry, whose items cross a batch
# at a time (`oms_streams.LaneStreams`, #913 L1d-2b, ruling Q2 (b)).


class ServedProfiles:
    """`Profiles` over the process's profile cache, which is for one loop
    (`accounts/profile_cache.py`): each read is awaited on the serving loop."""

    def __init__(self, profiles: Profiles, serving: Serving) -> None:
        self._profiles, self._serving = profiles, serving

    async def get_effective_profile(
        self, account_id: UUID, profile_id: UUID | None = None
    ) -> AccountProfile:
        read = self._profiles.get_effective_profile(account_id, profile_id)
        return await self._serving.call(read)


class ServedGate:
    """The order-entry gate as the lane asks it (C-2.21), read in place with no hop to the serving
    loop (#913 L4): each of its reads takes one source at one instant, safe from another thread (20
    Sec.6.2), so a write is in force for every read that begins after it returns.

    The second read is what makes that hold for the gate as a whole, never an optimisation to undo
    (the orchestrator's ruling of 2026-10-25 18:27Z (1)): one read that overlaps writes to two of
    the gate's sources, the key standing and the account health say, may take the one before its
    refusing write and the other after its own admitting write, an admitting pair that no single
    instant held. A refusing write that lands inside the first read is in force for the second,
    which begins after it, so the lane admits only when two reads in a row admit.

    An account whose rejected credential the lane notified (`ServedStandings`) is refused first and
    at once, as the key standing holds it only once the notice lands (CR-S3L1B-04). A new submit
    and a risk-increasing amend meet the serving loop's tick before the gate (`FencedSwitches`); no
    other exit reads it."""

    def __init__(self, gate: OrderEntryCheck, standings: ServedStandings) -> None:
        self._gate, self._standings = gate, standings

    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        if self._standings.refused(account_id):
            return NO_ACTIVE_KEY
        first = self._gate.refusal(account_id)
        return first if first is not None else self._gate.refusal(account_id)


#: The serving loop's tick, in seconds (#913 L4; the orchestrator's rulings of 2026-10-25 19:19Z on
#: CR-S3L4-04 and 21:56Z): how often the OMS stamps the serving loop's time there, and how old the
#: last stamp may be before the lane admits no new submit or risk-increasing amend, twice that: the
#: 1 s within which a stalled serving loop refused a gate read before L4 read the gate in place.
SERVING_TICK_S: Final = 0.5
SERVING_STALE_S: Final = 2 * SERVING_TICK_S


class ServingTick:
    """The serving loop's tick, which the order lane reads in place (#913 L4; the ruling of
    2026-10-25 19:19Z). Every write that could refuse at the gate runs on the serving loop (20
    Sec.6.2), so while it stalls the gate's sources are frozen. On the serving loop, `run()` beats
    every `SERVING_TICK_S`; from any thread, `overdue()` gives the last beat's age once it is over
    `SERVING_STALE_S`, else None. Sticky: however long the lane waits, only a beat of the serving
    loop ends it. The beat's time is a single assignment, read in place."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        wait: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._clock, self._wait = clock, wait
        self._beat_at = clock()  # built as the runtime starts: fresh until its first beat

    def beat(self) -> None:
        """The serving loop's time, on the serving loop only."""
        self._beat_at = self._clock()

    async def run(self) -> None:
        """Beat every `SERVING_TICK_S` until cancelled (the runtime's stop), on the serving loop."""
        while True:
            self.beat()
            await self._wait(SERVING_TICK_S)

    def overdue(self) -> float | None:
        """The last beat's age in seconds once it is over `SERVING_STALE_S`, else None: one read
        of the clock, so a caller logs the age it judged (SEC-S3L4-04)."""
        age = self._clock() - self._beat_at
        return age if age > SERVING_STALE_S else None


class FencedSwitches:
    """`TradingSwitches` for new exposure (#913 L4; the rulings of 2026-10-25 19:19Z and 21:56Z):
    a new submit's, the route's step 10, the pipeline's switches and a re-send, and the exit
    service's, which a risk-increasing amend alone reads, as it meets the gate as a submit does
    (SR-E28-27, C-2.21). While the serving loop's tick is overdue, `OmsNotReady`, logged with the
    age it was judged at, and no switch is read; else the switches' answer, whose first refusal is
    the environment lock's fence (#913 L2): the two compose, either refusing on its own. A
    protective amend, a cancel, cancel-all, a stop attach or a KILL reads none (C-2.6); the gate's
    age bounds stay the outer ones (20 Sec.6.2)."""

    def __init__(self, switches: TradingSwitches, tick: ServingTick) -> None:
        self._switches, self._tick = switches, tick

    def refusal(
        self, account_id: AccountId, environment: Environment
    ) -> TradingDisabled | OmsNotReady | None:
        if (age := self._tick.overdue()) is not None:
            _log().error(
                "oms_submit_fenced",
                account_id=str(account_id),
                age_s=round(age, 3),
                stale_s=SERVING_STALE_S,
            )
            raise OmsNotReady
        return self._switches.refusal(account_id, environment)


class ServedStandings:
    """The key standing, which only the serving loop writes (`accounts/key_standing.py`), told of a
    rejected credential from the lane: notified to the serving loop, never awaited, and refused on
    the lane at once (`refused`) until the notice has landed there (C-2.21). A notice lost or
    failed there leaves the account refused in this process."""

    def __init__(self, standings: KeyStandingReactions, serving: Serving) -> None:
        self._standings, self._serving = standings, serving
        #: Each account whose last rejection's notice has not landed: assigned on the lane, dropped
        #: on the serving loop once it lands, read on either (20 Sec.6.2: one dict read, GIL-atomic
        #: against either write); `_guard` orders the writes, so a later rejection stays.
        self._sent: dict[UUID, object] = {}
        self._guard = threading.Lock()

    def credential_rejected(self, account_id: UUID, refusal: Refusal) -> None:
        sent = object()
        with self._guard:
            self._sent[account_id] = sent
        self._serving.notify(self._land, account_id, refusal, sent)

    def _land(self, account_id: UUID, refusal: Refusal, sent: object) -> None:
        self._standings.credential_rejected(account_id, refusal)
        # the key standing holds it first, so a lane read that misses it here finds it there (L4)
        with self._guard:
            if self._sent.get(account_id) is sent:
                del self._sent[account_id]

    def refused(self, account_id: UUID) -> bool:
        return account_id in self._sent


class ServedFeed:
    """`OrderStateFeed` from the lane: the WS registry is single-threaded on the serving loop (23
    Sec.6.4), so each publish is notified there, never awaited."""

    def __init__(self, feed: MachinePublisher, serving: Serving) -> None:
        self._feed, self._serving = feed, serving

    def publish(
        self, order_id: UUID, account_id: UUID, payload: Mapping[str, Any], *, last: bool
    ) -> None:
        self._serving.notify(self._feed.publish, order_id, account_id, payload, last=last)


class ServedDemand:
    """The reference prices' ticker demand (`ReferenceDemand`), the serving loop's as the stream it
    holds is: each ask is notified there, never awaited."""

    def __init__(self, demand: AskedPrices, serving: Serving) -> None:
        self._demand, self._serving = demand, serving

    def asked(self, symbol: str, *, priced: bool) -> None:
        self._serving.notify(self._demand.asked, symbol, priced=priced)


class ServedClock:
    """The clock guard as `ClockHalt` reads it from the lane: its health reads are attribute reads
    of values the guard replaces whole, safe from another thread; a resync measures on the serving
    loop, awaited there."""

    def __init__(self, guard: ClockHealth, serving: Serving) -> None:
        self._guard, self._serving = guard, serving

    def assert_healthy(self) -> None:
        self._guard.assert_healthy()

    def offset_age_s(self) -> float:
        return self._guard.offset_age_s()

    async def resync_after_signature_failure(self, *, reason: str) -> int:
        return await self._serving.call(self._guard.resync_after_signature_failure(reason=reason))


#: How many tier requests may wait to land on the serving loop (#913 S4-S-d), one per symbol.
TIER_REQUESTS_PENDING_MAX: Final = 100
#: The tier requests dropped, by `reason`: `full` (the bridge or the catalogue), or `stopped` (the
#: catalogue had stopped).
TIER_REQUESTS_DROPPED: Final = "oms_tier_requests_dropped_total"


class ServedTierRequests:
    """`TierRequests` from the lane (#913 S4-S-d, 24 Sec.9.3.6): each symbol is notified to the
    catalogue on the serving loop (`Serving.notify`), never awaited, so the submit path makes no
    network call of its own (CV-C13). At most `TIER_REQUESTS_PENDING_MAX` symbols wait to land
    there, a symbol already waiting adding nothing. A request past that is counted `full`, and
    one the catalogue drops is counted by its reason (`full`, `stopped`); none raises into its
    caller. A request the closed serving loop cannot take is not this counter's: `Serving`
    counts it (`oms_lane_notices_failed_total{lost}`); that symbol stays waiting, so a repeat
    request for it adds nothing until the runtime's stop ends the wait (`close`)."""

    def __init__(self, catalogue: InstrumentCatalogue, serving: Serving, metrics: Metrics) -> None:
        self._catalogue, self._serving = catalogue, serving
        spec = next(spec for spec in CATALOGUE if spec.name == TIER_REQUESTS_DROPPED)
        dropped = metrics.counter(spec.name, spec.help, spec.labels, max_series=spec.max_series)
        self._dropped = {"full": dropped.labels("full"), "stopped": dropped.labels("stopped")}
        #: The symbols handed over and not yet landed: added on the lane, dropped on the serving
        #: loop, each under `_guard`.
        self._pending: set[str] = set()
        self._guard = threading.Lock()

    def request_tiers(self, symbol: Symbol) -> None:
        try:
            with self._guard:
                if symbol in self._pending:
                    return
                full = len(self._pending) >= TIER_REQUESTS_PENDING_MAX
                if not full:
                    self._pending.add(symbol)
            if full:
                self._dropped["full"].inc()
                return
            self._serving.notify(self._land, symbol)
        except Exception as exc:  # a request's failure is never its caller's
            _log().error("oms_tier_request_failed", error=type(exc).__name__)

    async def close(self) -> None:
        """The runtime's stop: the symbols still waiting are dropped, none will land."""
        with self._guard:
            self._pending.clear()

    def _land(self, symbol: str) -> None:
        with self._guard:
            self._pending.discard(symbol)
        try:
            dropped = self._catalogue.request_tiers(symbol)
            if dropped is not None:
                self._dropped[dropped].inc()
        except Exception as exc:  # logged here: no caller waits for it
            _log().error("oms_tier_request_failed", error=type(exc).__name__)


class GroupTopic(Protocol):
    """The `trade_groups` topic (`accounts.trade_group_topic`) as the lane's writes reach it, each
    call on the serving loop (E28-T05)."""

    def seed(self, groups: Iterable[TradeGroupWithLegs]) -> None: ...
    def created(self, record: TradeGroupWithLegs) -> None: ...
    def leg_changed(self, leg: TradeGroupLeg) -> None: ...
    def group_changed(self, group: TradeGroup) -> None: ...


class ObservedGroups(TradeGroupRepository):
    """The pipeline's trade-group facade, observed (E28-T05 #909 S4b): each write it commits goes,
    as stored, to the `trade_groups` topic on the serving loop by a `Serving.notify` notice, never
    awaited (C-2.18, C-2.20), bounded as every notice is and counted there when lost or failed
    (`oms_lane_notices_failed_total`). A replay, a key reuse or a write that raises hands over
    nothing. A group leaving `draft` (`expected_status="draft"`) is read and handed over whole,
    as the topic holds no draft; a writer that leaves `draft` otherwise is E34's to hand over."""

    def __init__(self, store: TradeGroupStore, topic: GroupTopic, serving: Serving) -> None:
        super().__init__(store)
        self._topic, self._serving = topic, serving

    async def create(
        self, group: TradeGroupDraft, legs: Sequence[LegDraft], *, write_ahead: GroupWriteAhead
    ) -> TradeGroupWithLegs | GroupReplay:
        stored = await super().create(group, legs, write_ahead=write_ahead)
        if not isinstance(stored, GroupReplay):
            self._serving.notify(self._topic.created, stored)
        return stored

    async def update_leg(
        self,
        group_id: GroupId,
        leg_id: UUID,
        update: LegUpdate,
        *,
        expected_status: LegStatus | None = None,
    ) -> TradeGroupLeg:
        leg = await super().update_leg(group_id, leg_id, update, expected_status=expected_status)
        self._serving.notify(self._topic.leg_changed, leg)
        return leg

    async def update_group(
        self,
        group_id: GroupId,
        update: GroupUpdate,
        *,
        expected_status: TradeGroupStatus | None = None,
    ) -> TradeGroup:
        group = await super().update_group(group_id, update, expected_status=expected_status)
        if expected_status == "draft" and group.status != "draft":
            await self._left_draft(group_id)
        else:
            self._serving.notify(self._topic.group_changed, group)
        return group

    async def _left_draft(self, group_id: GroupId) -> None:
        """One read on the lane; one that fails hands over nothing, logged by its error's type."""
        try:
            whole = await self.get(group_id)
        except Exception as exc:
            _log().error(
                "oms_trade_group_handover_failed",
                trade_group_id=str(group_id),
                error=type(exc).__name__,
            )
            return
        self._serving.notify(self._topic.created, whole)

    def persisted(self, record: TradeGroupRecord) -> None:
        """A first persist's group, as its rows: adapted on the serving loop (`_created`)."""
        self._serving.notify(_created, self._topic, record)

    async def seed(self, environment: str) -> int:
        """The topic's seed: this environment's active groups (C-2.11), read on the lane; answers
        how many it handed over."""
        held = await self.open_groups()
        own = tuple(record for record in held if record.group.environment == environment)
        self._serving.notify(self._topic.seed, own)
        return len(own)


def _created(topic: GroupTopic, record: TradeGroupRecord) -> None:
    """On the serving loop; a row the adapter refuses is a notice `Serving` counts as failed."""
    topic.created(record_from_rows(record))


class ObservedSubmissions(SubmissionRepository):
    """The first persist (24 Sec.8.4 step 5), observed: `placeOrder` stores an entry's group with
    its order, not through `TradeGroupRepository.create`, so it is handed over here."""

    def __init__(self, store: SubmissionStore, timer: WriteTimer, groups: ObservedGroups) -> None:
        super().__init__(store, timer)
        self._groups = groups

    async def create_first(
        self, first: FirstPersist, order: NewOrder, event: NewOrderEvent
    ) -> FirstPersisted:
        persisted = await super().create_first(first, order, event)
        if persisted.group is not None:
            self._groups.persisted(persisted.group)
        return persisted


# --- part 3: the runtime (#913 slice 3E) ---

#: The runtime's state, as `/readyz`'s `oms` check gives it (20 Sec.6.2).
OmsState = Literal["starting", "ok", "degraded"]
#: How often the startup's bounded wait looks at the clock guard and the key standing, in seconds.
STARTUP_POLL_S: Final = 0.25
#: The sweep's own statement cap on its reads, in milliseconds (CR-S3C1C-01). 21 Sec.13.1 row 49
#: scans the environment's orders for `held` rows, which no index serves, and a history the order
#: stores' cap (`CV_OMS_STATEMENT_TIMEOUT_MS`, 2 s by default, 5 s at most) cannot scan would fail
#: every retry and leave the OMS never ready. 15 s, beside the startup wait's 45 s ceiling, keeps
#: the sweep inside a deploy's 60 s `/readyz` window, and scans about 3 million rows at a
#: conservative 200 000 rows a second.
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
#: E28-T05: the `trade_groups` seed's reads before `ready`, a failed one tried again after the
#: sweep's first backoff, all of them within one sweep call's bound (`_seeded`).
SEED_ATTEMPTS: Final = 3
#: The startups whose seed failed every read (`_seeded`).
SEED_FAILURES: Final = "cv_tradegroup_ws_seed_failures_total"
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
    process's environment for the order lane's loop, signed by that loop's M2 borrower (#913 L1d)
    and opening its private streams through the lane's bridge; the opener of those streams, on the
    serving loop (#913 L1d-2b); the waits of its lanes (ruling Q19); and its key-verdict table."""

    def lane_trading_port(
        self,
        env: str,
        *,
        credentials: LoopSigningBorrower,
        transport: httpx.AsyncBaseTransport | None = None,
        clock_offset_ms: Callable[[], int | None] | None = None,
        private_streams: LaneStreams | None = None,
    ) -> OwnedPort: ...

    async def open_private_stream(
        self, account: AccountRef, *, clock_offset_ms: Callable[[], int | None] | None = None
    ) -> PrivateStream: ...

    def lane_waits(self) -> Mapping[RateLane, float]: ...

    def key_refusal(self, error: ExchangeError) -> tuple[str, int] | None: ...


class Ingestion(Protocol):
    """`ingestion.service.IngestionService` as the order path reads it at `start()`: the clock
    guard, the ticker stream and the instrument catalogue, each None until composed, and the
    snapshot of the clock's measured offset, None while unmeasured, which the lane reads with no
    host-step check (CR-S3L1B-09)."""

    @property
    def clock(self) -> ClockHealth | None: ...

    @property
    def tickers(self) -> DemandTickers | None: ...

    @property
    def instruments(self) -> InstrumentCatalogue | None: ...

    def clock_offset_snapshot_ms(self) -> int | None: ...


class Bundle(Protocol):
    """The statechart persistence bundle's sink and chain-trip latch (E50-T63)."""

    @property
    def sink(self) -> MachineEventSink: ...

    @property
    def latch(self) -> ChainTripLatch: ...


class OwnedSink(MachineEventSink, Protocol):
    """The order lane's own `machine_events` WAL sink, which the runtime builds and owns (#913 L2,
    ruling Q13)."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class EnvironmentLock(Protocol):
    """SEC-S3N-01 (#913 L2): the environment's lock, which one OMS process per environment and
    database holds for its facade's life: `acquire()` answers whether it is now held, never
    waiting for another holder; `confirm()` whether its session still holds it, the watchdog's
    probe (`LaneHeartbeat`); `release()` gives it up."""

    async def acquire(self) -> bool: ...

    async def confirm(self) -> bool: ...

    async def release(self) -> None: ...


class EnvironmentLocked(RuntimeError):
    """SEC-S3N-01: another process holds this environment's lock (a deploy overlapping on another
    host): this runtime refuses to start, failing closed, and is never ready."""


class EnvironmentLockUnanswered(RuntimeError):
    """CR-S3L2-01/02: the environment's lock could not be asked (Postgres unreachable, or no answer
    within `ENVIRONMENT_LOCK_TIMEOUT_S`), which is no other holder: the start asks again, the whole
    composition with it, after the sweep's backoff (`SWEEP_RETRY_S`), never ready meanwhile."""


#: The fail-closed alarm the lane's audit writer fires (ruling 4): the cause, its error's class.
type AuditAlarm = Callable[[str], Awaitable[None]]


class OwnedAudit(AuditWriterPort, Protocol):
    """The order lane's own audit writer, which the runtime builds on the lane and owns (#913 L2,
    ruling Q12): started there, and stopped there within `grace_s`."""

    async def start(self) -> None: ...

    async def stop(self, grace_s: float = ...) -> None: ...


class OrderStores(OrderStore, OrderEventStore, Protocol):
    """The order rows and their events, in one adapter (`SqlAlchemyOrderStore`)."""


class PositionStores(PositionStore, PositionSnapshotStore, Protocol):
    """The positions and their snapshots, in one adapter (`SqlAlchemyPositionStore`), over the
    clock it is built with (E29-T05 S8b)."""


class GroupStores(TradeGroupStore, TradeGroupReads, Protocol):
    """The trade groups: the pipeline's system port and the principal-scoped read a replay goes
    through (`TradeGroupReader`), in one adapter (`SqlAlchemyTradeGroupStore`), so a store that
    lacks the scoped read fails at the type check, not at a replay (SEC-S3F1-01)."""


@dataclass(frozen=True, slots=True)
class OmsStores:
    """The runtime's stores, on one pool of its own that `release` disposes of, and the builders
    of the order lane's own audit writer and `machine_events` sink over it (#913 L2), the writer's
    with the alarm it is given, the sink's at the WAL path it is given, and the probe of the file a
    bundle's sink holds (`unclaimed`, SEC-S3L2-03). They take no principal, so
    a route reaches them only through the OMS's own surfaces, after its RBAC check (C-12.4): the
    pipeline, its anchors and `OrderRoute`'s reads, the existence read and a replay's two, the
    order by its account and the group through the principal-scoped `TradeGroupReader`. `sweep` is
    the startup sweep's reads, under their own statement cap (`SWEEP_STATEMENT_TIMEOUT_MS`).
    `positions` builds the private-stream consumer's position store over the clock it is given,
    the exchange-synced one, which its projection reads too (E29-T05 S8b, CG14)."""

    orders: OrderStores
    executions: ExecutionStore
    submissions: SubmissionStore
    anchors: IdempotencyAnchorStore
    stops: RecordedStopStore
    groups: GroupStores
    accounts: TradingAccountReads
    sweep: UnfinishedOrders
    positions: Callable[[Callable[[], datetime]], PositionStores]
    audit: Callable[[AuditAlarm], OwnedAudit]
    sink: Callable[[str], OwnedSink]
    #: The bytes of frames `CV_MACHINE_EVENT_WAL_PATH` holds that Postgres has not taken, read
    #: under its lock; blocking, so run off the loop (SEC-S3L2-03).
    unclaimed: Callable[[], int]
    lock: EnvironmentLock
    release: Callable[[], Coroutine[Any, Any, None]]


#: The name prefix of the order lane's own WAL files, each beside the serving loop's (#913 L2, D6).
LANE_WAL_PREFIX: Final = "oms_lane."
#: How long the stop gives the lane's audit writer to empty its WAL into Postgres, inside its
#: share of `OMS_STOP_RESERVE_S`; what it has not inserted stays in the WAL for the next start.
LANE_AUDIT_STOP_S: Final = 1.0
#: The window of the lane writer's alarm page (ruling 4, CR-S3L2-08), in seconds: the first alarm of
#: each cause in a window pages, so a full WAL pages once a window, never once a refused record.
LANE_AUDIT_PAGE_S: Final = 5.0
#: SEC-S3N-01: the namespace of the environment's lock key (`environment_lock_key`), and the
#: bound on asking for the lock at the start, for the pool's connection and for the statement.
ENVIRONMENT_LOCK_NAMESPACE: Final = b"cv.oms.environment:"
ENVIRONMENT_LOCK_TIMEOUT_S: Final = 5.0
#: The order lane's heartbeat (the orchestrator's ruling 2 of 2026-10-25 12:22Z; CR-S3L1A-02), in
#: seconds: how often the lane ticks, the environment lock's watchdog asking on the same tick
#: (ruling 3), and how long without a tick reads it wedged: past a tick and the watchdog's bound
#: (`ENVIRONMENT_LOCK_TIMEOUT_S`), and within a lane read's own (`HOP_TIMEOUT_S`).
LANE_TICK_S: Final = 1.0
LANE_STALE_S: Final = 10.0
#: SEC-S3L2-01: how long a process that has just taken the environment's lock waits before its
#: startup sweep, and so before its first admit, in seconds: a tick and the watchdog's bound, by
#: which a previous holder whose session ended has found its lock lost and fenced itself.
ENVIRONMENT_FENCE_GRACE_S: Final = LANE_TICK_S + ENVIRONMENT_LOCK_TIMEOUT_S


def environment_lock_key(environment: str) -> int:
    """SEC-S3N-01: the key of `environment`'s lock, a signed 64-bit `bigint`, the first 8 bytes of
    BLAKE2b over `ENVIRONMENT_LOCK_NAMESPACE` and the environment, as the reaper's lock derives
    its own (`storage.retention.locks.advisory_key`)."""
    digest = hashlib.blake2b(ENVIRONMENT_LOCK_NAMESPACE + environment.encode(), digest_size=8)
    return int.from_bytes(digest.digest(), "big", signed=True)


class LaneHeartbeat:
    """The order lane's heartbeat, and the environment lock's watchdog on the same tick (#913 L2;
    the orchestrator's rulings 2 and 3 of 2026-10-25 12:22Z; CR-S3L1A-02, CR-S3L2-03).

    On the lane, `run()` ticks every `LANE_TICK_S` and, on the same tick, asks the environment's
    lock whether its session still holds it (`EnvironmentLock.confirm`, within
    `ENVIRONMENT_LOCK_TIMEOUT_S`). A lock not held, or a session that cannot answer, is lost:
    logged CRITICAL (`oms_environment_lock_lost`) and paged once, and `fenced` for good, so the
    runtime refuses every new submit while its exits, stops and KILLs run on (never a silent run
    without the lock, never a blocked exit: C-2.6, C-2.21); a restart is the way back.

    From any thread (`/readyz` reads on a worker thread), `stale()` answers whether the lane has
    not ticked within `LANE_STALE_S`: a wedged lane, alive but stuck. The first stale read of each
    stall pages (`oms_lane_stalled`). The tick's time and the fence are single assignments, read
    in place (20 Sec.6.2); the stall's flag is under a lock."""

    def __init__(
        self,
        lock: EnvironmentLock,
        pager: Pager,
        *,
        clock: Callable[[], float] = time.monotonic,
        wait: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._lock, self._pager, self._clock, self._wait = lock, pager, clock, wait
        self._ticked_at = clock()  # built as its lane starts: fresh until its first tick
        self._fenced = False
        self._stall = threading.Lock()
        self._stalled = False

    @property
    def fenced(self) -> bool:
        """Whether the environment's lock was lost: no new submit is admitted (ruling 3)."""
        return self._fenced

    async def run(self) -> None:
        """Tick, and watch the lock while it is held, until cancelled (the stop's closer)."""
        while True:
            self._ticked_at = self._clock()
            if not self._fenced:
                await self._watch()
            await self._wait(LANE_TICK_S)

    async def _watch(self) -> None:
        error: str | None = None
        try:
            async with asyncio.timeout(ENVIRONMENT_LOCK_TIMEOUT_S):
                held = await self._lock.confirm()
        except Exception as exc:  # it cannot tell: taken as lost (C-2.21)
            held, error = False, type(exc).__name__
        if not held:
            self._fenced = True
            _log().critical("oms_environment_lock_lost", error=error)
            _page(self._pager, "oms_environment_lock_lost")

    def stale(self) -> bool:
        """Whether the lane has not ticked within `LANE_STALE_S`; the first stale read of each
        stall pages, and a fresh read ends the stall."""
        stale = self._clock() - self._ticked_at > LANE_STALE_S
        with self._stall:
            first, self._stalled = stale and not self._stalled, stale
        if first:
            _log().critical("oms_lane_stalled", stale_s=LANE_STALE_S)
            _page(self._pager, "oms_lane_stalled")
        return stale


def lane_audit_wal(settings: Settings) -> str:
    """The order lane's own audit WAL: `oms_lane.<name>` beside `CV_AUDIT_WAL_PATH`, so never the
    serving loop's file (#913 L2, D6)."""
    wal = Path(settings.audit_wal_path)
    return str(wal.with_name(LANE_WAL_PREFIX + wal.name))


def lane_sink_wal(settings: Settings) -> str:
    """The order lane's own `machine_events` WAL (#913 L2, ruling Q13): `oms_lane.<name>` beside
    `CV_MACHINE_EVENT_WAL_PATH`, which a persistence bundle's sink holds, a bundle composed or
    not, so a bundle that comes or goes across a restart never moves it (SEC-S3L2-03)."""
    wal = Path(settings.machine_event_wal_path)
    return str(wal.with_name(LANE_WAL_PREFIX + wal.name))


def pg_stores(settings: Settings, metrics: Metrics) -> OmsStores:
    """The stores over the runtime's own pool (`oms` in `pg_stat_activity`). Lazy: building them
    connects nothing. The lane's audit writer inserts through the audit repository over that pool,
    into the one `audit_log` chain, which the chain lock serialises (ruling Q12); the environment's
    lock is held on a connection of that pool's own (SEC-S3N-01)."""
    pool = SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "oms")
    events = EventFramesAdapter(EventsAdapter(SqlAlchemyEventStore(pool)))
    ops = PersistOps(metrics, where="order_lane")  # its pending rows apart from a bundle's
    counts = MachineEventSinkMetrics(flushed=ops.flushed, pending=ops.pending)
    audit_wal = lane_audit_wal(settings)
    cap_ms = settings.oms_statement_timeout_ms  # every capped store's but the sweep's (20 Sec.7.2)
    return OmsStores(
        orders=SqlAlchemyOrderStore(pool, statement_timeout_ms=cap_ms),
        executions=SqlAlchemyExecutionStore(pool, statement_timeout_ms=cap_ms),
        submissions=SqlAlchemySubmissionStore(pool, statement_timeout_ms=cap_ms),
        anchors=SqlAlchemyIdempotencyAnchorStore(pool, statement_timeout_ms=cap_ms),
        stops=SqlAlchemyRecordedStopStore(pool, statement_timeout_ms=cap_ms),
        groups=SqlAlchemyTradeGroupStore(pool, statement_timeout_ms=cap_ms),
        accounts=SqlAlchemyTradingAccountReads(pool, statement_timeout_ms=cap_ms),
        sweep=SqlAlchemyOrderStore(pool, statement_timeout_ms=SWEEP_STATEMENT_TIMEOUT_MS),
        # S8b (CG14): over the exchange-synced clock its caller gives, never the raw wall clock
        positions=lambda clock: SqlAlchemyPositionStore(
            pool, statement_timeout_ms=cap_ms, clock=clock
        ),
        audit=lambda alarm: build_lane_audit_writer(
            SqlAlchemyAuditRepository(pool), audit_wal, on_alarm=alarm
        ),
        sink=lambda wal: build_machine_event_sink(settings, events, metrics=counts, wal_path=wal),
        unclaimed=lambda: unclaimed_machine_events(settings),
        lock=SqlAlchemySessionLock(
            pool.engine,
            environment_lock_key(settings.environment.value),
            timeout_s=ENVIRONMENT_LOCK_TIMEOUT_S,
        ),
        release=pool.dispose,
    )


def group_reads(settings: Settings) -> TradeGroupReads | None:
    """The principal-scoped group reads of the REST routes (E28-T05 S2f), on a pool of their own on
    the serving loop, not the order lane's, at the OMS stores' statement cap; `None` on the fake
    backend (503). The adapter is built here, where the architecture test lets it be named, and
    typed as the scoped read alone: a route that holds it cannot reach the system port (C-12.4)."""
    if settings.storage_backend != "real":
        return None
    pool = SqlAlchemyRelationalRepository(settings.pg_dsn.get_secret_value(), "group-reads")
    return SqlAlchemyTradeGroupStore(pool, statement_timeout_ms=settings.oms_statement_timeout_ms)


class StandaloneSink(Interim):
    """No persistence bundle is composed, so no HMAC'd journal stands beside B1's `machine_events`
    (20 Sec.6.2, CV-C53): the startup announces it as it does an interim port,
    `oms_interim_ports{port="machine_event_sink"}` at 1 with a WARNING. B1's rows go to the order
    lane's own sink either way (#913 L2, ruling Q13)."""

    port: ClassVar[RuntimePortName] = "machine_event_sink"
    replaced_by: ClassVar[str] = "#2701"
    serves: ClassVar[str] = (
        "the standalone machine_events WAL sink, with no HMAC'd journal; on a live process with "
        "CV_TRADING_LIVE_ENABLED on, none, and the OMS is never ready"
    )


class UnclaimedMachineEvents(RuntimeError):
    """SEC-S3L2-03 (20 Sec.6.2): no persistence bundle is composed, so no sink of this process
    holds `CV_MACHINE_EVENT_WAL_PATH`, and it holds frames Postgres has not taken: a run before
    #913 L2's lane wrote B1's rows there, or a bundle's run left them. The start refuses, failing
    closed, never adopting or skipping them, so no chain forks or loses a row."""


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


class GroupRead(Protocol):
    """`OrderRoute.groups`: a replay's one read of its group, through the principal-scoped reader
    (`TradeGroupReader`, SR-E28-21), never the system facade (C-12.4)."""

    async def get(self, scope: AccountScope, group_id: GroupId) -> ScopedTradeGroup: ...


class OrderVersions(Protocol):
    """`OrderRoute.versions`: a `202`'s one read of B1's facade, an order's version (ruling Q5),
    never a command."""

    def version(self, order_id: UUID) -> int | None: ...


@dataclass(frozen=True, slots=True)
class OrderRoute:
    """What `POST /orders` reads of the composed OMS beside the pipeline and its anchors (24
    Sec.8.4), each the instance the pipeline was built with: the existence read (step 4), the arm
    records (step 5), the switches B1's `SEND` asks too (step 10), and a replay's rows (steps 8 and
    12): the order by its account, and the group through the principal-scoped reader (SR-E28-21),
    never the system facade (C-12.4). The account, order and group reads are typed as the one read
    each step uses. The exit routes (E29-T04 slice 4) read the arm records too, and the process's
    `environment`, which every order `OrderExits.scope` answers is of. `versions` is B1's facade,
    typed as the one read a `202`'s `ETag` makes of it, `version()` (ruling Q5)."""

    accounts: AccountExistence
    arm_records: ArmRecords
    switches: TradingSwitches
    orders: OrderRead
    groups: GroupRead
    environment: Environment
    versions: OrderVersions


class PeekedFigures(Protocol):
    """The leg accounts' cached figures for the trade-group preview (E28-T05 S3c, #909)."""

    async def peeked(
        self, symbol: Symbol, fallbacks: Mapping[UUID, Decimal | None]
    ) -> dict[UUID, AccountFigures | None]: ...


class PreviewFigures:
    """`PeekedFigures` over the order path's own account binding and figures, on the order lane
    (SR-E28-22): each account resolved as an order's is, so the preview never holds a key ref, its
    kept reading peeked at its bound profile's fallback and its symbol's rates merged as the size
    step merges them (`with_rates`). No venue read and no tiers asked: an account it cannot resolve
    (deleted, of another environment or keyless since the route's scope check, or unread), or with
    nothing fresh kept, has none, and its leg is `figure_unknown`."""

    def __init__(self, accounts: TradingAccounts, figures: OrderFigures) -> None:
        self._accounts, self._figures = accounts, figures

    async def peeked(
        self, symbol: Symbol, fallbacks: Mapping[UUID, Decimal | None]
    ) -> dict[UUID, AccountFigures | None]:
        known: dict[UUID, AccountFigures | None] = dict.fromkeys(fallbacks)
        for account_id, fallback in fallbacks.items():
            try:
                ref = await self._accounts.trading_account(AccountId(account_id))
            except OmsError:
                continue
            reading = self._figures.peek(ref, (symbol,), fallback_sl_offset_pct=fallback)
            known[account_id] = None if reading is None else with_rates(reading, symbol)
        return known


@dataclass(frozen=True, slots=True)
class PreviewParts:
    """What the trade-group preview reads of the composed OMS (E28-T05 S3c), the order path's own
    and never a write (the read-only guarantee): the leg guard over its risk gate and switches, its
    stop resolver, the listing and the ticker stream (with no demand, so no venue call), each read
    in place as the order route reads its switches, and the legs' figures, peeked on the lane."""

    guard: LegGuard
    stops: StopPort
    instruments: Instruments
    prices: ReferencePricesBinding
    figures: PeekedFigures


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
    exits: OrderExits
    lane: Lane
    cancel_all: CancelAll
    heartbeat: LaneHeartbeat
    #: E29-T05's private-stream consumer, built, started once `ready` (S8b).
    stream: StreamWiring
    #: When the fencing grace since the lock was taken ends, on the runtime's `monotonic`.
    admit_after: float
    preview: PreviewParts
    #: E29-T07 #915: `setPositionLeverage`'s service over the pipeline's account, instrument and
    #: profile reads, the routed port, the switches and the audit writer.
    leverage: PositionLeverage
    #: E29-T07 #915: the position writes' pre-check, fill wait, records and Partial-mode sweep.
    positions: PositionWrites
    #: E29-T13's snapshot reads on the lane, which the WS topics take once `ready`; None without
    #: the topics.
    topic_reads: TopicReads | None = None
    #: The observed group facade, when a `trade_groups` topic is wired (E28-T05).
    groups: ObservedGroups | None = None


@dataclass(frozen=True, slots=True)
class OnLane:
    """What `POST /orders` reaches of the composed OMS from the serving loop (20 Sec.6.2, CV-C13):
    the pipeline's submit and replay answer, the anchors' lookup, and steps 4 and 8's account and
    order reads, each awaited on the order lane (`Lane.call`), where the OMS and its pool run.
    Cancelling the await cancels the lane's task; the route's shield keeps the submit's (`_on_lane`
    for when the lane does not answer)."""

    parts: _Parts

    async def submit(self, request: OrderRequest, context: SubmitContext) -> SubmitOutcome:
        if self.parts.heartbeat.fenced:  # ruling 3: no new order once the lock is lost
            raise OmsNotReady
        return await _on_lane(self.parts, self.parts.submission.submit(request, context), None)

    async def answer_replay(self, account_id: AccountId, replay: Replay) -> SubmitOutcome:
        return await _on_lane(self.parts, self.parts.submission.answer_replay(account_id, replay))

    async def lookup(
        self,
        created_by: UUID,
        client_ref: UUID,
        request_sha256: str,
        *,
        operation: AnchorOperation = "placeOrder",
    ) -> Lookup:
        found = self.parts.anchors.lookup(
            created_by, client_ref, request_sha256, operation=operation
        )
        return await _on_lane(self.parts, found)

    async def environment_of(self, account_id: AccountId) -> Environment:
        return await _on_lane(self.parts, self.parts.route.accounts.environment_of(account_id))

    async def get(self, account_id: UUID, order_id: UUID) -> OrderRow | None:
        return await _on_lane(self.parts, self.parts.route.orders.get(account_id, order_id))


@dataclass(frozen=True, slots=True)
class OnLaneTopicReads:
    """E29-T13's snapshot reads (`ws_topics.SnapshotReads`) from the serving loop: each awaited on
    the order lane within `HOP_TIMEOUT_S`, where the OMS's pool runs; `OmsNotReady` once the lane
    has stopped or the hop's bound passed, which the topics read as a failed load."""

    parts: _Parts

    async def read(self, family: Family, account: UUID) -> View:
        reads = self.parts.topic_reads
        if reads is None:  # composed without the topics: never attached
            raise OmsNotReady
        return await _on_lane(self.parts, reads.read(family, account))


@dataclass(frozen=True, slots=True)
class OnLaneGroups:
    """`OrderRoute.groups` from the serving loop: a replay's group read, awaited on the lane."""

    parts: _Parts

    async def get(self, scope: AccountScope, group_id: GroupId) -> ScopedTradeGroup:
        return await _on_lane(self.parts, self.parts.route.groups.get(scope, group_id))


@dataclass(frozen=True, slots=True)
class OnLanePreview:
    """`PreviewParts.figures` from the serving loop: peeked on the lane, where they are kept."""

    parts: _Parts

    async def peeked(
        self, symbol: Symbol, fallbacks: Mapping[UUID, Decimal | None]
    ) -> dict[UUID, AccountFigures | None]:
        return await _on_lane(self.parts, self.parts.preview.figures.peeked(symbol, fallbacks))


@dataclass(frozen=True, slots=True)
class OnLaneExits:
    """`OmsRuntime.exits` from the serving loop (20 Sec.6.2, CV-C13; E29-T04 slice 4): the exit
    service's scope and account reads, each awaited on the order lane within `HOP_TIMEOUT_S`, and
    its refusal records, per-order cancels and amends, which wait out the service's own bounds, as
    the submit does; a refusal's record carries the route's `step` and `reason` as the route named
    them (24 Sec.15.5). The service, its store and B1's facade run on the lane. `guard`, the routes'
    in-flight guard, is read in place: only the serving loop's `run_claimed` claims and releases
    it, and the service never touches it after building it."""

    parts: _Parts

    @property
    def guard(self) -> InFlightGuard:
        return self.parts.exits.guard

    async def scope(self, caller: ExitCaller, order_id: UUID) -> ScopedOrder | ExitOutcome:
        return await _on_lane(self.parts, self.parts.exits.scope(caller, order_id))

    async def accounts_in_scope(
        self, scope: AccountScope, requested: Collection[UUID]
    ) -> tuple[UUID, ...]:
        return await _on_lane(self.parts, self.parts.exits.accounts_in_scope(scope, requested))

    async def deny(
        self,
        row: OrderRow,
        operation: ExitOperation,
        outcome: ExitOutcome,
        *,
        actor: SubmitActor,
        request_id: UUID | None,
        step: ExitStep | None = None,
        reason: str | None = None,
    ) -> ExitOutcome:
        record = self.parts.exits.deny(
            row, operation, outcome, actor=actor, request_id=request_id, step=step, reason=reason
        )
        return await _on_lane(self.parts, record, None)

    async def cancel_admitted(
        self,
        row: OrderRow,
        *,
        actor: SubmitActor,
        reason: CancelReason,
        request_id: UUID | None,
        origin: RuleOrigin | None = None,
    ) -> ExitOutcome:
        cancel = self.parts.exits.cancel_admitted(
            row, actor=actor, reason=reason, request_id=request_id, origin=origin
        )
        return await _on_lane(self.parts, cancel, None)

    async def amend(
        self,
        scoped: ScopedOrder,
        terms: AmendTerms,
        *,
        caller: ExitCaller,
        expected_seq: int | None,
    ) -> ExitOutcome:
        amend = self.parts.exits.amend(scoped, terms, caller=caller, expected_seq=expected_seq)
        return await _on_lane(self.parts, amend, None)


@dataclass(frozen=True, slots=True)
class OnLaneLeverage:
    """`OmsRuntime.leverage` from the serving loop (E29-T07 #915): a change, awaited on the order
    lane, where the trading port and the audit writer run, bounded by the service's own
    timeouts (its reads, its record and the venue's call), as the exits' cancels are."""

    parts: _Parts

    async def apply(
        self, request: LeverageRequest, *, actor: SubmitActor, request_id: UUID | None
    ) -> LeverageOutcome:
        change = self.parts.leverage.apply(request, actor=actor, request_id=request_id)
        return await _on_lane(self.parts, change, None)


@dataclass(frozen=True, slots=True)
class OnLanePositions:
    """`OmsRuntime.positions` from the serving loop (E29-T07 #915): the reversal's native-stop
    pre-check, its close's fill wait (bounded by its own deadline), the correlation records and a
    full close's sweep, each awaited on the order lane, where B1's facade, the stores, the trading
    port and the audit writer run."""

    parts: _Parts

    async def entry_stop_ready(self, account_id: AccountId) -> None:
        await _on_lane(self.parts, self.parts.positions.entry_stop_ready(account_id), None)

    async def group_key_free(self, created_by: UUID, key: UUID, request_sha256: str) -> None:
        free = self.parts.positions.group_key_free(created_by, key, request_sha256)
        await _on_lane(self.parts, free, None)

    async def await_fill(self, account_id: UUID, order_id: UUID, *, deadline: float) -> CloseFill:
        fill = self.parts.positions.await_fill(account_id, order_id, deadline=deadline)
        return await _on_lane(self.parts, fill, None)

    async def venue_position(self, row: PositionRow) -> VenuePosition:
        return await _on_lane(self.parts, self.parts.positions.venue_position(row), None)

    async def record(self, record: RequestRecord) -> bool:
        return await _on_lane(self.parts, self.parts.positions.record(record), None)

    async def sweep_after_close(
        self, row: PositionRow, order_id: UUID, *, actor: SubmitActor, request_id: UUID | None
    ) -> bool:
        sweep = self.parts.positions.sweep_after_close(
            row, order_id, actor=actor, request_id=request_id
        )
        return await _on_lane(self.parts, sweep)


@dataclass(frozen=True, slots=True)
class OnLaneCancelAll:
    """`OmsRuntime.cancel_all` from the serving loop (E29-T04 slice 4, S4-E): the cancel-all
    service's scope, a read, awaited on the order lane within `HOP_TIMEOUT_S`, and its run, which
    the service's own deadline bounds, as the exit service's cancels are. The service, the exit
    service under it and the order store run on the lane."""

    parts: _Parts

    async def scope(self, scope: AccountScope, request: CancelAllRequest) -> ScopedAccounts:
        return await _on_lane(self.parts, self.parts.cancel_all.scope(scope, request))

    async def run(
        self,
        accounts: ScopedAccounts,
        request: CancelAllRequest,
        *,
        actor: SubmitActor,
        request_id: UUID | None,
    ) -> CancelAllOutcome:
        run = self.parts.cancel_all.run(accounts, request, actor=actor, request_id=request_id)
        return await _on_lane(self.parts, run, None)


async def _on_lane[T](
    parts: _Parts, coro: Coroutine[Any, Any, T], timeout_s: float | None = HOP_TIMEOUT_S
) -> T:
    """`coro` awaited on the lane: `OmsNotReady` once the lane has stopped (CR-S3L1B-07), and, with
    `timeout_s`, past it (CR-S3L1A-02): a read's bound; the submit's is the stop's drain."""
    try:
        return await parts.lane.call(coro, timeout_s=timeout_s)
    except LaneStopped:
        raise OmsNotReady from None
    except TimeoutError:
        if timeout_s is None:
            raise
        raise OmsNotReady from None


async def _cancelled(task: asyncio.Task[Any]) -> None:
    """`task` cancelled and waited for, on its own loop."""
    task.cancel()
    await asyncio.wait({task})


def _heartbeat_ended(pager: Pager, task: asyncio.Task[None]) -> None:
    """A heartbeat that ended other than by its stop's cancel leaves the lane unticked and its
    lock unwatched: logged CRITICAL by its error's class and paged at once (SEC-S3L2-04), before a
    read finds the lane stalled."""
    if not task.cancelled() and (error := task.exception()) is not None:
        _log().critical("oms_lane_heartbeat_ended", error=type(error).__name__)
        _page(pager, "oms_lane_heartbeat_ended")


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
    with `unplaced_entry_swept`, as `system:oms`, its ids only (21 Sec.3.3.11, C-2.9). Its key
    names the reason, `unplaced_entry_swept:<stop id>`, as the stop gate's voids do: an entry's
    take-profit request and an amend's request hold `<stop id>` under the same action, and a void
    keyed the same would be deduped against it and lost (#4560)."""

    async def write_ahead(swept: tuple[SweptStop, ...]) -> None:
        for stop in swept:
            detail = {"order_id": str(stop.order_id), "kind": stop.kind, "source": "entry_attach"}
            name = f"{SWEEP_REASON}:{stop.id}"
            record = KeyedRecord(
                _SWEPT[stop.kind], name, stop.exchange_account_id, "recorded_stop",
                stop.id, "success", "warning", SWEEP_REASON, None, detail,
            )  # fmt: skip
            await audit.write(record)

    return write_ahead


class StreamHealth(TrackedAccounts, Protocol):
    """Account health as the runtime's private-stream consumer takes it (E29-T05 S8b;
    `AccountHealthRuntime`): the feed its evidence goes to (`AccountHealthFeed`'s three calls),
    its last good tracking read (`streamed`, read in place from the lane) and the opening of the
    boot episode's dead-man's-switch window (`stream_started`, on the serving loop, 20 Sec.6.2)."""

    @property
    def feed(self) -> StreamEvidence: ...

    def stream_started(self) -> None: ...


async def _stream_begun(stream: StreamWiring) -> None:
    """On the order lane, the loop that consumes: the consumer starts there (20 Sec.6.2)."""
    stream.start()


def _stream_stop_ended(call: asyncio.Future[None]) -> None:
    """The consumer's stop ended on the lane: one that failed, or that the lane's own stop or death
    cancelled, is logged by its class, its outcome retrieved, never raised."""
    error = asyncio.CancelledError() if call.cancelled() else call.exception()
    if error is not None:
        _log().error("oms_stream_consumer_stop_failed", error=type(error).__name__)


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


async def _close_port(port: OwnedPort | None, transport: httpx.AsyncBaseTransport | None) -> None:
    """The lane's trading port, its account clients closed, then the lane's own transport, which
    the port never closes (the dev-only account fixture's, #913 L1d): each on the lane."""
    try:
        if port is not None:
            await port.aclose()
    finally:
        if transport is not None:
            await transport.aclose()


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
    `start()`, which the lifespan awaits after the account health runtime's, starts the order lane
    (`oms_lane.OrderLane`, 29 CV-C13) and composes the OMS there: the order facade wires B1's
    process-wide ports and refuses a second one, so it lives from `start()` to `stop()`, never in
    `create_app()`. A task it tracks runs the startup sweep, steps 2 to 4 on the lane, and sets
    `ready` at its end only. What `start()` cannot compose fails the runtime closed: logged by
    step (`phase`) and paged, `degraded` and never ready, while market data stays up. `run` tracks
    the route's submits, which `stop()` drains. It owns E29-T05's private-stream consumer (S8b):
    composed with the OMS, started where `ready` is set, stopped first."""

    def __init__(
        self,
        settings: Settings,
        *,
        venue: Venue,
        ingestion: Ingestion,
        read_only: ReadOnlyCheck,
        metrics: Metrics,
        gate: OrderEntryCheck,
        standings: KeyStandingRead,
        oms_enabled: FlagRead,
        live_enabled: FlagRead,
        profiles: Profiles | None,
        persistence: Bundle | None,
        feed: MachineStatePort,
        lane_signing: LaneSigningBinder,
        health: StreamHealth,
        hub: SystemBroadcast,
        lane_transport: Callable[[], httpx.AsyncBaseTransport] | None = None,
        topics: AttachedTopics | None = None,
        stores: Callable[[], OmsStores] | None = None,
        pager: Pager | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        max_machines: int = MAX_MACHINES,
        registry: Registry | None = None,
        lane: Callable[[], Lane] = OrderLane,
        heartbeat: Callable[[EnvironmentLock, Pager], LaneHeartbeat] = LaneHeartbeat,
        fencing: Callable[[float], Awaitable[None]] = asyncio.sleep,
        watch: Callable[[float], Awaitable[None]] = asyncio.sleep,
        serving_tick: Callable[[], ServingTick] = ServingTick,
        trade_groups: GroupTopic | None = None,
        kill_switch: KillSwitch | None = None,
    ) -> None:
        self._settings, self._metrics, self._lanes = settings, metrics, lane
        #: The B18 port, the composition root's one instance (#2904 G-79), else the interim.
        self._kill_switch = InterimKillSwitch() if kill_switch is None else kill_switch
        self._trade_groups = trade_groups  # E28-T05: seeded, and handed each group write
        #: The wait of the fencing grace (SEC-S3L2-01), apart from `sleep`'s retries, and the
        #: serving loop's between its watch's reads of the lane's state (SEC-S3L2-04).
        self._heartbeat, self._fencing, self._watch = heartbeat, fencing, watch
        self._serving_tick = serving_tick
        self._env: Environment = settings.environment.value
        self._venue, self._ingestion, self._read_only = venue, ingestion, read_only
        self._gate, self._standings = gate, standings
        self._oms_enabled, self._live_enabled = oms_enabled, live_enabled
        self._persistence, self._feed = persistence, feed
        #: #913 L1d: M2's binder of the lane's own signing (`SecretsBundle.lane_signing`), and the
        #: dev-only account fixture's lane transport, None in production; each start calls both
        #: on the lane.
        self._lane_signing, self._lane_transport = lane_signing, lane_transport
        #: E29-T05 S8b: account health and the gateway's hub, as the private-stream consumer takes
        #: them (`StreamHealth`, its account notices' `broadcast_system`).
        self._health, self._hub = health, hub
        #: E29-T13 (#4207): the gateway's `orders`, `executions` and `positions` topics, which the
        #: lane publishes its committed steps and position rows to (`StepPublisher`) and which read
        #: their snapshots on the lane once `ready` (`OnLaneTopicReads`); None composes neither.
        self._topics = topics
        #: The consumer's start, sent to the lane once `ready`: None until the lane answers it, True
        #: once it started the consumer, False once it failed; `readyz` reads all but True as not
        #: started.
        self._streaming: bool | None = None
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
        #: The order lane while it runs for this start, composed or still asking the environment's
        #: lock (CR-S3L2-01/02); `stop()` stops it.
        self._lane: Lane | None = None
        #: The serving loop's tick (`ServingTick`), from `start()` until the lane has stopped.
        self._ticking: asyncio.Task[None] | None = None
        self._running: set[asyncio.Task[Any]] = set()
        self._failed = self._stopping = False
        #: The step `_compose` has reached, which a failed start logs and pages.
        self._phase = "settings"
        #: When each cause of the lane writer's alarm last paged, on `monotonic`; the lane's alone,
        #: where the writer runs (`_audit_alarm`).
        self._audit_paged: dict[str, float] = {}
        #: Taken, never released, by the first read that finds this start's lane dead: it pages.
        self._lane_paged = threading.Lock()
        #: SEC-S3L2-05: the composition hands its parts over under it, and the stop sets
        #: `_stopping` and takes them under it, so either the stop takes them or the composition,
        #: seeing the stop, closes them itself.
        self._handoff = threading.Lock()
        #: The serving loop's watch of the lane (SEC-S3L2-04) while the runtime runs.
        self._watching: asyncio.Task[None] | None = None

    @property
    def started(self) -> bool:
        """Between `start()` and `stop()`: `/readyz` carries the `oms` check meanwhile only, as a
        stopped module reports none."""
        return self._loop is not None and not self._stopping

    @property
    def state(self) -> OmsState:
        """`ok` once ready; `degraded` once it will not get ready (it failed closed, its sweep
        refused, or its startup task ended without it), or its order lane died, paged at its first
        read (SEC-S3L1A-02), or stalled, unticked for `LANE_STALE_S`, paged at the first read of
        each stall (ruling 2); else `starting` (20 Sec.6.2). The exit routes read this."""
        if (parts := self._parts) is not None and parts.lane.dead:
            if self._lane_paged.acquire(blocking=False):  # once per death: never released
                _page(self._pager, "oms_lane_died")
            return "degraded"
        if parts is not None and parts.heartbeat.stale():  # a wedged lane (ruling 2)
            return "degraded"
        if self._ready.is_set():
            return "ok"
        startup = self._startup
        failed = self._failed or (startup is not None and startup.done())
        return "degraded" if failed else "starting"

    def monotonic(self) -> float:
        """The runtime's injected monotonic clock, the one the position writes' deadlines are
        measured on (E29-T07 #915: a reversal's fill wait starts at the request's arrival)."""
        return float(self._monotonic())

    @property
    def readiness(self) -> OmsState:
        """What `placeOrder` admits on (24 Sec.8.4 step 3): `state`, and `degraded` too once the
        environment's lock is lost (ruling 3), when every new submit is refused, while `state`,
        which the exit routes read, keeps them open (C-2.6)."""
        state, parts = self.state, self._parts
        return "degraded" if parts is not None and parts.heartbeat.fenced else state

    @property
    def readyz(self) -> OmsState:
        """`/readyz`'s `oms` check (20 Sec.6.2, 24 Sec.8.12 "Readiness"): `readiness`, and once
        `ready`, `degraded` too while the private-stream consumer is not doing its job: it has not
        started (the lane has not yet confirmed its start, or the start failed), it has faulted,
        or a position reading has been owed to protection for `OWED_DEGRADED_S` or more; failing
        closed, so the check reads `ok` only once the lane has confirmed the start. Never
        `readiness` itself, which `placeOrder` reads (the orchestrator's Q3): one unprotected
        position never refuses every entry. Read from a worker thread; the detail names no
        account."""
        state, parts = self.readiness, self._parts
        if state != "ok" or parts is None:
            return state
        if self._streaming is not True or parts.stream.readiness.degraded() is not None:
            return "degraded"
        return state

    @property
    def submission(self) -> OnLane:
        """The pipeline, on the order lane once composed; `OmsNotReady` before."""
        return OnLane(self._composed())

    @property
    def anchors(self) -> OnLane:
        """The anchor service the pipeline was built with, whose lookup the route reads on the lane
        (SEC-S3D-02); `OmsNotReady` before it is composed."""
        return OnLane(self._composed())

    @property
    def route(self) -> OrderRoute:
        """The route's reads of the composed OMS (`OrderRoute`): the account, order and group reads
        on the lane, the arm records, the switches and B1's facade's `version()` (`versions`) in
        place; `OmsNotReady` before."""
        parts = self._composed()
        lane, groups, raw = OnLane(parts), OnLaneGroups(parts), parts.route
        return OrderRoute(
            lane, raw.arm_records, raw.switches, lane, groups, raw.environment, raw.versions
        )

    @property
    def preview(self) -> PreviewParts:
        """The trade-group preview's reads (`PreviewParts`), its figures peeked on the order lane
        (`OnLanePreview`); `OmsNotReady` before it is composed."""
        parts = self._composed()
        return replace(parts.preview, figures=OnLanePreview(parts))

    @property
    def exits(self) -> OnLaneExits:
        """The exit service the exit routes and cancel-all drive (E29-T04 slice 4), over the
        pipeline's facade, command port and checks, each call awaited on the order lane
        (`OnLaneExits`); `OmsNotReady` before it is composed."""
        return OnLaneExits(self._composed())

    @property
    def cancel_all(self) -> OnLaneCancelAll:
        """`cancelAllOrders`' service (E29-T04 slice 4, S4-E) over the exit service above and the
        order store's open-order read, each call hopped to the order lane (`OnLaneCancelAll`);
        `OmsNotReady` before it is composed."""
        return OnLaneCancelAll(self._composed())

    @property
    def leverage(self) -> OnLaneLeverage:
        """`setPositionLeverage`'s service (E29-T07 #915), each change awaited on the order lane
        (`OnLaneLeverage`); `OmsNotReady` before it is composed."""
        return OnLaneLeverage(self._composed())

    @property
    def positions(self) -> OnLanePositions:
        """The position writes' service (E29-T07 #915), each call awaited on the order lane
        (`OnLanePositions`); `OmsNotReady` before it is composed."""
        return OnLanePositions(self._composed())

    def _composed(self) -> _Parts:
        if self._parts is None:
            raise OmsNotReady
        return self._parts

    async def wait_ready(self) -> None:
        """Until the startup sweep has set `ready`, on the serving loop only: `ready` is an
        `asyncio.Event` of that loop. E29-T05's consumer, on the lane, is started where `ready` is
        set (`_stream_started`), never by a waiter here."""
        await self._ready.wait()

    def run[T](self, coro: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
        """The route's submit, as a task the runtime tracks and the route shields (24 Sec.8.4 step
        12), which awaits the pipeline on the order lane (`OnLane`): `stop()` drains it. Before
        anything is composed, once the stop has begun, or once the environment's lock is lost
        (ruling 3), `OmsNotReady`. On the serving loop, the one that started the runtime, only,
        where the task keeps the 24 h record (CR-S3C2-01): another is a `RuntimeError`. Refused
        either way, the coroutine is closed."""
        if self._stopping or self._parts is None or self._parts.heartbeat.fenced:
            coro.close()
            raise OmsNotReady
        if self._loop is not asyncio.get_running_loop():
            coro.close()
            raise RuntimeError("the OMS's submits run on the loop that started it (CR-S3C2-01)")
        task = spawn(coro, name="oms-submit")
        self._running.add(task)
        task.add_done_callback(self._ended)
        return task

    def _ended(self, task: asyncio.Task[Any]) -> None:
        self._running.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            _log().error("oms_submit_task_failed", error=type(error).__name__)

    async def _audit_alarm(self, cause: str) -> None:
        """Ruling 4 (the orchestrator's of 2026-10-25 12:22Z; CR-S3L2-08): the lane writer's
        fail-closed alarm, a refused append (its WAL full or unwritable) or its flusher's death,
        paged through the runtime's pager (`cv_page`), so an `audit_unavailable` refusal is never a
        silent outage: the first of each `LANE_AUDIT_PAGE_S` window per cause (its error's class
        alone), on `monotonic`, a clock stepped back read as expired. On the lane, where the writer
        runs."""
        now, paged = self._monotonic(), self._audit_paged.get(cause)
        if paged is None or not 0 <= now - paged < LANE_AUDIT_PAGE_S:
            self._audit_paged[cause] = now
            _page(self._pager, f"oms_lane_audit_alarm: {cause}")

    async def _watched(self) -> None:
        """SEC-S3L2-04: every `LANE_STALE_S` the serving loop reads the runtime's state itself,
        whose reads page a dead lane once a death and a wedged one once a stall, so neither waits
        for a route or `/readyz` to read it; until the stop cancels it."""
        while True:
            await self._watch(LANE_STALE_S)
            _ = self.state

    def _watch_ended(self, task: asyncio.Task[None]) -> None:
        """A watch that ended other than by the stop's cancel: logged CRITICAL and paged, as the
        lane's stalls would page only on a reader's read again."""
        if not task.cancelled() and (error := task.exception()) is not None:
            _log().critical("oms_lane_watch_ended", error=type(error).__name__)
            _page(self._pager, "oms_lane_watch_ended")

    def _startup_ended(self, task: asyncio.Task[None]) -> None:
        """An error out of the startup task (a flag view or the guard raising) leaves the state
        `degraded` and never ready: logged, not left for asyncio's "never retrieved" at GC."""
        if not task.cancelled() and (error := task.exception()) is not None:
            _log().critical("oms_startup_failed", error=type(error).__name__)

    def _tick_ended(self, task: asyncio.Task[None]) -> None:
        """A serving-loop tick that ended other than by its stop's cancel leaves every new submit
        and risk-increasing amend fenced (`FencedSwitches`) until the runtime starts again, never
        admitted (fail closed): logged by its error's class and paged, once, as the task ends once
        (SEC-S3L4-02)."""
        if not task.cancelled() and (error := task.exception()) is not None:
            _log().critical("oms_serving_tick_ended", error=type(error).__name__)
            _page(self._pager, "oms_serving_tick_ended")

    async def start(self) -> None:
        """Start the serving loop's tick (`ServingTick`, L4) and the order lane, compose the OMS on
        the lane, then spawn the startup task (20 Sec.6.2). A second call does nothing until
        `stop()`. What cannot be composed, the lane included, fails the runtime closed, the tick
        and the lane stopped again; but an environment lock that was not answered (Postgres
        unreachable) is asked again by the startup task, the runtime `starting` meanwhile
        (CR-S3L2-01/02). The composition hands its parts to the runtime itself, so a start
        cancelled once it has ended closes them before it stops the lane (SEC-S3L2-05); the
        serving loop's watch of the lane runs from here to the stop (SEC-S3L2-04)."""
        if self._loop is not None and not self._stopping:
            return
        self._loop, self._stopping, self._failed = asyncio.get_running_loop(), False, False
        self._lane_paged = threading.Lock()  # a new lane: its death pages anew
        self._streaming = None  # a new consumer, started once this start is ready
        lane = self._lane = self._lanes()
        tick, serving = self._serving_tick(), Serving(self._loop, self._metrics)
        # the serving loop's tick, which a new submit meets on the lane (L4, ruling of 19:19Z)
        self._ticking = spawn(tick.run(), name="oms-serving-tick")
        self._ticking.add_done_callback(self._tick_ended)
        try:
            self._phase = "lane"
            await lane.start()
            await lane.call(self._compose(lane, serving, tick))  # it hands its parts over itself
        except EnvironmentLockUnanswered:  # no other holder: the startup task asks again
            _log().warning("oms_environment_lock_unanswered", retry_s=SWEEP_RETRY_S[0])
        except Exception as exc:  # fail closed (C-2.21): never ready, no order admitted
            await self._fail_closed(lane, exc)
            return
        except BaseException:  # cancelled: the compose closes what it built on the lane first
            try:  # its wait there, then the join, within the stop reserve (20 Sec.6.2)
                deadline = asyncio.get_running_loop().time() + OMS_STOP_RESERVE_S - LANE_JOIN_S
                with contextlib.suppress(LaneStopped, TimeoutError):
                    async with asyncio.timeout_at(deadline):
                        await lane.idle()
                with self._handoff:  # handed over as the cancel came (SEC-S3L2-05): closed here
                    parts, self._parts = self._parts, None
                if parts is not None:
                    await _closed(parts.closers, deadline)
            finally:  # cancelled again meanwhile or not (SEC-S3L1C-01)
                self._untick()
                self._lane = None
                await lane.stop()
            raise
        if self._stopping:  # a stop began meanwhile and took what was composed (SEC-S3L2-05)
            return
        self._startup = spawn(self._started(lane, serving, tick), name="oms-startup")
        self._startup.add_done_callback(self._startup_ended)
        self._watching = spawn(self._watched(), name="oms-lane-watch")
        self._watching.add_done_callback(self._watch_ended)

    async def _fail_closed(self, lane: Lane, error: Exception) -> None:
        """A start that cannot compose fails the runtime closed (C-2.21): the serving loop's tick
        ended and its lane stopped, logged CRITICAL by its step and paged, `degraded` and never
        ready, no order admitted."""
        self._untick()
        self._lane = None
        await lane.stop()
        self._failed, phase = True, self._phase
        _log().critical("oms_runtime_failed_closed", phase=phase, error=type(error).__name__)
        _page(self._pager, f"oms_runtime_failed_closed: {phase}")

    async def _composed_again(self, lane: Lane, serving: Serving, tick: ServingTick) -> bool:
        """CR-S3L2-01/02 (20 Sec.6.2): the start could not ask the environment's lock, which is no
        other holder, so this asks again, the whole composition with it, after the sweep's backoff
        on the runtime's sleep (`SWEEP_RETRY_S`), each failure logged, never ready meanwhile.
        True once composed; another holder (`EnvironmentLocked`), or any other failure, fails the
        runtime closed as a failed start does, paged. The `SWEEP_MAX_FAILURES`-th unanswered ask
        in a row, the start's own counted, is logged CRITICAL and paged once, and the asking goes
        on (SEC-S3L2-06). A failure met while a stop runs ends it, cancelled, never paged; the
        composition hands its parts over itself (SEC-S3L2-05)."""
        delay, ceiling = SWEEP_RETRY_S
        unanswered = 1  # the start's own ask
        while True:
            await self._sleep(delay)
            delay = min(2 * delay, ceiling)
            try:
                await lane.call(self._compose(lane, serving, tick))
            except EnvironmentLockUnanswered:
                unanswered += 1
                paged = unanswered == SWEEP_MAX_FAILURES
                log = _log().critical if paged else _log().warning
                log("oms_environment_lock_unanswered", retry_s=delay, unanswered=unanswered)
                if paged:  # once: the asking goes on
                    _page(self._pager, "oms_environment_lock_unanswered")
                continue
            except Exception as exc:
                if self._stopping:  # the stop's cancel or its stopped lane, never a failure
                    raise asyncio.CancelledError from exc
                await self._fail_closed(lane, exc)
                return False
            return True

    async def stop(self) -> None:
        """Clear `ready`; begin the private-stream consumer's stop on the lane first and, beside
        it, give the submits in flight at most `CV_OMS_DRAIN_S`; wait for the consumer's stop at
        most `OMS_CONSUMER_STOP_S` from its start (E29-T05 S8b, the orchestrator's Q2 (a)), so no
        push reaches a facade that has stopped; cancel what remains and the startup task, their
        work on the lane with them, and wait for it to end there; then close the stop gate (its
        complete reads and passes cancelled with the startup task, before the machines), the
        facade (it unwires B1's ports), the command port, the lane's own sink, the private streams
        its bridge still holds (#913 L1d-2b), the trading port, its loop signing (whose close
        frees M2's lane pool), the lane's own audit writer, which the signing's last record needs,
        the OMS's pool and the lane's heartbeat, each on its own loop, isolated, within its share
        of what is left, and last the environment's lock (SEC-S3N-01), so nothing that signs or
        sends outlives it; then end the serving loop's tick, stop the lane, one still asking the
        lock included, and join its thread. All of it ends by `OMS_STOP_RESERVE_S` after the
        longer of the drain and the consumer's stop, `LANE_JOIN_S` of it the join's, inside the
        OMS module's 15 s grace (20 Sec.6.2). The shared profile cache is its owner's to close.
        What a composition handed over before the stop began is closed here; one that ends after
        it closes what it built itself (SEC-S3L2-05). The serving loop's watch ends with the
        startup task."""
        self._ready.clear()
        with self._handoff:
            self._stopping = True
        stream = self._stream_stop()  # first, and beside the drain (S8b)
        pending = await _drained(set(self._running), self._settings.oms_drain_s)
        await self._stream_stopped(stream)
        startup, self._startup = self._startup, None
        watching, self._watching = self._watching, None
        pending |= {task for task in (startup, watching) if task is not None}
        for task in pending:
            task.cancel()
        deadline = asyncio.get_running_loop().time() + OMS_STOP_RESERVE_S - LANE_JOIN_S
        lane, self._lane = self._lane, None
        with self._handoff:
            parts, self._parts = self._parts, None
        closers: list[_Closer] = [("cancelled", lambda: asyncio.wait(pending))] if pending else []
        if self._topics is not None:  # E29-T13: no snapshot read hops to a stopping lane
            closers.insert(0, ("ws_topic_reads", self._topics.detach))
        if lane is not None:  # its work cancelled above, a composition asked again among it
            closers.append(("lane", lane.idle))
        if parts is not None:
            closers += parts.closers
        try:
            await _closed(closers, deadline)
        finally:
            self._untick()  # the drain's submits met it; once the closers ran, none is left
            if lane is not None:  # cancelled or not: its own join bounds it (`LANE_JOIN_S`)
                await lane.stop()
        self._failed = False

    def _stream_stop(self) -> tuple[asyncio.Future[None], float] | None:
        """S8b (20 Sec.6.2): the consumer's stop, begun on the lane, where it runs, ahead of the
        drain: it closes every stream and ends its tasks within its own bound
        (`stream_consumer.STOP_TIMEOUT_S`, counted `stop_timeout` past it), and a start that has
        not landed yet starts nothing after it. The stop then waits for it at most
        `OMS_CONSUMER_STOP_S` from here (`_stream_stopped`) and never cuts it short. None with
        nothing composed, or a lane that refuses the call (stopped, dead or anything else),
        logged by its class: the stop goes on, outside `_closed`'s isolation as it is."""
        parts = self._parts
        if parts is None:
            return None
        try:
            call = parts.lane.call(parts.stream.stop())
        except Exception as exc:
            _log().error("oms_stream_consumer_stop_failed", error=type(exc).__name__)
            return None
        call.add_done_callback(_stream_stop_ended)
        return call, asyncio.get_running_loop().time() + OMS_CONSUMER_STOP_S

    async def _stream_stopped(self, stopping: tuple[asyncio.Future[None], float] | None) -> None:
        """The consumer's stop, waited for until `OMS_CONSUMER_STOP_S` after it began: one still
        running then is logged and holds the runtime's stop no longer, its tasks already cancelled
        on the lane, which its own stop and the bridge's closer end there."""
        if stopping is None:
            return
        call, deadline = stopping
        left = max(0.0, deadline - asyncio.get_running_loop().time())
        done, _ = await asyncio.wait({call}, timeout=left)
        if not done:
            _log().error("oms_stream_consumer_stop_overran", bound_s=OMS_CONSUMER_STOP_S)

    def _untick(self) -> None:
        """End the serving loop's tick, if it runs: cancelled, which its callback neither logs nor
        pages."""
        ticking, self._ticking = self._ticking, None
        if ticking is not None:
            ticking.cancel()

    async def _started(self, lane: Lane, serving: Serving, tick: ServingTick) -> None:
        """The startup sweep (20 Sec.6.2): a composition the environment's lock held back first
        (`_composed_again`), then step 1's waits, then what is left of the fencing grace since the
        lock was taken (`ENVIRONMENT_FENCE_GRACE_S`, SEC-S3L2-01), so a previous holder whose
        session ended has fenced itself before this one sweeps or admits, then steps 2 to 4, run
        again after a backoff while the store or the audit fails them (any other error ends it
        `degraded` after `SWEEP_MAX_FAILURES`, paged), then step 5, `ready`, never early, and there
        the private-stream consumer's start (`_stream_started`). A failure met while a stop runs
        ends it, cancelled, never retried."""
        if self._parts is None and not await self._composed_again(lane, serving, tick):
            return
        await self._waited()
        parts, (delay, ceiling) = self._composed(), SWEEP_RETRY_S
        if (grace := parts.admit_after - self._monotonic()) > 0:  # SEC-S3L2-01, step 1's counted
            await self._fencing(grace)
        stuck = 0  # the failures no retry can outlast (CR-S3E3-02)
        while True:
            try:
                swept = await parts.lane.call(self._swept(parts))  # on the order lane (CV-C13)
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
            if swept and not self._stopping:
                await self._seeded(parts)  # before `ready`, so before any group write (E28-T05)
            if swept and not self._stopping:  # a stop that began meanwhile clears `ready` for good
                self._ready.set()
                _log().info("oms_ready")
                if self._topics is not None:  # E29-T13: snapshots read on the lane from now on
                    self._topics.attach(OnLaneTopicReads(parts))
                await self._stream_started(parts)
            return

    async def _stream_started(self, parts: _Parts) -> None:
        """S8b (20 Sec.6.2, the orchestrator's Q4), where `ready` is set: account health's boot
        dead-man's-switch window opens (`stream_started`, here on the serving loop, the monitor's),
        then the private-stream consumer starts on the lane, where it runs, its owed gauge read at
        each scrape from then. No flag gates it (C-4.14). `/readyz` reads `degraded` until the lane
        confirms the start (`readyz`). A window that cannot open, or a start the lane refuses or
        does not answer, is logged CRITICAL by its error's class and paged, the check stays
        `degraded`, and the consumer is stopped on the lane all the same (`_stream_unstarted`), as
        a start the hop's bound cut may have begun there; one a stop overtook starts nothing."""
        try:
            self._health.stream_started()
            await parts.lane.call(_stream_begun(parts.stream), timeout_s=HOP_TIMEOUT_S)
        except Exception as exc:
            if self._stopping:  # the stop's own lane: nothing to start
                raise asyncio.CancelledError from exc
            self._streaming = False
            _log().critical("oms_stream_consumer_unstarted", error=type(exc).__name__)
            _page(self._pager, "oms_stream_consumer_unstarted")
            await self._stream_unstarted(parts)
            return
        self._streaming = True

    async def _stream_unstarted(self, parts: _Parts) -> None:
        """Fable Low-2: a start the hop's bound cut after the lane took it may have begun there, so
        the consumer is stopped on the lane too (a no-op for one never begun), and no consumer
        runs that `/readyz` reports as not started; bounded by the hop, logged by its class, never
        raised: the runtime stays `degraded` and paged either way."""
        try:
            await parts.lane.call(parts.stream.stop(), timeout_s=HOP_TIMEOUT_S)
        except Exception as exc:
            _log().error("oms_stream_consumer_stop_failed", error=type(exc).__name__)

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

    async def _seeded(self, parts: _Parts) -> None:
        """E28-T05 S4b: the topic's seed, read before `ready`. Only a submit writes a group, and
        one is admitted once ready, so the read and its notice precede every write's. Its reads
        (`SEED_ATTEMPTS`) share one sweep call's bound, so the seed delays `ready` by at most 17 s
        (15 s plus 2 s). Its count is logged. A seed that fails every read is counted
        (`SEED_FAILURES`) and logged at critical by its error's type, and the topic stays unseeded
        (its subscriptions pending) until restart; the OMS gets ready all the same."""
        if parts.groups is None:
            return
        try:
            count = await self._bounded(self._seed_reads(parts.lane, parts.groups))
        except Exception as exc:
            spec = next(spec for spec in CATALOGUE if spec.name == SEED_FAILURES)
            failures = self._metrics.counter(spec.name, spec.help, max_series=spec.max_series)
            failures.child().inc()
            _log().critical("oms_trade_groups_unseeded", error=type(exc).__name__)
            return
        _log().info("oms_trade_groups_seeded", count=count)

    async def _seed_reads(self, lane: Lane, groups: ObservedGroups) -> int:
        """The seed, read again after the sweep's first backoff when a read fails, until the
        `SEED_ATTEMPTS`th failure, which is raised; a cancellation never waits for a retry."""
        attempt = 1
        while True:
            try:
                return await lane.call(groups.seed(self._env))
            except Exception:
                if attempt == SEED_ATTEMPTS:
                    raise
            attempt += 1
            await self._sleep(SWEEP_RETRY_S[0])

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

    async def _compose(self, lane: Lane, serving: Serving, tick: ServingTick) -> _Parts:
        """The C6 rig's composition, on the order lane (CV-C13), for the process's environment only
        (C-2.11): the switches, bindings and announcements, the latch (20 Sec.6.2), then over the
        pool, made here, the stores, without a bundle the probe of the file its sink would hold
        (SEC-S3L2-03, else `UnclaimedMachineEvents`), the environment's lock, held before the
        lane's signing, its trading port, the facade or any machine exists (SEC-S3N-01, else
        `EnvironmentLocked`), the lane's own audit writer (#913 L2), its loop signing over that
        writer and its self-check, the lane's own trading port and router (#913 L1d) with the
        bridge its private streams cross (#913 L1d-2b), the lane's own sink, the command port, the
        facade, the private-stream consumer over it, built and not started, a live process failing
        closed there (E29-T05 S8b), the anchors and the pipeline; what the serving loop holds,
        through its bridge (`Served*`). A failure once the pool exists closes what was built before
        it goes on, each closer on its own loop."""
        self._phase = "settings"
        settings, env, metrics = self._settings, self._env, self._metrics
        ingestion = self._ingestion
        bounds = OmsBounds.from_settings(settings)
        ports = SubmissionPorts.interim(now=self._now)
        announce_interim_ports(ports, metrics=metrics)
        announce_interim_port("atr", ATR_FALLBACK, metrics=metrics)  # ruling Q6, until E13's port
        # one bridge for both: the gate refuses at once a credential the rejections report
        standings = ServedStandings(self._standings, serving)
        heartbeat: LaneHeartbeat | None = None  # built last, its fence joins the switches

        def fenced() -> bool:  # SEC-S3L2-02: read in place, a single assignment's bool
            return heartbeat is not None and heartbeat.fenced

        switches = TradingSwitchesBinding(
            live_enabled=settings.trading_live_enabled,
            live_flag=self._live_enabled,
            kill_switch=self._kill_switch,
            gate=ServedGate(self._gate, standings),
            fenced=fenced,
        )
        switches.announce(metrics=metrics)
        # fenced while the serving loop stalls (L4): a new submit's, and the exit service's, which a
        # risk-increasing amend alone reads (the orchestrator's ruling of 2026-10-25 21:56Z)
        submits = FencedSwitches(switches, tick)
        self._phase = "sink"
        bundle = self._persistence
        sunk = StandaloneSink() if bundle is None else bundle.sink
        announce_interim_port("machine_event_sink", sunk, metrics=metrics)
        if bundle is None and env not in _NOT_LIVE and settings.trading_live_enabled:
            raise NoMachineEventSink
        self._phase = "profiles"
        if self.profiles is None:
            raise NoProfileCache
        self._phase = "stores"
        stores = self._stores()
        closers: list[_Closer] = [("pool", lambda: lane.call(stores.release()))]
        try:
            self._phase = "sink_wal"  # SEC-S3L2-03: before the lane's sink or the facade exists
            if bundle is None and (left := await run_in_thread(stores.unclaimed)):
                _log().critical("oms_machine_event_wal_unclaimed", pending_bytes=left)
                raise UnclaimedMachineEvents(f"{left} bytes of machine_events no sink holds")
            self._phase = "environment_lock"  # SEC-S3N-01: before the facade or any machine
            try:
                held = await stores.lock.acquire()
            except StorageTierUnavailable as exc:  # no other holder: asked again (CR-S3L2-01)
                raise EnvironmentLockUnanswered(f"the {env} OMS lock was not answered") from exc
            if not held:
                raise EnvironmentLocked(f"another process holds the {env} OMS lock")
            closers.append(("environment_lock", lambda: lane.call(stores.lock.release())))  # last
            admit_after = self._monotonic() + ENVIRONMENT_FENCE_GRACE_S  # SEC-S3L2-01
            self._phase = "audit"
            # on the lane, its own WAL locked (D6), its alarm paged; it stops after its users, the
            # loop signing's last records among them
            writer = stores.audit(self._audit_alarm)
            closers.insert(0, ("audit", lambda: lane.call(writer.stop(LANE_AUDIT_STOP_S))))
            self._phase = "signing"
            # #913 L1d: the lane signs its own venue calls through M2's `LoopSigning`, bound here
            # over a credential store M2 builds on the lane and alone holds, its records ahead
            # through the lane's own writer; its close frees that store's pool
            signing = self._lane_signing(audit=writer)
            closers.insert(0, ("loop_signing", lambda: lane.call(signing.aclose())))
            await signing.self_check()  # a wiring fault fails the start, never an order's signing
            self._phase = "port"
            port: OwnedPort | None = None
            transport = None if self._lane_transport is None else self._lane_transport()
            # registered before the build, so a refused build still closes the transport: the
            # closure reads `port` late, when a closer runs it, so it closes the port the build
            # below assigns, or none if the adapter refused it
            closers.insert(0, ("trading_port", lambda: lane.call(_close_port(port, transport))))
            # #913 L1d-2b: the private streams stay on the serving loop's one registry (ruling Q2
            # (b)); the port opens them across this bridge, which does no I/O until a subscribe
            streams = LaneStreams(self._venue.open_private_stream, serving)
            port = self._venue.lane_trading_port(
                env, credentials=signing.borrower, transport=transport,
                clock_offset_ms=ingestion.clock_offset_snapshot_ms, private_streams=streams,
            )  # fmt: skip
            # what a consumer left open closes on the serving loop, the lane dead or not, ahead of
            # the port, by name, so before the heartbeat and the environment's lock (#913 L2)
            at_port = [name for name, _ in closers].index("trading_port")
            closers.insert(at_port, ("private_streams", lambda: serving.call(streams.aclose())))
            # S4-F (24 Sec.8.7): the OMS's way to the venue meets cancel-all's folds; every other
            # call passes through it as it is. The folds sit on the lane, over its own port.
            spacer = CancelAllSpacer(monotonic=self._monotonic, sleep=self._sleep)
            folds = CancelAllCoalescer(
                port, spacer=spacer, monotonic=self._monotonic, sleep=self._sleep,
                fold_sizes=_histogram(metrics, "oms_cancel_all_fold_members"),
            )  # fmt: skip
            router = TradingRouter({env: folds}, lane_waits=self._venue.lane_waits())
            self._phase = "commands"
            timer = WriteTimer(_histogram(metrics, "oms_db_write_seconds"))
            orders = OrderRepository(stores.orders, timer)
            stops = RecordedStopRepository(stores.stops, timer)
            audit = OmsAudit(writer, environment=env)
            notices = OrderNoticesRouter(self._pager)
            accounts = TradingAccountsBinding(stores.accounts, environment=env)
            # the size step's figures (24 Sec.9.3.6): on live, none, so every entry is refused
            figures = NoDayFigures() if env not in _NOT_LIVE else DayRiskFigures(
                env, port_for=router.port_for, tiers=_tiers(ingestion.instruments),
                now=self._now, monotonic=self._monotonic,
            )  # fmt: skip
            announce_interim_port("risk_figures", figures, metrics=metrics)
            clock = None if ingestion.clock is None else ServedClock(ingestion.clock, serving)
            clock_health = ClockHealthBinding(clock)  # the halt's and the consumer's re-sync's
            halt = ClockHalt(clock_health, monotonic=self._monotonic, metrics=metrics)
            command_accounts = CommandAccounts(accounts, self._pager)
            resolver = StopResolver(
                stops, CompleteRead(orders), StopVoidAudit(audit), now=self._now,
                store_timeout_s=store_timeout_for(settings.oms_statement_timeout_ms),
            )  # fmt: skip
            gate = ResolvingStopGate(
                stops, resolver, accounts=command_accounts, port_for=router.port_for,
                bound_s=bounds.stop_request_s, now=self._now, monotonic=self._monotonic,
                metrics=metrics, pager=self._pager,
            )  # fmt: skip
            rejections = CredentialRejectionsBinding(
                standings, key_refusal=self._venue.key_refusal, pager=self._pager
            )
            commands = OmsCommandPort(
                router=router, accounts=command_accounts, orders=orders, stops=stops,
                handovers=NoHandoverStore(), credentials=rejections, clock_halt=halt,
                switches=submits, audit=audit, submit_audit=audit, gate=gate, notices=notices,
                now_us=self._now_us, submit_timeout_s=bounds.submit_timeout_s, figures=figures,
            )  # fmt: skip
            fills = ExecutionRepository(stores.executions, timer)
            # E29-T13 (#4207): the WS topics' lane half, fed by each committed step and applied
            # position row, its frames crossing to the serving loop (`Serving.notify`)
            lane_clock = LaneClock(self._now)
            published = None if self._topics is None else StepPublisher(
                self._topics, serving.notify, fills, environment=env, clock=lane_clock,
                overtaken=_counter(metrics, OVERTAKES).child().inc,
            )  # fmt: skip
            # E28-T05 S4b: each committed group write goes to the topic, the first persist's too
            topic, observed = self._trade_groups, None
            submissions = SubmissionRepository(stores.submissions, timer)
            if topic is not None:
                observed = ObservedGroups(stores.groups, topic, serving)
                submissions = ObservedSubmissions(stores.submissions, timer, observed)
            steps = OrderStepWriter(
                orders,
                fills,
                clock=self._now,
                submissions=submissions,
                on_commit=None if published is None else published.committed,
            )
            # the lane's own, at one path whether or not a bundle holds the serving loop's
            sink = stores.sink(lane_sink_wal(settings))  # (ruling Q13, SEC-S3L2-03)
            states = OrderStateFeed(self._feed, max_orders=self._max)
            feed = CompositePublisher(ServedFeed(states, serving))
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
            if published is not None:  # a position waits for the fills held before their bind
                published.bind(machines.held_fills)
            closers[:0] = [
                # the stop gate first: its reads end with the startup task's, before the machines
                ("stop_gate", lambda: lane.call(gate.aclose())),
                ("machines", lambda: lane.call(machines.stop())),
                ("commands", lambda: lane.call(commands.aclose())),
            ]
            if published is not None:  # before the stop gate: nothing taken once the stop begins
                closers.insert(0, ("ws_topics", lambda: lane.call(published.aclose())))
            self._phase = "stream"
            # E29-T05 S8b (24 Sec.8.12): the private-stream consumer over the facade, built and not
            # started (`_stream_started`), its stop the stop's first step (`_stream_stop`); its
            # position store on this pool over the exchange-synced clock its projection reads too
            # (CG14). Its stand-ins refuse a live process here, on the bindings as bound, until
            # E29-T06 (D4; the orchestrator's Q8) and, for the paging foreign-order lockout, until
            # E39-T04 (the security sign-off on #848, M1): the runtime fails closed, never ready.
            wall = ExchangeWallClock(ingestion.clock_offset_snapshot_ms)
            positions = stores.positions(wall)
            stream = build_stream_consumer(
                facade=machines, orders=orders, stops=stops,
                positions=_published(PositionRepository(positions, timer), published),
                snapshots=PositionSnapshotRepository(positions, timer),
                accounts=HealthAccounts(self._health), trading=accounts, ports=router,
                health=self._health.feed, hub=self._hub, serving=serving, credentials=rejections,
                audit=audit, emitter=writer, environment=settings.environment, pager=self._pager,
                metrics=metrics, now=self._now, offset_ms=ingestion.clock_offset_snapshot_ms,
                clock_health=clock_health, clock=wall,
            )  # fmt: skip
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
            asked = None if demand is None else ServedDemand(demand, serving)
            if demand is not None:
                # after the commands
                closers.insert(3, ("ticker_demand", lambda: serving.call(demand.close())))
            instruments = InstrumentsBinding(ingestion.instruments)
            # E28-T05 S3c: the preview's reads, the order path's own; its prices ask no demand
            preview = PreviewParts(
                S4SGuard(ports.risk_gate, submits), ports.stop_resolver, instruments,
                ReferencePricesBinding(tickers), PreviewFigures(accounts, figures),
            )  # fmt: skip
            validator = Validator(read_only_gate=self._read_only)
            # the profile cache is the serving loop's: the pipeline and the exits share one bridge
            profiles = ServedProfiles(self.profiles, serving)
            # S4-S-d: the size step's ask for missing tiers (S4-S-b2a calls it); a no-op when no
            # catalogue is composed, as on a process with no exchange feed
            catalogue = ingestion.instruments
            tiers: TierRequests = NO_TIER_REQUESTS
            if catalogue is not None:
                bridge = ServedTierRequests(catalogue, serving, metrics)
                # before the environment's lock, whose release the stop keeps last (#913 L2)
                at_lock = [name for name, _ in closers].index("environment_lock")
                closers.insert(at_lock, ("tier_requests", bridge.close))
                tiers = bridge
            deps = SubmissionDeps(
                accounts=accounts,
                instruments=instruments,
                prices=ReferencePricesBinding(tickers, demand=asked),
                profiles=profiles,
                switches=submits,
                gate=gate,
                audit=audit,
                groups=TradeGroupRepository(stores.groups) if observed is None else observed,
                figures=figures,
                tier_requests=tiers,
            )
            submission = OrderSubmission(
                ports, deps, machines=machines, commands=commands,
                allocator=OrderLinkIdAllocator(orders),
                validator=validator, router=router,
                anchors=anchors, clock_halt=halt, metrics=metrics, now=self._now,
                monotonic=self._monotonic, pager=self._pager,
                store_timeout_s=bounds.store_timeout_s, place_wait_s=bounds.place_wait_s,
                result_wait_s=bounds.result_wait_s, price_band=self._settings.oms_price_band_pct,
            )  # fmt: skip
            # `pg_stores`' one group adapter serves the system port and the scoped read alike.
            reader = TradeGroupReader(stores.groups)
            route = OrderRoute(accounts, ports.arm_records, submits, orders, reader, env, machines)
            exits = OrderExits(ExitDeps(
                machines=machines, commands=commands, orders=orders, stops=stops, audit=audit,
                instruments=instruments, profiles=profiles,
                stop_resolver=ports.stop_resolver, risk_gate=ports.risk_gate, validator=validator,
                switches=submits, oms_enabled=self._oms_enabled, environment=env,
            ))  # fmt: skip
            leverage = PositionLeverage(LeverageDeps(
                accounts=accounts, instruments=instruments, profiles=profiles,
                ports=router.port_for, switches=submits, audit=audit, environment=env,
            ))  # fmt: skip
            writes = PositionWrites(PositionWritesDeps(
                accounts=accounts, profiles=profiles, machines=machines, stops=stops,
                groups=stores.groups, ports=router.port_for, audit=audit, environment=env,
            ), monotonic=self._monotonic)  # fmt: skip
            self._phase = "audit_start"
            await writer.start()
            self._phase = "sink_start"
            await sink.start()
            closers.insert(3, ("sink", lambda: lane.call(sink.stop())))  # after the commands
            # its exits end before the facade stops
            closers.insert(0, ("exits", lambda: lane.call(exits.aclose())))
            # a full close's sweeps end before the exits, the facade and the trading port
            closers.insert(0, ("position_sweeps", lambda: lane.call(writes.aclose())))
            # S4-F: a fold's call still out once the machines have cut its members' invokes, as
            # theirs are, is ended before the trading port closes
            after = [name for name, _ in closers].index("machines") + 1
            closers.insert(after, ("cancel_all_folds", lambda: lane.call(folds.aclose())))
            self._phase = "heartbeat"  # rulings 2 and 3: the lane's tick and the lock's watchdog
            heartbeat = self._heartbeat(stores.lock, self._pager)
            beating = spawn(heartbeat.run(), name="oms-lane-heartbeat")
            beating.add_done_callback(functools.partial(_heartbeat_ended, self._pager))
            # it watches the lock until the lock's own closer, the last, releases it
            at_lock = [name for name, _ in closers].index("environment_lock")
            closers.insert(at_lock, ("heartbeat", lambda: lane.call(_cancelled(beating))))
            # E29-T13: scoped to the process's environment (C-2.11) through the OMS's own account
            # read, so a missing or deleted account, or another environment's, reads as no rows
            reads = None if published is None else TopicReads(
                orders, PositionRepository(positions, timer), fills, accounts=accounts,
                environment=env, clock=lane_clock,
            )  # fmt: skip
            parts = _Parts(
                submission, anchors, machines, tuple(closers), stops, audit, stores.sweep, route,
                gate, exits, lane, CancelAll(orders, exits, folds=(folds, accounts)), heartbeat,
                stream, admit_after, preview, leverage, writes, reads, observed,
            )  # fmt: skip
            with self._handoff:  # SEC-S3L2-05: the runtime's now, unless a stop began meanwhile
                stopping = self._stopping
                if not stopping:
                    self._parts = parts
            if stopping:  # closed below, as a cancelled composition is: none outlives the stop
                raise asyncio.CancelledError
        except BaseException:  # within the reserve less the join, as a cancelled start waits
            reserve = OMS_STOP_RESERVE_S - LANE_JOIN_S  # (ruling 6, SEC-S3L1CG-01)
            await _closed(closers, asyncio.get_running_loop().time() + reserve)
            raise
        return parts

    def _now_us(self) -> int:
        return (self._now() - _EPOCH) // _US


def _counter(metrics: Metrics, name: str) -> BoundedMetric:
    spec = next(spec for spec in CATALOGUE if spec.name == name)
    return metrics.counter(spec.name, spec.help, spec.labels, max_series=spec.max_series)


def _published(
    positions: PositionRepository, publisher: StepPublisher | None
) -> PositionRepository | PublishedPositions:
    """The consumer's position store: E29-T13's `PublishedPositions` over it when the topics are
    composed, so each applied row is published too; else the store itself."""
    return positions if publisher is None else PublishedPositions(positions, publisher)


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
    gate: OrderEntryCheck,
    standings: KeyStandingRead,
    oms_enabled: FlagRead,
    live_enabled: FlagRead,
    profiles: Profiles | None,
    persistence: Bundle | None,
    feed: MachineStatePort,
    lane_signing: LaneSigningBinder,
    health: StreamHealth,
    hub: SystemBroadcast,
    lane_transport: Callable[[], httpx.AsyncBaseTransport] | None = None,
    topics: AttachedTopics | None = None,
    trade_groups: GroupTopic | None = None,
    kill_switch: KillSwitch | None = None,
) -> OmsRuntime | None:
    """The process's OMS runtime, with no I/O; None on the fake backend, which composes no OMS, so
    `placeOrder` answers `501 not_implemented` there (20 Sec.6.2). Its audit writer is its order
    lane's own (#913 L2), never the serving loop's; `lane_signing` is M2's binder of the lane's own
    signing, and `lane_transport` the dev-only account fixture's lane transport, None in
    production (#913 L1d). `health` (the account health runtime) and `hub` (the gateway's) are
    what its private-stream consumer takes (E29-T05 S8b); `topics`, the gateway's `orders`,
    `executions` and `positions` topics, what its committed steps and position rows feed and its
    lane's snapshot reads serve (E29-T13); `trade_groups`, the topic it seeds and hands each
    committed group write to (E28-T05); `kill_switch`, the B18 port with the audit-chain break
    halt folded in (#2904), the one instance every reader of the port shares."""
    if settings.storage_backend != "real":
        return None
    return OmsRuntime(
        settings, venue=ctx.exchange_bybit, ingestion=ctx.ingestion,
        read_only=ctx.oms_read_only_gate, metrics=metrics, gate=gate,
        standings=standings, oms_enabled=oms_enabled, live_enabled=live_enabled,
        profiles=profiles, persistence=persistence, feed=feed, lane_signing=lane_signing,
        health=health, hub=hub, lane_transport=lane_transport, topics=topics,
        trade_groups=trade_groups, kill_switch=kill_switch,
    )  # fmt: skip
