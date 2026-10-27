"""Postgres adapter for `DefinitionStore` and `DefinitionReads` (E28-T05 #909; M10).

SQLAlchemy Core over the 0039 definition tables (21 Sec.3.3.3a), every value bound. A unit of
work is the trade-group store's: its statement cap, its failure mapping by name (here
`DEFINITION_RULES` and `DEFINITION_CONFLICTS`) and, for an `OwnerScope`, the live-owner gate
before anything else; a write takes an `OwnerScope` only, whose user it stores as the writer.
`replace` and `soft_delete` lock the live row `FOR UPDATE` first (SEC-2-03, 21 Sec.3.3.3a): a
soft-deleted one is not found, a racing write waits for the commit. A create or replace then locks
its members' accounts `FOR SHARE` in id order and refuses one not live, as the fired-group store
does for legs. `replace` binds `env`, which `trg_tgd_write_once` refuses to change; the touch
trigger moves `updated_at`. A read, and its members statement, carries `group_visible` with
`DEFINITION_VISIBLE`: a grant reads a definition with all its members or not at all.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import fields
from datetime import datetime
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from candleviewer.db.models import trade_group_definition_members, trade_group_definitions
from candleviewer.storage.repositories import trade_group_definitions as port
from candleviewer.storage.repositories import trade_groups_sqlalchemy as groups
from candleviewer.storage.repositories.accounts import AccountScope, GrantScope, OwnerScope
from candleviewer.storage.repositories.orders_sqlalchemy import OMS_STATEMENT_TIMEOUT_MS
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    SqlAlchemyUnitOfWork,
)
from candleviewer.storage.repositories.trade_groups import ACCOUNT_NOT_LIVE
from candleviewer.storage.repositories.user_roles_sqlalchemy import (
    WRITE_AHEAD_TIMEOUT_S,
    bounded_write_ahead,
)

_D, _M = trade_group_definitions.c, trade_group_definition_members.c
#: SR-E28-21 over the enclosing definition, built once: `trade_groups_sqlalchemy._GRANT_VISIBLE`
#: over its members for a group's legs (unit-pinned).
DEFINITION_VISIBLE: Final = sa.text(
    "(EXISTS (SELECT 1 FROM trade_group_definition_members vl "
    "WHERE vl.definition_id = trade_group_definitions.id) "
    "AND NOT EXISTS (SELECT 1 FROM trade_group_definition_members vl "
    "WHERE vl.definition_id = trade_group_definitions.id "
    "AND NOT (vl.exchange_account_id = ANY(CAST(:granted AS uuid[])) "
    "AND EXISTS (SELECT 1 FROM exchange_accounts vea WHERE vea.id = vl.exchange_account_id "
    "AND vea.deleted_at IS NULL) "
    "AND EXISTS (SELECT 1 FROM user_account_access uaa WHERE uaa.user_id = CAST(:caller AS uuid) "
    "AND uaa.exchange_account_id = vl.exchange_account_id AND uaa.can_view AND NOT uaa.frozen))))"
)
#: A member's account `env` and `is_enabled`, read as text like the predicate's own account check:
#: the identity guard of #2333 and #3968 pins the modules that name the `exchange_accounts` Table.
_ACCOUNTS: Final = (
    sa.text("SELECT id, env, is_enabled FROM exchange_accounts")
    .columns(id=sa.Uuid, env=sa.Text, is_enabled=sa.Boolean)
    .subquery("ea")
)
_REFUSALS: Final = dict.fromkeys(port.DEFINITION_RULES, port.DefinitionRuleError) | dict.fromkeys(
    port.DEFINITION_CONFLICTS, port.DefinitionConflictError
)


def definition_statement(scope: AccountScope, definition_id: UUID) -> sa.Select[Any]:
    """The live definition when `scope` sees it: every column but `deleted_at`."""
    visible = groups.group_visible(scope, grant_visible=DEFINITION_VISIBLE)
    columns = (_D[f.name] for f in fields(port.DefinitionRow))
    return sa.select(*columns).where(_D.id == definition_id, _D.deleted_at.is_(None), visible)


def members_statement(scope: AccountScope, definition_id: UUID) -> sa.Select[Any]:
    """Its members under the same predicate, each with its account's `env` and `is_enabled`."""
    ea = _ACCOUNTS.c
    joined = trade_group_definition_members.join(trade_group_definitions).join(
        _ACCOUNTS, ea.id == _M.exchange_account_id
    )
    visible = groups.group_visible(scope, grant_visible=DEFINITION_VISIBLE)
    stmt = sa.select(_M.exchange_account_id, _M.enabled, ea.env, ea.is_enabled).select_from(joined)
    stmt = stmt.where(_D.id == definition_id, _D.deleted_at.is_(None), visible)
    return stmt.order_by(_M.exchange_account_id)


def lock_statement(definition_id: UUID) -> sa.Select[Any]:
    """The live row's `updated_at`, `FOR UPDATE` (SEC-2-03, 21 Sec.3.3.3a)."""
    live = sa.select(_D.updated_at).where(_D.id == definition_id, _D.deleted_at.is_(None))
    return live.with_for_update()


def members_upsert_statement(new: port.NewDefinition, writer: UUID) -> sa.Insert:
    """Each member; one stored with another `enabled` takes this one and `updated_by`."""
    rows = [
        {"definition_id": new.id, "exchange_account_id": m.exchange_account_id,
         "enabled": m.enabled, "created_by": writer, "updated_by": writer}
        for m in new.members
    ]  # fmt: skip
    stmt = pg_insert(trade_group_definition_members).values(rows)
    return stmt.on_conflict_do_update(
        index_elements=[_M.definition_id, _M.exchange_account_id],
        set_={"enabled": stmt.excluded.enabled, "updated_by": stmt.excluded.updated_by},
        where=_M.enabled.is_distinct_from(stmt.excluded.enabled),
    )


class SqlAlchemyDefinitionStore:
    """`DefinitionStore` and `DefinitionReads` over one relational repository (asyncpg), each
    statement capped at `OMS_STATEMENT_TIMEOUT_MS`, lock waits included: a write that waits longer
    on another's row lock leaves as `StorageQueryFailed('57014')`, having written nothing."""

    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    @asynccontextmanager
    async def _unit_of_work(
        self, scope: AccountScope, *, write: bool = False
    ) -> AsyncIterator[SqlAlchemyUnitOfWork]:
        if write and not isinstance(scope, OwnerScope):  # a grant neither writes nor skips the gate
            raise port.DefinitionScopeDeniedError
        with groups.constraints(_REFUSALS):
            async with self._relational.unit_of_work() as uow:
                cap = {"timeout": str(OMS_STATEMENT_TIMEOUT_MS)}
                await uow.session.execute(groups.SET_TIMEOUT, cap)
                if isinstance(scope, OwnerScope):
                    caller = {"caller": str(scope.user_id)}
                    if not (await uow.session.execute(groups.OWNER_GATE, caller)).scalar_one():
                        raise port.DefinitionScopeDeniedError
                yield uow

    @staticmethod
    async def _record(
        uow: SqlAlchemyUnitOfWork, scope: AccountScope, definition_id: UUID
    ) -> tuple[port.DefinitionRecord, ...]:
        """The definition with its members, or nothing; a grant that reads none of its members
        reads nothing: all or none, should the scope change between the two statements."""
        row = (await uow.session.execute(definition_statement(scope, definition_id))).first()
        if row is None:
            return ()
        found = await uow.session.execute(members_statement(scope, definition_id))
        members = tuple(port.MemberRow(*m) for m in found)
        if isinstance(scope, GrantScope) and not members:
            return ()
        return (port.DefinitionRecord(port.DefinitionRow(*row), members),)

    async def _read_back(
        self, uow: SqlAlchemyUnitOfWork, scope: OwnerScope, definition_id: UUID
    ) -> port.DefinitionRecord:
        """A write's record; none, under the owner predicate, means its role lapsed: denied."""
        if not (found := await self._record(uow, scope, definition_id)):
            raise port.DefinitionScopeDeniedError
        return found[0]

    async def _commit(
        self,
        uow: SqlAlchemyUnitOfWork,
        scope: OwnerScope,
        new: port.NewDefinition,
        before: port.DefinitionRecord | None,
        write_ahead: port.DefinitionWriteAhead,
    ) -> port.DefinitionRecord:
        """Lock the members' accounts, each live; upsert, read back, write ahead (C-2.9), commit."""
        if accounts := {m.exchange_account_id for m in new.members}:
            live = await uow.session.execute(groups.lock_accounts_statement(accounts))
            if set(live.scalars()) != accounts:  # one is missing or soft-deleted
                raise port.DefinitionRuleError(ACCOUNT_NOT_LIVE)
            await uow.session.execute(members_upsert_statement(new, scope.user_id))
        after = await self._read_back(uow, scope, new.id)
        await bounded_write_ahead(write_ahead(before, after), WRITE_AHEAD_TIMEOUT_S)
        await uow.commit()
        return after

    async def create(
        self, scope: OwnerScope, new: port.NewDefinition, *, write_ahead: port.DefinitionWriteAhead
    ) -> port.DefinitionRecord:
        async with self._unit_of_work(scope, write=True) as uow:
            values = {"id": new.id, "name": new.name, "env": new.env}
            row = values | {"created_by": scope.user_id, "updated_by": scope.user_id}
            await uow.session.execute(sa.insert(trade_group_definitions).values(row))
            return await self._commit(uow, scope, new, None, write_ahead)

    async def replace(
        self,
        scope: OwnerScope,
        definition_id: UUID,
        new: port.NewDefinition,
        *,
        expected_updated_at: datetime | None,
        write_ahead: port.DefinitionWriteAhead,
    ) -> port.DefinitionRecord | None:
        if new.id != definition_id:
            raise ValueError("new.id must be the definition replaced")
        async with self._unit_of_work(scope, write=True) as uow:
            held = (await uow.session.execute(lock_statement(definition_id))).first()
            if held is None:
                return None
            if expected_updated_at is not None and held.updated_at != expected_updated_at:
                raise port.DefinitionStaleError
            before = await self._read_back(uow, scope, definition_id)
            row = sa.update(trade_group_definitions).where(_D.id == definition_id)
            await uow.session.execute(
                row.values(name=new.name, env=new.env, updated_by=scope.user_id)
            )
            kept = [m.exchange_account_id for m in new.members]
            dropped = sa.delete(trade_group_definition_members).where(
                _M.definition_id == definition_id, _M.exchange_account_id.not_in(kept)
            )
            await uow.session.execute(dropped)
            return await self._commit(uow, scope, new, before, write_ahead)

    async def soft_delete(
        self, scope: OwnerScope, definition_id: UUID, *, write_ahead: port.DefinitionWriteAhead
    ) -> port.DefinitionRecord | None:
        async with self._unit_of_work(scope, write=True) as uow:
            if (await uow.session.execute(lock_statement(definition_id))).first() is None:
                return None
            before = await self._read_back(uow, scope, definition_id)
            row = sa.update(trade_group_definitions).where(_D.id == definition_id)
            await uow.session.execute(
                row.values(deleted_at=sa.func.now(), updated_by=scope.user_id)
            )
            await bounded_write_ahead(write_ahead(before, None), WRITE_AHEAD_TIMEOUT_S)
            await uow.commit()
        return before

    async def get(self, scope: AccountScope, definition_id: UUID) -> port.DefinitionRecord | None:
        if isinstance(scope, GrantScope) and not scope.account_ids:
            return None  # an empty grant sees nothing and runs no SQL
        async with self._unit_of_work(scope) as uow:
            found = await self._record(uow, scope, definition_id)
        return found[0] if found else None
