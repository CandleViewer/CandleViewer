"""`SqlAlchemyAuditRepository` — the concrete Postgres implementation of
`candleviewer.audit.repository.AuditRepository` (E09-T02).

Lives in M10 (`storage`, allowed to import `sqlalchemy`) so `candleviewer.audit`
never imports a storage driver directly (CONSTITUTION.md ADR-0003, C-3.1).
Structurally compatible with the `AuditRepository` Protocol without importing
`candleviewer.audit` — the composition root injects it into `AuditService(repository=...)`;
neither module imports the other.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import sqlalchemy as sa
import structlog

from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class AuditReadFailed(StorageTierUnavailable):
    """An audit read failed in the database. Carries only the SQLSTATE, never the
    statement or its bound parameters (the filters can hold an IP address)."""

    def __init__(self, sqlstate: str | None) -> None:
        super().__init__(f"audit read failed (sqlstate {sqlstate or 'unknown'})")
        self.sqlstate = sqlstate


_ADVISORY_LOCK_SQL = sa.text("SELECT pg_advisory_xact_lock(hashtext('audit_log'))")

_INSERT_SQL = sa.text("""
    INSERT INTO audit_log
        (record_id, actor_user_id, actor_label, actor_ip, session_id, action, object_kind,
         object_id, object_label, outcome, severity, reason, before_state,
         after_state, request_id, env, event_ts)
    VALUES
        (:record_id, :actor_user_id, :actor_label, :actor_ip, :session_id, :action, :object_kind,
         :object_id, :object_label, :outcome, :severity, :reason,
         CAST(:before_state AS jsonb), CAST(:after_state AS jsonb), :request_id, :env, :event_ts)
    ON CONFLICT (record_id) DO NOTHING
    """)

_HEAD_SQL = sa.text("SELECT id, entry_hash FROM audit_log ORDER BY id DESC LIMIT 1")
_COUNT_SQL = sa.text("SELECT count(*) FROM audit_log")
_ENTRY_HASH_SQL = sa.text("SELECT entry_hash FROM audit_log WHERE id = :id")

#: Every hashed column is rendered to text *by Postgres*, with exactly the
#: casts `audit_chain()` uses, so the Python verifier encodes the same bytes
#: the trigger hashed (see `_VERIFY_BATCH_SQL`).

#: Fixed statements (no string-built SQL — Semgrep/Bandit B608): every
#: optional filter is a typed, bound parameter that is a no-op when NULL.
_QUERY_PAGE_SQL = sa.text(
    "SELECT id, event_ts, actor_user_id, action, object_kind, object_id, outcome, "
    "severity, actor_ip, request_id, entry_hash, prev_hash FROM audit_log WHERE "
    "(CAST(:actor_user_id AS uuid) IS NULL OR actor_user_id = CAST(:actor_user_id AS uuid)) "
    "AND (CAST(:actions AS text[]) IS NULL OR action = ANY(CAST(:actions AS text[]))) "
    "AND (CAST(:subject_type AS text) IS NULL OR object_kind = CAST(:subject_type AS text)) "
    "AND (CAST(:severity AS severity) IS NULL OR severity = CAST(:severity AS severity)) "
    "AND (CAST(:outcome AS audit_outcome) IS NULL "
    "OR outcome = CAST(:outcome AS audit_outcome)) "
    "AND (CAST(:from_ts AS timestamptz) IS NULL OR event_ts >= CAST(:from_ts AS timestamptz)) "
    "AND (CAST(:to_ts AS timestamptz) IS NULL OR event_ts <= CAST(:to_ts AS timestamptz)) "
    "AND (CAST(:ip AS inet) IS NULL OR actor_ip = CAST(:ip AS inet)) "
    "AND (CAST(:cursor AS bigint) IS NULL OR id < CAST(:cursor AS bigint)) "
    "ORDER BY id DESC LIMIT :limit"
)

_SET_TIMEOUT_SQL = sa.text("SELECT set_config('statement_timeout', :v, true)")

#: SQLSTATE 57014 `query_canceled`: raised when `statement_timeout` fires.
_QUERY_CANCELED = "57014"


def _sqlstate(exc: sa.exc.DBAPIError) -> str | None:
    orig: object = exc.orig
    for attr in ("sqlstate", "pgcode"):
        code = getattr(orig, attr, None)
        if isinstance(code, str):
            return code
    cause = getattr(orig, "__cause__", None)
    code = getattr(cause, "sqlstate", None)
    return code if isinstance(code, str) else None


_VERIFY_BATCH_SQL = sa.text(
    "SELECT id, prev_hash, entry_hash, actor_user_id::text AS actor_user_id, actor_label, "
    "actor_ip::text AS actor_ip, session_id::text AS session_id, action, object_kind, "
    "object_id, outcome::text AS outcome, severity::text AS severity, reason, "
    "before_state::text AS before_state, after_state::text AS after_state, "
    "request_id::text AS request_id, env::text AS env, "
    "to_char(event_ts AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.USOF') AS event_ts "
    "FROM audit_log WHERE id > :after_id "
    "AND (CAST(:to_id AS bigint) IS NULL OR id <= CAST(:to_id AS bigint)) "
    "ORDER BY id ASC LIMIT :limit"
)

_INSERT_CHECKPOINT_SQL = sa.text("""
    INSERT INTO audit_checkpoints (id, head_id, head_hash, row_count, signed_by)
    VALUES (:id, :head_id, :head_hash, :row_count, :signed_by)
    ON CONFLICT (head_id) DO NOTHING
    """)


def _json_or_null(value: dict[str, Any] | None) -> str | None:
    """SQL NULL for an absent state — never the JSON literal `null`, which
    the chain trigger would hash as the 4-char text `null`."""
    return None if value is None else json.dumps(value, sort_keys=True)


class SqlAlchemyAuditRepository:
    """Backs `AuditWriter`/`AuditQueryService`/`checkpoint.run_checkpoint`.

    Constructed directly from a `SqlAlchemyRelationalRepository` (the same
    relational-tier client `StorageService` wires for every other module) —
    The composition root constructs it and injects it into `AuditService`.
    """

    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def insert(self, record: dict[str, Any]) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(_ADVISORY_LOCK_SQL)
            await uow.session.execute(
                _INSERT_SQL,
                {
                    "record_id": record["record_id"],
                    "actor_user_id": record.get("actor_user_id"),
                    "actor_label": record["actor_label"],
                    "actor_ip": record.get("actor_ip"),
                    "session_id": record.get("session_id"),
                    "action": record["action"],
                    "object_kind": record.get("object_kind"),
                    "object_id": record.get("object_id"),
                    "object_label": record.get("object_label"),
                    "outcome": record["outcome"],
                    "severity": record["severity"],
                    "reason": record.get("reason"),
                    "before_state": _json_or_null(record.get("before_state")),
                    "after_state": _json_or_null(record.get("after_state")),
                    "request_id": record.get("request_id"),
                    "env": record.get("env"),
                    "event_ts": datetime.fromisoformat(record["event_ts"]),
                },
            )
            await uow.commit()

    async def query_page(
        self,
        *,
        actor_user_id: str | None,
        actions: list[str] | None,
        subject_type: str | None,
        severity: str | None,
        outcome: str | None,
        from_ts: datetime | None,
        to_ts: datetime | None,
        cursor: int | None,
        limit: int,
        ip: str | None = None,
        timeout_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "actor_user_id": actor_user_id,
            "actions": actions or None,
            "subject_type": subject_type,
            "severity": severity,
            "outcome": outcome,
            "from_ts": from_ts,
            "to_ts": to_ts,
            "cursor": cursor,
            "limit": limit,
            "ip": ip,
        }
        # The budget covers the whole call, connection checkout included: a pool wait
        # would otherwise run to the pool's own 30 s timeout.
        budget = asyncio.timeout(None if timeout_ms is None else timeout_ms / 1000)
        try:
            async with budget:
                async with self._relational.unit_of_work() as uow:
                    if timeout_ms is not None:
                        # SET takes no bind parameters; set_config(..., true) is `SET LOCAL`.
                        await uow.session.execute(_SET_TIMEOUT_SQL, {"v": f"{int(timeout_ms)}ms"})
                    result = await uow.session.execute(_QUERY_PAGE_SQL, params)
                    return [dict(row._mapping) for row in result]
        except TimeoutError:
            cause = "budget"
        except sa.exc.TimeoutError:
            cause = "pool"
        except (sa.exc.SQLAlchemyError, OSError) as exc:
            state = _sqlstate(exc) if isinstance(exc, sa.exc.DBAPIError) else None
            if state != _QUERY_CANCELED and not budget.expired():
                # Class and SQLSTATE only: the exception text carries the bound filters.
                _log().warning("audit.read.failed", error=type(exc).__name__, sqlstate=state)
                raise AuditReadFailed(state) from None
            cause = "statement_timeout"
        _log().warning("audit.read.timeout", cause=cause, budget_ms=timeout_ms)
        raise TimeoutError("audit read exceeded its time budget")

    async def fetch_entry_hash(self, entry_id: int) -> str | None:
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(_ENTRY_HASH_SQL, {"id": entry_id})).first()
            return row[0] if row is not None else None

    async def fetch_verify_batch(
        self, *, after_id: int, to_id: int | None, limit: int
    ) -> list[dict[str, Any]]:
        params = {"after_id": after_id, "to_id": to_id, "limit": limit}
        async with self._relational.unit_of_work() as uow:
            result = await uow.session.execute(_VERIFY_BATCH_SQL, params)
            return [dict(row._mapping) for row in result]

    async def read_head(self) -> tuple[int, str] | None:
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(_HEAD_SQL)).first()
            return (row[0], row[1]) if row is not None else None

    async def count(self) -> int:
        async with self._relational.unit_of_work() as uow:
            return int((await uow.session.execute(_COUNT_SQL)).scalar_one())

    async def write_checkpoint(
        self, *, checkpoint_id: str, head_id: int, head_hash: str, row_count: int, signed_by: str
    ) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(
                _INSERT_CHECKPOINT_SQL,
                {
                    "id": checkpoint_id,
                    "head_id": head_id,
                    "head_hash": head_hash,
                    "row_count": row_count,
                    "signed_by": signed_by,
                },
            )
            await uow.commit()
