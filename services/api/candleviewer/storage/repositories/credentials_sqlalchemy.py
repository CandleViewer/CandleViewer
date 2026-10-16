"""Postgres adapter for M2's credential and KCV ports (E27-T02).

Lives in M10 so M2 never imports a driver; structurally satisfies
`secrets.store.CredentialStore` / `secrets.store.KcvStore` without importing M2 (C-3.2).
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

_INSERT = sa.text(
    "INSERT INTO api_keys (id, exchange_account_id, label, key_id_enc, key_id_last4, "
    "secret_enc, enc_nonce, enc_alg, dek_ref, kek_version, permission_snapshot, read_only) "
    "SELECT :id, ea.id, :label, :key_id_enc, :key_id_last4, :secret_enc, :enc_nonce, :enc_alg, "
    ":dek_ref, :kek_version, CAST(:permission_snapshot AS jsonb), :read_only "
    "FROM exchange_accounts ea WHERE ea.id = :exchange_account_id AND ea.env::text = :env"
)
_GET = sa.text(
    "SELECT k.id, k.exchange_account_id, ea.env::text AS env, k.label, k.key_id_enc, "
    "k.key_id_last4, k.secret_enc, k.enc_nonce, k.dek_ref, k.kek_version, k.enc_alg, "
    "k.permission_snapshot, k.status::text AS status, (k.revoked_at IS NOT NULL) AS revoked "
    "FROM api_keys k JOIN exchange_accounts ea ON ea.id = k.exchange_account_id "
    "WHERE k.id = :id AND ea.env::text = :env"
)
_REVOKE = sa.text(
    "UPDATE api_keys SET revoked_at = COALESCE(revoked_at, now()), status = 'revoked', "
    "updated_at = now() WHERE id = :id"
)
_IDS = sa.text(
    "SELECT k.id FROM api_keys k JOIN exchange_accounts ea ON ea.id = k.exchange_account_id "
    "WHERE k.kek_version = :v AND k.revoked_at IS NULL AND ea.env::text = :env "
    "AND (CAST(:after AS uuid) IS NULL OR k.id > CAST(:after AS uuid)) ORDER BY k.id LIMIT :limit"
)
_COUNT = sa.text(
    "SELECT count(*) FROM api_keys k JOIN exchange_accounts ea ON ea.id = k.exchange_account_id "
    "WHERE k.kek_version = :v AND k.revoked_at IS NULL AND ea.env::text = :env"
)
_REWRAP = sa.text(
    "UPDATE api_keys SET dek_ref = :dek_ref, kek_version = :to_v, updated_at = now() "
    "WHERE id = :id AND kek_version = :from_v AND revoked_at IS NULL"
)
_TOUCH = sa.text("UPDATE api_keys SET last_used_at = now() WHERE id = :id")
# `kek_versions` is keyed (env, version) since 0026 (#2338); `kv_kcv_unique` stays global.
_KCV_GET = sa.text("SELECT kcv FROM kek_versions WHERE env::text = :env AND version = :v")
_KCV_ALL = sa.text(
    "SELECT env::text AS env, version, kcv, (retired_at IS NOT NULL) AS retired FROM kek_versions"
)
_KCV_PUT = sa.text(
    "INSERT INTO kek_versions (env, version, kcv) VALUES (CAST(:env AS exchange_env), :v, :kcv) "
    "ON CONFLICT (env, version) DO NOTHING"
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
        params = {k: v for k, v in record.items() if k not in ("revoked", "status")}
        params["permission_snapshot"] = json.dumps(record["permission_snapshot"])
        params["read_only"] = bool(record["permission_snapshot"].get("readOnly"))
        if int(await self._exec(_INSERT, params)) != 1:
            raise ValueError("exchange account missing or environment mismatch")

    async def get(self, key_id: UUID, env: str) -> dict[str, Any] | None:
        rows = await self._exec(_GET, {"id": key_id, "env": env})
        if not rows:
            return None
        rec = dict(rows[0])
        rec["key_id_enc"], rec["secret_enc"] = bytes(rec["key_id_enc"]), bytes(rec["secret_enc"])
        rec["enc_nonce"] = bytes(rec["enc_nonce"])
        return rec

    async def mark_revoked(self, key_id: UUID) -> None:
        await self._exec(_REVOKE, {"id": key_id})

    async def ids_at_kek_version(
        self, version: int, limit: int, env: str, after: UUID | None = None
    ) -> list[UUID]:
        params = {"v": version, "limit": limit, "after": after, "env": env}
        return [r["id"] for r in await self._exec(_IDS, params)]

    async def count_at_kek_version(self, version: int, env: str) -> int:
        return int((await self._exec(_COUNT, {"v": version, "env": env}))[0]["count"])

    async def rewrap(
        self, key_id: UUID, *, from_version: int, dek_ref: str, kek_version: int
    ) -> bool:
        params = {"id": key_id, "from_v": from_version, "to_v": kek_version, "dek_ref": dek_ref}
        return int(await self._exec(_REWRAP, params)) == 1

    async def touch_last_used(self, key_id: UUID) -> None:
        await self._exec(_TOUCH, {"id": key_id})

    async def kcv_for(self, env: str, version: int) -> bytes | None:
        rows = await self._exec(_KCV_GET, {"env": env, "v": version})
        return bytes(rows[0]["kcv"]) if rows else None

    async def kcv_versions(self) -> list[tuple[str, int, bytes, bool]]:
        rows = await self._exec(_KCV_ALL, {})
        return [
            (str(r["env"]), int(r["version"]), bytes(r["kcv"]), bool(r["retired"])) for r in rows
        ]

    async def record_kcv(self, env: str, version: int, kcv: bytes) -> bytes:
        """Insert-if-absent, then re-read: concurrent boots converge on one stored KCV. One KCV
        under two environments violates `kv_kcv_unique` and propagates (the boot degrades)."""
        await self._exec(_KCV_PUT, {"env": env, "v": version, "kcv": kcv})
        stored = await self.kcv_for(env, version)
        if stored is None:  # pragma: no cover - row was just inserted or already present
            raise RuntimeError("kek_versions row missing after insert")
        return stored
