"""The rule engine's signal bus (24 §11.5 "Signals"; E35-T13 slice 4a; RE-S3, RE-D7).

`emit_signal` offers a signal and never awaits (C-2.20): `SignalBus.offer` is synchronous. The bus
holds a bounded queue of its own (`limits.SIGNAL_QUEUE_BOUND`), apart from the evaluation queue,
so a burst of signals never pushes a market tick out of it: a full queue refuses the newest
signal, never one waiting, counted in `rule_signal_dropped_total` and logged once per episode,
which ends when the queue next runs empty. A signal deeper than the depth limit is never enqueued:
its chain is cut, logged as an error and counted in `rule_signal_chain_truncated_total`. A signal
carries its owner, and the runner evaluates it for that owner's `on_signal` rules alone (RE-S3). A
repeat of an action's fire key among the last `KEYS_REMEMBERED` is enqueued once. Memory only: a
stop drops the waiting signals, as it drops queued fires.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Final, Literal
from uuid import UUID

import structlog

from candleviewer.rules.executor.handlers import Capability, HandlerAnswer, Prepared
from candleviewer.rules.executor.keys import request_sha256
from candleviewer.rules.executor.metrics import ExecutorMetrics
from candleviewer.rules.limits import SIGNAL_MAX_DEPTH_DEFAULT, SIGNAL_QUEUE_BOUND
from candleviewer.rules.scope import ActionRequest

#: The fire keys the bus remembers, so a repeat of one is enqueued once (`fire_key_signal_depth`).
KEYS_REMEMBERED: Final = 1024
#: What `offer` did with a signal: enqueued, a repeat of a key it holds, cut at the depth limit, or
#: refused by the full queue.
Offer = Literal["queued", "repeat", "truncated", "full"]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Signal:
    """One signal (24 §11.5): its owner, the emitting rule's, which namespaces it; its name and
    payload, the IR's own, read-only and never logged; its depth, 1 for a signal no signal caused;
    the emitting rule and the emitting action's fire key."""

    owner: UUID
    name: str
    payload: Mapping[str, Any] = field(repr=False)
    depth: int
    rule_id: str
    dedupe_key: str


class SignalBus:
    """The bounded queue of signals waiting for the runner, which takes them in turn with the
    evaluation queue's ticks; `listen` gives it the runner's wake-up."""

    def __init__(
        self,
        *,
        max_depth: int = SIGNAL_MAX_DEPTH_DEFAULT,
        bound: int = SIGNAL_QUEUE_BOUND,
        metrics: ExecutorMetrics | None = None,
    ) -> None:
        self.max_depth = max_depth
        self._queue: asyncio.Queue[Signal] = asyncio.Queue(maxsize=bound)
        self._keys: OrderedDict[str, None] = OrderedDict()
        self._metrics = ExecutorMetrics() if metrics is None else metrics
        self._episode = False  # a refusal was logged since the queue last ran empty
        self._wake: Callable[[], None] | None = None

    @property
    def waiting(self) -> int:
        return self._queue.qsize()

    def listen(self, wake: Callable[[], None]) -> None:
        self._wake = wake

    def offer(self, signal: Signal) -> Offer:
        """On the dispatch worker, never awaited: `signal` waits for the runner, or is refused."""
        if signal.depth > self.max_depth:
            self._metrics.chain_truncated()
            _log().error(
                "rules.signal_chain_truncated", rule_id=signal.rule_id, depth=signal.depth,
                max_depth=self.max_depth,
            )  # fmt: skip
            return "truncated"
        if signal.dedupe_key in self._keys:
            return "repeat"
        try:
            self._queue.put_nowait(signal)
        except asyncio.QueueFull:
            self._metrics.signal_dropped()
            if not self._episode:
                self._episode = True
                _log().warning("rules.signal_dropped", rule_id=signal.rule_id, waiting=self.waiting)
            return "full"
        self._keys[signal.dedupe_key] = None
        while len(self._keys) > KEYS_REMEMBERED:
            self._keys.popitem(last=False)
        if self._wake is not None:
            self._wake()
        return "queued"

    def take(self) -> Signal | None:
        """The oldest waiting signal, or `None`; the episode ends once the queue runs empty."""
        try:
            signal = self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None
        if self._queue.empty():
            self._episode = False
        return signal

    def clear(self) -> int:
        """Drop the waiting signals at a stop; how many there were."""
        dropped = 0
        while self.take() is not None:
            dropped += 1
        return dropped


#: The answers of an `emit_signal` refused here, each `failed` with its code (24 §11.5).
_REFUSED: Final[Mapping[Offer, str]] = MappingProxyType(
    {"truncated": "signal_chain_truncated", "full": "signal_queue_full"}
)


class EmitSignalHandler:
    """`emit_signal` (24 §11.5): the signal offered to the bus, one level deeper than the signal
    whose evaluation fired the action, and never awaited; `ok` once it waits (or a repeat of its
    fire key), `failed` when the chain is cut or the queue is full. The fingerprint covers the
    name and the depth: an engine-internal action meets no anchor, and its payload rides the
    request as the IR holds it."""

    capability: Capability = "signals"

    def __init__(self, bus: SignalBus) -> None:
        self._bus = bus

    def prepare(
        self, req: ActionRequest, account_id: UUID | None, *, max_notional_usd: Decimal | None
    ) -> Prepared:
        params = req.payload.params
        name, payload = params.get("signal_name"), params.get("payload")
        if not isinstance(name, str) or not name or not isinstance(payload, Mapping | None):
            return Prepared(MappingProxyType({"invalid": True}), request_sha256({}))
        signal = Signal(
            owner=req.owner, name=name, payload=MappingProxyType(dict(payload or {})),
            depth=req.signal_depth + 1, rule_id=req.rule_id, dedupe_key="",
        )  # fmt: skip
        fingerprint = request_sha256({"signal_name": name, "depth": signal.depth})
        return Prepared(MappingProxyType({"signal": signal}), fingerprint)

    async def send(self, prepared: Prepared, *, client_ref: str) -> HandlerAnswer:
        signal = prepared.request.get("signal")
        if not isinstance(signal, Signal):
            return HandlerAnswer("refused", error_code="invalid_params")
        # `client_ref` is the fire key's one-way image: one per action of a fire (24 §11.9).
        offered = self._bus.offer(replace(signal, dedupe_key=client_ref))
        refused = _REFUSED.get(offered)
        return HandlerAnswer("done") if refused is None else HandlerAnswer("refused", refused)
