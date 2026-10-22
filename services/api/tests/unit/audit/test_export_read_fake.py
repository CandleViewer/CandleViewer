"""The in-memory export read (`audit_fakes`) cuts as `_EXPORT_BATCH_SQL` does (#889 S8), so a
unit test can meet a short batch and an entry over the per-entry cap read alone."""

from __future__ import annotations

from audit_fakes import FakeAuditRepository


async def _filled(repo: FakeAuditRepository, sizes: tuple[int, ...]) -> None:
    """One entry per size, a `reason` of that many characters."""
    for i, size in enumerate(sizes):
        record = {"record_id": f"r{i}", "actor_label": "t", "action": "auth.login"}
        record |= {"outcome": "success", "severity": "info", "reason": "x" * size}
        await repo.insert(record | {"event_ts": "2026-10-21T12:00:00+00:00"})


async def test_the_fake_export_batch_stops_at_the_byte_budget(repo: FakeAuditRepository) -> None:
    await _filled(repo, (10, 10, 10))
    repo.max_bytes = 1  # the first row always goes in
    assert [row[0] for row in await repo.fetch_export_batch(after_id=0, to_id=3, limit=10)] == [1]


async def test_the_fake_export_batch_reads_an_entry_over_the_cap_alone_and_whole(
    repo: FakeAuditRepository,
) -> None:
    await _filled(repo, (10, 600, 10))
    repo.max_entry = 500
    fetch = repo.fetch_export_batch
    assert [row[0] for row in await fetch(after_id=0, to_id=3, limit=10)] == [1]  # ends before it
    (alone,) = await fetch(after_id=1, to_id=3, limit=10)
    assert (alone[0], alone[12], alone[18]) == (2, "x" * 600, "r1")  # first, alone and whole
    assert [row[0] for row in await fetch(after_id=2, to_id=3, limit=10)] == [3]
