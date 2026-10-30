"""Integration (E28-X03, #976): the matrix's refused cells on a migrated Postgres 16, each proven to
change no table a route could reach by a per-table row-hash checksum taken before and after it.

The RBAC pack's real `create_app()` (`build_world`) with the real backend's E28 stores over the
container: the profile store, the accounts, the definitions and the group reads, each built by
its own wiring from settings pointed at the database. The E28 seed (`tests/fixtures/e28/seed.sql`)
is the data, and `manager_with_grant` is granted its E28-A and E28-C, so each situation names
seeded rows: granted (A, Pair, the fired group), foreign (B), mixed (Core3). A foreign or mixed
group does not exist in the seed, so those cells read an absent id, which answers alike.

Every table a route can reach is named in `TABLES`; `audit_log` is left out (each refusal appends
to it, and the in-memory suite asserts that record). A table of the families those names come from
that the list misses fails `test_the_checksummed_tables_cover_every_reachable_family`. The
preview's scope cells are left to the in-memory suite: the preview reads no table before its scope
check and writes none at all (`test_trade_group_preview_read_only_pg.py`). Needs Docker
(testcontainers); CI `integration` runs it.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from pydantic import SecretStr

import candleviewer.app as appmod
import candleviewer.oms_wiring as oms_wiring
import candleviewer.profiles_wiring as profiles_wiring
import candleviewer.trade_groups_wiring as groups_wiring
from candleviewer.api.profile_writes import ProfileWrites
from candleviewer.storage.repositories.relational_sqlalchemy import SqlAlchemyRelationalRepository
from tests.contract._profile_writes_world import Limits
from tests.contract.rbac import rbac_harness as rbac
from tests.contract.test_account_profile_writes_provider import _ALT, _RISK
from tests.integration import _refused
from tests.security.e28 import _cells as cells
from tests.security.e28.conftest import live_target_refusal
from tests.unit.api.test_trade_group_definition_create import payload
from tests.unit.api.test_trade_group_preview_route import body

pytestmark = pytest.mark.integration
if (_LIVE := live_target_refusal(os.environ)) is not None:  # the suite's guard, here too
    pytest.exit(f"E28-X03 security suite refused to run: {_LIVE}", returncode=4)

pg_dsn = _refused.pg_dsn  # the module-scoped Postgres 16, migrated; its database is named `test`
_SEED = Path(__file__).resolve().parents[5] / "tests" / "fixtures" / "e28" / "seed.sql"
#: Every table an E28 route reads or writes, or a write of one could reach by a trigger (a
#: relaxing profile save's Owner notice is a `system_events` row, SR-E28-01).
TABLES = (
    "exchange_accounts user_account_access account_profiles account_profile_revisions"
    " trade_group_definitions trade_group_definition_members trade_groups trade_group_legs"
    " positions position_snapshots orders order_events executions system_events"
).split()
#: The families those tables belong to: a new table of one must be listed above (or excluded).
_FAMILIES = ("exchange_account", "user_account", "account_profile", "trade_group", "position",
             "order", "execution", "system_event")  # fmt: skip
_EXCLUDED = frozenset({"audit_log"})
_E28 = "e28f0000-0000-4000-8000-0000000000{}"
D1, D2, D3 = (uuid.UUID(_E28.format(n)) for n in ("d1", "d2", "d3"))
_IDS = {
    "accountId": {"granted": D1, "foreign": D2},
    "profileId": {"granted": uuid.UUID(_E28.format("c1")), "foreign": uuid.UUID(_E28.format("c2"))},
    "tradeGroupId": {"granted": uuid.UUID(_E28.format("b1"))},
    "definitionId": {
        "granted": uuid.UUID(_E28.format("a2")),
        "mixed": uuid.UUID(_E28.format("a1")),
    },
}
_ACCOUNTS = {"granted": (D1,), "foreign": (D2,), "mixed": (D1, D2), "-": ()}
_ABSENT = uuid.UUID(int=0xAB5E)


def _conn(dsn: str) -> psycopg.Connection[tuple[Any, ...]]:
    return psycopg.connect(dsn.replace("postgresql+asyncpg", "postgresql"), autocommit=True)


def checksums(dsn: str) -> dict[str, tuple[Any, ...] | None]:
    """Each table's row count and an order-free hash of its rows, whole."""
    query = sql.SQL(
        "SELECT count(*), coalesce(md5(string_agg(md5(t::text), '' ORDER BY md5(t::text))), '')"
        " FROM {} AS t"
    )
    with _conn(dsn) as c:
        return {t: c.execute(query.format(sql.Identifier(t))).fetchone() for t in TABLES}


class _Pools:
    """Every relational pool the wiring builds, so each is disposed on the loop that used it."""

    def __init__(self, real: Any) -> None:
        self.real, self.made = real, list[Any]()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.made.append(self.real(*args, **kwargs))
        return self.made[-1]


@pytest.fixture(scope="module")
def served(pg_dsn: str) -> Iterator[tuple[rbac.World, Any]]:
    with _conn(pg_dsn) as c:
        c.execute(_SEED.read_bytes())  # the file's own BEGIN ... COMMIT
    pools = _Pools(SqlAlchemyRelationalRepository)
    with pytest.MonkeyPatch.context() as mp:
        for module in (oms_wiring, profiles_wiring, groups_wiring, appmod):
            mp.setattr(module, "SqlAlchemyRelationalRepository", pools)

        def real(settings: Any) -> Any:
            return settings.model_copy(
                update={"storage_backend": "real", "pg_dsn": SecretStr(pg_dsn)}
            )

        wire, accounts = profiles_wiring.wire_profiles, appmod._build_accounts_counts
        definitions, groups = groups_wiring.definition_store, oms_wiring.group_reads
        mp.setattr(appmod, "wire_profiles", lambda s, m, b: wire(real(s), m, b))
        mp.setattr(appmod, "_build_accounts_counts", lambda s: accounts(real(s)))
        mp.setattr(appmod, "definition_store", lambda s: definitions(real(s)))
        mp.setattr(appmod, "group_reads", lambda s: groups(real(s)))
        mp.setattr(appmod, "profile_writes", lambda w, _c, **_k: ProfileWrites(
            w.repository, w.accounts, Limits(), w.rules, "demo"))  # fmt: skip
        world = rbac.build_world(mp)
        world.resolver.extra["manager_with_grant"] = (D1, D3)
        with world.client as client:
            assert client.portal is not None
            try:
                yield world, client
            finally:
                for pool in pools.made:
                    client.portal.call(pool.dispose)


def _request(cell: cells.Cell) -> tuple[str, str, Any]:
    method, template = cell.key.split(" ", 1)
    ids = {name: by.get(cell.at, _ABSENT) for name, by in _IDS.items()}
    sent: Any = None
    if cell.key == cells.PREVIEW:
        sent = body(*_ACCOUNTS[cell.at])
    elif template.startswith("/trade-group-definitions") and method in ("POST", "PUT"):
        sent = payload(*_ACCOUNTS[cell.at], name="E28 written")
    elif template.endswith("/profiles") and method == "POST":
        sent = _RISK
    elif template.endswith("{profileId}") and method == "PUT":
        sent = _ALT
    elif template.endswith("/default-profile") and method == "PUT":
        sent = {"profile_id": str(ids["profileId"])}
    return method, template.format(**ids), sent


_DENIED = [c for c in cells.cells() if c.denied and c.expect != "403 account_scope_denied"]


@pytest.mark.parametrize("cell", [pytest.param(c, id=c.id) for c in _DENIED])
def test_a_refused_cell_changes_no_table_on_postgres(
    served: tuple[rbac.World, Any], pg_dsn: str, cell: cells.Cell
) -> None:
    _, client = served
    method, path, sent = _request(cell)
    headers = {**rbac.bearer(cell.actor), "if-match": 'W/"0"'}
    before = checksums(pg_dsn)
    resp = client.request(method, path, json=sent, headers=headers)
    assert rbac.observed(resp) == cell.expect, cell.id
    assert checksums(pg_dsn) == before, f"{cell.id}: a refused call changed a table"


def test_the_checksummed_tables_cover_every_reachable_family(pg_dsn: str) -> None:
    patterns = [f"{family}%" for family in _FAMILIES]
    with _conn(pg_dsn) as c:
        found = {
            name
            for (name,) in c.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                " AND table_name LIKE ANY(%s)",
                (patterns,),
            ).fetchall()
        }
    assert set(TABLES) <= found, f"listed but not in the schema: {sorted(set(TABLES) - found)}"
    missed = sorted(found - set(TABLES) - _EXCLUDED)
    assert not missed, f"tables of a reachable family with no checksum: {missed}"
