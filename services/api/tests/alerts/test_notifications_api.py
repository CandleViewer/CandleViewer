"""E40-T04 `GET /notifications`: per-source scope from the caller's permissions and grants, the
`Notification` shape (uuid5 ids, deep links, no source payloads), and the read's edges.

The SQL that applies a scope is pinned in `tests/unit/storage/test_alert_inbox_store.py` and on
real Postgres in `tests/integration/storage/test_notifications_union_pg.py`; here the store is a
fake that records the scope it was given.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid5

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from candleviewer.api import notifications
from candleviewer.api.notifications import (
    LIST_NOTIFICATIONS_QUERY,
    NOTIFICATION_NAMESPACE,
    SYSTEM_TITLE_MAX,
    dump,
    make_notifications_router,
    notification_id,
    notification_scope,
    source_id,
)
from candleviewer.observability.redaction import redact_text
from candleviewer.rules.manager import Actor
from candleviewer.storage.repositories.notifications import (
    NotificationRow,
    NotificationScope,
)

USER = "00000000-0000-4000-8000-00000000000a"
ACCT = "0a000000-0000-4000-8000-000000000001"
ORDER = "0b000000-0000-4000-8000-000000000001"
RULE = "0c000000-0000-4000-8000-000000000001"
ALERT = "13000000-0000-4000-8000-00000000000a"
T0 = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
VIEWER = frozenset({"alerts:read", "rules:read", "orders:read", "marketdata:read"})


def _row(nkind: str, src: int, src_id: int, **over: Any) -> NotificationRow:
    base = NotificationRow(
        nkind=nkind, src=src, src_id=src_id, ts=T0, severity="info", title="t", body=None,
        read_at=None, symbol=None, account_id=None, source_uuid=None, event="e", code=None,
    )  # fmt: skip
    return replace(base, **over)


class FakeStore:
    def __init__(self) -> None:
        self.scopes: list[NotificationScope] = []
        self.kw: list[dict[str, Any]] = []
        self.rows: list[NotificationRow] = []
        self.last: NotificationRow | None = None

    async def list_page(
        self,
        scope: NotificationScope,
        *,
        unread_only: bool = False,
        cursor: str | None = None,
        limit: int = 100,
    ) -> tuple[list[NotificationRow], NotificationRow | None]:
        if cursor == "bad":
            raise ValueError("invalid cursor")
        self.scopes.append(scope)
        self.kw.append({"unread_only": unread_only, "cursor": cursor, "limit": limit})
        return self.rows, self.last


class Env:
    def __init__(self, *, wired: bool = True, rules_wired: bool = True) -> None:
        self.store = FakeStore()
        self.actor: Actor | None = Actor(USER, "s", VIEWER, frozenset({ACCT}))
        self.visible: frozenset[str] = frozenset({RULE})
        self.rule_calls = 0
        self.store_up = True

        def resolve(_r: Request) -> Actor | None:
            return self.actor

        async def visible(_a: Actor) -> frozenset[str]:
            self.rule_calls += 1
            return self.visible

        app = FastAPI()
        app.include_router(
            make_notifications_router(
                lambda: self.store if self.store_up else None,
                resolve if wired else None,
                visible if rules_wired else None,
            )
        )
        self.c = TestClient(app)

    def scope(self, **params: Any) -> NotificationScope:
        r = self.c.get("/notifications", params=params)
        assert r.status_code == 200, r.text
        return self.store.scopes[-1]


@pytest.fixture
def env() -> Env:
    return Env()


# --- scope -------------------------------------------------------------------------------


def test_viewer_scope_is_every_source_it_holds_on_its_granted_accounts(env: Env) -> None:
    s = env.scope()
    assert (s.alerts, s.rules, s.orders) == (True, True, True)
    assert s.rule_ids == {RULE} and s.accounts == {ACCT} and s.user_id == USER


#: What a Viewer and a Manager hold of the sources' read and write permissions (`alerts`, `rules`,
#: `orders`, `positions`), and nothing: none of these reaches a system row.
_ROLE_PERMS = {
    "viewer": VIEWER,
    "manager": VIEWER | {"rules:write", "alerts:write", "orders:write", "positions:write"},
    "no permission at all": frozenset(),
}


@pytest.mark.parametrize("roles", sorted(_ROLE_PERMS))
def test_no_one_but_the_owner_gets_system_rows(env: Env, roles: str) -> None:
    """Fail closed (04 §7.2.2 row 34b; #3917 review SR-E40T04A-01): no role-neutral view of
    `system_events` is approved, whatever a non-Owner holds."""
    env.actor = Actor(USER, "s", _ROLE_PERMS[roles], frozenset({ACCT}))
    assert env.scope().system is False
    assert env.scope(kind=["system"]).system is False


def test_a_user_without_orders_read_gets_no_order_source(env: Env) -> None:
    """Ticket security note: no order events for a viewer lacking `orders:read`."""
    env.actor = Actor(USER, "s", VIEWER - {"orders:read"}, frozenset({ACCT}))
    assert env.scope().orders is False


def test_each_source_needs_its_own_permission(env: Env) -> None:
    env.actor = Actor(USER, "s", frozenset(), frozenset({ACCT}))
    s = env.scope()
    assert (s.alerts, s.rules, s.orders, s.system) == (False, False, False, False)
    assert s.empty and env.rule_calls == 0  # no `rules:read`: the predicate is not even asked


def test_owner_scope_is_every_account_the_listed_rules_and_the_system_stream(env: Env) -> None:
    env.actor = Actor(USER, "s", VIEWER, frozenset(), is_owner=True)
    env.visible = frozenset({RULE, "0c000000-0000-4000-8000-000000000002"})  # `list_rules`'
    s = env.scope()
    assert s.accounts is None and s.rule_ids == env.visible and s.rules is True
    assert s.system is True


def test_no_visible_rule_turns_the_rule_source_off(env: Env) -> None:
    env.visible = frozenset()
    s = env.scope()
    assert s.rules is False and s.rule_ids == frozenset()


def test_unwired_rules_module_means_no_rule_rows_never_every_rule() -> None:
    env = Env(rules_wired=False)
    s = env.scope()
    assert s.rules is False and s.rule_ids == frozenset()


def test_a_manager_without_grants_sees_no_account_rows(env: Env) -> None:
    env.actor = Actor(USER, "s", VIEWER, frozenset())
    s = env.scope()
    assert s.accounts == frozenset() and s.orders is True  # the SQL matches no account


@pytest.mark.parametrize(
    ("kinds", "expect"),
    [
        (["alert"], (True, False, False, False)),
        (["rule", "order"], (False, True, True, False)),
        (["system"], (False, False, False, False)),  # not the Owner (04 §7.2.2 row 34b)
        (["risk"], (False, False, False, False)),
    ],
)
def test_kind_filter_selects_sources(
    env: Env, kinds: list[str], expect: tuple[bool, bool, bool, bool]
) -> None:
    s = env.scope(kind=kinds)
    assert (s.alerts, s.rules, s.orders, s.system) == expect


def test_rule_predicate_is_skipped_when_rules_are_not_requested(env: Env) -> None:
    env.scope(kind=["alert"])
    assert env.rule_calls == 0


def test_scope_is_pure_over_the_actor() -> None:
    a = Actor(USER, "s", frozenset({"alerts:read"}), frozenset({ACCT}))
    assert notification_scope(a, (), frozenset({RULE})).rules is False  # no `rules:read`
    assert notification_scope(a, ("alert",), frozenset()).alerts is True
    owner = Actor(USER, "s", frozenset(), frozenset(), is_owner=True)
    assert notification_scope(owner, ("system",), frozenset()).system is True


# --- the read ----------------------------------------------------------------------------


def test_paging_parameters_reach_the_store(env: Env) -> None:
    env.c.get("/notifications", params={"limit": 500, "cursor": "abc", "unread_only": "true"})
    assert env.store.kw[-1] == {"unread_only": True, "cursor": "abc", "limit": 500}


def test_next_cursor_comes_from_the_last_row_and_marks_has_more(env: Env) -> None:
    env.store.rows = [_row("alert", 1, 7)]
    env.store.last = env.store.rows[-1]
    meta = env.c.get("/notifications").json()["meta"]
    assert meta["has_more"] is True and meta["count"] == 1 and meta["next_cursor"]


@pytest.mark.parametrize("limit", ["0", "501", "x"])
def test_limit_is_bounded(env: Env, limit: str) -> None:
    assert env.c.get("/notifications", params={"limit": limit}).status_code == 422


def test_unknown_kind_is_422(env: Env) -> None:
    assert env.c.get("/notifications", params={"kind": "trade"}).status_code == 422


def test_invalid_cursor_is_400(env: Env) -> None:
    r = env.c.get("/notifications", params={"cursor": "bad"})
    assert r.status_code == 400 and r.json()["detail"] == "invalid cursor"


@pytest.mark.parametrize("key", ["user_id", "userId", "account", "exchange_account_ids"])
def test_undeclared_query_parameter_is_refused(env: Env, key: str) -> None:
    r = env.c.get("/notifications", params={key: "x"})
    assert r.status_code == 422 and env.store.scopes == []


def test_no_session_is_401_and_unwired_resolver_501(env: Env) -> None:
    env.actor = None
    assert env.c.get("/notifications").status_code == 401
    assert Env(wired=False).c.get("/notifications").status_code == 501


def test_store_down_is_503(env: Env) -> None:
    env.store_up = False
    assert env.c.get("/notifications").status_code == 503


def test_declared_query_set_matches_the_contract() -> None:
    """Read from the spec (SR-026); see `test_alert_deliveries_rbac.py` for why not the table."""
    from candleviewer.api.contract_conformance import load_openapi_spec
    from tests.unit.api.test_query_allowlist import _declared_query

    declared = _declared_query(load_openapi_spec(), "/notifications", "get")
    assert declared == LIST_NOTIFICATIONS_QUERY


# --- Notification shape ------------------------------------------------------------------


def test_id_is_uuid5_of_source_table_and_id() -> None:
    assert NOTIFICATION_NAMESPACE == UUID("2def8b5c-e7e2-4686-af54-02c04b8c6a78")
    assert notification_id(1, 4471) == str(uuid5(NOTIFICATION_NAMESPACE, "alert_deliveries4471"))
    assert notification_id(3, 4471) != notification_id(1, 4471)
    assert notification_id(2, 9) == notification_id(2, 9)


def test_source_id_is_the_originating_rows_uuid_never_a_raw_id() -> None:
    """Contract-typed (uuid): the 24 §1.6 scheme over `<table>:<event id>` (ruling on #1016)."""
    assert source_id(1, 4471) == str(uuid5(NOTIFICATION_NAMESPACE, "alert_deliveries:4471"))
    assert source_id(4, 5) == str(uuid5(NOTIFICATION_NAMESPACE, "system_events:5"))
    assert source_id(1, 4471) != notification_id(1, 4471)
    for src in (1, 2, 3, 4):
        UUID(source_id(src, 7))  # always a uuid


def test_alert_row_dump() -> None:
    r = _row("alert", 1, 4471, title="BTC reclaims 64k", body="BTCUSDT crossed 64000",
             read_at=T0, symbol="BTCUSDT", source_uuid=ALERT, event="in_app",
             severity="warning")  # fmt: skip
    assert dump(r) == {
        "id": notification_id(1, 4471), "kind": "alert", "severity": "warning",
        "title": "BTC reclaims 64k", "body": "BTCUSDT crossed 64000",
        "created_at": T0.isoformat(), "read_at": T0.isoformat(), "symbol": "BTCUSDT",
        "exchange_account_id": None, "source_id": source_id(1, 4471),
        "route": f"/alerts/{ALERT}",
    }  # fmt: skip


def test_rule_row_names_the_rule_and_the_outcome() -> None:
    r = _row("rule", 2, 3, title="Move SL to BE", event="action_fail", severity="error",
             source_uuid=RULE, account_id=ACCT)  # fmt: skip
    d = dump(r)
    assert d["title"] == "Rule Move SL to BE: action failed" and d["severity"] == "error"
    assert d["route"] == f"/rules/{RULE}/history" and d["exchange_account_id"] == ACCT


@pytest.mark.parametrize(
    ("event", "code", "title", "severity"),
    [
        ("reject", "10018", "BTCUSDT order rejected (code 10018)", "error"),
        ("error", None, "BTCUSDT order failed", "error"),
        ("expire", None, "BTCUSDT order expired", "warning"),
        ("fill", "0", "BTCUSDT order filled", "info"),
        ("kill", "0", "BTCUSDT order cancelled by the kill switch", "warning"),
        ("adopt", None, "BTCUSDT order adopted from the exchange (review it)", "warning"),
    ],
)
def test_order_row_title_and_severity(
    event: str, code: str | None, title: str, severity: str
) -> None:
    r = _row("order", 3, 11, title=None, severity=None, symbol="BTCUSDT", event=event,
             code=code, source_uuid=ORDER, account_id=ACCT)  # fmt: skip
    d = dump(r)
    assert (d["title"], d["severity"]) == (title, severity)
    assert d["route"] == f"/positions/order/{ORDER}" and d["source_id"] == source_id(3, 11)


def test_system_row_has_no_route_but_a_source_id() -> None:
    d = dump(_row("system", 4, 5, title="Dead-man's-switch call owed", severity="warning"))
    assert d["route"] is None and d["source_id"] == source_id(4, 5) and d["kind"] == "system"
    assert d["title"] == "Dead-man's-switch call owed"


def test_a_system_message_passes_the_shared_redaction_then_the_cut() -> None:
    """A bare key-shaped run (the redaction's 18 to 36 alphanumerics) straddles the cut: cut
    first, its 10-character stub would be too short for that shape and would survive; redacted
    first, nothing of it does."""
    key = "Zq" + "9x" * 14  # 30 alphanumerics, built here: no literal looks like a credential
    message = f"{'x' * (SYSTEM_TITLE_MAX - 11)} {key} tail"
    assert key[:10] in redact_text(message[:SYSTEM_TITLE_MAX])  # cut first, the stub would stay
    d = dump(_row("system", 4, 6, title=message, event="health"))
    assert len(d["title"]) <= SYSTEM_TITLE_MAX and key[:10] not in d["title"]


def test_a_system_message_that_cannot_be_redacted_is_not_shown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(_text: str) -> str:
        raise RuntimeError("redaction rules failed to load")

    monkeypatch.setattr(notifications, "redact_text", boom)
    d = dump(_row("system", 4, 7, title="raw text", event="health_degraded"))
    assert d["title"] == "System event (health_degraded)"


def test_a_malformed_symbol_is_never_echoed() -> None:
    assert dump(_row("alert", 1, 1, symbol="<script>"))["symbol"] is None


def test_every_answer_is_exactly_the_contracts_notification(env: Env) -> None:
    """Built field by field (#3917 review SR-E40T04A-06): the SQL selects no `payload`,
    `details`, `ret_msg` or `context` (pinned in `test_alert_inbox_store.py`), and the answer's
    keys are exactly `Notification`'s, so no source field can be added on the way out."""
    from candleviewer.api.contract_conformance import load_openapi_spec

    env.actor = Actor(USER, "s", VIEWER, frozenset(), is_owner=True)
    env.store.rows = [_row(k, src, 9) for k, src in (("alert", 1), ("rule", 2), ("order", 3),
                                                      ("system", 4))]  # fmt: skip
    items = env.c.get("/notifications").json()["items"]
    declared = set(load_openapi_spec()["components"]["schemas"]["Notification"]["properties"])
    assert len(items) == 4 and all(set(i) == declared for i in items)


@pytest.mark.parametrize(("system_rows", "offloaded"), [(50, False), (51, True)])
def test_a_page_of_many_system_rows_is_redacted_off_the_loop(
    env: Env, monkeypatch: pytest.MonkeyPatch, system_rows: int, offloaded: bool
) -> None:
    calls: list[int] = []
    real = asyncio.to_thread

    async def spy(fn: Any, *a: Any) -> Any:
        calls.append(len(a[0]))
        return await real(fn, *a)

    monkeypatch.setattr(notifications.asyncio, "to_thread", spy)
    env.actor = Actor(USER, "s", VIEWER, frozenset(), is_owner=True)
    env.store.rows = [_row("system", 4, n + 1, title=f"m{n}") for n in range(system_rows)]
    assert len(env.c.get("/notifications", params={"limit": 500}).json()["items"]) == system_rows
    assert calls == ([system_rows] if offloaded else [])
    assert notifications.OFFLOAD_SYSTEM_ROWS == 50
