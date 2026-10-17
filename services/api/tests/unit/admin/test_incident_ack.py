"""Unit (E42-T05): `POST /admin/incidents/{incidentId}/acknowledge` against fakes: the transition,
the one write-ahead `incident.acknowledged` record, the refusals and the closed doors. A repeat
writes no second record: `test_incidents_sqlalchemy.py`, `test_incident_ack_pg.py`. The guard is in
`test_admin_http.py`, CSRF in `tests/contract/`. IDOR does not apply: the operation is
`scope: none`, so there is no per-account or per-user row to cross into."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.admin.ops.incidents import AdminIncidentsService
from candleviewer.api.admin_ops import incident_payload, make_admin_incident_ack_router
from candleviewer.api.error_redaction import validation_error_handler
from candleviewer.audit.actions import validate_action
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.redact import redact
from candleviewer.auth.generated_permissions import Permission
from candleviewer.storage.errors import StorageTierUnavailable, WriteAheadTimeout
from tests.unit.admin._admin_fakes import Resolver, expected_record, principal
from tests.unit.admin._ops_fakes import NOW, Store, row
from tests.unit.admin._tier_fakes import TierAuditSpy

_ROW = row(7)  # an id that is no user's, so a swapped `by` and `id` cannot pass unseen
_URL = "/admin/incidents/{}/acknowledge"
_PATH, _BAD = _URL.format(_ROW.id), _URL.format("not-a-uuid")
_SECRET = "postgresql://cv:" + "hunter2" + "@db/cv"  # built by concatenation: no scanner sees it
_KEY = "Zq9" + "x" * 20 + "AbCd"  # the shape `redact_text` masks as a key


def _app(store: Store | None = None, *, spy: Any = None, **service: Any) -> Any:
    """The route on the audited guard over `store` (`wired=False`: none) and the tier test's audit
    spy (it keeps `before_state`; `refuse` makes one action fail like a full WAL)."""
    wired = service.pop("wired", True)
    store, spy = store or Store([_ROW]), spy or TierAuditSpy()
    incidents = AdminIncidentsService(store if wired else None, now=lambda: NOW, **service)
    app = FastAPI()
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(make_admin_incident_ack_router(incidents, resolver=Resolver(), audit=spy))
    return TestClient(app), spy, store


def _post(client: TestClient, role: str = "owner", path: str = _PATH) -> Any:
    return client.post(path, headers={"x-role": role})


def _guard(role: str) -> dict[str, Any]:
    route = expected_record(role, _URL.format("{incidentId}"), Permission.ADMIN_WRITE)
    return route | {"before_state": None}


def _record(role: str) -> dict[str, Any]:
    """The whole `incident.acknowledged` record: the caller as the actor, the incident as the
    object, its status before and after and what it was; never its title or detail."""
    who, after = principal(role), {"status": "acknowledged", "component": "recorder"}
    return {
        "action": "incident.acknowledged", "actor_label": role, "actor_user_id": who.user_id,
        "actor_ip": who.ip, "session_id": who.session_id, "object_kind": "incident",
        "object_id": str(_ROW.id), "outcome": AuditOutcome.SUCCESS, "severity": Severity.INFO,
        "before_state": {"status": "open"}, "request_id": who.request_id,
        "after_state": after | {"severity": "error", "occurrences": 7},
    }  # fmt: skip


def test_a_writer_acknowledges_an_open_incident_and_the_one_record_names_them() -> None:
    client, spy, store = _app()
    response = _post(client, "admin")  # named "admin": the label is the caller's, not "owner"
    stored, who = store.rows[0], principal("admin")
    assert (stored.status, stored.acknowledged_by, stored.acknowledged_at) == (
        "acknowledged", who.user_id, NOW,
    )  # fmt: skip
    assert response.status_code == 200 and response.json() == incident_payload(stored)
    assert spy.records == [_guard("admin"), _record("admin")]
    assert validate_action("incident.acknowledged") == "incident.acknowledged"  # SR-E42-11
    assert redact(spy.records[1]["after_state"]) == spy.records[1]["after_state"]  # no secret key


@pytest.mark.parametrize(
    ("stored", "path", "status", "code"),
    [
        (row(7, status="resolved", resolved_at=NOW), _PATH, 409, "conflict"),
        (_ROW, _URL.format(row(8).id), 404, "not_found"),
        (_ROW, _BAD, 422, "validation_failed"),
    ],
    ids=["resolved", "unknown", "malformed"],
)
def test_a_refused_id_changes_and_records_nothing(
    stored: Any, path: str, status: int, code: str
) -> None:
    client, spy, store = _app(Store([stored]))
    response = _post(client, path=path)
    assert (response.status_code, response.json()["code"]) == (status, code)
    assert store.rows == [stored] and [r["action"] for r in spy.records] == ["admin.area_entered"]


@pytest.mark.parametrize("role", ["manager", "viewer", "reader"])  # `reader`: admin:read only
@pytest.mark.parametrize("path", [_PATH, _BAD], ids=["valid", "malformed"])
def test_a_denied_caller_is_audited_by_the_guard_and_never_reaches_the_store(
    role: str, path: str
) -> None:
    client, spy, store = _app()
    response = _post(client, role, path)  # RBAC first: the id is not even validated
    assert (response.status_code, response.json()["code"]) == (403, "forbidden")
    assert spy.records == [_guard(role)] and store.acks == []  # the denial's own row, none of ours


@pytest.mark.parametrize(
    ("stored", "service", "status", "code"),
    [
        (Store([_ROW]), {"wired": False}, 501, "not_implemented"),
        (Store([_ROW], error=StorageTierUnavailable(_SECRET)), {}, 503, "store_unavailable"),
        (Store([_ROW], hang=True), {"write_budget_s": 0.01}, 503, "store_unavailable"),
    ],
    ids=["not-wired", "tier-down", "budget"],
)
def test_a_store_that_is_missing_or_fails_is_refused_with_a_fixed_detail(
    stored: Store, service: dict[str, Any], status: int, code: str
) -> None:
    client, spy, _ = _app(stored, **service)
    with capture_logs() as logs:
        response = _post(client)
    assert (response.status_code, response.json()["code"]) == (status, code)
    assert ("retry-after" in response.headers) == (status == 503)
    assert "hunter2" not in response.text + repr(logs)  # the class is logged, never the text
    assert [r["action"] for r in spy.records] == ["admin.area_entered"]
    assert stored.rows == [_ROW]


@pytest.mark.parametrize(
    ("refuse", "error", "klass"),
    [
        ("incident.acknowledged", None, "RuntimeError"),
        (None, WriteAheadTimeout("write-ahead audit exceeded 5.0 s"), "WriteAheadTimeout"),
    ],
    ids=["refused", "timed-out"],
)
def test_a_record_that_cannot_be_written_refuses_the_change(
    refuse: str | None, error: Exception | None, klass: str
) -> None:
    client, spy, store = _app(Store([_ROW], error=error), spy=TierAuditSpy(refuse=refuse))
    with capture_logs() as logs:
        response = _post(client)
    assert (response.status_code, response.json()["code"]) == (503, "audit_unavailable")
    assert store.rows == [_ROW] and [r["action"] for r in spy.records] == ["admin.area_entered"]
    (log,) = logs  # the class only, never "audit WAL full at /var/lib/cv"
    assert (log["event"], log["error"]) == ("admin_incidents.ack_audit_failed", klass)
    assert "/var/lib/cv" not in response.text + repr(logs)


def test_the_served_row_is_redacted_again_like_the_lists_and_the_stored_one_is_not() -> None:
    client, _, store = _app(Store([row(7, title=_KEY, detail=_KEY)]))
    shown = _post(client).json()
    assert (shown["title"], shown["detail"]) == ("[redacted:key-shape]",) * 2
    assert (store.rows[0].title, store.rows[0].detail) == (_KEY, _KEY)
