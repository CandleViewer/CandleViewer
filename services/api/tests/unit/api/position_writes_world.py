"""A world for the position write routes (E29-T07 #915 PR 2): `closePosition`,
`closeAllPositions` and `reversePosition` on a bare app, over the real `OmsReads` (the read
world's in-memory store, seeded with positions on the acceptance tests' account) and recording
doubles of the runtime's pipeline, anchors, reads, cancel-all and position service. The pipeline's
outcomes are the acceptance tests' (`first_reduce_only`, `first_entry`), so every `202` body is
rendered from rows the order store contract builds. No network (C-13.5)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, Final

from fastapi import FastAPI
from fastapi.responses import Response
from httpx import ASGITransport, AsyncClient

from candleviewer.accounts.errors import AccountNotFoundError
from candleviewer.accounts.trade_groups import ScopedTradeGroup, TradeGroupWithLegs
from candleviewer.api.idempotency import IdempotencyCache
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.api.position_close import make_position_close_router
from candleviewer.api.position_reverse import make_position_reverse_router
from candleviewer.api.recording_writes import WriteLimiter
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.observability.metrics import Metrics
from candleviewer.oms.cancel_all import CancelAllRequest, ScopedAccounts
from candleviewer.oms.errors import (
    AccountScopeDenied,
    OmsError,
    OmsNotReady,
    StoreUnavailable,
    TradingDisabled,
)
from candleviewer.oms.idempotency import Fresh, Lookup, Replay
from candleviewer.oms.ports import FAILED, PASSED, ArmToken, RequestRecord, SubmitActor, Verdict
from candleviewer.oms.position_writes import CloseFill, VenuePosition
from candleviewer.oms.reads import OmsReads
from candleviewer.oms.submit import (
    OrderRequest,
    SubmitContext,
    SubmitOutcome,
    WrittenRows,
    entry_order_id,
)
from candleviewer.storage.repositories.orders import OrderRow
from candleviewer.storage.repositories.positions import PositionRow
from tests.unit.api import test_order_acceptance as acc
from tests.unit.api.oms_reads_world import (
    ACCOUNT_A,
    ACCOUNT_B,
    ACCOUNT_LIVE,
    ENVIRONMENT,
    Audit,
    ReadStore,
    Store,
    position,
)
from tests.unit.oms.submission_contract import entry, reduce_only

ACCOUNT: Final = ACCOUNT_A
LIVE: Final = ACCOUNT_LIVE
SESSION: Final = uuid.UUID("5e551011-0000-4000-8000-000000000917")
#: The long on ACCOUNT (0.200 BTCUSDT), B's short, a flat one on ACCOUNT, and a long on LIVE.
ON_A: Final = "00000000-0000-0000-0000-000000000d01"
ON_B: Final = "00000000-0000-0000-0000-000000000d02"
FLAT: Final = "00000000-0000-0000-0000-000000000d03"
ON_LIVE: Final = "00000000-0000-0000-0000-000000000d04"
HEDGED: Final = "00000000-0000-0000-0000-000000000d06"
USERS: Final = {
    "owner": acc.USER,
    **{who: uuid.uuid5(uuid.NAMESPACE_URL, f"cv-915-writes/{who}")
       for who in ("manager", "reader", "viewer")},
}  # fmt: skip
_WRITE: Final = frozenset({Permission.POSITIONS_READ, Permission.POSITIONS_WRITE})


def first_close(chart: str = "submitted", account: uuid.UUID = ACCOUNT) -> SubmitOutcome:
    """A close's first `202`: a reduce-only order on `account`, no group."""
    first, order = reduce_only(acc.USER, account)
    return SubmitOutcome(202, first.anchor.id, order.id, None, chart, written=WrittenRows(order))


def first_open(chart: str = "submitted", account: uuid.UUID = ACCOUNT) -> SubmitOutcome:
    """A reversal entry's first `202`: its one-leg group on `account`."""
    first, order = entry(acc.USER, account, acc.PROFILE)
    assert first.group is not None
    order = replace(order, id=entry_order_id(first.group.id))
    rows = WrittenRows(order, first.group, first.legs)
    return SubmitOutcome(202, first.anchor.id, order.id, first.group.id, chart, written=rows)


def store() -> Store:
    return Store(
        orders=[], fills=[],
        positions=[
            position(1, ACCOUNT),
            position(2, ACCOUNT_B, side="Sell", size=Decimal("0.100")),
            position(3, ACCOUNT, symbol="ETHUSDT", side="None", size=Decimal(0)),
            position(4, LIVE, size=Decimal(5)),
            position(6, ACCOUNT, symbol="SOLUSDT", side="Sell", position_idx=2),
        ],
        events={},
    )  # fmt: skip


def snapshot(who: str) -> PrincipalSnapshot:
    """The Owner; a Manager trading ACCOUNT and LIVE; `reader`, a Manager viewing ACCOUNT
    without trading it; a Viewer, who holds no `positions:write`."""
    if who == "owner":
        return PrincipalSnapshot(USERS[who], frozenset({"owner"}), frozenset(Permission))
    if who == "viewer":
        grant = AccountGrant(ACCOUNT, True, False, False)
        held = frozenset({Permission.POSITIONS_READ})
        return PrincipalSnapshot(USERS[who], frozenset({"viewer"}), held, (grant,))
    trade = who == "manager"
    grants = (AccountGrant(ACCOUNT, True, trade, False), AccountGrant(LIVE, True, trade, False))
    return PrincipalSnapshot(USERS[who], frozenset({"manager"}), _WRITE, grants)


class Principals:
    """A principal per bearer; `fail`: its store's 503."""

    def __init__(self, *, fail: bool = False) -> None:
        self.tokens = {who: TradingPrincipal(SESSION, snapshot(who)) for who in USERS}
        # The Owner viewing as a user in a live view-as context (a protective write the guard
        # passed): `viewing-<who>` carries that user as the target (22 "View-as session").
        for who in ("manager", "reader"):
            viewing = TradingPrincipal(SESSION, snapshot("owner"), target=snapshot(who))
            self.tokens[f"viewing-{who}"] = viewing
        self.fail = fail

    async def resolve(self, request: Any) -> TradingPrincipal | None:
        if self.fail:
            raise StoreUnavailable
        return self.tokens.get(request.headers.get("authorization", "").partition(" ")[2])


@dataclass
class Records:
    """The audit writer's `write`: each record, in order, with the pipeline's submits so far."""

    pipeline: Pipeline
    written: list[tuple[RequestRecord, int]] = field(default_factory=list)
    fail: bool = False

    def record_id(self, action: str, name: str) -> uuid.UUID:
        raise AssertionError("no keyed record on this path")

    async def write(self, record: Any) -> None:
        if self.fail:
            raise RuntimeError("the audit writer is not started")
        self.written.append((record, len(self.pipeline.submitted)))


@dataclass
class Arm:
    shown: list[ArmToken | None] = field(default_factory=list)

    def check(
        self, *, session_id: uuid.UUID, environment: Environment, token: ArmToken | None
    ) -> Verdict:
        self.shown.append(token)
        return FAILED if environment == "live" and token != ArmToken("armed") else PASSED


@dataclass
class Switches:
    refusal_of: TradingDisabled | OmsNotReady | None = None

    def refusal(
        self, account_id: AccountId, environment: Environment
    ) -> TradingDisabled | OmsNotReady | None:
        return self.refusal_of


@dataclass
class Orders:
    """The order read by account; `error` raised instead when set."""

    rows: dict[uuid.UUID, OrderRow] = field(default_factory=dict)
    error: BaseException | None = None

    async def get(self, account_id: uuid.UUID, order_id: uuid.UUID) -> OrderRow | None:
        if self.error is not None:
            raise self.error
        row = self.rows.get(order_id)
        return row if row is not None and row.exchange_account_id == account_id else None


@dataclass
class Groups:
    found: TradeGroupWithLegs | None = None

    async def get(self, scope: Any, group_id: uuid.UUID) -> ScopedTradeGroup:
        if self.found is None:
            raise AccountNotFoundError("trade_group")
        return ScopedTradeGroup(record=self.found, shows_private_fields=True)


@dataclass
class Route:
    environment: Environment = "demo"
    arm_records: Arm = field(default_factory=Arm)
    switches: Switches = field(default_factory=Switches)
    orders: Orders = field(default_factory=Orders)
    groups: Groups = field(default_factory=Groups)


@dataclass
class Anchors:
    """The anchor lookups, by (operation, ref): `answers`, else `Fresh`; each recorded."""

    answers: dict[tuple[str, uuid.UUID], Lookup] = field(default_factory=dict)
    calls: list[tuple[str, uuid.UUID]] = field(default_factory=list)

    async def lookup(
        self, created_by: uuid.UUID, client_ref: uuid.UUID, request_sha256: str, *,
        operation: str = "placeOrder",
    ) -> Lookup:  # fmt: skip
        self.calls.append((operation, client_ref))
        return self.answers.get((operation, client_ref), Fresh())


@dataclass
class Pipeline:
    """`OrderSubmission`: each submit recorded with the clock's reading; a reduce-only order is
    answered `close`, an entry `entry` (an `OmsError` is raised); `replays` per anchor id."""

    close: SubmitOutcome | OmsError = field(default_factory=first_close)
    entry: SubmitOutcome | OmsError = field(default_factory=first_open)
    replays: dict[uuid.UUID, SubmitOutcome] = field(default_factory=dict)
    submitted: list[tuple[OrderRequest, SubmitContext]] = field(default_factory=list)
    log: list[str] | None = None

    async def submit(self, request: OrderRequest, context: SubmitContext) -> SubmitOutcome:
        self.submitted.append((request, context))
        if self.log is not None:
            self.log.append("entry" if not request.reduce_only else "close")
        answer = self.close if request.reduce_only else self.entry
        if isinstance(answer, OmsError):
            raise answer
        return answer

    async def answer_replay(self, account_id: AccountId, replay: Replay) -> SubmitOutcome:
        return self.replays[replay.anchor.id]


@dataclass
class Positions:
    """The position service: the fill answer, the pre-check's refusal, the records, the sweeps."""

    fill: CloseFill = "filled"
    fill_error: OmsError | None = None
    venue: VenuePosition = "flat"
    group_refusal: OmsError | None = None
    group_keys: list[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=list)
    stop_refusal: OmsError | None = None
    log: list[str] | None = None
    records: list[RequestRecord] = field(default_factory=list)
    sweeps: list[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=list)
    waits: list[float] = field(default_factory=list)
    #: The runtime's clock, the world's (`World.clock`).
    clock: list[float] = field(default_factory=lambda: [0.0])

    async def entry_stop_ready(self, account_id: AccountId) -> None:
        if self.stop_refusal is not None:
            raise self.stop_refusal

    async def group_key_free(
        self, created_by: uuid.UUID, key: uuid.UUID, request_sha256: str
    ) -> None:
        self.group_keys.append((created_by, key))
        if self.group_refusal is not None:
            raise self.group_refusal

    async def await_fill(
        self, account_id: uuid.UUID, order_id: uuid.UUID, *, deadline: float
    ) -> CloseFill:
        self.waits.append(deadline - self.clock[0])  # what is left on the runtime's clock
        if self.fill_error is not None:
            raise self.fill_error
        if self.log is not None:
            self.log.append(f"fill:{self.fill}")
        return self.fill

    async def venue_position(self, row: PositionRow) -> VenuePosition:
        if self.log is not None:
            self.log.append(f"venue:{self.venue}")
        return self.venue

    async def record(self, record: RequestRecord) -> bool:
        self.records.append(record)
        return True

    async def sweep_after_close(
        self, row: PositionRow, order_id: uuid.UUID, *, actor: SubmitActor,
        request_id: uuid.UUID | None,
    ) -> bool:  # fmt: skip
        self.sweeps.append((row.id, order_id))
        return True


@dataclass
class CancelAll:
    """`CancelAll.scope` (all or nothing, this process's environment only) and `run`."""

    environment: Environment = "demo"
    runs: list[CancelAllRequest] = field(default_factory=list)
    error: OmsError | None = None

    async def scope(self, scope: Any, request: CancelAllRequest) -> ScopedAccounts:
        mine = tuple(a for a in (ACCOUNT, LIVE) if ENVIRONMENT[a] == self.environment)
        named = request.exchange_account_ids
        if any(a not in mine for a in named):
            raise AccountScopeDenied
        return ScopedAccounts(tuple(a for a in mine if not named or a in named))

    async def run(
        self, accounts: ScopedAccounts, request: CancelAllRequest, *, actor: SubmitActor,
        request_id: uuid.UUID | None,
    ) -> object:  # fmt: skip
        self.runs.append(request)
        if self.error is not None:
            raise self.error
        return None


@dataclass
class Runtime:
    route: Route
    submission: Pipeline
    anchors: Anchors
    positions: Positions
    cancel_all: CancelAll
    readiness: str = "ok"
    refuse_run: bool = False
    tasks: set[asyncio.Task[Response]] = field(default_factory=set)

    def monotonic(self) -> float:
        return self.positions.clock[0]

    def run(self, coro: Coroutine[Any, Any, Response]) -> asyncio.Task[Response]:
        if self.refuse_run:
            coro.close()
            raise OmsNotReady
        task = asyncio.get_running_loop().create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task


@dataclass
class World:
    environment: Environment = "demo"
    store: Store = field(default_factory=store)
    audit: Audit = field(default_factory=Audit)
    route: Route = field(default_factory=Route)
    pipeline: Pipeline = field(default_factory=Pipeline)
    anchors: Anchors = field(default_factory=Anchors)
    positions: Positions = field(default_factory=Positions)
    cancel_all: CancelAll = field(default_factory=CancelAll)
    oms_enabled: bool = True
    principals: str = "ok"  # "ok", "none" (no source composed) or "fail" (its store down)
    composed: bool = True
    reads_composed: bool = True
    readiness: str = "ok"
    refuse_run: bool = False
    limiter: WriteLimiter = field(
        default_factory=lambda: WriteLimiter(rate_per_minute=60, clock=lambda: 0.0)
    )
    clock: list[float] = field(default_factory=lambda: [0.0])
    cache: IdempotencyCache = field(default_factory=IdempotencyCache)
    records: Records = field(init=False)

    def __post_init__(self) -> None:
        self.records = Records(self.pipeline)
        self.route.environment = self.cancel_all.environment = self.environment
        self.positions.clock = self.clock  # one clock: the route's deadline and the fill wait

    def runtime(self) -> Runtime:
        return Runtime(
            self.route, self.pipeline, self.anchors, self.positions, self.cancel_all,
            self.readiness, self.refuse_run,
        )  # fmt: skip

    def app(self) -> FastAPI:
        reads = OmsReads(ReadStore(self.store), self.environment) if self.reads_composed else None
        runtime = self.runtime() if self.composed else None
        limiter = self.limiter
        app = FastAPI()
        common: dict[str, Any] = {
            "audit": self.audit, "records": self.records, "metrics": Metrics("demo"),
            "replays": self.cache, "limiter": limiter,
        }  # fmt: skip
        source = None if self.principals == "none" else Principals(fail=self.principals == "fail")
        app.include_router(make_position_close_router(
            source, lambda: runtime, reads, **common
        ))  # fmt: skip
        app.include_router(make_position_reverse_router(
            source, lambda: runtime, reads, oms_enabled=lambda: self.oms_enabled, **common,
        ))  # fmt: skip
        return app

    @asynccontextmanager
    async def client(self) -> AsyncIterator[AsyncClient]:
        async with AsyncClient(transport=ASGITransport(app=self.app()), base_url="http://t") as c:
            yield c

    def exhaust(self) -> None:
        """The Owner's rate spent: one write a minute, written already (ruling BQ-15)."""
        self.limiter = WriteLimiter(rate_per_minute=1, clock=lambda: 0.0)
        assert self.limiter.admit(str(USERS["owner"])) is None

    def submitted(self) -> list[OrderRequest]:
        return [request for request, _ in self.pipeline.submitted]


def headers(who: str, *, key: uuid.UUID | None = None, arm: str | None = None) -> dict[str, str]:
    out = {"authorization": f"Bearer {who}", "idempotency-key": str(key or uuid.uuid4())}
    if arm is not None:
        out["x-arm-token"] = arm
    return out


async def post(
    world: World, path: str, who: str = "owner", body: Any = None, *,
    hdrs: dict[str, str] | None = None, **kw: Any,
) -> Any:  # fmt: skip
    async with world.client() as client:
        sent = headers(who, **kw) if hdrs is None else hdrs
        return await client.post(path, json=body, headers=sent)


def on(path: str, position: str) -> str:
    return path.replace("{positionId}", position)


Seed = Callable[[World], None]
