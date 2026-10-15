"""#2097: the RBAC matrix cells of `GET /auth/_perf/argon2-params`, with the perf switch on.

The pack's shared world runs with `CV_AUTH_PERF_ENABLED` off, so the route's matrix row is
`not_mounted` there. This module builds the same real-app world on a testnet with no exchange
key and the switch on, and runs every cell of that row with a real bearer token per actor
(SR-018): the owner gets the parameters, both managers and the viewer get 403, no session gets
401. The expected outcomes are read from `matrix.yaml`, never restated here. Cross-account
(IDOR) has no object here: the scope is `none` and the route takes no id, so the manager who
holds an account grant is refused exactly like the one who does not.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import pytest
import yaml

from candleviewer.api._generated.openapi_models import Argon2Params
from tests.contract.rbac.rbac_harness import (
    ACTORS,
    MATRIX_PATH,
    World,
    bearer,
    build_world,
    record_cell,
)

_KEY = "GET /auth/_perf/argon2-params"


def _outcomes() -> dict[str, str]:
    with MATRIX_PATH.open(encoding="utf-8") as fh:
        matrix: dict[str, Any] = yaml.safe_load(fh)
    outcomes: dict[str, str] = matrix["operations"][_KEY]["outcomes"]
    return outcomes


@pytest.fixture(scope="module")
def perf_world() -> Iterator[World]:
    """Same teardown discipline as the pack's `_world_module`: every patch and env change is
    undone at module teardown (`test_zz_patches_do_not_leak.py` checks the patches)."""
    mp = pytest.MonkeyPatch()
    try:
        mp.setenv("CV_ENVIRONMENT", "testnet")
        mp.setenv("CV_AUTH_PERF_ENABLED", "true")
        mp.delenv("CV_BYBIT_API_KEY", raising=False)
        mp.delenv("CV_BYBIT_API_SECRET", raising=False)
        yield build_world(mp)
    finally:
        mp.undo()


@pytest.mark.parametrize("actor", ACTORS)
def test_perf_params_cell_matches_the_matrix_with_the_switch_on(
    perf_world: World, actor: str
) -> None:
    started = time.perf_counter()
    resp = perf_world.client.get(_KEY.split(" ", 1)[1], headers=bearer(actor))
    observed = {401: "401", 403: "403"}.get(resp.status_code, "allow")
    try:
        assert observed == _outcomes()[actor], f"{actor}: got {resp.status_code}"
        if observed == "allow":
            assert resp.status_code == 200
            body = Argon2Params.model_validate(resp.json())
            assert body.model_dump() == {"m": 65536, "t": 3, "p": 4}
        else:
            assert "m" not in resp.json(), "a refusal never reveals the parameters"
    except AssertionError:
        # Recorded after the checks, as in test_route_matrix.py, so a red cell stays red (#294).
        record_cell("auth", _KEY, actor, "fail", started)
        raise
    record_cell("auth", _KEY, actor, "pass", started)
