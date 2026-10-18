"""E42-T01: `PUT /admin/capacity/subaccount-tier` against fakes (contract `setSubaccountTier`).

The guard is tested in `test_admin_http.py`; here the route behind it: the closed body and its 422s,
the 503s, the whole `settings.change` record written ahead of the row, `Idempotency-Key` ignored,
the capacity cache dropped by a write, a failing `used` never un-recording the tier. The same route
on the real `create_app` (CSRF, schema, RBAC matrix) is in `tests/contract/`."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import jsonschema
import pytest
from fastapi.testclient import TestClient
from httpx import Response
from structlog.testing import capture_logs

from candleviewer.admin.overview.ports import SUBACCOUNT_TIER_KEY
from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.audit.writer import AuditWriter
from candleviewer.auth.generated_permissions import Permission
from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories.system_settings import StoredSetting
from tests.unit.admin._admin_fakes import expected_record, principal
from tests.unit.admin._route_fakes import NOW, Ports
from tests.unit.admin._tier_fakes import TierAuditSpy, make_tier_app
from tests.unit.audit.audit_fakes import FakeAuditRepository
from tests.unit.storage.fakes_system_settings import FakeSystemSettings

_PATH = "/admin/capacity/subaccount-tier"
_AT = datetime(2026, 10, 1, tzinfo=UTC)  # the fake store's clock: when the row was recorded
_ERRORS = "https://candleviewer.local/errors/"
_PROBLEM = {"$ref": "#/components/schemas/Problem", "components": load_openapi_spec()["components"]}
# A DSN with a fake password, which must never be echoed. Its scheme is joined at run time, so
# trufflehog's Postgres detector finds nothing here (#3482). Real credentials never go in source.
_DSN = "postgresql" + "://cv:hunter2@db/cv"


def _recorded(word: str | None) -> FakeSystemSettings:
    store = FakeSystemSettings()
    if word is not None:
        store.rows[SUBACCOUNT_TIER_KEY] = StoredSetting(word, _AT)
    return store


def _failing(error: BaseException) -> FakeSystemSettings:
    """A store whose write raises `error`, as the database or the hook's bound would."""

    class Failing(FakeSystemSettings):
        async def put_string(self, *a: Any, **kw: Any) -> StoredSetting:
            raise error

    return Failing()


def _app(
    store: FakeSystemSettings | None, **kw: Any
) -> tuple[TestClient, TierAuditSpy, FakeSystemSettings | None]:
    app, spy = make_tier_app(store, now=lambda: NOW, **kw)
    return TestClient(app), spy, store


def _put(client: TestClient, body: Any = None, role: str = "owner", **kw: Any) -> Any:
    headers = {"x-role": role, **kw.pop("headers", {})}
    return client.put(_PATH, json=body, headers=headers, **kw)


def _guard_record(role: str = "owner") -> dict[str, Any]:
    """What the admin router writes before the handler runs (`before_state` is the spy's)."""
    return expected_record(role, _PATH, Permission.ADMIN_WRITE) | {"before_state": None}


def _change_record(before: str | None, after: str, role: str = "owner") -> dict[str, Any]:
    """The `settings.change` record: the writer's guard fields (actor, ip, session, request id,
    success, info) with the setting as the object and the tier before and after."""
    return expected_record(role, _PATH, Permission.ADMIN_WRITE) | {
        "action": "settings.change",
        "object_kind": "setting",
        "object_id": SUBACCOUNT_TIER_KEY,
        "before_state": {"tier": before},
        "after_state": {"tier": after},
    }


def _problem(response: Response, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    body: dict[str, Any] = response.json()
    assert (body["status"], body["code"], body["type"]) == (status, code, _ERRORS + code)
    return body


# -- the happy path and its audit record ---------------------------------------------------------


@pytest.mark.parametrize(("word", "cap"), [("regular", 5), ("business_kyc", 20)])
def test_the_owner_records_the_tier_and_gets_the_resulting_capacity(word: str, cap: int) -> None:
    client, spy, store = _app(_recorded(None))
    response = _put(client, {"tier": word})
    assert (response.status_code, response.json()) == (
        200,
        {
            "status": "ok",
            "generated_at": "2026-10-16T00:30:00Z",
            "tier": word,
            "cap": cap,
            "used": 3,  # the fakes' sub-account count: read fresh, not from the tier row
            "tier_source": "recorded",
            "recorded_at": "2026-10-01T00:00:00Z",
        },
    )
    assert store is not None and store.rows[SUBACCOUNT_TIER_KEY] == StoredSetting(word, _AT)
    assert store.written_by[SUBACCOUNT_TIER_KEY] == principal("owner").user_id
    assert [r["action"] for r in spy.records] == ["admin.area_entered", "settings.change"]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (None, "business_kyc"),
        ("regular", "business_kyc"),
        ("business_kyc", "regular"),
        ("regular", "regular"),  # a repeat: before == after, and still audited
        ("enterprise", "regular"),  # a stored word that is no tier is audited as it stood
    ],
    ids=["first", "upgrade", "downgrade", "repeat", "unrecognised-before"],
)
def test_the_whole_settings_change_record_names_the_tier_before_and_after(
    before: str | None, after: str
) -> None:
    client, spy, _ = _app(_recorded(before))
    assert _put(client, {"tier": after}, "admin").status_code == 200  # named "admin", not "owner"
    assert spy.records == [_guard_record("admin"), _change_record(before, after, "admin")]


async def test_the_record_survives_the_real_writer_and_its_redactor(tmp_path: Path) -> None:
    repo = FakeAuditRepository()
    writer = AuditWriter(repo, str(tmp_path / "audit.wal"), sleep=repo.retry_sleep)
    await writer.start()
    app, _ = make_tier_app(_recorded("regular"), spy=writer, now=lambda: NOW)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://cv") as client:
        sent = {"tier": "business_kyc"}
        assert (await client.put(_PATH, json=sent, headers={"x-role": "owner"})).status_code == 200
    await writer.flush(5)
    await writer.stop(1)
    rows = [(r["action"], r["object_id"], r["before_state"], r["after_state"]) for r in repo.rows]
    assert [(a, o, json.loads(b or "null"), json.loads(f)) for a, o, b, f in rows] == [
        ("admin.area_entered", _PATH, None, {"route": _PATH, "reauth_age_s": None}),
        # `tier` is not a secret-shaped field name: both states survive the redactor unmasked
        ("settings.change", SUBACCOUNT_TIER_KEY, {"tier": "regular"}, {"tier": "business_kyc"}),
    ]


def test_the_record_is_written_ahead_of_the_row_it_describes() -> None:
    store = _recorded("regular")
    seen: list[dict[str, StoredSetting]] = []

    class Peek(TierAuditSpy):
        async def emit(self, action: str, **fields: Any) -> None:
            if action == "settings.change":
                seen.append(dict(store.rows))  # the store as the record is appended
            await super().emit(action, **fields)

    client, _, _ = _app(store, spy=Peek())
    assert _put(client, {"tier": "business_kyc"}).status_code == 200
    assert seen == [{SUBACCOUNT_TIER_KEY: StoredSetting("regular", _AT)}]  # still the old tier
    assert store.rows[SUBACCOUNT_TIER_KEY].value == "business_kyc"  # and then the new one


# -- who may call it -----------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["manager", "viewer", "reader"])  # `reader`: admin:read only
@pytest.mark.parametrize("body", [{"tier": "business_kyc"}, {"nope": 1}], ids=["valid", "invalid"])
def test_a_denied_caller_is_audited_by_the_guard_and_never_reaches_the_store(
    role: str, body: Any
) -> None:
    client, spy, store = _app(_recorded("regular"))
    denied = _problem(_put(client, body, role), 403, "forbidden")  # before any validation
    assert denied["detail"] == "requires admin:write"
    assert spy.records == [_guard_record(role)]  # the denial's own row; no `settings.change`
    assert store is not None and store.calls == []
    assert store.rows[SUBACCOUNT_TIER_KEY].value == "regular"


def test_an_anonymous_caller_is_refused_before_the_body_is_even_read() -> None:
    client, spy, store = _app(_recorded(None))
    response = client.put(_PATH, content=b"{not json", headers={"x-role": ""})
    _problem(response, 401, "unauthenticated")
    assert spy.records == [] and store is not None and store.calls == []


# -- the closed body (422) -----------------------------------------------------------------------

_CANARY = "sk_live_" + "Zq9x" * 6  # a secret-shaped value a client might send, as a tier or a key


@pytest.mark.parametrize(
    ("raw", "field", "rule"),
    [
        (b"{}", "tier", "missing"),
        (b'{"tier": "gold"}', "tier", "literal_error"),
        (b'{"tier": "Regular"}', "tier", "literal_error"),
        (b'{"tier": null}', "tier", "literal_error"),
        (f'{{"tier": "regular", "{_CANARY}": 20}}'.encode(), "", "extra_forbidden"),
        (b'["regular"]', "", "model_type"),
        (b"not json", "", "json_invalid"),
        (b'{"tier": "regular"}'.ljust(1025), "", "body_too_large"),  # one byte over the cap
        (f'{{"tier": "{_CANARY}"}}'.encode(), "tier", "literal_error"),
    ],
    ids="missing gold case null extra list junk big canary".split(),
)
def test_a_body_that_is_not_one_of_the_two_tiers_is_422_and_changes_nothing(
    raw: bytes, field: str, rule: str
) -> None:
    client, spy, store = _app(_recorded("regular"))
    body = _problem(_put(client, content=raw), 422, "validation_failed")
    assert [(e["field"], e["rule"]) for e in body["errors"]] == [(field, rule)]
    assert _CANARY not in str(body)  # the input is never echoed: not as a value, not as a key
    assert [r["action"] for r in spy.records] == ["admin.area_entered"]  # nothing to audit
    assert store is not None and store.calls == []  # not even read
    assert store.rows[SUBACCOUNT_TIER_KEY].value == "regular"


def test_a_body_of_exactly_the_cap_is_read() -> None:  # 1025 bytes is `body_too_large`, above
    client, _, _ = _app(_recorded(None))
    assert _put(client, content=b'{"tier": "regular"}'.ljust(1024)).status_code == 200


# -- the store and the audit trail fail closed (503) ---------------------------------------------


def _unavailable(response: Response, code: str) -> None:
    body = _problem(response, 503, code)
    jsonschema.validate(body, _PROBLEM)
    assert response.headers["retry-after"] == "5" and body["retry_after_seconds"] == 5
    assert not [leak for leak in ("/var/lib", "WAL full", "Errno") if leak in response.text]


@pytest.mark.parametrize("wired", [False, True], ids=["no-store", "down"])
def test_a_store_that_is_missing_or_down_is_503_with_a_fixed_detail(wired: bool) -> None:
    store = _recorded(None) if wired else None
    if store is not None:
        store.down = True
    client, spy, _ = _app(store)
    response = _put(client, {"tier": "regular"})
    _unavailable(response, "store_unavailable")
    assert response.json()["detail"] == "The settings store is unavailable."
    assert [r["action"] for r in spy.records] == ["admin.area_entered"]  # no `settings.change`
    assert store is None or store.rows == {}


def test_an_os_error_from_the_store_is_503_and_only_its_class_is_logged() -> None:
    refused = ConnectionRefusedError(f"[Errno 111] dsn={_DSN}")
    client, _, _ = _app(_failing(refused))
    with capture_logs() as logs:
        _unavailable(_put(client, {"tier": "regular"}), "store_unavailable")
    assert [(log["event"], log["error"]) for log in logs] == [
        ("admin_tier_store_unavailable", "ConnectionRefusedError")
    ]
    assert "hunter2" not in str(logs)


def test_a_commit_that_fails_after_the_record_leaves_the_tier_unchanged_and_over_reports() -> None:
    store = _recorded("regular")
    store.commit_fails = True
    client, spy, _ = _app(store)
    _unavailable(_put(client, {"tier": "business_kyc"}), "store_unavailable")
    assert store.rows[SUBACCOUNT_TIER_KEY].value == "regular"  # unchanged
    assert spy.records[-1] == _change_record("regular", "business_kyc")  # never under-reported


def test_a_record_that_cannot_be_written_refuses_the_change() -> None:
    client, spy, store = _app(_recorded("regular"), spy=TierAuditSpy(refuse="settings.change"))
    with capture_logs() as logs:
        response = _put(client, {"tier": "business_kyc"})
    _unavailable(response, "audit_unavailable")
    assert store is not None and store.rows[SUBACCOUNT_TIER_KEY].value == "regular"
    assert [r["action"] for r in spy.records] == ["admin.area_entered"]  # the guard's row only
    who = principal("owner")
    assert [(log["event"], log["error"]) for log in logs] == [
        ("admin_tier_audit_failed", "RuntimeError")  # the class only, never "audit WAL full"
    ]
    assert (logs[0]["actor_user_id"], logs[0]["request_id"]) == (who.user_id, who.request_id)


def test_a_write_ahead_timeout_is_also_audit_unavailable_and_logged() -> None:
    client, _, _ = _app(_failing(WriteAheadTimeout("write-ahead audit exceeded 5.0 s")))
    with capture_logs() as logs:
        _unavailable(_put(client, {"tier": "regular"}), "audit_unavailable")
    assert [(log["event"], log["error"]) for log in logs] == [
        ("admin_tier_audit_failed", "WriteAheadTimeout")
    ]


def test_a_bug_in_the_store_is_not_dressed_up_as_an_outage() -> None:
    client, _, _ = _app(_failing(RuntimeError("programming error")))
    with pytest.raises(RuntimeError, match="programming error"):
        _put(client, {"tier": "regular"})


# -- x-idempotency: ignored ----------------------------------------------------------------------


@pytest.mark.parametrize("key", ["6f1d2c3b-4a5e-4f60-8a7b-9c0d1e2f3a4b", "not-a-uuid", ""])
def test_the_idempotency_key_is_never_read_so_one_key_cannot_replay_or_conflict(key: str) -> None:
    client, _, store = _app(_recorded(None))
    headers = {"Idempotency-Key": key}
    first = _put(client, {"tier": "regular"}, headers=headers)
    other = _put(client, {"tier": "business_kyc"}, headers=headers)  # same key, another body
    assert (first.status_code, other.status_code) == (200, 200)  # no 409 `idempotency_key_reuse`
    assert "idempotency-replayed" not in other.headers and other.json()["tier"] == "business_kyc"
    assert store is not None and store.rows[SUBACCOUNT_TIER_KEY].value == "business_kyc"


# -- read-after-write ----------------------------------------------------------------------------


def test_the_next_capacity_read_shows_the_new_tier_at_once() -> None:
    client, _, _ = _app(_recorded(None))
    headers = {"x-role": "owner"}
    before = client.get("/admin/capacity", headers=headers).json()["subaccounts"]
    assert (before["tier"], before["tier_source"]) == (None, "unrecorded")  # and now cached
    assert _put(client, {"tier": "business_kyc"}).status_code == 200
    after = client.get("/admin/capacity", headers=headers).json()["subaccounts"]
    assert (after["tier"], after["cap"], after["tier_source"]) == ("business_kyc", 20, "recorded")


def test_a_failed_write_also_drops_the_cached_slice() -> None:
    store = _recorded(None)
    client, _, _ = _app(store)
    headers = {"x-role": "owner"}
    assert client.get("/admin/capacity", headers=headers).json()["subaccounts"]["tier"] is None
    store.down = True
    assert _put(client, {"tier": "regular"}).status_code == 503
    store.down, store.rows[SUBACCOUNT_TIER_KEY] = False, StoredSetting("business_kyc", _AT)
    got = client.get("/admin/capacity", headers=headers).json()["subaccounts"]
    assert got["tier"] == "business_kyc"  # an ambiguous commit never leaves a stale slice


def test_a_failing_usage_source_never_un_records_the_tier() -> None:
    class NoUsage(Ports):
        async def subaccounts_in_use(self) -> int:
            raise OSError("db at 10.0.0.9 unreachable")

    client, spy, store = _app(_recorded(None), ports=NoUsage())
    response = _put(client, {"tier": "business_kyc"})
    assert response.status_code == 200  # the tier is committed and audited before `used` is read
    assert response.json() == {
        "status": "error",
        "detail": "subaccounts: source failed",
        "generated_at": "2026-10-16T00:30:00Z",
        "tier": "business_kyc",
        "cap": 20,
        "tier_source": "recorded",
        "recorded_at": "2026-10-01T00:00:00Z",  # `used` is omitted, never defaulted to 0
    }
    assert store is not None and store.rows[SUBACCOUNT_TIER_KEY].value == "business_kyc"
    assert spy.records[-1] == _change_record(None, "business_kyc")
    store.rows[SUBACCOUNT_TIER_KEY] = StoredSetting("regular", _AT)  # changed behind the route
    read = client.get("/admin/capacity", headers={"x-role": "owner"}).json()["subaccounts"]
    assert read["tier"] == "regular"  # the failed-`used` answer was not cached: this read is fresh
