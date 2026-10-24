"""`SqlAlchemyRecorderRepository` - Postgres persistence for the recorder
tables (`recorded_symbols`, `recording_sessions`, `recording_gaps`,
`retention_policies`; migration `0011_recorder`, E16-T01).

Lives in M10 (`storage`) because only M10 may import a storage driver
(ADR-0003, `docs/plan/module-contracts.toml` `storage_driver_imports`); the
recorder module (M11) consumes it through injection. Static, parameterised
SQL only. `reason_refs` edits and the policy resolution are single statements
so the auto-record path (E16-T02) cannot lose an update to a read-modify-write
race; so are the manual-row writes (`upsert_manual`, `clear_manual`, `set_pinned`,
`set_retention`, E16-F01). Nothing here hard-deletes a row: `soft_remove` sets `removed_at`, and the
gap/session tables are append/update-only (ADR-0015 Sec.7). `clear_manual` never soft-removes
a pinned row, so its retention protection holds (ADR-0015 decisions 4 and 6).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Collection, Sequence
from datetime import datetime, timedelta
from typing import Any, Final, Literal

import sqlalchemy as sa

from candleviewer.domain.sql_names import EPOCH, ts_us_from_row
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.models import StreamKind, TimeRange
from candleviewer.storage.repositories.recorded import (
    STREAM_BY_DB_KIND,
    RecordedGap,
    RecordedQueryRejected,
)
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
    constraint_of,
    is_outage,
    query_failure,
    sqlstate_of,
)
from candleviewer.storage.retention.policy import RowReading, read_policy_row

#: Hard default retention (days) when neither a symbol nor a default policy exists.
HARD_DEFAULT_RETAIN_DAYS = 30
#: What `clear_manual` did to the active manual row: `demoted` to an auto reason, `removed`
#: (soft), or `absent` (no active manual row).
ManualCleared = Literal["demoted", "removed", "absent"]

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
# --- E16-F01 manual rows ---------------------------------------------------------------------
# A manual add makes the active (symbol, env) row manual: a new row, or the active auto row
# promoted, its `reason_refs`, `auto_added_at` and `pinned` kept. A soft-removed row is outside
# `ux_rs_symbol`, so a new row goes in beside it. No streams or depth: the column defaults of
# `0011_recorder` on insert (an integration test pins them), the row's own on promotion.
_UPSERT_MANUAL = sa.text(
    _with_cols(
        "INSERT INTO recorded_symbols (id, symbol, env, reason, streams, orderbook_depth, "
        "added_by) VALUES (CAST(:id AS uuid), :symbol, CAST(:env AS exchange_env), 'manual', "
        "COALESCE(CAST(CAST(:streams AS text[]) AS stream_kind[]), "
        "'{trades,orderbook_delta,tickers,liquidations}'), "
        "COALESCE(CAST(:depth AS smallint), 200), CAST(:added_by AS uuid)) "
        "ON CONFLICT (symbol, env) WHERE removed_at IS NULL DO UPDATE SET reason = 'manual', "
        "streams = COALESCE(CAST(CAST(:streams AS text[]) AS stream_kind[]), "
        "recorded_symbols.streams), "
        "orderbook_depth = COALESCE(CAST(:depth AS smallint), recorded_symbols.orderbook_depth), "
        "added_by = COALESCE(EXCLUDED.added_by, recorded_symbols.added_by), "
        "updated_at = now() RETURNING @C@"
    )
)
# Takes the manual reason away. A row with refs left, or pinned, becomes the auto reason they
# imply (a position over a chart; any other ref, or none, counts as a chart) with
# `auto_added_at` set, so `rs_autoshape` holds, and stays active: that keeps a pin's retention
# protection. Only an unpinned row with no ref left is soft-removed.
_CLEAR_MANUAL = sa.text(
    "UPDATE recorded_symbols SET "
    "reason = CASE WHEN reason_refs = '[]'::jsonb AND NOT pinned THEN reason "
    "WHEN reason_refs @> jsonb_build_array(jsonb_build_object('kind', 'position')) "
    "THEN 'position_open' ELSE 'chart_open' END, "
    "auto_added_at = CASE WHEN reason_refs = '[]'::jsonb AND NOT pinned THEN auto_added_at "
    "ELSE COALESCE(auto_added_at, now()) END, "
    "removed_at = CASE WHEN reason_refs = '[]'::jsonb AND NOT pinned THEN now() END, "
    "updated_at = now() "
    "WHERE symbol = :symbol AND env = CAST(:env AS exchange_env) AND removed_at IS NULL "
    "AND reason = 'manual' RETURNING removed_at IS NOT NULL AS removed"
)
_SET_PINNED = sa.text(
    "UPDATE recorded_symbols SET pinned = CAST(:pinned AS boolean), updated_at = now() "
    "WHERE id = CAST(:id AS uuid) AND removed_at IS NULL RETURNING 1"
)
_SET_RETENTION = sa.text(
    "UPDATE recorded_symbols SET retention_days = CAST(:days AS integer), updated_at = now() "
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
# `RecordingGapReader` (E26-T02): `_GAPS_IN` held to the asked streams and to the earliest
# `:limit` rows by start, `id` breaking ties; `gaps_in` stays unbounded for its own callers.
_REPLAY_GAPS = sa.text(
    "SELECT stream::text AS stream, gap_start, gap_end, cause "
    "FROM recording_gaps WHERE symbol = :symbol AND gap_start < :hi AND gap_end > :lo "
    "AND stream = ANY(CAST(:streams AS stream_kind[])) ORDER BY gap_start, id LIMIT :limit"
)
#: Storage stream -> its Postgres `stream_kind` value, for the gap read's stream filter.
_DB_KIND: Final = {stream: kind for kind, stream in STREAM_BY_DB_KIND.items()}
_EARLIEST = sa.text(
    "SELECT min(first_event_ts) AS first FROM recording_sessions WHERE symbol = :symbol"
)
# Flags only: a gap row's window is never shrunk or deleted (E16-T04 security notes).
_MARK_BACKFILLED = sa.text(
    "UPDATE recording_gaps SET backfilled = true, backfill_source = :source "
    "WHERE id = :id RETURNING 1"
)
# Pinned symbol -> infinite (NULL); else symbol-scoped; else default; else caller's hard default.
# The row's `action` comes with its `retain_days`: `read_policy_row` reads the pair.
_RESOLVE = sa.text(
    "SELECT retain_days, action FROM ("
    "SELECT NULL::integer AS retain_days, NULL::text AS action, 0 AS ord WHERE EXISTS ("
    "SELECT 1 FROM recorded_symbols WHERE symbol = :symbol AND pinned AND removed_at IS NULL) "
    "UNION ALL "
    "SELECT retain_days, action::text, CASE WHEN scope = 'symbol' THEN 1 ELSE 2 END AS ord "
    "FROM retention_policies WHERE stream = CAST(:stream AS stream_kind) AND enabled "
    "AND (scope = 'default' OR symbol = :symbol)) AS r ORDER BY ord LIMIT 1"
)


def _reading(row: dict[str, Any]) -> RowReading | None:
    """`read_policy_row` of the row `_RESOLVE` chose; `None` is its pinned sentinel (infinite)."""
    days = row["retain_days"]
    return None if days is None else read_policy_row(str(row["action"]), int(days))


class SqlAlchemyRecorderRepository:
    def __init__(self, relational: SqlAlchemyRelationalRepository) -> None:
        self._relational = relational

    async def _all(self, stmt: sa.TextClause, params: dict[str, Any]) -> list[dict[str, Any]]:
        async with self._relational.unit_of_work() as uow:
            rows = (await uow.session.execute(stmt, params)).mappings().all()
            await uow.commit()
        return [dict(r) for r in rows]

    async def _write(self, stmt: sa.TextClause, params: dict[str, Any]) -> list[dict[str, Any]]:
        """`_all` for the manual-row writes: a statement the database refused leaves as
        `StorageQueryFailed` (`StorageConstraintViolated` for a constraint), its SQLSTATE and
        constraint name only, nothing chained (C-12.6). A database that cannot answer passes as
        it is, for the caller's outage handling."""
        try:
            return await self._all(stmt, params)
        except sa.exc.DBAPIError as exc:
            if not is_outage(exc):
                raise query_failure(sqlstate_of(exc), constraint_of(exc)) from None
            passing = exc  # stripped in place by the unit of work; re-raised after the handler
        raise passing

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

    async def upsert_manual(
        self, symbol: str, added_by: str | None, streams: Sequence[str], depth: int | None, env: str
    ) -> dict[str, Any]:
        """Make the active (symbol, env) row manual (E16-F01): insert it, or promote the active
        auto row, keeping its `reason_refs`, `auto_added_at` and `pinned`. A soft-removed row is
        never resurrected. No `streams` or `depth` takes the column default on insert and keeps
        the row's on promotion; a named `added_by` replaces the row's, `None` never clears it.
        `env` has no default: a caller that forgot it would write a `live` row (#2726)."""
        params = {
            "id": str(uuid.uuid4()),
            "symbol": symbol,
            "env": env,
            "added_by": added_by,
            "streams": list(streams) or None,
            "depth": depth,
        }
        return (await self._write(_UPSERT_MANUAL, params))[0]

    async def clear_manual(self, symbol: str, env: str) -> ManualCleared:
        """Take the manual reason off the active row (E16-F01): `demoted` to the auto reason its
        refs imply, or `removed` (soft) when none is left. A pinned row is never removed here, so it
        is demoted even with no ref left and its retention protection holds; the policy's B11
        lifecycle, not this method, stops its recording. `absent`: no active manual row."""
        rows = await self._write(_CLEAR_MANUAL, {"symbol": symbol, "env": env})
        if not rows:
            return "absent"
        return "removed" if rows[0]["removed"] else "demoted"

    async def set_pinned(self, recorded_id: str, pinned: bool) -> bool:
        """Set `pinned` on the active row `recorded_id` (E16-F01). False: no active row has that
        id (it never existed, or is soft-removed); True also when it already held that value."""
        return bool(await self._write(_SET_PINNED, {"id": recorded_id, "pinned": pinned}))

    async def set_retention(self, recorded_id: str, retention_days: int | None) -> bool:
        """Set `retention_days` on the active row `recorded_id` (E16-F01); `None` is NULL, the
        default. False: no active row has that id; True also when it already held that value. A
        value `rs_retention` refuses (not 1 to 3650) leaves as `StorageConstraintViolated`."""
        params = {"id": recorded_id, "days": retention_days}
        return bool(await self._write(_SET_RETENTION, params))

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

    async def recording_gaps(
        self, symbol: str, rng: TimeRange, *, streams: Collection[StreamKind], limit: int
    ) -> list[RecordedGap]:
        """`RecordingGapReader` (E26-T02): gaps of `symbol` in `streams` intersecting `rng`, the
        earliest `limit` by start. A `limit` below 1 (or a bool) or a stream that is not
        recorded is refused before the query. A database failure is `StorageQueryFailed`,
        raised after the handler with only the SQLSTATE: the replay fails it as an unreadable
        gap table, and no driver text or chain (which may name the server) goes with it
        (24 Sec.13.7, RP-I02)."""
        if isinstance(limit, bool) or limit < 1:
            raise RecordedQueryRejected("limit must be an int >= 1")
        if any(stream not in _DB_KIND for stream in streams):
            raise RecordedQueryRejected("streams must be recorded streams")
        params = {
            "symbol": symbol,
            "lo": EPOCH + timedelta(microseconds=rng.start_us),
            "hi": EPOCH + timedelta(microseconds=rng.end_us),
            "streams": sorted(_DB_KIND[stream] for stream in streams),
            "limit": limit,
        }
        try:
            rows = await self._all(_REPLAY_GAPS, params)
        except (sa.exc.SQLAlchemyError, OSError) as exc:
            state = (
                getattr(exc.orig, "sqlstate", None) if isinstance(exc, sa.exc.DBAPIError) else None
            )
        else:
            return [
                RecordedGap(
                    symbol=symbol,
                    stream=STREAM_BY_DB_KIND[str(row["stream"])],
                    start_us=ts_us_from_row(row["gap_start"]),
                    end_us=ts_us_from_row(row["gap_end"]),
                    cause=str(row["cause"]),
                )
                for row in rows
            ]
        raise StorageQueryFailed(state if isinstance(state, str) else None)  # nothing chained

    async def earliest_first_event(self, symbol: str) -> datetime | None:
        rows = await self._all(_EARLIEST, {"symbol": symbol})
        value = rows[0]["first"] if rows else None
        return value if isinstance(value, datetime) else None

    async def mark_gap_backfilled(self, gap_id: int, source: str) -> bool:
        return bool(await self._all(_MARK_BACKFILLED, {"id": gap_id, "source": source}))

    async def resolve_policy(self, symbol: str, stream: str) -> int | None:
        """The roll-off's hot window in days for (symbol, stream); `None` is infinite (pinned)."""
        rows = await self._all(_RESOLVE, {"symbol": symbol, "stream": stream})
        if not rows:
            return HARD_DEFAULT_RETAIN_DAYS
        reading = _reading(rows[0])
        return None if reading is None else reading.hot_days

    async def policy_reading(self, symbol: str, stream: str) -> RowReading | None:
        """`read_policy_row` of the EXPLICIT rule that wins for (symbol, stream), through the
        mapping the reaper's facts use; `None` when there is none, or the symbol is pinned."""
        rows = await self._all(_RESOLVE, {"symbol": symbol, "stream": stream})
        return _reading(rows[0]) if rows else None

    async def explicit_policy_days(self, symbol: str, stream: str) -> int | None:
        """The klines boundary's hot window in days of an EXPLICIT enabled rule for (symbol,
        stream); `None` when there is none (or it is infinite), never the 30 d default."""
        reading = await self.policy_reading(symbol, stream)
        return None if reading is None else reading.hot_days
