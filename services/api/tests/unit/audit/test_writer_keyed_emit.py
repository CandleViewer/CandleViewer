"""#3085 Q3: `AuditWriter.emit_keyed()` keys a record by its action's namespace and a name. A
repeat of a keyed record, after a restart too, is one row (`ON CONFLICT (record_id) DO NOTHING`),
the first written; an action has its own namespace, fixed for good, and one not keyed is refused."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from audit_fakes import FakeAuditRepository, FakeClock
from test_writer_build import _dead_flusher, _writer

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.writer import (
    KEYED_ACTIONS,
    AuditUnavailable,
    AuditWriterStopped,
    keyed_record_id,
)

_ACTION, _NAME = "admin.view_as_ended", "00000000-0000-4000-8000-000000000001"


def test_writer_keyed_actions_keep_their_namespaces_for_good() -> None:
    """A new namespace would give a context written on both sides of the change two rows (V45);
    the restart test below pins the id one derives."""
    assert KEYED_ACTIONS[_ACTION] == uuid.UUID("f30c6b64-1ea6-416d-aebb-8aaa0760f421")
    # E29-T04 (#913): a stop request's records, named by their `recorded_stops` row's id.
    assert KEYED_ACTIONS["sl.attached"] == uuid.UUID("d6abc860-0257-4214-9142-d65723f23fd7")
    assert KEYED_ACTIONS["sl.modified"] == uuid.UUID("132f3241-512e-445d-86af-731eab14fe5e")
    assert KEYED_ACTIONS["tp.modified"] == uuid.UUID("0f574dd0-7558-4261-8417-7c38870c061d")
    # E27-S04 (#898 R7): a key revoke's completion record, named by the key's id.
    assert KEYED_ACTIONS["api_key.revoked"] == uuid.UUID("05b2ed69-7564-401d-8d03-51392a7758ca")
    # E35-T09 (#5000): a rule action's records, named by the action's `dedupe_key` (24 §11.9).
    assert KEYED_ACTIONS["rules.fired"] == uuid.UUID("51f5d119-a574-4365-b206-e54224c41884")
    assert KEYED_ACTIONS["rules.blocked"] == uuid.UUID("74e6d147-d012-4f44-a891-c6fc0477a2bf")
    assert set(KEYED_ACTIONS) <= AUDIT_ACTIONS
    assert len(set(KEYED_ACTIONS.values())) == len(KEYED_ACTIONS)  # never two actions on one id


async def test_writer_keyed_emit_repeated_after_a_restart_is_one_row(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    repo.down = True
    first = _writer(repo, tmp_path, clock)
    await first.start()
    await first.emit_keyed(_ACTION, _NAME, actor_label="ana", reason="ended")
    await first.stop(0.01)  # simulated kill: the record is in the WAL, not in Postgres
    repo.down = False
    second = _writer(repo, tmp_path, clock)
    await second.start()  # replays the first frame
    late = {"recorded_late": True}
    await second.emit_keyed(_ACTION, _NAME, actor_label="ana", after_state=late)
    await second.emit("auth.logout", actor_label="ana")
    await second.flush(5)
    await second.stop(1)

    assert [r["action"] for r in repo.rows] == [_ACTION, "auth.logout"]
    assert repo.rows[0]["record_id"] == "65978c65-517c-56e7-b92b-7978fdce545c"  # uuid5, for good
    assert repo.rows[0]["after_state"] is None  # the first written stays
    assert uuid.UUID(repo.rows[1]["record_id"]).version == 4  # an unkeyed emit mints its own
    assert (await AuditQueryService(repo).verify()).verified


async def test_writer_keyed_emit_refuses_an_unkeyed_action_and_raises_every_refusal(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    """An action it does not key is a caller error, appended and counted nowhere. A writer that
    refuses raises it, counted as `emit()`'s, so no caller marks a record written that was not
    (`ViewAsService.write_end_record` leaves its end pending)."""
    stopped = _writer(repo, tmp_path, clock)
    dead = await _dead_flusher(repo, tmp_path / "dead", clock)
    with pytest.raises(ValueError, match="not a keyed audit action"):
        await dead.emit_keyed("admin.view_as_started", _NAME, actor_label="ana")
    for writer, refusal in ((stopped, AuditWriterStopped), (dead, AuditUnavailable)):
        with pytest.raises(refusal):
            await writer.emit_keyed(_ACTION, _NAME, actor_label="ana")
        assert writer.refused_by_domain["admin"] == 1
    await dead.stop(1)
    assert stopped.buffer_depth == 0 and dead.buffer_depth == 1 and repo.rows == []


@pytest.mark.parametrize("name", ["", "   "])
async def test_writer_keyed_emit_refuses_a_blank_name_without_echoing_it(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock, name: str
) -> None:
    """`uuid5(namespace, "")` would fold every blank-keyed record of an action into one row; the
    refusal names no input (S4-SEC-10) and nothing is appended."""
    writer = _writer(repo, tmp_path, clock)
    with pytest.raises(ValueError, match=r"^a keyed audit record needs a name$"):
        await writer.emit_keyed(_ACTION, name, actor_label="ana")
    assert writer.buffer_depth == 0


async def test_keyed_record_id_is_the_id_emit_keyed_stores_its_record_under(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    """CR-2B1-08: the one derivation of a keyed record's id, which a caller names ahead of the
    record (a recorded stop's `audit_record_id`, 21 Sec.3.3.11) and `emit_keyed` stores, so the
    two never drift apart; it refuses as `emit_keyed` does, naming no input."""
    writer = _writer(repo, tmp_path, clock)
    await writer.start()
    await writer.emit_keyed(_ACTION, _NAME, actor_label="ana", reason="ended")
    await writer.flush(5)
    await writer.stop(1)
    assert [row["record_id"] for row in repo.rows] == [str(keyed_record_id(_ACTION, _NAME))]
    stop = "4a1b2c3d-5e6f-4a7b-8c9d-0e1f2a3b4c5d"  # a recorded stop's row id
    assert keyed_record_id("sl.attached", stop) == uuid.uuid5(KEYED_ACTIONS["sl.attached"], stop)
    with pytest.raises(ValueError, match="not a keyed audit action"):
        keyed_record_id("sl.loosened", stop)
    with pytest.raises(ValueError, match=r"^a keyed audit record needs a name$"):
        keyed_record_id("sl.attached", " ")
