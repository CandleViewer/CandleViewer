"""Per-user audit-record budget for `/admin/audit*` (contract #2392, "Audit budget").

The component handles the read and refusal records for `/admin/audit*`, so that reads and
refusals cannot crowd the audit log, which also carries order intents.

* Capped records (`per_hour`, or `owner_per_hour` for the Owner, over a sliding hour per
  user): `admin.audit_read` for the first read of a filter set or a due continuation, and
  `admin.audit_denied` for a refusal. A slot is reserved before the write and held while it
  is in flight, so no hour exceeds the cap, whatever the interleaving.
* Counts are never dropped. A `429`, and a refusal over the cap, are counted (`suppressed`);
  served continuation pages are counted per filter set (by digest, `FILTER_SETS_PER_USER`
  per user, older sets fold into `other_pages`). A record takes the counts it carries, each
  digest with its page count in `after_state`; a failed write gives them back.

A due record that cannot be written raises `BudgetWriteFailed` (answer 503, serve nothing):
in-flight cap full, writer error or `write_timeout_s` overrun, or an untracked user. A write
is a tracked task that is never cancelled (`AuditWriter.emit` must not stop mid-append); it
holds its slot until done and settles its own counts. A caller that gives up after the writer
accepted a read record errs toward recording more: that page is recorded, not served.

State is bounded (C-2.18): `tracked_users` users and `inflight_cap` writes in flight, as for
`auth.csrf_refused` (`api/csrf.py`). The least recently used user is evicted only once its
state no longer matters (no record in the last hour, no counts, nothing in flight), so a
fresh entry counts as the old one would; until then a new user writes nothing.
"""

from __future__ import annotations

import asyncio
import bisect
import hashlib
import json
import math
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog

from candleviewer.observability.context import spawn

READ_ACTION = "admin.audit_read"
DENIAL_ACTION = "admin.audit_denied"
FILTER_SETS_PER_USER = 16
#: As `api/csrf.py` `AUDIT_TIMEOUT_S`: how long a caller waits for one audit write.
WRITE_TIMEOUT_S = 2.0
_HOUR_S = 3600.0


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


class _Raw(Protocol):
    # A read-only callable property, so writers with named keyword-only parameters satisfy it.
    @property
    def emit(self) -> Callable[..., Awaitable[None]]: ...


class BudgetWriteFailed(Exception):
    """A due record could not be written: answer 503 `store_unavailable`, serve nothing."""


def filters_digest(filters: dict[str, Any]) -> str:
    """Digest of a canonical filter set: the key its continuation pages are counted under."""
    return hashlib.sha256(json.dumps(filters, sort_keys=True, default=str).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class BudgetActor:
    """Who a record is for. `key` identifies the user across sessions."""

    key: str
    label: str
    user_id: Any
    owner: bool


@dataclass(slots=True)
class _User:
    actor: BudgetActor
    stamps: list[float] = field(default_factory=list)  # capped records, by write time
    reserved: int = 0  # capped slots whose write has not finished
    reading: int = 0  # pages planned but not yet served, recorded or given up
    writing: int = 0
    suppressed: int = 0
    pages: OrderedDict[str, int] = field(default_factory=OrderedDict)  # digest -> pending
    other_pages: int = 0
    last_read_record: float = -math.inf

    def pending_pages(self) -> int:
        return sum(self.pages.values()) + self.other_pages


@dataclass(slots=True)
class _Take:
    """Counts a record carries, taken from the user; given back if the write fails."""

    suppressed: int = 0
    pages: dict[str, int] = field(default_factory=dict)
    other_pages: int = 0

    def detail(self, current: str | None = None) -> dict[str, Any]:
        pages = dict(self.pages)
        if current is not None:  # the page this read record serves
            pages[current] = pages.get(current, 0) + 1
        out: dict[str, Any] = {}
        if pages:
            out["pages"] = [{"filters_sha256": d, "pages": n} for d, n in sorted(pages.items())]
        if self.other_pages:
            out["other_pages"] = self.other_pages
        if self.suppressed:
            out["suppressed"] = self.suppressed
        return out


@dataclass(slots=True)
class _Write:
    action: str
    user: _User
    take: _Take
    page: str | None = None  # digest of the page a read record serves
    at: float = 0.0


@dataclass(slots=True)
class ReadReservation:
    """One read's plan. `action` is `count` (a continuation page, no record), `record` (a
    capped record is due: call `write_read`), `refuse` (over the cap: 429, counted) or
    `unwritable` (503). `commit()` once served; `release()` (idempotent, in a `finally`)
    gives back whatever is still reserved."""

    action: str
    digest: str
    _user: _User | None = None
    _open: bool = False

    def commit(self) -> None:
        st = self._user
        if not (self._open and st is not None and self.action == "count"):
            self.release()  # a `record` page is served only through `write_read`
            return
        st.reading -= 1
        if self.digest in st.pages:
            st.pages[self.digest] += 1
        else:  # the filter set left the per-user window meanwhile
            st.other_pages += 1
        self._open = False

    def release(self) -> None:
        if self._open and self._user is not None:
            self._user.reading -= 1
            if self.action == "record":
                self._user.reserved -= 1
        self._open = False


class AuditRecordBudget:
    def __init__(
        self,
        *,
        per_hour: int = 120,
        owner_per_hour: int = 600,
        tracked_users: int = 1024,
        inflight_cap: int = 64,
        flush_pages: int = 50,
        flush_seconds: float = 300.0,
        write_timeout_s: float = WRITE_TIMEOUT_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._per_hour, self._owner_per_hour = per_hour, owner_per_hour
        self._tracked, self._inflight_cap = tracked_users, inflight_cap
        self._flush_pages, self._flush_s = flush_pages, flush_seconds
        self._write_timeout_s, self._clock = write_timeout_s, clock
        self._users: OrderedDict[str, _User] = OrderedDict()
        self._tasks: set[asyncio.Task[bool]] = set()
        self._inflight = 0
        self._untracked = 0  # suppressed counts of users that could not be tracked

    def __len__(self) -> int:
        return len(self._users)

    @property
    def inflight(self) -> int:
        return self._inflight

    def emitter(self, raw: _Raw, actor: BudgetActor) -> BudgetedEmitter:
        return BudgetedEmitter(self, raw, actor)

    def retry_after(self, key: str) -> int:
        """Seconds until the user's oldest capped record leaves its hour (at least 1)."""
        st = self._users.get(key)
        if st is None or not st.stamps:
            return 1
        return max(1, math.ceil(st.stamps[0] + _HOUR_S - self._clock()))

    # -- state --------------------------------------------------------------------------
    def _track(self, actor: BudgetActor) -> _User | None:
        st = self._users.get(actor.key)
        if st is not None:
            self._users.move_to_end(actor.key)
        elif len(self._users) < self._tracked or self._evict_one():
            st = self._users[actor.key] = _User(actor)
        else:
            return None
        st.actor = actor
        return st

    def _evict_one(self) -> bool:
        """Drop the least recently used user whose state no longer matters: a fresh entry
        for it then counts exactly as the old one would, so eviction never lifts the bound."""
        now = self._clock()
        for key, st in self._users.items():
            _prune(st, now)
            busy = st.stamps or st.reserved or st.reading or st.writing
            if not (busy or st.suppressed or st.pending_pages()):
                del self._users[key]
                return True
        return False

    def _admit(self, st: _User) -> bool:
        """Reserve one capped slot unless the user's hour is full."""
        _prune(st, self._clock())
        cap = self._owner_per_hour if st.actor.owner else self._per_hour
        if len(st.stamps) + st.reserved >= cap:
            return False
        st.reserved += 1
        return True

    @staticmethod
    def _take(st: _User, *, pages: bool) -> _Take:
        take = _Take(suppressed=st.suppressed)
        st.suppressed = 0
        if pages:
            take.pages = {d: n for d, n in st.pages.items() if n}
            for d in take.pages:
                st.pages[d] = 0
            take.other_pages, st.other_pages = st.other_pages, 0
        return take

    # -- counting and planning -----------------------------------------------------------
    def count_suppressed(self, actor: BudgetActor) -> None:
        """A `429`: no record; counted and carried by a later one."""
        st = self._track(actor)
        if st is None:
            self._untracked += 1
        else:
            st.suppressed += 1

    def plan_read(self, actor: BudgetActor, digest: str) -> ReadReservation:
        st = self._track(actor)
        if st is not None and digest in st.pages:
            due = (
                st.pending_pages() + 1 >= self._flush_pages
                or self._clock() - st.last_read_record >= self._flush_s
            )
            if not due:
                st.pages.move_to_end(digest)
                st.reading += 1
                return ReadReservation("count", digest, st, True)
        if st is None or self._inflight >= self._inflight_cap:
            return ReadReservation("unwritable", digest)
        if not self._admit(st):
            st.suppressed += 1
            return ReadReservation("refuse", digest)
        st.reading += 1
        return ReadReservation("record", digest, st, True)

    # -- writing -------------------------------------------------------------------------
    async def write_read(
        self, res: ReadReservation, raw: _Raw, fields: dict[str, Any], detail: dict[str, Any]
    ) -> None:
        """Write the `admin.audit_read` a `record` plan reserved, carrying its page and every
        count outstanding for the user. `BudgetWriteFailed`: answer 503, serve nothing."""
        st = res._user
        if res.action != "record" or not res._open or st is None:
            raise ValueError("write_read needs an open `record` reservation")
        res._open = False  # the write settles the slot and the page from here on
        take = self._take(st, pages=True)
        after = {**detail, "filters_sha256": res.digest, **take.detail(current=res.digest)}
        w = _Write(READ_ACTION, st, take, page=res.digest)
        await self._write(raw, {**fields, "after_state": after}, w)

    async def write_denial(self, actor: BudgetActor, raw: _Raw, fields: dict[str, Any]) -> bool:
        """A capped `admin.audit_denied` refusal record. True: written. False: over the cap,
        counted (return the refusal unchanged, with `Retry-After`). `BudgetWriteFailed`:
        due but unwritable (answer 503)."""
        st = self._track(actor)
        if st is None:
            raise BudgetWriteFailed("user not tracked")
        if not self._admit(st):
            st.suppressed += 1
            return False
        take = self._take(st, pages=False)
        after = {**(fields.get("after_state") or {}), **take.detail()}
        w = _Write(DENIAL_ACTION, st, take)
        await self._write(raw, {**fields, "after_state": after or None}, w)
        return True

    async def _write(self, raw: _Raw, fields: dict[str, Any], w: _Write) -> None:
        if self._inflight >= self._inflight_cap:
            self._settle(w, ok=False)
            raise BudgetWriteFailed("in-flight audit cap")
        w.at = self._clock()
        self._inflight += 1
        w.user.writing += 1
        task = spawn(self._run(raw, fields, w), name="audit-budget-write")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        done, _ = await asyncio.wait({task}, timeout=self._write_timeout_s)
        if task not in done:
            _log().warning("audit.budget.write_slow", action=w.action)
            raise BudgetWriteFailed("audit write timed out")
        if task.cancelled() or not task.result():
            raise BudgetWriteFailed("audit write failed")

    async def _run(self, raw: _Raw, fields: dict[str, Any], w: _Write) -> bool:
        """The write itself, never cancelled by its caller; settles its own counts."""
        ok = False
        try:
            await raw.emit(w.action, **fields)
            ok = True
        except Exception as exc:
            _log().warning("audit.budget.write_failed", action=w.action, error=type(exc).__name__)
        finally:
            self._inflight -= 1
            w.user.writing -= 1
            self._settle(w, ok)
        return ok

    def _settle(self, w: _Write, ok: bool) -> None:
        st = w.user
        st.reserved -= 1
        if ok:
            bisect.insort(st.stamps, w.at)
        if w.page is not None:
            st.reading -= 1
            if ok:
                st.pages[w.page] = st.pages.get(w.page, 0)
                st.pages.move_to_end(w.page)
                while len(st.pages) > FILTER_SETS_PER_USER:
                    st.other_pages += st.pages.popitem(last=False)[1]
        if not ok:  # give the counts back
            st.suppressed += w.take.suppressed
            st.other_pages += w.take.other_pages
            for d, n in w.take.pages.items():
                if d in st.pages:
                    st.pages[d] += n
                else:
                    st.other_pages += n
        elif w.action == READ_ACTION:
            st.last_read_record = w.at


def _prune(st: _User, now: float) -> None:
    del st.stamps[: bisect.bisect_right(st.stamps, now - _HOUR_S)]


class BudgetedEmitter:
    """The writer `authorize()` sees on `/admin/audit*`: `admin.audit_denied` goes through
    the budget; any other action goes straight to the writer and is never budgeted."""

    def __init__(self, budget: AuditRecordBudget, raw: _Raw, actor: BudgetActor) -> None:
        self._budget, self._raw, self._actor = budget, raw, actor
        #: The last refusal was over the cap: counted, not written (add `Retry-After`).
        self.suppressed = False

    async def emit(self, action: str, **kwargs: Any) -> None:
        if action != DENIAL_ACTION:
            await self._raw.emit(action, **kwargs)
            return
        self.suppressed = not await self._budget.write_denial(self._actor, self._raw, kwargs)
