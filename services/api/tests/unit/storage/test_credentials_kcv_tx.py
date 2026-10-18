"""A KCV enrolment and its `security.kek_enrolled` record share one transaction (#2266 PR C,
C-2.9): the M10 adapter over a unit of work that logs each statement, the commit and the
rollback, as `test_credentials_rewrap_tx.py` does for the re-wrap."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, cast

import pytest

from candleviewer.storage.errors import KcvEnrolmentNotAudited
from candleviewer.storage.repositories.credentials_sqlalchemy import SqlAlchemyCredentialStore

KCV = b"K" * 8
PUT, RECORD = "INSERT kek_versions", ["BUILD", "LOCK", "INSERT audit_log"]


class _Tx:
    """Logs `INSERT <table>`, `LOCK` (the chain lock), `SELECT`, `COMMIT` and, on an exception,
    `ROLLBACK`; an INSERT writes the rows `rows` gives its table. Its row builder logs `BUILD`,
    or refuses."""

    def __init__(self, enrolled: int = 1, recorded: int = 1, *, refuse: bool = False) -> None:
        self.log: list[str] = []
        self._rows, self._refuse = {"kek_versions": enrolled, "audit_log": recorded}, refuse

    def build(self, action: str, fields: dict[str, str]) -> dict[str, Any]:
        if self._refuse:
            raise ValueError("unregistered action")
        self.log.append("BUILD")
        return {
            "record_id": "r", "actor_label": "system:secrets", "action": action,
            "outcome": "success", "severity": "info", "event_ts": "2026-10-18T00:00:00+00:00",
        }  # fmt: skip

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(statement: Any, params: object = None) -> Any:
            words = statement.text.split()
            if words[0] == "INSERT":
                self.log.append(f"INSERT {words[2]}")
                return SimpleNamespace(rowcount=self._rows[words[2]])
            self.log.append("LOCK" if "pg_advisory_xact_lock" in words[1] else "SELECT")
            rows = SimpleNamespace(all=lambda: [{"kcv": KCV}])
            return SimpleNamespace(returns_rows=True, mappings=lambda: rows)

        async def commit() -> None:
            self.log.append("COMMIT")

        try:
            yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)
        except BaseException:
            self.log.append("ROLLBACK")
            raise


def _enrol(tx: _Tx, *, wired: bool = True) -> Any:
    store = SqlAlchemyCredentialStore(cast(Any, tx), audit_row=tx.build if wired else None)
    return store.record_kcv("demo", 3, KCV, audit=("security.kek_enrolled", {"env": "demo"}))


@pytest.mark.parametrize(
    ("enrolled", "log"),
    [(1, [PUT, *RECORD, "COMMIT", "SELECT", "COMMIT"]), (0, [PUT, "COMMIT", "SELECT", "COMMIT"])],
    ids=["enrolled", "enrolled_already"],
)
async def test_an_enrolment_writes_its_record_in_its_transaction_iff_it_inserted_the_row(
    enrolled: int, log: list[str]
) -> None:
    tx = _Tx(enrolled)
    assert await _enrol(tx) == (KCV, bool(enrolled)) and tx.log == log


@pytest.mark.parametrize(
    ("fake", "wired", "error", "log"),
    [
        ({"recorded": 0}, True, KcvEnrolmentNotAudited, [PUT, *RECORD, "ROLLBACK"]),
        ({"refuse": True}, True, ValueError, [PUT, "ROLLBACK"]),
        ({}, False, KcvEnrolmentNotAudited, []),
    ],
    ids=["record_id_already_stored", "builder_fails", "no_builder_wired"],
)
async def test_an_enrolment_without_its_record_commits_nothing(
    fake: dict[str, Any], wired: bool, error: type[Exception], log: list[str]
) -> None:
    tx = _Tx(**fake)  # built per run: a rerun starts from an empty log (C-13.7)
    with pytest.raises(error):
        await _enrol(tx, wired=wired)
    assert tx.log == log
