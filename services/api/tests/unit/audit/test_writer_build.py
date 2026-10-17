"""ADR-0037 S2a1 (#3009): `AuditWriter.build()` is `emit()`'s validating half. `build()` then
`ingest()` stores what `emit()` stores, in the WAL, the rows and the chain; `build()` reads the
clock once and writes nothing, even while the writer refuses; and `emit()` still refuses
before it builds, so its errors come in the same order as before."""

from __future__ import annotations

import asyncio
import itertools
import json
import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from audit_fakes import FakeAuditRepository, FakeClock

from candleviewer.audit.actions import UnknownAuditAction
from candleviewer.audit.models import AuditOutcome, ExchangeEnv, Severity
from candleviewer.audit.query import AuditQueryService
from candleviewer.audit.redact import PII_HASH_PREFIX, REDACTION_MARKER
from candleviewer.audit.writer import AuditUnavailable, AuditWriter, AuditWriterStopped

#: `emit()` calls between them using every argument: ids as text and as `UUID`, states to
#: redact, text Postgres cannot store, and a value of each enum.
_CALLS: list[dict[str, Any]] = [
    {"action": "auth.login", "actor_label": "alice"},
    {
        "action": "auth.mfa_reset",
        "actor_label": "owner",
        "before_state": {"password": "x", "email": "a@example.test", "role": "trader"},
        "after_state": {"keys": [{"token": "y"}], "n": 2.5, "none": None},
    },
    {
        "action": "orders.submit",
        "actor_label": "bot\x00",
        "actor_user_id": str(uuid.UUID(int=0x51)),
        "actor_ip": "10.0.0.1",
        "session_id": uuid.UUID(int=0x52),
        "object_kind": "order",
        "object_id": "42",
        "object_label": "BTCUSDT",
        "outcome": AuditOutcome.DENIED,
        "severity": Severity.WARNING,
        "reason": "risk_cap",
        "request_id": str(uuid.UUID(int=0x53)),
        "env": ExchangeEnv.DEMO,
    },
]


def _ids() -> Callable[[], uuid.UUID]:
    """A `uuid.uuid4` stand-in that gives every writer the same ids in the same order."""
    counter = itertools.count(1)
    return lambda: uuid.UUID(int=next(counter))


def _writer(repo: FakeAuditRepository, path: Path, clock: FakeClock, **kw: Any) -> AuditWriter:
    return AuditWriter(repo, str(path / "audit.wal"), clock=clock, sleep=repo.retry_sleep, **kw)


async def _dead_flusher(repo: FakeAuditRepository, path: Path, clock: FakeClock) -> AuditWriter:
    """A writer whose flusher gave up on an insert and died: it refuses until `start()`."""
    died = asyncio.Event()

    async def alarm(_reason: str) -> None:
        died.set()

    w = _writer(repo, path, clock, max_insert_attempts=1, on_alarm=alarm)
    await w.start()
    repo.down = True
    await w.emit("auth.login", actor_label="lost-for-now")
    await asyncio.wait_for(died.wait(), 5)
    assert w.failure is not None
    return w


@pytest.mark.parametrize("form", ["model", "json"])
async def test_writer_build_then_ingest_stores_what_emit_stores(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: str
) -> None:
    """Equal WAL frames, rows and chain, whether `ingest()` gets the model (the lane's
    fallback, ADR-0037 decision 1) or its JSON form (a drained frame's `rec`)."""
    stored: list[tuple[bytes, list[dict[str, Any]]]] = []
    for path in (tmp_path / "emit", tmp_path / "build"):
        monkeypatch.setattr(uuid, "uuid4", _ids())
        repo = FakeAuditRepository()
        repo.down = True  # the frames stay in the WAL until they are compared
        w = _writer(repo, path, FakeClock())
        await w.start()
        for call in _CALLS:
            if path.name == "emit":
                await w.emit(**call)
            else:
                built = w.build(**call)
                await w.ingest(built if form == "model" else json.loads(built.model_dump_json()))
        wal = (path / "audit.wal").read_bytes()
        repo.down = False
        await w.flush(5)
        await w.stop(1)
        assert (await AuditQueryService(repo).verify()).verified
        stored.append((wal, repo.rows))
    assert stored[0] == stored[1]
    rows = stored[0][1]
    assert [r["action"] for r in rows] == [c["action"] for c in _CALLS]
    assert rows[1]["before_state"] is not None and "a@example.test" not in rows[1]["before_state"]
    assert json.loads(rows[1]["before_state"])["password"] == REDACTION_MARKER


async def test_writer_build_reads_the_clock_once_and_ingest_keeps_event_ts(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    w = _writer(repo, tmp_path, clock)
    await w.start()
    before = clock.now
    built = w.build("auth.session_revoked", actor_label="alice")
    assert built.event_ts == clock.now == before + timedelta(microseconds=1)
    clock.now += timedelta(hours=1)  # the record waits in the lane a while
    later = clock.now
    await w.ingest(built)
    await w.ingest(w.build("auth.logout", actor_label="bob"))
    await w.flush(5)
    await w.stop(1)
    assert clock.now == later + timedelta(microseconds=1)  # only the second build() read it
    stamps = [row["event_ts"] for row in repo.rows]
    assert stamps == [ts.strftime("%Y-%m-%dT%H:%M:%S.%f+00") for ts in (built.event_ts, clock.now)]


async def test_writer_build_writes_nothing_and_builds_while_the_writer_refuses(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    stopped = _writer(repo, tmp_path / "stopped", clock)
    dead = await _dead_flusher(repo, tmp_path / "dead", clock)
    for w, refusal in ((stopped, AuditWriterStopped), (dead, AuditUnavailable)):
        built = w.build(
            "auth.session_revoked",
            actor_label="alice",
            before_state={"token": "t", "email": "a@example.test"},
        )
        assert built.action == "auth.session_revoked" and built.before_state is not None
        assert built.before_state["token"] == REDACTION_MARKER
        assert built.before_state["email"].startswith(PII_HASH_PREFIX)
        with pytest.raises(UnknownAuditAction):
            w.build("auth.unregistered_action", actor_label="x")
        with pytest.raises(refusal):
            await w.ingest(built)
        assert w.committed_through() == 0
    assert (tmp_path / "stopped" / "audit.wal").read_bytes() == b""
    assert stopped.buffer_depth == 0 and dead.buffer_depth == 1  # only the emit() before it
    await dead.stop(1)


async def test_writer_emit_still_refuses_before_it_builds(
    repo: FakeAuditRepository, tmp_path: Path, clock: FakeClock
) -> None:
    """A stopped writer answers `AuditWriterStopped` even for an unregistered action, and a
    dead flusher `AuditUnavailable`, counted; neither reads the clock."""
    stopped = _writer(repo, tmp_path / "stopped", clock)
    before = clock.now
    with pytest.raises(AuditWriterStopped):
        await stopped.emit("auth.unregistered_action", actor_label="x")
    with pytest.raises(AuditWriterStopped):
        await stopped.emit("auth.login", actor_label="x")
    assert clock.now == before
    dead = await _dead_flusher(repo, tmp_path / "dead", clock)
    refused, before = dead.refused_total, clock.now
    with pytest.raises(AuditUnavailable):
        await dead.emit("auth.unregistered_action", actor_label="x")
    assert dead.refused_total == refused + 1 and clock.now == before
    await dead.stop(1)
