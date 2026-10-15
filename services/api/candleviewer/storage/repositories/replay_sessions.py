"""Driver-free replay-session repository surface (E26-T01 slice 2/3, `0023_replay_sessions`).

The replay module (M12) may not import a storage driver (ADR-0003), so the lifecycle service types
against `ReplaySessionRepository` and these plain frozen dataclasses;
`replay_sessions_sqlalchemy.py` is the Postgres implementation.

Owner scoping (C-12.4): every method takes the caller's `user_id` and the implementation re-checks
it in SQL. A missing row, a malformed id and another user's row are indistinguishable (`get` ->
None, writes -> `ReplaySessionNotFoundError`), so ids cannot be probed across users. The one
unscoped read is `list_idle_since`, the system-only reclaim sweep: it returns a projection without
`bookmarks`, which 21 §12 classifies P1 ("read only by `user_id` in the WHERE clause").

State (C-2.19): `ReplayState` carries every B12 `replay` chart state (28 §B12.2). Only `destroyed`
is final (§B12.3: `finished` and `error` re-enter via SEEK), so it is the one terminal state and
every mutator refuses it. Which transition is legal is the B12 machine's call; the repository only
refuses terminal rows and lost compare-and-sets.
"""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol


class ReplayState(StrEnum):
    """Mirror of the `replay_state` enum and of every B12 chart state (a unit test pins both)."""

    CREATED = "created"
    BUFFERING = "buffering"
    PLAYING = "playing"
    PAUSED = "paused"
    FINISHED = "finished"
    ERROR = "error"
    STEPPING = "stepping"
    DESTROYED = "destroyed"


class SourceTier(StrEnum):
    """Mirror of CHECK `rps_tier`: a closed enum, never a path (SR-097)."""

    AUTO = "auto"
    QUESTDB = "questdb"
    PARQUET = "parquet"


#: Sessions that hold buffers: the `ix_rps_live` predicate, what the quota counts and the
#: reclaim sweep scans.
LIVE_STATES = frozenset(
    {ReplayState.BUFFERING, ReplayState.PLAYING, ReplayState.PAUSED, ReplayState.STEPPING}
)
#: B12's only final state; terminal rows refuse every update (the owner may still delete them).
TERMINAL_STATES = frozenset({ReplayState.DESTROYED})
#: Entering one of these stamps `finished_at`.
FINISHED_STATES = frozenset({ReplayState.FINISHED, ReplayState.DESTROYED})
#: Upper bound for one page / one sweep batch; callers' limits are clamped into `1..MAX_PAGE_LIMIT`.
MAX_PAGE_LIMIT = 200
_MAX_CURSOR_CHARS = 256


class ReplaySessionNotFoundError(Exception):
    """Row is missing, malformed-id or owned by someone else (all identical, HTTP 404)."""


class ReplaySessionConstraintError(Exception):
    """The database rejected the row by a named CHECK, FK or key (`rps_range`, `rps_speed`, ...).

    `constraint` lets the service word a human-readable validation error (HTTP 422).
    """

    def __init__(self, constraint: str) -> None:
        super().__init__(f"replay session violates constraint {constraint!r}")
        self.constraint = constraint


class ReplaySessionIllegalUpdateError(Exception):
    """The row's current state refuses this update (HTTP 409).

    Either it is terminal (`current in TERMINAL_STATES`) or `expected_state` lost the
    compare-and-set (re-read and retry). Only raised for a row the caller owns.
    """

    def __init__(
        self, session_id: str, current: ReplayState, expected: ReplayState | None = None
    ) -> None:
        super().__init__(
            f"replay session {session_id} is {current.value}"
            + ("" if expected is None else f", expected {expected.value}")
        )
        self.session_id = session_id
        self.current = current
        self.expected = expected


class ReplaySessionCursorError(ValueError):
    """`cursor` is not one this repository issued (garbage, truncated or tampered; HTTP 422)."""


@dataclass(frozen=True, slots=True)
class ReplaySessionCreate:
    """What the service supplies at create; the row starts in `created` with zeroed counters.

    `id` is service-minted (the table has no default). `source_tier` is a closed enum, and no
    field accepts a filesystem path (SR-097).
    """

    id: str
    user_id: str
    symbol: str
    range_start: datetime
    range_end: datetime
    recording_session_id: str | None = None
    cursor_ts: datetime | None = None
    speed: Decimal = Decimal(1)
    source_tier: SourceTier = SourceTier.AUTO
    paper_trading: bool = False
    paper_account_id: str | None = None
    bookmarks: tuple[dict[str, Any], ...] = ()
    loop_enabled: bool = False

    def __post_init__(self) -> None:
        for name in ("range_start", "range_end", "cursor_ts"):
            if (value := getattr(self, name)) is not None:
                require_aware(value, name)


@dataclass(frozen=True, slots=True)
class ReplaySessionRow:
    """Every column of 21 §3.6.4. Datetimes are tz-aware UTC; ids are canonical uuid text."""

    id: str
    user_id: str
    recording_session_id: str | None
    symbol: str
    range_start: datetime
    range_end: datetime
    cursor_ts: datetime | None
    speed: Decimal
    state: ReplayState
    source_tier: SourceTier
    paper_trading: bool
    paper_account_id: str | None
    bookmarks: tuple[dict[str, Any], ...]
    loop_enabled: bool
    events_emitted: int
    gap_warnings: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True, slots=True)
class IdleReplaySession:
    """What the reclaim sweep needs to destroy one session; deliberately no `bookmarks` (P1)."""

    id: str
    user_id: str
    symbol: str
    state: ReplayState
    paper_account_id: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ReplaySessionPage:
    rows: tuple[ReplaySessionRow, ...]
    next_cursor: str | None


def require_aware(value: datetime, name: str) -> datetime:
    """Naive datetimes would silently misorder against timestamptz; refuse them."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def clamp_limit(limit: int) -> int:
    return max(1, min(limit, MAX_PAGE_LIMIT))


def require_counters(*counters: int | None) -> None:
    """`events_emitted` / `gap_warnings` only ever count up from zero."""
    if any(c is not None and c < 0 for c in counters):
        raise ValueError("counters must be >= 0")


def encode_cursor(created_at: datetime, session_id: str) -> str:
    """Opaque base64url of the last row's `(created_at, id)` keyset, unpadded."""
    raw = json.dumps([created_at.isoformat(), session_id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """Inverse of `encode_cursor`; anything else is a `ReplaySessionCursorError`, never a 500."""
    try:
        if len(cursor) > _MAX_CURSOR_CHARS:
            raise ValueError("too long")
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True))
        if not (
            isinstance(data, list) and len(data) == 2 and all(isinstance(x, str) for x in data)
        ):
            raise ValueError("wrong shape")
        created_at = require_aware(datetime.fromisoformat(data[0]), "cursor timestamp")
        return created_at, str(uuid.UUID(data[1]))
    except ValueError as exc:
        raise ReplaySessionCursorError("invalid cursor") from exc


def state_columns(
    state: ReplayState, *, now: datetime, finished: bool = False, error_message: str | None = None
) -> tuple[datetime | None, str | None]:
    """`(finished_at, error_message)` that entering `state` writes.

    Both describe the *current* state, so they are stamped on entry and cleared on exit:
    `finished_at` while `finished`/`destroyed` (or when `finished` forces it), `error_message`
    only while `error` (caller-sanitised: never a path or traceback, SR-097).
    """
    if error_message is not None and state is not ReplayState.ERROR:
        raise ValueError("error_message is only valid when entering the error state")
    return (now if finished or state in FINISHED_STATES else None), error_message


class ReplaySessionRepository(Protocol):
    async def create(self, row: ReplaySessionCreate) -> ReplaySessionRow:
        """Insert in `created`. A violated CHECK/FK/key is `ReplaySessionConstraintError`."""
        ...

    async def get(self, user_id: str, session_id: str) -> ReplaySessionRow | None: ...

    async def list_page(
        self,
        user_id: str,
        *,
        state: ReplayState | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ReplaySessionPage:
        """Newest first by `(created_at, id)` DESC; `limit` is clamped into `1..MAX_PAGE_LIMIT`."""
        ...

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
        """Move to `state`; atomic compare-and-set when `expected_state` is given.

        Always bumps `updated_at`; `finished_at` / `error_message` follow `state_columns`.
        `finished=True` additionally stamps `finished_at` for a state that does not imply it.
        A terminal row, or a lost compare-and-set, raises `ReplaySessionIllegalUpdateError`
        (so a second destroy raises: the B12 machine owns idempotency).
        """
        ...

    async def update_cursor(
        self,
        user_id: str,
        session_id: str,
        *,
        cursor_ts: datetime,
        events_emitted: int | None = None,
        gap_warnings: int | None = None,
    ) -> None:
        """Persist the throttled playback position and counters (absolute values) in one UPDATE.

        Deliberately leaves `updated_at` alone: the reclaim sweep reads it as the last *control*
        activity, so a session nobody is controlling must not look alive because its clock ticks.
        """
        ...

    async def update_speed(
        self, user_id: str, session_id: str, *, speed: Decimal
    ) -> ReplaySessionRow:
        """Change the multiplier (a control call, so it bumps `updated_at`)."""
        ...

    async def touch(self, user_id: str, session_id: str, at: datetime) -> None:
        """Record control activity: `updated_at` moves to `at`, never backwards."""
        ...

    async def count_active(self, user_id: str) -> int:
        """Sessions in `LIVE_STATES`; what the per-user concurrent-session quota compares."""
        ...

    async def list_idle_since(self, before: datetime, limit: int) -> list[IdleReplaySession]:
        """SYSTEM ONLY, not user-scoped: live sessions untouched since before `before`.

        Oldest first, at most `limit` (clamped), for the reclaim sweep.
        """
        ...

    async def delete(self, user_id: str, session_id: str) -> bool:
        """Hard delete by the owner (any state); False when there was nothing to delete."""
        ...


__all__ = [
    "FINISHED_STATES", "LIVE_STATES", "MAX_PAGE_LIMIT", "TERMINAL_STATES", "IdleReplaySession",
    "ReplaySessionConstraintError", "ReplaySessionCreate", "ReplaySessionCursorError",
    "ReplaySessionIllegalUpdateError", "ReplaySessionNotFoundError", "ReplaySessionPage",
    "ReplaySessionRepository", "ReplaySessionRow", "ReplayState", "SourceTier", "clamp_limit",
    "decode_cursor", "encode_cursor", "require_aware", "require_counters", "state_columns",
]  # fmt: skip
