"""E28-T05 S2d (#909): `updateTradeGroupDefinition` and `deleteTradeGroupDefinition` over the
create's world, whose store also replaces and soft-deletes as Postgres does: the live row locked
first, `None` for one that is not live (SEC-2-03), the read's `updated_at` compared under the lock.
Core3 holds A, B and C (C paused), Pair A and C, Live L; and the writes' replays (SR-E28-17)."""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from candleviewer.accounts.trade_group_definitions import definition_etag, stored_definition
from candleviewer.audit.writer import AuditUnavailable
from candleviewer.storage.repositories import trade_group_definitions as port
from tests.unit.api import test_trade_group_definition_create as create
from tests.unit.api import test_trade_group_definition_reads as reads

A, B, C, D, L, PATH = create.A, create.B, create.C, create.D, create.L, create.PATH
CORE3, PAIR, LIVE, MISSING = reads.CORE3, reads.PAIR, reads.LIVE, reads.MISSING
REPLACE = "Replace trade-group definition {} with 2 members (demo)"
DELETE = "Delete trade-group definition {}"
WAS = create.state_of((A, True), (B, True), (C, False))  # Core3 as a record holds it


class World(create.World):
    """`replace` and `soft_delete` as the Postgres store: `lost` holds an id deleted between the
    route's read and the store's row lock; `commits` counts the writes, so a record shows whether
    it was written ahead; `expected` holds each `expected_updated_at` the store was given."""

    def __init__(self) -> None:
        super().__init__()
        self.records[CORE3] = reads.record(CORE3, "Core3", A, B, C, paused=C)
        self.records[LIVE] = reads.record(LIVE, "Live", L, env="live")
        self.lost, self.commits, self.expected = set[UUID](), 0, list[Any]()

    async def emit(self, action: str, **kwargs: Any) -> None:
        await super().emit(action, **kwargs)
        self.audited[-1]["committed"] = self.commits

    def _locked(self, key: UUID) -> port.DefinitionRecord | None:
        return None if key in self.deleted | self.lost else self.records.get(key)

    async def replace(
        self, scope: Any, key: UUID, new: port.NewDefinition, *, expected_updated_at: Any,
        write_ahead: port.DefinitionWriteAhead,
    ) -> port.DefinitionRecord | None:  # fmt: skip
        self.expected.append(expected_updated_at)
        if (before := self._locked(key)) is None:
            return None
        if expected_updated_at not in (None, before.definition.updated_at):
            raise port.DefinitionStaleError
        others = {r.definition.name.lower() for r in self._seen(scope) if r != before}
        if new.name.lower() in others:
            raise port.DefinitionConflictError("ux_tgd_name")
        moved = before.definition.updated_at + timedelta(seconds=1)  # the touch trigger
        row = dataclasses.replace(before.definition, name=new.name, updated_at=moved)
        held = sorted(new.members, key=lambda m: m.exchange_account_id)
        rows = tuple(port.MemberRow(m.exchange_account_id, m.enabled, new.env, True) for m in held)
        await write_ahead(before, after := port.DefinitionRecord(row, rows))
        self.records[key], self.commits = after, self.commits + 1
        return after

    async def soft_delete(
        self, scope: Any, key: UUID, *, write_ahead: port.DefinitionWriteAhead
    ) -> port.DefinitionRecord | None:
        if (before := self._locked(key)) is None:
            return None
        await write_ahead(before, None)
        self.deleted.add(key)
        self.commits += 1
        return before

    def put(
        self, sent: dict[str, Any] | None = None, key: UUID = CORE3, *, if_match: str | None = None,
        idempotency_key: str | None = None,
    ) -> Any:  # fmt: skip
        body = create.payload(A, C) if sent is None else sent
        named = {"if-match": if_match, "idempotency-key": idempotency_key}
        headers = {name: value for name, value in named.items() if value is not None}
        return self.client.put(f"{PATH}/{key}", json=body, headers=headers)

    def delete(self, key: UUID = CORE3, *, idempotency_key: str | None = None) -> Any:
        sent = {} if idempotency_key is None else {"idempotency-key": idempotency_key}
        return self.client.delete(f"{PATH}/{key}", headers=sent)

    def tag(self) -> str:
        return definition_etag(stored_definition(self.records[CORE3]))


def _rows(world: World) -> list[tuple[Any, ...]]:
    keys = ("action", "committed", "before_state", "after_state")
    return [tuple(r[k] for k in keys) for r in world.audited]


@pytest.fixture
def world() -> World:
    return World()


def test_a_replace_records_membership_before_and_after(world: World) -> None:
    """At the read's `ETag`: 200 with what a read then answers and a new tag; `.updated` written
    ahead with Core3 before and after, B removed and C toggled; the store compares the read row."""
    tag, was = world.tag(), world.records[CORE3].definition.updated_at
    got, read = world.put(if_match=tag), world.client.get(f"{PATH}/{CORE3}")
    assert (got.status_code, got.json(), got.headers["etag"]) == (
        200, read.json(), read.headers["etag"]
    )  # fmt: skip
    assert got.headers["etag"] != tag and world.expected == [was]
    change = {"added": [], "removed": [str(B)], "toggled": [str(C)]}
    after = create.state_of((A, True), (C, True)) | {"membership_change": change}
    assert _rows(world) == [("trade_group_definition.updated", 0, WAS, after)]
    assert world.texts == [REPLACE.format(CORE3)] and world.audited[0]["object_id"] == str(CORE3)


def test_a_replace_over_a_stale_etag_is_412_and_changes_nothing(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Anything but the `ETag` of the row read is 412 and never challenged; a read made before a
    write that lands ahead of the store's row lock is 412 there (`expected_updated_at`)."""
    old = world.tag()
    assert world.put(if_match=old).status_code == 200
    new, read = world.tag(), world.records[CORE3]
    refused = [world.put(if_match=sent) for sent in (old, "*", f"{new}, {new}", new[2:], "")]
    twice = [("if-match", new), ("if-match", new)]  # two headers, each the current tag
    refused.append(world.client.put(f"{PATH}/{CORE3}", json=create.payload(A, C), headers=twice))
    assert world.put(create.payload(A, B, C)).status_code == 200  # no If-Match: it lands

    async def before_that_write(*_: Any) -> port.DefinitionRecord:
        return read

    monkeypatch.setattr(world, "get", before_that_write)
    refused.append(world.put(if_match=new))
    assert {(r.status_code, r.json()["code"]) for r in refused} == {(412, "version_conflict")}
    assert (len(world.texts), world.commits) == (3, 2)
    assert world.expected[-1] == read.definition.updated_at
    assert [m.exchange_account_id for m in world.records[CORE3].members] == [A, B, C]


def test_without_if_match_the_last_write_wins(world: World) -> None:
    sent = [create.payload(A, C), create.payload(A, B, C, name="Core 3")]
    assert [world.put(body).status_code for body in sent] == [200, 200]
    held = world.client.get(f"{PATH}/{CORE3}").json()["definition"]
    assert (held["name"], len(held["members"]), world.expected) == ("Core 3", 3, [None, None])


def test_an_environment_change_is_400_write_once(world: World) -> None:
    """22: another `environment` than the stored one, whatever the members, is refused before any
    member is judged; nothing is changed or challenged."""
    answers = [world.put(create.payload(L, env="live"))]
    answers.append(world.put(create.payload(A, C, env="live")))
    entry = {"field": "environment", "rule": "write_once"}
    entry["message"] = "A definition's environment cannot change."
    assert {(r.status_code, r.json()["code"]) for r in answers} == {(400, "validation_failed")}
    assert [r.json()["errors"] for r in answers] == [[entry]] * 2
    assert (world.texts, world.audited, world.commits) == ([], [], 0)


def test_a_replace_of_a_deleted_definition_is_404_and_adds_no_member(world: World) -> None:
    """SEC-2-03, C-2.11: missing, deleted, of another environment, or deleted between the read and
    the store's row lock: the read's one 404, a delete's alike; nothing is written."""
    core3 = world.records[CORE3]
    world.deleted.add(CORE3)
    world.lost.add(PAIR)
    keys = (MISSING, CORE3, LIVE, PAIR)
    answers = [world.put(key=key) for key in keys] + [world.delete(key) for key in keys]
    missing = world.client.get(f"{PATH}/{MISSING}")
    assert {(r.status_code, r.text) for r in answers} == {(404, missing.text)}
    assert (world.records[CORE3], world.commits, world.audited) == (core3, 0, [])
    assert world.texts == [REPLACE.format(PAIR), DELETE.format(PAIR)]  # live when read


def test_a_delete_soft_deletes_and_records_what_it_ends(world: World) -> None:
    """204; Core3 is then neither read nor listed, and a second delete is a missing one's 404;
    `.deleted` written ahead with Core3 before and every member removed."""
    gone, again = world.delete(), world.delete()
    assert (gone.status_code, gone.content, again.status_code) == (204, b"", 404)
    listed = [item["id"] for item in world.client.get(PATH).json()["items"]]
    assert world.client.get(f"{PATH}/{CORE3}").status_code == 404 and str(CORE3) not in listed
    removed = {"added": [], "removed": [str(A), str(B), str(C)], "toggled": []}
    expected = ("trade_group_definition.deleted", 0, WAS, {"membership_change": removed})
    assert _rows(world) == [expected] and world.texts == [DELETE.format(CORE3)]


def test_a_deleted_name_is_free_again(world: World) -> None:
    """`ux_tgd_name` holds a live name alone: Pair takes Core3's once Core3 is deleted."""
    renamed = create.payload(A, C, name="cORE3")
    answers = [world.put(renamed, PAIR), world.delete(), world.put(renamed, PAIR)]
    assert [r.status_code for r in answers] == [409, 204, 200]
    assert answers[0].json()["code"] == "conflict"
    assert world.records[PAIR].definition.name == "cORE3"


def test_update_and_delete_need_the_step_up(world: World) -> None:
    """PF-S02: without a live `risk_caps` step-up nothing is written; the challenge names the
    definition by its id, never its name, and only a write past every check is challenged."""
    world.elevated = False
    stale, answers = world.put(if_match='W/"0000000000000000"'), [world.put(), world.delete()]
    codes = ["version_conflict", "step_up_required", "step_up_required"]
    assert [r.json()["code"] for r in [stale, *answers]] == codes
    assert world.texts == [REPLACE.format(CORE3), DELETE.format(CORE3)]
    assert (world.commits, world.audited, world.deleted) == (0, [], set())


@pytest.mark.parametrize("role", ["manager", "viewer"])
def test_a_manager_and_a_viewer_get_403_on_a_replace_and_a_delete(world: World, role: str) -> None:
    """SR-E28-31: audited, whatever the flag says, before any read; unaudited, 503."""
    world.principal, read = create.caller(role), world.reads
    answers = [world.put(), world.delete()]
    world.flag = False
    answers += [world.put(), world.delete()]
    assert {(r.status_code, r.json()["code"]) for r in answers} == {(403, "forbidden")}
    assert [r["action"] for r in world.audited] == ["rbac.denied"] * 4
    world.faults["audit"] = AuditUnavailable("down")
    assert {world.put().json()["code"], world.delete().json()["code"]} == {"audit_unavailable"}
    assert (world.reads, world.commits, world.texts) == (read, 0, [])


def test_a_replace_naming_an_unknown_member_is_refused_as_a_create_is(world: World) -> None:
    """SR-E29-13: a missing or deleted member is the create's one 403 `account_scope_denied`, never
    a 404 and never an environment mismatch; nothing is changed or challenged."""
    answers = [world.put(create.payload(A, MISSING)), world.put(create.payload(D, L))]
    answers.append(world.post(create.payload(A, MISSING, name="New")))
    assert {(r.status_code, r.text) for r in answers} == {(403, answers[0].text)}
    assert answers[0].json()["code"] == "account_scope_denied"
    assert (world.texts, world.commits) == ([], 0)


def test_a_replace_and_a_delete_replay_to_their_own_principal_alone(world: World) -> None:
    """SR-E28-17: the kept answer to the same request, before the flag (21 Sec.10.7), which refuses
    a fresh write, and behind the step-up; another body under the key is 409; another Owner's same
    request runs afresh."""
    put, gone = str(uuid4()), str(uuid4())
    first, deleted = world.put(idempotency_key=put), world.delete(PAIR, idempotency_key=gone)
    world.flag = False
    again, off = world.put(idempotency_key=put), world.delete()
    deleted_again = world.delete(PAIR, idempotency_key=gone)
    assert (again.status_code, again.content, again.headers["etag"]) == (
        200, first.content, first.headers["etag"]
    )  # fmt: skip
    assert (deleted.status_code, deleted_again.status_code, len(world.audited)) == (204, 204, 2)
    assert [r.headers["idempotency-replayed"] for r in (again, deleted_again)] == ["true"] * 2
    assert (off.json()["code"], "reason" in off.json()) == ("trading_disabled", False)
    other = world.put(create.payload(A, B, C), idempotency_key=put)
    world.elevated = False
    challenged = world.delete(PAIR, idempotency_key=gone)
    world.flag, world.elevated, world.principal = True, True, create.caller("owner", uuid4())
    theirs = world.put(idempotency_key=put)
    assert [other.json()["code"], challenged.json()["code"]] == [
        "idempotency_key_reuse", "step_up_required"
    ]  # fmt: skip
    assert (theirs.status_code, "idempotency-replayed" in theirs.headers) == (200, False)


def test_a_kept_answer_replays_to_its_own_path_alone(world: World) -> None:
    """SR-E28-17: the fingerprint holds the path, so a key sent for another definition is a reuse
    (409), never a kept answer for a write that was not made; nothing is challenged or written."""
    put, gone = str(uuid4()), str(uuid4())
    assert world.put(idempotency_key=put).status_code == 200
    assert world.delete(PAIR, idempotency_key=gone).status_code == 204
    other = [world.put(key=PAIR, idempotency_key=put), world.delete(CORE3, idempotency_key=gone)]
    assert {(r.status_code, r.json()["code"]) for r in other} == {(409, "idempotency_key_reuse")}
    assert world.texts == [REPLACE.format(CORE3), DELETE.format(PAIR)]  # no more was asked
    assert (world.commits, world.deleted) == (2, {PAIR})
    assert world.client.get(f"{PATH}/{CORE3}").status_code == 200  # Core3 was never deleted


def test_the_flag_refuses_a_replace_and_a_delete_before_the_definition_is_read(
    world: World,
) -> None:
    """21 Sec.10.7, as the create's: off, a replace or a delete of an id nobody holds is `403
    trading_disabled` with no `reason`, not the read's 404, and the store is not read."""
    world.flag, read = False, world.reads
    answers = [world.put(key=MISSING), world.delete(MISSING)]
    assert {(r.status_code, r.json()["code"]) for r in answers} == {(403, "trading_disabled")}
    assert ["reason" in r.json() for r in answers] == [False, False]
    assert (world.reads, world.texts, world.commits) == (read, [], 0)


def test_a_replayed_write_restates_itself_in_the_step_up_text(world: World) -> None:
    """PF-S02, SR-E28-17: a kept answer is served behind the step-up its write took, and what the
    Owner confirms is that write: a replace by its id and its body's members, a delete by its id,
    a create by its environment and members, never a name."""
    put, gone, made = str(uuid4()), str(uuid4()), {"idempotency-key": str(uuid4())}
    fresh = create.payload(A, C, name="Fresh")  # Core3 holds the name Core3

    def writes() -> list[Any]:
        return [
            world.put(idempotency_key=put), world.delete(PAIR, idempotency_key=gone),
            world.client.post(PATH, json=fresh, headers=made),
        ]  # fmt: skip

    firsts = writes()
    asked = len(world.texts)
    replays = writes()
    assert [r.status_code for r in firsts] == [r.status_code for r in replays] == [200, 204, 201]
    assert [r.headers["idempotency-replayed"] for r in replays] == ["true"] * 3
    created = "Create a demo trade-group definition of 2 members"
    assert world.texts[asked:] == [REPLACE.format(CORE3), DELETE.format(PAIR), created]
    assert len(world.audited) == 3  # a replay writes nothing


@pytest.mark.parametrize("fault", [AuditUnavailable("down"), TimeoutError()])
def test_an_unwritable_record_changes_nothing(world: World, fault: Exception) -> None:
    """C-2.9: unwritten, `.updated` and `.deleted` leave Core3 as it was."""
    core3, world.faults["audit"] = world.records[CORE3], fault
    answers = [world.put(), world.delete()]
    assert {(r.status_code, r.json()["code"]) for r in answers} == {(503, "audit_unavailable")}
    assert (world.records[CORE3], world.deleted, world.commits) == (core3, set(), 0)
