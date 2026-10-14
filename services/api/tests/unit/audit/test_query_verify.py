"""Query pagination/filters, chain verify and tamper location (property
test), export stub, checkpoint job."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from audit_fakes import FakeAuditRepository, FakeClock
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from candleviewer.audit.checkpoint import run_checkpoint
from candleviewer.audit.cursor import decode_cursor
from candleviewer.audit.errors import AuditChainBroken
from candleviewer.audit.models import AuditOutcome, Severity
from candleviewer.audit.query import VERIFY_BATCH_SIZE, AuditQueryService

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


async def test_verify_an_empty_or_past_the_head_range_checks_nothing(
    repo: FakeAuditRepository, clock: FakeClock
) -> None:
    await _seed(repo, 3, clock)
    result = await AuditQueryService(repo).verify(from_id=4)
    assert (result.verified, result.entries_checked, repo.verify_calls) == (True, 0, [])


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
