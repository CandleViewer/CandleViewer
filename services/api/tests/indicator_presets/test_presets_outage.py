"""IR-24 / AC-18 for `/indicator-presets` (E13-T03, #427): a failing store through the real app
(`create_app()`, its middleware and error redaction) answers an RFC 9457 body that names no SQL,
no file path, no bound parameter and none of the submitted JSON: 503 `store_unavailable` for an
outage, a generic 500 for a bug. Also the app's own preset series and their startup read."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest
from _presets_env import ATR14, EMA9, FakePresetRepo
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError
from structlog.testing import capture_logs

from candleviewer.observability.metrics_catalogue import CATALOGUE
from tests.contract.rbac.rbac_harness import World, bearer, build_world

#: What a leak would look like: SQL, a file path or a frame, a bound parameter, the body sent.
_LEAKS = re.compile(
    r"SELECT|INSERT|UPDATE indicator|/home/|/var/|\.py|Traceback|secret-owner|ATR 14"
)


class _Failing:
    """Every repository call raises `error` (the AC-18 failing-repository fixture)."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def __getattr__(self, name: str) -> Any:
        async def fail(*_args: Any, **_kwargs: Any) -> Any:
            raise self._error

        return fail


@pytest.fixture(scope="module")
def world() -> Iterator[World]:
    mp = pytest.MonkeyPatch()
    try:
        yield build_world(mp)
    finally:
        mp.undo()


def _requests(client: TestClient) -> list[Any]:
    headers = bearer("manager_with_grant")
    return [
        client.get("/indicator-presets", headers=headers),
        client.post("/indicator-presets", json=ATR14, headers=headers),
        client.put(f"/indicator-presets/{EMA9}", json=ATR14, headers=headers),
        client.delete(f"/indicator-presets/{EMA9}", headers=headers),
    ]


_SQL = "SELECT id FROM indicator_presets WHERE owner_user_id = 'secret-owner'"


def test_a_store_outage_is_a_generic_503_on_every_operation(world: World) -> None:
    error = OperationalError(_SQL, {"owner": "secret-owner"}, ConnectionError("/var/run/pg.sock"))
    world.app.state.indicator_presets_repository = _Failing(error)
    for r in _requests(world.client):
        assert (r.status_code, r.headers["content-type"]) == (503, "application/problem+json")
        assert r.json()["code"] == "store_unavailable" and not _LEAKS.search(r.text), r.text


@pytest.mark.parametrize(
    "error",
    [RuntimeError(f"boom at /home/app/candleviewer/x.py: {_SQL}"),
     IntegrityError(_SQL, {"owner": "secret-owner"}, ValueError("indicator_presets_pkey"))],
)  # fmt: skip
def test_a_store_bug_is_a_generic_500_with_nothing_of_the_failure(
    world: World, error: Exception
) -> None:
    world.app.state.indicator_presets_repository = _Failing(error)
    with capture_logs():  # the console renderer would format each traceback for seconds
        responses = _requests(world.client)  # the world's client never raises server errors
    for r in responses:
        assert r.status_code == 500 and not _LEAKS.search(r.text), r.text


def test_the_app_registers_the_two_preset_series_with_their_catalogue_bounds(world: World) -> None:
    """The router's series are the catalogue's: re-declaring a series exactly as the catalogue
    does returns the app's own (any other kind, label or bound would raise `MetricsError`)."""
    wired, facade = world.app.state.indicator_presets_metrics, world.app.state.metrics_facade
    specs = [s for s in CATALOGUE if s.name.startswith("indicator_preset")]
    assert len(specs) == 2
    for spec in specs:
        register = facade.gauge if spec.kind == "gauge" else facade.counter
        same = register(spec.name, spec.help, spec.labels, max_series=spec.max_series)
        assert same is (wired.presets if spec.kind == "gauge" else wired.denied)


async def test_the_app_reads_the_preset_gauge_from_its_own_store_at_startup(world: World) -> None:
    """`create_app()` leaves the primer on `app.state` for the lifespan to start (the composition
    guard checks that it does); it reads the app's store into the app's gauge."""
    world.app.state.indicator_presets_repository = FakePresetRepo()
    await world.app.state.indicator_presets_gauge.prime()
    facade = world.app.state.metrics_facade
    got = {
        builtin: facade.registry.get_sample_value(
            "indicator_presets_total", {"env": facade.env, "builtin": builtin}
        )
        for builtin in ("true", "false")
    }
    assert got == {"true": 18.0, "false": 0.0}
