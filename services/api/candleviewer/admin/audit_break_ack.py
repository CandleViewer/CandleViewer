"""The host-console acknowledgement of an audit-chain break (#2904, ruling BQ-256; SR-086's
console fallback): the flow behind `python -m candleviewer.audit_ack_break`.

The entry point imports no `audit` (C-3.3), so this M21 module composes the run over the CLI's
Postgres side (`AckStores`, M10's `SqlAlchemyAuditAckDatabase`): it reads the chain's halt records
(`audit.break_halt.read_halt_view`), checks that the named Owner is an active Owner, and runs
`audit.break_halt.acknowledge_break`, whose record goes straight into `audit_log` (the chain's
advisory lock serialises it with cv-api's appends). Every cv-api process clears the halt at its
next re-read of the chain, within `REFRESH_INTERVAL_S`.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Final, Protocol

from candleviewer.audit.actions import validate_action
from candleviewer.audit.break_halt import (
    READ_TIMEOUT_S,
    AckOutcome,
    AckRequest,
    BreakIdentity,
    acknowledge_break,
    read_halt_view,
)
from candleviewer.audit.models import AuditEmission, storable
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.redact import redact
from candleviewer.audit.repository import AuditRepository

__all__ = [
    "CONSOLE_ACTOR",
    "AckOutcome",
    "AckStores",
    "ActiveOwners",
    "BreakIdentity",
    "ConsoleAckUnavailable",
    "acknowledge_from_console",
]

#: Every console acknowledgement's `actor_label`; the Owner is its `actor_user_id`.
CONSOLE_ACTOR: Final = "console:owner"


class ActiveOwners(Protocol):
    async def find_active_owner(self, identifier: str) -> str | None: ...


class AckStores(Protocol):
    @property
    def audit_log(self) -> AuditRepository: ...

    @property
    def owners(self) -> ActiveOwners: ...

    async def reachable(self) -> bool: ...


class ConsoleAckUnavailable(RuntimeError):
    """Postgres unreachable, or the halt records unreadable: nothing was written."""


async def acknowledge_from_console(
    stores: AckStores, *, owner: str, identity: BreakIdentity, reason: str
) -> AckOutcome:
    """One acknowledgement by `owner` (a username or email) of the break `identity`. Raises
    `ConsoleAckUnavailable` before any record when the store cannot be read."""
    if not await stores.reachable():
        raise ConsoleAckUnavailable("postgres unreachable")
    owner_id = await stores.owners.find_active_owner(owner)
    query = AuditQueryService(stores.audit_log)
    try:
        async with asyncio.timeout(READ_TIMEOUT_S):
            view = await read_halt_view(query)
    except Exception as exc:  # unread: refuse before any record
        raise ConsoleAckUnavailable(type(exc).__name__) from exc
    finally:
        query.close()
    request = AckRequest(
        identity=identity,
        reason=reason,
        actor_user_id=None if owner_id is None else uuid.UUID(owner_id),
        actor_label=CONSOLE_ACTOR,
    )
    emit = _direct_emit(stores.audit_log)
    return await acknowledge_break(
        request, is_owner=owner_id is not None, engaged=view.halted, emit=emit
    )


def _direct_emit(repository: AuditRepository) -> Callable[..., Awaitable[None]]:
    """A record built as `AuditWriter.build` builds one (registered action, redacted states, a
    new `record_id`, `event_ts` read once), committed by the repository's `insert` (the chain's
    one locked writer, as break-glass's direct trail uses) before it returns."""

    async def emit(action: str, **fields: Any) -> None:
        validate_action(action)
        states = {key: redact(fields.get(key)) for key in ("before_state", "after_state")}
        emission = AuditEmission(
            record_id=uuid.uuid4(), action=action, event_ts=datetime.now(UTC), **(fields | states)
        )
        await repository.insert(storable(json.loads(emission.model_dump_json())))

    return emit
