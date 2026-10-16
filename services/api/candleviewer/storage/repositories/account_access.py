"""Driver-free surface of the account-access grant store (E42-T08, #2648).

`api` may not import a storage driver (ADR-0003), so the routes catch these errors and read
`AccessChange` from here; `account_access_sqlalchemy.py` implements the store. A grant is live
while `can_view` is true. Removing one is a soft revoke (`can_view = can_trade = false`), never a
DELETE, so its freeze state and `max_daily_loss_usd` survive a later re-grant (#965 O4, C-12.5).
A grant write never lowers a freeze: a row it inserts or revives for a frozen manager inherits
the freeze (#2648 Q1).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

#: `AccountAccessGrantInput.level` (22-api-openapi.yaml): `trade` implies `read`.
AccessLevel = Literal["read", "trade"]


class AccessUserNotFoundError(Exception):
    """The user does not exist or is deleted (HTTP 404). Nothing changed."""


class AccessUserNotActiveError(Exception):
    """The user is `invited`, `locked` or `disabled`: grants change only on an `active` user
    (HTTP 409). Nothing changed."""

    def __init__(self, status: str) -> None:
        super().__init__(f"user status is {status}")
        self.status = status


class AccessUnknownAccountError(Exception):
    """An exchange account in the set does not exist or is deleted (HTTP 404). Nothing changed."""

    def __init__(self, account_ids: frozenset[uuid.UUID]) -> None:
        super().__init__(f"{len(account_ids)} unknown exchange account(s)")
        self.account_ids = account_ids


class AccessAuditUnavailableError(Exception):
    """The write-ahead `users.access_change` record could not be written (HTTP 503
    `audit_unavailable`). The transaction rolled back; nothing changed."""


class AccessSelfTargetError(Exception):
    """The actor named their own grants (SR-055, HTTP 403). The route refuses and audits this
    first; the store refuses it again before any statement. Nothing changed."""


class AccessBusyError(Exception):
    """A lock wait outlived the store's `lock_timeout`, or Postgres broke a deadlock (SQLSTATE
    55P03 or 40P01): HTTP 409 `conflict`. Nothing changed; a retry may succeed."""


class AccessPositionsUnknownError(Exception):
    """The change removes a live grant while an open-position or open-order count is unknown,
    and the caller did not acknowledge it (AC7, #965 O2; every removal, #2648 Q2): HTTP 409
    `positions_unknown`. Nothing changed."""


@dataclass(frozen=True, slots=True)
class RemovalContext:
    """The user's exposure as the caller read it before the transaction (#965 O2), under the
    names E42-T04's disable records. A count is `None` while unknown: a failed or timed-out read
    is unknown, never 0. A removal never flattens a position or cancels an order."""

    open_position_count: int | None = None
    open_order_count: int | None = None
    acknowledged_unknown_positions: bool = False

    @property
    def blocks_removal(self) -> bool:
        """An unknown count needs the acknowledgement before any live grant is removed."""
        unknown = self.open_position_count is None or self.open_order_count is None
        return unknown and not self.acknowledged_unknown_positions


class AccessAuditEmitter(Protocol):
    """The subset of `AuditWriter.emit` the store calls; the writer itself satisfies it.
    Injected by the composition root: storage (M10) may not import audit (M19)."""

    async def emit(
        self,
        action: str,
        *,
        actor_label: str,
        actor_user_id: uuid.UUID,
        object_kind: str,
        object_id: str,
        before_state: dict[str, object],
        after_state: dict[str, object],
        request_id: uuid.UUID | None,
        # An `AuditOutcome`, which storage cannot import: `Any`, as in `auth/scopes.py`.
        outcome: Any = ...,
        reason: str | None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class AccessChange:
    """A user's live grants (`exchange_account_id` -> level) before and after a replacement.
    The keys are plain `uuid.UUID`s (never the driver's subclass), so orjson serialises them."""

    user_id: uuid.UUID
    before: Mapping[uuid.UUID, AccessLevel]
    after: Mapping[uuid.UUID, AccessLevel]
    #: Accounts whose grant row is frozen once the change applies. Only a row the change inserts
    #: or revives can become frozen, so a grant live before keeps its flag: the set also
    #: describes `before`.
    frozen: frozenset[uuid.UUID] = frozenset()

    @property
    def changed(self) -> bool:
        """False for an unchanged set: nothing was written or audited, and no push is due."""
        return self.before != self.after

    @property
    def removed(self) -> frozenset[uuid.UUID]:
        """The live grants the change soft-revokes."""
        return frozenset(self.before.keys() - self.after.keys())
