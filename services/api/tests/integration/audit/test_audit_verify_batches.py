"""Integration: verify's and the export's batch statements on Postgres 16 (#2464; #889 S8). A
batch stops before a row once the renderings before that row reach the byte budget, so it holds
at most the budget plus one entry: an entry over the whole budget comes alone when it is first,
and ends the batch it lands in otherwise; the walk goes on past short batches. Verify never
fetches an entry over the per-entry cap: the read that starts with it names it, and a run stops
there. The export's batch renders verify's columns alike, then `record_id` and `object_label`,
and reads an entry over the cap alone, with every member. Entries go in through the
repository's own `insert`.

Exercised by the CI integration job (testcontainers). Before review, verify's statements were
also run by hand on a scratch Postgres 16.4, and these tests on a local Postgres 16 container.
"""

from __future__ import annotations

import gzip
import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from testcontainers.postgres import PostgresContainer

from candleviewer.audit.export import EXPORT_DIR, ExportPlan, write_export
from candleviewer.audit.query import AuditQueryService, _canonical_hash
from candleviewer.settings import Environment
from candleviewer.storage.errors import AuditEntryTooLarge
from candleviewer.storage.repositories.audit_sqlalchemy import SqlAlchemyAuditRepository
from candleviewer.storage.repositories.relational_sqlalchemy import (
    SqlAlchemyRelationalRepository,
)

pytestmark = pytest.mark.integration

_ROOT = Path(__file__).resolve().parents[3]
_T0 = datetime(2026, 10, 15, tzinfo=UTC)
_BUDGET = 1000  # bytes: a few small entries, and less than one large one


@pytest.fixture(scope="module")
def pg_dsn() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url()
        migrate_dsn = url.replace("postgresql+psycopg2", "postgresql+psycopg")
        subprocess.run(  # fixed argv, literal alembic subcommand, no shell
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_ROOT,
            env={**os.environ, "CV_PG_DSN": migrate_dsn},
            check=True,
        )
        yield url.replace("postgresql+psycopg2", "postgresql+asyncpg")


@pytest.fixture
async def relational(pg_dsn: str) -> AsyncIterator[SqlAlchemyRelationalRepository]:
    """Built inside the test's own loop and disposed before it closes."""
    client = SqlAlchemyRelationalRepository(pg_dsn)
    try:
        yield client
    finally:
        await client.dispose()


async def _append(repo: SqlAlchemyAuditRepository, sizes: list[int]) -> tuple[int, list[int]]:
    """One entry per size, a `reason` of that many characters; returns the id before them and
    their ids, read back: an insert draws two ids since `0045_audit_chain_hardening`."""
    head = await repo.read_head()
    ids: list[int] = []
    for i, size in enumerate(sizes):
        await repo.insert(
            {
                "record_id": uuid.uuid4(),
                "actor_label": "it",
                "action": "auth.login",
                "outcome": "success",
                "severity": "info",
                "reason": "r" * size,
                "event_ts": (_T0 + timedelta(seconds=i)).isoformat(),
            }
        )
        written = await repo.read_head()
        assert written is not None
        ids.append(written[0])
    return 0 if head is None else head[0], ids


def _n(row: tuple[Any, ...]) -> int:
    """What the statement counts for a row: the UTF-8 bytes of its renderings."""
    return len("".join(v for v in row[3:] if v is not None).encode())


def _ids(rows: list[tuple[Any, ...]]) -> list[int]:
    return [int(row[0]) for row in rows]


async def test_a_batch_stops_before_the_row_that_starts_past_the_budget(
    relational: SqlAlchemyRelationalRepository,
) -> None:
    whole = SqlAlchemyAuditRepository(relational)  # the default budget: all twelve fit
    cut = SqlAlchemyAuditRepository(relational, verify_batch_max_bytes=_BUDGET)
    base, ids = await _append(whole, [100] * 12)
    every = await whole.fetch_verify_batch(after_id=base, to_id=ids[-1], limit=100)
    assert _ids(every) == ids
    batch = await cut.fetch_verify_batch(after_id=base, to_id=ids[-1], limit=100)
    assert batch == every[: len(batch)] and 1 < len(batch) < 12
    sizes = [_n(row) for row in every]  # the last row in starts below the budget
    assert sum(sizes[: len(batch) - 1]) < _BUDGET <= sum(sizes[: len(batch)])


async def test_an_entry_over_the_budget_comes_alone_first_and_ends_a_batch_otherwise(
    relational: SqlAlchemyRelationalRepository,
) -> None:
    repo = SqlAlchemyAuditRepository(relational, verify_batch_max_bytes=_BUDGET)
    base, ids = await _append(repo, [10, 10, 5000, 10, 10])  # the third is over the whole budget
    big, last = ids[2], ids[4]
    fetch = repo.fetch_verify_batch
    assert _ids(await fetch(after_id=base, to_id=last, limit=10)) == ids[:3]
    assert _ids(await fetch(after_id=ids[1], to_id=last, limit=10)) == [big]
    assert _ids(await fetch(after_id=big, to_id=last, limit=10)) == ids[3:]
    result = await AuditQueryService(repo).verify(from_id=ids[0], to_id=last, batch_size=10)
    assert (result.verified, result.entries_checked) == (True, 5)


async def test_an_entry_over_the_cap_is_never_fetched_and_stops_the_run(
    relational: SqlAlchemyRelationalRepository,
) -> None:
    repo = SqlAlchemyAuditRepository(relational, verify_max_entry_bytes=2000)
    base, ids = await _append(repo, [10, 10, 5000, 10])  # the third is over the cap
    big, last = ids[2], ids[3]
    batch = await repo.fetch_verify_batch(after_id=base, to_id=last, limit=10)
    assert _ids(batch) == ids[:2]  # ends before it
    with pytest.raises(AuditEntryTooLarge) as err:
        await repo.fetch_verify_batch(after_id=ids[1], to_id=last, limit=10)
    assert err.value.entry_id == big
    with pytest.raises(AuditEntryTooLarge):
        await AuditQueryService(repo).verify(from_id=ids[0], to_id=last, batch_size=10)


async def _user(relational: SqlAlchemyRelationalRepository) -> uuid.UUID:
    """A `users` row, which a set `actor_user_id` must reference."""
    user = uuid.uuid4()
    async with relational.unit_of_work() as uow:
        await uow.session.execute(
            sa.text(
                "INSERT INTO users (id, email, username, password_hash, status) VALUES "
                "(:id, :email, :username, '$argon2id$synthetic', 'active')"
            ),
            {"id": user, "email": f"{user.hex}@example.invalid", "username": f"it_{user.hex[:12]}"},
        )
        await uow.commit()
    return user


def _full(actor: uuid.UUID, i: int, label: str) -> dict[str, Any]:
    """An entry with every nullable column set, each to a value of its own."""
    return {
        "record_id": uuid.uuid4(),
        "actor_user_id": actor,
        "actor_label": f"it {i}",
        "actor_ip": f"203.0.113.{i + 1}",
        "session_id": uuid.uuid4(),
        "action": "orders.submit",
        "object_kind": "order",
        "object_id": f"o-{i}",
        "object_label": label,
        "outcome": "denied",
        "severity": "warning",
        "reason": f"reason {i}",
        "before_state": {"qty": f"{i}.5"},
        "after_state": {"qty": "é", "n": [i]},
        "request_id": uuid.uuid4(),
        "env": "demo",
        "event_ts": (_T0 + timedelta(seconds=i)).isoformat(),
    }


async def test_an_export_batch_renders_verify_s_columns_then_record_id_and_object_label(
    relational: SqlAlchemyRelationalRepository,
) -> None:
    """#889 S8: with every nullable column set to a value of its own, an export batch carries
    verify's renderings, then `record_id` as text and `object_label` as stored."""
    repo, labels = SqlAlchemyAuditRepository(relational), ("BTC 注文", "Zoë")
    head, actor = await repo.read_head(), await _user(relational)
    base = 0 if head is None else head[0]
    records = [_full(actor, i, label) for i, label in enumerate(labels)]
    for record in records:
        await repo.insert(record)
    written = await repo.read_head()
    assert written is not None
    batch = await repo.fetch_export_batch(after_id=base, to_id=written[0], limit=10)
    verify = await repo.fetch_verify_batch(after_id=base, to_id=written[0], limit=10)
    assert [row[:18] for row in batch] == verify and all(None not in row for row in batch)
    for row, record, label in zip(batch, records, labels, strict=True):
        assert (row[18], row[19]) == (str(record["record_id"]), label)


async def test_an_export_batch_reads_an_entry_over_the_cap_alone_and_whole(
    relational: SqlAlchemyRelationalRepository,
) -> None:
    repo = SqlAlchemyAuditRepository(relational, verify_max_entry_bytes=2000)
    base, ids = await _append(repo, [10, 10, 5000, 10])  # the third is over the cap
    big, last = ids[2], ids[3]
    fetch = repo.fetch_export_batch
    assert _ids(await fetch(after_id=base, to_id=last, limit=10)) == ids[:2]
    (alone,) = await fetch(after_id=ids[1], to_id=last, limit=10)
    assert (alone[0], alone[12]) == (big, "r" * 5000)  # first and alone, with every member
    assert _ids(await fetch(after_id=big, to_id=last, limit=10)) == [last]


async def test_an_export_span_count_stops_at_its_cap(
    relational: SqlAlchemyRelationalRepository,
) -> None:
    repo = SqlAlchemyAuditRepository(relational)
    _, ids = await _append(repo, [10, 10, 10, 10])
    span = {"first_id": ids[0], "last_id": ids[-1]}  # four entries, more ids since 0045
    assert [await repo.count_export_span(**span, cap=cap) for cap in (3, 9)] == [3, 4]


async def test_an_export_written_from_postgres_recomputes_every_hash_and_link(
    relational: SqlAlchemyRelationalRepository, tmp_path: Path
) -> None:
    """#889 S8: the writer over the real trigger's renderings, an entry over the cap included."""
    repo = SqlAlchemyAuditRepository(relational, verify_max_entry_bytes=2000)
    _, ids = await _append(repo, [10, 5000, 10])
    head = await repo.read_head()
    assert head is not None
    anchor = await repo.fetch_anchor_hash(ids[0]) or "0" * 64
    key = {"key_id": "cv-audit-export-v1:" + "0" * 16, "public_key": "A" * 43 + "="}
    plan: dict[str, Any] = {"from_ts": _T0, "to_ts": _T0 + timedelta(hours=1), **key}
    plan |= {"first_id": ids[0], "last_id": head[0], "anchor_hash": anchor, "head_id": head[0]}
    plan |= {"head_hash": head[1], "environment": Environment.TESTNET, "compressed": True}
    done = await write_export(ExportPlan(**plan), repo, data_dir=tmp_path, job_id=uuid.uuid4())
    plain = gzip.decompress((tmp_path / EXPORT_DIR / done.name).read_bytes())
    entries = [json.loads(line) for line in plain.split(b"\n")[1:-1]]
    for entry in entries:
        assert entry["prev_hash"] == anchor, entry["id"]
        assert _canonical_hash(anchor, entry) == entry["entry_hash"], entry["id"]
        anchor = entry["entry_hash"]
    assert done.row_count == len(entries) == 3
