"""`ProfilesRepository` (E28-T01 #905): rows to `AccountProfile`, store errors to the accounts
domain errors, one not-found for every miss, the cache invalidated by every write, and each
committed write announced (#906 D3a)."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
import structlog

from candleviewer.accounts import profile_repository
from candleviewer.accounts.errors import (
    AccountConflictError,
    AccountNotFoundError,
    AccountRuleError,
    AccountScopeDeniedError,
    AccountsError,
    AccountVersionConflictError,
    ProfileUnavailableError,
)
from candleviewer.accounts.profile_changes import ProfilesChanged
from candleviewer.accounts.profile_repository import (
    DefaultBinding,
    ProfilesRepository,
    StoredProfile,
)
from candleviewer.accounts.profiles import AccountProfile, profile_from_row, profile_values
from candleviewer.storage.errors import StorageQueryFailed, StorageTierUnavailable
from candleviewer.storage.repositories.account_profiles import (
    DEFAULT_MOVES_ALONE,
    AccountProfileRevision,
    AccountProfileRow,
    AccountProfileStoreConflictError,
    AccountProfileStoreError,
    AccountProfileStoreRuleError,
    AccountProfileStoreScopeDeniedError,
    AccountProfileStoreStaleError,
    DefaultBindingRow,
    DefaultMove,
)
from candleviewer.storage.repositories.accounts import OwnerScope

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "profiles"
_T = datetime(2026, 10, 20, 9, tzinfo=UTC)
_CREATED = 1_792_486_800_000_000  # `_T` in microseconds
_OWNER = OwnerScope(uuid4())


def _profile(**changes: Any) -> AccountProfile:
    data = json.loads((_FIXTURES / "risk_based.json").read_text(encoding="utf-8"))
    return AccountProfile.model_validate({**data, **changes})


_P = _profile()
_IDS = (_P.account_id, _P.profile_id)


async def _no_record(before: object, after: object) -> None:
    """A write's write-ahead hook that records nothing; the fake store never awaits it."""


_NO = _no_record


def _row(profile: AccountProfile = _P, *, version: int = 3, **values: Any) -> AccountProfileRow:
    stored = dataclasses.replace(profile_values(profile), **values)
    return AccountProfileRow(
        id=profile.profile_id, exchange_account_id=profile.account_id, version=version,
        values=stored, created_by=None, updated_by=None, created_at=_T, updated_at=_T,
        deleted_at=None,
    )  # fmt: skip


class _Store:
    """Answers each call with the scripted value, or raises it; `events` records when the call
    returned, in the order shared with `_Cache`."""

    def __init__(self, answer: object, events: list[str] | None = None) -> None:
        self.answer = answer
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.events = [] if events is None else events

    def __getattr__(self, name: str) -> Any:
        async def call(*args: Any, **kwargs: Any) -> object:
            self.calls.append((name, args, kwargs))
            self.events.append("store returned")
            if isinstance(self.answer, BaseException):
                raise self.answer
            return self.answer

        return call


class _Cache:
    def __init__(self, events: list[str] | None = None) -> None:
        self.invalidated: list[UUID] = []
        self.events = [] if events is None else events

    def invalidate(self, account_id: UUID) -> None:
        self.invalidated.append(account_id)
        self.events.append("invalidated")


class _Counter:
    def __init__(self) -> None:
        self.total = 0.0

    def inc(self, amount: float = 1) -> None:
        self.total += amount

    def child(self) -> _Counter:
        return self


def _repo(answer: object) -> tuple[ProfilesRepository, _Store, _Cache, _Counter]:
    events: list[str] = []
    store, cache, bumps = _Store(answer, events), _Cache(events), _Counter()
    # The facade names the concrete cache and metric types; these fakes are structural.
    repo = ProfilesRepository(store, cache=cache, version_bumps=bumps)  # type: ignore[arg-type]  # fakes
    return repo, store, cache, bumps


async def test_reads_map_rows_to_the_domain_model() -> None:
    repo, store, _, _ = _repo((_row(), _row(_profile(profile_id=str(uuid4()), name="B"))))
    profiles = await repo.list_profiles(_OWNER, _P.account_id)
    assert [p.name for p in profiles] == ["Risk 1%", "B"] and profiles[0].version == 3
    assert profiles[0].risk_pct_equity == Decimal("0.01")
    assert store.calls == [("list_profiles", (_OWNER, _P.account_id), {})]


_READS: dict[str, Any] = {
    "read_profiles": lambda r: r.read_profiles(_OWNER, _P.account_id),
    "read_profile": lambda r: r.read_profile(_OWNER, _P.account_id, _P.profile_id),
    "list_profiles": lambda r: r.list_profiles(_OWNER, _P.account_id),
    "get_profile": lambda r: r.get_profile(_OWNER, _P.account_id, _P.profile_id),
}


async def test_a_read_answers_each_profile_with_its_rows_created_at() -> None:
    """#906 D1b: the row's `created_at`, which the model does not hold, in exact microseconds;
    `list_profiles` and `get_profile` still answer the model alone."""
    first = dataclasses.replace(_row(), created_at=datetime(2026, 10, 1, 8, 30, 15, 123456, UTC))
    rows = (first, _row(_profile(profile_id=str(uuid4()), name="B")))
    repo, store, _, _ = _repo(rows)
    read = await repo.read_profiles(_OWNER, _P.account_id)
    assert [s.created_at for s in read] == [1_790_843_415_123_456, 1_792_486_800_000_000]
    assert [s.profile for s in read] == [profile_from_row(row) for row in rows]
    assert await repo.list_profiles(_OWNER, _P.account_id) == tuple(s.profile for s in read)
    assert store.calls[0] == ("list_profiles", (_OWNER, _P.account_id), {})
    one, one_store, _, _ = _repo(first)
    assert await one.read_profile(_OWNER, _P.account_id, _P.profile_id) == read[0]
    assert await one.get_profile(_OWNER, _P.account_id, _P.profile_id) == read[0].profile
    # the caller's scope and both ids, as given, once per read
    assert one_store.calls == [("get_profile", (_OWNER, _P.account_id, _P.profile_id), {})] * 2
    assert isinstance(read[0], StoredProfile)


@pytest.mark.parametrize("read", list(_READS))
@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (TypeError("Decimal('NaN') in sl_offset_value"), "TypeError"),  # the store's decode
        (KeyError("pct"), "KeyError"),  # a stored ladder rung with no `pct`
        (InvalidOperation(), "InvalidOperation"),  # a non-numeric rung: an ArithmeticError
        (_row(allowed_symbols=("btcusdt",)), "ValidationError"),  # the model's, not a CHECK's
    ],
    ids=["store", "ladder-key", "ladder-number", "model"],
)
async def test_an_unreadable_stored_row_fails_closed_and_logs_no_value(
    read: str, answer: object, error: str
) -> None:
    """SR-E28-24: `ProfileUnavailableError`, unchained, as the order path's cache answers it; the
    log line names the error's class and never a value (C-12.6)."""
    listed = read in ("read_profiles", "list_profiles") and not isinstance(answer, BaseException)
    repo, _, _, _ = _repo((answer,) if listed else answer)
    with structlog.testing.capture_logs() as logs, pytest.raises(ProfileUnavailableError) as ei:
        await _READS[read](repo)
    assert str(ei.value) == "stored profile unreadable"
    assert ei.value.__cause__ is None and ei.value.__suppress_context__
    assert logs == [
        {
            "event": "profile.read_failed_closed",
            "reason": "invalid_row",
            "account_id": str(_P.account_id),
            "error": error,
            "log_level": "warning",
        }
    ]


@pytest.mark.parametrize("read", list(_READS))
@pytest.mark.parametrize(
    "raised", [StorageTierUnavailable("pg"), StorageQueryFailed("57014")], ids=["tier", "query"]
)
async def test_a_storage_error_reaches_the_caller_unchanged(read: str, raised: Exception) -> None:
    """An outage is not an unreadable row (#906 D1b, code lens R1C-03): D1c's 503 logs the class
    and sqlstate it receives, so the reads pass a `StorageError` through as raised."""
    repo, _, _, _ = _repo(raised)
    with pytest.raises(type(raised)) as ei:
        await _READS[read](repo)
    assert ei.value is raised


@pytest.mark.parametrize(
    "call",
    [
        lambda r: r.get_profile(_OWNER, _P.account_id, _P.profile_id),
        _READS["read_profile"],
        lambda r: r.update_profile(_OWNER, *_IDS, _P, expected_version=3, write_ahead=_NO),
        lambda r: r.delete_profile(_OWNER, *_IDS, expected_version=3, write_ahead=_NO),
        lambda r: r.set_default_profile(_OWNER, *_IDS, expected_binding_version=3, write_ahead=_NO),
        lambda r: r.get_revision(_OWNER, _P.account_id, _P.profile_id, 2),
        lambda r: r.create_profile(_OWNER, _P.account_id, _P, write_ahead=_NO),
    ],
    ids=["get", "read", "update", "delete", "set_default", "revision", "create"],
)
async def test_every_miss_is_the_same_not_found(call: Any) -> None:
    repo, _, _, bumps = _repo(None)
    with pytest.raises(AccountNotFoundError) as ei:
        await call(repo)
    assert ei.value.entity == "profile" and str(ei.value) == "not found"
    assert bumps.total == 0  # a miss bumped no version (D2-3's combined re-check, R2-01)


@pytest.mark.parametrize(
    ("raised", "mapped", "detail"),
    [
        (AccountProfileStoreScopeDeniedError(), AccountScopeDeniedError, None),
        (AccountProfileStoreConflictError("ux_ap_name"), AccountConflictError, "ux_ap_name"),
        (AccountProfileStoreRuleError("ap_trading_caps"), AccountRuleError, "ap_trading_caps"),
        (AccountProfileStoreRuleError(DEFAULT_MOVES_ALONE), AccountRuleError, DEFAULT_MOVES_ALONE),
        (AccountProfileStoreStaleError(), AccountVersionConflictError, None),
        (AccountProfileStoreError("x"), AccountsError, None),
    ],
)
@pytest.mark.parametrize("call", ["update", *_READS])
async def test_store_errors_map_to_domain_errors_unchained(
    raised: AccountProfileStoreError, mapped: type[AccountsError], detail: str | None, call: str
) -> None:
    repo, _, _, _ = _repo(raised)
    with pytest.raises(mapped) as ei:
        await (_READS[call](repo) if call in _READS else _write(repo, call))
    assert type(ei.value) is mapped and ei.value.__cause__ is None
    assert ei.value.__suppress_context__
    if detail is not None:
        assert detail in (getattr(ei.value, "constraint", None), getattr(ei.value, "rule", None))


@pytest.mark.parametrize(
    "call",
    [
        lambda r: r.create_profile(_OWNER, uuid4(), _P, write_ahead=_NO),
        lambda r: r.update_profile(
            _OWNER, uuid4(), _P.profile_id, _P, expected_version=3, write_ahead=_NO
        ),
        lambda r: r.update_profile(
            _OWNER, _P.account_id, uuid4(), _P, expected_version=3, write_ahead=_NO
        ),
    ],
    ids=["create-other-account", "update-other-account", "update-other-profile"],
)
async def test_a_profile_naming_another_path_is_not_found_and_writes_nothing(call: Any) -> None:
    """The path's ids address a write (SEC-1B-06): a body naming others is a path mismatch, which
    reads as missing, as everywhere, and reaches no store."""
    repo, store, cache, bumps = _repo(_row())
    with pytest.raises(AccountNotFoundError) as ei:
        await call(repo)
    assert ei.value.entity == "profile"
    assert store.calls == [] and cache.invalidated == [] and bumps.total == 0


async def test_create_sends_the_stored_values_and_returns_the_database_version() -> None:
    repo, store, cache, bumps = _repo(_row(version=1))
    created = await repo.create_profile(_OWNER, _P.account_id, _P, write_ahead=_NO)
    assert created.profile.version == 1 and bumps.total == 0
    name, args, _ = store.calls[0]
    assert name == "create_profile"
    assert args == (_OWNER, _P.account_id, _P.profile_id, profile_values(_P))
    assert cache.invalidated == [_P.account_id]


async def test_update_passes_the_expected_version_and_counts_one_bump() -> None:
    repo, store, cache, bumps = _repo(_row(version=4))
    updated = await repo.update_profile(_OWNER, *_IDS, _P, expected_version=3, write_ahead=_NO)
    assert updated.profile.version == 4 and bumps.total == 1
    assert cache.invalidated == [_P.account_id]
    assert store.calls[0][2] == {"expected_version": 3, "write_ahead": _NO}


async def test_a_failed_write_still_invalidates_before_it_raises() -> None:
    """SR-E28-15: an ambiguous outcome must not leave an old profile cached."""
    for raised in (AccountProfileStoreStaleError(), RuntimeError("storage blip")):
        repo, _, cache, bumps = _repo(raised)
        with pytest.raises((AccountVersionConflictError, RuntimeError)):
            await repo.update_profile(_OWNER, *_IDS, _P, expected_version=3, write_ahead=_NO)
        assert cache.invalidated == [_P.account_id] and bumps.total == 0


_WRITES: dict[str, tuple[Any, object]] = {
    "create": (
        lambda r: r.create_profile(_OWNER, _P.account_id, _P, write_ahead=_NO),
        _row(version=1),
    ),
    "update": (
        lambda r: r.update_profile(_OWNER, *_IDS, _P, expected_version=3, write_ahead=_NO),
        _row(version=4),
    ),
    "delete": (
        lambda r: r.delete_profile(_OWNER, *_IDS, expected_version=3, write_ahead=_NO),
        _row(version=4),
    ),
    "set_default": (
        lambda r: r.set_default_profile(_OWNER, *_IDS, expected_binding_version=3, write_ahead=_NO),
        DefaultMove(
            profile=_row(version=4, is_default=True), previous=None, written=True, version=4
        ),
    ),
}


async def _write(repo: ProfilesRepository, write: str, **kw: Any) -> object:
    """One of the four writes on `_P`, at version 3 where it takes one, with a hook."""
    kw.setdefault("write_ahead", _NO)
    if write == "create":
        return await repo.create_profile(_OWNER, _P.account_id, _P, **kw)
    if write == "update":
        ids = (_P.account_id, _P.profile_id)
        return await repo.update_profile(_OWNER, *ids, _P, expected_version=3, **kw)
    if write == "delete":
        return await repo.delete_profile(
            _OWNER, _P.account_id, _P.profile_id, expected_version=3, **kw
        )
    return await repo.set_default_profile(
        _OWNER, _P.account_id, _P.profile_id, expected_binding_version=3, **kw
    )


@pytest.mark.parametrize("write", list(_WRITES))
async def test_every_write_hands_its_write_ahead_hook_to_the_store(write: str) -> None:
    """C-2.9: the hook runs in the store's transaction, so the facade passes it through as is."""

    async def hook(before: object, after: object) -> None:  # the fake store never awaits it
        raise AssertionError("not awaited here")

    repo, store, _, _ = _repo(_WRITES[write][1])
    await _write(repo, write, write_ahead=hook)
    assert store.calls[0][2]["write_ahead"] is hook


@pytest.mark.parametrize("write", list(_WRITES))
async def test_a_write_without_its_write_ahead_record_is_refused_before_the_store(
    write: str,
) -> None:
    """C-2.9, #906 D2-2 R1S-02: the hook is required, and a dynamic caller's `None` is a
    `TypeError` before the store or the cache is reached, so no write is made unrecorded."""
    repo, store, cache, bumps = _repo(_WRITES[write][1])
    with pytest.raises(TypeError, match="write-ahead record"):
        await _write(repo, write, write_ahead=None)
    assert (store.calls, cache.invalidated, bumps.total) == ([], [], 0)


_BAD: dict[str, Any] = {"allowed_symbols": ("btcusdt",)}  # the model's refusal, not a CHECK's
_MOVE: Any = _WRITES["set_default"][1]


@pytest.mark.parametrize(
    ("write", "answer", "bumped"),
    [
        ("create", _row(version=1, **_BAD), 0),
        ("update", _row(version=4, **_BAD), 1),
        ("delete", _row(version=4, **_BAD), 1),
        ("set_default", dataclasses.replace(_MOVE, profile=_row(version=4, **_BAD)), 1),
        ("set_default", dataclasses.replace(_MOVE, previous=_row(_profile(name="B"), **_BAD)), 2),
    ],
    ids=["create", "update", "delete", "move-target", "move-previous"],
)
async def test_a_write_answers_its_stored_row_and_an_unreadable_one_fails_closed(
    write: str, answer: object, bumped: int
) -> None:
    """#906 D2-3: a create and a replace answer the model with its row's `created_at`, for their
    documents; a written row the model cannot read is `ProfileUnavailableError` from every write
    (SR-E28-24), unchained and logged by its class alone as a committed row, with the account
    invalidated and its version bumps counted (R1C-04): the write committed, so its caller answers
    503, never a 500."""
    if write in ("create", "update"):
        row: Any = _WRITES[write][1]
        repo, _, _, _ = _repo(row)
        assert await _write(repo, write) == StoredProfile(profile_from_row(row), _CREATED)
    repo, _, cache, bumps = _repo(answer)
    with structlog.testing.capture_logs() as logs, pytest.raises(ProfileUnavailableError) as ei:
        await _write(repo, write)
    assert ei.value.__cause__ is None and ei.value.__suppress_context__
    assert [(log["event"], log["reason"], log["error"]) for log in logs] == [
        ("profile.read_failed_closed", "committed_row_unreadable", "ValidationError")
    ]
    assert cache.invalidated == [_P.account_id] and bumps.total == bumped


async def test_an_unreadable_row_from_a_move_that_wrote_nothing_is_not_called_committed() -> None:
    """A move that found the profile already the default committed nothing: its unreadable row is
    `invalid_row`, with nothing counted (R1C-04)."""
    move = dataclasses.replace(_MOVE, profile=_row(version=4, **_BAD), written=False)
    repo, _, _, bumps = _repo(move)
    with structlog.testing.capture_logs() as logs, pytest.raises(ProfileUnavailableError):
        await _write(repo, "set_default")
    assert [log["reason"] for log in logs] == ["invalid_row"] and bumps.total == 0


@pytest.mark.parametrize("refused", [False, True], ids=["committed", "refused"])
@pytest.mark.parametrize("write", list(_WRITES))
async def test_every_write_invalidates_only_after_the_store_returned(
    write: str, refused: bool
) -> None:
    """SR-E28-15: invalidating first would let a reader reload the old profile before the commit
    and serve it for a TTL after a narrowing write."""
    answer = AccountProfileStoreStaleError() if refused else _WRITES[write][1]
    repo, _, cache, _ = _repo(answer)
    if refused:
        with pytest.raises(AccountVersionConflictError):
            await _write(repo, write)
    else:
        await _write(repo, write)
    assert cache.events == ["store returned", "invalidated"]


@pytest.mark.parametrize("write", list(_WRITES))
async def test_every_write_invalidates_its_account_when_it_succeeds(write: str) -> None:
    """SR-E28-15: the next order-path read after any write goes to the store."""
    call, answer = _WRITES[write]
    repo, _, cache, _ = _repo(answer)
    await call(repo)
    assert cache.invalidated == [_P.account_id]


@pytest.mark.parametrize("write", list(_WRITES))
async def test_every_write_invalidates_its_account_when_the_store_refuses(write: str) -> None:
    """An ambiguous outcome must not leave an old profile cached; the error is unchained."""
    call, _ = _WRITES[write]
    repo, _, cache, bumps = _repo(AccountProfileStoreStaleError())
    with pytest.raises(AccountVersionConflictError) as ei:
        await call(repo)
    assert cache.invalidated == [_P.account_id] and bumps.total == 0
    assert ei.value.__cause__ is None and ei.value.__suppress_context__


async def test_a_refusal_is_logged_by_its_name_and_never_a_value() -> None:
    repo, _, _, _ = _repo(AccountProfileStoreRuleError("ap_trading_caps"))
    with structlog.testing.capture_logs() as logs, pytest.raises(AccountRuleError):
        await repo.update_profile(_OWNER, *_IDS, _P, expected_version=3, write_ahead=_NO)
    assert logs == [
        {
            "event": "profile.constraint_violation",
            "constraint": "ap_trading_caps",
            "log_level": "warning",
        }
    ]


async def test_moving_the_default_counts_both_bumps_and_returns_both_profiles() -> None:
    old = _row(_profile(profile_id=str(uuid4()), name="Old"), version=5, is_default=False)
    move = DefaultMove(
        profile=_row(version=4, is_default=True), previous=old, written=True, version=4
    )
    repo, _, cache, bumps = _repo(move)
    moved = await repo.set_default_profile(
        _OWNER, *_IDS, expected_binding_version=3, write_ahead=_NO
    )
    assert moved.profile.is_default and moved.previous is not None and moved.previous.name == "Old"
    assert bumps.total == 2 and cache.invalidated == [_P.account_id]


async def test_setting_the_default_again_writes_and_counts_nothing() -> None:
    move = DefaultMove(profile=_row(is_default=True), previous=None, written=False, version=3)
    repo, _, _, bumps = _repo(move)
    moved = await repo.set_default_profile(
        _OWNER, *_IDS, expected_binding_version=3, write_ahead=_NO
    )
    assert moved.previous is None and moved.version == 3 and bumps.total == 0


async def test_a_move_answers_the_binding_version_after_it() -> None:
    """The binding's `ETag` after the move (#906 0d) is the store's version, never the tag sent."""
    move = DefaultMove(
        profile=_row(version=4, is_default=True), previous=None, written=True, version=8
    )
    repo, store, _, _ = _repo(move)
    moved = await repo.set_default_profile(
        _OWNER, *_IDS, expected_binding_version=7, write_ahead=_NO
    )
    assert moved.version == 8 and moved.profile.is_default
    assert store.calls[0][2] == {"expected_binding_version": 7, "write_ahead": _NO}


def test_a_move_requires_the_binding_version_in_the_domain() -> None:
    """No default, so no caller can leave the `If-Match` out and fall back to last-write-wins:
    a later `int | None = None` that skipped the check would pass every test that sends it."""
    move = inspect.signature(ProfilesRepository.set_default_profile)
    assert move.parameters["expected_binding_version"].default is inspect.Parameter.empty


async def test_the_binding_reads_as_its_default_profile_and_version() -> None:
    row = DefaultBindingRow(account_id=_P.account_id, profile_id=_P.profile_id, version=5)
    repo, store, cache, _ = _repo(row)
    binding = await repo.get_default_binding(_OWNER, _P.account_id)
    assert binding == DefaultBinding(account_id=_P.account_id, profile_id=_P.profile_id, version=5)
    assert store.calls == [("get_default_binding", (_OWNER, _P.account_id), {})]
    assert cache.invalidated == []


async def test_a_binding_out_of_scope_or_missing_is_the_accounts_not_found() -> None:
    """The store reads an account that is missing, soft-deleted or out of the grants as `None`,
    all alike (no existence oracle); a binding names the account, so its miss does too. An owner
    scope held by anyone else is the uniform 403, unchained."""
    repo, _, _, _ = _repo(None)
    with pytest.raises(AccountNotFoundError) as ei:
        await repo.get_default_binding(_OWNER, _P.account_id)
    assert ei.value.entity == "account" and str(ei.value) == "not found"
    denied, _, _, _ = _repo(AccountProfileStoreScopeDeniedError())
    with pytest.raises(AccountScopeDeniedError) as refused:
        await denied.get_default_binding(_OWNER, _P.account_id)
    assert refused.value.__cause__ is None and refused.value.__suppress_context__


async def test_delete_counts_one_bump_and_returns_the_deleted_profile() -> None:
    repo, _, _, bumps = _repo(dataclasses.replace(_row(version=4), deleted_at=_T))
    deleted = await repo.delete_profile(_OWNER, *_IDS, expected_version=3, write_ahead=_NO)
    assert deleted.version == 4 and bumps.total == 1


async def test_a_revision_reads_as_the_profile_at_that_version() -> None:
    revision = AccountProfileRevision(
        id=9, version=2, profile=_row(version=2), changed_by=None, changed_at=_T
    )
    repo, store, cache, _ = _repo(revision)
    profile = await repo.get_revision(_OWNER, _P.account_id, _P.profile_id, 2)
    assert profile.version == 2 and store.calls[0][1][-1] == 2 and cache.invalidated == []


async def test_reads_never_invalidate() -> None:
    repo, _, cache, _ = _repo(_row())
    await repo.get_profile(_OWNER, _P.account_id, _P.profile_id)
    listing, _, list_cache, _ = _repo((_row(),))
    await listing.list_profiles(_OWNER, _P.account_id)
    assert cache.invalidated == [] and list_cache.invalidated == []


async def test_without_a_cache_or_metric_the_repository_still_works() -> None:
    repo = ProfilesRepository(_Store(_row(version=4)), cache=None)
    assert (
        await repo.update_profile(_OWNER, *_IDS, _P, expected_version=None, write_ahead=_NO)
    ).profile.version == 4


# --- #906 D3a: a committed write publishes its account's change (24 Sec.9.2) -----------------

_LATER = _T + timedelta(seconds=5)  # a write's `updated_at`, after the row's `created_at`
_KINDS = {"create": "created", "update": "updated", "delete": "deleted"}


class _Bell:
    """A `ProfileChanges` port: it hears each event, in the order shared with the store and the
    cache, then raises `fails` or, with `hangs`, waits until it is cancelled."""

    def __init__(self, events: list[str], fails: Exception | None = None, hangs: bool = False):
        self.events, self.fails, self.hangs = events, fails, hangs
        self.heard: list[ProfilesChanged] = []
        self.entered = asyncio.Event()

    async def changed(self, event: ProfilesChanged) -> None:
        self.events.append("rang")
        self.heard.append(event)
        self.entered.set()
        if self.hangs:
            await asyncio.Event().wait()
        if self.fails is not None:
            raise self.fails


def _belled(answer: object, **bell: Any) -> tuple[ProfilesRepository, _Bell, list[str]]:
    events: list[str] = []
    ring, store, cache = _Bell(events, **bell), _Store(answer, events), _Cache(events)
    repo = ProfilesRepository(store, cache=cache, changes=ring)  # type: ignore[arg-type]  # fakes
    return repo, ring, events


def _written(version: int, profile: AccountProfile = _P, **values: Any) -> AccountProfileRow:
    return dataclasses.replace(_row(profile, version=version, **values), updated_at=_LATER)


def _change(kind: str, *rows: AccountProfileRow, binding: int | None = None) -> ProfilesChanged:
    """`ts_event` is `_LATER`, the written row's `updated_at`, never the clock's."""
    named = tuple({"profile_id": r.id, "version": r.version} for r in rows)
    return ProfilesChanged.model_validate(
        {"exchange_account_id": _P.account_id, "change": kind, "profiles": named,
         "binding_version": binding, "ts_event": _CREATED + 5_000_000}
    )  # fmt: skip


@pytest.mark.parametrize("readable", [True, False], ids=["read-back", "unreadable"])
@pytest.mark.parametrize(("write", "version"), [("create", 1), ("update", 4), ("delete", 4)])
async def test_each_committed_write_rings_once_with_its_rows_new_versions(
    write: str, version: int, readable: bool
) -> None:
    """The kind, the row's id and version (the database's, never the `If-Match` sent) and its
    `updated_at`, once the store returned and the account was invalidated, and whether or not the
    row reads back: the write committed."""
    row = _written(version, **({} if readable else _BAD))
    repo, bell, events = _belled(row)
    with nullcontext() if readable else pytest.raises(ProfileUnavailableError):
        await _write(repo, write)
    assert bell.heard == [_change(_KINDS[write], row)]
    assert events == ["store returned", "invalidated", "rang"]


_OLD = _profile(profile_id=str(uuid4()), name="Old")


@pytest.mark.parametrize(
    ("previous", "readable"),
    [(_row(_OLD, version=6), True), (None, True), (_row(_OLD, version=6, **_BAD), False)],
    ids=["replaced", "first-default", "unreadable"],
)
async def test_a_move_rings_both_rows_demoted_first_with_the_bindings_new_version(
    previous: AccountProfileRow | None, readable: bool
) -> None:
    """One event per move: the demoted default, then the new one, each at its new version, the
    binding's version after the move (never the one sent) and the new default's `updated_at`."""
    new = _written(4, is_default=True)
    move = DefaultMove(profile=new, previous=previous, written=True, version=8)
    repo, bell, events = _belled(move)
    with nullcontext() if readable else pytest.raises(ProfileUnavailableError):
        await repo.set_default_profile(_OWNER, *_IDS, expected_binding_version=7, write_ahead=_NO)
    named = (new,) if previous is None else (previous, new)
    assert bell.heard == [_change("default_moved", *named, binding=8)]
    assert events == ["store returned", "invalidated", "rang"]


@pytest.mark.parametrize(
    ("write", "answer", "raised"),
    [
        *[(w, AccountProfileStoreStaleError(), AccountVersionConflictError) for w in _WRITES],
        ("create", AccountProfileStoreConflictError("ux_ap_name"), AccountConflictError),
        ("update", AccountProfileStoreRuleError("ap_trading_caps"), AccountRuleError),
        ("delete", AccountProfileStoreScopeDeniedError(), AccountScopeDeniedError),
        ("update", StorageTierUnavailable("pg"), StorageTierUnavailable),
        ("delete", None, AccountNotFoundError),
        ("create", None, AccountNotFoundError),
        ("update", None, AccountNotFoundError),
        ("set_default", dataclasses.replace(_MOVE, written=False), None),
        ("mismatch", _row(), AccountNotFoundError),
    ],
    ids=[
        *(f"stale-{w}" for w in _WRITES),
        *("conflict", "rule", "denied", "outage", "miss-delete", "miss-create", "miss-update"),
        *("no-op-move", "path-mismatch"),
    ],
)
async def test_a_write_that_changes_nothing_or_is_refused_rings_nothing(
    write: str, answer: object, raised: type[Exception] | None
) -> None:
    repo, bell, events = _belled(answer)
    with structlog.testing.capture_logs() as logs:
        with nullcontext() if raised is None else pytest.raises(raised):
            if write == "mismatch":  # a body naming another account reaches no store
                await repo.create_profile(_OWNER, uuid4(), _P, write_ahead=_NO)
            else:
                await _write(repo, write)
    assert bell.heard == [] and "rang" not in events
    assert "profile.change_unannounced" not in [log["event"] for log in logs]  # nor tried


@pytest.mark.parametrize("fault", ["fails", "hangs"])
@pytest.mark.parametrize("write", list(_WRITES))
async def test_a_doorbell_that_fails_or_hangs_never_fails_the_write(
    write: str, fault: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The write has committed: a doorbell that raises, or outlasts `ANNOUNCE_TIMEOUT_S` (forced
    to 0, no sleep), is logged once by the account, the change and the error class, never a value,
    and the write answers as it would have."""
    answer = _WRITES[write][1]
    expected = await _write(_repo(answer)[0], write)
    monkeypatch.setattr(profile_repository, "ANNOUNCE_TIMEOUT_S", 0)
    fails = RuntimeError(f"bus down near {_P.name}")  # a message the log line must not carry
    repo, _, _ = _belled(answer, **({"fails": fails} if fault == "fails" else {"hangs": True}))
    writing = asyncio.ensure_future(_write(repo, write))
    try:
        with structlog.testing.capture_logs() as logs:
            done, _ = await asyncio.wait({writing}, timeout=5)  # bounds the test; times nothing
        assert writing in done, "the write waited on its doorbell"
        assert writing.result() == expected
    finally:
        writing.cancel()
    error = "RuntimeError" if fault == "fails" else "TimeoutError"
    assert logs == [
        {"event": "profile.change_unannounced", "account_id": str(_P.account_id),
         "change": _KINDS.get(write, "default_moved"), "error": error, "log_level": "warning"}
    ]  # fmt: skip


async def test_an_announcement_waits_announce_timeout_s(monkeypatch: pytest.MonkeyPatch) -> None:
    """D3a's combined re-check, R2-03 (folded in D3e): `_ring` is bounded by the constant, never
    by a literal of its own. The constant is set apart from its 0.5 s and the bound `_ring` is
    given is recorded, so nothing is timed."""
    bounds: list[float] = []

    def timeout(delay: float) -> Any:
        bounds.append(delay)
        return asyncio.timeout(delay)

    monkeypatch.setattr(profile_repository, "ANNOUNCE_TIMEOUT_S", 0.25)
    monkeypatch.setattr(profile_repository, "asyncio", SimpleNamespace(timeout=timeout))
    repo, bell, _ = _belled(_WRITES["update"][1])
    await _write(repo, "update")
    assert (bounds, len(bell.heard)) == ([0.25], 1)


async def test_an_event_that_cannot_be_built_never_fails_the_write() -> None:
    """The write has committed: an event the model refuses (a binding version of 0) is logged by
    its class and never raised, as a port's failure is."""
    repo, bell, _ = _belled(dataclasses.replace(_MOVE, version=0))
    with structlog.testing.capture_logs() as logs:
        moved = await _write(repo, "set_default")
    assert (bell.heard, getattr(moved, "version", None)) == ([], 0)
    assert [(log["event"], log["error"]) for log in logs] == [
        ("profile.change_unannounced", "ValidationError")
    ]


async def test_a_cancelled_write_is_not_swallowed_by_its_doorbell() -> None:
    """`CancelledError` is not an `Exception`: a write cancelled while it rings stays cancelled."""
    repo, bell, _ = _belled(_row(version=4), hangs=True)
    writing = asyncio.ensure_future(_write(repo, "update"))
    await asyncio.wait_for(bell.entered.wait(), 5)  # bounds the test; times nothing
    writing.cancel()
    done, _ = await asyncio.wait({writing}, timeout=5)  # bounds the test; times nothing
    assert writing in done and writing.cancelled()


@pytest.mark.parametrize("write", list(_WRITES))
async def test_without_a_port_a_write_rings_nothing(write: str) -> None:
    """No port (the fake backend's facade, a test's): the write answers and logs nothing."""
    repo, _, _, _ = _repo(_WRITES[write][1])
    with structlog.testing.capture_logs() as logs:
        await _write(repo, write)
    assert logs == []
