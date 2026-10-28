"""`/scanner/presets*` audit (E08-T09 PR 2a, #4708; C-2.9, 24 section 15.5): every write is
recorded ahead of its row, a record carries `version` and `content_sha256` but never the name or
the filter, the default it clears is recorded `.updated`, a refused record stores nothing, and a
write refused after its record gets a second record with outcome `failure`."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from typing import Any

import pytest
from _scanner_env import SID, USER_A, Env, body
from structlog.testing import capture_logs

from candleviewer.api.scanner_presets_service import content_sha256
from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.redact import redact
from candleviewer.audit.writer import AuditUnavailable, AuditWriterStopped
from candleviewer.storage.errors import StorageConstraintViolated
from candleviewer.storage.repositories.scanner_presets import (
    ConflictRule,
    ScannerPresetConflictError,
    ScannerPresetFields,
)

_FILTER = body()["filter"]


def _ordered(env: Env) -> list[str]:
    """One log of audit actions and store writes, in the order they happened."""
    log: list[str] = []
    emit, call = env.audit.emit, env.repo._call

    async def audited(action: str, **kw: Any) -> None:
        log.append(f"audit:{action}")
        await emit(action, **kw)

    def stored(method: str, /, **kw: Any) -> None:
        if method in ("create", "update", "delete"):
            log.append(f"store:{method}")
        call(method, **kw)

    env.audit.emit = audited  # type: ignore[method-assign]  # the test's spy
    env.repo._call = stored  # type: ignore[method-assign]  # the test's spy
    return log


@pytest.mark.parametrize("action", ["created", "updated", "deleted"])
def test_the_three_actions_are_registered(action: str) -> None:
    assert f"scanner_preset.{action}" in AUDIT_ACTIONS


def test_every_write_is_audited_ahead_of_its_row() -> None:
    """Gherkin: the create is audited ahead as scanner_preset.created."""
    env = Env()
    log = _ordered(env)
    made = env.create()
    env.c.put(f"/scanner/presets/{made['id']}", json=body(name="Renamed"))
    env.c.delete(f"/scanner/presets/{made['id']}")
    assert log == [
        "audit:scanner_preset.created", "store:create",
        "audit:scanner_preset.updated", "store:update",
        "audit:scanner_preset.deleted", "store:delete",
    ]  # fmt: skip


def test_records_carry_version_and_the_digest_never_the_name_or_the_filter() -> None:
    env = Env()
    made = env.create()
    env.c.put(f"/scanner/presets/{made['id']}", json=body(name="Renamed", sort="funding_rate"))
    env.c.delete(f"/scanner/presets/{made['id']}")
    created, updated, deleted = env.audit.calls
    first = ScannerPresetFields("Momentum", _FILTER, "turnover_24h", False)
    second = ScannerPresetFields("Renamed", _FILTER, "funding_rate", False)
    assert created["after_state"] == {"version": 1, "content_sha256": content_sha256(first)}
    assert "before_state" not in created
    assert updated["before_state"] == created["after_state"]
    assert updated["after_state"] == {"version": 2, "content_sha256": content_sha256(second)}
    assert deleted["before_state"] == updated["after_state"] and "after_state" not in deleted
    for record in (created, updated, deleted):
        assert (record["object_kind"], record["object_id"]) == ("scanner_preset", made["id"])
        assert (record["actor_user_id"], record["session_id"], record["actor_ip"]) == (
            USER_A, SID, "10.0.0.9",
        )  # fmt: skip
        assert record.get("outcome", "success") == "success"
        text = json.dumps(record, default=str)
        for leak in ("Momentum", "Renamed", 'turnover_24h": {', "50000000", "trend_up"):
            assert leak not in text


def test_the_digest_is_sha256_of_the_canonical_name_filter_sort_and_default() -> None:
    fields = ScannerPresetFields("Fast", {"spread_bps": {"max": "2"}}, "spread_bps", True)
    canonical = json.dumps(
        {"filter": fields.filter, "is_default": True, "name": "Fast", "sort": "spread_bps"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )  # fmt: skip
    assert content_sha256(fields) == hashlib.sha256(canonical.encode()).hexdigest()
    state = {"version": 1, "content_sha256": content_sha256(fields)}
    assert redact(state) == state  # a `*hash*` key would be dropped by the redaction


def test_setting_a_default_records_the_cleared_one_as_updated_with_its_version_raised() -> None:
    env = Env()
    first = env.create(name="First", is_default=True)
    log = _ordered(env)
    second = env.create(name="Second", is_default=True)
    assert log == ["audit:scanner_preset.created", "audit:scanner_preset.updated", "store:create"]
    cleared = env.audit.calls[-1]
    was = ScannerPresetFields("First", _FILTER, "turnover_24h", True)
    now = ScannerPresetFields("First", _FILTER, "turnover_24h", False)
    assert (cleared["object_id"], cleared["before_state"], cleared["after_state"]) == (
        first["id"],
        {"version": 1, "content_sha256": content_sha256(was)},
        {"version": 2, "content_sha256": content_sha256(now)},
    )
    assert env.audit.calls[-2]["object_id"] == second["id"]


@pytest.mark.parametrize("error", [AuditUnavailable("down"), AuditWriterStopped()])
@pytest.mark.parametrize("op", ["create", "update", "delete"])
def test_a_refused_audit_record_is_503_audit_unavailable_and_nothing_is_stored(
    op: str, error: Exception
) -> None:
    env = Env()
    made = env.create()
    before, calls = dict(env.repo.rows), len(env.repo.calls)
    env.audit.fail = error
    with capture_logs() as logs:
        if op == "create":
            r = env.c.post("/scanner/presets", json=body(name="Other"))
        elif op == "update":
            r = env.c.put(f"/scanner/presets/{made['id']}", json=body(name="Other"))
        else:
            r = env.c.delete(f"/scanner/presets/{made['id']}")
    assert (r.status_code, r.json()["code"]) == (503, "audit_unavailable")
    assert r.headers["retry-after"] == "5"
    assert env.repo.rows == before
    assert not any(m in ("create", "update", "delete") for m, _ in env.repo.calls[calls:])
    assert any(e["event"] == "scanner_presets_audit_unavailable" for e in logs)


@pytest.mark.parametrize("rule", ["name_taken", "conflict"])
def test_a_write_refused_after_its_record_gets_a_failure_record_with_the_same_digest(
    rule: ConflictRule,
) -> None:
    env = Env()
    first = env.create(name="First", is_default=True)
    env.repo.race = ScannerPresetConflictError(rule)  # the pre-check passed; the store refuses
    r = env.c.post("/scanner/presets", json=body(name="Second", is_default=True))
    assert (r.status_code, r.json()["errors"][0]["rule"]) == (409, rule)
    tail = env.audit.calls[-4:]
    assert [(c["action"], c.get("outcome", "success")) for c in tail] == [
        ("scanner_preset.created", "success"), ("scanner_preset.updated", "success"),
        ("scanner_preset.created", "failure"), ("scanner_preset.updated", "failure"),
    ]  # fmt: skip
    assert tail[2]["after_state"] == tail[0]["after_state"]
    assert tail[3]["object_id"] == first["id"] and tail[3]["after_state"] == tail[1]["after_state"]
    assert [i["name"] for i in env.listed() if i["is_default"]] == ["First"]


def test_a_default_changed_after_its_record_is_conflict_and_both_records_get_a_failure() -> None:
    """S-2 (round 1): the cleared default's record names the version the store must clear."""
    env = Env()
    first = env.create(name="First", is_default=True)
    original = env.repo.get_default

    async def then_changed(owner: str) -> Any:
        got = await original(owner)
        row = env.repo.rows[first["id"]]  # the owner's concurrent PUT lands after this read
        env.repo.rows[first["id"]] = dataclasses.replace(row, version=row.version + 1)
        return got

    env.repo.get_default = then_changed  # type: ignore[method-assign]  # the test's race
    r = env.c.post("/scanner/presets", json=body(name="Second", is_default=True))
    assert (r.status_code, r.json()["errors"][0]["rule"]) == (409, "conflict")
    assert [(c["action"], c.get("outcome", "success")) for c in env.audit.calls[-4:]] == [
        ("scanner_preset.created", "success"), ("scanner_preset.updated", "success"),
        ("scanner_preset.created", "failure"), ("scanner_preset.updated", "failure"),
    ]  # fmt: skip
    assert [i["name"] for i in env.listed() if i["is_default"]] == ["First"]


def test_a_constraint_refusal_after_the_record_still_gets_its_failure_record() -> None:
    """S-1 (round 1): a refusal with no domain error (a 500) still closes the record."""
    env = Env()
    env.repo.race = StorageConstraintViolated("23503", "fk_sp_user")
    with pytest.raises(StorageConstraintViolated):
        env.c.post("/scanner/presets", json=body(name="Second"))
    assert [(c["action"], c.get("outcome", "success")) for c in env.audit.calls[-2:]] == [
        ("scanner_preset.created", "success"), ("scanner_preset.created", "failure"),
    ]  # fmt: skip


def test_a_delete_lost_to_a_concurrent_one_is_404_with_a_failure_record() -> None:
    env = Env()
    made = env.create()
    original = env.repo.delete

    async def gone(owner: str, preset_id: str) -> bool:
        env.repo.rows.pop(preset_id, None)  # another request deleted it first
        return await original(owner, preset_id)

    env.repo.delete = gone  # type: ignore[method-assign]  # the test's race
    r = env.c.delete(f"/scanner/presets/{made['id']}")
    assert r.status_code == 404
    assert [(c["action"], c.get("outcome", "success")) for c in env.audit.calls[-2:]] == [
        ("scanner_preset.deleted", "success"), ("scanner_preset.deleted", "failure"),
    ]  # fmt: skip


def test_a_failure_record_that_cannot_be_written_still_answers_the_refusal() -> None:
    env = Env()
    env.create(name="First")
    env.repo.race = ScannerPresetConflictError("name_taken")

    async def refuse_failures(action: str, **kw: Any) -> None:
        if kw.get("outcome") == "failure":
            raise AuditUnavailable("down")
        env.audit.calls.append({"action": action, **kw})

    env.audit.emit = refuse_failures  # type: ignore[method-assign]  # the test's writer
    with capture_logs() as logs:
        r = env.c.post("/scanner/presets", json=body(name="Second"))
    assert (r.status_code, r.json()["errors"][0]["rule"]) == (409, "name_taken")
    assert any(e["event"] == "scanner_preset_failure_unrecorded" for e in logs)


def test_reads_and_refusals_before_the_record_write_nothing() -> None:
    env = Env()
    env.create(name="Taken")
    calls = len(env.audit.calls)
    env.c.get("/scanner/presets")
    env.c.get("/scanner/criteria")
    env.c.post("/scanner/presets", json=body(name="taken"))  # 409 from the pre-check
    env.c.post("/scanner/presets", json=body(filter={"spread_bps": {}}))  # 422
    assert env.audit.calls[calls:] == []
