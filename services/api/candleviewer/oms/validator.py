"""Order validator enforcing the process-wide read-only gate (E09-T04 AC3).

"Read-only mode is a single process-wide flag consulted by the OMS
validator (`20-architecture.md` §3.x `Validator`) so it cannot be bypassed by
any route" (ticket Technical notes). This module never imports
`candleviewer.net` (M14's §3 allow-list does not include it): the read-only
flag is injected as a structurally-typed `ReadOnlyCheck` at construction time
by the composition root (`candleviewer.app`), which *is* allowed to import
both M14 and the `net` package. Mirrors the `SecretsHandle`/`AuditHandle`
type-alias pattern `admin.wiring` already uses to avoid a direct import edge.
"""

from __future__ import annotations

from typing import Protocol

from .errors import TradingDisabled


class ReadOnlyCheck(Protocol):
    """Structural type for `candleviewer.net.ReadOnlyGate` — no import edge.

    Any object exposing `is_read_only`/`reason_code`/`reason_text` satisfies
    this (the real `ReadOnlyGate`, or a test fake), so `oms` never has a
    static or runtime import of the `net` package.
    """

    @property
    def is_read_only(self) -> bool: ...

    @property
    def reason_code(self) -> str | None: ...

    @property
    def reason_text(self) -> str | None: ...


class OrderPlacementRefused(TradingDisabled):
    """Raised when an order-opening command is rejected because the process
    is in read-only degraded mode (a public/off-mesh binding was detected):
    `403 trading_disabled` with no reason (`errors.PROBLEMS`). `reason_code` and
    `reason_text` are the gate's own, for the log; the answer's detail is fixed.
    """

    default_detail = "Order entry is paused: the terminal is read-only."

    def __init__(self, *, reason_code: str | None, reason_text: str | None) -> None:
        self.reason_code = reason_code or "net.read_only"
        self.reason_text = reason_text or "The trading terminal is in read-only mode."
        super().__init__()


class Validator:
    """OMS command validator boundary (`20-architecture.md` §3 `Validator`).

    Only the read-only gate check is implemented here (E09-T04's scope);
    instrument filters, RBAC scope, environment match and risk caps are
    owned by later OMS tickets and are layered onto this same `validate()`
    entry point, never bypassing it.
    """

    def __init__(self, *, read_only_gate: ReadOnlyCheck) -> None:
        self._read_only_gate = read_only_gate

    def assert_order_placement_allowed(self) -> None:
        """Raise `OrderPlacementRefused` if the process is read-only.

        Called before any position-opening order is accepted, per the
        ticket's "Read-only degradation" scope: order placement is disabled
        at the OMS boundary while the gate is tripped, and this check cannot
        be routed around by any other entry point because every order path
        must call it (no flag, config, or role may re-enable placement).
        """
        if self._read_only_gate.is_read_only:
            raise OrderPlacementRefused(
                reason_code=self._read_only_gate.reason_code,
                reason_text=self._read_only_gate.reason_text,
            )
