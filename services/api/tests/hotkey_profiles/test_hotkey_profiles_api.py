"""`/settings/hotkeys*` through its router over the in-memory store (E10-T05, #5211): each Gherkin
scenario of the ticket that the server answers, a Viewer writing and another user's profile on
every operation, 22's refusal orders, the view-as backstop, `If-Match` and the weak `ETag`, the
caps, the outages and the write-ahead audit. The answers against 22 itself, through the real app:
tests/contract/hotkey_profiles/; the router over Postgres: the integration module."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from candleviewer.api.hotkey_profiles import (
    CONFLICT_RULES,
    INVALID_RULES,
    REFUSAL_SERIES,
    make_hotkey_profiles_router,
)
from candleviewer.api.hotkey_rules import VOCABULARY
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories.hotkey_profiles import MAX_PROFILES
from tests.hotkey_profiles._hotkey_env import (
    FOOTPRINT,
    MISSING,
    SCALPING,
    SID,
    USER_A,
    USER_B,
    VIEWER,
    Audit,
    Env,
    tag,
)

_REWRITTEN = "Hotkey-Bindings-Rewritten"
_KEYMAP: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[4] / "apps/web/src/keymap/keymap.json").read_text("utf-8")
)


@pytest.fixture
def env() -> Env:
    return Env()


def _client_default() -> list[dict[str, Any]]:
    """`profileStore.ts`'s `input()` with nothing changed: every command of `keymap.json`, in its
    order, at its default, with the scope 22's table gives its context (the vocabulary carries
    it, held to the table by its freshness test) and the keymap's `requiresArm` and `confirm`."""
    return [
        {"action": c["id"], "keys": c["defaultBinding"],
         "scope": VOCABULARY.commands[c["id"]].scope,
         "requires_arm": c.get("requiresArm") is True, "confirm": c.get("confirm") is True}
        for c in _KEYMAP["commands"]
    ]  # fmt: skip


def _binding(action: str, keys: str, scope: str, **flags: Any) -> dict[str, Any]:
    return {"action": action, "keys": keys, "scope": scope, **flags}


def _rules(r: Any) -> list[tuple[str, str]]:
    return [(e.get("field", ""), e["rule"]) for e in r.json()["errors"]]


# -- the Gherkin scenarios, as the server answers them -------------------------------------------


def test_scenario_a_profile_follows_its_owner_to_another_device(env: Env) -> None:
    """Scenario: a profile follows its owner to another device. The Owner's remap of "Toggle
    footprint" to Ctrl+Alt+F is stored and made active, so a second device's session reads it
    back (`/me/keymap` reads the active profile: tests/unit/api/test_me_router.py)."""
    made = env.create()
    active = env.activate(made["id"])
    assert (active.status_code, active.json()["is_active"]) == (200, True)
    (listed,) = env.listed()
    assert listed["is_active"] and listed["bindings"] == [
        FOOTPRINT | {"requires_arm": False, "confirm": False}
    ]
    stored = env.store.rows[uuid.UUID(made["id"])].bindings
    assert stored == {"chart.footprint_toggle": "Ctrl+Alt+F"}


def test_scenario_a_viewer_stays_on_the_device(env: Env) -> None:
    """Scenario: a Viewer stays on the device. The client sends a Viewer's remap nowhere; were one
    sent, every write is `403 forbidden`, audited `rbac.denied`, and nothing is stored."""
    env.user = VIEWER
    writes = [
        env.c.post("/settings/hotkeys", json=SCALPING),
        env.put(MISSING, SCALPING),
        env.delete(MISSING),
        env.activate(MISSING),
    ]
    assert [(r.status_code, r.json()["code"]) for r in writes] == [(403, "forbidden")] * 4
    assert all(r.json()["required_permissions"] == ["settings:write"] for r in writes)
    assert env.audit.actions() == ["rbac.denied"] * 4 and env.store.rows == {}
    assert env.listed() == []  # the Viewer reads: settings:read


def test_scenario_another_users_profile_does_not_exist(env: Env) -> None:
    """Scenario: another user's profile does not exist. A replace, a delete or an activation of
    another user's profile id is the 404 of an id no one holds, byte for byte, nothing changes,
    and the list never names it."""
    theirs = env.store.seed(USER_B, "Theirs", is_active=False)
    before = dict(env.store.rows)
    as_theirs = {"If-Match": f'W/"{theirs.id}:1"'}
    foreign = [env.put(theirs.id, SCALPING, as_theirs), env.delete(theirs.id),
               env.activate(theirs.id)]  # fmt: skip
    missing = [env.put(MISSING, SCALPING, as_theirs), env.delete(MISSING), env.activate(MISSING)]
    assert [r.status_code for r in foreign + missing] == [404] * 6
    assert [r.content for r in foreign] == [r.content for r in missing]
    assert env.store.rows == before and env.listed() == []
    assert [(c["action"], c["object_id"]) for c in env.audit.calls] == [
        ("rbac.denied", str(theirs.id))
    ] * 3  # the three probes of another user's profile; an id no one holds leaves no record


def test_scenario_the_clients_own_default_profile_is_accepted(env: Env) -> None:
    """Scenario: the client's own default profile is accepted. Every command at its default, the
    non-chord shapes and the three locked commands included, is 201 and nothing is rewritten."""
    default = _client_default()
    assert len(default) == len(VOCABULARY.commands) == 76
    r = env.c.post("/settings/hotkeys", json={"name": "Default", "bindings": default})
    assert r.status_code == 201, r.text
    assert _REWRITTEN not in r.headers
    assert r.json()["bindings"] == default  # in the keymap's order, as sent


def test_scenario_a_conflicting_pair_is_refused_by_name(env: Env) -> None:
    """Scenario: a conflicting pair is refused, by name: 409 naming both commands, nothing
    stored. But the declared F11 shadow and two unbound commands in one scope are no conflict."""
    pair = [_binding("chart.footprint_toggle", "Alt+Q", "chart"),
            _binding("chart.undo", "Alt+Q", "chart")]  # fmt: skip
    r = env.c.post("/settings/hotkeys", json={"name": "Pair", "bindings": pair})
    assert (r.status_code, r.json()["code"]) == (409, "conflict")
    assert [(e["field"], e["rule"], e["message"].split()[4]) for e in r.json()["errors"]] == [
        ("bindings[1].keys", "binding_conflict", "chart.footprint_toggle"),
        ("bindings[0].keys", "binding_conflict", "chart.undo"),
    ]
    assert env.store.rows == {} and env.audit.calls == []
    shadow = [_binding("global.fullscreen", "F11", "global"),
              _binding("workspace.fullscreen_panel", "F11", "workspace")]  # fmt: skip
    unbound = [_binding("ticket.side_buy", "", "ticket"),
               _binding("ticket.side_sell", "", "ticket")]  # fmt: skip
    for name, bindings in (("Shadow", shadow), ("Unbound", unbound)):
        assert env.c.post("/settings/hotkeys", json={"name": name, "bindings": bindings}
                          ).status_code == 201  # fmt: skip


def test_scenario_the_server_keeps_the_arm_on_an_order_submit(env: Env) -> None:
    """Scenario: the server keeps the arm on an order submit. `requires_arm: false` on
    `ticket.submit` (a `placeOrder` submit) is stored and answered as true, and the answer names
    it in `Hotkey-Bindings-Rewritten`; the rewrite runs the other way on a protective command."""
    submit = _binding("ticket.submit", "Ctrl+Enter", "ticket", requires_arm=False)
    cancel_all = _binding("dom.cancel_all", "Ctrl+Shift+X", "dom", requires_arm=True)
    r = env.c.post("/settings/hotkeys", json={"name": "Arm", "bindings": [submit, cancel_all]})
    assert (r.status_code, r.headers[_REWRITTEN]) == (201, "ticket.submit, dom.cancel_all")
    flags = {b["action"]: (b["requires_arm"], b["confirm"]) for b in r.json()["bindings"]}
    assert flags == {"ticket.submit": (True, True), "dom.cancel_all": (False, True)}
    assert env.listed()[0]["bindings"] == r.json()["bindings"]
    put = env.put(r.json()["id"], {"name": "Arm", "bindings": [submit]})
    assert (put.status_code, put.headers[_REWRITTEN]) == (200, "ticket.submit")
    assert put.json()["bindings"][0]["requires_arm"] is True


@pytest.mark.parametrize(
    ("body", "field", "rule"),
    [
        (SCALPING | {"owner_user_id": str(USER_B)}, "owner_user_id", "extra_forbidden"),
        ({"name": "X", "bindings": [FOOTPRINT | {"armed": True}]}, "bindings[0].armed",
         "extra_forbidden"),
        ({"name": "X", "bindings": [_binding("chart.teleport", "Q", "chart")]},
         "bindings[0].action", "unknown_action"),
    ],
)  # fmt: skip
def test_scenario_unknown_fields_and_unknown_actions_are_refused(
    env: Env, body: dict[str, Any], field: str, rule: str
) -> None:
    """Scenario: unknown fields and unknown actions are refused: 422 with a problem code, and
    nothing is stored, on a create and on a replace alike."""
    made = env.create()
    for r in (env.c.post("/settings/hotkeys", json=body), env.put(made["id"], body)):
        assert (r.status_code, r.json()["code"], _rules(r)) == (
            422, "validation_failed", [(field, rule)])  # fmt: skip
    assert env.listed() == [made] and env.audit.actions() == ["hotkey_profile.created"]


def test_scenario_every_change_is_audited(env: Env) -> None:
    """Scenario: every change is audited. One record per create, replace, activation and delete,
    with the actor, the profile id, its name and its binding count, written ahead; never a
    binding."""
    one, two = env.create(), env.create(name="Swing", bindings=[])
    assert env.activate(one["id"]).status_code == 200
    renamed = env.put(two["id"], SCALPING | {"name": "Swing 2"})
    assert env.activate(two["id"]).status_code == 200
    assert env.delete(one["id"]).status_code == 204
    shape = {"actor_label": str(USER_A), "actor_user_id": USER_A, "actor_ip": "10.0.0.9",
             "session_id": SID, "request_id": None, "object_kind": "hotkey_profile",
             "outcome": AuditOutcome.SUCCESS, "severity": Severity.INFO}  # fmt: skip
    state = {"name": "Scalping", "binding_count": 1, "is_active": False}
    swing = {"name": "Swing", "binding_count": 0, "is_active": False}
    assert env.audit.calls == [
        shape | {"action": "hotkey_profile.created", "object_id": one["id"],
                 "before_state": None, "after_state": state},
        shape | {"action": "hotkey_profile.created", "object_id": two["id"],
                 "before_state": None, "after_state": swing},
        shape | {"action": "hotkey_profile.activated", "object_id": one["id"],
                 "before_state": state | {"previous_active_id": None},
                 "after_state": state | {"is_active": True}},
        shape | {"action": "hotkey_profile.updated", "object_id": two["id"],
                 "before_state": swing, "after_state": state | {"name": "Swing 2"}},
        shape | {"action": "hotkey_profile.activated", "object_id": two["id"],
                 "before_state": state | {"name": "Swing 2", "previous_active_id": one["id"]},
                 "after_state": state | {"name": "Swing 2", "is_active": True}},
        shape | {"action": "hotkey_profile.deleted", "object_id": one["id"],
                 "before_state": state, "after_state": None},
    ]  # fmt: skip
    assert renamed.status_code == 200
    assert "Ctrl+Alt+F" not in json.dumps(env.audit.calls, default=str)


def test_scenario_a_refusal_never_stalls_the_client_on_the_servers_side(env: Env) -> None:
    """Scenario: a refusal never stalls the client. The server's half: a permanent refusal is
    told from a transient one by its status, its code and its rule (CR-305C-04), and a refused
    profile leaves later changes free to sync."""
    made = env.create()
    permanent = env.c.post("/settings/hotkeys", json={"name": "Bad", "bindings": [
        _binding("ticket.submit", "S", "ticket")]})  # fmt: skip
    assert (permanent.status_code, _rules(permanent)) == (
        422, [("bindings[0].keys", "bare_letter_dangerous")])  # fmt: skip
    assert "retry_after_seconds" not in permanent.json()
    env.audit.fail = AuditUnavailable("wal full")
    transient = env.put(made["id"], SCALPING | {"name": "Later"})
    assert (transient.status_code, transient.json()["code"]) == (503, "audit_unavailable")
    assert (transient.headers["Retry-After"], transient.json()["retry_after_seconds"]) == ("5", 5)
    env.audit.fail = None
    later = env.put(made["id"], SCALPING | {"name": "Later"})
    assert (later.status_code, later.json()["name"], later.json()["version"]) == (200, "Later", 2)


# -- 22's refusal orders ---------------------------------------------------------------------------


def _huge() -> dict[str, Any]:
    """A body one byte past 22's 64 KiB, which no rule reads: 413 before anything else."""
    return {"content": b"{" + b" " * (64 * 1024) + b"}", "headers": {"content-type": "x"}}


def test_a_create_answers_413_then_422_then_409_in_22s_order(env: Env) -> None:
    """413, then 422, then 409: `binding_conflict`, then `limit_reached`, then `name_taken`."""
    made = env.create()
    pair = [_binding("chart.footprint_toggle", "Alt+Q", "chart"),
            _binding("chart.undo", "Alt+Q", "chart")]  # fmt: skip
    invalid = {"name": "Scalping", "bindings": [*pair, _binding("chart.teleport", "Q", "chart")]}
    assert env.c.post("/settings/hotkeys", **_huge()).status_code == 413
    assert _rules(env.c.post("/settings/hotkeys", json=invalid)) == [
        ("bindings[2].action", "unknown_action")]  # fmt: skip
    clash = env.c.post("/settings/hotkeys", json={"name": "Scalping", "bindings": pair})
    assert [rule for _, rule in _rules(clash)] == ["binding_conflict"] * 2
    for n in range(MAX_PROFILES - 1):
        env.create(name=f"P{n}", bindings=[])
    full = env.c.post("/settings/hotkeys", json=SCALPING)  # Scalping is taken too
    assert (full.status_code, full.json()["errors"]) == (409, [
        {"rule": "limit_reached", "message": full.json()["detail"]}])  # fmt: skip
    assert len(env.listed()) == MAX_PROFILES and env.listed()[0] == made


def test_a_replace_answers_413_404_412_422_then_409_in_22s_order(env: Env) -> None:
    """413, then 404 (a tag never tells another user's profile apart from none), then 412, then
    422, then 409: `binding_conflict`, then `name_taken`."""
    made, other = env.create(), env.create(name="Other", bindings=[])
    theirs = env.store.seed(USER_B)
    pair = [_binding("chart.footprint_toggle", "Alt+Q", "chart"),
            _binding("chart.undo", "Alt+Q", "chart")]  # fmt: skip
    invalid = {"name": "Scalping", "bindings": [*pair, _binding("chart.teleport", "Q", "chart")]}
    assert env.c.put(f"/settings/hotkeys/{theirs.id}", **_huge()).status_code == 413
    assert env.put(theirs.id, invalid, {"If-Match": "*"}).status_code == 404
    assert env.put("not-a-uuid", invalid, {"If-Match": "*"}).status_code == 404
    assert env.put(other["id"], invalid, {"If-Match": "*"}).status_code == 412
    assert _rules(env.put(other["id"], invalid, tag(other))) == [
        ("bindings[2].action", "unknown_action")]  # fmt: skip
    taken_and_clashing = {"name": "SCALPING", "bindings": pair}
    clash = env.put(other["id"], taken_and_clashing, tag(other))
    assert [rule for _, rule in _rules(clash)] == ["binding_conflict"] * 2
    taken = env.put(other["id"], {"name": "SCALPING", "bindings": []}, tag(other))
    assert (taken.status_code, _rules(taken)) == (409, [("name", "name_taken")])
    assert env.listed() == [made, other]


def test_a_delete_answers_404_before_409_profile_active(env: Env) -> None:
    made = env.create()
    env.activate(made["id"])
    theirs = env.store.seed(USER_B, is_active=True)
    assert env.delete(theirs.id).status_code == 404  # active, but not the caller's
    active = env.delete(made["id"])
    assert (active.status_code, active.json()["errors"]) == (409, [
        {"rule": "profile_active", "message": active.json()["detail"]}])  # fmt: skip
    assert [p["id"] for p in env.listed()] == [made["id"]]


# -- the forbidden role and another user's profile, on every operation ---------------------------


@pytest.mark.parametrize("operation", ["create", "update", "delete", "activate"])
def test_a_viewer_writing_is_403_audited_and_reads_nothing(env: Env, operation: str) -> None:
    """The forbidden role: `settings:write` is refused before the store is read or the body."""
    mine = env.store.seed(VIEWER, "Mine")
    env.user, env.store.fail = VIEWER, OSError("a store read would answer 503")
    sent = {
        "create": lambda: env.c.post("/settings/hotkeys", **_huge()),
        "update": lambda: env.c.put(f"/settings/hotkeys/{mine.id}", **_huge()),
        "delete": lambda: env.delete(mine.id),
        "activate": lambda: env.activate(mine.id),
    }[operation]()
    assert (sent.status_code, sent.json()["code"]) == (403, "forbidden")
    (denied,) = env.audit.calls
    assert (denied["action"], denied["reason"]) == (
        "rbac.denied", "missing_permission:settings:write:self")  # fmt: skip
    env.store.fail = None
    assert env.store.rows == {mine.id: mine}


def test_a_viewer_lists_its_own_profiles_and_no_one_elses(env: Env) -> None:
    env.store.seed(USER_A, "A's")
    mine = env.store.seed(VIEWER, "Mine")
    env.user = VIEWER
    assert [p["id"] for p in env.listed()] == [str(mine.id)]


@pytest.mark.parametrize("operation", ["update", "delete", "activate"])
def test_another_users_profile_is_a_404_and_nothing_changes(env: Env, operation: str) -> None:
    """The cross-user case on each write by id: the 404 of an id no one holds, the probe audited
    `rbac.denied` (`not_owner`), their profile untouched and never listed to the caller."""
    theirs = env.store.seed(USER_B, "Theirs", is_active=False)
    send = {
        "update": lambda pid: env.put(pid, SCALPING, {"If-Match": f'W/"{pid}:1"'}),
        "delete": env.delete,
        "activate": env.activate,
    }[operation]
    probe, missing = send(theirs.id), send(MISSING)
    assert (probe.status_code, probe.content) == (404, missing.content)
    assert probe.json()["code"] == "not_found"
    assert env.store.rows == {theirs.id: theirs} and env.listed() == []
    (denied,) = env.audit.calls
    assert denied == {
        "action": "rbac.denied", "actor_label": str(USER_A), "actor_user_id": USER_A,
        "actor_ip": "10.0.0.9", "session_id": SID, "request_id": None,
        "object_kind": "hotkey_profile", "object_id": str(theirs.id),
        "outcome": AuditOutcome.DENIED, "severity": Severity.WARNING,
        "reason": "not_owner:settings:write:self",
    }  # fmt: skip


def test_the_list_never_names_another_users_profile(env: Env) -> None:
    env.store.seed(USER_B, "Theirs", is_active=True)
    mine = env.create()
    assert env.listed() == [mine]
    env.user = USER_B
    assert [p["name"] for p in env.listed()] == ["Theirs"]


@pytest.mark.parametrize("refusal", [AuditUnavailable("wal full"), RuntimeError("no writer")])
def test_a_probe_whose_record_cannot_be_written_is_still_the_same_404(
    env: Env, refusal: Exception
) -> None:
    theirs = env.store.seed(USER_B)
    env.audit.fail = refusal
    with capture_logs() as logs:
        probe = env.activate(theirs.id)
    assert (probe.status_code, probe.content) == (404, env.activate(MISSING).content)
    assert [(log["event"], log["error"]) for log in logs] == [
        ("hotkey_profile_denial_unaudited", type(refusal).__name__)]  # fmt: skip
    assert env.store.rows == {theirs.id: theirs}


def test_a_path_id_that_is_no_uuid_is_a_404_with_no_record(env: Env) -> None:
    answers = [env.put("not-a-uuid", SCALPING), env.delete("x"), env.activate("1234")]
    assert {(r.status_code, r.json()["code"]) for r in answers} == {(404, "not_found")}
    assert env.audit.calls == []


# -- view-as (#3085, BQ-14) ------------------------------------------------------------------------


def test_a_view_reads_the_targets_profiles(env: Env) -> None:
    """Reads answer the target to the viewer, as every `scope: self` read does."""
    theirs = env.store.seed(USER_B, "Theirs")
    env.store.seed(USER_A, "The viewer's own")
    env.user, env.viewing = USER_B, USER_A
    assert [p["id"] for p in env.listed()] == [str(theirs.id)]


@pytest.mark.parametrize("operation", ["create", "update", "delete", "activate"])
def test_a_write_under_a_view_is_refused_view_as_read_only_before_anything_is_read(
    env: Env, operation: str
) -> None:
    """The guard refuses it first; this backstop answers the same, before RBAC, the body or the
    store: no record, nothing read."""
    theirs = env.store.seed(USER_B, "Theirs")
    env.user, env.viewing, env.store.fail = USER_B, USER_A, OSError("no store read")
    sent = {
        "create": lambda: env.c.post("/settings/hotkeys", **_huge()),
        "update": lambda: env.c.put(f"/settings/hotkeys/{theirs.id}", **_huge()),
        "delete": lambda: env.delete(theirs.id),
        "activate": lambda: env.activate(theirs.id),
    }[operation]()
    assert (sent.status_code, sent.json()["code"]) == (403, "view_as_read_only")
    assert env.audit.calls == []
    env.store.fail = None
    assert env.store.rows == {theirs.id: theirs}


# -- versions: `If-Match` and the weak `ETag` (BQ-10) ----------------------------------------------


def test_a_replace_bumps_the_version_and_answers_its_etag(env: Env) -> None:
    made = env.c.post("/settings/hotkeys", json=SCALPING)
    body = made.json()
    assert (made.headers["ETag"], body["version"], body["is_active"]) == (
        f'W/"{body["id"]}:1"', 1, False)  # fmt: skip
    put = env.put(body["id"], SCALPING | {"name": "Two"}, tag(body))
    assert (put.status_code, put.headers["ETag"], put.json()["version"]) == (
        200, f'W/"{body["id"]}:2"', 2)  # fmt: skip
    assert put.json()["created_at"] == body["created_at"] < put.json()["updated_at"]
    assert "etag" not in env.c.get("/settings/hotkeys").headers  # a listed tag is built by hand


def test_a_replace_without_if_match_is_last_write_wins(env: Env) -> None:
    """`If-Match` is optional (22 `IfMatch`): with none, a replace applies at any version."""
    made = env.create()
    env.put(made["id"], SCALPING | {"name": "Elsewhere"}, tag(made))  # another device, v2
    r = env.put(made["id"], SCALPING | {"name": "Here"})
    assert (r.status_code, r.json()["name"], r.json()["version"]) == (200, "Here", 3)


@pytest.mark.parametrize(
    "value",
    ["*", 'W/"{id}:1", W/"{id}:2"', 'W/"{other}:2"', '"{id}:2"', 'W/"{id}:0"',
     'W/"{id}:99999999999"', "junk", 'W/"{id}:1"'],
)  # fmt: skip
def test_a_tag_that_names_no_current_version_is_412_and_changes_nothing(
    env: Env, value: str
) -> None:
    made = env.create()
    current = env.put(made["id"], SCALPING | {"name": "Two"}, tag(made)).json()
    sent = {"If-Match": value.format(id=made["id"], other=MISSING)}
    r = env.put(made["id"], SCALPING | {"name": "Stale"}, sent)
    assert (r.status_code, r.json()["code"], r.headers["ETag"]) == (
        412, "version_conflict", f'W/"{made["id"]}:2"')  # fmt: skip
    assert env.listed() == [current] and ("conflict", "version_conflict") not in env.refusals.counts


def test_a_writer_between_the_read_and_the_replace_is_a_412_naming_its_version(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store compares the version under its lock: one that moves after the router's read is
    `HotkeyProfileStaleError`, answered 412 with that version's `ETag`."""
    made, write = env.create(), env.store.replace

    async def raced(owner: uuid.UUID, pid: uuid.UUID, *args: Any, **kw: Any) -> Any:
        env.store.rows[pid] = replace(env.store.rows[pid], version=2)  # another writer commits
        return await write(owner, pid, *args, **kw)

    monkeypatch.setattr(env.store, "replace", raced)
    r = env.put(made["id"], SCALPING | {"name": "Mine"}, tag(made))
    assert (r.status_code, r.headers["ETag"]) == (412, f'W/"{made["id"]}:2"')
    assert env.audit.actions() == ["hotkey_profile.created"]


def test_a_profile_deleted_between_the_read_and_the_replace_is_a_404(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    made, write = env.create(), env.store.replace

    async def vanished(owner: uuid.UUID, pid: uuid.UUID, *args: Any, **kw: Any) -> Any:
        del env.store.rows[pid]  # another session deletes it first
        return await write(owner, pid, *args, **kw)

    monkeypatch.setattr(env.store, "replace", vanished)
    r = env.put(made["id"], SCALPING | {"name": "Mine"})
    assert (r.status_code, r.json()["code"], env.store.rows) == (404, "not_found", {})


# -- activation: one active profile, no record when nothing changes --------------------------------


def test_an_activation_swaps_the_active_profile_and_keeps_versions(env: Env) -> None:
    one, two = env.create(), env.create(name="Swing")
    first = env.activate(one["id"])
    swap = env.activate(two["id"])
    assert (swap.status_code, swap.headers["ETag"]) == (200, f'W/"{two["id"]}:1"')
    assert swap.json() == two | {"is_active": True}  # version and updated_at stay
    assert [(p["id"], p["is_active"]) for p in env.listed()] == [
        (one["id"], False), (two["id"], True)]  # fmt: skip
    assert first.json() == one | {"is_active": True}
    activated = [c for c in env.audit.calls if c["action"] == "hotkey_profile.activated"]
    assert [c["before_state"]["previous_active_id"] for c in activated] == [None, one["id"]]


def test_activating_the_active_profile_changes_nothing_and_writes_no_record(env: Env) -> None:
    made = env.create()
    env.activate(made["id"])
    calls = list(env.audit.calls)
    with capture_logs() as logs:
        again = env.activate(made["id"])
    assert (again.status_code, again.headers["ETag"]) == (200, f'W/"{made["id"]}:1"')
    assert again.json() == made | {"is_active": True}
    assert env.audit.calls == calls and logs == []


# -- the caps and the outages ----------------------------------------------------------------------


def test_a_body_past_64_kib_is_413_and_one_not_json_is_422(env: Env) -> None:
    """22: a body over 64 KiB is `413 payload_too_large`, read before it is parsed."""
    made = env.create()
    big = {"name": "Big", "bindings": [FOOTPRINT | {"params": {"pad": "x" * 70_000}}]}
    sent = {"content": json.dumps(big).encode(), "headers": {"content-type": "application/json"}}
    for r in (env.c.post("/settings/hotkeys", **sent),
              env.c.put(f"/settings/hotkeys/{made['id']}", **sent)):  # fmt: skip
        assert (r.status_code, r.json()["code"]) == (413, "payload_too_large")
    bad = env.c.post("/settings/hotkeys", content=b"{",
                     headers={"content-type": "application/json"})  # fmt: skip
    assert (bad.status_code, _rules(bad)) == (422, [("", "json_invalid")])
    assert env.listed() == [made]


async def test_a_streamed_body_past_64_kib_with_no_length_is_413(env: Env) -> None:
    """With no `Content-Length` the stream is read only until it passes the cap."""
    pulled: list[int] = []

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(64):  # 64 chunks of 4 KiB: 256 KiB on offer
            pulled.append(1)
            yield b" " * 4096

    transport = httpx.ASGITransport(app=env.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post("/settings/hotkeys", content=chunks(),
                              headers={"content-type": "application/json"})  # fmt: skip
    assert (r.status_code, r.json()["code"]) == (413, "payload_too_large")
    assert "content-length" not in r.request.headers and len(pulled) <= 64 * 1024 // 4096 + 1
    assert env.listed() == []


def _retry(r: Any) -> tuple[int, str, str, int]:
    """A 503 as 22 shapes it: its code, `Retry-After` and `retry_after_seconds`."""
    body = r.json()
    return r.status_code, body["code"], r.headers["Retry-After"], body["retry_after_seconds"]


def test_no_session_is_401_on_every_operation(env: Env) -> None:
    env.user = None
    answers = [env.c.get("/settings/hotkeys"), env.c.post("/settings/hotkeys", json=SCALPING),
               env.put(MISSING, SCALPING), env.delete(MISSING), env.activate(MISSING)]  # fmt: skip
    assert {(r.status_code, r.json()["code"]) for r in answers} == {(401, "unauthenticated")}


def test_no_store_or_a_store_outage_is_503_store_unavailable(env: Env) -> None:
    env.store_up = False
    down = [env.c.get("/settings/hotkeys"), env.c.post("/settings/hotkeys", json=SCALPING)]
    assert {_retry(r) for r in down} == {(503, "store_unavailable", "5", 5)}
    assert down[0].json()["detail"] == "The hotkey profile store is unavailable."
    env.store_up, env.store.fail = True, OSError("connection refused")
    with capture_logs() as logs:
        outage = [env.c.get("/settings/hotkeys"), env.delete(MISSING), env.activate(MISSING)]
    assert {_retry(r) for r in outage} == {(503, "store_unavailable", "5", 5)}
    assert {(log["event"], log["error"]) for log in logs} == {
        ("hotkey_profiles_store_unavailable", "OSError")}  # fmt: skip


def test_a_store_error_that_is_no_outage_propagates(env: Env) -> None:
    """A defect is never dressed as an outage: it reaches the server's error handling."""
    env.store.fail = LookupError("a defect, not an outage")
    with pytest.raises(LookupError):
        env.c.get("/settings/hotkeys")


@pytest.mark.parametrize(
    "refusal", [AuditUnavailable("wal full"), RuntimeError("no writer"), WriteAheadTimeout("slow")]
)
def test_a_record_not_written_is_503_audit_unavailable_and_nothing_changes(
    env: Env, refusal: Exception
) -> None:
    """Written ahead (C-2.9): the store awaits each record before it commits, so a record that
    is not written (refused, no writer, or past the store's bound) changes nothing, on every
    write."""
    one, two = env.create(), env.create(name="Swing")
    env.activate(one["id"])
    rows = dict(env.store.rows)
    env.audit.fail = refusal
    answers = [
        env.c.post("/settings/hotkeys", json=SCALPING | {"name": "New"}),
        env.put(one["id"], SCALPING | {"name": "New"}),
        env.activate(two["id"]),
        env.delete(two["id"]),
    ]
    assert {_retry(r) for r in answers} == {(503, "audit_unavailable", "5", 5)}
    assert env.store.rows == rows


def test_a_viewers_denial_that_cannot_be_written_is_503_audit_unavailable(env: Env) -> None:
    """With no audit writer started, `enforce` cannot write the denial: nothing is answered as
    allowed, and the write is not made."""
    env.user, env.audit.fail = VIEWER, RuntimeError("no writer")
    r = env.c.post("/settings/hotkeys", json=SCALPING)
    assert _retry(r) == (503, "audit_unavailable", "5", 5) and env.store.rows == {}


def test_the_router_refuses_to_build_without_an_audit_emitter() -> None:
    with pytest.raises(TypeError, match="audit emitter is required"):
        make_hotkey_profiles_router(lambda: None, None, cast(Any, None))


def test_no_resolver_fails_closed_with_401() -> None:
    app = FastAPI()
    app.include_router(make_hotkey_profiles_router(lambda: None, None, Audit()))
    assert TestClient(app).get("/settings/hotkeys").status_code == 401


# -- the refusal counter and the logs --------------------------------------------------------------


def test_each_409_and_422_is_counted_once_by_code_and_rule(env: Env) -> None:
    """`hotkey_profile_refusals_total{code,rule}`: a 409 by its rule, a 422 by its first item's
    rule, a schema refusal as `schema`; a 404, 412 or 413 is not counted."""
    made = env.create()
    env.activate(made["id"])
    pair = [_binding("chart.footprint_toggle", "Alt+Q", "chart"),
            _binding("chart.undo", "Alt+Q", "chart")]  # fmt: skip
    sent = [
        env.c.post("/settings/hotkeys", json={"name": "P", "bindings": pair}),
        env.c.post("/settings/hotkeys", json=SCALPING),  # name taken
        env.c.post(
            "/settings/hotkeys",
            json={
                "name": "U",
                "bindings": [
                    _binding("chart.teleport", "Q", "chart"),
                    _binding("chart.undo", "Q!", "chart"),
                ],
            },
        ),
        env.c.post("/settings/hotkeys", json={"name": "S", "bindings": [], "extra": 1}),
        env.c.post("/settings/hotkeys", json={"name": "N\x00", "bindings": []}),
        env.delete(made["id"]),  # the active one
        env.put(made["id"], SCALPING, {"If-Match": "*"}),  # 412: not counted
        env.delete(MISSING),  # 404: not counted
        env.c.post("/settings/hotkeys", **_huge()),  # 413: not counted
    ]
    assert [r.status_code for r in sent] == [409, 409, 422, 422, 422, 409, 412, 404, 413]
    assert env.refusals.counts == {
        ("conflict", "binding_conflict"): 1, ("conflict", "name_taken"): 1,
        ("validation_failed", "unknown_action"): 1, ("validation_failed", "schema"): 1,
        ("validation_failed", "invalid_character"): 1, ("conflict", "profile_active"): 1,
    }  # fmt: skip
    assert set(CONFLICT_RULES) | set(INVALID_RULES) >= {r for _, r in env.refusals.counts}
    assert REFUSAL_SERIES == len(CONFLICT_RULES) + len(INVALID_RULES) == 15


def test_logs_carry_ids_counts_and_codes_never_a_name_or_a_binding(env: Env) -> None:
    with capture_logs() as logs:
        made = env.create(name="Secret name")
        env.put(made["id"], SCALPING | {"name": "Secret name"})
        env.activate(made["id"])
        env.c.post("/settings/hotkeys", json={"name": "Secret name", "bindings": [FOOTPRINT]})
        other = env.create(name="Another secret")
        env.delete(other["id"])
    assert [log["event"] for log in logs] == [
        "hotkey_profile_created", "hotkey_profile_updated", "hotkey_profile_activated",
        "hotkey_profile_refused", "hotkey_profile_created", "hotkey_profile_deleted",
    ]  # fmt: skip
    refused = logs[3]
    assert {k: refused[k] for k in ("operation", "code", "rule")} == {
        "operation": "create", "code": "conflict", "rule": "name_taken"}  # fmt: skip
    blob = json.dumps(logs, default=str)
    assert "Secret" not in blob and "Ctrl+Alt+F" not in blob and "footprint" not in blob
