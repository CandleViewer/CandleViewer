"""AUDIT-SECRET-MARKER (E42-Q01, #962): a secret-shaped marker the audit redactor must keep out of
the drawer and the export (AD-S04-07, C-12.6).

The seed emits one `api_key.import` entry through the real audit writer, whose states carry `MARKER`
as a caller's mistake would: under `api_key` before and under `api_secret` after. The audit redactor
replaces a value by the name of its field, so the entry is stored with `<redacted:secret>` in both
states, and nothing that reads it (the drawer's diff, the export) can show the marker. A scan of
either for `MARKER` finds nothing; the check shows the same of the stored row.

`MARKER` is `FIXTURE-SECRET-` and 24 letters and digits: plainly the fixture's, and no credential.
Its body is the shape of an exchange key, so the log redactor replaces it too; for that reason the
fixtures' secret scan (`test_admin_fixture_handles.py`) skips this one value, by name, and no other.
The entry can never be removed (C-5.7), so a database not named for tests is `FixtureRefused` before
anything is read or written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import sqlalchemy as sa

from candleviewer.audit.redact import REDACTION_MARKER
from candleviewer.db import models as m
from tests.fixtures.admin.audit_session import audit_session, read_audit_db
from tests.fixtures.admin.seed import FixtureCheckError

MARKER: Final = "FIXTURE-SECRET-0123456789ABCDEF01234567"
ACTOR: Final = "fixture-secret-marker"
ACTION: Final = "api_key.import"
OBJECT_ID: Final = "fixture-secret-marker"
#: The writer's WAL file, in the directory the caller gives.
WAL_NAME: Final = "fixture-secret-marker.wal"
#: What each state holds once stored: the redactor's marker under the same field.
STORED: Final = ({"api_key": REDACTION_MARKER}, {"api_secret": REDACTION_MARKER})


def _mine(*columns: Any) -> sa.Select[Any]:
    return sa.select(*columns).where(m.audit_log.c.actor_label == ACTOR)


async def seed_secret_marker(dsn: str, wal_dir: Path) -> None:
    """The entry through a writer built on `dsn`, its WAL in `wal_dir`. A second run finds it and
    writes nothing. `dsn` is the SQLAlchemy asyncpg URL of a migrated test database."""
    async with audit_session(dsn, wal_dir / WAL_NAME) as (relational, writer):
        async with relational.engine.connect() as conn:
            held = (await conn.execute(_mine(m.audit_log.c.id))).all()
        if not held:
            await writer.emit(
                ACTION,
                actor_label=ACTOR,
                object_kind="api_key",
                object_id=OBJECT_ID,
                before_state={"api_key": MARKER},
                after_state={"api_secret": MARKER},
            )


async def check_secret_marker(dsn: str) -> None:
    """`FixtureCheckError` unless the one entry is stored with the redacted states and the marker
    is in none of its columns. It never prints a stored value."""
    [rows] = await read_audit_db(dsn, _mine(m.audit_log))
    failed = [f"{len(rows)} entries by {ACTOR}, not 1"] if len(rows) != 1 else []
    for row in rows:
        if MARKER in json.dumps(dict(row), default=str):
            failed.append("the marker is stored in the entry")
        if (row["before_state"], row["after_state"]) != STORED:
            failed.append("a state of the entry is not the redacted one")
    if failed:
        raise FixtureCheckError("AUDIT-SECRET-MARKER: " + "; ".join(failed))
