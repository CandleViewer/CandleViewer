"""Postgres adapter for M2's auth keyring rows (#2152 S2, ADR-0009 Amendment 4).

Lives in M10 so M2 never imports a driver; it moves plain dicts, so the `AuthKeyStore` port S4 adds
to `secrets/store.py` is satisfied structurally (C-3.2). It moves only wrapped keys (`dek_ref`), ids
and versions, and never logs a row. Bound to the process environment, it refuses a call that names
another before any I/O (C-2.11). A database error leaves the two writes as `StorageQueryFailed`
with the SQLSTATE alone: the driver's text carries the failing row, wrap included (C-12.6, class
S). Static SQL with explicit columns (21 Sec.12 forbids `SELECT *`, enforced by the unit test);
it never deletes (`cv_app` has no DELETE on `auth_keys`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError

from candleviewer.domain.primitives import Environment
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_ROWS = sa.text(
    "SELECT id, env::text AS env, purpose, key_version, origin, dek_ref, kek_version "
    "FROM auth_keys WHERE env = CAST(:env AS exchange_env) ORDER BY purpose, key_version"
)
# Only a conflict on that key means another boot wrote it first: a reused `id` must raise.
_INSERT = sa.text(
    "INSERT INTO auth_keys (id, env, purpose, key_version, origin, dek_ref, kek_version) "
    "VALUES (:id, CAST(:env AS exchange_env), :purpose, :key_version, :origin, :dek_ref, "
    ":kek_version) ON CONFLICT ON CONSTRAINT ak_env_purpose_key_version DO NOTHING"
)
# Only the wrap and its version move (`trg_auth_keys_write_once` refuses the rest).
_REWRAP = sa.text(
    "UPDATE auth_keys SET dek_ref = :dek_ref, kek_version = :to_v "
    "WHERE id = :id AND env = CAST(:env AS exchange_env) AND kek_version = :from_v"
)
# A KEK re-wrap run of the environment waits for none of its rows to be left at the old version.
_COUNT = sa.text(
    "SELECT count(*) FROM auth_keys WHERE env = CAST(:env AS exchange_env) AND kek_version = :v"
)
# Counts only, every environment's (these tables have none). An unconfirmed TOTP method counts too.
_MFA_MATERIAL = sa.text(
    "SELECT (SELECT count(*) FROM mfa_methods WHERE kind = 'totp' AND revoked_at IS NULL) "
    "+ (SELECT count(*) FROM recovery_codes WHERE used_at IS NULL) AS material"
)


class AuthKeyEnvironmentError(ValueError):
    """A call named an environment other than the process's (C-2.11); refused before any I/O."""


class SqlAlchemyAuthKeyStore:
    def __init__(self, relational: SqlAlchemyRelationalRepository, *, env: Environment) -> None:
        self._rel, self._env = relational, env

    def _own(self, *envs: object) -> None:
        if any(env != self._env for env in envs):
            raise AuthKeyEnvironmentError("the auth key store serves only the process environment")

    async def rows_for(self, env: str) -> list[dict[str, Any]]:
        """Every row of `env`, which must be the process's, by purpose then key version."""
        self._own(env)
        async with self._rel.unit_of_work() as uow:
            res: Any = await uow.session.execute(_ROWS, {"env": env})
            return [dict(row) for row in res.mappings().all()]

    async def insert_keyring(self, records: Sequence[Mapping[str, Any]]) -> bool:
        """Insert every record in one transaction, or none: False (nothing written) when a
        `(env, purpose, key_version)` is taken already, so concurrent boots converge on the first
        one's rows. Rows go in key order, so they cannot lock crosswise. `ValueError` for no
        records, `AuthKeyEnvironmentError` for another environment's: both before any I/O."""
        if not records:
            raise ValueError("a keyring needs at least one record")
        self._own(*(r.get("env") for r in records))
        rows = sorted(
            ({"key_version": 1, **r} for r in records),
            key=lambda r: (r["env"], r["purpose"], r["key_version"]),
        )
        try:
            async with self._rel.unit_of_work() as uow:
                inserted = 0
                for row in rows:
                    res: Any = await uow.session.execute(_INSERT, row)
                    inserted += int(res.rowcount)
                if inserted != len(rows):
                    await uow.rollback()
                    return False
                await uow.commit()
                return True
        except DBAPIError as exc:
            state = getattr(exc.orig, "sqlstate", None)
        raise StorageQueryFailed(state if isinstance(state, str) else None)  # nothing chained

    async def count_at_kek_version(self, version: int, env: str) -> int:
        """The rows of `env`, which must be the process's, wrapped under KEK `version` (#2266)."""
        self._own(env)
        async with self._rel.unit_of_work() as uow:
            res: Any = await uow.session.execute(_COUNT, {"env": env, "v": version})
            return int(res.scalar_one())

    async def count_mfa_material(self) -> int:
        """Unrevoked TOTP methods plus unused recovery codes, in every environment: what a new
        keyring would strand. Counts only; no seed, digest or user leaves the call."""
        async with self._rel.unit_of_work() as uow:
            res: Any = await uow.session.execute(_MFA_MATERIAL)
            return int(res.scalar_one())

    async def rewrap(
        self, key_id: UUID, *, env: str, from_version: int, dek_ref: str, kek_version: int
    ) -> bool:
        """Compare-and-set on `kek_version`; True iff this call moved the row of `env`, which must
        be the process's."""
        self._own(env)
        params = {
            "id": key_id, "env": env, "from_v": from_version, "to_v": kek_version,
            "dek_ref": dek_ref,
        }  # fmt: skip
        try:
            async with self._rel.unit_of_work() as uow:
                res: Any = await uow.session.execute(_REWRAP, params)
                await uow.commit()
                return int(res.rowcount) == 1
        except DBAPIError as exc:
            state = getattr(exc.orig, "sqlstate", None)
        raise StorageQueryFailed(state if isinstance(state, str) else None)  # nothing chained
