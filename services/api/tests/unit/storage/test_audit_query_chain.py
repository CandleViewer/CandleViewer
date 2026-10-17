"""Chain material for a page (design §5, §17) and the process-wide read cap, on fakes.

The chain statement against the real trigger is covered by
`tests/integration/audit/test_audit_query_page.py` (CI)."""

from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from candleviewer.storage.errors import StorageTierUnavailable
from candleviewer.storage.repositories import audit_sqlalchemy as mod
from candleviewer.storage.repositories.audit_sqlalchemy import (
    CHAIN_FIELD_MAX_CHARS,
    CHAIN_PAGE_MAX_CHARS,
    AuditReadBusy,
    SqlAlchemyAuditRepository,
)

_WAIT_S = 5.0  # a hang guard: a regression must fail its test, not hang the run


class _ChainSession:
    """Answers the chain statement for the ids it is given: `after_state` of `sizes[id]`
    characters, cut at `:n` as Postgres `left()` would."""

    def __init__(self, sizes: dict[int, int]) -> None:
        self.sizes = sizes
        self.calls: list[list[int]] = []
        self.cuts: list[int] = []  # `:n` of each call

    async def execute(self, stmt: Any, params: dict[str, Any]) -> list[Any]:
        self.calls.append(params["ids"])
        self.cuts.append(params["n"])
        out = []
        for i in params["ids"]:
            text = "x" * min(self.sizes.get(i, 10), params["n"])
            chain = {"id": i, "after_state": text, "reason": None, "chain_prev_hash": "p"}
            out.append(SimpleNamespace(_mapping=chain))
        return out


async def _attach(sizes: dict[int, int], ids: range) -> tuple[list[dict[str, Any]], Any]:
    session, rows = _ChainSession(sizes), [{"id": i} for i in ids]
    await mod._attach_chain(session, rows)
    return rows, session


async def test_chain_is_fetched_by_id_in_chunks_newest_first() -> None:
    rows, session = await _attach({}, range(1, 121))
    assert [len(c) for c in session.calls] == [50, 50, 20]
    assert session.calls[0][:2] == [120, 119] and all(r["chain"] for r in rows)
    assert rows[0]["chain"]["chain_prev_hash"] == "p"


async def test_a_rendering_over_the_field_cap_leaves_only_that_row_without_a_form() -> None:
    rows, _ = await _attach({7: CHAIN_FIELD_MAX_CHARS + 5, 8: CHAIN_FIELD_MAX_CHARS}, range(1, 10))
    assert [r["id"] for r in rows if r["chain"] is None] == [7]


async def test_fetching_stops_past_the_page_cap() -> None:
    big = CHAIN_FIELD_MAX_CHARS
    per_chunk = 50 * big
    sizes = dict.fromkeys(range(1, 501), big)
    rows, session = await _attach(sizes, range(1, 501))
    complete = [r["id"] for r in rows if r["chain"] is not None]
    assert len(complete) == CHAIN_PAGE_MAX_CHARS // big  # newest first, up to the cap
    assert min(complete) == 500 - len(complete) + 1
    assert len(session.calls) == CHAIN_PAGE_MAX_CHARS // per_chunk + 1  # then stops


async def test_the_chunk_that_reaches_the_page_cap_is_cut_to_what_is_left() -> None:
    """F8-1: a rendering is cut one past what the page can still take, so the chunk that
    crosses the cap is not fetched at the field cap's width. Which rows are complete is the
    same as when every chunk is cut at the field cap."""
    size = (CHAIN_PAGE_MAX_CHARS - 4) // 300  # six chunks of 50 rows leave four characters
    rows, session = await _attach(dict.fromkeys(range(1, 351), size), range(1, 351))
    assert session.cuts == [CHAIN_FIELD_MAX_CHARS + 1] * 6 + [4 + 1]
    assert sum(r["chain"] is not None for r in rows) == 300


class _Rel:
    """`unit_of_work()` whose first `hold` entries block until they are cancelled."""

    def __init__(self, hold: int) -> None:
        self.hold, self.all_held = hold, asyncio.Event()

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        if self.hold:
            self.hold -= 1
            if not self.hold:
                self.all_held.set()
            await asyncio.Event().wait()

        async def execute(stmt: Any, params: dict[str, Any] | None = None) -> list[Any]:
            return []

        yield SimpleNamespace(session=SimpleNamespace(execute=execute))


async def _read(repo: SqlAlchemyAuditRepository, **kw: Any) -> list[dict[str, Any]]:
    params = set(inspect.signature(repo.query_page).parameters) - {"limit", "owner"}
    return await repo.query_page(**{**dict.fromkeys(params), "limit": 10, **kw})


async def _release(held: list[asyncio.Future[Any]]) -> None:
    for task in held:
        task.cancel()
    await asyncio.gather(*held, return_exceptions=True)


async def test_reads_past_the_process_cap_fail_closed_at_once() -> None:
    rel = _Rel(hold=2)
    repo = SqlAlchemyAuditRepository(rel, read_slots=2)  # type: ignore[arg-type]  # fake
    held = [asyncio.ensure_future(_read(repo)), asyncio.ensure_future(_read(repo, owner=True))]
    await asyncio.wait_for(rel.all_held.wait(), _WAIT_S)
    for owner in (False, True):
        with pytest.raises(AuditReadBusy) as err:
            await _read(repo, owner=owner)
        assert isinstance(err.value, StorageTierUnavailable)  # the router's 503
    await _release(held)
    assert await _read(repo) == [] and await _read(repo, owner=True) == []  # slots given back


async def test_one_read_slot_is_kept_for_the_owner() -> None:
    """Security review of #2443: two Managers at their per-user limit of 2 would hold all
    four slots; other users' reads now hold at most `read_slots - 1`, and the Owner reads."""
    rel = _Rel(hold=3)
    repo = SqlAlchemyAuditRepository(rel, read_slots=4)  # type: ignore[arg-type]  # fake
    held = [asyncio.ensure_future(_read(repo)) for _ in range(3)]
    await asyncio.wait_for(rel.all_held.wait(), _WAIT_S)
    with pytest.raises(AuditReadBusy):
        await _read(repo)  # a fourth read that is not the Owner's
    assert await _read(repo, owner=True) == []  # the kept slot
    await _release(held)


def test_a_cap_without_room_for_the_owner_and_others_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        SqlAlchemyAuditRepository(_Rel(hold=0), read_slots=1)  # type: ignore[arg-type]


def test_chain_renderings_are_the_verify_renderings() -> None:
    """The page check must hash what `verify` hashes: the same 15 expressions."""
    verify = str(mod._VERIFY_BATCH_SQL)
    chain = str(mod._CHAIN_ROWS_SQL)
    wrapped = re.findall(r"left\((.+?), :n\) AS (\w+)", chain)
    assert len(wrapped) == 15
    for expr, name in wrapped:
        assert f"{expr} AS {name}" in verify or (expr == name and f" {name}," in verify)
