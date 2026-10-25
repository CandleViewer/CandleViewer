"""Contract, provider side (#895, E27-S01 backend slice): `listExchangeAccounts` and
`createExchangeAccount` as the app serves them. The world is the RBAC pack's real `create_app()`
(no network, C-13.5) over one fake M13 store scoped as Postgres scopes it: an `OwnerScope` passes
the live-owner gate unless a test closes it, a `GrantScope` sees only its accounts. Every answer
is checked against the operation's declared response (2020-12, format checker).
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from structlog.testing import capture_logs

import candleviewer.app as appmod
from candleviewer.api.deny_by_default import served_operations
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.auth.scopes import PrincipalSnapshot
from candleviewer.storage.repositories.accounts import (
    AccountKey,
    AccountsPage,
    AccountsStoreConflictError,
    AccountsStoreRuleError,
    AccountsStoreScopeDeniedError,
    AccountWriteAhead,
    ExchangeAccountRow,
    NewExchangeAccount,
    OwnerScope,
)
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

PATH = "/exchange-accounts"
#: The `subDemo` example's parent and body, on this server's environment (`demo`).
PARENT = uuid.UUID("a1000000-0000-4000-8000-000000000001")
SUB: dict[str, Any] = SPEC["paths"][PATH]["post"]["requestBody"]["content"]["application/json"][
    "examples"
]["subDemo"]["value"]
MAIN = {"exchange": "bybit", "environment": "demo", "kind": "main", "label": "Main",
        "exchange_uid": "10234567"}  # fmt: skip
#: A viewer stripped of every permission: the forbidden-role case.
BARE = PrincipalSnapshot(user_id_of("viewer"), frozenset({"viewer"}), frozenset())


class Store:
    """The M13 store as Postgres scopes it (module docstring). `seen` holds each call's kind and
    scope; `gated` closes the live-owner gate; `fails` raises on the next create."""

    def __init__(self) -> None:
        row = account_row("demo")
        self.rows = {
            GRANTED: dataclasses.replace(row, id=GRANTED, label="Granted", exchange_uid="1000001"),
            FOREIGN: dataclasses.replace(row, id=FOREIGN, label="Main", exchange_uid="10234567"),
            PARENT: dataclasses.replace(row, id=PARENT, label="Parent", exchange_uid="1000003"),
        }
        self.seen: list[tuple[str, object]] = []
        self.gated = False
        self.fails: Exception | None = None

    def _visible(self, scope: Any) -> list[ExchangeAccountRow]:
        if isinstance(scope, OwnerScope):
            if self.gated:
                raise AccountsStoreScopeDeniedError
            return list(self.rows.values())
        return [r for i, r in self.rows.items() if i in scope.account_ids]

    async def list_accounts(
        self, scope: Any, *, env: str | None, kind: str | None, after: AccountKey | None, limit: int
    ) -> AccountsPage[ExchangeAccountRow]:
        self.seen.append(("list", scope))
        rows = sorted(self._visible(scope), key=lambda r: (r.created_at, r.id))
        rows = [r for r in rows if env in (None, r.env) and kind in (None, r.kind)]
        if after is not None:
            rows = [r for r in rows if (r.created_at, r.id) > (after.created_at, after.id)]
        page = rows[:limit]
        nxt = AccountKey(page[-1].created_at, page[-1].id) if len(rows) > limit else None
        return AccountsPage(tuple(page), nxt)

    async def get_account(self, scope: Any, account_id: uuid.UUID) -> ExchangeAccountRow | None:
        return next((r for r in self._visible(scope) if r.id == account_id), None)

    async def create_account(
        self, scope: Any, new: NewExchangeAccount, *, write_ahead: AccountWriteAhead | None = None
    ) -> ExchangeAccountRow:
        self.seen.append(("create", scope))
        self._visible(scope)
        if self.fails is not None:
            raise self.fails
        row = dataclasses.replace(
            account_row(new.env), id=new.id, kind=new.kind, exchange_uid=new.exchange_uid,
            label=new.label, parent_account_id=new.parent_account_id, trading_enabled=False,
        )  # fmt: skip
        if write_ahead is not None:
            await write_ahead(row)
        self.rows[row.id] = row
        return row


Served = tuple[World, Store]


@pytest.fixture(scope="module")
def _served() -> Iterator[Served]:
    store, mp = Store(), pytest.MonkeyPatch()
    try:
        mp.setattr(appmod, "_build_accounts_counts", lambda _settings: store)  # the M13 store
        yield build_world(mp), store
    finally:
        mp.undo()


@pytest.fixture
def served(_served: Served) -> Iterator[Served]:
    world, store = _served
    world.audit.records.clear()
    store.seen.clear()
    store.gated, store.fails = False, None
    kept = dict(store.rows)
    yield world, store
    store.rows.clear()
    store.rows.update(kept)


def answer(resp: Any, method: str) -> Any:
    """The body, once it validates against what the operation declares for its status."""
    status = resp.status_code
    declared = SPEC["paths"][PATH][method]["responses"][str(status)]
    own = "#/paths/" + PATH.replace("/", "~1") + f"/{method}/responses/{status}"
    pointer = declared.get("$ref", own)
    media = "application~1json" if status < 400 else "application~1problem+json"
    validate_example(f"{pointer.removeprefix('#')}/content/{media}/schema", resp.json())
    return resp.json()


def create(world: World, body: Any, actor: str = "owner", key: str | None = None) -> Any:
    headers = bearer(actor) | ({} if key is None else {"Idempotency-Key": key})
    return world.client.post(PATH, json=body, headers=headers)


def listed(world: World, actor: str, **query: Any) -> Any:
    return world.client.get(PATH, params=query, headers=bearer(actor))


def test_both_operations_are_served_on_the_literal_path(served: Served) -> None:
    assert {("GET", PATH), ("POST", PATH)} <= served_operations(served[0].app)
    assert "accounts.create" in AUDIT_ACTIONS  # the registered name (SR-E27-09)


@pytest.mark.parametrize(
    ("actor", "ids"),
    [
        ("owner", {GRANTED, FOREIGN, PARENT}),
        ("manager_with_grant", {GRANTED}),  # only the granted account (KV7)
        ("manager_without_grant", set()),
        ("viewer", set()),
    ],
)
def test_each_actor_lists_exactly_the_accounts_its_scope_holds(
    served: Served, actor: str, ids: set[uuid.UUID]
) -> None:
    world, _ = served
    body = answer(listed(world, actor), "get")
    assert {uuid.UUID(item["id"]) for item in body["items"]} == ids
    assert body["meta"] == {"next_cursor": None, "has_more": False, "count": len(ids)}


def test_the_list_pages_through_its_cursor_and_a_foreign_cursor_is_refused(served: Served) -> None:
    world, _ = served
    first = answer(listed(world, "owner", limit=2), "get")
    assert (first["meta"]["count"], first["meta"]["has_more"]) == (2, True)
    cursor = first["meta"]["next_cursor"]
    rest = answer(listed(world, "owner", limit=2, cursor=cursor), "get")
    assert {i["id"] for i in first["items"]} | {i["id"] for i in rest["items"]} == {
        str(i) for i in (GRANTED, FOREIGN, PARENT)
    }
    assert rest["meta"]["next_cursor"] is None
    other = listed(world, "manager_with_grant", limit=2, cursor=cursor)  # another caller's
    filtered = listed(world, "owner", limit=2, cursor=cursor, kind="main")  # other filters
    for resp in (other, filtered, listed(world, "owner", cursor="not-a-cursor")):
        assert (resp.status_code, resp.json()["code"]) == (400, "invalid_cursor")


def test_an_item_carries_the_status_members_unless_the_balance_is_left_out(served: Served) -> None:
    world, _ = served
    (item,) = answer(listed(world, "manager_with_grant"), "get")["items"]
    assert item["connection_state"] == "pending"  # not monitored on this world
    assert (item["balance"], item["balance_stale"], item["health"]) == (None, False, None)
    (bare,) = answer(listed(world, "manager_with_grant", include_balance="false"), "get")["items"]
    assert not {"balance", "balance_stale", "balance_stale_since"} & set(bare)
    assert bare["exchange"] == "bybit" and bare["environment"] == "demo"


def test_a_caller_without_accounts_read_is_403_audited(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, store = served
    monkeypatch.setattr(world.resolver, "snapshot", lambda _actor: BARE)
    resp = listed(world, "viewer")
    assert answer(resp, "get")["required_permissions"] == ["accounts:read"]
    (record,) = world.audit.records
    assert (record["action"], record["reason"], record["session_id"]) == (
        "rbac.denied", "missing_permission:accounts:read:none", session_id_of("viewer"),
    )  # fmt: skip
    assert store.seen == []


def test_the_stores_owner_gate_refusing_an_owners_list_is_403_and_audited(served: Served) -> None:
    world, store = served
    store.gated = True
    resp = listed(world, "owner")
    assert (resp.status_code, answer(resp, "get")["code"]) == (403, "forbidden")
    (record,) = world.audit.records
    assert record["reason"] == "not_owner:accounts:read:granted_accounts"


def test_ac1_a_demo_sub_account_is_registered_with_its_record(served: Served) -> None:
    """AC "Add a sub-account": 201, the account as stored with no key; `accounts.create` written
    ahead, naming the Owner, the account and its UID and label, never a key."""
    world, store = served
    resp = create(world, SUB)
    got = answer(resp, "post")
    assert resp.status_code == 201
    assert {k: got[k] for k in SUB} == SUB
    assert (got["key_status"], got["connection_state"]) == ("missing", "pending")
    (record,) = world.audit.records
    assert (record["action"], record["object_kind"], record["object_id"]) == (
        "accounts.create", "exchange_account", got["id"],
    )  # fmt: skip
    assert record["actor_user_id"] == user_id_of("owner")
    assert record["after_state"]["exchange_uid"] == SUB["exchange_uid"]
    assert uuid.UUID(got["id"]) in store.rows


@pytest.mark.parametrize("actor", ["manager_with_grant", "manager_without_grant", "viewer"])
def test_no_role_but_the_owner_registers_an_account(served: Served, actor: str) -> None:
    """The forbidden-role and IDOR cases: a Manager, granted or not, and a Viewer get 403,
    audited, and reach no store."""
    world, store = served
    resp = create(world, MAIN, actor)
    assert answer(resp, "post")["required_permissions"] == ["accounts:write"]
    (record,) = world.audit.records
    assert record["reason"] == "missing_permission:accounts:write:none"
    assert store.seen == []


@pytest.mark.parametrize(
    ("body", "field", "rule"),
    [
        ({**SUB, "parent_account_id": None}, "parent_account_id", "required"),
        ({**MAIN, "parent_account_id": str(PARENT)}, "parent_account_id", "forbidden"),
        ({**MAIN, "environment": "live"}, "environment", "environment"),  # C-2.11
    ],
)
def test_a_shape_the_database_would_refuse_is_422_before_it(
    served: Served, body: dict[str, Any], field: str, rule: str
) -> None:
    world, store = served
    resp = create(world, body)
    got = answer(resp, "post")
    assert (resp.status_code, [(e["field"], e["rule"]) for e in got["errors"]]) == (
        422, [(field, rule)],
    )  # fmt: skip
    assert (store.seen, world.audit.records) == ([], [])


def test_a_closed_body_refuses_an_undeclared_member(served: Served) -> None:
    world, store = served
    resp = create(world, {**MAIN, "api_key": "x"})
    assert (resp.status_code, store.seen) == (422, [])


def test_ac2_a_duplicate_uid_is_409_naming_the_account_that_holds_it(served: Served) -> None:
    world, store = served
    store.fails = AccountsStoreConflictError("ux_ea_uid")
    resp = create(world, MAIN)
    assert (resp.status_code, answer(resp, "post")["detail"]) == (
        409, "This UID is already registered as Main.",
    )  # fmt: skip
    assert world.audit.records == []


def test_a_sixth_sub_under_one_parent_is_409_conflict_and_nothing_is_stored(
    served: Served,
) -> None:
    """22 createExchangeAccount: "the server rejects the 6th with `conflict`". The store refuses
    before its write-ahead, so, as for a taken UID or label, no `accounts.create` is written."""
    world, store = served
    store.fails = AccountsStoreConflictError("sub_account_cap")
    before = set(store.rows)
    resp = create(world, SUB)
    got = answer(resp, "post")
    assert (resp.status_code, got["code"], got["detail"]) == (
        409, "conflict",
        "The parent account already holds as many sub-accounts as its tier allows.",
    )  # fmt: skip
    assert (world.audit.records, set(store.rows)) == ([], before)


def test_a_parent_of_another_environment_or_kind_is_422(served: Served) -> None:
    world, store = served
    store.fails = AccountsStoreRuleError("parent_unavailable")
    resp = create(world, SUB)
    assert [(e["field"], e["rule"]) for e in answer(resp, "post")["errors"]] == [
        ("parent_account_id", "parent_unavailable")
    ]


def test_a_stored_rule_without_a_parent_is_422_with_no_field_entry(served: Served) -> None:
    world, store = served
    store.fails = AccountsStoreRuleError("ea_uid_fmt")
    resp = create(world, MAIN)
    (entry,) = answer(resp, "post")["errors"]
    assert (resp.status_code, entry) == (
        422, {"rule": "ea_uid_fmt", "message": "The account breaks a stored rule."},
    )  # fmt: skip


def test_a_record_not_written_is_503_and_nothing_is_stored(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, store = served

    async def down(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("the audit writer is not started")

    monkeypatch.setattr(world.audit, "emit", down)
    before = set(store.rows)
    resp = create(world, MAIN | {"exchange_uid": "99990001", "label": "New"})
    assert (resp.status_code, answer(resp, "post")["code"]) == (503, "audit_unavailable")
    assert resp.headers["retry-after"] == "5"
    assert set(store.rows) == before


def test_an_idempotent_replay_with_the_same_key_returns_the_first_answer(served: Served) -> None:
    world, store = served
    key = str(uuid.uuid4())
    body = MAIN | {"exchange_uid": "99990002", "label": "Once"}
    first = create(world, body, key=key)
    again = create(world, body, key=key)
    assert (first.status_code, again.status_code, again.json()) == (201, 201, first.json())
    assert again.headers["idempotency-replayed"] == "true"
    assert [kind for kind, _ in store.seen] == ["create"]


def test_an_idempotency_key_reused_with_another_body_is_409(served: Served) -> None:
    world, _ = served
    key = str(uuid.uuid4())
    body = MAIN | {"exchange_uid": "99990002", "label": "Once"}
    assert create(world, body, key=key).status_code == 201
    reused = create(world, body | {"label": "Other"}, key=key)
    assert (reused.status_code, answer(reused, "post")["code"]) == (409, "idempotency_key_reuse")


def test_a_non_uuid_idempotency_key_is_422_naming_the_header(served: Served) -> None:
    world, _ = served
    bad = create(world, MAIN | {"exchange_uid": "99990002", "label": "Once"}, key="not-a-uuid")
    assert (bad.status_code, answer(bad, "post")["errors"][0]["field"]) == (422, "Idempotency-Key")


def test_the_stores_owner_gate_refusing_a_create_is_403_and_audited(served: Served) -> None:
    world, store = served
    store.gated = True
    with capture_logs():
        resp = create(world, MAIN)
    assert answer(resp, "post")["required_permissions"] == ["accounts:write"]
    (record,) = world.audit.records
    assert record["reason"] == "not_owner:accounts:write:none"
