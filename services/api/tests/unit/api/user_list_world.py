"""The world of the `GET /users` tests (#5478): an in-memory user admin store that keeps
`_LIST_USERS`' rules (no soft-deleted row; `status`; `role` among grants that have not expired;
`ILIKE ... ESCAPE '\\'` on the username or the e-mail; the `(created_at, id)` keyset, order and
limit), the router over it with a fixed principal, a recording audit writer, the caller's session
and a fake clock. No I/O, no sleep. Postgres runs the statement itself:
`tests/integration/admin/test_user_list_pg.py`."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.users import make_user_admin_router
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.auth.view_as import ViewAsPhase, ViewAsRequestContext, bound_view_as
from candleviewer.storage.repositories.identity_sqlalchemy import user_of
from candleviewer.storage.repositories.user_list import UserListFilter

T0: Final = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
CALLER: Final = uuid.UUID(int=0xC0FFEE)
SESSION: Final = uuid.UUID(int=0x5E55)  # the session the caller's bearer names
#: Columns of `users` that no `User` carries, as a store that grew them would hand them on.
CANARIES: Final = {
    "password_hash": "$argon2id$canary-5478",
    "last_login_ip": "100.64.0.9",
    "failed_login_count": 3,
    "purge_after": "2027-01-31T00:00:00+00:00",
}
SPEC: Final[dict[str, Any]] = load_openapi_spec()


def like(pattern: str, text: str) -> bool:
    """Postgres `text ILIKE pattern ESCAPE '\\'`: `%` any run, `_` one character, `\\x` an x."""
    parts, chars = [], iter(pattern)
    for char in chars:
        if char == "\\":
            parts.append(re.escape(next(chars, "\\")))
        else:
            parts.append({"%": ".*", "_": "."}.get(char) or re.escape(char))
    return re.fullmatch("".join(parts), text, re.IGNORECASE | re.DOTALL) is not None


@dataclass
class Row:
    """One `users` row and its grants (`roles`: role -> expiry, `None` for none)."""

    id: uuid.UUID
    username: str
    email: str
    created_at: datetime = T0
    status: str = "active"
    roles: dict[str, datetime | None] = field(default_factory=lambda: {"viewer": None})
    display_name: str | None = None
    deleted: bool = False


def rows(count: int, *, tie: int = 1, start: datetime = T0) -> list[Row]:
    """`count` users, `tie` of them sharing each `created_at`, their ids out of insertion order."""
    made = []
    for n in range(count):
        uid = uuid.UUID(int=(n * 7919) % 100_003 + 1)
        name = f"user{n:03d}"
        at = start + timedelta(seconds=n // tie)
        made.append(Row(uid, name, f"{name}@example.invalid", at, display_name=f"Name {n}"))
    return made


class UserRows:
    """`UserAdminStore` in memory, as `_LIST_USERS` reads Postgres (module docstring). `now` is
    the database's `now()` grants expire at; `reads` holds each list read; `error` is raised by
    the next one, as a driver's would be."""

    def __init__(self, found: Iterable[Row] = (), *, now: datetime = T0) -> None:
        self.rows = {row.id: row for row in found}
        self.now, self.reads = now, list[UserListFilter]()
        self.error: Exception | None = None

    def live_roles(self, row: Row) -> list[str]:
        return sorted(r for r, until in row.roles.items() if until is None or until > self.now)

    def answered(self, row: Row) -> dict[str, Any]:
        named = {"id": str(row.id), "username": row.username, "email": row.email}
        mapped = user_of(named | {
            "display_name": row.display_name, "roles": self.live_roles(row), "status": row.status,
            "mfa_enabled": True, "mfa_required": True, "last_login_at": None,
            "created_at": row.created_at, "updated_at": row.created_at,
        })  # fmt: skip
        return mapped | CANARIES

    def matches(self, row: Row, q: UserListFilter) -> bool:
        return (
            not row.deleted
            and q.status in (None, row.status)
            and (q.role is None or q.role in self.live_roles(row))
            and (q.pattern is None or like(q.pattern, row.username) or like(q.pattern, row.email))
            and (q.after is None or (row.created_at, row.id) > q.after)
        )

    async def list_users(self, query: UserListFilter) -> list[dict[str, Any]]:
        self.reads.append(query)
        if self.error is not None:
            raise self.error
        found = sorted((r for r in self.rows.values() if self.matches(r, query)), key=_order)
        return [self.answered(row) for row in found[: query.limit]]

    async def get_user(self, user_id: uuid.UUID) -> dict[str, Any] | None:
        row = self.rows.get(user_id)
        return None if row is None or row.deleted else self.answered(row)

    async def update_user(self, *_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("no list test changes a user")


def _order(row: Row) -> tuple[datetime, uuid.UUID]:
    return row.created_at, row.id


class Records:
    """The audit writer: each record's action and fields; `fail` is what every write raises, as a
    writer that cannot write (`AuditUnavailable`) or an audit service not started (`RuntimeError`)
    does."""

    def __init__(self, *, fail: Exception | None = None) -> None:
        self.fail, self.calls = fail, list[dict[str, Any]]()

    async def emit(self, action: str, **kwargs: Any) -> None:
        if self.fail is not None:
            raise self.fail
        self.calls.append({"action": action, **kwargs})


class Clock:
    def __init__(self, now: datetime = T0) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def principal(role: str, uid: uuid.UUID = CALLER, *, grant: bool = False) -> PrincipalSnapshot:
    """The principal of `role` with 22's `x-permissions` (the Owner: all), a Manager's one grant."""
    held = SPEC["x-permissions"][role]
    perms = frozenset(Permission) if role == "owner" else frozenset(Permission(p) for p in held)
    grants = (AccountGrant(uuid.UUID(int=0xACC), True, True, False),) if grant else ()
    return PrincipalSnapshot(uid, frozenset({role}), perms, grants)


def viewing_as(target: uuid.UUID, viewer: uuid.UUID = CALLER) -> ViewAsRequestContext:
    """The Owner viewing as `target` in a live context: a read answers as the target."""
    return ViewAsRequestContext(
        viewer_user_id=viewer, viewer_session_id=SESSION, viewer_label="owner",
        target_user_id=target, context_id=uuid.uuid5(SESSION, "view-as"),
        subject_user_id=target, phase=ViewAsPhase.LIVE,
    )  # fmt: skip


@dataclass
class World:
    """One app: the store (`wired`: present at all), who the resolver answers, the audit writer,
    the clock and a live view-as context bound around each request, as the guard binds one."""

    store: UserRows = field(default_factory=UserRows)
    caller: PrincipalSnapshot | None = field(default_factory=lambda: principal("owner"))
    records: Records = field(default_factory=Records)
    clock: Clock = field(default_factory=Clock)
    wired: bool = True
    viewing: ViewAsRequestContext | None = None

    def client(self) -> TestClient:
        async def peek(raw: str) -> Any:
            return SimpleNamespace(id=SESSION) if raw == "tok" else None

        sessions = SimpleNamespace(peek_access_token=peek)
        auth: Any = SimpleNamespace(sessions_is_active=True, sessions=sessions)
        resolver = SimpleNamespace(resolve=lambda request: self.caller)
        notifier: Any = object()  # no list request changes a role
        router = make_user_admin_router(
            self.store if self.wired else None, self.records, resolver, notifier, auth=auth,
            clock=self.clock,
        )  # fmt: skip
        app = FastAPI()
        app.include_router(router)
        if (context := self.viewing) is not None:

            @app.middleware("http")
            async def bound(request: Request, call_next: Any) -> Any:
                with bound_view_as(context):
                    return await call_next(request)

        headers = {"Authorization": "Bearer tok"}
        return TestClient(app, headers=headers, raise_server_exceptions=False)

    def get(self, **params: Any) -> Any:
        return self.client().get("/users", params=params)

    def denied(self) -> list[dict[str, Any]]:
        return [c for c in self.records.calls if c["action"] == "rbac.denied"]
