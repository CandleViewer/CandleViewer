"""`GET /notifications` - unified notification history (E40-T04) - contract: `22-api-openapi.yaml`
listNotifications, `Notification`.

The operation holds no permission of its own (`x-rbac: {permissions: [], scope: self}`): the
caller must have a verified session, and visibility comes from the per-source filters, resolved
here into a `NotificationScope` and applied in SQL before the union is merged
(`storage/repositories/notifications_sqlalchemy.py`). A source the caller has no permission for
is simply absent - never a 403, never a partial row. Rules are filtered by the rules module's
own visibility predicate (`RulesManager.visible_rule_ids`), so a rule's history is visible here
exactly when the rule itself is.

`Notification.id` is `uuid5(namespace, source_table + source_id)` (24-internal-schemas.md §1.6),
so one source row always maps to one id. `source_id` stays contract-typed (a uuid, C-6.1): the
same scheme over `<source_table>:<event id>`, never a raw bigint; the raw parent ids (alert, rule,
order) travel only in `route`. `read_at` is `acked_at` for an alert delivery and null for the
other sources until their owners define read state.
"""

# No `from __future__ import annotations`: FastAPI must evaluate `Depends(<closure>)` in the
# handler signatures at definition time (string annotations cannot see the closures).

import inspect
import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, Any, Final, Literal
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from candleviewer.api.alerts import _Problem, _ProblemRoute, _Refused
from candleviewer.api.query_allowlist import undeclared_query_refusal
from candleviewer.rules.manager import Actor
from candleviewer.storage.repositories.notifications import (
    SOURCES,
    NotificationRow,
    NotificationScope,
    NotificationStore,
    encode_cursor,
)

#: 22-api-openapi.yaml `Notification.x-cv-uuid5-namespace` (24-internal-schemas.md §1.6).
NOTIFICATION_NAMESPACE: Final = UUID("2def8b5c-e7e2-4686-af54-02c04b8c6a78")
#: SR-026: the declared query parameters of `listNotifications`.
LIST_NOTIFICATIONS_QUERY = frozenset({"limit", "cursor", "kind", "unread_only"})
Kind = Literal["alert", "rule", "order", "risk", "system"]
KINDS: Final[tuple[Kind, ...]] = ("alert", "rule", "order", "risk", "system")
_SYMBOL = re.compile(r"^[A-Z0-9]{2,20}USDT$")
#: The rules the caller may read; None = every rule (the Owner), unavailable -> no rule rows.
VisibleRules = Callable[[Actor], Awaitable[frozenset[str] | None]]

_RULE_EVENT: Final = {"action_ok": "action done", "action_fail": "action failed",
                      "throttled": "throttled"}  # fmt: skip
_ORDER_EVENT: Final = {
    "ack": "accepted", "reject": "rejected", "fill": "filled", "partial_fill": "partially filled",
    "amend_ack": "amended", "cancel_ack": "cancelled", "expire": "expired", "error": "failed",
}  # fmt: skip
_ORDER_SEVERITY: Final = {"reject": "error", "error": "error", "expire": "warning"}
#: SPA deep links (apps/web/src/routes/manifest.ts R-191, R-164, R-132); system rows have none.
_ROUTE: Final = {"alert": "/alerts/{}", "rule": "/rules/{}/history", "order": "/positions/order/{}"}


def notification_scope(
    actor: Actor, kinds: Sequence[str], rule_ids: frozenset[str] | None
) -> NotificationScope:
    """The caller's view per source: its permission, then its grants (Owner: all of them)."""
    want = frozenset(kinds or KINDS)
    perms, owner = actor.perms, actor.is_owner
    return NotificationScope(
        user_id=actor.user_id,
        alerts="alert" in want and "alerts:read" in perms,
        rules="rule" in want and "rules:read" in perms and rule_ids != frozenset(),
        rule_ids=rule_ids,
        orders="order" in want and "orders:read" in perms,
        accounts=None if owner else frozenset(actor.granted_accounts),
        system="system" in want,
        system_all=owner,
    )


def notification_id(src: int, src_id: int) -> str:
    return str(uuid5(NOTIFICATION_NAMESPACE, f"{SOURCES[src]}{src_id}"))


def source_id(src: int, src_id: int) -> str:
    """The originating row's own uuid (orchestrator ruling on #1016: `<table>:<event id>`)."""
    return str(uuid5(NOTIFICATION_NAMESPACE, f"{SOURCES[src]}:{src_id}"))


def _title(r: NotificationRow) -> str:
    if r.nkind == "rule":
        return f"Rule {r.title}: {_RULE_EVENT.get(r.event, r.event)}"
    if r.nkind == "order":
        what = f"Order {_ORDER_EVENT.get(r.event, r.event)}"
        what = f"{r.symbol} {what[0].lower()}{what[1:]}" if r.symbol else what
        return f"{what} (code {r.code})" if r.code and r.event in _ORDER_SEVERITY else what
    return r.title or ""


def dump(r: NotificationRow) -> dict[str, Any]:
    """`Notification`, field by field: no source payload, details or exchange text."""
    severity = _ORDER_SEVERITY.get(r.event, "info") if r.nkind == "order" else r.severity
    route = _ROUTE.get(r.nkind)
    symbol = r.symbol if r.symbol is not None and _SYMBOL.match(r.symbol) else None
    return {
        "id": notification_id(r.src, r.src_id), "kind": r.nkind,
        "severity": severity or "info", "title": _title(r), "body": r.body,
        "created_at": r.ts.isoformat(),
        "read_at": None if r.read_at is None else r.read_at.isoformat(),
        "symbol": symbol, "exchange_account_id": r.account_id,
        "source_id": source_id(r.src, r.src_id),
        "route": None if route is None or r.source_uuid is None else route.format(r.source_uuid),
    }  # fmt: skip


def make_notifications_router(
    store_provider: Callable[[], NotificationStore | None],
    actor_resolver: Callable[[Request], Any] | None,
    visible_rules: VisibleRules | None,
) -> APIRouter:
    router = APIRouter(tags=["alerts"], route_class=_ProblemRoute)

    async def readable_rules(actor: Actor) -> frozenset[str] | None:
        """No rules module wired: no rule rows (an empty set), never every rule."""
        return frozenset() if visible_rules is None else await visible_rules(actor)

    async def caller(request: Request) -> Actor:
        """A verified session, no permission (the contract's empty `x-rbac`), then SR-026."""
        if actor_resolver is None:
            raise _Problem(501, "not_implemented", "Not implemented", "no principal resolver")
        got = actor_resolver(request)
        actor: Actor | None = await got if inspect.isawaitable(got) else got
        if actor is None:
            raise _Problem(401, "unauthorized", "Unauthorized", "no verified session")
        refusal = undeclared_query_refusal(request, LIST_NOTIFICATIONS_QUERY)
        if refusal is not None:
            raise _Refused(refusal)
        return actor

    @router.get("/notifications")
    async def list_notifications(
        actor: Annotated[Actor, Depends(caller)],
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
        kind: Annotated[list[Kind] | None, Query()] = None,
        unread_only: bool = False,
    ) -> Response:
        store = store_provider()
        if store is None:
            raise _Problem(503, "service_unavailable", "Unavailable", "notifications unavailable")
        wants_rules = "rules:read" in actor.perms and (not kind or "rule" in kind)
        rule_ids = await readable_rules(actor) if wants_rules else frozenset()
        scope = notification_scope(actor, kind or (), rule_ids)
        try:
            rows, last = await store.list_page(
                scope, unread_only=unread_only, cursor=cursor, limit=limit
            )
        except ValueError:
            raise _Problem(400, "validation_failed", "Bad request", "invalid cursor") from None
        items = [dump(r) for r in rows]
        nxt = None if last is None else encode_cursor(last)
        meta = {"next_cursor": nxt, "has_more": nxt is not None, "count": len(items)}
        return JSONResponse({"items": items, "meta": meta})

    return router


__all__ = [
    "KINDS",
    "LIST_NOTIFICATIONS_QUERY",
    "NOTIFICATION_NAMESPACE",
    "dump",
    "make_notifications_router",
    "notification_id",
    "notification_scope",
    "source_id",
]
