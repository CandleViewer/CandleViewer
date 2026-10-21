"""Driver-free port for the permanent replay anchor (E29-T04 #913; 21-database-schema.md
Sec.3.3.10, revision `0043_order_submission`, M10).

Stdlib only, with the sibling port `orders`, so M14 (`oms`) types against it with no storage
driver (ADR-0003); `idempotency_anchors_sqlalchemy.py` is the Postgres implementation, and the
first persist that inserts an anchor is `submissions.py`'s.

The anchor is SR-E29-07's permanent record of an order-creating request: its principal, its
operation, the client's `Idempotency-Key` as canonical lower-case UUID text (`client_ref`) and the
request fingerprint (`request_sha256`), the rows it created and, once decided, its first answer.
`client_ref` and `request_sha256` are class P1 (21 Sec.12): they are written once and never read
back. `find` matches (`created_by`, `operation`, `client_ref`), so another principal's key reads as
missing, and compares the fingerprint in SQL, answering only whether it matches (`body_matches`).
An outcome is recorded once, by compare-and-set from NULL (`ia_decided`, `trg_ia_write_once`).

Every value a writer gives is refused, before any statement, by the rule the table would refuse
it with (`ia_ref_fmt`, the `sha256_hex` domain, `ia_target`, `ia_decided`, `ia_code`,
`ia_ret_code`), and no error names a value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Literal, Protocol, get_args
from uuid import UUID

from candleviewer.storage.repositories.orders import require_aware

__all__ = [
    "MAX_RET_CODE", "MIN_RET_CODE", "UX_IA_PRINCIPAL_REF", "AnchorOperation", "AnchorOutcome",
    "AnchorRow", "AnchorStatus", "IdempotencyAnchorStore", "NewAnchor", "require_client_ref",
    "require_fingerprint",
]  # fmt: skip

#: The operations that keep a permanent anchor (`ia_operation`): `placeOrder`, and E29-T07's
#: order-creating position routes (OM-T11).
AnchorOperation = Literal["placeOrder", "closePosition", "reversePosition", "closeAllPositions"]
#: The first answers `placeOrder` records (21 Sec.3.3.10 "Writes"): `202`, the `429` of a create
#: the trading port sent nothing for, and a business rejection's `502`.
AnchorStatus = Literal[202, 429, 502]
#: The unique constraint that scopes a key to its principal and operation (21 Sec.3.3.10).
UX_IA_PRINCIPAL_REF: Final = "ux_ia_principal_ref"
#: `outcome_ret_code` is a Postgres `integer`.
MIN_RET_CODE: Final = -(2**31)
MAX_RET_CODE: Final = 2**31 - 1
_SHA256: Final = re.compile(r"[0-9a-f]{64}")
#: `ia_code`: an `x-error-codes` slug.
_CODE: Final = re.compile(r"[a-z][a-z0-9_]{1,63}")
_OPERATIONS: Final = frozenset(get_args(AnchorOperation))
_STATUSES: Final = frozenset(get_args(AnchorStatus))


def require_client_ref(client_ref: str) -> None:
    """`ia_ref_fmt`: the canonical lower-case UUID text, `str(UUID(key))`, nothing else."""
    try:
        canonical = str(UUID(client_ref))
    except (TypeError, ValueError, AttributeError):
        canonical = None
    if canonical != client_ref:
        raise ValueError("client_ref must be canonical lower-case UUID text (ia_ref_fmt)")


def require_fingerprint(request_sha256: str) -> None:
    """The `sha256_hex` domain: 64 lower-case hex digits."""
    if not isinstance(request_sha256, str) or _SHA256.fullmatch(request_sha256) is None:
        raise ValueError("request_sha256 must be 64 lower-case hex digits (sha256_hex)")


@dataclass(frozen=True, slots=True, kw_only=True)
class NewAnchor:
    """An `idempotency_anchors` row to insert, last in the first persist's transaction. `id` is
    the server's; `created_by` is the authenticated principal's id (or the rule owner's, M15),
    never a client value. It names exactly one target for `placeOrder` (`ia_target`): an entry's
    one-leg group, or the order of a request that created no group."""

    id: UUID
    created_by: UUID
    operation: AnchorOperation
    client_ref: str = field(repr=False)
    request_sha256: str = field(repr=False)
    trade_group_id: UUID | None = None
    order_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.operation not in _OPERATIONS:
            raise ValueError("operation is not an anchored operation (ia_operation)")
        require_client_ref(self.client_ref)
        require_fingerprint(self.request_sha256)
        targets = (self.trade_group_id is not None) + (self.order_id is not None)
        if targets > 1 or (self.operation == "placeOrder" and targets != 1):
            raise ValueError("a placeOrder anchor names one group or one order (ia_target)")


@dataclass(frozen=True, slots=True, kw_only=True)
class AnchorOutcome:
    """The first answer of the anchored request, recorded once (`ia_decided`): `code` is its
    problem code when it was a refusal, and `ret_code` the exchange's `retCode` of an
    `exchange_error` only (`ia_code`, `ia_ret_code`)."""

    status: AnchorStatus
    decided_at: datetime
    code: str | None = None
    ret_code: int | None = None

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError("status is not an answer the anchor records (ia_decided)")
        require_aware("decided_at", self.decided_at)
        refused = self.status >= 400
        if refused != (self.code is not None):
            raise ValueError("a refusal, and only one, carries its problem code (ia_code)")
        if self.code is not None and _CODE.fullmatch(self.code) is None:
            raise ValueError("code must be an x-error-codes slug (ia_code)")
        if self.ret_code is not None:
            if self.code != "exchange_error":
                raise ValueError("ret_code comes only with an exchange_error (ia_ret_code)")
            if isinstance(self.ret_code, bool) or not MIN_RET_CODE <= self.ret_code <= MAX_RET_CODE:
                raise ValueError("ret_code must be an integer the column holds")


@dataclass(frozen=True, slots=True)
class AnchorRow:
    """One anchor as `find` reads it: every column but `client_ref` and `request_sha256`, which
    are never read back (SR-E29-07), and whether the stored fingerprint equals the one given."""

    id: UUID
    created_by: UUID
    operation: AnchorOperation
    trade_group_id: UUID | None
    order_id: UUID | None
    outcome_status: int | None
    outcome_code: str | None
    outcome_ret_code: int | None
    created_at: datetime
    decided_at: datetime | None
    body_matches: bool


class IdempotencyAnchorStore(Protocol):
    """The anchor's reads and its one update. No route reaches it: the OMS calls it after its own
    admission (scope and arm, 22 Idempotency)."""

    async def find(
        self,
        created_by: UUID,
        operation: AnchorOperation,
        client_ref: str,
        request_sha256: str,
    ) -> AnchorRow | None:
        """This principal's anchor of the key on the operation, and whether its fingerprint is
        `request_sha256`; `None` when there is none (another principal's key reads as missing).
        `ValueError` for a key or fingerprint the table could not hold, before any statement."""
        ...

    async def record_outcome(self, anchor_id: UUID, outcome: AnchorOutcome) -> bool:
        """Record the first answer by compare-and-set from NULL: True when this call recorded it,
        False when an outcome was recorded already (or no such anchor), with nothing written."""
        ...
