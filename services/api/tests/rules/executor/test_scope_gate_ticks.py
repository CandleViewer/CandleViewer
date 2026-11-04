"""#5817: a rule scoped by `applies_to` fires and acts on the evaluation tick (24 §11.5, E35-S04).

K1b's dispatch rig (`test_dispatch.start`): one tick evaluates the rule on its instance, its fire is
dispatched off the tick and its action reaches the simulation sink (a `simulate` rule) or the
executor's downstream (an `armed` one). A rule scoped to open positions or pending orders does so
as a rule on `any` or `account` does: no scope refusal is recorded or counted for it.
"""

from __future__ import annotations

import pytest

from candleviewer.rules.manager import RuleRow
from tests.rules.executor.test_dispatch import DispatchRig, rig, start
from tests.rules.test_scope_applies_to import APPLIES_TO
from tests.rules.test_scope_wiring import A

__all__ = ["rig", "start"]  # the fixtures, imported


def _applying(row: RuleRow, applies_to: str) -> None:
    """The stored rule's scope narrowed to `applies_to` (the rig's rules are on `any`)."""
    row.versions[0].ir["scope"]["applies_to"] = applies_to


@pytest.mark.parametrize("mode", ["simulate", "armed"])
@pytest.mark.parametrize("applies_to", APPLIES_TO)
async def test_tick_rule_on_each_applies_to_fires_and_its_action_runs(
    rig: DispatchRig, applies_to: str, mode: str
) -> None:
    rid = await rig.add(mode)
    _applying(await rig.row(rid), applies_to)
    await rig.fire()
    await rig.settle()
    reached = rig.simulated if mode == "simulate" else rig.sink.entered
    assert [(r.rule_id, r.instance.account_id) for r in reached] == [(rid, A)]
    assert rig.audits == []  # no scope denial recorded
    assert rig.counted.blocked() == {}  # and none counted
