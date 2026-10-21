"""#3085 S7: the view-as guard (plan 1.4; 22-api-openapi.yaml "View-as session"). The guard alone
in front of catch-all routes that record what they saw; the session store and the view-as service
are S4's rig (the fake repository, a real `ViewAsService`, recording ports), step-up is a fake, and
the refusal recorder is the real one over the budget tests' recording writer. No sleep: the clocks
are fake. The contract-wide sweep is `tests/security/auth/test_view_as_http.py`."""

from __future__ import annotations

import re
from functools import cache
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.deny_by_default import declared_operations
from candleviewer.api.view_as_guard import STATE_KEY, make_view_as_guard
from candleviewer.api.view_as_policy import OWN_OPERATIONS, PROTECTIVE_WRITES, ProtectiveWrites
from candleviewer.api.view_as_refusals import VIEW_AS_REFUSED, ViewAsRefusalRecorder
from candleviewer.auth.errors import AuthError, SessionReadOnly
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.view_as import ViewAsEndReason, ViewAsPhase, current_view_as
from tests.unit.admin.test_view_as_service import _TARGET, _VIEWER, _at, _Rig
from tests.unit.api.test_audit_budget import _Clock, _Writer
from tests.unit.auth.test_step_up import _session

_METHODS = ["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"]


@cache
def _spec() -> dict[str, Any]:
    return load_openapi_spec()


def _declared() -> frozenset[tuple[str, str]]:
    return frozenset(declared_operations(_spec()))


def _path(template: str) -> str:
    """A concrete path of `template`: each placeholder becomes `x`."""
    return re.sub(r"\{[^}]+\}", "x", template)


class _Sessions:
    def __init__(self, rig: _Rig) -> None:
        self.rig = rig
        self.fails: Exception | None = None

    async def authenticate_access_token(
        self, raw_access_token: str, *, allow_locked: bool = False
    ) -> SessionRecord:
        if self.fails is not None:
            raise self.fails
        if (record := self.rig.repo.sessions.get(raw_access_token)) is None:
            raise AuthError("no such session")
        return record


class _StepUp:
    """`assert_writable`: a session in `read_only` is in the downgrade."""

    def __init__(self) -> None:
        self.read_only: set[str] = set()
        self.asked = 0
        self.fails: Exception | None = None

    async def assert_writable(self, session_id: str) -> None:
        self.asked += 1
        if self.fails is not None:
            raise self.fails
        if session_id in self.read_only:
            raise SessionReadOnly(until=None)


class _Auth:
    def __init__(self, rig: _Rig) -> None:
        self.sessions, self.step_up = _Sessions(rig), _StepUp()
        self.sessions_is_active = self.step_up_is_active = True


class _Gate:
    """The guard in front of catch-all routes; `seen` holds (method, path, stamp, contextvar)."""

    def __init__(self, *, inner: list[str] | None = None) -> None:
        self.rig = _Rig()
        self.auth = _Auth(self.rig)
        self.writer = _Writer(_Clock())
        self.refusals: ViewAsRefusalRecorder | None = ViewAsRefusalRecorder(
            self.writer, operations=_declared(), clock=self.writer.clock
        )
        self.service: Any = self.rig.service
        self.protective = ProtectiveWrites(_declared())
        self.seen: list[tuple[str, str, Any, Any]] = []
        app = FastAPI()

        @app.api_route("/{path:path}", methods=_METHODS)
        async def route(request: Request, path: str) -> JSONResponse:
            stamp = request.scope.get("state", {}).get(STATE_KEY)
            self.seen.append((request.method, f"/{path}", stamp, current_view_as()))
            return JSONResponse({"ok": True})

        if inner is not None:  # a layer the guard wraps, as it wraps the read-only/step-up guard

            @app.middleware("http")
            async def probe(request: Request, call_next: Any) -> Any:
                inner.append(request.method)
                return await call_next(request)

        app.middleware("http")(
            make_view_as_guard(
                self.auth,
                views=lambda: self.service,
                refusals=lambda: self.refusals,
                protective=self.protective,
                operations=_declared(),
                clock=self.rig.clock,
            )
        )
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def call(
        self, method: str, path: str, record: SessionRecord | None = None
    ) -> httpx.Response:
        headers = {} if record is None else {"Authorization": f"Bearer {record.id}"}
        return await self.client.request(method, path, headers=headers)

    def refused(self) -> list[dict[str, Any]]:
        return [kw for action, kw, _ in self.writer.records if action == VIEW_AS_REFUSED]


def _code(response: httpx.Response) -> tuple[int, str]:
    return response.status_code, response.json()["code"]


async def test_live_write_refused_one_record() -> None:
    """A write while viewing: `403 view_as_read_only`, the route never runs, and one refusal
    record is written ahead, naming the viewer, the viewer's session and the operation's template,
    never the target or the raw path."""
    gate = _Gate()
    record = await gate.rig.viewing()
    response = await gate.call("POST", "/orders", record)
    assert _code(response) == (403, "view_as_read_only") and gate.seen == []
    (refusal,) = gate.refused()
    assert (refusal["actor_user_id"], refusal["session_id"]) == (_VIEWER, record.id)
    assert refusal["after_state"] == {"method": "POST", "path": "/orders"}
    assert refusal["reason"] == "view_as_read_only"


async def test_held_read_refused_view_as_expired() -> None:
    """An ended context is held: a read answers `403 view_as_expired`, never the viewer's data."""
    gate = _Gate()
    record = await gate.rig.viewing()
    gate.rig.clock.now = _at(31)  # past `expires_at`: held, with no write
    response = await gate.call("GET", "/me", record)
    assert _code(response) == (403, "view_as_expired") and gate.seen == []
    assert [r["reason"] for r in gate.refused()] == ["view_as_expired"]


def _contract_own_operations() -> set[tuple[str, str]]:
    """The own operations the contract's "View-as session" section lists, read from its prose:
    each `METHOD /path`, and a bare `METHOD` sharing the path that follows it."""
    text = _spec()["info"]["description"]
    bullet = text.split("**The viewer's own operations.**", 1)[1].split("None of the rules", 1)[0]
    found: set[tuple[str, str]] = set()
    pending: list[str] = []
    for token in re.findall(r"`([^`]+)`", bullet):
        method, _, path = token.partition(" ")
        if not path:
            pending.append(method)
            continue
        found |= {(m, path) for m in (*pending, method)}
        pending.clear()
    return found


@pytest.mark.parametrize("held", [False, True], ids=["live", "held"])
async def test_own_ops_equal_contract_list_pass_live_and_held(held: bool) -> None:
    """Leaving view-as is one call that nothing refuses: each own operation passes, as the viewer,
    in a live context and in a held one."""
    assert _contract_own_operations() == OWN_OPERATIONS
    gate = _Gate()
    record = await gate.rig.viewing()
    gate.rig.clock.now = _at(31) if held else _at(5)
    for method, template in sorted(OWN_OPERATIONS):
        assert (await gate.call(method, _path(template), record)).status_code == 200
    assert len(gate.seen) == len(OWN_OPERATIONS) and gate.refused() == []
    phase = ViewAsPhase.HELD if held else ViewAsPhase.LIVE
    assert {(s.subject_user_id, s.phase) for _, _, s, _ in gate.seen} == {(_VIEWER, phase)}


async def test_order_after_csrf_idlelock_enrolment_session_read_only() -> None:
    """The guard sits after CSRF, the idle lock and the enrolment check and before the
    read-only/step-up guard; and before it refuses a write, a session in the read-only downgrade
    gets `session_read_only`, the session state the contract decides first."""
    from candleviewer import app as appmod
    from tests.unit.api.test_enrolment_only_guard import _middleware_name

    order = [_middleware_name(m) for m in appmod.create_app().user_middleware]  # outermost first
    names = ["CsrfMiddleware", "IdleLockMiddleware", "make_enrolment_only_guard"]
    assert [order.index(n) for n in names] == sorted(order.index(n) for n in names)
    at = order.index("make_view_as_guard")
    assert order.index("make_enrolment_only_guard") < at < order.index("make_read_only_guard")

    gate = _Gate()
    record = await gate.rig.viewing()
    gate.auth.step_up.read_only.add(str(record.id))
    response = await gate.call("POST", "/orders", record)
    assert _code(response) == (403, "session_read_only") and gate.refused() == []


async def test_refusal_issues_no_challenge_binds_no_key() -> None:
    """A refused write never reaches the layers the guard wraps: no step-up challenge (the
    read-only/step-up guard sits inside it) and no idempotency key (the route never runs), even
    on a step-up-gated route."""
    inner: list[str] = []
    gate = _Gate(inner=inner)
    record = await gate.rig.viewing()
    response = await gate.call("PUT", f"/users/{_TARGET}/roles", record)  # a step-up route
    assert _code(response) == (403, "view_as_read_only")
    assert inner == [] and gate.seen == []


async def test_refuses_with_step_up_unwired() -> None:
    """Without step-up there is no downgrade to check, and the write is refused all the same."""
    gate = _Gate()
    gate.auth.step_up_is_active = False
    record = await gate.rig.viewing()
    response = await gate.call("DELETE", "/alerts/x", record)
    assert _code(response) == (403, "view_as_read_only") and gate.auth.step_up.asked == 0


@pytest.mark.parametrize("failing", ["session", "eligibility", "label"])
async def test_store_failure_503(failing: str) -> None:
    """A session, eligibility or label read that fails answers `503 store_unavailable`: never a
    fallback scope, and the route never runs."""
    gate = _Gate()
    record = await gate.rig.viewing()
    if failing == "session":
        gate.auth.sessions.fails = RuntimeError("store down")
    else:
        gate.rig.ports.fails["ineligible" if failing == "eligibility" else "usernames"] = OSError()
    response = await gate.call("GET", "/me", record)
    assert _code(response) == (503, "store_unavailable") and gate.seen == []


def test_the_protective_writes_are_the_contracts_operations() -> None:
    """Each is named by its operationId and by its (METHOD, template), which must agree."""
    ids = {
        operation["operationId"]: (method.upper(), template)
        for template, item in _spec()["paths"].items()
        for method, operation in item.items()
        if isinstance(operation, dict) and "operationId" in operation
    }
    assert {i: ids[i] for i in PROTECTIVE_WRITES} == {
        i: operation for i, (operation, _) in PROTECTIVE_WRITES.items()
    }


@pytest.mark.parametrize("operation_id", sorted(PROTECTIVE_WRITES))
async def test_protective_ops_fail_closed_until_registered(operation_id: str) -> None:
    """A protective write is refused as any write until its handler registers (the tripwire);
    then it passes to the handler, as the viewer, live and held."""
    gate = _Gate()
    record = await gate.rig.viewing()
    (method, template), _ = PROTECTIVE_WRITES[operation_id]
    response = await gate.call(method, _path(template), record)
    assert _code(response) == (403, "view_as_read_only") and gate.seen == []
    gate.protective.register(operation_id)
    assert (await gate.call(method, _path(template), record)).status_code == 200
    gate.rig.clock.now = _at(31)
    assert (await gate.call(method, _path(template), record)).status_code == 200
    assert [(s.subject_user_id, s.phase) for _, _, s, _ in gate.seen] == [
        (_VIEWER, ViewAsPhase.LIVE),
        (_VIEWER, ViewAsPhase.HELD),
    ]


def test_only_a_protective_write_registers() -> None:
    with pytest.raises(ValueError, match="not a protective write"):
        ProtectiveWrites(_declared()).register("submitOrder")


async def test_a_live_read_passes_as_the_target_and_the_binding_ends_with_it() -> None:
    gate = _Gate()
    record = await gate.rig.viewing()
    assert (await gate.call("GET", "/me", record)).status_code == 200
    ((_, _, stamp, bound),) = gate.seen
    assert stamp == bound and (stamp.subject_user_id, stamp.target_user_id) == (_TARGET, _TARGET)
    assert (stamp.viewer_user_id, stamp.viewer_label) == (_VIEWER, "ana")
    assert current_view_as() is None


async def test_a_read_of_an_ineligible_context_ends_it_and_answers_view_as_expired() -> None:
    gate = _Gate()
    record = await gate.rig.viewing()
    gate.rig.ports.reason = ViewAsEndReason.TARGET_INELIGIBLE  # the target became an Owner
    response = await gate.call("GET", "/me", record)
    await gate.rig.settled()
    assert _code(response) == (403, "view_as_expired") and gate.seen == []
    assert gate.rig.held(record).end_reason == "target_ineligible"


async def test_a_context_that_reads_unbound_fails_closed() -> None:
    """`evaluate` reads `None` for a revoked row: never "no context", never the viewer's scope."""
    gate = _Gate()
    record = await gate.rig.viewing()

    class _Revoked:
        async def evaluate(self, record: SessionRecord, *, now: Any) -> None:
            return None

        async def viewer_label(self, record: SessionRecord) -> str:
            return "ana"

    gate.service = _Revoked()
    response = await gate.call("GET", "/me", record)
    assert _code(response) == (503, "store_unavailable") and gate.seen == []


@pytest.mark.parametrize("recorder", ["unwritable", "missing"])
async def test_a_refusal_that_cannot_be_recorded_answers_audit_unavailable(recorder: str) -> None:
    gate = _Gate()
    if recorder == "unwritable":
        gate.writer.mode = "fail"
    else:
        gate.refusals = None
    record = await gate.rig.viewing()
    response = await gate.call("POST", "/orders", record)
    assert _code(response) == (503, "audit_unavailable") and gate.seen == []


async def test_a_session_with_no_context_passes_untouched() -> None:
    gate = _Gate()
    plain = _session(UUID(int=7))
    assert await gate.rig.repo.create_session(plain) is not None
    assert (await gate.call("POST", "/orders", plain)).status_code == 200
    assert [stamp for _, _, stamp, _ in gate.seen] == [None] and gate.rig.ports.asked == 0


async def test_a_request_with_no_bearer_passes_untouched() -> None:
    gate = _Gate()
    assert (await gate.call("POST", "/orders")).status_code == 200
    assert [stamp for _, _, stamp, _ in gate.seen] == [None]


async def test_a_bearer_that_does_not_authenticate_passes_to_the_route() -> None:
    """The route answers it (401): the guard reads nothing more."""
    gate = _Gate()
    record = await gate.rig.viewing()
    gate.auth.sessions.fails = AuthError("expired")
    assert (await gate.call("POST", "/orders", record)).status_code == 200
    assert [stamp for _, _, stamp, _ in gate.seen] == [None] and gate.rig.ports.asked == 0


async def test_no_view_as_service_passes_untouched() -> None:
    """The fake backend: no context can exist there."""
    gate = _Gate()
    record = await gate.rig.viewing()
    gate.service = None
    assert (await gate.call("POST", "/orders", record)).status_code == 200
    assert [stamp for _, _, stamp, _ in gate.seen] == [None] and gate.rig.ports.asked == 0


async def test_a_cleared_context_passes_untouched() -> None:
    """Once the viewer has left, the session is the viewer's own again: a write passes,
    unstamped, with no record and no eligibility read."""
    gate = _Gate()
    record = await gate.rig.viewing()
    left = await gate.rig.service.leave(record, now=_at(1))
    assert left is not None and left.view_as is not None
    asked = gate.rig.ports.asked
    assert (await gate.call("POST", "/orders", record)).status_code == 200
    assert [stamp for _, _, stamp, _ in gate.seen] == [None]
    assert gate.refused() == [] and gate.rig.ports.asked == asked


@pytest.mark.parametrize("method", ["HEAD", "OPTIONS"])
async def test_a_live_head_or_options_passes_as_the_target_and_a_held_one_is_refused(
    method: str,
) -> None:
    gate = _Gate()
    record = await gate.rig.viewing()
    assert (await gate.call(method, "/me", record)).status_code == 200
    ((_, _, stamp, _),) = gate.seen
    assert stamp.subject_user_id == _TARGET
    gate.rig.clock.now = _at(31)
    response = await gate.call(method, "/me", record)
    assert response.status_code == 403 and len(gate.seen) == 1
    assert [r["reason"] for r in gate.refused()] == ["view_as_expired"]


async def test_an_own_operation_reads_no_eligibility() -> None:
    """Leaving view-as passes even when the eligibility read fails."""
    gate = _Gate()
    record = await gate.rig.viewing()
    gate.rig.ports.fails["ineligible"] = OSError()
    assert (await gate.call("DELETE", "/auth/session/view-as", record)).status_code == 200


async def test_an_own_operation_whose_label_cannot_be_read_passes_as_the_viewers_id() -> None:
    """Leave and logout never wait on the users row; any other request does (503)."""
    gate = _Gate()
    record = await gate.rig.viewing()
    gate.rig.ports.fails["usernames"] = OSError()
    assert (await gate.call("DELETE", "/auth/session/view-as", record)).status_code == 200
    ((_, _, stamp, _),) = gate.seen
    assert stamp.viewer_label == str(_VIEWER)
    assert _code(await gate.call("POST", "/orders", record)) == (503, "store_unavailable")


async def test_a_viewer_with_no_username_is_labelled_by_id() -> None:
    gate = _Gate()
    record = await gate.rig.viewing()
    gate.rig.ports.names = {}
    assert (await gate.call("GET", "/me", record)).status_code == 200
    ((_, _, stamp, _),) = gate.seen
    assert stamp.viewer_label == str(_VIEWER)


@pytest.mark.parametrize(
    ("raised", "answer"),
    [
        (RuntimeError("step-up store down"), (503, "store_unavailable")),
        (AuthError("no such session"), (403, "view_as_read_only")),
    ],
)
async def test_a_read_only_check_that_fails_is_never_a_pass(
    raised: Exception, answer: tuple[int, str]
) -> None:
    """A failed downgrade read answers 503; one that finds no session leaves the write refused."""
    gate = _Gate()
    record = await gate.rig.viewing()
    gate.auth.step_up.fails = raised
    assert _code(await gate.call("POST", "/orders", record)) == answer
    assert gate.seen == []


async def test_the_read_only_check_skips_exempt_paths_and_safe_methods() -> None:
    """A write to an exempt path that is not an own operation, and a held read, are refused
    for view-as, never `session_read_only`, and ask the downgrade nothing."""
    gate = _Gate()
    record = await gate.rig.viewing()
    gate.auth.step_up.read_only.add(str(record.id))
    assert _code(await gate.call("PUT", "/auth/logout", record)) == (
        403,
        "view_as_read_only",
    )
    gate.rig.clock.now = _at(31)
    assert _code(await gate.call("GET", "/me", record)) == (403, "view_as_expired")
    assert gate.auth.step_up.asked == 0
