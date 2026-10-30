"""`PUT /positions/{positionId}/leverage` (E29-T07 #915; 22 `setPositionLeverage`), on fakes: the
real router, the real `OmsReads` over the read world's in-memory store (`oms_reads_world`), and
the real `PositionLeverage` over the exchange's `FakeTradingPort`, behind a runtime double that
runs the change as a task, as `OmsRuntime.run` does. Each test names the Gherkin scenario or the
ruling it proves. No network (C-13.5)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final

import pytest
from fastapi import FastAPI
from fastapi.responses import Response
from httpx import ASGITransport, AsyncClient

from candleviewer.api.idempotency import IdempotencyCache
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.api.position_leverage import (
    LEVERAGE_PATH,
    make_position_leverage_router,
)
from candleviewer.api.recording_writes import WriteLimiter
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.exchange.base.errors import InstrumentFilterError, InsufficientMarginError
from candleviewer.exchange.base.fakes import FakeTradingPort
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.errors import OmsNotReady, StoreUnavailable, TradingDisabled
from candleviewer.oms.fakes import InMemoryTradingAccounts
from candleviewer.oms.leverage import LEVERAGE_ACTION, LeverageDeps, PositionLeverage
from candleviewer.oms.ports import FAILED, ArmToken, RequestRecord, Verdict
from candleviewer.oms.reads import OmsReads
from tests.unit.api.oms_reads_world import (
    ACCOUNT_A,
    ACCOUNT_B,
    ACCOUNT_LIVE,
    MISSING,
    Audit,
    ReadStore,
    Store,
    seeded,
)
from tests.unit.oms import command_rig as cr
from tests.unit.oms.submit_rig import Instruments, profile

SESSION: Final = uuid.UUID("5e551011-0000-4000-8000-000000000916")
#: Position 1 on A (granted), 2 on B (foreign), 4 on LIVE: the read world's seeded rows.
ON_A: Final = "00000000-0000-0000-0000-000000000d01"
ON_B: Final = "00000000-0000-0000-0000-000000000d02"
ON_LIVE: Final = "00000000-0000-0000-0000-000000000d04"
_WRITE: Final = frozenset({Permission.POSITIONS_READ, Permission.POSITIONS_WRITE})
USERS: Final = {
    who: uuid.uuid5(uuid.NAMESPACE_URL, f"cv-915-leverage/{who}")
    for who in ("owner", "manager", "reader", "viewer", "scoped")
}
#: `admin:write` beside the trade permissions: the Owner's alone among the seeded roles.
_ADMIN: Final = _WRITE | {Permission.ADMIN_WRITE}


def snapshot(who: str) -> PrincipalSnapshot:
    """The Owner; a Manager trading A, who holds no `admin:write` (Owner-only leverage, #915); a
    Viewer, who holds no `positions:write` (22 `x-permissions`). `scoped` and `reader` hold
    `admin:write` on a narrowed grant set, which no seeded role does today: they reach the scope
    checks the route keeps behind the capability (defence in depth), `scoped` trading A,
    `reader` viewing A without trading it."""
    if who == "owner":
        return PrincipalSnapshot(USERS[who], frozenset({"owner"}), frozenset(Permission))
    if who == "viewer":
        grant = AccountGrant(ACCOUNT_A, True, False, False)
        held = frozenset({Permission.POSITIONS_READ})
        return PrincipalSnapshot(USERS[who], frozenset({"viewer"}), held, (grant,))
    grant = AccountGrant(ACCOUNT_A, True, who != "reader", False)
    held = _WRITE if who == "manager" else _ADMIN
    return PrincipalSnapshot(USERS[who], frozenset({"manager"}), held, (grant,))


class Principals:
    """`SessionTradingPrincipalResolver`: a principal per bearer; `fail`: its store's 503."""

    def __init__(self, *, fail: bool = False) -> None:
        self.tokens = {who: TradingPrincipal(SESSION, snapshot(who)) for who in USERS}
        self.fail = fail

    async def resolve(self, request: Any) -> TradingPrincipal | None:
        if self.fail:
            raise StoreUnavailable
        return self.tokens.get(request.headers.get("authorization", "").partition(" ")[2])


class Arm:
    """`ArmRecords`: a live account needs a token, `armed`, presented (22 `ArmToken`)."""

    def __init__(self) -> None:
        self.asked: list[Environment] = []
        self.stopping = False

    def check(
        self, *, session_id: uuid.UUID, environment: Environment, token: ArmToken | None
    ) -> Verdict:
        self.asked.append(environment)
        if self.stopping:  # the runtime's stop began under the request
            raise OmsNotReady
        if environment == "live" and (token is None or token != ArmToken("armed")):
            return FAILED
        return "pass"


@dataclass
class Records:
    """The audit writer's `write`, each record with the venue calls made before it."""

    port: FakeTradingPort
    written: list[tuple[RequestRecord, int]] = field(default_factory=list)
    fail: bool = False

    def record_id(self, action: str, name: str) -> uuid.UUID:
        raise AssertionError("no keyed record on this path")

    async def write(self, record: Any) -> None:
        if self.fail:
            raise RuntimeError("the audit writer is not started")
        self.written.append((record, len(self.port.calls)))

    def kinds(self) -> list[tuple[str, str]]:
        return [(r.outcome, r.reason) for r, _ in self.written]


@dataclass
class Switches:
    refusal_of: TradingDisabled | OmsNotReady | None = None

    def refusal(
        self, account_id: AccountId, environment: Environment
    ) -> TradingDisabled | OmsNotReady | None:
        return self.refusal_of


@dataclass
class Runtime:
    """`OmsRuntime` as the route reads it: its readiness, its arm records, the change's service
    and `run`, which runs the change as a task it keeps (`refuse_run`: its stop begun)."""

    leverage: PositionLeverage
    route: Any
    readiness: str = "ok"
    refuse_run: bool = False
    tasks: set[asyncio.Task[Response]] = field(default_factory=set)

    def run(self, coro: Coroutine[Any, Any, Response]) -> asyncio.Task[Response]:
        if self.refuse_run:
            coro.close()
            raise OmsNotReady
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task


@dataclass
class _Route:
    arm_records: Arm


@dataclass
class World:
    environment: Environment = "demo"
    store: Store = field(default_factory=seeded)
    audit: Audit = field(default_factory=Audit)
    arm: Arm = field(default_factory=Arm)
    switches: Switches = field(default_factory=Switches)
    instruments: Instruments = field(default_factory=Instruments)
    oms_enabled: bool = True
    composed: bool = True
    reads_composed: bool = True
    readiness: str = "ok"
    refuse_run: bool = False
    rate: int = 20
    no_principals: bool = False
    principals_fail: bool = False
    cache: IdempotencyCache = field(default_factory=IdempotencyCache)
    port: FakeTradingPort = field(init=False)
    records: Records = field(init=False)

    def __post_init__(self) -> None:
        self.port = FakeTradingPort(environment=self.environment)
        self.records = Records(self.port)

    def runtime(self) -> Runtime:
        accounts = InMemoryTradingAccounts()
        seeded_envs: tuple[tuple[uuid.UUID, Environment], ...] = (
            (ACCOUNT_A, "demo"), (ACCOUNT_B, "demo"), (ACCOUNT_LIVE, "live"),
        )  # fmt: skip
        for account, env in seeded_envs:
            accounts.seed(cr.ref(cr.ACCOUNT, env), as_id=AccountId(account))
        held = profile(max_leverage_cap=Decimal(25), leverage=Decimal(10))
        service = PositionLeverage(LeverageDeps(
            accounts=_Refs(accounts), instruments=self.instruments, profiles=_Profile(held),
            ports=lambda env: self.port, switches=self.switches, audit=self.records,
            environment=self.environment,
        ))  # fmt: skip
        return Runtime(service, _Route(self.arm), self.readiness, self.refuse_run)

    def app(self) -> FastAPI:
        reads = OmsReads(ReadStore(self.store), self.environment) if self.reads_composed else None
        runtime = self.runtime() if self.composed else None
        app = FastAPI()
        app.include_router(make_position_leverage_router(
            None if self.no_principals else Principals(fail=self.principals_fail),
            lambda: runtime, reads, audit=self.audit, records=self.records,
            oms_enabled=lambda: self.oms_enabled, metrics=Metrics("demo"), replays=self.cache,
            limiter=WriteLimiter(rate_per_minute=self.rate, clock=lambda: 0.0),
        ))  # fmt: skip
        return app

    @asynccontextmanager
    async def client(self) -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=self.app()), base_url="http://t") as c:
            yield c

    def sent(self) -> list[Any]:
        return [c.request for c in self.port.calls if c.method == "set_leverage"]


class _Refs:
    """The account ref a position's account is signed for, of that account's own id."""

    def __init__(self, accounts: InMemoryTradingAccounts) -> None:
        self._accounts = accounts

    async def trading_account(self, account_id: AccountId) -> Any:
        found = await self._accounts.trading_account(account_id)
        return found.model_copy(update={"account_id": account_id})


@dataclass
class _Profile:
    held: Any

    async def get_effective_profile(self, account_id: uuid.UUID, profile_id: Any = None) -> Any:
        return self.held


def headers(who: str, *, key: uuid.UUID | None = None, arm: str | None = None) -> dict[str, str]:
    out = {"authorization": f"Bearer {who}"}
    out["idempotency-key"] = str(key or uuid.uuid4())
    if arm is not None:
        out["x-arm-token"] = arm
    return out


async def put(world: World, who: str, position: str = ON_A, body: Any = None, **kw: Any) -> Any:
    async with world.client() as client:
        return await client.put(
            LEVERAGE_PATH.replace("{positionId}", position),
            json={"leverage": "12.5"} if body is None else body, headers=headers(who, **kw),
        )  # fmt: skip


# --- The change -------------------------------------------------------------------------------


async def test_leverage_route_a_change_answers_the_position_with_the_new_leverage() -> None:
    world = World()
    answer = await put(world, "owner")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["id"], body["leverage"]) == (ON_A, "12.5")
    assert world.sent() == [(cr.SYMBOL, Decimal("12.5"))]
    [(ahead, before), (after, _)] = world.records.written
    assert before == 0  # C-2.9: recorded ahead of the venue's call
    assert (ahead.action, ahead.reason, after.reason) == (LEVERAGE_ACTION, "requested", "applied")


async def test_leverage_route_the_same_value_is_an_idempotent_200() -> None:
    """Ruling BQ-8: the venue's "not modified" answer is the change done."""
    world = World()
    world.port.script(
        "set_leverage", InstrumentFilterError("held", filter_name="leverage_not_modified")
    )
    answer = await put(world, "owner", body={"leverage": "10"})
    assert answer.status_code == 200 and answer.json()["leverage"] == "10"
    assert world.records.kinds()[-1] == ("success", "not_modified")


async def test_leverage_route_a_replay_answers_the_first_200_and_sends_once() -> None:
    """C-2.10: the same key and body is the stored answer, `Idempotency-Replayed`."""
    world, key = World(), uuid.uuid4()
    async with world.client() as client:
        path, body = LEVERAGE_PATH.replace("{positionId}", ON_A), {"leverage": "12.5"}
        first = await client.put(path, json=body, headers=headers("owner", key=key))
        again = await client.put(path, json=body, headers=headers("owner", key=key))
        other = await client.put(path, json={"leverage": "13"}, headers=headers("owner", key=key))
    assert (first.status_code, again.status_code) == (200, 200)
    assert again.headers["idempotency-replayed"] == "true" and again.json() == first.json()
    assert len(world.sent()) == 1
    assert (other.status_code, other.json()["code"]) == (409, "idempotency_key_reuse")
    assert world.records.kinds()[-1] == ("denied", "idempotency_key_reuse")


@pytest.mark.parametrize(
    ("leverage", "rule"), [("26", "max_leverage_cap"), ("101", "max_leverage")]
)
async def test_leverage_route_above_a_bound_is_422_unsent(leverage: str, rule: str) -> None:
    """BQ-8 / C-12.5: bounded server-side by the instrument and the profile, 422."""
    world = World()
    answer = await put(world, "owner", body={"leverage": leverage})
    assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed")
    assert rule in [e["rule"] for e in answer.json()["errors"]]
    assert world.sent() == []
    assert world.records.kinds() == [("denied", "validation_failed")]


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"leverage": 10},
        {"leverage": "1e2"},
        {"leverage": "10", "x": 1},
        [1],
        {"leverage": "-1"},
    ],
    ids=["missing", "number", "exponent", "extra", "array", "negative"],
)
async def test_leverage_route_a_body_22_refuses_is_422_unaudited_unsent(body: Any) -> None:
    world = World()
    answer = await put(world, "owner", body=body)
    assert (answer.status_code, answer.json()["code"]) == (422, "validation_failed")
    assert world.sent() == [] and world.records.written == []


async def test_leverage_route_a_body_past_its_cap_is_refused_unread() -> None:
    world = World()
    answer = await put(world, "owner", body={"leverage": "1" * 2_000})
    assert answer.status_code == 422 and answer.json()["errors"][0]["rule"] == "body_too_large"


# --- RBAC and scope (Gherkin "Scope is enforced server-side") --------------------------------


async def test_leverage_route_scope_a_viewer_is_forbidden_and_audited() -> None:
    world = World()
    answer = await put(world, "viewer")
    assert (answer.status_code, answer.json()["code"]) == (403, "forbidden")
    assert world.audit.actions() == ["rbac.denied"] and world.sent() == []


async def test_leverage_route_scope_a_foreign_position_is_404_as_a_missing_one_audited() -> None:
    """IDOR (SR-E29-13): a caller holding the capability, granted A only, asks for B's position:
    the same 404 as an id nothing holds, no state change, and the foreign one audited."""
    world = World()
    foreign = await put(world, "scoped", ON_B)
    missing = await put(world, "scoped", str(MISSING))
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert world.audit.actions() == ["rbac.denied"]
    assert world.audit.emitted[0]["object_id"] == str(ACCOUNT_B)
    assert world.sent() == [] and world.records.written == []


async def test_leverage_route_scope_a_view_only_grant_is_account_scope_denied() -> None:
    world = World()
    answer = await put(world, "reader")
    assert (answer.status_code, answer.json()["code"]) == (403, "account_scope_denied")
    assert world.audit.actions() == ["rbac.denied"] and world.sent() == []


@pytest.mark.parametrize(
    "position", [ON_A, ON_B, str(MISSING)], ids=["granted", "foreign", "absent"]
)
async def test_leverage_route_owner_only_a_manager_is_forbidden_before_any_read(
    position: str,
) -> None:
    """Owner-only leverage (#915, 22 `admin:write`): a Manager trading A is a capability 403 on
    its granted position, a foreign one and a missing one alike, audited, nothing read or sent."""
    world = World()
    answer = await put(world, "manager", position)
    assert (answer.status_code, answer.json()["code"]) == (403, "forbidden")
    assert answer.json()["required_permissions"] == ["positions:write", "admin:write"]
    assert world.audit.actions() == ["rbac.denied"]
    assert world.sent() == [] and world.records.written == []


async def test_leverage_route_scope_a_capable_caller_trades_the_granted_account() -> None:
    world = World()
    assert (await put(world, "scoped")).status_code == 200


async def test_leverage_route_scope_another_environments_position_is_never_read() -> None:
    """C-2.11: a demo process answers a live position's id as a missing one."""
    world = World()
    answer = await put(world, "owner", ON_LIVE)
    assert answer.status_code == 404 and world.sent() == []


# --- The arm token (22 `ArmToken`) -----------------------------------------------------------


async def test_leverage_route_arm_a_live_change_without_a_token_is_refused_and_audited() -> None:
    world = World(environment="live")
    answer = await put(world, "owner", ON_LIVE)
    assert (answer.status_code, answer.json()["code"]) == (403, "session_not_armed")
    assert world.sent() == []
    assert world.records.kinds() == [("denied", "session_not_armed")]
    armed = await put(world, "owner", ON_LIVE, arm="armed")
    assert armed.status_code == 200 and len(world.sent()) == 1


async def test_leverage_route_arm_a_demo_change_needs_no_token() -> None:
    world = World()
    assert (await put(world, "owner")).status_code == 200
    assert world.arm.asked == ["demo"]


# --- Gates, readiness, rate (BQ-15) -----------------------------------------------------------


async def test_leverage_route_the_flag_off_is_trading_disabled_recorded() -> None:
    world = World(oms_enabled=False)
    answer = await put(world, "owner")
    assert (answer.status_code, answer.json()["code"]) == (403, "trading_disabled")
    assert world.records.kinds() == [("denied", "trading_disabled")] and world.sent() == []


async def test_leverage_route_the_kill_switch_refuses_before_anything_is_sent() -> None:
    """C-2.21: the switches are consulted synchronously, before the venue."""
    world = World(switches=Switches(TradingDisabled()))
    answer = await put(world, "owner")
    assert (answer.status_code, answer.json()["code"]) == (403, "trading_disabled")
    assert world.sent() == []


async def test_leverage_route_the_rate_past_its_bound_is_429_with_retry_after() -> None:
    world = World(rate=1)
    async with world.client() as client:
        path = LEVERAGE_PATH.replace("{positionId}", ON_A)
        first = await client.put(path, json={"leverage": "12"}, headers=headers("owner"))
        second = await client.put(path, json={"leverage": "13"}, headers=headers("owner"))
    assert first.status_code == 200
    assert (second.status_code, second.json()["code"]) == (429, "rate_limited")
    assert int(second.headers["retry-after"]) >= 1 and len(world.sent()) == 1


@pytest.mark.parametrize(
    ("change", "status", "code"),
    [
        (lambda w: setattr(w, "composed", False), 501, "not_implemented"),
        (lambda w: setattr(w, "readiness", "starting"), 503, "oms_not_ready"),
        (lambda w: setattr(w, "refuse_run", True), 503, "oms_not_ready"),
        (lambda w: setattr(w, "reads_composed", False), 503, "store_unavailable"),
        (lambda w: setattr(w.store, "fail", True), 503, "store_unavailable"),
        (lambda w: setattr(w.records, "fail", True), 503, "audit_unavailable"),
    ],
    ids=["no_oms", "not_ready", "stopping", "no_reads", "store", "audit"],
)
async def test_leverage_route_an_unavailable_dependency_sends_nothing(
    change: Any, status: int, code: str
) -> None:
    world = World()
    change(world)
    answer = await put(world, "owner")
    assert (answer.status_code, answer.json()["code"]) == (status, code)
    assert world.sent() == []


async def test_leverage_route_a_venue_refusal_is_502_with_its_code_only() -> None:
    world = World()
    world.port.script("set_leverage", InsufficientMarginError("no margin", exchange_ret_code=7))
    answer = await put(world, "owner")
    assert answer.status_code == 502
    assert answer.json()["exchange"] == {"ret_code": 7} and "no margin" not in answer.text


async def test_leverage_route_a_missing_key_is_400_recorded() -> None:
    world = World()
    async with world.client() as client:
        answer = await client.put(
            LEVERAGE_PATH.replace("{positionId}", ON_A), json={"leverage": "12"},
            headers={"authorization": "Bearer owner"},
        )  # fmt: skip
    assert (answer.status_code, answer.json()["code"]) == (400, "validation_failed")
    assert world.records.kinds() == [("denied", "validation_failed")]


async def test_leverage_route_a_malformed_id_is_400_and_no_principal_is_401() -> None:
    world = World()
    assert (await put(world, "owner", "x")).status_code == 400
    assert (await put(world, "nobody")).status_code == 401


async def test_leverage_route_a_second_request_under_a_running_key_is_in_flight() -> None:
    """The in-flight guard (22 Idempotency): the key's first change still running is 409."""
    world, key, gate, entered = World(), uuid.uuid4(), asyncio.Event(), asyncio.Event()

    async def slow(account: Any, symbol: Any, leverage: Decimal) -> None:
        entered.set()
        await gate.wait()

    world.port.set_leverage = slow  # type: ignore[method-assign]  # held until the gate opens
    async with world.client() as client:
        path, body = LEVERAGE_PATH.replace("{positionId}", ON_A), {"leverage": "12"}
        sent = headers("owner", key=key)
        first = asyncio.ensure_future(client.put(path, json=body, headers=sent))
        await entered.wait()  # the first change is at the venue
        second = await client.put(path, json=body, headers=headers("owner", key=key))
        gate.set()
        assert (await first).status_code == 200
    assert (second.status_code, second.json()["code"]) == (409, "idempotency_in_flight")
    assert second.headers["retry-after"] == "1"


# --- Fail-closed edges ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "status", "code"),
    [
        (lambda w: setattr(w, "no_principals", True), 501, "not_implemented"),
        (lambda w: setattr(w, "principals_fail", True), 503, "store_unavailable"),
        (lambda w: setattr(w.arm, "stopping", True), 503, "oms_not_ready"),
        (lambda w: setattr(w, "switches", Switches(OmsNotReady())), 503, "oms_not_ready"),
    ],
    ids=["no_principals", "principals_store", "arm_stopping", "switches_fenced"],
)
async def test_leverage_route_an_edge_before_the_venue_sends_nothing(
    change: Any, status: int, code: str
) -> None:
    world = World()
    change(world)
    answer = await put(world, "owner")
    assert (answer.status_code, answer.json()["code"]) == (status, code)
    assert world.sent() == []


@pytest.mark.parametrize(
    ("who", "position", "code"),
    [("viewer", ON_A, "forbidden"), ("manager", ON_A, "forbidden"),
     ("scoped", ON_B, "not_found"), ("reader", ON_A, "account_scope_denied")],
)  # fmt: skip
async def test_leverage_route_scope_a_refusal_stands_when_its_record_cannot_be_written(
    who: str, position: str, code: str
) -> None:
    """A refusal whose `rbac.denied` cannot be written is still refused (never a pass)."""
    world = World()
    world.audit.fail = True
    answer = await put(world, who, position)
    assert answer.json()["code"] == code and world.sent() == []


async def test_leverage_route_an_unrecorded_arm_refusal_is_audit_unavailable() -> None:
    """C-2.9: no refusal is answered unrecorded; the key stays unbound."""
    world = World(environment="live")
    world.records.fail = True
    answer = await put(world, "owner", ON_LIVE)
    assert (answer.status_code, answer.json()["code"]) == (503, "audit_unavailable")
    assert world.sent() == [] and len(world.cache) == 0


async def test_leverage_route_a_full_in_flight_guard_is_429(monkeypatch: Any) -> None:
    import candleviewer.api.position_leverage as route

    monkeypatch.setattr(route, "MAX_IN_FLIGHT", 0)
    world = World()
    answer = await put(world, "owner")
    assert (answer.status_code, answer.json()["code"]) == (429, "rate_limited")
    assert answer.headers["retry-after"] == "1" and world.sent() == []
