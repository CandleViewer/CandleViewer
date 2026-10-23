"""`SqlAlchemyRecordingReads` (E16-T08, #492): a page of `recorded_symbols` rows, removed ones
hidden, each with its latest session's state and start; one such row by id; a page of sessions,
newest first, with gap counts. Every read is held to the environment the caller takes from
settings (C-2.11, #2726), never a `live` default. Keyset pages; static, parameterised SQL. M10
returns rows; `recorder.control` maps them."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

#: Literal SQL only (no concatenation): `_PAGE` and `_ONE` repeat the column list, the JOIN and
#: the env/removed prefix; a unit test pins both copies to one tuple of column expressions.
#: `:hidden`: the reasons whose rows (and their sessions) a restricted view leaves out.
_PAGE: Final = sa.text(
    "SELECT rs.id::text AS id, rs.symbol::text AS symbol, rs.reason::text AS reason, rs.pinned, "
    "rs.streams::text[] AS streams, rs.orderbook_depth AS depth, rs.retention_days, "
    "rs.added_by::text AS added_by, ls.state AS session_state, "
    "ls.started_at AS session_started_at FROM recorded_symbols rs LEFT JOIN LATERAL ("
    "SELECT s.state::text AS state, s.started_at FROM recording_sessions s "
    "WHERE s.symbol = rs.symbol AND s.recorded_symbol_id = rs.id "
    "ORDER BY s.started_at DESC, s.id DESC LIMIT 1) ls ON true "
    "WHERE rs.env = CAST(:env AS exchange_env) AND rs.removed_at IS NULL "
    "AND rs.reason::text <> ALL(CAST(:hidden AS text[])) "
    "AND (CAST(:state AS text) IS NULL OR COALESCE(ls.state, 'idle') = CAST(:state AS text)) "
    "AND (CAST(:reason AS text) IS NULL OR rs.reason::text = CAST(:reason AS text)) "
    "AND (CAST(:pinned AS boolean) IS NULL OR rs.pinned = CAST(:pinned AS boolean)) "
    "AND (CAST(:a_key AS text) IS NULL OR (rs.symbol::text, rs.id) > "
    "(CAST(:a_key AS text), CAST(:a_id AS uuid))) ORDER BY rs.symbol::text, rs.id LIMIT :limit"
)
_ONE: Final = sa.text(
    "SELECT rs.id::text AS id, rs.symbol::text AS symbol, rs.reason::text AS reason, rs.pinned, "
    "rs.streams::text[] AS streams, rs.orderbook_depth AS depth, rs.retention_days, "
    "rs.added_by::text AS added_by, ls.state AS session_state, "
    "ls.started_at AS session_started_at FROM recorded_symbols rs LEFT JOIN LATERAL ("
    "SELECT s.state::text AS state, s.started_at FROM recording_sessions s "
    "WHERE s.symbol = rs.symbol AND s.recorded_symbol_id = rs.id "
    "ORDER BY s.started_at DESC, s.id DESC LIMIT 1) ls ON true "
    "WHERE rs.env = CAST(:env AS exchange_env) AND rs.removed_at IS NULL "
    "AND rs.id = CAST(:id AS uuid)"
)
_SESSIONS: Final = sa.text(
    "SELECT s.id::text AS id, s.recorded_symbol_id::text AS recorded_symbol_id, "
    "s.symbol::text AS symbol, s.state::text AS state, s.started_at, s.ended_at, "
    "s.streams::text[] AS streams, s.orderbook_depth AS depth, s.messages_received, "
    "s.bytes_written, (SELECT count(*) FROM recording_gaps g WHERE g.symbol = s.symbol "
    "AND g.recording_session_id = s.id) AS gap_count FROM recording_sessions s "
    "JOIN recorded_symbols rs ON rs.id = s.recorded_symbol_id "
    "WHERE rs.env = CAST(:env AS exchange_env) "
    "AND rs.reason::text <> ALL(CAST(:hidden AS text[])) "
    "AND (CAST(:symbol AS text) IS NULL OR s.symbol::text = CAST(:symbol AS text)) "
    "AND (CAST(:since AS timestamptz) IS NULL OR s.ended_at IS NULL "
    "OR s.ended_at > CAST(:since AS timestamptz)) "
    "AND (CAST(:until AS timestamptz) IS NULL OR s.started_at < CAST(:until AS timestamptz)) "
    "AND (CAST(:a_key AS timestamptz) IS NULL OR (s.started_at, s.id) < "
    "(CAST(:a_key AS timestamptz), CAST(:a_id AS uuid))) "
    "ORDER BY s.started_at DESC, s.id DESC LIMIT :limit"
)


class SqlAlchemyRecordingReads:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def _rows(self, stmt: sa.TextClause, params: dict[str, Any]) -> list[dict[str, Any]]:
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(stmt, params)).mappings().all()
            await uow.commit()
        return [dict(r) for r in rows]

    async def recorded_page(
        self, *, env: str, state: str | None, reason: str | None, pinned: bool | None,
        hidden: tuple[str, ...], after: tuple[str, str] | None, limit: int,
    ) -> list[dict[str, Any]]:  # fmt: skip
        """Up to `limit` rows after `after`, a `(symbol, id)` key, in that order."""
        key, last = after or (None, None)
        return await self._rows(_PAGE, {
            "env": env, "state": state, "reason": reason, "pinned": pinned,
            "hidden": list(hidden), "a_key": key, "a_id": last, "limit": limit,
        })  # fmt: skip

    async def recorded_row(self, entry_id: str, *, env: str) -> dict[str, Any] | None:
        rows = await self._rows(_ONE, {"env": env, "id": entry_id})
        return rows[0] if rows else None

    async def sessions_page(
        self, *, env: str, symbol: str | None, since: datetime | None, until: datetime | None,
        hidden: tuple[str, ...], after: tuple[datetime, str] | None, limit: int,
    ) -> list[dict[str, Any]]:  # fmt: skip
        """Up to `limit` sessions overlapping `[since, until)`, newest first, after `after`, a
        `(started_at, id)` key; `gap_count` counts each one's gap rows."""
        key, last = after or (None, None)
        return await self._rows(_SESSIONS, {
            "env": env, "symbol": symbol, "since": since, "until": until,
            "hidden": list(hidden), "a_key": key, "a_id": last, "limit": limit,
        })  # fmt: skip
