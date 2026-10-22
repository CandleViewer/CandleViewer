"""Persistence ports for `api_keys` envelope columns, `kek_versions`, `auth_keys` counts and
the audit export signing keys (`audit_signing_keys`).

Records are plain dicts, keyed by `CredentialRow` field names (by `audit_signing_keys` column names
for export keys), so the Postgres adapter in M10 (`storage`) satisfies these Protocols
structurally without importing M2 (C-3.2).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from itertools import count
from typing import Any, Final, Protocol
from uuid import UUID

#: `(action, fields)` -> durable, hash-chained audit append (write-ahead; raises to refuse).
AuditSink = Callable[[str, dict[str, str]], Awaitable[None]]

#: An export key's public record (`list_keys`, `rotation`): 22's `AuditSigningKey` but `alg` and
#: `verified`, which are not stored, plus its environment and version.
EXPORT_KEY_PUBLIC: Final = (
    "env", "version", "key_id", "public_key", "fingerprint_sha256", "status", "valid_from",
    "valid_until", "retired_reason",
)  # fmt: skip
#: The active key's sealed record (`active`), which S6 opens: the seed sealed, the DEK wrapped.
EXPORT_KEY_SEALED: Final = (
    "id", "env", "version", "key_id", "public_key", "fingerprint_sha256", "sealed_seed",
    "dek_ref", "kek_version",
)  # fmt: skip
RETIRED_REASONS: Final = frozenset({"scheduled", "compromise", "unrecoverable"})
_REQUEST = ("created_by", "client_ref", "client_body_sha256")
_DEK_REF = re.compile(r"ek1:[0-9a-f]{120}")
_KEY_ID = re.compile(r"cv-audit-export-v[1-9][0-9]*:[0-9a-f]{16}")
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
#: A rotation's `200` shows the key it made as it was then (decision 5), even once retired.
_AS_MADE: Final = {"status": "active", "valid_until": None, "retired_reason": None}


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


class ExportKeyStore(Protocol):
    """`audit_signing_keys` (#889 S4, ADR-0039, 21 Sec.3.1.5b): the process environment's audit
    export signing keys. Bound to it, a store refuses another environment, in a call or a record,
    before any I/O (C-2.11). It moves sealed bytes only: before any write it refuses a
    `sealed_seed` that is not 60 bytes and a `dek_ref` that is not `ek1:` and 120 hex, so no
    plaintext seed or DEK is stored (C-2.7). A key record carries `id`, `env`, `version`, `key_id`,
    `public_key`, `sealed_seed`, `dek_ref` and `kek_version`; the store derives the fingerprint
    from `public_key` and refuses a `key_id` that is not the one derived (`ask_key_id`), so the id
    the seal binds is the row's. A rotation's record also carries its request: `created_by`,
    `client_ref` (stored as canonical lower-case UUID text) and `client_body_sha256` (decision 5).
    `audit` is the `(action, fields)` record committed with the change (C-2.9); its event time is
    the change's."""

    async def active(self, env: str) -> dict[str, Any] | None:
        """The active key's `EXPORT_KEY_SEALED` record, which S6 opens, or None. Its `env` is the
        row's own, never the argument."""
        ...

    async def list_keys(self, env: str) -> list[dict[str, Any]]:
        """Every key of `env` as an `EXPORT_KEY_PUBLIC` record, newest first: no seed, no wrap."""
        ...

    async def insert_first(
        self, record: dict[str, Any], *, audit: tuple[str, dict[str, str]]
    ) -> bool:
        """The environment's first key, version 1, active from its record's time, committed with
        that record. False, nothing written, when it has a key: another boot won (no second v1)."""
        ...

    async def rotate(
        self,
        record: dict[str, Any],
        *,
        retire: str,
        reason: str,
        audit: tuple[str, dict[str, str]],
    ) -> dict[str, Any] | None:
        """One transaction: the record's time T; the active key whose `key_id` is `retire` retired
        at T for `reason` and its seed destroyed (Q3), in one write; `record` inserted active from
        T, its version the retired key's plus one, which is the highest plus one; the record;
        commit. Returns the rotation's `200` as `rotation` rebuilds it, or None, nothing written,
        when `retire` is not the active key. Any failure rolls back all of it. A malformed
        `retire` raises `ValueError` before any I/O."""
        ...

    async def rotation(
        self, env: str, *, created_by: UUID, client_ref: str
    ) -> dict[str, Any] | None:
        """The durable idempotency read (decision 5), by `(env, created_by, client_ref)` only and
        at any age: `active`, the key the request made, as it was then; `retired`, the key one
        version lower; and the request's `client_body_sha256`, which the caller compares (409
        `idempotency_key_reuse`). None for another user's or environment's request (SR-E29-07)."""
        ...

    async def count_at_kek_version(self, version: int, env: str) -> int:
        """The keys of `env` holding a seed, wrapped under KEK `version`: what a KEK re-wrap must
        still move. A destroyed seed has nothing to re-wrap (Q3)."""
        ...

    async def rewrap(
        self,
        key_id: str,
        *,
        env: str,
        from_version: int,
        dek_ref: str,
        kek_version: int,
        audit: tuple[str, dict[str, str]],
    ) -> bool:
        """Compare-and-set on `kek_version` of the key `key_id` of `env` while it holds its seed;
        True iff this call moved it, and then the `audit` record, which is required, committed
        with it (C-2.9): a failure of either rolls back both. A malformed `key_id` or `dek_ref`,
        a `from_version` or `kek_version` that is not an int of at least 1, and a `kek_version`
        that is `from_version` (no re-wrap) raise `ValueError` before any I/O."""
        ...

    async def count_retired_with_seed(self, env: str) -> int:
        """Retired keys of `env` still holding a seed: Q3's `retired_with_seed` finding (I2)."""
        ...

    async def destroy_retired_seeds(self, env: str, *, audit: tuple[str, dict[str, str]]) -> int:
        """Q3's retried destroy: every retired key of `env` loses its seed, the `audit` record,
        which is required, committed with it when any did (C-2.9). How many did."""
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


def _now() -> datetime:
    return datetime.now(UTC)


def _wrapped(ref: object) -> bool:
    return isinstance(ref, str) and _DEK_REF.fullmatch(ref) is not None


def _canonical(ref: object) -> str:
    """An `Idempotency-Key` as `ask_client_ref` stores it; `ValueError` for no UUID."""
    return str(UUID(str(ref)))


def _key_id(value: object) -> str:
    """A key id as `ask_key_id` shapes it; `ValueError` for anything else, before any I/O."""
    if not isinstance(value, str) or _KEY_ID.fullmatch(value) is None:
        raise ValueError("an export key is named by its key id, cv-audit-export-v<N>:<16 hex>")
    return value


def _public(row: Mapping[str, Any]) -> dict[str, Any]:
    return {k: row[k] for k in EXPORT_KEY_PUBLIC}


def _rotation(new: Mapping[str, Any], old: Mapping[str, Any]) -> dict[str, Any]:
    made = {"active": _public(new) | _AS_MADE, "retired": _public(old)}
    return made | {"client_body_sha256": new["client_body_sha256"]}


def _key_row(record: Mapping[str, Any], *, request: bool) -> dict[str, Any]:
    """`record`'s columns, refused (`ValueError`) as every store refuses them before any write: a
    seed that is not 60 sealed bytes, a DEK that is not `ek1:` and 120 hex, a rotation's request
    incomplete. `client_ref` is made canonical; a first key carries no request."""
    row = {k: record[k] for k in EXPORT_KEY_SEALED if k != "fingerprint_sha256"}
    seed = row["sealed_seed"]
    if type(seed) is not bytes or len(seed) != 60 or not _wrapped(row["dek_ref"]):
        raise ValueError("an export key is stored only sealed: a 60-byte seed, an ek1 DEK wrap")
    row |= {k: record.get(k) if request else None for k in _REQUEST}
    if request and (row["created_by"] is None or row["client_body_sha256"] is None):
        raise ValueError("a rotated export key carries its request")
    return row | ({"client_ref": _canonical(row["client_ref"])} if request else {})


def _rewrap_checked(key_id: object, dek_ref: object, from_version: object, to: object) -> None:
    """A re-wrap's arguments, refused (`ValueError`) as every store refuses them before any I/O: a
    malformed key id or wrap, a KEK version on either side that is not an int of at least 1
    (`ask_kek_version`), or one that moves nothing (I3)."""
    _key_id(key_id)
    if not _wrapped(dek_ref):
        raise ValueError("a DEK is stored only wrapped: ek1 and 120 hex")
    if any(type(v) is not int or v < 1 for v in (from_version, to)) or to == from_version:
        raise ValueError("ask_kek_version, or a re-wrap that moves no KEK version")


class _RequestTaken(ValueError):
    """The fake's `ExportKeyRequestTaken` (M10): a rotation's request stored already. M2 tells it
    apart by this `code`, as `broker._io` reads a typed refusal of another module (I1)."""

    code = "STORAGE_EXPORT_KEY_REQUEST_TAKEN"


class InMemoryExportKeyStore:
    """Test fake for `ExportKeyStore`: `rows` holds `audit_signing_keys` rows of any environment
    and `audit` each record committed with a change. Bound to one environment, it refuses what a
    store and the table (21 Sec.3.1.5b) refuse. `clock` gives a change's time; while
    `audit_fails` is set, a record fails and so does the change it records."""

    def __init__(self, env: str = "demo", clock: Callable[[], datetime] = _now) -> None:
        self.env, self.clock = env, clock
        self.rows: list[dict[str, Any]] = []
        self.audit: list[tuple[str, dict[str, str]]] = []
        self.audit_fails = False

    def _mine(self, env: object) -> list[dict[str, Any]]:
        if env != self.env:
            raise ValueError("the export key store serves only the process environment")
        return [r for r in self.rows if r["env"] == env]

    def _checked(self, row: dict[str, Any]) -> str:
        """`row`'s fingerprint, or the refusal of a CHECK, which Postgres fires before any unique
        key: `ask_kek_version`, `ask_public_key`, `ask_key_id` and a request's `sha256_hex`."""
        if type(row["kek_version"]) is not int or row["kek_version"] < 1:
            raise ValueError("ask_kek_version")
        if type(row["public_key"]) is not bytes or len(row["public_key"]) != 32:
            raise ValueError("ask_public_key")
        fp = hashlib.sha256(row["public_key"]).hexdigest()
        if row["key_id"] != f"cv-audit-export-v{row['version']}:{fp[:16]}":
            raise ValueError("ask_key_id")
        body = row["client_body_sha256"]
        if body is not None and (not isinstance(body, str) or not _SHA256_HEX.fullmatch(body)):
            raise ValueError("sha256_hex")
        return fp

    def _new(self, row: dict[str, Any], at: datetime) -> dict[str, Any]:
        """`row` as the table inserts it, active from `at`, or the refusal of a CHECK, of the
        primary key or of a unique key of 21 Sec.3.1.5b (the version, the fingerprint, the
        request: `_RequestTaken`). The `created_by` foreign key and the column types are not
        checked."""
        fp, ref = self._checked(row), row["client_ref"]
        if any(r["id"] == row["id"] for r in self.rows):
            raise ValueError("an export key's id is unique")
        for r in self._mine(row["env"]):
            if r["version"] == row["version"] or r["fingerprint_sha256"] == fp:
                raise ValueError("an export key's version, fingerprint and request are unique")
            if ref and (r["created_by"], r["client_ref"]) == (row["created_by"], ref):
                raise _RequestTaken("an export key's version, fingerprint and request are unique")
        return row | {"fingerprint_sha256": fp, "status": "active", "valid_from": at} | _AS_MADE

    def _commit(self, rows: list[dict[str, Any]], audit: tuple[str, dict[str, str]]) -> None:
        """The change and its record, or neither: one transaction."""
        if self.audit_fails:
            raise RuntimeError("audit record not written")
        self.audit.append((audit[0], dict(audit[1])))
        self.rows = rows

    def _seeded(self, env: str) -> list[dict[str, Any]]:
        return [r for r in self._mine(env) if r["sealed_seed"] is not None]

    async def active(self, env: str) -> dict[str, Any] | None:
        live = (r for r in self._mine(env) if r["status"] == "active")
        return next(({k: r[k] for k in EXPORT_KEY_SEALED} for r in live), None)

    async def list_keys(self, env: str) -> list[dict[str, Any]]:
        return [_public(r) for r in sorted(self._mine(env), key=lambda r: -r["version"])]

    async def insert_first(
        self, record: dict[str, Any], *, audit: tuple[str, dict[str, str]]
    ) -> bool:
        mine, row = self._mine(record.get("env")), _key_row(record, request=False)
        if row["version"] != 1:
            raise ValueError("an environment's first export key is version 1")
        self._checked(row)  # the CHECKs before the unique key, as Postgres fires them
        if any(r["id"] == row["id"] for r in self.rows):
            raise ValueError("an export key's id is unique")  # the primary key, any environment
        if mine:
            return False
        self._commit([*self.rows, self._new(row, self.clock())], audit)
        return True

    async def rotate(
        self,
        record: dict[str, Any],
        *,
        retire: str,
        reason: str,
        audit: tuple[str, dict[str, str]],
    ) -> dict[str, Any] | None:
        mine, row = self._mine(record.get("env")), _key_row(record, request=True)
        _key_id(retire)
        if reason not in RETIRED_REASONS:
            raise ValueError("a retired_reason of 22's three")
        at = self.clock()
        old = next((r for r in mine if r["key_id"] == retire and r["status"] == "active"), None)
        if old is None:
            return None
        if not row["version"] == old["version"] + 1 == max(r["version"] for r in mine) + 1:
            raise ValueError("a rotation steps the export key version by one")
        gone = {"status": "retired", "valid_until": at, "retired_reason": reason}
        retired, new = old | gone | {"sealed_seed": None}, self._new(row, at)
        self._commit([retired if r is old else r for r in self.rows] + [new], audit)
        return _rotation(new, retired)

    async def rotation(
        self, env: str, *, created_by: UUID, client_ref: str
    ) -> dict[str, Any] | None:
        mine, request = self._mine(env), (created_by, _canonical(client_ref))
        new = next((r for r in mine if (r["created_by"], r["client_ref"]) == request), None)
        if new is None:
            return None
        (old,) = (r for r in mine if r["version"] == new["version"] - 1)
        return _rotation(new, old)

    async def count_at_kek_version(self, version: int, env: str) -> int:
        return sum(r["kek_version"] == version for r in self._seeded(env))

    async def rewrap(
        self,
        key_id: str,
        *,
        env: str,
        from_version: int,
        dek_ref: str,
        kek_version: int,
        audit: tuple[str, dict[str, str]],
    ) -> bool:
        seeded = self._seeded(env)
        _rewrap_checked(key_id, dek_ref, from_version, kek_version)
        for r in seeded:
            if (r["key_id"], r["kek_version"]) == (key_id, from_version):
                if dek_ref == r["dek_ref"]:  # the trigger: a DEK moves with its KEK version (23514)
                    raise ValueError("a re-wrap moves the DEK with its KEK version")
                moved = r | {"dek_ref": dek_ref, "kek_version": kek_version}
                self._commit([moved if x is r else x for x in self.rows], audit)
                return True
        return False  # no row matched: a stale or replayed call, as in SQL

    async def count_retired_with_seed(self, env: str) -> int:
        return sum(r["status"] == "retired" for r in self._seeded(env))

    async def destroy_retired_seeds(self, env: str, *, audit: tuple[str, dict[str, str]]) -> int:
        held = {id(r) for r in self._seeded(env) if r["status"] == "retired"}
        if held:
            gone = [r | {"sealed_seed": None} if id(r) in held else r for r in self.rows]
            self._commit(gone, audit)
        return len(held)
