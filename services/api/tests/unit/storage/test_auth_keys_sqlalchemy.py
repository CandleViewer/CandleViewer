"""`SqlAlchemyAuthKeyStore`'s statements and transactions (#2152 S2, S4). Each write and its
record share one transaction (BQ-5, C-2.9), checked here over a unit of work that logs every
statement; the SQL itself, the guards and the compare-and-set run on Postgres in
`tests/integration/storage/test_auth_keys_pg.py` (CI lane)."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
import sqlalchemy as sa

from candleviewer.secrets import store as m2
from candleviewer.storage.errors import AuthKeyAuditNotWritten
from candleviewer.storage.repositories import auth_keys_sqlalchemy as m

# Self-discovering: a statement added later cannot dodge the scope guard.
_STATEMENTS = {n: v for n, v in vars(m).items() if isinstance(v, sa.TextClause)}
#: The table's DDL (21 Sec.3.1.5a verbatim), whose `ak_dek_ref` CHECK M2's fake copies.
_MIGRATION = Path(m.__file__).parents[2] / "migrations" / "versions" / "0030_auth_keys.py"
KEY = UUID(int=11)
WRAP = "ak1:" + "ab" * 60
MOVE: dict[str, Any] = {
    "env": "demo", "from_version": 1, "dek_ref": WRAP, "kek_version": 2,
    "audit": ("security.auth_keyring_rewrapped", {"auth_key_id": str(KEY)}),
}  # fmt: skip
ENROLLED = ("security.auth_keyring_enrolled", {"origin": "generated"})
RECORD = {
    "record_id": "00000000-0000-4000-8000-000000000001", "actor_label": "system:secrets",
    "action": "security.auth_keyring_enrolled", "outcome": "success", "severity": "info",
    "event_ts": "2026-10-31T00:00:00+00:00",
}  # fmt: skip


def _ring() -> list[dict[str, Any]]:
    return [
        {"id": UUID(int=n), "env": "demo", "purpose": p, "origin": "generated",
         "dek_ref": WRAP, "kek_version": 1}
        for n, p in ((1, "totp_seal"), (2, "recovery_hmac"))
    ]  # fmt: skip


class _Tx:
    """A relational repository whose unit of work logs each statement by its target (`auth_keys`
    or the record's `audit_log`, `LOCK` for the chain lock), `COMMIT`, `ROLLBACK`, and, on an
    exception, `ABORT`; a key INSERT or UPDATE changes `changed` rows each, the record's INSERT
    `recorded`. Its row builder logs `BUILD`."""

    def __init__(self, changed: int = 1, recorded: int = 1) -> None:
        self.log: list[str] = []
        self._changed, self._recorded = changed, recorded

    def build(self, action: str, fields: dict[str, str]) -> dict[str, Any]:
        self.log.append("BUILD")
        return {**RECORD, "action": action}

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(statement: Any, params: object = None) -> Any:
            sql = " ".join(statement.text.split())
            if "pg_advisory_xact_lock" in sql:
                self.log.append("LOCK")
            else:
                verb, table = sql.split()[0], re.search(r"(audit_log|auth_keys)", sql)
                self.log.append(f"{verb} {table[1] if table else ''}".strip())
            audit = "audit_log" in sql
            return SimpleNamespace(rowcount=self._recorded if audit else self._changed)

        async def commit() -> None:
            self.log.append("COMMIT")

        async def rollback() -> None:
            self.log.append("ROLLBACK")

        try:
            yield SimpleNamespace(
                session=SimpleNamespace(execute=execute), commit=commit, rollback=rollback
            )
        except BaseException:
            self.log.append("ABORT")
            raise


def _store(tx: _Tx, build: Callable[..., Any] | None = None) -> m.SqlAlchemyAuthKeyStore:
    return m.SqlAlchemyAuthKeyStore(cast(Any, tx), env="demo", audit_row=build or tx.build)


def _refuse(action: str, fields: dict[str, str]) -> dict[str, Any]:
    raise ValueError("unregistered action")


def test_statements_name_their_columns_and_never_delete() -> None:
    assert set(_STATEMENTS) == {"_ROWS", "_INSERT", "_REWRAP", "_COUNT", "_MFA_MATERIAL"}
    for name, stmt in _STATEMENTS.items():
        text = str(stmt)
        # 21 Sec.12 forbids `SELECT *` on auth_keys; for this module this test is the guard.
        assert not re.search(r"(?i)select\s+(distinct\s+)?\*|\w\.\*", text), name
        assert "DELETE" not in text.upper() and "TRUNCATE" not in text.upper(), name  # 0030


def test_the_rewrap_is_a_compare_and_set_on_the_row_s_environment_and_kek_version() -> None:
    """The CAS predicate: the row, of the process environment, still at `from_version` (BQ-4)."""
    where = str(m._REWRAP).split("WHERE", 1)[1].split()
    assert " ".join(where) == (
        "id = :id AND env = CAST(:env AS exchange_env) AND kek_version = :from_v"
    )


def test_the_fakes_copies_of_the_table_and_m10_have_not_drifted() -> None:
    """M2's fake refuses the wraps `ak_dek_ref` refuses and raises M10's error by its code (as
    `test_export_keys_sqlalchemy.py` pins the export key's copies)."""
    check = re.search(
        r"CONSTRAINT ak_dek_ref\s+CHECK \(dek_ref ~ '\^(.+?)\$'\)", _MIGRATION.read_text()
    )
    assert check is not None and m2._AUTH_WRAP.pattern == check[1]
    assert m2._AuthKeyAuditNotWritten.code == AuthKeyAuditNotWritten.code


@pytest.mark.parametrize(
    ("changed", "result", "log"),
    [
        (1, True, ["BUILD", "INSERT auth_keys", "INSERT auth_keys", "LOCK", "INSERT audit_log",
                   "COMMIT"]),
        (0, False, ["BUILD", "INSERT auth_keys", "INSERT auth_keys", "ROLLBACK"]),
    ],
    ids=["inserted", "another_boot_s_keyring"],
)  # fmt: skip
async def test_the_keyring_insert_commits_its_record_iff_it_wrote_every_row(
    changed: int, result: bool, log: list[str]
) -> None:
    tx = _Tx(changed=changed)
    assert await _store(tx).insert_keyring(_ring(), audit=ENROLLED) is result and tx.log == log


@pytest.mark.parametrize(
    ("changed", "result", "log"),
    [
        (1, True, ["BUILD", "UPDATE auth_keys", "LOCK", "INSERT audit_log", "COMMIT"]),
        (0, False, ["BUILD", "UPDATE auth_keys"]),  # nothing moved: nothing recorded or committed
    ],
    ids=["moved", "not_moved"],
)
async def test_the_rewrap_commits_its_record_iff_it_moved_the_row(
    changed: int, result: bool, log: list[str]
) -> None:
    tx = _Tx(changed=changed)
    assert await _store(tx).rewrap(KEY, **MOVE) is result and tx.log == log


@pytest.mark.parametrize("write", ["insert", "rewrap"])
async def test_a_write_whose_record_is_not_written_commits_nothing(write: str) -> None:
    tx = _Tx(recorded=0)  # its `record_id` is stored already
    store = _store(tx)
    with pytest.raises(AuthKeyAuditNotWritten) as unwritten:
        if write == "insert":
            await store.insert_keyring(_ring(), audit=ENROLLED)
        else:
            await store.rewrap(KEY, **MOVE)
    assert tx.log[-2:] == ["INSERT audit_log", "ABORT"] and "COMMIT" not in tx.log
    assert unwritten.value.__context__ is None and WRAP not in repr(unwritten.value)


async def test_a_refused_record_or_environment_reaches_no_database() -> None:
    tx = _Tx()
    with pytest.raises(ValueError, match="unregistered action"):
        await _store(tx, _refuse).insert_keyring(_ring(), audit=ENROLLED)
    with pytest.raises(ValueError, match="unregistered action"):
        await _store(tx, _refuse).rewrap(KEY, **MOVE)
    with pytest.raises(m.AuthKeyEnvironmentError):
        await _store(tx).rewrap(KEY, **MOVE | {"env": "live"})
    with pytest.raises(m.AuthKeyEnvironmentError):
        await _store(tx).insert_keyring([{**_ring()[0], "env": "live"}], audit=ENROLLED)
    with pytest.raises(ValueError, match="at least one record"):
        await _store(tx).insert_keyring([], audit=ENROLLED)
    assert tx.log == []
