"""Two-layer (SR-050), scope-at-construction (SR-051), self-service (SR-026), step-up (SR-025)
and WS parity assertions for the RBAC matrix pack (E09-Q03)."""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any

import pytest

from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import Allow, Deny, decide
from tests.contract.rbac.rbac_harness import (
    ACTORS,
    FOREIGN,
    GRANTED,
    World,
    bearer,
    user_id_of,
)

_FIXTURE = Path(__file__).parents[2] / "fixtures" / "rule_ir" / "form_simple_0.json"


def _rule_body(account: uuid.UUID, name: str) -> dict[str, Any]:
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"), parse_float=str)
    raw["name"] = name
    raw["actions"][0]["params"] = {"channel": "ui", "severity": "info", "template": "x"}
    raw["scope"] = {"level": "account", "account_ids": [str(account)]}
    return {"ir": raw}


def _rules(world: World, actor: str) -> list[dict[str, Any]]:
    resp = world.client.get("/rules", headers=bearer(actor))
    assert resp.status_code == 200
    items: list[dict[str, Any]] = resp.json()["items"]
    return items


# -- SR-050: two layers, API capability AND domain grant ----------------------------------------


def test_valid_capability_but_non_granted_account_is_403_nothing_mutated_and_audited(
    world: World,
) -> None:
    """Manager holds `rules:write` (layer 1 passes) but no grant on FOREIGN (layer 2 denies)."""
    before = len(world.rule_store._rows)
    resp = world.client.post(
        "/rules", json=_rule_body(FOREIGN, "foreign"), headers=bearer("manager_with_grant")
    )
    assert resp.status_code == 403
    assert len(world.rule_store._rows) == before
    assert world.scope_events == ["rule_scope_denied"], "the denial must be audited"
    ok = world.client.post(
        "/rules", json=_rule_body(GRANTED, "granted"), headers=bearer("manager_with_grant")
    )
    assert ok.status_code == 201, "the same capability on the granted account must pass"


def test_no_capability_is_refused_at_the_api_boundary_before_the_domain_layer(
    world: World,
) -> None:
    resp = world.client.post(
        "/rules", json=_rule_body(GRANTED, "viewer-attempt"), headers=bearer("viewer")
    )
    assert resp.status_code == 403
    assert not world.rule_store._rows
    assert world.scope_events == [], "layer 1 refuses first; the scope layer is never consulted"


def test_manager_without_any_grant_cannot_create_even_with_the_capability(world: World) -> None:
    resp = world.client.post(
        "/rules", json=_rule_body(GRANTED, "ungranted"), headers=bearer("manager_without_grant")
    )
    assert resp.status_code == 403
    assert not world.rule_store._rows


# -- granted_accounts HTTP cells, pinned against the policy decision point ----------------------
#
# `decide()` (auth/scopes.py) is the single policy decision point. Today only the WS gateway calls
# it; the mounted HTTP routes enforce the same grant through `ScopeResolver.authorize_accounts`.
# Each cell below asserts the HTTP outcome AND that `decide()` returns the matching decision for
# the same principal, so HTTP and PDP cannot silently diverge.


@pytest.mark.parametrize(
    ("actor", "account", "http_status", "decision"),
    [
        ("manager_with_grant", GRANTED, 201, Allow),
        ("manager_with_grant", FOREIGN, 403, Deny),
        ("manager_without_grant", GRANTED, 403, Deny),
        ("owner", GRANTED, 201, Allow),
        ("owner", FOREIGN, 201, Allow),
        ("viewer", GRANTED, 403, Deny),
    ],
)
def test_granted_accounts_http_cell_agrees_with_the_decision_point(
    world: World, actor: str, account: uuid.UUID, http_status: int, decision: type
) -> None:
    resp = world.client.post(
        "/rules", json=_rule_body(account, f"{actor}-{str(account)[-1]}"), headers=bearer(actor)
    )
    assert resp.status_code == http_status, f"{actor} on {str(account)[-1]}: {resp.status_code}"
    snap = world.resolver.snapshot(actor)
    pdp = decide(
        snap, Permission.RULES_WRITE, scope=Scope.GRANTED_ACCOUNTS, exchange_account_id=account
    )
    assert isinstance(pdp, decision), f"decide() disagrees with HTTP for {actor}: {pdp!r}"
    created = len(world.rule_store._rows)
    assert created == (1 if http_status == 201 else 0), "a denied call must create nothing"


def test_granted_accounts_read_cell_allows_granted_and_hides_foreign(world: World) -> None:
    mine = world.client.post("/rules", json=_rule_body(GRANTED, "m"), headers=bearer("owner"))
    theirs = world.client.post("/rules", json=_rule_body(FOREIGN, "t"), headers=bearer("owner"))
    assert mine.status_code == theirs.status_code == 201
    got = world.client.get(f"/rules/{mine.json()['id']}", headers=bearer("manager_with_grant"))
    assert got.status_code == 200, "granted account: allow"
    other = world.client.get(f"/rules/{theirs.json()['id']}", headers=bearer("manager_with_grant"))
    absent = world.client.get(f"/rules/{uuid.uuid4()}", headers=bearer("manager_with_grant"))
    assert other.status_code == 404 == absent.status_code, "non-granted account: indistinguishable"
    assert other.json() == absent.json() or other.json().get("code") == absent.json().get("code")


# -- granted_accounts write cell: PUT /rules/{ruleId}/active-version (#2574) --------------------
#
# The matrix row cannot reach this route's scope logic (its runner sends a static body against an
# empty rule store, so no real version id exists); these cells drive the real path instead.


def _acct(account: uuid.UUID) -> dict[str, Any]:
    return {"level": "account", "account_ids": [str(account)]}


def _rule_with_old_version(world: World, scope: dict[str, Any]) -> tuple[str, str]:
    """Owner-made rule on `scope`, edited once: (rule id, its older, inactive version id)."""
    body = _rule_body(GRANTED, "two-versions")
    body["ir"]["scope"] = scope
    made = world.client.post("/rules", json=body, headers=bearer("owner"))
    assert made.status_code == 201, made.text
    rid = str(made.json()["id"])
    body["ir"]["actions"][0]["params"]["template"] = "edited"
    hdrs = {**bearer("owner"), "If-Match": "1"}
    assert world.client.put(f"/rules/{rid}", json=body, headers=hdrs).status_code == 200
    items = world.client.get(f"/rules/{rid}/versions", headers=bearer("owner")).json()["items"]
    assert len(items) == 2
    return rid, str(items[-1]["id"])  # newest first: the last item is version 1


def _activate(world: World, actor: str, rule_id: str, version_id: str) -> Any:
    body = {"version_id": version_id}
    return world.client.put(f"/rules/{rule_id}/active-version", json=body, headers=bearer(actor))


def _active_version(world: World, rule_id: str) -> str:
    view = world.client.get(f"/rules/{rule_id}", headers=bearer("owner")).json()
    return str(view["active_version_id"])


@pytest.mark.parametrize(
    ("actor", "account"), [("manager_with_grant", FOREIGN), ("manager_without_grant", GRANTED)]
)
def test_active_version_on_an_unseen_rule_is_the_same_404_as_a_missing_rule_or_version(
    world: World, actor: str, account: uuid.UUID
) -> None:
    """#2574, 04 §7.3: on a rule the caller cannot see, its real version, a missing version and a
    missing rule are one indistinguishable 404 (no existence oracle). Visibility is checked before
    any version lookup or scope pre-check; the denial is audited and nothing changes."""
    rid, old = _rule_with_old_version(world, _acct(account))
    active = _active_version(world, rid)
    world.audit.records.clear()
    world.scope_events.clear()
    real = _activate(world, actor, rid, old)
    no_version = _activate(world, actor, rid, str(uuid.uuid4()))
    no_rule = _activate(world, actor, str(uuid.uuid4()), old)
    statuses = (real.status_code, no_version.status_code, no_rule.status_code)
    assert statuses == (404, 404, 404), f"a real foreign version must not answer 403: {statuses}"
    assert real.json() == no_version.json() == no_rule.json(), "the problem bodies must match"
    assert real.json()["code"] == "not_found"
    assert _active_version(world, rid) == active, "a refused call must change nothing"
    refused = [
        (r["rule_id"], r["op"], r["reason"])
        for r in world.audit.records
        if r["action"] == "rule.scope_refused"
    ]
    assert refused == [(rid, "set_active_version", "rule_not_visible")] * 2, refused
    assert world.scope_events == [], "an unseen rule never reaches the scope pre-check"


@pytest.mark.parametrize(
    ("actor", "account"), [("manager_with_grant", GRANTED), ("owner", FOREIGN)]
)
def test_active_version_on_a_visible_rule_switches_the_version(
    world: World, actor: str, account: uuid.UUID
) -> None:
    rid, old = _rule_with_old_version(world, _acct(account))
    resp = _activate(world, actor, rid, old)
    assert resp.status_code == 200, resp.text
    assert resp.json()["active_version_id"] == old == _active_version(world, rid)


def test_active_version_without_rules_write_is_the_same_403_whether_or_not_the_rule_exists(
    world: World,
) -> None:
    """The viewer lacks `rules:write`: refused at the API boundary before any lookup."""
    rid, old = _rule_with_old_version(world, _acct(GRANTED))
    active = _active_version(world, rid)
    real = _activate(world, "viewer", rid, old)
    absent = _activate(world, "viewer", str(uuid.uuid4()), str(uuid.uuid4()))
    assert real.status_code == absent.status_code == 403
    assert real.json() == absent.json() and real.json()["code"] == "forbidden"
    assert _active_version(world, rid) == active


def test_active_version_grant_refusal_on_a_visible_rule_is_audited_as_scope_refused(
    world: World,
) -> None:
    """An account-less rule is visible to a manager with no grants, who still may not switch it
    (`_require_grants`, no vacuous pass): 403 audited as `rule.scope_refused`."""
    rid, old = _rule_with_old_version(world, {"level": "symbol", "symbols": ["BTCUSDT"]})
    world.audit.records.clear()
    resp = _activate(world, "manager_without_grant", rid, old)
    assert resp.status_code == 403 and resp.json()["code"] == "forbidden", resp.text
    refused = [
        (r["op"], r["reason"]) for r in world.audit.records if r["action"] == "rule.scope_refused"
    ]
    assert refused == [("set_active_version", "no_grants")], refused


# -- SR-051: scope applied at construction -------------------------------------------------------


def test_list_with_one_grant_returns_only_that_accounts_rows(world: World) -> None:
    for acct, name in ((GRANTED, "mine"), (FOREIGN, "theirs")):
        r = world.client.post("/rules", json=_rule_body(acct, name), headers=bearer("owner"))
        assert r.status_code == 201, r.text
    names = {i["name"] for i in _rules(world, "manager_with_grant")}
    assert names == {"mine"}, "a manager with one grant must never see another account's rows"
    assert {i["name"] for i in _rules(world, "owner")} == {"mine", "theirs"}
    assert _rules(world, "manager_without_grant") == []
    assert _rules(world, "viewer") == []


def test_scope_is_part_of_the_query_not_a_post_filter(world: World) -> None:
    """SQL-predicate hook: the rules store is asked for rows, and visibility is decided from the
    caller's grants *inside* `RulesManager._visible` (before pagination), so a page of `limit`
    rows can never be short-changed by rows a post-filter would drop."""
    for i in range(3):
        world.client.post("/rules", json=_rule_body(FOREIGN, f"f{i}"), headers=bearer("owner"))
    world.client.post("/rules", json=_rule_body(GRANTED, "m0"), headers=bearer("owner"))
    page = world.client.get("/rules", params={"limit": 1}, headers=bearer("manager_with_grant"))
    assert [i["name"] for i in page.json()["items"]] == ["m0"], (
        "pagination must run over the already-scoped set"
    )
    assert page.json()["meta"]["has_more"] is False


# -- SR-026 / SR-025 -----------------------------------------------------------------------------

_SELF_SERVICE_WITH_BODY = [
    ("POST", "/settings/hotkey-audit", {
        "command_id": "chart.zoom", "before": "a", "after": "b", "acknowledged_unsafe": False,
    }),
    ("POST", "/auth/logout", {}),
]  # fmt: skip


@pytest.mark.parametrize(("method", "path", "body"), _SELF_SERVICE_WITH_BODY)
def test_self_service_routes_reject_a_target_user_id_in_the_body(
    world: World, method: str, path: str, body: dict[str, Any]
) -> None:
    target = str(user_id_of("owner"))
    resp = world.client.request(
        method, path, json={**body, "user_id": target}, headers=bearer("manager_with_grant")
    )
    assert resp.status_code in (400, 422), (
        f"{method} {path}: a target-user parameter must be rejected, got {resp.status_code}"
    )


def test_self_service_reads_are_always_about_the_caller(world: World) -> None:
    mgr = world.client.get(
        "/auth/session", params={"user_id": str(user_id_of("owner"))},
        headers=bearer("manager_with_grant"),
    )  # fmt: skip
    assert mgr.status_code == 200
    assert mgr.json()["user"]["id"] == str(user_id_of("manager_with_grant")), (
        "a user_id query parameter must never retarget a self-scoped read"
    )


_ADMIN_MUTATIONS = [
    ("PUT", "/users/{uid}/roles", {"roles": ["viewer"]}),
    ("POST", "/users", {}),
    ("POST", "/users/{uid}/invite", None),
    ("DELETE", "/users/{uid}/invite", None),
    ("POST", "/users/{uid}/mfa/reset", None),
]  # fmt: skip


@pytest.mark.parametrize(("method", "path", "body"), _ADMIN_MUTATIONS)
@pytest.mark.parametrize("actor", ["manager_with_grant", "manager_without_grant", "viewer"])
def test_administrative_mutations_are_owner_only(
    world: World, method: str, path: str, body: Any, actor: str
) -> None:
    world.step_up.elevated = True  # even a fully elevated non-owner session is refused
    url = path.format(uid=user_id_of("viewer"))
    resp = world.client.request(method, url, json=body, headers=bearer(actor))
    assert resp.status_code == 403
    assert world.users.roles == world.users.initial_roles, "a refused call must not mutate roles"


@pytest.mark.parametrize(("method", "path", "body"), _ADMIN_MUTATIONS)
def test_administrative_mutations_require_step_up_even_for_the_owner(
    world: World, method: str, path: str, body: Any
) -> None:
    world.step_up.elevated = False
    url = path.format(uid=user_id_of("viewer"))
    resp = world.client.request(method, url, json=body, headers=bearer("owner"))
    assert resp.status_code == 403
    assert resp.json().get("code") == "step_up_required"
    assert world.users.roles == world.users.initial_roles


# -- WS parity ----------------------------------------------------------------------------------


_WS_TIMEOUT_S = 5.0


def _recv(ws: Any) -> dict[str, Any]:
    """`receive_json` with a hard deadline: a missing frame fails the test instead of hanging the
    suite. The blocking read runs in a worker thread; leaving the `with` block closes the socket,
    which unblocks it."""
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        frame: dict[str, Any] = pool.submit(ws.receive_json).result(timeout=_WS_TIMEOUT_S)
    except FutureTimeout:
        pytest.fail(f"no WS frame within {_WS_TIMEOUT_S}s (expected frame never arrived)")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return frame


def _hello(ws: Any) -> None:
    """§4.2: `hello` -> `welcome` precedes everything else (E17-S01)."""
    ws.send_json({"t": "hello", "id": "h"})
    assert _recv(ws)["t"] == "welcome"


def _auth(ws: Any, actor: str) -> dict[str, Any]:
    _hello(ws)
    ws.send_json({"t": "auth", "id": "a", "p": {"access_token": f"tok-{actor}"}})
    return _recv(ws)


def _sub(ws: Any, ch: str, account: uuid.UUID | None) -> dict[str, Any]:
    entry: dict[str, Any] = {"ch": ch}
    if account is not None:
        entry["opts"] = {"exchange_account_ids": [str(account)]}
    ws.send_json({"t": "sub", "id": ch, "p": {"topics": [entry]}})
    frame = _recv(ws)
    if frame["t"] != "sub_ok":
        return {"ok": False, "error": {"code": frame["p"]["code"]}}
    result: dict[str, Any] = frame["p"]["results"][0]
    return result


def _topic_cells() -> list[Any]:
    from tests.contract.rbac.test_route_matrix import _TOPICS

    return [
        pytest.param(fam, actor, id=f"{fam}|{actor}") for fam in sorted(_TOPICS) for actor in ACTORS
    ]


@pytest.mark.parametrize(("family", "actor"), _topic_cells())
def test_every_topic_family_x_actor_matches_the_matrix(
    world: World, family: str, actor: str
) -> None:
    from tests.contract.rbac.test_route_matrix import _TOPICS

    row = _TOPICS[family]
    expected = row["outcomes"][actor]
    account = GRANTED if row["scope"] == "granted_accounts" else None
    with world.client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        if actor != "unauthenticated":
            assert _auth(ws, actor)["t"] == "auth_ok"
        else:
            _hello(ws)
        result = _sub(ws, row["sample"], account)
    observed = "sub_ok" if result["ok"] else result["error"]["code"]
    assert observed == expected, f"topic {family} as {actor}: expected {expected}, got {observed}"


def test_non_entitled_role_gets_forbidden_not_a_silent_empty_subscription(world: World) -> None:
    """Contract parity: a viewer lacking a topic's permission is told so (`forbidden`)."""
    from candleviewer.auth.scopes import PrincipalSnapshot
    from candleviewer.ws.permissions import check_subscribe

    bare = PrincipalSnapshot(user_id_of("viewer"), frozenset({"viewer"}), frozenset())
    from candleviewer.auth.scopes import Deny

    for family in ("book", "orders", "recorder"):
        decision = check_subscribe(bare, family, exchange_account_id=GRANTED)
        assert isinstance(decision, Deny), family


def test_in_flight_subscription_gets_revoked_when_the_grant_is_withdrawn(world: World) -> None:
    """Grant revoked mid-connection: `revoked` frame, then a resubscribe is denied (§9.5)."""
    mgr = user_id_of("manager_with_grant")
    with world.client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
        assert _auth(ws, "manager_with_grant")["t"] == "auth_ok"
        assert _sub(ws, "orders", GRANTED)["ok"] is True
        world.resolver.revoked.add("manager_with_grant")  # the owner withdraws the grant ...
        resp = world.client.put(  # ... and the role-change path re-evaluates live sockets
            f"/users/{mgr}/roles", json={"roles": ["manager"]}, headers=bearer("owner")
        )
        assert resp.status_code == 200
        change, revoked = _recv(ws), _recv(ws)
        assert change["t"] == "permission_change"
        assert (revoked["t"], revoked["ch"]) == ("revoked", "orders")
        assert revoked["p"]["reason"] == "account_scope_changed"
        assert _sub(ws, "orders", GRANTED)["error"]["code"] == "account_scope_denied"
