"""Process-wide read-only degradation gate.

A single, process-wide flag consulted by the OMS validator so an unsafe
binding cannot be routed around: no flag, config, or role may re-enable
order placement while the gate is tripped (mirrors the native-SL invariant
pattern, C-4.14). This module holds only the flag and the human-readable
reason; the OMS validator import and consult it directly, it never lives
inside the OMS module itself (C-2.16-style separation is not applicable
here, but module boundaries per C-3.1 still require the flag to be owned
by `net`, not duplicated).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import structlog


def _logger() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


if TYPE_CHECKING:
    from .binding_check import BindingCheckResult

GateListener = Callable[[bool, "str | None", "str | None"], None]


class ReadOnlyGate:
    """Thread-safe, process-wide read-only flag.

    Defaults to writable (`tripped=False`). Once tripped it stays tripped
    until explicitly cleared by a fresh, passing self-check — never by
    catching an exception or by a request handler.

    `subscribe()` lets the `system` WS topic (or any other consumer) observe
    every trip/clear transition without polling `is_read_only`; this is what
    lets the degraded-mode banner (CMP-092) be published the instant the
    gate trips rather than on the next client poll.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tripped = False
        self._reason_code: str | None = None
        self._reason_text: str | None = None
        self._listeners: list[GateListener] = []
        # E27-T02: a sticky (reason_code, reason_text) set by `latch()`; while set, the gate
        # cannot be cleared and its published reason cannot be replaced.
        self._latched_reason: tuple[str, str] | None = None

    def subscribe(self, listener: GateListener) -> None:
        """Register a callback invoked with `(is_read_only, reason_code,
        reason_text)` on every `trip()`/`clear()` call. Invoked synchronously,
        outside the internal lock, so a listener may itself call back into
        this gate's read-only properties without deadlocking."""
        with self._lock:
            self._listeners.append(listener)

    def _notify(self) -> None:
        with self._lock:
            tripped, reason_code, reason_text = (
                self._tripped,
                self._reason_code,
                self._reason_text,
            )
            listeners = tuple(self._listeners)
        for listener in listeners:
            try:
                listener(tripped, reason_code, reason_text)
            except Exception:
                # A misbehaving listener must never be able to crash the
                # trip()/clear() caller (e.g. the scheduler loop) or prevent
                # the other listeners from being notified. The gate's own
                # state was already updated above, so this stays fail-closed
                # regardless of listener behaviour.
                _logger().exception(
                    "net.read_only_gate: listener raised while handling tripped=%s reason_code=%s",
                    tripped,
                    reason_code,
                )

    def latch(self, *, reason_code: str, reason_text: str) -> None:
        """Trip permanently for this process (E27-T02: KEK unavailable). Overrides any current
        reason; a later passing mesh self-check cannot clear it. Recovery is a restart."""
        with self._lock:
            self._latched_reason = (reason_code, reason_text)
            self._tripped = True
            self._reason_code, self._reason_text = reason_code, reason_text
        self._notify()

    def trip(self, *, reason_code: str, reason_text: str) -> None:
        with self._lock:
            if self._latched_reason is not None:
                return  # already closed with the latched reason
            self._tripped = True
            self._reason_code = reason_code
            self._reason_text = reason_text
        self._notify()

    def clear(self, *, check_result: BindingCheckResult) -> None:
        """Clear the gate, but only given a fresh, *passing* self-check.

        `check_result` must be the `BindingCheckResult` from a self-check
        run that just completed with `safe=True`. A caller cannot clear the
        gate on a whim (e.g. from a request handler, or after merely
        catching an exception) without re-running the check.
        """
        if not check_result.safe:
            raise ValueError(
                "ReadOnlyGate.clear() requires a passing BindingCheckResult "
                f"(got reason_code={check_result.reason_code!r}); the gate stays "
                "tripped until the self-check actually passes."
            )
        with self._lock:
            if self._latched_reason is not None:
                return
            self._tripped = False
            self._reason_code = None
            self._reason_text = None
        self._notify()

    @property
    def is_read_only(self) -> bool:
        with self._lock:
            return self._tripped

    @property
    def reason_code(self) -> str | None:
        with self._lock:
            return self._reason_code

    @property
    def reason_text(self) -> str | None:
        with self._lock:
            return self._reason_text
