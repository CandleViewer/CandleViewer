"""#4834 (E35 authoring limits, G-13): a `note` or `reason` is at most `MAX_NOTE_CHARS` characters.

The four writes (`createRule`, `updateRule`, `setActiveRuleVersion`, `setRuleMode`) refuse a longer
one whole, never shortened: `422 rule_ir_invalid` with `errors[{field, rule: "max_length"}]`
(22 `noteTooLong`), after the unstorable-text `400` and before the scope check, so it writes no
audit record, and a live arm's refused `reason` spends no step-up grant. Characters are Unicode
code points. The manager holds every write to the same bound whoever calls it, and each refusal is
counted under `cap` `note` or `reason`.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from prometheus_client import generate_latest

from candleviewer.api.rules_crud import make_rules_crud_router
from candleviewer.app import _RuleCompileTelemetry
from candleviewer.observability.metrics import Metrics
from candleviewer.observability.metrics_catalogue import register_r0
from candleviewer.rules.limits import MAX_NOTE_CHARS, NOTE_BOUND_DETAIL, NOTE_BOUND_MESSAGE
from candleviewer.rules.manager import (
    REFUSED_CAPS,
    RULE_IR_INVALID_TITLE,
    Actor,
    InMemoryRuleStore,
    RuleCapRefused,
    RuleError,
    RuleRow,
    RulesManager,
)
from candleviewer.rules.vocabulary import default_registry
from tests.rules.test_rule_check_limit import _series
from tests.rules.test_rules_manager import OWNER, _mgr
from tests.rules.test_rules_routes import ARM, BASE, LIVE, _ir
from tests.rules.test_scope_crud import A, C, _scoped, _setup

LONG = "n" * (MAX_NOTE_CHARS + 1)
FULL = "n" * MAX_NOTE_CHARS
#: 280 characters outside the Basic Multilingual Plane: 1,120 UTF-8 bytes, 560 UTF-16 units.
ASTRAL = "\U0001f600" * MAX_NOTE_CHARS
REG = default_registry()


def _refusal(field: str) -> dict[str, Any]:
    """The problem a refused `note` or `reason` answers, as 22's `noteTooLong` example shows it."""
    return {
        "type": "https://candleviewer.local/errors/rule_ir_invalid",
        "title": RULE_IR_INVALID_TITLE,
        "status": 422,
        "code": "rule_ir_invalid",
        "detail": NOTE_BOUND_DETAIL,
        "errors": [{"field": field, "rule": "max_length", "message": NOTE_BOUND_MESSAGE}],
    }


class _Env:
    """The write routes over an in-memory manager: its audit records, `on_cap_refused`'s calls and
    the one live step-up grant the actor holds."""

    def __init__(
        self,
        perms: frozenset[str] = frozenset(BASE),
        uid: str = "u1",
        counter: Callable[[str], None] | None = None,
    ) -> None:
        self.audits: list[tuple[str, dict[str, Any]]] = []
        self.capped: list[str] = []
        self.grants = 1

        def capped(cap: str) -> None:
            self.capped.append(cap)
            if counter is not None:
                counter(cap)

        async def audit(action: str, payload: dict[str, Any]) -> None:
            self.audits.append((action, payload))

        async def consume() -> bool:
            if self.grants <= 0:
                raise RuleError(403, "step_up_required", "Step-up required.")
            self.grants -= 1
            return True

        self.mgr = RulesManager(InMemoryRuleStore(), REG, audit=audit)
        self.actor = Actor(
            uid, "s1", perms, is_owner=True, step_up_fresh=True, consume_step_up=consume
        )

        def resolve(_request: Request) -> Actor:
            return self.actor

        app = FastAPI()
        app.include_router(make_rules_crud_router(lambda: self.mgr, resolve, on_cap_refused=capped))
        self.c = TestClient(app)

    def create(self, **over: Any) -> str:
        r = self.c.post("/rules", json={"ir": _ir(**over)})
        assert r.status_code == 201, r.text
        return str(r.json()["id"])

    def write(self, route: str, rid: str, text: Any) -> Any:
        """One of the four writes of `rid` carrying `text` as its `note` or `reason`. The body is
        sent as ASCII JSON, so a lone surrogate travels as its escape, as a client would send it."""
        sent = {"content-type": "application/json"}
        if route == "create":
            method, url, body = "POST", "/rules", {"ir": _ir(name="second"), "note": text}
        elif route == "update":
            method, url, body = "PUT", f"/rules/{rid}", {"ir": _ir("2"), "note": text}
            sent["If-Match"] = "1"
        elif route == "activate":
            version = self.c.get(f"/rules/{rid}/versions").json()["items"][0]["id"]
            body = {"version_id": version, "note": text}
            method, url = "PUT", f"/rules/{rid}/active-version"
        else:
            method, url, body = "PUT", f"/rules/{rid}/mode", {"mode": "simulate", "reason": text}
            sent["Idempotency-Key"] = "k"
        return self.c.request(method, url, content=json.dumps(body).encode(), headers=sent)

    def stored(self, rid: str) -> tuple[list[Any], list[Any], str]:
        """The rule's version notes, every rule's names and its mode."""
        notes = [v["notes"] for v in self.c.get(f"/rules/{rid}/versions").json()["items"]]
        names = [r["name"] for r in self.c.get("/rules").json()["items"]]
        return notes, names, self.c.get(f"/rules/{rid}").json()["mode"]

    def _row(self, rid: str) -> RuleRow:
        """The stored row of `rid`. `RuleStore`, the manager's port, names no `_rows`: this is the
        one reach into the in-memory store's map."""
        rows: dict[str, RuleRow] = self.mgr._s._rows  # type: ignore[attr-defined]  # see docstring
        return rows[rid]


WRITES = pytest.mark.parametrize("route", ["create", "update", "activate"])


@WRITES
def test_a_281_character_note_is_422_naming_the_field_and_stores_nothing(route: str) -> None:
    e = _Env()
    rid = e.create()
    before, audits = e.stored(rid), list(e.audits)
    r = e.write(route, rid, LONG)
    assert r.status_code == 422 and r.json() == _refusal("note")
    assert e.stored(rid) == before  # no stored copy, no shortened copy
    assert e.audits == audits and e.capped == ["note"]


def test_a_281_character_reason_is_422_naming_the_field_and_changes_nothing() -> None:
    e = _Env()
    rid = e.create()
    before, audits = e.stored(rid), list(e.audits)
    r = e.write("mode", rid, LONG)
    assert r.status_code == 422 and r.json() == _refusal("reason")
    assert e.stored(rid) == before and e.audits == audits and e.capped == ["reason"]


@pytest.mark.parametrize(("route", "field"), [("activate", "note"), ("mode", "reason")])
def test_the_activation_and_the_mode_change_count_their_refusal_in_the_cap_counter(
    route: str, field: str
) -> None:
    """`setActiveRuleVersion` and `setRuleMode` answer a refusal at a counted bound through the
    counting path, as the saves do: the `422` ticks `rule_authoring_cap_refused_total{cap}` (the
    app's own telemetry on a catalogue-registered facade)."""
    metrics = Metrics("demo")
    register_r0(metrics)
    telemetry = _RuleCompileTelemetry(metrics)
    e = _Env(counter=telemetry.on_cap_refused)
    rid = e.create()
    r = e.write(route, rid, LONG)
    assert r.status_code == 422 and r.json() == _refusal(field)
    counted = _series(generate_latest(metrics.registry).decode(), "cap_refused", "cap")
    assert counted == dict.fromkeys(REFUSED_CAPS, "0.0") | {field: "1.0"}


def test_a_live_arms_over_long_reason_spends_no_grant_and_raises_no_challenge() -> None:
    """22 `setRuleMode`: the bound is decided before the scope check and before the live-enablement
    step-up is consumed, so the refused arm leaves the actor's one grant for the next request."""
    e = _Env()
    rid = e.create(scope=LIVE)
    assert e.write("mode", rid, "ok").status_code == 200  # simulate
    h = e.c.get(f"/rules/{rid}/versions").json()["items"][0]["ir_hash"]
    row = e._row(rid)
    row.simulated_hashes.add(h)
    row.simulation_fires = 5
    audits = list(e.audits)
    arm = {"mode": "armed", "reason": LONG}
    r = e.c.put(f"/rules/{rid}/mode", json=arm, headers={"Idempotency-Key": "arm"})
    assert r.status_code == 422 and r.json() == _refusal("reason")
    assert e.grants == 1 and e.audits == audits
    armed = e.c.put(f"/rules/{rid}/mode", json={"mode": "armed"}, headers={"Idempotency-Key": "a"})
    assert armed.status_code == 200 and e.grants == 0  # the grant was there to spend


@WRITES
def test_a_280_character_note_is_stored_verbatim(route: str) -> None:
    e = _Env()
    rid = e.create()
    r = e.write(route, rid, FULL)
    assert r.status_code in (200, 201), r.text
    if route == "activate":
        (record,) = [p for a, p in e.audits if a == "rule.updated" and p.get("activated")]
        assert record["note"] == FULL
    else:
        stored = e._row(r.json()["id"] if route == "create" else rid)
        assert FULL in [v.notes for v in stored.versions]
    assert e.capped == []


def test_a_280_character_reason_is_recorded_verbatim() -> None:
    e = _Env()
    rid = e.create(scope=LIVE)
    assert e.write("mode", rid, "ok").status_code == 200
    h = e.c.get(f"/rules/{rid}/versions").json()["items"][0]["ir_hash"]
    e._row(rid).simulated_hashes.add(h)
    e._row(rid).simulation_fires = 5
    arm = {"mode": "armed", "reason": FULL}
    r = e.c.put(f"/rules/{rid}/mode", json=arm, headers={"Idempotency-Key": "arm"})
    assert r.status_code == 200, r.text
    (armed,) = [p for a, p in e.audits if a == "rule.armed"]
    assert armed["override_reason"] == FULL and e.capped == []


@pytest.mark.parametrize("route", ["create", "update", "activate", "mode"])
def test_the_bound_counts_code_points_not_bytes_or_utf16_units(route: str) -> None:
    e = _Env()
    rid = e.create()
    held = e.write(route, rid, ASTRAL)
    assert held.status_code in (200, 201), held.text
    refused = e.write(route, rid, ASTRAL + "\U0001f600")  # the bound is decided first
    assert refused.status_code == 422 and refused.json()["errors"][0]["rule"] == "max_length"


async def test_the_manager_refuses_an_over_long_note_whatever_the_caller() -> None:
    """The backstop: an import, a cascade or any later route reaches the same bound."""
    m, audits, _ = _mgr()
    rid = (await m.create(_ir(), OWNER))["id"]
    version = (await m.versions(rid))[0]["id"]
    audits.clear()
    calls: dict[str, list[Callable[[], Awaitable[Any]]]] = {
        "note": [
            lambda: m.create(_ir(name="b"), OWNER, LONG),
            lambda: m.update(rid, _ir("2"), 1, OWNER, LONG),
            lambda: m.set_active_version(rid, version, LONG, OWNER),
        ],
        "reason": [lambda: m.set_mode(rid, "simulate", OWNER, "k", override_reason=LONG)],
    }
    for field, writes in calls.items():
        for write in writes:
            with pytest.raises(RuleCapRefused) as refused:
                await write()
            answer = refused.value
            assert (answer.cap, answer.status, answer.code) == (field, 422, "rule_ir_invalid")
            assert answer.extra["errors"] == [_refusal(field)["errors"][0]]
    assert audits == [] and [v["version"] for v in await m.versions(rid)] == [1]
    assert (await m.get(rid, OWNER))["mode"] == "disabled"


@settings(max_examples=60, deadline=None)
@given(
    text=st.text(
        alphabet=st.characters(min_codepoint=0x20, codec="utf-8"),  # no NUL, no lone surrogate
        max_size=MAX_NOTE_CHARS + 40,
    )
)
def test_any_text_up_to_280_round_trips_and_any_longer_is_refused(text: str) -> None:
    e = _Env()
    r = e.c.post("/rules", json={"ir": _ir(), "note": text})
    if len(text) > MAX_NOTE_CHARS:
        assert r.status_code == 422 and r.json() == _refusal("note")
        assert e.c.get("/rules").json()["items"] == []
    else:
        assert r.status_code == 201, r.text
        assert e._row(r.json()["id"]).versions[0].notes == text


@pytest.mark.parametrize("bad", ["a\x00b", "\ud800", 7])
def test_text_that_cannot_be_stored_stays_the_400_whatever_its_length(bad: Any) -> None:
    """The unstorable-text check comes first: its `400 validation_failed` is unchanged, an
    over-long value of that kind included."""
    e = _Env()
    rid = e.create()
    value = bad * (MAX_NOTE_CHARS + 1) if isinstance(bad, str) else bad
    for route in ("create", "update", "activate", "mode"):
        r = e.write(route, rid, value)
        assert (r.status_code, r.json()["code"]) == (400, "validation_failed"), route
    assert e.capped == []


@pytest.mark.parametrize("route", ["create", "update", "activate", "mode"])
def test_a_viewer_gets_403_not_422_with_an_over_long_note(route: str) -> None:
    e = _Env()
    rid = e.create()
    e.actor = Actor("u1", "s1", frozenset({"rules:read"}), is_owner=True)
    r = e.write(route, rid, LONG)
    assert (r.status_code, r.json()["code"]) == (403, "forbidden")
    assert e.capped == []


def test_an_over_long_note_on_another_users_rule_is_the_audited_404_on_update() -> None:
    """On `updateRule` the stored rule is looked at first: another user's rule is the audited
    `404`, whatever the note; the bound never says whether the rule exists."""
    e = _Env()
    rid = e.create()
    e.actor = Actor("u2", "s2", frozenset(BASE), granted_accounts=frozenset({str(A)}))
    r = e.write("update", rid, LONG)
    assert (r.status_code, r.json()["code"]) == (404, "not_found")
    assert e.audits[-1][0] == "rule.scope_refused" and e.capped == []


def test_an_over_long_note_on_another_users_rule_is_the_unrecorded_422_on_activation() -> None:
    """On the activation the bound comes before the rule is looked up: the same `422` for a rule
    that is not the caller's, one that is and one that does not exist, and no record."""
    e = _Env()
    rid = e.create()
    version = e.c.get(f"/rules/{rid}/versions").json()["items"][0]["id"]
    e.actor = Actor("u2", "s2", frozenset(BASE), granted_accounts=frozenset({str(A)}))
    audits = list(e.audits)
    for target in (rid, "00000000-0000-4000-8000-000000000999"):
        body = {"version_id": version, "note": LONG}
        r = e.c.put(f"/rules/{target}/active-version", json=body)
        assert r.status_code == 422 and r.json() == _refusal("note")
    assert e.audits == audits


@pytest.mark.parametrize("route", ["create", "update"])
def test_an_over_long_note_is_decided_before_the_scope_check(route: str) -> None:
    """An ungranted account in the body's scope is never looked up: no scope record is written."""
    c, scope_audits, _src, _ = _setup()
    rid = c.post("/rules", json={"ir": _scoped(A)}).json()["id"]
    scope_audits.clear()
    if route == "create":
        r = c.post("/rules", json={"ir": {**_scoped(C), "name": "other"}, "note": LONG})
    else:
        body = {"ir": _scoped(C), "note": LONG}
        r = c.put(f"/rules/{rid}", json=body, headers={"If-Match": "1"})
    assert (r.status_code, r.json()["code"]) == (422, "rule_ir_invalid")
    assert scope_audits == []


def test_an_over_long_reason_is_decided_before_the_arms_visibility_and_scope_checks() -> None:
    """An arm of another user's rule with an over-long `reason` is the `422`, before the rule is
    looked up: no refusal is recorded and the actor's grant is untouched."""
    e = _Env()
    rid = e.create()
    e.actor = Actor("u2", "s2", frozenset({*BASE, ARM}), granted_accounts=frozenset({str(A)}))
    audits = list(e.audits)
    arm = {"mode": "armed", "reason": LONG}
    r = e.c.put(f"/rules/{rid}/mode", json=arm, headers={"Idempotency-Key": "x"})
    assert r.status_code == 422 and r.json() == _refusal("reason")
    assert e.audits == audits and e.grants == 1
