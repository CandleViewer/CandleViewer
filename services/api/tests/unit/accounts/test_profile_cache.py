"""`EffectiveProfiles` (E28-T01 #905): the order path's cached profile reads — hits, TTL, the
single-flight load, the generation guard of SR-E28-15 and fail-closed errors (SR-E28-24)."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import structlog

from candleviewer.accounts.errors import AccountNotFoundError, ProfileUnavailableError
from candleviewer.accounts.profile_cache import EffectiveProfiles
from candleviewer.accounts.profiles import AccountProfile, profile_values
from candleviewer.storage.errors import (
    StorageQueryFailed,
    StorageRecordInvalid,
    StorageTierUnavailable,
)
from candleviewer.storage.repositories.account_profiles import AccountProfileRow

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "profiles"
_T = datetime(2026, 10, 20, 9, tzinfo=UTC)


def _profile(**changes: Any) -> AccountProfile:
    data = json.loads((_FIXTURES / "risk_based.json").read_text(encoding="utf-8"))
    return AccountProfile.model_validate({**data, **changes})


_P = _profile()  # the account's default
_ACCOUNT = _P.account_id


def _row(profile: AccountProfile = _P, *, version: int = 3) -> AccountProfileRow:
    return AccountProfileRow(
        id=profile.profile_id, exchange_account_id=profile.account_id, version=version,
        values=profile_values(profile), created_by=None, updated_by=None, created_at=_T,
        updated_at=_T, deleted_at=None,
    )  # fmt: skip


class _Reads:
    """`EffectiveProfileReads` answering the n-th call with the n-th scripted answer; when gated,
    call n waits for `gates[n]` and signals `entered[n]` first."""

    def __init__(self, *answers: object, gated: bool = False) -> None:
        self.answers = list(answers)
        self.calls: list[tuple[UUID, UUID | None]] = []
        self.cancelled: list[int] = []
        self.entered = [asyncio.Event() for _ in answers]
        self.gates = [asyncio.Event() for _ in answers]
        if not gated:
            for gate in self.gates:
                gate.set()

    async def effective_profile(
        self, account_id: UUID, profile_id: UUID | None
    ) -> AccountProfileRow | None:
        n = len(self.calls)
        self.calls.append((account_id, profile_id))
        self.entered[n].set()
        try:
            await self.gates[n].wait()
        except asyncio.CancelledError:
            self.cancelled.append(n)
            raise
        answer = self.answers[n]
        if isinstance(answer, BaseException):
            raise answer
        assert answer is None or isinstance(answer, AccountProfileRow)
        return answer


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class _Lookups:
    def __init__(self) -> None:
        self.counts: dict[str, float] = {"hit": 0, "miss": 0}

    def labels(self, result: str) -> Any:
        counts = self.counts

        class _Child:
            def inc(self, amount: float = 1) -> None:
                counts[result] += amount

        return _Child()


async def _entered(reads: _Reads, n: int) -> None:
    """Call `n` has reached the store; a regression fails here instead of hanging."""
    async with asyncio.timeout(1):
        await reads.entered[n].wait()


def _cache(reads: _Reads, **kwargs: Any) -> tuple[EffectiveProfiles, _Clock]:
    clock = _Clock()
    return EffectiveProfiles(reads, clock=clock, **kwargs), clock


async def test_the_default_is_loaded_once_then_served_from_the_cache() -> None:
    reads = _Reads(_row())
    lookups = _Lookups()
    cache, _ = _cache(reads, lookups=lookups)
    assert (await cache.get_effective_profile(_ACCOUNT)).version == 3
    assert (await cache.get_effective_profile(_ACCOUNT)).profile_id == _P.profile_id
    assert (await cache.get_effective_profile(_ACCOUNT, _P.profile_id)).version == 3
    assert reads.calls == [(_ACCOUNT, None)] and lookups.counts == {"hit": 2, "miss": 1}


async def test_peek_serves_only_what_is_cached_and_never_awaits() -> None:
    cache, _ = _cache(_Reads(_row()))
    assert cache.peek(_ACCOUNT) is None
    loaded = await cache.get_effective_profile(_ACCOUNT)
    assert cache.peek(_ACCOUNT) is loaded and cache.peek(_ACCOUNT, _P.profile_id) is loaded


async def test_an_entry_older_than_the_ttl_is_read_again() -> None:
    reads = _Reads(_row(version=3), _row(version=4))
    cache, clock = _cache(reads, ttl_s=30.0)
    await cache.get_effective_profile(_ACCOUNT)
    clock.now += 29.9
    assert (await cache.get_effective_profile(_ACCOUNT)).version == 3
    clock.now += 0.1
    assert cache.peek(_ACCOUNT) is None
    assert (await cache.get_effective_profile(_ACCOUNT)).version == 4 and len(reads.calls) == 2


async def test_another_accounts_profile_id_is_a_miss_and_not_found() -> None:
    other = uuid4()
    cache, _ = _cache(_Reads(_row(), None))
    await cache.get_effective_profile(_ACCOUNT)
    assert cache.peek(other, _P.profile_id) is None
    with pytest.raises(AccountNotFoundError):
        await cache.get_effective_profile(other, _P.profile_id)


async def test_a_missing_profile_is_not_found_and_not_cached() -> None:
    reads = _Reads(None, None)
    cache, _ = _cache(reads)
    for _ in range(2):
        with pytest.raises(AccountNotFoundError):
            await cache.get_effective_profile(_ACCOUNT)
    assert len(reads.calls) == 2


async def test_concurrent_readers_share_one_load() -> None:
    reads = _Reads(_row(), gated=True)
    cache, _ = _cache(reads)
    first = asyncio.ensure_future(cache.get_effective_profile(_ACCOUNT))
    await _entered(reads, 0)
    second = asyncio.ensure_future(cache.get_effective_profile(_ACCOUNT))
    reads.gates[0].set()
    assert (await first).version == (await second).version == 3
    assert len(reads.calls) == 1


async def test_cancelling_one_reader_leaves_the_shared_load_to_the_others() -> None:
    reads = _Reads(_row(), gated=True)
    cache, _ = _cache(reads)
    first = asyncio.ensure_future(cache.get_effective_profile(_ACCOUNT))
    await _entered(reads, 0)
    second = asyncio.ensure_future(cache.get_effective_profile(_ACCOUNT))
    await asyncio.sleep(0)  # let the second reader join the load
    first.cancel()
    reads.gates[0].set()
    assert (await second).version == 3
    with pytest.raises(asyncio.CancelledError):
        await first
    assert len(reads.calls) == 1


async def test_a_load_started_before_invalidate_is_neither_installed_nor_served() -> None:
    """SR-E28-15: once a write has invalidated, no older version is answered."""
    reads = _Reads(_row(version=3), _row(version=4), gated=True)
    cache, _ = _cache(reads)
    early = asyncio.ensure_future(cache.get_effective_profile(_ACCOUNT))
    await _entered(reads, 0)
    cache.invalidate(_ACCOUNT)  # a narrowing write lands while version 3 is being read
    late = asyncio.ensure_future(cache.get_effective_profile(_ACCOUNT))
    await _entered(reads, 1)  # the late reader did not join the overtaken load
    reads.gates[1].set()
    assert (await late).version == 4
    reads.gates[0].set()  # the overtaken load ends last, so only its guard keeps version 3 out
    assert (await early).version == 4  # the early reader retried rather than return version 3
    cached = cache.peek(_ACCOUNT)
    assert cached is not None and cached.version == 4 and len(reads.calls) == 2


async def test_a_read_overtaken_twice_fails_closed() -> None:
    reads = _Reads(_row(version=3), _row(version=4), gated=True)
    cache, _ = _cache(reads)
    reader = asyncio.ensure_future(cache.get_effective_profile(_ACCOUNT))
    await _entered(reads, 0)
    cache.invalidate(_ACCOUNT)
    reads.gates[0].set()
    await _entered(reads, 1)  # the retry's load
    cache.invalidate(_ACCOUNT)
    reads.gates[1].set()
    with pytest.raises(ProfileUnavailableError):
        await reader


async def test_a_store_failure_fails_closed_and_is_not_cached() -> None:
    reads = _Reads(StorageTierUnavailable("postgres unreachable (OSError)"), _row())
    cache, _ = _cache(reads)
    with pytest.raises(ProfileUnavailableError) as ei:
        await cache.get_effective_profile(_ACCOUNT)
    assert ei.value.__cause__ is None
    assert (await cache.get_effective_profile(_ACCOUNT)).version == 3


async def test_a_slow_store_fails_closed_at_the_load_timeout() -> None:
    reads = _Reads(_row(), gated=True)
    cache, _ = _cache(reads, load_timeout_s=0.01)
    with pytest.raises(ProfileUnavailableError):
        await cache.get_effective_profile(_ACCOUNT)  # the gate never opens: a hung store
    reads.gates[0].set()


async def test_invalidate_drops_only_that_accounts_profiles() -> None:
    other = _profile(profile_id=str(uuid4()), account_id=str(uuid4()))
    reads = _Reads(_row(), _row(other))
    cache, _ = _cache(reads)
    await cache.get_effective_profile(_ACCOUNT)
    await cache.get_effective_profile(other.account_id)
    cache.invalidate(_ACCOUNT)
    assert cache.peek(_ACCOUNT) is None and cache.peek(other.account_id) is not None


async def test_the_oldest_profile_is_dropped_past_the_bound_with_its_default_pointer() -> None:
    profiles = [_profile(profile_id=str(uuid4()), account_id=str(uuid4())) for _ in range(3)]
    reads = _Reads(*(_row(p) for p in profiles))
    cache, _ = _cache(reads, max_entries=2)
    for p in profiles:
        await cache.get_effective_profile(p.account_id)
    assert cache.peek(profiles[0].account_id) is None
    assert all(cache.peek(p.account_id) is not None for p in profiles[1:])


async def test_a_non_default_profile_does_not_answer_for_the_default() -> None:
    alternate = _profile(profile_id=str(uuid4()), is_default=False, name="Alt")
    cache, _ = _cache(_Reads(_row(alternate)))
    assert (await cache.get_effective_profile(_ACCOUNT, alternate.profile_id)).name == "Alt"
    assert cache.peek(_ACCOUNT) is None


async def test_a_former_default_read_again_stops_answering_for_the_default() -> None:
    """SEC-1B-01: the default moved outside this process. Once the old default is read again as
    a plain profile it no longer answers for the account's default, which is loaded afresh."""
    moved = _P.model_copy(update={"is_default": False})
    successor = _profile(profile_id=str(uuid4()), name="Swing")
    reads = _Reads(_row(_P), _row(moved, version=4), _row(successor))
    cache, clock = _cache(reads)
    assert (await cache.get_effective_profile(_ACCOUNT)).profile_id == _P.profile_id
    clock.now += 31.0
    assert not (await cache.get_effective_profile(_ACCOUNT, _P.profile_id)).is_default
    assert cache.peek(_ACCOUNT) is None
    assert (await cache.get_effective_profile(_ACCOUNT)).profile_id == successor.profile_id
    assert reads.calls == [(_ACCOUNT, None), (_ACCOUNT, _P.profile_id), (_ACCOUNT, None)]


async def test_a_stored_row_the_model_refuses_fails_closed_without_its_values() -> None:
    """SEC-1B-02: the database does not check symbol entries, so a stored row can be one the model
    refuses. It is an unreadable profile (SR-E28-24), and its values stay out of the error."""
    row = _row()
    unreadable = dataclasses.replace(
        row, values=dataclasses.replace(row.values, allowed_symbols=("btc usdt; drop",))
    )
    cache, _ = _cache(_Reads(unreadable, _row()))
    with structlog.testing.capture_logs() as logs, pytest.raises(ProfileUnavailableError) as ei:
        await cache.get_effective_profile(_ACCOUNT)
    assert "btc" not in str(ei.value) and ei.value.__cause__ is None
    assert [(log["reason"], log["error"]) for log in logs] == [("invalid_row", "ValidationError")]
    assert "btc" not in str(logs)
    assert cache.peek(_ACCOUNT) is None
    assert (await cache.get_effective_profile(_ACCOUNT)).version == 3


async def test_invalidate_drops_a_profile_cached_by_its_id() -> None:
    """SR-E28-15: the order path reads by profile id too, so its entry goes with the account."""
    reads = _Reads(_row(version=3), _row(version=4))
    cache, _ = _cache(reads)
    await cache.get_effective_profile(_ACCOUNT, _P.profile_id)
    cache.invalidate(_ACCOUNT)
    assert cache.peek(_ACCOUNT, _P.profile_id) is None
    assert (await cache.get_effective_profile(_ACCOUNT, _P.profile_id)).version == 4
    assert len(reads.calls) == 2


async def test_a_write_to_another_account_does_not_overtake_a_read() -> None:
    """Generations are per account: only the account's own writes make a read retry."""
    reads = _Reads(_row(), gated=True)
    cache, _ = _cache(reads)
    reader = asyncio.ensure_future(cache.get_effective_profile(_ACCOUNT))
    await _entered(reads, 0)
    cache.invalidate(uuid4())
    cache.invalidate(uuid4())
    reads.gates[0].set()
    assert (await reader).version == 3
    assert len(reads.calls) == 1 and cache.peek(_ACCOUNT) is not None


async def test_aclose_cancels_a_load_its_reader_gave_up_on() -> None:
    reads = _Reads(_row(), gated=True)
    cache, _ = _cache(reads, load_timeout_s=0.01)
    with pytest.raises(ProfileUnavailableError):
        await cache.get_effective_profile(_ACCOUNT)  # the reader stops waiting; the load runs on
    await cache.aclose()
    assert reads.cancelled == [0] and cache.peek(_ACCOUNT) is None


async def test_each_fail_closed_read_is_logged_with_its_reason_and_no_value() -> None:
    cache, _ = _cache(_Reads(StorageTierUnavailable("postgres unreachable (OSError)")))
    with structlog.testing.capture_logs() as logs, pytest.raises(ProfileUnavailableError):
        await cache.get_effective_profile(_ACCOUNT)
    assert logs == [
        {
            "event": "profile.read_failed_closed",
            "reason": "store_unavailable",
            "account_id": str(_ACCOUNT),
            "error": "StorageTierUnavailable",
            "sqlstate": None,
            "log_level": "warning",
        }
    ]


async def test_a_query_fault_is_logged_apart_from_an_outage() -> None:
    """A missed migration (42P01) and a lost database both fail closed, told apart in the log."""
    cache, _ = _cache(_Reads(StorageQueryFailed("42P01")))
    with structlog.testing.capture_logs() as logs, pytest.raises(ProfileUnavailableError):
        await cache.get_effective_profile(_ACCOUNT)
    assert [(log["error"], log["sqlstate"]) for log in logs] == [("StorageQueryFailed", "42P01")]


async def test_a_timed_out_and_an_overtaken_read_are_logged_with_their_reason() -> None:
    slow = _Reads(_row(), gated=True)
    cache, _ = _cache(slow, load_timeout_s=0.01)
    with structlog.testing.capture_logs() as logs, pytest.raises(ProfileUnavailableError):
        await cache.get_effective_profile(_ACCOUNT)
    slow.gates[0].set()
    reads = _Reads(_row(version=3), _row(version=4), gated=True)
    overtaken, _ = _cache(reads)
    with structlog.testing.capture_logs() as more:
        reader = asyncio.ensure_future(overtaken.get_effective_profile(_ACCOUNT))
        await _entered(reads, 0)
        overtaken.invalidate(_ACCOUNT)
        reads.gates[0].set()
        await _entered(reads, 1)
        overtaken.invalidate(_ACCOUNT)
        reads.gates[1].set()
        with pytest.raises(ProfileUnavailableError):
            await reader
    assert [log["reason"] for log in logs] == ["timeout"]
    assert [log["reason"] for log in more] == ["overtaken"]


async def test_a_load_that_fails_after_its_reader_left_is_still_retrieved() -> None:
    """No "Task exception was never retrieved" for a load whose reader timed out first: the
    cache retrieves the failure itself when the load settles (CR-1B-R3-03)."""
    reads = _Reads(StorageTierUnavailable("postgres unreachable (OSError)"), gated=True)
    cache, _ = _cache(reads, load_timeout_s=0.01)
    with pytest.raises(ProfileUnavailableError):
        await cache.get_effective_profile(_ACCOUNT)
    (load,) = cache._tasks  # the orphaned load, still waiting on the store
    reads.gates[0].set()
    await asyncio.wait({load})
    assert not load._log_traceback  # asyncio's own flag: set until someone retrieves the error
    assert not cache._tasks and isinstance(load.exception(), StorageTierUnavailable)


@pytest.mark.parametrize(
    "decoded",
    [TypeError("tp_ladder is not a JSON array"), KeyError("pct"), ArithmeticError("decimal")],
    ids=["type", "key", "arithmetic"],
)
async def test_a_row_the_store_cannot_decode_fails_closed(decoded: Exception) -> None:
    """SR-E28-24: the store's own decoder refusing a stored row is an unreadable profile too."""
    cache, _ = _cache(_Reads(decoded))
    with structlog.testing.capture_logs() as logs, pytest.raises(ProfileUnavailableError) as ei:
        await cache.get_effective_profile(_ACCOUNT)
    assert ei.value.__cause__ is None and ei.value.__suppress_context__
    assert [(log["reason"], log["error"]) for log in logs] == [
        ("invalid_row", type(decoded).__name__)
    ]


async def test_a_store_record_error_is_the_store_failing_not_an_unreadable_row() -> None:
    """A `StorageError` that is also a `ValueError` is the store's answer, mapped as such."""
    cache, _ = _cache(_Reads(StorageRecordInvalid("column missing")))
    with structlog.testing.capture_logs() as logs, pytest.raises(ProfileUnavailableError):
        await cache.get_effective_profile(_ACCOUNT)
    assert [(log["reason"], log["error"]) for log in logs] == [
        ("store_unavailable", "StorageRecordInvalid")
    ]


async def test_a_loaded_profile_of_another_account_is_never_served() -> None:
    """Defence in depth: the load is re-checked as `peek` re-checks the cache (C-12.4)."""
    other = _profile(profile_id=str(uuid4()), account_id=str(uuid4()))
    cache, _ = _cache(_Reads(_row(other)))
    with pytest.raises(AccountNotFoundError):
        await cache.get_effective_profile(_ACCOUNT, other.profile_id)
    assert cache.peek(other.account_id, other.profile_id) is None  # refused before it is cached


async def test_a_loaded_non_default_never_answers_for_the_default() -> None:
    alternate = _profile(profile_id=str(uuid4()), is_default=False, name="Alt")
    cache, _ = _cache(_Reads(_row(alternate)))
    with pytest.raises(AccountNotFoundError):
        await cache.get_effective_profile(_ACCOUNT)
    assert cache.peek(_ACCOUNT, alternate.profile_id) is None


def test_the_bound_must_hold_one_profile() -> None:
    with pytest.raises(ValueError, match="max_entries"):
        EffectiveProfiles(_Reads(), max_entries=0)


async def test_the_cached_profile_is_the_one_the_store_answered() -> None:
    cache, _ = _cache(_Reads(_row(_P, version=7)))
    profile = await cache.get_effective_profile(_ACCOUNT)
    assert profile.version == 7 and profile.risk_pct_equity == _P.risk_pct_equity
