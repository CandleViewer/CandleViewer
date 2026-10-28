"""`/scanner/presets*` through the real app (E08-T09 PR 2a, #4708): `create_app()` mounts the
router, the fake backend wires no store (503 `store_unavailable`), and a failing store answers an
RFC 9457 body that names no SQL, no file path, no bound parameter and none of the submitted JSON:
503 for an outage, a generic 500 for a bug."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest
from _scanner_env import MISSING, MOMENTUM, FakeScannerRepo
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from structlog.testing import capture_logs

from tests.contract.rbac.rbac_harness import World, bearer, build_world

_LEAKS = re.compile(r"SELECT|INSERT|scanner_presets|/home/|/var/|\.py|Traceback|secret|Momentum")
_SQL = "SELECT id FROM scanner_presets WHERE user_id = 'secret-owner'"


class _Failing:
    """Every repository call raises `error`."""

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
        client.get("/scanner/presets", headers=headers),
        client.post("/scanner/presets", json=MOMENTUM, headers=headers),
        client.put(f"/scanner/presets/{MISSING}", json=MOMENTUM, headers=headers),
        client.delete(f"/scanner/presets/{MISSING}", headers=headers),
    ]


def test_the_fake_backend_wires_no_store_so_every_preset_operation_is_503(world: World) -> None:
    world.app.state.scanner_presets_repository = None
    for r in _requests(world.client):
        assert (r.status_code, r.json()["code"]) == (503, "store_unavailable")
    criteria = world.client.get("/scanner/criteria", headers=bearer("viewer"))
    assert criteria.status_code == 200 and len(criteria.json()["items"]) == 8


def test_a_store_outage_is_a_generic_503_on_every_operation(world: World) -> None:
    error = OperationalError(_SQL, {"owner": "secret-owner"}, ConnectionError("/var/run/pg.sock"))
    world.app.state.scanner_presets_repository = _Failing(error)
    with capture_logs() as logs:
        responses = _requests(world.client)
    for r in responses:
        assert (r.status_code, r.headers["content-type"]) == (503, "application/problem+json")
        assert r.json()["code"] == "store_unavailable" and not _LEAKS.search(r.text), r.text
        assert r.headers["retry-after"] == "5"
    assert any(e["event"] == "scanner_presets_store_unavailable" for e in logs)


def test_a_store_bug_is_a_generic_500_with_nothing_of_the_failure(world: World) -> None:
    world.app.state.scanner_presets_repository = _Failing(RuntimeError(f"boom /home/x.py {_SQL}"))
    with capture_logs():
        responses = _requests(world.client)
    for r in responses:
        assert r.status_code == 500 and not _LEAKS.search(r.text), r.text


def test_the_app_serves_a_create_and_its_list_over_a_wired_store(world: World) -> None:
    world.app.state.scanner_presets_repository = FakeScannerRepo()
    made = world.client.post("/scanner/presets", json=MOMENTUM,
                             headers=bearer("manager_with_grant"))  # fmt: skip
    assert made.status_code == 201, made.text
    listed = world.client.get("/scanner/presets", headers=bearer("manager_with_grant"))
    assert [i["id"] for i in listed.json()["items"]] == [made.json()["id"]]
    assert world.client.get("/scanner/presets", headers=bearer("owner")).json()["items"] == []
