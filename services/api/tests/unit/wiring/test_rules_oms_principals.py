"""E35-T11 slice 3b: check 5's principal reads at the composition root (24 §11.5 "The principal";
the E35 threat model's RE-S1, RE-E1, RE-E3, RE-E6; E35-FR-01; BQ-3 of #863, BQ-6 as ruled).

`RulePrincipals` serves each user's view from memory, refreshed every 250 ms by user id (never a
session) from the identity read and the trade grants, the order route's own decision over the
process's environment. The checks here are the executor's own (`Gates`), over these views, so a
view that refuses here refuses at dispatch. No sleeps: a frozen clock, a sleep that waits on an
event the test sets, and a hang that nobody ends, under a bound the test sets to 0.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Collection
from dataclasses import dataclass, field
from typing import Any

import pytest
from structlog.testing import capture_logs

from candleviewer.auth.generated_permissions import Permission
from candleviewer.auth.scopes import AccountGrant, PrincipalSnapshot
from candleviewer.rules.executor.gates import PRINCIPAL_MAX_AGE_S, Gates
from candleviewer.rules.executor.handlers import HANDLERS
from candleviewer.rules.ir.models import Action, RuleScope
from candleviewer.rules.scope import ActionRequest, ScopeInstanceRef
from candleviewer.rules_oms_principals import (
    PRINCIPAL_READ_TIMEOUT_S,
    PRINCIPAL_REFRESH_S,
    IdentityPrincipalSource,
    RulePrincipals,
    principal_view,
)
from candleviewer.rules_oms_requests import rule_origin, submit_context
from tests.rules.executor.request_builders import action_request

OWNER, ARMER = uuid.UUID(int=0xA1), uuid.UUID(int=0xA2)
A, B, C, ELSEWHERE = (uuid.UUID(int=i) for i in (0xB1, 0xB2, 0xB3, 0xB9))
ENVIRONMENT = frozenset({A, B, C})  # ELSEWHERE is another environment's account
RULE = str(uuid.UUID(int=0x7))
WRITE = frozenset({Permission.ORDERS_WRITE})


def owner_role(user: uuid.UUID, permissions: frozenset[Permission] = WRITE) -> PrincipalSnapshot:
    return PrincipalSnapshot(user, frozenset({"owner"}), permissions)


def manager(user: uuid.UUID, *grants: AccountGrant) -> PrincipalSnapshot:
    return PrincipalSnapshot(user, frozenset({"manager"}), WRITE, tuple(grants))


def trade(account: uuid.UUID) -> AccountGrant:
    return AccountGrant(account, can_view=True, can_trade=True, frozen=False)


class Clock:
    def __init__(self) -> None:
        self.t = 1_000.0

    def __call__(self) -> float:
        return self.t


@dataclass
class Source:
    """`PrincipalSource` in memory: each user's snapshot (`None`: cannot act; absent: no such
    user), the environment's accounts, and the reads that fail or hang."""

    users: dict[uuid.UUID, PrincipalSnapshot | None] = field(default_factory=dict)
    accounts: frozenset[uuid.UUID] = ENVIRONMENT
    failing: set[uuid.UUID | None] = field(default_factory=set)  # None: the environment's read
    hanging: set[uuid.UUID] = field(default_factory=set)
    asked: list[uuid.UUID] = field(default_factory=list)

    async def snapshot(self, user_id: uuid.UUID) -> PrincipalSnapshot | None:
        self.asked.append(user_id)
        if user_id in self.hanging:
            await asyncio.Event().wait()
        if user_id in self.failing:
            raise ConnectionError("the identity store refused the read")
        if user_id not in self.users:
            raise LookupError("no such user")
        return self.users[user_id]

    async def live_accounts(self) -> frozenset[uuid.UUID]:
        if None in self.failing:
            raise ConnectionError("the account store refused the read")
        return self.accounts


def request(account: uuid.UUID | None = A, **over: Any) -> ActionRequest:
    """An armed `place_order` of `OWNER`'s rule, armed by `ARMER`, on `account`."""
    action = Action.model_validate(
        {"node_id": "a1", "type": "place_order", "params": {}} | over.pop("action", {})
    )
    instance = ScopeInstanceRef(f"BTCUSDT@{account}", "BTCUSDT", account)
    scope = RuleScope.model_validate({"level": "account"})
    base = {
        "action_type": "place_order",
        "payload": action,
        "rule_id": RULE,
        "armed_by": str(ARMER),
    }
    return action_request(scope, OWNER, instance, **(base | over))


async def read(source: Source, clock: Clock, **kw: Any) -> RulePrincipals:
    principals = RulePrincipals(source, clock=clock, **kw)
    await principals.refresh((OWNER, ARMER))
    return principals


def check_five(
    principals: RulePrincipals, clock: Clock, account: uuid.UUID | None = A, *, wide: bool = False
) -> str | None:
    refused, _, _ = Gates(principal=principals).principal(
        request(account), account, all_accounts=wide, now=clock()
    )
    return refused


async def test_owner_is_the_oms_principal_and_armer_is_recorded() -> None:
    """G "The owner is the OMS principal and the armer is recorded (RE-S1, E35-FR-01)": a rule
    owned by a Manager and armed by the Owner is checked against both users' views, read by id;
    the request the OMS gets names the owner as its principal, with the owner's role and no
    session, and its origin the armer with the armer's role."""
    clock = Clock()
    source = Source({OWNER: manager(OWNER, trade(A)), ARMER: owner_role(ARMER)})
    principals = await read(source, clock)
    assert sorted(source.asked) == [OWNER, ARMER]  # by user id, each once a cycle
    assert check_five(principals, clock) is None
    owner, armer = principals.principal(OWNER), principals.principal(ARMER)
    assert owner is not None and armer is not None
    assert (owner.role, owner.is_owner, armer.role, armer.is_owner) == (
        "manager", False, "owner", True
    )  # fmt: skip
    req = request()
    context = submit_context(
        owner=req.owner, owner_role=owner.role or "", origin=rule_origin(req, armer.role),
        client_ref=str(uuid.UUID(int=0xC1)), request_sha256="ab" * 32,
    )  # fmt: skip
    assert (context.actor.user_id, context.actor.role) == (OWNER, "manager")
    assert (context.actor.session_id, context.actor.ip, context.request_id) == (None, None, None)
    assert context.origin is not None
    assert (context.origin.armed_by, context.origin.armed_by_role) == (ARMER, "owner")


@pytest.mark.parametrize("who", ["owner", "armer"])
@pytest.mark.parametrize("state", ["disabled", "deleted"])
async def test_a_disabled_owner_or_armer_blocks_the_action(who: str, state: str) -> None:
    """G same (forbidden role): a user who cannot act (not active, or a role outside the system
    set: `identity_snapshot` answers `None`) or that the store no longer holds is an inactive
    view at once, and the action is refused `permission`."""
    clock = Clock()
    source = Source({OWNER: owner_role(OWNER), ARMER: owner_role(ARMER)})
    user = OWNER if who == "owner" else ARMER
    if state == "disabled":
        source.users[user] = None
    else:
        del source.users[user]
    principals = await read(source, clock)
    view = principals.principal(user)
    assert view is not None and not view.active and view.trade_accounts == frozenset()
    assert check_five(principals, clock) == "permission"
    assert check_five(principals, clock, None) == "permission"  # an account-less action too


@pytest.mark.parametrize(
    "grant",
    [
        AccountGrant(A, can_view=True, can_trade=False, frozen=False),
        AccountGrant(A, can_view=True, can_trade=True, frozen=True),
        AccountGrant(A, can_view=False, can_trade=True, frozen=False),
    ],
    ids=["view-only", "frozen", "soft-revoked"],
)
async def test_a_view_only_or_frozen_grant_blocks_the_action(grant: AccountGrant) -> None:
    """G same (forbidden role): the order route's decision with `requires_trade` admits no
    view-only, frozen or revoked grant, so the account is not the owner's to trade."""
    clock = Clock()
    principals = await read(Source({OWNER: manager(OWNER, grant), ARMER: owner_role(ARMER)}), clock)
    owner = principals.principal(OWNER)
    assert owner is not None and owner.active and owner.trade_accounts == frozenset()
    assert check_five(principals, clock) == "permission"


async def test_principal_read_failure_blocks_the_action() -> None:
    """G same: a user never read is refused; a read that fails keeps the user's last view, which
    serves until it is older than the executor's one-second bound and is refused after."""
    clock = Clock()
    source = Source({OWNER: owner_role(OWNER), ARMER: owner_role(ARMER)})
    assert check_five(RulePrincipals(source, clock=clock), clock) == "permission"  # never read
    principals = await read(source, clock)
    source.failing.add(ARMER)
    clock.t += 0.6
    with capture_logs() as logs:
        await principals.refresh((OWNER, ARMER))
        await principals.refresh((OWNER, ARMER))  # warned once until it answers again
    assert check_five(principals, clock) is None  # the armer's view is 0.6 s old
    clock.t += 0.4
    assert check_five(principals, clock) is None  # one second old: still within the bound
    clock.t += 0.001  # one second and a millisecond: past the ruled bound (24 §11.5)
    assert check_five(principals, clock) == "permission" and PRINCIPAL_MAX_AGE_S == 1.0
    unread = [e for e in logs if e["event"] == "rules.principal_unread"]
    assert [(e["user"], e["error"]) for e in unread] == [(str(ARMER), "ConnectionError")]


async def test_a_read_past_its_bound_leaves_the_last_view_to_age_out() -> None:
    """BQ-6 as ruled: each read stays bounded; one past its bound leaves the old view to age out,
    so the action fails closed, while the other user's view is refreshed beside it."""
    clock = Clock()
    source = Source({OWNER: owner_role(OWNER), ARMER: owner_role(ARMER)})
    principals = await read(source, clock, read_timeout_s=0.0)
    first = principals.principal(ARMER)
    source.hanging.add(ARMER)
    clock.t += 0.5
    async with asyncio.timeout(5):  # a guard: the bound, not this, ends the hang
        await principals.refresh((OWNER, ARMER))
    owner = principals.principal(OWNER)
    assert principals.principal(ARMER) is first and owner is not None and owner.read_at == clock.t
    clock.t += 0.51
    assert check_five(principals, clock) == "permission"
    assert PRINCIPAL_READ_TIMEOUT_S == 2.0


async def test_an_unread_environment_ages_every_view_out() -> None:
    clock = Clock()
    source = Source({OWNER: owner_role(OWNER), ARMER: owner_role(ARMER)})
    principals = await read(source, clock)
    source.failing.add(None)
    clock.t += 0.75
    await principals.refresh((OWNER, ARMER))
    assert source.asked.count(OWNER) == 1  # no user is read in a cycle that read no accounts
    clock.t += 0.26
    assert check_five(principals, clock) == "permission"


# fmt: off
async def test_all_accounts_resolves_through_the_real_principal_reads_and_needs_the_owner_role_at_execution() -> None:  # noqa: E501 -- the ticket's test name (#5003)
    """G "all_accounts resolves at fire time to the owner and armer intersection and needs the
    Owner role at execution (BQ-3, C-12.4)": the accounts both users' current grants allow, read
    by id, never their union, sorted; and a principal without the Owner role is refused at
    execution, as at save."""
    clock = Clock()
    armer = manager(ARMER, trade(B), trade(C), trade(ELSEWHERE))
    principals = await read(Source({OWNER: owner_role(OWNER), ARMER: armer}), clock)
    gates, spec = Gates(principal=principals), HANDLERS["place_order"]
    wide = request(action={"targets": "all_accounts"})
    assert gates.resolve_targets(wide, spec, clock()) == ((B, C), True)
    assert check_five(principals, clock, B, wide=True) is None
    assert check_five(principals, clock, A, wide=True) == "permission"  # the owner's alone
    demoted = await read(Source({OWNER: manager(OWNER, trade(B)), ARMER: owner_role(ARMER)}), clock)
    assert Gates(principal=demoted).resolve_targets(wide, spec, clock()) == ((B,), True)
    assert check_five(demoted, clock, B, wide=True) == "permission"  # no Owner role now
    assert check_five(demoted, clock, B) is None  # an action that names its account needs none
# fmt: on


# fmt: off
async def test_an_action_on_an_account_outside_the_owner_armer_intersection_never_reaches_the_oms() -> None:  # noqa: E501 -- the plan's test name (#5003)
    """The cross-account case: each user may trade one account the other may not; an action on
    either is refused at check 5, before anything is written ahead or sent."""
    clock = Clock()
    source = Source({OWNER: manager(OWNER, trade(A)), ARMER: manager(ARMER, trade(B))})
    principals = await read(source, clock)
    for account in (A, B, C, ELSEWHERE):
        assert check_five(principals, clock, account) == "permission"
# fmt: on


async def test_an_owner_admits_every_account_of_the_environment_and_a_manager_its_grants() -> None:
    clock = Clock()
    source = Source({OWNER: owner_role(OWNER), ARMER: manager(ARMER, trade(A), trade(ELSEWHERE))})
    principals = await read(source, clock)
    owner, armer = principals.principal(OWNER), principals.principal(ARMER)
    assert owner is not None and owner.trade_accounts == ENVIRONMENT
    assert armer is not None and armer.trade_accounts == frozenset({A})  # its environment's only
    no_write = principal_view(OWNER, owner_role(OWNER, frozenset()), ENVIRONMENT, clock())
    assert no_write.active and no_write.trade_accounts == frozenset()  # no `orders:write`


async def test_a_user_no_longer_named_is_forgotten() -> None:
    clock = Clock()
    principals = await read(Source({OWNER: owner_role(OWNER), ARMER: owner_role(ARMER)}), clock)
    await principals.refresh((OWNER,))
    assert principals.principal(ARMER) is None and principals.principal(OWNER) is not None


class Steps:
    """The refresh task's sleep: each wait is recorded, then held until the test lets it go."""

    def __init__(self) -> None:
        self.waits: list[float] = []
        self.slept = asyncio.Event()
        self.go = asyncio.Event()

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)
        self.slept.set()
        await self.go.wait()
        self.go.clear()

    async def next(self) -> None:
        self.slept.clear()
        self.go.set()
        async with asyncio.timeout(5):
            await self.slept.wait()


async def test_the_refresh_runs_every_quarter_second_inside_the_age_bound() -> None:
    """BQ-6 as ruled: a cycle every 250 ms from its start, well inside the one-second bound."""
    clock, steps = Clock(), Steps()
    source = Source({OWNER: owner_role(OWNER), ARMER: owner_role(ARMER)})
    principals = RulePrincipals(source, clock=clock, sleep=steps)
    named: Callable[[], Collection[uuid.UUID]] = lambda: (OWNER, ARMER)  # noqa: E731
    principals.start(named)
    try:
        async with asyncio.timeout(5):
            await steps.slept.wait()
        clock.t += 0.1
        await steps.next()
        assert steps.waits == [PRINCIPAL_REFRESH_S, PRINCIPAL_REFRESH_S]
        assert PRINCIPAL_REFRESH_S * 4 <= PRINCIPAL_MAX_AGE_S
        assert source.asked.count(OWNER) == 2
    finally:
        with capture_logs() as logs:
            await principals.stop()
    assert principals.principal(OWNER) is None  # a stop forgets every view
    assert not [e for e in logs if e.get("cv_page")]  # a stop pages nothing


async def test_a_second_start_runs_no_second_refresh_task() -> None:
    """`start` spawns the refresh once until `stop()`: a second call keeps the one task."""
    clock, steps = Clock(), Steps()
    source = Source({OWNER: owner_role(OWNER), ARMER: owner_role(ARMER)})
    principals = RulePrincipals(source, clock=clock, sleep=steps)
    named: Callable[[], Collection[uuid.UUID]] = lambda: (OWNER, ARMER)  # noqa: E731
    principals.start(named)
    principals.start(named)
    try:
        running = [t for t in asyncio.all_tasks() if t.get_name() == "rule-principals"]
        assert len(running) == 1
    finally:
        await principals.stop()
    assert not [t for t in asyncio.all_tasks() if t.get_name() == "rule-principals"]


async def test_a_stop_before_any_start_forgets_every_view() -> None:
    clock = Clock()
    principals = await read(Source({OWNER: owner_role(OWNER), ARMER: owner_role(ARMER)}), clock)
    assert check_five(principals, clock) is None
    await principals.stop()
    assert principals.principal(OWNER) is None and principals.principal(ARMER) is None
    assert check_five(principals, clock) == "permission"


async def test_a_stopped_refresh_ages_every_snapshot_out() -> None:
    """The task's end other than by `stop()` is logged CRITICAL and paged once; no view is read
    again, so each ages out and the action is refused (fail closed)."""
    clock, steps = Clock(), Steps()
    source = Source({OWNER: owner_role(OWNER), ARMER: owner_role(ARMER)})
    principals = RulePrincipals(source, clock=clock, sleep=steps)
    cycles: list[int] = []

    def named() -> Collection[uuid.UUID]:
        cycles.append(len(cycles))
        if len(cycles) > 1:  # the second cycle meets a fault
            raise RuntimeError("the rule list cannot be read")
        return (OWNER, ARMER)

    with capture_logs() as logs:
        principals.start(named)
        task = principals._task
        assert task is not None
        async with asyncio.timeout(5):
            await steps.slept.wait()
            steps.go.set()
            await asyncio.wait({task})
    assert check_five(principals, clock) is None  # the views read before the end still serve
    clock.t += 1.001  # past the one-second bound: every view aged out
    assert check_five(principals, clock) == "permission"
    ended = [e for e in logs if e["event"] == "rules.principals_ended"]
    assert ended == [
        {"event": "rules.principals_ended", "log_level": "critical", "cv_page": True,
         "error": "RuntimeError"}
    ]  # fmt: skip
    await principals.stop()


@dataclass
class Identity:
    users: dict[str, dict[str, Any]]

    async def user(self, user_id: str) -> dict[str, Any]:
        if user_id not in self.users:
            raise LookupError(user_id)
        return self.users[user_id]

    async def session_info(self, user_id: str) -> dict[str, Any]:
        return {"permissions": ["orders:write", "not:a_permission"]}


@dataclass
class Grants:
    rows: dict[uuid.UUID, list[tuple[uuid.UUID, bool, bool, bool]]]
    asked: list[object] = field(default_factory=list)

    async def load_trade_grants(
        self, user_id: uuid.UUID
    ) -> list[tuple[uuid.UUID, bool, bool, bool]]:
        self.asked.append(user_id)
        return self.rows.get(user_id, [])

    async def load_environment_accounts(self, environment: str) -> frozenset[uuid.UUID]:
        self.asked.append(environment)
        return ENVIRONMENT


async def test_the_identity_source_reads_by_user_id_and_never_an_owners_grants() -> None:
    """E35-FR-01: the identity read and the trade grants by user id, as the order route reads
    them; an Owner's grants are every account, so they are not read; a user who is not active
    cannot act, and one the store does not hold is `LookupError`."""
    identity = Identity({
        str(OWNER): {"status": "active", "roles": ["owner"]},
        str(ARMER): {"status": "active", "roles": ["manager"]},
        str(B): {"status": "disabled", "roles": ["manager"]},
    })  # fmt: skip
    grants = Grants({ARMER: [(A, True, True, False)]})
    source = IdentityPrincipalSource(identity, grants, "demo")
    owner, armer = await source.snapshot(OWNER), await source.snapshot(ARMER)
    assert owner is not None and owner.is_owner and owner.account_grants == ()
    assert armer is not None and armer.account_grants == (trade(A),)
    assert armer.permissions == WRITE  # an unknown code is dropped
    assert await source.snapshot(B) is None
    with pytest.raises(LookupError):
        await source.snapshot(C)
    assert await source.live_accounts() == ENVIRONMENT
    assert grants.asked == [ARMER, "demo"]
