"""B1's OMS facade (E29-T03 #847): one `order` machine per order, built only through
`statechart.factory.build("order", lane="order")` and driven only through `statechart.gateway`.

Statecharts record; this synchronous code enforces (C-2.21), before any send:

* **Legality** is B1's static table (`Legality`, read from the committed chart, C-2.19). A command
  the order's state does not list raises `IllegalTransition`, and a `lifecycle` step that is not an
  edge of the chart is refused before its row is written (24-internal-schemas.md Sec.8.2 S8). A
  receipt is never the gate on a `defer` chart (CV-C06).
* **S5.** Fills are always applied (S4 dedupes them). An `orders`-topic push older than the last
  one the order took, or one its state has no arm for while no request is in flight, is ignored.
  A push that outruns the order waits in a bounded reorder buffer, released in `(ts_exec, seq)`
  order: an `EXEC` before the bind (SR-E29-03) and an exchange end before its fills (INV-B1-k).
* **S6.** A push for a final order raises `ReconcileAnomaly`, audited ahead as
  `oms.reconcile_anomaly` and counted, and changes nothing. A fill for a final or held machine is
  B1's to consume, which audits it and starts the stop (INV-B1-o); one for an evicted order hands
  the position to B8.
* **S9, SR-E29-12.** A rule, an algo or a group never acts on an `untracked` order, and only a
  user resolves a hold or adopts (D6). A chain-trip latched machine refuses order-path commands.

The binding's effects go through what this facade wires (`b01_order.set_ports`, `set_audit_hook`,
`set_fill_core`); its notices come back through the outbox (CV-C25), which the facade takes after
every committed step. The first fill starts the `protection` region (24 Sec.8.8 rule 2), a KILL
whose cancel did not end the order is sent again (INV-B1-h), a hostile `EXEC` quarantines it
(OM-T04), and the rest go to the notice port. Each step is published through the publish port with
the order's account as its scope (OM-I02, 23-ws-protocol.md Sec.6.4): the composition root
(E29-T04) wires it to `ws/machines.py`, so `oms` imports no `ws` (C-3.4). A machine is stopped and
evicted once its order is final and its stop settled (MUST-11).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol
from uuid import UUID

import structlog

from candleviewer.observability import spawn
from candleviewer.observability.metrics import BoundedMetric, Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.observability.tracing import span
from candleviewer.statechart import Registry, build
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.gateway import Gateway, GatewayError, receipt_is_conclusive
from candleviewer.statechart.persistence import ChainTripLatch, MachineKey
from candleviewer.statechart.plugins import MachineEventSink, Pager, cv_plugins
from candleviewer.statechart.plugins._base import LogPager
from candleviewer.storage.repositories.orders import ORDER_STATE_OF, NewOrder

from .errors import (
    POST_TERMINAL_PUSH,
    IllegalTransition,
    OrderBufferFull,
    OrderMachinesFull,
    OrderNotLoaded,
    OrderStepRefused,
    ReconcileAnomaly,
)
from .execution import apply_fields
from .order_steps import OrderStepWriter, event_kind
from .repository import OrderRepository

__all__ = [
    "B1_AUDITS",
    "MAX_HELD",
    "MAX_MACHINES",
    "Actor",
    "CommandEvent",
    "Legality",
    "MachinePublisher",
    "OrderAudit",
    "OrderAuditRecord",
    "OrderMachinePorts",
    "OrderMachines",
    "OrderNotice",
    "OrderNotices",
    "PushEvent",
]


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


MACHINE: Final = "order"
LANE: Final = "order"
#: Live order machines in this process (C-2.18): a full registry refuses a new order, as a live
#: machine is never evicted.
MAX_MACHINES: Final = 4096
#: Pushes one order's reorder buffer holds, and refusals it keeps (C-2.18); past it a push is
#: refused (`OrderBufferFull`).
MAX_HELD: Final = 256
#: Settle rounds per turn (C-2.18): each takes one notice, refusal, held push or KILL; the rest
#: waits for a turn the facade schedules.
SETTLE_ROUNDS: Final = 4 * MAX_HELD
#: Await each send's macrostep, so a step B1 rolled back reaches the caller (S7). Safe: the facade
#: sends from its own calls and tasks, never from a B1 action, so the CV-C51 self-receipt hang
#: cannot arise (as `rules.lifecycle` and `auth.session_chart` do).
_AWAIT_STEP: Final = True

Actor = Literal["user", "rule", "algo", "group", "system"]
CommandEvent = Literal[
    "SEND", "CANCEL", "AMEND", "OPERATOR_RESOLVED", "ADOPT", "TRANSPORT_FAULT", "MISMATCH",
    "RECON_FOUND_LIVE", "RECON_FOUND_PARTIAL", "RECON_FOUND_FILLED", "RECON_FOUND_CANCELLED",
    "RECON_MISS",
]  # fmt: skip
PushEvent = Literal[
    "EXEC", "TRIGGERED", "EXPIRE", "REMOTE_CANCELLED", "AMEND_REJECTED", "SL_OBSERVED", "SL_LOST",
    "SL_DEADLINE",
]  # fmt: skip
Outcome = Literal["success", "failure", "denied"]
Severity = Literal["info", "warning", "error", "critical"]
#: Command sources that never act on an `untracked` order (S9, SR-E29-12).
MANAGERS: Final = frozenset({"rule", "algo", "group"})
#: Commands only a user sends: the operator's decision on a hold, and an adoption (D6, E45-S01).
USER_ONLY: Final = frozenset({"OPERATOR_RESOLVED", "ADOPT"})
#: Order-path commands a chain-trip latched machine refuses (CV-C63, 23 Sec.6.4 `degraded`).
ORDER_PATH: Final = frozenset({"SEND", "CANCEL", "AMEND", "ADOPT"})
#: Protection facts: the region takes them while the machine lives; B8 holds the position after.
_PROTECTION: Final = frozenset({"SL_OBSERVED", "SL_LOST", "SL_DEADLINE"})
#: Exchange ends that wait until the order holds every fill they report (INV-B1-k).
_ENDS: Final = frozenset({"REMOTE_CANCELLED", "EXPIRE"})
#: B1's refusal arms: an event that reaches only one of them is not a transition of the state.
_REFUSALS: Final = frozenset({"audit_command_refused_unowned", "audit_operator_command_refused"})
#: The context keys the facade reads after each committed step: its plain view (C-2.20).
_VIEW: Final = (
    "order_link_id", "symbol", "exchange_order_id", "filled_qty", "halted_by_kill", "recon_misses",
)  # fmt: skip
_CHART_STATE_OF: Final = {stored: chart for chart, stored in ORDER_STATE_OF.items()}
ANOMALY: Final = "oms.reconcile_anomaly"

#: B1's audit records (`b01_order`'s hook names, catalogue B1.6) and the registered M19 action,
#: outcome and severity each is written under (C-2.9; SR-E29-17: never an unregistered action). A
#: KILL's records are its cancel of this order (`orders.cancel`, OM-R01), and a push the order did
#: not take is an anomaly (S6, OM-T04). The operator's resolution and an adoption are their routes'
#: records (E45-T03, E45-S01), and the legality check refuses the commands B1 would refuse, so
#: B1's own copies of those are logged only.
B1_AUDITS: Final[Mapping[str, tuple[str, Outcome, Severity]]] = MappingProxyType({
    "halted_by_kill": ("orders.cancel", "success", "warning"),
    "kill_cancel_in_flight": ("orders.cancel", "success", "warning"),
    "kill_protection_retained": ("orders.cancel", "success", "info"),
    "kill_no_cancel_unsubmitted": ("orders.cancel", "denied", "info"),
    "kill_no_cancel_unverified_duplicate": ("orders.cancel", "denied", "warning"),
    "kill_ignored_terminal": ("orders.cancel", "denied", "info"),
    "kill_ignored_unowned": ("orders.cancel", "denied", "warning"),
    "kill_cancel_timeout": ("orders.cancel", "failure", "error"),
    "kill_cancel_failed": ("orders.cancel", "failure", "error"),
    "kill_cancel_lost": ("orders.cancel", "failure", "error"),
    "guard_denied": (ANOMALY, "denied", "error"),
    "reconcile_anomaly": (ANOMALY, "denied", "error"),
})  # fmt: skip


@dataclass(frozen=True, slots=True)
class OrderAuditRecord:
    """One record the facade writes ahead (C-2.9). E29-T04 writes it through `AuditWriter.emit`
    as `system:oms`, with the order as its object; `detail` holds ids and state names, never
    values (C-12.6)."""

    action: str
    order_id: UUID
    account_id: UUID
    outcome: Outcome
    severity: Severity
    reason: str
    detail: Mapping[str, str | None]


@dataclass(frozen=True, slots=True)
class OrderNotice:
    """An outbox notice the facade hands on (CV-C25): `amend_rejected` (S2, for the UI), `alert`
    (the pager), `request_reconciliation` (E29-T06) and `request_fallback_sl` (B8, E32)."""

    kind: str
    order_id: UUID
    account_id: UUID
    order_link_id: str | None
    detail: Mapping[str, Any]


class OrderAudit(Protocol):
    """The audit writer E29-T04 wires: `write` makes the record durable, or raises (C-2.9)."""

    async def write(self, record: OrderAuditRecord) -> None: ...


class OrderNotices(Protocol):
    """Where E29-T04 routes the outbox's notices."""

    async def notify(self, notice: OrderNotice) -> None: ...


class MachinePublisher(Protocol):
    """`ws/machines.py`'s registry, as E29-T04 wires it (23 Sec.6.4): the order's
    `machines.order:{id}.state` payload, scoped to the account the facade names (OM-I02); `last`
    marks the entity's final one. Synchronous and non-blocking: a plugin hook calls it."""

    def publish(
        self, order_id: UUID, account_id: UUID, payload: Mapping[str, Any], *, last: bool
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class OrderMachinePorts:
    """What E29-T04's composition root wires into the facade."""

    steps: OrderStepWriter
    orders: OrderRepository
    commands: b01.CommandPort
    audit: OrderAudit
    publish: MachinePublisher
    notices: OrderNotices
    sink: MachineEventSink


def _arms(spec: object) -> list[Mapping[str, Any]]:
    items = spec if isinstance(spec, list) else [spec]
    return [arm if isinstance(arm, Mapping) else {"target": arm} for arm in items]


def _lifecycle_leaf(target: object) -> str | None:
    """`#order.lifecycle.held` -> `held`; a `protection` target, or none, is no lifecycle step."""
    head = "#order.lifecycle."
    return target[len(head) :] if isinstance(target, str) and target.startswith(head) else None


def _acts(arm: Mapping[str, Any]) -> bool:
    """An arm that moves the order or records more than B1's refusal of the event."""
    return _lifecycle_leaf(arm.get("target")) is not None or not set(arm.get("actions") or ()) <= (
        _REFUSALS
    )


@dataclass(frozen=True, slots=True)
class Legality:
    """B1's static table, read from the committed chart (C-2.19): the `lifecycle` edges a step may
    commit (24 Sec.8.2's diagram, the KILL note's arms included), the events each state has an arm
    for that is not a refusal, the final states, and the states with a request in flight, which
    defer what they do not handle (24 Sec.8.2 S10)."""

    edges: frozenset[tuple[str, str]]
    handled: Mapping[str, frozenset[str]]
    finals: frozenset[str]
    in_flight: frozenset[str]

    @classmethod
    def of(cls, chart: Mapping[str, Any]) -> Legality:
        region = chart["states"]["lifecycle"]
        shared: Mapping[str, Any] = region.get("on") or {}
        edges: set[tuple[str, str]] = set()
        handled: dict[str, frozenset[str]] = {}
        for name, node in region["states"].items():
            # A state's own arms shadow the region's: every guarded B1 group ends unguarded.
            groups = {
                event: _arms(spec) for event, spec in {**shared, **(node.get("on") or {})}.items()
            }
            invoke = node.get("invoke") or {}
            results = [arm for key in ("onDone", "onError") for arm in _arms(invoke.get(key, []))]
            for arm in [*results, *(arm for group in groups.values() for arm in group)]:
                if (target := _lifecycle_leaf(arm.get("target"))) is not None:
                    edges.add((name, target))
            handled[name] = frozenset(e for e, group in groups.items() if any(map(_acts, group)))
        states = region["states"]
        return cls(
            edges=frozenset(edges),
            handled=MappingProxyType(handled),
            finals=frozenset(n for n, node in states.items() if node.get("type") == "final"),
            in_flight=frozenset(n for n, node in states.items() if "invoke" in node),
        )

    def require_edge(self, source: str, target: str) -> None:
        """`IllegalTransition` unless B1 lists a step from *source* into *target*."""
        if (source, target) not in self.edges:
            raise IllegalTransition(source, target)

    def require(self, state: str, event: str) -> None:
        """`IllegalTransition` unless *state* has an arm for *event* that is not a refusal."""
        if event not in self.handled.get(state, frozenset()):
            raise IllegalTransition(state, event)


def _int(raw: object) -> int:
    return raw if type(raw) is int else 0


def _uuid(raw: object) -> UUID | None:
    try:
        return UUID(str(raw))
    except ValueError:
        return None


def _decimal_text(value: Decimal) -> str:
    """Canonical decimal text, as `b01_order` keeps money: fixed point, no trailing zeros."""
    out = format(value, "f")
    return out.rstrip("0").rstrip(".") if "." in out else out


def _order_fields(order: NewOrder) -> dict[str, Any]:
    """The order as B1's `VALIDATE` and `DISCOVERED` name it (24 Sec.8.1), from the order the step
    writer stores, so the two agree field for field (`order_steps`, SR-E29-03)."""
    terms = {key: getattr(order, key) for key in ("qty", *b01.TERMS)}
    return {
        "order_id": str(order.id),
        "order_link_id": order.order_link_id,
        "account_id": str(order.exchange_account_id),
        "symbol": order.symbol,
        "side": order.side.lower(),
        "reduce_only": order.reduce_only,
        **{key: None if value is None else _decimal_text(value) for key, value in terms.items()},
    }


def _leaves(interp: Any) -> dict[str, str]:
    """`{region: leaf}` of the active configuration (`order.<region>.<leaf>`)."""
    parts = (str(state_id).split(".") for state_id in interp.current_state_ids)
    return {p[1]: p[2] for p in parts if len(p) == 3}


def _outruns(push: Mapping[str, Any], filled: object) -> bool:
    """INV-B1-k: an exchange end that reports more filled than the order holds is early."""
    try:
        return Decimal(str(push["cum_exec_qty"])) > Decimal(str(filled or "0"))
    except (KeyError, InvalidOperation):
        return False


def _summary(view: Mapping[str, Any]) -> dict[str, Any]:
    """23 Sec.6.4's `context_summary` for `order`: `symbol`, `halted_by_kill`, `recon_misses`."""
    summary = {
        "symbol": view.get("symbol"),
        "halted_by_kill": view.get("halted_by_kill") is True,
        "recon_misses": _int(view.get("recon_misses")),
    }
    return {key: value for key, value in summary.items() if value is not None}


@dataclass(eq=False, slots=True)
class _Order:
    """One live order machine and the plain view its committed steps leave (C-2.20): the facade
    decides from this, never by querying the interpreter."""

    order_id: UUID
    account_id: UUID
    environment: str
    interp: Any = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    #: The facade holds `lock`, and settles before it lets go.
    busy: bool = False
    lifecycle: str = "draft"
    protection: str = "not_required"
    view: dict[str, Any] = field(default_factory=dict)
    steps: int = 0
    #: The `seq` of the last outbox notice taken.
    cursor: int = -1
    notices: deque[dict[str, Any]] = field(default_factory=deque)
    #: The reorder buffer: `((ts_exec, seq), event, payload)`.
    held: list[tuple[tuple[int, int], str, dict[str, Any]]] = field(default_factory=list)
    #: S5: the exchange time of the newest `orders`-topic push the order took.
    last_update_ms: int = -1
    #: `exec_id` -> why B1 refused that EXEC, for the facade's answer (`_answer`).
    denied: OrderedDict[str, str] = field(default_factory=OrderedDict)
    #: The step count a lost KILL was last sent again at.
    kill_sent_at: int = -1
    published: dict[str, Any] | None = None
    task: asyncio.Task[None] | None = None

    @property
    def key(self) -> str:
        return str(self.order_id)


class _Observer:
    """The facade's plugin, duck-typed (only the factory imports the runtime, CV-LINT-IMPORT): its
    `on_transition` runs once a step has committed, and never for a rolled-back one."""

    __slots__ = ("_order", "_stepped")

    def __init__(self, stepped: Callable[[_Order, Any], None], order: _Order) -> None:
        self._stepped = stepped
        self._order = order

    def on_transition(self, interpreter: Any, *_transition: Any) -> None:
        self._stepped(self._order, interpreter)


class OrderMachines:
    """B1's OMS facade: one per process, as it wires the binding's process-wide ports, which
    `stop()` unwires. Every send to an order runs under that order's lock (a keyed
    `asyncio.Lock`), so an order's commands, pushes and turns never interleave; orders run
    concurrently."""

    def __init__(
        self,
        ports: OrderMachinePorts,
        *,
        metrics: Metrics,
        pager: Pager | None = None,
        latch: ChainTripLatch | None = None,
        now_us: Callable[[], int],
        registry: Registry | None = None,
        max_machines: int = MAX_MACHINES,
    ) -> None:
        self._ports = ports
        self._metrics = metrics
        self._pager: Pager = pager if pager is not None else LogPager()
        self._latch = latch if latch is not None else ChainTripLatch()
        self._registry = registry if registry is not None else Registry()
        self.legality = Legality.of(self._registry.get(MACHINE))
        self._killable = frozenset(s for s, target in self.legality.edges if target == "killed")
        self._hash = self._registry.hash(MACHINE)
        self._now_us = now_us
        self._max = max_machines
        self._gateway = Gateway(pager=self._pager)
        self._orders: dict[UUID, _Order] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        specs = {spec.name: spec for spec in CATALOGUE}

        def counter(name: str) -> BoundedMetric:
            spec = specs[name]
            return metrics.counter(name, spec.help, spec.labels, max_series=spec.max_series)

        self._transitions = counter("oms_state_transitions_total")
        self._illegal = counter("oms_illegal_transitions_total").child()
        self._anomalies = counter("oms_reconcile_anomaly_total").child()
        b01.set_ports(b01.OrderPorts(persist=self._persist, commands=ports.commands, now_us=now_us))
        b01.set_audit_hook(self._audited)
        b01.set_fill_core(apply_fields)

    # --- The API -------------------------------------------------------------------------------

    def state(self, order_id: UUID) -> tuple[str, str] | None:
        """The order's `lifecycle` and `protection` states after its last committed step, while
        its machine lives."""
        o = self._orders.get(order_id)
        return None if o is None else (o.lifecycle, o.protection)

    async def start(
        self,
        order: NewOrder,
        *,
        environment: str,
        gates: Mapping[str, str],
        rate_reservation: str | None = None,
    ) -> str:
        """E29-T04's pipeline, once its synchronous gates ran (C-2.21): build the order's machine
        and record `VALIDATE` with their verdicts. The order's first row is written at `validated`
        (24 Sec.8.4), or none when a verdict refused it. Answers the lifecycle state."""
        payload: dict[str, Any] = {"gates": dict(gates), "order": _order_fields(order)}
        if rate_reservation is not None:
            payload["rate_reservation"] = rate_reservation
        attrs = {"order_link_id": order.order_link_id, "symbol": order.symbol, "env": environment}
        with span("oms.validate", attrs):
            return await self._first(order, environment, "VALIDATE", payload)

    async def discover(
        self, order: NewOrder, *, environment: str, pass_id: str | None = None
    ) -> str:
        """E29-T06's reconciler found an exchange order with no local row (24 Sec.8.5 step 3c):
        build its machine and record `DISCOVERED`, which writes its `untracked` row (S9)."""
        fields = _order_fields(order) | {"exchange_order_id": order.exchange_order_id}
        payload = {"order": fields} | ({} if pass_id is None else {"pass_id": pass_id})
        return await self._first(order, environment, "DISCOVERED", payload)

    async def command(
        self,
        account_id: UUID,
        order_id: UUID,
        event: CommandEvent,
        payload: Mapping[str, Any] | None = None,
        *,
        actor: Actor,
    ) -> str:
        """A command to the order, from a route, a rule, an algo or E29-T06's reconciler. Refused
        with `IllegalTransition` unless its state lists it and its source may send it (S9), and
        with `DegradedLatchError` on a latched machine; else sent, answering the lifecycle state
        once the step settled. `OrderStepRefused` when B1 rolled the step back (S7)."""
        o = self._live(account_id, order_id)
        if o is not None:
            async with self._holding(o):
                if o.interp is not None:
                    self._admit(o, event, actor)
                    await self._send_order(o, event, payload or {})
                    await self._settle(o)
                    return o.lifecycle
        state = await self._stored(account_id, order_id)
        if state is not None and state in self.legality.finals:
            raise self._refuse(state, event)
        raise OrderNotLoaded("no machine in this process holds the order")

    async def push(
        self, account_id: UUID, order_id: UUID, event: PushEvent, payload: Mapping[str, Any]
    ) -> None:
        """An exchange fact for the order: E29-T05's private stream, B8's position reads, or the
        scheduler's `SL_DEADLINE`, taken in S5 order. `ReconcileAnomaly` for a push the order
        cannot take (S6), raised once its record is written; `OrderBufferFull` when it would wait
        in a full reorder buffer; `OrderStepRefused` when B1 rolled its step back (S7)."""
        o = self._live(account_id, order_id)
        if o is not None:
            async with self._holding(o):
                if o.interp is not None:
                    anomaly = await self._take(o, event, dict(payload))
                    await self._settle(o)
                    if anomaly:
                        raise ReconcileAnomaly(o.lifecycle, event)
                    return
        await self._unloaded(account_id, order_id, event, payload)

    async def kill(self, reason: str, *, account_id: UUID | None = None) -> tuple[UUID, ...]:
        """B18's kill switch, recorded on every live machine (of *account_id*, if given) once it
        is enforced synchronously (C-2.21): each order reaches `killed` and cancels at most once
        (INV-B1-h). Answers the orders whose KILL did not commit, each logged and paged. A reason
        B1's schema refuses is refused before any order is touched, never halfway through."""
        if not 0 < len(reason) <= b01.MAX_TEXT:
            raise ValueError(f"a KILL reason is 1 to {b01.MAX_TEXT} characters")
        failed: list[UUID] = []
        for o in [o for o in self._orders.values() if account_id in (None, o.account_id)]:
            async with self._holding(o):
                if o.interp is None:
                    continue
                try:
                    await self._kill(o, reason)
                except (OrderStepRefused, GatewayError) as exc:
                    failed.append(o.order_id)
                    self._page("oms_kill_not_recorded", o, error=type(exc).__name__)
                await self._settle(o)
        return tuple(failed)

    async def idle(self) -> None:
        """Until no turn is pending (the composition root's shutdown, and tests). It waits on the
        pending ones only: `gather` over done tasks completes without yielding to the loop."""
        while pending := [task for task in self._tasks if not task.done()]:
            await asyncio.wait(pending)

    async def stop(self) -> None:
        """Shutdown: the turns end, every machine stops, and the binding is unwired. Each order
        recovers from its `order_events` on the next start (A7)."""
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)
        for o in list(self._orders.values()):
            await self._close(o, publish=False)
        b01.set_ports(None)
        b01.set_audit_hook(None)
        b01.set_fill_core(None)

    # --- Build, lookup and eviction (C-2.18, MUST-11, OM-I02) -----------------------------------

    async def _first(
        self, order: NewOrder, environment: str, event: str, payload: Mapping[str, Any]
    ) -> str:
        """Build the order's machine and send its first event. A machine whose first step was
        refused is dropped again, so a refused order leaves nothing behind (S7)."""
        o = await self._open(order, environment, event)
        self._ports.steps.expect(order)
        try:
            async with self._holding(o):
                await self._send_order(o, event, payload)
                await self._settle(o)
                return o.lifecycle
        except BaseException:
            await self._close(o, publish=False)
            raise

    async def _open(self, order: NewOrder, environment: str, event: str) -> _Order:
        """The order's machine, with the plugin triple, which writes ahead on the order lane (24
        Sec.17.6), and the facade's observer. Its scope is the stored order's account (OM-I02)."""
        if (known := self._orders.get(order.id)) is not None:
            raise self._refuse(known.lifecycle, event)
        if len(self._orders) >= self._max:
            raise OrderMachinesFull(f"{self._max} order machines are live")
        o = _Order(order.id, order.exchange_account_id, environment)
        self._orders[order.id] = o
        triple = cv_plugins(
            machine_kind=MACHINE,
            lane=LANE,
            entity_id=o.key,
            env=environment,
            metrics=self._metrics,
            sink=self._ports.sink,
            pager=self._pager,
        )
        # The plugins are duck-typed (CV-LINT-IMPORT): `build` takes them as the runtime's base.
        plugins: tuple[Any, ...] = (*triple, _Observer(self._stepped, o))
        try:
            built = await build(
                MACHINE, clock=default_clock(), lane=LANE, plugins=plugins, registry=self._registry
            )
        except BaseException:
            del self._orders[order.id]
            raise
        o.interp = built.interpreter
        self._gateway.register(o.key, o.interp, kind="order", lane=LANE, metrics=triple[1])
        return o

    async def _close(self, o: _Order, *, publish: bool) -> None:
        """Stop and evict the order's machine; with *publish*, its last payload is the entity's
        final one (23 Sec.6.4)."""
        interp, o.interp = o.interp, None
        self._gateway.unregister(o.key)
        self._orders.pop(o.order_id, None)
        if interp is not None:
            if publish:
                self._publish(o, interp, last=True)
            await interp.stop()

    def _live(self, account_id: UUID, order_id: UUID) -> _Order | None:
        """The order's live machine, if the account holds it: another account's order is not
        found, as an unknown one is (no oracle, C-12.4)."""
        o = self._orders.get(order_id)
        return o if o is not None and o.account_id == account_id else None

    async def _stored(self, account_id: UUID, order_id: UUID) -> str | None:
        row = await self._ports.orders.get(account_id, order_id)
        return None if row is None else row.lifecycle_state or _CHART_STATE_OF.get(row.state)

    async def _unloaded(
        self, account_id: UUID, order_id: UUID, event: str, payload: Mapping[str, Any]
    ) -> None:
        """A push for an order with no machine here. A protection fact is B8's once the order's
        machine is gone; for a final order the push is an anomaly (S6), and a fill also hands the
        position to B8, as no machine can start its stop."""
        if event in _PROTECTION:
            return
        state = await self._stored(account_id, order_id)
        if state is None or state not in self.legality.finals:
            raise OrderNotLoaded("no machine in this process holds the order")
        await self._anomaly(order_id, account_id, state, event, payload)
        if event == "EXEC":
            notice = OrderNotice("request_fallback_sl", order_id, account_id, None, {})
            await self._notify(notice)
        raise ReconcileAnomaly(state, event)

    # --- Gates, sends and pushes (C-2.21, S5, S6, S9) -------------------------------------------

    def _admit(self, o: _Order, event: str, actor: Actor) -> None:
        """The synchronous gates of a command, before any send: the chain-trip latch (CV-C63), S9
        and SR-E29-12, and legality."""
        if event in ORDER_PATH:
            key = MachineKey(MACHINE, o.key, o.environment)
            if getattr(o.interp, "chain_trips", 0) and not self._latch.is_latched(key):
                self._latch.latch(key, "chain_trips")
            self._latch.admit_command(key)
        unowned = o.lifecycle == "untracked" and actor in MANAGERS
        if unowned or (event in USER_ONLY and actor != "user"):
            raise self._refuse(o.lifecycle, event)
        try:
            self.legality.require(o.lifecycle, event)
        except IllegalTransition:
            raise self._refuse(o.lifecycle, event) from None

    def _refuse(self, state: str, attempted: str) -> IllegalTransition:
        """`ILLEGAL_TRANSITION`, counted and logged: nothing was sent or written."""
        self._illegal.inc()
        logger().warning("oms_illegal_transition", state=state, attempted=attempted)
        return IllegalTransition(state, attempted)

    @contextlib.asynccontextmanager
    async def _holding(self, o: _Order) -> AsyncIterator[None]:
        """The order's lock; its holder settles the order before it lets go."""
        async with o.lock:
            o.busy = True
            try:
                yield
            finally:
                o.busy = False

    async def _send_order(self, o: _Order, event: str, payload: Mapping[str, Any]) -> None:
        """Through the gateway, the only send path (E50-T15). A step B1 rolled back raises
        `OrderStepRefused`; a deferred one is no error (S10), and no receipt is a gate (CV-C06)."""
        receipt = await self._gateway.send(o.key, {"type": event, **payload}, wait=_AWAIT_STEP)
        if receipt_is_conclusive(receipt) and receipt.error is not None:
            raise OrderStepRefused(event, type(receipt.error).__name__)

    async def _take(self, o: _Order, event: str, push: dict[str, Any]) -> bool:
        """S5 and S6 for one push to a live machine; True when the push is an S6 anomaly."""
        final = o.lifecycle in self.legality.finals
        if event in _PROTECTION:
            await self._send_order(o, event, push)
            return False
        if event == "EXEC":
            if final or o.lifecycle == "held":  # B1 audits it and starts the stop (INV-B1-o)
                await self._send_order(o, event, push)
                return True
            if o.view.get("exchange_order_id") is None and o.lifecycle != "untracked":
                self._hold(o, event, push)  # it waits for the bind (SR-E29-03)
                return False
            attrs = {"order_link_id": o.view.get("order_link_id"), "symbol": o.view.get("symbol")}
            with span("private_ws.fill", attrs):
                await self._send_order(o, event, push)
            return False
        if final:
            await self._anomaly(o.order_id, o.account_id, o.lifecycle, event, push)
            return True
        stamp = push.get("updated_time")
        stale = type(stamp) is int and stamp < o.last_update_ms
        unlisted = event not in self.legality.handled.get(o.lifecycle, frozenset())
        if stale or (unlisted and o.lifecycle not in self.legality.in_flight):
            logger().info("oms_push_ignored", state=o.lifecycle, trigger=event, stale=stale)
            return False
        if event in _ENDS and _outruns(push, o.view.get("filled_qty")):
            self._hold(o, event, push)  # it waits for the fills it reports (INV-B1-k)
            return False
        if type(stamp) is int:
            o.last_update_ms = stamp
        await self._send_order(o, event, push)
        return False

    def _hold(self, o: _Order, event: str, push: dict[str, Any]) -> None:
        if len(o.held) >= MAX_HELD:
            raise OrderBufferFull(f"the order holds {MAX_HELD} pushes")
        if event == "EXEC":
            key = (_int(push.get("ts_exec")), _int(push.get("seq")))
        else:
            key = (_int(push.get("updated_time")) * 1_000, 0)
        o.held.append((key, event, push))
        o.held.sort(key=lambda item: item[0])

    def _due(self, o: _Order) -> tuple[str, dict[str, Any]] | None:
        """The first held push, in `(ts_exec, seq)` order, that the order can take now: a fill
        once the order is bound (or held, untracked or final), an end once it holds the fills it
        reports (or is final)."""
        final = o.lifecycle in self.legality.finals
        unowned = o.lifecycle in ("held", "untracked")
        bound = o.view.get("exchange_order_id") is not None
        for index, (_key, event, push) in enumerate(o.held):
            fill = event == "EXEC" and (bound or unowned)
            end = event in _ENDS and not _outruns(push, o.view.get("filled_qty"))
            if final or fill or end:
                del o.held[index]
                return event, push
        return None

    # --- Settling: the notices, refusals, held pushes and a lost KILL (CV-C25) -----------------

    async def _settle(self, o: _Order) -> None:
        """After the order's steps, under its lock: act on their notices and refusals, release
        the held pushes the order can take now, send a lost KILL again, then evict the machine if
        the order is done. This is a turn's boundary: a failure stops the turn, logged, and the
        next step brings another (C-2.18 bounds the rounds of one turn)."""
        for _ in range(SETTLE_ROUNDS):
            if o.interp is None:
                return
            try:
                if not await self._settle_one(o):
                    return
            except Exception as exc:  # the turn's boundary: logged, and the next step retries
                link = o.view.get("order_link_id")
                logger().error("oms_settle_stopped", order_link_id=link, error=type(exc).__name__)
                return
        self._schedule(o)

    async def _settle_one(self, o: _Order) -> bool:
        """One round; False once nothing is left to do."""
        if o.notices:
            await self._act(o, o.notices.popleft())
        elif o.denied:
            await self._answer(o, *o.denied.popitem(last=False))
        elif (due := self._due(o)) is not None:
            event, push = due
            try:
                await self._take(o, event, push)
            except OrderStepRefused:
                self._hold(o, event, push)  # it waits for the next turn, as delivered
                raise
        elif self._kill_lost(o):
            await self._resend_kill(o)
        elif self._done(o):
            await self._close(o, publish=True)
            return False
        else:
            return False
        return True

    async def _act(self, o: _Order, notice: dict[str, Any]) -> None:
        """One outbox notice: the first fill starts the stop (24 Sec.8.8 rule 2; the region takes a
        repeat as a no-op); `terminal` needs no hand-off, as the step that ended the order is
        published; anything else goes to the notice port."""
        kind = str(notice.get("kind"))
        if kind == "first_fill":
            await self._send_order(o, "FIRST_FILL", {})
        elif kind != "terminal":
            detail = {key: value for key, value in notice.items() if key not in ("seq", "kind")}
            link = o.view.get("order_link_id")
            await self._notify(OrderNotice(kind, o.order_id, o.account_id, link, detail))

    async def _answer(self, o: _Order, exec_id: str, reason: str) -> None:
        """An EXEC B1 refused that is neither a repeat (S4) nor early (before the bind) is hostile
        (OM-T04): the order is quarantined where its state lists `FAULT`, else it pages."""
        if reason in (b01.REPEAT, b01.UNBOUND):
            return
        if "FAULT" in self.legality.handled.get(o.lifecycle, frozenset()):
            fault = {"reason": "OM-T04"} | ({"exec_id": exec_id} if exec_id else {})
            await self._send_order(o, "FAULT", fault)
        else:
            self._page("oms_hostile_exec_not_quarantined", o, state=o.lifecycle)

    def _kill_lost(self, o: _Order) -> bool:
        """INV-B1-h: a halted order is live again (a fill, a refused cancel or a transport fault
        took it out of `cancel_pending`), so the KILL that reused that cancel cancelled nothing."""
        halted = o.view.get("halted_by_kill") is True
        return halted and o.lifecycle in self._killable and o.kill_sent_at != o.steps

    async def _resend_kill(self, o: _Order) -> None:
        """Sends KILL again, once per committed step: the order reaches `killed`, whose entry
        cancels it through the audited cancel service (SR-E29-06)."""
        o.kill_sent_at = o.steps
        logger().error("oms_kill_resent", order_link_id=o.view.get("order_link_id"))
        await self._record(o, "kill_cancel_lost", {"state": o.lifecycle})
        await self._kill(o, "kill_cancel_lost")

    async def _kill(self, o: _Order, reason: str) -> None:
        """KILL. Both regions take it, so where B1 lists it into `killed` the configuration, not
        the receipt, proves it committed: the receipt can read clean when the `lifecycle` step
        rolled back and the `protection` audit did not (CV-C06)."""
        await self._send_order(o, "KILL", {"reason": reason})
        if o.lifecycle in self._killable:
            raise OrderStepRefused("KILL", "the lifecycle step was rolled back")

    def _done(self, o: _Order) -> bool:
        """MUST-11: final, its stop settled (no attach in flight) and nothing left to act on."""
        final = o.lifecycle in self.legality.finals and o.protection != "sl_pending"
        return final and not (o.notices or o.denied or o.held)

    # --- The observer: every committed step (C-2.20, CV-C02, OM-I02) -----------------------------

    def _stepped(self, o: _Order, interp: Any) -> None:
        """A step committed (a rolled-back one never gets here, so its notices never do, CV-C02):
        the plain view, the outbox's new notices, the publish and, unless the facade holds the
        order, a turn. The taken notices leave the outbox; its newest stays, as the next
        notice's `seq` follows it."""
        ctx = interp.context
        leaves = _leaves(interp)
        o.lifecycle = leaves.get("lifecycle", o.lifecycle)
        o.protection = leaves.get("protection", o.protection)
        o.view = {key: ctx.get(key) for key in _VIEW}
        o.steps += 1
        raw = ctx.get("outbox")
        box = [dict(n) for n in raw if isinstance(n, Mapping)] if isinstance(raw, list) else []
        fresh = [n for n in box if type(n.get("seq")) is int and n["seq"] > o.cursor]
        if fresh:
            o.notices.extend(fresh)
            o.cursor = fresh[-1]["seq"]
        if len(box) > 1:
            ctx["outbox"] = box[-1:]
        self._publish(o, interp)
        if not o.busy and (o.notices or o.denied or o.held or self._kill_lost(o) or self._done(o)):
            self._schedule(o)

    def _schedule(self, o: _Order) -> None:
        current = asyncio.current_task()
        if o.task is None or o.task.done() or o.task is current:
            task = spawn(self._turn(o), name="oms-order-turn")
            o.task = task
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _turn(self, o: _Order) -> None:
        """A turn for steps no caller drove (an invoke's answer): it settles the order, and as
        `_settle` is its boundary it never fails."""
        async with self._holding(o):
            await self._settle(o)

    def _publish(self, o: _Order, interp: Any, *, last: bool = False) -> None:
        """23 Sec.6.4: the order's `MachineStateUpdate`, scoped to its account (OM-I02). An
        unchanged one is not published again; the entity's last is marked."""
        view = {
            "machine_kind": MACHINE,
            "state": o.lifecycle,
            "regions": {"lifecycle": o.lifecycle, "protection": o.protection},
            "tags": sorted(interp.tags),
            "degraded": bool(getattr(interp, "chain_trips", 0)),
            "machine_hash": self._hash,
            "environment": o.environment,
            "context_summary": _summary(o.view),
        }
        if view == o.published and not last:
            return
        o.published = view
        payload = view | {"updated_at_ms": self._now_us() // 1_000}
        try:
            self._ports.publish.publish(o.order_id, o.account_id, payload, last=last)
        except Exception as exc:  # the step stands; a refused publish is logged, as the registry's
            logger().error("oms_publish_failed", error=type(exc).__name__)

    # --- The binding's ports: the write-ahead step and the audit hook (S8, C-2.9) ----------------

    async def _persist(self, step: b01.Step) -> int:
        """B1's persist port: a step that is not an edge of the chart is refused before its row is
        written (C-2.19, S8), which rolls it back; a committed one is counted."""
        source = step.from_state or "draft"
        if (source, step.to_state) not in self.legality.edges:
            raise self._refuse(source, step.to_state)
        seq = await self._ports.steps(step)
        self._transitions.labels(source, step.to_state, event_kind(step)[1]).inc()
        return seq

    async def _audited(self, name: str, context: dict[str, Any]) -> None:
        """B1's audit hook: one of its records, written ahead under `B1_AUDITS` (C-2.9). A refused
        EXEC's reason is kept for `_answer`; a repeat (S4) and an early fill are not anomalies.
        It never raises (a rollback would undo a KILL): a lost record pages."""
        order_id = _uuid(context.get("order_id"))
        o = None if order_id is None else self._orders.get(order_id)
        denied = context.get("denied")
        reason = str(denied.get("reason") or "") if isinstance(denied, Mapping) else ""
        if o is not None and name == "guard_denied" and isinstance(denied, Mapping):
            o.denied[str(denied.get("exec_id") or "")] = reason
            while len(o.denied) > MAX_HELD:
                o.denied.popitem(last=False)
        if name == "guard_denied" and reason in (b01.REPEAT, b01.UNBOUND):
            return
        if o is None or name not in B1_AUDITS:
            logger().info("oms_b1_record", record=name)
            return
        detail: dict[str, str | None] = {"state": o.lifecycle, "exec_id": None, "trigger": None}
        for key in ("anomaly", "denied"):
            extra = context.get(key)
            if isinstance(extra, Mapping):
                detail |= {k: str(v) for k, v in extra.items() if k in detail and v is not None}
        if reason:
            detail["refusal"] = reason
        await self._record(o, name, detail)

    async def _record(self, o: _Order, name: str, detail: Mapping[str, str | None]) -> None:
        action, outcome, severity = B1_AUDITS[name]
        if action == ANOMALY:
            self._anomalies.inc()
        fields = {"order_link_id": o.view.get("order_link_id"), **detail}
        record = OrderAuditRecord(action, o.order_id, o.account_id, outcome, severity, name, fields)
        try:
            await self._ports.audit.write(record)
        except Exception as exc:  # B1's hook must not raise: the record is lost, so it pages
            self._page("oms_audit_record_lost", o, record=name, error=type(exc).__name__)

    async def _anomaly(
        self,
        order_id: UUID,
        account_id: UUID,
        state: str,
        event: str,
        push: Mapping[str, Any],
    ) -> None:
        """S6, the facade's own record: counted, logged and written ahead of the refusal; a record
        that cannot be written raises (C-2.9)."""
        self._anomalies.inc()
        exec_id = push.get("exec_id")
        detail = {
            "state": state,
            "trigger": event,
            "exec_id": exec_id if isinstance(exec_id, str) else None,
        }
        logger().error("oms_reconcile_anomaly", **detail)
        record = OrderAuditRecord(
            ANOMALY, order_id, account_id, "denied", "error", POST_TERMINAL_PUSH, detail
        )
        await self._ports.audit.write(record)

    async def _notify(self, notice: OrderNotice) -> None:
        try:
            await self._ports.notices.notify(notice)
        except Exception as exc:  # the step that posted it stands: a lost notice pages
            logger().critical("oms_notice_lost", kind=notice.kind, error=type(exc).__name__)
            self._pager.raise_alert(
                "page", f"order notice lost: {notice.kind}", machine_kind=MACHINE
            )

    def _page(self, event: str, o: _Order, **detail: str) -> None:
        logger().critical(event, order_link_id=o.view.get("order_link_id"), **detail)
        self._pager.raise_alert("page", event, machine_kind=MACHINE)
