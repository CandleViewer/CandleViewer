"""The view-as context of a session (#3085): the Owner sees the app as another user, read-only.

`22-api-openapi.yaml`, "View-as session": `POST /admin/view-as` starts a context on the caller's
session, the **viewer**'s, for a **target**; `GET`/`DELETE /auth/session/view-as` read and end it.
It is held on the session's row (`SessionRecord.view_as`) and a refresh carries it to the next.

Phases (`ViewAsState.phase`, read at the injected auth clock, so an expiry needs no write): `none`
(no context, or a cleared one), `live` (not ended and before `expires_at`: it views as the
target) and `held` (ended, or at or past `expires_at`, and not cleared: it grants nothing until
`DELETE /auth/session/view-as` clears it). `expires_at` is `started_at` plus 30 minutes.

An end is one conditional write, and only its winner writes `admin.view_as_ended`; a record that
cannot be written then stays pending on the row (`end_pending`) until it is written late. A model
refuses what the `sessions` CHECK refuses: presence and the time relations of `_shape`, never an
order between `ended_at`, `end_recorded_at` and `cleared_at` (a stepped clock could break one).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Final, Literal, Protocol, Self
from uuid import UUID

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    from candleviewer.auth.models import SessionRecord

VIEW_AS_TTL: Final = timedelta(minutes=30)  # 22: from `started_at`, and nothing extends it


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware (UTC)")
    return value.astimezone(UTC)


_Utc = Annotated[datetime, AfterValidator(_utc)]
_FROZEN = ConfigDict(frozen=True, extra="forbid")


class ViewAsPhase(StrEnum):
    """Where a session's context stands at an instant (`ViewAsState.phase`)."""

    NONE = "none"  # no context, or a cleared one
    LIVE = "live"  # not ended and before `expires_at`: the session views as the target
    HELD = "held"  # ended, or at or past `expires_at`, and not cleared: it grants nothing


class ViewAsEndReason(StrEnum):
    """Why a context ended, the reason of its `admin.view_as_ended` (22 `endViewAs`). Closed."""

    ENDED = "ended"  # `DELETE /auth/session/view-as`
    EXPIRED = "expired"  # at `expires_at`; derived, never asked for (`ViewAsState.end_at`)
    VIEWER_INELIGIBLE = "viewer_ineligible"  # the viewer's session lost `users:write`
    TARGET_INELIGIBLE = "target_ineligible"  # the target became an Owner or was disabled
    SESSION_ENDED = "session_ended"  # logout, or the session's revocation or expiry


class ViewAsState(BaseModel):
    """A session's view-as context as its row holds it; timestamps are timezone-aware, in UTC."""

    model_config = _FROZEN

    context_id: UUID
    target_user_id: UUID
    started_at: _Utc
    expires_at: _Utc
    ended_at: _Utc | None = None
    end_reason: ViewAsEndReason | None = None
    end_recorded_at: _Utc | None = None
    cleared_at: _Utc | None = None

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.expires_at != self.started_at + VIEW_AS_TTL:
            raise ValueError("expires_at must be started_at plus VIEW_AS_TTL (30 minutes)")
        if (self.ended_at is None) != (self.end_reason is None):
            raise ValueError("ended_at and end_reason must be set together or not at all")
        if self.ended_at is None:
            if self.end_recorded_at is not None or self.cleared_at is not None:
                raise ValueError("end_recorded_at and cleared_at must not be set without ended_at")
            return self
        if self.ended_at > self.expires_at:
            raise ValueError("ended_at must not be after expires_at")
        if (self.end_reason is ViewAsEndReason.EXPIRED) != (self.ended_at == self.expires_at):
            raise ValueError("end_reason must be expired exactly when ended_at is expires_at")
        return self

    def model_copy(self, *, update: Mapping[str, object] | None = None, deep: bool = False) -> Self:
        """A copy validated as a new row, so no copy bypasses `_shape` (`deep` is moot: frozen)."""
        return self.model_validate({**self.model_dump(), **(update or {})})

    @classmethod
    def start(cls, context_id: UUID, target_user_id: UUID, *, now: datetime) -> ViewAsState:
        """A fresh context started at `now`, the server's clock: the request sets neither time."""
        started = _utc(now)
        return cls(
            context_id=context_id,
            target_user_id=target_user_id,
            started_at=started,
            expires_at=started + VIEW_AS_TTL,
        )

    @property
    def end_pending(self) -> bool:
        """Ended, with its `admin.view_as_ended` not written yet (it is written late)."""
        return self.ended_at is not None and self.end_recorded_at is None

    def phase(self, *, now: datetime) -> ViewAsPhase:
        """The phase at `now`, the injected auth clock: an expiry needs no write."""
        at = _utc(now)
        if self.cleared_at is not None:
            return ViewAsPhase.NONE
        if self.ended_at is None and at < self.expires_at:
            return ViewAsPhase.LIVE
        return ViewAsPhase.HELD

    def end_at(self, *, now: datetime, reason: ViewAsEndReason) -> tuple[datetime, ViewAsEndReason]:
        """The `(ended_at, end_reason)` a write records for an end asked at `now`: from `expires_at`
        on, `(expires_at, expired)` whatever was asked (derived); never before `started_at`."""
        if self.ended_at is not None:
            raise ValueError("the context already ended: a context ends exactly once")
        at = max(_utc(now), self.started_at)
        if at >= self.expires_at:
            return self.expires_at, ViewAsEndReason.EXPIRED
        if reason is ViewAsEndReason.EXPIRED:
            raise ValueError("expired is derived from expires_at, never asked for before it")
        return at, reason

    def binding(self, *, now: datetime) -> ViewAsBinding | None:
        """What a request or a socket of the session is bound to at `now`; `None` in `NONE`."""
        phase = self.phase(now=now)
        if phase is ViewAsPhase.NONE:
            return None
        return ViewAsBinding(
            context_id=self.context_id,
            target_user_id=self.target_user_id,
            expires_at=self.expires_at,
            phase=phase,
        )


def view_as_phase(state: ViewAsState | None, *, now: datetime) -> ViewAsPhase:
    """The phase at `now` of a session's optional context: `NONE` when it holds none."""
    return ViewAsPhase.NONE if state is None else state.phase(now=now)


class ViewAsBinding(BaseModel):
    """What a request or socket of a viewing session is bound to (23-ws-protocol.md section 9.6)."""

    model_config = _FROZEN

    context_id: UUID
    target_user_id: UUID
    expires_at: _Utc
    phase: Literal[ViewAsPhase.LIVE, ViewAsPhase.HELD]


class ViewAsRequestContext(BaseModel):
    """What the view-as guard stamps (`request.scope["state"]["cv.view_as"]`) and binds on every
    request of a session holding a context, own operations and held ones too. The viewer is the
    actor (`viewer_label`, their username); a request answers in the scope of `subject_user_id`
    (`is_viewing_as_target`), never `target_user_id`, and a held context only as the viewer."""

    model_config = _FROZEN

    viewer_user_id: UUID
    viewer_session_id: UUID = Field(repr=False)
    viewer_label: str = Field(min_length=1)
    target_user_id: UUID
    context_id: UUID
    subject_user_id: UUID
    phase: Literal[ViewAsPhase.LIVE, ViewAsPhase.HELD]

    @model_validator(mode="after")
    def _parties(self) -> Self:
        if self.viewer_user_id == self.target_user_id:
            raise ValueError("the viewer must not be the target")
        if self.subject_user_id not in (self.viewer_user_id, self.target_user_id):
            raise ValueError("the subject must be the viewer or the target")
        if self.phase is ViewAsPhase.HELD and self.subject_user_id != self.viewer_user_id:
            raise ValueError("a held context answers as the viewer, never as the target")
        return self

    @property
    def is_viewing_as_target(self) -> bool:
        return self.subject_user_id == self.target_user_id


#: The context of the request or WebSocket frame being handled; set only by `bound_view_as`.
_CURRENT: ContextVar[ViewAsRequestContext | None] = ContextVar("cv_view_as", default=None)


def current_view_as() -> ViewAsRequestContext | None:
    """The view-as context bound to the running request or frame, or `None`."""
    return _CURRENT.get()


@contextmanager
def bound_view_as(ctx: ViewAsRequestContext) -> Iterator[ViewAsRequestContext]:
    """Bind `ctx` for the block, reset on every exit. A task created inside keeps it for life
    (contextvars are copied at task creation): create a long-lived one (a socket's push loop or
    close timer) outside the block, or rebind it."""
    token = _CURRENT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT.reset(token)


@dataclass(frozen=True, slots=True)
class ViewAsNotice:
    """The target's `system` notification of a start (22 `startViewAs`; the Q1 ruling, option A):
    one `system_events` row addressed to the target, `auth`/`view_as_started`/`info` (no
    incident), in the start's own unit of work. `message` names the viewer by username and the
    window, never the reason."""

    target_user_id: UUID
    message: str
    correlation_id: UUID | None


@dataclass(frozen=True, slots=True)
class ViewAsStartResult:
    """A start's outcome (`ViewAsService.start`): `started`, the row holding the new context;
    `held`, the row as it stands when it holds a context a start cannot replace (409
    `view_as_active`); neither when the session is revoked, absolute-expired or gone."""

    started: SessionRecord | None = None
    held: SessionRecord | None = None


#: A start's write-ahead hook: given the locked row, it writes an audit record or raises.
ViewAsStartHook = Callable[["SessionRecord"], Awaitable[None]]


class ViewAsSessionStore(Protocol):
    """The storage contract of the view-as columns of `sessions`, apart from `SessionRepository`
    until every repository implements it. Each write is one conditional write: `None` if unmet. A
    refresh carries a context to the successor row and the rotated row keeps its copy, so a context
    may sit on several rows: `admin.view_as_ended` is keyed by `context_id`, so it has one."""

    async def start_view_as(
        self, session_id: str, state: ViewAsState, *, now: datetime
    ) -> SessionRecord | None:
        """Put the fresh `state` on the row iff it is neither revoked nor absolute-expired at `now`
        and holds no context, or a cleared one whose end is recorded (of two concurrent starts,
        exactly one). An ended `state`, or a self-targeting one on a row that would take it, is a
        caller error: `ValueError`, nothing written (a row that refuses the start answers `None`
        first). The start request uses `start_view_as_unit`, which wraps this write."""
        ...

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
        """The start request's one unit of work (22 `startViewAs`; plan section 1.6), under the
        row's lock (`FOR NO KEY UPDATE`), so of concurrent starts exactly one writes anything.
        It answers `(started, held)`:
        - a row revoked, absolute-expired at `now` or gone answers `(None, None)`;
        - a context the row holds and a start cannot replace (live, or ended and not cleared)
          answers `(None, row)`;
        - a cleared context whose end is not recorded has its record written late
          (`flush_pending_end`) and is marked recorded;
        - then the notice, the started record ahead (`write_ahead`) and the fresh `state`,
          committed together: `(row, None)`.
        A hook past `audit_timeout_s` raises `WriteAheadTimeout`; a hook that fails raises its
        error; a write that fails raises the driver's. Each rolls everything back. An ended or
        self-targeting `state` is a caller error (`ValueError`), refused before any write."""
        ...

    async def end_view_as(
        self, session_id: str, context_id: UUID, *, ended_at: datetime, reason: ViewAsEndReason
    ) -> SessionRecord | None:
        """Set the end (from `ViewAsState.end_at`) iff the row holds `context_id`, unended, and,
        when the row is revoked, no other unrevoked row holds it. A rotated predecessor's copy is
        therefore refused once its successor carries the context on, so a stale end cannot spend
        the one keyed record on the predecessor; before the successor's insert commits (the gap
        `SessionService.refresh` bounds) the predecessor alone holds it and is ended. An orphaned
        or logged-out row is ended, as the sweeper does."""
        ...

    async def leave_view_as(
        self,
        session_id: str,
        context_id: UUID,
        *,
        ended_at: datetime,
        reason: ViewAsEndReason,
        now: datetime,
    ) -> tuple[SessionRecord, bool] | None:
        """The viewer's `DELETE` as one write, so a failure changes nothing: iff the row holds
        `context_id`, not cleared, and is not revoked, set the end (`ended_at`, `reason`) unless it
        has ended, and `cleared_at`. The row and whether this call ended it (the caller then writes
        the record). A revoked row is refused: a request in flight across a refresh would end the
        predecessor's copy while the successor carried the context on after its recorded end."""
        ...

    async def clear_view_as(
        self, session_id: str, context_id: UUID, *, now: datetime
    ) -> SessionRecord | None:
        """Set `cleared_at` iff the row holds `context_id`, ended and not cleared; the end stays."""
        ...

    async def mark_view_as_recorded(
        self, session_id: str, context_id: UUID, *, now: datetime
    ) -> SessionRecord | None:
        """Set `end_recorded_at` iff the row holds `context_id`, ended and not yet recorded."""
        ...

    async def list_view_as_due(
        self, *, now: datetime, rotated_grace: timedelta, limit: int
    ) -> tuple[SessionRecord, ...]:
        """Rows whose end is unrecorded and that ended, reached `expires_at`, or sit on a revoked
        or absolute-expired session: at most `limit`, earliest `expires_at` first. A row revoked
        `rotated` is due only once every row holding its context was revoked `rotated` at least
        `rotated_grace` ago (no successor came, or it moved on), so a carried copy is never due.
        Callers pass a `rotated_grace` longer than the gap between the `revoked_at` a refresh's
        claim stamps and its successor's insert (`SessionService.refresh` states the bound; the
        sweeper's setting must have a floor): a shorter one could end, as `session_ended`, a
        context a slow successor then carries."""
        ...

    async def list_live_view_as(self, *, limit: int) -> tuple[SessionRecord, ...]:
        """Unrevoked rows whose context has not ended, at most `limit`, earliest `expires_at` first,
        for the sweeper's eligibility pass (22 ends a context at once when its viewer or target
        stops being eligible). Its query keeps the `ix_sessions_view_as_target` predicate,
        `context_id IS NOT NULL AND ended_at IS NULL`."""
        ...

    async def list_live_view_as_by_target(self, target_user_id: UUID) -> tuple[SessionRecord, ...]:
        """Unrevoked rows whose unended context names `target_user_id`; the caller reads phases."""
        ...

    async def list_live_view_as_by_viewer(self, viewer_user_id: UUID) -> tuple[SessionRecord, ...]:
        """Unrevoked rows of `viewer_user_id`'s sessions that hold an unended context; the caller
        reads phases."""
        ...
