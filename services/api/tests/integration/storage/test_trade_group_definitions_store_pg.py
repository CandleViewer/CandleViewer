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
_DISABLE = "UPDATE exchange_accounts SET is_enabled = false, trading_enabled = true WHERE id = %s"
_WRITER = "SELECT updated_by, deleted_at IS NOT NULL FROM trade_group_definitions WHERE id = %s"


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
    return port.NewDefinition(id=of or uuid4(), name=name, env=env, members=kept)


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


@pytest.mark.parametrize(
    ("error", "name", "new"),
    [
        (port.DefinitionRuleError, "trg_tgdm_env", _new("Mixed", A, LIVE)),
        (port.DefinitionRuleError, "trg_tgdm_env", _new("Pair", A, C, LIVE, of=PAIR)),
        (port.DefinitionRuleError, "trg_tgd_write_once", _new("Pair", A, C, env="live", of=PAIR)),
        (port.DefinitionRuleError, "tgd_name", _new("n" * 81, A)),
        (port.DefinitionRuleError, "account_not_live", _new("Ghost", uuid4())),
        (port.DefinitionConflictError, "trade_group_definitions_pkey", _new("Taken", A, of=CORE3)),
    ],
)
async def test_a_refused_write_leaves_by_its_name_and_writes_nothing(
    store: Store, pg_dsn: str, error: type[Exception], name: str, new: port.NewDefinition
) -> None:
    """SR-E28-16, PF-T16 by create and by replace, and four more refusals: none writes anything."""
    hook, kept = _Hook(), [await store.get(ME, d) for d in (CORE3, PAIR)]
    write = _put(store, new, hook) if new.id == PAIR else store.create(ME, new, write_ahead=hook)
    with pytest.raises(error) as refused:
        await write
    assert refused.value.args == (name,) and hook.seen == []
    assert [await store.get(ME, d) for d in (CORE3, PAIR)] == kept
    assert new.id in (CORE3, PAIR) or tg._sql(pg_dsn, _COUNT, new.id, new.id) == [(0, 0)]


async def test_a_member_account_must_be_live_and_a_disabled_one_reads_disabled(
    store: Store, pg_dsn: str
) -> None:
    """Soft-deleted, it refuses a create and a replace, writing nothing; disabled, it is live."""
    hook, gone, off = _Hook(), tg._account(pg_dsn), tg._account(pg_dsn)
    tg._sql(pg_dsn, "UPDATE exchange_accounts SET deleted_at = now() WHERE id = %s", gone)
    tg._sql(pg_dsn, _DISABLE, off)  # trading left on: a read of the wrong column would show
    pair, late = await store.get(ME, PAIR), _new("Late", A, gone)
    for write in (
        store.create(ME, late, write_ahead=hook),
        _put(store, _new("Pair", gone, of=PAIR), hook),
    ):
        with pytest.raises(port.DefinitionRuleError, match=r"^account_not_live$"):
            await write
    assert hook.seen == [] and tg._sql(pg_dsn, _COUNT, late.id, late.id) == [(0, 0)]
    made = await store.create(ME, _new("Off", A, off), write_ahead=hook)
    assert {m.exchange_account_id: m.account_enabled for m in made.members} == {A: True, off: False}
    assert await store.get(ME, PAIR) == pair


async def test_a_soft_deleted_definition_takes_no_member(store: Store, pg_dsn: str) -> None:
    """SEC-2-03 (21 Sec.3.3.3a): a replace of a deleted definition answers `None`, and one racing
    a delete waits on its row lock, then answers `None`; neither adds a member."""
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
    hook, pair = _Hook(), await store.get(ME, PAIR)  # another definition, whose members stay
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
    assert await store.get(ME, PAIR) == pair


async def test_the_stored_writer_is_the_owner_the_gate_checked(store: Store, pg_dsn: str) -> None:
    """The scope names the writer: another Owner's replace and then a soft delete store theirs."""
    hook, other, new = _Hook(), OwnerScope(tg._user(pg_dsn, "owner")), _new("Writers", A)
    await store.create(ME, new, write_ahead=hook)
    now = await store.replace(other, new.id, new, expected_updated_at=None, write_ahead=hook)
    assert now is not None and now.definition.created_by == OWNER
    assert now.definition.updated_by == other.user_id
    await store.soft_delete(ME, new.id, write_ahead=hook)
    assert tg._sql(pg_dsn, _WRITER, new.id) == [(OWNER, True)]


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
    """The live-owner gate comes first, and a grant cannot write even a definition it sees."""
    hook, pair, stranger = _Hook(), await store.get(ME, PAIR), tg._user(pg_dsn)
    tg._grant(pg_dsn, stranger, A)
    them, grant, denied = OwnerScope(stranger), GrantScope(stranger, frozenset({A})), _new("No", A)
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
