"""candleviewer.statechart.gateway — the ONLY send path into a machine (E50-T15).

29-statechart-adoption-plan.md §1.4:

* `Gateway.send(key, event)` runs on the interpreter's owning loop (loop
  affinity asserted per interpreter).
* `Gateway.send_threadsafe(key, event)` is the only cross-thread path
  (CV-C33). It wraps the library's `run_coroutine_threadsafe` delivery and
  **reads every future** (CV-C36): a failure is counted in
  `cv_machine_send_refused_total{kind,reason}` and logged, never lost.
* Order-lane inbox overflow (`overflow_policy="refuse"` == RAISE) becomes
  `GatewayOverloadedError` (HTTP 503) plus a page; nothing is dropped
  silently (CV-C36).
* `priority=True` is never set and `Event(system=True)` is never forwarded
  (CV-C42); there is no parameter through which a caller could ask.
* A `wait=True` receipt with `changed=False, error=None` is never a gate on a
  `defer` chart (CV-C06): `receipt_is_conclusive()` is the only sanctioned
  way to read one.
* Admission (E50-T63, C-2.21): a `Gateway` is built with an `Admission`, and
  `send`/`send_threadsafe` ask `admit(machine_key, event_type)` synchronously
  before they deliver; a refusal is `GatewayDegradedError` (HTTP 503), counted
  `degraded`. The check is a constructor argument, never shared state, so it
  stays visible in every call path. `ALWAYS_ADMIT` admits everything; the
  latch-backed one is `statechart_wiring.LatchAdmission`. Reads are never gated.

This module never imports the runtime (CV-LINT-IMPORT); the overflow
exception is re-exported by `factory.py`.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

import structlog

from candleviewer.statechart.config import Lane
from candleviewer.statechart.factory import InboxFullError, re_mint
from candleviewer.statechart.plugins._base import LogPager, Pager, Severity

if TYPE_CHECKING:
    from candleviewer.statechart.persistence import MachineKey


def logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger("candleviewer.statechart.gateway")


#: `reason` label values for `cv_machine_send_refused_total`.
REASON_QUEUE_FULL: Final = "queue_full"
REASON_SEND_FAILED: Final = "send_failed"
REASON_SYSTEM_EVENT: Final = "system_event"
REASON_DEGRADED: Final = "degraded"


@dataclass(frozen=True, slots=True)
class Decision:
    """An admission's answer: admitted, or refused for `reason` (a metric label value)."""

    admitted: bool
    reason: str


ADMITTED: Final = Decision(True, "")


class Admission(Protocol):
    """The synchronous check before any send (C-2.21): `key` is the machine's `MachineKey`, or
    `None` for one registered without a key; `event_type` the event's `type`."""

    def admit(self, key: MachineKey | None, event_type: str) -> Decision: ...


class _AlwaysAdmit:
    def admit(self, key: MachineKey | None, event_type: str) -> Decision:
        return ADMITTED


#: Admits everything: the default, and the explicit choice of an owner that has not adopted the
#: persistence bundle's latch, or that gates on its own (the OMS facade).
ALWAYS_ADMIT: Final[Admission] = _AlwaysAdmit()


class RefusalRecorder(Protocol):
    """`CvMetricsPlugin.record_send_refused` (E50-T60)."""

    def record_send_refused(self, reason: str) -> None: ...


class GatewayError(Exception):
    """Base for gateway refusals."""


class UnknownMachineError(GatewayError):
    """No interpreter registered under the key."""


class LoopAffinityError(GatewayError):
    """`send()` called off the interpreter's owning loop; use
    `send_threadsafe()` from other threads (CV-C33)."""


class SystemEventRefusedError(GatewayError):
    """Caller tried to forward a system-provenance event (CV-C42)."""


class GatewayDegradedError(GatewayError):
    """The admission refused the command: the machine is degraded (the chain-trip latch, CV-C63)
    until an operator acknowledges it (E42). Maps to HTTP 503 at the API edge."""

    status_code: Final = 503

    def __init__(self, key: str, lane: Lane) -> None:
        self.key = key
        self.lane = lane
        super().__init__(
            f"machine '{key}' ({lane} lane) is degraded (chain-trip latch, CV-C63): "
            "commands refused until acknowledged"
        )


class GatewayOverloadedError(GatewayError):
    """Inbox refused the event. Maps to HTTP 503 at the API edge."""

    status_code: Final = 503

    def __init__(self, key: str, lane: Lane) -> None:
        self.key = key
        self.lane = lane
        super().__init__(f"machine '{key}' ({lane} lane) inbox full; retry later")


@dataclass(slots=True)
class _Entry:
    interpreter: Any
    kind: str
    lane: Lane
    metrics: RefusalRecorder
    loop: asyncio.AbstractEventLoop
    machine_key: MachineKey | None = None


def receipt_is_conclusive(receipt: Any) -> bool:
    """CV-C06: whether a `send(wait=True)` receipt may gate a decision.

    Every CV chart is `onUnhandled: "defer"`, so a receipt with
    `changed=False, error=None` (or `deferred=True`) only says "nothing ran
    yet" — never "the request was a correct no-op". Such a receipt is not a
    gate; callers must observe the outcome another way (state entry, audit).
    """
    if receipt is None or getattr(receipt, "deferred", False):
        return False
    return bool(receipt.changed) or receipt.error is not None


#: CV-C68 (R14-01 containment): the only fields `cv_re_mint` may change.
RE_MINT_ALLOWED_FIELDS: Final = frozenset({"data", "error", "fired_at", "scheduled_for"})


class ReMintForbiddenError(GatewayError):
    """`cv_re_mint` was asked to override `type`/`src` (or any non-payload
    field), which would forge engine provenance (CV-C68, R14-01)."""


#: Spec name (E50-T56 ticket / CV-C68).
ReMintForbidden = ReMintForbiddenError


def cv_re_mint(ev: Any, **payload: Any) -> Any:
    """Payload-only wrapper over the library's `re_mint` (CV-C68).

    Accepts only `data`, `error`, `fired_at`, `scheduled_for`; anything else
    (notably `type`, `src`) raises `ReMintForbiddenError` before the library
    is called, so event type and provenance are always preserved. Remove when
    upstream R14-01 closes and the pin moves via an ADR-0016 amendment.
    """
    bad = sorted(set(payload) - RE_MINT_ALLOWED_FIELDS)
    if bad:
        raise ReMintForbiddenError(
            f"cv_re_mint may only change {sorted(RE_MINT_ALLOWED_FIELDS)}; refused {bad} (CV-C68)"
        )
    return re_mint(ev, **payload)


Event = str | Mapping[str, Any]


class Gateway:
    """Registry of running interpreters plus the sanctioned send paths."""

    def __init__(self, *, pager: Pager | None = None, admission: Admission = ALWAYS_ADMIT) -> None:
        self._pager: Pager = pager or LogPager()
        self._admission = admission
        self._entries: dict[str, _Entry] = {}

    def register(
        self,
        key: str,
        interpreter: Any,
        *,
        kind: str,
        lane: Lane,
        metrics: RefusalRecorder,
        machine_key: MachineKey | None = None,
    ) -> None:
        """Bind *key* to a started interpreter. Must run on its owning loop:
        that loop is recorded and asserted on every `send()`. `machine_key` is
        what the admission is asked about (`None`: admitted as before)."""
        if key in self._entries:
            raise GatewayError(f"machine '{key}' already registered")
        loop = asyncio.get_running_loop()
        self._entries[key] = _Entry(interpreter, kind, lane, metrics, loop, machine_key)

    def unregister(self, key: str) -> None:
        self._entries.pop(key, None)

    def _entry(self, key: str) -> _Entry:
        try:
            return self._entries[key]
        except KeyError:
            raise UnknownMachineError(f"no machine registered as '{key}'") from None

    def _reject_system(self, entry: _Entry, event: Event) -> None:
        if getattr(event, "system", False):
            entry.metrics.record_send_refused(REASON_SYSTEM_EVENT)
            raise SystemEventRefusedError("system-provenance events are never forwarded (CV-C42)")

    def _admit(self, key: str, entry: _Entry, event: Event) -> None:
        """C-2.21: the injected admission, asked before any delivery; a refusal is counted and
        raised as `GatewayDegradedError`, and nothing reaches the interpreter."""
        event_type = event if isinstance(event, str) else str(event.get("type", ""))
        decision = self._admission.admit(entry.machine_key, event_type)
        if decision.admitted:
            return
        entry.metrics.record_send_refused(decision.reason or REASON_DEGRADED)
        logger().warning(
            "statechart_send_refused", key=key, kind=entry.kind, reason=REASON_DEGRADED
        )
        raise GatewayDegradedError(key, entry.lane)

    def _overloaded(self, key: str, entry: _Entry, *, count: bool) -> GatewayOverloadedError:
        if count:
            entry.metrics.record_send_refused(REASON_QUEUE_FULL)
        severity: Severity = "page" if entry.lane == "order" else "alert"
        logger().error(
            "statechart_send_refused", key=key, kind=entry.kind, reason=REASON_QUEUE_FULL
        )
        self._pager.raise_alert(
            severity, f"inbox full: {key} ({entry.lane} lane)", machine_kind=entry.kind
        )
        return GatewayOverloadedError(key, entry.lane)

    async def send(self, key: str, event: Event, *, wait: bool = False) -> Any:
        """Send on the owning loop. Returns the library receipt when
        *wait* (read it only via `receipt_is_conclusive`, CV-C06)."""
        entry = self._entry(key)
        if asyncio.get_running_loop() is not entry.loop:
            raise LoopAffinityError(f"send('{key}') off its owning loop; use send_threadsafe")
        self._reject_system(entry, event)
        self._admit(key, entry, event)
        try:
            pending = entry.interpreter.send(event, wait=wait)
        except InboxFullError:
            raise self._overloaded(key, entry, count=True) from None
        return await pending

    def send_threadsafe(self, key: str, event: Event) -> concurrent.futures.Future[None]:
        """The only cross-thread path (CV-C33). Every future is read: a
        failure on the loop is logged, counted and (order lane) paged."""
        entry = self._entry(key)
        self._reject_system(entry, event)
        self._admit(key, entry, event)
        try:
            fut: concurrent.futures.Future[None] = entry.interpreter.send_threadsafe(event)
        except InboxFullError:
            raise self._overloaded(key, entry, count=True) from None
        except Exception as exc:
            entry.metrics.record_send_refused(REASON_SEND_FAILED)
            logger().error(
                "statechart_send_failed", key=key, kind=entry.kind, error=type(exc).__name__
            )
            raise
        fut.add_done_callback(lambda f: self._read_future(key, entry, f))
        return fut

    def _read_future(self, key: str, entry: _Entry, fut: concurrent.futures.Future[None]) -> None:
        if fut.cancelled():
            entry.metrics.record_send_refused(REASON_SEND_FAILED)
            logger().error("statechart_send_failed", key=key, kind=entry.kind, error="cancelled")
            return
        exc = fut.exception()
        if exc is None:
            return
        if isinstance(exc, InboxFullError):
            # The library already fired on_event_dropped("queue_full") for a
            # loop-side refusal, which CvMetricsPlugin counts: do not double count.
            self._overloaded(key, entry, count=False)
            return
        entry.metrics.record_send_refused(REASON_SEND_FAILED)
        logger().error("statechart_send_failed", key=key, kind=entry.kind, error=type(exc).__name__)


__all__ = [
    "ADMITTED",
    "ALWAYS_ADMIT",
    "Admission",
    "Decision",
    "Gateway",
    "GatewayDegradedError",
    "GatewayError",
    "GatewayOverloadedError",
    "LoopAffinityError",
    "ReMintForbidden",
    "ReMintForbiddenError",
    "SystemEventRefusedError",
    "UnknownMachineError",
    "cv_re_mint",
    "receipt_is_conclusive",
]
