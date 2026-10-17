"""#2097: the RBAC matrix cells of `GET /auth/_perf/argon2-params`, with the perf switch on.

The pack's shared world runs with `CV_AUTH_PERF_ENABLED` off, so the route's matrix row is
`not_mounted` there. This module builds the same real-app world on a keyless testnet with the
switch on and runs every cell of that row with a real bearer token per actor (SR-018): the owner
gets the parameters a fresh hash embeds, both managers and the viewer get 403, no session gets
401. Each refusal is a body the contract declares for its status, with its catalogued `code`.
Outcomes are read from `matrix.yaml`. Cross-account (IDOR) has no object: the scope is `none`
and the route takes no id, so a manager with an account grant is refused like one without.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from typing import Any

import pytest
import yaml
from argon2 import extract_parameters
from jsonschema import Draft202012Validator

from candleviewer.api._generated.openapi_models import Argon2Params
from candleviewer.auth.hashing import Hasher
from tests.contract.rbac.rbac_harness import (
    ACTORS,
    MATRIX_PATH,
    World,
    bearer,
    build_world,
    load_contract,
    record_cell,
)

_PATH = "/auth/_perf/argon2-params"
_OPERATION = f"GET {_PATH}"
_ERRORS = "https://candleviewer.local/errors/"  # `Problem.type` is this plus the `code`
_REFUSAL_CODES = {401: "unauthenticated", 403: "forbidden"}  # `x-error-codes` slugs it serves
_CONTRACT = load_contract()
_CATALOGUE = {e["code"]: e["status"] for e in _CONTRACT["x-error-codes"]}


def _outcomes() -> dict[str, str]:
    with MATRIX_PATH.open(encoding="utf-8") as fh:
        matrix: dict[str, Any] = yaml.safe_load(fh)
    outcomes: dict[str, str] = matrix["operations"][_OPERATION]["outcomes"]
    return outcomes


def _problem_errors(status: int, body: Any) -> list[str]:
    """Why *body* is not a problem the contract declares for a *status* response of this route."""
    declared = _CONTRACT["paths"][_PATH]["get"]["responses"][str(status)]["$ref"]
    ref = f"{declared}/content/application~1problem+json/schema"
    validator = Draft202012Validator({"$ref": ref, "components": _CONTRACT["components"]})
    return [e.message for e in validator.iter_errors(body)]


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
    resp = perf_world.client.get(_PATH, headers=bearer(actor))
    observed = {401: "401", 403: "403"}.get(resp.status_code, "allow")
    try:
        assert observed == _outcomes()[actor], f"{actor}: got {resp.status_code}"
        if observed == "allow":
            assert resp.status_code == 200
            body = Argon2Params.model_validate(resp.json()).model_dump()
            assert body == {"m": 65536, "t": 3, "p": 4}
            fresh = extract_parameters(asyncio.run(Hasher().hash("fresh")))
            assert body == {"m": fresh.memory_cost, "t": fresh.time_cost, "p": fresh.parallelism}
        else:
            body = resp.json()
            code = _REFUSAL_CODES[resp.status_code]
            expected = {"status": resp.status_code, "code": code, "type": f"{_ERRORS}{code}"}
            assert "m" not in body, "a refusal never reveals the parameters"
            assert resp.headers.get("content-type") == "application/problem+json"
            assert _problem_errors(resp.status_code, body) == []
            # `get`: a refusal missing a key is an assertion failure, which the except records.
            assert {key: body.get(key) for key in expected} == expected
            assert _CATALOGUE[code] == resp.status_code
    except AssertionError:
        # Recorded after the checks, as in test_route_matrix.py, so a red cell stays red (#294).
        record_cell("auth", _OPERATION, actor, "fail", started)
        raise
    record_cell("auth", _OPERATION, actor, "pass", started)
