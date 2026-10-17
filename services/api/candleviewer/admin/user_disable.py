"""`UserDisableService`: the disable cascade of `DELETE /users/{userId}` and E42-T09's `PATCH`
(E42-T04 S4, #965, SR-029). In order (R7): `users:write`, then a self-target (SR-055), each refusal
audited before any read (U25); the open-position and -order counts (O2: read only); the store's
transaction (S3), whose hook refuses an unacknowledged unknown count (AC7) and writes
`users.disable` ahead (O6). A change that did not commit closes that record with a `failure` one
(C-2.9): `not_applied` if the store never reached its commit, `outcome_unknown` (no after state)
if the commit itself failed, since a driver timeout or a cancellation there may have gone through.
A retry does not settle that: if the commit landed, the revoked ids died with the exception and a
repeat is AC5's no-op, which returns none (see `SqlAlchemyUserLifecycleStore.disable`). The
post-commit steps (sockets, session sweep, B16 REVOKE, invite) are slice S4b's."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from typing import Any, Final, NoReturn, Protocol

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
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.owner_floor import OwnerFloorError
from candleviewer.auth.scopes import ForbiddenError, PrincipalSnapshot, enforce
from candleviewer.auth.step_up import PositionStateProvider
from candleviewer.observability.context import current_request_id
from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories.user_lifecycle import (
    LifecycleAuditHook,
    UserSelfTargetError,
    UserStatusChange,
)

POSITIONS_DECISION: Final = "leave"  # O2: positions and orders stay as they are
CLOSING_TIMEOUT_S: Final = 2.0  # bounds the closing record; the writer may still be slow
NOT_APPLIED: Final = "not_applied"  # a closing record's reason: rolled back, nothing changed
OUTCOME_UNKNOWN: Final = "outcome_unknown"  # ... or its commit failed and may have gone through
_AUDIT_DOWN = (AuditError, RuntimeError)  # `AuditWriter` refusals; RuntimeError: not started


class LifecycleStore(Protocol):  # `SqlAlchemyUserLifecycleStore` (S3): commits once `audit` returns
    async def disable(
        self, user_id: uuid.UUID, *, actor: uuid.UUID, now: datetime, audit: LifecycleAuditHook
    ) -> UserStatusChange | None: ...


class AuditEmitter(Protocol):  # `AuditWriter` (M19): durable, write-ahead
    async def emit(self, action: str, **kwargs: Any) -> None: ...


class OpenOrderCounter(Protocol):  # `None` while unknown (UL-F9: no order has a user yet)
    async def open_order_count(self, user_id: str) -> int | None: ...


@dataclass(frozen=True, slots=True)
class DisableResult:  # `changed` is False for AC5's no-op
    changed: bool


class _AuditRefusedError(Exception):
    """`users.disable` was not made durable; the transaction rolled back."""


@dataclass
class _Ahead:  # what the store's write-ahead hook saw; the store commits as soon as it returns
    change: UserStatusChange | None = None  # set when the hook starts
    returned: bool = False  # set when it returns: a later raise is the commit's, outcome unknown


@dataclass
class _Tally:  # one step's runs, each bounded and isolated so none stops the others (R7)
    timeout_s: float
    attempted: int = 0
    failures: int = 0
    error: str | None = None  # the type only: a message may carry ids

    async def run[T](self, op: Callable[[], Awaitable[T]]) -> T | None:
        """`op` is called inside the bound and the isolation, so one that raises before it returns
        an awaitable fails this run like any other (a built awaitable would be outside both)."""
        self.attempted += 1
        try:
            async with asyncio.timeout(self.timeout_s):
                return await op()
        except Exception as exc:  # isolated by design, a timeout too; `_step` counts and logs it
            self.failures, self.error = self.failures + 1, type(exc).__name__
            return None

    @property
    def outcome(self) -> str:
        return "failed" if self.failures else "ok" if self.attempted else "skipped"


@dataclass(frozen=True, slots=True)
class _OnTarget:  # `enforce` names no object: its `rbac.denied` names the target, as S4's do
    audit: AuditEmitter
    user_id: uuid.UUID

    async def emit(self, action: str, **kwargs: Any) -> None:
        target = {"object_kind": "user", "object_id": str(self.user_id)}
        await self.audit.emit(action, **kwargs | target)


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


async def _count(read: Awaitable[int | None], kind: str, timeout_s: float) -> int | None:
    """Unreadable, or unread within `timeout_s`: unknown (AC7), never a hang."""
    try:
        async with asyncio.timeout(timeout_s):
            return await read
    except Exception as exc:  # a timeout too; the caller then needs the acknowledgement
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
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        count_timeout_s: float = 2.0,  # bounds each count read: a timeout is unknown (AC7)
        closing_timeout_s: float = CLOSING_TIMEOUT_S,
    ) -> None:
        self._store, self._audit, self._clock = store, audit, clock
        self._positions, self._orders = positions, orders
        self._count_timeout_s = count_timeout_s
        self._closing_timeout_s = closing_timeout_s

    async def disable(
        self,
        user_id: uuid.UUID,
        *,
        actor: PrincipalSnapshot,
        acknowledge_unknown_positions: bool = False,
    ) -> DisableResult:
        """Raises a `UserLifecycleError` with nothing changed, or a store failure: rolled back,
        unless the commit itself failed, whose outcome is unknown: if it landed, a retry does not
        settle it, since AC5's no-op returns no ids (see `SqlAlchemyUserLifecycleStore.disable`)."""
        rid, now, uid = _request_uuid(), self._clock(), str(user_id)
        await self._guard(user_id, actor, rid)
        bound = self._count_timeout_s
        positions = await _count(self._positions.open_position_count(uid), "positions", bound)
        orders = await _count(self._orders.open_order_count(uid), "orders", bound)
        unknown = (positions is None or orders is None) and not acknowledge_unknown_positions
        counts = {
            "positions_decision": POSITIONS_DECISION,
            "open_position_count": positions,
            "open_order_count": orders,
            "acknowledged_unknown_positions": acknowledge_unknown_positions,
        }
        change = await self._commit(user_id, actor.user_id, counts, rid, now, unknown)
        if change is None:
            raise self._refused("not_found", UserNotFoundError(uid))
        result = "disabled" if change.changed else "noop"  # a no-op writes no record (AC5)
        user_lifecycle_total.labels(action="disable", result=result).inc()
        return DisableResult(change.changed)

    async def _guard(
        self, user_id: uuid.UUID, actor: PrincipalSnapshot, rid: uuid.UUID | None
    ) -> None:
        try:  # `scope` is `Scope.NONE`: `users:write` is not per account
            denied = _OnTarget(self._audit, user_id)
            await enforce(actor, Permission.USERS_WRITE, emitter=denied, request_id=rid)
        except ForbiddenError as exc:  # `enforce` audited `rbac.denied`
            raise self._refused("forbidden", LifecycleForbiddenError("forbidden_role")) from exc
        except _AUDIT_DOWN as exc:
            raise self._refused("audit_unavailable", LifecycleAuditUnavailableError()) from exc
        if user_id == actor.user_id:
            await self._deny_self(_who(actor.user_id, user_id, rid))

    async def _deny_self(self, who: dict[str, Any]) -> NoReturn:
        """SR-055: refused with an audited 403, or a 503 if the record cannot be written."""
        try:
            await self._audit.emit(
                "rbac.denied",
                **who,
                outcome=AuditOutcome.DENIED,
                severity=Severity.WARNING,
                reason="self_target",
            )
        except _AUDIT_DOWN as exc:
            raise self._refused("audit_unavailable", LifecycleAuditUnavailableError()) from exc
        raise self._refused("self_target", LifecycleForbiddenError("self_target"))

    async def _commit(
        self,
        user_id: uuid.UUID,
        actor: uuid.UUID,
        counts: dict[str, Any],
        rid: uuid.UUID | None,
        now: datetime,
        unknown: bool,
    ) -> UserStatusChange | None:
        ahead = _Ahead()

        async def write_ahead(change: UserStatusChange) -> None:
            if unknown:  # AC7, under the lock, rolled back; a no-op never gets here (AC5)
                refusal = PositionsUnknownError(self._positions.source)
                raise self._refused("positions_unknown", refusal)
            ahead.change = change
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
            ahead.returned = True  # the store commits next (S3): a raise from here on is unknown

        try:
            return await self._store.disable(user_id, actor=actor, now=now, audit=write_ahead)
        except OwnerFloorError as exc:  # refused under the lock, unaudited (UL1-D1)
            raise self._refused("last_owner", LastOwnerError(str(user_id))) from exc
        except UserSelfTargetError:  # the store's own SR-055 check: the same audited 403
            await self._deny_self(_who(actor, user_id, rid))
        except _AuditRefusedError as exc:  # AC8: nothing durable, nothing changed
            raise self._refused("audit_unavailable", LifecycleAuditUnavailableError()) from exc
        except BaseException as exc:
            if ahead.change is not None:  # its record may be durable: close it with what is known
                who = _who(actor, user_id, rid)
                await self._close(who, ahead.change, may_have_committed=ahead.returned)
            if isinstance(exc, WriteAheadTimeout):  # the hook outlived its bound: rolled back
                raise self._refused("audit_unavailable", LifecycleAuditUnavailableError()) from exc
            if isinstance(exc, Exception) and not isinstance(exc, UserLifecycleError):
                user_lifecycle_total.labels(action="disable", result="error").inc()
            raise

    async def _close(
        self, who: dict[str, Any], change: UserStatusChange, *, may_have_committed: bool
    ) -> None:
        """Close a write-ahead `users.disable` whose change did not commit (C-2.9), with what is
        known: `not_applied` and the unchanged state, or, if the commit was sent and failed,
        `outcome_unknown` and no after state, since it may have gone through."""
        before = {"status": change.before, "roles": sorted(change.roles)}
        tally = _Tally(self._closing_timeout_s)
        record = partial(
            self._audit.emit,
            "users.disable",
            **who,
            outcome=AuditOutcome.FAILURE,
            severity=Severity.ERROR,
            reason=OUTCOME_UNKNOWN if may_have_committed else NOT_APPLIED,
            before_state=before,
            after_state=None if may_have_committed else before,
        )
        await tally.run(record)
        self._step("closing_record", tally, who["object_id"])

    def _refused(self, result: str, error: UserLifecycleError) -> UserLifecycleError:
        user_lifecycle_total.labels(action="disable", result=result).inc()
        _log().info("users.disable.refused", result=result, request_id=current_request_id())
        return error

    def _step(self, name: str, tally: _Tally, user_id: uuid.UUID | str) -> None:
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
