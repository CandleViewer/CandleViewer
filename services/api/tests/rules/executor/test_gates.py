"""E35-T10 (#5002) slice 2e: the synchronous checks before each rule action (24 §11.5, §11.9).

`Gated` drives one `ActionExecutor` with every one of the 25 types bound to a handler double that
records what it would send, scripted check-1 verdicts, a routing emitter whose scope re-check a test
scripts per node (or the real `ScopedActionEmitter` over a scope snapshot), the switches of checks
2 and 3 (`Switches`, open unless a test closes one), the principal of check 5 (`Principals`: the
owner and the armer active Owners admitting A, B and C, unless a test says otherwise) and the
records in memory. The first refusal wins in the ruled order (BQ-1), and every refusal is
decided before the records written ahead, so it writes `rules.blocked` and never `rules.fired`.
No order path is reached: the doubles stand where E35-T11's handlers will (plan §4).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, get_args

import pytest

from candleviewer.flags_wiring import FeatureFlagsRuntime
from candleviewer.oms_wiring import InterimKillSwitch
from candleviewer.rules.executor.dispatch import Fire
from candleviewer.rules.executor.engine import ActionExecutor, RowVerdict
from candleviewer.rules.executor.gates import PRINCIPAL_MAX_AGE_S, Gates
from candleviewer.rules.executor.handlers import (
    ENGINE_INTERNAL,
    HANDLERS,
    HandlerAnswer,
    HandlerSpec,
    Prepared,
    prepared,
)
from candleviewer.rules.executor.keys import dedupe_key
from candleviewer.rules.ir.models import Action, ActionType, RuleScope
from candleviewer.rules.scope import (
    ActionRequest,
    ScopedActionEmitter,
    ScopeInstanceRef,
    ScopeResolver,
)
from candleviewer.rules.scope_state import SnapshotScopeState
from candleviewer.rules_oms_wiring import RuleSwitchesBinding
from tests.rules.executor.request_builders import (
    Counted,
    Principals,
    Records,
    Switches,
    action_request,
)
from tests.unit.admin.flag_fakes import FakeAudit, FakeStepUp, FakeUsers

RULE, RUN = str(uuid.UUID(int=7)), uuid.UUID(int=8)
OWNER, ARMER = uuid.UUID(int=0xA1), uuid.UUID(int=0xA2)
A, B, C = uuid.UUID(int=0xB1), uuid.UUID(int=0xB2), uuid.UUID(int=0xB3)
TYPES: tuple[str, ...] = get_args(ActionType)


REFUSED = HandlerAnswer("refused", error_code="validation_failed")


class Double:
    """A bound handler: records what it would send, by node and account, and accepts it, but on
    an account of `refuse`, which it refuses."""

    def __init__(
        self, sent: list[tuple[str, str]], answer: HandlerAnswer, refuse: set[uuid.UUID]
    ) -> None:
        self.sent, self.answer, self.refuse = sent, answer, refuse

    def prepare(self, req: ActionRequest, account_id: uuid.UUID | None, **_: Any) -> Prepared:
        return prepared({"node": req.payload.node_id, "account": str(account_id)})

    async def send(self, prep: Prepared, *, client_ref: str) -> HandlerAnswer:
        account = str(prep.request["account"])
        self.sent.append((str(prep.request["node"]), account))
        return REFUSED if account in {str(a) for a in self.refuse} else self.answer


def bound_table(
    sent: list[tuple[str, str]],
    answers: Mapping[str, HandlerAnswer] | None = None,
    refuse: set[uuid.UUID] | None = None,
) -> dict[str, HandlerSpec]:
    """Every type bound to a `Double`, accepting unless `answers` names another answer."""
    answers, refuse = answers or {}, set() if refuse is None else refuse
    return {
        t: replace(spec, handler=Double(sent, answers.get(t, HandlerAnswer("accepted")), refuse))
        for t, spec in HANDLERS.items()
    }


def action(node: str, action_type: str = "place_order", **over: Any) -> ActionRequest:
    """An armed fire's `action_type` action on account A's instance, every param left empty;
    `on_error`, `targets` and `action` go to its IR action, the rest to the request."""
    instance = over.pop("instance", ScopeInstanceRef(f"BTCUSDT@{A}", "BTCUSDT", A))
    ir = {k: over.pop(k) for k in ("on_error", "targets") if k in over} | over.pop("action", {})
    payload = Action.model_validate({"node_id": node, "type": action_type, "params": {}} | ir)
    scope = over.pop(
        "scope", RuleScope.model_validate({"level": "account", "account_ids": [str(A)]})
    )
    base = {"action_type": action_type, "payload": payload, "rule_id": RULE, "run_id": RUN}
    return action_request(scope, OWNER, instance, **(base | {"armed_by": str(ARMER)} | over))


@dataclass
class Gated:
    switches: Any = field(default_factory=Switches)  # the double, or the composition root's
    verdicts: dict[str, list[RowVerdict]] = field(default_factory=dict)
    denied: dict[str, str] = field(default_factory=dict)  # node -> the scope re-check's reason
    answers: dict[str, HandlerAnswer] = field(default_factory=dict)  # type -> its double's answer
    sent: list[tuple[str, str]] = field(default_factory=list)
    records: Records = field(default_factory=Records)
    counted: Counted = field(default_factory=Counted)
    stops: dict[uuid.UUID, Decimal] = field(default_factory=lambda: {A: Decimal("58000")})
    principals: Principals = field(default_factory=lambda: Principals(frozenset({A, B, C})))
    emitter: ScopedActionEmitter | None = None  # the real one, over a scope snapshot
    checked: list[tuple[str, str]] = field(default_factory=list)  # check 1 per (node, account)
    refuse: set[uuid.UUID] = field(default_factory=set)  # the accounts the doubles refuse
    now: float = 1000.0  # the executor's monotonic clock, frozen; the principal reads on it
    executor: ActionExecutor = field(init=False)

    def __post_init__(self) -> None:
        self.principals.clock = self.clock
        self.executor = ActionExecutor(
            check_one=self.check_one, scope_check=self.scope_check, gates=self.gates(),
            records=self.records, audit=self.records, metrics=self.counted.metrics,
            handlers=bound_table(self.sent, self.answers, self.refuse), clock=self.clock,
        )  # fmt: skip

    def clock(self) -> float:
        return self.now

    def gates(self) -> Gates:
        return Gates(switches=self.switches, principal=self.principals)

    async def check_one(self, req: ActionRequest) -> RowVerdict:
        self.checked.append((req.payload.node_id, str(req.instance.account_id)))
        queue = self.verdicts.get(req.payload.node_id)
        return queue.pop(0) if queue else "armed"

    def scope_check(self, req: ActionRequest) -> str | None:
        return self.denied.get(req.payload.node_id)

    async def emit(self, req: ActionRequest) -> str | None:
        """The routing emitter (`emit_checked`): the scope re-check's reason (check 4), else the
        hand-over (`_route`) and `None`."""
        if self.emitter is not None:
            return await self.emitter.emit_checked(req)
        if req.payload.node_id in self.denied:
            return self.denied[req.payload.node_id]
        await self.executor.hand_over(req)
        return None

    async def run(self, *reqs: ActionRequest, **fire: Any) -> None:
        await self.executor.execute(Fire(RULE, RUN, tuple(reqs), self.emit, version_id="v", **fire))

    def results(self) -> list[tuple[str, str, str | None]]:
        return self.records.results()

    def audited(self) -> list[tuple[str, str, str | None]]:
        """`(verb, node, blocked_by)` of every audit record, in order."""
        return [(verb, f.node_id, f.blocked_by) for verb, f in self.records.audits]


def every_type() -> tuple[ActionRequest, ...]:
    return tuple(action(f"a{n}", t, on_error="continue") for n, t in enumerate(TYPES))


def blocked_alone(gated: Gated, reason: str) -> None:
    """Every action is `blocked` with `reason`: one `rules.blocked` each, no `rules.fired`, and no
    handler double called."""
    nodes = [f"a{n}" for n in range(len(TYPES))]
    assert gated.results() == [(node, "blocked", reason) for node in nodes]
    assert gated.audited() == [("rules.blocked", node, reason) for node in nodes]
    assert gated.sent == []


async def test_the_kill_switch_stops_every_rule_action_within_its_guarantee() -> None:
    """Scenario: The kill switch stops every rule action (parent Gherkin 5). An engaged B18 double,
    all 25 types bound to handler doubles and the rollout port on: every action is blocked before
    any handler (`kill_switch`), and positions and their native stops are untouched."""
    gated = Gated(Switches(engaged={None}))
    before = dict(gated.stops)
    await gated.run(*every_type())
    blocked_alone(gated, "kill_switch")
    assert gated.stops == before  # the recorded-stop double: nothing moved, nothing cancelled
    assert gated.counted.blocked() == {"kill_switch": len(TYPES)}


async def test_the_order_entry_kill_switch_flag_blocks_every_rule_action() -> None:
    """Scenario: The order-entry flag blocks too, and an unreadable flag counts as engaged
    (failure case): `killswitch.order_entry` on, read directly, blocks every action."""
    gated = Gated(Switches(order_entry=True))
    await gated.run(*every_type())
    blocked_alone(gated, "kill_switch")


def _runtime() -> FeatureFlagsRuntime:
    """A flag runtime on the fake backend, never started: every view still unread."""
    return FeatureFlagsRuntime(
        None, environment="demo", audit=FakeAudit(), step_up=FakeStepUp(), users=FakeUsers(),
        sessions=SimpleNamespace(authenticated=lambda: []),
    )  # fmt: skip


@dataclass
class _Views:
    rules_enabled: Callable[[], bool]
    order_entry_killed: Callable[[], bool]


class _RolledOut(RuleSwitchesBinding):
    """The composition root's switches with the rollout port on, as E35-T11 will bind it, so an
    OMS action reaches the checks after check 2."""

    def oms_actions(self) -> bool:
        return True


def _bound(views: _Views, *, rolled_out: bool = True) -> RuleSwitchesBinding:
    kind = _RolledOut if rolled_out else RuleSwitchesBinding
    return kind(views, InterimKillSwitch().refusal)


async def test_an_unreadable_kill_switch_flag_blocks_as_engaged() -> None:
    """Scenario: The order-entry flag blocks too, and an unreadable flag counts as engaged
    (failure case): the real view of `killswitch.order_entry`, never read, reads engaged, while
    the master switch reads on and B18 (the OMS's interim) admits."""
    view = _runtime().order_entry_killed
    assert view() is True and not view._read.is_set()
    gated = Gated(_bound(_Views(lambda: True, view)))
    await gated.run(*every_type())
    blocked_alone(gated, "kill_switch")


async def test_maintenance_mode_alone_is_never_read_as_the_kill_switch() -> None:
    """Scenario: The order-entry flag blocks too, and an unreadable flag counts as engaged
    (failure case): maintenance mode keeps its own reason `order_entry`. The maintenance gate is
    engaged, which the checks never read: the action passes check 3 and the OMS's refusal, which
    names the gate's reason, is recorded `order_entry`."""
    assert _runtime().gate.refusal(A) is not None  # maintenance: engaged until its flags are read
    refused = HandlerAnswer("refused", error_code="trading_disabled", blocked_by="order_entry")
    gated = Gated(_bound(_Views(lambda: True, lambda: False)), answers={"place_order": refused})
    await gated.run(action("a1"))
    assert gated.results() == [("a1", "blocked", "order_entry")]
    assert gated.sent == [("a1", str(A))]  # it passed every check and met the OMS's own refusal


@pytest.mark.parametrize("unread", [False, True], ids=["off", "unread"])
async def test_the_master_switch_off_blocks_every_action(unread: bool) -> None:
    """Scenario: The master switch off blocks every action (failure case): `rules.enabled` off,
    or never read (its real view), blocks every action `rules_disabled`, before any other check,
    though the kill switch is engaged and every action is out of scope too."""
    view = _runtime().rules_enabled if unread else (lambda: False)
    gated = Gated(_bound(_Views(view, lambda: True), rolled_out=False))
    gated.denied = {f"a{n}": "grant_revoked" for n in range(len(TYPES))}
    await gated.run(*every_type())
    blocked_alone(gated, "rules_disabled")


#: For each check k, the closures that make it fail on a `Gated` (checks 1 to 4 here, check 8 by
#: `widen_stop`'s type); each later commit adds its own.
def _fail(gated: Gated, check: int) -> None:
    if check == 1:
        gated.verdicts["a1"] = ["mode_changed"]
    elif check == 2:
        gated.switches.enabled = False
    elif check == 3:
        gated.switches.engaged.add(None)
    elif check == 4:
        gated.denied["a1"] = "grant_revoked"
    elif check == 5:
        gated.principals.missing.add(ARMER)


_FIRST: dict[int, tuple[str, str | None]] = {
    1: ("skipped", "mode_changed"), 2: ("blocked", "rules_disabled"), 3: ("blocked", "kill_switch"),
    4: ("blocked", "scope"), 5: ("blocked", "permission"), 8: ("blocked", "native_sl"),
}  # fmt: skip


@pytest.mark.parametrize(
    ("k", "action_type"),
    [(k, "place_order") for k in (1, 2, 3, 4, 5)] + [(k, "widen_stop") for k in (1, 2, 3, 4, 5, 8)],
)
async def test_check_order_is_stable_first_refusal_wins(k: int, action_type: str) -> None:
    """Scenario: The first refusal wins in a fixed order. Checks k to 8 all fail (each that
    applies to the type: check 8 to `widen_stop` by type), and the result names check k's."""
    gated = Gated()
    for check in range(k, 9):
        _fail(gated, check)
    await gated.run(action("a1", action_type))
    outcome, reason = _FIRST[k]
    assert gated.results() == [("a1", outcome, reason)] and gated.sent == []
    assert gated.audited() == [("rules.blocked", "a1", reason)]


async def test_widen_stop_reads_kill_switch_while_engaged_and_native_sl_otherwise() -> None:
    """`widen_stop` is refused by type at check 8's slot, so an engaged kill switch (check 3) reads
    first; with every switch open it is `native_sl`, and `rules.blocked` alone is written."""
    engaged = Gated(Switches(engaged={None}))
    await engaged.run(action("a1", "widen_stop"))
    assert engaged.results() == [("a1", "blocked", "kill_switch")]
    open_ = Gated(Switches(rollout=False))
    await open_.run(action("a1", "widen_stop"))
    assert open_.results() == [("a1", "blocked", "native_sl")]
    assert open_.audited() == [("rules.blocked", "a1", "native_sl")] and open_.sent == []


async def test_an_oms_action_is_unavailable_while_the_rollout_port_reads_off() -> None:
    """Check 2's second half: with its handler bound, an action whose capability reaches past the
    engine is `unavailable` while the rollout port reads off, as the composition root binds it; an
    engine-internal one runs, and `widen_stop` is refused at check 8 by type."""
    gated = Gated(_bound(_Views(lambda: True, lambda: False), rolled_out=False))
    internal = tuple(t for t in TYPES if HANDLERS[t].capability in ENGINE_INTERNAL)
    past = tuple(t for t in TYPES if t not in internal)
    reqs = (action(f"a{n}", t, on_error="continue") for n, t in enumerate(past + internal))
    await gated.run(*reqs)
    refused = {node: reason for node, outcome, reason in gated.results() if outcome == "blocked"}
    expected = {f"a{n}": "unavailable" for n, t in enumerate(past) if t != "widen_stop"}
    assert refused == expected | {f"a{past.index('widen_stop')}": "native_sl"}
    reached = {f"a{n}" for n in range(len(past), len(TYPES))}
    assert {node for node, _ in gated.sent} == reached and len(internal) == 6


# --- The scope environment, `targets` and the principal (BQ-3, BQ-4, BQ-5) -----------------------


class _Source:
    """The scope snapshot's source: the owner's grants on `grants`, each account's environment as
    `envs` holds it (an account it leaves out was not read)."""

    def __init__(self, envs: Mapping[uuid.UUID, str]) -> None:
        self.grants, self.envs = [A, B, C], dict(envs)

    async def load_grants(self, owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
        return [(a, True, False) for a in self.grants]

    async def load_permissions(self, owner: uuid.UUID) -> frozenset[str]:
        return frozenset({"rules:arm_live"})

    async def load_account_environments(
        self, account_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        return {a: self.envs[a] for a in account_ids if a in self.envs}


@dataclass
class _Scoped:
    source: _Source
    state: SnapshotScopeState
    audits: list[tuple[str, dict[str, str]]]


async def _scoped(
    gated: Gated,
    environment: str = "demo",
    *,
    envs: Mapping[uuid.UUID, str] | None = None,
    live_gate: bool = False,
) -> _Scoped:
    """`gated`'s emitter becomes the real `ScopedActionEmitter` over a refreshed scope snapshot."""
    audits: list[tuple[str, dict[str, str]]] = []

    async def audit(event: str, data: dict[str, str]) -> None:
        audits.append((event, data))

    source = _Source(dict.fromkeys((A, B, C), environment) if envs is None else envs)
    state = SnapshotScopeState(source, environment, lambda: live_gate)
    await state.refresh(OWNER)
    gated.emitter = ScopedActionEmitter(
        ScopeResolver(state, audit), audit, gated.executor.hand_over
    )
    return _Scoped(source, state, audits)


def per_account(gated: Gated) -> list[tuple[str, str | None, str, str | None]]:
    """`(node, account, outcome, blocked_by)` of each recorded result, in order."""
    return [
        (
            e.payload["node_id"],
            e.payload["account_id"],
            e.payload["outcome"],
            e.payload["blocked_by"],
        )
        for _, e in gated.records.events
        if e.kind != "action_start"
    ]


def _role(owner: frozenset[uuid.UUID], armer: frozenset[uuid.UUID], **over: Any) -> Gated:
    """A `Gated` whose owner (an Owner) and armer (a Manager) admit `owner` and `armer`."""
    gated = Gated(**over)
    gated.principals.facts.update(
        {OWNER: (True, "owner", True, owner), ARMER: (True, "manager", False, armer)}
    )
    return gated


async def test_an_account_less_action_checks_the_global_kill_switch() -> None:
    """24 §11.5 check 3: an action that names no account asks B18's global verdict, never its
    instance's account's. Engaged on A alone, a notification on A's instance runs and an order on
    A is blocked; engaged globally, both are."""
    on_a = Gated(Switches(engaged={A}))
    await on_a.run(action("a1", "send_notification", on_error="continue"), action("a2"))
    assert on_a.results() == [("a1", "ok", None), ("a2", "blocked", "kill_switch")]
    globally = Gated(Switches(engaged={None}))
    await globally.run(action("a1", "send_notification", on_error="continue"), action("a2"))
    assert globally.results() == [
        ("a1", "blocked", "kill_switch"),
        ("a2", "blocked", "kill_switch"),
    ]


async def test_a_live_scope_action_is_blocked_by_the_closed_live_gate() -> None:
    """Scenario: Live and cross-environment actions are blocked (failure case): on a live process
    with the rule live gate closed, a live-scoped action is blocked `live_gate` before the OMS."""
    gated = Gated()
    live = RuleScope.model_validate(
        {"level": "account", "account_ids": [str(A)], "environments": ["live"]}
    )
    await _scoped(gated, "live", live_gate=False)
    await gated.run(action("a1", scope=live, environment="live"))
    assert gated.results() == [("a1", "blocked", "live_gate")] and gated.sent == []
    assert gated.audited() == [("rules.blocked", "a1", "live_gate")]


async def test_an_account_of_another_environment_is_blocked() -> None:
    """Scenario: Live and cross-environment actions are blocked (failure case): the account's own
    environment, read with its grant, is not the process's: `environment`, before the OMS."""
    gated = Gated()
    scoped = await _scoped(gated, envs={A: "testnet", B: "demo", C: "demo"})
    await gated.run(action("a1"))
    assert gated.results() == [("a1", "blocked", "environment")] and gated.sent == []
    assert [data["reason"] for _, data in scoped.audits] == ["environment"]


@pytest.mark.parametrize(
    "reason",
    ["grant_revoked", "account_disabled", "manager_frozen", "symbol_not_allowed", "applies_to",
     "algo_child", "out_of_scope"],
)  # fmt: skip
async def test_any_other_scope_refusal_reads_scope(reason: str) -> None:
    """Only `live_gate` and `environment` keep their own `blocked_by` (C-2.11); every other reason
    the scope re-check gives is `scope`."""
    gated = Gated(denied={"a1": reason})
    await gated.run(action("a1"))
    assert gated.results() == [("a1", "blocked", "scope")]


async def test_scope_accounts_and_originating_account_resolve_to_the_instances_account() -> None:
    """24 §11.5 (BQ-4): a rule over A and B fires on A's instance; both readings act on A alone,
    once per trigger, never on every account of the scope."""
    both = RuleScope.model_validate({"level": "account", "account_ids": [str(A), str(B)]})
    gated = Gated()
    await gated.run(
        action("a1", scope=both, on_error="continue"),
        action("a2", scope=both, targets="originating_account"),
    )
    assert per_account(gated) == [("a1", str(A), "ok", None), ("a2", str(A), "ok", None)]
    assert gated.sent == [("a1", str(A)), ("a2", str(A))]
    resolved = [
        e.payload["resolved_accounts"] for _, e in gated.records.events if e.kind != "action_start"
    ]
    assert resolved == [[str(A)], [str(A)]]


async def test_each_resolved_account_gets_its_own_key_checks_and_result() -> None:
    """`all_accounts` resolving to A, B and C: each account runs the checks (check 1 included),
    with its own fire key and its own result, every result naming all three as resolved."""
    gated = Gated()
    await gated.run(action("a1", targets="all_accounts"))
    assert gated.checked == [("a1", str(A)), ("a1", str(B)), ("a1", str(C))]
    assert per_account(gated) == [("a1", str(a), "ok", None) for a in (A, B, C)]
    keys = [e.payload["dedupe_key"] for _, e in gated.records.events if e.kind != "action_start"]
    assert keys == [
        dedupe_key(rule_id=RULE, version=1, scope_instance=f"BTCUSDT@{A}", node_id="a1",
                   run_id=RUN, account_id=a)
        for a in (A, B, C)
    ]  # fmt: skip
    resolved = {
        tuple(e.payload["resolved_accounts"])
        for _, e in gated.records.events
        if e.kind != "action_start"
    }
    assert resolved == {(str(A), str(B), str(C))}


async def test_abort_on_first_skips_the_actions_remaining_accounts() -> None:
    """The first account whose result is neither `ok` nor `simulated` stops the action's other
    accounts, recorded `skipped`, whatever `on_error` says; the next action still runs under
    `continue`."""
    gated = Gated(refuse={B})
    await gated.run(action("a1", targets="all_accounts", on_error="continue"), action("a2"))
    assert per_account(gated) == [
        ("a1", str(A), "ok", None), ("a1", str(B), "failed", None),
        ("a1", str(C), "skipped", None), ("a2", str(A), "ok", None),
    ]  # fmt: skip
    assert gated.sent == [("a1", str(A)), ("a1", str(B)), ("a2", str(A))]


async def test_revoked_grant_blocks_action_at_runtime() -> None:
    """Scenario: Authority is the intersection of owner and armer (RE-E6). A grant revoked after
    arming blocks at runtime (RE-E1): the armer's, through the principal (`permission`); the
    owner's, through the scope re-check (`scope`)."""
    gated = _role(frozenset({A, B}), frozenset({A, B}))
    scoped = await _scoped(gated)
    await gated.run(action("a1"))
    gated.principals.facts[ARMER] = (True, "manager", False, frozenset({B}))
    await gated.run(action("a2"))
    gated.principals.facts[ARMER] = (True, "manager", False, frozenset({A, B}))
    scoped.source.grants.remove(A)
    await scoped.state.refresh(OWNER)
    await gated.run(action("a3"))
    assert gated.results() == [
        ("a1", "ok", None), ("a2", "blocked", "permission"), ("a3", "blocked", "scope"),
    ]  # fmt: skip
    assert gated.sent == [("a1", str(A))]


async def test_rule_authority_is_intersection_of_author_and_armer() -> None:
    """Scenario: Authority is the intersection of owner and armer (RE-E6): an Owner who arms a
    rule never lends it reach the rule's own owner lacks, nor the other way round."""
    gated = _role(frozenset({A, B}), frozenset({A, C}))
    on = {a: ScopeInstanceRef(f"BTCUSDT@{a}", "BTCUSDT", a) for a in (A, B, C)}
    reqs = [action(f"a{n}", instance=on[a], on_error="continue") for n, a in enumerate((A, B, C))]
    await gated.run(*reqs)
    assert per_account(gated) == [
        ("a0", str(A), "ok", None), ("a1", str(B), "blocked", "permission"),
        ("a2", str(C), "blocked", "permission"),
    ]  # fmt: skip
    assert gated.sent == [("a0", str(A))]


async def test_all_accounts_expands_to_current_grants_only() -> None:
    """Scenario: Authority is the intersection of owner and armer (RE-E6). `all_accounts` means
    the current intersection at fire time (RE-E3, AC-12): the armer holds A and B when arming; B
    is withdrawn and the owner gains C; the next fire acts on A alone."""
    gated = _role(frozenset({A, B}), frozenset({A, B}))
    await gated.run(action("a1", targets="all_accounts"))
    gated.principals.facts[OWNER] = (True, "owner", True, frozenset({A, B, C}))
    gated.principals.facts[ARMER] = (True, "manager", False, frozenset({A}))
    await gated.run(action("a2", targets="all_accounts"))
    assert per_account(gated) == [
        ("a1", str(A), "ok", None), ("a1", str(B), "ok", None), ("a2", str(A), "ok", None),
    ]  # fmt: skip


# fmt: off
async def test_all_accounts_resolves_to_the_owner_armer_intersection_and_needs_the_owner_role_at_execution() -> None:  # noqa: E501 -- the issue's test name (#5002)
    """Scenario: all_accounts resolves at fire time to the intersection and needs the Owner role
    at execution (BQ-3, C-12.4): owner and armer hold different grants; the action resolves to
    their intersection, and an owner who no longer holds the Owner role is blocked `permission`."""
    gated = _role(frozenset({A, B, C}), frozenset({B, C}))
    await gated.run(action("a1", targets="all_accounts"))
    gated.principals.facts[OWNER] = (True, "manager", False, frozenset({A, B, C}))
    await gated.run(action("a2", targets="all_accounts", on_error="continue"))
    assert per_account(gated) == [
        ("a1", str(B), "ok", None), ("a1", str(C), "ok", None),
        ("a2", str(B), "blocked", "permission"), ("a2", str(C), "skipped", None),
    ]  # fmt: skip
    assert gated.sent == [("a1", str(B)), ("a1", str(C))]
# fmt: on


@pytest.mark.parametrize("bound", [True, False], ids=["disjoint", "unbound"])
async def test_an_empty_all_accounts_resolution_is_blocked_as_permission(bound: bool) -> None:
    """24 §11.5 (BQ-4): an intersection that holds no account, or no principal read at all,
    records one `blocked` (`permission`) result with no account and no resolved accounts."""
    gated = _role(frozenset({A}), frozenset({B}))
    if not bound:
        gated.executor = ActionExecutor(
            check_one=gated.check_one, scope_check=gated.scope_check,
            gates=Gates(switches=gated.switches), records=gated.records, audit=gated.records,
            handlers=bound_table(gated.sent), clock=gated.clock,
        )  # fmt: skip
    await gated.run(action("a1", targets="all_accounts"))
    assert per_account(gated) == [("a1", None, "blocked", "permission")] and gated.sent == []
    (event,) = [e for _, e in gated.records.events if e.kind == "action_fail"]
    assert event.payload["resolved_accounts"] == []
    assert gated.audited() == [("rules.blocked", "a1", "permission")]


@pytest.mark.parametrize(
    ("user", "facts"),
    [
        (OWNER, (False, "owner", True, frozenset({A}))),  # the owner disabled
        (ARMER, (False, "manager", False, frozenset({A}))),  # the armer disabled
        (ARMER, (True, "viewer", False, frozenset())),  # the armer view-only: admits none
        (OWNER, (True, "manager", False, frozenset())),  # the owner's grant frozen: admits none
    ],
    ids=["owner-disabled", "armer-disabled", "armer-view-only", "owner-frozen"],
)
async def test_a_disabled_or_view_only_owner_or_armer_blocks_the_action(
    user: uuid.UUID, facts: tuple[bool, str | None, bool, frozenset[uuid.UUID]]
) -> None:
    """The forbidden-role case (C-12.4): a user who is disabled, or whose grant admits no trade on
    the account, blocks every action that reaches check 5, an account-less one too when the user
    is disabled."""
    gated = Gated()
    gated.principals.facts[user] = facts
    await gated.run(action("a1", on_error="continue"), action("a2", "send_notification"))
    notification = ("a2", "blocked", "permission") if not facts[0] else ("a2", "ok", None)
    assert gated.results() == [("a1", "blocked", "permission"), notification]
    assert ("a1", str(A)) not in gated.sent


async def test_an_action_never_reaches_an_account_outside_the_owner_armer_intersection() -> None:
    """The cross-account case (IDOR, C-12.4): of A, B and C, only B is admitted by both users;
    every action on A or C is blocked `permission`, by whichever reading reaches it."""
    gated = _role(frozenset({A, B}), frozenset({B, C}))
    on = {a: ScopeInstanceRef(f"BTCUSDT@{a}", "BTCUSDT", a) for a in (A, B, C)}
    reqs = [action(f"a{n}", instance=on[a], on_error="continue") for n, a in enumerate((A, B, C))]
    await gated.run(*reqs, action("a9", targets="all_accounts"))
    reached = {account for _, account in gated.sent}
    assert reached == {str(B)}
    refused = {
        (node, acct) for node, acct, outcome, _ in per_account(gated) if outcome == "blocked"
    }
    assert refused == {("a0", str(A)), ("a2", str(C))}


async def test_all_accounts_never_reaches_past_the_rules_scope() -> None:
    """Cross-account: `all_accounts` reaches past the scope's own accounts only for a rule whose
    scope names none; here the scope names A, so B is refused by the scope re-check (`scope`), and
    `abort_on_first` stops C."""
    gated = Gated()
    await _scoped(gated)
    await gated.run(action("a1", targets="all_accounts"))
    assert per_account(gated) == [
        ("a1", str(A), "ok", None), ("a1", str(B), "blocked", "scope"),
        ("a1", str(C), "skipped", None),
    ]  # fmt: skip
    assert gated.sent == [("a1", str(A))]


@pytest.mark.parametrize(
    ("missing", "age", "admitted"),
    [(None, PRINCIPAL_MAX_AGE_S, True), (None, PRINCIPAL_MAX_AGE_S + 0.5, False),
     (OWNER, 0.0, False), (ARMER, 0.0, False)],
    ids=["at-the-bound", "stale", "owner-unread", "armer-unread"],
)  # fmt: skip
async def test_a_stale_or_unread_principal_blocks_as_permission(
    missing: uuid.UUID | None, age: float, admitted: bool
) -> None:
    """24 §11.5: a snapshot older than one second, or not read at all, is a failed read: the
    action is blocked `permission`. The executor holds the bound: one second old still serves."""
    assert PRINCIPAL_MAX_AGE_S == 1.0
    gated = Gated()
    gated.principals.ages[ARMER] = age
    if missing is not None:
        gated.principals.missing.add(missing)
    await gated.run(action("a1"))
    assert gated.results() == [("a1", "ok", None) if admitted else ("a1", "blocked", "permission")]


@pytest.mark.parametrize("inactive", [OWNER, ARMER])
async def test_an_account_less_action_needs_both_users_active(inactive: uuid.UUID) -> None:
    """24 §11.5: an action that names no account is checked on no account, but both users must be
    active: an inactive owner or armer blocks a notification `permission`."""
    gated = Gated()
    await gated.run(action("a1", "send_notification"))
    gated.principals.facts[inactive] = (False, "owner", True, frozenset({A, B, C}))
    await gated.run(action("a2", "send_notification"))
    assert gated.results() == [("a1", "ok", None), ("a2", "blocked", "permission")]


async def test_records_carry_both_roles_from_the_principal_snapshot() -> None:
    """24 §15.5 (BQ-5): `rules.fired` and `rules.blocked` carry both users' roles as the snapshot
    the action was checked against gave them, `None` for an action refused before check 5 read
    it; no record names a user as its actor (the actor is the rule, 04 SR-062)."""
    gated = _role(frozenset({A}), frozenset({A}))
    await gated.run(action("a1", on_error="continue"), action("a2", "widen_stop"))
    gated.switches.engaged.add(None)
    await gated.run(action("a3"))
    roles = [(verb, f.node_id, f.owner_role, f.armed_by_role) for verb, f in gated.records.audits]
    assert roles == [
        ("rules.fired", "a1", "owner", "manager"), ("rules.blocked", "a2", "owner", "manager"),
        ("rules.blocked", "a3", None, None),
    ]  # fmt: skip
