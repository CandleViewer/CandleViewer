"""SQL grant/permission reads for rule scope (E35-S04). Static, parameterised SQL only.

Returns plain tuples (account_id, can_view, frozen): storage may not import `rules` (M10).
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository

_GRANTS = sa.text(
    "SELECT exchange_account_id, can_view, frozen FROM user_account_access "
    "WHERE user_id = CAST(:id AS uuid)"
)
# O5 (E42-T04, #965, C-2.21): a user who is not `active`, or is deleted, has no permission, so a
# disabled user's armed rules lose `rules:arm_live` on the next read, before the asynchronous
# disarm has run. The same predicate guards `identity_sqlalchemy._PERMS_SQL`.
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

    async def load_permissions(self, owner: UUID) -> frozenset[str]:
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_PERMS, {"id": str(owner)})).all()
        return frozenset(str(r[0]) for r in rows)
