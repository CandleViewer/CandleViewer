"""The shared synchronous order-entry gate vocabulary (#837 Q5, E42-T03 / E27-T04).

One composed gate refuses an order before any OMS work (C-2.21). Each check is synchronous and
O(1), does no I/O and never queries an interpreter: it reads a plain bool or enum that its monitor
publishes on transition (C-2.20). The gate is a safety invariant, so no flag ever gates it
(C-4.14). It guards submissions that open or increase exposure and the amends that raise risk
(quantity up, stop loosened, trigger re-armed), never a cancel, a close, a quantity-reducing amend
or a stop-tightening amend (C-2.6). Attaching a missing native SL, tightening a stop, or re-arming
a protective trigger is never gated; "trigger re-armed" above means an exposure-increasing (entry)
trigger. An amend with any risk-increasing component is gated. `candleviewer.api.order_entry_gate`
states the scope, and the caller classifies the operation, because the gate never inspects it.

`OrderEntryGate(maintenance, *account_checks)` is built once at the composition root and is
frozen: the maintenance check comes first by construction, the checks are kept as a tuple (so the
order is fixed and a reused gate never runs dry), and `maintenance` is a required argument (the
type-checker rejects a call without it, and an explicit `None` raises `ValueError`). The first slot
is typed as the generic `OrderEntryCheck` because this kernel cannot import the admin
`MaintenanceGate`, so it is marked structurally instead: the gate requires `scope == "global"` on
that argument, which `MaintenanceGate` declares, and an account check in the slot raises
`TypeError`. That is a runtime guard, not a static type, and it keeps an account check out of the
slot; passing the `MaintenanceGate` itself remains the composition root's job. Every call names
the target account (`account_id: UUID`, never `None`), so the per-account checks always run. A
check that raises propagates: the route answers a redacted 500 and the order is never admitted; an
exception is never turned into a refusal or an admit.

These types live in the shared kernel (`candleviewer.domain`, importable by every module) so the
admin maintenance gate and the accounts checks can return a refusal without importing the API
layer; `candleviewer.api.order_entry_gate` re-exports them and renders the 403 problem.
`REFUSAL_REASONS` is the closed set the contract (`trading_disabled` `reason`, #2592) and
`24-internal-schemas.md` list; a refusal with any other reason is refused when it is built.

`detail` is short human text, a constant authored in code: never user input, and never logged (the
API edge logs `reason` and `account_id` only; the caller does receive it in the problem body). Its
guard is a tripwire for UUID- and hex-id-shaped text in either case, not a secret scanner: it
catches an id pasted into a message by mistake and nothing more.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal, Protocol, get_args
from uuid import UUID

RefusalReason = Literal[
    "maintenance", "account_disabled_by_policy", "no_active_key", "account_unhealthy"
]
REFUSAL_REASONS: Final[frozenset[str]] = frozenset(get_args(RefusalReason))
DETAIL_MAX_LEN: Final = 200
#: A tripwire for a UUID or a long hex id in `detail` (8-4-4-4 hex digits, either case).
_ID_SHAPED: Final = re.compile(r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}")


@dataclass(frozen=True, slots=True)
class OrderEntryRefusal:
    reason: RefusalReason
    detail: str

    def __post_init__(self) -> None:
        if self.reason not in REFUSAL_REASONS:
            raise ValueError(f"unknown order-entry refusal reason {self.reason!r}")
        if not self.detail.strip() or len(self.detail) > DETAIL_MAX_LEN:
            raise ValueError(f"a refusal detail is 1-{DETAIL_MAX_LEN} characters of human text")
        if _ID_SHAPED.search(self.detail):
            raise ValueError("a refusal detail never carries an id")


class OrderEntryCheck(Protocol):
    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        """Synchronous, O(1), no I/O: `None` lets the order through."""


@dataclass(frozen=True, slots=True, init=False)
class OrderEntryGate:
    """The composed gate: the maintenance check first, then the account checks in the order
    given; the first refusal wins and the remaining checks are not consulted."""

    checks: tuple[OrderEntryCheck, ...]

    def __init__(self, maintenance: OrderEntryCheck, *account_checks: OrderEntryCheck) -> None:
        if maintenance is None:  # the type-checker rejects it; this guards an untyped caller
            raise ValueError("an order-entry gate needs its maintenance check first")
        if getattr(maintenance, "scope", None) != "global":
            raise TypeError("the first order-entry check must be the global maintenance check")
        checks = (maintenance, *account_checks)
        for check in checks:
            if not callable(getattr(check, "refusal", None)):
                raise TypeError(f"not an order-entry check: {type(check).__name__}")
        object.__setattr__(self, "checks", checks)

    def refusal(self, account_id: UUID) -> OrderEntryRefusal | None:
        if not isinstance(account_id, UUID):
            raise TypeError("the order-entry gate needs the target account id")
        for check in self.checks:
            refusal = check.refusal(account_id)
            if refusal is not None:
                return refusal
        return None
