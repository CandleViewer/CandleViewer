"""E42-X03 (#1026) admin RBAC cells, elevation state `stale`.

Cells for sessions whose every step-up has lapsed: grace windows and one-shot grants.
The expectations and the pinned gaps are documented in `_cells.py`.
"""

from __future__ import annotations

import pytest

from tests.security.admin import _cells as cells
from tests.security.admin._world import AdminWorld

STATE = "stale"


@pytest.mark.parametrize(("op", "actor"), cells.status_params(STATE))
def test_route_answers_each_actor_as_the_matrix_and_gate_say(
    world: AdminWorld, op: cells.Op, actor: str
) -> None:
    cells.assert_status(world, op, actor, STATE)


@pytest.mark.parametrize(("op", "actor"), cells.code_params(STATE))
def test_denial_carries_the_registry_code(world: AdminWorld, op: cells.Op, actor: str) -> None:
    cells.assert_code(world, op, actor, STATE)


@pytest.mark.parametrize(("op", "actor"), cells.record_params(STATE))
def test_answer_writes_the_audit_record_its_guard_owes(
    world: AdminWorld, op: cells.Op, actor: str
) -> None:
    cells.assert_records(world, op, actor, STATE)


@pytest.mark.parametrize(("op", "actor"), cells.counted_params(STATE))
def test_denial_is_counted(world: AdminWorld, op: cells.Op, actor: str) -> None:
    cells.assert_counted(world, op, actor, STATE)
