"""Shared HTTP plumbing of the alert routers: `/alerts` (E40-T02), `/alerts/deliveries*` and
`/notifications` (E40-T04).

* `Problem`: an RFC 9457 refusal (`application/problem+json`) raised from a dependency or a
  handler; `Refused` carries a ready response (the shared SR-026 query refusal) as is.
* `ProblemRoute`: the route class that renders both.
* `caller()`: the one caller dependency, so the authorization order is written once:
  no resolver wired → 501 (fail closed); no verified session → 401; the operation's permission
  missing → 403 with `required_permissions`; then SR-026 - any query key the operation does not
  declare → 422 - before anything is read. `permission=None` is an operation whose `x-rbac`
  declares no permission (`listNotifications`): a session is still required.

RBAC is enforced here, server-side (C-12.4); ownership (`scope: self`) stays with each router,
which knows its rows.
"""

# No `from __future__ import annotations`: FastAPI evaluates the dependency signatures at
# definition time.

import inspect
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, Protocol

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from candleviewer.api.query_allowlist import undeclared_query_refusal
from candleviewer.rules.manager import Actor

#: Session -> `Actor` (sync or async); None when the request carries no verified session.
Resolver = Callable[[Request], Actor | Awaitable[Actor | None] | None]


class AuditEmitter(Protocol):
    """The M19 audit writer's `emit` as the routers call it (write-ahead, C-2.9)."""

    async def emit(self, action: str, **fields: Any) -> None: ...


class Problem(Exception):
    def __init__(self, status: int, code: str, title: str, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.status, self.code, self.title, self.detail, self.extra = (
            status, code, title, detail, extra,
        )  # fmt: skip

    def response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status,
            media_type="application/problem+json",
            content={
                "type": f"https://candleviewer.local/errors/{self.code}",
                "title": self.title,
                "status": self.status,
                "code": self.code,
                "detail": self.detail,
                **self.extra,
            },
        )


class Refused(Exception):
    """A ready refusal raised from a dependency: the shared SR-026 query refusal, sent as is."""

    def __init__(self, response: JSONResponse) -> None:
        super().__init__(response.status_code)
        self.response = response


class ProblemRoute(APIRoute):
    """Turns `Problem` (or a ready `Refused`) raised in a dependency or handler into an RFC 9457
    response."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        inner = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                return await inner(request)
            except Problem as p:
                return p.response()
            except Refused as r:
                return r.response

        return handler


def caller(
    resolver: Resolver | None,
    permission: str | None,
    query: frozenset[str] | None = None,
) -> Callable[[Request], Awaitable[Actor]]:
    """The dependency resolving the caller of one operation (see the module docstring)."""

    async def dep(request: Request) -> Actor:
        if resolver is None:
            raise Problem(501, "not_implemented", "Not implemented", "no principal resolver")
        got = resolver(request)
        actor: Actor | None = await got if inspect.isawaitable(got) else got
        if actor is None:
            raise Problem(401, "unauthorized", "Unauthorized", "no verified session")
        if permission is not None and permission not in actor.perms:
            raise Problem(403, "forbidden", "Forbidden", f"requires {permission}",
                          required_permissions=[permission])  # fmt: skip
        if query is not None:
            refusal = undeclared_query_refusal(request, query)
            if refusal is not None:
                raise Refused(refusal)
        return actor

    return dep


__all__ = ["AuditEmitter", "Problem", "ProblemRoute", "Refused", "Resolver", "caller"]
