"""#415 E17-X02: the production scope snapshot answers each owner from that owner's own grants.

A grant's freeze belongs to (owner, account), so a refresh of one owner never changes another
owner's answer, in the runtime check before every action (C-2.21) or in the API checks (C-12.4).
"""

from __future__ import annotations

import asyncio
import uuid
from uuid import UUID

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from candleviewer.rules.errors import ScopeForbiddenError
from candleviewer.rules.ir.models import RuleScope
from candleviewer.rules.scope import Reason, Resolution, ScopeInstanceRef, ScopeResolver
from candleviewer.rules.scope_state import ARM_LIVE, SnapshotScopeState

O1, O2, O3 = (uuid.UUID(int=i) for i in (1, 2, 3))
A, B, C = (uuid.UUID(int=i) for i in (10, 11, 12))
OWNERS, ACCOUNTS = (O1, O2, O3), (A, B, C)
Row = tuple[UUID, bool, bool]  # (account, can_view, frozen), as `SqlAlchemyScopeSource` returns
Own = tuple[list[Row], frozenset[str]]  # an owner's rows and permissions, as last loaded


class Source:
    def __init__(self) -> None:
        self.rows: dict[UUID, list[Row]] = {}
        self.perms: dict[UUID, frozenset[str]] = {}

    async def load_grants(self, owner: UUID) -> list[Row]:
        return list(self.rows.get(owner, []))

    async def load_permissions(self, owner: UUID) -> frozenset[str]:
        return self.perms.get(owner, frozenset())


class GatedSource(Source):
    """A `Source` whose permission load waits on `release` (open at first): a refresh in flight."""

    def __init__(self) -> None:
        super().__init__()
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.release.set()

    async def load_permissions(self, owner: UUID) -> frozenset[str]:
        self.entered.set()
        await self.release.wait()
        return await super().load_permissions(owner)


async def _noop(_a: str, _d: dict[str, str]) -> None:
    return None


def _scope(*accounts: UUID, envs: tuple[str, ...] = ("demo",)) -> RuleScope:
    return RuleScope.model_validate(
        {"level": "account", "account_ids": [str(a) for a in accounts], "environments": envs}
    )


def _check(r: ScopeResolver, owner: UUID, acct: UUID) -> Reason | None:
    inst = ScopeInstanceRef(f"BTCUSDT@{acct}", "BTCUSDT", acct)
    return r.check_action(_scope(acct), owner, "demo", inst)


async def _loaded(rows: dict[UUID, list[Row]], *order: UUID) -> tuple[SnapshotScopeState, Source]:
    src = Source()
    src.rows = rows
    state = SnapshotScopeState(src, "demo")
    for owner in order:
        await state.refresh(owner)
    return state, src


@pytest.mark.parametrize("order", [(O1, O2), (O2, O1)], ids=["frozen-first", "frozen-last"])
async def test_check_a_freeze_holds_for_its_owner_whichever_owner_is_refreshed_last(
    order: tuple[UUID, UUID],
) -> None:
    """O1 is frozen on A and live on B; O2 holds a live grant on A: O1 is stopped, O2 is not."""
    rows = {O1: [(A, True, True), (B, True, False)], O2: [(A, True, False)]}
    state, _src = await _loaded(rows, *order)
    r = ScopeResolver(state, _noop)
    assert (_check(r, O1, A), _check(r, O2, A), _check(r, O1, B)) == ("manager_frozen", None, None)
    one, two = r.resolve(_scope(A), O1, "demo"), r.resolve(_scope(A), O2, "demo")
    assert [s.reason for s in one.suppressed] == ["manager_frozen"] and not one.instances
    assert [i.account_id for i in two.instances] == [A] and not two.suppressed
    assert state.granted_accounts(O1) == {A, B}  # still named: manager_frozen, not grant_revoked


@pytest.mark.parametrize("drop", ["refresh", "invalidate"])
async def test_check_dropping_another_owners_grant_leaves_the_account_to_mine(drop: str) -> None:
    """O2's frozen grant on A goes away (a refresh without it, or a dropped entry): O1's live
    grant on A answers as O1's own in every reader."""
    state, src = await _loaded({O1: [(A, True, False)], O2: [(A, True, True)]}, O1, O2)
    if drop == "refresh":
        src.rows[O2] = []
        await state.refresh(O2)
    else:
        state.invalidate(O2)
    r = ScopeResolver(state, _noop)
    assert (_check(r, O1, A), _check(r, O2, A)) == (None, "grant_revoked")
    assert [i.account_id for i in r.resolve(_scope(A), O1, "demo").instances] == [A]
    await r.authorize_accounts(O1, [A])
    assert r.listable_accounts(O1) == [A]


async def test_resolve_reads_an_account_as_its_owner_sees_it() -> None:
    """O2's grant on C does not turn O1's ungranted C into a silent skip of another environment."""
    state, _src = await _loaded({O1: [(A, True, False)], O2: [(C, True, False)]}, O1, O2)
    res = ScopeResolver(state, _noop).resolve(_scope(A, C, envs=("demo", "testnet")), O1, "testnet")
    assert not res.instances  # A is a demo account: skipped in testnet
    assert [(s.instance.account_id, s.reason) for s in res.suppressed] == [(C, "grant_revoked")]


async def test_check_soft_revoked_rows_hold_no_grant_and_freeze_nothing() -> None:
    """O1 has only soft-revoked rows, one of them frozen: it holds no grant on any account and is
    not frozen as a whole."""
    state, _src = await _loaded({O1: [(A, False, True), (B, False, False)]}, O1)
    r = ScopeResolver(state, _noop)
    assert [_check(r, O1, a) for a in ACCOUNTS] == ["grant_revoked"] * 3
    assert not state.owner_frozen(O1) and not state.granted_accounts(O1)


async def test_check_account_missing_from_the_map_is_disabled_and_unlisted() -> None:
    """A grant on an account the account map does not hold is no access in any reader: `account()`
    needs the map's entry as well as the owner's row."""
    state, _src = await _loaded({O1: [(A, True, False), (B, True, False)]}, O1)
    del state._accounts[A]
    r = ScopeResolver(state, _noop)
    assert [_check(r, O1, a) for a in (A, B)] == ["account_disabled", None]
    with pytest.raises(ScopeForbiddenError):
        await r.authorize_accounts(O1, [A])
    assert r.listable_accounts(O1) == [B]


def _live(own: Own | None) -> dict[UUID, bool]:
    """The owner's view grants, each with its freeze, from its own rows."""
    return {a: frozen for a, view, frozen in (own[0] if own else []) if view}


def _expected(own: Own | None, acct: UUID) -> Reason | None:
    live = _live(own)
    if live and all(live.values()):
        return "manager_frozen"  # every live grant frozen: the owner is frozen as a whole
    if acct not in live:
        return "grant_revoked"
    return "manager_frozen" if live[acct] else None


def _summary(res: Resolution) -> tuple[object, ...]:
    suppressed = tuple((s.instance.key, s.reason) for s in res.suppressed)
    return res.env_skipped, tuple(i.key for i in res.instances), suppressed


async def _answers(r: ScopeResolver, owner: UUID) -> tuple[object, ...]:
    everywhere = _scope(*ACCOUNTS, envs=("demo", "testnet", "live"))
    allowed = []
    for a in ACCOUNTS:
        try:
            await r.authorize_accounts(owner, [a])
            allowed.append(a)
        except ScopeForbiddenError:
            pass
    resolutions = [_summary(r.resolve(everywhere, owner, e)) for e in ("demo", "testnet", "live")]
    checks = [_check(r, owner, a) for a in ACCOUNTS]
    return checks, resolutions, allowed, r.listable_accounts(owner)


async def _alone(owner: UUID, own: Own | None) -> ScopeResolver:
    """The same production state, loaded with `owner`'s own rows only."""
    src = Source()
    state = SnapshotScopeState(src, "demo", live_gate_open=lambda: True)
    if own is not None:
        src.rows[owner], src.perms[owner] = own
        await state.refresh(owner)
    return ScopeResolver(state, _noop)


def _rows(grants: tuple[tuple[bool, bool] | None, ...]) -> list[Row]:
    return [(a, g[0], g[1]) for a, g in zip(ACCOUNTS, grants, strict=True) if g is not None]


# Every refresh gives each account no grant, a live one, a frozen one or a soft-revoked one (frozen
# or not), so owners overlap on accounts often; None as a step's rows is an invalidation.
GRANT = st.sampled_from([None, (True, False), (True, True), (False, False), (False, True)])
STEP = st.tuples(
    st.sampled_from(OWNERS), st.none() | st.tuples(GRANT, GRANT, GRANT).map(_rows), st.booleans()
)


@settings(deadline=None)
@given(steps=st.lists(STEP, min_size=1, max_size=10))
async def test_every_owner_answers_from_its_own_rows_property(
    steps: list[tuple[UUID, list[Row] | None, bool]],
) -> None:
    """Random refreshes and drops of three owners: after every step, each owner's answers equal a
    recomputation from its own rows, and those of the same state loaded with its rows alone; the
    account map holds exactly the accounts some loaded owner holds a live grant on."""
    src = Source()
    state = SnapshotScopeState(src, "demo", live_gate_open=lambda: True)
    r = ScopeResolver(state, _noop)
    loaded: dict[UUID, Own] = {}
    for owner, rows, arm in steps:
        if rows is None:
            state.invalidate(owner)
            loaded.pop(owner, None)
        else:
            src.rows[owner], src.perms[owner] = rows, frozenset({ARM_LIVE}) if arm else frozenset()
            await state.refresh(owner)
            loaded[owner] = (rows, src.perms[owner])
        assert state._accounts.keys() == {a for own in loaded.values() for a in _live(own)}
        for o in OWNERS:
            own = loaded.get(o)
            assert state.granted_accounts(o) == _live(own).keys()  # a frozen grant stays named
            assert [_check(r, o, a) for a in ACCOUNTS] == [_expected(own, a) for a in ACCOUNTS]
            assert await _answers(r, o) == await _answers(await _alone(o, own), o)


async def test_refresh_in_flight_changes_no_answer_until_it_publishes() -> None:
    """O2's refresh waits in its permission load: until it ends, every answer of O1 and of O2 is the
    last published one; after it, O2's new freeze, grant and permission apply and O1's stay."""
    src = GatedSource()
    src.rows = {O1: [(A, True, True), (B, True, False)], O2: [(A, True, False), (B, True, False)]}
    src.perms = {O2: frozenset({ARM_LIVE})}
    state = SnapshotScopeState(src, "demo", live_gate_open=lambda: True)
    r = ScopeResolver(state, _noop)
    for owner in (O1, O2):
        await state.refresh(owner)
    before = [await _answers(r, o) for o in (O1, O2)]
    src.rows[O2] = [(A, True, True), (B, True, False), (C, True, False)]  # frozen on A, new on C
    src.perms[O2] = frozenset()  # and no arming permission
    src.entered.clear()
    src.release.clear()
    refresh = asyncio.create_task(state.refresh(O2))
    try:
        async with asyncio.timeout(5):
            await src.entered.wait()
        assert [await _answers(r, o) for o in (O1, O2)] == before
    finally:
        src.release.set()
        await refresh
    assert await _answers(r, O1) == before[0]
    assert [_check(r, O2, a) for a in ACCOUNTS] == ["manager_frozen", None, None]
    assert not state.can_arm_live(O2)
