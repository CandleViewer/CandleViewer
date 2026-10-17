"""Contract (E42-T05, health read slice): `GET /admin/health` over HTTP. The RBAC cells of the
issue (owner 200, manager 403 plus an audit record, viewer 403, unauthenticated 401) with the
whole audit record, a body that validates against the contract schema and round-trips through the
generated model, and a refusal that is a contract `Problem`."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from candleviewer.api._generated import openapi_models as api
from candleviewer.observability.health_probes import HealthRegistry
from candleviewer.observability.redaction import redact_structure
from tests.contract._admin_support import validate_example
from tests.unit.admin._admin_fakes import expected_record
from tests.unit.admin._ops_fakes import make_app, settled_registry

_SCHEMA = "/paths/~1admin~1health/get/responses/200/content/application~1json/schema"
_PATH = "/admin/health"


@pytest.mark.parametrize(
    ("role", "status", "code"),
    [("owner", 200, None), ("reader", 200, None), ("manager", 403, "forbidden"),
     ("viewer", 403, "forbidden"), ("", 401, "unauthenticated")],
    ids=["owner", "admin-read-only", "manager", "viewer", "unauthenticated"],
)  # fmt: skip
async def test_rbac_cell(role: str, status: int, code: str | None) -> None:
    app, spy = make_app(await settled_registry())
    response = TestClient(app).get(_PATH, headers={"x-role": role})
    assert response.status_code == status
    # The whole record, written before the handler or the refusal (write-ahead); none for 401.
    assert spy.records == ([] if status == 401 else [expected_record(role, _PATH)])
    if code is not None:
        assert response.headers["content-type"] == "application/problem+json"
        assert response.json()["code"] == code
        assert "components" not in response.json()  # a refused caller reads no health detail


async def test_the_response_validates_against_the_contract_and_round_trips() -> None:
    app, _ = make_app(await settled_registry())
    body = TestClient(app).get(_PATH, headers={"x-role": "owner"}).json()
    validate_example(_SCHEMA, body)
    assert api.HealthReport.model_validate(body).model_dump(mode="json", exclude_unset=True) == body
    assert redact_structure(body) == body  # the shared redaction rule set finds nothing to mask


@pytest.mark.parametrize("wired", [False, True], ids=["not-wired", "no-snapshot-yet"])
def test_a_refusal_is_a_contract_problem_with_a_registered_code(wired: bool) -> None:
    app, _ = make_app(HealthRegistry() if wired else None)
    response = TestClient(app).get(_PATH, headers={"x-role": "owner"})
    assert response.status_code == (503 if wired else 501)
    validate_example("/components/schemas/Problem", response.json())
    assert response.json()["type"].rsplit("/", 1)[1] == response.json()["code"]
