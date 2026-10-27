"""Integration: `SqlAlchemyDefinitionStore` on Postgres 16 with the E28 seed (E28-T05 #909).

The database is `test_trade_groups_store_pg.py`'s, set up like production, renamed for the seed's
guard and loaded with the E28 world (#904): Core3 (E28-A, B, C) and Pair (E28-A, C) in demo,
E28-LIVE-MAIN in live. The store runs as `cv_app`, which holds no DELETE on definitions.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from candleviewer.storage.repositories import trade_group_definitions as port
from candleviewer.storage.repositories import trade_group_definitions_sqlalchemy as pg
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.integration.storage import test_trade_groups_store_pg as tg
from tests.integration.storage.test_trade_groups_store_pg import pg_dsn as bootstrapped
from tests.integration.storage.test_trade_groups_store_pg import rel

pytestmark = pytest.mark.integration
__all__ = ["bootstrapped", "rel"]  # the group store test's database and `cv_app` pool
Store = pg.SqlAlchemyDefinitionStore
Record = port.DefinitionRecord | None

_SEED = Path(__file__).resolve().parents[5] / "tests" / "fixtures" / "e28" / "seed.sql"
_E28 = "e28f0000-0000-4000-8000-{:0>12}"
OWNER, A, B, C, LIVE, CORE3, PAIR = (UUID(_E28.format(t)) for t in "1 d1 d2 d3 f1 a1 a2".split())
ME, ABC = OwnerScope(OWNER), frozenset({A, B, C})
_COUNT = (
    "SELECT (SELECT count(*) FROM trade_group_definitions WHERE id = %s), "
    "(SELECT count(*) FROM trade_group_definition_members WHERE definition_id = %s)"
)
_FREEZE = (
    "UPDATE user_account_access SET frozen = true, frozen_at = now() "
    "WHERE user_id = %s AND exchange_account_id = %s"
)


@pytest.fixture(scope="module")
def pg_dsn(bootstrapped: str) -> str:
    """`bootstrapped`'s database, renamed `*_test` for the seed's guard, seeded once."""
    base = bootstrapped.rsplit("/", 1)[0]
    tg._sql(base + "/postgres", "ALTER DATABASE candleviewer RENAME TO candleviewer_test")
    with tg._conn(base + "/candleviewer_test") as c:
        c.execute(_SEED.read_bytes())  # the file's own BEGIN ... COMMIT
    return base + "/candleviewer_test"


@pytest.fixture
def store(rel: SqlAlchemyRelationalRepository) -> Store:
    return pg.SqlAlchemyDefinitionStore(rel)


def _new(
    name: str, *members: UUID, env: Any = "demo", of: UUID | None = None, off: UUID | None = None
) -> port.NewDefinition:
    kept = tuple(port.NewMember(m, m != off) for m in members)
    return port.NewDefinition(id=of or uuid4(), name=name, env=env, members=kept, actor=OWNER)


def _member(account: UUID, enabled: bool = True) -> port.MemberRow:
    return port.MemberRow(account, enabled, "demo", True)


def _put(
    store: Store,
    new: port.NewDefinition,
    hook: port.DefinitionWriteAhead,
    at: datetime | None = None,
) -> Coroutine[Any, Any, Record]:
    return store.replace(ME, new.id, new, expected_updated_at=at, write_ahead=hook)


class _Hook:
    """The write-ahead hook: it keeps each (before, after) and, when told, refuses it."""

    def __init__(self, refuse: bool = False) -> None:
        self.seen: list[tuple[Record, Record]] = []
        self.refuse = refuse

    async def __call__(self, before: Record, after: Record) -> None:
        self.seen.append((before, after))
        if self.refuse:
            raise RuntimeError("the audit trail refused the record")


async def test_a_definition_is_written_with_its_record_and_a_failing_record_writes_nothing(
    store: Store, pg_dsn: str
) -> None:
    hook, refused, new, lost = _Hook(), _Hook(refuse=True), _new("Written", C, A), _new("Lost", A)
    made = await store.create(ME, new, write_ahead=hook)
    assert hook.seen == [(None, made)] and await store.get(ME, new.id) == made
    assert made.members == (_member(A), _member(C)) and made.definition.created_by == OWNER
    for write in (
        store.create(ME, lost, write_ahead=refused),
        _put(store, _new("Renamed", A, of=new.id), refused),
        store.soft_delete(ME, new.id, write_ahead=refused),
    ):
        with pytest.raises(RuntimeError, match="refused"):
            await write
    assert len(refused.seen) == 3 and tg._sql(pg_dsn, _COUNT, lost.id, lost.id) == [(0, 0)]
    assert await store.get(ME, new.id) == made


async def test_a_live_name_is_unique_in_any_letter_case_and_a_deleted_ones_name_is_free(
    store: Store,
) -> None:
    hook = _Hook()
    with pytest.raises(port.DefinitionConflictError) as taken:
        await store.create(ME, _new("cORE3", A), write_ahead=hook)
    first = await store.create(ME, _new("Freed", A), write_ahead=hook)
    assert await store.soft_delete(ME, first.definition.id, write_ahead=hook) == first
    assert await store.soft_delete(ME, first.definition.id, write_ahead=hook) is None
    again = await store.create(ME, _new("FREED", A), write_ahead=hook)
    assert taken.value.constraint == "ux_tgd_name" and again.definition.name == "FREED"
    assert hook.seen[1] == (first, None) and await store.get(ME, first.definition.id) is None


async def test_a_member_of_another_environment_is_refused_by_trg_tgdm_env(
    store: Store, pg_dsn: str
) -> None:
    """SR-E28-16, PF-T16, by create and by replace; a changed environment, a long name and an
    unknown account are refused by name too, and none writes anything."""
    hook, pair, mixed = _Hook(), await store.get(ME, PAIR), _new("Mixed", A, LIVE)
    for rule, write in (
        ("trg_tgdm_env", store.create(ME, mixed, write_ahead=hook)),
        ("trg_tgdm_env", _put(store, _new("Pair", A, C, LIVE, of=PAIR), hook)),
        ("trg_tgd_write_once", _put(store, _new("Pair", A, C, env="live", of=PAIR), hook)),
        ("tgd_name", store.create(ME, _new("n" * 81, A), write_ahead=hook)),
        ("trade_group_definition_members_exchange_account_id_fkey",
         store.create(ME, _new("Ghost", uuid4()), write_ahead=hook)),
    ):  # fmt: skip
        with pytest.raises(port.DefinitionRuleError) as refused:
            await write
        assert refused.value.rule == rule
    assert hook.seen == [] and tg._sql(pg_dsn, _COUNT, mixed.id, mixed.id) == [(0, 0)]
    assert await store.get(ME, PAIR) == pair


async def test_a_soft_deleted_definition_takes_no_member(store: Store, pg_dsn: str) -> None:
    """SEC-2-03: a replace of a deleted definition answers `None`, and one racing a delete waits
    on its row lock, then answers `None`; neither adds a member."""
    hook, held, release = _Hook(), asyncio.Event(), asyncio.Event()
    gone = (await store.create(ME, _new("Gone", A), write_ahead=hook)).definition.id
    raced = await store.create(ME, _new("Raced", A), write_ahead=hook)
    await store.soft_delete(ME, gone, write_ahead=hook)
    assert await _put(store, _new("Gone", A, C, of=gone), hook) is None

    async def hold(before: Record, after: Record) -> None:
        held.set()
        await release.wait()

    async with asyncio.timeout(15):
        deleting = asyncio.create_task(store.soft_delete(ME, raced.definition.id, write_ahead=hold))
        await held.wait()  # the delete holds the row lock until its record is written
        racing = _new("Raced", A, C, of=raced.definition.id)
        replacing = asyncio.create_task(_put(store, racing, hook))
        try:
            await tg._wait_until_blocked(pg_dsn, "trade-groups-it")
            release.set()
            assert await deleting == raced and await replacing is None
        finally:
            await tg._settle(deleting, replacing)
    for definition_id in (gone, racing.id):
        assert tg._sql(pg_dsn, _COUNT, definition_id, definition_id) == [(1, 1)]
    assert len(hook.seen) == 3


async def test_a_replace_over_a_stale_updated_at_writes_nothing(store: Store) -> None:
    hook = _Hook()
    made = await store.create(ME, _new("Stale", A, C), write_ahead=hook)
    at, made_id = made.definition.updated_at, made.definition.id
    now = await _put(store, _new("Stale 2", A, of=made_id, off=A), hook, at)
    assert now is not None and hook.seen[-1] == (made, now) and now.definition.updated_at > at
    assert (now.definition.name, now.members) == ("Stale 2", (_member(A, enabled=False),))
    with pytest.raises(port.DefinitionStaleError):
        await _put(store, _new("Stale 3", A, C, of=made_id), hook, at)
    other = _new("Other", A)  # another definition's id: refused before any statement
    with pytest.raises(ValueError, match="replaced"):
        await store.replace(ME, made_id, other, expected_updated_at=None, write_ahead=hook)
    assert await store.get(ME, made_id) == now and len(hook.seen) == 2


async def test_a_grant_reads_only_definitions_whose_every_member_it_sees(
    store: Store, pg_dsn: str
) -> None:
    """SR-E28-21: Core3 is hidden without a grant on E28-B, with B's grant frozen and with B
    outside the scope; Pair reads with both members; the Owner reads both."""
    core3, pair = await store.get(ME, CORE3), await store.get(ME, PAIR)
    assert core3 is not None and pair is not None and len(core3.members) == 3
    no_b, frozen_b, all_three = tg._user(pg_dsn), tg._user(pg_dsn), tg._user(pg_dsn)
    for user, accounts in ((no_b, (A, C)), (frozen_b, ABC), (all_three, ABC)):
        for account in accounts:
            tg._grant(pg_dsn, user, account)
    tg._sql(pg_dsn, _FREEZE, frozen_b, B)
    narrowed = GrantScope(all_three, frozenset({A, C}))
    for scope in (GrantScope(no_b, ABC), GrantScope(frozen_b, ABC), narrowed):
        assert (await store.get(scope, CORE3), await store.get(scope, PAIR)) == (None, pair)
    full = GrantScope(all_three, ABC)
    assert (await store.get(full, CORE3), await store.get(full, PAIR)) == (core3, pair)
    empty = await store.create(ME, _new("Empty"), write_ahead=_Hook())  # a member-less one
    assert empty.members == () and await store.get(full, empty.definition.id) is None
    assert await store.get(GrantScope(all_three, frozenset()), PAIR) is None


async def test_a_non_owner_scope_cannot_write(store: Store, pg_dsn: str) -> None:
    """The live-owner gate comes first: nothing is read, written or written ahead."""
    hook, pair, stranger, denied = _Hook(), await store.get(ME, PAIR), tg._user(pg_dsn), _new("No")
    tg._grant(pg_dsn, stranger, A)
    them, grant = OwnerScope(stranger), GrantScope(stranger, frozenset({A}))
    for attempt in (
        store.create(them, denied, write_ahead=hook),
        store.replace(
            them, PAIR, _new("Taken", of=PAIR), expected_updated_at=None, write_ahead=hook
        ),
        store.soft_delete(them, PAIR, write_ahead=hook),
        store.get(them, PAIR),
        store.create(grant, denied, write_ahead=hook),  # type: ignore[arg-type]  # not an owner's
    ):
        with pytest.raises(port.DefinitionScopeDeniedError):
            await attempt
    assert hook.seen == [] and tg._sql(pg_dsn, _COUNT, denied.id, denied.id) == [(0, 0)]
    assert await store.get(ME, PAIR) == pair
