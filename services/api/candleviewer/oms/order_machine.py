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
  A release the store refuses for the push's own data leaves the buffer, a fill answered as a
  hostile one; one a store failure refuses waits for a later turn, `MAX_RELEASES` times at most.
* **S6.** A push for a final order raises `ReconcileAnomaly`, audited ahead as
  `oms.reconcile_anomaly` and counted, and changes nothing. A fill for a final or held machine is
  B1's to consume, which audits it and starts the stop (INV-B1-o); one for an evicted order hands
  the position to B8.
* **S9, SR-E29-12.** A rule, an algo or a group never acts on an `untracked` order, only a user
  resolves a hold or adopts (D6), and only the system reports what reconciliation found or a
  transport fault. A chain-trip latched machine refuses order-path commands.
  `command` and `push` take only their own event names, and no payload names its own `type`, so
  no gate is skipped by an event it was not written for.
* **S7, an unknown outcome.** A step whose write did not answer in time may still have committed,
  and a write that meets a row that moved on finds the machine behind its row: B1 rolls the step
  back either way, so the facade pages and rebuilds the machine from the order's events (`_resync`,
  as `hydrate` does), where the row decides, and the caller gets `OrderStepUnknown`. A caller that
  waited on the order meanwhile, a KILL included, follows it to the rebuilt machine.
* **Recovery (A7).** After a restart, `hydrate` rebuilds an order from its `order_events`, checks
  the fold against its row (OM-T03) and replays the recorded steps on a fresh machine, writing,
  auditing, notifying and sending nothing for them (24 Sec.8.2 "Recovery", `oms.recovery`).

The binding's effects go through what this facade wires (`b01_order.set_ports`, `set_audit_hook`,
`set_fill_core`); its notices come back through the outbox (CV-C25), which the facade takes after
every committed step, each removed once acted on, so a failed one is tried again. The first fill
starts the `protection` region (24 Sec.8.8 rule 2), a KILL whose cancel did not end the order is
sent again (INV-B1-h), a hostile `EXEC` quarantines it (OM-T04), and the rest go to the notice
port. Each step is published through the publish port with the order's account as its scope
(OM-I02, 23-ws-protocol.md Sec.6.4): the composition root (E29-T04) wires it to `ws/machines.py`,
so `oms` imports no `ws` (C-3.4). A machine is stopped and evicted once its order is final and
its stop settled (MUST-11). The audit, notice and read ports are awaited within `PORT_TIMEOUT`,
as an order's lock is held meanwhile.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import OrderedDict, deque
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol, get_args
from uuid import UUID

import structlog

from candleviewer.observability import spawn
from candleviewer.observability.metrics import BoundedMetric, Metrics
from candleviewer.observability.metrics_catalogue import CATALOGUE
from candleviewer.observability.tracing import span
from candleviewer.statechart import Registry, build
from candleviewer.statechart.bindings import b01_order as b01
from candleviewer.statechart.factory import default_clock
from candleviewer.statechart.gateway import (
    ALWAYS_ADMIT,
    Gateway,
    GatewayError,
    receipt_is_conclusive,
)
from candleviewer.statechart.persistence import ChainTripLatch, MachineKey
from candleviewer.statechart.plugins import LogPager, MachineEventSink, Pager, cv_plugins
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.orders import (
    LIFECYCLE_STATE_OF,
    MAX_EVENT_PAGE,
    NewOrder,
    OrderEventRow,
    OrderRow,
    OrderStoreError,
    StaleOrderState,
)
from candleviewer.storage.repositories.submissions import FirstPersist

from .errors import (
    POST_TERMINAL_PUSH,
    IllegalTransition,
    OmsError,
    OrderBufferFull,
    OrderHistoryRefused,
    OrderMachinesFull,
    OrderNotLoaded,
    OrderStepRefused,
    OrderStepUnknown,
    ReconcileAnomaly,
)
from .execution import apply_fields
from .order_steps import OrderStepWriter, event_kind
from .recovery import RebuiltOrder, Replayed, rebuild, recorded_outcomes, replay_plan
from .repository import OrderEventRepository, OrderRepository

__all__ = [
    "B1_AUDITS",
    "COMMAND_EVENTS",
    "FOLLOWS",
    "MAX_HELD",
    "MAX_HISTORY",
    "MAX_MACHINES",
    "MAX_PUSH_LEAD_MS",
    "MAX_RELEASES",
    "PORT_TIMEOUT",
    "PUSH_EVENTS",
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
#: Releases of one held push that a store failure, or an outcome in doubt, refused (C-2.18): the
#: last one drops it, paged, for reconciliation to apply again (24 Sec.8.5 step 2), so no push
#: holds the order's turns, or a lost KILL's re-send (INV-B1-h), for longer.
MAX_RELEASES: Final = 8
#: Settle rounds per turn (C-2.18): each takes one notice, refusal, held push or KILL; the rest
#: waits for a turn the facade schedules.
SETTLE_ROUNDS: Final = 4 * MAX_HELD
#: Events of one order hydration reads (C-2.18): past them the order is refused, never cut short.
#: An order holds at most `b01.MAX_FILLS` fills, each one event, and a few steps besides.
MAX_HISTORY: Final = 32 * MAX_EVENT_PAGE
#: Seconds a replayed step may take to commit (its send, or its invoke's recorded answer).
REPLAY_STEP_TIMEOUT: Final = 5.0
#: How far an `orders` push's exchange time may lead the facade's clock when it moves S5's
#: watermark (C-2.18): a push stamped further ahead, from a skewed or hostile stream, moves it only
#: this far, so it cannot hide the pushes after it for longer.
MAX_PUSH_LEAD_MS: Final = 60_000
#: Seconds the facade waits on its audit, notice and read ports (C-2.18): an order's lock is held
#: meanwhile, so a stalled sink must not hold the order, or a KILL, for longer.
PORT_TIMEOUT: Final = 5.0
#: Rebuilt machines a caller follows the order through (C-2.18): one that waited on an order's
#: lock while resyncs replaced its machine takes the newest, or is answered as if none held it.
FOLLOWS: Final = 4
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
#: The events `command` and `push` take, checked at run time (C-2.21): the `Literal`s bind static
#: callers only, and the facade's gates hold only for the events they were written for.
COMMAND_EVENTS: Final = frozenset(get_args(CommandEvent))
PUSH_EVENTS: Final = frozenset(get_args(PushEvent))
#: The failures of a rolled-back step whose row may be ahead of the machine (24 Sec.8.2 S7): the
#: store did not answer in time, so a COMMIT in flight may still land, or the row had moved on.
_BEHIND_ROW: Final = (b01.StepOutcomeUnknown, StaleOrderState)
#: The failures of a rolled-back step that refused its own data (hostile or malformed, OM-T04):
#: the same event is refused on every delivery (`OrderStepRefused.deterministic`).
_DATA_REFUSALS: Final = (ValueError, TypeError, LookupError, ArithmeticError, OrderStoreError)
#: The SQLSTATE classes of a statement the database refused for its data (22, a data exception;
#: 23, an integrity constraint), which `StorageQueryFailed` carries; an outage's (08, 57) or a
#: driver failure with none may pass later.
_DATA_SQLSTATES: Final = frozenset({"22", "23"})
Outcome = Literal["success", "failure", "denied"]
Severity = Literal["info", "warning", "error", "critical"]
#: Command sources that never act on an `untracked` order (S9, SR-E29-12).
MANAGERS: Final = frozenset({"rule", "algo", "group"})
#: Commands only a user sends: the operator's decision on a hold, and an adoption (D6, E45-S01).
USER_ONLY: Final = frozenset({"OPERATOR_RESOLVED", "ADOPT"})
#: Commands only the system sends: what reconciliation found (E29-T06, after its SR-E29-03 full
#: match) and a transport fault, so no route, rule, algo or group ends or binds an order by them.
SYSTEM_ONLY: Final = frozenset({
    "RECON_FOUND_LIVE", "RECON_FOUND_PARTIAL", "RECON_FOUND_FILLED", "RECON_FOUND_CANCELLED",
    "RECON_MISS", "MISMATCH", "TRANSPORT_FAULT",
})  # fmt: skip
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
    "event_seq", "reduce_only", "recorded_stop",
)  # fmt: skip
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
    "kill_spared_recorded_stop": ("orders.cancel", "denied", "info"),
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
    values (C-12.6). `request_id` is the correlation id of the HTTP request the record is written
    for (`X-Correlation-Id`, #3990), None for a job, a restart's resume or a fill-driven step (21
    Sec.3.10.1)."""

    action: str
    order_id: UUID
    account_id: UUID
    outcome: Outcome
    severity: Severity
    reason: str
    detail: Mapping[str, str | None]
    request_id: UUID | None = None


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
    events: OrderEventRepository


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
    commit (24 Sec.8.2's diagram, the KILL note's arms included), the triggers of each edge (an
    event, or a service's `done.invoke.<id>` or `error.platform.<id>`), which hydration replays,
    the events each state has an arm for that is not a refusal, the final states, and the states
    with a request in flight, which defer what they do not handle (24 Sec.8.2 S10)."""

    edges: frozenset[tuple[str, str]]
    handled: Mapping[str, frozenset[str]]
    finals: frozenset[str]
    in_flight: frozenset[str]
    triggers: Mapping[tuple[str, str], frozenset[str]]

    @classmethod
    def of(cls, chart: Mapping[str, Any]) -> Legality:
        region = chart["states"]["lifecycle"]
        shared: Mapping[str, Any] = region.get("on") or {}
        triggers: dict[tuple[str, str], set[str]] = {}
        handled: dict[str, frozenset[str]] = {}
        for name, node in region["states"].items():
            # A state's own arms shadow the region's: every guarded B1 group ends unguarded.
            groups = {
                event: _arms(spec) for event, spec in {**shared, **(node.get("on") or {})}.items()
            }
            invoke = node.get("invoke") or {}
            results = {
                f"{kind}.{invoke['id']}": _arms(invoke.get(key, []))
                for kind, key in (("done.invoke", "onDone"), ("error.platform", "onError"))
                if invoke
            }
            for trigger, arms in {**groups, **results}.items():
                for arm in arms:
                    if (target := _lifecycle_leaf(arm.get("target"))) is not None:
                        triggers.setdefault((name, target), set()).add(trigger)
            handled[name] = frozenset(e for e, group in groups.items() if any(map(_acts, group)))
        states = region["states"]
        return cls(
            edges=frozenset(triggers),
            handled=MappingProxyType(handled),
            finals=frozenset(n for n, node in states.items() if node.get("type") == "final"),
            in_flight=frozenset(n for n, node in states.items() if "invoke" in node),
            triggers=MappingProxyType({edge: frozenset(t) for edge, t in triggers.items()}),
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


def _row_state(row: OrderRow) -> str:
    """The order's B1 `lifecycle` state, as its row stores it (24 Sec.8.2 mapping)."""
    return row.lifecycle_state or LIFECYCLE_STATE_OF[row.state]


def _uuid(raw: object) -> UUID | None:
    try:
        return UUID(str(raw))
    except ValueError:
        return None


def _shown(event: object) -> str:
    """A caller's event name as a refusal logs and raises it (C-12.6, C-2.18): text is cut to
    `MAX_TEXT` characters, each unprintable one shown as `?`; anything else by its type's name."""
    if not isinstance(event, str):
        return type(event).__name__
    return "".join(c if c.isprintable() else "?" for c in event[: b01.MAX_TEXT])


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


def _exec_id(push: Mapping[str, Any]) -> str | None:
    """A push's `exec_id` as B1 keeps one (`b01.text_id`: text of 1 to `MAX_TEXT` characters with
    no control character), else None: a record or a log holds ids, never a caller's value
    (C-12.6), and a `FAULT` naming it passes B1's schema and the store."""
    return b01.text_id(push.get("exec_id"))


def _data_refusal(error: BaseException) -> bool:
    """A rolled-back step's failure refused the step's own data, so every delivery meets it: one
    of `_DATA_REFUSALS`, or a statement the database refused with a data-class SQLSTATE
    (`_DATA_SQLSTATES`)."""
    if isinstance(error, StorageQueryFailed):
        return (error.sqlstate or "")[:2] in _DATA_SQLSTATES
    return isinstance(error, _DATA_REFUSALS)


def _summary(view: Mapping[str, Any]) -> dict[str, Any]:
    """23 Sec.6.4's `context_summary` for `order`: `symbol`, `halted_by_kill`, `recon_misses`."""
    summary = {
        "symbol": view.get("symbol"),
        "halted_by_kill": view.get("halted_by_kill") is True,
        "recon_misses": _int(view.get("recon_misses")),
    }
    return {key: value for key, value in summary.items() if value is not None}


@dataclass(frozen=True, slots=True)
class _Held:
    """A push in an order's reorder buffer: its `(ts_exec, seq)` key, and how many of its releases
    a store failure, or an outcome in doubt, refused (`MAX_RELEASES`)."""

    key: tuple[int, int]
    event: str
    push: dict[str, Any]
    refused: int = 0


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
    #: The reorder buffer, in `(ts_exec, seq)` order.
    held: list[_Held] = field(default_factory=list)
    #: S5: the exchange time of the newest `orders`-topic push the order took (a push B1 refused
    #: was not taken), at most `MAX_PUSH_LEAD_MS` ahead of the clock when it was taken.
    last_update_ms: int = -1
    #: `exec_id` -> why B1 refused that EXEC, or the store its held release (`_release`), for the
    #: facade's answer (`_answer`).
    denied: OrderedDict[str, str] = field(default_factory=OrderedDict)
    #: The step count a lost KILL was last sent again at.
    kill_sent_at: int = -1
    published: dict[str, Any] | None = None
    task: asyncio.Task[None] | None = None
    #: While hydration replays the order: the recorded steps not yet replayed (`_persist`).
    replaying: deque[Replayed] | None = None
    #: A replayed step that left the record, for `_replayed` to raise.
    replay_fault: OrderHistoryRefused | None = None
    #: Set by every committed step, for `_replayed` to wait on.
    moved: asyncio.Event = field(default_factory=asyncio.Event)
    #: A step rolled back with its row perhaps ahead of the machine (`_BEHIND_ROW`): the next
    #: settle rebuilds the machine from the order's events (`_resync`).
    resync: bool = False
    #: This machine was closed by a resync, which rebuilt the order on `successor` (None when it
    #: left the order no machine): a caller that waited on this lock follows the order there.
    resynced: bool = False
    successor: _Order | None = None

    @property
    def key(self) -> str:
        return str(self.order_id)


class _Observer:
    """The facade's plugin, duck-typed (only the factory imports the runtime, CV-LINT-IMPORT): its
    `on_transition` runs once a step has committed, and never for a rolled-back one, which
    `on_transition_failed` reports instead (its trigger, with each failed action's error), before
    the rollback restores the machine."""

    __slots__ = ("_failed", "_order", "_stepped")

    def __init__(
        self,
        stepped: Callable[[_Order, Any], None],
        failed: Callable[[_Order, Any, str, Any], None],
        order: _Order,
    ) -> None:
        self._stepped = stepped
        self._failed = failed
        self._order = order

    def on_transition(self, interpreter: Any, *_transition: Any) -> None:
        self._stepped(self._order, interpreter)

    def on_transition_failed(self, interpreter: Any, transition: Any, failed: Any) -> None:
        trigger = getattr(transition, "event", None)
        self._failed(self._order, interpreter, trigger if isinstance(trigger, str) else "", failed)


class OrderMachines:
    """B1's OMS facade: one per process, as it wires the binding's process-wide ports, which
    `stop()` unwires. A second one is refused while the first holds them (`RuntimeError`): it
    would take over the first one's machines, a demo and a live root's included (C-2.11). Every
    send to an order runs under that order's lock (a keyed `asyncio.Lock`), so an order's
    commands, pushes and turns never interleave; orders run concurrently."""

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
        if b01.ports_wired():
            raise RuntimeError("an OMS facade holds B1's ports already: one per process (C-2.11)")
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
        # E50-T63: the order path's one gate is this facade's latch (`_admit`), so its gateway
        # admits everything.
        self._gateway = Gateway(pager=self._pager, admission=ALWAYS_ADMIT)
        self._orders: dict[UUID, _Order] = {}
        #: Orders a resync is rebuilding, by the machine it closed, whose lock it holds: a caller
        #: finds the order here between the old machine's close and the new one's build.
        self._resyncing: dict[UUID, _Order] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        specs = {spec.name: spec for spec in CATALOGUE}

        def counter(name: str) -> BoundedMetric:
            spec = specs[name]
            return metrics.counter(name, spec.help, spec.labels, max_series=spec.max_series)

        self._transitions = counter("oms_state_transitions_total")
        self._illegal = counter("oms_illegal_transitions_total").child()
        self._anomalies = counter("oms_reconcile_anomaly_total").child()
        self._backstops = counter("oms_native_stop_backstop_total").child()
        unknown = specs["oms_unknown_orders"]
        self._unknown_gauge = metrics.gauge(
            unknown.name, unknown.help, unknown.labels, max_series=unknown.max_series
        ).child()
        #: The live orders whose machine is in `unknown`, for `oms_unknown_orders` (R13).
        self._unknown: set[UUID] = set()
        b01.set_ports(b01.OrderPorts(persist=self._persist, commands=ports.commands, now_us=now_us))
        b01.set_audit_hook(self._audited)
        b01.set_fill_core(apply_fields)
        self._wired = True

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
        first: FirstPersist | None = None,
    ) -> str:
        """E29-T04's pipeline, once its synchronous gates ran (C-2.21): build the order's machine
        and record `VALIDATE` with their verdicts. The order's first row is written at `validated`
        (24 Sec.8.4), with `first`'s rows in the same transaction when given, or none when a
        verdict refused it. An order that would open a position with no stop is refused whatever
        its gates say: its native-stop verdict is recorded as `FAILED` (C-2.6), so no caller
        places it unprotected, and the backstop is logged at ERROR and counted, as a caller that
        reaches it has a defect. Answers the lifecycle state."""
        if not order.reduce_only and order.stop_loss is None:
            logger().error(
                "oms_native_stop_backstop", order_link_id=order.order_link_id, symbol=order.symbol
            )
            self._backstops.inc()
            gates = {**gates, "native_stop": b01.FAILED}
        payload: dict[str, Any] = {"gates": dict(gates), "order": _order_fields(order)}
        if rate_reservation is not None:
            payload["rate_reservation"] = rate_reservation
        attrs = {"order_link_id": order.order_link_id, "symbol": order.symbol, "env": environment}
        with span("oms.validate", attrs):
            return await self._first(order, environment, "VALIDATE", payload, first=first)

    async def discover(
        self, order: NewOrder, *, environment: str, pass_id: str | None = None
    ) -> str:
        """E29-T06's reconciler found an exchange order with no local row (24 Sec.8.5 step 3c):
        build its machine and record `DISCOVERED`, which writes its `untracked` row (S9)."""
        fields = _order_fields(order) | {"exchange_order_id": order.exchange_order_id}
        payload = {"order": fields} | ({} if pass_id is None else {"pass_id": pass_id})
        return await self._first(order, environment, "DISCOVERED", payload)

    async def materialise(
        self, order: NewOrder, *, environment: str, pass_id: str | None = None
    ) -> str:
        """The TP/SL order of a stop the OMS recorded has appeared, matched by E29-T05's private
        stream or E29-T06's reconciler (24 Sec.8.3 rule 7, Sec.8.8 rule 6): build its machine and
        record `MATERIALISED`, which writes its `submitted` row bound to the order's exchange id
        and sends nothing. With a *pass_id* reconciliation materialised it, which its first row
        records as its source. Its fills apply as a live order's do; it is reduce-only, so they
        start no stop (INV-B1-o); and a KILL never cancels it (C-2.6)."""
        fields = _order_fields(order) | {"exchange_order_id": order.exchange_order_id}
        payload: dict[str, Any] = {"order": fields}
        if pass_id is not None:
            payload |= {"pass_id": pass_id, "source": "reconcile"}
        return await self._first(order, environment, "MATERIALISED", payload)

    async def hydrate(self, account_id: UUID, order_id: UUID, *, environment: str) -> str:
        """After a restart (A7), the order's machine from its `order_events` (24 Sec.8.2
        "Recovery"), as the composition root (E29-T04) calls it for each non-final order the
        account holds: `list_open`'s, and the `held` and `untracked` ones, which `OPEN_STATES`
        leaves out (INV-B1-n), so the root enumerates them too. The fold of its events must equal
        its row (OM-T03); a fresh machine then replays each recorded step, which writes, audits,
        notifies and sends nothing, and an invoke the record does not answer resumes once the
        replay ends (SR-E29-15). An order whose fills call for its stop (`starts_protection`) has
        its first fill notified again, so the stop is confirmed from an exchange read (24 Sec.8.8
        rule 2). A final order gets no machine (MUST-11: S6 reads its row). Answers the lifecycle
        state; `OrderNotLoaded` when the account holds no such order, and `OrderHistoryRefused`,
        logged and paged with nothing kept, when its history does not rebuild its row or replay
        on B1. An order whose machine lives is answered from it once a hydration or a resync
        under way ends; one whose machine is still being built refuses this one
        (`IllegalTransition`: one machine per order)."""
        live = self._live(account_id, order_id)
        for _ in range(FOLLOWS):
            if live is None:
                break
            async with self._holding(live):  # a hydration or a resync under way ends first
                if live.interp is not None:
                    return live.lifecycle
            live = live.successor
        return await self._hydrate(account_id, order_id, environment)

    async def _hydrate(self, account_id: UUID, order_id: UUID, environment: str) -> str:
        """`hydrate`'s rebuild, with no live machine for the order: the fold, then the replay."""
        row = await self._bounded(self._ports.orders.get(account_id, order_id))
        if row is None:
            raise OrderNotLoaded("no order of the account has this id")
        try:
            history = await self._history(account_id, order_id)
            rebuilt = rebuild(history)
            if rebuilt != RebuiltOrder.of_row(row):
                raise OrderHistoryRefused("the order's events do not rebuild its row (OM-T03)")
            if rebuilt.lifecycle_state in self.legality.finals:
                return rebuilt.lifecycle_state
            plan = replay_plan(history, self.legality.triggers)
            return await self._replay(row, environment, plan, rebuilt)
        except OrderHistoryRefused as exc:
            link = row.order_link_id
            logger().critical("oms_order_history_refused", order_link_id=link, reason=str(exc))
            self._raise_alert("page", "oms_order_history_refused")
            raise

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
        with `IllegalTransition` unless it is one of `COMMAND_EVENTS` with no `type` in its
        payload, its state lists it, its source may send it (S9) and it is no `AMEND` of a
        recorded stop's row (24 Sec.8.8 rule 6), and with `DegradedLatchError` on a latched
        machine; else sent, answering the lifecycle state once the step settled.
        `OrderStepRefused` when B1 rolled the step back (S7), and `OrderStepUnknown` when its write
        may have committed all the same: the machine is then rebuilt from the order's events
        before this returns, and the caller reads the order's state again rather than resending.
        A command that waited while a resync rebuilt the order's machine is taken by the rebuilt
        one."""
        payload = payload or {}
        self._vet(COMMAND_EVENTS, event, payload)
        o = self._live(account_id, order_id)
        for _ in range(FOLLOWS):
            if o is None:
                break
            async with self._holding(o):
                if o.interp is not None:
                    self._admit(o, event, actor)
                    try:
                        await self._send_order(o, event, payload)
                    finally:
                        await self._settle(o)
                    return o.lifecycle
            o = o.successor  # a resync rebuilt the order while this command waited
        state = await self._stored(account_id, order_id)
        if state is not None and state in self.legality.finals:
            raise self._refuse(state, event)
        raise OrderNotLoaded("no machine in this process holds the order")

    async def push(
        self, account_id: UUID, order_id: UUID, event: PushEvent, payload: Mapping[str, Any]
    ) -> None:
        """An exchange fact for the order: E29-T05's private stream, B8's position reads, or the
        scheduler's `SL_DEADLINE`, taken in S5 order. `IllegalTransition` for an event outside
        `PUSH_EVENTS`, or a payload naming its own `type`, before anything is read. Then
        `ReconcileAnomaly` for a push the order cannot take (S6), raised once its record is
        written; `OrderBufferFull` when it would wait in a full reorder buffer;
        `OrderStepRefused` when B1 rolled its step back (S7), `deterministic` when the store
        refused the push's own data, which a redelivery meets again, and `OrderStepUnknown` when
        the step's write may have committed all the same: the machine is rebuilt first, and as the
        facade keeps no copy of the push, its caller delivers it again once, which changes
        nothing the first one did (S4, S5), and leaves it to reconciliation (24 Sec.8.5 step 2)
        if that is answered `OrderStepUnknown` too. A push that waited while a resync rebuilt the
        order's machine is taken by the rebuilt one."""
        self._vet(PUSH_EVENTS, event, payload)
        o = self._live(account_id, order_id)
        for _ in range(FOLLOWS):
            if o is None:
                break
            async with self._holding(o):
                if o.interp is not None:
                    try:
                        anomaly = await self._take(o, event, dict(payload))
                    finally:
                        await self._settle(o)
                    if anomaly:
                        raise ReconcileAnomaly(o.lifecycle, event)
                    return
            o = o.successor  # a resync rebuilt the order while this push waited
        await self._unloaded(account_id, order_id, event, payload)

    async def abandon(self, account_id: UUID, order_id: UUID, reason: str) -> str:
        """E29-T04 (S2-Q5): an order whose `SEND` step was refused is never sent, and nothing
        would send it again, so the pipeline ends it with a KILL from `validated` only. B1 takes
        it to `killed` with nothing to cancel (`skip_kill_cancel`, audited
        `kill_no_cancel_unsubmitted`). The order was never sent, as the send's step commits its
        attempt before any create can leave, so the step voids the entry's recorded stops (21
        Sec.3.3.11's table); a KILL after the send leaves them waiting for the complete read.
        Answers `killed`; `IllegalTransition` in any other state, nothing sent; `OrderStepRefused`
        when the KILL's step rolled back; `OrderNotLoaded` when no machine of the account holds
        the order. A reason B1's schema would refuse is cut, as `kill` cuts it."""
        reason = reason[: b01.MAX_TEXT] or "abandoned"
        o = self._live(account_id, order_id)
        for _ in range(FOLLOWS):
            if o is None:
                break
            async with self._holding(o):
                if o.interp is not None:
                    if o.lifecycle != "validated":
                        raise self._refuse(o.lifecycle, "ABANDON")
                    try:
                        await self._kill(o, reason)
                    finally:
                        await self._settle(o)
                    return o.lifecycle
            o = o.successor  # a resync rebuilt the order while this call waited
        state = await self._stored(account_id, order_id)
        if state is not None and state in self.legality.finals:
            raise self._refuse(state, "ABANDON")
        raise OrderNotLoaded("no machine in this process holds the order")

    async def kill(self, reason: str, *, account_id: UUID | None = None) -> tuple[UUID, ...]:
        """B18's kill switch, recorded on every live machine (of *account_id*, if given) once it
        is enforced synchronously (C-2.21): each order reaches `killed` and cancels at most once
        (INV-B1-h). The orders are killed concurrently, each under its own lock, so a slow order
        delays no other. An order whose machine a resync is rebuilding, or rebuilds while its KILL
        waits (a KILL in doubt included), is killed on the rebuilt machine. Answers the orders
        whose KILL did not commit, each logged and paged, among them a live order a resync left
        with no machine (24 Sec.8.2 "An unknown outcome") and one whose hydration, which the KILL
        waited on, refused its history (OM-T03). A reason B1's schema would refuse is cut to
        `MAX_TEXT`, or `kill` when empty, never refused: a malformed reason must not stop a
        KILL. A recorded stop's row is never killed: it audits its KILL, which commits so."""
        reason = reason[: b01.MAX_TEXT] or "kill"
        targets = {o.order_id: o for o in self._orders.values()} | self._resyncing
        live = [o for o in targets.values() if account_id in (None, o.account_id)]
        done = await asyncio.gather(
            *(self._kill_one(o, reason) for o in live), return_exceptions=True
        )
        failed: list[UUID] = []
        for o, outcome in zip(live, done, strict=True):
            if isinstance(outcome, BaseException):
                self._page("oms_kill_not_recorded", o, error=type(outcome).__name__)
            if outcome is not True:
                failed.append(o.order_id)
        return tuple(failed)

    async def _kill_one(self, o: _Order, reason: str) -> bool:
        """One order's KILL, under its lock, on the machine that holds the order: one a resync
        closed (another caller's, or this KILL's own unknown outcome) leads to the machine it
        rebuilt, which is killed in turn. True once a KILL commits, or when the closed machine
        left nothing to kill (`_settled`); False, paged, when it did not commit, when no machine
        holds a live order any more (a resync, or a hydration whose history was refused, left
        none), or when its machine is still being built, so nothing recorded it."""
        error = "no machine"
        for _ in range(FOLLOWS):
            async with self._holding(o):
                if o.interp is not None:
                    try:
                        await self._kill(o, reason)
                    except (OrderStepRefused, OrderStepUnknown, GatewayError) as exc:
                        error = type(exc).__name__
                    else:
                        return True
                    finally:
                        await self._settle(o)
                    if not o.resynced:
                        break  # refused: the order is as it was
                elif not o.resynced:
                    if self._orders.get(o.order_id) is o:
                        error = "the machine is being built"
                    elif await self._settled(o):
                        return True  # evicted once final (MUST-11), or no live row to kill
                    break  # a live order with no machine: nothing recorded the KILL
            if o.successor is None:
                break
            o = o.successor
        self._page("oms_kill_not_recorded", o, error=error)
        return False

    async def _settled(self, o: _Order) -> bool:
        """A machine closed by no resync left nothing to kill: it was evicted once final (MUST-11),
        or the order has no row (its first step was refused, S7) or a final one. A live row whose
        machine is gone, as a hydration whose history was refused leaves it (OM-T03), has nothing
        to record a KILL; a row that cannot be read raises."""
        if o.lifecycle in self.legality.finals:
            return True
        row = await self._bounded(self._ports.orders.get(o.account_id, o.order_id))
        return row is None or _row_state(row) in self.legality.finals

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
        if self._wired:  # a stopped facade never unwires the ports of the one after it
            self._wired = False
            b01.set_ports(None)
            b01.set_audit_hook(None)
            b01.set_fill_core(None)

    # --- Build, lookup and eviction (C-2.18, MUST-11, OM-I02) -----------------------------------

    async def _first(
        self,
        order: NewOrder,
        environment: str,
        event: str,
        payload: Mapping[str, Any],
        *,
        first: FirstPersist | None = None,
    ) -> str:
        """Build the order's machine and send its first event. A machine whose first step was
        refused is dropped again, so a refused order leaves nothing behind (S7); one whose first
        row may have committed all the same is rebuilt from it, if it did (`_resync`), under the
        order's lock, as every resync is, so a caller that waited on it follows the order."""
        o = await self._open(order.id, order.exchange_account_id, environment, event)
        self._ports.steps.expect(order, first=first)
        try:
            async with self._holding(o):
                try:
                    await self._send_order(o, event, payload)
                    await self._settle(o)
                except BaseException:
                    if o.resync:
                        await self._resync(o)
                    else:
                        await self._close(o, publish=False)
                    raise
                return o.lifecycle
        finally:  # a first step the chart refused never reached the writer to spend it
            self._ports.steps.forget(order.id)

    async def _open(
        self,
        order_id: UUID,
        account_id: UUID,
        environment: str,
        event: str,
        *,
        replaying: deque[Replayed] | None = None,
    ) -> _Order:
        """The order's machine, with the plugin triple, which writes ahead on the order lane (24
        Sec.17.6), and the facade's observer. Its scope is the stored order's account (OM-I02)."""
        if (known := self._orders.get(order_id)) is not None:
            raise self._refuse(known.lifecycle, event)
        if len(self._orders) >= self._max:
            raise OrderMachinesFull(f"{self._max} order machines are live")
        o = _Order(order_id, account_id, environment, replaying=replaying)
        self._orders[order_id] = o
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
        plugins: tuple[Any, ...] = (*triple, _Observer(self._stepped, self._failed, o))
        try:
            built = await build(
                MACHINE, clock=default_clock(), lane=LANE, plugins=plugins, registry=self._registry
            )
        except BaseException:
            del self._orders[order_id]
            raise
        o.interp = built.interpreter
        self._gateway.register(o.key, o.interp, kind="order", lane=LANE, metrics=triple[1])
        return o

    async def _close(self, o: _Order, *, publish: bool) -> None:
        """Stop and evict the order's machine; with *publish*, its last payload is the entity's
        final one (23 Sec.6.4)."""
        interp, o.interp = o.interp, None
        self._gateway.unregister(o.key)
        if self._orders.pop(o.order_id, None) is o:
            self._unknown.discard(o.order_id)
            self._unknown_gauge.set(len(self._unknown))
        if interp is not None:
            if publish:
                self._publish(o, interp, last=True)
            await interp.stop()

    async def _history(self, account_id: UUID, order_id: UUID) -> list[OrderEventRow]:
        """Every event of the order, page by page, in `seq` order; past `MAX_HISTORY` it is
        refused rather than read in part (C-2.18)."""
        events: list[OrderEventRow] = []
        while len(events) <= MAX_HISTORY:
            after = events[-1].seq if events else -1
            page = await self._bounded(
                self._ports.events.list_for_order(
                    account_id, order_id, after_seq=after, limit=MAX_EVENT_PAGE
                )
            )
            events.extend(page)
            if len(page) < MAX_EVENT_PAGE:
                return events
        raise OrderHistoryRefused(f"the order has more than {MAX_HISTORY} events")

    async def _replay(
        self, row: OrderRow, environment: str, plan: tuple[Replayed, ...], rebuilt: RebuiltOrder
    ) -> str:
        """Hydration's replay, under the order's lock: each recorded step sent, or answered by
        the machine's own invoke, and committed before the next (`_persist` answers its `seq`);
        then the machine must hold the order its events rebuild (`_recovered`). The binding's
        replay starts only once `_open` built the machine: a second hydration of a live order is
        refused first (one machine per order), and leaves that machine's attempts and replay
        alone."""
        link = row.order_link_id
        o = await self._open(
            row.id, row.exchange_account_id, environment, "hydrate", replaying=deque(plan)
        )
        b01.begin_replay(link, recorded_outcomes(plan))
        try:
            async with self._holding(o):
                for step in plan:
                    if step.answered:
                        await self._replayed(o, step.row.seq)
                    else:
                        try:
                            await self._send_order(o, step.trigger, step.row.payload)
                        except OrderStepRefused:
                            raise o.replay_fault or OrderHistoryRefused(
                                f"the replayed {step.trigger} at seq {step.row.seq} was refused"
                            ) from None
                        self._took(o, step)
                self._recovered(o, rebuilt)
                o.replaying = None
                b01.end_replay(link)
                self._publish(o, o.interp)
                stop_due = b01.starts_protection(o.view, o.lifecycle)
                if o.protection == "not_required" and stop_due:
                    await self._send_order(o, "FIRST_FILL", {})  # 24 Sec.8.8 rule 2, again
                await self._settle(o)
                return o.lifecycle
        except BaseException:
            try:  # the machine stops first, so no invoke waiting on the replay's gate is sent
                await self._close(o, publish=False)
            finally:
                b01.end_replay(link)
            raise

    async def _replayed(self, o: _Order, seq: int) -> None:
        """Until the recorded step at *seq* has committed: a replayed step that left the record
        raises its `OrderHistoryRefused`, as does one that does not commit in time."""
        try:
            async with asyncio.timeout(REPLAY_STEP_TIMEOUT):
                while True:
                    if (fault := o.replay_fault) is not None:
                        raise fault
                    done = o.view.get("event_seq")
                    if type(done) is int and done >= seq:
                        return
                    o.moved.clear()
                    await o.moved.wait()
        except TimeoutError:
            raise OrderHistoryRefused(f"the replayed step at seq {seq} did not commit") from None

    def _took(self, o: _Order, step: Replayed) -> None:
        """A sent event's step commits within its send, or the replay left the record there (a
        guard denied it, or it was deferred)."""
        done = o.view.get("event_seq")
        if type(done) is not int or done < step.row.seq:
            raise OrderHistoryRefused(
                f"the replayed {step.trigger} at seq {step.row.seq} moved nothing"
            )

    def _recovered(self, o: _Order, rebuilt: RebuiltOrder) -> None:
        """The replayed machine holds the order its events rebuild: every recorded step replayed,
        the state, the bound id, the fills applied in order, and the money and terms."""
        ctx = o.interp.context

        def money(key: str) -> Decimal | None:
            raw = ctx.get(key)
            return None if raw is None else Decimal(str(raw))

        keys = ("qty", "filled_qty", "cum_exec_value", "avg_price", "fee_paid", *b01.TERMS)
        held: list[object] = [o.lifecycle, ctx.get("exchange_order_id")]
        held += [tuple(ctx.get("seen_exec_ids") or ()), *map(money, keys)]
        fold: list[object] = [rebuilt.lifecycle_state, rebuilt.exchange_order_id, rebuilt.exec_ids]
        fold += [rebuilt.qty, rebuilt.cum_exec_qty, rebuilt.cum_exec_value, rebuilt.avg_price]
        fold += [rebuilt.fee_paid, rebuilt.price, rebuilt.trigger_price, rebuilt.take_profit]
        fold += [rebuilt.stop_loss]
        if o.replaying or held != fold:
            raise OrderHistoryRefused("the replayed machine is not the order its events rebuild")

    def _live(self, account_id: UUID, order_id: UUID) -> _Order | None:
        """The order's machine, if the account holds it: while a resync rebuilds it, the machine
        that resync closed, whose lock it holds, so a caller waits for the rebuilt one. Another
        account's order is not found, as an unknown one is (no oracle, C-12.4)."""
        o = self._resyncing.get(order_id) or self._orders.get(order_id)
        return o if o is not None and o.account_id == account_id else None

    async def _stored(self, account_id: UUID, order_id: UUID) -> str | None:
        row = await self._bounded(self._ports.orders.get(account_id, order_id))
        return None if row is None else _row_state(row)

    async def _bounded[T](self, call: Awaitable[T]) -> T:
        """A read, audit or notice port's answer within `PORT_TIMEOUT` (C-2.18), else
        `TimeoutError`: an order's lock may be held meanwhile."""
        async with asyncio.timeout(PORT_TIMEOUT):
            return await call

    async def _unloaded(
        self, account_id: UUID, order_id: UUID, event: str, payload: Mapping[str, Any]
    ) -> None:
        """A push for an order with no machine here. A protection fact is B8's once the order's
        machine is gone; for a final order the push is an anomaly (S6), and a fill also hands the
        position to B8, as no machine can start its stop, unless the order is reduce-only: it
        opens no position (C-2.6, as `b01_order.starts_protection` says). The hand-off is a
        protective notice, not an order action, so an S6 record that cannot be written (which
        raises, paged) never loses it."""
        if event in _PROTECTION:
            return
        row = await self._bounded(self._ports.orders.get(account_id, order_id))
        state = "" if row is None else _row_state(row)
        if row is None or state not in self.legality.finals:
            raise OrderNotLoaded("no machine in this process holds the order")
        try:
            await self._anomaly(order_id, account_id, state, event, payload)
        finally:
            if event == "EXEC" and not row.reduce_only:
                notice = OrderNotice("request_fallback_sl", order_id, account_id, None, {})
                await self._notify(notice)
        raise ReconcileAnomaly(state, event)

    # --- Gates, sends and pushes (C-2.21, S5, S6, S9) -------------------------------------------

    def _admit(self, o: _Order, event: str, actor: Actor) -> None:
        """The synchronous gates of a command, before any send: the chain-trip latch (CV-C63), S9
        and SR-E29-12 (whose source may send it), a recorded stop's amend (24 Sec.8.8 rule 6), and
        legality."""
        if event in ORDER_PATH:
            key = MachineKey(MACHINE, o.key, o.environment)
            if getattr(o.interp, "chain_trips", 0) and not self._latch.is_latched(key):
                self._latch.latch(key, "chain_trips")
            self._latch.admit_command(key)
        unowned = o.lifecycle == "untracked" and actor in MANAGERS
        misowned = (event in USER_ONLY and actor != "user") or (
            event in SYSTEM_ONLY and actor != "system"
        )
        # A recorded stop changes only through its record (`setPositionTpSl`), never by an amend,
        # whatever its position (`order_not_amendable`); a cancel is the cancel service's to judge.
        unamendable = event == "AMEND" and o.view.get("recorded_stop") is True
        if unowned or misowned or unamendable:
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

    def _vet(self, events: frozenset[str], event: str, payload: Mapping[str, Any]) -> None:
        """C-2.21 at run time: an event outside the method's set, or a payload naming its own
        `type` (which would replace the event the gates checked), is refused and counted before
        the order is even looked up, whatever the caller's static types said. An unknown name is
        an untyped caller's value, so the refusal logs and raises it only bounded (`_shown`)."""
        if not isinstance(event, str) or event not in events:
            raise self._refuse(MACHINE, _shown(event))
        if "type" in payload:
            raise self._refuse(MACHINE, event)

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
        """Through the gateway, the only send path (E50-T15), as *event*: the payload cannot
        rename it. A step B1 rolled back raises `OrderStepRefused`, `deterministic` when it
        refused its own data (`_data_refusal`), or `OrderStepUnknown` when its row may be ahead
        of the machine (`_BEHIND_ROW`, which also set `resync`); a deferred one is no error (S10),
        and no receipt is a gate (CV-C06)."""
        receipt = await self._gateway.send(o.key, {**payload, "type": event}, wait=_AWAIT_STEP)
        if receipt_is_conclusive(receipt) and (error := receipt.error) is not None:
            if isinstance(error, _BEHIND_ROW):
                raise OrderStepUnknown(event, type(error).__name__)
            data = _data_refusal(error)
            typed = error if isinstance(error, OmsError) else None  # names no value (C-12.6)
            raise OrderStepRefused(event, type(error).__name__, deterministic=data) from typed

    async def _take(self, o: _Order, event: str, push: dict[str, Any]) -> bool:
        """S5 and S6 for one push to a live machine; True when the push is an S6 anomaly."""
        final = o.lifecycle in self.legality.finals
        if event in _PROTECTION:
            await self._send_order(o, event, self._capped(push))
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
        await self._send_order(o, event, push)
        if type(stamp) is int:  # taken, so the watermark moves, at most to the clock's lead
            lead = self._now_us() // 1_000 + MAX_PUSH_LEAD_MS
            o.last_update_ms = max(o.last_update_ms, min(stamp, lead))
        return False

    def _capped(self, push: dict[str, Any]) -> dict[str, Any]:
        """A protection reading's exchange time, at most `MAX_PUSH_LEAD_MS` ahead of the clock, as
        S5's watermark is (C-2.18): a reading stamped further ahead, from a skewed or hostile
        stream, is taken at the lead, never dropped, so it decides the region for that long at
        most (INV-B1-f). A time past what B1's closed schemas hold is left for them to refuse."""
        stamp = push.get("updated_time")
        lead = self._now_us() // 1_000 + MAX_PUSH_LEAD_MS
        if type(stamp) is int and lead < stamp <= b01.MAX_EXCHANGE_US // 1_000:
            return {**push, "updated_time": lead}
        return push

    def _hold(self, o: _Order, event: str, push: dict[str, Any], refused: int = 0) -> None:
        if len(o.held) >= MAX_HELD:
            raise OrderBufferFull(f"the order holds {MAX_HELD} pushes")
        if event == "EXEC":
            key = (_int(push.get("ts_exec")), _int(push.get("seq")))
        else:
            key = (_int(push.get("updated_time")) * 1_000, 0)
        o.held.append(_Held(key, event, push, refused))
        o.held.sort(key=lambda held: held.key)

    def _due(self, o: _Order) -> _Held | None:
        """The first held push, in `(ts_exec, seq)` order, that the order can take now: a fill
        once the order is bound (or held, untracked or final), an end once it holds the fills it
        reports (or is final)."""
        final = o.lifecycle in self.legality.finals
        unowned = o.lifecycle in ("held", "untracked")
        bound = o.view.get("exchange_order_id") is not None
        for index, held in enumerate(o.held):
            fill = held.event == "EXEC" and (bound or unowned)
            end = held.event in _ENDS and not _outruns(held.push, o.view.get("filled_qty"))
            if final or fill or end:
                del o.held[index]
                return held
        return None

    # --- Settling: the notices, refusals, held pushes and a lost KILL (CV-C25) -----------------

    async def _settle(self, o: _Order) -> None:
        """After the order's steps, under its lock: act on their notices and refusals, send a lost
        KILL again, release the held pushes the order can take now, then evict the machine if the
        order is done. This is a turn's boundary: a failure stops the turn, logged, and the next
        step brings another (C-2.18 bounds the rounds of one turn)."""
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
        """One round; False once nothing is left to do. A machine that may be behind its row is
        rebuilt first. A notice or a refusal leaves its queue only once acted on, so one that
        failed is tried again at the next turn; a first fill that could not start the stop pages
        (C-2.6). A lost KILL is sent again before any held push is released, so no push holds it
        back (INV-B1-h, C-2.21)."""
        if o.resync:
            await self._resync(o)
            return False
        if o.notices:
            await self._act(o, o.notices[0])
            o.notices.popleft()
        elif o.denied:
            exec_id, reason = next(iter(o.denied.items()))
            await self._answer(o, exec_id, reason)
            o.denied.pop(exec_id, None)
        elif self._kill_lost(o):
            await self._resend_kill(o)
        elif (held := self._due(o)) is not None:
            await self._release(o, held)
        elif self._done(o):
            await self._close(o, publish=True)
            return False
        else:
            return False
        return True

    async def _release(self, o: _Order, held: _Held) -> None:
        """A held push the order can take now. A step the store refused for the push's own data
        is refused on every release (`OrderStepRefused.deterministic`): the push leaves the
        buffer, and a fill, logged at ERROR, is answered as a hostile one (`_answer`, OM-T04),
        while an end pages. A store failure, or an outcome in doubt, keeps it for the next turn,
        as delivered, and stops this one, `MAX_RELEASES` times at most: the last drops it, paged,
        for reconciliation to apply again (24 Sec.8.5 step 2), so no push holds the order's
        turns."""
        try:
            await self._take(o, held.event, held.push)
        except (OrderStepRefused, OrderStepUnknown) as exc:
            data = isinstance(exc, OrderStepRefused) and exc.deterministic
            if data and held.event == "EXEC":
                exec_id, link = _exec_id(held.push), o.view.get("order_link_id")
                logger().error(
                    "oms_held_fill_refused", order_link_id=link, exec_id=exec_id, error=exc.failure
                )
                self._deny(o, exec_id or "", f"the write-ahead step refused it ({exc.failure})")
            elif data or held.refused + 1 >= MAX_RELEASES:
                self._page("oms_held_push_dropped", o, trigger=held.event, error=exc.failure)
            else:
                self._hold(o, held.event, held.push, held.refused + 1)
                raise

    async def _act(self, o: _Order, notice: dict[str, Any]) -> None:
        """One outbox notice: the first fill starts the stop (24 Sec.8.8 rule 2; the region takes a
        repeat as a no-op), and one that could not pages (C-2.6); `terminal` needs no hand-off, as
        the step that ended the order is published; anything else goes to the notice port, which
        never raises (`_notify`)."""
        kind = str(notice.get("kind"))
        if kind == "first_fill":
            try:
                await self._send_order(o, "FIRST_FILL", {})
            except Exception as exc:
                self._page("oms_first_fill_not_delivered", o, error=type(exc).__name__)
                raise
        elif kind != "terminal":
            detail = {key: value for key, value in notice.items() if key not in ("seq", "kind")}
            link = o.view.get("order_link_id")
            await self._notify(OrderNotice(kind, o.order_id, o.account_id, link, detail))

    async def _answer(self, o: _Order, exec_id: str, reason: str) -> None:
        """An EXEC B1 refused that is neither a repeat (S4) nor early (before the bind), or a held
        one whose step the store refused for its data, is hostile (OM-T04): the order is
        quarantined where its state lists `FAULT`, else it pages."""
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
        rolled back and the `protection` audit did not (CV-C06). A recorded stop's row stays live
        by design: its guarded arm audits the KILL and sends nothing (C-2.6, INV-B1-p)."""
        await self._send_order(o, "KILL", {"reason": reason})
        if o.lifecycle in self._killable and o.view.get("recorded_stop") is not True:
            raise OrderStepRefused("KILL", "the lifecycle step was rolled back")

    def _done(self, o: _Order) -> bool:
        """MUST-11: final, its stop settled (no attach in flight) and nothing left to act on."""
        final = o.lifecycle in self.legality.finals and o.protection != "sl_pending"
        return final and not (o.notices or o.denied or o.held)

    # --- S7's unknown outcome: the row decides (`_BEHIND_ROW`) ---------------------------------

    async def _resync(self, o: _Order) -> None:
        """A step rolled back while its row may have committed (a write that did not answer in
        time), or met a row that had moved on: the machine may be behind its row, which decides
        (S7). Under the order's lock, the facade pages, closes the machine and hydrates the order
        from its events, as after a restart (A7): the old machine's command attempts go with it,
        so an invoke the record does not answer resumes as one this process did not begin (a
        `place` looks its id up first), and an order whose fills call for its stop is sent
        `FIRST_FILL` again, its stop attached and read back afresh (INV-B1-f). Meanwhile a caller
        finds the order by the closed machine (`_resyncing`) and waits on its lock; it then
        follows the order to the rebuilt one (`successor`). The pushes, notices and refusals the
        old machine held pass to the new one, or, with none (a final order, or a history the
        rebuild refused), to `_orphaned`."""
        o.resync, o.resynced = False, True
        self._resyncing[o.order_id] = o
        link = o.view.get("order_link_id")
        self._page("oms_step_outcome_unknown", o, state=o.lifecycle)
        try:
            await self._close(o, publish=False)
            try:
                await self._hydrate(o.account_id, o.order_id, o.environment)
            except Exception as exc:  # a refused history is logged and paged by `_hydrate` itself
                error = type(exc).__name__
                logger().error("oms_resync_not_hydrated", order_link_id=link, error=error)
            n = o.successor = self._orders.get(o.order_id)
            if n is None:
                await self._orphaned(o)
                return
            async with self._holding(n):
                n.notices.extend(o.notices)
                n.denied.update(o.denied)
                n.held.extend(o.held)
                n.held.sort(key=lambda held: held.key)
                n.last_update_ms = max(n.last_update_ms, o.last_update_ms)
                await self._settle(n)
        finally:
            self._resyncing.pop(o.order_id, None)  # a nested resync's entry went before it

    async def _orphaned(self, o: _Order) -> None:
        """What a resynced order left with no machine: each held push goes as an evicted order's
        does (S6, a fill handing its position to B8), each notice to the notice port, and a
        refusal B1 kept for an answer pages, as no machine is left to quarantine. When the row
        holds fills and the stop was not confirmed, the position goes to B8, as no machine can
        start the stop (C-2.6); a row that cannot be read pages."""
        link = o.view.get("order_link_id")
        for held in o.held:
            try:
                await self._unloaded(o.account_id, o.order_id, held.event, held.push)
            except ReconcileAnomaly:
                continue  # recorded (S6)
            except Exception as exc:  # no final row, or no answer: reconciliation re-applies it
                error = type(exc).__name__
                logger().error(
                    "oms_held_push_dropped", order_link_id=link, trigger=held.event, error=error
                )
        for notice in o.notices:
            kind = str(notice.get("kind"))
            if kind not in ("first_fill", "terminal"):
                detail = {k: v for k, v in notice.items() if k not in ("seq", "kind")}
                await self._notify(OrderNotice(kind, o.order_id, o.account_id, link, detail))
        if any(reason not in (b01.REPEAT, b01.UNBOUND) for reason in o.denied.values()):
            self._page("oms_hostile_exec_not_quarantined", o, state="no machine")
        try:
            row = await self._bounded(self._ports.orders.get(o.account_id, o.order_id))
        except Exception as exc:  # the stop's need is unknown: the operator is paged
            self._page("oms_resync_row_unread", o, error=type(exc).__name__)
            return
        held_fills = row is not None and row.cum_exec_qty > 0 and not row.reduce_only
        if held_fills and o.protection != "sl_present":
            handoff = OrderNotice("request_fallback_sl", o.order_id, o.account_id, link, {})
            await self._notify(handoff)

    # --- The observer: every committed step (C-2.20, CV-C02, OM-I02) -----------------------------

    def _failed(self, o: _Order, interp: Any, trigger: str, failed: Any) -> None:
        """A step B1 rolled back (S11). When a failure leaves its row perhaps ahead of the machine
        (`_BEHIND_ROW`), the next settle rebuilds the machine: a caller settles before it lets go
        of the order, and a step no caller drove (an invoke's answer) gets a turn. When the store
        refused a service result's step for its data (`done.invoke.<id>`: a place ack naming an
        exchange order id another order of the account holds, say), the attempt is recorded as
        failed (`b01.fail_attempt`), so the invoke the rollback re-arms takes the order to
        `unknown` (S1), where reconciliation decides, rather than answering the same result into
        the same refusal until the runtime cuts the chain: the order would rest in its invoking
        state with nothing running and no stop started for a position the exchange may have
        opened (C-2.6)."""
        if o.replaying is not None:
            return
        errors = [error for _action, error in failed or ()]
        if any(isinstance(error, _BEHIND_ROW) for error in errors):
            o.resync = True
            self._schedule(o)
            return
        invoke = trigger.removeprefix("done.invoke.")
        refused = next((error for error in errors if _data_refusal(error)), None)
        if invoke != trigger and refused is not None:
            link, failure = o.view.get("order_link_id"), type(refused).__name__
            logger().error("oms_invoke_result_refused", order_link_id=link, error=failure)
            b01.fail_attempt(interp.context, invoke, failure)

    def _stepped(self, o: _Order, interp: Any) -> None:
        """A step committed (a rolled-back one never gets here, so its notices never do, CV-C02):
        the plain view, the outbox's new notices, the publish and, unless the facade holds the
        order, a turn. The taken notices leave the outbox; its newest stays, as the next
        notice's `seq` follows it."""
        ctx = interp.context
        leaves = _leaves(interp)
        o.lifecycle = leaves.get("lifecycle", o.lifecycle)
        o.protection = leaves.get("protection", o.protection)
        if o.lifecycle == "unknown" and self._orders.get(o.order_id) is o:
            self._unknown.add(o.order_id)
        else:
            self._unknown.discard(o.order_id)
        self._unknown_gauge.set(len(self._unknown))
        o.view = {key: ctx.get(key) for key in _VIEW}
        o.steps += 1
        raw = ctx.get("outbox")
        box = [dict(n) for n in raw if isinstance(n, Mapping)] if isinstance(raw, list) else []
        fresh = [n for n in box if type(n.get("seq")) is int and n["seq"] > o.cursor]
        if fresh:
            if o.replaying is None:  # a replayed step's notices went out when it happened
                o.notices.extend(fresh)
            o.cursor = fresh[-1]["seq"]
        if len(box) > 1:
            ctx["outbox"] = box[-1:]
        o.moved.set()
        if o.replaying is not None:
            return
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
        order_id = _uuid(step.order_id)
        o = None if order_id is None else self._orders.get(order_id)
        if o is not None and o.replaying is not None:
            return self._replay_step(o, step)
        seq = await self._ports.steps(step)
        self._transitions.labels(source, step.to_state, event_kind(step)[1]).inc()
        return seq

    def _replay_step(self, o: _Order, step: b01.Step) -> int:
        """A replayed step writes nothing and answers its row's `seq`: it must be the next step
        the record holds, by its states, kind and source (24 Sec.8.2 "Recovery")."""
        replaying = o.replaying or deque()
        row = replaying[0].row if replaying else None
        try:
            kind = event_kind(step)
        except ValueError:
            kind = None
        if row is not None:
            frm = None if row.from_state is None else LIFECYCLE_STATE_OF[row.from_state]
            want = (frm, replaying[0].state, (row.kind, row.source))
            if (step.from_state, step.to_state, kind) == want:
                replaying.popleft()
                return row.seq
        at = "past its end" if row is None else f"at seq {row.seq}"
        o.replay_fault = OrderHistoryRefused(f"the replay left the record {at}")
        o.moved.set()
        raise o.replay_fault

    async def _audited(self, name: str, context: dict[str, Any]) -> None:
        """B1's audit hook: one of its records, written ahead under `B1_AUDITS` (C-2.9). A refused
        EXEC's reason is kept for `_answer`; a repeat (S4) and an early fill are not anomalies.
        It never raises (a rollback would undo a KILL): a lost record pages."""
        order_id = _uuid(context.get("order_id"))
        o = None if order_id is None else self._orders.get(order_id)
        if o is not None and o.replaying is not None:  # audited when the step happened
            logger().info("oms_b1_record_replayed", record=name)
            return
        denied = context.get("denied")
        reason = str(denied.get("reason") or "") if isinstance(denied, Mapping) else ""
        if o is not None and name == "guard_denied" and isinstance(denied, Mapping):
            self._deny(o, str(denied.get("exec_id") or ""), reason)
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

    def _deny(self, o: _Order, exec_id: str, reason: str) -> None:
        """Keep why an EXEC was refused, for `_answer`: at most `MAX_HELD`, the oldest dropped."""
        o.denied[exec_id] = reason
        while len(o.denied) > MAX_HELD:
            o.denied.popitem(last=False)

    async def _record(self, o: _Order, name: str, detail: Mapping[str, str | None]) -> None:
        """B1's record, written ahead (C-2.9); an S6 anomaly is alerted once it is written."""
        action, outcome, severity = B1_AUDITS[name]
        fields = {"order_link_id": o.view.get("order_link_id"), **detail}
        record = OrderAuditRecord(action, o.order_id, o.account_id, outcome, severity, name, fields)
        try:
            await self._bounded(self._ports.audit.write(record))
        except Exception as exc:  # B1's hook must not raise: the record is lost, so it pages
            self._page("oms_audit_record_lost", o, record=name, error=type(exc).__name__)
        if action == ANOMALY:
            self._alert_anomaly()

    async def _anomaly(
        self,
        order_id: UUID,
        account_id: UUID,
        state: str,
        event: str,
        push: Mapping[str, Any],
    ) -> None:
        """S6, the facade's own record: logged and written ahead of the refusal, then counted and
        alerted; a record that cannot be written raises (C-2.9), counted and alerted all the same,
        and its loss pages. The push never met B1's closed schema, so its `exec_id` is kept only
        as B1 keeps one (`_exec_id`): the detail holds ids and state names, never a caller's value
        (C-12.6)."""
        detail = {"state": state, "trigger": event, "exec_id": _exec_id(push)}
        logger().error("oms_reconcile_anomaly", **detail)
        record = OrderAuditRecord(
            ANOMALY, order_id, account_id, "denied", "error", POST_TERMINAL_PUSH, detail
        )
        try:
            await self._bounded(self._ports.audit.write(record))
        except Exception as exc:  # C-2.9: no refusal is answered unrecorded, and the loss pages
            error = type(exc).__name__
            logger().critical("oms_audit_record_lost", record=POST_TERMINAL_PUSH, error=error)
            self._raise_alert("page", "oms_audit_record_lost")
            raise
        finally:
            self._alert_anomaly()

    def _alert_anomaly(self) -> None:
        """S6 (#847's "raised, audited and alerted"): each anomaly is counted in
        `oms_reconcile_anomaly_total` and raised to the pager as an alert, a ticket, not a page."""
        self._anomalies.inc()
        self._raise_alert("alert", "oms_reconcile_anomaly")

    async def _notify(self, notice: OrderNotice) -> None:
        try:
            await self._bounded(self._ports.notices.notify(notice))
        except Exception as exc:  # the step that posted it stands: a lost notice pages
            logger().critical("oms_notice_lost", kind=notice.kind, error=type(exc).__name__)
            self._raise_alert("page", f"order notice lost: {notice.kind}")

    def _page(self, event: str, o: _Order, **detail: str) -> None:
        logger().critical(event, order_link_id=o.view.get("order_link_id"), **detail)
        self._raise_alert("page", event)

    def _raise_alert(self, severity: Literal["page", "alert"], summary: str) -> None:
        """The pager is a synchronous, non-blocking sink (`Pager`), called once the record it
        alerts on is written. One that raises is contained and logged at CRITICAL, as
        `CvErrorHooks` contains its hooks: a broken pager never loses a record, rolls back a
        step or changes a caller's answer (C-2.9)."""
        try:
            self._pager.raise_alert(severity, summary, machine_kind=MACHINE)
        except Exception as exc:  # the alert is lost, never the record or the answer
            logger().critical("oms_pager_failed", summary=summary, error=type(exc).__name__)
