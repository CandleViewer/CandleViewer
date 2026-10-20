"""The `GET /notifications` read model's driver-free half (E40-T04): what one caller may see
(`NotificationScope`), one union row (`NotificationRow`), the event kinds each source serves and
the keyset cursor. The SQL lives in `notifications_sqlalchemy.py`; the API imports only this
module (ADR-0003: M23 never reaches a storage driver).
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

#: Branch ranks (`src`), the keyset's tie-break between sources.
SOURCES: dict[int, str] = {
    1: "alert_deliveries",
    2: "rule_events",
    3: "order_events",
    4: "system_events",
}
#: `rule_events.kind` values that are notifications: an action's outcome or its throttling, not
#: the per-evaluation `condition_eval` / `action_start` / `log` rows.
RULE_EVENT_KINDS: tuple[str, ...] = ("action_ok", "action_fail", "throttled")
#: `order_event_kind` values that are notifications: outcomes, not requests or raw pushes
#: (`local_create`, `submit_attempt`, `*_request`, `exchange_push`, `reconcile_diff` stay out).
#: `kill` (the kill switch took the order) and `adopt` (reconciliation took over an exchange order
#: no row held, for owner review) came with migration 0034.
ORDER_EVENT_KINDS: tuple[str, ...] = (
    "ack", "reject", "fill", "partial_fill", "amend_ack", "cancel_ack", "expire", "error", "kill",
    "adopt",
)  # fmt: skip
_INT64_MAX = 2**63 - 1


@dataclass(frozen=True, slots=True)
class NotificationScope:
    """What one caller may see, per source, already resolved from the caller's permissions and
    grants (`api.notifications.notification_scope`):

    - `alerts`: the caller's own in-app alert records (`alerts:read`);
    - `rules` / `rule_ids`: the events of exactly these rules (`rules:read`, the rules module's
      visibility predicate); an empty set is none;
    - `orders` / `accounts`: order events on these accounts (`orders:read`); `accounts` None is
      every account (the Owner), an empty set none;
    - `system`: the whole `system_events` stream, the Owner's alone (SR-E40T04A-01: no
      role-neutral view of it is approved for Managers or Viewers yet).
    """

    user_id: str
    alerts: bool = False
    rules: bool = False
    rule_ids: frozenset[str] = frozenset()
    orders: bool = False
    accounts: frozenset[str] | None = frozenset()
    system: bool = False

    @property
    def empty(self) -> bool:
        return not (self.alerts or (self.rules and self.rule_ids) or self.orders or self.system)


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
    """Malformed or foreign cursors raise `ValueError` (the router's 400), never a value the
    driver would refuse at bind time: the source rank must be one of `SOURCES`, the id a bigint,
    the timestamp offset-aware and representable in UTC (SR-E40T04A-04, CR-06)."""
    try:
        ts, src, src_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        when = datetime.fromisoformat(ts)
        when.astimezone(UTC)  # year 1 at +14:00 has no UTC instant
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("invalid cursor") from exc
    if (
        when.tzinfo is None
        or type(src) is not int
        or src not in SOURCES
        or type(src_id) is not int
        or not 0 < src_id <= _INT64_MAX
    ):
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
    "ORDER_EVENT_KINDS",
    "RULE_EVENT_KINDS",
    "SOURCES",
    "NotificationRow",
    "NotificationScope",
    "NotificationStore",
    "decode_cursor",
    "encode_cursor",
]
