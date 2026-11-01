"""E35-T10 (#5002) slice 2e, BQ-3: the scope re-check reads each account's own environment.

`SnapshotScopeState` keeps each granted account's environment from the scope source's own read of
`exchange_accounts.env`; `ScopeResolver.check_action`, the action's re-check (24 §11.5 check 4),
refuses `environment` for an account of another environment than the process, and for one whose
environment was not read (fail closed, C-2.11).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from candleviewer.rules.ir.models import RuleScope
from candleviewer.rules.scope import ScopeInstanceRef, ScopeResolver
from candleviewer.rules.scope_state import SnapshotScopeState

OWNER = uuid.UUID(int=0xA1)
DEMO, TESTNET, UNREAD = uuid.UUID(int=0xB1), uuid.UUID(int=0xB2), uuid.UUID(int=0xB3)
SCOPE = RuleScope.model_validate({"level": "account"})


class _Source:
    """The owner's grants on three accounts: one of the process's environment, one of another,
    and one whose environment the read does not name (deleted, or not read)."""

    def __init__(self) -> None:
        self.asked: list[list[uuid.UUID]] = []
        self.envs = {DEMO: "demo", TESTNET: "testnet"}

    async def load_grants(self, owner: uuid.UUID) -> list[tuple[uuid.UUID, bool, bool]]:
        return [(DEMO, True, False), (TESTNET, True, False), (UNREAD, True, False)]

    async def load_permissions(self, owner: uuid.UUID) -> frozenset[str]:
        return frozenset()

    async def load_account_environments(
        self, account_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, str]:
        self.asked.append(list(account_ids))
        return dict(self.envs)


async def _resolver() -> tuple[ScopeResolver, _Source, SnapshotScopeState]:
    async def audit(event: str, data: dict[str, str]) -> None:
        return None

    source = _Source()
    state = SnapshotScopeState(source)
    await state.refresh(OWNER)
    return ScopeResolver(state, audit), source, state


def _on(account: uuid.UUID) -> ScopeInstanceRef:
    return ScopeInstanceRef(f"BTCUSDT@{account}", "BTCUSDT", account)


async def test_check_action_refuses_an_account_of_another_environment() -> None:
    resolver, source, _ = await _resolver()
    assert source.asked == [[DEMO, TESTNET, UNREAD]]  # one read, of the granted accounts
    assert resolver.check_action(SCOPE, OWNER, "demo", _on(DEMO)) is None
    assert resolver.check_action(SCOPE, OWNER, "demo", _on(TESTNET)) == "environment"
    assert resolver.suppressions_total["environment"] == 1


async def test_an_account_whose_environment_was_not_read_is_refused() -> None:
    """Fail closed (BQ-3): an account the read does not name has no environment, and is refused
    as one of another environment is, never taken for the process's."""
    resolver, _, _ = await _resolver()
    assert resolver.check_action(SCOPE, OWNER, "demo", _on(UNREAD)) == "environment"
    resolved = resolver.resolve(SCOPE, OWNER, "demo")  # the instances never include it either
    assert [i.account_id for i in resolved.instances] == [DEMO]


async def test_an_account_the_next_read_no_longer_names_loses_its_environment() -> None:
    """C-2.11 (R1C1-05): an account read in the process's environment at one refresh, then no
    longer named by the read at the next (deleted meanwhile), keeps no environment from the first:
    it is refused `environment`."""
    resolver, source, state = await _resolver()
    assert resolver.check_action(SCOPE, OWNER, "demo", _on(DEMO)) is None
    del source.envs[DEMO]
    await state.refresh(OWNER)
    assert resolver.check_action(SCOPE, OWNER, "demo", _on(DEMO)) == "environment"
