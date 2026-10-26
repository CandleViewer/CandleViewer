"""#4674: `updateRule`'s stale `If-Match` answers the status 22 declares for it (412).

22 declares `412 PreconditionFailed` (code `version_conflict`) for `PUT /rules/{ruleId}` and no
`409`; the provider must answer exactly that, so a client following 22 reaches its reload path.
"""

from __future__ import annotations

from typing import Any

import pytest

from candleviewer.api.contract_conformance import load_openapi_spec
from tests.rules.test_rules_routes import _Env, _ir


@pytest.fixture(scope="module")
def update_rule_responses() -> dict[str, Any]:
    paths = load_openapi_spec()["paths"]
    assert isinstance(paths, dict)
    op = paths["/rules/{ruleId}"]["put"]
    assert op["operationId"] == "updateRule"
    responses = op["responses"]
    assert isinstance(responses, dict)
    return responses


def test_update_rule_contract_declares_412_and_no_409(
    update_rule_responses: dict[str, Any],
) -> None:
    assert update_rule_responses["412"] == {"$ref": "#/components/responses/PreconditionFailed"}
    assert "409" not in update_rule_responses


def test_update_rule_stale_if_match_answers_a_declared_status_with_the_declared_code(
    update_rule_responses: dict[str, Any],
) -> None:
    e = _Env()
    rid = e.create()
    ok = e.c.put(f"/rules/{rid}", json={"ir": _ir("2")}, headers={"If-Match": '"1"'})
    assert ok.status_code == 200
    stale = e.c.put(f"/rules/{rid}", json={"ir": _ir("3")}, headers={"If-Match": '"1"'})
    assert str(stale.status_code) in update_rule_responses
    assert stale.status_code == 412
    body = stale.json()
    assert body["code"] == "version_conflict" and body["status"] == 412
    assert body["title"] == "Version conflict"
