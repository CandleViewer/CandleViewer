"""#4834 (G-16): the stored-rule cap's count in `PostgresRuleStore`, against a recording fake unit
of work.

One static statement for every role, by ownership alone: the caller's own rules that are not
deleted, readable or not (22 `createRule`). It is written out whole, equal to its head and SR-051's
ownership predicate, and classified with the ownership reads (#2291's inventory). Real SQL:
tests/integration/storage/test_rules_store_pg.py.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa

from candleviewer import rules_store_pg as mod
from candleviewer.rules_store_pg import PostgresRuleStore

CALLER = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001"


class _Rel:
    """`unit_of_work()` recording each statement with its parameters; each one answers `held` as
    its one scalar."""

    def __init__(self, held: int = 0) -> None:
        self.calls: list[tuple[sa.TextClause, dict[str, Any]]] = []
        self.held = held

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: sa.TextClause, params: dict[str, Any] | None = None) -> Any:
            self.calls.append((stmt, dict(params or {})))
            return SimpleNamespace(scalar_one=lambda: self.held)

        yield SimpleNamespace(session=SimpleNamespace(execute=execute))


def _store(rel: _Rel) -> PostgresRuleStore:
    # The adapter takes the concrete SqlAlchemyRelationalRepository; `_Rel` mimics only its
    # unit_of_work(), so the nominal type cannot match.
    return PostgresRuleStore(rel)  # type: ignore[arg-type]  # structural fake, see above


def test_the_count_is_written_out_as_its_parts() -> None:
    """One literal, no string built at import: the live-row head, then the ownership predicate the
    name lookup reads, byte for byte."""
    assert mod._COUNT_OWN.text == "".join((mod._COUNT_HEAD, mod._OWN_PRED))
    assert mod._COUNT_OWN.text == (
        "SELECT count(*) FROM rules rl WHERE rl.deleted_at IS NULL AND "
        "rl.owner_user_id = CAST(:caller AS uuid)"
    )


def test_the_count_is_classified_with_the_ownership_reads() -> None:
    """Every role runs it, the Owner's included, so it names no role and no grant: it sits beside
    the name lookup's ownership read, never among the Owner role's statements."""
    assert {mod._COUNT_OWN, mod._NAME_OWN} <= mod.GRANT_STATEMENTS
    assert mod._COUNT_OWN not in mod.OWNER_STATEMENTS | mod.UNSCOPED_STATEMENTS
    assert mod._OWNER_PRED not in mod._COUNT_OWN.text
    assert ":granted" not in mod._COUNT_OWN.text


async def test_the_count_runs_its_one_statement_bound_to_the_caller() -> None:
    rel = _Rel(held=7)
    assert await _store(rel).count_owned_live(CALLER) == 7
    assert rel.calls == [(mod._COUNT_OWN, {"caller": CALLER})]  # ownership decides: no fill


@pytest.mark.parametrize("owner", ["", "u1", "not-a-user"])
async def test_an_owner_id_that_is_not_a_uuid_counts_none_and_runs_no_statement(
    owner: str,
) -> None:
    rel = _Rel(held=3)
    assert await _store(rel).count_owned_live(owner) == 0
    assert rel.calls == []
