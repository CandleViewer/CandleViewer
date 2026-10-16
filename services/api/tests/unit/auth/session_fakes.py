"""In-memory `SessionRepository` fake for E09-S03 unit tests. No database."""

from __future__ import annotations

from datetime import datetime

from candleviewer.auth.models import SessionRecord, UserStatus
from candleviewer.auth.session_repository import StepUpChange


class FakeSessionRepository:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionRecord] = {}
        # prev_session_id -> next_session_id
        self.rotation_next: dict[str, str] = {}
        self.rotation_prev: dict[str, str] = {}
        #: #2911: `users.status` by user id (`None`: the user row is gone). Unset is `active`.
        self.user_statuses: dict[str, UserStatus | None] = {}

    def _user_status(self, user_id: object) -> UserStatus | None:
        return self.user_statuses.get(str(user_id), UserStatus.ACTIVE)

    def _with_status(self, session: SessionRecord | None) -> SessionRecord | None:
        """#2911: the by-id and by-refresh-hash reads carry the owner's status."""
        if session is None:
            return None
        return session.model_copy(update={"user_status": self._user_status(session.user_id)})

    async def create_session(self, session: SessionRecord) -> SessionRecord | None:
        """#2911: nothing is stored unless the user is `active`; the check and the insert are
        one step, as the real insert runs under the user row's lock."""
        if self._user_status(session.user_id) is not UserStatus.ACTIVE:
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
        if session is None or session.revoked_at is not None:
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
