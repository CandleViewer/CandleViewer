"""In-memory `recording_sessions` / `recording_gaps` fake for E16-T04 tests (no I/O).

Mirrors the SQL semantics of `SqlAlchemyRecorderRepository` that the session, coverage and
integrity code relies on: live = `ended_at IS NULL`, `record_live_gap` targets the newest
live session of its env, windows intersect half-open, gaps are never deleted. A session's env is
its recorded row's, as in SQL; the env arguments have no default (C-2.11, #2726).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from candleviewer.recorder.sessions import SessionConfig, to_us

#: The explicit config a `SessionManager` takes: it has no default env.
LIVE, DEMO = SessionConfig(env="live"), SessionConfig(env="demo")


class MemRecorderStore:
    def __init__(self) -> None:
        self.recorded: dict[tuple[str, str], str] = {}  # (symbol, env) -> the row's id
        self.refs: dict[str, dict[str, str]] = {}  # the ref each `upsert_auto` named
        self.sessions: dict[str, dict[str, Any]] = {}
        self.gaps: list[dict[str, Any]] = []
        self.fail = False

    async def get_by_symbol(self, symbol: str, env: str) -> dict[str, Any] | None:
        rid = self.recorded.get((symbol, env))
        return None if rid is None else {"id": rid, "symbol": symbol}

    async def upsert_auto(self, symbol: str, reason: str, ref: dict[str, str], env: str) -> str:
        self.refs[symbol] = ref
        return self.recorded.setdefault((symbol, env), str(uuid.uuid4()))

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
        if self.fail:
            raise OSError("pg down")
        sid = str(uuid.uuid4())
        env = next((e for (_, e), rid in self.recorded.items() if rid == recorded_symbol_id), None)
        self.sessions[sid] = {
            "id": sid,
            "env": env,  # the row's: a session on an unknown row belongs to no env
            "symbol": symbol,
            "state": "starting",
            "streams": list(streams),
            "started_at": started_at,
            "ended_at": None,
            "first_event_ts": None,
            "last_event_ts": None,
            "end_reason": None,
        }
        return sid

    async def close_session_at(
        self, session_id: str, *, reason: str, ended_at: datetime, error: bool = False
    ) -> bool:
        s = self.sessions.get(session_id)
        if s is None or s["ended_at"] is not None:
            return False
        s["ended_at"] = max(ended_at, s["started_at"])
        s["state"] = "error" if error else "stopped"
        s["end_reason"] = reason
        return True

    async def set_session_state(self, session_id: str, state: str) -> bool:
        s = self.sessions.get(session_id)
        if s is None or s["ended_at"] is not None:
            return False
        s["state"] = state
        return True

    async def touch_session_events(
        self, session_id: str, *, first: datetime, last: datetime
    ) -> bool:
        s = self.sessions[session_id]
        s["first_event_ts"] = s["first_event_ts"] or first
        s["last_event_ts"] = max(s["last_event_ts"] or last, last)
        return True

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
        assert gap_end > gap_start, "rg_window CHECK"
        assert session_id in self.sessions
        gid = len(self.gaps) + 1
        self.gaps.append(
            {
                "id": gid,
                "session_id": session_id,
                "symbol": symbol,
                "stream": stream,
                "gap_start": gap_start,
                "gap_end": gap_end,
                "cause": cause,
                "backfilled": False,
                "backfill_source": None,
            }
        )
        return gid

    def _open(self, env: str) -> list[dict[str, Any]]:
        return [s for s in self.sessions.values() if s["ended_at"] is None and s.get("env") == env]

    def _live(self, symbol: str, env: str) -> dict[str, Any] | None:
        live = [s for s in self._open(env) if s["symbol"] == symbol]
        return max(live, key=lambda s: s["started_at"]) if live else None

    async def record_live_gap(self, *, symbol: str, env: str, **gap: Any) -> bool:
        live = self._live(symbol, env)  # `gap`: stream, gap_start, gap_end and cause
        if live is None:
            return False
        await self.record_gap(session_id=live["id"], symbol=symbol, **gap)
        return True

    async def add_session_counters(self, symbol: str, *, env: str, **kw: int) -> bool:
        return self._live(symbol, env) is not None

    async def list_live_sessions(self, env: str) -> list[dict[str, Any]]:
        return sorted((dict(s) for s in self._open(env)), key=lambda s: s["started_at"])

    async def sessions_in(self, symbol: str, lo: datetime, hi: datetime) -> list[dict[str, Any]]:
        return [
            dict(s)
            for s in self.sessions.values()
            if s["symbol"] == symbol
            and s["started_at"] < hi
            and (s["ended_at"] is None or s["ended_at"] > lo)
        ]

    async def gaps_in(self, symbol: str, lo: datetime, hi: datetime) -> list[dict[str, Any]]:
        return [
            dict(g)
            for g in self.gaps
            if g["symbol"] == symbol and g["gap_start"] < hi and g["gap_end"] > lo
        ]

    async def earliest_first_event(self, symbol: str) -> datetime | None:
        firsts = [
            s["first_event_ts"]
            for s in self.sessions.values()
            if s["symbol"] == symbol and s["first_event_ts"] is not None
        ]
        return min(firsts) if firsts else None

    async def mark_gap_backfilled(self, gap_id: int, source: str) -> bool:
        for g in self.gaps:
            if g["id"] == gap_id:
                g["backfilled"], g["backfill_source"] = True, source
                return True
        return False

    def gap_windows(self, cause: str | None = None) -> list[tuple[str, int, int, str]]:
        return [
            (g["stream"], to_us(g["gap_start"]), to_us(g["gap_end"]), g["cause"])
            for g in self.gaps
            if cause is None or g["cause"] == cause
        ]


class UsClock:
    def __init__(self, t: int) -> None:
        self.t = t

    def __call__(self) -> int:
        return self.t

    def advance_s(self, s: float) -> None:
        self.t += int(s * 1_000_000)
