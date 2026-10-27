"""The definition store's port and predicate, without a database (E28-T05 #909).

The port imports the stdlib and two driver-free sibling ports only (whose own imports
`test_trade_groups_port.py` pins), each error carries a name and nothing else (C-12.6), and the
grant predicate is the trade-group store's SR-E28-21 predicate over a definition's members, read
all or nothing across the store's two statements (its fake unit of work).
"""

from __future__ import annotations

import sys
from dataclasses import fields
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from candleviewer.db import models
from candleviewer.storage.repositories import trade_group_definitions as port
from candleviewer.storage.repositories import trade_group_definitions_sqlalchemy as pg
from candleviewer.storage.repositories import trade_groups_sqlalchemy as groups
from candleviewer.storage.repositories.accounts import GrantScope
from tests.unit.storage.test_trade_groups_port import _DRIVERS, _imports
from tests.unit.storage.test_trade_groups_store import _Rel, _Result


def test_the_port_imports_no_driver() -> None:
    direct = _imports(port.__name__)
    assert {n for n in direct if n.startswith("candleviewer")} == {
        "candleviewer.storage.repositories.accounts",
        "candleviewer.storage.repositories.trade_groups",
    }
    assert {n.partition(".")[0] for n in direct} - {"candleviewer"} <= sys.stdlib_module_names
    assert not {n.partition(".")[0] for n in direct} & _DRIVERS


def test_each_error_carries_its_name_and_nothing_else() -> None:
    conflict = port.DefinitionConflictError("ux_tgd_name")
    rule = port.DefinitionRuleError("trg_tgdm_env")
    assert (conflict.constraint, conflict.args, rule.rule, rule.args) == (
        "ux_tgd_name", ("ux_tgd_name",), "trg_tgdm_env", ("trg_tgdm_env",),
    )  # fmt: skip
    for error in (port.DefinitionStaleError(), port.DefinitionScopeDeniedError()):
        assert isinstance(error, port.DefinitionStoreError) and error.args == ()
    assert not port.DEFINITION_RULES & port.DEFINITION_CONFLICTS
    columns = [c.name for c in models.trade_group_definitions.c if c.name != "deleted_at"]
    assert [f.name for f in fields(port.DefinitionRow)] == columns


def test_the_grant_predicate_is_the_group_stores_over_a_definitions_members() -> None:
    legs = groups._GRANT_VISIBLE.replace("trade_group_legs", "trade_group_definition_members")
    over_members = legs.replace(
        "vl.trade_group_id = trade_groups.id", "vl.definition_id = trade_group_definitions.id"
    )
    assert pg.DEFINITION_VISIBLE == over_members != groups._GRANT_VISIBLE


async def test_a_grant_read_is_all_or_nothing_across_its_two_statements() -> None:
    """A grant frozen between the definition and its members reads nothing (SR-E28-21)."""
    at = datetime(2026, 10, 1, tzinfo=UTC)
    row: Any = (UUID(int=1), "Core3", "demo", None, None, at, at)
    vanished = _Rel(_Result([row]), _Result([]))
    store = pg.SqlAlchemyDefinitionStore(vanished)  # type: ignore[arg-type]  # structural fake
    assert await store.get(GrantScope(UUID(int=2), frozenset({UUID(int=3)})), UUID(int=1)) is None
    assert len(vanished.calls) == 2 and vanished.commits == 0
