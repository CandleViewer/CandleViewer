"""E28-T05 S3a (#909): the trade-group planner and its E28-T04 hook. Each leg is sized by its own
profile from one snapshot, every leg is planned before a widening refuses the whole group, a leg
lacking a native stop or readiness is blocked, and the planner holds no write or exchange port
(SR-E28-03, -04, -22; C-2.6, C-2.21)."""

from __future__ import annotations

import ast
import inspect
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, get_args
from uuid import UUID

import pytest
from structlog.testing import capture_logs

import candleviewer.oms.fanout.plan as planner
from candleviewer.accounts.override_comparator import OVERRIDE_CLASS, ProfileNotFound
from candleviewer.accounts.sizer import FailReason, SkipReason
from candleviewer.accounts.sizer_metrics import SizerMetrics, size_leg_observed
from candleviewer.accounts.trade_group_readiness import ReadinessReason
from candleviewer.api._generated.openapi_models import Rejection
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.observability.metrics import Metrics
from candleviewer.oms import ports
from candleviewer.oms.errors import OmsNotReady, OrderInvalid, StopUnitUnsupported, TradingDisabled
from candleviewer.oms.fanout.plan import GroupPlan, GroupRefused, LegProfiles, LegRequest, LegTerms
from candleviewer.risk.models import RiskDecision, RiskRefusal
from tests.unit.oms.submit_rig import figures, instrument, profile

D = Decimal
A, B, C, E, F = (AccountId(UUID(int=n)) for n in range(1, 6))
ALT = UUID(int=99)  # an alternate profile of A's
NOW = datetime(2026, 10, 27, tzinfo=UTC)
RISK = {"sizing_mode": "risk_based", "fixed_qty": None, "risk_pct_equity": "0.005"}
ALLOWED = RiskDecision(allowed=True, evaluated_at=NOW)


class _Port:
    """A readiness source (a table), switch or risk gate raising a fence or fault; it records."""

    def __init__(self, answer: Any = None, table: dict[UUID, Any] | None = None) -> None:
        self.answer, self.table, self.asked = answer, table or {}, list[Any]()

    def _answer(self, asked: Any, answer: Any) -> Any:
        self.asked.append(asked)
        if isinstance(answer, OmsNotReady | RuntimeError | TypeError):
            raise answer
        return answer

    def reason(self, account_id: UUID, environment: Environment, *, account_enabled: bool) -> Any:
        return self._answer(account_id, self.table.get(account_id))

    def refusal(self, account_id: AccountId, environment: Environment) -> Any:
        return self._answer(account_id, self.answer)

    def check(self, order: ports.SizedOrder, *, profile: Any) -> Any:
        return self._answer(order, self.answer)


def _guard(gate: Any = None, switch: Any = None) -> planner.S4SGuard:
    return planner.S4SGuard(gate or ports.InterimRiskGate(now=lambda: NOW), _Port(switch))


def _request(*legs: LegRequest, **terms: Any) -> planner.GroupRequest:
    """A limit buy of BTCUSDT at 60000 unless `terms` says otherwise (no mid: sized there)."""
    defaults = LegTerms(**({"price": D(60000)} | terms))
    return planner.GroupRequest("BTCUSDT", "buy", "limit", legs, defaults)


def _plan(
    request: planner.GroupRequest,
    held: dict[AccountId, Any],
    *,
    env: Environment = "demo",
    mid: Decimal | None = None,
    known: dict[UUID, Any] | None = None,
    ready: _Port | None = None,
    unread: bool = False,
) -> tuple[GroupPlan | GroupRefused, list[UUID], _Port]:
    reads: list[UUID] = []

    def read(account_id: UUID) -> Any:
        reads.append(account_id)
        return (known or {}).get(account_id, figures())

    source = ready or _Port()
    snapshot = planner.take_snapshot(
        [(leg.account_id, True) for leg in request.legs], environment=env,
        instrument=instrument(), mid=mid, last=None, figures=read, readiness=source,
    )  # fmt: skip
    snapshot = replace(snapshot, readiness={}) if unread else snapshot  # no readiness was read
    profiles = {a: p if isinstance(p, LegProfiles) else LegProfiles(p) for a, p in held.items()}
    result = planner.plan_group(
        request, profiles=profiles, snapshot=snapshot, guard=_guard(),
        stops=ports.InterimStopResolver(), observer=SizerMetrics.register(Metrics("demo")),
    )  # fmt: skip
    return result, reads, source


def _rows(plan: GroupPlan | GroupRefused) -> list[tuple[str, str | None, Decimal | None]]:
    assert isinstance(plan, GroupPlan)
    return [(p.status, p.reason, None if p.sizing is None else p.sizing.qty) for p in plan.legs]


def _refused(plan: GroupPlan | GroupRefused) -> list[tuple[int, list[tuple[str, str, str]]]]:
    assert isinstance(plan, GroupRefused)
    return [(r.index, [(v.field, v.rule, v.reason) for v in r.violations]) for r in plan.legs]


def test_each_leg_is_sized_by_its_own_profile_from_one_snapshot() -> None:
    """AC 5's shape: A and C risk 0.5 % of their equity, C asking a lower leverage and a nearer
    take-profit; B (hedge) a fixed 0.1 whose `atr` stop falls back to 2 % (`warn`, a WARN). One
    read and one ask an account; each native stop covers its whole leg; DEBUG: ids and codes."""
    held = {A: profile(A, **RISK), C: profile(C, **RISK)}
    held[B] = profile(B, fixed_qty="0.1", position_mode="hedge", sl_offset_unit="atr")
    nearer = ports.StopOffset(unit="price", value=D(63000))
    legs = (LegRequest(A), LegRequest(B),
            LegRequest(C, LegTerms(leverage=D(5), take_profit=nearer)))  # fmt: skip
    half = figures(equity="50000", available_margin="50000")
    with capture_logs() as logs:
        plan, reads, ready = _plan(_request(*legs), held, known={C: half})
    assert _rows(plan) == [("ready", None, D("0.163")), ("warn", None, D("0.1")),
                           ("ready", None, D("0.081"))]  # fmt: skip
    assert reads == ready.asked == [A, B, C]
    assert isinstance(plan, GroupPlan)
    sent = [p.admitted.leg for p in plan.legs if p.admitted is not None]
    assert [(s.stop_price, s.stop_qty, s.position_idx, s.take_profit_price, s.leverage)
            for s in sent] == [(D(57000), D("0.163"), 0, D(66000), D(10)),
                               (D(58800), D("0.1"), 1, D(62400), D(10)),
                               (D(57000), D("0.081"), 0, D(63000), D(5))]  # fmt: skip
    assert plan.totals == planner.GroupTotals(3, 3, D("0.344"), D(20640), D("874.704"), D("22.704"))
    warned = [(e["log_level"], e["account_id"]) for e in logs if e["log_level"] == "warning"]
    assert warned == [("warning", str(B))]
    debug = [sorted(e) for e in logs if e["event"] == "trade_group_leg_planned"]
    assert debug == [["account_id", "event", "leg", "log_level", "reason", "status"]] * 3


def test_skips_carry_their_reason_and_leave_other_legs_alone() -> None:
    """AC 6's shape: B skipped; C and F (overlaid) allow only ETHUSDT; E sizes under 1000 USDT."""
    narrower = LegTerms(sizing=ports.SizingRequest(mode="fixed_qty", qty=D("0.005")))
    eth = {"allowed_symbols": ["ETHUSDT"]}
    held = {A: profile(A), B: profile(B), C: profile(C, **eth), F: profile(F, **eth)}
    held[E] = profile(E, min_leg_notional="1000")
    legs = (LegRequest(A), LegRequest(B, skip=True), LegRequest(C), LegRequest(F, narrower))
    plan, _, _ = _plan(_request(*legs, LegRequest(E)), held)
    alone, _, _ = _plan(_request(LegRequest(A)), {A: profile(A)})
    assert _rows(plan) == [
        ("ready", None, D("0.01")), ("skipped", "skipped", None),
        ("skipped", "symbol_not_allowed", None), ("skipped", "symbol_not_allowed", None),
        ("skipped", "below_min_notional", D("0.01")),
    ]  # fmt: skip
    assert isinstance(plan, GroupPlan) and isinstance(alone, GroupPlan)
    assert plan.legs[0] == alone.legs[0]
    assert plan.totals == replace(alone.totals, accounts_targeted=5)


def test_a_widening_refuses_the_whole_group_naming_every_offending_leg() -> None:
    """D6: A's 0.2 is clamped by the day's 500 USDT of loss; C's stop and E's take-profit lie
    further than the profile's: refused whole, naming all three (SR-E28-03/04). Unasked, a
    profile's own leg its comparator refuses (an entry under `reduce_only_default`) is blocked."""
    further = LegTerms(stop_loss=ports.StopOffset(unit="price", value=D(56000)))
    far = LegTerms(take_profit=ports.StopOffset(unit="price", value=D(70000)))
    legs = (LegRequest(A, LegTerms(sizing=ports.SizingRequest(mode="fixed_qty", qty=D("0.2")))),
            LegRequest(B), LegRequest(C, further), LegRequest(E, far))  # fmt: skip
    plan, _, _ = _plan(_request(*legs), {a: profile(a) for a in (A, B, C, E)})
    refused = _refused(plan)
    assert [index for index, _ in refused] == [0, 2, 3]
    assert refused[0][1] == [("max_daily_loss", "narrow_only", "above_limit")]
    assert ("sl_offset_value", "R4", "further_than_bound") in refused[1][1]
    assert refused[2][1] == [("tp_offset_value", "narrow_only", "further_than_bound")]
    assert isinstance(plan, GroupRefused) and plan.legs[0].violations[0].requested == D("0.2")
    own, _, _ = _plan(
        _request(LegRequest(A), LegRequest(B)),
        {A: profile(A), B: profile(B, reduce_only_default=True)},
    )
    assert _rows(own) == [("ready", None, D("0.01")), ("blocked", "cap_breached", D("0.01"))]


@pytest.mark.parametrize(
    ("alternate", "refused"),
    [({"fixed_qty": "0.005", "fallback_sl_offset_pct": "0.03"}, None),
     ({"fixed_qty": "0.5", "max_position_notional": "100000", "max_daily_loss": "5000"},
      ("max_position_notional", "R1", "above_limit")),
     ({"trading_enabled": False}, ("trading_enabled", "never", "profile_disabled"))],
    ids=["narrower", "past_the_bound_caps", "not_trading"],
)  # fmt: skip
def test_an_alternate_profile_only_narrows(alternate: dict[str, Any], refused: Any) -> None:
    """ADR-0040: _A_ narrows _B_, its `never` fields held at _B_'s; past _B_'s caps it refuses."""
    other = profile(A, profile_id=ALT, is_default=False, **alternate)
    plan, _, _ = _plan(_request(LegRequest(A)), {A: LegProfiles(profile(A), other)})
    if refused is not None:
        assert refused in _refused(plan)[0][1]
        assert isinstance(plan, GroupRefused) and plan.legs[0].alternate == other
        return
    assert _rows(plan) == [("ready", None, D("0.005"))]
    assert isinstance(plan, GroupPlan)
    leg = plan.legs[0]
    assert leg.admitted is not None and leg.admitted.held == ("fallback_sl_offset_pct",)
    assert leg.admitted.leg.profile_id == ALT
    assert leg.profile is not None and leg.profile.fallback_sl_offset_pct == D("0.02")


def test_a_leg_with_no_native_stop_is_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """C-2.6: under a 58000 mid B's 59400 stop is none; nor is an `ok` leg's missing one."""
    held = {A: profile(A), B: profile(B, sl_offset_value="0.01")}
    plan, _, _ = _plan(_request(LegRequest(A), LegRequest(B)), held, mid=D(58000))
    assert _rows(plan) == [("ready", None, D("0.01")), ("blocked", "invalid_stop_distance", None)]
    assert isinstance(plan, GroupPlan) and plan.totals.accounts_submittable == 1
    stop = plan.legs[1].sizing.stop if plan.legs[1].sizing is not None else None
    assert (stop and stop.price, plan.legs[1].admitted) == (D(59400), None)

    def stopless(*args: Any, **kwargs: Any) -> Any:
        return replace(size_leg_observed(*args, **kwargs), stop=None)

    monkeypatch.setattr(planner, "size_leg_observed", stopless)
    plan, _, _ = _plan(_request(LegRequest(A)), {A: profile(A)})
    assert _rows(plan) == [("blocked", "invalid_stop_distance", D("0.01"))]
    assert isinstance(plan, GroupPlan) and plan.totals.accounts_submittable == 0


def test_a_not_ready_member_is_blocked_with_its_reason() -> None:
    """Through `member_reason`: B's key failed; C's source raised and E's answered no enabled
    member's reason (fail closed); F's figures are not cached, its sizer failing first."""
    ready = _Port(table={B: "key_invalid", C: TypeError("x"), E: "member_disabled"})
    request = _request(*map(LegRequest, (A, B, C, E, F)))
    held = {a: profile(a) for a in (A, B, C, E, F)}
    plan, _, _ = _plan(request, held, known={F: None}, ready=ready)
    assert _rows(plan) == [
        ("ready", None, D("0.01")), ("blocked", "key_invalid", D("0.01")),
        ("blocked", "trading_disabled", D("0.01")), ("blocked", "trading_disabled", D("0.01")),
        ("blocked", "figure_unknown", None),
    ]  # fmt: skip
    assert isinstance(plan, GroupPlan) and all(p.admitted is not None for p in plan.legs[:4])
    plan, _, _ = _plan(_request(LegRequest(A)), {A: profile(A)}, unread=True)
    assert _rows(plan) == [("blocked", "trading_disabled", D("0.01"))]  # unread is never ready


@pytest.mark.parametrize("env", ["demo", "testnet", "live"])
def test_the_hook_blocks_what_the_interim_risk_gate_refuses(env: Environment) -> None:
    """`S4SGuard` over the interim risk gate admits demo unevaluated and blocks any other."""
    plan, _, _ = _plan(_request(LegRequest(A)), {A: profile(A)}, env=env)
    row = ("ready", None) if env == "demo" else ("blocked", "risk_state_unavailable")
    assert _rows(plan) == [(*row, D("0.01"))]


def _order(**over: Any) -> ports.SizedOrder:
    """A demo market buy of 1 BTCUSDT from 60000, its native stop at 57000."""
    base: dict[str, Any] = dict(
        account_id=A, environment="demo", symbol="BTCUSDT", side="buy", qty=D(1), price=None,
        order_type="market", trigger_price=None, reduce_only=False, intent="entry",
        reference_price=D(60000), stop_loss=D(57000), effect=ports.OrderEffect.ENTRY,
    )  # fmt: skip
    return ports.SizedOrder(**(base | over))


@pytest.mark.parametrize(
    ("over", "code"),
    [({"qty": D(50)}, None), ({"qty": D("50.001")}, "cap_breached"),
     ({"order_type": "limit", "price": D(60000), "qty": D(60)}, None)],
    ids=["market_at_the_cap", "market_past_it", "limit_past_it"],
)  # fmt: skip
def test_a_market_leg_over_max_mkt_order_qty_is_refused(over: dict[str, Any], code: Any) -> None:
    """The comparator leaves `max_mkt_order_qty` (50 on BTCUSDT) to its caller (#2635)."""
    assert _guard().refusal(_order(**over), profile=profile(A), instrument=instrument()) == code


def _refusal(code: RiskRefusal) -> RiskDecision:
    return RiskDecision(allowed=False, code=code, message="Refused.", evaluated_at=NOW)


@pytest.mark.parametrize(
    ("switch", "decision", "code"),
    [(TradingDisabled(), ALLOWED, "trading_disabled"), (OmsNotReady(), ALLOWED, "trading_disabled"),
     (None, RuntimeError("echoed exchange text"), "risk_state_unavailable"),
     (None, _refusal(RiskRefusal.RISK_LIMIT_BREACHED), "cap_breached"),
     (None, _refusal(RiskRefusal.ACCOUNT_LOCKED), "account_locked"),
     (None, _refusal(RiskRefusal.RISK_STATE_UNAVAILABLE), "risk_state_unavailable")],
    ids=["switched_off", "fenced", "gate_raises", "risk_limit", "locked", "no_state"],
)  # fmt: skip
def test_the_hook_reads_the_switches_then_the_risk_gate_and_fails_closed(
    switch: Any, decision: Any, code: str
) -> None:
    gate = _Port(decision)
    with capture_logs() as logs:
        got = _guard(gate, switch).refusal(_order(), profile=profile(A), instrument=instrument())
    assert got == code and len(gate.asked) == (switch is None)
    assert "echoed" not in repr(logs)  # a port's fault is logged by its class alone (C-12.6)


@pytest.mark.parametrize(
    ("terms", "held", "error", "named"),
    [({"price": None}, None, OrderInvalid, [("price", "finite")]),
     ({"take_profit": ports.StopOffset(unit="price", value=D("NaN"))}, None, OrderInvalid,
      [("sizing", "profile_overlay")]),
     ({"take_profit": ports.StopOffset(unit="atr", value=D(2))}, None, StopUnitUnsupported,
      [("take_profit", "stop_unit_unsupported")]),
     ({"leverage": D(500)}, None, OrderInvalid, [("sizing", "profile_overlay")]),
     ({}, profile(B), ProfileNotFound, []),
     ({}, LegProfiles(profile(A), profile(B, profile_id=ALT)), ProfileNotFound, [])],
    ids=["limit_without_price", "take_profit_not_finite", "take_profit_in_atr",
         "leverage_past_100", "another_accounts_profile", "another_accounts_alternate"],
)  # fmt: skip
def test_a_request_no_leg_can_be_sized_or_judged_by_is_refused_whole(
    terms: dict[str, Any], held: Any, error: type[Exception], named: list[tuple[str, str]]
) -> None:
    with pytest.raises(error) as refused:
        _plan(_request(LegRequest(A), **terms), {A: held or profile(A)})
    assert [(e.field, e.rule) for e in getattr(refused.value, "errors", ())] == named


def test_the_codes_are_22s_and_every_reason_maps_onto_one() -> None:
    """22's `rejection.code` (S0) holds every sizer and enabled-member reason; ADR-0040's holds."""
    (codes,) = (a for a in get_args(Rejection.model_fields["code"].annotation) if get_args(a))
    assert get_args(planner.RejectionCode) == get_args(codes)
    reasons = {r.value for r in (*SkipReason, *FailReason)} | set(get_args(ReadinessReason))
    assert reasons - set(get_args(codes)) == {"member_disabled"}
    identity = {"profile_id", "account_id", "name", "is_default", "version", "updated_at"}
    assert planner._HELD == {f for f, row in OVERRIDE_CLASS.items() if row == "never"} - identity


def test_the_planner_imports_no_write_or_exchange_port() -> None:
    """SR-E28-22, C-2.21: no trading port, OMS command, group store or statechart in reach."""
    tree = ast.parse(inspect.getsource(planner))
    froms = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert {n.module for n in froms if (n.module or "").startswith("candleviewer")} == {
        "candleviewer.accounts", "candleviewer.accounts.profiles", "candleviewer.accounts.sizer",
        "candleviewer.accounts.sizer_metrics", "candleviewer.accounts.trade_group_readiness",
        "candleviewer.domain.events", "candleviewer.domain.primitives", "candleviewer.oms",
        "candleviewer.oms.errors", "candleviewer.risk.models",
    }  # fmt: skip
    packages = {"candleviewer.accounts", "candleviewer.oms"}  # whole modules, imported by name
    assert {f"{n.module}.{a.name}" for n in froms if n.module in packages for a in n.names} == {
        "candleviewer.accounts.override_comparator", "candleviewer.oms.ports",
        "candleviewer.oms.sizing",
    }  # fmt: skip
    read = {n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and ast.unparse(n.value) == "ports"}  # fmt: skip
    assert read == {"OrderEffect", "RiskGate", "SizedOrder", "SizingRequest", "StopOffset",
                    "StopResolver", "TradingSwitches", "UNKNOWN_FIGURES"}  # fmt: skip
    plain = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert plain == {"time", "structlog"}
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Await | ast.AsyncFunctionDef)]
