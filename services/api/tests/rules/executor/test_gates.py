"""E35-T10 (#5002) slice 2e: the synchronous checks before each rule action (24 §11.5, §11.9).

`Gated` drives one `ActionExecutor` with every one of the 25 types bound to a handler double that
records what it would send, scripted check-1 verdicts, a routing emitter whose scope re-check a test
scripts per node, the switches of checks 2 and 3 (`Switches`, open unless a test closes one) and
the records in memory. The first refusal wins in the ruled order (BQ-1), and every refusal is
decided before the records written ahead, so it writes `rules.blocked` and never `rules.fired`.
No order path is reached: the doubles stand where E35-T11's handlers will (plan §4).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, get_args

import pytest

from candleviewer.flags_wiring import FeatureFlagsRuntime
from candleviewer.oms_wiring import InterimKillSwitch
from candleviewer.rules.executor.dispatch import Fire
from candleviewer.rules.executor.engine import ActionExecutor, RowVerdict
from candleviewer.rules.executor.gates import Gates
from candleviewer.rules.executor.handlers import (
    ENGINE_INTERNAL,
    HANDLERS,
    HandlerAnswer,
    HandlerSpec,
    Prepared,
    prepared,
)
from candleviewer.rules.ir.models import Action, ActionType, RuleScope
from candleviewer.rules.scope import ActionRequest, ScopeInstanceRef
from candleviewer.rules_oms_wiring import RuleSwitchesBinding
from tests.rules.executor.request_builders import Counted, Records, Switches, action_request
from tests.unit.admin.flag_fakes import FakeAudit, FakeStepUp, FakeUsers

RULE, RUN = str(uuid.UUID(int=7)), uuid.UUID(int=8)
OWNER, ARMER = uuid.UUID(int=0xA1), uuid.UUID(int=0xA2)
A, B, C = uuid.UUID(int=0xB1), uuid.UUID(int=0xB2), uuid.UUID(int=0xB3)
TYPES: tuple[str, ...] = get_args(ActionType)


class Double:
    """A bound handler: records what it would send, by node and account, and accepts it."""

    def __init__(self, sent: list[tuple[str, str]], answer: HandlerAnswer) -> None:
        self.sent, self.answer = sent, answer

    def prepare(self, req: ActionRequest, account_id: uuid.UUID | None, **_: Any) -> Prepared:
        return prepared({"node": req.payload.node_id, "account": str(account_id)})

    async def send(self, prep: Prepared, *, client_ref: str) -> HandlerAnswer:
        self.sent.append((str(prep.request["node"]), str(prep.request["account"])))
        return self.answer


def bound_table(
    sent: list[tuple[str, str]], answers: Mapping[str, HandlerAnswer] | None = None
) -> dict[str, HandlerSpec]:
    """Every type bound to a `Double`, accepting unless `answers` names another answer."""
    answers = answers or {}
    return {
        t: replace(spec, handler=Double(sent, answers.get(t, HandlerAnswer("accepted"))))
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
    executor: ActionExecutor = field(init=False)

    def __post_init__(self) -> None:
        self.executor = ActionExecutor(
            check_one=self.check_one, scope_check=self.scope_check, gates=self.gates(),
            records=self.records, audit=self.records, metrics=self.counted.metrics,
            handlers=bound_table(self.sent, self.answers),
        )  # fmt: skip

    def gates(self) -> Gates:
        return Gates(switches=self.switches)

    async def check_one(self, req: ActionRequest) -> RowVerdict:
        queue = self.verdicts.get(req.payload.node_id)
        return queue.pop(0) if queue else "armed"

    def scope_check(self, req: ActionRequest) -> str | None:
        return self.denied.get(req.payload.node_id)

    async def emit(self, req: ActionRequest) -> bool:
        """The routing emitter: the scope re-check (check 4), then the hand-over (`_route`)."""
        if req.payload.node_id in self.denied:
            return False
        await self.executor.hand_over(req)
        return True

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


_FIRST: dict[int, tuple[str, str | None]] = {
    1: ("skipped", "mode_changed"), 2: ("blocked", "rules_disabled"), 3: ("blocked", "kill_switch"),
    4: ("blocked", "scope"), 8: ("blocked", "native_sl"),
}  # fmt: skip


@pytest.mark.parametrize(
    ("k", "action_type"),
    [(1, "place_order"), (2, "place_order"), (3, "place_order"), (4, "place_order")]
    + [(k, "widen_stop") for k in (1, 2, 3, 4, 8)],
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
