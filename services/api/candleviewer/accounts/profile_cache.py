"""The order path's profile reads: an in-process cache of effective profiles (E28-T01 #905).

`get_effective_profile(account_id, profile_id)` answers the profile the sizer (E28-T03), the
guard (E28-T04) and the fan-out (E34) use: the given profile, or the account's default when
`profile_id` is `None` (24-internal-schemas.md Sec.9.3). It is a system read with no principal,
so no route reaches it. A read is served from the cache while the entry is younger than
`TTL_S`; a miss loads through the store's `EffectiveProfileReads`, one load per key at a time
(single-flight, shared under `asyncio.shield`, so a cancelled reader leaves it to the others),
bounded by `LOAD_TIMEOUT_S`.

`invalidate(account_id)` drops the account's entries and bumps the account's generation, so a
load of that account that started before it is never installed (SR-E28-15: a narrowing write
invalidates before it returns, and no older version is served after that). `ProfilesRepository`
calls it after every write. A read overtaken that way retries once, then fails closed with
`ProfileUnavailableError`, as it does when the store fails or times out or a stored row is
unreadable (SR-E28-24: the guard never falls back to a default); each such refusal is logged at
WARN with its reason, never with a value. `peek()` is the synchronous, cache-only form for a
check that must not touch the database.

The cache holds at most `MAX_ENTRIES` profiles and drops the oldest past that. It is for one
event loop; reads take no lock. Every load is a tracked task, and `aclose()` cancels those still
running (the composition root calls it before disposing of the engine).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

import structlog

from candleviewer.accounts.errors import AccountNotFoundError, ProfileUnavailableError
from candleviewer.accounts.profiles import AccountProfile, profile_from_row
from candleviewer.observability import spawn
from candleviewer.storage.errors import StorageError
from candleviewer.storage.repositories.account_profiles import EffectiveProfileReads

if TYPE_CHECKING:
    from candleviewer.observability.metrics import BoundedMetric

#: An entry older than this is read again: a change made outside this process shows within it.
TTL_S: Final = 30.0
#: One store read of a profile; the order path fails closed past it.
LOAD_TIMEOUT_S: Final = 2.0
#: Profiles held at once; a deployment has a few per account.
MAX_ENTRIES: Final = 1024

_Key = tuple[UUID, UUID | None]
_Load = asyncio.Task[AccountProfile | None]


def _log() -> Any:
    """Resolve per call: a module-level logger pins a stale processor chain (#2008)."""
    return structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class _Entry:
    profile: AccountProfile
    loaded_at: float


def _answers(profile: AccountProfile, account_id: UUID, profile_id: UUID | None) -> bool:
    """Whether `profile` answers this read: the account's own, and the asked-for profile or, for
    the default, a default (re-checked here as `peek` does, whatever the store returned)."""
    if profile.account_id != account_id:
        return False
    return profile.is_default if profile_id is None else profile.profile_id == profile_id


class EffectiveProfiles:
    """Cached effective-profile reads over `EffectiveProfileReads`."""

    def __init__(
        self,
        reads: EffectiveProfileReads,
        *,
        clock: Callable[[], float] = time.monotonic,
        ttl_s: float = TTL_S,
        load_timeout_s: float = LOAD_TIMEOUT_S,
        max_entries: int = MAX_ENTRIES,
        lookups: BoundedMetric | None = None,
    ) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._reads, self._clock = reads, clock
        self._ttl, self._timeout, self._max = ttl_s, load_timeout_s, max_entries
        self._entries: dict[UUID, _Entry] = {}
        self._defaults: dict[UUID, UUID] = {}
        #: Per account, bumped by `invalidate`: a write overtakes only its own account's loads.
        self._generations: dict[UUID, int] = {}
        #: One load per key and generation: a reader never joins a load an invalidate overtook.
        self._inflight: dict[_Key, tuple[int, _Load]] = {}
        #: Every load still running, superseded or not, for `aclose`.
        self._tasks: set[_Load] = set()
        self._hit = None if lookups is None else lookups.labels("hit")
        self._miss = None if lookups is None else lookups.labels("miss")

    def peek(self, account_id: UUID, profile_id: UUID | None = None) -> AccountProfile | None:
        """The cached, fresh profile, or `None` (the caller fails closed); never awaits."""
        pid = self._defaults.get(account_id) if profile_id is None else profile_id
        if pid is None:
            return None
        entry = self._entries.get(pid)
        if entry is None or not _answers(entry.profile, account_id, profile_id):
            return None  # another account's profile, or a default that moved, reads as a miss
        if self._clock() - entry.loaded_at >= self._ttl:
            return None
        return entry.profile

    async def get_effective_profile(
        self, account_id: UUID, profile_id: UUID | None = None
    ) -> AccountProfile:
        """The profile, or the account's default; `AccountNotFoundError` when there is none
        (a missing, deleted or other account's profile alike), `ProfileUnavailableError` when the
        store cannot answer."""
        for _ in range(2):
            hit = self.peek(account_id, profile_id)
            if hit is not None:
                if self._hit is not None:
                    self._hit.inc()
                return hit
            if self._miss is not None:
                self._miss.inc()
            generation = self._generations.get(account_id, 0)
            loaded = await self._load((account_id, profile_id))
            if generation == self._generations.get(account_id, 0):
                if loaded is None or not _answers(loaded, account_id, profile_id):
                    raise AccountNotFoundError("profile")
                return loaded
        _log().warning("profile.read_failed_closed", reason="overtaken", account_id=str(account_id))
        raise ProfileUnavailableError("profile reads kept being overtaken by writes")

    def invalidate(self, account_id: UUID) -> None:
        """Drop the account's profiles; a load of the account already running is not installed."""
        self._generations[account_id] = self._generations.get(account_id, 0) + 1
        self._defaults.pop(account_id, None)
        for pid in [p for p, e in self._entries.items() if e.profile.account_id == account_id]:
            del self._entries[pid]

    async def aclose(self) -> None:
        """Cancel every load still running and wait for them to end."""
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _load(self, key: _Key) -> AccountProfile | None:
        generation = self._generations.get(key[0], 0)
        running = self._inflight.get(key)
        if running is not None and running[0] == generation and not running[1].done():
            task = running[1]
        else:
            task = spawn(self._fetch(key, generation), name="profile-load")
            self._inflight[key] = (generation, task)
            self._tasks.add(task)
            task.add_done_callback(self._settled)
        try:
            async with asyncio.timeout(self._timeout):
                return await asyncio.shield(task)
        except TimeoutError:
            _log().warning("profile.read_failed_closed", reason="timeout", account_id=str(key[0]))
            raise ProfileUnavailableError("profile read timed out") from None
        except StorageError as exc:
            _log().warning(
                "profile.read_failed_closed",
                reason="store_unavailable",
                account_id=str(key[0]),
                error=type(exc).__name__,
                sqlstate=getattr(exc, "sqlstate", None),
            )
            raise ProfileUnavailableError("profile store unavailable") from None

    def _settled(self, task: _Load) -> None:
        self._tasks.discard(task)
        if not task.cancelled():
            task.exception()  # retrieved: its readers, if any are left, have their answer

    async def _fetch(self, key: _Key, generation: int) -> AccountProfile | None:
        account_id, profile_id = key
        try:
            try:
                row = await self._reads.effective_profile(account_id, profile_id)
                profile = None if row is None else profile_from_row(row)
            except StorageError:
                raise  # `_load` maps it: the store could not answer
            except (ValueError, TypeError, KeyError, ArithmeticError):
                # A stored row the store's decoder or the model refuses (pydantic's
                # ValidationError is a ValueError): fail closed like any other unreadable
                # profile, with none of its values in the error or the log (SR-E28-24).
                _log().warning(
                    "profile.read_failed_closed", reason="invalid_row", account_id=str(account_id)
                )
                raise ProfileUnavailableError("stored profile unreadable") from None
            if profile is not None and generation == self._generations.get(account_id, 0):
                self._install(profile)
            return profile
        finally:
            running = self._inflight.get(key)
            if running is not None and running[1] is asyncio.current_task():
                del self._inflight[key]

    def _install(self, profile: AccountProfile) -> None:
        self._entries.pop(profile.profile_id, None)
        while len(self._entries) >= self._max:
            oldest = next(iter(self._entries))
            evicted = self._entries.pop(oldest).profile
            if self._defaults.get(evicted.account_id) == oldest:
                del self._defaults[evicted.account_id]
        self._entries[profile.profile_id] = _Entry(profile, self._clock())
        if profile.is_default:
            self._defaults[profile.account_id] = profile.profile_id
        elif self._defaults.get(profile.account_id) == profile.profile_id:
            del self._defaults[profile.account_id]  # read again after the default moved away
