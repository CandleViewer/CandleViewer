"""The definition store's port and predicate, without a database (E28-T05 #909).

The port imports the stdlib and two driver-free sibling ports only (whose own imports
`test_trade_groups_port.py` pins), each error carries a name and nothing else (C-12.6), and the
grant predicate is the trade-group store's SR-E28-21 predicate over a definition's members. On
that store's fake unit of work: every read statement carries the scope, a read is capped and an
Owner's gated first, a read sees one snapshot and skips one with no member, logging its id, an
empty read-back denies a write.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import fields
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from structlog.testing import capture_logs

from candleviewer.db import models
from candleviewer.storage.errors import WriteAheadTimeout
from candleviewer.storage.repositories import trade_group_definitions as port
from candleviewer.storage.repositories import trade_group_definitions_sqlalchemy as pg
from candleviewer.storage.repositories import trade_groups_sqlalchemy as groups
from candleviewer.storage.repositories.accounts import GrantScope, OwnerScope
from tests.unit.storage import test_trade_groups_store as fake
from tests.unit.storage.test_trade_groups_port import _DRIVERS, _imports
from tests.unit.storage.test_trade_groups_store import _Rel as _GroupRel
from tests.unit.storage.test_trade_groups_store import _Result

_sql, _params, _marked = fake._sql, fake._params, fake._binds_as_markers
_ID, _CALLER, _ACCOUNT = UUID(int=1), UUID(int=2), UUID(int=3)
_GRANT, _OWNER = GrantScope(_CALLER, frozenset({_ACCOUNT})), OwnerScope(_CALLER)
_AT = datetime(2026, 10, 1, tzinfo=UTC)
_ROW: Any = (_ID, "Core3", "demo", None, None, _AT, _AT)
_NEW = port.NewDefinition(id=_ID, name="Core3", env="demo", members=())
_OTHER: Any = (UUID(int=4), "Pair", "demo", None, None, _AT, _AT)
_MEMBER: Any = (_ID, _ACCOUNT, True, "demo", False)
_FIRST = port.DefinitionRecord(port.DefinitionRow(*_ROW), (port.MemberRow(*_MEMBER[1:]),))


class _Rel(_GroupRel):
    """The group store's fake, which also answers the snapshot statement; `opened` holds each unit
    of work's first statement."""

    def __init__(self, *script: _Result | BaseException) -> None:
        super().__init__(*script)
        self.opened: list[Any] = []

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async with super().unit_of_work() as uow:
            run, first = uow.session.execute, len(self.opened)

            async def execute(stmt: Any, params: dict[str, Any] | None = None) -> Any:
                if len(self.opened) == first:
                    self.opened.append(stmt)
                return _Result() if stmt is pg.READ_SNAPSHOT else await run(stmt, params)

            uow.session.execute = execute
            yield uow


def _store(rel: _Rel, **caps: Any) -> pg.SqlAlchemyDefinitionStore:
    return pg.SqlAlchemyDefinitionStore(rel, **caps)  # type: ignore[arg-type]  # structural fake


def test_the_port_imports_no_driver() -> None:
    direct = _imports(port.__name__)
    assert {n for n in direct if n.startswith("candleviewer")} == {
        "candleviewer.storage.repositories.accounts",
        "candleviewer.storage.repositories.trade_groups",
    }
    assert {n.partition(".")[0] for n in direct} - {"candleviewer"} <= sys.stdlib_module_names
    assert not {n.partition(".")[0] for n in direct} & _DRIVERS


def test_an_error_carries_only_its_name_and_a_row_every_column_but_deleted_at() -> None:
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
    assert pg.DEFINITION_VISIBLE.text == over_members != groups._GRANT_VISIBLE


@pytest.mark.parametrize(
    "build",
    [pg.definition_statement, pg.members_statement, lambda s, _id: pg.page_statement(s, None, 10)],
)
def test_every_read_statement_carries_the_scope_and_binds_the_caller(build: Any) -> None:
    grant, owner = build(_GRANT, _ID), build(_OWNER, _ID)
    assert _marked(pg.DEFINITION_VISIBLE.text) in _marked(_sql(grant))
    assert (_params(grant)["caller"], _params(grant)["granted"]) == (str(_CALLER), [str(_ACCOUNT)])
    assert _marked(groups._OWNER_PRED) in _marked(_sql(owner))
    assert "user_account_access" not in _sql(owner) and _params(owner)["caller"] == str(_CALLER)


async def test_a_grant_read_is_all_or_nothing_across_its_two_statements() -> None:
    """A grant frozen between the definition and its members reads nothing (SR-E28-21)."""
    vanished = _Rel(_Result([_ROW]), _Result([]))
    assert await _store(vanished).get(_GRANT, _ID) is None
    assert len(vanished.calls) == 2 and vanished.commits == 0


async def test_a_read_is_capped_an_owner_gated_first_and_an_empty_grant_runs_no_sql() -> None:
    grant, owner, empty = _Rel(_Result([])), _Rel(_Result(), _Result([])), _Rel()
    assert await _store(grant).get(_GRANT, _ID) is None and grant.caps == [{"timeout": "2000"}]
    assert await _store(owner).get(_OWNER, _ID) is None and owner.calls[0] is groups.OWNER_GATE
    assert await _store(empty).get(GrantScope(_CALLER, frozenset()), _ID) is None
    assert empty.calls == empty.caps == []


async def test_a_write_whose_read_back_finds_nothing_is_denied() -> None:
    """The read-back carries the owner predicate: an Owner whose role lapsed after the gate (then
    the insert or the row lock) reads nothing back, and nothing commits or is written ahead."""
    rel, hook = _Rel(*[_Result(), _Result([_ROW]), _Result([])] * 3), AsyncMock()
    for write in (
        _store(rel).create(_OWNER, _NEW, write_ahead=hook),
        _store(rel).replace(_OWNER, _ID, _NEW, expected_updated_at=None, write_ahead=hook),
        _store(rel).soft_delete(_OWNER, _ID, write_ahead=hook),
    ):
        with pytest.raises(port.DefinitionScopeDeniedError):
            await write
    assert rel.commits == 0 and rel.rollbacks == 3 and hook.await_count == 0


async def test_the_store_runs_under_the_caps_it_is_given() -> None:
    """The root's caps: a statement cap, an int of at least 1, and a write-ahead bound."""
    for timeout in (0, -1, True, 2.5, "2000"):
        with pytest.raises(ValueError, match="statement_timeout_ms"):
            _store(_Rel(), statement_timeout_ms=timeout)
    rel, late = _Rel(_Result([])), _Rel(_Result(), _Result(), _Result([_ROW]), _Result([]))
    assert await _store(rel, statement_timeout_ms=750).get(_GRANT, _ID) is None
    store = _store(late, audit_timeout_s=0.01)

    async def hang(*_: object) -> None:  # only the bound ends it
        await asyncio.Event().wait()

    with pytest.raises(WriteAheadTimeout):  # its 0.01 s bound, never the 5 s default
        async with asyncio.timeout(1):
            await store.create(_OWNER, _NEW, write_ahead=hang)
    assert (rel.caps, late.commits, late.rollbacks) == ([{"timeout": "750"}], 0, 1)


async def test_a_page_reads_its_members_in_one_statement_and_drops_one_that_lost_them() -> None:
    """A read skips one that read no member, logging its id alone (C-12.6): in one snapshot, one
    stored with none, which the record would 503. A page answers the others, a get is a 404, and
    a write's read-back keeps it."""
    grant = _Rel(_Result([_ROW, _OTHER]), _Result([_MEMBER]))
    with capture_logs() as logs:
        assert await _store(grant).page(_GRANT, after=("Core", _ID), limit=2) == (_FIRST,)
        owner = _Rel(_Result(), _Result([_ROW, _OTHER]), _Result([_MEMBER]))  # the gate first
        assert await _store(owner).page(_OWNER, after=None, limit=2) == (_FIRST,)
        gone = _Rel(_Result(), _Result([_ROW]), _Result([]))
        assert await _store(gone).get(_OWNER, _ID) is None
    assert "trade_group_definitions.id IN ($3::UUID, $4::UUID)" in _sql(grant.calls[1])
    skipped = {"event": "trade_group_definition.read_skipped", "log_level": "warning"}
    assert logs == [skipped | {"definition_id": str(key)} for key in (_OTHER[0], _OTHER[0], _ID)]
    empty = _Rel()  # an empty grant runs no SQL
    assert await _store(empty).page(GrantScope(_CALLER, frozenset()), after=None, limit=2) == ()
    assert empty.calls == empty.caps == []


async def test_a_read_sees_one_snapshot_and_a_write_reads_committed() -> None:
    """A read's statements share one snapshot, set before any query fixes it, so a definition
    deleted between them is read whole and a page is short only at the listing's end; a write's
    row lock must see the last commit, so it keeps READ COMMITTED."""
    reads = _Rel(_Result([_ROW]), _Result([_MEMBER]), _Result([]))
    assert await _store(reads).get(_GRANT, _ID) == _FIRST
    assert await _store(reads).page(_GRANT, after=None, limit=2) == ()
    write = _Rel(_Result(), _Result([]))  # the owner gate, then the row lock: not live
    assert await _store(write).soft_delete(_OWNER, _ID, write_ahead=AsyncMock()) is None
    assert (reads.opened, write.opened) == ([pg.READ_SNAPSHOT] * 2, [groups.SET_TIMEOUT])
    assert pg.READ_SNAPSHOT.text == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
