"""Two-layer (SR-050), scope-at-construction (SR-051), self-service (SR-026), step-up (SR-025)
and WS parity assertions for the RBAC matrix pack (E09-Q03)."""

from __future__ import annotations

import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from candleviewer.api.deny_by_default import served_operations
from candleviewer.auth.errors import SessionReadOnly
from candleviewer.auth.generated_permissions import Permission, Scope
from candleviewer.auth.scopes import Allow, Deny, decide
from tests.contract.rbac.rbac_harness import (
    ACTORS,
    FOREIGN,
    GRANTED,
    ROLE_OF,
    World,
    bearer,
    fill_path,
    record_cell,
    seed_machine,
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
    mine = world.client.post(
        "/rules", json=_rule_body(GRANTED, "m"), headers=bearer("manager_with_grant")
    )
    theirs = world.client.post("/rules", json=_rule_body(FOREIGN, "t"), headers=bearer("owner"))
    assert mine.status_code == theirs.status_code == 201
    got = world.client.get(f"/rules/{mine.json()['id']}", headers=bearer("manager_with_grant"))
    assert got.status_code == 200, "granted account: allow"
    other = world.client.get(f"/rules/{theirs.json()['id']}", headers=bearer("manager_with_grant"))
    absent = world.client.get(f"/rules/{uuid.uuid4()}", headers=bearer("manager_with_grant"))
    assert other.status_code == 404 == absent.status_code, "non-granted account: indistinguishable"
    assert other.json() == absent.json() or other.json().get("code") == absent.json().get("code")


def test_read_of_the_owners_rule_on_a_granted_account_is_the_unseen_404(world: World) -> None:
    """#3334, 04 §7.2.2 rows 24 and 25: a grant on the account never reaches another user's rule."""
    owners = world.client.post("/rules", json=_rule_body(GRANTED, "o"), headers=bearer("owner"))
    got = world.client.get(f"/rules/{owners.json()['id']}", headers=bearer("manager_with_grant"))
    absent = world.client.get(f"/rules/{uuid.uuid4()}", headers=bearer("manager_with_grant"))
    assert got.status_code == absent.status_code == 404
    assert got.json() == absent.json()


# -- granted_accounts write cell: PUT /rules/{ruleId}/active-version (#2574) --------------------
#
# The matrix row cannot reach this route's scope logic (its runner sends a static body against an
# empty rule store, so no real version id exists); these cells drive the real path instead.


def _acct(account: uuid.UUID) -> dict[str, Any]:
    return {"level": "account", "account_ids": [str(account)]}


def _rule_with_old_version(
    world: World, scope: dict[str, Any], maker: str = "owner"
) -> tuple[str, str]:
    """`maker`'s rule on `scope`, edited once: (rule id, its older, inactive version id)."""
    body = _rule_body(GRANTED, "two-versions")
    body["ir"]["scope"] = scope
    made = world.client.post("/rules", json=body, headers=bearer(maker))
    assert made.status_code == 201, made.text
    rid = str(made.json()["id"])
    body["ir"]["actions"][0]["params"]["template"] = "edited"
    hdrs = {**bearer(maker), "If-Match": "1"}
    assert world.client.put(f"/rules/{rid}", json=body, headers=hdrs).status_code == 200
    items = world.client.get(f"/rules/{rid}/versions", headers=bearer(maker)).json()["items"]
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
    rid, old = _rule_with_old_version(world, _acct(account), actor)
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


@pytest.mark.parametrize("actor", ["manager_without_grant", "manager_with_grant"])
def test_active_version_on_an_accountless_owner_rule_is_the_unseen_404(
    world: World, actor: str
) -> None:
    """#3334: a rule naming no account is no one's but its owner's, with a grant or without one
    (04 §7.2.2 rows 24 and 25): the unseen 404, audited as `rule.scope_refused`."""
    rid, old = _rule_with_old_version(world, {"level": "symbol", "symbols": ["BTCUSDT"]})
    world.audit.records.clear()
    resp = _activate(world, actor, rid, old)
    assert resp.status_code == 404 and resp.json()["code"] == "not_found", resp.text
    refused = [
        (r["op"], r["reason"]) for r in world.audit.records if r["action"] == "rule.scope_refused"
    ]
    assert refused == [("set_active_version", "rule_not_visible")], refused


def test_active_version_by_an_owner_without_grants_is_refused_as_no_grants(world: World) -> None:
    """#3334: ownership passes and the grant check still refuses (no vacuous pass): a manager's
    own account-less rule, once they hold no grant, cannot switch version: 403 audited."""
    scope = {"level": "symbol", "symbols": ["BTCUSDT"]}
    rid, old = _rule_with_old_version(world, scope, "manager_with_grant")
    world.rule_store._rows[rid].owner = str(user_id_of("manager_without_grant"))
    world.audit.records.clear()
    resp = _activate(world, "manager_without_grant", rid, old)
    assert resp.status_code == 403 and resp.json()["code"] == "forbidden", resp.text
    refused = [
        (r["op"], r["reason"]) for r in world.audit.records if r["action"] == "rule.scope_refused"
    ]
    assert refused == [("set_active_version", "no_grants")], refused


def test_update_naming_an_ungranted_account_on_an_unseen_rule_is_the_unseen_404(
    world: World,
) -> None:
    """#3334: the stored rule is looked at before the document it is saved with, so a manager
    never gets the scope layer's 403 for a rule that is not theirs, only the audited 404."""
    owners = world.client.post("/rules", json=_rule_body(GRANTED, "o"), headers=bearer("owner"))
    rid = owners.json()["id"]
    world.audit.records.clear()
    world.scope_events.clear()
    hdrs = {**bearer("manager_with_grant"), "If-Match": "1"}
    resp = world.client.put(f"/rules/{rid}", json=_rule_body(FOREIGN, "o"), headers=hdrs)
    assert resp.status_code == 404 and resp.json()["code"] == "not_found", resp.text
    refused = [r["op"] for r in world.audit.records if r["action"] == "rule.scope_refused"]
    assert refused == ["update"] and world.scope_events == []


# -- SR-051: scope applied at construction -------------------------------------------------------


def test_list_with_one_grant_returns_only_that_accounts_rows(world: World) -> None:
    made = (
        (GRANTED, "mine", "manager_with_grant"),
        (FOREIGN, "theirs", "owner"),
        (GRANTED, "owners", "owner"),
    )
    for acct, name, maker in made:
        r = world.client.post("/rules", json=_rule_body(acct, name), headers=bearer(maker))
        assert r.status_code == 201, r.text
    names = {i["name"] for i in _rules(world, "manager_with_grant")}
    assert names == {"mine"}, "a manager with one grant must never see another user's rows"
    assert {i["name"] for i in _rules(world, "owner")} == {"mine", "theirs", "owners"}
    assert _rules(world, "manager_without_grant") == []
    assert _rules(world, "viewer") == []


def test_scope_is_part_of_the_query_not_a_post_filter(world: World) -> None:
    """SQL-predicate hook: the rules store is asked for rows, and visibility is decided from the
    caller's grants *inside* `RulesManager._visible` (before pagination), so a page of `limit`
    rows can never be short-changed by rows a post-filter would drop."""
    for i in range(3):
        world.client.post("/rules", json=_rule_body(FOREIGN, f"f{i}"), headers=bearer("owner"))
    world.client.post(
        "/rules", json=_rule_body(GRANTED, "m0"), headers=bearer("manager_with_grant")
    )
    page = world.client.get("/rules", params={"limit": 1}, headers=bearer("manager_with_grant"))
    names = [i["name"] for i in page.json()["items"]]
    assert names == ["m0"], "pagination must run over the already-scoped set"
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
    why = f"{method} {path}: a target-user parameter must be rejected, got {resp.status_code}"
    assert resp.status_code in (400, 422), why


def test_self_service_reads_are_always_about_the_caller(world: World) -> None:
    mgr = world.client.get("/auth/session", headers=bearer("manager_with_grant"))
    assert mgr.status_code == 200
    assert mgr.json()["user"]["id"] == str(user_id_of("manager_with_grant"))


#: The accounts each seeded actor may reach (`GET /me`): an owner every account, a manager its
#: grants, a viewer or an ungranted manager none.
_ME_ACCOUNTS = {
    "owner": {str(GRANTED), str(FOREIGN)},
    "manager_with_grant": {str(GRANTED)},
    "manager_without_grant": set(),
    "viewer": set(),
}


@pytest.mark.parametrize("actor", ACTORS[:4])
def test_me_is_always_about_the_caller_with_their_own_role_and_accounts(
    world: World, actor: str
) -> None:
    """The shell bootstrap (#2713): the identity, role and account scope come from the verified
    session alone, so each actor reads exactly their own and never another user's."""
    resp = world.client.get("/me", headers=bearer(actor))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["id"] == str(user_id_of(actor))
    assert body["role"] == ROLE_OF[actor]
    assert {a["exchange_account_id"] for a in body["accounts"]} == _ME_ACCOUNTS[actor]
    assert body["session"]["session_id"] == str(uuid.uuid5(user_id_of(actor), "session"))
    assert body["session"]["environment"] == world.app.state.app_context.settings.environment.value


@pytest.mark.parametrize("actor", ACTORS[:4])
def test_me_preferences_and_keymap_serve_the_contract_defaults_to_every_role(
    world: World, actor: str
) -> None:
    """Every role holds `settings:read`; nothing is stored yet, so each gets the empty answer."""
    prefs = world.client.get("/me/preferences", headers=bearer(actor))
    keymap = world.client.get("/me/keymap", headers=bearer(actor))
    assert (prefs.status_code, prefs.json()) == (200, {"_meta": {"overridden": []}})
    assert (keymap.status_code, keymap.json()) == (200, {"bindings": []})


def test_a_session_in_the_read_only_downgrade_still_reads_the_bootstrap(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`403 session_read_only` is a refusal of writes; the bootstrap reads stay served."""

    async def read_only(_session_id: str) -> None:
        raise SessionReadOnly(datetime.now(UTC) + timedelta(minutes=5))

    monkeypatch.setattr(world.step_up, "assert_writable", read_only)
    write = world.client.put(
        f"/users/{user_id_of('viewer')}/roles", json={"roles": ["viewer"]}, headers=bearer("owner")
    )
    assert write.status_code == 403 and write.json()["code"] == "session_read_only"
    for path in ("/me", "/me/preferences", "/me/keymap"):
        assert world.client.get(path, headers=bearer("owner")).status_code == 200, path


#: The executed self-service routes (x-rbac `scope: self`), which take no target-user parameter.
#: `GET /onboarding/checklist` is `not_executable` in this pack (501 in the CI app), so it is not
#: listed; its refusal is asserted in tests/unit/api/test_onboarding_checklist.py.
_SELF_SERVICE_QUERY_ROUTES = [
    ("GET", "/auth/session"),
    ("GET", "/auth/sessions"),
    ("GET", "/me"),
    ("GET", "/me/preferences"),
    ("GET", "/me/keymap"),
    ("POST", "/auth/logout"),
    ("DELETE", "/me/sessions/{sessionId}"),
    ("GET", "/alerts"),
    ("GET", "/alerts/{alertId}"),
]


@pytest.mark.parametrize(("method", "path"), _SELF_SERVICE_QUERY_ROUTES)
@pytest.mark.parametrize("actor", ACTORS[:4])  # every authenticated role
def test_self_service_routes_reject_a_target_user_query_parameter(
    world: World, method: str, path: str, actor: str
) -> None:
    """SR-026 (#2573, #2632): a target-user parameter is refused (422), never silently ignored,
    for every role and whichever other user it names. The refusal carries no data and writes no
    audit record, so nothing was revoked."""
    target = next(a for a in ACTORS[:4] if a != actor)
    resp = world.client.request(
        method, fill_path(path), params={"user_id": str(user_id_of(target))}, headers=bearer(actor)
    )
    assert resp.status_code == 422, f"{method} {path} as {actor}: got {resp.status_code}"
    body = resp.json()
    assert body["code"] == "validation_failed"
    assert "user_id" in body["detail"]
    assert not {"user", "session", "items"} & set(body), "a refusal carries no data"
    assert world.audit.records == [], "a refused call is not audited and revokes nothing"


#: A valid `POST /admin/recorder/purge` body (22-api-openapi.yaml `purgeRecordedData`), so the
#: call can only be refused for who sends it or for the missing step-up, never as malformed.
_PURGE_BODY = {"symbol": "BTCUSDT", "confirm_symbol": "BTCUSDT", "reason": "free disk"}
#: Purge also requires an `Idempotency-Key`; the other administrative mutations take none.
_IDEMPOTENCY_KEY = "00000000-0000-4000-8000-0000000000e1"
_KEYED_MUTATIONS = {("POST", "/admin/recorder/purge")}

_ADMIN_MUTATIONS = [
    ("PUT", "/users/{uid}/roles", {"roles": ["viewer"]}),
    ("POST", "/users", {}),
    ("POST", "/users/{uid}/invite", None),
    ("DELETE", "/users/{uid}/invite", None),
    ("POST", "/users/{uid}/mfa/reset", None),
    ("POST", "/admin/recorder/purge", _PURGE_BODY),  # 04 §7.2.2 row 9a; mounted by E16-T06 (#490)
]  # fmt: skip


def _admin_headers(actor: str, method: str, path: str) -> dict[str, str]:
    """`bearer(actor)` plus the `Idempotency-Key` the contract requires on purge."""
    if (method, path) in _KEYED_MUTATIONS:
        return {**bearer(actor), "Idempotency-Key": _IDEMPOTENCY_KEY}
    return bearer(actor)


def _job_ids(world: World) -> set[str]:
    jobs: dict[str, Any] = world.app.state.admin_jobs._jobs
    return set(jobs)


@pytest.mark.parametrize(("method", "path", "body"), _ADMIN_MUTATIONS)
@pytest.mark.parametrize("actor", ["manager_with_grant", "manager_without_grant", "viewer"])
def test_administrative_mutations_are_owner_only(
    world: World, method: str, path: str, body: Any, actor: str
) -> None:
    world.step_up.elevated = True  # even a fully elevated non-owner session is refused
    jobs_before = _job_ids(world)
    url = path.format(uid=user_id_of("viewer"))
    resp = world.client.request(method, url, json=body, headers=_admin_headers(actor, method, path))
    assert resp.status_code == 403
    assert world.users.roles == world.users.initial_roles, "a refused call must not mutate roles"
    assert world.purge_backend.calls == [], "a refused call must not plan or run a purge"
    assert _job_ids(world) == jobs_before, "a refused call must not start a job"


@pytest.mark.parametrize(("method", "path", "body"), _ADMIN_MUTATIONS)
def test_administrative_mutations_require_step_up_even_for_the_owner(
    world: World, method: str, path: str, body: Any
) -> None:
    world.step_up.elevated = False
    jobs_before = _job_ids(world)
    url = path.format(uid=user_id_of("viewer"))
    resp = world.client.request(
        method, url, json=body, headers=_admin_headers("owner", method, path)
    )
    assert resp.status_code == 403
    assert resp.json().get("code") == "step_up_required"
    assert world.users.roles == world.users.initial_roles
    assert world.purge_backend.calls == [] and _job_ids(world) == jobs_before


#: Owner-only, step-up-gated mutations the app does not serve yet. Mounting one fails
#: `test_unmounted_administrative_mutations_are_not_served_yet` until it moves into
#: `_ADMIN_MUTATIONS` with a request body, so the two tests above cover it (#2575). E16-T06
#: (#490) mounted `POST /admin/recorder/purge` and moved it into `_ADMIN_MUTATIONS`.
_ADMIN_MUTATIONS_UNMOUNTED: list[tuple[str, str]] = [
    ("POST", "/risk/lockouts/{accountId}/override"),  # 04 §7.2.2 row 34; mounted by E39-S02 (#955)
]
#: The matrix row of an Owner-only operation (the `POST /admin/audit/verify` shape).
_OWNER_ONLY_OUTCOMES = {
    "owner": "allow",
    "manager_with_grant": "403",
    "manager_without_grant": "403",
    "viewer": "403",
    "unauthenticated": "401",
}
_OWNER_ONLY_MUTATIONS = [(m, p) for m, p, _ in _ADMIN_MUTATIONS] + _ADMIN_MUTATIONS_UNMOUNTED


def _shape(path: str) -> str:
    """`/users/{uid}/roles` here and `/users/{userId}/roles` in the matrix are one operation."""
    return re.sub(r"\{[^}]+\}", "{}", path)


def _matrix_outcomes(method: str, path: str) -> dict[str, str]:
    from tests.contract.rbac.test_route_matrix import _OPS

    rows = [
        row["outcomes"]
        for key, row in _OPS.items()
        if key.split(" ", 1)[0] == method and _shape(key.split(" ", 1)[1]) == _shape(path)
    ]
    assert len(rows) == 1, f"{method} {path}: expected one matrix row, found {len(rows)}"
    outcomes: dict[str, str] = rows[0]
    return outcomes


@pytest.mark.parametrize(("method", "path"), _OWNER_ONLY_MUTATIONS)
def test_administrative_mutation_rows_are_owner_only_even_while_unmounted(
    method: str, path: str
) -> None:
    """#2575, #2625: an Owner-only narrowing within a permission Managers hold (purge:
    `recording:write`, 04 §7.2.2 row 9a; lockout override: `killswitch:write`, row 34) lives only
    in the matrix, so the row must refuse every non-Owner before the route is mounted; a Manager
    `allow` would certify a handler that lets any Manager purge or clear a risk lockout."""
    assert _matrix_outcomes(method, path) == _OWNER_ONLY_OUTCOMES, f"{method} {path}"


def test_unmounted_administrative_mutations_are_not_served_yet(world: World) -> None:
    """#492/#955 guard: once the app serves one of `_ADMIN_MUTATIONS_UNMOUNTED`, this fails until
    the route moves into `_ADMIN_MUTATIONS`, so the Owner-only and step-up tests cannot miss it.
    The two tests above format paths with `uid` only; a route with another path parameter
    (`{accountId}`) needs them extended when it moves, never the assertions weakened."""
    served = {(m, _shape(p)) for m, p in served_operations(world.app)}
    now_served = [f"{m} {p}" for m, p in _ADMIN_MUTATIONS_UNMOUNTED if (m, _shape(p)) in served]
    assert not now_served, (
        "now served: move these into _ADMIN_MUTATIONS with a request body so the Owner-only "
        "and step-up tests run against them: " + ", ".join(now_served)
    )


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
    machine = family.startswith("machines.")  # §6.4: scoped by its entity, not by options
    account = GRANTED if row["scope"] == "granted_accounts" and not machine else None
    if machine:
        seed_machine(world.app, row, actor)
    started = time.perf_counter()
    msg = f"topic {family} as {actor}: expected {expected}"
    try:
        with world.client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
            if actor != "unauthenticated":
                assert _auth(ws, actor)["t"] == "auth_ok"
            else:
                _hello(ws)
            result = _sub(ws, row["sample"], account)
        observed = "sub_ok" if result["ok"] else result["error"]["code"]
        assert observed == expected, f"{msg}, got {observed}"
    except BaseException:
        record_cell("ws", f"WS {family}", actor, "fail", started)
        raise
    record_cell("ws", f"WS {family}", actor, "pass", started)


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


# -- `system` content per role (SR-188, 23-ws-protocol.md §15.9; #2175) -------------------------

_KINDS_ENUM = json.loads(
    (Path(__file__).resolve().parents[5] / "docs" / "plan" / "ws-schema.json").read_text("utf-8")
)["schemas"]["cv://ws/v1/system.schema.json"]["properties"]["kind"]["enum"]
#: Every role receives it whole; reading up to it proves nothing else was queued before it.
_MARK = {"kind": "notice", "severity": "info", "message": "marker", "reason": "test.marker"}
_HALT = {"engaged": True, "scope": "accounts", "exchange_account_ids": [str(GRANTED), str(FOREIGN)]}
_WHO = {"engaged_by": str(user_id_of("owner")), "reason": "halt"}  # the Owner's, as `actions`
_OMS = {"name": "oms", "state": "degraded"}  # a health component; `detail` is the Owner's
#: An `all_roles` flag, an `owner_only` one and a key no flag definition names (E42-T03).
_FLAGS = {"trading.one_click": True, "storage.cold_tier": True, "test.undefined": True}
_SEEN = {"trading.one_click": True}  # what a Manager or Viewer may learn of them
#: One frame per `system_kinds` row, carrying the kind's Owner-only fields where it has any.
_SYSTEM_SAMPLES: dict[str, dict[str, Any]] = {
    "clock_drift": {"kind": "clock_drift", "severity": "warning", "clock_offset_ms": 900},
    "connection_quality": {"kind": "connection_quality", "class": "lagging", "queue_pct": 30},
    "degraded_data": {"kind": "degraded_data", "degraded_topics": ["heatmap.BTCUSDT"]},
    "exchange_state": {"kind": "exchange_state", "public_ws": "resyncing"},
    "feature_flags": {"kind": "feature_flags", "feature_flags": _FLAGS},
    "health": {
        "kind": "health",
        "health": "degraded",
        "components": [_OMS | {"detail": "x"}],
        "feature_flags": _FLAGS,
    },
    "kill_switch": {
        "kind": "kill_switch",
        "kill_switch": _HALT | _WHO,
        "actions": {"rules_disarmed": 1},
    },
    "notice": {"kind": "notice", "severity": "critical", "reason": "net.binding_check_failed"},
    "shutdown_notice": {"kind": "shutdown_notice", "reason": "deploy", "closing_in_ms": 5000},
    "unknown": {"kind": "tick"},
}


def _system_rows() -> dict[str, dict[str, str]]:
    from tests.contract.rbac.test_route_matrix import _MATRIX

    rows: dict[str, dict[str, str]] = _MATRIX["system_kinds"]
    return rows


def _neutral(kind: str, actor: str) -> dict[str, Any]:
    """The role-neutral view, written out: no Owner-only field, accounts cut to the actor's,
    flag keys to the ones the actor's role may learn."""
    if kind == "health":
        return {
            "kind": "health",
            "health": "degraded",
            "components": [_OMS],
            "feature_flags": _SEEN,
        }
    if kind == "feature_flags":
        return {"kind": "feature_flags", "feature_flags": _SEEN}
    mine = [str(GRANTED)] if actor == "manager_with_grant" else []
    return {"kind": "kill_switch", "kill_switch": _HALT | {"exchange_account_ids": mine}}


def _until_mark(ws: Any, hub: Any) -> list[Any]:
    """The `system` bodies queued for `ws` before now, read up to the marker."""
    ws.portal.call(hub.broadcast_system, _MARK)  # on the app's own loop, as a producer runs
    seen: list[Any] = []
    while (frame := _recv(ws)).get("p") != _MARK:
        seen.append(frame.get("p"))
    return seen


def test_system_kind_matrix_is_total_over_the_contract_kinds() -> None:
    rows = _system_rows()
    assert set(rows) == {*_KINDS_ENUM, "unknown"} == set(_SYSTEM_SAMPLES)
    for kind, row in rows.items():
        assert set(row) == set(ACTORS), kind
        assert set(row.values()) <= {"whole", "neutral", "none"}, kind
        assert row["unauthenticated"] == "none", kind


@pytest.mark.parametrize(
    ("kind", "actor"),
    [pytest.param(k, a, id=f"{k}|{a}") for k in sorted(_SYSTEM_SAMPLES) for a in ACTORS],
)
def test_every_system_kind_x_actor_matches_the_matrix(world: World, kind: str, actor: str) -> None:
    expected = _system_rows()[kind][actor]
    sample = _SYSTEM_SAMPLES[kind]
    want = {"whole": [sample], "neutral": [_neutral(kind, actor)], "none": []}[expected]
    hub = world.app.state.ws_hub
    started = time.perf_counter()
    try:
        with world.client.websocket_connect("/ws", subprotocols=["cv.v1.json"]) as ws:
            if actor == "unauthenticated":
                _hello(ws)
                ws.portal.call(hub.broadcast_system, sample)
                ws.send_json({"t": "sub", "id": "s", "p": {"topics": ["system"]}})
                first = _recv(ws)  # the refusal, unless a `system` frame was queued before it
                got = [] if first["t"] == "err" else [first.get("p")]
            else:
                assert _auth(ws, actor)["t"] == "auth_ok"
                _until_mark(ws, hub)  # whatever `auth_ok` queued
                ws.portal.call(hub.broadcast_system, sample)
                got = _until_mark(ws, hub)
        assert got == want, f"system {kind} as {actor}: expected {expected}, got {got}"
    except BaseException:
        record_cell("ws", f"WS system.{kind}", actor, "fail", started)
        raise
    record_cell("ws", f"WS system.{kind}", actor, "pass", started)
