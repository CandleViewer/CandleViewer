"""E28-T05 S3a (#909): the trade-group planner, over a recording fake guard (`S4SGuard` is tested
on its own). Each leg is sized by its own profile from one snapshot; every leg is planned before a
widening refuses the whole group; a leg lacking a native stop or readiness, or that the guard
refuses, is blocked; no write or exchange port is in reach (SR-E28-03, -04, -22; C-2.6, C-2.21)."""

from __future__ import annotations

import ast
import inspect
from dataclasses import replace
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from structlog.testing import capture_logs

import candleviewer.oms.fanout.plan as planner
from candleviewer.accounts.override_comparator import OVERRIDE_CLASS, ProfileNotFound, ResolvedLeg
from candleviewer.accounts.sizer_metrics import SizerMetrics, size_leg_observed
from candleviewer.domain.primitives import AccountId, Environment
from candleviewer.observability.metrics import Metrics
from candleviewer.oms import ports
from candleviewer.oms.errors import OrderInvalid, StopUnitUnsupported
from candleviewer.oms.fanout.plan import GroupPlan, GroupRefused, LegProfiles, LegRequest, LegTerms
from tests.unit.oms.submit_rig import figures, instrument, profile

D = Decimal
A, B, C, E, F = (AccountId(UUID(int=n)) for n in range(1, 6))
ALT = UUID(int=99)  # an alternate profile of A's
RISK = {"sizing_mode": "risk_based", "fixed_qty": None, "risk_pct_equity": "0.005"}


class _Ready:
    """A readiness source answering from `table`, or for a row switched off; it records asks."""

    def __init__(self, table: dict[UUID, Any] | None = None) -> None:
        self.table, self.asked = table or {}, list[UUID]()

    def reason(self, account_id: UUID, environment: Environment, *, account_enabled: bool) -> Any:
        self.asked.append(account_id)
        answer = self.table.get(account_id) if account_enabled else "account_disabled"
        if isinstance(answer, Exception):
            raise answer
        return answer


class _Guard:
    """A `LegGuard` recording the order and profile it is handed; it answers, or raises."""

    def __init__(self, answer: Any = None) -> None:
        self.answer, self.seen = answer, list[tuple[ports.SizedOrder, Any]]()

    def refusal(self, order: ports.SizedOrder, *, profile: Any, instrument: Any) -> Any:
        self.seen.append((order, profile))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _request(*legs: LegRequest, **terms: Any) -> planner.GroupRequest:
    """A limit buy of BTCUSDT at 60000 unless `terms` says otherwise (no mid: sized there)."""
    defaults = LegTerms(**({"price": D(60000)} | terms))
    return planner.GroupRequest("BTCUSDT", "buy", "limit", legs, defaults)


def _plan(
    request: planner.GroupRequest,
    held: dict[AccountId, Any],
    *,
    mid: Decimal | None = None,
    known: dict[UUID, Any] | None = None,
    ready: _Ready | None = None,
    unread: bool = False,
    off: tuple[UUID, ...] = (),
    guard: _Guard | None = None,
    environment: Environment = "demo",
) -> tuple[GroupPlan | GroupRefused, list[UUID], _Ready]:
    reads: list[UUID] = []

    def read(account_id: UUID) -> Any:
        reads.append(account_id)
        return (known or {}).get(account_id, figures())

    source = ready or _Ready()
    snapshot = planner.take_snapshot(
        [(leg.account_id, leg.account_id not in off) for leg in request.legs],
        environment=environment, instrument=instrument(), mid=mid, last=None, figures=read,
        readiness=source,
    )  # fmt: skip
    snapshot = replace(snapshot, readiness={}) if unread else snapshot  # no readiness was read
    profiles = {a: p if isinstance(p, LegProfiles) else LegProfiles(p) for a, p in held.items()}
    result = planner.plan_group(
        request, profiles=profiles, snapshot=snapshot, guard=guard or _Guard(),
        stops=ports.InterimStopResolver(), observer=SizerMetrics.register(Metrics("demo")),
    )  # fmt: skip
    return result, reads, source


def _rows(plan: GroupPlan | GroupRefused) -> list[tuple[str, str | None, Decimal | None]]:
    assert isinstance(plan, GroupPlan)
    return [(p.status, p.reason, None if p.sizing is None else p.sizing.qty) for p in plan.legs]


def _sent(plan: GroupPlan | GroupRefused) -> list[ResolvedLeg]:
    assert isinstance(plan, GroupPlan)
    return [p.admitted.leg for p in plan.legs if p.admitted is not None]


def _refused(plan: GroupPlan | GroupRefused) -> list[tuple[int, list[tuple[str, str, str]]]]:
    assert isinstance(plan, GroupRefused)
    return [(r.index, [(v.field, v.rule, v.reason) for v in r.violations]) for r in plan.legs]


def test_each_leg_is_sized_by_its_own_profile_from_one_snapshot() -> None:
    """AC 5's shape: A and C risk 0.5 % of their equity, C asking a lower leverage and a nearer
    take-profit; B (hedge) a fixed 0.1 whose `atr` stop falls back to 2 % (`warn`, a WARN). One
    read and one ask an account; each native stop covers its whole leg; logs: ids and codes."""
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
    assert [(s.stop_price, s.stop_qty, s.position_idx, s.take_profit_price, s.leverage)
            for s in _sent(plan)] == [(D(57000), D("0.163"), 0, D(66000), D(10)),
                                      (D(58800), D("0.1"), 1, D(62400), D(10)),
                                      (D(57000), D("0.081"), 0, D(63000), D(5))]  # fmt: skip
    assert isinstance(plan, GroupPlan)
    assert plan.totals == planner.GroupTotals(3, 3, D("0.344"), D(20640), D("874.704"), D("22.704"))
    warned = [(sorted(e), e["account_id"]) for e in logs if e["log_level"] == "warning"]
    assert warned == [(["account_id", "event", "log_level"], str(B))]
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
    """D6: A's 0.2 is clamped by the day's 500 USDT of loss, F's under the minimum by the 0.1 USDT
    left of it (its sizer fails `cap_breached`); C's stop and E's take-profit lie further than the
    profile's: refused whole, naming all four (SR-E28-03/04); so is A's clamped size when it then
    fails on margin. Unasked, a profile's own leg is only blocked, by its comparator (B: an entry
    under `reduce_only_default`) or by a cap failing it (F); a cap that clamps it is explained (C,
    ADR-0040: only the profile's own sizing clamps)."""
    big = LegTerms(sizing=ports.SizingRequest(mode="fixed_qty", qty=D("0.2")))
    further = LegTerms(stop_loss=ports.StopOffset(unit="price", value=D(56000)))
    far = LegTerms(take_profit=ports.StopOffset(unit="price", value=D(70000)))
    legs = (LegRequest(A, big), LegRequest(B), LegRequest(C, further), LegRequest(E, far),
            LegRequest(F, big))  # fmt: skip
    spent: dict[UUID, Any] = {F: figures(realised_loss_today="499.9")}
    plan, _, _ = _plan(_request(*legs), {a: profile(a) for a in (A, B, C, E, F)}, known=spent)
    refused = _refused(plan)
    assert [index for index, _ in refused] == [0, 2, 3, 4]
    assert refused[0][1] == refused[3][1] == [("max_daily_loss", "narrow_only", "above_limit")]
    assert ("sl_offset_value", "R4", "further_than_bound") in refused[1][1]
    assert refused[2][1] == [("tp_offset_value", "narrow_only", "further_than_bound")]
    assert isinstance(plan, GroupRefused)
    assert [plan.legs[i].violations[0].requested for i in (0, 3)] == [D("0.2")] * 2
    thin: dict[UUID, Any] = {A: figures(available_margin="500")}  # then fails on margin
    margin, _, _ = _plan(_request(LegRequest(A, big)), {A: profile(A)}, known=thin)
    assert _refused(margin) == [(0, [("max_daily_loss", "narrow_only", "above_limit")])]
    held = {A: profile(A), B: profile(B, reduce_only_default=True),
            C: profile(C, max_position_notional="300"), F: profile(F)}  # fmt: skip
    own, _, _ = _plan(_request(*map(LegRequest, held)), held, known=spent)
    assert _rows(own) == [("ready", None, D("0.01")), ("blocked", "cap_breached", D("0.01")),
                          ("ready", None, D("0.005")), ("blocked", "cap_breached", 0)]  # fmt: skip
    clamped = own.legs[2].sizing if isinstance(own, GroupPlan) else None
    assert clamped is not None and "capped by max_position_notional" in clamped.render()


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


def test_an_alternates_held_fields_are_the_never_rows_but_its_identity() -> None:
    """ADR-0040: _A_'s `never` rows, but its identity, are held at _B_'s (`enabled` among them)."""
    identity = {"profile_id", "account_id", "name", "is_default", "version", "updated_at"}
    assert planner._HELD == {f for f, row in OVERRIDE_CLASS.items() if row == "never"} - identity


def test_the_guard_reads_the_legs_caps_at_the_tighter_of_bound_and_alternate() -> None:
    """ADR-0040 rows 29 to 36: _A_ only tightens _B_'s caps, a `None` being no value from its
    side, so the guard reads _B_'s cap where _A_'s is looser and _A_'s where it is tighter."""
    looser = {"max_open_positions": 50, "max_leverage_cap": D(20), "max_concurrent_orders": 50,
              "max_position_notional": D(30000), "max_position_pct_equity": D("0.9")}  # fmt: skip
    tighter = {"max_daily_loss": D(400), "max_daily_loss_pct": D("0.01"),
               "max_orders_per_minute": 30}  # fmt: skip
    other = profile(A, profile_id=ALT, is_default=False, fixed_qty="0.005", **looser, **tighter)
    guard = _Guard()
    plan, _, _ = _plan(_request(LegRequest(A)), {A: LegProfiles(profile(A), other)}, guard=guard)
    assert _rows(plan) == [("ready", None, D("0.005"))]
    [(_, seen)] = guard.seen
    assert (seen.profile_id, seen.fixed_qty) == (ALT, D("0.005"))
    caps = {"max_open_positions": 1, "max_leverage_cap": D(10), "max_concurrent_orders": 5,
            "max_position_notional": D(20000), "max_position_pct_equity": D("0.5")}  # fmt: skip
    assert {f: getattr(seen, f) for f in caps | tighter} == caps | tighter


def test_a_legs_terms_are_its_side_type_layers_and_profiles() -> None:
    """A hedge sell is index 2, its stop above entry; a market buy is sized from the mid, the
    guard seeing it so, on the snapshot's environment (live) and with the take-profit sent, its
    unnamed terms the profile's time-in-force, `Full` and one-way's index; `overrides` win over
    `defaults` member by member, the guard handed each leg's own profile."""
    sell, _, _ = _plan(replace(_request(LegRequest(A)), side="sell"),
                       {A: profile(A, position_mode="hedge")})  # fmt: skip
    [leg] = _sent(sell)
    assert (leg.side, leg.position_idx, leg.stop_price) == ("sell", 2, D(63000))
    guard = _Guard()
    market = replace(_request(LegRequest(A), price=None), order_type="market")
    fok = {A: profile(A, time_in_force_default="FOK")}
    plan, _, _ = _plan(market, fok, mid=D(60000), guard=guard, environment="live")
    assert _rows(plan) == [("ready", None, D("0.01"))]
    [(order, _)], [leg] = guard.seen, _sent(plan)
    assert (order.order_type, order.price, order.reference_price) == ("market", None, D(60000))
    assert (order.environment, order.qty, order.take_profit) == ("live", D("0.01"), D(66000))
    assert (leg.time_in_force, leg.tpsl_mode, leg.position_idx) == ("FOK", "Full", 0)
    guard = _Guard()
    lower = LegRequest(B, LegTerms(leverage=D(3), time_in_force="IOC"))
    both = _request(LegRequest(A), lower, leverage=D(5), time_in_force="FOK", tpsl_mode="Partial")
    plan, _, _ = _plan(both, {A: profile(A), B: profile(B)}, guard=guard)
    assert [(s.leverage, s.time_in_force, s.tpsl_mode) for s in _sent(plan)] == [
        (D(5), "FOK", "Partial"), (D(3), "IOC", "Partial")
    ]  # fmt: skip
    assert [seen.leverage for _, seen in guard.seen] == [D(5), D(3)]


@pytest.mark.parametrize(
    ("terms", "named"),
    [({"sizing": ports.SizingRequest(mode="profile", max_notional_usd=D(100))},
      ("max_position_notional", "R1", "above_limit")),
     ({"time_in_force": "GTC"}, ("time_in_force_default", "narrow_only", "above_limit")),
     ({"position_idx": 1}, ("position_mode", "never", "changed"))],
    ids=["max_notional_usd", "time_in_force", "position_idx"],
)  # fmt: skip
def test_a_term_asked_alone_past_the_profile_refuses_the_whole_request(
    terms: dict[str, Any], named: tuple[str, str, str]
) -> None:
    """Against a profile resting `IOC` in one-way mode, each asked alone (D6)."""
    held = {A: profile(A, time_in_force_default="IOC")}
    assert _refused(_plan(_request(LegRequest(A), **terms), held)[0]) == [(0, [named])]


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
    member's reason (fail closed); F's figures are not cached, its sizer failing first. Alone, A
    unread is never ready, and its row switched off reaches the source (`account_disabled`)."""
    ready = _Ready({B: "key_invalid", C: TypeError("x"), E: "member_disabled"})
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
    assert _rows(plan) == [("blocked", "trading_disabled", D("0.01"))]
    plan, _, _ = _plan(_request(LegRequest(A)), {A: profile(A)}, off=(A,))
    assert _rows(plan) == [("blocked", "account_disabled", D("0.01"))]


@pytest.mark.parametrize("answer", ["account_locked", "member_disabled", RuntimeError("echoed")])
def test_the_guards_refusal_blocks_its_leg_and_a_raise_fails_closed(answer: Any) -> None:
    """A code outside 22's set, or a raise (which a guard must not do), is
    `risk_state_unavailable`; the raise is logged by its class alone (C-12.6)."""
    with capture_logs() as logs:
        plan, _, _ = _plan(_request(LegRequest(A)), {A: profile(A)}, guard=_Guard(answer))
    code = "account_locked" if answer == "account_locked" else "risk_state_unavailable"
    assert _rows(plan) == [("blocked", code, D("0.01"))] and "echoed" not in repr(logs)
    raised = [(e["account_id"], e["error"]) for e in logs if e["log_level"] == "error"]
    assert raised == [(str(A), "RuntimeError")] * isinstance(answer, Exception)


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


def test_a_repeated_account_or_a_leg_without_profiles_is_refused_whole() -> None:
    """22's `duplicate_account`, a skipped leg's too; no profiles is `ProfileNotFound` (a 404)."""
    with pytest.raises(OrderInvalid) as repeated:
        _plan(_request(LegRequest(A), LegRequest(A, skip=True)), {A: profile(A)})
    assert [(e.field, e.rule) for e in repeated.value.errors] == [("legs", "duplicate_account")]
    with pytest.raises(ProfileNotFound):
        _plan(_request(LegRequest(A), LegRequest(B)), {A: profile(A)})


def test_the_planner_imports_no_write_or_exchange_port() -> None:
    """SR-E28-22, C-2.21: no trading port, OMS command, group store or statechart in reach."""
    tree = ast.parse(inspect.getsource(planner))
    froms = [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert {n.module for n in froms if (n.module or "").startswith("candleviewer")} == {
        "candleviewer.accounts", "candleviewer.accounts.profiles", "candleviewer.accounts.sizer",
        "candleviewer.accounts.sizer_metrics", "candleviewer.accounts.trade_group_readiness",
        "candleviewer.domain.events", "candleviewer.domain.primitives", "candleviewer.oms",
        "candleviewer.oms.errors", "candleviewer.oms.fanout.guard",
    }  # fmt: skip
    packages = {"candleviewer.accounts", "candleviewer.oms"}  # whole modules, imported by name
    assert {f"{n.module}.{a.name}" for n in froms if n.module in packages for a in n.names} == {
        "candleviewer.accounts.override_comparator", "candleviewer.oms.ports",
        "candleviewer.oms.sizing",
    }  # fmt: skip
    read = {n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and ast.unparse(n.value) == "ports"}  # fmt: skip
    assert read == {"OrderEffect", "SizedOrder", "SizingRequest", "StopOffset", "StopResolver",
                    "UNKNOWN_FIGURES"}  # fmt: skip
    plain = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert plain == {"time", "structlog"}
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Await | ast.AsyncFunctionDef)]
