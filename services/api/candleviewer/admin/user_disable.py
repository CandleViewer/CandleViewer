"""`UserDisableService`: the disable cascade of `DELETE /users/{userId}` and E42-T09's `PATCH`
(E42-T04 S4, #965, SR-029). In order (R7): (1) `users:write`, then a self-target (SR-055), each
refusal audited, before any read of the target (U25); (2) the open-position and -order counts
(O2: nothing here flattens, cancels or places an order), an unknown one needing the caller's
acknowledgement (AC7); (3) the store's transaction (S3), whose hook writes `users.disable` ahead
with ids, status, roles and counts only (O6), closed by a `failure` record if nothing committed;
(4) isolated, logged, counted post-commit steps, never rolled back: socket close through the
session service's publish path (`bye user_disabled`, 4403), a sweep of a successor an in-flight
refresh minted after the snapshot, one B16 REVOKE per session (R5) and an `invited` user's
open invite (R6). S5 adds the rule disarm."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, Protocol

import structlog

from candleviewer.admin.errors import (
    LastOwnerError,
    LifecycleAuditUnavailableError,
    LifecycleForbiddenError,
    PositionsUnknownError,
    UserLifecycleError,
    UserNotFoundError,
)
from candleviewer.admin.lifecycle_metrics import user_lifecycle_steps_total, user_lifecycle_total
from candleviewer.audit.errors import AuditError
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.errors import InviteNotFound
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.owner_floor import OwnerFloorError
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.auth.session_service import RevocationSink, publish_revoked
from candleviewer.auth.step_up import PositionStateProvider
from candleviewer.observability.context import current_request_id
from candleviewer.storage.repositories.user_lifecycle import (
    REVOKED_REASON,
    LifecycleAuditHook,
    UserStatusChange,
)

POSITIONS_DECISION: Final = "leave"  # O2: positions and orders stay as they are
CLOSING_TIMEOUT_S: Final = 2.0  # bounds the closing record; the writer may still be slow
_AUDIT_DOWN = (AuditError, RuntimeError)  # `AuditWriter` refusals; RuntimeError: not started


class LifecycleStore(Protocol):  # `SqlAlchemyUserLifecycleStore` (S3)
    async def disable(
        self, user_id: uuid.UUID, *, actor: uuid.UUID, now: datetime, audit: LifecycleAuditHook
    ) -> UserStatusChange | None: ...


class AuditEmitter(Protocol):  # `AuditWriter` (M19): durable, write-ahead
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class OpenOrderCounter(Protocol):  # `None` while unknown (UL-F9: no order has a user yet)
    async def open_order_count(self, user_id: str) -> int | None: ...


class SessionSweeper(Protocol):  # `SessionService`: revokes and publishes each live session
    async def revoke_all(self, user_id: str, *, reason: str) -> tuple[SessionRecord, ...]: ...


class SessionRows(Protocol):  # `SessionRepository`
    async def find_by_id(self, session_id: str) -> SessionRecord | None: ...


class SessionRevokeRecorder(Protocol):  # the process's B16 charts: `StepUpService.chart`
    async def revoke(self, record: SessionRecord, now: datetime, reason: str) -> None: ...


class InviteRevoker(Protocol):  # `InviteService`: `InviteNotFound` when none is open
    async def revoke(self, user_id: uuid.UUID) -> None: ...


@dataclass(frozen=True, slots=True)
class DisableResult:  # `changed` is False for AC5's no-op
    changed: bool
    failed_steps: tuple[str, ...] = ()


class _AuditRefusedError(Exception):
    """`users.disable` was not made durable; the transaction rolled back."""


@dataclass
class _Tally:  # one step's runs, each isolated so a failure never stops the others (R7)
    attempted: int = 0
    failures: int = 0
    error: str | None = None  # the type only: a message may carry ids

    async def run[T](self, op: Awaitable[T]) -> T | None:
        self.attempted += 1
        try:
            return await op
        except Exception as exc:  # isolated by design; `_step` counts and logs it
            self.failures, self.error = self.failures + 1, type(exc).__name__
            return None

    @property
    def outcome(self) -> str:
        return "failed" if self.failures else "ok" if self.attempted else "skipped"


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _request_uuid() -> uuid.UUID | None:  # the bound correlation id (a UUID4 at the edge)
    try:
        return uuid.UUID(current_request_id() or "")
    except ValueError:
        return None


def _who(actor: uuid.UUID, target: uuid.UUID, rid: uuid.UUID | None) -> dict[str, Any]:  # O6
    return {
        "actor_label": str(actor),
        "actor_user_id": actor,
        "object_kind": "user",
        "object_id": str(target),
        "request_id": rid,
    }


async def _count(read: Awaitable[int | None], kind: str) -> int | None:  # unreadable: unknown
    try:
        return await read
    except Exception as exc:  # the caller then needs the acknowledgement
        _log().warning("users.disable.exposure_unreadable", kind=kind, error=type(exc).__name__)
        return None


class UserDisableService:
    def __init__(
        self,
        store: LifecycleStore,
        audit: AuditEmitter,
        *,
        positions: PositionStateProvider,
        orders: OpenOrderCounter,
        sessions: SessionSweeper,
        session_rows: SessionRows,
        chart: SessionRevokeRecorder,
        publish_revocation: RevocationSink,
        invites: InviteRevoker,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        closing_timeout_s: float = CLOSING_TIMEOUT_S,
    ) -> None:
        self._store, self._audit, self._clock = store, audit, clock
        self._positions, self._orders = positions, orders
        self._sessions, self._rows, self._chart = sessions, session_rows, chart
        self._publish, self._invites = publish_revocation, invites
        self._closing_timeout_s = closing_timeout_s

    async def disable(
        self,
        user_id: uuid.UUID,
        *,
        actor: PrincipalSnapshot,
        acknowledge_unknown_positions: bool = False,
    ) -> DisableResult:
        """Raises a `UserLifecycleError` with nothing changed, or a store failure (rolled back)."""
        rid, now, uid = _request_uuid(), self._clock(), str(user_id)
        await self._guard(user_id, actor, rid)
        positions = await _count(self._positions.open_position_count(uid), "positions")
        orders = await _count(self._orders.open_order_count(uid), "orders")
        if (positions is None or orders is None) and not acknowledge_unknown_positions:
            raise self._refused("positions_unknown", PositionsUnknownError(self._positions.source))
        counts = {
            "positions_decision": POSITIONS_DECISION,
            "open_position_count": positions,
            "open_order_count": orders,
            "acknowledged_unknown_positions": acknowledge_unknown_positions,
        }
        change = await self._commit(user_id, actor.user_id, counts, rid, now)
        if change is None:
            raise self._refused("not_found", UserNotFoundError(uid))
        if not change.changed:
            user_lifecycle_total.labels(action="disable", result="noop").inc()
            return DisableResult(changed=False)
        user_lifecycle_total.labels(action="disable", result="disabled").inc()
        return DisableResult(True, await self._after_commit(change, actor.user_id, rid, now))

    async def _guard(
        self, user_id: uuid.UUID, actor: PrincipalSnapshot, rid: uuid.UUID | None
    ) -> None:
        try:
            await enforce(actor, Permission.USERS_WRITE, scope=Scope.NONE, emitter=self._audit)
            if user_id == actor.user_id:
                await self._audit.emit(
                    "rbac.denied",
                    **_who(actor.user_id, user_id, rid),
                    outcome=AuditOutcome.DENIED,
                    severity=Severity.WARNING,
                    reason="self_target",
                )
        except ForbiddenError as exc:  # `enforce` audited `rbac.denied`
            raise self._refused("forbidden", LifecycleForbiddenError("forbidden_role")) from exc
        except _AUDIT_DOWN as exc:
            raise self._refused("audit_unavailable", LifecycleAuditUnavailableError()) from exc
        if user_id == actor.user_id:
            raise self._refused("self_target", LifecycleForbiddenError("self_target"))

    async def _commit(
        self,
        user_id: uuid.UUID,
        actor: uuid.UUID,
        counts: dict[str, Any],
        rid: uuid.UUID | None,
        now: datetime,
    ) -> UserStatusChange | None:
        handed: list[UserStatusChange] = []  # the change the hook got, once it started
        written = False

        async def write_ahead(change: UserStatusChange) -> None:
            nonlocal written
            handed.append(change)
            roles = sorted(change.roles)
            grants = {str(account): level for account, level in change.revoked_grants.items()}
            after = {"status": change.after, "roles": roles, "grants": {}}
            try:
                await self._audit.emit(
                    "users.disable",
                    **_who(actor, user_id, rid),
                    outcome=AuditOutcome.SUCCESS,
                    severity=Severity.WARNING,
                    before_state={"status": change.before, "roles": roles, "grants": grants},
                    after_state=after
                    | {"sessions_revoked": len(change.revoked_session_ids), **counts},
                )
            except _AUDIT_DOWN as exc:
                raise _AuditRefusedError from exc
            written = True

        try:
            return await self._store.disable(user_id, actor=actor, now=now, audit=write_ahead)
        except OwnerFloorError as exc:  # refused under the lock, unaudited (UL1-D1)
            raise self._refused("last_owner", LastOwnerError(str(user_id))) from exc
        except _AuditRefusedError as exc:  # AC8: nothing durable, nothing changed
            raise self._refused("audit_unavailable", LifecycleAuditUnavailableError()) from exc
        except BaseException as exc:
            if handed:  # the record may be durable for a change that did not commit
                await self._close(handed[0], actor, rid)
            if isinstance(exc, TimeoutError) and handed and not written:  # the hook timed out
                raise self._refused("audit_unavailable", LifecycleAuditUnavailableError()) from exc
            if isinstance(exc, Exception):
                user_lifecycle_total.labels(action="disable", result="error").inc()
            raise

    async def _close(
        self, change: UserStatusChange, actor: uuid.UUID, rid: uuid.UUID | None
    ) -> None:
        """Close a write-ahead `users.disable` whose change did not commit."""
        tally, unchanged = _Tally(), {"status": change.before, "roles": sorted(change.roles)}
        record = self._audit.emit(
            "users.disable",
            **_who(actor, change.user_id, rid),
            outcome=AuditOutcome.FAILURE,
            severity=Severity.ERROR,
            reason="not_applied",
            before_state=unchanged,
            after_state=unchanged,
        )
        await tally.run(asyncio.wait_for(record, self._closing_timeout_s))
        self._step("closing_record", tally, change.user_id)

    async def _after_commit(
        self, change: UserStatusChange, actor: uuid.UUID, rid: uuid.UUID | None, now: datetime
    ) -> tuple[str, ...]:
        user, sockets, sweep, b16, invite = change.user_id, _Tally(), _Tally(), _Tally(), _Tally()

        async def publish(session_id: str, reason: str) -> None:  # isolated per session
            await sockets.run(self._publish(session_id, reason))

        await publish_revoked(publish, map(str, change.revoked_session_ids), REVOKED_REASON)
        self._step("socket_close", sockets, user)
        swept: tuple[SessionRecord, ...] = (
            await sweep.run(self._sessions.revoke_all(str(user), reason=REVOKED_REASON)) or ()
        )
        self._step("session_sweep", sweep, user)
        revoked: list[uuid.UUID | SessionRecord] = [*change.revoked_session_ids, *swept]
        for session in revoked:
            await b16.run(self._record_revoke(session, now))
        self._step("b16_revoke", b16, user)
        if change.before == "invited":
            await invite.run(self._revoke_invite(user, actor, rid))
        self._step("invite_revoke", invite, user)
        steps = {"socket_close": sockets, "session_sweep": sweep, "b16_revoke": b16}
        return tuple(name for name, t in (steps | {"invite_revoke": invite}).items() if t.failures)

    async def _record_revoke(self, session: uuid.UUID | SessionRecord, now: datetime) -> None:
        """One B16 REVOKE; its action writes `auth.session_revoked` (R5)."""
        if isinstance(session, SessionRecord):
            record: SessionRecord | None = session
        else:
            record = await self._rows.find_by_id(str(session))
        if record is None:
            raise LookupError("revoked session row not found")
        await self._chart.revoke(record, now, REVOKED_REASON)

    async def _revoke_invite(
        self, user_id: uuid.UUID, actor: uuid.UUID, rid: uuid.UUID | None
    ) -> None:
        """R6; none open (consumed, so its enrolment refuses a non-`invited` user) is a no-op."""
        try:
            await self._invites.revoke(user_id)
        except InviteNotFound:
            return
        await self._audit.emit(
            "users.invite_revoked", **_who(actor, user_id, rid), reason=REVOKED_REASON
        )

    def _refused(self, result: str, error: UserLifecycleError) -> UserLifecycleError:
        user_lifecycle_total.labels(action="disable", result=result).inc()
        _log().info("users.disable.refused", result=result, request_id=current_request_id())
        return error

    def _step(self, name: str, tally: _Tally, user_id: uuid.UUID) -> None:
        """One line and one count per step; a failure is logged at error, for alerting (R7)."""
        user_lifecycle_steps_total.labels(step=name, outcome=tally.outcome).inc()
        (_log().error if tally.failures else _log().info)(
            "users.disable.step",
            step=name,
            outcome=tally.outcome,
            attempted=tally.attempted,
            error=tally.error,
            target_user_id=str(user_id),
            request_id=current_request_id(),
        )
