"""E42-X03 (#1026): the admin abuse cases `main` can run today and no other test already holds.

Seeds: `docs/security/threat-models/e42-admin.md` §9.2 (AC-ADM-nn) and the user-lifecycle annex §4
(UL-ACnn). Each case drives the real `create_app()`, with the real `AuthService` (sessions, MFA,
step-up and its B16 chart) over in-memory fakes, a fixed clock and no network (C-13.5, C-13.7).
The audit stand-ins refuse an unregistered action as `AuditWriter.emit` does. The catalogue,
`docs/security/abuse-cases/e42-admin.md`, lists every seed with the test that holds it or the
ticket it waits on; `test_abuse_catalogue.py` keeps the two in step.

Held elsewhere: the RBAC cells (`test_cells_*.py`) hold AC-ADM-01, -02, -03 and -32 for every admin
and users route. The last-owner races (AC-ADM-28, UL-AC03), the disabled invitee's old link
(UL-AC14), the append-only trigger case for a privileged role that is not the owner
(AC-ADM-15) and the two-connection insert case (AC-ADM-16, #889 S3) need Postgres:
`tests/integration/admin/` and `tests/integration/audit/`.

Waiting on other tickets (recorded in the catalogue, never skipped):
- AC-ADM-12: `POST /orders` (E29-T07).
- AC-ADM-20 past its 501, and AC-ADM-21: E42-T02 (#889), decision D1.
- AC-ADM-23 at the route, and AC-ADM-24: #3084.
- AC-ADM-25 through the routes: a verifier wired by the backup engine (#3319), and
  `restoreBackup` (E42-T05, #966).
- AC-ADM-30: D8 (#1085).
- AC-ADM-31: #3196.
- AC-ADM-33: a principal resolver for `PUT /admin/log-level`.
- AC-ADM-34's summary: E43-S02.
- AC-ADM-35's engage-to-frame: #956.
- UL-AC12, UL-AC13: E42-T10 (#2650).
- UL-AC15's unbind: E42-T08 (#2648).
"""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Iterator
from typing import Any, cast

import httpx
import pytest

import candleviewer.app as appmod
from candleviewer.admin.flags import catalogue
from candleviewer.admin.flags.registry import Category, FlagSpec, UnsafeFlagDefinitionError
from candleviewer.api.deny_by_default import served_operations
from candleviewer.api.view_as_policy import OWN_OPERATIONS, PROTECTIVE_WRITES
from candleviewer.auth.generated_permissions import Permission
from candleviewer.statechart.bindings import b16_session
from tests.contract.rbac import rbac_harness as matrix
from tests.security.admin._world import (
    ORIGIN,
    VIEW_AS_REFUSAL_BUDGET,
    AdminWorld,
    open_admin_world,
)
from tests.security.auth._stack import PW as STACK_PW
from tests.security.auth._stack import Stack, open_stack
from tests.security.auth.test_invite_http_abuse import _INVITE, _invite, _owner, _redeem
from tests.unit.api.test_view_as_gate import _contract_own_operations

#: Parallel attempts per race: enough to interleave on one loop, as a real burst would.
N = 10


@pytest.fixture
def stack(monkeypatch: pytest.MonkeyPatch) -> Iterator[Stack]:
    with open_stack(monkeypatch) as s:
        yield s


@pytest.fixture
def admin(monkeypatch: pytest.MonkeyPatch, b16_audit: object) -> Iterator[AdminWorld]:
    """A world of the RBAC suite's own (`_world.py`), one per test: these cases change state."""
    with open_admin_world(monkeypatch) as world:
        b16_session.set_audit_sink(world.audit)  # as `create_app` wires it (see `conftest.py`)
        yield world


def _burst(world: AdminWorld, actor: str, method: str, path: str, body: Any) -> list[Any]:
    """`N` identical requests at once, on the app's own loop."""

    async def run() -> list[httpx.Response]:
        transport = httpx.ASGITransport(app=world.app, client=("127.0.0.1", 50000))
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
            headers = {"origin": ORIGIN, **world.headers(actor)}
            sends = (client.request(method, path, json=body, headers=headers) for _ in range(N))
            return await asyncio.gather(*sends)

    portal = world.client.portal
    assert portal is not None
    return portal.call(run)


def _records(world: AdminWorld, action: str, actor: str) -> list[dict[str, Any]]:
    uid = str(world.actors[actor].user_id)
    return [
        r
        for r in world.audit.records
        if r["action"] == action and str(r.get("actor_user_id")) == uid
    ]


def _outcome(record: dict[str, Any]) -> str:
    outcome = record.get("outcome")
    return str(getattr(outcome, "value", outcome)).lower()


# -- AC-ADM-27: invite-link replay; `createUser` with MFA off -------------------------------------


def test_ac_adm_27_a_spent_invite_link_answers_as_an_unknown_one(stack: Stack) -> None:
    owner = _owner(stack)
    token = _invite(stack, owner)
    assert _redeem(stack, token).status_code == 200
    redeemed = len(stack.audit.of("users.invite_redeemed"))
    unknown = "A" * len(token)  # well-formed, never issued
    confirm = {"method_id": "00000000-0000-4000-8000-000000000001", "code": "000000"}
    for method, suffix, body in (
        ("GET", "", None),  # validate
        ("POST", "", {"password": STACK_PW}),  # redeem
        ("POST", "/confirm", confirm),  # confirm the enrolment
    ):
        spent = stack.client.request(method, f"/invites/{token}{suffix}", json=body)
        never = stack.client.request(method, f"/invites/{unknown}{suffix}", json=body)
        assert (spent.status_code, spent.json()) == (never.status_code, never.json())
        assert spent.status_code == 404, spent.text
    assert len(stack.audit.of("users.invite_redeemed")) == redeemed  # nothing redeemed twice


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="AD-F10 (#3086): `createUser` still accepts `mfa_required: false` (C-12.2)",
)
def test_ac_adm_27_create_user_refuses_mfa_not_required(stack: Stack) -> None:
    owner = _owner(stack)
    refused = stack.client.post("/users", headers=owner, json={**_INVITE, "mfa_required": False})
    assert refused.status_code in (400, 422), refused.text  # 400 or 422: note 7, decision D9
    assert not stack.audit.of("users.invited")


# -- AC-ADM-05: TOTP replay at the step-up --------------------------------------------------------


def test_ac_adm_05_a_replayed_code_strikes_three_times_then_the_session_reads_only(
    stack: Stack,
) -> None:
    headers, seed = stack.principal("owner", "owner", Permission.USERS_WRITE)
    assert stack.client.post("/users", headers=headers, json=_INVITE).status_code == 403
    assert stack.step_up(headers, seed).status_code == 200  # this time step's code is spent
    failed = stack.in_process("auth_stepup_failures_total")
    replay = {"code": stack.code(seed), "password": STACK_PW, "action_class": "users"}
    answers = [stack.client.post("/auth/step-up", headers=headers, json=replay) for _ in range(3)]
    assert [a.status_code for a in answers] == [401, 401, 403], [a.text for a in answers]
    assert [a.json().get("failures_remaining") for a in answers[:2]] == [2, 1]
    assert {a.json()["code"] for a in answers[:2]} == {"mfa_invalid"}
    assert answers[2].json()["code"] == "session_read_only"
    write = stack.client.post("/users", headers=headers, json=_INVITE)
    assert (write.status_code, write.json()["code"]) == (403, "session_read_only")
    assert stack.in_process("auth_stepup_failures_total") - failed == 3
    assert len(stack.audit.of("auth.step_up_failed")) == 3
    assert len(stack.audit.of("auth.session_readonly_downgrade")) == 1


# -- AC-ADM-13: a flag gating authentication refuses boot -----------------------------------------


def test_ac_adm_13_create_app_refuses_a_flag_that_gates_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A definition that escaped its constructor check (forced past it here, as
    `test_flag_registry.py` does) still stops `create_app` (SR-E42-07, AD-F09)."""
    valid = next(spec for spec in catalogue.FLAGS if spec.key == "trading.one_click")
    smuggled = object.__new__(FlagSpec)
    for each in dataclasses.fields(FlagSpec):  # every field, so a new one never leaves this stale
        object.__setattr__(smuggled, each.name, getattr(valid, each.name))
    object.__setattr__(smuggled, "key", "ui.sneaky_auth")
    object.__setattr__(smuggled, "gates", Category.AUTH)
    monkeypatch.setattr(catalogue, "FLAGS", (*catalogue.FLAGS, smuggled))
    with pytest.raises(UnsafeFlagDefinitionError, match=r"ui\.sneaky_auth"):
        appmod.create_app()


# -- AC-ADM-15, the API half: nothing mutates the audit log ---------------------------------------


def test_ac_adm_15_no_route_mutates_the_audit_log(admin: AdminWorld) -> None:
    audit_routes = {
        f"{m} {p}" for m, p in served_operations(admin.app) if p.startswith("/admin/audit")
    }
    assert audit_routes == {
        "GET /admin/audit",
        "POST /admin/audit/verify",
        "POST /admin/audit/export",
        "GET /admin/audit/exports/{jobId}",  # #889 S9: a read; nothing mutates the log
        "GET /admin/audit/signing-keys",  # #889 S7: a read of the signing keys, not of the log
    }
    admin.elevate(["audit"])  # the Owner's strongest standing: a live `audit` window
    before = len(admin.audit.records)
    for method in ("PUT", "PATCH", "DELETE"):
        for path in ("/admin/audit", "/admin/audit/1", "/admin/audit/verify"):
            refused = admin.send("owner", method, path, {})
            assert refused.status_code in (404, 405), (method, path, refused.status_code)
    assert len(admin.audit.records) == before  # refused before any guard or handler ran


# -- Role escalation and grant self-assignment under concurrent writes ----------------------------


def test_parallel_self_promotions_by_a_manager_all_fail_and_each_is_audited(
    admin: AdminWorld,
) -> None:
    manager = "manager_with_grant"
    admin.elevate(["users"])  # past the step-up path guard: RBAC itself must refuse
    uid = admin.actors[manager].user_id
    answers = _burst(admin, manager, "PUT", f"/users/{uid}/roles", {"roles": ["owner"]})
    assert [(a.status_code, a.json()["code"]) for a in answers] == [(403, "forbidden")] * N
    assert len(_records(admin, "rbac.denied", manager)) == N
    assert admin.roles.roles[uid] == frozenset({"manager"})
    assert not [r for r in admin.audit.records if r["action"] in ("roles.grant", "roles.revoke")]


def test_parallel_grant_self_assignments_by_the_owner_all_fail_and_each_is_audited(
    admin: AdminWorld,
) -> None:
    admin.elevate(["users"])
    uid = admin.actors["owner"].user_id
    body = {"grants": [{"exchange_account_id": str(matrix.GRANTED), "access": "trade"}]}
    path = f"/users/{uid}/account-access?acknowledge_unknown_positions=false"
    answers = _burst(admin, "owner", "PUT", path, body)
    assert [a.status_code for a in answers] == [403] * N, [a.text for a in answers]
    refusals = [r for r in _records(admin, "rbac.denied", "owner") if r["reason"] == "self_target"]
    assert len(refusals) == N
    assert admin.access.grants[uid] == [] and admin.access.calls == []  # refused before any read


# -- AC-ADM-06, AC-ADM-07: a flag write demands the class its key and stored value choose ---------

_EVIDENCE = "https://github.com/CandleViewer/CandleViewer/issues/412"


def _flag_put(world: AdminWorld, key: str, body: dict[str, Any]) -> httpx.Response:
    """`PUT /admin/feature-flags/{key}` as the Owner, naming the flag's `updated_at` as read."""
    listed = world.send("owner", "GET", "/admin/feature-flags", {}).json()["items"]
    [item] = [i for i in listed if i["key"] == key]
    request = {"json": {**body, "expected_updated_at": item["updated_at"]}}
    return world.send("owner", "PUT", f"/admin/feature-flags/{key}", request)


def _flag_value(world: AdminWorld, key: str) -> Any:
    listed = world.send("owner", "GET", "/admin/feature-flags", {}).json()["items"]
    [item] = [i for i in listed if i["key"] == key]
    return item["value"]


def _challenged(answer: httpx.Response) -> tuple[int, str, str]:
    doc = answer.json()
    return answer.status_code, doc.get("code", ""), doc.get("action_class", "")


def _changes(world: AdminWorld, key: str) -> list[tuple[str, str]]:
    """The Owner's `flags.change` records of `key`: (outcome, reason)."""
    return [
        (_outcome(r), r["reason"])
        for r in _records(world, "flags.change", "owner")
        if r["object_id"] == key
    ]


def test_ac_adm_06_the_live_gate_needs_its_own_step_up_and_its_evidence_first(
    admin: AdminWorld,
) -> None:
    admin.elevate(["flags"])  # a `flags` window only
    key = "trading.live_enabled"
    live = {"value": True, "reason": "pen test passed", "evidence_url": _EVIDENCE}
    assert _challenged(_flag_put(admin, key, live)) == (403, "step_up_required", "live_enablement")
    challenges = _records(admin, "auth.step_up_required", "owner")
    assert [r["reason"] for r in challenges] == ["live_enablement"]  # audited, never zero
    assert _changes(admin, key) == []  # the challenge alone: `auth.step_up_required` only
    without = _flag_put(admin, key, {"value": True, "reason": "pen test passed"})
    assert without.status_code == 422, without.text
    assert without.json()["errors"] == [{"field": "evidence_url", "rule": "gate_evidence_required"}]
    assert _records(admin, "auth.step_up_required", "owner") == challenges  # refused first
    assert _changes(admin, key) == [("failure", "gate_evidence_required")]  # the 422's record
    assert _flag_value(admin, key) is False  # nothing written


def test_ac_adm_07_a_kill_switch_releases_only_on_its_own_class_and_maintenance_engages_on_flags(
    admin: AdminWorld,
) -> None:
    admin.elevate(["flags"])  # a `flags` window only
    key, mode = "killswitch.order_entry", "maintenance.mode"
    engaged = _flag_put(admin, key, {"value": True, "reason": "drill"})
    assert engaged.status_code == 200, engaged.text  # stopping trading never waits for a code
    assert ("success", "drill") in _changes(admin, key)
    assert _challenged(_flag_put(admin, key, {"value": False, "reason": "drill over"})) == (
        403,
        "step_up_required",
        "killswitch",
    )
    challenges = _records(admin, "auth.step_up_required", "owner")
    assert [r["reason"] for r in challenges] == ["killswitch"]  # the release's challenge, audited
    assert _flag_value(admin, key) is True  # still engaged
    mark, owner = len(admin.audit.records), str(admin.actors["owner"].user_id)
    on = _flag_put(admin, mode, {"value": True, "reason": "drill"})  # the same `flags` grant
    assert on.status_code == 200, on.text
    engage = {
        (r["action"], _outcome(r), r.get("reason"), r.get("object_id"))
        for r in admin.audit.records[mark:]
        if str(r.get("actor_user_id")) == owner
    }
    graced = {(a, o, why) for a, o, why, _ in engage}  # the grace record names no object
    assert ("auth.step_up_grace_used", "success", "flags") in graced
    assert ("flags.change", "success", "drill", mode) in engage
    assert {a for a, _, _, obj in engage if obj == mode} >= {"flags.change", "maintenance.enabled"}
    assert _flag_value(admin, mode) is True


# -- AC-ADM-22: a view-as session cannot mutate ----------------------------------------------------

#: The state-changing methods: view-as refuses by the method, never by the effect (22 "View-as
#: session", "Read-only").
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
#: An all-roles UI flag that is on by default: a write turns it off, so one that got through can be
#: read back.
_UI_FLAG = "rules.graph_editor"


def _coded(answer: httpx.Response) -> tuple[int, Any]:
    """An answer's status and its problem `code` (None for a body with none, or not JSON)."""
    try:
        doc = answer.json()
    except ValueError:
        doc = None
    return answer.status_code, doc.get("code") if isinstance(doc, dict) else None


def _flag_updated_at(world: AdminWorld, key: str) -> Any:
    listed = world.send("owner", "GET", "/admin/feature-flags", {}).json()["items"]
    [item] = [i for i in listed if i["key"] == key]
    return item["updated_at"]


def _held(world: AdminWorld) -> dict[str, Any]:
    """What a write the guard let through would change in this world: each user's roles, the grants
    and who read them, and each session's revocation and view-as context."""
    sessions = cast(Any, world.auth.view_as_store).sessions  # the fake store's rows
    return {
        "roles": dict(world.roles.roles),
        "grants": {user: list(grants) for user, grants in world.access.grants.items()},
        "grant_reads": list(world.access.calls),
        "sessions": {sid: (row.revoked_at, row.view_as) for sid, row in sessions.items()},
    }


def test_ac_adm_22_view_as_cannot_mutate(admin: AdminWorld) -> None:
    """The deployed composition's whole path (the S13b security look's Low-2): an Owner starts
    viewing as a Manager, `201`, which `GET /auth/session/view-as` reads back `active`, with the
    start's record written and the Manager told, and ends it, `204` and its record. In between
    the Owner sends every state-changing operation the app serves. Each but the viewer's own is
    refused `403 view_as_read_only` and changes nothing, and each is recorded as the contract
    says (22 "View-as session"): one `admin.view_as_refused`, outcome `denied`, naming the
    operation's template, the viewer as actor and the viewer's session, never the Manager, and none
    gets past the guard to the router, so no handler runs. The routes come from the app's router,
    as `test_ac_adm_15` reads the audit routes, so a new write route cannot escape the case, and
    the world's refusal cap is above the sweep (`VIEW_AS_REFUSAL_BUDGET`), which the case asserts.
    The carve-out is the contract's list of the viewer's own operations, which the guard reads: a
    second start is the start route's own refusal, and leaving is never refused. No protective
    write is registered yet (E39-S03, E29-T07, E34-S03), so none is carved out; the day one is,
    this case must say what it admits."""
    owner, manager = admin.actors["owner"], admin.actors["manager_with_grant"]
    admin.elevate(["users", "flags"])  # the start's step-up class, and the control write's
    stamp = _flag_updated_at(admin, _UI_FLAG)
    start = {"json": {"target_user_id": str(manager.user_id), "reason": "AC-ADM-22"}}
    started = admin.send("owner", "POST", "/admin/view-as", start)
    assert started.status_code == 201, started.text
    assert ("POST", "/admin/view-as") in admin.reached  # a request the guards pass is seen
    context = started.json()
    assert (context["target_user_id"], context["target_username"]) == (
        str(manager.user_id),
        "manager_with_grant",
    )
    assert (context["state"], context["read_only"]) == ("active", True)
    read = admin.send("owner", "GET", "/auth/session/view-as", {})
    assert (read.status_code, read.json()) == (200, context)  # the context the start answered
    (begun,) = _records(admin, "admin.view_as_started", "owner")  # written ahead
    assert (begun["object_id"], str(begun["session_id"])) == (
        str(manager.user_id),
        str(owner.session_id),
    )
    assert begun["after_state"]["reason"] == "AC-ADM-22"
    assert begun["actor_ip"] == "127.0.0.1"  # the request's address, as `admin.area_entered` has it
    (notice,) = cast(Any, admin.auth.view_as_store).notices  # the Manager is told
    assert notice.target_user_id == manager.user_id and "'owner'" in notice.message
    assert "AC-ADM-22" not in notice.message  # the viewer by name, never the reason

    unsafe = {op for op in served_operations(admin.app) if op[0] in _UNSAFE_METHODS}
    protective = [operation for operation, _ in PROTECTIVE_WRITES.values()]
    assert not [op for op in protective if admin.app.state.protective_writes.is_registered(op)]
    assert _contract_own_operations() == OWN_OPERATIONS  # the contract's list, read from its prose
    carved_out = {op for op in unsafe if op in OWN_OPERATIONS}
    assert carved_out == {op for op in OWN_OPERATIONS if op[0] in _UNSAFE_METHODS}, carved_out
    swept = sorted(unsafe - carved_out)
    assert len(swept) < VIEW_AS_REFUSAL_BUDGET  # one record each: the sweep fits the world's cap
    ids = {  # the viewed Manager's user and session, and a flag whose write can be read back
        "userId": str(manager.user_id),
        "sessionId": str(manager.session_id),
        "flagKey": _UI_FLAG,
    }
    attempts: dict[tuple[str, str], dict[str, Any]] = {  # sent whole: a bypass would take effect
        ("PUT", "/users/{userId}/roles"): {"roles": ["owner"]},
        ("PUT", "/admin/feature-flags/{flagKey}"): {
            "value": False,
            "reason": "AC-ADM-22",
            "expected_updated_at": stamp,
        },
    }
    assert set(attempts) <= set(swept)  # so the sweep is never empty

    before, mark, routed = _held(admin), len(admin.audit.records), len(admin.reached)
    counted = Stack.in_process("auth_view_as_refused_total", reason="view_as_read_only")
    answers: dict[tuple[str, str], tuple[int, Any]] = {}
    for method, template in swept:
        path = matrix.fill_path(template, ids)
        answers[method, template] = _coded(
            admin.send("owner", method, path, {"json": attempts.get((method, template))})
        )
    assert {op: a for op, a in answers.items() if a != (403, "view_as_read_only")} == {}
    assert admin.reached[routed:] == []  # none got past the guard to the router: no handler ran
    assert _held(admin) == before  # nothing changed

    written = admin.audit.records[mark:]
    assert {r["action"] for r in written} == {"admin.view_as_refused"}  # no handler ran to record
    assert len(written) == len(swept)  # one each
    assert {(r["after_state"]["method"], r["after_state"]["path"]) for r in written} == set(swept)
    assert all(r["object_id"] == r["after_state"]["path"] for r in written)
    assert {(r["object_kind"], r["reason"], _outcome(r)) for r in written} == {
        ("operation", "view_as_read_only", "denied")
    }
    viewer = (str(owner.user_id), "owner", str(owner.session_id))  # never the Manager
    assert {(str(r["actor_user_id"]), r["actor_label"], str(r["session_id"])) for r in written} == {
        viewer
    }
    refused = Stack.in_process("auth_view_as_refused_total", reason="view_as_read_only")
    assert refused - counted == len(swept)

    second = admin.send("owner", "POST", "/admin/view-as", start)  # the viewer's own: not refused
    assert _coded(second) == (409, "view_as_active")  # as the start route answers it, not read-only
    left = admin.send("owner", "DELETE", "/auth/session/view-as", {})
    assert left.status_code == 204, left.text  # leaving is one call nothing refuses
    assert admin.client.portal is not None
    admin.client.portal.call(admin.app.state.csrf_refusal_audits.drain)  # the end's record lands
    (ended,) = _records(admin, "admin.view_as_ended", "owner")
    assert (ended["reason"], ended["object_id"], str(ended["session_id"])) == (
        "ended",
        str(manager.user_id),
        str(owner.session_id),
    )
    assert ended["actor_ip"] == "127.0.0.1"  # the leave's address
    assert _flag_value(admin, _UI_FLAG) is True  # the refused write changed nothing
    accepted = _flag_put(admin, _UI_FLAG, {"value": False, "reason": "AC-ADM-22"})
    assert accepted.status_code == 200, accepted.text  # the same write, once the view has ended
    assert _flag_value(admin, _UI_FLAG) is False
