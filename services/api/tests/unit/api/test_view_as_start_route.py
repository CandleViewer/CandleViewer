"""#3085 S13b: `POST /admin/view-as` (22 `startViewAs`). The admin-area guard (`users:write`) first,
then the refusals in the contract's order, each but `422` recorded as one `admin.view_as_refused`
ahead of its answer, then the step-up gate (class `users`), then the start's one unit of work."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from structlog.testing import capture_logs

from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.deny_by_default import declared_operations
from candleviewer.api.view_as import START_REFUSALS, make_view_as_start_router
from candleviewer.api.view_as_refusals import VIEW_AS_REFUSED, ViewAsRefusalRecorder
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.errors import StepUpRequired
from candleviewer.auth.models import MintedSession
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import CHALLENGE_WINDOW, StepUpChallenge
from candleviewer.auth.view_as import ViewAsState
from tests.unit.admin.test_view_as_service import _TARGET, _VIEWER, _at, _Rig
from tests.unit.api._fakes import BASE, HASHER, RecordingWriter
from tests.unit.api.test_view_as_routes import Store

_SPEC = load_openapi_spec()
_PATH = "/admin/view-as"
_REASON = "Reproduce the empty positions panel bo reported"
_OTHER = UUID(int=3)  # a user who is not the target
_RID = uuid4()


def _user(username: str, status: str = "active", roles: tuple[str, ...] = ("manager",)) -> Any:
    return {"username": username, "display_name": "Bo B.", "status": status, "roles": list(roles)}


class StepUp:
    """The `users` class: elevated unless `elevated` is false, then a challenge per request."""

    def __init__(self) -> None:
        self.elevated = True
        self.pending: list[tuple[str, str]] = []

    async def require_elevation(self, session_id: str, action_class: str) -> None:
        if not self.elevated:
            raise StepUpRequired(action_class)

    async def record_pending(self, session_id: str, action_class: str) -> StepUpChallenge:
        self.pending.append((session_id, action_class))
        return StepUpChallenge(uuid4(), action_class, _at(0) + CHALLENGE_WINDOW)


class Auth:
    step_up_is_active = sessions_is_active = True

    def __init__(self, sessions: SessionService) -> None:
        self.sessions, self.step_up = sessions, StepUp()


class Users:
    """`TargetUsers`: undeleted users' rows; `fails` raises from every read. With a `barrier`,
    every concurrent start reads its target before any of them goes on."""

    def __init__(self) -> None:
        self.rows: dict[str, Any] = {str(_TARGET): _user("bo"), str(_VIEWER): _user("ana")}
        self.fails: Exception | None = None
        self.barrier: asyncio.Barrier | None = None

    async def user(self, user_id: str) -> Any:
        if self.barrier is not None:
            await self.barrier.wait()
        if self.fails is not None:
            raise self.fails
        if user_id not in self.rows:
            raise LookupError("unknown user")
        return self.rows[user_id]


class Writer(RecordingWriter):
    """The audit writer; an action in `refuses` raises, as an unwritable record does."""

    def __init__(self) -> None:
        super().__init__()
        self.refuses: set[str] = set()

    async def emit(self, action: str, **kw: Any) -> None:
        if action in self.refuses:
            raise ConnectionError("audit WAL unwritable")
        await super().emit(action, **kw)


class World:
    """The router alone, behind its admin-area guard, over the S13a service on the fake store."""

    def __init__(self) -> None:
        self.repo = Store()
        self.rig = _Rig(repo=self.repo)
        self.clock, self.ports = self.rig.clock, self.rig.ports
        self.sessions = SessionService(self.repo, HASHER, clock=self.clock)
        self.auth, self.users, self.audit = Auth(self.sessions), Users(), Writer()
        self.recorder = ViewAsRefusalRecorder(self.audit, operations=declared_operations(_SPEC))
        self.service: Any = self.rig.service
        self.permissions = frozenset({"users:write"})
        self.minted: MintedSession | None = None
        app = FastAPI()
        app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
        app.include_router(
            make_view_as_start_router(
                self.auth,
                resolver=self,
                audit=self.audit,
                views=lambda: self.service,
                refusals=lambda: self.recorder,
                users=self.users,
                clock=self.clock,
            )
        )
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url=BASE)

    async def resolve(self, request: Any) -> AuditPrincipal | None:
        """The admin-area guard's principal: the viewer, as an own operation resolves (S8)."""
        if self.minted is None:
            return None
        return AuditPrincipal(
            user_id=_VIEWER,
            username="ana",
            permissions=self.permissions,
            session_id=self.minted.session_id,
            ip="100.64.0.9",
            request_id=_RID,
        )

    async def sign_in(self) -> MintedSession:
        self.minted = await self.sessions.mint(str(_VIEWER))
        return self.minted

    async def start(self, body: Any = None, *, raw: bytes | None = None) -> httpx.Response:
        assert self.minted is not None
        headers = {"Authorization": f"Bearer {self.minted.access_token}"}
        sent = {"target_user_id": str(_TARGET), "reason": _REASON} if body is None else body
        if raw is not None:
            return await self.client.post(_PATH, content=raw, headers=headers)
        return await self.client.post(_PATH, json=sent, headers=headers)

    def held(self) -> ViewAsState | None:
        assert self.minted is not None
        return self.repo.sessions[str(self.minted.session_id)].view_as

    def refused(self) -> list[tuple[str, str]]:
        return [(r["reason"], r["object_id"]) for r in self.audit.of(VIEW_AS_REFUSED)]


def _code(response: httpx.Response) -> tuple[int, str]:
    assert response.headers["content-type"].startswith("application/problem+json")
    return response.status_code, response.json()["code"]


async def _viewing(w: World) -> ViewAsState:
    """The signed-in session holding a live context on `_TARGET`."""
    assert w.minted is not None
    state = ViewAsState.start(uuid4(), _TARGET, now=_at(0))
    assert await w.repo.start_view_as(str(w.minted.session_id), state, now=w.clock())
    return state


# -- the start ------------------------------------------------------------------------------------


async def test_a_start_answers_201_with_the_context_it_started() -> None:
    w = World()
    await w.sign_in()
    response = await w.start()
    held = w.held()
    assert response.status_code == 201 and held is not None
    assert response.json() == {
        "target_user_id": str(_TARGET),
        "target_username": "bo",
        "target_display_name": "Bo B.",
        "started_at": held.started_at.isoformat().replace("+00:00", "Z"),
        "expires_at": held.expires_at.isoformat().replace("+00:00", "Z"),
        "read_only": True,
        "state": "active",
    }
    assert [c["action"] for c in w.ports.calls] == ["admin.view_as_started"]
    assert len(w.repo.notices) == 1 and w.refused() == []


async def test_a_locked_target_can_be_viewed_as() -> None:
    """A `locked` user is only locked out of signing in (22)."""
    w = World()
    await w.sign_in()
    w.users.rows[str(_TARGET)] = _user("bo", status="locked")
    assert (await w.start()).status_code == 201


async def test_of_two_concurrent_starts_one_starts_and_the_other_is_refused_and_recorded() -> None:
    """Both pass the refusals before either starts, so the start's unit of work decides: the loser
    reads the winner's context held, answers 409 and records it."""
    w = World()
    await w.sign_in()
    w.users.barrier = asyncio.Barrier(2)
    answers = await asyncio.gather(w.start(), w.start())
    assert sorted(r.status_code for r in answers) == [201, 409]
    (lost,) = [r for r in answers if r.status_code == 409]
    assert _code(lost) == (409, "view_as_active")
    assert w.refused() == [("view_as_active", str(_TARGET))]
    assert [c["action"] for c in w.ports.calls] == ["admin.view_as_started"]


# -- the refusals ---------------------------------------------------------------------------------


async def _held_and_self(w: World) -> UUID:
    await _viewing(w)
    return _VIEWER


async def _self(w: World) -> UUID:
    return _VIEWER  # an Owner here: the self-target comes first


async def _unknown(w: World) -> UUID:
    return _OTHER


async def _disabled_owner(w: World) -> UUID:
    w.users.rows[str(_TARGET)] = _user("bo", status="disabled", roles=("owner",))
    return _TARGET


async def _invited(w: World) -> UUID:
    w.users.rows[str(_TARGET)] = _user("bo", status="invited")
    return _TARGET


async def _owner(w: World) -> UUID:
    w.users.rows[str(_TARGET)] = _user("bo", roles=("owner",))
    return _TARGET


@pytest.mark.parametrize(
    ("arrange", "status", "code"),
    [
        (_held_and_self, 409, "view_as_active"),
        (_self, 403, "view_as_self_target"),
        (_unknown, 404, "not_found"),
        (_disabled_owner, 409, "conflict"),
        (_invited, 409, "conflict"),
        (_owner, 403, "view_as_owner_target"),
    ],
    ids=["active", "self", "not-found", "disabled", "invited", "owner"],
)
async def test_each_refusal_comes_in_the_contracts_order_and_is_recorded(
    arrange: Callable[[World], Awaitable[UUID]], status: int, code: str
) -> None:
    """Each case also breaks every later rule, so only the order answers it. Each writes one
    `admin.view_as_refused` naming the requested user, and none is a challenge."""
    w = World()
    await w.sign_in()
    w.auth.step_up.elevated = False
    w.users.rows[str(_VIEWER)] = _user("ana", roles=("owner",))
    target = await arrange(w)
    response = await w.start({"target_user_id": str(target), "reason": _REASON})
    assert _code(response) == (status, code) and START_REFUSALS[code] == status
    assert w.refused() == [(code, str(target))] and w.auth.step_up.pending == []


async def test_the_active_refusal_records_the_context_it_holds() -> None:
    w = World()
    minted = await w.sign_in()
    state = await _viewing(w)
    await w.start({"target_user_id": str(_OTHER), "reason": _REASON})
    (record,) = w.audit.of(VIEW_AS_REFUSED)
    assert record["before_state"] == {
        "target_user_id": str(_TARGET),
        "started_at": state.started_at.isoformat(),
        "expires_at": state.expires_at.isoformat(),
    }
    assert (record["actor_user_id"], record["session_id"]) == (_VIEWER, minted.session_id)


@pytest.mark.parametrize(
    "body",
    [
        json.dumps({"target_user_id": str(_TARGET)}).encode(),
        json.dumps({"target_user_id": "not-a-uuid", "reason": _REASON}).encode(),
        json.dumps({"target_user_id": str(_TARGET), "reason": " "}).encode(),
        json.dumps({"target_user_id": str(_TARGET), "reason": _REASON, "extra": 1}).encode(),
        b"{" + b" " * 9000 + b"}",
    ],
    ids=["no-reason", "not-a-uuid", "blank-reason", "extra-member", "too-large"],
)
async def test_an_invalid_body_is_a_422_that_records_nothing_even_while_viewing(
    body: bytes,
) -> None:
    w = World()
    await w.sign_in()
    await _viewing(w)
    response = await w.start(raw=body)
    assert _code(response) == (422, "validation_failed")
    assert w.refused() == [] and "not-a-uuid" not in response.text


async def test_a_caller_without_users_write_is_the_guards_403_with_no_refusal_record() -> None:
    w = World()
    await w.sign_in()
    w.permissions = frozenset()
    assert _code(await w.start()) == (403, "forbidden")
    (entered,) = w.audit.of("admin.area_entered")
    assert entered["outcome"] == "denied" and w.refused() == [] and w.held() is None


async def test_a_refusal_that_cannot_be_recorded_answers_503_and_starts_nothing() -> None:
    w = World()
    await w.sign_in()
    w.users.rows[str(_TARGET)] = _user("bo", roles=("owner",))
    w.audit.refuses.add(VIEW_AS_REFUSED)
    assert _code(await w.start()) == (503, "audit_unavailable")
    assert w.held() is None


# -- the step-up gate ------------------------------------------------------------------------------


async def test_the_challenge_comes_after_the_refusals_and_restates_the_target() -> None:
    w = World()
    minted = await w.sign_in()
    w.auth.step_up.elevated = False
    response = await w.start()
    assert _code(response) == (403, "step_up_required")
    assert response.json()["action_summary"] == "View as user 'bo', read-only"
    assert w.auth.step_up.pending == [(str(minted.session_id), "users")]
    assert w.held() is None and w.refused() == [] and w.ports.calls == []


# -- failures --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("port", "code"), [("emit", "audit_unavailable"), ("usernames", "store_unavailable")]
)
async def test_a_start_whose_records_cannot_be_written_answers_503_and_starts_nothing(
    port: str, code: str
) -> None:
    w = World()
    await w.sign_in()
    w.ports.fails[port] = ConnectionError("down")
    assert _code(await w.start()) == (503, code)
    assert w.held() is None and w.repo.notices == []


async def test_a_users_read_that_fails_answers_503_and_records_nothing() -> None:
    w = World()
    await w.sign_in()
    w.users.fails = ConnectionError("users store unreachable")
    assert _code(await w.start()) == (503, "store_unavailable")
    assert w.refused() == [] and w.held() is None


async def test_a_backend_without_the_service_answers_503_after_the_guard() -> None:
    w = World()
    await w.sign_in()
    w.service = None
    assert _code(await w.start()) == (503, "store_unavailable")
    assert [e["action"] for e in w.audit.events] == ["admin.area_entered"]


async def test_the_reason_reaches_only_the_started_record() -> None:
    """It is never logged, challenged, answered or noticed, and no refusal carries it (22)."""
    w = World()
    await w.sign_in()
    with capture_logs() as logs:
        started = await w.start()
        w.auth.step_up.elevated = False
        await w.start()  # a refusal: the session now views
    assert _REASON not in json.dumps(logs, default=str) + started.text
    assert _REASON not in json.dumps(w.audit.events, default=str)
    assert _REASON not in "".join(n.message for n in w.repo.notices)
    (record,) = [c for c in w.ports.calls if c["action"] == "admin.view_as_started"]
    assert record["after_state"]["reason"] == _REASON
