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
import re
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, fields
from types import MappingProxyType
from typing import Any, ClassVar, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.accounts.verification import Refusal
from candleviewer.admin.wiring import keyed_record_id
from candleviewer.domain.events import Instrument
from candleviewer.domain.order_entry import OrderEntryCheck, OrderEntryRefusal
from candleviewer.domain.primitives import AccountId, Environment, Px, Symbol
from candleviewer.exchange.base.errors import AuthError, ExchangeError, OmsErrorCode
from candleviewer.exchange.base.models import AccountRef, TickerEvent
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.commands import NEVER_SENT_ALERT
from candleviewer.oms.errors import (
    AccountScopeDenied,
    OmsNotReady,
    OrderEntryRefused,
    StoreUnavailable,
    TradingDisabled,
)
from candleviewer.oms.order_machine import MAX_MACHINES, OrderAuditRecord, OrderNotice
from candleviewer.oms.ports import (
    ClockHealth,
    Interim,
    KeyedRecord,
    RequestRecord,
    RuntimePortName,
    SubmitActor,
    announce_interim_port,
)
from candleviewer.oms.submit import RESULT_WAIT_S, STORE_TIMEOUT_S
from candleviewer.settings import OMS_INFLIGHT_STUCK_MAX_S, Settings
from candleviewer.statechart.config import CV_COMMAND_TIMEOUT, CV_PERSIST_TIMEOUT
from candleviewer.statechart.plugins import LogPager, Pager
from candleviewer.statechart.plugins.state_feed import (
    FeedBinding,
    MachineStateHandle,
    MachineStatePort,
)
from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.orders import OrderStoreError
from candleviewer.storage.repositories.trading_accounts import (
    TradingAccountReads,
    TradingAccountRow,
)

#: The stop request's bound (21 Sec.3.3.11, [LANE-25]), in seconds: how long an unanswered stop
#: request holds its key before it waits for the complete read (`RefuseWhileWaiting`); above an
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
#: The alert the pager takes as a ticket, not a page: an order a restart found never sent.
_TICKETS: Final = frozenset({NEVER_SENT_ALERT})
#: The alerts an order raises, a closed set: the order machine's (`raise_unknown_alert`,
#: `raise_critical_alert` on `quarantined` and `held`, `raise_naked_position_alert`) and the one a
#: resumed create past its history raises (`oms.commands`). Only these are logged and paged by
#: name, so a value of any other source, a key among them, is never a name (SEC-S3C2-01, C-12.6).
ORDER_ALERTS: Final = frozenset(
    {"order_unknown", "order_quarantined", "order_held", "SL_ATTACH_FAILED", NEVER_SENT_ALERT}
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
    and a page until E29-T06 and E32 own them; `amend_rejected` is a log line. It logs the order's
    ids and the notice's names only, never a price, a size or a key (C-12.6): an alert is named
    only from `ORDER_ALERTS` and an amend's code from `OmsErrorCode`, else `unnamed`. It never
    raises: a notice it cannot route is a CRITICAL log and a page, whatever it was, and a failing
    pager is logged at CRITICAL."""

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
            log.error("oms_order_alert", alert=alert, **ids)
            self._raise("alert" if alert in _TICKETS else "page", f"order alert {alert}")
        elif kind in UNOWNED_NOTICES:
            owner = UNOWNED_NOTICES[kind]
            log.error("oms_order_notice_unowned", kind=kind, owner=owner, **ids)
            self._raise("page", f"order notice {kind} has no owner until {owner}")
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
