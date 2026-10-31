"""#3085 S13b: `POST /admin/view-as` (22 `startViewAs`). The admin-area guard (`users:write`) first,
then the refusals in the contract's order, each but `422` recorded as one `admin.view_as_refused`
ahead of its answer, then the step-up gate (class `users`), then the start's one unit of work."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, NamedTuple
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from structlog.testing import capture_logs

from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.deny_by_default import declared_operations
from candleviewer.api.view_as import make_view_as_start_router
from candleviewer.api.view_as_refusals import VIEW_AS_REFUSED, ViewAsRefusalRecorder
from candleviewer.audit.access import AuditPrincipal
from candleviewer.auth.errors import StepUpRequired
from candleviewer.auth.models import MintedSession
from candleviewer.auth.session_service import SessionService
from candleviewer.auth.step_up import CHALLENGE_WINDOW, StepUpChallenge
from candleviewer.auth.view_as import ViewAsEndReason, ViewAsStartResult, ViewAsState
from candleviewer.storage.errors import ActorNotAuthorised
from tests.unit.admin.test_view_as_service import _TARGET, _VIEWER, _at, _Rig
from tests.unit.api._fakes import BASE, HASHER, RecordingWriter
from tests.unit.api.test_view_as_routes import Store

_SPEC = load_openapi_spec()
_PATH = "/admin/view-as"
_REASON = "Reproduce the empty positions panel bo reported"
_OTHER = UUID(int=3)  # a user who is not the target
_RID = uuid4()
_WAIT_S = 30.0  # bounds the barrier below: a regression fails instead of hanging the run


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
            async with asyncio.timeout(_WAIT_S):
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


async def _held(w: World) -> ViewAsState:
    """The signed-in session holding an ended context on `_TARGET` that it has not cleared: the
    state after its expiry or its viewer's end, until the viewer leaves (22)."""
    state = await _viewing(w)
    assert w.minted is not None
    ended = await w.repo.end_view_as(
        str(w.minted.session_id), state.context_id, ended_at=w.clock(), reason=ViewAsEndReason.ENDED
    )
    assert ended is not None and ended.view_as is not None
    return ended.view_as


async def _cleared(w: World) -> ViewAsState:
    """The signed-in session whose context ended, was recorded and was cleared by a leave."""
    held = await _held(w)
    assert w.minted is not None
    session_id, now = str(w.minted.session_id), w.clock()
    assert await w.repo.mark_view_as_recorded(session_id, held.context_id, now=now)
    cleared = await w.repo.clear_view_as(session_id, held.context_id, now=now)
    assert cleared is not None and cleared.view_as is not None
    return cleared.view_as


# -- the start ------------------------------------------------------------------------------------


async def _after_a_start() -> World:
    """A world whose signed-in viewer has started a context on `_TARGET`."""
    w = World()
    await w.sign_in()
    await w.start()
    return w


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


async def test_a_start_writes_one_started_record() -> None:
    w = await _after_a_start()
    assert [c["action"] for c in w.ports.calls] == ["admin.view_as_started"]


async def test_a_start_records_the_address_it_came_from() -> None:
    """The started record's `actor_ip` is the admin principal's address, as a refusal record's is
    (the #4245 re-check's n-7)."""
    w = await _after_a_start()
    (call,) = w.ports.calls
    assert call.get("actor_ip") == "100.64.0.9"


async def test_a_start_notifies_the_target_once() -> None:
    w = await _after_a_start()
    assert len(w.repo.notices) == 1


async def test_a_start_writes_no_refusal_record() -> None:
    w = await _after_a_start()
    assert w.refused() == []


async def test_a_locked_target_can_be_viewed_as() -> None:
    """A `locked` user is only locked out of signing in (22)."""
    w = World()
    await w.sign_in()
    w.users.rows[str(_TARGET)] = _user("bo", status="locked")
    assert (await w.start()).status_code == 201


async def test_a_cleared_context_does_not_block_a_start() -> None:
    """A viewer who left its context holds none (22): it can start another."""
    w = World()
    await w.sign_in()
    await _cleared(w)
    assert (await w.start()).status_code == 201


async def test_a_reason_of_the_maximum_size_is_a_201_with_every_character_escaped() -> None:
    """500 astral characters, each escaped as a surrogate pair: about 6 KB, the largest body the
    contract allows, which the body cap leaves room for."""
    w = World()
    await w.sign_in()
    raw = json.dumps({"target_user_id": str(_TARGET), "reason": "\U0001f600" * 500}).encode()
    assert (await w.start(raw=raw)).status_code == 201


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


#: Each refusal's cause, its status and its problem code.
_REFUSALS = [
    pytest.param((_held_and_self, 409, "view_as_active"), id="active"),
    pytest.param((_self, 403, "view_as_self_target"), id="self"),
    pytest.param((_unknown, 404, "not_found"), id="not-found"),
    pytest.param((_disabled_owner, 409, "conflict"), id="disabled"),
    pytest.param((_invited, 409, "conflict"), id="invited"),
    pytest.param((_owner, 403, "view_as_owner_target"), id="owner"),
]


class Refusal(NamedTuple):
    """A refused start: its world, the user it asked for, its answer, and the status and problem
    code the contract gives that refusal."""

    world: World
    target: UUID
    response: httpx.Response
    status: int
    code: str


@pytest.fixture(params=_REFUSALS)
async def refusal(request: pytest.FixtureRequest) -> Refusal:
    """Each refusal, sent by an unelevated Owner, so a refusal that was a challenge would show."""
    arrange, status, code = request.param
    w = World()
    await w.sign_in()
    w.auth.step_up.elevated = False
    w.users.rows[str(_VIEWER)] = _user("ana", roles=("owner",))
    target = await arrange(w)
    response = await w.start({"target_user_id": str(target), "reason": _REASON})
    return Refusal(w, target, response, status, code)


async def test_each_refusal_comes_in_the_contracts_order(refusal: Refusal) -> None:
    """Where a case can, it also breaks a later rule, so only the order answers it: the held
    context is also a self-target, a self-target also an Owner's, and a disabled user an Owner."""
    assert _code(refusal.response) == (refusal.status, refusal.code)


async def test_each_refusal_is_recorded_naming_the_requested_user(refusal: Refusal) -> None:
    assert refusal.world.refused() == [(refusal.code, str(refusal.target))]


async def test_a_refused_start_is_never_a_challenge(refusal: Refusal) -> None:
    assert refusal.world.auth.step_up.pending == []


async def test_a_held_context_refuses_a_start_and_is_never_challenged() -> None:
    """The state after its expiry (22 says live or held), and the viewer is not elevated."""
    w = World()
    await w.sign_in()
    await _held(w)
    w.auth.step_up.elevated = False
    assert _code(await w.start()) == (409, "view_as_active")
    assert w.auth.step_up.pending == []


@pytest.mark.parametrize("hold", [_viewing, _held], ids=["live", "held"])
async def test_the_active_refusal_records_the_context_it_holds(
    hold: Callable[[World], Awaitable[ViewAsState]],
) -> None:
    w = World()
    await w.sign_in()
    state = await hold(w)
    await w.start({"target_user_id": str(_OTHER), "reason": _REASON})
    (record,) = w.audit.of(VIEW_AS_REFUSED)
    assert record["before_state"] == {
        "target_user_id": str(_TARGET),
        "started_at": state.started_at.isoformat(),
        "expires_at": state.expires_at.isoformat(),
    }


async def test_a_refusal_record_names_the_viewer_and_the_request_it_answers() -> None:
    w = World()
    minted = await w.sign_in()
    await w.start({"target_user_id": str(_VIEWER), "reason": _REASON})
    (record,) = w.audit.of(VIEW_AS_REFUSED)
    assert (record["actor_user_id"], record["session_id"]) == (_VIEWER, minted.session_id)
    assert (record["actor_label"], record["actor_ip"]) == ("ana", "100.64.0.9")
    assert record["request_id"] == _RID


_BODIES = pytest.mark.parametrize(
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


async def _invalid(body: bytes) -> tuple[World, httpx.Response]:
    """An invalid body, sent by a session that holds a context: a valid one would be refused and
    recorded."""
    w = World()
    await w.sign_in()
    await _viewing(w)
    return w, await w.start(raw=body)


@_BODIES
async def test_an_invalid_body_is_a_422_even_while_viewing(body: bytes) -> None:
    _, response = await _invalid(body)
    assert _code(response) == (422, "validation_failed")


@_BODIES
async def test_an_invalid_body_records_nothing_even_while_viewing(body: bytes) -> None:
    w, _ = await _invalid(body)
    assert w.refused() == []


@pytest.mark.parametrize(
    ("body", "echoed"),
    [
        ({"target_user_id": "not-a-uuid", "reason": _REASON}, "not-a-uuid"),
        ({"target_user_id": str(_TARGET), "reason": _REASON, "smuggled": 1}, "smuggled"),
    ],
    ids=["value", "member-name"],
)
async def test_an_invalid_body_is_never_echoed(body: dict[str, Any], echoed: str) -> None:
    _, response = await _invalid(json.dumps(body).encode())
    assert response.status_code == 422 and echoed not in response.text


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


async def _challenged() -> tuple[World, MintedSession, httpx.Response]:
    """An unelevated viewer's start, which no refusal stops."""
    w = World()
    minted = await w.sign_in()
    w.auth.step_up.elevated = False
    return w, minted, await w.start()


async def test_a_start_no_refusal_stops_is_challenged_when_not_elevated() -> None:
    _, _, response = await _challenged()
    assert _code(response) == (403, "step_up_required")


async def test_the_challenge_restates_the_target_and_not_the_reason() -> None:
    _, _, response = await _challenged()
    assert response.json()["action_summary"] == "View as user 'bo', read-only"


async def test_the_challenge_is_recorded_pending_for_the_session_and_its_class() -> None:
    w, minted, _ = await _challenged()
    assert w.auth.step_up.pending == [(str(minted.session_id), "users")]


async def test_a_challenged_start_starts_nothing_and_records_no_refusal() -> None:
    w, _, _ = await _challenged()
    assert w.held() is None and w.refused() == [] and w.ports.calls == []


async def test_a_starts_window_opens_when_the_gate_has_passed_not_when_the_row_was_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#4245's re-check Nit-1: the start's `now` is read after the step-up gate, so a gate that
    took 40 s does not backdate the context: its window, in the 201 and in the session's row, opens
    at the instant the start ran."""
    w = World()
    await w.sign_in()
    opened = w.clock.now + timedelta(seconds=40)

    async def slow_gate(session_id: str, action_class: str) -> None:
        w.clock.now = opened  # the gate took its time

    monkeypatch.setattr(w.auth.step_up, "require_elevation", slow_gate)
    response = await w.start()
    held = w.held()
    assert response.status_code == 201 and held is not None
    assert held.started_at == opened
    assert response.json()["started_at"] == opened.isoformat().replace("+00:00", "Z")


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


def _session_unreadable(w: World) -> None:
    w.repo.fails.add("find_by_access_token_jti")  # the guard reads no row: the route's own read


def _users_unreadable(w: World) -> None:
    w.users.fails = ConnectionError("users store unreachable")


_READS = pytest.mark.parametrize(
    "fail", [_session_unreadable, _users_unreadable], ids=["session", "users"]
)


@_READS
async def test_a_read_that_fails_answers_503_and_starts_nothing(
    fail: Callable[[World], None],
) -> None:
    w = World()
    await w.sign_in()
    fail(w)
    assert _code(await w.start()) == (503, "store_unavailable")
    assert w.refused() == [] and w.held() is None and w.ports.calls == []


@_READS
async def test_a_read_that_fails_says_the_context_could_not_be_started(
    fail: Callable[[World], None],
) -> None:
    w = World()
    await w.sign_in()
    fail(w)
    detail = (await w.start()).json()["detail"]
    assert detail == "The view-as context could not be started. Try again shortly."


async def test_a_backend_without_the_service_answers_503_after_the_guard() -> None:
    w = World()
    await w.sign_in()
    w.service = None
    assert _code(await w.start()) == (503, "store_unavailable")
    assert [e["action"] for e in w.audit.events] == ["admin.area_entered"]


async def test_a_target_row_outside_the_contract_answers_503_and_starts_nothing() -> None:
    """The 201's target is checked before anything starts, so no started context can end up behind
    a 500 (#4245 security Low-1): a display name past `ViewAsContext`'s bound is a 503."""
    w = World()
    await w.sign_in()
    w.users.rows[str(_TARGET)] = {**_user("bo"), "display_name": "B" * 81}
    assert _code(await w.start()) == (503, "store_unavailable")
    assert w.held() is None and w.repo.notices == [] and w.ports.calls == []


async def test_a_target_row_outside_the_contract_logs_its_fields_and_never_their_values() -> None:
    """#4245's re-check Minor-1: the row's display name is P1, so the 503's log line names the
    failing fields and their error types, never the value pydantic's text would echo."""
    w = World()
    await w.sign_in()
    name = "Bartholomew-" + "X" * 80
    w.users.rows[str(_TARGET)] = {**_user("bo"), "display_name": name}
    with capture_logs() as logs:
        assert _code(await w.start()) == (503, "store_unavailable")
    (line,) = [e for e in logs if e.get("read") == "users"]
    assert line["fields"] == [("target_display_name", "string_too_long")]
    assert "exc_info" not in line and "Bartholomew" not in json.dumps(logs, default=str)


async def test_a_target_with_no_display_name_starts_with_a_null_one() -> None:
    w = World()
    await w.sign_in()
    w.users.rows[str(_TARGET)] = {k: v for k, v in _user("bo").items() if k != "display_name"}
    response = await w.start()
    assert response.status_code == 201 and response.json()["target_display_name"] is None


async def test_a_start_whose_session_went_meanwhile_answers_401() -> None:
    """The start's unit of work found no session row: it was revoked or expired after the route
    read it, so nothing started (22)."""

    class Gone:
        async def start(self, *_args: Any, **_kw: Any) -> ViewAsStartResult:
            return ViewAsStartResult(started=None, held=None)

    w = World()
    await w.sign_in()
    w.service = Gone()
    assert _code(await w.start()) == (401, "unauthenticated")
    assert w.refused() == []


async def test_a_backend_without_step_up_answers_503_and_starts_nothing() -> None:
    w = World()
    await w.sign_in()
    w.auth.step_up_is_active = False
    assert _code(await w.start()) == (503, "store_unavailable")
    assert w.held() is None and w.ports.calls == []


async def test_a_start_that_could_not_be_written_logs_its_code_and_nothing_that_names_anyone() -> (
    None
):
    """#4245 security Low-3: an operator sees a failed start by its code and its cause's class."""
    w = World()
    minted = await w.sign_in()
    w.ports.fails["emit"] = ConnectionError("down")
    with capture_logs() as logs:
        assert _code(await w.start()) == (503, "audit_unavailable")
    (line,) = [e for e in logs if e["event"] == "admin.view_as.start_unavailable"]
    assert line["code"] == "audit_unavailable" and line["error"] is not None
    written = json.dumps(logs, default=str)
    assert all(v not in written for v in (_REASON, str(minted.session_id), str(_TARGET)))


async def test_the_reason_reaches_only_the_started_record() -> None:
    """It is never logged, answered or noticed, and no refusal record carries it (22). The
    challenge restates the target alone, as its own test pins."""
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


# -- #2593: the viewer re-read at the effect, in the start's unit of work ---------------------


def _viewer_revoked(w: World) -> None:
    """The start's unit of work re-reads the viewer under the owner lock: no active owner."""

    async def refused(session_id: str, *_args: Any, **_kw: Any) -> Any:
        raise ActorNotAuthorised(str(_VIEWER))

    w.repo.start_view_as_unit = refused  # type: ignore[method-assign]  # the store's re-read


async def test_a_viewer_demoted_since_entry_gets_the_guards_403_and_nothing_starts() -> None:
    w = World()
    await w.sign_in()
    _viewer_revoked(w)
    r = await w.start()
    fresh = World()
    await fresh.sign_in()
    fresh.permissions = frozenset()
    entry = await fresh.start()
    assert (r.status_code, entry.status_code) == (403, 403) and r.json() == entry.json()
    assert "challenge_id" not in r.json()
    assert w.held() is None and w.repo.notices == [] and w.refused() == []
    assert w.audit.of("admin.view_as_started") == []
    (denied,) = w.audit.of("rbac.denied")
    assert (denied["reason"], denied["object_id"]) == ("actor_role_revoked", str(_TARGET))
    assert denied["session_id"] == w.minted.session_id  # type: ignore[union-attr]


async def test_a_viewer_refused_at_the_effect_unrecorded_answers_503() -> None:
    w = World()
    await w.sign_in()
    _viewer_revoked(w)
    w.audit.refuses.add("rbac.denied")
    assert _code(await w.start()) == (503, "audit_unavailable")
    assert w.held() is None
