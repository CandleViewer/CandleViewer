"""Contract (E42-T05, incidents read slice): `GET /admin/incidents` over HTTP. The RBAC cells of
the issue (owner 200, manager 403 plus an audit record, viewer 403, unauthenticated 401) with the
whole record and no read of the store for a refused caller, a body that validates against the
contract schema and round-trips through the generated models, the contract's own 40-events example
served as stored, and refusals that are `Problem` documents."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from candleviewer.api._generated import openapi_models as api
from candleviewer.storage.repositories.incidents import IncidentRow
from tests.contract._admin_support import SPEC, validate_example
from tests.unit.admin._admin_fakes import expected_record
from tests.unit.admin._ops_fakes import Store, make_app, row

_PATH = "/admin/incidents"
_SCHEMA = "/paths/~1admin~1incidents/get/responses/200/content/application~1json/schema"
_OK = SPEC["paths"][_PATH]["get"]["responses"]["200"]["content"]["application/json"]
_GROUPED = _OK["examples"]["grouped"]["value"]


@pytest.mark.parametrize(
    ("role", "status", "code"),
    [("owner", 200, None), ("reader", 200, None), ("manager", 403, "forbidden"),
     ("viewer", 403, "forbidden"), ("", 401, "unauthenticated")],
    ids=["owner", "admin-read-only", "manager", "viewer", "unauthenticated"],
)  # fmt: skip
def test_rbac_cell(role: str, status: int, code: str | None) -> None:
    store = Store([row(1)])
    app, spy = make_app(store=store)
    response = TestClient(app).get(_PATH, headers={"x-role": role})
    assert response.status_code == status
    # The whole record, written before the handler or the refusal (write-ahead); none for 401.
    assert spy.records == ([] if status == 401 else [expected_record(role, _PATH)])
    if code is not None:
        assert response.json()["code"] == code and store.calls == []  # the store is never read


def test_the_response_validates_against_the_contract_and_round_trips() -> None:
    app, _ = make_app(store=Store([row(1), row(2)]))
    body = TestClient(app).get(_PATH, headers={"x-role": "owner"}).json()
    validate_example(_SCHEMA, body)
    assert api.Page.model_validate(body).model_dump(mode="json", exclude_unset=True) == body
    for item in body["items"]:
        assert api.Incident.model_validate(item).model_dump(mode="json", exclude_unset=True) == item


def _stored(item: dict[str, Any]) -> IncidentRow:
    """The contract example's incident as the `incidents` table holds it."""
    times = {k: datetime.fromisoformat(item[k]) for k in ("first_seen_at", "last_seen_at")}
    return IncidentRow(**item | times | {"id": UUID(item["id"])})


def test_forty_events_grouped_into_one_incident_are_served_exactly_as_the_contract_shows() -> None:
    (stored,) = _GROUPED["items"]
    app, _ = make_app(store=Store([_stored(stored)]))
    response = TestClient(app).get(_PATH, headers={"x-role": "owner"})
    assert response.json() == _GROUPED  # 40 occurrences, first and last seen, status open
    assert response.json()["items"][0]["occurrences"] == 40


@pytest.mark.parametrize(
    ("store", "status"),
    [(None, 501), (Store(error=TimeoutError()), 503)],
    ids=["not-wired", "down"],
)
def test_a_refusal_is_a_contract_problem_with_a_registered_code(
    store: Store | None, status: int
) -> None:
    app, _ = make_app(store=store)
    response = TestClient(app).get(_PATH, headers={"x-role": "owner"})
    assert response.status_code == status
    validate_example("/components/schemas/Problem", response.json())
    assert response.json()["type"].rsplit("/", 1)[1] == response.json()["code"]
