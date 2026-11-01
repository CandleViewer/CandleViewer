"""SQL grant/permission reads for rule scope (E35-S04). Static, parameterised SQL only.

Returns plain tuples (account_id, can_view, frozen): storage may not import `rules` (M10).
`load_trade_grants` (E29-T04, #913) adds `can_trade`, for the order route's principal;
`load_account_environments` (E35-T10, BQ-3) each live account's `exchange_accounts.env`.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

_GRANTS = sa.text(
    "SELECT exchange_account_id, can_view, frozen FROM user_account_access "
    "WHERE user_id = CAST(:id AS uuid)"
)
# E29-T04 (#913): the same rows with their trade right (21 Sec.3.1.3), so `decide(...,
# requires_trade=True)` admits a grant with `can_trade` and refuses a view-only or frozen one.
_TRADE_GRANTS = sa.text(
    "SELECT exchange_account_id, can_view, can_trade, frozen FROM user_account_access "
    "WHERE user_id = CAST(:id AS uuid)"
)
# O5 (E42-T04, #965, C-2.21): a user who is not `active`, or is deleted, has no permission, so a
# disabled user's armed rules lose `rules:arm_live` on the next read, before the asynchronous
# disarm has run. The same predicate guards `identity_sqlalchemy._PERMS_SQL`.
# E35-T10 (BQ-3): each account's own environment, for the rule action's re-check (24 Sec.11.5
# check 4); a deleted account is not read, so the re-check refuses it.
_ENVIRONMENTS = sa.text(
    "SELECT id, env::text FROM exchange_accounts WHERE id = ANY(CAST(:ids AS uuid[])) "
    "AND deleted_at IS NULL"
)
_PERMS = sa.text(
    "SELECT DISTINCT p.code FROM users u "
    "JOIN user_roles ur ON ur.user_id = u.id "
    "JOIN role_permissions rp ON rp.role_id = ur.role_id "
    "JOIN permissions p ON p.id = rp.permission_id "
    "WHERE u.id = CAST(:id AS uuid) AND u.status = 'active' AND u.deleted_at IS NULL "
    "AND (ur.expires_at IS NULL OR ur.expires_at > now())"
)


class SqlAlchemyScopeSource:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def load_grants(self, owner: UUID) -> list[tuple[UUID, bool, bool]]:
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_GRANTS, {"id": str(owner)})).all()
        return [(UUID(str(r[0])), bool(r[1]), bool(r[2])) for r in rows]

    async def load_trade_grants(self, user_id: UUID) -> list[tuple[UUID, bool, bool, bool]]:
        """`(account_id, can_view, can_trade, frozen)` for each grant row of `user_id`, a
        soft-revoked one (`can_view` false) included, which `decide` refuses."""
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_TRADE_GRANTS, {"id": str(user_id)})).all()
        return [(UUID(str(r[0])), bool(r[1]), bool(r[2]), bool(r[3])) for r in rows]

    async def load_account_environments(self, account_ids: Sequence[UUID]) -> dict[UUID, str]:
        """`{account_id: env}` for each live account of `account_ids`; one deleted or missing is
        left out, so its environment reads as not read."""
        ids = sorted(str(a) for a in account_ids)
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_ENVIRONMENTS, {"ids": ids})).all()
        return {UUID(str(r[0])): str(r[1]) for r in rows}

    async def load_permissions(self, owner: UUID) -> frozenset[str]:
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_PERMS, {"id": str(owner)})).all()
        return frozenset(str(r[0]) for r in rows)
