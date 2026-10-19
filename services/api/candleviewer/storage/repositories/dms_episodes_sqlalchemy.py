"""Postgres journal of the dead-man's-switch episodes (E27-T04 W5, #837): `system_events` rows.

One unresolved `warning` row (`exchange`, `dms_hook_owed`; no incident, §3.10.2a of 21) per episode,
written before its first hook call, resolved once a call has returned, replayed by a restart while
open. `system_events` has no `env`: every statement filters on the account's in `exchange_accounts`
(C-2.11). Literal `sa.text`, bound parameters; a fixed `message`, and in `details` only the closed
`from_state` and `reason` codes, anything else refused, so unlike `PgSystemEventWriter`'s free text
no row needs the redaction serializer (C-12.6).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Final, NamedTuple
from uuid import UUID

import sqlalchemy as sa

from candleviewer.storage.repositories.accounts import AccountsStoreError
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_ENVS: Final = frozenset({"live", "demo", "testnet"})
#: `accounts.health`'s `HealthState` values and `HealthReason` codes (storage does not import it).
_STATES: Final = frozenset({"healthy", "degraded", "down"})
_REASONS: Final = frozenset("ws_heartbeat rest_only ws_silent no_success never_connected".split())
_MESSAGE: Final = "Dead-man's-switch call owed: the account went down"

_RECORD = sa.text(
    "INSERT INTO system_events (component, kind, severity, exchange_account_id, message, details, "
    "event_ts) SELECT 'exchange', 'dms_hook_owed', CAST('warning' AS severity), ea.id, :message, "
    "CAST(:details AS jsonb), CAST(:at AS timestamptz) FROM exchange_accounts ea "
    "WHERE ea.id = CAST(:account AS uuid) AND ea.env::text = :env RETURNING id"
)
#: The row and its account's older open rows: a replaced episode, or a write whose outcome was lost.
_RESOLVE = sa.text(
    "UPDATE system_events AS se SET resolved_at = now() FROM exchange_accounts ea "
    "WHERE ea.id = se.exchange_account_id AND ea.env::text = :env "
    "AND se.exchange_account_id = CAST(:account AS uuid) AND se.id <= :row "
    "AND se.component = 'exchange' AND se.kind = 'dms_hook_owed' AND se.resolved_at IS NULL"
)
#: The latest open row per account (the episode its monitor would owe), newest first.
_OPEN = sa.text(
    "SELECT row_id, account_id, from_state, reason, at FROM ("
    "SELECT DISTINCT ON (se.exchange_account_id) se.id AS row_id, "
    "se.exchange_account_id::text AS account_id, se.details ->> 'from_state' AS from_state, "
    "se.details ->> 'reason' AS reason, se.event_ts AS at "
    "FROM system_events se JOIN exchange_accounts ea ON ea.id = se.exchange_account_id "
    "WHERE ea.env::text = :env AND se.component = 'exchange' AND se.kind = 'dms_hook_owed' "
    "AND se.resolved_at IS NULL ORDER BY se.exchange_account_id, se.id DESC"
    ") latest ORDER BY row_id DESC LIMIT :limit"
)


class DmsEpisodeRow(NamedTuple):
    row: int
    account_id: UUID
    from_state: str | None
    reason: str | None
    at: datetime


class SqlAlchemyDmsEpisodeJournal:
    def __init__(self, relational: SqlAlchemyRelationalRepository, *, env: str) -> None:
        if env not in _ENVS:  # a misspelt environment would match no account and keep nothing
            raise ValueError("unknown env")
        self._relational, self._env = relational, env

    async def record(self, account_id: UUID, *, from_state: str, reason: str, at: datetime) -> int:
        """The new row's id; an account that is not one of this environment's is an error."""
        if from_state not in _STATES or reason not in _REASONS:
            raise AccountsStoreError("an episode is recorded by its closed codes only")
        details = json.dumps({"from_state": from_state, "reason": reason}, sort_keys=True)
        params = {"account": str(account_id), "env": self._env, "message": _MESSAGE}
        async with self._relational.unit_of_work() as uow:
            res = await uow.session.execute(_RECORD, {**params, "details": details, "at": at})
            row = res.scalar_one_or_none()
            if row is None:
                raise AccountsStoreError("no account of this environment to record an episode for")
            await uow.commit()
        return int(row)

    async def resolve(self, account_id: UUID, row: int) -> None:
        params = {"account": str(account_id), "env": self._env, "row": row}
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_RESOLVE, params)
            await uow.commit()

    async def open_episodes(self, limit: int) -> tuple[DmsEpisodeRow, ...]:
        async with self._relational.unit_of_work() as uow:  # a read: nothing to commit
            res = await uow.session.execute(_OPEN, {"env": self._env, "limit": limit})
            return tuple(
                DmsEpisodeRow(
                    int(m["row_id"]), UUID(m["account_id"]), m["from_state"], m["reason"], m["at"]
                )
                for m in res.mappings()
            )
