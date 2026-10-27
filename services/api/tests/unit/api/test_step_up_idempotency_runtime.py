"""AC "Refusal binds no idempotency key", runtime half (#2304; the contract half is
`tests/contract/test_step_up_challenge_contract.py::test_idempotency_section_states_the_binding_point`).

On every mounted operation the contract marks `x-idempotency: required`, a request refused at the
step-up gate (`403 step_up_required`) or at the idle-lock gate (`401 session_idle_locked`) stores
no idempotency record and executes nothing, so the identical re-send, once the gate is satisfied,
is a first submission: it executes once and is not answered from the idempotency store.

Each route runs its real router over the fakes its own unit tests drive it with, behind the real
gates in `create_app()`'s order: `IdleLockMiddleware` outside, the read-only/step-up guard
(`make_read_only_guard`) inside it, over the real `StepUpService` of
`test_step_up_challenge_router._world`. The idle lock is the one seam: the store the middleware
reads locks every bearer on demand. `rotateAuditSigningKey` runs through the real `create_app()`
instead (its own test's world), its session locked by the real idle deadline. No network: the key
import answers from its recorded fixtures through a mock transport (`respx` answers nothing else).
"""

from __future__ import annotations

import asyncio
import functools
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.types import ASGIApp

from candleviewer.accounts.key_age import KeyRotationPolicy
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.exchange_keys import make_exchange_keys_router
from candleviewer.api.idempotency import IdempotencyCache
from candleviewer.api.idle_lock import IdleLockMiddleware
from candleviewer.api.order_cancel_all import CANCEL_ALL_PATH
from candleviewer.api.rules_actor import SessionRulesActorResolver, make_rules_audit
from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.api.step_up import (
    HANDLER_GATED_ROUTES,
    dangerous_action_class,
    make_read_only_guard,
    request_elevation,
)
from candleviewer.app import create_app
from candleviewer.auth.errors import SessionIdleLocked
from candleviewer.auth.models import SessionRecord
from candleviewer.auth.session_service import MIN_IDLE_TIMEOUT_S
from candleviewer.key_import_wiring import KeyImports
from candleviewer.rules.manager import InMemoryRuleStore, RulesManager
from candleviewer.rules.vocabulary import default_registry
from tests.contract.test_create_api_key_provider import Resolver as KeyResolver
from tests.contract.test_step_up_challenge_contract import _IDEMPOTENCY_REQUIRED
from tests.rules.test_rules_routes import LIVE, _ir
from tests.unit.accounts.test_key_import import ACCT
from tests.unit.accounts.test_key_selfcheck import EGRESS
from tests.unit.api import test_order_amend_route as amend
from tests.unit.api import test_order_cancel_all_route as cancel_all
from tests.unit.api import test_order_exits_route as exits
from tests.unit.api import test_orders_route as orders
from tests.unit.api.test_audit_signing_rotate import OWNER as KEYS_MANAGE
from tests.unit.api.test_audit_signing_rotate import _deployed, _Rot
from tests.unit.api.test_invites_create_app_e2e import _login
from tests.unit.api.test_step_up_challenge_router import _IDEM, _World, _world
from tests.unit.api.test_step_up_router import _PW, _T0, _code, _Sessions
from tests.unit.api.test_step_up_rules_route import _Identity
from tests.unit.credentials_m2._vectors import API_KEY, API_SECRET
from tests.unit.oms import submit_rig as sr
from tests.unit.test_key_import_wiring import Rig as KeyRig

_SPEC = load_openapi_spec()
_ARM, _SIMULATE = {"mode": "armed"}, {"mode": "simulate"}
_KEY_BODY = {"api_key": API_KEY, "api_secret": API_SECRET, "label": "main-trade"}
_ROTATE = "/admin/keys/audit-signing/rotate"


def _mounted_keyed_operations() -> set[tuple[str, str]]:
    """(METHOD, path) of every operation `create_app()` serves that 22 marks `required`."""
    served = served_operations(create_app())
    keyed = {(method.upper(), path) for method, path in _IDEMPOTENCY_REQUIRED}
    return keyed & served


def _step_up_gated(method: str, path: str) -> bool:
    """Whether the operation demands a step-up: a path row (a concrete path stands in for the
    template's parameters) or a handler row of the registry."""
    concrete = path.replace("{", "").replace("}", "")
    handler = any((m, p) == (method, path) for m, p, _ in HANDLER_GATED_ROUTES)
    return handler or dangerous_action_class(method, concrete) is not None


class _Locks:
    """The session store `IdleLockMiddleware` reads: while `locked`, every bearer's session is
    idle-locked, as `authenticate_access_token` refuses one past its idle deadline; otherwise
    the harness sessions answer."""

    def __init__(self, w: _World) -> None:
        self._w, self.locked = w, False

    async def authenticate_access_token(self, token: str) -> SessionRecord:
        if self.locked:
            raise SessionIdleLocked("idle", idle_locked_at=_T0)
        record: SessionRecord = await self._w.auth.sessions.authenticate_access_token(token)
        return record


@dataclass
class _Case:
    """One keyed route behind the gates. `send` sends the one request under test, unchanged each
    time; `executed` counts what it did (orders sent, keys imported, rules armed or disarmed);
    `records` counts the idempotency records held under its key, `binds` of them once it ran."""

    send: Callable[[], Awaitable[httpx.Response]]
    executed: Callable[[], int]
    records: Callable[[], int]
    ok: int
    step_up: Callable[..., Awaitable[httpx.Response]]
    lock: Callable[[bool], Awaitable[None]]
    binds: int = 1  # the records a first submission binds


def _gated(w: _World, app: FastAPI, locks: _Locks) -> ASGIApp:
    """`app` behind the guard and the idle lock, in `create_app()`'s order."""
    app.middleware("http")(make_read_only_guard(w.auth, w.audit))
    return IdleLockMiddleware(app, sessions=lambda: locks, spec=_SPEC)


def _client(app: ASGIApp, peer: tuple[str, int] = ("127.0.0.1", 50000)) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, client=peer), base_url="http://t")


@dataclass
class _Env:
    """What a builder builds over: the step-up world, the idle-lock seam, the exit stack the
    clients and rigs live on, and `monkeypatch` (the `create_app()` world patches its builders)."""

    w: _World
    locks: _Locks
    stack: AsyncExitStack
    monkeypatch: pytest.MonkeyPatch


#: A router-level builder: (step-up world, idle-lock seam, exit stack, gate under test) -> case.
_Builder = Callable[[_World, _Locks, AsyncExitStack, str], Awaitable[_Case]]


def _case(
    w: _World, locks: _Locks, client: AsyncClient, send: Callable[[], Awaitable[httpx.Response]],
    executed: Callable[[], int], records: Callable[[], int], ok: int, binds: int = 1,
) -> _Case:  # fmt: skip
    async def step_up(**body: Any) -> httpx.Response:
        payload = {"code": _code(w.seed, w.clock), "password": _PW, **body}
        return await client.post("/auth/step-up", headers=w.h("owner"), json=payload)

    async def lock(locked: bool) -> None:
        locks.locked = locked

    return _Case(send, executed, records, ok, step_up, lock, binds)


async def _harness(w: _World, stack: AsyncExitStack) -> AsyncClient:
    """A client of the harness app, which serves `POST /auth/step-up` over the same service."""
    return await stack.enter_async_context(_client(w.client.app))


async def _place_order(w: _World, locks: _Locks, stack: AsyncExitStack, gate: str) -> _Case:
    world = orders.World()
    client = await stack.enter_async_context(_client(_gated(w, world.app(), locks)))
    sent = orders.request("owner")

    def records() -> int:  # the 24 h record and the anchor the lookup binds
        return len(world.cache) + len(world.oms.anchors.calls)

    async def send() -> httpx.Response:
        return await client.post("/orders", **sent)

    def executed() -> int:
        return len(world.oms.submission.submitted)

    return _case(w, locks, await _harness(w, stack), send, executed, records, 202, binds=2)


async def _cancel_all(w: _World, locks: _Locks, stack: AsyncExitStack, gate: str) -> _Case:
    world = cancel_all.World()
    client = await stack.enter_async_context(_client(_gated(w, world.app(), locks)))
    sent = cancel_all._args("owner", {}, orders.KEY)

    async def send() -> httpx.Response:
        return await client.post(CANCEL_ALL_PATH, **sent)

    def executed() -> int:  # one run per first submission
        return len(world.oms.tasks)

    return _case(w, locks, await _harness(w, stack), send, executed, world.cache.__len__, 200)


def _exit_headers() -> dict[str, str]:
    return {
        "authorization": "Bearer owner",
        "x-correlation-id": str(exits.TRACE),
        "idempotency-key": str(exits.KEY),
    }


async def _cancel_order(w: _World, locks: _Locks, stack: AsyncExitStack, gate: str) -> _Case:
    world, machines, row, _ = await exits.scripted_world("submitted", "cancelled")
    app = _gated(w, world.app(), locks)
    client = await stack.enter_async_context(_client(app, (exits.PEER, 4321)))

    async def send() -> httpx.Response:
        return await client.delete(f"/orders/{row.id}", headers=_exit_headers())

    def executed() -> int:
        return machines.sent.count("CANCEL")

    return _case(w, locks, await _harness(w, stack), send, executed, world.cache.__len__, 202)


async def _amend_order(w: _World, locks: _Locks, stack: AsyncExitStack, gate: str) -> _Case:
    rig = await stack.enter_async_context(sr.rigged())
    rig.store.seed_owner(amend.OWNER)
    world, row = await amend.amendable(rig)
    app = _gated(w, world.app(), locks)
    client = await stack.enter_async_context(_client(app, (exits.PEER, 4321)))

    async def send() -> httpx.Response:
        body = {"price": "60100"}
        return await client.patch(f"/orders/{row.id}", json=body, headers=_exit_headers())

    def executed() -> int:
        return len(amend.amends(rig))

    return _case(w, locks, await _harness(w, stack), send, executed, world.cache.__len__, 202)


async def _import_key(w: _World, locks: _Locks, stack: AsyncExitStack, gate: str) -> _Case:
    rig = KeyRig()
    await rig.boot()
    rig.flow = rig.importer()
    cache, app = IdempotencyCache(), FastAPI()
    app.include_router(
        make_exchange_keys_router(
            KeyImports(rig.flow, lambda: asyncio.sleep(0)), rig, KeyResolver(),
            egress_ip=EGRESS, rotation=KeyRotationPolicy(), replays=cache,
            # Handler-gated since #2304 slice 3b: the router demands `keys` itself, through the
            # harness's real step-up service, as `create_app()` wires it.
            elevation=request_elevation(w.auth, "keys"),
        )
    )  # fmt: skip
    client = await stack.enter_async_context(_client(_gated(w, app, locks)))
    headers = {"Authorization": "Bearer owner", "Idempotency-Key": _IDEM}
    path = f"/exchange-accounts/{ACCT}/keys"

    async def send() -> httpx.Response:
        with respx.mock():  # nothing but the rig's recorded transport answers
            return await client.post(path, json=_KEY_BODY, headers=headers)

    def executed() -> int:  # each import seals one key
        return len(rig.m2.rows)

    case = _case(w, locks, await _harness(w, stack), send, executed, cache.__len__, 201)
    if gate == "idle_lock":  # every other gate admits the request: `keys` is elevated
        assert (await case.step_up(action_class="keys")).status_code == 200
    return case


async def _set_rule_mode(w: _World, locks: _Locks, stack: AsyncExitStack, gate: str) -> _Case:
    """A live-scoped rule, simulated and ready to arm (`test_step_up_rules_route._armable`), on
    the harness app, for the step-up case, which arms it (the live arm is the gated branch); for
    the idle-lock case a new rule, which it simulates (no step-up gates that)."""
    trail: list[str] = []
    to_writer = make_rules_audit(w.audit)

    async def audit(action: str, payload: dict[str, Any]) -> None:
        trail.append(action)
        await to_writer(action, payload)

    async def broadcast(payload: dict[str, Any]) -> None:
        return None

    mgr = RulesManager(InMemoryRuleStore(), default_registry(), audit=audit, broadcast=broadcast)
    resolver = SessionRulesActorResolver(
        lambda: _Sessions(w.sessions), lambda: w.auth.step_up, _Identity(), w.audit
    )
    app = w.client.app
    assert isinstance(app, FastAPI)  # not yet serving: routes may be added
    app.include_router(make_rules_crud_router(lambda: mgr, resolver.resolve))
    gated = IdleLockMiddleware(app, sessions=lambda: locks, spec=_SPEC)  # the guard is mounted
    client = await stack.enter_async_context(_client(gated))
    made = await client.post("/rules", headers=w.h(), json={"ir": _ir(scope=LIVE, name="r0")})
    rid = str(made.json()["id"])
    body, action = (_ARM, "rule.armed") if gate == "step_up" else (_SIMULATE, "rule.simulated")
    if gate == "step_up":
        simulate = w.h() | {"Idempotency-Key": f"simulate-{rid}"}
        ready = await client.put(f"/rules/{rid}/mode", headers=simulate, json=_SIMULATE)
        assert ready.status_code == 200, ready.text
        versions = (await client.get(f"/rules/{rid}/versions", headers=w.h())).json()
        await mgr.record_simulation(rid, versions["items"][0]["ir_hash"], 5, 0.0)
    before = trail.count(action)

    async def send() -> httpx.Response:
        return await client.put(f"/rules/{rid}/mode", headers=w.h(), json=body)

    def records() -> int:
        return sum(1 for key in mgr._idem if f":{_IDEM}:" in key)

    def executed() -> int:
        return trail.count(action) - before

    return _case(w, locks, client, send, executed, records, 200)


async def _rotate_signing_key(env: _Env, gate: str) -> _Case:
    """`rotateAuditSigningKey` through the real `create_app()` (`test_audit_signing_rotate`): its
    record is durable, the new key row naming the request's key (`client_ref`). The session idles
    out at the shortest deadline, inside the access token's lifetime, so the real store refuses it
    as idle-locked; the real service lifts the lock with the password. The `keys` window does not
    outlast the lock, so satisfying it takes a step-up too."""
    rot: _Rot = await _deployed(env.monkeypatch)
    sessions = rot.w.auth.sessions
    if gate == "idle_lock":  # `_login` mints the session: at the shortest idle deadline
        short = functools.partial(sessions.mint, idle_timeout_s=MIN_IDLE_TIMEOUT_S)
        env.monkeypatch.setattr(sessions, "mint", short)
    token, ref = await _login(rot.w, "owner", KEYS_MANAGE), uuid.uuid4()
    session_id = str((await sessions.authenticate_access_token(token)).id)

    async def send() -> httpx.Response:
        sent: httpx.Response = rot.post(token, ref)
        return sent

    async def step_up(**body: Any) -> httpx.Response:
        answered: httpx.Response = rot.w.elevate(token, **body)
        return answered

    async def password(given: str) -> bool:
        return given == _PW

    async def lock(locked: bool) -> None:
        if locked:
            rot.w.clock.now += timedelta(seconds=MIN_IDLE_TIMEOUT_S + 1)
            return
        await sessions.unlock(session_id, password=_PW, check=password)
        assert (await step_up(action_class="keys")).status_code == 200

    def records() -> int:
        return sum(1 for row in rot.keys.rows if row.get("client_ref") == str(ref))

    def executed() -> int:  # the boot's key, then one per rotation
        return len(rot.keys.rows) - 1

    return _Case(send, executed, records, 200, step_up, lock)


def _router_level(build: _Builder) -> Callable[[_Env, str], Awaitable[_Case]]:
    @functools.wraps(build)
    async def built(env: _Env, gate: str) -> _Case:
        return await build(env.w, env.locks, env.stack, gate)

    return built


#: Every mounted keyed operation's case. `test_every_mounted_keyed_operation_has_a_case` keeps
#: this the set `create_app()` serves, so a newly mounted one fails until it is added here.
_CASES: dict[tuple[str, str], Callable[[_Env, str], Awaitable[_Case]]] = {
    ("POST", "/exchange-accounts/{accountId}/keys"): _router_level(_import_key),
    ("POST", "/orders"): _router_level(_place_order),
    ("PATCH", "/orders/{orderId}"): _router_level(_amend_order),
    ("DELETE", "/orders/{orderId}"): _router_level(_cancel_order),
    ("POST", "/orders/cancel-all"): _router_level(_cancel_all),
    ("PUT", "/rules/{ruleId}/mode"): _router_level(_set_rule_mode),
    ("POST", _ROTATE): _rotate_signing_key,
}
_STEP_UP_CASES = sorted(op for op in _CASES if _step_up_gated(*op))
_IDS = {op: f"{op[0]} {op[1]}" for op in _CASES}


@asynccontextmanager
async def _built(
    op: tuple[str, str], gate: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[_Case]:
    w = await _world()
    w.sessions["owner"] = w.sessions["tok"]  # the routes' fakes name the caller `owner`
    async with AsyncExitStack() as stack:
        yield await _CASES[op](_Env(w, _Locks(w), stack, monkeypatch), gate)


def test_every_mounted_keyed_operation_has_a_case() -> None:
    assert set(_CASES) == _mounted_keyed_operations()


def test_the_step_up_cases_are_the_gated_keyed_operations() -> None:
    """The registry decides which keyed operations take a step-up; today the key import, the
    signing-key rotation (path rows, `keys`) and the rule mode (handler row, `live_enablement`)."""
    assert _STEP_UP_CASES == [
        ("POST", "/admin/keys/audit-signing/rotate"),
        ("POST", "/exchange-accounts/{accountId}/keys"),
        ("PUT", "/rules/{ruleId}/mode"),
    ]


@pytest.mark.parametrize("op", _STEP_UP_CASES, ids=[_IDS[op] for op in _STEP_UP_CASES])
async def test_a_request_refused_a_step_up_binds_no_key_and_its_resend_executes_once(
    op: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _built(op, "step_up", monkeypatch) as case:
        refused = await case.send()
        assert (refused.status_code, refused.json()["code"]) == (403, "step_up_required")
        assert (case.executed(), case.records()) == (0, 0)
        granted = await case.step_up(challenge_id=refused.json()["challenge_id"])
        assert granted.status_code == 200, granted.text
        resent = await case.send()
        assert resent.status_code == case.ok, resent.text
        assert "idempotency-replayed" not in resent.headers  # a first submission, not a replay
        assert (case.executed(), case.records()) == (1, case.binds)


@pytest.mark.parametrize("op", sorted(_CASES), ids=[_IDS[op] for op in sorted(_CASES)])
async def test_a_request_refused_as_idle_locked_binds_no_key_and_its_resend_executes_once(
    op: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _built(op, "idle_lock", monkeypatch) as case:
        await case.lock(True)
        refused = await case.send()
        assert (refused.status_code, refused.json()["code"]) == (401, "session_idle_locked")
        assert (case.executed(), case.records()) == (0, 0)
        await case.lock(False)
        resent = await case.send()
        assert resent.status_code == case.ok, resent.text
        assert "idempotency-replayed" not in resent.headers  # a first submission, not a replay
        assert (case.executed(), case.records()) == (1, case.binds)
