"""`/alerts/deliveries*` - the alert delivery inbox (E40-T04) - contract: `22-api-openapi.yaml`
listAlertDeliveries, ackAlertDelivery, ackAllAlertDeliveries, reportAlertDesktopOutcome.

Ownership is the delivery row's `user_id`, never a client-supplied user (`scope: self`). The
permission check comes first (403 before any lookup); then an unknown or foreign delivery, or a
list filtered on a foreign `alert_id`, is a 404 - and the foreign case is audited
(`alert.denied`) before the refusal, so existence is never disclosed.

- **ack**: only `sent -> acked` is legal. Acking an acked delivery returns it unchanged (same
  `acked_at`); a delivery that never reached `sent` has nothing to acknowledge and is returned
  unchanged too. Audited (write-ahead, C-2.9) only when the state changes.
- **ack-all**: never one unbounded statement - batches of `ACK_ALL_BATCH` rows, at most
  `ACK_ALL_MAX_BATCHES` per request; a client whose `unacked_count` is still above 0 calls again
  (the continuation). One audit record per call that acknowledged anything, with the count.

`on_change` receives the ids of the deliveries a request changed, after the change is committed
(the `alerts` WS topic publishes them as deltas). It is told, never asked: its failure is logged
and never fails the request, whose change is already durable.
- **desktop-outcome**: the Electron shell reports `shown` (`queued -> sent`) or `blocked` /
  `failed` (`queued -> failed` plus ONE in-app channel-failure notice, one transaction). A
  report for a delivery already settled is a 204 no-op; a non-desktop delivery is a 422. The
  audit record carries the outcome and the OS permission the shell observed.

The response never carries the delivery `context` or anything from the alert's SECRET webhook
columns: `AlertDelivery` is built field by field (`dump`).
"""

# No `from __future__ import annotations`: FastAPI must evaluate `Depends(<closure>)` in the
# handler signatures at definition time (string annotations cannot see the closures).

import inspect
import re
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Protocol
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from candleviewer.alerts.dispatcher import Metric
from candleviewer.api.alerts import READ, WRITE, _Problem, _ProblemRoute, _Refused
from candleviewer.api.query_allowlist import undeclared_query_refusal
from candleviewer.audit.models import AuditOutcome
from candleviewer.rules.manager import Actor

#: SR-026: the declared query parameters of `listAlertDeliveries`; any other key is refused.
LIST_DELIVERIES_QUERY = frozenset(
    {"cursor", "limit", "status", "alert_id", "unacked_only", "from", "to"}
)
#: ack-all bounds (ticket DoS note): rows per UPDATE, UPDATEs per request.
ACK_ALL_BATCH = 500
ACK_ALL_MAX_BATCHES = 10
_INT64_MAX = 2**63 - 1
_SYMBOL = re.compile(r"^[A-Z0-9]{2,20}USDT$")
DeliveryStatus = Literal["queued", "sent", "failed", "suppressed", "acked"]
#: The ids of the deliveries a request changed (the dispatcher's `on_change` shape).
OnChange = Callable[[Sequence[int]], Awaitable[None]]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class DeliveryRow(Protocol):
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
    def items(self) -> Sequence[DeliveryRow]: ...
    @property
    def next_cursor(self) -> str | None: ...


class AlertDeliveryStore(Protocol):
    """What the inbox needs (`SqlAlchemyAlertDeliveryRepository` satisfies it)."""

    async def get(self, delivery_id: int) -> DeliveryRow | None: ...
    async def alert_owner(self, alert_id: str) -> str | None: ...
    async def list_page(
        self,
        *,
        user_id: str | None = None,
        alert_id: str | None = None,
        status: str | None = None,
        unacked_only: bool = False,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> DeliveryPage: ...
    async def ack(self, delivery_id: int, user_id: str) -> DeliveryRow | None: ...
    async def ack_all(self, user_id: str, cap: int = 1000) -> list[int]: ...
    async def report_desktop(
        self, delivery_id: int, *, error: str | None, notice_title: str
    ) -> DeliveryRow | None: ...


class _DesktopOutcome(BaseModel):
    """The report-back body; closed (`additionalProperties: false`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    outcome: Literal["shown", "blocked", "failed"]
    permission: Literal["granted", "denied", "default", "unsupported"]


def _iso(d: datetime | None) -> str | None:
    return None if d is None else d.isoformat()


def _utc(d: datetime | None) -> datetime | None:
    """A window bound without an offset is read as UTC (RFC 3339 UTC, `From`/`To`)."""
    return d if d is None or d.tzinfo is not None else d.replace(tzinfo=UTC)


def dump(row: DeliveryRow) -> dict[str, Any]:
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


def _not_found() -> _Problem:
    return _Problem(404, "not_found", "Not found", "No such alert delivery.")


def make_alert_deliveries_router(
    store_provider: Callable[[], AlertDeliveryStore | None],
    actor_resolver: Callable[[Request], Any] | None,
    audit: Any,
    *,
    metric: Metric | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    on_change: OnChange | None = None,
) -> APIRouter:
    """Mount before the `/alerts` CRUD router: its `/alerts/{alertId}` would otherwise take
    `GET /alerts/deliveries` and refuse `deliveries` as a malformed alert id. *metric* is the
    dispatcher's `cv_alert_delivery_*` sink: a desktop delivery settles here, not there."""
    router = APIRouter(tags=["alerts"], route_class=_ProblemRoute)

    def store() -> AlertDeliveryStore:
        s = store_provider()
        if s is None:
            raise _Problem(503, "service_unavailable", "Unavailable", "alerts store unavailable")
        return s

    async def changed(ids: Sequence[int]) -> None:
        if not ids or on_change is None:
            return
        try:
            await on_change(ids)
        except Exception:  # the change is committed; a lost delta is the topic's to repair
            _log().exception("alert_inbox_change_hook_failed", count=len(ids))

    async def emit(action: str, actor: Actor, kind: str, object_id: str | None, **kw: Any) -> None:
        await audit.emit(
            action, actor_label=actor.user_id, actor_user_id=actor.user_id,
            object_kind=kind, object_id=object_id, **kw,
        )  # fmt: skip

    def need(
        perm: str, query: frozenset[str] | None = None
    ) -> Callable[[Request], Awaitable[Actor]]:
        """*query*: the operation's declared query parameters (SR-026), checked once the
        caller holds *perm* and before anything is read."""

        async def dep(request: Request) -> Actor:
            if actor_resolver is None:
                raise _Problem(501, "not_implemented", "Not implemented", "no principal resolver")
            got = actor_resolver(request)
            actor: Actor | None = await got if inspect.isawaitable(got) else got
            if actor is None:
                raise _Problem(401, "unauthorized", "Unauthorized", "no verified session")
            if perm not in actor.perms:
                raise _Problem(403, "forbidden", "Forbidden", f"requires {perm}",
                               required_permissions=[perm])  # fmt: skip
            if query is not None:
                refusal = undeclared_query_refusal(request, query)
                if refusal is not None:
                    raise _Refused(refusal)
            return actor

        return dep

    writer = need(WRITE)

    async def owned(
        deliveryId: Annotated[int, Path(ge=1, le=_INT64_MAX)],
        actor: Annotated[Actor, Depends(writer)],
    ) -> tuple[Actor, DeliveryRow]:
        """`scope: self`: someone else's delivery is indistinguishable from a missing one."""
        row = await store().get(deliveryId)
        if row is None:
            raise _not_found()
        if row.user_id != actor.user_id:
            await emit("alert.denied", actor, "alert_delivery", str(deliveryId),
                       outcome=AuditOutcome.DENIED,
                       reason="delivery owned by another user")  # fmt: skip
            raise _not_found()
        return actor, row

    @router.get("/alerts/deliveries")
    async def list_deliveries(
        actor: Annotated[Actor, Depends(need(READ, LIST_DELIVERIES_QUERY))],
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
                raise _Problem(404, "not_found", "Not found", "No such alert.")
            if owner != actor.user_id:
                await emit("alert.denied", actor, "alert", aid, outcome=AuditOutcome.DENIED,
                           reason="alert owned by another user")  # fmt: skip
                raise _Problem(404, "not_found", "Not found", "No such alert.")
        try:
            page = await s.list_page(
                user_id=actor.user_id, alert_id=aid, status=status,
                unacked_only=unacked_only, from_ts=_utc(from_ts), to_ts=_utc(to),
                cursor=cursor, limit=limit,
            )  # fmt: skip
        except ValueError:
            raise _Problem(400, "validation_failed", "Bad request", "invalid cursor") from None
        items = [dump(r) for r in page.items]
        meta = {"next_cursor": page.next_cursor, "has_more": page.next_cursor is not None,
                "count": len(items)}  # fmt: skip
        return JSONResponse({"items": items, "meta": meta})

    # Declared before `/{deliveryId}/ack`: different segment counts, but keep the literal first.
    @router.post("/alerts/deliveries/ack-all")
    async def ack_all(actor: Annotated[Actor, Depends(writer)]) -> Response:
        s, total = store(), 0
        for _ in range(ACK_ALL_MAX_BATCHES):
            ids = await s.ack_all(actor.user_id, cap=ACK_ALL_BATCH)
            total += len(ids)
            await changed(ids)
            if len(ids) < ACK_ALL_BATCH:
                break
        if total:  # audited before the response, with what it acknowledged (C-2.9)
            await emit("alert.deliveries_acked", actor, "alert_delivery", None,
                       after_state={"status": "acked", "acknowledged": total})  # fmt: skip
        return JSONResponse({"acknowledged": total})

    @router.post("/alerts/deliveries/{deliveryId}/ack")
    async def ack(got: Annotated[tuple[Actor, DeliveryRow], Depends(owned)]) -> Response:
        actor, row = got
        if row.status != "sent":  # acked already (same acked_at), or nothing to acknowledge
            return JSONResponse(dump(row))
        await emit("alert.delivery_acked", actor, "alert_delivery", str(row.id),
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
        request: Request, got: Annotated[tuple[Actor, DeliveryRow], Depends(owned)]
    ) -> Response:
        actor, row = got
        body = await _outcome(request)
        if row.channel != "desktop":
            raise _Problem(422, "validation_failed", "Invalid report",
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
        await emit("alert.desktop_outcome", actor, "alert_delivery", str(row.id),
                   before_state={"status": "queued"}, after_state=after)  # fmt: skip
        new = await store().report_desktop(
            row.id, error=error, notice_title=f"desktop delivery failed: {row.title}"[:200]
        )
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
        raise _Problem(422, "validation_failed", "Invalid report", "The report body is invalid.",
                       errors=[{"field": ".".join(map(str, e["loc"])), "rule": e["type"],
                                "message": e["msg"]} for e in errs]) from None  # fmt: skip
    except ValueError:
        raise _Problem(422, "validation_failed", "Invalid report", "Body is not JSON.") from None


__all__ = [
    "ACK_ALL_BATCH",
    "ACK_ALL_MAX_BATCHES",
    "LIST_DELIVERIES_QUERY",
    "AlertDeliveryStore",
    "DeliveryRow",
    "OnChange",
    "dump",
    "make_alert_deliveries_router",
]
