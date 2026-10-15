"""Query, verify and export against `audit_log` (ticket "Scope /
Deliverables": `GET /admin/audit`, `POST /admin/audit/verify`,
`POST /admin/audit/export`).

`verify()` recomputes `audit_chain()`'s canonical serialisation in Python,
batch by batch (`batch_size` rows at a time — ticket "Technical notes":
"`verify` streams in batches so it does not load the table into memory"),
and returns the id of the first row whose stored `entry_hash` does not match
the recomputed one, or whose `prev_hash` does not equal the previous row's
`entry_hash` (covers both an altered row and a deleted-and-reinserted row
breaking the link, ticket AC "Tampering is detected and located").
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any

from candleviewer.audit.cursor import AuditCursor, encode_cursor
from candleviewer.audit.errors import AuditError
from candleviewer.audit.hashing import ChainHasher
from candleviewer.audit.models import (
    AUDIT_QUERY_DEFAULT_LIMIT,
    AuditEntry,
    AuditPage,
    AuditPageMeta,
    AuditQueryRequest,
    ChainBreakKind,
    VerifyResult,
)
from candleviewer.audit.repository import AuditRepository
from candleviewer.audit.verify_slot import VerifySlot
from candleviewer.observability.context import spawn
from candleviewer.settings import Settings

_GENESIS_HASH = "0" * 64
#: Rows per verify batch (ticket "Technical notes").
VERIFY_BATCH_SIZE = 10_000
#: The `audit_verify_max_span` default (#2392): the most ids one range may span.
VERIFY_MAX_SPAN: int = Settings.model_fields["audit_verify_max_span"].default
_PREFETCH = "audit.verify.prefetch"
#: The hashed columns after `prev_hash`, in the order `audit_chain()` hashes them
#: (`21-database-schema.md` §3.10.1).
HASHED_FIELDS = (
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


def _canonical_field(value: object) -> str:
    """Mirror of the SQL `audit_field()`: NULL -> `-`, else `<len>:<value>`
    (length in characters, as Postgres `length(text)`). Prefix-free, so the
    concatenation of fields is unambiguous (PR #1561 finding 8)."""
    if value is None:
        return "-"
    text = str(value)
    return f"{len(text)}:{text}"


def _canonical_digest(prev_hash: str, renderings: Iterable[str | None]) -> str:
    """`audit_chain()`'s digest: `prev_hash`, then the renderings in `HASHED_FIELDS` order,
    each framed by `_canonical_field`, then SHA-256 over the UTF-8 bytes."""
    payload = _canonical_field(prev_hash) + "".join(map(_canonical_field, renderings))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_hash(prev_hash: str, row: Mapping[str, Any]) -> str:
    """Recompute `audit_chain()`'s digest.

    `row` carries every hashed column already rendered to text by Postgres
    with the trigger's own casts (see `AuditRepository.fetch_verify_batch`),
    so this is a pure concatenation of `_canonical_field` encodings — the
    same length-prefixed form as the trigger's `audit_field()`.
    """
    return _canonical_digest(prev_hash, (row[name] for name in HASHED_FIELDS))


@dataclass(frozen=True, slots=True)
class _Walk:
    checked: int  # rows examined, the first divergent one included
    passed: int  # rows that passed every check
    last_hash: str  # `entry_hash` of the last row that passed (else the expected predecessor)
    bad_id: int | None = None
    kind: ChainBreakKind | None = None
    last_id: int = 0  # the id of the last row that passed (0: none did)


_NO_CHECKPOINTS: Mapping[int, str] = MappingProxyType({})


def _walk_batch(
    expected_prev: str,
    rows: Sequence[Sequence[Any]],
    checkpoints: Mapping[int, str] = _NO_CHECKPOINTS,
) -> _Walk:
    """Check one batch, on the hasher's thread. `rows` are `(id, prev_hash, entry_hash,
    *renderings)` in id order. Per row: the link, then the hash (design §5), then the
    `head_hash` of a checkpoint naming that id (`checkpoints`, by id)."""
    for index, row in enumerate(rows):
        if row[1] != expected_prev:
            kind = ChainBreakKind.PREV_HASH_MISMATCH
            return _Walk(index + 1, index, expected_prev, row[0], kind)
        if _canonical_digest(expected_prev, row[3:]) != row[2]:
            kind = ChainBreakKind.ENTRY_HASH_MISMATCH
            return _Walk(index + 1, index, expected_prev, row[0], kind)
        if checkpoints.get(row[0], row[2]) != row[2]:
            kind = ChainBreakKind.CHECKPOINT_MISMATCH
            return _Walk(index + 1, index, expected_prev, row[0], kind)
        expected_prev = row[2]
    return _Walk(len(rows), len(rows), expected_prev, last_id=rows[-1][0] if rows else 0)


@dataclass(frozen=True, slots=True)
class VerifyPlan:
    """A verify range after defaulting (contract #2392/#2446). `head_id` is the one head read
    (0 for an empty log). `from_id`/`to_id` are `None` for an empty log; `from_id > to_id`
    only with `truncated_at`, a checkpoint `head_id` above the head found at defaulting."""

    from_id: int | None
    to_id: int | None
    head_id: int
    truncated_at: int | None = None


class VerifyRangeBeyondHead(AuditError):
    """`from_id` is past the chain head and no checkpoint names an id above it (404)."""

    def __init__(self) -> None:
        super().__init__("from_id is beyond the chain head")


async def _discard(task: asyncio.Future[Any]) -> None:
    """Cancel a prefetch nobody will read and wait for it, so no statement outlives the
    call and its error is not reported as unretrieved. Never swallows the caller's own
    cancellation: `asyncio.wait` raises it."""
    task.cancel()
    await asyncio.wait([task])
    if not task.cancelled():
        task.exception()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _page_chain_verified(rows: list[dict[str, Any]]) -> bool:
    """Design §5 on a page: every row's hashed fields recompute to its `entry_hash`, and its
    `prev_hash` is the `entry_hash` of the row before it in the chain (genesis for the
    first), whether or not that row is on the page. A row whose canonical form was not
    fetched in full (`chain` is `None`, over the render caps) is unverified, never
    verified. It shows the returned rows match their stored hashes and links, not that the
    rest of the chain does (`verify` checks a range). The hash is unkeyed SHA-256: a writer
    with database access could rebuild a consistent chain, which only external anchors detect.

    So `False` means either that a row or a link does not check out, or that the page was
    not fully checked because a rendering or the page is over the render caps. It is not by
    itself evidence of tampering: a client should offer `verify` over the range rather
    than report one. On a Manager's page (only its own entries), a `False` from the caps
    also tells it that a hashed field it cannot see renders to more than 16 Ki
    characters, or the page to more than 4 Mi: one bit of size, accepted in the security
    review of the query slice, as nothing depends on the content of hidden fields."""
    for row in rows:
        chain = row["chain"]
        if chain is None:
            return False
        expected_prev = chain["chain_prev_hash"] or _GENESIS_HASH
        if row["prev_hash"] != expected_prev:
            return False
        if _canonical_hash(expected_prev, chain) != row["entry_hash"]:
            return False
    return True


class AuditQueryService:
    """Backs the three `/admin/audit*` endpoints. Constructed with the same
    `RelationalRepository` the `AuditWriter` uses — read-only queries only,
    never an INSERT/UPDATE/DELETE (the DB grants forbid the latter two
    anyway). A page's chain check and verify's batches run on `hasher`, a
    bounded executor of its own; `close()` shuts it down. `clock` stamps
    `checked_at`. `verify_slot` is verify's single-flight, shared with the scheduled
    verify job."""

    def __init__(
        self,
        repository: AuditRepository,
        hasher: ChainHasher | None = None,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._hasher = hasher if hasher is not None else ChainHasher()
        self._clock = clock
        self.verify_slot = VerifySlot()

    def close(self) -> None:
        self._hasher.shutdown()

    async def query(
        self,
        *,
        restrict_to_actor: str | None,
        actor_user_id: str | None = None,
        actions: list[str] | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        severity: str | None = None,
        outcome: str | None = None,
        from_ts: datetime | None = None,
        to_ts: datetime | None = None,
        q: str | None = None,
        after: AuditCursor | None = None,
        limit: int = AUDIT_QUERY_DEFAULT_LIMIT,
        ip: str | None = None,
        timeout_ms: int | None = None,
        owner: bool = False,
    ) -> AuditPage:
        """`limit` is validated to 1..500 by `AuditQueryRequest`
        (`extra="forbid"`); out-of-range values raise `ValidationError`
        rather than issuing an unbounded query. `subject_type` (the
        `object_kind` column) is passed through to the repository — PR
        #1608 review finding 5: it used to be accepted here and silently
        dropped.

        `restrict_to_actor` has no default: the caller states the scope it
        resolved (`None` only for the Owner's raw view, else the caller's own
        user id), and the repository applies it in the SQL of every page.
        `after` is the decoded cursor; `meta.next_cursor` names the last
        entry returned when more entries follow. `owner` (the principal's
        `is_owner`, SR-017) lets the read use the slot kept for the Owner."""
        req = AuditQueryRequest.model_validate(
            {
                "actor_user_id": actor_user_id,
                "actions": actions,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "ip": ip,
                "severity": severity,
                "outcome": outcome,
                "from_ts": from_ts,
                "to_ts": to_ts,
                "q": q,
                "limit": limit,
            }
        )
        limit = req.limit
        rows = await self._repository.query_page(
            restrict_to_actor=restrict_to_actor,
            actor_user_id=req.actor_user_id,
            actions=req.actions,
            subject_type=req.subject_type,
            subject_id=req.subject_id,
            severity=None if req.severity is None else req.severity.value,
            outcome=None if req.outcome is None else req.outcome.value,
            ip=req.ip,
            q=req.q,
            from_ts=req.from_ts,
            to_ts=req.to_ts,
            after=None if after is None else (after.ts, after.id),
            limit=limit + 1,
            timeout_ms=timeout_ms,
            owner=owner,
        )

        has_more = len(rows) > limit
        rows = rows[:limit]
        # On the full rows, before any projection, and off the event loop. A refusal
        # (`ChainHasherBusy`) or cancellation serves nothing.
        chain_verified = await self._hasher.run(functools.partial(_page_chain_verified, rows))
        items = [
            AuditEntry(
                id=row["id"],
                ts=row["event_ts"],
                actor_user_id=row["actor_user_id"],
                action=row["action"],
                subject_type=row["object_kind"],
                subject_id=row["object_id"],
                outcome=row["outcome"],
                severity=row["severity"],
                ip=str(row["actor_ip"]) if row["actor_ip"] is not None else None,
                request_id=str(row["request_id"]) if row["request_id"] is not None else None,
                entry_hash=row["entry_hash"],
                prev_hash=row["prev_hash"],
            )
            for row in rows
        ]
        last = items[-1] if has_more and items else None
        next_cursor = None if last is None else encode_cursor(AuditCursor(last.ts, last.id))
        return AuditPage(
            items=items,
            chain_verified=chain_verified,
            meta=AuditPageMeta(next_cursor=next_cursor, has_more=has_more, count=len(items)),
        )

    async def plan_verify(
        self, *, from_id: int | None, to_id: int | None, max_span: int = VERIFY_MAX_SPAN
    ) -> VerifyPlan:
        """Range defaulting (#2392/#2446). One bounds read serves the defaults, the
        beyond-head test and the clamp. With neither bound, the newest `max_span` entries;
        with one, the other makes a `max_span` range, clipped to the first entry and the
        head; `to_id` past the head is clamped to it. A `from_id` past the head raises
        `VerifyRangeBeyondHead` (404), unless a checkpoint names an id above the head: then
        the plan carries that tail truncation. The caller checks the span of two given
        bounds (422) first."""
        bounds = await self._repository.read_bounds()
        first, head = bounds if bounds is not None else (None, 0)
        if (from_id is not None and from_id > head) or first is None:
            above = await self._repository.fetch_checkpoint_above(head)
            if from_id is None:  # an empty log
                return VerifyPlan(None, None, head, above)
            if above is None:
                raise VerifyRangeBeyondHead
            return VerifyPlan(from_id, head, head, above)
        hi = head if to_id is None else min(to_id, head)
        if from_id is None:
            return VerifyPlan(max(hi - max_span + 1, min(first, hi), 1), hi, head)
        if to_id is None:
            hi = min(head, from_id + max_span - 1)
        return VerifyPlan(from_id, hi, head)

    async def run_verify(
        self, plan: VerifyPlan, *, batch_size: int = VERIFY_BATCH_SIZE
    ) -> VerifyResult:
        """Check the plan's range. The first entry is checked against the stored
        `entry_hash` of the greatest id below `from_id` (genesis when there is none): ids
        have gaps, so `from_id - 1` may not exist (design §1 gap 10). Keyset batches of
        `batch_size` rows, hashed off the event loop; the walk stops at the first divergence
        (`kind` says which check failed). A database failure, a read over its time budget
        or a full hasher raises and returns nothing; a `batch_size` below 1 is a
        `ValueError`, never an empty "verified" walk."""
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        stored = None
        if plan.from_id is not None:
            stored = await self._repository.fetch_anchor_hash(plan.from_id)
        anchor = stored or _GENESIS_HASH
        walk = _Walk(0, 0, anchor)
        if plan.from_id is not None and plan.to_id is not None:
            walk = await self._check_range(plan.from_id, plan.to_id, plan, anchor, batch_size)
        elif plan.truncated_at is not None:  # an empty log, and checkpoints name entries
            walk = replace(walk, bad_id=plan.truncated_at, kind=ChainBreakKind.TAIL_TRUNCATED)
        return VerifyResult(
            verified=walk.bad_id is None,
            entries_checked=walk.checked,
            first_bad_id=walk.bad_id,
            checked_at=self._clock(),
            from_id=plan.from_id,
            to_id=plan.to_id,
            anchor_hash=anchor,
            last_hash=walk.last_hash if walk.passed else None,
            kind=walk.kind,
            # From genesis (no entry below `from_id`) to the head read at defaulting.
            full_chain=plan.from_id is not None and stored is None and plan.to_id == plan.head_id,
        )

    async def _check_range(
        self, lo: int, hi: int, plan: VerifyPlan, anchor: str, batch_size: int
    ) -> _Walk:
        """The walk and the checkpoint cross-check (#2392), breaks taken in id order: every
        checkpoint with `head_id <= hi` must name an entry whose `entry_hash` is its
        `head_hash` (below the range, the stored hash; in it, after the entry's own
        checks), and a range that ends at the head breaks on a checkpoint above it."""
        checkpoints = await self._repository.fetch_checkpoints(hi)
        missing, mismatch = ChainBreakKind.CHECKPOINT_MISSING, ChainBreakKind.CHECKPOINT_MISMATCH
        for head_id, head_hash, stored in checkpoints:
            if head_id >= lo:
                break
            if stored != head_hash:
                return _Walk(0, 0, anchor, head_id, missing if stored is None else mismatch)
        inside = {h: (hh, e) for h, hh, e in checkpoints if h >= lo}
        gap = min((h for h, (_, e) in inside.items() if e is None), default=None)
        above = plan.truncated_at
        walk = _Walk(0, 0, anchor)
        if above is None:  # `lo <= hi`
            end = hi if gap is None else gap - 1
            known = {h: hh for h, (hh, e) in inside.items() if e is not None}
            if end >= lo:
                walk = await self._walk(anchor, lo - 1, end, batch_size, known)
            if walk.bad_id is not None:
                return walk
            if gap is not None:
                return replace(walk, bad_id=gap, kind=missing)
            # A checkpointed entry deleted during the run, after the last row the walk passed,
            # leaves no next row whose link would break: it was never visited.
            unvisited = [h for h in known if h > walk.last_id]
            if unvisited:
                return replace(walk, bad_id=min(unvisited), kind=missing)
            if hi == plan.head_id:
                above = await self._repository.fetch_checkpoint_above(hi)
        kind = ChainBreakKind.TAIL_TRUNCATED
        return walk if above is None else replace(walk, bad_id=above, kind=kind)

    async def verify(
        self,
        *,
        from_id: int | None = None,
        to_id: int | None = None,
        batch_size: int = VERIFY_BATCH_SIZE,
    ) -> VerifyResult:
        """`plan_verify` then `run_verify`, for callers with no gate between the two."""
        plan = await self.plan_verify(from_id=from_id, to_id=to_id)
        return await self.run_verify(plan, batch_size=batch_size)

    async def _walk(
        self,
        expected: str,
        after_id: int,
        last_id: int,
        batch_size: int,
        checkpoints: Mapping[int, str] = _NO_CHECKPOINTS,
    ) -> _Walk:
        """Keyset batches `after_id < id <= last_id`; batch n+1 is fetched while batch n
        is hashed, and batch n+2 only after batch n is done (at most two held)."""
        checked = passed = passed_id = 0
        pending: asyncio.Future[list[tuple[Any, ...]]] | None
        pending = spawn(self._fetch(after_id, last_id, batch_size), name=_PREFETCH)
        try:
            while pending is not None:
                rows = await pending
                pending = None
                if not rows:
                    break
                if len(rows) == batch_size and rows[-1][0] < last_id:
                    pending = spawn(self._fetch(rows[-1][0], last_id, batch_size), name=_PREFETCH)
                check = functools.partial(_walk_batch, expected, rows, checkpoints)
                walk = await self._hasher.run(check)
                checked, passed = checked + walk.checked, passed + walk.passed
                if walk.bad_id is not None:
                    return _Walk(checked, passed, walk.last_hash, walk.bad_id, walk.kind)
                expected, passed_id = walk.last_hash, walk.last_id
            return _Walk(checked, passed, expected, last_id=passed_id)
        finally:
            if pending is not None:  # a prefetch nobody read: a break, an error, a cancel
                await _discard(pending)

    async def _fetch(self, after_id: int, last_id: int, limit: int) -> list[tuple[Any, ...]]:
        return await self._repository.fetch_verify_batch(
            after_id=after_id, to_id=last_id, limit=limit
        )
