"""`StorageFlagStore` (E42-T03): the admin `FlagStore` port over the flag repository. Rows pass as
stored, readable or not; a stale row becomes `StaleWriteError` with the locked row; an outage, a
missing row and a lapsed bound become `StoreUnavailableError`; what `prepare` raises reaches the
writer as is."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.admin.flags import FLAGS, FlagWrite, StaleWriteError, StoredFlag
from candleviewer.admin.flags import StoreUnavailableError as Unavailable
from candleviewer.flags_wiring import StorageFlagStore, write_bound_s
from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories.flags_sqlalchemy import (
    FlagChange,
    FlagRow,
    FlagRowMissingError,
    FlagSeed,
    RowPrepare,
    StaleFlagRowError,
)

_USER, _ACTOR = uuid.UUID(int=9), uuid.UUID(int=7)
_AT = datetime(2026, 10, 16, 8, 0, 0, 123456, tzinfo=UTC)
#: An unreadable value and override, as a direct database change could leave them.
_ROW = FlagRow({"odd": 1}, {_USER: "maybe"}, {"viewer": True}, _AT, _ACTOR)
_STORED = StoredFlag({"odd": 1}, {_USER: "maybe"}, {"viewer": True}, _AT, _ACTOR)  # type: ignore[arg-type]  # unreadable on purpose


class _Repo:
    """Records what reaches it; raises `error` once `prepare` ran (as the repository does)."""

    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.seeds: list[FlagSeed] = []
        self.changes: list[FlagChange] = []

    async def ensure(self, seeds: Iterable[FlagSeed]) -> None:
        self.seeds = list(seeds)
        if self.error is not None:
            raise self.error

    async def load(self) -> Mapping[str, FlagRow]:
        if self.error is not None:
            raise self.error
        return {"trading.one_click": _ROW}

    async def write(self, key: str, prepare: RowPrepare) -> FlagRow:
        self.changes.append(change := await prepare(_ROW))
        if self.error is not None:
            raise self.error
        return replace(_ROW, value=change.value, user_overrides=change.user_overrides)


def _store(repo: _Repo, bound_s: float = 3.5, environment: str = "live") -> StorageFlagStore:
    fake: Any = repo  # a structural fake repository
    return StorageFlagStore(fake, bound_s=bound_s, environment=environment)


async def _set(store: StorageFlagStore, seen: list[StoredFlag]) -> StoredFlag:
    async def prepare(row: StoredFlag) -> FlagWrite:
        seen.append(row)
        return FlagWrite("trading.one_click", True, {_USER: False}, _AT, _ACTOR)

    return await store.write("trading.one_click", prepare)


@pytest.mark.parametrize(
    ("environment", "oms"), [("live", False), ("demo", True), ("testnet", False)]
)
async def test_ensure_seeds_each_flag_at_its_default_or_its_environments_seed(
    environment: str, oms: bool
) -> None:
    """#913 slice 3 Q3: `trading.oms_enabled` is seeded on in a demo process alone."""
    repo = _Repo()
    await _store(repo, environment=environment).ensure(FLAGS)
    seeded = {f.key: f.default for f in FLAGS} | {"trading.oms_enabled": oms}
    assert repo.seeds == [
        FlagSeed(f.key, f.kind.value, f.description, seeded[f.key], f.is_killswitch, f.variants)
        for f in FLAGS
    ]


@pytest.mark.parametrize(
    ("key", "seed"),
    [
        ("killswitch.order_entry", True),
        ("maintenance.mode", True),
        ("trading.live_enabled", True),  # the live gate
        ("trading.one_click", "yes"),  # a boolean flag takes no string
    ],
)
async def test_ensure_ignores_a_seed_on_a_kill_switch_the_live_gate_or_of_the_wrong_kind(
    monkeypatch: pytest.MonkeyPatch, key: str, seed: object
) -> None:
    """CR-S3B1-02, C-4.14: the catalogue's table is not the only guard. Such a seed is logged and
    its flag keeps the default, while a valid seed beside it still lands."""
    table = {key: {"demo": seed}, "trading.oms_enabled": {"demo": True}}
    monkeypatch.setattr("candleviewer.flags_wiring.ENVIRONMENT_SEEDS", table)
    repo = _Repo()
    with capture_logs() as logs:
        await _store(repo, environment="demo").ensure(FLAGS)
    expected = {f.key: f.default for f in FLAGS} | {"trading.oms_enabled": True}
    assert {s.key: s.default for s in repo.seeds} == expected
    assert [(log["event"], log["key"], log["environment"]) for log in logs] == [
        ("feature_flag_seed_ignored", key, "demo")
    ]


async def test_a_write_prepares_on_the_row_as_stored_and_returns_the_new_row() -> None:
    repo, seen = _Repo(), list[StoredFlag]()
    written = await _set(_store(repo), seen)
    assert seen == [_STORED]
    assert repo.changes == [FlagChange(True, {_USER: False}, _AT, _ACTOR)]
    assert written == replace(_STORED, value=True, user_overrides={_USER: False})


async def test_a_stale_row_is_a_stale_write_carrying_the_locked_row() -> None:
    with pytest.raises(StaleWriteError) as stale:
        await _set(_store(_Repo(StaleFlagRowError(_ROW))), [])
    assert stale.value.current == _STORED


@pytest.mark.parametrize("error", [StorageTierUnavailable("down"), FlagRowMissingError("its user")])
async def test_nothing_written_for_a_store_reason_is_store_unavailable(error: Exception) -> None:
    for call in (_store(_Repo(error)).ensure(FLAGS), _store(_Repo(error)).load()):
        with pytest.raises(Unavailable):
            await call
    with capture_logs() as logs, pytest.raises(Unavailable) as raised:
        await _set(_store(_Repo(error)), [])
    assert raised.value.__cause__ is None and str(raised.value) == type(error).__name__
    missing = [e for e in logs if e["event"] == "feature_flag_row_missing"]
    expected = [{"key": "trading.one_click", "row": "its user"}]
    assert [{k: e[k] for k in ("key", "row")} for e in missing] == (
        expected if isinstance(error, FlagRowMissingError) else []
    )


async def test_what_prepare_raises_reaches_the_writer_as_is_even_a_storage_error() -> None:
    mine = StorageTierUnavailable("the users store")  # never taken for the flag store's outage

    async def refuse(_: StoredFlag) -> Any:
        raise mine

    with pytest.raises(StorageTierUnavailable) as raised:
        await _store(_Repo()).write("trading.one_click", refuse)
    assert raised.value is mine


async def test_a_write_past_its_bound_is_store_unavailable() -> None:
    class _Stalled(_Repo):  # a connect, pool or commit stall: no server-side bound covers it
        async def write(self, key: str, prepare: RowPrepare) -> FlagRow:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

    async with asyncio.timeout(5):  # a removed bound fails here instead of hanging CI
        with pytest.raises(Unavailable, match="TimeoutError"):
            await _set(_store(_Stalled(), 0.01), [])
    assert (write_bound_s(500), write_bound_s(2000)) == (3.5, 5.0)  # 5 s: the writer tests' cap
