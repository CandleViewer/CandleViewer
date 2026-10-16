"""`SqlAlchemyMfaRepository` — Postgres implementation of
`candleviewer.auth.mfa_repository.MfaRepository` (E09-S02, QA #1658).

`mfa_challenges` has no `mfa_token_hash` column (migration 0001); the hash is
persisted, UTF-8 encoded, in the existing `nonce bytea` column (a digest of
the bearer token, never the token itself). `kind` is fixed to `totp` (the
column is NOT NULL and `LoginService` does not choose a method at issuance).
Replay guards are single conditional `UPDATE`s (atomic compare-and-set).
Every statement is static and parameterised.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_METHOD_COLS = (
    "id::text AS id, user_id::text AS user_id, kind::text AS kind, label, secret_enc, "
    "secret_key_ref, last_accepted_time_step, confirmed_at, last_used_at, created_at, "
    "revoked_at"
)
_CHALLENGE_COLS = (
    "id::text AS id, user_id::text AS user_id, convert_from(nonce, 'UTF8') AS mfa_token_hash, "
    "purpose, attempts, satisfied_at, expires_at, created_at"
)
#: #2295: a method `m` that may still be confirmed: never confirmed (every confirmation
#: records the accepted step), not revoked, and its user's latest method.
_CONFIRMABLE = (
    "m.user_id = CAST(:u AS uuid) AND m.confirmed_at IS NULL AND m.revoked_at IS NULL "
    "AND m.last_accepted_time_step IS NULL AND NOT EXISTS (SELECT 1 FROM mfa_methods n "
    "WHERE n.user_id = m.user_id AND n.created_at > m.created_at)"
)


def _sql(template: str) -> sa.TextClause:
    # Only the static fragments above are substituted, never caller data.
    return sa.text(
        template.replace("@M@", _METHOD_COLS)
        .replace("@C@", _CHALLENGE_COLS)
        .replace("@P@", _CONFIRMABLE)
    )


_CREATE_METHOD = _sql(
    "INSERT INTO mfa_methods (id, user_id, kind, label, secret_enc, secret_key_ref) "
    "VALUES (CAST(:id AS uuid), CAST(:u AS uuid), 'totp', :label, :enc, :ref) RETURNING @M@"
)
_FIND_PENDING = _sql("SELECT @M@ FROM mfa_methods m WHERE m.id = CAST(:id AS uuid) AND @P@")
_CLAIM = _sql(
    "UPDATE mfa_methods m SET confirmed_at = :now, last_accepted_time_step = :step "
    "WHERE m.id = CAST(:id AS uuid) AND @P@ RETURNING @M@"
)
_REVOKE_OTHER_TOTP = sa.text(
    "UPDATE mfa_methods SET revoked_at = :now WHERE user_id = CAST(:u AS uuid) "
    "AND id <> CAST(:id AS uuid) AND kind = 'totp' AND revoked_at IS NULL"
)
_SUPERSEDE = sa.text(
    "UPDATE mfa_methods SET revoked_at = :now WHERE user_id = CAST(:u AS uuid) "
    "AND confirmed_at IS NULL AND revoked_at IS NULL"
)
_ACTIVE_TOTP = _sql(
    "SELECT @M@ FROM mfa_methods WHERE user_id = CAST(:u AS uuid) AND kind = 'totp' "
    "AND confirmed_at IS NOT NULL AND revoked_at IS NULL ORDER BY created_at DESC"
)
_ACTIVE_ALL = _sql(
    "SELECT @M@ FROM mfa_methods WHERE user_id = CAST(:u AS uuid) "
    "AND confirmed_at IS NOT NULL AND revoked_at IS NULL ORDER BY created_at DESC"
)
_TIME_STEP = sa.text(
    "UPDATE mfa_methods SET last_accepted_time_step = :step WHERE id = CAST(:id AS uuid) "
    "AND (last_accepted_time_step IS NULL OR last_accepted_time_step < :step) RETURNING 1"
)
_REVOKE = sa.text("UPDATE mfa_methods SET revoked_at = :now WHERE id = CAST(:id AS uuid)")
_TOUCH = sa.text("UPDATE mfa_methods SET last_used_at = :now WHERE id = CAST(:id AS uuid)")
_CH_CREATE = _sql(
    "INSERT INTO mfa_challenges (id, user_id, kind, nonce, purpose, expires_at) "
    "VALUES (CAST(:id AS uuid), CAST(:u AS uuid), 'totp', convert_to(:h, 'UTF8'), :purpose, "
    ":exp) RETURNING @C@"
)
_CH_FIND = _sql(
    "SELECT @C@ FROM mfa_challenges WHERE nonce = convert_to(:h, 'UTF8') AND satisfied_at IS NULL"
)
_CH_ATTEMPT = sa.text(
    "UPDATE mfa_challenges SET attempts = LEAST(attempts + 1, 10) "
    "WHERE id = CAST(:id AS uuid) RETURNING attempts"
)
_CH_SATISFY = sa.text(
    "UPDATE mfa_challenges SET satisfied_at = :now WHERE id = CAST(:id AS uuid) "
    "AND satisfied_at IS NULL RETURNING 1"
)
_RC_DELETE = sa.text("DELETE FROM recovery_codes WHERE user_id = CAST(:u AS uuid)")
_RC_INSERT = sa.text(
    "INSERT INTO recovery_codes (id, user_id, code_hash) "
    "VALUES (CAST(:id AS uuid), CAST(:u AS uuid), :h)"
)
_RC_FIND = sa.text(
    "SELECT id::text AS id FROM recovery_codes WHERE user_id = CAST(:u AS uuid) "
    "AND code_hash = :h AND used_at IS NULL"
)
#: #2344: the recovery sign-in's unit of work. Each conditional update wins at most once and
#: only for the code's and the challenge's own user.
_RC_USE = sa.text(
    "UPDATE recovery_codes SET used_at = :now WHERE id = CAST(:id AS uuid) "
    "AND user_id = CAST(:u AS uuid) AND used_at IS NULL RETURNING 1"
)
_CH_SATISFY_OWN = sa.text(
    "UPDATE mfa_challenges SET satisfied_at = :now WHERE id = CAST(:id AS uuid) "
    "AND user_id = CAST(:u AS uuid) AND satisfied_at IS NULL RETURNING 1"
)
_REVOKE_ALL = sa.text(
    "UPDATE mfa_methods SET revoked_at = :now WHERE user_id = CAST(:u AS uuid) "
    "AND revoked_at IS NULL"
)
_RC_COUNT = sa.text(
    "SELECT count(*) AS n FROM recovery_codes WHERE user_id = CAST(:u AS uuid) AND used_at IS NULL"
)


class SqlAlchemyMfaRepository:
    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        method_factory: Callable[..., Any],
        challenge_factory: Callable[..., Any],
    ) -> None:
        self._relational = relational
        self._method = method_factory
        self._challenge = challenge_factory

    async def _run(self, stmt: sa.TextClause, params: dict[str, Any]) -> list[Any]:
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(stmt, params)).all()
            await uow.commit()
        return list(rows)

    async def _run_no_rows(self, stmt: sa.TextClause, params: dict[str, Any]) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(stmt, params)
            await uow.commit()

    async def _one(
        self, stmt: sa.TextClause, params: dict[str, Any], factory: Callable[..., Any]
    ) -> Any:
        rows = await self._run(stmt, params)
        return factory(**dict(rows[0]._mapping)) if rows else None

    async def create_pending_method(
        self, user_id: str, *, secret_enc: bytes, secret_key_ref: str, label: str
    ) -> Any:
        return await self._one(
            _CREATE_METHOD,
            {
                "id": str(uuid.uuid4()),
                "u": user_id,
                "label": label,
                "enc": secret_enc,
                "ref": secret_key_ref,
            },
            self._method,
        )

    async def find_pending_method(self, method_id: str, user_id: str) -> Any:
        return await self._one(_FIND_PENDING, {"id": method_id, "u": user_id}, self._method)

    async def supersede_pending_methods(self, user_id: str, *, now: datetime) -> None:
        await self._run_no_rows(_SUPERSEDE, {"u": user_id, "now": now})

    async def complete_enrollment(
        self,
        user_id: str,
        *,
        method_id: str,
        time_step: int,
        now: datetime,
        code_hashes: tuple[str, ...],
    ) -> Any:
        """One unit of work (#2295): claim, revoke the other TOTP methods, replace the codes."""
        async with self._relational.unit_of_work() as uow:
            run = uow.session.execute
            claim = {"id": method_id, "u": user_id, "now": now, "step": time_step}
            claimed = (await run(_CLAIM, claim)).first()
            if claimed is None:
                await uow.rollback()
                return None
            await run(_REVOKE_OTHER_TOTP, {"id": method_id, "u": user_id, "now": now})
            await run(_RC_DELETE, {"u": user_id})
            for h in code_hashes:
                await run(_RC_INSERT, {"id": str(uuid.uuid4()), "u": user_id, "h": h})
            await uow.commit()
        return self._method(**dict(claimed._mapping))

    async def find_active_totp_methods(self, user_id: str) -> tuple[Any, ...]:
        rows = await self._run(_ACTIVE_TOTP, {"u": user_id})
        return tuple(self._method(**dict(r._mapping)) for r in rows)

    async def find_active_methods(self, user_id: str) -> tuple[Any, ...]:
        rows = await self._run(_ACTIVE_ALL, {"u": user_id})
        return tuple(self._method(**dict(r._mapping)) for r in rows)

    async def record_time_step(self, method_id: str, *, time_step: int) -> bool:
        return bool(await self._run(_TIME_STEP, {"id": method_id, "step": time_step}))

    async def revoke_method(self, method_id: str, *, now: datetime) -> None:
        await self._run_no_rows(_REVOKE, {"id": method_id, "now": now})

    async def touch_method_used(self, method_id: str, *, now: datetime) -> None:
        await self._run_no_rows(_TOUCH, {"id": method_id, "now": now})

    async def create_challenge(
        self, user_id: str, *, purpose: str, mfa_token_hash: str, expires_at: datetime
    ) -> Any:
        return await self._one(
            _CH_CREATE,
            {
                "id": str(uuid.uuid4()),
                "u": user_id,
                "h": mfa_token_hash,
                "purpose": purpose,
                "exp": expires_at,
            },
            self._challenge,
        )

    async def find_open_challenge_by_token_hash(self, mfa_token_hash: str) -> Any:
        return await self._one(_CH_FIND, {"h": mfa_token_hash}, self._challenge)

    async def record_challenge_attempt(self, challenge_id: str) -> int:
        rows = await self._run(_CH_ATTEMPT, {"id": challenge_id})
        return int(rows[0]._mapping["attempts"]) if rows else 0

    async def satisfy_challenge(self, challenge_id: str, *, now: datetime) -> bool:
        return bool(await self._run(_CH_SATISFY, {"id": challenge_id, "now": now}))

    async def replace_recovery_codes(self, user_id: str, *, code_hashes: tuple[str, ...]) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_RC_DELETE, {"u": user_id})
            for h in code_hashes:
                await uow.session.execute(
                    _RC_INSERT, {"id": str(uuid.uuid4()), "u": user_id, "h": h}
                )
            await uow.commit()

    async def find_unused_recovery_code(self, user_id: str, *, code_hash: str) -> str | None:
        rows = await self._run(_RC_FIND, {"u": user_id, "h": code_hash})
        return str(rows[0]._mapping["id"]) if rows else None

    async def count_unused_recovery_codes(self, user_id: str) -> int:
        rows = await self._run(_RC_COUNT, {"u": user_id})
        return int(rows[0]._mapping["n"])

    async def complete_recovery(
        self, user_id: str, *, challenge_id: str, code_id: str, now: datetime
    ) -> bool:
        """One unit of work (#2344): spend the code, satisfy the challenge, revoke every method;
        a lost race on either rolls back."""
        async with self._relational.unit_of_work() as uow:
            run = uow.session.execute
            won = (await run(_RC_USE, {"id": code_id, "u": user_id, "now": now})).first()
            if won is not None:
                satisfy = {"id": challenge_id, "u": user_id, "now": now}
                won = (await run(_CH_SATISFY_OWN, satisfy)).first()
            if won is None:
                await uow.rollback()
                return False
            await run(_REVOKE_ALL, {"u": user_id, "now": now})
            await uow.commit()
        return True
