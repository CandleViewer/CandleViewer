"""E28-T05 S3c (#909): `previewTradeGroup` over fakes: the principal source, the OMS runtime and
its preview reads (a guard that admits, the interim stop resolver, BTCUSDT listed, cached figures
that record their asks), the accounts (A and B demo, L live, D deleted), their bound profiles (the
OMS fixture's) and alternates of A's, readiness, the flag's gate, the user's bucket and the audit
writer. Each check of the route's module docstring is driven alone, and each answer's records are
read in the order written."""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from candleviewer.accounts.errors import AccountNotFoundError, ProfileUnavailableError
from candleviewer.accounts.models import ExchangeAccount
from candleviewer.api import trade_group_preview as route
from candleviewer.api._generated import openapi_models as api
from candleviewer.api.order_principal import TradingPrincipal
from candleviewer.api.preview_limiter import PreviewLimiter
from candleviewer.api.trade_group_preview import (
    PREVIEW_PATH,
    PreviewReads,
    make_trade_group_preview_router,
)
from candleviewer.api.trade_groups_gate import TradeGroupsGate
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.domain.primitives import AccountId
from candleviewer.observability.metrics import Metrics
from candleviewer.oms import ports
from candleviewer.oms.errors import OmsNotReady, StoreUnavailable
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.accounts import GrantScope
from tests.contract.rbac.rbac_harness import bearer_viewing, build_world
from tests.unit.oms.submit_rig import figures as known
from tests.unit.oms.submit_rig import instrument as btcusdt
from tests.unit.oms.submit_rig import profile

A, B, C, L, D, FOREIGN = (AccountId(UUID(int=n)) for n in (1, 2, 5, 3, 4, 9))  # L live, D gone
ALT, NARROW, OFF = UUID(int=91), UUID(int=92), UUID(int=93)  # A's alternates
OWNER, MANAGER, VIEWER = UUID(int=71), UUID(int=72), UUID(int=73)
LABELS: dict[UUID, str] = {A: "E28-A", B: "E28-B", C: "E28-C", L: "E28-LIVE-MAIN"}
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
PREVIEWED, REFUSED = "trade_group.previewed", "trade_group.override_refused"
TRADE = frozenset({Permission.ORDERS_WRITE, Permission.ORDERS_READ})
_GRANTS = tuple(AccountGrant(a, True, True, False) for a in (A, B, C, L, D))
SNAPSHOTS = {
    "owner": PrincipalSnapshot(OWNER, frozenset({"owner"}), frozenset(Permission)),
    "manager": PrincipalSnapshot(MANAGER, frozenset({"manager"}), TRADE, _GRANTS),
    "viewer": PrincipalSnapshot(VIEWER, frozenset({"viewer"}), frozenset({Permission.ORDERS_READ})),
}
#: Bearer token: the principal, the manager's second session included (one user, two sessions).
TOKENS = {who: TradingPrincipal(UUID(int=81), s) for who, s in SNAPSHOTS.items()}
TOKENS["manager_2"] = TradingPrincipal(UUID(int=82), SNAPSHOTS["manager"])


def body(*legs: UUID | tuple[UUID, dict[str, Any]], **over: Any) -> dict[str, Any]:
    """A limit buy of BTCUSDT at 60000, one leg per account named (with its overrides)."""
    named = [
        {"exchange_account_id": str(leg)} if isinstance(leg, UUID)
        else {"exchange_account_id": str(leg[0]), "overrides": leg[1]}
        for leg in legs or (A, B)
    ]  # fmt: skip
    return {"symbol": "BTCUSDT", "side": "buy", "order_type": "limit",
            "defaults": {"price": "60000"}, "legs": named} | over  # fmt: skip


def counted(world: World, outcome: str) -> float:
    labels = {"outcome": outcome, "env": "demo"}
    found = world.metrics.registry.get_sample_value("cv_tradegroup_preview_total", labels)
    return found or 0.0


class World:
    """The router over this world, which fakes every port it reads (module docstring)."""

    def __init__(self, rate: int = 20) -> None:
        self.flag, self.readiness, self.clock = True, "ok", 0.0
        self.records: list[dict[str, Any]] = []
        self.fail: str | None = None  # the action whose write raises
        self.faults: dict[str, BaseException] = {}  # a read's port that raises
        self.read, self.profiled, self.asked = list[UUID](), list[UUID](), list[Any]()
        self.alternates = {
            ALT: profile(A, profile_id=str(ALT), is_default=False),
            NARROW: profile(
                A, profile_id=str(NARROW), is_default=False, leverage="5", max_leverage_cap="5"
            ),
            OFF: profile(A, profile_id=str(OFF), is_default=False, trading_enabled=False),
        }
        self.limiter, self.metrics = PreviewLimiter(rate, clock=lambda: self.clock), Metrics("demo")
        self.runtime: World | None = self
        reads = PreviewReads(self, cast(Any, self), self, "demo")
        app = FastAPI()
        app.include_router(make_trade_group_preview_router(
            self, lambda: self.runtime, reads=reads, audit=self, limiter=self.limiter,
            gate=TradeGroupsGate(lambda: self.flag, preview_ready=True), metrics=self.metrics,
        ))  # fmt: skip
        self.client = TestClient(app, raise_server_exceptions=False)

    def post(self, sent: dict[str, Any] | None = None, who: str = "owner") -> Any:
        headers = {"Authorization": f"Bearer {who}", "Idempotency-Key": "never-read"}
        return self.client.post(
            PREVIEW_PATH, json=body() if sent is None else sent, headers=headers
        )

    def actions(self) -> list[tuple[str, str | None]]:
        return [(r["action"], r["reason"]) for r in self.records]

    def _fault(self, port: str) -> None:
        if (fault := self.faults.get(port)) is not None:
            raise fault

    async def resolve(self, request: Any) -> TradingPrincipal | None:  # the principal source
        self._fault("principal")
        return TOKENS.get(request.headers["authorization"].partition(" ")[2])

    async def emit(self, action: str, **fields: Any) -> None:  # the audit writer
        if action == self.fail:
            raise RuntimeError("the audit writer is not started")
        self.records.append({"action": action, **fields})

    async def get_account(self, scope: Any, account_id: UUID) -> ExchangeAccount:
        self._fault("accounts")
        self.read.append(account_id)
        if account_id not in LABELS or (
            isinstance(scope, GrantScope) and account_id not in scope.account_ids
        ):  # missing, deleted or outside the scope: M13's one answer
            raise AccountNotFoundError("account")
        row = {"id": account_id, "env": "live" if account_id == L else "demo", "kind": "main"}
        row |= {"exchange_uid": "1001", "label": LABELS[account_id]}
        return ExchangeAccount.model_validate(row | {"created_at": NOW, "updated_at": NOW})

    async def get_effective_profile(self, account_id: UUID, profile_id: UUID | None = None) -> Any:
        self._fault("profiles")
        self.profiled.append(account_id)
        if profile_id is None:
            return profile(AccountId(account_id))
        found = self.alternates.get(profile_id)
        if found is None or found.account_id != account_id:  # another account's: a miss
            raise AccountNotFoundError("profile")
        return found

    def reason(self, account_id: UUID, environment: Any, *, account_enabled: bool) -> Any:
        return None  # every member ready

    @property
    def preview(self) -> World:  # the OMS runtime's preview reads, as `oms_wiring.PreviewParts`
        self._fault("preview")
        return self

    guard = instruments = prices = figures = property(lambda self: self)
    stops = ports.InterimStopResolver()

    def refusal(self, order: Any, *, profile: Any, instrument: Any) -> None:
        return None  # the guard admits

    async def instrument(self, symbol: str) -> Any:
        return btcusdt() if symbol == "BTCUSDT" else None

    async def market(self, symbol: str) -> ports.MarketReading:
        return ports.MarketReading(mid=None, last=None)  # a limit leg is sized at its price

    async def peeked(self, symbol: str, fallbacks: dict[UUID, Decimal | None]) -> dict[UUID, Any]:
        self.asked.append(dict(fallbacks))
        return {account: known() for account in fallbacks}


@pytest.fixture
def world() -> World:
    return World()


def test_an_answered_preview_writes_one_trade_group_previewed_record(world: World) -> None:
    """Ruling 2: a `200` of 22's `TradeGroupPreview`, each leg with its account row's label, after
    one row naming the request's ids, symbol and side, the role and the counts, never a figure;
    each leg's figures peeked at its bound profile's fallback; no key or arm token is read (22)."""
    got = world.post(body(A, B, (C, {"skip": True})))
    assert got.status_code == 200
    doc = api.TradeGroupPreview.model_validate(got.json())
    assert [(leg.status, leg.account_label) for leg in doc.legs] == [
        ("ready", "E28-A"), ("ready", "E28-B"), ("skipped", "E28-C"),
    ]  # fmt: skip
    assert world.asked == [{A: Decimal("0.02"), B: Decimal("0.02")}] and C not in world.profiled
    ids, counts = [str(A), str(B), str(C)], {"ready": 2, "warn": 0, "skipped": 1, "blocked": 0}
    assert world.records == [{
        "action": PREVIEWED, "actor_label": str(OWNER), "actor_user_id": OWNER,
        "actor_ip": "testclient", "object_kind": "trade_group_preview", "outcome": "success",
        "severity": "info", "reason": None, "request_id": None, "env": "demo", "after_state": {
            "symbol": "BTCUSDT", "side": "buy", "exchange_account_ids": ids, "role": "owner",
            "outcomes": counts,
        },
    }]  # fmt: skip


def test_previews_past_the_rate_are_429_with_retry_after_and_never_need_a_key() -> None:
    """AC 8, ruling 2, R1S-04: the user's bucket, taken after the session and before RBAC, so the
    user's two sessions share it and a refused role is bounded too; past it `429 rate_limited`
    with `Retry-After`, counted and never recorded; it refills at the rate."""
    world = World(rate=2)
    assert [world.post(who=who).status_code for who in ("manager", "manager_2")] == [200, 200]
    limited = world.post(who="manager")
    assert (limited.status_code, limited.json()["code"]) == (429, "rate_limited")
    assert (limited.headers["retry-after"], limited.json()["retry_after_seconds"]) == ("1", 1)
    assert counted(world, "rate_limited") == 1 and world.actions() == [(PREVIEWED, None)] * 2
    assert [world.post(who="viewer").status_code for _ in range(3)] == [403, 403, 429]
    assert world.post(who="nobody").status_code == 401 and len(world.limiter) == 2  # no bucket
    world.clock += 1.0
    assert world.post(who="manager_2").status_code == 200


def test_a_viewer_gets_403(world: World) -> None:
    """PF-I03: the submit's permission, `orders:write`, and no other: a Viewer's `403 forbidden`
    is recorded `rbac.denied` and previews nothing; unrecorded, 503 (C-2.9)."""
    got = world.post(who="viewer")
    assert (got.status_code, got.json()["required_permissions"]) == (403, ["orders:write"])
    assert world.actions() == [("rbac.denied", "missing_permission:orders:write:none")]
    world.fail = "rbac.denied"
    assert world.post(who="viewer").json()["code"] == "audit_unavailable"
    assert world.read == world.asked == []


def test_the_flag_off_refuses_the_preview_after_rbac_with_no_reason(world: World) -> None:
    """21 Sec.10.7: `trading.trade_groups` off, `403 trading_disabled` with no `reason`, recorded
    before the body is read; a Viewer still meets RBAC first."""
    world.flag = False
    got = world.post({"not": "read"})
    assert (got.status_code, got.json()["code"], "reason" in got.json()) == (
        403, "trading_disabled", False,
    )  # fmt: skip
    assert world.actions() == [(PREVIEWED, "trading_disabled")]
    assert world.records[0]["after_state"] == {"role": "owner", "outcomes": {}}
    assert world.post(who="viewer").json()["code"] == "forbidden"


@pytest.mark.parametrize(
    ("sent", "errors"),
    [
        (body(A, B, A), [("legs[2].exchange_account_id", "duplicate_account")]),
        (body(A, B) | {"defaults": {"price": "60000", "sizing": {"mode": "fixed_qty",
         "qty": "0.01", "round_to_lot": False}}},
         [("defaults.sizing.round_to_lot", "qty_rounding")]),
        (body((A, {"sizing": {"mode": "profile", "round_to_lot": False}}), B),
         [("legs[0].overrides.sizing.round_to_lot", "qty_rounding")]),
        (body(A) | {"legs": []}, [("legs", "too_short")]),
        ({k: v for k, v in body(A, A).items() if k != "defaults"},
         [("legs[1].exchange_account_id", "duplicate_account")]),
        (body() | {"note": "x" * 17_000}, [("body", "body_too_large")]),
    ],
)  # fmt: skip
def test_a_repeated_account_is_422_before_any_read(
    world: World, sent: dict[str, Any], errors: list[tuple[str, str]]
) -> None:
    """SR-E28-17 and ADR-0040 row 16 (R1C-03): a repeated account and `round_to_lot: false` are
    the body's 422 with the shape's, decided before any account is read, and recorded."""
    got = world.post(sent)
    assert got.status_code == 422
    assert [(e["field"], e["rule"]) for e in got.json()["errors"]] == errors
    assert world.actions() == [(PREVIEWED, errors[0][1])] and world.read == []


def test_an_ungranted_and_a_missing_account_refuse_the_whole_preview_alike() -> None:
    """PF-I01, SR-E29-13 (R1S-05): a leg outside the grants, on a deleted account, or on none
    refuses the whole request with one byte-identical `403 account_scope_denied`, counted and
    recorded `rbac.denied` naming the account, as `placeOrder` records it, then previewed; no
    profile or figure is read before it, and a grant is judged before any row is read."""
    answers, reason = set(), "account_not_granted:orders:write:granted_accounts"
    for who, offending, rows in (("manager", FOREIGN, []), ("manager", D, [A, D]),
                                 ("owner", FOREIGN, [A, FOREIGN])):  # fmt: skip
        world = World()
        got = world.post(body(A, offending), who=who)
        answers.add((got.status_code, got.content))
        assert [(r["action"], r["reason"], r.get("object_id")) for r in world.records] == [
            ("rbac.denied", reason, str(offending)), (PREVIEWED, "account_scope_denied", None),
        ]  # fmt: skip
        assert (world.read, world.profiled, world.asked) == (rows, [], [])
    assert len(answers) == 1 and next(iter(answers))[0] == 403


def test_a_leg_outside_this_environment_is_400_counted_and_never_peeked(world: World) -> None:
    """SR-E28-16, C-2.11 (S0's R1S-04, S3b's R1S-01): a leg on another environment's account is
    `400 validation_failed`, `environment_mismatch` per leg, counted and recorded, and never
    reaches the figures; the scope check comes first, so an ungranted leg beside it is the 403."""
    got = world.post(body(A, L))
    entry = {"field": "legs[1].exchange_account_id", "rule": "environment_mismatch"}
    entry["message"] = "This account is not in this server's environment."
    assert (got.status_code, got.json()["errors"]) == (400, [entry])
    assert counted(world, "environment_mismatch") == 1
    assert world.actions() == [(PREVIEWED, "environment_mismatch")] and world.asked == []
    assert world.post(body(L, FOREIGN), who="manager").json()["code"] == "account_scope_denied"
    assert counted(world, "environment_mismatch") == 1


def test_a_foreign_profile_id_is_404_after_the_scope_check(world: World) -> None:
    """SR-E28-03: an alternate that is not one of its leg's account's own profiles (A's named on
    B's leg) is `404 not_found` before anything is sized; an ungranted leg beside it is the
    scope's 403 first."""
    foreign = {"profile_id": str(ALT)}
    got = world.post(body((B, foreign), A))
    assert (got.status_code, got.json()["code"]) == (404, "not_found")
    assert world.actions() == [(PREVIEWED, "not_found")] and world.asked == []
    assert world.post(body((B, foreign), FOREIGN), who="manager").status_code == 403


@pytest.mark.parametrize(
    ("over", "field", "rule"),
    [
        ({"intent": "scale_out"}, "intent", "intent_mismatch"),
        ({"reduce_only": True}, "reduce_only", "intent_mismatch"),
        ({"algo": {"kind": "twap"}}, "algo.kind", "algo_unsupported"),
        ({"trigger": {"price": "61000", "direction": "rise"}}, "defaults.trigger",
         "trigger_unsupported"),
        ({"trailing_stop": {"unit": "percent", "value": "1"}}, "defaults.trailing_stop",
         "trailing_stop_unsupported"),
        ({"sizing": {"mode": "pct_position", "pct": "50"}}, "defaults.sizing.mode",
         "sizing_mode_unsupported"),
        ({"stop_loss": {"unit": "price", "value": "0"}}, "defaults.stop_loss",
         "native_stop_required"),
    ],
)  # fmt: skip
def test_what_the_planner_does_not_carry_is_400_before_any_figure(
    world: World, over: dict[str, Any], field: str, rule: str
) -> None:
    """S3a's carry: refused as `placeOrder` refuses it, recorded by its rule, before the figures."""
    top = {k: v for k, v in over.items() if k in ("intent", "reduce_only", "algo")}
    sent = body(**top) | ({} if top else {"defaults": {"price": "60000"} | over})
    got = world.post(sent)
    assert (got.status_code, [(e["field"], e["rule"]) for e in got.json()["errors"]]) == (
        400, [(field, rule)],
    )  # fmt: skip
    assert world.actions() == [(PREVIEWED, rule)] and world.asked == []


@pytest.mark.parametrize(
    ("overrides", "rule", "limit"),
    [
        ({"leverage": "11"}, "max_leverage_cap", "10"),  # past _B_'s cap
        ({"profile_id": str(NARROW), "leverage": "6"}, "max_leverage_cap", "5"),  # min(B, A)
        ({"profile_id": str(OFF)}, "trading_enabled", None),  # an alternate that does not trade
    ],
)
def test_a_widening_before_planning_is_403_recorded_ahead_and_reads_no_figure(
    world: World, overrides: dict[str, Any], rule: str, limit: str | None
) -> None:
    """R1S-03: before anything is sized, an alternate that is not enabled and trading, and a
    leverage above the tighter `max_leverage_cap` of _B_ and _A_, refuse the whole request as a
    widening does, each offending leg's `trade_group.override_refused` row written first."""
    got = world.post(body((A, overrides), B))
    entry = {"field": "legs[0]", "rule": rule, "message": "This leg would go past its bound "
             "profile's caps."} | ({} if limit is None else {"limit": limit})  # fmt: skip
    assert (got.status_code, got.json()["code"], got.json()["errors"]) == (
        403, "risk_limit_breached", [entry],
    )  # fmt: skip
    assert world.actions() == [(REFUSED, "risk_limit_breached"), (PREVIEWED, "risk_limit_breached")]
    refusal = world.records[0]["after_state"]
    assert (refusal["leg"], refusal["role"], refusal["violations"][0]["field"]) == (
        0,
        "owner",
        rule,
    )
    assert world.records[1]["after_state"]["outcomes"] == {"refused": 1} and world.asked == []


def test_a_widening_preview_is_403_and_each_offending_leg_is_audited_ahead(world: World) -> None:
    """D6: a size the day's loss cap clamps, on two legs, is refused whole, one `errors[]` entry
    per leg with the cap's limit, each leg's `trade_group.override_refused` row ahead of the
    previewed row; any of them unwritten is 503, with nothing answered past it (C-2.9)."""
    big = {"sizing": {"mode": "fixed_qty", "qty": "0.2"}}
    got = world.post(body((A, big), (B, big)))
    named = [(e["field"], e["rule"], "limit" in e) for e in got.json()["errors"]]
    assert (got.status_code, named) == (
        403, [("legs[0]", "max_daily_loss", True), ("legs[1]", "max_daily_loss", True)],
    )  # fmt: skip
    assert [action for action, _ in world.actions()] == [REFUSED, REFUSED, PREVIEWED]
    assert [r["object_id"] for r in world.records[:2]] == [str(A), str(B)]
    for fail in (REFUSED, PREVIEWED):
        world.fail = fail
        assert world.post(body((A, big), B)).json()["code"] == "audit_unavailable"


@pytest.mark.parametrize("who", ["owner", "manager"])
def test_an_unwritable_record_answers_503(world: World, who: str) -> None:
    """C-2.9: a preview, or a refusal of one, whose `trade_group.previewed` row cannot be written
    is `503 audit_unavailable`, never the answer it would have been."""
    world.fail = PREVIEWED
    for flag in (True, False):
        world.flag = flag
        got = world.post(who=who)
        assert (got.status_code, got.json()["code"]) == (503, "audit_unavailable")
    assert world.records == []


@pytest.mark.parametrize(
    ("fault", "status", "code"),
    [
        ("no principals", 501, "not_implemented"),
        ("no runtime", 501, "not_implemented"),
        ("no reads", 503, "store_unavailable"),
        ("starting", 503, "oms_not_ready"),
        ("principal", 503, "store_unavailable"),
        ("accounts", 503, "store_unavailable"),
        ("profiles", 503, "store_unavailable"),
        ("preview", 503, "oms_not_ready"),
    ],
)
def test_an_unwired_or_unread_dependency_answers_503_or_501_unrecorded(
    fault: str, status: int, code: str
) -> None:
    """No principal source or OMS runtime composed is 501, as on `placeOrder`; a runtime not ready,
    a principal, row or profile that cannot be read, or the OMS gone meanwhile, 503 with nothing
    recorded past RBAC: no decision was made on the request."""
    world = World()
    if fault in ("no principals", "no reads"):
        reads = PreviewReads(world, cast(Any, world), world, "demo")
        app = FastAPI()
        app.include_router(make_trade_group_preview_router(
            None if fault == "no principals" else world, lambda: world, audit=world,
            reads=None if fault == "no reads" else reads, limiter=world.limiter,
            gate=TradeGroupsGate(lambda: True, preview_ready=True), metrics=Metrics("demo"),
        ))  # fmt: skip
        world.client = TestClient(app, raise_server_exceptions=False)
    world.runtime = None if fault == "no runtime" else world
    world.readiness = "starting" if fault == "starting" else "ok"
    world.faults = {"principal": StoreUnavailable(), "preview": OmsNotReady(),
                    "accounts": StorageTierUnavailable("down"),
                    "profiles": ProfileUnavailableError("down")}  # fmt: skip
    world.faults = {port: error for port, error in world.faults.items() if port == fault}
    got = world.post()
    assert (got.status_code, got.json()["code"], world.records) == (status, code, [])


def test_an_unlisted_symbol_or_a_planners_refusal_is_400_recorded(world: World) -> None:
    """The listing's `listed` and the planner's own refusals (an `r_multiple` stop) are answered
    as `placeOrder` answers them, each recorded by its rule."""
    got = world.post(body() | {"symbol": "DOGEUSDT"})
    assert [(e["field"], e["rule"]) for e in got.json()["errors"]] == [("symbol", "listed")]
    stopped = body() | {"defaults": {"price": "60000", "stop_loss": {"unit": "r_multiple",
                                                                       "value": "1"}}}  # fmt: skip
    got = world.post(stopped)
    assert (got.status_code, got.json()["errors"][0]["rule"]) == (400, "stop_unit_unsupported")
    assert world.actions() == [(PREVIEWED, "listed"), (PREVIEWED, "stop_unit_unsupported")]


def test_a_viewing_session_is_refused_by_the_view_as_guard_before_the_route() -> None:
    """#3085: the preview is no protective write, so the view-as guard refuses a viewing session
    `view_as_read_only`, as it refuses any write, and the route never runs: nothing is recorded."""
    with pytest.MonkeyPatch.context() as mp:
        world = build_world(mp)
        got = world.client.post(
            PREVIEW_PATH, json=body(), headers=bearer_viewing("manager_with_grant")
        )
        actions = [record["action"] for record in world.audit.records]
    assert (got.status_code, got.json()["code"]) == (403, "view_as_read_only")
    assert "rbac.denied" not in actions and PREVIEWED not in actions


def test_the_route_reaches_no_write_or_exchange_port() -> None:
    """The read-only guarantee (the plan on #909, SR-E28-22): the route reaches the OMS through
    the planner, its guard's type, its errors and its ports' types, and the submit module for its
    store bound alone; no exchange, no store but the accounts' scope type, and no wiring."""
    froms = [
        n for n in ast.walk(ast.parse(inspect.getsource(route))) if isinstance(n, ast.ImportFrom)
    ]
    modules = {n.module or "" for n in froms}
    near = ("candleviewer.oms", "candleviewer.exchange", "candleviewer.storage")
    assert {m for m in modules if m.startswith(near)} == {
        "candleviewer.oms", "candleviewer.oms.classify", "candleviewer.oms.errors",
        "candleviewer.oms.fanout", "candleviewer.oms.fanout.guard", "candleviewer.oms.submit",
        "candleviewer.storage.errors", "candleviewer.storage.repositories.accounts",
    }  # fmt: skip
    whole = ("candleviewer.oms", "candleviewer.oms.fanout", "candleviewer.oms.submit")
    named = {f"{n.module}.{a.name}" for n in froms for a in n.names if n.module in whole}
    assert named == {"candleviewer.oms.ports", "candleviewer.oms.fanout.plan",
                     "candleviewer.oms.submit.STORE_TIMEOUT_S"}  # fmt: skip
    assert not [m for m in modules if "wiring" in m]
