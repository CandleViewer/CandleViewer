"""`CvStateFeedPlugin`: feeds `machines.{entity}.state` from a machine's own hooks (E17-T08;
23-ws-protocol.md §6.4, 24-internal-schemas.md §17.6).

One instance per interpreter, attached by the module that owns the machine beside the mandatory
triple, never in it: `feed_plugins(port, binding)` gives the entries for `build(plugins=)` and
`restore(extra_plugins=)`. It publishes through a `MachineStatePort` defined here, so `statechart`
imports nothing of `ws` (C-3.1); the composition root maps the port onto the WS registry
(`machine_state_wiring.py`).

A payload goes out on the init record (`CvMetricsPlugin` skips it, CV-C09; a feed wants the first
state), on every transition, internal ones included, once after a restore (`cv_bring_up`: a restored
`start()` enters no state) and when `chain_trips` first passes 0. One whose tags hold `terminal`
goes out as the entity's last (`last=True`); a later one that still holds it replaces it, a parallel
chart's next step. A stop removes a live entry. Hooks never raise into the interpreter
(`contained`) and never call `send()` (CV-C25); there is no `on_receipt_dropped` (CV-C69). Only the
public `value`, `tags`, `chain_trips` and `context` are read, and of the context only `SUMMARY`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, Protocol
from uuid import UUID

from candleviewer.statechart.plugins._base import HookFailureCounter, contained
from candleviewer.statechart.registry import Registry, default_registry

_SYMBOL: Final = re.compile(r"[A-Z0-9]{2,20}USDT")


def _flag(value: object) -> bool:
    return type(value) is bool


def _count(value: object) -> bool:
    return type(value) is int and value >= 0


def _symbol(value: object) -> bool:
    return isinstance(value, str) and _SYMBOL.fullmatch(value) is not None


def _scope(value: object) -> bool:
    return value in ("global", "accounts")


#: §6.4, §15.10: per chart id, the `context_summary` keys the feed may send and their types. A value
#: off its type is dropped, so one bad key never refuses the whole payload. `alert`'s `severity` is
#: left out: B10 never writes it, so the context would only repeat the chart's default.
SUMMARY: Final[Mapping[str, Mapping[str, Callable[[object], bool]]]] = {
    "order": {"symbol": _symbol, "halted_by_kill": _flag, "recon_misses": _count},
    "alert": {"delivery_attempts": _count, "storm_count": _count},
    "recording": {"symbol": _symbol, "gap_count_24h": _count},
    "book": {"symbol": _symbol, "resync_count": _count},
    "session": {"mfa_satisfied": _flag, "step_up_failures": _count},
    "kill_switch": {"scope": _scope, "cancel_working": _flag, "flatten": _flag},
}


@dataclass(frozen=True, slots=True)
class FeedBinding:
    """A machine's public entity (§6.4) and the scope its owning module binds from its own record,
    never from the machine's context. `entity_id` is `None` for a singleton."""

    machine_kind: str  # the chart id
    entity_id: str | None = None
    accounts: frozenset[UUID] = frozenset()
    user: UUID | None = None


class MachineStateHandle(Protocol):
    """One machine's slot; both calls are synchronous and never block (a hook runs in the step)."""

    def publish(self, payload: Mapping[str, Any], *, last: bool) -> None: ...

    def remove(self) -> None: ...


class MachineStatePort(Protocol):
    """Where the feed publishes. `bind` raises `ValueError` for a chart with no public entity."""

    @property
    def environment(self) -> str: ...

    def now_ms(self) -> int: ...

    def bind(self, binding: FeedBinding) -> MachineStateHandle: ...


def _top(value: Any) -> str:
    """The state a library state value names: `"open"`, or `{"unwinding": "x"}` -> `"unwinding"`."""
    return value if isinstance(value, str) else str(next(iter(value)))


def project(interp: Any) -> tuple[str, dict[str, str] | None]:
    """`state` and `regions` as `admin.inspector.published_state` reads a configuration: the root's
    active child, or for a parallel chart each region's, `state` being the first region's."""
    value = interp.value
    if getattr(interp.machine, "type", None) != "parallel":
        return _top(value), None
    regions = {str(name): _top(sub) for name, sub in value.items()}
    return next(iter(regions.values())), regions


class CvStateFeedPlugin(HookFailureCounter):
    """See the module docstring."""

    def __init__(
        self,
        handle: MachineStateHandle,
        binding: FeedBinding,
        *,
        machine_hash: str,
        environment: str,
        now_ms: Callable[[], int],
    ) -> None:
        super().__init__()
        self._handle, self._binding = handle, binding
        self._hash, self._environment, self._now_ms = machine_hash, environment, now_ms
        self._summary = SUMMARY.get(binding.machine_kind, {})
        self._last: dict[str, Any] | None = None  # what the registry holds

    @contained
    def on_transition(
        self, interpreter: Any, from_states: Any, to_states: Any, transition: Any
    ) -> None:
        self._publish(interpreter)

    @contained
    def cv_bring_up(self, interpreter: Any) -> None:
        """Called once by `factory.cv_bring_up_restored`, after a restored `start()`."""
        self._publish(interpreter)

    @contained
    def on_chain_budget_exceeded(self, interpreter: Any, error: BaseException, event: Any) -> None:
        """`degraded` flips once. A trip is no transition, and a settle trip fires before the engine
        repairs its configuration, so the last payload stands, with the flag set."""
        last = self._last
        if last is not None and not last["degraded"]:
            self._send({**last, "degraded": True, "updated_at_ms": self._now_ms()})

    @contained
    def on_interpreter_stop(self, interpreter: Any) -> None:
        self._handle.remove()  # the registry keeps a terminal entry, and a newer machine's

    def _publish(self, interp: Any) -> None:
        state, regions = project(interp)
        payload: dict[str, Any] = {"machine_kind": self._binding.machine_kind, "state": state}
        if regions is not None:
            payload["regions"] = regions
        payload |= {
            "tags": sorted(interp.tags),
            "degraded": interp.chain_trips > 0,
            "machine_hash": self._hash,
            "environment": self._environment,
            "updated_at_ms": self._now_ms(),
        }
        if summary := self._context_summary(interp.context):
            payload["context_summary"] = summary
        self._send(payload)

    def _send(self, payload: dict[str, Any]) -> None:
        """The one place `last` is decided: the tags say `terminal`. Kept only once it went out."""
        self._handle.publish(payload, last="terminal" in payload["tags"])
        self._last = payload

    def _context_summary(self, context: Mapping[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for key, valid in self._summary.items():
            value = context.get(key)
            if value is None and key == "symbol":
                value = self._binding.entity_id  # `book`, `recording`: the entity is the symbol
            if valid(value):  # null or off its type: left out, and a value is never logged (C-12.6)
                summary[key] = value
        return summary


def feed_plugins(
    port: MachineStatePort | None, binding: FeedBinding, *, registry: Registry | None = None
) -> tuple[Any, ...]:
    """The entries for one machine's `build(plugins=)` and `restore(extra_plugins=)`: none without
    a port (a module not wired to the gateway; a unit test), else one `CvStateFeedPlugin`. The
    port's `bind` raises for a chart with no public entity or an id off the §6.4 grammar: a wiring
    bug, met when the owner builds the plugin. `registry` is the one `build()` gets (tests)."""
    if port is None:
        return ()
    machine_hash = (registry or default_registry()).hash(binding.machine_kind)
    feed = CvStateFeedPlugin(
        port.bind(binding),
        binding,
        machine_hash=machine_hash,
        environment=port.environment,
        now_ms=port.now_ms,
    )
    return (feed,)
