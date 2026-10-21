"""#3085 S2b: the fake half of the store parity test. The table in `view_as_store_scenarios.py` is
played here against `FakeSessionRepository` and in
`tests/integration/storage/test_sessions_view_as_store_pg.py` against Postgres; both must give
exactly the outcomes it states, so the fake the view-as service tests rely on cannot drift."""

from __future__ import annotations

import pytest

from candleviewer.auth.view_as import ViewAsSessionStore

from .session_fakes import FakeSessionRepository
from .view_as_store_scenarios import SCENARIOS, Scenario, Stamp, expected, play


def _stamp(repo: FakeSessionRepository) -> Stamp:
    """A row's `revoked_reason` alone, written raw: no store method leaves one with no time."""

    async def stamp(session_id: str, reason: str) -> None:
        repo.sessions[session_id] = repo.sessions[session_id].model_copy(
            update={"revoked_reason": reason}
        )

    return stamp


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
async def test_the_fake_store_gives_each_outcome_the_table_states(scenario: Scenario) -> None:
    repo = FakeSessionRepository()
    assert await play(repo, scenario, _stamp(repo)) == expected(scenario)


def test_the_table_calls_every_store_method_both_applying_and_refused() -> None:
    """A store method the table never calls could drift between the fake and Postgres unseen."""
    methods = {name for name in vars(ViewAsSessionStore) if not name.startswith("_")}
    writes = {name for name in methods if not name.startswith("list_")}
    calls = [(c.method, o) for s in SCENARIOS for c, o in zip(s.calls, s.expect, strict=True)]
    assert {method for method, _ in calls} == methods
    assert {method for method, outcome in calls if outcome is None} == writes
    assert {method for method, outcome in calls if isinstance(outcome, tuple)} == methods
