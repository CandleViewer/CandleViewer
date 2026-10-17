"""SQL identity read path for `/auth/session`, `/auth/mfa/verify` (QA #1658) and `/me` (#2713).

Implements the `IdentityProvider` shape `api/sessions.py` expects: the
OpenAPI `User` object plus `SessionInfo.permissions`/`account_scope`, read
from the E09-T01 tables (`users`, `user_roles`, `roles`, `role_permissions`,
`permissions`, `user_account_access`), and the `Me.accounts` the caller may
read or trade, joined to `exchange_accounts`. Static, parameterised SQL only.
Never selects `password_hash` or any SECRET-classified column.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_USER_SQL = sa.text("""
    SELECT u.id::text AS id, u.username::text AS username, u.email::text AS email,
           u.display_name, u.status::text AS status, u.mfa_required,
           u.last_login_at, u.created_at, u.updated_at,
           COALESCE((SELECT array_agg(DISTINCT r.name::text ORDER BY r.name::text)
                     FROM user_roles ur JOIN roles r ON r.id = ur.role_id
                     WHERE ur.user_id = u.id
                       AND (ur.expires_at IS NULL OR ur.expires_at > now())),
                    ARRAY[]::text[]) AS roles,
           EXISTS (SELECT 1 FROM mfa_methods m WHERE m.user_id = u.id
                   AND m.confirmed_at IS NOT NULL AND m.revoked_at IS NULL) AS mfa_enabled
    FROM users u
    WHERE u.id = CAST(:id AS uuid) AND u.deleted_at IS NULL
    """)
# O5 (E42-T04, #965, C-2.21): a user who is not `active`, or is deleted, has no permission (the
# same predicate as `scope_sqlalchemy._PERMS`), so a disable takes effect at the next read.
_PERMS_SQL = sa.text("""
    SELECT DISTINCT p.code FROM users u
    JOIN user_roles ur ON ur.user_id = u.id AND (ur.expires_at IS NULL OR ur.expires_at > now())
    JOIN role_permissions rp ON rp.role_id = ur.role_id
    JOIN permissions p ON p.id = rp.permission_id
    WHERE u.id = CAST(:id AS uuid) AND u.status = 'active' AND u.deleted_at IS NULL
    ORDER BY p.code
    """)
_SCOPE_SQL = sa.text(
    "SELECT exchange_account_id::text FROM user_account_access "
    "WHERE user_id = CAST(:id AS uuid) AND can_view ORDER BY 1"
)
# `Me.accounts`, scoped at construction (SR-051) as `auth.scopes.account_scope` does: an owner
# (a live `owner` role of an active, undeleted user, the account store's `_OWNER_PRED`) reaches
# every live account with `trade`; anyone else only the live accounts of their own unfrozen view
# grants, `trade` only where `can_trade`. No key column.
_ACCOUNTS_SQL = sa.text("""
    SELECT ea.id::text AS exchange_account_id, ea.label, ea.env::text AS environment,
           CASE WHEN o.is_owner OR COALESCE(uaa.can_trade, false) THEN 'trade' ELSE 'read' END
               AS mode
    FROM (SELECT EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id
                         JOIN users u ON u.id = ur.user_id
                         WHERE ur.user_id = CAST(:id AS uuid) AND r.name::text = 'owner'
                           AND u.deleted_at IS NULL AND u.status = 'active'
                           AND (ur.expires_at IS NULL OR ur.expires_at > now())) AS is_owner) o
    CROSS JOIN exchange_accounts ea
    LEFT JOIN user_account_access uaa
           ON uaa.exchange_account_id = ea.id AND uaa.user_id = CAST(:id AS uuid)
    WHERE ea.deleted_at IS NULL AND (o.is_owner OR (uaa.can_view AND NOT uaa.frozen))
    ORDER BY ea.created_at, ea.id
    """)


def _iso(value: Any) -> str | None:
    return None if value is None else str(value.isoformat())


class SqlAlchemyIdentityProvider:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def user(self, user_id: str) -> dict[str, Any]:
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(_USER_SQL, {"id": user_id})).first()
        if row is None:
            raise LookupError("unknown user")
        m = row._mapping
        return {
            "id": m["id"],
            "username": m["username"],
            "email": m["email"],
            "display_name": m["display_name"],
            "roles": list(m["roles"] or ()),
            "status": m["status"],
            "mfa_enabled": bool(m["mfa_enabled"]),
            "mfa_required": bool(m["mfa_required"]),
            "last_login_at": _iso(m["last_login_at"]),
            "created_at": _iso(m["created_at"]),
            "updated_at": _iso(m["updated_at"]),
        }

    async def session_info(self, user_id: str) -> dict[str, Any]:
        async with self._relational.unit_of_work() as uow:
            perms = (await uow.session.execute(_PERMS_SQL, {"id": user_id})).all()
            scope = (await uow.session.execute(_SCOPE_SQL, {"id": user_id})).all()
        return {
            "permissions": [str(r[0]) for r in perms],
            "account_scope": [str(r[0]) for r in scope],
        }

    async def accounts(self, user_id: str) -> list[dict[str, Any]]:
        """The accounts `user_id` may read or trade, oldest first (`Me.accounts`).

        An owner is a live `owner` role of an active, undeleted user, as in the account store's
        `_OWNER_PRED` (SR-051), so a disabled or deleted owner reaches nothing through the role."""
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(_ACCOUNTS_SQL, {"id": user_id})).all()
        return [
            {
                "exchange_account_id": m["exchange_account_id"],
                "label": m["label"],
                "environment": m["environment"],
                "mode": m["mode"],
            }
            for m in (row._mapping for row in rows)
        ]
