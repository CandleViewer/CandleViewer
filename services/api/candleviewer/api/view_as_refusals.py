"""View-as refusal records (#3085; 22-api-openapi.yaml "View-as session", "Refusal records").

Each refusal (a write or a held session's request, a refused start, a WebSocket action frame) is
counted in `auth_view_as_refused_total{reason}` first, then writes one `admin.view_as_refused`
ahead of its answer: outcome `denied`, severity `warning`, reason the problem code, actor the
viewer and the viewer's session, never the target. The records go through the "Audit budget"
mechanism of `queryAuditLog` in an instance of their own, one hourly cap per viewer for all, the
Owner's too (`view_as_refusal_budget_per_hour`, Q7): over it nothing is written and the count is
carried by the viewer's next record, or the flush task's summary (`suppressed_summary`, object
`view_as`). A REST refusal whose due record cannot be written raises `ViewAsRefusalUnrecorded`
and answers `503 audit_unavailable` (#3223 item 2). A WebSocket frame gets its `err` anyway (23
section 9.6), so its refusal is then counted into the viewer's next record or summary, as one
over the cap is. Nothing sets `Retry-After` (#3223 item 1). The object (Q8), never a body, a
payload, a session id in a state or raw input: the operation's contract path template
(`after_state` `{method, path}`, as `auth.csrf_refused` records it), the frame type (`(invalid)`
off `FRAME_TYPE`, with its length alone), or the requested user (`before_state` the held
context, for `view_as_active`). Inert until #3085's guard, sockets and start call it; the app
builds it, and the lifespan runs its flush task.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Literal, Protocol, get_args
from uuid import UUID

from candleviewer.api.audit_budget import (
    WRITE_TIMEOUT_S,
    AuditBudgetFlushTask,
    AuditRecordBudget,
    BudgetActor,
    BudgetWriteFailed,
)
from candleviewer.api.csrf import bounded_method
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.auth.metrics import auth_view_as_refused_total
from candleviewer.auth.view_as import ViewAsRequestContext, ViewAsState

VIEW_AS_REFUSED: Final = "admin.view_as_refused"
SUMMARY_KIND: Final = "view_as"  # the object of the budget's out-of-cap summary records
#: `api.csrf.match_operation`'s template for a path no operation declares.
UNMATCHED: Final = "(unmatched)"
#: A refused frame's object is its type when it has this form, else `INVALID_FRAME_TYPE`.
FRAME_TYPE: Final = re.compile(r"[a-z][a-z0-9_.]{0,63}")
INVALID_FRAME_TYPE: Final = "(invalid)"
OperationReason = Literal["view_as_read_only", "view_as_expired"]
StartReason = Literal[
    "view_as_active", "view_as_self_target", "not_found", "conflict", "view_as_owner_target"
]
#: The problem codes a refusal of each object carries (Q9): the record's reason and the metric's
#: label, whose closed set (`auth.metrics.VIEW_AS_REFUSAL_REASONS`) is their union.
REASONS_BY_KIND: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "operation": frozenset(get_args(OperationReason)),
        "ws_frame": frozenset({"view_as_read_only"}),
        "user": frozenset(get_args(StartReason)),
    }
)


class ViewAsRefusalUnrecorded(BudgetWriteFailed):
    """A due `admin.view_as_refused` could not be written: a REST refusal then answers
    `503 audit_unavailable`, not the audit routes' `store_unavailable`, and nothing changes."""


class _Emitter(Protocol):
    @property
    def emit(self) -> Callable[..., Awaitable[None]]: ...


@dataclass(frozen=True, slots=True)
class Viewer:
    """The caller of a refused start, outside any context; a viewing request or socket passes its
    `ViewAsRequestContext`. Either names the viewer and the viewer's session, never the target."""

    viewer_user_id: UUID
    viewer_session_id: UUID
    viewer_label: str  # the viewer's username

    def __post_init__(self) -> None:
        if not self.viewer_label:  # as `ViewAsRequestContext`'s: every record names its actor
            raise ValueError("a viewer has a label")


_Viewer = ViewAsRequestContext | Viewer


class ViewAsRefusalRecorder:
    """Writes view-as refusal records within the viewers' own budget (`budget`), whose flush task
    (`flush`) the lifespan runs as it runs the audit routes' (module docstring). `operations`:
    the contract's (`declared_operations(spec)`), whose templates name a refused operation."""

    def __init__(
        self,
        audit: _Emitter,
        *,
        operations: Iterable[tuple[str, str]],
        per_hour: int = 120,
        tracked_users: int = 1024,
        inflight_cap: int = 64,
        flush_seconds: float = 300.0,
        write_timeout_s: float = WRITE_TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._audit = audit
        self._templates = frozenset(template for _, template in operations) | {UNMATCHED}
        # One cap for every viewer, the Owner's included (Q7), and no reads to count.
        self.budget = AuditRecordBudget(
            per_hour=per_hour,
            owner_per_hour=per_hour,
            tracked_users=tracked_users,
            inflight_cap=inflight_cap,
            flush_seconds=flush_seconds,
            write_timeout_s=write_timeout_s,
            clock=clock,
            read_action=None,
            denial_action=VIEW_AS_REFUSED,
            object_kind=SUMMARY_KIND,
        )
        self.flush = AuditBudgetFlushTask(self.budget, audit)

    async def refuse_operation(
        self,
        viewer: _Viewer,
        reason: OperationReason,
        *,
        method: str,
        template: str,
        ip: str | None = None,
        request_id: str | UUID | None = None,
    ) -> bool:
        """A REST refusal of `method` on `template`, the operation's contract path template as
        `api.csrf.match_operation` gives it. Any other string, a raw path above all, is the
        caller's error (`ValueError`, which never echoes it): a path's ids never land."""
        if template not in self._templates:
            raise ValueError("a refused operation is named by its contract path template")
        after = {"method": bounded_method(method), "path": template}
        return await self._record_refusal(
            viewer, reason, "operation", template, after_state=after, ip=ip, request_id=request_id
        )

    async def refuse_frame(
        self,
        viewer: _Viewer,
        frame_type: str,
        *,
        ip: str | None = None,
        request_id: str | UUID | None = None,
    ) -> bool:
        """A refused WebSocket action frame: the object is its type, never its payload, and a type
        off `FRAME_TYPE` is `INVALID_FRAME_TYPE`, with its length alone. 23 section 9.6 sends the
        `err` whatever the record does, so this never raises for it. True: written. False:
        counted into the viewer's next record or summary, over the cap or unwritable."""
        after: dict[str, Any] | None = None
        obj = frame_type
        if not FRAME_TYPE.fullmatch(frame_type):  # the client's own: never stored raw
            obj, after = INVALID_FRAME_TYPE, {"frame_type_len": len(frame_type)}
        try:
            return await self._record_refusal(
                viewer,
                "view_as_read_only",
                "ws_frame",
                obj,
                after_state=after,
                ip=ip,
                request_id=request_id,  # the socket's upgrade id (#3990)
                answered=True,
            )
        except ViewAsRefusalUnrecorded:  # counted by the budget, as `answered` asks
            return False

    async def refuse_start(
        self,
        viewer: _Viewer,
        reason: StartReason,
        *,
        target_user_id: UUID,
        held: ViewAsState | None = None,
        ip: str | None = None,
        request_id: str | UUID | None = None,
    ) -> bool:
        """A refused `startViewAs`: the object is the requested user. `held`, the context the
        session already holds, goes with `view_as_active` and only with it."""
        if (reason == "view_as_active") != (held is not None):
            raise ValueError("the held context goes with view_as_active, and only with it")
        before = None
        if held is not None:
            before = {
                "target_user_id": str(held.target_user_id),
                "started_at": held.started_at.isoformat(),
                "expires_at": held.expires_at.isoformat(),
            }
        target = str(target_user_id)
        return await self._record_refusal(
            viewer, reason, "user", target, before_state=before, ip=ip, request_id=request_id
        )

    async def _record_refusal(
        self,
        viewer: _Viewer,
        reason: str,
        object_kind: str,
        object_id: str,
        *,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        ip: str | None = None,
        request_id: str | UUID | None = None,
        answered: bool = False,
    ) -> bool:
        """Count the refusal, then record it within the viewer's budget. True: written, ahead of
        the answer. False: over the cap, counted (`suppressed`). `ViewAsRefusalUnrecorded`: due
        and unwritable, then also counted if the refusal is `answered` all the same. A reason its
        object cannot carry is the caller's error (`ValueError`). Only the wrappers above call
        it, so they alone shape a record's object and states."""
        if reason not in REASONS_BY_KIND.get(object_kind, frozenset()):
            raise ValueError(f"a {object_kind!r} refusal never carries {reason!r}")
        auth_view_as_refused_total.labels(reason=reason).inc()  # first, whatever the budget says
        fields: dict[str, Any] = {
            "actor_label": viewer.viewer_label,
            "actor_user_id": viewer.viewer_user_id,
            "actor_ip": ip,
            "session_id": viewer.viewer_session_id,
            "object_kind": object_kind,
            "object_id": object_id,
            "outcome": AuditOutcome.DENIED,
            "severity": Severity.WARNING,
            "reason": reason,
            "before_state": before_state,
            "after_state": after_state,
            "request_id": request_id,
        }
        # Keyed by the viewer, across sessions. One cap applies to all (Q7), so every viewer is
        # tracked in the user map (`owner=False`), never the few entries kept apart for Owners.
        key, label = str(viewer.viewer_user_id), viewer.viewer_label
        actor = BudgetActor(key, label, viewer.viewer_user_id, owner=False)
        try:
            return await self.budget.write_denial(
                actor, self._audit, fields, count_if_unwritten=answered
            )
        except BudgetWriteFailed as exc:
            raise ViewAsRefusalUnrecorded(str(exc)) from exc
