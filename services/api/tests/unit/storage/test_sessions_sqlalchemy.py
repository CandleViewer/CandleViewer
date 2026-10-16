"""`SqlAlchemySessionRepository` with a fake unit of work (no DB available; the
real-Postgres round trip is an integration test, not run locally: no docker)."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from candleviewer.storage.repositories.sessions_sqlalchemy import (
    SqlAlchemySessionRepository,
    row_to_fields,
)

_NOW = datetime(2026, 9, 30, tzinfo=UTC)
#: `(step_up_elevations, step_up_failures, readonly_until)` as `update_step_up_state` passes it.
StepUpColumns = tuple[dict[str, datetime], int, datetime | None]


def _row(**over: Any) -> SimpleNamespace:
    m: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "user_id": str(uuid.uuid4()),
        "refresh_token_hash": "h",
        "access_token_jti": str(uuid.uuid4()),
        "issued_at": _NOW,
        "last_seen_at": _NOW,
        "expires_at": _NOW,
        "revoked_at": None,
        "revoked_reason": None,
        "ip": "10.0.0.1/32",
        "user_agent": "ua",
        "device_label": None,
        "is_electron": False,
        "mfa_satisfied_at": None,
        "idle_timeout_s": 900,
        "step_up_elevations": "{}",
        "step_up_failures": 0,
        "readonly_until": None,
    }
    m.update(over)
    return SimpleNamespace(_mapping=m)


class _Result:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def first(self) -> SimpleNamespace | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[SimpleNamespace]:
        return self._rows


class _Session:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, stmt: Any, params: dict[str, Any]) -> _Result:
        self.calls.append((str(stmt), params))
        return _Result(self.rows)


class _Relational:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.session = _Session(rows)
        self.commits = 0

    @asynccontextmanager
    async def unit_of_work(self) -> Any:
        rel = self

        async def commit() -> None:
            rel.commits += 1

        yield SimpleNamespace(session=self.session, commit=commit)


def _repo(rows: list[SimpleNamespace]) -> tuple[SqlAlchemySessionRepository, _Relational]:
    rel = _Relational(rows)
    return SqlAlchemySessionRepository(rel, dict), rel  # type: ignore[arg-type]  # fake relational stub, structurally compatible


def test_row_to_fields_strips_inet_mask_and_parses_uuids() -> None:
    f = row_to_fields(_row())
    assert f["ip"] == "10.0.0.1"
    assert isinstance(f["id"], uuid.UUID)
    assert f["idle_timeout_s"] == 900


async def test_revoke_is_conditional_update_returning_and_parameterised() -> None:
    repo, rel = _repo([_row(revoked_reason="logout")])
    got = await repo.revoke("sid", reason="logout", now=_NOW)
    sql, params = rel.session.calls[0]
    assert "revoked_at IS NULL" in sql
    assert "RETURNING" in sql
    assert params == {"id": "sid", "reason": "logout", "now": _NOW}
    assert got["revoked_reason"] == "logout"
    assert rel.commits == 1


async def test_revoke_already_revoked_returns_none() -> None:
    repo, _ = _repo([])
    assert await repo.revoke("sid", reason="x", now=_NOW) is None


async def test_revoke_all_passes_except_session() -> None:
    repo, rel = _repo([_row(), _row()])
    out = await repo.revoke_all_for_user("u", reason="logout_all", now=_NOW, except_session_id="e")
    assert len(out) == 2
    assert rel.session.calls[0][1]["except_id"] == "e"


async def test_family_walk_returns_ids_and_lookup_by_jti_is_bound() -> None:
    repo, _rel = _repo(
        [SimpleNamespace(_mapping={"id": "a"}), SimpleNamespace(_mapping={"id": "b"})]
    )
    assert await repo.walk_rotation_family("a") == ("a", "b")
    repo2, rel2 = _repo([_row()])
    await repo2.find_by_access_token_jti("jti")
    assert rel2.session.calls[0][1] == {"j": "jti"}


async def test_update_step_up_state_rewrites_the_row_it_locked_in_one_transaction() -> None:
    """#2304: the step-up columns are read under the row lock and rewritten from that read in
    the same transaction, never from a copy of the row read before it."""
    until = datetime(2026, 9, 30, 0, 5, tzinfo=UTC)
    stored = '{"keys": "2026-09-30T00:05:00+00:00"}'
    repo, rel = _repo([_row(step_up_elevations=stored, step_up_failures=1)])
    seen: list[StepUpColumns] = []

    def change(state: StepUpColumns) -> StepUpColumns:
        seen.append(state)
        return {"users": until}, 2, None

    got = await repo.update_step_up_state("sid", change)

    (lock_sql, lock_params), (write_sql, params) = rel.session.calls
    assert "revoked_at IS NULL" in lock_sql and lock_sql.endswith("FOR NO KEY UPDATE")
    assert lock_params == {"id": "sid"} and seen == [({"keys": until}, 1, None)]
    assert write_sql.startswith("UPDATE sessions SET step_up_elevations = CAST(:elevations")
    assert "revoked_at IS NULL" in write_sql and "RETURNING" in write_sql
    elevations = '{"users": "2026-09-30T00:05:00+00:00"}'
    assert params == {"id": "sid", "elevations": elevations, "failures": 2, "readonly_until": None}
    assert rel.commits == 1 and got is not None


async def test_update_step_up_state_of_a_revoked_or_absent_row_writes_nothing() -> None:
    repo, rel = _repo([])
    seen: list[StepUpColumns] = []

    def change(state: StepUpColumns) -> StepUpColumns:
        seen.append(state)
        return state

    assert await repo.update_step_up_state("sid", change) is None
    assert seen == [] and len(rel.session.calls) == 1 and rel.commits == 0


async def test_lift_idle_lock_restamps_and_clears_elevations_in_one_conditional_write() -> None:
    """#2301 (B16.7): one UPDATE re-stamps `last_seen_at` and clears
    `step_up_elevations`; `step_up_failures` and `readonly_until` are kept."""
    repo, rel = _repo([_row(step_up_failures=2)])
    got = await repo.lift_idle_lock("sid", now=_NOW)
    ((sql, params),) = rel.session.calls
    assignments = sql.split("WHERE", 1)[0]
    assert "last_seen_at = :now" in assignments
    assert "step_up_elevations = '{}'::jsonb" in assignments
    assert "step_up_failures" not in assignments and "readonly_until" not in assignments
    assert "revoked_at IS NULL" in sql and "RETURNING" in sql
    assert params == {"id": "sid", "now": _NOW}
    assert rel.commits == 1 and got["step_up_failures"] == 2


async def test_consume_step_up_key_is_one_conditional_update_of_the_live_unexpired_key() -> None:
    """#2304: a one-shot grant is removed by one conditional UPDATE, never read-modify-write, so
    of two concurrent consumers only one gets the row."""
    key = "once:killswitch:" + str(uuid.UUID(int=1)) + ":" + "a" * 64
    repo, rel = _repo([_row()])
    got = await repo.consume_step_up_key("sid", key=key, now=_NOW)
    sql, params = rel.session.calls[0]
    assert "SET step_up_elevations = step_up_elevations - CAST(:key AS text)" in sql
    assert "revoked_at IS NULL" in sql and "RETURNING" in sql
    assert "CAST(step_up_elevations ->> CAST(:key AS text) AS timestamptz) > :now" in sql
    assert params == {"id": "sid", "key": key, "now": _NOW}
    assert got is not None and rel.commits == 1


async def test_consume_step_up_key_that_updates_no_row_returns_none() -> None:
    repo, _ = _repo([])
    assert await repo.consume_step_up_key("sid", key="once:killswitch", now=_NOW) is None
