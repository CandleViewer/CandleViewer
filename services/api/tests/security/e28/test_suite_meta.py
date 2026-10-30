"""E28-X03 (#976): the suite checks itself, so a new route, a new actor or a lost guard fails it.

- The cells are generated (never empty, ids unique) and cover every executed E28 row of
  `matrix.yaml` for every actor, and those rows are exactly the E28 operations the app serves: a
  route on an E28 path with no cell fails here, naming it (shown with a probe mounted in memory).
- The rows `not_mounted` today are not served, so mounting `createTradeGroup`, its amend or its
  cancel (E34-S02/S03), or SR-E28-28's lockout override and kill-switch release, fails until each
  gets its cells. The `account_scope` rows delegated to this ticket are all cells here.
- Every mounted write has a forbidden-role cell and a cross-account (IDOR) cell.
- The `trade_groups` topic row names every actor, and `test_ws_scope.py` runs each.
- The live guard refuses every live target it names, without echoing a value, admits this run's
  environment, and is a fixture of every test of the suite.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import APIRouter

from candleviewer.api.deny_by_default import served_operations
from tests.contract.rbac.rbac_harness import ACTORS
from tests.security.e28 import _cells as cells
from tests.security.e28._world import E28World
from tests.security.e28.conftest import live_target_refusal, target_env

_HERE = os.path.dirname(__file__)
#: Declared, not served: each owes its cells the day its ticket mounts it.
_UNMOUNTED = {
    "POST /trade-groups": "E34-S02 #1110",
    "POST /trade-groups/{tradeGroupId}/amend": "E34-S03 #1111",
    "POST /trade-groups/{tradeGroupId}/cancel": "E34-S03 #1111",
    "POST /risk/lockouts/{accountId}/override": "SR-E28-28, E39",
    "POST /trading/kill-switch": "SR-E28-28, E39",
}
_PROBE = "GET /trade-groups/{tradeGroupId}/probe"


def _served(world: E28World) -> set[str]:
    return {f"{m} {p}" for m, p in served_operations(world.app)}


def _uncovered(world: E28World) -> list[str]:
    covered = {cell.key for cell in cells.cells()}
    e28 = {k for k in _served(world) if cells.E28_PATHS.match(k.split(" ", 1)[1])}
    return sorted(e28 - covered)


def test_the_cells_are_generated_and_cover_every_actor_and_situation() -> None:
    made = cells.cells()
    assert len(made) > 100 and len({c.id for c in made}) == len(made)
    for key in cells.rows("executed"):
        got = {(c.actor, c.at) for c in made if c.key == key}
        assert got == {(a, s) for a in ACTORS for s in cells.situations(key)}, key


def test_every_served_e28_route_has_cells_and_no_cell_is_for_a_route_not_served(
    world: E28World,
) -> None:
    assert not _uncovered(world), f"E28 routes served with no cell: {_uncovered(world)}"
    stale = {c.key for c in cells.cells()} - _served(world)
    assert not stale, f"cells for routes not served: {sorted(stale)}"


def test_the_unmounted_rows_are_not_served_and_owe_their_cells(world: E28World) -> None:
    declared = cells.matrix()["operations"]
    assert set(cells.rows("not_mounted")) <= set(_UNMOUNTED)
    assert all(declared[k]["state"] == "not_mounted" for k in _UNMOUNTED)
    mounted = sorted(set(_UNMOUNTED) & _served(world))
    assert not mounted, f"now served: give these cells and an executed row: {mounted}"


def test_the_account_scope_rows_delegated_here_are_all_cells() -> None:
    delegated = {
        k for k, row in cells.matrix()["account_scope"].items()
        if row == {"delegated": cells.DELEGATED}
    }  # fmt: skip
    assert delegated and delegated <= {c.key for c in cells.cells()}


def test_every_mounted_write_has_its_forbidden_role_and_cross_account_cells() -> None:
    made = cells.cells()
    for key in [k for k in cells.rows("executed") if not k.startswith("GET ")]:
        mine = [c for c in made if c.key == key]
        assert any(c.actor == "viewer" and c.expect.startswith("403") for c in mine), key
        idor = [c for c in mine if c.actor == "manager_with_grant" and c.at in ("foreign", "mixed")]
        assert idor and all(c.denied for c in idor), key
        if any(not c.denied for c in mine if c.actor == "manager_with_grant"):
            # the role may write here, so its foreign cell is a scope refusal, not a role one
            scoped = ("404 not_found", "403 account_scope_denied")
            assert any(c.expect in scoped for c in idor), key


def test_the_ws_topic_row_names_every_actor() -> None:
    assert set(cells.ws_outcomes()) == set(ACTORS)


@pytest.fixture
def probe(world: E28World) -> Iterator[str]:
    """`_PROBE` mounted as a ticket might, with no cell; the routes restored by identity."""
    routes = list(world.app.router.routes)
    router = APIRouter()

    @router.get("/trade-groups/{tradeGroupId}/probe")
    async def leaked() -> dict[str, str]:
        return {"state": "leaked"}

    world.app.include_router(router)
    try:
        yield _PROBE
    finally:
        world.app.router.routes[:] = routes
    assert _PROBE not in _served(world)


def test_an_e28_route_mounted_without_cells_fails_the_coverage(world: E28World, probe: str) -> None:
    assert _uncovered(world) == [probe]


_LIVE = [
    {"CV_ENVIRONMENT": "live"}, {"CV_FEED": "LIVE"}, {"CV_TRADING_LIVE_ENABLED": "true"},
    {"CV_BYBIT_API_KEY": "synthetic-not-a-key"}, {"cv_bybit_api_secret": ""},
    {"CV_CI_ALLOWED_HOSTS": "postgres,api.bybit.com"},
    {"CV_BYBIT_ARCHIVE_BASE": "https://public.bybit.com"}, {"CV_VENUE_HOSTS": "stream.bytick.com"},
]  # fmt: skip


@pytest.mark.parametrize("env", _LIVE, ids=[next(iter(e)) for e in _LIVE])
def test_the_guard_refuses_a_live_target_and_names_no_value(env: dict[str, str]) -> None:
    why = live_target_refusal({"CV_ENVIRONMENT": "demo", **env})
    assert why is not None
    assert not [v for v in env.values() if v and v.lower() not in ("live", "true") and v in why]


def test_the_guard_admits_a_demo_target_and_this_run() -> None:
    demo = {"CV_ENVIRONMENT": "demo", "CV_CI_ALLOWED_HOSTS": "postgres,questdb",
            "CV_PG_DSN": "postgresql://cv@localhost/test"}  # fmt: skip
    assert live_target_refusal(demo) is None
    assert live_target_refusal(target_env()) is None  # this run, its `.env` included


def test_every_test_of_the_suite_runs_behind_the_guard(request: pytest.FixtureRequest) -> None:
    mine = [i for i in request.session.items if str(getattr(i, "path", "")).startswith(_HERE)]
    assert mine, "no item of the suite collected"
    unguarded = [i.nodeid for i in mine if "_live_guard" not in getattr(i, "fixturenames", ())]
    assert not unguarded, unguarded


def test_the_guard_reads_a_dotenv_the_app_would_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fable at 089f4cf4: `Settings` reads `.env` at the working directory, so the guard does."""
    (tmp_path / ".env").write_text("CV_ENVIRONMENT=live\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CV_ENVIRONMENT", raising=False)
    assert live_target_refusal(target_env()) == "CV_ENVIRONMENT targets live"
