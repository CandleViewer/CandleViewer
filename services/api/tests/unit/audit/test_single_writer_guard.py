"""Single-writer guard for `audit_log` (design §5, "Ordering assumption").

`verify` walks the chain in id order. Chain order equals id order only because the one
writer path, `SqlAlchemyAuditRepository.insert`, takes `pg_advisory_xact_lock` *before* its
INSERT, so `nextval` runs under the lock. An INSERT that bypasses it takes the lock only
inside the BEFORE trigger, after `nextval`: two concurrent bypassing INSERTs can chain out
of id order, and `verify` would then report a break that is not one. So no code under
`candleviewer/` (migrations aside) may insert into `audit_log` except that repository.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_PACKAGE = Path(__file__).resolve().parents[3] / "candleviewer"
_WRITER = Path("storage/repositories/audit_sqlalchemy.py")
_TABLE = r"(?:\w+\.)*\"?audit_log\"?(?!\w)"
#: Raw SQL `INSERT INTO`/`COPY`, Core `audit_log.insert()`/`insert(audit_log)`, asyncpg copy.
_BYPASS = re.compile(
    rf"\bINSERT\s+INTO\s+{_TABLE}|\bCOPY\s+{_TABLE}|\baudit_log\s*\.\s*insert\s*\("
    rf"|\binsert\s*\(\s*{_TABLE}|copy_records_to_table\s*\(\s*['\"]audit_log['\"]",
    re.IGNORECASE,
)


@pytest.mark.parametrize(
    "snippet",
    [
        "INSERT INTO audit_log (record_id) VALUES (:r)",
        'insert into public."audit_log" (record_id)',
        "COPY audit_log FROM STDIN",
        "stmt = audit_log.insert().values(record_id=r)",
        "stmt = sa.insert(models.audit_log)",
        "await conn.copy_records_to_table('audit_log', records=rows)",
    ],
)
def test_the_guard_catches_every_insert_form(snippet: str) -> None:
    assert _BYPASS.search(snippet)


@pytest.mark.parametrize(
    "snippet", ["INSERT INTO audit_checkpoints (id)", "INSERT INTO audit_log_archive (id)"]
)
def test_the_guard_ignores_other_tables(snippet: str) -> None:
    assert not _BYPASS.search(snippet)


def test_only_the_audit_repository_inserts_into_audit_log() -> None:
    found = {
        path.relative_to(_PACKAGE): len(_BYPASS.findall(path.read_text(encoding="utf-8")))
        for path in _PACKAGE.rglob("*.py")
        if "migrations" not in path.relative_to(_PACKAGE).parts
    }
    assert {path: n for path, n in found.items() if n} == {_WRITER: 1}
