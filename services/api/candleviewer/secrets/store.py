"""Persistence ports for `api_keys` envelope columns, `kek_versions` and `auth_keys`.

Records are plain dicts keyed by `CredentialRow` field names, so the Postgres adapter in
M10 (`storage`) satisfies these Protocols structurally without importing M2 (C-3.2).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from uuid import UUID

#: `(action, fields)` -> durable, hash-chained audit append (write-ahead; raises to refuse).
AuditSink = Callable[[str, dict[str, str]], Awaitable[None]]


class CredentialStore(Protocol):
    async def insert(self, record: dict[str, Any]) -> None: ...
    async def get(self, key_id: UUID, env: str) -> dict[str, Any] | None:
        """The row only if its account is in `env` (C-2.11: env-namespaced read)."""
        ...

    async def mark_revoked(self, key_id: UUID) -> None: ...
    async def ids_at_kek_version(
        self, version: int, limit: int, env: str, after: UUID | None = None
    ) -> list[UUID]:
        """Non-revoked ids at `version` in `env` (C-2.11), ordered by id, after `after`."""
        ...

    async def count_at_kek_version(self, version: int, env: str) -> int: ...
    async def rewrap(
        self, key_id: UUID, *, from_version: int, dek_ref: str, kek_version: int
    ) -> bool:
        """Compare-and-set on `kek_version`; True iff this call moved the row."""
        ...

    async def touch_last_used(self, key_id: UUID) -> None: ...


class KcvStore(Protocol):
    """`kek_versions`: one KEK lineage per environment, keyed `(env, version)` (#2338)."""

    async def kcv_for(self, env: str, version: int) -> bytes | None: ...
    async def kcv_versions(self) -> list[tuple[str, int, bytes, bool]]:
        """All `(env, version, kcv, retired)` rows, every environment (KCVs are not secret)."""
        ...

    async def record_kcv(self, env: str, version: int, kcv: bytes) -> bytes:
        """Insert-if-absent; return the KCV now stored for `(env, version)` (re-read after
        conflict). A KCV already stored under another key raises (`kv_kcv_unique`)."""
        ...


class InMemoryCredentialStore:
    """Test fake for both ports. Never used with real credentials."""

    def __init__(self) -> None:
        self.rows: dict[UUID, dict[str, Any]] = {}
        self.kcvs: dict[tuple[str, int], bytes] = {}
        self.retired: set[tuple[str, int]] = set()

    async def insert(self, record: dict[str, Any]) -> None:
        self.rows[record["id"]] = dict(record)

    def activate(self, key_id: UUID, status: str = "active") -> None:
        """Test helper: E27-T03 verification moves a key from `pending`."""
        self.rows[key_id]["status"] = status

    async def get(self, key_id: UUID, env: str) -> dict[str, Any] | None:
        row = self.rows.get(key_id)
        return dict(row) if row is not None and row["env"] == env else None

    async def mark_revoked(self, key_id: UUID) -> None:
        if key_id in self.rows:
            self.rows[key_id]["revoked"] = True

    async def ids_at_kek_version(
        self, version: int, limit: int, env: str, after: UUID | None = None
    ) -> list[UUID]:
        ids = sorted(
            k
            for k, r in self.rows.items()
            if r["kek_version"] == version and not r["revoked"] and r["env"] == env
        )
        return [k for k in ids if after is None or k > after][:limit]

    async def count_at_kek_version(self, version: int, env: str) -> int:
        return len(await self.ids_at_kek_version(version, len(self.rows) + 1, env))

    async def rewrap(
        self, key_id: UUID, *, from_version: int, dek_ref: str, kek_version: int
    ) -> bool:
        row = self.rows.get(key_id)
        if row is None or row["kek_version"] != from_version:
            return False
        row["dek_ref"], row["kek_version"] = dek_ref, kek_version
        return True

    async def touch_last_used(self, key_id: UUID) -> None:
        return None

    async def kcv_for(self, env: str, version: int) -> bytes | None:
        return self.kcvs.get((env, version))

    async def kcv_versions(self) -> list[tuple[str, int, bytes, bool]]:
        return [(e, v, k, (e, v) in self.retired) for (e, v), k in sorted(self.kcvs.items())]

    async def record_kcv(self, env: str, version: int, kcv: bytes) -> bytes:
        if (env, version) not in self.kcvs and kcv in self.kcvs.values():
            raise ValueError("kv_kcv_unique")  # mirrors the global UNIQUE(kcv) of 0020
        return self.kcvs.setdefault((env, version), kcv)


class AuthKeyStore(Protocol):
    """`auth_keys` (#2152, 21 §3.1.5a) plus the counts-only MFA probe. Records are plain dicts
    keyed by column: `id` (UUID), `env`, `purpose`, `key_version`, `origin`, `dek_ref`,
    `kek_version`."""

    async def rows_for(self, env: str) -> list[dict[str, Any]]:
        """Every row of `env` (C-2.11: env-namespaced read)."""

    async def insert_keyring(self, records: list[dict[str, Any]]) -> bool:
        """All `records` in one transaction; False, with nothing written, on any conflict."""

    async def count_mfa_material(self) -> int:
        """Unrevoked TOTP methods plus unused recovery codes, in every environment."""

    async def rewrap(
        self, key_id: UUID, *, env: str, from_version: int, dek_ref: str, kek_version: int
    ) -> bool:
        """Compare-and-set on `kek_version`; True iff this call moved the row."""


class InMemoryAuthKeyStore:
    """Test fake for `AuthKeyStore`. Never used with real keys."""

    def __init__(self, *, mfa_material: int = 0) -> None:
        self.rows: dict[UUID, dict[str, Any]] = {}
        self.mfa_material = mfa_material

    async def rows_for(self, env: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.rows.values() if r["env"] == env]

    async def insert_keyring(self, records: list[dict[str, Any]]) -> bool:
        rows = [*self.rows.values(), *records]  # the table and the batch, as one transaction sees
        ids = {r["id"] for r in rows}
        keys = {(r["env"], r["purpose"], r["key_version"]) for r in rows}
        if not len(ids) == len(keys) == len(rows):
            return False  # the primary key and ak_env_purpose_key_version: all or nothing
        self.rows.update((r["id"], dict(r)) for r in records)
        return True

    async def count_mfa_material(self) -> int:
        return self.mfa_material

    async def rewrap(
        self, key_id: UUID, *, env: str, from_version: int, dek_ref: str, kek_version: int
    ) -> bool:
        row = self.rows.get(key_id)
        if row is None or row["env"] != env or row["kek_version"] != from_version:
            return False
        row["dek_ref"], row["kek_version"] = dek_ref, kek_version
        return True
