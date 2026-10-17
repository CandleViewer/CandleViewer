"""`AuditRepository` — the storage-facing seam `AuditWriter`/`AuditQueryService`/
`checkpoint.run_checkpoint` depend on instead of a raw SQL driver.

CONSTITUTION.md ADR-0003 forbids `candleviewer.audit` from importing a
storage driver directly (`sqlalchemy`, `asyncpg`, ...) — this Protocol is the
seam that keeps that true: the concrete implementation
(`candleviewer.storage.repositories.audit_sqlalchemy.SqlAlchemyAuditRepository`)
lives in M10 (`storage`, which *is* allowed to import `sqlalchemy`) and is
structurally compatible with this Protocol without either module importing
the other's types — the composition root injects it into `AuditService(repository=...)`;
neither module imports the other.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class AuditRepository(Protocol):
    """Everything the audit module needs from the relational tier, expressed
    without any SQL-driver type in its signatures (plain `dict`/`str`/`int`).
    """

    async def insert(self, record: dict[str, Any]) -> None:
        """Insert one audit row inside the advisory-lock-serialised
        transaction the implementation owns (ticket "Technical notes": a
        single writer must hold `pg_advisory_xact_lock` for the insert's
        duration so the chain trigger cannot race)."""
        ...

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
        """`timeout_ms` bounds the whole call, connection checkout included, and the
        statement (`statement_timeout`, transaction-local); an overrun raises the builtin
        `TimeoutError`. Any other database failure raises a storage error that carries only
        the SQLSTATE, never the bound filters. Return up to `limit` rows ordered by
        `id DESC`, most recent first, matching every supplied filter (including `subject_type`,
        the `object_kind` column)."""
        ...

    async def fetch_entry_hash(self, entry_id: int) -> str | None:
        """Return `entry_hash` for the row with this `id`, or `None`."""
        ...

    async def fetch_verify_batch(
        self, *, after_id: int, to_id: int | None, limit: int
    ) -> list[dict[str, Any]]:
        """Return up to `limit` rows with `id > after_id` (and `id <= to_id`
        when given), ordered `id ASC`, with every hashed column rendered to
        text by Postgres using the
        exact casts `audit_chain()` uses (`::text`, jsonb `::text`, and the
        trigger's `to_char(... 'YYYY-MM-DD"T"HH24:MI:SS.USOF')` for
        `event_ts`), `None` for SQL NULL."""
        ...

    async def read_head(self) -> tuple[int, str] | None:
        """Return `(id, entry_hash)` of the most recent row, or `None` if
        `audit_log` is empty."""
        ...

    async def count(self) -> int:
        """Total row count in `audit_log`."""
        ...

    async def write_checkpoint(
        self, *, checkpoint_id: str, head_id: int, head_hash: str, row_count: int, signed_by: str
    ) -> None:
        """Insert one `audit_checkpoints` row. Idempotent per `head_id`."""
        ...
