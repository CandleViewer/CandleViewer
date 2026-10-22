"""#2748 (b): an alert write the database refuses is answered by what refused it.

Only the name key's unique violation is a name clash (409, `AlertNameTakenError`). A value the
stored alert's own rules refuse, a CHECK (23514) or a NOT NULL (23502), is `422
validation_failed`, naming no constraint. Any other constraint error is a defect and stays a 500.
The store is a fake; the contract is read from `docs/plan/22-api-openapi.yaml`.
"""

from __future__ import annotations

from typing import Any

import pytest
from _alert_api_env import PRICE_CROSS, Env
from fastapi.testclient import TestClient

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.error_redaction import install_error_redaction
from candleviewer.storage.errors import StorageConstraintViolated


@pytest.fixture
def env() -> Env:
    return Env()


def _write(env: Env, write: str, refusal: Exception) -> Any:
    """Create, or replace an alert created first, with the store refusing the write."""
    if write == "create":
        env.repo.refusal = refusal
        return env.c.post("/alerts", json=PRICE_CROSS | {"name": "refused"})
    alert = env.create(name="kept")
    env.repo.refusal = refusal
    return env.c.put(f"/alerts/{alert['id']}", json=PRICE_CROSS | {"name": "kept"})


@pytest.mark.parametrize(("state", "constraint"), [("23514", "al_cooldown"), ("23502", None)])
@pytest.mark.parametrize("write", ["create", "update"])
def test_a_value_a_stored_alert_rule_refuses_is_422_naming_no_constraint(
    env: Env, write: str, state: str, constraint: str | None
) -> None:
    r = _write(env, write, StorageConstraintViolated(state, constraint))
    assert r.status_code == 422 and r.json()["code"] == "validation_failed"
    assert "al_cooldown" not in r.text and state not in r.text


@pytest.mark.parametrize("write", ["create", "update"])
def test_any_other_constraint_error_stays_a_defect(env: Env, write: str) -> None:
    install_error_redaction(env.c.app)  # the app's own handler answers the 500
    env.c = TestClient(env.c.app, raise_server_exceptions=False)
    r = _write(env, write, StorageConstraintViolated("23503", "alerts_owner_user_id_fkey"))
    assert r.status_code == 500 and r.json()["code"] == "internal_error"
    assert "alerts_owner_user_id_fkey" not in r.text and "23503" not in r.text


def test_the_contract_declares_409_and_422_for_alert_writes() -> None:
    paths: Any = load_openapi_spec()["paths"]
    for op in (paths["/alerts"]["post"], paths["/alerts/{alertId}"]["put"]):
        responses = op["responses"]
        assert responses["409"] == {"$ref": "#/components/responses/Conflict"}
        assert responses["422"] == {"$ref": "#/components/responses/UnprocessableEntity"}
