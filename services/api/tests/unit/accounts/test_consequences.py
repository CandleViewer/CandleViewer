"""The consequence read (E27-S04 B2b, #898): CR-05 and the aggregate.

CR-05: the five store reads inside SCR-129's 1 s. The account is read first; then its keys (and
with them the exposure read), its grantees, its armed rules and its running algos run at once,
each under its store bound, and the exposure read gets what is left of the budget. A store read
that hits its bound fails the read closed. No wall time: reads park on `asyncio.Event`
barriers, the bound is a fake deadline the test fires, the clock a counter the fakes advance.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from candleviewer.accounts.consequences import (
    ARMED_LISTED,
    STORE_BOUND_S,
    AccountConsequences,
    AssignedUser,
    ConsequenceRead,
    StoreReadFailed,
    _first,
    position_id,
)
from candleviewer.accounts.errors import (
    AccountNotFoundError,
    AccountScopeDeniedError,
    AccountsError,
)
from candleviewer.accounts.exposure import (
    ExposureFailed,
    ExposureKnown,
    ExposureOutcome,
    ExposureUnknown,
)
from candleviewer.accounts.models import ApiKeyMetadata, ExchangeAccount, ExchangeEnv
from candleviewer.accounts.profile_repository import ArmedRule
from candleviewer.accounts.repository import AccountsRepository
from candleviewer.storage.repositories.accounts import (
    AccountsStoreScopeDeniedError,
    GranteeRow,
    GrantScope,
    OwnerScope,
)
from tests.unit.accounts.test_exposure_decision import _position
from tests.unit.accounts.test_exposure_read import ACCOUNT, K1, FakeDeadline, key

OWNER = OwnerScope(UUID(int=9))
USERS = (AssignedUser(UUID(int=7), "ann", "trade"),)
RULES = (ArmedRule(UUID(int=8), "breakout"),)
OPEN, FLAT = _position(stop_loss=Decimal("58000")), _position(symbol="ETHUSDT", size=Decimal("0"))
KNOWN = ExposureKnown(K1, (OPEN, FLAT), 3)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class Fakes:
    """Every port the read uses. `park` names reads that wait on their own `release` event;
    each read sets its `started` event and advances the clock by `cost[name]`."""

    def __init__(self, *park: str, outcome: ExposureOutcome = KNOWN) -> None:
        names = ("account", "keys", "grantees", "rules", "algos")
        self.started = {n: asyncio.Event() for n in names}
        self.release = {n: asyncio.Event() for n in names}
        for name in names:
            if name not in park:
                self.release[name].set()
        self.clock, self.cost = Clock(), dict.fromkeys(names, 0.0)
        self.fail: dict[str, Exception] = {}
        self.calls: list[tuple[str, Any]] = []
        self.within: list[float | None] = []
        self.rules: tuple[ArmedRule, ...] = RULES
        self.outcome = outcome

    async def _step(self, name: str, arg: Any) -> None:
        self.calls.append((name, arg))
        self.started[name].set()
        await self.release[name].wait()
        self.clock.now += self.cost[name]
        if name in self.fail:
            raise self.fail[name]

    async def get_account(self, scope: Any, account_id: UUID) -> ExchangeAccount:
        await self._step("account", scope)
        return ACCOUNT

    async def list_keys(self, scope: OwnerScope, account_id: UUID) -> tuple[ApiKeyMetadata, ...]:
        await self._step("keys", scope)
        return (key(K1),)

    async def list_grantees(self, scope: OwnerScope, account_id: UUID) -> tuple[AssignedUser, ...]:
        await self._step("grantees", scope)
        return USERS

    async def armed_on(self, account_id: UUID) -> tuple[ArmedRule, ...]:
        raise AssertionError("the summary lists through `covering`")

    async def covering(self, account_id: UUID, *, limit: int) -> tuple[ArmedRule, ...]:
        await self._step("rules", limit)
        return self.rules[:limit]

    async def running(self, account_id: UUID) -> int:
        await self._step("algos", account_id)
        return 2

    async def read(
        self, account: ExchangeAccount, keys: Sequence[ApiKeyMetadata], *, within_s: float | None
    ) -> ExposureOutcome:
        assert [k.id for k in keys] == [K1]
        self.within.append(within_s)
        return self.outcome

    def consequences(self, deadline: Any = asyncio.timeout) -> ConsequenceRead:
        return ConsequenceRead(
            self, self, self, self, env="demo", clock=self.clock, deadline=deadline
        )  # fmt: skip


async def _read(fakes: Fakes, **kw: Any) -> Any:
    scope = kw.pop("scope", OWNER)
    return await fakes.consequences(**kw).read(scope, OWNER, ACCOUNT.id)


async def test_read_aggregates_the_five_reads_open_positions_only() -> None:
    fakes = Fakes()
    got = await _read(fakes, scope=GrantScope(UUID(int=9), frozenset({ACCOUNT.id})))
    assert got == AccountConsequences(ACCOUNT.id, (OPEN,), 3, 2, USERS, RULES)
    assert sorted(name for name, _ in fakes.calls) == [
        "account", "algos", "grantees", "keys", "rules",
    ]  # fmt: skip
    seen = dict(fakes.calls)
    assert isinstance(seen["account"], GrantScope)  # the caller's scope; keys and users: owner
    assert (seen["keys"], seen["grantees"], seen["rules"]) == (OWNER, OWNER, ARMED_LISTED + 1)


async def test_read_four_store_reads_overlap_after_the_account() -> None:
    """A barrier: all four are in flight before any is released, so none waits on another."""
    fakes = Fakes("keys", "grantees", "rules", "algos")
    task = asyncio.create_task(_read(fakes))
    for name in ("keys", "grantees", "rules", "algos"):
        await fakes.started[name].wait()
    assert fakes.calls[0][0] == "account" and not task.done()
    for name in ("keys", "grantees", "rules", "algos"):
        fakes.release[name].set()
    assert isinstance(await task, AccountConsequences)


@pytest.mark.parametrize("parked", ["account", "keys", "grantees", "rules", "algos"])
async def test_read_parked_store_read_hits_its_bound_fails_closed(parked: str) -> None:
    fakes, deadline = Fakes(parked), FakeDeadline()
    task = asyncio.create_task(_read(fakes, deadline=deadline))
    await fakes.started[parked].wait()
    deadline.fire.set()
    with pytest.raises(StoreReadFailed):
        await task
    assert deadline.limits and set(deadline.limits) == {STORE_BOUND_S}


async def test_read_exposure_gets_what_is_left_of_the_budget() -> None:
    fakes = Fakes()
    fakes.cost.update(account=0.1, keys=0.15)
    await _read(fakes)
    assert fakes.within == [pytest.approx(0.75)]  # 1.0 s minus the account and the keys


async def test_read_budget_spent_exposure_read_still_asked_with_nothing_left() -> None:
    fakes = Fakes()
    fakes.cost.update(account=0.6, keys=0.6)
    await _read(fakes)
    assert fakes.within == [pytest.approx(-0.2)]  # ExposureRead reads none: every key `timeout`


@pytest.mark.parametrize(
    "outcome",
    [
        ExposureUnknown("leave_positions", ((K1, "auth_error"),)),
        ExposureUnknown("fix_key", ((K1, "ip_not_allowed"),)),
        ExposureFailed(503, "timeout", None, ((K1, "timeout"),)),
        ExposureFailed(502, "rate_limited", 10006, ((K1, "rate_limited"),)),
    ],
)
async def test_read_exposure_not_read_is_answered_as_decided(outcome: ExposureOutcome) -> None:
    assert await _read(Fakes(outcome=outcome)) == outcome


async def test_read_account_of_another_environment_is_not_found() -> None:
    fakes = Fakes()
    other = ACCOUNT.model_copy(update={"env": ExchangeEnv.LIVE})
    fakes.get_account = lambda scope, account_id: _returns(other)  # type: ignore[method-assign]
    with pytest.raises(AccountNotFoundError):
        await _read(fakes)
    assert fakes.calls == []  # nothing else is read


async def _returns(value: Any) -> Any:
    return value


@pytest.mark.parametrize("failing", ["account", "keys", "grantees", "rules", "algos"])
async def test_read_store_error_raised_as_it_is(failing: str) -> None:
    fakes = Fakes()
    fakes.fail[failing] = AccountsError("store error")
    with pytest.raises(AccountsError) as raised:
        await _read(fakes)
    assert raised.value is fakes.fail[failing]


async def test_read_more_armed_rules_than_listed_fails_closed() -> None:
    fakes = Fakes()
    fakes.rules = tuple(ArmedRule(UUID(int=i + 1), f"r{i}") for i in range(ARMED_LISTED + 1))
    with pytest.raises(StoreReadFailed):
        await _read(fakes)


def test_first_prefers_the_owner_gates_refusal() -> None:
    denied, down = AccountScopeDeniedError(), StoreReadFailed("bound")
    assert _first(ExceptionGroup("g", [down, ExceptionGroup("h", [denied])])) is denied
    assert _first(ExceptionGroup("g", [down, AccountsError("x")])) is down


def test_position_id_stable_per_account_symbol_and_index() -> None:
    again, hedged = _position(size=Decimal("2")), _position(position_idx=1)
    assert position_id(ACCOUNT.id, OPEN) == position_id(ACCOUNT.id, again)
    assert position_id(ACCOUNT.id, OPEN) != position_id(ACCOUNT.id, hedged)
    assert position_id(ACCOUNT.id, OPEN) != position_id(UUID(int=1), OPEN)
    assert position_id(ACCOUNT.id, OPEN).version == 5


def test_consequence_read_store_bound_must_sit_inside_the_budget() -> None:
    fakes = Fakes()
    with pytest.raises(ValueError):
        ConsequenceRead(fakes, fakes, fakes, fakes, env="demo", store_bound_s=1.0)


class _GranteeStore:
    def __init__(self, denied: bool = False) -> None:
        self.denied = denied

    async def list_grantees(self, scope: OwnerScope, account_id: UUID) -> tuple[GranteeRow, ...]:
        if self.denied:
            raise AccountsStoreScopeDeniedError
        return (GranteeRow(UUID(int=1), "ann", True), GranteeRow(UUID(int=2), "bob", False))


async def test_repository_list_grantees_levels_and_owner_gate() -> None:
    repo = AccountsRepository(_GranteeStore())  # type: ignore[arg-type]  # the one read used
    assert await repo.list_grantees(OWNER, ACCOUNT.id) == (
        AssignedUser(UUID(int=1), "ann", "trade"), AssignedUser(UUID(int=2), "bob", "read"),
    )  # fmt: skip
    refused = AccountsRepository(_GranteeStore(denied=True))  # type: ignore[arg-type]
    with pytest.raises(AccountScopeDeniedError):
        await refused.list_grantees(OWNER, ACCOUNT.id)
