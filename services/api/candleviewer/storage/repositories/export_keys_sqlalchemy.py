"""Postgres adapter for M2's audit export signing keys (#889 S4b, ADR-0039; 21 Sec.3.1.5b).

Lives in M10 so M2 never imports a driver; it moves plain dicts, so `ExportKeyStore` in
`secrets/store.py` is satisfied structurally (C-3.2). It moves only sealed seeds and wrapped DEKs,
refusing before any write a seed that is not 60 bytes and a wrap that is not `ek1:` and 120 hex,
and never logs a row. Bound to the process environment, it refuses a call or a record naming
another, or a key not named by its key id, before any I/O, and every statement names it (C-2.11).
A change's record (a generation, a rotation, and since S6 a re-wrap or a destroy) is built by a
function the composition root injects (`admin.wiring.secrets_audit_row`) and inserted in the
change's transaction by `insert_audit_row_locked`: row locks first, the chain lock last, READ
COMMITTED (C-2.9). A database error leaves as `StorageQueryFailed` with the SQLSTATE alone, nothing
chained: the driver's text repeats the failing row, sealed seed and wrap included (C-12.6, class S).
Two constraint names are read: another boot's first key (`insert_first`) and a retried request
(`ExportKeyRequestTaken`).
Static SQL with explicit columns (21 Sec.12 forbids `SELECT *`; a unit test guards it), no DELETE.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
import structlog
from sqlalchemy.exc import DBAPIError

from candleviewer.domain.primitives import Environment
from candleviewer.storage.errors import (
    ExportKeyAuditNotWritten,
    ExportKeyRequestTaken,
    StorageQueryFailed,
)
from candleviewer.storage.repositories.audit_sqlalchemy import insert_audit_row_locked
from candleviewer.storage.repositories.credentials_sqlalchemy import AuditRowBuilder
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    constraint_of,
    sqlstate_of,
)

_ACTIVE = sa.text(
    "SELECT id, env::text AS env, version, key_id, public_key, fingerprint_sha256, sealed_seed, "
    "dek_ref, kek_version FROM audit_signing_keys "
    "WHERE env = CAST(:env AS exchange_env) AND status = 'active'"
)
# The public records name neither `sealed_seed` nor `dek_ref` (the unit test pins it).
_LIST = sa.text(
    "SELECT env::text AS env, version, key_id, public_key, fingerprint_sha256, status, "
    "valid_from, valid_until, retired_reason FROM audit_signing_keys "
    "WHERE env = CAST(:env AS exchange_env) ORDER BY version DESC"
)
# A request's key and the one before it, found by `(env, created_by, client_ref)` only (SR-E29-07).
_ROTATION = sa.text(
    "SELECT k.env::text AS env, k.version, k.key_id, k.public_key, k.fingerprint_sha256, "
    "k.status, k.valid_from, k.valid_until, k.retired_reason, k.client_body_sha256 "
    "FROM audit_signing_keys n JOIN audit_signing_keys k "
    "ON k.env = n.env AND k.version IN (n.version, n.version - 1) "
    "WHERE n.env = CAST(:env AS exchange_env) AND n.created_by = :created_by "
    "AND n.client_ref = :client_ref ORDER BY k.version DESC"
)
# The database derives the fingerprint, and `ask_key_id` refuses a key id it does not derive.
_INSERT = sa.text(
    "INSERT INTO audit_signing_keys (id, env, version, key_id, public_key, fingerprint_sha256, "
    "sealed_seed, dek_ref, kek_version, status, valid_from, created_by, client_ref, "
    "client_body_sha256) VALUES (:id, CAST(:env AS exchange_env), :version, :key_id, "
    ":public_key, encode(sha256(:public_key), 'hex'), :sealed_seed, :dek_ref, :kek_version, "
    "'active', :at, :created_by, :client_ref, :client_body_sha256) "
    "RETURNING env::text AS env, version, key_id, public_key, fingerprint_sha256, status, "
    "valid_from, valid_until, retired_reason, client_body_sha256"
)
# The retire and Q3's destroy in one write: the table admits a retire that keeps the seed.
_RETIRE = sa.text(
    "UPDATE audit_signing_keys SET status = 'retired', valid_until = :at, "
    "retired_reason = :reason, sealed_seed = NULL "
    "WHERE env = CAST(:env AS exchange_env) AND key_id = :key_id AND status = 'active' "
    "RETURNING env::text AS env, version, key_id, public_key, fingerprint_sha256, status, "
    "valid_from, valid_until, retired_reason, client_body_sha256"
)
_TOP = sa.text("SELECT max(version) FROM audit_signing_keys WHERE env = CAST(:env AS exchange_env)")
# Only the wrap and its version move, on a key still holding its seed (Q3).
_REWRAP = sa.text(
    "UPDATE audit_signing_keys SET dek_ref = :dek_ref, kek_version = :to_v "
    "WHERE env = CAST(:env AS exchange_env) AND key_id = :key_id AND kek_version = :from_v "
    "AND sealed_seed IS NOT NULL"
)
_COUNT = sa.text(
    "SELECT count(*) FROM audit_signing_keys WHERE env = CAST(:env AS exchange_env) "
    "AND kek_version = :v AND sealed_seed IS NOT NULL"
)
_RETAINED = sa.text(
    "SELECT count(*) FROM audit_signing_keys WHERE env = CAST(:env AS exchange_env) "
    "AND status = 'retired' AND sealed_seed IS NOT NULL"
)
_DESTROY = sa.text(
    "UPDATE audit_signing_keys SET sealed_seed = NULL WHERE env = CAST(:env AS exchange_env) "
    "AND status = 'retired' AND sealed_seed IS NOT NULL RETURNING key_id, fingerprint_sha256"
)

_KEY = ("id", "env", "version", "key_id", "public_key", "sealed_seed", "dek_ref", "kek_version")
_REQUEST = ("created_by", "client_ref", "client_body_sha256")
_REASONS = frozenset({"scheduled", "compromise", "unrecoverable"})
#: What a concurrent first boot holds once it commits: losing to it inserts no second v1.
_FIRST_TAKEN = frozenset({"ask_env_version", "ux_ask_active"})
_DEK_REF = re.compile(r"ek1:[0-9a-f]{120}")
#: `ask_key_id`'s shape, as `secrets/store.py`'s `_KEY_ID` (a unit test pins the two equal).
_KEY_ID = re.compile(r"cv-audit-export-v[1-9][0-9]*:[0-9a-f]{16}")
#: A rotation's `200` shows the key it made as it was then (decision 5), even once retired.
_AS_MADE = {"status": "active", "valid_until": None, "retired_reason": None}


def _fits(pattern: re.Pattern[str], value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _canonical(ref: object) -> str:
    """An `Idempotency-Key` as `ask_client_ref` stores it; `ValueError` for no UUID."""
    return str(UUID(str(ref)))


def _destroyed(fields: dict[str, str], gone: list[tuple[str, str]]) -> dict[str, str]:
    """Q3's destroy record as M2's fake builds it (`secrets/store.py`; a unit test pins the two)."""
    named = {"destroyed": str(len(gone)), "key_ids": ",".join(k for k, _ in gone)}
    return {**fields, **named, "fingerprints_sha256": ",".join(f for _, f in gone)}


def _rotation(new: dict[str, Any], old: dict[str, Any]) -> dict[str, Any]:
    """The rotation's `200` and its request's fingerprint, which the caller compares."""
    digest, _ = new.pop("client_body_sha256"), old.pop("client_body_sha256")
    return {"active": new | _AS_MADE, "retired": old, "client_body_sha256": digest}


async def _record(session: Any, row: dict[str, Any]) -> None:
    if not await insert_audit_row_locked(session, row):
        raise ExportKeyAuditNotWritten("the export key's record was not written; nothing was")


def _at(row: dict[str, Any]) -> datetime:
    """A record's `event_ts`, the time of the change it records; a naive one is refused before
    any I/O, so no comparison with a stored time can fail after the commit."""
    at = datetime.fromisoformat(row["event_ts"])
    if at.tzinfo is None:
        raise ValueError("a record's event_ts is timezone-aware")
    return at


class ExportKeyEnvironmentError(ValueError):
    """A call or a record named an environment other than the process's (C-2.11); refused
    before any I/O."""


class SqlAlchemyExportKeyStore:
    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        env: Environment,
        audit_row: AuditRowBuilder,
    ) -> None:
        self._rel, self._env, self._audit_row = relational, env, audit_row

    def _own(self, *envs: object) -> None:
        if any(env != self._env for env in envs):
            raise ExportKeyEnvironmentError("the export key store serves only its environment")

    def _params(self, record: dict[str, Any], *, request: bool) -> dict[str, Any]:
        """The INSERT's values, refused before any I/O: another environment's record, a seed that
        is not 60 sealed bytes, a DEK that is not `ek1:` and 120 hex, a rotation's request
        incomplete (`ValueError`). `client_ref` goes in canonical; a first key has no request."""
        self._own(record.get("env"))
        params = {k: record[k] for k in _KEY} | dict.fromkeys(_REQUEST)
        seed = params["sealed_seed"]
        if type(seed) is not bytes or len(seed) != 60 or not _fits(_DEK_REF, params["dek_ref"]):
            raise ValueError("an export key is stored only sealed: a 60-byte seed, an ek1 DEK wrap")
        if request:
            params |= {k: record.get(k) for k in _REQUEST}
            if params["created_by"] is None or params["client_body_sha256"] is None:
                raise ValueError("a rotated export key carries its request")
            params["client_ref"] = _canonical(params["client_ref"])
        return params

    async def _exec(self, stmt: sa.TextClause, **params: Any) -> Any:
        """One statement in its own transaction: its rows as dicts, or its row count."""
        try:
            async with self._rel.unit_of_work() as uow:
                res: Any = await uow.session.execute(stmt, params)
                out = [dict(m) for m in res.mappings().all()] if res.returns_rows else res.rowcount
                await uow.commit()
                return out
        except DBAPIError as exc:
            state = sqlstate_of(exc)
        raise StorageQueryFailed(state)  # the SQLSTATE alone, nothing chained (C-12.6)

    async def _update(
        self, stmt: sa.TextClause, params: dict[str, Any], audit: tuple[str, dict[str, str]]
    ) -> int:
        """One UPDATE and, only if it changed a row, its `audit` record, built before any I/O and
        written with the chain lock last: one transaction, so a failure of either rolls back
        both (C-2.9). The rows it changed."""
        row = self._audit_row(*audit)
        try:
            async with self._rel.unit_of_work() as uow:
                res: Any = await uow.session.execute(stmt, params)
                if changed := int(res.rowcount):
                    await _record(uow.session, row)
                await uow.commit()
                return changed
        except DBAPIError as exc:
            state = sqlstate_of(exc)
        raise StorageQueryFailed(state)  # the SQLSTATE alone, nothing chained (C-12.6)

    async def active(self, env: str) -> dict[str, Any] | None:
        """The active key's sealed record, its `env` read from the row."""
        self._own(env)
        rows: list[dict[str, Any]] = await self._exec(_ACTIVE, env=env)
        return rows[0] if rows else None

    async def list_keys(self, env: str) -> list[dict[str, Any]]:
        self._own(env)
        return list(await self._exec(_LIST, env=env))

    async def insert_first(
        self, record: dict[str, Any], *, audit: tuple[str, dict[str, str]]
    ) -> bool:
        """The key and its generation record, the key active from the record's `event_ts`. A
        unique violation on `ask_env_version` or `ux_ask_active` is a boot that won first: False,
        nothing written. Any other conflict, a reused `id` included, raises."""
        params = self._params(record, request=False)
        if params["version"] != 1:
            raise ValueError("an environment's first export key is version 1")
        row = self._audit_row(*audit)
        params["at"] = _at(row)
        try:
            async with self._rel.unit_of_work() as uow:
                await uow.session.execute(_INSERT, params)
                await _record(uow.session, row)
                await uow.commit()
                return True
        except DBAPIError as exc:
            state, name = sqlstate_of(exc), constraint_of(exc)
        if state == "23505" and name in _FIRST_TAKEN:
            return False
        raise StorageQueryFailed(state)  # the SQLSTATE alone, nothing chained (C-12.6)

    async def rotate(
        self,
        record: dict[str, Any],
        *,
        retire: str,
        reason: str,
        audit: tuple[str, dict[str, str]],
    ) -> dict[str, Any] | None:
        """One READ COMMITTED transaction: (1) the record, built first, gives T, its `event_ts`;
        (2) the active key `retire` is retired at T and its seed destroyed in one UPDATE, which
        locks its row; (3) under that lock, `record` must be the next version, the retired one's
        and the highest plus one, and goes in active from T; (4) the record, the chain lock last;
        (5) commit. None when `retire` is not the active key: nothing was written. A T before its
        `valid_from` (a clock stepped back) still ends it, with a warning (21 Sec.3.1.5b)."""
        params = self._params(record, request=True)
        if not _fits(_KEY_ID, retire) or reason not in _REASONS:
            raise ValueError("a key id to retire; reason: scheduled, compromise or unrecoverable")
        row = self._audit_row(*audit)
        params["at"] = at = _at(row)
        retiring = {"env": self._env, "key_id": retire, "at": at, "reason": reason}
        try:
            async with self._rel.unit_of_work() as uow:
                s: Any = uow.session
                old = (await s.execute(_RETIRE, retiring)).mappings().one_or_none()
                if old is None:
                    return None
                stepped_back = at < old["valid_from"]  # a clock stepped back: T all the same
                top = (await s.execute(_TOP, {"env": self._env})).scalar_one()
                if not params["version"] == old["version"] + 1 == top + 1:
                    raise ValueError("a rotation steps the export key version by one")
                new = (await s.execute(_INSERT, params)).mappings().one()
                await _record(s, row)
                await uow.commit()
                if stepped_back:  # logged only once committed (21 Sec.3.1.5b)
                    ids = {"retired_key_id": old["key_id"], "active_key_id": new["key_id"]}
                    log = structlog.get_logger(__name__)  # resolved per call (#2008)
                    log.warning("audit.export_key.clock_anomaly", env=self._env, **ids)
                return _rotation(dict(new), dict(old))
        except DBAPIError as exc:
            state, name = sqlstate_of(exc), constraint_of(exc)
        if (state, name) == ("23505", "ask_env_request"):  # a retry that raced its first try
            raise ExportKeyRequestTaken("this rotation's request is stored already; nothing was")
        raise StorageQueryFailed(state)  # the SQLSTATE alone, nothing chained (C-12.6)

    async def rotation(
        self, env: str, *, created_by: UUID, client_ref: str
    ) -> dict[str, Any] | None:
        self._own(env)
        ref = _canonical(client_ref)
        rows = await self._exec(_ROTATION, env=env, created_by=created_by, client_ref=ref)
        if not rows:
            return None
        new, old = rows  # the request's key, then the one it retired
        return _rotation(new, old)

    async def count_at_kek_version(self, version: int, env: str) -> int:
        self._own(env)
        return int((await self._exec(_COUNT, env=env, v=version))[0]["count"])

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
        """The compare-and-set, then its record, refused before any I/O as M2's fake refuses it.
        The trigger refuses a DEK that does not move with its KEK version (23514)."""
        self._own(env)
        if not (_fits(_KEY_ID, key_id) and _fits(_DEK_REF, dek_ref)):
            raise ValueError("a key id, and a DEK stored only wrapped: ek1 and 120 hex")
        versions = (from_version, kek_version)
        if any(type(v) is not int or v < 1 for v in versions) or kek_version == from_version:
            raise ValueError("ask_kek_version, or a re-wrap that moves no KEK version")
        move = {"env": env, "key_id": key_id, "from_v": from_version, "to_v": kek_version}
        return await self._update(_REWRAP, move | {"dek_ref": dek_ref}, audit) == 1

    async def count_retired_with_seed(self, env: str) -> int:
        self._own(env)
        return int((await self._exec(_RETAINED, env=env))[0]["count"])

    async def destroy_retired_seeds(
        self, env: str, *, audit: tuple[str, dict[str, str]]
    ) -> list[tuple[str, str]]:
        """The UPDATE's RETURNING names the keys its record names (#889 S6b, F3). The record is
        built once before any I/O, so a refused one reaches no database, then again with them."""
        self._own(env)
        self._audit_row(*audit)
        try:
            async with self._rel.unit_of_work() as uow:
                res: Any = await uow.session.execute(_DESTROY, {"env": env})
                gone = sorted((r["key_id"], r["fingerprint_sha256"]) for r in res.mappings().all())
                if gone:
                    await _record(
                        uow.session, self._audit_row(audit[0], _destroyed(audit[1], gone))
                    )
                await uow.commit()
                return gone
        except DBAPIError as exc:
            state = sqlstate_of(exc)
        raise StorageQueryFailed(state)  # the SQLSTATE alone, nothing chained (C-12.6)
