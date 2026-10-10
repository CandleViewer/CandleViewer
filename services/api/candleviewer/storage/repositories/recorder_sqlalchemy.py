"""`SqlAlchemyRecorderRepository` - Postgres persistence for the recorder
tables (`recorded_symbols`, `recording_sessions`, `recording_gaps`,
`retention_policies`; migration `0011_recorder`, E16-T01).

Lives in M10 (`storage`) because only M10 may import a storage driver
(ADR-0003, `docs/plan/module-contracts.toml` `storage_driver_imports`); the
recorder module (M11) consumes it through injection. Static, parameterised
SQL only. `reason_refs` edits and the policy resolution are single statements
so the auto-record path (E16-T02) cannot lose an update to a read-modify-write
race. Nothing here hard-deletes a row: `soft_remove` sets `removed_at`, and the
gap/session tables are append/update-only (ADR-0015 Sec.7).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa

from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

#: Hard default retention (days) when neither a symbol nor a default policy exists.
HARD_DEFAULT_RETAIN_DAYS = 30

_RS_COLS = (
    "id::text AS id, symbol::text AS symbol, env::text AS env, reason::text AS reason, "
    "reason_refs, streams::text[] AS streams, orderbook_depth, pinned, retention_days, "
    "priority, added_by::text AS added_by, auto_added_at, created_at, removed_at"
)


def _with_cols(sql: str) -> str:
    """Splice the constant column list into a SELECT template."""
    return sql.replace("@C@", _RS_COLS)


_LIST = sa.text(
    _with_cols(
        "SELECT @C@ FROM recorded_symbols WHERE env = CAST(:env AS exchange_env) "
        "AND removed_at IS NULL ORDER BY priority, symbol"
    )
)
_GET = sa.text(
    _with_cols(
        "SELECT @C@ FROM recorded_symbols WHERE symbol = :symbol "
        "AND env = CAST(:env AS exchange_env) AND removed_at IS NULL"
    )
)
_UPSERT_AUTO = sa.text(
    "INSERT INTO recorded_symbols (id, symbol, env, reason, reason_refs, auto_added_at) "
    "VALUES (CAST(:id AS uuid), :symbol, CAST(:env AS exchange_env), "
    "CAST(:reason AS record_reason), jsonb_build_array(CAST(:ref AS jsonb)), now()) "
    "ON CONFLICT (symbol, env) WHERE removed_at IS NULL DO UPDATE SET "
    "reason_refs = CASE WHEN recorded_symbols.reason_refs "
    "@> jsonb_build_array(CAST(:ref AS jsonb)) "
    "THEN recorded_symbols.reason_refs "
    "ELSE recorded_symbols.reason_refs || jsonb_build_array(CAST(:ref AS jsonb)) END, "
    "updated_at = now() RETURNING id::text"
)
_ADD_REF = sa.text(
    "UPDATE recorded_symbols SET "
    "reason_refs = CASE WHEN reason_refs @> jsonb_build_array(CAST(:ref AS jsonb)) "
    "THEN reason_refs ELSE reason_refs || jsonb_build_array(CAST(:ref AS jsonb)) END, "
    "updated_at = now() WHERE id = CAST(:id AS uuid) AND removed_at IS NULL RETURNING 1"
)
_REMOVE_REF = sa.text(
    "UPDATE recorded_symbols SET reason_refs = COALESCE((SELECT jsonb_agg(e) "
    "FROM jsonb_array_elements(reason_refs) AS e WHERE e <> CAST(:ref AS jsonb)), "
    "'[]'::jsonb), updated_at = now() WHERE id = CAST(:id AS uuid) "
    "AND removed_at IS NULL RETURNING 1"
)
_SOFT_REMOVE = sa.text(
    "UPDATE recorded_symbols SET removed_at = now(), updated_at = now() "
    "WHERE id = CAST(:id AS uuid) AND removed_at IS NULL RETURNING 1"
)
_OPEN_SESSION = sa.text(
    "INSERT INTO recording_sessions (id, recorded_symbol_id, symbol, streams, "
    "orderbook_depth, ws_endpoint) VALUES (CAST(:id AS uuid), CAST(:rsid AS uuid), :symbol, "
    "CAST(CAST(:streams AS text[]) AS stream_kind[]), :depth, :ws)"
)
_OPEN_SESSION_AT = sa.text(
    "INSERT INTO recording_sessions (id, recorded_symbol_id, symbol, streams, "
    "orderbook_depth, ws_endpoint, started_at) VALUES (CAST(:id AS uuid), CAST(:rsid AS uuid), "
    ":symbol, CAST(CAST(:streams AS text[]) AS stream_kind[]), :depth, :ws, :started)"
)
_CLOSE_SESSION = sa.text(
    "UPDATE recording_sessions SET ended_at = now(), "
    "state = CAST(CASE WHEN :reason = 'error' THEN 'error' ELSE 'stopped' END AS recording_state), "
    "end_reason = :reason WHERE id = CAST(:id AS uuid) AND ended_at IS NULL RETURNING 1"
)
_RECORD_GAP = sa.text(
    "INSERT INTO recording_gaps (recording_session_id, symbol, stream, gap_start, gap_end, "
    "cause) VALUES (CAST(:sid AS uuid), :symbol, CAST(:stream AS stream_kind), :gs, :ge, "
    ":cause) RETURNING id"
)
# E16-T03 StreamWriter: both target the symbol's live session (ix_recs_live), newest first.
_ADD_COUNTERS = sa.text(
    "UPDATE recording_sessions SET messages_received = messages_received + :rx, "
    "messages_dropped = messages_dropped + :dropped, bytes_written = bytes_written + :bytes, "
    "reconnect_count = reconnect_count + :reconnects WHERE id = "
    "(SELECT id FROM recording_sessions WHERE symbol = :symbol "
    "AND state IN ('starting','recording','degraded') ORDER BY started_at DESC LIMIT 1)"
    " RETURNING 1"
)
_RECORD_LIVE_GAP = sa.text(
    "INSERT INTO recording_gaps (recording_session_id, symbol, stream, gap_start, gap_end, "
    "cause) SELECT s.id, :symbol, CAST(:stream AS stream_kind), :gs, :ge, :cause FROM "
    "(SELECT id FROM recording_sessions WHERE symbol = :symbol "
    "AND state IN ('starting','recording','degraded') ORDER BY started_at DESC LIMIT 1)"
    " AS s RETURNING id"
)
# --- E16-T04 sessions / gaps / coverage ------------------------------------------------------
_LIVE_SESSIONS = sa.text(
    "SELECT id::text AS id, symbol::text AS symbol, state::text AS state, "
    "streams::text[] AS streams, started_at, ended_at, first_event_ts, last_event_ts, "
    "end_reason FROM recording_sessions "
    "WHERE state IN ('starting','recording','degraded','stopping') ORDER BY started_at"
)
_CLOSE_SESSION_AT = sa.text(
    "UPDATE recording_sessions SET ended_at = GREATEST(started_at, :ended), "
    "state = CAST(:state AS recording_state), end_reason = :reason "
    "WHERE id = CAST(:id AS uuid) AND ended_at IS NULL RETURNING 1"
)
_SET_STATE = sa.text(
    "UPDATE recording_sessions SET state = CAST(:state AS recording_state) "
    "WHERE id = CAST(:id AS uuid) AND ended_at IS NULL RETURNING 1"
)
_TOUCH_EVENTS = sa.text(
    "UPDATE recording_sessions SET first_event_ts = COALESCE(first_event_ts, :first), "
    "last_event_ts = GREATEST(COALESCE(last_event_ts, :last), :last) "
    "WHERE id = CAST(:id AS uuid) RETURNING 1"
)
_SESSIONS_IN = sa.text(
    "SELECT id::text AS id, symbol::text AS symbol, state::text AS state, "
    "streams::text[] AS streams, started_at, ended_at, first_event_ts, last_event_ts, "
    "end_reason FROM recording_sessions WHERE symbol = :symbol "
    "AND started_at < :hi AND (ended_at IS NULL OR ended_at > :lo) ORDER BY started_at"
)
_GAPS_IN = sa.text(
    "SELECT id, stream::text AS stream, gap_start, gap_end, cause, backfilled, backfill_source "
    "FROM recording_gaps WHERE symbol = :symbol AND gap_start < :hi AND gap_end > :lo "
    "ORDER BY gap_start"
)
_EARLIEST = sa.text(
    "SELECT min(first_event_ts) AS first FROM recording_sessions WHERE symbol = :symbol"
)
# Flags only: a gap row's window is never shrunk or deleted (E16-T04 security notes).
_MARK_BACKFILLED = sa.text(
    "UPDATE recording_gaps SET backfilled = true, backfill_source = :source "
    "WHERE id = :id RETURNING 1"
)
# Pinned symbol -> infinite (NULL); else symbol-scoped; else default; else caller's hard default.
_RESOLVE = sa.text(
    "SELECT retain_days FROM ("
    "SELECT NULL::integer AS retain_days, 0 AS ord WHERE EXISTS ("
    "SELECT 1 FROM recorded_symbols WHERE symbol = :symbol AND pinned AND removed_at IS NULL) "
    "UNION ALL "
    "SELECT retain_days, CASE WHEN scope = 'symbol' THEN 1 ELSE 2 END AS ord "
    "FROM retention_policies WHERE stream = CAST(:stream AS stream_kind) AND enabled "
    "AND (scope = 'default' OR symbol = :symbol)) AS r ORDER BY ord LIMIT 1"
)


class SqlAlchemyRecorderRepository:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def _all(self, stmt: sa.TextClause, params: dict[str, Any]) -> list[dict[str, Any]]:
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(stmt, params)).mappings().all()
            await uow.commit()
        return [dict(r) for r in rows]

    async def list_recorded(self, env: str = "live") -> list[dict[str, Any]]:
        return await self._all(_LIST, {"env": env})

    async def get_by_symbol(self, symbol: str, env: str = "live") -> dict[str, Any] | None:
        rows = await self._all(_GET, {"symbol": symbol, "env": env})
        return rows[0] if rows else None

    async def upsert_auto(
        self, symbol: str, reason: str, ref: dict[str, str], env: str = "live"
    ) -> str:
        """Insert an auto-record row, or append `ref` to the active row's reasons."""
        rows = await self._all(
            _UPSERT_AUTO,
            {
                "id": str(uuid.uuid4()),
                "symbol": symbol,
                "env": env,
                "reason": reason,
                "ref": json.dumps(ref, sort_keys=True),
            },
        )
        return str(rows[0]["id"])

    async def add_reason_ref(self, recorded_id: str, ref: dict[str, str]) -> bool:
        rows = await self._all(_ADD_REF, {"id": recorded_id, "ref": json.dumps(ref)})
        return bool(rows)

    async def remove_reason_ref(self, recorded_id: str, ref: dict[str, str]) -> bool:
        rows = await self._all(_REMOVE_REF, {"id": recorded_id, "ref": json.dumps(ref)})
        return bool(rows)

    async def soft_remove(self, recorded_id: str) -> bool:
        return bool(await self._all(_SOFT_REMOVE, {"id": recorded_id}))

    async def open_session(
        self,
        *,
        recorded_symbol_id: str,
        symbol: str,
        streams: Sequence[str],
        orderbook_depth: int,
        ws_endpoint: str,
    ) -> str:
        session_id = str(uuid.uuid4())
        await self._exec(
            _OPEN_SESSION,
            {
                "id": session_id,
                "rsid": recorded_symbol_id,
                "symbol": symbol,
                "streams": list(streams),
                "depth": orderbook_depth,
                "ws": ws_endpoint,
            },
        )
        return session_id

    async def _exec(self, stmt: sa.TextClause, params: dict[str, Any]) -> None:
        async with self._relational.unit_of_work() as uow:
            await uow.session.execute(stmt, params)
            await uow.commit()

    async def close_session(self, session_id: str, reason: str) -> bool:
        return bool(await self._all(_CLOSE_SESSION, {"id": session_id, "reason": reason}))

    async def record_gap(
        self,
        *,
        session_id: str,
        symbol: str,
        stream: str,
        gap_start: datetime,
        gap_end: datetime,
        cause: str,
    ) -> int:
        rows = await self._all(
            _RECORD_GAP,
            {
                "sid": session_id,
                "symbol": symbol,
                "stream": stream,
                "gs": gap_start,
                "ge": gap_end,
                "cause": cause,
            },
        )
        return int(rows[0]["id"])

    async def add_session_counters(
        self,
        symbol: str,
        *,
        messages_received: int,
        messages_dropped: int,
        bytes_written: int,
        reconnect_count: int,
    ) -> bool:
        """Add counter deltas to the symbol's live session (E16-T03). False = no live session."""
        params = {
            "symbol": symbol,
            "rx": messages_received,
            "dropped": messages_dropped,
            "bytes": bytes_written,
            "reconnects": reconnect_count,
        }
        return bool(await self._all(_ADD_COUNTERS, params))

    async def record_live_gap(
        self, *, symbol: str, stream: str, gap_start: datetime, gap_end: datetime, cause: str
    ) -> bool:
        """Insert a gap on the symbol's live session (E16-T03). False = no live session."""
        params = {
            "symbol": symbol,
            "stream": stream,
            "gs": gap_start,
            "ge": gap_end,
            "cause": cause,
        }
        return bool(await self._all(_RECORD_LIVE_GAP, params))

    # --- E16-T04 ------------------------------------------------------------------------------

    async def list_live_sessions(self) -> list[dict[str, Any]]:
        """Sessions not yet closed (`starting|recording|degraded|stopping`), oldest first."""
        return await self._all(_LIVE_SESSIONS, {})

    async def open_session_at(
        self,
        *,
        recorded_symbol_id: str,
        symbol: str,
        streams: Sequence[str],
        orderbook_depth: int,
        ws_endpoint: str,
        started_at: datetime,
    ) -> str:
        """`open_session` with the caller's (injected-clock) `started_at`."""
        session_id = str(uuid.uuid4())
        await self._exec(
            _OPEN_SESSION_AT,
            {
                "id": session_id,
                "rsid": recorded_symbol_id,
                "symbol": symbol,
                "streams": list(streams),
                "depth": orderbook_depth,
                "ws": ws_endpoint,
                "started": started_at,
            },
        )
        return session_id

    async def close_session_at(
        self, session_id: str, *, reason: str, ended_at: datetime, error: bool = False
    ) -> bool:
        """Close with an explicit `ended_at` (clamped to `started_at`) and `end_reason`."""
        params = {
            "id": session_id,
            "ended": ended_at,
            "reason": reason,
            "state": "error" if error else "stopped",
        }
        return bool(await self._all(_CLOSE_SESSION_AT, params))

    async def set_session_state(self, session_id: str, state: str) -> bool:
        return bool(await self._all(_SET_STATE, {"id": session_id, "state": state}))

    async def touch_session_events(
        self, session_id: str, *, first: datetime, last: datetime
    ) -> bool:
        params = {"id": session_id, "first": first, "last": last}
        return bool(await self._all(_TOUCH_EVENTS, params))

    async def sessions_in(self, symbol: str, lo: datetime, hi: datetime) -> list[dict[str, Any]]:
        return await self._all(_SESSIONS_IN, {"symbol": symbol, "lo": lo, "hi": hi})

    async def gaps_in(self, symbol: str, lo: datetime, hi: datetime) -> list[dict[str, Any]]:
        return await self._all(_GAPS_IN, {"symbol": symbol, "lo": lo, "hi": hi})

    async def earliest_first_event(self, symbol: str) -> datetime | None:
        rows = await self._all(_EARLIEST, {"symbol": symbol})
        value = rows[0]["first"] if rows else None
        return value if isinstance(value, datetime) else None

    async def mark_gap_backfilled(self, gap_id: int, source: str) -> bool:
        return bool(await self._all(_MARK_BACKFILLED, {"id": gap_id, "source": source}))

    async def resolve_policy(self, symbol: str, stream: str) -> int | None:
        """Retention days for (symbol, stream); `None` is the infinite sentinel (pinned)."""
        rows = await self._all(_RESOLVE, {"symbol": symbol, "stream": stream})
        return HARD_DEFAULT_RETAIN_DAYS if not rows else rows[0]["retain_days"]

    async def explicit_policy_days(self, symbol: str, stream: str) -> int | None:
        """Days of an EXPLICIT enabled rule for (symbol, stream); `None` when no rule exists (or
        the rule is infinite) — unlike `resolve_policy`, never the 30 d repository default."""
        rows = await self._all(_RESOLVE, {"symbol": symbol, "stream": stream})
        return None if not rows else rows[0]["retain_days"]
