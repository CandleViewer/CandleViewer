"""In-memory `SessionRepository` and `ViewAsSessionStore` fakes for auth unit tests, the two calls
that meet a stray session, and a loop clock a test advances. No database."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import UUID

import pytest

from candleviewer.auth.errors import SessionRevoked, UserDisabled
from candleviewer.auth.models import MintedSession, SessionRecord, UserStatus
from candleviewer.auth.session_repository import StepUpChange
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.view_as import ViewAsEndReason, ViewAsNotice, ViewAsStartHook, ViewAsState
from candleviewer.storage.errors import WriteAheadTimeout


def _due(session: SessionRecord, held: ViewAsState, now: datetime) -> bool:
    return held.end_recorded_at is None and (
        held.ended_at is not None
        or held.expires_at <= now
        or session.is_revoked
        or session.is_absolute_expired(now=now)
    )


class FakeSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionRecord] = {}
        # prev_session_id -> next_session_id
        self.rotation_next: dict[str, str] = {}
        self.rotation_prev: dict[str, str] = {}
        #: #2911: `users.status` by user id (`None`: the user row is gone). Unset is `active`.
        self.user_statuses: dict[str, UserStatus | None] = {}
        #: #3085: the starts' notices as committed, and a failure the next notice insert raises.
        self.notices: list[ViewAsNotice] = []
        self.notice_fails: Exception | None = None
        self._start_lock = asyncio.Lock()  # the row lock a start takes, for every row at once

    def _user_status(self, user_id: object) -> UserStatus | None:
        return self.user_statuses.get(str(user_id), UserStatus.ACTIVE)

    def _with_status(self, session: SessionRecord | None) -> SessionRecord | None:
        """#2911: the by-id and by-refresh-hash reads carry the owner's status."""
        if session is None:
            return None
        return session.model_copy(update={"user_status": self._user_status(session.user_id)})

    async def create_session(self, session: SessionRecord) -> SessionRecord | None:
        """#2911: nothing is stored when the user is `disabled` or gone; the check and the
        insert are one step, as the real insert runs under the user row's lock."""
        if self._user_status(session.user_id) in (UserStatus.DISABLED, None):
            return None
        self.sessions[str(session.id)] = session
        return session

    async def find_by_id(self, session_id: str) -> SessionRecord | None:
        return self._with_status(self.sessions.get(session_id))

    async def find_by_refresh_hash(self, refresh_token_hash: str) -> SessionRecord | None:
        for s in self.sessions.values():
            if s.refresh_token_hash == refresh_token_hash:
                return self._with_status(s)
        return None

    async def find_by_access_token_jti(self, access_token_jti: str) -> SessionRecord | None:
        for s in self.sessions.values():
            if str(s.access_token_jti) == access_token_jti:
                return s
        return None

    async def find_live_by_user(self, user_id: str) -> tuple[SessionRecord, ...]:
        return tuple(
            s for s in self.sessions.values() if str(s.user_id) == user_id and s.revoked_at is None
        )

    async def touch_last_seen(self, session_id: str, *, now: datetime) -> SessionRecord | None:
        session = self.sessions.get(session_id)
        # The SQL write is conditional on the lock too: activity never lifts it (#2300).
        if session is None or session.revoked_at is not None or session.is_idle_locked(now=now):
            return None
        updated = session.model_copy(update={"last_seen_at": now})
        self.sessions[session_id] = updated
        return updated

    async def lift_idle_lock(self, session_id: str, *, now: datetime) -> SessionRecord | None:
        session = self.sessions.get(session_id)
        if session is None or session.revoked_at is not None:
            return None
        updated = session.model_copy(update={"last_seen_at": now, "step_up_elevations": {}})
        self.sessions[session_id] = updated
        return updated

    async def revoke(self, session_id: str, *, reason: str, now: datetime) -> SessionRecord | None:
        session = self.sessions.get(session_id)
        if session is None or session.revoked_at is not None:
            return None
        updated = session.model_copy(update={"revoked_at": now, "revoked_reason": reason})
        self.sessions[session_id] = updated
        return updated

    async def update_step_up_state(
        self, session_id: str, change: StepUpChange
    ) -> SessionRecord | None:
        """Atomic like the locked read-and-write: no await between the read and the write."""
        session = self.sessions.get(session_id)
        if session is None or session.revoked_at is not None:
            return None
        elevations, failures, readonly_until = change(
            (dict(session.step_up_elevations), session.step_up_failures, session.readonly_until)
        )
        updated = session.model_copy(
            update={
                "step_up_elevations": dict(elevations),
                "step_up_failures": failures,
                "readonly_until": readonly_until,
            }
        )
        self.sessions[session_id] = updated
        return updated

    async def save_step_up_state(
        self,
        session_id: str,
        *,
        elevations: dict[str, datetime],
        failures: int,
        readonly_until: datetime | None,
    ) -> SessionRecord | None:
        """Seed the step-up columns. Tests only: `SessionRepository` has no blind write (#2304)."""
        return await self.update_step_up_state(
            session_id, lambda _state: (dict(elevations), failures, readonly_until)
        )

    async def consume_step_up_key(
        self, session_id: str, *, key: str, now: datetime
    ) -> SessionRecord | None:
        """Atomic like the conditional UPDATE: no await between the check and the write."""
        session = self.sessions.get(session_id)
        until = None if session is None else session.step_up_elevations.get(key)
        if session is None or session.revoked_at is not None or until is None or until <= now:
            return None
        remaining = {k: v for k, v in session.step_up_elevations.items() if k != key}
        updated = session.model_copy(update={"step_up_elevations": remaining})
        self.sessions[session_id] = updated
        return updated

    async def revoke_all_for_user(
        self, user_id: str, *, reason: str, now: datetime, except_session_id: str | None = None
    ) -> tuple[SessionRecord, ...]:
        revoked = []
        for sid, session in list(self.sessions.items()):
            if str(session.user_id) != user_id or session.revoked_at is not None:
                continue
            if except_session_id is not None and sid == except_session_id:
                continue
            updated = session.model_copy(update={"revoked_at": now, "revoked_reason": reason})
            self.sessions[sid] = updated
            revoked.append(updated)
        return tuple(revoked)

    async def link_rotation(self, *, prev_session_id: str, next_session_id: str) -> None:
        self.rotation_next[prev_session_id] = next_session_id
        self.rotation_prev[next_session_id] = prev_session_id

    async def walk_rotation_family(self, session_id: str) -> tuple[str, ...]:
        seen: set[str] = set()
        stack = [session_id]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            nxt = self.rotation_next.get(current)
            if nxt is not None:
                stack.append(nxt)
            prev = self.rotation_prev.get(current)
            if prev is not None:
                stack.append(prev)
        return tuple(seen)

    # -- #3085 `ViewAsSessionStore`: no await between a write's check and its write.

    def _view_as_context(self, session_id: str, context_id: UUID) -> ViewAsState | None:
        session = self.sessions.get(session_id)
        held = None if session is None else session.view_as
        return held if held is not None and held.context_id == context_id else None

    def _carried_on(self, session_id: str, context_id: UUID) -> bool:
        """A revoked row whose context another, unrevoked row holds: its successor carries it on."""
        others = (s for sid, s in self.sessions.items() if sid != session_id and not s.is_revoked)
        return self.sessions[session_id].is_revoked and any(
            s.view_as is not None and s.view_as.context_id == context_id for s in others
        )

    def _put_view_as(self, session_id: str, state: ViewAsState) -> SessionRecord:
        """Store `state` on the row, rebuilt so its CHECKs apply (`model_copy` would skip them)."""
        updated = SessionRecord.model_validate(
            {**dict(self.sessions[session_id]), "view_as": state}
        )
        self.sessions[session_id] = updated
        return updated

    async def start_view_as(
        self, session_id: str, state: ViewAsState, *, now: datetime
    ) -> SessionRecord | None:
        if state.ended_at is not None:
            raise ValueError("a start puts a fresh context on the row, never an ended one")
        session = self.sessions.get(session_id)
        if session is None or session.is_revoked or session.is_absolute_expired(now=now):
            return None
        held = session.view_as
        if held is not None and (held.cleared_at is None or held.end_recorded_at is None):
            return None
        if state.target_user_id == session.user_id:  # the CHECK, where the write would apply
            raise ValueError("a session must never view as its own user")
        return self._put_view_as(session_id, state)

    async def start_view_as_unit(
        self,
        session_id: str,
        state: ViewAsState,
        *,
        now: datetime,
        notice: ViewAsNotice,
        flush_pending_end: ViewAsStartHook,
        write_ahead: ViewAsStartHook,
        audit_timeout_s: float,
    ) -> tuple[SessionRecord | None, SessionRecord | None]:
        """As the SQL store's: every write lands at the end, together, or none does."""
        if state.ended_at is not None:
            raise ValueError("a start puts a fresh context on the row, never an ended one")
        async with self._start_lock:
            session = self.sessions.get(session_id)
            if session is None or session.is_revoked or session.is_absolute_expired(now=now):
                return None, None
            held = session.view_as
            if held is not None and held.cleared_at is None:
                return None, session
            if state.target_user_id == session.user_id:
                raise ValueError("a session must never view as its own user")
            if held is not None and held.end_recorded_at is None:
                await _bounded(flush_pending_end(session), audit_timeout_s)
            if self.notice_fails is not None:
                raise self.notice_fails
            await _bounded(write_ahead(session), audit_timeout_s)
            self.notices.append(notice)
            return self._put_view_as(session_id, state), None

    async def end_view_as(
        self, session_id: str, context_id: UUID, *, ended_at: datetime, reason: ViewAsEndReason
    ) -> SessionRecord | None:
        held = self._view_as_context(session_id, context_id)
        if held is None or held.ended_at is not None or self._carried_on(session_id, context_id):
            return None
        end = {"ended_at": ended_at, "end_reason": reason}
        return self._put_view_as(session_id, held.model_copy(update=end))

    async def leave_view_as(
        self,
        session_id: str,
        context_id: UUID,
        *,
        ended_at: datetime,
        reason: ViewAsEndReason,
        now: datetime,
    ) -> tuple[SessionRecord, bool] | None:
        held = self._view_as_context(session_id, context_id)
        if held is None or held.cleared_at is not None or self.sessions[session_id].is_revoked:
            return None
        ends = held.ended_at is None
        end = {"ended_at": ended_at, "end_reason": reason} if ends else {}
        state = held.model_copy(update={**end, "cleared_at": now})
        return self._put_view_as(session_id, state), ends

    async def clear_view_as(
        self, session_id: str, context_id: UUID, *, now: datetime
    ) -> SessionRecord | None:
        held = self._view_as_context(session_id, context_id)
        if held is None or held.ended_at is None or held.cleared_at is not None:
            return None
        return self._put_view_as(session_id, held.model_copy(update={"cleared_at": now}))

    async def mark_view_as_recorded(
        self, session_id: str, context_id: UUID, *, now: datetime
    ) -> SessionRecord | None:
        held = self._view_as_context(session_id, context_id)
        if held is None or not held.end_pending:
            return None
        return self._put_view_as(session_id, held.model_copy(update={"end_recorded_at": now}))

    async def list_view_as_due(
        self, *, now: datetime, rotated_grace: timedelta, limit: int
    ) -> tuple[SessionRecord, ...]:
        held = [(s, s.view_as) for s in self.sessions.values() if s.view_as is not None]
        cutoff = now - rotated_grace
        carried = {  # contexts a row still carries: not revoked `rotated`, or within the grace
            v.context_id
            for s, v in held
            if s.revoked_reason != "rotated" or s.revoked_at is None or s.revoked_at > cutoff
        }
        due = [
            (v.expires_at, s)
            for s, v in held
            if _due(s, v, now) and (s.revoked_reason != "rotated" or v.context_id not in carried)
        ]
        due.sort(key=lambda pair: pair[0])  # stable: equal expiries keep insertion order
        return tuple(s for _, s in due[:limit])

    def _unended(self) -> list[tuple[SessionRecord, ViewAsState]]:
        return [
            (s, s.view_as)
            for s in self.sessions.values()
            if s.revoked_at is None and s.view_as is not None and s.view_as.ended_at is None
        ]

    async def list_live_view_as(self, *, limit: int) -> tuple[SessionRecord, ...]:
        live = sorted(self._unended(), key=lambda pair: pair[1].expires_at)  # stable, as above
        return tuple(s for s, _ in live[:limit])

    async def list_live_view_as_by_target(self, target_user_id: UUID) -> tuple[SessionRecord, ...]:
        return tuple(s for s, v in self._unended() if v.target_user_id == target_user_id)

    async def list_live_view_as_by_viewer(self, viewer_user_id: UUID) -> tuple[SessionRecord, ...]:
        return tuple(s for s, _ in self._unended() if s.user_id == viewer_user_id)


async def _bounded(hook: Awaitable[None], timeout_s: float) -> None:
    """`bounded_write_ahead`'s contract, without its storage import."""
    try:
        async with asyncio.timeout(timeout_s):
            await hook
    except TimeoutError as exc:
        raise WriteAheadTimeout(f"write-ahead audit exceeded {timeout_s} s") from exc


class YieldingFindRepository(FakeSessionRepository):
    """Yields after each by-id and by-refresh-hash read, so every request of a burst holds the row
    as it was before the first of them revoked it (on Postgres the read and the revoke are two
    statements)."""

    async def find_by_id(self, session_id: str) -> SessionRecord | None:
        found = await super().find_by_id(session_id)
        await asyncio.sleep(0)
        return found

    async def find_by_refresh_hash(self, refresh_token_hash: str) -> SessionRecord | None:
        found = await super().find_by_refresh_hash(refresh_token_hash)
        await asyncio.sleep(0)
        return found


class LostRaceRepository(FakeSessionRepository):
    """Another caller revokes the row first: this call's conditional revoke changes nothing."""

    async def revoke(self, session_id: str, *, reason: str, now: datetime) -> SessionRecord | None:
        return None


class CommitParkedRepository(FakeSessionRepository):
    """The revoke commits, then parks until the test sets `release`: a cancel that lands after the
    `UPDATE` committed but before its answer came back (#3332). With *fail_with* the revoke raises
    it after the commit instead of answering, as a dropped connection would."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        super().__init__()
        self.parked, self.release = asyncio.Event(), asyncio.Event()
        self.fail_with = fail_with

    async def revoke(self, session_id: str, *, reason: str, now: datetime) -> SessionRecord | None:
        updated = await super().revoke(session_id, reason=reason, now=now)
        self.parked.set()
        await self.release.wait()
        if self.fail_with is not None:
            raise self.fail_with
        return updated


class LoopClock:
    """The running loop's clock plus a skew the test advances: an `asyncio.timeout` fires when the
    test says so and nothing waits; other timers keep real time, so a hang still fails."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        loop = asyncio.get_running_loop()
        real, self._skew = loop.time, 0.0
        monkeypatch.setattr(loop, "time", lambda: real() + self._skew)

    def advance(self, seconds: float) -> None:
        self._skew += seconds


#: A call that meets a stray session, a live session of a disabled or deleted user that no disable
#: revoked: it revokes the session as `user_disabled` and refuses the call (#2911, #3331).
StrayEntry = Callable[[SessionService, MintedSession], Awaitable[object]]


async def require_active_by_id(service: SessionService, minted: MintedSession) -> object:
    return await service.require_active(str(minted.session_id))


async def refresh_by_token(service: SessionService, minted: MintedSession) -> object:
    return await service.refresh(minted.refresh_token)


#: `(entry, refusal, match)`: the two entries revoke the same way (#3331), and each refuses with
#: its own error, whose message *match* finds.
STRAY_ENTRIES = [
    pytest.param(
        require_active_by_id,
        SessionRevoked,
        "session revoked: user_disabled",
        id="require_active",
    ),
    pytest.param(refresh_by_token, UserDisabled, "user is disabled or gone", id="refresh"),
]
