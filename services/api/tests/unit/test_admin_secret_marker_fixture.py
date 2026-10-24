"""E42-Q01 (#962): AUDIT-SECRET-MARKER: the marker's parameters, the real audit writer keeping it
out of the stored entry and the WAL, the refusal of a database not named for tests, and the check
over spoiled worlds. The writer is the real `AuditWriter`, over an in-memory `audit_log` (no
Docker); the Postgres half is `tests/integration/admin/test_admin_fixture_b4b_pg.py`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from candleviewer.audit.actions import AUDIT_ACTIONS
from candleviewer.audit.redact import REDACTION_MARKER, redact
from candleviewer.observability.redaction import redact_text
from tests.fixtures.admin.secret_marker import (
    ACTION,
    ACTOR,
    MARKER,
    OBJECT_ID,
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
    db = FakeDb()
    patch_audit_session(monkeypatch, db)
    await seed_secret_marker(_DSN, tmp_path)
    [row] = _stored(db)
    assert (row["actor_label"], row["action"], row["object_id"]) == (ACTOR, ACTION, OBJECT_ID)
    assert row["before_state"] == {"api_key": REDACTION_MARKER}
    assert row["after_state"] == {"api_secret": REDACTION_MARKER}
    assert MARKER not in json.dumps(row, default=str)
    assert [f for f in _files(tmp_path) if MARKER.encode() in f.read_bytes()] == []
    await check_secret_marker(_DSN)


async def test_a_second_seed_writes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = FakeDb()
    patch_audit_session(monkeypatch, db)
    await seed_secret_marker(_DSN, tmp_path)
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
