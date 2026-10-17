"""`SqlAlchemyUserRepository` — Postgres implementation of
`candleviewer.auth.repository.UserRepository` (E09-S01, QA #1658).

Lives in M10 so `candleviewer.auth` never imports a storage driver (ADR-0003).
Every statement is static, parameterised SQL; no password material is ever
returned beyond the stored Argon2id digest `LoginService` must verify.
Lockout increment-and-lock is one atomic `UPDATE ... RETURNING`.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_FIND_SQL = sa.text("""
    SELECT u.id::text AS id, u.username::text AS username, u.email::text AS email,
           u.password_hash, u.password_algo_params, u.status::text AS status,
           u.mfa_required, u.failed_login_count, u.locked_until,
           COALESCE((SELECT array_agg(DISTINCT m.kind::text) FROM mfa_methods m
                     WHERE m.user_id = u.id AND m.confirmed_at IS NOT NULL
                       AND m.revoked_at IS NULL), ARRAY[]::text[]) AS mfa_methods
    FROM users u
    WHERE u.deleted_at IS NULL AND (u.username = :ident OR u.email = :ident)
    LIMIT 1
    """)
_FIND_BY_ID_SQL = sa.text("""
    SELECT u.id::text AS id, u.username::text AS username, u.email::text AS email,
           u.password_hash, u.password_algo_params, u.status::text AS status,
           u.mfa_required, u.failed_login_count, u.locked_until,
           COALESCE((SELECT array_agg(DISTINCT m.kind::text) FROM mfa_methods m
                     WHERE m.user_id = u.id AND m.confirmed_at IS NOT NULL
                       AND m.revoked_at IS NULL), ARRAY[]::text[]) AS mfa_methods
    FROM users u
    WHERE u.deleted_at IS NULL AND u.id = CAST(:ident AS uuid)
    LIMIT 1
    """)
_SUCCESS_SQL = sa.text(
    "UPDATE users SET failed_login_count = 0, locked_until = NULL, last_login_at = :now "
    "WHERE id = CAST(:id AS uuid)"
)
_FAILURE_SQL = sa.text("""
    UPDATE users SET
      failed_login_count = failed_login_count + 1,
      locked_until = CASE WHEN failed_login_count + 1 >= :threshold
                          THEN CAST(:lock_until AS timestamptz) ELSE locked_until END
    WHERE id = CAST(:id AS uuid)
    RETURNING CASE WHEN failed_login_count >= :threshold THEN locked_until END AS locked_until
    """)
_REHASH_SQL = sa.text(
    "UPDATE users SET password_hash = :h, password_algo_params = CAST(:p AS jsonb), "
    "password_changed_at = now() WHERE id = CAST(:id AS uuid)"
)
_REQUIRE_MFA_SQL = sa.text("UPDATE users SET mfa_required = true WHERE id = CAST(:id AS uuid)")


class SqlAlchemyUserRepository:
    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        record_factory: Callable[..., Any],
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._relational = relational
        self._make = record_factory
        self._clock = clock

    async def find_by_identifier(self, identifier: str) -> Any:
        return await self._find(_FIND_SQL, identifier)

    async def find_by_id(self, user_id: str) -> Any:
        return await self._find(_FIND_BY_ID_SQL, user_id)

    async def _find(self, stmt: sa.TextClause, ident: str) -> Any:
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(stmt, {"ident": ident})).first()
            await uow.commit()
        if row is None:
            return None
        m = row._mapping
        params = m["password_algo_params"]
        if isinstance(params, str):
            params = json.loads(params)
        return self._make(
            id=m["id"],
            username=m["username"],
            email=m["email"],
            password_hash=m["password_hash"],
            password_algo_params=dict(params),
            status=m["status"],
            mfa_required=m["mfa_required"],
            failed_login_count=m["failed_login_count"],
            locked_until=m["locked_until"],
            mfa_methods=tuple(m["mfa_methods"] or ()),
        )

    async def record_login_success(self, user_id: str) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_SUCCESS_SQL, {"id": user_id, "now": self._clock()})
            await uow.commit()

    async def record_login_failure(
        self, user_id: str, *, lockout_threshold: int, lock_duration: timedelta, now: datetime
    ) -> datetime | None:
        async with self._relational.unit_of_work() as uow:
            row = (
                await uow.session.execute(
                    _FAILURE_SQL,
                    {
                        "id": user_id,
                        "threshold": lockout_threshold,
                        "lock_until": now + lock_duration,
                    },
                )
            ).first()
            await uow.commit()
        return None if row is None else row._mapping["locked_until"]

    async def rehash_password(
        self, user_id: str, *, password_hash: str, algo_params: dict[str, int]
    ) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(
                _REHASH_SQL,
                {"id": user_id, "h": password_hash, "p": json.dumps(algo_params)},
            )
            await uow.commit()

    async def set_mfa_required(self, user_id: str) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_REQUIRE_MFA_SQL, {"id": user_id})
            await uow.commit()
