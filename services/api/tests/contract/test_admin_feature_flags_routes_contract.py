"""Contract (E42-T03): `listFeatureFlags` and `setFeatureFlag` over HTTP. The RBAC cells (owner
answered, manager and viewer 403 with the guard's denial record, unauthenticated 401), and real
answers that validate against the contract schema and round-trip through the generated models: the
list, a write, a conflict and a refusal."""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest
from pydantic import BaseModel

from candleviewer.api._generated import openapi_models as api
from candleviewer.api.contract_conformance import load_openapi_spec
from tests.unit.admin._flag_route_fakes import client, put, write

_SPEC: Any = load_openapi_spec()  # a parsed YAML document, walked untyped
_LIST, _PUT = "/admin/feature-flags", "/admin/feature-flags/{flagKey}"


def _deref(node: Any) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            kind, name = node["$ref"].split("/")[-2:]
            return _deref(_SPEC["components"][kind][name])
        return {k: _deref(v) for k, v in node.items() if k != "examples"}
    return [_deref(v) for v in node] if isinstance(node, list) else node


def _schema(path: str, method: str, status: str) -> Any:
    answer = _deref(_SPEC["paths"][path][method]["responses"][status])
    return next(iter(answer["content"].values()))["schema"]


@pytest.mark.parametrize("method", ["get", "put"])
@pytest.mark.parametrize(
    ("role", "status"), [("owner", 200), ("manager", 403), ("viewer", 403), ("", 401)]
)
def test_rbac_cell(method: str, role: str, status: int) -> None:
    c, audit = client()
    if method == "get":
        response = c.get(_LIST, headers={"x-role": role})
    else:
        response = put(c, write(), role=role)
    assert response.status_code == status
    entered = [kw for action, kw in audit.records if action == "admin.area_entered"]
    assert len(entered) == (status != 401)  # the guard's record, the denial's own for a 403
    if status != 200:
        assert response.json()["code"] == {401: "unauthenticated", 403: "forbidden"}[status]


@pytest.mark.parametrize(
    ("path", "body", "status", "model"),
    [
        (_LIST, None, "200", None),
        (_PUT, write(), "200", api.FeatureFlag),
        (_PUT, write(value="yes"), "422", api.Problem),
    ],
    ids=["list", "write", "refusal"],
)
def test_the_answer_validates_against_the_contract(
    path: str, body: Any, status: str, model: type[BaseModel] | None
) -> None:
    c, _ = client()
    if body is None:
        response = c.get(path, headers={"x-role": "owner"})
    else:
        response = put(c, body)
    assert response.status_code == int(status)
    jsonschema.validate(response.json(), _schema(path, "get" if body is None else "put", status))
    if model is not None:
        dumped = model.model_validate(response.json()).model_dump(mode="json", exclude_unset=True)
        assert dumped == response.json()


def test_a_conflict_carries_the_current_flag_as_the_contract_shapes_it() -> None:
    c, _ = client()
    put(c, write())
    response = put(c, write())  # still names the first read
    assert response.status_code == 409
    jsonschema.validate(response.json(), _schema(_PUT, "put", "409"))
    conflict = api.FeatureFlagConflict.model_validate(response.json())
    assert conflict.model_dump(mode="json", exclude_unset=True) == response.json()
