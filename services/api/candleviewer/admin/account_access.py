"""`AccountAccessService`: the write behind `PUT /users/{userId}/account-access` (E42-T08 S9c,
#2648), after the route's RBAC, self-target and step-up checks. The open-position count is read
once, bounded (failed or late: unknown, never 0); no open-order count exists yet (UL-F9). The store
refuses an unacknowledged removal while a count is unknown (AC7, #2648 Q2); nothing flattens or
cancels (#965 O2). A commit that changed the live set (an addition too) pushes `grants_changed`
(23-ws-protocol.md §9.5) from a tracked task, which `drain` waits for at shutdown, for at most
`DRAIN_TIMEOUT_S`, and reports what is left (C-2.18). The request waits for the push at most 2 s
(AC3) and never cancels it: cut off inside the WS principal load, a push would leave the live
sockets on their old, wider grants (C-12.4). The WS registry's own bounds end it instead: the
load's deny-all, each socket's send and the audit rows. Each push outcome is logged and counted
(`pushed`, `timeout`, `failed`); a failed push is never rolled back (#965 R7). A store call that
raises anything but one of its refusals, or is cancelled, may have cut off a commit that landed (a
session that fails to close after it), so it pushes too (no change, no revoke).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Mapping
from typing import Any, Final, Literal, Protocol

import structlog

from candleviewer.admin.lifecycle_metrics import user_lifecycle_steps_total
from candleviewer.auth.step_up import PositionStateProvider
from candleviewer.observability.context import current_request_id, spawn
from candleviewer.storage.repositories import account_access as aa

COUNT_TIMEOUT_S: Final = 2.0  # AC7: how long the open-position count may take, then unknown
PUSH_WAIT_S: Final = 2.0  # AC3: how long the request waits for the `revoked` frames
#: How long shutdown waits for the pushes in flight (C-2.18): the principal load's own bound, the
#: longest single wait inside one (`PRINCIPAL_LOAD_TIMEOUT_S` in `ws_wiring`).
DRAIN_TIMEOUT_S: Final = 5.0
PUSH_STEP: Final = "grants_push"  # the push's `step` of `cv_user_lifecycle_steps_total` (R7)
#: The store's refusals: each is raised before any write, so nothing changed and none is pushed.
_REFUSALS: Final = (
    aa.AccessSelfTargetError,
    aa.AccessUserNotFoundError,
    aa.AccessUserNotActiveError,
    aa.AccessUnknownAccountError,
    aa.AccessBusyError,
    aa.AccessPositionsUnknownError,
    aa.AccessAuditUnavailableError,
)


class GrantStore(Protocol):  # `SqlAlchemyAccountAccessStore`
    async def replace_grants(
        self,
        user_id: uuid.UUID,
        grants: Mapping[uuid.UUID, aa.AccessLevel],
        *,
        actor_user_id: uuid.UUID,
        request_id: uuid.UUID | None = None,
        removal: aa.RemovalContext | None = None,
        actor_ip: str | None = None,
        session_id: uuid.UUID | None = None,
    ) -> aa.AccessChange: ...


class GrantsNotifier(Protocol):  # `WsEvents`, which admin may not import (CONSTITUTION §3)
    async def grants_changed(self, user_id: uuid.UUID) -> None: ...


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


def _request_uuid() -> uuid.UUID | None:  # `CorrelationMiddleware` binds a UUID4, if any
    return uuid.UUID(rid) if (rid := current_request_id()) else None


async def _count(read: Awaitable[int | None], timeout_s: float) -> int | None:
    try:
        async with asyncio.timeout(timeout_s):
            return await read
    except Exception as exc:  # a timeout too: unknown, never 0 and never a hang
        _log().warning("account access positions unreadable", error=type(exc).__name__)
        return None


# TODO(#2648): alert on `grants_push` outcomes `failed` and `timeout` (R7: counted and alerted),
# with the lifecycle alert rule of E42-T04's observability slice (#965), which also serves the
# counter.
def _pushed(
    user_id: uuid.UUID, outcome: Literal["pushed", "timeout", "failed"], error: str | None = None
) -> None:
    """One count and one line per push outcome. `timeout`: the request stopped waiting (AC3
    missed) while the push goes on, to be counted again when it ends `pushed` or `failed`."""
    user_lifecycle_steps_total.labels(step=PUSH_STEP, outcome=outcome).inc()
    log = _log()
    level = {"pushed": log.info, "timeout": log.warning, "failed": log.error}[outcome]
    level("account access push", outcome=outcome, error=error, target_user_id=str(user_id))


class AccountAccessService:
    def __init__(
        self,
        store: GrantStore,
        notifier: GrantsNotifier,
        *,
        positions: PositionStateProvider,
        count_timeout_s: float = COUNT_TIMEOUT_S,  # a count read past it is unknown (AC7)
        push_wait_s: float = PUSH_WAIT_S,
        drain_timeout_s: float = DRAIN_TIMEOUT_S,
    ) -> None:
        self._store, self._notifier, self._positions = store, notifier, positions
        self._count_timeout_s, self._push_wait_s = count_timeout_s, push_wait_s
        self._drain_timeout_s = drain_timeout_s
        self._pushes: set[asyncio.Task[None]] = set()  # tracked: see `drain`

    async def replace(
        self,
        user_id: uuid.UUID,
        grants: Mapping[uuid.UUID, aa.AccessLevel],
        *,
        actor_user_id: uuid.UUID,
        acknowledge_unknown_positions: bool,
        actor_ip: str | None = None,
        session_id: uuid.UUID | None = None,
    ) -> aa.AccessChange:
        """Raises the store's refusals (nothing changed) or its failure. `actor_ip` and
        `session_id` name the caller in the change's audit records (C-2.9)."""
        rid = _request_uuid()  # first: a bad id must not strand the count read built below
        read = self._positions.open_position_count(str(user_id))
        removal = aa.RemovalContext(
            open_position_count=await _count(read, self._count_timeout_s),
            acknowledged_unknown_positions=acknowledge_unknown_positions,
        )
        try:
            change = await self._store.replace_grants(
                user_id,
                grants,
                actor_user_id=actor_user_id,
                request_id=rid,
                removal=removal,
                actor_ip=actor_ip,
                session_id=session_id,
            )
        except _REFUSALS:
            raise  # raised before any write: nothing changed, so nothing to re-evaluate
        except (Exception, asyncio.CancelledError):
            self._push(user_id)  # whatever cut the call off, the commit may have landed (C-12.4)
            raise
        if change.changed:
            # `wait` never cancels the push, on its timeout or on this request's cancellation.
            done, _ = await asyncio.wait({self._push(user_id)}, timeout=self._push_wait_s)
            if not done:
                _pushed(user_id, "timeout")
        return change

    def _push(self, user_id: uuid.UUID) -> asyncio.Task[None]:
        task = spawn(self._notify(user_id), name="account-access-push")
        self._pushes.add(task)
        task.add_done_callback(self._pushes.discard)
        return task

    async def _notify(self, user_id: uuid.UUID) -> None:
        """No bound of its own (see the module docstring); never raises (R7)."""
        try:
            await self._notifier.grants_changed(user_id)
        except Exception as exc:
            _pushed(user_id, "failed", type(exc).__name__)
        else:
            _pushed(user_id, "pushed")

    async def drain(self) -> int:
        """Shutdown: wait up to `drain_timeout_s` for the pushes in flight; the WS registry's
        bounds end each, but a hung one must not hold the shutdown (C-2.18). Returns how many are
        still running, logged: they are never cancelled here, and the gateway has stopped, so no
        live socket is left on their old grants."""
        if not self._pushes:
            return 0
        _, pending = await asyncio.wait(set(self._pushes), timeout=self._drain_timeout_s)
        if pending:
            _log().warning("account access pushes still in flight at shutdown", pushes=len(pending))
        return len(pending)
