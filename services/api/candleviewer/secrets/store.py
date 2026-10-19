"""Persistence ports for `api_keys` envelope columns, `kek_versions` and `auth_keys` counts.

Records are plain dicts keyed by `CredentialRow` field names, so the Postgres adapter in
M10 (`storage`) satisfies these Protocols structurally without importing M2 (C-3.2).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from itertools import count
from typing import Any, Protocol
from uuid import UUID

#: `(action, fields)` -> durable, hash-chained audit append (write-ahead; raises to refuse).
AuditSink = Callable[[str, dict[str, str]], Awaitable[None]]


class CredentialStore(Protocol):
    async def insert(self, record: dict[str, Any]) -> None: ...
    async def get(self, key_id: UUID, env: str) -> dict[str, Any] | None:
        """The row only if its account is in `env` (C-2.11: env-namespaced read). It carries
        `can_withdraw` and `can_transfer` as bools and `permission_snapshot` as a dict: the
        borrow's C-2.8 re-check (SR-E27-14) refuses anything else, a missing flag included."""
        ...

    async def mark_revoked(self, key_id: UUID) -> None: ...
    async def ids_at_kek_version(
        self, version: int, limit: int, env: str, after: UUID | None = None
    ) -> list[UUID]:
        """Ids at `version` in `env` (C-2.11) that neither revocation signal (`revoked_at`,
        status `revoked`) fences, ordered by id, after `after`."""
        ...

    async def count_at_kek_version(self, version: int, env: str) -> int:
        """How many rows `ids_at_kek_version` lists, all pages together."""
        ...

    async def count_rewrapped_since_enrolment(self, version: int, env: str) -> int:
        """Rows of `env` at `version` created before `(env, version)` was enrolled in
        `kek_versions`. Only a re-wrap puts a row there (`store()` writes the current version,
        enrolled at boot first), so these are an earlier run's progress; a revoked row counts
        too, since the rotation still moved it (#2266)."""
        ...

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
        """Compare-and-set on `kek_version` of a row of `env` that neither revocation signal
        (`revoked_at`, status `revoked`) fences. True iff this call moved the row, and then the
        `audit` record `(action, fields)` committed in the same transaction (C-2.9, #2266);
        a failure of either rolls back both."""
        ...

    async def count_stranded(self, env: str, *loaded_versions: int) -> int:
        """Rows of `env` that neither revocation signal fences (as `ids_at_kek_version`) at a KEK
        version not in `loaded_versions`: keys a process with only those KEKs cannot open."""
        ...

    async def touch_last_used(self, key_id: UUID) -> None: ...


class AuthKeyStore(Protocol):
    """`auth_keys` (#2152, ADR-0009 Amendment 4): the environment's auth keyring rows, which
    only the rotation boot re-wraps. A KEK re-wrap run counts them (#2266); #2152 S4 adds the
    rest of this port."""

    async def count_at_kek_version(self, version: int, env: str) -> int:
        """The rows of `env`, the process's environment, wrapped under KEK `version`."""
        ...


class KcvStore(Protocol):
    """`kek_versions`: one KEK lineage per environment, keyed `(env, version)` (#2338)."""

    async def kcv_for(self, env: str, version: int) -> bytes | None: ...
    async def kcv_versions(self) -> list[tuple[str, int, bytes, bool]]:
        """All `(env, version, kcv, retired)` rows, every environment (KCVs are not secret)."""
        ...

    async def record_kcv(
        self, env: str, version: int, kcv: bytes, *, audit: tuple[str, dict[str, str]]
    ) -> tuple[bytes, bool]:
        """Insert-if-absent; return the KCV now stored for `(env, version)` (re-read after
        conflict) and whether this call inserted it, the `audit` record `(action, fields)` then
        committed with it (C-2.9, #2266). A KCV under another key raises (`kv_kcv_unique`)."""
        ...


class InMemoryCredentialStore:
    """Test fake for both ports. Never used with real credentials."""

    def __init__(self) -> None:
        self.rows: dict[UUID, dict[str, Any]] = {}
        self.kcvs: dict[tuple[str, int], bytes] = {}
        self.retired: set[tuple[str, int]] = set()
        #: `(action, fields)` of each record `rewrap` committed with a moved row.
        self.rewrap_audit: list[tuple[str, dict[str, str]]] = []
        #: `(action, fields)` of each record `record_kcv` committed with an enrolment.
        self.kcv_audit: list[tuple[str, dict[str, str]]] = []
        #: When each row was inserted and each KCV enrolled, as `created_at` orders them.
        self.created: dict[UUID, int] = {}
        self.enrolled: dict[tuple[str, int], int] = {}
        self._clock = count()

    async def insert(self, record: dict[str, Any]) -> None:
        self.rows[record["id"]] = dict(record)
        self.created[record["id"]] = next(self._clock)

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
            if r["kek_version"] == version and r["env"] == env
            if not r["revoked"] and r.get("status") != "revoked"
        )
        return [k for k in ids if after is None or k > after][:limit]

    async def count_at_kek_version(self, version: int, env: str) -> int:
        return len(await self.ids_at_kek_version(version, len(self.rows) + 1, env))

    async def count_rewrapped_since_enrolment(self, version: int, env: str) -> int:
        at = self.enrolled.get((env, version))
        if at is None:  # never enrolled through `record_kcv`: no row predates it
            return 0
        ids = [k for k, r in self.rows.items() if r["env"] == env and r["kek_version"] == version]
        return sum(self.created.get(k, at) < at for k in ids)

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
        row = self.rows.get(key_id)
        if row is None or row["env"] != env or row["kek_version"] != from_version:
            return False
        if row["revoked"] or row.get("status") == "revoked":
            return False
        row["dek_ref"], row["kek_version"] = dek_ref, kek_version
        self.rewrap_audit.append((audit[0], dict(audit[1])))
        return True

    async def count_stranded(self, env: str, *loaded_versions: int) -> int:
        return sum(
            r["env"] == env and r["kek_version"] not in loaded_versions
            for r in self.rows.values()
            if not r["revoked"] and r.get("status") != "revoked"
        )

    async def touch_last_used(self, key_id: UUID) -> None:
        return None

    async def kcv_for(self, env: str, version: int) -> bytes | None:
        return self.kcvs.get((env, version))

    async def kcv_versions(self) -> list[tuple[str, int, bytes, bool]]:
        return [(e, v, k, (e, v) in self.retired) for (e, v), k in sorted(self.kcvs.items())]

    async def record_kcv(
        self, env: str, version: int, kcv: bytes, *, audit: tuple[str, dict[str, str]]
    ) -> tuple[bytes, bool]:
        if (env, version) in self.kcvs:
            return self.kcvs[(env, version)], False
        if kcv in self.kcvs.values():
            raise ValueError("kv_kcv_unique")  # mirrors the global UNIQUE(kcv) of 0020
        self.kcvs[(env, version)], self.enrolled[(env, version)] = kcv, next(self._clock)
        self.kcv_audit.append((audit[0], dict(audit[1])))
        return kcv, True


class InMemoryAuthKeyStore:
    """Test fake for `AuthKeyStore`: `rows` holds `auth_keys` records (`env`, `kek_version`) of any
    environment. Bound to one, as the M10 adapter is, it refuses a call naming another (#3505)."""

    def __init__(self, env: str = "demo") -> None:
        self.rows: list[dict[str, Any]] = []
        self.env = env

    async def count_at_kek_version(self, version: int, env: str) -> int:
        if env != self.env:
            raise ValueError("the auth key store serves only the process environment")
        return sum(r["env"] == env and r["kek_version"] == version for r in self.rows)
