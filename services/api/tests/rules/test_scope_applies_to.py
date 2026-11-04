"""#5817: a rule scoped by `applies_to` is evaluated by the tick's scope gate (24 §11.5, E35-S04).

`applies_to` (`any`, `account`, `open_positions`, `pending_orders`) is an authorable scope value.
The tick's gate runs before the rule has an action, for one scope instance of the rule: a rule
scoped to open positions or pending orders passes it as a rule on any other value does, and is
neither refused nor counted while its scope holds.
"""

from __future__ import annotations

from collections import Counter

import pytest

from candleviewer.rules.evaluator.engine import scope_instance
from candleviewer.rules.scope import ScopeResolver, make_scope_gate
from tests.rules.test_scope import OWNER, A, FakeState, _noop, scope

APPLIES_TO = ("any", "account", "open_positions", "pending_orders")


@pytest.mark.parametrize("applies_to", APPLIES_TO)
def test_gate_rule_instance_in_scope_passes_for_every_applies_to(applies_to: str) -> None:
    """The gate answers `None` for an instance in scope, whatever the rule's `applies_to`."""
    resolver = ScopeResolver(FakeState(), _noop)
    gate = make_scope_gate(
        resolver, scope(account_ids=[str(A)], applies_to=applies_to), OWNER, "demo"
    )
    assert gate(scope_instance("BTCUSDT", str(A))) is None
    assert resolver.suppressions_total == Counter()  # nothing refused, nothing counted
