"""The `GET /notifications` read model's driver-free half (E40-T04): what one caller may see
(`NotificationScope`), one union row (`NotificationRow`) and the keyset cursor. The SQL lives in
`notifications_sqlalchemy.py`; the API imports only this module (ADR-0003: M23 never reaches a
storage driver).
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

#: Branch ranks (`src`), the keyset's tie-break between sources.
SOURCES: dict[int, str] = {
    1: "alert_deliveries",
    2: "rule_events",
    3: "order_events",
    4: "system_events",
}
KIND_OF_SOURCE: dict[int, str] = {1: "alert", 2: "rule", 3: "order", 4: "system"}
RULE_EVENT_KINDS = ("action_ok", "action_fail", "throttled")
ORDER_EVENT_KINDS = (
    "ack", "reject", "fill", "partial_fill", "amend_ack", "cancel_ack", "expire", "error",
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class NotificationScope:
    """What one caller may see, per source. `rule_ids` / `accounts` None means every rule /
    every account (the Owner); an empty set means none."""

    user_id: str
    alerts: bool = False
    rules: bool = False
    rule_ids: frozenset[str] | None = frozenset()
    orders: bool = False
    accounts: frozenset[str] | None = frozenset()
    system: bool = False
    system_all: bool = False

    @property
    def empty(self) -> bool:
        return not (self.alerts or self.rules or self.orders or self.system)


@dataclass(frozen=True, slots=True)
class NotificationRow:
    """One union row, before `api.notifications` shapes it into a `Notification`."""

    nkind: str
    src: int
    src_id: int
    ts: datetime
    severity: str | None
    title: str | None
    body: str | None
    read_at: datetime | None
    symbol: str | None
    account_id: str | None
    source_uuid: str | None
    event: str
    code: str | None


def encode_cursor(row: NotificationRow) -> str:
    raw = json.dumps([row.ts.isoformat(), row.src, row.src_id]).encode()
    return base64.urlsafe_b64encode(raw).decode()


def decode_cursor(cursor: str) -> tuple[datetime, int, int]:
    """Malformed or foreign cursors raise `ValueError` (the router's 400)."""
    try:
        ts, src, src_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        when = datetime.fromisoformat(ts)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid cursor") from exc
    if when.tzinfo is None or src not in SOURCES or not isinstance(src_id, int) or src_id < 0:
        raise ValueError("invalid cursor")
    return when, src, src_id


class NotificationStore(Protocol):
    async def list_page(
        self,
        scope: NotificationScope,
        *,
        unread_only: bool = False,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[NotificationRow], NotificationRow | None]:
        """Newest first: the page and, when there is more, the row the next cursor encodes."""
        ...


__all__ = [
    "KIND_OF_SOURCE",
    "ORDER_EVENT_KINDS",
    "RULE_EVENT_KINDS",
    "SOURCES",
    "NotificationRow",
    "NotificationScope",
    "NotificationStore",
    "decode_cursor",
    "encode_cursor",
]
