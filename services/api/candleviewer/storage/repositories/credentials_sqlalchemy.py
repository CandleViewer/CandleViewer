"""Postgres adapter for M2's credential and KCV ports (E27-T02).

Lives in M10 so M2 never imports a driver; structurally satisfies
`secrets.store.CredentialStore` / `secrets.service.KcvStore` without importing M2 (C-3.2).
Moves only ciphertext, nonces and wrapped-DEK refs; never logs a row. Static SQL only.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

_COLS = (
    "id, exchange_account_id, label, key_id_enc, key_id_last4, secret_enc, enc_nonce, "
    "dek_ref, kek_version, enc_alg, permission_snapshot, (revoked_at IS NOT NULL) AS revoked"
)
_INSERT = sa.text(
    "INSERT INTO api_keys (id, exchange_account_id, label, key_id_enc, key_id_last4, "
    "secret_enc, enc_nonce, enc_alg, dek_ref, kek_version, permission_snapshot) VALUES "
    "(:id, :exchange_account_id, :label, :key_id_enc, :key_id_last4, :secret_enc, "
    ":enc_nonce, :enc_alg, :dek_ref, :kek_version, CAST(:permission_snapshot AS jsonb))"
)
_GET = sa.text(f"SELECT {_COLS} FROM api_keys WHERE id = :id")  # noqa: S608 -- constant
_REVOKE = sa.text(
    "UPDATE api_keys SET revoked_at = COALESCE(revoked_at, now()), status = 'revoked', "
    "updated_at = now() WHERE id = :id"
)
_IDS = sa.text(
    "SELECT id FROM api_keys WHERE kek_version = :v AND revoked_at IS NULL ORDER BY id LIMIT :limit"
)
_COUNT = sa.text("SELECT count(*) FROM api_keys WHERE kek_version = :v AND revoked_at IS NULL")
_REWRAP = sa.text(
    "UPDATE api_keys SET dek_ref = :dek_ref, kek_version = :to_v, updated_at = now() "
    "WHERE id = :id AND kek_version = :from_v"
)
_TOUCH = sa.text("UPDATE api_keys SET last_used_at = now() WHERE id = :id")
_KCV_GET = sa.text("SELECT kcv FROM kek_versions WHERE version = :v")
_KCV_PUT = sa.text(
    "INSERT INTO kek_versions (version, kcv) VALUES (:v, :kcv) ON CONFLICT (version) DO NOTHING"
)


class SqlAlchemyCredentialStore:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._rel = relational

    async def _exec(self, stmt: sa.TextClause, params: dict[str, Any]) -> Any:
        async with self._rel.unit_of_work() as uow:
            res: Any = await uow.session.execute(stmt, params)
            rows = res.mappings().all() if res.returns_rows else res.rowcount
            await uow.commit()
            return rows

    async def insert(self, record: dict[str, Any]) -> None:
        params = {k: v for k, v in record.items() if k != "revoked"}
        params["permission_snapshot"] = json.dumps(record["permission_snapshot"], default=str)
        await self._exec(_INSERT, params)

    async def get(self, key_id: UUID) -> dict[str, Any] | None:
        rows = await self._exec(_GET, {"id": key_id})
        if not rows:
            return None
        rec = dict(rows[0])
        rec["key_id_enc"], rec["secret_enc"] = bytes(rec["key_id_enc"]), bytes(rec["secret_enc"])
        rec["enc_nonce"] = bytes(rec["enc_nonce"])
        return rec

    async def mark_revoked(self, key_id: UUID) -> None:
        await self._exec(_REVOKE, {"id": key_id})

    async def ids_at_kek_version(self, version: int, limit: int) -> list[UUID]:
        return [r["id"] for r in await self._exec(_IDS, {"v": version, "limit": limit})]

    async def count_at_kek_version(self, version: int) -> int:
        return int((await self._exec(_COUNT, {"v": version}))[0]["count"])

    async def rewrap(
        self, key_id: UUID, *, from_version: int, dek_ref: str, kek_version: int
    ) -> bool:
        params = {"id": key_id, "from_v": from_version, "to_v": kek_version, "dek_ref": dek_ref}
        return int(await self._exec(_REWRAP, params)) == 1

    async def touch_last_used(self, key_id: UUID) -> None:
        await self._exec(_TOUCH, {"id": key_id})

    async def kcv_for(self, version: int) -> bytes | None:
        rows = await self._exec(_KCV_GET, {"v": version})
        return bytes(rows[0]["kcv"]) if rows else None

    async def record_kcv(self, version: int, kcv: bytes) -> None:
        await self._exec(_KCV_PUT, {"v": version, "kcv": kcv})
