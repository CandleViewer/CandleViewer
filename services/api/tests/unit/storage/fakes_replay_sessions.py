"""In-memory `ReplaySessionRepository` for service tests (E26-T01 slice 2/3). No database.

Same ordering, keyset cursor, owner scoping, compare-and-set, terminal-row and constraint
semantics as `SqlAlchemyReplaySessionRepository`: `replay_sessions_contract.py` runs one
behavioural suite against both, so the fake cannot drift from Postgres unnoticed. Time comes from
the injected clock (a settable `FakeClock` by default): no sleeps, no wall clock.
"""

from __future__ import annotations

import dataclasses
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from candleviewer.storage.repositories.replay_sessions import (
    LIVE_STATES,
    TERMINAL_STATES,
    IdleReplaySession,
    ReplaySessionConstraintError,
    ReplaySessionCreate,
    ReplaySessionIllegalUpdateError,
    ReplaySessionNotFoundError,
    ReplaySessionPage,
    ReplaySessionRow,
    ReplayState,
    SourceTier,
    clamp_limit,
    decode_cursor,
    encode_cursor,
    require_aware,
    require_counters,
    state_columns,
)

_CENT = Decimal("0.01")
_SYMBOL_CODE = re.compile(r"[A-Z0-9]{4,20}")  # the shared `symbol_code` domain CHECK
_SPEED_MIN, _SPEED_MAX = Decimal("0.1"), Decimal(100)
_NUMERIC_6_2_LIMIT = Decimal(10_000)


class FakeClock:
    """Settable UTC clock shared by a repository and its test."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 10, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> datetime:
        self.now += timedelta(**delta)
        return self.now


def _canon(value: str) -> str | None:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def _numeric_6_2(speed: Decimal) -> Decimal:
    """What a `numeric(6,2)` column stores (half-up), or `rps_speed` when it cannot hold it."""
    if not speed.is_finite() or abs(speed) >= _NUMERIC_6_2_LIMIT:
        raise ReplaySessionConstraintError("rps_speed")
    return speed.quantize(_CENT, rounding=ROUND_HALF_UP)


class FakeReplaySessionRepository:
    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or FakeClock()
        self._rows: dict[str, ReplaySessionRow] = {}

    # -- helpers ---------------------------------------------------------------------------------

    def _owned(self, user_id: str, session_id: str) -> ReplaySessionRow | None:
        row = self._rows.get(_canon(session_id) or "")
        return row if row is not None and row.user_id == _canon(user_id) else None

    def _writable(
        self, user_id: str, session_id: str, expected: ReplayState | None = None
    ) -> ReplaySessionRow:
        row = self._owned(user_id, session_id)
        if row is None:
            raise ReplaySessionNotFoundError(session_id)
        if row.state in TERMINAL_STATES or (expected is not None and row.state is not expected):
            raise ReplaySessionIllegalUpdateError(row.id, row.state, expected)
        return row

    def _store(self, row: ReplaySessionRow, **changes: Any) -> ReplaySessionRow:
        self._rows[row.id] = new = dataclasses.replace(row, **changes)
        return new

    @staticmethod
    def _check(
        *, start: datetime, end: datetime, cursor: datetime | None, speed: Decimal,
        paper: bool, account: str | None, tier: str,
    ) -> None:  # fmt: skip
        """Postgres evaluates CHECKs in name order: rps_cursor, rps_paper, rps_range, ..."""
        if cursor is not None and not start <= cursor <= end:
            raise ReplaySessionConstraintError("rps_cursor")
        if paper and account is None:
            raise ReplaySessionConstraintError("rps_paper")
        if end <= start:
            raise ReplaySessionConstraintError("rps_range")
        if not _SPEED_MIN <= speed <= _SPEED_MAX:
            raise ReplaySessionConstraintError("rps_speed")
        if tier not in {t.value for t in SourceTier}:
            raise ReplaySessionConstraintError("rps_tier")

    # -- ReplaySessionRepository -----------------------------------------------------------------

    async def create(self, row: ReplaySessionCreate) -> ReplaySessionRow:
        now = self._clock()
        if not _SYMBOL_CODE.fullmatch(
            row.symbol
        ):  # a domain check, coerced before the table CHECKs
            raise ReplaySessionConstraintError("symbol_code_check")
        speed = _numeric_6_2(row.speed)
        self._check(
            start=row.range_start, end=row.range_end, cursor=row.cursor_ts, speed=speed,
            paper=row.paper_trading, account=row.paper_account_id, tier=row.source_tier,
        )  # fmt: skip
        sid, uid = str(uuid.UUID(row.id)), str(uuid.UUID(row.user_id))
        if sid in self._rows:
            raise ReplaySessionConstraintError("replay_sessions_pkey")
        made = ReplaySessionRow(
            id=sid, user_id=uid, symbol=row.symbol,
            recording_session_id=row.recording_session_id, range_start=row.range_start,
            range_end=row.range_end, cursor_ts=row.cursor_ts, speed=speed,
            state=ReplayState.CREATED, source_tier=SourceTier(row.source_tier),
            paper_trading=row.paper_trading, paper_account_id=row.paper_account_id,
            bookmarks=tuple(row.bookmarks), loop_enabled=row.loop_enabled, events_emitted=0,
            gap_warnings=0, error_message=None, created_at=now, updated_at=now, finished_at=None,
        )  # fmt: skip
        self._rows[sid] = made
        return made

    async def get(self, user_id: str, session_id: str) -> ReplaySessionRow | None:
        return self._owned(user_id, session_id)

    async def list_page(
        self,
        user_id: str,
        *,
        state: ReplayState | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ReplaySessionPage:
        n = clamp_limit(limit)
        after = decode_cursor(cursor) if cursor else None
        wanted = None if state is None else ReplayState(state)
        rows = sorted(
            (
                r for r in self._rows.values()
                if r.user_id == _canon(user_id) and (wanted is None or r.state is wanted)
            ),
            key=lambda r: (r.created_at, r.id),
            reverse=True,
        )  # fmt: skip
        if after is not None:
            rows = [r for r in rows if (r.created_at, r.id) < after]
        page = rows[:n]
        more = len(rows) > n
        return ReplaySessionPage(
            tuple(page), encode_cursor(page[-1].created_at, page[-1].id) if more else None
        )

    async def update_state(
        self,
        user_id: str,
        session_id: str,
        *,
        state: ReplayState,
        expected_state: ReplayState | None = None,
        finished: bool = False,
        error_message: str | None = None,
    ) -> ReplaySessionRow:
        target = ReplayState(state)
        expected = None if expected_state is None else ReplayState(expected_state)
        now = self._clock()
        finished_at, message = state_columns(
            target, now=now, finished=finished, error_message=error_message
        )
        row = self._writable(user_id, session_id, expected)
        return self._store(
            row, state=target, updated_at=max(row.updated_at, now), finished_at=finished_at,
            error_message=message,
        )  # fmt: skip

    async def update_cursor(
        self,
        user_id: str,
        session_id: str,
        *,
        cursor_ts: datetime,
        events_emitted: int | None = None,
        gap_warnings: int | None = None,
    ) -> None:
        require_aware(cursor_ts, "cursor_ts")
        require_counters(events_emitted, gap_warnings)
        row = self._writable(user_id, session_id)
        self._check(
            start=row.range_start, end=row.range_end, cursor=cursor_ts, speed=row.speed,
            paper=row.paper_trading, account=row.paper_account_id, tier=row.source_tier,
        )  # fmt: skip
        self._store(
            row, cursor_ts=cursor_ts,
            events_emitted=row.events_emitted if events_emitted is None else events_emitted,
            gap_warnings=row.gap_warnings if gap_warnings is None else gap_warnings,
        )  # fmt: skip

    async def update_speed(
        self, user_id: str, session_id: str, *, speed: Decimal
    ) -> ReplaySessionRow:
        now = self._clock()
        row = self._writable(user_id, session_id)
        stored = _numeric_6_2(speed)
        self._check(
            start=row.range_start, end=row.range_end, cursor=row.cursor_ts, speed=stored,
            paper=row.paper_trading, account=row.paper_account_id, tier=row.source_tier,
        )  # fmt: skip
        return self._store(row, speed=stored, updated_at=max(row.updated_at, now))

    async def touch(self, user_id: str, session_id: str, at: datetime) -> None:
        require_aware(at, "at")
        row = self._writable(user_id, session_id)
        self._store(row, updated_at=max(row.updated_at, at))

    async def count_active(self, user_id: str) -> int:
        return sum(
            r.user_id == _canon(user_id) and r.state in LIVE_STATES for r in self._rows.values()
        )

    async def list_idle_since(self, before: datetime, limit: int) -> list[IdleReplaySession]:
        require_aware(before, "before")
        idle = sorted(
            (r for r in self._rows.values() if r.state in LIVE_STATES and r.updated_at < before),
            key=lambda r: (r.updated_at, r.id),
        )
        return [
            IdleReplaySession(r.id, r.user_id, r.symbol, r.state, r.paper_account_id, r.updated_at)
            for r in idle[: clamp_limit(limit)]
        ]

    async def delete(self, user_id: str, session_id: str) -> bool:
        row = self._owned(user_id, session_id)
        if row is None:
            return False
        del self._rows[row.id]
        return True
