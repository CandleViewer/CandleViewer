"""E42-Q01 (#962): AUDIT-SECRET-MARKER: the marker's parameters, the real audit writer keeping it
out of the stored entry and the WAL, a second seed after a run cut before its flush, the refusal of
a database not named for tests, and the check over spoiled worlds. The writer is the real
`AuditWriter`, over an in-memory `audit_log` (no Docker); the Postgres half is
`tests/integration/admin/test_admin_fixture_b4b_pg.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.redact import REDACTION_MARKER, redact
from candleviewer.audit.repository import AuditRepository
from candleviewer.audit.wal import AuditWal
from candleviewer.audit.writer import AuditWriter
from candleviewer.observability.redaction import redact_text
from tests.fixtures.admin.secret_marker import (
    ACTION,
    ACTOR,
    MARKER,
    OBJECT_ID,
    WAL_NAME,
    check_secret_marker,
    seed_secret_marker,
)
from tests.fixtures.admin.seed import FixtureCheckError, FixtureRefused
from tests.unit._admin_fake_db import FakeDb, patch_audit_session

_DSN = "postgresql+asyncpg://fixture@127.0.0.1:1/test"  # nothing connects: the fakes answer


def _stored(db: FakeDb) -> list[dict[str, Any]]:
    return db.tables["audit_log"]


def _files(directory: Path) -> list[Path]:
    return list(directory.iterdir())


def test_the_marker_is_synthetic_and_the_log_redactor_replaces_it_by_shape() -> None:
    assert MARKER.startswith("FIXTURE-SECRET-")
    assert redact_text(MARKER) == "[redacted:key-shape]"


def test_the_audit_redactor_replaces_it_by_the_name_of_the_field_that_holds_it() -> None:
    assert redact({"api_key": MARKER, "api_secret": MARKER}) == {
        "api_key": REDACTION_MARKER,
        "api_secret": REDACTION_MARKER,
    }
    assert redact({"note": MARKER}) == {"note": MARKER}  # by name, not by shape: the seed's fields


def test_the_entrys_action_is_registered() -> None:
    assert ACTION in AUDIT_ACTIONS


async def test_the_seed_writes_one_entry_and_the_marker_stays_out_of_it_and_the_wal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Each record the WAL is handed is caught as it is appended: the flush compacts the file, so a
    scan of it afterwards would find nothing whatever it had held."""
    db = FakeDb()
    patch_audit_session(monkeypatch, db)
    appended: list[dict[str, Any]] = []
    append = AuditWal.append

    def caught(wal: AuditWal, record: dict[str, Any]) -> int:
        appended.append(record)
        return append(wal, record)

    monkeypatch.setattr(AuditWal, "append", caught)
    await seed_secret_marker(_DSN, tmp_path)
    [row] = _stored(db)
    assert (row["actor_label"], row["action"], row["object_id"]) == (ACTOR, ACTION, OBJECT_ID)
    assert row["before_state"] == {"api_key": REDACTION_MARKER}
    assert row["after_state"] == {"api_secret": REDACTION_MARKER}
    assert MARKER not in json.dumps(row, default=str)
    assert (len(appended), MARKER in json.dumps(appended, default=str)) == (1, False)
    await check_secret_marker(_DSN)


async def test_a_second_seed_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = FakeDb()
    patch_audit_session(monkeypatch, db)
    await seed_secret_marker(_DSN, tmp_path)
    await seed_secret_marker(_DSN, tmp_path)
    assert len(_stored(db)) == 1


class _Down:
    """An `audit_log` that is unreachable: the entry stays in the WAL."""

    async def insert(self, record: dict[str, Any]) -> None:
        raise OSError("the database is down")


async def test_a_seed_after_a_run_cut_before_its_flush_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A run that ended between the emit and the flush leaves the entry in the WAL. The next run's
    writer replays it inside its flusher, after `start()` returns: a seed that read before the
    flush would find no entry and emit a second one, and audit rows can never be removed."""
    cut = AuditWriter(cast("AuditRepository", _Down()), str(tmp_path / WAL_NAME))
    await cut.start()
    await cut.emit(
        ACTION,
        actor_label=ACTOR,
        object_kind="api_key",
        object_id=OBJECT_ID,
        before_state={"api_key": MARKER},
        after_state={"api_secret": MARKER},
    )
    await cut.stop(0.05)
    db = FakeDb()
    patch_audit_session(monkeypatch, db)
    await seed_secret_marker(_DSN, tmp_path)
    assert len(_stored(db)) == 1


async def test_a_database_not_named_for_tests_is_refused_before_a_writer_or_a_row(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = FakeDb("candleviewer")
    built = patch_audit_session(monkeypatch, db)
    for run in (seed_secret_marker(_DSN, tmp_path), check_secret_marker(_DSN)):
        with pytest.raises(FixtureRefused):
            await run
    assert (built, db.shapes, "audit_log" in db.tables) == (
        [],
        ["SELECT current_database()"] * 2,
        False,
    )
    assert _files(tmp_path) == []  # no WAL file either


def _entry(**changed: Any) -> dict[str, Any]:
    """The entry the seed leaves, with `changed`."""
    kept = {
        "before_state": {"api_key": REDACTION_MARKER},
        "after_state": {"api_secret": REDACTION_MARKER},
    }
    return {"id": 1, "actor_label": ACTOR, "reason": None} | kept | changed


_SPOILS = [
    ("no entry", [], "0 entries by fixture-secret-marker, not 1"),
    ("two entries", [_entry(), _entry(id=2)], "2 entries by fixture-secret-marker, not 1"),
    ("marker in the reason", [_entry(reason=MARKER)], "the marker is stored in the entry"),
    (
        "marker in a state",
        [_entry(before_state={"api_key": MARKER})],
        "the marker is stored in the entry; a state of the entry is not the redacted one",
    ),
    (
        "a state left as it was",
        [_entry(after_state={"api_secret": "left"})],
        "a state of the entry is not the redacted one",
    ),
    ("a state missing", [_entry(after_state=None)], "a state of the entry is not the redacted one"),
]


@pytest.mark.parametrize(("rows", "named"), [c[1:] for c in _SPOILS], ids=[c[0] for c in _SPOILS])
async def test_the_check_names_a_spoiled_world_and_never_prints_the_marker(
    monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]], named: str
) -> None:
    patch_audit_session(monkeypatch, FakeDb(audit_log=rows))
    with pytest.raises(FixtureCheckError, match=re.escape(named)) as failed:
        await check_secret_marker(_DSN)
    assert MARKER not in str(failed.value)
