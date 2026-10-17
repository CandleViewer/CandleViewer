"""Unit (E42-T05): the `GET /admin/incidents` handler: its payload, the paging inputs and the
registered problem every refusal uses (a fixed detail, never source text). The guard is tested in
`test_admin_http.py`, the RBAC cells in `tests/contract/test_admin_incidents_contract.py`."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from candleviewer.api.admin_ops import incident_payload
from candleviewer.storage.errors import StorageTierUnavailable
from tests.unit.admin._ops_fakes import NOW, Store, make_app, row

_SECRET = "postgresql://cv:" + "hunter2" + "@db/cv"  # concatenated: no scanner sees a credential


def _get(store: Store | None, **params: Any) -> Response:
    """The owner's request against a fresh app: the store keeps no state, so cursors carry over."""
    app, _ = make_app(store=store)
    response: Response = TestClient(app).get(
        "/admin/incidents", params=params, headers={"x-role": "owner"}
    )
    return response


def test_incidents_page_through_cursors_with_the_contracts_meta() -> None:
    store = Store([row(1), row(2), row(3)])
    first = _get(store, limit=2).json()
    assert [i["occurrences"] for i in first["items"]] == [1, 2]
    meta = first["meta"]
    assert (meta["has_more"], meta["count"], isinstance(meta["next_cursor"], str)) == (
        True,
        2,
        True,
    )
    last = _get(store, limit=2, cursor=meta["next_cursor"]).json()
    assert [i["occurrences"] for i in last["items"]] == [3]
    assert last["meta"] == {"next_cursor": None, "has_more": False, "count": 1}


def test_a_stored_null_is_sent_as_null_and_a_dropped_title_is_left_out() -> None:
    kept = incident_payload(row(1, detail=None, acknowledged_by=None))
    assert kept["detail"] is None and kept["acknowledged_by"] is None
    assert "title" not in incident_payload(row(1, title=None))  # its redaction failed


def test_the_status_filter_reaches_the_store() -> None:
    store = Store([row(1), row(2, status="resolved", resolved_at=NOW)])
    shown = _get(store, status="resolved").json()["items"]
    assert [i["status"] for i in shown] == ["resolved"]


@pytest.mark.parametrize(
    "params",
    [{"status": "closed"}, {"limit": 0}, {"limit": 501}, {"cursor": "A" * 513}],
    ids="status low high long".split(),
)
def test_the_contracts_closed_set_and_bounds_are_enforced(params: dict[str, Any]) -> None:
    store = Store([row(1)])
    refused = _get(store, **params)
    assert (refused.status_code, refused.json()["code"]) == (422, "validation_failed")
    assert store.calls == []  # refused before the store is asked


def test_a_bad_cursor_is_a_400_that_does_not_echo_it() -> None:
    response = _get(Store([row(1)]), cursor="not-a-cursor")
    assert (response.status_code, response.json()["code"]) == (400, "invalid_cursor")
    assert "retry-after" not in response.headers and "not-a-cursor" not in response.text


@pytest.mark.parametrize(
    ("store", "status", "code"),
    [
        (None, 501, "not_implemented"),
        (Store(error=StorageTierUnavailable(_SECRET)), 503, "store_unavailable"),
        (Store(error=TimeoutError(_SECRET)), 503, "store_unavailable"),
    ],
    ids=["not-wired", "tier-down", "timeout"],
)
def test_incidents_refuse_instead_of_serving_an_empty_page(
    store: Store | None, status: int, code: str
) -> None:
    response = _get(store)
    assert (response.status_code, response.json()["code"]) == (status, code)
    assert "items" not in response.json() and "hunter2" not in response.text
    if status == 503:  # the read model's literal, whatever the source said
        assert response.json()["detail"] == "incidents: store unavailable"
