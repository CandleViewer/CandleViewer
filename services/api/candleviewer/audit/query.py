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
import json
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
#: The recorded states, as (`detail` key, `audit_log` column).
_STATES = (("before", "before_state"), ("after", "after_state"))
#: Deepest container nesting of a state the Owner's page returns. The response serializer
#: refuses about 255 levels, so a deeper state is withheld instead of failing the page.
STATE_MAX_DEPTH = 128
#: Longest number literal a state the Owner's page returns may hold, in characters (digits,
#: sign, `.`, `e`/`E`). Converting a number costs more the longer its literal, so a state
#: holding a longer one is withheld, whatever the page's structure budget.
NUMBER_MAX_CHARS = 64
#: The structure one Owner page serves of its states (`audit_page_structure_budget`), in
#: tokens: each `{`, `[` and `,` of their renderings. The page is serialized on the event
#: loop at a cost per value, and this bounds the number of values (C-2.17).
DEFAULT_PAGE_STRUCTURE_BUDGET = 50_000


class _StructureBudget:
    """What is left of a page's structure budget, spent in page order. A state costs the
    `{`, `[` and `,` of its rendering: each member or item of it follows one of them, so
    the cost bounds the number of values the response serializes for it, whatever their
    shape. From the first state that does not fit, none does, so the states served never
    cost more than the budget and the ones withheld are the rest of the page."""

    __slots__ = ("_left",)

    def __init__(self, tokens: int) -> None:
        self._left = tokens

    def spend(self, tokens: int) -> bool:
        """Whether a state costing `tokens` is served; once one is not, no later one is."""
        if tokens > self._left:
            self._left = -1
            return False
        self._left -= tokens
        return True


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


def _nesting_within(value: dict[str, Any], limit: int) -> bool:
    """Whether `value` nests at most `limit` containers deep, walked without recursion."""
    stack: list[tuple[dict[str, Any] | list[Any], int]] = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > limit:
            return False
        children = node.values() if isinstance(node, dict) else node
        stack.extend((child, depth + 1) for child in children if isinstance(child, dict | list))
    return True


class _NumberOverCap(ValueError):
    """A number literal longer than `NUMBER_MAX_CHARS` characters, refused unconverted."""


def _capped_int(literal: str) -> int:
    """`parse_int` of a state's parse: the scanner hands over each integer literal's text
    before converting it, so one over `NUMBER_MAX_CHARS` is never converted."""
    if len(literal) > NUMBER_MAX_CHARS:
        raise _NumberOverCap
    return int(literal)


def _capped_float(literal: str) -> float:
    """`parse_float` of a state's parse, as `_capped_int`."""
    if len(literal) > NUMBER_MAX_CHARS:
        raise _NumberOverCap
    return float(literal)


def _parse_state(rendering: str, budget: _StructureBudget) -> dict[str, Any] | None:
    """A state's rendering as an object, or `None` when it cannot be returned: the page's
    structure budget has no room left for it, it holds a number literal over
    `NUMBER_MAX_CHARS` characters, it does not parse (defensive: a jsonb rendering always
    does), it is not an object, or it nests deeper than `STATE_MAX_DEPTH`. Never raises
    for the rendering, never yields its text. The number cap is checked by the parse
    itself, which hands each literal's text to `_capped_int` / `_capped_float` before
    converting it: no pass of its own, and a run of digits inside a string is no literal."""
    # Counted once, before any parse, for both bounds: brackets and commas are the state's
    # cost, and as a container opens with one bracket, the brackets alone bound its depth.
    brackets = rendering.count("{") + rendering.count("[")
    if not budget.spend(brackets + rendering.count(",")):
        return None
    try:
        value = json.loads(rendering, parse_int=_capped_int, parse_float=_capped_float)
    except (ValueError, RecursionError):  # `_NumberOverCap` is a `ValueError`
        return None
    if not isinstance(value, dict):
        return None
    # Only a state with more brackets than the limit is walked.
    if brackets > STATE_MAX_DEPTH and not _nesting_within(value, STATE_MAX_DEPTH):
        return None
    return value


def _owner_detail(row: dict[str, Any], budget: _StructureBudget) -> dict[str, Any]:
    """The Owner's `detail`, built from the page's capped chain renderings (`row["chain"]`),
    as the page select fetches no state. With the form fetched in full, a null rendering is
    a null state and any other is parsed, so a state shown is the one the chain check hashed.
    Without it (over the render caps), only whether each state is null is known, and a
    non-null one is withheld; so is a state past the page's structure `budget` or holding
    a number literal over `NUMBER_MAX_CHARS` characters. A withheld state is null and
    listed in `elided`; a stored null never is, and `elided` is absent when nothing was
    withheld."""
    chain = row["chain"]
    detail: dict[str, Any] = {}
    elided: list[str] = []
    for key, column in _STATES:
        if chain is None:
            value, withheld = None, not row[f"{column}_is_null"]
        elif chain[column] in (None, "null"):  # SQL NULL, or a jsonb `null`
            value, withheld = None, False
        else:
            value = _parse_state(chain[column], budget)
            withheld = value is None
        detail[key] = value
        if withheld:
            elided.append(key)
    if elided:
        detail["elided"] = elided
    return detail


def _check_page(
    rows: list[dict[str, Any]], raw: bool, structure_budget: int
) -> tuple[bool, list[dict[str, Any] | None]]:
    """The hasher-thread part of a page read: the chain check and, for the Owner's raw view
    only, each row's `detail`, since parsing the renderings is CPU work too, as is spending
    the page's `structure_budget` on them in page order. Any other view builds no detail
    (`None` per row)."""
    verified = _page_chain_verified(rows)
    budget = _StructureBudget(structure_budget)
    return verified, [_owner_detail(row, budget) if raw else None for row in rows]


def _entry(row: dict[str, Any], detail: dict[str, Any] | None) -> AuditEntry:
    """An entry from a page row. `detail` is `None` for any view but the Owner's raw one,
    whose select fetched no Owner-only column: none is read, and they stay null."""
    owner_only: dict[str, Any] = {"ip": None}
    if detail is not None:
        owner_only = {
            "subject_label": row["object_label"],
            "reason": row["reason"],
            "environment": row["env"],
            "session_id": row["session_id"],
            "ip": None if row["actor_ip"] is None else str(row["actor_ip"]),
            "detail": detail,
        }
    return AuditEntry(
        id=row["id"],
        ts=row["event_ts"],
        actor_user_id=row["actor_user_id"],
        actor_username=row["actor_label"],
        action=row["action"],
        subject_type=row["object_kind"],
        subject_id=row["object_id"],
        outcome=row["outcome"],
        severity=row["severity"],
        request_id=None if row["request_id"] is None else str(row["request_id"]),
        entry_hash=row["entry_hash"],
        prev_hash=row["prev_hash"],
        **owner_only,
    )


class AuditQueryService:
    """Backs the three `/admin/audit*` endpoints. Constructed with the same
    `RelationalRepository` the `AuditWriter` uses — read-only queries only,
    never an INSERT/UPDATE/DELETE (the DB grants forbid the latter two
    anyway). A page's chain check runs on `hasher`, a bounded executor of its
    own; `close()` shuts it down. The Owner's page serves at most
    `structure_budget` of its states' structure (`_StructureBudget`)."""

    def __init__(
        self,
        repository: AuditRepository,
        hasher: ChainHasher | None = None,
        *,
        structure_budget: int = DEFAULT_PAGE_STRUCTURE_BUDGET,
    ) -> None:
        self._repository = repository
        self._hasher = hasher if hasher is not None else ChainHasher()
        self._structure_budget = structure_budget

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
        raw: bool = False,
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
        `is_owner`, SR-017) lets the read use the slot kept for the Owner.
        `raw` is the Owner's raw view (`AuditView.RAW`), stated by the caller
        and never inferred from the scope or `owner`. Only a raw read fetches
        the Owner-only columns and builds `detail`; it defaults to `False`, so
        a caller that omits it gets less, never more."""
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
            raw=raw,
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
        # On the full rows, before any projection, and off the event loop, as are parsing the
        # Owner's states and spending the page's structure budget on them. A refusal
        # (`ChainHasherBusy`) or cancellation serves nothing.
        check = functools.partial(_check_page, rows, raw, self._structure_budget)
        chain_verified, details = await self._hasher.run(check)
        items = [_entry(row, detail) for row, detail in zip(rows, details, strict=True)]
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
