"""The re-wrap CAS and its audit record share one transaction (#2266, C-2.9): the M10 adapter
over a unit of work that logs each statement, the commit and the rollback."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest

from candleviewer.storage.errors import RewrapAuditNotWired, RewrapAuditNotWritten
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore

KEY = UUID(int=11)
MOVE: dict[str, Any] = {
    "env": "demo", "from_version": 1, "dek_ref": "v1:00", "kek_version": 2,
    "audit": ("security.credential_rewrapped", {"key_id": str(KEY)}),
}  # fmt: skip
RECORD = {
    "record_id": "00000000-0000-4000-8000-000000000001", "actor_label": "system:secrets",
    "action": "security.credential_rewrapped", "outcome": "success", "severity": "info",
    "event_ts": "2026-10-18T00:00:00+00:00",
}  # fmt: skip


class _Tx:
    """A relational repository whose unit of work logs `UPDATE`, `LOCK` (the chain lock),
    `INSERT`, `COMMIT` and, on an exception, `ROLLBACK`; an UPDATE moves `moved` rows and an
    INSERT writes `inserted`. Its row builder `build` logs `BUILD`."""

    def __init__(self, moved: int = 1, inserted: int = 1) -> None:
        self.log: list[str] = []
        self._counts = {"UPDATE": moved, "INSERT": inserted}

    def build(self, action: str, fields: dict[str, str]) -> dict[str, Any]:
        self.log.append("BUILD")
        return _build(action, fields)

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(statement: Any, params: object = None) -> Any:
            sql = statement.text
            self.log.append("LOCK" if "pg_advisory_xact_lock" in sql else sql.split()[0])
            return SimpleNamespace(rowcount=self._counts.get(self.log[-1], 0))

        async def commit() -> None:
            self.log.append("COMMIT")

        try:
            yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)
        except BaseException:
            self.log.append("ROLLBACK")
            raise


def _build(action: str, fields: dict[str, str]) -> dict[str, Any]:
    return {**RECORD, "action": action}


def _refuse(action: str, fields: dict[str, str]) -> dict[str, Any]:
    raise ValueError("unregistered action")


@pytest.mark.parametrize(
    ("moved", "log"),
    [(1, ["UPDATE", "BUILD", "LOCK", "INSERT", "COMMIT"]), (0, ["UPDATE"])],
    ids=["moved", "not_moved"],
)
async def test_the_cas_builds_locks_and_inserts_its_record_iff_it_moved_the_row(
    moved: int, log: list[str]
) -> None:
    tx = _Tx(moved=moved)
    store = SqlAlchemyCredentialStore(cast(Any, tx), audit_row=tx.build)
    assert await store.rewrap(KEY, **MOVE) is bool(moved) and tx.log == log


@pytest.mark.parametrize(
    ("inserted", "builder", "error", "log"),
    [
        (0, _build, RewrapAuditNotWritten, ["UPDATE", "LOCK", "INSERT", "ROLLBACK"]),
        (1, _refuse, ValueError, ["UPDATE", "ROLLBACK"]),
        (1, None, RewrapAuditNotWired, []),
    ],
    ids=["record_id_already_stored", "builder_fails", "no_builder_wired"],
)
async def test_a_cas_without_its_record_commits_nothing(
    inserted: int, builder: Callable[..., Any] | None, error: type[Exception], log: list[str]
) -> None:
    tx = _Tx(inserted=inserted)  # built per run: a rerun starts from an empty log (C-13.7)
    with pytest.raises(error):
        await SqlAlchemyCredentialStore(cast(Any, tx), audit_row=builder).rewrap(KEY, **MOVE)
    assert tx.log == log
