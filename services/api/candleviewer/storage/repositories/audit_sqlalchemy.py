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
import itertools
import json
import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
import structlog
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, INET, TIMESTAMP, UUID

from candleviewer.observability.audit_query_metrics import cv_audit_query_timeouts_total
from candleviewer.settings import Settings
from candleviewer.storage.errors import AuditEntryTooLarge, StorageTierUnavailable
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


class AuditReadBusy(StorageTierUnavailable):
    """Every audit read slot is in use. The read fails closed at once (503) instead of
    queueing for the connection pool that the audit writer also uses."""

    def __init__(self) -> None:
        super().__init__("audit read capacity reached")


#: Audit page reads in flight per process (`audit_query_global_max_concurrent`); fewer than
#: the pool's 10 base connections, so reads never take the connections the writer needs.
#: One slot is kept for the Owner: other reads together hold at most `read_slots - 1`.
DEFAULT_READ_SLOTS = 4
#: Caps on what is fetched for a page's chain check. A rendering longer than
#: `CHAIN_FIELD_MAX_CHARS` is cut by Postgres, and fetching stops once a page has used
#: `CHAIN_PAGE_MAX_CHARS`; such rows get no canonical form and are never counted as verified.
CHAIN_FIELD_MAX_CHARS = 16_384
CHAIN_PAGE_MAX_CHARS = 4 * 1024 * 1024
_CHAIN_CHUNK = 50


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
#: The stored predecessor of a range starting at `:before_id` (ids have gaps).
_ANCHOR_SQL = sa.text(
    "SELECT entry_hash FROM audit_log WHERE id < :before_id ORDER BY id DESC LIMIT 1"
)
#: The first and the head id in one statement (both ends of the primary key index).
_BOUNDS_SQL = sa.text("SELECT min(id), max(id) FROM audit_log")
#: A checkpoint above `:head_id` whose entry is missing or has another hash: a truncated tail.
#: A checkpoint written after the head was read names an existing entry with its own hash.
_CHECKPOINT_ABOVE_SQL = sa.text(
    "SELECT min(c.head_id) FROM audit_checkpoints c LEFT JOIN audit_log a ON a.id = c.head_id "
    "WHERE c.head_id > :head_id AND a.entry_hash IS DISTINCT FROM c.head_hash"
)
#: Each checkpoint up to `:to_id` with the stored `entry_hash` of the id it names (NULL when
#: no entry has that id).
_CHECKPOINTS_SQL = sa.text(
    "SELECT c.head_id, c.head_hash, a.entry_hash FROM audit_checkpoints c "
    "LEFT JOIN audit_log a ON a.id = c.head_id WHERE c.head_id <= :to_id ORDER BY c.head_id"
)
#: Rendered UTF-8 bytes per verify batch: a batch stops before a row once the rows before it
#: reach this, so it holds at most the budget plus one entry (the first row always goes in),
#: and each entry is capped at `VERIFY_MAX_ENTRY_BYTES`.
VERIFY_BATCH_MAX_BYTES = 8 * 1024 * 1024
#: The `audit_verify_max_entry_bytes` default: the most rendered UTF-8 bytes one entry may
#: have for verify to fetch it. A larger entry ends a run with `AuditEntryTooLarge`.
VERIFY_MAX_ENTRY_BYTES: int = Settings.model_fields["audit_verify_max_entry_bytes"].default
#: Default per-statement budget for verify's reads (the head, the anchor, each batch),
#: client-side and as `statement_timeout`: the `audit_verify_statement_timeout_ms` default, a
#: backstop far above one keyset batch. An overrun is 503.
VERIFY_READ_TIMEOUT_MS: int = Settings.model_fields["audit_verify_statement_timeout_ms"].default

#: Every hashed column is rendered to text *by Postgres*, with exactly the
#: casts `audit_chain()` uses, so the Python verifier encodes the same bytes
#: the trigger hashed (see `_VERIFY_BATCH_SQL`).

#: The `audit_log` columns the page query reads or filters on, typed so that every bound
#: value carries its Postgres type. The enum columns are read as text: an enum type built
#: without its values would refuse them on read, and the values are owned by the schema.
_AUDIT = sa.table(
    "audit_log",
    sa.column("id", sa.BigInteger),
    sa.column("event_ts", TIMESTAMP(timezone=True)),
    sa.column("actor_user_id", UUID(as_uuid=True)),
    sa.column("actor_ip", INET),
    sa.column("action", sa.Text),
    sa.column("object_kind", sa.Text),
    sa.column("object_id", sa.Text),
    sa.column("outcome", sa.Text),
    sa.column("severity", sa.Text),
    sa.column("request_id", UUID(as_uuid=True)),
    sa.column("entry_hash", sa.Text),
    sa.column("prev_hash", sa.Text),
)
_OUTCOME = ENUM(name="audit_outcome", create_type=False)
_SEVERITY = ENUM(name="severity", create_type=False)

#: The `q` document. The full-text index planned in ADR-0025 must use this exact expression
#: (the planner matches the expression, and `'simple'` must stay a literal, not a parameter).
FTS_DOCUMENT_SQL = (
    "to_tsvector('simple', coalesce(before_state::text, '') || ' ' || "
    "coalesce(after_state::text, '') || ' ' || coalesce(object_label, ''))"
)
_FTS_DOCUMENT: sa.ColumnClause[str] = sa.literal_column(FTS_DOCUMENT_SQL)
_FTS_CONFIG: sa.ColumnClause[str] = sa.literal_column("'simple'")

_SET_TIMEOUT_SQL = sa.text(
    "SELECT set_config('statement_timeout', :v, true), "
    # One SQL text per filter shape; a custom plan per call keeps each shape's plan fitted
    # to its values (a generic plan cannot see a time window or an actor's row count).
    "set_config('plan_cache_mode', 'force_custom_plan', true)"
)

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


#: A keyset batch of at most `:limit` rows, cut once the renderings before a row reach
#: `:max_bytes` (UTF-8): the first row is always admitted, so the walk always moves on. A row
#: over `:max_entry` bytes ends the batch before it, so it only ever comes first, and then
#: without its renderings (NULL); each row carries its byte count `n` last.
_VERIFY_BATCH_SQL = sa.text(
    "SELECT w.id, w.prev_hash, w.entry_hash, f.*, w.n FROM ("
    "SELECT r.*, sum(r.n) OVER o - r.n AS before, row_number() OVER o AS k, "
    "count(*) FILTER (WHERE r.n > :max_entry) OVER o AS big FROM ("
    "SELECT q.*, octet_length(concat(actor_user_id, actor_label, actor_ip, session_id, "
    "action, object_kind, object_id, outcome, severity, reason, before_state, after_state, "
    "request_id, env, event_ts)) AS n FROM ("
    "SELECT id, prev_hash, entry_hash, actor_user_id::text AS actor_user_id, actor_label, "
    "actor_ip::text AS actor_ip, session_id::text AS session_id, action, object_kind, "
    "object_id, outcome::text AS outcome, severity::text AS severity, reason, "
    "before_state::text AS before_state, after_state::text AS after_state, "
    "request_id::text AS request_id, env::text AS env, "
    "to_char(event_ts AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.USOF') AS event_ts "
    "FROM audit_log WHERE id > :after_id AND id <= :to_id ORDER BY id ASC LIMIT :limit"
    ") q) r WINDOW o AS (ORDER BY r.id)) w LEFT JOIN LATERAL (SELECT w.actor_user_id, "
    "w.actor_label, w.actor_ip, w.session_id, w.action, w.object_kind, w.object_id, w.outcome, "
    "w.severity, w.reason, w.before_state, w.after_state, w.request_id, w.env, w.event_ts"
    ") f ON w.n <= :max_entry WHERE w.before < :max_bytes AND (w.big = 0 OR w.k = 1) "
    "ORDER BY w.id"
)

#: For given rows, by id: the renderings the trigger hashed (as `_VERIFY_BATCH_SQL`, each cut
#: at `:n` characters so a long one is never fetched whole) and the `entry_hash` of the
#: row before it in the chain (by id; none for the first).
_CHAIN_ROWS_SQL = sa.text(
    "SELECT id, left(actor_user_id::text, :n) AS actor_user_id, "
    "left(actor_label, :n) AS actor_label, left(actor_ip::text, :n) AS actor_ip, "
    "left(session_id::text, :n) AS session_id, left(action, :n) AS action, "
    "left(object_kind, :n) AS object_kind, left(object_id, :n) AS object_id, "
    "left(outcome::text, :n) AS outcome, left(severity::text, :n) AS severity, "
    "left(reason, :n) AS reason, left(before_state::text, :n) AS before_state, "
    "left(after_state::text, :n) AS after_state, left(request_id::text, :n) AS request_id, "
    "left(env::text, :n) AS env, "
    "left(to_char(event_ts AT TIME ZONE 'UTC','YYYY-MM-DD\"T\"HH24:MI:SS.USOF'), :n) AS event_ts, "
    "(SELECT p.entry_hash FROM audit_log p WHERE p.id < a.id ORDER BY p.id DESC LIMIT 1) "
    "AS chain_prev_hash FROM audit_log a WHERE id = ANY(CAST(:ids AS bigint[])) ORDER BY id DESC"
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


def _page_statement(
    *,
    restrict_to_actor: str | None,
    actor_user_id: str | None,
    actions: list[str] | None,
    subject_type: str | None,
    subject_id: str | None,
    severity: str | None,
    outcome: str | None,
    ip: str | None,
    q: str | None,
    from_ts: datetime | None,
    to_ts: datetime | None,
    after: tuple[datetime, int] | None,
    limit: int,
) -> sa.Select[Any]:
    """One statement per combination of present filters, each a bound parameter (no
    string-built SQL, Semgrep/Bandit B608), and no `IS NULL OR` placeholder, so every shape
    gets its own plan. Ordered `(event_ts DESC, id DESC)`, the order every audit index
    ends in; `after` resumes strictly after that position. A set `restrict_to_actor`
    replaces `actor_user_id`, so a narrowed caller can never widen its rows."""
    t = _AUDIT
    actor = restrict_to_actor if restrict_to_actor is not None else actor_user_id
    where: list[sa.ColumnElement[bool]] = []
    if actor is not None:
        where.append(t.c.actor_user_id == uuid.UUID(actor))
    if actions:
        where.append(t.c.action == sa.any_(sa.bindparam("actions", actions, ARRAY(sa.Text))))
    if subject_type is not None:
        where.append(t.c.object_kind == subject_type)
    if subject_id is not None:
        where.append(t.c.object_id == subject_id)
    if severity is not None:
        where.append(t.c.severity == sa.bindparam("severity", severity, _SEVERITY))
    if outcome is not None:
        where.append(t.c.outcome == sa.bindparam("outcome", outcome, _OUTCOME))
    if ip is not None:
        where.append(t.c.actor_ip == ip)
    if from_ts is not None:
        where.append(t.c.event_ts >= from_ts)
    if to_ts is not None:
        where.append(t.c.event_ts < to_ts)
    if q is not None:
        query = sa.func.websearch_to_tsquery(_FTS_CONFIG, sa.bindparam("q", q, sa.Text))
        where.append(_FTS_DOCUMENT.op("@@")(query))
    if after is not None:
        ts, last_id = after
        where += [t.c.event_ts <= ts, sa.or_(t.c.event_ts < ts, t.c.id < last_id)]
    order = (t.c.event_ts.desc(), t.c.id.desc())
    return sa.select(t).where(*where).order_by(*order).limit(limit)


_CHAIN_KEYS = frozenset({"id", "chain_prev_hash"})


async def _attach_chain(session: Any, rows: list[dict[str, Any]]) -> None:
    """Set `row["chain"]` on each row: its renderings (the keys `_canonical_hash` reads) and
    `chain_prev_hash`, fetched in chunks by id. It is `None` when the form is incomplete: a
    rendering over `CHAIN_FIELD_MAX_CHARS`, or a row past `CHAIN_PAGE_MAX_CHARS` for the page,
    where fetching stops. The caller counts an incomplete form as unverified."""
    chains: dict[int, dict[str, Any] | None] = {}
    left = CHAIN_PAGE_MAX_CHARS
    for chunk in itertools.batched(sorted((r["id"] for r in rows), reverse=True), _CHAIN_CHUNK):
        if left < 0:
            break
        # One character past what is allowed: a longer rendering leaves its row incomplete
        # whatever its length, so near the page cap the chunk is not fetched at full width.
        params = {"ids": list(chunk), "n": min(CHAIN_FIELD_MAX_CHARS, left) + 1}
        for found in await session.execute(_CHAIN_ROWS_SQL, params):
            chain = dict(found._mapping)
            texts = [v for k, v in chain.items() if k not in _CHAIN_KEYS and v is not None]
            left -= sum(len(v) for v in texts)
            complete = left >= 0 and all(len(v) <= CHAIN_FIELD_MAX_CHARS for v in texts)
            chains[chain["id"]] = chain if complete else None
    for row in rows:
        row["chain"] = chains.get(row["id"])


class SqlAlchemyAuditRepository:
    """Backs `AuditWriter`/`AuditQueryService`/`checkpoint.run_checkpoint`.

    Constructed directly from a `SqlAlchemyRelationalRepository` (the same
    relational-tier client `StorageService` wires for every other module) —
    The composition root constructs it and injects it into `AuditService`.
    """

    def __init__(
        self,
        relational: SqlAlchemyRelationalRepository,
        *,
        read_slots: int = DEFAULT_READ_SLOTS,
        verify_read_timeout_ms: int = VERIFY_READ_TIMEOUT_MS,
        verify_batch_max_bytes: int = VERIFY_BATCH_MAX_BYTES,
        verify_max_entry_bytes: int = VERIFY_MAX_ENTRY_BYTES,
    ) -> None:
        if read_slots < 2:  # the Owner's slot, and at least one for everyone else
            raise ValueError("read_slots must be at least 2")
        self._relational = relational
        self._verify_timeout_ms = verify_read_timeout_ms
        self._batch_bytes = verify_batch_max_bytes
        self._entry_bytes = verify_max_entry_bytes
        self._read_slots = read_slots
        self._reads = 0
        self._shared_reads = 0  # reads that are not the Owner's

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
        restrict_to_actor: str | None,
        actor_user_id: str | None,
        actions: list[str] | None,
        subject_type: str | None,
        subject_id: str | None,
        severity: str | None,
        outcome: str | None,
        ip: str | None,
        q: str | None,
        from_ts: datetime | None,
        to_ts: datetime | None,
        after: tuple[datetime, int] | None,
        limit: int,
        timeout_ms: int | None = None,
        owner: bool = False,
    ) -> list[dict[str, Any]]:
        statement = _page_statement(
            restrict_to_actor=restrict_to_actor,
            actor_user_id=actor_user_id,
            actions=actions,
            subject_type=subject_type,
            subject_id=subject_id,
            severity=severity,
            outcome=outcome,
            ip=ip,
            q=q,
            from_ts=from_ts,
            to_ts=to_ts,
            after=after,
            limit=limit,
        )
        # The budget covers the whole call, connection checkout included: a pool wait
        # would otherwise run to the pool's own 30 s timeout.
        budget = asyncio.timeout(None if timeout_ms is None else timeout_ms / 1000)
        cause, error, state = "", "", None
        shared = 0 if owner else 1
        if self._reads >= self._read_slots or self._shared_reads + shared >= self._read_slots:
            _log().warning("audit.read.busy", slots=self._read_slots, owner=owner)
            raise AuditReadBusy
        # Nothing runs between taking the slot and the `try` that gives it back.
        self._reads += 1
        self._shared_reads += shared
        try:
            async with budget:
                async with self._relational.unit_of_work() as uow:
                    if timeout_ms is not None:
                        # SET takes no bind parameters; set_config(..., true) is `SET LOCAL`.
                        await uow.session.execute(_SET_TIMEOUT_SQL, {"v": f"{int(timeout_ms)}ms"})
                    result = await uow.session.execute(statement)
                    rows = [dict(row._mapping) for row in result]
                    await _attach_chain(uow.session, rows)
                    return rows
        except TimeoutError:
            cause = "budget"
        except sa.exc.TimeoutError:
            cause = "pool"
        except (sa.exc.SQLAlchemyError, OSError) as exc:
            state = _sqlstate(exc) if isinstance(exc, sa.exc.DBAPIError) else None
            if state == _QUERY_CANCELED or budget.expired():
                cause = "statement_timeout"
            error = type(exc).__name__
        finally:
            self._reads -= 1
            self._shared_reads -= shared
        # Raised after the handlers and `from None`: the database error, whose text carries
        # the statement and the bound filters, stays in no exception chain (C-12.6). The log
        # lines carry the cause, or the class and SQLSTATE, only.
        if cause:
            _log().warning("audit.read.timeout", cause=cause, budget_ms=timeout_ms)
            cv_audit_query_timeouts_total.labels(cause).inc()
            raise TimeoutError("audit read exceeded its time budget") from None
        _log().warning("audit.read.failed", error=error, sqlstate=state)
        raise AuditReadFailed(state) from None

    async def fetch_entry_hash(self, entry_id: int) -> str | None:
        async with self._relational.unit_of_work() as uow:
            row = (await uow.session.execute(_ENTRY_HASH_SQL, {"id": entry_id})).first()
            return row[0] if row is not None else None

    async def fetch_anchor_hash(self, before_id: int) -> str | None:
        rows = await self._bounded_read(_ANCHOR_SQL, {"before_id": before_id})
        return str(rows[0][0]) if rows else None

    async def fetch_verify_batch(
        self, *, after_id: int, to_id: int, limit: int
    ) -> list[tuple[Any, ...]]:
        params = {"after_id": after_id, "to_id": to_id, "limit": limit}
        params.update(max_bytes=self._batch_bytes, max_entry=self._entry_bytes)
        rows = await self._bounded_read(_VERIFY_BATCH_SQL, params)
        big = next((row[0] for row in rows if row[-1] > self._entry_bytes), None)
        if big is not None:  # only ever the first row, its renderings never fetched
            raise AuditEntryTooLarge(int(big))
        return [row[:-1] for row in rows]

    async def read_head(self) -> tuple[int, str] | None:
        rows = await self._bounded_read(_HEAD_SQL, {})
        return (int(rows[0][0]), str(rows[0][1])) if rows else None

    async def read_bounds(self) -> tuple[int, int] | None:
        [(first, head)] = await self._bounded_read(_BOUNDS_SQL, {})
        return None if head is None else (int(first), int(head))

    async def fetch_checkpoints(self, to_id: int) -> list[tuple[int, str, str | None]]:
        rows = await self._bounded_read(_CHECKPOINTS_SQL, {"to_id": to_id})
        return [(int(h), str(hh), None if e is None else str(e)) for h, hh, e in rows]

    async def fetch_checkpoint_above(self, head_id: int) -> int | None:
        [(above,)] = await self._bounded_read(_CHECKPOINT_ABOVE_SQL, {"head_id": head_id})
        return None if above is None else int(above)

    async def _bounded_read(
        self, statement: sa.TextClause, params: dict[str, Any]
    ) -> list[tuple[Any, ...]]:
        """One read under the verify statement budget, rows as plain tuples. Failures as in
        `query_page`: the builtin `TimeoutError`, or `AuditReadFailed` with the SQLSTATE
        only, raised `from None` so no database error rides along (C-12.6)."""
        budget = asyncio.timeout(self._verify_timeout_ms / 1000)
        timed_out, error, state = False, "", None
        try:
            async with budget:
                async with self._relational.unit_of_work() as uow:
                    limit = {"v": f"{int(self._verify_timeout_ms)}ms"}
                    await uow.session.execute(_SET_TIMEOUT_SQL, limit)
                    return [tuple(row) for row in await uow.session.execute(statement, params)]
        except (TimeoutError, sa.exc.TimeoutError):
            timed_out = True
        except (sa.exc.SQLAlchemyError, OSError) as exc:
            state = _sqlstate(exc) if isinstance(exc, sa.exc.DBAPIError) else None
            timed_out = state == _QUERY_CANCELED or budget.expired()
            error = type(exc).__name__
        if timed_out:
            _log().warning("audit.verify_read.timeout", budget_ms=self._verify_timeout_ms)
            raise TimeoutError("audit read exceeded its time budget") from None
        _log().warning("audit.verify_read.failed", error=error, sqlstate=state)
        raise AuditReadFailed(state) from None

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
