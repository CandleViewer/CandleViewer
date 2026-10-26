"""Contract, provider side (#906 slice D1c): `listAccountProfiles` and `getAccountProfile` as the
app serves them. The world is the RBAC pack's real `create_app()` (no network, C-13.5) over one
fake of the account and profile reads, scoped as Postgres scopes them: an `OwnerScope` passes the
live-owner gate unless a test closes it, a `GrantScope` sees only its accounts (an empty one
nothing), and a profile is found only under its own account. Every answer is checked against
the operation's declared response (2020-12, format checker). `getAccountDefaultProfile` (#906
D2-6) is read the same way, the account's binding after the account.
"""

from __future__ import annotations

import dataclasses
import json
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy.exc import OperationalError
from structlog.testing import capture_logs

import candleviewer.app as appmod
from candleviewer.accounts.models import ExchangeEnv
from candleviewer.accounts.profile_repository import ProfilesRepository
from candleviewer.accounts.profiles import AccountProfile, profile_from_row, profile_values, to_us
from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.profile_projection import profile_document
from candleviewer.api.profiles import make_profiles_router
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.storage.errors import StorageQueryFailed, StorageTierUnavailable
from candleviewer.storage.repositories.account_profiles import AccountProfileRow, DefaultBindingRow
from candleviewer.storage.repositories.account_profiles import (
    AccountProfileStoreScopeDeniedError as ProfileGate,
)
from candleviewer.storage.repositories.accounts import AccountsStoreError, GrantScope, OwnerScope
from candleviewer.storage.repositories.accounts import AccountsStoreScopeDeniedError as AccountGate
from tests.contract._admin_support import SPEC, validate_example
from tests.contract.rbac.rbac_harness import (
    FOREIGN,
    GRANTED,
    World,
    bearer,
    build_world,
    session_id_of,
    user_id_of,
)
from tests.unit.accounts.test_key_import import account_row

LIST = "/exchange-accounts/{accountId}/profiles"
ITEM = LIST + "/{profileId}"
BINDING = "/exchange-accounts/{accountId}/default-profile"
#: An account found, then emptied: its profiles soft-deleted between the two reads (a race).
EMPTIED = uuid.UUID("00000000-0000-4000-8000-00000000000c")
#: Each account's environment. The server's is `demo`, so FOREIGN's is another environment's.
ENV = {GRANTED: "demo", FOREIGN: "live", EMPTIED: "testnet"}
#: A viewer stripped of every permission: the forbidden-role case.
BARE = PrincipalSnapshot(user_id_of("viewer"), frozenset({"viewer"}), frozenset())
_AT = datetime(2026, 10, 20, 9, tzinfo=UTC)
#: A row's last update, an hour after it was written: each stamp has one place in a document.
_LATER = _AT + timedelta(hours=1)
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "profiles"


def _row(fixture: str, account: uuid.UUID, n: int, **changes: Any) -> AccountProfileRow:
    """The fixture re-homed onto `account` as profile `n`, its row written at `_AT` and updated
    at `_LATER`."""
    raw = json.loads((_FIXTURES / f"{fixture}.json").read_text(encoding="utf-8"))
    ids = {"profile_id": uuid.UUID(int=n), "account_id": account}
    p = AccountProfile.model_validate({**raw, **changes, **ids})
    return AccountProfileRow(
        id=p.profile_id, exchange_account_id=account, version=p.version, values=profile_values(p),
        created_by=None, updated_by=None, created_at=_AT, updated_at=_LATER, deleted_at=None,
    )  # fmt: skip


class _Cancelled(Exception):
    """A driver's `query_canceled` (a statement timeout), its SQLSTATE where asyncpg names it."""

    sqlstate = "57014"


class Store:
    """The reads as Postgres scopes them (module docstring). `seen` holds each read's kind
    (`account`, `profiles`, `binding`) and scope; `gated` the kinds whose live-owner gate refuses
    an Owner; `fails` an error per kind; `bindings` each account's binding version (0d-2)."""

    def __init__(self) -> None:
        alternate = _row("pct_equity", GRANTED, 2, is_default=False, name="Alt")
        self.rows = {
            GRANTED: (_row("risk_based", GRANTED, 1), alternate),
            FOREIGN: (_row("fixed_notional", FOREIGN, 3),),
            EMPTIED: (),
        }
        self.seen: list[tuple[str, object]] = []
        self.gated: set[str] = set()
        self.fails: dict[str, Exception] = {}
        self.bindings = dict.fromkeys(self.rows, 1)

    def _shown(self, kind: str, scope: Any, account_id: uuid.UUID) -> bool:
        self.seen.append((kind, scope))
        if kind in self.fails:
            raise self.fails[kind]
        if not isinstance(scope, OwnerScope):
            return account_id in scope.account_ids and account_id in self.rows
        if kind in self.gated:  # the live-owner gate (SR-051)
            raise AccountGate if kind == "account" else ProfileGate
        return account_id in self.rows

    async def get_account(self, scope: Any, account_id: uuid.UUID) -> Any:
        if not self._shown("account", scope, account_id):
            return None
        return dataclasses.replace(account_row(ENV[account_id]), id=account_id)

    async def list_profiles(self, scope: Any, account_id: uuid.UUID) -> Any:
        return self.rows[account_id] if self._shown("profiles", scope, account_id) else ()

    async def get_profile(self, scope: Any, account_id: uuid.UUID, profile_id: uuid.UUID) -> Any:
        rows = self.rows[account_id] if self._shown("profiles", scope, account_id) else ()
        return next((r for r in rows if r.id == profile_id), None)

    async def get_default_binding(self, scope: Any, account_id: uuid.UUID) -> Any:
        rows = self.rows[account_id] if self._shown("binding", scope, account_id) else ()
        found = [r.id for r in rows if r.values.is_default]  # none: no live default (EMPTIED)
        return DefaultBindingRow(account_id, found[0], self.bindings[account_id]) if found else None


Served = tuple[World, Store]


@pytest.fixture(scope="module")
def _served() -> Iterator[Served]:
    store, mp = Store(), pytest.MonkeyPatch()
    # `effective` is the order path's cache, which the OMS runtime is handed; no read uses it.
    repository = ProfilesRepository(cast(Any, store), cache=None)
    wiring = SimpleNamespace(repository=repository, effective=None)
    try:
        mp.setattr(appmod, "wire_profiles", lambda *_args: wiring)
        mp.setattr(appmod, "_build_accounts_counts", lambda _settings: store)  # the M13 store
        yield build_world(mp), store
    finally:
        mp.undo()


@pytest.fixture
def served(_served: Served) -> Served:
    world, store = _served
    world.audit.records.clear()
    store.seen.clear()
    store.gated.clear()
    store.fails.clear()
    return world, store


def read(world: World, actor: str, account: Any, profile: Any = None, **query: str) -> Any:
    path = f"/exchange-accounts/{account}/profiles" + ("" if profile is None else f"/{profile}")
    return world.client.get(path, params=query, headers=bearer(actor))


def answer(resp: Any, *, item: bool = False, path: str | None = None) -> Any:
    """The body, once it validates against what the operation declares for its status."""
    path, status = path or (ITEM if item else LIST), resp.status_code
    declared = SPEC["paths"][path]["get"]["responses"][str(status)]
    own = "#/paths/" + path.replace("/", "~1") + f"/get/responses/{status}"
    pointer = declared.get("$ref", own)
    media = "application~1json" if status == 200 else "application~1problem+json"
    validate_example(f"{pointer.removeprefix('#')}/content/{media}/schema", resp.json())
    return resp.json()


def _scope(actor: str) -> object:
    """The scope a read of `actor` runs in, built here rather than by `account_scope`."""
    uid = user_id_of(actor)
    if actor == "owner":
        return OwnerScope(uid)
    return GrantScope(uid, frozenset({GRANTED} if actor == "manager_with_grant" else ()))


def _denied(record: dict[str, Any], resp: Any, actor: str, reason: str) -> None:
    """`rbac.denied` naming the account, the actor, its session (#4174) and the request: a denied
    warning labelled with the actor's id, as `enforce` writes it."""
    named = (
        "action", "object_kind", "object_id", "reason", "actor_user_id", "session_id", "outcome",
        "severity", "actor_label",
    )  # fmt: skip
    assert [record[key] for key in named] == [
        "rbac.denied", "exchange_account", str(GRANTED), reason, user_id_of(actor),
        session_id_of(actor), "denied", "warning", str(user_id_of(actor)),
    ]  # fmt: skip
    assert str(record["request_id"]) == resp.headers["x-correlation-id"]


def _denials() -> float:
    """`authz_denied_total{permission="accounts:read"}` (SR-125): a test asserts its delta."""
    return REGISTRY.get_sample_value("authz_denied_total", {"permission": "accounts:read"}) or 0.0


@pytest.mark.parametrize(
    ("actor", "account", "status"),
    [
        ("owner", GRANTED, 200),
        ("owner", FOREIGN, 200),  # a live account on a demo server, answered (16:00Z ruling 3)
        ("manager_with_grant", GRANTED, 200),
        ("manager_with_grant", FOREIGN, 404),
        ("manager_without_grant", GRANTED, 404),
        ("viewer", GRANTED, 404),
        ("unauthenticated", GRANTED, 401),
    ],
)
def test_each_actor_reads_exactly_the_accounts_its_scope_holds(
    served: Served, actor: str, account: uuid.UUID, status: int
) -> None:
    """Each read resolves the account first, then its profiles, both in the caller's scope; an
    answer carries the account's environment, never the server's. Both are served on the literal
    templates: no path convertor under the prefix lets an `a/b` id slip a row (#4087 R1S-01)."""
    world, store = served
    ops = served_operations(world.app)
    assert {("GET", LIST), ("GET", ITEM)} <= ops
    assert not [path for _, path in ops if path.startswith("/exchange-accounts/") and ":" in path]
    sent = read(world, actor, account), read(world, actor, account, store.rows[account][0].id)
    assert [r.status_code for r in sent] == [status, status], sent[0].text
    listed, got = answer(sent[0], item=False), answer(sent[1], item=True)
    if status == 200:
        assert {doc["environment"] for doc in [*listed["items"], got]} == {ENV[account]}
    kinds = {200: ["account", "profiles"] * 2, 404: ["account"] * 2, 401: []}[status]
    assert store.seen == [(kind, _scope(actor)) for kind in kinds]


def test_an_account_outside_the_grants_answers_as_one_that_does_not_exist(served: Served) -> None:
    """PF-I06: an account outside the grants, a missing one and one emptied by a soft delete
    between the two reads are one 404, the same body for every caller and cause, unaudited."""
    world, _ = served
    nowhere = uuid.uuid4()
    sent = [
        read(world, "manager_with_grant", FOREIGN),
        read(world, "manager_with_grant", nowhere),
        read(world, "viewer", GRANTED),
        read(world, "owner", nowhere),
        read(world, "owner", EMPTIED),
    ]
    assert {(r.status_code, r.text) for r in sent} == {(404, sent[0].text)}
    assert answer(sent[0], item=False)["detail"] == "No such exchange account."
    assert world.audit.records == []


def test_a_profile_is_read_only_through_its_own_account(served: Served) -> None:
    """IDOR: another account's profile under one the caller reads (the Owner too), a missing
    profile, one outside the grants and one of a missing or emptied account: one 404."""
    world, store = served
    theirs, mine = store.rows[FOREIGN][0].id, store.rows[GRANTED][0].id
    sent = [
        read(world, "manager_with_grant", GRANTED, theirs),
        read(world, "owner", GRANTED, theirs),
        read(world, "manager_with_grant", GRANTED, uuid.uuid4()),
        read(world, "manager_with_grant", FOREIGN, theirs),
        read(world, "owner", uuid.uuid4(), mine),
        read(world, "owner", EMPTIED, mine),
    ]
    assert {(r.status_code, r.text) for r in sent} == {(404, sent[0].text)}
    assert answer(sent[0], item=True)["detail"] == "No such profile."
    assert world.audit.records == []


def test_a_profile_answers_its_document_with_its_weak_etag(served: Served) -> None:
    world, store = served
    row = store.rows[FOREIGN][0]
    resp = read(world, "owner", FOREIGN, row.id)
    live = ExchangeEnv.LIVE  # the account's, not the server's
    want = profile_document(profile_from_row(row), created_at=to_us(_AT), environment=live)
    assert answer(resp, item=True) == want
    etag = resp.headers["etag"]
    assert etag == f'W/"{row.id}:{row.version}"'
    assert re.fullmatch(SPEC["components"]["headers"]["ProfileETag"]["schema"]["pattern"], etag)
    assert "idempotency-replayed" not in resp.headers


def test_the_list_is_one_page_in_the_stores_order_and_carries_no_etag(served: Served) -> None:
    world, store = served
    demo = ExchangeEnv.DEMO
    docs = [
        profile_document(profile_from_row(r), created_at=to_us(_AT), environment=demo)
        for r in store.rows[GRANTED]
    ]
    resp = read(world, "manager_with_grant", GRANTED)
    body = answer(resp, item=False)
    assert body == {"items": docs}
    assert [doc["profile"]["is_default"] for doc in body["items"]] == [True, False]
    assert read(world, "manager_with_grant", GRANTED, cursor="x", limit="1").json() == body
    assert "etag" not in resp.headers


def test_a_caller_without_accounts_read_is_403_audited_and_never_reaches_the_store(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The forbidden-role case, on both reads. Each refusal's record is written, so none is logged
    as an unaudited refusal."""
    world, store = served
    monkeypatch.setattr(world.resolver, "snapshot", lambda _actor: BARE)
    reason = "missing_permission:accounts:read:none"
    with capture_logs() as logs:
        for item, profile in ((False, None), (True, store.rows[GRANTED][0].id)):
            resp = read(world, "viewer", GRANTED, profile)
            assert resp.status_code == 403
            assert answer(resp, item=item)["required_permissions"] == ["accounts:read"]
            _denied(world.audit.records.pop(), resp, "viewer", reason)
    assert (world.audit.records, store.seen) == ([], [])
    assert not [log for log in logs if log["event"] == "profile_read_denial_unaudited"]


@pytest.mark.parametrize(
    ("item", "gated"),
    [(False, "account"), (False, "profiles"), (True, "account"), (True, "profiles")],
)
def test_the_stores_owner_gate_refusing_an_owner_is_403_and_audited(
    served: Served, item: bool, gated: str
) -> None:
    """SR-051: either store's live-owner gate refuses an Owner `enforce` let through (the role
    removed in between): a 403, counted, then `rbac.denied` in `enforce`'s reason shape."""
    world, store = served
    store.gated.add(gated)
    before = _denials()
    resp = read(world, "owner", GRANTED, store.rows[GRANTED][0].id if item else None)
    assert resp.status_code == 403
    assert answer(resp, item=item)["required_permissions"] == ["accounts:read"]
    (record,) = world.audit.records
    _denied(record, resp, "owner", "not_owner:accounts:read:granted_accounts")
    assert (record["actor_ip"], _denials()) == ("127.0.0.1", before + 1)


@pytest.mark.parametrize("error", [RuntimeError, AuditUnavailable])
def test_a_refusal_whose_record_cannot_be_written_still_refuses(
    served: Served, monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    """A read never answers on an audit record: the owner gate's refusal and `enforce`'s stay 403
    when their record fails (the writer not started, or its WAL unwritable), each logged by ids
    and class only."""
    world, store = served

    async def down(*_args: Any, **_kwargs: Any) -> None:
        raise error("the record was not written")

    monkeypatch.setattr(world.audit, "emit", down)
    store.gated.add("account")
    with capture_logs() as logs:
        gated = read(world, "owner", GRANTED)
        monkeypatch.setattr(world.resolver, "snapshot", lambda _actor: BARE)
        bare = read(world, "viewer", GRANTED)
    assert [gated.status_code, bare.status_code] == [403, 403]
    assert [log for log in logs if log["event"] == "profile_read_denial_unaudited"] == [
        {"event": "profile_read_denial_unaudited", "log_level": "warning",
         "actor_user_id": str(user_id_of(actor)), "account_id": str(GRANTED),
         "error": error.__name__}
        for actor in ("owner", "viewer")
    ]  # fmt: skip


@pytest.mark.parametrize("item", [False, True], ids=["list", "get"])
@pytest.mark.parametrize(
    ("kind", "error", "logged", "sqlstate"),
    [
        ("account", ConnectionRefusedError(), "ConnectionRefusedError", None),  # the driver's
        ("account", OperationalError("SELECT 1", {}, _Cancelled()), "OperationalError", "57014"),
        ("account", AccountsStoreError(), "AccountsError", None),
        ("profiles", StorageTierUnavailable("down"), "StorageTierUnavailable", None),
        ("profiles", StorageQueryFailed("57014"), "StorageQueryFailed", "57014"),  # a timeout
        ("row", None, "ProfileUnavailableError", None),  # a stored row the model refuses
    ],
)
def test_a_store_that_cannot_answer_is_503_with_retry_after(
    served: Served, monkeypatch: pytest.MonkeyPatch,
    item: bool, kind: str, error: Exception | None, logged: str, sqlstate: str | None,
) -> None:  # fmt: skip
    world, store = served
    if error is None:  # lower case: the model refuses it, so it is never answered as stored
        row = store.rows[GRANTED][0]
        bad = dataclasses.replace(row.values, allowed_symbols=("btcusdt",))
        monkeypatch.setitem(store.rows, GRANTED, (dataclasses.replace(row, values=bad),))
    else:
        store.fails[kind] = error
    with capture_logs() as logs:
        resp = read(world, "owner", GRANTED, store.rows[GRANTED][0].id if item else None)
    body = answer(resp, item=item)
    assert (resp.status_code, body["code"], body["detail"]) == (
        503, "store_unavailable", "The profile store is unavailable.",
    )  # fmt: skip
    assert (body["retry_after_seconds"], resp.headers["retry-after"]) == (5, "5")
    assert [log for log in logs if log["event"] == "profile_read_unavailable"] == [
        {"event": "profile_read_unavailable", "log_level": "warning", "error": logged,
         "sqlstate": sqlstate},
    ]  # fmt: skip


def test_an_error_that_is_no_outage_is_a_500(served: Served) -> None:
    """A defect fails visibly: never a 404, nor a 503 a client would retry; and the app's handler
    answers it without the error's text (C-12.6)."""
    world, store = served
    store.fails["account"] = TypeError("a defect")
    resp = read(world, "owner", GRANTED)
    assert (resp.status_code, resp.json()["code"]) == (500, "internal_error")
    assert "defect" not in resp.text


@pytest.mark.parametrize("wired", ["neither", "profiles", "accounts"])
def test_without_a_store_the_reads_are_503_after_the_same_checks(
    served: Served, monkeypatch: pytest.MonkeyPatch, wired: str
) -> None:
    """The fake backend wires no store, and one reader alone is none: an admitted caller gets 503,
    a caller without `accounts:read` still 403, and with no resolver wired every call is 501."""
    world, store = served
    reads = ProfilesRepository(cast(Any, store), cache=None) if wired == "profiles" else None
    accounts = store if wired == "accounts" else None

    def client(resolver: Any) -> TestClient:
        app = FastAPI()
        app.include_router(make_profiles_router(reads, accounts, world.audit, resolver))
        return TestClient(app)

    storeless, path = client(world.resolver), f"/exchange-accounts/{GRANTED}/profiles"
    for item, sent in ((False, path), (True, f"{path}/{uuid.uuid4()}")):
        resp = storeless.get(sent, headers=bearer("owner"))
        detail = answer(resp, item=item)["detail"]
        assert (resp.status_code, detail) == (503, "Profiles are not available on this backend.")
        assert resp.headers["retry-after"] == "5"
        assert client(None).get(sent, headers=bearer("owner")).status_code == 501
    monkeypatch.setattr(world.resolver, "snapshot", lambda _actor: BARE)
    assert storeless.get(path, headers=bearer("viewer")).status_code == 403
    assert store.seen == []  # a reader wired alone is never read


def test_the_binding_reads_as_its_profile_and_version_with_its_tag(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#906 D2-6, `getAccountDefaultProfile`: the account first, in the caller's scope, for the
    environment its answer carries (no read checks it), then its binding: the default profile and
    the binding's version, which the weak `ETag` names, never the profile. A miss is the account's
    one 404, unaudited (PF-I06); the store's owner gate is 403, recorded; an outage 503."""
    world, store = served
    monkeypatch.setitem(store.bindings, FOREIGN, 7)

    def get(actor: str, account: object) -> Any:
        return world.client.get(BINDING.format(accountId=account), headers=bearer(actor))

    resp, theirs = get("owner", FOREIGN), store.rows[FOREIGN][0].id
    want = {"exchange_account_id": str(FOREIGN), "environment": "live", "profile_id": str(theirs)}
    assert (resp.status_code, answer(resp, path=BINDING)) == (200, want | {"version": 7})
    tag = resp.headers["etag"]
    assert tag == f'W/"{FOREIGN}:default:7"'
    assert re.fullmatch(
        SPEC["components"]["headers"]["DefaultBindingETag"]["schema"]["pattern"], tag
    )
    owner = OwnerScope(user_id_of("owner"))
    assert store.seen == [("account", owner), ("binding", owner)]
    missed = [get("manager_with_grant", FOREIGN), get("viewer", GRANTED)]
    missed += [get("owner", uuid.uuid4()), get("owner", EMPTIED)]  # EMPTIED: no live default
    assert {(r.status_code, r.text) for r in missed} == {(404, missed[0].text)}
    assert answer(missed[0], path=BINDING)["detail"] == "No such exchange account."
    assert world.audit.records == []
    store.gated.add("binding")
    gated = get("owner", GRANTED)
    _denied(world.audit.records.pop(), gated, "owner", "not_owner:accounts:read:granted_accounts")
    store.gated.clear()
    store.fails["binding"] = StorageTierUnavailable("down")
    down = get("owner", GRANTED)
    assert (down.status_code, answer(down, path=BINDING)["code"]) == (503, "store_unavailable")
