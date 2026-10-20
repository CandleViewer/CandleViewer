"""`/alerts/deliveries*` - the alert delivery inbox (E40-T04) - contract: `22-api-openapi.yaml`
listAlertDeliveries, ackAlertDelivery, ackAllAlertDeliveries, reportAlertDesktopOutcome.

Ownership is the delivery row's `user_id`, never a client-supplied user (`scope: self`). The
permission check comes first (403 before any lookup, `alerts_http.caller`); then an unknown or
foreign delivery, or a list filtered on a foreign `alert_id`, is a 404 - and the foreign case is
audited (`alert.denied`) before the refusal, so existence is never disclosed by the answer.
Delivery ids are sequential, so those denial records are budgeted per caller (`DenialBudget`):
probing other users' ids cannot flood the audit log, and what the budget holds back is carried by
the caller's next denial record.

- **ack**: only `sent -> acked` is legal. Acking an acked delivery returns it unchanged (same
  `acked_at`); a delivery that never reached `sent` has nothing to acknowledge and is returned
  unchanged too. The attempted transition is audited write-ahead (C-2.9); the conditional update
  may then lose to another session of the same user, whose answer is returned.
- **ack-all**: never one unbounded statement - batches of `ACK_ALL_BATCH` rows, at most
  `ACK_ALL_MAX_BATCHES` per request; a client whose `unacked_count` is still above 0 calls again
  (the continuation). With anything to acknowledge, one record is written first, naming the
  request's scope and bound; the count reached is the response's.
- **desktop-outcome**: the Electron shell reports `shown` (`queued -> sent`) or `blocked` /
  `failed` (`queued -> failed` plus ONE in-app channel-failure notice, one transaction). A
  report for a delivery already settled is a 204 no-op; a non-desktop delivery is a 422. The
  audit record carries the outcome and the OS permission the shell observed.

`on_change` receives the ids of the deliveries a request changed, after the change is committed
(the `alerts` WS topic publishes them as deltas). It is told, never asked: each call is bounded by
`CHANGE_HOOK_TIMEOUT_S` (an ack-all calls it once per batch), and its failure is logged and never
fails the request, whose change is already durable.

The response never carries the delivery `context` or anything from the alert's SECRET webhook
columns: `AlertDelivery` is built field by field (`dump`).
"""

# No `from __future__ import annotations`: FastAPI must evaluate `Depends(<closure>)` in the
# handler signatures at definition time (string annotations cannot see the closures).

import asyncio
import re
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from candleviewer.alerts.dispatcher import Metric
from candleviewer.api.alerts import READ, WRITE
from candleviewer.api.alerts_http import AuditEmitter, Problem, ProblemRoute, Resolver, caller
from candleviewer.audit.models import AuditOutcome
from candleviewer.rules.manager import Actor

#: SR-026: the declared query parameters of `listAlertDeliveries`; any other key is refused.
LIST_DELIVERIES_QUERY = frozenset(
    {"cursor", "limit", "status", "alert_id", "unacked_only", "from", "to"}
)
#: ack-all bounds (ticket DoS note): rows per UPDATE, UPDATEs per request.
ACK_ALL_BATCH = 500
ACK_ALL_MAX_BATCHES = 10
#: How long a request waits on one `on_change` call once its change is committed.
CHANGE_HOOK_TIMEOUT_S = 2.0
#: `alert.denied` records per caller per window, and the callers tracked: delivery ids are
#: sequential, so probing them must not flood the audit log (C-2.9, C-12.8; #3917 review).
DENIALS_PER_WINDOW = 20
DENIAL_WINDOW_S = 3600.0
MAX_TRACKED_CALLERS = 1024
_INT64_MAX = 2**63 - 1
_SYMBOL = re.compile(r"^[A-Z0-9]{2,20}USDT$")
DeliveryStatus = Literal["queued", "sent", "failed", "suppressed", "acked"]
#: The ids of the deliveries a request changed (the dispatcher's `on_change` shape).
OnChange = Callable[[Sequence[int]], Awaitable[None]]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class DeliveryView(Protocol):
    """The `alert_deliveries` columns the inbox reads (the repository's `DeliveryRow` fits; the
    API never imports the SQL module, ADR-0003)."""

    @property
    def id(self) -> int: ...
    @property
    def alert_id(self) -> str: ...
    @property
    def user_id(self) -> str | None: ...
    @property
    def channel(self) -> str: ...
    @property
    def status(self) -> str: ...
    @property
    def title(self) -> str: ...
    @property
    def body(self) -> str: ...
    @property
    def context(self) -> dict[str, Any]: ...
    @property
    def error_message(self) -> str | None: ...
    @property
    def queued_at(self) -> datetime: ...
    @property
    def acked_at(self) -> datetime | None: ...
    @property
    def severity(self) -> str | None: ...


class DeliveryPage(Protocol):
    """A keyset page (`storage.repositories.alerts.Page` fits; read-only, so covariant)."""

    @property
    def items(self) -> Sequence[DeliveryView]: ...
    @property
    def next_cursor(self) -> str | None: ...


class AlertDeliveryStore(Protocol):
    """What the inbox needs (`SqlAlchemyAlertDeliveryRepository` satisfies it)."""

    async def get(self, delivery_id: int) -> DeliveryView | None: ...
    async def alert_owner(self, alert_id: str) -> str | None: ...
    async def unacked_count(self, user_id: str) -> int: ...
    async def list_page(
        self,
        *,
        user_id: str,
        alert_id: str | None = None,
        status: str | None = None,
        unacked_only: bool = False,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> DeliveryPage: ...
    async def ack(self, delivery_id: int, user_id: str) -> DeliveryView | None: ...
    async def ack_all(self, user_id: str, cap: int = 1000) -> list[int]: ...
    async def report_desktop(
        self, delivery_id: int, *, user_id: str, error: str | None, notice_title: str
    ) -> DeliveryView | None: ...


@dataclass(slots=True)
class _Caller:
    written: deque[float] = field(default_factory=deque)  # record times inside the window
    held: int = 0  # denials not recorded since the caller's last record


class DenialBudget:
    """At most `per_window` `alert.denied` records per caller in any `window_s`.

    Past it a denial is counted, not written, and the caller's next record carries the count
    (`after_state.suppressed_before`), so nothing is dropped while the caller keeps probing; a run
    of held denials is logged with its running count at 1, 10, 100, ... (never one line per
    denial). A record whose write fails gives its slot and its count back (`restore`). State is
    bounded (C-2.18): `max_callers` entries, least recently used evicted first; an evicted
    caller's held count is logged rather than lost silently. Process-local, single event loop
    (no lock needed).
    """

    def __init__(
        self,
        per_window: int = DENIALS_PER_WINDOW,
        window_s: float = DENIAL_WINDOW_S,
        max_callers: int = MAX_TRACKED_CALLERS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if per_window < 1 or window_s <= 0 or max_callers < 1:
            raise ValueError("denial budget bounds must be positive")
        self._per, self._window, self._max, self._clock = per_window, window_s, max_callers, clock
        self._callers: OrderedDict[str, _Caller] = OrderedDict()

    def __len__(self) -> int:
        return len(self._callers)

    def admit(self, user_id: str) -> int | None:
        """The held count this denial's record carries; None when it is held instead."""
        now = self._clock()
        entry = self._callers.get(user_id)
        if entry is None:
            entry = self._callers[user_id] = _Caller()
            self._evict()
        else:
            self._callers.move_to_end(user_id)
        while entry.written and now - entry.written[0] >= self._window:
            entry.written.popleft()
        if len(entry.written) < self._per:
            entry.written.append(now)
            carried, entry.held = entry.held, 0
            return carried
        entry.held += 1
        if _is_power_of_ten(entry.held):
            _log().warning("alert_denied_audit_held", user_id=user_id, held=entry.held,
                           per_window=self._per)  # fmt: skip
        return None

    def restore(self, user_id: str, carried: int) -> None:
        """The record `admit` let through was not written: give its slot back and hold its count
        again, this denial's own included, for the caller's next record."""
        entry = self._callers.get(user_id)
        if entry is None:  # evicted meanwhile: the count goes to the log, not nowhere
            _log().warning("alert_denied_audit_held_evicted", user_id=user_id, held=carried + 1)
            return
        if entry.written:
            entry.written.pop()
        entry.held += carried + 1

    def _evict(self) -> None:
        while len(self._callers) > self._max:
            user_id, gone = self._callers.popitem(last=False)
            if gone.held:
                _log().warning("alert_denied_audit_held_evicted", user_id=user_id, held=gone.held)


def _is_power_of_ten(n: int) -> bool:
    while n >= 10 and n % 10 == 0:
        n //= 10
    return n == 1


def _iso(d: datetime | None) -> str | None:
    return None if d is None else d.isoformat()


def _utc(d: datetime | None, name: str) -> datetime | None:
    """A window bound in UTC: one without an offset is read as UTC (RFC 3339 UTC, `From`/`To`);
    one whose offset has no UTC instant (year 1 at +14:00) is the shared 422, never a bind error
    in the driver."""
    if d is None:
        return None
    try:
        return (d if d.tzinfo is not None else d.replace(tzinfo=UTC)).astimezone(UTC)
    except OverflowError:
        raise Problem(422, "validation_failed", "Invalid query", f"{name} is out of range.",
                      errors=[{"field": name, "rule": "datetime_range",
                               "message": "no UTC instant"}]) from None  # fmt: skip


def dump(row: DeliveryView) -> dict[str, Any]:
    """`AlertDelivery`: `message` is the `body`, falling back to `title`; `symbol` is the
    firing's symbol when it is one (a storm summary names several, so it has none)."""
    symbol = row.context.get("symbol") if isinstance(row.context, dict) else None
    return {
        "id": row.id, "alert_id": row.alert_id, "channel": row.channel, "status": row.status,
        "severity": row.severity or "info", "title": row.title,
        "message": row.body or row.title,
        "symbol": symbol if isinstance(symbol, str) and _SYMBOL.match(symbol) else None,
        "fired_at": row.queued_at.isoformat(), "acked_at": _iso(row.acked_at),
        "error": row.error_message,
    }  # fmt: skip


class _DesktopOutcome(BaseModel):
    """The report-back body; closed (`additionalProperties: false`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    outcome: Literal["shown", "blocked", "failed"]
    permission: Literal["granted", "denied", "default", "unsupported"]


def _not_found() -> Problem:
    return Problem(404, "not_found", "Not found", "No such alert delivery.")


def _no_alert() -> Problem:
    return Problem(404, "not_found", "Not found", "No such alert.")


def make_alert_deliveries_router(
    store_provider: Callable[[], AlertDeliveryStore | None],
    actor_resolver: Resolver | None,
    audit: AuditEmitter,
    *,
    metric: Metric | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    on_change: OnChange | None = None,
    denials: DenialBudget | None = None,
) -> APIRouter:
    """Mount before the `/alerts` CRUD router: its `/alerts/{alertId}` would otherwise take
    `GET /alerts/deliveries` and refuse `deliveries` as a malformed alert id. *metric* is the
    dispatcher's `cv_alert_delivery_*` sink: a desktop delivery settles here, not there."""
    router = APIRouter(tags=["alerts"], route_class=ProblemRoute)
    budget = DenialBudget() if denials is None else denials

    def store() -> AlertDeliveryStore:
        s = store_provider()
        if s is None:
            raise Problem(503, "service_unavailable", "Unavailable", "alerts store unavailable")
        return s

    async def changed(ids: Sequence[int]) -> None:
        if not ids or on_change is None:
            return
        try:
            async with asyncio.timeout(CHANGE_HOOK_TIMEOUT_S):
                await on_change(ids)
        except TimeoutError:  # the change is committed; a lost delta is the topic's to repair
            _log().warning("alert_inbox_change_hook_timeout", count=len(ids))
        except Exception:
            _log().exception("alert_inbox_change_hook_failed", count=len(ids))

    async def _audit(action: str, actor: Actor, kind: str, object_id: str | None,
                     **fields: Any) -> None:  # fmt: skip
        await audit.emit(
            action, actor_label=actor.user_id, actor_user_id=actor.user_id,
            object_kind=kind, object_id=object_id, **fields,
        )  # fmt: skip

    async def _deny(actor: Actor, kind: str, object_id: str, reason: str) -> None:
        """A foreign id: audited within the caller's denial budget (`DenialBudget`)."""
        carried = budget.admit(actor.user_id)
        if carried is None:
            return
        extra = {"after_state": {"suppressed_before": carried}} if carried else {}
        try:
            await _audit("alert.denied", actor, kind, object_id, outcome=AuditOutcome.DENIED,
                         reason=reason, **extra)  # fmt: skip
        except BaseException:  # not written: its slot and its count go back to the budget
            budget.restore(actor.user_id, carried)
            raise

    reader = caller(actor_resolver, READ, LIST_DELIVERIES_QUERY)
    writer = caller(actor_resolver, WRITE)

    async def owned(
        deliveryId: Annotated[int, Path(ge=1, le=_INT64_MAX)],
        actor: Annotated[Actor, Depends(writer)],
    ) -> tuple[Actor, DeliveryView]:
        """`scope: self`: someone else's delivery is indistinguishable from a missing one."""
        row = await store().get(deliveryId)
        if row is None:
            raise _not_found()
        if row.user_id != actor.user_id:
            await _deny(actor, "alert_delivery", str(deliveryId), "delivery owned by another user")
            raise _not_found()
        return actor, row

    @router.get("/alerts/deliveries")
    async def list_deliveries(
        actor: Annotated[Actor, Depends(reader)],
        cursor: Annotated[str | None, Query(max_length=512)] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        status: DeliveryStatus | None = None,
        alert_id: UUID | None = None,
        unacked_only: bool = False,
        from_ts: Annotated[datetime | None, Query(alias="from")] = None,
        to: datetime | None = None,
    ) -> Response:
        s = store()
        aid = None if alert_id is None else str(alert_id)
        if aid is not None:
            owner = await s.alert_owner(aid)
            if owner is None:
                raise _no_alert()
            if owner != actor.user_id:
                await _deny(actor, "alert", aid, "alert owned by another user")
                raise _no_alert()
        try:
            page = await s.list_page(
                user_id=actor.user_id, alert_id=aid, status=status,
                unacked_only=unacked_only, from_ts=_utc(from_ts, "from"), to_ts=_utc(to, "to"),
                cursor=cursor, limit=limit,
            )  # fmt: skip
        except ValueError:
            raise Problem(400, "validation_failed", "Bad request", "invalid cursor") from None
        items = [dump(r) for r in page.items]
        meta = {"next_cursor": page.next_cursor, "has_more": page.next_cursor is not None,
                "count": len(items)}  # fmt: skip
        return JSONResponse({"items": items, "meta": meta})

    # Declared before `/{deliveryId}/ack`: different segment counts, but keep the literal first.
    @router.post("/alerts/deliveries/ack-all")
    async def ack_all(actor: Annotated[Actor, Depends(writer)]) -> Response:
        s = store()
        pending = await s.unacked_count(actor.user_id)
        if not pending:  # nothing sent and unacknowledged: no change, no record
            return JSONResponse({"acknowledged": 0})
        # Write-ahead (C-2.9): the record names the request's scope and bound before any batch
        # commits, so no acknowledgement goes unrecorded; the count reached is the response's.
        await _audit("alert.deliveries_acked", actor, "alert_delivery", None,
                     before_state={"status": "sent", "unacked": pending},
                     after_state={"status": "acked", "scope": "all_sent",
                                  "max": ACK_ALL_BATCH * ACK_ALL_MAX_BATCHES})  # fmt: skip
        total = 0
        for _ in range(ACK_ALL_MAX_BATCHES):
            ids = await s.ack_all(actor.user_id, cap=ACK_ALL_BATCH)
            total += len(ids)
            await changed(ids)
            if len(ids) < ACK_ALL_BATCH:
                break
        return JSONResponse({"acknowledged": total})

    @router.post("/alerts/deliveries/{deliveryId}/ack")
    async def ack(got: Annotated[tuple[Actor, DeliveryView], Depends(owned)]) -> Response:
        actor, row = got
        if row.status != "sent":  # acked already (same acked_at), or nothing to acknowledge
            return JSONResponse(dump(row))
        await _audit("alert.delivery_acked", actor, "alert_delivery", str(row.id),
                     before_state={"status": "sent"},
                     after_state={"status": "acked"})  # fmt: skip
        new = await store().ack(row.id, actor.user_id)
        if new is not None:
            await changed((new.id,))
        else:  # another session of the same user won the conditional update (and told the topic)
            new = await store().get(row.id)
            if new is None:
                raise _not_found()
        return JSONResponse(dump(new))

    @router.post("/alerts/deliveries/{deliveryId}/desktop-outcome")
    async def desktop_outcome(
        request: Request, got: Annotated[tuple[Actor, DeliveryView], Depends(owned)]
    ) -> Response:
        actor, row = got
        body = await _outcome(request)
        if row.channel != "desktop":
            raise Problem(422, "validation_failed", "Invalid report",
                          "Only a desktop delivery takes a desktop outcome.",
                          errors=[{"field": "deliveryId", "rule": "not_desktop_delivery",
                                   "message": "not a desktop delivery"}])  # fmt: skip
        if row.status != "queued":  # settled already: a repeated report changes nothing
            return Response(status_code=204)
        error = (
            None
            if body.outcome == "shown"
            else f"desktop notification {body.outcome} (OS permission: {body.permission})"
        )
        after = {"status": "sent" if error is None else "failed", "outcome": body.outcome,
                 "permission": body.permission}  # fmt: skip
        await _audit("alert.desktop_outcome", actor, "alert_delivery", str(row.id),
                     before_state={"status": "queued"}, after_state=after)  # fmt: skip
        new = await store().report_desktop(
            row.id, user_id=actor.user_id, error=error,
            notice_title=f"desktop delivery failed: {row.title}"[:200],
        )  # fmt: skip
        if new is not None:
            await changed((new.id,))  # the topic finds a failure's notice row itself
            if metric is not None:
                metric("cv_alert_delivery_total", ("desktop", new.status)).inc()
                if new.status == "sent":
                    lat = max((now() - new.queued_at).total_seconds(), 0.0)
                    metric("cv_alert_delivery_latency_seconds", ("desktop",)).observe(lat)
        return Response(status_code=204)

    return router


async def _outcome(request: Request) -> _DesktopOutcome:
    try:
        return _DesktopOutcome.model_validate(await request.json())
    except ValidationError as exc:
        errs = exc.errors(include_url=False, include_input=False)[:20]
        raise Problem(422, "validation_failed", "Invalid report", "The report body is invalid.",
                      errors=[{"field": ".".join(map(str, e["loc"])), "rule": e["type"],
                               "message": e["msg"]} for e in errs]) from None  # fmt: skip
    except ValueError:
        raise Problem(422, "validation_failed", "Invalid report", "Body is not JSON.") from None


__all__ = [
    "ACK_ALL_BATCH",
    "ACK_ALL_MAX_BATCHES",
    "CHANGE_HOOK_TIMEOUT_S",
    "DENIALS_PER_WINDOW",
    "DENIAL_WINDOW_S",
    "LIST_DELIVERIES_QUERY",
    "AlertDeliveryStore",
    "DeliveryView",
    "DenialBudget",
    "OnChange",
    "dump",
    "make_alert_deliveries_router",
]
