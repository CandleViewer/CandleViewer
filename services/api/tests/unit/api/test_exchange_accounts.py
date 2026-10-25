"""The account routes (#895, E27-S01 backend slice) on a bare app: the edges the provider test
does not reach (no resolver, no store, an unwritten refusal, the write-ahead bound, the store's
other refusals and outages), the cursor codec, the status merge, and the path guard's `keys`
step-up on `createExchangeAccount` before its handler runs (SR-E27-02)."""

from __future__ import annotations

import base64
import dataclasses
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from candleviewer.accounts.health import AccountHealth, HealthState
from candleviewer.accounts.models import ExchangeAccount
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.accounts.status import AccountStatusReader
from candleviewer.api.exchange_accounts import (
    CURSOR_TTL_S,
    account_document,
    decode_cursor,
    encode_cursor,
    make_exchange_accounts_router,
)
from candleviewer.audit.errors import AuditError
from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.storage.errors import StorageTierUnavailable, WriteAheadTimeout
from candleviewer.storage.repositories.accounts import (
    AccountKey,
    AccountsPage,
    AccountsStoreConflictError,
    AccountsStoreRuleError,
    AccountsStoreScopeDeniedError,
    AccountWriteAhead,
    NewExchangeAccount,
)
from tests.unit.accounts.test_key_import import account_row
from tests.unit.api.test_step_up_router import _H, _build

OWNER = PrincipalSnapshot(
    uuid.uuid4(), frozenset({"owner"}),
    frozenset({Permission.ACCOUNTS_READ, Permission.ACCOUNTS_WRITE}),
)  # fmt: skip
BODY = {"exchange": "bybit", "environment": "demo", "kind": "main", "label": "Main",
        "exchange_uid": "10234567"}  # fmt: skip
NOW = datetime(2026, 10, 25, 9, tzinfo=UTC)


class _Resolver:
    def __init__(self, principal: PrincipalSnapshot | None = OWNER) -> None:
        self.principal = principal

    def resolve(self, _request: Any) -> PrincipalSnapshot | None:
        return self.principal


class _Audit:
    def __init__(self, fails: Exception | None = None) -> None:
        self.records: list[dict[str, Any]] = []
        self.fails = fails

    async def emit(self, action: str, **kw: Any) -> None:
        if self.fails is not None:
            raise self.fails
        self.records.append({"action": action, **kw})


class _Store:
    """`create_account` raises `fails` or runs the hook; `list_accounts` raises `list_fails`."""

    def __init__(self) -> None:
        self.fails: Exception | None = None
        self.list_fails: Exception | None = None
        self.rows = [dataclasses.replace(account_row("demo"), label="Main", exchange_uid="1000001")]

    async def create_account(
        self, _scope: Any, new: NewExchangeAccount, *, write_ahead: AccountWriteAhead | None = None
    ) -> Any:
        if self.fails is not None:
            raise self.fails
        row = dataclasses.replace(account_row(new.env), id=new.id, label=new.label)
        if write_ahead is not None:
            await write_ahead(row)
        return row

    async def list_accounts(self, _scope: Any, **_kw: Any) -> AccountsPage[Any]:
        if self.list_fails is not None:
            raise self.list_fails
        return AccountsPage(tuple(self.rows), None)


_DEFAULT = _Resolver()


def _client(
    store: _Store | None, audit: _Audit, resolver: _Resolver | None = _DEFAULT, **kw: Any
) -> TestClient:
    app = FastAPI()
    # `_Store` is a structural fake of the `AccountsStore` port: only the two calls used here.
    accounts = None if store is None else AccountsRepository(store)  # type: ignore[arg-type]
    router = make_exchange_accounts_router(accounts, audit, resolver, environment="demo", **kw)
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_without_a_resolver_every_call_is_501_and_without_a_session_401() -> None:
    unwired = _client(_Store(), _Audit(), None)
    assert unwired.get("/exchange-accounts").status_code == 501
    assert unwired.post("/exchange-accounts", json=BODY).status_code == 501
    anon = _client(_Store(), _Audit(), _Resolver(None))
    assert anon.get("/exchange-accounts").status_code == 401
    assert anon.post("/exchange-accounts", json=BODY).status_code == 401
    assert _client(_Store(), _Audit()).get("/exchange-accounts").status_code == 200


def test_without_a_store_an_admitted_caller_gets_503() -> None:
    client = _client(None, _Audit())
    for resp in (client.get("/exchange-accounts"), client.post("/exchange-accounts", json=BODY)):
        assert (resp.status_code, resp.json()["code"]) == (503, "store_unavailable")


def test_a_write_refusal_whose_record_fails_is_503_and_a_read_refusal_stays_403() -> None:
    viewer = PrincipalSnapshot(uuid.uuid4(), frozenset({"viewer"}), frozenset())
    client = _client(_Store(), _Audit(fails=AuditError("down")), _Resolver(viewer))
    with capture_logs() as logs:
        read, write = client.get("/exchange-accounts"), client.post("/exchange-accounts", json=BODY)
    assert (read.status_code, write.status_code) == (403, 503)
    assert write.json()["code"] == "audit_unavailable"
    assert [log["event"] for log in logs] == ["account_denial_unaudited"]


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (WriteAheadTimeout("bound"), 503, "audit_unavailable"),
        (AccountsStoreConflictError("ux_ea_label"), 409, "conflict"),
        (AccountsStoreConflictError("exchange_accounts_pkey"), 409, "conflict"),
        (AccountsStoreConflictError("sub_account_cap"), 409, "conflict"),
        (AccountsStoreRuleError("ea_uid_fmt"), 422, "validation_failed"),
        (StorageTierUnavailable("down"), 503, "store_unavailable"),
    ],
)
def test_each_refusal_of_the_store_maps_to_its_problem(
    error: Exception, status: int, code: str
) -> None:
    store, audit = _Store(), _Audit()
    store.fails = error
    resp = _client(store, audit).post("/exchange-accounts", json=BODY)
    assert (resp.status_code, resp.json()["code"]) == (status, code)
    assert audit.records == []


def test_a_gate_refusal_whose_record_fails_is_still_403_and_logged() -> None:
    store, audit = _Store(), _Audit(fails=AuditError("down"))
    store.fails = AccountsStoreScopeDeniedError()
    with capture_logs() as logs:
        resp = _client(store, audit).post("/exchange-accounts", json=BODY)
    assert (resp.status_code, resp.json()["code"]) == (403, "forbidden")
    assert [log["event"] for log in logs] == ["account_denial_unaudited"]


def test_a_defect_in_the_store_is_a_500_not_an_outage() -> None:
    store = _Store()
    store.fails = TypeError("a defect")
    assert _client(store, _Audit()).post("/exchange-accounts", json=BODY).status_code == 500
    store.fails, store.list_fails = None, TypeError("a defect")
    assert _client(store, _Audit()).get("/exchange-accounts").status_code == 500


def test_a_uid_conflict_whose_holder_cannot_be_read_still_answers_409() -> None:
    store = _Store()
    store.fails = AccountsStoreConflictError("ux_ea_uid")
    store.list_fails = StorageTierUnavailable("down")
    resp = _client(store, _Audit()).post("/exchange-accounts", json=BODY)
    assert (resp.status_code, resp.json()["detail"]) == (409, "This UID is already registered.")
    store.list_fails = None  # read, but no account holds the UID any more (a race)
    resp = _client(store, _Audit()).post("/exchange-accounts", json=BODY)
    assert resp.json()["detail"] == "This UID is already registered."


def test_a_defect_while_reading_the_uid_holder_is_a_500_not_a_plain_conflict() -> None:
    store = _Store()
    store.fails = AccountsStoreConflictError("ux_ea_uid")
    store.list_fails = TypeError("a defect")
    assert _client(store, _Audit()).post("/exchange-accounts", json=BODY).status_code == 500


def test_a_list_store_outage_is_503_logged_by_class() -> None:
    store = _Store()
    store.list_fails = StorageTierUnavailable("down")
    with capture_logs() as logs:
        resp = _client(store, _Audit()).get("/exchange-accounts")
    assert (resp.status_code, resp.headers["retry-after"]) == (503, "5")
    assert [log["error"] for log in logs] == ["StorageTierUnavailable"]


def test_the_cursor_is_bound_to_its_caller_filters_and_hour() -> None:
    owner, at = uuid.uuid4(), AccountKey(NOW, uuid.uuid4())
    issued = int(NOW.timestamp())
    cursor = encode_cursor(owner, ["demo", None], at, issued)
    assert decode_cursor(cursor, owner, ["demo", None], issued + CURSOR_TTL_S) == at
    assert decode_cursor(cursor, owner, ["demo", None], issued + CURSOR_TTL_S + 1) is None
    assert decode_cursor(cursor, owner, ["demo", None], issued - 1) is None  # from the future
    assert decode_cursor(cursor, uuid.uuid4(), ["demo", None], issued) is None
    assert decode_cursor(cursor, owner, [None, None], issued) is None
    assert decode_cursor("x" * 513, owner, ["demo", None], issued) is None
    odd = base64.urlsafe_b64encode(json.dumps(["not", "a", "dict"]).encode()).decode()
    assert decode_cursor(odd, owner, ["demo", None], issued) is None
    naive = encode_cursor(owner, [], AccountKey(NOW.replace(tzinfo=None), at.id), issued)
    assert decode_cursor(naive, owner, [], issued) is None


def test_an_expired_cursor_is_400_on_the_route() -> None:
    clock = [NOW]
    client = _client(_Store(), _Audit(), clock=lambda: clock[0])
    cursor = encode_cursor(OWNER.user_id, [None, None], AccountKey(NOW, uuid.uuid4()), 0)
    resp = client.get("/exchange-accounts", params={"cursor": cursor})
    assert (resp.status_code, resp.json()["code"]) == (400, "invalid_cursor")


class _Views:
    def __init__(self, health: AccountHealth | None) -> None:
        self.health = health

    def view(self, _account_id: uuid.UUID) -> Any:
        return self.health


def test_an_item_merges_the_monitors_view_and_a_disabled_account_says_so() -> None:
    health = AccountHealth(
        state=HealthState.DEGRADED, reason="rest_only", heartbeat_age_ms=None, rest_only=True,
        changed_at=NOW - timedelta(seconds=5),
    )  # fmt: skip
    account = ExchangeAccount.model_validate(account_row("demo"), from_attributes=True)
    reader = AccountStatusReader(_Views(health), _Views(None))
    doc = account_document(account, reader)
    assert (doc["connection_state"], doc["health"]["state"]) == ("degraded", "degraded")
    off = account.model_copy(update={"is_enabled": False})
    assert account_document(off, None)["connection_state"] == "disabled"
    assert account_document(off, reader)["connection_state"] == "disabled"
    assert "key_status" not in doc and doc["created_at"].endswith("Z")


async def test_a_create_without_step_up_is_refused_by_the_path_guard_with_keys() -> None:
    """SR-E27-02: the row in `DANGEROUS_ROUTES` refuses before the handler; a list passes."""
    c, em, *_ = await _build()
    reached: list[str] = []

    async def stand_in() -> dict[str, bool]:
        reached.append("ran")
        return {"ok": True}

    app = c.app
    assert isinstance(app, FastAPI)
    app.add_api_route("/exchange-accounts", stand_in, methods=["GET", "POST"])
    r = c.post("/exchange-accounts", headers=_H)
    assert (r.status_code, r.json()["code"], r.json()["action_class"]) == (
        403, "step_up_required", "keys",
    )  # fmt: skip
    assert [call["action"] for call in em.calls].count("auth.step_up_required") == 1
    assert reached == []
    assert c.get("/exchange-accounts", headers=_H).status_code == 200
