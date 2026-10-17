"""`AdminIncidentsService` (E42-T05): the `GET /admin/incidents` read model.

It reads the materialised `incidents` table (`21-database-schema.md` 3.10.2a), never
`system_events`. A page is `limit` rows, newest `last_seen_at` first with `id` as the tie-break,
behind an opaque keyset cursor bound to its `status` filter and valid for an hour. `title` and
`detail` pass through `redact_text` again on the way out (`24-internal-schemas.md` 15.4) and are
cut to the contract's lengths; a `detail` that cannot be redacted is `None`, a `title` that cannot
is dropped. A page of more than `OFFLOAD_ROWS` rows is redacted off the event loop (C-2.18). No
store wired is `OpsNotWired`; a store that fails or outlasts its budget is `OpsUnavailable`, never
an empty page, which would read as "no incidents".
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

import structlog

from candleviewer.admin.errors import InvalidCursor, OpsNotWired, OpsUnavailable
from candleviewer.admin.overview.fanout import utc_now
from candleviewer.observability.context import current_request_id
from candleviewer.observability.redaction import redact_text
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.incidents import IncidentRow, IncidentStore, Position

#: The contract's `Incident.title` / `detail` `maxLength`, `Cursor` `maxLength` and lifetime.
TITLE_MAX: Final = 200
DETAIL_MAX: Final = 2000
CURSOR_MAX: Final = 512
CURSOR_TTL_S: Final = 3600
READ_BUDGET_S: Final = 2.0
#: `redact_text` costs ~0.13 ms a row at the contract's full lengths (12 us a title, 120 us a
#: detail, measured): 8 ms for 50 rows, 15 ms for the default 100, 70 to 100 ms for 500. Past this
#: many rows the page is redacted in a worker thread (C-2.18): the loop then waits at most about
#: the interpreter's 5 ms switch interval, not the page's time (the regex holds the GIL per call).
OFFLOAD_ROWS: Final = 50


@dataclass(frozen=True, slots=True)
class IncidentPage:
    items: tuple[IncidentRow, ...]
    next_cursor: str | None


def _log() -> structlog.stdlib.BoundLogger:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)  # type: ignore[no-any-return]  # structlog returns Any


def encode_cursor(status: str | None, after: Position, issued: int) -> str:
    raw = {"v": 1, "s": status, "t": after[0].isoformat(), "i": str(after[1]), "iat": issued}
    return base64.urlsafe_b64encode(json.dumps(raw).encode()).decode().rstrip("=")


def decode_cursor(cursor: str, status: str | None, now: int) -> Position:
    """The position of a cursor issued for this `status` less than an hour ago, else
    `InvalidCursor`. Every failure is the same refusal: the cursor is never echoed."""
    try:
        if len(cursor) > CURSOR_MAX:
            raise ValueError("too long")
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        at, rid = datetime.fromisoformat(str(data["t"])), UUID(str(data["i"]))
        iat = data["iat"]
        ok = (data["v"], data["s"]) == (1, status) and at.tzinfo is not None
        ok = ok and type(iat) is int and 0 <= now - iat <= CURSOR_TTL_S
        if ok:
            at = at.astimezone(UTC)  # the instant the driver binds; an offset can overflow it
    except (ValueError, KeyError, TypeError, OverflowError):  # incl. bad base64, JSON, UUID or time
        ok = False
    if not ok:
        raise InvalidCursor("the cursor is malformed, expired or for another listing")
    return at, rid


def _scrub(text: str | None, cap: int) -> str | None:
    """`redact_text`, then the cut (a cut first could split a secret into an unmatched stub)."""
    if text is None:
        return None
    try:
        return redact_text(text)[:cap]
    except Exception as exc:  # the contract: redaction that fails leaves the field out
        _log().error("admin_incidents.redaction_failed", error=type(exc).__name__)
        return None


def _scrubbed(rows: list[IncidentRow]) -> list[IncidentRow]:
    return [
        replace(r, title=_scrub(r.title, TITLE_MAX), detail=_scrub(r.detail, DETAIL_MAX))
        for r in rows
    ]


class AdminIncidentsService:
    def __init__(
        self,
        store: IncidentStore | None,
        *,
        now: Callable[[], datetime] = utc_now,
        budget_s: float = READ_BUDGET_S,
    ) -> None:
        self._store, self._now, self._budget_s = store, now, budget_s

    async def page(self, *, status: str | None, cursor: str | None, limit: int) -> IncidentPage:
        if self._store is None:
            raise OpsNotWired("incidents: no store wired")
        issued = int(self._now().timestamp())
        after = decode_cursor(cursor, status, issued) if cursor else None
        try:
            async with asyncio.timeout(self._budget_s):
                rows = await self._store.page(status=status, after=after, limit=limit + 1)
        except (TimeoutError, StorageTierUnavailable) as exc:  # only the class is logged
            _log().warning(
                "admin_incidents.read_failed",
                error=type(exc).__name__,
                request_id=current_request_id(),
            )
            raise OpsUnavailable("incidents: store unavailable") from None
        kept = rows[:limit]
        big = len(kept) > OFFLOAD_ROWS
        shown = await asyncio.to_thread(_scrubbed, kept) if big else _scrubbed(kept)
        more = len(rows) > limit
        last = shown[-1] if more else None
        nxt = None if last is None else encode_cursor(status, (last.last_seen_at, last.id), issued)
        return IncidentPage(tuple(shown), nxt)
