"""Driver-free surface of the account-access grant store (E42-T08, #2648).

`api` may not import a storage driver (ADR-0003), so the routes catch these errors and read
`AccessChange` from here; `account_access_sqlalchemy.py` implements the store. A grant is live
while `can_view` is true. Removing one is a soft revoke (`can_view = can_trade = false`), never a
DELETE, so its freeze state and `max_daily_loss_usd` survive a later re-grant (#965 O4, C-12.5).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

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


class AccessAuditEmitter(Protocol):
    """The subset of `AuditWriter.emit` the store calls. Injected by the composition root:
    storage (M10) may not import audit (M19), so `outcome` is an `AuditOutcome` value."""

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
        outcome: str,
        reason: str | None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class AccessChange:
    """A user's live grants (`exchange_account_id` -> level) before and after a replacement.
    The keys are plain `uuid.UUID`s (never the driver's subclass), so orjson serialises them."""

    user_id: uuid.UUID
    before: Mapping[uuid.UUID, AccessLevel]
    after: Mapping[uuid.UUID, AccessLevel]

    @property
    def changed(self) -> bool:
        """False for an unchanged set: nothing was written or audited, and no push is due."""
        return self.before != self.after
