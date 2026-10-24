"""`POST /orders` (E29-T04 #913 slice 3F; 24 Sec.8.4 "The route", 22 `placeOrder`), on fakes: the
router on a bare app, so each step is driven alone. The runtime, the pipeline, the anchors and the
reads are recording doubles; the bodies are validated against 22 by `test_order_acceptance`'s
helpers. The view-as case runs the real app (`create_app`) over the RBAC pack's world."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import Response
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY, generate_latest
from structlog.testing import capture_logs

from candleviewer.accounts.errors import AccountNotFoundError
from candleviewer.accounts.trade_groups import ScopedTradeGroup, TradeGroupWithLegs
from candleviewer.api.idempotency import IdempotencyCache, request_fingerprint
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.api.orders import MAX_ORDER_BODY_BYTES, make_orders_router
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.domain.order_entry import OrderEntryRefusal
from candleviewer.domain.primitives import Environment, GroupId
from candleviewer.observability.correlation import CorrelationMiddleware
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.errors import (
    AccountScopeDenied,
    OmsError,
    OmsNotReady,
    OrderEntryRefused,
    ProfileNotFound,
    RiskRefused,
    StoreUnavailable,
    TradingDisabled,
)
from candleviewer.oms.idempotency import Fresh, InFlight, KeyReuse, Lookup, Replay
from candleviewer.oms.ports import (
    FAILED,
    PASSED,
    ArmToken,
    KeyedRecord,
    RequestRecord,
    StopOffset,
    Verdict,
)
from candleviewer.oms.submit import OrderRequest, SubmitContext, SubmitOutcome
from candleviewer.storage.repositories.idempotency_anchors import AnchorRow
from candleviewer.storage.repositories.orders import OrderRow
from tests.contract.rbac.rbac_harness import GRANTED, bearer_viewing, build_world
from tests.unit.api.test_order_acceptance import (
    ACCOUNT,
    USER,
    first_entry,
    first_reduce_only,
    read_entry,
    replay_of,
    stored,
    validate,
)

MANAGER = UUID("4b000000-0000-4000-8000-000000000002")
VIEWER = UUID("4b000000-0000-4000-8000-000000000003")
FOREIGN = UUID("a1000000-0000-4000-8000-000000000009")
SESSION = UUID("5e551011-0000-4000-8000-000000000002")
KEY = UUID("9b2f7c1e-4d3a-4f6b-8a0c-5e1d2c3b4a59")
TRACE = UUID("7d3c9a2e-1f4b-4c8d-9e0a-2b3c4d5e6f70")  # an `X-Correlation-Id`, a UUIDv4
T0 = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)
GATE = OrderEntryRefusal("no_active_key", "The account has no verified active key.")
_EVERY = frozenset(Permission)
_TRADE = frozenset({Permission.ORDERS_WRITE, Permission.ORDERS_READ})
BODY: dict[str, Any] = {
    "exchange_account_id": str(ACCOUNT), "symbol": "BTCUSDT", "side": "buy",
    "order_type": "limit", "price": "60000", "sizing": {"mode": "fixed_qty", "qty": "0.010"},
    "stop_loss": {"unit": "price", "value": "58000"},
}  # fmt: skip


def snapshot(who: str, *, trade: bool = True, frozen: bool = False) -> PrincipalSnapshot:
    """The Owner; a Manager granted `ACCOUNT` (`trade`: may trade it); a viewer."""
    if who == "owner":
        return PrincipalSnapshot(USER, frozenset({"owner"}), _EVERY)
    if who == "viewer":
        return PrincipalSnapshot(VIEWER, frozenset({"viewer"}), frozenset({Permission.ORDERS_READ}))
    grant = AccountGrant(ACCOUNT, True, trade, frozen)
    return PrincipalSnapshot(MANAGER, frozenset({"manager"}), _TRADE, (grant,))


class Principals:
    """`SessionTradingPrincipalResolver`: a principal per bearer token; `fail`: the store's 503."""

    def __init__(self) -> None:
        self.tokens = {who: TradingPrincipal(SESSION, snapshot(who)) for who in ("owner", "viewer")}
        self.tokens["manager"] = TradingPrincipal(SESSION, snapshot("manager"))
        self.tokens["view_only"] = TradingPrincipal(SESSION, snapshot("manager", trade=False))
        self.tokens["frozen"] = TradingPrincipal(SESSION, snapshot("manager", frozen=True))
        self.fail = False

    async def resolve(self, request: Any) -> TradingPrincipal | None:
        if self.fail:
            raise StoreUnavailable
        return self.tokens.get(request.headers.get("authorization", "").partition(" ")[2])


@dataclass
class Audit:
    """The audit writer: `rbac.denied` (`emit`) and the route's other refusals (`write`)."""

    emitted: list[dict[str, Any]] = field(default_factory=list)
    written: list[RequestRecord] = field(default_factory=list)
    fail: bool = False

    async def emit(self, action: str, **fields: Any) -> None:
        if self.fail:
            raise RuntimeError("the audit writer is not started")
        self.emitted.append({"action": action, **fields})

    def record_id(self, action: str, name: str) -> UUID:
        raise AssertionError("the route writes no keyed record")

    async def write(self, record: KeyedRecord | RequestRecord) -> None:
        if self.fail:
            raise RuntimeError("the audit writer is not started")
        assert isinstance(record, RequestRecord)
        self.written.append(record)

    def actions(self) -> list[str]:
        return [e["action"] for e in self.emitted] + [r.action for r in self.written]


@dataclass
class Accounts:
    """The existence read: `envs` names each account that exists, with its environment."""

    envs: dict[UUID, Environment] = field(
        default_factory=lambda: {ACCOUNT: "demo", FOREIGN: "demo"}
    )
    fail: bool = False

    async def environment_of(self, account_id: UUID) -> Environment:
        if self.fail:
            raise StoreUnavailable
        if account_id not in self.envs:
            raise AccountScopeDenied
        return self.envs[account_id]


@dataclass
class Switches:
    """`TradingSwitches`: `refuses` is its answer; `asked` counts the asks."""

    refuses: TradingDisabled | None = None
    asked: int = 0

    def refusal(self, account_id: UUID, environment: str) -> TradingDisabled | None:
        self.asked += 1
        return self.refuses


@dataclass
class Orders:
    """The order read: `rows` by id, each under its own account only."""

    rows: dict[UUID, OrderRow] = field(default_factory=dict)

    async def get(self, account_id: UUID, order_id: UUID) -> OrderRow | None:
        row = self.rows.get(order_id)
        return row if row is not None and row.exchange_account_id == account_id else None


@dataclass
class Groups:
    """The scoped group read: `found`, else every read misses as the store's does."""

    found: TradeGroupWithLegs | None = None
    scopes: list[Any] = field(default_factory=list)

    async def get(self, scope: Any, group_id: UUID) -> ScopedTradeGroup:
        self.scopes.append(scope)
        if self.found is None:
            raise AccountNotFoundError("trade_group")
        return ScopedTradeGroup(record=self.found, shows_private_fields=True)


@dataclass
class ArmChecks:
    """`ArmRecords`, recording each token the route hands it (`shown`): a live account passes
    with one only (the interim `NoArmRecords` refuses every live order)."""

    shown: list[ArmToken | None] = field(default_factory=list)

    def check(
        self, *, session_id: UUID, environment: Environment, token: ArmToken | None
    ) -> Verdict:
        self.shown.append(token)
        return FAILED if environment == "live" and token is None else PASSED


@dataclass
class Reads:
    """`oms_wiring.OrderRoute`."""

    accounts: Accounts = field(default_factory=Accounts)
    arm_records: ArmChecks = field(default_factory=ArmChecks)
    switches: Switches = field(default_factory=Switches)
    orders: Orders = field(default_factory=Orders)
    groups: Groups = field(default_factory=Groups)


@dataclass
class Anchors:
    """The runtime's `AnchorService`: `answer` for every lookup, each recorded."""

    answer: Lookup | Exception = field(default_factory=Fresh)
    calls: list[tuple[UUID, UUID, str]] = field(default_factory=list)

    async def lookup(self, created_by: UUID, client_ref: UUID, request_sha256: str) -> Lookup:
        self.calls.append((created_by, client_ref, request_sha256))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


@dataclass
class Pipeline:
    """`OrderSubmission`: `outcome` (or `error`) for each submit, after `hold` when one is set."""

    outcome: SubmitOutcome = field(default_factory=first_entry)
    error: Exception | None = None
    replay: SubmitOutcome | None = None
    hold: asyncio.Event | None = None
    submitted: list[tuple[OrderRequest, SubmitContext]] = field(default_factory=list)

    async def submit(self, request: OrderRequest, context: SubmitContext) -> SubmitOutcome:
        self.submitted.append((request, context))
        if self.hold is not None:
            await self.hold.wait()
        if self.error is not None:
            raise self.error
        return self.outcome

    async def answer_replay(self, account_id: UUID, replay: Replay) -> SubmitOutcome:
        assert self.replay is not None
        return self.replay


@dataclass
class Runtime:
    """`OmsRuntime`: its `state`, its parts, and `run`, which records each task it tracks.
    `stopped` is the stop race: a stop begun after step 3 read `ok`, which `route` or `run` meets
    first and answers `OmsNotReady`, as the runtime's own do (closing the coroutine it refuses)."""

    state: str = "ok"
    reads: Reads = field(default_factory=Reads)
    anchors: Anchors = field(default_factory=Anchors)
    submission: Pipeline = field(default_factory=Pipeline)
    tasks: list[asyncio.Task[Response]] = field(default_factory=list)
    stopped: str | None = None

    @property
    def route(self) -> Reads:
        if self.stopped == "route":
            raise OmsNotReady
        return self.reads

    def run(self, coro: Coroutine[Any, Any, Response]) -> asyncio.Task[Response]:
        if self.stopped == "run":
            coro.close()
            raise OmsNotReady
        self.tasks.append(asyncio.get_running_loop().create_task(coro))
        return self.tasks[-1]


@dataclass
class Pager:
    pages: list[str] = field(default_factory=list)

    def raise_alert(self, severity: str, summary: str, *, machine_kind: str) -> None:
        self.pages.append(summary)


@dataclass
class World:
    """Everything the router is built over; `flag` is `trading.oms_enabled`."""

    principals: Principals | None = field(default_factory=Principals)
    runtime: Runtime | None = field(default_factory=Runtime)
    audit: Audit = field(default_factory=Audit)
    flag: bool = True
    metrics: Metrics = field(default_factory=lambda: Metrics("demo"))
    cache: IdempotencyCache = field(default_factory=IdempotencyCache)
    pager: Pager = field(default_factory=Pager)

    @property
    def oms(self) -> Runtime:
        assert self.runtime is not None
        return self.runtime

    def app(self) -> FastAPI:
        app = FastAPI()
        router = make_orders_router(
            self.principals, lambda: self.runtime, audit=self.audit, records=self.audit,
            oms_enabled=lambda: self.flag, metrics=self.metrics, replays=self.cache,
            pager=self.pager,
        )  # fmt: skip
        app.include_router(router)
        app.add_middleware(CorrelationMiddleware)  # binds `request_id`, as `create_app` does
        return app

    def rejected(self, code: str) -> float:
        line = f'oms_submit_rejected_total{{code="{code}",env="demo"}}'
        text = generate_latest(self.metrics.registry).decode()
        found = [float(r.rsplit(" ", 1)[1]) for r in text.splitlines() if r.startswith(line)]
        return found[0] if found else 0


def authz_denied() -> float:
    """`authz_denied_total` for `orders:write`, which steps 2 and 4 count (process-wide)."""
    return REGISTRY.get_sample_value("authz_denied_total", {"permission": "orders:write"}) or 0.0


@asynccontextmanager
async def client(world: World) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=world.app()), base_url="http://t") as c:
        yield c


def request(
    who: str = "owner", body: object = None, key: object = KEY, extra: dict[str, str] | None = None
) -> dict[str, Any]:
    """`POST /orders`' arguments as `who`: `BODY` unless `body` is given, bytes sent as they are,
    and the `extra` headers."""
    headers = {"authorization": f"Bearer {who}"} | (extra or {})
    if key is not None:
        headers["idempotency-key"] = str(key)
    raw = body if isinstance(body, bytes) else json.dumps(BODY if body is None else body).encode()
    return {"content": raw, "headers": headers}


async def post(
    world: World, who: str = "owner", body: object = None, key: object = KEY,
    extra: dict[str, str] | None = None,
) -> httpx.Response:  # fmt: skip
    async with client(world) as c:
        return await c.post("/orders", **request(who, body, key, extra))


def _live(w: World) -> None:
    w.oms.route.accounts.envs[ACCOUNT] = "live"


def _anchor(w: World, answer: Lookup | Exception) -> None:
    w.oms.anchors.answer = answer


#: Each step's refusal alone (24 Sec.8.4): what it answers, what it records, and whether the
#: anchor's lookup (step 8) ran. Nothing reaches the pipeline, and no task is run.
_STEPS: list[tuple[str, Any, str, int, str, str | None, bool]] = [
    ("1_no_source", lambda w: setattr(w, "principals", None), "owner", 501, "not_implemented",
     None, False),
    ("1_no_session", None, "nobody", 401, "unauthenticated", None, False),
    ("1_unread", lambda w: setattr(w.principals, "fail", True), "owner", 503,
     "store_unavailable", None, False),
    ("2_permission", None, "viewer", 403, "forbidden", "rbac.denied", False),
    ("2_view_only", None, "view_only", 403, "account_scope_denied", "rbac.denied", False),
    ("2_frozen", None, "frozen", 403, "account_scope_denied", "rbac.denied", False),
    ("3_no_runtime", lambda w: setattr(w, "runtime", None), "owner", 501, "not_implemented",
     None, False),
    ("3_starting", lambda w: setattr(w.oms, "state", "starting"), "owner", 503, "oms_not_ready",
     None, False),
    ("4_missing", lambda w: w.oms.route.accounts.envs.clear(), "owner", 403,
     "account_scope_denied", "rbac.denied", False),
    ("4_unread", lambda w: setattr(w.oms.route.accounts, "fail", True), "owner", 503,
     "store_unavailable", "orders.submit", False),
    ("5_unarmed", _live, "owner", 403, "session_not_armed", "orders.submit", False),
    ("8_in_flight", lambda w: _anchor(w, InFlight(1)), "owner", 409, "idempotency_in_flight",
     "orders.submit", True),
    ("8_reuse", lambda w: _anchor(w, KeyReuse()), "owner", 409, "idempotency_key_reuse",
     "orders.submit", True),
    ("8_unread", lambda w: _anchor(w, StoreUnavailable()), "owner", 503, "store_unavailable",
     "orders.submit", True),
    ("9_flag", lambda w: setattr(w, "flag", False), "owner", 403, "trading_disabled",
     "orders.submit", True),
    ("10_live_or_b18", lambda w: setattr(w.oms.route.switches, "refuses", TradingDisabled()),
     "owner", 403, "trading_disabled", "orders.submit", True),
    ("10_gate", lambda w: setattr(w.oms.route.switches, "refuses", OrderEntryRefused(GATE)),
     "owner", 403, "trading_disabled", "account.disabled_by_policy", True),
]  # fmt: skip


@pytest.mark.parametrize(
    ("change", "who", "status", "code", "action", "looked_up"),
    [case[1:] for case in _STEPS],
    ids=[case[0] for case in _STEPS],
)
async def test_each_step_refuses_before_the_next_runs(
    change: Any, who: str, status: int, code: str, action: str | None, looked_up: bool
) -> None:
    world = World()
    if change is not None:
        change(world)
    answer = await post(world, who)
    assert (answer.status_code, answer.json()["code"]) == (status, code)
    assert world.audit.actions() == ([] if action is None else [action])
    if world.runtime is not None:
        assert bool(world.oms.anchors.calls) is looked_up
        assert (world.oms.submission.submitted, world.oms.tasks) == ([], [])


def _starting(w: World) -> None:
    w.oms.state = "starting"


def _starting_and_missing(w: World) -> None:
    """A runtime that is starting, asked for an account that does not exist."""
    _starting(w)
    w.oms.route.accounts.envs.clear()


#: Two adjacent steps that would each refuse the request: the earlier one answers, with its
#: records, and the later one's counter does not move (`authz`: `authz_denied_total`, which steps
#: 2 and 4 count; else its `oms_submit_rejected_total` code; None: the body's 400 counts nothing).
_PAIRS: list[tuple[str, Any, str, object, object, int, str, list[str], str | None]] = [
    ("1_session_then_body", None, "nobody", b"{", KEY, 401, "unauthenticated", [], None),
    ("2_rbac_then_runtime", _starting, "viewer", None, KEY, 403, "forbidden", ["rbac.denied"],
     "oms_not_ready"),
    ("3_runtime_then_existence", _starting_and_missing, "owner", None, KEY, 503, "oms_not_ready",
     [], "authz"),
    ("5_arm_then_key", _live, "owner", None, None, 403, "session_not_armed", ["orders.submit"],
     "validation_failed"),
    ("10_switches_then_body", lambda w: setattr(w.oms.route.switches, "refuses", TradingDisabled()),
     "owner", BODY | {"price": None}, KEY, 403, "trading_disabled", ["orders.submit"],
     "validation_failed"),
]  # fmt: skip


@pytest.mark.parametrize(
    ("change", "who", "body", "key", "status", "code", "actions", "later"),
    [case[1:] for case in _PAIRS],
    ids=[case[0] for case in _PAIRS],
)
async def test_of_two_refusing_steps_the_earlier_answers_and_the_later_counts_nothing(
    change: Any, who: str, body: object, key: object, status: int, code: str,
    actions: list[str], later: str | None,
) -> None:  # fmt: skip
    """24 Sec.8.4's order where two steps would refuse alike: a viewer meets RBAC before a runtime
    that is starting (403, never 503), and a live account with no arm token meets step 5 before
    its missing `Idempotency-Key` (`session_not_armed`)."""
    world = World()
    if change is not None:
        change(world)
    denied = authz_denied()
    answer = await post(world, who, body, key)
    assert (answer.status_code, answer.json()["code"]) == (status, code)
    assert world.audit.actions() == actions
    if later == "authz":
        assert authz_denied() == denied
    elif later is not None:
        assert world.rejected(later) == 0


async def test_a_missing_or_malformed_key_is_400_audited_before_any_lookup() -> None:
    for key in (None, "not-a-uuid"):
        world = World()
        answer = await post(world, key=key)
        assert (answer.status_code, answer.json()["errors"][0]["field"]) == (400, "Idempotency-Key")
        assert (world.audit.actions(), world.oms.anchors.calls) == (["orders.submit"], [])


@pytest.mark.parametrize(
    "body",
    [b"{", b"[]", b'{"exchange_account_id": NaN}', {}, {"exchange_account_id": "acct-1"},
     {"exchange_account_id": 7}],
    ids=["bad_json", "not_an_object", "nan", "missing", "malformed", "not_a_string"],
)  # fmt: skip
async def test_an_account_that_cannot_be_read_is_400_before_rbac_unaudited(body: object) -> None:
    """There is no account to scope it (24 Sec.8.4 step 2): even a viewer gets the 400."""
    world = World()
    answer = await post(world, "viewer", body)
    assert (answer.status_code, answer.json()["code"]) == (400, "validation_failed")
    assert answer.json()["errors"][0]["field"] == "exchange_account_id"
    assert world.audit.actions() == []


async def test_a_body_past_the_cap_is_400_before_it_is_parsed_unaudited() -> None:
    """C-2.18, as an unreadable body is refused before step 2 (24 Sec.8.4): a declared
    `Content-Length` over `MAX_ORDER_BODY_BYTES` unread, though the body behind it would pass, and
    a stream that declares none at its first chunk past the cap."""
    pulled: list[int] = []

    async def chunks(chunk: bytes, count: int) -> AsyncIterator[bytes]:
        for _ in range(count):
            pulled.append(len(chunk))
            yield chunk

    declared, streamed = World(), World()
    sent = request()
    over = sent["headers"] | {"content-length": str(MAX_ORDER_BODY_BYTES + 1)}
    async with client(declared) as c:
        unread = await c.post("/orders", content=chunks(sent["content"], 1), headers=over)
    assert pulled == []
    async with client(streamed) as c:
        cut = await c.post("/orders", content=chunks(b" " * 1024, 64), headers=sent["headers"])
    assert len(pulled) == MAX_ORDER_BODY_BYTES // 1024 + 1
    for world, answer in ((declared, unread), (streamed, cut)):
        assert (answer.status_code, answer.json()["code"]) == (400, "validation_failed")
        assert answer.json()["errors"][0]["rule"] == "body_too_large"
        assert (world.audit.actions(), world.oms.anchors.calls) == ([], [])
        assert world.rejected("validation_failed") == 0


@pytest.mark.parametrize("who", ["viewer", "manager_outside", "owner_missing"])
async def test_a_scope_refusal_whose_record_fails_still_answers_its_403(who: str) -> None:
    """Steps 2 and 4, as `testApiKey` does: counted and logged, never a 503."""
    world = World()
    world.audit.fail = True
    body = BODY | {"exchange_account_id": str(FOREIGN)} if who == "manager_outside" else BODY
    if who == "owner_missing":
        world.oms.route.accounts.envs.clear()
    with capture_logs() as logs:
        answer = await post(world, who.split("_")[0], body)
    assert answer.status_code == 403
    assert any(line["event"] == "orders_denial_unaudited" for line in logs)


async def test_an_account_that_does_not_exist_reads_as_one_outside_the_grants() -> None:
    """No oracle (SR-E29-13): the Owner's missing account (step 4) and a Manager's foreign one
    (step 2) get the same body and the same `rbac.denied` record, the account named."""
    missing, foreign = World(), World()
    missing.oms.route.accounts.envs.clear()
    owner = await post(missing, "owner")
    manager = await post(foreign, "manager", BODY | {"exchange_account_id": str(ACCOUNT)})
    manager_foreign = await post(foreign, "manager", BODY | {"exchange_account_id": str(FOREIGN)})
    assert owner.json() == manager_foreign.json() and manager.status_code != 403
    (step_4,), (step_2,) = missing.audit.emitted, foreign.audit.emitted
    shape = {"action", "object_kind", "object_id", "outcome", "severity", "reason"}
    assert {k: step_4[k] for k in shape} == {k: step_2[k] for k in shape} | {
        "object_id": str(ACCOUNT),
    }  # fmt: skip
    assert step_2["object_id"] == str(FOREIGN)


@pytest.mark.parametrize("state", ["starting", "degraded"])
async def test_a_runtime_that_is_not_ready_is_503_counted_never_audited_and_runs_nothing(
    state: str,
) -> None:
    """SEC-S3E2-01: `run` admits a composed runtime that is not ready, so step 3 is the route's
    alone, and it reads `state` only."""
    world = World()
    world.oms.state = state
    answer = await post(world)
    assert (answer.status_code, answer.json()["code"]) == (503, "oms_not_ready")
    assert answer.headers["retry-after"] == str(answer.json()["retry_after_seconds"])
    assert (world.audit.actions(), world.oms.tasks, world.oms.anchors.calls) == ([], [], [])
    assert world.rejected("oms_not_ready") == 1


@pytest.mark.parametrize("meets", ["route", "anchors", "run"])
async def test_a_stop_begun_after_step_3_is_its_503_unaudited_and_binds_no_key(meets: str) -> None:
    """The stop race: the runtime read `ok` at step 3, then began its stop before the route read
    its parts, while it looked the key up, or before `run` took the submit. Each answers as step 3
    does, `oms_not_ready` counted and never an audited refusal, and binds no key: the same key and
    body once the runtime is back are a first submission."""
    world = World()
    if meets == "anchors":
        _anchor(world, OmsNotReady())
    else:
        world.oms.stopped = meets
    answer = await post(world)
    assert (answer.status_code, answer.json()["code"]) == (503, "oms_not_ready")
    assert answer.headers["retry-after"] == str(answer.json()["retry_after_seconds"])
    assert (world.audit.actions(), world.oms.submission.submitted, world.oms.tasks) == ([], [], [])
    assert world.rejected("oms_not_ready") == 1
    world.oms.stopped, world.oms.anchors.answer = None, Fresh()
    again = await post(world)
    assert again.status_code == 202 and "idempotency-replayed" not in again.headers
    assert len(world.oms.submission.submitted) == 1


@pytest.mark.parametrize("sent", ["t" * 256, "", "t" * 257], ids=["token", "empty", "over_256"])
async def test_the_arm_token_reaches_the_arm_records_masked_or_as_none(sent: str) -> None:
    """Step 5 (SR-043, C-12.6): `X-Arm-Token` reaches the port as an `ArmToken`, held masked; an
    empty one, or one past 22's 256 characters, as no token, which a live account's check
    refuses."""
    world = World()
    _live(world)
    answer = await post(world, extra={"x-arm-token": sent})
    (shown,) = world.oms.route.arm_records.shown
    if len(sent) == 256:
        assert isinstance(shown, ArmToken) and shown == ArmToken(sent)
        assert sent not in repr(shown) and answer.status_code == 202
    else:
        assert shown is None
        assert (answer.status_code, answer.json()["code"]) == (403, "session_not_armed")


async def test_a_refusal_whose_record_cannot_land_is_503_and_binds_no_key() -> None:
    """C-2.9: the same key and body once the writer is back are a first submission."""
    world = World(flag=False)
    world.audit.fail = True
    refused = await post(world)
    assert (refused.status_code, refused.json()["code"]) == (503, "audit_unavailable")
    assert world.rejected("audit_unavailable") == 1
    world.audit.fail, world.flag = False, True
    answer = await post(world)
    assert answer.status_code == 202 and "idempotency-replayed" not in answer.headers
    assert len(world.oms.submission.submitted) == 1


async def test_a_refused_order_is_audited_before_the_403() -> None:
    """#2780 (24 Sec.8.4.1): the gate's refusal is one `account.disabled_by_policy` record, with
    the actor, the role, the account, the reason and the request id, before the 403; a record that
    cannot land answers 503 instead of the 403."""
    world = World()
    world.oms.route.switches.refuses = OrderEntryRefused(GATE)
    answer = await post(world, "manager", extra={"x-correlation-id": str(TRACE)})
    assert (answer.status_code, answer.json()["reason"]) == (403, "no_active_key")
    (record,) = world.audit.written
    assert (record.action, record.reason, record.outcome) == (
        "account.disabled_by_policy", "no_active_key", "denied",
    )  # fmt: skip
    assert (record.account_id, record.actor.user_id, record.actor.role) == (
        ACCOUNT, MANAGER, "manager",
    )  # fmt: skip
    assert record.actor.session_id == SESSION and record.detail["environment"] == "demo"
    assert record.request_id == TRACE  # the id `CorrelationMiddleware` bound for the request
    world.audit.fail = True
    assert (await post(world, "manager")).status_code == 503


@pytest.mark.parametrize("who", ["viewer", "view_only", "outside"])
async def test_rbac_refuses_first_and_discloses_no_gate_reason(who: str) -> None:
    """#2780: the forbidden role and the cross-account caller never reach the gate."""
    world = World()
    world.oms.route.switches.refuses = OrderEntryRefused(GATE)
    body = BODY | {"exchange_account_id": str(FOREIGN)} if who == "outside" else BODY
    answer = await post(world, "manager" if who == "outside" else who, body)
    assert answer.status_code == 403 and "reason" not in answer.json()
    assert (world.oms.route.switches.asked, world.audit.actions()) == (0, ["rbac.denied"])


_REDUCE = BODY | {"reduce_only": True, "intent": "flatten", "order_type": "market", "price": None}
_REDUCE.pop("stop_loss")


async def test_the_flag_passes_a_reduce_only_body_and_the_gate_still_takes_it() -> None:
    """24 Sec.8.4 step 9: narrower than the gate (C-4.14, C-2.6); the route is mounted with it
    off."""
    world = World(flag=False)
    world.oms.submission.outcome = first_reduce_only()
    assert (await post(world, body=_REDUCE)).status_code == 202
    world.oms.route.switches.refuses = OrderEntryRefused(GATE)
    gated = await post(world, body=_REDUCE, key=MANAGER)
    assert (gated.status_code, gated.json()["reason"]) == (403, "no_active_key")


async def test_only_a_json_true_passes_the_flag_and_the_strict_read_refuses_a_string() -> None:
    """A `"true"` string is no `reduce_only`: refused by the flag while it is off, and by step 11's
    strict read while it is on."""
    stringly = _REDUCE | {"reduce_only": "true"}
    off, on = World(flag=False), World()
    flagged, read = await post(off, body=stringly), await post(on, body=stringly)
    assert (flagged.status_code, flagged.json()["code"]) == (403, "trading_disabled")
    assert "reason" not in flagged.json()
    assert (read.status_code, read.json()["errors"][0]["field"]) == (400, "reduce_only")
    assert on.oms.submission.submitted == [] and off.oms.route.switches.asked == 0


async def test_a_repeated_account_key_is_read_once_for_rbac_and_for_the_order() -> None:
    """DC-S3A2-01 (C-12.4): steps 2 and 11 read the one parse, whose last key wins, so RBAC checks
    the account the order would go to."""
    rest = json.dumps({k: v for k, v in BODY.items() if k != "exchange_account_id"})[1:-1]

    def twice(first: UUID, last: UUID) -> bytes:
        named = '"exchange_account_id": "{}"'
        return f"{{{named.format(first)}, {rest}, {named.format(last)}}}".encode()

    refused, world = World(), World()
    denied = await post(refused, "manager", twice(ACCOUNT, FOREIGN))
    assert (denied.status_code, refused.audit.emitted[0]["object_id"]) == (403, str(FOREIGN))
    assert (await post(world, "manager", twice(FOREIGN, ACCOUNT))).status_code == 202
    ((order, _context),) = world.oms.submission.submitted
    assert order.account_id == ACCOUNT


@pytest.mark.parametrize(
    ("change", "field", "rule"),
    [
        ({"price": None}, "price", "required"),
        ({"algo": {"kind": "twap"}}, "algo.kind", "algo_unsupported"),
        ({"leverage": "5"}, "leverage", "extra_forbidden"),
        ({"side": "BUY"}, "side", "literal_error"),
        ({"close_on_trigger": 1}, "close_on_trigger", "bool_type"),
    ],
    ids=["limit_without_price", "algo", "extra_member", "side", "number_for_bool"],
)
async def test_the_body_is_read_strictly_audited_and_refused_before_the_pipeline(
    change: dict[str, Any], field: str, rule: str
) -> None:
    world = World()
    answer = await post(world, body=BODY | change)
    errors = {(e["field"], e["rule"]) for e in answer.json()["errors"]}
    assert (answer.status_code, (field, rule) in errors) == (400, True)
    assert (world.audit.actions(), world.oms.submission.submitted) == (["orders.submit"], [])


async def test_the_pipeline_gets_the_request_as_read_with_its_key_and_fingerprint() -> None:
    world = World()
    await post(world, "manager", BODY | {"profile_id": str(FOREIGN), "note": "breakout"})
    ((order, context),) = world.oms.submission.submitted
    raw = request("manager", BODY | {"profile_id": str(FOREIGN), "note": "breakout"})["content"]
    assert (order.account_id, order.side, order.order_type, str(order.price)) == (
        ACCOUNT, "buy", "limit", "60000",
    )  # fmt: skip
    assert (order.sizing.mode, str(order.sizing.qty)) == ("fixed_qty", "0.010")
    assert order.stop_loss == StopOffset("price", Decimal("58000"))
    assert (order.profile_id, order.note, order.time_in_force) == (FOREIGN, "breakout", "GTC")
    assert (context.actor.user_id, context.actor.role, context.actor.session_id) == (
        MANAGER, "manager", SESSION,
    )  # fmt: skip
    assert context.client_ref == KEY
    assert context.request_sha256 == request_fingerprint("POST", "/orders", raw)
    assert world.oms.anchors.calls == [(MANAGER, KEY, context.request_sha256)]


async def test_a_first_202_is_its_written_rows_and_its_repeat_the_24h_record() -> None:
    world = World()
    first = await post(world)
    assert first.status_code == 202 and "idempotency-replayed" not in first.headers
    validate(first.json())
    repeat = await post(world)
    assert (repeat.status_code, repeat.headers["idempotency-replayed"]) == (202, "true")
    assert repeat.content == first.content
    assert (len(world.oms.submission.submitted), len(world.oms.anchors.calls)) == (1, 1)
    assert world.audit.actions() == []  # a replay is the stored answer, not a refusal


async def test_the_24h_record_answers_another_body_under_its_key_409() -> None:
    world = World()
    await post(world)
    reused = await post(world, body=BODY | {"price": "60001"})
    assert (reused.status_code, reused.json()["code"]) == (409, "idempotency_key_reuse")
    assert world.audit.actions() == ["orders.submit"]
    assert len(world.oms.submission.submitted) == 1


async def test_another_principals_key_is_answered_as_one_never_seen() -> None:
    """IDOR (SR-E29-07): the 24 h record and the anchor are each the principal's own."""
    world = World()
    await post(world, "owner")
    other = await post(world, "manager")
    assert other.status_code == 202 and "idempotency-replayed" not in other.headers
    assert [call[0] for call in world.oms.anchors.calls] == [USER, MANAGER]


def _replay(world: World, outcome: SubmitOutcome) -> None:
    """Step 8 meets a decided anchor whose repeat `answer_replay` answers `outcome`."""
    anchor = AnchorRow(
        outcome.anchor_id, USER, "placeOrder", outcome.trade_group_id, outcome.order_id,
        outcome.status, outcome.code, outcome.ret_code, T0, T0, True,
    )  # fmt: skip
    world.oms.anchors.answer, world.oms.submission.replay = Replay(anchor), outcome


async def test_an_anchors_replay_answers_its_entrys_rows_as_read_now_and_keeps_none() -> None:
    world, first = World(), first_entry()
    row, found = read_entry(first, state="unknown", lifecycle_state="unknown")
    world.oms.route.orders.rows[row.id], world.oms.route.groups.found = row, found
    _replay(world, replay_of(first, "unknown"))
    answer = await post(world, "manager")
    assert (answer.status_code, answer.headers["idempotency-replayed"]) == (202, "true")
    validate(answer.json())
    assert answer.json()["reconciling"] is True and world.oms.submission.submitted == []
    assert world.oms.route.groups.scopes[0].account_ids == frozenset({ACCOUNT})  # SR-E28-21
    assert (await post(world, "manager")).status_code == 202
    assert len(world.oms.anchors.calls) == 2 and world.audit.actions() == []


async def test_a_replay_is_answered_while_the_flag_and_the_switches_now_refuse() -> None:
    """C-2.10: the exact repeat of an accepted request gets its stored outcome."""
    world, first = World(flag=False), first_reduce_only()
    world.oms.route.switches.refuses = OrderEntryRefused(GATE)
    assert first.written is not None
    world.oms.route.orders.rows[first.written.order.id] = stored(first.written.order)
    _replay(world, replay_of(first))
    answer = await post(world, body=_REDUCE)
    assert answer.status_code == 202 and world.oms.route.switches.asked == 0


@pytest.mark.parametrize(
    ("status", "code"), [(429, "exchange_rate_limited"), (502, "exchange_error")]
)
async def test_a_recorded_429_or_502_is_replayed_with_no_retry_after(
    status: Literal[429, 502], code: str
) -> None:
    world = World()
    _replay(world, SubmitOutcome(status, KEY, MANAGER, None, "rejected", code, replayed=True))
    answer = await post(world)
    assert (answer.status_code, answer.headers["idempotency-replayed"]) == (status, "true")
    assert "retry-after" not in answer.headers


@pytest.mark.parametrize("missing", ["group", "order"])
async def test_a_replay_whose_rows_cannot_be_read_is_503_audited_and_sends_nothing(
    missing: str,
) -> None:
    """The scoped group read misses, or it finds the group and the order read does not find its
    order (`row is None`: an anchor never exists without its order)."""
    world, first = World(), first_entry()
    if missing == "order":
        world.oms.route.groups.found = read_entry(first)[1]
    _replay(world, replay_of(first))
    with capture_logs() as logs:
        answer = await post(world)
    assert (answer.status_code, answer.json()["code"]) == (503, "store_unavailable")
    (record,) = world.audit.written
    assert (record.action, record.detail["step"]) == ("orders.submit", "replay")
    unread = "orders_replay_row_missing" if missing == "order" else "orders_replay_unread"
    assert unread in [line["event"] for line in logs] and world.oms.submission.submitted == []


async def test_a_grant_revoked_before_a_repeat_is_403_before_any_answer_is_read() -> None:
    """SEC-S3D-03: a caller who lost access reads no outcome back (22 Idempotency)."""
    world = World()
    assert world.principals is not None
    assert (await post(world, "manager")).status_code == 202
    world.principals.tokens["manager"] = TradingPrincipal(SESSION, snapshot("manager", trade=False))
    revoked = await post(world, "manager")
    assert (revoked.status_code, revoked.json()["code"]) == (403, "account_scope_denied")
    assert len(world.oms.anchors.calls) == 1


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (RiskRefused(), 403, "risk_limit_breached"),
        (ProfileNotFound(), 404, "not_found"),  # another account's profile_id, through the route
        (StoreUnavailable(), 503, "store_unavailable"),
    ],
)
async def test_a_refusal_the_pipeline_raises_is_its_answer_and_binds_nothing(
    error: OmsError, status: int, code: str
) -> None:
    """The pipeline records its own refusals before it raises them: the route adds none."""
    world = World()
    world.oms.submission.error = error
    for _ in range(2):
        answer = await post(world)
        assert (answer.status_code, answer.json()["code"]) == (status, code)
    assert world.audit.actions() == [] and len(world.oms.submission.submitted) == 2


async def test_a_first_429_carries_its_retry_after_and_is_kept_by_the_anchor_alone() -> None:
    world = World()
    world.oms.submission.outcome = replace(
        first_entry(),
        status=429,
        lifecycle="rejected",
        code="exchange_rate_limited",
        retry_after_s=3,
    )
    answer = await post(world)
    assert (answer.status_code, answer.headers["retry-after"]) == (429, "3")
    assert world.cache.get(str(USER), f"placeOrder:{KEY}") is None


async def test_a_first_answer_without_its_rows_fails_closed_and_pages() -> None:
    """CR-S3D-07: no read after the send, so nothing to answer from: a paged 500, kept nowhere."""
    world = World()
    world.oms.submission.outcome = replace(first_entry(), written=None)
    answer = await post(world)
    assert (answer.status_code, answer.json()["code"]) == (500, "internal_error")
    assert world.pager.pages == ["orders_first_answer_unwritten"]
    assert world.rejected("internal_error") == 1  # 20 Sec.12.1 pages on it
    assert world.cache.get(str(USER), f"placeOrder:{KEY}") is None


async def test_a_replay_that_reads_another_group_fails_closed_and_pages() -> None:
    """SEC-S3F2-03: the scoped read finds a group other than the one the outcome names, which the
    renderer refuses (CR-S3F1-02): a paged 500, counted, kept nowhere and nothing sent."""
    world, first = World(), first_entry()
    row, found = read_entry(first)
    other = found.group.model_copy(update={"group_id": GroupId(UUID(int=99))})
    another = TradeGroupWithLegs(group=other, legs=())
    world.oms.route.orders.rows[row.id], world.oms.route.groups.found = row, another
    _replay(world, replay_of(first))
    answer = await post(world)
    assert (answer.status_code, answer.json()["code"]) == (500, "internal_error")
    assert world.pager.pages == ["orders_replay_group_mismatch"]
    assert world.rejected("internal_error") == 1 and world.oms.submission.submitted == []
    assert world.cache.get(str(USER), f"placeOrder:{KEY}") is None


async def test_the_pipelines_own_repeat_that_reads_another_group_fails_closed_and_pages() -> None:
    """DC-S3F2-01, step 12's twin of the test above: the pipeline's own repeat (`_repeat`), whose
    scoped read finds a group other than the one the outcome names, is the same paged 500,
    counted and kept nowhere, the pipeline asked once."""
    world, first = World(), first_entry()
    row, found = read_entry(first)
    other = found.group.model_copy(update={"group_id": GroupId(UUID(int=99))})
    another = TradeGroupWithLegs(group=other, legs=())
    world.oms.route.orders.rows[row.id], world.oms.route.groups.found = row, another
    world.oms.submission.outcome = replay_of(first)
    answer = await post(world)
    assert (answer.status_code, answer.json()["code"]) == (500, "internal_error")
    assert world.pager.pages == ["orders_replay_group_mismatch"]
    assert world.rejected("internal_error") == 1 and len(world.oms.submission.submitted) == 1
    assert world.cache.get(str(USER), f"placeOrder:{KEY}") is None


async def test_the_pipelines_own_repeat_answers_the_rows_as_read_now_and_is_not_kept() -> None:
    """A concurrent first request met the key held (`_repeat`): the earlier one's answer is kept."""
    world, first = World(), first_reduce_only()
    assert first.written is not None
    row = stored(first.written.order, state="accepted", lifecycle_state="submitted")
    world.oms.route.orders.rows[row.id] = row
    world.oms.submission.outcome = replay_of(first, "submitted")
    answer = await post(world, body=_REDUCE)
    assert (answer.status_code, answer.headers["idempotency-replayed"]) == (202, "true")
    assert answer.json()["order"]["lifecycle_state"] == "submitted"
    assert world.cache.get(str(USER), f"placeOrder:{KEY}") is None


async def test_a_cancelled_request_still_completes_its_submit_and_keeps_its_answer() -> None:
    """24 Sec.8.4 step 12: shielded from the client's disconnect; the task the runtime tracks
    renders the answer and keeps it, so the repeat is the 24 h record's."""
    world = World()
    hold = world.oms.submission.hold = asyncio.Event()
    async with client(world) as c:
        sent = asyncio.create_task(c.post("/orders", **request()))
        for _ in range(10_000):  # a bound on the test, not a time
            if world.oms.submission.submitted:
                break
            await asyncio.sleep(0)
        sent.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sent
    hold.set()
    (task,) = world.oms.tasks
    assert (await task).status_code == 202
    repeat = await post(world)
    assert (repeat.status_code, repeat.headers["idempotency-replayed"]) == (202, "true")


async def test_no_log_line_carries_a_written_member_the_key_or_the_fingerprint() -> None:
    """SEC-S3D-01 (C-12.6), over a first answer and a fail-closed one."""
    world = World()
    written = world.oms.submission.outcome.written
    assert written is not None and written.group is not None
    with capture_logs() as logs:
        await post(world)
        world.oms.submission.outcome = replace(world.oms.submission.outcome, written=None)
        await post(world, key=MANAGER)
    text = json.dumps(logs, default=str)
    order = written.order
    members = [order.order_link_id, str(order.qty), str(order.stop_loss), str(order.id)]
    members += [written.group.client_group_ref, str(KEY), str(MANAGER)]
    members.append(request_fingerprint("POST", "/orders", request()["content"]))
    assert logs and [m for m in members if m in text] == []


def test_a_viewing_sessions_order_is_refused_by_the_middleware_before_the_route() -> None:
    """#4177: `placeOrder` is no protective write, so the view-as guard refuses it
    `view_as_read_only` and the route never runs: the Owner viewing would pass RBAC and get the
    fake backend's 501."""
    with pytest.MonkeyPatch.context() as mp:
        world = build_world(mp)
        answer = world.client.post(
            "/orders", json={"exchange_account_id": str(GRANTED)},
            headers=bearer_viewing("manager_with_grant"),
        )  # fmt: skip
        actions = [record["action"] for record in world.audit.records]
    assert (answer.status_code, answer.json()["code"]) == (403, "view_as_read_only")
    assert "rbac.denied" not in actions and "orders.submit" not in actions
