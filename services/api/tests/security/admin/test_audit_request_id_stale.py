"""#3990 (independent QA, issuecomment-6319173131): a route the step-up gate refuses writes B16's
`auth.step_up_required` challenge, and it carries the id `CorrelationMiddleware` bound for the
refused request, as every other record of the request does.

The real `create_app()` of the E42-X03 world (`_world.py`), the elevation state `stale`: every
grace window and one-shot grant has lapsed, so each gated route answers with a challenge. The
cell's requests are stamped as in `test_audit_request_id.py` (the `sent` fixture); the step-up
exchange's own records (`POST /auth/step-up`, sent unstamped) are not the route's.
"""

from __future__ import annotations

import pytest

from tests.security.admin import _cells as cells
from tests.security.admin._world import SIGNED_IN, AdminWorld

STATE = "stale"
#: The cells a step-up challenge answers in this state (`_cells.expect`).
CELLS = [
    (op, actor)
    for op in cells.ops_for(STATE)
    for actor in SIGNED_IN
    if cells.expect(op, actor, STATE).kind == "challenge"
]


@pytest.mark.parametrize(
    ("op", "actor"), [pytest.param(op, a, id=f"{op.key}|{a}") for op, a in CELLS]
)
def test_a_step_up_challenge_carries_the_id_the_middleware_bound(
    world: AdminWorld, sent: list[str], op: cells.Op, actor: str
) -> None:
    start = len(sent)
    seen = cells.observe(world, op, actor, STATE)
    stamped = set(sent[start:])
    challenges = [r for r in seen.records if r["action"] == "auth.step_up_required"]
    assert challenges, f"{op.key} as {actor}: {[r['action'] for r in seen.records]}"
    unnamed = [
        f"{r['action']}: {r.get('request_id')}"
        for r in cells.route_records(seen.records)
        if str(r.get("request_id")) not in stamped
    ]
    assert unnamed == []


def test_the_sweep_challenges_a_handler_gate_and_a_path_gate() -> None:
    """The QA's route `POST /admin/keys/kek-rewrap`, which the read-only/step-up guard gates by
    path (as it gates `PUT /recording/retention-policies`, the QA's other route, which this world
    does not mount), and a route its handler gates (`POST /admin/recorder/purge`) are among the
    challenged cells, so the sweep cannot pass vacuously. Both refusals reach
    `StepUpService.record_pending`, which carries the id (`tests/unit/auth/test_step_up_b16.py`)."""
    keys = {op.key for op, _ in CELLS}
    assert {"POST /admin/keys/kek-rewrap", "POST /admin/recorder/purge"} <= keys
    gates = {gate.where for op, _ in CELLS if (gate := cells.gate_of(op.key)) is not None}
    assert {"path", "handler"} <= gates
