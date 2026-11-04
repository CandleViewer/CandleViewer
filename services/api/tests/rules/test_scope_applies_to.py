"""#5817: a rule scoped by `applies_to` is evaluated by the tick's scope gate (24 §11.5, E35-S04).

`applies_to` (`any`, `account`, `open_positions`, `pending_orders`) is an authorable scope value.
The tick's gate runs before the rule has an action, for one scope instance of the rule: a rule
scoped to open positions or pending orders passes it as a rule on any other value does, and is
neither refused nor counted while its scope holds. The gate judges the entity its instance stands
for (`instance_entity`); a check that knows the entity an action touches judges that one, and a
genuine mismatch is refused `applies_to` and counted.
"""

from __future__ import annotations

from collections import Counter
from typing import Final
from uuid import UUID

import pytest
from hypothesis import given, seed
from hypothesis import strategies as st

from candleviewer.rules.evaluator.engine import scope_instance
from candleviewer.rules.ir.models import RuleScope
from candleviewer.rules.scope import (
    AccountState,
    EntityKind,
    ScopeInstanceRef,
    ScopeResolver,
    fire_scoped,
    instance_entity,
    make_scope_gate,
)
from tests.rules.test_scope import OWNER, A, B, C, FakeState, _noop, scope

APPLIES_TO = ("any", "account", "open_positions", "pending_orders")
ENTITIES: Final[tuple[EntityKind, ...]] = ("open_position", "pending_order", "account")
#: The entities an action of a rule on each `applies_to` may touch (E35-S04's design note: an
#: `open_positions` rule must not cancel a pending order); any other is a genuine mismatch.
ALLOWED: Final[dict[str, frozenset[str]]] = {
    "any": frozenset(ENTITIES),
    "account": frozenset(ENTITIES),
    "open_positions": frozenset({"open_position"}),
    "pending_orders": frozenset({"pending_order"}),
}
SYMBOLS = ("BTCUSDT", "ETHUSDT")
ACCOUNTS = (A, B, C)


def _ref(key: str) -> ScopeInstanceRef:
    """The instance a key names, a ``*`` part as None (the test's own reading of the key)."""
    sym, _, acct = key.partition("@")
    return ScopeInstanceRef(key, None if sym == "*" else sym, None if acct == "*" else UUID(acct))


IN_SCOPE = _ref(scope_instance("BTCUSDT", str(A)))


@pytest.mark.parametrize("applies_to", APPLIES_TO)
def test_gate_rule_instance_in_scope_passes_for_every_applies_to(applies_to: str) -> None:
    """The gate answers `None` for an instance in scope, whatever the rule's `applies_to`."""
    resolver = ScopeResolver(FakeState(), _noop)
    gate = make_scope_gate(
        resolver, scope(account_ids=[str(A)], applies_to=applies_to), OWNER, "demo"
    )
    assert gate(scope_instance("BTCUSDT", str(A))) is None
    assert resolver.suppressions_total == Counter()  # nothing refused, nothing counted


@pytest.mark.parametrize(
    ("applies_to", "entity"),
    [
        ("open_positions", "open_position"),
        ("pending_orders", "pending_order"),
        ("account", "account"),
        ("any", "account"),
    ],
)
def test_instance_entity_is_the_entity_its_applies_to_names(applies_to: str, entity: str) -> None:
    assert instance_entity(scope(applies_to=applies_to)) == entity


@pytest.mark.parametrize("entity", ENTITIES)
@pytest.mark.parametrize("applies_to", APPLIES_TO)
def test_check_action_known_entity_is_refused_only_outside_applies_to(
    applies_to: str, entity: EntityKind
) -> None:
    """A genuine mismatch: the entity an action touches lies outside the rule's `applies_to`."""
    resolver = ScopeResolver(FakeState(), _noop)
    sc = scope(account_ids=[str(A)], applies_to=applies_to)
    mismatch = entity not in ALLOWED[applies_to]
    answer = resolver.check_action(sc, OWNER, "demo", IN_SCOPE, entity)
    assert answer == ("applies_to" if mismatch else None)
    assert resolver.suppressions_total == Counter({"applies_to": 1} if mismatch else {})


async def test_fire_scoped_refuses_a_known_entity_outside_applies_to_and_sends_nothing() -> None:
    """The dispatch re-check that knows the action's entity keeps the refusal: an
    `open_positions` rule's action on a pending order is skipped `scope` and never dispatched."""
    resolver = ScopeResolver(FakeState(), _noop)
    sc = scope(account_ids=[str(A)], applies_to="open_positions")
    sent: list[str] = []

    async def dispatch(i: ScopeInstanceRef) -> None:
        sent.append(i.key)

    out = await fire_scoped(resolver, sc, OWNER, "demo", IN_SCOPE, dispatch, entity="pending_order")
    assert (out.fired, out.suppressed, out.skipped_reason) == (False, "applies_to", "scope")
    assert sent == [] and resolver.suppressions_total == Counter({"applies_to": 1})
    for entity in ("open_position", None):  # the action's own entity, or the instance's
        assert (
            await fire_scoped(resolver, sc, OWNER, "demo", IN_SCOPE, dispatch, entity=entity)
        ).fired
    assert sent == [IN_SCOPE.key, IN_SCOPE.key]
    assert resolver.suppressions_total == Counter({"applies_to": 1})  # the passes count nothing


@st.composite
def _cases(draw: st.DrawFn) -> tuple[RuleScope, FakeState, str, str]:
    """A scope, the owner's state, an instance key and the process environment, each drawn over
    every field the resolver reads (an absent account, a `*` part and `live` included)."""
    sc = RuleScope.model_validate(
        {
            "level": "account",
            "account_ids": [
                str(a) for a in draw(st.lists(st.sampled_from(ACCOUNTS), unique=True, max_size=2))
            ],
            "symbols": draw(st.lists(st.sampled_from(SYMBOLS), unique=True, max_size=2)),
            "applies_to": draw(st.sampled_from(APPLIES_TO)),
            "environments": draw(st.sampled_from((["demo"], ["live"], ["demo", "live"]))),
            "exclude_algo_children": draw(st.booleans()),
        }
    )
    state = FakeState()
    state.grants = {OWNER: set(draw(st.lists(st.sampled_from(ACCOUNTS), unique=True)))}
    state.accounts = {
        a: AccountState(
            draw(st.sampled_from(("demo", "live"))),
            enabled=draw(st.booleans()),
            frozen=draw(st.booleans()),
            allowed_symbols=draw(st.none() | st.frozensets(st.sampled_from(SYMBOLS))),
        )
        for a in draw(st.lists(st.sampled_from(ACCOUNTS), unique=True))
    }
    state.frozen = {OWNER} if draw(st.booleans()) else set()
    state.live_open, state.arm_live = draw(st.booleans()), draw(st.booleans())
    symbol = draw(st.sampled_from((*SYMBOLS, None)))
    account = draw(st.sampled_from((*(str(a) for a in ACCOUNTS), None)))
    return sc, state, scope_instance(symbol, account), draw(st.sampled_from(("demo", "live")))


@seed(5817)
@given(case=_cases())
def test_gate_answers_as_check_action_for_the_entity_its_instance_stands_for(
    case: tuple[RuleScope, FakeState, str, str],
) -> None:
    """Property: the tick's gate answers, and counts, as `check_action` does for the entity the
    instance stands for, so it never refuses an instance for its own `applies_to`; a known
    entity changes that answer only by an `applies_to` refusal, where it lies outside."""
    sc, state, key, environment = case
    gated, checked = ScopeResolver(state, _noop), ScopeResolver(state, _noop)
    answer = make_scope_gate(gated, sc, OWNER, environment)(key)
    assert answer == checked.check_action(sc, OWNER, environment, _ref(key), instance_entity(sc))
    assert answer != "applies_to"
    assert gated.suppressions_total == checked.suppressions_total
    for entity in ENTITIES:
        known = ScopeResolver(state, _noop).check_action(sc, OWNER, environment, _ref(key), entity)
        mismatch = answer is None and entity not in ALLOWED[sc.applies_to]
        assert known == ("applies_to" if mismatch else answer)
