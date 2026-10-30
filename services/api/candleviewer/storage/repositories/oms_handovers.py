"""Driver-free hand-over store surface (E29-T06 #914 PR 1; 21 Sec.3.3.12).

`oms_handovers` (21 Sec.3.3.12, 24 Sec.8.3 rule 7) keeps, for the next reconciliation pass, the
orders a lookup or a reconciliation mismatch finds under a row's id that are not that row's
(SR-E29-03), and the trade executions no row takes. An entry holds the normalised order or
execution (`record`, 24 Sec.14.4, as JSON) and, where its writer has one, the raw exchange message
(`payload`), redacted before it is bound. `oms_handovers_sqlalchemy.py` is the Postgres side; the
OMS reaches it through `oms.handovers`, which serves the ports E29-T04 and E29-T05 write through.

`NewHandover` refuses what the table's CHECKs would refuse before any statement runs, naming the
rule and never a value: the kinds and sources, the key that goes with each kind, ids of 1 to 64
characters with no control character, and a `record` that names the entry's own account, order
and fill (C-2.11). The store keeps at most `MAX_HANDOVERS_PER_ACCOUNT` entries per account and
refuses an append past it with `HandoverStoreFull`, never dropping one silently (C-2.18).
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol, get_args
from uuid import UUID

HandoverKind = Literal["order", "execution"]
#: Who handed the entry over: the private stream (E29-T05), a lookup of the command port
#: (E29-T04), or the reconciliation pass (E29-T06).
HandoverSource = Literal["ws_private", "rest", "reconcile"]
#: What an append did: a new entry, an entry already held left as it was, or an empty read counted
#: on the execution entry already held (24 Sec.8.5 step 3d).
AppendOutcome = Literal["added", "held", "counted"]
HANDOVER_KINDS: Final[frozenset[str]] = frozenset(get_args(HandoverKind))
HANDOVER_SOURCES: Final[frozenset[str]] = frozenset(get_args(HandoverSource))
#: 21 Sec.3.3.12: the entries one account may hold, decided ones included (C-2.18).
MAX_HANDOVERS_PER_ACCOUNT: Final = 1_000
#: `oh_ids`: an exchange order id or an `exec_id` is text of 1 to 64 characters.
MAX_KEY_LEN: Final = 64
#: Control characters (Unicode `Cc`), which no id the exchange sends holds: one is hostile or
#: malformed data, and Postgres refuses NUL in a text column.
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class HandoverStoreFull(Exception):
    """The account holds `MAX_HANDOVERS_PER_ACCOUNT` entries: the append is refused, nothing is
    written, and the caller logs, counts and pages it (21 Sec.3.3.12's overflow policy)."""


def _key(raw: object, rule: str) -> None:
    if not isinstance(raw, str) or not 0 < len(raw) <= MAX_KEY_LEN or _CONTROL.search(raw):
        raise ValueError(f"oh_ids: {rule} is not text of 1 to {MAX_KEY_LEN} characters")


@dataclass(frozen=True, slots=True, kw_only=True)
class NewHandover:
    """An `oms_handovers` entry to append; the store assigns `id`, and the database `created_at`
    and, for an empty read, `first_empty_read_at`. `record` and `payload` are read-only copies,
    so nothing between these checks and the insert changes them."""

    exchange_account_id: UUID
    kind: HandoverKind
    exchange_order_id: str
    source: HandoverSource
    record: Mapping[str, Any]
    exec_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    empty_read: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.exchange_account_id, UUID):
            raise ValueError("record: the entry names no account id")
        if self.kind not in HANDOVER_KINDS:
            raise ValueError("oh_kind: the kind is neither order nor execution")
        if self.source not in HANDOVER_SOURCES:
            raise ValueError("oh_source: the source is not a hand-over's writer")
        if (self.kind == "execution") != (self.exec_id is not None):
            raise ValueError("oh_exec: an execution, and only one, names its exec_id")
        _key(self.exchange_order_id, "exchange_order_id")
        if self.exec_id is not None:
            _key(self.exec_id, "exec_id")
        if not isinstance(self.record, Mapping):
            raise ValueError("oh_record: the record is not an object")
        if not isinstance(self.payload, Mapping):
            raise ValueError("oh_payload: the payload is not an object")
        if self.empty_read and self.kind != "execution":
            raise ValueError("oh_reads: empty_read is an execution's alone")
        names = (str(self.exchange_account_id), self.exchange_order_id)
        if (self.record.get("account_id"), self.record.get("exchange_order_id")) != names or (
            self.exec_id is not None and self.record.get("exec_id") != self.exec_id
        ):
            raise ValueError("oh_record: the record names another account, order or fill")
        object.__setattr__(self, "record", MappingProxyType(dict(self.record)))
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True, slots=True, kw_only=True)
class HandoverRow:
    """One `oms_handovers` row, every column in table order."""

    id: int
    exchange_account_id: UUID
    kind: HandoverKind
    exchange_order_id: str
    exec_id: str | None
    source: HandoverSource
    record: Mapping[str, Any]
    payload: Mapping[str, Any]
    empty_reads: int
    first_empty_read_at: datetime | None
    decided_at: datetime | None
    created_at: datetime


class OmsHandoverStore(Protocol):
    """Account-scoped writes and reads of `oms_handovers` (C-12.4). Each call is one transaction of
    its own, capped by the OMS statement timeout, and its caller bounds it (C-2.18)."""

    async def append(self, entry: NewHandover) -> AppendOutcome:
        """Keep *entry* for the next pass, under the account's lock: idempotent on (account,
        orderId) or (account, exec_id), an execution's `empty_read` counted on the entry held;
        `HandoverStoreFull` past the bound, with nothing written."""
        ...

    async def pending(self, account_id: UUID, kind: HandoverKind) -> tuple[HandoverRow, ...]:
        """The account's entries of *kind*, in append order, at most the bound."""
        ...

    async def decide(self, account_id: UUID, exec_id: str) -> bool:
        """Mark an unpaired fill decided, once: True when this call stamped it."""
        ...

    async def prune(self, account_id: UUID, ids: Collection[int]) -> int:
        """Delete the account's entries *ids* (a paired fill, an order with a row): how many."""
        ...
