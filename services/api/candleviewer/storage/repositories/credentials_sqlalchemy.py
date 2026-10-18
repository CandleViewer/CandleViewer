"""Postgres adapter for M2's credential and KCV ports (E27-T02).

Lives in M10 so M2 never imports a driver; structurally satisfies
`secrets.store.CredentialStore` / `secrets.store.KcvStore` without importing M2 (C-3.2).
Moves only ciphertext, nonces and wrapped-DEK refs; never logs a row. Static SQL only.
A re-wrap's audit record is built by a function the composition root injects
(`admin.wiring.secrets_audit_row`): M10 depends on M1 only, so it never imports `audit` (§3).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

import sqlalchemy as sa

from candleviewer.storage.errors import RewrapAuditNotWired, RewrapAuditNotWritten
from candleviewer.storage.repositories.audit_sqlalchemy import insert_audit_row_locked
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

#: `(action, fields)` -> one `audit_log` record in the WAL's format.
AuditRowBuilder = Callable[[str, dict[str, str]], dict[str, Any]]

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
    "k.permission_snapshot, k.status::text AS status, (k.revoked_at IS NOT NULL) AS revoked, "
    "k.can_withdraw, k.can_transfer "
    "FROM api_keys k JOIN exchange_accounts ea ON ea.id = k.exchange_account_id "
    "WHERE k.id = :id AND ea.env::text = :env"
)
#: Record fields `insert` never writes: the database sets them (0017 defaults, the CHECKs).
_READ_ONLY = frozenset({"revoked", "status", "can_withdraw", "can_transfer"})
_REVOKE = sa.text(
    "UPDATE api_keys SET revoked_at = COALESCE(revoked_at, now()), status = 'revoked', "
    "updated_at = now() WHERE id = :id"
)
#: `_IDS` and `_COUNT` leave out a row either revocation signal fences, as `_REWRAP` does, so a
#: KEK rotation never lists a row it may not move and can still complete (#2266).
_IDS = sa.text(
    "SELECT k.id FROM api_keys k JOIN exchange_accounts ea ON ea.id = k.exchange_account_id "
    "WHERE k.kek_version = :v AND k.revoked_at IS NULL AND k.status <> 'revoked' "
    "AND ea.env::text = :env "
    "AND (CAST(:after AS uuid) IS NULL OR k.id > CAST(:after AS uuid)) ORDER BY k.id LIMIT :limit"
)
_COUNT = sa.text(
    "SELECT count(*) FROM api_keys k JOIN exchange_accounts ea ON ea.id = k.exchange_account_id "
    "WHERE k.kek_version = :v AND k.revoked_at IS NULL AND k.status <> 'revoked' "
    "AND ea.env::text = :env"
)
#: Rows at `:v` created before `(env, :v)` was enrolled, revoked or not: an earlier run's moves.
_REWRAPPED = sa.text(
    "SELECT count(*) FROM api_keys k JOIN exchange_accounts ea ON ea.id = k.exchange_account_id "
    "JOIN kek_versions kv ON kv.env = ea.env AND kv.version = k.kek_version "
    "WHERE k.kek_version = :v AND ea.env::text = :env AND k.created_at < kv.created_at"
)
#: Moves a row of the process's environment unless a revocation signal fences it (`revoked_at`
#: or status `revoked`); every other status is re-wrapped, or the rotation never completes.
_REWRAP = sa.text(
    "UPDATE api_keys SET dek_ref = :dek_ref, kek_version = :to_v, updated_at = now() "
    "WHERE id = :id AND kek_version = :from_v AND revoked_at IS NULL AND status <> 'revoked' "
    "AND EXISTS (SELECT 1 FROM exchange_accounts ea "
    "WHERE ea.id = api_keys.exchange_account_id AND ea.env::text = :env)"
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


def _decode(value: object) -> object:
    """`permission_snapshot` jsonb arrives as `str` (no asyncpg codec) or decoded, as in
    `accounts_sqlalchemy._decode`; a JSON object comes back as a dict. Any other shape (text that is
    no JSON, an array, a scalar, `null`) comes back as no mapping, never raising: the borrow's C-2.8
    re-check (SR-E27-14) refuses it as `snapshot_invalid`, while `destroy()` and the KEK re-wrap,
    which never read the snapshot, still reach the row (`ak_snapshot_shape` makes it an object, so
    only a row edited past that CHECK gets here, KV-T03)."""
    try:
        parsed: object = json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return value
    return dict(parsed) if isinstance(parsed, Mapping) else parsed


class SqlAlchemyCredentialStore:
    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        audit_row: AuditRowBuilder | None = None,
    ) -> None:
        self._rel = relational
        #: Builds the record `rewrap` writes with its compare-and-set; without one it refuses.
        self._audit_row = audit_row

    async def _exec(self, stmt: sa.TextClause, params: dict[str, Any]) -> Any:
        async with self._rel.unit_of_work() as uow:
            res: Any = await uow.session.execute(stmt, params)
            rows = res.mappings().all() if res.returns_rows else res.rowcount
            await uow.commit()
            return rows

    async def insert(self, record: dict[str, Any]) -> None:
        params = {k: v for k, v in record.items() if k not in _READ_ONLY}
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
        rec["permission_snapshot"] = _decode(rec["permission_snapshot"])
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

    async def count_rewrapped_since_enrolment(self, version: int, env: str) -> int:
        return int((await self._exec(_REWRAPPED, {"v": version, "env": env}))[0]["count"])

    async def rewrap(
        self,
        key_id: UUID,
        *,
        env: str,
        from_version: int,
        dek_ref: str,
        kek_version: int,
        audit: tuple[str, dict[str, str]],
    ) -> bool:
        """The UPDATE, then, only if it moved the row, the chain lock and the record's INSERT
        (row lock first, chain lock last), then COMMIT: one transaction, so an error or a
        cancellation before the commit rolls back both (C-2.9, #2266)."""
        if self._audit_row is None:
            raise RewrapAuditNotWired("re-wrap refused: no audit row builder is wired")
        params = {
            "id": key_id, "env": env, "from_v": from_version, "to_v": kek_version,
            "dek_ref": dek_ref,
        }  # fmt: skip
        async with self._rel.unit_of_work() as uow:
            moved: Any = await uow.session.execute(_REWRAP, params)
            if int(moved.rowcount) != 1:
                return False
            if not await insert_audit_row_locked(uow.session, self._audit_row(*audit)):
                raise RewrapAuditNotWritten("re-wrap audit record not written")
            await uow.commit()
            return True

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
