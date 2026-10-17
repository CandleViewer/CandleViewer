"""GET /users/{userId}/account-access (E42-T08 S9b, #2648; contract `listUserAccountAccess`).

Owner only (`users:read`), decided before any lookup, so one 403 serves an existing and a missing
user alike (threat U25). A missing or deleted user is 404. The body is the user's live grants and
is a valid input to the `PUT`. The read on Postgres: tests/integration/storage/*account_access*.
"""

from __future__ import annotations

import uuid
from typing import Any

import jsonschema
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

from candleviewer.api.contract_conformance import load_openapi_spec
from candleviewer.api.users import make_users_router
from candleviewer.audit.writer import AuditUnavailable, AuditWriterStopped
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.storage.errors import StorageQueryFailed
from candleviewer.storage.repositories.account_access import (
    AccessGrant,
    AccessLevel,
    AccessUserNotFoundError,
)

CALLER, TARGET, OTHER, EMPTY, MISSING, DELETED = (uuid.uuid4() for _ in range(6))
_A, _B, _C = sorted(uuid.uuid4() for _ in range(3))
_PATH = "/users/{}/account-access"
_CONTRACT = "/users/{userId}/account-access"


class _Emitter:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.error = error

    async def emit(self, action: str, **kw: Any) -> None:
        if self.error is not None:
            raise self.error
        self.calls.append({"action": action, **kw})


class _Store:
    """`AccountAccessStore` over in-memory grants: a user without an entry does not exist, and a
    `deleted` one is hidden as a missing one is (the real read filters `deleted_at IS NULL`)."""

    def __init__(
        self,
        grants: dict[uuid.UUID, list[AccessGrant]],
        *,
        deleted: frozenset[uuid.UUID] = frozenset(),
        error: Exception | None = None,
    ) -> None:
        self.grants, self.deleted, self.error = grants, deleted, error
        self.calls: list[uuid.UUID] = []

    async def list_grants(self, user_id: uuid.UUID) -> list[AccessGrant]:
        self.calls.append(user_id)
        if self.error is not None:
            raise self.error
        if user_id in self.deleted or user_id not in self.grants:
            raise AccessUserNotFoundError(str(user_id))
        return list(self.grants[user_id])


class _Resolver:
    def __init__(self, snap: PrincipalSnapshot | None) -> None:
        self.snap = snap

    def resolve(self, request: Request) -> PrincipalSnapshot | None:
        return self.snap


class _Notifier:
    async def roles_changed(self, user_id: uuid.UUID) -> None:
        raise AssertionError("a read notifies nobody")


@pytest.fixture(scope="module")
def spec() -> dict[str, Any]:
    loaded: dict[str, Any] = load_openapi_spec()
    return loaded


def _principal(
    role: str, spec: dict[str, Any], grants: tuple[AccountGrant, ...] = ()
) -> PrincipalSnapshot:
    """The caller as the contract's `x-permissions` define the role (the owner holds every code)."""
    codes = frozenset(Permission) if role == "owner" else None
    perms = codes or frozenset(Permission(p) for p in spec["x-permissions"][role])
    return PrincipalSnapshot(CALLER, frozenset({role}), perms, grants)


def _grant(
    account: uuid.UUID,
    level: AccessLevel = "read",
    label: str = "main",
    env: str = "live",
    granted_by: uuid.UUID | None = CALLER,
) -> AccessGrant:
    return AccessGrant(account, level, label, env, granted_by)


def _client(
    store: _Store | None, snap: PrincipalSnapshot | None, emitter: _Emitter | None = None
) -> TestClient:
    app = FastAPI()
    users = make_users_router(
        None, emitter or _Emitter(), _Resolver(snap), _Notifier(), account_access=store
    )
    app.include_router(users)
    return TestClient(app, headers={"Authorization": "Bearer tok"})


def _errors(spec: dict[str, Any], schema: dict[str, Any], body: Any) -> list[str]:
    """Contract violations of `body` against an operation's schema (its `$ref`s resolved)."""
    root = {**schema, "components": spec["components"]}
    return [e.message for e in jsonschema.Draft202012Validator(root).iter_errors(body)]


def _users_read_denied() -> float:
    labels = {"permission": Permission.USERS_READ.value}
    return float(REGISTRY.get_sample_value("authz_denied_total", labels) or 0.0)


def test_get_lists_live_grants_of_live_accounts(spec: dict[str, Any]) -> None:
    held = [_grant(_A, "read", "main", "live", CALLER), _grant(_B, "trade", "sub-1", "demo", None)]
    store = _Store({TARGET: held})
    r = _client(store, _principal("owner", spec)).get(_PATH.format(TARGET))
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/json")
    assert r.json() == {
        "items": [
            {
                "exchange_account_id": str(_A),
                "level": "read",
                "account_label": "main",
                "environment": "live",
                "granted_by": str(CALLER),
            },
            {  # the granting user is gone: the field is left out, not null
                "exchange_account_id": str(_B),
                "level": "trade",
                "account_label": "sub-1",
                "environment": "demo",
            },
        ]
    }
    ok = spec["paths"][_CONTRACT]["get"]["responses"]["200"]["content"]["application/json"]
    assert _errors(spec, ok["schema"], r.json()) == []  # and never a `granted_at`, as above
    assert store.calls == [TARGET]  # no step-up wiring is needed: a read


def test_get_missing_or_deleted_user_404(spec: dict[str, Any]) -> None:
    store, em = _Store({TARGET: []}, deleted=frozenset({DELETED})), _Emitter()
    c = _client(store, _principal("owner", spec), em)
    missing, deleted = c.get(_PATH.format(MISSING)), c.get(_PATH.format(DELETED))
    assert missing.status_code == deleted.status_code == 404
    assert missing.json() == deleted.json()  # one body: a deleted user cannot be told from none
    assert missing.json()["code"] == "not_found"
    assert str(MISSING) not in missing.text and str(DELETED) not in deleted.text
    assert em.calls == []  # a 404 for the owner is not a denial


def test_get_never_returns_another_users_grants(spec: dict[str, Any]) -> None:
    store = _Store(
        {
            TARGET: [_grant(_A, "trade")],
            OTHER: [_grant(_B, "read")],
            CALLER: [_grant(_C, "read")],  # the caller's own grants are not the target's
            EMPTY: [],  # a user without grants lists nothing
        }
    )
    c = _client(store, _principal("owner", spec))

    def listed(user: uuid.UUID) -> list[str]:
        return [i["exchange_account_id"] for i in c.get(_PATH.format(user)).json()["items"]]

    assert listed(TARGET) == [str(_A)] and listed(OTHER) == [str(_B)] and listed(EMPTY) == []
    assert store.calls == [TARGET, OTHER, EMPTY]  # only the path's user was ever read


_HELD = (AccountGrant(_A, True, True, False),)


@pytest.mark.parametrize(
    ("role", "grants", "target"),
    [
        ("manager", (), TARGET),
        ("manager", _HELD, TARGET),
        ("viewer", (), TARGET),
        ("manager", _HELD, CALLER),  # a manager's own grants are read through /auth/session
    ],
    ids=["manager-without-grant", "manager-with-grant", "viewer", "manager-own-id"],
)
def test_get_forbidden_manager_viewer_audited(
    role: str, grants: tuple[AccountGrant, ...], target: uuid.UUID, spec: dict[str, Any]
) -> None:
    store, em = _Store({TARGET: [_grant(_A)], CALLER: [_grant(_A)]}), _Emitter()
    before = _users_read_denied()
    r = _client(store, _principal(role, spec, grants), em).get(_PATH.format(target))
    assert r.status_code == 403 and r.json()["code"] == "forbidden"
    assert store.calls == []  # nothing is looked up for a refused caller
    (record,) = em.calls  # one record for the one attempt, naming whom it was for
    assert record["action"] == "rbac.denied" and record["actor_user_id"] == CALLER
    assert (record["object_kind"], record["object_id"]) == ("user", str(target))
    assert "users:read" in record["reason"]
    assert _users_read_denied() == before + 1  # SR-125: counted with the audit row


@pytest.mark.parametrize(
    "error",
    [
        AuditUnavailable("audit WAL unavailable: OSError"),
        AuditWriterStopped(),
        RuntimeError("audit not started"),
    ],
    ids=["wal-unavailable", "writer-stopped", "audit-not-started"],
)
def test_get_refusal_that_cannot_be_audited_is_503_audit_unavailable(
    error: Exception, spec: dict[str, Any]
) -> None:
    """A refused caller whose `rbac.denied` record cannot be written is not told `403`: nothing
    is looked up, and no traceback is logged for it."""
    store, before = _Store({TARGET: [_grant(_A)]}), _users_read_denied()
    with capture_logs() as logs:
        r = _client(store, _principal("manager", spec), _Emitter(error)).get(_PATH.format(TARGET))
    assert r.status_code == 503 and r.json()["code"] == "audit_unavailable"
    assert r.headers["Retry-After"] == str(r.json()["retry_after_seconds"])
    assert str(error) not in r.text and store.calls == []
    assert _users_read_denied() == before + 1  # SR-125: counted before the write
    assert [e["log_level"] for e in logs] == ["warning"] and "exc_info" not in logs[0]


def test_get_403_is_identical_for_existing_and_missing_users(spec: dict[str, Any]) -> None:
    """Threat U25: a manager cannot tell an id that exists from one that does not (only the
    contract's request id, if any, may differ)."""
    store = _Store({TARGET: [_grant(_A)]})
    c = _client(store, _principal("manager", spec))
    existing, missing = c.get(_PATH.format(TARGET)), c.get(_PATH.format(MISSING))
    assert existing.status_code == missing.status_code == 403

    def body(r: Any) -> dict[str, Any]:
        return {k: v for k, v in r.json().items() if k not in ("instance", "request_id")}

    assert body(existing) == body(missing) and store.calls == []


def test_get_unauthenticated_is_401_and_never_reaches_the_store() -> None:
    store, em = _Store({TARGET: [_grant(_A)]}), _Emitter()
    r = _client(store, None, em).get(_PATH.format(TARGET))
    assert r.status_code == 401 and r.json()["code"] == "unauthenticated"
    assert store.calls == [] and em.calls == []


def test_get_unwired_fails_closed_with_501(spec: dict[str, Any]) -> None:
    store = _Store({TARGET: []})
    assert _client(None, _principal("owner", spec)).get(_PATH.format(TARGET)).status_code == 501
    app = FastAPI()
    app.include_router(make_users_router(None, _Emitter(), None, _Notifier(), account_access=store))
    assert TestClient(app).get(_PATH.format(TARGET)).status_code == 501
    assert store.calls == []


@pytest.mark.parametrize(
    "error",
    [StorageQueryFailed("57P01"), ConnectionRefusedError("db at 10.1.2.3 refused")],
    ids=["driver-error", "connection-error"],
)
def test_get_store_failure_is_503_without_driver_text(
    error: Exception, spec: dict[str, Any]
) -> None:
    store = _Store({TARGET: []}, error=error)
    r = _client(store, _principal("owner", spec)).get(_PATH.format(TARGET))
    assert r.status_code == 503 and r.json()["code"] == "store_unavailable"
    assert r.headers["Retry-After"] == str(r.json()["retry_after_seconds"])
    assert "57P01" not in r.text and "10.1.2.3" not in r.text  # fixed detail, no driver text


def test_get_then_put_round_trips(spec: dict[str, Any]) -> None:
    """Each listed item, cut down to the two input fields, is a valid `PUT` body naming the listed
    grants, so sending it back is a no-op (the store's round trip: tests/unit/storage and the
    Postgres suite), but for a live grant on a soft-deleted account: it is not listed, so a `PUT`
    of the listing would revoke it (#3027). The read-only fields are not input."""
    held = [_grant(_A, "trade", "main", "live"), _grant(_B, "read", "sub-1", "demo", None)]
    c = _client(_Store({TARGET: held}), _principal("owner", spec))
    items = c.get(_PATH.format(TARGET)).json()["items"]
    inputs = [{"exchange_account_id": i["exchange_account_id"], "level": i["level"]} for i in items]
    request = spec["paths"][_CONTRACT]["put"]["requestBody"]["content"]["application/json"]
    assert _errors(spec, request["schema"], {"grants": inputs}) == []
    assert _errors(spec, request["schema"], {"grants": items}) != []  # closed: no account_label
    assert {g["exchange_account_id"]: g["level"] for g in inputs} == {
        str(g.exchange_account_id): g.level for g in held
    }
