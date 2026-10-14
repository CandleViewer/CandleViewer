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

import functools
import hashlib
from datetime import UTC, datetime
from typing import Any

from candleviewer.audit.cursor import AuditCursor, encode_cursor
from candleviewer.audit.hashing import ChainHasher
from candleviewer.audit.models import (
    AUDIT_QUERY_DEFAULT_LIMIT,
    AuditEntry,
    AuditPage,
    AuditPageMeta,
    AuditQueryRequest,
    VerifyResult,
)
from candleviewer.audit.repository import AuditRepository

_GENESIS_HASH = "0" * 64


def _canonical_field(value: object) -> str:
    """Mirror of the SQL `audit_field()`: NULL -> `-`, else `<len>:<value>`
    (length in characters, as Postgres `length(text)`). Prefix-free, so the
    concatenation of fields is unambiguous (PR #1561 finding 8)."""
    if value is None:
        return "-"
    text = str(value)
    return f"{len(text)}:{text}"


def _canonical_hash(prev_hash: str, row: dict[str, Any]) -> str:
    """Recompute `audit_chain()`'s digest.

    `row` carries every hashed column already rendered to text by Postgres
    with the trigger's own casts (see `AuditRepository.fetch_verify_batch`),
    so this is a pure concatenation of `_canonical_field` encodings — the
    same length-prefixed form as the trigger's `audit_field()`.
    """
    parts = (
        prev_hash,
        row["actor_user_id"],
        row["actor_label"],
        row["actor_ip"],
        row["session_id"],
        row["action"],
        row["object_kind"],
        row["object_id"],
        row["outcome"],
        row["severity"],
        row["reason"],
        row["before_state"],
        row["after_state"],
        row["request_id"],
        row["env"],
        row["event_ts"],
    )
    payload = "".join(_canonical_field(part) for part in parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _page_chain_verified(rows: list[dict[str, Any]]) -> bool:
    """Design §5 on a page: every row's hashed fields recompute to its `entry_hash`, and its
    `prev_hash` is the `entry_hash` of the row before it in the chain (genesis for the
    first), whether or not that row is on the page. A row whose canonical form was not
    fetched in full (`chain` is `None`, over the render caps) is unverified, never
    verified. This proves the returned rows, not the rest of the chain (`verify` does).

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
    anyway). A page's chain check runs on `hasher`, a bounded executor of its
    own; `close()` shuts it down."""

    def __init__(self, repository: AuditRepository, hasher: ChainHasher | None = None) -> None:
        self._repository = repository
        self._hasher = hasher if hasher is not None else ChainHasher()

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

    async def verify(
        self,
        *,
        from_id: int | None = None,
        to_id: int | None = None,
        batch_size: int = 5_000,
    ) -> VerifyResult:
        checked = 0
        expected_prev = _GENESIS_HASH
        first_bad_id: int | None = None
        cursor = from_id - 1 if from_id else 0

        if from_id and from_id > 1:
            prev_hash = await self._repository.fetch_entry_hash(from_id - 1)
            if prev_hash is not None:
                expected_prev = prev_hash

        while first_bad_id is None:
            rows = await self._repository.fetch_verify_batch(
                after_id=cursor, to_id=to_id, limit=batch_size
            )
            if not rows:
                break
            for row in rows:
                checked += 1
                if row["prev_hash"] != expected_prev:
                    first_bad_id = row["id"]
                    break
                recomputed = _canonical_hash(expected_prev, row)
                if recomputed != row["entry_hash"]:
                    first_bad_id = row["id"]
                    break
                expected_prev = row["entry_hash"]
                cursor = row["id"]
            if len(rows) < batch_size:
                break

        return VerifyResult(
            verified=first_bad_id is None,
            entries_checked=checked,
            first_bad_id=first_bad_id,
            checked_at=datetime.now(UTC),
        )
