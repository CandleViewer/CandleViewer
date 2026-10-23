"""`ProfilesRepository` (E28-T01 #905): rows to `AccountProfile`, store errors to the accounts
domain errors, one not-found for every miss, and the cache invalidated by every write."""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import structlog

from candleviewer.accounts.errors import (
    AccountConflictError,
    AccountNotFoundError,
    AccountRuleError,
    AccountScopeDeniedError,
    AccountsError,
    AccountVersionConflictError,
)
from candleviewer.accounts.profile_repository import DefaultBinding, ProfilesRepository
from candleviewer.accounts.profiles import AccountProfile, profile_values
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
_OWNER = OwnerScope(uuid4())


def _profile(**changes: Any) -> AccountProfile:
    data = json.loads((_FIXTURES / "risk_based.json").read_text(encoding="utf-8"))
    return AccountProfile.model_validate({**data, **changes})


_P = _profile()


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


@pytest.mark.parametrize(
    "call",
    [
        lambda r: r.get_profile(_OWNER, _P.account_id, _P.profile_id),
        lambda r: r.update_profile(_OWNER, _P.account_id, _P.profile_id, _P, expected_version=3),
        lambda r: r.delete_profile(_OWNER, _P.account_id, _P.profile_id, expected_version=3),
        lambda r: r.set_default_profile(
            _OWNER, _P.account_id, _P.profile_id, expected_binding_version=3
        ),
        lambda r: r.get_revision(_OWNER, _P.account_id, _P.profile_id, 2),
        lambda r: r.create_profile(_OWNER, _P.account_id, _P),
    ],
    ids=["get", "update", "delete", "set_default", "revision", "create"],
)
async def test_every_miss_is_the_same_not_found(call: Any) -> None:
    repo, _, _, _ = _repo(None)
    with pytest.raises(AccountNotFoundError) as ei:
        await call(repo)
    assert ei.value.entity == "profile" and str(ei.value) == "not found"


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
async def test_store_errors_map_to_domain_errors_unchained(
    raised: AccountProfileStoreError, mapped: type[AccountsError], detail: str | None
) -> None:
    repo, _, _, _ = _repo(raised)
    with pytest.raises(mapped) as ei:
        await repo.update_profile(_OWNER, _P.account_id, _P.profile_id, _P, expected_version=3)
    assert type(ei.value) is mapped and ei.value.__cause__ is None
    assert ei.value.__suppress_context__
    if detail is not None:
        assert detail in (getattr(ei.value, "constraint", None), getattr(ei.value, "rule", None))


@pytest.mark.parametrize(
    "call",
    [
        lambda r: r.create_profile(_OWNER, uuid4(), _P),
        lambda r: r.update_profile(_OWNER, uuid4(), _P.profile_id, _P, expected_version=3),
        lambda r: r.update_profile(_OWNER, _P.account_id, uuid4(), _P, expected_version=3),
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
    created = await repo.create_profile(_OWNER, _P.account_id, _P)
    assert created.version == 1 and bumps.total == 0
    name, args, _ = store.calls[0]
    assert name == "create_profile"
    assert args == (_OWNER, _P.account_id, _P.profile_id, profile_values(_P))
    assert cache.invalidated == [_P.account_id]


async def test_update_passes_the_expected_version_and_counts_one_bump() -> None:
    repo, store, cache, bumps = _repo(_row(version=4))
    updated = await repo.update_profile(
        _OWNER, _P.account_id, _P.profile_id, _P, expected_version=3
    )
    assert updated.version == 4 and bumps.total == 1 and cache.invalidated == [_P.account_id]
    assert store.calls[0][2] == {"expected_version": 3, "write_ahead": None}


async def test_a_failed_write_still_invalidates_before_it_raises() -> None:
    """SR-E28-15: an ambiguous outcome must not leave an old profile cached."""
    for raised in (AccountProfileStoreStaleError(), RuntimeError("storage blip")):
        repo, _, cache, bumps = _repo(raised)
        with pytest.raises((AccountVersionConflictError, RuntimeError)):
            await repo.update_profile(_OWNER, _P.account_id, _P.profile_id, _P, expected_version=3)
        assert cache.invalidated == [_P.account_id] and bumps.total == 0


_WRITES: dict[str, tuple[Any, object]] = {
    "create": (lambda r: r.create_profile(_OWNER, _P.account_id, _P), _row(version=1)),
    "update": (
        lambda r: r.update_profile(_OWNER, _P.account_id, _P.profile_id, _P, expected_version=3),
        _row(version=4),
    ),
    "delete": (
        lambda r: r.delete_profile(_OWNER, _P.account_id, _P.profile_id, expected_version=3),
        _row(version=4),
    ),
    "set_default": (
        lambda r: r.set_default_profile(
            _OWNER, _P.account_id, _P.profile_id, expected_binding_version=3
        ),
        DefaultMove(
            profile=_row(version=4, is_default=True), previous=None, written=True, version=4
        ),
    ),
}


async def _write(repo: ProfilesRepository, write: str, **kw: Any) -> object:
    """One of the four writes on `_P`, at version 3 where it takes one."""
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
        await repo.update_profile(_OWNER, _P.account_id, _P.profile_id, _P, expected_version=3)
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
        _OWNER, _P.account_id, _P.profile_id, expected_binding_version=3
    )
    assert moved.profile.is_default and moved.previous is not None and moved.previous.name == "Old"
    assert bumps.total == 2 and cache.invalidated == [_P.account_id]


async def test_setting_the_default_again_writes_and_counts_nothing() -> None:
    move = DefaultMove(profile=_row(is_default=True), previous=None, written=False, version=3)
    repo, _, _, bumps = _repo(move)
    moved = await repo.set_default_profile(
        _OWNER, _P.account_id, _P.profile_id, expected_binding_version=3
    )
    assert moved.previous is None and moved.version == 3 and bumps.total == 0


async def test_a_move_answers_the_binding_version_after_it() -> None:
    """The binding's `ETag` after the move (#906 0d) is the store's version, never the tag sent."""
    move = DefaultMove(
        profile=_row(version=4, is_default=True), previous=None, written=True, version=8
    )
    repo, store, _, _ = _repo(move)
    moved = await repo.set_default_profile(
        _OWNER, _P.account_id, _P.profile_id, expected_binding_version=7
    )
    assert moved.version == 8 and moved.profile.is_default
    assert store.calls[0][2] == {"expected_binding_version": 7, "write_ahead": None}


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
    deleted = await repo.delete_profile(_OWNER, _P.account_id, _P.profile_id, expected_version=3)
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
        await repo.update_profile(_OWNER, _P.account_id, _P.profile_id, _P, expected_version=None)
    ).version == 4
