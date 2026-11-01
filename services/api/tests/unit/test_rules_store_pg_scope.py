"""#2291 (SR-051: the scope is part of the query): `PostgresRuleStore`'s scoped reads, statement by
statement, against a recording fake unit of work.

Every statement is classified, the Owner and grant variants of each read differ only in their
scope predicate, the Owner's predicate is the accounts store's own, and each read binds the scope's
values. Real SQL: tests/integration/storage/test_rules_store_pg.py.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from structlog.testing import capture_logs

from candleviewer import rules_store_pg as mod
from candleviewer.rules.ir.accounts import collect_account_ids
from candleviewer.rules.manager import GrantRead, OwnerRead, RuleRow, VersionRow
from candleviewer.rules_store_pg import PostgresRuleStore
from candleviewer.storage.repositories import accounts_sqlalchemy

CALLER = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001"
A, B = "a1000000-0000-4000-8000-000000000001", "b1000000-0000-4000-8000-000000000002"
RID = "10000000-0000-4000-8000-000000000001"
#: (owner statement, the other variant, the other variant's predicate), one pair per scoped read.
PAIRS = [
    (mod._PAGE_OWNER, mod._PAGE_GRANT, mod._GRANT_PRED),
    (mod._IDS_OWNER, mod._IDS_GRANT, mod._GRANT_PRED),
    (mod._NAME_OWNER, mod._NAME_OWN, mod._OWN_PRED),
]
Answer = Callable[[sa.TextClause, dict[str, Any]], list[Any] | bool]


class _Rel:
    """`unit_of_work()` recording each statement with its parameters; `answer` gives the rows (or
    the scalar) a statement returns, nothing by default."""

    def __init__(self, answer: Answer | None = None) -> None:
        self.calls: list[tuple[sa.TextClause, dict[str, Any]]] = []
        self.commits = 0
        self.answer: Answer = answer or (lambda _stmt, _params: [])

    def ran(self) -> list[sa.TextClause]:
        return [stmt for stmt, _ in self.calls]

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[Any]:
        async def execute(stmt: sa.TextClause, params: dict[str, Any] | None = None) -> Any:
            self.calls.append((stmt, dict(params or {})))
            got = self.answer(stmt, dict(params or {}))
            rows = got if isinstance(got, list) else []
            return SimpleNamespace(all=lambda: rows, scalar_one=lambda: got)

        async def commit() -> None:
            self.commits += 1

        yield SimpleNamespace(session=SimpleNamespace(execute=execute), commit=commit)


def _store(rel: _Rel) -> PostgresRuleStore:
    # The adapter takes the concrete SqlAlchemyRelationalRepository; `_Rel` mimics only its
    # unit_of_work(), so the nominal type cannot match.
    return PostgresRuleStore(rel)  # type: ignore[arg-type]  # structural fake, see above


def _rule_row(rid: str = RID) -> SimpleNamespace:
    return SimpleNamespace(
        id=rid, name="r", owner=CALLER, scope="global", mode="disabled", active_version_id=None,
        armed_by=None, disabled_reason=None, deleted=False, last_session="", last_editor="",
    )  # fmt: skip


def _statements() -> set[sa.TextClause]:
    return {v for v in vars(mod).values() if isinstance(v, sa.TextClause)}


def test_statement_inventory_is_fully_classified() -> None:
    owner, grant, rest = mod.OWNER_STATEMENTS, mod.GRANT_STATEMENTS, mod.UNSCOPED_STATEMENTS
    assert not (owner & grant or owner & rest or grant & rest)
    assert _statements() == owner | grant | rest


@pytest.mark.parametrize(("owner", "other", "predicate"), PAIRS, ids=["page", "ids", "name"])
def test_owner_and_grant_variants_differ_only_in_their_scope_predicate(
    owner: sa.TextClause, other: sa.TextClause, predicate: str
) -> None:
    o, g = owner.text, other.text
    assert o.count(mod._OWNER_PRED) == 1 and g.count(predicate) == 1
    assert o.replace(mod._OWNER_PRED, "<scope>") == g.replace(predicate, "<scope>")
    assert owner in mod.OWNER_STATEMENTS and other in mod.GRANT_STATEMENTS


@pytest.mark.parametrize(
    ("statement", "parts"),
    [
        (mod._PAGE_OWNER, (mod._PAGE_HEAD, mod._OWNER_PRED, mod._PAGE_TAIL)),
        (mod._PAGE_GRANT, (mod._PAGE_HEAD, mod._GRANT_PRED, mod._PAGE_TAIL)),
        (mod._IDS_OWNER, (mod._IDS_HEAD, mod._OWNER_PRED, " ORDER BY rl.id")),
        (mod._IDS_GRANT, (mod._IDS_HEAD, mod._GRANT_PRED, " ORDER BY rl.id")),
        (mod._NAME_OWNER, (mod._NAME_HEAD, mod._OWNER_PRED, ")")),
        (mod._NAME_OWN, (mod._NAME_HEAD, mod._OWN_PRED, ")")),
    ],
    ids=["page-owner", "page-grant", "ids-owner", "ids-grant", "name-owner", "name-own"],
)
def test_each_scoped_statement_is_written_out_as_its_parts(
    statement: sa.TextClause, parts: tuple[str, str, str]
) -> None:
    """The statements are written out whole (no string built by `+` at import); each stays equal,
    byte for byte, to its head, its scope predicate and its tail."""
    assert statement.text == "".join(parts)


def test_the_owner_predicate_is_the_accounts_stores() -> None:
    assert mod._OWNER_PRED == accounts_sqlalchemy._OWNER_PRED


def test_the_grant_predicate_is_ownership_and_every_version_within_the_grants() -> None:
    """Anyone else reads their own rule only while no version names an account outside the grants
    and none holds a set not computed yet; every version counts, not the active one alone."""
    assert mod._OWN_PRED == "rl.owner_user_id = CAST(:caller AS uuid)"
    head, _, rest = mod._GRANT_PRED.partition(" AND NOT EXISTS (")
    assert head == mod._OWN_PRED
    assert rest == (
        "SELECT 1 FROM rule_versions v WHERE v.rule_id = rl.id "
        "AND (v.account_refs IS NULL OR NOT v.account_refs <@ CAST(:granted AS text[])))"
    )


def test_statements_are_static_and_have_no_forbidden_shapes() -> None:
    for stmt in _statements():
        for bad in ("%(", "SELECT *", "OFFSET", "DELETE"):
            assert bad not in stmt.text
    added = mod.OWNER_STATEMENTS | mod.GRANT_STATEMENTS
    for stmt in added | {mod._VERSIONS_OF_PAGE, mod._UNFILLED, mod._FILL}:
        assert "{" not in stmt.text  # no template, and no literal array, in what #2291 adds
    for stmt in mod.OWNER_STATEMENTS | mod.GRANT_STATEMENTS:
        assert "FROM rules rl WHERE rl.deleted_at IS NULL AND " in stmt.text
    for stmt in (mod._PAGE_OWNER, mod._PAGE_GRANT):
        assert stmt.text.count("LIMIT") == 1 and stmt.text.endswith(" ORDER BY rl.id LIMIT :limit")
        assert "(CAST(:after AS uuid) IS NULL OR rl.id > CAST(:after AS uuid))" in stmt.text


async def test_a_grant_page_runs_the_grant_statement_bound_to_the_caller_and_sorted_grants() -> (
    None
):
    rel = _Rel(lambda stmt, _p: [_rule_row()] if stmt is mod._PAGE_GRANT else [])
    rows = await _store(rel).scoped_page(
        GrantRead(CALLER, frozenset({B, A})), mode="armed", level="account", after=RID, limit=3
    )
    assert [r.id for r in rows] == [RID]
    assert rel.ran() == [mod._UNFILLED, mod._PAGE_GRANT, mod._VERSIONS_OF_PAGE]
    page = {"caller": CALLER, "granted": [A, B], "mode": "armed", "level": "account"}
    assert rel.calls[1][1] == page | {"after": RID, "only": None, "limit": 3}
    assert rel.calls[2][1] == {"ids": [RID]}  # the page's own rows' versions only


async def test_an_owner_page_runs_the_owner_statement_bound_to_the_caller() -> None:
    rel = _Rel()
    assert (
        await _store(rel).scoped_page(
            OwnerRead(CALLER), mode=None, level=None, after=None, limit=2, only=RID
        )
        == []
    )
    assert rel.ran() == [mod._PAGE_OWNER]  # no fill, and no versions read for an empty page
    assert rel.calls[0][1] == {
        "caller": CALLER, "mode": None, "level": None, "after": None, "only": RID, "limit": 2,
    }  # fmt: skip


async def test_an_empty_grant_set_still_runs_the_grant_statement() -> None:
    """A caller with no grants still reads their own rules naming no account (`_visible`)."""
    rel = _Rel()
    store = _store(rel)
    await store.scoped_page(
        GrantRead(CALLER, frozenset()), mode=None, level=None, after=None, limit=1
    )
    assert await store.scoped_ids(GrantRead(CALLER, frozenset())) == frozenset()
    granted = [params.get("granted") for stmt, params in rel.calls if stmt in mod.GRANT_STATEMENTS]
    assert granted == [[], []]


@pytest.mark.parametrize(
    "scope", [GrantRead("u1", frozenset({A})), OwnerRead("u1")], ids=["grant", "owner"]
)
async def test_a_caller_that_is_not_a_uuid_runs_no_statement(scope: GrantRead | OwnerRead) -> None:
    rel = _Rel()
    store = _store(rel)
    assert await store.scoped_page(scope, mode=None, level=None, after=None, limit=5) == []
    assert await store.scoped_ids(scope) == frozenset()
    assert await store.name_taken(scope, "r", "") is False
    assert rel.calls == []


async def test_a_point_read_of_an_id_that_is_not_a_uuid_runs_no_statement() -> None:
    rel = _Rel()
    page = await _store(rel).scoped_page(
        GrantRead(CALLER, frozenset({A})), mode=None, level=None, after=None, limit=1, only="r-1"
    )
    assert page == [] and rel.calls == []


@pytest.mark.parametrize("after", ["", "not-a-rule", "10000000-0000-4000-8000-00000000000"])
async def test_a_cursor_that_is_not_a_uuid_is_refused_before_any_statement(after: str) -> None:
    rel = _Rel()
    with pytest.raises(ValueError):
        await _store(rel).scoped_page(
            OwnerRead(CALLER), mode=None, level=None, after=after, limit=2
        )
    assert rel.calls == []


async def test_the_name_lookup_runs_the_owner_or_the_ownership_statement() -> None:
    rel = _Rel(lambda stmt, _p: stmt is mod._NAME_OWN)
    store = _store(rel)
    assert await store.name_taken(GrantRead(CALLER, frozenset({A})), "alpha", RID) is True
    assert await store.name_taken(OwnerRead(CALLER), "alpha", "") is False
    assert rel.ran() == [mod._NAME_OWN, mod._NAME_OWNER]  # ownership decides: no fill
    assert [params for _, params in rel.calls] == [
        {"caller": CALLER, "name": "alpha", "exclude": RID},
        {"caller": CALLER, "name": "alpha", "exclude": None},
    ]


def _version(n: int, ir: dict[str, Any]) -> VersionRow:
    return VersionRow(str(UUID(int=n)), RID, n, ir, "h", "1.0.0", "", "", "")


async def test_put_writes_each_versions_account_set_from_the_walker() -> None:
    first = {"scope": {"account_ids": [B, A, B]}, "conditions": {}, "actions": []}
    second = {
        "scope": {"account_ids": []},
        "conditions": {"left": {"metric": "equity", "account_id": B}},
        "actions": [{"params": {"route": {"target_account_ids": [A.upper()]}}}],
    }
    row = RuleRow(RID, "r", CALLER, versions=[_version(1, first), _version(2, second)])
    rel = _Rel()
    await _store(rel).put(row)
    written = [params["refs"] for stmt, params in rel.calls if stmt is mod._INSERT_VERSION]
    assert written == [[A, B], sorted([A.upper(), B])]
    assert written == [sorted(set(collect_account_ids(v.ir))) for v in row.versions]


def _unfilled(*irs: dict[str, Any]) -> list[SimpleNamespace]:
    return [SimpleNamespace(id=f"{n}", ir=json.dumps(ir)) for n, ir in enumerate(irs, start=1)]


async def test_the_fill_writes_each_unfilled_version_once_before_the_first_grant_read() -> None:
    batches = [_unfilled({"scope": {"account_ids": [B, A]}}, {"conditions": {}}), []]
    rel = _Rel(lambda stmt, _p: batches.pop(0) if stmt is mod._UNFILLED else [])
    store = _store(rel)
    grant = GrantRead(CALLER, frozenset({A}))
    await store.scoped_ids(grant)
    fills = [params for stmt, params in rel.calls if stmt is mod._FILL]
    assert fills == [{"id": "1", "refs": [A, B]}, {"id": "2", "refs": []}]
    assert [p for s, p in rel.calls if s is mod._UNFILLED] == [{"n": mod.FILL_BATCH}] * 2
    assert rel.commits == 2
    rel.calls.clear()
    await store.scoped_page(grant, mode=None, level=None, after=None, limit=1)
    await store.scoped_ids(OwnerRead(CALLER))
    assert mod._UNFILLED not in rel.ran()  # once per process


async def test_the_owner_reads_and_the_name_lookup_run_no_fill() -> None:
    rel = _Rel()
    store = _store(rel)
    await store.scoped_page(OwnerRead(CALLER), mode=None, level=None, after=None, limit=1)
    await store.scoped_ids(OwnerRead(CALLER))
    await store.name_taken(GrantRead(CALLER, frozenset()), "r", "")
    assert mod._UNFILLED not in rel.ran() and mod._FILL not in rel.ran()


async def test_a_failed_fill_is_logged_by_count_and_tried_again_while_the_read_runs() -> None:
    def answer(stmt: sa.TextClause, _params: dict[str, Any]) -> list[Any]:
        if stmt is mod._FILL:
            raise RuntimeError("the database refused the write")
        return _unfilled({"scope": {"account_ids": [A]}}) if stmt is mod._UNFILLED else []

    rel = _Rel(answer)
    store = _store(rel)
    grant = GrantRead(CALLER, frozenset({A}))
    with capture_logs() as logs:
        await store.scoped_ids(grant)
    assert rel.ran()[-1] is mod._IDS_GRANT  # the read itself runs
    assert logs == [
        {"event": "rules.account_refs_fill_failed", "log_level": "error", "filled": 0,
         "error": "RuntimeError"},
    ]  # fmt: skip
    rel.calls.clear()
    rel.answer = lambda _stmt, _params: []
    await store.scoped_ids(grant)
    assert rel.ran() == [mod._UNFILLED, mod._IDS_GRANT]  # tried again, then done


def test_the_fill_batch_is_bounded() -> None:
    assert mod.FILL_BATCH == 500
    assert mod._UNFILLED.text.endswith("WHERE account_refs IS NULL ORDER BY id LIMIT :n")
    assert mod._FILL.text.endswith("WHERE id = CAST(:id AS uuid) AND account_refs IS NULL")


def test_rule_ids_order_as_text_and_as_uuid_alike() -> None:
    """The in-memory store pages by string order and Postgres by the uuid key: equal for the
    canonical ids the server issues."""
    ids = [str(UUID(int=n << k)) for n in (1, 3, 7) for k in (0, 64, 120)]
    assert sorted(ids) == [str(u) for u in sorted(UUID(i) for i in ids)]
