"""Query pagination/filters, chain verify and tamper location (property
test), export stub, checkpoint job."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from audit_fakes import FakeAuditRepository, FakeClock
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.audit import query as query_mod
from candleviewer.audit.checkpoint import run_checkpoint
from candleviewer.audit.cursor import decode_cursor
from candleviewer.audit.errors import AuditChainBroken
from candleviewer.audit.models import AuditOutcome, ChainBreakKind, Severity
from candleviewer.audit.query import (
    VERIFY_BATCH_SIZE,
    AuditQueryService,
    VerifyRangeBeyondHead,
)

_ME, _OTHER = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))


async def _seed(repo: FakeAuditRepository, n: int, clock: FakeClock, first: int = 0) -> None:
    for i in range(first, first + n):
        await repo.insert(
            {
                "record_id": f"00000000-0000-4000-8000-{i:012d}",
                "action": "orders.submit" if i % 2 else "auth.login",
                "actor_label": f"u{i}",
                "outcome": "denied" if i % 3 == 0 else "success",
                "severity": "error" if i % 5 == 0 else "info",
                "object_id": str(i),
                "before_state": {"i": i} if i % 4 else None,
                "event_ts": clock().isoformat(),
            }
        )


async def test_query_cursor_pagination_walks_newest_first(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 7, clock)
    svc = AuditQueryService(repo)
    page1 = await svc.query(restrict_to_actor=None, limit=3)
    assert [e.id for e in page1.items] == [7, 6, 5] and page1.meta.has_more
    assert page1.meta.count == 3 and page1.meta.next_cursor is not None
    position = decode_cursor(page1.meta.next_cursor)
    assert (position.ts, position.id) == (page1.items[-1].ts, 5)
    page2 = await svc.query(restrict_to_actor=None, limit=3, after=position)
    assert [e.id for e in page2.items] == [4, 3, 2] and page2.meta.has_more
    last = await svc.query(
        restrict_to_actor=None, limit=3, after=decode_cursor(page2.meta.next_cursor or "")
    )
    assert [e.id for e in last.items] == [1] and not last.meta.has_more
    assert last.meta.next_cursor is None
    assert repo.page_calls[-1]["after"] == (page2.items[-1].ts, 2)


async def test_query_orders_by_event_time_then_id(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    """Order is `(ts DESC, id DESC)`, not id: a row replayed late with an older `ts`
    (WAL replay, clock skew) sorts by its time, and equal times by id."""
    await _seed(repo, 3, clock)
    repo.rows[2]["event_ts"] = repo.rows[0]["event_ts"]  # id 3 shares id 1's time
    page = await AuditQueryService(repo).query(restrict_to_actor=None)
    assert [e.id for e in page.items] == [2, 3, 1]


async def test_query_paging_is_stable_while_entries_append(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    """Every entry present when paging starts comes back exactly once, whatever is
    written between pages (newer, or older by `ts`)."""
    await _seed(repo, 20, clock)
    before = {r["id"] for r in repo.rows}
    svc, seen, after, i = AuditQueryService(repo), [], None, 100
    while True:
        page = await svc.query(restrict_to_actor=None, limit=3, after=after)
        seen += [e.id for e in page.items]
        await _seed(repo, 1, clock, first=i)  # a new head
        clock.now -= timedelta(seconds=1)  # and a late replay, older than every entry
        await _seed(repo, 1, clock, first=i + 1)
        clock.now, i = clock.now + timedelta(seconds=1), i + 2
        if page.meta.next_cursor is None:
            break
        after = decode_cursor(page.meta.next_cursor)
    old = [s for s in seen if s in before]
    assert sorted(old) == sorted(before) and len(old) == len(set(old))


async def test_query_passes_the_resolved_scope_to_the_repository(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 4, clock)
    for row in repo.rows:
        row["actor_user_id"] = _ME if row["id"] % 2 else _OTHER
    page = await AuditQueryService(repo).query(restrict_to_actor=_ME, actor_user_id=_OTHER)
    assert [e.id for e in page.items] == [3, 1]
    assert repo.page_calls[-1]["restrict_to_actor"] == _ME


async def test_query_filters_by_subject_id_ip_and_full_text(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 6, clock)
    repo.rows[1].update(object_label="Breakout BTC", actor_ip="10.0.0.9")
    svc = AuditQueryService(repo)
    page = await svc.query(restrict_to_actor=None, subject_id="1")
    assert [e.id for e in page.items] == [2]
    assert [e.id for e in (await svc.query(restrict_to_actor=None, ip="10.0.0.9")).items] == [2]
    found = await svc.query(restrict_to_actor=None, q="breakout btc")
    assert [e.id for e in found.items] == [2]
    assert (await svc.query(restrict_to_actor=None, q="breakout eth")).items == []
    assert (await svc.query(restrict_to_actor=None, q="  ")).meta.count == 6  # blank: no search
    assert repo.page_calls[-1]["q"] is None


async def test_query_filters_by_action_severity_outcome(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 10, clock)
    page = await AuditQueryService(repo).query(
        restrict_to_actor=None, actions=["auth.login"], severity="error", outcome="denied"
    )
    assert [e.id for e in page.items] == [1]
    assert page.items[0].outcome is AuditOutcome.DENIED
    assert page.items[0].severity is Severity.ERROR


async def test_query_filters_by_subject_type(repo: FakeAuditRepository, clock: FakeClock) -> None:
    """PR #1608 review finding 5: `subject_type` used to be accepted and
    silently dropped instead of being passed to the repository."""
    await repo.insert(
        {
            "record_id": "00000000-0000-4000-8000-000000000100",
            "action": "order.place",
            "actor_label": "u1",
            "outcome": "success",
            "severity": "info",
            "object_kind": "order",
            "object_id": "1",
            "event_ts": clock().isoformat(),
        }
    )
    await repo.insert(
        {
            "record_id": "00000000-0000-4000-8000-000000000101",
            "action": "key.rotate",
            "actor_label": "u1",
            "outcome": "success",
            "severity": "info",
            "object_kind": "api_key",
            "object_id": "2",
            "event_ts": clock().isoformat(),
        }
    )
    page = await AuditQueryService(repo).query(restrict_to_actor=None, subject_type="order")
    assert [e.subject_type for e in page.items] == ["order"]


async def test_query_rejects_naive_from_ts(repo: FakeAuditRepository) -> None:
    from datetime import datetime

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        await AuditQueryService(repo).query(restrict_to_actor=None, from_ts=datetime(2026, 1, 1))


async def test_query_rejects_from_ts_not_before_to_ts(repo: FakeAuditRepository) -> None:
    from datetime import UTC, datetime

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        await AuditQueryService(repo).query(
            restrict_to_actor=None,
            from_ts=datetime(2026, 1, 2, tzinfo=UTC),
            to_ts=datetime(2026, 1, 2, tzinfo=UTC),  # `to` is exclusive: an empty window
        )


async def test_verify_empty_log_is_verified(repo: FakeAuditRepository) -> None:
    result = await AuditQueryService(repo).verify()
    assert result.verified and result.entries_checked == 0 and result.first_bad_id is None


async def test_verify_batches_and_subrange(repo: FakeAuditRepository, clock: FakeClock) -> None:
    await _seed(repo, 12, clock)
    svc = AuditQueryService(repo)
    full = await svc.verify(batch_size=5)
    assert full.verified and full.entries_checked == 12
    part = await svc.verify(from_id=4, to_id=9, batch_size=2)
    assert part.verified and part.entries_checked == 6


async def test_verify_broken_prev_link_located(repo: FakeAuditRepository, clock: FakeClock) -> None:
    await _seed(repo, 5, clock)
    del repo.rows[2]  # out-of-band delete of id 3
    result = await AuditQueryService(repo).verify()
    assert not result.verified and result.first_bad_id == 4
    assert result.kind is ChainBreakKind.PREV_HASH_MISMATCH


async def test_verify_anchors_on_the_greatest_id_below_from_id(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    """Design §1 gap 10: ids have gaps (a WAL-replay duplicate or a rolled-back insert uses
    up a sequence value). With no row at `from_id - 1`, the anchor is the stored
    `entry_hash` of the greatest id below `from_id`, never genesis (a false break)."""
    await _seed(repo, 3, clock)
    repo.burn_ids(1)  # id 4 is never written
    await _seed(repo, 3, clock, first=3)  # ids 5, 6, 7
    svc = AuditQueryService(repo)
    for from_id in (4, 5):
        result = await svc.verify(from_id=from_id)
        assert (result.verified, result.entries_checked, result.first_bad_id) == (True, 3, None)
    assert (await svc.verify()).verified  # and the whole chain, across the gap


async def test_verify_clamps_to_the_head_read_when_it_starts(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    """Entries appended during the run, and a `to_id` beyond the head, are not checked."""
    await _seed(repo, 5, clock)
    fetch = repo.fetch_verify_batch

    async def fetch_then_append(**kw: Any) -> list[tuple[Any, ...]]:
        rows = await fetch(**kw)
        await _seed(repo, 1, clock, first=100 + len(repo.rows))  # a write lands mid-run
        return rows

    repo.fetch_verify_batch = fetch_then_append  # type: ignore[method-assign]  # spy on the fake
    result = await AuditQueryService(repo).verify(to_id=1_000, batch_size=2)
    assert (result.verified, result.entries_checked) == (True, 5)
    assert {to_id for _, to_id, _ in repo.verify_calls} == {5}


async def test_verify_walks_keyset_batches_of_ten_thousand_by_default(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 10, clock)
    assert VERIFY_BATCH_SIZE == 10_000
    await AuditQueryService(repo).verify()
    assert repo.verify_calls == [(0, 10, 10_000)]
    repo.verify_calls.clear()
    await AuditQueryService(repo).verify(from_id=3, batch_size=4)
    assert repo.verify_calls == [(2, 10, 4), (6, 10, 4)]  # a full last batch ends at the head


class _SpyHasher:
    """Runs each batch check inline and records how many fetches were issued by then."""

    def __init__(self, repo: FakeAuditRepository) -> None:
        self.repo, self.fetched_at_submit = repo, list[int]()

    async def run(self, fn: Callable[[], Any]) -> Any:
        await asyncio.sleep(0)  # one loop turn: a prefetch scheduled before this call starts
        self.fetched_at_submit.append(len(self.repo.verify_calls))
        return fn()

    def shutdown(self) -> None:
        return None


async def test_verify_fetches_the_next_batch_while_hashing_one(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    """Pipelined: batch n+1 is in flight while batch n is hashed, and batch n+2 is not
    fetched before batch n is done, so at most two batches are held."""
    await _seed(repo, 9, clock)
    hasher = _SpyHasher(repo)
    svc = AuditQueryService(repo, hasher)  # type: ignore[arg-type]  # structural stand-in
    assert (await svc.verify(batch_size=3)).entries_checked == 9
    assert hasher.fetched_at_submit == [2, 3, 3]


async def test_verify_hashes_off_the_event_loop(
    repo: FakeAuditRepository, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed(repo, 3, clock)
    threads: list[int] = []
    walk = query_mod._walk_batch

    def spy(*args: Any) -> Any:
        threads.append(threading.get_ident())
        return walk(*args)

    monkeypatch.setattr(query_mod, "_walk_batch", spy)
    assert (await AuditQueryService(repo).verify()).verified
    assert threads and threading.get_ident() not in threads


async def test_verify_stops_at_the_first_divergence_and_cancels_the_prefetch(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 9, clock)
    repo.rows[1]["reason"] = "forged"  # id 2
    repo.rows[7]["reason"] = "forged"  # id 8, never reached
    result = await AuditQueryService(repo).verify(batch_size=3)
    assert (result.verified, result.entries_checked, result.first_bad_id) == (False, 2, 2)
    assert result.kind is ChainBreakKind.ENTRY_HASH_MISMATCH
    assert len(repo.verify_calls) <= 2  # the prefetch of ids 4-6, never the third batch


async def test_verify_reports_a_broken_link_before_a_bad_hash(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    """Both checks fail on id 3: the link is checked first (`prev_hash_mismatch`)."""
    await _seed(repo, 4, clock)
    repo.rows[2].update(prev_hash="f" * 64, reason="forged")
    result = await AuditQueryService(repo).verify()
    assert (result.first_bad_id, result.kind) == (3, ChainBreakKind.PREV_HASH_MISMATCH)
    assert "kind" not in result.model_dump(mode="json")  # internal: not in the response


async def test_verify_takes_checked_at_from_the_injected_clock(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    from datetime import UTC, datetime

    await _seed(repo, 2, clock)
    at = datetime(2026, 10, 14, 23, 0, tzinfo=UTC)
    assert (await AuditQueryService(repo, clock=lambda: at).verify()).checked_at == at


async def test_verify_from_id_beyond_the_head_is_not_found(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 3, clock)
    with pytest.raises(VerifyRangeBeyondHead):
        await AuditQueryService(repo).verify(from_id=4)
    assert repo.verify_calls == []


async def test_verify_beyond_the_head_with_a_checkpoint_above_is_the_truncation(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    """#2446: not a 404 when a checkpoint names an id above the head; the echoed range
    has `from_id > to_id` and nothing is walked."""
    await _seed(repo, 3, clock)
    repo.checkpoints[6] = {"head_id": 6}
    result = await AuditQueryService(repo).verify(from_id=5)
    assert (result.verified, result.entries_checked, result.first_bad_id) == (False, 0, 6)
    assert (result.from_id, result.to_id, result.kind) == (5, 3, ChainBreakKind.TAIL_TRUNCATED)
    assert (result.anchor_hash, result.last_hash) == (repo.rows[2]["entry_hash"], None)
    assert repo.verify_calls == []


@pytest.mark.parametrize(("head_hash", "truncated_at"), [(None, None), ("e" * 64, 4)])
async def test_a_checkpoint_above_the_head_read_is_a_truncation_only_if_its_entry_differs(
    repo: FakeAuditRepository, clock: FakeClock, head_hash: str | None, truncated_at: int | None
) -> None:
    """Review of #2460: the checkpoint job may name an entry written after the head was read.
    If that entry exists with the checkpoint's hash it is no truncation (here, `from_id` past
    the head read is then a 404); a missing entry or another hash is one."""
    await _seed(repo, 4, clock)
    repo.checkpoints[4] = {"head_id": 4, "head_hash": head_hash or repo.rows[3]["entry_hash"]}

    async def head_read_before_id_4() -> tuple[int, int]:
        return (1, 3)

    repo.read_bounds = head_read_before_id_4  # type: ignore[method-assign]  # the race, staged
    svc = AuditQueryService(repo)
    if truncated_at is None:
        with pytest.raises(VerifyRangeBeyondHead):
            await svc.plan_verify(from_id=5, to_id=None)
    else:
        assert (await svc.plan_verify(from_id=5, to_id=None)).truncated_at == truncated_at


@pytest.mark.parametrize("checkpoint", [None, 4])
async def test_verify_an_empty_log_echoes_no_range(
    repo: FakeAuditRepository, checkpoint: int | None
) -> None:
    if checkpoint is not None:
        repo.checkpoints[checkpoint] = {"head_id": checkpoint}  # every entry is gone
    result = await AuditQueryService(repo).verify()
    assert (result.from_id, result.to_id, result.entries_checked) == (None, None, 0)
    assert (result.anchor_hash, result.last_hash) == ("0" * 64, None)
    assert (result.verified, result.first_bad_id) == (checkpoint is None, checkpoint)


async def test_verify_marks_only_a_run_from_genesis_to_the_head_as_the_full_chain(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    """The gauge rule's input: a partial range is never the full chain, nor is an empty log."""
    assert not (await AuditQueryService(repo).verify()).full_chain  # an empty log
    await _seed(repo, 5, clock)
    svc = AuditQueryService(repo)
    assert (await svc.verify()).full_chain
    assert not (await svc.verify(from_id=2)).full_chain
    assert not (await svc.verify(to_id=4)).full_chain
    assert "full_chain" not in (await svc.verify()).model_dump(mode="json")


async def test_verify_a_head_entry_gone_during_the_run_is_a_truncation(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    """Review of #2462: a range ending at the head must pass the head entry; when it vanished
    during the run the run breaks there, so the chain gauge can never read 1 over it."""
    await _seed(repo, 5, clock)
    fetch = repo.fetch_verify_batch

    async def delete_then_fetch(**kw: Any) -> list[tuple[Any, ...]]:
        repo.rows[:] = [r for r in repo.rows if r["id"] != 5]
        return await fetch(**kw)

    repo.fetch_verify_batch = delete_then_fetch  # type: ignore[method-assign]  # spy
    result = await AuditQueryService(repo).verify()
    assert (result.verified, result.first_bad_id) == (False, 5)
    assert (result.kind, result.entries_checked) == (ChainBreakKind.TAIL_TRUNCATED, 4)


def _checkpoint(repo: FakeAuditRepository, head_id: int, head_hash: str | None = None) -> None:
    """A checkpoint naming `head_id`, by default with that entry's stored hash."""
    stored = next((r["entry_hash"] for r in repo.rows if r["id"] == head_id), "f" * 64)
    repo.checkpoints[head_id] = {"head_id": head_id, "head_hash": head_hash or stored}


async def test_verify_passes_the_checkpoints_that_match(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 6, clock)
    for head_id in (2, 5):
        _checkpoint(repo, head_id)
    result = await AuditQueryService(repo).verify()
    assert (result.verified, result.entries_checked) == (True, 6)


@pytest.mark.parametrize(("from_id", "checked"), [(1, 3), (5, 0)])
async def test_verify_a_checkpoint_that_does_not_match_is_a_break(
    repo: FakeAuditRepository, clock: FakeClock, from_id: int, checked: int
) -> None:
    """In the range, checked after the entry's own checks (which count it); below the
    range, the stored hash, before anything is walked."""
    await _seed(repo, 6, clock)
    _checkpoint(repo, 3, head_hash="e" * 64)
    result = await AuditQueryService(repo).verify(from_id=from_id)
    assert (result.verified, result.first_bad_id) == (False, 3)
    assert (result.kind, result.entries_checked) == (ChainBreakKind.CHECKPOINT_MISMATCH, checked)
    assert result.last_hash == (repo.rows[1]["entry_hash"] if checked else None)


@pytest.mark.parametrize(("from_id", "checked"), [(1, 3), (6, 0)])
async def test_verify_a_checkpoint_naming_no_entry_is_a_break(
    repo: FakeAuditRepository, clock: FakeClock, from_id: int, checked: int
) -> None:
    await _seed(repo, 3, clock)
    repo.burn_ids(1)  # id 4 is never written
    await _seed(repo, 3, clock, first=3)  # ids 5-7
    _checkpoint(repo, 4, head_hash="e" * 64)
    result = await AuditQueryService(repo).verify(from_id=from_id)
    assert (result.first_bad_id, result.entries_checked) == (4, checked)
    assert result.kind is ChainBreakKind.CHECKPOINT_MISSING
    assert all(after <= 3 for after, _, _ in repo.verify_calls)  # the walk stops below it


async def test_verify_walks_on_past_a_matching_checkpoint_below_the_range(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 5, clock)
    _checkpoint(repo, 2)
    result = await AuditQueryService(repo).verify(from_id=4)
    assert (result.verified, result.entries_checked) == (True, 2)


async def test_verify_a_missing_checkpointed_entry_at_from_id_walks_nothing(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 3, clock)
    repo.burn_ids(1)  # id 4 is never written
    await _seed(repo, 2, clock, first=3)  # ids 5-6
    _checkpoint(repo, 4, head_hash="e" * 64)
    result = await AuditQueryService(repo).verify(from_id=4)
    assert (result.first_bad_id, result.kind) == (4, ChainBreakKind.CHECKPOINT_MISSING)
    assert (result.entries_checked, result.last_hash, repo.verify_calls) == (0, None, [])


async def test_verify_reports_an_entrys_own_break_before_its_checkpoint(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 4, clock)
    _checkpoint(repo, 3, head_hash="e" * 64)
    repo.rows[2]["reason"] = "forged"  # id 3 also fails its own hash
    svc = AuditQueryService(repo)
    result = await svc.verify()
    assert (result.first_bad_id, result.kind) == (3, ChainBreakKind.ENTRY_HASH_MISMATCH)
    repo.rows[1]["reason"] = "forged"  # id 2, before the checkpoint: first in id order
    assert (await svc.verify()).first_bad_id == 2


async def test_verify_a_range_ending_at_the_head_breaks_on_a_checkpoint_above_it(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 4, clock)
    _checkpoint(repo, 9)
    svc = AuditQueryService(repo)
    whole = await svc.verify()
    assert (whole.first_bad_id, whole.kind) == (9, ChainBreakKind.TAIL_TRUNCATED)
    assert (whole.entries_checked, whole.last_hash) == (4, repo.rows[3]["entry_hash"])
    assert (await svc.verify(to_id=3)).verified  # ends below the head: not a truncation


async def _append_with_checkpoint(
    repo: FakeAuditRepository, clock: FakeClock, head_hash: str | None = None
) -> None:
    """The checkpoint job during a run: one more entry, then a checkpoint naming it."""
    await _seed(repo, 1, clock, first=100 + len(repo.rows))
    new = repo.rows[-1]
    repo.checkpoints[new["id"]] = {
        "head_id": new["id"],
        "head_hash": head_hash or new["entry_hash"],
    }


@pytest.mark.parametrize(("head_hash", "first_bad_id"), [(None, None), ("e" * 64, 6)])
async def test_a_checkpoint_written_during_the_walk_breaks_only_if_its_entry_differs(
    repo: FakeAuditRepository, clock: FakeClock, head_hash: str | None, first_bad_id: int | None
) -> None:
    """Review of #2460: a checkpoint naming an entry written during the run is no truncation;
    one whose entry has another hash (a reused id) is reported."""
    await _seed(repo, 5, clock)
    fetch = repo.fetch_verify_batch

    async def fetch_then_checkpoint(**kw: Any) -> list[tuple[Any, ...]]:
        rows = await fetch(**kw)
        if len(repo.rows) == 5:  # once, while the walk runs
            await _append_with_checkpoint(repo, clock, head_hash)
        return rows

    repo.fetch_verify_batch = fetch_then_checkpoint  # type: ignore[method-assign]  # spy
    result = await AuditQueryService(repo).verify()
    assert (result.verified, result.first_bad_id) == (first_bad_id is None, first_bad_id)
    assert result.kind is (None if first_bad_id is None else ChainBreakKind.TAIL_TRUNCATED)


async def test_a_checkpoint_written_between_plan_and_run_is_no_break(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 5, clock)
    svc = AuditQueryService(repo)
    plan = await svc.plan_verify(from_id=None, to_id=None)
    await _append_with_checkpoint(repo, clock)  # names id 6, past the head the plan read
    assert (await svc.run_verify(plan)).verified


async def test_a_checkpointed_entry_deleted_during_the_run_is_missing(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    """Review of #2460: the last checkpointed entry, deleted once the run started, leaves no
    next row whose link would break; the walk never visited it, so it is missing."""
    await _seed(repo, 5, clock)
    _checkpoint(repo, 5)
    fetch = repo.fetch_verify_batch

    async def delete_then_fetch(**kw: Any) -> list[tuple[Any, ...]]:
        repo.rows[:] = [r for r in repo.rows if r["id"] != 5]
        return await fetch(**kw)

    repo.fetch_verify_batch = delete_then_fetch  # type: ignore[method-assign]  # spy
    result = await AuditQueryService(repo).verify()
    assert (result.first_bad_id, result.kind) == (5, ChainBreakKind.CHECKPOINT_MISSING)


async def test_verify_beyond_the_head_reports_an_earlier_checkpoint_break_first(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 3, clock)
    _checkpoint(repo, 2, head_hash="e" * 64)
    _checkpoint(repo, 6)
    result = await AuditQueryService(repo).verify(from_id=5)
    assert (result.first_bad_id, result.kind) == (2, ChainBreakKind.CHECKPOINT_MISMATCH)


@pytest.mark.parametrize(
    ("from_id", "to_id", "expected"),
    [
        (None, None, (7, 10)),  # the newest span
        (3, None, (3, 6)),  # filled in from `from_id`
        (8, None, (8, 10)),  # ... clipped to the head
        (None, 100, (7, 10)),  # `to_id` clamped to the head, then filled in
        (None, 2, (1, 2)),  # ... clipped to the first entry
        (2, 40, (2, 10)),  # both given: clamped only
    ],
)
async def test_plan_defaults_the_range_from_one_bounds_read(
    repo: FakeAuditRepository,
    clock: FakeClock,
    from_id: int | None,
    to_id: int | None,
    expected: tuple[int, int],
) -> None:
    await _seed(repo, 10, clock)
    reads = repo.read_bounds
    calls: list[int] = []

    async def counted() -> tuple[int, int] | None:
        calls.append(1)
        return await reads()

    repo.read_bounds = counted  # type: ignore[method-assign]  # spy on the fake
    plan = await AuditQueryService(repo).plan_verify(from_id=from_id, to_id=to_id, max_span=4)
    assert ((plan.from_id, plan.to_id), plan.head_id, calls) == (expected, 10, [1])


async def test_plan_fills_in_down_to_the_first_entry_not_to_id_one(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    repo.burn_ids(2)  # the first entry is id 3
    await _seed(repo, 3, clock)
    plan = await AuditQueryService(repo).plan_verify(from_id=None, to_id=4, max_span=10)
    assert (plan.from_id, plan.to_id) == (3, 4)


@pytest.mark.parametrize(
    ("from_id", "to_id", "max_span", "full"),
    [
        (None, None, 10, True),  # the whole log fits the span
        (1, None, 10, True),  # below the first entry
        (None, None, 2, False),  # the newest span only
        (4, None, 10, False),
        (None, 4, 10, False),  # short of the head
    ],
)
async def test_plan_marks_a_range_from_the_first_entry_to_the_head_as_the_full_chain(
    repo: FakeAuditRepository,
    clock: FakeClock,
    from_id: int | None,
    to_id: int | None,
    max_span: int,
    full: bool,
) -> None:
    repo.burn_ids(2)  # the first entry is id 3
    await _seed(repo, 3, clock)  # ids 3-5
    plan = await AuditQueryService(repo).plan_verify(
        from_id=from_id, to_id=to_id, max_span=max_span
    )
    assert plan.full_chain is full


async def test_verify_echoes_the_anchor_and_the_last_entry_that_passed(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 5, clock)
    svc, hashes = AuditQueryService(repo), [r["entry_hash"] for r in repo.rows]
    whole = await svc.verify()
    assert (whole.from_id, whole.to_id, whole.last_hash) == (1, 5, hashes[4])
    assert whole.anchor_hash == "0" * 64  # genesis
    assert (await svc.verify(from_id=3)).anchor_hash == hashes[1]  # the stored predecessor
    repo.rows[3]["reason"] = "forged"  # id 4
    assert (await svc.verify(from_id=3)).last_hash == hashes[2]  # id 3 passed
    assert (await svc.verify(from_id=4)).last_hash is None  # none passed


class _FakeTimer:
    """A fake clock for the run deadline: `sleep` returns once the test moves time past it."""

    def __init__(self) -> None:
        self.passed, self.asked = asyncio.Event(), list[float]()

    async def sleep(self, delay: float) -> None:
        self.asked.append(delay)
        await self.passed.wait()


async def test_verify_past_its_deadline_is_stopped_with_its_statement(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 3, clock)
    timer, entered, stalled = _FakeTimer(), asyncio.Event(), list[asyncio.Task[Any]]()

    async def never(**_kw: Any) -> list[tuple[Any, ...]]:
        stalled.append(asyncio.current_task())  # type: ignore[arg-type]  # inside a task
        entered.set()
        await asyncio.Event().wait()
        return []

    repo.fetch_verify_batch = never  # type: ignore[method-assign]  # a fetch that never answers
    svc = AuditQueryService(repo, sleep=timer.sleep)
    plan = await svc.plan_verify(from_id=None, to_id=None)
    run = asyncio.ensure_future(svc.run_verify(plan, deadline_s=60))
    await entered.wait()
    timer.passed.set()  # the fake clock moves past the deadline
    with pytest.raises(TimeoutError):
        await run
    assert timer.asked == [60] and stalled and all(t.done() for t in stalled)


async def test_verify_within_its_deadline_returns_and_drops_its_timer(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 3, clock)
    svc = AuditQueryService(repo, sleep=_FakeTimer().sleep)
    plan = await svc.plan_verify(from_id=None, to_id=None)
    assert (await svc.run_verify(plan, deadline_s=60)).verified
    timers = [t for t in asyncio.all_tasks() if t.get_name() == "audit.verify.deadline"]
    assert all(t.done() for t in timers)


async def test_verify_walks_on_past_batches_cut_short_by_the_byte_budget(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    """Oversized entries: each batch stops at the byte budget (its first row always
    admitted), and a short batch does not end the walk."""
    for i in range(4):
        await repo.insert(
            {
                "record_id": f"00000000-0000-4000-8000-{i:012d}",
                "action": "auth.login",
                "actor_label": "u",
                "outcome": "success",
                "severity": "info",
                "after_state": {"blob": "x" * 5000},
                "event_ts": clock().isoformat(),
            }
        )
    repo.max_bytes = 1000
    result = await AuditQueryService(repo).verify(batch_size=10)
    assert (result.verified, result.entries_checked) == (True, 4)
    assert [after for after, _, _ in repo.verify_calls] == [0, 1, 2, 3]  # one row a batch


async def test_verify_a_range_inside_an_id_gap_checks_nothing(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 2, clock)
    repo.burn_ids(2)  # ids 3 and 4 are never written
    await _seed(repo, 1, clock, first=2)  # id 5
    result = await AuditQueryService(repo).verify(from_id=3, to_id=4)
    assert (result.verified, result.entries_checked) == (True, 0)
    assert repo.verify_calls == [(2, 4, VERIFY_BATCH_SIZE)]


async def test_verify_cancelled_mid_run_leaves_no_fetch_running(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 6, clock)
    gate, fetch = asyncio.Event(), repo.fetch_verify_batch
    pending: list[asyncio.Task[Any]] = []

    async def stalled(**kw: Any) -> list[tuple[Any, ...]]:
        if kw["after_id"] > 0:  # the prefetch never answers
            pending.append(asyncio.current_task())  # type: ignore[arg-type]  # inside a task
            gate.set()
            await asyncio.Event().wait()
        return await fetch(**kw)

    repo.fetch_verify_batch = stalled  # type: ignore[method-assign]  # spy on the fake
    svc = AuditQueryService(repo)
    run = asyncio.ensure_future(svc.verify(batch_size=3))
    await gate.wait()
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    assert pending and all(task.done() for task in pending)
    assert svc._hasher.pending == 0  # the hashing job finished, too


@pytest.mark.parametrize("batch_size", [0, -1])
async def test_verify_with_no_room_in_a_batch_is_refused_not_verified(
    repo: FakeAuditRepository, clock: FakeClock, batch_size: int
) -> None:
    """Review of #2450: a batch of 0 rows used to walk nothing and report `verified`."""
    await _seed(repo, 2, clock)
    with pytest.raises(ValueError, match="batch_size"):
        await AuditQueryService(repo).verify(batch_size=batch_size)


_FIELDS = ["actor_label", "action", "reason", "before_state", "object_id", "event_ts", "severity"]


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    n=st.integers(min_value=1, max_value=15),
    data=st.data(),
)
def test_verify_any_single_tamper_reports_first_divergent_id(n: int, data: st.DataObject) -> None:
    repo = FakeAuditRepository()
    asyncio.run(_seed(repo, n, FakeClock()))
    victim = data.draw(st.integers(min_value=0, max_value=n - 1))
    field = data.draw(st.sampled_from(_FIELDS))
    original = repo.rows[victim][field]
    repo.rows[victim][field] = (original or "") + "X"
    result = asyncio.run(AuditQueryService(repo).verify(batch_size=4))
    assert not result.verified
    assert result.first_bad_id == victim + 1


def test_chain_broken_error_carries_id() -> None:
    err = AuditChainBroken(42)
    assert err.first_bad_id == 42 and "42" in str(err)


async def test_checkpoint_empty_log_writes_nothing(
    repo: FakeAuditRepository, tmp_path: Path
) -> None:
    assert await run_checkpoint(repo, off_box_path=str(tmp_path / "cp.ndjson")) is None
    assert not (tmp_path / "cp.ndjson").exists()


async def test_checkpoint_writes_db_row_and_off_box_file(
    repo: FakeAuditRepository, clock: FakeClock, tmp_path: Path
) -> None:
    await _seed(repo, 3, clock)
    path = tmp_path / "offbox" / "cp.ndjson"
    result = await run_checkpoint(repo, off_box_path=str(path))
    assert result is not None and result.head_id == 3 and result.row_count == 3
    assert repo.checkpoints[3]["head_hash"] == repo.rows[-1]["entry_hash"]
    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert line["head_hash"] == repo.rows[-1]["entry_hash"] and line["head_id"] == 3
    await run_checkpoint(repo, off_box_path=str(path))  # idempotent per head_id
    assert len(repo.checkpoints) == 1


@pytest.mark.parametrize("bad", ["", "x"])
async def test_verify_detects_tampered_head_hash(
    repo: FakeAuditRepository, clock: FakeClock, bad: str
) -> None:
    await _seed(repo, 2, clock)
    repo.rows[-1]["entry_hash"] = bad
    result = await AuditQueryService(repo).verify()
    assert result.first_bad_id == 2


_HASHED_KEYS = (
    "actor_user_id",
    "actor_label",
    "actor_ip",
    "session_id",
    "action",
    "object_kind",
    "object_id",
    "outcome",
    "severity",
    "reason",
    "before_state",
    "after_state",
    "request_id",
    "env",
    "event_ts",
)
_field = st.one_of(st.none(), st.text(alphabet="ab:-1|", max_size=4))


# deadline=None: 300 examples x 32 generated strings takes 12-15 s on the CI
# runner; hypothesis's default 200 ms per-example deadline trips under full-suite
# load (observed on PR #1601, unrelated diff). The property itself is cheap and
# deterministic; the deadline is the only source of flakiness (C-9.3).
@settings(max_examples=300, deadline=None)
@given(a=st.lists(_field, min_size=16, max_size=16), b=st.lists(_field, min_size=16, max_size=16))
def test_canonical_hash_input_is_injective(a: list[str | None], b: list[str | None]) -> None:
    from candleviewer.audit.query import _canonical_field

    def encode(vals: list[str | None]) -> str:
        return "".join(_canonical_field(v) for v in vals)

    if a != b:
        assert encode(a) != encode(b)


def test_canonical_field_golden() -> None:
    from candleviewer.audit.query import _canonical_field, _canonical_hash

    assert _canonical_field(None) == "-" and _canonical_field("") == "0:"
    assert _canonical_field("ab") == "2:ab" and _canonical_field("é") == "1:é"
    row = dict.fromkeys(_HASHED_KEYS)
    row.update(actor_label="a", action="auth.login", outcome="success", severity="info")
    # sha256("64:000..0" "-" "1:a" "-" "-" "10:auth.login" "-" "-" "7:success" "4:info" "-"*6)
    import hashlib

    expected = hashlib.sha256(
        ("64:" + "0" * 64 + "-1:a--10:auth.login--7:success4:info" + "-" * 6).encode()
    ).hexdigest()
    assert _canonical_hash("0" * 64, row) == expected


@pytest.mark.parametrize(
    ("value", "framed"),
    [
        (None, "-"),  # SQL NULL
        ("", "0:"),  # empty string: not NULL
        ("é", "1:é"),  # U+00E9: 1 character, 2 UTF-8 bytes
        ("e\u0301", "2:e\u0301"),  # e + combining acute: 2 characters
        ("日本", "2:日本"),  # 2 characters, 6 bytes
        ("\U0001f600", "1:\U0001f600"),  # outside the BMP: 1 character (not 2 UTF-16 units)
        ("1:-", "3:1:-"),  # the framing characters inside a value
    ],
)
def test_canonical_field_pins_the_trigger_framing(value: str | None, framed: str) -> None:
    """`audit_field()`: NULL is `-`, else `<length>:<value>`, the length in characters as
    Postgres `length(text)` counts them in a UTF-8 database, never in bytes."""
    from candleviewer.audit.query import _canonical_field

    assert _canonical_field(value) == framed


def test_canonical_digest_hashes_the_utf8_bytes_of_the_framed_fields() -> None:
    import hashlib

    from candleviewer.audit.query import HASHED_FIELDS, _canonical_digest, _canonical_hash

    renderings = ["\U0001f600", None, "", *([None] * (len(HASHED_FIELDS) - 3))]
    framed = "64:" + "0" * 64 + "1:\U0001f600" + "-" + "0:" + "-" * (len(HASHED_FIELDS) - 3)
    expected = hashlib.sha256(framed.encode("utf-8")).hexdigest()
    assert _canonical_digest("0" * 64, renderings) == expected
    assert _canonical_hash("0" * 64, dict(zip(HASHED_FIELDS, renderings, strict=True))) == expected


def test_sqlstate_extraction_and_timeout_mapping() -> None:
    import sqlalchemy as sa

    from candleviewer.storage.repositories import audit_sqlalchemy as mod

    class _Orig(Exception):
        sqlstate = "57014"

    class _Wrapped(Exception):
        def __init__(self) -> None:
            self.__cause__ = _Orig()

    assert mod._sqlstate(sa.exc.DBAPIError("s", {}, _Orig())) == "57014"
    assert mod._sqlstate(sa.exc.DBAPIError("s", {}, _Wrapped())) == "57014"
    assert mod._sqlstate(sa.exc.DBAPIError("s", {}, Exception())) is None


async def test_verify_a_deleted_predecessor_breaks_at_from_id(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    """Review of #2449: with row `from_id - 1` deleted out of band, the anchor is the
    greatest id below it, so `from_id`'s link is wrong and the break is `from_id`."""
    await _seed(repo, 6, clock)
    del repo.rows[3]  # id 4
    result = await AuditQueryService(repo).verify(from_id=5)
    assert (result.verified, result.first_bad_id, result.entries_checked) == (False, 5, 1)
    assert result.kind is ChainBreakKind.PREV_HASH_MISMATCH
